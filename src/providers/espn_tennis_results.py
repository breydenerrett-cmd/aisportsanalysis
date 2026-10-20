"""ESPN's public tennis scoreboards as a free ATP/WTA results feed (a `tennis_results.ResultsFeed`).

WHY THIS EXISTS
---------------
The Odds API `/scores` does not list tennis, so a member dog's tennis bet had no result source and could only
void after 72 hours. ESPN publishes ATP and WTA scoreboards as plain JSON, free and keyless:

    https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard?dates=YYYYMMDD
    https://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard?dates=YYYYMMDD

WHAT REALLY WORKS (checked 2026-10-19 against live responses)
-------------------------------------------------------------
* `?dates=` returns every tournament ACTIVE that day with its WHOLE draw (all rounds, past and scheduled), so
  one response holds several days of matches. A competition's own `startDate` says when it was scheduled.
* Coverage is the tours ESPN calls ATP and WTA: Grand Slams, Masters/WTA 1000, 500s and 250s, qualifying
  rounds, and the WTA 125 events it lists. There is NO Challenger or ITF scoreboard: the slugs `challenger`,
  `itf`, `atp-challenger`, `wta-125` all answer 400. A Challenger/ITF match on the odds feed therefore never
  matches a result here and voids after 72 hours; it is never guessed. (`/tennis/all/scoreboard` exists but
  lists the same ATP/WTA tournaments.)
* Status names seen: STATUS_FINAL, STATUS_RETIRED, STATUS_WALKOVER, STATUS_CANCELED (doubles only so far),
  STATUS_IN_PROGRESS, STATUS_SCHEDULED. A match carries per-set games in `linescores` and a winner flag on
  each competitor. Doubles are listed beside singles and are skipped (the odds feed prices singles).
* NO FINISH TIME. ESPN gives a scheduled `startDate` and nothing for when a match ended, so
  `completed_utc` below is the moment OUR fetch first saw the match settled (an upper bound on the true finish,
  never earlier than it), and `start_utc` carries the schedule. A back-fill run stamps its own fetch time.
  That keeps every row point-in-time: nothing here claims to have been known before it was observed.

HOW A MATCH SETTLES (the one rule, documented here and in docs/ALLSPORTS_DOGS.md)
------------------------------------------------------------------------------
Common book rules for a match-winner (moneyline) bet:
* Played to the end (STATUS_FINAL, one competitor flagged the winner): the winner wins.
* Retirement / default / disqualification AFTER at least one set was COMPLETED: the player who advanced wins
  the bet. A set is completed by the games (6-0..6-4, 7-5, 7-6, or any lead of two from six games on,
  super-tiebreak 10-x included), not by ESPN's per-set flag, which is not set reliably on the last set.
* Retirement BEFORE a set completes: VOID (stake returned).
* Walkover (the match was never played): VOID.
* Cancelled: VOID. Postponed, suspended, delayed, scheduled, in progress: not settled yet (pending).
* Anything else (a final with no winner flagged, an unknown status): UNRESOLVED, never graded.

Plain `urllib` with an ordinary User-Agent, one request at a time, no retry storm. A response that is not JSON
(a browser check page) stops the run: nothing here tries to pass one.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, List, Optional, Sequence, Tuple

from src.providers.tennis_results import ResultsFeed, TennisResultsError

SOURCE = "espn"
BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/tennis"
TOURS = ("atp", "wta")
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36")
TIMEOUT_SECONDS = 30
POLITE_DELAY_SECONDS = 0.5

# settlement states
GRADED, VOID, PENDING, UNRESOLVED = "graded", "void", "pending", "unresolved"

_FINAL = {"STATUS_FINAL"}
_RETIRED_WORDS = ("RETIRE", "DEFAULT", "DISQUALIF", "FORFEIT")
_WALKOVER_WORDS = ("WALKOVER", "WALK_OVER")
_CANCELLED_WORDS = ("CANCEL", "ABANDON")


class EspnTennisError(TennisResultsError):
    """ESPN could not be read (network, not JSON, or a browser check). Nothing is recorded for the run."""


@dataclass(frozen=True)
class TennisMatch:
    """One singles competition as ESPN lists it. `a` and `b` follow ESPN's own `order` (1 then 2)."""
    tour: str
    tournament: str
    espn_event_id: str
    match_id: str
    start_utc: Optional[str]
    status: str                    # ESPN's status name, e.g. STATUS_RETIRED
    state: str                     # ESPN's pre / in / post
    player_a: str
    player_b: str
    winner: Optional[str]          # "a", "b" or None
    sets: Tuple[Tuple[int, int], ...] = ()      # games (a, b) per set, in order
    note: str = ""
    round_name: str = ""

    @property
    def score_text(self) -> str:
        if self.note:
            return self.note
        return " ".join(f"{a}-{b}" for a, b in self.sets)


# ---------------------------------------------------------------------------
# sets and settlement (pure)
# ---------------------------------------------------------------------------

