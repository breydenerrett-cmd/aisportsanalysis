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
unknown, or already had its token retrieved -- see
src.appstate.customers.take_activation_token's docstring for why those
three cases are deliberately indistinguishable from outside.

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

from src.appstate import billing
from src.appstate import customers
from src.appstate import events
from src.appstate import ratelimit
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
    """Copied from src.appstate.ratelimit's own client-IP fallback -- same
    reason api/support.py's `_client_ip` gives for not reusing
    `limiter_dependency` outright (this route has no user_dependency to key
    on; it is unauthenticated by design)."""
    client = getattr(request, "client", None)
    host = getattr(client, "host", None) if client is not None else None
    return host or "unknown"


def _rate_limit_signup(request: Request) -> None:
    result = _signup_limiter.check(ratelimit.key_for(f"ip:{_client_ip(request)}"))
    if not result.allowed:
        raise HTTPException(status_code=429, detail={
            "error": "rate_limited", "retry_after": result.retry_after})


def _valid_email(email: str) -> bool:
    return bool(email) and len(email) <= MAX_EMAIL_LENGTH and bool(_EMAIL_RE.match(email))


class SignupRequest(BaseModel):
    email: str = Field(max_length=MAX_EMAIL_LENGTH)


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
    try:
        url = provider.create_checkout(user_id, price_id)
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
    EMAIL" section for the reasoning."""
    if user.status in ("active", "suspended", "invited"):
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
        if user.status != "pending_payment":
            users_store.set_user_status(user.id, "pending_payment")
        events.record_event_safe(user.id, events.CHECKOUT_STARTED)
        return {"user_id": user.id,
                "checkout": {"status": "redirect", "checkout_url": checkout_url}}
    if user.status != "waitlisted":
        users_store.set_user_status(user.id, "waitlisted")
    return {"user_id": user.id, "status": "waitlisted"}


@router.post("/signup")
def signup(body: SignupRequest, _rate_limit: None = Depends(_rate_limit_signup)) -> dict:
    email = (body.email or "").strip().lower()
    if not _valid_email(email):
        raise HTTPException(status_code=400, detail="a valid email is required")

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
            return _respond_for(user)
        # ACCOUNT_CREATED, not SIGNUP_STARTED: this is the moment a real
        # user row came into existence. SIGNUP_STARTED now belongs solely
        # to the client-side beacon that fires when a visitor REACHES the
        # form (api/funnel.py's PUBLIC_FUNNEL_KINDS) -- the two shared one
        # kind until 2026-09-01, which made the landing -> signup
        # conversion number a mixture of page-loads and real signups.
        events.record_event_safe(user.id, events.ACCOUNT_CREATED)
    return _respond_for(user)


@router.get("/signup/complete")
def signup_complete(session_id: str) -> dict:
    """The no-email-sender activation bridge -- see module docstring.
    `session_id` is the Stripe Checkout Session id Stripe appends to the
    success_url redirect. A 404 covers three cases this endpoint never
    tells apart (see src.appstate.customers.take_activation_token's
    docstring): payment never completed, session id is unknown/forged, or
    the token was already retrieved once."""
    result = customers.take_activation_token(session_id)
    if result is None:
        raise HTTPException(status_code=404, detail={
            "error": "not_found",
            "message": "no activation token available for this session"})
    return {"user_id": result["user_id"], "token": result["raw_token"]}
