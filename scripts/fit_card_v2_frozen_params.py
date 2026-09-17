"""T0a: the ONE-TIME 2025 fit that produces
data/processed/card_v2_frozen_params.json.

Reads ONLY:
  - data/historical/mlb_results.csv, filtered to 2025-04-15..2025-12-31
  - data/historical/pitcher_logs_2025.jsonl   (2025-only, backfilled for T0a)
  - data/historical/bullpen_log_2025.jsonl    (2025-only, backfilled for T0a)
  - data/processed/boxscores_2025.jsonl       (season-keyed store; 2025 only
    by construction of its filename)

Refuses any row dated 2026-01-01 or later -- belt and suspenders on top of
the fact that none of the four inputs above contain a 2026 row by
construction. Never reads data/processed/card_calibration.json (V1's live,
frozen-separately store) or any pitcher/bullpen row outside the 2025-only
files.

Writes data/processed/card_v2_frozen_params.json ONCE. Re-running this
script with the same inputs must reproduce the file byte for byte
(determinism proven by a separate check, not asserted here).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis import calibrate, strength, playerprops  # noqa: E402
from src.pipeline import features as features_mod  # noqa: E402
from src.pipeline import history, pitchers as pitcher_store  # noqa: E402
from src.pipeline import bullpen, boxscores  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEASON = "2025"
MIN_DATE = "2025-04-15"
MAX_DATE = "2025-12-31"
SEALED_START = "2026-01-01"

PITCHER_LOG_2025 = os.path.join(REPO, "data", "historical", "pitcher_logs_2025.jsonl")
BULLPEN_LOG_2025 = os.path.join(REPO, "data", "historical", "bullpen_log_2025.jsonl")
BOX_STORE_2025 = os.path.join(REPO, "data", "processed", "boxscores_2025.jsonl")
OUT_PATH = os.path.join(REPO, "data", "processed", "card_v2_frozen_params.json")

FAMILY = "nb1"
RUN_LINE = 1.5
MIN_PER_SLOT = 30
EPS = 1e-9


def _sealed_guard(date_str):
    if date_str and str(date_str) >= SEALED_START:
        raise SystemExit(f"REFUSED: row dated {date_str} is inside the sealed "
                          "2026-01-01..2026-08-27 window")


def _relief_rates(pen_log, cache={}):
    def _for(date):
        if date not in cache:
            cache[date] = {
                team: row.get("rate")
                for team, row in bullpen.relief_rates_by_team(pen_log, date).items()
                if row.get("rate")
            }
        return cache[date]
    return _for


def estimate_dispersion(rows, results_store, league):
    """Same procedure as scripts/test_run_dispersion_2025.py: mean of
    (observed - predicted)^2 / predicted per team-game, at the raw (no
    dispersion-adjusted) Poisson mean."""
    residuals = []
    for row in rows:
        actual = results_store.get(str(row["game_pk"])) or results_store.get(row["game_pk"]) or {}
        away = actual.get("away_score")
        home = actual.get("home_score")
        try:
            away, home = int(away), int(home)
        except (TypeError, ValueError):
            continue
        try:
            means = strength.run_means(row, league_rpg=league)
        except strength.StrengthError:
            continue
        for predicted, observed in ((means["away_mean"], away),
                                    (means["home_mean"], home)):
            if predicted > 0:
                residuals.append((observed - predicted) ** 2 / predicted)
    if not residuals:
        raise SystemExit("no residuals -- cannot estimate DISPERSION")
    return round(statistics.fmean(residuals), 4), len(residuals)


def fit_moneyline(rows, dispersion, relief_for):
    pairs = []
    skipped = 0
    with_bullpen = 0
    for row in rows:
        relief = relief_for(row["date"])
        away_pen = relief.get(row["away_team"])
        home_pen = relief.get(row["home_team"])
        if away_pen and home_pen:
            with_bullpen += 1
        features = {**row, "away_bullpen_rate": away_pen,
                    "home_bullpen_rate": home_pen}
        try:
            line = strength.model_line(features, league_rpg=fit_moneyline.league,
                                       dispersion=dispersion)
        except strength.StrengthError:
            skipped += 1
            continue
        pairs.append((line["p_home"], int(row["home_won"])))
    cal = calibrate.fit(pairs)
    return cal, skipped, with_bullpen, len(pairs)


def fit_runline(rows, dispersion, relief_for, results_store):
    """Side-level run-line cover calibration. Four (p, outcome) observations
    per game -- home -1.5, home +1.5, away -1.5, away +1.5 -- pooled into one
    Platt fit, since run-line covering is symmetric by side and by
    favourite/underdog and one fit is what registration 11.2 names
    ('the side-level run-line cover calibration'). Actual scores come from
    the results store by game_pk -- build_training_table's rows carry only
    the win/loss label, not the score, the same lookup estimate_dispersion
    uses."""
    pairs = []
    for row in rows:
        actual = (results_store.get(str(row["game_pk"]))
                 or results_store.get(row["game_pk"]) or {})
        try:
            margin = int(actual["home_score"]) - int(actual["away_score"])
        except (TypeError, ValueError, KeyError):
            continue
        relief = relief_for(row["date"])
        away_pen = relief.get(row["away_team"])
        home_pen = relief.get(row["home_team"])
        features = {**row, "away_bullpen_rate": away_pen,
                    "home_bullpen_rate": home_pen}
        try:
            means = strength.run_means(features, league_rpg=fit_moneyline.league)
            probs = strength.market_probabilities(
                means["away_mean"], means["home_mean"], run_line=RUN_LINE,
                dispersion=dispersion, family=FAMILY)
        except strength.StrengthError:
            continue
        pairs.append((probs["p_home_minus"], 1 if margin > RUN_LINE else 0))
        pairs.append((probs["p_home_plus"], 1 if margin > -RUN_LINE else 0))
        pairs.append((probs["p_away_minus"], 1 if margin < -RUN_LINE else 0))
        pairs.append((probs["p_away_plus"], 1 if margin < RUN_LINE else 0))
    cal = calibrate.fit(pairs)
    return cal, len(pairs)


def estimate_rho(box_store_2025):
    """Same procedure as scripts/test_prop_dispersion.py's _estimate_rho, run
    on the WHOLE 2025 season (this is a one-time freeze, not a fit/test
    split): excess variance of hits-per-game over the binomial implied by
    the model's own mean and plate appearances."""
    rows = [r for r in boxscores.read(box_store_2025) if r.get("type") == "batter"]
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

    predictions = []
    history_rows = []
    for date in dates:
        league = None
        if history_rows:
            try:
                league = playerprops.league_rates(history_rows)
            except playerprops.PropError:
                league = None
        if league:
            for row in by_date[date]:
                prior = [r for r in by_player[row["player_id"]]
                         if str(r.get("date") or "") < date]
                if not prior:
                    continue
                try:
                    rates = playerprops.batter_rates(prior, league)
                except playerprops.PropError:
                    continue
                pa = rates["pa_per_game"]
                if not pa or pa <= 0:
                    continue
                predictions.append((pa, rates["hit"], int(row.get("h") or 0)))
        history_rows.extend(by_date[date])

    ratios = []
    for pa, per_pa, hits in predictions:
        expected = pa * per_pa
        variance = pa * per_pa * (1 - per_pa)
        if variance <= 0 or pa <= 1:
            continue
        ratios.append(((hits - expected) ** 2 / variance, pa))
    if not ratios:
        raise SystemExit("no ratios -- cannot estimate RHO")
    dispersion = statistics.fmean(r for r, _ in ratios)
    mean_pa = statistics.fmean(pa for _, pa in ratios)
    if mean_pa <= 1:
        raise SystemExit("mean_pa <= 1 -- cannot estimate RHO")
    rho = (dispersion - 1.0) / (mean_pa - 1.0)
    return round(rho, 5), round(dispersion, 4), len(predictions)


