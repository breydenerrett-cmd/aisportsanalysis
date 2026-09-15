"""Multisport quiet-hours calendar tests.

Tests for src/sports/calendar.py: verdict(now), upcoming_starts(now), and the
CLI entry point that the capture chain calls.
"""

import datetime as dt
import unittest
from dataclasses import replace
from unittest.mock import patch

import src.sports
from src.sports.calendar import upcoming_starts, next_start_within, verdict, main


def _fake_spec(key, schedule_fn=None):
    """Create a fake SportSpec for testing."""
    return replace(src.sports.spec("mlb"), key=key, schedule_fn=schedule_fn)


class UpcomingStarts(unittest.TestCase):
    """Test upcoming_starts() collects and filters game starts."""

    def test_mlb_game_five_hours_out_is_included(self):
        """A game within horizon is returned."""
        now = dt.datetime(2026, 9, 14, 15, 0, tzinfo=dt.timezone.utc)

        def mlb_schedule(date_str):
            return [{
                "game_id": "1",
                "away": "BOS",
                "home": "NYY",
                "start_utc": "2026-09-14T20:00:00Z",
            }]

        mlb_spec = _fake_spec("mlb", schedule_fn=mlb_schedule)
        starts = upcoming_starts(now, horizon_hours=26, specs=[mlb_spec])
        self.assertEqual(starts, ["2026-09-14T20:00:00Z"])

    def test_nfl_game_is_collected_alongside_mlb(self):
        """Multiple sports' games are de-duplicated and sorted."""
        now = dt.datetime(2026, 9, 14, 15, 0, tzinfo=dt.timezone.utc)

        def mlb_schedule(date_str):
            if date_str == "2026-09-14":
                return [{
                    "game_id": "1",
                    "away": "BOS",
                    "home": "NYY",
                    "start_utc": "2026-09-14T20:00:00Z",
                }]
            return []

        def nfl_schedule(date_str):
            if date_str == "2026-09-14":
                return [{
                    "game_id": "2",
                    "away": "BUF",
                    "home": "DET",
                    "start_utc": "2026-09-14T17:00:00Z",
                }]
            return []

        mlb_spec = _fake_spec("mlb", schedule_fn=mlb_schedule)
        nfl_spec = _fake_spec("nfl", schedule_fn=nfl_schedule)
        starts = upcoming_starts(now, horizon_hours=26, specs=[mlb_spec, nfl_spec])
        self.assertEqual(starts, ["2026-09-14T17:00:00Z", "2026-09-14T20:00:00Z"])

    def test_game_outside_horizon_is_excluded(self):
        """A game more than horizon hours away is not returned."""
        now = dt.datetime(2026, 9, 14, 15, 0, tzinfo=dt.timezone.utc)

        def mlb_schedule(date_str):
            return [{
                "game_id": "1",
                "away": "BOS",
                "home": "NYY",
                "start_utc": "2026-09-16T20:00:00Z",  # 53 hours out
            }]

        mlb_spec = _fake_spec("mlb", schedule_fn=mlb_schedule)
        starts = upcoming_starts(now, horizon_hours=26, specs=[mlb_spec])
        self.assertEqual(starts, [])

    def test_game_at_now_or_before_is_excluded(self):
        """A game at or before now is not returned."""
        now = dt.datetime(2026, 9, 14, 15, 0, tzinfo=dt.timezone.utc)

        def mlb_schedule(date_str):
            return [{
                "game_id": "1",
                "away": "BOS",
                "home": "NYY",
                "start_utc": "2026-09-14T15:00:00Z",  # exactly now
            }]

        mlb_spec = _fake_spec("mlb", schedule_fn=mlb_schedule)
        starts = upcoming_starts(now, horizon_hours=26, specs=[mlb_spec])
        self.assertEqual(starts, [])

    def test_duplicates_are_removed(self):
        """The same start time from two sports appears once."""
        now = dt.datetime(2026, 9, 14, 15, 0, tzinfo=dt.timezone.utc)

        def sched1(date_str):
            return [{
                "game_id": "1",
                "away": "A",
                "home": "B",
                "start_utc": "2026-09-14T20:00:00Z",
            }]

        def sched2(date_str):
            return [{
                "game_id": "2",
                "away": "C",
                "home": "D",
                "start_utc": "2026-09-14T20:00:00Z",
            }]

        spec1 = _fake_spec("sport1", schedule_fn=sched1)
        spec2 = _fake_spec("sport2", schedule_fn=sched2)
        starts = upcoming_starts(now, horizon_hours=26, specs=[spec1, spec2])
        self.assertEqual(starts, ["2026-09-14T20:00:00Z"])

    def test_a_spec_whose_schedule_fn_raises_is_skipped(self):
        """An exception in one sport's schedule_fn is caught and doesn't stop others."""
        now = dt.datetime(2026, 9, 14, 15, 0, tzinfo=dt.timezone.utc)

        def raises_fn(date_str):
            raise RuntimeError("network error")

        def mlb_schedule(date_str):
            return [{
                "game_id": "1",
                "away": "BOS",
                "home": "NYY",
                "start_utc": "2026-09-14T20:00:00Z",
            }]

        broken_spec = _fake_spec("broken", schedule_fn=raises_fn)
        mlb_spec = _fake_spec("mlb", schedule_fn=mlb_schedule)
        starts = upcoming_starts(now, horizon_hours=26, specs=[broken_spec, mlb_spec])
        # Only MLB's game is returned; the broken spec is silently skipped.
        self.assertEqual(starts, ["2026-09-14T20:00:00Z"])

    def test_both_empty_specs_return_empty_list(self):
        """Two sports with no games return an empty list."""
        now = dt.datetime(2026, 9, 14, 15, 0, tzinfo=dt.timezone.utc)

        def empty_schedule(date_str):
            return []

        mlb_spec = _fake_spec("mlb", schedule_fn=empty_schedule)
        nfl_spec = _fake_spec("nfl", schedule_fn=empty_schedule)
        starts = upcoming_starts(now, horizon_hours=26, specs=[mlb_spec, nfl_spec])
        self.assertEqual(starts, [])


