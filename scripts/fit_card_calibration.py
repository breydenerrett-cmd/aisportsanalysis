"""Fit the card model's Platt scaling on completed games. Writes one file.

Runs nightly from `scripts/daily_loop.sh`. The fit uses only games that have
FINISHED, so tonight's card is calibrated on yesterday's evidence and never
on its own -- the same walk-forward discipline `scripts/backtest_card.py`
measures under, executed rather than simulated.

The output is small and boring on purpose:

    {"a": 0.03, "b": 0.507, "n": 1896, "base_rate": 0.521,
     "fitted": true, "fitted_through": "2026-09-09", "fitted_at": "..."}

`b` below 1 means the model is being told to be less sure than it is. On the
2026 season it lands near 0.5 -- the raw model's confidence is roughly twice
what its accuracy earns. That number is worth watching: if it drifts toward
1 the model is getting better, and if it drifts toward 0 the model is
becoming noise with a shape.

Usage:
    python scripts/fit_card_calibration.py [--season 2026] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis import calibrate, strength  # noqa: E402
from src.pipeline import features as features_mod  # noqa: E402
from src.pipeline import history, pitchers as pitcher_store  # noqa: E402
from src.report import card as card_mod  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default=None,
                    help="defaults to the current year")
    ap.add_argument("--out", default=card_mod.CALIBRATION_STORE)
    ap.add_argument("--min-date", default=None)
    args = ap.parse_args(argv)

    season = args.season or str(datetime.now(timezone.utc).year)
    store = history.read_results()
    if not store:
        print("no results store -- nothing to fit on", file=sys.stderr)
        return 1

    logs = pitcher_store.read_logs() or None
    table = features_mod.build_training_table(
        store,
        min_date=args.min_date or f"{season}-04-15",
        max_date=f"{season}-12-31",
        pitcher_logs=logs,
        require_complete=True,
    )
    rows = table["rows"]
    if not rows:
        print(f"no completed {season} games with full features", file=sys.stderr)
        return 1

    league = strength.league_runs_per_game(rows)

    # THE SAME MODEL THE CARD RUNS, including the real relief rate. Without
    # this the Platt fit describes a DIFFERENT model from the one whose
    # probabilities it is used to correct -- fitted on the whole-season
    # stand-in, applied to the relief-rate version -- and the correction
    # would be wrong by however much the two differ. Rebuilt per date
    # because the rates are identical for every game on a slate.
    from src.pipeline import bullpen  # noqa: PLC0415 -- optional store

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
                team: row.get("rate")
                for team, row in bullpen.relief_rates_by_team(pen_log, date).items()
                if row.get("rate")}
        return rate_cache[date]

    pairs = []
    skipped = 0
    with_bullpen = 0
    for row in rows:
        relief = _relief(row["date"])
        away_pen = relief.get(row["away_team"])
        home_pen = relief.get(row["home_team"])
        if away_pen and home_pen:
            with_bullpen += 1
        features = {**row, "away_bullpen_rate": away_pen,
                    "home_bullpen_rate": home_pen}
        try:
            line = strength.model_line(features, league_rpg=league)
        except strength.StrengthError:
            skipped += 1
            continue
        pairs.append((line["p_home"], int(row["home_won"])))

    cal = calibrate.fit(pairs)
    blob = cal.to_dict()
    blob.update({
        "model_id": strength.MODEL_ID,
        "season": season,
        "fitted_through": table["last_date"],
        "fitted_at": datetime.now(timezone.utc).isoformat(),
        "skipped_no_model_line": skipped,
        "games_with_relief_rate": with_bullpen,
    })

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(blob, fh, indent=1, sort_keys=True)
        fh.write("\n")

    print(f"fitted on {cal.n} games through {table['last_date']}: "
          f"a={cal.a:+.4f} b={cal.b:.4f} "
          f"({'USED' if blob['fitted'] else 'NOT ENOUGH GAMES -- base rate'})")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
