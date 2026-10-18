"""Relief Retriever: fades the tired bullpen."""

from __future__ import annotations

from typing import List, Optional

from src.hounds.pack.base import Context, Hound, Selection, day_before, side_info

GAP = 120
DAYS = 3


def relief_pitches(ctx: Context, team: str) -> Optional[int]:
    days = [day_before(ctx.date, n) for n in range(1, DAYS + 1)]
    if any(d not in ctx.bullpen_dates for d in days):
        return None
    total = 0
    for r in ctx.bullpen:
        if r.get("empty") or r.get("team") != team or r.get("started"):
            continue
        if str(r.get("date")) in days:
            total += int(r.get("pitches") or 0)
    return total


class ReliefRetriever(Hound):
    id = "relief_retriever"
    name = "Relief Retriever"
    tagline = "Counts the bullpen's pitches."
    category = "stats"
    style = "bullpen fatigue"
    sports = ("mlb",)
    markets = ("moneyline",)
    RULE = ("MLB moneyline. Add up each club's relief pitches (bullpen log, non-starters) over the three "
            "calendar days before the game. If one bullpen threw 120 or more pitches more than the other, "
            "bet the club with the fresher bullpen. All three days must be in the bullpen log.")

    def pick(self, board, ctx: Context) -> List[Selection]:
        if ctx.sport != "mlb" or not ctx.home or not ctx.away:
            return []
        if not side_info(board, "moneyline", "home"):
            return []
        h, a = relief_pitches(ctx, ctx.home), relief_pitches(ctx, ctx.away)
        if h is None or a is None:
            return []
        gap = h - a
        if abs(gap) < GAP:
            return []
        side = "away" if gap > 0 else "home"
        fresh, tired = (ctx.away_name, ctx.home_name) if side == "away" else (ctx.home_name, ctx.away_name)
        reason = (f"{tired} relievers threw {max(h, a)} pitches over the last three days, "
                  f"{fresh} relievers {min(h, a)}.")
        return [Selection("moneyline", side, float(abs(gap)), reason)]


HOUND = ReliefRetriever()