class Verdict(unittest.TestCase):
    """Test verdict() returns the capture chain's verdict string."""

    def test_quiet_when_no_game_starts_within_horizon(self):
        """QUIET when both sports have no upcoming games."""
        now = dt.datetime(2026, 9, 14, 15, 0, tzinfo=dt.timezone.utc)

        def empty_schedule(date_str):
            return []

        mlb_spec = _fake_spec("mlb", schedule_fn=empty_schedule)
        nfl_spec = _fake_spec("nfl", schedule_fn=empty_schedule)
        result = verdict(now, 26, specs=[mlb_spec, nfl_spec])
        self.assertEqual(result, "QUIET")

    def test_active_with_nfl_when_mlb_empty(self):
        """ACTIVE when only one sport has a game."""
        now = dt.datetime(2026, 9, 14, 15, 0, tzinfo=dt.timezone.utc)

        def empty_schedule(date_str):
            return []

        def nfl_schedule(date_str):
            if date_str == "2026-09-14":
                return [{
                    "game_id": "1",
                    "away": "BUF",
                    "home": "DET",
                    "start_utc": "2026-09-14T20:00:00Z",
                }]
            return []

        mlb_spec = _fake_spec("mlb", schedule_fn=empty_schedule)
        nfl_spec = _fake_spec("nfl", schedule_fn=nfl_schedule)
        result = verdict(now, 26, specs=[mlb_spec, nfl_spec])
        self.assertTrue(result.startswith("ACTIVE next start 2026-09-14T20:00:00Z"))

    def test_active_shows_earliest_start_across_all_sports(self):
        """ACTIVE shows the earliest start when multiple sports have games."""
        now = dt.datetime(2026, 9, 14, 15, 0, tzinfo=dt.timezone.utc)

        def mlb_schedule(date_str):
            if date_str == "2026-09-14":
                return [{
                    "game_id": "1",
                    "away": "BOS",
                    "home": "NYY",
                    "start_utc": "2026-09-14T20:00:00Z",
                }]
            return []

        def nfl_schedule(date_str):
            if date_str == "2026-09-14":
                return [{
                    "game_id": "2",
                    "away": "BUF",
                    "home": "DET",
                    "start_utc": "2026-09-14T17:00:00Z",
                }]
            return []

        mlb_spec = _fake_spec("mlb", schedule_fn=mlb_schedule)
        nfl_spec = _fake_spec("nfl", schedule_fn=nfl_schedule)
        result = verdict(now, 26, specs=[mlb_spec, nfl_spec])
        self.assertEqual(result, "ACTIVE next start 2026-09-14T17:00:00Z")


