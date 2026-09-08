"""The published slip: which of a day's plays reach a customer, in what order.

WHY THIS IS A SEPARATE LEDGER AND NOT A FIELD ON THE DECISION
--------------------------------------------------------------
`run_slate` writes decisions game by game. A day-level rank is not knowable
inside that loop -- where a selection ranks depends on every other game on the
slate -- so a rank cannot honestly be stamped on a `DecisionRecord` at the
instant it is written.

More importantly the slip has to be FROZEN rather than re-derived. Re-deriving
yesterday's slip under today's ranker is exactly the re-ranking of graded
history that docs/PRODUCT_DOCTRINE.md amendment 8 forbids: it would let a new
ranker manufacture a better-looking record without making a single better
pick. So the slip is persisted, and once persisted it is the sole authority on
rank, cohort and agreement. `DecisionRecord` deliberately carries none of
those (see the comment where they are refused, and the test that pins it).

SEVERAL SLIPS PER DATE IS EXPECTED, NOT A BUG
----------------------------------------------
The slate runs on a cadence as lineups post, so a 15:00Z slip and a 22:00Z
slip for one date legitimately differ -- the later one saw lineups the earlier
one could not. Each is immutable and carries its own `slip_utc`. This is the
same shape `scripts/afternoon_slate.sh` already documents for decisions: two
frozen sets for one date is the design, and anything reading this ledger must
treat `slip_utc` as part of a slip's identity.

WHAT THE RANK IS, AND EMPHATICALLY IS NOT
-------------------------------------------
The ranking basis is CASE STRENGTH: how many independent families backed the
selection, how much of the genome's own claim actually fired, and how deep and
fresh the board was. Price standing enters LAST and only as a tiebreak.

That ordering is deliberate and is a correction of the older
`slate.DAY_RANKING_RULE`, which ranked on price standing alone. Price standing
is execution quality -- the consensus is computed FROM the same prices, so
their difference can never be evidence the market is wrong -- and ranking a
picks slip on it ranks how little margin the bettor pays, not how strong the
case is. It is kept as the final tiebreak because, between two selections with
identical cases, taking the better number is strictly better.

Nothing here is a probability, an edge, an expected value or a confidence. No
number in this module is independent of the market it is quoted against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional, Sequence

from src.analysis import families as families_mod
from src.analysis.prices import MIN_BOOKS
from src.engine.slate import price_standing_bps
from src.ledger.chain import HashChainLedger
from src.ledger.records import (
    COHORT_IMPLIES,
    COHORT_PUBLISHED,
    COHORT_TOP_3,
    COHORT_TOP_5,
)

# ---------------------------------------------------------------------------
# The pre-registered rule
# ---------------------------------------------------------------------------

# THE EPOCH STAMP (doctrine amendment 8). Every slip row carries this string.
# A change to the ranking basis, to the evidence floors, or to the cohort cuts
# is a NEW VERSION and therefore a new epoch: slips already written keep the
# rule they were ranked under, and comparing two rankers means comparing
# forward epochs rather than re-scoring history under the newer one.
#
# Bump this and nothing else in the same commit. A silent change to the basis
# under an unchanged rule id is the one edit that would make every slip on the
# ledger uninterpretable.
SLIP_RULE = "DAY_SLIP_BY_FAMILY_AGREEMENT_V1"

# The cohort cuts are PART OF THE RULE, frozen here rather than passed in.
# A cut a caller can pass is a cut that can be chosen after the results are
# known, which is the move that turns "let the evidence determine the cutoff"
# into "report whichever cut won".
COHORT_CUTS: Mapping[str, int] = {COHORT_TOP_3: 3, COHORT_TOP_5: 5}

SLIP_BASIS = (
    "case strength: distinct families backing the selection (a family "
    "contributes at most one, so near-duplicate systems cannot manufacture "
    "agreement), then how much of the genome's own mechanism claim fired and "
    "at what threshold rung, then board depth and freshness, then price "
    "standing as the final tiebreak. Price standing is execution quality and "
    "never predictive merit: the consensus is derived from the same prices, "
    "so their difference can never be evidence the market is wrong."
)

# ---------------------------------------------------------------------------
# The evidence threshold
# ---------------------------------------------------------------------------
#
# DELIBERATELY MADE OF FLOORS THIS PROJECT ALREADY PRE-REGISTERED ELSEWHERE.
# Inventing a fresh numeric bar here -- "publish when at least two families
# agree", say -- would be choosing a threshold with the candidate list already
# in view, and a threshold picked to produce a target number of picks is the
# purest form of the thing this project's whole research discipline exists to
# resist. Every floor below is a bar the codebase already applies for its own
# stated reasons:
#
#   - the engine's own verdict must be `play`. A refusal is not a pick, and
#     publishing one would misrepresent standing down as choosing.
#   - the selection must be FORWARD_TEST. A CONTROL playing is meaningless by
#     construction and a MARKET_REFERENCE system playing is the board agreeing
#     with itself (src/report/engine_bridge.py says exactly this about engine
#     interest; a published pick is that claim with money next to it).
#   - the board must carry a price and clear `prices.MIN_BOOKS`. Below that
#     floor a consensus is "that handful's opinion, not a market's".
#   - the record must carry at least one mechanism predicate: a falsifiable,
#     machine-checkable claim frozen with the pick. Without one the pick can
#     never be graded REFUTED vs VARIANCE, so the learning loop can never
#     learn from it, and a pick nothing could ever contradict is not a thesis.
#
# Selectivity therefore EMERGES (doctrine amendment 6). On a night when
# nothing clears these floors the slip is empty, and that is a measurement
# rather than a posture -- `Slip.misses` names every candidate that failed and
# which floor it failed, so the page can say what it would have taken.
MIN_MECHANISM_PREDICATES = 1

MISS_NOT_A_PLAY = "not_a_play"
MISS_NOT_FORWARD_TEST = "not_forward_test"
MISS_NO_PRICE = "no_price"
MISS_THIN_BOARD = "thin_board"
MISS_NO_FALSIFIABLE_MECHANISM = "no_falsifiable_mechanism"

CONTROL_PREFIX = "trivial_"
MARKET_REFERENCE_PREFIX = "market_derived_consensus_"


class SlipError(ValueError):
    """A slip could not be built honestly."""


def is_forward_test(system_id: Optional[str]) -> bool:
    """The same prefix rule `src/report/engine_bridge.py` uses, restated here
    against the one place it is defined rather than re-derived: an unset or
    unknown system id is NEVER treated as a null baseline or as the market."""
    sid = system_id or ""
    return not (sid.startswith(CONTROL_PREFIX)
                or sid.startswith(MARKET_REFERENCE_PREFIX))


def _field(row, name, default=None):
    """Read a field off either a DecisionRecord or a raw ledger dict."""
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


# ---------------------------------------------------------------------------
# Confirmation strength
# ---------------------------------------------------------------------------

def confirmation_strength(record) -> tuple:
    """`(n_signals_fired, deepest_threshold_rung)` for one record.

    Read off `mechanism_predicates`, which the engine froze WITH the pick:
    one predicate per fired signal, each naming the feature and the
    `threshold_index` rung (0 = the p50 ladder rung, 2 = p90) it crossed. That
    is a structured, frozen fact.

    The obvious alternative -- parsing `score=2.0` out of the `evidence`
    strings -- is refused: a rank that depends on the format of a human-facing
    string breaks silently the first time that string is reworded, and it
    would read the genome's `score`, which is explicitly not a measure of
    merit.

    A record with no predicates returns `(0, -1)`. It cannot reach the slip
    anyway (MIN_MECHANISM_PREDICATES), and -1 sorts below rung 0 rather than
    tying with it.
    """
    preds = _field(record, "mechanism_predicates") or ()
    if not preds:
        return (0, -1)
    rungs = [p.get("threshold_index") if isinstance(p, Mapping)
             else getattr(p, "threshold_index", None) for p in preds]
    numeric = [r for r in rungs if isinstance(r, int)
               and not isinstance(r, bool)]
    return (len(preds), max(numeric) if numeric else -1)


def board_quality(record) -> tuple:
    """`(books_at_decision, -staleness_seconds)` -- deeper and fresher first.

    Staleness is negated so a single `reverse`-free sort key orders both the
    same way. A record with no friction block reports zero books, which sorts
    last; it cannot reach the slip anyway.
    """
    friction = _field(record, "friction") or {}
    books = _field(record, "books_at_decision") or friction.get("book_count") or 0
    staleness = friction.get("staleness_seconds")
    return (int(books), -(int(staleness) if isinstance(staleness, (int, float))
                          else 0))


# ---------------------------------------------------------------------------
# Candidates and misses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Miss:
    """One selection that did not reach the slip, and the floor it failed.

    Named rather than dropped. A candidate that silently never appears is
    indistinguishable from one that was never considered, and on an empty
    night that ambiguity is the difference between "we checked and nothing
    qualified" and "the pipeline broke".
    """

    wager_id: str
    system_id: str
    reason: str
    detail: str = ""

    def to_dict(self) -> dict:
        return {"wager_id": self.wager_id, "system_id": self.system_id,
                "reason": self.reason, "detail": self.detail}


@dataclass(frozen=True)
class SlipPick:
    """One published pick, at its frozen rank, with the basis inspectable.

    Every number a reader would need to check the rank themselves is carried
    here. A rank whose basis has to be taken on faith is a rank that cannot be
    audited, and the audit is the product.
    """

    rank: int
    cohorts: tuple
    event_id: str
    market_key: str
    selection_id: str
    line: Optional[str]
    book: Optional[str]
    price_american: Optional[int]
    system_ids: tuple
    n_families: int
    n_systems: int
    n_signals: int
    deepest_rung: int
    books_at_decision: int
    price_standing_bps: Optional[int]
    thesis: Optional[str]
    counterarguments: tuple
    agreement: Mapping
    decision_utc: Optional[str]

    @property
    def wager_id(self) -> str:
        return families_mod.wager_id(
            self.event_id, self.market_key, self.selection_id)

    def to_dict(self) -> dict:
        return {
            "rank": self.rank,
            "cohorts": list(self.cohorts),
            "wager_id": self.wager_id,
            "event_id": self.event_id,
            "market_key": self.market_key,
            "selection_id": self.selection_id,
            "line": self.line,
            "book": self.book,
            "price_american": self.price_american,
            "system_ids": list(self.system_ids),
            "n_families": self.n_families,
            "n_systems": self.n_systems,
            "n_signals": self.n_signals,
            "deepest_rung": self.deepest_rung,
            "books_at_decision": self.books_at_decision,
            "price_standing_bps": self.price_standing_bps,
            "thesis": self.thesis,
            "counterarguments": list(self.counterarguments),
            "agreement": dict(self.agreement),
            "decision_utc": self.decision_utc,
        }


@dataclass(frozen=True)
class Slip:
    """One date's published slip, frozen at one instant."""

    date: str
    slip_utc: str
    rule: str
    basis: str
    cohort_cuts: Mapping[str, int]
    picks: tuple = ()
    misses: tuple = ()
    # Control and market-reference plays seen while building this slip.
    # Counted rather than listed (see build_slip): they were never candidates,
    # and listing hundreds of them would bury the genuine near-misses. Carried
    # so the number is still stated -- a reader can see the slate was busy
    # even on a night the slip is empty.
    n_instrument_plays: int = 0

    def cohort(self, tag: str) -> tuple:
        """The picks in one cohort. A FILTER over the frozen list, never an
        arithmetic reassignment -- which is why cohorts nest."""
        return tuple(p for p in self.picks if tag in p.cohorts)

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "slip_utc": self.slip_utc,
            "rule": self.rule,
            "basis": self.basis,
            "cohort_cuts": dict(self.cohort_cuts),
            "picks": [p.to_dict() for p in self.picks],
            "misses": [m.to_dict() for m in self.misses],
            "n_picks": len(self.picks),
            "n_misses": len(self.misses),
            "n_instrument_plays": self.n_instrument_plays,
        }


