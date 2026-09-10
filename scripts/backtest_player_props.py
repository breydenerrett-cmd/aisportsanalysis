"""Is the player-prop model calibrated? Measured on real batter games.

WHAT THIS ANSWERS, AND WHY IT COMES BEFORE ANY TALK OF VALUE
------------------------------------------------------------
The owner's criterion for a bet is exact and correct: our numbers say a
hitter clears his line more than half the time, the book pays +110, take it.
That criterion is only worth anything **if our number is calibrated**. If we
say 52% and the truth is 48%, +110 is a losing bet placed with confidence.

So this measures calibration and nothing else. It reads no prices at all.
When it says the model is honest at 55%, a later script can go looking for
55% priced at +110; until it does, there is nothing to look for.

POINT-IN-TIME BY CONSTRUCTION
-----------------------------
Each batter's rates come only from his own games STRICTLY BEFORE the one
being predicted. The league rates likewise. A game on the prediction date
contributes nothing to its own prediction.

Expected plate appearances come from the batter's own PA-per-game to date,
which encodes his lineup slot without needing the lineup card. That is what
makes this measurable today: **the backtest does not need lineups, only the
live product does** -- you cannot bet a man who is not playing.

Usage:
    python scripts/backtest_player_props.py [--market batter_hits] [--line 0.5]
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
from src.pipeline import boxscores  # noqa: E402

BOX_STORE = os.path.join("data", "processed", "boxscores_2026.jsonl")
EPS = 1e-9

# The line each market is quoted at most often, from the captured price
# store. Priced here because that is what a reader would actually be
# offered, not because it is the easiest to model.
DEFAULT_LINES = {
    "batter_hits": 0.5,
    "batter_total_bases": 1.5,
    "batter_home_runs": 0.5,
    "batter_runs_scored": 0.5,
    "batter_rbis": 0.5,
    "batter_hits_runs_rbis": 1.5,
}

# Below this the calibration table is reading noise.
MIN_PREDICTIONS = 500


def _outcome(row, market):
    """Did this batter's real line clear it? Returns the countable quantity."""
    if market == "batter_hits":
        return int(row.get("h") or 0)
    if market == "batter_total_bases":
        return int(row.get("total_bases") or 0)
    if market == "batter_home_runs":
        return int(row.get("hr") or 0)
    if market == "batter_runs_scored":
        return int(row.get("r") or 0)
    if market == "batter_rbis":
        return int(row.get("rbi") or 0)
    if market == "batter_hits_runs_rbis":
        return int(row.get("hits_runs_rbi") or 0)
    raise ValueError(market)


def _log_loss(pairs):
    if not pairs:
        return None
    return statistics.fmean(
        -(y * math.log(min(max(p, EPS), 1 - EPS))
          + (1 - y) * math.log(1 - min(max(p, EPS), 1 - EPS)))
        for p, y in pairs)


