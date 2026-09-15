"""Structural checks for Live and Tennis routing wiring.

Verifies:
- main.js dispatches "live" to renderLive, unchanged by the 2026-09-15
  redesign (D5: Live leaves the public chrome but keeps its typed-URL
  route exactly as it was)
- main.js dispatches sport "tennis" to the shared renderComingSoon page,
  not the live tennis board (D4: tennis is not shown until results
  grading is connected -- tennis.js itself stays on disk, unmodified and
  unrouted, per docs/DESIGN_SYSTEM.md's "NFL and Tennis" section)
- NAV_ITEMS does not contain "#/live"
- sport.js's rendered chrome carries no "#/live" link anywhere (D5)
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


def _code_only(text: str) -> str:
    """Strip `/* */` block comments and `//` line comments -- sport.js's
    own docstring names "#/live" in prose to explain that it was deleted,
    which a raw substring scan would misread as the link still existing."""
    out, in_block = [], False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("/*"):
            in_block = True
        if in_block:
            if "*/" in s:
                in_block = False
            continue
        if s.startswith("//"):
            continue
        out.append(line)
    return "\n".join(out)


class LiveTennisWiring(unittest.TestCase):
    """Verify that Live and Tennis routes are wired into the router."""

    def setUp(self):
        self.main_text = _read_web_js("main.js")

    def test_dispatches_live_route(self):
        """main.js should dispatch 'live' route to renderLive."""
        self.assertIn('route === "live"', self.main_text)
        self.assertIn("renderLive", self.main_text)

    def test_dispatches_tennis_route_to_coming_soon(self):
        """Redesign, 2026-09-15 (D4): main.js should dispatch sport ===
        'tennis' -- every route under it, #/tennis and #/tennis/board alike
        -- to the shared renderComingSoon page, not the live tennis board."""
        self.assertIn('sport === "tennis"', self.main_text)
        self.assertIn("renderComingSoon", self.main_text)

    def test_live_not_in_nav_items(self):
        """NAV_ITEMS should not contain #/live."""
        self.assertNotIn("#/live", self.main_text.split("const NAV_ITEMS")[1].split("];")[0])

    def test_imports_renderLive(self):
        """main.js should import renderLive from live.js, unchanged by the
        redesign -- #/live keeps its existing dispatch (D5)."""
        self.assertIn('from "./live.js"', self.main_text)
        self.assertIn("renderLive", self.main_text)

    def test_does_not_import_the_live_tennis_board_module(self):
        """Redesign, 2026-09-15 (D4): tennis routes no longer reach
        web/js/tennis.js at all -- it stays on disk, unmodified and
        unrouted (docs/DESIGN_SYSTEM.md's "NFL and Tennis" section), so
        tests/test_web_tennis_board.py, which reads tennis.js directly,
        keeps passing untouched."""
        self.assertNotIn('from "./tennis.js"', self.main_text)

    def test_imports_render_coming_soon(self):
        """main.js should import renderComingSoon from comingsoon.js."""
        self.assertIn('from "./comingsoon.js"', self.main_text)
        self.assertIn("renderComingSoon", self.main_text)

    def test_sport_js_carries_no_live_link(self):
        """D5: Live leaves the public chrome -- sport.js's rendered
        sport-level chrome (live tabs, coming-soon links) must never link
        to #/live, the one place besides main.js's own dispatch that could
        reintroduce it."""
        sport_text = _code_only(_read_web_js("sport.js"))
        self.assertNotIn("#/live", sport_text)


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
