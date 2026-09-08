"""Tests for src/pipeline/standings.py.

Point-in-time correctness is the hard rule this store exists to serve: a
date with no snapshot must come back honestly absent, never backfilled with
a nearby date's numbers. That is what most of these tests actually guard.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.pipeline import standings
from src.providers import mlb


def _record(team_id, name, division_id, division_name, league_id,
            division_rank, wins, losses, pct, games_back,
            wc_rank=None, wc_games_back=None):
    team_record = {
        "team": {"id": team_id, "name": name},
        "season": "2026",
        "streak": {"streakCode": "W1"},
        "divisionRank": str(division_rank),
        "gamesBack": games_back,
        "gamesPlayed": wins + losses,
        "wins": wins,
        "losses": losses,
        "winningPercentage": pct,
        "clinched": False,
        "divisionLeader": division_rank == 1,
        "wildCardGamesBack": wc_games_back if wc_games_back is not None else "-",
    }
    if wc_rank is not None:
        team_record["wildCardRank"] = str(wc_rank)
    return {
        "league": {"id": league_id},
        "division": {"id": division_id, "name": division_name},
        "teamRecords": [team_record],
    }


AL_EAST_LEADER = _record(139, "Rays", 201, "American League East",
                          mlb.LEAGUE_ID_AL, 1, 83, 55, ".601", "-")
AL_EAST_CHASER = _record(147, "Yankees", 201, "American League East",
                          mlb.LEAGUE_ID_AL, 2, 79, 60, ".568", "4.5",
                          wc_rank=1, wc_games_back="+8.5")
NL_CENTRAL_MID = _record(158, "Brewers", 205, "National League Central",
                          mlb.LEAGUE_ID_NL, 3, 70, 68, ".507", "6.5",
                          wc_rank=4, wc_games_back="2.0")


class TestBuildIsIdempotentAndResumable(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.path = Path(self.tmpdir.name) / "standings.jsonl"

    def test_build_appends_one_row_per_team(self):
        with mock.patch.object(mlb, "fetch_standings",
                                return_value=[AL_EAST_LEADER, AL_EAST_CHASER]):
            result = standings.build(2026, "2026-09-01", path=self.path)
        self.assertFalse(result["skipped"])
        self.assertEqual(result["teams"], 2)
        rows = [json.loads(l) for l in self.path.read_text().splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["date"], "2026-09-01")

    def test_a_second_build_for_the_same_date_is_a_noop(self):
        with mock.patch.object(mlb, "fetch_standings",
                                return_value=[AL_EAST_LEADER]) as fake:
            standings.build(2026, "2026-09-01", path=self.path)
            result = standings.build(2026, "2026-09-01", path=self.path)
        self.assertTrue(result["skipped"])
        self.assertEqual(fake.call_count, 1)  # second build never re-fetched
        rows = [json.loads(l) for l in self.path.read_text().splitlines()]
        self.assertEqual(len(rows), 1)  # never rewritten/duplicated

    def test_force_rebuilds_the_same_date_and_appends_again(self):
        with mock.patch.object(mlb, "fetch_standings",
                                return_value=[AL_EAST_LEADER]):
            standings.build(2026, "2026-09-01", path=self.path)
            standings.build(2026, "2026-09-01", path=self.path, force=True)
        rows = [json.loads(l) for l in self.path.read_text().splitlines()]
        self.assertEqual(len(rows), 2)  # append-only: force adds, never rewrites

    def test_a_provider_fault_is_recorded_not_raised(self):
        with mock.patch.object(mlb, "fetch_standings",
                                side_effect=mlb.MLBError("boom")):
            result = standings.build(2026, "2026-09-01", path=self.path)
        self.assertTrue(result["error"])
        self.assertIn("boom", result["reason"])
        self.assertFalse(self.path.exists() and self.path.stat().st_size > 0)


class TestCatchup(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.path = Path(self.tmpdir.name) / "standings.jsonl"

    def test_catchup_fills_a_date_range(self):
        with mock.patch.object(mlb, "fetch_standings",
                                return_value=[AL_EAST_LEADER]):
            report = standings.catchup(start="2026-09-01", end="2026-09-03",
                                        path=self.path)
        self.assertEqual(report["dates_built"], 3)
        self.assertEqual(report["dates_requested"], 3)
        dates = standings._stored_dates(self.path)
        self.assertEqual(dates, {"2026-09-01", "2026-09-02", "2026-09-03"})

    def test_catchup_skips_dates_already_stored(self):
        with mock.patch.object(mlb, "fetch_standings",
                                return_value=[AL_EAST_LEADER]) as fake:
            standings.build(2026, "2026-09-01", path=self.path)
            report = standings.catchup(start="2026-09-01", end="2026-09-02",
                                        path=self.path)
        self.assertEqual(report["dates_skipped"], 1)
        self.assertEqual(report["dates_built"], 1)
        self.assertEqual(fake.call_count, 2)  # one for the initial build, one new

    def test_bare_catchup_on_an_empty_store_only_reaches_today_not_the_whole_season(self):
        # No `start` given and nothing stored yet: must not silently kick off
        # an unbounded historical backfill.
        with mock.patch.object(mlb, "fetch_standings",
                                return_value=[AL_EAST_LEADER]):
            report = standings.catchup(end="2026-09-05", path=self.path)
        self.assertEqual(report["dates_requested"], 1)

    def test_bare_catchup_resumes_from_the_day_after_the_latest_snapshot(self):
        with mock.patch.object(mlb, "fetch_standings",
                                return_value=[AL_EAST_LEADER]):
            standings.build(2026, "2026-09-01", path=self.path)
            report = standings.catchup(end="2026-09-04", path=self.path)
        self.assertEqual(report["dates_requested"], 3)  # 09-02, 09-03, 09-04
        dates = standings._stored_dates(self.path)
        self.assertEqual(dates, {"2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"})

    def test_a_bad_date_is_recorded_in_errors_and_does_not_abort_the_run(self):
        def flaky(season, date=None, timeout=None):
            if date == "2026-09-02":
                raise mlb.MLBError("stalled")
            return [AL_EAST_LEADER]

        with mock.patch.object(mlb, "fetch_standings", side_effect=flaky):
            report = standings.catchup(start="2026-09-01", end="2026-09-03",
                                        path=self.path)
        self.assertEqual(len(report["errors"]), 1)
        self.assertEqual(report["errors"][0]["date"], "2026-09-02")
        self.assertEqual(report["dates_built"], 2)


class TestReadAndAccessor(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.path = Path(self.tmpdir.name) / "standings.jsonl"
        with mock.patch.object(
                mlb, "fetch_standings",
                return_value=[AL_EAST_LEADER, AL_EAST_CHASER, NL_CENTRAL_MID]):
            standings.build(2026, "2026-09-01", path=self.path)

    def test_read_on_a_missing_store_is_an_empty_dict(self):
        missing = Path(self.tmpdir.name) / "nope.jsonl"
        self.assertEqual(standings.read(missing), {})

    def test_read_indexes_by_date_then_team(self):
        index = standings.read(self.path)
        self.assertIn("2026-09-01", index)
        self.assertIn("TB", index["2026-09-01"])
        self.assertIn("NYY", index["2026-09-01"])

    def test_accessor_found_case_has_every_requested_field(self):
        row = standings.team_standing("2026-09-01", "TB", path=self.path)
        self.assertTrue(row["found"])
        self.assertEqual(row["wins"], 83)
        self.assertEqual(row["losses"], 55)
        self.assertAlmostEqual(row["win_pct"], 0.601)
        self.assertEqual(row["games_back"], 0.0)
        self.assertEqual(row["division_rank"], 1)
        self.assertEqual(row["division_name"], "American League East")
        self.assertIsNone(row["wildcard_rank"])
        self.assertIsNone(row["wildcard_games_back"])
        self.assertEqual(row["playoff_context"],
                          "1st in American League East, leads the division")

    def test_accessor_wildcard_chaser_context_line(self):
        row = standings.team_standing("2026-09-01", "NYY", path=self.path)
        self.assertEqual(row["division_rank"], 2)
        self.assertEqual(row["wildcard_rank"], 1)
        self.assertIn("4.5 GB", row["playoff_context"])
        self.assertIn("leads the 1st wild card by 8.5", row["playoff_context"])

    def test_accessor_wildcard_trailer_context_line(self):
        row = standings.team_standing("2026-09-01", "MIL", path=self.path)
        self.assertIn("6.5 GB", row["playoff_context"])
        self.assertIn("2.0 back of the last wild card", row["playoff_context"])

    def test_unknown_date_is_absent_never_a_nearby_date(self):
        row = standings.team_standing("2026-09-02", "TB", path=self.path)
        self.assertFalse(row["found"])
        self.assertIn("no standings snapshot stored for 2026-09-02", row["reason"])
        self.assertIsNone(row["wins"])
        self.assertIsNone(row["games_back"])
        self.assertIsNone(row["playoff_context"])

    def test_unknown_team_on_a_known_date_is_absent_with_a_reason(self):
        row = standings.team_standing("2026-09-01", "XXX", path=self.path)
        self.assertFalse(row["found"])
        self.assertIn("not found in the 2026-09-01 snapshot", row["reason"])
        self.assertIsNone(row["wins"])

    def test_accepted_alias_oak_resolves_to_ath(self):
        # Not present in this fixture, but must not raise/crash and must
        # normalize consistently -- exercised against a real team instead:
        # TB has no alias, so use the alias table directly.
        self.assertEqual(standings._normalize_team("oak"), "ATH")
        self.assertEqual(standings._normalize_team("ARI"), "AZ")
        self.assertEqual(standings._normalize_team("tb"), "TB")

    def test_index_can_be_reused_across_calls(self):
        index = standings.read(self.path)
        row = standings.team_standing("2026-09-01", "TB", index=index)
        self.assertTrue(row["found"])


class TestPlayoffContextLine(unittest.TestCase):

    def test_leader_line(self):
        row = {"division_rank": 1, "division_name": "AL East", "games_back": 0.0,
               "wildcard_rank": None, "wildcard_games_back": None, "wildcard_leading": None}
        self.assertEqual(standings.playoff_context_line(row), "1st in AL East, leads the division")

    def test_no_wildcard_data_known(self):
        row = {"division_rank": 3, "division_name": "NL West", "games_back": 5.0,
               "wildcard_rank": None, "wildcard_games_back": None, "wildcard_leading": None}
        self.assertEqual(standings.playoff_context_line(row), "3rd in NL West, 5.0 GB")

    def test_ordinal_suffixes(self):
        self.assertEqual(standings._ordinal(1), "1st")
        self.assertEqual(standings._ordinal(2), "2nd")
        self.assertEqual(standings._ordinal(3), "3rd")
        self.assertEqual(standings._ordinal(4), "4th")
        self.assertEqual(standings._ordinal(11), "11th")
        self.assertEqual(standings._ordinal(12), "12th")
        self.assertEqual(standings._ordinal(21), "21st")


if __name__ == "__main__":
    unittest.main()
