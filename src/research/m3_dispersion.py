"""M3 -- when books disagree, is the outlier wrong?

THE CLAIM
---------
At any moment, eighteen books quote the same game and mostly agree. When one
sits well away from the pack, one of two things is true: it knows something the
others don't, or it has not updated. If the second is usually the case, the
consensus is the better estimate and the outlier's price is the one you can
actually bet -- an outlier by definition offers a better number on the side it
is wrong about.

PRIOR: LOW, AND RECORDED BEFORE THE RUN
----------------------------------------
V1's `stale_book` detector tested a version of this and came back +0.03
percentage points at p=0.97 -- as dead as a result gets. This differs in
conditioning on dispersion across the whole book set rather than one book
against consensus, and in reporting by dispersion size rather than one
threshold, but it is close enough that a positive finding here should be
treated as suspicious rather than celebrated. Pre-registering the low prior is
what makes that discipline enforceable later.

LEAVE-ONE-OUT, ALWAYS
---------------------
The consensus a book is compared against excludes that book. Including it
shrinks every deviation toward zero by the book's own weight, and shrinks it
MOST for the books that deviate most -- so the measurement fights the effect
it is trying to find, hardest exactly where the effect would live.
"""

from __future__ import annotations

from src.core import odds as odds_math
from src.model import discovery

# Dispersion buckets, in probability points of leave-one-out deviation. Bet
# selection uses the bucket floors as thresholds. Pre-registered: a book two
# points off the pack is a visible disagreement, five points is a stale line.
THRESHOLDS = (0.02, 0.03, 0.05)

# A snapshot needs this many books before "consensus" means anything. With
# three books a single outlier is a third of the sample it is being compared
# against.
MIN_BOOKS = 6

# Minimum lead time. Matches the rest of the family so M3's selections are
# comparable to V1's and are prices the system could act on.
RECOMMENDATION_LEAD_MINUTES = 360


def _fair(quote, method="proportional"):
    try:
        away, home = odds_math.devig_two_way(
            quote["away_price"], quote["home_price"], method=method)
    except odds_math.OddsError:
        return None
    return away, home


def deviations(paths, method="proportional",
               lead_minutes=RECOMMENDATION_LEAD_MINUTES) -> list:
    """Each book's leave-one-out deviation from consensus, at one snapshot per game.

    One snapshot per game, not all of them: the same book sitting off the pack
    across five consecutive snapshots is one disagreement observed five times,
    and counting it five times would inflate the sample without adding
    information.
    """
    from src.research import pricepath

    out = []
    for path in paths:
        picked = pricepath.quote_at(path, lead_minutes)
        if picked is None:
            continue
        _, quotes = picked
        priced = []
        for quote in quotes:
            fair = _fair(quote, method)
            if fair is None:
                continue
            priced.append((quote, fair[1]))
        if len(priced) < MIN_BOOKS:
            continue
        total = sum(home for _, home in priced)
        for quote, home in priced:
            others = (total - home) / (len(priced) - 1)
            out.append({
                "event_id": path["event_id"],
                "date": path["date"],
                "book": quote["book"],
                "home_won": path["home_won"],
                "book_home_probability": home,
                "consensus_home_probability": others,
                # Positive: this book is higher on the home team than the pack.
                "deviation": home - others,
                "away_price": quote["away_price"],
                "home_price": quote["home_price"],
                "books": len(priced),
            })
    return out


def trade(rows, threshold) -> dict:
    """Bet against the outlier, at the outlier's own price.

    A book higher on the home team than the pack is offering a better away
    price than anyone else, so the bet is away. Consensus is treated as the
    truth and the deviation as the error -- which is the hypothesis, and is
    exactly what the result either supports or refutes.
    """
    picks = []
    for row in rows:
        if abs(row["deviation"]) < threshold:
            continue
        side = "away" if row["deviation"] > 0 else "home"
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
            "consensus_home_probability": row["consensus_home_probability"],
            "_diff": profit,
        })
    if not picks:
        return {"n": 0, "threshold": threshold, "reason": "no book deviated that far"}

    roi = sum(p["profit"] for p in picks) / len(picks)
    # What the consensus itself said this side's chance was. If the strategy's
    # hit rate merely matches this, it has found nothing -- it has rediscovered
    # the consensus and paid the spread to do it.
    implied = sum(p["consensus_home_probability"] if p["side"] == "home"
                  else 1 - p["consensus_home_probability"] for p in picks) / len(picks)
    hit = sum(p["won"] for p in picks) / len(picks)
    for pick in picks:
        pick["_diff"] = (1.0 if pick["won"] else 0.0) - (
            pick["consensus_home_probability"] if pick["side"] == "home"
            else 1 - pick["consensus_home_probability"])

    return {
        "n": len(picks),
        "threshold": threshold,
        "dates": len({p["date"] for p in picks}),
        "events": len({p["event_id"] for p in picks}),
        "hit_rate": hit,
        "consensus_implied": implied,
        # The effect: how much better than the consensus this did, in points.
        "effect": hit - implied,
        "clustered_p": discovery.clustered_two_sided_p(hit - implied, picks),
        "ci": discovery.clustered_bootstrap(
            picks, lambda subset: sum(s["_diff"] for s in subset) / len(subset)),
        "roi": roi,
        "share_home": sum(p["side"] == "home" for p in picks) / len(picks),
        "books": sorted({p["book"] for p in picks}),
    }


def evaluate(paths, method="proportional",
             lead_minutes=RECOMMENDATION_LEAD_MINUTES) -> dict:
    rows = deviations(paths, method, lead_minutes)
    if not rows:
        return {"n": 0, "reason": "no snapshot carried enough books"}
    spread = sorted(abs(r["deviation"]) for r in rows)
    return {
        "n": len(rows),
        "events": len({r["event_id"] for r in rows}),
        "deviation": {
            "median": spread[len(spread) // 2],
            "p95": spread[int(len(spread) * 0.95)],
            "max": spread[-1],
        },
        "trades": {str(t): trade(rows, t) for t in THRESHOLDS},
    }
