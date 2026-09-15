"""Tests for in-play odds capture (event-driven, budget-constrained)."""

import json
import tempfile
import unittest
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.pipeline import live_odds


@dataclass(frozen=True)
class Decision:
    """Minimal Decision-like object for testing."""
    allowed: bool
    reason: str


class TestShouldCapture(unittest.TestCase):
    """Test the pure state-change detector."""

    def test_first_observation(self):
        """First observation always triggers capture."""
        new = {"sport": "mlb", "status": "in_progress", "inning": 1, "half": "top"}
        allowed, reason = live_odds.should_capture(None, new)
        self.assertTrue(allowed)
        self.assertEqual(reason, "first observation")

    def test_mlb_final_status(self):
        """Final game status stops capture."""
        prev = {"sport": "mlb", "status": "in_progress", "inning": 9}
        new = {"sport": "mlb", "status": "final", "inning": 9}
        allowed, reason = live_odds.should_capture(prev, new)
        self.assertFalse(allowed)
        self.assertEqual(reason, "final")

    def test_mlb_score_change(self):
        """MLB score change triggers capture."""
        prev = {"sport": "mlb", "home_runs": 0, "away_runs": 0, "inning": 1}
        new = {"sport": "mlb", "home_runs": 1, "away_runs": 0, "inning": 1}
        allowed, reason = live_odds.should_capture(prev, new)
        self.assertTrue(allowed)
        self.assertEqual(reason, "score")

    def test_mlb_inning_change(self):
        """MLB inning change triggers capture."""
        prev = {"sport": "mlb", "inning": 1, "half": "top", "home_runs": 0, "away_runs": 0}
        new = {"sport": "mlb", "inning": 2, "half": "top", "home_runs": 0, "away_runs": 0}
        allowed, reason = live_odds.should_capture(prev, new)
        self.assertTrue(allowed)
        self.assertEqual(reason, "inning")

    def test_mlb_half_change(self):
        """MLB half-inning change triggers capture."""
        prev = {"sport": "mlb", "inning": 1, "half": "top", "home_runs": 0, "away_runs": 0}
        new = {"sport": "mlb", "inning": 1, "half": "bottom", "home_runs": 0, "away_runs": 0}
        allowed, reason = live_odds.should_capture(prev, new)
        self.assertTrue(allowed)
        self.assertEqual(reason, "half")

    def test_mlb_pitcher_change(self):
        """MLB pitcher change triggers capture."""
        prev = {"sport": "mlb", "pitcher_id": "123", "home_runs": 0, "away_runs": 0, "inning": 1}
        new = {"sport": "mlb", "pitcher_id": "456", "home_runs": 0, "away_runs": 0, "inning": 1}
        allowed, reason = live_odds.should_capture(prev, new)
        self.assertTrue(allowed)
        self.assertEqual(reason, "pitching change")

    def test_mlb_no_change(self):
        """MLB with no changes does not trigger capture."""
        state = {"sport": "mlb", "inning": 1, "half": "top", "pitcher_id": "123",
                 "home_runs": 0, "away_runs": 0}
        allowed, reason = live_odds.should_capture(state, dict(state))
        self.assertFalse(allowed)
        self.assertEqual(reason, "no change")

    def test_nfl_score_change(self):
        """NFL score change triggers capture."""
        prev = {"sport": "nfl", "home_score": 0, "away_score": 0, "completed": False}
        new = {"sport": "nfl", "home_score": 7, "away_score": 0, "completed": False}
        allowed, reason = live_odds.should_capture(prev, new)
        self.assertTrue(allowed)
        self.assertEqual(reason, "score")

    def test_nfl_completed(self):
        """NFL completed status stops capture."""
        prev = {"sport": "nfl", "home_score": 7, "away_score": 3, "completed": False}
        new = {"sport": "nfl", "home_score": 7, "away_score": 3, "completed": True}
        allowed, reason = live_odds.should_capture(prev, new)
        self.assertFalse(allowed)
        self.assertEqual(reason, "completed")

    def test_nfl_no_change(self):
        """NFL with no changes does not trigger capture."""
        state = {"sport": "nfl", "home_score": 7, "away_score": 3, "completed": False}
        allowed, reason = live_odds.should_capture(state, dict(state))
        self.assertFalse(allowed)
        self.assertEqual(reason, "no change")


