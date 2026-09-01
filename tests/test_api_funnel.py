"""api/funnel.py: POST /funnel/event (public) and GET /admin/funnel (admin)
-- called directly, same skip-if-no-fastapi/no-TestClient pattern as
tests/test_api_admin.py and tests/test_api_support.py (see the former's
module docstring for why).
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

try:
    from fastapi import HTTPException
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.appstate import events

ENV_ADMIN_TOKEN = "APP_ADMIN_TOKEN"


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class PostFunnelEventTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._patcher = mock.patch.object(events, "db_path", lambda: self.db)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def test_landing_view_is_accepted_and_recorded(self):
        from api.funnel import FunnelEventRequest, post_funnel_event
        result = post_funnel_event(FunnelEventRequest(kind="landing_view"))
        self.assertEqual(result, {"recorded": True})
        rows = events.list_events(db=self.db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].kind, "landing_view")

    def test_signup_started_is_accepted(self):
        from api.funnel import FunnelEventRequest, post_funnel_event
        post_funnel_event(FunnelEventRequest(kind="signup_started"))
        rows = events.list_events(db=self.db)
        self.assertEqual(rows[0].kind, "signup_started")

    def test_bet_saved_is_rejected_from_the_public_endpoint(self):
        """The exact ACCEPTANCE check this task names: a public caller
        cannot claim a bet was saved -- that kind is only ever recorded
        server-side from a real POST /my-bets (src/appstate/events.py)."""
        from api.funnel import FunnelEventRequest, post_funnel_event
        with self.assertRaises(HTTPException) as ctx:
            post_funnel_event(FunnelEventRequest(kind="bet_saved"))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(events.list_events(db=self.db), [])

    def test_every_authed_only_kind_is_rejected(self):
        from api.funnel import FunnelEventRequest, PUBLIC_FUNNEL_KINDS, post_funnel_event
        for kind in sorted(events.EVENT_KINDS - PUBLIC_FUNNEL_KINDS):
            with self.subTest(kind=kind):
                with self.assertRaises(HTTPException) as ctx:
                    post_funnel_event(FunnelEventRequest(kind=kind))
                self.assertEqual(ctx.exception.status_code, 400)

    def test_unknown_kind_is_rejected_too(self):
        from api.funnel import FunnelEventRequest, post_funnel_event
        with self.assertRaises(HTTPException) as ctx:
            post_funnel_event(FunnelEventRequest(kind="not_a_real_kind"))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_recorded_under_the_fixed_anonymous_sentinel_not_a_real_identity(self):
        from api.funnel import ANONYMOUS_FUNNEL_USER_ID, FunnelEventRequest, post_funnel_event
        post_funnel_event(FunnelEventRequest(kind="landing_view"))
        expected_hash = events.hash_user_id(ANONYMOUS_FUNNEL_USER_ID)
        self.assertEqual(events.list_events(db=self.db)[0].user_hash, expected_hash)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class FunnelRateLimitTests(unittest.TestCase):
    """FixedWindowLimiter is exhaustively unit-tested in
    tests/test_appstate_ratelimit.py; this pins that api/funnel.py actually
    wires POST /funnel/event to one, at the documented 60/hr limit."""

    def test_limit_is_sixty_per_hour(self):
        from api import funnel
        self.assertEqual(funnel.FUNNEL_RATE_LIMIT_PER_HOUR, 60)
        self.assertEqual(funnel._funnel_limiter.limit, 60)
        self.assertEqual(funnel._funnel_limiter.window_s, 3600.0)

    def test_trips_after_the_configured_count(self):
        import api.funnel as funnel_mod
        from src.appstate import ratelimit
        original = funnel_mod._funnel_limiter
        funnel_mod._funnel_limiter = ratelimit.FixedWindowLimiter(limit=2, window_s=3600.0)
        funnel_mod._rate_limit_funnel = ratelimit.limiter_dependency(funnel_mod._funnel_limiter)
        try:
            request = mock.Mock(client=None)
            funnel_mod._rate_limit_funnel(request=request)
            funnel_mod._rate_limit_funnel(request=request)
            with self.assertRaises(HTTPException) as ctx:
                funnel_mod._rate_limit_funnel(request=request)
            self.assertEqual(ctx.exception.status_code, 429)
        finally:
            funnel_mod._funnel_limiter = original


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class AdminFunnelTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._patcher = mock.patch.object(events, "db_path", lambda: self.db)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        self._original_token = os.environ.get(ENV_ADMIN_TOKEN)
        os.environ[ENV_ADMIN_TOKEN] = "test-admin-token"
        self.addCleanup(self._restore_token)

    def _restore_token(self):
        if self._original_token is None:
            os.environ.pop(ENV_ADMIN_TOKEN, None)
        else:
            os.environ[ENV_ADMIN_TOKEN] = self._original_token

    def test_funnel_imports_require_admin_rather_than_duplicating_it(self):
        from api import auth, funnel
        self.assertIs(funnel._require_admin, auth._require_admin)

    def test_honest_zeros_with_no_events_at_all(self):
        from api.funnel import get_admin_funnel
        result = get_admin_funnel(_admin=None)
        self.assertEqual(len(result["steps"]), 7)
        for step in result["steps"]:
            self.assertEqual(step["count"], 0)
            self.assertIsNone(step["conversion_pct_from_previous"])

    def test_step_order_matches_the_stated_funnel(self):
        from api.funnel import get_admin_funnel
        result = get_admin_funnel(_admin=None)
        kinds = [s["kind"] for s in result["steps"]]
        self.assertEqual(kinds, [
            "landing_view", "signup_started", "checkout_started",
            "checkout_completed", "invite_redeemed", "bet_check_run",
            "bet_saved",
        ])

    def test_counts_and_conversion_within_range(self):
        from api.funnel import get_admin_funnel
        today = date.today().isoformat()
        anon = events.hash_user_id("anonymous-funnel-visitor")
        events.record_event(anon, events.LANDING_VIEW, at=f"{today}T00:00:00+00:00", db=self.db)
        events.record_event(anon, events.LANDING_VIEW, at=f"{today}T00:05:00+00:00", db=self.db)
        events.record_event(anon, events.SIGNUP_STARTED, at=f"{today}T00:10:00+00:00", db=self.db)

        result = get_admin_funnel(start=today, end=today, _admin=None)
        steps = {s["kind"]: s for s in result["steps"]}
        self.assertEqual(steps["landing_view"]["count"], 2)
        self.assertIsNone(steps["landing_view"]["conversion_pct_from_previous"])
        self.assertEqual(steps["signup_started"]["count"], 1)
        self.assertEqual(steps["signup_started"]["conversion_pct_from_previous"], 50.0)
        self.assertEqual(steps["checkout_started"]["count"], 0)
        # previous step (signup_started) is nonzero, so 0/1 is an honest
        # 0.0%, not a fabricated "no data" None -- None is reserved for
        # when the previous step itself is 0 (see checkout_completed below,
        # whose previous step -- checkout_started -- is 0).
        self.assertEqual(steps["checkout_started"]["conversion_pct_from_previous"], 0.0)
        self.assertIsNone(steps["checkout_completed"]["conversion_pct_from_previous"])

    def test_events_outside_the_date_range_are_excluded(self):
        from api.funnel import get_admin_funnel
        anon = events.hash_user_id("anonymous-funnel-visitor")
        last_year = (date.today() - timedelta(days=400)).isoformat()
        events.record_event(anon, events.LANDING_VIEW, at=f"{last_year}T00:00:00+00:00", db=self.db)
        result = get_admin_funnel(
            start=date.today().isoformat(), end=date.today().isoformat(), _admin=None)
        steps = {s["kind"]: s for s in result["steps"]}
        self.assertEqual(steps["landing_view"]["count"], 0)

    def test_bet_check_run_counts_first_occurrence_per_user_not_every_run(self):
        """A user who runs three bet checks after their first should not
        inflate this step to 3 -- see FIRST_OCCURRENCE_STEPS's docstring."""
        from api.funnel import get_admin_funnel
        today = date.today().isoformat()
        u1 = events.hash_user_id(1)
        u2 = events.hash_user_id(2)
        events.record_event(u1, events.BET_CHECK_RUN, at=f"{today}T00:00:00+00:00", db=self.db)
        events.record_event(u1, events.BET_CHECK_RUN, at=f"{today}T01:00:00+00:00", db=self.db)
        events.record_event(u1, events.BET_CHECK_RUN, at=f"{today}T02:00:00+00:00", db=self.db)
        events.record_event(u2, events.BET_CHECK_RUN, at=f"{today}T03:00:00+00:00", db=self.db)
        result = get_admin_funnel(start=today, end=today, _admin=None)
        steps = {s["kind"]: s for s in result["steps"]}
        self.assertEqual(steps["bet_check_run"]["count"], 2)

    def test_a_returning_users_first_bet_check_counts_on_its_own_day_only(self):
        from api.funnel import get_admin_funnel
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        today = date.today().isoformat()
        u1 = events.hash_user_id(1)
        events.record_event(u1, events.BET_CHECK_RUN, at=f"{yesterday}T00:00:00+00:00", db=self.db)
        events.record_event(u1, events.BET_CHECK_RUN, at=f"{today}T00:00:00+00:00", db=self.db)
        result = get_admin_funnel(start=today, end=today, _admin=None)
        steps = {s["kind"]: s for s in result["steps"]}
        self.assertEqual(steps["bet_check_run"]["count"], 0)

    def test_default_window_is_trailing_thirty_days_ending_today_in_utc(self):
        """The default window ends on the UTC date, NOT the host's local one.

        src.appstate.events stamps every event with
        `datetime.now(timezone.utc)`, and api.funnel._step_counts compares
        those stamps as UTC calendar dates. Asserting `date.today()` here
        would pass only on a host at or east of UTC and silently encode the
        bug it was meant to catch: on a UTC-7 machine every event recorded
        after 17:00 local lands on the NEXT UTC day, outside a window that
        ends on the local date, and the whole funnel renders zero.
        """
        from api.funnel import FUNNEL_DEFAULT_WINDOW_DAYS, get_admin_funnel
        utc_today = datetime.now(timezone.utc).date()
        result = get_admin_funnel(_admin=None)
        self.assertEqual(result["end"], utc_today.isoformat())
        expected_start = (utc_today -
                         timedelta(days=FUNNEL_DEFAULT_WINDOW_DAYS - 1)).isoformat()
        self.assertEqual(result["start"], expected_start)

    def test_end_before_start_is_400(self):
        from api.funnel import get_admin_funnel
        with self.assertRaises(HTTPException) as ctx:
            get_admin_funnel(start="2026-09-01", end="2026-08-01", _admin=None)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_bad_date_format_is_400(self):
        from api.funnel import get_admin_funnel
        with self.assertRaises(HTTPException) as ctx:
            get_admin_funnel(start="not-a-date", _admin=None)
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
