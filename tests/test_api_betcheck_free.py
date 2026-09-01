"""api/betcheck.py's POST /betcheck/free -- the anonymous, lifetime-capped
free tier the landing page promises.

Same skip-if-no-fastapi, call-the-route-function-directly pattern as
tests/test_api_betcheck.py (see that module's docstring): the one network
call is patched to a fixed offline schedule, and the free-check store is
pointed at a per-test sqlite file.

WHAT THESE TESTS ARE PINNING
-------------------------------
The three properties that make "3 free Bet Checks, no card required" a
promise rather than marketing: the count is the SERVER's (a client cannot
assert it, forge it, or reset it by editing a token), the fourth call is a
structured refusal rather than a fourth check, and what the free tier
actually serves is the REAL Bet Check -- not a degraded preview.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import patch

try:
    import fastapi  # noqa: F401
    _HAVE_FASTAPI = True
except ImportError:
    _HAVE_FASTAPI = False

if _HAVE_FASTAPI:
    from api import betcheck as betcheck_api
    from src.appstate import events, freechecks
    from src.appstate import users as users_store
    from src.providers import mlb


def _schedule(date="2026-08-31"):
    return [{
        "game_pk": 990101, "date": date, "away_team": "BOS", "home_team": "NYY",
        "venue": "Yankee Stadium", "start_time_utc": f"{date}T23:05:00Z",
    }]


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    """Enough of a Request for src.appstate.ratelimit's IP-keyed
    dependency -- it reads `request.client.host` and nothing else."""

    def __init__(self, host="203.0.113.7"):
        self.client = _FakeClient(host)


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class _FreeCheckBase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        for module, name in ((users_store, "db_path"), (events, "db_path")):
            patcher = mock.patch.object(module, name, lambda: self.db)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def _body(self, **overrides):
        defaults = dict(date="2026-08-31", away="BOS", home="NYY", side="home",
                        american_price=-125)
        defaults.update(overrides)
        return betcheck_api.BetCheckRequest(**defaults)

    def _free(self, token=None, **overrides):
        return betcheck_api.post_betcheck_free(
            self._body(**overrides), free_check_token=token)


class FreeBudgetTests(_FreeCheckBase):

    def test_three_checks_then_a_structured_exhaustion(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            first = self._free()
            token = first["free_check"]["token"]
            self.assertEqual(first["free_check"]["remaining"], 2)
            self.assertEqual(self._free(token)["free_check"]["remaining"], 1)
            self.assertEqual(self._free(token)["free_check"]["remaining"], 0)
            with self.assertRaises(fastapi.HTTPException) as ctx:
                self._free(token)
        self.assertEqual(ctx.exception.status_code, 402)
        detail = ctx.exception.detail
        self.assertEqual(detail["error"], "free_checks_exhausted")
        self.assertEqual(detail["remaining"], 0)
        self.assertEqual(detail["free_check_token"], token)
        # The refusal has to tell the visitor where to go next, or it is
        # just a dead end at the exact moment they are most interested.
        self.assertIn("/signup", detail["message"])

    def test_every_response_carries_the_remaining_count(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            first = self._free()
            block = first["free_check"]
        self.assertEqual(block["limit"], freechecks.FREE_CHECK_LIFETIME_LIMIT)
        self.assertEqual(block["used"], 1)
        self.assertEqual(block["remaining"],
                         freechecks.FREE_CHECK_LIFETIME_LIMIT - 1)

    def test_the_exhausted_check_happens_before_any_analysis(self):
        """A spent visitor must not be able to keep pulling the domain path
        (and the schedule provider behind it) for free."""
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            token = self._free()["free_check"]["token"]
            self._free(token)
            self._free(token)
        with patch.object(mlb, "fetch_games") as fetch:
            with self.assertRaises(fastapi.HTTPException):
                self._free(token)
        fetch.assert_not_called()

    def test_the_counter_survives_a_restart(self):
        """Nothing in this process remembers the count between calls -- the
        sqlite file does. Simulated by dropping every cached module-level
        state a restart would drop: the store is re-read from disk on each
        call, so a fresh lookup is the same evidence."""
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            token = self._free()["free_check"]["token"]
            self._free(token)
            self._free(token)
            reread = freechecks.get_grant(token)
            self.assertTrue(reread.exhausted)
            with self.assertRaises(fastapi.HTTPException) as ctx:
                self._free(token)
        self.assertEqual(ctx.exception.status_code, 402)

    def test_a_tampered_token_gets_a_fresh_identity_not_extra_checks(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            token = self._free()["free_check"]["token"]
            self._free(token)
            self._free(token)
            forged = token[:-1] + ("A" if token[-1] != "A" else "B")
            result = self._free(forged)
        # A brand-new identity with a brand-new budget -- NOT the spent
        # one's remaining checks, and NOT a fourth check on the real token.
        self.assertNotEqual(result["free_check"]["token"], forged)
        self.assertNotEqual(result["free_check"]["token"], token)
        self.assertEqual(result["free_check"]["used"], 1)
        self.assertTrue(freechecks.get_grant(token).exhausted)

    def test_a_client_cannot_assert_its_own_remaining_count(self):
        """The request body has no place to put a count, and the response's
        count comes from the store, not from anything the caller sent."""
        self.assertNotIn("remaining",
                         betcheck_api.BetCheckRequest.model_fields)
        self.assertNotIn("free_check_token",
                         betcheck_api.BetCheckRequest.model_fields)


class FreeErrorPathTests(_FreeCheckBase):
    """A check the visitor never received must never cost one of their
    three -- and must never leave a half-started identity behind."""

    def test_unknown_game_404_spends_nothing_and_mints_nothing(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                self._free(away="SEA", home="TEX")
        self.assertEqual(ctx.exception.status_code, 404)
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            after = self._free()
        self.assertEqual(after["free_check"]["used"], 1)

    def test_schedule_failure_502_spends_nothing(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            token = self._free()["free_check"]["token"]
        with patch.object(mlb, "fetch_games", side_effect=mlb.MLBError("boom")):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                self._free(token)
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(freechecks.get_grant(token).checks_used, 1)

    def test_malformed_date_400_spends_nothing(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            token = self._free()["free_check"]["token"]
            with self.assertRaises(fastapi.HTTPException) as ctx:
                self._free(token, date="not-a-date")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(freechecks.get_grant(token).checks_used, 1)


class FreeCheckIsTheRealBetCheckTests(_FreeCheckBase):
    """The free tier must be the product, not a demo of it."""

    def test_the_free_payload_matches_the_paid_one_field_for_field(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            paid = betcheck_api.post_betcheck(self._body())
            free = self._free()
        free_without_budget = {k: v for k, v in free.items() if k != "free_check"}
        self.assertEqual(sorted(free_without_budget), sorted(paid))
        self.assertEqual(free_without_budget, paid)

    def test_counterargument_lines_are_present_and_never_empty(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            free = self._free()
        self.assertTrue(free["counterargument_lines"])

    def test_recommendation_stays_null_on_the_free_tier_too(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            free = self._free()
        self.assertIsNone(free["recommendation"])


class FreeCheckEventTests(_FreeCheckBase):

    def test_a_successful_free_check_records_free_bet_check(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            free = self._free()
        rows = events.list_events(db=self.db)
        self.assertEqual([r.kind for r in rows], [events.FREE_BET_CHECK])
        self.assertEqual(rows[0].properties, {"date": "2026-08-31"})
        # Keyed on the grant's HASH, never the raw token (a live
        # credential) and never a user id (there is no user).
        grant = freechecks.get_grant(free["free_check"]["token"])
        self.assertEqual(
            rows[0].user_hash,
            events.hash_user_id(betcheck_api.FREE_CHECK_EVENT_IDENTITY_PREFIX
                                + grant.token_hash))

    def test_the_raw_token_never_reaches_the_analytics_table(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            free = self._free()
        token = free["free_check"]["token"]
        for row in events.list_events(db=self.db):
            self.assertNotIn(token, row.user_hash)
            self.assertNotIn(token, str(row.properties))

    def test_a_refused_fourth_check_records_nothing(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            token = self._free()["free_check"]["token"]
            self._free(token)
            self._free(token)
            before = len(events.list_events(db=self.db))
            with self.assertRaises(fastapi.HTTPException):
                self._free(token)
        self.assertEqual(len(events.list_events(db=self.db)), before)

    def test_free_bet_check_is_distinct_from_the_paid_bet_check_run(self):
        """Two kinds on purpose: merging them would make "a real customer's
        first check" -- the activation number -- uncountable."""
        self.assertNotEqual(events.FREE_BET_CHECK, events.BET_CHECK_RUN)
        self.assertIn(events.FREE_BET_CHECK, events.EVENT_KINDS)

    def test_a_broken_events_db_never_breaks_the_free_response(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()), \
             patch.object(events, "record_event",
                          side_effect=RuntimeError("disk full")):
            payload = self._free()
        self.assertIn("query", payload)
        self.assertEqual(payload["free_check"]["remaining"], 2)


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class FreeRouteRateLimitTests(unittest.TestCase):
    """The free route is the one bet-check surface reachable with no
    credential, so it cannot be farmed for odds data one game at a time."""

    def test_the_hourly_per_ip_limit_fires(self):
        limiter = betcheck_api._free_betcheck_limiter
        self.assertEqual(limiter.limit,
                         betcheck_api.FREE_BETCHECK_RATE_LIMIT_PER_HOUR)
        self.assertEqual(limiter.window_s, 3600.0)
        request = _FakeRequest(host="198.51.100.4")
        for _ in range(betcheck_api.FREE_BETCHECK_RATE_LIMIT_PER_HOUR):
            betcheck_api._free_rate_limited(request)
        with self.assertRaises(fastapi.HTTPException) as ctx:
            betcheck_api._free_rate_limited(request)
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.detail["error"], "rate_limited")

    def test_it_is_far_tighter_than_the_authed_route(self):
        self.assertLess(betcheck_api.FREE_BETCHECK_RATE_LIMIT_PER_HOUR,
                        betcheck_api.BETCHECK_RATE_LIMIT_PER_MIN)


if __name__ == "__main__":
    unittest.main()
