"""src/appstate/ratelimit.py: the fixed-window per-key limiter.

stdlib only -- FixedWindowLimiter and key_for import no fastapi at all, so
the first class below runs with or without fastapi installed. The fastapi
dependency factory (limiter_dependency) is only exercised in the
skip-if-no-fastapi class, same pattern as the rest of tests/test_api_*.py.
"""

from __future__ import annotations

import unittest

from src.appstate import ratelimit

try:
    import fastapi  # noqa: F401
    _HAVE_FASTAPI = True
except ImportError:
    _HAVE_FASTAPI = False


class KeyForTests(unittest.TestCase):

    def test_same_identity_hashes_to_the_same_key(self):
        self.assertEqual(ratelimit.key_for("user:1"), ratelimit.key_for("user:1"))

    def test_different_identities_hash_differently(self):
        self.assertNotEqual(ratelimit.key_for("user:1"), ratelimit.key_for("user:2"))

    def test_the_raw_identity_never_appears_in_the_key(self):
        self.assertNotIn("user:1", ratelimit.key_for("user:1"))


class FixedWindowLimiterTests(unittest.TestCase):

    def test_construction_refuses_a_non_positive_limit_or_window(self):
        with self.assertRaises(ValueError):
            ratelimit.FixedWindowLimiter(limit=0, window_s=60.0)
        with self.assertRaises(ValueError):
            ratelimit.FixedWindowLimiter(limit=5, window_s=0.0)

    def test_allows_up_to_the_limit_then_refuses(self):
        limiter = ratelimit.FixedWindowLimiter(limit=3, window_s=60.0)
        for _ in range(3):
            self.assertTrue(limiter.check("k", now=1000.0).allowed)
        result = limiter.check("k", now=1000.0)
        self.assertFalse(result.allowed)
        self.assertEqual(result.remaining, 0)
        self.assertIsNotNone(result.retry_after)

    def test_remaining_counts_down(self):
        limiter = ratelimit.FixedWindowLimiter(limit=3, window_s=60.0)
        self.assertEqual(limiter.check("k", now=1000.0).remaining, 2)
        self.assertEqual(limiter.check("k", now=1000.0).remaining, 1)
        self.assertEqual(limiter.check("k", now=1000.0).remaining, 0)

    def test_a_new_window_resets_the_count(self):
        limiter = ratelimit.FixedWindowLimiter(limit=2, window_s=60.0)
        limiter.check("k", now=1000.0)
        limiter.check("k", now=1000.0)
        self.assertFalse(limiter.check("k", now=1000.0).allowed)
        # Past the window boundary: a fresh count.
        self.assertTrue(limiter.check("k", now=1061.0).allowed)

    def test_different_keys_never_share_a_counter(self):
        limiter = ratelimit.FixedWindowLimiter(limit=1, window_s=60.0)
        self.assertTrue(limiter.check("a", now=1000.0).allowed)
        self.assertTrue(limiter.check("b", now=1000.0).allowed)
        self.assertFalse(limiter.check("a", now=1000.0).allowed)

    def test_retry_after_is_bounded_by_the_window(self):
        limiter = ratelimit.FixedWindowLimiter(limit=1, window_s=60.0)
        limiter.check("k", now=1000.0)
        result = limiter.check("k", now=1000.0)
        self.assertLessEqual(result.retry_after, 60.0)
        self.assertGreater(result.retry_after, 0.0)


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class LimiterDependencyTests(unittest.TestCase):
    """The fastapi dependency factory -- exercised as a plain callable, the
    same direct-call style tests/test_api_*.py already uses for routes."""

    def test_importable_without_fastapi_is_asserted_by_the_try_import(self):
        # ratelimit itself imported cleanly above with fastapi present or
        # not (HAS_FASTAPI reflects which); this pins that the guard exists.
        self.assertTrue(hasattr(ratelimit, "HAS_FASTAPI"))

    def test_ip_keyed_dependency_allows_then_refuses(self):
        from unittest import mock
        limiter = ratelimit.FixedWindowLimiter(limit=1, window_s=60.0)
        dep = ratelimit.limiter_dependency(limiter)
        request = mock.Mock()
        request.client.host = "203.0.113.5"
        dep(request)  # first call: allowed, no raise
        with self.assertRaises(fastapi.HTTPException) as ctx:
            dep(request)
        self.assertEqual(ctx.exception.status_code, 429)

    def test_ip_keyed_dependency_separates_clients(self):
        from unittest import mock
        limiter = ratelimit.FixedWindowLimiter(limit=1, window_s=60.0)
        dep = ratelimit.limiter_dependency(limiter)
        request_a, request_b = mock.Mock(), mock.Mock()
        request_a.client.host = "203.0.113.5"
        request_b.client.host = "203.0.113.9"
        dep(request_a)
        dep(request_b)  # a different client's first call: still allowed

    def test_a_request_with_no_client_falls_back_to_one_shared_counter(self):
        """A conservative fallback (stricter, never looser): missing client
        info collapses onto "unknown" rather than bypassing the limit."""
        from unittest import mock
        limiter = ratelimit.FixedWindowLimiter(limit=1, window_s=60.0)
        dep = ratelimit.limiter_dependency(limiter)
        request = mock.Mock(client=None)
        dep(request)
        with self.assertRaises(fastapi.HTTPException):
            dep(request)

    def test_user_keyed_dependency_uses_the_resolved_users_id(self):
        from unittest import mock
        from dataclasses import dataclass

        @dataclass
        class _FakeUser:
            id: int

        limiter = ratelimit.FixedWindowLimiter(limit=1, window_s=60.0)

        def _fake_current_user():
            return _FakeUser(id=42)

        dep = ratelimit.limiter_dependency(limiter, user_dependency=_fake_current_user)
        request = mock.Mock()
        dep(request=request, current_user=_FakeUser(id=42))
        with self.assertRaises(fastapi.HTTPException):
            dep(request=request, current_user=_FakeUser(id=42))
        # A different user id is a different counter, same request object.
        dep(request=request, current_user=_FakeUser(id=7))


