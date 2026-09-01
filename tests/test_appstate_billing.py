"""src/appstate/billing.py: the billing ABSTRACTION, NullBillingProvider,
and StripeBillingProvider.

docs/LAUNCH_DECISIONS.md ("DECIDED BY BREY -- 2026-09-01", Decision 2)
picked Stripe; NullBillingProviderTests below still pin that the null
provider is honest about doing nothing, while StripeBillingProviderTests
pin that the real provider is equally honest when unconfigured, and
correct (idempotency key, request shape, response parsing) when it is --
all through an injected fake transport, never a live network call.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.appstate import billing
from src.appstate import customers
from src.appstate import events
from src.appstate import users as users_store


class NullBillingProviderTests(unittest.TestCase):

    def setUp(self):
        self.provider = billing.NullBillingProvider()

    def test_create_checkout_returns_no_real_url_but_records_the_intent(self):
        result = self.provider.create_checkout(1, "beta")
        self.assertEqual(result, "")
        intents = self.provider.recorded_intents()
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].method, "create_checkout")
        self.assertEqual(intents[0].user_id, 1)
        self.assertEqual(intents[0].plan_id, "beta")

    def test_subscription_status_is_honestly_not_configured(self):
        sub = self.provider.subscription_status(1)
        self.assertEqual(sub.status, "not_configured")
        self.assertIsNone(sub.provider_ref)

    def test_cancel_is_idempotent(self):
        first = self.provider.cancel(1)
        second = self.provider.cancel(1)
        self.assertEqual(first.status, "canceled")
        self.assertEqual(second.status, "canceled")
        # Calling cancel twice must not raise or double-record a failure --
        # it's what makes a one-click-cancel button safe to double-click.
        self.assertEqual(
            [i.method for i in self.provider.recorded_intents()],
            ["cancel", "cancel"])

    def test_cancel_then_status_reflects_canceled(self):
        self.provider.cancel(5)
        sub = self.provider.subscription_status(5)
        self.assertEqual(sub.status, "canceled")

    def test_intents_are_per_instance_not_global(self):
        other = billing.NullBillingProvider()
        self.provider.create_checkout(1, "beta")
        self.assertEqual(other.recorded_intents(), [])

    def test_protocol_methods_present(self):
        """BillingProvider is a Protocol -- this pins that
        NullBillingProvider actually implements its full shape, since
        Protocol conformance is structural and easy to silently drift
        from."""
        for method in ("create_checkout", "subscription_status", "cancel"):
            self.assertTrue(callable(getattr(self.provider, method)))


class _FakeTransport:
    """Records every call it receives and returns a queued response --
    the seam that keeps StripeBillingProvider's tests off the network."""

    def __init__(self):
        self.calls = []
        self._responses = []

    def queue(self, status_code, body_dict):
        self._responses.append(
            billing._TransportResponse(
                status_code=status_code,
                body=json.dumps(body_dict).encode("utf-8")))

    def __call__(self, method, url, headers, data):
        self.calls.append({"method": method, "url": url, "headers": headers, "data": data})
        return self._responses.pop(0)


class StripeBillingProviderNotConfiguredTests(unittest.TestCase):

    def setUp(self):
        self.transport = _FakeTransport()
        self.provider = billing.StripeBillingProvider(api_key="", transport=self.transport)

    def test_create_checkout_refuses_without_api_key(self):
        with self.assertRaises(billing.BillingProviderNotConfigured):
            self.provider.create_checkout(1, "price_beta")
        self.assertEqual(self.transport.calls, [], "must never touch the network unconfigured")

    def test_subscription_status_refuses_without_api_key(self):
        with self.assertRaises(billing.BillingProviderNotConfigured):
            self.provider.subscription_status(1)

    def test_cancel_refuses_without_api_key(self):
        with self.assertRaises(billing.BillingProviderNotConfigured):
            self.provider.cancel(1)

    def test_reads_api_key_from_env_when_not_passed_explicitly(self):
        with mock.patch.dict(os.environ, {billing.ENV_STRIPE_API_KEY: ""}):
            provider = billing.StripeBillingProvider(transport=self.transport)
            with self.assertRaises(billing.BillingProviderNotConfigured):
                provider.create_checkout(1, "price_beta")


