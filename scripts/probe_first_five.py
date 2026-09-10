"""Is the model relatively better over five innings than over nine?

THE ARGUMENT BEING TESTED, stated before the test so it can be wrong.

This model's strongest input is starting-pitcher quality, from real
per-start logs. Its weakest is everything after the starter leaves. The
first five innings are mostly the starter, so if the model has any real
skill it should show up MORE clearly there -- and first-five markets are
quoted by fewer books and priced with less attention than the full game,
which is where a small operator can afford to look.

That is a claim about where to spend effort, not a claim of edge, and this
probe is descriptive. It never looks at a price. What it compares is how
well the model predicts FIVE innings against how well it predicts NINE, on
the same games, with the same features.

THE F5 PREDICTION. Not a new model -- the same run means, restricted:

    first-five runs allowed = starter's share of five innings at his rate
                            + the remainder at the relief rate

A starter averaging 6.0 innings covers all five; one averaging 4.4 covers
4.4 and his bullpen covers 0.6. Offence is scaled by five ninths, which
assumes runs are spread evenly across innings -- they are not exactly (the
first inning scores more than the fourth), and that is a stated
simplification rather than a hidden one.

WHAT WOULD MAKE THIS INTERESTING. The model's gain over a base rate is
0.0009 nats on the full-game moneyline. If the same model gains materially
MORE on the five-inning outcome, that is a signal about where its skill
lives and it argues for building the F5 surface next. If it gains the same
or less, the argument above is wrong and the F5 direction should be dropped
rather than pursued on a hunch.

Read-only. No prices, no adoption, no pre-registration needed because
nothing here changes any published number.

Usage:
    python scripts/probe_first_five.py [--season 2026]
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
from src.engine.settle_slate import load_boxscore_first_five  # noqa: E402
from src.pipeline import bullpen, features as features_mod  # noqa: E402
from src.pipeline import history, pitchers as pitcher_store  # noqa: E402

FIRST_FIVE_INNINGS = 5.0
EPS = 1e-9

# Below this, no verdict. A log-loss difference of a few thousandths of a nat
# needs hundreds of games behind it before it means anything, and the first
# draft of this file happily declared a winner off 97.
MIN_GAMES_FOR_A_VERDICT = 400

# The model's full-game gain over a base rate on the WHOLE season
# (scripts/backtest_card.py). The subsample that happens to carry first-five
# results has to reproduce this before the comparison between five and nine
# innings can be read as being about the innings rather than about which
# games got a linescore row stored.
FULL_SEASON_GAIN = 0.00089
REPRESENTATIVE_TOLERANCE = 0.005


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


def _first_five_means(means, features):
    """The same run means, restricted to innings one through five."""
    out = {}
    for side, opp in (("away", "home"), ("home", "away")):
        ip = features.get(f"{opp}_sp_ip_per_start")
        starter_innings = (min(float(ip), FIRST_FIVE_INNINGS)
                           if isinstance(ip, (int, float)) else 0.0)
        relief_innings = FIRST_FIVE_INNINGS - starter_innings
        starter_rate = means.get(f"{opp}_starter_rate")
        pen_rate = means.get(f"{opp}_bullpen_rate")
        if starter_rate is None:
            defence_per_nine = means[f"{opp}_defence"]
        else:
            defence_per_nine = (
                (starter_rate * starter_innings + (pen_rate or means[f"{opp}_defence"])
                 * relief_innings) / FIRST_FIVE_INNINGS)
        offence_scale = means[f"{side}_offence"] / means["league_runs_per_game"]
        out[f"{side}_mean"] = max(
            defence_per_nine * (FIRST_FIVE_INNINGS / 9.0) * offence_scale, 0.05)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2026")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    store = history.read_results()
    logs = pitcher_store.read_logs() or None
    f5 = load_boxscore_first_five()
    if not f5:
        print("no first-five results stored", file=sys.stderr)
        return 1

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
                t: r.get("rate")
                for t, r in bullpen.relief_rates_by_team(pen_log, date).items()
                if r.get("rate")}
        return rate_cache[date]

    table = features_mod.build_training_table(
        store, min_date=f"{args.season}-04-15", max_date=f"{args.season}-12-31",
        pitcher_logs=logs, require_complete=True)
    rows = table["rows"]
    league = strength.league_runs_per_game(rows)

    full_pairs, f5_pairs = [], []
    full_base, f5_base = [], []
    f5_ties = 0
    missing = 0

    for row in rows:
        key = str(row["game_pk"])
        result = store.get(key) or {}
        away, home = _int(result.get("away_score")), _int(result.get("home_score"))
        five = f5.get(key)
        if away is None or home is None or five is None:
            missing += 1
            continue
        f5_home, f5_away = five

        relief = _relief(row["date"])
        feats = {**row,
                 "away_bullpen_rate": relief.get(row["away_team"]),
                 "home_bullpen_rate": relief.get(row["home_team"])}
        try:
            means = strength.run_means(feats, league_rpg=league)
        except strength.StrengthError:
            missing += 1
            continue

        full = strength.market_probabilities(means["away_mean"], means["home_mean"])
        full_pairs.append((full["p_home"], int(row["home_won"])))

        # THE FIVE-INNING OUTCOME IS THREE-WAY. A tie through five is a real
        # and common result -- the F5 moneyline is quoted three-way or with
        # a push for exactly that reason -- so ties are EXCLUDED from the
        # win/loss comparison and counted, rather than folded into one side
        # where they would flatter or punish the model at random.
        if f5_home == f5_away:
            f5_ties += 1
            continue
        fm = _first_five_means(means, feats)
        probs = strength.market_probabilities(fm["away_mean"], fm["home_mean"])
        # Renormalised over the two decisive outcomes, since ties are out.
        p_home_no_tie = probs["p_home"]
        f5_pairs.append((p_home_no_tie, 1 if f5_home > f5_away else 0))

    full_rate = statistics.fmean(y for _, y in full_pairs) if full_pairs else 0.5
    f5_rate = statistics.fmean(y for _, y in f5_pairs) if f5_pairs else 0.5
    full_base = [(full_rate, y) for _, y in full_pairs]
    f5_base = [(f5_rate, y) for _, y in f5_pairs]

    report = {
        "season": args.season,
        "games_full": len(full_pairs),
        "games_f5_decisive": len(f5_pairs),
        "f5_ties_excluded": f5_ties,
        "missing": missing,
        "full_game": {
            "home_win_rate": round(full_rate, 4),
            "model_log_loss": round(_log_loss(full_pairs), 5),
            "base_log_loss": round(_log_loss(full_base), 5),
        },
        "first_five": {
            "home_win_rate": round(f5_rate, 4),
            "model_log_loss": round(_log_loss(f5_pairs), 5),
            "base_log_loss": round(_log_loss(f5_base), 5),
        },
    }
    report["full_game"]["gain_nats"] = round(
        report["full_game"]["base_log_loss"]
        - report["full_game"]["model_log_loss"], 5)
    report["first_five"]["gain_nats"] = round(
        report["first_five"]["base_log_loss"]
        - report["first_five"]["model_log_loss"], 5)

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"SEASON {args.season}")
    print(f"  full game        {report['games_full']} games")
    print(f"  first five       {report['games_f5_decisive']} decisive "
          f"({report['f5_ties_excluded']} ties excluded, "
          f"{report['f5_ties_excluded'] / max(report['games_full'], 1):.1%} of games)")
    print(f"  unusable         {report['missing']}")
    print()
    print(f"{'outcome':<14}{'home wins':>12}{'model':>11}{'base':>11}{'gain':>11}")
    for label, key in (("full game", "full_game"), ("first five", "first_five")):
        s = report[key]
        print(f"{label:<14}{s['home_win_rate']:>12.1%}{s['model_log_loss']:>11.5f}"
              f"{s['base_log_loss']:>11.5f}{s['gain_nats']:>+11.5f}")
    print()
    fg = report["full_game"]["gain_nats"]
    f5g = report["first_five"]["gain_nats"]

    # TWO REFUSALS BEFORE ANY VERDICT, and the first draft of this file had
    # neither. It printed "THE ARGUMENT SURVIVES" off 97 games whose
    # full-game arm disagreed with the whole-season measurement by a factor
    # of ten -- which is the same over-claim this probe exists to avoid
    # making, produced by the probe itself.
    if len(f5_pairs) < MIN_GAMES_FOR_A_VERDICT:
        print(f"  NO VERDICT. {len(f5_pairs)} decisive first-five games is "
              f"below the {MIN_GAMES_FOR_A_VERDICT} this probe needs before")
        print("  it will say anything. The first-five results store covers a")
        print(f"  small fraction of the season ({report['missing']} games have")
        print("  no linescore row), and that is the finding: the DATA is the")
        print("  blocker, not the hypothesis. Backfill boxscores first.")
    elif abs(fg - FULL_SEASON_GAIN) > REPRESENTATIVE_TOLERANCE:
        print(f"  NO VERDICT. On this subsample the model's FULL-GAME gain is")
        print(f"  {fg:+.5f} nats against {FULL_SEASON_GAIN:+.5f} measured over")
        print("  the whole season. The games that happen to carry a")
        print("  first-five result are not a representative slice, so the")
        print("  comparison between the two outcomes is not interpretable.")
    elif f5g > fg * 1.5 and f5g > 0:
        print("  THE ARGUMENT SURVIVES. The model gains materially more over")
        print("  five innings than over nine, which is where its starter")
        print("  data lives and where the market pays least attention.")
        print("  Building the F5 surface is worth a pre-registration.")
    elif f5g <= fg:
        print("  THE ARGUMENT FAILS. The model is no better over five")
        print("  innings than over nine, so the reason to prefer F5 was")
        print("  wrong. Drop the direction rather than pursue it on a hunch.")
    else:
        print("  INCONCLUSIVE. F5 is better but not by enough to justify")
        print("  building a second surface on it.")
    print()
    print("  No price was read by this probe. It compares the model against")
    print("  a base rate on two outcomes, and says nothing about either")
    print("  market's efficiency.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
