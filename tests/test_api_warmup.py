"""api/warmup.py: the background cache warm-up that covers the cold-cache
first-request problem (10-13s, once a 502 -- measured on staging
2026-09-21). See that module's docstring for the full problem statement.

No real data, no network, no sleeps longer than ~0.1s: every test here uses
injected fake items/dates/clock/events instead of the production builders or
a real interval wait.
"""

from __future__ import annotations

import logging
import threading
import time
import unittest
from datetime import datetime, timezone

from api import warmup


class WarmDatesTests(unittest.TestCase):

    def test_dedupes_when_utc_and_eastern_agree(self):
        """Midday UTC: UTC-today and Eastern-today are the same calendar
        date, so the four candidates collapse to two, not four."""
        now = datetime(2026, 9, 21, 15, 0, 0, tzinfo=timezone.utc)
        dates = warmup.warm_dates(now)
        self.assertEqual(dates, ["2026-09-21", "2026-09-22"])

    def test_covers_the_utc_midnight_rollover(self):
        """01:00 UTC on 2026-09-21 is still 2026-09-20 evening in Eastern --
        the exact rollover window a cold cache bites a real visitor in.
        Both UTC-today and Eastern-today (and each one's tomorrow) must be
        covered so neither zone's rollover leaves a cold key unwarmed."""
        now = datetime(2026, 9, 21, 1, 0, 0, tzinfo=timezone.utc)
        dates = warmup.warm_dates(now)
        self.assertIn("2026-09-20", dates)  # Eastern-today
        self.assertIn("2026-09-21", dates)  # UTC-today
        self.assertIn("2026-09-22", dates)  # UTC-tomorrow
        self.assertEqual(dates, sorted(set(dates)))  # deduped, sorted

    def test_naive_datetime_is_treated_as_utc(self):
        now = datetime(2026, 9, 21, 15, 0, 0)
        dates = warmup.warm_dates(now)
        self.assertEqual(dates, ["2026-09-21", "2026-09-22"])


class _ListLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class RunWarmupPassTests(unittest.TestCase):

    def _logger(self):
        log = logging.getLogger("test.warmup." + self.id())
        log.setLevel(logging.DEBUG)
        handler = _ListLogHandler()
        log.addHandler(handler)
        return log, handler

    def test_calls_every_item_for_every_date(self):
        calls = []
        items = [
            ("alpha", lambda date: calls.append(("alpha", date))),
            ("beta", lambda date: calls.append(("beta", date))),
        ]
        dates = ["2026-09-21", "2026-09-22"]

        warmup.run_warmup_pass(items, dates)

        self.assertEqual(calls, [
            ("alpha", "2026-09-21"), ("beta", "2026-09-21"),
            ("alpha", "2026-09-22"), ("beta", "2026-09-22"),
        ])

    def test_one_builder_failing_does_not_stop_the_rest(self):
        calls = []

        def boom(date):
            raise RuntimeError(f"builder blew up for {date}")

        items = [
            ("first", lambda date: calls.append(("first", date))),
            ("broken", boom),
            ("last", lambda date: calls.append(("last", date))),
        ]

        # Must not raise -- a warm-up failure never reaches a caller.
        warmup.run_warmup_pass(items, ["2026-09-21"])

        self.assertEqual(calls, [("first", "2026-09-21"), ("last", "2026-09-21")])

    def test_failure_is_logged_but_success_continues_to_be_called(self):
        log, handler = self._logger()

        def boom(date):
            raise ValueError("nope")

        items = [("broken", boom), ("ok", lambda date: None)]
        warmup.run_warmup_pass(items, ["2026-09-21"], log=log)

        messages = [r.getMessage() for r in handler.records]
        self.assertTrue(any("broken" in m and "failed" in m for m in messages))
        self.assertTrue(any("ok" in m and "ok" in m for m in messages))

    def test_multiple_builders_all_failing_still_completes(self):
        def boom(date):
            raise RuntimeError("always fails")

        items = [("a", boom), ("b", boom), ("c", boom)]
        # Must complete without raising for every item on every date.
        warmup.run_warmup_pass(items, ["2026-09-21", "2026-09-22"])


class WarmIntervalSecondsTests(unittest.TestCase):

    def test_default_when_unset(self):
        self.assertEqual(warmup.warm_interval_seconds({}), warmup.DEFAULT_WARM_INTERVAL_SECONDS)

    def test_default_when_blank(self):
        self.assertEqual(
            warmup.warm_interval_seconds({"WARM_INTERVAL_SECONDS": "  "}),
            warmup.DEFAULT_WARM_INTERVAL_SECONDS)

    def test_env_override(self):
        self.assertEqual(
            warmup.warm_interval_seconds({"WARM_INTERVAL_SECONDS": "45"}), 45.0)

    def test_zero_is_returned_unchanged_disable_decision_is_the_callers(self):
        self.assertEqual(
            warmup.warm_interval_seconds({"WARM_INTERVAL_SECONDS": "0"}), 0.0)

    def test_garbage_falls_back_to_default(self):
        self.assertEqual(
            warmup.warm_interval_seconds({"WARM_INTERVAL_SECONDS": "not-a-number"}),
            warmup.DEFAULT_WARM_INTERVAL_SECONDS)


