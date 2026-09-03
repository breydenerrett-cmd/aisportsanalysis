"""The deterministic point-in-time replay engine: what was on the table at T.

NOTHING IN THIS PACKAGE IS EVIDENCE. Nothing this module produces is evidence.
A replay is a rehearsal against a store we already own the answers to, run
inside an explicitly exploratory sandbox (docs/EVOLAB_DESIGN.md sections 11 and
15); the forward ledger is the only independent arbiter this project has. A
number that leaves here is a hypothesis with provenance attached, never a
finding, and price improvement is line-shopping value -- never EV, never edge
(docs/PLAN_TWO_TOOLS.md).

THE ONE CORRECTNESS PROPERTY
----------------------------
A strategy must be structurally incapable of seeing anything that did not exist
at T. Three mechanisms, none of which is a filter:

1. **The engine carries no outcome at all.** `ReplayGame` is built by copying
   an allowlist of fields out of the price path; `home_won` and `total_runs`
   are never read, never stored, never passed. There is no line in this module
   that could leak an outcome because there is no line in this module that
   knows one. Fitness joins outcomes later, after every decision is fixed.
2. **Boards are served through one generator, `iter_instants_through`, which
   STOPS at T.** It breaks out of the ascending scan on the first observation
   after T rather than skipping past it and continuing. A row dated T+1s is
   therefore never yielded to anything, which is why injecting one into every
   store leaves every decision byte-identical (acceptance test 2).
3. **`WorldView` has no attribute for an outcome or a closing price**, refuses
   one at construction and raises on access (see decide.py). This module adds
   `LeakageError`, raised if a quote dated after T ever reaches board assembly
   -- unreachable through the generator, and kept as the alarm that would fire
   if someone bypassed it.

THE REPLAY CLOCK IS THE STORE'S OWN ALPHABET
--------------------------------------------
Decision times ARE observations (Phase 0 recommendation 2). The engine serves
the board observed at T and refuses any T that is not one of that game's
observed instants -- there is nothing between instants and interpolating one
would be fabrication. `T` is inclusive: the observation stamped T is the board
at T. "Future" means strictly after T.

WHY TWO POINT CLASSES AND NOT FOUR
----------------------------------
The design's four-rung ladder did not survive contact with the data, and this
is the largest amendment here. The historical store is three snapshots a day;
**no two observations anywhere in 2023-24 are closer than 177 minutes**, median
gap six hours. `T_MINUS_30M` exists for 1,269 of 4,819 games and lineup posting
times do not exist at all. So the ladder collapses to `EARLY_BOARD` and
`LATE_BOARD`, both of which are real observations, and `LATE_BOARD` is not
called a close: it is a median 85 minutes before first pitch and it carries its
own gap so nobody can forget that.

WHAT THE ENGINE REFUSES TO CALL POINT-IN-TIME
---------------------------------------------
Every feature the registry serves is availability class C or D
(docs/EVOLAB_PHASE0_FEASIBILITY.md section 3): it depends on the probable
pitcher, the posted lineup, or both, and neither has a recorded availability
time for 2023-24. Worse for class C, `docs/AUDIT_PROBABLE_PITCHER_PIT.md`
measured that the stored probable is effectively the actual first-pitch
starter -- 0.10% / 0.08% disagreement, 12-41x cleaner than the real scratch
rate -- so scratches are invisible and the availability time is not merely
unknown, it is known false. `assert_point_in_time` therefore RAISES for those
features. They may still be served, under a named, versioned parameter that is
stamped on every artifact (`STARTER_IDENTITY`, `LINEUP_POSTING`), which is the
audit's own recommendation. What is forbidden is describing them as
point-in-time.

EXECUTION, AND THE TIE-BREAK
----------------------------
Design section 5's three modes. The tie-break rule that section demands, stated
once and implemented once:

  Best price is the maximum DECIMAL payout on the board (never the maximum
  American integer -- +100 and -100 are the same price and `max` prefers the
  positive one, hazard H12). When two or more books share that maximum, the
  PRICE is used and the BOOK IS REPORTED AS None, with every tied book listed
  in `tied_books`. The engine never names one of them as the best book.

That is a refusal, not an ordering. 62.7% (2023) and 78.6% (2024) of instants
have a tie, so naming a winner by book key would manufacture a fact -- "this
book was reliably best" -- out of alphabetical order, in the majority of cases.
The price is order-invariant (a max over floats); the tied list is sorted. Both
are deterministic, and neither depends on file order.

SEALED DATA
-----------
2026-01-01..2026-08-27 is SEALED. Every entry point refuses it by name with
`SealedWindowError` before reading anything. 2025 is tuning-only and is refused
here too: the replay universe is 2023-24, full stop.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from src.analysis import prices as prices_mod
from src.core import odds as odds_math
from src.data import parks
from src.evolab.decide import FORBIDDEN_ATTRIBUTES, BoardMeta, WorldView
from src.evolab.registry import DEFAULT_REGISTRY
from src.pipeline import snapshots
from src.research import matrix as matrix_mod

# ---------------------------------------------------------------------------
# The boundaries, stated as constants so a violation is a named refusal
# ---------------------------------------------------------------------------

# The replay universe. 2025 is tuning-only and is not replayed; 2026 is sealed.
# Same tuple matrix.py guards on, referenced rather than restated so the two
# can never drift apart.
REPLAY_SEASONS = matrix_mod.ALLOWED_SEASONS

# docs/EVOLAB_PHASE0_FEASIBILITY.md section 5. Not enforced as an equality --
# a store that grows or a fixture run would both trip it -- but stamped on the
# manifest beside the count actually served, so a shortfall is visible.
PHASE0_UNIVERSE = 4819
PHASE0_UNIVERSE_BY_SEASON = {2023: 2408, 2024: 2411}

# The sealed forward window. Refused by name, before any read.
SEALED_START = dt.date(2026, 1, 1)
SEALED_END = dt.date(2026, 8, 27)

# The two point classes that survive the measured snapshot grid.
EARLY_BOARD = "EARLY_BOARD"
LATE_BOARD = "LATE_BOARD"
POINT_CLASSES = (EARLY_BOARD, LATE_BOARD)

# EARLY_BOARD is the latest observation at least this far before first pitch.
# Six hours because that is the store's own median spacing: it is the coarsest
# rung that reliably exists and is reliably distinct from the late board.
EARLY_BOARD_MIN_GAP_MINUTES = 360.0

# The declared lineup-posting assumption (Phase 0 recommendation 3). T-180 is
# where the coverage cliff sits; it is an ASSUMPTION, not a measurement, and
# every artifact carries it.
LINEUP_ASSUMED_POST_MINUTES = 180.0

# Markets Phase 1 serves. h2h only: the historical store holds h2h and totals
# and no spreads at all, and F5 is ~290 games at one observation each -- a
# board with no second instant cannot answer a timing question and is not
# served rather than served thinly.
MARKETS_SERVED = ("h2h",)
H2H = "h2h"

# A consensus over fewer books is that handful's opinion. Same floor as
# everywhere else in the system.
MIN_BOOKS = prices_mod.MIN_BOOKS

# Execution modes, spelled the way genome.py spells them.
CONSENSUS_EXECUTION = "CONSENSUS_EXECUTION"
SPECIFIC_BOOK_EXECUTION = "SPECIFIC_BOOK_EXECUTION"
BEST_OBSERVED_EXECUTION = "BEST_OBSERVED_EXECUTION"
EXECUTION_MODES = (CONSENSUS_EXECUTION, SPECIFIC_BOOK_EXECUTION,
                   BEST_OBSERVED_EXECUTION)

# Execution refusal reasons. Vocabulary shared with decide.py where one
# already exists, so autopsy reporting stays a lookup rather than a
# translation layer.
MARKET_UNAVAILABLE = "MARKET_UNAVAILABLE"
NOT_SIMULTANEOUS = "NOT_SIMULTANEOUS"
THIN_CONSENSUS = "THIN_CONSENSUS"
BOOK_ABSENT = "BOOK_ABSENT"
UNPRICEABLE = "UNPRICEABLE"

ENGINE_VERSION = "phase1.1.0"

EVIDENCE_LABEL = (
    "Evolution Lab replay -- exploratory sandbox, NOT evidence. Replayed "
    "against a store whose outcomes are already known; only the forward "
    "ledger arbitrates. Price improvement here is line-shopping value, never "
    "EV and never edge.")

# The fields copied out of a price path. An ALLOWLIST, not a blocklist: a new
# outcome-shaped key added to pricepath upstream cannot arrive here by
# default, which is the difference between a guarantee and a habit.
QUOTE_FIELDS = ("book", "snapshot_at", "gap_minutes", "away_price",
                "home_price")


class ReplayError(RuntimeError):
    """Raised when a replay cannot be served honestly."""


class SealedWindowError(ReplayError):
    """Raised when anything reaches for the sealed 2026 window.

    Its own class, not a message, because a seal breach must be catchable and
    countable rather than indistinguishable from a typo in a season number.
    """


class LeakageError(ReplayError):
    """Raised when a fact dated after T reaches the decision path.

    Unreachable through `iter_instants_through`, which stops at T. Kept as the
    alarm that fires if a future caller assembles a board by some other route.
    """


class NotPointInTimeError(ReplayError):
    """Raised when a feature with no proved availability time is described as
    point-in-time."""


# ---------------------------------------------------------------------------
# Availability classes and the two declared assumptions
# ---------------------------------------------------------------------------

# docs/EVOLAB_PHASE0_FEASIBILITY.md section 3's classes, per feature.
#   A = schedule publication (months ahead, safe by inspection)
#   B = a named snapshot instant (exact, store-recorded)
#   C = max(month cutoff, probable announcement) -- announcement NOT recorded,
#       and the stored probable is the actual starter (the audit)
#   D = lineup posting -- NOT recorded anywhere for 2023-24
FEATURE_AVAILABILITY = {
    "lineup_platoon_share": "D",
    "lineup_vs_primary_pitch": "D",
    "lineup_vs_starter_history": "D",
    "top_minus_bottom": "D",
    "primary_pitch_share": "C",
    "primary_pitch": "C",
    "starter_platoon_gap": "C",
    "starter_velocity_gap": "C",
    "starter_groundball_share": "C",
}

# Class D features that ALSO need the probable (Phase 0's "needs C too"), plus
# every class C feature. These are the starter-conditioned set: the ones the
# probable-pitcher audit's leak reaches.
STARTER_CONDITIONED = frozenset({
    "lineup_platoon_share", "lineup_vs_primary_pitch",
    "lineup_vs_starter_history", "primary_pitch", "primary_pitch_share",
    "starter_platoon_gap", "starter_velocity_gap", "starter_groundball_share",
})

# Schedule and market facts, which DO have a provable availability time.
POINT_IN_TIME_FIELDS = frozenset({
    "away_team", "home_team", "park", "commence_time", "official_date",
    "board", "board_meta", "observed_utc", "books", "away_price",
    "home_price", "consensus_probability",
})


@dataclass(frozen=True)
class EngineParameter:
    """One named, versioned assumption the engine runs under.

    Hazard H13: an unstated input that silently changes results is the same
    class of danger as non-determinism. These are neither defaults nor
    conventions -- they are parameters, they carry a version, and
    `ReplayManifest` stamps them on every artifact.
    """

    name: str
    version: str
    value: str
    source: str
    measured: dict = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "version": self.version,
                "value": self.value, "source": self.source,
                "measured": dict(sorted(self.measured.items())),
                "note": self.note}


STARTER_IDENTITY = EngineParameter(
    name="starter_identity",
    version="1.0.0",
    value="actual_at_first_pitch",
    source="docs/AUDIT_PROBABLE_PITCHER_PIT.md",
    measured={
        "announced_probable_available": False,
        "measured_agreement_with_actual_2023": 0.9990,
        "measured_agreement_with_actual_2024": 0.9992,
        "side_level_disagreement_2023": 0.001029,
        "side_level_disagreement_2024": 0.000824,
    },
    note=("The stored probable is effectively the actual first-pitch starter: "
          "agreement is 12-41x too clean to be a pre-game announcement "
          "snapshot, so late scratches are invisible. ~2-8% of rows may carry "
          "a starter the live system could not have known; residual visible "
          "disagreement 0.09%. Not repairable -- no archived probables feed "
          "with fetch timestamps exists for 2023-24 and none can be bought."),
)

LINEUP_POSTING = EngineParameter(
    name="lineup_posting",
    version="1.0.0",
    value="assumed_T_minus_180_minutes",
    source="docs/EVOLAB_PHASE0_FEASIBILITY.md section 3",
    measured={
        "posting_timestamp_available": False,
        "assumed_post_minutes_before_first_pitch": LINEUP_ASSUMED_POST_MINUTES,
        "executable_universe_at_assumption": 3624,
        "full_universe": PHASE0_UNIVERSE,
    },
    note=("data/historical/lineups.jsonl records the lineup that was posted "
          "and not when. Under the T-180 assumption the executable universe "
          "falls to ~3,624 games, and the survivors are selected by first "
          "pitch time, which correlates with coast and day of week. That "
          "selection must be reported with any lineup-conditioned result."),
)


def availability_class(feature) -> str:
    """The availability class of one feature name, or ReplayError.

    Bare feature names (no away_/home_ prefix), because the class is a
    property of the quantity, not of the side.
    """
    name = str(feature)
    # Board fields are checked BEFORE the side prefix is stripped:
    # `away_price` is a market fact whose bare name is `price`, and stripping
    # first would ask the wrong question of it.
    if name in POINT_IN_TIME_FIELDS:
        return "B" if name in ("board", "board_meta", "observed_utc", "books",
                               "away_price", "home_price",
                               "consensus_probability") else "A"
    for prefix in ("away_", "home_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    if name in FEATURE_AVAILABILITY:
        return FEATURE_AVAILABILITY[name]
    if name in POINT_IN_TIME_FIELDS:
        return "A"
    raise ReplayError(
        f"{feature!r} has no recorded availability class; every quantity the "
        "engine serves must be classified in FEATURE_AVAILABILITY before it "
        "can be served, because an unclassified quantity is one nobody has "
        "asked when it became knowable")


def assert_point_in_time(feature) -> str:
    """Return the class if `feature` is genuinely point-in-time, else raise.

    Classes A (schedule) and B (a named snapshot instant) pass: both have an
    availability time that is either safe by inspection or recorded exactly in
    the store. C and D do not, and the refusal distinguishes them because the
    two failures are different:

      D -- the availability time is UNKNOWN. No lineup posting timestamp
           exists for 2023-24 and none can be reconstructed.
      C -- the availability time is KNOWN FALSE. The stored probable is the
           actual first-pitch starter, so a class C feature was, in the store,
           available only after the game began.

    `src/model/pointintime.py` marks the rebuilt inputs CLEAN, which is a
    correct and DIFFERENT claim: those accumulations respect their cutoff. "The
    accumulation is cutoff-respecting" is not "the pitcher id was knowable at
    T", and this function is where the distinction stops being a footnote.
    """
    klass = availability_class(feature)
    if klass in ("A", "B"):
        return klass
    if klass == "C":
        raise NotPointInTimeError(
            f"{feature!r} is availability class C: it is conditioned on the "
            "probable pitcher, whose announcement time is not recorded for "
            "2023-24 and whose stored value is the ACTUAL first-pitch starter "
            f"(agreement {STARTER_IDENTITY.measured['measured_agreement_with_actual_2023']}"
            f" / {STARTER_IDENTITY.measured['measured_agreement_with_actual_2024']}, "
            "12-41x too clean for an announcement snapshot). It may be SERVED "
            f"under the named parameter {STARTER_IDENTITY.name} v"
            f"{STARTER_IDENTITY.version}; it may not be CALLED point-in-time. "
            "See docs/AUDIT_PROBABLE_PITCHER_PIT.md")
    raise NotPointInTimeError(
        f"{feature!r} is availability class D: it is conditioned on the posted "
        "lineup, and no lineup posting timestamp exists for 2023-24. It may be "
        f"SERVED under the named parameter {LINEUP_POSTING.name} v"
        f"{LINEUP_POSTING.version} (assumed posting at T-"
        f"{int(LINEUP_ASSUMED_POST_MINUTES)} minutes); it may not be CALLED "
        "point-in-time. See docs/EVOLAB_PHASE0_FEASIBILITY.md section 3")


def is_starter_conditioned(feature) -> bool:
    """True when the probable-pitcher leak reaches this feature."""
    name = str(feature)
    for prefix in ("away_", "home_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name in STARTER_CONDITIONED


# ---------------------------------------------------------------------------
# Sealed-window and season guards -- before any read
# ---------------------------------------------------------------------------

def _as_date(value):
    """A date from a date, datetime or ISO-ish string; None when unreadable.

    None over a guess: an unparseable stamp must not become 1970-01-01 and
    sail through a seal check.
    """
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def refuse_sealed(value, *, what="date"):
    """Raise SealedWindowError if `value` falls inside the sealed window.

    Accepts a date, datetime, ISO string or season number. Called at every
    entry point BEFORE anything is read, so a sealed request never touches a
    file -- the same discipline `test_validation_pit.py` already tests for the
    sealed seasons elsewhere in the project.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        if SEALED_START.year <= value <= SEALED_END.year:
            raise SealedWindowError(
                f"season {value} overlaps the SEALED window "
                f"{SEALED_START.isoformat()}..{SEALED_END.isoformat()}; the "
                "replay engine refuses it before reading anything. The sealed "
                "forward window is the project's only independent arbiter and "
                "the lab does not get to look at it")
        return value
    day = _as_date(value)
    if day is not None and SEALED_START <= day <= SEALED_END:
        raise SealedWindowError(
            f"{what} {day.isoformat()} is inside the SEALED window "
            f"{SEALED_START.isoformat()}..{SEALED_END.isoformat()}; the replay "
            "engine refuses it before reading anything")
    return value


