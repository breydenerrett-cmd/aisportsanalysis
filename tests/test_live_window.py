"""Tests for src.pipeline.live_window.

All tests use fakes, temp directories, and a fake clock that advances per sleep.
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.pipeline import live_window


class FakeClock:
    """Advances on each sleep() call."""

    def __init__(self, start_utc=None):
        self.now = start_utc or datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += timedelta(seconds=seconds)


class TestPregameContext(unittest.TestCase):
    """Tests for pregame_context."""

    def test_pregame_context_mlb_with_fixture_data(self):
        """pregame_context returns game_pk -> pregame dict with favourite."""
        games = [
            {
                "game_pk": 747101,
                "start_time_utc": "2026-09-14T21:40:00Z",
                "teams": {
                    "home": {
                        "team": {"name": "Boston Red Sox"},
                        "probablePitcher": {"id": 112211},
                    },
                    "away": {
                        "team": {"name": "New York Yankees"},
                        "probablePitcher": {"id": 123456},
                    },
                },
            }
        ]
        rows = [
            {
                "sport": "mlb",
                "home_team": "Boston Red Sox",
                "away_team": "New York Yankees",
                "commence_time": "2026-09-14T21:40:00Z",
                "book": "DraftKings",
                "home_price": -110,
                "away_price": -110,
                "observed_utc": "2026-09-14T20:00:00Z",
            },
        ]

        context = live_window.pregame_context(
            "mlb", "2026-09-14", rows=rows, games=games
        )

        self.assertIn("747101", context)
        self.assertEqual(context["747101"]["sport"], "mlb")
        self.assertEqual(context["747101"]["home_team"], "Boston Red Sox")
        self.assertEqual(context["747101"]["away_team"], "New York Yankees")
        self.assertIn(context["747101"]["favorite"], ["home", "away", None])

    def test_pregame_context_nfl_with_data(self):
        """pregame_context works for NFL games."""
        games = [
            {
                "game_id": "2026_02_DET_BUF",
                "start_utc": "2026-09-14T01:20:00Z",
                "home": "Buffalo Bills",
                "away": "Detroit Lions",
            }
        ]

        context = live_window.pregame_context("nfl", "2026-09-14", games=games)

        self.assertIn("2026_02_DET_BUF", context)
        self.assertEqual(context["2026_02_DET_BUF"]["sport"], "nfl")

    def test_pregame_context_empty_games(self):
        """pregame_context returns empty dict when no games."""
        context = live_window.pregame_context("mlb", "2026-09-15", games=[])
        self.assertEqual(context, {})


class TestTick(unittest.TestCase):
    """Tests for tick."""

    def test_tick_no_changes(self):
        """tick calls no capture when states don't change."""
        def mock_poll():
            return {"live_games": 1, "rows_written": 1}

        def mock_capture(*args, **kwargs):
            return {"captured": 0}

        state = {
            "date": "2026-09-14",
            "prev_states": {"pk1": {"status": "Live", "home_runs": 0, "away_runs": 0}},
            "pregame": {},
        }

        deps = {
            "poll": mock_poll,
            "capture": mock_capture,
        }

        with mock.patch("src.pipeline.livefeed_mlb.latest_states") as m_states:
            m_states.return_value = {"pk1": {"status": "Live", "home_runs": 0, "away_runs": 0}}
            result = live_window.tick("mlb", state=state, deps=deps)

        self.assertEqual(result["changed"], 0)

    def test_tick_records_candidate_on_rule_fire(self):
        """tick records a candidate when a rule fires."""
        def mock_poll():
            return {"live_games": 1, "rows_written": 1}

        def mock_capture(*args, **kwargs):
            return {"captured": 5}

        state = {
            "date": "2026-09-14",
            "prev_states": {},
            "pregame": {
                "pk1": {
                    "sport": "mlb",
                    "game_id": "pk1",
                    "home_team": "Boston Red Sox",
                    "away_team": "New York Yankees",
                    "favorite": "home",
                    "favorite_prob": 0.6,
                    "starter_ids": {"home": 1, "away": 2},
                    "event_id": "evt1",
                }
            },
        }

        def mock_evaluate(*, pregame, state, quote):
            return [
                {
                    "rule_id": "mlb_favorite_trails_after_3",
                    "sport": "mlb",
                    "game_id": "pk1",
                    "side": "home",
                    "team": "Boston Red Sox",
                    "bet": "Boston Red Sox moneyline",
                    "price": -110,
                    "books": 5,
                    "state_id": "abc123",
                    "observed_utc": "2026-09-14T20:00:00Z",
                    "trigger": {"inning": 3},
                }
            ]

        def mock_record(candidate):
            return {**candidate, "recorded_utc": "2026-09-14T20:00:01Z"}

        deps = {
            "poll": mock_poll,
            "capture": mock_capture,
            "evaluate": mock_evaluate,
            "record": mock_record,
        }

        new_state = {
            "status": "Live",
            "home_runs": 1,
            "away_runs": 2,
            "inning": 3,
            "observed_utc": "2026-09-14T20:00:00Z",
        }

        with mock.patch("src.pipeline.livefeed_mlb.latest_states") as m_states:
            m_states.return_value = {"pk1": new_state}
            with mock.patch("src.pipeline.live_odds.latest_inplay_quote") as m_quote:
                m_quote.return_value = {
                    "observed_utc": "2026-09-14T20:00:00Z",
                    "quotes": [
                        {"book": "DraftKings", "home_price": -110, "away_price": 100}
                    ],
                }
                with mock.patch("src.pipeline.live_odds.read_inplay") as m_inplay:
                    m_inplay.return_value = []
                    result = live_window.tick("mlb", state=state, deps=deps)

        self.assertGreater(result["candidates_new"], 0)


