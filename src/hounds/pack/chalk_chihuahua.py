"""Chalk Chihuahua: always the favourite (inside the -200 rule)."""

from __future__ import annotations

from typing import List

from src.hounds.pack.base import PRICE_MIN, Context, Hound, Selection, side_info

FAV_MAX = -101


class ChalkChihuahua(Hound):
    id = "chalk_chihuahua"
    name = "Chalk Chihuahua"
    tagline = "Always the favourite."
    category = "simple"
    style = "favourites"
    sports = ("mlb", "nfl")
    markets = ("moneyline",)
    band = (PRICE_MIN, FAV_MAX)
    RULE = ("Moneyline, MLB and NFL. Bet the favourite (the side with the higher de-vigged consensus) when "
            "its board-average price is between -199 and -101.")

    def pick(self, board, ctx: Context) -> List[Selection]:
        home, away = side_info(board, "moneyline", "home"), side_info(board, "moneyline", "away")
        if not home or not away or home["fair"] == away["fair"]:
            return []
        fav = "home" if home["fair"] > away["fair"] else "away"
        info = home if fav == "home" else away
        if not (PRICE_MIN <= info["price_average"] <= FAV_MAX):
            return []
        team = ctx.home_name if fav == "home" else ctx.away_name
        return [Selection("moneyline", fav, info["fair"], f"{team} are the favourite at {info['price_average']:+d}.")]


HOUND = ChalkChihuahua()
