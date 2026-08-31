"""The enumeration engine: selections as Python integer bitsets.

NOTHING IN THIS PACKAGE IS EVIDENCE. See registry.py's docstring and
docs/EVOLAB_DESIGN.md sections 11 and 15.

WHY BITSETS, AND WHY THEY ARE NOT A MICRO-OPTIMISATION
------------------------------------------------------
This environment has no numpy and no scipy -- stdlib only. Design section 12
turns that constraint into the design: because the space is ENUMERATED rather
than searched, every genome's selection is a fixed boolean combination of a
small, shared set of per-(feature, rung) predicates. So build those predicates
once per world as arbitrary-precision integers, and each genome's selection
becomes two or three integer `&`/`|` operations on ~4,800-bit numbers -- work
CPython does in C.

The alternative is evaluating ~5,000 genomes against ~4,800 games one decision
at a time: 24 million Python-level decisions per world, times 51 worlds. That
is the difference between minutes and milliseconds per world, and it is what
makes 50 placebo worlds affordable enough that the placebo ceiling -- the
lab's actual scientific product -- can be measured at all.

BIT INDEX IS GAME INDEX, AND THAT ORDER IS THE CALLER'S CONTRACT
----------------------------------------------------------------
Bit i is game i in the caller's own game ordering. Nothing here sorts, so the
caller must fix one chronological ordering per world and reuse it for every
mask and every value vector. Masks built against different orderings combine
into confident nonsense, which is why `sum_over_mask` refuses a mask with bits
set past the end of its value vector rather than silently ignoring them.

TWO MASKS PER (FEATURE, RUNG), NOT ONE
--------------------------------------
Design section 12 says "one bitset per (feature, threshold) pair". In contact
with the sign convention that turns out to be two: a signal that fires tells
you the magnitude cleared the rung, but the SIDE it points to depends on the
sign of the differential. So each pair yields an away-mask and a home-mask,
disjoint by construction. 6 features x 3 rungs x 2 sides = 36 masks per world,
still nothing.

FLOAT ACCUMULATION IS ORDERED
-----------------------------
`sum_over_mask` walks set bits from lowest index upward, always. Float
addition is not associative, so an unordered walk would make a fitness number
depend on iteration order; design section 4's determinism requirement reaches
down to here.
"""

from __future__ import annotations


class BitsetError(RuntimeError):
    """Raised when a mask and its universe cannot be reconciled."""


def mask_from_indices(indices) -> int:
    """The bitset with exactly `indices` set. Negative indices are refused.

    Refused rather than wrapped: Python's negative indexing would happily turn
    -1 into "the last game" in a value vector but into an invalid shift here,
    and a helper that means two different things by -1 is a bug generator.
    """
    mask = 0
    for i in indices:
        if not isinstance(i, int) or isinstance(i, bool) or i < 0:
            raise BitsetError(f"game index must be a non-negative int, got "
                              f"{i!r}")
        mask |= 1 << i
    return mask


def signal_masks(differentials, threshold, direction) -> tuple:
    """(away_mask, home_mask) for one (feature, rung) pair over one world.

    `differentials[i]` is away_<feature> - home_<feature> for game i, or None
    where either side was unmeasured. None never sets a bit in either mask:
    absence of a differential is absence of a signal, not a zero.

    A differential of exactly 0.0 also sets no bit even if the threshold were
    0, because at d == 0 neither side holds more of the feature and the
    mechanism says nothing -- the same rule registry.SignalSpec.side_for uses,
    kept identical here so the fast path and the readable path agree.
    """
    if direction not in (-1, 1):
        raise BitsetError(f"direction must be -1 or +1, got {direction!r}")
    if not threshold > 0:
        raise BitsetError(f"threshold must be > 0, got {threshold!r}")
    away = home = 0
    for i, d in enumerate(differentials):
        if d is None or d == 0 or abs(d) < threshold:
            continue
        if d * direction > 0:
            away |= 1 << i
        else:
            home |= 1 << i
    return away, home


