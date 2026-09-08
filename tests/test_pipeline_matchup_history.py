"""Tests for src/pipeline/matchup_history.py.

The properties that matter, same family as test_pipeline_lineup_store.py: a
pair fetched once is never fetched again (even across games and across
builds), a game already stored is skipped on rerun, an unposted lineup is
skipped without being marked failed, and read() hands back the exact shape
`briefing.build_slate(matchups_by_pk=...)` expects. The network is faked
throughout.
"""

import json
import tempfile
import unittest
from pathlib import Path

from src.pipeline import lineup_store, matchup_history
from src.providers import mlb


def _game(pk, away="LAD", home="SF", away_pid=100, home_pid=200):
    return {"game_pk": pk, "away_team": away, "home_team": home,
            "away_probable_id": away_pid, "home_probable_id": home_pid}


def _lineup_row(pk, away_ids, home_ids):
    def side(ids):
        return [{"order": i, "person_id": pid, "name": f"P{pid}", "position": "OF"}
                for i, pid in enumerate(ids, 1)]
    return {"date": "2026-06-01", "game_pk": pk,
            "away": side(away_ids), "home": side(home_ids)}


class FakeBatterVsPitcher:
    """Records every (batter, pitcher) pair actually fetched."""

    def __init__(self, line=None):
        self.line = line or {"at_bats": 4, "hits": 1, "home_runs": 0,
                             "strikeouts": 1, "walks": 0, "avg": 0.25, "ops": 0.6}
        self.calls = []

    def __call__(self, batter_id, pitcher_id, timeout=20):
        self.calls.append((batter_id, pitcher_id))
        return dict(self.line)


