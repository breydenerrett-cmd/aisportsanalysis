"""api/support.py: POST /support, GET /admin/support,
POST /admin/support/{id}/status -- called directly (same skip-if-no-fastapi,
no-TestClient pattern as tests/test_api_mybets.py and tests/test_api_admin.py).

AUTH-BOUNDARY NOTE (see BOUNDARIES/ACCEPTANCE in this task's brief): v1 has
no "list my own support messages" route for a regular user -- only the
admin listing exists. A user who files a ticket gets the created message
back in that one POST response and nothing else; there is no way for them
to read it back later through this API. That is a deliberate v1 scope cut,
not an oversight -- documented here and in
docs/ONBOARDING_SUPPORT_PLAYBOOK.md rather than tested as a 403/404, since
there is no route to call that boundary on.
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

from src.appstate import support as support_store
from src.appstate import users as users_store

ENV_ADMIN_TOKEN = "APP_ADMIN_TOKEN"


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class CreateSupportMessageTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._patcher = mock.patch.object(support_store, "db_path", lambda: self.db)
        self._patcher.start()
        self.user = users_store.create_user("supportuser@example.com", db=self.db)

    def tearDown(self):
        self._patcher.stop()
        self._tmp.cleanup()

    def test_authed_caller_needs_no_email(self):
        from api.support import SupportMessageRequest, create_support_message
        result = create_support_message(
            SupportMessageRequest(subject="Help", body="It broke"),
            sender=self.user, _rate_limit=None)
        self.assertEqual(result["user_id"], self.user.id)
        self.assertIsNone(result["email"])
        self.assertEqual(result["status"], "open")

    def test_anonymous_caller_with_email_succeeds(self):
        from api.support import SupportMessageRequest, create_support_message
        result = create_support_message(
            SupportMessageRequest(email="pre-invite@example.com",
                                  subject="Question", body="Before I sign up..."),
            sender=None, _rate_limit=None)
        self.assertIsNone(result["user_id"])
        self.assertEqual(result["email"], "pre-invite@example.com")

    def test_anonymous_caller_without_email_is_400(self):
        from api.support import SupportMessageRequest, create_support_message
        with self.assertRaises(HTTPException) as ctx:
            create_support_message(
                SupportMessageRequest(subject="Question", body="body"),
                sender=None, _rate_limit=None)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_authed_callers_email_field_is_ignored(self):
        # An authed sender's identity is their account, not whatever they
        # typed into an optional email field -- see create_support_message's
        # own docstring.
        from api.support import SupportMessageRequest, create_support_message
        result = create_support_message(
            SupportMessageRequest(email="someone-else@example.com",
                                  subject="s", body="b"),
            sender=self.user, _rate_limit=None)
        self.assertEqual(result["user_id"], self.user.id)
        self.assertIsNone(result["email"])

    def test_open_message_cap_surfaces_as_429(self):
        from api.support import SupportMessageRequest, create_support_message
        for i in range(support_store.MAX_OPEN_MESSAGES_PER_USER):
            create_support_message(
                SupportMessageRequest(subject=f"s{i}", body="b"),
                sender=self.user, _rate_limit=None)
        with self.assertRaises(HTTPException) as ctx:
            create_support_message(
                SupportMessageRequest(subject="one more", body="b"),
                sender=self.user, _rate_limit=None)
        self.assertEqual(ctx.exception.status_code, 429)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class SupportRateLimitTests(unittest.TestCase):
    """The dual (authed-or-IP) keying api/support.py's own limiter uses --
    see that module's docstring for why it can't reuse
    ratelimit.limiter_dependency outright."""

    def setUp(self):
        import api.support as support_mod
        from src.appstate import ratelimit
        self._support_mod = support_mod
        self._original_limiter = support_mod._support_limiter
        support_mod._support_limiter = ratelimit.FixedWindowLimiter(
            limit=2, window_s=3600.0)

    def tearDown(self):
        self._support_mod._support_limiter = self._original_limiter

    def test_trips_after_the_configured_count_for_anonymous_ip(self):
        dep = self._support_mod._rate_limit_support
        request = mock.Mock(client=None)
        dep(request=request, sender=None)
        dep(request=request, sender=None)
        with self.assertRaises(HTTPException) as ctx:
            dep(request=request, sender=None)
        self.assertEqual(ctx.exception.status_code, 429)

    def test_authed_and_anonymous_get_separate_counters(self):
        dep = self._support_mod._rate_limit_support
        request = mock.Mock(client=None)
        user = users_store.User(id=1, email="a@b.com", created_at="x",
                                status="active", plan="beta")
        dep(request=request, sender=user)
        dep(request=request, sender=user)
        # The user's counter is now tripped; an anonymous caller on the
        # same request/IP must still get through on a fresh counter.
        dep(request=request, sender=None)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class AdminSupportRoutesTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._patcher = mock.patch.object(support_store, "db_path", lambda: self.db)
        self._patcher.start()
        self._original_token = os.environ.get(ENV_ADMIN_TOKEN)
        os.environ[ENV_ADMIN_TOKEN] = "test-admin-token"

    def tearDown(self):
        self._patcher.stop()
        self._tmp.cleanup()
        if self._original_token is None:
            os.environ.pop(ENV_ADMIN_TOKEN, None)
        else:
            os.environ[ENV_ADMIN_TOKEN] = self._original_token

    def test_support_imports_require_admin_rather_than_duplicating_it(self):
        """The admin gate itself (404-when-unconfigured, 401-wrong-token,
        compare_digest) is exhaustively tested against
        api.auth._require_admin in tests/test_api_auth.py; this pins that
        api/support.py imports that same function rather than a
        reimplementation that could drift -- same check
        tests/test_api_admin.py runs for api/admin.py."""
        from api import auth, support
        self.assertIs(support._require_admin, auth._require_admin)

    def test_list_and_filter(self):
        from api.support import list_support_messages
        support_store.create_message(user_id=1, subject="a", body="b", db=self.db)
        answered = support_store.create_message(user_id=2, subject="c", body="d",
                                                 db=self.db)
        support_store.update_status(answered.id, "answered", db=self.db)

        result = list_support_messages(_admin=None)
        self.assertEqual(len(result["messages"]), 2)

        open_only = list_support_messages(status="open", _admin=None)
        self.assertEqual(len(open_only["messages"]), 1)

    def test_set_status(self):
        from api.support import SupportStatusRequest, set_support_status
        msg = support_store.create_message(user_id=1, subject="a", body="b",
                                           db=self.db)
        result = set_support_status(msg.id, SupportStatusRequest(status="answered"),
                                    _admin=None)
        self.assertEqual(result["status"], "answered")
        self.assertIsNotNone(result["answered_at"])

    def test_set_status_unknown_id_is_404(self):
        from api.support import SupportStatusRequest, set_support_status
        with self.assertRaises(HTTPException) as ctx:
            set_support_status(999999, SupportStatusRequest(status="closed"),
                               _admin=None)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_set_status_bad_value_is_400(self):
        from api.support import SupportStatusRequest, set_support_status
        msg = support_store.create_message(user_id=1, subject="a", body="b",
                                           db=self.db)
        with self.assertRaises(HTTPException) as ctx:
            set_support_status(msg.id, SupportStatusRequest(status="bogus"),
                               _admin=None)
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
