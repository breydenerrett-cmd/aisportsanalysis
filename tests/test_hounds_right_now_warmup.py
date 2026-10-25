"""The startup warm-up for the "right now" caches (owner, 2026-10-25). The first right-now call after a deploy paid a cold
board and house-store load. The warm-up pre-builds those same caches for today on one daemon thread. It must run the
injected steps, count and swallow failures, and never raise.
"""

from __future__ import annotations

import threading
import unittest
from pathlib import Path

from src.hounds.interact import right_now

ROOT = Path(__file__).resolve().parent.parent


class TheStartupWarmup(unittest.TestCase):
    def test_it_builds_the_house_stores_once_and_each_distinct_board_once(self):
        stores, boards = [], []
        hounds = [{"id": "a", "spec": {"sports": ["NFL", "MLB"]}}, {"id": "b", "spec": {"sports": ["MLB", "NFL"]}},
                  {"id": "c", "spec": {"sports": ["UFC"]}}, {"id": "d", "spec": None}]
        report = right_now.warm_today(hounds=hounds, stores_fn=lambda now: stores.append(now),
                                      games_fn=lambda sports, now: boards.append(tuple(sports)))
        self.assertEqual(len(stores), 1)
        self.assertEqual(sorted(boards), [("MLB", "NFL"), ("UFC",)])
        self.assertEqual(report, {"stores": True, "sport_sets": 2, "errors": 0})

    def test_a_failing_step_is_counted_and_never_raised(self):
        def boom(*_a, **_k):
            raise RuntimeError("store is down")
        boards = []
        hounds = [{"id": "a", "spec": {"sports": ["NFL"]}}, "not a row", {"id": "c", "spec": {"sports": ["MLB"]}}]
        report = right_now.warm_today(hounds=hounds, stores_fn=boom,
                                      games_fn=lambda sports, now: boards.append(sports) if sports == ["MLB"] else boom())
        self.assertFalse(report["stores"])
        self.assertEqual(boards, [["MLB"]])            # the good board still warmed after the bad one failed
        self.assertGreaterEqual(report["errors"], 2)

    def test_the_background_thread_runs_the_steps_and_returns_at_once(self):
        ran = []
        thread = right_now.start_background_warmup(hounds=[{"id": "a", "spec": {"sports": ["NFL"]}}],
                                                   stores_fn=lambda now: ran.append("stores"),
                                                   games_fn=lambda sports, now: ran.append(tuple(sports)))
        self.assertIsInstance(thread, threading.Thread)
        self.assertTrue(thread.daemon)
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(ran, ["stores", ("NFL",)])

    def test_the_background_thread_swallows_an_error_it_did_not_expect(self):
        thread = right_now.start_background_warmup(hounds=[], stores_fn=lambda now: 1 / 0)
        thread.join(5)
        self.assertFalse(thread.is_alive())

    def test_the_app_startup_hook_is_wired_to_the_warm_up(self):
        src = (ROOT / "api" / "app.py").read_text(encoding="utf-8")
        self.assertIn("def _start_right_now_warmup", src)
        self.assertIn("right_now.start_background_warmup()", src)


if __name__ == "__main__":
    unittest.main()
