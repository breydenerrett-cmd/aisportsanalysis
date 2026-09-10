"""Platt scaling, fit walk-forward. Two parameters, no library.

WHY THIS EXISTS
---------------
`src.analysis.strength` orders games correctly and states its confidence
wrongly. Measured over 1,896 games of 2026, the raw model's own calibration
table read:

    it said 36%  ->  the home team won 45% of the time
    it said 55%  ->  53%
    it said 64%  ->  57%
    it said 73%  ->  60%

Monotone, so the ORDERING carries information; compressed, so the NUMBERS do
not. A model like that is dangerous in exactly one specific way, and it is
the way that matters for this product: the games where it disagrees most
loudly with the market are the games where it is most wrong. Ranking picks by
raw disagreement would systematically select the model's own errors.

Platt scaling fixes the scale without touching the ordering: fit
`p = sigmoid(a + b * logit(p_raw))` and the ranking is unchanged while the
confidence becomes something a person can act on. `b < 1` is the model being
told to be less sure than it is.

WALK-FORWARD, NOT FITTED ONCE
-----------------------------
The store holds one season, so there is no earlier season to fit on. Fitting
on all of 2026 and then reporting 2026 accuracy would be scoring a model on
its own training set -- the exact error this repo has spent weeks building
audits against.

So the fit expands: to calibrate a game on date D, `WalkForward` uses only
games that finished strictly before D. Every reported number is therefore a
genuine out-of-sample prediction, and the procedure that produces tonight's
number is the identical procedure that produced every number in the
backtest -- no branch, no special case, no retrospective refit.

Before `MIN_FIT_GAMES` have accumulated there is nothing to fit on, and the
answer is the running base rate rather than a two-parameter fit on fifty
games. A calibration fit on noise is worse than no calibration, because it
looks like one.

Pure. stdlib only.
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

# Below this many completed games there is not enough to estimate two
# parameters against, and the honest answer is the base rate. 300 is roughly
# a fortnight of a full major-league schedule.
MIN_FIT_GAMES = 300

# IRLS settles in a handful of steps for a two-parameter logistic; the cap is
# a runaway guard, not a tuning knob.
MAX_ITERATIONS = 50
CONVERGENCE = 1e-9

# Guards so a probability of exactly 0 or 1 (which `logit` cannot take, and
# which no honest model should produce) can never crash a page render.
EPS = 1e-6


class Calibration:
    """A fitted `(a, b)` and the sample it came from."""

    __slots__ = ("a", "b", "n", "base_rate")

    def __init__(self, a: float, b: float, n: int, base_rate: float):
        self.a, self.b, self.n, self.base_rate = a, b, n, base_rate

    def apply(self, p_raw: float) -> float:
        if self.n < MIN_FIT_GAMES:
            return self.base_rate
        return _sigmoid(self.a + self.b * _logit(p_raw))

    def to_dict(self) -> dict:
        return {"a": round(self.a, 6), "b": round(self.b, 6), "n": self.n,
                "base_rate": round(self.base_rate, 6),
                "fitted": self.n >= MIN_FIT_GAMES}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"Calibration(a={self.a:.4f}, b={self.b:.4f}, n={self.n}, "
                f"fitted={self.n >= MIN_FIT_GAMES})")


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _logit(p: float) -> float:
    p = min(max(float(p), EPS), 1.0 - EPS)
    return math.log(p / (1.0 - p))


def fit(pairs: Sequence) -> Calibration:
    """Fit `(a, b)` on `[(p_raw, y), ...]` by iteratively reweighted least
    squares. Two parameters, so the normal equations are a 2x2 solve.

    Returns an unfitted `Calibration` carrying the base rate when there is
    too little to fit on, or when the design is degenerate (every raw
    probability identical -- which happens on a slate where the model
    refused every game and fell back to a constant).
    """
    rows = [(float(p), int(y)) for p, y in pairs
            if p is not None and y is not None]
    n = len(rows)
    base = (sum(y for _, y in rows) / n) if n else 0.5
    if n < MIN_FIT_GAMES:
        return Calibration(0.0, 1.0, n, base)

    xs = [_logit(p) for p, _ in rows]
    ys = [float(y) for _, y in rows]
    if max(xs) - min(xs) < 1e-9:
        return Calibration(0.0, 1.0, n, base)

    a, b = 0.0, 1.0
    for _ in range(MAX_ITERATIONS):
        s00 = s01 = s11 = g0 = g1 = 0.0
        for x, y in zip(xs, ys):
            mu = _sigmoid(a + b * x)
            w = max(mu * (1.0 - mu), 1e-12)
            r = y - mu
            g0 += r
            g1 += r * x
            s00 += w
            s01 += w * x
            s11 += w * x * x
        det = s00 * s11 - s01 * s01
        if abs(det) < 1e-15:
            break
        da = (s11 * g0 - s01 * g1) / det
        db = (s00 * g1 - s01 * g0) / det
        a += da
        b += db
        if abs(da) < CONVERGENCE and abs(db) < CONVERGENCE:
            break
    return Calibration(a, b, n, base)


class WalkForward:
    """Fit-on-the-past calibration, refit at most once per date.

    Feed it `(date, p_raw, y)` as games finish, in any order; ask it for the
    calibration standing on a date and it fits on everything strictly
    earlier. The refit is cached per date because IRLS over a season costs
    real time and a slate asks the same question fifteen times.
    """

    def __init__(self):
        self._rows = []          # (date, p_raw, y), kept sorted on read
        self._cache = {}
        self._sorted = True

    def add(self, date: str, p_raw: float, y: int) -> None:
        if p_raw is None or y is None:
            return
        self._rows.append((str(date), float(p_raw), int(y)))
        self._sorted = False
        self._cache.clear()

    def calibration_for(self, date: str) -> Calibration:
        key = str(date)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        if not self._sorted:
            self._rows.sort(key=lambda r: r[0])
            self._sorted = True
        past = [(p, y) for d, p, y in self._rows if d < key]
        cal = fit(past)
        self._cache[key] = cal
        return cal

    def apply(self, date: str, p_raw: float) -> float:
        return self.calibration_for(date).apply(p_raw)

    def __len__(self) -> int:  # pragma: no cover - introspection aid
        return len(self._rows)


def brier(pairs) -> Optional[float]:
    rows = list(pairs)
    if not rows:
        return None
    return sum((p - y) ** 2 for p, y in rows) / len(rows)