def cohorts_for_rank(rank: int) -> tuple:
    """The frozen cohort tags for a 1-based rank, nested outward.

    Built from `COHORT_CUTS` and then closed under `COHORT_IMPLIES`, so a tag
    can never be present without the tags it implies. Ordered outermost-first
    so the rendered tuple reads the way the cohorts nest.
    """
    tags = {COHORT_PUBLISHED}
    for tag, cut in COHORT_CUTS.items():
        if rank <= cut:
            tags.add(tag)
    for tag in tuple(tags):
        tags.update(COHORT_IMPLIES.get(tag, ()))
    order = [COHORT_PUBLISHED, COHORT_TOP_5, COHORT_TOP_3]
    return tuple(t for t in order if t in tags)


def _rank_key(entry) -> tuple:
    """Deterministic total order under `SLIP_BASIS`. No tie is ever broken by
    chance or by iteration order -- the last two terms are identifiers purely
    so the same slate produces the same slip on any machine."""
    agreement, record, standing = entry
    n_signals, rung = confirmation_strength(record)
    books, fresh = board_quality(record)
    return (
        -agreement.n_families,       # case strength: independent sources
        -n_signals,                  # how much of the claim fired
        -rung,                       # and at what threshold rung
        -books,                      # board depth
        -fresh,                      # board freshness
        0 if standing is not None else 1,
        -(standing if standing is not None else 0),   # execution quality, LAST
        _field(record, "selection_id") or "",
        _field(record, "event_id") or "",
    )