def _validated_seasons(seasons) -> tuple:
    """Sorted, deduplicated replay seasons, or a named refusal."""
    if seasons is None:
        return tuple(REPLAY_SEASONS)
    if isinstance(seasons, int) and not isinstance(seasons, bool):
        seasons = (seasons,)
    out = []
    for season in seasons:
        try:
            season = int(season)
        except (TypeError, ValueError):
            raise ReplayError(f"season {season!r} is not a year")
        refuse_sealed(season, what="season")
        if season not in REPLAY_SEASONS:
            raise ReplayError(
                f"season {season} is outside the replay universe "
                f"{tuple(REPLAY_SEASONS)}; 2025 is tuning-only and 2026 is "
                "sealed. The lab replays 2023-24 and nothing else")
        out.append(season)
    if not out:
        raise ReplayError("no seasons requested")
    return tuple(sorted(set(out)))


# ---------------------------------------------------------------------------
# The universe: games, boards, and no outcome anywhere
# ---------------------------------------------------------------------------

def _parse_utc(value):
    """A timezone-aware UTC datetime, or None."""
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.timezone.utc)


def _iso(moment) -> str:
    """One canonical spelling of an instant, so digests compare."""
    return moment.astimezone(dt.timezone.utc).isoformat()


@dataclass(frozen=True)
class Quote:
    """One book's two-way price at one observed instant."""

    book: str
    away_price: int
    home_price: int


