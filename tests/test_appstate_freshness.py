"""src/appstate/freshness.py: TTL cache, single-flight, and the
serve-stale-with-flag policy, tested in isolation from any endpoint.

Each test builds its own SingleFlightTTLCache so no test observes another
test's cached state -- the module has no process-global cache of its own
(api/today.py and api/games.py each own one module-level instance; those
are exercised through tests/test_api_today.py and tests/test_api_games.py).
"""

from __future__ import annotations

import threading
import time
import unittest
from datetime import datetime, timedelta, timezone

from src.appstate import freshness


def _now_plus(base: datetime, seconds: float) -> datetime:
    return base + timedelta(seconds=seconds)


class FreshnessPolicyTests(unittest.TestCase):

    def test_no_observed_utc_is_never_stale(self):
        """Absence of odds is a different fact than old odds -- this policy
        speaks only to the second."""
        policy = freshness.FreshnessPolicy(odds_max_age_s=1800)
        stale, reason = policy.evaluate_odds_age(None, now=datetime.now(timezone.utc))
        self.assertFalse(stale)
        self.assertIsNone(reason)

    def test_under_threshold_is_fresh(self):
        policy = freshness.FreshnessPolicy(odds_max_age_s=1800)
        now = datetime(2026, 8, 31, 12, 30, 0, tzinfo=timezone.utc)
        observed = (now - timedelta(minutes=10)).isoformat()
        stale, reason = policy.evaluate_odds_age(observed, now=now)
        self.assertFalse(stale)
        self.assertIsNone(reason)

    def test_over_threshold_is_stale_with_a_named_reason(self):
        policy = freshness.FreshnessPolicy(odds_max_age_s=1800)
        now = datetime(2026, 8, 31, 12, 30, 0, tzinfo=timezone.utc)
        observed = (now - timedelta(minutes=45)).isoformat()
        stale, reason = policy.evaluate_odds_age(observed, now=now)
        self.assertTrue(stale)
        self.assertIn("2700", reason)  # 45 minutes = 2700s, named not hidden


class SingleFlightTTLCacheTests(unittest.TestCase):

    def test_cache_hit_within_ttl_never_rebuilds(self):
        calls = []
        cache = freshness.SingleFlightTTLCache(ttl_s=120.0)

        def builder():
            calls.append(1)
            return {"n": len(calls)}

        v1, m1 = cache.get("k", builder)
        v2, m2 = cache.get("k", builder)
        self.assertEqual(len(calls), 1)
        self.assertEqual(v1, v2)
        self.assertFalse(m1["stale"])
        self.assertFalse(m2["stale"])
        self.assertGreaterEqual(m2["age_s"], 0.0)

    def test_ttl_expiry_triggers_exactly_one_rebuild(self):
        calls = []
        cache = freshness.SingleFlightTTLCache(ttl_s=0.05)

        def builder():
            calls.append(1)
            return {"n": len(calls)}

        cache.get("k", builder)
        time.sleep(0.08)
        value, meta = cache.get("k", builder)
        self.assertEqual(len(calls), 2)
        self.assertEqual(value, {"n": 2})
        self.assertFalse(meta["stale"])

    def test_every_result_carries_served_built_and_age_metadata(self):
        cache = freshness.SingleFlightTTLCache(ttl_s=120.0)
        _, meta = cache.get("k", lambda: {"ok": True})
        for key in ("served_at", "built_at", "age_s", "stale", "stale_reason"):
            self.assertIn(key, meta)
        self.assertIsNotNone(meta["served_at"])
        self.assertIsNotNone(meta["built_at"])
        self.assertEqual(meta["age_s"], 0.0)

    def test_single_flight_under_concurrent_threads_builds_once(self):
        """N threads racing a cold key must share one rebuild -- the
        stampede-protection property. A short sleep inside the builder
        widens the race window so concurrent callers actually overlap
        instead of finishing sequentially before the next one starts."""
        cache = freshness.SingleFlightTTLCache(ttl_s=120.0)
        call_count = 0
        call_lock = threading.Lock()
        thread_count = 12
        start_barrier = threading.Barrier(thread_count)
        results = []

        def builder():
            nonlocal call_count
            with call_lock:
                call_count += 1
            time.sleep(0.1)
            return "built-once"

        def worker():
            start_barrier.wait()  # force every thread to race the same window
            value, _meta = cache.get("shared-key", builder)
            results.append(value)

        threads = [threading.Thread(target=worker) for _ in range(thread_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertEqual(call_count, 1,
                         "single-flight must call the builder exactly once "
                         "for N concurrent callers on the same cold key")
        self.assertEqual(results, ["built-once"] * thread_count)

    def test_rebuild_failure_with_no_prior_value_reraises(self):
        """Nothing honest to serve on a cold key -- the caller's own error
        handling (e.g. api/games.py's MLBError -> 502) must still see the
        original exception, not a swallowed/rewrapped one."""
        cache = freshness.SingleFlightTTLCache(ttl_s=120.0)

        class Boom(Exception):
            pass

        def failing_builder():
            raise Boom("provider down")

        with self.assertRaises(Boom):
            cache.get("k", failing_builder)

    def test_rebuild_failure_after_a_good_build_serves_last_good_stale(self):
        """Serve-stale-with-flag: once a value exists, a later rebuild
        failure never wipes it out or fabricates a fresh replacement --
        the last-good value comes back with stale=True and a reason naming
        the failure."""
        cache = freshness.SingleFlightTTLCache(ttl_s=0.05)

        good_value, _ = cache.get("k", lambda: "good-value")
        self.assertEqual(good_value, "good-value")

        time.sleep(0.08)  # force TTL expiry so the next get() attempts a rebuild

        def failing_builder():
            raise RuntimeError("provider down")

        value, meta = cache.get("k", failing_builder)
        self.assertEqual(value, "good-value")
        self.assertTrue(meta["stale"])
        self.assertIn("rebuild failed", meta["stale_reason"])
        self.assertIsNotNone(meta["built_at"])

    def test_odds_observed_extractor_is_reevaluated_against_current_clock(self):
        """A cache HIT (no rebuild) must still re-check odds staleness
        against `now` at read time -- odds keep aging in real time even
        though the cached payload itself is untouched."""
        policy = freshness.FreshnessPolicy(odds_max_age_s=0.05)
        cache = freshness.SingleFlightTTLCache(ttl_s=120.0, policy=policy)
        built_at = datetime.now(timezone.utc).isoformat()

        _, meta_immediately = cache.get(
            "k", lambda: {"observed_utc": built_at},
            odds_observed_extractor=lambda v: v["observed_utc"])
        self.assertFalse(meta_immediately["stale"])

        time.sleep(0.08)  # now older than the 0.05s odds threshold, cache entry still fresh

        _, meta_later = cache.get(
            "k", lambda: {"observed_utc": built_at},
            odds_observed_extractor=lambda v: v["observed_utc"])
        self.assertTrue(meta_later["stale"])
        self.assertIn("odds board", meta_later["stale_reason"])

    def test_invalidate_forces_a_rebuild_without_waiting_for_ttl(self):
        calls = []
        cache = freshness.SingleFlightTTLCache(ttl_s=120.0)

        def builder():
            calls.append(1)
            return len(calls)

        cache.get("k", builder)
        cache.invalidate("k")
        cache.get("k", builder)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
