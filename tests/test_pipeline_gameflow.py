"""Tests for src/pipeline/gameflow.py and the play-by-play provider seam.

No network anywhere: `fetch_*` are injected, and the payloads are built by
`make_play_by_play` / `make_win_probability` below, which produce the exact
shape the real MLB Stats API serves (verified against game 824470 while this
module was written: `homeTeamWinProbability` is the probability AFTER the
play, `count.outs` is the outs AFTER the play, and the third out of a
half-inning carries outs=3).

These builders are imported by tests/test_gameflow_pit.py and
tests/test_report_postmortem.py so all three files exercise ONE fixture shape
rather than three that can drift apart.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.pipeline import gameflow
from src.providers import mlb


def make_play(*, index, inning, half, outs_after, event, event_type,
              away_score, home_score, batter=(1, "Batter One"),
              pitcher=(2, "Pitcher Two"), post_bases=(), rbi=0,
              scoring=False, description=None, complete=True):
    matchup = {
        "batter": {"id": batter[0], "fullName": batter[1]},
        "pitcher": {"id": pitcher[0], "fullName": pitcher[1]},
    }
    for base in post_bases:
        matchup[{"1B": "postOnFirst", "2B": "postOnSecond",
                 "3B": "postOnThird"}[base]] = {"id": 99}
    return {
        "result": {"event": event, "eventType": event_type, "rbi": rbi,
                   "awayScore": away_score, "homeScore": home_score,
                   "description": description or f"{batter[1]} {event.lower()}"},
        "about": {"atBatIndex": index, "inning": inning, "halfInning": half,
                  "isComplete": complete, "isScoringPlay": scoring,
                  "startTime": f"2026-09-02T1{inning}:00:00.000Z"},
        "count": {"balls": 0, "strikes": 0, "outs": outs_after},
        "matchup": matchup,
    }


def make_play_by_play(plays):
    return {"allPlays": list(plays)}


def make_win_probability(plays, home_probabilities):
    """One WP entry per play, mirroring the API: probability AFTER the play,
    plus that play's own added delta. `home_probabilities` are PERCENTS."""
    entries = []
    previous = 50.0
    for play, home_pct in zip(plays, home_probabilities):
        entries.append({
            "about": dict(play["about"]),
            "result": dict(play["result"]),
            "homeTeamWinProbability": home_pct,
            "awayTeamWinProbability": 100.0 - home_pct,
            "homeTeamWinProbabilityAdded": home_pct - previous,
            "leverageIndex": 1.0,
        })
        previous = home_pct
    return entries


# A four-play half-inning-crossing game used by several tests: the away team
# scores 2 in the top of the 1st, the home team never answers.
SIMPLE_PLAYS = [
    make_play(index=0, inning=1, half="top", outs_after=0, event="Single",
              event_type="single", away_score=0, home_score=0,
              post_bases=("1B",)),
    make_play(index=1, inning=1, half="top", outs_after=0, event="Home Run",
              event_type="home_run", away_score=2, home_score=0, rbi=2,
              scoring=True, batter=(3, "Slugger Three")),
    make_play(index=2, inning=1, half="top", outs_after=3, event="Triple Play",
              event_type="triple_play", away_score=2, home_score=0),
    make_play(index=3, inning=1, half="bottom", outs_after=1, event="Flyout",
              event_type="field_out", away_score=2, home_score=0,
              pitcher=(4, "Pitcher Four")),
]
SIMPLE_WP_PCT = [46.0, 25.0, 30.0, 28.0]