class TestShouldDispatch(unittest.TestCase):
    """Tests for should_dispatch."""

    def test_should_dispatch_live_game_mlb(self):
        """should_dispatch returns True when a live game is running."""
        now = datetime(2026, 9, 14, 21, 0, 0, tzinfo=timezone.utc)
        games = [
            {
                "game_pk": 747101,
                "start_time_utc": "2026-09-14T21:00:00Z",
                "status": {"abstractGameState": "Live"},
            }
        ]

        def mock_schedule(date):
            return games

        can_run, reason = live_window.should_dispatch(
            "mlb", now=now, schedule=mock_schedule
        )

        self.assertTrue(can_run)
        self.assertIn("Live", reason)

    def test_should_dispatch_game_starts_soon(self):
        """should_dispatch returns True when a game starts within 30 minutes."""
        now = datetime(2026, 9, 14, 20, 0, 0, tzinfo=timezone.utc)
        games = [
            {
                "game_pk": 747101,
                "start_time_utc": "2026-09-14T20:20:00Z",
                "status": {"abstractGameState": "Pre-Game"},
            }
        ]

        def mock_schedule(date):
            return games

        can_run, reason = live_window.should_dispatch(
            "mlb", now=now, schedule=mock_schedule
        )

        self.assertTrue(can_run)
        self.assertIn("within 30 minutes", reason)

    def test_should_dispatch_nothing_happening(self):
        """should_dispatch returns False when no games are live/starting soon."""
        now = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)
        games = [
            {
                "game_pk": 747101,
                "start_time_utc": "2026-09-14T21:00:00Z",
                "status": {"abstractGameState": "Pre-Game"},
            }
        ]

        def mock_schedule(date):
            return games

        can_run, reason = live_window.should_dispatch(
            "mlb", now=now, schedule=mock_schedule
        )

        self.assertFalse(can_run)
        self.assertIn("nothing starts", reason)

    def test_should_dispatch_nfl_outside_window(self):
        """should_dispatch returns False for NFL outside broadcast windows."""
        # Tuesday 10 AM ET
        now = datetime(2026, 9, 15, 14, 0, 0, tzinfo=timezone.utc)

        can_run, reason = live_window.should_dispatch("nfl", now=now)

        self.assertFalse(can_run)
        self.assertIn("outside", reason)

    def test_should_dispatch_already_running(self):
        """should_dispatch returns False when window is already running."""
        now = datetime(2026, 9, 14, 21, 0, 0, tzinfo=timezone.utc)

        def mock_running():
            return True

        can_run, reason = live_window.should_dispatch(
            "mlb", now=now, running=mock_running
        )

        self.assertFalse(can_run)
        self.assertIn("already running", reason)


