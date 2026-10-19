"""A request-body size cap, as pure ASGI (no FastAPI import, so it is testable anywhere).

WHY (red team 2026-10-19). Nothing capped a request body: one 52 MB POST to a
login route raised the process's RSS by about 460 MB, and production is a 1 GB
machine. Every legitimate body in this app is a login, a form, a small JSON spec
or a webhook, all well under a few KB, so 64 KB is generous.

TWO CHECKS, because a client chooses how to send:

  * `Content-Length` over the limit is refused with 413 BEFORE the app (or even
    the request line's route) runs, so nothing is read.
  * A body with no (or a lying) Content-Length, i.e. chunked, is counted as the
    app reads it; the first chunk that takes the total past the limit aborts the
    read, and the client gets the same 413.

WHY THE `send` WRAPPER. The app's own middleware (api/app.py `log_requests`)
catches every exception and answers 500, so an exception raised from the
counting `receive` cannot be relied on to reach this layer. Instead the overflow
is recorded and, when the app begins its response, that response is replaced by
the 413 (the app's own body messages are dropped). If the exception does reach
here and nothing was sent, the 413 is sent directly.

Per-path overrides exist for a route that genuinely needs more; the table is
small on purpose and each entry says why.
"""

from __future__ import annotations

import json
from typing import Dict, Optional

DEFAULT_MAX_BODY_BYTES = 64 * 1024

# Stripe signs the raw payload, so it cannot be trimmed; events are a few KB but
# an invoice with many lines can run larger, and a refused webhook is a missed
# payment event (Stripe retries, then gives up). Unauthenticated until the
# signature is checked, but 256 KB per request is not the memory problem.
PATH_LIMITS: Dict[str, int] = {
    "/billing/webhook": 256 * 1024,
}

_BODY = json.dumps({
    "error": "payload_too_large",
    "message": "the request body is too large",
}).encode("utf-8")


class BodyTooLarge(Exception):
    """Raised from the counting receive once the body passes the limit."""


def limit_for(path: str, default: int = DEFAULT_MAX_BODY_BYTES) -> int:
    return PATH_LIMITS.get(path, default)


def _content_length(scope) -> Optional[int]:
    for name, value in scope.get("headers") or ():
        if name == b"content-length":
            try:
                parsed = int(value.decode("latin-1").strip())
            except ValueError:
                return None  # malformed: the counting wrapper is the backstop
            return parsed if parsed >= 0 else None
    return None


class BodyLimitMiddleware:
    def __init__(self, app, max_bytes: int = DEFAULT_MAX_BODY_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        limit = limit_for(scope.get("path") or "", self.max_bytes)
        declared = _content_length(scope)
        if declared is not None and declared > limit:
            await self._refuse(send)
            return

        seen = 0
        overflowed = False
        started = False

        async def counting_receive():
            nonlocal seen, overflowed
            message = await receive()
            if message.get("type") == "http.request":
                seen += len(message.get("body") or b"")
                if seen > limit:
                    overflowed = True
                    raise BodyTooLarge()
            return message

        async def guarded_send(message):
            nonlocal started
            if overflowed:
                if message["type"] == "http.response.start" and not started:
                    started = True
                    await self._refuse(send)
                return  # the app's own (500) response is dropped
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except BodyTooLarge:
            if not started:
                await self._refuse(send)
            return
        if overflowed and not started:
            await self._refuse(send)

    @staticmethod
    async def _refuse(send) -> None:
        await send({"type": "http.response.start", "status": 413, "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(_BODY)).encode("ascii")),
            (b"connection", b"close"),
        ]})
        await send({"type": "http.response.body", "body": _BODY, "more_body": False})
