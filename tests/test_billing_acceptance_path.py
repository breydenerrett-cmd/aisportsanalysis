"""The buying path, end to end, as one buyer lives it.

Owner's acceptance path (2026-10-01): "checkout opens" is not the test.

    new user -> checkout -> payment success in test mode -> entitlement
    persisted -> user closes the success page -> user returns later ->
    access still works

plus: a duplicate webhook grants nothing twice; cancelling stops renewal and
keeps what was paid for; an expired entitlement is refused; a missing or
misconfigured billing environment fails out loud, never a silent waitlist
and never a session that takes a card it cannot honour; and getting back in
never depends on one browser tab staying open.

Everything runs through the real route functions and the real store, against
the in-process Stripe stand-in the funnel smoke test uses
(billing._fake_stripe_transport: synthetic key only, never a real request).
No live billing is touched and nothing here can reach Stripe.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sqlite3
from contextlib import closing
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

try:
    from fastapi import HTTPException
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.appstate import billing
from src.appstate import customers
from src.appstate import users as users_store

WEBHOOK_SECRET = "whsec_acceptance_synthetic"
ADMIN_TOKEN = "acceptance-admin-token"
FAR_FUTURE = billing.FAKE_TRANSPORT_CURRENT_PERIOD_END
SESSION = billing.FAKE_TRANSPORT_SESSION_ID
CUSTOMER = billing.FAKE_TRANSPORT_CUSTOMER_ID
SUBSCRIPTION = billing.FAKE_TRANSPORT_SUBSCRIPTION_ID

SELLING_ENV = {
    billing.ENV_BILLING_PROVIDER: "stripe",
    billing.ENV_STRIPE_API_KEY: billing.FAKE_TRANSPORT_KEY_PREFIX + "_acceptance",
    billing.ENV_STRIPE_FAKE_TRANSPORT: "1",
    billing.ENV_STRIPE_BETA_PRICE_ID: billing.FAKE_TRANSPORT_PRICE_ID,
    billing.ENV_STRIPE_WEBHOOK_SECRET: WEBHOOK_SECRET,
    billing.ENV_PUBLIC_BASE_URL: "https://linehound.test",
    billing.ENV_STRIPE_TRIAL_DAYS: "7",
    "APP_ADMIN_TOKEN": ADMIN_TOKEN,
}


def _epoch(moment: datetime) -> int:
    return int(moment.timestamp())


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class _Case(unittest.TestCase):
    ENV = SELLING_ENV

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "app.db"
        patcher = mock.patch.object(users_store, "db_path", lambda: self.db)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for name in SELLING_ENV:
            os.environ.pop(name, None)
        os.environ.update(self.ENV)
        os.environ.pop("APP_PUBLIC_DEMO", None)

    # -- the buyer's own actions, through the real routes -------------------

    def signup(self, email="buyer@example.com"):
        from api.signup import SignupRequest, signup
        return signup(SignupRequest(email=email), _rate_limit=None)

    def webhook(self, event: dict, secret: str = WEBHOOK_SECRET):
        from api.billing import stripe_webhook
        from tests.test_api_billing import _FakeRequest
        payload = json.dumps(event).encode("utf-8")
        stamp = _epoch(datetime.now(timezone.utc))
        signature = hmac.new(secret.encode("utf-8"), f"{stamp}.".encode("utf-8") + payload,
                             hashlib.sha256).hexdigest()
        request = _FakeRequest(payload, {"stripe-signature": f"t={stamp},v1={signature}"})
        return asyncio.run(stripe_webhook(request))

    def completed_event(self, user_id):
        return {"id": "evt_completed_1", "type": "checkout.session.completed",
                "data": {"object": {"id": SESSION, "client_reference_id": str(user_id),
                                    "customer": CUSTOMER, "subscription": SUBSCRIPTION,
                                    "payment_status": "no_payment_required"}}}

    def subscription_event(self, kind, status, *, period_end=FAR_FUTURE, cancel_at=None,
                           new_shape=False):
        obj = {"id": SUBSCRIPTION, "customer": CUSTOMER, "status": status,
               "cancel_at": cancel_at}
        if new_shape:   # Stripe API 2025-03-31 and later: the end is on the item
            obj["items"] = {"data": [{"current_period_end": period_end}]}
        else:
            obj["current_period_end"] = period_end
        return {"id": f"evt_{kind}_{status}", "type": f"customer.subscription.{kind}",
                "data": {"object": obj}}

    def collect_token(self, session_id=SESSION):
        from api.signup import signup_complete
        return signup_complete(session_id, _rate_limit=None)

    def open_paid_page(self, token):
        """What every paid route does first: authenticate, then entitlement."""
        from api.auth import get_current_user, require_paid_access
        user = get_current_user(authorization=f"Bearer {token}", request=None)
        return require_paid_access(current_user=user)

    def buy(self, email="buyer@example.com"):
        """signup -> Stripe test checkout -> both webhooks -> the token."""
        started = self.signup(email)
        self.assertEqual(started["checkout"]["status"], "redirect", started)
        user_id = started["user_id"]
        self.webhook(self.completed_event(user_id))
        self.webhook(self.subscription_event("created", "trialing"))
        return user_id, self.collect_token()["token"]

    def age_rows(self, table, column, delta, where=""):
        """Move stored timestamps into the past: time passing, without sleep."""
        moment = (datetime.now(timezone.utc) - delta).isoformat()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute(f"UPDATE {table} SET {column} = ? {where}", (moment,))


class BuyAndComeBack(_Case):
    def test_purchase_persists_and_access_survives_closing_the_page(self):
        started = self.signup()
        self.assertEqual(started["checkout"]["status"], "redirect")
        self.assertEqual(started["checkout"]["checkout_url"], billing.FAKE_TRANSPORT_CHECKOUT_URL)
        user_id = started["user_id"]

        # Before the webhook: paying has not happened, so nothing is granted.
        with self.assertRaises(HTTPException) as nothing_yet:
            self.collect_token()
        self.assertEqual(nothing_yet.exception.status_code, 404)

        self.assertEqual(self.webhook(self.completed_event(user_id)), {"received": True})
        self.webhook(self.subscription_event("created", "trialing"))

        # Entitlement is on disk, not in a browser.
        record = customers.get_subscription_record(user_id)
        self.assertEqual(record["status"], "trialing")
        self.assertEqual(record["stripe_subscription_id"], SUBSCRIPTION)
        self.assertTrue(customers.has_paid_access(user_id))
        self.assertEqual(users_store.get_user(user_id).status, "active")

        token = self.collect_token()["token"]
        self.assertEqual(self.open_paid_page(token).id, user_id)

        # The buyer closes the success page. The re-read window lapses and the
        # session id becomes worthless...
        self.age_rows("signup_activation_tokens", "retrieved_at", timedelta(minutes=11))
        with self.assertRaises(HTTPException) as closed:
            self.collect_token()
        self.assertEqual(closed.exception.status_code, 404)
        # ...and returning later with the token still works.
        self.assertEqual(self.open_paid_page(token).id, user_id)

    def test_a_reload_inside_the_window_gets_the_same_token(self):
        _, token = self.buy()
        self.assertEqual(self.collect_token()["token"], token)

    def test_the_buyer_who_closed_the_tab_before_the_token_arrived_can_come_back(self):
        # Paid, webhook landed, completion page never read. A day later the
        # same link (it is in the browser's history) still works.
        started = self.signup()
        self.webhook(self.completed_event(started["user_id"]))
        # A completed session alone grants no access (it carries no period);
        # the subscription event that follows it within a second does.
        self.webhook(self.subscription_event("created", "trialing"))
        self.age_rows("signup_activation_tokens", "created_at", timedelta(hours=24))
        token = self.collect_token()["token"]
        self.assertEqual(self.open_paid_page(token).id, started["user_id"])

    def test_the_period_end_is_recorded_from_either_stripe_shape(self):
        for new_shape in (False, True):
            with self.subTest(new_shape=new_shape):
                self.setUp()
                user_id, _ = self.buy()
                end = _epoch(datetime(2027, 1, 15, tzinfo=timezone.utc))
                self.webhook(self.subscription_event("updated", "active", period_end=end,
                                                     new_shape=new_shape))
                record = customers.get_subscription_record(user_id)
                self.assertEqual(record["current_period_end"][:10], "2027-01-15")


class DuplicateWebhook(_Case):
    def test_a_redelivered_payment_grants_nothing_twice(self):
        user_id, token = self.buy()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            tokens_before = conn.execute(
                "SELECT COUNT(*) FROM tokens WHERE user_id = ?", (user_id,)).fetchone()[0]
        for _ in range(3):
            self.webhook(self.completed_event(user_id))
            self.webhook(self.subscription_event("created", "trialing"))
        with closing(sqlite3.connect(self.db)) as conn, conn:
            tokens_after = conn.execute(
                "SELECT COUNT(*) FROM tokens WHERE user_id = ?", (user_id,)).fetchone()[0]
            sessions = conn.execute(
                "SELECT COUNT(*) FROM signup_activation_tokens").fetchone()[0]
            subscriptions = len(customers.list_subscription_rows())
        self.assertEqual(tokens_after, tokens_before)
        self.assertEqual(sessions, 1)
        self.assertEqual(subscriptions, 1)
        self.assertEqual(customers.get_subscription_record(user_id)["status"], "trialing")
        self.assertEqual(self.collect_token()["token"], token)

    def test_a_forged_or_unsigned_webhook_changes_nothing(self):
        started = self.signup()
        with self.assertRaises(HTTPException) as forged:
            self.webhook(self.completed_event(started["user_id"]), secret="whsec_wrong")
        self.assertEqual(forged.exception.status_code, 400)
        self.assertIsNone(customers.get_subscription_record(started["user_id"]))
        with self.assertRaises(HTTPException):
            self.collect_token()


class CancelAndExpiry(_Case):
    def _user(self, user_id):
        return users_store.get_user(user_id)

    def test_cancel_stops_renewal_and_keeps_what_was_paid_for(self):
        from api.billing import billing_status, cancel_subscription
        user_id, token = self.buy()
        result = cancel_subscription(current_user=self._user(user_id), _rate_limit=None)
        self.assertTrue(result["cancel_at_period_end"], result)
        status = billing_status(current_user=self._user(user_id))
        self.assertIsNotNone(status["cancel_at"], status)
        self.assertIsNotNone(status["current_period_end"], status)
        # Renewal is off; the period already paid for is still theirs.
        self.assertEqual(self.open_paid_page(token).id, user_id)

    def test_after_the_paid_period_access_is_refused_with_a_reason(self):
        user_id, token = self.buy()
        ended = _epoch(datetime.now(timezone.utc) - timedelta(hours=1))
        # Scheduled cancel whose period has now run out, before Stripe's
        # `deleted` event has even arrived. Time passing is what ends access
        # (the paid-through instant moves into the past); the announcement
        # alone never shortens or lengthens it.
        self.age_rows("billing_subscriptions", "paid_through", timedelta(hours=1))
        self.webhook(self.subscription_event("updated", "active", period_end=ended,
                                             cancel_at=ended))
        with self.assertRaises(HTTPException) as lapsed:
            self.open_paid_page(token)
        self.assertEqual(lapsed.exception.status_code, 402)
        self.assertEqual(lapsed.exception.detail["error"], "subscription_expired")
        # And after `deleted`.
        self.webhook(self.subscription_event("deleted", "canceled", period_end=ended))
        with self.assertRaises(HTTPException) as gone:
            self.open_paid_page(token)
        self.assertEqual(gone.exception.status_code, 402)

    def test_deleted_with_time_left_keeps_access_until_that_time(self):
        user_id, token = self.buy()
        later = _epoch(datetime.now(timezone.utc) + timedelta(days=3))
        self.webhook(self.subscription_event("deleted", "canceled", period_end=later))
        self.assertEqual(self.open_paid_page(token).id, user_id)

    def test_no_token_and_a_made_up_token_are_refused(self):
        self.buy()
        from api.auth import get_current_user
        for header in (None, "Bearer not-a-real-token", "Bearer "):
            with self.assertRaises(HTTPException) as refused:
                get_current_user(authorization=header, request=None)
            self.assertEqual(refused.exception.status_code, 401)


class RecoveryWithoutTheTab(_Case):
    def _reissue(self, **body):
        from api.admin import ReissueTokenRequest, reissue_subscriber_token
        return reissue_subscriber_token(ReissueTokenRequest(**body), _admin=None)

    def test_support_can_reissue_and_the_old_token_dies(self):
        user_id, old = self.buy("lost@example.com")
        self.age_rows("signup_activation_tokens", "retrieved_at", timedelta(days=30))
        fresh = self._reissue(email="  Lost@Example.com ")["token"]   # as support would paste it
        self.assertNotEqual(fresh, old)
        self.assertEqual(self.open_paid_page(fresh).id, user_id)
        from api.auth import get_current_user
        with self.assertRaises(HTTPException) as dead:
            get_current_user(authorization=f"Bearer {old}", request=None)
        self.assertEqual(dead.exception.status_code, 401)

    def test_a_buyer_who_never_saw_the_token_is_recoverable_after_the_link_dies(self):
        started = self.signup("never-read@example.com")
        self.webhook(self.completed_event(started["user_id"]))
        self.webhook(self.subscription_event("created", "trialing"))
        self.age_rows("signup_activation_tokens", "created_at", timedelta(hours=73))
        with self.assertRaises(HTTPException) as dead_link:
            self.collect_token()
        self.assertEqual(dead_link.exception.status_code, 404)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            leftover = conn.execute(
                "SELECT raw_token FROM signup_activation_tokens").fetchone()[0]
        self.assertIsNone(leftover, "an unread subscriber token was left readable at rest")
        fresh = self._reissue(user_id=started["user_id"])["token"]
        self.assertEqual(self.open_paid_page(fresh).id, started["user_id"])

    def test_reissue_refuses_someone_who_has_not_paid(self):
        started = self.signup("unpaid@example.com")
        with self.assertRaises(HTTPException) as refused:
            self._reissue(user_id=started["user_id"])
        self.assertEqual(refused.exception.status_code, 409)

    def test_reissue_needs_the_admin_token(self):
        from api.auth import _require_admin
        for header in (None, "wrong"):
            with self.assertRaises(HTTPException) as refused:
                _require_admin(x_admin_token=header)
            self.assertEqual(refused.exception.status_code, 401)
        self.assertIsNone(_require_admin(x_admin_token=ADMIN_TOKEN))


class BrokenBillingFailsOutLoud(_Case):
    """Each case removes ONE required setting from a deploy that is switched
    on. None may waitlist the buyer, none may open a checkout, and none may
    say checkout is on."""

    MISSING = (billing.ENV_STRIPE_API_KEY, billing.ENV_STRIPE_BETA_PRICE_ID,
               billing.ENV_STRIPE_WEBHOOK_SECRET, billing.ENV_PUBLIC_BASE_URL)

    def test_each_missing_setting_is_an_explicit_refusal_before_any_charge(self):
        for name in self.MISSING:
            with self.subTest(missing=name):
                self.setUp()
                os.environ.pop(name, None)
                calls = []
                real = billing._fake_stripe_transport

                def spy(method, url, headers, data):
                    calls.append((method, url))
                    return real(method, url, headers, data)

                with mock.patch.object(billing, "_fake_stripe_transport", spy):
                    result = self.signup(f"{name.lower()}@example.com")
                self.assertEqual(result["status"], "error", result)
                self.assertIn("nothing has been charged", result["message"])
                self.assertNotIn("checkout", result)
                self.assertNotIn(name, json.dumps(result))
                self.assertEqual(
                    [c for c in calls if c[1].endswith("/v1/checkout/sessions")], [],
                    "a checkout session was opened on a deploy that cannot honour it")
                self.assertEqual(billing.public_checkout_status(), "unavailable")

    def test_the_webhook_route_refuses_when_it_cannot_verify(self):
        os.environ.pop(billing.ENV_STRIPE_WEBHOOK_SECRET, None)
        with self.assertRaises(HTTPException) as refused:
            self.webhook(self.completed_event(1))
        self.assertEqual(refused.exception.status_code, 501)

    def test_health_reports_broken_not_ok(self):
        from src.appstate import apphealth
        os.environ.pop(billing.ENV_STRIPE_WEBHOOK_SECRET, None)
        checkout = apphealth.report()["checkout"]
        self.assertNotEqual(checkout["status"], "ok", checkout)
        self.assertNotIn("whsec", json.dumps(checkout))


class BillingSwitchedOff(_Case):
    ENV = {"APP_ADMIN_TOKEN": ADMIN_TOKEN}

    def test_off_says_so_and_never_promises_a_payment(self):
        result = self.signup("early@example.com")
        # The API names the state; the page words it ("Checkout is not open
        # yet. Your email is saved; nothing has been charged." in signup.js,
        # pinned by tests/test_checkout_copy_states.py).
        self.assertEqual(result["status"], "waitlisted", result)
        self.assertNotIn("checkout", result)
        self.assertEqual(billing.public_checkout_status(), "off")
        self.assertIsNone(customers.get_subscription_record(result["user_id"]))


if __name__ == "__main__":
    unittest.main()
