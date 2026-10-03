"""api/signup.py: POST /signup (PUBLIC, rate-limited) and GET
/signup/complete -- self-serve entry into the paid beta, on top of the
existing invite-token/billing machinery (src/appstate/users.py,
src/appstate/billing.py, src/appstate/customers.py). This module does no
storage logic of its own beyond the two calls above -- same api/<->src/
split every other pairing in this repo keeps.

WHY THIS ROUTE HAS NO AUTH DEPENDENCY
--------------------------------------
Every other write route in this API assumes an already-invited/authed
caller. Self-serve signup is the one entry point that, by definition, has
no bearer token yet -- that is the whole point of it existing alongside
(not instead of) admin invites. It is rate-limited instead (10/hour per
IP, same shape and same reasoning as api/support.py's anonymous path) so
an open, unauthenticated POST cannot be used to spam-create user rows.

THE NO-EMAIL-SENDER ACTIVATION BRIDGE
----------------------------------------
There is no transactional email sender wired into this app yet. A real
provider (Stripe Checkout) can complete a real payment before that exists,
but the resulting access token has to reach the paying user somehow. GET
/signup/complete?session_id=<stripe checkout session id> is that bridge:
the browser lands back on this app's own success page after Stripe's
hosted checkout (see src.appstate.billing.StripeBillingProvider's
`success_url`), carrying the session id Stripe appends to it, and this
endpoint hands back the ONE-TIME token
src.appstate.billing.apply_stripe_webhook_event minted the moment the
webhook verified that payment. Once an email sender exists, that sender
delivers the same token and this endpoint becomes redundant (kept for
users who close the success tab before the email arrives, or simply not
removed at all -- that is a future call, not this task's).

Never returns a token for a session that never completed payment, is
unknown, or whose re-read window (10 minutes after the first successful
read) has closed -- see src.appstate.customers.take_activation_token's
docstring for why those cases are deliberately indistinguishable from
outside. Inside the window the same session id returns the same token, so
the success page can poll while the webhook is late and survive a reload.

IDEMPOTENT PER EMAIL
----------------------
POST /signup never creates a second user row for an email that already has
one. A repeat signup for a `pending_payment` or `waitlisted` email
re-evaluates today's billing configuration and returns the resulting state
(a fresh checkout URL if Stripe just became configured; still waitlisted
if not) rather than either erroring or silently no-op'ing -- see
`_respond_for`. `active`, `suspended`, and admin-`invited` users are left
alone entirely: signup is not a way to re-litigate an account a human
process (the admin invite endpoint, or Stripe support) already put in a
different state.

THE ONE EXCEPTION: EARLY-ACCESS TESTERS (src/appstate/tester_upgrade.py)
-------------------------------------------------------------------------
`testers.grant_tester` leaves a person `invited`, so a tester whose week ran out
used to hit the `invited` line above and never reach a checkout: a permanent
dead end. A user with a row in `testers` and no current subscription
entitlement is therefore routed through the same checkout a new buyer gets, on
the SAME user id (no second account, nothing deleted):

  * billing on  -> `{"user_id", "checkout": {"status": "redirect", ...}}`, the
    normal answer. An `invited` tester moves to `pending_payment` and the
    webhook makes them `active`, exactly as for a new buyer. Applies inside the
    week too (someone who wants to pay early).
  * billing off -> a distinct, truthful state, no checkout and no promise of an
    email nothing sends: `{"status": "tester_expired", "expires_at"}` once the
    window has ended, `{"status": "tester_active", "expires_at"}` while it is
    still open. The user's status is not touched.
  * billing switched on but unable to take a payment -> the same `error`
    answers a new buyer gets.

A comped `invited` user who is not a tester, an `active` paying customer and a
`suspended` account keep exactly the behaviour above.

NOTE FOR WHOEVER CREATES THE STRIPE PRICE (doc note only -- no Stripe
calls happen in this module or this task): when Brey sets up the beta
Price in the Stripe dashboard, the Product's display name should be
"Linehound (beta)" -- the working brand per Brey's 2026-09-01 decision,
not a final legal/trademark name. This module never reads or sets that
display name; Stripe Checkout renders it from the Product itself.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.appstate import attribution as attribution_mod
from src.appstate import billing
from src.appstate import customers
from src.appstate import events
from src.appstate import ratelimit
from src.appstate import tester_upgrade
from src.appstate import users as users_store

router = APIRouter()

# Same length bound api/support.py uses for its own optional email field --
# RFC 5321's own practical max for a full address.
MAX_EMAIL_LENGTH = 254

# Deliberately simple (not RFC 5322-complete): this is an abuse/typo guard
# ahead of a real signup, not a validator meant to reject every technically
# exotic-but-legal address. A generous, wrong-shaped string ("no @ at all",
# "just a domain") is what this actually needs to catch.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# See module docstring's "WHY THIS ROUTE HAS NO AUTH DEPENDENCY" -- same
# per-hour shape (not per-minute, like the authed core-loop routes) and
# same limit api/support.py's own anonymous path uses, for the same
# reason: nobody legitimately signs up ten times an hour from one IP.
SIGNUP_RATE_LIMIT_PER_HOUR = 10
_signup_limiter = ratelimit.FixedWindowLimiter(
    limit=SIGNUP_RATE_LIMIT_PER_HOUR, window_s=3600.0)


def _client_ip(request: Request) -> str:
    """The caller's address, `Fly-Client-IP` first -- see
    src.appstate.ratelimit.client_ip for why the socket address alone put
    every visitor behind Fly's proxy in one shared bucket."""
    return ratelimit.client_ip(request)


