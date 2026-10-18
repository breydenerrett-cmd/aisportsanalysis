"""Dartboard Dalmatian: throws a dart at the board. A control."""

from __future__ import annotations

from typing import List

from src.hounds.pack.base import SIDES, Context, Hound, Selection, seed_bytes

DART_MARKETS = ("moneyline", "spread", "total")


class DartboardDalmatian(Hound):
    id = "dartboard_dalmatian"
    name = "Dartboard Dalmatian"
    tagline = "Throws a dart at the board."
    category = "random"
    style = "seeded random market and side (control)"
    sports = ("mlb", "nfl")
    markets = DART_MARKETS
    who_decided = "random"
    RULE = ("Control, MLB and NFL. Seed = sha256 of 'dartboard_dalmatian|' plus the odds event id. Market = "
            "moneyline, spread or total by the first byte mod 3; side = home/Over if the second byte is "
            "even, away/Under if odd. Pass if that market is not on the board.")

    def pick(self, board, ctx: Context) -> List[Selection]:
        b = seed_bytes(self.id, ctx.event_id)
        market = DART_MARKETS[b[0] % 3]
        if market not in (board.get("markets") or {}):
            return []
        side = SIDES[market][0] if b[1] % 2 == 0 else SIDES[market][1]
        return [Selection(market, side, 0.0, f"Seeded dart (bytes {b[0]}, {b[1]}): {market} {side}. A control.")]


HOUND = DartboardDalmatian()
