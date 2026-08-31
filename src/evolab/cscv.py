"""CSCV and the Probability of Backtest Overfitting -- Evolution Lab design section 8.

NOTHING THIS MODULE PRODUCES IS EVIDENCE. PBO is a property of a SEARCH over a
strategy set, not of a strategy: it answers "does picking the in-sample best
tell us anything about out-of-sample rank?", and its honest answer on a barren
space is 0.5. A low PBO is a necessary condition for taking a search seriously,
never a sufficient one, and it may not be reported at all until the
validator-validation tests in `tests/test_evolab_stats.py` pass.

THE METHOD (Bailey, Borwein, Lopez de Prado & Zhu)
--------------------------------------------------
1. Split the replay universe into S = 10 chronological blocks.
2. For each of the C(10, 5) = 252 balanced splits, take half the blocks as
   in-sample and their complement as out-of-sample.
3. Select the strategy with the best in-sample fitness; record its
   out-of-sample RANK among all strategies.
4. PBO = the fraction of splits where that rank lands below the median.

Both a split and its complement appear in the 252 -- that symmetry is the
"combinatorially symmetric" part, and it is why the statistic has no
preference for early or late data.

WHY THIS IS CHEAP
-----------------
Because the lab enumerates, per-strategy per-block fitness is computed ONCE.
Every one of the 252 splits is then table arithmetic over that matrix: a split's
out-of-sample sum is the strategy's total minus its in-sample sum, and the rank
of a single value needs one linear pass, not a sort. The statistics cost
nothing next to the replay, and this module is required to keep it that way --
it never touches a world, a game or a price.

DETERMINISM AND TIES, HANDLED EXPLICITLY
----------------------------------------
Strategies are processed in sorted id order, so no result can depend on the
order a dict happened to iterate. Ties are the interesting failure mode:

- In-sample selection ties are broken by the smallest strategy id, and the
  number of tied selections is reported.
- Out-of-sample rank uses MID-RANKS, so a tied group all receive the group's
  average rank.
- A strategy whose out-of-sample rank is exactly the median contributes 0.5 to
  the PBO count. This matters: if every strategy is identical, every rank is
  the midrank, and counting only strict inequality would report PBO = 0.0 --
  "no overfitting" -- from a table with no information in it at all. With the
  half-count convention such a table reports exactly 0.5, which is the truth.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from typing import Mapping, Sequence

DEFAULT_BLOCKS = 10


class CSCVError(ValueError):
    """Raised when a fitness table cannot support an honest CSCV."""


@dataclass(frozen=True)
class SplitOutcome:
    """One of the 252 splits, kept for the diagnostics and for the autopsy."""

    split_index: int
    in_sample_blocks: tuple[int, ...]
    selected: str
    selected_is_fitness: float
    selected_oos_fitness: float
    oos_rank: float             # mid-rank, 1 = worst, n_strategies = best
    relative_rank: float        # rank / (n + 1), in (0, 1)
    logit: float                # log(w / (1 - w)); < 0 means below median
    is_selection_tied: bool


@dataclass(frozen=True)
class CSCVResult:
    """The PBO and everything needed to argue with it."""

    pbo: float
    n_strategies: int
    n_blocks: int
    n_splits: int
    splits: tuple[SplitOutcome, ...]
    prob_oos_loss: float                    # fraction of splits with OOS <= 0
    performance_degradation: float | None   # OLS slope of OOS on IS fitness
    median_logit: float
    n_below_median: int
    n_at_median: int
    n_tied_selections: int
    degenerate: bool                        # every fitness value identical
    selection_counts: Mapping[str, int]

    @property
    def most_selected(self) -> str | None:
        if not self.selection_counts:
            return None
        return max(sorted(self.selection_counts), key=lambda k: self.selection_counts[k])


def cscv(fitness_table: Mapping[str, Sequence[float]], *,
         block_weights: Sequence[float] | None = None,
         tie_tolerance: float = 0.0) -> CSCVResult:
    """Run combinatorially symmetric cross-validation over a fitness table.

    `fitness_table` maps strategy id -> per-block fitness, one value per
    chronological block, higher is better. Every strategy must be scored on
    every block: a missing block would let a strategy be selected on evidence
    another strategy never faced.

    `block_weights` lets unequal blocks (different game counts) be aggregated
    honestly; the default is equal weight, which is right when blocks are cut
    to equal size.

    `tie_tolerance` is the absolute tolerance for calling two fitness values
    tied. The default is exact equality, which is what a table built by the
    same arithmetic for every strategy deserves; loosen it only with a stated
    reason.
    """
    names = sorted(fitness_table)
    n = len(names)
    if n < 2:
        raise CSCVError("CSCV needs at least 2 strategies to rank")

    rows = [list(fitness_table[k]) for k in names]
    s = len(rows[0])
    if s < 4 or s % 2 != 0:
        raise CSCVError(
            f"CSCV needs an even number of blocks (>= 4); got {s}")
    for name, row in zip(names, rows):
        if len(row) != s:
            raise CSCVError(
                f"strategy {name!r} has {len(row)} block fitnesses, expected {s}")
        for v in row:
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                raise CSCVError(f"strategy {name!r} has non-numeric fitness {v!r}")
            if math.isnan(v) or math.isinf(v):
                raise CSCVError(
                    f"strategy {name!r} has a non-finite fitness ({v!r}); "
                    "absent fitness must be resolved before CSCV, never coerced")

    if block_weights is None:
        weights = [1.0] * s
    else:
        weights = [float(w) for w in block_weights]
        if len(weights) != s:
            raise CSCVError("block_weights must have one weight per block")
        if any(w < 0 for w in weights) or sum(weights) <= 0:
            raise CSCVError("block_weights must be non-negative and not all zero")

    degenerate = all(
        abs(v - rows[0][0]) <= tie_tolerance for row in rows for v in row)

    weighted = [[w * v for w, v in zip(weights, row)] for row in rows]
    totals = [sum(row) for row in weighted]
    total_weight = sum(weights)

    half = s // 2
    splits: list[SplitOutcome] = []
    below = 0.0
    n_below = 0
    n_at = 0
    n_tied_selections = 0
    oos_losses = 0
    selection_counts: dict[str, int] = {name: 0 for name in names}
    is_values: list[float] = []
    oos_values: list[float] = []

    for split_index, is_blocks in enumerate(combinations(range(s), half)):
        is_weight = sum(weights[b] for b in is_blocks)
        oos_weight = total_weight - is_weight
        if is_weight <= 0 or oos_weight <= 0:
            raise CSCVError(
                "a split had zero weight on one side; block_weights must give "
                "every block positive weight for CSCV to be balanced")

        is_scores = []
        oos_scores = []
        for i in range(n):
            row = weighted[i]
            is_sum = 0.0
            for b in is_blocks:
                is_sum += row[b]
            is_scores.append(is_sum / is_weight)
            oos_scores.append((totals[i] - is_sum) / oos_weight)

        best_i = 0
        best_v = is_scores[0]
        tied = 0
        for i in range(1, n):
            v = is_scores[i]
            if v > best_v + tie_tolerance:
                best_v, best_i, tied = v, i, 0
            elif abs(v - best_v) <= tie_tolerance:
                tied += 1
        # names is sorted, so the first index wins a tie deterministically.
        selected = names[best_i]
        selection_counts[selected] += 1
        if tied:
            n_tied_selections += 1

        target = oos_scores[best_i]
        less = 0
        equal = 0
        for v in oos_scores:
            if v < target - tie_tolerance:
                less += 1
            elif abs(v - target) <= tie_tolerance:
                equal += 1
        # Mid-rank: 1 is worst, n is best; a tied group shares its mean rank.
        rank = less + (equal + 1) / 2.0
        w = rank / (n + 1.0)
        logit = math.log(w / (1.0 - w))

        median_rank = (n + 1) / 2.0
        if rank < median_rank - 1e-12:
            below += 1.0
            n_below += 1
        elif abs(rank - median_rank) <= 1e-12:
            below += 0.5
            n_at += 1

        if target <= 0.0:
            oos_losses += 1

        is_values.append(best_v)
        oos_values.append(target)
        splits.append(SplitOutcome(
            split_index=split_index,
            in_sample_blocks=tuple(is_blocks),
            selected=selected,
            selected_is_fitness=best_v,
            selected_oos_fitness=target,
            oos_rank=rank,
            relative_rank=w,
            logit=logit,
            is_selection_tied=bool(tied),
        ))

    n_splits = len(splits)
    logits = sorted(sp.logit for sp in splits)
    mid = n_splits // 2
    median_logit = (logits[mid] if n_splits % 2
                    else (logits[mid - 1] + logits[mid]) / 2.0)

    return CSCVResult(
        pbo=below / n_splits,
        n_strategies=n,
        n_blocks=s,
        n_splits=n_splits,
        splits=tuple(splits),
        prob_oos_loss=oos_losses / n_splits,
        performance_degradation=_ols_slope(is_values, oos_values),
        median_logit=median_logit,
        n_below_median=n_below,
        n_at_median=n_at,
        n_tied_selections=n_tied_selections,
        degenerate=degenerate,
        selection_counts=dict(selection_counts),
    )


def probability_of_backtest_overfitting(
        fitness_table: Mapping[str, Sequence[float]], **kwargs) -> float:
    """The PBO alone. Prefer `cscv()`; a bare PBO hides its own diagnostics."""
    return cscv(fitness_table, **kwargs).pbo


def _ols_slope(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Slope of the out-of-sample-on-in-sample line across splits.

    Bailey & Lopez de Prado's "performance degradation": a slope at or below
    zero says in-sample selection buys nothing out of sample, or costs.
    Returns None when the in-sample values carry no real variance to regress on.

    "No real variance" has to mean more than `sxx > 0`. Summing the same five
    block fitnesses in different orders gives answers that differ in the last
    bits, so a table of IDENTICAL strategies still produces a spread of about
    1e-18 across splits -- and regressing on that returns a confident-looking
    slope built entirely out of float non-associativity. That is precisely the
    spurious ranking signal this module is required not to invent, so a spread
    that small is treated as no spread at all.
    """
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    spread = max(xs) - min(xs)
    if spread <= 1e-9 * max(1.0, abs(mx)):
        return None
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / sxx


def chronological_blocks(n_items: int, n_blocks: int = DEFAULT_BLOCKS) -> list[tuple[int, int]]:
    """Cut `n_items` ordered items into `n_blocks` contiguous [start, end) blocks.

    Chronological and contiguous on purpose: shuffled blocks would let a split
    train on a week that surrounds its own test week, which is the leak CSCV
    exists to avoid. Remainders go to the earliest blocks, so block sizes
    differ by at most one and the last block is never a stub.
    """
    if n_blocks < 2:
        raise CSCVError("need at least 2 blocks")
    if n_items < n_blocks:
        raise CSCVError(
            f"cannot cut {n_items} items into {n_blocks} blocks; "
            "a block with no data cannot be scored")
    base, extra = divmod(n_items, n_blocks)
    out = []
    start = 0
    for i in range(n_blocks):
        size = base + (1 if i < extra else 0)
        out.append((start, start + size))
        start += size
    return out
