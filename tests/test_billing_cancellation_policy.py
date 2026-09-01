"""The LINEHOUND paid-beta cancellation policy, end to end.

THE POLICY, RESTATED (it is what every test below pins):
  Cancelling stops RENEWAL. It does not take back what was already paid
  for -- the customer keeps paid access through Stripe's
  `current_period_end`, loses it after that timestamp, and reactivating
  before then resumes renewal with no gap in access at all.

Three layers get exercised because the policy is only true if all three
agree: src.appstate.billing (the Stripe call shape -- a scheduled cancel,
never an immediate DELETE), src.appstate.customers.has_paid_access (the one
entitlement decision, a pure local-table read), and the real api.app game
surface (a lapsed subscriber gets a structured 402 while /billing/* stays
reachable so they can reactivate).

Endpoint tests drive the REAL api.app over ASGI using the same request
helper shape as tests/test_api_surface_auth.py -- router-level dependencies
(which is where the paid gate lives) are invisible to direct route-function
calls, so nothing less would actually prove the gate is wired.

Every store is the suite's temp app db (tests/__init__.py redirects
APP_DB_PATH before any test module imports), and every Stripe call goes
through an injected fake transport. Nothing here touches a real store or a
real socket.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAVE_FASTAPI = True
except ImportError:
    HAVE_FASTAPI = False

from src.appstate import billing
from src.appstate import customers
from src.appstate import events
from src.appstate import users as users_store


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _epoch(moment: datetime) -> int:
    return int(moment.timestamp())


class _QueueTransport:
    """Same injected-transport shape tests/test_appstate_billing.py uses:
    canned responses in call order, every request recorded for assertions.
    A test that makes an unqueued call fails loudly rather than getting a
    fabricated default."""

    def __init__(self):
        self.calls = []
        self._queued = []

    def queue(self, status_code, body_dict):
        self._queued.append(billing._TransportResponse(
            status_code=status_code, body=json.dumps(body_dict).encode("utf-8")))

    def __call__(self, method, url, headers, data):
        self.calls.append({"method": method, "url": url, "data": data})
        if not self._queued:
            raise AssertionError(f"unqueued Stripe call: {method} {url}")
        return self._queued.pop(0)


class CancelKeepsAccessUntilPeriodEndTests(unittest.TestCase):
    """The provider-level half of the policy: what cancel actually asks
    Stripe for, and what the local record ends up saying."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._db_patcher = mock.patch.object(users_store, "db_path", lambda: self.db)
        self._db_patcher.start()
        self.now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        self.period_end = self.now + timedelta(days=27)
        self.transport = _QueueTransport()
        self.user = users_store.create_user(
            "policy@example.com", status="active", db=self.db)

    def tearDown(self):
        self._db_patcher.stop()
        self._tmp.cleanup()

    def _provider(self):
        return billing.StripeBillingProvider(
            api_key="sk_test_synthetic", transport=self.transport,
            customer_ref_lookup=lambda user_id: "cus_policy")

    def _queue_active_then_scheduled(self):
        self.transport.queue(200, {"data": [{
            "id": "sub_policy", "status": "active",
            "current_period_end": _epoch(self.period_end),
            "items": {"data": [{"price": {"id": "price_beta"}}]},
        }]})
        self.transport.queue(200, {
            "id": "sub_policy", "status": "active", "cancel_at_period_end": True,
            "cancel_at": _epoch(self.period_end),
            "current_period_end": _epoch(self.period_end)})

    def test_cancel_immediately_after_purchase_keeps_access_until_period_end(self):
        """(a) The worst case for an immediate-cancel bug: a customer who
        pays and cancels the same minute must still have the whole period
        they paid for."""
        customers.upsert_customer(self.user.id, "cus_policy", db=self.db)
        customers.upsert_subscription(self.user.id, "sub_policy", "active", db=self.db)
        self._queue_active_then_scheduled()
        result = self._provider().cancel(self.user.id)
        customers.upsert_subscription(
            self.user.id, result.provider_ref, result.status,
            cancel_at=result.cancel_at, current_period_end=result.current_period_end,
            db=self.db)
        self.assertTrue(customers.has_paid_access(
            self.user.id, now=self.now, db=self.db))

    def test_cancel_is_a_scheduled_stripe_call_never_an_immediate_delete(self):
        """The regression this whole module exists for: cancel used to be
        DELETE /v1/subscriptions/{id}, which ends access on the spot."""
        self._queue_active_then_scheduled()
        self._provider().cancel(self.user.id)
        methods = [call["method"] for call in self.transport.calls]
        self.assertNotIn("DELETE", methods)
        self.assertIn("cancel_at_period_end=true",
                      self.transport.calls[-1]["data"].decode("utf-8"))

    def test_cancel_mid_cycle_keeps_access_until_that_same_period_end(self):
        """(b) Mid-cycle cancel is the same story with a nearer boundary --
        the recorded period end is Stripe's, not a recomputed guess."""
        mid_cycle_end = self.now + timedelta(days=3)
        self.transport.queue(200, {"data": [{
            "id": "sub_policy", "status": "active",
            "current_period_end": _epoch(mid_cycle_end),
            "items": {"data": [{"price": {"id": "price_beta"}}]},
        }]})
        self.transport.queue(200, {
            "id": "sub_policy", "status": "active", "cancel_at_period_end": True,
            "cancel_at": _epoch(mid_cycle_end),
            "current_period_end": _epoch(mid_cycle_end)})
        result = self._provider().cancel(self.user.id)
        self.assertEqual(result.current_period_end, _iso(mid_cycle_end))
        customers.upsert_subscription(
            self.user.id, "sub_policy", result.status, cancel_at=result.cancel_at,
            current_period_end=result.current_period_end, db=self.db)
        self.assertTrue(customers.has_paid_access(
            self.user.id, now=mid_cycle_end - timedelta(hours=1), db=self.db))
        self.assertFalse(customers.has_paid_access(
            self.user.id, now=mid_cycle_end + timedelta(hours=1), db=self.db))


