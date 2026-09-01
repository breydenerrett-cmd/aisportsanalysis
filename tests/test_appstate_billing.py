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
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from src.appstate import billing


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