def set_completed(games_a: int, games_b: int) -> bool:
    """Whether a set at this games score is over: a lead of two from six games on (6-4, 7-5, 13-11, a 10-8
    super-tiebreak), or a 7-6 tiebreak set. 6-6, 6-5, 5-3 and 0-0 are not."""
    hi, lo = max(games_a, games_b), min(games_a, games_b)
    return (hi >= 6 and hi - lo >= 2) or (hi == 7 and lo == 6)


def completed_sets(sets: Sequence[Tuple[int, int]]) -> int:
    return sum(1 for a, b in sets if set_completed(a, b))


def classify_status(status: str) -> str:
    """'final', 'retired', 'walkover', 'cancelled', 'pending' or 'unknown' for an ESPN status name."""
    name = str(status or "").upper()
    if name in _FINAL:
        return "final"
    if any(word in name for word in _WALKOVER_WORDS):
        return "walkover"
    if any(word in name for word in _RETIRED_WORDS):
        return "retired"
    if any(word in name for word in _CANCELLED_WORDS):
        return "cancelled"
    if name in ("STATUS_SCHEDULED", "STATUS_IN_PROGRESS", "STATUS_POSTPONED", "STATUS_SUSPENDED",
                "STATUS_DELAYED", "STATUS_RAIN_DELAY", "STATUS_HALFTIME", "STATUS_END_PERIOD",
                "STATUS_PRE_GAME", "STATUS_UNKNOWN"):
        return "pending"
    return "unknown"


def settlement(match: TennisMatch) -> dict:
    """{state, winner, reason}: what a moneyline bet on this match becomes. Pure; see the module docstring."""
    kind = classify_status(match.status)
    if kind == "pending":
        return {"state": PENDING, "winner": None, "reason": f"not settled yet ({match.status})"}
    if kind == "walkover":
        return {"state": VOID, "winner": None,
                "reason": "walkover: the match was not played, so a match-winner bet is void"}
    if kind == "cancelled":
        return {"state": VOID, "winner": None, "reason": f"the match was cancelled ({match.status})"}
    if kind == "final":
        if match.winner in ("a", "b"):
            return {"state": GRADED, "winner": match.winner, "reason": f"completed ({match.score_text})"}
        return {"state": UNRESOLVED, "winner": None,
                "reason": "ESPN lists the match final but flags no single winner"}
    if kind == "retired":
        if match.winner not in ("a", "b"):
            return {"state": UNRESOLVED, "winner": None,
                    "reason": f"{match.status} but ESPN flags no single winner"}
        done = completed_sets(match.sets)
        if done >= 1:
            return {"state": GRADED, "winner": match.winner,
                    "reason": (f"retirement after {done} completed set(s): the player who advanced "
                               f"wins the bet ({match.score_text})")}
        return {"state": VOID, "winner": None,
                "reason": f"retired before a set was completed: void ({match.score_text})"}
    return {"state": UNRESOLVED, "winner": None, "reason": f"unrecognised ESPN status {match.status!r}"}


# ---------------------------------------------------------------------------
# the scoreboard document (pure)
# ---------------------------------------------------------------------------

def _text(value) -> str:
    return "" if value is None or isinstance(value, bool) else str(value).strip()


