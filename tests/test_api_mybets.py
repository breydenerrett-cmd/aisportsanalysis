"""api/mybets.py: GET/POST/DELETE for the authed user's saved bets.

Skip-if-no-fastapi (see tests/test_api_auth.py's module docstring for why
there is no TestClient/HTTP layer here). Route functions are called
directly with a real User (from src.appstate.users) standing in for what
FastAPI's Depends(get_current_user) would have resolved.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.appstate import savedbets as savedbets_store
from src.appstate import users as users_store


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class MyBetsRouteTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._patcher = mock.patch.object(savedbets_store, "db_path", lambda: self.db)
        self._patcher.start()
        self.user = users_store.create_user("betuser@example.com", db=self.db)

    def tearDown(self):
        self._patcher.stop()
        self._tmp.cleanup()

    def test_list_is_empty_for_a_new_user(self):
        from api.mybets import list_my_bets
        result = list_my_bets(current_user=self.user)
        self.assertEqual(result, {"bets": []})

    def test_post_then_get_roundtrip(self):
        from api.mybets import SaveBetRequest, create_my_bet, list_my_bets
        created = create_my_bet(
            SaveBetRequest(game="BOS@NYY", side="BOS ML", price=120,
                           snapshot_digest="deadbeef"),
            current_user=self.user)
        self.assertEqual(created["game"], "BOS@NYY")
        self.assertIn("id", created)

        listed = list_my_bets(current_user=self.user)
        self.assertEqual(len(listed["bets"]), 1)
        self.assertEqual(listed["bets"][0]["id"], created["id"])
        self.assertEqual(listed["bets"][0]["snapshot_digest"], "deadbeef")

    def test_delete_then_it_no_longer_lists(self):
        from api.mybets import SaveBetRequest, create_my_bet, delete_my_bet, list_my_bets
        created = create_my_bet(
            SaveBetRequest(game="BOS@NYY", side="BOS ML"), current_user=self.user)
        result = delete_my_bet(created["id"], current_user=self.user)
        self.assertEqual(result, {"deleted": True, "id": created["id"]})
        self.assertEqual(list_my_bets(current_user=self.user)["bets"], [])

    def test_delete_unknown_bet_is_404(self):
        from fastapi import HTTPException
        from api.mybets import delete_my_bet
        with self.assertRaises(HTTPException) as ctx:
            delete_my_bet(999999, current_user=self.user)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_one_user_cannot_delete_anothers_bet(self):
        from fastapi import HTTPException
        from api.mybets import SaveBetRequest, create_my_bet, delete_my_bet
        other = users_store.create_user("other@example.com", db=self.db)
        created = create_my_bet(
            SaveBetRequest(game="BOS@NYY", side="BOS ML"), current_user=self.user)
        with self.assertRaises(HTTPException) as ctx:
            delete_my_bet(created["id"], current_user=other)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_one_user_cannot_see_anothers_bets(self):
        from api.mybets import SaveBetRequest, create_my_bet, list_my_bets
        other = users_store.create_user("other2@example.com", db=self.db)
        create_my_bet(SaveBetRequest(game="BOS@NYY", side="BOS ML"),
                       current_user=self.user)
        self.assertEqual(list_my_bets(current_user=other)["bets"], [])


if __name__ == "__main__":
    unittest.main()
