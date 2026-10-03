"""The matchup fact sheet: one game, both teams side by side, with the market and what is missing.

The page an analyst (or the AI analyst) reads before forming a view of a game. It contains
facts and nothing else: no prediction, no pick, no edge, no "value". The only probabilities in
it are the MARKET's own, labelled as such (`implied` is a price turned into a probability;
`without_margin` is that probability after the bookmaker's margin is divided out). They are not
ours and must not be read as ours.

LEAKAGE
-------
`as_of` is the one moment everything is measured at. It defaults to the game's kickoff, and it
may not be later than the kickoff (`features.game_features` refuses it): both teams' form, rest,
travel, injuries, the head-to-head and every differential go through `features.completed_games`,
which admits only games that finished before it, so nothing in the sheet can see the game it
describes. The sheet does not print the game's score. Three blocks are recorded at or near game
time and say `"as_of_safe": false`; nothing else reads them: the closing market, the observed
conditions, and the quarterback and coach listed for the game.

THE MARKET BLOCK
----------------
Prices are American. `implied` = 100/(p+100) for a plus price and |p|/(|p|+100) for a minus
price. A two-way market's margin is the sum of the two implied probabilities minus 1 and
`without_margin` divides each by that sum; with a price missing the implied figure is still
shown and `margin` and `without_margin` are None. The spread is shown two ways: nflverse's
`spread_line` (positive when the HOME team is favoured) and in betting convention (the
favourite's number is negative), so neither reading is a guess.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.datasvc.nfl import features as feat
from src.datasvc.nfl.store import NflStore

FACTS_ONLY = ("Facts only. No prediction, no pick. The probabilities in the market block are the market's own, "
              "not an estimate made here.")

# -- the market ------------------------------------------------------------------------------


def _valid_price(price: Any) -> bool:
    """An American price: a number, not a bool, with an absolute value of at least 100."""
    return isinstance(price, (int, float)) and not isinstance(price, bool) and abs(price) >= 100


def implied(price: Any) -> Optional[float]:
    """An American price as a probability, margin included (None for anything that cannot be a price)."""
    if not _valid_price(price):
        return None
    return round(100.0 / (price + 100.0), 4) if price > 0 else round(-price / (-price + 100.0), 4)


def _two_way(a: Any, b: Any, names=("home", "away")) -> dict:
    ia, ib = implied(a), implied(b)
    total = ia + ib if ia is not None and ib is not None else None
    return {names[0]: a if _valid_price(a) else None, names[1]: b if _valid_price(b) else None,
            "implied": {names[0]: ia, names[1]: ib},
            "margin": round(total - 1, 4) if total is not None else None,
            "without_margin": {names[0]: round(ia / total, 4) if total else None,
                               names[1]: round(ib / total, 4) if total else None}}


def market_block(game: dict) -> dict:
    """The schedule file's market for the game, labelled as not as-of: one value per game."""
    line, total = game.get("spread_line"), game.get("total_line")
    has_ml = _valid_price(game.get("home_moneyline")) or _valid_price(game.get("away_moneyline"))
    if line is None and total is None and not has_ml:
        return {"available": False, "as_of_safe": False,
                "reason": "the schedule file has no spread, total or moneyline for this game yet"}
    favourite = None
    if line is not None:
        favourite = "home" if line > 0 else "away" if line < 0 else "pick"
    return {
        "available": True, "as_of_safe": False,
        "note": ("the schedule file's single market value for the game, overwritten as the market moves: the "
                 "closing numbers for a game that is final, the latest numbers at fetched_utc for one not yet "
                 "played. Never an as-of-date price"),
        "source": game.get("source"), "fetched_utc": game.get("fetched_utc"),
        "spread": {"nflverse_spread_line": line, "home": (-line if line is not None else None),
                   "away": (line if line is not None else None), "favourite": favourite,
                   "prices": _two_way(game.get("home_spread_odds"), game.get("away_spread_odds"))},
        "total": {"line": total, "prices": _two_way(game.get("over_odds"), game.get("under_odds"), ("over", "under"))},
        "moneyline": _two_way(game.get("home_moneyline"), game.get("away_moneyline")),
    }


# -- differentials ---------------------------------------------------------------------------

FORM_WINDOWS = {"last_3": 3, "last_5": 5, "season_to_date": 3}
FORM_FIGURES = (
    ("points_for_per_game", "points per game", lambda w: w["points_for_per_game"], lambda w: w["games"]),
    ("points_against_per_game", "points allowed per game", lambda w: w["points_against_per_game"], lambda w: w["games"]),
    ("margin_per_game", "points margin per game", lambda w: w["margin_per_game"], lambda w: w["games"]),
    ("yards_per_play", "net yards per play", lambda w: w["yards_per_play"]["value"], lambda w: w["yards_per_play"]["games"]),
    ("yards_per_play_allowed", "net yards per play allowed", lambda w: w["yards_per_play_allowed"]["value"],
     lambda w: w["yards_per_play_allowed"]["games"]),
    ("turnover_margin", "takeaways - giveaways per game", lambda w: w["turnover_margin"]["value"],
     lambda w: w["turnover_margin"]["games"]),
)


