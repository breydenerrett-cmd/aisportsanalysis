"""Home Dog Hank: the home underdog."""

from __future__ import annotations

from typing import List

from src.hounds.pack.base import PRICE_MAX, Context, Hound, Selection, side_info

DOG_MIN = 100


class HomeDogHank(Hound):
    id = "home_dog_hank"
    name = "Home Dog Hank"
    tagline = "The home underdog."
    category = "simple"
    style = "home underdogs"
    sports = ("mlb", "nfl")
    markets = ("moneyline",)
    band = (DOG_MIN, PRICE_MAX)
    RULE = "Moneyline, MLB and NFL. Bet the home club when its board-average price is +100 to +400."

    def pick(self, board, ctx: Context) -> List[Selection]:
        home = side_info(board, "moneyline", "home")
        if not home or not (DOG_MIN <= home["price_average"] <= PRICE_MAX):
            return []
        return [Selection("moneyline", "home", home["fair"],
                          f"{ctx.home_name} are at home and the underdog at {home['price_average']:+d}.")]


HOUND = HomeDogHank()
