"""The request-body cap (api/bodylimit.py), red team 2026-10-19: one 52 MB POST
raised the process's RSS by about 460 MB on a 1 GB machine.

The middleware is pure ASGI, so most of this runs without FastAPI (Linux CI).
The last class drives the REAL app, which also catches the wiring mistake (the
middleware existing but not being the outermost layer) and is skipped where
FastAPI is absent.
"""

from __future__ import annotations

import asyncio
import json
import unittest

from api import bodylimit
from api.bodylimit import BodyLimitMiddleware

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

LIMIT = bodylimit.DEFAULT_MAX_BODY_BYTES


def drive(app, *, path="/x", chunks=(b"",), declared=None, method="POST"):
    """Run one request through `app`; return (status, body bytes, messages the
    app asked to receive)."""
    headers = []
    if declared is not None:
        headers.append((b"content-length", str(declared).encode()))
    scope = {"type": "http", "method": method, "path": path, "headers": headers,
             "client": ("127.0.0.1", 1)}
    queue = list(chunks)
    pulled = []
    sent = []

    async def receive():
        if not queue:
            return {"type": "http.disconnect"}
        body = queue.pop(0)
        pulled.append(len(body))
        return {"type": "http.request", "body": body, "more_body": bool(queue)}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    status = next((m["status"] for m in sent if m["type"] == "http.response.start"), None)
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, body, pulled


async def reading_app(scope, receive, send):
    """Reads the whole body, answers 200 with its length."""
    total = 0
    while True:
        message = await receive()
        total += len(message.get("body") or b"")
        if not message.get("more_body"):
            break
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": str(total).encode()})


async def swallowing_app(scope, receive, send):
    """Like api/app.py's log_requests: turns every exception into a 500."""
    try:
        await reading_app(scope, receive, send)
    except Exception:  # noqa: BLE001
        await send({"type": "http.response.start", "status": 500, "headers": []})
        await send({"type": "http.response.body", "body": b"internal"})


class DeclaredLengthTests(unittest.TestCase):
    def test_over_limit_content_length_is_413_and_nothing_is_read(self):
        status, body, pulled = drive(BodyLimitMiddleware(reading_app), declared=LIMIT + 1,
                                     chunks=(b"x" * 10,))
        self.assertEqual(status, 413)
        self.assertEqual(json.loads(body)["error"], "payload_too_large")
        self.assertEqual(pulled, [], "the body must not be read at all")

    def test_a_52mb_declaration_is_refused_without_buffering(self):
        status, _, pulled = drive(BodyLimitMiddleware(reading_app), declared=52 * 1024 * 1024)
        self.assertEqual((status, pulled), (413, []))

    def test_exactly_the_limit_passes(self):
        status, body, _ = drive(BodyLimitMiddleware(reading_app), declared=LIMIT,
                                chunks=(b"x" * LIMIT,))
        self.assertEqual((status, body), (200, str(LIMIT).encode()))

    def test_small_and_empty_bodies_pass(self):
        for chunks in ((b"",), (b'{"a":1}',)):
            status, _, _ = drive(BodyLimitMiddleware(reading_app), chunks=chunks)
            self.assertEqual(status, 200)

    def test_garbage_content_length_falls_back_to_counting(self):
        mw = BodyLimitMiddleware(reading_app)
        status, _, _ = drive(mw, declared="not-a-number", chunks=(b"x" * (LIMIT + 1),))
        self.assertEqual(status, 413)


class ChunkedTests(unittest.TestCase):
    def test_chunked_body_past_the_limit_is_aborted_early(self):
        chunks = [b"x" * 16384] * 400          # ~6.5 MB, no Content-Length
        status, _, pulled = drive(BodyLimitMiddleware(reading_app), chunks=chunks)
        self.assertEqual(status, 413)
        self.assertLess(sum(pulled), LIMIT + 16384 + 1, "stops at the first chunk past the limit")

    def test_a_lying_content_length_is_still_caught(self):
        status, _, _ = drive(BodyLimitMiddleware(reading_app), declared=10,
                             chunks=[b"x" * 16384] * 8)
        self.assertEqual(status, 413)

    def test_an_app_that_swallows_exceptions_still_yields_413_not_500(self):
        status, body, _ = drive(BodyLimitMiddleware(swallowing_app), chunks=[b"x" * 16384] * 8)
        self.assertEqual(status, 413)
        self.assertNotIn(b"internal", body)

    def test_chunked_body_under_the_limit_passes(self):
        status, body, _ = drive(BodyLimitMiddleware(reading_app), chunks=[b"x" * 1000] * 10)
        self.assertEqual((status, body), (200, b"10000"))


class ScopeAndPathTests(unittest.TestCase):
    def test_non_http_scopes_pass_through(self):
        seen = []

        async def inner(scope, receive, send):
            seen.append(scope["type"])

        asyncio.run(BodyLimitMiddleware(inner)({"type": "lifespan"}, None, None))
        self.assertEqual(seen, ["lifespan"])

    def test_stripe_webhook_has_its_own_larger_limit(self):
        mw = BodyLimitMiddleware(reading_app)
        status, _, _ = drive(mw, path="/billing/webhook", declared=LIMIT + 1,
                             chunks=(b"x" * (LIMIT + 1),))
        self.assertEqual(status, 200)
        status, _, _ = drive(mw, path="/billing/webhook",
                             declared=bodylimit.PATH_LIMITS["/billing/webhook"] + 1)
        self.assertEqual(status, 413)

    @unittest.skipUnless(HAS_FASTAPI, "api.hounds_create imports fastapi")
    def test_the_zapier_callback_ceiling_fits_under_the_global_limit(self):
        """The menu-size spec comes back through POST /hounds/create/translate/callback,
        which caps itself at 64 KB; the global cap must never be below that."""
        from api import hounds_create
        self.assertLessEqual(hounds_create.MAX_CALLBACK_BYTES, LIMIT)
        from src.hounds.english import translate
        self.assertLess(translate.MAX_SPEC_JSON * 3, LIMIT)  # even heavily \u-escaped


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class RealAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from api.app import app
        cls.app = app

    def test_the_red_team_body_is_refused_by_the_real_app(self):
        status, body, pulled = drive(self.app, path="/auth/login", declared=52 * 1024 * 1024)
        self.assertEqual(status, 413)
        self.assertEqual(pulled, [])

    def test_chunked_oversize_through_the_real_app_is_413_not_500(self):
        status, _, _ = drive(self.app, path="/auth/login", chunks=[b"0," * 8192] * 40)
        self.assertEqual(status, 413)

    def test_it_is_the_outermost_layer(self):
        from api.app import app
        self.assertIs(app.user_middleware[0].cls, BodyLimitMiddleware)


if __name__ == "__main__":
    unittest.main()