class StripeBillingProviderConfiguredTests(unittest.TestCase):

    def setUp(self):
        self.transport = _FakeTransport()
        self.provider = billing.StripeBillingProvider(
            api_key="sk_test_synthetic", transport=self.transport)

    def test_create_checkout_posts_and_returns_the_hosted_url(self):
        self.transport.queue(200, {"id": "cs_test_123", "url": "https://checkout.stripe.com/test123"})
        url = self.provider.create_checkout(42, "price_beta")
        self.assertEqual(url, "https://checkout.stripe.com/test123")
        self.assertEqual(len(self.transport.calls), 1)
        call = self.transport.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], billing.STRIPE_API_BASE + "/v1/checkout/sessions")
        self.assertIn("Idempotency-Key", call["headers"])
        self.assertIn("Bearer sk_test_synthetic", call["headers"]["Authorization"])
        self.assertIn(b"client_reference_id=42", call["data"])

    def test_create_checkout_uses_a_caller_supplied_idempotency_key(self):
        self.transport.queue(200, {"id": "cs_test_1", "url": "https://checkout.stripe.com/1"})
        self.provider.create_checkout(1, "price_beta", idempotency_key="my-fixed-key")
        self.assertEqual(self.transport.calls[0]["headers"]["Idempotency-Key"], "my-fixed-key")

    def test_create_checkout_raises_on_stripe_error_response(self):
        self.transport.queue(402, {"error": {"message": "card declined"}})
        with self.assertRaises(RuntimeError):
            self.provider.create_checkout(1, "price_beta")

    def test_subscription_status_without_a_linked_customer_is_honestly_not_configured(self):
        sub = self.provider.subscription_status(7)
        self.assertEqual(sub.status, "not_configured")
        self.assertEqual(self.transport.calls, [])

    def test_subscription_status_with_linked_customer_reports_active(self):
        provider = billing.StripeBillingProvider(
            api_key="sk_test_synthetic", transport=self.transport,
            customer_ref_lookup=lambda user_id: "cus_test_1")
        self.transport.queue(200, {"data": [{
            "id": "sub_test_1", "status": "active",
            "items": {"data": [{"price": {"id": "price_beta"}}]},
        }]})
        sub = provider.subscription_status(7)
        self.assertEqual(sub.status, "active")
        self.assertEqual(sub.plan_id, "price_beta")
        self.assertEqual(sub.provider_ref, "sub_test_1")

    def test_cancel_is_idempotent_when_nothing_active(self):
        provider = billing.StripeBillingProvider(
            api_key="sk_test_synthetic", transport=self.transport,
            customer_ref_lookup=lambda user_id: None)
        first = provider.cancel(7)
        second = provider.cancel(7)
        self.assertEqual(first.status, "not_configured")
        self.assertEqual(second.status, "not_configured")
        self.assertEqual(self.transport.calls, [])

    def test_cancel_deletes_an_active_subscription(self):
        provider = billing.StripeBillingProvider(
            api_key="sk_test_synthetic", transport=self.transport,
            customer_ref_lookup=lambda user_id: "cus_test_1")
        self.transport.queue(200, {"data": [{
            "id": "sub_test_1", "status": "active",
            "items": {"data": [{"price": {"id": "price_beta"}}]},
        }]})
        self.transport.queue(200, {"id": "sub_test_1", "status": "canceled"})
        result = provider.cancel(7)
        self.assertEqual(result.status, "canceled")
        self.assertEqual(self.transport.calls[-1]["method"], "DELETE")