@dataclass(frozen=True)
class Instant:
    """Every book's quote for one game at ONE observed snapshot.

    Simultaneity is a fact about how the store was written, not an assumption:
    every book quoting a game at one instant arrives inside a single API
    response carrying a single `snapshot_at`, so this cross-section was
    genuinely on the board at once (Phase 0 section 2, measured: no quote is
    more than 15 minutes stale relative to its own snapshot). The flag is
    computed rather than asserted so a stitched board built by some other
    route reports itself as stitched and best-price execution refuses it.
    """

    observed: dt.datetime
    gap_minutes: float
    quotes: tuple

    @property
    def books(self) -> tuple:
        return tuple(q.book for q in self.quotes)

    @property
    def simultaneous(self) -> bool:
        return len(self.quotes) > 0


class ReplayGame:
    """One game in the replay universe: identity, features, and its boards.

    NO OUTCOME. Not a hidden outcome, not a private outcome -- there is no
    field, because the loader never copies one out of the price path. The same
    forbidden-name guard `WorldView` carries is repeated here, because this
    object is the carrier and a guarantee that only holds at the last hop is
    not a guarantee.

    __slots__ for the same reason decide.py uses it: it stops anyone attaching
    an `outcome` after construction, which is how a leak would actually arrive.
    """

    __slots__ = ("game_pk", "season", "official_date", "commence_time",
                 "away_team", "home_team", "park", "cutoff", "features",
                 "instants", "game_key", "event_id")

    def __init__(self, *, game_pk, season, official_date, commence_time,
                 away_team, home_team, park, cutoff, features, instants,
                 game_key, event_id):
        object.__setattr__(self, "game_pk", str(game_pk))
        object.__setattr__(self, "season", int(season))
        object.__setattr__(self, "official_date", official_date)
        object.__setattr__(self, "commence_time", commence_time)
        object.__setattr__(self, "away_team", away_team)
        object.__setattr__(self, "home_team", home_team)
        object.__setattr__(self, "park", park)
        object.__setattr__(self, "cutoff", cutoff)
        object.__setattr__(self, "features", dict(features))
        object.__setattr__(self, "instants", tuple(instants))
        object.__setattr__(self, "game_key", tuple(game_key))
        object.__setattr__(self, "event_id", event_id)

    def __setattr__(self, name, value):
        raise ReplayError(
            f"ReplayGame is frozen; {name!r} cannot be set after "
            "construction. A game that can be edited mid-replay is a game "
            "whose decisions cannot be reproduced")

    def __getattr__(self, name):
        if name.lower() in FORBIDDEN_ATTRIBUTES:
            raise AttributeError(
                f"ReplayGame has no {name!r} and never will. The replay engine "
                "does not read outcomes or post-decision prices out of the "
                "store at all; fitness joins them after every decision is "
                "already fixed (docs/EVOLAB_DESIGN.md section 2)")
        raise AttributeError(f"ReplayGame has no attribute {name!r}")

    def __repr__(self):
        return (f"ReplayGame({self.game_pk}, {self.official_date}, "
                f"{self.away_team}@{self.home_team}, "
                f"{len(self.instants)} instants)")


