"""Tests for NFL pre-game featured-board capture cadence.

These tests use fake clocks, fake games, and fake capture/budget functions
to verify the phase-tracking logic without touching the network or real files.
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.pipeline import nfl_capture


class TestDuePhases(unittest.TestCase):
    """Tests for due_phases function."""

    def test_game_71_hours_out_triggers_t72h(self):
        """A game 71h out should trigger the t72h phase."""
        now = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)
        # Game is 71 hours away
        game_start = now + timedelta(hours=71)
        games = [
            {
                "game_id": "2026_09_BUF_NYJ",
                "start_utc": game_start.isoformat().replace("+00:00", "Z"),
            }
        ]
        done = set()

        due = nfl_capture.due_phases(games, done, now)

        # Should have one due phase: t72h
        self.assertEqual(len(due), 1)
        self.assertIn(("2026_09_BUF_NYJ", "t72h"), due)

    def test_two_games_both_inside_t24h_fires_once(self):
        """Two games both inside the t24h window should both be marked due in one check."""
        now = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)
        # Game starting exactly 20 hours out opens t72h and t24h phases
        game1_start = now + timedelta(hours=20)
        game2_start = now + timedelta(hours=18)
        games = [
            {
                "game_id": "2026_09_BUF_NYJ",
                "start_utc": game1_start.isoformat().replace("+00:00", "Z"),
            },
            {
                "game_id": "2026_09_DET_GB",
                "start_utc": game2_start.isoformat().replace("+00:00", "Z"),
            },
        ]
        done = set()

        due = nfl_capture.due_phases(games, done, now)

        # Each game should have t72h and t24h due (both windows opened)
        # Total: 4 pairs (2 games × 2 phases)
        self.assertEqual(len(due), 4)
        self.assertIn(("2026_09_BUF_NYJ", "t72h"), due)
        self.assertIn(("2026_09_BUF_NYJ", "t24h"), due)
        self.assertIn(("2026_09_DET_GB", "t72h"), due)
        self.assertIn(("2026_09_DET_GB", "t24h"), due)

    def test_second_run_at_same_clock_returns_nothing_due(self):
        """When phases are already marked done, a second run should find nothing due."""
        now = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)
        game_start = now + timedelta(hours=20)
        games = [
            {
                "game_id": "2026_09_BUF_NYJ",
                "start_utc": game_start.isoformat().replace("+00:00", "Z"),
            }
        ]
        # Simulate that both t72h and t24h are already done
        # (20h out opens both phases)
        done = {("2026_09_BUF_NYJ", "t72h"), ("2026_09_BUF_NYJ", "t24h")}

        due = nfl_capture.due_phases(games, done, now)

        self.assertEqual(len(due), 0)

    def test_game_already_started_never_due(self):
        """A game that has already started should never be due for any phase."""
        now = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)
        game_start = now - timedelta(hours=1)  # Already started
        games = [
            {
                "game_id": "2026_09_BUF_NYJ",
                "start_utc": game_start.isoformat().replace("+00:00", "Z"),
            }
        ]
        done = set()

        due = nfl_capture.due_phases(games, done, now)

        self.assertEqual(len(due), 0)

    def test_phases_fire_once_each_as_clock_advances(self):
        """As the clock advances, each phase window should fire exactly once."""
        game_start = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)
        games = [
            {
                "game_id": "2026_09_BUF_NYJ",
                "start_utc": game_start.isoformat().replace("+00:00", "Z"),
            }
        ]

        captures = []
        done = set()

        # Phase 1: t72h window (72h = 4320 minutes before)
        # Window opens at: start - 4320m = start - 72h
        now1 = game_start - timedelta(minutes=4320)
        due1 = nfl_capture.due_phases(games, done, now1)
        self.assertEqual(len(due1), 1)
        self.assertIn(("2026_09_BUF_NYJ", "t72h"), due1)
        captures.append(("t72h", due1))
        done.update(due1)

        # Phase 2: t24h window (1440 minutes before)
        now2 = game_start - timedelta(minutes=1440)
        due2 = nfl_capture.due_phases(games, done, now2)
        self.assertEqual(len(due2), 1)
        self.assertIn(("2026_09_BUF_NYJ", "t24h"), due2)
        captures.append(("t24h", due2))
        done.update(due2)

        # Phase 3: t6h window (360 minutes before)
        now3 = game_start - timedelta(minutes=360)
        due3 = nfl_capture.due_phases(games, done, now3)
        self.assertEqual(len(due3), 1)
        self.assertIn(("2026_09_BUF_NYJ", "t6h"), due3)
        captures.append(("t6h", due3))
        done.update(due3)

        # Phase 4: t2h window (120 minutes before)
        now4 = game_start - timedelta(minutes=120)
        due4 = nfl_capture.due_phases(games, done, now4)
        self.assertEqual(len(due4), 1)
        self.assertIn(("2026_09_BUF_NYJ", "t2h"), due4)
        captures.append(("t2h", due4))
        done.update(due4)

        # Phase 5: t30m window (30 minutes before)
        now5 = game_start - timedelta(minutes=30)
        due5 = nfl_capture.due_phases(games, done, now5)
        self.assertEqual(len(due5), 1)
        self.assertIn(("2026_09_BUF_NYJ", "t30m"), due5)
        captures.append(("t30m", due5))
        done.update(due5)

        # Total: 5 captures
        self.assertEqual(len(captures), 5)


class TestLoadDone(unittest.TestCase):
    """Tests for load_done function."""

    def test_load_done_from_nonexistent_file_returns_empty_set(self):
        """Loading from a nonexistent file should return an empty set."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "does_not_exist.jsonl"
            done = nfl_capture.load_done(path)
            self.assertEqual(done, set())

    def test_load_done_reads_jsonl_rows_correctly(self):
        """Loading should parse JSONL rows and build a set of (game_id, phase) tuples."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "done.jsonl"
            rows = [
                {"game_id": "2026_09_BUF_NYJ", "phase": "t72h", "observed_utc": "2026-09-14T06:00:00Z"},
                {"game_id": "2026_09_DET_GB", "phase": "t24h", "observed_utc": "2026-09-14T10:00:00Z"},
            ]
            for row in rows:
                path.write_text(
                    path.read_text() + json.dumps(row) + "\n" if path.exists() else json.dumps(row) + "\n",
                    encoding="utf-8",
                )
            # Simpler way: just write the lines
            path.write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
            )

            done = nfl_capture.load_done(path)

            self.assertEqual(len(done), 2)
            self.assertIn(("2026_09_BUF_NYJ", "t72h"), done)
            self.assertIn(("2026_09_DET_GB", "t24h"), done)

    def test_load_done_skips_malformed_lines(self):
        """Malformed JSON lines should be logged and skipped."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "done.jsonl"
            content = (
                json.dumps({"game_id": "2026_09_BUF_NYJ", "phase": "t72h", "observed_utc": "2026-09-14T06:00:00Z"}) + "\n"
                + "this is not valid json\n"
                + json.dumps({"game_id": "2026_09_DET_GB", "phase": "t24h", "observed_utc": "2026-09-14T10:00:00Z"}) + "\n"
            )
            path.write_text(content, encoding="utf-8")

            done = nfl_capture.load_done(path)

            # Should have 2 valid rows, the malformed one skipped
            self.assertEqual(len(done), 2)