class StripeCheckoutPersistenceWiringTests(unittest.TestCase):
    """create_checkout wired to real src.appstate.customers persistence
    (the shape get_billing_provider() uses in production) -- pins customer
    create-or-reuse and idempotency-key reuse against a real temp db,
    still through the fake transport."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self.transport = _FakeTransport()
        self.provider = billing.StripeBillingProvider(
            api_key="sk_test_synthetic", transport=self.transport,
            customer_ref_lookup=lambda uid: customers.get_customer_ref(uid, db=self.db),
            on_customer_created=lambda uid, cid: customers.upsert_customer(uid, cid, db=self.db),
            idempotency_key_resolver=lambda uid, plan, gen: (
                customers.get_or_create_idempotency_key(uid, plan, gen, db=self.db)),
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_first_checkout_creates_and_persists_a_customer(self):
        self.transport.queue(200, {"id": "cus_new_1"})
        self.transport.queue(200, {"id": "cs_1", "url": "https://checkout.stripe.com/1"})
        self.provider.create_checkout(1, "price_beta")
        self.assertEqual(customers.get_customer_ref(1, db=self.db), "cus_new_1")
        self.assertEqual(self.transport.calls[0]["url"],
                          billing.STRIPE_API_BASE + "/v1/customers")
        self.assertIn("customer=cus_new_1", self.transport.calls[1]["data"].decode())

    def test_second_checkout_reuses_customer_not_a_duplicate(self):
        self.transport.queue(200, {"id": "cus_new_1"})
        self.transport.queue(200, {"id": "cs_1", "url": "https://checkout.stripe.com/1"})
        self.provider.create_checkout(1, "price_beta")
        self.transport.queue(200, {"id": "cs_2", "url": "https://checkout.stripe.com/2"})
        self.provider.create_checkout(1, "price_beta")
        # Only one /v1/customers POST across both calls -- the second
        # checkout must reuse the persisted customer, not mint another.
        customer_calls = [c for c in self.transport.calls if c["url"].endswith("/v1/customers")]
        self.assertEqual(len(customer_calls), 1)

    def test_retried_checkout_for_same_user_and_plan_reuses_idempotency_key(self):
        self.transport.queue(200, {"id": "cus_new_1"})
        self.transport.queue(200, {"id": "cs_1", "url": "https://checkout.stripe.com/1"})
        self.provider.create_checkout(1, "price_beta")
        first_key = self.transport.calls[-1]["headers"]["Idempotency-Key"]
        self.transport.queue(200, {"id": "cs_2", "url": "https://checkout.stripe.com/2"})
        self.provider.create_checkout(1, "price_beta")
        second_key = self.transport.calls[-1]["headers"]["Idempotency-Key"]
        self.assertEqual(first_key, second_key)


class StripeWebhookPersistenceTests(unittest.TestCase):
    """apply_stripe_webhook_event: the verified-signature-only persistence
    path from a Stripe event to src.appstate.customers' tables."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_checkout_completed_links_customer_and_activates_subscription(self):
        event = {
            "type": "checkout.session.completed",
            "data": {"object": {
                "client_reference_id": "42",
                "customer": "cus_1",
                "subscription": "sub_1",
            }},
        }
        billing.apply_stripe_webhook_event(event, db=self.db)
        self.assertEqual(customers.get_customer_ref(42, db=self.db), "cus_1")
        record = customers.get_subscription_record(42, db=self.db)
        self.assertEqual(record["status"], "active")
        self.assertEqual(record["stripe_subscription_id"], "sub_1")

    def test_checkout_completed_missing_client_reference_id_is_ignored(self):
        event = {"type": "checkout.session.completed",
                  "data": {"object": {"customer": "cus_1", "subscription": "sub_1"}}}
        billing.apply_stripe_webhook_event(event, db=self.db)
        self.assertIsNone(customers.get_customer_ref(1, db=self.db))

    def test_subscription_updated_transitions_existing_user_to_active(self):
        customers.upsert_customer(7, "cus_7", db=self.db)
        event = {
            "type": "customer.subscription.updated",
            "data": {"object": {"id": "sub_7", "customer": "cus_7", "status": "active"}},
        }
        billing.apply_stripe_webhook_event(event, db=self.db)
        record = customers.get_subscription_record(7, db=self.db)
        self.assertEqual(record["status"], "active")

    def test_subscription_updated_past_due_maps_to_canceled(self):
        customers.upsert_customer(7, "cus_7", db=self.db)
        event = {
            "type": "customer.subscription.updated",
            "data": {"object": {"id": "sub_7", "customer": "cus_7", "status": "past_due"}},
        }
        billing.apply_stripe_webhook_event(event, db=self.db)
        record = customers.get_subscription_record(7, db=self.db)
        self.assertEqual(record["status"], "canceled")

    def test_subscription_deleted_marks_canceled_regardless_of_status_field(self):
        customers.upsert_customer(7, "cus_7", db=self.db)
        customers.upsert_subscription(7, "sub_7", "active", db=self.db)
        event = {
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": "sub_7", "customer": "cus_7", "status": "active"}},
        }
        billing.apply_stripe_webhook_event(event, db=self.db)
        record = customers.get_subscription_record(7, db=self.db)
        self.assertEqual(record["status"], "canceled")

    def test_subscription_event_for_unmapped_customer_is_ignored(self):
        event = {
            "type": "customer.subscription.updated",
            "data": {"object": {"id": "sub_x", "customer": "cus_unmapped", "status": "active"}},
        }
        billing.apply_stripe_webhook_event(event, db=self.db)  # must not raise
        self.assertIsNone(customers.get_subscription_record(999, db=self.db))

    def test_unknown_event_type_is_ignored(self):
        billing.apply_stripe_webhook_event({"type": "invoice.paid", "data": {}}, db=self.db)

    def test_empty_event_is_ignored(self):
        billing.apply_stripe_webhook_event({}, db=self.db)

    def test_subscription_updated_carries_cancel_at_through(self):
        customers.upsert_customer(7, "cus_7", db=self.db)
        cancel_epoch = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp())
        event = {
            "type": "customer.subscription.updated",
            "data": {"object": {"id": "sub_7", "customer": "cus_7",
                                "status": "active", "cancel_at": cancel_epoch}},
        }
        billing.apply_stripe_webhook_event(event, db=self.db)
        record = customers.get_subscription_record(7, db=self.db)
        self.assertEqual(record["cancel_at"], "2026-10-01T00:00:00+00:00")

    def test_subscription_updated_without_cancel_at_clears_a_stale_value(self):
        customers.upsert_customer(7, "cus_7", db=self.db)
        customers.upsert_subscription(7, "sub_7", "active", cancel_at="2026-10-01T00:00:00+00:00",
                                      db=self.db)
        event = {
            "type": "customer.subscription.updated",
            "data": {"object": {"id": "sub_7", "customer": "cus_7", "status": "active"}},
        }
        billing.apply_stripe_webhook_event(event, db=self.db)
        record = customers.get_subscription_record(7, db=self.db)
        self.assertIsNone(record["cancel_at"])


