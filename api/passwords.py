"""api/passwords.py: email + password sign-in on top of the bearer-token sessions.

    POST /auth/login                    {email, password}  -> a NEW session token
    POST /auth/logout                   revokes the token that made the request
    GET  /auth/password                 {has_password}
    POST /auth/password                 {new_password, current_password?}
    POST /admin/users/password-reset    {user_id | email, reason}   (admin only)

The storage, hashing, rules and rate limits are src/appstate/passwords.py; where a
session token ends is src/appstate/access.py. This file is the HTTP shape only,
the same api/<->src/ split every other pairing here keeps.

TOKENS STAY THE SESSION. Login exchanges a password for the same kind of token
the admin issues, minted by users_store.insert_token, ending where the member's
access ends (tester window, subscriber lifetime, a comp). Nothing downstream
changed: every route still authenticates a bearer token.

NO ACCOUNT ENUMERATION. A wrong password, an unknown email, an account with no
password and a malformed body are one response: 401 `login_failed` with one
sentence, byte for byte, and each spends the same scrypt. Only a caller who has
presented the CORRECT password can learn anything else about the account (that
it has no active access: 403 `no_access`), which tells them nothing they did not
already hold the key to.

CSRF STANCE (stated because the reviewer will ask)
-----------------------------------------------------
There is no cookie. A session is a bearer token the page keeps in localStorage and
sends in an Authorization header, which a browser never attaches on its own to a
request another site causes, so the usual CSRF attack (ride the victim's ambient
credentials) has nothing to ride. Login CSRF (forcing a victim into the
attacker's session) needs a cookie jar to plant a session in; there is none.
These routes also take JSON only: FastAPI refuses a body that is not
application/json (a plain HTML form posts urlencoded or text/plain), and a
cross-origin fetch that sets application/json needs a CORS preflight this app
never answers (no CORS middleware). tests/test_api_passwords.py pins all three
facts: no Set-Cookie on any response, a form post is refused, no CORS allow
headers. If a cookie is ever introduced, this reasoning ends and a CSRF token
becomes mandatory.

WHAT NEVER LEAVES THIS FILE: the password. It is read from the body, passed to
src.appstate.passwords, and not stored, logged or put in an exception, an event
or a response. The fields are typed `Any` and checked by hand so a malformed
value gets the plain sentence below and not a 422 that echoes the input back.
Events (login_succeeded / login_failed / password_set) carry no email,
password, hash or token; a failed login is recorded under a fixed anonymous id
so an unknown address and a wrong password leave identical traces.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from api.admin import REISSUE_REASON_MAX, _LOOKS_LIKE_A_TOKEN, _SECRET_HINTS, _account_id
from api.auth import _require_admin, get_current_user
from src.appstate import access
from src.appstate import events
from src.appstate import passwords
from src.appstate import ratelimit
from src.appstate import users as users_store

router = APIRouter()

# ONE sentence for every way a sign-in can fail on credentials. Never changes with
# the reason.
LOGIN_FAILED_MESSAGE = "That email and password do not match."
NO_ACCESS_MESSAGE = ("This account has no active access, so no session was started. "
                     "If you think that is wrong, use Get help on the support page.")

# A reason is stored in the audit log: it may not hold a token (admin.py's own
# patterns) or a password.
_PASSWORD_HINT = re.compile(r"pass(?:word|wd)\s*[:=]\s*\S", re.IGNORECASE)


def _err(status: int, code: str, message: str, *, headers: Optional[dict] = None,
         **extra: Any) -> HTTPException:
    detail = {"error": code, "message": message}
    detail.update(extra)
    return HTTPException(status_code=status, detail=detail, headers=headers)


def _rate_limited(retry_after: float) -> HTTPException:
    seconds = max(int(retry_after + 0.999), 1)
    minutes = (seconds + 59) // 60
    wait = "a minute" if minutes <= 1 else f"{minutes} minutes"
    if seconds >= 2 * 3600:
        wait = f"{(seconds + 3599) // 3600} hours"
    return _err(429, "rate_limited", f"Too many attempts. Try again in about {wait}.",
                headers={"Retry-After": str(seconds)}, retry_after=seconds)


def _count_attempt(keys) -> None:
    """Count the attempt or raise the 429. A limiter that cannot reach its table
    refuses (503): a sign-in that cannot be rate limited must not be open."""
    try:
        retry = passwords.check_and_record_attempt(keys)
    except Exception as exc:  # noqa: BLE001 -- fail closed
        print(f"auth: login limiter unavailable: {exc!r}", file=sys.stderr, flush=True)
        raise _err(503, "login_unavailable", "Sign-in is unavailable right now. Try again shortly.")
    if retry is not None:
        raise _rate_limited(retry)


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: Optional[Any] = None
    password: Optional[Any] = None


@router.post("/auth/login")
def login(body: LoginRequest, request: Request) -> dict:
    """Exchange an email and password for a session token.

    Order matters and is the whole design: (1) count the attempt against the
    hashed client address and the hashed email, refusing 429 past the limits;
    (2) verify, always spending one scrypt; (3) only for a verified person, ask
    where their access ends. 401 for any credential failure (identical), 403
    `no_access` for correct credentials with no access (waitlisted, suspended,
    lapsed, or an admin-invited beta user, who signs in with their access code),
    200 with the token otherwise.

    A tester whose window has ended still gets a token, ending in the past (the
    way a support re-issue does): it opens nothing, but the sign-in page then
    shows the ended-access state and the upgrade door
    (POST /billing/tester-checkout). `access_active` says which."""
    email = body.email.strip().lower() if isinstance(body.email, str) else ""
    password = body.password if isinstance(body.password, str) else ""
    _count_attempt([(passwords.SCOPE_IP, ratelimit.client_ip(request)),
                    (passwords.SCOPE_EMAIL, email[:passwords.MAX_EMAIL_LENGTH + 1])])

    user = passwords.authenticate_password(email, password)
    if user is None:
        events.record_event_safe(events.LOGIN_ANONYMOUS_USER_ID, events.LOGIN_FAILED,
                                 {"method": "password", "reason": "bad_credentials"})
        raise _err(401, "login_failed", LOGIN_FAILED_MESSAGE)

    plan = access.access_token_end(user)
    if plan is None:
        events.record_event_safe(events.LOGIN_ANONYMOUS_USER_ID, events.LOGIN_FAILED,
                                 {"method": "password", "reason": "no_access"})
        raise _err(403, "no_access", NO_ACCESS_MESSAGE)

    kind, ends_at = plan
    now = datetime.now(timezone.utc)
    try:
        with users_store._connect() as conn:
            raw_token = users_store.insert_token(conn, user.id, ttl=ends_at - now, now=now)
    except Exception as exc:  # noqa: BLE001 -- nothing was issued
        print(f"auth: login could not issue a token: {exc!r}", file=sys.stderr, flush=True)
        raise _err(503, "login_unavailable", "Sign-in is unavailable right now. Try again shortly.")
    events.record_event_safe(user.id, events.LOGIN_SUCCEEDED, {"method": "password", "kind": kind})
    return {"token": raw_token, "expires_at": ends_at.isoformat(), "kind": kind,
            "access_active": ends_at > now, "has_password": True}


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------

@router.post("/auth/logout")
def logout(authorization: Optional[str] = Header(default=None),
           user: users_store.User = Depends(get_current_user)) -> dict:
    """Revoke the token that made this request, and only that one: a member signed
    in on a phone and a laptop signs out of one. The dependency has already
    proved the token good, so a bad or expired token is the usual 401 (and has
    nothing left to revoke)."""
    _scheme, _, raw_token = (authorization or "").partition(" ")
    revoked = users_store.revoke_token(raw_token) if raw_token else False
    return {"ok": True, "revoked": bool(revoked)}


# ---------------------------------------------------------------------------
# GET / POST /auth/password
# ---------------------------------------------------------------------------

class SetPasswordRequest(BaseModel):
    new_password: Optional[Any] = None
    current_password: Optional[Any] = None


@router.get("/auth/password")
def password_status(user: users_store.User = Depends(get_current_user)) -> dict:
    """Whether the signed-in member has a password. The sign-in page asks this
    once after an access-code sign-in to decide whether to offer to set one."""
    return {"has_password": passwords.has_password(user.id)}


@router.post("/auth/password")
def set_password(body: SetPasswordRequest,
                 user: users_store.User = Depends(get_current_user)) -> dict:
    """Set or change the signed-in member's password.

    A token is enough to SET the first one (it is the proof of who they are); to
    CHANGE an existing one the current password is required too, so a token left
    on a shared machine cannot quietly take the account over. Wrong current
    passwords are rate limited per account (the same 10 per 15 minutes) because
    the token holder is exactly who could guess one.

    Changing a password does not revoke other sessions: the member's tokens
    include the access code they were given, and revoking it would lock them out
    of the only fallback they have when a password is forgotten. An admin who
    suspects a leaked password clears it (POST /admin/users/password-reset) and
    re-issues the access code (POST /admin/users/reissue), which revokes every
    old token."""
    new_password = body.new_password
    try:
        passwords.check_password_rules(new_password, user.email)
    except passwords.PasswordRejected as exc:
        raise _err(400, "password_rejected", str(exc))
    if passwords.has_password(user.id):
        current = body.current_password
        if not isinstance(current, str) or not current:
            raise _err(400, "current_password_required",
                       "Enter your current password to change it.")
        _count_attempt([(passwords.SCOPE_PASSWORD_CHANGE, str(user.id))])
        if not passwords.verify_user_password(user.id, current):
            raise _err(403, "current_password_wrong", "Your current password is not right.")
    try:
        replaced = passwords.set_password(user.id, new_password, email=user.email)
    except passwords.PasswordRejected as exc:  # cannot differ from the check above
        raise _err(400, "password_rejected", str(exc))
    events.record_event_safe(user.id, events.PASSWORD_SET, {"changed": bool(replaced)})
    return {"ok": True, "has_password": True, "changed": bool(replaced)}


# ---------------------------------------------------------------------------
# POST /admin/users/password-reset
# ---------------------------------------------------------------------------

class PasswordResetRequest(BaseModel):
    # Any, for the reason admin.py's ReissueAccessRequest gives: a malformed id is
    # the same refusal as an unknown account, not a 422.
    user_id: Optional[Any] = None
    email: Optional[str] = None
    reason: Optional[str] = None


PASSWORD_RESET_REFUSED = {"error": "password_reset_refused",
                          "message": "no password was cleared: this request does not match an account"}


def _write_audit(conn, user_id: int, properties: dict) -> None:
    """The `support_password_reset` row, on the caller's open transaction (same
    pattern and reason as admin._write_reissue_audit)."""
    events._ensure_schema(conn)
    conn.execute(
        "INSERT INTO analytics_events (user_hash, kind, properties_json, at) VALUES (?, ?, ?, ?)",
        (events.hash_user_id(user_id), events.SUPPORT_PASSWORD_RESET,
         json.dumps(properties, sort_keys=True), events._now_iso()))


@router.post("/admin/users/password-reset")
def admin_password_reset(body: PasswordResetRequest,
                         _admin: None = Depends(_require_admin)) -> dict:
    """SUPPORT RECOVERY FOR A FORGOTTEN PASSWORD. There is no email sender, so the
    procedure (docs/support/FREE_MEMBERS.md, "Passwords") is:

      1. Verify the person the way a token re-issue is verified: a reply from the
         account's own mailbox. Nothing here proves it.
      2. POST here with {"user_id" | "email", "reason"}. The stored password is
         deleted; the response carries NO secret and no password.
      3. POST /admin/users/reissue for the same account (also revokes every old
         token) and send the new access code to the account's address.
      4. The member signs in with the access code and sets a new password.

    AUDIT: one `support_password_reset` event (hashed user, the reason, whether a
    password existed), written in the SAME transaction as the delete: both stand
    or neither does (503). The reason may not contain a token or a password."""
    if (body.email is None) == (body.user_id is None):
        raise HTTPException(status_code=400, detail="send exactly one of email or user_id")
    why = (body.reason or "").strip()
    if not why:
        raise _err(400, "reason_required", "say what was verified and for which ticket")
    if len(why) > REISSUE_REASON_MAX:
        raise _err(400, "reason_too_long", f"keep the reason under {REISSUE_REASON_MAX} characters")
    if _LOOKS_LIKE_A_TOKEN.search(why) or _SECRET_HINTS.search(why) or _PASSWORD_HINT.search(why):
        raise _err(400, "reason_looks_like_a_secret",
                   "the reason is stored in a log; do not paste a token, key or password into it")
    if body.email is not None:
        user = users_store.get_user_by_email(body.email.strip().lower())
    else:
        account_id = _account_id(body.user_id)
        user = users_store.get_user(account_id) if account_id is not None else None
    if user is None:
        raise HTTPException(status_code=409, detail=dict(PASSWORD_RESET_REFUSED))

    def write_audit(conn, existed: bool) -> None:
        _write_audit(conn, user.id, {"action": "password_reset", "reason": why,
                                     "had_password": existed})

    try:
        had = passwords.clear_password(user.id, audit=write_audit)
    except Exception as exc:  # noqa: BLE001 -- the delete rolled back with the audit row
        print(f"admin: password reset failed, nothing changed: {exc!r}", file=sys.stderr, flush=True)
        raise _err(503, "password_reset_failed",
                   "the password could not be cleared; nothing was changed")
    return {"user_id": user.id, "had_password": had, "cleared": True,
            "next_step": "POST /admin/users/reissue for this account, send the new access "
                         "code to its address, and have the member set a new password."}
