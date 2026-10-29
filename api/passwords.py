"""api/passwords.py: email + password sign-in on top of the bearer-token sessions.

    POST /auth/login                    {email, password}  -> a NEW session token
    POST /auth/logout                   revokes the token that made the request
    GET  /auth/password                 {has_password}
    POST /auth/password                 {new_password, current_password?}
    POST /admin/users/password-reset    {user_id | email, reason}   (admin only)
    POST /auth/password/forgot          {email} -> always the same neutral message
    POST /auth/password/reset           {token, new_password} -> spends the link, new session
    POST /admin/users/password-reset-link {user_id | email, reason} (admin; shows the link once)

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

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from api.admin import REISSUE_REASON_MAX, _LOOKS_LIKE_A_TOKEN, _SECRET_HINTS, _account_id
from api.auth import _require_admin, get_current_user
from src.appstate import access
from src.appstate import events
from src.appstate import passwords
from src.appstate import ratelimit
from src.appstate import users as users_store
from src.appstate import password_reset
from src.appstate import billing
from src.notify import email as mail
from src.notify import password_reset_email

logger = logging.getLogger("linehound.password_reset")

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

    A tester whose window has ended signs in as a FREE member (kind "free",
    owner ruling 2026-10-27): they keep their kennel and get what a free account
    gets, never the paid board. `access_active` is True for them."""
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
# POST /auth/continue-free
# ---------------------------------------------------------------------------

@router.post("/auth/continue-free")
def continue_free(request: Request, authorization: Optional[str] = Header(default=None)) -> dict:
    """An ended tester who signed in with their access code (never set a password)
    trades that ENDED code for a fresh free-member session (owner ruling
    2026-10-27: they keep their kennel). The code is the proof of identity, as for
    POST /billing/tester-checkout. Every refusal is the same 401
    `continue_unavailable`, so this tells nobody which rule failed; the rules and
    the 90 day bound are access.continue_as_free. The old code is revoked as the
    new token is issued. Rate limited like sign-in (per hashed client address;
    a refused or failed exchange counts, so guessing codes is throttled). The
    event carries the user's hashed id and the kind only, never a token or email."""
    _count_attempt([(passwords.SCOPE_IP, ratelimit.client_ip(request))])
    _scheme, _, raw_token = (authorization or "").partition(" ")
    try:
        issued = access.continue_as_free(raw_token.strip())
    except Exception as exc:  # noqa: BLE001 -- nothing was issued
        print(f"auth: continue-free failed: {exc!r}", file=sys.stderr, flush=True)
        raise _err(503, "login_unavailable", "Sign-in is unavailable right now. Try again shortly.")
    if issued is None:
        events.record_event_safe(events.LOGIN_ANONYMOUS_USER_ID, events.LOGIN_FAILED,
                                 {"method": "continue_free", "reason": "refused"})
        raise _err(401, "continue_unavailable", "That access code cannot be continued.")
    new_token, ends_at, user_id = issued
    events.record_event_safe(user_id, events.LOGIN_SUCCEEDED,
                             {"method": "continue_free", "kind": access.LEVEL_FREE_KIND})
    return {"token": new_token, "expires_at": ends_at.isoformat(), "kind": access.LEVEL_FREE_KIND,
            "access_active": True}


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


# ---------------------------------------------------------------------------
# Forgot password (owner ask 2026-10-29)
# ---------------------------------------------------------------------------

FORGOT_NEUTRAL_MESSAGE = "If that email has an account, a reset link is on its way."
RESET_BAD_LINK_MESSAGE = "That reset link has expired or was already used. Ask for a new one."


def _reset_link(raw_token: str) -> str:
    return f"{billing._public_base_url()}/web/#/reset?token={raw_token}"


class ForgotRequest(BaseModel):
    email: Optional[Any] = None


