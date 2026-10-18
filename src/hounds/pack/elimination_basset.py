"""Elimination Basset: the home club when it is one loss from going home."""

from __future__ import annotations

from typing import List, Optional

from src.hounds.pack.base import Context, Hound, Selection, side_info

POSTSEASON = ("F", "D", "L", "W")


def series_state(ctx: Context) -> Optional[dict]:
    """The two clubs' current postseason series from finished games before today, or None."""
    from src.situation import series as series_mod

    season = ctx.date[:4]
    pair = {ctx.home, ctx.away}
    meetings = [g for g in ctx.mlb_games
                if g.get("game_type") in POSTSEASON and g["date"][:4] == season
                and {g["home"], g["away"]} == pair
                and g.get("home_score") is not None and g.get("away_score") is not None]
    if not meetings:
        return None
    gt = meetings[-1]["game_type"]
    rnd = [g for g in meetings if g["game_type"] == gt]
    wins = {ctx.home: 0, ctx.away: 0}
    for g in rnd:
        winner = g["home"] if g["home_score"] > g["away_score"] else g["away"]
        wins[winner] += 1
    needed = series_mod.wins_needed(int(season), gt)
    if max(wins.values()) >= needed:
        return None
    return {"round": gt, "wins": wins, "needed": needed, "games": len(rnd)}


class EliminationBasset(Hound):
    id = "elimination_basset"
    name = "Elimination Basset"
    tagline = "Home when it's do or die."
    category = "history"
    style = "postseason series state"
    sports = ("mlb",)
    markets = ("moneyline",)
    RULE = ("MLB postseason moneyline. From this postseason's finished games between the two clubs, find "
            "their current series. If the home club is one loss from elimination, bet the home club. "
            "Otherwise pass.")

    def pick(self, board, ctx: Context) -> List[Selection]:
        if ctx.sport != "mlb" or not ctx.home or not ctx.away or not side_info(board, "moneyline", "home"):
            return []
        st = series_state(ctx)
        if st is None or st["wins"][ctx.away] != st["needed"] - 1:
            return []
        reason = (f"Series {ctx.home} {st['wins'][ctx.home]}-{st['wins'][ctx.away]} {ctx.away} with "
                  f"{st['needed']} wins needed: {ctx.home_name} are one loss from elimination at home.")
        return [Selection("moneyline", "home", float(st["games"]), reason)]


HOUND = EliminationBasset()
