"""Where does our calibrated number beat the book's price? Descriptive.

THE OWNER'S CRITERION, IMPLEMENTED LITERALLY
---------------------------------------------
"If something with over a 50% chance based on our system shows a high
likelihood of hitting over 50% of the time but the odds on the bookies have
it at +110 or +115 or higher, you could assume that is a safe bet, high
value."

That is exactly right and it generalises: a price implies a break-even
probability, and a bet is worth taking when our probability exceeds it by
enough to survive being a little wrong. +110 breaks even at 47.6%; a
genuine 55% there is worth 15 cents on the dollar.

WHAT MAKES THIS HONEST RATHER THAN A SLOT MACHINE
--------------------------------------------------
Only markets whose probabilities have been MEASURED as calibrated are
scanned. `src.analysis.playerprops.publishable()` is the gate, and it
currently refuses two of six markets that measured worse than a base rate.

Calibration was established first, on 16,741 batter games, with no price in
sight (`scripts/backtest_player_props.py`). Doing it the other way round --
scanning prices for gaps and then believing the gaps -- is how a model's own
errors get sold as edges, and it is the exact shape of this project's
2026-09-09 incident.

WHAT THIS PROBE CANNOT TELL YOU
--------------------------------
Whether these bets WIN. It reads prices and probabilities and reports where
they disagree. The captured price store covers about a week, so even where
value appears, the sample cannot settle profitability. A separate
pre-registered forward test does that, and it does not exist yet.

The de-vig is reported alongside every gap for a specific reason: a book's
two sides sum to more than 100%, and the excess is its margin. A "gap"
measured against the raw price partly IS that margin, which is not value and
does not belong to us.

Read-only.

Usage:
    python scripts/probe_prop_value.py [--min-edge 0.03] [--top 25]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis import playerprops  # noqa: E402
from src.core import odds as odds_math  # noqa: E402
from src.pipeline import boxscores  # noqa: E402

BOX_STORE = os.path.join("data", "processed", "boxscores_2026.jsonl")
PROP_STORE = os.path.join("data", "processed", "batter_props.jsonl")

# A pair whose two sides sum below this cannot be a real two-way market --
# a book always prices both sides above 100% and that excess is its margin.
# Same floor and same reason as src/analysis/derivative_prices.py's.
MIN_TWO_WAY_BOOKSUM = 0.98

# Below this many books quoting BOTH sides of one player-line, a
# "consensus" is a handful's opinion rather than a market.
#
# TWO, NOT THREE, AND THE REASON IS MEASURED. At three this examined 12% of
# the board and the survivors bunched on whichever date happened to get a
# fuller capture -- 13 of the top 18 findings came from one day. Player-prop
# boards are simply thinner two-way than game boards: only 40% of total-base
# contracts carry three books quoting both sides, and 10% of hits contracts,
# though 56-75% carry two.
#
# Two is a real weakening and it is stated rather than hidden. It is not a
# threshold moved to produce more findings -- it is moved because three was
# selecting on capture depth rather than on anything about the bets.
MIN_BOOKS = 2


def _read_props():
    rows = []
    if not os.path.exists(PROP_STORE):
        return rows
    with open(PROP_STORE, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                rows.append(json.loads(raw))
            except ValueError:
                continue
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-edge", type=float, default=0.03,
                    help="probability points above break-even to report")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    props = _read_props()
    if not props:
        print("no captured prop prices", file=sys.stderr)
        return 1

    box = [r for r in boxscores.read(BOX_STORE) if r.get("type") == "batter"]
    by_player_name = defaultdict(list)
    for row in box:
        name = row.get("player_name")
        if name:
            by_player_name[name].append(row)
    for lines in by_player_name.values():
        lines.sort(key=lambda r: str(r.get("date") or ""))

    # Group the prices: one contract is (date, event, player, market, line),
    # and within it one row per book per side at the newest instant.
    contracts = defaultdict(lambda: defaultdict(dict))
    newest = {}
    def _assessable(market):
        # BOTH gates. `publishable` asks whether the model is any good;
        # `deviggable` asks whether a fair price exists to measure against.
        # Home runs pass the first and fail the second -- no book quotes the
        # under, so a "gap" there is measured against a raw price that still
        # contains the book's whole margin, which is not value.
        return (playerprops.publishable(market or "")
                and playerprops.deviggable(market or ""))

    for row in props:
        market = row.get("market")
        if not _assessable(market):
            continue
        key = (row.get("game_date"), row.get("event_id"), row.get("player"),
               market, str(row.get("line")))
        stamp = row.get("observed_utc") or ""
        if stamp > newest.get(key, ""):
            newest[key] = stamp
    for row in props:
        market = row.get("market")
        if not _assessable(market):
            continue
        key = (row.get("game_date"), row.get("event_id"), row.get("player"),
               market, str(row.get("line")))
        if (row.get("observed_utc") or "") != newest.get(key):
            continue
        side = row.get("side")
        if side in ("Over", "Under") and row.get("book"):
            contracts[key][row["book"]][side] = row.get("price")

    findings = []
    all_assessed = []
    skipped = defaultdict(int)

    for key, books in contracts.items():
        date, _event, player, market, line_text = key
        try:
            line = float(line_text)
        except (TypeError, ValueError):
            skipped["unreadable line"] += 1
            continue

        # De-vig each book, then average. A gap measured against a raw price
        # partly IS the book's margin, which is not value and is not ours.
        fair_overs, best_over, best_book = [], None, None
        for book, sides in books.items():
            over, under = sides.get("Over"), sides.get("Under")
            if over is None or under is None:
                continue
            try:
                raw = (odds_math.american_to_probability(over)
                       + odds_math.american_to_probability(under))
                if raw < MIN_TWO_WAY_BOOKSUM:
                    continue
                fair_over, _fair_under = odds_math.devig_two_way(over, under)
                decimal = odds_math.american_to_decimal(over)
            except (odds_math.OddsError, TypeError, ValueError,
                    ZeroDivisionError):
                continue
            fair_overs.append(fair_over)
            if best_over is None or decimal > best_over[1]:
                best_over, best_book = (over, decimal), book

        if len(fair_overs) < MIN_BOOKS or best_over is None:
            skipped[f"fewer than {MIN_BOOKS} two-way books"] += 1
            continue

        prior = [r for r in by_player_name.get(player, [])
                 if str(r.get("date") or "") < str(date)]
        if not prior:
            skipped["no prior games for this batter"] += 1
            continue
        history = [r for r in box if str(r.get("date") or "") < str(date)]
        try:
            league = playerprops.league_rates(history)
            priced = playerprops.price_prop(market=market, line=line,
                                            batter_lines=prior, league=league)
        except playerprops.PropError:
            skipped["batter below the plate-appearance floor"] += 1
            continue

        ours = priced["probability"]
        consensus = statistics.fmean(fair_overs)
        break_even = 1.0 / best_over[1]
        edge = ours - break_even

        # Did it actually happen? Resolved for EVERY assessable contract,
        # not only the flagged ones, because the control arm needs them --
        # and never used to select.
        outcome = None
        for row in by_player_name.get(player, []):
            if str(row.get("date") or "") == str(date):
                got = {"batter_hits": row.get("h"),
                       "batter_total_bases": row.get("total_bases"),
                       "batter_home_runs": row.get("hr"),
                       "batter_runs_scored": row.get("r")}.get(market)
                if got is not None:
                    outcome = 1 if int(got) > line else 0
                break

        all_assessed.append({"best_price": best_over[0], "outcome": outcome})

        if edge < args.min_edge:
            continue

        findings.append({
            "date": date, "player": player, "market": market, "line": line,
            "our_probability": round(ours, 4),
            "market_fair": round(consensus, 4),
            "best_price": best_over[0], "best_book": best_book,
            "break_even": round(break_even, 4),
            "edge_points": round(edge * 100, 2),
            "vs_market_points": round((ours - consensus) * 100, 2),
            "books": len(fair_overs),
            "outcome": outcome,
        })

    findings.sort(key=lambda f: -f["edge_points"])
    graded = [f for f in findings if f["outcome"] is not None]

    def _roi(rows):
        """Flat one-unit stakes at the price that was actually available,
        with a normal 95% interval. These are independent single bets with
        no clustering to correct for."""
        if not rows:
            return None
        profits = []
        for row in rows:
            try:
                decimal = odds_math.american_to_decimal(row["best_price"])
            except (odds_math.OddsError, TypeError, ValueError):
                continue
            profits.append((decimal - 1.0) if row["outcome"] else -1.0)
        if len(profits) < 2:
            return None
        mean = statistics.fmean(profits)
        var = statistics.fmean((p - mean) ** 2 for p in profits)
        se = math.sqrt(var / len(profits))
        return {"n": len(profits), "roi_pct": round(mean * 100, 2),
                "ci95": [round((mean - 1.96 * se) * 100, 2),
                         round((mean + 1.96 * se) * 100, 2)],
                "units": round(sum(profits), 2)}

    # THE CONTROL, and without it the flagged number means nothing. Every
    # assessable contract, backed on the over at the best price, with no
    # selection by our model at all. If the flagged arm does not beat this,
    # our disagreement with the market is not adding anything -- and if it
    # does worse, the disagreement is actively selecting our own errors,
    # which is what the team model was measured doing.
    control = [f for f in all_assessed if f["outcome"] is not None]

    report = {
        "contracts_examined": len(contracts),
        "assessable": len(all_assessed),
        "flagged": len(findings),
        "graded": len(graded),
        "hit_rate": (round(statistics.fmean(f["outcome"] for f in graded), 4)
                     if graded else None),
        "mean_break_even": (round(statistics.fmean(f["break_even"]
                                                   for f in graded), 4)
                            if graded else None),
        "flagged_return": _roi(graded),
        "control_return": _roi(control),
        "control_hit_rate": (round(statistics.fmean(f["outcome"]
                                                    for f in control), 4)
                             if control else None),
        "skipped": dict(skipped),
        "top": findings[:args.top],
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"CONTRACTS EXAMINED  {report['contracts_examined']}  "
          f"(publishable markets only)")
    print(f"FLAGGED             {report['flagged']} at >= "
          f"{args.min_edge * 100:.0f} points over break-even")
    print(f"  skipped: {report['skipped']}")
    print()
    fr, cr = report["flagged_return"], report["control_return"]
    if fr and cr:
        print("  DID SELECTING ON OUR EDGE HELP? Flat stakes, best available")
        print("  price, 95% intervals.")
        print(f"    flagged (edge >= {args.min_edge * 100:.0f} pts)   "
              f"n={fr['n']:<5} won {report['hit_rate']:.1%}   "
              f"ROI {fr['roi_pct']:+.1f}%   [{fr['ci95'][0]:+.1f}, "
              f"{fr['ci95'][1]:+.1f}]")
        print(f"    control (every over)          n={cr['n']:<5} won "
              f"{report['control_hit_rate']:.1%}   "
              f"ROI {cr['roi_pct']:+.1f}%   [{cr['ci95'][0]:+.1f}, "
              f"{cr['ci95'][1]:+.1f}]")
        print()
        print("    The control takes every assessable over with no selection")
        print("    by our model at all. If the flagged arm does not beat it,")
        print("    our disagreement with the market is adding nothing; if it")
        print("    does worse, the disagreement is selecting our own errors.")
        print()
        print("    A WEEK OF PRICES SETTLES NEITHER. Read the intervals.")
    print()
    print(f"{'date':<12}{'player':<22}{'market':<22}{'line':>5}"
          f"{'ours':>7}{'mkt':>7}{'price':>7}{'edge':>7}  book")
    for f in report["top"]:
        print(f"{f['date']:<12}{f['player'][:21]:<22}{f['market']:<22}"
              f"{f['line']:>5}{f['our_probability']:>7.3f}"
              f"{f['market_fair']:>7.3f}{f['best_price']:>7}"
              f"{f['edge_points']:>+7.1f}  {f['best_book']}")
    print()
    print("  'ours' is our calibrated probability, 'mkt' the books' own")
    print("  de-vigged consensus, 'edge' how far ours sits above what the")
    print("  best available price needs to break even.")
    print()
    print("  NOTHING HERE IS A CLAIM THAT THESE WIN. A week of prices cannot")
    print("  settle profitability, and a forward test is the only thing that")
    print("  can. What it establishes is whether there is anything to look")
    print("  for at all.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
