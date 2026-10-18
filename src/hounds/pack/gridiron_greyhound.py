"""Gridiron Greyhound: point differential per game against the spread."""

from __future__ import annotations

from typing import List, Optional

from src.hounds.pack.base import Context, Hound, Selection, nfl_season, nfl_team_games

MIN_GAMES = 2
HOME_FIELD = 1.5
BAR = 3.0


def pd_per_game(ctx: Context, team: str) -> Optional[tuple]:
    games = nfl_team_games(ctx, team, season=nfl_season(ctx))
    if len(games) < MIN_GAMES:
        return None
    return sum(g["pf"] - g["pa"] for g in games) / len(games), len(games)


def cover_margin(ctx: Context, board) -> Optional[tuple]:
    mb = (board.get("markets") or {}).get("spread")
    if ctx.sport != "nfl" or not mb or mb["line"] is None or not ctx.home or not ctx.away:
        return None
    h, a = pd_per_game(ctx, ctx.home), pd_per_game(ctx, ctx.away)
    if h is None or a is None:
        return None
    expected = 0.5 * (h[0] - a[0]) + HOME_FIELD
    return expected + mb["line"], expected, h, a, mb["line"]


class GridironGreyhound(Hound):
    id = "gridiron_greyhound"
    name = "Gridiron Greyhound"
    tagline = "Point differential with a whistle."
    category = "stats"
    style = "simple rating vs spread"
    sports = ("nfl",)
    markets = ("spread",)
    RULE = ("NFL spread, main line. Expected home margin = half of (home point differential per game minus "
            "away point differential per game, 2026 finals before kickoff, 2+ games each) plus 1.5 for home "
            "field. Add the home spread line. Bet the home side if that is +3.0 or more, the away side if "
            "-3.0 or less.")

    def pick(self, board, ctx: Context) -> List[Selection]:
        cm = cover_margin(ctx, board)
        if cm is None:
            return []
        margin, expected, h, a, line = cm
        if abs(margin) < BAR:
            return []
        side = "home" if margin > 0 else "away"
        reason = (f"Point differential per game {ctx.home} {h[0]:+.1f} ({h[1]} games), {ctx.away} {a[0]:+.1f} "
                  f"({a[1]}); expected home margin {expected:+.1f} vs home line {line:+g}.")
        return [Selection("spread", side, round(abs(margin), 4), reason)]


HOUND = GridironGreyhound()
