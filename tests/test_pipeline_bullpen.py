"""Tests for src/pipeline/bullpen.py.

Availability is the value here and it is an INFERENCE, not a fact. The tests
therefore care as much about the reason attached to each rating as the rating
itself -- a verdict a reader cannot audit is worse than no verdict, because they
have no way to notice when it is wrong.
"""

import json
import tempfile
import unittest
from pathlib import Path

from src.pipeline import bullpen


def appearance(days_ago, pitches=15, innings=1.0):
    return {"days_ago": days_ago, "pitches": pitches, "innings": innings,
            "date": f"2026-08-{28 - days_ago:02d}"}


class TestInningsAreThirds(unittest.TestCase):
    """"5.1" is five and one third. Reading it as five point one is a real bug."""

    def test_whole_innings(self):
        self.assertEqual(bullpen._innings_to_float("6.0"), 6.0)

    def test_one_third(self):
        self.assertAlmostEqual(bullpen._innings_to_float("5.1"), 5 + 1 / 3)

    def test_two_thirds(self):
        self.assertAlmostEqual(bullpen._innings_to_float("0.2"), 2 / 3)

    def test_an_impossible_fraction_raises(self):
        # .3 would be three thirds, which is the next whole inning. Silently
        # accepting it would put a wrong workload into an availability call.
        with self.assertRaises(bullpen.BullpenError):
            bullpen._innings_to_float("5.3")

    def test_blank_is_zero_not_an_error(self):
        self.assertEqual(bullpen._innings_to_float(None), 0.0)


class TestAvailability(unittest.TestCase):

    def test_no_recent_work_is_available(self):
        result = bullpen.availability([])
        self.assertEqual(result["availability"], bullpen.AVAILABLE)
        self.assertIn("has not pitched", result["availability_reason"])

    def test_three_straight_days_is_likely_unavailable(self):
        result = bullpen.availability(
            [appearance(1), appearance(2), appearance(3)])
        self.assertEqual(result["availability"], bullpen.LIKELY_UNAVAILABLE)
        self.assertIn("days in a row", result["availability_reason"])

    def test_a_heavy_outing_yesterday_is_likely_unavailable(self):
        result = bullpen.availability([appearance(1, pitches=34)])
        self.assertEqual(result["availability"], bullpen.LIKELY_UNAVAILABLE)
        self.assertIn("34 pitches", result["availability_reason"])

    def test_a_light_outing_yesterday_is_still_available(self):
        result = bullpen.availability([appearance(1, pitches=12)])
        self.assertEqual(result["availability"], bullpen.AVAILABLE)
        self.assertIn("only 12", result["availability_reason"])

    def test_two_straight_days_with_real_work_is_questionable(self):
        result = bullpen.availability([appearance(1, pitches=24),
                                       appearance(2, pitches=20)])
        self.assertEqual(result["availability"], bullpen.QUESTIONABLE)

    def test_an_unknown_pitch_count_is_questionable_not_assumed(self):
        # Guessing a pitch count from innings would turn an unknown into a
        # confident rating, which is exactly the fabrication this repo forbids.
        result = bullpen.availability([appearance(1, pitches=None)])
        self.assertEqual(result["availability"], bullpen.QUESTIONABLE)
        self.assertIn("pitch count unavailable", result["availability_reason"])

    def test_a_rest_day_after_two_straight_restores_availability(self):
        result = bullpen.availability([appearance(2), appearance(3)])
        self.assertEqual(result["availability"], bullpen.AVAILABLE)

    def test_every_rating_carries_a_reason(self):
        for appearances in ([], [appearance(1)], [appearance(1, 40)],
                            [appearance(1), appearance(2), appearance(3)]):
            self.assertTrue(bullpen.availability(appearances)["availability_reason"])