def iter_instants_through(game, T):
    """Yield this game's instants up to and INCLUDING T, then stop.

    The single gate every board goes through, and the reason acceptance test 2
    passes. Two properties do the work:

      - `break`, not `continue`. The scan halts at the first observation after
        T rather than stepping over it and carrying on, so a future row is not
        skipped -- it is never reached. Rows the loop never reaches cannot
        influence anything downstream, including through a bug.
      - inclusive at T. T is itself an observed instant (Phase 0 recommendation
        2: the clock's alphabet is the store's own), so the board stamped T is
        the board at T. Future means strictly after T.

    Instants are stored ascending, which the loader guarantees by sorting.
    """
    for instant in game.instants:
        if instant.observed > T:
            break
        yield instant


def board_at(game, T):
    """The latest instant at or before T, or None. Never an interpolation."""
    latest = None
    for instant in iter_instants_through(game, T):
        latest = instant
    return latest


# ---------------------------------------------------------------------------
# Loading -- projection through an allowlist, deduplication, no outcome
# ---------------------------------------------------------------------------

def _project_quotes(path, counters):
    """A price path's quotes as {observed: {book: Quote}}, deduplicated.

    Only QUOTE_FIELDS are read. `home_won` and `total_runs` sit on the same
    dict and are not copied, not inspected and not counted -- this function is
    where the outcome stops travelling.

    Hazard H4: the API can serve one snapshot for two requested times, and
    `pricepath` appends both, so a book can appear twice at one instant and a
    consensus mean would weight it double. Every observed duplicate is
    byte-identical today, so the dedupe is a no-op on real data -- but when a
    duplicate DISAGREES the book is dropped from that instant entirely rather
    than resolved by picking one, because there is no honest way to choose
    between two prices that claim the same moment.
    """
    by_instant = {}
    conflicts = set()
    for raw in path.get("quotes") or []:
        quote = {key: raw.get(key) for key in QUOTE_FIELDS}
        observed = _parse_utc(quote["snapshot_at"])
        book = quote["book"]
        if observed is None or not book:
            counters["quotes_unusable"] += 1
            continue
        away, home = quote["away_price"], quote["home_price"]
        if away is None or home is None:
            counters["quotes_unusable"] += 1
            continue
        slot = by_instant.setdefault(observed, {})
        existing = slot.get(book)
        if existing is not None:
            if (existing.away_price, existing.home_price) != (away, home):
                conflicts.add((observed, book))
                counters["duplicate_quotes_conflicting"] += 1
            else:
                counters["duplicate_quotes_identical"] += 1
            continue
        slot[book] = Quote(book=book, away_price=away, home_price=home)
    for observed, book in conflicts:
        by_instant.get(observed, {}).pop(book, None)
    return by_instant


def _instants_from_path(path, commence, counters) -> tuple:
    """Sorted Instants for one path, every one strictly before first pitch.

    `commence` is the SCHEDULE's first pitch (the matrix row's
    `start_time_utc`), not the odds event's. They usually agree, but the odds
    feed revises `commence_time` between snapshots -- a rain delay or a
    correction -- and `pricepath` filters each record against whatever the
    feed said at the time while stamping the path with the first value it saw.
    Measured consequence on the real store: quotes that postdate the stored
    first pitch survive into a path. Filtering here against the schedule
    closes that, and the drops are counted rather than silent (hazard H8).
    """
    out = []
    for observed, by_book in sorted(_project_quotes(path, counters).items()):
        if observed >= commence:
            counters["quotes_at_or_after_first_pitch"] += 1
            continue
        quotes = tuple(by_book[book] for book in sorted(by_book))
        if not quotes:
            continue
        gap = (commence - observed).total_seconds() / 60.0
        out.append(Instant(observed=observed, gap_minutes=gap, quotes=quotes))
    return tuple(out)


def _pick_path(candidates):
    """One price path per game_pk, chosen by a stated rule (hazard H5).

    Six game_pks across 2023-24 carry more than one odds event. The richer
    board wins -- most distinct instants, then most quotes -- and an exact tie
    falls to the lowest event_id. Stated so the choice is a rule rather than a
    property of which line the backfill happened to write first.
    """
    if len(candidates) == 1:
        return candidates[0]
    return sorted(
        candidates,
        key=lambda p: (-len({q.get("snapshot_at") for q in p.get("quotes") or []}),
                       -len(p.get("quotes") or []),
                       str(p.get("event_id"))))[0]


def _features_for(row, registry) -> dict:
    """The registry's features for one matrix row, both sides, or None.

    The registry is the gate (design section 3 rule 3): a matrix column with
    no registered mechanism is not served at all, so nothing can be searched
    that nobody has written a mechanism for. Non-numeric values become None
    rather than being coerced -- `lineup_vs_starter_history` is a dict, and a
    dict silently truncated to a number is a fabricated feature.
    """
    out = {}
    for feature in registry.features():
        for side in ("away", "home"):
            key = f"{side}_{feature}"
            value = row.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                value = None
            out[key] = value
    return out


@dataclass(frozen=True)
class ReplayUniverse:
    """The games the engine serves, in one deterministic order, plus provenance.

    Ordered by (commence_time, game_pk) -- never by file order, which hazard H7
    shows is a property of how a resumable build was run rather than of the
    data.
    """

    games: tuple
    manifest: "ReplayManifest"

    def by_id(self) -> dict:
        return {game.game_pk: game for game in self.games}

    def get(self, game_pk):
        # Was a linear scan over self.games sitting beside an unused by_id()
        # (map-compute-scale.md section 2b) -- O(n) per call, harmless only
        # because nothing today calls it in a per-game loop. Routed through
        # by_id() instead: behaviour-identical (same lookup key, same
        # ReplayError on a miss), verified by
        # tests/test_replay_universe_get.py on a fixture universe.
        try:
            return self.by_id()[str(game_pk)]
        except KeyError:
            raise ReplayError(f"game {game_pk!r} is not in the replay universe")

    def __len__(self) -> int:
        return len(self.games)

    def __iter__(self):
        return iter(self.games)


