"""ESPN as the automatic result source for `ufc autograde` (the default).

WHY
---
Grading the UFC card by hand (docs/audit/2026-10-01/UFC_GRADING.md) was the one
manual step left in its life cycle. ESPN's public MMA data is already read by
our own data layer (`src/datasvc/ufc/`, contract in docs/datasvc/UFC_SCHEMA.md):
free, no key, a named winner and a method for every finished bout, and it covers
the Contender Series as well as numbered and Fight Night cards. It is not
UFC.com, whose terms ban automated and manual collection.

WHAT IT DOES, FOR ONE CARD DATE D AND THE PUBLISHED PICKS OF D
--------------------------------------------------------------
1. Reads ESPN's UFC scoreboard for D (one request). The scoreboard lists the
   day's events with each bout's two fighters, name AND ESPN id; the event
   document the data layer crawls carries ids only. If any pick has no bout on
   that scoreboard, the day before is read too (a card date is the UTC date a
   bout STARTS on, so a main-card bout after midnight UTC belongs to the next
   date while ESPN lists its event under the evening it began).
2. Matches each pick to one bout by name, with `names.match` run on BOTH
   fighters. Each name must resolve to exactly one ESPN athlete id (accents,
   punctuation, a trailing "Jr." and word order are folded by `names.normalise`;
   when two athletes fit equally well `names.match` refuses to choose and so do
   we), and a bout must exist whose two fighters are exactly those two ids.
   Anything less is NOT graded: it comes back `unresolved` with the reason.
3. Crawls only the events that hold a published fighter, through the data
   layer's own `schedule.crawl_event` (the event, then one status document per
   bout), and reads the bout's result there: status, winner, method, round, time.
4. Hands the result to `ufc_autograde.resolve_bout`, the same rules every
   source goes through: final-only, void outcomes for a draw / no contest /
   cancelled bout, and "the published pairing did not happen" when a published
   fighter fought a different opponent. `autograde_date` then records it through
   `ufc_results.record_result` with the provenance of the row: provider `espn`,
   the ESPN event id, the ESPN bout id, the time the bout's status was fetched,
   ESPN's raw status and method, and how the names were matched.

WHAT IS CHECKED, WHAT IS NOT
----------------------------
Checked: a final status from ESPN's status document for the exact bout; a winner
flagged on exactly one competitor; the scoreboard and the event document agreeing
on who is in the bout and, when both flag a winner, on who won (a disagreement
HOLDS the bout, because ESPN is mid-edit); a draw / no contest carrying no winner;
`STATUS_CANCELED`. A result already on file (typed by a person, or an earlier
automatic row) is compared with ESPN and never overwritten.

NOT checked, and not claimed: ESPN is one source. Nothing here proves a result
is right beyond what ESPN says; an overturned result after ESPN went final is not
detected (run `ufc autograde --verify` later to compare again). ESPN has no
explicit "this pairing was cancelled" for a replaced fighter: the old bout simply
disappears, so a replacement is INFERRED from a published fighter appearing in a
different final bout. A bout ESPN dropped from the card (the data layer's
`dropped_from_event` marker, which is ours, not ESPN's) is held for a person, as
is a bout whose scoreboard is not final yet. Bout start times are per card
segment on ESPN, so they are never used to match.

NAMES THE ODDS FEED SPELLS DIFFERENTLY
--------------------------------------
Published picks carry the odds feed's names, ESPN uses ring names: tonight's
card has "Michael Parkin" in the ledger and "Mick Parkin" on ESPN, whose own
athlete record says first name "Mick" (so not even `fighters.alias_forms` ties
them). A strict matcher leaves such a pick ungraded; a fuzzy one would be
guessing. The middle path is `CONFIRMED_ALIASES`: a spelling a person has
confirmed is one ESPN athlete, keyed to that athlete's ESPN ID and applied only
when that athlete is on the card. Every entry carries its evidence. Nothing else
bridges a nickname.

FRESHNESS AND COST
------------------
The scoreboard is always requested live, the event document and any status that
is not final are re-requested on every run, and a status ESPN has already called
final is served from the cache for good (the data layer's rule). A card costs one
scoreboard request (two if the day before is needed) plus, per event crawled, 1 +
the number of bouts on it (14 to 16 for a UFC card), through one `PoliteFetcher`
(one request at a time, a request cap of `MAX_REQUESTS`, a browser check stops
the run). `offline=True` serves everything from the raw cache and fails with a
clear message on a miss: a replay of a saved grading with no network.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import date as date_cls, timedelta
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from src.datasvc import names
from src.datasvc.http import (FetchError, NotFound, PoliteFetcher, RequestCapReached,
                              SourceBlocked)
from src.datasvc.ufc import espn_urls, fighters, schedule
from src.pipeline import ufc_results
from src.pipeline.ufc_autograde import (
    ACTION_RECORD, ACTION_UNRESOLVED, STATUS_CANCELLED, STATUS_FINAL, STATUS_PENDING,
    BoutIdentity, Decision, ProviderError, ProviderFight, UfcResultsProvider, resolve_bout)

PROVIDER_NAME = "espn"
MAX_REQUESTS = 60          # one run's network cap: a scoreboard or two plus ~16 per event

_NO_WINNER_METHODS = ("DRAW", "NC")


# ---------------------------------------------------------------------------
# Spellings a person has confirmed
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConfirmedAlias:
    """The odds feed's spelling -> one ESPN athlete, confirmed by a person.

    Keyed by athlete id on purpose: a name can be reused, an id cannot. Applied
    only when that athlete is on the card being read, and still subject to the
    pair rule (a bout between the two resolved fighters must exist)."""
    espn_athlete_id: str
    espn_name: str
    evidence: str


CONFIRMED_ALIASES: Dict[str, ConfirmedAlias] = {
    names.normalise("Michael Parkin"): ConfirmedAlias(
        espn_athlete_id="5060505",
        espn_name="Mick Parkin",
        evidence=(
            "2026-10-03, UFC 332 (ESPN event 600061182, bout 401912274): the odds feed "
            "published 'Johnny Walker vs Michael Parkin'; ESPN's scoreboard and the "
            "Wikipedia UFC 332 card both list 'Johnny Walker vs Mick Parkin' (heavyweight, "
            "early prelims), and Walker has no other bout and no other Parkin is on the "
            "card. Confirmed as the same BOUT; ESPN's athlete record gives first name "
            "'Mick' and Wikipedia states no legal first name, so this rests on bout "
            "identity, not on a biography. Remove the entry if you disagree."),
    ),
}


# ---------------------------------------------------------------------------
# Scoreboard: who is in each bout, by name and id (pure)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScoreFighter:
    fighter_id: str
    name: str
    aliases: Tuple[str, ...]
    order: Optional[int]
    winner: Optional[bool]


@dataclass(frozen=True)
class ScoreBout:
    event_id: str
    event_name: str
    bout_id: str
    fighters: Tuple[ScoreFighter, ...]
    status_name: str

    @property
    def fighter_ids(self) -> frozenset:
        return frozenset(f.fighter_id for f in self.fighters)


def _text(value) -> Optional[str]:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def parse_scoreboard(doc) -> List[ScoreBout]:
    """Every bout of every event on an ESPN scoreboard document, with each
    fighter's name, aliases (the data layer's `alias_forms`), order and winner
    flag. A competitor with no id is skipped; one with no name is kept (it can be
    matched by id, never by name)."""
    out: List[ScoreBout] = []
    if not isinstance(doc, dict):
        return out
    for event in doc.get("events") or []:
        if not isinstance(event, dict):
            continue
        event_id = _text(event.get("id"))
        if not event_id:
            continue
        for comp in event.get("competitions") or []:
            if not isinstance(comp, dict):
                continue
            bout_id = _text(comp.get("id"))
            if not bout_id:
                continue
            competitors = []
            for entry in comp.get("competitors") or []:
                if not isinstance(entry, dict):
                    continue
                fighter_id = _text(entry.get("id"))
                if not fighter_id:
                    continue
                athlete = entry.get("athlete") if isinstance(entry.get("athlete"), dict) else {}
                name = (fighters.clean_text(athlete.get("displayName"))
                        or fighters.clean_text(athlete.get("fullName")) or "")
                order = entry.get("order")
                competitors.append(ScoreFighter(
                    fighter_id=fighter_id, name=name,
                    aliases=tuple(fighters.alias_forms(athlete)),
                    order=order if isinstance(order, int) and not isinstance(order, bool) else None,
                    winner=entry.get("winner") if isinstance(entry.get("winner"), bool) else None))
            status = comp.get("status") if isinstance(comp.get("status"), dict) else {}
            status_type = status.get("type") if isinstance(status.get("type"), dict) else {}
            out.append(ScoreBout(
                event_id=event_id, event_name=_text(event.get("name")) or "",
                bout_id=bout_id, fighters=tuple(competitors),
                status_name=_text(status_type.get("name")) or ""))
    return out


def people_index(board: Sequence[ScoreBout]) -> Dict[str, List[str]]:
    """{ESPN athlete id: every name it may be called by}, for `names.match`."""
    people: Dict[str, List[str]] = {}
    for bout in board:
        for fighter in bout.fighters:
            forms = people.setdefault(fighter.fighter_id, [])
            for form in (*fighter.aliases, names.normalise(fighter.name)):
                if form and form not in forms:
                    forms.append(form)
    return people


# ---------------------------------------------------------------------------
# Name -> ESPN athlete (pure)
# ---------------------------------------------------------------------------

@dataclass
class NameResolution:
    fighter_id: Optional[str]
    ambiguous: bool = False
    candidates: Tuple[Tuple[str, str, float], ...] = ()
    via: str = "none"          # "names.match", "confirmed alias" or "none"


def resolve_name(name: str, people: Mapping[str, Sequence[str]],
                 aliases: Optional[Mapping[str, ConfirmedAlias]] = None) -> NameResolution:
    """One published fighter name -> at most one ESPN athlete id.

    `names.match` decides, and refuses to guess between equal candidates. A
    confirmed alias applies first, only when its athlete is among `people`; if
    `names.match` then finds a DIFFERENT athlete the name is ambiguous (two
    people claim it), never silently the alias."""
    found = names.match(name, dict(people))
    candidates = tuple((pid, label, score) for pid, label, score in found.candidates)
    alias = (aliases or {}).get(names.normalise(name))
    if alias is not None and alias.espn_athlete_id in people:
        if found.best is None and not found.ambiguous:
            return NameResolution(alias.espn_athlete_id, via="confirmed alias")
        if found.best == alias.espn_athlete_id:
            return NameResolution(alias.espn_athlete_id, via="confirmed alias", candidates=candidates)
        return NameResolution(None, ambiguous=True, candidates=candidates, via="names.match")
    if found.ambiguous:
        return NameResolution(None, ambiguous=True, candidates=candidates, via="names.match")
    if found.best is None:
        return NameResolution(None, via="none")
    return NameResolution(found.best, candidates=candidates, via="names.match")


# ---------------------------------------------------------------------------
# One ESPN bout as a ProviderFight (pure)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EspnFight(ProviderFight):
    """A `ProviderFight` that also carries ESPN's ids and the names each
    fighter may be called by, so a pick can be matched by athlete id."""
    fighter1_id: str = ""
    fighter2_id: str = ""
    winner_id: str = ""
    fighter1_aliases: Tuple[str, ...] = ()
    fighter2_aliases: Tuple[str, ...] = ()


def _clock(seconds) -> str:
    whole = int(seconds)
    return f"{whole // 60}:{whole % 60:02d}"


def raw_status_of(bout: dict) -> str:
    """ESPN's status and result in one line for the row's `raw_status`."""
    parts = [bout.get("status_raw") or bout.get("status") or "unknown"]
    if bout.get("result_method_raw"):
        parts.append(f"result={bout['result_method_raw']}")
    if bout.get("status") == "final" and bout.get("end_round"):
        parts.append(f"R{bout['end_round']}" + (
            f" {_clock(bout['end_time_s'])}" if bout.get("end_time_s") is not None else ""))
    if bout.get("result_detail"):
        parts.append(f"({bout['result_detail']})")
    return " ".join(parts)


def _held_reason(bout: dict, board_bout: Optional[ScoreBout]) -> Optional[str]:
    """Why a FINAL core bout must not be graded yet: the scoreboard (the source of
    the names) and the event document (the source of the result) disagree."""
    if board_bout is None:
        return None
    core_ids = {str(bout.get("fighter_a_id") or ""), str(bout.get("fighter_b_id") or "")} - {""}
    if board_bout.fighter_ids != core_ids:
        return (f"HELD: ESPN's scoreboard lists fighters {sorted(board_bout.fighter_ids)} "
                f"but the event document lists {sorted(core_ids)}")
    flagged = [f.fighter_id for f in board_bout.fighters if f.winner]
    winner_id = bout.get("winner_id")
    if winner_id and flagged and flagged != [str(winner_id)]:
        return (f"HELD: ESPN's scoreboard flags {flagged} as the winner but the event "
                f"document flags {winner_id}")
    return None


def fight_from_bout(event: dict, bout: dict, board_bout: Optional[ScoreBout]) -> EspnFight:
    """One crawled ESPN bout (+ its scoreboard entry, for names) -> EspnFight.

    status: final -> STATUS_FINAL, ESPN's own canceled -> STATUS_CANCELLED,
    anything else (scheduled, in progress, postponed, unknown, the data layer's
    `dropped_from_event`) -> STATUS_PENDING. outcome (final only): a flagged
    winner -> "win"; no winner and method DRAW / NC -> "draw" / "no_contest";
    anything else (no winner and no marker, a winner on a draw / no contest, a
    scoreboard and event document in conflict) -> None, which the autograder
    leaves for a person."""
    a_id = str(bout.get("fighter_a_id") or "")
    b_id = str(bout.get("fighter_b_id") or "")
    by_id = {f.fighter_id: f for f in (board_bout.fighters if board_bout else ())}

    def name_of(fighter_id: str) -> str:
        return by_id[fighter_id].name if fighter_id in by_id else ""

    def aliases_of(fighter_id: str) -> Tuple[str, ...]:
        return by_id[fighter_id].aliases if fighter_id in by_id else ()

    raw = raw_status_of(bout)
    state = bout.get("status")
    status = (STATUS_FINAL if state == "final"
              else STATUS_CANCELLED if (state == "canceled"
                                        and bout.get("status_raw") != schedule.DROPPED_STATUS_RAW)
              else STATUS_PENDING)
    if bout.get("status_raw") == schedule.DROPPED_STATUS_RAW:
        raw = ("dropped_from_event (our marker, not an ESPN status: the bout vanished from "
               "the card; a person must say whether it was cancelled)")
    outcome: Optional[str] = None
    winner_id = str(bout.get("winner_id") or "")
    if status == STATUS_FINAL:
        held = _held_reason(bout, board_bout)
        method = bout.get("result_method")
        if held:
            status, raw = STATUS_PENDING, f"{raw} -- {held}"
        elif winner_id and method in _NO_WINNER_METHODS:
            raw = f"{raw} -- a winner is flagged on a bout ESPN calls {method}"
        elif winner_id:
            outcome = ufc_results.OUTCOME_WIN
        elif method == "DRAW":
            outcome = ufc_results.OUTCOME_DRAW
        elif method == "NC":
            outcome = ufc_results.OUTCOME_NO_CONTEST
    won = outcome == ufc_results.OUTCOME_WIN
    return EspnFight(
        provider=PROVIDER_NAME, event_id=str(event.get("event_id") or bout.get("event_id") or ""),
        fight_id=str(bout.get("bout_id") or ""), fighter1=name_of(a_id), fighter2=name_of(b_id),
        status=status, raw_status=raw, outcome=outcome,
        winner=(name_of(winner_id) or None) if won else None,
        fetched_utc=str(bout.get("fetched_utc") or ""),
        fighter1_id=a_id, fighter2_id=b_id, winner_id=winner_id if won else "",
        fighter1_aliases=aliases_of(a_id), fighter2_aliases=aliases_of(b_id))


# ---------------------------------------------------------------------------
# The provider
# ---------------------------------------------------------------------------

def make_fetcher(cache_dir=None, *, offline: bool = False) -> PoliteFetcher:
    """The one polite fetcher a run uses. `offline` means no request may reach
    ESPN: every read must already be in the raw cache."""
    return PoliteFetcher(cache_dir=cache_dir, delay_s=0.35,
                         max_requests=0 if offline else MAX_REQUESTS)


class EspnMmaResultsProvider(UfcResultsProvider):
    name = PROVIDER_NAME

    def __init__(self, fetcher: PoliteFetcher, *, live: bool = True,
                 aliases: Optional[Mapping[str, ConfirmedAlias]] = None):
        self._fetcher = fetcher
        self._live = live
        self._aliases = dict(CONFIRMED_ALIASES if aliases is None else aliases)
        self._people: Dict[str, List[str]] = {}
        self._board: List[ScoreBout] = []
        self.notes: List[str] = []

    # -- network, behind one error translation ------------------------------------

    def _guard(self, what: str, call):
        try:
            return call()
        except NotFound:
            raise
        except SourceBlocked:
            raise ProviderError(
                f"ESPN served a browser check instead of data for {what}; stopped, "
                "nothing was recorded (a source that blocks a plain client is not used)") from None
        except RequestCapReached as exc:
            if not self._live:
                raise ProviderError(
                    f"offline: {what} is not in the raw cache, and an offline run makes "
                    "no requests") from None
            raise ProviderError(f"ESPN request cap reached while reading {what} ({exc}); "
                                "nothing was recorded") from None
        except FetchError as exc:
            raise ProviderError(f"ESPN request failed for {what}: {exc}") from None

    def _scoreboard(self, day: date_cls) -> List[ScoreBout]:
        url = espn_urls.scoreboard(day)

        def fetch():
            if self._live:
                return self._fetcher.get_json(url, use_cache=False)
            return self._fetcher.get_json(url)
        try:
            doc = self._guard(f"the scoreboard for {day}", fetch)
        except NotFound:
            doc = {}
        board = parse_scoreboard(doc)
        events = sorted({b.event_id for b in board})
        self.notes.append(f"scoreboard {day}: {len(events)} event(s), {len(board)} bout(s)")
        return board

    def _crawl(self, event_id: str):
        def crawl():
            return schedule.crawl_event(self._fetcher, event_id,
                                        max_age_s=0.0 if self._live else None)
        try:
            return self._guard(f"event {event_id}", crawl)
        except NotFound:
            self.notes.append(f"event {event_id}: ESPN answered 404")
            return None, []
        except ValueError as exc:
            raise ProviderError(f"ESPN event {event_id} is not in the expected shape: {exc}") from None

    # -- the seam ------------------------------------------------------------------

    def fetch_fights(self, date: str, *, now) -> List[EspnFight]:
        """Every bout of every UFC event ESPN lists for `date` (no picks to look for)."""
        return self.fetch_for_bouts(date, (), now=now)

    def fetch_for_bouts(self, date: str, bouts: Sequence[BoutIdentity], *, now) -> List[EspnFight]:
        try:
            day = date_cls.fromisoformat(str(date))
        except ValueError:
            raise ProviderError(f"date must be YYYY-MM-DD, got {date!r}") from None
        self.notes = []
        board = self._scoreboard(day)
        self._people = people_index(board)
        if bouts and any(not self._located(b) for b in bouts):
            board = board + self._scoreboard(day - timedelta(days=1))
            self._people = people_index(board)
        self._board = board

        if bouts:
            wanted = self._events_with_a_published_fighter(bouts, board)
        else:
            wanted = list(dict.fromkeys(b.event_id for b in board))
        fights: List[EspnFight] = []
        for event_id in wanted:
            event, core_bouts = self._crawl(event_id)
            if event is None:
                continue
            on_board = {b.bout_id: b for b in board if b.event_id == event_id}
            for core in core_bouts:
                if core.get("status_raw") == schedule.DROPPED_STATUS_RAW:
                    self.notes.append(f"bout {core.get('bout_id')} was dropped from event "
                                      f"{event_id}; held for a person")
                    continue
                fights.append(fight_from_bout(event, core, on_board.get(core["bout_id"])))
        return fights

    def _resolve(self, name: str, people) -> NameResolution:
        return resolve_name(name, people, self._aliases)

    def _located(self, bout: BoutIdentity) -> bool:
        """Whether the scoreboard read so far has anything to say about this
        pick: at least one of its fighters is on it, or a name fits several
        athletes. A pick with neither fighter on it may belong to an event ESPN
        lists under the day before, so only then is that day read too. (A pick
        with ONE fighter on the board is not widened for: its event is found, and
        the missing name is a replaced or differently spelled opponent, which the
        day before cannot explain.)"""
        for name in (bout.home, bout.away):
            found = self._resolve(name, self._people)
            if found.fighter_id or found.ambiguous:
                return True
        return False

    def _events_with_a_published_fighter(self, bouts, board) -> List[str]:
        ids = set()
        for bout in bouts:
            for name in (bout.home, bout.away):
                found = self._resolve(name, self._people)
                if found.fighter_id:
                    ids.add(found.fighter_id)
        return list(dict.fromkeys(b.event_id for b in board if b.fighter_ids & ids))

    def decide(self, bout: BoutIdentity, fights: Sequence[ProviderFight]) -> Decision:
        fights = list(fights)
        people: Dict[str, List[str]] = {pid: list(forms) for pid, forms in self._people.items()}
        for f in fights:
            if isinstance(f, EspnFight):
                for fid, name, forms in ((f.fighter1_id, f.fighter1, f.fighter1_aliases),
                                         (f.fighter2_id, f.fighter2, f.fighter2_aliases)):
                    if fid:
                        known = people.setdefault(fid, [])
                        for form in (*forms, names.normalise(name)):
                            if form and form not in known:
                                known.append(form)

        def unresolved(reason: str) -> Decision:
            return Decision(bout, ACTION_UNRESOLVED, reason)

        if not fights:
            looked = "; ".join(self.notes) or "no scoreboard was read"
            return unresolved(
                f"ESPN gave no bout for either published fighter ({looked})")
        home = self._resolve(bout.home, people)
        away = self._resolve(bout.away, people)
        for given, found in ((bout.home, home), (bout.away, away)):
            if found.ambiguous:
                options = ", ".join(f"{label!r} (ESPN {pid}, score {score})"
                                    for pid, label, score in found.candidates)
                return unresolved(
                    f"ambiguous: names.match cannot choose one ESPN fighter for {given!r}: "
                    f"{options}; nothing graded")
        if home.fighter_id and home.fighter_id == away.fighter_id:
            return unresolved("both published names resolve to the same ESPN fighter "
                              f"({home.fighter_id}); nothing graded")

        spelled: Dict[str, str] = {}
        if home.fighter_id:
            spelled[home.fighter_id] = bout.home
        if away.fighter_id:
            spelled[away.fighter_id] = bout.away
        translated = [
            dataclasses.replace(
                f, fighter1=spelled.get(f.fighter1_id, f.fighter1),
                fighter2=spelled.get(f.fighter2_id, f.fighter2),
                winner=spelled.get(f.winner_id, f.winner))
            if isinstance(f, EspnFight) else f
            for f in fights]
        decision = resolve_bout(bout, translated)

        shown = {}
        for f in fights:
            if isinstance(f, EspnFight):
                shown.setdefault(f.fighter1_id, f.fighter1)
                shown.setdefault(f.fighter2_id, f.fighter2)
        if decision.action == ACTION_RECORD:
            matched = "; ".join(
                f"{given!r} = ESPN {shown.get(found.fighter_id) or found.fighter_id!r} "
                f"(athlete {found.fighter_id}, {found.via})"
                for given, found in ((bout.home, home), (bout.away, away)) if found.fighter_id)
            if matched:
                decision.provenance["basis"] = f"{decision.provenance.get('basis', '')}; {matched}"
        elif decision.action == ACTION_UNRESOLVED:
            if "looks like a spelling" in decision.reason:
                decision.reason += (
                    " -- to accept it, record the result by hand (python -m src.cli ufc "
                    "result ...) or add a confirmed alias in "
                    "src/providers/espn_mma_results.py (CONFIRMED_ALIASES)")
            elif decision.reason.startswith("neither published fighter"):
                decision.reason += f" ({'; '.join(self.notes)})"
        return decision
