"""Live game state for NHL and tennis, kept fresh in-process from free feeds, logged, and shown on the site.

WHY THIS EXISTS (live hounds, phase L1, 2026-10-29)
----------------------------------------------------
The live hounds of the next phases bet and pass on what is happening IN a game: a power play, an empty net, who is in goal,
who has the points; in tennis who is serving and who is up a break. This phase builds only the ground floor: a fresh,
honest, free state per live game, a log of how it changed, and one line of it on the site. No bet, no rule change, no Odds
API call, no credit.

    nhl.py     NHL Stats API (api-web.nhle.com): the day's score read every 30 s, boxscore + play-by-play of each live game
               at most every 60 s: strength, empty net, goalie in net with tonight's save %, skaters, goals by period
    tennis.py  ESPN ATP/WTA scoreboards: sets, games, the server, and NET BREAKS in the current set (a pure, exhaustively
               tested function)
    store.py   the cache, the 180 second stale guard, the append-only snapshot log (live_state/YYYY-MM-DD.jsonl beside the
               hounds ledger on the volume)
    names.py   our odds feed's names -> the vendor's names, with the grader's strictness
    lines.py   the one line a game card and an open ticket print
    loop.py    the daemon thread (api/app.py starts it); LIVE_STATE=off disables it; never starts under pytest

THE LOOKUP THE LATER PHASES CALL
--------------------------------
``state_for(sport, home_name, away_name, commence_utc)`` returns the live state dict of THE game those names and that start
fit, or None. None is the answer to every doubt: no game fits, two fit, the names are in the other orientation (NHL), the
cache is older than ``STALE_AFTER_SECONDS``, or the feed is off. Fields inside the dict follow the same rule: an unknown or
contradictory value is None, never a guess (see nhl.py and tennis.py for each field's rule).
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Mapping, Optional

from src.hounds import live_scores as ls
from src.sports.live_state import lines, loop, names, nhl, store, tennis
from src.sports.live_state.loop import enabled, run_pass, start_loop
from src.sports.live_state.store import STALE_AFTER_SECONDS, STATUS, clear

__all__ = ["state_for", "public_view", "status", "enabled", "run_pass", "start_loop", "clear", "STATUS",
           "STALE_AFTER_SECONDS", "SPORTS"]

SPORTS = ("NHL", "TENNIS")


def _sport_code(sport) -> Optional[str]:
    text = str(sport or "").strip().upper()
    if text in ("NHL", "ICEHOCKEY_NHL"):
        return "NHL"
    if text == "TENNIS" or text.startswith("TENNIS_"):
        return "TENNIS"
    return None


def state_for(sport, home_name, away_name, commence_utc, *, now: Optional[datetime] = None) -> Optional[dict]:
    """The live state of the one game these names and start fit, or None (see the module docstring).

    `sport` is a family code ("NHL", "TENNIS") or an Odds API sport key ("icehockey_nhl", "tennis_atp_basel"); `commence_utc`
    a datetime or an ISO string. The dict is a copy: it may be modified. It carries a ``line`` (the one-line text, None
    when the game is not live) and, for tennis, ``home`` / ``away`` laid out in the CALLER's order."""
    code = _sport_code(sport)
    commence = ls.parse_utc(commence_utc)
    if code is None or commence is None or not home_name or not away_name:
        return None
    moment = now or datetime.now(timezone.utc)
    games = store.fresh_games(code, moment)
    if not games:
        return None
    found = (nhl.match if code == "NHL" else tennis.match)(str(home_name), str(away_name), commence, games)
    if found is None:
        return None
    found = copy.deepcopy(found)                   # the cache's own lists and dicts are never handed out
    found["line"] = lines.line_for(found)
    return found


def public_view(state: Optional[Mapping]) -> Optional[dict]:
    """The small block a payload carries for a LIVE game: its one line and when it was read. None when there is no line."""
    if not state or state.get("state") != "live" or not state.get("line"):
        return None
    return {"line": state["line"], "sport": state.get("sport"), "as_of": state.get("as_of")}


def status(now: Optional[datetime] = None) -> dict:
    """What /health shows: is it on, when it last passed, its last error, how many games it holds, how many log lines it wrote."""
    moment = now or datetime.now(timezone.utc)
    out = dict(store.STATUS)
    out["games"] = store.summary(moment)
    out["stale_after_seconds"] = int(STALE_AFTER_SECONDS)
    return out
