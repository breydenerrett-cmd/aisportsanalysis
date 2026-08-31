"""Hansen's Superior Predictive Ability test -- Evolution Lab design section 8.

NOTHING THIS MODULE PRODUCES IS EVIDENCE. An SPA p-value computed inside the
lab is a statement about a search over a strategy set in a sandbox; it cannot
promote anything, and it is not a bet.

WHY THIS EXISTS ALONGSIDE THE PLACEBO CEILING
---------------------------------------------
The placebo ceiling and this test answer the same question by different roads.

- The ceiling is empirical: run the WHOLE search -- enumeration, gates,
  selection, stopping rules -- on worlds known to contain no edge, and see how
  high the search climbs anyway.
- SPA is analytic: hold the strategy set fixed, ask whether the best observed
  mean differential could plausibly have come from a universe where no
  strategy beats the benchmark, with the multiplicity of the whole set priced
  in and the dependence between strategies preserved by resampling them
  together.

**They should broadly agree. If they disagree, one of them has a bug, and that
is exactly why both are run.** A small SPA p-value alongside a real maximum
buried inside the placebo distribution means either the placebo worlds are
easier than reality (the ceiling is understated -- see `placebo.py`) or the
differential series handed to SPA is not the series the search actually
maximised. Neither is a discovery. `cross_check()` below names the mismatch
rather than letting a reader pick the friendlier number.

THE TEST (Hansen 2005)
----------------------
Given per-period differentials d_{k,t} = strategy k's performance minus the
benchmark's at period t, testing H0: max_k E[d_k] <= 0,

    T = max( 0, max_k sqrt(n) * dbar_k / omega_k )

with omega_k the stationary-bootstrap standard deviation of sqrt(n)*dbar_k.
The null distribution comes from resampling the periods -- the SAME resample
for every strategy, which is what preserves the cross-sectional dependence
that makes the multiplicity correction honest -- and recentering by g_k:

    consistent : g_k = dbar_k if sqrt(n)*dbar_k/omega_k >= -sqrt(2*log log n) else 0
    lower      : g_k = max(dbar_k, 0)      -> a lower bound on the p-value
    upper      : g_k = dbar_k              -> an upper bound on the p-value

The consistent variant is the one to quote; the bounds are reported with it
because a gap between them says the answer depends on how the bad strategies
are treated, which a single number would hide.

The p-value is (1 + exceedances) / (1 + n_bootstrap), so its floor is
1/(n_bootstrap + 1). A finite bootstrap cannot earn a p-value of zero, and a
report that shows one is describing its own bootstrap size.

A PERIOD IS A GAME-DAY
----------------------
Differentials must be aggregated to game-days before they arrive here, exactly
as section 6 requires for every other uncertainty in this project. Feeding
per-selection rows would treat same-day selections as independent draws and
shrink every standard error that depends on them.

COST
----
O(n_bootstrap * n_periods * n_strategies / mean_block_length) with the prefix
sum trick below, in pure stdlib Python. That is fine for hundreds of
strategies and gets slow for thousands; lower `n_bootstrap` deliberately and
record it, and never trim the strategy set to speed it up -- the whole point of
SPA is that the full set is priced in. A pre-screened universe returns a
p-value for a search that was not run.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Mapping, Sequence

from src.evolab.placebo import stationary_bootstrap_blocks

# Below this, a differential series is treated as having no variance at all.
_OMEGA_FLOOR = 1e-12

VARIANTS = ("consistent", "lower", "upper")


class SPAError(ValueError):
    """Raised when an SPA test cannot be run honestly."""


@dataclass(frozen=True)
class SPAResult:
    """Hansen's SPA on one strategy set."""

    statistic: float
    p_value: float                  # the consistent variant -- the one to quote
    p_lower: float
    p_upper: float
    variant: str
    n_periods: int
    n_strategies: int
    n_bootstrap: int
    block_length: float
    seed: int
    best_strategy: str | None
    best_studentized: float
    means: Mapping[str, float]
    omegas: Mapping[str, float]
    studentized: Mapping[str, float]
    inactive: tuple[str, ...]       # zero-variance, zero-mean series

    @property
    def rejects(self) -> bool:
        """Convenience only. A rejection here is a hypothesis, not a finding."""
        return self.p_value < 0.05


