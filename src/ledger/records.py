"""DecisionRecord, ReviewRecord, Scorecard -- frozen per synthesis-judge.md 4.2.

Field names are verbatim against `docs/planning/synthesis-judge.md` section
4.2 ("Records written" / "Scoring"). Do not rename, reorder, add, or drop a
field here without updating that document first -- the contract is frozen and
this module is its implementation, not the other way around.

THE TWO-LEDGER RULE, AS A TYPE
-------------------------------
synthesis-judge.md 4.2 / ARCHITECTURE_BETTING_ENGINE.md F9: `objective()` must
take a view that "structurally lacks money fields" -- an `ObjectiveView`, not
a `Scorecard`. A `Scorecard` carries `account` (money: bankroll, units, ROI);
an `ObjectiveView` is what `objective()` is actually allowed to see, and its
constructor raises the moment any forbidden field would be smuggled in --
whether directly, or nested inside an arbitrary extra mapping. This is the
second line of enforcement described in F9; the first line is the AST test
over `objective()` itself (tests/test_ledger_records.py), which this module
does not implement because a type cannot stop a *hardcoded literal* the way
an AST walk can.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Mapping

# -- shared vocabulary --------------------------------------------------

KNOWN_AT_GRADES = frozenset("ABCD")

VERDICTS = frozenset({
    "play", "no_play", "market_unavailable",
    "refused_stale", "refused_thin", "refused_grade",
    "refused_sample", "refused_regime", "refused_friction",
})

# B1 (slice-review-2026-09-03): `DecisionRecord.record_provenance` names WHEN
# a record was written relative to the game it decides -- the thing
# `recorded_utc` alone cannot say on its own, since a caller could set
# `recorded_utc` honestly to the write instant and STILL leave a reader
# unable to tell "written before first pitch on a live slate" apart from
# "written after first pitch" apart from "written in a deliberate
# replay/backfill of an already-past date". Three values, one per case:
#   live_pre_commencement  -- a live slate wrote this before the game's own
#                              first pitch (the genuinely pre-commitment
#                              case).
#   live_post_commencement -- a live slate wrote this AFTER the game's own
#                              first pitch had already passed at write time.
#                              `src.engine.slate.run_slate` refuses to stake
#                              a game in this state going forward (B2) --
#                              this value exists so an already-published row
#                              from before that guard existed (or a
#                              corrective row appended to explain one) can
#                              still be labelled honestly rather than
#                              erased.
#   replay                 -- a deliberate replay/backfill of an
#                              already-past date (`run_slate --date` for a
#                              date strictly before the wall-clock date it
#                              was run on). The game has necessarily already
#                              been played; that is expected and honest for
#                              a replay, unlike the live case above.
RECORD_PROVENANCE_LIVE_PRE_COMMENCEMENT = "live_pre_commencement"
RECORD_PROVENANCE_LIVE_POST_COMMENCEMENT = "live_post_commencement"
RECORD_PROVENANCE_REPLAY = "replay"

RECORD_PROVENANCE_VALUES = frozenset({
    RECORD_PROVENANCE_LIVE_PRE_COMMENCEMENT,
    RECORD_PROVENANCE_LIVE_POST_COMMENCEMENT,
    RECORD_PROVENANCE_REPLAY,
})

# F9 / the Two-Ledger Rule: these names may never appear on anything
# `objective()` is allowed to read. Kept here (not only in the AST test) so
# ObjectiveView and the test import the SAME list rather than two lists that
# can drift apart.
FORBIDDEN_OBJECTIVE_FIELDS = frozenset({
    "account", "bankroll", "units", "drawdown", "roi_units", "profit_units",
})


class RecordContractError(ValueError):
    """A ledger v2 record violated its frozen contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RecordContractError(message)


