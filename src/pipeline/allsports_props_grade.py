"""Grade a captured player prop against a box score from the in-house data service.

    grade_prop(row, box) -> {"status": "win" | "loss" | "push" | "void" | "unresolved", "actual", "line", ...}

`row` is one row of `data/processed/allsports_props.jsonl` (`allsports_props.project`): `market`, `player`, `side`
(Over / Under, or Yes / No for an anytime scorer), `line` (a string, None for Yes / No markets) and `sport`.

`box` is a finished game as the data service holds it:

 * NBA, NHL and NCAAF football (the ESPN-fed leagues): `DataClient().league("nba").game(game_id)` (the whole answer
   or its `data`): `{"game": {...}, "team_games": [...], "player_games": [...]}`. Player rows carry `stats`
   `{group: {key: display string}}`, `player_name`, `did_not_play`.
 * NFL (nflverse): `{"game": {...}, "player_games": [rows of src/datasvc/nfl/store.py]}`, the rows
   `nfl_player_games(store, game_id=...)` returns. A nflverse row means "has a stat line".

THE RULES (each one is a test)
------------------------------
 * A player who did not play is a VOID (the book refunds the leg): a box row marked did-not-play, a row with no
   minutes or no time on ice, or, in a league whose box lists every dressed player, a player the box does not list.
 * It is never a guess. A game that is not final, a box with no player lines, a name that does not fit exactly one
   player (`names.person_score`; "Nic" is not "Nicolas"), a near-miss name, a market the box cannot answer
   (first basket, power-play points) or a stat the box does not carry is `unresolved`, with the reason. Only the
   absence of any near name in a box that lists every dressed player is read as "did not play".
 * nflverse lists only players with a stat line, so there a missing player is `unresolved`, not a void or a zero.
 * A postponed or cancelled game voids every leg.
 * Over / Under: the stat against the line (a level stat is a PUSH). Yes: the stat is at least one (two for a
   double-double, three for a triple-double). No: it is zero.
 * Anytime TD counts rushing and receiving touchdowns, as the stored nflverse rows carry them; a kick-return or
   defensive touchdown is not in the file, so the result says so in `note`.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from src.datasvc import names

WIN, LOSS, PUSH, VOID, UNRESOLVED = "win", "loss", "push", "void", "unresolved"

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
_VOID_STATUS_WORDS = ("POSTPONED", "CANCELED", "CANCELLED")


# -- numbers ------------------------------------------------------------------------------------------------------

def _num(value) -> Optional[float]:
    """A count from ESPN's display string ("22", "+6", "0") or a number; None for anything else."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lstrip("+")
    try:
        return float(text)
    except ValueError:
        return None


def _made(value) -> Optional[float]:
    """The made half of a "made-attempted" display string ("3-5" -> 3)."""
    if value is None:
        return None
    return _num(str(value).split("-")[0])


def _clock_seconds(value) -> Optional[float]:
    """"14:22" -> 862; "33" (NBA minutes) -> 33 * 60."""
    if value is None:
        return None
    text = str(value).strip()
    if ":" in text:
        minutes, _, seconds = text.partition(":")
        m, s = _num(minutes), _num(seconds)
        return None if m is None or s is None else m * 60 + s
    minutes = _num(text)
    return None if minutes is None else minutes * 60


def _total(*parts: Optional[float]) -> Optional[float]:
    return None if any(p is None for p in parts) else float(sum(parts))


# -- the stats of a player, per market ----------------------------------------------------------------------------

