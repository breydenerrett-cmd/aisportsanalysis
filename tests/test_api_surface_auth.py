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
            captured["headers"] = {k.decode().lower(): v.decode()
                                   for k, v in message.get("headers", [])}
        elif message["type"] == "http.response.body":
            body_parts.append(message.get("body", b""))

    asyncio.new_event_loop().run_until_complete(app(scope, receive, send))
    _last_headers.clear()
    _last_headers.update(captured.get("headers") or {})
    raw = b"".join(body_parts)
    try:
        return captured.get("status"), json.loads(raw)
    except ValueError:
        return captured.get("status"), raw.decode("utf-8", "replace")


#: Response headers of the most recent `_request` call. A module-level
#: stash rather than a third return value, so every existing
#: `status, body = _request(...)` call site below stays untouched.
_last_headers: dict = {}


def _location(app, method, path) -> str:
    """The Location header of a redirect response -- what a browser would
    actually follow, which is the whole point of these two routes."""
    _request(app, method, path)
    return _last_headers.get("location")


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

    def test_betcheck_free_is_open_by_design(self):
        """The landing page's "3 Bet Checks, no card required" offer cannot
        be honoured behind the login wall the rest of the game surface sits
        behind. An empty body gets pydantic's 422, which is proof enough
        that the request reached the route rather than the auth gate --
        what must NEVER appear here is a 401/403.
        """
        status, _ = _request(self.app, "POST", "/betcheck/free")
        self.assertNotIn(status, (401, 403))

    def test_root_redirects_to_the_landing_page_unauthenticated(self):
        """The bare origin used to answer the default JSON 404 (found on
        linehound-staging, 2026-09-01) -- a visitor cannot be expected to
        know the /web prefix. A REDIRECT, not the file itself: landing.html
        loads its css/js by relative path, which only resolve correctly
        from a /web/ base URL."""
        status, _ = _request(self.app, "GET", "/")
        self.assertEqual(status, 307)
        self.assertEqual(_location(self.app, "GET", "/"), "/web/landing.html")

    def test_app_redirects_to_the_client_shell_unauthenticated(self):
        status, _ = _request(self.app, "GET", "/app")
        self.assertEqual(status, 307)
        self.assertEqual(_location(self.app, "GET", "/app"), "/web")

    def test_health_stays_open(self):
        status, _ = _request(self.app, "GET", "/health")
        self.assertNotEqual(status, 401)

    def test_meta_stays_open(self):
        status, _ = _request(self.app, "GET", "/meta")
        self.assertNotEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
