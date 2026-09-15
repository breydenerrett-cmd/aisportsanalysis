"""Tests for src/pipeline/tennis_discovery.py"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.pipeline import tennis_discovery


class TestTennisDiscovery(unittest.TestCase):
    """Tests for tennis tournament discovery."""

    def setUp(self):
        """Create a temp file for each test."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name) / "tennis_tournaments.jsonl"

    def tearDown(self):
        """Clean up temp directory."""
        self.temp_dir.cleanup()

    def _fake_fetch_sports(self):
        """Return mixed list: baseball, nfl, and three tennis entries (one inactive)."""
        return [
            {
                "key": "baseball_mlb",
                "title": "MLB",
                "description": "Major League Baseball",
                "group": "Baseball",
                "active": True,
                "has_outrights": False,
            },
            {
                "key": "americanfootball_nfl",
                "title": "NFL",
                "description": "National Football League",
                "group": "American Football",
                "active": True,
                "has_outrights": False,
            },
            {
                "key": "tennis_atp_us_open",
                "title": "ATP US Open",
                "description": "ATP US Open",
                "group": "Tennis",
                "active": True,
                "has_outrights": True,
            },
            {
                "key": "tennis_wta_us_open",
                "title": "WTA US Open",
                "description": "WTA US Open",
                "group": "Tennis",
                "active": True,
                "has_outrights": True,
            },
            {
                "key": "tennis_atp_china_open",
                "title": "ATP China Open",
                "description": "ATP China Open",
                "group": "Tennis",
                "active": False,  # This one is inactive
                "has_outrights": False,
            },
        ]

    def test_discover_keeps_only_tennis_and_writes_three_rows(self):
        """discover() filters for tennis and writes 3 rows."""
        result = tennis_discovery.discover(
            fetch_sports=self._fake_fetch_sports,
            path=str(self.temp_path)
        )

        self.assertEqual(result["written"], 3)
        self.assertEqual(len(result["keys"]), 3)
        self.assertEqual(len(result["active_keys"]), 2)  # Two active, one inactive
        self.assertIn("tennis_atp_us_open", result["keys"])
        self.assertIn("tennis_wta_us_open", result["keys"])
        self.assertIn("tennis_atp_china_open", result["keys"])
        self.assertIn("tennis_atp_us_open", result["active_keys"])
        self.assertIn("tennis_wta_us_open", result["active_keys"])
        self.assertNotIn("tennis_atp_china_open", result["active_keys"])
        self.assertNotIn("baseball_mlb", result["keys"])
        self.assertNotIn("americanfootball_nfl", result["keys"])

        # Verify rows were written
        self.assertTrue(self.temp_path.exists())
        with open(self.temp_path, "r") as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 3)

        # Verify row content
        row = json.loads(lines[0])
        self.assertEqual(row["key"], "tennis_atp_us_open")
        self.assertEqual(row["title"], "ATP US Open")
        self.assertIn("observed_utc", row)
        self.assertTrue(row["active"])
        self.assertTrue(row["has_outrights"])

    def test_active_keys_returns_two_active(self):
        """active_keys() returns the 2 active from the latest observation."""
        tennis_discovery.discover(
            fetch_sports=self._fake_fetch_sports,
            path=str(self.temp_path)
        )

        result = tennis_discovery.active_keys(path=str(self.temp_path))
        self.assertEqual(len(result), 2)
        self.assertIn("tennis_atp_us_open", result)
        self.assertIn("tennis_wta_us_open", result)
        self.assertNotIn("tennis_atp_china_open", result)

    def test_latest_returns_rows_from_newest_observation(self):
        """latest() returns only rows from the newest observed_utc."""
        now1 = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)
        result1 = tennis_discovery.discover(
            fetch_sports=self._fake_fetch_sports,
            path=str(self.temp_path),
            now=now1
        )
        self.assertEqual(result1["written"], 3)

        # Make a second observation with newer timestamp
        now2 = now1 + timedelta(hours=2)
        result2 = tennis_discovery.discover(
            fetch_sports=self._fake_fetch_sports,
            path=str(self.temp_path),
            now=now2
        )
        self.assertEqual(result2["written"], 3)

        # latest() should return only the newer rows
        latest_rows = tennis_discovery.latest(path=str(self.temp_path))
        self.assertEqual(len(latest_rows), 3)
        # All rows should have the newer timestamp
        for row in latest_rows:
            self.assertEqual(row["observed_utc"], now2.isoformat())

    def test_latest_returns_empty_when_no_file(self):
        """latest() returns [] when file does not exist."""
        result = tennis_discovery.latest(path=str(self.temp_path))
        self.assertEqual(result, [])

    def test_active_keys_returns_empty_when_older_than_max_age(self):
        """active_keys() returns [] if observation is older than max_age_hours."""
        now = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)
        tennis_discovery.discover(
            fetch_sports=self._fake_fetch_sports,
            path=str(self.temp_path),
            now=now
        )

        # Ask for active keys at a time 37 hours later (max_age default is 36)
        later = now + timedelta(hours=37)
        result = tennis_discovery.active_keys(
            path=str(self.temp_path),
            now=later,
            max_age_hours=36
        )
        self.assertEqual(result, [])

    def test_active_keys_returns_keys_when_within_max_age(self):
        """active_keys() returns keys if observation is within max_age_hours."""
        now = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)
        tennis_discovery.discover(
            fetch_sports=self._fake_fetch_sports,
            path=str(self.temp_path),
            now=now
        )

        # Ask for active keys at a time 35 hours later (within 36-hour max)
        later = now + timedelta(hours=35)
        result = tennis_discovery.active_keys(
            path=str(self.temp_path),
            now=later,
            max_age_hours=36
        )
        self.assertEqual(len(result), 2)
        self.assertIn("tennis_atp_us_open", result)
        self.assertIn("tennis_wta_us_open", result)

    def test_provider_error_returns_error_and_writes_nothing(self):
        """When fetch_sports raises, discover() returns error and writes nothing."""
        def failing_fetch():
            raise RuntimeError("Provider is down")

        result = tennis_discovery.discover(
            fetch_sports=failing_fetch,
            path=str(self.temp_path)
        )

        self.assertIn("error", result)
        self.assertEqual(result["written"], 0)
        self.assertFalse(self.temp_path.exists())

    def test_discover_with_empty_sports_list(self):
        """discover() handles empty sports list gracefully."""
        def empty_fetch():
            return []

        result = tennis_discovery.discover(
            fetch_sports=empty_fetch,
            path=str(self.temp_path)
        )

        self.assertEqual(result["written"], 0)
        self.assertEqual(result["keys"], [])
        self.assertEqual(result["active_keys"], [])
        # File may or may not be created depending on implementation
        # but no rows should be written
        if self.temp_path.exists():
            with open(self.temp_path, "r") as f:
                content = f.read()
            self.assertEqual(content, "")

    def test_discover_with_no_tennis_entries(self):
        """discover() handles sports list with no tennis gracefully."""
        def no_tennis_fetch():
            return [
                {"key": "baseball_mlb", "active": True},
                {"key": "americanfootball_nfl", "active": True},
            ]

        result = tennis_discovery.discover(
            fetch_sports=no_tennis_fetch,
            path=str(self.temp_path)
        )

        self.assertEqual(result["written"], 0)
        self.assertEqual(result["keys"], [])
        self.assertEqual(result["active_keys"], [])

    def test_row_structure_is_correct(self):
        """Each written row has correct structure and all required fields."""
        tennis_discovery.discover(
            fetch_sports=self._fake_fetch_sports,
            path=str(self.temp_path)
        )

        with open(self.temp_path, "r") as f:
            for line in f:
                row = json.loads(line)
                # Verify required fields
                self.assertIn("observed_utc", row)
                self.assertIn("key", row)
                self.assertIn("title", row)
                self.assertIn("description", row)
                self.assertIn("group", row)
                self.assertIn("active", row)
                self.assertIn("has_outrights", row)
                # Verify types
                self.assertIsInstance(row["active"], bool)
                self.assertIsInstance(row["has_outrights"], bool)
                self.assertTrue(row["key"].startswith("tennis_"))


if __name__ == "__main__":
    unittest.main()
