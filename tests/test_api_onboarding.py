"""api/onboarding.py: GET /onboarding, called directly (same skip-if-no-
fastapi, no-TestClient pattern as this repo's other api/ tests)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.appstate import events
from src.appstate import onboarding
from src.appstate import users as users_store


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class GetOnboardingRouteTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._patcher = mock.patch.object(events, "db_path", lambda: self.db)
        self._patcher.start()
        self.user = users_store.create_user("onboardme@example.com", db=self.db)

    def tearDown(self):
        self._patcher.stop()
        self._tmp.cleanup()

    def test_no_events_yet_nothing_complete(self):
        from api.onboarding import get_onboarding
        result = get_onboarding(current_user=self.user)
        self.assertFalse(result["complete"])
        for step in onboarding.STEPS:
            self.assertFalse(result["steps"][step]["complete"])
            self.assertIsNone(result["steps"][step]["completed_at"])

    def test_all_steps_present_in_response(self):
        from api.onboarding import get_onboarding
        result = get_onboarding(current_user=self.user)
        self.assertEqual(set(result["steps"].keys()), set(onboarding.STEPS))

    def test_progress_reflects_recorded_events(self):
        from api.onboarding import get_onboarding
        events.record_event(events.hash_user_id(self.user.id),
                            events.INVITE_REDEEMED, db=self.db)
        events.record_event(events.hash_user_id(self.user.id), events.PAGE_VIEW,
                            {"route": "/today"}, db=self.db)
        result = get_onboarding(current_user=self.user)
        self.assertTrue(result["steps"][onboarding.TOKEN_REDEEMED]["complete"])
        self.assertTrue(result["steps"][onboarding.FIRST_TODAY_VIEW]["complete"])
        self.assertFalse(result["steps"][onboarding.FIRST_BET_CHECK]["complete"])
        self.assertFalse(result["complete"])

    def test_scoped_to_the_authed_caller_only(self):
        from api.onboarding import get_onboarding
        other = users_store.create_user("someoneelse@example.com", db=self.db)
        events.record_event(events.hash_user_id(other.id), events.BET_SAVED,
                            db=self.db)
        result = get_onboarding(current_user=self.user)
        self.assertFalse(result["steps"][onboarding.FIRST_SAVED_BET]["complete"])


if __name__ == "__main__":
    unittest.main()