def load_universe(seasons=REPLAY_SEASONS, *, paths_by_season=None,
                  matrix_rows_by_season=None, out_dir=None, store=None,
                  registry=DEFAULT_REGISTRY, code_commit=None,
                  source_label=None, timings=None) -> ReplayUniverse:
    """The replay universe: games with a matrix row AND usable pre-game odds.

    That join is Phase 0 section 5's definition and its 4,819-game answer. Both
    stores are injectable so tests run on fixtures in milliseconds; when they
    are injected the manifest says so instead of naming files, because a
    fixture run must never be mistakable for a store run.

    Nothing about an outcome is read. `pricepath.build` returns `home_won` and
    `total_runs` on every path and this function copies neither.

    `timings`, if a `src.core.timing.TimingCollector`, gets one
    "universe_build" stage recording this call's wall/CPU/RSS -- purely
    additive: omitted (the default), nothing about the returned
    `ReplayUniverse` changes (map-compute-scale.md section 1).
    """
    from src.core.timing import stage as _stage
    from contextlib import nullcontext as _null
    with (_stage("universe_build", collector=timings) if timings is not None
         else _null()):
        return _load_universe(
            seasons, paths_by_season=paths_by_season,
            matrix_rows_by_season=matrix_rows_by_season, out_dir=out_dir,
            store=store, registry=registry, code_commit=code_commit,
            source_label=source_label)


def _load_universe(seasons, *, paths_by_season, matrix_rows_by_season,
                   out_dir, store, registry, code_commit,
                   source_label) -> ReplayUniverse:
    """The actual universe build -- see load_universe's docstring. Split out
    so the timing wrapper above has a single call to measure without an
    early `return` inside the `with` block skipping the stage's own
    bookkeeping (a `return` inside a `with` still runs `__exit__`, but
    keeping the timed region to exactly "call this function" is simpler to
    reason about than auditing every early exit here for that property)."""
    seasons = _validated_seasons(seasons)
    injected = paths_by_season is not None or matrix_rows_by_season is not None

    if paths_by_season is None:
        from src.research import pricepath  # deferred: heavy, and unused on fixtures
        kwargs = {"store": store} if store is not None else {}
        paths_by_season = {season: pricepath.build(season, **kwargs)
                           for season in seasons}
    if matrix_rows_by_season is None:
        matrix_kwargs = {"out_dir": out_dir} if out_dir is not None else {}
        matrix_rows_by_season = {
            season: list(matrix_mod.read(season, **matrix_kwargs).values())
            for season in seasons}

    counters = {"quotes_unusable": 0, "duplicate_quotes_identical": 0,
                "duplicate_quotes_conflicting": 0, "matrix_rows": 0,
                "no_price_path": 0, "no_usable_instant": 0,
                "multi_event_games": 0, "official_date_disagreements": 0,
                "quotes_at_or_after_first_pitch": 0, "no_first_pitch": 0}

    games, by_season = [], {}
    for season in seasons:
        paths_by_pk = {}
        for path in paths_by_season.get(season) or []:
            paths_by_pk.setdefault(str(path.get("game_pk")), []).append(path)

        rows = matrix_rows_by_season.get(season) or []
        seen = set()
        for row in sorted(rows, key=lambda r: (str(r.get("date")),
                                               str(r.get("game_pk")))):
            game_pk = str(row.get("game_pk"))
            if game_pk in seen:
                raise ReplayError(
                    f"matrix row for game {game_pk} appears twice in season "
                    f"{season}; a duplicated row makes the universe depend on "
                    "which copy was read last")
            seen.add(game_pk)
            counters["matrix_rows"] += 1

            candidates = paths_by_pk.get(game_pk)
            if not candidates:
                counters["no_price_path"] += 1
                continue
            if len(candidates) > 1:
                counters["multi_event_games"] += 1
            path = _pick_path(candidates)

            # The schedule's first pitch is authoritative: it is availability
            # class A (published months ahead) and it is the value every other
            # store in the project agrees on. The odds event's own
            # commence_time is a feed value that gets revised.
            commence = _parse_utc(row.get("start_time_utc"))
            if commence is None:
                commence = _parse_utc(path.get("commence_time"))
                counters["no_first_pitch"] += 1
            if commence is None:
                counters["no_usable_instant"] += 1
                continue
            instants = _instants_from_path(path, commence, counters)
            if not instants:
                counters["no_usable_instant"] += 1
                continue

            official = snapshots.official_date(_iso(commence))
            if official != str(row.get("date")):
                # Counted, not corrected. The Eastern official date is the
                # project's identity (snapshots.game_key) and the matrix date
                # comes from the results CSV; a disagreement is a data fact
                # worth a manifest line, not something to silently pick from.
                counters["official_date_disagreements"] += 1
            away = parks.canonical_team(row.get("away_team"))
            home = parks.canonical_team(row.get("home_team"))
            try:
                park = parks.get_park(home)["name"]
            except parks.ParkError:
                park = None
            refuse_sealed(official, what="game date")

            games.append(ReplayGame(
                game_pk=game_pk,
                season=season,
                official_date=official,
                commence_time=commence,
                away_team=away,
                home_team=home,
                park=park,
                cutoff=row.get("cutoff"),
                features=_features_for(row, registry),
                instants=instants,
                game_key=snapshots.game_key(away, home, _iso(commence)),
                event_id=path.get("event_id"),
            ))
        by_season[season] = sum(1 for g in games if g.season == season)

    games.sort(key=lambda g: (g.commence_time, g.game_pk))

    manifest = ReplayManifest.build(
        seasons=seasons, games=games, games_by_season=by_season,
        exclusions=counters, registry=registry, code_commit=code_commit,
        injected=injected, out_dir=out_dir, store=store,
        source_label=source_label)
    return ReplayUniverse(games=tuple(games), manifest=manifest)


# ---------------------------------------------------------------------------
# Decision points: the two-class ladder
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DecisionPoint:
    """One (game, T) pair at which a strategy may act.

    `T` is an observed instant, never a wall-clock time and never an
    interpolation. `gap_minutes` travels with it because a "late board" at a
    median 85 minutes out is not a close and the number is the only thing that
    stops it being read as one.
    """

    game_pk: str
    official_date: str
    commence_time: str
    T: str
    point_class: str
    gap_minutes: float
    books: int

    def to_dict(self) -> dict:
        return {"game_pk": self.game_pk, "official_date": self.official_date,
                "commence_time": self.commence_time, "T": self.T,
                "point_class": self.point_class,
                "gap_minutes": round(self.gap_minutes, 6),
                "books": self.books}


def classify_points(game) -> tuple:
    """This game's decision points as ((point_class, Instant), ...).

    LATE_BOARD is the last pre-game observation. EARLY_BOARD is the latest
    observation at least EARLY_BOARD_MIN_GAP_MINUTES before first pitch. When
    the two land on the same instant -- a game with one observation, or one
    whose only boards are all early -- only LATE_BOARD is emitted. Emitting
    both would score one board twice and quietly double a strategy's sample.
    """
    if not game.instants:
        return ()
    late = game.instants[-1]
    early = None
    for instant in game.instants:
        if instant.gap_minutes >= EARLY_BOARD_MIN_GAP_MINUTES:
            early = instant
    out = []
    if early is not None and early.observed != late.observed:
        out.append((EARLY_BOARD, early))
    out.append((LATE_BOARD, late))
    return tuple(out)


