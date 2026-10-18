"""Grudge Bulldog: never forgets a beating."""

from __future__ import annotations

from datetime import timedelta
from typing import List

from src.hounds.pack.base import Context, Hound, Selection, day_before, parse_utc, side_info

NFL_MARGIN = 7
NFL_WINDOW = timedelta(days=450)
MLB_MARGIN = 5


class GrudgeBulldog(Hound):
    id = "grudge_bulldog"
    name = "Grudge Bulldog"
    tagline = "Never forgets."
    category = "intangibles"
    style = "revenge and bounce-back"
    sports = ("mlb", "nfl")
    markets = ("moneyline", "spread")
    RULE = ("NFL spread: bet a club that lost the two clubs' most recent meeting (a final since 2021, within "
            "450 days before kickoff) by 7 or more points. MLB moneyline: bet a club that lost to the same "
            "opponent yesterday by 5 or more runs.")

    def pick(self, board, ctx: Context) -> List[Selection]:
        if not ctx.home or not ctx.away:
            return []
        pair = {ctx.home, ctx.away}
        if ctx.sport == "nfl":
            meets = [g for g in ctx.nfl_games if {g.get("home_team"), g.get("away_team")} == pair
                     and g.get("home_score") is not None and g.get("away_score") is not None]
            if not meets:
                return []
            g = meets[-1]
            k = parse_utc(g.get("kickoff_utc"))
            if k is None or ctx.start - k > NFL_WINDOW:
                return []
            margin = g["home_score"] - g["away_score"]
            loser = g["away_team"] if margin > 0 else g["home_team"]
            if abs(margin) < NFL_MARGIN:
                return []
            side = "home" if loser == ctx.home else "away"
            if not side_info(board, "spread", side):
                return []
            reason = (f"{loser} lost the last meeting {max(g['home_score'], g['away_score'])}-"
                      f"{min(g['home_score'], g['away_score'])} on {g.get('gameday')}.")
            return [Selection("spread", side, float(abs(margin)), reason)]
        y = day_before(ctx.date)
        prev = [g for g in ctx.mlb_games if g["date"] == y and {g["home"], g["away"]} == pair
                and g.get("home_score") is not None and g.get("away_score") is not None]
        if not prev:
            return []
        g = prev[-1]
        margin = g["home_score"] - g["away_score"]
        if abs(margin) < MLB_MARGIN:
            return []
        loser = g["away"] if margin > 0 else g["home"]
        side = "home" if loser == ctx.home else "away"
        if not side_info(board, "moneyline", side):
            return []
        reason = (f"{loser} lost to the same opponent yesterday "
                  f"{max(g['home_score'], g['away_score'])}-{min(g['home_score'], g['away_score'])}.")
        return [Selection("moneyline", side, float(abs(margin)), reason)]


HOUND = GrudgeBulldog()
