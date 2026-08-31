"""The noise ceiling and Brey's kill criterion -- Evolution Lab design sections 7 and 15.

NOTHING THIS MODULE PRODUCES IS EVIDENCE. Clearing the ceiling is permission to
keep building inside the sandbox; it is not a finding, not a bet, and it does
not promote anything. Failing to clear it IS a publishable result and the
honest end of the line for this space.

WHAT THE CEILING IS
-------------------
The lab's primary product. Run the ENTIRE search -- enumeration, fitness,
gates, selection, stopping rules, hyperparameters, and later mutation and
crossover -- on worlds known to contain no edge, and record the maximum
fitness the search reaches anyway. That distribution of placebo maxima is how
much apparent edge our own process manufactures from nothing. The real
champion is then read against it: not "is it good?" but "is it better than
what we would have found in a world with nothing to find?".

The comparison is only meaningful if the SAME search produced both numbers.
A real maximum taken over 5,000 strategies compared against placebo maxima
taken over 50 is not a ceiling, it is a rigged comparison; `ceiling_report`
records the strategy counts and warns when they differ.

WHAT THE 95TH PERCENTILE COSTS AT 10 REPLICATES
-----------------------------------------------
With the design's default of 10 worlds per generator, the empirical 95th
percentile under the nearest-rank convention IS the maximum of those 10, and
the smallest achievable exceedance p-value is 1/11 = 0.0909. The threshold is
therefore coarse by construction: it cannot resolve a real champion that sits
just above the placebo pack, and it will call a champion "clear" on the
strength of one lucky placebo world being modest. Section 7 says more
replicates are cheap; `min_worlds` marks anything below the default
UNDERPOWERED so a thin distribution cannot quietly deliver a verdict.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

# Verdicts. Only BELOW_PLACEBO_CEILING is the design's kill verdict and a death
# reason in section 9's taxonomy; the others exist so a report never has to
# round an ambiguous result toward the friendlier answer.
BELOW_PLACEBO_CEILING = "BELOW_PLACEBO_CEILING"
CLEARS_PLACEBO_CEILING = "CLEARS_PLACEBO_CEILING"
INCONCLUSIVE = "INCONCLUSIVE"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

DEFAULT_PERCENTILE = 95.0
DEFAULT_MIN_WORLDS = 10          # design section 7's replicate default
DEFAULT_MIN_GENERATORS = 3       # a majority of five needs at least three


class CeilingError(ValueError):
    """Raised when a ceiling cannot be computed honestly."""


def percentile(values: Sequence[float], pct: float,
               method: str = "nearest_rank") -> float:
    """The `pct`-th percentile of `values`.

    `nearest_rank` (the default) returns the smallest sample value at or above
    the requested rank -- with 10 values at 95% that is the maximum. It is the
    conservative choice for a ceiling: it never interpolates a threshold that
    no placebo world actually reached.

    `linear` is the familiar interpolating definition, offered for reporting
    alongside the nearest-rank number, never as a way to lower a threshold a
    champion failed to clear.
    """
    if not values:
        raise CeilingError("percentile of an empty sample")
    if not 0.0 <= pct <= 100.0:
        raise CeilingError(f"percentile {pct!r} outside [0, 100]")
    ordered = sorted(float(v) for v in values)
    n = len(ordered)
    if method == "nearest_rank":
        rank = math.ceil(pct / 100.0 * n)
        return ordered[min(max(rank, 1), n) - 1]
    if method == "linear":
        if n == 1:
            return ordered[0]
        pos = (pct / 100.0) * (n - 1)
        lo = math.floor(pos)
        hi = math.ceil(pos)
        if lo == hi:
            return ordered[int(pos)]
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)
    raise CeilingError(f"unknown percentile method {method!r}")


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0


@dataclass(frozen=True)
class GeneratorCeiling:
    """Where the real champion sits against one generator's placebo maxima."""

    generator: str
    n_worlds: int
    real_max: float
    placebo_min: float
    placebo_median: float
    placebo_threshold: float     # the percentile the champion must beat
    placebo_max: float
    percentile_rank: float       # 0-100, mid-rank of real among placebo maxima
    exceedance_p: float          # (1 + #{placebo >= real}) / (n + 1)
    clears: bool
    underpowered: bool
    threshold_pct: float

    @property
    def margin(self) -> float:
        """How far above (positive) or below the threshold the champion sits."""
        return self.real_max - self.placebo_threshold


@dataclass(frozen=True)
class CeilingReport:
    """The full ceiling: per generator, pooled, and the verdict."""

    real_max: float
    real_champion: str | None
    per_generator: tuple[GeneratorCeiling, ...]
    pooled: GeneratorCeiling
    verdict: str
    verdict_reason: str
    generators_cleared: tuple[str, ...]
    generators_failed: tuple[str, ...]
    generators_underpowered: tuple[str, ...]
    threshold_pct: float
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_kill(self) -> bool:
        return self.verdict == BELOW_PLACEBO_CEILING


