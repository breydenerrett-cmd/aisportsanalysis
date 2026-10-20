"""api/free_signup.py: POST /auth/signup, a self-serve FREE account (PUBLIC, rate limited).

    POST /auth/signup   {email, password, kennel_name?, website?}   -> a session token

OWNER DECISION "yes open signups" (2026-10-19). A visitor gives an email and a
password and is signed in at once, as an `active` member whose plan is "free"
(src/appstate/access.py, TWO LEVELS). No waitlist, no access code, no approval. A
free member opens the dog surface (kennels, building, editing and backtesting their
own dogs, Ask, the locker room, fire, fan tips, following) and NOT the paid member
board (Gameday, Matchups, Props and the other daily-picks routes): that stays behind
paid access, testers and comps, enforced in api/auth.py require_paid_access.

The older POST /signup (api/signup.py) is untouched. It is the PAID-beta door
(waitlist while billing is off, Stripe checkout when it is on) and the page keeps
linking to it as "Early access to daily picks".

THE PASSWORD never leaves this function: it is read from the body, checked against
src/appstate/passwords.check_password_rules (10+ characters, not the email, not on
the common list), hashed, and stored as a scrypt record. It is not logged, stored,
echoed or put in an event or an exception. The body fields are typed `Any` and
checked by hand so a malformed value gets a plain sentence and not a 422 that
echoes the input back (the same reason api/passwords.py gives).

NO ACCOUNT ENUMERATION, AND ITS ONE HONEST LIMIT. A signup for an address that
already has an account of any kind creates nothing and returns the SAME 200, with
the SAME keys and the SAME sentence as a new account; the only difference is that
`token` is null. That difference cannot be removed: a new member must be handed a
session (there is no email sender to send a link), and a repeat cannot be handed
someone else's. What bounds it is the rate limit (5 an hour per address, 100 a day
overall, every attempt counted, an existing email's included), which makes probing
a list of addresses impractical, and the fact that an existing address is never told
anything else about itself. Both paths also spend one scrypt, so neither is faster.

ABUSE BASICS: a honeypot field (`website`, hidden on the page: a bot that fills every
input fills it, a person never sees it) gets the repeat-signup answer and creates
nothing; the email is lower-cased and format-checked; the per-address and overall
limits live in the database (src/appstate/free_members.py) so a redeploy does not
reset them; the body cap is api/bodylimit.py's. The `signup_free_created` event is
written in the account's own transaction and carries no email.

The kennel name is optional, validated, and handed to whatever kennel-name store the
product has registered (free_members.register_kennel_name_store); with none, it is
dropped, and the response says nothing either way.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from api.passwords import _err, _rate_limited
from api.signup import _valid_email
from src.appstate import free_members
from src.appstate import passwords
from src.appstate import ratelimit

router = APIRouter()

# One sentence for a new account and a repeat, byte for byte (see the docstring).
SIGNUP_MESSAGE = ("If that email can be used, you're in. If you already have an account, "
                  "sign in instead; if you lost your password, use Get help on the support page.")

INVALID_EMAIL_MESSAGE = "Enter a valid email address."


class FreeSignupRequest(BaseModel):
    email: Optional[Any] = None
    password: Optional[Any] = None
    kennel_name: Optional[Any] = None
    # The honeypot. Named like a field a bot wants to fill; the page hides it.
    website: Optional[Any] = None


def _answer(token: Optional[str] = None, ends_at: Optional[datetime] = None) -> dict:
    """The one response shape. A new account fills `token` and `expires_at`."""
    now = datetime.now(timezone.utc)
    return {"ok": True, "message": SIGNUP_MESSAGE, "token": token,
            "expires_at": ends_at.isoformat() if ends_at is not None else None,
            "kind": "free" if token else None,
            "access_active": bool(token) and ends_at is not None and ends_at > now,
            "has_password": bool(token)}


@router.post("/auth/signup")
def free_signup(body: FreeSignupRequest, request: Request) -> dict:
    """Create a free account and sign it in. Order is the design: the honeypot (a
    bot is answered like a repeat and counted nowhere); the cheap checks that cost
    nothing to refuse (400); THEN the rate limit (429, 503 if it cannot be read: a
    signup that cannot be limited must not be open); then one scrypt and the
    transaction."""
    if body.website not in (None, ""):
        return _answer()

    email = body.email.strip().lower() if isinstance(body.email, str) else ""
    if not _valid_email(email):
        raise _err(400, "invalid_email", INVALID_EMAIL_MESSAGE)
    try:
        normalised = passwords.check_password_rules(body.password, email)
    except passwords.PasswordRejected as exc:
        raise _err(400, "password_rejected", str(exc))
    try:
        kennel_name = free_members.clean_kennel_name(body.kennel_name)
    except free_members.KennelNameRejected as exc:
        raise _err(400, "kennel_name_rejected", str(exc))

    try:
        retry = free_members.check_and_record_signup(ratelimit.client_ip(request))
    except Exception as exc:  # noqa: BLE001 -- fail closed
        print(f"auth: signup limiter unavailable: {exc!r}", file=sys.stderr, flush=True)
        raise _err(503, "signup_unavailable", "Sign-up is unavailable right now. Try again shortly.")
    if retry is not None:
        raise _rate_limited(retry)

    record = passwords.hash_password(normalised)       # spent on a repeat too
    try:
        member = free_members.create_free_member(
            email, record, has_kennel_name=kennel_name is not None)
    except Exception as exc:  # noqa: BLE001 -- nothing was written
        print(f"auth: free signup could not create an account: {exc!r}", file=sys.stderr, flush=True)
        raise _err(503, "signup_unavailable", "Sign-up is unavailable right now. Try again shortly.")
    if member is None:
        return _answer()
    free_members.keep_kennel_name(member.user.id, kennel_name)
    return _answer(member.token, member.expires_at)
