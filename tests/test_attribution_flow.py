"""Acquisition attribution, end to end, and the rate-limit key.

The funnel could not say which channel produced a paying subscriber: every
anonymous event shared one id, and the UTM tags died on the landing page
(never reaching signup, the account row, Stripe or the paid event). These
tests follow one visitor's tags from the signup request to the Stripe Checkout
Session's metadata, the three server-side events, the admin funnel's
by-source table and the revenue report -- using the same injected fake Stripe
transport tests/test_appstate_billing.py uses (no network).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import tempfile
import unittest
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

try:
    from fastapi import HTTPException
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.appstate import attribution
from src.appstate import billing
from src.appstate import customers
from src.appstate import events
from src.appstate import ratelimit
from src.appstate import users as users_store
from tests.test_appstate_billing import _FakeTransport

WEBHOOK_SECRET = "whsec_synthetic_attribution_secret"
ANON = "0123456789abcdef0123456789abcdef"
TAGS = {"utm_source": "reddit", "utm_medium": "post", "utm_campaign": "launch",
        "utm_content": "hero", "utm_term": "mlb picks", "referrer_host": "old.reddit.com"}


class _DbCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "app.db"
        for module in (users_store, events):
            patcher = mock.patch.object(module, "db_path", lambda: self.db)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {
            billing.ENV_STRIPE_BETA_PRICE_ID: "price_attr_beta",
            billing.ENV_STRIPE_WEBHOOK_SECRET: WEBHOOK_SECRET,
            billing.ENV_PUBLIC_BASE_URL: "https://linehound.test",
        })
        env.start()
        self.addCleanup(env.stop)


class CleaningTests(unittest.TestCase):
    def test_keeps_the_known_keys_and_drops_the_rest(self):
        out = attribution.clean_attribution({**TAGS, "anon_id": ANON, "email": "a@b.co",
                                             "ip": "1.2.3.4"})
        self.assertEqual(out["utm_source"], "reddit")
        self.assertEqual(out["anon_id"], ANON)
        self.assertNotIn("email", out)
        self.assertNotIn("ip", out)

    def test_values_are_capped_and_bad_ones_dropped_individually(self):
        out = attribution.clean_attribution({
            "utm_source": "x" * 500, "utm_medium": "<script>alert(1)</script>",
            "utm_campaign": "spring_launch", "anon_id": "short"})
        self.assertEqual(len(out["utm_source"]), attribution.MAX_VALUE_LENGTH)
        self.assertNotIn("utm_medium", out)
        self.assertEqual(out["utm_campaign"], "spring_launch")
        self.assertNotIn("anon_id", out)

    def test_non_mappings_and_non_strings_are_empty(self):
        self.assertEqual(attribution.clean_attribution(None), {})
        self.assertEqual(attribution.clean_attribution("utm_source=x"), {})
        self.assertEqual(attribution.clean_attribution({"utm_source": 7}), {})


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class SignupToStripeToEventsTests(_DbCase):
    def _provider(self, transport):
        return billing.StripeBillingProvider(
            api_key="sk_test_synthetic", transport=transport,
            customer_ref_lookup=lambda uid: customers.get_customer_ref(uid, db=self.db),
            on_customer_created=lambda uid, cid: customers.upsert_customer(uid, cid, db=self.db))

    def _signup(self, email, attrs, transport):
        from api.signup import SignupRequest, signup
        with mock.patch.object(billing, "get_billing_provider",
                               return_value=self._provider(transport)):
            return signup(SignupRequest(email=email, attribution=attrs), _rate_limit=None)

    def _form(self, call):
        return urllib.parse.parse_qs(call["data"].decode("utf-8"))

    def _transport(self):
        transport = _FakeTransport()
        transport.queue(200, {"id": "cus_attr_1"})
        transport.queue(200, {"id": "cs_attr_1", "url": "https://checkout.stripe.com/attr1"})
        return transport

    def test_tags_reach_the_stripe_checkout_session_metadata(self):
        transport = self._transport()
        result = self._signup("attr@example.com", {**TAGS, "anon_id": ANON}, transport)
        self.assertEqual(result["checkout"]["status"], "redirect")
        session_call = [c for c in transport.calls if c["url"].endswith("/v1/checkout/sessions")][0]
        form = self._form(session_call)
        self.assertEqual(form["metadata[utm_source]"], ["reddit"])
        self.assertEqual(form["metadata[utm_campaign]"], ["launch"])
        self.assertEqual(form["metadata[referrer_host]"], ["old.reddit.com"])
        self.assertEqual(form["metadata[anon_id]"], [ANON])
        self.assertEqual(form["subscription_data[metadata][utm_source]"], ["reddit"])
        self.assertEqual(form["metadata[app_user_id]"], [str(result["user_id"])])

    def _idempotency_key(self, transport):
        call = [c for c in transport.calls if c["url"].endswith("/v1/checkout/sessions")][0]
        return {k.lower(): v for k, v in call["headers"].items()}["idempotency-key"]

    def test_the_idempotency_key_is_the_buyers_own_not_an_attribution_field(self):
        # Found by review, 2026-10-01: a loop variable named `key` replaced
        # the Idempotency-Key with the last attribution field name, so every
        # web buyer sent "anon_id" and Stripe would refuse the second one.
        first, second = self._transport(), _FakeTransport()
        second.queue(200, {"id": "cus_attr_2"})
        second.queue(200, {"id": "cs_attr_2", "url": "https://checkout.stripe.com/attr2"})
        a = self._signup("idem-a@example.com", {**TAGS, "anon_id": ANON}, first)
        b = self._signup("idem-b@example.com", {**TAGS, "anon_id": "d" * 32}, second)
        key_a, key_b = self._idempotency_key(first), self._idempotency_key(second)
        for key in (key_a, key_b):
            self.assertNotIn(key, ("anon_id", "utm_source", "utm_medium",
                                   "utm_campaign", "referrer_host"))
        self.assertIn(str(a["user_id"]), key_a)
        self.assertIn(str(b["user_id"]), key_b)
        self.assertNotEqual(key_a, key_b)

    def test_account_created_and_checkout_started_carry_the_tags(self):
        self._signup("attr2@example.com", {**TAGS, "anon_id": ANON}, self._transport())
        by_kind = {e.kind: e for e in events.list_events(db=self.db)}
        for kind in (events.ACCOUNT_CREATED, events.CHECKOUT_STARTED):
            with self.subTest(kind=kind):
                self.assertEqual(by_kind[kind].properties["utm_source"], "reddit")
                self.assertEqual(by_kind[kind].properties["utm_medium"], "post")

    def test_checkout_completed_carries_the_tags_after_the_webhook(self):
        from api.billing import stripe_webhook
        from tests.test_api_signup import _signed_request
        result = self._signup("attr3@example.com", {**TAGS, "anon_id": ANON}, self._transport())
        with mock.patch("tests.test_api_signup.WEBHOOK_SECRET", WEBHOOK_SECRET):
            request = _signed_request({
                "type": "checkout.session.completed",
                "data": {"object": {"id": "cs_attr_1", "client_reference_id": str(result["user_id"]),
                                    "customer": "cus_attr_1", "subscription": "sub_attr_1"}}},
                secret=WEBHOOK_SECRET)
        asyncio.run(stripe_webhook(request))
        completed = [e for e in events.list_events(db=self.db)
                     if e.kind == events.CHECKOUT_COMPLETED]
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].properties["utm_source"], "reddit")
        self.assertEqual(completed[0].properties["utm_campaign"], "launch")

    def test_first_touch_wins_on_a_repeat_signup(self):
        self._signup("attr4@example.com", {"utm_source": "reddit"}, self._transport())
        transport = _FakeTransport()
        transport.queue(200, {"id": "cs_attr_2", "url": "https://checkout.stripe.com/attr2"})
        result = self._signup("attr4@example.com", {"utm_source": "twitter"}, transport)
        self.assertEqual(
            customers.get_signup_attribution(result["user_id"], db=self.db)["utm_source"],
            "reddit")
        form = self._form([c for c in transport.calls if c["url"].endswith("/v1/checkout/sessions")][0])
        self.assertEqual(form["metadata[utm_source]"], ["reddit"],
                         "a retried checkout must carry the same metadata as the first")

    def test_a_direct_signup_stores_no_row_and_adds_no_metadata(self):
        transport = self._transport()
        result = self._signup("direct@example.com", None, transport)
        self.assertEqual(customers.get_signup_attribution(result["user_id"], db=self.db), {})
        form = self._form([c for c in transport.calls if c["url"].endswith("/v1/checkout/sessions")][0])
        self.assertNotIn("metadata[utm_source]", form)
        account = [e for e in events.list_events(db=self.db) if e.kind == events.ACCOUNT_CREATED][0]
        self.assertEqual(account.properties, {})

    def test_hostile_attribution_is_cleaned_before_it_is_stored_or_sent(self):
        transport = self._transport()
        self._signup("evil@example.com",
                     {"utm_source": "<img src=x onerror=1>", "utm_medium": "ok_medium",
                      "extra": "x"}, transport)
        form = self._form([c for c in transport.calls if c["url"].endswith("/v1/checkout/sessions")][0])
        self.assertNotIn("metadata[utm_source]", form)
        self.assertEqual(form["metadata[utm_medium]"], ["ok_medium"])
        self.assertNotIn("metadata[extra]", form)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class FunnelAnonymousIdAndBreakdownTests(_DbCase):
    def _post(self, kind, props=None, anon=None):
        from api.funnel import FunnelEventRequest, post_funnel_event
        post_funnel_event(FunnelEventRequest(kind=kind, properties=props, anon_id=anon))

    def test_each_visitor_id_is_its_own_hash(self):
        self._post("landing_view", anon=ANON)
        self._post("landing_view", anon="f" * 32)
        rows = events.list_events(db=self.db)
        self.assertEqual(len({r.user_hash for r in rows}), 2)
        self.assertEqual(rows[0].user_hash, events.hash_user_id("anon:" + ANON))

    def test_a_missing_or_malformed_id_falls_back_to_the_sentinel(self):
        from api.funnel import ANONYMOUS_FUNNEL_USER_ID
        self._post("landing_view")
        self._post("landing_view", anon="not an id!!")
        hashes = {r.user_hash for r in events.list_events(db=self.db)}
        self.assertEqual(hashes, {events.hash_user_id(ANONYMOUS_FUNNEL_USER_ID)})

    def test_admin_funnel_counts_unique_visitors_and_splits_by_source(self):
        from api.funnel import get_admin_funnel
        a, b = ANON, "b" * 32
        self._post("landing_view", {"utm_source": "reddit"}, anon=a)
        self._post("landing_view", {"utm_source": "reddit"}, anon=a)   # a reload
        self._post("landing_view", {"utm_source": "twitter"}, anon=b)
        self._post("landing_view", None, anon="c" * 32)                # direct
        self._post("cta_click", {"utm_source": "reddit", "cta": "cta-signup-hero"}, anon=a)
        self._post("signup_started", {"utm_source": "reddit"}, anon=a)
        result = get_admin_funnel(_admin=None)
        steps = {s["kind"]: s for s in result["steps"]}
        self.assertEqual(steps["landing_view"]["count"], 4)
        self.assertEqual(steps["landing_view"]["unique_visitors"], 3)
        self.assertEqual(steps["cta_click"]["count"], 1)
        self.assertEqual(steps["cta_click"]["conversion_from"], "landing_view")
        self.assertEqual(steps["signup_started"]["unique_visitors"], 1)
        by_source = result["by_source"]
        self.assertEqual(by_source["reddit"]["landing_view"], 2)
        self.assertEqual(by_source["reddit"]["cta_click"], 1)
        self.assertEqual(by_source["reddit"]["signup_started"], 1)
        self.assertEqual(by_source["twitter"]["landing_view"], 1)
        self.assertEqual(by_source["(direct)"]["landing_view"], 1)

    def test_a_hostile_beacon_cannot_break_the_admin_funnel(self):
        # Found by review, 2026-10-01: properties.utm_source = {"a": 1} was
        # stored by the public beacon and then used as a dict key, so
        # GET /admin/funnel answered 500 until the event aged out.
        from api.funnel import get_admin_funnel
        self._post("landing_view", {"utm_source": {"a": 1}}, anon=ANON)
        self._post("landing_view", {"utm_source": ["x", "y"]}, anon="b" * 32)
        self._post("landing_view", {"utm_source": 7}, anon="c" * 32)
        self._post("landing_view", {"utm_source": "red" + chr(10) + "dit" + "x" * 300}, anon="d" * 32)
        self._post("landing_view", {"utm_source": "reddit"}, anon="e" * 32)
        by_source = get_admin_funnel(_admin=None)["by_source"]
        self.assertEqual(by_source["(invalid)"]["landing_view"], 3)
        self.assertEqual(by_source["reddit"]["landing_view"], 1)
        for label in by_source:
            self.assertIsInstance(label, str)
            self.assertLessEqual(len(label), 64)
            self.assertTrue(label.isprintable())

    def test_by_source_includes_the_server_side_steps(self):
        from api.funnel import get_admin_funnel
        user = users_store.create_user("src@example.com", status="pending_payment")
        events.record_event_safe(user.id, events.ACCOUNT_CREATED, {"utm_source": "reddit"})
        events.record_event_safe(user.id, events.CHECKOUT_COMPLETED, {"utm_source": "reddit"})
        by_source = get_admin_funnel(_admin=None)["by_source"]
        self.assertEqual(by_source["reddit"]["account_created"], 1)
        self.assertEqual(by_source["reddit"]["checkout_completed"], 1)
        self.assertNotIn("bet_check_run", by_source["reddit"])


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class RevenueReportTests(_DbCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(customers.users_store, "db_path", lambda: self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _user(self, email, source=None):
        user = users_store.create_user(email, status="active", plan="beta")
        if source:
            customers.record_signup_attribution(user.id, {"utm_source": source}, db=self.db)
        return user

    def test_counts_mrr_and_sources(self):
        from api.admin import get_revenue
        paying1 = self._user("p1@example.com", "reddit")
        paying2 = self._user("p2@example.com", "reddit")
        paying3 = self._user("p3@example.com")
        trial = self._user("t1@example.com", "twitter")
        ended = self._user("e1@example.com", "twitter")
        self._user("nobody@example.com", "twitter")        # signed up, never paid
        # The revenue report counts a row only while it is paid through a
        # future instant (an active row nothing has paid for is `unpaid`).
        from datetime import datetime, timedelta, timezone
        end = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        customers.upsert_subscription(paying1.id, "sub1", "active",
                                      current_period_end=end, db=self.db)
        customers.upsert_subscription(paying2.id, "sub2", "active",
                                      current_period_end=end, db=self.db)
        customers.upsert_subscription(paying3.id, "sub3", "active",
                                      cancel_at=end, current_period_end=end, db=self.db)
        customers.upsert_subscription(trial.id, "sub4", "trialing",
                                      current_period_end=end, db=self.db)
        customers.upsert_subscription(ended.id, "sub5", "canceled", db=self.db)

        report = get_revenue(_admin=None)
        self.assertEqual(report["price_cents"], 1999)
        self.assertEqual(report["paying"], 3)
        self.assertEqual(report["trialing"], 1)
        self.assertEqual(report["canceled"], 1)
        self.assertEqual(report["cancel_scheduled"], 1)
        # MRR counts the two renewing actives; the scheduled-cancel one and the
        # trial are not recurring revenue. Gross is the figure without the
        # cancel subtraction.
        self.assertEqual(report["mrr_cents"], 2 * 1999)
        self.assertEqual(report["mrr_usd"], 39.98)
        self.assertEqual(report["mrr_gross_cents"], 3 * 1999)
        self.assertEqual(report["signups_total"], 6)
        self.assertEqual(report["signups_by_source"], {"twitter": 3, "reddit": 2, "(direct)": 1})
        self.assertEqual(report["paying_by_source"], {"reddit": 2, "(direct)": 1})
        self.assertEqual(report["trialing_by_source"], {"twitter": 1})

    def test_empty_database_reports_zeros(self):
        from api.admin import get_revenue
        report = get_revenue(_admin=None)
        self.assertEqual((report["paying"], report["trialing"], report["mrr_cents"]), (0, 0, 0))
        self.assertEqual(report["signups_by_source"], {})

    def test_the_revenue_route_is_admin_gated(self):
        from tests.test_public_record import _asgi_get
        with mock.patch.dict(os.environ, {"APP_ADMIN_TOKEN": "admin-secret-for-test"}):
            status, _ = _asgi_get("/admin/revenue")
            self.assertEqual(status, 401)
            status, body = _asgi_get("/admin/revenue",
                                     headers=[(b"x-admin-token", b"admin-secret-for-test")])
            self.assertEqual(status, 200)
            self.assertEqual(body["price_cents"], 1999)
        with mock.patch.dict(os.environ, {"APP_ADMIN_TOKEN": ""}):
            status, _ = _asgi_get("/admin/revenue")
            self.assertEqual(status, 404)


class FlyClientIpTests(unittest.TestCase):
    class _Req:
        def __init__(self, host="10.0.0.1", headers=None):
            self.client = type("C", (), {"host": host})()
            self.headers = headers if headers is not None else {}

    def test_fly_client_ip_wins_over_the_proxy_socket_address(self):
        req = self._Req(host="172.16.0.9", headers={"fly-client-ip": "203.0.113.7"})
        self.assertEqual(ratelimit.client_ip(req), "203.0.113.7")

    @unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
    def test_header_lookup_is_case_insensitive_through_a_real_headers_object(self):
        from starlette.datastructures import Headers
        req = self._Req(headers=Headers({"Fly-Client-IP": "198.51.100.4"}))
        self.assertEqual(ratelimit.client_ip(req), "198.51.100.4")

    def test_without_the_header_the_socket_address_is_used(self):
        self.assertEqual(ratelimit.client_ip(self._Req(host="192.0.2.8")), "192.0.2.8")

    def test_blank_header_falls_back_and_no_client_is_unknown(self):
        self.assertEqual(ratelimit.client_ip(self._Req(host="192.0.2.8",
                                                       headers={"fly-client-ip": "  "})), "192.0.2.8")
        bare = type("R", (), {})()
        self.assertEqual(ratelimit.client_ip(bare), "unknown")

    @unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
    def test_two_visitors_behind_one_proxy_get_separate_buckets(self):
        """The bug: both are the proxy's address, so the 2nd visitor's first
        request counted against the 1st visitor's allowance."""
        limiter = ratelimit.FixedWindowLimiter(limit=1, window_s=60)
        dependency = ratelimit.limiter_dependency(limiter)
        proxy = "172.16.0.9"
        dependency(self._Req(host=proxy, headers={"fly-client-ip": "203.0.113.1"}))
        dependency(self._Req(host=proxy, headers={"fly-client-ip": "203.0.113.2"}))  # must not 429
        with self.assertRaises(HTTPException) as ctx:
            dependency(self._Req(host=proxy, headers={"fly-client-ip": "203.0.113.1"}))
        self.assertEqual(ctx.exception.status_code, 429)

    @unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
    def test_signup_and_support_use_the_same_resolution(self):
        from api import signup, support
        req = self._Req(host="172.16.0.9", headers={"fly-client-ip": "203.0.113.50"})
        self.assertEqual(signup._client_ip(req), "203.0.113.50")
        self.assertEqual(support._client_ip(req), "203.0.113.50")

    @unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
    def test_the_signup_limit_is_per_real_visitor(self):
        from api import signup
        limit = signup.SIGNUP_RATE_LIMIT_PER_HOUR
        proxy = "172.16.0.77"
        with mock.patch.object(signup, "_signup_limiter",
                               ratelimit.FixedWindowLimiter(limit=limit, window_s=3600.0)):
            for _ in range(limit):
                signup._rate_limit_signup(self._Req(host=proxy, headers={"fly-client-ip": "198.51.100.1"}))
            with self.assertRaises(HTTPException):
                signup._rate_limit_signup(self._Req(host=proxy, headers={"fly-client-ip": "198.51.100.1"}))
            # A different visitor behind the same proxy is unaffected.
            signup._rate_limit_signup(self._Req(host=proxy, headers={"fly-client-ip": "198.51.100.2"}))


if __name__ == "__main__":
    unittest.main()
