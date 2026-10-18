"""Smoke and performance against the REAL ledgers (read-only).

Numeric assertions live in tests/test_hounds_stats.py against a fixture; here
only shape, coverage and cost are checked, so a ledger growing by a day never
breaks this file. The cold build streams ~1,000,000 odds rows and ~39,000
decision rows; the routes must then answer from the cache.
"""

from __future__ import annotations

import json
import time
import tracemalloc
import unittest

from src.hounds import contract, stats
from src.hounds.ledgers import FIRST_OPEN_DAY, Sources

WARM_BUDGET_SECONDS = 2.0
COLD_PEAK_BUDGET_BYTES = 250 * 1024 * 1024    # python-allocated peak while building


class LiveBook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Sources.default()
        before = cls.src.fingerprint()
        stats.clear_cache()
        tracemalloc.start()
        started = time.time()
        cls.book = stats.get_book(cls.src)
        cls.cold_seconds = time.time() - started
        _, cls.cold_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        cls.unchanged = (before == cls.src.fingerprint())

    def test_the_build_wrote_nothing(self):
        self.assertTrue(self.unchanged)

    def test_cold_build_memory_is_bounded(self):
        self.assertLess(self.cold_peak, COLD_PEAK_BUDGET_BYTES,
                        f"cold build peaked at {self.cold_peak / 1e6:.0f} MB")

    def test_warm_leaderboard_answers_under_two_seconds(self):
        started = time.time()
        for _ in range(20):
            payload = contract.leaderboard_payload(stats.leaderboard(stats.get_book(self.src)),
                                                   self.book.as_of)
            json.dumps(payload)
        per_call = (time.time() - started) / 20
        self.assertLess(per_call, WARM_BUDGET_SECONDS)

    def test_every_engine_hound_has_a_real_forward_record(self):
        for hid in ("beagle", "basset", "collie", "pointer", "setter", "whippet",
                    "terrier", "spaniel"):
            with self.subTest(hid):
                s = self.book.hounds[hid].summary
                self.assertGreaterEqual(s.record.bets, 50)
                self.assertEqual(s.record.bets, s.record.wins + s.record.losses
                                 + s.record.pushes + s.record.voids)
                self.assertIn(s.verdict.label, ("TOO EARLY", "BEATING THE CLOSE",
                                                "PAYING THE VIG",
                                                "NO DIFFERENT FROM THE MARKET"))
                self.assertTrue(s.rule_text)

    def test_baselines_do_not_lead_the_board(self):
        board = stats.leaderboard(self.book)
        kinds = [s.kind for s in board]
        first_baseline = kinds.index("baseline") if "baseline" in kinds else len(kinds)
        self.assertNotIn("house", kinds[first_baseline:])

    def test_old_dog_is_in_the_graveyard_with_its_cause(self):
        dog = {s.id: s for s in stats.graveyard(self.book)}["old-dog"]
        self.assertEqual(dog.status, "retired")
        self.assertIn("paused 2026-10-16", dog.retired.cause)
        self.assertEqual(dog.verdict.label, "NOT MEASURED")
        self.assertGreater(dog.record.bets, 50)

    def test_sealed_window_never_appears(self):
        for data in self.book.hounds.values():
            for row in data.bets:
                self.assertGreaterEqual(row.date, FIRST_OPEN_DAY)
            for point in data.series[1:]:
                self.assertGreaterEqual(point.date, FIRST_OPEN_DAY)

    def test_series_are_zero_started_and_consistent_with_the_record(self):
        for hid, data in self.book.hounds.items():
            if not data.series:
                continue
            with self.subTest(hid):
                self.assertEqual(data.series[0].cum_units_recorded_price, 0.0)
                self.assertEqual(data.series[0].bets_settled, 0)
                self.assertAlmostEqual(data.series[-1].cum_units_recorded_price,
                                       data.summary.record.units_recorded_price, places=3)
                self.assertEqual(sum(p.bets_settled for p in data.series),
                                 data.summary.record.bets)

    def test_stream_has_refusals_and_is_newest_first(self):
        stream = self.book.stream
        self.assertGreater(len(stream), 100)
        stamps = [i.decided_utc for i in stream]
        self.assertEqual(stamps, sorted(stamps, reverse=True))
        self.assertTrue(any(i.refused for i in stream))

    def test_most_house_bets_verify_against_the_captured_odds(self):
        verified = [d.summary for h, d in self.book.hounds.items()
                    if h in ("beagle", "pointer", "setter")]
        self.assertTrue(all(s.verified for s in verified),
                        [(s.id, s.verified_share, s.checkable_share) for s in verified])


if __name__ == "__main__":
    unittest.main()
