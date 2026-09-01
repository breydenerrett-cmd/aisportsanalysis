"""Billing endpoints: checkout, subscription status, and Stripe webhook,
wired to src.appstate.billing and src.appstate.customers.

Same api/<->src/ boundary as api/auth.py: this module imports FROM
src.appstate.billing, never the reverse. No card data ever passes through
here -- Stripe's own hosted Checkout/webhook events are the only things
this module touches (src/appstate/billing.py's module docstring).

Both endpoints are honest about "not configured" rather than faking
success -- see src/appstate/billing.py's NullBillingProvider and
StripeBillingProvider docstrings. The active provider is read via
src.appstate.billing.get_billing_provider() on every request (not cached
at import time) so a BILLING_PROVIDER/STRIPE_API_KEY env change takes
effect on the next request, the same freshness api/auth.py's
authproviders.get_provider() gives AUTH_PROVIDER.

CANCELLATION POLICY (LINEHOUND paid beta): cancelling stops renewal and
nothing else -- the customer keeps paid access through the period they
already paid for (`current_period_end`), and POST /billing/reactivate
resumes renewal with no gap as long as it is called before then. The
entitlement decision itself lives in one place,
src.appstate.customers.has_paid_access, which api/auth.py's
require_paid_access gates the game surface on.

STRIPE TEST MODE: everything here (checkout, webhook, cancel, reactivate) works
identically in test mode with a `sk_test_...` STRIPE_API_KEY and Stripe's
published test card numbers -- Stripe does not distinguish test/live at the
API-shape level, only by which key is used and which dashboard the
resulting objects show up in. See POST /billing/cancel's own docstring for
the one behavioral wrinkle test mode raises (webhook delivery timing).
"""

from __future__ import annotations

import json
import os
import sys

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.appstate import billing
from src.appstate import customers
from src.appstate import events
from src.appstate import ratelimit
from src.appstate.users import User

from api.auth import get_current_user

router = APIRouter()

# Both routes below already require get_current_user, so there is always a
# stable identity to key on -- same authed-user-keyed shape
# api/mybets.py's own limiter uses. 20/min is generous for a real user
# opening checkout or hitting cancel and tight enough to blunt a script
# hammering either route once a bearer token is compromised (defensive
# review finding F6).
BILLING_RATE_LIMIT_PER_MIN = 20
_billing_limiter = ratelimit.FixedWindowLimiter(
    limit=BILLING_RATE_LIMIT_PER_MIN, window_s=60.0)
_rate_limited_billing = ratelimit.limiter_dependency(
    _billing_limiter, user_dependency=get_current_user)


class CheckoutRequest(BaseModel):
    plan_id: str


@router.post("/billing/checkout")
def create_checkout(body: CheckoutRequest,
                     current_user: User = Depends(get_current_user),
                     _rate_limit: None = Depends(_rate_limited_billing)) -> dict:
    """Start a checkout for the authed user. Returns a structured
    "not configured" body today (NullBillingProvider is the default, and
    StripeBillingProvider refuses without STRIPE_API_KEY) -- this is not
    an error response, it is the honest current state of billing per
    docs/LAUNCH_DECISIONS.md Decision 2, so it is a 200 with a status
    field rather than a 5xx a caller would need to specially handle.

    SERVER-SIDE PLAN ALLOWLIST (defensive review finding F1): body.plan_id
    is a client-supplied string and must never reach
    provider.create_checkout as the literal Stripe price -- a caller could
    otherwise name an arbitrary price id (someone else's plan, or a probe
    of Stripe's id namespace) and this app would unknowingly open a real
    checkout session against it. Only billing.BETA_PLAN_ID is accepted; it
    is resolved server-side to billing.beta_plan_stripe_price_id(), the
    exact same allowlist-then-resolve api/signup.py::_attempt_checkout
    already applies for the self-serve path, so calling this endpoint
    directly gets the identical guarantee.
    """
    if body.plan_id != billing.BETA_PLAN_ID:
        raise HTTPException(status_code=400, detail={
            "error": "unknown_plan",
            "message": f"{body.plan_id!r} is not a recognized plan id; "
                       f"expected {billing.BETA_PLAN_ID!r}"})
    price_id = billing.beta_plan_stripe_price_id()
    if not price_id:
        # Same honest "not configured" shape as every other billing gap --
        # the plan itself is real, Brey just hasn't created its Stripe
        # Price yet (see billing.ENV_STRIPE_BETA_PRICE_ID's own comment).
        return {"status": "not_configured",
                "message": "billing is not configured yet"}
    provider = billing.get_billing_provider()
    try:
        url = provider.create_checkout(current_user.id, price_id)
    except billing.BillingProviderNotConfigured as exc:
        return {"status": "not_configured", "message": str(exc)}
    except RuntimeError as exc:
        # Defensive review finding F3: StripeBillingProvider._call raises a
        # plain RuntimeError embedding Stripe's raw response body -- that
        # must never reach the caller verbatim (account-identifying detail
        # this endpoint has no business relaying), and must never surface
        # as an unhandled 500 either. Logged server-side only, the same
        # swallow-and-log shape events.record_event_safe uses, so the
        # failure is still visible to whoever reads stderr/logs.
        print(f"billing: checkout provider call failed for "
              f"user_id={current_user.id}: {exc!r}", file=sys.stderr, flush=True)
        return {"status": "error",
                "message": "checkout could not be started; try again shortly"}
    if not url:
        # NullBillingProvider's honest non-answer (see its docstring) --
        # same "not configured" shape as the exception path above, so a
        # caller checks one field regardless of which provider is active.
        return {"status": "not_configured",
                "message": "billing is not configured yet"}
    # A real checkout URL was actually handed back -- record the event
    # here, not the honest "not_configured" branches above, since those
    # never started a checkout.
    events.record_event_safe(current_user.id, events.CHECKOUT_STARTED)
    return {"status": "redirect", "checkout_url": url}


