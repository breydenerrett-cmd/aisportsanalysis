"""Evaluate a detector against the closing line, with every statistic stated.

WHAT IS BEING MEASURED, AND WHY MARKET MOVEMENT COMES FIRST
------------------------------------------------------------
A detector picks a side. The question is not whether that side won -- over a few
hundred games a coin-flip strategy wins plenty -- but whether the price MOVED
toward it between the recommendation and the close. Closing line value converges
roughly ten times faster than return, and it is the only metric here that
measures information rather than luck.

Return is reported second and never alone. A profitable run with negative CLV is
a run that got lucky at bad prices, and reporting it first is how a strategy
survives long enough to lose the money back.

WHY THE CONFIDENCE INTERVAL IS CLUSTERED
----------------------------------------
Selections on one slate are not independent. The same weather, the same day of
the schedule, the same market conditions move them together, and treating each
bet as its own draw understates the interval -- often badly enough to turn noise
into a result.

So the bootstrap resamples DATES, not selections. A date is drawn with all its
picks attached, which is the correlation structure the data actually has.

WHY A BASE-RATE CONTROL IS COMPULSORY
-------------------------------------
Almost every detector here fires on the better team. The better team wins more
often, so a naive hit rate is guaranteed to look good and means nothing. Each
detector is therefore compared against what the PRICE already implied for the
same selections: the edge is realised minus implied, and a detector that merely
restates the favourite scores zero by construction.

NOTHING HERE DECIDES ANYTHING
-----------------------------
This module measures. It does not choose thresholds, drop losers, or rank. The
family correction lives in src/model/family.py and runs over the whole set at
once, because a per-detector decision made in isolation is exactly the multiple
comparisons problem wearing a different hat.
"""

from __future__ import annotations

import math
import random

# Resamples for the clustered bootstrap. Two thousand is enough for a stable
# 95% interval and cheap at these sample sizes.
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20260828


class DiscoveryError(RuntimeError):
    """Raised when an evaluation cannot be run honestly."""


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _mean(values):
    return sum(values) / len(values) if values else None


def normal_cdf(z) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def two_sided_p(effect, values) -> float:
    """p for "the mean of these differences is zero", by a t-like normal approx.

    Approximate on purpose and labelled so. At these sample sizes the normal and
    t answers agree to the third decimal.

    Valid ONLY for independent draws. Selections are not independent -- the
    docstring above explains why -- so `evaluate` must never feed per-selection
    differences through here: use clustered_two_sided_p, which takes its
    variance at the date level, same as the bootstrap.
    """
    n = len(values)
    if n < 2:
        return 1.0
    mean = _mean(values)
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    if variance <= 0:
        return 0.0 if effect else 1.0
    z = mean / math.sqrt(variance / n)
    return 2.0 * (1.0 - normal_cdf(abs(z)))


def clustered_two_sided_p(effect, rows, diff_key="_diff") -> float:
    """p for the same mean, with the variance taken at the DATE level.

    The family correction in src/model/family.py consumes only `p`, never the
    bootstrap interval, so the p it is handed must carry the same correlation
    structure the interval does: selections on one slate move together, and a
    variance computed per-selection pretends every pick is a fresh draw --
    exactly the anticonservative n that turns noise into a result.

    Cluster-robust variance of the overall mean: the point estimate stays the
    selection-level mean (identical to `effect`, and to what the bootstrap
    resamples), only its uncertainty is measured across dates. With one
    selection per date this collapses to the independent formula, so nothing
    is lost where the clustering is trivial.
    """
    by_date = {}
    for row in rows:
        by_date.setdefault(row["date"], []).append(row[diff_key])
    clusters = list(by_date.values())
    g = len(clusters)
    n = sum(len(c) for c in clusters)
    # Fewer than two dates leaves no way to measure between-date variance; the
    # bootstrap refuses the same case, and a p of 1.0 is the honest refusal
    # here -- returning the per-selection p instead would be the defect back.
    if g < 2 or n < 2:
        return 1.0
    mean = sum(sum(c) for c in clusters) / n
    # Sum of within-cluster residual totals, squared: correlated picks inside a
    # date add up instead of cancelling, which is what widens the variance.
    variance = (g / (g - 1)) * sum(
        sum(d - mean for d in c) ** 2 for c in clusters) / (n * n)
    if variance <= 0:
        return 0.0 if effect else 1.0
    z = mean / math.sqrt(variance)
    return 2.0 * (1.0 - normal_cdf(abs(z)))