class _Req:
    def __init__(self, host="10.0.0.1", headers=None):
        self.client = type("C", (), {"host": host})()
        self.headers = headers if headers is not None else {}


class ClientIpBehindCloudflareTests(unittest.TestCase):
    """Production is reached directly at linehound-prod.fly.dev and through
    Cloudflare at linehound.app. Through Cloudflare, Fly-Client-IP is a
    Cloudflare address shared by many visitors, so keying on it put everyone on
    linehound.app in one bucket (the 11th signup of the hour was a 429)."""

    CF_EDGE = "172.69.10.1"          # inside 172.64.0.0/13
    CF_EDGE_V6 = "2606:4700:10::1"   # inside 2606:4700::/32

    def test_a_cloudflare_hop_resolves_to_cf_connecting_ip(self):
        req = _Req(headers={"fly-client-ip": self.CF_EDGE, "cf-connecting-ip": "203.0.113.50"})
        self.assertEqual(ratelimit.client_ip(req), "203.0.113.50")

    def test_a_cloudflare_ipv6_hop_resolves_to_cf_connecting_ip(self):
        req = _Req(headers={"fly-client-ip": self.CF_EDGE_V6, "cf-connecting-ip": "2001:db8::7"})
        self.assertEqual(ratelimit.client_ip(req), "2001:db8::7")

    def test_two_visitors_through_cloudflare_get_different_keys(self):
        a = ratelimit.client_ip(_Req(headers={"fly-client-ip": self.CF_EDGE,
                                              "cf-connecting-ip": "203.0.113.1"}))
        b = ratelimit.client_ip(_Req(headers={"fly-client-ip": self.CF_EDGE,
                                              "cf-connecting-ip": "203.0.113.2"}))
        self.assertNotEqual(a, b)

    def test_a_direct_fly_request_ignores_a_spoofed_cf_connecting_ip(self):
        req = _Req(headers={"fly-client-ip": "198.51.100.4", "cf-connecting-ip": "203.0.113.99"})
        self.assertEqual(ratelimit.client_ip(req), "198.51.100.4")

    def test_a_cloudflare_hop_without_cf_connecting_ip_falls_back_to_fly(self):
        self.assertEqual(ratelimit.client_ip(_Req(headers={"fly-client-ip": self.CF_EDGE})),
                         self.CF_EDGE)

    def test_a_malformed_cf_connecting_ip_falls_back_to_fly_and_is_never_the_key(self):
        for bad in ("not-an-ip", "999.1.1.1", "203.0.113.1\nX: y", "x" * 5000, "<script>"):
            got = ratelimit.client_ip(_Req(headers={"fly-client-ip": self.CF_EDGE,
                                                    "cf-connecting-ip": bad}))
            self.assertEqual(got, self.CF_EDGE, bad[:20])

    def test_a_malformed_fly_client_ip_is_never_the_key(self):
        for bad in ("not-an-ip", "1.2.3", "a" * 5000, "203.0.113.1, 203.0.113.2"):
            got = ratelimit.client_ip(_Req(host="192.0.2.8", headers={"fly-client-ip": bad}))
            self.assertEqual(got, "192.0.2.8", bad[:20])

    def test_addresses_are_normalised_through_ipaddress(self):
        got = ratelimit.client_ip(_Req(headers={"fly-client-ip": "2001:0DB8:0:0:0:0:0:1"}))
        self.assertEqual(got, "2001:db8::1")
        got = ratelimit.client_ip(_Req(headers={"fly-client-ip": "::ffff:203.0.113.5"}))
        self.assertEqual(got, "203.0.113.5")

    def test_every_published_range_is_present_and_exact(self):
        got = sorted(str(n) for n in ratelimit.CLOUDFLARE_IP_RANGES)
        want = sorted([
            "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
            "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
            "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
            "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
            "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32", "2405:b500::/32",
            "2405:8100::/32", "2a06:98c0::/29", "2c0f:f248::/32"])
        self.assertEqual(got, want)

    def test_an_address_just_outside_a_range_is_not_cloudflare(self):
        # 172.72.0.0 is the first address past 172.64.0.0/13.
        req = _Req(headers={"fly-client-ip": "172.72.0.1", "cf-connecting-ip": "203.0.113.50"})
        self.assertEqual(ratelimit.client_ip(req), "172.72.0.1")

    def test_a_headers_object_that_raises_never_raises(self):
        class Boom:
            def get(self, *_a, **_k):
                raise RuntimeError("boom")
        self.assertEqual(ratelimit.client_ip(_Req(host="192.0.2.8", headers=Boom())), "192.0.2.8")

    def test_the_docstring_states_what_remains_true(self):
        doc = ratelimit.client_ip.__doc__
        self.assertIn("client-controlled", doc)
        self.assertIn("not a security boundary", doc)