class TestBuild(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store_path = Path(self.tmp.name) / "matchup_history.jsonl"
        self.pair_path = Path(self.tmp.name) / "matchup_pairs.json"
        self.lineup_path = Path(self.tmp.name) / "lineups.jsonl"

    def _write_lineups(self, *rows):
        with self.lineup_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    def _build(self, games, fetch_bvp=None, resume=True):
        fetch_bvp = fetch_bvp or FakeBatterVsPitcher()
        report = matchup_history.build(
            "2026-06-01", lineup_path=self.lineup_path, path=self.store_path,
            pair_cache_path=self.pair_path, resume=resume,
            fetch_games=lambda iso, timeout=20: games,
            fetch_batter_vs_pitcher=fetch_bvp, sleep=lambda s: None)
        return report, fetch_bvp

    def test_a_pair_is_fetched_once_even_across_two_games(self):
        # The same batter (501) faces the same pitcher (200) in both games --
        # a division doubleheader shape. The second lookup must be a cache hit.
        self._write_lineups(
            _lineup_row(1, away_ids=[501], home_ids=[601]),
            _lineup_row(2, away_ids=[501], home_ids=[602]))
        games = [_game(1, away_pid=100, home_pid=200),
                 _game(2, away_pid=100, home_pid=200)]
        report, fetch = self._build(games)
        self.assertEqual(fetch.calls.count((501, 200)), 1)
        self.assertEqual(report["pairs_fetched"], 3)  # 501v200, 601v100, 602v100
        self.assertEqual(report["written"], 2)

    def test_resume_skips_a_game_pk_already_stored(self):
        self._write_lineups(_lineup_row(1, away_ids=[501], home_ids=[601]))
        games = [_game(1)]
        self._build(games)
        report, fetch = self._build(games)
        self.assertEqual(report["skipped_stored"], 1)
        self.assertEqual(report["written"], 0)
        self.assertEqual(fetch.calls, [])  # nothing refetched on rerun

    def test_a_game_with_no_posted_lineup_is_skipped_not_failed(self):
        # No lineup rows written at all -- lineup_store.read() returns {}.
        games = [_game(1)]
        report, fetch = self._build(games)
        self.assertEqual(report["skipped_no_lineup"], 1)
        self.assertEqual(report["written"], 0)
        self.assertEqual(report["failed"], 0)
        self.assertEqual(fetch.calls, [])

    def test_a_missing_probable_pitcher_skips_that_side_only(self):
        self._write_lineups(_lineup_row(1, away_ids=[501], home_ids=[601]))
        games = [_game(1, home_pid=None)]  # home has no probable
        report, fetch = self._build(games)
        self.assertEqual(report["written"], 1)
        store = matchup_history.read(self.store_path)
        # away lineup (601) vs the (missing) home probable never happened.
        self.assertIsNone(store["1"]["away"])
        # home lineup (501... wait, away_ids feed the away side) vs the away
        # probable (100) DID happen.
        self.assertIsNotNone(store["1"]["home"])

    def test_pair_cache_persists_across_separate_build_calls(self):
        self._write_lineups(_lineup_row(1, away_ids=[501], home_ids=[601]))
        self._build([_game(1)])
        self.assertIn("501:200", matchup_history.read_pairs(self.pair_path))
        # A second build, second date, same pitcher/batter pair reused.
        self._write_lineups(
            _lineup_row(1, away_ids=[501], home_ids=[601]),
            _lineup_row(3, away_ids=[501], home_ids=[701]))
        fetch = FakeBatterVsPitcher()
        matchup_history.build(
            "2026-06-02", lineup_path=self.lineup_path, path=self.store_path,
            pair_cache_path=self.pair_path,
            fetch_games=lambda iso, timeout=20: [_game(3)],
            fetch_batter_vs_pitcher=fetch, sleep=lambda s: None)
        self.assertNotIn((501, 200), fetch.calls)  # already cached from game 1

    def test_read_shape_matches_matchups_by_pk(self):
        self._write_lineups(_lineup_row(1, away_ids=[501, 502], home_ids=[601]))
        self._build([_game(1)])
        store = matchup_history.read(self.store_path)
        self.assertEqual(set(store), {"1"})
        self.assertEqual(set(store["1"]), {"home", "away"})
        self.assertIn("batters", store["1"]["home"])
        self.assertIn("total_at_bats", store["1"]["home"])
        self.assertIn("usable", store["1"]["home"])

    def test_thin_aggregate_reports_usable_false_with_a_reason(self):
        self._write_lineups(_lineup_row(1, away_ids=[501], home_ids=[601]))
        thin = FakeBatterVsPitcher({"at_bats": 2, "hits": 1, "home_runs": 0,
                                    "strikeouts": 0, "walks": 0, "avg": 0.5,
                                    "ops": 1.0})
        self._build([_game(1)], fetch_bvp=thin)
        store = matchup_history.read(self.store_path)
        self.assertFalse(store["1"]["home"]["usable"])
        self.assertIn("at least", store["1"]["home"]["reason"])

    def test_an_mlberror_on_one_pair_does_not_lose_the_rest_of_the_lineup(self):
        calls = []

        def flaky(batter_id, pitcher_id, timeout=20):
            calls.append((batter_id, pitcher_id))
            if batter_id == 502:
                raise mlb.MLBError("boom")
            return {"at_bats": 4, "hits": 1, "home_runs": 0, "strikeouts": 1,
                    "walks": 0, "avg": 0.25, "ops": 0.6}

        self._write_lineups(_lineup_row(1, away_ids=[501, 502], home_ids=[601]))
        report, _ = self._build([_game(1)], fetch_bvp=flaky)
        self.assertEqual(report["written"], 1)
        store = matchup_history.read(self.store_path)
        # 501/502 are the AWAY lineup, which faces the home probable.
        ids = [b["person_id"] for b in store["1"]["away"]["batters"]]
        self.assertEqual(ids, [501])  # 502 dropped, not fabricated


class TestRead(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "matchup_history.jsonl"

    def test_missing_file_is_empty_not_an_error(self):
        self.assertEqual(matchup_history.read(self.path), {})

    def test_read_pairs_missing_file_is_empty(self):
        self.assertEqual(
            matchup_history.read_pairs(Path(self.tmp.name) / "pairs.json"), {})

    def test_corrupt_row_raises_a_named_error(self):
        self.path.write_text("not json\n", encoding="utf-8")
        with self.assertRaises(matchup_history.MatchupHistoryError):
            matchup_history.read(self.path)


if __name__ == "__main__":
    unittest.main()
