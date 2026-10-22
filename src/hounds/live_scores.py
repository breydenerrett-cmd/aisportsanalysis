"""Live scores for the games behind open tickets: ESPN's free scoreboard (most families) and MLB's own Stats API (MLB).

WHY THIS EXISTS (2026-10-22). Member tickets on the Oct 21 NBA games were still PENDING five hours after the games
ended. The only score source those tickets had was The Odds API ``/scores``, polled by the capture slot at most every
``scores_poll_interval_hours`` (8) per sport key, committed to git, and shipped in the next hourly image rebuild. The
one NBA poll that night ran at 00:10Z, an hour into the games, saw 21-15, and the key was then locked out until 08:10Z.
``docs/audit/2026-10-22/GRADING_DELAY.md`` has the timeline. This module is the free, fast path: the same public ESPN
JSON the data service already reads (``src/datasvc/espn``), fetched by the API process itself, for ONLY the games that
have an open ticket.

WHAT IT DOES NOT DO
-------------------
It does not grade anything and it does not change a grading rule. It turns a scoreboard into one small answer per game
(``upcoming`` / ``live`` / ``final`` / ``postponed`` / ``cancelled`` with the score) and ``live_settle`` feeds a FINAL
one to the existing settle functions in the shape they already read.

CORRECTNESS OVER COVERAGE
-------------------------
A wrong score would append a wrong grade to an append-only ledger, so every doubt is a non-answer:

  * a game is matched to an ESPN event only when BOTH team names agree in the SAME orientation (home with home).
    A neutral-site game the two vendors list the other way round is not matched, never flipped;
  * exactly one ESPN event may fit; two (a doubleheader) means no answer;
  * the ESPN start must be within ``MATCH_WINDOW`` of the ticket's start;
  * a score counts only from a FINAL status with both numbers present. Soccer counts only regulation time
    (``STATUS_FULL_TIME``): the books grade a match result at 90 minutes, and ESPN's extra-time and penalty finals
    would grade a cup tie on a different basis;
  * an unmapped family (cricket, rugby, AFL) or league is unsupported and stays on the old path.

ONE REQUEST PER LEAGUE-DAY, NEVER A STORE. A scoreboard is one small request for a league on a day; only the wanted
games are read out of it and only those are kept. MLB is asked one game at a time by ``gamePk``
(``providers.mlb.fetch_game_instances``), which also follows a postponed game to its makeup under the same pk.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterable, Mapping, Optional

from src.datasvc.espn import leagues as lg
from src.datasvc.espn import parse as espn_parse

UPCOMING, LIVE, FINAL, POSTPONED, CANCELLED = "upcoming", "live", "final", "postponed", "cancelled"
STATES = (UPCOMING, LIVE, FINAL, POSTPONED, CANCELLED)

#: How far apart the ticket's start and ESPN's start may be and still be one game. The vendors round and revise a start
#: by minutes, not by a day. It must stay well under 24 hours: the same two teams meet on back-to-back days in a playoff
#: series (same home side, same orientation), and the neighbouring day's scoreboard is read when a game is not on its own
#: day's, so a window over a day would hand yesterday's FINAL to today's ticket (found by the 2026-10-22 verification:
#: a 30 hour window graded game 2 from game 1's score). A game moved more than this far is a different game here, and
#: stays on the old path.
MATCH_WINDOW = timedelta(hours=12)

# The family code a ticket carries -> the ESPN league code it is settled from.
ESPN_LEAGUE_BY_FAMILY = {
    "NBA": "nba", "WNBA": "wnba", "NHL": "nhl", "NCAAF": "ncaaf", "NCAAB": "ncaab",
}
# An Odds API sport key (a ticket's ``league``) -> ESPN league, for the families that span leagues.
ESPN_LEAGUE_BY_KEY = {
    "basketball_wncaab": "ncaaw", "basketball_ncaab": "ncaab", "basketball_nba": "nba", "basketball_wnba": "wnba",
    "icehockey_nhl": "nhl", "americanfootball_ncaaf": "ncaaf",
    "soccer_epl": "epl", "soccer_spain_la_liga": "laliga", "soccer_germany_bundesliga": "bundesliga",
    "soccer_italy_serie_a": "seriea", "soccer_france_ligue_one": "ligue1", "soccer_usa_mls": "mls",
    "soccer_uefa_champs_league": "ucl",
}
#: The NFL is not in the data service's registry (its own store is nflverse); ESPN's path is the same shape.
NFL_PATH = "football/nfl"
NFL_CODE = "nfl"
MLB_FAMILY = "MLB"
#: Families with no ESPN scoreboard row per game: the free tennis and MMA readers of src/pipeline/allsports_free_results.py
#: settle these (a winner, or a named void), never a score.
TENNIS_FAMILY, MMA_FAMILY = "TENNIS", "MMA"
FREE_FAMILIES = (TENNIS_FAMILY, MMA_FAMILY)
SOCCER_FULL_TIME = "STATUS_FULL_TIME"

_FINAL_STATUS = re.compile(r"^STATUS_FINAL")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_TEAM_ALIASES = (("los angeles ", "la "), ("saint ", "st "), (" and ", " "))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# which feed settles a ticket
# ---------------------------------------------------------------------------

def espn_league_for(family: str, league_key: Optional[str] = None) -> Optional[str]:
    """The ESPN league code for a ticket's family (and Odds API sport key), or None when this module cannot settle it."""
    code = str(family or "").upper()
    if code == "NFL":
        return NFL_CODE
    if league_key and str(league_key).lower() in ESPN_LEAGUE_BY_KEY:
        return ESPN_LEAGUE_BY_KEY[str(league_key).lower()]
    return ESPN_LEAGUE_BY_FAMILY.get(code)