class EntitlementTests(unittest.TestCase):
    """(c)/(d) at the source: src.appstate.customers.has_paid_access is the
    ONE place entitlement is decided, so it is pinned directly rather than
    only through a route."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._db_patcher = mock.patch.object(users_store, "db_path", lambda: self.db)
        self._db_patcher.start()
        self.now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        self.period_end = self.now + timedelta(days=10)
        self.user = users_store.create_user(
            "entitle@example.com", status="active", db=self.db)

    def tearDown(self):
        self._db_patcher.stop()
        self._tmp.cleanup()

    def test_no_subscription_record_is_not_paid_access(self):
        """An invite-token beta user is NOT entitled by this function --
        api/auth.py's gate is what leaves them alone, deliberately, so this
        function never has to guess who is a paying customer."""
        self.assertFalse(customers.has_paid_access(
            self.user.id, now=self.now, db=self.db))

    def test_active_subscription_is_entitled(self):
        customers.upsert_subscription(self.user.id, "sub_1", "active", db=self.db)
        self.assertTrue(customers.has_paid_access(
            self.user.id, now=self.now, db=self.db))

    def test_trialing_subscription_is_entitled(self):
        customers.upsert_subscription(self.user.id, "sub_1", "trialing", db=self.db)
        self.assertTrue(customers.has_paid_access(
            self.user.id, now=self.now, db=self.db))

    def test_scheduled_cancel_stays_entitled_through_the_paid_period(self):
        """(c) Stripe still says "active" for a scheduled cancel -- the
        customer is mid-period and has lost nothing."""
        customers.upsert_subscription(
            self.user.id, "sub_1", "active", cancel_at=_iso(self.period_end),
            current_period_end=_iso(self.period_end), db=self.db)
        self.assertTrue(customers.has_paid_access(
            self.user.id, now=self.period_end - timedelta(seconds=1), db=self.db))

    def test_scheduled_cancel_expires_once_the_period_end_passes(self):
        """(d) ...and stops being entitled after it, even if Stripe's
        `customer.subscription.deleted` webhook has not landed yet. A
        webhook that never arrives must not extend paid access forever."""
        customers.upsert_subscription(
            self.user.id, "sub_1", "active", cancel_at=_iso(self.period_end),
            current_period_end=_iso(self.period_end), db=self.db)
        self.assertFalse(customers.has_paid_access(
            self.user.id, now=self.period_end + timedelta(seconds=1), db=self.db))

    def test_canceled_subscription_is_entitled_until_the_period_end(self):
        customers.upsert_subscription(
            self.user.id, "sub_1", "canceled",
            current_period_end=_iso(self.period_end), db=self.db)
        self.assertTrue(customers.has_paid_access(
            self.user.id, now=self.now, db=self.db))
        self.assertFalse(customers.has_paid_access(
            self.user.id, now=self.period_end + timedelta(days=1), db=self.db))

    def test_canceled_with_no_recorded_period_end_is_not_entitled(self):
        """Absent data stays absent: with no period end on record there is
        nothing to say this canceled customer paid through any date, and
        inventing one would be a fabrication in either direction."""
        customers.upsert_subscription(self.user.id, "sub_1", "canceled", db=self.db)
        self.assertFalse(customers.has_paid_access(
            self.user.id, now=self.now, db=self.db))

    def test_unparsable_period_end_never_raises(self):
        """This runs on every authed request of the game surface; a junk
        timestamp must degrade to not-entitled, never crash the route."""
        customers.upsert_subscription(
            self.user.id, "sub_1", "canceled", current_period_end="not-a-date",
            db=self.db)
        self.assertFalse(customers.has_paid_access(
            self.user.id, now=self.now, db=self.db))


class ReactivationTests(unittest.TestCase):
    """(e) Reactivating before expiration resumes renewal, with no gap."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._db_patcher = mock.patch.object(users_store, "db_path", lambda: self.db)
        self._db_patcher.start()
        self.now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        self.period_end = self.now + timedelta(days=10)
        self.transport = _QueueTransport()
        self.user = users_store.create_user(
            "reactivate@example.com", status="active", db=self.db)
        customers.upsert_customer(self.user.id, "cus_reactivate", db=self.db)

    def tearDown(self):
        self._db_patcher.stop()
        self._tmp.cleanup()

    def _provider(self):
        return billing.StripeBillingProvider(
            api_key="sk_test_synthetic", transport=self.transport,
            customer_ref_lookup=lambda user_id: "cus_reactivate")

    def test_reactivate_before_expiration_resumes_renewal_with_no_gap(self):
        customers.upsert_subscription(
            self.user.id, "sub_r", "active", cancel_at=_iso(self.period_end),
            current_period_end=_iso(self.period_end), db=self.db)
        # Entitled the whole time -- before the call and after it. That "no
        # gap" is the point: cancel never removed access, so reactivation
        # has nothing to restore, only renewal to resume.
        self.assertTrue(customers.has_paid_access(
            self.user.id, now=self.now, db=self.db))
        self.transport.queue(200, {"data": [{
            "id": "sub_r", "status": "active", "cancel_at_period_end": True,
            "cancel_at": _epoch(self.period_end),
            "current_period_end": _epoch(self.period_end),
            "items": {"data": [{"price": {"id": "price_beta"}}]},
        }]})
        self.transport.queue(200, {
            "id": "sub_r", "status": "active", "cancel_at_period_end": False,
            "cancel_at": None, "current_period_end": _epoch(self.period_end)})
        result = self._provider().reactivate(self.user.id)
        self.assertFalse(result.cancel_at_period_end)
        self.assertIsNone(result.cancel_at)
        customers.upsert_subscription(
            self.user.id, "sub_r", result.status, cancel_at=result.cancel_at,
            current_period_end=result.current_period_end, db=self.db)
        record = customers.get_subscription_record(self.user.id, db=self.db)
        self.assertIsNone(record["cancel_at"])
        # Renewal resumed: no scheduled cancel means the period end is no
        # longer an expiry date, so a date past it is still entitled.
        self.assertTrue(customers.has_paid_access(
            self.user.id, now=self.period_end + timedelta(days=1), db=self.db))

    def test_reactivating_an_ended_subscription_reports_it_rather_than_faking(self):
        """Stripe cannot resume a finished subscription; the honest answer
        is the canceled state, so the caller knows a new checkout is next."""
        self.transport.queue(200, {"data": [{
            "id": "sub_r", "status": "canceled",
            "items": {"data": [{"price": {"id": "price_beta"}}]},
        }]})
        result = self._provider().reactivate(self.user.id)
        self.assertEqual(result.status, "canceled")
        # Only the status read happened -- no write call was attempted.
        self.assertEqual(len(self.transport.calls), 1)


