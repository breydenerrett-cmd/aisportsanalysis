"""GET /hounds/live and GET /hounds/live/status: where a ticket's game stands right now (src/hounds/live_settle.py).

    GET /hounds/live?ids=<event id>,<event id>   per game: upcoming | live (the score) | final | postponed | cancelled
    GET /hounds/live/status                      is the loop on, when it last ran and last graded, how many games are
                                                 waiting on a final (the "Grading" indicator)

Public reads, no auth, nothing private: a game's state and score are public facts, keyed by the event id a ticket already
carries (``event_id`` on a bet row). An id the cache does not hold is simply absent, and the page then says nothing about
that ticket rather than guess. At most 60 ids a call, each 1 to 64 safe characters.

CACHING. ``max-age=15``: a 5-minute loop writes these, so a longer public cache would be older than the data it caches.
The record and bankroll are NOT read here; they come from the stats book, which the loop rebuilds the moment it grades.

MOUNT ORDER. ``/hounds/live`` is a literal path under ``/hounds/{id}``; api/app.py mounts this router BEFORE api.hounds.
"""

from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from src.appstate import ratelimit
from src.hounds import live_settle
from src.hounds.contract import envelope

router = APIRouter()

MAX_IDS = 60
_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_CACHE = "public, max-age=15"

_read_limiter = ratelimit.FixedWindowLimiter(limit=240, window_s=60.0)
_rl_read = ratelimit.limiter_dependency(_read_limiter)


@router.get("/hounds/live")
def live_games(response: Response, ids: Optional[str] = Query(None, max_length=4400), _rl: None = Depends(_rl_read)) -> dict:
    wanted = [part.strip() for part in (ids or "").split(",") if part.strip()]
    if len(wanted) > MAX_IDS:
        raise HTTPException(status_code=422, detail=f"ask for at most {MAX_IDS} games at a time")
    if any(not _ID.match(w) for w in wanted):
        raise HTTPException(status_code=422, detail="a game id is 1 to 64 letters, digits, dashes or underscores")
    response.headers["Cache-Control"] = _CACHE
    return envelope({"games": live_settle.game_states(wanted) if wanted else {}})


@router.get("/hounds/live/status")
def live_status(response: Response, _rl: None = Depends(_rl_read)) -> dict:
    response.headers["Cache-Control"] = _CACHE
    return envelope(live_settle.status())
