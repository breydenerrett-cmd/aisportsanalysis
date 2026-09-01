"""api/billing.py: checkout + Stripe webhook endpoints.

Same skip-if-no-fastapi shape as tests/test_api_auth.py, and the same
"call the dependency functions directly, no TestClient" approach (see that
file's module docstring for why). Endpoints are async where FastAPI
requires it (the webhook reads request.body()); tests drive them with
asyncio.run.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

try:
    from fastapi import HTTPException
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.appstate import billing
from src.appstate import customers
from src.appstate import events
from src.appstate import users as users_store


class _FakeRequest:
    """Just enough of a FastAPI Request for stripe_webhook: an async
    .body() and a .headers mapping."""

    def __init__(self, body: bytes, headers: dict):
        self._body = body
        self.headers = headers

    async def body(self) -> bytes:
        return self._body


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class CheckoutEndpointTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._db_patcher = mock.patch.object(users_store, "db_path", lambda: self.db)
        self._db_patcher.start()
        self._env_patcher = mock.patch.dict(os.environ, {}, clear=False)
        self._env_patcher.start()
        os.environ.pop(billing.ENV_BILLING_PROVIDER, None)
        os.environ.pop(billing.ENV_STRIPE_API_KEY, None)
        self.user = users_store.create_user(
            "checkout@example.com", status="active", db=self.db)

    def tearDown(self):
        self._env_patcher.stop()
        self._db_patcher.stop()
        self._tmp.cleanup()

    def test_null_provider_reports_not_configured(self):
        from api.billing import CheckoutRequest, create_checkout
        result = create_checkout(CheckoutRequest(plan_id="beta"), current_user=self.user)
        self.assertEqual(result["status"], "not_configured")

    def test_stripe_without_api_key_reports_not_configured(self):
        os.environ[billing.ENV_BILLING_PROVIDER] = "stripe"
        from api.billing import CheckoutRequest, create_checkout
        result = create_checkout(CheckoutRequest(plan_id="beta"), current_user=self.user)
        self.assertEqual(result["status"], "not_configured")

    def test_unknown_billing_provider_is_a_hard_error(self):
        os.environ[billing.ENV_BILLING_PROVIDER] = "some_typo"
        from api.billing import CheckoutRequest, create_checkout
        with self.assertRaises(RuntimeError):
            create_checkout(CheckoutRequest(plan_id="beta"), current_user=self.user)

    def test_successful_checkout_records_checkout_started(self):
        with mock.patch.object(billing, "get_billing_provider") as get_provider:
            stub = mock.Mock()
            stub.create_checkout.return_value = "https://checkout.stripe.com/test123"
            get_provider.return_value = stub
            from api.billing import CheckoutRequest, create_checkout
            with mock.patch.object(events, "record_event_safe") as safe:
                result = create_checkout(CheckoutRequest(plan_id="beta"), current_user=self.user)
        self.assertEqual(result["status"], "redirect")
        safe.assert_called_once_with(self.user.id, events.CHECKOUT_STARTED)

    def test_not_configured_checkout_never_records_checkout_started(self):
        from api.billing import CheckoutRequest, create_checkout
        with mock.patch.object(events, "record_event_safe") as safe:
            create_checkout(CheckoutRequest(plan_id="beta"), current_user=self.user)
        safe.assert_not_called()


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class BillingStatusEndpointTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._db_patcher = mock.patch.object(users_store, "db_path", lambda: self.db)
        self._db_patcher.start()
        self.user = users_store.create_user(
            "status@example.com", status="active", db=self.db)

    def tearDown(self):
        self._db_patcher.stop()
        self._tmp.cleanup()

    def test_no_subscription_record_is_not_configured(self):
        from api.billing import billing_status
        result = billing_status(current_user=self.user)
        self.assertEqual(result, {"status": "not_configured"})

    def test_reports_status_from_the_table_not_a_live_call(self):
        customers.upsert_subscription(self.user.id, "sub_1", "active", db=self.db)
        from api.billing import billing_status
        result = billing_status(current_user=self.user)
        self.assertEqual(result["status"], "active")
        self.assertEqual(result["stripe_subscription_id"], "sub_1")

    def test_reflects_a_later_cancellation(self):
        customers.upsert_subscription(self.user.id, "sub_1", "active", db=self.db)
        customers.upsert_subscription(self.user.id, "sub_1", "canceled", db=self.db)
        from api.billing import billing_status
        result = billing_status(current_user=self.user)
        self.assertEqual(result["status"], "canceled")

    def test_reports_cancel_at_when_the_webhook_carried_one(self):
        customers.upsert_subscription(self.user.id, "sub_1", "active",
                                      cancel_at="2026-10-01T00:00:00+00:00", db=self.db)
        from api.billing import billing_status
        result = billing_status(current_user=self.user)
        self.assertEqual(result["cancel_at"], "2026-10-01T00:00:00+00:00")

    def test_cancel_at_is_none_when_the_webhook_never_carried_one(self):
        customers.upsert_subscription(self.user.id, "sub_1", "active", db=self.db)
        from api.billing import billing_status
        result = billing_status(current_user=self.user)
        self.assertIsNone(result["cancel_at"])


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class CancelEndpointTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._db_patcher = mock.patch.object(users_store, "db_path", lambda: self.db)
        self._db_patcher.start()
        self._env_patcher = mock.patch.dict(os.environ, {}, clear=False)
        self._env_patcher.start()
        os.environ.pop(billing.ENV_BILLING_PROVIDER, None)
        os.environ.pop(billing.ENV_STRIPE_API_KEY, None)
        self.user = users_store.create_user(
            "cancel@example.com", status="active", db=self.db)

    def tearDown(self):
        self._env_patcher.stop()
        self._db_patcher.stop()
        self._tmp.cleanup()

    def test_no_subscription_record_is_not_configured(self):
        from api.billing import cancel_subscription
        result = cancel_subscription(current_user=self.user)
        self.assertEqual(result, {"status": "not_configured"})

    def test_stripe_without_api_key_is_not_configured_even_with_a_local_record(self):
        # A local record can exist (e.g. from an earlier webhook) even if
        # STRIPE_API_KEY has since been unset -- cancel must still refuse
        # honestly rather than pretend it reached Stripe.
        customers.upsert_subscription(self.user.id, "sub_1", "active", db=self.db)
        os.environ[billing.ENV_BILLING_PROVIDER] = "stripe"
        from api.billing import cancel_subscription
        result = cancel_subscription(current_user=self.user)
        self.assertEqual(result["status"], "not_configured")

    def test_cancel_updates_local_state_and_records_the_event(self):
        customers.upsert_subscription(self.user.id, "sub_1", "active", db=self.db)
        # NullBillingProvider.cancel() never returns a provider_ref, so
        # exercise the persistence branch with a Stripe-shaped stand-in
        # instead (get_billing_provider mocked below).
        canceled = billing.Subscription(user_id=self.user.id, plan_id="beta",
                                        status="canceled", provider_ref="sub_1")
        with mock.patch.object(billing, "get_billing_provider") as get_provider:
            stub = mock.Mock()
            stub.cancel.return_value = canceled
            get_provider.return_value = stub
            from api.billing import cancel_subscription
            with mock.patch.object(events, "record_event_safe") as safe:
                result = cancel_subscription(current_user=self.user)
        self.assertEqual(result["status"], "canceled")
        record = customers.get_subscription_record(self.user.id, db=self.db)
        self.assertEqual(record["status"], "canceled")
        safe.assert_called_once_with(self.user.id, events.SUBSCRIPTION_CANCELLED)

    def test_cancel_is_safe_to_call_twice(self):
        customers.upsert_subscription(self.user.id, "sub_1", "active", db=self.db)
        canceled = billing.Subscription(user_id=self.user.id, plan_id="beta",
                                        status="canceled", provider_ref="sub_1")
        with mock.patch.object(billing, "get_billing_provider") as get_provider:
            stub = mock.Mock()
            stub.cancel.return_value = canceled
            get_provider.return_value = stub
            from api.billing import cancel_subscription
            first = cancel_subscription(current_user=self.user)
            second = cancel_subscription(current_user=self.user)
        self.assertEqual(first["status"], "canceled")
        self.assertEqual(second["status"], "canceled")


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class WebhookEndpointTests(unittest.TestCase):

    SECRET = "whsec_synthetic_test_secret"

    def setUp(self):
        self._env_patcher = mock.patch.dict(os.environ, {}, clear=False)
        self._env_patcher.start()
        os.environ.pop(billing.ENV_STRIPE_WEBHOOK_SECRET, None)

    def tearDown(self):
        self._env_patcher.stop()

    def _signed_headers(self, payload: bytes, secret: str = SECRET) -> dict:
        ts = int(datetime.now(timezone.utc).timestamp())
        signed_payload = f"{ts}.".encode("utf-8") + payload
        sig = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        return {"stripe-signature": f"t={ts},v1={sig}"}

    def test_unconfigured_secret_is_501(self):
        from api.billing import stripe_webhook
        request = _FakeRequest(b"{}", {})
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(stripe_webhook(request))
        self.assertEqual(ctx.exception.status_code, 501)

    def test_valid_signature_is_accepted(self):
        os.environ[billing.ENV_STRIPE_WEBHOOK_SECRET] = self.SECRET
        from api.billing import stripe_webhook
        payload = b'{"type": "checkout.session.completed"}'
        request = _FakeRequest(payload, self._signed_headers(payload))
        result = asyncio.run(stripe_webhook(request))
        self.assertEqual(result, {"received": True})

    def test_bad_signature_is_400(self):
        os.environ[billing.ENV_STRIPE_WEBHOOK_SECRET] = self.SECRET
        from api.billing import stripe_webhook
        request = _FakeRequest(b"{}", {"stripe-signature": "t=1,v1=deadbeef"})
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(stripe_webhook(request))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_missing_signature_header_is_400(self):
        os.environ[billing.ENV_STRIPE_WEBHOOK_SECRET] = self.SECRET
        from api.billing import stripe_webhook
        request = _FakeRequest(b"{}", {})
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(stripe_webhook(request))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_out_of_range_timestamp_header_is_400_not_500(self):
        # A forged Stripe-Signature carrying a wildly out-of-range unix
        # timestamp must be rejected as an invalid signature (400), never
        # crash the route into an unhandled 500. Regression: the verifier
        # used to raise OverflowError on such a header, which this
        # unauthenticated route did not catch.
        os.environ[billing.ENV_STRIPE_WEBHOOK_SECRET] = self.SECRET
        from api.billing import stripe_webhook
        request = _FakeRequest(
            b"{}", {"stripe-signature": "t=99999999999999999999,v1=deadbeef"})
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(stripe_webhook(request))
        self.assertEqual(ctx.exception.status_code, 400)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class WebhookPersistenceTests(unittest.TestCase):
    """A verified webhook must actually persist into
    src.appstate.customers, end to end through the route -- not just
    return {"received": True} -- and GET /billing/status must then see
    it, all against an isolated temp db."""

    SECRET = "whsec_synthetic_test_secret"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._db_patcher = mock.patch.object(users_store, "db_path", lambda: self.db)
        self._db_patcher.start()
        self._env_patcher = mock.patch.dict(os.environ, {}, clear=False)
        self._env_patcher.start()
        os.environ[billing.ENV_STRIPE_WEBHOOK_SECRET] = self.SECRET
        self.user = users_store.create_user(
            "webhook@example.com", status="active", db=self.db)

    def tearDown(self):
        self._env_patcher.stop()
        self._db_patcher.stop()
        self._tmp.cleanup()

    def _signed_request(self, event: dict) -> _FakeRequest:
        payload = json.dumps(event).encode("utf-8")
        ts = int(datetime.now(timezone.utc).timestamp())
        signed_payload = f"{ts}.".encode("utf-8") + payload
        sig = hmac.new(self.SECRET.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        return _FakeRequest(payload, {"stripe-signature": f"t={ts},v1={sig}"})

    def test_checkout_completed_persists_and_status_endpoint_reflects_it(self):
        from api.billing import billing_status, stripe_webhook
        event = {
            "type": "checkout.session.completed",
            "data": {"object": {
                "client_reference_id": str(self.user.id),
                "customer": "cus_wh_1",
                "subscription": "sub_wh_1",
            }},
        }
        result = asyncio.run(stripe_webhook(self._signed_request(event)))
        self.assertEqual(result, {"received": True})
        status = billing_status(current_user=self.user)
        self.assertEqual(status["status"], "active")
        self.assertEqual(status["stripe_subscription_id"], "sub_wh_1")

    def test_subsequent_cancellation_webhook_updates_status(self):
        from api.billing import billing_status, stripe_webhook
        completed = {
            "type": "checkout.session.completed",
            "data": {"object": {
                "client_reference_id": str(self.user.id),
                "customer": "cus_wh_2",
                "subscription": "sub_wh_2",
            }},
        }
        asyncio.run(stripe_webhook(self._signed_request(completed)))
        deleted = {
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": "sub_wh_2", "customer": "cus_wh_2", "status": "canceled"}},
        }
        asyncio.run(stripe_webhook(self._signed_request(deleted)))
        status = billing_status(current_user=self.user)
        self.assertEqual(status["status"], "canceled")


if __name__ == "__main__":
    unittest.main()