def decision_points(seasons=REPLAY_SEASONS, *, universe=None, **kwargs):
    """The replay's decision points, in one deterministic order.

    Ordered by (commence_time, game_pk, point-class rank), which is a total
    order over the universe and independent of file order, dict order and
    hash seed. `universe` is accepted so a caller that already loaded one does
    not pay for it twice.
    """
    if universe is None:
        universe = load_universe(seasons, **kwargs)
    elif kwargs:
        raise ReplayError("pass either a loaded universe or loader arguments, "
                          "not both")
    for game in universe.games:
        for point_class, instant in classify_points(game):
            yield DecisionPoint(
                game_pk=game.game_pk,
                official_date=game.official_date,
                commence_time=_iso(game.commence_time),
                T=_iso(instant.observed),
                point_class=point_class,
                gap_minutes=instant.gap_minutes,
                books=len(instant.quotes),
            )


# ---------------------------------------------------------------------------
# WorldView assembly
# ---------------------------------------------------------------------------

def world_view(game, T, *, point_class=None, timings=None) -> WorldView:
    """Everything visible at T for this game, and structurally nothing else.

    `T` must be one of this game's observed instants: the engine serves
    observations and refuses to interpolate (Phase 0 recommendation 2). A
    strategy asking for a price at a time nobody quoted gets a refusal, not a
    number.

    `lineup_posted` is the DECLARED ASSUMPTION, not a fact: true when T is
    within LINEUP_POSTING's assumed posting window. No lineup posting
    timestamp exists for 2023-24, so this flag is a parameter's output and is
    stamped as one on every artifact.

    `timings`, if given a `src.core.timing.TimingCollector`, records one
    "world_view" stage per call -- additive only; callers that never pass it
    (every existing caller) see no behavior change. Not the default choice
    for a per-decision hot path (a caller iterating thousands of decision
    points should pass its OWN outer stage instead, per sweep.py's pattern,
    to avoid per-call collector overhead dominating the measurement), but
    available for a caller that wants exactly this granularity.
    """
    from src.core.timing import stage as _stage
    from contextlib import nullcontext as _null
    with (_stage("world_view", collector=timings) if timings is not None
         else _null()):
        return _world_view(game, T, point_class=point_class)


def _world_view(game, T, *, point_class=None) -> WorldView:
    moment = _parse_utc(T)
    if moment is None:
        raise ReplayError(f"T {T!r} is not a readable instant")
    refuse_sealed(moment, what="decision time")

    instant = None
    for candidate in iter_instants_through(game, moment):
        if candidate.observed == moment:
            instant = candidate
    if instant is None:
        raise ReplayError(
            f"no observation for game {game.game_pk} at {_iso(moment)}; the "
            "engine serves the store's own instants and never interpolates a "
            "board between them (docs/EVOLAB_PHASE0_FEASIBILITY.md section 9, "
            "recommendation 2)")

    # Defensive, and deliberately unreachable through the generator above: if
    # a quote dated after T ever reaches board assembly, the run stops.
    if instant.observed > moment:
        raise LeakageError(
            f"board for game {game.game_pk} is stamped {_iso(instant.observed)}, "
            f"after T={_iso(moment)}")

    if point_class is None:
        point_class = next((klass for klass, i in classify_points(game)
                            if i.observed == moment), LATE_BOARD)
    if point_class not in POINT_CLASSES:
        raise ReplayError(
            f"point_class {point_class!r} is not one of {POINT_CLASSES}; the "
            "ladder is pre-registered so no strategy can invent a bespoke "
            "timing, and the finer rungs the design first proposed do not "
            "exist in this store")

    board = {H2H: {q.book: {"away_price": q.away_price,
                            "home_price": q.home_price}
                   for q in instant.quotes}}
    meta = BoardMeta(
        observed_utc=_iso(instant.observed),
        books=tuple(sorted(q.book for q in instant.quotes)),
        simultaneous=instant.simultaneous,
        # Zero by construction: the decision instant IS the observation. The
        # field is kept and computed rather than hardcoded so a future
        # decision point that is not an observation would report its own
        # staleness instead of claiming freshness it does not have.
        staleness_seconds=int((moment - instant.observed).total_seconds()),
    )
    return WorldView(
        game_id=game.game_pk,
        official_date=game.official_date,
        commence_time=_iso(game.commence_time),
        point_class=point_class,
        game={"away": game.away_team, "home": game.home_team,
              "park": game.park, "commence_time": _iso(game.commence_time)},
        features=dict(game.features),
        board=board,
        board_meta=meta,
        available=tuple(m for m in MARKETS_SERVED if board.get(m)),
        lineup_posted=instant.gap_minutes <= LINEUP_ASSUMED_POST_MINUTES,
    )


def worldview_dict(view) -> dict:
    """A WorldView as a canonically ordered plain dict.

    The serialisation the determinism tests hash. Sorted keys throughout and
    one spelling per instant, so two runs that saw the same world produce the
    same bytes rather than the same meaning.
    """
    return {
        "game_id": view.game_id,
        "official_date": view.official_date,
        "commence_time": view.commence_time,
        "point_class": view.point_class,
        "game": {k: view.game[k] for k in sorted(view.game)},
        "features": {k: view.features[k] for k in sorted(view.features)},
        "board": {market: {book: {side: quotes[book][side]
                                  for side in sorted(quotes[book])}
                           for book in sorted(quotes)}
                  for market, quotes in sorted(view.board.items())},
        "board_meta": {"observed_utc": view.board_meta.observed_utc,
                       "books": list(view.board_meta.books),
                       "simultaneous": view.board_meta.simultaneous,
                       "staleness_seconds": view.board_meta.staleness_seconds},
        "available": list(view.available),
        "lineup_posted": view.lineup_posted,
    }


def _canonical_json(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, default=str)


def worldview_digest(view) -> str:
    """A sha256 over the canonical serialisation. Byte-identity, testable."""
    return hashlib.sha256(
        _canonical_json(worldview_dict(view)).encode("utf-8")).hexdigest()


def decision_dict(decision) -> dict:
    """A Decision (or NO_PLAY) as a canonically ordered plain dict."""
    if not decision:
        return {"decision": "NO_PLAY"}
    return {"decision": "PLAY", "market": decision.market,
            "side": decision.side, "score": repr(decision.score),
            "signals_fired": [list(s) for s in decision.signals_fired],
            "execution_mode": decision.execution_mode}