def _rate_limit_signup(request: Request) -> None:
    result = _signup_limiter.check(ratelimit.key_for(f"ip:{_client_ip(request)}"))
    if not result.allowed:
        raise HTTPException(status_code=429, detail={
            "error": "rate_limited", "retry_after": result.retry_after})


# GET /signup/complete is polled by the success page every 2 seconds for up to
# 60 seconds (web/js/signup.js: SIGNUP_POLL_INTERVAL_MS / SIGNUP_POLL_TIMEOUT_MS),
# which is at most 30 requests from one honest buyer. 30 a minute therefore never
# refuses one; it exists because every call writes (the stale-token sweep in
# customers._wipe_stale_rereads) and the route has no other gate. A 429 is not
# an error to the page: pollSignupToken treats it like a 404 and tries again.
SIGNUP_COMPLETE_RATE_LIMIT_PER_MINUTE = 30
_complete_limiter = ratelimit.FixedWindowLimiter(
    limit=SIGNUP_COMPLETE_RATE_LIMIT_PER_MINUTE, window_s=60.0)


def _rate_limit_signup_complete(request: Request) -> None:
    result = _complete_limiter.check(ratelimit.key_for(f"ip:{_client_ip(request)}"))
    if not result.allowed:
        raise HTTPException(status_code=429, detail={
            "error": "rate_limited", "retry_after": result.retry_after})


def _valid_email(email: str) -> bool:
    return bool(email) and len(email) <= MAX_EMAIL_LENGTH and bool(_EMAIL_RE.match(email))


class SignupRequest(BaseModel):
    email: str = Field(max_length=MAX_EMAIL_LENGTH)
    # First-touch UTM tags, referrer host and the browser's random visitor id
    # (web/js/attribution.js). Untrusted: src.appstate.attribution decides
    # what is kept. Optional, so every older client keeps working.
    attribution: Optional[dict] = None


class _CheckoutProviderError(Exception):
    """Raised by _attempt_checkout (never lets `str(exc)` travel further --
    see _respond_for) when a CONFIGURED billing provider's create_checkout
    call itself failed -- e.g. a real Stripe API error
    (StripeBillingProvider._call's RuntimeError, which embeds Stripe's raw
    response body: see that class's docstring). Distinct from
    billing.BillingProviderNotConfigured (the honest "billing not set up
    yet" case, which _attempt_checkout still returns None for, unchanged):
    this is "billing IS configured and the provider itself refused or
    failed," which must not be silently folded into "waitlisted" -- a
    signup that could not check out belongs in an honest error state, not
    a queue it was never actually placed in.
    """


class _CheckoutMisconfigured(Exception):
    """Billing is switched ON and the deploy cannot honour a payment.

    The third state, and the one that hid for weeks. `_attempt_checkout`
    returning None used to mean two very different things at once:

      * billing is deliberately off (BILLING_PROVIDER unset -- the honest
        default while there is nothing to sell). Waitlisting is correct.
      * billing is switched on and MISCONFIGURED -- no PUBLIC_BASE_URL, no
        STRIPE_BETA_PRICE_ID. Waitlisting is a lie: the person came to buy,
        the product meant to sell to them, and they were told "we'll email
        you when a beta spot opens up" by a codebase that contains no email
        sender at all.

    Collapsing the two meant a broken production deploy looked exactly like
    a closed beta, in the logs and in the response, and would have kept
    looking like one for as long as nobody happened to try to pay.
    """


