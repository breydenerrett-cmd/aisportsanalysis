"""src/datasvc/nfl/timeutil.py and venues.py: the clocks and the stadium table.

A kickoff an hour wrong moves a game across the leakage gate, and a latitude with the wrong sign
puts a team in the wrong hemisphere, so both are pinned to hand-checked cases and, where the
machine has a time zone database, to that database.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from src.datasvc.nfl import timeutil, venues

try:
    import zoneinfo
    _NY = zoneinfo.ZoneInfo("America/New_York")
    _LONDON = zoneinfo.ZoneInfo("Europe/London")
    _BERLIN = zoneinfo.ZoneInfo("Europe/Berlin")
    _MELBOURNE = zoneinfo.ZoneInfo("Australia/Melbourne")
    _PHOENIX = zoneinfo.ZoneInfo("America/Phoenix")
    _CHICAGO = zoneinfo.ZoneInfo("America/Chicago")
    _LA = zoneinfo.ZoneInfo("America/Los_Angeles")
    HAS_TZDATA = True
except Exception:  # noqa: BLE001 -- no tz database on this machine is a fact, not a failure
    HAS_TZDATA = False


class KickoffInUtc(unittest.TestCase):
    def test_eastern_daylight_time_is_four_hours_behind_utc(self):
        self.assertEqual(timeutil.eastern_to_utc("2025-09-04", "20:20"), "2025-09-05T00:20:00Z")
        self.assertEqual(timeutil.eastern_to_utc("2025-10-05", "09:30"), "2025-10-05T13:30:00Z")

    def test_eastern_standard_time_is_five_hours_behind_utc(self):
        """The case a fixed UTC-4 gets wrong: every game from November to February."""
        self.assertEqual(timeutil.eastern_to_utc("2025-12-25", "13:00"), "2025-12-25T18:00:00Z")
        self.assertEqual(timeutil.eastern_to_utc("2026-02-08", "18:30"), "2026-02-08T23:30:00Z")
        self.assertEqual(timeutil.eastern_to_utc("2024-11-10", "09:30"), "2024-11-10T14:30:00Z")

    def test_the_morning_the_clocks_change_in_november_and_march(self):
        self.assertEqual(timeutil.eastern_to_utc("2025-11-02", "13:00"), "2025-11-02T18:00:00Z")   # back that morning
        self.assertEqual(timeutil.eastern_to_utc("2025-11-01", "20:00"), "2025-11-02T00:00:00Z")   # night before: EDT
        self.assertEqual(timeutil.eastern_to_utc("2026-03-08", "13:00"), "2026-03-08T17:00:00Z")   # forward that morning
        self.assertEqual(timeutil.eastern_to_utc("2026-03-07", "20:00"), "2026-03-08T01:00:00Z")

    def test_a_kickoff_after_midnight_utc_is_the_next_utc_day(self):
        self.assertEqual(timeutil.eastern_to_utc("2026-09-10", "20:35"), "2026-09-11T00:35:00Z")

    def test_a_blank_time_is_none_and_nonsense_raises(self):
        self.assertIsNone(timeutil.eastern_to_utc("2025-09-04", ""))
        self.assertIsNone(timeutil.eastern_to_utc("2025-09-04", None))
        self.assertIsNone(timeutil.eastern_to_utc("2025-09-04", "  "))
        for bad_time in ("25:00", "9pm", "20:75"):
            with self.assertRaises(ValueError, msg=bad_time):
                timeutil.eastern_to_utc("2025-09-04", bad_time)
        with self.assertRaises(ValueError):
            timeutil.eastern_to_utc("not a date", "13:00")

    def test_the_older_us_rule_is_used_before_2007(self):
        # 2006: daylight time ran first Sunday of April to last Sunday of October
        self.assertEqual(timeutil.us_dst_dates(2006), (date(2006, 4, 2), date(2006, 10, 29)))
        self.assertEqual(timeutil.us_dst_dates(2007), (date(2007, 3, 11), date(2007, 11, 4)))
        self.assertEqual(timeutil.eastern_to_utc("2006-03-26", "13:00"), "2006-03-26T18:00:00Z")   # still standard in March
        self.assertEqual(timeutil.eastern_to_utc("2007-03-18", "13:00"), "2007-03-18T17:00:00Z")   # already daylight
        with self.assertRaises(ValueError):
            timeutil.us_dst_dates(1980)

    @unittest.skipUnless(HAS_TZDATA, "no time zone database on this machine")
    def test_the_written_rules_agree_with_zoneinfo_for_every_day_of_20_years(self):
        day, end = date(2007, 1, 1), date(2030, 12, 31)
        checked = 0
        while day <= end:
            for clock in ("09:30", "13:00", "20:20"):
                hour, minute = int(clock[:2]), int(clock[3:])
                expected = datetime(day.year, day.month, day.day, hour, minute, tzinfo=_NY).astimezone(timezone.utc)
                self.assertEqual(timeutil.eastern_to_utc(day.isoformat(), clock),
                                 expected.strftime("%Y-%m-%dT%H:%M:%SZ"), (day, clock))
                checked += 1
            day += timedelta(days=1)
        self.assertGreater(checked, 25000)


class OffsetsOfTheRegionsThatHostGames(unittest.TestCase):
    def offset(self, zone, instant):
        return timeutil.utc_offset_hours(zone, instant)

    def test_us_zones_move_on_the_same_instant_as_the_us_rule(self):
        self.assertEqual(self.offset("us_eastern", "2025-03-09T06:59:59Z"), -5)
        self.assertEqual(self.offset("us_eastern", "2025-03-09T07:00:00Z"), -4)
        self.assertEqual(self.offset("us_eastern", "2025-11-02T05:59:59Z"), -4)
        self.assertEqual(self.offset("us_eastern", "2025-11-02T06:00:00Z"), -5)
        # each zone changes at 02:00 its own time
        self.assertEqual(self.offset("us_pacific", "2025-03-09T09:59:59Z"), -8)
        self.assertEqual(self.offset("us_pacific", "2025-03-09T10:00:00Z"), -7)
        self.assertEqual(self.offset("us_central", "2025-07-01T00:00:00Z"), -5)
        self.assertEqual(self.offset("us_mountain", "2025-12-01T00:00:00Z"), -7)

    def test_arizona_never_changes_its_clocks(self):
        self.assertEqual(self.offset("us_arizona", "2025-07-01T00:00:00Z"), -7)
        self.assertEqual(self.offset("us_arizona", "2025-12-01T00:00:00Z"), -7)
        # so in summer it keeps Pacific daylight time and in winter it is an hour ahead of Pacific
        self.assertEqual(self.offset("us_arizona", "2025-07-01T00:00:00Z"), self.offset("us_pacific", "2025-07-01T00:00:00Z"))
        self.assertEqual(self.offset("us_arizona", "2025-12-01T00:00:00Z") - self.offset("us_pacific", "2025-12-01T00:00:00Z"), 1)

    def test_europe_changes_on_the_last_sunday_of_march_and_october_at_0100_utc(self):
        self.assertEqual(self.offset("uk", "2026-10-04T13:30:00Z"), 1)                 # the October 2026 London game: BST
        self.assertEqual(self.offset("central_europe", "2026-10-18T13:30:00Z"), 2)
        self.assertEqual(self.offset("central_europe", "2026-10-25T13:30:00Z"), 1)     # clocks went back that morning
        self.assertEqual(self.offset("uk", "2026-03-29T00:59:59Z"), 0)
        self.assertEqual(self.offset("uk", "2026-03-29T01:00:00Z"), 1)

    def test_victoria_is_in_the_southern_hemisphere(self):
        self.assertEqual(self.offset("au_victoria", "2026-09-11T00:35:00Z"), 10)       # the opener at the MCG, before October
        self.assertEqual(self.offset("au_victoria", "2026-10-10T00:35:00Z"), 11)
        self.assertEqual(self.offset("au_victoria", "2026-02-01T00:00:00Z"), 11)
        self.assertEqual(self.offset("au_victoria", "2026-05-01T00:00:00Z"), 10)

    def test_brazil_and_mexico_do_not_change(self):
        for instant in ("2026-01-15T00:00:00Z", "2026-07-15T00:00:00Z"):
            self.assertEqual(self.offset("brazil", instant), -3)
            self.assertEqual(self.offset("mexico", instant), -6)

    def test_an_unknown_zone_raises(self):
        with self.assertRaises(KeyError):
            timeutil.utc_offset_hours("mars", "2026-01-01T00:00:00Z")

    @unittest.skipUnless(HAS_TZDATA, "no time zone database on this machine")
    def test_the_offsets_agree_with_zoneinfo_through_the_whole_football_calendar(self):
        zones = {"us_eastern": _NY, "us_central": _CHICAGO, "us_pacific": _LA, "us_arizona": _PHOENIX, "uk": _LONDON,
                 "central_europe": _BERLIN, "au_victoria": _MELBOURNE}
        when = datetime(2021, 8, 1, tzinfo=timezone.utc)
        while when < datetime(2027, 3, 1, tzinfo=timezone.utc):
            for name, tz in zones.items():
                expected = int(when.astimezone(tz).utcoffset().total_seconds() // 3600)
                self.assertEqual(timeutil.utc_offset_hours(name, when), expected, (name, when))
            when += timedelta(hours=7)


class SeasonOfADate(unittest.TestCase):
    def test_the_season_is_named_for_the_year_it_starts(self):
        self.assertEqual(timeutil.season_of("2026-02-08"), 2025)     # Super Bowl LX is the 2025 season
        self.assertEqual(timeutil.season_of("2026-03-01"), 2026)
        self.assertEqual(timeutil.season_of("2026-10-03"), 2026)
        self.assertEqual(timeutil.season_of(date(2027, 1, 3)), 2026)


class TheStadiumTable(unittest.TestCase):
    def test_every_venue_has_a_known_zone_and_sane_coordinates(self):
        self.assertEqual(len(venues.VENUES), 41)
        for sid, v in venues.VENUES.items():
            self.assertEqual(v.stadium_id, sid)
            self.assertIn(v.zone, timeutil.ZONES, sid)
            self.assertTrue(-90 <= v.lat <= 90 and -180 <= v.lon <= 180, sid)

    def test_countries_zones_and_hemispheres_match_the_cities(self):
        us = [v for v in venues.VENUES.values() if v.country == "US"]
        self.assertEqual(len(us), 30)
        for v in us:                                   # continental US: north, west of Greenwich, between the oceans
            self.assertTrue(24 < v.lat < 49 and -125 < v.lon < -66, v.stadium_id)
            self.assertTrue(v.zone.startswith("us_"), v.stadium_id)
        self.assertLess(venues.venue("MEL00").lat, 0)
        self.assertLess(venues.venue("RIO00").lat, 0)
        self.assertLess(venues.venue("SAO00").lat, 0)
        self.assertGreater(venues.venue("MEL00").lon, 100)
        for sid in ("LON00", "LON02", "FRA00", "GER00", "MUN01", "MAD01", "PAR00"):
            self.assertGreater(venues.venue(sid).lat, 40, sid)
        self.assertEqual(venues.venue("PHO00").zone, "us_arizona")
        self.assertEqual(venues.venue("DEN00").zone, "us_mountain")
        self.assertEqual(venues.venue("IND00").zone, "us_eastern")        # Indiana is Eastern
        self.assertEqual(venues.venue("NAS00").zone, "us_central")

    def test_distances_match_well_known_figures(self):
        """A sign or digit slip in a coordinate would break one of these by hundreds of miles."""
        self.assertAlmostEqual(venues.miles_between("KAN00", "SEA00"), 1500, delta=40)       # Kansas City to Seattle
        self.assertAlmostEqual(venues.miles_between("NYC01", "LAX01"), 2450, delta=40)       # New York to Los Angeles
        self.assertAlmostEqual(venues.miles_between("MIA00", "SEA00"), 2720, delta=40)       # the longest US trip
        self.assertAlmostEqual(venues.miles_between("NYC01", "LON00"), 3452, delta=40)       # New York to London
        self.assertAlmostEqual(venues.miles_between("LON00", "LON02"), 10, delta=2)          # Wembley to Tottenham
        self.assertAlmostEqual(venues.miles_between("PHI00", "NYC01"), 85, delta=6)          # Philadelphia to the Meadowlands
        self.assertAlmostEqual(venues.miles_between("LAX01", "MEL00"), 7930, delta=60)       # Los Angeles to Melbourne
        self.assertEqual(venues.miles_between("GER00", "MUN01"), 0.0)                        # one building, two ids
        self.assertEqual(venues.miles_between("KAN00", "KAN00"), 0.0)

    def test_an_unknown_or_blank_id_has_no_distance(self):
        self.assertIsNone(venues.venue("NOPE"))
        self.assertIsNone(venues.venue(None))
        self.assertIsNone(venues.miles_between("KAN00", "NOPE"))
        self.assertIsNone(venues.miles_between(None, "KAN00"))

    def test_haversine_is_symmetric_and_in_statute_miles(self):
        a, b = venues.venue("KAN00"), venues.venue("SEA00")
        self.assertAlmostEqual(venues.haversine_miles(a.lat, a.lon, b.lat, b.lon),
                               venues.haversine_miles(b.lat, b.lon, a.lat, a.lon), places=9)
        self.assertAlmostEqual(venues.haversine_miles(0, 0, 0, 1), 69.09, delta=0.1)          # one degree of the equator

    def test_a_teams_home_stadium_is_the_one_it_used_most_that_season(self):
        games = [
            {"home_team": "JAX", "season": 2026, "stadium_id": "JAX00", "neutral_site": False},
            {"home_team": "JAX", "season": 2026, "stadium_id": "JAX00", "neutral_site": False},
            {"home_team": "JAX", "season": 2026, "stadium_id": "LON00", "neutral_site": True},      # neutral: ignored
            {"home_team": "JAX", "season": 2026, "stadium_id": "LON02", "venue_check": "stadium_id_name_conflict",
             "neutral_site": False},                                                                 # contradicted: ignored
            {"home_team": "LA", "season": 2025, "stadium_id": "LAX01", "neutral_site": False},
            {"home_team": "LAC", "season": 2025, "stadium_id": "LAX01", "neutral_site": False},
        ]
        table = venues.home_stadium_ids(games)
        self.assertEqual(table[("JAX", 2026)], "JAX00")
        self.assertEqual(table[("LA", 2025)], table[("LAC", 2025)], "LAX01")                         # two teams, one stadium


if __name__ == "__main__":
    unittest.main()
