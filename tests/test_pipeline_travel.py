"""Tests for src/pipeline/travel.py."""

import unittest

from src.pipeline import travel


class TestDistance(unittest.TestCase):

    def test_same_point_is_zero(self):
        self.assertEqual(travel.great_circle_miles((40.0, -74.0), (40.0, -74.0)), 0.0)

    def test_a_known_pair_is_about_right(self):
        # Yankee Stadium to Dodger Stadium is roughly 2,440 miles.
        miles = travel.great_circle_miles((40.8296, -73.9262), (34.0739, -118.2400))
        self.assertGreater(miles, 2350)
        self.assertLess(miles, 2500)

    def test_it_is_symmetric(self):
        a, b = (40.8296, -73.9262), (47.5914, -122.3325)
        self.assertEqual(travel.great_circle_miles(a, b),
                         travel.great_circle_miles(b, a))


class TestTravelLoad(unittest.TestCase):

    def store(self, rows):
        return rows

    def game(self, date, home, away):
        return {"date": date, "home_team": home, "away_team": away}

    def test_distance_is_measured_from_where_they_actually_played(self):
        rows = [self.game("2026-08-27", "SEA", "TEX")]
        load = travel.travel_load(rows, "TEX", "2026-08-28", "TOR")
        self.assertEqual(load["last_venue"], "SEA")
        self.assertGreater(load["miles"], 2000)

    def test_a_home_stand_is_zero_miles_not_missing(self):
        rows = [self.game("2026-08-27", "NYY", "BOS")]
        load = travel.travel_load(rows, "NYY", "2026-08-28", "NYY")
        self.assertEqual(load["miles"], 0.0)
        self.assertIsNone(load["reason"])

    def test_direction_is_reported_because_it_is_not_symmetric(self):
        rows = [self.game("2026-08-27", "SEA", "BOS")]
        load = travel.travel_load(rows, "BOS", "2026-08-28", "NYY")
        self.assertTrue(load["eastward"])

    def test_tonights_game_is_never_counted(self):
        # Reading tonight's row would be a leak, and a subtle one: the venue
        # would be right and the distance zero.
        rows = [self.game("2026-08-28", "TOR", "SEA"),
                self.game("2026-08-26", "SEA", "TEX")]
        load = travel.travel_load(rows, "SEA", "2026-08-28", "TOR")
        self.assertEqual(load["last_venue"], "SEA")

    def test_no_recent_games_gives_a_reason_rather_than_a_number(self):
        load = travel.travel_load([], "BOS", "2026-08-28", "NYY")
        self.assertIsNone(load["miles"])
        self.assertIn("no games", load["reason"])

    def test_an_unknown_park_is_reported_not_guessed(self):
        rows = [{"date": "2026-08-27", "home_team": "ZZZ", "away_team": "BOS"}]
        load = travel.travel_load(rows, "BOS", "2026-08-28", "NYY")
        self.assertIsNone(load["miles"])
        self.assertIn("unknown team", load["reason"])

    def test_a_dense_stretch_is_flagged(self):
        rows = [self.game(f"2026-08-2{d}", "NYY", "BOS") for d in range(1, 8)]
        load = travel.travel_load(rows, "BOS", "2026-08-28", "NYY")
        self.assertTrue(load["dense_stretch"])
        self.assertGreaterEqual(load["games_last_7"], travel.DENSE_GAME_COUNT)

    def test_zones_are_an_approximation_from_longitude(self):
        rows = [self.game("2026-08-27", "SEA", "BOS")]
        load = travel.travel_load(rows, "BOS", "2026-08-28", "NYY")
        self.assertGreater(load["zones"], 2)
        self.assertLess(load["zones"], 4)


if __name__ == "__main__":
    unittest.main()
