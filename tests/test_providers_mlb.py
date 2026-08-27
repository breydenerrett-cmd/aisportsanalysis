"""Tests for src/providers/mlb.py. No network access -- _get_json is patched.

The critical behaviour under test is the final/pending distinction. An
in-progress game carries a partial score in the same field a final game uses,
so a loose check ingests garbage that is nearly impossible to spot later.
"""

import unittest
from unittest import mock

from src.providers import mlb
from src.providers.mlb import MLBError


def make_game(coded_state="F", away_score=1, home_score=2,
              away="TOR", home="CWS", game_pk=777172,
              away_probable="Eric Lauer", home_probable="Adrian Houser",
              game_type="R"):
    """Build an API-shaped game record. Mirrors the live payload structure."""
    def side(abbrev, score, probable, team_id):
        entry = {"team": {"abbreviation": abbrev, "name": abbrev, "id": team_id}}
        if score is not None:
            entry["score"] = score
        if probable is not None:
            entry["probablePitcher"] = {"fullName": probable, "id": 1000 + team_id}
        return entry

    return {
        "gamePk": game_pk,
        "gameType": game_type,
        "officialDate": "2025-07-09",
        "gameDate": "2025-07-09T18:10:00Z",
        "status": {"codedGameState": coded_state, "detailedState": "X"},
        "venue": {"name": "Rate Field"},
        "teams": {
            "away": side(away, away_score, away_probable, 141),
            "home": side(home, home_score, home_probable, 145),
        },
    }


def schedule_payload(games):
    return {"dates": [{"games": games}]} if games else {"dates": []}


class TestGameState(unittest.TestCase):
    def test_final_game_is_final(self):
        self.assertTrue(mlb.is_final(make_game("F")))

    def test_game_over_code_is_also_final(self):
        self.assertTrue(mlb.is_final(make_game("O")))

    def test_in_progress_is_not_final_even_with_scores(self):
        # The exact bug this guards: partial scores look like final scores.
        game = make_game("I", away_score=6, home_score=2)
        self.assertFalse(mlb.is_final(game))
        self.assertEqual(mlb.game_state(game), "pending")

    def test_scheduled_is_not_final(self):
        self.assertFalse(mlb.is_final(make_game("S", None, None)))

    def test_final_code_without_scores_is_not_final(self):
        self.assertFalse(mlb.is_final(make_game("F", None, None)))

    def test_zero_score_is_a_real_score_not_a_missing_one(self):
        # A shutout must not be mistaken for absent data.
        self.assertTrue(mlb.is_final(make_game("F", 0, 3)))

    def test_postponed_is_cancelled(self):
        game = make_game("D", None, None)
        self.assertTrue(mlb.is_cancelled(game))
        self.assertEqual(mlb.game_state(game), "cancelled")

    def test_missing_status_block_is_pending_not_a_crash(self):
        self.assertEqual(mlb.game_state({"teams": {}}), "pending")