def spa_test(differentials: Mapping[str, Sequence[float]], *,
             seed: int,
             block_length: float = 7.0,
             n_bootstrap: int = 1000,
             variant: str = "consistent") -> SPAResult:
    """Run Hansen's SPA over per-period, per-strategy performance differentials.

    `differentials[k][t]` is strategy k's performance minus the benchmark's in
    period t (a game-day). Higher is better. Every strategy must be scored on
    every period -- an absent period is not a zero, and coercing it to one
    would make a strategy that sat out look identical to the benchmark on days
    it never faced.

    The bootstrap is drawn twice from the same seed: once to estimate omega,
    once to build the null distribution. Regenerating rather than storing keeps
    memory at O(n + strategies) and makes the two passes provably identical.
    """
    if variant not in VARIANTS:
        raise SPAError(f"unknown variant {variant!r}; known: {', '.join(VARIANTS)}")

    names = sorted(differentials)
    if not names:
        raise SPAError("SPA needs at least one strategy")
    series = [list(differentials[k]) for k in names]
    n = len(series[0])
    if n < 8:
        raise SPAError(
            f"SPA needs a meaningful number of periods; got {n}. A bootstrap "
            "over a handful of game-days reports precision it does not have")
    for name, row in zip(names, series):
        if len(row) != n:
            raise SPAError(
                f"strategy {name!r} has {len(row)} periods, expected {n}")
        for v in row:
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                raise SPAError(f"strategy {name!r} has non-numeric value {v!r}")
            if math.isnan(v) or math.isinf(v):
                raise SPAError(
                    f"strategy {name!r} has a non-finite differential ({v!r}); "
                    "absence must be resolved before the test, never coerced")
    if n_bootstrap < 100:
        raise SPAError("n_bootstrap below 100 cannot resolve a p-value usefully")

    n_strategies = len(names)
    root_n = math.sqrt(n)
    means = [sum(row) / n for row in series]

    # Prefix sums: a bootstrap block's sum is then two lookups instead of a
    # loop over its members. Same draw, less arithmetic.
    prefix = [_prefix_sums(row) for row in series]

    # --- pass 1: omega, the stationary-bootstrap sd of sqrt(n) * dbar* -------
    rng = random.Random(seed)
    sq = [0.0] * n_strategies
    for _ in range(n_bootstrap):
        blocks = stationary_bootstrap_blocks(n, block_length, rng)
        for k in range(n_strategies):
            boot_mean = _block_sum(prefix[k], n, blocks) / n
            diff = boot_mean - means[k]
            sq[k] += diff * diff
    omegas = [math.sqrt(n * (s / n_bootstrap)) for s in sq]

    active = []
    inactive = []
    for k, name in enumerate(names):
        if omegas[k] > _OMEGA_FLOOR:
            active.append(k)
            continue
        if abs(means[k]) > _OMEGA_FLOOR:
            raise SPAError(
                f"strategy {name!r} has a constant non-zero differential "
                f"(mean {means[k]!r}, zero bootstrap variance). That is a "
                "riskless gain against the benchmark, which in this domain "
                "means a data or alignment bug, not an edge")
        inactive.append(name)

    studentized = [
        (root_n * means[k] / omegas[k]) if omegas[k] > _OMEGA_FLOOR else 0.0
        for k in range(n_strategies)
    ]
    statistic = max([0.0] + [studentized[k] for k in active])
    best_k = max(active, key=lambda k: (studentized[k], -k)) if active else None

    # --- recentering ---------------------------------------------------------
    threshold = math.sqrt(2.0 * math.log(math.log(n))) if n >= 3 else 0.0
    g_consistent = [
        means[k] if studentized[k] >= -threshold else 0.0
        for k in range(n_strategies)
    ]
    g_lower = [max(means[k], 0.0) for k in range(n_strategies)]
    g_upper = list(means)

    # --- pass 2: the null distribution, same seed, same resamples ------------
    rng = random.Random(seed)
    exceed = {"consistent": 0, "lower": 0, "upper": 0}
    for _ in range(n_bootstrap):
        blocks = stationary_bootstrap_blocks(n, block_length, rng)
        best = {"consistent": 0.0, "lower": 0.0, "upper": 0.0}
        for k in active:
            boot_mean = _block_sum(prefix[k], n, blocks) / n
            scale = root_n / omegas[k]
            for key, centre in (("consistent", g_consistent[k]),
                                ("lower", g_lower[k]),
                                ("upper", g_upper[k])):
                z = (boot_mean - centre) * scale
                if z > best[key]:
                    best[key] = z
        for key in exceed:
            if best[key] > statistic:
                exceed[key] += 1

    # (1 + exceedances) / (1 + B): the conservative Monte-Carlo convention, and
    # the same one `ceiling.py` uses for its exceedance p. It never reports a
    # p-value of exactly zero, which a finite bootstrap has not earned -- the
    # floor is 1/(B+1) and that is a statement about B, not about the market.
    p = {key: (1 + exceed[key]) / (1 + n_bootstrap) for key in exceed}

    return SPAResult(
        statistic=statistic,
        p_value=p[variant],
        p_lower=p["lower"],
        p_upper=p["upper"],
        variant=variant,
        n_periods=n,
        n_strategies=n_strategies,
        n_bootstrap=n_bootstrap,
        block_length=float(block_length),
        seed=seed,
        best_strategy=names[best_k] if best_k is not None else None,
        best_studentized=statistic,
        means={names[k]: means[k] for k in range(n_strategies)},
        omegas={names[k]: omegas[k] for k in range(n_strategies)},
        studentized={names[k]: studentized[k] for k in range(n_strategies)},
        inactive=tuple(inactive),
    )