class StartBackgroundWarmupTests(unittest.TestCase):

    def test_interval_zero_disables_no_thread_started(self):
        calls = []

        def items_factory():
            calls.append(1)
            return []

        thread = warmup.start_background_warmup(
            interval_s=0.0, items_factory=items_factory)

        self.assertIsNone(thread)
        self.assertEqual(calls, [])  # never even asked for the warm list

    def test_negative_interval_disables(self):
        thread = warmup.start_background_warmup(
            interval_s=-5.0, items_factory=lambda: [])
        self.assertIsNone(thread)

    def test_start_returns_immediately_without_waiting_for_a_pass(self):
        """`thread.start()` scheduling the thread must not itself block on
        the first warm-up pass -- app startup depends on that. Simulated
        with a slow-ish (but test-fast, ~0.1s) first item; the call to
        start_background_warmup must return long before that completes."""
        pass_started = threading.Event()
        release = threading.Event()

        def slow_item(date):
            pass_started.set()
            release.wait(timeout=2.0)

        items_factory_called = threading.Event()

        def items_factory():
            items_factory_called.set()
            return [("slow", slow_item)]

        stop_event = threading.Event()
        started = time.monotonic()
        thread = warmup.start_background_warmup(
            interval_s=100.0, items_factory=items_factory,
            stop_event=stop_event)
        elapsed = time.monotonic() - started

        try:
            self.assertIsNotNone(thread)
            self.assertTrue(thread.daemon)
            self.assertLess(elapsed, 0.5)  # did not wait for the pass
            self.assertTrue(pass_started.wait(timeout=2.0),
                            "background thread never started its pass")
        finally:
            release.set()
            stop_event.set()
            thread.join(timeout=2.0)

    def test_thread_runs_the_injected_items_against_injected_dates(self):
        calls = []
        done = threading.Event()

        def item_a(date):
            calls.append(("a", date))

        def item_b(date):
            calls.append(("b", date))
            done.set()  # second item on the single date -- pass complete

        stop_event = threading.Event()
        thread = warmup.start_background_warmup(
            interval_s=100.0, items_factory=lambda: [("a", item_a), ("b", item_b)],
            stop_event=stop_event)
        try:
            self.assertTrue(done.wait(timeout=2.0), "warm-up pass never completed")
        finally:
            stop_event.set()
            thread.join(timeout=2.0)
        # Whatever dates warm_dates() picked (unmocked -- real "today"), the
        # two items must have been called as a pair, in order, once per date.
        self.assertTrue(calls)
        self.assertEqual(len(calls) % 2, 0)
        self.assertEqual([c[0] for c in calls], ["a", "b"] * (len(calls) // 2))
        # Both items saw the same date each time they ran as a pair.
        for i in range(0, len(calls), 2):
            self.assertEqual(calls[i][1], calls[i + 1][1])


class WarmupLoopIntervalTests(unittest.TestCase):
    """Exercises `_warmup_loop` directly (not via start_background_warmup)
    to prove it runs more than one pass and stops promptly on the stop
    event -- with a short interval and a bounded join timeout instead of any
    real sleep in the test itself."""

    def test_runs_again_after_the_interval_and_stops_on_event(self):
        pass_count = []
        stop_event = threading.Event()

        def items_factory():
            pass_count.append(1)
            if len(pass_count) >= 3:
                stop_event.set()
            return []

        thread = threading.Thread(
            target=warmup._warmup_loop,
            kwargs=dict(items_factory=items_factory, interval_s=0.01,
                       stop_event=stop_event, dates_fn=lambda: ["2026-09-21"]),
            daemon=True)
        thread.start()
        thread.join(timeout=2.0)

        self.assertFalse(thread.is_alive())
        self.assertGreaterEqual(len(pass_count), 3)

    def test_a_crashing_items_factory_does_not_kill_the_loop(self):
        pass_count = []
        stop_event = threading.Event()

        def items_factory():
            pass_count.append(1)
            if len(pass_count) >= 2:
                stop_event.set()
            raise RuntimeError("items_factory is broken this run")

        thread = threading.Thread(
            target=warmup._warmup_loop,
            kwargs=dict(items_factory=items_factory, interval_s=0.01,
                       stop_event=stop_event, dates_fn=lambda: ["2026-09-21"]),
            daemon=True)
        thread.start()
        thread.join(timeout=2.0)

        self.assertFalse(thread.is_alive())
        self.assertGreaterEqual(len(pass_count), 2)


try:  # the CI test gate installs no fastapi (same guard as test_api_card.py)
    import fastapi  # noqa: F401
    _HAVE_FASTAPI = True
except Exception:  # noqa: BLE001
    _HAVE_FASTAPI = False


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class DefaultItemsTests(unittest.TestCase):
    """Only checks the SHAPE of the production wiring (names, callability,
    that it imports cleanly) -- not real behaviour, which needs real data
    and is covered by the local timing check instead, not unittest."""

    def test_returns_one_callable_builder_per_declared_name(self):
        items = warmup._default_items()
        names = [name for name, _builder in items]
        self.assertEqual(tuple(names), warmup.WARM_ITEM_NAMES)
        for _name, builder in items:
            self.assertTrue(callable(builder))


class WarmupStatusTests(unittest.TestCase):
    """2026-09-22: /health reports warm-up progress, so deploy checks wait
    for the first pass instead of racing it (the 01:15Z /today 502)."""

    def test_a_completed_pass_is_counted_even_when_an_item_fails(self):
        before = warmup.status()["passes_completed"]
        stop = threading.Event()

        def boom(_date):
            stop.set()
            raise RuntimeError("builder failed")

        warmup._warmup_loop(items_factory=lambda: [("x", boom)], interval_s=60,
                            stop_event=stop, dates_fn=lambda: ["2026-09-22"])
        after = warmup.status()
        self.assertEqual(after["passes_completed"], before + 1)
        self.assertFalse(after["running"])
        self.assertIsNotNone(after["last_pass_utc"])

    @unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
    def test_health_carries_the_warmup_block_without_changing_status(self):
        from fastapi.testclient import TestClient
        from api.app import app
        body = TestClient(app).get("/health").json()
        self.assertIn("warmup", body)
        self.assertIn("passes_completed", body["warmup"])


if __name__ == "__main__":
    unittest.main()
