"""Tests for src.pipeline.livefeed_nfl."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, MagicMock

from src.pipeline import livefeed_nfl


class TestInWindow(unittest.TestCase):
    """Test in_window() for the 2026 NFL broadcast windows."""

    def test_sunday_13_00_et_is_true(self):
        """Sunday 17:00 UTC = 13:00 ET, should be True."""
        # 2026-09-13 is a Sunday
        # 17:00 UTC = 13:00 EDT (UTC-4)
        now = datetime(2026, 9, 13, 17, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(livefeed_nfl.in_window(now))

    def test_sunday_23_00_et_is_true(self):
        """Sunday 23:00 ET, should be True."""
        # 2026-09-13 is a Sunday
        # 03:00 UTC (next day) = 23:00 EDT
        now = datetime(2026, 9, 14, 3, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(livefeed_nfl.in_window(now))

    def test_sunday_12_00_et_is_true(self):
        """Sunday 12:00 ET (start of window), should be True."""
        # 2026-09-13 is a Sunday
        # 16:00 UTC = 12:00 EDT
        now = datetime(2026, 9, 13, 16, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(livefeed_nfl.in_window(now))

    def test_sunday_11_59_et_is_false(self):
        """Sunday 11:59 ET (before window), should be False."""
        # 2026-09-13 is a Sunday
        # 15:59 UTC = 11:59 EDT
        now = datetime(2026, 9, 13, 15, 59, 0, tzinfo=timezone.utc)
        self.assertFalse(livefeed_nfl.in_window(now))

    def test_tuesday_is_false(self):
        """Tuesday anytime, should be False."""
        # 2026-09-15 is a Tuesday
        now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
        self.assertFalse(livefeed_nfl.in_window(now))

    def test_thursday_18_00_et_is_false(self):
        """Thursday 18:00 ET (before window), should be False."""
        # 2026-09-10 is a Thursday
        # 22:00 UTC = 18:00 EDT
        now = datetime(2026, 9, 10, 22, 0, 0, tzinfo=timezone.utc)
        self.assertFalse(livefeed_nfl.in_window(now))

    def test_thursday_19_00_et_is_true(self):
        """Thursday 19:00 ET (start of window), should be True."""
        # 2026-09-10 is a Thursday
        # 23:00 UTC = 19:00 EDT
        now = datetime(2026, 9, 10, 23, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(livefeed_nfl.in_window(now))

    def test_thursday_23_30_et_is_true(self):
        """Thursday 23:30 ET, should be True."""
        # 2026-09-10 is a Thursday
        # 03:30 UTC (next day) = 23:30 EDT
        now = datetime(2026, 9, 11, 3, 30, 0, tzinfo=timezone.utc)
        self.assertTrue(livefeed_nfl.in_window(now))

    def test_monday_19_00_et_is_true(self):
        """Monday 19:00 ET (start of window), should be True."""
        # 2026-09-14 is a Monday
        # 23:00 UTC = 19:00 EDT
        now = datetime(2026, 9, 14, 23, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(livefeed_nfl.in_window(now))

    def test_monday_23_59_et_is_true(self):
        """Monday 23:59 ET, should be True."""
        # 2026-09-14 is a Monday
        now = datetime(2026, 9, 15, 3, 59, 0, tzinfo=timezone.utc)
        self.assertTrue(livefeed_nfl.in_window(now))

    def test_wednesday_is_false(self):
        """Wednesday anytime, should be False."""
        # 2026-09-16 is a Wednesday
        now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
        self.assertFalse(livefeed_nfl.in_window(now))


class TestPoll(unittest.TestCase):
    """Test poll() with injected dependencies and temporary directories."""

    def setUp(self):
        """Create temporary directory for live data."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.live_dir = self.temp_dir.name

    def tearDown(self):
        """Clean up temporary directory."""
        self.temp_dir.cleanup()

    def _make_clock(self, dt):
        """Create a mock clock that returns a fixed datetime."""
        return lambda: dt

    def _make_spend_guard_allowed(self):
        """Create a spend guard that allows spending."""
        from src.capture.budget import Decision
        return lambda family, est_credits, **kwargs: Decision(True, "ok")

    def _make_spend_guard_refused(self):
        """Create a spend guard that refuses spending."""
        from src.capture.budget import Decision
        return lambda family, est_credits, **kwargs: Decision(False, "test refuse")

    def _make_fetch_scores(self, events):
        """Create a fetch_scores function that returns fixed events."""
        return lambda sport=None, env=None: events

    def test_outside_window_without_force_skipped(self):
        """Outside broadcast window without force -> skipped, fetch not called."""
        # Tuesday, should be outside window
        now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)

        fetch_called = []
        def fetch_scores(sport=None, env=None):
            fetch_called.append(True)
            return []

        result = livefeed_nfl.poll(
            live_dir=self.live_dir,
            clock=self._make_clock(now),
            fetch_scores=fetch_scores,
            spend_guard=self._make_spend_guard_allowed(),
            force=False
        )

        self.assertIn("skipped", result)
        self.assertEqual(result["skipped"], "outside window")
        self.assertEqual(len(fetch_called), 0)

    def test_force_overrides_window(self):
        """With force=True, should poll even outside window."""
        # Tuesday, outside window
        now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)

        events = [
            {
                "id": "evt1",
                "home_team": "NY Giants",
                "away_team": "Philadelphia Eagles",
                "commence_time": "2026-09-20T13:00:00Z",
                "completed": False,
                "scores": None,
                "last_update": "2026-09-15T12:00:00Z",
            }
        ]

        result = livefeed_nfl.poll(
            live_dir=self.live_dir,
            clock=self._make_clock(now),
            fetch_scores=self._make_fetch_scores(events),
            spend_guard=self._make_spend_guard_allowed(),
            force=True
        )

        self.assertNotIn("skipped", result)
        self.assertEqual(result["events"], 1)

    def test_spend_guard_refused_skipped(self):
        """Spend guard refuses -> skipped, fetch not called."""
        # Inside window
        now = datetime(2026, 9, 13, 17, 0, 0, tzinfo=timezone.utc)  # Sunday 13:00 ET

        fetch_called = []
        def fetch_scores(sport=None, env=None):
            fetch_called.append(True)
            return []

        result = livefeed_nfl.poll(
            live_dir=self.live_dir,
            clock=self._make_clock(now),
            fetch_scores=fetch_scores,
            spend_guard=self._make_spend_guard_refused(),
        )

        self.assertIn("skipped", result)
        self.assertIn("test refuse", result["skipped"])
        self.assertEqual(len(fetch_called), 0)

    def test_three_event_scenario(self):
        """Test with three events: in-play, not started, completed."""
        now = datetime(2026, 9, 13, 19, 0, 0, tzinfo=timezone.utc)  # Sunday 15:00 ET

        events = [
            {
                "id": "evt_inplay",
                "home_team": "NY Giants",
                "away_team": "Philadelphia Eagles",
                "commence_time": "2026-09-13T18:00:00Z",  # Already started
                "completed": False,
                "scores": [
                    {"name": "NY Giants", "score": "7"},
                    {"name": "Philadelphia Eagles", "score": "3"},
                ],
                "last_update": "2026-09-13T19:00:00Z",
            },
            {
                "id": "evt_future",
                "home_team": "Dallas Cowboys",
                "away_team": "Washington Commanders",
                "commence_time": "2026-09-14T00:30:00Z",  # Tomorrow night
                "completed": False,
                "scores": None,
                "last_update": "2026-09-13T19:00:00Z",
            },
            {
                "id": "evt_completed",
                "home_team": "Green Bay Packers",
                "away_team": "Detroit Lions",
                "commence_time": "2026-09-10T23:00:00Z",  # Thursday night (past)
                "completed": True,
                "scores": [
                    {"name": "Green Bay Packers", "score": "24"},
                    {"name": "Detroit Lions", "score": "21"},
                ],
                "last_update": "2026-09-11T00:30:00Z",
            },
        ]

        record_credit_calls = []
        def record_credit(remaining, used_last, caller, **kwargs):
            record_credit_calls.append((remaining, used_last, caller))
            return True

        result = livefeed_nfl.poll(
            live_dir=self.live_dir,
            clock=self._make_clock(now),
            fetch_scores=self._make_fetch_scores(events),
            spend_guard=self._make_spend_guard_allowed(),
            record_credit=record_credit,
            quota=lambda env=None: {"remaining": 50000, "used_last": 1},
        )

        self.assertEqual(result["events"], 3)
        self.assertEqual(result["in_play"], 1)  # Only in_play event
        # Should write: in-play event + completed event (first time)
        self.assertEqual(result["rows_written"], 2)
        self.assertEqual(result["finals_written"], 1)
        self.assertEqual(len(result["errors"]), 0)

        # Verify credit recording
        self.assertEqual(len(record_credit_calls), 1)
        self.assertEqual(record_credit_calls[0][2], livefeed_nfl.CALLER)

        # Verify written rows
        date_str = "2026-09-13"
        states = livefeed_nfl.latest_states(date_str, live_dir=self.live_dir)

        # Should have evt_inplay and evt_completed
        self.assertIn("evt_inplay", states)
        self.assertIn("evt_completed", states)
        self.assertNotIn("evt_future", states)

        # Check scores are parsed as integers
        self.assertEqual(states["evt_inplay"]["home_score"], 7)
        self.assertEqual(states["evt_inplay"]["away_score"], 3)
        self.assertTrue(states["evt_inplay"]["in_play"])

        self.assertEqual(states["evt_completed"]["home_score"], 24)
        self.assertEqual(states["evt_completed"]["away_score"], 21)
        self.assertTrue(states["evt_completed"]["completed"])

    def test_second_poll_idempotent(self):
        """Second poll writes in-play game again, final game not again."""
        now1 = datetime(2026, 9, 13, 19, 0, 0, tzinfo=timezone.utc)
        now2 = datetime(2026, 9, 13, 20, 0, 0, tzinfo=timezone.utc)

        events = [
            {
                "id": "evt_inplay",
                "home_team": "NY Giants",
                "away_team": "Philadelphia Eagles",
                "commence_time": "2026-09-13T18:00:00Z",
                "completed": False,
                "scores": [
                    {"name": "NY Giants", "score": "7"},
                    {"name": "Philadelphia Eagles", "score": "3"},
                ],
                "last_update": "2026-09-13T19:00:00Z",
            },
            {
                "id": "evt_completed",
                "home_team": "Green Bay Packers",
                "away_team": "Detroit Lions",
                "commence_time": "2026-09-10T23:00:00Z",
                "completed": True,
                "scores": [
                    {"name": "Green Bay Packers", "score": "24"},
                    {"name": "Detroit Lions", "score": "21"},
                ],
                "last_update": "2026-09-11T00:30:00Z",
            },
        ]

        # First poll
        result1 = livefeed_nfl.poll(
            live_dir=self.live_dir,
            clock=self._make_clock(now1),
            fetch_scores=self._make_fetch_scores(events),
            spend_guard=self._make_spend_guard_allowed(),
        )

        self.assertEqual(result1["rows_written"], 2)

        # Second poll (same time window, same events)
        result2 = livefeed_nfl.poll(
            live_dir=self.live_dir,
            clock=self._make_clock(now2),
            fetch_scores=self._make_fetch_scores(events),
            spend_guard=self._make_spend_guard_allowed(),
        )

        # Second poll should write in-play again, but not the already-completed event
        self.assertEqual(result2["rows_written"], 1)  # Only in-play
        self.assertEqual(result2["finals_written"], 0)  # Completed already written

        # Verify state file has both rows for in-play (one per poll) and one for completed
        date_str = "2026-09-13"
        rows = livefeed_nfl.read_states(date_str, live_dir=self.live_dir)

        # Count rows per event
        evt_inplay_rows = [r for r in rows if r.get("event_id") == "evt_inplay"]
        evt_completed_rows = [r for r in rows if r.get("event_id") == "evt_completed"]

        self.assertEqual(len(evt_inplay_rows), 2)  # Written twice
        self.assertEqual(len(evt_completed_rows), 1)  # Written once

    def test_error_in_event_processing(self):
        """Errors in event processing are reported, don't stop poll."""
        now = datetime(2026, 9, 13, 19, 0, 0, tzinfo=timezone.utc)

        events = [
            {
                # Missing id - should error
                "home_team": "NY Giants",
                "away_team": "Philadelphia Eagles",
                "commence_time": "2026-09-13T18:00:00Z",
                "completed": False,
                "scores": None,
                "last_update": "2026-09-13T19:00:00Z",
            },
            {
                "id": "evt_good",
                "home_team": "Dallas Cowboys",
                "away_team": "Washington Commanders",
                "commence_time": "2026-09-13T18:00:00Z",  # Already started (in-play)
                "completed": False,
                "scores": [
                    {"name": "Dallas Cowboys", "score": "10"},
                    {"name": "Washington Commanders", "score": "7"},
                ],
                "last_update": "2026-09-13T19:00:00Z",
            },
        ]

        result = livefeed_nfl.poll(
            live_dir=self.live_dir,
            clock=self._make_clock(now),
            fetch_scores=self._make_fetch_scores(events),
            spend_guard=self._make_spend_guard_allowed(),
        )

        # Should have written the in-play event
        self.assertEqual(result["events"], 2)
        self.assertGreater(result["rows_written"], 0)

    def test_fetch_scores_error_reported(self):
        """fetch_scores error is reported in errors field."""
        now = datetime(2026, 9, 13, 19, 0, 0, tzinfo=timezone.utc)

        def fetch_scores_error(sport=None, env=None):
            raise RuntimeError("API error")

        result = livefeed_nfl.poll(
            live_dir=self.live_dir,
            clock=self._make_clock(now),
            fetch_scores=fetch_scores_error,
            spend_guard=self._make_spend_guard_allowed(),
        )

        # Should report error but continue
        self.assertIn("errors", result)
        self.assertGreater(len(result["errors"]), 0)
        self.assertEqual(result["rows_written"], 0)

    def test_none_scores_handled(self):
        """Events with null scores are handled correctly."""
        now = datetime(2026, 9, 13, 19, 0, 0, tzinfo=timezone.utc)

        events = [
            {
                "id": "evt_no_scores",
                "home_team": "NY Giants",
                "away_team": "Philadelphia Eagles",
                "commence_time": "2026-09-20T18:00:00Z",  # Future
                "completed": False,
                "scores": None,
                "last_update": "2026-09-13T19:00:00Z",
            },
        ]

        result = livefeed_nfl.poll(
            live_dir=self.live_dir,
            clock=self._make_clock(now),
            fetch_scores=self._make_fetch_scores(events),
            spend_guard=self._make_spend_guard_allowed(),
        )

        # Future game should not be written
        self.assertEqual(result["rows_written"], 0)
        self.assertEqual(result["events"], 1)

    def test_credit_logging_optional(self):
        """Poll works without credit logging (lazy imports fail gracefully)."""
        now = datetime(2026, 9, 13, 19, 0, 0, tzinfo=timezone.utc)

        events = [
            {
                "id": "evt1",
                "home_team": "NY Giants",
                "away_team": "Philadelphia Eagles",
                "commence_time": "2026-09-13T18:00:00Z",
                "completed": False,
                "scores": [
                    {"name": "NY Giants", "score": "7"},
                    {"name": "Philadelphia Eagles", "score": "3"},
                ],
                "last_update": "2026-09-13T19:00:00Z",
            },
        ]

        # No quota or record_credit injected: the lazy defaults are used.
        # Those defaults are the REAL provider and the REAL credit log, so
        # both are patched here -- the first version of this test wrote a
        # row into data/processed/credit_log.jsonl on every run.
        from unittest import mock

        with mock.patch("src.providers.odds.quota",
                        side_effect=RuntimeError("no network in tests")), \
                mock.patch("src.pipeline.creditlog.log") as logged:
            result = livefeed_nfl.poll(
                live_dir=self.live_dir,
                clock=self._make_clock(now),
                fetch_scores=self._make_fetch_scores(events),
                spend_guard=self._make_spend_guard_allowed(),
            )

        # Should still work, and the quota failure means nothing was logged
        # to the real store either.
        self.assertGreater(result["rows_written"], 0)
        self.assertFalse(logged.called)


