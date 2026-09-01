"""api/support.py: POST /support (authed or anonymous-with-email),
GET /admin/support and POST /admin/support/{id}/status (admin-only).

Thin wiring over src.appstate.support -- this module does no storage logic
of its own, the same split every other api/<->src/ pairing in this repo
keeps (api/mybets.py over savedbets.py, api/admin.py over users.py/events.py).

WHY POST /support HAS NO REQUIRED AUTH DEPENDENCY
------------------------------------------------------
Every other authenticated write route in this API (POST /my-bets, POST
/betcheck) can assume a bearer token because reaching them at all already
implies a redeemed invite. Support has to catch the case that never gets
that far: someone whose invite link is broken, whose token expired before
they used it, or who has a billing question before ever being invited.
Refusing those callers a way to reach Brey would defeat the point of a
support channel. So this route accepts either an authenticated caller (an
`Authorization` header, resolved exactly as every other route resolves
one) or an anonymous caller who supplies their own `email` in the body --
never both silently merged into one path, and never a caller with a
present-but-invalid token quietly falling back to anonymous (a bad token
still 401s, the same as anywhere else in this API; only the ABSENCE of the
header opens the anonymous path).

WHY THE RATE LIMIT KEYS ON USER-ID-OR-IP, NOT A NEW LIMITER SHAPE
-----------------------------------------------------------------------
src.appstate.ratelimit.limiter_dependency only builds a limiter keyed
purely on an authed user (`user_dependency` given) or purely on the
caller's IP (omitted) -- it has no notion of "whichever identity this
particular request resolved to", because every other route in this repo
picks one shape and keeps it (POST /my-bets is always-authed; POST
/betcheck is always-anonymous). Support is the first route that is
sometimes one, sometimes the other, so `_rate_limit_support` below
re-implements ratelimit's own client-IP fallback (three lines, copied
rather than importing that module's private `_client_identity`) and reuses
its public `FixedWindowLimiter`/`key_for` for the actual counting -- the
only new logic here is which identity string to key on, not how a fixed
window works.

WHY THIS IS "10/HOUR" NOT "10/MINUTE" LIKE THE OTHER ROUTES
------------------------------------------------------------------
POST /my-bets and POST /betcheck are the product's core loop -- a real
user might legitimately fire either dozens of times in a sitting. Support
messages are not: nobody legitimately files ten support tickets in one
minute, and a triage queue Brey has to read by hand needs the abuse floor
lower, not higher, than the core-loop routes. An hour-long fixed window
also means the documented "up to 2x at a boundary" trade-off
(src.appstate.ratelimit's own module docstring) tops out at 20 messages in
the worst case, not 20 in one minute.

WHY GET /admin/support NEVER RETURNS A USER'S EMAIL FROM THE `users` TABLE
------------------------------------------------------------------------------
It returns exactly the `email` column stored on the support_messages row
itself (present only for anonymous senders; NULL for an authed sender,
who is identified by `user_id` instead). Admins who need an authed
sender's email already have GET /admin/users for that -- see that route's
own module docstring for why it is deliberately the ONE place an email is
looked up by admin credentials. Joining users here would make this the
second such place.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from src.appstate import ratelimit
from src.appstate import support as support_store
from src.appstate.users import User

from api.auth import _require_admin, get_current_user

router = APIRouter()

# See module docstring's "WHY 10/HOUR" section.
SUPPORT_RATE_LIMIT_PER_HOUR = 10
_support_limiter = ratelimit.FixedWindowLimiter(
    limit=SUPPORT_RATE_LIMIT_PER_HOUR, window_s=3600.0)


def _resolve_optional_user(authorization: Optional[str] = Header(default=None),
                           request: Request = None) -> Optional[User]:
    """None when no `Authorization` header was sent at all (the anonymous
    path is open); otherwise delegates to `get_current_user` verbatim, so a
    present-but-bad token still 401s exactly as it would on any other
    route -- see module docstring's "never both silently merged" note."""
    if authorization is None:
        return None
    return get_current_user(authorization=authorization, request=request)


def _client_ip(request: Request) -> str:
    """Copied from src.appstate.ratelimit's own client-IP fallback -- see
    module docstring for why this route can't just reuse
    `limiter_dependency` outright."""
    client = getattr(request, "client", None)
    host = getattr(client, "host", None) if client is not None else None
    return host or "unknown"


def _rate_limit_support(request: Request,
                        sender: Optional[User] = Depends(_resolve_optional_user)
                        ) -> None:
    identity = f"user:{sender.id}" if sender is not None else f"ip:{_client_ip(request)}"
    result = _support_limiter.check(ratelimit.key_for(identity))
    if not result.allowed:
        raise HTTPException(status_code=429, detail={
            "error": "rate_limited", "retry_after": result.retry_after})


class SupportMessageRequest(BaseModel):
    email: Optional[str] = Field(default=None, max_length=254)
    subject: str = Field(max_length=support_store.MAX_SUBJECT_LENGTH)
    body: str = Field(max_length=support_store.MAX_BODY_LENGTH)


def _serialize(message: support_store.SupportMessage) -> dict:
    return {
        "id": message.id,
        "user_id": message.user_id,
        "email": message.email,
        "subject": message.subject,
        "body": message.body,
        "created_at": message.created_at,
        "status": message.status,
        "answered_at": message.answered_at,
    }


@router.post("/support")
def create_support_message(
        body: SupportMessageRequest,
        sender: Optional[User] = Depends(_resolve_optional_user),
        _rate_limit: None = Depends(_rate_limit_support)) -> dict:
    """Authed callers identify by `sender.id`; anonymous callers must supply
    `email` in the body -- an authed caller who ALSO sends `email` has it
    ignored (their account is the identity of record; see
    src.appstate.support's docstring for why exactly one of user_id/email
    is ever stored, never both)."""
    if sender is None and not (body.email or "").strip():
        raise HTTPException(status_code=400, detail=
                            "email is required when no Authorization token is sent")
    try:
        message = support_store.create_message(
            user_id=sender.id if sender is not None else None,
            email=None if sender is not None else body.email,
            subject=body.subject, body=body.body)
    except support_store.TooManyOpenMessagesError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _serialize(message)


@router.get("/admin/support")
def list_support_messages(
        status: Optional[str] = None,
        user_id: Optional[int] = None,
        _admin: None = Depends(_require_admin)) -> dict:
    try:
        messages = support_store.list_messages(status=status, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"messages": [_serialize(m) for m in messages]}


class SupportStatusRequest(BaseModel):
    status: str


@router.post("/admin/support/{message_id}/status")
def set_support_status(
        message_id: int,
        body: SupportStatusRequest,
        _admin: None = Depends(_require_admin)) -> dict:
    try:
        updated = support_store.update_status(message_id, body.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if updated is None:
        raise HTTPException(status_code=404, detail="support message not found")
    return _serialize(updated)