def clustered_bootstrap(rows, statistic, resamples=BOOTSTRAP_RESAMPLES,
                        seed=BOOTSTRAP_SEED) -> dict:
    """95% interval, resampling DATES rather than selections.

    Selections on one slate share weather, schedule position and market
    conditions. Drawing them independently pretends to more information than
    the data holds, and the interval comes out too narrow.
    """
    by_date = {}
    for row in rows:
        by_date.setdefault(row["date"], []).append(row)
    dates = list(by_date)
    if len(dates) < 2:
        return {"low": None, "high": None, "resamples": 0,
                "reason": "fewer than two distinct dates to resample"}

    rng = random.Random(seed)
    draws = []
    for _ in range(resamples):
        sample = []
        for _ in range(len(dates)):
            sample.extend(by_date[dates[rng.randrange(len(dates))]])
        value = statistic(sample)
        if value is not None:
            draws.append(value)
    if not draws:
        return {"low": None, "high": None, "resamples": 0,
                "reason": "statistic undefined on every resample"}
    draws.sort()
    return {
        "low": round(draws[int(0.025 * len(draws))], 5),
        "high": round(draws[min(len(draws) - 1, int(0.975 * len(draws)))], 5),
        "resamples": len(draws),
        "clusters": len(dates),
        "reason": None,
    }


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate(name, rows, min_sample=30) -> dict:
    """Every statistic the brief asks for, for one detector.

    `rows` are selections, each carrying:
      date, won (bool or None for push/void), implied (de-vigged probability at
      recommendation), closing_implied (same at the close, or None), price
      (American, for return).
    """
    decided = [r for r in rows if r.get("won") is not None
               and r.get("implied") is not None]
    result = {
        "detector": name,
        "selections": len(rows),
        "decided": len(decided),
        "pushes": sum(1 for r in rows if r.get("won") is None),
        "effect": None, "p": 1.0, "hit_rate": None, "mean_implied": None,
        "late_move": None, "late_move_n": 0, "roi": None, "ci": None,
        "by_season": {}, "economically_meaningful": None,
        "verdict": None,
    }

    if len(decided) < min_sample:
        result["verdict"] = (
            f"only {len(decided)} decided selections; below the {min_sample} "
            "floor nothing here is worth reading")
        return result

    # THE headline: realised minus what the price already implied. A detector
    # that merely restates the favourite scores zero here by construction.
    differences = [(1.0 if r["won"] else 0.0) - r["implied"] for r in decided]
    result["hit_rate"] = round(_mean([1.0 if r["won"] else 0.0 for r in decided]), 4)
    result["mean_implied"] = round(_mean([r["implied"] for r in decided]), 4)
    result["effect"] = round(_mean(differences), 5)
    # The p and the interval must share the date-cluster structure: family.py
    # consumes only `p`, so a per-selection p here would hand the FDR gate the
    # anticonservative n the module docstring forbids.
    diff_rows = [dict(r, _diff=d) for r, d in zip(decided, differences)]
    result["p"] = round(clustered_two_sided_p(result["effect"], diff_rows), 6)
    result["ci"] = clustered_bootstrap(
        diff_rows, lambda sample: _mean([s["_diff"] for s in sample]))

    # LATE-MARKET MOVEMENT, deliberately not called closing line value.
    #
    # The "closing" snapshot in the historical store is the latest one before
    # first pitch, and its median distance from first pitch is 84 minutes. A
    # real close is the final broadly-available price seconds before the game
    # locks, and a line can move plenty in the last hour -- so calling this CLV
    # would claim a measurement we did not make. It is the drift between the
    # recommendation-time price and a late pre-game snapshot, which is a proxy:
    # informative, directionally the same quantity, and honestly weaker.
    with_close = [r for r in decided if r.get("closing_implied") is not None]
    result["late_move_n"] = len(with_close)
    if with_close:
        moves = [r["closing_implied"] - r["implied"] for r in with_close]
        move_rows = [dict(r, _diff=m) for r, m in zip(with_close, moves)]
        result["late_move"] = round(_mean(moves), 5)
        # Same clustering as the headline p: line moves on one slate share the
        # same market conditions, so per-selection independence is just as false
        # here as it is for outcomes.
        result["late_move_p"] = round(
            clustered_two_sided_p(result["late_move"], move_rows), 6)
        result["late_move_ci"] = clustered_bootstrap(
            move_rows, lambda sample: _mean([s["_diff"] for s in sample]))

    # Return, second and never alone.
    priced = [r for r in decided if r.get("price") is not None]
    if priced:
        result["roi"] = round(_mean([_unit_return(r) for r in priced]), 5)
        result["roi_n"] = len(priced)

    result["by_season"] = _by_season(decided)
    result["economically_meaningful"] = _is_meaningful(result)
    result["verdict"] = _verdict(result)
    return result


def _unit_return(row) -> float:
    price = row["price"]
    if not row["won"]:
        return -1.0
    return price / 100.0 if price > 0 else 100.0 / abs(price)


def _by_season(decided) -> dict:
    """Effect per season. A result that only exists in one year is a year, not
    an effect, and the split is the cheapest way to see that."""
    seasons = {}
    for row in decided:
        seasons.setdefault(str(row["date"])[:4], []).append(
            (1.0 if row["won"] else 0.0) - row["implied"])
    return {season: {"n": len(diffs), "effect": round(_mean(diffs), 5)}
            for season, diffs in sorted(seasons.items())}


def _is_meaningful(result) -> dict:
    """Is the effect big enough to matter, separately from being real?

    One point of probability is roughly the vig on a single bet, so an edge
    below that is not tradeable however certain it is.
    """
    effect = abs(result["effect"] or 0.0)
    return {
        "threshold": 0.010,
        "passes": effect >= 0.010,
        "why": ("an edge below one point of probability is smaller than the vig "
                "on a single bet, so it is not tradeable however certain it is"),
    }


def _verdict(result) -> str:
    ci = result.get("ci") or {}
    crosses_zero = (ci.get("low") is not None and ci.get("high") is not None
                    and ci["low"] <= 0 <= ci["high"])
    if crosses_zero:
        return ("the clustered interval includes zero: this is consistent with "
                "no effect at all")
    if not result["economically_meaningful"]["passes"]:
        return ("distinguishable from zero, but smaller than the vig -- real and "
                "not tradeable")
    direction = "above" if result["effect"] > 0 else "below"
    return (f"{result['effect'] * 100:+.1f} points {direction} what the price "
            "implied, interval excludes zero -- carry to the family correction")