# -- PriceObservation identity, carried on DecisionRecord ------------------
#
# The task names these verbatim as MARKET/SELECTION/LINE/PRICE/BOOK/TIMESTAMP
# -- the human-readable identity fields of a priced quote. They map onto the
# frozen synthesis-4.2 DecisionRecord field names one-for-one:
#
#   MARKET    -> market_key
#   SELECTION -> selection_id
#   LINE      -> line
#   PRICE     -> price_american
#   BOOK      -> book
#   TIMESTAMP -> decision_utc  (the instant the decision, and its price
#                                observation, are pinned to)
#
# PRICE_OBSERVATION_IDENTITY_FIELDS below is the DecisionRecord-side name for
# that mapping, so a test can assert the six identity fields are present
# without hardcoding the mapping in two places.
PRICE_OBSERVATION_IDENTITY_FIELDS: Mapping[str, str] = {
    "MARKET": "market_key",
    "SELECTION": "selection_id",
    "LINE": "line",
    "PRICE": "price_american",
    "BOOK": "book",
    "TIMESTAMP": "decision_utc",
}


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """One system's decision about one game at one instant. Frozen per 4.2.

    Every field below is named exactly as synthesis-judge.md 4.2 names it.
    `known_at_grade` (task requirement, alongside the PriceObservation
    identity fields) records the knowability grade of the information the
    decision was made on -- distinct from any grade on the priced quote
    itself, because a decision can be graded A on its inputs while its price
    is graded differently, and the two must never be conflated.
    """

    engine_version: str
    system_id: str
    system_version: str
    registry_fingerprint: str
    frame_fingerprint: str | None
    snapshot_fingerprint: str
    game_pk: int | None
    event_id: str
    decision_utc: str
    point_class: str
    information_time: str
    recorded_utc: str
    verdict: str
    selection_id: str | None
    market_key: str | None
    line: str | None
    book: str | None
    price_american: int | None
    consensus_fair: float | None
    books_at_decision: int | None
    friction: dict | None
    p_model: float | None
    p_model_interval: tuple | None
    edge_bps: int | None
    price_improvement_bps: int | None
    rating: dict | None
    thesis: str | None
    evidence: list
    counterarguments: list
    supporting_systems: list
    refusal_reason: str | None
    assumption_exposure: dict
    stake_units: float
    known_at_grade: str  # task requirement: carried alongside the identity fields
    # vertical-slice S5/honest-probabilities task additions (both optional,
    # default None so every pre-existing construction site keeps working):
    #   value_basis    -- REQUIRED non-None on any record whose proposal
    #                      carried no p_model: names what the selection
    #                      rested on when there is no calibrated probability
    #                      to project a value against (src.engine.analyze's
    #                      VALUE_BASIS_PRICE_STANDING_ONLY). None for a
    #                      record whose p_model IS set -- that record's
    #                      value basis is already the edge_bps/p_model pair,
    #                      which is the "existing value projection" the task
    #                      distinguishes this from.
    #   selection_rule -- the named, pre-registered constant
    #                      (src.engine.slate.SELECTION_RULE) recording HOW a
    #                      slate runner turned this record into a paper
    #                      wager (or chose not to) -- set by the slate
    #                      runner, never by analyze() itself, which knows
    #                      nothing about staking.
    #
    # B1 (slice-review-2026-09-03) addition, same convention -- optional,
    # default None so every pre-existing construction site keeps working:
    #   record_provenance -- WHEN this record was written relative to the
    #                      game it decides, distinct from `decision_utc`
    #                      (the information instant) and `recorded_utc` (the
    #                      wall-clock write instant): one of
    #                      RECORD_PROVENANCE_VALUES below. `analyze()` is
    #                      pure and never sets this on its own (it has no
    #                      clock and no notion of live-vs-replay); a caller
    #                      may pass one in explicitly (still pure -- it is
    #                      an argument, not a clock read), and the caller
    #                      that actually writes to the ledger
    #                      (`src.engine.slate.run_slate`) always does. A
    #                      record with `record_provenance is None` predates
    #                      this field (every one of the 69 rows published
    #                      before this fix) and carries no evidence either
    #                      way -- it must never be read as "pre-commitment
    #                      confirmed".
    value_basis: str | None = None
    selection_rule: str | None = None
    record_provenance: str | None = None
    prev_hash: str = ""
    row_hash: str = ""

    def __post_init__(self) -> None:
        _require(self.verdict in VERDICTS,
                  f"verdict={self.verdict!r} must be one of {sorted(VERDICTS)}")
        _require(self.known_at_grade in KNOWN_AT_GRADES,
                  f"known_at_grade={self.known_at_grade!r} must be one of "
                  f"{sorted(KNOWN_AT_GRADES)}")
        _require(
            self.record_provenance is None
            or self.record_provenance in RECORD_PROVENANCE_VALUES,
            f"record_provenance={self.record_provenance!r} must be None or "
            f"one of {sorted(RECORD_PROVENANCE_VALUES)}"
        )
        if self.verdict == "play":
            _require(self.price_american is not None,
                      "price_american is REQUIRED on a play (synthesis 4.2)")
            _require(bool(self.counterarguments) or self.evidence,
                      "evidence/counterarguments are REQUIRED on a play "
                      "(synthesis 4.2: 'non-empty REQUIRED on a play')")
        if self.line is not None:
            _require(isinstance(self.line, str),
                      "line must be a decimal string or None, never a float "
                      "(src/board/ids.py discipline)")
        if self.edge_bps is not None and self.price_improvement_bps is not None:
            _require(
                self.edge_bps != self.price_improvement_bps
                or self.edge_bps == 0,
                "edge_bps (p_model - fair) and price_improvement_bps are "
                "separate columns with separate meanings and must not be "
                "silently assigned the same computed value"
            )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReviewRecord:
    """The computed review of one settled decision. Frozen per 4.2.

    `thesis_outcome` is COMPUTED from `mechanism_checks`, never written
    directly by a caller with a free-text opinion -- see `compute_thesis_outcome`.
    """

    decision_key: tuple
    review_utc: str
    settled: str  # win|loss|push|void|unsettled
    thesis_outcome: str  # CONFIRMED|REFUTED|UNTESTED|VARIANCE -- COMPUTED
    mechanism_checks: tuple  # [{name, expected, observed, verdict}]
    market_path: dict
    late_information: tuple
    missed_information: tuple
    lineup_delta: dict
    bullpen_delta: dict
    counterargument_realized: tuple
    variance_flag: bool
    system_action: str  # none|watch|demote|retire
    new_hypothesis: str | None

    def __post_init__(self) -> None:
        _require(self.settled in {"win", "loss", "push", "void", "unsettled"},
                  f"settled={self.settled!r} is not a recognized outcome")
        _require(
            self.thesis_outcome in {"CONFIRMED", "REFUTED", "UNTESTED", "VARIANCE"},
            f"thesis_outcome={self.thesis_outcome!r} must be one of "
            "CONFIRMED|REFUTED|UNTESTED|VARIANCE"
        )
        _require(self.system_action in {"none", "watch", "demote", "retire"},
                  f"system_action={self.system_action!r} must be one of "
                  "none|watch|demote|retire")
        expected = compute_thesis_outcome(self.mechanism_checks, self.settled)
        _require(
            self.thesis_outcome == expected,
            f"thesis_outcome={self.thesis_outcome!r} does not match the "
            f"value computed from mechanism_checks ({expected!r}) -- "
            "thesis_outcome must be COMPUTED, never asserted freehand"
        )
        if self.thesis_outcome == "VARIANCE":
            _require(
                self.variance_flag,
                "VARIANCE is only assignable when mechanism checks confirmed "
                "and the outcome disagreed -- variance_flag must be True"
            )

    def to_dict(self) -> dict:
        return asdict(self)