class TestChangedGames(unittest.TestCase):
    """Test the multi-game change detector."""

    def test_multiple_games_with_changes(self):
        """Multiple games, some changed."""
        prev = {
            "game1": {"sport": "mlb", "home_runs": 0, "away_runs": 0},
            "game2": {"sport": "mlb", "home_runs": 1, "away_runs": 2},
        }
        new = {
            "game1": {"sport": "mlb", "home_runs": 1, "away_runs": 0},  # score changed
            "game2": {"sport": "mlb", "home_runs": 1, "away_runs": 2},  # no change
            "game3": {"sport": "mlb", "home_runs": 0, "away_runs": 0},  # first observation
        }
        changes = live_odds.changed_games(prev, new)
        # game1 (score), game3 (first observation)
        self.assertEqual(len(changes), 2)
        game_ids = {gid for gid, _ in changes}
        self.assertEqual(game_ids, {"game1", "game3"})

    def test_empty_prev_states(self):
        """All new games are first observations."""
        new = {
            "game1": {"sport": "mlb", "home_runs": 0, "away_runs": 0},
            "game2": {"sport": "mlb", "home_runs": 1, "away_runs": 0},
        }
        changes = live_odds.changed_games({}, new)
        self.assertEqual(len(changes), 2)

    def test_empty_new_states(self):
        """No games = no changes."""
        prev = {
            "game1": {"sport": "mlb", "home_runs": 0, "away_runs": 0},
        }
        changes = live_odds.changed_games(prev, {})
        self.assertEqual(len(changes), 0)


