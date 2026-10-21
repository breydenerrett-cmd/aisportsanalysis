"""api/free_signup.py: POST /auth/signup, a self-serve FREE account (PUBLIC, rate limited).

    POST /auth/signup   {email, password, age_confirmed, kennel_name?, attribution?, hound_id?, website?}   -> a session token

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

THE 21+ ATTESTATION (2026-10-20). `age_confirmed` must be the JSON value `true`: the "I am 21 or older" box on the
sign-up form and on the quiz and builder "Keep" step. Anything else (missing, false, the string "true", 1) is refused
with a 400 `age_required` and nothing is created, counted or hashed. It is checked with the other cheap checks, before
the rate limit (and last among them, so a body with a bad email or password still hears about that first), so a visitor who
forgot the box does not burn one of their five. The moment is stored on the user row
(users.age_attested_at) in the account's own transaction. It is a checkbox, not age verification, and the sentence
says so nowhere because it claims nothing more.

`attribution` is the visitor's first touch (web/js/attribution.js: UTM tags, referrer host, random visitor id), cleaned by
src/appstate/attribution.py exactly as POST /signup cleans it, and stored first-touch-wins against the new account. A
repeat signup (an address that already has an account) stores nothing, so a stranger cannot re-credit someone else's
account to a campaign.

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
from api.signup import _remember_attribution, _valid_email
from src.appstate import attribution as attribution_mod
from src.appstate import free_members
from src.appstate import passwords
from src.appstate import ratelimit

router = APIRouter()

# One sentence for a new account and a repeat, byte for byte (see the docstring).
SIGNUP_MESSAGE = ("If that email can be used, you're in. If you already have an account, "
                  "sign in instead; if you lost your password, use Get help on the support page.")

INVALID_EMAIL_MESSAGE = "Enter a valid email address."
AGE_REQUIRED_MESSAGE = "Confirm that you are 21 or older to make an account."


class FreeSignupRequest(BaseModel):
    email: Optional[Any] = None
    password: Optional[Any] = None
    kennel_name: Optional[Any] = None
    # "I am 21 or older". Typed Any and checked for exactly `true` by hand (see the docstring).
    age_confirmed: Optional[Any] = None
    # The visitor's first touch (web/js/attribution.js). Untrusted: attribution_mod decides what is kept.
    attribution: Optional[Any] = None
    # The honeypot. Named like a field a bot wants to fill; the page hides it.
    website: Optional[Any] = None
    # The dog this signup is keeping, when the caller already has one saved under the new account. Optional and
    # only ever used to send the Keep confirmation (see _send_keep_email); a missing, unknown or someone else's
    # id changes nothing and says nothing.
    hound_id: Optional[Any] = None


def _answer(token: Optional[str] = None, ends_at: Optional[datetime] = None) -> dict:
    """The one response shape. A new account fills `token` and `expires_at`."""
    now = datetime.now(timezone.utc)
    return {"ok": True, "message": SIGNUP_MESSAGE, "token": token,
            "expires_at": ends_at.isoformat() if ends_at is not None else None,
            "kind": "free" if token else None,
            "access_active": bool(token) and ends_at is not None and ends_at > now,
            "has_password": bool(token)}


def _send_keep_email(user, hound_id: Any) -> None:
    """THE KEEP HOOK on the signup path (growth playbook backlog 2). When the request names a hound that exists
    and belongs to the account just created, send the Keep confirmation on a background thread: the signup
    answer never waits for Resend and never changes because of it. A new account owns no hound yet unless a
    caller created one first, so for the usual order (the quiz and builder "Keep {Name}" form: account, THEN dog) this
    path stays quiet and the email is sent by POST /hounds instead (api/hounds_create.py ``_send_keep_email``, for
    the account's first dog). No-op while RESEND_API_KEY is unset."""
    if not isinstance(hound_id, str) or not hound_id.strip():
        return
    try:
        from src.hounds import user_store
        from src.notify import email_jobs
        dog = user_store.get_hound(hound_id.strip()[:64])
        if dog is not None and dog["owner_user_id"] == user.id:
            email_jobs.send_keep_confirmation_async(user, dog)
    except Exception as exc:  # noqa: BLE001 -- an email problem must never fail a signup
        print(f"auth: keep email hook failed: {exc!r}", file=sys.stderr, flush=True)


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
    if body.age_confirmed is not True:
        raise _err(400, "age_required", AGE_REQUIRED_MESSAGE)

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
            email, record, has_kennel_name=kennel_name is not None, age_attested=True)
    except Exception as exc:  # noqa: BLE001 -- nothing was written
        print(f"auth: free signup could not create an account: {exc!r}", file=sys.stderr, flush=True)
        raise _err(503, "signup_unavailable", "Sign-up is unavailable right now. Try again shortly.")
    if member is None:
        return _answer()
    free_members.keep_kennel_name(member.user.id, kennel_name)
    _remember_attribution(member.user.id, attribution_mod.clean_attribution(body.attribution))
    _send_keep_email(member.user, body.hound_id)
    return _answer(member.token, member.expires_at)
