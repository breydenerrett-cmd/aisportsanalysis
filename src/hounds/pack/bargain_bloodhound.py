"""Bargain Bloodhound: only buys below fair."""

from __future__ import annotations

from typing import List, Optional

from src.hounds.pack.base import Context, Hound, Selection, break_even, side_info

MARGIN = 0.005


def bargain(board) -> Optional[tuple]:
    """(margin, side, side info) for the moneyline side whose best price beats fair, or None."""
    best = None
    for side in ("home", "away"):
        info = side_info(board, "moneyline", side)
        if not info:
            return None
        m = info["fair"] - break_even(info["price_best"])
        if m >= MARGIN and (best is None or (m, side) > (best[0], best[1])):
            best = (m, side, info)
    return best


class BargainBloodhound(Hound):
    id = "bargain_bloodhound"
    name = "Bargain Bloodhound"
    tagline = "Only buys below fair."
    category = "math"
    style = "best price vs de-vigged consensus"
    sports = ("mlb", "nfl")
    markets = ("moneyline",)
    RULE = ("Moneyline, MLB and NFL. Bet the side whose best price has a break-even probability at least 0.5 "
            "points below the de-vigged consensus (the larger margin if both sides qualify).")

    def pick(self, board, ctx: Context) -> List[Selection]:
        b = bargain(board)
        if b is None:
            return []
        m, side, info = b
        reason = (f"Best price {info['price_best']:+d} at {info['book']} breaks even at "
                  f"{break_even(info['price_best']):.3f}, consensus fair {info['fair']:.3f}.")
        return [Selection("moneyline", side, round(m, 6), reason)]


HOUND = BargainBloodhound()
