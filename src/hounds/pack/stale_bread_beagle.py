"""Stale-Bread Beagle: a book far off the consensus."""

from __future__ import annotations

from typing import List

from src.hounds.pack.base import MARKETS, SIDES, Context, Hound, Selection, break_even

MIN_BOOKS = 5
EDGE = 0.025


class StaleBreadBeagle(Hound):
    id = "stale_bread_beagle"
    name = "Stale-Bread Beagle"
    tagline = "Sniffs out a stale book."
    category = "market"
    style = "book disagreement"
    sports = ("mlb", "nfl")
    markets = ("moneyline", "spread", "total")
    RULE = ("MLB and NFL, moneyline, main spread and main total, sides with 5+ books on the line. Edge = "
            "the side's de-vigged consensus minus the raw implied probability of its best price. Bet the "
            "single largest edge if it is 2.5 points or more. Graded at the board average like every hound.")

    def pick(self, board, ctx: Context) -> List[Selection]:
        best = None
        for market in MARKETS:
            mb = (board.get("markets") or {}).get(market)
            if not mb:
                continue
            for side in SIDES[market]:
                info = mb["sides"][side]
                if info["book_count"] < MIN_BOOKS:
                    continue
                edge = info["fair"] - break_even(info["price_best"])
                key = (edge, market, side)
                if best is None or key > best:
                    best = key
        if best is None or best[0] < EDGE:
            return []
        edge, market, side = best
        info = board["markets"][market]["sides"][side]
        reason = (f"{info['book']} offers {info['price_best']:+d} against a consensus fair of {info['fair']:.3f} "
                  f"across {info['book_count']} books: {edge * 100:.1f} points off.")
        return [Selection(market, side, round(edge, 6), reason)]


HOUND = StaleBreadBeagle()
