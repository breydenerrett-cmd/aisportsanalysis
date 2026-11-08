"""The quiz's impact meter (src/hounds/quiz/impact.py + drill.impact_windows). No FastAPI needed.

Fixture slate: 2026-10-20 (tests/_hounds_user_fixtures.py), Boston at Seattle, the away side +120, Boston wins. Asked on 2026-10-22 the
last completed day is 10-21, so the 1-day window is empty, and the 3-day (10-19..10-21) and 7-day windows hold the one bet.
"""

from __future__ import annotations

import os
import re
import tempfile
import unittest
from unittest import mock

from src.hounds import user_engine as eng
from src.hounds.interact import drill
from src.hounds.quiz import impact
from tests._hounds_user_fixtures import DATE, EVENT, result_row, standard_rows, utc

NOW = utc("2026-10-22T12:00:00Z")
PK = "900001"
INDEX = {EVENT: {"game_pk": PK}}
RESULTS = {PK: result_row(PK, DATE, "BOS", "SEA", 5, 3)}
DOGS = {"sports": ["MLB"], "personality": "underdog_hunter", "markets": ["moneyline"], "price_comfort": "plus"}
BANNED = (r"\bbeta\b", r"\bnew\b", r"\bedge\b", r"\block\b", r"\bclv\b", r"nothing cleared the bar", r"\bprofit")


def inject(**over):
    out = dict(rows_by_date={DATE: standard_rows()}, mlb_results=RESULTS, nfl_results=lambda d: {}, game_pk_index=INDEX)
    out.update(over)
    return out


class TheMeter(unittest.TestCase):
    def setUp(self):
        drill.clear_cache()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        ledger = os.path.join(self._tmp.name, "hounds_user_v1.jsonl")
        patch = mock.patch.object(eng, "ledger_path", lambda p=None: p or ledger)
        patch.start()
        self.addCleanup(patch.stop)

    def measure(self, answers, previous=None, **kw):
        return impact.measure(answers, previous, now=NOW, **inject(**kw))

    def test_one_line_per_window_and_the_empty_day_says_it_would_not_have_bet(self):
        out = self.measure(DOGS)
        self.assertTrue(out["available"])
        lines = [w["line"] for w in out["windows"]]
        self.assertEqual([w["days"] for w in out["windows"]], [1, 3, 7])
        self.assertEqual(lines[0], "Last day: would not have bet")
        self.assertEqual(lines[1], "Last 3 days: 1 bet, 1-0, +1.2u")
        self.assertEqual(lines[2], "Last 7 days: 1 bet, 1-0, +1.2u")

    def test_the_delta_is_this_answer_against_the_one_before(self):
        before = {"sports": ["MLB"], "personality": "chalk_eater", "markets": ["moneyline"]}
        out = self.measure(DOGS, before)
        self.assertIsNotNone(out["delta"])
        self.assertRegex(out["delta"]["line"], r"^this choice: [+-]\d+ bets?, [+-]\d+\.\du over 7 days$|^this choice: no change over 7 days$")
        self.assertEqual(out["delta"]["bets"], out["windows"][2]["bets"] - self.measure(before)["windows"][2]["bets"])

    def test_the_same_spec_before_and_after_has_no_delta(self):
        self.assertIsNone(self.measure(DOGS, dict(DOGS))["delta"])
        self.assertIsNone(self.measure(DOGS)["delta"])

    def test_one_pass_serves_both_specs_and_a_repeat_is_cached_by_spec(self):
        calls = []
        real = drill.run_user_many

        def spy(hounds, days, **kw):
            calls.append((len(hounds), days))
            return real(hounds, days, **kw)
        with mock.patch.object(drill, "run_user_many", spy):
            self.measure(DOGS, {"sports": ["MLB"], "personality": "chalk_eater", "markets": ["moneyline"]})
            self.assertEqual(calls, [(2, 7)])                          # the spec and the one before, one 7-day pass
        # injected rows are never cached (the tests' own data), so check the cache with the real store off: patch the replay
        drill.clear_cache()
        counted = []

        def fake(hounds, days, **kw):
            counted.append(len(hounds))
            return {h["id"]: {"record_by_day": []} for h in hounds}
        from src.hounds.interact import board_split
        with mock.patch.object(drill, "run_user_many", fake), mock.patch.object(board_split, "ensure", lambda *a, **k: None):
            impact.measure(DOGS, None, now=NOW)
            impact.measure(DOGS, None, now=NOW)
        self.assertEqual(counted, [1])

    def test_a_busy_replay_slot_is_a_busy_error_not_a_hang(self):
        self.assertTrue(drill._drill_slot.acquire(blocking=False))
        try:
            with self.assertRaises(drill.DrillError) as ctx, mock.patch.object(drill, "SLOT_WAIT_S", 0.05):
                self.measure(DOGS)
            self.assertEqual(ctx.exception.code, "drill_busy")
        finally:
            drill._drill_slot.release()

    def test_a_gematria_hound_gets_a_reason_and_no_lines(self):
        out = self.measure({"sports": ["MLB"], "personality": "gematria"})
        self.assertFalse(out["available"])
        self.assertEqual(out["windows"], [])
        self.assertIn("past day cannot be replayed", out["note"])

    def test_more_than_four_sports_replays_the_busiest_four_and_says_so(self):
        seen = []
        real = drill.run_user_many

        def spy(hounds, days, **kw):
            seen.extend(sorted(hounds[0]["spec"]["sports"]))
            return real(hounds, days, **kw)
        with mock.patch.object(drill, "run_user_many", spy):
            out = self.measure({"sports": ["ANY"], "personality": "chaos_agent", "markets": ["moneyline"]})
        self.assertLessEqual(len(seen), impact.MAX_SPORTS)
        self.assertIn("only, to keep this quick", out["note"])

    def test_answers_that_cannot_compose_are_not_an_error(self):
        out = self.measure("nonsense")
        self.assertIsInstance(out["windows"], list)

    def test_no_member_facing_line_uses_a_banned_word_or_a_profit_claim(self):
        out = self.measure(DOGS, {"sports": ["MLB"], "personality": "chalk_eater", "markets": ["moneyline"]})
        text = " ".join([w["line"] for w in out["windows"]] + [out["note"], (out["delta"] or {}).get("line", "")]).lower()
        for pattern in BANNED:
            self.assertIsNone(re.search(pattern, text), pattern)


