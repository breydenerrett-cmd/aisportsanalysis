"""Tests for the sport registry package.

WHY THESE ASSERTIONS: the registry's whole job is to be the single place a
sport's constants live, so the tests that matter are the ones that would fail
if it drifted from the modules that own those constants today (the odds
provider's sport key, the card ledger's store path and lock lead) -- a registry
that merely agreed with itself would be worthless. The subprocess test guards
the import cycle: card_ledger and providers.odds import src.sports, so
src.sports must never import a provider at module load.
"""

import os
import subprocess
import sys
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestSportsRegistry(unittest.TestCase):
    """Test the sport registry and sport specifications."""

    def test_keys_returns_tuple_of_all_sports(self):
        """keys() should return all sport keys as a tuple."""
        import src.sports
        result = src.sports.keys()
        self.assertIsInstance(result, tuple)
        self.assertEqual(result, ("mlb", "nfl", "tennis", "mma"))

    def test_spec_default_is_mlb(self):
        """spec() with no argument should return MLB spec."""
        import src.sports
        from src.sports.mlb import MLB
        self.assertIs(src.sports.spec(), MLB)

    def test_spec_empty_string_is_mlb(self):
        """spec("") should return MLB spec."""
        import src.sports
        from src.sports.mlb import MLB
        self.assertIs(src.sports.spec(""), MLB)

    def test_is_default_treats_none_and_empty_as_mlb(self):
        """is_default() agrees with spec() about what counts as the default."""
        import src.sports
        self.assertTrue(src.sports.is_default(None))
        self.assertTrue(src.sports.is_default(""))
        self.assertTrue(src.sports.is_default("mlb"))
        self.assertFalse(src.sports.is_default("nfl"))
        self.assertFalse(src.sports.is_default("tennis"))

    def test_spec_mlb_odds_key_matches_provider(self):
        """spec("mlb").odds_api_key should match src.providers.odds.SPORT."""
        import src.sports
        from src.providers import odds
        self.assertEqual(src.sports.spec("mlb").odds_api_key, odds.SPORT)

    def test_spec_nfl_odds_key(self):
        """spec("nfl").odds_api_key should be "americanfootball_nfl"."""
        import src.sports
        self.assertEqual(src.sports.spec("nfl").odds_api_key,
                         "americanfootball_nfl")

    def test_spec_tennis_odds_key_is_none(self):
        """Tennis has no single odds key -- the feed is per tournament."""
        import src.sports
        self.assertIsNone(src.sports.spec("tennis").odds_api_key)

    def test_spec_unknown_sport_raises_unknownsport(self):
        """spec("bogus") should raise UnknownSport with valid keys in message."""
        import src.sports
        with self.assertRaises(src.sports.UnknownSport) as ctx:
            src.sports.spec("bogus")
        message = str(ctx.exception)
        self.assertIn("mlb", message)
        self.assertIn("nfl", message)
        self.assertIn("tennis", message)

    def test_mlb_card_ledger_path_matches_constant(self):
        """MLB.card_ledger_path should match src.appstate.card_ledger.CARD_STORE."""
        import src.sports
        from src.appstate import card_ledger
        mlb_spec = src.sports.spec("mlb")
        # CARD_STORE is built with os.path.join, so it is backslashed on
        # Windows; the spec holds the repo-relative literal. Compare on one
        # separator rather than asserting a platform.
        self.assertEqual(mlb_spec.card_ledger_path.replace("\\", "/"),
                         card_ledger.CARD_STORE.replace("\\", "/"))
        self.assertEqual(mlb_spec.card_ledger_path, "evidence/cards_v1.jsonl")

    def test_mlb_lock_lead_hours_matches_constant(self):
        """MLB.lock_lead_hours should match src.appstate.card_ledger.LOCK_LEAD_HOURS."""
        import src.sports
        from src.appstate import card_ledger
        self.assertEqual(src.sports.spec("mlb").lock_lead_hours,
                         card_ledger.LOCK_LEAD_HOURS)

    def test_only_mlb_is_not_experimental(self):
        """MLB is the shipped sport; every other sport is experimental."""
        import src.sports
        for key in src.sports.keys():
            spec = src.sports.spec(key)
            self.assertEqual(spec.experimental, key != "mlb",
                             f"{key} has the wrong experimental flag")

    def test_import_sports_does_not_import_mlb_provider(self):
        """Importing src.sports must not import src.providers.mlb.

        card_ledger and providers.odds import src.sports; a provider imported
        at src.sports load time would close that cycle and break startup.
        Checked in a fresh interpreter because this process has already
        imported the provider in other tests.
        """
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys, src.sports; print('src.providers.mlb' in sys.modules)"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        self.assertEqual(result.stdout.strip(), "False")

    def test_mlb_schedule_fn_adapts_fetch_games(self):
        """MLB.schedule_fn normalizes src.providers.mlb.fetch_games records.

        The fake below is one record in fetch_games' real shape -- that
        function returns `parse_game` output, whose team fields carry club
        abbreviations and whose start time is `start_time_utc`.
        """
        import src.sports
        from src.providers import mlb as mlb_provider

        mlb_spec = src.sports.spec("mlb")
        self.assertIsNotNone(mlb_spec.schedule_fn)

        fake_game = {
            "game_pk": 12345,
            "date": "2026-09-14",
            "start_time_utc": "2026-09-14T19:05:00Z",
            "state": "pending",
            "game_type": "R",
            "away_team": "BOS",
            "home_team": "NYY",
            "away_team_id": 111,
            "home_team_id": 147,
            "away_score": None,
            "home_score": None,
        }

        calls = []

        def fake_fetch_games(date_str):
            calls.append(date_str)
            return [fake_game]

        with mock.patch.object(mlb_provider, "fetch_games", fake_fetch_games):
            result = mlb_spec.schedule_fn("2026-09-14")

        self.assertEqual(calls, ["2026-09-14"])
        self.assertEqual(len(result), 1)
        game = result[0]
        self.assertEqual(sorted(game.keys()),
                         ["away", "game_id", "home", "start_utc"])
        # The id is a string for every sport, even where the provider's own
        # value is an int.
        self.assertEqual(game["game_id"], "12345")
        self.assertEqual(game["away"], "BOS")
        self.assertEqual(game["home"], "NYY")
        self.assertEqual(game["start_utc"], "2026-09-14T19:05:00Z")

    def test_mlb_schedule_fn_empty_slate(self):
        """A date with no games is an empty list, not an error."""
        import src.sports
        from src.providers import mlb as mlb_provider

        with mock.patch.object(mlb_provider, "fetch_games", lambda d: []):
            self.assertEqual(src.sports.spec("mlb").schedule_fn("2026-01-01"), [])

    def test_mlb_team_abbrev_fn(self):
        """MLB.team_abbrev_fn should resolve full team names to abbreviations."""
        import src.sports

        team_abbrev_fn = src.sports.spec("mlb").team_abbrev_fn
        self.assertIsNotNone(team_abbrev_fn)
        self.assertEqual(team_abbrev_fn("Boston Red Sox"), "BOS")
        # An unrecognised club is None, never a guessed abbreviation.
        self.assertIsNone(team_abbrev_fn("Unknown Team"))

    def test_nfl_schedule_fn_adapts_provider(self):
        """NFL.schedule_fn normalizes src.providers.nfl.registry_schedule_fn records.

        The fake below is one record in registry_schedule_fn's real shape -- that
        function returns the sport-neutral shape with game_id, away, home, start_utc.
        """
        import src.sports
        from src.providers import nfl as nfl_provider

        nfl_spec = src.sports.spec("nfl")
        self.assertIsNotNone(nfl_spec.schedule_fn)

        fake_game = {
            "game_id": "2026_01_BUF_DET",
            "away": "BUF",
            "home": "DET",
            "start_utc": "2026-09-10T00:15:00Z",
        }

        calls = []

        def fake_registry_schedule_fn(date_str):
            calls.append(date_str)
            return [fake_game]

        with mock.patch.object(nfl_provider, "registry_schedule_fn", fake_registry_schedule_fn):
            result = nfl_spec.schedule_fn("2026-09-10")

        self.assertEqual(calls, ["2026-09-10"])
        self.assertEqual(len(result), 1)
        game = result[0]
        self.assertEqual(sorted(game.keys()),
                         ["away", "game_id", "home", "start_utc"])
        self.assertEqual(game["game_id"], "2026_01_BUF_DET")
        self.assertEqual(game["away"], "BUF")
        self.assertEqual(game["home"], "DET")
        self.assertEqual(game["start_utc"], "2026-09-10T00:15:00Z")

    def test_nfl_team_abbrev_fn(self):
        """NFL.team_abbrev_fn should resolve full team names to abbreviations."""
        import src.sports

        team_abbrev_fn = src.sports.spec("nfl").team_abbrev_fn
        self.assertIsNotNone(team_abbrev_fn)
        self.assertEqual(team_abbrev_fn("Buffalo Bills"), "BUF")
        self.assertEqual(team_abbrev_fn("Kansas City Chiefs"), "KC")
        # An unrecognised team is None, never a guessed abbreviation.
        self.assertIsNone(team_abbrev_fn("Unknown Team"))

    def test_nfl_adapters_are_wired(self):
        """NFL now has schedule_fn and team_abbrev_fn wired from the provider."""
        import src.sports
        nfl_spec = src.sports.spec("nfl")
        self.assertIsNotNone(nfl_spec.schedule_fn)
        self.assertIsNotNone(nfl_spec.team_abbrev_fn)

    def test_tennis_stub_has_no_adapters(self):
        """Tennis provider lands later; None says so honestly."""
        import src.sports
        tennis_spec = src.sports.spec("tennis")
        self.assertIsNone(tennis_spec.schedule_fn)
        self.assertIsNone(tennis_spec.team_abbrev_fn)

    def test_spec_is_frozen(self):
        """A spec is a constant record; mutating one at runtime must fail."""
        import dataclasses
        import src.sports
        with self.assertRaises(dataclasses.FrozenInstanceError):
            src.sports.spec("mlb").odds_api_key = "something_else"


if __name__ == "__main__":
    unittest.main()
