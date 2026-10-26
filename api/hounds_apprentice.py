"""The Apprentice hound's lessons (src/hounds/apprentice): the owner's real bets, their screenshots, grading and patterns.

    GET  /hounds/{id}/apprentice                       the owner's lessons with their states, and the analytics
    GET  /hounds/{id}/apprentice/board                 the games on the board to pick a lesson's game from
    POST /hounds/{id}/apprentice/lessons               log a bet by hand: {legs, stake, book, placed_at, ticket_id?, state?}
    POST /hounds/{id}/apprentice/lessons/{lid}/state   append a state change: {state, result?, cash_out_amount?, resolution?}
    POST /hounds/{id}/apprentice/import                {image_b64, utc_offset_minutes}: a screenshot -> a DRAFT (nothing filed)
    POST /hounds/{id}/apprentice/import/confirm        {image_hash, lesson, acknowledged, lesson_id?}: file the confirmed draft
    GET  /hounds/{id}/apprentice/evidence/{eid}        the owner's own screenshot
    GET  /hounds/{id}/apprentice/proposal              read only: the paper rules its lessons suggest
    POST /hounds/{id}/apprentice/apply                 {basis, as_of, confirm: true}: make the proposal a new version

OWNER ONLY, and only for an Apprentice hound: anyone else, and any other hound, reads as not found. There is no route that
edits or deletes a lesson, because there is no such operation (the database refuses it too). Nothing here places a bet.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from src.appstate import ratelimit
from src.appstate import users as users_store
from src.hounds.apprentice import board, service, store
from src.hounds.contract import envelope
from src.hounds.interact import common

from api.auth import get_current_user

router = APIRouter()
_NO_STORE = "no-store"

_read = ratelimit.limiter_dependency(ratelimit.FixedWindowLimiter(limit=120, window_s=60.0))
_write = ratelimit.limiter_dependency(ratelimit.FixedWindowLimiter(limit=120, window_s=3600.0), user_dependency=get_current_user)
# a screenshot import is the one call that can cost money (Haiku vision under the $5 cap)
IMPORTS_PER_HOUR = 20
_import = ratelimit.limiter_dependency(ratelimit.FixedWindowLimiter(limit=IMPORTS_PER_HOUR, window_s=3600.0),
                                       user_dependency=get_current_user)


def _err(exc: service.ServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"error": exc.code, "message": str(exc), **exc.extra})


def _hound(hound_id: str, user: users_store.User) -> dict:
    dog = common.resolve(hound_id)
    try:
        return dict(service.check_owner(dog.hound if dog is not None and dog.kind == common.KIND_USER else None, user.id))
    except service.ServiceError as exc:
        raise _err(exc)


def _router():
    from src.ai import router as ai_router
    return ai_router.default_router()


class LessonBody(BaseModel):
    legs: List[Dict[str, Any]]
    stake: Any = None
    book: Optional[str] = None
    placed_at: Optional[str] = None
    ticket_id: Optional[str] = None
    total_price: Any = None
    payout: Any = None
    state: Optional[Dict[str, Any]] = None
    owner: Optional[str] = None                 # Brey / Jacob / unknown (default unknown)
    recommendation_id: Optional[str] = None


class StateBody(BaseModel):
    state: str
    result: Optional[str] = None
    cash_out_amount: Optional[float] = None
    resolution: Optional[bool] = None
    settlement_time: Optional[str] = None


class ImportBody(BaseModel):
    image_b64: str
    utc_offset_minutes: Optional[int] = None


class ConfirmBody(BaseModel):
    image_hash: str
    lesson: Dict[str, Any]
    acknowledged: List[str] = []
    lesson_id: Optional[str] = None


class ApplyBody(BaseModel):
    basis: str
    as_of: str
    confirm: bool = False


@router.get("/hounds/{hound_id}/apprentice")
def apprentice(hound_id: str, response: Response, current_user: users_store.User = Depends(get_current_user),
               _rl: None = Depends(_read)) -> dict:
    response.headers["Cache-Control"] = _NO_STORE
    try:
        return envelope(service.overview(_hound(hound_id, current_user), current_user.id))
    except service.ServiceError as exc:
        raise _err(exc)


@router.get("/hounds/{hound_id}/apprentice/board")
def apprentice_board(hound_id: str, response: Response, current_user: users_store.User = Depends(get_current_user),
                     _rl: None = Depends(_read)) -> dict:
    response.headers["Cache-Control"] = _NO_STORE
    _hound(hound_id, current_user)
    return envelope({"games": board.board_games()})


@router.post("/hounds/{hound_id}/apprentice/lessons")
def add_lesson(hound_id: str, body: LessonBody, response: Response,
               current_user: users_store.User = Depends(get_current_user), _rl: None = Depends(_write)) -> dict:
    response.headers["Cache-Control"] = _NO_STORE
    try:
        return envelope({"lesson": service.add_manual(_hound(hound_id, current_user), current_user.id, body.model_dump())})
    except service.ServiceError as exc:
        raise _err(exc)


@router.post("/hounds/{hound_id}/apprentice/lessons/{lesson_id}/state")
def lesson_state(hound_id: str, lesson_id: str, body: StateBody, response: Response,
                 current_user: users_store.User = Depends(get_current_user), _rl: None = Depends(_write)) -> dict:
    response.headers["Cache-Control"] = _NO_STORE
    data = {"result": body.result, "cash_out_amount": body.cash_out_amount, "resolution": body.resolution,
            "settlement_time": body.settlement_time}
    try:
        return envelope(service.set_state(_hound(hound_id, current_user), current_user.id, lesson_id, body.state,
                                          {k: v for k, v in data.items() if v is not None}))
    except service.ServiceError as exc:
        raise _err(exc)


@router.post("/hounds/{hound_id}/apprentice/import")
def import_screenshot(hound_id: str, body: ImportBody, response: Response,
                      current_user: users_store.User = Depends(get_current_user), _rl: None = Depends(_import)) -> dict:
    response.headers["Cache-Control"] = _NO_STORE
    try:
        hound = _hound(hound_id, current_user)
        data = service.decode_image(body.image_b64)
        return envelope(service.import_screenshot(hound, current_user.id, data, _router(),
                                                  utc_offset_minutes=body.utc_offset_minutes))
    except service.ServiceError as exc:
        raise _err(exc)


@router.post("/hounds/{hound_id}/apprentice/import/confirm")
def import_confirm(hound_id: str, body: ConfirmBody, response: Response,
                   current_user: users_store.User = Depends(get_current_user), _rl: None = Depends(_write)) -> dict:
    response.headers["Cache-Control"] = _NO_STORE
    try:
        return envelope(service.confirm_import(_hound(hound_id, current_user), current_user.id, body.image_hash, body.lesson,
                                               acknowledged=body.acknowledged, lesson_id=body.lesson_id))
    except service.ServiceError as exc:
        raise _err(exc)


@router.get("/hounds/{hound_id}/apprentice/evidence/{evidence_id}")
def evidence(hound_id: str, evidence_id: str, current_user: users_store.User = Depends(get_current_user),
             _rl: None = Depends(_read)) -> Response:
    _hound(hound_id, current_user)
    found = store.evidence_file(evidence_id, current_user.id)
    if found is None:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": "no such screenshot"})
    path, media = found
    return Response(content=path.read_bytes(), media_type=media,
                    headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/hounds/{hound_id}/apprentice/proposal")
def apprentice_proposal(hound_id: str, response: Response, current_user: users_store.User = Depends(get_current_user),
                        _rl: None = Depends(_read)) -> dict:
    response.headers["Cache-Control"] = _NO_STORE
    try:
        return envelope(service.proposal(_hound(hound_id, current_user), current_user.id))
    except service.ServiceError as exc:
        raise _err(exc)


@router.post("/hounds/{hound_id}/apprentice/apply")
def apprentice_apply(hound_id: str, body: ApplyBody, response: Response,
                     current_user: users_store.User = Depends(get_current_user), _rl: None = Depends(_write)) -> dict:
    response.headers["Cache-Control"] = _NO_STORE
    if not body.confirm:
        raise HTTPException(status_code=422, detail={"error": "confirm_required",
                                                     "message": "Look at the proposal, then confirm it. Nothing was changed."})
    try:
        out = service.apply_proposal(_hound(hound_id, current_user), current_user.id, body.basis, body.as_of)
    except service.ServiceError as exc:
        raise _err(exc)
    return envelope({"hound_id": out["hound"]["id"], "version_no": out["hound"]["version_no"], "changes": out["changes"],
                     "paper_only": True})
