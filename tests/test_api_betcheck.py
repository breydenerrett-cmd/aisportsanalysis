"""api/betcheck.py: POST /betcheck, with the network call stubbed out.

SKIP-IF-NO-FASTAPI, LIKE THE REST OF api/
------------------------------------------
Same pattern as tests/test_api_games.py: api/ is allowed to depend on
FastAPI (tests/test_api_boundary.py is the test that enforces src/ never
does); this repo's test environment does not always have it installed. If
FastAPI is unavailable, api/betcheck.py cannot even be imported, so the
whole class is skipped rather than the suite failing on an unrelated
dependency gap.

The endpoint function is a plain callable (an APIRouter route decorator
registers a route and returns the same function), so it is exercised
directly here -- no live HTTP server and no TestClient needed. The one
network call it makes (mlb.fetch_games) is patched to a fixed, offline
schedule; the historical store is the real repo store, read offline, the
same way tests/test_api_today.py and tests/test_api_games.py already do.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    import fastapi  # noqa: F401
    from pydantic import ValidationError
    _HAVE_FASTAPI = True
except ImportError:
    _HAVE_FASTAPI = False

if _HAVE_FASTAPI:
    from api import betcheck as betcheck_api
    from src.appstate import events
    from src.providers import mlb


class _FakeState:
    def __init__(self, user_id):
        self.user_id = user_id


class _FakeRequest:
    """Stands in for the Request object api/betcheck.py reads
    `request.state.user_id` off of -- see api/auth.py's get_current_user."""

    def __init__(self, user_id=None):
        self.state = _FakeState(user_id)