def generator_ceiling(generator: str, real_max: float,
                      placebo_maxima: Sequence[float], *,
                      threshold_pct: float = DEFAULT_PERCENTILE,
                      min_worlds: int = DEFAULT_MIN_WORLDS,
                      method: str = "nearest_rank") -> GeneratorCeiling:
    """Place the real search maximum inside one generator's placebo maxima."""
    maxima = [float(v) for v in placebo_maxima]
    if not maxima:
        raise CeilingError(f"generator {generator}: no placebo worlds")
    for v in maxima:
        if math.isnan(v) or math.isinf(v):
            raise CeilingError(
                f"generator {generator}: non-finite placebo maximum {v!r}")
    if math.isnan(real_max) or math.isinf(real_max):
        raise CeilingError(f"non-finite real maximum {real_max!r}")

    n = len(maxima)
    less = sum(1 for v in maxima if v < real_max)
    equal = sum(1 for v in maxima if v == real_max)
    at_or_above = n - less
    threshold = percentile(maxima, threshold_pct, method=method)

    return GeneratorCeiling(
        generator=generator,
        n_worlds=n,
        real_max=float(real_max),
        placebo_min=min(maxima),
        placebo_median=_median(maxima),
        placebo_threshold=threshold,
        placebo_max=max(maxima),
        percentile_rank=100.0 * (less + 0.5 * equal) / n,
        exceedance_p=(1 + at_or_above) / (n + 1),
        clears=float(real_max) > threshold,
        underpowered=n < min_worlds,
        threshold_pct=threshold_pct,
    )


def kill_criterion(ceilings: Sequence[GeneratorCeiling], *,
                   min_generators: int = DEFAULT_MIN_GENERATORS,
                   count_underpowered: bool = False) -> tuple[str, str]:
    """Brey's kill criterion (design section 15), as a function.

    > If the real search maximum lies inside the placebo maximum distribution
    > -- no better than its 95th percentile -- across the majority of the five
    > generators, evolution is not built.

    A strict majority is required in BOTH directions, and the asymmetry is
    deliberate: failing to clear is the default. A split decision returns
    INCONCLUSIVE rather than being rounded toward the answer that lets the
    build continue, and too few usable generators returns
    INSUFFICIENT_EVIDENCE rather than a verdict from one generator's opinion.

    Underpowered generators (fewer worlds than the replicate default) are
    excluded from the count unless `count_underpowered` is set, because a
    95th percentile taken over three worlds is a number, not a threshold.
    """
    usable = [c for c in ceilings
              if count_underpowered or not c.underpowered]
    if len(usable) < min_generators:
        return (INSUFFICIENT_EVIDENCE,
                f"only {len(usable)} generator(s) with enough placebo worlds; "
                f"{min_generators} are required before any verdict. No claim "
                "about the ceiling may be made from this run.")

    failed = [c.generator for c in usable if not c.clears]
    cleared = [c.generator for c in usable if c.clears]
    n = len(usable)

    if len(failed) * 2 > n:
        return (BELOW_PLACEBO_CEILING,
                f"the real maximum is no better than the {usable[0].threshold_pct:g}th "
                f"percentile of the placebo maxima in {len(failed)} of {n} "
                f"generators ({', '.join(sorted(failed))}). Within this feature "
                "and policy space, our search cannot distinguish apparent "
                "winners from winners generated by worlds known to contain zero "
                "edge. Evolution does not get built.")
    if len(cleared) * 2 > n:
        return (CLEARS_PLACEBO_CEILING,
                f"the real maximum clears the {usable[0].threshold_pct:g}th percentile "
                f"of the placebo maxima in {len(cleared)} of {n} generators "
                f"({', '.join(sorted(cleared))}). That is permission to keep "
                "building in the sandbox, and nothing more: it is not evidence "
                "and promotes nothing.")
    return (INCONCLUSIVE,
            f"{len(cleared)} of {n} generators cleared and {len(failed)} did not; "
            "neither side is a majority. This is not a licence to proceed -- add "
            "placebo replicates until the split resolves.")


