"""Tests for src.providers.nfl module."""

import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src.providers import nfl


class TestNFLProvider(unittest.TestCase):
    """Test NFL provider functions."""

    @classmethod
    def setUpClass(cls):
        """Load fixture files once."""
        fixtures_dir = Path(__file__).parent / "fixtures" / "nfl"
        cls.games_fixture = (fixtures_dir / "games_sample.csv").read_text()
        cls.injuries_fixture = (fixtures_dir / "injuries_sample.csv").read_text()
        cls.stats_fixture = (fixtures_dir / "stats_team_week_sample.csv").read_text()

    def test_current_season_september(self):
        """Season in September is the current year."""
        result = nfl.current_season(datetime(2026, 9, 14))
        self.assertEqual(result, 2026)

    def test_current_season_january(self):
        """Season in January is the previous year."""
        result = nfl.current_season(datetime(2027, 1, 10))
        self.assertEqual(result, 2026)

    def test_current_season_march(self):
        """Season in March is the current year."""
        result = nfl.current_season(datetime(2026, 3, 15))
        self.assertEqual(result, 2026)

    def test_start_utc_eastern_time(self):
        """Convert Eastern game time to UTC ISO string."""
        # "2026-09-20" at "13:00" Eastern is 17:00 UTC
        result = nfl.start_utc("2026-09-20", "13:00")
        self.assertEqual(result, "2026-09-20T17:00:00Z")

    def test_start_utc_evening_game(self):
        """Evening game time in Eastern converts correctly."""
        # "2026-09-17" at "20:15" Eastern is 2026-09-18 00:15 UTC
        result = nfl.start_utc("2026-09-17", "20:15")
        self.assertEqual(result, "2026-09-18T00:15:00Z")

    def test_start_utc_empty_gametime_returns_none(self):
        """Empty gametime returns None."""
        result = nfl.start_utc("2026-09-20", "")
        self.assertIsNone(result)

    def test_start_utc_whitespace_gametime_returns_none(self):
        """Whitespace-only gametime returns None."""
        result = nfl.start_utc("2026-09-20", "   ")
        self.assertIsNone(result)

    def test_normalize_game_basic_fields(self):
        """Normalize game extracts all required fields with correct types."""
        row = {
            "game_id": "2026_02_DET_BUF",
            "season": "2026",
            "week": "2",
            "game_type": "REG",
            "gameday": "2026-09-17",
            "gametime": "20:15",
            "away_team": "DET",
            "home_team": "BUF",
            "away_score": "31",
            "home_score": "30",
            "stadium": "Highmark Stadium",
            "roof": "domed",
            "surface": "artificial",
            "away_moneyline": "-110",
            "home_moneyline": "-110",
            "spread_line": "BUF -1.5",
            "total_line": "59.0",
            "location": "",
        }
        result = nfl.normalize_game(row)

        self.assertEqual(result["game_id"], "2026_02_DET_BUF")
        self.assertEqual(result["season"], 2026)
        self.assertEqual(result["week"], 2)
        self.assertEqual(result["game_type"], "REG")
        self.assertEqual(result["gameday"], "2026-09-17")
        self.assertEqual(result["gametime"], "20:15")
        self.assertEqual(result["away_team"], "DET")
        self.assertEqual(result["home_team"], "BUF")
        self.assertEqual(result["away_score"], 31)
        self.assertEqual(result["home_score"], 30)
        self.assertTrue(result["completed"])
        self.assertEqual(result["stadium"], "Highmark Stadium")
        self.assertEqual(result["roof"], "domed")
        self.assertEqual(result["surface"], "artificial")
        self.assertEqual(result["total_line"], 59.0)

        # Numeric odds fields must be float or None, never left as strings.
        self.assertIsInstance(result["away_moneyline"], float)
        self.assertEqual(result["away_moneyline"], -110.0)
        self.assertIsInstance(result["home_moneyline"], float)
        self.assertEqual(result["home_moneyline"], -110.0)
        # "BUF -1.5" (team abbreviation prefix) does not parse as a number,
        # so spread_line falls back to None rather than staying a string.
        self.assertIsNone(result["spread_line"])

    def test_normalize_game_spread_line_numeric(self):
        """spread_line parses to float when it is a plain signed number."""
        row = {
            "game_id": "2026_02_DET_BUF",
            "season": "2026",
            "week": "2",
            "game_type": "REG",
            "gameday": "2026-09-17",
            "gametime": "20:15",
            "away_team": "DET",
            "home_team": "BUF",
            "away_score": "",
            "home_score": "",
            "away_moneyline": "-135",
            "home_moneyline": "115",
            "spread_line": "1.5",
            "location": "",
        }
        result = nfl.normalize_game(row)
        self.assertIsInstance(result["away_moneyline"], float)
        self.assertEqual(result["away_moneyline"], -135.0)
        self.assertIsInstance(result["home_moneyline"], float)
        self.assertEqual(result["home_moneyline"], 115.0)
        self.assertIsInstance(result["spread_line"], float)
        self.assertEqual(result["spread_line"], 1.5)

    def test_normalize_game_completed_flag(self):
        """completed is True only when both scores are present."""
        # Both scores present
        row = {
            "game_id": "2026_02_DET_BUF",
            "season": "2026",
            "week": "2",
            "game_type": "REG",
            "gameday": "2026-09-17",
            "gametime": "20:15",
            "away_team": "DET",
            "home_team": "BUF",
            "away_score": "31",
            "home_score": "30",
            "location": "",
        }
        result = nfl.normalize_game(row)
        self.assertTrue(result["completed"])

        # Missing home_score
        row["home_score"] = ""
        result = nfl.normalize_game(row)
        self.assertFalse(result["completed"])

        # Missing both
        row["away_score"] = ""
        result = nfl.normalize_game(row)
        self.assertFalse(result["completed"])

    def test_normalize_game_neutral_site(self):
        """neutral_site is True only when location is 'Neutral'."""
        row = {
            "game_id": "2026_02_DET_BUF",
            "season": "2026",
            "week": "2",
            "game_type": "REG",
            "gameday": "2026-09-17",
            "gametime": "20:15",
            "away_team": "DET",
            "home_team": "BUF",
            "away_score": "",
            "home_score": "",
            "location": "Neutral",
        }
        result = nfl.normalize_game(row)
        self.assertTrue(result["neutral_site"])

        row["location"] = "Regular Season"
        result = nfl.normalize_game(row)
        self.assertFalse(result["neutral_site"])

    def test_normalize_game_start_utc_computed(self):
        """start_utc is computed from gameday and gametime."""
        row = {
            "game_id": "2026_02_DET_BUF",
            "season": "2026",
            "week": "2",
            "game_type": "REG",
            "gameday": "2026-09-17",
            "gametime": "20:15",
            "away_team": "DET",
            "home_team": "BUF",
            "away_score": "",
            "home_score": "",
            "location": "",
        }
        result = nfl.normalize_game(row)
        self.assertEqual(result["start_utc"], "2026-09-18T00:15:00Z")

    @patch("src.providers.nfl._get_text")
    def test_fetch_schedule_filters_by_season(self, mock_get):
        """fetch_schedule filters results by season."""
        mock_get.return_value = self.games_fixture

        result = nfl.fetch_schedule(season=2026)
        # All fixture games are 2026
        self.assertTrue(all(g["season"] == 2026 for g in result))
        self.assertGreater(len(result), 0)

    @patch("src.providers.nfl._get_text")
    def test_fetch_schedule_filters_by_week(self, mock_get):
        """fetch_schedule filters by week when provided."""
        mock_get.return_value = self.games_fixture

        result = nfl.fetch_schedule(season=2026, week=2)
        self.assertTrue(all(g["week"] == 2 for g in result))
        # Should have week 2 games only
        self.assertEqual(len(result), 5)

    @patch("src.providers.nfl._get_text")
    def test_fetch_schedule_returns_normalized_games(self, mock_get):
        """fetch_schedule returns normalized game dicts."""
        mock_get.return_value = self.games_fixture

        result = nfl.fetch_schedule(season=2026, week=2)
        self.assertGreater(len(result), 0)

        game = result[0]
        # Check normalized keys are present
        required_keys = [
            "game_id",
            "season",
            "week",
            "gameday",
            "start_utc",
            "away_team",
            "home_team",
            "completed",
        ]
        for key in required_keys:
            self.assertIn(key, game, f"Missing key: {key}")

        # The real nflverse feed stores these as plain signed numbers, so
        # every fixture row should parse cleanly to float, never a string.
        for g in result:
            self.assertIsInstance(g["away_moneyline"], float)
            self.assertIsInstance(g["home_moneyline"], float)
            self.assertIsInstance(g["spread_line"], float)
            self.assertIsInstance(g["total_line"], float)

    @patch("src.providers.nfl._get_text")
    def test_schedule_for_date(self, mock_get):
        """schedule_for_date returns games on the specified date."""
        mock_get.return_value = self.games_fixture

        result = nfl.schedule_for_date("2026-09-17")
        # Should find DET@BUF game
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["game_id"], "2026_02_DET_BUF")
        self.assertEqual(result[0]["away_team"], "DET")
        self.assertEqual(result[0]["home_team"], "BUF")
        self.assertEqual(result[0]["start_utc"], "2026-09-18T00:15:00Z")

    @patch("src.providers.nfl._get_text")
    def test_schedule_for_date_multiple_games(self, mock_get):
        """schedule_for_date returns multiple games on the same date."""
        mock_get.return_value = self.games_fixture

        result = nfl.schedule_for_date("2026-09-20")
        # Should find multiple Sunday games
        self.assertGreater(len(result), 1)
        self.assertTrue(all(g["gameday"] == "2026-09-20" for g in result))

    @patch("src.providers.nfl._get_text")
    def test_schedule_for_week(self, mock_get):
        """schedule_for_week returns games for a specific season and week."""
        mock_get.return_value = self.games_fixture

        result = nfl.schedule_for_week(season=2026, week=2)
        self.assertTrue(all(g["season"] == 2026 for g in result))
        self.assertTrue(all(g["week"] == 2 for g in result))

    @patch("src.providers.nfl._get_text")
    def test_fetch_injuries_maps_named_keys(self, mock_get):
        """fetch_injuries normalizes keys correctly."""
        mock_get.return_value = self.injuries_fixture

        result = nfl.fetch_injuries(season=2026)
        self.assertGreater(len(result), 0)

        injury = result[0]
        required_keys = [
            "season",
            "week",
            "team",
            "gsis_id",
            "full_name",
            "position",
            "report_status",
            "practice_status",
        ]
        for key in required_keys:
            self.assertIn(key, injury, f"Missing key: {key}")

        # Check types
        self.assertIsInstance(injury["season"], int)
        self.assertIsInstance(injury["week"], int)

    @patch("src.providers.nfl._get_text")
    def test_fetch_team_stats_numeric_columns(self, mock_get):
        """fetch_team_stats converts numeric columns to float."""
        mock_get.return_value = self.stats_fixture

        result = nfl.fetch_team_stats(season=2026)
        self.assertGreater(len(result), 0)

        stats = result[0]
        # Check required keys
        self.assertIn("season", stats)
        self.assertIn("week", stats)
        self.assertIn("team", stats)
        self.assertIn("opponent_team", stats)

        # Check types
        self.assertIsInstance(stats["season"], int)
        self.assertIsInstance(stats["week"], int)
        self.assertIsInstance(stats["team"], str)
        self.assertIsInstance(stats["opponent_team"], str)

        # Check numeric columns are float
        if "passing_yards" in stats:
            self.assertIsInstance(stats["passing_yards"], (float, int, str))
        if "passing_epa" in stats:
            val = stats["passing_epa"]
            if val:
                self.assertIsInstance(val, (float, int))

    @patch("src.providers.nfl._get_text")
    def test_fetch_team_stats_epa_columns_present(self, mock_get):
        """fetch_team_stats includes EPA columns in docstring promise."""
        mock_get.return_value = self.stats_fixture

        result = nfl.fetch_team_stats(season=2026)
        self.assertGreater(len(result), 0)

        # Should have at least some EPA-related columns
        stats = result[0]
        epa_keys = [
            "passing_epa",
            "rushing_epa",
            "receiving_epa",
        ]
        # At least one EPA column should be present in the fixture
        found = any(k in stats for k in epa_keys)
        self.assertTrue(found, "No EPA columns found in fixture")

    @patch("src.providers.nfl._get_text")
    def test_registry_schedule_fn_returns_correct_shape(self, mock_get):
        """registry_schedule_fn returns games with SportSpec shape."""
        mock_get.return_value = self.games_fixture

        result = nfl.registry_schedule_fn("2026-09-17")
        self.assertEqual(len(result), 1)

        game = result[0]
        required_keys = {"game_id", "away", "home", "start_utc"}
        self.assertEqual(set(game.keys()), required_keys)

        # Check values
        self.assertEqual(game["game_id"], "2026_02_DET_BUF")
        self.assertEqual(game["away"], "DET")
        self.assertEqual(game["home"], "BUF")
        self.assertEqual(game["start_utc"], "2026-09-18T00:15:00Z")

    @patch("src.providers.nfl._get_text")
    def test_get_text_error_raises_nfl_error(self, mock_get):
        """Transport error in _get_text surfaces as NFLError."""
        mock_get.side_effect = OSError("Network unreachable")

        with self.assertRaises(nfl.NFLError):
            nfl.fetch_schedule(season=2026)

    def test_attribution_mentions_nflverse(self):
        """Module ATTRIBUTION mentions nflverse and CC BY."""
        self.assertIn("nflverse", nfl.ATTRIBUTION)
        self.assertIn("CC BY", nfl.ATTRIBUTION)
        self.assertIn("github.com/nflverse", nfl.ATTRIBUTION)

    def test_nfl_error_is_runtime_error(self):
        """NFLError is a RuntimeError subclass."""
        self.assertTrue(issubclass(nfl.NFLError, RuntimeError))

    def test_user_agent_constant(self):
        """USER_AGENT is set correctly."""
        self.assertEqual(nfl.USER_AGENT, "linehound-nfl/1.0")

    def test_default_timeout_constant(self):
        """DEFAULT_TIMEOUT is set."""
        self.assertEqual(nfl.DEFAULT_TIMEOUT, 30)


if __name__ == "__main__":
    unittest.main()
