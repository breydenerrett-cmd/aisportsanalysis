"""M5 -- which de-vig method is actually best calibrated?

THE QUESTION
------------
Stripping the bookmaker's margin from a two-way price is not one operation, it
is a choice between several. Proportional splits the overround in proportion to
the raw probabilities. Additive splits it evenly. Power and Shin solve for a
parameter, Shin explicitly modelling the insider-trading story that produces
favourite-longshot bias.

They agree closely on a coin-flip game and diverge on lopsided ones. Since a
lopsided game is exactly where the bias they disagree about lives, the choice is
not cosmetic: it changes every edge number the system reports on favourites and
longshots.

The system currently de-vigs proportionally everywhere, because that is the
simplest thing and nobody had measured the alternatives.

WHAT IS MEASURED
----------------
For each method, the consensus de-vigged home probability at a fixed
pre-game snapshot, scored against the realised result by log loss and Brier
score, overall and split by how lopsided the price is. Lower is better on both.

WHY THIS RUNS FIRST
-------------------
It is the cheapest hypothesis in the family and the only one whose negative
result is still useful: if proportional wins, that is a confirmation the rest
of the system is built on the right primitive, and every later hypothesis
inherits it.

NOT AN EDGE CLAIM
-----------------
Better calibration is not a betting edge. It says the number is less wrong, not
that anyone will pay for it. Turning it into an edge claim requires the same
gates as everything else, and `trade()` below is the part that has to clear
them.
"""

from __future__ import annotations

import math

from src.core import odds as odds_math
from src.research import pricepath

METHODS = ("proportional", "additive", "power", "shin")

# Where the recommendation-time price is read. Six hours matches
# backfill.RECOMMENDATION_LEAD_MINUTES so M5's conclusion applies to the price
# the system actually uses, not to a moment it never sees.
RECOMMENDATION_LEAD_MINUTES = 360

# Lopsidedness buckets, by consensus de-vigged probability of the favourite.
# The interesting divergence is in the last two; the first exists as a control
# where all four methods should agree and any difference is noise.
BUCKETS = ((0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.75), (0.75, 1.01))


def consensus(quotes, method) -> float:
    """Mean de-vigged home probability across every book quoting the game.

    One book's number is that book's opinion plus its margin. The average across
    the board is the closest thing to "what the market thought", and it is what
    a calibration question has to be asked of -- otherwise the answer depends on
    which book happened to be listed first.
    """
    values = []
    for quote in quotes:
        try:
            _, home_fair = odds_math.devig_two_way(
                quote["away_price"], quote["home_price"], method=method)
        except odds_math.OddsError:
            continue
        values.append(home_fair)
    if not values:
        return None
    return sum(values) / len(values)


def _log_loss(probability, outcome):
    # Clamped because a book quoting a near-certainty plus a shock result would
    # otherwise contribute an infinite penalty and decide the comparison alone.
    p = min(max(probability, 1e-6), 1 - 1e-6)
    return -(math.log(p) if outcome else math.log(1 - p))


def _brier(probability, outcome):
    return (probability - (1.0 if outcome else 0.0)) ** 2


def rows(paths, lead_minutes=RECOMMENDATION_LEAD_MINUTES) -> list:
    """One row per event: every method's probability at the same snapshot.

    Every method is scored on the SAME games at the SAME moment. Letting one
    method quietly cover a different subset -- because a solver failed to
    converge on some prices -- would compare methods on populations rather than
    on skill, so a row is kept only when all four produce a number.
    """
    out = []
    for path in paths:
        picked = pricepath.quote_at(path, lead_minutes)
        if picked is None:
            continue
        snapshot_at, quotes = picked
        probabilities = {}
        for method in METHODS:
            value = consensus(quotes, method)
            if value is None:
                break
            probabilities[method] = value
        if len(probabilities) != len(METHODS):
            continue
        out.append({
            "event_id": path["event_id"],
            "date": path["date"],
            "home_won": path["home_won"],
            "books": len(quotes),
            "gap_minutes": quotes[0]["gap_minutes"],
            "probabilities": probabilities,
        })
    return out


def _score(subset) -> dict:
    scores = {}
    for method in METHODS:
        losses = [_log_loss(r["probabilities"][method], r["home_won"]) for r in subset]
        briers = [_brier(r["probabilities"][method], r["home_won"]) for r in subset]
        scores[method] = {
            "log_loss": sum(losses) / len(losses),
            "brier": sum(briers) / len(briers),
        }
    return scores


def _bucket_of(row):
    # Bucket on the proportional probability so a row lands in the same bucket
    # for all four methods. Bucketing per method would let each one pick its own
    # population and make the comparison meaningless.
    p = row["probabilities"]["proportional"]
    favourite = max(p, 1 - p)
    for low, high in BUCKETS:
        if low <= favourite < high:
            return (low, high)
    return None


def evaluate(paths, lead_minutes=RECOMMENDATION_LEAD_MINUTES) -> dict:
    """Calibration of all four methods, overall and by lopsidedness."""
    data = rows(paths, lead_minutes)
    if not data:
        return {"n": 0, "reason": "no event had a quote at the required lead"}

    by_bucket = {}
    for row in data:
        bucket = _bucket_of(row)
        if bucket is None:
            continue
        by_bucket.setdefault(bucket, []).append(row)

    # Maximum disagreement between methods, per row -- the direct measurement of
    # how much the choice matters at all. If this is tiny everywhere, M5 is
    # answered "it doesn't matter" regardless of which method scores best.
    spreads = []
    for row in data:
        values = list(row["probabilities"].values())
        spreads.append(max(values) - min(values))
    spreads.sort()

    return {
        "n": len(data),
        "base_rate_home": sum(r["home_won"] for r in data) / len(data),
        "mean_implied_home": sum(r["probabilities"]["proportional"] for r in data) / len(data),
        "overall": _score(data),
        "by_bucket": {f"{low:.2f}-{high:.2f}": {"n": len(subset), **_score(subset)}
                      for (low, high), subset in sorted(by_bucket.items())},
        "method_spread": {
            "mean": sum(spreads) / len(spreads),
            "median": spreads[len(spreads) // 2],
            "p95": spreads[int(len(spreads) * 0.95)],
            "max": spreads[-1],
        },
    }


def best_method(result, metric="log_loss") -> str:
    """Whichever method scores lowest overall. Ties broken by name for determinism."""
    overall = result.get("overall") or {}
    if not overall:
        return None
    return min(sorted(overall), key=lambda m: overall[m][metric])