class TestCaptureInplay(unittest.TestCase):
    """Test the main capture function with budget guards and fetch."""

    def test_spend_guard_refuses(self):
        """Spend guard refusal returns early without fetching."""
        spend_guard = Decision(allowed=False, reason="test: disabled")
        fetch_called = []

        def fake_fetch(**kwargs):
            fetch_called.append(True)
            raise AssertionError("should not have fetched")

        result = live_odds.capture_inplay(
            "mlb",
            state_snapshot_id="snap123",
            reason="test_reason",
            env=None,
            spend_guard=spend_guard,
            fetch_normalized=fake_fetch
        )

        self.assertFalse(fetch_called)
        self.assertEqual(result["captured"], 0)
        self.assertEqual(result["refused"], "test: disabled")
        self.assertEqual(result["credits"], 0)

    def test_capture_filters_to_inplay(self):
        """Only events with commence_time <= now are captured."""
        now = datetime.now(timezone.utc)

        # Create events: one past (in-play), one future (not in-play)
        past_event = {
            "event_id": "e1",
            "commence_time": now.isoformat().replace("+00:00", "Z"),
            "home_team": "Home1",
            "away_team": "Away1",
            "all_books": {
                "h2h": [
                    {"book": "book1", "home_price": 1.5, "away_price": 2.5},
                    {"book": "book2", "home_price": 1.6, "away_price": 2.4},
                ]
            }
        }
        future_event = {
            "event_id": "e2",
            "commence_time": (now.timestamp() + 3600),  # 1 hour in future
            "home_team": "Home2",
            "away_team": "Away2",
            "all_books": {"h2h": [{"book": "book1", "home_price": 1.7, "away_price": 2.3}]}
        }

        def fake_fetch(**kwargs):
            return {
                "fetched_utc": now.isoformat(),
                "events": [past_event, future_event]
            }

        spend_guard = Decision(allowed=True, reason="ok")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            result = live_odds.capture_inplay(
                "mlb",
                state_snapshot_id="snap123",
                reason="score",
                spend_guard=spend_guard,
                fetch_normalized=fake_fetch,
                path=tmp_path,
                clock=lambda tz: now,
                # The default is the REAL credit log; an un-injected test
                # here wrote rows into data/processed/credit_log.jsonl.
                record_credit=lambda *args, **kwargs: None,
            )

            self.assertEqual(result["captured"], 2)  # Only past_event's 2 books
            self.assertEqual(result["events_in_play"], 1)  # Only past_event
            self.assertEqual(result["credits"], 1)  # len(DEFAULT_MARKETS)

            # Verify written rows
            lines = Path(tmp_path).read_text(encoding="utf-8").strip().split("\n")
            self.assertEqual(len(lines), 2)
            for line in lines:
                row = json.loads(line)
                self.assertEqual(row["event_id"], "e1")
                self.assertEqual(row["in_play"], True)
                self.assertEqual(row["state_snapshot_id"], "snap123")
                self.assertEqual(row["trigger"], "score")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_capture_tags_rows_correctly(self):
        """Written rows have all required fields."""
        now = datetime.now(timezone.utc)

        event = {
            "event_id": "event123",
            "commence_time": now.isoformat().replace("+00:00", "Z"),
            "home_team": "Yankees",
            "away_team": "Red Sox",
            "all_books": {
                "h2h": [
                    {"book": "draftkings", "home_price": 1.8, "away_price": 2.0}
                ]
            }
        }

        def fake_fetch(**kwargs):
            return {
                "fetched_utc": now.isoformat(),
                "events": [event]
            }

        spend_guard = Decision(allowed=True, reason="ok")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            live_odds.capture_inplay(
                "mlb",
                state_snapshot_id="snap_xyz",
                reason="inning",
                spend_guard=spend_guard,
                fetch_normalized=fake_fetch,
                path=tmp_path,
                clock=lambda tz: now,
                record_credit=lambda *args, **kwargs: None,
            )

            row = json.loads(Path(tmp_path).read_text(encoding="utf-8").strip())
            self.assertEqual(row["sport"], "mlb")
            self.assertEqual(row["event_id"], "event123")
            self.assertEqual(row["commence_time"], now.isoformat().replace("+00:00", "Z"))
            self.assertEqual(row["home_team"], "Yankees")
            self.assertEqual(row["away_team"], "Red Sox")
            self.assertEqual(row["market"], "h2h")
            self.assertEqual(row["book"], "draftkings")
            self.assertEqual(row["home_price"], 1.8)
            self.assertEqual(row["away_price"], 2.0)
            self.assertTrue(row["in_play"])
            self.assertEqual(row["state_snapshot_id"], "snap_xyz")
            self.assertEqual(row["trigger"], "inning")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_capture_records_credit(self):
        """Credit logging is called once per capture."""
        credit_log_calls = []

        def fake_record_credit(remaining, used_last, caller, **kwargs):
            credit_log_calls.append({
                "remaining": remaining,
                "used_last": used_last,
                "caller": caller,
                "kwargs": kwargs
            })

        event = {
            "event_id": "e1",
            "commence_time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "home_team": "A",
            "away_team": "B",
            "all_books": {"h2h": []}
        }

        def fake_fetch(**kwargs):
            return {"fetched_utc": datetime.now(timezone.utc).isoformat(), "events": [event]}

        spend_guard = Decision(allowed=True, reason="ok")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            live_odds.capture_inplay(
                "mlb",
                state_snapshot_id="snap123",
                reason="score",
                spend_guard=spend_guard,
                fetch_normalized=fake_fetch,
                record_credit=fake_record_credit,
                path=tmp_path
            )

            self.assertEqual(len(credit_log_calls), 1)
            call = credit_log_calls[0]
            self.assertEqual(call["caller"], "live_odds.capture_inplay")
            self.assertEqual(call["kwargs"]["budget_band"], "live_odds")
        finally:
            Path(tmp_path).unlink(missing_ok=True)


