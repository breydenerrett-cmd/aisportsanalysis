"""src/appstate/savedbets.py: append-only saved bets, soft-delete."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.appstate import savedbets


class SavedBetsTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_and_list_roundtrip(self):
        bet = savedbets.save_bet(
            1, "BOS@NYY", "BOS ML", price=120, snapshot_digest="abc123", db=self.db)
        self.assertIsNotNone(bet.id)
        rows = savedbets.list_bets(1, db=self.db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].game, "BOS@NYY")
        self.assertEqual(rows[0].snapshot_digest, "abc123")
        self.assertFalse(rows[0].is_deleted)

    def test_missing_game_or_side_raises(self):
        with self.assertRaises(ValueError):
            savedbets.save_bet(1, "", "BOS ML", db=self.db)
        with self.assertRaises(ValueError):
            savedbets.save_bet(1, "BOS@NYY", "", db=self.db)

    def test_list_is_scoped_per_user(self):
        savedbets.save_bet(1, "BOS@NYY", "BOS ML", db=self.db)
        savedbets.save_bet(2, "LAD@SF", "SF ML", db=self.db)
        self.assertEqual(len(savedbets.list_bets(1, db=self.db)), 1)
        self.assertEqual(len(savedbets.list_bets(2, db=self.db)), 1)

    def test_list_is_newest_first(self):
        savedbets.save_bet(1, "GAME1", "A", db=self.db)
        savedbets.save_bet(1, "GAME2", "B", db=self.db)
        rows = savedbets.list_bets(1, db=self.db)
        self.assertEqual([r.game for r in rows], ["GAME2", "GAME1"])

    def test_delete_is_soft_and_hides_from_default_listing(self):
        bet = savedbets.save_bet(1, "BOS@NYY", "BOS ML", db=self.db)
        deleted = savedbets.delete_bet(bet.id, 1, db=self.db)
        self.assertTrue(deleted)
        self.assertEqual(savedbets.list_bets(1, db=self.db), [])
        with_deleted = savedbets.list_bets(1, include_deleted=True, db=self.db)
        self.assertEqual(len(with_deleted), 1)
        self.assertTrue(with_deleted[0].is_deleted)

    def test_delete_is_scoped_to_owning_user(self):
        """A user can never delete another user's saved bet, even knowing
        its id -- delete_bet is a no-op (returns False) across users."""
        bet = savedbets.save_bet(1, "BOS@NYY", "BOS ML", db=self.db)
        deleted = savedbets.delete_bet(bet.id, 2, db=self.db)
        self.assertFalse(deleted)
        self.assertEqual(len(savedbets.list_bets(1, db=self.db)), 1)

    def test_delete_unknown_bet_returns_false(self):
        self.assertFalse(savedbets.delete_bet(999999, 1, db=self.db))

    def test_no_update_function_exists(self):
        """Pinning the append-only design: there is no update_bet in this
        module. If someone adds one, this test names the decision it
        overturns and forces a conscious removal, not an accidental one."""
        self.assertFalse(hasattr(savedbets, "update_bet"))


if __name__ == "__main__":
    unittest.main()
