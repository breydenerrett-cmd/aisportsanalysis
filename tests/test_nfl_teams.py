"""Tests for the NFL team map (src.sports.nfl_teams).

WHY THESE ASSERTIONS: the team map's job is to resolve any form of team name
(full name, nickname, alias, code) to a canonical nflverse code, so data rows
from the odds feed and schedule can be joined on a shared team identifier. The
tests verify 32 teams exist, all names round-trip, aliases resolve, and unknown
names fail fast rather than silently.
"""

import csv
import unittest
from pathlib import Path

from src.sports import nfl_teams


class TestNFLTeamMap(unittest.TestCase):
    """Test the NFL team map."""

    def test_teams_tuple_has_32_entries(self):
        """TEAMS must have exactly 32 teams."""
        self.assertEqual(len(nfl_teams.TEAMS), 32)

    def test_teams_tuple_entries_are_triples(self):
        """Each entry in TEAMS is a (code, full_name, short_name) triple."""
        for entry in nfl_teams.TEAMS:
            self.assertIsInstance(entry, tuple)
            self.assertEqual(len(entry), 3)
            code, full_name, short_name = entry
            self.assertIsInstance(code, str)
            self.assertIsInstance(full_name, str)
            self.assertIsInstance(short_name, str)
            self.assertGreater(len(code), 0)
            self.assertGreater(len(full_name), 0)
            self.assertGreater(len(short_name), 0)

    def test_all_codes_is_sorted_tuple_of_32(self):
        """ALL_CODES is a sorted tuple of 32 codes."""
        self.assertIsInstance(nfl_teams.ALL_CODES, tuple)
        self.assertEqual(len(nfl_teams.ALL_CODES), 32)
        # Verify it's sorted
        self.assertEqual(nfl_teams.ALL_CODES, tuple(sorted(nfl_teams.ALL_CODES)))
        # Verify all codes from TEAMS are included
        codes_from_teams = {code for code, _, _ in nfl_teams.TEAMS}
        self.assertEqual(set(nfl_teams.ALL_CODES), codes_from_teams)

    def test_abbrev_exact_code_match(self):
        """abbrev() accepts exact nflverse codes."""
        self.assertEqual(nfl_teams.abbrev("BUF"), "BUF")
        self.assertEqual(nfl_teams.abbrev("KC"), "KC")
        self.assertEqual(nfl_teams.abbrev("GB"), "GB")

    def test_abbrev_code_match_case_insensitive(self):
        """abbrev() matches codes case-insensitively."""
        self.assertEqual(nfl_teams.abbrev("buf"), "BUF")
        self.assertEqual(nfl_teams.abbrev("kc"), "KC")
        self.assertEqual(nfl_teams.abbrev("gb"), "GB")

    def test_abbrev_full_name_match(self):
        """abbrev() accepts full team names."""
        self.assertEqual(nfl_teams.abbrev("Buffalo Bills"), "BUF")
        self.assertEqual(nfl_teams.abbrev("Kansas City Chiefs"), "KC")
        self.assertEqual(nfl_teams.abbrev("Green Bay Packers"), "GB")

    def test_abbrev_full_name_case_insensitive(self):
        """abbrev() matches full names case-insensitively."""
        self.assertEqual(nfl_teams.abbrev("buffalo bills"), "BUF")
        self.assertEqual(nfl_teams.abbrev("KANSAS CITY CHIEFS"), "KC")
        self.assertEqual(nfl_teams.abbrev("green bay packers"), "GB")

    def test_abbrev_short_name_match(self):
        """abbrev() accepts short names (nicknames)."""
        self.assertEqual(nfl_teams.abbrev("Bills"), "BUF")
        self.assertEqual(nfl_teams.abbrev("Chiefs"), "KC")
        self.assertEqual(nfl_teams.abbrev("Packers"), "GB")

    def test_abbrev_short_name_case_insensitive(self):
        """abbrev() matches short names case-insensitively."""
        self.assertEqual(nfl_teams.abbrev("bills"), "BUF")
        self.assertEqual(nfl_teams.abbrev("CHIEFS"), "KC")
        self.assertEqual(nfl_teams.abbrev("packers"), "GB")

    def test_abbrev_ignores_punctuation(self):
        """abbrev() ignores punctuation when matching."""
        # San Francisco 49ers has a digit but no special chars in the map
        self.assertEqual(nfl_teams.abbrev("San Francisco 49ers"), "SF")
        self.assertEqual(nfl_teams.abbrev("San Francisco 49ers."), "SF")

    def test_abbrev_ignores_extra_spaces(self):
        """abbrev() normalizes extra spaces."""
        self.assertEqual(nfl_teams.abbrev("  Buffalo Bills  "), "BUF")
        self.assertEqual(nfl_teams.abbrev("Buffalo    Bills"), "BUF")

    def test_abbrev_alias_la_rams_variants(self):
        """abbrev() resolves LA Rams aliases."""
        self.assertEqual(nfl_teams.abbrev("LA Rams"), "LA")
        self.assertEqual(nfl_teams.abbrev("L.A. Rams"), "LA")
        self.assertEqual(nfl_teams.abbrev("LAR"), "LA")
        self.assertEqual(nfl_teams.abbrev("St. Louis Rams"), "LA")

    def test_abbrev_alias_la_chargers_variants(self):
        """abbrev() resolves LA Chargers aliases."""
        self.assertEqual(nfl_teams.abbrev("LA Chargers"), "LAC")
        self.assertEqual(nfl_teams.abbrev("L.A. Chargers"), "LAC")
        self.assertEqual(nfl_teams.abbrev("San Diego Chargers"), "LAC")

    def test_abbrev_alias_lv_raiders_variants(self):
        """abbrev() resolves Las Vegas/Oakland Raiders aliases."""
        self.assertEqual(nfl_teams.abbrev("Oakland Raiders"), "LV")

    def test_abbrev_alias_washington_variants(self):
        """abbrev() resolves Washington team name aliases."""
        self.assertEqual(nfl_teams.abbrev("Washington Football Team"), "WAS")
        self.assertEqual(nfl_teams.abbrev("WSH"), "WAS")

    def test_abbrev_alias_jax_short_form(self):
        """abbrev() resolves JAC -> JAX."""
        self.assertEqual(nfl_teams.abbrev("JAC"), "JAX")

    def test_abbrev_unknown_returns_none(self):
        """abbrev() returns None for unknown team names."""
        self.assertIsNone(nfl_teams.abbrev("Unknown Team"))
        self.assertIsNone(nfl_teams.abbrev("London Lions"))
        self.assertIsNone(nfl_teams.abbrev("XYZ"))
        self.assertIsNone(nfl_teams.abbrev(None))
        self.assertIsNone(nfl_teams.abbrev(""))

    def test_abbrev_returns_uppercase_code(self):
        """abbrev() always returns uppercase codes."""
        result = nfl_teams.abbrev("bills")
        self.assertEqual(result, result.upper())

    def test_full_name_returns_odds_api_names(self):
        """full_name() returns The Odds API full names."""
        self.assertEqual(nfl_teams.full_name("BUF"), "Buffalo Bills")
        self.assertEqual(nfl_teams.full_name("KC"), "Kansas City Chiefs")
        self.assertEqual(nfl_teams.full_name("GB"), "Green Bay Packers")

    def test_full_name_case_insensitive(self):
        """full_name() accepts codes case-insensitively."""
        self.assertEqual(nfl_teams.full_name("buf"), "Buffalo Bills")
        self.assertEqual(nfl_teams.full_name("kc"), "Kansas City Chiefs")

    def test_full_name_unknown_code_returns_none(self):
        """full_name() returns None for unknown codes."""
        self.assertIsNone(nfl_teams.full_name("XYZ"))
        self.assertIsNone(nfl_teams.full_name(None))
        self.assertIsNone(nfl_teams.full_name(""))

    def test_short_name_returns_nicknames(self):
        """short_name() returns team nicknames."""
        self.assertEqual(nfl_teams.short_name("BUF"), "Bills")
        self.assertEqual(nfl_teams.short_name("KC"), "Chiefs")
        self.assertEqual(nfl_teams.short_name("GB"), "Packers")

    def test_short_name_case_insensitive(self):
        """short_name() accepts codes case-insensitively."""
        self.assertEqual(nfl_teams.short_name("buf"), "Bills")
        self.assertEqual(nfl_teams.short_name("kc"), "Chiefs")

    def test_short_name_unknown_code_returns_none(self):
        """short_name() returns None for unknown codes."""
        self.assertIsNone(nfl_teams.short_name("XYZ"))
        self.assertIsNone(nfl_teams.short_name(None))
        self.assertIsNone(nfl_teams.short_name(""))

    def test_every_full_name_round_trips_through_abbrev(self):
        """Every full name resolves through abbrev() to its code."""
        for code, full_name, _ in nfl_teams.TEAMS:
            self.assertEqual(nfl_teams.abbrev(full_name), code)

    def test_every_short_name_round_trips_through_abbrev(self):
        """Every short name resolves through abbrev() to its code."""
        for code, _, short_name in nfl_teams.TEAMS:
            self.assertEqual(nfl_teams.abbrev(short_name), code)

    def test_fixtures_use_valid_codes(self):
        """Every team in the fixtures CSV is in ALL_CODES."""
        fixtures_dir = Path(__file__).parent / "fixtures" / "nfl"
        games_csv = fixtures_dir / "games_sample.csv"

        if not games_csv.exists():
            self.skipTest(f"Fixture file not found: {games_csv}")

        away_teams = set()
        home_teams = set()

        with open(games_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                away_teams.add(row['away_team'])
                home_teams.add(row['home_team'])

        all_fixture_teams = away_teams | home_teams
        invalid_teams = all_fixture_teams - set(nfl_teams.ALL_CODES)

        self.assertEqual(len(invalid_teams), 0,
                         f"Invalid team codes in fixtures: {invalid_teams}")

    def test_spec_integration(self):
        """The sportspec should have functioning team_abbrev_fn."""
        import src.sports
        nfl_spec = src.sports.spec("nfl")
        self.assertIsNotNone(nfl_spec.team_abbrev_fn)
        # Test that it works
        self.assertEqual(nfl_spec.team_abbrev_fn("Buffalo Bills"), "BUF")
        self.assertIsNone(nfl_spec.team_abbrev_fn("Unknown Team"))

    def test_all_32_teams_accounted_for(self):
        """Verify all 32 NFL teams are present."""
        expected_codes = {
            "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
            "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
            "LA", "LAC", "LV", "MIA", "MIN", "NE", "NO", "NYG", "NYJ",
            "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
        }
        actual_codes = {code for code, _, _ in nfl_teams.TEAMS}
        self.assertEqual(actual_codes, expected_codes)

    def test_no_duplicate_codes(self):
        """All team codes must be unique."""
        codes = [code for code, _, _ in nfl_teams.TEAMS]
        self.assertEqual(len(codes), len(set(codes)))

    def test_no_duplicate_full_names(self):
        """All full names must be unique."""
        full_names = [fn for _, fn, _ in nfl_teams.TEAMS]
        self.assertEqual(len(full_names), len(set(full_names)))

    def test_no_duplicate_short_names(self):
        """All short names must be unique."""
        short_names = [sn for _, _, sn in nfl_teams.TEAMS]
        self.assertEqual(len(short_names), len(set(short_names)))


if __name__ == "__main__":
    unittest.main()
