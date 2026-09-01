"""src/appstate/onboarding.py: onboarding-checklist derivation over
analytics_events. stdlib only, no FastAPI involved."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.appstate import events
from src.appstate import onboarding


class GetOnboardingStateTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self.user_id = 101
        self.user_hash = events.hash_user_id(self.user_id)

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_events_means_nothing_complete(self):
        state = onboarding.get_onboarding_state(self.user_id, db=self.db)
        for step in onboarding.STEPS:
            self.assertFalse(state.steps[step].complete, step)
            self.assertIsNone(state.steps[step].completed_at, step)
        self.assertFalse(state.complete)

    def test_invite_redeemed_event_completes_token_redeemed_only(self):
        events.record_event(self.user_hash, events.INVITE_REDEEMED, db=self.db)
        state = onboarding.get_onboarding_state(self.user_id, db=self.db)
        self.assertTrue(state.steps[onboarding.TOKEN_REDEEMED].complete)
        for step in onboarding.STEPS:
            if step != onboarding.TOKEN_REDEEMED:
                self.assertFalse(state.steps[step].complete, step)
        self.assertFalse(state.complete)

    def test_today_route_page_view_completes_first_today_view(self):
        events.record_event(self.user_hash, events.PAGE_VIEW,
                            {"route": "/today", "date": "2026-08-31"}, db=self.db)
        state = onboarding.get_onboarding_state(self.user_id, db=self.db)
        self.assertTrue(state.steps[onboarding.FIRST_TODAY_VIEW].complete)

    def test_non_today_page_view_does_not_complete_first_today_view(self):
        # A games-list page view is real product usage, but it is not "the
        # user has seen Today" -- see onboarding.py's honesty rule.
        events.record_event(self.user_hash, events.PAGE_VIEW,
                            {"route": "/games/2026-08-31"}, db=self.db)
        state = onboarding.get_onboarding_state(self.user_id, db=self.db)
        self.assertFalse(state.steps[onboarding.FIRST_TODAY_VIEW].complete)

    def test_bet_check_run_completes_first_bet_check(self):
        events.record_event(self.user_hash, events.BET_CHECK_RUN, db=self.db)
        state = onboarding.get_onboarding_state(self.user_id, db=self.db)
        self.assertTrue(state.steps[onboarding.FIRST_BET_CHECK].complete)

    def test_bet_saved_completes_first_saved_bet(self):
        events.record_event(self.user_hash, events.BET_SAVED, db=self.db)
        state = onboarding.get_onboarding_state(self.user_id, db=self.db)
        self.assertTrue(state.steps[onboarding.FIRST_SAVED_BET].complete)

    def test_all_four_events_completes_the_whole_checklist(self):
        events.record_event(self.user_hash, events.INVITE_REDEEMED, db=self.db)
        events.record_event(self.user_hash, events.PAGE_VIEW,
                            {"route": "/today"}, db=self.db)
        events.record_event(self.user_hash, events.BET_CHECK_RUN, db=self.db)
        events.record_event(self.user_hash, events.BET_SAVED, db=self.db)
        state = onboarding.get_onboarding_state(self.user_id, db=self.db)
        self.assertTrue(state.complete)

    def test_earliest_matching_event_timestamp_is_kept(self):
        events.record_event(self.user_hash, events.BET_SAVED,
                            at="2026-01-01T00:00:00+00:00", db=self.db)
        events.record_event(self.user_hash, events.BET_SAVED,
                            at="2026-06-01T00:00:00+00:00", db=self.db)
        state = onboarding.get_onboarding_state(self.user_id, db=self.db)
        self.assertEqual(state.steps[onboarding.FIRST_SAVED_BET].completed_at,
                         "2026-01-01T00:00:00+00:00")

    def test_another_users_events_never_complete_this_users_steps(self):
        other_hash = events.hash_user_id(self.user_id + 1)
        events.record_event(other_hash, events.BET_SAVED, db=self.db)
        state = onboarding.get_onboarding_state(self.user_id, db=self.db)
        self.assertFalse(state.steps[onboarding.FIRST_SAVED_BET].complete)


if __name__ == "__main__":
    unittest.main()