def supported(family: str, league_key: Optional[str] = None, game_pk=None) -> bool:
    if str(family or "").upper() == MLB_FAMILY:
        return game_pk not in (None, "", "None")
    if str(family or "").upper() in FREE_FAMILIES:
        return True
    return espn_league_for(family, league_key) is not None


def scoreboard_url(league_code: str, day: date) -> str:
    """The same URL shape the data service's runner builds (``src/datasvc/espn/pipeline.py``)."""
    if league_code == NFL_CODE:
        return f"{lg.SITE}{NFL_PATH}/scoreboard?dates={day.strftime('%Y%m%d')}&limit=100"
    league = lg.get(league_code)
    url = f"{lg.SITE}{league.path}/scoreboard?dates={day.strftime('%Y%m%d')}&limit={league.limit}"
    return url + (f"&groups={league.groups}" if league.groups else "")


# ---------------------------------------------------------------------------
# team names
# ---------------------------------------------------------------------------

def norm_team(name: Optional[str]) -> str:
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower().replace("&", " and ")
    text = _NON_ALNUM.sub(" ", text).strip()
    text = f" {text} "
    for old, new in _TEAM_ALIASES:
        text = text.replace(f" {old.strip()} ", f" {new.strip()} ")
    return " ".join(text.split())


_CLUB_SUFFIXES = frozenset({"fc", "cf", "afc", "sc", "ac"})


def teams_match(a: Optional[str], b: Optional[str]) -> bool:
    """Two team names are the same club: equal after folding ("Los Angeles Clippers" / "LA Clippers"), ignoring a club
    suffix ("Arsenal" / "Arsenal FC"), or one is the other plus extra words when the shorter keeps two or more words
    ("Brighton Hove Albion" / "Brighton and Hove Albion FC"). A shared nickname alone ("Kings", "Panthers") is NOT
    enough: several leagues share them, so the answer is no."""
    x = [t for t in norm_team(a).split() if t not in _CLUB_SUFFIXES]
    y = [t for t in norm_team(b).split() if t not in _CLUB_SUFFIXES]
    if not x or not y:
        return False
    if x == y:
        return True
    small, big = (set(x), set(y)) if len(x) <= len(y) else (set(y), set(x))
    return len(small) >= 2 and small <= big


# ---------------------------------------------------------------------------
# ESPN
# ---------------------------------------------------------------------------

def _state_of(row: Mapping, league_code: str) -> str:
    status = str(row.get("status") or "").upper()
    if status in ("STATUS_POSTPONED", "STATUS_SUSPENDED", "STATUS_ABANDONED"):
        return POSTPONED
    if status in ("STATUS_CANCELED", "STATUS_CANCELLED"):
        return CANCELLED
    if row.get("completed") and row.get("state") == "post":
        if league_code in {code for code, l in lg.LEAGUES.items() if l.family == "soccer"}:
            return FINAL if status == SOCCER_FULL_TIME else LIVE      # an extra-time final waits for the old path
        return FINAL if _FINAL_STATUS.match(status) or status == SOCCER_FULL_TIME else LIVE
    if row.get("state") == "in":
        return LIVE
    return UPCOMING


