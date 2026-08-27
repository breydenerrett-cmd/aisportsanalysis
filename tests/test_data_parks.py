"""Tests for src/data/parks.py.

The wind classification is the substance here. Bearings are geometry and easy
to get backwards -- particularly the meteorological convention that wind
direction names where the wind comes FROM, not where it is going.
"""

import unittest

from src.data import parks
from src.data.parks import ParkError


class TestParkTable(unittest.TestCase):
    def test_thirty_teams(self):
        self.assertEqual(len(parks.PARKS), 30)

    def test_every_park_has_required_fields(self):
        for abbrev, park in parks.PARKS.items():
            with self.subTest(team=abbrev):
                for field in ("name", "lat", "lon", "altitude_m", "roof",
                              "orientation_deg"):
                    self.assertIn(field, park)

    def test_coordinates_are_plausible_for_north_america(self):
        for abbrev, park in parks.PARKS.items():
            with self.subTest(team=abbrev):
                self.assertTrue(20.0 < park["lat"] < 55.0, park["lat"])
                self.assertTrue(-125.0 < park["lon"] < -65.0, park["lon"])

    def test_roof_values_are_from_the_known_set(self):
        for abbrev, park in parks.PARKS.items():
            with self.subTest(team=abbrev):
                self.assertIn(park["roof"], ("open", "retractable", "fixed"))

    def test_coors_is_the_high_altitude_outlier(self):
        altitudes = {k: v["altitude_m"] for k, v in parks.PARKS.items()}
        self.assertEqual(max(altitudes, key=altitudes.get), "COL")
        self.assertGreater(altitudes["COL"], 1000)

    def test_no_orientation_is_claimed_without_verification(self):
        # This test is the honesty guard. If someone fills bearings in, they
        # must also update this test deliberately -- it cannot drift silently.
        self.assertEqual(len(parks.parks_missing_orientation()), 30)

    def test_roofed_teams_set_matches_the_table(self):
        for abbrev in parks.ROOFED_TEAMS:
            self.assertNotEqual(parks.PARKS[abbrev]["roof"], "open")


class TestLookup(unittest.TestCase):
    def test_lookup_is_case_insensitive_and_trims(self):
        self.assertEqual(parks.get_park("bos")["name"], "Fenway Park")
        self.assertEqual(parks.get_park("  BOS  ")["name"], "Fenway Park")

    def test_unknown_team_raises_with_a_helpful_message(self):
        with self.assertRaises(ParkError) as ctx:
            parks.get_park("XYZ")
        self.assertIn("unknown team", str(ctx.exception))

    def test_non_string_rejected(self):
        for bad in (None, 5, ["BOS"]):
            with self.subTest(bad=bad):
                with self.assertRaises(ParkError):
                    parks.get_park(bad)

    def test_returns_a_copy_so_callers_cannot_mutate_the_table(self):
        park = parks.get_park("BOS")
        park["lat"] = 0.0
        self.assertNotEqual(parks.PARKS["BOS"]["lat"], 0.0)

    def test_coordinates_helper(self):
        lat, lon = parks.coordinates("CHC")
        self.assertAlmostEqual(lat, parks.PARKS["CHC"]["lat"])
        self.assertAlmostEqual(lon, parks.PARKS["CHC"]["lon"])

    def test_has_roof(self):
        self.assertTrue(parks.has_roof("TOR"))
        self.assertFalse(parks.has_roof("CHC"))


class TestAliases(unittest.TestCase):
    """Abbreviation drift between sources is a silent-failure bug, not cosmetic.

    The MLB Stats API emits ATH and AZ; odds feeds and historical datasets
    commonly emit OAK and ARI. Without aliasing, park lookups miss and weather
    goes quietly blank for those teams for an entire season.
    """

    def test_mlb_api_spellings_resolve(self):
        self.assertEqual(parks.canonical_team("ATH"), "OAK")
        self.assertEqual(parks.canonical_team("AZ"), "ARI")

    def test_aliased_lookup_returns_the_right_park(self):
        self.assertEqual(parks.get_park("ATH")["name"],
                         parks.get_park("OAK")["name"])
        self.assertEqual(parks.get_park("AZ")["name"],
                         parks.get_park("ARI")["name"])

    def test_canonical_keys_pass_through_unchanged(self):
        for abbrev in parks.PARKS:
            with self.subTest(team=abbrev):
                self.assertEqual(parks.canonical_team(abbrev), abbrev)

    def test_every_alias_points_at_a_real_park(self):
        for alias, target in parks.ALIASES.items():
            with self.subTest(alias=alias):
                self.assertIn(target, parks.PARKS)

    def test_no_alias_shadows_a_canonical_key(self):
        # An alias that collides with a real team would silently redirect it.
        for alias in parks.ALIASES:
            with self.subTest(alias=alias):
                self.assertNotIn(alias, parks.PARKS)

    def test_aliases_are_case_insensitive(self):
        self.assertEqual(parks.canonical_team("ath"), "OAK")

    def test_coordinates_work_through_an_alias(self):
        self.assertEqual(parks.coordinates("ATH"), parks.coordinates("OAK"))


