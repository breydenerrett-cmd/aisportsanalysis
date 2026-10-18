"""The statistics of the loop, pure and stdlib-only: a clustered paired mean, Student's t, the look
boundaries, and Benjamini-Hochberg.

WHY NOT A BOOTSTRAP HERE
------------------------
The verdict referee uses a date-clustered bootstrap (src/hounds/verdict.py) because a label wants an
interval. The loop wants a DECISION at pre-set looks, with an error rate it can state, so it uses the
closed-form cluster-robust variance of a ratio mean (the same clustering: whole slate dates) and
Student's t with D - 1 degrees of freedom (D = distinct dates). That is deterministic, instant, and
has a p-value to spend (docs/PREREG_LEARNING_LOOP.md section 6).

Student's t needs no scipy: the survival function is the regularised incomplete beta function,
evaluated with the standard continued fraction (Lentz). Pinned in tests against published values.
"""

from __future__ import annotations

import math
from functools import lru_cache
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence

from src.hounds.learning import rules

_TINY = 1e-300


# ---- Student's t ------------------------------------------------------------------------------

def _betacf(a: float, b: float, x: float, max_iter: int = 400, eps: float = 3e-15) -> float:
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = _TINY if abs(d) < _TINY else d
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = _TINY if abs(d) < _TINY else d
        c = 1.0 + aa / c
        c = _TINY if abs(c) < _TINY else c
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = _TINY if abs(d) < _TINY else d
        c = 1.0 + aa / c
        c = _TINY if abs(c) < _TINY else c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """The regularised incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_bt = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
             + a * math.log(x) + b * math.log1p(-x))
    bt = math.exp(ln_bt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_sf(t: float, df: float) -> float:
    """P(T > t) for Student's t with ``df`` degrees of freedom (one-sided upper tail)."""
    if df <= 0:
        raise ValueError("df must be positive")
    if math.isinf(t):
        return 0.0 if t > 0 else 1.0
    tail = 0.5 * betainc(df / 2.0, 0.5, df / (df + t * t))
    return tail if t >= 0 else 1.0 - tail


@lru_cache(maxsize=4096)
def t_quantile_upper(alpha: float, df: float) -> float:
    """The t with P(T > t) = alpha (alpha in (0, 0.5]), by bisection on ``t_sf``."""
    if not 0.0 < alpha <= 0.5:
        raise ValueError("alpha must be in (0, 0.5]")
    lo, hi = 0.0, 1.0
    while t_sf(hi, df) > alpha:
        hi *= 2.0
        if hi > 1e8:
            break
    for _ in range(90):
        mid = (lo + hi) / 2.0
        if t_sf(mid, df) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# ---- the clustered paired mean ------------------------------------------------------------------

@dataclass(frozen=True)
class PairedStats:
    n: int
    dates: int
    mean: Optional[float]
    se: Optional[float]
    t: Optional[float]
    df: Optional[int]
    p_better: Optional[float]      # one-sided: challenger better (mean > 0)
    p_worse: Optional[float]       # one-sided: challenger worse (mean < 0)

    def to_json(self) -> dict:
        return {"n": self.n, "dates": self.dates, "mean": _r(self.mean), "se": _r(self.se),
                "t": _r(self.t), "df": self.df, "p_better": _r(self.p_better, 6),
                "p_worse": _r(self.p_worse, 6)}


def _r(x, nd: int = 4):
    return None if x is None else round(x, nd)


def clustered_paired(slots: Iterable[tuple]) -> PairedStats:
    """``slots`` = ``(date, difference)`` pairs. Mean, cluster-robust SE (clusters = dates), t, p.

    Fewer than two dates, or a zero standard error, gives ``None`` for everything that needs a
    variance: no interval is better than a fake one, and a p-value of None never crosses a boundary.
    """
    by_date: dict = {}
    for when, diff in slots:
        cell = by_date.setdefault(str(when)[:10], [0.0, 0])
        cell[0] += float(diff)
        cell[1] += 1
    n = sum(c[1] for c in by_date.values())
    d = len(by_date)
    if n == 0:
        return PairedStats(0, 0, None, None, None, None, None, None)
    mean = sum(c[0] for c in by_date.values()) / n
    if d < 2:
        return PairedStats(n, d, mean, None, None, None, None, None)
    ss = sum((c[0] - mean * c[1]) ** 2 for c in by_date.values())
    var = (d / (d - 1.0)) * ss / (n * n)
    if var <= 0.0:
        return PairedStats(n, d, mean, 0.0, None, d - 1, None, None)
    se = math.sqrt(var)
    t = mean / se
    df = d - 1
    return PairedStats(n, d, mean, se, t, df, t_sf(t, df), t_sf(-t, df))


