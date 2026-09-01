"""The daily loop and standalone snapshot must not spend on an empty slate.

docs/SEASON_END_PLAN.md §2 found the one non-zero off-season cost: the daily
snapshot billed the whole-sport odds call every day regardless of whether MLB
had any games scheduled. Both entry points now gate on the FREE schedule
(dense.any_game_scheduled) and skip the paid capture when it is confirmed
empty -- but never when the schedule is merely unreachable, because missed
movement on a live day cannot be recovered. These tests pin that wiring.
"""
import argparse
import unittest

from src import cli
from src.pipeline import dense, snapshots


class _Tripwire(RuntimeError):
    """Raised if the paid capture is reached on a confirmed-empty slate."""


class SnapshotGateTests(unittest.TestCase):
    def setUp(self):
        self.real_any = dense.any_game_scheduled
        self.real_capture = snapshots.capture

        def tripwire(*a, **k):
            raise _Tripwire("capture() must not run when the slate is empty")

        snapshots.capture = tripwire

    def tearDown(self):
        dense.any_game_scheduled = self.real_any
        snapshots.capture = self.real_capture

    def test_standalone_snapshot_skips_paid_capture_on_empty_slate(self):
        dense.any_game_scheduled = lambda *a, **k: False
        code = cli.cmd_snapshot(argparse.Namespace())
        self.assertEqual(code, cli.EXIT_OK)  # a skip is success, not an error

    def test_capture_still_runs_when_the_schedule_is_unreachable(self):
        # None (outage) is NOT a skip: the tripwire firing proves capture ran.
        dense.any_game_scheduled = lambda *a, **k: None
        with self.assertRaises(_Tripwire):
            cli.cmd_snapshot(argparse.Namespace())

    def test_capture_still_runs_when_games_are_scheduled(self):
        dense.any_game_scheduled = lambda *a, **k: True
        with self.assertRaises(_Tripwire):
            cli.cmd_snapshot(argparse.Namespace())


if __name__ == "__main__":
    unittest.main()
