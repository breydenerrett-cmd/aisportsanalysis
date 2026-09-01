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