class TestParsePlayByPlay(unittest.TestCase):

    def test_outs_and_bases_are_pre_play_and_reset_each_half_inning(self):
        parsed = mlb.parse_play_by_play(
            1, make_play_by_play(SIMPLE_PLAYS),
            make_win_probability(SIMPLE_PLAYS, SIMPLE_WP_PCT))
        plays = parsed["plays"]
        self.assertEqual([p["outs_before"] for p in plays], [0, 0, 0, 0])
        self.assertEqual([p["outs_after"] for p in plays], [0, 0, 3, 1])
        # The single put a runner on first, so the NEXT play started with him
        # there; the home run cleared the bases for the play after it.
        self.assertEqual([p["bases_before"] for p in plays],
                          ["empty", "1B", "empty", "empty"])
        # New half-inning resets, even though the previous play left 3 outs.
        self.assertEqual(plays[3]["outs_before"], 0)

    def test_win_probability_is_joined_by_at_bat_index_never_invented(self):
        wp = make_win_probability(SIMPLE_PLAYS, SIMPLE_WP_PCT)
        del wp[2]  # the API served nothing for this play
        parsed = mlb.parse_play_by_play(1, make_play_by_play(SIMPLE_PLAYS), wp)
        plays = parsed["plays"]
        self.assertAlmostEqual(plays[0]["home_win_prob"], 0.46)
        self.assertAlmostEqual(plays[1]["home_win_prob_added"], -0.21)
        self.assertIsNone(plays[2]["home_win_prob"])
        self.assertIsNone(plays[2]["wp_source"])
        self.assertEqual(plays[0]["wp_source"], mlb.WP_SOURCE_MLB)
        self.assertTrue(parsed["wp_available"])

    def test_no_win_probability_at_all_is_reported_not_filled_in(self):
        parsed = mlb.parse_play_by_play(1, make_play_by_play(SIMPLE_PLAYS), [])
        self.assertFalse(parsed["wp_available"])
        for play in parsed["plays"]:
            self.assertIsNone(play["home_win_prob"])
            self.assertIsNone(play["away_win_prob"])
            self.assertIsNone(play["wp_source"])

    def test_incomplete_plays_are_dropped(self):
        plays = list(SIMPLE_PLAYS) + [
            make_play(index=4, inning=1, half="bottom", outs_after=1,
                      event="Single", event_type="single", away_score=2,
                      home_score=0, complete=False)]
        parsed = mlb.parse_play_by_play(1, make_play_by_play(plays), [])
        self.assertEqual(len(parsed["plays"]), 4)

    def test_probability_is_stored_as_a_fraction_not_a_percent(self):
        parsed = mlb.parse_play_by_play(
            1, make_play_by_play(SIMPLE_PLAYS),
            make_win_probability(SIMPLE_PLAYS, SIMPLE_WP_PCT))
        for play in parsed["plays"]:
            self.assertLessEqual(play["home_win_prob"], 1.0)
            self.assertAlmostEqual(play["home_win_prob"] + play["away_win_prob"],
                                    1.0, places=6)


class TestBuildRows(unittest.TestCase):

    def _rows(self, wp=None, meta=None):
        return gameflow.build_rows(
            "2026-09-02", 42, make_play_by_play(SIMPLE_PLAYS),
            wp if wp is not None else make_win_probability(SIMPLE_PLAYS,
                                                            SIMPLE_WP_PCT),
            "2026-09-03T04:00:00Z", game_meta=meta)

    def test_one_play_row_each_plus_one_game_row_written_last(self):
        rows = self._rows()
        self.assertEqual(sum(1 for r in rows if r["type"] == "play"), 4)
        self.assertEqual(rows[-1]["type"], "game")
        self.assertEqual(rows[-1]["n_plays"], 4)
        self.assertTrue(rows[-1]["wp_available"])

    def test_starters_are_read_off_the_first_play_of_each_half(self):
        rows = self._rows()
        game = rows[-1]
        # top half = the HOME team's pitcher; bottom half = the away team's.
        self.assertEqual(game["home_starter_id"], 2)
        self.assertEqual(game["away_starter_id"], 4)

    def test_game_meta_supplies_teams_probables_and_final_score(self):
        rows = self._rows(meta={"home_team": "CIN", "away_team": "SD",
                                 "home_score": 0, "away_score": 2,
                                 "home_probable_id": 2, "away_probable_id": 7})
        game = rows[-1]
        self.assertEqual((game["home_team"], game["away_team"]), ("CIN", "SD"))
        self.assertEqual((game["home_score_final"], game["away_score_final"]),
                          (0, 2))
        self.assertEqual(game["home_probable_id"], 2)

    def test_wp_available_false_when_the_api_served_none(self):
        rows = self._rows(wp=[])
        self.assertFalse(rows[-1]["wp_available"])


