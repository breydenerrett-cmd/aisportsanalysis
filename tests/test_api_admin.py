"""api/admin.py: GET /admin/overview and GET /admin/users, called directly
(same skip-if-no-fastapi, no-TestClient pattern as tests/test_api_auth.py
and tests/test_api_mybets.py -- see test_api_auth.py's module docstring for
why).

The admin gate itself (404-when-unconfigured, 401-wrong-token,
compare_digest) is already exhaustively tested against api.auth._require_admin
in tests/test_api_auth.py; this file proves admin.py actually calls that
same function (not a reimplementation) and that its two payload shapes are
right, rather than re-testing the gate's own internals.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from fastapi import HTTPException
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.appstate import events
from src.appstate import users as users_store

ENV_ADMIN_TOKEN = "APP_ADMIN_TOKEN"


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class AdminGateTests(unittest.TestCase):
    """admin.py's routes are gated by api.auth._require_admin -- proven here
    by exercising the same three outcomes that dependency produces, through
    admin.py's own route functions rather than by re-deriving the gate."""

    def setUp(self):
        self._original = os.environ.get(ENV_ADMIN_TOKEN)
        self.addCleanup(self._restore)

    def _restore(self):
        if self._original is None:
            os.environ.pop(ENV_ADMIN_TOKEN, None)
        else:
            os.environ[ENV_ADMIN_TOKEN] = self._original

    def test_unconfigured_admin_token_is_a_404(self):
        os.environ.pop(ENV_ADMIN_TOKEN, None)
        from api import admin
        with self.assertRaises(HTTPException) as ctx:
            admin._require_admin(x_admin_token=None)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_wrong_token_is_a_401(self):
        os.environ[ENV_ADMIN_TOKEN] = "correct-token"
        from api import admin
        with self.assertRaises(HTTPException) as ctx:
            admin._require_admin(x_admin_token="wrong-token")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_admin_imports_require_admin_rather_than_duplicating_it(self):
        """Pins the task's own instruction: one gate, imported, not two
        independent implementations that could drift."""
        from api import admin, auth
        self.assertIs(admin._require_admin, auth._require_admin)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class AdminOverviewTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = self.root / "app.db"
        self.events_db = self.root / "events.db"
        self._patchers = [
            mock.patch.object(users_store, "db_path", lambda: self.db),
            mock.patch.object(events, "db_path", lambda: self.events_db),
        ]
        for p in self._patchers:
            p.start()
        self.addCleanup(self._stop_patchers)
        os.environ[ENV_ADMIN_TOKEN] = "test-admin-token"
        self._original = None

    def _stop_patchers(self):
        for p in self._patchers:
            p.stop()
        self._tmp.cleanup()

    def tearDown(self):
        os.environ.pop(ENV_ADMIN_TOKEN, None)

    def test_overview_shape_and_counts(self):
        from api import admin
        users_store.create_user("active@example.com", status="active",
                                plan="beta", db=self.db)
        users_store.create_user("invited@example.com", status="invited",
                                plan="none", db=self.db)
        events.record_event(events.hash_user_id(1), events.PAGE_VIEW,
                            db=self.events_db)

        with mock.patch("src.appstate.apphealth.report",
                        return_value={"status": "ok", "reasons": []}):
            result = admin.get_overview(_admin=None)

        self.assertEqual(result["users"]["total"], 2)
        self.assertEqual(result["users"]["by_status"],
                         {"active": 1, "invited": 1})
        self.assertEqual(result["users"]["by_plan"], {"beta": 1, "none": 1})
        self.assertEqual(result["invites_outstanding"], 0)  # neither issued a token
        self.assertIn("daily_counts_by_kind", result["events"])
        self.assertEqual(result["store_health"], {"status": "ok", "reasons": []})
        self.assertIn("version", result)

    def test_outstanding_invites_counts_unexpired_unrevoked_tokens_only(self):
        from api import admin
        from datetime import timedelta
        user = users_store.create_user("invitee@example.com", db=self.db)
        users_store.issue_invite_token(user.id, db=self.db)  # outstanding
        expired_user = users_store.create_user("expired@example.com", db=self.db)
        users_store.issue_invite_token(expired_user.id, ttl=timedelta(seconds=-1),
                                       db=self.db)  # already expired

        with mock.patch("src.appstate.apphealth.report",
                        return_value={"status": "ok", "reasons": []}):
            result = admin.get_overview(_admin=None)
        self.assertEqual(result["invites_outstanding"], 1)

    def test_no_email_appears_in_the_overview_payload(self):
        """Privacy rule: emails appear ONLY in GET /admin/users, never
        /admin/overview."""
        from api import admin
        import json
        users_store.create_user("secret@example.com", db=self.db)
        with mock.patch("src.appstate.apphealth.report",
                        return_value={"status": "ok", "reasons": []}):
            result = admin.get_overview(_admin=None)
        blob = json.dumps(result)
        self.assertNotIn("secret@example.com", blob)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class AdminUsersTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._patcher = mock.patch.object(users_store, "db_path", lambda: self.db)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def test_users_listing_shape(self):
        from api import admin
        user = users_store.create_user("visible@example.com", status="active",
                                       plan="beta", db=self.db)
        result = admin.get_users(_admin=None)
        self.assertEqual(len(result["users"]), 1)
        row = result["users"][0]
        self.assertEqual(row["id"], user.id)
        self.assertEqual(row["email"], "visible@example.com")
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["plan"], "beta")
        self.assertEqual(row["created_at"], user.created_at)


if __name__ == "__main__":
    unittest.main()
