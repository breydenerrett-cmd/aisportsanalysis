"""Tests for bounded tennis h2h capture per tournament key.

Tests verify:
- Two keys with matches inside t24h both captured, rows carry sport and tournament_key
- Refusing guard prevents writes and marks
- Second run at same clock has nothing due
- Seven keys limited to six, ordered by earliest match
- Key with list_events error is skipped, others proceed
- Matches already started are never due
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.pipeline import tennis_capture


class TestTennisCapture(unittest.TestCase):

    def test_two_keys_with_matches_in_t24h_both_captured(self):
        """Two keys with matches inside t24h -> both captured, sport and tournament_key set."""
        with tempfile.TemporaryDirectory() as tmp:
            snap_path = Path(tmp) / "snap.jsonl"
            mb_path = Path(tmp) / "mb.jsonl"
            done_path = Path(tmp) / "done.jsonl"

            now = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)

            # Two tournament keys with upcoming matches
            key1 = "tennis_atp_paris"
            key2 = "tennis_wta_wimbledon"

            # Matches starting in 12 hours (within t24h window)
            match_time = (now + timedelta(hours=12)).isoformat()

            events_key1 = [
                {"id": "e1", "commence_time": match_time, "home_team": "Player A", "away_team": "Player B"}
            ]
            events_key2 = [
                {"id": "e2", "commence_time": match_time, "home_team": "Player C", "away_team": "Player D"}
            ]

            payload_key1 = {
                "events": [{
                    "event_id": "e1",
                    "commence_time": match_time,
                    "home_team": "Player A",
                    "away_team": "Player B",
                    "markets": {
                        "h2h": {"book": "bet365", "home_price": -150, "away_price": 130}
                    },
                    "all_books": {
                        "h2h": [{"book": "bet365", "home_price": -150, "away_price": 130}]
                    }
                }]
            }

            payload_key2 = {
                "events": [{
                    "event_id": "e2",
                    "commence_time": match_time,
                    "home_team": "Player C",
                    "away_team": "Player D",
                    "markets": {
                        "h2h": {"book": "bet365", "home_price": -130, "away_price": 110}
                    },
                    "all_books": {
                        "h2h": [{"book": "bet365", "home_price": -130, "away_price": 110}]
                    }
                }]
            }

            def mock_list_events(*, env, sport):
                if sport == key1:
                    return events_key1
                elif sport == key2:
                    return events_key2
                return []

            def mock_fetch_normalized(*, markets, env, sport):
                if sport == key1:
                    return payload_key1
                elif sport == key2:
                    return payload_key2
                return {"events": []}

            guard_calls = []

            def mock_spend_guard(*args, **kwargs):
                guard_calls.append((args, kwargs))
                # Always allow
                decision = mock.Mock()
                decision.allowed = True
                return decision

            result = tennis_capture.run(
                now=now,
                keys=[key1, key2],
                list_events=mock_list_events,
                fetch_normalized=mock_fetch_normalized,
                spend_guard=mock_spend_guard,
                snapshot_path=str(snap_path),
                multibook_path=str(mb_path),
                done_path=str(done_path),
            )

            # The guard reads the REAL credit log. Handing it the done log as
            # `store` made it refuse every capture on the runner on
            # 2026-09-15 ("quota unreadable").
            self.assertTrue(guard_calls)
            for _args, kwargs in guard_calls:
                self.assertNotIn("store", kwargs)

            # Both keys should be captured
            self.assertEqual(len(result["captured"]), 2)
            self.assertIn(key1, result["captured"])
            self.assertIn(key2, result["captured"])

            # Rows should carry sport and tournament_key
            snap_rows = []
            if snap_path.exists():
                with open(snap_path) as f:
                    for line in f:
                        snap_rows.append(json.loads(line))

            self.assertGreater(len(snap_rows), 0)
            for row in snap_rows:
                self.assertIn("sport", row)
                self.assertIn("tournament_key", row)

            # Should use 2 credits (1 per key)
            self.assertEqual(result["credits"], 2)

    def test_refusing_guard_skips_capture(self):
        """Refusing guard -> nothing written, nothing marked done."""
        with tempfile.TemporaryDirectory() as tmp:
            snap_path = Path(tmp) / "snap.jsonl"
            mb_path = Path(tmp) / "mb.jsonl"
            done_path = Path(tmp) / "done.jsonl"

            now = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)
            key = "tennis_atp_paris"
            match_time = (now + timedelta(hours=12)).isoformat()

            events = [
                {"id": "e1", "commence_time": match_time, "home_team": "Player A", "away_team": "Player B"}
            ]

            def mock_list_events(*, env, sport):
                return events

            def mock_spend_guard(*args, **kwargs):
                decision = mock.Mock()
                decision.allowed = False
                decision.reason = "budget exhausted"
                return decision

            result = tennis_capture.run(
                now=now,
                keys=[key],
                list_events=mock_list_events,
                fetch_normalized=mock.Mock(),  # Should not be called
                spend_guard=mock_spend_guard,
                snapshot_path=str(snap_path),
                multibook_path=str(mb_path),
                done_path=str(done_path),
            )

            # Key should be skipped
            self.assertEqual(len(result["captured"]), 0)
            self.assertIn(key, result["skipped"])

            # No rows written
            self.assertEqual(result["rows"], 0)

            # No done marker written
            self.assertFalse(done_path.exists())

    def test_second_run_at_same_clock_nothing_due(self):
        """Second run at same clock -> nothing due (already in done log)."""
        with tempfile.TemporaryDirectory() as tmp:
            snap_path = Path(tmp) / "snap.jsonl"
            mb_path = Path(tmp) / "mb.jsonl"
            done_path = Path(tmp) / "done.jsonl"

            now = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)
            key = "tennis_atp_paris"
            match_time = (now + timedelta(hours=12)).isoformat()

            events = [
                {"id": "e1", "commence_time": match_time, "home_team": "Player A", "away_team": "Player B"}
            ]

            payload = {
                "events": [{
                    "event_id": "e1",
                    "commence_time": match_time,
                    "home_team": "Player A",
                    "away_team": "Player B",
                    "markets": {
                        "h2h": {"book": "bet365", "home_price": -150, "away_price": 130}
                    },
                    "all_books": {
                        "h2h": [{"book": "bet365", "home_price": -150, "away_price": 130}]
                    }
                }]
            }

            def mock_list_events(*, env, sport):
                return events

            def mock_fetch_normalized(*, markets, env, sport):
                return payload

            def mock_spend_guard(*args, **kwargs):
                decision = mock.Mock()
                decision.allowed = True
                return decision

            # First run
            result1 = tennis_capture.run(
                now=now,
                keys=[key],
                list_events=mock_list_events,
                fetch_normalized=mock_fetch_normalized,
                spend_guard=mock_spend_guard,
                snapshot_path=str(snap_path),
                multibook_path=str(mb_path),
                done_path=str(done_path),
            )

            self.assertEqual(len(result1["captured"]), 1)
            self.assertEqual(result1["credits"], 1)

            # Second run at same time
            result2 = tennis_capture.run(
                now=now,
                keys=[key],
                list_events=mock_list_events,
                fetch_normalized=mock_fetch_normalized,
                spend_guard=mock_spend_guard,
                snapshot_path=str(snap_path),
                multibook_path=str(mb_path),
                done_path=str(done_path),
            )

            # Nothing captured on second run (already done)
            self.assertEqual(len(result2["captured"]), 0)
            self.assertEqual(result2["credits"], 0)

    def test_seven_keys_only_six_considered(self):
        """Seven active keys -> only six considered."""
        with tempfile.TemporaryDirectory() as tmp:
            snap_path = Path(tmp) / "snap.jsonl"
            mb_path = Path(tmp) / "mb.jsonl"
            done_path = Path(tmp) / "done.jsonl"

            now = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)

            # Seven keys, each with one match at different times
            keys = [f"tennis_atp_key{i}" for i in range(7)]

            def mock_list_events(*, env, sport):
                # Each key gets a unique match time
                key_index = int(sport.split("key")[1])
                match_time = (now + timedelta(hours=key_index + 1)).isoformat()
                return [{"id": f"e{key_index}", "commence_time": match_time}]

            def mock_fetch_normalized(*, markets, env, sport):
                key_index = int(sport.split("key")[1])
                return {
                    "events": [{
                        "event_id": f"e{key_index}",
                        "commence_time": (now + timedelta(hours=key_index + 1)).isoformat(),
                        "markets": {"h2h": {"book": "bet365", "home_price": -150, "away_price": 130}},
                        "all_books": {"h2h": [{"book": "bet365", "home_price": -150, "away_price": 130}]}
                    }]
                }

            def mock_spend_guard(*args, **kwargs):
                decision = mock.Mock()
                decision.allowed = True
                return decision

            result = tennis_capture.run(
                now=now,
                keys=keys,
                list_events=mock_list_events,
                fetch_normalized=mock_fetch_normalized,
                spend_guard=mock_spend_guard,
                snapshot_path=str(snap_path),
                multibook_path=str(mb_path),
                done_path=str(done_path),
            )

            # Only 6 keys should be in the selected list (result["keys"])
            self.assertEqual(len(result["keys"]), 6)

            # At most 6 should be captured
            self.assertLessEqual(len(result["captured"]), 6)

    def test_key_with_list_events_error_skipped(self):
        """Key whose list_events raises is skipped, others proceed."""
        with tempfile.TemporaryDirectory() as tmp:
            snap_path = Path(tmp) / "snap.jsonl"
            mb_path = Path(tmp) / "mb.jsonl"
            done_path = Path(tmp) / "done.jsonl"

            now = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)

            key1 = "tennis_atp_paris"
            key2 = "tennis_atp_london"
            match_time = (now + timedelta(hours=12)).isoformat()

            events_key2 = [
                {"id": "e2", "commence_time": match_time, "home_team": "Player C", "away_team": "Player D"}
            ]

            payload_key2 = {
                "events": [{
                    "event_id": "e2",
                    "commence_time": match_time,
                    "home_team": "Player C",
                    "away_team": "Player D",
                    "markets": {
                        "h2h": {"book": "bet365", "home_price": -130, "away_price": 110}
                    },
                    "all_books": {
                        "h2h": [{"book": "bet365", "home_price": -130, "away_price": 110}]
                    }
                }]
            }

            def mock_list_events(*, env, sport):
                if sport == key1:
                    raise RuntimeError("API error")
                elif sport == key2:
                    return events_key2
                return []

            def mock_fetch_normalized(*, markets, env, sport):
                if sport == key2:
                    return payload_key2
                return {"events": []}

            def mock_spend_guard(*args, **kwargs):
                decision = mock.Mock()
                decision.allowed = True
                return decision

            result = tennis_capture.run(
                now=now,
                keys=[key1, key2],
                list_events=mock_list_events,
                fetch_normalized=mock_fetch_normalized,
                spend_guard=mock_spend_guard,
                snapshot_path=str(snap_path),
                multibook_path=str(mb_path),
                done_path=str(done_path),
            )

            # key1 should be skipped
            self.assertIn(key1, result["skipped"])

            # key2 should be captured
            self.assertIn(key2, result["captured"])

            # Only 1 credit used
            self.assertEqual(result["credits"], 1)

    def test_matches_already_started_never_due(self):
        """Matches already started are never due (no phases capture them)."""
        with tempfile.TemporaryDirectory() as tmp:
            snap_path = Path(tmp) / "snap.jsonl"
            mb_path = Path(tmp) / "mb.jsonl"
            done_path = Path(tmp) / "done.jsonl"

            now = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)
            key = "tennis_atp_paris"

            # Match started 1 hour ago
            match_time = (now - timedelta(hours=1)).isoformat()

            events = [
                {"id": "e1", "commence_time": match_time, "home_team": "Player A", "away_team": "Player B"}
            ]

            def mock_list_events(*, env, sport):
                return events

            def mock_fetch_normalized(*, markets, env, sport):
                # Should never be called
                raise AssertionError("fetch_normalized should not be called for started matches")

            def mock_spend_guard(*args, **kwargs):
                raise AssertionError("spend_guard should not be called for no due pairs")

            result = tennis_capture.run(
                now=now,
                keys=[key],
                list_events=mock_list_events,
                fetch_normalized=mock_fetch_normalized,
                spend_guard=mock_spend_guard,
                snapshot_path=str(snap_path),
                multibook_path=str(mb_path),
                done_path=str(done_path),
            )

            # Nothing captured
            self.assertEqual(len(result["captured"]), 0)
            self.assertEqual(result["credits"], 0)


if __name__ == "__main__":
    unittest.main()
