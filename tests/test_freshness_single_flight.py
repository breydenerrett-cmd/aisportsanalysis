"""src/appstate/freshness.py: at most one background (stale-while-
revalidate) rebuild in flight per SingleFlightTTLCache INSTANCE, not one
per key.

WHY THIS IS SEPARATE FROM tests/test_stale_while_revalidate.py
-----------------------------------------------------------------
That file already covers the single-key stampede case (`_start_background_
refresh` never starts a second rebuild for a key that is already
refreshing) and the failure/last-good-value paths -- none of it touches
more than one key per cache, so none of it exercises the property this
file is about. Measured 2026-09-2x: overlapping background rebuilds for
DIFFERENT keys of the SAME cache (a warm-up pass touching several dates
back to back, each one going stale while an earlier date's rebuild was
still running) pushed peak working set to 1,029 MB against the 1,024 MB
deploy VM. The fix promotes the "one rebuild in flight" guard from
per-key to per-cache; this file is the regression test for that promotion.

Every test builds its own cache -- same isolation discipline
tests/test_appstate_freshness.py's module docstring states.
"""

from __future__ import annotations

import threading
import time
import unittest
from datetime import datetime, timedelta, timezone

from src.appstate import freshness


class _Builder:
    """A builder whose duration and outcome the test controls -- same
    fixture `tests/test_stale_while_revalidate.py` uses."""

    def __init__(self, delay=0.0, value="v1"):
        self.delay = delay
        self.value = value
        self.calls = 0
        self.started = threading.Event()

    def __call__(self):
        self.calls += 1
        self.started.set()
        if self.delay:
            time.sleep(self.delay)
        return self.value


def _age(cache, key, seconds):
    entry = cache._entries[key]
    entry.built_at = datetime.now(timezone.utc) - timedelta(seconds=seconds)


class OneRebuildPerCacheTests(unittest.TestCase):

    def _stale_cache(self):
        return freshness.SingleFlightTTLCache(ttl_s=1.0,
                                              stale_while_revalidate_s=600.0)

    def test_two_different_keys_share_one_rebuild_slot(self):
        """key "a" goes stale first and starts refreshing (slow, so it is
        still running); a stale hit on a DIFFERENT key "b" must serve its
        own stale value and start NOTHING -- not a second concurrent
        rebuild for "b" alongside "a"'s."""
        cache = self._stale_cache()
        cache.get("a", _Builder(value="a1"))
        cache.get("b", _Builder(value="b1"))
        _age(cache, "a", 60)
        _age(cache, "b", 60)

        slow_a = _Builder(delay=1.0, value="a2")
        value_a, meta_a = cache.get("a", slow_a)
        self.assertTrue(slow_a.started.wait(1.0), "a's rebuild never started")

        slow_b = _Builder(delay=1.0, value="b2")
        value_b, meta_b = cache.get("b", slow_b)

        # Both calls return immediately with their OWN last-good value --
        # the point of serve-stale-with-flag is untouched by this change.
        self.assertEqual(value_a, "a1")
        self.assertEqual(value_b, "b1")
        self.assertTrue(meta_a["stale"])
        self.assertTrue(meta_b["stale"])

        # "b" must NOT have started its own background rebuild while "a"'s
        # is still in flight -- this is the property under test.
        self.assertFalse(slow_b.started.is_set(),
                         "a second rebuild started for a different key "
                         "while one was already in flight for this cache")
        self.assertEqual(slow_b.calls, 0)

    def test_the_idle_key_gets_its_turn_once_the_slot_frees_up(self):
        """Once "a"'s rebuild finishes and the slot frees, a LATER stale
        hit on "b" does start its own background rebuild -- the guard
        skips a second CONCURRENT rebuild, it does not starve "b"
        forever."""
        cache = self._stale_cache()
        cache.get("a", _Builder(value="a1"))
        cache.get("b", _Builder(value="b1"))
        _age(cache, "a", 60)
        _age(cache, "b", 60)

        quick_a = _Builder(delay=0.05, value="a2")
        cache.get("a", quick_a)
        self.assertTrue(quick_a.started.wait(1.0))
        # give the (short) background rebuild time to finish and release
        # the slot.
        for _ in range(50):
            if not cache._refreshing:
                break
            time.sleep(0.02)
        self.assertFalse(cache._refreshing, "slot never freed")

        slow_b = _Builder(delay=0.2, value="b2")
        cache.get("b", slow_b)
        self.assertTrue(slow_b.started.wait(1.0),
                        "b never got a turn after the slot freed up")

    def test_a_single_key_is_still_refreshed_at_most_once(self):
        """Regression: the single-key stampede case (already covered in
        tests/test_stale_while_revalidate.py) still holds under the new,
        coarser guard -- repeated stale hits on ONE key never start more
        than one rebuild for it."""
        cache = self._stale_cache()
        cache.get("k", _Builder(value="first"))
        _age(cache, "k", 60)

        slow = _Builder(delay=0.3, value="second")
        for _ in range(6):
            cache.get("k", slow)
        self.assertTrue(slow.started.wait(1.0))
        time.sleep(0.1)
        self.assertEqual(slow.calls, 1)

    def test_refreshing_set_is_empty_before_and_after(self):
        """`_refreshing` stays a plain set a caller can still probe with
        `in`/`not in` (tests/test_stale_while_revalidate.py does exactly
        that) -- only the STOP CONDITION inside `_start_background_refresh`
        changed, not the attribute's shape."""
        cache = self._stale_cache()
        cache.get("k", _Builder(value="first"))
        self.assertEqual(cache._refreshing, set())
        _age(cache, "k", 60)

        builder = _Builder(delay=0.05, value="second")
        cache.get("k", builder)
        self.assertTrue(builder.started.wait(1.0))
        self.assertIn("k", cache._refreshing)
        for _ in range(50):
            if "k" not in cache._refreshing:
                break
            time.sleep(0.02)
        self.assertNotIn("k", cache._refreshing)

    def test_two_caches_are_independent(self):
        """The guard is per CACHE INSTANCE, not a process-wide singleton --
        two separate SingleFlightTTLCache objects each get their own
        rebuild slot, so a slow rebuild on one cache never blocks a
        different cache's own stale hit from refreshing."""
        cache1 = self._stale_cache()
        cache2 = self._stale_cache()
        cache1.get("k", _Builder(value="c1-first"))
        cache2.get("k", _Builder(value="c2-first"))
        _age(cache1, "k", 60)
        _age(cache2, "k", 60)

        slow1 = _Builder(delay=1.0, value="c1-second")
        cache1.get("k", slow1)
        self.assertTrue(slow1.started.wait(1.0))

        slow2 = _Builder(delay=0.05, value="c2-second")
        cache2.get("k", slow2)
        self.assertTrue(slow2.started.wait(1.0),
                        "a different cache's rebuild was blocked by this "
                        "cache's own in-flight rebuild")



