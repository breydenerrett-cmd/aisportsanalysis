"""src/appstate/users.py: invite-token auth, stdlib sqlite3.

Every test points APP_DB_PATH at a fresh tmp file (via the `db=` kwarg,
which every users.py function accepts) so tests never touch the real
data/app/app.db and never interfere with each other.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.appstate import users


class UserStoreTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_create_user_defaults_to_invited_and_none_plan(self):
        user = users.create_user("brey@example.com", db=self.db)
        self.assertEqual(user.status, "invited")
        self.assertEqual(user.plan, "none")
        self.assertEqual(user.email, "brey@example.com")

    def test_email_is_normalized_lowercase_and_stripped(self):
        user = users.create_user("  Brey@Example.com  ", db=self.db)
        self.assertEqual(user.email, "brey@example.com")

    def test_duplicate_email_raises(self):
        users.create_user("a@example.com", db=self.db)
        with self.assertRaises(ValueError):
            users.create_user("a@example.com", db=self.db)

    def test_unknown_status_or_plan_raises(self):
        with self.assertRaises(ValueError):
            users.create_user("b@example.com", status="bogus", db=self.db)
        with self.assertRaises(ValueError):
            users.create_user("c@example.com", plan="bogus", db=self.db)

    def test_get_user_and_get_user_by_email_roundtrip(self):
        created = users.create_user("d@example.com", db=self.db)
        self.assertEqual(users.get_user(created.id, db=self.db), created)
        self.assertEqual(users.get_user_by_email("d@example.com", db=self.db), created)
        self.assertIsNone(users.get_user(999999, db=self.db))

    def test_set_status_and_plan(self):
        user = users.create_user("e@example.com", db=self.db)
        users.set_user_status(user.id, "active", db=self.db)
        users.set_user_plan(user.id, "beta", db=self.db)
        updated = users.get_user(user.id, db=self.db)
        self.assertEqual(updated.status, "active")
        self.assertEqual(updated.plan, "beta")

    def test_raw_token_is_never_stored_only_its_hash(self):
        """The core security property: reading every row of the tokens
        table must never yield a value the raw token equals -- only its
        sha256 hash. This is what makes a database dump harmless."""
        user = users.create_user("f@example.com", db=self.db)
        raw_token = users.issue_invite_token(user.id, db=self.db)

        conn = sqlite3.connect(str(self.db))
        rows = conn.execute("SELECT token_hash FROM tokens").fetchall()
        conn.close()

        self.assertEqual(len(rows), 1)
        stored_hash = rows[0][0]
        self.assertNotEqual(stored_hash, raw_token)
        self.assertEqual(len(stored_hash), 64)  # sha256 hex digest length
        self.assertEqual(stored_hash, users._hash_token(raw_token))

    def test_authenticate_resolves_a_fresh_token_to_its_user(self):
        user = users.create_user("g@example.com", db=self.db)
        raw_token = users.issue_invite_token(user.id, db=self.db)
        resolved = users.authenticate(raw_token, db=self.db)
        self.assertEqual(resolved, user)

    def test_authenticate_rejects_unknown_token(self):
        self.assertIsNone(users.authenticate("not-a-real-token", db=self.db))

    def test_authenticate_rejects_expired_token(self):
        """Expiry proven with an injected clock -- no sleeping in tests."""
        user = users.create_user("h@example.com", db=self.db)
        raw_token = users.issue_invite_token(
            user.id, ttl=timedelta(seconds=1), db=self.db)
        past_expiry = datetime.now(timezone.utc) + timedelta(days=1)
        self.assertIsNone(users.authenticate(raw_token, db=self.db, now=past_expiry))
        # Still valid right at issuance, proving the token itself was good.
        self.assertIsNotNone(users.authenticate(raw_token, db=self.db))

    def test_authenticate_rejects_revoked_token(self):
        user = users.create_user("i@example.com", db=self.db)
        raw_token = users.issue_invite_token(user.id, db=self.db)
        self.assertIsNotNone(users.authenticate(raw_token, db=self.db))
        revoked = users.revoke_token(raw_token, db=self.db)
        self.assertTrue(revoked)
        self.assertIsNone(users.authenticate(raw_token, db=self.db))

    def test_revoke_is_not_idempotent_signal_but_safe_to_call_twice(self):
        user = users.create_user("j@example.com", db=self.db)
        raw_token = users.issue_invite_token(user.id, db=self.db)
        self.assertTrue(users.revoke_token(raw_token, db=self.db))
        # Second revoke of an already-revoked token: no matching row to
        # flip, so it reports False rather than silently succeeding twice.
        self.assertFalse(users.revoke_token(raw_token, db=self.db))

    def test_two_tokens_for_the_same_user_are_independent(self):
        user = users.create_user("k@example.com", db=self.db)
        token_a = users.issue_invite_token(user.id, db=self.db)
        token_b = users.issue_invite_token(user.id, db=self.db)
        users.revoke_token(token_a, db=self.db)
        self.assertIsNone(users.authenticate(token_a, db=self.db))
        self.assertIsNotNone(users.authenticate(token_b, db=self.db))

    def test_mark_token_first_used_true_on_first_call_false_after(self):
        user = users.create_user("firstuse@example.com", db=self.db)
        raw_token = users.issue_invite_token(user.id, db=self.db)
        self.assertTrue(users.mark_token_first_used(raw_token, db=self.db))
        # Second call on the same token: already marked, no transition to
        # report, and no overwrite of the timestamp that was already set.
        self.assertFalse(users.mark_token_first_used(raw_token, db=self.db))

    def test_mark_token_first_used_persists_the_timestamp(self):
        user = users.create_user("persist@example.com", db=self.db)
        raw_token = users.issue_invite_token(user.id, db=self.db)
        users.mark_token_first_used(raw_token, at="2026-08-31T12:00:00+00:00",
                                    db=self.db)
        conn = sqlite3.connect(str(self.db))
        row = conn.execute(
            "SELECT first_used_at FROM tokens WHERE token_hash = ?",
            (users._hash_token(raw_token),)).fetchone()
        conn.close()
        self.assertEqual(row[0], "2026-08-31T12:00:00+00:00")

    def test_mark_token_first_used_is_a_harmless_no_op_on_unknown_token(self):
        """A token that never authenticated (unknown hash, or a hash from a
        different auth provider) must not raise or fabricate a match."""
        self.assertFalse(
            users.mark_token_first_used("not-a-real-token", db=self.db))

    def test_first_used_at_column_is_added_to_a_pre_existing_db(self):
        """MIGRATION SAFETY: a tokens table that predates first_used_at (no
        column at all) must gain it on the next connect, exactly the
        upgrade path a real deployed app.db goes through -- see
        src/appstate/savedbets.py's identical settlement-columns test for
        the pattern this mirrors."""
        conn = sqlite3.connect(str(self.db))
        conn.execute("""
            CREATE TABLE tokens (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                plan TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

        user = users.create_user("old-db@example.com", db=self.db)
        raw_token = users.issue_invite_token(user.id, db=self.db)
        # The pre-existing row (issued before the migration ran, in a real
        # upgrade) has no first_used_at value -- a fresh connect must not
        # error out, and the column must now exist and be usable.
        self.assertTrue(users.mark_token_first_used(raw_token, db=self.db))
        self.assertFalse(users.mark_token_first_used(raw_token, db=self.db))

    def test_db_path_defaults_to_data_app_app_db_under_repo_root(self):
        from src import paths
        expected = paths.repo_root() / "data" / "app" / "app.db"
        self.assertEqual(users.db_path(), expected)


if __name__ == "__main__":
    unittest.main()