class SignupActivationTests(unittest.TestCase):
    """checkout.session.completed's second job -- activating a self-serve
    signup (api/signup.py) -- lives in apply_stripe_webhook_event, not
    api/signup.py itself, since only the webhook path has a
    Stripe-verified payment to act on. See src/appstate/customers.py's
    signup_activation_tokens docstring for the one-time-retrieval contract
    pinned here."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self.user = users_store.create_user(
            "signup-activate@example.com", status="pending_payment", db=self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def _completed_event(self, session_id: str = "cs_test_1") -> dict:
        return {
            "type": "checkout.session.completed",
            "data": {"object": {
                "id": session_id,
                "client_reference_id": str(self.user.id),
                "customer": "cus_activate_1",
                "subscription": "sub_activate_1",
            }},
        }

    def test_activates_a_pending_payment_user(self):
        billing.apply_stripe_webhook_event(self._completed_event(), db=self.db)
        activated = users_store.get_user(self.user.id, db=self.db)
        self.assertEqual(activated.status, "active")

    def test_mints_a_one_time_token_the_activated_user_can_authenticate_with(self):
        billing.apply_stripe_webhook_event(self._completed_event(), db=self.db)
        result = customers.take_activation_token("cs_test_1", db=self.db)
        self.assertEqual(result["user_id"], self.user.id)
        resolved = users_store.authenticate(result["raw_token"], db=self.db)
        self.assertEqual(resolved.id, self.user.id)

    def test_token_retrieval_is_one_time_only(self):
        billing.apply_stripe_webhook_event(self._completed_event(), db=self.db)
        first = customers.take_activation_token("cs_test_1", db=self.db)
        self.assertIsNotNone(first)
        second = customers.take_activation_token("cs_test_1", db=self.db)
        self.assertIsNone(second)

    def test_unknown_session_id_never_yields_a_token(self):
        self.assertIsNone(customers.take_activation_token("cs_never_happened", db=self.db))

    def test_retried_webhook_delivery_does_not_mint_a_second_token(self):
        """Stripe does not guarantee exactly-once webhook delivery -- a
        second delivery of the same event must not invalidate whichever
        token the browser already fetched, or hand out a second, different
        one for the same signup."""
        billing.apply_stripe_webhook_event(self._completed_event(), db=self.db)
        first = customers.take_activation_token("cs_test_1", db=self.db)
        # Redeliver the same event (already-active user, same session id).
        billing.apply_stripe_webhook_event(self._completed_event(), db=self.db)
        second = customers.take_activation_token("cs_test_1", db=self.db)
        self.assertIsNotNone(first)
        self.assertIsNone(second, "a retried webhook must not mint a new token")

    def test_records_checkout_completed_event(self):
        with mock.patch.object(events, "record_event_safe") as safe:
            billing.apply_stripe_webhook_event(self._completed_event(), db=self.db)
        safe.assert_called_once_with(self.user.id, events.CHECKOUT_COMPLETED, db=self.db)

    def test_does_not_activate_an_already_active_user(self):
        active_user = users_store.create_user(
            "already-active@example.com", status="active", db=self.db)
        event = {
            "type": "checkout.session.completed",
            "data": {"object": {
                "id": "cs_test_active", "client_reference_id": str(active_user.id),
                "customer": "cus_x", "subscription": "sub_x",
            }},
        }
        billing.apply_stripe_webhook_event(event, db=self.db)
        still = users_store.get_user(active_user.id, db=self.db)
        self.assertEqual(still.status, "active")

    def test_unknown_user_id_in_event_is_a_harmless_no_op(self):
        event = {
            "type": "checkout.session.completed",
            "data": {"object": {
                "id": "cs_test_ghost", "client_reference_id": "999999",
                "customer": "cus_ghost", "subscription": "sub_ghost",
            }},
        }
        billing.apply_stripe_webhook_event(event, db=self.db)  # must not raise
        self.assertIsNone(customers.take_activation_token("cs_test_ghost", db=self.db))


class BetaPlanConfigTests(unittest.TestCase):
    """docs/PRICING_OFFER_VALIDATION.md's single-tier beta plan, expressed
    as overridable config -- see billing.beta_plan_stripe_price_id's own
    docstring for why STRIPE_BETA_PRICE_ID is checked separately from
    STRIPE_API_KEY."""

    def setUp(self):
        self._env_patcher = mock.patch.dict(os.environ, {}, clear=False)
        self._env_patcher.start()
        os.environ.pop(billing.ENV_STRIPE_BETA_PRICE_ID, None)

    def tearDown(self):
        self._env_patcher.stop()

    def test_no_price_id_configured_is_none(self):
        self.assertIsNone(billing.beta_plan_stripe_price_id())

    def test_reads_price_id_from_env(self):
        os.environ[billing.ENV_STRIPE_BETA_PRICE_ID] = "price_test_beta_1"
        self.assertEqual(billing.beta_plan_stripe_price_id(), "price_test_beta_1")

    def test_beta_plan_price_matches_the_pricing_doc_recommendation(self):
        # $19.99/mo, docs/PRICING_OFFER_VALIDATION.md section 1 -- pinned
        # here so a change to that number is a deliberate edit to this
        # constant, not a silent drift between the doc and the code.
        self.assertEqual(billing.BETA_PLAN_PRICE_CENTS, 1999)
        self.assertEqual(billing.BETA_PLAN.id, billing.BETA_PLAN_ID)


class BillingProviderFactoryTests(unittest.TestCase):

    def test_default_is_null(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(billing.ENV_BILLING_PROVIDER, None)
            provider = billing.get_billing_provider()
        self.assertIsInstance(provider, billing.NullBillingProvider)

    def test_explicit_stripe_selection(self):
        provider = billing.get_billing_provider("stripe")
        self.assertIsInstance(provider, billing.StripeBillingProvider)

    def test_unknown_provider_is_a_hard_error(self):
        with self.assertRaises(RuntimeError):
            billing.get_billing_provider("some_typo")

    def test_stripe_provider_is_wired_to_customers_persistence(self):
        """get_billing_provider("stripe") must not return the bare,
        storage-free StripeBillingProvider every other test in this file
        constructs directly -- it should already have a working
        customer_ref_lookup wired to src.appstate.customers."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "app.db"
            customers.upsert_customer(5, "cus_wired", db=db)
            provider = billing.get_billing_provider("stripe", db=db)
            self.assertEqual(provider._customer_ref_lookup(5), "cus_wired")