class TestClassifyWind(unittest.TestCase):
    # Park axis points due north: home plate at south, center field at north.
    NORTH = 0.0

    def test_wind_from_the_south_blows_out(self):
        # Wind FROM the south pushes north, from home plate toward center.
        self.assertEqual(parks.classify_wind(self.NORTH, 180.0), "out")

    def test_wind_from_the_north_blows_in(self):
        self.assertEqual(parks.classify_wind(self.NORTH, 0.0), "in")

    def test_wind_from_the_east_is_a_crosswind(self):
        self.assertEqual(parks.classify_wind(self.NORTH, 90.0), "cross")

    def test_wind_from_the_west_is_a_crosswind(self):
        self.assertEqual(parks.classify_wind(self.NORTH, 270.0), "cross")

    def test_edge_of_the_arc_still_counts_as_straight(self):
        # 45 degrees off the out-axis is the boundary and is inclusive.
        self.assertEqual(parks.classify_wind(self.NORTH, 135.0), "out")
        self.assertEqual(parks.classify_wind(self.NORTH, 225.0), "out")

    def test_just_outside_the_arc_is_cross(self):
        self.assertEqual(parks.classify_wind(self.NORTH, 134.0, arc=44.0), "cross")

    def test_a_narrower_arc_reclassifies_marginal_wind(self):
        self.assertEqual(parks.classify_wind(self.NORTH, 150.0, arc=45.0), "out")
        self.assertEqual(parks.classify_wind(self.NORTH, 150.0, arc=20.0), "cross")

    def test_works_for_an_east_facing_park(self):
        east = 90.0
        self.assertEqual(parks.classify_wind(east, 270.0), "out")
        self.assertEqual(parks.classify_wind(east, 90.0), "in")
        self.assertEqual(parks.classify_wind(east, 0.0), "cross")

    def test_wraps_correctly_around_360(self):
        # Axis near north, wind just past 360 should behave like just past 0.
        self.assertEqual(parks.classify_wind(350.0, 170.0), "out")
        self.assertEqual(parks.classify_wind(10.0, 355.0), "in")

    def test_unverified_orientation_returns_none_not_a_guess(self):
        self.assertIsNone(parks.classify_wind(None, 180.0))

    def test_invalid_bearings_rejected(self):
        for bad in (-1, 361, "north", None):
            with self.subTest(bad=bad):
                with self.assertRaises(ParkError):
                    parks.classify_wind(0.0, bad)

    def test_invalid_arc_rejected(self):
        for bad in (0, -5, 91):
            with self.subTest(bad=bad):
                with self.assertRaises(ParkError):
                    parks.classify_wind(0.0, 180.0, arc=bad)


class TestWindEffect(unittest.TestCase):
    def test_open_park_without_orientation_is_not_applicable(self):
        result = parks.wind_effect("CHC", 180.0, wind_mph=12)
        self.assertFalse(result["applicable"])
        self.assertIsNone(result["direction"])
        self.assertIn("not verified", result["reason"])

    def test_roofed_park_with_unknown_roof_state_is_not_applicable(self):
        result = parks.wind_effect("TOR", 180.0, wind_mph=12)
        self.assertFalse(result["applicable"])
        self.assertIn("unknown", result["reason"])

    def test_closed_roof_suppresses_wind(self):
        result = parks.wind_effect("TOR", 180.0, wind_mph=20, roof_closed=True)
        self.assertFalse(result["applicable"])
        self.assertIn("roof closed", result["reason"])

    def test_open_roof_falls_through_to_orientation_check(self):
        result = parks.wind_effect("TOR", 180.0, wind_mph=20, roof_closed=False)
        self.assertFalse(result["applicable"])
        self.assertIn("not verified", result["reason"])

    def test_unknown_team_raises(self):
        with self.assertRaises(ParkError):
            parks.wind_effect("XYZ", 180.0)


class TestAngularDistance(unittest.TestCase):
    def test_never_exceeds_180(self):
        for a in range(0, 360, 30):
            for b in range(0, 360, 30):
                with self.subTest(a=a, b=b):
                    self.assertLessEqual(parks._angular_distance(a, b), 180.0)

    def test_is_symmetric(self):
        self.assertAlmostEqual(parks._angular_distance(10, 350),
                               parks._angular_distance(350, 10))

    def test_wraps_the_short_way(self):
        self.assertAlmostEqual(parks._angular_distance(10, 350), 20.0)


if __name__ == "__main__":
    unittest.main()