class TestParseGame(unittest.TestCase):
    def test_extracts_core_fields(self):
        record = mlb.parse_game(make_game())
        self.assertEqual(record["game_pk"], 777172)
        self.assertEqual(record["away_team"], "TOR")
        self.assertEqual(record["home_team"], "CWS")
        self.assertEqual(record["date"], "2025-07-09")
        self.assertEqual(record["venue"], "Rate Field")

    def test_home_win_is_recorded_correctly(self):
        record = mlb.parse_game(make_game(away_score=1, home_score=2))
        self.assertEqual(record["winner"], "CWS")
        self.assertEqual(record["home_won"], 1)
        self.assertEqual(record["total_runs"], 3)
        self.assertEqual(record["run_differential"], 1)

    def test_away_win_is_recorded_correctly(self):
        record = mlb.parse_game(make_game(away_score=7, home_score=3))
        self.assertEqual(record["winner"], "TOR")
        self.assertEqual(record["home_won"], 0)
        self.assertEqual(record["run_differential"], 4)

    def test_pending_game_has_no_winner_and_no_derived_fields(self):
        record = mlb.parse_game(make_game("I", 6, 2))
        self.assertIsNone(record["winner"])
        self.assertIsNone(record["home_won"])
        self.assertIsNone(record["total_runs"])
        # The partial scores are still surfaced, but clearly marked pending.
        self.assertEqual(record["state"], "pending")
        self.assertEqual(record["away_score"], 6)

    def test_tied_final_in_a_competitive_game_is_rejected(self):
        # A regular season game must have a winner; a tie means bad data.
        game = make_game("F", 3, 3)
        game["gameType"] = "R"
        with self.assertRaises(MLBError):
            mlb.parse_game(game)

    def test_tied_final_in_spring_training_is_a_legitimate_result(self):
        # Found live: four March 2025 dates failed to ingest entirely because
        # spring games legitimately end level once both sides run out of
        # pitchers. ATL 0-0 DET and WSH 5-5 NYM were real finals.
        game = make_game("F", 5, 5)
        game["gameType"] = "S"
        record = mlb.parse_game(game)
        self.assertIsNone(record["winner"])
        self.assertIsNone(record["home_won"])
        self.assertEqual(record["total_runs"], 10)
        self.assertEqual(record["run_differential"], 0)

    def test_tied_all_star_game_is_allowed(self):
        # The 2002 All-Star Game ended 7-7.
        game = make_game("F", 7, 7)
        game["gameType"] = "A"
        self.assertIsNone(mlb.parse_game(game)["winner"])

    def test_tied_postseason_game_is_rejected(self):
        for game_type in ("F", "D", "L", "W"):
            with self.subTest(game_type=game_type):
                game = make_game("F", 2, 2)
                game["gameType"] = game_type
                with self.assertRaises(MLBError):
                    mlb.parse_game(game)

    def test_tied_game_of_unknown_type_refuses_to_guess(self):
        # Neither decisive nor known-tie-allowed: the honest answer is to stop
        # rather than assume which rule applies.
        game = make_game("F", 4, 4)
        game["gameType"] = "Z"
        with self.assertRaises(MLBError) as ctx:
            mlb.parse_game(game)
        self.assertIn("unknown gameType", str(ctx.exception))

    def test_decided_spring_game_still_gets_a_winner(self):
        game = make_game("F", 2, 6)
        game["gameType"] = "S"
        record = mlb.parse_game(game)
        self.assertEqual(record["winner"], "CWS")
        self.assertEqual(record["home_won"], 1)

    def test_game_type_is_captured(self):
        game = make_game()
        game["gameType"] = "R"
        self.assertEqual(mlb.parse_game(game)["game_type"], "R")

    def test_regular_season_is_the_only_training_game_type(self):
        self.assertEqual(mlb.TRAINING_GAME_TYPES, frozenset({"R"}))
        self.assertNotIn("S", mlb.TRAINING_GAME_TYPES)

    def test_missing_probable_pitcher_stays_none(self):
        record = mlb.parse_game(make_game(away_probable=None))
        self.assertIsNone(record["away_probable"])
        self.assertIsNone(record["away_probable_id"])
        self.assertEqual(record["home_probable"], "Adrian Houser")

    def test_blank_pitcher_name_is_treated_as_missing(self):
        game = make_game()
        game["teams"]["away"]["probablePitcher"]["fullName"] = "   "
        self.assertIsNone(mlb.parse_game(game)["away_probable"])

    def test_abbreviations_are_normalized(self):
        game = make_game(away=" tor ")
        self.assertEqual(mlb.parse_game(game)["away_team"], "TOR")


class TestFetchResults(unittest.TestCase):
    def test_splits_games_by_state(self):
        games = [
            make_game("F", 1, 2, game_pk=1),
            make_game("I", 3, 1, game_pk=2),
            make_game("D", None, None, game_pk=3),
        ]
        with mock.patch.object(mlb, "_get_json",
                               return_value=schedule_payload(games)):
            result = mlb.fetch_results("2025-07-09")
        self.assertEqual(result["summary"],
                         {"total": 3, "final": 1, "pending": 1, "cancelled": 1})
        self.assertEqual(len(result["final"]), 1)
        self.assertEqual(result["final"][0]["game_pk"], 1)

    def test_a_slate_with_nothing_final_reports_zero(self):
        # This is the July 2026 situation: games underway, nothing usable.
        games = [make_game("I", 6, 2), make_game("I", 5, 1)]
        with mock.patch.object(mlb, "_get_json",
                               return_value=schedule_payload(games)):
            result = mlb.fetch_results("2026-07-09")
        self.assertEqual(result["summary"]["final"], 0)
        self.assertEqual(result["final"], [])

    def test_empty_date_returns_empty_not_an_error(self):
        with mock.patch.object(mlb, "_get_json", return_value=schedule_payload([])):
            result = mlb.fetch_results("2025-01-15")
        self.assertEqual(result["summary"]["total"], 0)

    def test_requests_the_right_endpoint_and_params(self):
        with mock.patch.object(mlb, "_get_json",
                               return_value=schedule_payload([])) as fake:
            mlb.fetch_schedule("2025-07-09")
        path, params = fake.call_args[0][0], fake.call_args[0][1]
        self.assertEqual(path, "schedule")
        self.assertEqual(params["date"], "2025-07-09")
        self.assertEqual(params["sportId"], 1)
        self.assertIn("probablePitcher", params["hydrate"])