def _games(entry) -> Optional[int]:
    value = entry.get("value") if isinstance(entry, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _iso_z(value) -> Optional[str]:
    """ESPN writes '2026-10-17T10:30Z'; return a full ISO-8601 UTC string, or None when unreadable."""
    text = _text(value)
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_scoreboard(doc, tour: str) -> List[TennisMatch]:
    """Every SINGLES competition of every tournament on one ESPN scoreboard document.

    A competition with fewer or more than two athlete competitors (doubles, or a bye that ESPN lists with a
    roster) is skipped, as is one with no id. A competitor without a name is kept as ''; it can never match."""
    out: List[TennisMatch] = []
    if not isinstance(doc, dict):
        return out
    for event in doc.get("events") or []:
        if not isinstance(event, dict):
            continue
        for group in event.get("groupings") or []:
            if not isinstance(group, dict):
                continue
            label = _text(((group.get("grouping") or {}).get("displayName"))).lower()
            if "singles" not in label:
                continue
            for comp in group.get("competitions") or []:
                match = _parse_competition(comp, event, tour)
                if match is not None:
                    out.append(match)
    return out


def _parse_competition(comp, event, tour) -> Optional[TennisMatch]:
    if not isinstance(comp, dict) or not _text(comp.get("id")):
        return None
    competitors = [c for c in comp.get("competitors") or [] if isinstance(c, dict)]
    if len(competitors) != 2 or any(not isinstance(c.get("athlete"), dict) for c in competitors):
        return None
    competitors.sort(key=lambda c: c.get("order") if isinstance(c.get("order"), int) else 99)
    names, sets_by_player, winners = [], [], []
    for c in competitors:
        athlete = c["athlete"]
        names.append(_text(athlete.get("displayName") or athlete.get("fullName")))
        sets_by_player.append([_games(s) for s in c.get("linescores") or []])
        winners.append(c.get("winner") if isinstance(c.get("winner"), bool) else None)
    n_sets = min(len(sets_by_player[0]), len(sets_by_player[1]))
    sets = tuple((sets_by_player[0][i], sets_by_player[1][i]) for i in range(n_sets)
                 if sets_by_player[0][i] is not None and sets_by_player[1][i] is not None)
    if winners[0] is True and winners[1] is not True:
        winner = "a"
    elif winners[1] is True and winners[0] is not True:
        winner = "b"
    else:
        winner = None
    status = comp.get("status") if isinstance(comp.get("status"), dict) else {}
    stype = status.get("type") if isinstance(status.get("type"), dict) else {}
    notes = comp.get("notes") if isinstance(comp.get("notes"), list) else []
    note = _text(notes[0].get("text")) if notes and isinstance(notes[0], dict) else ""
    return TennisMatch(
        tour=tour, tournament=_text(event.get("name")), espn_event_id=_text(event.get("id")),
        match_id=_text(comp.get("id")), start_utc=_iso_z(comp.get("startDate") or comp.get("date")),
        status=_text(stype.get("name")), state=_text(stype.get("state")), player_a=names[0], player_b=names[1],
        winner=winner, sets=sets, note=note, round_name=_text((comp.get("round") or {}).get("displayName")))


# ---------------------------------------------------------------------------
# the transport
# ---------------------------------------------------------------------------

def default_get_json(url: str) -> dict:
    """Plain urllib GET. A non-JSON answer (a browser check or an error page) raises and is never worked around."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise EspnTennisError(f"ESPN tennis scoreboard answered HTTP {exc.code}") from None
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise EspnTennisError(f"could not reach ESPN: {type(exc).__name__}") from None
    try:
        return json.loads(body.decode("utf-8", errors="replace"))
    except ValueError:
        raise EspnTennisError("ESPN did not return JSON (a browser check?); stopped, nothing recorded") from None


def scoreboard_url(tour: str, date_iso: str) -> str:
    """The scoreboard URL for a tour and an ISO date (YYYY-MM-DD)."""
    return f"{BASE_URL}/{tour}/scoreboard?dates={str(date_iso).replace('-', '')}"


class EspnTennisFeed(ResultsFeed):
    """ATP and WTA results from ESPN, in the `ResultsFeed` row shape plus the fields settlement needs.

    `get_json(url) -> dict` and `sleep` are injectable so tests never touch the network; `now` is the clock
    that stamps `completed_utc`."""

    def __init__(self, get_json: Optional[Callable[[str], dict]] = None, sleep: Optional[Callable] = None,
                 now: Optional[Callable[[], datetime]] = None, tours: Sequence[str] = TOURS):
        super().__init__(name=SOURCE)
        self._get_json = get_json or default_get_json
        self._sleep = sleep or time.sleep
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._tours = tuple(tours)
        self._made_a_request = False
        self.notes: List[str] = []

    def observed_utc(self) -> str:
        return self._now().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def fetch_matches(self, date_iso: str) -> List[TennisMatch]:
        """Every singles match on the ATP and WTA scoreboards for a date (whole draws, every status)."""
        out: List[TennisMatch] = []
        for tour in self._tours:
            if self._made_a_request:
                self._sleep(POLITE_DELAY_SECONDS)
            self._made_a_request = True
            doc = self._get_json(scoreboard_url(tour, date_iso))
            matches = parse_scoreboard(doc, tour)
            self.notes.append(f"{tour} {date_iso}: {len(matches)} singles match(es)")
            out.extend(matches)
        return out

    def fetch_results(self, date: str) -> list:
        """Settled singles matches (graded or void) SCHEDULED on `date` (UTC), as ResultsFeed rows.

        winner is 'a' or 'b' for a graded match and None for a void one (see `outcome`)."""
        observed = self.observed_utc()
        rows = []
        for match in self.fetch_matches(date):
            if not (match.start_utc or "").startswith(str(date)):
                continue
            verdict = settlement(match)
            if verdict["state"] not in (GRADED, VOID):
                continue
            rows.append(result_row(match, verdict, observed))
        return rows


def result_row(match: TennisMatch, verdict: dict, observed_utc: str) -> dict:
    """One settled match as a ResultsFeed row."""
    return {
        "event_id": f"espn:{match.match_id}", "tournament": match.tournament,
        "player_a": match.player_a, "player_b": match.player_b, "winner": verdict["winner"],
        "outcome": "win" if verdict["state"] == GRADED else "void",
        "void_reason": None if verdict["state"] == GRADED else verdict["reason"],
        "score": match.score_text, "status": match.status, "tour": match.tour,
        "start_utc": match.start_utc, "completed_utc": observed_utc, "completed_utc_basis": "observed",
        "source": SOURCE, "espn_event_id": match.espn_event_id, "espn_match_id": match.match_id,
    }
