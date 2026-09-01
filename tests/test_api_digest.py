"""api/digest.py: GET /digest, with the network call stubbed out.

Same skip-if-no-fastapi and direct-call pattern as tests/test_api_games.py
and tests/test_api_mybets.py: no TestClient, the route function is called
directly with a real User standing in for what Depends(get_current_user)
would resolve, and the one network call (mlb.fetch_games) is patched to a
fixed offline schedule.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.appstate import events, savedbets as savedbets_store
from src.appstate import users as users_store
from src.providers import mlb


def _schedule(today=None):
    today = today or date.today().isoformat()
    return [{
        "game_pk": 990101, "date": today, "away_team": "BOS", "home_team": "NYY",
        "venue": "Yankee Stadium", "start_time_utc": f"{today}T23:05:00Z",
    }]


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class DigestRouteTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._patchers = [
            mock.patch.object(savedbets_store, "db_path", lambda: self.db),
            mock.patch.object(events, "db_path", lambda: self.db),
        ]
        for p in self._patchers:
            p.start()
        self.user = users_store.create_user("digestuser@example.com", db=self.db)

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        self._tmp.cleanup()

    def test_returns_the_real_digest_shape(self):
        from api.digest import get_digest
        with mock.patch.object(mlb, "fetch_games", return_value=_schedule()):
            payload = get_digest(current_user=self.user)
        blob = json.loads(json.dumps(payload))  # JSON-serialisable end to end
        self.assertEqual(blob["user_id"], self.user.id)
        self.assertEqual(blob["slate"]["checked_games"], 1)
        self.assertIsNone(blob["since_last_digest"])
        self.assertEqual(blob["settled_bets"], [])
        self.assertIn("what_changed", blob)
        self.assertIn("price_improvement", blob)

    def test_records_digest_viewed_event(self):
        from api.digest import get_digest
        with mock.patch.object(mlb, "fetch_games", return_value=_schedule()):
            get_digest(current_user=self.user)
        recorded = events.list_events(db=self.db)
        kinds = [e.kind for e in recorded]
        self.assertIn(events.DIGEST_VIEWED, kinds)

    def test_second_call_sees_the_first_calls_timestamp_as_since(self):
        from api.digest import get_digest
        with mock.patch.object(mlb, "fetch_games", return_value=_schedule()):
            first = get_digest(current_user=self.user)
            second = get_digest(current_user=self.user)
        self.assertIsNone(first["since_last_digest"])
        self.assertEqual(second["since_last_digest"], first["generated_at"])

    def test_settled_bet_since_last_digest_is_reported_once(self):
        from api.digest import get_digest
        bet = savedbets_store.save_bet(self.user.id, "BOS@NYY", "BOS ML",
                                       db=self.db)
        savedbets_store.mark_settled(bet.id, "won", db=self.db)
        with mock.patch.object(mlb, "fetch_games", return_value=_schedule()):
            first = get_digest(current_user=self.user)
            second = get_digest(current_user=self.user)
        self.assertEqual(len(first["settled_bets"]), 1)
        self.assertEqual(first["settled_bets"][0]["id"], bet.id)
        # The bet settled before the second digest's own "since" cutoff (it
        # was already reported in the first digest), so it must not repeat.
        self.assertEqual(second["settled_bets"], [])

    def test_schedule_provider_failure_is_a_502(self):
        from fastapi import HTTPException
        from api.digest import get_digest
        with mock.patch.object(mlb, "fetch_games",
                               side_effect=mlb.MLBError("boom")):
            with self.assertRaises(HTTPException) as ctx:
                get_digest(current_user=self.user)
        self.assertEqual(ctx.exception.status_code, 502)


if __name__ == "__main__":
    unittest.main()
