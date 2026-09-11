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

import _propboard  # noqa: E402  -- the shared board, see its docstring

from src.analysis import playerprops  # noqa: E402
from src.core import odds as odds_math  # noqa: E402

MIN_BOOKS = _propboard.MIN_BOOKS

# TWO SIDES OF THE MARKET ARE EXAMINED ON ONE WEEK OF PRICES, so a nominal
# 95% interval is not a 95% statement about the pair. 2.2414 is the normal
# quantile for a two-sided 97.5% interval -- Bonferroni across the two arms.
# Fixed in docs/PREREG_UNDER_SIDE.md before either side was read. A third
# slice would need a further correction, registered before it was looked at.
Z_BONFERRONI = 2.2414


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-edge", type=float, default=0.03,
                    help="probability points above break-even to report")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    props = _propboard.read_props()
    if not props:
        print("no captured prop prices", file=sys.stderr)
        return 1

    box, by_player_name = _propboard.read_batters()

    # TONIGHT'S BATTING SLOT. Slot beats the batter's own season average on
    # plate appearances by 13% (scripts/probe_lineup_slot.py). Whether it
    # also closes the gap against a PRICE is a different question, and this
    # probe answers it by running both arms.
    slot_by_player_date = _propboard.slot_index()

    contracts = _propboard.build_contracts(props)

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
        fair_overs, best = _propboard.devig(books)

        if (len(fair_overs) < MIN_BOOKS
                or "Over" not in best or "Under" not in best):
            skipped[f"fewer than {MIN_BOOKS} two-way books"] += 1
            continue

        prior = [r for r in by_player_name.get(player, [])
                 if str(r.get("date") or "") < str(date)]
        if not prior:
            skipped["no prior games for this batter"] += 1
            continue
        history = [r for r in box if str(r.get("date") or "") < str(date)]
        slot = slot_by_player_date.get((str(date), player))
        try:
            league = playerprops.league_rates(history)
            priced = playerprops.price_prop(market=market, line=line,
                                            batter_lines=prior, league=league,
                                            batting_slot=slot)
        except playerprops.PropError:
            skipped["batter below the plate-appearance floor"] += 1
            continue

        p_over = priced["probability"]
        consensus = statistics.fmean(fair_overs)

        # Did it actually happen? Resolved for EVERY assessable contract,
        # not only the flagged ones, because the control arm needs them --
        # and never used to select.
        outcome = _propboard.resolve(by_player_name, player, date, market,
                                     line)

        # BOTH SIDES. Reading the over row alone drew every possible pick
        # from the minority tail where our model runs hottest against the
        # price -- see docs/PREREG_UNDER_SIDE.md. The under price was always
        # in the capture. The threshold is the SAME on both sides; a
        # threshold tuned per side would be a threshold tuned to produce a
        # result.
        for side in ("Over", "Under"):
            american, decimal, book = best[side]
            ours = p_over if side == "Over" else 1.0 - p_over
            mkt = consensus if side == "Over" else 1.0 - consensus
            break_even = 1.0 / decimal
            edge = ours - break_even
            won = (None if outcome is None
                   else (outcome if side == "Over" else 1 - outcome))

            all_assessed.append({
                "side": side, "best_price": american, "outcome": won,
                "pa_source": priced["expected_pa_source"]})

            if edge < args.min_edge:
                continue

            findings.append({
                "date": date, "player": player, "market": market,
                "line": line, "side": side,
                "our_probability": round(ours, 4),
                "market_fair": round(mkt, 4),
                "best_price": american, "best_book": book,
                "break_even": round(break_even, 4),
                "edge_points": round(edge * 100, 2),
                "vs_market_points": round((ours - mkt) * 100, 2),
                "books": len(fair_overs),
                "outcome": won,
                "pa_source": priced["expected_pa_source"],
                "batter_pa_sample": priced["batter_pa_sample"],
            })

    findings.sort(key=lambda f: -f["edge_points"])
    graded = [f for f in findings if f["outcome"] is not None]

    def _roi(rows):
        """Flat one-unit stakes at the price that was actually available.

        Two intervals are returned. The 95% is the ordinary one. The 97.5% is
        the one the DECISION uses: two sides of the market are being examined
        on the same week of prices, so a nominal 95% interval is not a 95%
        statement about the pair. The Bonferroni correction was fixed in
        `docs/PREREG_UNDER_SIDE.md` before either side was read.

        These are independent single bets with no clustering to correct for.
        """
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
                "ci975": [round((mean - Z_BONFERRONI * se) * 100, 2),
                          round((mean + Z_BONFERRONI * se) * 100, 2)],
                "units": round(sum(profits), 2)}

    def _side(rows, side):
        return [r for r in rows if r["side"] == side
                and r["outcome"] is not None]

    # THE CONTROL, and without it the flagged number means nothing. Every
    # assessable contract at the best price on that side, with no selection
    # by our model at all. If a flagged arm does not beat its OWN side's
    # control, our disagreement with the market is not adding anything -- and
    # if it does worse, the disagreement is actively selecting our own
    # errors, which is what the team model was measured doing.
    #
    # OWN SIDE, and the reason is arithmetic: overs hit 48.9% of these
    # contracts and unders therefore 51.1%. Judging the under arm against the
    # over control would credit that base-rate gap to our model.
    sides = {}
    for side in ("Over", "Under"):
        flagged_side = _side(findings, side)
        control_side = _side(all_assessed, side)
        sides[side] = {
            "flagged": _roi(flagged_side),
            "control": _roi(control_side),
            "flagged_hit_rate": (
                round(statistics.fmean(f["outcome"] for f in flagged_side), 4)
                if flagged_side else None),
            "control_hit_rate": (
                round(statistics.fmean(f["outcome"] for f in control_side), 4)
                if control_side else None),
        }

    report = {
        "contracts_examined": len(contracts),
        "assessable": len(all_assessed),
        "flagged": len(findings),
        "graded": len(graded),
        "sides": sides,
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
    print("  DID SELECTING ON OUR EDGE HELP? Flat stakes at the best price")
    print("  that side actually had. The DECISION interval is the 97.5% --")
    print("  two sides on one week of prices, Bonferroni, fixed in")
    print("  docs/PREREG_UNDER_SIDE.md before either side was read.")
    print()
    verdicts = {}
    for side in ("Over", "Under"):
        s = sides[side]
        fr, cr = s["flagged"], s["control"]
        print(f"    --- {side.upper()} ---")
        if not (fr and cr):
            print(f"      too few graded to score "
                  f"(flagged {fr['n'] if fr else 0})")
            verdicts[side] = "NOT MEASURABLE"
            continue
        print(f"      flagged (edge >= {args.min_edge * 100:.0f} pts)  "
              f"n={fr['n']:<5} won {s['flagged_hit_rate']:.1%}   "
              f"ROI {fr['roi_pct']:+.1f}%")
        print(f"        95%   [{fr['ci95'][0]:+.1f}, {fr['ci95'][1]:+.1f}]"
              f"      97.5% [{fr['ci975'][0]:+.1f}, {fr['ci975'][1]:+.1f}]"
              f"  <-- decides")
        print(f"      control (every {side.lower()})       "
              f"n={cr['n']:<5} won {s['control_hit_rate']:.1%}   "
              f"ROI {cr['roi_pct']:+.1f}%   "
              f"[{cr['ci95'][0]:+.1f}, {cr['ci95'][1]:+.1f}]")
        clears = fr["ci975"][0] > 0
        beats = fr["roi_pct"] > cr["roi_pct"]
        verdicts[side] = ("CANDIDATE" if (clears and beats)
                          else "NO FINDING")
        print(f"      -> {verdicts[side]}  "
              f"(interval excludes zero: {'yes' if clears else 'no'}; "
              f"beats own control: {'yes' if beats else 'no'})")
        print()
    print("    Each flagged arm is judged against its OWN side's control.")
    print("    Overs hit ~49% of these contracts and unders ~51%, so judging")
    print("    the under arm against the over control would credit that")
    print("    base-rate gap to our model.")
    print()
    if set(verdicts.values()) <= {"NO FINDING", "NOT MEASURABLE"}:
        print("    BOTH SIDES: NO FINDING. As pre-registered, the conclusion")
        print("    is that model-versus-price disagreement does not select")
        print("    profitable player props on this data in either direction,")
        print("    and the prop card does not ship as a disagreement scanner.")
        print()
    print("    A WEEK OF PRICES SETTLES NOTHING EITHER WAY. Read the intervals.")
    print()
    # DID THE LINEUP HELP? The flagged picks split by which plate-appearance
    # estimate they used. Tonight's slot beats the season average on PAs by
    # 13%; whether that also closes the gap against a PRICE is a different
    # question and this is where it gets answered.
    with_slot = [f for f in graded if f["pa_source"] == "batting_slot"]
    without = [f for f in graded if f["pa_source"] != "batting_slot"]
    ws, wo = _roi(with_slot), _roi(without)
    print("  DID KNOWING TONIGHT'S LINEUP HELP? (both sides pooled)")
    if ws:
        print(f"    with tonight's slot     n={ws['n']:<5} "
              f"ROI {ws['roi_pct']:+.1f}%   "
              f"[{ws['ci95'][0]:+.1f}, {ws['ci95'][1]:+.1f}]")
    else:
        print(f"    with tonight's slot     n={len(with_slot)} -- too few "
              f"to score; the posted-lineup store covers far fewer games "
              f"than the price store")
    if wo:
        print(f"    season average only     n={wo['n']:<5} "
              f"ROI {wo['roi_pct']:+.1f}%   "
              f"[{wo['ci95'][0]:+.1f}, {wo['ci95'][1]:+.1f}]")
    else:
        print(f"    season average only     n={len(without)} -- too few to "
              f"score, and a number here would mean nothing")
    print()
    print(f"{'date':<12}{'player':<20}{'market':<21}{'line':>5}{'side':>6}"
          f"{'ours':>7}{'mkt':>7}{'price':>7}{'edge':>7}  book")
    for f in report["top"]:
        print(f"{f['date']:<12}{f['player'][:19]:<20}{f['market']:<21}"
              f"{f['line']:>5}{f['side']:>6}{f['our_probability']:>7.3f}"
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