def _billing_is_switched_on() -> bool:
    """True when this deploy intends to sell, whatever state it is in."""
    selected = (os.environ.get(billing.ENV_BILLING_PROVIDER)
                or billing.DEFAULT_BILLING_PROVIDER).strip()
    return selected != billing.DEFAULT_BILLING_PROVIDER


def _attempt_checkout(user_id: int) -> Optional[str]:
    """A real Stripe checkout URL for user_id, or None -- the honest
    "billing not ready" state -- whenever either half of billing
    (STRIPE_API_KEY, or the beta plan's own STRIPE_BETA_PRICE_ID) is
    missing. See src.appstate.billing.beta_plan_stripe_price_id's
    docstring for why both are checked rather than just the API key.

    Raises _CheckoutProviderError (never billing.BillingProviderNotConfigured
    itself, and never lets a provider's raw RuntimeError propagate) when
    billing IS configured but the provider call failed -- defensive review
    finding F3: without this, a real Stripe RuntimeError (which embeds
    Stripe's raw response body) surfaced all the way up as this route's
    unhandled 500, body and all.
    """
    price_id = billing.beta_plan_stripe_price_id()
    if not price_id:
        if _billing_is_switched_on():
            print(f"ESCALATE: signup: {billing.ENV_BILLING_PROVIDER} is set "
                  f"but no beta plan price id is configured -- every paying "
                  f"customer is being silently waitlisted",
                  file=sys.stderr, flush=True)
            raise _CheckoutMisconfigured()
        return None
    provider = billing.get_billing_provider()
    # The user's FIRST-touch attribution (stored at signup), so a retried
    # checkout carries the same metadata as the first attempt -- Stripe
    # refuses to reuse an idempotency key with different parameters.
    kwargs = {}
    stored = customers.get_signup_attribution(user_id)
    if stored:
        kwargs["attribution"] = stored
    try:
        url = provider.create_checkout(user_id, price_id, **kwargs)
    except billing.BillingProviderNotConfigured as exc:
        if _billing_is_switched_on():
            # Names the variable, never a secret's value.
            print(f"ESCALATE: signup: billing is switched on but cannot "
                  f"complete a checkout: {exc}", file=sys.stderr, flush=True)
            raise _CheckoutMisconfigured() from None
        return None
    except RuntimeError as exc:
        # Never relay Stripe's raw error body -- log it server-side only,
        # the same swallow-and-log shape events.record_event_safe uses for
        # a failure that must not become the caller's problem.
        print(f"signup: checkout provider call failed for user_id={user_id}: "
              f"{exc!r}", file=sys.stderr, flush=True)
        raise _CheckoutProviderError() from None
    return url or None


def _respond_for(user: users_store.User) -> dict:
    """The response (and any resulting status write) for an email that
    already has a user row -- see module docstring's "IDEMPOTENT PER
    EMAIL" section for the reasoning, and its early-access-tester exception."""
    # None for everyone who is not an early-access tester without a current
    # subscription, which leaves the rest of this function exactly as it was.
    tester = tester_upgrade.upgrade_state(user)
    if tester is None and user.status in ("active", "suspended", "invited"):
        # Not this endpoint's business to move a user out of a state a
        # human process put them in -- report it plainly instead.
        return {"user_id": user.id, "status": user.status}
    try:
        checkout_url = _attempt_checkout(user.id)
    except _CheckoutProviderError:
        # Structured, generic response -- never the raw provider error
        # (see _attempt_checkout's docstring) and never a 500 out of the
        # one endpoint the public actually hits.
        return {"user_id": user.id, "status": "error",
                "message": "checkout could not be started; try again shortly"}
    except _CheckoutMisconfigured:
        # Deliberately NOT "try again shortly" -- trying again will not help,
        # and telling someone it might is the same false comfort as putting
        # them on a waitlist nothing can email. No config detail reaches the
        # caller; the ESCALATE line in the logs is for the operator.
        return {"user_id": user.id, "status": "error",
                "message": "payments are not available right now; nothing "
                           "has been charged"}
    if checkout_url:
        # A tester who is already `active` (a lapsed subscriber coming back)
        # keeps that status: nothing about their account changed, and the
        # webhook only ever moves a person INTO active.
        keep_status = tester is not None and user.status == "active"
        if user.status != "pending_payment" and not keep_status:
            users_store.set_user_status(user.id, "pending_payment")
        stored = customers.get_signup_attribution(user.id)
        events.record_event_safe(user.id, events.CHECKOUT_STARTED,
                                 *([stored] if stored else []))
        return {"user_id": user.id,
                "checkout": {"status": "redirect", "checkout_url": checkout_url}}
    if tester is not None:
        # Billing is off, so there is nothing to buy. Say what is true about
        # their access and leave their status alone: waitlisting a tester would
        # file a person we already let in under "not yet picked".
        return {"user_id": user.id, "status": tester["state"],
                "expires_at": tester["expires_at"]}
    if user.status != "waitlisted":
        users_store.set_user_status(user.id, "waitlisted")
    return {"user_id": user.id, "status": "waitlisted"}


