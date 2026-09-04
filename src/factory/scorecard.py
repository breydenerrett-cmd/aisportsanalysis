"""Assemble a real `Fitness` (src/factory/fitness.py) from what genuinely
exists today, and project it onto a `Scorecard` (src/ledger/records.py).

WHY THIS MODULE EXISTS
-----------------------
docs/planning/checkpoint-2026-09-03/C_factory_fitness.md Q8: `Fitness` and
`promotion_verdict` are real, well-tested, pure functions -- but nothing in
the repository has ever constructed a `Fitness` object outside a test. This
module is that missing assembly step. It does not compute anything on its
own authority: every number either comes straight out of a `SettledBet`
(src/accounts/paper.py), a `DecisionRecord`/`ReviewRecord`
(src/ledger/records.py), or an already-computed research artifact (the raw
output of src/research/battery.py's `run()`, or a pre-shaped summary of a
src/research/funnel.py family / src/evolab/{cscv,spa}.py population sweep --
those are population-wide computations this module has no business
repeating for one system).

THE ABSENT DISCIPLINE
----------------------
`Fitness`'s component dataclasses have no `Optional` slot for "we don't
know" -- every field is a concrete, range-checked value. So when an input
this module needs is missing, it does two things, always together, never
one without the other:

  1. Sets the field(s) that gate `promotion_verdict`'s positivity check
     (`_component_positive` in fitness.py) to a value that reads NEGATIVE --
     never a value that could pass by omission.
  2. Records an `AbsentComponent(field, reason)` in the returned
     `FitnessAssembly.absent` tuple, so "we never measured this" stays
     distinguishable from "we measured this and it failed" all the way to
     the EOD report.

Two numbers this module computes that have no field on `Fitness` at all --
CLV (kept distinct from `late_move`, src/pipeline/grading.py) and the
stdev-of-returns volatility this task adds for the first time -- are
reporting-only figures. They live on `RealizedStats` / `Scorecard.stability`
and NEVER gate `promotion_verdict`, matching `Scorecard.clv_bps_mean`'s own
"advisory only" label.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from src.accounts.paper import SettledBet
from src.board.settle import LOSS, PUSH, VOID, WIN
from src.core import odds as odds_math
from src.factory.fitness import (
    BankrollComponent,
    EconomicComponent,
    FalsificationComponent,
    Fitness,
    ForwardSurvivalComponent,
    MultiplicityComponent,
    PriceResilienceComponent,
    RobustnessComponent,
    SampleSufficiencyComponent,
)
from src.core import calibration as calibration_module
from src.ledger.records import (
    AccountSummary,
    DecisionRecord,
    PROBABILITY_PROVENANCE_MARKET_DERIVED,
    PROBABILITY_PROVENANCE_MODEL_DERIVED,
    ReviewRecord,
    Scorecard,
)

# Provenances whose p_model is an honest attempt at a calibrated probability
# -- `model_derived` (fitted, price-independent) and `market_derived` (the
# board's own de-vigged consensus, republished via the identity map,
# docs/PREREG_CALIBRATED_PROBABILITY.md §1-2: "already a well-calibrated
# forecast"). `placeholder` (a fixed null-control constant) and `none` (no
# probability at all) are excluded -- neither is a claim about calibration,
# so folding either in would manufacture a calibration score out of nothing.
_CALIBRATION_ELIGIBLE_PROVENANCE = frozenset({
    PROBABILITY_PROVENANCE_MODEL_DERIVED,
    PROBABILITY_PROVENANCE_MARKET_DERIVED,
})

# docs/PREREG_CALIBRATED_PROBABILITY.md §4: minimum sample before ANY
# calibration claim is published -- >=500 decision/review pairs AND >=9
# independent 7-day game-day clusters. Below either, report
# "INSUFFICIENT SAMPLE" and publish no calibration claim; do not shrink
# these to fit whatever sample happens to exist.
MIN_CALIBRATION_PAIRS = 500

# log-loss of an uninformative p=0.5 forecast -- the reference this module
# uses when there is no genuine calibration evidence to average. Never a
# computed result; only ever a documented "we know nothing" placeholder so
# `EconomicComponent.logloss_vs_market`'s `>= 0.0` invariant still holds.
NEUTRAL_LOGLOSS = math.log(2)
# Brier score of that same uninformative p=0.5 forecast: (0.5 - y)**2 = 0.25
# regardless of y. Same role as NEUTRAL_LOGLOSS, for Scorecard.brier.
NEUTRAL_BRIER = 0.25

# docs/planning/design-factory-first.md §10.4: every clustered bootstrap uses
# game-day blocks of >= 7 days (`DEFAULT_SPA_BLOCK_LENGTH` in
# src/evolab/sweep.py). n_independent_clusters counts how many such 7-day
# blocks of distinct decision-days exist -- never the raw decision count.
try:
    from src.evolab.sweep import DEFAULT_SPA_BLOCK_LENGTH
except Exception:  # pragma: no cover -- evolab is optional at import time
    DEFAULT_SPA_BLOCK_LENGTH = 7.0

# The default `required_clusters` is derived, not invented: G6
# (src/factory/gates.py `gate_g6_forward`) requires >=60 forward ledger days
# before a system may be considered for promotion; at one cluster per
# DEFAULT_SPA_BLOCK_LENGTH days that is ceil(60 / 7) = 9 clusters.
import inspect as _inspect

from src.factory.gates import gate_g6_forward as _gate_g6_forward

_G6_REQUIRED_LEDGER_DAYS = _inspect.signature(
    _gate_g6_forward).parameters["required_ledger_days"].default
DEFAULT_REQUIRED_CLUSTERS = math.ceil(
    _G6_REQUIRED_LEDGER_DAYS / DEFAULT_SPA_BLOCK_LENGTH)

POINT_CLASS_ORDER = ("A", "B", "C", "D")  # best -> worst, per KNOWN_AT_GRADES-like usage


class ScorecardError(ValueError):
    """A scorecard/fitness assembly was attempted with malformed inputs."""


@dataclass(frozen=True, slots=True)
class AbsentComponent:
    """One field or component this module could not compute, and why.

    `field` names either a whole Fitness component (e.g. "robustness") or a
    single field within one that could not be computed independently of the
    rest (e.g. "economic.logloss_vs_market").
    """

    field: str
    reason: str


@dataclass(frozen=True, slots=True)
class RealizedStats:
    """Everything this module can compute from `bets` alone -- no decisions,
    no reviews, no research artifact needed. Never partially absent: an
    empty `bets` sequence produces real (zero/false) values, not fabricated
    ones, because "nothing has settled yet" is itself a true fact.
    """

    n_settled: int
    n_wins: int
    n_losses: int
    n_pushes: int
    n_voids: int
    hit_rate: Optional[float]  # wins / (wins + losses); None with no decided bets
    total_staked_units: float
    total_profit_units: float
    roi_units: float
    avg_odds_decimal: Optional[float]  # None with no settled bets
    starting_bankroll: float
    bankroll: float
    peak: float
    drawdown_max: float
    per_bet_returns: tuple  # profit_units / stake_units, decided bets only
    volatility: Optional[float]  # sample stdev of per_bet_returns; None if n<2


def compute_realized_stats(bets: Sequence[SettledBet],
                            starting_bankroll: float = 1000.0) -> RealizedStats:
    """Replay `bets` (in the order given -- callers pass them chronologically,
    matching `PaperAccount._record_settlement`'s own running-total discipline)
    into bankroll/ROI/drawdown/hit-rate/average-odds/volatility.

    This is a pure replay, independent of any live `PaperAccount` -- a runner
    that already has one can pass `account.ledger.read()`'s settled rows
    reconstructed as `SettledBet`s, or the account's own settled-bet list, and
    get an identical answer to what the account itself would report for
    bankroll/drawdown_max/roi_units (see tests/test_factory_scorecard.py).
    """
    n_settled = n_wins = n_losses = n_pushes = n_voids = 0
    total_staked = total_profit = 0.0
    bankroll = starting_bankroll
    peak = starting_bankroll
    drawdown_max = 0.0
    decimal_odds: list = []
    returns: list = []

    for settled in bets:
        n_settled += 1
        outcome = settled.outcome
        if outcome == WIN:
            n_wins += 1
        elif outcome == LOSS:
            n_losses += 1
        elif outcome == PUSH:
            n_pushes += 1
        elif outcome == VOID:
            n_voids += 1
        else:
            raise ScorecardError(f"unrecognized settlement outcome {outcome!r}")

        decimal_odds.append(odds_math.american_to_decimal(settled.bet.price_american))

        if outcome not in (PUSH, VOID):
            total_staked += settled.bet.stake_units
            returns.append(settled.profit_units / settled.bet.stake_units)
        total_profit += settled.profit_units
        bankroll += settled.profit_units
        peak = max(peak, bankroll)
        drawdown_max = max(drawdown_max, peak - bankroll)

    hit_rate = (n_wins / (n_wins + n_losses)) if (n_wins + n_losses) > 0 else None
    roi_units = (total_profit / total_staked) if total_staked > 0 else 0.0
    avg_odds_decimal = (sum(decimal_odds) / len(decimal_odds)) if decimal_odds else None
    volatility = statistics.stdev(returns) if len(returns) >= 2 else None

    return RealizedStats(
        n_settled=n_settled, n_wins=n_wins, n_losses=n_losses,
        n_pushes=n_pushes, n_voids=n_voids, hit_rate=hit_rate,
        total_staked_units=total_staked, total_profit_units=total_profit,
        roi_units=roi_units, avg_odds_decimal=avg_odds_decimal,
        starting_bankroll=starting_bankroll, bankroll=bankroll, peak=peak,
        drawdown_max=drawdown_max, per_bet_returns=tuple(returns),
        volatility=volatility,
    )


def decision_key_for(decision: DecisionRecord) -> tuple:
    """The join key from a `DecisionRecord` to the `ReviewRecord` that reviews
    it. MUST include `system_id` (B4 fix, 2026-09-03): two systems that
    decide the same (event, market, selection) at the exact same instant --
    routine when several genomes evaluate the same board -- are two
    DISTINCT decisions and must never share a review. Before this fix the
    key omitted `system_id` entirely, so `_decision_review_pairs` paired
    one system's decision with every OTHER system's review of the same
    (event_id, market_key, selection_id, decision_utc); reproduced on
    2026-09-03: `trivial_always_home` (27 settled bets) picked up n=41
    calibration pairs, the exact contaminated numbers the published
    `window=2026-08-31` scorecard carried. `logloss_vs_market` IS
    `objective()` -- the one scalar the factory ranks systems on -- so a
    contaminated join here is not cosmetic.

    Mirrors `src.engine.slate.decision_key`'s five-field shape exactly
    (that function's own docstring already named `decision_key_for`'s old
    four fields "plus system_id" -- this brings the two into agreement).
    Any `ReviewRecord.decision_key` already on disk from BEFORE this fix is
    a 4-tuple lacking `system_id`; it can never equal one of these 5-tuples
    again, so it simply stops joining to anything post-fix rather than
    joining to the wrong system -- conservative by construction, never a
    fabricated match. See src/engine/settle_slate.py's `run_settle` for the
    matching per-system filter on the `reviews` handed to `build_scorecard`.
    """
    return (decision.event_id, decision.system_id, decision.market_key,
            decision.selection_id, decision.decision_utc)


def _worst_point_class(decisions: Sequence[DecisionRecord]) -> str:
    """The worst `known_at_grade` (A best .. D worst) across `decisions`,
    for `ForwardSurvivalComponent.point_class` -- that field is the same
    A/B/C/D knowability vocabulary G6 and G1 grade on
    (`gate_g6_forward(point_class=...)`, `known_at_grade`), NOT
    `DecisionRecord.point_class` (a distinct market-timing label, e.g.
    "LATE_BOARD"). Worst-of, never best-of, so one grade-D decision cannot
    be hidden behind a pile of grade-A ones."""
    if not decisions:
        return "D"
    return max((d.known_at_grade for d in decisions),
               key=lambda pc: POINT_CLASS_ORDER.index(pc)
               if pc in POINT_CLASS_ORDER else len(POINT_CLASS_ORDER))


def _decision_review_pairs(decisions: Sequence[DecisionRecord],
                            reviews: Sequence[ReviewRecord]):
    """Yield (decision, review) pairs for decisions that both have a
    matching settled review AND carry a `p_model` -- the only pairs usable
    for calibration (logloss/brier) or CLV."""
    by_key = {decision_key_for(d): d for d in decisions}
    for review in reviews:
        decision = by_key.get(review.decision_key)
        if decision is not None:
            yield decision, review


def _calibration(decisions: Sequence[DecisionRecord],
                  reviews: Sequence[ReviewRecord]) -> tuple:
    """(logloss_mean, brier_mean, n) over decision/review pairs with a
    `p_model` and a win/loss settlement. `n == 0` means genuinely nothing
    was computable -- callers must not treat that as a passing 0.0 logloss.

    N2/honesty fix (2026-09-04), REVISED under docs/PREREG_CALIBRATED_
    PROBABILITY.md §5: a calibration claim ("this probability was
    well-calibrated") is meaningful for any probability that was an honest
    attempt at calibration -- `model_derived` (fitted, price-independent)
    AND `market_derived` (the board's own de-vigged consensus, republished
    verbatim; §1 calls it "already a well-calibrated forecast" by
    construction). A `placeholder` constant (a null control's fixed
    convention, e.g. 0.5) or `none` (no probability at all) is NOT an
    attempt at calibration and stays excluded, exactly like `p_model is
    None` always was.

    Widening this from model_derived-only to include market_derived is
    deliberate, not an oversight: it is what makes §5's trap ("0.67275 <
    ln 2, so the log-loss half of `economically_meaningful` PASSES on the
    market's own forecast") a real, reachable code path rather than one
    that could never fire because this function filtered market_derived
    out before it ever reached `logloss_mean`. What still holds
    `economically_meaningful` shut for a market_derived-only system is
    `n_edge == 0` (`_mean_edge_return` below), never this function --
    see the named regression test in tests/test_factory_scorecard.py.
    """
    losses, briers = [], []
    for decision, review in _decision_review_pairs(decisions, reviews):
        if (decision.p_model is None
                or decision.p_model_provenance not in _CALIBRATION_ELIGIBLE_PROVENANCE
                or review.settled not in (WIN, LOSS)):
            continue
        y = 1.0 if review.settled == WIN else 0.0
        p = min(max(decision.p_model, 1e-9), 1 - 1e-9)
        losses.append(-(y * math.log(p) + (1 - y) * math.log(1 - p)))
        briers.append((decision.p_model - y) ** 2)
    n = len(losses)
    if n == 0:
        return None, None, 0
    return sum(losses) / n, sum(briers) / n, n


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    """docs/PREREG_CALIBRATED_PROBABILITY.md §4's calibration measurement
    for one `p_model_provenance`'s decision/review pairs -- reporting only,
    never a gate on `promotion_verdict` (that stays `_calibration`/
    `_mean_edge_return`, above). Below the §4 minimum sample, `sufficient`
    is False and every score field stays `None`/empty: no calibration claim
    is published at any sample size below the floor, not even a
    PROVISIONAL one -- §4/§8 ("Reports reliability bins on 40 games").
    """

    provenance: str
    n_pairs: int
    n_clusters: int
    required_pairs: int
    required_clusters: int
    sufficient: bool
    log_loss: Optional[float] = None
    brier: Optional[float] = None
    ece: Optional[float] = None
    max_ce: Optional[float] = None
    mean_predicted: Optional[float] = None
    observed_rate: Optional[float] = None
    reliability_fixed_width: tuple = ()
    reliability_equal_count: tuple = ()
    # Baseline 1 (§4): the de-vigged consensus on the same games. For a
    # market_derived probability that IS this forecast (§1: "forecast and
    # benchmark are the same object"), so the delta is exactly 0.0,
    # published as zero, never omitted. None for any other provenance --
    # this report does not attempt a separate consensus lookup for those.
    baseline_market_delta_log_loss: Optional[float] = None
    # Baseline 2 (§4): `calibration.baseline_base_rate` on the same outcomes.
    baseline_base_rate_log_loss: Optional[float] = None
    baseline_base_rate_brier: Optional[float] = None
    # Baseline 3 (§4): the frozen 2024 reference points, context only, never
    # a live cross-sample comparison (docs/EVOLAB_PHASE2A_BASELINE.md §9.2).
    baseline_phase2a_log_loss: float = 0.67275
    baseline_phase2a_brier: float = 0.23999


def build_calibration_report(
    decisions: Sequence[DecisionRecord],
    reviews: Sequence[ReviewRecord],
    *,
    provenance: str = PROBABILITY_PROVENANCE_MARKET_DERIVED,
    min_pairs: int = MIN_CALIBRATION_PAIRS,
    required_clusters: int = DEFAULT_REQUIRED_CLUSTERS,
    bins: int = 10,
) -> CalibrationReport:
    """docs/PREREG_CALIBRATED_PROBABILITY.md §4, implemented verbatim: both
    bin schemes, log-loss/Brier/ECE/max-CE, the three named baselines,
    gated by the minimum-sample rule (>=500 decision/review pairs AND >=9
    independent 7-day game-day clusters). Calls
    `src.core.calibration.reliability_curve`/`reliability_curve_equal_count`
    -- there is exactly one reliability implementation in this codebase.
    """
    pairs = [
        (d, r) for d, r in _decision_review_pairs(decisions, reviews)
        if d.p_model is not None and d.p_model_provenance == provenance
        and r.settled in (WIN, LOSS)
    ]
    n_pairs = len(pairs)
    decision_days = {d.decision_utc[:10] for d, _ in pairs if d.decision_utc}
    n_clusters = len(decision_days) // int(DEFAULT_SPA_BLOCK_LENGTH)
    sufficient = n_pairs >= min_pairs and n_clusters >= required_clusters

    if not sufficient:
        return CalibrationReport(
            provenance=provenance, n_pairs=n_pairs, n_clusters=n_clusters,
            required_pairs=min_pairs, required_clusters=required_clusters,
            sufficient=False,
        )

    preds = [d.p_model for d, _ in pairs]
    outs = [1.0 if r.settled == WIN else 0.0 for _, r in pairs]
    scores = calibration_module.score_all(preds, outs, bins=bins)
    fixed = tuple(calibration_module.reliability_curve(preds, outs, bins=bins))
    equal = tuple(calibration_module.reliability_curve_equal_count(
        preds, outs, bins=bins))
    base_rate = calibration_module.baseline_base_rate(outs)

    market_delta = (0.0 if provenance == PROBABILITY_PROVENANCE_MARKET_DERIVED
                    else None)

    return CalibrationReport(
        provenance=provenance, n_pairs=n_pairs, n_clusters=n_clusters,
        required_pairs=min_pairs, required_clusters=required_clusters,
        sufficient=True,
        log_loss=scores["log_loss"], brier=scores["brier"],
        ece=scores["ece"], max_ce=scores["max_ce"],
        mean_predicted=scores["mean_predicted"],
        observed_rate=scores["observed_rate"],
        reliability_fixed_width=fixed, reliability_equal_count=equal,
        baseline_market_delta_log_loss=market_delta,
        baseline_base_rate_log_loss=base_rate["log_loss"],
        baseline_base_rate_brier=base_rate["brier"],
    )


def _mean_edge_return(decisions: Sequence[DecisionRecord]) -> tuple:
    """Mean of `edge_bps` (p_model - de-vigged fair, already computed on
    every play decision -- src/ledger/records.py's PRICE_OBSERVATION_IDENTITY
    docstring) over verdict=="play" decisions that carry one, as a fraction.
    Returns (mean_or_None, n).

    N2/honesty fix: `DecisionRecord.__post_init__` already makes `edge_bps`
    structurally None for anything but `model_derived` provenance, so the
    `d.edge_bps is not None` filter below can never admit a placeholder or
    market_derived row -- the explicit provenance check is defense in
    depth, and self-documents the same claim this module's other economic
    aggregations make.
    """
    edges = [d.edge_bps for d in decisions
             if d.verdict == "play" and d.edge_bps is not None
             and d.p_model_provenance == PROBABILITY_PROVENANCE_MODEL_DERIVED]
    if not edges:
        return None, 0
    return (sum(edges) / len(edges)) / 10000.0, len(edges)


@dataclass(frozen=True, slots=True)
class ClvStats:
    """CLV (src/pipeline/grading.py's real, primary metric) -- distinct from
    `late_move` -- computed per decision/review pair where the review's
    `market_path` carries a captured `close_price`. Advisory only: mirrors
    `Scorecard.clv_bps_mean`'s own label and never gates `promotion_verdict`.
    """

    n_graded: int
    n_total_reviewed: int
    mean_cents: Optional[float]
    mean_prob_edge: Optional[float]
    beat_rate: Optional[float]


def compute_clv_stats(decisions: Sequence[DecisionRecord],
                       reviews: Sequence[ReviewRecord]) -> ClvStats:
    from src.pipeline import snapshots as _snapshots

    cents, prob_edges, beats = [], [], []
    n_total = 0
    for decision, review in _decision_review_pairs(decisions, reviews):
        n_total += 1
        close_price = (review.market_path or {}).get("close_price")
        if close_price is None or decision.price_american is None:
            continue
        value = _snapshots.closing_line_value(decision.price_american, close_price)
        cents.append(value["cents"])
        prob_edges.append(value["prob_edge"])
        beats.append(1.0 if value["beat_close"] else 0.0)

    n_graded = len(cents)
    return ClvStats(
        n_graded=n_graded, n_total_reviewed=n_total,
        mean_cents=(sum(cents) / n_graded) if n_graded else None,
        mean_prob_edge=(sum(prob_edges) / n_graded) if n_graded else None,
        beat_rate=(sum(beats) / n_graded) if n_graded else None,
    )


@dataclass(frozen=True, slots=True)
class FitnessAssembly:
    """The result of `build_fitness`: a real `Fitness`, what could not be
    computed and why, and the raw realized stats it was built from (so a
    caller building a `Scorecard` or an EOD report never has to recompute
    the same numbers a second, possibly divergent, way)."""

    fitness: Fitness
    absent: tuple  # tuple[AbsentComponent, ...]
    stats: RealizedStats
    clv: ClvStats

    def absent_reasons(self) -> dict:
        return {a.field: a.reason for a in self.absent}


def build_fitness(
    system_id: str,
    bets: Sequence[SettledBet],
    decisions: Sequence[DecisionRecord],
    reviews: Sequence[ReviewRecord],
    research: Optional[Mapping[str, Any]] = None,
    *,
    world: str = "real",
    window: str = "forward",
    starting_bankroll: float = 1000.0,
    required_clusters: int = DEFAULT_REQUIRED_CLUSTERS,
) -> FitnessAssembly:
    """Assemble a real `Fitness` for `system_id` from settled bets, its
    decisions/reviews, and whatever research artifact exists.

    `research`, if given, is a plain mapping with any of these OPTIONAL keys
    -- each independently absent if its key (or a needed sub-key) is missing:

      "battery"          -- the raw dict returned by
                             `src.research.battery.run(rows, ...)`
                             (`{"survives", "ran", "fatal", "report",
                             "rules": {"version", "fingerprint"}}`).
      "robustness"        -- {"cscv_pbo", "spa_p", "placebo_percentile",
                             "stable_across_splits"}, pre-computed by a
                             population-wide src.evolab.cscv/spa sweep (those
                             functions need every candidate's fitness table
                             at once; this module only ever sees one system).
      "forward_survival"  -- {"out_of_sample", "within_sealed_epochs"},
                             epoch-registry facts this module has no way to
                             derive from bets/decisions alone.
      "price_resilience"  -- {"survives_worst_book", "survives_shrink",
                             "shrink_fraction"}, from a worst-book/shrink
                             sensitivity run this module does not perform.
      "multiplicity"      -- {"effective_tests", "raw_tests",
                             "total_searched_at_verdict",
                             "multiplicity_charge"}. Derive from a
                             `src.research.funnel` family (post `_apply_fdr`)
                             with, e.g., `effective_tests =
                             sum(1 for r in family if r["q_pass"])`,
                             `raw_tests = len(family)`, `multiplicity_charge
                             = this system's own row["fdr_threshold"]`.
    """
    research = research or {}
    absent: list = []

    stats = compute_realized_stats(bets, starting_bankroll=starting_bankroll)
    clv = compute_clv_stats(decisions, reviews)

    # -- bankroll: always computable, even from zero bets (a true "nothing
    # has happened yet" is not a fabricated pass). --------------------------
    bankroll_component = BankrollComponent(
        realized_roi=stats.roi_units,
        drawdown_max=stats.drawdown_max,
        bankroll_positive=stats.bankroll > stats.starting_bankroll,
    )

    # -- economic: "economically meaningful performance" per fitness.py's
    # own docstring -- calibration/return vs the de-vigged market, NEVER the
    # bankroll P&L (that is `bankroll`, kept separate on purpose). ----------
    edge_return, n_edge = _mean_edge_return(decisions)
    logloss_mean, brier_mean, n_calibration = _calibration(decisions, reviews)
    if n_edge == 0:
        absent.append(AbsentComponent(
            "economic.realized_return",
            "no verdict=='play' decision carries a model_derived edge_bps "
            "(edge_bps is structurally null for none/placeholder/"
            "market_derived provenance -- see DecisionRecord's invariant)"))
    if n_calibration == 0:
        absent.append(AbsentComponent(
            "economic.logloss_vs_market",
            "no decision/review pair carries both a model_derived p_model "
            "and a win/loss settlement (a placeholder or market_derived "
            "p_model is never folded into a calibration claim)"))
    economically_meaningful = bool(
        n_edge > 0 and edge_return > 0.0
        and n_calibration > 0 and logloss_mean < NEUTRAL_LOGLOSS
    )
    economic_component = EconomicComponent(
        logloss_vs_market=logloss_mean if n_calibration else NEUTRAL_LOGLOSS,
        realized_return=edge_return if n_edge else 0.0,
        economically_meaningful=economically_meaningful,
    )

    # -- robustness: population-wide CSCV/SPA/placebo evidence, supplied or
    # absent. ------------------------------------------------------------
    robustness_in = research.get("robustness")
    if robustness_in is None:
        absent.append(AbsentComponent(
            "robustness", "no CSCV/SPA/placebo artifact supplied"))
        robustness_component = RobustnessComponent(
            cscv_pbo=1.0, spa_p=1.0, placebo_percentile=0.0,
            stable_across_splits=False,
        )
    else:
        robustness_component = RobustnessComponent(
            cscv_pbo=robustness_in["cscv_pbo"],
            spa_p=robustness_in["spa_p"],
            placebo_percentile=robustness_in["placebo_percentile"],
            stable_across_splits=bool(robustness_in["stable_across_splits"]),
        )

    # -- forward_survival: forward_selections/ledger_days/point_class are
    # real, computed from decisions; out_of_sample/within_sealed_epochs are
    # epoch-registry labels this module cannot derive on its own. ----------
    play_decisions = [d for d in decisions if d.verdict == "play"]
    decision_days = {d.decision_utc[:10] for d in decisions if d.decision_utc}
    forward_in = research.get("forward_survival")
    if forward_in is None:
        absent.append(AbsentComponent(
            "forward_survival.out_of_sample/within_sealed_epochs",
            "no epoch-registry artifact supplied"))
        out_of_sample = within_sealed_epochs = False
    else:
        out_of_sample = bool(forward_in["out_of_sample"])
        within_sealed_epochs = bool(forward_in["within_sealed_epochs"])
    forward_survival_component = ForwardSurvivalComponent(
        forward_selections=len(play_decisions),
        ledger_days=len(decision_days),
        out_of_sample=out_of_sample,
        within_sealed_epochs=within_sealed_epochs,
        point_class=_worst_point_class(decisions),
    )

    # -- sample_sufficiency: always computable (possibly zero), never absent
    # -- n_independent_clusters is game-day BLOCKS, never a decision count
    # (design-factory-first.md §10.4). --------------------------------------
    n_clusters = len(decision_days) // int(DEFAULT_SPA_BLOCK_LENGTH)
    sample_sufficiency_component = SampleSufficiencyComponent(
        n_decisions=len(decisions),
        n_independent_clusters=n_clusters,
        required_clusters=required_clusters,
    )

    # -- price_resilience: a worst-book/shrink sensitivity run this module
    # does not perform. ------------------------------------------------------
    price_in = research.get("price_resilience")
    if price_in is None:
        absent.append(AbsentComponent(
            "price_resilience", "no worst-book/shrink sensitivity artifact supplied"))
        price_resilience_component = PriceResilienceComponent(
            survives_worst_book=False, survives_shrink=False,
            shrink_fraction=0.25,
        )
    else:
        price_resilience_component = PriceResilienceComponent(
            survives_worst_book=bool(price_in["survives_worst_book"]),
            survives_shrink=bool(price_in["survives_shrink"]),
            shrink_fraction=price_in["shrink_fraction"],
        )

    # -- falsification: the real battery (src/research/battery.py `run()`),
    # translated verbatim -- never re-derived here. --------------------------
    battery_in = research.get("battery")
    if battery_in is None:
        absent.append(AbsentComponent(
            "falsification", "no falsification battery artifact supplied"))
        falsification_component = FalsificationComponent(
            battery_verdict="NOT_RUN", battery_rules_version="absent",
            fatal_rules_triggered=0,
        )
    else:
        falsification_component = falsification_from_battery(battery_in)

    # -- multiplicity: the real BH-FDR family (src/research/funnel.py
    # `_apply_fdr`), pre-summarized -- never re-derived here. ----------------
    multiplicity_in = research.get("multiplicity")
    if multiplicity_in is None:
        absent.append(AbsentComponent(
            "multiplicity", "no BH-FDR funnel family artifact supplied"))
        multiplicity_component = MultiplicityComponent(
            effective_tests=0, raw_tests=0, total_searched_at_verdict=0,
            multiplicity_charge=0.0,
        )
    else:
        multiplicity_component = MultiplicityComponent(
            effective_tests=multiplicity_in["effective_tests"],
            raw_tests=multiplicity_in["raw_tests"],
            total_searched_at_verdict=multiplicity_in["total_searched_at_verdict"],
            multiplicity_charge=multiplicity_in["multiplicity_charge"],
        )

    fitness = Fitness(
        system_id=system_id, world=world, window=window,
        economic=economic_component, robustness=robustness_component,
        forward_survival=forward_survival_component,
        sample_sufficiency=sample_sufficiency_component,
        price_resilience=price_resilience_component,
        falsification=falsification_component,
        multiplicity=multiplicity_component,
        bankroll=bankroll_component,
    )

    return FitnessAssembly(fitness=fitness, absent=tuple(absent), stats=stats,
                            clv=clv)


def falsification_from_battery(battery_result: Mapping[str, Any]) -> FalsificationComponent:
    """Translate `src.research.battery.run()`'s real output verbatim into a
    `FalsificationComponent` -- never re-derives the verdict.

    `battery_result["ran"] is False` means the sample was under the
    battery's own floor and `survives=True` is vacuous (see battery.py's own
    docstring) -- that is reported as NOT_RUN, never PASS, so a vacuous
    survival can never read as a real one.
    """
    fatal = list(battery_result.get("fatal") or [])
    ran = bool(battery_result.get("ran", True))
    survives = bool(battery_result.get("survives", False))
    rules = battery_result.get("rules") or {}
    version = rules.get("version", "unknown")
    if not ran:
        verdict = "NOT_RUN"
    elif survives and not fatal:
        verdict = "PASS"
    else:
        verdict = "FAILED"
    return FalsificationComponent(
        battery_verdict=verdict, battery_rules_version=str(version),
        fatal_rules_triggered=len(fatal),
    )


def multiplicity_from_funnel_family(family: Sequence[Mapping[str, Any]],
                                     system_name: str, *,
                                     total_searched_at_verdict: Optional[int] = None
                                     ) -> dict:
    """Translate a `src.research.funnel` family (rows already passed through
    `_apply_fdr`, each carrying `name`, `q_pass`, `fdr_threshold`) into the
    `research["multiplicity"]` shape `build_fitness` expects.

    `effective_tests` is the count of family members that survived BOTH the
    BH-FDR correction and the pre-registered effect floor (`q_pass`) --
    "effective" in the sense of "not paid for and then discarded", not a
    re-derivation of BH's own internal statistic. `multiplicity_charge` is
    the named system's own BH-adjusted alpha threshold.
    """
    raw_tests = len(family)
    effective_tests = sum(1 for row in family if row.get("q_pass"))
    by_name = {row.get("name"): row for row in family}
    row = by_name.get(system_name)
    if row is None:
        raise ScorecardError(
            f"{system_name!r} not found in the supplied funnel family "
            f"({sorted(by_name)})")
    return {
        "effective_tests": effective_tests,
        "raw_tests": raw_tests,
        "total_searched_at_verdict": (
            total_searched_at_verdict if total_searched_at_verdict is not None
            else raw_tests),
        "multiplicity_charge": row.get("fdr_threshold", 0.0) or 0.0,
    }


# ---------------------------------------------------------------------------
# Scorecard
# ---------------------------------------------------------------------------

def _top5_win_share(bets: Sequence[SettledBet]) -> float:
    """Share of total realized profit contributed by the 5 largest winning
    bets -- "dependence on top wins" (C_factory_fitness.md Q8), computed
    directly from settlements rather than requiring a separate graded-row
    battery run. 0.0 (never fabricated) when there is no positive profit to
    share."""
    wins = sorted((b.profit_units for b in bets if b.outcome == WIN), reverse=True)
    total_profit = sum(b.profit_units for b in bets)
    if not wins or total_profit <= 0:
        return 0.0
    return sum(wins[:5]) / total_profit


def build_scorecard(
    system_id: str,
    world: str,
    window: str,
    point_class: str,
    market_key: str,
    bets: Sequence[SettledBet],
    decisions: Sequence[DecisionRecord],
    reviews: Sequence[ReviewRecord],
    research: Optional[Mapping[str, Any]] = None,
    *,
    starting_bankroll: float = 1000.0,
    required_clusters: int = DEFAULT_REQUIRED_CLUSTERS,
) -> tuple:
    """Build one `Scorecard` row (system, world, window, point_class,
    market) plus the same `absent` accounting `build_fitness` produces --
    every field this module could not genuinely compute is a documented,
    conservative placeholder, listed in the returned `absent` tuple, never a
    silent invention. Returns `(Scorecard, tuple[AbsentComponent, ...])`.
    """
    assembly = build_fitness(
        system_id, bets, decisions, reviews, research, world=world,
        window=window, starting_bankroll=starting_bankroll,
        required_clusters=required_clusters,
    )
    fitness = assembly.fitness
    stats = assembly.stats
    clv = assembly.clv
    absent = list(assembly.absent)

    if clv.n_graded == 0:
        absent.append(AbsentComponent(
            "clv_bps_mean",
            "no decision/review pair carries a captured close_price"))
    if stats.avg_odds_decimal is None:
        absent.append(AbsentComponent("avg_odds_decimal", "no settled bets"))

    # reliability_bins: docs/PREREG_CALIBRATED_PROBABILITY.md §4/§5 -- the
    # implementation is `src.core.calibration.reliability_curve`, which has
    # existed since before this fix; "no calibration-bin implementation
    # exists" was never true. This system's own p_model_provenance (the one
    # eligible provenance it actually emits, model_derived or
    # market_derived -- a system emits exactly one) decides whether there is
    # anything to bin at all; the §4 minimum-sample rule (>=500 pairs, >=9
    # seven-day clusters) decides whether a claim is publishable yet.
    provenances_present = {d.p_model_provenance for d in decisions}
    eligible_provenances = sorted(
        provenances_present & _CALIBRATION_ELIGIBLE_PROVENANCE)
    calibration_report = None
    if not eligible_provenances:
        absent.append(AbsentComponent(
            "reliability_bins",
            "no model_derived or market_derived decision exists for this "
            "system -- a placeholder or none-provenance p_model is not a "
            "calibration attempt (docs/PREREG_CALIBRATED_PROBABILITY.md §4)"))
    else:
        calibration_report = build_calibration_report(
            decisions, reviews, provenance=eligible_provenances[0])
        if not calibration_report.sufficient:
            absent.append(AbsentComponent(
                "reliability_bins",
                f"INSUFFICIENT SAMPLE: {calibration_report.n_pairs} "
                f"decision/review pair(s) (need >= "
                f"{calibration_report.required_pairs}) across "
                f"{calibration_report.n_clusters} independent 7-day "
                f"cluster(s) (need >= {calibration_report.required_clusters}) "
                "-- docs/PREREG_CALIBRATED_PROBABILITY.md §4"))
    absent.append(AbsentComponent(
        "realized_return_ci", "no clustered-bootstrap CI implementation exists"))
    absent.append(AbsentComponent(
        "stability.season_month_stability",
        "season/month/market stability has no implementation anywhere in "
        "this codebase (checkpoint 2026-09-03 hardest truth 9)"))

    account = AccountSummary(
        bankroll=stats.bankroll, units=stats.total_staked_units,
        drawdown=stats.drawdown_max, roi_units=stats.roi_units,
        profit_units=stats.total_profit_units,
    )

    calibration_brier = _calibration(decisions, reviews)[1]
    # N2/honesty fix: shown "beside every decision" in aggregate here --
    # Scorecard is a per-(system, window) row, not per-decision, so a
    # per-provenance breakdown is the aggregate-appropriate form of the same
    # disclosure eod.py makes per-decision. Never itself folded into any
    # scored field; purely a reporting-only count, exactly like clv_bps_mean.
    provenance_counts: dict = {}
    for d in decisions:
        provenance_counts[d.p_model_provenance] = (
            provenance_counts.get(d.p_model_provenance, 0) + 1)
    scorecard = Scorecard(
        system_id=system_id, world=world, window=window,
        point_class=point_class, market_key=market_key,
        n_decisions=fitness.sample_sufficiency.n_decisions,
        n_independent_clusters=fitness.sample_sufficiency.n_independent_clusters,
        logloss_vs_market=fitness.economic.logloss_vs_market,
        brier=calibration_brier if calibration_brier is not None else NEUTRAL_BRIER,
        reliability_bins=(calibration_report.reliability_fixed_width
                          if calibration_report is not None
                          and calibration_report.sufficient else ()),
        realized_return=fitness.economic.realized_return,
        realized_return_ci=(),
        avg_odds_decimal=stats.avg_odds_decimal or 0.0,
        clv_bps_mean=(clv.mean_prob_edge or 0.0) * 10000.0,
        stability={
            "volatility_stdev_of_returns": stats.volatility,
            "n_returns": len(stats.per_bet_returns),
            "season_month_stability": None,
            "p_model_provenance_counts": provenance_counts,
        },
        price_sensitivity={
            "survives_worst_book": fitness.price_resilience.survives_worst_book,
            "survives_shrink": fitness.price_resilience.survives_shrink,
            "shrink_fraction": fitness.price_resilience.shrink_fraction,
        },
        top5_win_share=_top5_win_share(bets),
        placebo_percentile=fitness.robustness.placebo_percentile,
        cscv_pbo=fitness.robustness.cscv_pbo,
        spa_p=fitness.robustness.spa_p,
        battery_verdict=fitness.falsification.battery_verdict,
        battery_rules_version=fitness.falsification.battery_rules_version,
        effective_tests=fitness.multiplicity.effective_tests,
        raw_tests=fitness.multiplicity.raw_tests,
        total_searched_at_verdict=fitness.multiplicity.total_searched_at_verdict,
        account=account,
    )
    return scorecard, tuple(absent)