def build_slip(records: Iterable, clustering, *, date: str, slip_utc: str,
               systems: Optional[Sequence[str]] = None) -> Slip:
    """Rank one date's plays into a frozen slip.

    `records` are that date's decision records (any verdict, any class -- the
    floors below do the filtering, and every rejection is named in `misses` so
    an empty slip can be told apart from a broken pipeline). `clustering` is a
    `families.FamilyClustering` over the FORWARD_TEST population; it is
    required and has no default, because an agreement count computed without
    one would silently be a raw system count, which is the exact number
    doctrine amendment 9 exists to stop being reported.

    `slip_utc` is passed in rather than read from a clock so this function
    stays pure and reproducible: the same records and instant always produce
    the same slip.
    """
    if clustering is None:
        raise SlipError(
            "build_slip requires a family clustering -- without one the "
            "agreement count silently degrades to a raw system count, which "
            "is the number the family discount exists to replace")
    # A clustering built WITHOUT genomes runs only the behavioural relation,
    # and that is not a smaller version of the right answer -- it is biased in
    # the one direction that matters. On this population it finds 15 families
    # where both relations find 11, because every F5 genome is a feature-set
    # twin of an h2h genome. Understating collapse overstates agreement, which
    # is precisely the manufactured confidence amendment 9 exists to prevent,
    # so a structure-blind clustering is refused rather than quietly used.
    # (Caught here because it was shipped once: the CLI omitted `genomes=` and
    # the slip reported 15 families for a night with no structural twins both
    # firing, so nothing looked wrong.)
    bases = set((clustering.basis_of or {}).values())
    if bases and not (bases & {families_mod.BASIS_BEHAVIOURAL_AND_STRUCTURAL,
                               families_mod.BASIS_STRUCTURAL_ONLY}):
        raise SlipError(
            "this family clustering was built without genome structure, so "
            "only the behavioural relation ran. Structurally identical "
            "genomes would be counted as independent agreement. Pass "
            "genomes= to families()")

    rows = list(records or ())
    misses: list = []
    eligible: dict = {}
    n_instrument_plays = 0

    for record in rows:
        system_id = _field(record, "system_id") or ""
        wid = families_mod.wager_id(_field(record, "event_id"),
                                    _field(record, "market_key"),
                                    _field(record, "selection_id"))
        if _field(record, "verdict") != "play":
            # Not a miss worth naming: a refusal is a different kind of
            # answer, already recorded on the decision with its own reason.
            continue
        if not is_forward_test(system_id):
            # Counted, not listed. A control or market-reference system was
            # never a candidate for publication -- it is a different
            # population, not a pick that fell short -- so naming each one
            # would bury the handful of genuine near-misses under hundreds of
            # rows that were never eligible. `misses` has to stay readable,
            # because its job is to answer "what would it have taken
            # tonight?" on an empty night.
            n_instrument_plays += 1
            continue
        if _field(record, "price_american") is None:
            misses.append(Miss(wid, system_id, MISS_NO_PRICE,
                               "no price on the board at decision time"))
            continue
        books, _fresh = board_quality(record)
        if books < MIN_BOOKS:
            misses.append(Miss(
                wid, system_id, MISS_THIN_BOARD,
                f"{books} book(s) at decision, floor is {MIN_BOOKS}"))
            continue
        n_signals, _rung = confirmation_strength(record)
        if n_signals < MIN_MECHANISM_PREDICATES:
            misses.append(Miss(
                wid, system_id, MISS_NO_FALSIFIABLE_MECHANISM,
                "no mechanism predicate frozen with the pick, so no game "
                "could ever refute it"))
            continue
        # Several capture instants can decide the same wager. Keep the one
        # that stands the deepest, so the published price is the best the
        # system actually committed to -- never a blend, which would be a
        # price nobody was ever offered.
        prior = eligible.get(wid)
        standing = price_standing_bps(record) if not isinstance(
            record, Mapping) else _standing_from_row(record)
        if prior is None or _better_standing(standing, prior[1]):
            eligible[wid] = (record, standing)

    picks: list = []
    ranked_input = []
    for wid, (record, standing) in eligible.items():
        group = [r for r in rows
                 if families_mod.wager_id(
                     _field(r, "event_id"), _field(r, "market_key"),
                     _field(r, "selection_id")) == wid
                 and _field(r, "verdict") == "play"
                 and is_forward_test(_field(r, "system_id"))]
        ag = families_mod.agreement(group, clustering)
        ranked_input.append((ag, record, standing))

    ranked_input.sort(key=_rank_key)
    for i, (ag, record, standing) in enumerate(ranked_input, start=1):
        n_signals, rung = confirmation_strength(record)
        books, _ = board_quality(record)
        picks.append(SlipPick(
            rank=i,
            cohorts=cohorts_for_rank(i),
            event_id=_field(record, "event_id"),
            market_key=_field(record, "market_key"),
            selection_id=_field(record, "selection_id"),
            line=_field(record, "line"),
            book=_field(record, "book"),
            price_american=_field(record, "price_american"),
            system_ids=tuple(ag.systems),
            n_families=ag.n_families,
            n_systems=ag.n_systems,
            n_signals=n_signals,
            deepest_rung=rung,
            books_at_decision=books,
            price_standing_bps=standing,
            thesis=_field(record, "thesis"),
            counterarguments=tuple(_field(record, "counterarguments") or ()),
            agreement=ag.to_dict(),
            decision_utc=_field(record, "decision_utc"),
        ))

    return Slip(date=date, slip_utc=slip_utc, rule=SLIP_RULE, basis=SLIP_BASIS,
                cohort_cuts=dict(COHORT_CUTS), picks=tuple(picks),
                misses=tuple(misses), n_instrument_plays=n_instrument_plays)


