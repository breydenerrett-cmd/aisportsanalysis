"""Jet-Lag Jack: rested legs against red-eyes."""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from src.hounds.pack.base import (Context, Hound, Selection, day_before, nfl_season, parse_utc,
                                  side_info)

NFL_REST_GAP = 3


def _mlb_yesterday(ctx: Context, team: str, yesterday: str) -> Optional[dict]:
    for g in ctx.mlb_games:
        if g["date"] == yesterday and team in (g["home"], g["away"]):
            return g
    return None


def nfl_rest(ctx: Context, team: str) -> Optional[int]:
    prev = [r for r in ctx.nfl_schedule if team in (r.get("away_team"), r.get("home_team"))]
    if not prev:
        return None
    last = parse_utc(prev[-1].get("kickoff_utc"))
    if last is None:
        return None
    from src.hounds.pack.base import eastern_date

    return (date.fromisoformat(ctx.date) - date.fromisoformat(eastern_date(last))).days


class JetlagJack(Hound):
    id = "jetlag_jack"
    name = "Jet-Lag Jack"
    tagline = "Rested legs beat red-eyes."
    category = "history"
    style = "rest and travel"
    sports = ("mlb", "nfl")
    markets = ("moneyline", "spread")
    RULE = ("MLB moneyline: bet a club that did not play yesterday when its opponent played yesterday in a "
            "different ballpark from today's (the opponent travelled overnight); yesterday must be covered by "
            "the results stores. NFL spread: bet the club with 3 or more extra days of rest since its "
            "previous 2026 game.")

    def pick(self, board, ctx: Context) -> List[Selection]:
        if not ctx.home or not ctx.away:
            return []
        if ctx.sport == "mlb":
            if not side_info(board, "moneyline", "home"):
                return []
            y = day_before(ctx.date)
            if y not in ctx.mlb_covered:
                return []
            gh, ga = _mlb_yesterday(ctx, ctx.home, y), _mlb_yesterday(ctx, ctx.away, y)
            if gh is None and ga is not None and ga["home"] != ctx.home:
                side, rested, tired, park = "home", ctx.home_name, ctx.away_name, ga["home"]
            elif ga is None and gh is not None and gh["home"] != ctx.home:
                side, rested, tired, park = "away", ctx.away_name, ctx.home_name, gh["home"]
            else:
                return []
            reason = f"{rested} had yesterday off; {tired} played yesterday at {park} and travelled."
            return [Selection("moneyline", side, 1.0, reason)]
        mb = (board.get("markets") or {}).get("spread")
        if not mb:
            return []
        rh, ra = nfl_rest(ctx, ctx.home), nfl_rest(ctx, ctx.away)
        if rh is None or ra is None or abs(rh - ra) < NFL_REST_GAP:
            return []
        side = "home" if rh > ra else "away"
        reason = f"Rest days since last game: {ctx.home} {rh}, {ctx.away} {ra}."
        return [Selection("spread", side, float(abs(rh - ra)), reason)]


HOUND = JetlagJack()