class StripeWebhookSignatureTests(unittest.TestCase):
    """HMAC-SHA256 verification per Stripe's documented scheme, using a
    synthetic secret this test controls -- never a real Stripe secret."""

    SECRET = "whsec_synthetic_test_secret"

    def _sign(self, payload: bytes, timestamp: int, secret: str = SECRET) -> str:
        signed_payload = f"{timestamp}.".encode("utf-8") + payload
        signature = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        return f"t={timestamp},v1={signature}"

    def test_valid_signature_verifies(self):
        payload = b'{"type": "checkout.session.completed"}'
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        header = self._sign(payload, int(now.timestamp()))
        self.assertTrue(
            billing.verify_stripe_webhook_signature(payload, header, self.SECRET, now=now))

    def test_wrong_secret_fails(self):
        payload = b'{"type": "checkout.session.completed"}'
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        header = self._sign(payload, int(now.timestamp()))
        self.assertFalse(
            billing.verify_stripe_webhook_signature(payload, header, "whsec_wrong", now=now))

    def test_tampered_payload_fails(self):
        payload = b'{"type": "checkout.session.completed"}'
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        header = self._sign(payload, int(now.timestamp()))
        tampered = b'{"type": "checkout.session.completed", "amount": 0}'
        self.assertFalse(
            billing.verify_stripe_webhook_signature(tampered, header, self.SECRET, now=now))

    def test_stale_timestamp_fails(self):
        payload = b"{}"
        signed_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
        header = self._sign(payload, int(signed_at.timestamp()))
        checked_at = signed_at + timedelta(minutes=10)
        self.assertFalse(
            billing.verify_stripe_webhook_signature(payload, header, self.SECRET, now=checked_at))

    def test_missing_header_fails(self):
        self.assertFalse(billing.verify_stripe_webhook_signature(b"{}", None, self.SECRET))

    def test_malformed_header_fails(self):
        self.assertFalse(
            billing.verify_stripe_webhook_signature(b"{}", "not-a-real-header", self.SECRET))

    def test_rotation_accepts_any_matching_v1_value(self):
        payload = b"{}"
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        ts = int(now.timestamp())
        real_sig = self._sign(payload, ts).split(",")[1]
        header = f"t={ts},v1=deadbeef,{real_sig}"
        self.assertTrue(
            billing.verify_stripe_webhook_signature(payload, header, self.SECRET, now=now))


if __name__ == "__main__":
    unittest.main()
