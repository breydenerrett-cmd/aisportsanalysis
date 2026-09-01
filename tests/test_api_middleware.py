"""api/app.py's request-logging middleware + structured-500 handling.

Skip-if-no-fastapi (see tests/test_api_auth.py's module docstring). The
middleware is an ASGI-shaped async function, so it is exercised directly
with asyncio.run and a minimal Starlette Request built from a bare scope --
no TestClient/HTTP layer, same constraint as every other api/ test here.
Assertions are on the STDERR LOG LINE'S CONTENT, because a redaction bug
that only shows up in a live log stream and never in a unit test is exactly
the failure this module exists to prevent (same reasoning
tests/test_appstate_reqlog.py's docstring gives for testing format_line
directly).
"""

from __future__ import annotations

import contextlib
import io
import unittest

try:
    import fastapi  # noqa: F401
    from starlette.requests import Request
    from starlette.responses import JSONResponse, PlainTextResponse
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

if HAS_FASTAPI:
    from api.app import log_requests, _route_template


def _request(path="/game/2026-08-31/BOS/NYY", method="GET",
             route_path=None, user_id=None):
    scope = {"type": "http", "method": method, "path": path,
             "headers": [], "query_string": b""}
    request = Request(scope)
    if route_path is not None:
        class _Route:
            path = route_path
        request.scope["route"] = _Route()
    if user_id is not None:
        request.state.user_id = user_id
    return request


async def _run(request, call_next):
    return await log_requests(request, call_next)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class RouteTemplateTests(unittest.TestCase):

    def test_uses_the_matched_route_template_when_present(self):
        request = _request(path="/game/2026-08-31/BOS/NYY",
                           route_path="/game/{date}/{away}/{home}")
        self.assertEqual(_route_template(request), "/game/{date}/{away}/{home}")

    def test_falls_back_to_the_raw_path_when_no_route_matched(self):
        request = _request(path="/no/such/route")
        self.assertEqual(_route_template(request), "/no/such/route")


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class LogRequestsTests(unittest.TestCase):

    def _capture(self, request, call_next):
        import asyncio
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            response = asyncio.run(_run(request, call_next))
        return response, buf.getvalue()

    def test_normal_request_logs_method_path_status_and_dash_user(self):
        async def call_next(_request):
            return JSONResponse({"ok": True}, status_code=200)

        request = _request(route_path="/health")
        response, log = self._capture(request, call_next)
        self.assertEqual(response.status_code, 200)
        self.assertIn("method=GET", log)
        self.assertIn("path=/health", log)
        self.assertIn("status=200", log)
        self.assertIn("user=-", log)

    def test_authed_request_logs_a_hashed_user_not_the_raw_id(self):
        from src.appstate import reqlog

        async def call_next(_request):
            return JSONResponse({"ok": True}, status_code=200)

        request = _request(route_path="/my-bets", user_id=42)
        _response, log = self._capture(request, call_next)
        self.assertIn(f"user={reqlog.user_ref(42)}", log)
        self.assertNotIn("user=42", log)

    def test_no_bearer_token_or_email_ever_reaches_the_log_line(self):
        """The middleware never sees the Authorization header value at all
        (get_current_user resolves it, not the middleware) -- this proves
        the log line stays clean even when the request carried one."""
        async def call_next(_request):
            return JSONResponse({"ok": True}, status_code=200)

        scope = {"type": "http", "method": "GET", "path": "/my-bets",
                 "headers": [(b"authorization", b"Bearer sekrit-token-value")],
                 "query_string": b""}
        request = Request(scope)
        request.scope["route"] = type("R", (), {"path": "/my-bets"})()
        _response, log = self._capture(request, call_next)
        self.assertNotIn("sekrit-token-value", log)
        self.assertNotIn("Bearer", log)

    def test_unhandled_exception_becomes_a_structured_500_with_no_traceback(self):
        async def call_next(_request):
            raise ValueError("boom -- something in the domain layer broke")

        request = _request(route_path="/betcheck", method="POST")
        response, log = self._capture(request, call_next)
        self.assertEqual(response.status_code, 500)
        body = response.body.decode("utf-8")
        self.assertIn("error_id", body)
        self.assertNotIn("Traceback", body)
        self.assertNotIn("boom -- something in the domain layer broke", body)
        # The error id in the client response is the same one on the
        # server-side log line -- that correlation is the whole point.
        import json
        error_id = json.loads(body)["error_id"]
        self.assertIn(f"error_id={error_id}", log)
        self.assertIn("status=500", log)

    def test_each_unhandled_exception_gets_a_distinct_error_id(self):
        async def call_next(_request):
            raise RuntimeError("again")

        import json
        ids = set()
        for _ in range(3):
            request = _request(route_path="/betcheck", method="POST")
            response, _log = self._capture(request, call_next)
            ids.add(json.loads(response.body.decode("utf-8"))["error_id"])
        self.assertEqual(len(ids), 3)


if __name__ == "__main__":
    unittest.main()