def _standing_from_row(row: Mapping) -> Optional[int]:
    """Price standing from a raw ledger dict, through the SAME arithmetic
    `slate.price_standing_bps` applies to a record -- imported, never
    reimplemented, so the two can never drift apart."""
    from src.core import odds as odds_math
    consensus = row.get("consensus_fair")
    price = row.get("price_american")
    if consensus is None or price is None:
        return None
    return int(round((consensus - odds_math.american_to_probability(price))
                     * 10_000))


def _better_standing(candidate: Optional[int], incumbent: Optional[int]) -> bool:
    """A real standing always beats an absent one; between two real ones the
    higher wins. Absence never wins by defaulting to zero -- zero is a real,
    middling standing."""
    if candidate is None:
        return False
    if incumbent is None:
        return True
    return candidate > incumbent


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------

DEFAULT_SLIP_PATH = "evidence/slips_v1.jsonl"


def append_slip(slip: Slip, path: str = DEFAULT_SLIP_PATH) -> dict:
    """Append one frozen slip to the hash-chained slip ledger.

    Append-only, like every other ledger here. A slip is never edited and
    never recomputed in place: a later slate pass writes a NEW slip for the
    same date, and both stand.
    """
    return HashChainLedger(path).append(slip.to_dict())


def read_slips(path: str = DEFAULT_SLIP_PATH) -> list:
    """Every slip on the ledger, oldest first. Missing file reads empty --
    a ledger that has not been started is a normal state, not an error."""
    return HashChainLedger(path).read()


def latest_slip_for(date: str, path: str = DEFAULT_SLIP_PATH) -> Optional[dict]:
    """The most recent slip written for one date, or None.

    "Most recent" is by position in the append-only chain, not by comparing
    `slip_utc` strings: the chain's order is the order things actually
    happened, and a clock disagreement must never be able to reorder history.
    """
    found = None
    for row in read_slips(path):
        if row.get("date") == date and row.get("rule"):
            found = row
    return found