def espn_answers(payload: Mapping, league_code: str, wanted: Iterable[Mapping], observed: str) -> dict:
    """{game key: answer} for the wanted games found in ONE scoreboard payload. ``wanted`` items carry ``key``,
    ``home_team``, ``away_team`` and ``start`` (datetime). A game with no unambiguous match is simply absent."""
    rows = espn_parse.games(payload, league_code, observed, None)
    details = {}
    for event in payload.get("events") or []:
        stype = (((event.get("competitions") or [{}])[0].get("status") or event.get("status") or {}).get("type") or {})
        details[str(event.get("id"))] = stype.get("shortDetail") or stype.get("detail")
    out: dict = {}
    for want in wanted:
        hits = []
        for row in rows:
            espn_start = parse_utc(row.get("date_utc"))
            start = want.get("start")
            if start is not None and espn_start is not None and abs(espn_start - start) > MATCH_WINDOW:
                continue
            if teams_match(row.get("home_name"), want.get("home_team")) and \
                    teams_match(row.get("away_name"), want.get("away_team")):
                hits.append(row)
        if len(hits) != 1:
            continue                                  # no match, a swapped orientation or a doubleheader: no answer
        row = hits[0]
        state = _state_of(row, league_code)
        home, away = row.get("home_score"), row.get("away_score")
        if state == FINAL and (home is None or away is None):
            state = LIVE                              # a final with no readable score is not a score
        out[want["key"]] = {"state": state, "home_score": home, "away_score": away,
                            "detail": details.get(row["game_id"]), "source": "espn", "source_id": row["game_id"],
                            "start_utc": row.get("date_utc")}
    return out


# ---------------------------------------------------------------------------
# MLB (one game at a time, by gamePk)
# ---------------------------------------------------------------------------

def mlb_answer(game_pk, fetch_instances: Optional[Callable] = None) -> Optional[dict]:
    """The state of one MLB game from the Stats API's schedule entry for its gamePk, or None when it cannot be
    asked. A game postponed and made up under the same pk is final when ANY entry is final (the existing settle
    contract settles it from that final)."""
    if fetch_instances is None:
        from src.providers import mlb
        fetch_instances = mlb.fetch_game_instances
    instances = list(fetch_instances(game_pk) or [])
    if not instances:
        return None
    finals = [g for g in instances if g.get("state") == "final" and g.get("away_score") is not None
              and g.get("home_score") is not None]
    if finals:
        g = sorted(finals, key=lambda x: str(x.get("date") or ""))[-1]
        return {"state": FINAL, "home_score": g["home_score"], "away_score": g["away_score"],
                "detail": g.get("detailed_state"), "source": "mlb_statsapi", "source_id": str(game_pk),
                "start_utc": g.get("start_time_utc"), "date": g.get("date"), "away_code": g.get("away_team"),
                "home_code": g.get("home_team")}
    g = sorted(instances, key=lambda x: str(x.get("date") or ""))[-1]
    detailed = str(g.get("detailed_state") or "")
    if detailed in ("Postponed", "Suspended"):
        state = POSTPONED
    elif detailed == "Cancelled":
        state = CANCELLED
    elif detailed in ("Scheduled", "Pre-Game", "Warmup", "Delayed Start"):
        state = UPCOMING
    else:
        state = LIVE
    return {"state": state, "home_score": g.get("home_score"), "away_score": g.get("away_score"), "detail": detailed,
            "source": "mlb_statsapi", "source_id": str(game_pk), "start_utc": g.get("start_time_utc")}


def days_to_ask(slate_date: Optional[str], start: Optional[datetime]) -> list:
    """The scoreboard days to read for a game, most likely first: its slate (Eastern) date, then the day either side
    (a game listed under the neighbouring day by the vendor). The neighbours are asked only when the first misses."""
    base = None
    if slate_date:
        try:
            base = date.fromisoformat(str(slate_date)[:10])
        except ValueError:
            base = None
    if base is None and start is not None:
        base = (start - timedelta(hours=5)).date()
    if base is None:
        return []
    return [base, base - timedelta(days=1), base + timedelta(days=1)]
