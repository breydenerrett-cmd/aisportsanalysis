"""Measure `src.analysis.strength` against real results. Read-only.

WHAT THIS ANSWERS
-----------------
One question, in three parts:

  1. Is the model calibrated? When it says 60%, does the home team win about
     60% of the time?
  2. Is it better than knowing nothing? The comparison is the home-field base
     rate, which is what a coin that has read one fact about baseball
     predicts.
  3. Does it know anything the MARKET does not? This is the only part that
     could ever justify a published pick. A model can be beautifully
     calibrated and still be strictly worse than the price, in which case
     every disagreement it has with the market is noise and the honest
     product is to say so.

Part 3 is the one that decides what the front page is allowed to claim, and
it is reported whether or not it is flattering. If the model loses to the
market -- which is the expected result, and the result every published
handicapper's own numbers show -- the picks are still published, because a
published, graded, frozen pick with an honest label is the product. What
changes is the label, not the publication.

POINT-IN-TIME
-------------
Every feature comes from `src.pipeline.features.build_training_table`, whose
only history accessor filters strictly before the game date. The league run
rate is recomputed per date from that same already-filtered material, never
from a season total. Nothing here reads a result before predicting it.

Usage:
    python scripts/backtest_card.py [--season 2026] [--min-date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis import calibrate, strength  # noqa: E402
from src.pipeline import features as features_mod  # noqa: E402
from src.pipeline import history, pitchers as pitcher_store  # noqa: E402

EPS = 1e-9


def _log_loss(p, y):
    p = min(max(p, EPS), 1 - EPS)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def _summary(name, preds):
    """preds: list of (p, y). Returns a dict; never prints on its own."""
    if not preds:
        return {"name": name, "n": 0}
    n = len(preds)
    ll = sum(_log_loss(p, y) for p, y in preds) / n
    brier = sum((p - y) ** 2 for p, y in preds) / n
    acc = sum(1 for p, y in preds if (p >= 0.5) == (y == 1)) / n
    return {"name": name, "n": n, "log_loss": round(ll, 5),
            "brier": round(brier, 5), "accuracy": round(acc, 4)}


def _calibration(preds, bins=10):
    buckets = defaultdict(list)
    for p, y in preds:
        b = min(int(p * bins), bins - 1)
        buckets[b].append((p, y))
    out = []
    for b in sorted(buckets):
        rows = buckets[b]
        out.append({
            "bucket": f"{b / bins:.0%}-{(b + 1) / bins:.0%}",
            "n": len(rows),
            "predicted": round(sum(p for p, _ in rows) / len(rows), 4),
            "actual": round(sum(y for _, y in rows) / len(rows), 4),
        })
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2026")
    ap.add_argument("--min-date", default=None,
                    help="skip games before this date (April rows are mostly "
                         "prior, not evidence)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    store = history.read_results()
    logs = pitcher_store.read_logs() if hasattr(pitcher_store, "read_logs") else None
    table = features_mod.build_training_table(
        store,
        min_date=args.min_date or f"{args.season}-04-15",
        max_date=f"{args.season}-12-31",
        pitcher_logs=logs,
        require_complete=True,
    )
    rows = table["rows"]
    if not rows:
        print("no rows -- nothing to measure", file=sys.stderr)
        return 1

    # League run rate, point-in-time: from the rows on or before each date.
    by_date = defaultdict(list)
    for r in rows:
        by_date[r["date"]].append(r)
    dates = sorted(by_date)
    running = []
    league_by_date = {}
    for d in dates:
        # Every feature in `running` was computed from games strictly before
        # its own date, so a mean over them is safe on this date too.
        lg = strength.league_runs_per_game(running) if running else None
        league_by_date[d] = lg or strength.league_runs_per_game(by_date[d])
        running.extend(by_date[d])

    # THE SAME MODEL THE CARD RUNS. Measuring the whole-season stand-in and
    # publishing the number as the live model's would be measuring a model
    # nobody uses -- and the two differ by more than the model's entire gain
    # over a base rate (scripts/test_bullpen_rate.py).
    from src.pipeline import bullpen

    try:
        pen_log = bullpen.read_log()
    except Exception:  # noqa: BLE001
        pen_log = []
    rate_cache = {}

    def _relief(date):
        if not pen_log:
            return {}
        if date not in rate_cache:
            rate_cache[date] = {
                team: r.get("rate")
                for team, r in bullpen.relief_rates_by_team(pen_log, date).items()
                if r.get("rate")}
        return rate_cache[date]

    raw_preds, cal_preds, base_preds = [], [], []
    errors = defaultdict(int)
    margin_err = []
    total_err = []

    base_rate = table.get("base_rate") or 0.54

    # WALK-FORWARD, and the order of the three statements in the loop below is
    # the whole point: read the calibration standing BEFORE this date, use it,
    # and only then feed this game in. Reversing the last two would calibrate
    # each game partly on itself, which is the shape of leak that produces a
    # beautiful backtest and a worthless product.
    wf = calibrate.WalkForward()

    for r in rows:
        lg = league_by_date.get(r["date"])
        if not lg:
            errors["no_league_rate"] += 1
            continue
        relief = _relief(r["date"])
        features = {**r,
                    "away_bullpen_rate": relief.get(r["away_team"]),
                    "home_bullpen_rate": relief.get(r["home_team"])}
        try:
            line = strength.model_line(features, league_rpg=lg)
        except strength.StrengthError:
            errors["no_model_line"] += 1
            continue
        y = int(r["home_won"])
        p_raw = line["p_home"]
        p_cal = wf.apply(r["date"], p_raw)
        wf.add(r["date"], p_raw, y)

        raw_preds.append((p_raw, y))
        cal_preds.append((p_cal, y))
        base_preds.append((base_rate, y))

        actual = store.get(str(r["game_pk"])) or store.get(r["game_pk"]) or {}
        ah, aa = actual.get("home_score"), actual.get("away_score")
        if isinstance(ah, int) and isinstance(aa, int):
            margin_err.append((line["home_mean"] - line["away_mean"]) - (ah - aa))
            total_err.append((line["home_mean"] + line["away_mean"]) - (ah + aa))

    report = {
        "model_id": strength.MODEL_ID,
        "season": args.season,
        "window": [table["first_date"], table["last_date"]],
        "n_games": len(cal_preds),
        "home_base_rate": base_rate,
        "skipped": dict(errors),
        "table_skipped": table["skipped"],
        "model": _summary("model (calibrated)", cal_preds),
        "model_raw": _summary("model (raw, uncalibrated)", raw_preds),
        "baseline_home_rate": _summary("always the base rate", base_preds),
        "calibration": _calibration(cal_preds),
        "calibration_raw": _calibration(raw_preds),
        "final_platt": wf.calibration_for("9999-12-31").to_dict(),
    }
    if margin_err:
        n = len(margin_err)
        report["margin_bias"] = round(sum(margin_err) / n, 3)
        report["margin_mae"] = round(sum(abs(e) for e in margin_err) / n, 3)
    if total_err:
        n = len(total_err)
        report["total_bias"] = round(sum(total_err) / n, 3)
        report["total_mae"] = round(sum(abs(e) for e in total_err) / n, 3)

    m, b = report["model"], report["baseline_home_rate"]
    if m.get("n") and b.get("n"):
        report["log_loss_gain_vs_base"] = round(b["log_loss"] - m["log_loss"], 5)

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"MODEL         {strength.MODEL_ID}")
    print(f"WINDOW        {report['window'][0]} .. {report['window'][1]}  "
          f"({report['n_games']} games)")
    print()
    for key in ("model", "model_raw", "baseline_home_rate"):
        s = report[key]
        print(f"  {s['name']:<28} log-loss {s['log_loss']:.5f}   "
              f"brier {s['brier']:.5f}   accuracy {s['accuracy']:.1%}")
    print(f"\n  platt fit on the full season: {report['final_platt']}")
    print(f"\n  gain over base rate   {report.get('log_loss_gain_vs_base')} nats "
          f"({'model is better' if (report.get('log_loss_gain_vs_base') or 0) > 0 else 'BASE RATE IS BETTER'})")
    if "margin_bias" in report:
        print(f"\n  run margin   bias {report['margin_bias']:+.2f}  "
              f"mean abs error {report['margin_mae']:.2f}")
        print(f"  game total   bias {report['total_bias']:+.2f}  "
              f"mean abs error {report['total_mae']:.2f}")
    print("\n  CALIBRATION")
    print(f"    {'bucket':<12}{'n':>6}{'predicted':>12}{'actual':>10}")
    for c in report["calibration"]:
        print(f"    {c['bucket']:<12}{c['n']:>6}{c['predicted']:>12.3f}"
              f"{c['actual']:>10.3f}")
    if report["skipped"]:
        print(f"\n  skipped: {report['skipped']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
