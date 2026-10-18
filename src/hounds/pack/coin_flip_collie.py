"""Coin-Flip Collie: the control. A seeded coin, nothing else."""

from __future__ import annotations

from typing import List

from src.hounds.pack.base import Context, Hound, Selection, seed_bytes, side_info


class CoinFlipCollie(Hound):
    id = "coin_flip_collie"
    name = "Coin-Flip Collie"
    tagline = "The control."
    category = "random"
    style = "seeded coin flip (control)"
    sports = ("mlb", "nfl")
    markets = ("moneyline",)
    who_decided = "random"
    RULE = ("Control, moneyline, MLB and NFL. Seed = sha256 of 'coin_flip_collie|' plus the odds event id. "
            "Home if the seed's first byte is even, away if odd. Every game qualifies.")

    def pick(self, board, ctx: Context) -> List[Selection]:
        if not side_info(board, "moneyline", "home"):
            return []
        b = seed_bytes(self.id, ctx.event_id)
        side = "home" if b[0] % 2 == 0 else "away"
        return [Selection("moneyline", side, 0.0, f"Seeded coin flip (first byte {b[0]}): {side}. A control.")]


HOUND = CoinFlipCollie()
