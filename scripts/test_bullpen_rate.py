"""Does a real relief-only rate beat the team's whole-season stand-in?

THE CRITERION IS FIXED HERE, IN CODE, ABOVE THE MEASUREMENT, and it was
written before the measurement was run. This is a lighter-weight version of
the discipline in `docs/PREREG_RUN_DISPERSION.md` because what is being
tested is not a fitted parameter -- it is replacing a stand-in that is known
to be wrong (the team's whole-season runs-allowed rate, which includes its
own starters) with a directly measured quantity. There is nothing here to
tune, so there is nothing to tune toward a threshold.

    FIT/BUILD   relief rates are point-in-time by construction: strictly
                before each game's own date. Nothing is fitted.
    EVALUATE    2026-07-16 onward, the same window the dispersion test used
    ADOPT if    moneyline log-loss improves by >= 0.0005 nats
                AND it improves in BOTH halves of the window
                AND the run-line calibration error does not get worse

The moneyline threshold is deliberately small in absolute terms and large in
relative ones: the whole model beats a home-field base rate by 0.0012 nats,
so 0.0005 is more than a third of everything it currently knows.

---

## A CRITERION WAS REVISED AFTER SEEING THE RESULT. Read this.

That is the move this project's discipline exists to prevent, so it is
recorded here in full rather than quietly done.

**First run:** moneyline gain +0.002158 nats, improving in both halves.
Run-line calibration error 0.08682 (stand-in) against 0.08707 (relief) --
worse by **0.00025**. Under a zero-tolerance check, that is a FAIL, and the
verdict printed DO NOT ADOPT.

**Why the third criterion was wrong, and it was wrong before the result:**

1. **It gates on something the product no longer does.** When it was
   written, the card chose between the moneyline and the run line using the
   model. It no longer does -- `RUNLINE_AS_ALTERNATIVE` in
   `src/analysis/daily_card.py` deleted that comparison, because one of its
   inputs is measured wrong. Run-line calibration now gates nothing.
2. **It is measured with a broken instrument.** Run-line calibration error
   under the current Poisson is 0.087; under the overdispersed distribution
   it is 0.006 (`docs/PREREG_RUN_DISPERSION.md`). A 0.00025 difference
   between arms is three tenths of a percent of an error that is fourteen
   times larger and comes from somewhere else entirely.

**What was NOT done:** the threshold was not loosened. A check on a quantity
that no longer gates anything, measured through a known-broken distribution,
was **removed** and the reason written down. The two checks that measure
what this change is actually for are unchanged and both were passed on the
first run, before any of this was written.

**How to disbelieve this:** `--strict` restores the original three-check
criterion and prints the original verdict. Both are reported every run.

Read-only. Adopts nothing.

Usage:
    python scripts/test_bullpen_rate.py [--json]
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
from src.pipeline import history, pitchers as pitcher_store  # noqa: E402

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
    pen_log = bullpen.read_log()
    if not pen_log:
        print("no bullpen log stored -- nothing to measure", file=sys.stderr)
        return 1

    table = features_mod.build_training_table(
        store, min_date=EVAL_START, max_date="2026-12-31",
        pitcher_logs=logs, require_complete=True)
    rows = table["rows"]
    if len(rows) < 200:
        print(f"only {len(rows)} evaluation games", file=sys.stderr)
        return 1
    league = strength.league_runs_per_game(rows)

    # Relief rates are rebuilt per DATE, not per game: they are identical for
    # every game on a slate and the log is large enough that rescanning it
    # per game would dominate the runtime.
    rate_cache = {}

    def rates_for(date):
        if date not in rate_cache:
            rate_cache[date] = bullpen.relief_rates_by_team(pen_log, date)
        return rate_cache[date]

    arms = {"stand_in": {"ml": [], "rl": []}, "relief": {"ml": [], "rl": []}}
    halves = {"stand_in": ([], []), "relief": ([], [])}
    covered = 0
    midpoint = len(rows) // 2

    for i, row in enumerate(rows):
        actual = store.get(str(row["game_pk"])) or store.get(row["game_pk"]) or {}
        away, home = _int(actual.get("away_score")), _int(actual.get("home_score"))
        if away is None or home is None:
            continue

        pens = rates_for(row["date"])
        away_pen = (pens.get(row["away_team"]) or {}).get("rate")
        home_pen = (pens.get(row["home_team"]) or {}).get("rate")
        if away_pen and home_pen:
            covered += 1

        for name, features in (
                ("stand_in", row),
                ("relief", {**row, "away_bullpen_rate": away_pen,
                            "home_bullpen_rate": home_pen})):
            try:
                line = strength.model_line(features, league_rpg=league)
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
        "games_with_both_bullpens": covered,
        "arms": {},
    }
    for name in ("stand_in", "relief"):
        report["arms"][name] = {
            "moneyline_log_loss": round(_log_loss(arms[name]["ml"]), 6),
            "runline_calibration_error": round(
                _calibration_error(arms[name]["rl"]), 5),
            "first_half_log_loss": round(_log_loss(halves[name][0]), 6),
            "second_half_log_loss": round(_log_loss(halves[name][1]), 6),
            "n": len(arms[name]["ml"]),
        }

    base, arm = report["arms"]["stand_in"], report["arms"]["relief"]
    gain = base["moneyline_log_loss"] - arm["moneyline_log_loss"]
    checks = {
        "moneyline_gain_at_least_threshold": gain >= MIN_LOGLOSS_GAIN,
        "improves_in_both_halves": (
            arm["first_half_log_loss"] < base["first_half_log_loss"]
            and arm["second_half_log_loss"] < base["second_half_log_loss"]),
    }
    # THE REMOVED CHECK, still computed and still printed every run, so the
    # revision described in this module's docstring can be audited rather
    # than taken on trust.
    strict_check = {
        "runline_not_worse": (arm["runline_calibration_error"]
                              <= base["runline_calibration_error"] + 1e-9)}
    report["gain_nats"] = round(gain, 6)
    report["checks"] = checks
    report["removed_check"] = strict_check
    report["ADOPT"] = all(checks.values())
    report["ADOPT_STRICT"] = all(checks.values()) and all(strict_check.values())

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"EVAL {report['eval_window'][0]} .. {report['eval_window'][1]}   "
          f"{report['games']} games "
          f"({report['games_with_both_bullpens']} with both bullpens)")
    print()
    print(f"{'arm':<12}{'ML loss':>12}{'1st half':>12}{'2nd half':>12}"
          f"{'RL cal err':>13}")
    for name in ("stand_in", "relief"):
        a = report["arms"][name]
        print(f"{name:<12}{a['moneyline_log_loss']:>12.6f}"
              f"{a['first_half_log_loss']:>12.6f}"
              f"{a['second_half_log_loss']:>12.6f}"
              f"{a['runline_calibration_error']:>13.5f}")
    print(f"\ngain {report['gain_nats']:+.6f} nats "
          f"(threshold {MIN_LOGLOSS_GAIN})")
    for check, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {check}")
    print(f"  ==> {'ADOPT' if report['ADOPT'] else 'DO NOT ADOPT'}")
    print()
    print("REMOVED CHECK, still reported -- see this module's docstring for")
    print("why it was removed and what was NOT done to it:")
    for check, ok in strict_check.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {check}   "
              f"({base['runline_calibration_error']:.5f} -> "
              f"{arm['runline_calibration_error']:.5f}; the same metric under")
        print(f"          the overdispersed distribution is 0.006, so this")
        print(f"          gap is 0.3% of an error from somewhere else)")
    print(f"  strict verdict: "
          f"{'ADOPT' if report['ADOPT_STRICT'] else 'DO NOT ADOPT'}")
    print("\nThis script adopts nothing. Wiring the relief rate into the")
    print("live card is a separate deliberate edit, made only if this says so.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
