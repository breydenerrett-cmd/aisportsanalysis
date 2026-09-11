"""Past the TTL, answer now and rebuild behind the caller.

WHY
---
`SingleFlightTTLCache` made the requesting thread run the rebuild whenever
the TTL had passed. Correct, and on a small machine it is what a customer
experiences as a dead page: /games/{date} rebuilds in ~3s on a developer
laptop and 20-45s on the 512 MB staging container, against a 120s TTL. So
about every other visitor arrived just after an expiry and waited out the
whole rebuild behind an animating skeleton.

The owner, 2026-09-10, on both #/today and #/games: "they just sit there and
spin and circle for many many many minutes... how would we fix this so that
as soon as they click on the link, you don't have to load, they're already
loaded."

WHAT IS TESTED
--------------
The property that answers him: **a caller past the TTL returns before the
rebuild finishes.** Not that a flag is set, not that a thread was spawned --
that the call came back early, measured against a builder that deliberately
takes longer than the assertion window.

And the three ways serving stale could go quietly wrong: a cold key with
nothing to serve must still block, the staleness must be VISIBLE, and the
window must be bounded so a permanently failing rebuild cannot serve an
ancient value forever.
"""

from __future__ import annotations

import threading
import time
import unittest
from datetime import datetime, timedelta, timezone

from src.appstate import freshness


class _Builder:
    """A builder whose duration and outcome the test controls."""

    def __init__(self, delay=0.0, value="v1"):
        self.delay = delay
        self.value = value
        self.calls = 0
        self.started = threading.Event()
        self.raise_with = None

    def __call__(self):
        self.calls += 1
        self.started.set()
        if self.delay:
            time.sleep(self.delay)
        if self.raise_with is not None:
            raise self.raise_with
        return self.value


def _age(cache, key, seconds):
    """Backdate a cached entry rather than sleeping through a real TTL."""
    entry = cache._entries[key]
    entry.built_at = datetime.now(timezone.utc) - timedelta(seconds=seconds)


class TheCallerDoesNotWaitForARebuild(unittest.TestCase):

    def test_a_stale_read_returns_before_the_rebuild_finishes(self):
        """THE ONE THAT MATTERS. The builder takes 2s; the stale read must
        come back in a small fraction of that. Timing is the assertion
        because "did the customer wait" is the actual question -- a test
        that only checked a stale flag would pass on a cache that still
        blocked."""
        cache = freshness.SingleFlightTTLCache(ttl_s=1.0,
                                               stale_while_revalidate_s=600.0)
        quick = _Builder(value="first")
        cache.get("k", quick)
        _age(cache, "k", 60)

        slow = _Builder(delay=2.0, value="second")
        start = time.monotonic()
        value, meta = cache.get("k", slow)
        elapsed = time.monotonic() - start

        self.assertEqual(value, "first", "must serve the last good value")
        self.assertLess(elapsed, 0.5,
                        f"the caller waited {elapsed:.2f}s on a 2s rebuild -- "
                        f"this is the defect the whole change exists to fix")
        self.assertTrue(slow.started.wait(1.0),
                        "no background rebuild was started, so the value "
                        "would never refresh")

    def test_the_refresh_actually_lands(self):
        cache = freshness.SingleFlightTTLCache(ttl_s=1.0,
                                               stale_while_revalidate_s=600.0)
        cache.get("k", _Builder(value="first"))
        _age(cache, "k", 60)

        second = _Builder(value="second")
        cache.get("k", second)
        self.assertTrue(second.started.wait(2.0))
        for _ in range(50):
            if cache.get("k", _Builder(value="third"))[0] == "second":
                break
            time.sleep(0.05)
        self.assertEqual(cache.get("k", _Builder(value="third"))[0], "second",
                         "the background rebuild never replaced the entry")

    def test_only_one_background_rebuild_runs_at_a_time(self):
        """A pile-up of identical rebuilds on a one-CPU box is the failure
        this cache exists to prevent; serving stale must not reintroduce it."""
        cache = freshness.SingleFlightTTLCache(ttl_s=1.0,
                                               stale_while_revalidate_s=600.0)
        cache.get("k", _Builder(value="first"))
        _age(cache, "k", 60)

        slow = _Builder(delay=1.0, value="second")
        for _ in range(8):
            cache.get("k", slow)
        self.assertTrue(slow.started.wait(1.0))
        time.sleep(0.2)
        self.assertEqual(slow.calls, 1,
                         f"{slow.calls} concurrent rebuilds of one key")