@router.post("/signup")
def signup(body: SignupRequest, _rate_limit: None = Depends(_rate_limit_signup)) -> dict:
    email = (body.email or "").strip().lower()
    if not _valid_email(email):
        raise HTTPException(status_code=400, detail="a valid email is required")

    attribution = attribution_mod.clean_attribution(body.attribution)

    user = users_store.get_user_by_email(email)
    if user is None:
        try:
            user = users_store.create_user(email, status="pending_payment", plan="none")
        except ValueError as exc:
            # Same race window api/auth.py's create_invite documents: another
            # worker inserted this email between the SELECT and this INSERT.
            # Re-read rather than turning a benign race into a 400/500 on
            # the one endpoint the public actually hits.
            user = users_store.get_user_by_email(email)
            if user is None:
                raise HTTPException(status_code=400, detail=str(exc))
            _remember_attribution(user.id, attribution)
            return _respond_for(user)
        _remember_attribution(user.id, attribution)
        # ACCOUNT_CREATED, not SIGNUP_STARTED: this is the moment a real
        # user row came into existence. SIGNUP_STARTED now belongs solely
        # to the client-side beacon that fires when a visitor REACHES the
        # form (api/funnel.py's PUBLIC_FUNNEL_KINDS) -- the two shared one
        # kind until 2026-09-01, which made the landing -> signup
        # conversion number a mixture of page-loads and real signups.
        # Attribution rides as event properties only when there is some, so a
        # direct signup records exactly the event it always did.
        events.record_event_safe(user.id, events.ACCOUNT_CREATED,
                                 *([attribution] if attribution else []))
    else:
        # A returning signup (a pending or waitlisted email trying again)
        # keeps the first touch it already has; this only fills a gap.
        _remember_attribution(user.id, attribution)
    return _respond_for(user)


def _remember_attribution(user_id: int, attribution: dict) -> None:
    """Store first-touch attribution without ever letting analytics fail the
    signup it rides on -- the same swallow-and-log contract
    events.record_event_safe gives."""
    if not attribution:
        return
    try:
        customers.record_signup_attribution(user_id, attribution)
    except Exception as exc:  # noqa: BLE001
        print(f"signup: could not store attribution for user_id={user_id}: {exc!r}",
              file=sys.stderr, flush=True)


@router.get("/signup/complete")
def signup_complete(session_id: str,
                    _rate_limit: None = Depends(_rate_limit_signup_complete)) -> dict:
    """The no-email-sender activation bridge -- see module docstring.
    `session_id` is the Stripe Checkout Session id Stripe appends to the
    success_url redirect. A 404 covers three cases this endpoint never
    tells apart (see src.appstate.customers.take_activation_token's
    docstring): payment never completed (or its webhook has not landed YET --
    web/js/signup.js polls this route for up to a minute while it 404s),
    session id is unknown/forged, or the token's re-read window closed.

    RE-READ WINDOW: the first successful read starts a 10-minute window
    (customers.ACTIVATION_REREAD_WINDOW) in which the SAME session id returns
    the SAME token again, so a reload or a lost response never locks a
    paying customer out. After it the token is wiped and the session id is
    dead -- a session id found later in a history file or a log is worth
    nothing.

    RATE LIMIT: 30 per minute per client IP (see
    SIGNUP_COMPLETE_RATE_LIMIT_PER_MINUTE) -- one buyer's poll loop makes at
    most 30; the page treats a 429 as "try again"."""
    result = customers.take_activation_token(
        session_id, reread_window=customers.ACTIVATION_REREAD_WINDOW)
    if result is None:
        raise HTTPException(status_code=404, detail={
            "error": "not_found",
            "message": "no activation token available for this session"})
    return {"user_id": result["user_id"], "token": result["raw_token"]}
