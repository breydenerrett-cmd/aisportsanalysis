"""Tests for dense snapshot capture."""

import unittest
from datetime import datetime, timezone

from src.pipeline import dense


NOW = datetime(2026, 8, 30, 15, 0, tzinfo=timezone.utc)


def _rows(*times):
    return [{"commence_time": t} for t in times]


class WindowTests(unittest.TestCase):
    def test_a_game_inside_the_window_counts(self):
        rows = _rows("2026-08-30T17:00:00Z")
        self.assertEqual(dense.games_in_window(rows, NOW), 1)

    def test_a_game_beyond_the_window_does_not(self):
        rows = _rows("2026-08-30T22:00:00Z")
        self.assertEqual(dense.games_in_window(rows, NOW), 0)

    def test_a_game_already_under_way_does_not(self):
        # In-play pricing is a different product and is never what this samples.
        rows = _rows("2026-08-30T14:00:00Z")
        self.assertEqual(dense.games_in_window(rows, NOW), 0)

    def test_a_game_starting_exactly_now_does_not(self):
        rows = _rows("2026-08-30T15:00:00Z")
        self.assertEqual(dense.games_in_window(rows, NOW), 0)

    def test_an_unparseable_start_time_is_skipped_not_counted(self):
        rows = _rows("not a timestamp", None, "2026-08-30T17:00:00Z")
        self.assertEqual(dense.games_in_window(rows, NOW), 1)

    def test_a_naive_timestamp_is_treated_as_utc(self):
        rows = _rows("2026-08-30T17:00:00")
        self.assertEqual(dense.games_in_window(rows, NOW), 1)


class CostTests(unittest.TestCase):
    def test_the_daily_estimate_multiplies_out(self):
        cost = dense.estimate_daily_credits(hours_of_baseball=11)
        self.assertEqual(cost["credits_per_hour"],
                         cost["credits_per_call"] * cost["captures_per_hour"])
        self.assertEqual(cost["credits_per_day"], cost["credits_per_hour"] * 11)
        self.assertEqual(cost["credits_per_month"], cost["credits_per_day"] * 30)


class RunTests(unittest.TestCase):
    """The guards, each of which exists to stop a spend."""

    def setUp(self):
        self.calls = []
        self.real_quota = dense.odds_provider.quota
        self.real_status = dense.odds_provider.status
        self.real_capture = dense.snapshots.capture
        self.real_upcoming = dense._upcoming
        dense.odds_provider.status = lambda env=None: {"configured": True}
        dense.snapshots.capture = self._capture

    def tearDown(self):
        dense.odds_provider.quota = self.real_quota
        dense.odds_provider.status = self.real_status
        dense.snapshots.capture = self.real_capture
        dense._upcoming = self.real_upcoming

    def _capture(self, env=None):
        self.calls.append("capture")
        return {"captured": 30, "events": 15, "configured": True}

    def test_nothing_is_spent_below_the_credit_floor(self):
        dense.odds_provider.quota = lambda env=None: {"remaining": 100}
        dense._upcoming = lambda now=None, timeout=20: _rows("2026-08-30T17:00:00Z")
        result = dense.run(credit_floor=5000, now=NOW, sleep=None)
        self.assertEqual(result["skipped"], "credit floor")
        self.assertEqual(self.calls, [])

    def test_nothing_is_spent_when_no_game_is_approaching(self):
        dense.odds_provider.quota = lambda env=None: {"remaining": 50000}
        dense._upcoming = lambda now=None, timeout=20: _rows("2026-08-30T23:00:00Z")
        result = dense.run(now=NOW, sleep=None)
        self.assertEqual(result["captures"], 0)
        self.assertEqual(result["stopped_early"], "no game inside the window")
        self.assertEqual(self.calls, [])

    def test_nothing_is_spent_when_the_schedule_is_unreachable(self):
        # A schedule outage must not become a reason to spend blindly.
        dense.odds_provider.quota = lambda env=None: {"remaining": 50000}
        dense._upcoming = lambda now=None, timeout=20: None
        result = dense.run(now=NOW, sleep=None)
        self.assertEqual(result["stopped_early"], "schedule unreachable")
        self.assertEqual(self.calls, [])

    def test_nothing_is_spent_when_the_quota_cannot_be_read(self):
        def boom(env=None):
            raise dense.odds_provider.OddsProviderError("down")
        dense.odds_provider.quota = boom
        dense._upcoming = lambda now=None, timeout=20: _rows("2026-08-30T17:00:00Z")
        result = dense.run(now=NOW, sleep=None)
        self.assertEqual(result["skipped"], "quota unreadable")
        self.assertEqual(self.calls, [])

    def test_a_full_run_captures_the_requested_number_of_times(self):
        dense.odds_provider.quota = lambda env=None: {"remaining": 50000}
        dense._upcoming = lambda now=None, timeout=20: _rows("2026-08-30T17:00:00Z")
        result = dense.run(captures=4, now=NOW, sleep=None)
        self.assertEqual(result["captures"], 4)
        self.assertEqual(result["observations"], 120)
        self.assertIsNone(result["stopped_early"])
        self.assertEqual(len(self.calls), 4)

    def test_the_window_is_rechecked_before_every_capture(self):
        """A run that outlives its window stops, rather than buying in-play prices."""
        dense.odds_provider.quota = lambda env=None: {"remaining": 50000}
        seen = {"n": 0}

        def shrinking(now=None, timeout=20):
            seen["n"] += 1
            # The game is gone from the window by the third check.
            return (_rows("2026-08-30T17:00:00Z") if seen["n"] < 3
                    else _rows("2026-08-30T14:00:00Z"))

        dense._upcoming = shrinking
        result = dense.run(captures=4, now=NOW, sleep=None)
        self.assertEqual(result["captures"], 2)
        self.assertEqual(result["stopped_early"], "no game inside the window")


if __name__ == "__main__":
    unittest.main()
