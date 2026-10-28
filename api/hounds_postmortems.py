"""The bets spreadsheet and the hindsight reviews (owner ask 2026-10-28).

    GET /hounds/{id}/export?format=csv|xlsx   every bet the hound recorded, as a download (src/hounds/bet_export.py)
    GET /hounds/{id}/postmortems              the hindsight reviews of its settled bets, keyed by bet id (src/ai/postmortems.py)

WHO CAN SEE WHAT. A HOUSE hound (the pack, the AI hounds, The Learner, the desk and the baselines) is public: its bets, reasons and
reviews are open to anyone, like its record page. A MEMBER hound's spreadsheet and reviews are for its OWNER only. The export of a
member hound answers 401 with no sign-in and 403 to anyone else; the reviews route answers 200 with ``visible: false`` and nothing
in it (the record page is public and asks every time, so a visitor simply sees no reviews, not an error).

NO REQUEST WAITS FOR A BUILD. The stats come from the cached book (``common.hound_data``); with none yet the export answers 503
``warming_up`` with a Retry-After, and the reviews route answers an empty, visible payload with ``warming_up: true``.

HINDSIGHT. Every review leaves here labelled ``Hindsight review`` with the note that it was written after the result, never as
pre-game reasoning. Paper only.

MOUNT ORDER. ``/hounds/{id}/export`` has the same shape as the literal ``/hounds/tips/export`` (api/hounds_tips.py), so this router is
mounted AFTER that one in api/app.py (tests/test_postmortems_api.py pins the order).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response

from src.ai import postmortem_parse, postmortems
from src.appstate import ratelimit
from src.hounds import bet_export
from src.hounds.contract import envelope
from src.hounds.interact import common

from api import auth as auth_mod

router = APIRouter()

_NO_STORE = "no-store"
EXPORT_PER_MIN = 12
READ_PER_MIN = 60
_export_limiter = ratelimit.FixedWindowLimiter(limit=EXPORT_PER_MIN, window_s=60.0)
_rl_export = ratelimit.limiter_dependency(_export_limiter)
_read_limiter = ratelimit.FixedWindowLimiter(limit=READ_PER_MIN, window_s=60.0)
_rl_read = ratelimit.limiter_dependency(_read_limiter)

MEDIA = {"csv": "text/csv; charset=utf-8", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
REVIEW_LIMIT = 250                         # the record page lists this many settled tickets; the reviews cover the same ones


def _err(status: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": code, "message": message, **extra})


def _dog(hound_id: str) -> "common.Dog":
    dog = common.resolve(hound_id)
    if dog is None:
        raise _err(404, "not_found", "no such hound")
    return dog


def _viewer_is_owner(dog: "common.Dog", authorization: Optional[str]) -> bool:
    viewer = auth_mod.optional_user_id(authorization)
    return dog.kind == common.KIND_USER and viewer is not None and viewer == dog.owner_user_id


@router.get("/hounds/{hound_id}/export")
def export_bets(hound_id: str, response: Response, format: str = Query("csv", pattern="^(csv|xlsx)$"),
                authorization: Optional[str] = Header(default=None), _rl: None = Depends(_rl_export)):
    dog = _dog(hound_id)
    if dog.kind == common.KIND_USER and not _viewer_is_owner(dog, authorization):
        if auth_mod.optional_user_id(authorization) is None:
            raise _err(401, "sign_in_required", "Sign in to download your hound's spreadsheet.")
        raise _err(403, "owner_only", "Only a hound's owner can download its spreadsheet.")
    if format not in bet_export.available_formats():
        raise _err(422, "format_unavailable", "The Excel format is not switched on here. The CSV opens in Excel and Google Sheets.",
                   available=list(bet_export.available_formats()))
    data = common.hound_data(dog)
    if data is None:
        response.headers["Retry-After"] = "5"
        raise _err(503, "warming_up", "The record is still being worked out. Try again in a few seconds.")
    try:
        engine = postmortems.default_engine()
        reviews = engine.reviews_for_hound(dog.id, 5000)
        queued = engine.queue.pending_keys(dog.id)
    except Exception:  # noqa: BLE001 -- the sheet is complete without reviews; a bad ledger must not stop the download
        reviews, queued = {}, set()
    now = datetime.now(timezone.utc)
    rows = bet_export.build_rows(data.view("all"), reviews=reviews, queued=queued, now=now)
    body = bet_export.to_csv(rows) if format == "csv" else bet_export.to_xlsx(rows)
    if body is None:
        raise _err(422, "format_unavailable", "The Excel format is not switched on here. The CSV opens in Excel and Google Sheets.",
                   available=["csv"])
    name = bet_export.filename(dog.id, format, now.date())
    return Response(content=body, media_type=MEDIA[format],
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": _NO_STORE})


@router.get("/hounds/{hound_id}/postmortems")
def hound_postmortems(hound_id: str, response: Response, authorization: Optional[str] = Header(default=None),
                      _rl: None = Depends(_rl_read)) -> dict:
    response.headers["Cache-Control"] = _NO_STORE
    dog = _dog(hound_id)
    visible = dog.kind != common.KIND_USER or _viewer_is_owner(dog, authorization)
    base = {"hound_id": dog.id, "visible": visible, "label": postmortem_parse.LABEL, "note": postmortem_parse.NOTE,
            "reviews": {}, "pending": 0}
    if not visible:
        return envelope(base)
    try:
        engine = postmortems.default_engine()
        base["reviews"] = engine.reviews_for_hound(dog.id, REVIEW_LIMIT)
        base["pending"] = len(engine.queue.pending_keys(dog.id))
    except Exception:  # noqa: BLE001 -- a page without reviews is a page; a bad ledger must not break the record
        base["warming_up"] = True
    return envelope(base)
