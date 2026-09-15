"""Tests for api/live.py"""

import unittest
from datetime import datetime, timezone

try:
    from api.app import app
    _HAVE_FASTAPI = True
except Exception:  # noqa: BLE001
    _HAVE_FASTAPI = False


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class LiveAPIRequiresAuth(unittest.TestCase):
    """GET /live requires a bearer token."""

    def _status(self, path):
        import asyncio

        captured = {}

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            if message["type"] == "http.response.start":
                captured["status"] = message["status"]

        # Split path and query_string
        if "?" in path:
            path_part, query_part = path.split("?", 1)
            query_string = query_part.encode()
        else:
            path_part = path
            query_string = b""

        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "GET", "scheme": "http", "path": path_part, "raw_path": path_part.encode(),
            "query_string": query_string, "root_path": "", "headers": [(b"host", b"test")],
            "client": ("test", 1), "server": ("test", 80),
        }
        asyncio.new_event_loop().run_until_complete(app(scope, receive, send))
        return captured.get("status")

    def test_live_without_token_is_401(self):
        self.assertEqual(401, self._status("/live"))

    def test_live_with_sport_without_token_is_401(self):
        self.assertEqual(401, self._status("/live?sport=nfl"))


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class LiveAPIContract(unittest.TestCase):
    """GET /live returns the correct contract shape."""

    def test_live_mlb_returns_contract_keys(self):
        """GET /live?sport=mlb returns the correct keys."""
        from api import live
        from unittest.mock import patch

        # Mock the state readers and candidates
        mock_states_mlb = {
            "game1": {
                "game_pk": "game1",
                "home_team": "Yankees",
                "away_team": "Red Sox",
                "inning": 6,
                "half": "top",
                "home_runs": 3,
                "away_runs": 2,
                "status": "Live",
                "observed_utc": "2026-09-14T20:30:00Z",
            }
        }

        mock_candidates = [
            {
                "rule_id": "favorite_behind_early",
                "sport": "mlb",
                "game_id": "game1",
                "bet": "Yankees to win",
                "price": -110,
                "observed_utc": "2026-09-14T20:28:00Z",
                "recorded_utc": "2026-09-14T20:28:00Z",
            }
        ]

        with patch.object(
            live, "_get_livefeed_mlb_latest_states", return_value=mock_states_mlb
        ):
            with patch.object(
                live, "_get_livefeed_nfl_latest_states", return_value={}
            ):
                with patch.object(
                    live, "_get_live_ledger_candidates", return_value=mock_candidates
                ):
                    result = live.get_live(sport="mlb")

        # Check contract keys
        self.assertIn("sport", result)
        self.assertIn("generated_utc", result)
        self.assertIn("notice", result)
        self.assertIn("poller", result)
        self.assertIn("games", result)
        self.assertIn("candidates", result)

        # Check poller keys
        self.assertIn("last_observed_utc", result["poller"])
        self.assertIn("fresh", result["poller"])
        self.assertIn("status", result["poller"])

        # Check sport
        self.assertEqual("mlb", result["sport"])

        # Check notice
        self.assertIn("internal testing", result["notice"].lower())

    def test_live_nfl_returns_contract_keys(self):
        """GET /live?sport=nfl returns the correct keys."""
        from api import live
        from unittest.mock import patch

        mock_states_nfl = {
            "event1": {
                "event_id": "event1",
                "home_team": "Buffalo Bills",
                "away_team": "Miami Dolphins",
                "home_score": 14,
                "away_score": 10,
                "quarter": 2,
                "completed": False,
                "status": "In Play",
                "observed_utc": "2026-09-14T21:00:00Z",
            }
        }

        mock_candidates = []

        with patch.object(
            live, "_get_livefeed_mlb_latest_states", return_value={}
        ):
            with patch.object(
                live, "_get_livefeed_nfl_latest_states", return_value=mock_states_nfl
            ):
                with patch.object(
                    live, "_get_live_ledger_candidates", return_value=mock_candidates
                ):
                    result = live.get_live(sport="nfl")

        self.assertEqual("nfl", result["sport"])

    def test_invalid_sport_returns_400(self):
        """GET /live?sport=cricket returns 400."""
        from api import live
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            live.get_live(sport="cricket")

        self.assertEqual(400, ctx.exception.status_code)

    def test_status_is_live_when_40_seconds_old_mlb(self):
        """Status is 'live' when observed_utc is 40 seconds old (MLB)."""
        from api import live
        from unittest.mock import patch
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        forty_secs_ago = now - timedelta(seconds=40)

        mock_states = {
            "game1": {
                "game_pk": "game1",
                "home_team": "Yankees",
                "away_team": "Red Sox",
                "inning": 3,
                "half": "top",
                "home_runs": 0,
                "away_runs": 1,
                "status": "Live",
                "observed_utc": forty_secs_ago.isoformat(),
            }
        }

        with patch.object(
            live, "_get_livefeed_mlb_latest_states", return_value=mock_states
        ):
            with patch.object(
                live, "_get_livefeed_nfl_latest_states", return_value={}
            ):
                with patch.object(
                    live, "_get_live_ledger_candidates", return_value=[]
                ):
                    result = live.get_live(sport="mlb")

        self.assertEqual("live", result["poller"]["status"])

    def test_status_is_stale_when_20_minutes_old_mlb(self):
        """Status is 'stale' when observed_utc is 20 minutes old (MLB)."""
        from api import live
        from unittest.mock import patch
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        twenty_mins_ago = now - timedelta(minutes=20)

        mock_states = {
            "game1": {
                "game_pk": "game1",
                "home_team": "Yankees",
                "away_team": "Red Sox",
                "inning": 3,
                "half": "top",
                "home_runs": 0,
                "away_runs": 1,
                "status": "Live",
                "observed_utc": twenty_mins_ago.isoformat(),
            }
        }

        with patch.object(
            live, "_get_livefeed_mlb_latest_states", return_value=mock_states
        ):
            with patch.object(
                live, "_get_livefeed_nfl_latest_states", return_value={}
            ):
                with patch.object(
                    live, "_get_live_ledger_candidates", return_value=[]
                ):
                    result = live.get_live(sport="mlb")

        self.assertEqual("stale", result["poller"]["status"])

    def test_status_is_idle_when_no_rows(self):
        """Status is 'idle' when there are no game states."""
        from api import live
        from unittest.mock import patch

        with patch.object(
            live, "_get_livefeed_mlb_latest_states", return_value={}
        ):
            with patch.object(
                live, "_get_livefeed_nfl_latest_states", return_value={}
            ):
                with patch.object(
                    live, "_get_live_ledger_candidates", return_value=[]
                ):
                    result = live.get_live(sport="mlb")

        self.assertEqual("idle", result["poller"]["status"])

    def test_status_is_live_when_5_minutes_old_nfl(self):
        """Status is 'live' when observed_utc is 5 minutes old (NFL, 10 min threshold)."""
        from api import live
        from unittest.mock import patch
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        five_mins_ago = now - timedelta(minutes=5)

        mock_states = {
            "event1": {
                "event_id": "event1",
                "home_team": "Buffalo Bills",
                "away_team": "Miami Dolphins",
                "home_score": 14,
                "away_score": 10,
                "quarter": 2,
                "completed": False,
                "status": "In Play",
                "observed_utc": five_mins_ago.isoformat(),
            }
        }

        with patch.object(
            live, "_get_livefeed_mlb_latest_states", return_value={}
        ):
            with patch.object(
                live, "_get_livefeed_nfl_latest_states", return_value=mock_states
            ):
                with patch.object(
                    live, "_get_live_ledger_candidates", return_value=[]
                ):
                    result = live.get_live(sport="nfl")

        self.assertEqual("live", result["poller"]["status"])

    def test_status_is_stale_when_15_minutes_old_nfl(self):
        """Status is 'stale' when observed_utc is 15 minutes old (NFL, 10 min threshold)."""
        from api import live
        from unittest.mock import patch
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        fifteen_mins_ago = now - timedelta(minutes=15)

        mock_states = {
            "event1": {
                "event_id": "event1",
                "home_team": "Buffalo Bills",
                "away_team": "Miami Dolphins",
                "home_score": 14,
                "away_score": 10,
                "quarter": 2,
                "completed": False,
                "status": "In Play",
                "observed_utc": fifteen_mins_ago.isoformat(),
            }
        }

        with patch.object(
            live, "_get_livefeed_mlb_latest_states", return_value={}
        ):
            with patch.object(
                live, "_get_livefeed_nfl_latest_states", return_value=mock_states
            ):
                with patch.object(
                    live, "_get_live_ledger_candidates", return_value=[]
                ):
                    result = live.get_live(sport="nfl")

        self.assertEqual("stale", result["poller"]["status"])


if __name__ == "__main__":
    unittest.main()