@router.get("/billing/status")
def billing_status(current_user: User = Depends(get_current_user)) -> dict:
    """The authed user's subscription status, read from
    src.appstate.customers' local table -- NEVER a live Stripe call. That
    is deliberate: this endpoint is meant to be safe to hit on every page
    load, and hitting Stripe's API on every page load would be both slow
    and something Stripe's rate limits would eventually punish. The table
    only ever reflects what a verified webhook has told this app (see
    src.appstate.billing.apply_stripe_webhook_event), so this is always at
    most as fresh as the last webhook delivery -- an honest lag, not a
    fabricated up-to-the-second answer.
    """
    record = customers.get_subscription_record(current_user.id)
    if record is None:
        # No webhook has ever reported a subscription for this user --
        # same "not_configured" shape create_checkout uses, so a caller
        # checks one field regardless of which endpoint answered it.
        return {"status": "not_configured"}
    return {"status": record["status"],
            "stripe_subscription_id": record["stripe_subscription_id"],
            # Stripe's "scheduled to cancel at period end" timestamp, when
            # the last webhook carried one (src.appstate.billing's
            # apply_stripe_webhook_event) -- None for a subscription with
            # no cancellation scheduled, same honest-absence shape as
            # everything else this endpoint reports.
            "cancel_at": record.get("cancel_at"),
            # The paid-through timestamp: what the customer keeps access
            # until after cancelling, and what the paid-surface gate
            # measures "expired" against (src.appstate.customers
            # .has_paid_access). None when no webhook/cancel response has
            # carried one -- absent stays absent, never a guessed date.
            "current_period_end": record.get("current_period_end"),
            "updated_at": record["updated_at"]}


@router.post("/billing/cancel")
def cancel_subscription(current_user: User = Depends(get_current_user),
                         _rate_limit: None = Depends(_rate_limited_billing)) -> dict:
    """Stop the authed user's subscription from renewing. Requires a local
    subscription record to already exist (same "not_configured" gate
    billing_status reads) -- there is nothing honest to cancel for a user
    billing has never reported a subscription for, real or test-mode.

    ACCESS IS NOT REVOKED HERE. Per the LINEHOUND paid-beta policy this is
    a SCHEDULED cancel: the customer keeps everything they already paid for
    through `current_period_end`, and only stops being entitled after that
    timestamp (src.appstate.customers.has_paid_access). That is why the
    response's `status` is usually still "active" with
    `cancel_at_period_end: true` -- Stripe's own model, reported straight
    rather than flattened into a "canceled" that would misdescribe a
    customer who still has three weeks of access left.

    Calls `provider.cancel()` (idempotent per its own protocol docstring --
    a double-click is safe) and then writes the result straight into
    src.appstate.customers itself, rather than waiting on Stripe's own
    `customer.subscription.deleted` webhook to arrive: in Stripe TEST MODE
    especially, a webhook endpoint not yet configured with a live
    `STRIPE_WEBHOOK_SECRET` (or a dashboard-registered endpoint pointed at
    this deploy) means that webhook may never arrive at all, which would
    leave GET /billing/status reporting a stale "active" subscription the
    user just canceled. Proactively updating here means the cancel button
    is correct immediately regardless of webhook delivery; a webhook that
    does arrive later just confirms (upserts) the same state again.
    """
    record = customers.get_subscription_record(current_user.id)
    if record is None:
        return {"status": "not_configured"}
    provider = billing.get_billing_provider()
    try:
        subscription = provider.cancel(current_user.id)
    except billing.BillingProviderNotConfigured as exc:
        return {"status": "not_configured", "message": str(exc)}
    except RuntimeError as exc:
        # Same F3 shape as checkout above: a live Stripe error must not reach
        # the caller verbatim or surface as an unhandled 500. Logged
        # server-side only.
        print(f"billing: cancel provider call failed for "
              f"user_id={current_user.id}: {exc!r}", file=sys.stderr, flush=True)
        return {"status": "error",
                "message": "cancellation could not be completed; try again shortly"}
    _persist(current_user.id, subscription)
    events.record_event_safe(current_user.id, events.SUBSCRIPTION_CANCELLED)
    return _subscription_body(subscription)


