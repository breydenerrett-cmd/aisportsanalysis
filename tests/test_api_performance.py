"""api/performance.py: GET /performance.

Same offline pattern as tests/test_api_opportunities.py: the direct-call
tests below exercise `api.performance.get_performance` (shape, limit
validation) against whatever real (possibly empty) on-disk stores this
checkout has -- no network, no auth dependency visible at that level. The
401-without-a-token check drives the real ASGI app instead, since
router-level auth dependencies are invisible to a direct function call
(mirrors tests/test_api_surface_auth.py's own helper).
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
    from api import performance as perf_api
    from src.appstate import freshness


class _ResetPerformanceCache(unittest.TestCase):
    def setUp(self):
        if _HAVE_FASTAPI:
            perf_api._performance_cache = freshness.SingleFlightTTLCache(
                ttl_s=perf_api.PERFORMANCE_CACHE_TTL_S)


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class GetPerformanceShapeTests(_ResetPerformanceCache):
    def test_returns_the_real_performance_shape(self):
        payload = perf_api.get_performance(limit=10)
        blob = json.loads(json.dumps(payload))  # JSON-serialisable end to end
        for key in ("label", "generated_at", "disclaimer", "freshness",
                   "classes", "systems", "recent_picks", "reasoning_split",
                   "series", "notes"):
            self.assertIn(key, blob, f"{key!r} missing from payload")
        self.assertEqual(blob["label"], "PAPER / RESEARCH PERFORMANCE")

    def test_class_rollup_keys(self):
        payload = perf_api.get_performance(limit=5)
        for cls_name in ("CONTROL", "MARKET_REFERENCE", "FORWARD_TEST", "ALL"):
            self.assertIn(cls_name, payload["classes"])
            for key in ("n_settled", "wins", "losses", "pushes",
                       "units_staked", "units_net", "return_on_units",
                       "hit_rate", "drawdown_max"):
                self.assertIn(key, payload["classes"][cls_name])

    def test_recent_picks_respects_limit(self):
        payload = perf_api.get_performance(limit=3)
        self.assertLessEqual(len(payload["recent_picks"]), 3)

    def test_no_banned_field_names_in_standings(self):
        payload = perf_api.get_performance(limit=5)
        for row in payload["systems"]:
            self.assertNotIn("roi_units", row)
            self.assertIn("return_on_units", row)

    def test_cuts_present_with_documented_keys(self):
        payload = perf_api.get_performance(limit=5)
        self.assertIn("cuts", payload)
        self.assertIn("cuts_note", payload)
        self.assertEqual(
            set(payload["cuts"]),
            {"by_market", "by_odds_range", "by_grade", "by_class", "rolling"})

    def test_cuts_bucket_shape(self):
        payload = perf_api.get_performance(limit=5)
        expected = {"key", "label", "n_settled", "wins", "losses", "pushes",
                   "hit_rate", "units_staked", "units_net",
                   "return_on_units", "avg_odds_decimal", "thin"}
        for cut_name, buckets in payload["cuts"].items():
            for bucket in buckets:
                self.assertEqual(set(bucket), expected, cut_name)

    def test_rolling_has_exactly_last_7_and_last_30(self):
        payload = perf_api.get_performance(limit=5)
        keys = [b["key"] for b in payload["cuts"]["rolling"]]
        self.assertEqual(keys, ["last_7", "last_30"])

    def test_cuts_is_json_serialisable(self):
        payload = perf_api.get_performance(limit=5)
        json.dumps(payload["cuts"])  # must not raise


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class GetPerformanceLimitValidationTests(_ResetPerformanceCache):
    def test_limit_zero_is_rejected(self):
        with self.assertRaises(fastapi.HTTPException) as ctx:
            perf_api.get_performance(limit=0)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_limit_over_200_is_rejected(self):
        with self.assertRaises(fastapi.HTTPException) as ctx:
            perf_api.get_performance(limit=201)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_limit_at_bounds_is_accepted(self):
        # 1 and 200 are the documented inclusive bounds -- must not raise.
        perf_api.get_performance(limit=1)
        perf_api.get_performance(limit=200)


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
class PerformanceRequiresAuthTests(unittest.TestCase):
    """Mirrors tests/test_api_opportunities.py's own auth test: the real
    api.app, over ASGI, with no APP_PUBLIC_DEMO set -- router-level auth
    is invisible to a direct function call, so only a real request through
    the app proves the gate is mounted."""

    @classmethod
    def setUpClass(cls):
        from api.app import app
        cls.app = app

    def test_performance_is_401_without_a_token(self):
        status, _ = _asgi_request(self.app, "GET", "/performance")
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
