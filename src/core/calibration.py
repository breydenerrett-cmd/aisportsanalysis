"""Calibration metrics: does a stated probability mean what it says?

WHY THIS MODULE EXISTS
----------------------
Accuracy and calibration are different properties, and betting cares about the
second one.

A model that ranks games correctly but says "70%" when the true rate is 55% is
ACCURATE and BADLY CALIBRATED. It will find edge everywhere, because it is
comparing an inflated probability against an honest market price. It will bet
constantly and lose steadily.

Calibration asks a narrower question: of all the times this model said 60%, did
the thing happen about 60% of the time? That is the only property that makes a
model probability comparable to a market price.

These metrics are built BEFORE any model is fitted, on purpose. Building the
scoreboard before the game is what stops the goalposts from moving later.

All functions are pure, stdlib-only, and take (predictions, outcomes) where
predictions are probabilities in (0, 1) and outcomes are 0/1 integers.
"""

from __future__ import annotations

import math

# Log loss is unbounded as p approaches 0 or 1. Clamp so one confident miss
# cannot dominate the entire metric with an infinity.
_LOG_LOSS_EPSILON = 1e-15


class CalibrationError(ValueError):
    """Raised when predictions and outcomes are not a usable pair."""


# ---------------------------------------------------------------------------
# Scalar scores
# ---------------------------------------------------------------------------

def brier_score(predictions, outcomes) -> float:
    """Mean squared error between predicted probability and outcome.

    Range 0 to 1, lower is better. A model that always says 0.5 scores 0.25 on
    a balanced set, which is the number to beat before claiming anything.

    Brier is a "proper scoring rule": it is minimized by reporting your true
    belief, so it cannot be gamed by shading predictions toward the extremes.
    """
    preds, obs = _validate_pair(predictions, outcomes)
    return sum((p - o) ** 2 for p, o in zip(preds, obs)) / len(preds)


def log_loss(predictions, outcomes) -> float:
    """Negative log likelihood. Lower is better; 0 is perfect.

    Punishes confident mistakes far more harshly than Brier does, which is the
    right bias for betting -- a confident wrong probability is exactly what
    empties a bankroll.

    This is the metric to use when comparing the model against the de-vigged
    market. If the model cannot beat the market's log loss, it has no edge, and
    no amount of ROI in a small sample changes that.
    """
    preds, obs = _validate_pair(predictions, outcomes)
    total = 0.0
    for p, o in zip(preds, obs):
        p = min(max(p, _LOG_LOSS_EPSILON), 1.0 - _LOG_LOSS_EPSILON)
        total += -(o * math.log(p) + (1 - o) * math.log(1.0 - p))
    return total / len(preds)


def expected_calibration_error(predictions, outcomes, bins: int = 10) -> float:
    """Average gap between predicted and observed rates, weighted by bin size.

    0.0 means perfectly calibrated. 0.05 means the model is off by about 5
    percentage points on average -- which, at typical betting margins, is more
    than enough to erase any real edge.
    """
    curve = reliability_curve(predictions, outcomes, bins=bins)
    total = sum(b["count"] for b in curve)
    if total == 0:
        raise CalibrationError("no predictions to score")
    return sum(b["count"] * abs(b["mean_predicted"] - b["observed_rate"])
               for b in curve) / total


def max_calibration_error(predictions, outcomes, bins: int = 10) -> float:
    """Worst per-bin calibration gap among bins that hold any predictions.

    Useful because a model can look fine on average while being badly wrong in
    one specific probability band -- often the high-confidence band, which is
    where the largest stakes go.
    """
    curve = reliability_curve(predictions, outcomes, bins=bins)
    gaps = [abs(b["mean_predicted"] - b["observed_rate"])
            for b in curve if b["count"] > 0]
    if not gaps:
        raise CalibrationError("no populated bins to score")
    return max(gaps)


# ---------------------------------------------------------------------------
# Reliability curve
# ---------------------------------------------------------------------------

