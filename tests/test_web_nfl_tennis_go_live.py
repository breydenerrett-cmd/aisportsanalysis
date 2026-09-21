"""NFL and Tennis stop showing "COMING SOON" and become real sections
(owner directive, 2026-09-19).

Before this change, `#/nfl` and `#/tennis` -- every route under either --
rendered `comingsoon.js`'s shared static page (see the now-superseded
paragraph in docs/DESIGN_SYSTEM.md section 6, kept as history). NFL and
Tennis are NOT the same kind of change, and this file keeps them in
separate test classes on purpose:

  NFL genuinely goes live. It publishes picks (one so far, published and
  graded 2026-09-17 as a WIN) and gets its own card and graded record,
  same machinery MLB already uses (`card.js`'s `renderCard`,
  `cardrecord.js`'s `renderCardRecord`, both already supported an
  `{sport: "nfl"}` option before this change -- only the routing was
  missing). A one-pick record is not a track record, so this file also
  checks that neither page renders a win-rate or ROI percentage while the
  sample is this small -- it must show the raw count instead.

  Tennis is routed but stays picks-free. `#/tennis` now renders the real
  research board (`tennis.js`'s `renderTennisBoard`) instead of the
  static page, but the board itself is unchanged: no pick, no slip, no
  record surface exists for tennis anywhere, and its own "Research only"
  notice still renders.

Static text scans only, matching every other file in this directory --
this repo's tests/ suite has no JS execution harness.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_JS = ROOT / "web" / "js"


def _read(name: str) -> str:
    return (WEB_JS / name).read_text(encoding="utf-8")


class NflRoutesToTheRealCardAndRecord(unittest.TestCase):
    """main.js must dispatch sport "nfl" to card.js/cardrecord.js, not the
    shared coming-soon page."""

    def setUp(self):
        self.main = _read("main.js")

    def test_main_js_imports_renderCard_from_card_js(self):
        self.assertIn('from "./card.js"', self.main)
        self.assertIn("renderCard", self.main)

    def test_nfl_gameday_route_calls_renderCard_with_nfl_sport(self):
        self.assertIn('renderCard(main, { sport: "nfl" })', self.main)

    def test_nfl_record_route_calls_renderCardRecord_with_nfl_sport(self):
        self.assertIn('renderCardRecord(main, { sport: "nfl" })', self.main)

    def test_nfl_no_longer_dispatches_to_renderComingSoon(self):
        # The old dispatch was a single branch handling nfl, tennis, nba
        # and nhl together (`sport === "nfl" || sport === "tennis" || ...`)
        # -- that exact combined condition must be gone, since nfl and
        # tennis now have their own branches ahead of the nba/nhl one.
        self.assertNotIn(
            'sport === "nfl" || sport === "tennis" || sport === "nba" || sport === "nhl"',
            self.main,
        )


class TennisRoutesToTheRealBoardButStaysPicksFree(unittest.TestCase):
    """main.js must dispatch sport "tennis" to tennis.js's real board, not
    the shared coming-soon page -- and the board itself must still carry
    no pick, slip or record language."""

    def setUp(self):
        self.main = _read("main.js")
        self.tennis = _read("tennis.js")

    def test_main_js_imports_renderTennisBoard(self):
        self.assertIn('from "./tennis.js"', self.main)
        self.assertIn("renderTennisBoard", self.main)

    def test_tennis_route_calls_renderTennisBoard(self):
        self.assertIn('await renderTennisBoard(main);', self.main)

    def test_tennis_board_still_carries_the_research_only_notice(self):
        # tests/test_web_tennis_board.py already pins this string inside
        # tennis.js itself; re-checked here as the thing that must survive
        # tennis.js going from unrouted to routed.
        self.assertIn(
            "Research only. No tennis picks until results grading is connected.",
            self.tennis,
        )


class SportsRegistryReflectsTheLiveState(unittest.TestCase):
    """sport.js's SPORTS registry: nfl and tennis are 'live', each with
    its own home and (for NFL) a submenu mirroring MLB's shape."""

    def setUp(self):
        self.sport = _read("sport.js")

    def test_nfl_entry_is_live(self):
        self.assertIn('key: "nfl"', self.sport)
        idx = self.sport.index('key: "nfl"')
        entry = self.sport[idx:idx + 300]
        self.assertIn('status: "live"', entry)
        self.assertIn('home: "#/nfl"', entry)

    def test_nfl_submenu_has_gameday_and_results_hash_before_label(self):
        self.assertIn('{ hash: "#/nfl", label: "GAMEDAY"', self.sport)
        self.assertIn('{ hash: "#/nfl/record", label: "RESULTS"', self.sport)

    def test_tennis_entry_is_live(self):
        self.assertIn('key: "tennis"', self.sport)
        idx = self.sport.index('key: "tennis"')
        entry = self.sport[idx:idx + 300]
        self.assertIn('status: "live"', entry)
        self.assertIn('home: "#/tennis"', entry)

    def test_nba_and_nhl_remain_coming_soon(self):
        # This change is scoped to NFL and Tennis only -- NBA/NHL must not
        # be touched by it.
        self.assertIn(
            'key: "nba", label: "NBA", status: "coming_soon", home: "#/nba"',
            self.sport,
        )
        self.assertIn(
            'key: "nhl", label: "NHL", status: "coming_soon", home: "#/nhl"',
            self.sport,
        )


class NflRecordNeverShowsAPercentageOffASample(unittest.TestCase):
    """The owner's rule, verbatim in substance: never render an NFL
    win-rate or ROI percentage off n=1 (or any small sample) -- show the
    raw count instead, and make the sample size unmissable. Both pages
    that print the pooled NFL record (card.js's recordLine, cardrecord.js's
    headline) must carry this guard."""

    def setUp(self):
        self.card = _read("card.js")
        self.cardrecord = _read("cardrecord.js")

    def test_card_js_defines_a_sample_floor(self):
        self.assertIn("NFL_SAMPLE_FLOOR", self.card)

    def test_card_js_record_line_is_sport_aware(self):
        self.assertIn("function recordLine(rec, sport", self.card)

    def test_card_js_suppresses_the_percentage_below_the_floor(self):
        self.assertIn("tooSmallForARate", self.card)
        self.assertIn("data-hook\": \"card-record-small-sample\"", self.card)

    def test_cardrecord_js_defines_a_sample_floor(self):
        self.assertIn("NFL_SAMPLE_FLOOR", self.cardrecord)

    def test_cardrecord_js_headline_is_sport_aware(self):
        self.assertIn("function headline(record, sport", self.cardrecord)

    def test_cardrecord_js_suppresses_the_percentage_below_the_floor(self):
        self.assertIn("tooSmallForARate", self.cardrecord)
        self.assertIn("data-hook\": \"record-nfl-sample-note\"", self.cardrecord)

    def test_cardrecord_js_passes_sport_into_headline(self):
        self.assertIn("headline(record, sport)", self.cardrecord)


if __name__ == "__main__":
    unittest.main()
