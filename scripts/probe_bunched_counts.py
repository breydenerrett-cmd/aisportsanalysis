"""Does the per-GAME model fix the two markets measured worse than nothing?

THE CLAIM UNDER TEST
--------------------
`playerprops.NOT_PUBLISHABLE` refuses two markets and names both the cause
and the cure:

    batter_rbis            over 0.5   -0.01353 nats   WORSE THAN A BASE RATE
    batter_hits_runs_rbis  over 1.5   -0.04033 nats   MUCH WORSE

    "...a home run with two aboard is three RBIs in a single plate
     appearance. Treating a per-PA rate as a Bernoulli trial and asking for
     'at least one' assumes those events arrive one at a time... The fix,
     when someone does it: model these off the batter's own per-GAME
     distribution rather than a per-PA rate, which carries the bunching for
     free. That is a different model and it needs its own measurement."

This is that measurement.

WHAT IS COMPARED
----------------
Three arms on the same batter-games, scored by mean log loss in nats (lower
is better), against the same point-in-time discipline the existing backtest
uses -- league rates and a batter's own history accumulate as the season
runs, and a prediction on date D sees only games strictly before D:

    base_rate   the pooled rate of the population itself -- the do-nothing
                floor, and the thing both markets currently lose to
    per_pa      the shipped model: playerprops.price_prop
    per_game    playerprops.empirical_over over the batter's own game log

WHAT WOULD CHANGE AS A RESULT
-----------------------------
Nothing automatically. If `per_game` beats `base_rate` the case exists to
take that market out of NOT_PUBLISHABLE, and that is a separate edit made
deliberately with this number quoted beside it. If it does not, the markets
stay refused and this file is the record of an attempt that failed --
published either way, same as every other measurement here.

Read-only. Adopts nothing.

Usage:
    python scripts/probe_bunched_counts.py [--json]
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
from src.paths import processed_path  # noqa: E402
from src.pipeline import boxscores  # noqa: E402

BOX_STORE = processed_path("boxscores_2026.jsonl")

# The lines NOT_PUBLISHABLE measured, so this is comparable to the number it
# is trying to beat. Not swept: a line chosen after seeing the answer is a
# free parameter.
LINES = {"batter_rbis": 0.5, "batter_hits_runs_rbis": 1.5}

# Probabilities are clipped before a logarithm, because a confident arm that
# said 0.0 on an event that happened would otherwise return infinity and
# destroy the mean.
CLIP = 1e-6


def _clip(p):
    return min(max(float(p), CLIP), 1.0 - CLIP)


def _log_loss(pairs):
    if not pairs:
        return None
    return statistics.fmean(
        -(math.log(_clip(p)) if y else math.log(1.0 - _clip(p)))
        for p, y in pairs)


def _outcome(row, market):
    """The quantity the bet settles on -- the same field the backtest uses,
    so the thing modelled and the thing graded cannot drift apart."""
    value = playerprops.game_count(row, market)
    return 0 if value is None else value


def measure(market, line, rows):
    by_player = defaultdict(list)
    by_date = defaultdict(list)
    for row in rows:
        date = str(row.get("date") or "")
        if not date or not row.get("player_id"):
            continue
        by_player[row["player_id"]].append(row)
        by_date[date].append(row)
    for lines in by_player.values():
        lines.sort(key=lambda r: str(r.get("date") or ""))

    per_pa, per_game, outcomes = [], [], []
    refused = defaultdict(int)
    history = []

    for date in sorted(by_date):
        league = None
        if history:
            try:
                league = playerprops.league_rates(history)
            except playerprops.PropError:
                league = None
        league_counts = ([playerprops.game_count(r, market) for r in history]
                         if history else [])
        league_counts = [c for c in league_counts if c is not None]

        if league and league_counts:
            for row in by_date[date]:
                prior = [r for r in by_player[row["player_id"]]
                         if str(r.get("date") or "") < date]
                if not prior:
                    refused["no prior games"] += 1
                    continue
                # BOTH ARMS OR NEITHER. Scoring the two on different
                # populations would compare a model on the batters it likes
                # against another on everyone, which is not a comparison.
                try:
                    priced = playerprops.price_prop(
                        market=market, line=line, batter_lines=prior,
                        league=league)
                except playerprops.PropError as exc:
                    refused["per-PA floor" if "floor" in str(exc)
                            else str(exc)[:40]] += 1
                    continue
                try:
                    empirical = playerprops.empirical_over(
                        playerprops.game_counts(prior, market), line,
                        league_counts)
                except playerprops.PropError as exc:
                    refused["per-game floor" if "floor" in str(exc)
                            else str(exc)[:40]] += 1
                    continue

                hit = 1 if _outcome(row, market) > line else 0
                per_pa.append((priced["probability"], hit))
                per_game.append((empirical, hit))
                outcomes.append(hit)

        history.extend(by_date[date])

    span = sorted(by_date)
    if not outcomes:
        return {"market": market, "line": line, "n": 0,
                "refused": dict(refused), "date_count": len(span),
                "dates": f"{span[0]} .. {span[-1]}" if span else "none"}

    base = statistics.fmean(outcomes)
    base_loss = _log_loss([(base, y) for y in outcomes])
    pa_loss = _log_loss(per_pa)
    game_loss = _log_loss(per_game)
    return {
        "market": market, "line": line, "n": len(outcomes),
        "base_rate": base,
        "base_log_loss": base_loss,
        "per_pa_log_loss": pa_loss,
        "per_game_log_loss": game_loss,
        "per_pa_gain_nats": base_loss - pa_loss,
        "per_game_gain_nats": base_loss - game_loss,
        "per_pa_mean": statistics.fmean(p for p, _ in per_pa),
        "per_game_mean": statistics.fmean(p for p, _ in per_game),
        "refused": dict(refused),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    rows = [r for r in boxscores.read(BOX_STORE) if r.get("type") == "batter"]
    if not rows:
        print("no boxscore batter rows stored", file=sys.stderr)
        return 1

    print("=" * 76)
    print("BUNCHED COUNTS -- does modelling per GAME beat the base rate?")
    print("=" * 76)
    print(f"  {len(rows)} batter-games in the store")
    print("  Lines are the ones NOT_PUBLISHABLE measured, not swept.")
    print()

    results = []
    for market, line in LINES.items():
        got = measure(market, line, rows)
        results.append(got)
        print(f"{market}  over {line}")
        if not got.get("n"):
            # NOT "no effect". A measurement that could not run is a
            # different fact from one that ran and found nothing, and
            # printing them the same way is how the second gets claimed on
            # the strength of the first.
            print("  *** THIS MEASUREMENT COULD NOT RUN. ***")
            print(f"  refused: {got.get('refused')}")
            print()
            print(f"  The store covers {got.get('dates', '?')} -- "
                  f"{got.get('date_count', 0)} dates. Both arms need history")
            print(f"  a batter does not have yet: the shipped per-PA model "
                  f"refuses below")
            print(f"  {playerprops.MIN_PA_FOR_A_RATE} plate appearances "
                  f"(about ten games) and the per-game model below")
            print(f"  {playerprops.MIN_GAMES_FOR_A_RATE} games, so on a "
                  f"{got.get('date_count', 0)}-date window almost no batter "
                  f"qualifies.")
            print()
            print("  This is a DATA blocker, not a result. Nothing is")
            print("  concluded about either model, the markets stay refused,")
            print("  and re-running this in two to three weeks -- or against")
            print("  a backfilled season -- is what answers it.")
            print()
            continue
        print(f"  n={got['n']}   cleared {got['base_rate']:.1%} of the time")
        print(f"  {'arm':<12} {'log loss':>10} {'vs base':>12} "
              f"{'mean p':>9}")
        print(f"  {'base rate':<12} {got['base_log_loss']:10.5f} "
              f"{'--':>12} {got['base_rate']:9.3f}")
        print(f"  {'per PA':<12} {got['per_pa_log_loss']:10.5f} "
              f"{got['per_pa_gain_nats']:+12.5f} {got['per_pa_mean']:9.3f}")
        print(f"  {'per GAME':<12} {got['per_game_log_loss']:10.5f} "
              f"{got['per_game_gain_nats']:+12.5f} "
              f"{got['per_game_mean']:9.3f}")
        better = got["per_game_gain_nats"] > 0
        print()
        if better:
            print("  -> per-GAME beats the base rate. The case exists to take")
            print("     this market out of NOT_PUBLISHABLE, quoting this")
            print("     number beside the edit.")
        else:
            print("  -> per-GAME does NOT beat the base rate. The market stays")
            print("     refused and this is the record of an attempt that")
            print("     failed.")
        if got["refused"]:
            print(f"  refused: {got['refused']}")
        print()

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