def compute_thesis_outcome(mechanism_checks: tuple, settled: str) -> str:
    """Derive `thesis_outcome` from `mechanism_checks` -- never write it by hand.

    `mechanism_checks` is a sequence of {"name", "expected", "observed",
    "verdict"} mappings where `verdict` is "confirmed" or "refuted". Rules:

      - no checks at all                              -> UNTESTED
      - any check refuted                              -> REFUTED
      - all checks confirmed, settled == "win"         -> CONFIRMED
      - all checks confirmed, settled in {"loss","push"} -> VARIANCE
      - all checks confirmed, settled unsettled/void   -> UNTESTED
    """
    if not mechanism_checks:
        return "UNTESTED"
    verdicts = [c.get("verdict") for c in mechanism_checks]
    if any(v == "refuted" for v in verdicts):
        return "REFUTED"
    if not all(v == "confirmed" for v in verdicts):
        return "UNTESTED"
    if settled == "win":
        return "CONFIRMED"
    if settled in ("loss", "push"):
        return "VARIANCE"
    return "UNTESTED"


@dataclass(frozen=True, slots=True)
class AccountSummary:
    """Money, reported never optimized. Lives ONLY on Scorecard.account --
    never on ObjectiveView, which cannot express it at all (see below)."""

    bankroll: float
    units: float
    drawdown: float
    roi_units: float
    profit_units: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Scorecard:
    """Per (system, world, window, point_class, market) scoring row. Frozen per 4.2."""

    system_id: str
    world: str
    window: str
    point_class: str
    market_key: str
    n_decisions: int
    n_independent_clusters: int  # game-day blocks >= 7 days, REQUIRED
    logloss_vs_market: float
    brier: float
    reliability_bins: tuple
    realized_return: float
    realized_return_ci: tuple  # clustered bootstrap
    avg_odds_decimal: float
    clv_bps_mean: float  # advisory only
    stability: dict
    price_sensitivity: dict
    top5_win_share: float
    placebo_percentile: float
    cscv_pbo: float
    spa_p: float
    battery_verdict: str
    battery_rules_version: str
    effective_tests: int
    raw_tests: int
    total_searched_at_verdict: int
    account: AccountSummary  # REPORTED, never optimized

    def __post_init__(self) -> None:
        _require(self.n_independent_clusters >= 0,
                  "n_independent_clusters must be >= 0")
        _require(self.effective_tests <= self.raw_tests
                  or self.raw_tests == 0,
                  "effective_tests must never exceed raw_tests")
        _require(isinstance(self.account, AccountSummary),
                  "account must be an AccountSummary -- money lives here, "
                  "and only here")

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def objective_view(self) -> "ObjectiveView":
        """Project this Scorecard onto the money-blind view `objective()` may
        read. The only sanctioned path from a Scorecard to an ObjectiveView."""
        return ObjectiveView(
            system_id=self.system_id,
            world=self.world,
            window=self.window,
            point_class=self.point_class,
            market_key=self.market_key,
            n_decisions=self.n_decisions,
            n_independent_clusters=self.n_independent_clusters,
            logloss_vs_market=self.logloss_vs_market,
            brier=self.brier,
            reliability_bins=self.reliability_bins,
            avg_odds_decimal=self.avg_odds_decimal,
            clv_bps_mean=self.clv_bps_mean,
            stability=self.stability,
            price_sensitivity=self.price_sensitivity,
            top5_win_share=self.top5_win_share,
            placebo_percentile=self.placebo_percentile,
            cscv_pbo=self.cscv_pbo,
            spa_p=self.spa_p,
            battery_verdict=self.battery_verdict,
            battery_rules_version=self.battery_rules_version,
            effective_tests=self.effective_tests,
            raw_tests=self.raw_tests,
            total_searched_at_verdict=self.total_searched_at_verdict,
        )


