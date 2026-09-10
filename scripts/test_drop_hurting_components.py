"""Two model components measured NEGATIVE. Does removing them actually help?

    CRITERION FIXED HERE, ABOVE THE MEASUREMENT, BEFORE IT WAS RUN.

    HELD OUT   2025. The ablation that motivated this was measured on 2026,
               so 2026 is spent for this question. Nothing is fitted here --
               removing an input fits nothing -- so a single held-out season
               is the whole test.
    ARMS       full, drop team rates, drop bullpen, drop both
    ADOPT an arm if moneyline log-loss improves by >= 0.0005 nats
                AND it improves in BOTH halves of the season
                AND run-line calibration does not get worse by more than
                    0.005 (a fifth of the gap the dispersion fix closed)
    OTHERWISE  change nothing. A component that neither helps nor hurts
               stays, because removing it is a change and changes need a
               reason.

WHY THIS IS BEING ASKED
-----------------------
`scripts/probe_model_ablation.py` over 1,896 games of 2026 found, against my
written expectations:

    run dispersion       +0.00424 nats
    starting pitcher     +0.00269
    home field           +0.00105
    team scoring rates   -0.00051    the model is BETTER without them
    bullpen              -0.00059    the model is BETTER without them

I expected team rates to be the largest contributor. They are a net
negative. Season runs scored and allowed carry whichever opponents and parks
a club happened to draw, and the starter plus the distribution shape appear
to be doing the real work.

THAT IS A DESCRIPTIVE FINDING ON ONE SEASON, and descriptive findings on the
season that produced them are how a model gets fitted to its own history.
Hence a held-out season and a criterion written first.

WHAT A "DROP TEAM RATES" MODEL ACTUALLY IS
-------------------------------------------
Both clubs' scored/allowed set to the league rate, which leaves the model
running on: tonight's two starters, the home-field credit, and the
overdispersed run distribution. That is a much simpler object than the
current one and it is worth saying out loud -- if it wins, the model has
been carrying two inputs that cost it.

The bullpen arm is subtler and its result is already half-known: measured
+0.00216 nats on a pre-specified July-onward window and -0.00034 over the
full season, the difference being thin April samples
(docs/THE_CARD.md). This tests it on a season where the sample is never thin
at the start, because 2025 is complete before 2026 begins.

Read-only. Adopts nothing.

Usage:
    python scripts/test_drop_hurting_components.py [--json]
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

HELD_OUT_SEASON = "2025"
MIN_LOGLOSS_GAIN = 0.0005
MAX_RUNLINE_DEGRADATION = 0.005
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


def _variant(features, arm, league):
    """One arm's feature set. `full` is untouched."""
    out = dict(features)
    if arm in ("drop_team", "drop_both"):
        for side in ("away", "home"):
            out[f"{side}_runs_scored_pg"] = league
            out[f"{side}_runs_allowed_pg"] = league
    if arm in ("drop_bullpen", "drop_both"):
        out["away_bullpen_rate"] = None
        out["home_bullpen_rate"] = None
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

    table = features_mod.build_training_table(
        store, min_date=f"{HELD_OUT_SEASON}-04-15",
        max_date=f"{HELD_OUT_SEASON}-12-31",
        pitcher_logs=logs, require_complete=True)
    rows = table["rows"]
    if len(rows) < 500:
        print(f"only {len(rows)} usable {HELD_OUT_SEASON} games",
              file=sys.stderr)
        return 1
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

    ARMS = ("full", "drop_team", "drop_bullpen", "drop_both")
    ml = {a: [] for a in ARMS}
    rl = {a: [] for a in ARMS}
    halves = {a: ([], []) for a in ARMS}
    bullpen_seen = 0
    midpoint = len(rows) // 2

    for i, row in enumerate(rows):
        actual = store.get(str(row["game_pk"])) or {}
        away, home = _int(actual.get("away_score")), _int(actual.get("home_score"))
        if away is None or home is None:
            continue
        pens = pens_for(row["date"])
        away_pen, home_pen = pens.get(row["away_team"]), pens.get(row["home_team"])
        if away_pen and home_pen:
            bullpen_seen += 1
        base = {**row, "away_bullpen_rate": away_pen,
                "home_bullpen_rate": home_pen}
        decided = 1 if abs(home - away) >= 2 else 0

        for arm in ARMS:
            try:
                line = strength.model_line(_variant(base, arm, league),
                                           league_rpg=league)
            except strength.StrengthError:
                continue
            pair = (line["p_home"], int(row["home_won"]))
            ml[arm].append(pair)
            rl[arm].append((line["p_home_minus"] + line["p_away_minus"], decided))
            halves[arm][0 if i < midpoint else 1].append(pair)

    report = {
        "held_out_season": HELD_OUT_SEASON,
        "games": len(ml["full"]),
        "games_with_bullpen_rates": bullpen_seen,
        "arms": {},
    }
    for arm in ARMS:
        report["arms"][arm] = {
            "moneyline_log_loss": round(_log_loss(ml[arm]), 6),
            "runline_calibration_error": round(_calibration_error(rl[arm]), 5),
            "first_half": round(_log_loss(halves[arm][0]), 6),
            "second_half": round(_log_loss(halves[arm][1]), 6),
        }

    # AN ARM WITH NOTHING TO REMOVE WAS NOT TESTED, AND MUST NOT PRINT A
    # VERDICT. The bullpen log holds no 2025 appearances, so `drop_bullpen`
    # removes an input that was never there and comes out byte-identical to
    # `full` -- a 0.000000 "gain" that a reader would take as a measured
    # null. Absent is not zero, and this is the same distinction enforced
    # everywhere else in this repo.
    untestable = set()
    if not bullpen_seen:
        untestable.update({"drop_bullpen", "drop_both"})

    base = report["arms"]["full"]
    verdicts = {}
    for arm in ("drop_team", "drop_bullpen", "drop_both"):
        if arm in untestable:
            verdicts[arm] = {
                "NOT_TESTED": True,
                "reason": (f"no bullpen appearances stored for "
                           f"{HELD_OUT_SEASON}, so this arm removes an input "
                           f"that was never present and is identical to the "
                           f"full model by construction"),
            }
            continue
        a = report["arms"][arm]
        gain = base["moneyline_log_loss"] - a["moneyline_log_loss"]
        checks = {
            "moneyline_gain_at_least_threshold": gain >= MIN_LOGLOSS_GAIN,
            "improves_in_both_halves": (a["first_half"] < base["first_half"]
                                        and a["second_half"] < base["second_half"]),
            "runline_not_materially_worse": (
                a["runline_calibration_error"]
                <= base["runline_calibration_error"] + MAX_RUNLINE_DEGRADATION),
        }
        verdicts[arm] = {"gain_nats": round(gain, 6), "checks": checks,
                         "ADOPT": all(checks.values())}
    report["verdicts"] = verdicts
    report["untestable_arms"] = sorted(untestable)

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"HELD-OUT SEASON  {HELD_OUT_SEASON}   {report['games']} games   "
          f"({report['games_with_bullpen_rates']} with both bullpens)")
    print()
    print(f"{'arm':<15}{'ML loss':>12}{'1st half':>12}{'2nd half':>12}"
          f"{'RL cal err':>13}")
    for arm in ARMS:
        a = report["arms"][arm]
        print(f"{arm:<15}{a['moneyline_log_loss']:>12.6f}"
              f"{a['first_half']:>12.6f}{a['second_half']:>12.6f}"
              f"{a['runline_calibration_error']:>13.5f}")
    print()
    for arm, v in verdicts.items():
        if v.get("NOT_TESTED"):
            print(f"{arm}: NOT TESTED -- {v['reason']}")
            print("    No verdict. An arm with nothing to remove produces a")
            print("    0.000000 'gain' that reads exactly like a measured")
            print("    null, and it is not one.")
            continue
        print(f"{arm}: {v['gain_nats']:+.6f} nats")
        for check, ok in v["checks"].items():
            print(f"    [{'PASS' if ok else 'FAIL'}] {check}")
        print(f"    ==> {'ADOPT' if v['ADOPT'] else 'DO NOT ADOPT'}")
    print()
    print("  'drop_team' leaves the model running on tonight's two starters,")
    print("  the home-field credit and the run distribution -- a much simpler")
    print("  object. If it wins, the model has been carrying two inputs that")
    print("  cost it.")
    print()
    print("  This script adopts nothing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
