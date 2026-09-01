"""The real app's game surface requires auth in the private alpha.

Red-team finding 2 (2026-09-01): /today, /games, /odds and /betcheck were
world-readable. Decision: the whole game surface sits behind the invite
token; only /health and /meta stay open. These tests drive the REAL
api.app (not a per-test FastAPI instance) over ASGI, because router-level
dependencies are invisible to direct route-function calls.
"""
import asyncio
import json
import unittest

try:
    import fastapi  # noqa: F401
    HAVE_FASTAPI = True
except ImportError:
    HAVE_FASTAPI = False


def _request(app, method, path, headers=None):
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


@unittest.skipUnless(HAVE_FASTAPI, "fastapi not installed")
class GameSurfaceRequiresAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from api.app import app
        cls.app = app

    def test_today_is_401_without_a_token(self):
        status, _ = _request(self.app, "GET", "/today")
        self.assertEqual(status, 401)

    def test_games_is_401_without_a_token(self):
        status, _ = _request(self.app, "GET", "/games/2026-08-31")
        self.assertEqual(status, 401)

    def test_odds_is_401_without_a_token(self):
        status, _ = _request(self.app, "GET", "/odds/2026-08-31")
        self.assertEqual(status, 401)

    def test_betcheck_is_401_without_a_token(self):
        status, _ = _request(self.app, "POST", "/betcheck")
        self.assertEqual(status, 401)

    def test_health_stays_open(self):
        status, _ = _request(self.app, "GET", "/health")
        self.assertNotEqual(status, 401)

    def test_meta_stays_open(self):
        status, _ = _request(self.app, "GET", "/meta")
        self.assertNotEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