def _prefix_sums(row: Sequence[float]) -> list[float]:
    out = [0.0]
    total = 0.0
    for v in row:
        total += v
        out.append(total)
    return out


def _block_sum(prefix: Sequence[float], n: int,
               blocks: Sequence[tuple[int, int]]) -> float:
    """Sum a stationary-bootstrap resample using prefix sums, wraps included."""
    total = 0.0
    full = prefix[n]
    for start, run in blocks:
        end = start + run
        if end <= n:
            total += prefix[end] - prefix[start]
            continue
        total += full - prefix[start]
        wraps, rest = divmod(end - n, n)
        total += wraps * full + prefix[rest]
    return total


def differentials_from_returns(
        returns: Mapping[str, Sequence[float]],
        benchmark: Sequence[float] | float = 0.0) -> dict[str, list[float]]:
    """Strategy-minus-benchmark per period.

    The default benchmark is 0.0 per period: "do not bet". Betting nothing
    costs nothing, so a strategy must beat zero before any comparison to a
    cleverer benchmark is worth making.
    """
    names = sorted(returns)
    if not names:
        raise SPAError("no strategies")
    n = len(returns[names[0]])
    if isinstance(benchmark, (int, float)):
        bench = [float(benchmark)] * n
    else:
        bench = [float(v) for v in benchmark]
    if len(bench) != n:
        raise SPAError("benchmark must have one value per period")
    out = {}
    for name in names:
        row = list(returns[name])
        if len(row) != n:
            raise SPAError(f"strategy {name!r} has {len(row)} periods, expected {n}")
        out[name] = [a - b for a, b in zip(row, bench)]
    return out


def cross_check(spa_result: SPAResult, clears_ceiling: bool,
                alpha: float = 0.05) -> tuple[str, str]:
    """Compare the analytic verdict with the empirical placebo ceiling.

    Returns (status, explanation) with status in {AGREE_NULL, AGREE_SIGNAL,
    DISAGREE}. A DISAGREE is a bug report, not a finding: the two procedures
    test the same claim over the same strategy set, so a split verdict means
    one of them is wrong, and neither number may be quoted until it is found.
    """
    rejects = spa_result.p_value < alpha
    if rejects and clears_ceiling:
        return ("AGREE_SIGNAL",
                f"SPA p={spa_result.p_value:.4f} < {alpha} and the real maximum "
                "clears the placebo ceiling. Both procedures say the same thing; "
                "neither makes it evidence.")
    if not rejects and not clears_ceiling:
        return ("AGREE_NULL",
                f"SPA p={spa_result.p_value:.4f} >= {alpha} and the real maximum "
                "sits inside the placebo distribution. Both procedures agree "
                "there is nothing here.")
    which = ("SPA rejects but the real maximum does not clear the placebo ceiling"
             if rejects else
             "the real maximum clears the placebo ceiling but SPA does not reject")
    return ("DISAGREE",
            f"{which} (p={spa_result.p_value:.4f}, bounds "
            f"[{spa_result.p_lower:.4f}, {spa_result.p_upper:.4f}]). One of the "
            "two is wrong: either the placebo worlds are easier than reality, or "
            "the differential series is not the series the search maximised. "
            "Find the bug before quoting either number.")
