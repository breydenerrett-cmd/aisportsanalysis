"""Is Poisson the right shape for baseball runs? Measured two independent ways.

WHY THIS EXISTS
---------------
`scripts/probe_market_consistency.py` found something that looked like a
market inefficiency and, on control, was not. What it actually found was a
fault in OUR distribution, stated by the market with a very large sample and
no game results involved at all.

Solving each book's own moneyline and total for two Poisson run means, and
then asking what run line those means imply, the books disagree with us by:

    home LAYS the runs (-1.5)    +3.57 points   (p25 +2.98, p75 +4.02)
    home TAKES the runs (+1.5)   -8.42 points   (p25 -8.87, p75 -7.95)

Both say the same thing -- real run margins are more spread out than Poisson
allows -- and the clusters are far too tight to be anything but a
deterministic property of the model. 3,575 observations from a single day.

That is a claim about baseball, and baseball has an independent witness:
final scores. This probe asks both, separately.

  1. THE OUTCOMES. Per-team runs and run margins from the results store,
     against what independent Poissons with the same means would produce.
     If runs are overdispersed, the observed variance exceeds the mean.
  2. THE MARKET. Reported by the sibling probe above; repeated here only as
     a number to compare against.

If those two agree, the correction is real and can be applied with an
out-of-sample test. If they disagree, something in the market read is wrong
and it must not be applied at all.

READ-ONLY. Touches no ledger, fits nothing, changes no constant. What it
produces is a measurement and a recommendation for a pre-registration.

Usage:
    python scripts/probe_run_dispersion.py [--season 2026]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis import strength  # noqa: E402
from src.pipeline import history  # noqa: E402


def _poisson_pmf(mean, k):
    return math.exp(-mean + k * math.log(mean) - math.lgamma(k + 1))


def _int(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _conditional_dispersion(store, season):
    """Mean squared Pearson residual against the model's OWN per-game means.

    Under Poisson this is 1.0 by construction, whatever the means are, so it
    isolates true overdispersion from the ordinary game-to-game variation in
    expected runs that the model already represents.

    Point-in-time throughout: the means come from
    `features.build_training_table`, whose only history accessor filters
    strictly before each game's date.
    """
    from src.pipeline import features as features_mod
    from src.pipeline import pitchers as pitcher_store

    logs = pitcher_store.read_logs() or None
    table = features_mod.build_training_table(
        store, min_date=f"{season}-04-15", max_date=f"{season}-12-31",
        pitcher_logs=logs, require_complete=True)
    rows = table["rows"]
    league = strength.league_runs_per_game(rows)
    if not rows or not league:
        return {"n": 0}

    residuals, margin_residuals = [], []
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
        # The margin's own variance ratio, conditional on the predicted
        # margin. Independent Poissons predict variance = sum of the means.
        expected_margin = means["home_mean"] - means["away_mean"]
        margin_var = means["home_mean"] + means["away_mean"]
        if margin_var > 0:
            margin_residuals.append(
                ((home - away) - expected_margin) ** 2 / margin_var)

    if not residuals:
        return {"n": 0}
    return {
        "n": len(residuals),
        "team_runs_ratio": round(statistics.fmean(residuals), 4),
        "margin_ratio": (round(statistics.fmean(margin_residuals), 4)
                         if margin_residuals else None),
        "games": len(margin_residuals),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2026")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    store = history.read_results()
    scores = []
    for row in store.values():
        if str(row.get("date", ""))[:4] != args.season:
            continue
        # COERCED, NEVER isinstance-CHECKED. The store round-trips through
        # CSV and keeps scores as strings; an isinstance(int) guard here is
        # what made the first run of this probe report "only 0 finished
        # games" out of 2,153. The identical trap was live in
        # src/appstate/card_ledger.py's grade_pick at the same moment and
        # would have VOIDed every pick on every card.
        away, home = _int(row.get("away_score")), _int(row.get("home_score"))
        if away is not None and home is not None:
            scores.append((away, home))
    if len(scores) < 200:
        print(f"only {len(scores)} finished games; not enough to measure",
              file=sys.stderr)
        return 1

    team_runs = [r for pair in scores for r in pair]
    margins = [h - a for a, h in scores]
    totals = [a + h for a, h in scores]

    mean_runs = statistics.fmean(team_runs)
    var_runs = statistics.pvariance(team_runs)
    var_margin = statistics.pvariance(margins)
    var_total = statistics.pvariance(totals)

    # Under INDEPENDENT Poissons with this mean, every one of these is
    # determined: var(runs) = mean, var(margin) = var(total) = 2 * mean.
    poisson_var_runs = mean_runs
    poisson_var_margin = 2 * mean_runs

    # The observed cover rates, which is what the run line actually pays on.
    n = len(scores)
    fav_covers = sum(1 for m in margins if abs(m) >= 2) / n
    one_run = sum(1 for m in margins if abs(m) == 1) / n

    # What independent Poissons at the observed mean would say, using the
    # same joint the product uses -- so this compares against the code that
    # actually prices the card, not against a textbook formula.
    probs = strength.market_probabilities(mean_runs, mean_runs, run_line=1.5)
    poisson_fav_covers = probs["p_home_minus"] + probs["p_away_minus"]
    poisson_one_run = 1.0 - poisson_fav_covers

    # THE NUMBER THAT DECIDES THE SIZE OF ANY CORRECTION, and the one a
    # naive read of variance/mean gets wrong.
    #
    # The 2.33 above is the MARGINAL variance-to-mean ratio, pooled over
    # every game. Part of it is not overdispersion at all: expected runs
    # genuinely differ from game to game (a good offence against a bad
    # starter really does expect more), and the law of total variance folds
    # that spread into the pooled figure. A correction sized off the pooled
    # ratio would double-count variation the model already represents.
    #
    # The conditional figure asks the right question: given the mean THIS
    # MODEL predicted for THIS game, how far off was the actual score, in
    # units of the Poisson standard deviation? Mean squared Pearson residual
    # is 1.0 under Poisson by construction, whatever the means are.
    conditional = _conditional_dispersion(store, args.season)

    report = {
        "season": args.season,
        "games": n,
        "conditional_dispersion": conditional,
        "runs": {
            "mean": round(mean_runs, 4),
            "variance": round(var_runs, 4),
            "poisson_variance": round(poisson_var_runs, 4),
            "variance_over_mean": round(var_runs / mean_runs, 4),
        },
        "margin": {
            "variance": round(var_margin, 4),
            "poisson_variance": round(poisson_var_margin, 4),
            "ratio": round(var_margin / poisson_var_margin, 4),
            "sd": round(math.sqrt(var_margin), 4),
        },
        "total": {
            "variance": round(var_total, 4),
            "poisson_variance": round(poisson_var_margin, 4),
            "ratio": round(var_total / poisson_var_margin, 4),
        },
        "cover_rates": {
            "observed_decided_by_two_or_more": round(fav_covers, 4),
            "poisson_decided_by_two_or_more": round(poisson_fav_covers, 4),
            "gap_points": round((fav_covers - poisson_fav_covers) * 100, 2),
            "observed_one_run_games": round(one_run, 4),
            "poisson_one_run_games": round(poisson_one_run, 4),
        },
        "margin_histogram": dict(sorted(Counter(abs(m) for m in margins).items())),
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    r, m, t, c = (report["runs"], report["margin"], report["total"],
                  report["cover_rates"])
    print(f"SEASON {args.season}   {n} finished games\n")
    print("PER-TEAM RUNS (pooled -- includes real game-to-game variation)")
    print(f"  mean {r['mean']:.3f}   variance {r['variance']:.3f}   "
          f"Poisson would be {r['poisson_variance']:.3f}")
    print(f"  variance/mean = {r['variance_over_mean']:.3f}  "
          f"({'OVERDISPERSED' if r['variance_over_mean'] > 1.05 else 'about Poisson'})")
    print()
    cd = report["conditional_dispersion"]
    print("CONDITIONAL ON THE MODEL'S OWN PER-GAME MEANS -- size a correction")
    print("off THIS, not off the pooled figure above")
    if cd.get("n"):
        print(f"  team runs   ratio {cd['team_runs_ratio']:.3f}   "
              f"(n={cd['n']} team-games; Poisson is 1.000)")
        if cd.get("margin_ratio"):
            print(f"  run margin  ratio {cd['margin_ratio']:.3f}   "
                  f"(n={cd['games']} games)")
        print("  The pooled figure folds in genuine variation in expected")
        print("  runs, which the model already represents. Sizing off it")
        print("  would double-count that and overshoot.")
    else:
        print("  not measurable here")
    print()
    print("RUN MARGIN (home minus away)")
    print(f"  variance {m['variance']:.3f}   independent Poissons would be "
          f"{m['poisson_variance']:.3f}   ratio {m['ratio']:.3f}")
    print(f"  sd {m['sd']:.3f} runs")
    print()
    print("GAME TOTAL")
    print(f"  variance {t['variance']:.3f}   Poisson {t['poisson_variance']:.3f}"
          f"   ratio {t['ratio']:.3f}")
    print()
    print("WHAT THE RUN LINE ACTUALLY PAYS ON")
    print(f"  games decided by 2+ runs   observed "
          f"{c['observed_decided_by_two_or_more']:.1%}   "
          f"Poisson {c['poisson_decided_by_two_or_more']:.1%}   "
          f"gap {c['gap_points']:+.2f} pts")
    print(f"  one-run games              observed {c['observed_one_run_games']:.1%}"
          f"   Poisson {c['poisson_one_run_games']:.1%}")
    print()
    print("  COMPARE THAT GAP TO THE MARKET'S. probe_market_consistency.py")
    print("  measured the books' own boards saying our Poisson understates")
    print("  the favourite's cover by ~3.6 points. If the number above lands")
    print("  near it, two independent witnesses agree and the correction is")
    print("  worth pre-registering. If it does not, the market read is wrong")
    print("  and nothing should be changed on the strength of it.")
    print()
    print("MARGIN HISTOGRAM (absolute)")
    for k in sorted(report["margin_histogram"]):
        count = report["margin_histogram"][k]
        bar = "#" * max(1, round(count / n * 200))
        print(f"  {k:>2} runs  {count:>4}  {count / n:5.1%}  {bar}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
