"""Professor Paws: the house run model, fed only unsealed inputs, shrunk halfway to the market."""

from __future__ import annotations

from typing import List, Optional

from src.hounds.pack.base import Context, Hound, Selection, mlb_team_games, side_info

MIN_GAMES = 5
SHRINK = 0.5
GAP = 0.020


def team_rates(ctx: Context, team: str) -> Optional[dict]:
    games = mlb_team_games(ctx, team)
    if not games:
        return None
    n = len(games)
    return {"rs": sum(g["rf"] for g in games) / n, "ra": sum(g["ra"] for g in games) / n, "n": n}


def league_rpg(ctx: Context) -> Optional[float]:
    runs, sides = 0, 0
    for g in ctx.mlb_games:
        if g.get("away_score") is None or g.get("home_score") is None:
            continue
        runs += g["away_score"] + g["home_score"]
        sides += 2
    return runs / sides if sides else None


def model(ctx: Context, total_line: Optional[float] = None) -> Optional[dict]:
    """strength.model_line on window team rates only; memoised per context and line."""
    key = ("professor_paws_model", total_line)
    if key in ctx.cache:
        return ctx.cache[key]
    from src.analysis import strength

    out = None
    a, h, lg = team_rates(ctx, ctx.away or ""), team_rates(ctx, ctx.home or ""), league_rpg(ctx)
    if a and h and lg and a["n"] >= MIN_GAMES and h["n"] >= MIN_GAMES:
        features = {"away_runs_scored_pg": a["rs"], "away_runs_allowed_pg": a["ra"], "away_games_played": a["n"],
                    "home_runs_scored_pg": h["rs"], "home_runs_allowed_pg": h["ra"], "home_games_played": h["n"]}
        try:
            line = strength.model_line(features, league_rpg=lg,
                                       totals=[total_line] if total_line is not None else None)
        except strength.StrengthError:
            line = None
        if line is not None:
            out = {"p_home": line["p_home"], "p_over": (line["p_over"] or {}).get(total_line),
                   "expected_total": line["expected_total"], "away": a, "home": h, "league_rpg": lg}
    ctx.cache[key] = out
    return out


class ProfessorPaws(Hound):
    id = "professor_paws"
    name = "Professor Paws"
    tagline = "The house model, on a leash."
    category = "stats"
    style = "model vs market, shrunk halfway to the market"
    sports = ("mlb",)
    markets = ("moneyline",)
    who_decided = "model"
    RULE = ("MLB moneyline. Feed the house run model (strength.model_line) each club's runs scored and "
            "allowed per game since 2026-08-28 (games before today; both clubs need 5+). Shrink its home "
            "win probability 50% toward the de-vigged consensus. Bet the side whose shrunk probability "
            "beats the consensus by 2.0 points or more.")

    def pick(self, board, ctx: Context) -> List[Selection]:
        if ctx.sport != "mlb":
            return []
        home, away = side_info(board, "moneyline", "home"), side_info(board, "moneyline", "away")
        m = model(ctx)
        if not home or not away or not m:
            return []
        p_home = SHRINK * m["p_home"] + (1 - SHRINK) * home["fair"]
        gaps = {"home": p_home - home["fair"], "away": (1 - p_home) - away["fair"]}
        side = max(gaps, key=gaps.get)
        if gaps[side] < GAP:
            return []
        team = ctx.home_name if side == "home" else ctx.away_name
        reason = (f"Model {m['p_home'] if side == 'home' else 1 - m['p_home']:.3f} for {team} from runs "
                  f"scored/allowed since 2026-08-28, shrunk to {p_home if side == 'home' else 1 - p_home:.3f}, "
                  f"vs consensus {(home if side == 'home' else away)['fair']:.3f}.")
        return [Selection("moneyline", side, round(gaps[side], 6), reason)]


HOUND = ProfessorPaws()