def _nba(m: dict) -> Dict[str, Optional[float]]:
    pts, reb, ast = _num(m.get("points")), _num(m.get("rebounds")), _num(m.get("assists"))
    stl, blk, tov = _num(m.get("steals")), _num(m.get("blocks")), _num(m.get("turnovers"))
    threes = _made(m.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted"))
    cats = [c for c in (pts, reb, ast, stl, blk) if c is not None]
    double = float(sum(1 for c in cats if c >= 10)) if len(cats) == 5 else None
    return {"player_points": pts, "player_rebounds": reb, "player_assists": ast, "player_threes": threes,
            "player_steals": stl, "player_blocks": blk, "player_turnovers": tov,
            "player_points_rebounds_assists": _total(pts, reb, ast), "player_points_rebounds": _total(pts, reb),
            "player_points_assists": _total(pts, ast), "player_rebounds_assists": _total(reb, ast),
            "player_blocks_steals": _total(blk, stl),
            "player_double_double": None if double is None else float(double >= 2),
            "player_triple_double": None if double is None else float(double >= 3)}


def _nhl(m: dict) -> Dict[str, Optional[float]]:
    goals, assists = _num(m.get("goals")), _num(m.get("assists"))
    return {"player_goals": goals, "player_assists": assists, "player_points": _total(goals, assists),
            "player_shots_on_goal": _num(m.get("shotsTotal")), "player_blocked_shots": _num(m.get("blockedShots")),
            "player_total_saves": _num(m.get("saves")), "player_goal_scorer_anytime": goals}


def _espn_football(m: dict) -> Dict[str, Optional[float]]:
    comp = str(m.get("completions/passingAttempts") or "")
    completions, _, attempts = comp.partition("/")
    rush_td, rec_td = _num(m.get("rushingTouchdowns")), _num(m.get("receivingTouchdowns"))
    rush_yds, rec_yds = _num(m.get("rushingYards")), _num(m.get("receivingYards"))
    return {"player_pass_yds": _num(m.get("passingYards")), "player_pass_tds": _num(m.get("passingTouchdowns")),
            "player_pass_completions": _num(completions), "player_pass_attempts": _num(attempts),
            "player_pass_interceptions": _num(m.get("interceptions")), "player_rush_yds": rush_yds,
            "player_rush_attempts": _num(m.get("rushingAttempts")), "player_receptions": _num(m.get("receptions")),
            "player_reception_yds": rec_yds, "player_rush_reception_yds": _total(rush_yds, rec_yds),
            "player_anytime_td": _total(rush_td, rec_td)}


def _nflverse(r: dict) -> Dict[str, Optional[float]]:
    rush_td, rec_td = _num(r.get("rushing_tds")), _num(r.get("receiving_tds"))
    rush_yds, rec_yds = _num(r.get("rushing_yards")), _num(r.get("receiving_yards"))
    return {"player_pass_yds": _num(r.get("passing_yards")), "player_pass_tds": _num(r.get("passing_tds")),
            "player_pass_completions": _num(r.get("completions")), "player_pass_attempts": _num(r.get("pass_attempts")),
            "player_pass_interceptions": _num(r.get("interceptions")), "player_rush_yds": rush_yds,
            "player_rush_attempts": _num(r.get("carries")), "player_receptions": _num(r.get("receptions")),
            "player_reception_yds": rec_yds, "player_rush_reception_yds": _total(rush_yds, rec_yds),
            "player_anytime_td": _total(rush_td, rec_td)}


#: markets with no point: Yes / No. Everything else is Over / Under against a line.
YES_NO_MARKETS = {"player_anytime_td": 1.0, "player_goal_scorer_anytime": 1.0,
                  "player_double_double": 1.0, "player_triple_double": 1.0}


class _Player:
    """One player of the box, whatever source it came from: name, whether he played, and the stats by market."""

    def __init__(self, name: str, played: Optional[bool], stats: Dict[str, Optional[float]], row: dict):
        self.name, self.played, self.stats, self.row = name, played, stats, row


def _espn_player(row: dict, sport: str) -> _Player:
    groups = row.get("stats") or {}
    merged: dict = {}
    for group in groups.values():
        if isinstance(group, dict):
            merged.update(group)
    seconds = _clock_seconds(merged.get("minutes") if sport == "nba" else merged.get("timeOnIce"))
    if row.get("did_not_play"):
        played: Optional[bool] = False
    elif seconds is not None:
        played = seconds > 0
    elif sport in ("nba", "nhl"):
        played = bool(merged)              # the league's box lists every dressed player: no stats, no minutes
    else:
        played = True if merged else None  # a football box lists a player once he has a stat
    stats = _nba(merged) if sport == "nba" else _nhl(merged) if sport == "nhl" else _espn_football(merged)
    return _Player(str(row.get("player_name") or ""), played, stats, row)


def _nfl_player(row: dict) -> _Player:
    return _Player(str(row.get("name") or row.get("player_name") or ""), True, _nflverse(row), row)


# -- the box --------------------------------------------------------------------------------------------------------

def _unwrap(box) -> dict:
    """The `data` of a data-service answer, or the dict itself; {} when there is nothing to read."""
    if not isinstance(box, dict):
        return {}
    if "available" in box:
        return (box.get("data") or {}) if box.get("available") else {}
    return box


def _is_espn_row(row: dict) -> bool:
    return isinstance(row.get("stats"), dict)


def _players(data: dict, sport: str) -> List[_Player]:
    out = []
    for row in data.get("player_games") or []:
        if not isinstance(row, dict):
            continue
        out.append(_espn_player(row, sport) if _is_espn_row(row) else _nfl_player(row))
    return out


def _game_final(game: dict) -> Optional[bool]:
    if not isinstance(game, dict) or not game:
        return None
    if game.get("completed") is True or str(game.get("state") or "").lower() == "post":
        return True
    if str(game.get("status") or "").lower() in ("final", "completed", "post", "complete"):
        return True
    return False


# -- names ----------------------------------------------------------------------------------------------------------

def _surname_and_initial(name: str):
    toks = [t for t in names.tokens(name) if t not in _SUFFIXES]
    return (toks[-1], toks[0][:1]) if len(toks) >= 2 else (toks[-1] if toks else "", "")


def _find_player(wanted: str, players: List[_Player]) -> tuple:
    """(player | None, reason | None, near names). Exactly one exact-enough match, else why not."""
    fits = [p for p in players if names.person_score(wanted, p.name) >= names.PERSON_MIN]
    if len(fits) == 1:
        return fits[0], None, []
    if len(fits) > 1:
        return None, "ambiguous: the name fits " + ", ".join(sorted(p.name for p in fits)), [p.name for p in fits]
    surname, initial = _surname_and_initial(wanted)
    near = sorted(p.name for p in players
                  if surname and _surname_and_initial(p.name)[0] == surname
                  and (not initial or _surname_and_initial(p.name)[1] in ("", initial)))
    return None, None, near


# -- the grade ------------------------------------------------------------------------------------------------------

def _result(status: str, row: dict, reason: str, *, actual=None, line=None, player: Optional[_Player] = None,
            note: Optional[str] = None) -> dict:
    out = {"status": status, "reason": reason, "actual": actual, "line": line, "market": row.get("market"),
           "side": row.get("side"), "player": row.get("player"),
           "matched": None if player is None else {"name": player.name, "player_id": player.row.get("player_id"),
                                                   "team_id": player.row.get("team_id") or player.row.get("team")}}
    if note:
        out["note"] = note
    return out


def grade_prop(row: dict, box) -> dict:
    """Grade one prop row against one finished game's box score. See the module docstring for every rule."""
    market = str(row.get("market") or "")
    sport = str(row.get("sport") or "").lower()
    side = str(row.get("side") or "").strip().lower()
    if side not in ("over", "under", "yes", "no"):
        return _result(UNRESOLVED, row, f"unknown side {row.get('side')!r}")
    data = _unwrap(box)
    if not data:
        return _result(UNRESOLVED, row, "no box score")
    game = data.get("game") or {}
    status_name = str(game.get("status") or "").upper()
    if any(word in status_name for word in _VOID_STATUS_WORDS):
        return _result(VOID, row, f"game {status_name.lower()}")
    final = _game_final(game)
    if final is None:
        return _result(UNRESOLVED, row, "the box has no game record, so it cannot be shown final")
    if not final:
        return _result(UNRESOLVED, row, "game not final")
    if sport not in ("nba", "nhl", "nfl", "ncaaf"):
        return _result(UNRESOLVED, row, f"no grader for sport {row.get('sport')!r}")
    players = _players(data, "nba" if sport == "nba" else "nhl" if sport == "nhl" else "football")
    if not players:
        return _result(UNRESOLVED, row, "the box carries no player lines "
                                        "(college leagues keep team totals only unless player lines are enabled)")
    listed_everyone = sport in ("nba", "nhl") and all(_is_espn_row(p.row) for p in players)

    player, why, near = _find_player(str(row.get("player") or ""), players)
    if why:
        return _result(UNRESOLVED, row, why)
    if player is None:
        if listed_everyone and not near:
            return _result(VOID, row, "player is not in the box score: he did not play")
        hint = f" (near: {', '.join(near)})" if near else ""
        return _result(UNRESOLVED, row, "player not found in the box score" + hint)
    if player.played is False:
        return _result(VOID, row, "player did not play", player=player)
    if player.played is None:
        return _result(UNRESOLVED, row, "cannot tell whether the player played", player=player)

    if market not in player.stats or player.stats[market] is None:
        return _result(UNRESOLVED, row, f"the box cannot answer market {market!r}", player=player)
    actual = player.stats[market]
    note = ("anytime TD counts rushing and receiving touchdowns; return and defensive touchdowns are not in the "
            "stored file") if (market == "player_anytime_td" and sport == "nfl") else None

    if market in YES_NO_MARKETS:
        if side in ("over", "under"):
            return _result(UNRESOLVED, row, f"{market} is a Yes / No market, got side {row.get('side')!r}",
                           actual=actual, player=player)
        hit = actual >= YES_NO_MARKETS[market]
        won = hit if side == "yes" else not hit
        return _result(WIN if won else LOSS, row, "scored" if hit else "did not score", actual=actual,
                       player=player, note=note)

    if side in ("yes", "no"):
        return _result(UNRESOLVED, row, f"{market} is an Over / Under market, got side {row.get('side')!r}",
                       actual=actual, player=player)
    line = _num(row.get("line"))
    if line is None:
        return _result(UNRESOLVED, row, "the row has no numeric line", actual=actual, player=player)
    if actual == line:
        return _result(PUSH, row, f"{actual:g} equals the line", actual=actual, line=line, player=player)
    over = actual > line
    won = over if side == "over" else not over
    return _result(WIN if won else LOSS, row, f"{actual:g} against {line:g}", actual=actual, line=line,
                   player=player, note=note)


def grade_rows(rows, boxes: Callable[[dict], object]) -> List[dict]:
    """grade_prop over many rows; `boxes(row)` returns the box for a row (None when it has none yet)."""
    out = []
    for row in rows:
        box = boxes(row)
        out.append(grade_prop(row, box) if box is not None else _result(UNRESOLVED, row, "no box score yet"))
    return out
