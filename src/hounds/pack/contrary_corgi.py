"""Contrary Corgi: fades the steam."""

from __future__ import annotations

from typing import List

from src.hounds.pack import steamy_setter
from src.hounds.pack.base import Context, Hound, Selection, other


class ContraryCorgi(Hound):
    id = "contrary_corgi"
    name = "Contrary Corgi"
    tagline = "Fades the steam."
    category = "market"
    style = "line movement, against it"
    sports = ("mlb", "nfl")
    markets = ("moneyline",)
    RULE = ("Moneyline, MLB and NFL. Same trigger as Steamy Setter (the consensus moved 3.0 points or more "
            "from the open to lock). Bet the other side.")

    def pick(self, board, ctx: Context) -> List[Selection]:
        st = steamy_setter.steam(board, ctx)
        if st is None:
            return []
        side, move, was, now = st
        team = ctx.home_name if side == "home" else ctx.away_name
        reason = (f"Consensus moved {move * 100:.1f} points toward {team} since the open "
                  f"(home {was:.3f} to {now:.3f}); fading it.")
        return [Selection("moneyline", other(side), round(move, 6), reason)]


HOUND = ContraryCorgi()