class TestIngestDate(unittest.TestCase):
    """Every dependency injected: no network, no clock, no default paths."""

    def _fakes(self, game_pks=(42, 43)):
        def fake_results(day, timeout=20):
            return {"final": [{"game_pk": pk, "home_team": "AAA",
                               "away_team": "BBB", "home_score": 0,
                               "away_score": 2} for pk in game_pks]}

        def fake_pbp(game_pk, timeout=20):
            return make_play_by_play(SIMPLE_PLAYS)

        def fake_wp(game_pk, timeout=20):
            return make_win_probability(SIMPLE_PLAYS, SIMPLE_WP_PCT)

        return fake_results, fake_pbp, fake_wp

    def _ingest(self, path, **kwargs):
        results, pbp, wp = self._fakes(kwargs.pop("game_pks", (42, 43)))
        return gameflow.ingest_date(
            "2026-09-02", path=path, fetch_results=results,
            fetch_play_by_play=pbp, fetch_win_probability=wp,
            sleep=lambda _s: None,
            clock=lambda: __import__("datetime").datetime(
                2026, 9, 3, tzinfo=__import__("datetime").timezone.utc),
            **kwargs)

    def test_writes_every_game_then_skips_them_all_on_a_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gameflow_2026.jsonl"
            first = self._ingest(path)
            self.assertEqual(first["games_written"], 2)
            self.assertEqual(first["play_rows"], 8)
            before = path.read_bytes()

            second = self._ingest(path)
            self.assertEqual(second["games_written"], 0)
            self.assertEqual(second["games_skipped"], 2)
            # Append-only and never rewritten: byte-identical after a rerun.
            self.assertEqual(path.read_bytes(), before)

    def test_a_failing_game_is_left_absent_so_a_rerun_retries_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gameflow_2026.jsonl"
            results, _pbp, wp = self._fakes()

            def angry_pbp(game_pk, timeout=20):
                if game_pk == 43:
                    raise mlb.MLBError("boom")
                return make_play_by_play(SIMPLE_PLAYS)

            report = gameflow.ingest_date(
                "2026-09-02", path=path, fetch_results=results,
                fetch_play_by_play=angry_pbp, fetch_win_probability=wp,
                sleep=lambda _s: None)
            self.assertEqual(report["games_written"], 1)
            self.assertEqual(len(report["errors"]), 1)
            self.assertNotIn(43, gameflow.game_pks_in_store(path))

            # The retry succeeds and writes it -- nothing marked it done.
            retry = self._ingest(path)
            self.assertEqual(retry["games_written"], 1)
            self.assertEqual(retry["games_skipped"], 1)

    def test_ingest_games_narrows_to_the_named_game_pks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gameflow_2026.jsonl"
            results, pbp, wp = self._fakes()
            report = gameflow.ingest_games(
                "2026-09-02", [43], path=path, fetch_results=results,
                fetch_play_by_play=pbp, fetch_win_probability=wp,
                sleep=lambda _s: None)
            self.assertEqual(report["games_written"], 1)
            self.assertEqual(gameflow.game_pks_in_store(path), {43})


class TestLoadGame(unittest.TestCase):

    def _store(self):
        return gameflow.build_rows(
            "2026-09-02", 42, make_play_by_play(SIMPLE_PLAYS),
            make_win_probability(SIMPLE_PLAYS, SIMPLE_WP_PCT),
            "2026-09-03T04:00:00Z")

    def test_returns_game_and_plays_in_at_bat_order(self):
        loaded = gameflow.load_game(self._store(), 42)
        self.assertEqual(loaded["game"]["n_plays"], 4)
        self.assertEqual([p["at_bat_index"] for p in loaded["plays"]],
                          [0, 1, 2, 3])

    def test_returns_none_for_an_unknown_game(self):
        self.assertIsNone(gameflow.load_game(self._store(), 999))
        self.assertIsNone(gameflow.load_game(self._store(), None))

    def test_returns_none_when_the_game_row_is_missing(self):
        """A truncated write (plays, no game row) is NOT a usable flow."""
        rows = [r for r in self._store() if r["type"] != "game"]
        self.assertIsNone(gameflow.load_game(rows, 42))


class TestStoreReadErrors(unittest.TestCase):

    def test_a_corrupt_line_raises_rather_than_being_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gameflow_2026.jsonl"
            path.write_text(json.dumps({"game_pk": 1}) + "\nnot json\n",
                            encoding="utf-8")
            with self.assertRaises(gameflow.GameFlowError):
                gameflow.read(path)


if __name__ == "__main__":
    unittest.main()