class StalenessIsNeverSilent(unittest.TestCase):

    def test_a_stale_read_is_flagged_and_says_why(self):
        cache = freshness.SingleFlightTTLCache(ttl_s=1.0,
                                               stale_while_revalidate_s=600.0)
        cache.get("k", _Builder(value="first"))
        _age(cache, "k", 300)
        _value, meta = cache.get("k", _Builder(delay=2.0, value="second"))
        self.assertTrue(meta["stale"])
        self.assertIsNotNone(meta["stale_reason"])
        self.assertGreater(meta["age_s"], 290)

    def test_a_fresh_read_is_not_flagged(self):
        cache = freshness.SingleFlightTTLCache(ttl_s=600.0,
                                               stale_while_revalidate_s=600.0)
        cache.get("k", _Builder(value="first"))
        _value, meta = cache.get("k", _Builder(value="second"))
        self.assertFalse(meta["stale"])


class TheWindowIsBounded(unittest.TestCase):

    def test_a_cold_key_still_blocks_because_nothing_honest_exists(self):
        """There is no last-good value to serve. Blocking is correct; the
        alternative is inventing a payload."""
        cache = freshness.SingleFlightTTLCache(ttl_s=1.0,
                                               stale_while_revalidate_s=600.0)
        builder = _Builder(delay=0.3, value="only")
        start = time.monotonic()
        value, _meta = cache.get("cold", builder)
        self.assertEqual(value, "only")
        self.assertGreaterEqual(time.monotonic() - start, 0.25)

    def test_past_the_window_the_caller_blocks_again(self):
        """An unbounded stale window lets a rebuild that fails every time
        serve last week's slate forever, each response cheerfully flagged
        stale. Old-but-honest has a limit."""
        cache = freshness.SingleFlightTTLCache(ttl_s=1.0,
                                               stale_while_revalidate_s=10.0)
        cache.get("k", _Builder(value="first"))
        _age(cache, "k", 5000)

        slow = _Builder(delay=0.3, value="second")
        start = time.monotonic()
        value, _meta = cache.get("k", slow)
        self.assertGreaterEqual(
            time.monotonic() - start, 0.25,
            "past the stale window the caller must wait for a real rebuild")
        self.assertEqual(value, "second")

    def test_a_zero_window_keeps_the_old_blocking_behaviour(self):
        """The default. Every caller that has not opted in is unchanged."""
        cache = freshness.SingleFlightTTLCache(ttl_s=1.0)
        cache.get("k", _Builder(value="first"))
        _age(cache, "k", 60)
        slow = _Builder(delay=0.3, value="second")
        start = time.monotonic()
        value, _meta = cache.get("k", slow)
        self.assertGreaterEqual(time.monotonic() - start, 0.25)
        self.assertEqual(value, "second")

    def test_a_failing_background_rebuild_does_not_take_the_caller_down(self):
        """The caller already has its answer and has gone. An exception
        escaping the daemon thread would be a traceback with no request
        attached to it."""
        cache = freshness.SingleFlightTTLCache(ttl_s=1.0,
                                               stale_while_revalidate_s=600.0)
        cache.get("k", _Builder(value="first"))
        _age(cache, "k", 60)

        broken = _Builder(value="never")
        broken.raise_with = RuntimeError("provider down")
        value, meta = cache.get("k", broken)
        self.assertEqual(value, "first")
        self.assertTrue(broken.started.wait(1.0))
        time.sleep(0.2)
        # And the key is not left marked as refreshing, or it would never
        # retry again for the life of the process.
        self.assertNotIn("k", cache._refreshing)


class TheEndpointsOptedIn(unittest.TestCase):
    """A cache that supports this and no endpoint using it helps nobody."""

    def test_games_entries_cache_serves_stale(self):
        try:
            import api.games as games
        except ImportError:
            self.skipTest("fastapi not installed")
        self.assertGreater(games._entries_cache.stale_while_revalidate_s, 0)

    def test_today_cache_serves_stale(self):
        try:
            import api.today as today
        except ImportError:
            self.skipTest("fastapi not installed")
        self.assertGreater(today._today_cache.stale_while_revalidate_s, 0)


if __name__ == "__main__":
    unittest.main()