class TestRun(unittest.TestCase):
    """Tests for run."""

    def test_run_stops_early_when_no_games_nearby(self):
        """run exits early when nothing is live and nothing starts within 30 min."""
        clock = FakeClock()

        def mock_poll():
            return {"live_games": 0, "rows_written": 0}

        def mock_schedule(date):
            return []

        deps = {
            "poll": mock_poll,
        }

        with mock.patch("src.pipeline.livefeed_mlb.latest_states") as m_states:
            m_states.return_value = {}
            with mock.patch("src.providers.mlb.fetch_games") as m_fetch:
                m_fetch.return_value = []
                result = live_window.run(
                    "mlb", max_minutes=330, clock=clock, sleep=clock.sleep, deps=deps
                )

        self.assertLessEqual(result["ticks"], 2)
        self.assertIn("nothing starts", result["stopped_reason"])

    def test_run_commits_at_interval(self):
        """run calls commit at the specified interval."""
        clock = FakeClock()
        commits = []

        def mock_poll():
            return {"live_games": 1, "rows_written": 1}

        def mock_commit():
            commits.append(clock())

        deps = {"poll": mock_poll}

        with mock.patch("src.pipeline.livefeed_mlb.latest_states") as m_states:
            m_states.return_value = {"pk1": {"status": "Live"}}
            with mock.patch("src.providers.mlb.fetch_games") as m_fetch:
                m_fetch.return_value = [
                    {
                        "game_pk": "pk1",
                        "start_time_utc": "2026-09-14T21:00:00Z",
                        "status": {"abstractGameState": "Live"},
                    }
                ]
                result = live_window.run(
                    "mlb",
                    max_minutes=10,
                    clock=clock,
                    sleep=clock.sleep,
                    deps=deps,
                    commit=mock_commit,
                    commit_every_minutes=5,
                )

        # Should have at least one commit
        self.assertGreater(len(commits), 0)

    def test_run_respects_max_minutes(self):
        """run stops when max_minutes elapsed."""
        clock = FakeClock()

        def mock_poll():
            return {"live_games": 1, "rows_written": 1}

        deps = {"poll": mock_poll}

        with mock.patch("src.pipeline.livefeed_mlb.latest_states") as m_states:
            m_states.return_value = {"pk1": {"status": "Live"}}
            with mock.patch("src.providers.mlb.fetch_games") as m_fetch:
                m_fetch.return_value = [
                    {
                        "game_pk": "pk1",
                        "start_time_utc": "2026-09-14T21:00:00Z",
                        "status": {"abstractGameState": "Live"},
                    }
                ]
                result = live_window.run(
                    "mlb",
                    max_minutes=5,
                    clock=clock,
                    sleep=clock.sleep,
                    deps=deps,
                )

        self.assertIn("max_minutes", result["stopped_reason"])


class TestSettle(unittest.TestCase):
    """Tests for settle."""

    def test_settle_mlb_candidate_from_final(self):
        """settle grades an MLB candidate against a final state row."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create live candidates ledger
            ledger_path = Path(tmpdir) / "live_candidates_v1.jsonl"
            candidate = {
                "kind": "live_candidate",
                "recorded_utc": "2026-09-14T20:00:00Z",
                "date": "2026-09-14",
                "rule_id": "mlb_favorite_trails_after_3",
                "sport": "mlb",
                "game_id": "747101",
                "side": "home",
                "team": "Boston Red Sox",
                "bet": "Boston Red Sox moneyline",
                "price": -110,
                "books": 5,
                "state_id": "abc123",
                "observed_utc": "2026-09-14T20:00:00Z",
                "trigger": {"inning": 3},
            }

            # Write candidate with chain fields
            row = candidate.copy()
            row["hash"] = "hash0"
            row["prior_hash"] = ""
            ledger_path.write_text(json.dumps(row) + "\n")

            # Settlement
            results = {
                "747101": {"home_score": 5, "away_score": 3}
            }

            with mock.patch("src.appstate.live_ledger.LIVE_STORE", str(ledger_path)):
                result = live_window.settle("2026-09-14", results=results)

            self.assertIsNotNone(result)
            self.assertGreater(result["graded"], 0)


class TestMain(unittest.TestCase):
    """Tests for main."""

    def test_main_should_dispatch_flag(self):
        """main with --should-dispatch prints DISPATCH or HOLD."""
        with mock.patch("src.pipeline.live_window.should_dispatch") as m_dispatch:
            m_dispatch.return_value = (True, "live game")
            with mock.patch("builtins.print") as m_print:
                live_window.main(["live_window.py", "--sport", "mlb", "--should-dispatch"])
                m_print.assert_called_once()
                call_arg = m_print.call_args[0][0]
                self.assertIn("DISPATCH", call_arg)

    def test_main_should_dispatch_false(self):
        """main prints HOLD when should_dispatch returns False."""
        with mock.patch("src.pipeline.live_window.should_dispatch") as m_dispatch:
            m_dispatch.return_value = (False, "outside window")
            with mock.patch("builtins.print") as m_print:
                live_window.main(["live_window.py", "--sport", "mlb", "--should-dispatch"])
                call_arg = m_print.call_args[0][0]
                self.assertIn("HOLD", call_arg)


if __name__ == "__main__":
    unittest.main()