def combine_and(masks) -> int:
    """Intersection. An empty collection is the EMPTY set, not the universe.

    The mathematical identity for an empty intersection is "everything", and
    returning it would let a genome whose signals all failed to build select
    every game in the world. Empty means empty here, deliberately.
    """
    masks = list(masks)
    if not masks:
        return 0
    out = masks[0]
    for m in masks[1:]:
        out &= m
    return out


def combine_or(masks) -> int:
    """Union."""
    out = 0
    for m in masks:
        out |= m
    return out


def combine_k_of_n(masks, k) -> int:
    """Games where at least `k` of `masks` are set.

    Implemented as the union over all k-subsets of their intersections. That
    is C(n, k) terms, which is at most C(3, 2) = 3 under MAX_SIGNALS -- so the
    naive formulation is also the fast one, and it is obviously correct, which
    matters more here than cleverness. It would be the wrong shape at n = 20.
    """
    masks = list(masks)
    if not isinstance(k, int) or isinstance(k, bool):
        raise BitsetError(f"k must be an int, got {k!r}")
    if not 1 <= k <= len(masks):
        raise BitsetError(
            f"k must be between 1 and the {len(masks)} mask(s) given, got {k}")
    from itertools import combinations
    out = 0
    for subset in combinations(masks, k):
        out |= combine_and(subset)
    return out


def iter_set_bits(mask):
    """Set bit indices, ascending. Yields nothing for 0.

    Isolating the lowest set bit with `mask & -mask` and clearing it keeps the
    cost proportional to the number of SELECTIONS (~500 per genome), not to
    the size of the universe (~4,800 games). Iterating range(universe) instead
    would be a 10x tax on every fitness sum.
    """
    if mask < 0:
        raise BitsetError("a selection mask cannot be negative")
    while mask:
        low = mask & -mask
        yield low.bit_length() - 1
        mask ^= low


def count_bits(mask) -> int:
    """Population count -- the selection count of a genome."""
    if mask < 0:
        raise BitsetError("a selection mask cannot be negative")
    return mask.bit_count()


def sum_over_mask(mask, values) -> float:
    """Sum of `values` over the games in `mask`, in ascending index order.

    Refuses a mask reaching past the end of `values`: that means the mask and
    the value vector were built against different game orderings, and the
    quiet failure -- dropping the out-of-range games -- would report a fitness
    over a silently different sample. None values are refused for the same
    reason: a missing per-game value must be resolved by the caller deciding
    what absence means, never by this function guessing it is zero.
    """
    if mask < 0:
        raise BitsetError("a selection mask cannot be negative")
    if mask.bit_length() > len(values):
        raise BitsetError(
            f"mask sets bit {mask.bit_length() - 1} but the value vector has "
            f"{len(values)} entries; the mask and the values were built "
            "against different game orderings")
    total = 0.0
    for i in iter_set_bits(mask):
        v = values[i]
        if v is None:
            raise BitsetError(
                f"values[{i}] is None for a selected game; decide what an "
                "absent value means before summing, do not let it read as 0")
        total += v
    return total


def universe_mask(n_games) -> int:
    """All `n_games` bits set -- the world's full universe."""
    if not isinstance(n_games, int) or isinstance(n_games, bool) \
            or n_games < 0:
        raise BitsetError(f"n_games must be a non-negative int, got "
                          f"{n_games!r}")
    return (1 << n_games) - 1


def build_signal_mask_table(registry, differentials_by_feature) -> dict:
    """{(feature, rung_index): (away_mask, home_mask)} for one world.

    The once-per-world precompute of design section 12. `differentials_by_
    feature` maps a registered feature name to that world's per-game
    differential vector, in the world's game order. A feature the caller did
    not supply is SKIPPED rather than filled with zeros -- a world that could
    not compute a feature has no signal there, and the difference between
    "absent" and "never fires" is the difference between an honest gap and a
    fabricated one.
    """
    table = {}
    for spec in registry.specs():
        diffs = differentials_by_feature.get(spec.feature)
        if diffs is None:
            continue
        for index in range(len(spec.ladder)):
            table[(spec.feature, index)] = signal_masks(
                diffs, spec.ladder[index], spec.direction)
    return table
