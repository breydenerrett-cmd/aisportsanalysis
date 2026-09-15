"""Structural checks for Live and Tennis routing wiring.

Verifies:
- main.js dispatches "live" to renderLive
- main.js dispatches "tennis" to renderTennisBoard
- NAV_ITEMS does not contain "#/live"
- api/app.py includes the tennis router with the paid dependency
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_JS = ROOT / "web" / "js"
API = ROOT / "api"


def _read_web_js(name: str) -> str:
    return (WEB_JS / name).read_text(encoding="utf-8")


def _read_api_file(name: str) -> str:
    return (API / name).read_text(encoding="utf-8")


class LiveTennisWiring(unittest.TestCase):
    """Verify that Live and Tennis routes are wired into the router."""

    def setUp(self):
        self.main_text = _read_web_js("main.js")

    def test_dispatches_live_route(self):
        """main.js should dispatch 'live' route to renderLive."""
        self.assertIn('route === "live"', self.main_text)
        self.assertIn("renderLive", self.main_text)

    def test_dispatches_tennis_route(self):
        """main.js should dispatch 'tennis' sport to renderTennisBoard."""
        self.assertIn('sport === "tennis"', self.main_text)
        self.assertIn("renderTennisBoard", self.main_text)

    def test_live_not_in_nav_items(self):
        """NAV_ITEMS should not contain #/live."""
        self.assertNotIn("#/live", self.main_text.split("const NAV_ITEMS")[1].split("];")[0])

    def test_imports_renderLive(self):
        """main.js should import renderLive from live.js."""
        self.assertIn('from "./live.js"', self.main_text)
        self.assertIn("renderLive", self.main_text)

    def test_imports_renderTennisBoard(self):
        """main.js should import renderTennisBoard from tennis.js."""
        self.assertIn('from "./tennis.js"', self.main_text)
        self.assertIn("renderTennisBoard", self.main_text)


class TennisRouterRegistration(unittest.TestCase):
    """Verify that the tennis router is registered in api/app.py."""

    def setUp(self):
        self.app_text = _read_api_file("app.py")

    def test_imports_tennis_router(self):
        """api/app.py should import the tennis router."""
        self.assertIn("from api.tennis import router as tennis_router", self.app_text)

    def test_includes_tennis_router_with_paid_dependency(self):
        """api/app.py should register tennis router with _authed_paid dependency."""
        self.assertIn("app.include_router(tennis_router, dependencies=_authed_paid)", self.app_text)


if __name__ == "__main__":
    unittest.main()
