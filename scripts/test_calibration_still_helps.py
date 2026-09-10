"""Does the Platt layer still earn its place after the dispersion fix?

    CRITERION FIXED HERE, ABOVE THE MEASUREMENT, BEFORE IT WAS RUN.

    FIT       Platt on 2025 only. One fit, frozen.
    TEST      2026 only. The fit never sees a 2026 game.
    KEEP CALIBRATION if it improves moneyline log-loss on 2026 by >= 0.0005
                     nats AND improves in both halves of the season.
    DROP IT   if it is worse by more than 0.0005 nats in both halves.
    NEITHER   leave it in place. A layer that neither helps nor hurts is
              left alone, because removing it is a change and changes need a
              reason.

WHY THE QUESTION
----------------
`src.analysis.calibrate` exists because the raw model was badly
overconfident: it said 73% about games the home team won 60% of, and Platt
scaling pulled it back. That overconfidence had a cause, and on 2026-09-10
the cause was fixed -- run variance is 2.33x the mean, not 1.0x, and
`strength.DISPERSION` now says so (docs/PREREG_RUN_DISPERSION.md).

Since then the fitted shrink has relaxed from b = 0.489 to b = 0.708, and
over the full 2026 season the RAW model's log-loss (0.68831) is now BETTER
than the walk-forward calibrated one (0.69137). A correction built for a
fault that no longer exists at the same size may now be over-correcting.

WHY THIS SPLIT AND NOT THE WALK-FORWARD ONE
--------------------------------------------
The 0.69137 figure comes from walk-forward calibration, which in April fits
on a handful of games and is mostly noise -- so part of the gap is the
procedure warming up rather than the layer being wrong. Fitting once on a
whole separate season and applying it to another removes that entirely and
asks the question directly.

It also means the answer is not contaminated by the season it is scored on,
which the walk-forward version cannot promise.

Read-only. Adopts nothing.

Usage:
    python scripts/test_calibration_still_helps.py [--json]
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

from src.analysis import calibrate, strength  # noqa: E402
from src.pipeline import bullpen, features as features_mod  # noqa: E402
from src.pipeline import history, pitchers as pitcher_store  # noqa: E402

FIT_SEASON = "2025"
TEST_SEASON = "2026"
DECISION_MARGIN = 0.0005
EPS = 1e-9


def _int(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _log_loss(pairs):
    if not pairs:
        return None
    return statistics.fmean(
        -(y * math.log(min(max(p, EPS), 1 - EPS))
          + (1 - y) * math.log(1 - min(max(p, EPS), 1 - EPS)))
        for p, y in pairs)


def _calibration_table(pairs, bins=10):
    buckets = defaultdict(list)
    for p, y in pairs:
        buckets[min(int(p * bins), bins - 1)].append((p, y))
    return [{"bucket": f"{b / bins:.0%}-{(b + 1) / bins:.0%}",
             "n": len(rows),
             "predicted": round(statistics.fmean(p for p, _ in rows), 4),
             "actual": round(statistics.fmean(y for _, y in rows), 4)}
            for b, rows in sorted(buckets.items())]


def _raw_predictions(store, season, logs, pen_log):
    """(p_home, home_won) for every usable game in a season, uncalibrated."""
    table = features_mod.build_training_table(
        store, min_date=f"{season}-04-15", max_date=f"{season}-12-31",
        pitcher_logs=logs, require_complete=True)
    rows = table["rows"]
    if not rows:
        return []
    league = strength.league_runs_per_game(rows)
    pen_cache = {}

    def pens_for(date):
        if not pen_log:
            return {}
        if date not in pen_cache:
            pen_cache[date] = {
                t: r.get("rate")
                for t, r in bullpen.relief_rates_by_team(pen_log, date).items()
                if r.get("rate")}
        return pen_cache[date]

    out = []
    for row in rows:
        actual = store.get(str(row["game_pk"])) or {}
        if _int(actual.get("home_score")) is None:
            continue
        pens = pens_for(row["date"])
        feats = {**row,
                 "away_bullpen_rate": pens.get(row["away_team"]),
                 "home_bullpen_rate": pens.get(row["home_team"])}
        try:
            line = strength.model_line(feats, league_rpg=league)
        except strength.StrengthError:
            continue
        out.append((line["p_home"], int(row["home_won"])))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    store = history.read_results()
    logs = pitcher_store.read_logs() or None
    try:
        pen_log = bullpen.read_log()
    except Exception:  # noqa: BLE001
        pen_log = []

    fit_rows = _raw_predictions(store, FIT_SEASON, logs, pen_log)
    test_rows = _raw_predictions(store, TEST_SEASON, logs, pen_log)
    if len(fit_rows) < 500 or len(test_rows) < 500:
        print(f"need both seasons: fit={len(fit_rows)} test={len(test_rows)}",
              file=sys.stderr)
        return 1

    # ONE FIT, on the fit season only. It never sees a test-season game.
    cal = calibrate.fit(fit_rows)

    raw = list(test_rows)
    calibrated = [(cal.apply(p), y) for p, y in test_rows]
    half = len(raw) // 2

    raw_loss = _log_loss(raw)
    cal_loss = _log_loss(calibrated)
    gain = raw_loss - cal_loss

    halves = []
    for lo, hi in ((0, half), (half, len(raw))):
        halves.append({
            "raw": round(_log_loss(raw[lo:hi]), 6),
            "calibrated": round(_log_loss(calibrated[lo:hi]), 6),
        })
    both_better = all(h["calibrated"] < h["raw"] for h in halves)
    both_worse = all(h["calibrated"] > h["raw"] for h in halves)

    if gain >= DECISION_MARGIN and both_better:
        verdict = "KEEP CALIBRATION"
    elif gain <= -DECISION_MARGIN and both_worse:
        verdict = "DROP CALIBRATION"
    else:
        verdict = "NEITHER -- leave it in place"

    report = {
        "fit_season": FIT_SEASON, "fit_games": len(fit_rows),
        "test_season": TEST_SEASON, "test_games": len(test_rows),
        "fit": cal.to_dict(),
        "raw_log_loss": round(raw_loss, 6),
        "calibrated_log_loss": round(cal_loss, 6),
        "gain_from_calibrating": round(gain, 6),
        "halves": halves,
        "verdict": verdict,
        "raw_calibration_table": _calibration_table(raw),
        "calibrated_calibration_table": _calibration_table(calibrated),
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"FIT   {FIT_SEASON}  {report['fit_games']} games -> {report['fit']}")
    print(f"TEST  {TEST_SEASON}  {report['test_games']} games "
          f"(the fit never saw one of these)")
    print()
    print(f"  raw            log-loss {report['raw_log_loss']:.6f}")
    print(f"  calibrated     log-loss {report['calibrated_log_loss']:.6f}")
    print(f"  calibrating is worth {report['gain_from_calibrating']:+.6f} nats "
          f"(margin {DECISION_MARGIN})")
    print(f"  halves: 1st raw {halves[0]['raw']:.6f} vs cal "
          f"{halves[0]['calibrated']:.6f}   "
          f"2nd raw {halves[1]['raw']:.6f} vs cal "
          f"{halves[1]['calibrated']:.6f}")
    print(f"\n  ==> {verdict}")
    print()
    print(f"{'bucket':<12}{'n':>6}{'raw pred':>11}{'cal pred':>11}{'actual':>10}")
    cal_by_bucket = {r["bucket"]: r for r in report["calibrated_calibration_table"]}
    for row in report["raw_calibration_table"]:
        c = cal_by_bucket.get(row["bucket"], {})
        print(f"{row['bucket']:<12}{row['n']:>6}{row['predicted']:>11.4f}"
              f"{c.get('predicted', float('nan')):>11.4f}{row['actual']:>10.4f}")
    print()
    print("  The two 'pred' columns are the same games read two ways; the")
    print("  question is which sits closer to 'actual' across the table.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
