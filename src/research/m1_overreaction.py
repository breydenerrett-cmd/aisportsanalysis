"""M1 -- do betting lines overreact and give some of it back?

THE CLAIM
---------
Management Science (2024) tracked 3,681 MLB games across four books from
opening to close and found consecutive price changes are significantly
NEGATIVELY autocorrelated: a move in one direction is partly reversed by the
next one. The market overreacts to news. The same pattern replicates in NFL,
NBA and NHL, so it looks like a property of how sportsbooks price rather than
anything about baseball.

That makes it the most interesting hypothesis we have, because it needs no
baseball opinion at all. V1 died trying to out-analyse the market. This asks
only whether the market's own corrections are predictable from its own prior
moves.

TWO SEPARATE QUESTIONS, DELIBERATELY KEPT APART
-----------------------------------------------
1. STATISTICAL: is the lag-1 autocorrelation of price changes negative?
2. ECONOMIC: after paying the spread, does fading the last move make money?

The first can be true while the second is false, and reporting only the first
would be the exact dishonesty this project exists to avoid. A negative
autocorrelation of -0.05 is real and worthless.

PER BOOK, NEVER PER CONSENSUS
-----------------------------
Changes are measured within a single book's own price path. A consensus series
moves when books ENTER or LEAVE the sample, which manufactures changes that no
book ever made and which mean-revert by construction as the sample composition
returns to normal. That artifact would produce a textbook negative
autocorrelation out of nothing at all.

THE LIMIT, STATED BEFORE THE RESULT
------------------------------------
The paper had tick-level data. We have a median of four or five snapshots per
game. If the overreaction happens and resolves inside one of our sampling
intervals, we cannot see it, and a null here means "not visible at this
resolution", not "not real".
"""

from __future__ import annotations

from src.core import odds as odds_math
from src.model import discovery
from src.research import pricepath

# A book must show at least this many quotes for a game to contribute a
# consecutive pair of changes. Three quotes give two changes, which is the
# minimum an autocorrelation needs.
MIN_QUOTES_PER_BOOK = 3

# Minimum size of the prior move, in probability points, for the fade trade to
# fire. Pre-registered rather than fitted: 0.01 and 0.02 are the two thresholds
# tested, chosen because a one-point move is roughly the smallest a book
# expresses and two points is a visible line move. Both are reported.
FADE_THRESHOLDS = (0.01, 0.02)


def _fair_home(quote, method="proportional"):
    try:
        _, home = odds_math.devig_two_way(
            quote["away_price"], quote["home_price"], method=method)
    except odds_math.OddsError:
        return None
    return home


def changes(paths, method="proportional") -> list:
    """Consecutive within-book changes in de-vigged home probability.

    Each row is one book's move from one snapshot to the next, carrying the
    PREVIOUS move so the pair can be correlated. The first move of a book's
    path has no predecessor and is dropped rather than paired with a zero.
    """
    out = []
    for path in paths:
        for book, quotes in pricepath.by_book(path).items():
            if len(quotes) < MIN_QUOTES_PER_BOOK:
                continue
            series = []
            for quote in quotes:
                fair = _fair_home(quote, method)
                if fair is None:
                    continue
                series.append((quote, fair))
            if len(series) < MIN_QUOTES_PER_BOOK:
                continue
            deltas = []
            for (previous, previous_fair), (current, current_fair) in zip(series, series[1:]):
                deltas.append({
                    "delta": current_fair - previous_fair,
                    "from_gap": previous["gap_minutes"],
                    "to_gap": current["gap_minutes"],
                    "home_probability": current_fair,
                    "away_price": current["away_price"],
                    "home_price": current["home_price"],
                })
            for previous, current in zip(deltas, deltas[1:]):
                out.append({
                    "event_id": path["event_id"],
                    "date": path["date"],
                    "book": book,
                    "home_won": path["home_won"],
                    "previous_delta": previous["delta"],
                    "delta": current["delta"],
                    "home_probability": current["home_probability"],
                    "away_price": current["away_price"],
                    "home_price": current["home_price"],
                    "gap_minutes": current["to_gap"],
                })
    return out


def autocorrelation(rows) -> dict:
    """Lag-1 correlation between consecutive within-book price changes."""
    if len(rows) < 3:
        return {"n": len(rows), "correlation": None,
                "reason": "not enough consecutive change pairs"}
    xs = [r["previous_delta"] for r in rows]
    ys = [r["delta"] for r in rows]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        return {"n": n, "correlation": None, "reason": "a series has no variation"}
    correlation = cov / ((var_x ** 0.5) * (var_y ** 0.5))

    # Significance at the DATE level, not the pair level. Every book quoting
    # every game on one slate moves together; treating 40,000 pairs as 40,000
    # independent observations would make any correlation look certain.
    for row in rows:
        row["_diff"] = (row["previous_delta"] - mean_x) * (row["delta"] - mean_y)
    p = discovery.clustered_two_sided_p(cov / n, rows)
    return {
        "n": n,
        "correlation": correlation,
        "clustered_p": p,
        "mean_absolute_change": sum(abs(y) for y in ys) / n,
    }


def fade(rows, threshold) -> dict:
    """Take the side the market just moved AWAY from, and settle it.

    A move toward the home team is faded by backing the away team at that
    book's current away price, and vice versa. Priced at the post-move quote,
    which is what a bettor reacting to the move would actually get -- pricing
    at the pre-move quote would be betting a number that no longer exists.
    """
    picks = []
    for row in rows:
        if abs(row["previous_delta"]) < threshold:
            continue
        # Market moved toward home, so fade means back away.
        side = "away" if row["previous_delta"] > 0 else "home"
        price = row["away_price"] if side == "away" else row["home_price"]
        won = (not row["home_won"]) if side == "away" else row["home_won"]
        try:
            profit = (odds_math.american_to_decimal(price) - 1.0) if won else -1.0
        except odds_math.OddsError:
            continue
        picks.append({
            "event_id": row["event_id"],
            "date": row["date"],
            "book": row["book"],
            "side": side,
            "price": price,
            "won": won,
            "profit": profit,
            "_diff": profit,
        })
    if not picks:
        return {"n": 0, "threshold": threshold,
                "reason": "no move exceeded the threshold"}

    roi = sum(p["profit"] for p in picks) / len(picks)
    interval = discovery.clustered_bootstrap(
        picks, lambda subset: sum(p["profit"] for p in subset) / len(subset))
    return {
        "n": len(picks),
        "threshold": threshold,
        "dates": len({p["date"] for p in picks}),
        "hit_rate": sum(p["won"] for p in picks) / len(picks),
        "roi": roi,
        "clustered_p": discovery.clustered_two_sided_p(roi, picks),
        "ci": interval,
        # A fade strategy that only ever backs underdogs would earn a positive
        # ROI from the favourite-longshot bias rather than from overreaction,
        # so the side balance has to be visible.
        "share_home": sum(p["side"] == "home" for p in picks) / len(picks),
    }


def evaluate(paths, method="proportional") -> dict:
    """Both questions: is the autocorrelation negative, and is fading it profitable."""
    rows = changes(paths, method)
    return {
        "pairs": len(rows),
        "events": len({r["event_id"] for r in rows}),
        "autocorrelation": autocorrelation(rows),
        "fade": {str(t): fade(rows, t) for t in FADE_THRESHOLDS},
    }
