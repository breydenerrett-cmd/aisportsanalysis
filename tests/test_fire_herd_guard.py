"""Fire-now herd guard (red team 2026-10-19).

Twenty simultaneous unsigned "Fire now" taps all missed the cache and queued on the build gate, and each then ran
its own full load, because the cache was not looked at again once the gate was held. The loaders now double-check
the cache inside the gate, and an unsigned caller gets a tighter per-address allowance.

The loader half needs no FastAPI (Linux CI); the route half is skipped where it is absent.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from datetime import timedelta
from unittest import mock

from src.appstate import freshness
from src.hounds.interact import common, drill, fire

try:
    from fastapi import HTTPException, Response
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False


def run_together(n, fn):
    """n threads released at once; returns their results (or exceptions) in order."""
    start = threading.Barrier(n)
    results = [None] * n

    def work(i):
        start.wait()
        try:
            results[i] = fn()
        except Exception as exc:  # noqa: BLE001
            results[i] = exc
    threads = [threading.Thread(target=work, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    return results


class FireHerdTests(unittest.TestCase):
    def setUp(self):
        fire.clear_cache()
        self.addCleanup(fire.clear_cache)

    def test_twenty_concurrent_cached_games_make_one_load(self):
        calls = []

        def slow_load(sports, now, rows_for=None):
            calls.append(1)
            time.sleep(0.2)
            return {"g": object()}

        with mock.patch.object(fire, "load_games", slow_load):
            now = common.now_utc()
            out = run_together(20, lambda: fire.cached_games(("MLB",), now))
        self.assertEqual(len(calls), 1, "every waiter must re-read the cache the builder filled")
        self.assertTrue(all(isinstance(o, dict) for o in out))
        self.assertEqual(len({id(o) for o in out}), 1)

    def test_twenty_concurrent_default_stores_make_one_load(self):
        from src.hounds.pack import base
        calls = []

        def slow_load(**kw):
            calls.append(1)
            time.sleep(0.2)
            return object()

        with mock.patch.object(base, "load_stores", slow_load):
            now = common.now_utc()
            out = run_together(20, lambda: fire.default_stores(now))
        self.assertEqual(len(calls), 1)
        self.assertEqual(len({id(o) for o in out}), 1)

    def test_a_fresh_cache_never_touches_the_gate(self):
        with mock.patch.object(fire, "load_games", lambda *a, **k: {"g": 1}):
            fire.cached_games(("MLB",), common.now_utc())
        with mock.patch.object(fire, "_heavy", side_effect=AssertionError("gate taken on a hit")):
            self.assertEqual(fire.cached_games(("MLB",), common.now_utc()), {"g": 1})

    def test_the_load_runs_inside_the_gate(self):
        seen = []

        def load(sports, now, rows_for=None):
            seen.append(freshness.build_stats()["running"])
            return {}

        with mock.patch.object(fire, "load_games", load):
            fire.cached_games(("MLB",), common.now_utc())
        self.assertEqual(seen, [1])


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class FireRouteGuardTests(unittest.TestCase):
    def setUp(self):
        from api import hounds_interact as api
        self.api = api

    def test_unsigned_fire_is_limited_tighter_than_signed(self):
        from src.appstate import ratelimit
        api = self.api
        api._fire_limiter = ratelimit.FixedWindowLimiter(limit=20, window_s=60.0)
        api._rl_fire = ratelimit.limiter_dependency(api._fire_limiter)
        api._fire_unsigned_limiter = ratelimit.FixedWindowLimiter(limit=api.FIRE_UNSIGNED_PER_MIN, window_s=60.0)
        api._rl_fire_unsigned = ratelimit.limiter_dependency(api._fire_unsigned_limiter)
        request = mock.Mock(headers={"fly-client-ip": "203.0.113.9"}, client=mock.Mock(host="10.0.0.1"))
        with mock.patch.object(api.auth_mod, "optional_user_id", lambda authorization: None):
            for _ in range(api.FIRE_UNSIGNED_PER_MIN):
                api._rl_fire_route(request, None)
            with self.assertRaises(HTTPException) as ctx:
                api._rl_fire_route(request, None)
        self.assertEqual(ctx.exception.status_code, 429)
        # a signed-in caller from the same address is not held to the unsigned number
        with mock.patch.object(api.auth_mod, "optional_user_id", lambda authorization: 7):
            api._rl_fire_route(request, "Bearer x")


if __name__ == "__main__":
    unittest.main()
