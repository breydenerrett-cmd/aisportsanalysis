"""api/performance.py: GET /performance/live.

Live research candidates record and history, from live_ledger module.
Uses the same offline pattern as test_api_performance.py: direct-call
tests exercise `api.performance.get_performance_live` with patched
live_ledger calls.
"""

from __future__ import annotations

import json
import unittest

try:
    import fastapi  # noqa: F401
    _HAVE_FASTAPI = True
except ImportError:
    _HAVE_FASTAPI = False

if _HAVE_FASTAPI:
    from api import performance as perf_api


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class GetPerformanceLiveShapeTests(unittest.TestCase):
    """Test /performance/live endpoint shape and content."""

    def test_returns_json_serialisable_payload(self):
        """Payload must be JSON-serialisable end to end."""
        payload = perf_api.get_performance_live(limit=50)
        json.loads(json.dumps(payload))  # must not raise

    def test_returns_required_keys(self):
        """Payload must contain record, history, notice, and generated_utc."""
        payload = perf_api.get_performance_live(limit=50)
        self.assertIn("record", payload)
        self.assertIn("history", payload)
        self.assertIn("notice", payload)
        self.assertIn("generated_utc", payload)

    def test_notice_is_correct_sentence(self):
        """Notice must be the exact required sentence."""
        payload = perf_api.get_performance_live(limit=50)
        self.assertEqual(
            payload["notice"],
            "Live analysis is in internal testing. No alerts are sent.")

    def test_record_has_counts(self):
        """Record must have settled, wins, losses, pushes, voids, units, by_rule."""
        payload = perf_api.get_performance_live(limit=50)
        record = payload["record"]
        for key in ("settled", "wins", "losses", "pushes", "voids", "units", "by_rule"):
            self.assertIn(key, record)

    def test_history_is_a_list(self):
        """History must be a list of candidate dicts."""
        payload = perf_api.get_performance_live(limit=50)
        self.assertIsInstance(payload["history"], list)

    def test_generated_utc_is_iso_string(self):
        """generated_utc must be an ISO datetime string."""
        payload = perf_api.get_performance_live(limit=50)
        # Basic check: ISO format starts with YYYY-MM-DD
        self.assertRegex(payload["generated_utc"], r"^\d{4}-\d{2}-\d{2}")


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class GetPerformanceLiveLimitValidationTests(unittest.TestCase):
    """Test /performance/live limit parameter validation."""

    def test_limit_zero_is_rejected(self):
        """Limit must be at least 1."""
        with self.assertRaises(fastapi.HTTPException) as ctx:
            perf_api.get_performance_live(limit=0)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_limit_over_200_is_rejected(self):
        """Limit must be at most 200."""
        with self.assertRaises(fastapi.HTTPException) as ctx:
            perf_api.get_performance_live(limit=201)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_limit_at_bounds_is_accepted(self):
        """Limits 1 and 200 must be accepted."""
        perf_api.get_performance_live(limit=1)
        perf_api.get_performance_live(limit=200)


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class GetPerformanceLiveWithPatchedLedger(unittest.TestCase):
    """Test /performance/live with patched live_ledger calls."""

    def test_with_fake_record_and_history(self):
        """Verify endpoint calls the patchable live_ledger functions."""
        fake_record = {
            "settled": 5,
            "wins": 3,
            "losses": 2,
            "pushes": 0,
            "voids": 0,
            "units": 1.5,
            "by_rule": {"rule_1": {"wins": 3, "losses": 2, "pushes": 0, "voids": 0, "units": 1.5}}
        }
        fake_history = [
            {
                "rule_id": "rule_1",
                "sport": "nfl",
                "game_id": "2026_01_TEN_KC",
                "bet": "Kansas City to win",
                "price": -150,
                "settlement": {"result": "WIN", "profit_units": 0.67}
            }
        ]

        # Patch live_ledger calls
        original_record = perf_api._live_ledger_record
        original_history = perf_api._live_ledger_history
        try:
            perf_api._live_ledger_record = lambda: fake_record
            perf_api._live_ledger_history = lambda limit: fake_history[:limit]

            payload = perf_api.get_performance_live(limit=50)
            self.assertEqual(payload["record"], fake_record)
            self.assertEqual(payload["history"], fake_history)
        finally:
            perf_api._live_ledger_record = original_record
            perf_api._live_ledger_history = original_history

    def test_respects_history_limit_parameter(self):
        """History limit parameter must be passed through to live_ledger.history."""
        def fake_history(limit):
            return [{"id": i} for i in range(limit)]

        original = perf_api._live_ledger_history
        try:
            perf_api._live_ledger_history = fake_history
            payload = perf_api.get_performance_live(limit=10)
            self.assertEqual(len(payload["history"]), 10)
        finally:
            perf_api._live_ledger_history = original


if __name__ == "__main__":
    unittest.main()
