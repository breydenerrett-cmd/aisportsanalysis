"""Talk to your hound: the routes (wiring only; every rule lives in ``src/hounds/chat``, which imports no FastAPI).

    GET    /hounds/{id}/chat                                  the owner: the saved conversation, today's allowance, and whether the hound
                                                              can answer right now (a key on the server, the shared spend meter)
    POST   /hounds/{id}/chat                                  the owner, {"message": "..."}: one message answered by Claude Haiku 5.5, as
                                                              the hound, from its own data. A proposed change comes back as a card
    POST   /hounds/{id}/chat/proposals/{message}/apply        the owner: make the card's change as the hound's next version (the only
                                                              thing in the chat that changes a hound)
    POST   /hounds/{id}/chat/proposals/{message}/cancel       the owner: leave the hound as it is
    DELETE /hounds/{id}/chat                                  the owner: clear the saved conversation (the day's allowance is not reset)

OWNER ONLY. Every route needs a signed-in account that OWNS the hound. A hound that is somebody else's, a house hound and an id that does
not exist all answer 404, so ids cannot be probed. A public hound page keeps the Ask tab's computed answers (``api/hounds_interact.py``),
which cost nothing and call no model. Free accounts chat too, with a smaller day (src/hounds/chat/service.py): the new chat is not behind
the paid Ask wall that the computed Ask has on a member hound.

MOUNT. ``/hounds/{id}/chat...`` is a literal two-segment tail under ``/hounds/{id}``, which no other router declares, so it can mount
anywhere after ``api.hounds_create``; api/app.py mounts it beside ``hounds_interact``.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from src.appstate import ratelimit
from src.appstate import users as users_store
from src.hounds.chat import service
from src.hounds.contract import envelope

from api import auth as auth_mod
from api.auth import get_current_user

router = APIRouter()

_NO_STORE = "no-store"

# Each send is a model call: a person types a message every few seconds at most; the day's allowance (20 / 100) is the real wall.
_send_limiter = ratelimit.FixedWindowLimiter(limit=12, window_s=60.0)
_rl_send = ratelimit.limiter_dependency(_send_limiter, user_dependency=get_current_user)
_read_limiter = ratelimit.FixedWindowLimiter(limit=120, window_s=60.0)
_rl_read = ratelimit.limiter_dependency(_read_limiter, user_dependency=get_current_user)
_edit_limiter = ratelimit.FixedWindowLimiter(limit=60, window_s=3600.0)
_rl_edit = ratelimit.limiter_dependency(_edit_limiter, user_dependency=get_current_user)


class ChatRequest(BaseModel):
    message: str = ""


def _paid(user: users_store.User) -> bool:
    return not auth_mod.is_free_member(user)


def _error(exc: service.ChatError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"error": exc.code, "message": str(exc), **exc.extra})


@router.get("/hounds/{hound_id}/chat")
def chat_open(hound_id: str, response: Response, current_user: users_store.User = Depends(get_current_user),
              _rl: None = Depends(_rl_read)) -> dict:
    response.headers["Cache-Control"] = _NO_STORE
    try:
        return envelope(service.open_chat(current_user.id, _paid(current_user), hound_id))
    except service.ChatError as exc:
        raise _error(exc)


@router.post("/hounds/{hound_id}/chat")
def chat_send(hound_id: str, body: ChatRequest, response: Response, current_user: users_store.User = Depends(get_current_user),
              _rl: None = Depends(_rl_send)) -> dict:
    response.headers["Cache-Control"] = _NO_STORE
    try:
        return envelope(service.send(current_user.id, _paid(current_user), hound_id, body.message))
    except service.ChatError as exc:
        raise _error(exc)


@router.delete("/hounds/{hound_id}/chat")
def chat_clear(hound_id: str, response: Response, current_user: users_store.User = Depends(get_current_user),
               _rl: None = Depends(_rl_edit)) -> dict:
    response.headers["Cache-Control"] = _NO_STORE
    try:
        return envelope(service.clear_chat(current_user.id, hound_id))
    except service.ChatError as exc:
        raise _error(exc)


@router.post("/hounds/{hound_id}/chat/proposals/{message_id}/apply")
def chat_apply(hound_id: str, message_id: int, response: Response, current_user: users_store.User = Depends(get_current_user),
               _rl: None = Depends(_rl_edit)) -> dict:
    response.headers["Cache-Control"] = _NO_STORE
    try:
        return envelope(service.apply_proposal(current_user.id, hound_id, message_id))
    except service.ChatError as exc:
        raise _error(exc)


@router.post("/hounds/{hound_id}/chat/proposals/{message_id}/cancel")
def chat_cancel(hound_id: str, message_id: int, response: Response, current_user: users_store.User = Depends(get_current_user),
                _rl: None = Depends(_rl_edit)) -> dict:
    response.headers["Cache-Control"] = _NO_STORE
    try:
        return envelope(service.cancel_proposal(current_user.id, hound_id, message_id))
    except service.ChatError as exc:
        raise _error(exc)