def _scan_for_forbidden(value: Any, path: str) -> None:
    """Recursively refuse any of FORBIDDEN_OBJECTIVE_FIELDS, at any depth --
    directly, or smuggled inside a nested dict/list a caller hands in."""
    if isinstance(value, Mapping):
        for k, v in value.items():
            if k in FORBIDDEN_OBJECTIVE_FIELDS:
                raise RecordContractError(
                    f"ObjectiveView refuses to carry {k!r} at {path}.{k} -- "
                    "the Two-Ledger Rule forbids any money field on the "
                    "prediction-quality view"
                )
            _scan_for_forbidden(v, f"{path}.{k}")
    elif isinstance(value, (list, tuple, set, frozenset)):
        for i, v in enumerate(value):
            _scan_for_forbidden(v, f"{path}[{i}]")
    elif hasattr(value, "__dataclass_fields__"):
        _scan_for_forbidden(asdict(value), path)


@dataclass(frozen=True, slots=True)
class ObjectiveView:
    """The money-blind view `objective()` is allowed to read (F9 / Two-Ledger Rule).

    Structurally cannot carry `account`, `bankroll`, `units`, `drawdown`,
    `roi_units` or `profit_units` -- there is no field for them, and
    `__post_init__` additionally refuses construction if any extra field a
    caller supplies (via `extra=`) contains one of those names at any depth,
    so a Scorecard's `account` cannot be smuggled in through a side channel.
    This is the "structurally lacks money fields" half of F9; the AST test
    over `objective()` itself is the other half.
    """

    system_id: str
    world: str
    window: str
    point_class: str
    market_key: str
    n_decisions: int
    n_independent_clusters: int
    logloss_vs_market: float
    brier: float
    reliability_bins: tuple
    avg_odds_decimal: float
    clv_bps_mean: float
    stability: dict
    price_sensitivity: dict
    top5_win_share: float
    placebo_percentile: float
    cscv_pbo: float
    spa_p: float
    battery_verdict: str
    battery_rules_version: str
    effective_tests: int
    raw_tests: int
    total_searched_at_verdict: int
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Guard the type's own field names too -- a future edit that adds a
        # field literally named "units" must fail exactly as loudly as an
        # attempt to smuggle one through `extra`.
        for f in fields(self):
            if f.name in FORBIDDEN_OBJECTIVE_FIELDS:
                raise RecordContractError(
                    f"ObjectiveView must never declare a field named "
                    f"{f.name!r} -- Two-Ledger Rule"
                )
        _scan_for_forbidden(self.extra, "extra")

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def objective(view: ObjectiveView) -> float:
    """The single scalar the factory ranks on -- reads ONLY an ObjectiveView.

    Structurally cannot read money: `view` has no money field to read, and an
    AST test over this function's source (tests/test_ledger_records.py)
    additionally fails if any of FORBIDDEN_OBJECTIVE_FIELDS appears as a
    literal name anywhere in its body, so a hardcoded bypass ("just multiply
    by 100 units") is caught even though the type alone would not catch it.
    """
    return view.logloss_vs_market