class OneBuildInTheWholeProcessTests(unittest.TestCase):
    """Production was killed for memory at the second warm-up pass: eleven
    caches each started their own background rebuild and seven builds ran
    side by side. One rebuild per cache is not the limit that matters."""

    def _overlap_tracker(self):
        state = {"running": 0, "most": 0, "builds": 0}
        guard = threading.Lock()

        def build():
            with guard:
                state["running"] += 1
                state["builds"] += 1
                state["most"] = max(state["most"], state["running"])
            time.sleep(0.05)
            with guard:
                state["running"] -= 1
            return object()

        return state, build

    def test_background_rebuilds_in_different_caches_never_overlap(self):
        state, build = self._overlap_tracker()
        caches = [freshness.SingleFlightTTLCache(ttl_s=60, stale_while_revalidate_s=600)
                  for _ in range(6)]
        for cache in caches:
            cache.get("k", build)
        for cache in caches:                      # age every entry past its TTL
            cache._entries["k"].built_at -= timedelta(seconds=61)
        for cache in caches:                      # the second warm-up pass
            _, meta = cache.get("k", build)
            self.assertTrue(meta["stale"])
        deadline = time.time() + 10
        while any(c._refreshing for c in caches) and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(state["builds"], 12)     # every cache did get rebuilt
        self.assertEqual(state["most"], 1)

    def test_a_blocking_build_waits_for_a_background_one(self):
        state, build = self._overlap_tracker()
        warm = freshness.SingleFlightTTLCache(ttl_s=60, stale_while_revalidate_s=600)
        cold = freshness.SingleFlightTTLCache(ttl_s=60)
        warm.get("k", build)
        warm._entries["k"].built_at -= timedelta(seconds=61)
        warm.get("k", build)                      # starts a background rebuild
        cold.get("k", build)                      # a request on a cold cache
        deadline = time.time() + 10
        while warm._refreshing and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(state["most"], 1)

    def test_a_builder_may_read_another_cache_on_its_own_thread(self):
        inner = freshness.SingleFlightTTLCache(ttl_s=60)
        outer = freshness.SingleFlightTTLCache(ttl_s=60)
        value, _ = outer.get("o", lambda: inner.get("i", lambda: 7)[0] + 1)
        self.assertEqual(value, 8)


if __name__ == "__main__":
    unittest.main()
