"""Billing ABSTRACTION, plus a real (test-mode-ready) Stripe implementation.

docs/LAUNCH_DECISIONS.md ("DECIDED BY BREY -- 2026-09-01", Decision 2):
Stripe is the billing provider. Everything here is built and tested in
test mode behind the BillingProvider abstraction below; Brey connects the
real account (business/bank/ID verification -- a step that is his alone)
exactly when live credentials are needed. Until then, StripeBillingProvider
with no STRIPE_API_KEY behaves exactly like NullBillingProvider: an honest
refusal, never a fake success.

NullBillingProvider is the always-available fallback. It:
  - records every call it receives (for tests/inspection), and
  - always reports "not configured" -- it never pretends a subscription is
    active, never invents a checkout URL, never fabricates status.

StripeBillingProvider talks to https://api.stripe.com via stdlib urllib
(no `stripe` SDK -- src/ is stdlib-only, tests/test_api_boundary.py and
this task's grep-test enforce it). Every test exercises it through an
injected `transport` callable; nothing in tests/ reaches a real network
socket. See its class docstring for the exact Brey credential trigger.

NO CARD DATA, EVER. Nothing in this module accepts, stores, or forwards a
card number, CVV, or any other payment instrument. Stripe's own hosted
Checkout/Customer Portal handles that entirely -- this app only ever sees
a checkout URL, a subscription id, and a status string.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Protocol

from src.appstate import customers
from src.appstate import events
from src.appstate import users as users_store


@dataclass(frozen=True)
class Plan:
    """A billing plan as this app understands it -- not a payment-provider
    concept. `none` is the only free tier; `beta` is the (future) paid
    beta tier described in docs/LAUNCH_DECISIONS.md."""
    id: str
    name: str
    price_cents: Optional[int] = None  # None: price not yet decided/priced


@dataclass(frozen=True)
class Subscription:
    """A user's subscription state as this app understands it. `status`
    values mirror what a real provider (Stripe) would report: active,
    canceled, not_configured. `provider_ref` is the provider's own id for
    this subscription once one exists; None under NullBillingProvider."""
    user_id: int
    plan_id: str
    status: str  # "active" | "canceled" | "not_configured"
    provider_ref: Optional[str] = None
    created_at: Optional[str] = None


# ---------------------------------------------------------------------------
# The beta plan -- docs/PRICING_OFFER_VALIDATION.md's single-tier $19.99/mo
# beta recommendation. That doc's own header is explicit that nothing in it
# is customer-facing until Brey approves it; keeping the price as a named
# constant (not a hardcoded literal at each call site) is what makes it a
# one-line change instead of a hunt-and-replace once he does, or if he picks
# a different number.
# ---------------------------------------------------------------------------
BETA_PLAN_ID = "beta"
BETA_PLAN_PRICE_CENTS = 1999  # $19.99/mo -- PRICING_OFFER_VALIDATION.md, pending Brey sign-off
BETA_PLAN = Plan(id=BETA_PLAN_ID, name="Beta", price_cents=BETA_PLAN_PRICE_CENTS)

# Stripe checkout needs a real Stripe Price id (e.g. "price_..."), which is
# a different thing from BETA_PLAN_ID above -- BETA_PLAN_ID is this app's
# own name for the plan; this env var is Stripe's id for the Price object
# Brey creates in the Stripe dashboard/API once the account exists. Kept
# separate from ENV_STRIPE_API_KEY: a valid test-mode key with no price id
# still can't open a real checkout session (Stripe would reject "beta" as a
# price id), so api/signup.py treats either being unset as the same honest
# "billing not ready" state.
ENV_STRIPE_BETA_PRICE_ID = "STRIPE_BETA_PRICE_ID"


def beta_plan_stripe_price_id() -> Optional[str]:
    """The Stripe Price id for BETA_PLAN, or None if Brey has not created
    one yet and set STRIPE_BETA_PRICE_ID. See the env var's own comment
    above for why this is checked separately from STRIPE_API_KEY."""
    return (os.environ.get(ENV_STRIPE_BETA_PRICE_ID) or "").strip() or None


class BillingProvider(Protocol):
    """The interface every billing provider (real or stub) implements.
    Callers program against this, never against a concrete provider, so
    swapping NullBillingProvider for a real Stripe-backed implementation
    later is a one-line wiring change, not a rewrite of every call site."""

    def create_checkout(self, user_id: int, plan_id: str, *,
                         idempotency_key: Optional[str] = None) -> str:
        """Return a URL (or opaque reference) the user is sent to in order
        to start paying for plan_id. Real implementations call out to the
        provider; NullBillingProvider never does. `idempotency_key` lets a
        caller retry a failed network attempt without risking a duplicate
        checkout session -- optional because NullBillingProvider (and any
        provider not yet wired to a real payment API) has nothing for it
        to dedupe against."""
        ...

    def subscription_status(self, user_id: int) -> Subscription:
        """Current subscription state for user_id."""
        ...

    def cancel(self, user_id: int) -> Subscription:
        """Cancel user_id's subscription. Must be idempotent -- calling it
        on an already-canceled (or never-started) subscription is not an
        error, it just returns the resulting (already-)canceled state.
        This is what makes one-click cancel safe to wire to a button that
        might get double-clicked."""
        ...


@dataclass
class _RecordedIntent:
    """One call NullBillingProvider received, kept only in memory for
    tests/inspection -- never persisted, since it is not a real billing
    event and must never be mistaken for one."""
    method: str
    user_id: int
    plan_id: Optional[str]
    at: str


class NullBillingProvider:
    """Records intents locally; answers 'not configured' to everything.

    This is deliberately NOT a fake-success stub -- a stub that pretends
    checkout succeeded would let the rest of the app be built and tested
    against a lie ("subscriptions work!") that silently stops being true
    the moment a real user tries it before Stripe is wired. Every method
    here is honest that billing does not exist yet.
    """

    def __init__(self) -> None:
        self._intents: List[_RecordedIntent] = []
        self._canceled: set = set()

    def _record(self, method: str, user_id: int, plan_id: Optional[str] = None) -> None:
        self._intents.append(_RecordedIntent(
            method=method, user_id=user_id, plan_id=plan_id,
            at=datetime.now(timezone.utc).isoformat()))

    def create_checkout(self, user_id: int, plan_id: str, *,
                         idempotency_key: Optional[str] = None) -> str:
        self._record("create_checkout", user_id, plan_id)
        # No real checkout exists. The empty string (not a URL) is the
        # honest answer -- a caller that treats this as a redirect target
        # will visibly fail rather than silently "succeed" against nothing.
        return ""

    def subscription_status(self, user_id: int) -> Subscription:
        self._record("subscription_status", user_id)
        plan_id = "beta" if user_id in self._canceled else "none"
        status = "canceled" if user_id in self._canceled else "not_configured"
        return Subscription(user_id=user_id, plan_id=plan_id, status=status,
                             provider_ref=None, created_at=None)

    def cancel(self, user_id: int) -> Subscription:
        self._record("cancel", user_id)
        self._canceled.add(user_id)
        return Subscription(user_id=user_id, plan_id="beta", status="canceled",
                             provider_ref=None, created_at=None)

    def recorded_intents(self) -> List[_RecordedIntent]:
        """Everything this stub has been asked to do, in call order --
        for tests to assert against; not part of the BillingProvider
        protocol itself."""
        return list(self._intents)


# ---------------------------------------------------------------------------
# Stripe -- test-mode-ready, stdlib-only, never a live call in tests.
# ---------------------------------------------------------------------------

STRIPE_API_BASE = "https://api.stripe.com"
ENV_PUBLIC_BASE_URL = "PUBLIC_BASE_URL"

# Where Stripe sends the browser back after hosted Checkout. This is a
# DEPLOY-TIME fact (docs/LAUNCH_DECISIONS.md Decision 3) -- staging and a
# future production domain are different origins -- so it is read from the
# environment, never written into this module. Absent the env var the
# placeholder below still applies, which keeps every existing unit test's
# expectations intact and keeps this module honest about not guessing at a
# hostname it was never told.
DEFAULT_PUBLIC_BASE_URL = "https://example.invalid"


def _public_base_url() -> str:
    return ((os.environ.get(ENV_PUBLIC_BASE_URL) or "").strip().rstrip("/")
            or DEFAULT_PUBLIC_BASE_URL)


ENV_STRIPE_API_KEY = "STRIPE_API_KEY"
ENV_STRIPE_WEBHOOK_SECRET = "STRIPE_WEBHOOK_SECRET"

# Stripe recommends rejecting a webhook whose timestamp has drifted too far
# from "now" -- it is the only defense a signature check alone doesn't give
# you against a captured-and-replayed request. 5 minutes matches Stripe's
# own documented default tolerance.
DEFAULT_WEBHOOK_TOLERANCE = timedelta(minutes=5)


class BillingProviderNotConfigured(RuntimeError):
    """Raised by a real BillingProvider (StripeBillingProvider) when it
    lacks what it needs to make an honest call -- no STRIPE_API_KEY, or no
    local record yet linking a user to a Stripe customer. Mirrors
    src.appstate.authproviders.AuthProviderNotConfigured: never a fake
    success, just a typed refusal the api layer turns into a structured
    'not configured' response instead of a fabricated one."""


@dataclass(frozen=True)
class _TransportResponse:
    """What a transport call returns -- just enough for this module to
    parse Stripe's JSON and check the status code. Kept minimal so a test
    fake only has to construct this, not a real HTTP response object."""
    status_code: int
    body: bytes


def _urllib_transport(method: str, url: str, headers: Dict[str, str],
                       data: Optional[bytes]) -> _TransportResponse:
    """The only function in this module that touches a real socket.
    Never called by a test -- every StripeBillingProvider test injects its
    own `transport` callable (see class docstring), which is what keeps
    "test-mode-ready" honest rather than aspirational.
    """
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 -- fixed https host
            return _TransportResponse(status_code=response.status, body=response.read())
    except urllib.error.HTTPError as exc:
        # Stripe puts a useful JSON error body on 4xx/5xx responses;
        # urlopen raises instead of returning them, so this reshapes an
        # HTTPError back into the same _TransportResponse shape the 2xx
        # path returns -- one code path downstream handles both.
        return _TransportResponse(status_code=exc.code, body=exc.read())


# ---------------------------------------------------------------------------
# FUNNEL-SMOKE FAKE TRANSPORT -- scripts/funnel_smoke.sh's hook, nothing else.
#
# The server process scripts/funnel_smoke.sh drives is a real `uvicorn`
# subprocess -- there is no way for a script outside that process to inject
# a `transport` callable the way every unit test in this file does. This is
# the one env-gated substitute: a deterministic in-process fake that plays
# Stripe's part just well enough for the real signup->checkout->webhook-
# >activation->cancel path to run end to end with no network call and no
# real Stripe account, so the day Brey's real keys land the path underneath
# them is already proven, not merely unit-tested in isolation.
#
# GUARDED, NOT JUST DOCUMENTED, AGAINST EVER MASKING A REAL KEY: activation
# requires BOTH STRIPE_FAKE_TRANSPORT set AND STRIPE_API_KEY starting with
# FAKE_TRANSPORT_KEY_PREFIX -- a prefix no real Stripe key (test or live)
# can ever start with (`sk_test_...` / `sk_live_...` are Stripe's own
# formats). tests/test_appstate_billing.py's FakeTransportGuardTests pins
# that a real-shaped key falls straight through to _urllib_transport even
# with the env var set, and prints a loud stderr warning when it does, so a
# forgotten `STRIPE_FAKE_TRANSPORT=1` in a real environment is silently
# inert rather than a way to fabricate billing success.
# ---------------------------------------------------------------------------

ENV_STRIPE_FAKE_TRANSPORT = "STRIPE_FAKE_TRANSPORT"

FAKE_TRANSPORT_KEY_PREFIX = "sk_test_synthetic"

# Stable, deterministic ids/urls the fake transport always returns --
# exported so scripts/funnel_smoke.sh can construct a byte-exact
# checkout.session.completed webhook body that actually matches what
# create_checkout just "returned" from the SAME process run, without
# scraping stdout or a log file for it.
FAKE_TRANSPORT_CUSTOMER_ID = "cus_funnelsmoke_synthetic"
FAKE_TRANSPORT_SESSION_ID = "cs_funnelsmoke_synthetic"
FAKE_TRANSPORT_SUBSCRIPTION_ID = "sub_funnelsmoke_synthetic"
FAKE_TRANSPORT_PRICE_ID = "price_synthetic"
FAKE_TRANSPORT_CHECKOUT_URL = "https://checkout.stripe.example/funnelsmoke_synthetic"


def _fake_stripe_transport(method: str, url: str, headers: Dict[str, str],
                            data: Optional[bytes]) -> _TransportResponse:
    """Deterministic stand-in for _urllib_transport. Only ever installed by
    _maybe_fake_transport below (never reachable any other way), and only
    answers the exact four calls StripeBillingProvider makes along
    scripts/funnel_smoke.sh's path -- create a customer, open a checkout
    session, read that customer's subscriptions (POST /billing/cancel's
    pre-cancel status check), and delete a subscription. Anything else
    raises rather than fabricating a shape this hook was never designed to
    answer, since a silently-wrong canned response would be a worse bug
    than a loud one.
    """
    path = urllib.parse.urlparse(url).path
    if method == "POST" and path == "/v1/customers":
        body = {"id": FAKE_TRANSPORT_CUSTOMER_ID}
    elif method == "POST" and path == "/v1/checkout/sessions":
        body = {"id": FAKE_TRANSPORT_SESSION_ID, "url": FAKE_TRANSPORT_CHECKOUT_URL}
    elif method == "GET" and path == f"/v1/customers/{FAKE_TRANSPORT_CUSTOMER_ID}/subscriptions":
        body = {"data": [{
            "id": FAKE_TRANSPORT_SUBSCRIPTION_ID,
            "status": "active",
            "items": {"data": [{"price": {"id": FAKE_TRANSPORT_PRICE_ID}}]},
        }]}
    elif method == "DELETE" and path == f"/v1/subscriptions/{FAKE_TRANSPORT_SUBSCRIPTION_ID}":
        body = {"status": "canceled"}
    else:
        raise RuntimeError(
            f"funnel-smoke fake transport has no canned response for "
            f"{method} {path} -- it only plays the exact calls "
            "scripts/funnel_smoke.sh's flow makes")
    return _TransportResponse(status_code=200, body=json.dumps(body).encode("utf-8"))


def _maybe_fake_transport(api_key: str) -> Optional[
        Callable[[str, str, Dict[str, str], Optional[bytes]], _TransportResponse]]:
    """None unless BOTH STRIPE_FAKE_TRANSPORT is set AND api_key starts with
    FAKE_TRANSPORT_KEY_PREFIX -- see the section docstring above for why
    both, always. Logs loudly either way a real key is in play: activation
    prints that the fake is live (so a stray real request never looks like
    a silent hang), and a set-but-refused env var prints why, so a
    forgotten flag against a real key is visible, not a mystery.
    """
    if not (os.environ.get(ENV_STRIPE_FAKE_TRANSPORT) or "").strip():
        return None
    if not api_key.startswith(FAKE_TRANSPORT_KEY_PREFIX):
        print(
            f"billing: {ENV_STRIPE_FAKE_TRANSPORT} is set but "
            f"{ENV_STRIPE_API_KEY} does not start with "
            f"{FAKE_TRANSPORT_KEY_PREFIX!r} -- refusing to fake Stripe; "
            "using the real Stripe API instead.", file=sys.stderr, flush=True)
        return None
    print(
        "billing: STRIPE FAKE TRANSPORT ACTIVE -- scripts/funnel_smoke.sh's "
        f"in-process Stripe stand-in is live because {ENV_STRIPE_API_KEY} "
        f"starts with {FAKE_TRANSPORT_KEY_PREFIX!r} (a synthetic key that "
        "can never be a real Stripe credential). This must NEVER print in "
        "a real deploy.", file=sys.stderr, flush=True)
    return _fake_stripe_transport


class StripeBillingProvider:
    """Stripe-backed BillingProvider, built stdlib-only against
    api.stripe.com. Test-mode-ready per docs/LAUNCH_DECISIONS.md Decision
    2: build and test everything against Stripe's sandbox shape now, so
    the moment Brey provides a real STRIPE_API_KEY (test or live), this
    starts making real calls with no code change.

    EXACT BREY CREDENTIAL TRIGGER: STRIPE_API_KEY unset (or the account
    behind it not yet created -- business/bank/ID verification, which is
    Brey's step alone per Decision 2) is what keeps this provider refusing
    via BillingProviderNotConfigured. Setting a test-mode key unblocks
    sandbox testing without any account activation; a live key requires
    the account to actually exist.

    `customer_ref_lookup(user_id) -> Optional[str]` resolves a local user
    id to a Stripe customer id. It defaults to "no mapping exists" when
    not supplied -- the honest answer for a bare, unwired instance (every
    unit test in this file that constructs StripeBillingProvider directly
    gets this). get_billing_provider() below is what wires the real
    src.appstate.customers-backed lookup (plus `on_customer_created` and
    `idempotency_key_resolver`, same rationale) for actual requests, so
    direct construction stays a pure, storage-free unit under test while
    production wiring gets real persistence.

    `on_customer_created(user_id, stripe_customer_id)` is called once
    create_checkout creates a new Stripe customer for a user with no
    existing mapping -- None (the default) means "don't persist," which
    keeps create_checkout's older single-call behavior (no `/v1/customers`
    call, no `customer` field on the checkout session) for callers that
    never supply it.

    `idempotency_key_resolver(user_id, plan_id, generator) -> str` lets a
    caller reuse one Idempotency-Key across retried checkout attempts for
    the same (user_id, plan_id) instead of minting a fresh uuid4 every
    call -- see src.appstate.customers.get_or_create_idempotency_key,
    which is exactly this callable's shape. None (the default) always
    calls `generator()`, matching the old always-fresh-key behavior.
    """

    name = "stripe"

    def __init__(self, *, api_key: Optional[str] = None,
                 transport: Optional[Callable[[str, str, Dict[str, str], Optional[bytes]],
                                               _TransportResponse]] = None,
                 api_base: str = STRIPE_API_BASE,
                 customer_ref_lookup: Optional[Callable[[int], Optional[str]]] = None,
                 on_customer_created: Optional[Callable[[int, str], None]] = None,
                 idempotency_key_resolver: Optional[
                     Callable[[int, str, Callable[[], str]], str]] = None) -> None:
        self._api_key = api_key if api_key is not None else (
            os.environ.get(ENV_STRIPE_API_KEY) or "").strip()
        # An explicitly injected `transport` (every unit test in
        # test_appstate_billing.py) always wins; the fake only ever
        # substitutes for the real default, never for a caller's own.
        self._transport = (transport or _maybe_fake_transport(self._api_key)
                            or _urllib_transport)
        self._api_base = api_base
        self._customer_ref_lookup = customer_ref_lookup or (lambda user_id: None)
        self._on_customer_created = on_customer_created
        self._idempotency_key_resolver = idempotency_key_resolver

    def _require_configured(self) -> None:
        if not self._api_key:
            raise BillingProviderNotConfigured(
                f"{ENV_STRIPE_API_KEY} not set -- Stripe billing stays "
                "inactive until Brey connects a Stripe account and "
                "provides an API key (docs/LAUNCH_DECISIONS.md Decision "
                "2). This is the exact Brey credential trigger for "
                "billing.")

    def _call(self, method: str, path: str, *, form: Optional[Dict[str, str]] = None,
               idempotency_key: Optional[str] = None) -> dict:
        self._require_configured()
        headers = {"Authorization": f"Bearer {self._api_key}"}
        data = None
        if form is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            data = urllib.parse.urlencode(form).encode("utf-8")
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        response = self._transport(method, self._api_base + path, headers, data)
        body = json.loads(response.body.decode("utf-8")) if response.body else {}
        if response.status_code >= 400:
            raise RuntimeError(f"Stripe API error {response.status_code}: {body}")
        return body

    def create_checkout(self, user_id: int, plan_id: str, *,
                         idempotency_key: Optional[str] = None) -> str:
        """POST /v1/checkout/sessions for a subscription to plan_id,
        return its hosted URL.

        Idempotency-Key: an explicit `idempotency_key` argument always
        wins (a caller that needs to safely retry one specific attempt
        should generate its own key once and pass it every retry). Absent
        that, `idempotency_key_resolver` (see __init__ docstring) gets a
        chance to reuse a previously-stored key for this (user_id,
        plan_id); with no resolver wired, a fresh uuid4 is minted every
        call -- the original behavior, still what every direct-construction
        unit test in this file exercises.

        Customer: reuses an existing Stripe customer for user_id via
        `customer_ref_lookup` when one exists; otherwise, if
        `on_customer_created` is wired, creates one via POST /v1/customers
        and persists the mapping through that callback before continuing.
        With neither wired, the session carries no `customer` field and
        relies on `client_reference_id` alone, matching this method's
        behavior before src.appstate.customers existed.
        """
        self._require_configured()
        key = idempotency_key or self._resolve_idempotency_key(user_id, plan_id)
        customer_id = self._ensure_customer(user_id)
        form = {
            "mode": "subscription",
            "client_reference_id": str(user_id),
            "line_items[0][price]": plan_id,
            "line_items[0][quantity]": "1",
            # Redirect targets, resolved from PUBLIC_BASE_URL at call time
            # (see _public_base_url). `{CHECKOUT_SESSION_ID}` is Stripe's
            # own literal placeholder -- Stripe substitutes the real session
            # id into the redirect, and web/js/signup.js's SIGNUP COMPLETE
            # view trades that id for the one-time activation token via
            # GET /signup/complete. Without the placeholder the paying user
            # lands on a page with no way to learn their own token, which
            # is exactly the no-email-sender bridge api/signup.py describes.
            "success_url": (_public_base_url()
                            + "/web/index.html#/signup/complete"
                              "?session_id={CHECKOUT_SESSION_ID}"),
            "cancel_url": _public_base_url() + "/web/index.html#/signup",
        }
        if customer_id:
            form["customer"] = customer_id
        body = self._call("POST", "/v1/checkout/sessions", form=form, idempotency_key=key)
        return body.get("url", "") or ""

    def _resolve_idempotency_key(self, user_id: int, plan_id: str) -> str:
        generator = lambda: f"checkout:{user_id}:{plan_id}:{uuid.uuid4().hex}"  # noqa: E731
        if self._idempotency_key_resolver is None:
            return generator()
        return self._idempotency_key_resolver(user_id, plan_id, generator)

    def _ensure_customer(self, user_id: int) -> Optional[str]:
        existing = self._customer_ref_lookup(user_id)
        if existing:
            return existing
        if self._on_customer_created is None:
            # No persistence wired -- creating a customer we then have no
            # way to remember would just leave an orphaned Stripe customer
            # behind on every single checkout call. Better to not create
            # one at all and fall back to client_reference_id only.
            return None
        body = self._call("POST", "/v1/customers",
                           form={"metadata[app_user_id]": str(user_id)})
        customer_id = body.get("id")
        if customer_id:
            self._on_customer_created(user_id, customer_id)
        return customer_id

    def subscription_status(self, user_id: int) -> Subscription:
        self._require_configured()
        customer_ref = self._customer_ref_lookup(user_id)
        if not customer_ref:
            # No local record yet linking this user to a Stripe customer --
            # the honest answer is the same "not_configured" an
            # unconfigured provider gives, not a fabricated "no
            # subscription" that implies we actually checked with Stripe.
            return Subscription(user_id=user_id, plan_id="none", status="not_configured")
        body = self._call("GET", f"/v1/customers/{customer_ref}/subscriptions")
        subs = body.get("data") or []
        if not subs:
            return Subscription(user_id=user_id, plan_id="none", status="not_configured")
        sub = subs[0]
        items = ((sub.get("items") or {}).get("data")) or [{}]
        plan_id = (items[0].get("price") or {}).get("id", "none")
        status = "active" if sub.get("status") == "active" else "canceled"
        return Subscription(user_id=user_id, plan_id=plan_id, status=status,
                             provider_ref=sub.get("id"), created_at=None)

    def cancel(self, user_id: int) -> Subscription:
        """Idempotent, same contract as NullBillingProvider.cancel: calling
        this on an already-canceled or never-started subscription returns
        the resulting state rather than erroring."""
        self._require_configured()
        current = self.subscription_status(user_id)
        if current.status != "active" or not current.provider_ref:
            return current
        body = self._call("DELETE", f"/v1/subscriptions/{current.provider_ref}")
        return Subscription(user_id=user_id, plan_id=current.plan_id,
                             status="canceled" if body.get("status") != "active" else "active",
                             provider_ref=current.provider_ref, created_at=current.created_at)


def verify_stripe_webhook_signature(payload: bytes, sig_header: Optional[str], secret: str, *,
                                     tolerance: timedelta = DEFAULT_WEBHOOK_TOLERANCE,
                                     now: Optional[datetime] = None) -> bool:
    """Verify a Stripe webhook per Stripe's documented scheme: the
    `Stripe-Signature` header is `t=<unix ts>,v1=<hex hmac>[,v1=<hex
    hmac>...]` (multiple v1 values appear during secret rotation), and the
    signed payload is the literal byte string f"{t}.{raw body}" -- byte-
    exact, so a re-serialized/re-encoded body will never match. Returns
    False (never raises) for any malformed header, missing v1 value,
    stale timestamp, or mismatched signature: a webhook endpoint is an
    unauthenticated URL a hostile actor can freely hit and retry, so it
    must fail closed on ambiguity rather than throw a 500 that might leak
    which part of the check failed.

    Comparison is `hmac.compare_digest` (constant-time) against every v1
    value present -- not `==`, which would leak, via timing, how many
    leading hex characters of a forged signature happened to match.

    `now` is injectable for deterministic tests, the same pattern
    src.appstate.users.authenticate uses for token expiry.
    """
    if not sig_header or not secret:
        return False
    timestamp_str: Optional[str] = None
    v1_values: List[str] = []
    for item in sig_header.split(","):
        key, _, value = item.partition("=")
        key = key.strip()
        value = value.strip()
        if key == "t":
            timestamp_str = value
        elif key == "v1":
            v1_values.append(value)
    if not timestamp_str or not v1_values:
        return False
    try:
        event_epoch = int(timestamp_str)
    except ValueError:
        return False
    now = now or datetime.now(timezone.utc)
    event_time = datetime.fromtimestamp(event_epoch, tz=timezone.utc)
    if abs(now - event_time) > tolerance:
        return False
    signed_payload = f"{timestamp_str}.".encode("utf-8") + payload
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, candidate) for candidate in v1_values)


def _int_or_none(value: object) -> Optional[int]:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def apply_stripe_webhook_event(event: dict, *, db: Optional[Path] = None) -> None:
    """Persist the effect of one verified Stripe webhook event onto
    src.appstate.customers' tables. MUST be called only after
    api/billing.py has verified the event's signature -- this function
    trusts its input completely, the same way
    src.appstate.users.authenticate trusts a token only after its own
    hash check passes; it has no signature of its own to check.

    Handles the three events this app's billing model needs:
      - checkout.session.completed: links user_id (client_reference_id)
        to the Stripe customer id, records the new subscription as active
        if one was created (subscription mode), and activates a
        self-serve signup (see _activate_signup below) -- the
        pending_payment -> active transition and the one-time GET
        /signup/complete token both happen here, since this is the one
        place this app knows a real Stripe payment was verified.
      - customer.subscription.updated / customer.subscription.deleted:
        looks the event's customer id back up to a local user_id (the
        event itself never carries one) and overwrites that user's
        recorded status. `.deleted` is always recorded as "canceled"
        regardless of the object's own `status` field, since a deleted
        subscription is canceled by definition even if Stripe's payload
        still shows its last pre-deletion status. `cancel_at` (Stripe's
        "scheduled to cancel at period end" unix timestamp) rides along
        when present, so GET /billing/status can show it without a live
        Stripe call.

    Any other event type, or one of these missing the fields it needs
    (e.g. no local mapping yet for a subscription.updated whose
    checkout.session.completed hasn't been processed -- Stripe does not
    guarantee webhook delivery order), is silently ignored rather than
    raised: a webhook endpoint that 500s on a legitimate-but-unhandled
    event looks like an outage to Stripe's retry logic.
    """
    event_type = event.get("type")
    obj = ((event.get("data") or {}).get("object")) or {}
    if event_type == "checkout.session.completed":
        user_id = _int_or_none(obj.get("client_reference_id"))
        customer_id = obj.get("customer")
        subscription_id = obj.get("subscription")
        if user_id is None or not customer_id:
            return
        customers.upsert_customer(user_id, customer_id, db=db)
        if subscription_id:
            customers.upsert_subscription(user_id, subscription_id, "active", db=db)
        _activate_signup(user_id, obj.get("id"), db=db)
    elif event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
        customer_id = obj.get("customer")
        subscription_id = obj.get("id")
        if not customer_id or not subscription_id:
            return
        user_id = customers.get_user_id_by_customer_ref(customer_id, db=db)
        if user_id is None:
            return
        status = ("canceled" if event_type == "customer.subscription.deleted"
                  else ("active" if obj.get("status") == "active" else "canceled"))
        customers.upsert_subscription(
            user_id, subscription_id, status,
            cancel_at=_epoch_to_iso(obj.get("cancel_at")), db=db)


def _epoch_to_iso(epoch: object) -> Optional[str]:
    """Stripe's unix-epoch timestamps (e.g. `cancel_at`) as an ISO-8601 UTC
    string, or None for anything absent/malformed -- never raises, since a
    webhook payload is untrusted shape even after signature verification
    (the signature proves Stripe sent it, not that every field matches this
    app's assumptions)."""
    if epoch is None:
        return None
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _activate_signup(user_id: int, stripe_session_id: Optional[str], *,
                      db: Optional[Path] = None) -> None:
    """Transition a pending_payment self-serve signup to active and mint
    the one-time activation token GET /signup/complete hands back -- see
    src/appstate/customers.py's signup_activation_tokens docstring for why
    a token bridge exists here instead of an email sender (there isn't one
    yet; api/signup.py's module docstring documents that an email sender
    replaces this).

    Gated on customers.has_activation_token so a retried webhook delivery
    (Stripe does not guarantee exactly-once delivery) never mints a second
    token for the same checkout session, and a no-op for a user this
    session's client_reference_id doesn't resolve to (defensive; should
    never happen for an event this app itself generated the
    client_reference_id for).
    """
    user = users_store.get_user(user_id, db=db)
    if user is None:
        return
    if user.status == "pending_payment":
        users_store.set_user_status(user_id, "active", db=db)
    if not stripe_session_id or customers.has_activation_token(stripe_session_id, db=db):
        return
    raw_token = users_store.issue_invite_token(user_id, db=db)
    customers.record_activation_token(stripe_session_id, user_id, raw_token, db=db)
    events.record_event_safe(user_id, events.CHECKOUT_COMPLETED, db=db)


ENV_BILLING_PROVIDER = "BILLING_PROVIDER"
DEFAULT_BILLING_PROVIDER = "null"

_BILLING_PROVIDERS: Dict[str, Callable[[], "BillingProvider"]] = {
    DEFAULT_BILLING_PROVIDER: NullBillingProvider,
    StripeBillingProvider.name: StripeBillingProvider,
}


def get_billing_provider(name: Optional[str] = None, *,
                          db: Optional[Path] = None) -> "BillingProvider":
    """Construct the active BillingProvider. `name` overrides
    BILLING_PROVIDER for tests; production code omits it. Unset env ->
    NullBillingProvider (today's honest default -- no billing exists
    yet). An unrecognized value is a hard error, matching
    src.appstate.authproviders.get_provider's never-silently-fall-back
    rule: a typo here should not quietly keep billing turned off while
    looking configured.

    A StripeBillingProvider built here (as opposed to constructed
    directly, which every unit test in test_appstate_billing.py does) is
    wired to real src.appstate.customers persistence for
    customer_ref_lookup / on_customer_created / idempotency_key_resolver
    -- this is the one place production code gets a provider backed by
    the actual mapping table rather than the bare, storage-free defaults.
    `db` overrides the db file for tests that need an isolated one (see
    tests/test_api_billing.py's db_path monkeypatch, which this also
    respects since customers.py resolves db_path at call time, not
    import time).
    """
    selected = (name if name is not None else
                os.environ.get(ENV_BILLING_PROVIDER)) or DEFAULT_BILLING_PROVIDER
    selected = selected.strip()
    cls = _BILLING_PROVIDERS.get(selected)
    if cls is None:
        raise RuntimeError(
            f"unknown {ENV_BILLING_PROVIDER}: {selected!r}; valid values: "
            f"{sorted(_BILLING_PROVIDERS)}")
    if cls is StripeBillingProvider:
        return StripeBillingProvider(
            customer_ref_lookup=lambda user_id: customers.get_customer_ref(user_id, db=db),
            on_customer_created=lambda user_id, cust_id: customers.upsert_customer(
                user_id, cust_id, db=db),
            idempotency_key_resolver=lambda user_id, plan_id, generator: (
                customers.get_or_create_idempotency_key(user_id, plan_id, generator, db=db)),
        )
    return cls()
