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
"""

from __future__ import annotations

import json
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.appstate import billing
from src.appstate import customers
from src.appstate.users import User

from api.auth import get_current_user

router = APIRouter()


class CheckoutRequest(BaseModel):
    plan_id: str


@router.post("/billing/checkout")
def create_checkout(body: CheckoutRequest,
                     current_user: User = Depends(get_current_user)) -> dict:
    """Start a checkout for the authed user. Returns a structured
    "not configured" body today (NullBillingProvider is the default, and
    StripeBillingProvider refuses without STRIPE_API_KEY) -- this is not
    an error response, it is the honest current state of billing per
    docs/LAUNCH_DECISIONS.md Decision 2, so it is a 200 with a status
    field rather than a 5xx a caller would need to specially handle.
    """
    provider = billing.get_billing_provider()
    try:
        url = provider.create_checkout(current_user.id, body.plan_id)
    except billing.BillingProviderNotConfigured as exc:
        return {"status": "not_configured", "message": str(exc)}
    if not url:
        # NullBillingProvider's honest non-answer (see its docstring) --
        # same "not configured" shape as the exception path above, so a
        # caller checks one field regardless of which provider is active.
        return {"status": "not_configured",
                "message": "billing is not configured yet"}
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
            "updated_at": record["updated_at"]}


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