class TestBoxscoreParsing(unittest.TestCase):

    BOX = {"teams": {
        "home": {"team": {"abbreviation": "DET"}, "pitchers": [1, 2],
                 "players": {
                     "ID1": {"person": {"fullName": "Starter"},
                             "stats": {"pitching": {"inningsPitched": "6.1",
                                                    "gamesStarted": 1,
                                                    "numberOfPitches": 92}}},
                     "ID2": {"person": {"fullName": "Reliever"},
                             "stats": {"pitching": {"inningsPitched": "1.0",
                                                    "gamesStarted": 0,
                                                    "numberOfPitches": 12}}}}},
        "away": {"team": {"abbreviation": "TB"}, "pitchers": [], "players": {}}}}

    def test_starters_are_marked_as_such(self):
        rows = bullpen.appearances_from_boxscore(self.BOX, "2026-08-26", 1)
        starter = [r for r in rows if r["name"] == "Starter"][0]
        self.assertTrue(starter["started"])
        self.assertAlmostEqual(starter["innings"], 6 + 1 / 3, places=3)

    def test_a_pitcher_with_no_stats_is_skipped_not_zeroed(self):
        box = json.loads(json.dumps(self.BOX))
        box["teams"]["home"]["players"]["ID2"]["stats"] = {}
        rows = bullpen.appearances_from_boxscore(box, "2026-08-26", 1)
        self.assertEqual([r["name"] for r in rows], ["Starter"])

    def test_a_missing_pitch_count_stays_none(self):
        box = json.loads(json.dumps(self.BOX))
        box["teams"]["home"]["players"]["ID2"]["stats"]["pitching"].pop("numberOfPitches")
        rows = bullpen.appearances_from_boxscore(box, "2026-08-26", 1)
        self.assertIsNone([r for r in rows if r["name"] == "Reliever"][0]["pitches"])


class TestTeamWorkload(unittest.TestCase):

    def log(self):
        return [
            {"date": "2026-08-27", "team": "NYY", "person_id": 1, "name": "A",
             "started": False, "innings": 1.0, "pitches": 34},
            {"date": "2026-08-27", "team": "NYY", "person_id": 2, "name": "B",
             "started": True, "innings": 6.0, "pitches": 95},
            {"date": "2026-08-25", "team": "NYY", "person_id": 3, "name": "C",
             "started": False, "innings": 2.0, "pitches": 28},
            {"date": "2026-08-27", "team": "BOS", "person_id": 4, "name": "D",
             "started": False, "innings": 1.0, "pitches": 10},
            {"date": "2026-08-28", "team": "NYY", "person_id": 5, "name": "E",
             "started": False, "innings": 1.0, "pitches": 10},
        ]

    def test_only_the_named_team_is_counted(self):
        work = bullpen.team_workload(self.log(), "NYY", "2026-08-28")
        self.assertEqual({r["name"] for r in work["relievers"]}, {"A", "C"})

    def test_starters_are_excluded(self):
        # A starter's outing says nothing about who is available out of the pen,
        # and folding him in would swamp the numbers that matter.
        work = bullpen.team_workload(self.log(), "NYY", "2026-08-28")
        self.assertNotIn("B", {r["name"] for r in work["relievers"]})

    def test_the_cutoff_date_itself_is_excluded(self):
        # Tonight's game has not been played. Including it would be a leak.
        work = bullpen.team_workload(self.log(), "NYY", "2026-08-28")
        self.assertNotIn("E", {r["name"] for r in work["relievers"]})

    def test_availability_is_attached_to_each_reliever(self):
        work = bullpen.team_workload(self.log(), "NYY", "2026-08-28")
        heavy = [r for r in work["relievers"] if r["name"] == "A"][0]
        self.assertEqual(heavy["availability"], bullpen.LIKELY_UNAVAILABLE)

    def test_totals_are_reported(self):
        work = bullpen.team_workload(self.log(), "NYY", "2026-08-28")
        self.assertEqual(work["reliever_count"], 2)
        self.assertEqual(work["total_innings"], 3.0)

    def test_an_empty_day_marker_is_ignored(self):
        log = self.log() + [{"date": "2026-08-26", "empty": True}]
        work = bullpen.team_workload(log, "NYY", "2026-08-28")
        self.assertEqual(work["reliever_count"], 2)


class TestLogIO(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "pen.jsonl"

    def tearDown(self):
        self.dir.cleanup()

    def test_a_missing_log_is_empty_not_an_error(self):
        self.assertEqual(bullpen.read_log(self.path), [])

    def test_corrupt_lines_are_named(self):
        self.path.write_text('{"date":"x"}\nnope\n', encoding="utf-8")
        with self.assertRaises(bullpen.BullpenError) as ctx:
            bullpen.read_log(self.path)
        self.assertIn(":2", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