def _schedule(date="2026-08-31"):
    return [{
        "game_pk": 990101, "date": date, "away_team": "BOS", "home_team": "NYY",
        "venue": "Yankee Stadium", "start_time_utc": f"{date}T23:05:00Z",
    }]


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class RequestValidationTests(unittest.TestCase):
    def test_side_outside_away_home_is_rejected_at_the_schema(self):
        with self.assertRaises(ValidationError):
            betcheck_api.BetCheckRequest(date="2026-08-31", away="BOS",
                                         home="NYY", side="draw",
                                         american_price=-125)

    def test_implausible_price_magnitude_is_rejected(self):
        with self.assertRaises(ValidationError):
            betcheck_api.BetCheckRequest(date="2026-08-31", away="BOS",
                                         home="NYY", side="home",
                                         american_price=5)

    def test_a_plausible_request_validates(self):
        body = betcheck_api.BetCheckRequest(date="2026-08-31", away="BOS",
                                            home="NYY", side="home",
                                            american_price=-125)
        self.assertEqual(body.american_price, -125)


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class PostBetcheckTests(unittest.TestCase):

    def test_returns_the_bet_check_contract_shape(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            body = betcheck_api.BetCheckRequest(
                date="2026-08-31", away="BOS", home="NYY", side="home",
                american_price=-125)
            payload = betcheck_api.post_betcheck(body)
        self.assertIn("query", payload)
        self.assertIn("game", payload)
        self.assertIn("counterargument", payload)
        self.assertIn("counterargument_lines", payload)
        self.assertIn("recommendation", payload)
        self.assertIsNone(payload["recommendation"])
        self.assertEqual(payload["game"]["away"], "BOS")
        self.assertEqual(payload["game"]["home"], "NYY")

    def test_unknown_game_is_a_structured_404(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            body = betcheck_api.BetCheckRequest(
                date="2026-08-31", away="SEA", home="TEX", side="home",
                american_price=-125)
            with self.assertRaises(fastapi.HTTPException) as ctx:
                betcheck_api.post_betcheck(body)
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn("SEA", ctx.exception.detail)
        self.assertIn("TEX", ctx.exception.detail)

    def test_unknown_date_is_a_structured_404_not_a_crash(self):
        with patch.object(mlb, "fetch_games", return_value=[]):
            body = betcheck_api.BetCheckRequest(
                date="2026-12-25", away="BOS", home="NYY", side="home",
                american_price=-125)
            with self.assertRaises(fastapi.HTTPException) as ctx:
                betcheck_api.post_betcheck(body)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_schedule_provider_failure_is_a_structured_502(self):
        with patch.object(mlb, "fetch_games",
                          side_effect=mlb.MLBError("boom")):
            body = betcheck_api.BetCheckRequest(
                date="2026-08-31", away="BOS", home="NYY", side="home",
                american_price=-125)
            with self.assertRaises(fastapi.HTTPException) as ctx:
                betcheck_api.post_betcheck(body)
        self.assertEqual(ctx.exception.status_code, 502)

    def test_malformed_date_is_a_400_not_a_502(self):
        """Same fix as api/games.py and api/odds.py: a malformed date is
        refused before it ever reaches mlb.fetch_games."""
        with patch.object(mlb, "fetch_games") as fetch:
            for bad in ("not-a-date", "2026-13-45", "08/31/2026", ""):
                with self.subTest(bad=bad):
                    body = betcheck_api.BetCheckRequest(
                        date=bad, away="BOS", home="NYY", side="home",
                        american_price=-125)
                    with self.assertRaises(fastapi.HTTPException) as ctx:
                        betcheck_api.post_betcheck(body)
                    self.assertEqual(ctx.exception.status_code, 400)
            fetch.assert_not_called()

    def test_away_home_are_bounded_and_reflected_only_up_to_the_bound(self):
        """Bet Check's 404 names what it searched for, including the
        club fields verbatim -- an unbounded club field would let a client
        grow that detail message arbitrarily. max_length on the request
        model bounds it before it is ever reflected."""
        with self.assertRaises(ValidationError):
            betcheck_api.BetCheckRequest(
                date="2026-08-31", away="X" * 41, home="NYY", side="home",
                american_price=-125)
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            body = betcheck_api.BetCheckRequest(
                date="2026-08-31", away="X" * 40, home="NYY", side="home",
                american_price=-125)
            with self.assertRaises(fastapi.HTTPException) as ctx:
                betcheck_api.post_betcheck(body)
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn("X" * 40, ctx.exception.detail)

    def test_no_win_probability_or_ev_language_at_the_wire(self):
        import json
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            body = betcheck_api.BetCheckRequest(
                date="2026-08-31", away="BOS", home="NYY", side="home",
                american_price=-125)
            payload = betcheck_api.post_betcheck(body)
        blob = json.dumps(payload).lower()
        for forbidden in ("win_probability", "win_prob", "true_probability"):
            self.assertNotIn(forbidden, blob)


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class BetCheckRunEventTests(unittest.TestCase):
    """bet_check_run wiring: recorded on a successful check with an authed
    caller, never without one and never on the 400/404/502 paths."""

    def _body(self, **overrides):
        defaults = dict(date="2026-08-31", away="BOS", home="NYY", side="home",
                        american_price=-125)
        defaults.update(overrides)
        return betcheck_api.BetCheckRequest(**defaults)

    def test_no_request_records_nothing(self):
        """Every existing direct-call test above calls post_betcheck with no
        Request -- must keep behaving exactly as before, just
        uninstrumented."""
        with patch.object(mlb, "fetch_games", return_value=_schedule()), \
             patch.object(events, "record_event_safe") as safe:
            betcheck_api.post_betcheck(self._body())
        safe.assert_not_called()

    def test_success_records_bet_check_run_for_the_authed_caller(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()), \
             patch.object(events, "record_event_safe") as safe:
            betcheck_api.post_betcheck(self._body(), request=_FakeRequest(9))
        safe.assert_called_once_with(
            9, events.BET_CHECK_RUN, {"date": "2026-08-31"})

    def test_unknown_game_404_records_nothing(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()), \
             patch.object(events, "record_event_safe") as safe:
            with self.assertRaises(fastapi.HTTPException):
                betcheck_api.post_betcheck(
                    self._body(away="SEA", home="TEX"), request=_FakeRequest(9))
        safe.assert_not_called()

    def test_schedule_failure_502_records_nothing(self):
        with patch.object(mlb, "fetch_games", side_effect=mlb.MLBError("boom")), \
             patch.object(events, "record_event_safe") as safe:
            with self.assertRaises(fastapi.HTTPException):
                betcheck_api.post_betcheck(self._body(), request=_FakeRequest(9))
        safe.assert_not_called()

    def test_malformed_date_400_records_nothing(self):
        with patch.object(mlb, "fetch_games") as fetch, \
             patch.object(events, "record_event_safe") as safe:
            with self.assertRaises(fastapi.HTTPException):
                betcheck_api.post_betcheck(
                    self._body(date="not-a-date"), request=_FakeRequest(9))
        fetch.assert_not_called()
        safe.assert_not_called()

    def test_no_user_id_on_the_request_records_nothing(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()), \
             patch.object(events, "record_event_safe") as safe:
            betcheck_api.post_betcheck(self._body(), request=_FakeRequest(None))
        safe.assert_not_called()

    def test_a_broken_events_db_never_breaks_the_response(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()), \
             patch.object(events, "record_event",
                          side_effect=RuntimeError("disk full")):
            payload = betcheck_api.post_betcheck(self._body(), request=_FakeRequest(9))
        self.assertIn("query", payload)


if __name__ == "__main__":
    unittest.main()
