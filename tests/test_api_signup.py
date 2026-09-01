"""api/signup.py: POST /signup + GET /signup/complete.

Same "call the dependency/route functions directly, no TestClient" shape as
tests/test_api_auth.py and tests/test_api_billing.py -- see that module's
docstring for why. The full flow test drives signup -> a fake Stripe
checkout -> a signed webhook completing it -> the minted token
authenticating on GET /today's own dependency, all against one isolated
temp db and an injected transport, never a real network call.
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
    """Just enough of a FastAPI Request for the rate-limit dependency (a
    `.client.host`) -- same minimal shape tests/test_api_billing.py's
    _FakeRequest gives the webhook route."""

    def __init__(self, host: str = "203.0.113.5"):
        self.client = type("Client", (), {"host": host})()


WEBHOOK_SECRET = "whsec_synthetic_signup_secret"


def _signed_request(event: dict, secret: str = WEBHOOK_SECRET):
    from tests.test_api_billing import _FakeRequest as _WebhookRequest
    payload = json.dumps(event).encode("utf-8")
    ts = int(datetime.now(timezone.utc).timestamp())
    signed_payload = f"{ts}.".encode("utf-8") + payload
    sig = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return _WebhookRequest(payload, {"stripe-signature": f"t={ts},v1={sig}"})


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class SignupUnconfiguredBillingTests(unittest.TestCase):
    """No STRIPE_API_KEY / no STRIPE_BETA_PRICE_ID -- honest waitlist,
    never a fabricated checkout, and the user row still gets created."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._db_patcher = mock.patch.object(users_store, "db_path", lambda: self.db)
        self._db_patcher.start()
        self._env_patcher = mock.patch.dict(os.environ, {}, clear=False)
        self._env_patcher.start()
        os.environ.pop(billing.ENV_BILLING_PROVIDER, None)
        os.environ.pop(billing.ENV_STRIPE_API_KEY, None)
        os.environ.pop(billing.ENV_STRIPE_BETA_PRICE_ID, None)

    def tearDown(self):
        self._env_patcher.stop()
        self._db_patcher.stop()
        self._tmp.cleanup()

    def test_new_signup_is_honestly_waitlisted(self):
        from api.signup import SignupRequest, signup
        result = signup(SignupRequest(email="waiting@example.com"),
                        _rate_limit=None)
        self.assertEqual(result["status"], "waitlisted")
        user = users_store.get_user_by_email("waiting@example.com", db=self.db)
        self.assertIsNotNone(user)
        self.assertEqual(user.status, "waitlisted")

    def test_signup_records_signup_started_once(self):
        from api.signup import SignupRequest, signup
        with mock.patch.object(events, "record_event_safe") as safe:
            signup(SignupRequest(email="once@example.com"), _rate_limit=None)
        safe.assert_any_call(mock.ANY, events.SIGNUP_STARTED)

    def test_repeat_signup_is_idempotent_no_duplicate_user(self):
        from api.signup import SignupRequest, signup
        first = signup(SignupRequest(email="dup@example.com"), _rate_limit=None)
        second = signup(SignupRequest(email="dup@example.com"), _rate_limit=None)
        self.assertEqual(first["user_id"], second["user_id"])
        self.assertEqual(second["status"], "waitlisted")

    def test_repeat_signup_does_not_re_emit_signup_started(self):
        from api.signup import SignupRequest, signup
        signup(SignupRequest(email="onceonly@example.com"), _rate_limit=None)
        with mock.patch.object(events, "record_event_safe") as safe:
            signup(SignupRequest(email="onceonly@example.com"), _rate_limit=None)
        for call in safe.call_args_list:
            self.assertNotEqual(call.args[1], events.SIGNUP_STARTED)

    def test_invalid_email_is_400(self):
        from api.signup import SignupRequest, signup
        with self.assertRaises(HTTPException) as ctx:
            signup(SignupRequest(email="not-an-email"), _rate_limit=None)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_no_token_before_payment(self):
        """GET /signup/complete must never hand back a token for a session
        that never had a verified checkout.session.completed webhook."""
        from api.signup import signup_complete
        with self.assertRaises(HTTPException) as ctx:
            signup_complete(session_id="cs_never_happened")
        self.assertEqual(ctx.exception.status_code, 404)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class SignupRateLimitTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._db_patcher = mock.patch.object(users_store, "db_path", lambda: self.db)
        self._db_patcher.start()

    def tearDown(self):
        self._db_patcher.stop()
        self._tmp.cleanup()

    def test_more_than_ten_per_hour_from_one_ip_is_429(self):
        import api.signup as signup_module
        # Fresh limiter instance so this test's counter is isolated from
        # anything another test in this process already sent through the
        # module-level limiter.
        signup_module._signup_limiter = type(signup_module._signup_limiter)(
            limit=signup_module.SIGNUP_RATE_LIMIT_PER_HOUR, window_s=3600.0)
        request = _FakeRequest()
        for _ in range(signup_module.SIGNUP_RATE_LIMIT_PER_HOUR):
            signup_module._rate_limit_signup(request)  # must not raise
        with self.assertRaises(HTTPException) as ctx:
            signup_module._rate_limit_signup(request)
        self.assertEqual(ctx.exception.status_code, 429)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class SignupFullFlowTests(unittest.TestCase):
    """signup -> fake Stripe checkout -> signed webhook completes it ->
    user active -> minted token authenticates on a real authed route.
    Everything through the injected transport / signed-but-fake webhook
    body -- no real network call anywhere in this test.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._db_patcher = mock.patch.object(users_store, "db_path", lambda: self.db)
        self._db_patcher.start()
        self._env_patcher = mock.patch.dict(os.environ, {}, clear=False)
        self._env_patcher.start()
        os.environ[billing.ENV_STRIPE_WEBHOOK_SECRET] = WEBHOOK_SECRET
        os.environ[billing.ENV_STRIPE_BETA_PRICE_ID] = "price_test_beta_1"

    def tearDown(self):
        self._env_patcher.stop()
        self._db_patcher.stop()
        self._tmp.cleanup()

    def test_full_signup_to_active_to_cancel_flow(self):
        from api.signup import SignupRequest, signup, signup_complete

        # 1) Signup with a fake configured Stripe provider handing back a
        #    real-shaped checkout URl.
        with mock.patch.object(billing, "get_billing_provider") as get_provider:
            stub = mock.Mock()
            stub.create_checkout.return_value = "https://checkout.stripe.com/pay/cs_flow_1"
            get_provider.return_value = stub
            result = signup(SignupRequest(email="flow@example.com"), _rate_limit=None)

        self.assertIn("checkout", result)
        self.assertEqual(result["checkout"]["status"], "redirect")
        user_id = result["user_id"]
        pending = users_store.get_user(user_id, db=self.db)
        self.assertEqual(pending.status, "pending_payment")

        # 2) No token exists yet -- payment hasn't completed.
        with self.assertRaises(HTTPException):
            signup_complete(session_id="cs_flow_1")

        # 3) A verified checkout.session.completed webhook arrives.
        from api.billing import stripe_webhook
        completed_event = {
            "type": "checkout.session.completed",
            "data": {"object": {
                "id": "cs_flow_1",
                "client_reference_id": str(user_id),
                "customer": "cus_flow_1",
                "subscription": "sub_flow_1",
            }},
        }
        webhook_result = asyncio.run(stripe_webhook(_signed_request(completed_event)))
        self.assertEqual(webhook_result, {"received": True})

        activated = users_store.get_user(user_id, db=self.db)
        self.assertEqual(activated.status, "active")

        # 4) The one-time token bridge hands back a working bearer token.
        complete_result = signup_complete(session_id="cs_flow_1")
        self.assertEqual(complete_result["user_id"], user_id)
        raw_token = complete_result["token"]

        from api.auth import get_current_user
        authed_user = get_current_user(authorization=f"Bearer {raw_token}")
        self.assertEqual(authed_user.id, user_id)

        # The token is retrievable exactly once.
        with self.assertRaises(HTTPException):
            signup_complete(session_id="cs_flow_1")

        # 5) Cancellation reflects locally without waiting on another webhook.
        from api.billing import billing_status, cancel_subscription
        canceled = billing.Subscription(user_id=user_id, plan_id="beta",
                                        status="canceled", provider_ref="sub_flow_1")
        with mock.patch.object(billing, "get_billing_provider") as get_provider:
            stub = mock.Mock()
            stub.cancel.return_value = canceled
            get_provider.return_value = stub
            cancel_result = cancel_subscription(current_user=activated)
        self.assertEqual(cancel_result["status"], "canceled")
        status_after = billing_status(current_user=activated)
        self.assertEqual(status_after["status"], "canceled")


if __name__ == "__main__":
    unittest.main()
