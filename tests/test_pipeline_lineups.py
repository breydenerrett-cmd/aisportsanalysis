"""Tests for src/pipeline/lineups.py.

TestLeakGuard is the one that matters. Season-to-date splits applied to an
earlier game in the same season tell you how the pitcher went on to perform, and
that single mistake is the most effective way there is to build a backtest that
looks brilliant and loses money. It has to raise, not warn.
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.pipeline import lineups


def slot(person_id, order=1, name=None):
    return {"person_id": person_id, "order": order, "name": name or f"P{person_id}"}


def hands(**mapping):
    return {str(k): {"bats": v} for k, v in mapping.items()}


class TestLeakGuard(unittest.TestCase):

    def record(self, days_ago=0):
        stamp = datetime.now(timezone.utc) - timedelta(days=days_ago)
        return {"as_of": stamp.isoformat(), "splits": {}}

    def test_using_a_split_for_an_earlier_date_raises(self):
        with self.assertRaises(lineups.LineupError) as ctx:
            lineups.assert_point_in_time(self.record(), "2026-06-01")
        self.assertIn("had not happened yet", str(ctx.exception))

    def test_the_error_names_the_correct_alternative(self):
        # A guard that only says "no" teaches people to delete the guard.
        with self.assertRaises(lineups.LineupError) as ctx:
            lineups.assert_point_in_time(self.record(), "2026-06-01")
        self.assertIn("game logs", str(ctx.exception))

    def test_today_is_allowed(self):
        today = datetime.now(timezone.utc).date().isoformat()
        lineups.assert_point_in_time(self.record(), today)

    def test_a_later_date_is_allowed(self):
        record = self.record(days_ago=5)
        lineups.assert_point_in_time(
            record, datetime.now(timezone.utc).date().isoformat())

    def test_a_record_with_no_stamp_cannot_be_checked_and_raises(self):
        # Silently allowing an unstampable record would make the guard optional
        # for exactly the data most likely to be wrong.
        with self.assertRaises(lineups.LineupError) as ctx:
            lineups.assert_point_in_time({"splits": {}}, "2026-08-28")
        self.assertIn("no as_of", str(ctx.exception))


class TestPlatoonSplit(unittest.TestCase):

    def record(self, left_ops=0.800, right_ops=0.600, left_bf=200, right_bf=300):
        return {"splits": {
            lineups.VS_LEFT: {"ops": left_ops, "batters_faced": left_bf},
            lineups.VS_RIGHT: {"ops": right_ops, "batters_faced": right_bf}}}

    def test_a_real_split_is_reported_with_its_direction(self):
        split = lineups.platoon_split(self.record())
        self.assertTrue(split["usable"])
        self.assertAlmostEqual(split["gap"], 0.200, places=3)
        self.assertEqual(split["weaker_against"], "L")

    def test_the_direction_inverts_correctly(self):
        split = lineups.platoon_split(self.record(left_ops=0.600, right_ops=0.800))
        self.assertEqual(split["weaker_against"], "R")

    def test_a_thin_side_makes_the_whole_split_unusable(self):
        # 30 batters faced is a fortnight. A "split" built on it is a handful of
        # at-bats wearing the costume of a tendency.
        split = lineups.platoon_split(self.record(left_bf=30))
        self.assertFalse(split["usable"])
        self.assertIn("30 batters faced", split["reason"])

    def test_both_sides_must_clear_the_gate(self):
        self.assertFalse(lineups.platoon_split(self.record(right_bf=10))["usable"])

    def test_missing_ops_is_unusable_rather_than_zero(self):
        record = self.record()
        record["splits"][lineups.VS_LEFT]["ops"] = None
        self.assertFalse(lineups.platoon_split(record)["usable"])

    def test_an_empty_record_is_unusable_not_an_error(self):
        self.assertFalse(lineups.platoon_split({})["usable"])


class TestHandedness(unittest.TestCase):

    def test_counts_by_side(self):
        lineup = [slot(1), slot(2), slot(3), slot(4)]
        counts = lineups.lineup_handedness(lineup, hands(**{"1": "L", "2": "R",
                                                            "3": "S", "4": "L"}))
        self.assertEqual((counts["L"], counts["R"], counts["S"]), (2, 1, 1))
        self.assertEqual(counts["known"], 4)

    def test_unknown_hitters_are_counted_separately_not_guessed(self):
        counts = lineups.lineup_handedness([slot(1), slot(99)], hands(**{"1": "L"}))
        self.assertEqual(counts["unknown"], 1)
        self.assertEqual(counts["known"], 1)


class TestPlatoonAdvantageShare(unittest.TestCase):

    def lineup(self):
        return [slot(1), slot(2), slot(3), slot(4)]

    def test_opposite_handed_hitters_have_the_advantage(self):
        result = lineups.platoon_advantage_share(
            self.lineup(), hands(**{"1": "L", "2": "L", "3": "R", "4": "R"}), "R")
        self.assertEqual(result["advantaged"], 2)
        self.assertEqual(result["share"], 0.5)

    def test_switch_hitters_always_count_as_advantaged(self):
        # That is the entire point of being one. Counting them neutral would
        # understate every lineup that carries them.
        result = lineups.platoon_advantage_share(
            self.lineup(), hands(**{"1": "S", "2": "S", "3": "R", "4": "R"}), "R")
        self.assertEqual(result["advantaged"], 2)

    def test_an_unknown_pitcher_hand_produces_no_share_and_says_why(self):
        result = lineups.platoon_advantage_share(self.lineup(), hands(), None)
        self.assertIsNone(result["share"])
        self.assertIn("throwing hand is unknown", result["reason"])

    def test_a_lineup_with_no_known_hitters_produces_no_share(self):
        result = lineups.platoon_advantage_share(self.lineup(), {}, "R")
        self.assertIsNone(result["share"])

    def test_the_share_is_over_KNOWN_hitters_not_the_whole_lineup(self):
        # Dividing by nine when only four are known understates the share and
        # would silently mute the detector on partially-known lineups.
        result = lineups.platoon_advantage_share(
            [slot(1), slot(2), slot(98), slot(99)],
            hands(**{"1": "L", "2": "L"}), "R")
        self.assertEqual(result["known"], 2)
        self.assertEqual(result["share"], 1.0)


class TestLineupVsPitcher(unittest.TestCase):

    def fake(self, per_batter):
        calls = iter(per_batter)

        def fetch(batter_id, pitcher_id, timeout=20):
            return next(calls)
        return fetch

    def line(self, ab, hits=0, hr=0, k=0):
        return {"at_bats": ab, "hits": hits, "home_runs": hr, "strikeouts": k,
                "walks": 0, "avg": None, "ops": None}

    def test_the_aggregate_is_gated_and_says_why_when_thin(self):
        original = lineups.batter_vs_pitcher
        lineups.batter_vs_pitcher = self.fake([self.line(3, 1), self.line(2, 1)])
        try:
            result = lineups.lineup_vs_pitcher([slot(1), slot(2)], 99)
        finally:
            lineups.batter_vs_pitcher = original
        self.assertFalse(result["usable"])
        self.assertEqual(result["total_at_bats"], 5)
        self.assertIn("only 5 career at-bats", result["reason"])

    def test_a_large_aggregate_is_usable_and_carries_its_average(self):
        original = lineups.batter_vs_pitcher
        lineups.batter_vs_pitcher = self.fake(
            [self.line(40, 12), self.line(30, 8)])
        try:
            result = lineups.lineup_vs_pitcher([slot(1), slot(2)], 99)
        finally:
            lineups.batter_vs_pitcher = original
        self.assertTrue(result["usable"])
        self.assertEqual(result["total_at_bats"], 70)
        self.assertEqual(result["aggregate_avg"], round(20 / 70, 3))
        self.assertIsNone(result["reason"])

    def test_no_pitcher_means_no_calls_and_no_fabricated_line(self):
        result = lineups.lineup_vs_pitcher([slot(1)], None)
        self.assertEqual(result["batters"], [])
        self.assertEqual(result["total_at_bats"], 0)


class TestCacheIO(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.dir.cleanup()

    def test_a_corrupt_cache_is_named_rather_than_silently_reset(self):
        path = Path(self.dir.name) / "h.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(lineups.LineupError):
            lineups._read_json(path, {})

    def test_a_missing_cache_returns_the_default(self):
        self.assertEqual(lineups._read_json(Path(self.dir.name) / "no.json", {}), {})

    def test_round_trip(self):
        path = Path(self.dir.name) / "h.json"
        lineups._write_json(path, {"1": {"bats": "L"}})
        self.assertEqual(lineups._read_json(path, {}), {"1": {"bats": "L"}})


if __name__ == "__main__":
    unittest.main()
