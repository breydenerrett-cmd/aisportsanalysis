"""Scrappy Schnauzer: the underdog hunter, +100 to +250 only."""

from __future__ import annotations

from typing import List

from src.hounds.pack import gridiron_greyhound, hot_streak_husky, professor_paws, steamy_setter
from src.hounds.pack.base import Context, Hound, Selection, side_info

BACKERS = (professor_paws.HOUND, gridiron_greyhound.HOUND, steamy_setter.HOUND, hot_streak_husky.HOUND)
DOG_MIN = 100
DOG_MAX = 250


class ScrappySchnauzer(Hound):
    id = "scrappy_schnauzer"
    name = "Scrappy Schnauzer"
    tagline = "The underdog hunter."
    category = "mixed"
    style = "underdogs with a reason"
    sports = ("mlb", "nfl")
    markets = ("moneyline",)
    band = (DOG_MIN, DOG_MAX)
    RULE = ("Moneyline underdogs priced +100 to +250 on the board average, MLB and NFL. Bet the underdog when "
            "at least one of Professor Paws, Gridiron Greyhound, Steamy Setter or Hot-Streak Husky picks that "
            "club in this game.")

    def pick(self, board, ctx: Context) -> List[Selection]:
        home, away = side_info(board, "moneyline", "home"), side_info(board, "moneyline", "away")
        if not home or not away:
            return []
        dog = "home" if home["fair"] < away["fair"] else "away"
        info = home if dog == "home" else away
        if not (DOG_MIN <= info["price_average"] <= DOG_MAX):
            return []
        backers = [h.id for h in BACKERS if h.applies_to(ctx.sport)
                   and any(s.side == dog and s.market in ("moneyline", "spread") for s in h.pick(board, ctx))]
        if not backers:
            return []
        team = ctx.home_name if dog == "home" else ctx.away_name
        return [Selection("moneyline", dog, float(len(backers)),
                          f"{team} at {info['price_average']:+d}, backed by {', '.join(backers)}.")]


HOUND = ScrappySchnauzer()
