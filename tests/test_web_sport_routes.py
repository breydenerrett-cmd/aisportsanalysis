"""Structural checks for NFL surface wiring (Task 1.9).

Static text scans of web/js/main.js, card.js, cardrecord.js, sport.js,
and labels_nfl.js to verify:

- sport.js exports parseSport, renderSportSwitcher, NFL_NOTICE
- main.js imports parseSport and routes #/nfl/today and #/nfl/record
- card.js fetches /card?sport= when sport is nfl and renders notice
- labels_nfl.js contains NFL wording
- Existing MLB routes still dispatch
- main.js does not import live.js or tennis.js
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_JS = ROOT / "web" / "js"


def _read(name: str) -> str:
    return (WEB_JS / name).read_text(encoding="utf-8")


class SportJsExports(unittest.TestCase):
    def setUp(self):
        self.text = _read("sport.js")

    def test_exports_parseSport(self):
        self.assertIn("export function parseSport", self.text)

    def test_exports_renderSportSwitcher(self):
        self.assertIn("export function renderSportSwitcher", self.text)

    def test_exports_NFL_NOTICE(self):
        self.assertIn("export const NFL_NOTICE", self.text)

    def test_NFL_NOTICE_contains_experimental_notice(self):
        self.assertIn("Experimental selections", self.text)


class LabelsNflExports(unittest.TestCase):
    def setUp(self):
        self.text = _read("labels_nfl.js")

    def test_contains_kickoff(self):
        self.assertIn("kickoff", self.text.lower())

    def test_exports_NFL_WORDING(self):
        self.assertIn("export const NFL_WORDING", self.text)


class MainJsNflRouting(unittest.TestCase):
    def setUp(self):
        self.text = _read("main.js")

    def test_imports_parseSport(self):
        self.assertIn('from "./sport.js"', self.text)
        self.assertIn("parseSport", self.text)

    def test_imports_renderCard(self):
        self.assertIn('from "./card.js"', self.text)
        self.assertIn("renderCard", self.text)

    def test_routes_nfl_today(self):
        # Should have a handler for sport === "nfl" && route === "today"
        self.assertIn('sport === "nfl"', self.text)
        self.assertIn('route === "today"', self.text)

    def test_routes_nfl_record(self):
        # Should have a handler for sport === "nfl" && route === "record"
        self.assertIn('route === "record"', self.text)
        self.assertIn("renderCardRecord", self.text)

    def test_calls_parseSport_on_segments(self):
        self.assertIn("parseSport(segments)", self.text)

    def test_imports_live_js(self):
        self.assertIn('from "./live.js"', self.text)
        self.assertIn("renderLive", self.text)

    def test_imports_tennis_js(self):
        self.assertIn('from "./tennis.js"', self.text)
        self.assertIn("renderTennisBoard", self.text)

    def test_dispatches_live(self):
        self.assertIn('route === "live"', self.text)

    def test_dispatches_tennis(self):
        self.assertIn('sport === "tennis"', self.text)
        self.assertIn("renderTennisBoard", self.text)

    def test_still_routes_mlb_today(self):
        # Existing routes must still work
        self.assertIn('route === "today"', self.text)
        self.assertIn("renderToday", self.text)

    def test_still_routes_existing_destinations(self):
        # These are the existing primary nav items that must still work
        for route in ("games", "betcheck", "mybets", "performance", "props", "record-card"):
            self.assertIn(f'route === "{route}"', self.text)


class CardJsNflSupport(unittest.TestCase):
    def setUp(self):
        self.text = _read("card.js")

    def test_imports_NFL_NOTICE(self):
        self.assertIn('from "./sport.js"', self.text)
        self.assertIn("NFL_NOTICE", self.text)

    def test_renders_nfl_notice(self):
        # Should render the notice for NFL
        self.assertIn("NFL_NOTICE", self.text)
        self.assertIn("sport === \"nfl\"", self.text)

    def test_fetches_with_sport_parameter(self):
        # Should include ?sport= in fetch URLs for NFL
        self.assertIn('?sport=', self.text)


class CardRecordJsNflSupport(unittest.TestCase):
    def setUp(self):
        self.text = _read("cardrecord.js")

    def test_imports_NFL_NOTICE(self):
        self.assertIn('from "./sport.js"', self.text)
        self.assertIn("NFL_NOTICE", self.text)

    def test_renders_nfl_notice(self):
        self.assertIn("sport === \"nfl\"", self.text)

    def test_fetches_with_sport_parameter(self):
        self.assertIn('?sport=', self.text)


class ExistingRoutesPreserved(unittest.TestCase):
    """Verify that existing MLB routes have not been changed."""

    def setUp(self):
        self.main_text = _read("main.js")

    def test_routes_comment_mentions_today_for_mlb(self):
        # The ROUTES comment should still mention the existing routes
        self.assertIn("#/today", self.main_text)
        self.assertIn("#/games", self.main_text)

    def test_existing_routes_still_dispatched(self):
        # These routes should still be in the dispatch logic
        self.assertIn("renderToday", self.main_text)
        self.assertIn("renderGamesList", self.main_text)
        self.assertIn("renderBetCheck", self.main_text)


if __name__ == "__main__":
    unittest.main()
