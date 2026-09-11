"""Head to head: does the book's number predict the outcome better than ours?

THE CRITERION IS IN `docs/PREREG_MARKET_VS_MODEL.md` AND WAS COMMITTED FIRST.
Read it before reading any number this prints. Nothing below chooses a
threshold, a population or a decision rule -- all three were fixed above the
measurement and are reproduced here only so the code and the document can be
checked against each other.

WHY IT MATTERS
--------------
The prop model is calibrated (+0.0133 nats over the base rate on 16,741
batter games, no price in sight) and its disagreements with the price lose
money (-13.4% flagged against a -9.1% control). Both are measured, and the
sentence that reconciles them is:

    Calibrated overall is not the same as calibrated conditional on
    disagreeing with the market.

If the de-vigged consensus is simply the better predictor, then betting our
disagreements cannot be profitable other than by luck, and no further input
-- platoon splits, park, weather, form -- changes that, because each one
makes us better OVERALL while the disagreements stay adversely selected.

Read-only. Adopts nothing.

Usage:
    python scripts/prereg_market_vs_model.py [--json]
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

from src.analysis import playerprops  # noqa: E402

# Fixed in the pre-registration, not here.
WEIGHT_GRID = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20260910

# A confident arm that said 0.0 on an event that happened would return an
# infinite log loss and destroy the mean. Clipping is a numerical necessity,
# not a modelling choice, and it is applied identically to every arm.
EPS = 1e-6

# The secondary "conditional on disagreement" slice. Declared in the
# pre-registration; conditioning on the model's own departure is exactly the
# selection the primary analysis exists to avoid, which is why it is secondary.
DISAGREEMENT = 0.05


def _log_loss(p, y):
    p = min(max(p, EPS), 1.0 - EPS)
    return -math.log(p) if y else -math.log(1.0 - p)


def _brier(p, y):
    return (p - y) ** 2


def _clustered_bootstrap(clusters, statistic, *, resamples, seed):
    """Resample whole player-nights, not single contracts.

    One batter's hits line and his total-bases line on the same night settle
    on the same at-bats. Treating them as two independent draws would shrink
    the interval by pretending to more information than exists.
    """
    keys = list(clusters)
    if len(keys) < 2:
        return None
    rng = random.Random(seed)
    draws = []
    for _ in range(resamples):
        picked = [clusters[rng.choice(keys)] for _ in keys]
        rows = [row for group in picked for row in group]
        value = statistic(rows)
        if value is not None:
            draws.append(value)
    if len(draws) < resamples // 2:
        return None
    draws.sort()
    lo = draws[int(0.025 * len(draws))]
    hi = draws[min(len(draws) - 1, int(0.975 * len(draws)))]
    return [lo, hi]


def _collect():
    """Build the scored population. Reads no outcome to decide membership."""
    props = _propboard.read_props()
    if not props:
        return None, "no captured prop prices"

    box, by_name = _propboard.read_batters()
    slots = _propboard.slot_index()
    contracts = _propboard.build_contracts(props)

    scored, skipped = [], defaultdict(int)
    for key, books in contracts.items():
        date, _event, player, market, line_text = key
        try:
            line = float(line_text)
        except (TypeError, ValueError):
            skipped["unreadable line"] += 1
            continue

        fair_overs, _best = _propboard.devig(books)
        if len(fair_overs) < _propboard.MIN_BOOKS:
            skipped[f"fewer than {_propboard.MIN_BOOKS} two-way books"] += 1
            continue

        prior = [r for r in by_name.get(player, ())
                 if str(r.get("date") or "") < str(date)]
        if not prior:
            skipped["no prior games for this batter"] += 1
            continue

        history = [r for r in box if str(r.get("date") or "") < str(date)]
        try:
            priced = playerprops.price_prop(
                market=market, line=line, batter_lines=prior,
                league=playerprops.league_rates(history),
                batting_slot=slots.get((str(date), player)))
        except playerprops.PropError:
            skipped["batter below the plate-appearance floor"] += 1
            continue

        outcome = _propboard.resolve(by_name, player, date, market, line)
        if outcome is None:
            skipped["no settled box score"] += 1
            continue

        scored.append({
            "date": str(date), "player": player, "market": market,
            "line": line, "outcome": outcome,
            "p_market": statistics.fmean(fair_overs),
            "p_model": priced["probability"],
            "books": len(fair_overs),
            "pa_sample": priced["batter_pa_sample"],
            "pa_source": priced["expected_pa_source"],
        })
    return (scored, dict(skipped)), None


def _arm_losses(rows, probability_of):
    if not rows:
        return None
    return {
        "log_loss": statistics.fmean(
            _log_loss(probability_of(r), r["outcome"]) for r in rows),
        "brier": statistics.fmean(
            _brier(probability_of(r), r["outcome"]) for r in rows),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    collected, error = _collect()
    if error:
        print(error, file=sys.stderr)
        return 1
    scored, skipped = collected

    if len(scored) < 200:
        print(f"only {len(scored)} scored contracts -- too few to compare two "
              f"predictors", file=sys.stderr)
        return 2

    base_rate = statistics.fmean(r["outcome"] for r in scored)

    arms = {
        "base_rate": _arm_losses(scored, lambda r: base_rate),
        "market": _arm_losses(scored, lambda r: r["p_market"]),
        "model": _arm_losses(scored, lambda r: r["p_model"]),
    }

    blend = {}
    for w in WEIGHT_GRID:
        blend[w] = _arm_losses(
            scored, lambda r, w=w: w * r["p_model"] + (1 - w) * r["p_market"])

    # THE PRIMARY STATISTIC: the paired per-contract difference. Positive
    # means the model loses to the market.
    def _paired(rows):
        if not rows:
            return None
        return statistics.fmean(
            _log_loss(r["p_model"], r["outcome"])
            - _log_loss(r["p_market"], r["outcome"]) for r in rows)

    clusters = defaultdict(list)
    for row in scored:
        clusters[(row["date"], row["player"])].append(row)

    d = _paired(scored)
    ci = _clustered_bootstrap(clusters, _paired,
                              resamples=BOOTSTRAP_RESAMPLES,
                              seed=BOOTSTRAP_SEED)

    if ci is None:
        verdict = "NOT MEASURABLE -- too few player-night clusters"
    elif ci[0] > 0:
        verdict = ("H2 SUPPORTED -- the market's number is the better "
                   "predictor")
    elif ci[1] < 0:
        verdict = "H1 SURVIVES -- our number carries information the price lacks"
    else:
        verdict = "UNDETERMINED -- the interval spans zero"

    # SECONDARY 1: per market.
    by_market = {}
    for market in sorted({r["market"] for r in scored}):
        rows = [r for r in scored if r["market"] == market]
        by_market[market] = {"n": len(rows), "paired_diff": _paired(rows)}

    # SECONDARY 2: conditional on disagreement -- the H1/H2 question in its
    # most direct form, and secondary precisely because the restriction
    # conditions on the model's own departure.
    apart = [r for r in scored
             if abs(r["p_model"] - r["p_market"]) > DISAGREEMENT]
    disagreement = None
    if len(apart) >= 30:
        model_closer = sum(
            1 for r in apart
            if abs(r["p_model"] - r["outcome"]) < abs(r["p_market"] - r["outcome"]))
        disagreement = {
            "n": len(apart),
            "model_closer_share": round(model_closer / len(apart), 4),
            "paired_diff": _paired(apart),
            "model_higher_share": round(
                sum(1 for r in apart if r["p_model"] > r["p_market"])
                / len(apart), 4),
        }

    # SECONDARY 3: concentration. A board whose findings are three lines from
    # one thin-sample batter is not a board.
    thin = [r for r in scored if (r["pa_sample"] or 0) < 100]
    concentration = {
        "distinct_batters": len({r["player"] for r in scored}),
        "share_with_thin_history": round(len(thin) / len(scored), 4),
        "paired_diff_thin": _paired(thin) if len(thin) >= 30 else None,
        "paired_diff_established": (
            _paired([r for r in scored if (r["pa_sample"] or 0) >= 100])),
    }

    report = {
        "criterion": "docs/PREREG_MARKET_VS_MODEL.md",
        "scored": len(scored),
        "clusters": len(clusters),
        "base_rate": round(base_rate, 4),
        "skipped": skipped,
        "arms": arms,
        "blend_log_loss": {str(w): v["log_loss"] for w, v in blend.items()},
        "paired_diff_nats": d,
        "paired_ci95": ci,
        "verdict": verdict,
        "by_market": by_market,
        "conditional_on_disagreement": disagreement,
        "concentration": concentration,
    }

    if args.json:
        print(json.dumps(report, indent=2, default=float))
        return 0

    print("MARKET vs MODEL -- pre-registered, criterion in")
    print(f"  {report['criterion']}")
    print()
    print(f"SCORED     {report['scored']} contracts across "
          f"{report['clusters']} player-nights")
    print(f"BASE RATE  {base_rate:.1%} of these overs hit")
    print(f"  skipped: {skipped}")
    print()
    print("  PREDICTIVE ACCURACY -- log loss in nats, LOWER IS BETTER")
    for name in ("base_rate", "market", "model"):
        a = arms[name]
        print(f"    {name:<12} {a['log_loss']:.5f} nats   "
              f"brier {a['brier']:.5f}")
    print()
    print("  THE PRIMARY STATISTIC -- paired per-contract difference,")
    print("  loss(model) - loss(market). Positive means the model loses.")
    print(f"    {d:+.5f} nats", end="")
    if ci:
        print(f"   95% clustered CI [{ci[0]:+.5f}, {ci[1]:+.5f}]")
    else:
        print()
    print()
    print(f"  VERDICT: {verdict}")
    print()
    print("  BLEND CURVE -- w * model + (1-w) * market. DESCRIPTIVE ONLY:")
    print("  its minimum is chosen on the same data that produced it, so an")
    print("  interior minimum is a candidate for a held-out test, never an")
    print("  adoption.")
    best_w = min(blend, key=lambda w: blend[w]["log_loss"])
    for w in WEIGHT_GRID:
        mark = "  <-- lowest" if w == best_w else ""
        print(f"    w={w:.1f}   {blend[w]['log_loss']:.5f}{mark}")
    print()
    print("  BY MARKET (secondary, descriptive -- nothing is promoted or")
    print("  dropped on the strength of it)")
    for market, v in by_market.items():
        print(f"    {market:<24} n={v['n']:<5} {v['paired_diff']:+.5f} nats")
    print()
    if disagreement:
        print("  CONDITIONAL ON DISAGREEMENT (secondary): the contracts where")
        print(f"  our number sits more than {DISAGREEMENT * 100:.0f} points from the market's.")
        print(f"    n={disagreement['n']}   our number landed closer "
              f"{disagreement['model_closer_share']:.1%} of the time")
        print(f"    paired difference {disagreement['paired_diff']:+.5f} nats")
        print(f"    we were the HIGHER number "
              f"{disagreement['model_higher_share']:.1%} of the time")
        print()
        print("    50% closer is a coin flip. Below 50% means that when we")
        print("    depart from the price, the price is usually right -- and")
        print("    departure is exactly what a value card selects on.")
        print()
    c = concentration
    print("  CONCENTRATION (secondary)")
    print(f"    {c['distinct_batters']} distinct batters; "
          f"{c['share_with_thin_history']:.1%} of contracts are batters with")
    print(f"    fewer than 100 prior plate appearances this season")
    if c["paired_diff_thin"] is not None:
        print(f"    thin history        {c['paired_diff_thin']:+.5f} nats")
    if c["paired_diff_established"] is not None:
        print(f"    established history {c['paired_diff_established']:+.5f} nats")
    print()
    print("  WHAT THIS CANNOT SAY: it measures accuracy, not profit. The link")
    print("  runs one way -- if the market's probability strictly dominates")
    print("  ours, betting our disagreements cannot pay except by luck. Being")
    print("  the better predictor does not by itself clear the vig.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