def _send_reset_link(email: str) -> None:
    """Runs AFTER the response (BackgroundTasks) so the caller's wait cannot tell
    an account from no account. Never raises; never logs the token or a full
    address. With no email provider it says so in one safe line and the owner
    uses People -> Send password reset link instead (docs/owner/PASSWORD_RESET.md).

    An account with no password (a comp or tester the admin made) is a user row
    like any other, so it gets a link and can set its first password here."""
    try:
        user = users_store.get_user_by_email(email)
        if user is None:
            return
        masked = mail.mask_email(user.email)
        raw, _ends = password_reset.create_token(user.id)
        if not mail.enabled():
            mail.note_disabled()
            logger.warning("password reset requested for %s but no email provider is configured "
                           "(RESEND_API_KEY unset); owner can send a link from admin People", masked)
            return
        minutes = int(password_reset.TOKEN_TTL.total_seconds() // 60)
        message = password_reset_email.build(to=user.email, link=_reset_link(raw), minutes=minutes)
        result = mail.send(message, user_id=user.id, kind=password_reset_email.KIND_PASSWORD_RESET,
                           date=password_reset.hash_token(raw)[:16])
        if result.get("status") != mail.R_SENT:
            logger.warning("password reset email to %s was not sent: %s", masked, result.get("status"))
    except Exception as exc:  # noqa: BLE001 -- a background job must not crash the worker
        logger.error("password reset send failed: %s", type(exc).__name__)


@router.post("/auth/password/forgot")
def forgot_password(body: ForgotRequest, request: Request, background: BackgroundTasks) -> dict:
    """Ask for a reset link. The answer is the same sentence for a known address,
    an unknown one, an account with no password and a malformed body; the work
    (lookup, token, email) happens after the response. Rate limited per email
    and per client address: counted for ANY string, so the limiter is not an
    oracle either."""
    email = body.email.strip().lower() if isinstance(body.email, str) else ""
    email = email[:passwords.MAX_EMAIL_LENGTH + 1]
    for keys, limits in (([(password_reset.SCOPE_FORGOT_IP, ratelimit.client_ip(request))],
                          password_reset.FORGOT_IP_LIMITS),
                         ([(password_reset.SCOPE_FORGOT_EMAIL, email)], password_reset.FORGOT_LIMITS)):
        try:
            retry = passwords.check_and_record_attempt(keys, limits=limits)
        except Exception as exc:  # noqa: BLE001 -- fail closed
            print(f"auth: forgot limiter unavailable: {exc!r}", file=sys.stderr, flush=True)
            raise _err(503, "login_unavailable", "That is unavailable right now. Try again shortly.")
        if retry is not None:
            raise _rate_limited(retry)
    if email and len(email) <= passwords.MAX_EMAIL_LENGTH and "@" in email:
        background.add_task(_send_reset_link, email)
    return {"ok": True, "message": FORGOT_NEUTRAL_MESSAGE}


class ResetRequest(BaseModel):
    token: Optional[Any] = None
    new_password: Optional[Any] = None


@router.post("/auth/password/reset")
def reset_password(body: ResetRequest, request: Request) -> dict:
    """Spend a reset link and set the new password.

    Order: rate limit by client address; check the password rules BEFORE the link
    is spent (a too-weak password must not burn it); spend the link (single use,
    30 minutes); set the password; revoke EVERY session of the account (the
    access codes too: that is the point of a reset after a leak); then, if the
    account still has access, mint one fresh session so the member lands signed
    in. A comp or tester keeps their access, just under a new code."""
    _count_attempt([(password_reset.SCOPE_RESET_IP, ratelimit.client_ip(request))])
    token = body.token
    owner_id = password_reset.live_owner(token)
    user = users_store.get_user(owner_id) if owner_id is not None else None
    if user is None:
        raise _err(400, "reset_link_invalid", RESET_BAD_LINK_MESSAGE)
    try:
        passwords.check_password_rules(body.new_password, user.email)
    except passwords.PasswordRejected as exc:
        raise _err(400, "password_rejected", str(exc))
    if password_reset.consume_token(token) != user.id:
        raise _err(400, "reset_link_invalid", RESET_BAD_LINK_MESSAGE)
    try:
        passwords.set_password(user.id, body.new_password, email=user.email)
        now = datetime.now(timezone.utc)
        plan = access.access_token_end(user)
        with users_store._connect() as conn:
            users_store.revoke_tokens_on(conn, user.id, when=now)
            raw_token = (users_store.insert_token(conn, user.id, ttl=plan[1] - now, now=now)
                         if plan is not None else None)
    except Exception as exc:  # noqa: BLE001
        print(f"auth: password reset failed: {exc!r}", file=sys.stderr, flush=True)
        raise _err(503, "login_unavailable", "That is unavailable right now. Ask for a new link.")
    events.record_event_safe(user.id, events.PASSWORD_SET, {"changed": True, "via": "reset_link"})
    out: dict = {"ok": True, "has_password": True}
    if raw_token is not None:
        out.update({"token": raw_token, "expires_at": plan[1].isoformat(), "kind": plan[0],
                    "access_active": plan[1] > now})
    return out


@router.post("/admin/users/password-reset-link")
def admin_password_reset_link(body: PasswordResetRequest,
                              _admin: None = Depends(_require_admin)) -> dict:
    """THE FALLBACK WHEN NO EMAIL PROVIDER IS CONFIGURED. Makes a reset link for
    the account and returns it ONCE (nothing stores the raw link) so the owner can
    text it. Same single-use, 30-minute token as the emailed one. Audited like a
    password clear: hashed user, the reason, never the link."""
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
    had = passwords.has_password(user.id)
    try:
        with users_store._connect() as conn:
            raw, ends = password_reset.create_token(user.id, via="admin", conn=conn)
            _write_audit(conn, user.id, {"action": "reset_link", "reason": why, "had_password": had})
    except Exception as exc:  # noqa: BLE001
        print(f"admin: reset link failed, nothing changed: {exc!r}", file=sys.stderr, flush=True)
        raise _err(503, "password_reset_failed", "the link could not be made; nothing was changed")
    return {"user_id": user.id, "email": user.email, "link": _reset_link(raw),
            "expires_at": ends.isoformat(), "shown_once": True}