def reliability_curve(predictions, outcomes, bins: int = 10):
    """Bucket predictions and compare predicted rate to observed rate.

    Returns a list of dicts, one per bin, each with:
        lower, upper      -- the bin's probability range
        count             -- how many predictions landed in it
        mean_predicted    -- average predicted probability in the bin
        observed_rate     -- fraction that actually happened
        gap               -- observed minus predicted (signed)

    A well-calibrated model produces observed_rate close to mean_predicted in
    every populated bin. Consistently negative gaps mean overconfidence, which
    is the failure mode that manufactures phantom edge.

    Empty bins are returned with count 0 rather than dropped, so the shape of
    the curve is stable across runs and comparable between models.
    """
    preds, obs = _validate_pair(predictions, outcomes)
    if not isinstance(bins, int) or bins < 1:
        raise CalibrationError(f"bins must be a positive integer, got {bins!r}")

    buckets = [{"lower": i / bins, "upper": (i + 1) / bins,
                "_sum_pred": 0.0, "_sum_obs": 0, "count": 0}
               for i in range(bins)]

    for p, o in zip(preds, obs):
        # The top bin is closed on the right so p == 1.0 has somewhere to go.
        idx = min(int(p * bins), bins - 1)
        b = buckets[idx]
        b["_sum_pred"] += p
        b["_sum_obs"] += o
        b["count"] += 1

    curve = []
    for b in buckets:
        n = b["count"]
        mean_pred = b["_sum_pred"] / n if n else 0.0
        observed = b["_sum_obs"] / n if n else 0.0
        curve.append({
            "lower": b["lower"],
            "upper": b["upper"],
            "count": n,
            "mean_predicted": mean_pred,
            "observed_rate": observed,
            "gap": observed - mean_pred,
        })
    return curve


def reliability_curve_equal_count(predictions, outcomes, bins: int = 10):
    """Reliability curve with equal-COUNT (quantile) bins instead of
    equal-WIDTH ones -- docs/PREREG_CALIBRATED_PROBABILITY.md §4's second
    mandated scheme.

    `reliability_curve` fixes the probability range each bin covers
    ([0, 0.1), [0.1, 0.2), ...), so a market whose predictions concentrate
    in a narrow band (MLB moneyline consensus sits mostly in 0.30-0.70)
    leaves most fixed-width bins empty and crowds all the real signal into
    a few. This scheme instead sorts predictions and splits them into
    `bins` groups of as-equal-as-possible size, so every bin's boundaries
    move with the sample instead of the sample being cut against fixed
    boundaries. Reported ALONGSIDE `reliability_curve`, never instead of it
    -- the two disagreeing is itself diagnostic (§4).

    Returns the same per-bin shape `reliability_curve` does (`lower`,
    `upper`, `count`, `mean_predicted`, `observed_rate`, `gap`), so
    `format_reliability_curve` renders either. `lower`/`upper` here are the
    bin's own observed prediction range, not a fixed fraction of [0, 1] --
    ties at a bin boundary stay together in the lower-indexed bin (a stable
    sort by prediction, sliced by count) rather than being split.
    """
    preds, obs = _validate_pair(predictions, outcomes)
    if not isinstance(bins, int) or bins < 1:
        raise CalibrationError(f"bins must be a positive integer, got {bins!r}")
    n = len(preds)
    if n < bins:
        bins = n  # never split emptier than one prediction per bin

    order = sorted(range(n), key=lambda i: preds[i])
    # Distribute n items into `bins` groups whose sizes differ by at most
    # one -- the standard "as equal as possible" quantile split, so an n not
    # evenly divisible by bins never silently starves the last bin.
    base, extra = divmod(n, bins)
    curve = []
    start = 0
    for b in range(bins):
        size = base + (1 if b < extra else 0)
        idxs = order[start:start + size]
        start += size
        group_preds = [preds[i] for i in idxs]
        group_obs = [obs[i] for i in idxs]
        mean_pred = sum(group_preds) / len(group_preds)
        observed = sum(group_obs) / len(group_obs)
        curve.append({
            "lower": min(group_preds),
            "upper": max(group_preds),
            "count": len(idxs),
            "mean_predicted": mean_pred,
            "observed_rate": observed,
            "gap": observed - mean_pred,
        })
    return curve