class TestReadInplay(unittest.TestCase):
    """Test reading stored in-play odds."""

    def test_read_all(self):
        """Read all rows from a store."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tmp:
            tmp_path = tmp.name
            tmp.write(json.dumps({"event_id": "e1", "sport": "mlb"}) + "\n")
            tmp.write(json.dumps({"event_id": "e2", "sport": "mlb"}) + "\n")

        try:
            rows = live_odds.read_inplay(tmp_path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["event_id"], "e1")
            self.assertEqual(rows[1]["event_id"], "e2")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_read_filter_by_sport(self):
        """Filter rows by sport."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tmp:
            tmp_path = tmp.name
            tmp.write(json.dumps({"event_id": "e1", "sport": "mlb"}) + "\n")
            tmp.write(json.dumps({"event_id": "e2", "sport": "nfl"}) + "\n")
            tmp.write(json.dumps({"event_id": "e3", "sport": "mlb"}) + "\n")

        try:
            rows = live_odds.read_inplay(tmp_path, sport="mlb")
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(r["sport"] == "mlb" for r in rows))
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_read_filter_by_event_id(self):
        """Filter rows by event_id."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tmp:
            tmp_path = tmp.name
            tmp.write(json.dumps({"event_id": "e1", "sport": "mlb"}) + "\n")
            tmp.write(json.dumps({"event_id": "e2", "sport": "mlb"}) + "\n")
            tmp.write(json.dumps({"event_id": "e1", "sport": "mlb"}) + "\n")

        try:
            rows = live_odds.read_inplay(tmp_path, event_id="e1")
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(r["event_id"] == "e1" for r in rows))
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_read_nonexistent_path(self):
        """Nonexistent file returns empty list."""
        rows = live_odds.read_inplay("/nonexistent/path/odds.jsonl")
        self.assertEqual(rows, [])


class TestLatestInplayQuote(unittest.TestCase):
    """Test fetching the newest batch of quotes."""

    def test_latest_quote_empty(self):
        """Empty rows return None."""
        result = live_odds.latest_inplay_quote([], "e1")
        self.assertIsNone(result)

    def test_latest_quote_no_matching_event(self):
        """No matching event_id returns None."""
        rows = [
            {"event_id": "e1", "observed_utc": "2026-09-14T10:00:00Z"},
            {"event_id": "e2", "observed_utc": "2026-09-14T10:01:00Z"},
        ]
        result = live_odds.latest_inplay_quote(rows, "e3")
        self.assertIsNone(result)

    def test_latest_quote_single_batch(self):
        """Single batch of quotes."""
        rows = [
            {"event_id": "e1", "observed_utc": "2026-09-14T10:00:00Z",
             "book": "draftkings", "home_price": 1.5, "away_price": 2.5},
            {"event_id": "e1", "observed_utc": "2026-09-14T10:00:00Z",
             "book": "fanduel", "home_price": 1.6, "away_price": 2.4},
        ]
        result = live_odds.latest_inplay_quote(rows, "e1")
        self.assertIsNotNone(result)
        self.assertEqual(result["observed_utc"], "2026-09-14T10:00:00Z")
        self.assertEqual(len(result["quotes"]), 2)
        books = {q["book"] for q in result["quotes"]}
        self.assertEqual(books, {"draftkings", "fanduel"})

    def test_latest_quote_multiple_batches(self):
        """Multiple batches, returns newest."""
        rows = [
            {"event_id": "e1", "observed_utc": "2026-09-14T10:00:00Z",
             "book": "draftkings", "home_price": 1.5, "away_price": 2.5},
            {"event_id": "e1", "observed_utc": "2026-09-14T10:01:00Z",
             "book": "draftkings", "home_price": 1.6, "away_price": 2.4},
            {"event_id": "e1", "observed_utc": "2026-09-14T10:01:00Z",
             "book": "fanduel", "home_price": 1.7, "away_price": 2.3},
        ]
        result = live_odds.latest_inplay_quote(rows, "e1")
        self.assertIsNotNone(result)
        self.assertEqual(result["observed_utc"], "2026-09-14T10:01:00Z")
        self.assertEqual(len(result["quotes"]), 2)

    def test_latest_quote_mixed_events(self):
        """Multiple events, returns only for specified event_id."""
        rows = [
            {"event_id": "e1", "observed_utc": "2026-09-14T10:00:00Z",
             "book": "b1", "home_price": 1.5, "away_price": 2.5},
            {"event_id": "e2", "observed_utc": "2026-09-14T10:01:00Z",
             "book": "b1", "home_price": 1.6, "away_price": 2.4},
            {"event_id": "e1", "observed_utc": "2026-09-14T10:02:00Z",
             "book": "b1", "home_price": 1.7, "away_price": 2.3},
        ]
        result = live_odds.latest_inplay_quote(rows, "e1")
        self.assertIsNotNone(result)
        self.assertEqual(result["observed_utc"], "2026-09-14T10:02:00Z")


if __name__ == "__main__":
    unittest.main()
