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

    def test_new_bet_has_null_settlement_fields(self):
        bet = savedbets.save_bet(1, "BOS@NYY", "BOS ML", db=self.db)
        self.assertIsNone(bet.settlement_status)
        self.assertFalse(bet.is_settled)
        rows = savedbets.list_bets(1, db=self.db)
        self.assertIsNone(rows[0].settlement_status)

    def test_existing_db_without_settlement_columns_still_opens(self):
        """The migration-safe ALTER: a db written before settlement existed
        (no settlement_status/reason/settled_at columns) must not break on
        the next connect -- it gets the columns added in place, not a
        rebuilt table, so pre-existing rows survive untouched."""
        import sqlite3
        conn = sqlite3.connect(str(self.db))
        conn.execute("""
            CREATE TABLE saved_bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                game TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL,
                saved_at TEXT NOT NULL,
                snapshot_digest TEXT,
                deleted_at TEXT
            )
        """)
        conn.execute(
            "INSERT INTO saved_bets (user_id, game, side, saved_at) "
            "VALUES (1, 'BOS@NYY', 'BOS ML', '2026-04-01T00:00:00+00:00')")
        conn.commit()
        conn.close()

        rows = savedbets.list_bets(1, db=self.db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].game, "BOS@NYY")
        self.assertIsNone(rows[0].settlement_status)

        # And the migration is safe to run again on the same (now-upgraded) db.
        savedbets.save_bet(1, "LAD@SF", "SF ML", db=self.db)
        self.assertEqual(len(savedbets.list_bets(1, db=self.db)), 2)

    def test_mark_settled_and_list_unsettled(self):
        bet = savedbets.save_bet(1, "BOS@NYY", "BOS ML", db=self.db)
        savedbets.save_bet(2, "LAD@SF", "SF ML", db=self.db)
        self.assertEqual(len(savedbets.list_unsettled_bets(db=self.db)), 2)

        marked = savedbets.mark_settled(bet.id, "won", reason=None,
                                        settled_at="2026-04-02T00:00:00+00:00",
                                        db=self.db)
        self.assertTrue(marked)
        remaining = savedbets.list_unsettled_bets(db=self.db)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].game, "LAD@SF")

        settled_row = savedbets.list_bets(1, db=self.db)[0]
        self.assertEqual(settled_row.settlement_status, "won")
        self.assertEqual(settled_row.settled_at, "2026-04-02T00:00:00+00:00")

    def test_mark_settled_never_overwrites_an_existing_verdict(self):
        """Append-only rule extended to settlement: a bet already settled
        stays exactly as first settled -- mark_settled's WHERE clause makes
        a second call a no-op, not a silent overwrite."""
        bet = savedbets.save_bet(1, "BOS@NYY", "BOS ML", db=self.db)
        savedbets.mark_settled(bet.id, "won", db=self.db)
        second = savedbets.mark_settled(bet.id, "lost", db=self.db)
        self.assertFalse(second)
        self.assertEqual(
            savedbets.list_bets(1, db=self.db)[0].settlement_status, "won")

    def test_mark_settled_rejects_unknown_status(self):
        bet = savedbets.save_bet(1, "BOS@NYY", "BOS ML", db=self.db)
        with self.assertRaises(ValueError):
            savedbets.mark_settled(bet.id, "cancelled", db=self.db)

    def test_soft_deleted_bet_excluded_from_unsettled_sweep(self):
        bet = savedbets.save_bet(1, "BOS@NYY", "BOS ML", db=self.db)
        savedbets.delete_bet(bet.id, 1, db=self.db)
        self.assertEqual(savedbets.list_unsettled_bets(db=self.db), [])

    def test_no_update_function_exists(self):
        """Pinning the append-only design: there is no update_bet in this
        module. If someone adds one, this test names the decision it
        overturns and forces a conscious removal, not an accidental one."""
        self.assertFalse(hasattr(savedbets, "update_bet"))


if __name__ == "__main__":
    unittest.main()
