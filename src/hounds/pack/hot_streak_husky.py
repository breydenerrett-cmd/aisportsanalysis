"""Hot-Streak Husky: rides the hot hand."""

from __future__ import annotations

from typing import List, Optional

from src.hounds.pack.base import (Context, Hound, Selection, mlb_team_games, nfl_season, nfl_team_games,
                                  side_info)

MLB_LAST = 10
MLB_HOT = 7
MLB_COLD = 4
NFL_HOT = 3
NFL_COLD = 2


def mlb_last10_wins(ctx: Context, team: str) -> Optional[int]:
    games = mlb_team_games(ctx, team)
    if len(games) < MLB_LAST:
        return None
    return sum(1 for g in games[-MLB_LAST:] if g["won"])


def nfl_streak(ctx: Context, team: str) -> int:
    """+n for an n-game winning streak, -n for losing; 0 with no games or after a tie."""
    games = nfl_team_games(ctx, team, season=nfl_season(ctx))
    n = 0
    for g in reversed(games):
        if g["tied"]:
            break
        if n == 0:
            n = 1 if g["won"] else -1
        elif (n > 0) == g["won"]:
            n += 1 if n > 0 else -1
        else:
            break
    return n


def hot_side(ctx: Context) -> Optional[tuple]:
    """(side, score, description) the Husky backs, or None. Shared with Scrappy Schnauzer."""
    if not ctx.home or not ctx.away:
        return None
    if ctx.sport == "mlb":
        h, a = mlb_last10_wins(ctx, ctx.home), mlb_last10_wins(ctx, ctx.away)
        if h is None or a is None:
            return None
        if h >= MLB_HOT and a <= MLB_COLD:
            return "home", float(h), f"{ctx.home} {h}-{MLB_LAST - h} in their last 10, {ctx.away} {a}-{MLB_LAST - a}."
        if a >= MLB_HOT and h <= MLB_COLD:
            return "away", float(a), f"{ctx.away} {a}-{MLB_LAST - a} in their last 10, {ctx.home} {h}-{MLB_LAST - h}."
        return None
    h, a = nfl_streak(ctx, ctx.home), nfl_streak(ctx, ctx.away)
    if h >= NFL_HOT and a <= -NFL_COLD:
        return "home", float(h), f"{ctx.home} have won {h} straight, {ctx.away} have lost {-a} straight."
    if a >= NFL_HOT and h <= -NFL_COLD:
        return "away", float(a), f"{ctx.away} have won {a} straight, {ctx.home} have lost {-h} straight."
    return None


class HotStreakHusky(Hound):
    id = "hot_streak_husky"
    name = "Hot-Streak Husky"
    tagline = "Rides the hot hand."
    category = "intangibles"
    style = "momentum"
    sports = ("mlb", "nfl")
    markets = ("moneyline", "spread")
    RULE = ("MLB moneyline: over each club's last 10 games since 2026-08-28, bet a club that won 7 or more "
            "against one that won 4 or fewer. NFL spread: bet a club on a 2026 winning streak of 3 or more "
            "against one on a losing streak of 2 or more.")

    def pick(self, board, ctx: Context) -> List[Selection]:
        hs = hot_side(ctx)
        if hs is None:
            return []
        side, score, text = hs
        market = "moneyline" if ctx.sport == "mlb" else "spread"
        if not side_info(board, market, side):
            return []
        return [Selection(market, side, score, text)]


HOUND = HotStreakHusky()