class TestMarkDone(unittest.TestCase):
    """Tests for mark_done function."""

    def test_mark_done_creates_file_and_appends_rows(self):
        """mark_done should create the file and append rows as JSONL."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "done.jsonl"
            now = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)
            pairs = [
                ("2026_09_BUF_NYJ", "t72h"),
                ("2026_09_DET_GB", "t24h"),
            ]

            nfl_capture.mark_done(path, pairs, now)

            self.assertTrue(path.exists())
            rows = nfl_capture.load_done(path)
            self.assertEqual(len(rows), 2)
            self.assertIn(("2026_09_BUF_NYJ", "t72h"), rows)
            self.assertIn(("2026_09_DET_GB", "t24h"), rows)

    def test_mark_done_appends_to_existing_file(self):
        """mark_done should append to an existing file without truncating."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "done.jsonl"
            now = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)

            # First write
            nfl_capture.mark_done(path, [("2026_09_BUF_NYJ", "t72h")], now)

            # Second write
            nfl_capture.mark_done(path, [("2026_09_DET_GB", "t24h")], now)

            # Both should be present
            rows = nfl_capture.load_done(path)
            self.assertEqual(len(rows), 2)

    def test_mark_done_with_empty_pairs_does_nothing(self):
        """mark_done with an empty pairs list should not write or create the file."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "done.jsonl"
            now = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)

            nfl_capture.mark_done(path, [], now)

            # File should not be created
            self.assertFalse(path.exists())


class TestRun(unittest.TestCase):
    """Tests for the run function."""

    def test_run_no_phases_due(self):
        """When no phases are due, run should return captured=False with 'no phase due'."""
        with tempfile.TemporaryDirectory() as tmp:
            done_path = Path(tmp) / "done.jsonl"
            now = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)

            # Game is far in the future, no phases due yet
            game_start = now + timedelta(days=10)
            games = [
                {
                    "game_id": "2026_09_BUF_NYJ",
                    "away": "Buffalo Bills",
                    "home": "New York Jets",
                    "start_utc": game_start.isoformat().replace("+00:00", "Z"),
                }
            ]

            def fake_capture(env=None, sport=None):
                return {"captured": 0, "events": 0}

            def fake_spend_guard(family, credits, now=None):
                from src.capture.budget import Decision
                return Decision(True, "ok")

            result = nfl_capture.run(
                now=now,
                games=games,
                capture=fake_capture,
                spend_guard=fake_spend_guard,
                done_path=done_path,
            )

            self.assertEqual(result["captured"], False)
            self.assertEqual(result["reason"], "no phase due")
            self.assertEqual(result["due"], [])

    def test_run_with_phases_due_and_guard_allows(self):
        """When phases are due and guard allows, run should capture and mark done."""
        with tempfile.TemporaryDirectory() as tmp:
            done_path = Path(tmp) / "done.jsonl"
            now = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)

            # Game is 20 hours away (triggers both t72h and t24h)
            game_start = now + timedelta(hours=20)
            games = [
                {
                    "game_id": "2026_09_BUF_NYJ",
                    "away": "Buffalo Bills",
                    "home": "New York Jets",
                    "start_utc": game_start.isoformat().replace("+00:00", "Z"),
                }
            ]

            def fake_capture(env=None, sport=None):
                return {
                    "captured": 12,
                    "events": 16,
                    "sport": "nfl",
                    "observed_utc": now.isoformat().replace("+00:00", "Z"),
                }

            def fake_spend_guard(family, credits, now=None):
                from src.capture.budget import Decision
                return Decision(True, "ok")

            result = nfl_capture.run(
                now=now,
                games=games,
                capture=fake_capture,
                spend_guard=fake_spend_guard,
                done_path=done_path,
            )

            self.assertEqual(result["captured"], True)
            self.assertEqual(result["credits"], 3)
            self.assertNotIn("reason", result)  # No reason field on success
            # Two phases due: t72h and t24h
            self.assertEqual(len(result["due"]), 2)
            self.assertIn(("2026_09_BUF_NYJ", "t72h"), result["due"])
            self.assertIn(("2026_09_BUF_NYJ", "t24h"), result["due"])
            self.assertIn("summary", result)

            # Verify done file was marked
            done = nfl_capture.load_done(done_path)
            self.assertEqual(len(done), 2)

    def test_run_with_phases_due_but_guard_refuses(self):
        """When phases are due but guard refuses, nothing should be marked done."""
        with tempfile.TemporaryDirectory() as tmp:
            done_path = Path(tmp) / "done.jsonl"
            now = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)

            game_start = now + timedelta(hours=20)
            games = [
                {
                    "game_id": "2026_09_BUF_NYJ",
                    "away": "Buffalo Bills",
                    "home": "New York Jets",
                    "start_utc": game_start.isoformat().replace("+00:00", "Z"),
                }
            ]

            def fake_capture(env=None, sport=None):
                self.fail("capture should not be called")

            def fake_spend_guard(family, credits, now=None):
                from src.capture.budget import Decision
                return Decision(False, "skipped: credit floor")

            result = nfl_capture.run(
                now=now,
                games=games,
                capture=fake_capture,
                spend_guard=fake_spend_guard,
                done_path=done_path,
            )

            self.assertEqual(result["captured"], False)
            self.assertIn("credit floor", result["reason"])
            # Two phases due: t72h and t24h (20h out)
            self.assertEqual(len(result["due"]), 2)

            # Verify done file was NOT marked
            done = nfl_capture.load_done(done_path)
            self.assertEqual(len(done), 0)

    def test_run_capture_error_does_not_mark_done(self):
        """When capture returns an error, nothing should be marked done."""
        with tempfile.TemporaryDirectory() as tmp:
            done_path = Path(tmp) / "done.jsonl"
            now = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)

            game_start = now + timedelta(hours=20)
            games = [
                {
                    "game_id": "2026_09_BUF_NYJ",
                    "away": "Buffalo Bills",
                    "home": "New York Jets",
                    "start_utc": game_start.isoformat().replace("+00:00", "Z"),
                }
            ]

            def fake_capture(env=None, sport=None):
                return {"error": "boom"}

            def fake_spend_guard(family, credits, now=None):
                from src.capture.budget import Decision
                return Decision(True, "ok")

            result = nfl_capture.run(
                now=now,
                games=games,
                capture=fake_capture,
                spend_guard=fake_spend_guard,
                done_path=done_path,
            )

            self.assertEqual(result["captured"], False)
            self.assertIn("boom", result["reason"])

            # Verify done file was NOT marked
            done = nfl_capture.load_done(done_path)
            self.assertEqual(len(done), 0)

    def test_run_game_already_started_not_captured(self):
        """A game that already started should never trigger a capture."""
        with tempfile.TemporaryDirectory() as tmp:
            done_path = Path(tmp) / "done.jsonl"
            now = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)

            # Game started 1 hour ago
            game_start = now - timedelta(hours=1)
            games = [
                {
                    "game_id": "2026_09_BUF_NYJ",
                    "away": "Buffalo Bills",
                    "home": "New York Jets",
                    "start_utc": game_start.isoformat().replace("+00:00", "Z"),
                }
            ]

            def fake_capture(env=None, sport=None):
                self.fail("capture should not be called")

            def fake_spend_guard(family, credits, now=None):
                self.fail("spend_guard should not be called")

            result = nfl_capture.run(
                now=now,
                games=games,
                capture=fake_capture,
                spend_guard=fake_spend_guard,
                done_path=done_path,
            )

            self.assertEqual(result["captured"], False)
            self.assertEqual(result["reason"], "no phase due")

    def test_run_captures_multiple_games_in_one_call(self):
        """When multiple games are due, one capture should mark all of them."""
        with tempfile.TemporaryDirectory() as tmp:
            done_path = Path(tmp) / "done.jsonl"
            now = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)

            # Two games both within phase windows (20h and 18h out both trigger t72h and t24h)
            game1_start = now + timedelta(hours=20)
            game2_start = now + timedelta(hours=18)
            games = [
                {
                    "game_id": "2026_09_BUF_NYJ",
                    "away": "Buffalo Bills",
                    "home": "New York Jets",
                    "start_utc": game1_start.isoformat().replace("+00:00", "Z"),
                },
                {
                    "game_id": "2026_09_DET_GB",
                    "away": "Detroit Lions",
                    "home": "Green Bay Packers",
                    "start_utc": game2_start.isoformat().replace("+00:00", "Z"),
                },
            ]

            capture_count = [0]

            def fake_capture(env=None, sport=None):
                capture_count[0] += 1
                return {
                    "captured": 12,
                    "events": 16,
                    "sport": "nfl",
                }

            def fake_spend_guard(family, credits, now=None):
                from src.capture.budget import Decision
                return Decision(True, "ok")

            result = nfl_capture.run(
                now=now,
                games=games,
                capture=fake_capture,
                spend_guard=fake_spend_guard,
                done_path=done_path,
            )

            # Should have called capture exactly once
            self.assertEqual(capture_count[0], 1)
            self.assertEqual(result["captured"], True)
            # Each game has t72h and t24h due: 2 games × 2 phases = 4 pairs
            self.assertEqual(len(result["due"]), 4)
            done = nfl_capture.load_done(done_path)
            self.assertEqual(len(done), 4)



class TestGameDayRefresh(unittest.TestCase):
    """The NFL card judges only a board under an hour old, so inside the six
    hours before a kickoff the board is re-bought every 25 minutes. Outside
    that window the five phases stand alone (see THE GAME-DAY WINDOW in
    src/pipeline/nfl_capture.py)."""

    KICKOFF = datetime(2026, 10, 2, 0, 15, 0, tzinfo=timezone.utc)

    def _games(self):
        return [{"game_id": "2026_04_SF_LA", "away": "49ers", "home": "Rams",
                 "start_utc": self.KICKOFF.isoformat().replace("+00:00", "Z")}]

    def _run(self, done_path, now, calls, guard_ok=True, error=None):
        def fake_capture(env=None, sport=None):
            calls.append(now)
            if error:
                return {"error": error}
            return {"captured": 800, "events": 14}

        def fake_spend_guard(family, credits, now=None):
            from src.capture.budget import Decision
            return Decision(guard_ok, "ok" if guard_ok else "floor reached")

        return nfl_capture.run(now=now, games=self._games(), capture=fake_capture,
                               spend_guard=fake_spend_guard, done_path=done_path)

    def _all_phases_done(self, done_path, at):
        nfl_capture.mark_done(done_path, [("2026_04_SF_LA", name) for name, _ in nfl_capture.PHASES], at)

    def test_one_evening_of_slots_keeps_the_board_under_an_hour_old(self):
        # Slots 13 minutes apart from 7 hours before kickoff to kickoff.
        with tempfile.TemporaryDirectory() as tmp:
            done_path = Path(tmp) / "done.jsonl"
            calls = []
            slot = self.KICKOFF - timedelta(hours=7)
            worst_age = timedelta(0)
            last = None
            while slot < self.KICKOFF:
                self._run(done_path, slot, calls)
                if calls:
                    last = calls[-1]
                if last is not None and self.KICKOFF - slot <= timedelta(hours=6):
                    worst_age = max(worst_age, slot - last)
                slot += timedelta(minutes=13)
            self.assertLess(worst_age, timedelta(minutes=60))
            # Bought far less often than once a slot (33 slots in 7 hours).
            self.assertLessEqual(len(calls), 17)
            self.assertGreaterEqual(len(calls), 12)

    def test_no_refresh_outside_the_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            done_path = Path(tmp) / "done.jsonl"
            # 10 hours out: t72h and t24h are done, t6h is not open yet.
            early = self.KICKOFF - timedelta(hours=10)
            nfl_capture.mark_done(done_path, [("2026_04_SF_LA", "t72h"), ("2026_04_SF_LA", "t24h")],
                                  early - timedelta(hours=5))
            calls = []
            result = self._run(done_path, early, calls)
            self.assertEqual(calls, [])
            self.assertEqual(result["reason"], "no phase due")

    def test_no_refresh_after_kickoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            done_path = Path(tmp) / "done.jsonl"
            self._all_phases_done(done_path, self.KICKOFF - timedelta(hours=1))
            calls = []
            result = self._run(done_path, self.KICKOFF + timedelta(minutes=20), calls)
            self.assertEqual(calls, [])
            self.assertFalse(result["captured"])

    def test_a_recent_capture_is_not_repeated(self):
        with tempfile.TemporaryDirectory() as tmp:
            done_path = Path(tmp) / "done.jsonl"
            now = self.KICKOFF - timedelta(hours=1)
            self._all_phases_done(done_path, now - timedelta(minutes=13))
            calls = []
            self.assertFalse(self._run(done_path, now, calls)["captured"])
            later = now + timedelta(minutes=13)   # 26 minutes after the last one
            result = self._run(done_path, later, calls)
            self.assertTrue(result["captured"])
            self.assertTrue(result["refresh"])
            self.assertEqual(result["credits"], nfl_capture.CREDITS_PER_CAPTURE)
            self.assertEqual(nfl_capture.last_capture_utc(done_path), later)

    def test_the_spend_guard_still_decides(self):
        with tempfile.TemporaryDirectory() as tmp:
            done_path = Path(tmp) / "done.jsonl"
            now = self.KICKOFF - timedelta(hours=1)
            self._all_phases_done(done_path, now - timedelta(minutes=40))
            calls = []
            result = self._run(done_path, now, calls, guard_ok=False)
            self.assertEqual(calls, [])
            self.assertFalse(result["captured"])
            self.assertEqual(result["credits"], 0)

    def test_a_failed_refresh_leaves_no_mark_so_the_next_slot_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            done_path = Path(tmp) / "done.jsonl"
            now = self.KICKOFF - timedelta(hours=1)
            before = now - timedelta(minutes=40)
            self._all_phases_done(done_path, before)
            calls = []
            self.assertFalse(self._run(done_path, now, calls, error="boom")["captured"])
            self.assertEqual(nfl_capture.last_capture_utc(done_path), before)

    def test_the_refresh_mark_never_reads_as_a_done_phase(self):
        with tempfile.TemporaryDirectory() as tmp:
            done_path = Path(tmp) / "done.jsonl"
            now = self.KICKOFF - timedelta(hours=5)
            nfl_capture.mark_done(done_path, [nfl_capture.REFRESH_MARK], now - timedelta(minutes=5))
            # t72h, t24h and t6h are all due and none is marked: a phase capture.
            calls = []
            result = self._run(done_path, now, calls)
            self.assertTrue(result["captured"])
            self.assertNotIn("refresh", result)
            self.assertEqual({phase for _, phase in result["due"]}, {"t72h", "t24h", "t6h"})


if __name__ == "__main__":
    unittest.main()
