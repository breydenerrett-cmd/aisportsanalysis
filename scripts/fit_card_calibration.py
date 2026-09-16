"""Fit the card model's Platt scaling on completed games. Writes one file.

FROZEN as of 2026-09-15 (owner decision; see
docs/CARD_CALIBRATION_FREEZE_2026-09-15.md). This script no longer runs
from `scripts/daily_loop.sh` -- the nightly refit was reading the sealed
2026-01-01..08-27 evaluation window every night
(docs/CARD_V2_DIAGNOSIS_2026-09-15.md section 0). The fitting code below is
unchanged and still works: `--out <path>` to anywhere other than the live
store still runs (2025-only research can reuse it), but writing
`data/processed/card_calibration.json` -- the live store the card reads --
now requires `--overwrite-frozen-store` in addition, so an accidental
`python scripts/fit_card_calibration.py` cannot quietly refit the frozen
file. Lifting the freeze for real needs a new dated owner decision, not
just the flag.

The fit uses only games that have FINISHED, so a card calibrated from its
output is calibrated on evidence that predates the games it prices and
never on its own -- the same walk-forward discipline
`scripts/backtest_card.py` measures under, executed rather than simulated.

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
        [--overwrite-frozen-store]
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


FREEZE_RECORD = "docs/CARD_CALIBRATION_FREEZE_2026-09-15.md"

# This repo's root, derived the same way the sys.path.insert above locates
# `src` -- used only to catch an absolute (or `..`-laden, or symlinked)
# `--out` that names this checkout's real live store by a different
# spelling than the literal relative path.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _writes_live_store(out_path: str) -> bool:
    """True when `out_path` names the live store the card actually reads
    (`src/report/card.py:CALIBRATION_STORE`). Two checks:

    1. Plain relative comparison, no `abspath` -- so a test can point
       `--out` at a temp-directory copy of the same relative path (with
       `cwd` set to that temp dir) and exercise the guard without ever
       touching this repo's real store.
    2. Resolved-path comparison against THIS repo's live store specifically
       -- so an absolute path (or one with `..` segments, or through a
       symlink) that resolves to this checkout's real
       `data/processed/card_calibration.json` cannot clear the guard just
       by being spelled differently. An absolute path to a *different*
       repo's or temp dir's same-named file still does not match, since
       the comparison is against this repo's resolved store, not the bare
       filename."""
    if os.path.normpath(out_path) == os.path.normpath(card_mod.CALIBRATION_STORE):
        return True
    live_store = os.path.realpath(os.path.join(REPO_ROOT, card_mod.CALIBRATION_STORE))
    return os.path.realpath(out_path) == live_store


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default=None,
                    help="defaults to the current year")
    ap.add_argument("--out", default=card_mod.CALIBRATION_STORE)
    ap.add_argument("--min-date", default=None)
    ap.add_argument("--overwrite-frozen-store", action="store_true",
                     help="required, in addition to --out, to write the "
                          "live store the card reads -- see " + FREEZE_RECORD)
    args = ap.parse_args(argv)

    # FROZEN 2026-09-15 (owner decision): refuse to write the live store
    # by accident. `--out` to anywhere else still runs the fit unchanged
    # below (2025-only research can reuse it); writing the live store back
    # needs this flag on top of that, and lifting the freeze for real needs
    # a new dated owner decision, not just the flag.
    if _writes_live_store(args.out) and not args.overwrite_frozen_store:
        print(f"refusing to write {args.out}: card calibration is frozen "
              f"by owner decision 2026-09-15, see {FREEZE_RECORD}",
              file=sys.stderr)
        return 1

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
