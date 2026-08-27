"""Tests for src/pipeline/slate.py. No network -- providers are patched.

The behaviour that matters: nothing is ever fabricated. Missing weather, a
missing key, and an unmatched odds event must all leave blanks and say so.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.pipeline import slate
from src.providers import odds as odds_provider
from src.providers import weather as weather_provider


def game(away="TOR", home="CWS", state="final", pk=1,
         away_score=1, home_score=2):
    return {
        "game_pk": pk, "date": "2025-07-09", "state": state,
        "start_time_utc": "2025-07-09T18:10:00Z",
        "venue": "Rate Field", "away_team": away, "home_team": home,
        "away_probable": "Eric Lauer", "home_probable": "Adrian Houser",
        "away_score": away_score, "home_score": home_score,
        "winner": home if home_score > away_score else away,
        "home_won": 1 if home_score > away_score else 0,
        "total_runs": away_score + home_score, "run_differential": 1,
    }


def odds_event(away="Toronto Blue Jays", home="Chicago White Sox"):
    return {
        "event_id": "e1", "commence_time": "2025-07-09T18:10:00Z",
        "away_team": away, "home_team": home,
        "markets": {
            "h2h": {"book": "draftkings", "away_price": 110, "home_price": -130},
            "spreads": {"book": "draftkings", "away_line": 1.5,
                        "away_price": -175, "home_line": -1.5, "home_price": 150},
            "totals": {"book": "draftkings", "total": 8.5,
                       "over_price": -110, "under_price": -110},
        },
    }


class TestTeamNameResolution(unittest.TestCase):
    def test_resolves_common_club_names(self):
        cases = {
            "Chicago Cubs": "CHC", "Chicago White Sox": "CWS",
            "Toronto Blue Jays": "TOR", "Boston Red Sox": "BOS",
            "Arizona Diamondbacks": "ARI", "Athletics": "OAK",
            "San Francisco Giants": "SF", "St. Louis Cardinals": "STL",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(slate.team_abbrev_from_name(name), expected)

    def test_white_sox_beats_red_sox_suffix_matching(self):
        # "Sox" alone is ambiguous; longest-suffix matching resolves it.
        self.assertEqual(slate.team_abbrev_from_name("Chicago White Sox"), "CWS")
        self.assertEqual(slate.team_abbrev_from_name("Boston Red Sox"), "BOS")

    def test_every_club_name_maps_to_a_real_park(self):
        from src.data import parks
        for abbrev in slate._NAME_TAIL_TO_ABBREV.values():
            with self.subTest(abbrev=abbrev):
                self.assertIn(abbrev, parks.PARKS)

    def test_all_thirty_clubs_are_covered(self):
        self.assertEqual(len(set(slate._NAME_TAIL_TO_ABBREV.values())), 30)

    def test_unknown_name_returns_none_not_a_guess(self):
        self.assertIsNone(slate.team_abbrev_from_name("Springfield Isotopes"))
        self.assertIsNone(slate.team_abbrev_from_name(""))
        self.assertIsNone(slate.team_abbrev_from_name(None))


class TestBuildSlate(unittest.TestCase):
    def build(self, games, env=None, weather_payloads=None, odds_events=None):
        env = {} if env is None else env
        with mock.patch.object(slate.mlb, "fetch_games", return_value=games), \
             mock.patch.object(weather_provider, "fetch_many",
                               return_value=weather_payloads or []), \
             mock.patch.object(odds_provider, "fetch_normalized",
                               return_value={"events": odds_events or []}):
            return slate.build_slate("2025-07-09", env=env)

    def test_schedule_fields_are_carried_through(self):
        result = self.build([game()])
        row = result["rows"][0]
        self.assertEqual(row["away_team"], "TOR")
        self.assertEqual(row["home_team"], "CWS")
        self.assertEqual(row["winner"], "CWS")
        self.assertEqual(row["away_probable"], "Eric Lauer")

    def test_park_data_is_attached_from_the_home_team(self):
        row = self.build([game()])["rows"][0]
        self.assertEqual(row["park_roof"], "open")
        self.assertIsNotNone(row["park_altitude_m"])

    def test_no_key_leaves_all_price_columns_blank(self):
        result = self.build([game()], env={})
        row = result["rows"][0]
        for column in ("ml_home_price", "ml_away_price", "rl_home_price",
                       "total_line", "ml_home_fair_prob"):
            with self.subTest(column=column):
                self.assertIsNone(row[column])
        self.assertFalse(result["odds_configured"])
        self.assertTrue(any("ODDS_API_KEY" in w for w in result["warnings"]))

    def test_odds_attach_and_are_devigged(self):
        result = self.build([game()], env={"ODDS_API_KEY": "k"},
                            odds_events=[odds_event()])
        row = result["rows"][0]
        self.assertEqual(row["ml_home_price"], -130)
        self.assertEqual(row["ml_away_price"], 110)
        # De-vigged probabilities must sum to 1, unlike the raw implied ones.
        total = row["ml_away_fair_prob"] + row["ml_home_fair_prob"]
        self.assertAlmostEqual(total, 1.0, places=5)
        self.assertGreater(row["ml_margin"], 0.0)

    def test_all_three_markets_land_in_the_row(self):
        row = self.build([game()], env={"ODDS_API_KEY": "k"},
                         odds_events=[odds_event()])["rows"][0]
        self.assertEqual(row["rl_home_line"], -1.5)
        self.assertEqual(row["total_line"], 8.5)
        self.assertEqual(row["total_over_price"], -110)

    def test_arizona_alias_resolves_on_the_schedule_side(self):
        # Live bug, caught against a real 2026-08-27 slate: the MLB schedule
        # emits "AZ" for Arizona while the odds feed's club name resolves to
        # "ARI". Comparing raw abbreviations silently drops the match even
        # though both sides individually resolve correctly.
        result = self.build(
            [game(away="AZ", home="SF")],
            env={"ODDS_API_KEY": "k"},
            odds_events=[odds_event(away="Arizona Diamondbacks",
                                    home="San Francisco Giants")],
        )
        row = result["rows"][0]
        self.assertEqual(row["ml_home_price"], -130)
        self.assertFalse(any("no odds matched" in w for w in result["warnings"]))

    def test_athletics_alias_resolves_on_the_schedule_side(self):
        result = self.build(
            [game(away="TOR", home="ATH")],
            env={"ODDS_API_KEY": "k"},
            odds_events=[odds_event(away="Toronto Blue Jays",
                                    home="Athletics")],
        )
        self.assertEqual(result["rows"][0]["ml_home_price"], -130)

    def test_unmatched_odds_event_leaves_prices_blank_and_warns(self):
        result = self.build([game()], env={"ODDS_API_KEY": "k"},
                            odds_events=[odds_event(home="Detroit Tigers")])
        self.assertIsNone(result["rows"][0]["ml_home_price"])
        self.assertTrue(any("no odds matched" in w for w in result["warnings"]))

    def test_cancelled_game_does_not_generate_an_odds_warning(self):
        result = self.build([game(state="cancelled")],
                            env={"ODDS_API_KEY": "k"}, odds_events=[])
        self.assertFalse(any("no odds matched" in w for w in result["warnings"]))

    def test_weather_failure_does_not_block_odds(self):
        with mock.patch.object(slate.mlb, "fetch_games", return_value=[game()]), \
             mock.patch.object(weather_provider, "fetch_many",
                               side_effect=weather_provider.WeatherError("429")), \
             mock.patch.object(odds_provider, "fetch_normalized",
                               return_value={"events": [odds_event()]}):
            result = slate.build_slate("2025-07-09", env={"ODDS_API_KEY": "k"})
        row = result["rows"][0]
        self.assertIsNone(row["weather_temp_f"])
        self.assertEqual(row["ml_home_price"], -130)
        self.assertTrue(any("weather unavailable" in w for w in result["warnings"]))

    def test_wind_effect_stays_blank_while_orientation_is_unverified(self):
        # The honest blank: wind is collected but not classified.
        payload = {"hourly": {
            "time": ["2025-07-09T18:00"], "temperature_2m": [77.0],
            "relative_humidity_2m": [60], "wind_speed_10m": [10.0],
            "wind_direction_10m": [180]}, "_source": "archive"}
        result = self.build([game()], weather_payloads=[payload])
        row = result["rows"][0]
        self.assertEqual(row["weather_wind_from_deg"], 180)
        self.assertIsNone(row["wind_effect"])

    def test_empty_schedule_is_not_an_error(self):
        result = self.build([])
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["coverage"]["games"], 0)


class TestCoverageReport(unittest.TestCase):
    def test_counts_analysable_games(self):
        rows = [
            {c: None for c in slate.SLATE_COLUMNS},
            {**{c: None for c in slate.SLATE_COLUMNS},
             "ml_away_price": 110, "ml_home_price": -130},
        ]
        report = slate.coverage_report(rows)
        self.assertEqual(report["games"], 2)
        self.assertEqual(report["analysable"], 1)
        self.assertEqual(report["not_analysable"], 1)

    def test_fill_rate_is_computed_not_asserted(self):
        rows = [
            {**{c: None for c in slate.SLATE_COLUMNS}, "weather_temp_f": 70.0},
            {c: None for c in slate.SLATE_COLUMNS},
        ]
        self.assertAlmostEqual(
            slate.coverage_report(rows)["fill_rate"]["weather_temp_f"], 0.5)

    def test_empty_slate_does_not_divide_by_zero(self):
        report = slate.coverage_report([])
        self.assertEqual(report["games"], 0)
        self.assertEqual(report["fill_rate"]["ml_home_price"], 0.0)


class TestPersistence(unittest.TestCase):
    def test_round_trip_preserves_values_and_blanks(self):
        rows = [{**{c: None for c in slate.SLATE_COLUMNS},
                 "date": "2025-07-09", "away_team": "TOR", "home_team": "CWS",
                 "ml_home_price": -130}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "slate.csv"
            slate.write_slate(rows, path)
            back = slate.read_slate(path)
        self.assertEqual(len(back), 1)
        self.assertEqual(back[0]["away_team"], "TOR")
        self.assertEqual(back[0]["ml_home_price"], "-130")
        # A blank must survive as None, not become the string "None".
        self.assertIsNone(back[0]["weather_temp_f"])

    def test_column_order_is_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "slate.csv"
            slate.write_slate([{c: None for c in slate.SLATE_COLUMNS}], path)
            header = path.read_text().splitlines()[0]
        self.assertEqual(header.split(","), slate.SLATE_COLUMNS)

    def test_missing_file_raises_a_clear_error(self):
        with self.assertRaises(slate.SlateError):
            slate.read_slate("/nonexistent/slate.csv")

    def test_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "deep" / "slate.csv"
            slate.write_slate([{c: None for c in slate.SLATE_COLUMNS}], path)
            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
