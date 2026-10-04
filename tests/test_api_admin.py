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
from datetime import datetime, timedelta, timezone
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


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class AdminReissueTokenTests(unittest.TestCase):
    """POST /admin/users/token: lost-token recovery. The token is a
    subscriber's only login and there is no email sender."""

    def setUp(self):
        from src.appstate import customers
        self.customers = customers
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self.events_db = Path(self._tmp.name) / "events.db"
        for p in (mock.patch.object(users_store, "db_path", lambda: self.db),
                  mock.patch.object(events, "db_path", lambda: self.events_db)):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)
        from api import admin
        self.admin = admin

    def _paying_user(self, email="payer@example.com", status="active"):
        user = users_store.create_user(email, status="active", plan="beta")
        self.customers.upsert_customer(user.id, "cus_" + str(user.id))
        # Paid through a future instant: access runs to the paid-through date
        # and an `active` row with none on record is not entitled (billing
        # ACCESS POLICY, 2026-10-04), so a "paying" fixture must have one.
        # A canceled fixture stays one with nothing paid through.
        paid_through = ((datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
                        if status in ("active", "trialing") else None)
        self.customers.upsert_subscription(user.id, "sub_" + str(user.id), status,
                                           current_period_end=paid_through)
        return user

    def _call(self, **kw):
        return self.admin.reissue_subscriber_token(
            self.admin.ReissueTokenRequest(**kw), _admin=None)

    def test_the_route_is_registered_behind_the_admin_gate(self):
        import inspect
        routes = {(r.path, tuple(sorted(r.methods))): r for r in self.admin.router.routes}
        self.assertIn(("/admin/users/token", ("POST",)), routes)
        default = inspect.signature(self.admin.reissue_subscriber_token).parameters["_admin"].default
        self.assertIs(default.dependency, self.admin._require_admin)

    def test_a_paying_user_gets_a_working_token_by_email_and_by_id(self):
        user = self._paying_user()
        by_email = self._call(email="Payer@Example.com")
        self.assertEqual(users_store.authenticate(by_email["token"]).id, user.id)
        by_id = self._call(user_id=user.id)
        self.assertEqual(users_store.authenticate(by_id["token"]).id, user.id)

    def test_existing_tokens_are_revoked_when_the_new_one_is_minted(self):
        user = self._paying_user()
        old = users_store.issue_invite_token(user.id)
        old2 = users_store.issue_invite_token(user.id)
        other = users_store.create_user("other@example.com", status="active")
        other_token = users_store.issue_invite_token(other.id)
        result = self._call(email="payer@example.com")
        self.assertIsNone(users_store.authenticate(old))
        self.assertIsNone(users_store.authenticate(old2))
        self.assertIsNotNone(users_store.authenticate(result["token"]))
        self.assertIsNotNone(users_store.authenticate(other_token), "another user's token")
        self.assertEqual(result["revoked_tokens"], 2)

    def test_the_token_lives_as_long_as_a_subscriber_token(self):
        from datetime import datetime, timedelta, timezone
        user = self._paying_user()
        token = self._call(user_id=user.id)["token"]
        from src.appstate import billing
        inside = datetime.now(timezone.utc) + billing.SUBSCRIBER_TOKEN_TTL - timedelta(days=1)
        outside = datetime.now(timezone.utc) + billing.SUBSCRIBER_TOKEN_TTL + timedelta(days=1)
        self.assertIsNotNone(users_store.authenticate(token, now=inside))
        self.assertIsNone(users_store.authenticate(token, now=outside))

    def test_a_trialing_user_counts_as_paid(self):
        user = self._paying_user(status="trialing")
        self.assertTrue(self._call(user_id=user.id)["token"])

    def test_a_user_without_paid_access_is_a_409_and_keeps_their_tokens(self):
        user = users_store.create_user("free@example.com", status="active")
        existing = users_store.issue_invite_token(user.id)
        with self.assertRaises(HTTPException) as ctx:
            self._call(email="free@example.com")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("no paid access", str(ctx.exception.detail))
        self.assertIsNotNone(users_store.authenticate(existing))

    def test_a_canceled_user_is_a_409(self):
        user = self._paying_user(status="canceled")
        with self.assertRaises(HTTPException) as ctx:
            self._call(user_id=user.id)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_unknown_user_is_404_and_bad_bodies_are_400(self):
        for kw, code in (({"email": "nobody@example.com"}, 404), ({"user_id": 9999}, 404),
                         ({}, 400),
                         ({"email": "a@example.com", "user_id": 1}, 400)):
            with self.assertRaises(HTTPException) as ctx:
                self._call(**kw)
            self.assertEqual(ctx.exception.status_code, code, kw)

    def test_an_event_is_recorded_and_never_carries_the_token(self):
        user = self._paying_user()
        token = self._call(user_id=user.id)["token"]
        recorded = [e for e in events.list_events()
                    if e.kind == events.SUPPORT_TOKEN_REISSUED]
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0].user_hash, events.hash_user_id(user.id))
        import json
        self.assertNotIn(token, json.dumps(recorded[0].properties))
        self.assertNotIn(token, str(recorded[0]))

    def test_the_token_is_never_printed(self):
        import contextlib
        import io
        user = self._paying_user()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            token = self._call(user_id=user.id)["token"]
        self.assertNotIn(token, out.getvalue() + err.getvalue())

    def test_the_support_procedure_is_in_the_docstring(self):
        doc = self.admin.reissue_subscriber_token.__doc__
        self.assertIn("SUPPORT PROCEDURE", doc)
        self.assertEqual(sum(1 for line in doc.splitlines() if line.strip()[:2] in
                             ("1.", "2.", "3.", "4.", "5.", "6.")), 6)

    def test_it_is_unreachable_without_the_admin_token(self):
        os.environ[ENV_ADMIN_TOKEN] = "correct-token"
        self.addCleanup(os.environ.pop, ENV_ADMIN_TOKEN, None)
        with self.assertRaises(HTTPException) as ctx:
            self.admin._require_admin(x_admin_token="nope")
        self.assertEqual(ctx.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