def fit_slot_table(box_store_2025):
    """Slot -> mean plate appearances, from the 2025 boxscore store's own
    `batting_order` field (added for this task -- see src/providers/mlb.py
    `_batting_slot`). Unlike scripts/probe_lineup_slot.py this does not join
    against lineup_store (which holds 2026 lineups only and is off-limits
    for this task); the 2025 boxscore rows carry the batting slot each
    batter actually hit in directly."""
    rows = [r for r in boxscores.read(box_store_2025) if r.get("type") == "batter"]
    by_slot = defaultdict(list)
    for row in rows:
        slot = row.get("batting_order")
        pa = row.get("pa")
        if slot is None or pa is None:
            continue
        if not isinstance(slot, int) or not (1 <= slot <= 9):
            continue
        by_slot[slot].append(int(pa))
    table = {}
    counts = {}
    for slot, values in sorted(by_slot.items()):
        counts[slot] = len(values)
        if len(values) >= MIN_PER_SLOT:
            table[str(slot)] = round(statistics.fmean(values), 3)
    return table, counts


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT_PATH)
    args = ap.parse_args(argv)

    full_store = history.read_results()
    # The shared results store spans every season (2023-2026). Restrict to
    # the 2025 window BEFORE the sealed-window guard runs -- the guard's job
    # is to catch a 2026 row that slipped into the 2025-only slice, not to
    # reject the store for containing 2026 rows elsewhere, which it always
    # will (V1 reads the same file for its own live season).
    store = {k: v for k, v in full_store.items()
             if MIN_DATE <= str(v.get("date") or "") <= MAX_DATE}
    for row in store.values():
        _sealed_guard(row.get("date"))

    logs = pitcher_store.read_logs(PITCHER_LOG_2025)
    if not logs:
        raise SystemExit(f"no pitcher logs at {PITCHER_LOG_2025} -- run the "
                          "T0a pitcher/bullpen backfill first")
    for appearances in logs.values():
        for a in appearances:
            _sealed_guard(a.get("date"))

    pen_log = bullpen.read_log(BULLPEN_LOG_2025)
    if not pen_log:
        raise SystemExit(f"no bullpen log at {BULLPEN_LOG_2025} -- run the "
                          "T0a pitcher/bullpen backfill first")
    for row in pen_log:
        _sealed_guard(row.get("date"))

    if not os.path.exists(BOX_STORE_2025):
        raise SystemExit(f"no boxscore store at {BOX_STORE_2025}")
    for row in boxscores.read(BOX_STORE_2025):
        _sealed_guard(row.get("date"))

    table = features_mod.build_training_table(
        store, min_date=MIN_DATE, max_date=MAX_DATE,
        pitcher_logs=logs, require_complete=True)
    rows = table["rows"]
    if not rows:
        raise SystemExit(f"no usable {SEASON} games with full features")
    for row in rows:
        _sealed_guard(row.get("date"))

    league = strength.league_runs_per_game(rows)
    fit_moneyline.league = league  # shared with fit_runline

    dispersion, dispersion_n = estimate_dispersion(rows, store, league)

    relief_for = _relief_rates(pen_log, cache={})
    ml_cal, ml_skipped, ml_with_bullpen, ml_n = fit_moneyline(
        rows, dispersion, relief_for)
    rl_cal, rl_n = fit_runline(rows, dispersion, relief_for, store)
    rho, rho_dispersion, rho_n = estimate_rho(BOX_STORE_2025)
    slot_table, slot_counts = fit_slot_table(BOX_STORE_2025)

    blob = {
        "_header": {
            "purpose": "T0a frozen parameters for card v2 "
                       "(docs/PREREG_CARD_V2.md 11.2, docs/CARD_V2_BUILD_PLAN.md T0a)",
            "fitted_on": f"2025 regular season, {MIN_DATE} through {MAX_DATE}, "
                        "MLB Stats API (free), from data/historical/mlb_results.csv, "
                        "data/historical/pitcher_logs_2025.jsonl, "
                        "data/historical/bullpen_log_2025.jsonl and "
                        "data/processed/boxscores_2025.jsonl",
            "fitted_not_on": "2026-01-01 through 2026-08-27 is SEALED and was "
                             "never read by this script (see _sealed_guard calls "
                             "throughout scripts/fit_card_v2_frozen_params.py); "
                             "2023 and 2024 were not read either -- 2025 only",
            "fit_run_once": True,
            # NO wall-clock timestamp here on purpose: this file's sha256 is
            # cited in the registration and must reproduce byte for byte
            # from the same four inputs (T0a's determinism proof). A
            # `datetime.now()` field would make every run's hash different
            # even though nothing about the fit changed. The date this was
            # actually run is recorded in this task's report and in git,
            # not inside the frozen file.
            "owner_decision": "2026-09-15 22:35Z, question 3 answered no "
                              "('Rebuild on 2025'), option O1",
        },
        "DISPERSION": dispersion,
        "DISPERSION_FAMILY": FAMILY,
        "DISPERSION_n_team_games": dispersion_n,
        "moneyline_calibration": {**ml_cal.to_dict(),
                                  "skipped_no_model_line": ml_skipped,
                                  "games_with_relief_rate": ml_with_bullpen},
        "runline_calibration": {**rl_cal.to_dict(), "n_side_observations": rl_n},
        "RHO": rho,
        "RHO_observed_dispersion": rho_dispersion,
        "RHO_n_predictions": rho_n,
        "slot_plate_appearances": slot_table,
        "slot_sample_sizes": {str(k): v for k, v in slot_counts.items()},
        "model_id": strength.MODEL_ID,
        "season": SEASON,
        "games_used": len(rows),
        "league_runs_per_game": round(league, 4) if league else None,
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(blob, fh, indent=1, sort_keys=True)
        fh.write("\n")

    print(f"games used: {len(rows)}")
    print(f"DISPERSION={dispersion} (n={dispersion_n})")
    print(f"moneyline calibration: {ml_cal.to_dict()}")
    print(f"runline calibration: {rl_cal.to_dict()}")
    print(f"RHO={rho} (n={rho_n})")
    print(f"slot table: {slot_table}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
