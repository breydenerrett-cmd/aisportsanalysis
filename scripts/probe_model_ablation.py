"""Which part of the model actually carries its skill? One component at a time.

WHY THIS, AND WHY NOW
---------------------
`scripts/probe_first_five.py` refuted the argument that the model's value
lives in its starting-pitcher component: over nine innings it beats a base
rate by +0.00495 nats, and over five -- which is mostly the starter -- it is
worse than knowing nothing. If the starter features were carrying the model,
isolating the innings he throws would have sharpened it.

So the question stops being "which market do we point this at" and becomes
"which part of this is doing the work". That is an ablation.

WHAT I EXPECT, WRITTEN DOWN BEFORE RUNNING SO IT CANNOT BE RETROFITTED
-----------------------------------------------------------------------
  team scoring rates   the largest contributor, on the F5 evidence
  home field           real and sizeable; it is most of what a base rate
                       already knows, so neutralising it should hurt
  bullpen              small but real -- measured at +0.00216 nats on its
                       own window (scripts/test_bullpen_rate.py)
  starter              small or nothing, on the F5 evidence
  dispersion           near zero on the MONEYLINE. It is a correction to the
                       shape of the run distribution and its effect showed up
                       on the run line; a large moneyline effect here would
                       contradict how it was adopted

Being wrong about any of these is a result. Being wrong about the last one
would mean something is not understood about a constant already adopted.

HOW A COMPONENT IS NEUTRALISED
------------------------------
Each arm replaces one input with the league-neutral version of itself and
changes nothing else:

  team      both clubs' scored/allowed rates set to the league rate
  starter   both starters unknown, so the relief rate covers the whole game
  bullpen   the whole-season stand-in, i.e. what the model did before
            2026-09-10
  home      HOME_FIELD_RUNS set to zero
  disp      DISPERSION set to 1.0, i.e. back to independent Poissons

The loss each arm shows is that component's contribution, measured against
the full model on the same games.

Read-only. Descriptive. Adopts nothing and changes no constant.

Usage:
    python scripts/probe_model_ablation.py [--season 2026] [--json]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis import strength  # noqa: E402
from src.pipeline import bullpen, features as features_mod  # noqa: E402
from src.pipeline import history, pitchers as pitcher_store  # noqa: E402

EPS = 1e-9

# Below this the differences are smaller than the noise and the table would
# invite reading structure into rounding.
MIN_GAMES = 500


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


def _neutralise(features, arm, league):
    """One component replaced by its league-neutral self."""
    out = dict(features)
    if arm == "team":
        for side in ("away", "home"):
            out[f"{side}_runs_scored_pg"] = league
            out[f"{side}_runs_allowed_pg"] = league
    elif arm == "starter":
        for side in ("away", "home"):
            out[f"{side}_sp_fip"] = None
            out[f"{side}_sp_innings"] = None
            out[f"{side}_sp_ip_per_start"] = None
    elif arm == "bullpen":
        out["away_bullpen_rate"] = None
        out["home_bullpen_rate"] = None
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2026")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    store = history.read_results()
    logs = pitcher_store.read_logs() or None
    try:
        pen_log = bullpen.read_log()
    except Exception:  # noqa: BLE001
        pen_log = []

    table = features_mod.build_training_table(
        store, min_date=f"{args.season}-04-15", max_date=f"{args.season}-12-31",
        pitcher_logs=logs, require_complete=True)
    rows = table["rows"]
    if len(rows) < MIN_GAMES:
        print(f"only {len(rows)} games", file=sys.stderr)
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

    arms = {name: [] for name in
            ("full", "team", "starter", "bullpen", "home", "disp")}
    base_pairs = []

    # HOME_FIELD_RUNS is a module constant, so the `home` arm swaps it and
    # puts it back. Restored in a finally so a raise mid-loop cannot leave
    # the model altered for everything downstream in this process.
    real_home_field = strength.HOME_FIELD_RUNS
    try:
        for row in rows:
            actual = store.get(str(row["game_pk"])) or {}
            if _int(actual.get("home_score")) is None:
                continue
            pens = pens_for(row["date"])
            full = {**row,
                    "away_bullpen_rate": pens.get(row["away_team"]),
                    "home_bullpen_rate": pens.get(row["home_team"])}
            y = int(row["home_won"])
            base_pairs.append(y)

            for arm in arms:
                feats = full
                dispersion = None
                if arm in ("team", "starter", "bullpen"):
                    feats = _neutralise(full, arm, league)
                elif arm == "disp":
                    dispersion = 1.0
                if arm == "home":
                    strength.HOME_FIELD_RUNS = 0.0
                try:
                    means = strength.run_means(feats, league_rpg=league)
                    probs = strength.market_probabilities(
                        means["away_mean"], means["home_mean"],
                        dispersion=dispersion)
                    arms[arm].append((probs["p_home"], y))
                except strength.StrengthError:
                    pass
                finally:
                    if arm == "home":
                        strength.HOME_FIELD_RUNS = real_home_field
    finally:
        strength.HOME_FIELD_RUNS = real_home_field

    base_rate = statistics.fmean(base_pairs)
    base_loss = _log_loss([(base_rate, y) for y in base_pairs])
    full_loss = _log_loss(arms["full"])

    report = {
        "season": args.season,
        "games": len(arms["full"]),
        "home_win_rate": round(base_rate, 4),
        "base_rate_log_loss": round(base_loss, 6),
        "full_model_log_loss": round(full_loss, 6),
        "full_model_gain": round(base_loss - full_loss, 6),
        "components": {},
    }
    for arm in ("team", "starter", "bullpen", "home", "disp"):
        loss = _log_loss(arms[arm])
        report["components"][arm] = {
            "log_loss_without_it": round(loss, 6),
            "contribution_nats": round(loss - full_loss, 6),
            "share_of_model": (round((loss - full_loss)
                                     / (base_loss - full_loss), 3)
                               if base_loss != full_loss else None),
        }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"SEASON {args.season}   {report['games']} games   "
          f"home wins {report['home_win_rate']:.1%}")
    print(f"  base rate     log-loss {report['base_rate_log_loss']:.6f}")
    print(f"  full model    log-loss {report['full_model_log_loss']:.6f}   "
          f"gain {report['full_model_gain']:+.6f} nats")
    print()
    print(f"{'component removed':<20}{'log-loss':>12}{'costs':>12}{'share':>9}")
    for arm in sorted(report["components"],
                      key=lambda a: -report["components"][a]["contribution_nats"]):
        c = report["components"][arm]
        share = c["share_of_model"]
        print(f"{arm:<20}{c['log_loss_without_it']:>12.6f}"
              f"{c['contribution_nats']:>+12.6f}"
              f"{(f'{share:>8.0%}' if share is not None else '       —')}")
    print()
    print("  'costs' is how much log-loss RISES when that component is")
    print("  replaced by its league-neutral self -- so bigger is more")
    print("  important. A NEGATIVE cost means the model is better without")
    print("  that component, which is a finding and not a rounding error if")
    print("  it is larger than the smallest positive one here.")
    print()
    print("  Expected before running (see the module docstring): team rates")
    print("  largest, home field real, bullpen small but real, starter small")
    print("  or nothing, dispersion near zero on the moneyline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