def bound(stats: PairedStats, alpha: float, side: str) -> Optional[float]:
    """The one-sided (1 - alpha) bound of the mean: ``lower`` or ``upper``."""
    if stats.mean is None or stats.se is None or stats.df is None:
        return None
    q = t_quantile_upper(alpha, stats.df)
    return stats.mean - q * stats.se if side == "lower" else stats.mean + q * stats.se


# ---- looks -----------------------------------------------------------------------------------------

@dataclass(frozen=True)
class LookResult:
    look_no: int                   # 1-based
    n_target: int
    alpha: float
    stats: PairedStats
    lower: Optional[float]
    upper: Optional[float]
    crossed_better: bool           # p_better <= alpha and mean > 0 (stage 1, before the volume floor)
    crossed_worse: bool            # p_worse <= alpha and mean < 0

    def to_json(self) -> dict:
        out = {"look_no": self.look_no, "n_target": self.n_target, "alpha": self.alpha,
               "lower": _r(self.lower), "upper": _r(self.upper),
               "crossed_better": self.crossed_better, "crossed_worse": self.crossed_worse}
        out.update(self.stats.to_json())
        return out


def look_sizes(analyst: bool = False) -> tuple:
    return rules.ANALYST_LOOKS if analyst else rules.LOOKS


def evaluate_look(look_no: int, sample: Sequence[tuple], *, analyst: bool = False) -> LookResult:
    """The result of look ``look_no`` (1-based) over its sample: the first ``n_target`` slots.

    ``sample`` must already be exactly the look's first n_target slots; the caller (the referee)
    owns the ordering."""
    sizes = look_sizes(analyst)
    if not 1 <= look_no <= len(sizes):
        raise ValueError(f"look_no must be 1..{len(sizes)}")
    alpha = rules.ALPHA_SPEND[look_no - 1]
    stats = clustered_paired(sample)
    lower = bound(stats, alpha, "lower")
    upper = bound(stats, alpha, "upper")
    better = (stats.p_better is not None and stats.p_better <= alpha
              and stats.mean is not None and stats.mean > 0)
    worse = (stats.p_worse is not None and stats.p_worse <= alpha
             and stats.mean is not None and stats.mean < 0)
    return LookResult(look_no, sizes[look_no - 1], alpha, stats, lower, upper, better, worse)


def look_reached(n_slots: int, dates: int, look_no: int, *, analyst: bool = False) -> bool:
    """Has the sample grown to look ``look_no``? It needs the size AND the dates (prereg section 6)."""
    return n_slots >= look_sizes(analyst)[look_no - 1] and dates >= rules.MIN_DATES_PER_LOOK


# ---- Benjamini-Hochberg --------------------------------------------------------------------------------

def benjamini_hochberg(p_adj: Mapping, q: float = rules.BH_Q) -> list:
    """Ids rejected by BH at level ``q`` over the family ``{id: adjusted p}``, in ascending p order.

    Sort ascending; find the largest i (1-based) with p_(i) <= i * q / m; reject the i smallest.
    Ties are broken by id so the answer never depends on dict order."""
    items = sorted(((float(p), str(k)) for k, p in p_adj.items()))
    m = len(items)
    cut = 0
    for i, (p, _k) in enumerate(items, start=1):
        if p <= i * q / m:
            cut = i
    return [k for _p, k in items[:cut]]


def adjusted_p(p: Optional[float]) -> Optional[float]:
    """Bonferroni over the planned looks: ``min(1, 5 p)`` (prereg section 7)."""
    if p is None:
        return None
    return min(1.0, rules.P_ADJ_FACTOR * p)
