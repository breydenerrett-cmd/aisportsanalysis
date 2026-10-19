"""A leaked access code must not outlive support's fix (red team 2026-10-19).

POST /auth/password lets ANY valid token set the FIRST password. Support's
documented answer to a leaked access code is a re-issue, which revokes every
token, but it kept the stored password, so an attacker who had set one kept
signing in by email + password for the life of the account. Every path that
revokes all of a person's tokens now deletes the password in the same
transaction, and the audit row records `had_password` (a bool, never the hash).

The store half is stdlib (runs on the Linux CI image); the route half drives the
real app and is skipped where FastAPI is absent. Chosen fix: clear-on-revoke
only. The rejected alternative (require the first-password token to postdate the
last re-issue) is redundant once the password is gone, because an old token is
revoked and can set nothing.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.appstate import comps
from src.appstate import passwords
from src.appstate import users as users_store

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

PW = "attacker owns this 99"
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


class StoreClearsPasswordOnRevoke(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "app.db"

    def victim(self, email="victim@example.com"):
        user = users_store.create_user(email, status="active", plan="none", db=self.db)
        leaked = users_store.issue_invite_token(user.id, db=self.db)
        # the attacker's move: a token alone sets the first password
        passwords.set_password(user.id, PW, email=email, db=self.db)
        return user, leaked

    def test_reissue_token_deletes_the_password(self):
        user, leaked = self.victim()
        seen = {}

        def audit(conn, revoked):
            seen["had"] = users_store.password_exists_on(conn, user.id)

        users_store.reissue_token(user.id, expires_at=NOW + timedelta(days=30),
                                  now=NOW, audit=audit, db=self.db)
        self.assertTrue(seen["had"], "the audit callback must still see the password")
        self.assertFalse(passwords.has_password(user.id, db=self.db))
        self.assertIsNone(passwords.authenticate_password(user.email, PW, db=self.db))

    def test_reissue_without_a_password_is_unchanged(self):
        user = users_store.create_user("plain@example.com", status="active", plan="none",
                                       db=self.db)
        seen = {}

        def audit(conn, revoked):
            seen["had"] = users_store.password_exists_on(conn, user.id)

        users_store.reissue_token(user.id, expires_at=NOW + timedelta(days=30), now=NOW,
                                  audit=audit, db=self.db)
        self.assertFalse(seen["had"])

    def test_failed_audit_keeps_the_password(self):
        user, _ = self.victim()

        def boom(conn, revoked):
            raise RuntimeError("audit down")

        with self.assertRaises(RuntimeError):
            users_store.reissue_token(user.id, expires_at=NOW + timedelta(days=30),
                                      now=NOW, audit=boom, db=self.db)
        self.assertTrue(passwords.has_password(user.id, db=self.db))

    def test_revoke_all_tokens_deletes_the_password(self):
        user, _ = self.victim()
        users_store.revoke_all_tokens(user.id, db=self.db)
        self.assertFalse(passwords.has_password(user.id, db=self.db))

    def test_comp_revoke_deletes_the_password_and_audits_the_fact(self):
        grant = comps.grant_comp(email="free@example.com", reason="early access",
                                 now=NOW, db=self.db)
        passwords.set_password(grant.user_id, PW, email="free@example.com", db=self.db)
        comps.revoke_comp(grant.user_id, "ticket 9: token leaked", now=NOW, db=self.db)
        self.assertFalse(passwords.has_password(grant.user_id, db=self.db))
        with closing(sqlite3.connect(self.db)) as conn:
            rows = [json.loads(r[0]) for r in conn.execute(
                "SELECT properties_json FROM analytics_events WHERE kind = 'comp_access_revoked'")]
        self.assertEqual([r["had_password"] for r in rows], [True])
        self.assertNotIn("hash", json.dumps(rows))

    def test_comp_grant_over_an_existing_account_deletes_the_password(self):
        user, _ = self.victim("waitlisted@example.com")
        comps.grant_comp(user_id=user.id, reason="let him in", now=NOW, db=self.db)
        self.assertFalse(passwords.has_password(user.id, db=self.db))

    def test_other_accounts_keep_their_password(self):
        victim, _ = self.victim()
        other = users_store.create_user("other@example.com", status="active", plan="none",
                                        db=self.db)
        passwords.set_password(other.id, PW, email="other@example.com", db=self.db)
        users_store.reissue_token(victim.id, expires_at=NOW + timedelta(days=30),
                                  now=NOW, db=self.db)
        self.assertTrue(passwords.has_password(other.id, db=self.db))


if HAS_FASTAPI:
    from tests.test_api_passwords import ADMIN, _asgi, _Base
    from src.appstate import events

    class LeakedTokenThroughTheApp(_Base):
        """The red team's repro, as a test: the attacker logged in after
        support's re-issue before the fix."""

        def test_attacker_cannot_log_in_after_reissue(self):
            victim = self.make_subscriber(email="victim@example.com", password=None)
            leaked = users_store.issue_invite_token(victim.id)
            r = _asgi(self.app, "POST", "/auth/password", body={"new_password": PW},
                      headers={"Authorization": f"Bearer {leaked}"})
            self.assertEqual(r["status"], 200)
            r = _asgi(self.app, "POST", "/admin/users/reissue",
                      body={"email": "victim@example.com", "reason": "ticket 12: token leaked"},
                      headers={"X-Admin-Token": ADMIN})
            self.assertEqual(r["status"], 200)
            self.assertEqual(r["json"]["revoked_tokens"], 1)
            r = _asgi(self.app, "POST", "/auth/login",
                      body={"email": "victim@example.com", "password": PW})
            self.assertEqual(r["status"], 401)
            # the real owner signs in with the new access code and sets their own
            new_token = _asgi(self.app, "POST", "/admin/users/reissue",
                              body={"email": "victim@example.com", "reason": "ticket 12 again"},
                              headers={"X-Admin-Token": ADMIN})["json"]["token"]
            r = _asgi(self.app, "POST", "/auth/password",
                      body={"new_password": "owner picks 77 words"},
                      headers={"Authorization": f"Bearer {new_token}"})
            self.assertEqual(r["status"], 200)
            self.assertFalse(r["json"]["changed"], "a first password, not a change")

        def test_audit_row_records_had_password_and_no_hash(self):
            victim = self.make_subscriber(email="victim@example.com", password=PW)
            r = _asgi(self.app, "POST", "/admin/users/reissue",
                      body={"email": "victim@example.com", "reason": "ticket 13: token leaked"},
                      headers={"X-Admin-Token": ADMIN})
            self.assertEqual(r["status"], 200)
            with closing(sqlite3.connect(self.db)) as conn:
                props = [json.loads(p[0]) for p in conn.execute(
                    "SELECT properties_json FROM analytics_events WHERE kind = ?",
                    (events.SUPPORT_TOKEN_REISSUED,))]
            self.assertEqual(len(props), 1)
            self.assertIs(props[0]["had_password"], True)
            self.assertFalse(passwords.has_password(victim.id))

        def test_legacy_token_route_also_clears_it(self):
            victim = self.make_subscriber(email="victim@example.com", password=PW)
            r = _asgi(self.app, "POST", "/admin/users/token",
                      body={"email": "victim@example.com"},
                      headers={"X-Admin-Token": ADMIN})
            self.assertEqual(r["status"], 200)
            self.assertFalse(passwords.has_password(victim.id))


if __name__ == "__main__":
    unittest.main()