class NextStartWithin(unittest.TestCase):
    """Test next_start_within() returns the earliest start or None."""

    def test_returns_first_start_when_games_exist(self):
        """Returns the earliest start time when games exist."""
        now = dt.datetime(2026, 9, 14, 15, 0, tzinfo=dt.timezone.utc)

        def schedule_fn(date_str):
            if date_str == "2026-09-14":
                return [{
                    "game_id": "1",
                    "away": "A",
                    "home": "B",
                    "start_utc": "2026-09-14T20:00:00Z",
                }, {
                    "game_id": "2",
                    "away": "C",
                    "home": "D",
                    "start_utc": "2026-09-14T22:00:00Z",
                }]
            return []

        spec1 = _fake_spec("sport1", schedule_fn=schedule_fn)
        start = next_start_within(now, 26, specs=[spec1])
        self.assertEqual(start, "2026-09-14T20:00:00Z")

    def test_returns_none_when_no_games(self):
        """Returns None when no games exist in horizon."""
        now = dt.datetime(2026, 9, 14, 15, 0, tzinfo=dt.timezone.utc)

        def schedule_fn(date_str):
            return []

        spec1 = _fake_spec("sport1", schedule_fn=schedule_fn)
        start = next_start_within(now, 26, specs=[spec1])
        self.assertIsNone(start)


class CLIEntry(unittest.TestCase):
    """Test the main() CLI entry point."""

    def test_main_prints_quiet_for_empty_schedule(self):
        """main() prints QUIET when no games exist."""
        now = dt.datetime(2026, 9, 14, 15, 0, tzinfo=dt.timezone.utc)

        def schedule_fn(date_str):
            return []

        spec1 = _fake_spec("sport1", schedule_fn=schedule_fn)

        with patch("src.sports.keys", return_value=["sport1"]):
            with patch("src.sports.spec", return_value=spec1):
                import io
                import sys
                out = io.StringIO()
                sys.stdout = out
                try:
                    main(argv=["--horizon", "26"], env={}, now=now)
                finally:
                    sys.stdout = sys.__stdout__
                self.assertEqual(out.getvalue().strip(), "QUIET")

    def test_main_uses_chain_first_pitches_override(self):
        """main() uses CHAIN_FIRST_PITCHES env var to override schedule fetch."""
        now = dt.datetime(2026, 9, 14, 15, 0, tzinfo=dt.timezone.utc)

        import io
        import sys
        out = io.StringIO()
        sys.stdout = out
        try:
            main(argv=["--horizon", "26"],
                 env={"CHAIN_FIRST_PITCHES": "2026-09-14T20:00:00Z 2026-09-15T19:00:00Z"},
                 now=now)
        finally:
            sys.stdout = sys.__stdout__

        result = out.getvalue().strip()
        self.assertTrue(result.startswith("ACTIVE next start 2026-09-14T20:00:00Z"))

    def test_main_with_override_outside_horizon_prints_quiet(self):
        """main() respects horizon even when override is provided."""
        now = dt.datetime(2026, 9, 14, 15, 0, tzinfo=dt.timezone.utc)

        import io
        import sys
        out = io.StringIO()
        sys.stdout = out
        try:
            main(argv=["--horizon", "26"],
                 env={"CHAIN_FIRST_PITCHES": "2026-09-16T20:00:00Z"},  # 53h out
                 now=now)
        finally:
            sys.stdout = sys.__stdout__

        result = out.getvalue().strip()
        self.assertEqual(result, "QUIET")

    def test_main_sorts_override_times_and_returns_earliest(self):
        """main() with override returns the earliest time within horizon."""
        now = dt.datetime(2026, 9, 14, 15, 0, tzinfo=dt.timezone.utc)

        import io
        import sys
        out = io.StringIO()
        sys.stdout = out
        try:
            # Times given out of order
            main(argv=["--horizon", "26"],
                 env={"CHAIN_FIRST_PITCHES": "2026-09-14T22:00:00Z 2026-09-14T17:00:00Z"},
                 now=now)
        finally:
            sys.stdout = sys.__stdout__

        result = out.getvalue().strip()
        self.assertTrue(result.startswith("ACTIVE next start 2026-09-14T17:00:00Z"))


if __name__ == "__main__":
    unittest.main()