def decision_digest(decision) -> str:
    return hashlib.sha256(
        _canonical_json(decision_dict(decision)).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Execution (design section 5)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExecutionQuote:
    """What a strategy would have transacted at, or a named refusal.

    Falsy when refused, so `if quote:` reads correctly. A refusal is a first
    class answer here: design section 5's rule is that execution is never a
    silent assumption, and "no price" is a legitimate outcome of asking for
    one.

    `consensus_probability` is a de-vigged probability, not a price, and
    `price` is None in CONSENSUS_EXECUTION for that reason -- a consensus is
    the board's opinion, not a number any book quoted. Neither is an edge, an
    EV or an advantage.
    """

    mode: str
    market: str
    side: str
    observed_utc: str
    books: int
    price: object = None
    book: object = None
    tied_books: tuple = ()
    consensus_probability: object = None
    refused: str = ""

    def __bool__(self) -> bool:
        return not self.refused

    def to_dict(self) -> dict:
        return {"mode": self.mode, "market": self.market, "side": self.side,
                "observed_utc": self.observed_utc, "books": self.books,
                "price": self.price, "book": self.book,
                "tied_books": list(self.tied_books),
                "consensus_probability": self.consensus_probability,
                "refused": self.refused,
                "label": prices_mod.LABEL}


def _side_prices(view, market, side) -> list:
    """[(book, american)] for one side, sorted by book.

    Sorted here, once, so every reduction downstream -- the de-vig mean
    especially -- accumulates in the same order on every run (hazard H2).
    """
    quotes = view.board.get(market) or {}
    key = "away_price" if side == "away" else "home_price"
    return [(book, quotes[book][key]) for book in sorted(quotes)
            if quotes[book].get(key) is not None]


def execution_quote(view, market, side, mode, *, book=None) -> ExecutionQuote:
    """The price this mode would have transacted at, or a refusal.

    Three modes, per design section 5, and never a silent assumption:

      CONSENSUS_EXECUTION      the de-vigged consensus across the board at T.
                               The primary mode, held identical across the
                               whole population during predictive search so no
                               strategy can win by execution while claiming
                               prediction. Refuses below the six-book floor.
      SPECIFIC_BOOK_EXECUTION  one named book's price at T, or no bet. The
                               realistic single-account case. Because the best
                               book is a coin flip in 63-79% of instants, a
                               result from this mode must NEVER be read as
                               "this book was reliably best".
      BEST_OBSERVED_EXECUTION  the best price among books observed at the same
                               instant -- permitted because the cross-section
                               is genuine, refused outright when the board is
                               not simultaneous, and always an upper bound.
                               Ties resolve by refusing to name a book; see
                               the module docstring.

    Takeability at stake is not measured and cannot be from anything we hold.
    "On the board" is the strongest claim available.
    """
    if mode not in EXECUTION_MODES:
        raise ReplayError(f"execution mode {mode!r} is not one of "
                          f"{EXECUTION_MODES}")
    if side not in ("away", "home"):
        raise ReplayError(f"side {side!r} is not 'away' or 'home'")
    observed = view.board_meta.observed_utc
    quotes = view.board.get(market) or {}
    if not quotes:
        return ExecutionQuote(mode=mode, market=market, side=side,
                              observed_utc=observed, books=0,
                              refused=MARKET_UNAVAILABLE)
    priced = _side_prices(view, market, side)

    if mode == CONSENSUS_EXECUTION:
        fairs = []
        for book_key in sorted(quotes):
            away = quotes[book_key].get("away_price")
            home = quotes[book_key].get("home_price")
            if away is None or home is None:
                continue
            try:
                fair_away, fair_home = odds_math.devig_two_way(away, home)
            except odds_math.OddsError:
                continue
            fairs.append(fair_away if side == "away" else fair_home)
        if len(fairs) < MIN_BOOKS:
            return ExecutionQuote(mode=mode, market=market, side=side,
                                  observed_utc=observed, books=len(fairs),
                                  refused=THIN_CONSENSUS)
        # math.fsum, not sum: correctly rounded and therefore order-invariant
        # by construction (hazard H2). The books are already sorted, so both
        # halves of the determinism guarantee hold.
        consensus = math.fsum(fairs) / len(fairs)
        return ExecutionQuote(mode=mode, market=market, side=side,
                              observed_utc=observed, books=len(fairs),
                              consensus_probability=consensus)

    if mode == SPECIFIC_BOOK_EXECUTION:
        if not book:
            raise ReplayError(
                "SPECIFIC_BOOK_EXECUTION needs the book named by the genome; "
                "choosing one here would be retroactive book selection")
        for name, price in priced:
            if name == book:
                return ExecutionQuote(mode=mode, market=market, side=side,
                                      observed_utc=observed,
                                      books=len(priced), price=price,
                                      book=name)
        return ExecutionQuote(mode=mode, market=market, side=side,
                              observed_utc=observed, books=len(priced),
                              refused=BOOK_ABSENT)

    # BEST_OBSERVED_EXECUTION
    if not view.board_meta.simultaneous:
        # Acceptance test 5 / design section 5: a best price stitched across
        # time is not a price anybody could have taken. Refused, not caveated.
        return ExecutionQuote(mode=mode, market=market, side=side,
                              observed_utc=observed, books=len(priced),
                              refused=NOT_SIMULTANEOUS)
    best_decimal, best_price, tied = None, None, []
    for name, price in priced:
        try:
            decimal = odds_math.american_to_decimal(price)
        except odds_math.OddsError:
            continue
        if best_decimal is None or decimal > best_decimal:
            best_decimal, best_price, tied = decimal, price, [name]
        elif decimal == best_decimal:
            tied.append(name)
    if best_decimal is None:
        return ExecutionQuote(mode=mode, market=market, side=side,
                              observed_utc=observed, books=len(priced),
                              refused=UNPRICEABLE)
    tied = tuple(sorted(tied))
    return ExecutionQuote(
        mode=mode, market=market, side=side, observed_utc=observed,
        books=len(priced), price=best_price,
        # One book, named. Several, and the book is None: the best PRICE is
        # real, the best BOOK usually is not.
        book=tied[0] if len(tied) == 1 else None,
        tied_books=tied)


# ---------------------------------------------------------------------------
# The manifest -- provenance stamped on every artifact
# ---------------------------------------------------------------------------

def _git_commit(repo_root=None):
    """The current commit, or None. NEVER a placeholder.

    An artifact stamped with a made-up commit is worse than one stamped with
    nothing: the first lies about being reproducible, the second admits it
    cannot prove it.
    """
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root),
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    commit = out.stdout.strip()
    return commit if out.returncode == 0 and commit else None


def _file_fingerprint(path):
    """{path, sha256, bytes} for one store file, or None when absent."""
    target = Path(path)
    if not target.exists():
        return None
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return {"path": str(target), "sha256": digest.hexdigest(),
            "bytes": target.stat().st_size}


def store_fingerprints(seasons, *, out_dir=None, store=None) -> dict:
    """Content hashes of every store the universe was built from.

    Content, not mtime: a store that was rebuilt byte-identically is the same
    store, and one edited in place is not, and only a hash can tell those
    apart. A missing file is recorded as missing rather than skipped, because
    "we did not read it" and "it was not there" are different provenance.
    """
    from src.pipeline import backfill
    odds_store = Path(store) if store else backfill.DEFAULT_STORE
    research = Path(out_dir) if out_dir else matrix_mod.DEFAULT_OUT_DIR
    out = {}
    for season in seasons:
        for label, path in (
                (f"odds_history_{season}", odds_store / f"mlb_{season}.jsonl"),
                (f"matchup_matrix_{season}",
                 research / f"matchup_matrix_{season}.jsonl")):
            out[label] = _file_fingerprint(path) or {"path": str(path),
                                                     "missing": True}
    out["mlb_results"] = (_file_fingerprint("data/historical/mlb_results.csv")
                          or {"path": "data/historical/mlb_results.csv",
                              "missing": True})
    return out


