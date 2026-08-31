"""Billing ABSTRACTION only -- no real provider wired in.

docs/LAUNCH_DECISIONS.md (Decision 2) recommends Stripe but that requires
Brey's own Stripe account (business/bank/ID verification) and his explicit
sign-off before any code talks to a real payment API. This module exists
so the rest of the app (rate-limit-per-tier gating, the one-click-cancel
affordance named in the implementation plan §9) can be written against a
stable BillingProvider interface *today*, with a real provider slotting in
later behind the same interface -- no caller-side rewrite when that
happens.

NullBillingProvider is the only implementation here. It:
  - records every call it receives (for tests/inspection), and
  - always reports "not configured" -- it never pretends a subscription is
    active, never invents a checkout URL, never fabricates status.

NO CARD DATA, EVER. Nothing in this module accepts, stores, or forwards a
card number, CVV, or any other payment instrument. A real provider (once
chosen) handles that entirely on its own hosted checkout/portal -- this
app only ever sees a subscription id and a status string.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Protocol


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


class BillingProvider(Protocol):
    """The interface every billing provider (real or stub) implements.
    Callers program against this, never against a concrete provider, so
    swapping NullBillingProvider for a real Stripe-backed implementation
    later is a one-line wiring change, not a rewrite of every call site."""

    def create_checkout(self, user_id: int, plan_id: str) -> str:
        """Return a URL (or opaque reference) the user is sent to in order
        to start paying for plan_id. Real implementations call out to the
        provider; NullBillingProvider never does."""
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

    def create_checkout(self, user_id: int, plan_id: str) -> str:
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