class WebhookIdempotencyTests(unittest.TestCase):
    """(f) Stripe does not guarantee exactly-once delivery, and retries for
    days. Applying the same event twice must leave the same state."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._db_patcher = mock.patch.object(users_store, "db_path", lambda: self.db)
        self._db_patcher.start()
        self.period_end = datetime(2026, 10, 1, tzinfo=timezone.utc)
        self.user = users_store.create_user(
            "webhookdupe@example.com", status="active", db=self.db)
        customers.upsert_customer(self.user.id, "cus_dupe", db=self.db)

    def tearDown(self):
        self._db_patcher.stop()
        self._tmp.cleanup()

    def _apply(self, event):
        billing.apply_stripe_webhook_event(event, db=self.db)

    def _scheduled_cancel_event(self):
        return {"type": "customer.subscription.updated",
                "data": {"object": {
                    "id": "sub_dupe", "customer": "cus_dupe", "status": "active",
                    "cancel_at_period_end": True,
                    "cancel_at": _epoch(self.period_end),
                    "current_period_end": _epoch(self.period_end)}}}

    def test_duplicate_scheduled_cancel_delivery_is_a_no_op(self):
        self._apply(self._scheduled_cancel_event())
        first = customers.get_subscription_record(self.user.id, db=self.db)
        self._apply(self._scheduled_cancel_event())
        second = customers.get_subscription_record(self.user.id, db=self.db)
        for field in ("stripe_subscription_id", "status", "cancel_at",
                      "current_period_end"):
            self.assertEqual(first[field], second[field])

    def test_duplicate_deleted_delivery_is_a_no_op(self):
        deleted = {"type": "customer.subscription.deleted",
                   "data": {"object": {
                       "id": "sub_dupe", "customer": "cus_dupe", "status": "active",
                       "current_period_end": _epoch(self.period_end)}}}
        self._apply(deleted)
        first = customers.get_subscription_record(self.user.id, db=self.db)
        self._apply(deleted)
        second = customers.get_subscription_record(self.user.id, db=self.db)
        self.assertEqual(first["status"], "canceled")
        self.assertEqual(first["current_period_end"], second["current_period_end"])
        self.assertEqual(first["status"], second["status"])

    def test_a_redelivered_checkout_session_never_unschedules_a_cancel(self):
        """The nastiest ordering Stripe can produce: the customer cancels,
        then a checkout.session.completed retry from hours earlier lands.
        It must not resurrect a renewing subscription (or wipe the paid-
        through timestamp entitlement is measured against)."""
        completed = {"type": "checkout.session.completed",
                     "data": {"object": {
                         "client_reference_id": str(self.user.id),
                         "customer": "cus_dupe", "subscription": "sub_dupe",
                         "id": "cs_dupe"}}}
        self._apply(completed)
        self._apply(self._scheduled_cancel_event())
        self._apply(completed)
        record = customers.get_subscription_record(self.user.id, db=self.db)
        self.assertEqual(record["cancel_at"], _iso(self.period_end))
        self.assertEqual(record["current_period_end"], _iso(self.period_end))


def _request(app, method, path, headers=None):
    """ASGI-level request against the real app -- the same helper shape as
    tests/test_api_surface_auth.py, because the paid gate is a router-level
    dependency that a direct route-function call would never run."""
    headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
        "query_string": b"", "headers": headers, "client": ("127.0.0.1", 11111),
        "server": ("testserver", 80),
    }
    captured = {}
    body_parts = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            captured["status"] = message["status"]
        elif message["type"] == "http.response.body":
            body_parts.append(message.get("body", b""))

    asyncio.new_event_loop().run_until_complete(app(scope, receive, send))
    raw = b"".join(body_parts)
    try:
        return captured.get("status"), json.loads(raw)
    except ValueError:
        return captured.get("status"), raw.decode("utf-8", "replace")


@unittest.skipUnless(HAVE_FASTAPI, "fastapi not installed")
class PaidSurfaceGateTests(unittest.TestCase):
    """(d) at the surface: an expired subscriber is refused the game
    surface with a structured 402 and still lets in an invite-token beta
    user, whose access this policy never touched.

    Runs against the suite's redirected APP_DB_PATH (tests/__init__.py) --
    api.app's dependencies resolve users_store.db_path() at call time
    inside the live app process, so an isolated temp db is not reachable
    from here the way it is in the unit tests above.
    """

    @classmethod
    def setUpClass(cls):
        from api.app import app
        cls.app = app

    def setUp(self):
        self.now = datetime.now(timezone.utc)

    def _authed_user(self, email):
        user = users_store.get_user_by_email(email) or users_store.create_user(
            email, status="active")
        return user, {"Authorization": f"Bearer {users_store.issue_invite_token(user.id)}"}

    def test_invite_beta_user_with_no_subscription_is_untouched(self):
        """The invite-token beta's whole user base has no billing row --
        the gate must let them straight through. Asserted against the
        dependency rather than over ASGI: letting a request through to the
        game routes means a live MLB fetch, which no unit test should do
        (the 402 cases below short-circuit before the route ever runs)."""
        from api.auth import require_paid_access
        user, _ = self._authed_user("gate-invite@example.com")
        self.assertIs(require_paid_access(current_user=user), user)

    def test_expired_subscriber_gets_a_structured_402_on_the_game_surface(self):
        user, headers = self._authed_user("gate-expired@example.com")
        customers.upsert_subscription(
            user.id, "sub_gate_expired", "canceled",
            cancel_at=_iso(self.now - timedelta(days=2)),
            current_period_end=_iso(self.now - timedelta(days=2)))
        for path in ("/today", "/games/2026-08-31", "/odds/2026-08-31"):
            status, body = _request(self.app, "GET", path, headers)
            self.assertEqual(status, 402, path)
            self.assertEqual(body["detail"]["error"], "subscription_expired", path)
        status, body = _request(self.app, "POST", "/betcheck", headers)
        self.assertEqual(status, 402)
        self.assertEqual(body["detail"]["error"], "subscription_expired")

    def test_subscriber_inside_the_paid_period_is_not_gated(self):
        """A customer who cancelled but is still inside the period they
        paid for keeps the game surface -- same reason as above for
        asserting the dependency directly rather than over ASGI."""
        from api.auth import require_paid_access
        user, _ = self._authed_user("gate-inside@example.com")
        customers.upsert_subscription(
            user.id, "sub_gate_inside", "active",
            cancel_at=_iso(self.now + timedelta(days=5)),
            current_period_end=_iso(self.now + timedelta(days=5)))
        self.assertIs(require_paid_access(current_user=user), user)

    def test_billing_stays_reachable_for_an_expired_subscriber(self):
        """The whole point of gating narrowly: an expired customer must
        still be able to see their status and reactivate/re-subscribe."""
        user, headers = self._authed_user("gate-billing@example.com")
        customers.upsert_subscription(
            user.id, "sub_gate_billing", "canceled",
            current_period_end=_iso(self.now - timedelta(days=1)))
        for method, path in (("GET", "/billing/status"),
                             ("POST", "/billing/cancel"),
                             ("POST", "/billing/reactivate")):
            status, _ = _request(self.app, method, path, headers)
            self.assertEqual(status, 200, f"{method} {path}")

    def test_support_stays_reachable_for_an_expired_subscriber(self):
        user, headers = self._authed_user("gate-support@example.com")
        customers.upsert_subscription(
            user.id, "sub_gate_support", "canceled",
            current_period_end=_iso(self.now - timedelta(days=1)))
        status, _ = _request(self.app, "POST", "/support", headers)
        self.assertNotEqual(status, 402)


@unittest.skipUnless(HAVE_FASTAPI, "fastapi not installed")
class ReactivateEndpointTests(unittest.TestCase):
    """POST /billing/reactivate mirrors POST /billing/cancel's error shapes
    -- an honest "not configured", never a raw 500 out of a Stripe error."""

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
            "reactivate-endpoint@example.com", status="active", db=self.db)

    def tearDown(self):
        self._env_patcher.stop()
        self._db_patcher.stop()
        self._tmp.cleanup()

    def test_no_subscription_record_is_not_configured(self):
        from api.billing import reactivate_subscription
        result = reactivate_subscription(current_user=self.user)
        self.assertEqual(result, {"status": "not_configured"})

    def test_stripe_without_api_key_is_not_configured_even_with_a_local_record(self):
        customers.upsert_subscription(self.user.id, "sub_1", "active", db=self.db)
        os.environ[billing.ENV_BILLING_PROVIDER] = "stripe"
        from api.billing import reactivate_subscription
        result = reactivate_subscription(current_user=self.user)
        self.assertEqual(result["status"], "not_configured")

    def test_provider_runtime_error_is_a_structured_response_not_a_500(self):
        customers.upsert_subscription(self.user.id, "sub_1", "active", db=self.db)
        with mock.patch.object(billing, "get_billing_provider") as get_provider:
            stub = mock.Mock()
            stub.reactivate.side_effect = RuntimeError(
                "Stripe API error 400: {'error': {'raw_body_marker': "
                "'should-never-reach-the-caller'}}")
            get_provider.return_value = stub
            from api.billing import reactivate_subscription
            result = reactivate_subscription(current_user=self.user)
        self.assertEqual(result["status"], "error")
        self.assertNotIn("should-never-reach-the-caller", str(result))

    def test_successful_reactivation_writes_local_state(self):
        customers.upsert_subscription(
            self.user.id, "sub_1", "active", cancel_at="2026-10-01T00:00:00+00:00",
            current_period_end="2026-10-01T00:00:00+00:00", db=self.db)
        resumed = billing.Subscription(
            user_id=self.user.id, plan_id="price_beta", status="active",
            provider_ref="sub_1", cancel_at_period_end=False, cancel_at=None,
            current_period_end="2026-10-01T00:00:00+00:00")
        with mock.patch.object(billing, "get_billing_provider") as get_provider:
            stub = mock.Mock()
            stub.reactivate.return_value = resumed
            get_provider.return_value = stub
            from api.billing import reactivate_subscription
            result = reactivate_subscription(current_user=self.user)
        self.assertFalse(result["cancel_at_period_end"])
        record = customers.get_subscription_record(self.user.id, db=self.db)
        self.assertIsNone(record["cancel_at"])
        self.assertEqual(record["current_period_end"], "2026-10-01T00:00:00+00:00")

    def test_successful_reactivation_records_its_own_event(self):
        """A cancel that was undone is its own moment in the funnel, not
        something an analyst has to infer from a churn that never arrived
        -- the same explicit-user-action-only rule POST /billing/cancel's
        SUBSCRIPTION_CANCELLED already follows."""
        customers.upsert_subscription(self.user.id, "sub_1", "active", db=self.db)
        resumed = billing.Subscription(
            user_id=self.user.id, plan_id="price_beta", status="active",
            provider_ref="sub_1", cancel_at_period_end=False)
        with mock.patch.object(billing, "get_billing_provider") as get_provider:
            stub = mock.Mock()
            stub.reactivate.return_value = resumed
            get_provider.return_value = stub
            from api.billing import reactivate_subscription
            with mock.patch.object(events, "record_event_safe") as safe:
                reactivate_subscription(current_user=self.user)
        safe.assert_called_once_with(self.user.id, events.SUBSCRIPTION_REACTIVATED)

    def test_a_not_configured_reactivation_records_nothing(self):
        from api.billing import reactivate_subscription
        with mock.patch.object(events, "record_event_safe") as safe:
            reactivate_subscription(current_user=self.user)
        safe.assert_not_called()


@unittest.skipUnless(HAVE_FASTAPI, "fastapi not installed")
class CancelEndpointPolicyTests(unittest.TestCase):
    """POST /billing/cancel reports the scheduled-cancel shape and records
    the paid-through timestamp -- the endpoint half of (a)."""

    SECRET = "whsec_synthetic_test_secret"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._db_patcher = mock.patch.object(users_store, "db_path", lambda: self.db)
        self._db_patcher.start()
        self._env_patcher = mock.patch.dict(os.environ, {}, clear=False)
        self._env_patcher.start()
        os.environ[billing.ENV_STRIPE_WEBHOOK_SECRET] = self.SECRET
        self.period_end = datetime(2026, 10, 1, tzinfo=timezone.utc)
        self.user = users_store.create_user(
            "cancel-policy@example.com", status="pending_payment", db=self.db)

    def tearDown(self):
        self._env_patcher.stop()
        self._db_patcher.stop()
        self._tmp.cleanup()

    def _signed_request(self, event):
        from tests.test_api_billing import _FakeRequest
        payload = json.dumps(event).encode("utf-8")
        ts = int(datetime.now(timezone.utc).timestamp())
        sig = hmac.new(self.SECRET.encode("utf-8"),
                       f"{ts}.".encode("utf-8") + payload, hashlib.sha256).hexdigest()
        return _FakeRequest(payload, {"stripe-signature": f"t={ts},v1={sig}"})

    def test_purchase_then_cancel_leaves_status_active_with_a_period_end(self):
        from api.billing import billing_status, cancel_subscription, stripe_webhook
        asyncio.run(stripe_webhook(self._signed_request({
            "type": "checkout.session.completed",
            "data": {"object": {"client_reference_id": str(self.user.id),
                                "customer": "cus_cp", "subscription": "sub_cp",
                                "id": "cs_cp"}}})))
        scheduled = billing.Subscription(
            user_id=self.user.id, plan_id="price_beta", status="active",
            provider_ref="sub_cp", cancel_at_period_end=True,
            cancel_at=_iso(self.period_end),
            current_period_end=_iso(self.period_end))
        with mock.patch.object(billing, "get_billing_provider") as get_provider:
            stub = mock.Mock()
            stub.cancel.return_value = scheduled
            get_provider.return_value = stub
            result = cancel_subscription(current_user=self.user)
        # "active" with cancel_at_period_end is the honest report: the
        # customer is still active, just no longer renewing.
        self.assertEqual(result["status"], "active")
        self.assertTrue(result["cancel_at_period_end"])
        status = billing_status(current_user=self.user)
        self.assertEqual(status["current_period_end"], _iso(self.period_end))
        self.assertTrue(customers.has_paid_access(
            self.user.id, now=self.period_end - timedelta(days=1), db=self.db))
        self.assertFalse(customers.has_paid_access(
            self.user.id, now=self.period_end + timedelta(days=1), db=self.db))


if __name__ == "__main__":
    unittest.main()
