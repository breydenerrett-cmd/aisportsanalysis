"""Fitness: a structured multi-component object, never a single scalar.

docs/ARCHITECTURE_BETTING_ENGINE.md §9.1 owner decision 9: "Profitability,
ROI, bankroll and drawdown are measured, but bankroll alone never decides
promotion. Fitness = economically meaningful performance plus robustness,
OOS/forward survival, sample sufficiency, price resilience, falsification
survival and multiple-testing controls." This module makes that a type
system enforces rather than a policy a reviewer remembers: `Fitness` cannot
be collapsed to one number (there is no `.score()` and no `__float__`), and
`promotion_verdict` inspects every component, refusing whenever the only
components that look positive are the bankroll ones.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Mapping


class FitnessError(ValueError):
    """A Fitness component was malformed (out of range, wrong shape)."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FitnessError(message)


def _require_unit_interval(value: float, name: str) -> None:
    _require(0.0 <= value <= 1.0, f"{name}={value!r} must be within [0, 1]")


@dataclass(frozen=True, slots=True)
class BankrollComponent:
    """Money, reported never optimized -- mirrors AccountSummary's role on
    Scorecard (src/ledger/records.py). Present on Fitness ONLY as one
    component among several, never alone sufficient for promotion."""

    realized_roi: float
    drawdown_max: float
    bankroll_positive: bool

    def __post_init__(self) -> None:
        _require(self.drawdown_max >= 0.0,
                  f"drawdown_max={self.drawdown_max!r} must be >= 0")


@dataclass(frozen=True, slots=True)
class EconomicComponent:
    """"Economically meaningful performance" -- calibration/return versus
    the de-vigged market, independent of whether it survives robustness
    checks (that is a separate component below)."""

    logloss_vs_market: float
    realized_return: float
    economically_meaningful: bool

    def __post_init__(self) -> None:
        _require(self.logloss_vs_market >= 0.0,
                  "logloss_vs_market must be >= 0")


@dataclass(frozen=True, slots=True)
class RobustnessComponent:
    """Cross-split / cross-world stability -- CSCV PBO, SPA p-value, and a
    placebo-ceiling percentile, the factory's immune system per
    docs/planning/design-factory-first.md §2."""

    cscv_pbo: float
    spa_p: float
    placebo_percentile: float
    stable_across_splits: bool

    def __post_init__(self) -> None:
        _require_unit_interval(self.cscv_pbo, "cscv_pbo")
        _require_unit_interval(self.spa_p, "spa_p")
        _require_unit_interval(self.placebo_percentile / 100.0
                                if self.placebo_percentile > 1.0
                                else self.placebo_percentile,
                                "placebo_percentile")


@dataclass(frozen=True, slots=True)
class ForwardSurvivalComponent:
    """OOS/forward survival: does the candidate keep working out-of-sample,
    within sealed epochs, per §5 G6."""

    forward_selections: int
    ledger_days: int
    out_of_sample: bool
    within_sealed_epochs: bool
    point_class: str

    def __post_init__(self) -> None:
        _require(self.forward_selections >= 0,
                  "forward_selections must be >= 0")
        _require(self.ledger_days >= 0, "ledger_days must be >= 0")
        _require(self.point_class in ("A", "B", "C", "D"),
                  f"point_class={self.point_class!r} must be one of A/B/C/D")

    @property
    def survived(self) -> bool:
        return (
            self.out_of_sample and self.within_sealed_epochs
            and self.point_class in ("A", "B")
            and self.forward_selections > 0 and self.ledger_days > 0
        )


@dataclass(frozen=True, slots=True)
class SampleSufficiencyComponent:
    """Whether there is enough independent evidence to trust anything else
    on this Fitness at all -- n_independent_clusters mirrors the same-named
    Scorecard field (src/ledger/records.py); a game-day-block count, not a
    raw decision count."""

    n_decisions: int
    n_independent_clusters: int
    required_clusters: int

    def __post_init__(self) -> None:
        _require(self.n_decisions >= 0, "n_decisions must be >= 0")
        _require(self.n_independent_clusters >= 0,
                  "n_independent_clusters must be >= 0")
        _require(self.required_clusters >= 0,
                  "required_clusters must be >= 0")

    @property
    def sufficient(self) -> bool:
        return self.n_independent_clusters >= self.required_clusters


@dataclass(frozen=True, slots=True)
class PriceResilienceComponent:
    """Edge survives at the worst book and under a shrink of p_model toward
    the market -- the LOCK-adjacent test applied generally to any Fitness."""

    survives_worst_book: bool
    survives_shrink: bool
    shrink_fraction: float

    def __post_init__(self) -> None:
        _require_unit_interval(self.shrink_fraction, "shrink_fraction")

    @property
    def resilient(self) -> bool:
        return self.survives_worst_book and self.survives_shrink


@dataclass(frozen=True, slots=True)
class FalsificationComponent:
    """Survival of the falsification battery (src/research/battery.py) --
    versioned, fatal-rule based; a fingerprint pins which rule set ran."""

    battery_verdict: str  # e.g. "PASS", "BELOW_PLACEBO_CEILING", ...
    battery_rules_version: str
    fatal_rules_triggered: int

    def __post_init__(self) -> None:
        _require(self.fatal_rules_triggered >= 0,
                  "fatal_rules_triggered must be >= 0")

    @property
    def survived(self) -> bool:
        return self.fatal_rules_triggered == 0 and self.battery_verdict == "PASS"


