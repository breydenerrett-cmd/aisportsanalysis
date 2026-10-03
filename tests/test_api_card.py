"""The /card routes: the one collision that is easy to reintroduce.

`/card/record`, `/card/history` and `/card/{date}` share a prefix, and
FastAPI matches in DECLARATION order -- so if `/card/{date}` is declared
first, the other two are captured as a date and rejected by `_validate_date`
as a 400. That is exactly what happened on the first run of this endpoint,
and it fails in the quietest possible way: the client's `.catch(() => null)`
turns the 400 into "no record yet", which is a real and normal state, so the
page renders correctly and the record silently never appears.

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
    """Every card route path: the PUBLIC router's, then the paid router's --
    the order api/app.py mounts them in, so the position of "/card/record"
    against "/card/{date}" in this list is the order FastAPI will match them.

    Read off the routers rather than `app.routes`: this FastAPI version keeps
    an included router as a single opaque `_IncludedRouter` entry instead of
    flattening its routes into the app, so walking `app.routes` finds nothing
    and a test written against it would pass vacuously on an empty list.
    """
    from api.card import public_router, router
    return ([getattr(r, "path", None) for r in public_router.routes]
            + [getattr(r, "path", None) for r in router.routes])


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

    def test_card_history_is_declared_before_the_date_route(self):
        """THE RECORD page's day-by-day route (2026-09-10) has the exact
        same collision /card/record does, against the exact same
        /card/{date} -- see this module's docstring."""
        paths = _card_router_paths()
        self.assertIn("/card/history", paths,
                      "the history route is not declared at all")
        self.assertIn("/card/{date}", paths)
        self.assertLess(
            paths.index("/card/history"), paths.index("/card/{date}"),
            "/card/{date} is declared before /card/history, so 'history' "
            "is matched as a date and 400s.")

    def test_every_card_route_is_declared(self):
        # "/card/accounts" joined the public router 2026-10-03 (example
        # accounts); its own tests are tests/test_example_accounts_route.py.
        self.assertEqual(
            {"/card", "/card/record", "/card/history", "/card/accounts", "/card/{date}"},
            set(_card_router_paths()))

    def test_card_accounts_is_declared_before_the_date_route(self):
        """Same collision as record and history: declared after
        /card/{date}, "accounts" would be matched as a date and 400."""
        paths = _card_router_paths()
        self.assertLess(paths.index("/card/accounts"), paths.index("/card/{date}"))


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

        path, _, query = path.partition("?")
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "GET", "scheme": "http", "path": path, "raw_path": path.encode(),
            "query_string": query.encode(), "root_path": "", "headers": [(b"host", b"test")],
            "client": ("test", 1), "server": ("test", 80),
        }
        asyncio.new_event_loop().run_until_complete(app(scope, receive, send))
        return captured.get("status")

    def test_card_by_date_is_401_without_a_token(self):
        self.assertEqual(401, self._status("/card/2026-09-10"))

    def test_card_today_is_401_without_a_token(self):
        self.assertEqual(401, self._status("/card"))

    def test_card_record_is_public_without_a_token(self):
        """The record is the proof the landing page promises "you can open
        yourself" -- no token. A 400 here means the /card/{date} collision is
        back; a 401 means the record went back behind the paid gate."""
        self.assertEqual(200, self._status("/card/record"))

    def test_card_history_is_public_without_a_token(self):
        """Same: the day-by-day settled detail is public. A 400 means the
        /card/{date} collision is back for this route too."""
        self.assertEqual(200, self._status("/card/history"))

    def test_every_public_record_variant_is_open(self):
        for path in ("/card/record?rule=v1", "/card/record?rule=v2",
                     "/card/record?sport=nfl", "/card/record?sport=mma",
                     "/card/history?rule=v1", "/card/history?rule=v2",
                     "/card/history?sport=nfl", "/card/history?sport=mma"):
            with self.subTest(path=path):
                self.assertEqual(200, self._status(path))

    def test_an_unsettled_date_stays_paid(self):
        """Tonight's card is the product: a dated card and any `?rule=` or
        `?sport=` variant of it still 401 without a token."""
        for path in ("/card/2099-01-01", "/card/2099-01-01?rule=v2",
                     "/card?sport=nfl", "/card?rule=v2"):
            with self.subTest(path=path):
                self.assertEqual(401, self._status(path))


if __name__ == "__main__":
    unittest.main()
