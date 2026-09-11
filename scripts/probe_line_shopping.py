"""How much is shopping the price worth, with no model involved at all?

THE QUESTION
------------
Every number this repo has produced about player props compares OUR estimate
to a book's. Both pre-registered runs of that comparison came back with no
finding (`docs/PREREG_MARKET_VS_MODEL.md`, `docs/PREREG_UNDER_SIDE.md`).

This asks a different question, and it is the one question in the whole area
that does not depend on our model being right about anything:

    Given that someone has already decided to make a particular bet, how
    much does it cost them to take the first price they see instead of the
    best price on the board?

That is not a prediction. It is arithmetic on prices that were all available
at the same moment, and the money is real whether or not anyone can forecast
a baseball game. It is also the thing LINEHOUND's Bet Check already does.

WHY IT IS NOT FREE MONEY, AND WHY THAT HAS TO BE MEASURED
----------------------------------------------------------
The obvious objection, and it is a good one: **the outlier may be the
informed one.** A book sitting well off the others has often moved on news
the rest have not priced yet -- a late scratch, a weather change. Taking the
best price then means systematically trading against whoever is fastest, and
"best price" becomes adverse selection wearing a helpful face.

That is a measurable claim, not a philosophical one, and it is why this probe
scores best-price and mean-price arms against the SAME outcomes rather than
assuming the spread is capturable.

Second objection, also handled: **best-of-N is biased upward in N.** A
contract quoted by six books has more chance of containing a high price than
one quoted by two, and contracts with more books are not a random sample --
they are the popular ones. So every number here is also reported stratified
by book count, and the headline is the paired per-contract difference, which
holds the contract fixed.

Read-only. Descriptive. Adopts nothing and selects no bets.

Usage:
    python scripts/probe_line_shopping.py [--json]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _propboard  # noqa: E402

from src.core import odds as odds_math  # noqa: E402
from src.pipeline import snapshots  # noqa: E402

BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20260910


def _collect():
    """Every contract, every book's price on both sides, and the outcome.

    No model is called. Nothing here needs `playerprops` at all, which is the
    point -- a batter below the plate-appearance floor still has a price
    worth shopping.
    """
    props = _propboard.read_props()
    if not props:
        return None, "no captured prop prices"

    _box, by_name = _propboard.read_batters()
    contracts = _propboard.build_contracts(props)

    rows, skipped = [], defaultdict(int)
    for key, books in contracts.items():
        date, _event, player, market, line_text = key
        try:
            line = float(line_text)
        except (TypeError, ValueError):
            skipped["unreadable line"] += 1
            continue

        # Every book that quoted BOTH sides, kept as decimals. Two-way only,
        # because a one-sided quote has no margin to measure and cannot be
        # compared like for like.
        quotes, booksums = [], []
        for book, sides in books.items():
            over, under = sides.get("Over"), sides.get("Under")
            if over is None or under is None:
                continue
            try:
                raw = (odds_math.american_to_probability(over)
                       + odds_math.american_to_probability(under))
                if raw < _propboard.MIN_TWO_WAY_BOOKSUM:
                    continue
                quotes.append({
                    "book": book,
                    "Over": odds_math.american_to_decimal(over),
                    "Under": odds_math.american_to_decimal(under)})
                booksums.append(raw)
            except (odds_math.OddsError, TypeError, ValueError,
                    ZeroDivisionError):
                continue

        if len(quotes) < _propboard.MIN_BOOKS:
            skipped[f"fewer than {_propboard.MIN_BOOKS} two-way books"] += 1
            continue

        outcome = _propboard.resolve(by_name, player, date, market, line)
        if outcome is None:
            skipped["no settled box score"] += 1
            continue

        rows.append({
            "date": str(date), "player": player, "market": market,
            "line": line, "outcome": outcome, "quotes": quotes,
            "books": len(quotes),
            "mean_booksum": statistics.fmean(booksums),
        })
    return (rows, dict(skipped)), None


def _profit(decimal, won):
    return (decimal - 1.0) if won else -1.0


def _arm(rows, pick):
    """ROI of one pricing policy over both sides of every contract.

    BOTH SIDES ARE BACKED, every contract, one unit each. That is not a
    strategy anyone would run -- backing both sides of the same market is a
    guaranteed small loss equal to the margin -- and that is exactly why it
    is the right frame here. It holds the bet selection completely fixed, so
    the ONLY thing separating the arms is which price was taken. Any
    difference between them is execution and nothing else.
    """
    profits = []
    for row in rows:
        for side, won in (("Over", row["outcome"]),
                          ("Under", 1 - row["outcome"])):
            profits.append(_profit(pick(row, side), won))
    if len(profits) < 2:
        return None
    mean = statistics.fmean(profits)
    var = statistics.fmean((p - mean) ** 2 for p in profits)
    return {"n": len(profits), "roi_pct": mean * 100,
            "se_pct": math.sqrt(var / len(profits)) * 100}


def _best(row, side):
    return max(q[side] for q in row["quotes"])


def _mean(row, side):
    return statistics.fmean(q[side] for q in row["quotes"])


def _worst(row, side):
    return min(q[side] for q in row["quotes"])


def _paired_gain(rows):
    """Best price minus mean price, per contract, in units.

    Paired on the contract, so book count and market popularity cancel --
    the upward bias of best-of-N cannot inflate a difference measured
    within the same contract's own quote set.

    THIS NUMBER CANNOT BE NEGATIVE AND ITS INTERVAL PROVES NOTHING.
    A losing bet returns -1 at every price, so the difference is zero; a
    winning bet returns more at the higher price, so the difference is
    positive. `max >= mean` is arithmetic. An interval excluding zero here
    is therefore guaranteed and is NOT evidence that the spread is
    capturable -- it only measures HOW BIG the arithmetic is.

    The question of whether the spread is real money is a different one,
    and `_adverse_selection` is where it gets asked.
    """
    gains = []
    for row in rows:
        for side, won in (("Over", row["outcome"]),
                          ("Under", 1 - row["outcome"])):
            gains.append(_profit(_best(row, side), won)
                         - _profit(_mean(row, side), won))
    return statistics.fmean(gains) * 100 if gains else None


def _adverse_selection(rows, *, quantiles=4):
    """IS THE OUTLIER THE INFORMED ONE? The question `_paired_gain` cannot ask.

    A book sitting well above the others has often moved on news the rest
    have not priced -- a late scratch, a weather change. If that is what
    dispersion mostly is, then taking the best price means trading against
    whoever is fastest, and the arithmetic gain above is an illusion that
    the outcomes quietly take back.

    The test: for every contract-side, take the CONSENSUS fair probability
    (de-vigged, margin removed) and the realised outcome, and stratify by
    how far the best price sits above the mean. The statistic in each
    stratum is

        realised win rate - consensus fair probability

    If dispersion carries no information, that gap is flat across strata:
    a contract where one book is generously off does not hit any less often
    than one where every book agrees. If the outlier is informed, the gap
    FALLS as dispersion rises -- the bets that looked most shoppable are the
    ones the market had already moved away from.

    De-vigged, because a gap measured against raw prices would be dominated
    by the book's margin, which is the same in every stratum and would swamp
    the effect being looked for.
    """
    scored = []
    for row in rows:
        for side, won in (("Over", row["outcome"]),
                          ("Under", 1 - row["outcome"])):
            prices = [q[side] for q in row["quotes"]]
            mean_price = statistics.fmean(prices)
            # De-vig each book's pair, then average, so the reference is a
            # fair probability rather than one carrying the margin.
            fair = statistics.fmean(
                (1.0 / q[side])
                / (1.0 / q["Over"] + 1.0 / q["Under"])
                for q in row["quotes"])
            scored.append({
                "dispersion": max(prices) / mean_price - 1.0,
                "fair": fair,
                "won": won,
            })
    if len(scored) < quantiles * 40:
        return None
    scored.sort(key=lambda s: s["dispersion"])
    size = len(scored) // quantiles
    strata = []
    for i in range(quantiles):
        chunk = (scored[i * size:(i + 1) * size] if i < quantiles - 1
                 else scored[(quantiles - 1) * size:])
        strata.append({
            "n": len(chunk),
            "mean_dispersion_pct": statistics.fmean(
                s["dispersion"] for s in chunk) * 100,
            "fair": statistics.fmean(s["fair"] for s in chunk),
            "realised": statistics.fmean(s["won"] for s in chunk),
            "gap_pts": (statistics.fmean(s["won"] for s in chunk)
                        - statistics.fmean(s["fair"] for s in chunk)) * 100,
        })
    return strata


def _clustered_ci(rows, statistic, *, resamples, seed):
    """Resample whole player-nights. One batter's hits and total-bases lines
    on the same night settle on the same at-bats."""
    clusters = defaultdict(list)
    for row in rows:
        clusters[(row["date"], row["player"])].append(row)
    keys = list(clusters)
    if len(keys) < 2:
        return None
    rng = random.Random(seed)
    draws = []
    for _ in range(resamples):
        picked = [clusters[rng.choice(keys)] for _ in keys]
        value = statistic([r for group in picked for r in group])
        if value is not None:
            draws.append(value)
    if len(draws) < resamples // 2:
        return None
    draws.sort()
    return [draws[int(0.025 * len(draws))],
            draws[min(len(draws) - 1, int(0.975 * len(draws)))]]


def game_market_reference():
    """The same arithmetic on game moneylines, for scale.

    Without a reference, "the book charges 6.8 points" is a number with no
    meaning. The game moneyline is the market this repo has been working in
    all along and the one a reader already has intuitions about.

    PRE-GAME ROWS ONLY, and the reason is a mistake made while writing this
    probe. An unfiltered pass over the same store reported a median
    best-versus-mean price gap of 39% and a maximum of 301% -- one event had
    two books at +2800 while six others said +250, at the same instant,
    9:32pm Eastern. That is not dispersion between books. It is an IN-PLAY
    price for a team already losing, and the store carries those.

    Every production consumer of this store filters correctly
    (`src/report/card.py`, `src/analysis/prices.py`, `src/report/clv.py`).
    The throwaway query did not. Recording it because the number looked like
    an enormous finding for about a minute, and a surprise is an alarm.
    """
    newest = {}
    for row in snapshots.iter_multibook():
        if not snapshots.is_full_game_moneyline(row):
            continue
        if not snapshots.is_pregame(row):
            continue
        key = (row.get("event_id"), row.get("book"))
        stamp = row.get("observed_utc") or ""
        if stamp > newest.get(key, ("",))[0]:
            newest[key] = (stamp, row)

    by_event = defaultdict(list)
    for _key, (_stamp, row) in newest.items():
        by_event[row.get("event_id")].append(row)

    sums, counts = [], []
    for quotes in by_event.values():
        if len(quotes) < 2:
            continue
        pairs = []
        for row in quotes:
            try:
                pairs.append(
                    odds_math.american_to_probability(row["home_price"])
                    + odds_math.american_to_probability(row["away_price"]))
            except (odds_math.OddsError, TypeError, ValueError, KeyError):
                continue
        if len(pairs) < 2:
            continue
        sums.append(statistics.fmean(pairs))
        counts.append(len(quotes))
    if not sums:
        return None
    return {"events": len(sums),
            "median_books": statistics.median(counts),
            "margin_pct": (statistics.fmean(sums) - 1.0) * 100}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--skip-game-reference", action="store_true",
                    help="skip the 38 MB moneyline pass")
    args = ap.parse_args(argv)

    collected, error = _collect()
    if error:
        print(error, file=sys.stderr)
        return 1
    rows, skipped = collected

    if len(rows) < 200:
        print(f"only {len(rows)} settled contracts -- too few", file=sys.stderr)
        return 2

    arms = {
        "best": _arm(rows, _best),
        "mean": _arm(rows, _mean),
        "worst": _arm(rows, _worst),
    }
    gain = _paired_gain(rows)
    gain_ci = _clustered_ci(rows, _paired_gain,
                            resamples=BOOTSTRAP_RESAMPLES,
                            seed=BOOTSTRAP_SEED)
    adverse = _adverse_selection(rows)
    game = None if args.skip_game_reference else game_market_reference()

    # THE MARGIN, for scale. A two-way book sum of 1.045 means the book is
    # charging 4.5 points across the pair. Shopping can only ever recover
    # part of that, and knowing the size of the whole tells you whether a
    # recovery is impressive or trivial.
    margin = (statistics.fmean(r["mean_booksum"] for r in rows) - 1.0) * 100
    tightest = statistics.fmean(
        min(1.0 / q["Over"] + 1.0 / q["Under"] for q in r["quotes"]) - 1.0
        for r in rows) * 100

    # STRATIFIED BY BOOK COUNT, because best-of-N grows with N and contracts
    # with more books are the popular ones, not a random sample.
    strata = {}
    for count in sorted({r["books"] for r in rows}):
        chunk = [r for r in rows if r["books"] == count]
        if len(chunk) < 20:
            continue
        strata[count] = {"contracts": len(chunk),
                         "paired_gain_pct": _paired_gain(chunk)}

    # HOW MANY BOOKS DO YOU ACTUALLY NEED? Best-of-k against best-of-all, on
    # the contracts that carry enough books to answer it. A deterministic
    # order (the books sorted by name) so this does not become a lottery --
    # it answers "how much of the spread does a fixed small set recover",
    # which is the shape of the real question, not "which books are best",
    # which this data cannot support.
    depth = {}
    deep = [r for r in rows if r["books"] >= 4]
    if len(deep) >= 50:
        for k in (1, 2, 3, 4):
            def _pick(row, side, k=k):
                ordered = sorted(row["quotes"], key=lambda q: q["book"])
                return max(q[side] for q in ordered[:k])
            arm = _arm(deep, _pick)
            depth[k] = arm["roi_pct"] if arm else None

    report = {
        "settled_contracts": len(rows),
        "skipped": skipped,
        "mean_margin_pct": margin,
        "tightest_book_margin_pct": tightest,
        "arms": arms,
        "paired_gain_pct": gain,
        "paired_gain_ci95": gain_ci,
        "adverse_selection_strata": adverse,
        "game_market_reference": game,
        "by_book_count": strata,
        "depth_on_deep_contracts": depth,
        "deep_contracts": len(deep),
    }

    if args.json:
        print(json.dumps(report, indent=2, default=float))
        return 0

    print("WHAT IS SHOPPING THE PRICE WORTH? No model involved.")
    print()
    print(f"SETTLED    {len(rows)} contracts with 2+ two-way books")
    print(f"  skipped: {skipped}")
    print()
    print("  THE BOOK'S MARGIN, for scale")
    print(f"    average book charges  {margin:+.2f} points across the pair")
    print(f"    the tightest book on each contract  {tightest:+.2f} points")
    books_per = statistics.median(r["books"] for r in rows)
    print(f"    median books quoting both sides  {books_per:.0f}")
    if game:
        print()
        print("    THE SAME ARITHMETIC ON GAME MONEYLINES, pre-game only:")
        print(f"      {game['margin_pct']:+.2f} points across "
              f"{game['events']} events, median {game['median_books']:.0f} "
              f"books each")
        print()
        print(f"    PLAYER PROPS COST "
              f"{margin / game['margin_pct']:.1f}x THE GAME MARKET and are")
        print(f"    quoted by a fraction of the books "
              f"({books_per:.0f} against {game['median_books']:.0f}). The")
        print("    market is both more expensive to enter and harder to shop.")
        print("    That does not make it the wrong market -- it makes the")
        print("    edge required to beat it nearly twice as large, and two")
        print("    pre-registered runs have now failed to find one.")
    print()
    print("  BACKING BOTH SIDES OF EVERY CONTRACT, one unit each, changing")
    print("  ONLY which price is taken. Backing both sides is a guaranteed")
    print("  small loss -- that is the point. It holds the bet completely")
    print("  fixed so the only difference between arms is execution.")
    for name in ("best", "mean", "worst"):
        a = arms[name]
        print(f"    {name:<6} price   n={a['n']:<6} "
              f"ROI {a['roi_pct']:+.2f}%  (se {a['se_pct']:.2f})")
    print()
    print("  HOW BIG IS THE ARITHMETIC -- best price minus mean price,")
    print("  paired on the same contract so book count and popularity")
    print("  cancel:")
    print(f"    {gain:+.2f} points per bet", end="")
    if gain_ci:
        print(f"   95% clustered CI [{gain_ci[0]:+.2f}, {gain_ci[1]:+.2f}]")
    else:
        print()
    print()
    print("    THIS INTERVAL EXCLUDING ZERO PROVES NOTHING. A losing bet")
    print("    returns -1 at every price and a winning one returns more at")
    print("    the higher price, so the difference cannot be negative --")
    print("    max >= mean is arithmetic, not evidence. What the number")
    print(f"    says is only the SIZE: {gain:.2f} points against a margin of")
    print(f"    {margin:.2f}, so shopping recovers about "
          f"{gain / margin:.0%} of what the book charges.")
    print()
    print("  IS THE OUTLIER THE INFORMED ONE? The question the arithmetic")
    print("  cannot ask. Contract-sides sorted by how far the best price")
    print("  sits above the mean; the statistic is realised win rate minus")
    print("  the books' own de-vigged consensus.")
    if adverse:
        print()
        print(f"    {'dispersion':>12}{'n':>7}{'fair':>8}{'actual':>8}"
              f"{'gap':>8}")
        for s in adverse:
            print(f"    {s['mean_dispersion_pct']:>11.2f}%{s['n']:>7}"
                  f"{s['fair']:>8.3f}{s['realised']:>8.3f}"
                  f"{s['gap_pts']:>+8.2f}")
        first, last = adverse[0]["gap_pts"], adverse[-1]["gap_pts"]
        print()
        print(f"    lowest-dispersion stratum {first:+.2f} pts, "
              f"highest {last:+.2f} pts")
        print()
        print("    A FLAT column is what no adverse selection looks like:")
        print("    contracts where one book is generously off hit no less")
        print("    often than contracts where every book agrees. A column")
        print("    that FALLS is the outlier being informed -- the bets that")
        print("    looked most shoppable are the ones the market had already")
        print("    moved away from, and the arithmetic gain is an illusion")
        print("    the outcomes take back.")
        print()
        print("    Four strata on one week of prices. The differences here")
        print("    are not tested against a null and no conclusion is drawn")
        print("    from them; this is a shape to watch as the store grows.")
    else:
        print("    not enough settled contract-sides to stratify")
    print()
    print("  BY BOOK COUNT (best-of-N grows with N; the paired gain should")
    print("  rise with book count if it is real dispersion)")
    for count, s in strata.items():
        print(f"    {count} books   n={s['contracts']:<5} "
              f"{s['paired_gain_pct']:+.2f} points")
    print()
    if depth:
        print(f"  HOW DEEP DO YOU NEED TO SHOP? On the {len(deep)} contracts")
        print("  carrying 4+ books, taking the best of the first k books in a")
        print("  fixed order:")
        for k, roi in depth.items():
            print(f"    best of {k}   ROI {roi:+.2f}%")
        print()
        print("    This answers how much a fixed small set recovers. It does")
        print("    NOT say which books to use -- a week of prices cannot")
        print("    rank books, and picking the ones that happened to pay")
        print("    would be fitting the sample.")
    print()
    print("  WHAT THIS CANNOT SAY: that any of it survives a book limiting")
    print("  or closing an account, which is how this value is collected in")
    print("  practice; nor that a week of prices is a season of prices.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
