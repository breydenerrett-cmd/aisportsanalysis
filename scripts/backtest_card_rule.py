"""Measure THE CARD'S SELECTION RULE, not the model. Read-only.

`scripts/backtest_card.py` asks whether the run model predicts games. This
asks the different and more practical question: if the card rule had run
every day over the window where real multi-book prices exist, what would a
reader have got?

Three arms, so the model's contribution is isolated rather than assumed:

    market      take the consensus favourite on every game. No model.
    card        the published rule: consensus favourite, kept only where the
                model agrees.
    contrarian  consensus favourite, kept only where the model DISAGREES.

If `card` and `market` are indistinguishable, the model filter is doing
nothing and the honest thing is to say so on the page and in the docs. If
`contrarian` beats both, the filter has the sign backwards. Both of those
outcomes are reportable results, and neither is a reason not to publish the
card -- the card's promise is a frozen, graded pick, not a winning one.

WHAT THIS WINDOW CAN AND CANNOT SUPPORT
---------------------------------------
The multi-book store starts 2026-08-27, so this is roughly two weeks. A
couple of hundred bets settles a win-RATE question loosely and settles no
ROI question at all: the standard error on flat-stake return over 200 bets
is several percentage points, which is wider than the entire effect anyone
is arguing about. The report prints the interval next to the number for
exactly that reason, and the number is never quoted without it.

Usage:
    python scripts/backtest_card_rule.py [--season 2026] [--json]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis import calibrate, prices as prices_mod, strength  # noqa: E402
from src.core import odds as odds_math  # noqa: E402
from src.pipeline import features as features_mod  # noqa: E402
from src.pipeline import history, pitchers as pitcher_store  # noqa: E402
from src.pipeline import slate as slate_mod, snapshots  # noqa: E402


def _profit(price_american: float, won: bool) -> float:
    """Flat one-unit stake. Loss is -1, win is the decimal price minus 1."""
    if not won:
        return -1.0
    return odds_math.american_to_decimal(price_american) - 1.0


def _interval(values):
    """Mean and a normal 95% interval. Not a bootstrap: these are independent
    single-game bets with no clustering to correct for, one bet per game."""
    n = len(values)
    if n < 2:
        return (None, None, None)
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    se = math.sqrt(var / n)
    return (mean, mean - 1.96 * se, mean + 1.96 * se)


def _arm_report(name, bets):
    if not bets:
        return {"name": name, "n": 0}
    wins = sum(1 for b in bets if b["won"])
    profits = [b["profit"] for b in bets]
    mean, lo, hi = _interval(profits)
    return {
        "name": name,
        "n": len(bets),
        "wins": wins,
        "win_rate": round(wins / len(bets), 4),
        "roi": None if mean is None else round(mean * 100, 3),
        "roi_ci95": None if lo is None else [round(lo * 100, 3), round(hi * 100, 3)],
        "units": round(sum(profits), 2),
        "avg_price": round(sum(b["price"] for b in bets) / len(bets), 1),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2026")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    store = history.read_results()
    logs = pitcher_store.read_logs() or None

    # Boards first: they define the window, and it is far shorter than the
    # results store's.
    boards = prices_mod.boards_by_matchup()
    if not boards:
        print("no multi-book boards stored -- nothing to measure",
              file=sys.stderr)
        return 1
    board_dates = sorted({key[2] for key in boards})

    table = features_mod.build_training_table(
        store, min_date=board_dates[0], max_date=board_dates[-1],
        pitcher_logs=logs, require_complete=True)
    rows = table["rows"]
    if not rows:
        print("no completed games inside the priced window", file=sys.stderr)
        return 1

    # The calibration must be fit on games BEFORE the window, otherwise every
    # arm is scored with a fit that has already seen its own outcomes. Fitting
    # on the pre-window season is the same thing `fit_card_calibration.py`
    # does nightly, one day at a time.
    pre = features_mod.build_training_table(
        store, min_date=f"{args.season}-04-15", max_date=board_dates[0],
        pitcher_logs=logs, require_complete=True)
    league_pre = strength.league_runs_per_game(pre["rows"]) or None
    pairs = []
    for row in pre["rows"]:
        try:
            pairs.append((strength.model_line(row, league_rpg=league_pre)["p_home"],
                          int(row["home_won"])))
        except strength.StrengthError:
            continue
    cal = calibrate.fit(pairs)

    league = strength.league_runs_per_game(rows) or league_pre
    arms = defaultdict(list)
    skipped = defaultdict(int)

    for row in rows:
        away = row["away_team"]
        home = row["home_team"]
        key = prices_mod.matchup_key(away, home, row["date"])
        board = boards.get(key)
        if not board:
            skipped["no_board"] += 1
            continue
        snap = prices_mod.snapshot(board["quotes"])
        if snap.get("skipped"):
            skipped["thin_board"] += 1
            continue
        sides = snap.get("sides") or {}
        pa = (sides.get("away") or {}).get("consensus_probability")
        ph = (sides.get("home") or {}).get("consensus_probability")
        if pa is None or ph is None:
            skipped["no_consensus"] += 1
            continue

        side = "away" if pa > ph else "home"
        detail = sides.get(side) or {}
        price = detail.get("best_price")
        if price is None:
            skipped["no_price"] += 1
            continue

        try:
            line = strength.model_line(row, league_rpg=league)
        except strength.StrengthError:
            skipped["no_model_line"] += 1
            continue
        p_home = cal.apply(line["p_home"])
        model_p = p_home if side == "home" else 1.0 - p_home
        agrees = model_p > 0.5

        won = bool(row["home_won"]) if side == "home" else not row["home_won"]
        bet = {"won": won, "price": price, "profit": _profit(price, won),
               "date": row["date"], "side": side}

        arms["market"].append(bet)
        arms["card" if agrees else "contrarian"].append(bet)

    report = {
        "window": [board_dates[0], board_dates[-1]],
        "n_dates": len(board_dates),
        "calibration": cal.to_dict(),
        "skipped": dict(skipped),
        "arms": [_arm_report("market: every consensus favourite", arms["market"]),
                 _arm_report("card: favourite, model agrees", arms["card"]),
                 _arm_report("contrarian: favourite, model disagrees",
                             arms["contrarian"])],
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"WINDOW   {report['window'][0]} .. {report['window'][1]}  "
          f"({report['n_dates']} dates)")
    print(f"CALIB    {report['calibration']}")
    print()
    for arm in report["arms"]:
        if not arm.get("n"):
            print(f"  {arm['name']:<42} (no bets)")
            continue
        ci = arm["roi_ci95"]
        print(f"  {arm['name']:<42} n={arm['n']:<4} "
              f"win {arm['win_rate']:.1%}  "
              f"ROI {arm['roi']:+.1f}%  "
              f"[{ci[0]:+.1f}%, {ci[1]:+.1f}%]  "
              f"avg price {arm['avg_price']:+.0f}")
    print(f"\n  skipped: {report['skipped']}")
    print("\n  READ THE INTERVALS, NOT THE POINT ESTIMATES. Over a window this")
    print("  short every arm's interval spans several points of ROI, so a")
    print("  difference between arms smaller than that is not a finding.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
