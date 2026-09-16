"""Tests for in-play odds capture (event-driven, budget-constrained)."""

import json
import tempfile
import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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

    def test_capture_bills_from_response_usage_headers(self):
        """R16-L3/D6: the credit row bills THIS call's own x-requests-last,
        read off the response's 'usage' dict, not a market-count estimate."""
        credit_log_calls = []

        def fake_record_credit(remaining, used_last, caller, **kwargs):
            credit_log_calls.append({"remaining": remaining, "used_last": used_last})

        event = {
            "event_id": "e1",
            "commence_time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "home_team": "A",
            "away_team": "B",
            "all_books": {"h2h": []},
        }

        def fake_fetch(**kwargs):
            return {
                "fetched_utc": datetime.now(timezone.utc).isoformat(),
                "events": [event],
                # Real x-requests-last / x-requests-remaining, as
                # src.providers.odds._get_json_with_usage surfaces them.
                "usage": {"last": 3, "remaining": 12345},
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
                record_credit=fake_record_credit,
                path=tmp_path,
            )

            self.assertEqual(result["credits"], 3)
            self.assertEqual(len(credit_log_calls), 1)
            self.assertEqual(credit_log_calls[0]["used_last"], 3)
            self.assertEqual(credit_log_calls[0]["remaining"], 12345)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_capture_writes_credit_row_to_live_credit_log_by_default(self):
        """R16-L4/D7: capture_inplay's default credit_store is the live-only
        log, never data/processed/credit_log.jsonl, so it never collides
        with the forward-capture chain's own writes to that file."""
        self.assertEqual(
            live_odds.DEFAULT_CREDIT_LOG_PATH.name, "credit_log_live.jsonl")
        self.assertIn("live", str(live_odds.DEFAULT_CREDIT_LOG_PATH))

    def test_capture_falls_back_to_market_estimate_without_usage(self):
        """A fetch that does not surface 'usage' (an older test double, or a
        caller not yet updated) still bills a non-None, non-zero estimate
        rather than leaving the row unbillable."""
        event = {
            "event_id": "e1",
            "commence_time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "home_team": "A",
            "away_team": "B",
            "all_books": {"h2h": []},
        }

        def fake_fetch(**kwargs):
            return {"fetched_utc": datetime.now(timezone.utc).isoformat(),
                    "events": [event]}

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
                record_credit=lambda *a, **k: None,
                path=tmp_path,
            )
            self.assertEqual(result["credits"], 1)  # len(DEFAULT_MARKETS)
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

    def test_latest_quote_carries_last_update(self):
        """D9: last_update must survive the round trip through
        latest_inplay_quote, not just capture_inplay's write."""
        rows = [
            {"event_id": "e1", "observed_utc": "2026-09-14T10:00:00Z",
             "book": "draftkings", "home_price": -110, "away_price": 100,
             "last_update": "2026-09-14T09:59:50Z"},
        ]
        result = live_odds.latest_inplay_quote(rows, "e1")
        self.assertEqual(result["quotes"][0]["last_update"], "2026-09-14T09:59:50Z")


class TestCaptureInplayPersistsLastUpdate(unittest.TestCase):
    """D9: capture_inplay must not drop each book's own last_update."""

    def test_written_rows_carry_last_update(self):
        def fake_fetch(markets, env=None, sport=None):
            return {
                "fetched_utc": "2026-09-14T20:00:00Z",
                "usage": {"last": 1, "remaining": 100},
                "events": [{
                    "event_id": "e1",
                    "commence_time": "2026-09-14T19:00:00Z",
                    "home_team": "Yankees", "away_team": "Red Sox",
                    "all_books": {"h2h": [
                        {"book": "draftkings", "home_price": -110, "away_price": 100,
                         "last_update": "2026-09-14T19:59:50Z"},
                    ]},
                }],
            }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "odds_inplay.jsonl"
            credit_store = Path(tmp) / "credit_log_live.jsonl"

            result = live_odds.capture_inplay(
                "mlb", state_snapshot_id="s1", reason="retry_0",
                fetch_normalized=fake_fetch,
                spend_guard=Decision(True, "ok"),
                path=path, credit_store=credit_store,
                clock=lambda tz: datetime(2026, 9, 14, 20, 0, 0, tzinfo=tz),
            )

            self.assertEqual(result["captured"], 1)
            rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
            self.assertEqual(rows[0]["last_update"], "2026-09-14T19:59:50Z")