@router.post("/billing/reactivate")
def reactivate_subscription(current_user: User = Depends(get_current_user),
                             _rate_limit: None = Depends(_rate_limited_billing)) -> dict:
    """Undo a scheduled cancellation: renewal resumes, with no gap in
    access (cancel never took any away -- see its docstring). Mirrors
    POST /billing/cancel exactly, including the same "not_configured" gate,
    the same never-a-raw-500 error shaping, and the same
    write-the-result-locally-rather-than-wait-for-a-webhook rationale.

    Reachable by a customer whose paid period has ALREADY lapsed -- the
    paid-surface gate deliberately does not cover /billing/* -- but a
    subscription Stripe has actually ended cannot be resumed: the provider
    reports the canceled state back unchanged and this returns it, so the
    caller learns a new checkout is required instead of being told a
    reactivation happened that did not.
    """
    record = customers.get_subscription_record(current_user.id)
    if record is None:
        return {"status": "not_configured"}
    provider = billing.get_billing_provider()
    try:
        subscription = provider.reactivate(current_user.id)
    except billing.BillingProviderNotConfigured as exc:
        return {"status": "not_configured", "message": str(exc)}
    except RuntimeError as exc:
        # Same F3 shape as checkout/cancel above: a live Stripe error must
        # not reach the caller verbatim or surface as an unhandled 500.
        print(f"billing: reactivate provider call failed for "
              f"user_id={current_user.id}: {exc!r}", file=sys.stderr, flush=True)
        return {"status": "error",
                "message": "reactivation could not be completed; try again shortly"}
    _persist(current_user.id, subscription)
    return _subscription_body(subscription)


def _persist(user_id: int, subscription: billing.Subscription) -> None:
    """Write a provider response straight into the local table, rather than
    waiting on Stripe's own webhook -- see cancel_subscription's docstring
    for why (test mode especially may never deliver one). No provider_ref
    means no real provider subscription was touched (NullBillingProvider's
    honest non-answer), and there is nothing to record."""
    if not subscription.provider_ref:
        return
    customers.upsert_subscription(
        user_id, subscription.provider_ref, subscription.status,
        cancel_at=subscription.cancel_at,
        current_period_end=subscription.current_period_end)


def _subscription_body(subscription: billing.Subscription) -> dict:
    """One response shape for cancel and reactivate, so a client parses a
    single structure for both. `cancel_at_period_end` is the field that
    actually says whether renewal is stopped -- `status` stays "active"
    for a scheduled cancel, because the customer really is still active."""
    return {"status": subscription.status,
            "stripe_subscription_id": subscription.provider_ref,
            "cancel_at_period_end": subscription.cancel_at_period_end,
            "cancel_at": subscription.cancel_at,
            "current_period_end": subscription.current_period_end}


@router.post("/billing/webhook")
async def stripe_webhook(request: Request) -> dict:
    """Stripe webhook receiver. Verifies `Stripe-Signature` with
    src.appstate.billing.verify_stripe_webhook_signature when
    STRIPE_WEBHOOK_SECRET is set; otherwise returns a structured 501 --
    there is no provider live to have sent this webhook honestly, so
    accepting it (or silently 200-ing it) would be worse than refusing.

    No signature verification is attempted at all when unconfigured --
    doing so against an unset secret would either always-fail (safe but
    pointless) or, if implemented carelessly, always-pass. The 501 makes
    the "not configured" state explicit instead of relying on that.
    """
    secret = (os.environ.get(billing.ENV_STRIPE_WEBHOOK_SECRET) or "").strip()
    if not secret:
        raise HTTPException(status_code=501, detail={
            "error": "not_configured",
            "message": f"{billing.ENV_STRIPE_WEBHOOK_SECRET} not set -- "
                       "Stripe webhooks are not active yet"})
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    if not billing.verify_stripe_webhook_signature(payload, sig_header, secret):
        raise HTTPException(status_code=400, detail={
            "error": "invalid_signature",
            "message": "Stripe-Signature header missing or did not verify"})
    try:
        event = json.loads(payload.decode("utf-8")) if payload else {}
    except (ValueError, UnicodeDecodeError):
        # Signature verified but the body isn't valid JSON -- Stripe never
        # actually sends this, but failing to persist an un-parseable
        # event is not a reason to 500 (or re-raise) something whose
        # authenticity we've already confirmed; there is just nothing
        # structured to act on.
        event = {}
    billing.apply_stripe_webhook_event(event)
    return {"received": True}
