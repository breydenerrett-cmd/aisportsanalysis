"""api/opportunities.py: GET /opportunities/{date} and GET /opportunities.

Same offline pattern as tests/test_api_games.py: the one network call
(mlb.fetch_games) is stubbed, everything else runs against real domain
code and the real (possibly empty) on-disk stores. The 401-without-a-token
check drives the real ASGI app, mirroring
tests/test_api_surface_auth.py's helper, since router-level auth
dependencies are invisible to a direct function call.
"""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch

try:
    import fastapi  # noqa: F401
    _HAVE_FASTAPI = True
except ImportError:
    _HAVE_FASTAPI = False

if _HAVE_FASTAPI:
    from api import games as games_mod
    from api import opportunities as opp_api
    from src.analysis import opportunities as opp
    from src.appstate import freshness
    from src.providers import mlb


def _schedule(date="2026-08-31"):
    return [{
        "game_pk": 990101, "date": date, "away_team": "BOS", "home_team": "NYY",
        "venue": "Yankee Stadium", "start_time_utc": f"{date}T23:05:00Z",
    }]


class _ResetEntriesCache(unittest.TestCase):
    """Same cache-isolation rationale as tests/test_api_games.py: the two
    modules share one `_entries_cache` inside api/games.py."""

    def setUp(self):
        if _HAVE_FASTAPI:
            games_mod._entries_cache = freshness.SingleFlightTTLCache(
                ttl_s=games_mod.ENTRIES_CACHE_TTL_S)


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class GetOpportunitiesForDateTests(_ResetEntriesCache):

    def test_returns_the_real_opportunities_shape(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            payload = opp_api.get_opportunities_for_date("2026-08-31")
        blob = json.loads(json.dumps(payload))  # JSON-serialisable end to end
        for key in ("date", "generated_at", "checked_games", "priced_games",
                   "rows", "qualifying", "empty_reason", "unpriced", "basis",
                   "label", "freshness"):
            self.assertIn(key, blob, f"{key!r} missing from payload")
        self.assertEqual(blob["date"], "2026-08-31")
        self.assertEqual(blob["checked_games"], 1)

    def test_malformed_date_is_a_400_not_a_502(self):
        with patch.object(mlb, "fetch_games") as fetch:
            for bad in ("not-a-date", "2026-13-45", "08/31/2026", "",
                       "2026-08-31T00:00:00Z"):
                with self.subTest(bad=bad):
                    with self.assertRaises(fastapi.HTTPException) as ctx:
                        opp_api.get_opportunities_for_date(bad)
                    self.assertEqual(ctx.exception.status_code, 400)
            fetch.assert_not_called()

    def test_schedule_provider_failure_is_a_structured_502(self):
        with patch.object(mlb, "fetch_games",
                          side_effect=mlb.MLBError("boom")):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                opp_api.get_opportunities_for_date("2026-08-31")
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("2026-08-31", ctx.exception.detail)

    def test_no_games_scheduled_is_an_honest_empty_payload(self):
        with patch.object(mlb, "fetch_games", return_value=[]):
            payload = opp_api.get_opportunities_for_date("2026-12-25")
        self.assertEqual(payload["checked_games"], 0)
        self.assertEqual(payload["rows"], [])
        self.assertEqual(payload["unpriced"], [])
        # From the constant, not a literal -- see test_opportunities.py's
        # note on the 2026-09-10 rename away from pick language.
        self.assertEqual(payload["empty_reason"], opp.EMPTY_REASON)


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class GetOpportunitiesTodayTests(_ResetEntriesCache):

    def test_uses_utc_today_like_get_today_does(self):
        from datetime import date as date_cls
        today = date_cls.today().isoformat()
        with patch.object(mlb, "fetch_games", return_value=_schedule(today)):
            payload = opp_api.get_opportunities_today()
        self.assertEqual(payload["date"], today)


def _asgi_request(app, method, path, headers=None):
    headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
        "query_string": b"", "headers": headers, "client": ("127.0.0.1", 11111),
        "server": ("testserver", 80),
    }
    captured = {}
    body_parts = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            captured["status"] = message["status"]
        elif message["type"] == "http.response.body":
            body_parts.append(message.get("body", b""))

    asyncio.new_event_loop().run_until_complete(app(scope, receive, send))
    raw = b"".join(body_parts)
    try:
        return captured.get("status"), json.loads(raw)
    except ValueError:
        return captured.get("status"), raw.decode("utf-8", "replace")


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class OpportunitiesRequiresAuthTests(unittest.TestCase):
    """Mirrors tests/test_api_surface_auth.py: the real api.app, over ASGI,
    with no APP_PUBLIC_DEMO set -- router-level auth is invisible to a
    direct function call, so only a real request through the app proves
    the gate is mounted."""

    @classmethod
    def setUpClass(cls):
        from api.app import app
        cls.app = app

    def test_opportunities_by_date_is_401_without_a_token(self):
        status, _ = _asgi_request(self.app, "GET", "/opportunities/2026-08-31")
        self.assertEqual(status, 401)

    def test_opportunities_today_is_401_without_a_token(self):
        status, _ = _asgi_request(self.app, "GET", "/opportunities")
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
