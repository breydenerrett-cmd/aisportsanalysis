"""Tests for api/live.py"""

import os
import unittest
from datetime import datetime, timezone
from unittest import mock

# NO NETWORK FROM THIS MODULE. /live also reads the live rows the runner
# pushes to GitHub (src/pipeline/live_remote.py), and that read is on by
# default. The tests that exercise it patch the reader; every other test
# would otherwise make a real request to raw.githubusercontent.com on every
# run (it did, and passed by getting a 404). "off" makes the remote reader
# return nothing before it builds a URL.
_ENV_PATCH = mock.patch.dict(os.environ, {"LIVE_REMOTE_BASE": "off"})


def setUpModule():
    _ENV_PATCH.start()


def tearDownModule():
    _ENV_PATCH.stop()

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


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class LiveAPIRemoteMerging(unittest.TestCase):
    """Remote data is merged with local data when enabled."""

    def test_local_empty_remote_has_fresh_row(self):
        """Local empty + remote 40sec old -> games has one entry with source 'remote'."""
        from api import live
        from unittest.mock import patch
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        forty_secs_ago = now - timedelta(seconds=40)

        mock_remote_row = {
            "game_pk": "game1",
            "home_team": "Yankees",
            "away_team": "Red Sox",
            "inning": 3,
            "half": "top",
            "home_runs": 1,
            "away_runs": 0,
            "status": "Live",
            "observed_utc": forty_secs_ago.isoformat(),
        }

        with patch.object(
            live, "_get_livefeed_mlb_latest_states", return_value={}
        ):
            with patch.object(
                live, "_get_livefeed_nfl_latest_states", return_value={}
            ):
                with patch.object(
                    live, "_get_live_ledger_candidates", return_value=[]
                ):
                    with patch.object(
                        live, "_remote_state_rows", return_value=[mock_remote_row]
                    ):
                        with patch.object(
                            live, "_remote_candidate_rows", return_value=[]
                        ):
                            with patch("src.pipeline.live_remote.enabled", return_value=True):
                                result = live.get_live(sport="mlb")

        self.assertEqual(1, len(result["games"]))
        self.assertEqual("Yankees", result["games"][0]["home_team"])
        self.assertEqual("remote", result["games"][0]["source"])
        self.assertEqual("live", result["poller"]["status"])
        self.assertEqual("remote", result["poller"]["source"])

    def test_local_newer_than_remote_for_same_game(self):
        """Local newer than remote for same game -> local row wins with source 'merged'."""
        from api import live
        from unittest.mock import patch
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        ten_secs_ago = now - timedelta(seconds=10)
        forty_secs_ago = now - timedelta(seconds=40)

        local_row = {
            "game_pk": "game1",
            "home_team": "Yankees",
            "away_team": "Red Sox",
            "inning": 4,
            "half": "bottom",
            "home_runs": 2,
            "away_runs": 1,
            "status": "Live",
            "observed_utc": ten_secs_ago.isoformat(),
        }

        remote_row = {
            "game_pk": "game1",
            "home_team": "Yankees",
            "away_team": "Red Sox",
            "inning": 3,
            "half": "top",
            "home_runs": 1,
            "away_runs": 0,
            "status": "Live",
            "observed_utc": forty_secs_ago.isoformat(),
        }

        with patch.object(
            live, "_get_livefeed_mlb_latest_states", return_value={"game1": local_row}
        ):
            with patch.object(
                live, "_get_livefeed_nfl_latest_states", return_value={}
            ):
                with patch.object(
                    live, "_get_live_ledger_candidates", return_value=[]
                ):
                    with patch.object(
                        live, "_remote_state_rows", return_value=[remote_row]
                    ):
                        with patch.object(
                            live, "_remote_candidate_rows", return_value=[]
                        ):
                            with patch("src.pipeline.live_remote.enabled", return_value=True):
                                result = live.get_live(sport="mlb")

        self.assertEqual(1, len(result["games"]))
        # Local row should win (it's newer)
        game = result["games"][0]
        self.assertIn("bottom of the 4", game.get("inning", ""))
        self.assertEqual("merged", game["source"])

    def test_remote_failure_returns_200_with_local_data(self):
        """Remote raising -> response is still 200 with local data only."""
        from api import live
        from unittest.mock import patch
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        forty_secs_ago = now - timedelta(seconds=40)

        local_row = {
            "game_pk": "game1",
            "home_team": "Yankees",
            "away_team": "Red Sox",
            "inning": 3,
            "half": "top",
            "home_runs": 1,
            "away_runs": 0,
            "status": "Live",
            "observed_utc": forty_secs_ago.isoformat(),
        }

        with patch.object(
            live, "_get_livefeed_mlb_latest_states", return_value={"game1": local_row}
        ):
            with patch.object(
                live, "_get_livefeed_nfl_latest_states", return_value={}
            ):
                with patch.object(
                    live, "_get_live_ledger_candidates", return_value=[]
                ):
                    with patch.object(
                        live, "_remote_state_rows", side_effect=Exception("network error")
                    ):
                        with patch.object(
                            live, "_remote_candidate_rows", return_value=[]
                        ):
                            with patch("src.pipeline.live_remote.enabled", return_value=True):
                                result = live.get_live(sport="mlb")

        # Should succeed despite remote error
        self.assertEqual(1, len(result["games"]))
        self.assertEqual("Yankees", result["games"][0]["home_team"])
        self.assertEqual("local", result["games"][0]["source"])

    def test_remote_disabled_ignores_remote_data(self):
        """When remote is disabled, only local data is returned."""
        from api import live
        from unittest.mock import patch
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        forty_secs_ago = now - timedelta(seconds=40)

        local_row = {
            "game_pk": "game1",
            "home_team": "Yankees",
            "away_team": "Red Sox",
            "inning": 3,
            "half": "top",
            "home_runs": 1,
            "away_runs": 0,
            "status": "Live",
            "observed_utc": forty_secs_ago.isoformat(),
        }

        remote_row = {
            "game_pk": "game2",
            "home_team": "Mets",
            "away_team": "Braves",
            "inning": 2,
            "half": "bottom",
            "home_runs": 0,
            "away_runs": 0,
            "status": "Live",
            "observed_utc": forty_secs_ago.isoformat(),
        }

        with patch.object(
            live, "_get_livefeed_mlb_latest_states", return_value={"game1": local_row}
        ):
            with patch.object(
                live, "_get_livefeed_nfl_latest_states", return_value={}
            ):
                with patch.object(
                    live, "_get_live_ledger_candidates", return_value=[]
                ):
                    with patch.object(
                        live, "_remote_state_rows", return_value=[remote_row]
                    ):
                        with patch.object(
                            live, "_remote_candidate_rows", return_value=[]
                        ):
                            with patch("src.pipeline.live_remote.enabled", return_value=False):
                                result = live.get_live(sport="mlb")

        # Only local game should be present (remote is disabled)
        self.assertEqual(1, len(result["games"]))
        self.assertEqual("Yankees", result["games"][0]["home_team"])


if __name__ == "__main__":
    unittest.main()
