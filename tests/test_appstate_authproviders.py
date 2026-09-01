"""src/appstate/authproviders.py: the AuthProvider seam.

InviteTokenProvider must be behaviorally identical to the inline logic
api/auth.py used to run (see tests/test_api_auth.py for the end-to-end
401/suspended/expired cases through the FastAPI dependency); these tests
pin the seam itself -- provider selection, ClerkProvider's clean refusal,
and InviteTokenProvider's header parsing in isolation.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.appstate import authproviders
from src.appstate import users as users_store


class ProviderSelectionTests(unittest.TestCase):

    def test_default_is_invite_token(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(authproviders.ENV_AUTH_PROVIDER, None)
            provider = authproviders.get_provider()
        self.assertIsInstance(provider, authproviders.InviteTokenProvider)
        self.assertEqual(provider.name, "invite_token")

    def test_explicit_clerk_selection(self):
        provider = authproviders.get_provider("clerk")
        self.assertIsInstance(provider, authproviders.ClerkProvider)

    def test_env_selects_provider(self):
        with mock.patch.dict(os.environ, {authproviders.ENV_AUTH_PROVIDER: "clerk"}):
            provider = authproviders.get_provider()
        self.assertIsInstance(provider, authproviders.ClerkProvider)

    def test_unknown_provider_is_a_hard_error_not_a_silent_fallback(self):
        with self.assertRaises(RuntimeError):
            authproviders.get_provider("some_typo")


class InviteTokenProviderTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._patcher = mock.patch.object(users_store, "db_path", lambda: self.db)
        self._patcher.start()
        self.provider = authproviders.InviteTokenProvider()

    def tearDown(self):
        self._patcher.stop()
        self._tmp.cleanup()

    def test_none_header_resolves_to_none(self):
        self.assertIsNone(self.provider.resolve(None))

    def test_wrong_scheme_resolves_to_none(self):
        self.assertIsNone(self.provider.resolve("Basic abc123"))

    def test_unknown_token_resolves_to_none(self):
        self.assertIsNone(self.provider.resolve("Bearer not-a-real-token"))

    def test_valid_token_resolves_to_the_user(self):
        user = users_store.create_user("seam@example.com", status="active", db=self.db)
        raw_token = users_store.issue_invite_token(user.id, db=self.db)
        resolved = self.provider.resolve(f"Bearer {raw_token}")
        self.assertEqual(resolved.id, user.id)

    def test_never_raises_not_configured(self):
        """Unlike ClerkProvider, invite-token auth is always 'configured'
        -- there is no missing env var or pending dependency for it."""
        try:
            self.provider.resolve("Bearer whatever")
        except authproviders.AuthProviderNotConfigured:
            self.fail("InviteTokenProvider must never raise NotConfigured")


class ClerkProviderTests(unittest.TestCase):

    def setUp(self):
        self.provider = authproviders.ClerkProvider()
        self._env_patcher = mock.patch.dict(os.environ, {}, clear=False)
        self._env_patcher.start()
        os.environ.pop(authproviders.ENV_CLERK_JWKS_URL, None)
        os.environ.pop(authproviders.ENV_CLERK_ISSUER, None)

    def tearDown(self):
        self._env_patcher.stop()

    def test_refuses_cleanly_when_env_unset(self):
        with self.assertRaises(authproviders.AuthProviderNotConfigured):
            self.provider.resolve("Bearer some.jwt.value")

    def test_refuses_cleanly_even_when_env_is_set(self):
        """Setting env vars alone cannot skip the pending SDK-approval
        gate -- see ClerkProvider's docstring for the exact Brey trigger."""
        os.environ[authproviders.ENV_CLERK_JWKS_URL] = "https://example.invalid/.well-known/jwks.json"
        os.environ[authproviders.ENV_CLERK_ISSUER] = "https://example.invalid"
        with self.assertRaises(authproviders.AuthProviderNotConfigured):
            self.provider.resolve("Bearer some.jwt.value")

    def test_never_returns_a_fake_user(self):
        """No env, no auth header, still never quietly returns None as if
        'not authenticated' -- it must raise, distinguishing 'this
        provider cannot work' from 'this credential does not work.'"""
        with self.assertRaises(authproviders.AuthProviderNotConfigured):
            self.provider.resolve(None)


if __name__ == "__main__":
    unittest.main()
