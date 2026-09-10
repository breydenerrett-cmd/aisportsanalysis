"""Run the pre-registered dispersion test. docs/PREREG_RUN_DISPERSION.md.

The windows, the metric and the adoption criterion are all fixed in that
document and are transcribed here as constants rather than accepted as
arguments -- a window a caller can move is not a pre-registered window.

    FIT        2026-04-15 .. 2026-07-15
    EVALUATE   2026-07-16 onward
    ADOPT if   run-line calibration error falls by >= 50%
               AND moneyline log-loss degrades by <= 0.001 nats
               AND the improvement holds in BOTH halves of the eval window
               AND the fitted dispersion is stable across the fit window

Read-only. Prints the verdict, adopts nothing. Changing
`strength.DISPERSION` is a separate, deliberate edit made only if this says
so, and the result is written into the pre-registration either way.

Usage:
    python scripts/test_run_dispersion.py [--json]
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
from src.pipeline import features as features_mod  # noqa: E402
from src.pipeline import history, pitchers as pitcher_store  # noqa: E402

# TRANSCRIBED FROM THE PRE-REGISTRATION. Not arguments.
FIT_START = "2026-04-15"
FIT_END = "2026-07-15"
EVAL_START = "2026-07-16"

CALIBRATION_IMPROVEMENT_REQUIRED = 0.50
MAX_LOGLOSS_DEGRADATION = 0.001
MAX_DISPERSION_DRIFT = 0.30
CALIBRATION_BINS = 10
EPS = 1e-9


def _int(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _rows(store, logs, min_date, max_date):
    table = features_mod.build_training_table(
        store, min_date=min_date, max_date=max_date, pitcher_logs=logs,
        require_complete=True)
    return table["rows"]


def _dispersion_of(rows, store, league):
    """Mean squared Pearson residual against this model's own means."""
    residuals = []
    for row in rows:
        actual = store.get(str(row["game_pk"])) or store.get(row["game_pk"]) or {}
        away, home = _int(actual.get("away_score")), _int(actual.get("home_score"))
        if away is None or home is None:
            continue
        try:
            means = strength.run_means(row, league_rpg=league)
        except strength.StrengthError:
            continue
        for predicted, observed in ((means["away_mean"], away),
                                    (means["home_mean"], home)):
            if predicted > 0:
                residuals.append((observed - predicted) ** 2 / predicted)
    return statistics.fmean(residuals) if residuals else None


def _score_window(rows, store, league, dispersion, family):
    """(run-line calibration error, moneyline log-loss) for one setting."""
    pairs_rl, pairs_ml = [], []
    for row in rows:
        actual = store.get(str(row["game_pk"])) or store.get(row["game_pk"]) or {}
        away, home = _int(actual.get("away_score")), _int(actual.get("home_score"))
        if away is None or home is None:
            continue
        try:
            means = strength.run_means(row, league_rpg=league)
        except strength.StrengthError:
            continue
        probs = strength.market_probabilities(
            means["away_mean"], means["home_mean"], run_line=1.5,
            dispersion=dispersion, family=family)
        # THE PRIMARY QUANTITY: P(decided by two or more runs). Symmetric,
        # so it does not depend on which club is the favourite and cannot be
        # gamed by the direction split that broke the first market probe.
        p_two_plus = probs["p_home_minus"] + probs["p_away_minus"]
        pairs_rl.append((p_two_plus, 1 if abs(home - away) >= 2 else 0))
        pairs_ml.append((probs["p_home"], int(row["home_won"])))
    return pairs_rl, pairs_ml


def _calibration_error(pairs, bins=CALIBRATION_BINS):
    """Sample-weighted mean absolute gap between predicted and observed."""
    if not pairs:
        return None
    buckets = defaultdict(list)
    for p, y in pairs:
        buckets[min(int(p * bins), bins - 1)].append((p, y))
    total = sum(len(v) for v in buckets.values())
    error = 0.0
    for rows in buckets.values():
        predicted = statistics.fmean(p for p, _ in rows)
        observed = statistics.fmean(y for _, y in rows)
        error += len(rows) / total * abs(predicted - observed)
    return error


