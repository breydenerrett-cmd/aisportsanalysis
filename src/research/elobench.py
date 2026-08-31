"""A public-style Elo projection, scored against the closing line.

The benchmark docs/BENCHMARK_ELO.md froze: a results-only Elo with
FiveThirtyEight's published constants (K=4, home advantage 24, preseason
1/3 regression), burned in on 2023, scored on 2024 against the de-vigged
close consensus, by log-loss and Brier, with a date-clustered p on the
per-game log-loss differential. The expected answer is stated there in
advance: the close wins.

POINT-IN-TIME BY CONSTRUCTION
-----------------------------
The only input is the results store, processed in (date, start time,
game_pk) order, and every forecast is emitted BEFORE that game's result
touches a rating. There is no pitcher adjustment because the store's
"probable" column is retroactively the actual starter -- a small lookahead
this module refuses rather than footnotes.
"""

from __future__ import annotations

import csv
import math

from pathlib import Path

from src.data import parks
from src.model import discovery, selections
from src.pipeline import backfill

RESULTS_PATH = Path("data/historical/mlb_results.csv")

# FiveThirtyEight's published MLB Elo constants, adopted a priori.
BASE = 1500.0
SCALE = 400.0
K = 4.0
HOME_ADVANTAGE = 24.0
PRESEASON_REGRESSION = 1.0 / 3.0

# A close consensus over fewer books than this is not a consensus (the
# same floor every module uses).
MIN_BOOKS = 6

BURN_SEASON = 2023
SCORED_SEASON = 2024


class EloBenchError(RuntimeError):
    """Raised when the benchmark cannot run honestly."""


def read_results(path=RESULTS_PATH, seasons=(BURN_SEASON, SCORED_SEASON)) -> list:
    """Regular-season rows for the named seasons, in play order."""
    rows = []
    with open(path, encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            season = int((row.get("date") or "0000")[:4] or 0)
            if season not in seasons:
                continue
            if (row.get("game_type") or "R") != "R":
                continue
            if row.get("home_won") in (None, ""):
                continue
            rows.append(row)
    rows.sort(key=lambda r: (r["date"], r.get("start_time_utc") or "",
                             r.get("game_pk") or ""))
    return rows


def forecast_probability(rating_home, rating_away) -> float:
    return 1.0 / (1.0 + 10.0 ** (-((rating_home + HOME_ADVANTAGE
                                    - rating_away) / SCALE)))


def forecasts(rows) -> list:
    """One forecast per game, emitted before the game updates the ratings.

    Season boundaries regress every club 1/3 toward 1500 -- the public
    methodology's answer to roster churn, applied blindly rather than
    tuned.
    """
    ratings = {}
    current_season = None
    out = []
    for row in rows:
        season = int(row["date"][:4])
        if current_season is not None and season != current_season:
            for team in list(ratings):
                ratings[team] = (ratings[team]
                                 + PRESEASON_REGRESSION * (BASE - ratings[team]))
        current_season = season

        home = parks.canonical_team(row["home_team"])
        away = parks.canonical_team(row["away_team"])
        rating_home = ratings.get(home, BASE)
        rating_away = ratings.get(away, BASE)
        probability = forecast_probability(rating_home, rating_away)
        out.append(dict(row, season=season, elo_home=probability))

        home_won = str(row["home_won"]) in ("1", "True", "true")
        ratings[home] = rating_home + K * ((1.0 if home_won else 0.0)
                                           - probability)
        ratings[away] = rating_away + K * ((0.0 if home_won else 1.0)
                                           - (1.0 - probability))
    return out


def _log_loss(probability, outcome) -> float:
    # Clamped away from 0/1 so a degenerate forecast cannot produce an
    # infinite loss and silently dominate the mean.
    clamped = min(max(probability, 1e-6), 1.0 - 1e-6)
    return -math.log(clamped if outcome else 1.0 - clamped)


def _brier(probability, outcome) -> float:
    return (probability - (1.0 if outcome else 0.0)) ** 2


def score(price_pairs=None, results_path=RESULTS_PATH) -> dict:
    """The frozen benchmark: 2023 burn-in, 2024 scored against the close.

    Returns the published result dict; every unscored 2024 game is counted
    with its reason, because coverage is part of the answer.
    """
    rows = read_results(results_path)
    if not any(int(r["date"][:4]) == BURN_SEASON for r in rows):
        raise EloBenchError(f"no {BURN_SEASON} burn-in rows in the store")
    projected = [r for r in forecasts(rows) if r["season"] == SCORED_SEASON]

    if price_pairs is None:
        price_pairs = backfill.price_pair(SCORED_SEASON)
    index = selections.index_price_pairs(price_pairs)

    scored, unscored = [], {"no_price_pair": 0, "not_distinct": 0,
                            "thin_consensus": 0}
    for row in projected:
        key = (parks.canonical_team(row["away_team"]),
               parks.canonical_team(row["home_team"]), row["date"])
        pair = selections._resolve_pair(index.get(key), row)
        if not pair:
            unscored["no_price_pair"] += 1
            continue
        if not pair.get("distinct"):
            unscored["not_distinct"] += 1
            continue
        fair = selections._fair(pair["close"]["bookmakers"],
                                pair["home_team"], pair["away_team"])
        if not fair or fair["books"] < MIN_BOOKS:
            unscored["thin_consensus"] += 1
            continue
        outcome = str(row["home_won"]) in ("1", "True", "true")
        elo_ll = _log_loss(row["elo_home"], outcome)
        close_ll = _log_loss(fair["home_fair"], outcome)
        scored.append({
            "date": row["date"],
            "elo_home": round(row["elo_home"], 5),
            "close_home": round(fair["home_fair"], 5),
            "home_won": outcome,
            "elo_log_loss": elo_ll,
            "close_log_loss": close_ll,
            "elo_brier": _brier(row["elo_home"], outcome),
            "close_brier": _brier(fair["home_fair"], outcome),
            # Positive: Elo is worse than the close on this game.
            "_diff": elo_ll - close_ll,
        })

    if not scored:
        raise EloBenchError("no 2024 game could be scored against a close")

    n = len(scored)
    mean_diff = sum(r["_diff"] for r in scored) / n
    return {
        "scored": n,
        "unscored": unscored,
        "elo_log_loss": round(sum(r["elo_log_loss"] for r in scored) / n, 5),
        "close_log_loss": round(sum(r["close_log_loss"] for r in scored) / n, 5),
        "elo_brier": round(sum(r["elo_brier"] for r in scored) / n, 5),
        "close_brier": round(sum(r["close_brier"] for r in scored) / n, 5),
        "log_loss_diff": round(mean_diff, 5),
        "diff_p_clustered": round(
            discovery.clustered_two_sided_p(mean_diff, scored), 6),
        "note": ("positive log_loss_diff = the close forecasts better than "
                 "the public-style Elo, as pre-stated in "
                 "docs/BENCHMARK_ELO.md"),
    }