class TheLineText(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(impact.window_line("Last 7 days", {"bets": 14, "wins": 8, "losses": 6, "pushes": 0, "units": 2.14}),
                         "Last 7 days: 14 bets, 8-6, +2.1u")
        self.assertEqual(impact.window_line("Last 7 days", {"bets": 3, "wins": 1, "losses": 1, "pushes": 1, "units": -0.04}),
                         "Last 7 days: 3 bets, 1-1-1, 0.0u")
        self.assertEqual(impact.window_line("Last day", {"bets": 0}), "Last day: would not have bet")
        self.assertEqual(impact.window_line("Last day", {"bets": 2, "wins": 0, "losses": 0, "pushes": 0, "units": 0}),
                         "Last day: 2 bets, not settled yet")

    def test_delta_sentence(self):
        cur, prev = {"bets": 9, "units": 1.5}, {"bets": 6, "units": 0.7}
        self.assertEqual(impact.delta_of(cur, prev)["line"], "this choice: +3 bets, +0.8u over 7 days")
        self.assertEqual(impact.delta_of(prev, cur)["line"], "this choice: -3 bets, -0.8u over 7 days")
        self.assertEqual(impact.delta_of(cur, cur)["line"], "this choice: no change over 7 days")
        self.assertIsNone(impact.delta_of(cur, None))


if __name__ == "__main__":
    unittest.main()


class TheReplayNeverRunsInsideTheRequest(unittest.TestCase):
    """2026-11-08 live check: on production the meter's replay outlasted the page's 45 s wait even over the split boards. The replay
    runs on one background worker; the request waits a little, then says "still checking" (503 board_warming) until it is remembered."""

    def setUp(self):
        from src.hounds.interact import board_split
        drill.clear_cache()
        with drill._cache_lock:
            drill._impact_jobs.clear()
        self.ensure = mock.patch.object(board_split, "ensure", lambda *a, **k: None)
        self.ensure.start()

    def tearDown(self):
        self.ensure.stop()

    def test_a_slow_replay_is_still_checking_then_the_answer(self):
        import threading
        gate = threading.Event()
        threads = []

        def slow(hounds, days, **kw):
            threads.append(threading.current_thread().name)
            gate.wait(5)
            return {h["id"]: {"record_by_day": []} for h in hounds}
        with mock.patch.object(drill, "run_user_many", slow), mock.patch.object(drill, "IMPACT_WAIT_S", 0.05):
            with self.assertRaises(drill.DrillError) as ctx:
                impact.measure(DOGS, None, now=NOW)
            self.assertEqual((ctx.exception.code, ctx.exception.status), ("board_warming", 503))
            self.assertEqual(ctx.exception.retry_after, drill.IMPACT_RETRY_AFTER_S)
            with self.assertRaises(drill.DrillError):                        # asking again does not queue a second replay
                impact.measure(DOGS, None, now=NOW)
            gate.set()
            for _ in range(100):
                with drill._cache_lock:
                    if not drill._impact_jobs:
                        break
                import time as _t
                _t.sleep(0.02)
            out = impact.measure(DOGS, None, now=NOW)
        self.assertTrue(out["available"])
        self.assertEqual(threads, ["impact-replay"])                         # one replay, on the worker, never the request's thread

    def test_a_fast_replay_answers_in_the_same_request(self):
        fake = lambda hounds, days, **kw: {h["id"]: {"record_by_day": []} for h in hounds}
        with mock.patch.object(drill, "run_user_many", fake):
            self.assertTrue(impact.measure(DOGS, None, now=NOW)["available"])

    def test_a_failed_replay_says_so_instead_of_checking_forever(self):
        def broken(hounds, days, **kw):
            raise OSError("boards unreadable")
        with mock.patch.object(drill, "run_user_many", broken):
            with self.assertRaises(drill.DrillError) as ctx:
                impact.measure(DOGS, None, now=NOW)
            self.assertEqual(ctx.exception.code, "impact_failed")
            with self.assertRaises(drill.DrillError) as again:               # remembered for a minute, not replayed on every ask
                impact.measure(DOGS, None, now=NOW)
            self.assertEqual(again.exception.code, "impact_failed")
        self.assertIn("OSError", drill.impact_stats["last_error"])