def _log_loss(pairs):
    if not pairs:
        return None
    return statistics.fmean(
        -(y * math.log(min(max(p, EPS), 1 - EPS))
          + (1 - y) * math.log(1 - min(max(p, EPS), 1 - EPS)))
        for p, y in pairs)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    store = history.read_results()
    logs = pitcher_store.read_logs() or None

    fit_rows = _rows(store, logs, FIT_START, FIT_END)
    eval_rows = _rows(store, logs, EVAL_START, "2026-12-31")
    if len(fit_rows) < 200 or len(eval_rows) < 200:
        print(f"windows too small: fit={len(fit_rows)} eval={len(eval_rows)}",
              file=sys.stderr)
        return 1

    league = strength.league_runs_per_game(fit_rows)

    # THE FIT. One number, estimated on the fit window only.
    dispersion = _dispersion_of(fit_rows, store, league)
    half = len(fit_rows) // 2
    drift_a = _dispersion_of(fit_rows[:half], store, league)
    drift_b = _dispersion_of(fit_rows[half:], store, league)
    drift = abs(drift_a - drift_b) if (drift_a and drift_b) else None

    results = {
        "windows": {"fit": [FIT_START, FIT_END], "eval": [EVAL_START, None],
                    "fit_games": len(fit_rows), "eval_games": len(eval_rows)},
        "fitted_dispersion": round(dispersion, 4) if dispersion else None,
        "dispersion_first_half": round(drift_a, 4) if drift_a else None,
        "dispersion_second_half": round(drift_b, 4) if drift_b else None,
        "dispersion_drift": round(drift, 4) if drift is not None else None,
        "arms": {},
    }

    arms = [("poisson", 1.0, "nb1"),
            ("nb1", dispersion, "nb1"),
            ("nb2", dispersion, "nb2")]

    eval_half = len(eval_rows) // 2
    for name, disp, family in arms:
        rl, ml = _score_window(eval_rows, store, league, disp, family)
        rl_a, _ = _score_window(eval_rows[:eval_half], store, league, disp, family)
        rl_b, _ = _score_window(eval_rows[eval_half:], store, league, disp, family)
        results["arms"][name] = {
            "dispersion": round(disp, 4),
            "family": family,
            "runline_calibration_error": round(_calibration_error(rl), 5),
            "runline_calibration_error_first_half": round(_calibration_error(rl_a), 5),
            "runline_calibration_error_second_half": round(_calibration_error(rl_b), 5),
            "moneyline_log_loss": round(_log_loss(ml), 5),
            "mean_p_two_plus": round(statistics.fmean(p for p, _ in rl), 4),
            "observed_two_plus": round(statistics.fmean(y for _, y in rl), 4),
            "n": len(rl),
        }

    base = results["arms"]["poisson"]
    verdicts = {}
    for name in ("nb1", "nb2"):
        arm = results["arms"][name]
        improvement = (1.0 - arm["runline_calibration_error"]
                       / base["runline_calibration_error"])
        better_a = (arm["runline_calibration_error_first_half"]
                    < base["runline_calibration_error_first_half"])
        better_b = (arm["runline_calibration_error_second_half"]
                    < base["runline_calibration_error_second_half"])
        degradation = arm["moneyline_log_loss"] - base["moneyline_log_loss"]
        checks = {
            "calibration_improved_by_half": improvement >= CALIBRATION_IMPROVEMENT_REQUIRED,
            "moneyline_not_degraded": degradation <= MAX_LOGLOSS_DEGRADATION,
            "holds_in_both_halves": better_a and better_b,
            "dispersion_stable": (drift is not None
                                  and drift <= MAX_DISPERSION_DRIFT),
        }
        verdicts[name] = {
            "improvement": round(improvement, 4),
            "moneyline_degradation": round(degradation, 5),
            "checks": checks,
            "ADOPT": all(checks.values()),
        }
    results["verdicts"] = verdicts

    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    w = results["windows"]
    print(f"FIT     {w['fit'][0]} .. {w['fit'][1]}   {w['fit_games']} games")
    print(f"EVAL    {w['eval'][0]} onward             {w['eval_games']} games")
    print(f"\nFITTED DISPERSION  {results['fitted_dispersion']}   "
          f"(halves {results['dispersion_first_half']} / "
          f"{results['dispersion_second_half']}, drift "
          f"{results['dispersion_drift']})")
    print()
    print(f"{'arm':<10}{'cal err':>10}{'1st half':>10}{'2nd half':>10}"
          f"{'ML loss':>10}{'pred 2+':>10}{'obs 2+':>10}")
    for name in ("poisson", "nb1", "nb2"):
        a = results["arms"][name]
        print(f"{name:<10}{a['runline_calibration_error']:>10.5f}"
              f"{a['runline_calibration_error_first_half']:>10.5f}"
              f"{a['runline_calibration_error_second_half']:>10.5f}"
              f"{a['moneyline_log_loss']:>10.5f}"
              f"{a['mean_p_two_plus']:>10.4f}{a['observed_two_plus']:>10.4f}")
    print()
    for name, v in verdicts.items():
        print(f"{name}: improvement {v['improvement']:+.1%}   "
              f"ML degradation {v['moneyline_degradation']:+.5f} nats")
        for check, ok in v["checks"].items():
            print(f"    [{'PASS' if ok else 'FAIL'}] {check}")
        print(f"    ==> {'ADOPT' if v['ADOPT'] else 'DO NOT ADOPT'}")
    print()
    print("This script adopts nothing. If a verdict says ADOPT, changing")
    print("strength.DISPERSION is a separate deliberate edit, and the result")
    print("goes into docs/PREREG_RUN_DISPERSION.md either way.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
