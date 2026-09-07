"""api/daily.py: GET /daily, GET /daily/{date}, GET /record (Task C1).

Same offline pattern as tests/test_api_performance.py: the direct-call
tests below exercise the route functions against whatever real (possibly
empty) on-disk stores this checkout has -- no network, no auth dependency
visible at that level. The 401-without-a-token checks drive the real ASGI
app instead, since router-level auth dependencies are invisible to a
direct function call (mirrors tests/test_api_surface_auth.py's own helper).
"""

from __future__ import annotations

import asyncio
import json
import unittest

try:
    import fastapi  # noqa: F401
    _HAVE_FASTAPI = True
except ImportError:
    _HAVE_FASTAPI = False

if _HAVE_FASTAPI:
    from api import daily as daily_api
    from src.appstate import freshness


class _ResetDailyCaches(unittest.TestCase):
    def setUp(self):
        if _HAVE_FASTAPI:
            daily_api._daily_index_cache = freshness.SingleFlightTTLCache(
                ttl_s=daily_api.DAILY_INDEX_CACHE_TTL_S)
            daily_api._daily_record_cache = freshness.SingleFlightTTLCache(
                ttl_s=daily_api.DAILY_RECORD_CACHE_TTL_S)
            daily_api._record_strip_cache = freshness.SingleFlightTTLCache(
                ttl_s=daily_api.RECORD_STRIP_CACHE_TTL_S)


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class GetDailyIndexShapeTests(_ResetDailyCaches):
    def test_returns_the_real_shape(self):
        payload = daily_api.get_daily_index(limit=10)
        blob = json.loads(json.dumps(payload))  # JSON-serialisable end to end
        self.assertIn("days", blob)
        self.assertIn("generated_at", blob)
        self.assertIsInstance(blob["days"], list)

    def test_each_day_row_has_the_documented_keys(self):
        payload = daily_api.get_daily_index(limit=30)
        for row in payload["days"]:
            for key in ("date", "n_games", "n_recommendations", "n_staked",
                       "wins", "losses", "pushes", "pending", "units_staked",
                       "units_net", "return_on_units", "avg_odds_decimal",
                       "settled", "best_bet", "worst_bet", "strongest_pregame"):
                self.assertIn(key, row, f"{key!r} missing from a /daily row")


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class GetDailyIndexLimitValidationTests(_ResetDailyCaches):
    def test_limit_zero_is_rejected(self):
        with self.assertRaises(fastapi.HTTPException) as ctx:
            daily_api.get_daily_index(limit=0)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_limit_over_200_is_rejected(self):
        with self.assertRaises(fastapi.HTTPException) as ctx:
            daily_api.get_daily_index(limit=201)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_limit_at_bounds_is_accepted(self):
        daily_api.get_daily_index(limit=1)
        daily_api.get_daily_index(limit=200)


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class GetDailyRecordShapeTests(_ResetDailyCaches):
    def test_returns_the_real_shape(self):
        payload = daily_api.get_daily_record("2026-09-05")
        blob = json.loads(json.dumps(payload))
        for key in ("date", "games", "rollup", "freshness", "notes",
                   "stake_policy", "label", "basis", "generated_at"):
            self.assertIn(key, blob, f"{key!r} missing from /daily/{{date}}")
        self.assertEqual(blob["date"], "2026-09-05")
        self.assertEqual(blob["stake_policy"], "FLAT_1U")
        self.assertEqual(blob["label"], "FROZEN PREGAME RECORD")

    def test_a_recommendation_carries_the_documented_keys(self):
        payload = daily_api.get_daily_record("2026-09-05")
        found = False
        for game in payload["games"]:
            for rec in game["recommendations"]:
                found = True
                for key in ("system_id", "system_class", "market_key", "side",
                           "line", "price_american", "decision_utc", "verdict",
                           "consensus_fair", "books_at_decision",
                           "market_implied_probability", "stated_implied_probability",
                           "value_points", "known_at_grade", "p_model_provenance",
                           "stake_units", "thesis", "counterarguments", "bet_id",
                           "staked", "settlement"):
                    self.assertIn(key, rec, f"{key!r} missing from a recommendation")
                self.assertEqual(rec["stake_units"], 1.0)
                for skey in ("status", "profit_units", "settled_day"):
                    self.assertIn(skey, rec["settlement"])
        self.assertTrue(found, "expected at least one recommendation in the real "
                              "2026-09-05 record to check shape against")

    def test_malformed_date_is_a_400(self):
        for bad in ("not-a-date", "2026-13-45", "08/31/2026", "",
                   "2026-08-31T00:00:00Z"):
            with self.subTest(bad=bad):
                with self.assertRaises(fastapi.HTTPException) as ctx:
                    daily_api.get_daily_record(bad)
                self.assertEqual(ctx.exception.status_code, 400)

    def test_a_date_with_nothing_on_it_is_an_honest_empty_record(self):
        payload = daily_api.get_daily_record("2019-01-01")
        self.assertEqual(payload["games"], [])
        self.assertEqual(payload["rollup"]["n_games"], 0)


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class GetRecordStripShapeTests(_ResetDailyCaches):
    def test_returns_the_real_shape(self):
        payload = daily_api.get_record_strip()
        blob = json.loads(json.dumps(payload))
        for key in ("today", "last_7", "last_30", "settled_through", "note",
                   "generated_at"):
            self.assertIn(key, blob, f"{key!r} missing from /record")

    def test_a_present_window_has_the_documented_keys(self):
        payload = daily_api.get_record_strip()
        for window_key in ("today", "last_7", "last_30"):
            window = payload[window_key]
            if window is None:
                continue
            for key in ("label", "from_date", "to_date", "wins", "losses",
                       "pushes", "units_net", "return_on_units", "n_settled",
                       "pending"):
                self.assertIn(key, window, f"{key!r} missing from {window_key!r}")


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
class DailyRequiresAuthTests(unittest.TestCase):
    """Mirrors tests/test_api_performance.py's own auth test: the real
    api.app, over ASGI, with no APP_PUBLIC_DEMO set -- router-level auth
    is invisible to a direct function call, so only a real request through
    the app proves the gate is mounted."""

    @classmethod
    def setUpClass(cls):
        from api.app import app
        cls.app = app

    def test_daily_index_is_401_without_a_token(self):
        status, _ = _asgi_request(self.app, "GET", "/daily")
        self.assertEqual(status, 401)

    def test_daily_record_is_401_without_a_token(self):
        status, _ = _asgi_request(self.app, "GET", "/daily/2026-08-31")
        self.assertEqual(status, 401)

    def test_record_strip_is_401_without_a_token(self):
        status, _ = _asgi_request(self.app, "GET", "/record")
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