class TestReadStates(unittest.TestCase):
    """Test read_states and latest_states functions."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.live_dir = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_read_states_empty_file(self):
        """read_states on non-existent file returns empty list."""
        result = livefeed_nfl.read_states("2026-09-13", live_dir=self.live_dir)
        self.assertEqual(result, [])

    def test_latest_states_empty_file(self):
        """latest_states on non-existent file returns empty dict."""
        result = livefeed_nfl.latest_states("2026-09-13", live_dir=self.live_dir)
        self.assertEqual(result, {})

    def test_read_states_with_rows(self):
        """read_states reads all rows from file."""
        date = "2026-09-13"
        live_dir_path = Path(self.live_dir)
        store_path = live_dir_path / f"{date}.jsonl"

        live_dir_path.mkdir(parents=True, exist_ok=True)
        rows = [
            {"event_id": "evt1", "home_score": 7, "away_score": 3},
            {"event_id": "evt2", "home_score": None, "away_score": None},
        ]
        with store_path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")

        result = livefeed_nfl.read_states(date, live_dir=self.live_dir)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["event_id"], "evt1")
        self.assertEqual(result[1]["event_id"], "evt2")

    def test_latest_states_returns_newest_per_event(self):
        """latest_states returns only the newest row per event_id."""
        date = "2026-09-13"
        live_dir_path = Path(self.live_dir)
        store_path = live_dir_path / f"{date}.jsonl"

        live_dir_path.mkdir(parents=True, exist_ok=True)
        rows = [
            {"event_id": "evt1", "home_score": 3, "away_score": 0, "ts": "1"},
            {"event_id": "evt1", "home_score": 7, "away_score": 3, "ts": "2"},
            {"event_id": "evt2", "home_score": 10, "away_score": 7, "ts": "3"},
        ]
        with store_path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")

        result = livefeed_nfl.latest_states(date, live_dir=self.live_dir)
        self.assertEqual(len(result), 2)
        self.assertEqual(result["evt1"]["ts"], "2")  # Latest for evt1
        self.assertEqual(result["evt2"]["ts"], "3")  # Latest for evt2

    def test_read_states_skips_corrupt_lines(self):
        """read_states skips corrupt JSON lines."""
        date = "2026-09-13"
        live_dir_path = Path(self.live_dir)
        store_path = live_dir_path / f"{date}.jsonl"

        live_dir_path.mkdir(parents=True, exist_ok=True)
        with store_path.open("w", encoding="utf-8") as f:
            f.write(json.dumps({"event_id": "evt1"}) + "\n")
            f.write("this is not json\n")
            f.write(json.dumps({"event_id": "evt2"}) + "\n")

        result = livefeed_nfl.read_states(date, live_dir=self.live_dir)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["event_id"], "evt1")
        self.assertEqual(result[1]["event_id"], "evt2")


if __name__ == "__main__":
    unittest.main()