def format_reliability_curve(curve, width: int = 28) -> str:
    """Render a reliability curve as plain text for terminal reports."""
    lines = [
        f"{'range':>12}  {'n':>5}  {'pred':>6}  {'obs':>6}  {'gap':>7}  chart",
        "-" * (48 + width),
    ]
    for b in curve:
        rng = f"{b['lower']:.2f}-{b['upper']:.2f}"
        if b["count"] == 0:
            lines.append(f"{rng:>12}  {0:>5}  {'-':>6}  {'-':>6}  {'-':>7}")
            continue
        filled = int(round(b["observed_rate"] * width))
        bar = "#" * filled + "." * (width - filled)
        marker = int(round(b["mean_predicted"] * width))
        bar = bar[:marker] + "|" + bar[marker + 1:] if marker < width else bar
        lines.append(
            f"{rng:>12}  {b['count']:>5}  {b['mean_predicted']:>6.3f}  "
            f"{b['observed_rate']:>6.3f}  {b['gap']:>+7.3f}  {bar}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Baselines -- the numbers a model has to beat to be worth anything
# ---------------------------------------------------------------------------

def baseline_always(probability: float, outcomes) -> dict:
    """Score a constant predictor. The floor any real model must clear."""
    obs = _validate_outcomes(outcomes)
    preds = [probability] * len(obs)
    return score_all(preds, obs)


def baseline_base_rate(outcomes) -> dict:
    """Score a predictor that always reports the observed base rate.

    This is a deceptively strong baseline. A model that cannot beat it has
    learned nothing beyond how often the favorite wins.
    """
    obs = _validate_outcomes(outcomes)
    rate = sum(obs) / len(obs)
    # Nudge off the boundary so log loss stays finite on a degenerate set.
    rate = min(max(rate, 1e-6), 1.0 - 1e-6)
    return baseline_always(rate, obs)


def score_all(predictions, outcomes, bins: int = 10) -> dict:
    """Every calibration metric at once, for report generation."""
    preds, obs = _validate_pair(predictions, outcomes)
    return {
        "n": len(preds),
        "brier": brier_score(preds, obs),
        "log_loss": log_loss(preds, obs),
        "ece": expected_calibration_error(preds, obs, bins=bins),
        "max_ce": max_calibration_error(preds, obs, bins=bins),
        "mean_predicted": sum(preds) / len(preds),
        "observed_rate": sum(obs) / len(obs),
    }


def compare(model_predictions, market_predictions, outcomes) -> dict:
    """Head-to-head: model versus de-vigged market on the same games.

    `market_predictions` must already be de-vigged (see src/core/odds.devig).
    Raw implied probabilities carry the bookmaker's margin and would make the
    market look artificially bad, handing the model a win it did not earn.

    Returns both score sets plus `model_beats_market`, which is decided on log
    loss. If that is False, the model has no demonstrated edge -- and that is a
    real result worth reporting plainly, not a failure to explain away.
    """
    model = score_all(model_predictions, outcomes)
    market = score_all(market_predictions, outcomes)
    return {
        "model": model,
        "market": market,
        "log_loss_delta": market["log_loss"] - model["log_loss"],
        "brier_delta": market["brier"] - model["brier"],
        "model_beats_market": model["log_loss"] < market["log_loss"],
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_pair(predictions, outcomes):
    preds = list(predictions)
    obs = _validate_outcomes(outcomes)
    if len(preds) != len(obs):
        raise CalibrationError(
            f"predictions and outcomes must be the same length, "
            f"got {len(preds)} and {len(obs)}"
        )
    if not preds:
        raise CalibrationError("no predictions to score")
    clean = []
    for p in preds:
        if isinstance(p, bool) or not isinstance(p, (int, float)):
            raise CalibrationError(f"prediction must be numeric, got {p!r}")
        p = float(p)
        if p != p:
            raise CalibrationError("prediction must not be NaN")
        if not (0.0 <= p <= 1.0):
            raise CalibrationError(
                f"prediction must be between 0 and 1, got {p!r}"
            )
        clean.append(p)
    return clean, obs


def _validate_outcomes(outcomes):
    obs = list(outcomes)
    if not obs:
        raise CalibrationError("no outcomes to score")
    clean = []
    for o in obs:
        if isinstance(o, bool):
            clean.append(int(o))
            continue
        if o not in (0, 1, 0.0, 1.0):
            raise CalibrationError(
                f"outcome must be 0 or 1, got {o!r} -- "
                "calibration scores binary events only"
            )
        clean.append(int(o))
    return clean
