"""The signed-in member's one-time announcements (src/appstate/announcements.py).

    GET  /me/announcements             the caller's unseen announcements, oldest first: [{id, kind, title, steps, created_utc}]
    POST /me/announcements/{id}/seen   mark one seen (idempotent); someone else's id reads as not found

Read at every page load by web/js/announcements.js. Nothing creates an announcement over HTTP: the owner does, from the CLI.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from src.appstate import announcements as store
from src.appstate import ratelimit
from src.appstate import users as users_store
from src.hounds.contract import envelope

from api.auth import get_current_user

router = APIRouter()

_rl_read = ratelimit.limiter_dependency(ratelimit.FixedWindowLimiter(limit=240, window_s=60.0),
                                        user_dependency=get_current_user)
_rl_write = ratelimit.limiter_dependency(ratelimit.FixedWindowLimiter(limit=60, window_s=3600.0),
                                         user_dependency=get_current_user)


def _public(row: dict) -> dict:
    return {k: row[k] for k in ("id", "kind", "title", "steps", "created_utc")}


@router.get("/me/announcements")
def my_announcements(response: Response, current_user: users_store.User = Depends(get_current_user),
                     _rl: None = Depends(_rl_read)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return envelope({"announcements": [_public(r) for r in store.unseen(current_user.id)]})


@router.post("/me/announcements/{announcement_id}/seen")
def announcement_seen(announcement_id: str, response: Response,
                      current_user: users_store.User = Depends(get_current_user),
                      _rl: None = Depends(_rl_write)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        row = store.mark_seen(current_user.id, announcement_id)
    except store.AnnouncementError as exc:
        raise HTTPException(status_code=exc.status, detail={"error": exc.code, "message": str(exc)})
    return envelope({"id": row["id"], "seen_utc": row["seen_utc"]})
