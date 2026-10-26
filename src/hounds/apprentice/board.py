"""The games on the board a member can pick a lesson's game from (and that a screenshot's legs are matched against).

Read only, from the same stored slates the hounds read (``ask_eval.default_slate``, cached a minute). The SERVER keeps
its own copy of who plays when: a lesson names an event id and this module fills in the sport, the teams, the start and the
slate date, so a client can never make a game up and have it graded as real (a game the board does not hold is typed
text, graded only from the ticket's own status).
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from src.hounds import user_spec
from src.hounds.apprentice import model

MAX_GAMES = 400


def board_games(now: Optional[datetime] = None, *, slate_for: Optional[Callable] = None) -> list:
    """[{event_id, sport, away_team, home_team, commence_utc, slate_date}] for today and the days ahead, soonest first.
    A slate that cannot be read is skipped (an empty board is honest: the member types the game)."""
    from src.hounds.interact import ask_eval, common, fire
    now = now or common.now_utc()
    slate_for = slate_for or ask_eval.default_slate
    out: dict = {}
    for date in fire.horizon_dates(user_spec.SPORTS, now):
        try:
            games = slate_for(date, False).games
        except Exception:  # noqa: BLE001
            continue
        for event_id, g in games.items():
            if g.commence is None or not g.home_team or not g.away_team:
                continue
            out.setdefault(event_id, {"event_id": str(event_id), "sport": g.sport, "away_team": g.away_team,
                                      "home_team": g.home_team, "commence_utc": model.iso(g.commence), "slate_date": date})
    return sorted(out.values(), key=lambda r: (r["commence_utc"], r["event_id"]))[:MAX_GAMES]


def pin_legs(legs: list, games: list) -> list:
    """For each leg that names an ``event_id``, overwrite the identity fields from the board (the client's copy is never
    trusted). An event id the board does not hold is dropped, so the leg is plain typed text."""
    by_id = {g["event_id"]: g for g in games}
    out = []
    for leg in legs:
        leg = dict(leg)
        eid = str(leg.get("event_id") or "")
        g = by_id.get(eid)
        for key in ("event_id", "away_team", "home_team", "commence_time", "slate_date", "game_pk"):
            leg.pop(key, None)
        if g is not None:
            leg.update({"event_id": g["event_id"], "sport": g["sport"], "away_team": g["away_team"],
                        "home_team": g["home_team"], "commence_time": g["commence_utc"], "slate_date": g["slate_date"]})
            leg["game"] = leg.get("game") or f"{g['away_team']} @ {g['home_team']}"
        out.append(leg)
    return out
