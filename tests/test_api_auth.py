"""api/auth.py: bearer-token auth dependency + admin invite endpoint.

Skip-if-no-fastapi, same shape as this repo's other api/ tests: FastAPI is
an api/-only dependency (tests/test_api_boundary.py), so a test environment
without it installed must skip rather than fail. No TestClient/HTTP layer
here (this environment's starlette build needs an extra HTTP client
package this repo does not otherwise depend on) -- instead the FastAPI
dependency functions are called directly, which exercises the same auth
logic without spinning up a server.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

try:
    from fastapi import HTTPException
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.appstate import users as users_store


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class GetCurrentUserTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        # api.auth.get_current_user calls users_store.authenticate() with
        # no db= override (it always targets the real APP_DB_PATH-resolved
        # store), so point that at our tmp db for the duration of the test.
        self._patcher = mock.patch.object(users_store, "db_path", lambda: self.db)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp.cleanup()

    def test_missing_header_is_401(self):
        from api.auth import get_current_user
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(authorization=None)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_wrong_scheme_is_401(self):
        from api.auth import get_current_user
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(authorization="Basic abc123")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_unknown_token_is_401(self):
        from api.auth import get_current_user
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(authorization="Bearer not-a-real-token")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_valid_token_resolves_to_the_user(self):
        from api.auth import get_current_user
        user = users_store.create_user("valid@example.com", status="active", db=self.db)
        raw_token = users_store.issue_invite_token(user.id, db=self.db)
        resolved = get_current_user(authorization=f"Bearer {raw_token}")
        self.assertEqual(resolved.id, user.id)

    def test_suspended_user_is_401_even_with_a_valid_token(self):
        from api.auth import get_current_user
        user = users_store.create_user("susp@example.com", status="suspended", db=self.db)
        raw_token = users_store.issue_invite_token(user.id, db=self.db)
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(authorization=f"Bearer {raw_token}")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_expired_token_is_401(self):
        from api.auth import get_current_user
        user = users_store.create_user("exp@example.com", status="active", db=self.db)
        raw_token = users_store.issue_invite_token(
            user.id, ttl=timedelta(seconds=-1), db=self.db)
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(authorization=f"Bearer {raw_token}")
        self.assertEqual(ctx.exception.status_code, 401)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class AdminInviteEndpointTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._patcher = mock.patch.object(users_store, "db_path", lambda: self.db)
        self._patcher.start()
        self._env_patcher = mock.patch.dict(os.environ, {}, clear=False)
        self._env_patcher.start()
        os.environ.pop("APP_ADMIN_TOKEN", None)

    def tearDown(self):
        self._env_patcher.stop()
        self._patcher.stop()
        self._tmp.cleanup()

    def test_endpoint_disabled_when_no_admin_token_configured(self):
        from api.auth import _require_admin
        with self.assertRaises(HTTPException) as ctx:
            _require_admin(x_admin_token=None)
        self.assertEqual(ctx.exception.status_code, 404)
        # Even a guess at a token does not open the door -- disabled means
        # disabled, not "open to whoever asks."
        with self.assertRaises(HTTPException) as ctx2:
            _require_admin(x_admin_token="anything")
        self.assertEqual(ctx2.exception.status_code, 404)

    def test_wrong_admin_token_is_401(self):
        os.environ["APP_ADMIN_TOKEN"] = "correct-horse"
        from api.auth import _require_admin
        with self.assertRaises(HTTPException) as ctx:
            _require_admin(x_admin_token="wrong")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_invite_happy_path_issues_a_working_token(self):
        os.environ["APP_ADMIN_TOKEN"] = "correct-horse"
        from api.auth import _require_admin, create_invite, get_current_user

        # Call the guard explicitly, the same check FastAPI's dependency
        # injection would run before the endpoint body -- there is no
        # TestClient in this environment to exercise the full DI wiring
        # (see module docstring), so the two pieces are proven together
        # by hand instead of trusting FastAPI to wire them at request time.
        _require_admin(x_admin_token="correct-horse")
        result = create_invite(email="new@example.com")
        self.assertIn("token", result)
        self.assertEqual(result["email"], "new@example.com")

        # The issued token must actually authenticate.
        resolved = get_current_user(authorization=f"Bearer {result['token']}")
        self.assertEqual(resolved.email, "new@example.com")

    def test_invite_reuses_existing_user_by_email(self):
        os.environ["APP_ADMIN_TOKEN"] = "correct-horse"
        from api.auth import _require_admin, create_invite

        _require_admin(x_admin_token="correct-horse")
        first = create_invite(email="repeat@example.com")
        _require_admin(x_admin_token="correct-horse")
        second = create_invite(email="repeat@example.com")
        self.assertEqual(first["user_id"], second["user_id"])
        # Two distinct tokens, both valid, since re-inviting must not
        # revoke a token still in someone's inbox.
        self.assertNotEqual(first["token"], second["token"])


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class ProviderSeamTests(unittest.TestCase):
    """get_current_user resolves through src.appstate.authproviders now --
    these pin that the seam itself is wired, on top of
    GetCurrentUserTests above pinning that invite-token behavior (the
    default provider) is unchanged."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._patcher = mock.patch.object(users_store, "db_path", lambda: self.db)
        self._patcher.start()
        self._env_patcher = mock.patch.dict(os.environ, {}, clear=False)
        self._env_patcher.start()

    def tearDown(self):
        self._env_patcher.stop()
        self._patcher.stop()
        self._tmp.cleanup()

    def test_unconfigured_clerk_provider_is_503_not_401(self):
        from api.auth import get_current_user
        from src.appstate import authproviders
        os.environ[authproviders.ENV_AUTH_PROVIDER] = "clerk"
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(authorization="Bearer whatever")
        self.assertEqual(ctx.exception.status_code, 503)

    def test_unknown_auth_provider_env_is_a_hard_error(self):
        from api.auth import get_current_user
        from src.appstate import authproviders
        os.environ[authproviders.ENV_AUTH_PROVIDER] = "some_typo"
        with self.assertRaises(RuntimeError):
            get_current_user(authorization="Bearer whatever")


if __name__ == "__main__":
    unittest.main()
