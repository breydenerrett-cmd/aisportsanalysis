"""H3: is the overdispersion a property of baseball, or of 2026?

docs/PREREG_RUN_DISPERSION.md, third pre-registration. Written before this
script was run and before any dispersion figure was computed on 2025.

    HELD OUT    2025, 2,212 games, ingested after H1 had already run and
                never touched by any measurement in this repo
    APPLIED     DISPERSION = 2.3352, the value H1 estimated from its 2026
                fit window. Nothing is fitted on 2025.
    ADOPT if    2025's own dispersion is within +/-3 standard errors of
                2.3352, using 2025's own residual standard error
                AND run-line calibration error on 2025 falls >= 50% versus
                Poisson
    REPORTED    moneyline log-loss must not degrade by more than 0.001 nats

Three standard errors, not two, and the pre-registration says why: this is a
cross-season comparison and the run environment genuinely moves between
years, so a band tight enough to fail on a real league-wide scoring shift
would be measuring the wrong thing.

Read-only. Adopts nothing.

Usage:
    python scripts/test_run_dispersion_2025.py [--json]
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

from src.analysis import strength  # noqa: E402
from src.pipeline import features as features_mod  # noqa: E402
from src.pipeline import history, pitchers as pitcher_store  # noqa: E402

# TRANSCRIBED FROM THE PRE-REGISTRATION. Not arguments.
HELD_OUT_SEASON = "2025"
DISPERSION_FROM_2026 = 2.3352
FAMILY = "nb1"
STANDARD_ERRORS_ALLOWED = 3.0
CALIBRATION_IMPROVEMENT_REQUIRED = 0.50
MAX_LOGLOSS_DEGRADATION = 0.001
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


def _calibration_error(pairs, bins=10):
    if not pairs:
        return None
    buckets = defaultdict(list)
    for p, y in pairs:
        buckets[min(int(p * bins), bins - 1)].append((p, y))
    total = sum(len(v) for v in buckets.values())
    return sum(
        len(rows) / total * abs(statistics.fmean(p for p, _ in rows)
                                - statistics.fmean(y for _, y in rows))
        for rows in buckets.values())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    store = history.read_results()
    logs = pitcher_store.read_logs() or None
    table = features_mod.build_training_table(
        store, min_date=f"{HELD_OUT_SEASON}-04-15",
        max_date=f"{HELD_OUT_SEASON}-12-31",
        pitcher_logs=logs, require_complete=True)
    rows = table["rows"]
    if len(rows) < 500:
        print(f"only {len(rows)} usable {HELD_OUT_SEASON} games -- the "
              f"held-out season is not in the store", file=sys.stderr)
        return 1
    league = strength.league_runs_per_game(rows)

    residuals = []
    poisson_rl, nb_rl = [], []
    poisson_ml, nb_ml = [], []

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

        decided = 1 if abs(home - away) >= 2 else 0
        for arm_rl, arm_ml, disp in ((poisson_rl, poisson_ml, 1.0),
                                     (nb_rl, nb_ml, DISPERSION_FROM_2026)):
            probs = strength.market_probabilities(
                means["away_mean"], means["home_mean"], run_line=1.5,
                dispersion=disp, family=FAMILY)
            arm_rl.append((probs["p_home_minus"] + probs["p_away_minus"],
                           decided))
            arm_ml.append((probs["p_home"], int(row["home_won"])))

    if not residuals:
        print("no residuals", file=sys.stderr)
        return 1

    dispersion = statistics.fmean(residuals)
    se = statistics.pstdev(residuals) / math.sqrt(len(residuals))
    distance = abs(dispersion - DISPERSION_FROM_2026)
    z = distance / se if se else float("inf")

    poisson_err = _calibration_error(poisson_rl)
    nb_err = _calibration_error(nb_rl)
    improvement = 1.0 - (nb_err / poisson_err) if poisson_err else 0.0
    degradation = _log_loss(nb_ml) - _log_loss(poisson_ml)

    checks = {
        "dispersion_within_3_se_of_the_2026_estimate": z <= STANDARD_ERRORS_ALLOWED,
        "runline_calibration_improved_by_half":
            improvement >= CALIBRATION_IMPROVEMENT_REQUIRED,
    }
    report = {
        "held_out_season": HELD_OUT_SEASON,
        "games": len(nb_ml),
        "team_games": len(residuals),
        "dispersion_2025": round(dispersion, 4),
        "dispersion_2026_applied": DISPERSION_FROM_2026,
        "standard_error": round(se, 4),
        "distance_in_standard_errors": round(z, 3),
        "runline_calibration_error": {
            "poisson": round(poisson_err, 5),
            "nb1": round(nb_err, 5),
            "improvement": round(improvement, 4),
        },
        "moneyline_log_loss": {
            "poisson": round(_log_loss(poisson_ml), 6),
            "nb1": round(_log_loss(nb_ml), 6),
            "degradation": round(degradation, 6),
            "within_tolerance": degradation <= MAX_LOGLOSS_DEGRADATION,
        },
        "checks": checks,
        "ADOPT": all(checks.values()),
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"HELD-OUT SEASON  {HELD_OUT_SEASON}   {report['games']} games   "
          f"{report['team_games']} team-games")
    print()
    print(f"dispersion estimated on {HELD_OUT_SEASON}:  "
          f"{report['dispersion_2025']}  (se {report['standard_error']})")
    print(f"dispersion estimated on 2026 (applied):  "
          f"{DISPERSION_FROM_2026}")
    print(f"distance: {report['distance_in_standard_errors']} standard errors "
          f"(limit {STANDARD_ERRORS_ALLOWED})")
    print()
    c = report["runline_calibration_error"]
    print(f"run-line calibration error   poisson {c['poisson']:.5f}   "
          f"nb1 {c['nb1']:.5f}   improvement {c['improvement']:+.1%}")
    m = report["moneyline_log_loss"]
    print(f"moneyline log-loss           poisson {m['poisson']:.6f}   "
          f"nb1 {m['nb1']:.6f}   change {m['degradation']:+.6f}")
    print()
    for check, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {check}")
    print(f"  [{'PASS' if m['within_tolerance'] else 'FAIL'}] "
          f"moneyline_not_degraded (reported, not gating)")
    print(f"  ==> {'ADOPT' if report['ADOPT'] else 'DO NOT ADOPT'}")
    print()
    print("This script adopts nothing. Changing strength.DISPERSION is a")
    print("separate deliberate edit, and the result goes into")
    print("docs/PREREG_RUN_DISPERSION.md either way.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
