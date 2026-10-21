"""api/hounds_interview.py: "Turn your strategy into a hound". An interview that ends in a paper hound.

    POST /hounds/interview                       start an interview (402 upgrade_required for a free account at its dog limit)
    GET  /hounds/interview/{id}[?edit=topic]     where it stands: the next question, what is still open, the chat so far;
                                                 ?edit opens an answered topic again, prefilled
    POST /hounds/interview/{id}/answer           {topic, fields, texts, data, skip} -> the next step
    POST /hounds/interview/{id}/resolve          {clarification, option} -> the next step
    POST /hounds/interview/{id}/review           {name, tagline} -> the confirmation screen; SAVES NOTHING
    POST /hounds/interview/{id}/confirm          {name, tagline, freeze_hash} -> creates the hound and the strategy record
    GET  /hounds/interview/records/{record_id}   the owner's strategy record, with any claimed history under its own label

Everything needs a signed-in member (a free account too); an interview belongs to its owner and another account's id
reads as 404. Nothing saves until `confirm`, which creates ONE hound through the same store function POST /hounds uses,
so the free account's one-dog limit, the five-dog ceiling, name rules and the Keep email all apply unchanged.

ROUTE ORDER. `/hounds/interview/...` sits next to `/hounds/{id}/...`; api/app.py mounts this router before api.hounds
and next to the other create routers (tests/test_hounds_interview_api.py pins it).

THE ASSISTANT. Haiku (src/ai/router.py, the $5 monthly cap, AI_PAID_CAP_USD) words the questions and proposes candidate
fields. `get_router()` is the one place the router is chosen, so a test replaces it with a fake and nothing here ever
touches the network under test. When the router is capped, cooling down or has no key, the interview carries on as a
plain form (src/hounds/interview/extract.py).

Thin wiring: all logic is src/hounds/interview. Paper only; nothing here places or suggests a real bet.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from src.appstate import ratelimit
from src.appstate import users as users_store
from src.hounds import user_spec, user_store
from src.hounds.interview import service
from src.hounds.interview.machine import InterviewError

from api import auth as auth_mod
from api.auth import get_current_user, require_member_access
from api.hounds_create import _send_keep_email, _spec_error, _store_error

router = APIRouter()

PAPER = {"paper_only": True, "not_advice": user_spec.NOT_ADVICE}

# A person finishes an interview in one sitting: eleven answers, a few corrections. These are far above that and low
# enough to blunt a script that turns the assistant's budget into somebody else's free text box.
START_PER_HOUR = 12
ANSWER_PER_HOUR = 120
READ_PER_MIN = 60
_start_limiter = ratelimit.FixedWindowLimiter(limit=START_PER_HOUR, window_s=3600.0)
_rl_start = ratelimit.limiter_dependency(_start_limiter, user_dependency=get_current_user)
_answer_limiter = ratelimit.FixedWindowLimiter(limit=ANSWER_PER_HOUR, window_s=3600.0)
_rl_answer = ratelimit.limiter_dependency(_answer_limiter, user_dependency=get_current_user)
_read_limiter = ratelimit.FixedWindowLimiter(limit=READ_PER_MIN, window_s=60.0)
_rl_read = ratelimit.limiter_dependency(_read_limiter, user_dependency=get_current_user)

STATUS = {"not_found": 404, "conflict": 409, "closed": 409, "changed": 409, "not_ready": 409, "not_open": 409,
          "unknown_topic": 422, "not_skippable": 422, "bad_option": 422, "bad_effect": 500}


def get_router():
    """The assistant's router, or None (then the interview is the plain form). A router that cannot be built is the
    same as one with no answer: it never stops an interview."""
    try:
        from src.ai.router import default_router
        return default_router()
    except Exception:  # noqa: BLE001
        return None


def _wrap(payload: dict) -> dict:
    out = dict(payload)
    out.update(PAPER)
    return out


def _interview_error(exc: InterviewError) -> HTTPException:
    return HTTPException(status_code=STATUS.get(exc.code, 400), detail={"error": exc.code, "message": str(exc)})


class AnswerRequest(BaseModel):
    topic: str
    fields: Dict[str, Any] = {}
    texts: Dict[str, str] = {}
    data: List[str] = []
    skip: bool = False


class ResolveRequest(BaseModel):
    clarification: str
    option: str


class NameRequest(BaseModel):
    name: str
    tagline: str = ""


class ConfirmRequest(BaseModel):
    name: str
    tagline: str = ""
    freeze_hash: Optional[str] = None


@router.post("/hounds/interview")
def start_interview(current_user: users_store.User = Depends(require_member_access),
                    _rl: None = Depends(_rl_start)) -> dict:
    try:
        return _wrap(service.start(current_user.id, free=auth_mod.is_free_member(current_user)))
    except user_store.StoreError as exc:
        raise _store_error(exc)


@router.get("/hounds/interview/records/{record_id}")
def interview_record(record_id: str, current_user: users_store.User = Depends(get_current_user),
                     _rl: None = Depends(_rl_read)) -> dict:
    try:
        return _wrap(service.record_view(current_user.id, record_id))
    except InterviewError as exc:
        raise _interview_error(exc)


@router.get("/hounds/interview/{interview_id}")
def interview_state(interview_id: str, response: Response, edit: Optional[str] = None,
                    current_user: users_store.User = Depends(get_current_user),
                    _rl: None = Depends(_rl_read)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        return _wrap(service.show(current_user.id, interview_id, edit=edit))
    except InterviewError as exc:
        raise _interview_error(exc)


@router.post("/hounds/interview/{interview_id}/answer")
def interview_answer(interview_id: str, body: AnswerRequest, response: Response,
                     current_user: users_store.User = Depends(require_member_access),
                     _rl: None = Depends(_rl_answer)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        return _wrap(service.answer(current_user.id, interview_id, body.topic,
                                    {"fields": body.fields, "texts": body.texts, "data": body.data, "skip": body.skip},
                                    router=get_router()))
    except InterviewError as exc:
        raise _interview_error(exc)


@router.post("/hounds/interview/{interview_id}/resolve")
def interview_resolve(interview_id: str, body: ResolveRequest, response: Response,
                      current_user: users_store.User = Depends(require_member_access),
                      _rl: None = Depends(_rl_answer)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        return _wrap(service.resolve(current_user.id, interview_id, body.clarification, body.option))
    except InterviewError as exc:
        raise _interview_error(exc)


@router.post("/hounds/interview/{interview_id}/review")
def interview_review(interview_id: str, body: NameRequest, response: Response,
                     current_user: users_store.User = Depends(require_member_access),
                     _rl: None = Depends(_rl_answer)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        return _wrap(service.review(current_user.id, interview_id, body.name, body.tagline))
    except InterviewError as exc:
        raise _interview_error(exc)
    except user_spec.SpecError as exc:
        raise _spec_error(exc)


@router.post("/hounds/interview/{interview_id}/confirm")
def interview_confirm(interview_id: str, body: ConfirmRequest, response: Response,
                      current_user: users_store.User = Depends(require_member_access),
                      _rl: None = Depends(_rl_start)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        out = service.confirm(current_user.id, interview_id, body.name, tagline=body.tagline, freeze_hash=body.freeze_hash,
                              free=auth_mod.is_free_member(current_user))
    except InterviewError as exc:
        raise _interview_error(exc)
    except user_spec.SpecError as exc:
        raise _spec_error(exc)
    except user_store.StoreError as exc:
        raise _store_error(exc)
    hound = out.get("hound")
    if hound is not None and not out.get("already"):
        _send_keep_email(current_user, hound)
    if hound is not None:
        from api.hounds_create import hound_summary
        out["hound"] = hound_summary(hound)
    else:
        found = user_store.get_hound(out["hound_id"])
        if found is not None:
            from api.hounds_create import hound_summary
            out["hound"] = hound_summary(found)
    return _wrap(out)
