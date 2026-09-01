"""src/appstate/freechecks.py: the lifetime free Bet Check budget.

The store half of the landing page's "3 introductory Bet Checks, no card
required" offer. Every test here is about the property that makes that
offer honest rather than decorative: the count lives on the SERVER, keyed
on a token the server minted, and survives the process.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.appstate import freechecks
from src.appstate import users as users_store


class FreeCheckGrantTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        patcher = mock.patch.object(users_store, "db_path", lambda: self.db)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def test_a_fresh_grant_has_the_whole_lifetime_budget(self):
        raw, grant = freechecks.issue_grant()
        self.assertTrue(raw)
        self.assertEqual(grant.checks_used, 0)
        self.assertEqual(grant.remaining, freechecks.FREE_CHECK_LIFETIME_LIMIT)
        self.assertFalse(grant.exhausted)

    def test_the_raw_token_is_never_stored(self):
        """Same rule src/appstate/users.py applies to bearer tokens: a
        dump of this table must not hand anyone a working credential."""
        raw, grant = freechecks.issue_grant()
        self.assertNotEqual(raw, grant.token_hash)
        self.assertEqual(grant.token_hash, freechecks.hash_token(raw))
        import sqlite3
        conn = sqlite3.connect(str(self.db))
        blob = " ".join(str(r) for r in
                        conn.execute("SELECT * FROM free_check_grants"))
        conn.close()
        self.assertNotIn(raw, blob)

    def test_two_grants_are_different_identities(self):
        raw_a, _ = freechecks.issue_grant()
        raw_b, _ = freechecks.issue_grant()
        self.assertNotEqual(raw_a, raw_b)
        freechecks.consume_check(raw_a)
        self.assertEqual(freechecks.get_grant(raw_a).checks_used, 1)
        self.assertEqual(freechecks.get_grant(raw_b).checks_used, 0)

    def test_exactly_three_checks_then_the_budget_is_gone(self):
        raw, _ = freechecks.issue_grant()
        for expected_used in (1, 2, 3):
            grant = freechecks.consume_check(raw)
            self.assertIsNotNone(grant)
            self.assertEqual(grant.checks_used, expected_used)
        self.assertIsNone(freechecks.consume_check(raw))
        self.assertTrue(freechecks.get_grant(raw).exhausted)
        self.assertEqual(freechecks.get_grant(raw).remaining, 0)

    def test_a_spent_budget_stays_spent_across_a_new_connection(self):
        """The restart test. Every read/write here opens its own
        connection, so the only thing carrying the count between them is
        the file on disk -- which is the whole reason this is a table and
        not an in-process dict."""
        raw, _ = freechecks.issue_grant()
        for _ in range(freechecks.FREE_CHECK_LIFETIME_LIMIT):
            freechecks.consume_check(raw)
        # Nothing cached: a fresh lookup against the same file sees it.
        self.assertTrue(freechecks.get_grant(raw).exhausted)
        self.assertIsNone(freechecks.consume_check(raw))

    def test_an_unknown_or_tampered_token_is_simply_not_an_identity(self):
        raw, _ = freechecks.issue_grant()
        freechecks.consume_check(raw)
        tampered = raw[:-1] + ("A" if raw[-1] != "A" else "B")
        self.assertIsNone(freechecks.get_grant(tampered))
        self.assertIsNone(freechecks.get_grant("forged-token"))
        self.assertIsNone(freechecks.get_grant(""))
        self.assertIsNone(freechecks.get_grant(None))
        # ...and it can never spend the real identity's remaining budget.
        self.assertIsNone(freechecks.consume_check(tampered))
        self.assertEqual(freechecks.get_grant(raw).checks_used, 1)

    def test_remaining_never_goes_negative(self):
        raw, _ = freechecks.issue_grant()
        for _ in range(freechecks.FREE_CHECK_LIFETIME_LIMIT):
            freechecks.consume_check(raw)
        with mock.patch.object(freechecks, "FREE_CHECK_LIFETIME_LIMIT", 1):
            self.assertEqual(freechecks.get_grant(raw).remaining, 0)


if __name__ == "__main__":
    unittest.main()
