"""Does a point-in-time park factor improve the model? Criterion fixed first.

    BUILD       park factors are point-in-time by construction: only games
                that finished strictly before each game's own date, from the
                home club's own home-versus-road split, regressed toward
                neutral over 150 imaginary games. Nothing is fitted.
    EVALUATE    2026-07-16 onward -- the same window the bullpen and
                dispersion tests used, so the three are comparable
    ADOPT if    moneyline log-loss improves by >= 0.0005 nats
                AND it improves in BOTH halves of the window

WHY THE THRESHOLD IS 0.0005 AGAIN. The whole model beats a home-field base
rate by about 0.0009 nats, so half a thousandth is more than half of
everything it currently knows. The same number was used for the bullpen so
the two results can be read against each other.

WHY THERE IS NO RUN-LINE CHECK. There was one on the bullpen test and it was
removed, in the open, for two reasons that apply identically here: the card
no longer selects a market with the model, and run-line calibration is
measured through a distribution whose own error on that quantity is
fourteen times larger than any difference this change could make. See
scripts/test_bullpen_rate.py's docstring. It is still COMPUTED and printed
below, so nothing is hidden -- it simply does not gate.

A PARK FACTOR CANNOT MOVE THE MONEYLINE MUCH, AND THAT IS EXPECTED. It
multiplies both clubs' run means equally, so it changes the shape of the
game -- how many runs, and therefore how often the favourite wins by two --
far more than it changes who wins. A near-zero moneyline result here is a
real answer, not a broken test, and would mean the factor belongs in the
totals and run-line surfaces rather than in the card's moneyline.

Read-only. Adopts nothing.

Usage:
    python scripts/test_park_factor.py [--json]
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
from src.pipeline import bullpen, features as features_mod  # noqa: E402
from src.pipeline import history, parkfactors  # noqa: E402
from src.pipeline import pitchers as pitcher_store  # noqa: E402

EVAL_START = "2026-07-16"
MIN_LOGLOSS_GAIN = 0.0005
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
    try:
        pen_log = bullpen.read_log()
    except Exception:  # noqa: BLE001
        pen_log = []

    table = features_mod.build_training_table(
        store, min_date=EVAL_START, max_date="2026-12-31",
        pitcher_logs=logs, require_complete=True)
    rows = table["rows"]
    if len(rows) < 200:
        print(f"only {len(rows)} evaluation games", file=sys.stderr)
        return 1
    league = strength.league_runs_per_game(rows)

    # Both caches are per DATE: the factors and rates are identical for every
    # game on a slate and rescanning per game would dominate the runtime.
    park_cache, pen_cache = {}, {}

    def parks_for(date):
        if date not in park_cache:
            park_cache[date] = parkfactors.park_factors(store, date)
        return park_cache[date]

    def pens_for(date):
        if not pen_log:
            return {}
        if date not in pen_cache:
            pen_cache[date] = {
                t: r.get("rate")
                for t, r in bullpen.relief_rates_by_team(pen_log, date).items()
                if r.get("rate")}
        return pen_cache[date]

    arms = {"no_park": {"ml": [], "rl": []}, "park": {"ml": [], "rl": []}}
    halves = {"no_park": ([], []), "park": ([], [])}
    factors_seen = []
    midpoint = len(rows) // 2

    for i, row in enumerate(rows):
        actual = store.get(str(row["game_pk"])) or store.get(row["game_pk"]) or {}
        away, home = _int(actual.get("away_score")), _int(actual.get("home_score"))
        if away is None or home is None:
            continue

        pens = pens_for(row["date"])
        base_features = {**row,
                         "away_bullpen_rate": pens.get(row["away_team"]),
                         "home_bullpen_rate": pens.get(row["home_team"])}
        factor = parkfactors.factor_for(parks_for(row["date"]), row["home_team"])
        factors_seen.append(factor)

        for name, feats in (("no_park", base_features),
                            ("park", {**base_features, "park_factor": factor})):
            try:
                line = strength.model_line(feats, league_rpg=league)
            except strength.StrengthError:
                continue
            ml = (line["p_home"], int(row["home_won"]))
            rl = (line["p_home_minus"] + line["p_away_minus"],
                  1 if abs(home - away) >= 2 else 0)
            arms[name]["ml"].append(ml)
            arms[name]["rl"].append(rl)
            halves[name][0 if i < midpoint else 1].append(ml)

    report = {
        "eval_window": [EVAL_START, table["last_date"]],
        "games": len(rows),
        "park_factor_spread": {
            "min": round(min(factors_seen), 4) if factors_seen else None,
            "max": round(max(factors_seen), 4) if factors_seen else None,
            "mean": round(statistics.fmean(factors_seen), 4) if factors_seen else None,
            "at_neutral": sum(1 for f in factors_seen if abs(f - 1.0) < 1e-9),
        },
        "arms": {},
    }
    for name in ("no_park", "park"):
        report["arms"][name] = {
            "moneyline_log_loss": round(_log_loss(arms[name]["ml"]), 6),
            "runline_calibration_error": round(
                _calibration_error(arms[name]["rl"]), 5),
            "first_half_log_loss": round(_log_loss(halves[name][0]), 6),
            "second_half_log_loss": round(_log_loss(halves[name][1]), 6),
            "n": len(arms[name]["ml"]),
        }

    base, arm = report["arms"]["no_park"], report["arms"]["park"]
    gain = base["moneyline_log_loss"] - arm["moneyline_log_loss"]
    checks = {
        "moneyline_gain_at_least_threshold": gain >= MIN_LOGLOSS_GAIN,
        "improves_in_both_halves": (
            arm["first_half_log_loss"] < base["first_half_log_loss"]
            and arm["second_half_log_loss"] < base["second_half_log_loss"]),
    }
    report["gain_nats"] = round(gain, 6)
    report["checks"] = checks
    report["ADOPT"] = all(checks.values())

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    s = report["park_factor_spread"]
    print(f"EVAL {report['eval_window'][0]} .. {report['eval_window'][1]}   "
          f"{report['games']} games")
    print(f"park factors: {s['min']} .. {s['max']}   mean {s['mean']}   "
          f"{s['at_neutral']} games at exactly neutral")
    print()
    print(f"{'arm':<10}{'ML loss':>12}{'1st half':>12}{'2nd half':>12}"
          f"{'RL cal err':>13}")
    for name in ("no_park", "park"):
        a = report["arms"][name]
        print(f"{name:<10}{a['moneyline_log_loss']:>12.6f}"
              f"{a['first_half_log_loss']:>12.6f}"
              f"{a['second_half_log_loss']:>12.6f}"
              f"{a['runline_calibration_error']:>13.5f}")
    print(f"\ngain {report['gain_nats']:+.6f} nats "
          f"(threshold {MIN_LOGLOSS_GAIN})")
    for check, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {check}")
    print(f"  ==> {'ADOPT' if report['ADOPT'] else 'DO NOT ADOPT'}")
    print()
    print("A park multiplies both clubs equally, so it changes how MANY runs")
    print("far more than WHO wins. A near-zero moneyline result is a real")
    print("answer and would mean the factor belongs in the totals and")
    print("run-line surfaces rather than in the card's moneyline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
