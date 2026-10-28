"""The selection rule at one decision point (docs/PREREG_LIVE_TENNIS.md sections 4 to 6). Deterministic and pure.

Two pure steps, both free of clocks, files and the network:

    prematch_p0(quotes)        the pre-match consensus that seeds the model (or None if fewer than 3 books)
    evaluate(model, fresh)     BET / NO_BET / EXCLUDED for one decision point, from the model's match price
                               and the FRESH quotes of the decision board

Order of the board checks, the first failure being the recorded reason: fewer than MIN_FRESH_BOOKS fresh books
(THIN_BOARD), the best fresh implied probabilities on the two sides summing below BEST_IMPLIED_SUM_FLOOR
(INCONSISTENT_BOARD: more than a 1% arbitrage across books means some quote is stale), then the gap rule.

The GAP of a side is 100 * (model probability - raw implied probability of the best, highest-decimal-odds
fresh price on that side), in probability points. The side with the larger gap is the candidate (a tie goes
to the home side); it is a BET only if the gap is at least GAP_THRESHOLD_PP, else NO_BET (BELOW_THRESHOLD).
One bet per decision point, never more. Nothing here places anything anywhere.
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

from src.research.live_tennis import board, config

BET = "BET"
NO_BET = "NO_BET"
EXCLUDED = "EXCLUDED"

# Exclusion and no-bet reasons, in one place so the report counts every one of them by name.
REASONS = (
    "BELOW_THRESHOLD", "THIN_BOARD", "INCONSISTENT_BOARD", "SCORE_MOVED", "NO_PREMATCH_PRICE",
    "MODEL_OUT_OF_RANGE", "CREDIT_REFUSED", "WINDOW_EXPIRED", "UNMATCHED", "FORMAT_CONTRADICTION",
)


def dp_id(event_id: str, set_number: int) -> str:
    """The one id of a decision point: (Odds API event, set number). One DP per (event, N), ever."""
    return f"{event_id}:S{int(set_number)}"


def prematch_p0(quotes: Sequence[Mapping]) -> Optional[dict]:
    """The pre-match consensus that seeds the model: {p0_home, n_books} over ALL quotes given, or None under 3 books."""
    stats = board.board_stats(quotes)
    if stats is None or stats["n_books"] < config.MIN_FRESH_BOOKS:
        return None
    return {"p0_home": stats["consensus_home"], "n_books": stats["n_books"]}


def evaluate(p_match_home: float, fresh: Sequence[Mapping]) -> dict:
    """The decision for one board. `p_match_home` is the model's match-win probability for the HOME player.

    -> {status, reason, side, gap_pp_home, gap_pp_away, stats, n_fresh}. `side` is the candidate side whenever a
    board exists (even for NO_BET), None when the board itself was refused.
    """
    n = len(fresh)
    if n < config.MIN_FRESH_BOOKS:
        return {"status": EXCLUDED, "reason": "THIN_BOARD", "side": None, "gap_pp_home": None,
                "gap_pp_away": None, "stats": board.board_stats(fresh), "n_fresh": n}
    stats = board.board_stats(fresh)
    if stats["best_implied_sum"] < config.BEST_IMPLIED_SUM_FLOOR:
        return {"status": EXCLUDED, "reason": "INCONSISTENT_BOARD", "side": None, "gap_pp_home": None,
                "gap_pp_away": None, "stats": stats, "n_fresh": n}
    gap_home = 100.0 * (p_match_home - stats["best_home"]["implied"])
    gap_away = 100.0 * ((1.0 - p_match_home) - stats["best_away"]["implied"])
    side = "home" if gap_home >= gap_away else "away"
    gap = gap_home if side == "home" else gap_away
    if gap >= config.GAP_THRESHOLD_PP:
        status, reason = BET, None
    else:
        status, reason = NO_BET, "BELOW_THRESHOLD"
    return {"status": status, "reason": reason, "side": side, "gap_pp_home": gap_home,
            "gap_pp_away": gap_away, "stats": stats, "n_fresh": n}


def model_for(p0_home: float, sport_key: str, home_sets: int, away_sets: int) -> Optional[dict]:
    """The model's prices for a decision point, or None when the pre-match price is out of the model's range
    (or the key is neither an ATP nor a WTA key). Delegates to markov.model_prices with the frozen constants."""
    from src.research.live_tennis import markov

    tour = config.tour_of(sport_key)
    level = config.serve_level(tour) if tour else None
    if level is None:
        return None
    priced = markov.model_prices(p0_home, level, config.sets_to_win(sport_key), config.SKILL_GAP_BOUND,
                                 home_sets, away_sets)
    if priced is None:
        return None
    priced = dict(priced)
    priced["serve_level"] = level
    priced["sets_to_win"] = config.sets_to_win(sport_key)
    priced["tour"] = tour
    return priced
