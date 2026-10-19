"""Drill load guards (red team 2026-10-19).

One 30-day house drill peaked at 686 MB and ran 55 s on a 1 GB machine, so a second drill beside it (or a
page-cache rebuild beside it) is an out-of-memory kill. The guards: one drill at a time process-wide (a second is
a 429 with Retry-After, not a queue), the whole house replay inside the build gate, the window capped at 30 days,
the data let go afterwards, and a smaller per-user allowance.

The store half needs no FastAPI (Linux CI); the route half is skipped where it is absent.
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


class DrillGuardTests(unittest.TestCase):
    def setUp(self):
        drill.clear_cache()
        self.addCleanup(drill.clear_cache)
        from tests.test_house_pack_hounds import START, basic_stores, mlb_game
        from src.hounds import pack as pack_mod, pack_run
        from src.hounds.learning import champions
        self.stores = basic_stores()
        self.stores.mlb_games.append(mlb_game(900001, "2026-09-20", "NYY", "BOS", 2, 4))
        self.stores.finalize()
        self.now = START + timedelta(days=2)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger = os.path.join(self._tmp.name, "hounds_house_v1.jsonl")
        for p in (mock.patch.object(pack_run, "ledger_path", lambda path=None: path or self.ledger),
                  mock.patch.object(champions, "champion_versions", lambda hs, path: tuple(hs))):
            p.start()
            self.addCleanup(p.stop)
        h = pack_mod.BY_ID["chalk_chihuahua"]
        self.dog = common.Dog(id=h.id, kind=common.KIND_HOUSE, name=h.name, house=h, root_id=h.id)
        self.pack_run = pack_run

    def test_a_second_drill_while_one_runs_is_a_429_with_retry_after(self):
        inside = threading.Event()
        release = threading.Event()
        real_run = self.pack_run.run

        def slow_run(*a, **k):
            inside.set()
            release.wait(10)
            return real_run(*a, **k)

        first = {}

        def first_drill():
            with mock.patch.object(self.pack_run, "run", slow_run):
                first["out"] = drill.drill(days=7, dog=self.dog, now=self.now, stores=self.stores)

        t = threading.Thread(target=first_drill)
        t.start()
        try:
            self.assertTrue(inside.wait(10))
            with self.assertRaises(drill.DrillError) as ctx:
                drill.drill(days=14, dog=self.dog, now=self.now, stores=self.stores)
            self.assertEqual((ctx.exception.status, ctx.exception.code), (429, "drill_busy"))
            self.assertEqual(ctx.exception.retry_after, drill.BUSY_RETRY_AFTER_S)
        finally:
            release.set()
            t.join(30)
        self.assertEqual(first["out"]["record"]["graded"], 1)
        # and the slot is free again afterwards
        self.assertEqual(drill.drill(days=14, dog=self.dog, now=self.now, stores=self.stores)["days"], 14)

    def test_the_slot_is_released_when_the_drill_fails(self):
        with mock.patch.object(drill, "run_house", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                drill.drill(days=7, dog=self.dog, now=self.now, stores=self.stores)
        self.assertEqual(drill.drill(days=7, dog=self.dog, now=self.now, stores=self.stores)["days"], 7)

    def test_the_whole_house_replay_holds_the_build_gate(self):
        seen = {}
        real_run, real_settle = self.pack_run.run, None
        from src.hounds import pack_settle
        real_settle = pack_settle.settle

        def run(*a, **k):
            seen["run"] = freshness.build_stats()["running"]
            return real_run(*a, **k)

        def settle(*a, **k):
            seen["settle"] = freshness.build_stats()["running"]
            return real_settle(*a, **k)

        with mock.patch.object(self.pack_run, "run", run), mock.patch.object(pack_settle, "settle", settle):
            drill.drill(days=7, dog=self.dog, now=self.now, stores=self.stores)
        self.assertEqual(seen, {"run": 1, "settle": 1})
        self.assertEqual(freshness.build_stats()["running"], 0)

    def test_data_is_collected_after_a_drill(self):
        with mock.patch("src.hounds.interact.drill.gc.collect") as collect:
            drill.drill(days=7, dog=self.dog, now=self.now, stores=self.stores)
        collect.assert_called()

    def test_the_window_is_capped_at_30_days(self):
        self.assertEqual(max(drill.DAYS_CHOICES), 30)
        for days in (31, 60, 365):
            with self.assertRaises(drill.DrillError):
                drill.window(days, self.now)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class RouteGuardTests(unittest.TestCase):
    def setUp(self):
        from api import hounds_interact as api
        self.api = api

    def test_busy_drill_answers_429_with_a_retry_after_header(self):
        busy = drill.DrillError("drill_busy", "another drill is running", 429, retry_after=30)
        with mock.patch.object(drill, "drill", side_effect=busy):
            with self.assertRaises(HTTPException) as ctx:
                self.api.run_drill(self.api.DrillRequest(dog_id=None, days=7, spec={}), Response(),
                                   current_user=mock.Mock(id=1), _rl=None)
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.headers, {"Retry-After": "30"})
        self.assertEqual(ctx.exception.detail["error"], "drill_busy")

    def test_the_drill_allowance_is_five_an_hour(self):
        self.assertEqual(self.api.DRILL_PER_USER_PER_HOUR, 5)
        self.assertEqual(self.api._drill_limiter.limit, 5)


if __name__ == "__main__":
    unittest.main()
