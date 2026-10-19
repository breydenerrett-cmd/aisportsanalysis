"""GET /hounds/kennels and GET /hounds/kennels/{handle}: every member's public dogs, grouped by owner.

    GET /hounds/kennels             members with at least one public dog: handle, label, dog count, best record
    GET /hounds/kennels/{handle}    one member's public dogs (a dog with no bet yet is listed, flagged "new")

Public reads, no auth. The handle is the anonymous owner label ("Handler 3F2A" -> "handler-3f2a"); no email, no
account id and no token is ever in a payload. The logic and the numbers are src/hounds/kennels.py (the
leaderboard's own stats), so this module is wiring.

MOUNT ORDER. ``/hounds/kennels`` is a literal path under ``/hounds/{id}``; this router is mounted BEFORE
api.hounds (api/app.py does, and tests/test_hounds_kennels_api.py pins it).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from src.appstate import ratelimit
from src.appstate import users as users_store
from src.hounds import kennels, seasons
from src.hounds.contract import envelope

from api.auth import get_current_user

router = APIRouter()

_read_limiter = ratelimit.FixedWindowLimiter(limit=120, window_s=60.0)
_rl_read = ratelimit.limiter_dependency(_read_limiter)


def _season(value: Optional[str]) -> str:
    sid = seasons.resolve(value)
    if sid is None:
        raise HTTPException(status_code=422, detail="season must be one of: " + ", ".join(seasons.ids() + [seasons.ALL]))
    return sid


@router.get("/hounds/kennels")
def kennel_index(response: Response, season: Optional[str] = Query(None, max_length=16),
                 _rl: None = Depends(_rl_read)) -> dict:
    response.headers["Cache-Control"] = "public, max-age=30"
    return envelope(kennels.kennel_list(_season(season)))


@router.get("/hounds/kennels/mine")
def my_kennel(response: Response, season: Optional[str] = Query(None, max_length=16),
              current_user: users_store.User = Depends(get_current_user), _rl: None = Depends(_rl_read)) -> dict:
    """The signed-in member's own dogs, retired ones flagged. Declared before {handle} so "mine" is never a handle."""
    response.headers["Cache-Control"] = "no-store"
    return envelope(kennels.my_kennel(current_user.id, _season(season)))


@router.get("/hounds/kennels/{handle}")
def kennel_page(handle: str, response: Response, season: Optional[str] = Query(None, max_length=16),
                _rl: None = Depends(_rl_read)) -> dict:
    out = kennels.kennel_detail(handle[:60], _season(season))
    if out is None:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": "no kennel with that name"})
    response.headers["Cache-Control"] = "public, max-age=30"
    return envelope(out)