class TestIterDates(unittest.TestCase):
    def test_inclusive_of_both_ends(self):
        dates = list(mlb.iter_dates("2025-07-01", "2025-07-03"))
        self.assertEqual(dates, ["2025-07-01", "2025-07-02", "2025-07-03"])

    def test_single_day_range(self):
        self.assertEqual(list(mlb.iter_dates("2025-07-01", "2025-07-01")),
                         ["2025-07-01"])

    def test_crosses_month_and_year_boundaries(self):
        self.assertEqual(list(mlb.iter_dates("2025-12-30", "2026-01-01")),
                         ["2025-12-30", "2025-12-31", "2026-01-01"])

    def test_reversed_range_rejected(self):
        with self.assertRaises(MLBError):
            list(mlb.iter_dates("2025-07-03", "2025-07-01"))

    def test_bad_date_format_rejected(self):
        for bad in ("07/09/2025", "not-a-date", 20250709, None):
            with self.subTest(bad=bad):
                with self.assertRaises(MLBError):
                    list(mlb.iter_dates(bad, "2025-07-01"))


class TestBackfill(unittest.TestCase):
    def test_collects_only_final_games_across_a_range(self):
        payloads = [
            schedule_payload([make_game("F", 1, 2, game_pk=1)]),
            schedule_payload([make_game("I", 3, 1, game_pk=2)]),
            schedule_payload([make_game("F", 4, 0, game_pk=3)]),
        ]
        with mock.patch.object(mlb, "_get_json", side_effect=payloads):
            result = mlb.backfill_results("2025-07-01", "2025-07-03")
        self.assertEqual(result["final_games"], 2)
        self.assertEqual([g["game_pk"] for g in result["games"]], [1, 3])
        self.assertEqual(result["dates_requested"], 3)

    def test_one_bad_date_does_not_abort_the_run(self):
        payloads = [
            schedule_payload([make_game("F", 1, 2, game_pk=1)]),
            MLBError("MLB API returned HTTP 500 for schedule"),
            schedule_payload([make_game("F", 4, 0, game_pk=3)]),
        ]
        with mock.patch.object(mlb, "_get_json", side_effect=payloads):
            result = mlb.backfill_results("2025-07-01", "2025-07-03")
        self.assertEqual(result["final_games"], 2)
        self.assertEqual(result["dates_failed"], 1)
        self.assertEqual(result["errors"][0]["date"], "2025-07-02")

    def test_progress_callback_fires_per_successful_date(self):
        payloads = [schedule_payload([make_game("F")]) for _ in range(3)]
        seen = []
        with mock.patch.object(mlb, "_get_json", side_effect=payloads):
            mlb.backfill_results("2025-07-01", "2025-07-03",
                                 on_date=lambda r: seen.append(r["date"]))
        self.assertEqual(seen, ["2025-07-01", "2025-07-02", "2025-07-03"])


class TestTransportErrors(unittest.TestCase):
    def test_http_error_becomes_mlb_error(self):
        import urllib.error
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.HTTPError(
                            "u", 500, "boom", None, None)):
            with self.assertRaises(MLBError) as ctx:
                mlb._get_json("schedule")
        self.assertIn("500", str(ctx.exception))

    def test_network_failure_becomes_mlb_error(self):
        import urllib.error
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("offline")):
            with self.assertRaises(MLBError):
                mlb._get_json("schedule")


if __name__ == "__main__":
    unittest.main()
