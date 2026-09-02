"""Tests for src/providers/mlb.py. No network access -- _get_json is patched.

The critical behaviour under test is the final/pending distinction. An
in-progress game carries a partial score in the same field a final game uses,
so a loose check ingests garbage that is nearly impossible to spot later.
"""

import json
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from src.providers import mlb
from src.providers.mlb import MLBError

FIXTURES = Path(__file__).resolve().parent / "fixtures"


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


class FakeResponse:
    """Minimal stand-in for the context-manager urlopen returns."""

    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self):
        return self._payload


class TestBoundedTimeoutAndRetry(unittest.TestCase):
    """The red-team finding this closes: a stalled MLB response used to pin
    a worker for DEFAULT_TIMEOUT's old value of 20 seconds. These tests pin
    the fix -- bounded per-attempt timeouts, one retry on a stall/reset only,
    never on an HTTP error status -- with a fake transport so no real socket
    is ever opened.
    """

    def test_default_timeout_is_no_longer_twenty_seconds(self):
        # The whole point: a bounded value, not the old 20s worker-pinning one.
        self.assertLess(mlb.DEFAULT_TIMEOUT, 20)
        self.assertEqual(mlb.DEFAULT_TIMEOUT, mlb.MLB_TOTAL_TIMEOUT_S)

    def test_retries_once_on_timeout_then_succeeds(self):
        import socket as socket_mod
        good = FakeResponse(json.dumps({"dates": []}).encode("utf-8"))
        with mock.patch("urllib.request.urlopen",
                        side_effect=[urllib.error.URLError(socket_mod.timeout("stalled")), good]) as fake:
            result = mlb._get_json("schedule")
        self.assertEqual(result, {"dates": []})
        self.assertEqual(fake.call_count, 2)

    def test_retries_once_on_connection_reset_then_succeeds(self):
        good = FakeResponse(json.dumps({"dates": []}).encode("utf-8"))
        with mock.patch("urllib.request.urlopen",
                        side_effect=[urllib.error.URLError(ConnectionResetError("reset")), good]) as fake:
            result = mlb._get_json("schedule")
        self.assertEqual(result, {"dates": []})
        self.assertEqual(fake.call_count, 2)

    def test_second_timeout_in_a_row_still_raises_mlb_error(self):
        import socket as socket_mod
        with mock.patch("urllib.request.urlopen",
                        side_effect=[urllib.error.URLError(socket_mod.timeout("stalled")),
                                     urllib.error.URLError(socket_mod.timeout("stalled again"))]) as fake:
            with self.assertRaises(MLBError):
                mlb._get_json("schedule")
        self.assertEqual(fake.call_count, 2)

    def test_never_retries_a_404(self):
        # An HTTP error status means the provider DID answer. Retrying that
        # re-asks a question it already declined to answer -- the exact
        # behaviour the retry loop must never do.
        import urllib.error
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.HTTPError(
                            "u", 404, "not found", None, None)) as fake:
            with self.assertRaises(MLBError):
                mlb._get_json("schedule")
        self.assertEqual(fake.call_count, 1)

    def test_first_attempt_uses_the_bounded_connect_timeout(self):
        good = FakeResponse(json.dumps({}).encode("utf-8"))
        with mock.patch("urllib.request.urlopen", return_value=good) as fake:
            mlb._get_json("schedule")
        self.assertEqual(fake.call_args.kwargs["timeout"], mlb.MLB_CONNECT_TIMEOUT_S)

    def test_retry_attempt_uses_the_caller_supplied_timeout(self):
        import socket as socket_mod
        good = FakeResponse(json.dumps({}).encode("utf-8"))
        with mock.patch("urllib.request.urlopen",
                        side_effect=[urllib.error.URLError(socket_mod.timeout("stalled")), good]) as fake:
            mlb._get_json("schedule", timeout=30)
        first_call, second_call = fake.call_args_list
        self.assertEqual(first_call.kwargs["timeout"], mlb.MLB_CONNECT_TIMEOUT_S)
        self.assertEqual(second_call.kwargs["timeout"], 30)

    def test_env_override_is_read_by_env_float(self):
        # The module constants themselves are computed once at import time
        # (`importlib.reload` here would swap in a second MLBError class and
        # break every other test's assertRaises in this file, since they
        # hold a reference to the class from the first import) -- so this
        # pins the override behaviour at the level that actually varies:
        # `_env_float`, the function every timing constant is built from.
        with mock.patch.dict("os.environ", {"MLB_CONNECT_TIMEOUT_S": "1.5"}):
            self.assertEqual(mlb._env_float("MLB_CONNECT_TIMEOUT_S", 3.0), 1.5)

    def test_bad_env_value_falls_back_to_the_constant_not_a_crash(self):
        with mock.patch.dict("os.environ", {"MLB_CONNECT_TIMEOUT_S": "not-a-number"}):
            self.assertEqual(mlb._env_float("MLB_CONNECT_TIMEOUT_S", 3.0), 3.0)

    def test_missing_env_value_falls_back_to_the_constant(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            import os as os_mod
            os_mod.environ.pop("MLB_CONNECT_TIMEOUT_S", None)
            self.assertEqual(mlb._env_float("MLB_CONNECT_TIMEOUT_S", 3.0), 3.0)


if __name__ == "__main__":
    unittest.main()


class TestFirstFive(unittest.TestCase):
    """Grading a first-five market needs the half-inning line, not the final score.

    The five-inning result cannot be derived from the final score and frequently
    disagrees with it -- measured on 2026-08-26, CIN @ SF was 2-4 through five and
    10-9 the other way at the end.
    """

    @staticmethod
    def line(*pairs, complete_halves=True):
        innings = []
        for i, (away, home) in enumerate(pairs, start=1):
            entry = {"num": i, "away": {"runs": away}}
            entry["home"] = {"runs": home} if home is not None else {}
            innings.append(entry)
        return {"linescore": {"innings": innings}}

    def test_runs_are_summed_over_exactly_five_innings(self):
        game = self.line((1, 0), (0, 2), (0, 0), (3, 0), (0, 1), (9, 9))
        result = mlb.first_five(game)
        self.assertTrue(result["complete"])
        self.assertEqual(result["away_runs"], 4)
        self.assertEqual(result["home_runs"], 3)
        self.assertEqual(result["total_runs"], 7)
        self.assertEqual(result["winner"], "away")

    def test_later_innings_are_ignored_entirely(self):
        # The sixth-inning crooked number must not reach the first-five total.
        game = self.line((0, 0), (0, 0), (0, 0), (0, 0), (0, 1), (12, 0))
        self.assertEqual(mlb.first_five(game)["total_runs"], 1)
        self.assertEqual(mlb.first_five(game)["winner"], "home")

    def test_a_tie_through_five_is_reported_as_a_tie(self):
        # Unlike a full game, a first-five moneyline can genuinely push. Picking a
        # side here would fabricate a result.
        result = mlb.first_five(self.line((0, 0), (1, 1), (0, 0), (0, 0), (0, 0)))
        self.assertTrue(result["complete"])
        self.assertIsNone(result["winner"])
        self.assertEqual(result["total_runs"], 2)

    def test_a_game_with_fewer_than_five_innings_is_void_not_zero(self):
        result = mlb.first_five(self.line((1, 0), (0, 0), (2, 1)))
        self.assertFalse(result["complete"])
        self.assertIsNone(result["total_runs"])
        self.assertIn("void", result["reason"])

    def test_an_unplayed_home_half_of_the_fifth_is_void(self):
        # A game called after the top of the fifth with the home team ahead is an
        # official final game whose first five never finished. Rare, and therefore
        # dangerous: scoring it as a result would put a weather outcome in the record.
        result = mlb.first_five(self.line((0, 0), (0, 1), (0, 0), (0, 0), (0, None)))
        self.assertFalse(result["complete"])
        self.assertIsNone(result["home_runs"])
        self.assertIn("five full innings were not played", result["reason"])

    def test_a_missing_half_is_never_treated_as_a_zero(self):
        # The failure mode this guards: 0 is a perfectly plausible number of runs,
        # so a defaulted half-inning is invisible in the output.
        void = mlb.first_five(self.line((0, 0), (0, 0), (0, None), (0, 0), (0, 0)))
        self.assertFalse(void["complete"])
        self.assertIsNone(void["away_runs"])

    def test_a_game_with_no_linescore_is_void_rather_than_an_error(self):
        result = mlb.first_five({})
        self.assertFalse(result["complete"])
        self.assertEqual(result["innings_available"], 0)

    def test_parse_game_attaches_it(self):
        game = dict(self.line((1, 0), (0, 0), (0, 0), (0, 0), (0, 0)))
        game.update({"gamePk": 1, "officialDate": "2026-08-26",
                     "status": {"codedGameState": "F", "detailedState": "Final"},
                     "gameType": "R",
                     "teams": {"away": {"team": {"abbreviation": "TB"}, "score": 3},
                               "home": {"team": {"abbreviation": "DET"}, "score": 0}}})
        parsed = mlb.parse_game(game)
        self.assertEqual(parsed["first_five"]["away_runs"], 1)
        # The full-game score is untouched by the first-five calculation.
        self.assertEqual(parsed["away_score"], 3)


class TestOfficialsHydrateIsOptOut(unittest.TestCase):
    """The whole point of the flag: silence for every caller that ignores it."""

    def test_default_hydrate_never_mentions_officials(self):
        with mock.patch.object(mlb, "_get_json",
                               return_value=schedule_payload([])) as fake:
            mlb.fetch_schedule("2026-09-02")
        self.assertNotIn("officials", fake.call_args[0][1]["hydrate"])

    def test_hydrate_officials_true_adds_it_without_removing_the_rest(self):
        with mock.patch.object(mlb, "_get_json",
                               return_value=schedule_payload([])) as fake:
            mlb.fetch_schedule("2026-09-02", hydrate_officials=True)
        hydrate = fake.call_args[0][1]["hydrate"]
        self.assertIn("officials", hydrate)
        self.assertIn("probablePitcher", hydrate)
        self.assertIn("linescore", hydrate)

    def test_fetch_officials_requests_the_hydrate(self):
        with mock.patch.object(mlb, "_get_json",
                               return_value=schedule_payload([])) as fake:
            mlb.fetch_officials("2026-09-02")
        self.assertIn("officials", fake.call_args[0][1]["hydrate"])


class TestParseOfficialsOnRecordedFixture(unittest.TestCase):
    """A real response, captured live 2026-09-02, trimmed to three games:
    one still 'Scheduled' (officials not yet revealed) and two past
    'Pre-Game' (a full four-person crew). No field inside a kept game was
    edited -- only the game list was trimmed for size.
    """

    @classmethod
    def setUpClass(cls):
        with open(FIXTURES / "mlb_schedule_officials_2026-09-02.json",
                  encoding="utf-8") as handle:
            payload = json.load(handle)
        cls.games = {g["gamePk"]: g for g in payload["dates"][0]["games"]}

    def test_a_scheduled_game_has_not_revealed_its_crew(self):
        game = self.games[823660]
        self.assertEqual(game["status"]["detailedState"], "Scheduled")
        record = mlb.parse_officials(game)
        self.assertEqual(record["game_pk"], 823660)
        self.assertEqual(record["officials"], [])
        self.assertEqual(record["game_state"], "Scheduled")
        self.assertEqual(record["first_pitch_utc"], "2026-09-02T23:40:00Z")
        self.assertIsNone(mlb.home_plate_umpire(record["officials"]))

    def test_a_pre_game_slate_has_a_four_person_crew(self):
        game = self.games[824717]
        self.assertEqual(game["status"]["detailedState"], "Pre-Game")
        record = mlb.parse_officials(game)
        self.assertEqual(len(record["officials"]), 4)
        types = {o["officialType"] for o in record["officials"]}
        self.assertEqual(types, {"Home Plate", "First Base",
                                 "Second Base", "Third Base"})
        for official in record["officials"]:
            self.assertIsInstance(official["id"], int)
            self.assertTrue(official["name"])

    def test_home_plate_umpire_is_pulled_out_by_type_not_position(self):
        record = mlb.parse_officials(self.games[824717])
        plate = mlb.home_plate_umpire(record["officials"])
        self.assertIsNotNone(plate)
        expected = next(o["name"] for o in record["officials"]
                        if o["officialType"] == "Home Plate")
        self.assertEqual(plate, expected)

    def test_an_in_progress_game_also_carries_its_crew(self):
        record = mlb.parse_officials(self.games[824470])
        self.assertEqual(record["game_state"], "In Progress")
        self.assertEqual(len(record["officials"]), 4)

    def test_fetch_officials_end_to_end_on_the_fixture(self):
        with open(FIXTURES / "mlb_schedule_officials_2026-09-02.json",
                  encoding="utf-8") as handle:
            payload = json.load(handle)
        with mock.patch.object(mlb, "_get_json", return_value=payload):
            records = mlb.fetch_officials("2026-09-02")
        by_pk = {r["game_pk"]: r for r in records}
        self.assertEqual(len(records), 3)
        self.assertEqual(by_pk[823660]["officials"], [])
        self.assertEqual(len(by_pk[824717]["officials"]), 4)
