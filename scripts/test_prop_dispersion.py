"""Plate appearances are not independent. How much, and does correcting help?

    CRITERION FIXED HERE, ABOVE THE MEASUREMENT, BEFORE IT WAS RUN.

    FIT       batter games from 2026-06-17 to 2026-08-05
    TEST      2026-08-06 onward
    ADOPT if  mean calibration gap on `batter_hits` over 0.5 falls by >= 50%
              on the test window
              AND log-loss does not get worse
              AND the fitted correlation is stable: the two halves of the FIT
                  window must agree within 0.02
    OTHERWISE change nothing.

WHY
---
`scripts/backtest_player_props.py` measured `batter_hits` over 0.5 at
+0.0107 nats -- real signal, about 2.7x what the team moneyline model
manages -- and **overconfident by roughly four points in every bucket**:

    predicted 0.461  ->  actual 0.408
    predicted 0.556  ->  actual 0.518
    predicted 0.647  ->  actual 0.614
    predicted 0.714  ->  actual 0.663

Four points is the difference between a bet worth taking at +110 and one
that quietly loses. The sign is the same everywhere, which means it is a
property of the model rather than noise.

THE MECHANISM, AND IT IS FAMILIAR
----------------------------------
The model treats a batter's plate appearances as independent coin flips at
his season rate. They are not. He faces one starter three times in the same
park on the same night, and his true rate that night is not his season rate.
Positive correlation between plate appearances makes outcomes CLUSTER: more
0-for-4s and more 3-for-4s than independence allows.

"At least one hit" is exactly the quantity clustering reduces -- the extra
0-fers come straight out of it. So an independent-trials model overstates
it, in every bucket, by about the amount observed.

This is the same failure the team run model had, where independent Poissons
understated run-margin spread by a factor of 2.3
(docs/PREREG_RUN_DISPERSION.md). Different distribution, same assumption,
same direction.

THE CORRECTION
--------------
Beta-binomial instead of binomial: same mean, one extra parameter `rho`
carrying the within-game correlation. `rho = 0` reproduces today's model
exactly, and a test asserts that so the correction can always be switched
off and compared.

`rho` is estimated from the fit window only, as the excess variance of
hits-per-game over what a binomial at the model's own mean and plate
appearances predicts:

    Var_observed / [n * p * (1 - p)]  =  1 + (n - 1) * rho

Read-only. Adopts nothing; changing `playerprops.RHO` is a separate edit.

Usage:
    python scripts/test_prop_dispersion.py [--json]
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

# TRANSCRIBED FROM THE CRITERION ABOVE. Not arguments.
FIT_START = "2026-06-17"
FIT_END = "2026-08-05"
TEST_START = "2026-08-06"
MARKET = "batter_hits"
LINE = 0.5
CALIBRATION_IMPROVEMENT_REQUIRED = 0.50
MAX_RHO_DRIFT = 0.02
EPS = 1e-9


def _log_loss(pairs):
    if not pairs:
        return None
    return statistics.fmean(
        -(y * math.log(min(max(p, EPS), 1 - EPS))
          + (1 - y) * math.log(1 - min(max(p, EPS), 1 - EPS)))
        for p, y in pairs)


def _calibration_gap(pairs, bins=10):
    """Sample-weighted mean ABSOLUTE gap between predicted and observed.

    Absolute, not signed: a model four points high in one bucket and four
    low in another is not calibrated, and a signed average would call it so.
    """
    buckets = defaultdict(list)
    for p, y in pairs:
        buckets[min(int(p * bins), bins - 1)].append((p, y))
    total = sum(len(v) for v in buckets.values())
    if not total:
        return None
    return sum(
        len(rows) / total * abs(statistics.fmean(p for p, _ in rows)
                                - statistics.fmean(y for _, y in rows))
        for rows in buckets.values())


def _predictions(rows_by_date, by_player, dates, lo, hi, rho):
    """(probability, outcome, expected_pa, per_pa_rate, observed_hits) rows."""
    out = []
    history = []
    for date in dates:
        league = None
        if history:
            try:
                league = playerprops.league_rates(history)
            except playerprops.PropError:
                league = None
        if league and lo <= date <= hi:
            for row in rows_by_date[date]:
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
                p = playerprops.probability_over(MARKET, LINE, rates, pa,
                                                 rho=rho)
                out.append((p, 1 if int(row.get("h") or 0) > LINE else 0,
                            pa, rates["hit"], int(row.get("h") or 0)))
        history.extend(rows_by_date[date])
    return out


def _estimate_rho(predictions):
    """Excess variance of hits-per-game over the binomial at the model's own
    mean and plate appearances."""
    ratios = []
    for _p, _y, pa, per_pa, hits in predictions:
        expected = pa * per_pa
        variance = pa * per_pa * (1 - per_pa)
        if variance <= 0 or pa <= 1:
            continue
        ratios.append(((hits - expected) ** 2 / variance, pa))
    if not ratios:
        return None, None
    dispersion = statistics.fmean(r for r, _ in ratios)
    mean_pa = statistics.fmean(pa for _, pa in ratios)
    if mean_pa <= 1:
        return None, dispersion
    return (dispersion - 1.0) / (mean_pa - 1.0), dispersion


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    rows = [r for r in boxscores.read(BOX_STORE) if r.get("type") == "batter"]
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
    if not dates:
        print("no batter rows", file=sys.stderr)
        return 1

    fit = _predictions(by_date, by_player, dates, FIT_START, FIT_END, 0.0)
    if len(fit) < 1000:
        print(f"only {len(fit)} fit-window predictions", file=sys.stderr)
        return 1

    rho, dispersion = _estimate_rho(fit)
    if rho is None:
        print("could not estimate the correlation", file=sys.stderr)
        return 1

    # Stability across the two halves of the FIT window.
    mid = len(fit) // 2
    rho_a, _ = _estimate_rho(fit[:mid])
    rho_b, _ = _estimate_rho(fit[mid:])
    drift = abs((rho_a or 0) - (rho_b or 0))

    plain = _predictions(by_date, by_player, dates, TEST_START, "9999", 0.0)
    corrected = _predictions(by_date, by_player, dates, TEST_START, "9999", rho)
    if len(plain) < 500:
        print(f"only {len(plain)} test-window predictions", file=sys.stderr)
        return 1

    plain_pairs = [(p, y) for p, y, *_ in plain]
    corr_pairs = [(p, y) for p, y, *_ in corrected]
    plain_gap = _calibration_gap(plain_pairs)
    corr_gap = _calibration_gap(corr_pairs)
    improvement = 1.0 - (corr_gap / plain_gap) if plain_gap else 0.0
    plain_loss = _log_loss(plain_pairs)
    corr_loss = _log_loss(corr_pairs)

    checks = {
        "calibration_gap_halved": improvement >= CALIBRATION_IMPROVEMENT_REQUIRED,
        "log_loss_not_worse": corr_loss <= plain_loss,
        "rho_stable_across_the_fit_window": drift <= MAX_RHO_DRIFT,
    }
    report = {
        "fit_window": [FIT_START, FIT_END], "fit_n": len(fit),
        "test_window": [TEST_START, dates[-1]], "test_n": len(plain),
        "observed_dispersion": round(dispersion, 4),
        "fitted_rho": round(rho, 5),
        "rho_halves": [round(rho_a, 5), round(rho_b, 5)],
        "rho_drift": round(drift, 5),
        "calibration_gap": {"binomial": round(plain_gap, 5),
                            "beta_binomial": round(corr_gap, 5),
                            "improvement": round(improvement, 4)},
        "log_loss": {"binomial": round(plain_loss, 5),
                     "beta_binomial": round(corr_loss, 5)},
        "mean_prediction": {
            "binomial": round(statistics.fmean(p for p, _ in plain_pairs), 4),
            "beta_binomial": round(statistics.fmean(p for p, _ in corr_pairs), 4),
            "actual": round(statistics.fmean(y for _, y in plain_pairs), 4),
        },
        "checks": checks,
        "ADOPT": all(checks.values()),
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"FIT   {FIT_START} .. {FIT_END}   {report['fit_n']} batter games")
    print(f"TEST  {TEST_START} .. {report['test_window'][1]}   "
          f"{report['test_n']} batter games")
    print()
    print(f"  hits-per-game variance is {report['observed_dispersion']}x the "
          f"binomial (independence would be 1.0)")
    print(f"  fitted within-game correlation rho = {report['fitted_rho']}   "
          f"halves {report['rho_halves']}   drift {report['rho_drift']}")
    print()
    m = report["mean_prediction"]
    print(f"  mean prediction   binomial {m['binomial']:.3f}   "
          f"beta-binomial {m['beta_binomial']:.3f}   actual {m['actual']:.3f}")
    c = report["calibration_gap"]
    print(f"  calibration gap   binomial {c['binomial']:.5f}   "
          f"beta-binomial {c['beta_binomial']:.5f}   "
          f"improvement {c['improvement']:+.1%}")
    ll = report["log_loss"]
    print(f"  log-loss          binomial {ll['binomial']:.5f}   "
          f"beta-binomial {ll['beta_binomial']:.5f}")
    print()
    for check, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {check}")
    print(f"  ==> {'ADOPT' if report['ADOPT'] else 'DO NOT ADOPT'}")
    print()
    print("  This script adopts nothing. Setting playerprops.RHO is a")
    print("  separate deliberate edit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
