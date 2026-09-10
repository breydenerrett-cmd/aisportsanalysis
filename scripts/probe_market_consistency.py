"""How internally consistent is each book's own board? Descriptive only.

READ THIS BEFORE READING THE OUTPUT
------------------------------------
This probe measures ONE thing and deliberately refuses to measure a second.

It measures: for every (book, game, capture instant) where a book quoted a
moneyline, a total and the standard run line together, how far the book's own
run-line price sits from the one its own moneyline and total imply.

It does NOT look at who won, at closing lines, or at whether the
disagreement predicts anything. That is a separate question, it needs a
pre-registration written before the answer is known, and running both in one
script is how a descriptive sweep quietly becomes a search for a threshold
that produced a nice number.

WHAT A LARGE NUMBER HERE WOULD AND WOULD NOT MEAN
--------------------------------------------------
A book whose three markets disagree has at least one price out of line with
its own other two. It does not follow that the odd one out is the wrong one,
and it certainly does not follow that betting it makes money.

There is also a boring explanation that has to be ruled out first, and this
probe reports the evidence for it: our Poisson joint distribution is not the
one the book uses. Runs are overdispersed relative to Poisson, so a
systematic, same-signed disagreement across EVERY book and EVERY game is
much more likely to be our model's shape than the market's error. What would
be interesting is dispersion BETWEEN books on the same game at the same
instant -- that cannot be explained by our distribution, because our
distribution is the same for all of them.

That between-book comparison is the headline of this report, for exactly
that reason.

Usage:
    python scripts/probe_market_consistency.py [--date YYYY-MM-DD] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis import consistency  # noqa: E402
from src.pipeline import snapshots  # noqa: E402


def _index(rows):
    """{(event_id, observed_utc, book): {"h2h": row, "spreads": row,
    "totals": row}} -- only instants where a book quoted all three."""
    by_key = defaultdict(dict)
    for row in rows:
        book = row.get("book")
        event = row.get("event_id")
        stamp = row.get("observed_utc")
        if not (book and event and stamp):
            continue
        market = row.get("market")
        if market is None:
            # The moneyline rows carry no `market` key at all; that is the
            # store's own shape, not an omission.
            if row.get("home_price") is None or row.get("away_price") is None:
                continue
            by_key[(event, stamp, book)]["h2h"] = row
        elif market == "spreads":
            by_key[(event, stamp, book)]["spreads"] = row
        elif market == "totals":
            by_key[(event, stamp, book)]["totals"] = row
    return {k: v for k, v in by_key.items() if len(v) == 3}


def _percentiles(values):
    if not values:
        return {}
    ordered = sorted(values)

    def pct(p):
        i = min(int(p / 100.0 * len(ordered)), len(ordered) - 1)
        return round(ordered[i], 3)

    return {"p05": pct(5), "p25": pct(25), "p50": pct(50),
            "p75": pct(75), "p95": pct(95),
            "min": round(ordered[0], 3), "max": round(ordered[-1], 3)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None,
                    help="official (Eastern) date; default is every date in "
                         "the store")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args(argv)

    rows = snapshots.pregame_rows(snapshots.read_multibook())
    if args.date:
        rows = [r for r in rows
                if snapshots.official_date(r.get("commence_time")) == args.date]
    if not rows:
        print("no pregame multibook rows in range", file=sys.stderr)
        return 1

    triples = _index(rows)
    results = []
    skipped = 0
    for (event, stamp, book), leg in triples.items():
        h2h, spreads, totals = leg["h2h"], leg["spreads"], leg["totals"]
        check = consistency.check_board(
            home_ml=h2h.get("home_price"), away_ml=h2h.get("away_price"),
            total_line=totals.get("total"),
            over_price=totals.get("over_price"),
            under_price=totals.get("under_price"),
            home_rl_price=spreads.get("home_price"),
            away_rl_price=spreads.get("away_price"),
            home_rl_line=spreads.get("home_line"))
        if check is None:
            skipped += 1
            continue
        check.update({"event_id": event, "observed_utc": stamp, "book": book,
                      "date": snapshots.official_date(h2h.get("commence_time")),
                      "away_team": h2h.get("away_team"),
                      "home_team": h2h.get("home_team")})
        results.append(check)

    if not results:
        print(f"{len(triples)} three-market instants, none usable "
              f"({skipped} skipped)", file=sys.stderr)
        return 1

    gaps = [r["disagreement_points"] for r in results]

    # FIRST, TRY TO KILL IT. The raw distribution came back with p25 at
    # -7.02 and p50 at +3.19 -- a gap that large in the middle is not one
    # population, and the obvious candidate is the branch in `check_board`
    # that reads `p_home_minus` when the home club lays the runs and
    # `p_home_plus` when it takes them. If our Poisson is wrong by different
    # amounts on those two questions, the split alone produces two clusters
    # and none of it is about the market at all.
    laying = [r["disagreement_points"] for r in results if r["home_lays_the_runs"]]
    taking = [r["disagreement_points"] for r in results
              if not r["home_lays_the_runs"]]

    # THE HEADLINE, and it is only a headline if it survives the control
    # below. Between-book spread on the SAME game at the SAME instant cannot
    # be explained by our distribution being the wrong shape, because our
    # distribution is identical for every book in the comparison.
    #
    # It CAN be explained by books disagreeing about which club is the
    # run-line favourite, which happens on a near-pick'em game and would put
    # some books in the "laying" cluster and some in the "taking" one --
    # manufacturing a spread out of the same artifact as above. So the
    # controlled figure only counts instants where every book agrees on the
    # direction.
    per_instant = defaultdict(list)
    for r in results:
        per_instant[(r["event_id"], r["observed_utc"])].append(r)

    def _spread(group):
        return (max(x["disagreement_points"] for x in group)
                - min(x["disagreement_points"] for x in group))

    spreads_between_books = [_spread(g) for g in per_instant.values()
                             if len(g) >= 3]
    spreads_same_direction = [
        _spread(g) for g in per_instant.values()
        if len(g) >= 3 and len({x["home_lays_the_runs"] for x in g}) == 1]

    by_book = defaultdict(list)
    for r in results:
        by_book[r["book"]].append(r["disagreement_points"])

    report = {
        "instants_with_all_three_markets": len(triples),
        "measured": len(results),
        "skipped_unusable": skipped,
        "dates": sorted({r["date"] for r in results if r["date"]}),
        "books": len(by_book),
        "disagreement_points": {
            "mean": round(statistics.fmean(gaps), 3),
            "stdev": round(statistics.pstdev(gaps), 3) if len(gaps) > 1 else None,
            **_percentiles(gaps),
        },
        "by_run_line_direction": {
            "home_lays_the_runs": {"n": len(laying), **_percentiles(laying)},
            "home_takes_the_runs": {"n": len(taking), **_percentiles(taking)},
        },
        "same_game_same_instant_spread_between_books": {
            "n_instants": len(spreads_between_books),
            **_percentiles(spreads_between_books),
        },
        "spread_between_books_same_direction_only": {
            "n_instants": len(spreads_same_direction),
            **_percentiles(spreads_same_direction),
        },
        "by_book": {
            book: {"n": len(v), "mean": round(statistics.fmean(v), 3),
                   "median": round(statistics.median(v), 3)}
            for book, v in sorted(by_book.items())
        },
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    d = report["disagreement_points"]
    print(f"THREE-MARKET INSTANTS   {report['instants_with_all_three_markets']}")
    print(f"MEASURED                {report['measured']} "
          f"({report['skipped_unusable']} unusable)")
    print(f"DATES                   {report['dates'][0]} .. "
          f"{report['dates'][-1]}   ({report['books']} books)")
    print()
    print("BOOK'S OWN RUN LINE minus THE ONE ITS ML+TOTAL IMPLY, in points")
    print(f"  mean {d['mean']:+.2f}   sd {d['stdev']}   "
          f"median {d['p50']:+.2f}")
    print(f"  p05 {d['p05']:+.2f}   p25 {d['p25']:+.2f}   "
          f"p75 {d['p75']:+.2f}   p95 {d['p95']:+.2f}")
    print()
    print("  A MEAN FAR FROM ZERO IS MOST LIKELY OUR MODEL, NOT THE MARKET.")
    print("  Poisson understates run-margin spread, and that error is the")
    print("  same sign for every book on every game.")
    print()
    lay = report["by_run_line_direction"]["home_lays_the_runs"]
    take = report["by_run_line_direction"]["home_takes_the_runs"]
    print("SPLIT BY RUN-LINE DIRECTION -- the control for exactly that")
    if lay.get("n"):
        print(f"  home LAYS the runs   n={lay['n']:<6} median {lay['p50']:+6.2f}"
              f"   p25 {lay['p25']:+6.2f}  p75 {lay['p75']:+6.2f}")
    if take.get("n"):
        print(f"  home TAKES the runs  n={take['n']:<6} median {take['p50']:+6.2f}"
              f"   p25 {take['p25']:+6.2f}  p75 {take['p75']:+6.2f}")
    print("  Two clusters here means the raw figure above is our own")
    print("  distribution splitting, not a market finding.")
    print()
    s = report["same_game_same_instant_spread_between_books"]
    c = report["spread_between_books_same_direction_only"]
    print("SPREAD BETWEEN BOOKS on the same game at the same instant")
    print(f"  all instants      n={s.get('n_instants', 0):<5} "
          + (f"median {s['p50']:.2f}  p95 {s['p95']:.2f}  max {s['max']:.2f}"
             if s.get("n_instants") else ""))
    print(f"  same direction    n={c.get('n_instants', 0):<5} "
          + (f"median {c['p50']:.2f}  p95 {c['p95']:.2f}  max {c['max']:.2f}"
             if c.get("n_instants") else ""))
    print()
    print("  READ THE SECOND LINE. The first mixes instants where books")
    print("  disagree about which club is the run-line favourite, and those")
    print("  land in different clusters of our own artifact. The controlled")
    print("  figure is disagreement among the books themselves and nothing")
    print("  else -- the distribution is identical for every book in it.")
    print()
    print("BY BOOK (mean points, own run line vs own ML+total)")
    for book, stat in sorted(report["by_book"].items(),
                             key=lambda kv: kv[1]["mean"]):
        print(f"  {book:<20} n={stat['n']:<6} mean {stat['mean']:+6.2f}   "
              f"median {stat['median']:+6.2f}")

    print()
    print("OUTLIERS (largest absolute disagreement)")
    for r in sorted(results, key=lambda x: -abs(x["disagreement_points"]))[:args.top]:
        print(f"  {r['disagreement_points']:+7.2f}  {r['book']:<16} "
              f"{r['away_team']} @ {r['home_team']}  "
              f"total {r['total_line']}  "
              f"ML {r['p_home_moneyline']:.3f}")
    print()
    print("NOTHING HERE IS AN EDGE. This probe never looked at a result or a")
    print("closing line. Whether a disagreement predicts anything is a")
    print("separate question needing a pre-registration written first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