def ceiling_report(real_max: float,
                   placebo_maxima: Mapping[str, Sequence[float]], *,
                   real_champion: str | None = None,
                   threshold_pct: float = DEFAULT_PERCENTILE,
                   min_worlds: int = DEFAULT_MIN_WORLDS,
                   min_generators: int = DEFAULT_MIN_GENERATORS,
                   method: str = "nearest_rank",
                   n_strategies_real: int | None = None,
                   n_strategies_placebo: Mapping[str, int] | None = None) -> CeilingReport:
    """Where the real champion sits, per generator and pooled, plus the verdict.

    `placebo_maxima` maps generator id -> the maximum fitness the search
    reached in each placebo world from that generator. One number per world:
    the maximum, because the ceiling is about the best thing the search would
    have crowned, not about the average strategy.

    Pooling treats every world equally regardless of generator. It is reported
    because it is the natural summary, but the per-generator verdicts are the
    ones the kill criterion reads: a generator that is easier than reality
    would drag a pooled threshold down without ever being visible in it.
    """
    if not placebo_maxima:
        raise CeilingError("no placebo maxima; there is no ceiling to report")

    warnings: list[str] = []
    ceilings = []
    pooled_values: list[float] = []
    for generator in sorted(placebo_maxima):
        maxima = list(placebo_maxima[generator])
        ceilings.append(generator_ceiling(
            generator, real_max, maxima,
            threshold_pct=threshold_pct, min_worlds=min_worlds, method=method))
        pooled_values.extend(float(v) for v in maxima)

    pooled = generator_ceiling(
        "POOLED", real_max, pooled_values,
        threshold_pct=threshold_pct, min_worlds=min_worlds, method=method)

    verdict, reason = kill_criterion(
        ceilings, min_generators=min_generators)

    for c in ceilings:
        if c.underpowered:
            warnings.append(
                f"{c.generator}: {c.n_worlds} world(s) is below the {min_worlds}-world "
                "replicate default; its threshold is UNDERPOWERED and it is "
                "excluded from the verdict count")
    if n_strategies_placebo:
        for generator in sorted(n_strategies_placebo):
            count = n_strategies_placebo[generator]
            if n_strategies_real is not None and count != n_strategies_real:
                warnings.append(
                    f"{generator}: the placebo search covered {count} strategies but "
                    f"the real search covered {n_strategies_real}. The ceiling is "
                    "only a ceiling when the same search produced both maxima")
    if len(placebo_maxima) < 5:
        warnings.append(
            f"only {len(placebo_maxima)} of the five design generators reported; "
            "the majority in the kill criterion is over what ran, not over what "
            "was designed")

    return CeilingReport(
        real_max=float(real_max),
        real_champion=real_champion,
        per_generator=tuple(ceilings),
        pooled=pooled,
        verdict=verdict,
        verdict_reason=reason,
        generators_cleared=tuple(sorted(c.generator for c in ceilings if c.clears)),
        generators_failed=tuple(sorted(
            c.generator for c in ceilings if not c.clears)),
        generators_underpowered=tuple(sorted(
            c.generator for c in ceilings if c.underpowered)),
        threshold_pct=threshold_pct,
        warnings=tuple(warnings),
    )


def search_maximum(fitness_by_strategy: Mapping[str, float]) -> tuple[str, float]:
    """The champion of one search: (strategy_id, fitness), ties to the lowest id.

    Deterministic by construction -- a ceiling built from a maximum that
    depended on dict ordering would not be reproducible, and reproducibility is
    the only thing that makes a placebo world worth building.
    """
    if not fitness_by_strategy:
        raise CeilingError("no strategies; there is no search maximum")
    best_id = None
    best = -math.inf
    for name in sorted(fitness_by_strategy):
        value = float(fitness_by_strategy[name])
        if math.isnan(value):
            raise CeilingError(f"strategy {name!r} has a NaN fitness")
        if value > best:
            best, best_id = value, name
    return best_id, best


def format_report(report: CeilingReport) -> str:
    """A plain-text ceiling table. Reporting only; it computes nothing new."""
    lines = [
        f"real maximum: {report.real_max:.6f}"
        + (f"  ({report.real_champion})" if report.real_champion else ""),
        f"threshold: {report.threshold_pct:g}th percentile of placebo maxima",
        "",
        f"{'generator':<10} {'worlds':>6} {'median':>10} {'threshold':>10} "
        f"{'max':>10} {'pct_rank':>9} {'p':>7}  verdict",
    ]
    for c in list(report.per_generator) + [report.pooled]:
        lines.append(
            f"{c.generator:<10} {c.n_worlds:>6} {c.placebo_median:>10.6f} "
            f"{c.placebo_threshold:>10.6f} {c.placebo_max:>10.6f} "
            f"{c.percentile_rank:>8.1f}% {c.exceedance_p:>7.4f}  "
            + ("clears" if c.clears else "BELOW")
            + ("  [UNDERPOWERED]" if c.underpowered else ""))
    lines.extend(["", f"VERDICT: {report.verdict}", report.verdict_reason])
    for w in report.warnings:
        lines.append(f"warning: {w}")
    lines.append("")
    lines.append("Nothing here is evidence. A cleared ceiling is permission to "
                 "keep building in the sandbox, never a bet.")
    return "\n".join(lines)