def _diff(unit: str, home, away, home_n=None, away_n=None, minimum: int = 0) -> dict:
    diff = None if home is None or away is None else round(home - away, 4)
    thin = home is None or away is None or (home_n or 0) < minimum or (away_n or 0) < minimum
    return {"unit": unit, "home": home, "away": away, "diff": diff,
            "home_sample": home_n, "away_sample": away_n, "thin_sample": thin}


def differentials(feats: dict) -> Dict[str, dict]:
    """Home minus away for every comparable figure. `thin_sample` is true when either side's
    window holds fewer games than it names (3 for last_3 and season_to_date, 5 for last_5) or
    a side has no value."""
    home, away = feats["home"], feats["away"]
    out: Dict[str, dict] = {}
    for window, minimum in FORM_WINDOWS.items():
        for name, unit, value, games in FORM_FIGURES:
            hw, aw = home["form"][window], away["form"][window]
            out[f"form.{window}.{name}"] = _diff(unit, value(hw), value(aw), games(hw), games(aw), minimum)
    hr, ar = home["rest"], away["rest"]
    out["rest.days_since_last_game"] = _diff("days", hr["days_since_last_game"], ar["days_since_last_game"])
    ht, at = home["travel"], away["travel"]
    out["travel.miles_from_home_base"] = _diff("miles", ht["miles_from_home_base"], at["miles_from_home_base"])
    out["travel.time_zones_crossed"] = _diff("hours", ht["time_zones_crossed"], at["time_zones_crossed"])
    hi, ai = home["injuries"], away["injuries"]
    for key, unit in (("out", "players out"), ("listed", "players on the report")):
        out[f"injuries.{key}"] = _diff(unit, hi["totals"][key] if hi.get("available") else None,
                                       ai["totals"][key] if ai.get("available") else None)
    return out


# -- the sheet -------------------------------------------------------------------------------

def matchup(store: NflStore, game_id: str, as_of: Any = None, *, now: Optional[datetime] = None) -> dict:
    """The fact sheet for one game.

    `as_of` defaults to the game's kickoff and may not be later than it. `now` is accepted for
    symmetry with the UFC sheet and for tests; nothing in the sheet depends on it. Raises
    `features.UnknownGame`, or ValueError for an unreadable or too-late `as_of`.
    """
    feats = feat.game_features(store, game_id, as_of)
    game = store.game_by_id()[game_id]
    market = market_block(game)
    diffs = differentials(feats)
    missing: List[dict] = list(feats["missing"])
    if not market["available"]:
        missing.append({"side": None, "team": None, "figure": "market", "reason": market["reason"]})
    for name, entry in diffs.items():
        if entry["diff"] is None:
            missing.append({"side": None, "team": None, "figure": f"differentials.{name}",
                            "reason": "one or both sides have no value for this figure"})
    return {
        "game": {"game_id": game_id, "season": game["season"], "week": game["week"], "game_type": game.get("game_type"),
                 "status": game.get("status"), "kickoff_utc": game.get("kickoff_utc"),
                 "home_team": game["home_team"], "away_team": game["away_team"],
                 "home_name": feat.team_name(game["home_team"]), "away_name": feat.team_name(game["away_team"]),
                 "stadium_id": game.get("stadium_id"), "stadium": game.get("stadium"),
                 "neutral_site": game.get("neutral_site"), "venue_check": game.get("venue_check")},
        "as_of": feats["as_of"], "as_of_source": feats["as_of_source"],
        "leakage_rule": feats["leakage_rule"], "note": FACTS_ONLY,
        "schedule": feats["schedule"], "conditions": feats["conditions"],
        "home": feats["home"], "away": feats["away"],
        "head_to_head": feats["head_to_head"],
        "market": market,
        "differentials": diffs,
        "missing": missing,
    }


def find_game(store: NflStore, team_a: str, team_b: str, *, season: Optional[int] = None,
              week: Optional[int] = None, now: Optional[datetime] = None) -> dict:
    """The game between two teams (either of them home), for the CLI and the API.

    With `season` and `week` the game of that week. Otherwise the earliest scheduled game that
    has not kicked off yet, else the most recent game between them. Raises UnknownTeam for a team
    not in the store, and LookupError when they never meet in the store's window.
    """
    a, b = feat.resolve_team(store, team_a), feat.resolve_team(store, team_b)
    if a == b:
        raise ValueError("a team does not play itself")
    games = [g for g in store.games_by_team().get(a, ()) if b in (g["home_team"], g["away_team"])
             and g.get("status") != "removed"]
    if season is not None:
        games = [g for g in games if g["season"] == season]
    if week is not None:
        games = [g for g in games if g["week"] == week]
    if not games:
        raise LookupError(f"no game between {a} and {b} in the store" +
                          (f" for season {season}" if season is not None else "") +
                          (f" week {week}" if week is not None else ""))
    now_iso = feat.iso_utc(now or datetime.now(timezone.utc))
    upcoming = [g for g in games if g.get("status") == "scheduled" and (g.get("kickoff_utc") or "") >= now_iso]
    return upcoming[0] if upcoming and season is None and week is None else games[-1]
