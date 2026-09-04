"""Decision dedup and Jaccard family clustering over a strategy population.

WHY THIS MODULE EXISTS
-----------------------
Once wagers are canonical (`wagers.py`), the question this program's owner
actually needs answered is: of N strategies making a combined total of D
decisions, how many of those decisions are the SAME wager, and how many
mechanically-distinct families does the population actually contain? See
docs/FACTORY_SCALE_DESIGN.md sections 1.4, 2, 3 for the full method and its
justification; this module is the implementation of that method only --
nothing here decides thresholds it does not already state and justify.

INPUT SHAPE
-----------
Every function here takes `selections: Mapping[str, frozenset[str] | set[str]]`
-- `{strategy_id: {wager_id, ...}}`. That is deliberately the smallest
sufficient shape: it does not require a `WagerStore`, a `SweepReport`, or any
other machinery, so `wagers.py`'s wager ids and `sweep.py`'s masks can both
feed this module through a thin adapter without this module knowing about
either. Building that adapter (turning a `WorldFitness.masks` bitmask into a
`{wager_id}` set) is the natural next slice once `sweep.py` persists masks
(see FACTORY_SCALE_DESIGN.md section 0) -- out of scope for this slice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

# Design section 2: a high, fixed bar for "this is mechanically the same
# trade" -- at most 1 in 5 combined decisions may differ. Fixed and named
# here, not swept per report, because a threshold a report author can tune
# is a threshold that can be tuned to manufacture apparent diversity.
FAMILY_THRESHOLD = 0.8


class OverlapError(RuntimeError):
    """Raised when overlap/clustering cannot be computed honestly."""


@dataclass(frozen=True)
class DedupStats:
    """Design section 1.4's dedup statistic for one strategy set."""

    n_strategies: int
    total_decisions: int
    unique_wagers: int

    @property
    def dedup_ratio(self) -> float:
        """unique_wagers / total_decisions; 1.0 means every decision was on a
        distinct wager (no overlap at all). Undefined (0.0) when there were
        no decisions -- an empty population has no ratio to report, and 0.0
        reads honestly as "nothing here" rather than raising for a legal,
        if uninteresting, input."""
        if self.total_decisions == 0:
            return 0.0
        return self.unique_wagers / self.total_decisions

    def to_dict(self) -> dict:
        return {
            "n_strategies": self.n_strategies,
            "total_decisions": self.total_decisions,
            "unique_wagers": self.unique_wagers,
            "dedup_ratio": self.dedup_ratio,
        }


def dedup_stats(selections: Mapping[str, "frozenset[str]"]) -> DedupStats:
    """Unique-vs-total decision counts across every strategy in `selections`."""
    total = sum(len(wagers) for wagers in selections.values())
    unique = set()
    for wagers in selections.values():
        unique |= set(wagers)
    return DedupStats(n_strategies=len(selections), total_decisions=total,
                      unique_wagers=len(unique))


def jaccard(a: "frozenset[str]", b: "frozenset[str]") -> float:
    """|a n b| / |a u b|. 1.0 for two identical non-empty sets, 0.0 if either
    is empty (two strategies that never bet cannot be said to overlap OR to
    differ -- 0.0 is the conservative "no evidence of similarity" answer,
    matching this module's general stance of never asserting a relationship
    the data does not support)."""
    a, b = set(a), set(b)
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def pairwise_jaccard(selections: Mapping[str, "frozenset[str]"]
                     ) -> dict[tuple[str, str], float]:
    """{(strategy_a, strategy_b): J} for every unordered pair, `a < b` by id
    (sorted iteration -- deterministic, per this codebase's general rule)."""
    ids = sorted(selections)
    out = {}
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            out[(a, b)] = jaccard(selections[a], selections[b])
    return out


def _find(parent: dict, x: str) -> str:
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _union(parent: dict, a: str, b: str) -> None:
    ra, rb = _find(parent, a), _find(parent, b)
    if ra != rb:
        parent[ra] = rb


def cluster_families(selections: Mapping[str, "frozenset[str]"], *,
                     threshold: float = FAMILY_THRESHOLD
                     ) -> list[list[str]]:
    """Single-linkage clusters of strategy ids: a family is a connected
    component of the graph "J(a, b) >= threshold" (design section 2).

    Returned as a list of sorted-id lists, the list itself sorted by
    (descending size, then by its first/smallest member id) so the result is
    deterministic and a report can print "largest family first" without a
    second sort.
    """
    ids = sorted(selections)
    parent = {i: i for i in ids}
    for (a, b), j in pairwise_jaccard(selections).items():
        if j >= threshold:
            _union(parent, a, b)
    groups: dict[str, list[str]] = {}
    for i in ids:
        root = _find(parent, i)
        groups.setdefault(root, []).append(i)
    families = [sorted(members) for members in groups.values()]
    families.sort(key=lambda fam: (-len(fam), fam[0]))
    return families


@dataclass(frozen=True)
class EffectiveN:
    """Design section 3's two effective-sample-size numbers. `credit` is a
    heuristic diminishing-returns discount, NOT a calibrated estimator --
    see FACTORY_SCALE_DESIGN.md section 3 before reporting it as if it were
    one."""

    n_families: int
    credit: float

    def to_dict(self) -> dict:
        return {"n_effective_families": self.n_families,
                "n_effective_credit": self.credit,
                "credit_is_heuristic_not_calibrated": True}


def effective_n(families: Sequence[Sequence[str]]) -> EffectiveN:
    """`N_effective_families` = family count; `N_effective_credit` =
    sum(1 + log2(size)) over families -- see design section 3 for why the
    family count is primary and the credit term is a secondary, explicitly
    heuristic discount, never a promotion gate."""
    import math
    credit = 0.0
    for fam in families:
        size = len(fam)
        if size <= 0:
            continue
        credit += 1.0 + math.log2(size)
    return EffectiveN(n_families=len(families), credit=credit)
