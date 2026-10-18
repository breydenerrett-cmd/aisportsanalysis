"""Steamy Setter: follows the steam from the open to the lock."""

from __future__ import annotations

from typing import List, Optional

from src.hounds.pack.base import Context, Hound, Selection, side_info

MOVE = 0.030


def steam(board, ctx: Context) -> Optional[tuple]:
    """(side the consensus moved toward, move, open home fair, lock home fair) or None."""
    if not ctx.open_board:
        return None
    now_h, open_h = side_info(board, "moneyline", "home"), side_info(ctx.open_board, "moneyline", "home")
    if not now_h or not open_h:
        return None
    move = now_h["fair"] - open_h["fair"]
    if abs(move) < MOVE:
        return None
    return ("home" if move > 0 else "away"), abs(move), open_h["fair"], now_h["fair"]


class SteamySetter(Hound):
    id = "steamy_setter"
    name = "Steamy Setter"
    tagline = "Follows the steam."
    category = "market"
    style = "line movement, with it"
    sports = ("mlb", "nfl")
    markets = ("moneyline",)
    RULE = ("Moneyline, MLB and NFL. Compare the de-vigged consensus at the open (earliest capture with 3+ "
            "books, within 24 hours for MLB or 7 days for NFL, at least an hour before lock) with the "
            "consensus at lock. Bet the side the consensus moved toward if it moved 3.0 points or more.")

    def pick(self, board, ctx: Context) -> List[Selection]:
        st = steam(board, ctx)
        if st is None:
            return []
        side, move, was, now = st
        team = ctx.home_name if side == "home" else ctx.away_name
        reason = (f"Consensus moved {move * 100:.1f} points toward {team} since the open "
                  f"(home {was:.3f} to {now:.3f}).")
        return [Selection("moneyline", side, round(move, 6), reason)]


HOUND = SteamySetter()
