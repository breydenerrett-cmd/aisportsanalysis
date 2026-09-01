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


if __name__ == "__main__":
    unittest.main()