class LimiterMemoryIsBoundedTests(unittest.TestCase):
    def test_the_cap_is_ten_thousand(self):
        self.assertEqual(ratelimit.MAX_TRACKED_KEYS, 10_000)

    def test_expired_windows_are_dropped_once_over_the_cap(self):
        limiter = ratelimit.FixedWindowLimiter(limit=5, window_s=60.0)
        for i in range(ratelimit.MAX_TRACKED_KEYS):
            limiter.check(f"old{i}", now=1000.0)
        self.assertEqual(len(limiter._windows), ratelimit.MAX_TRACKED_KEYS)
        limiter.check("fresh", now=2000.0)
        self.assertEqual(list(limiter._windows), ["fresh"])

    def test_live_windows_are_trimmed_oldest_first_to_the_cap(self):
        limiter = ratelimit.FixedWindowLimiter(limit=5, window_s=10_000.0)
        for i in range(ratelimit.MAX_TRACKED_KEYS + 50):
            limiter.check(f"k{i}", now=1000.0 + i)
        self.assertLessEqual(len(limiter._windows), ratelimit.MAX_TRACKED_KEYS)
        self.assertNotIn("k0", limiter._windows)
        self.assertIn(f"k{ratelimit.MAX_TRACKED_KEYS + 49}", limiter._windows)

    def test_pruning_never_changes_an_allowed_or_refused_answer_for_a_live_key(self):
        limiter = ratelimit.FixedWindowLimiter(limit=2, window_s=60.0)
        limiter.check("live", now=5000.0)
        limiter.check("live", now=5000.0)
        for i in range(ratelimit.MAX_TRACKED_KEYS):
            limiter.check(f"old{i}", now=1000.0)
        self.assertFalse(limiter.check("live", now=5001.0).allowed)


if __name__ == "__main__":
    unittest.main()