@dataclass(frozen=True)
class ReplayManifest:
    """The provenance every artifact carries, so a result cannot be read
    without it.

    Design section 11 requires world id, generator, seed, code commit, battery
    fingerprint and enumeration spec hash on every artifact; this is the
    replay half of that -- what universe was served, under which assumptions,
    from which bytes, at which commit. The two assumption parameters
    (STARTER_IDENTITY, LINEUP_POSTING) are here because hazard H13 says an
    unstated input that changes results is as dangerous as non-determinism,
    and the probable-pitcher audit's first recommendation is exactly this.

    `stamp` refuses to overwrite an existing manifest for the same reason: an
    artifact that quietly changed provenance is one whose numbers can no
    longer be attributed to anything.
    """

    engine_version: str
    seasons: tuple
    universe_size: int
    games_by_season: dict
    point_classes: dict
    markets_served: tuple
    execution_modes: tuple
    best_price_tie_break: str
    starter_identity: dict
    lineup_posting: dict
    registry_fingerprint: str
    code_commit: object
    store_fingerprints: dict
    exclusions: dict
    phase0_expected_universe: int
    universe_reconciliation: str
    evidence: str

    @classmethod
    def build(cls, *, seasons, games, games_by_season, exclusions,
              registry=DEFAULT_REGISTRY, code_commit=None, injected=False,
              out_dir=None, store=None, source_label=None) -> "ReplayManifest":
        if injected:
            fingerprints = {"__injected__": {
                "note": source_label or (
                    "stores were injected in process; no store file was read. "
                    "A fixture run is not a store run and must not be "
                    "reported as one")}}
        else:
            fingerprints = store_fingerprints(seasons, out_dir=out_dir,
                                              store=store)
        return cls(
            engine_version=ENGINE_VERSION,
            seasons=tuple(seasons),
            universe_size=len(games),
            games_by_season=dict(sorted(games_by_season.items())),
            point_classes=point_class_definitions(),
            markets_served=tuple(MARKETS_SERVED),
            execution_modes=tuple(EXECUTION_MODES),
            best_price_tie_break=BEST_PRICE_TIE_BREAK,
            starter_identity=STARTER_IDENTITY.to_dict(),
            lineup_posting=LINEUP_POSTING.to_dict(),
            registry_fingerprint=registry.fingerprint(),
            code_commit=code_commit if code_commit is not None
            else _git_commit(),
            store_fingerprints=fingerprints,
            exclusions=dict(sorted(exclusions.items())),
            phase0_expected_universe=PHASE0_UNIVERSE,
            universe_reconciliation=UNIVERSE_RECONCILIATION,
            evidence=EVIDENCE_LABEL,
        )

    def to_dict(self) -> dict:
        return {
            "engine_version": self.engine_version,
            "seasons": list(self.seasons),
            "universe_size": self.universe_size,
            "games_by_season": {str(k): v
                                for k, v in sorted(self.games_by_season.items())},
            "point_classes": self.point_classes,
            "markets_served": list(self.markets_served),
            "execution_modes": list(self.execution_modes),
            "best_price_tie_break": self.best_price_tie_break,
            "starter_identity": self.starter_identity,
            "lineup_posting": self.lineup_posting,
            "registry_fingerprint": self.registry_fingerprint,
            "code_commit": self.code_commit,
            "store_fingerprints": self.store_fingerprints,
            "exclusions": self.exclusions,
            "phase0_expected_universe": self.phase0_expected_universe,
            "universe_reconciliation": self.universe_reconciliation,
            "evidence": self.evidence,
        }

    def fingerprint(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.to_dict()).encode("utf-8")).hexdigest()

    def stamp(self, artifact) -> dict:
        """Return `artifact` with this manifest attached, or raise.

        A copy, not a mutation: the caller's dict is theirs. Refusing to
        overwrite an existing `replay_manifest` is the point -- two provenances
        on one artifact means neither can be trusted.
        """
        if not isinstance(artifact, dict):
            raise ReplayError("an artifact must be a dict to be stamped")
        if "replay_manifest" in artifact:
            raise ReplayError(
                "this artifact already carries a replay_manifest; stamping a "
                "second one would leave its numbers attributable to neither")
        out = dict(artifact)
        out["replay_manifest"] = self.to_dict()
        out.setdefault("evidence", EVIDENCE_LABEL)
        return out


# What the engine actually serves against Phase 0's measured 4,819, stated
# rather than reconciled away. The join itself reproduces 4,819 exactly
# (4,859 matrix rows less 40 with no joinable price path); the engine then
# serves 4,815 because four games' only quotes are stamped at or after the
# SCHEDULE's first pitch, which the odds feed's own revised commence_time did
# not exclude. Four games lost to a stricter pre-game rule is the right
# trade; hiding the difference would not be.
UNIVERSE_RECONCILIATION = (
    "Phase 0 measured 4,819 games (matrix row AND usable odds). This engine "
    "serves 4,815: the same join, then four games dropped because every quote "
    "they carry is stamped at or after the schedule's first pitch. The odds "
    "feed revises commence_time between snapshots, so pricepath's own "
    "pre-game filter can pass a quote that postdates the scheduled start; the "
    "engine filters against the schedule instead. See the exclusions block "
    "for the exact counts.")

BEST_PRICE_TIE_BREAK = (
    "Best price is the maximum DECIMAL payout on the board (never the maximum "
    "American integer: +100 and -100 are the same price and max prefers the "
    "positive one). When two or more books share that maximum the PRICE is "
    "used and the BOOK is reported as None, with every tied book listed in "
    "tied_books. The engine never names one of them as the best book: "
    "62.7% (2023) / 78.6% (2024) of instants carry a tie, so naming a winner "
    "would manufacture 'this book was reliably best' out of alphabetical "
    "order in the majority of cases. Deterministic because a max over floats "
    "is order-invariant and the tied list is sorted.")


def point_class_definitions() -> dict:
    """The pre-registered ladder, as it is actually served.

    Written into the manifest rather than only into the docs, because a point
    class is a definition a reader needs beside the number and the design's
    original four-rung ladder is not what the data supports.
    """
    return {
        EARLY_BOARD: {
            "definition": ("the latest observation at least "
                           f"{int(EARLY_BOARD_MIN_GAP_MINUTES)} minutes before "
                           "first pitch"),
            "min_gap_minutes": EARLY_BOARD_MIN_GAP_MINUTES,
        },
        LATE_BOARD: {
            "definition": ("the last observation before first pitch. NOT a "
                           "close: median 85 minutes out, and every decision "
                           "point carries its own gap_minutes"),
            "min_gap_minutes": 0.0,
        },
        "amended_from_design": (
            "docs/EVOLAB_DESIGN.md section 2 proposed T_MINUS_24H / "
            "T_MINUS_6H / LINEUP_POSTED / T_MINUS_30M. Phase 0 measured 3 "
            "snapshots a day, no two observations closer than 177 minutes, "
            "T_MINUS_30M present for 1,269 of 4,819 games and no lineup "
            "posting timestamps at all, so the ladder collapses to these two "
            "classes and the finer rungs are not served."),
        "collapse_rule": ("when the early and late boards are the same "
                          "instant only LATE_BOARD is emitted, so no board is "
                          "scored twice"),
    }