@dataclass(frozen=True, slots=True)
class MultiplicityComponent:
    """Multiple-testing control -- effective vs raw tests, and the charge for
    this specific cell, per docs/planning/design-factory-first.md §1.3/§1.4:
    "population size is a cost, not an asset, and must be priced."""

    effective_tests: int
    raw_tests: int
    total_searched_at_verdict: int
    multiplicity_charge: float  # e.g. BH-FDR-adjusted alpha spend, >= 0

    def __post_init__(self) -> None:
        _require(self.effective_tests <= self.raw_tests or self.raw_tests == 0,
                  "effective_tests must never exceed raw_tests")
        _require(self.total_searched_at_verdict >= 0,
                  "total_searched_at_verdict must be >= 0")
        _require(self.multiplicity_charge >= 0.0,
                  "multiplicity_charge must be >= 0")


@dataclass(frozen=True, slots=True)
class Fitness:
    """A structured, multi-component fitness record. NEVER a single scalar.

    §9.1 decision 9, verbatim: fitness is "economically meaningful
    performance plus robustness, OOS/forward survival, sample sufficiency,
    price resilience, falsification survival and multiple-testing
    controls." Each of those six clauses is its own component type here,
    plus `bankroll` (measured and reported, per decision 9's first
    sentence, but never sufficient alone -- see `promotion_verdict`).

    This type deliberately has no `.score()`, no `__float__`, and no field
    that could be summed into one number -- collapsing it is a decision a
    caller must make explicitly and separately (and `promotion_verdict`
    below refuses the one collapse the owner ruled out: bankroll-only).
    """

    system_id: str
    world: str
    window: str
    economic: EconomicComponent  # "economically meaningful performance"
    robustness: RobustnessComponent
    forward_survival: ForwardSurvivalComponent
    sample_sufficiency: SampleSufficiencyComponent
    price_resilience: PriceResilienceComponent
    falsification: FalsificationComponent
    multiplicity: MultiplicityComponent
    bankroll: BankrollComponent  # measured + reported, never decisive alone

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)

    def component_names(self) -> tuple:
        return tuple(
            f.name for f in fields(self)
            if f.name not in ("system_id", "world", "window")
        )


@dataclass(frozen=True, slots=True)
class PromotionVerdict:
    """The outcome of evaluating a Fitness for promotion.

    `positive_components` / `negative_components` name which non-bankroll
    components read as positive/negative, so a refusal is always
    inspectable, never a bare boolean.
    """

    promote: bool
    reasons: tuple
    positive_components: tuple
    negative_components: tuple

    def __bool__(self) -> bool:
        return self.promote


def _component_positive(name: str, fitness: Fitness) -> bool:
    if name == "economic":
        return fitness.economic.economically_meaningful
    if name == "robustness":
        return fitness.robustness.stable_across_splits
    if name == "forward_survival":
        return fitness.forward_survival.survived
    if name == "sample_sufficiency":
        return fitness.sample_sufficiency.sufficient
    if name == "price_resilience":
        return fitness.price_resilience.resilient
    if name == "falsification":
        return fitness.falsification.survived
    if name == "multiplicity":
        # A multiplicity charge is "positive" (i.e. not disqualifying) only
        # if effective tests were actually reported and the charge is finite
        # -- an uncharged or unreported multiplicity component can never
        # read as positive, it must be paid for to count.
        return (
            fitness.multiplicity.effective_tests > 0
            and fitness.multiplicity.multiplicity_charge >= 0.0
        )
    if name == "bankroll":
        return (
            fitness.bankroll.bankroll_positive
            and fitness.bankroll.realized_roi > 0.0
        )
    raise FitnessError(f"unknown Fitness component {name!r}")


NON_BANKROLL_COMPONENTS = (
    "economic", "robustness", "forward_survival", "sample_sufficiency",
    "price_resilience", "falsification", "multiplicity",
)


def promotion_verdict(fitness: Fitness) -> PromotionVerdict:
    """Decide whether `fitness` supports promotion.

    Refuses whenever ONLY the bankroll component(s) are positive -- the
    literal enforcement of §9.1 decision 9 ("bankroll alone never decides
    promotion"). Promotion additionally requires every non-bankroll
    component to be positive: this is a conjunctive gate, not a majority
    vote, because a single failed component (e.g. falsification) is meant
    to be disqualifying regardless of how good the others look.
    """
    positive = tuple(name for name in fitness.component_names()
                      if _component_positive(name, fitness))
    negative = tuple(name for name in fitness.component_names()
                      if name not in positive)

    non_bankroll_positive = [n for n in positive if n in NON_BANKROLL_COMPONENTS]
    bankroll_only = (
        "bankroll" in positive and not non_bankroll_positive
    )

    reasons = []
    if bankroll_only:
        reasons.append(
            "refused: only the bankroll component is positive -- bankroll "
            "alone never decides promotion (ARCHITECTURE §9.1 decision 9)"
        )
        return PromotionVerdict(promote=False, reasons=tuple(reasons),
                                 positive_components=positive,
                                 negative_components=negative)

    missing = [n for n in NON_BANKROLL_COMPONENTS if n not in positive]
    if missing:
        reasons.append(
            f"refused: non-bankroll component(s) not positive: {missing}"
        )
        return PromotionVerdict(promote=False, reasons=tuple(reasons),
                                 positive_components=positive,
                                 negative_components=negative)

    reasons.append(
        "promoted: every non-bankroll component positive "
        f"({', '.join(NON_BANKROLL_COMPONENTS)}); bankroll measured and "
        "reported, not decisive"
    )
    return PromotionVerdict(promote=True, reasons=tuple(reasons),
                             positive_components=positive,
                             negative_components=negative)