def _calibration(pairs, bins=10):
    buckets = defaultdict(list)
    for p, y in pairs:
        buckets[min(int(p * bins), bins - 1)].append((p, y))
    return [{"bucket": f"{b / bins:.0%}-{(b + 1) / bins:.0%}",
             "n": len(rows),
             "predicted": round(statistics.fmean(p for p, _ in rows), 4),
             "actual": round(statistics.fmean(y for _, y in rows), 4),
             "gap": round(statistics.fmean(p for p, _ in rows)
                          - statistics.fmean(y for _, y in rows), 4)}
            for b, rows in sorted(buckets.items())]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="batter_hits",
                    choices=sorted(playerprops.SUPPORTED_MARKETS) + ["all"])
    ap.add_argument("--line", type=float, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    rows = [r for r in boxscores.read(BOX_STORE) if r.get("type") == "batter"]
    if not rows:
        print("no boxscore batter rows stored", file=sys.stderr)
        return 1

    # Everything indexed by date, so "strictly before" is a slice rather than
    # a filter over the whole store per prediction.
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

    dates = sorted(by_date)
    markets = (sorted(playerprops.SUPPORTED_MARKETS)
               if args.market == "all" else [args.market])

    report = {"store_rows": len(rows), "players": len(by_player),
              "dates": [dates[0], dates[-1]], "markets": {}}

    for market in markets:
        line = args.line if args.line is not None else DEFAULT_LINES[market]
        pairs = []
        refused = defaultdict(int)

        # League rates accumulate as the season runs, so a prediction on
        # date D sees only games before D.
        history = []
        for date in dates:
            if history:
                try:
                    league = playerprops.league_rates(history)
                except playerprops.PropError:
                    league = None
            else:
                league = None

            if league:
                for row in by_date[date]:
                    prior = [r for r in by_player[row["player_id"]]
                             if str(r.get("date") or "") < date]
                    if not prior:
                        refused["no_prior_games"] += 1
                        continue
                    try:
                        priced = playerprops.price_prop(
                            market=market, line=line, batter_lines=prior,
                            league=league)
                    except playerprops.PropError as exc:
                        # GROUPED BY CAUSE, not by the number in the message.
                        # Keying on the raw text produced one bucket per
                        # distinct plate-appearance count -- forty lines of
                        # noise that buried the one fact that matters, which
                        # is how many batters the floor turned away.
                        message = str(exc)
                        cause = ("below the plate-appearance floor"
                                 if "floor" in message else message[:48])
                        refused[cause] += 1
                        continue
                    got = _outcome(row, market)
                    pairs.append((priced["probability"],
                                  1 if got > line else 0))
            history.extend(by_date[date])

        if len(pairs) < MIN_PREDICTIONS:
            report["markets"][market] = {
                "line": line, "n": len(pairs),
                "refused": dict(refused),
                "verdict": f"NOT MEASURED -- {len(pairs)} predictions is "
                           f"below the {MIN_PREDICTIONS} floor",
            }
            continue

        base = statistics.fmean(y for _, y in pairs)
        report["markets"][market] = {
            "line": line,
            "n": len(pairs),
            "refused": dict(refused),
            "base_rate": round(base, 4),
            "mean_prediction": round(statistics.fmean(p for p, _ in pairs), 4),
            "log_loss": round(_log_loss(pairs), 5),
            "base_log_loss": round(_log_loss([(base, y) for _, y in pairs]), 5),
            "calibration": _calibration(pairs),
        }
        report["markets"][market]["gain_nats"] = round(
            report["markets"][market]["base_log_loss"]
            - report["markets"][market]["log_loss"], 5)

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"BOXSCORE STORE  {report['store_rows']} batter rows, "
          f"{report['players']} players, "
          f"{report['dates'][0]} .. {report['dates'][1]}")
    for market, m in report["markets"].items():
        print(f"\n=== {market} over {m['line']} ===")
        if "verdict" in m:
            print(f"  {m['verdict']}")
            if m["refused"]:
                print(f"  refused: {m['refused']}")
            continue
        print(f"  {m['n']} predictions   "
              f"cleared {m['base_rate']:.1%} of the time   "
              f"model said {m['mean_prediction']:.1%} on average")
        print(f"  log-loss {m['log_loss']:.5f} against a base rate of "
              f"{m['base_log_loss']:.5f}   gain {m['gain_nats']:+.5f} nats")
        if m["refused"]:
            print(f"  refused: {m['refused']}")
        print(f"    {'bucket':<12}{'n':>7}{'predicted':>11}{'actual':>9}{'gap':>8}")
        for c in m["calibration"]:
            print(f"    {c['bucket']:<12}{c['n']:>7}{c['predicted']:>11.3f}"
                  f"{c['actual']:>9.3f}{c['gap']:>+8.3f}")
    print()
    print("  NO PRICE WAS READ BY THIS SCRIPT. Calibration first: a 55% that")
    print("  is really 55% is worth hunting for at +110. A 55% that is really")
    print("  48% is a losing bet placed with confidence, and the only way to")
    print("  tell the two apart is the table above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
