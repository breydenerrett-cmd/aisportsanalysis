"""The /card routes: the one collision that is easy to reintroduce.

`/card/record` and `/card/{date}` share a prefix, and FastAPI matches in
DECLARATION order -- so if `/card/{date}` is declared first, `/card/record`
is captured as a date and rejected by `_validate_date` as a 400. That is
exactly what happened on the first run of this endpoint, and it fails in the
quietest possible way: the client's `.catch(() => null)` turns the 400 into
"no record yet", which is a real and normal state, so the page renders
correctly and the record silently never appears.

A test that only asserted the route "returns something" would have passed.
This one asserts the resolved route object.

Auth note: the card router sits behind the same paid gate as every other
read-only game surface, so a real request without a token is a 401 -- and
that is asserted here too, because a headline surface accidentally shipped
PUBLIC would be a worse bug than the routing one.
"""

from __future__ import annotations

import unittest

try:
    from api.app import app
    _HAVE_FASTAPI = True
except Exception:  # noqa: BLE001 -- fastapi lives only in api/'s deps
    _HAVE_FASTAPI = False


def _card_router_paths():
    """The card router's own paths, in DECLARATION order.

    Read off `api.card.router` rather than `app.routes`: this FastAPI
    version keeps an included router as a single opaque `_IncludedRouter`
    entry instead of flattening its routes into the app, so walking
    `app.routes` finds nothing and a test written against it would pass
    vacuously on an empty list.
    """
    from api.card import router
    return [getattr(r, "path", None) for r in router.routes]


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class RouteOrder(unittest.TestCase):
    def test_card_record_is_declared_before_the_date_route(self):
        paths = _card_router_paths()
        self.assertIn("/card/record", paths,
                      "the record route is not declared at all")
        self.assertIn("/card/{date}", paths)
        self.assertLess(
            paths.index("/card/record"), paths.index("/card/{date}"),
            "/card/{date} is declared before /card/record, so 'record' is "
            "matched as a date and 400s. Declaration order IS the fix; see "
            "this module's docstring.")

    def test_all_three_card_routes_are_declared(self):
        self.assertEqual({"/card", "/card/record", "/card/{date}"},
                         set(_card_router_paths()))


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class CardRequiresAuth(unittest.TestCase):
    """Router-level auth is invisible to a direct function call, so only a
    real request through the app proves the gate is mounted."""

    def _status(self, path):
        import asyncio
        import json  # noqa: F401 -- kept for symmetry with sibling tests

        captured = {}

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            if message["type"] == "http.response.start":
                captured["status"] = message["status"]

        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "GET", "scheme": "http", "path": path, "raw_path": path.encode(),
            "query_string": b"", "root_path": "", "headers": [(b"host", b"test")],
            "client": ("test", 1), "server": ("test", 80),
        }
        asyncio.new_event_loop().run_until_complete(app(scope, receive, send))
        return captured.get("status")

    def test_card_by_date_is_401_without_a_token(self):
        self.assertEqual(401, self._status("/card/2026-09-10"))

    def test_card_today_is_401_without_a_token(self):
        self.assertEqual(401, self._status("/card"))

    def test_card_record_is_401_without_a_token(self):
        """The record is the sales pitch, and it is still behind the gate.
        A 400 here instead of a 401 means the route collision is back."""
        self.assertEqual(401, self._status("/card/record"))


if __name__ == "__main__":
    unittest.main()