class TestDueCapture(unittest.TestCase):
    """R16-L5: the retry/follow-up capture schedule for a tracked trigger."""

    def _now(self, **kwargs):
        return datetime(2026, 9, 14, 20, 0, 0, tzinfo=timezone.utc) + timedelta(**kwargs)

    def test_due_immediately_at_t0(self):
        record = live_odds.new_trigger_record(
            "2026-09-14T20:00:00Z", {"margin": -1})
        reason = live_odds.due_capture(record, self._now())
        self.assertEqual(reason, "retry_0")

    def test_not_due_before_45s_retry(self):
        record = live_odds.new_trigger_record("2026-09-14T20:00:00Z", {})
        record["next_retry_idx"] = 1  # the T0 attempt already happened
        reason = live_odds.due_capture(record, self._now(seconds=30))
        self.assertIsNone(reason)

    def test_due_at_45s_retry(self):
        record = live_odds.new_trigger_record("2026-09-14T20:00:00Z", {})
        record["next_retry_idx"] = 1
        reason = live_odds.due_capture(record, self._now(seconds=45))
        self.assertEqual(reason, "retry_45")

    def test_due_at_90s_retry(self):
        record = live_odds.new_trigger_record("2026-09-14T20:00:00Z", {})
        record["next_retry_idx"] = 2
        reason = live_odds.due_capture(record, self._now(seconds=90))
        self.assertEqual(reason, "retry_90")

    def test_no_more_retries_after_90s_exhausted(self):
        record = live_odds.new_trigger_record("2026-09-14T20:00:00Z", {})
        record["next_retry_idx"] = 3  # all three offsets attempted
        reason = live_odds.due_capture(record, self._now(seconds=200))
        self.assertIsNone(reason)  # follow-up (300s) not due yet either

    def test_priced_trigger_stops_retries_but_not_followup(self):
        record = live_odds.new_trigger_record("2026-09-14T20:00:00Z", {})
        record["priced"] = True
        record["next_retry_idx"] = 1
        # Before follow-up window: nothing due.
        self.assertIsNone(live_odds.due_capture(record, self._now(seconds=45)))
        # At follow-up window: the descriptive follow-up is still due.
        self.assertEqual(
            live_odds.due_capture(record, self._now(seconds=300)),
            live_odds.FOLLOWUP_REASON)

    def test_followup_due_once_at_5_minutes(self):
        record = live_odds.new_trigger_record("2026-09-14T20:00:00Z", {})
        record["priced"] = True
        record["next_retry_idx"] = 3
        reason = live_odds.due_capture(record, self._now(minutes=5))
        self.assertEqual(reason, live_odds.FOLLOWUP_REASON)

    def test_followup_not_due_again_once_marked_done(self):
        record = live_odds.new_trigger_record("2026-09-14T20:00:00Z", {})
        record["priced"] = True
        record["next_retry_idx"] = 3
        record["followup_done"] = True
        reason = live_odds.due_capture(record, self._now(minutes=10))
        self.assertIsNone(reason)

    def test_nothing_due_before_t0(self):
        """`now` before T0 (a clock or ordering oddity) must never be
        treated as "due" -- elapsed must be non-negative."""
        record = live_odds.new_trigger_record("2026-09-14T20:00:00Z", {})
        reason = live_odds.due_capture(record, self._now(seconds=-5))
        self.assertIsNone(reason)


class TestFreshQuotes(unittest.TestCase):
    """Side-independent freshness filter (used to gate PRICED before
    live_rules.fresh_median_price computes a per-side price)."""

    def test_filters_stale_and_keeps_fresh(self):
        quotes = [
            {"book": "DK", "last_update": "2026-09-14T19:59:00Z"},  # before T0
            {"book": "FD", "last_update": "2026-09-14T20:00:10Z"},
            {"book": "BR", "last_update": "2026-09-14T20:00:15Z"},
        ]
        fresh = live_odds.fresh_quotes(
            quotes, t0_utc="2026-09-14T20:00:00Z",
            captured_utc="2026-09-14T20:00:20Z")
        self.assertEqual({q["book"] for q in fresh}, {"FD", "BR"})

    def test_empty_or_none_quotes(self):
        self.assertEqual(live_odds.fresh_quotes(
            None, t0_utc="2026-09-14T20:00:00Z",
            captured_utc="2026-09-14T20:00:20Z"), [])
        self.assertEqual(live_odds.fresh_quotes(
            [], t0_utc="2026-09-14T20:00:00Z",
            captured_utc="2026-09-14T20:00:20Z"), [])


if __name__ == "__main__":
    unittest.main()
