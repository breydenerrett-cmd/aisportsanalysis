"""Structural checks for Task F2's three new front-end surfaces:

  - web/js/recordstrip.js (GET /record, mounted at the top of both
    #/today and #/performance)
  - web/js/matchups.js (THE MATCHUP GRID, #/today, wired in below TOP
    OPPORTUNITIES and above the Featured Bet carousel head)
  - web/js/dayrecap.js (the daily-recap gallery on #/performance, and the
    #/day/{date} full audit-trail detail route)

A plain-text scan, like tests/test_web_structure.py and
tests/test_web_v2_betcheck.py -- never starts a server, never imports a
JS engine.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.test_customer_language import HARD_BANNED, NEGATION_ONLY, NEGATORS

ROOT = Path(__file__).resolve().parent.parent
WEB_JS = ROOT / "web" / "js"

RECORDSTRIP_PATH = WEB_JS / "recordstrip.js"
MATCHUPS_PATH = WEB_JS / "matchups.js"
DAYRECAP_PATH = WEB_JS / "dayrecap.js"
TODAY_PATH = WEB_JS / "today.js"
PERFORMANCE_PATH = WEB_JS / "performance.js"
MAIN_PATH = WEB_JS / "main.js"

NEW_JS_FILES = (RECORDSTRIP_PATH, MATCHUPS_PATH, DAYRECAP_PATH)

BANNED_PROBABILITY_TOKENS = (
    "win_probability", "winProbability", "modelProbability", "true_probability",
)

FROZEN_TITLE = "PAPER POSITIONS FROZEN BEFORE FIRST PITCH"
CLASS_MEANINGS = (
    "fixed-direction null baseline, not a pick",
    "republishes the board's own consensus, a calibration reference, not a pick",
    "an unproven directional thesis under forward test",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class NewFilesExist(unittest.TestCase):
    def test_new_files_present_and_nonempty(self):
        for path in NEW_JS_FILES:
            self.assertTrue(path.is_file(), f"{path.name} missing")
            self.assertTrue(_read(path).strip(), f"{path.name} is empty")

    def test_new_files_export_their_documented_functions(self):
        self.assertRegex(_read(RECORDSTRIP_PATH), r"export async function renderRecordStrip\s*\(")
        self.assertRegex(_read(MATCHUPS_PATH), r"export async function renderMatchups\s*\(")
        self.assertRegex(_read(DAYRECAP_PATH), r"export async function renderDayRecap\s*\(")
        self.assertRegex(_read(DAYRECAP_PATH), r"export async function renderDayDetail\s*\(")


class RecordStripWiredIntoBothScreens(unittest.TestCase):
    def test_today_js_imports_and_calls_record_strip(self):
        text = _read(TODAY_PATH)
        self.assertIn('from "./recordstrip.js"', text)
        self.assertIn("renderRecordStrip", text)

    def test_performance_js_imports_and_calls_record_strip(self):
        text = _read(PERFORMANCE_PATH)
        self.assertIn('from "./recordstrip.js"', text)
        self.assertIn("renderRecordStrip", text)

    def test_record_strip_mounted_above_the_today_hero(self):
        # renderHero(...) is both a function declaration AND a call site
        # in today.js -- scope the search to renderToday's own body (like
        # tests/test_web_v2_betcheck.py's own renderResult-body slicing)
        # so this only ever compares the two actual DOM-append call sites.
        text = _read(TODAY_PATH)
        body = text.split("export async function renderToday(")[1]
        # renderCardRecordStrip since 2026-09-10: the strip used to show the
        # detector systems' paper standings above the card's own picks,
        # which answered "did YOUR picks win?" with another system's
        # numbers. The ordering this test protects is unchanged; only the
        # function that fills the slot is.
        strip_index = body.find("renderCardRecordStrip(recordStripHost)")
        # Matched on the call's PREFIX, not its full argument list. Pinning
        # every argument made this break the day renderHero gained one
        # (`hasPicks`, so the hero could stop printing "NOTHING CLEARS THE
        # BAR" beneath a list of picks) -- a failure that said nothing about
        # the ordering this test exists to protect.
        hero_index = body.find("renderHero(host, featured, aggregates, rows,")
        self.assertGreaterEqual(strip_index, 0)
        self.assertGreaterEqual(hero_index, 0)
        self.assertLess(strip_index, hero_index,
                         "record strip must be mounted above the Today hero")


class MatchupsWiredIntoToday(unittest.TestCase):
    def test_today_js_imports_and_calls_render_matchups(self):
        text = _read(TODAY_PATH)
        self.assertIn('from "./matchups.js"', text)
        # The third argument hands over the /today payload this screen has
        # already fetched, so the grid does not pay for a second copy of it
        # before it can start -- see matchups.js's own note.
        self.assertIn("renderMatchups(host, date, today)", text)

    def test_matchups_sits_above_the_slate_rail(self):
        # Scoped to renderToday's own body so this compares actual DOM-
        # append call sites, not function declarations.
        #
        # TOP OPPORTUNITIES used to lead this ordering and no longer mounts
        # at all (see the test below). Then the Featured Bet section was the
        # thing below the grid, and on 2026-09-12 it went the same way --
        # both were the price-comparison register on the main screen. What
        # survives is the part that was ever about ordering: the matchup
        # grid above whatever comes next, which is now the slate rail.
        text = _read(TODAY_PATH)
        body = text.split("export async function renderToday(")[1]
        mx_index = body.find("renderMatchups(host, date, today)")
        rail_index = body.find("renderSlateRail(rows, oddsIndex")
        self.assertGreaterEqual(mx_index, 0)
        self.assertGreaterEqual(rail_index, 0)
        self.assertLess(mx_index, rail_index)

    def test_the_featured_price_gap_section_is_not_mounted_on_today(self):
        """The price-gap feature must not come back by accident.

        It headlined "the largest price gap against consensus" as a feature
        and fired a POST /betcheck on every page load to fill a tile of
        PRICE STANDING / BEATS CONSENSUS / IMPROVEMENT rows.
        """
        text = _read(TODAY_PATH)
        body = text.split("export async function renderToday(")[1]
        self.assertEqual(body.find("renderFeaturedSection("), -1)
        self.assertEqual(body.find("loadFeaturedStanding("), -1)
        self.assertNotIn('from "./featuredbet.js"', text)

    def test_top_opportunities_is_not_mounted_on_today(self):
        """TOP OPPORTUNITIES must not come back to #/today by accident.

        Its hero card was labelled TOP PLAY -- a client-invented string with
        no backend equivalent; the API calls those rows `qualifying` and
        ranks them by execution quality, not by how good a bet they are.
        That component is what made a price gap read as a great pick, and
        removing it was a deliberate product decision
        (docs/PRODUCT_DOCTRINE.md).

        The import is kept alive deliberately (`void renderOpportunities`)
        so the module is not orphaned while the decision is revisited, which
        is exactly why a grep for the NAME would not catch a regression.
        This asserts on the CALL.
        """
        body = _read(TODAY_PATH).split("export async function renderToday(")[1]
        self.assertEqual(
            body.find("renderOpportunities(host"), -1,
            "TOP OPPORTUNITIES is mounted on #/today again")

    def test_existing_today_data_hooks_kept_intact(self):
        # A short sample of today.js's pre-existing data-hooks that must
        # survive this lane's edits untouched (top-opportunities itself
        # lives in opportunities.js, not today.js -- today.js only places
        # that section, so it is not checked here).
        text = _read(TODAY_PATH)
        # "gameday-featured-bet" was in this list until 2026-09-12. That
        # section -- FEATURED · LARGEST PRICE GAP AGAINST CONSENSUS, over
        # featuredbet.js's price-comparison tile -- was removed as the
        # register the owner retired on 2026-09-10, and a hook for a section
        # that must not exist has no business in a list of hooks that must.
        for hook in ("gameday-hero", "tonights-slate",
                     "what-changed", "check-band", "board-freshness"):
            self.assertIn(f'"{hook}"', text, f"missing pre-existing data-hook {hook!r}")


class DayRouteRegistered(unittest.TestCase):
    def setUp(self):
        self.text = _read(MAIN_PATH)

    def test_imports_day_detail(self):
        self.assertIn('from "./dayrecap.js"', self.text)
        self.assertIn("renderDayDetail", self.text)

    def test_hash_route_registered(self):
        self.assertIn('route === "day"', self.text)

    def test_section_label_registered(self):
        self.assertIn('day: "DAILY RECORD"', self.text)


class DayRecapGalleryWiredIntoPerformance(unittest.TestCase):
    def test_performance_js_imports_and_calls_day_recap(self):
        text = _read(PERFORMANCE_PATH)
        self.assertIn('from "./dayrecap.js"', text)
        self.assertIn("renderDayRecap(screen)", text)

    def test_day_recap_mounted_above_existing_content(self):
        # renderHead is both declared and called in performance.js -- scope
        # to renderPerformance's own body (like renderToday above) so this
        # compares actual DOM-append call sites only.
        text = _read(PERFORMANCE_PATH)
        body = text.split("export async function renderPerformance(")[1]
        recap_index = body.find("renderDayRecap(screen)")
        head_index = body.find("renderHead(payload)")
        self.assertGreaterEqual(recap_index, 0)
        self.assertGreaterEqual(head_index, 0)
        self.assertLess(recap_index, head_index,
                         "the daily recap gallery must mount above the existing performance content")


class HonestyRuleWiredExplicitly(unittest.TestCase):
    """The CONTROL/MARKET_REFERENCE/FORWARD_TEST honesty rule this whole
    screen exists to enforce -- see matchups.js's own module docstring."""

    def setUp(self):
        self.text = _read(MATCHUPS_PATH)

    def test_frozen_title_present_verbatim(self):
        self.assertIn(FROZEN_TITLE, self.text)

    def test_three_class_meanings_present_verbatim(self):
        for meaning in CLASS_MEANINGS:
            self.assertIn(meaning, self.text)

    def test_no_forward_test_note_present(self):
        self.assertIn("No system with a directional thesis played this game.", self.text)


class ValuePointsNeverFabricated(unittest.TestCase):
    def setUp(self):
        self.text = _read(MATCHUPS_PATH)

    def test_value_points_reason_identifier_read(self):
        self.assertIn("value_points_reason", self.text)

    def test_value_points_always_type_checked_before_use(self):
        # Every place a value_points figure is formatted, it must be
        # gated behind a typeof number check -- never a bare `|| 0` (or
        # equivalent) standing in for a null/missing comparison.
        self.assertNotRegex(self.text, r"value_points\s*\|\|\s*0\b")
        self.assertNotRegex(self.text, r"value_points\s*\?\?\s*0\b")

    def test_value_points_reads_reasons_when_null(self):
        # The LIVE PRICE READ block's null-value_points branch must fall
        # back to the opportunities row's own `reasons` sentences, never
        # a client-composed excuse.
        self.assertIn("row.reasons", self.text)


class NeverFabricateGuardsAcrossNewFiles(unittest.TestCase):
    def test_no_verdict_or_default_fallback(self):
        for path in NEW_JS_FILES:
            text = _read(path)
            self.assertNotRegex(
                text, r"verdict\s*\|\|\s*[\"']\w+[\"']",
                f"{path.name}: a verdict must never be defaulted")

    def test_no_win_probability_or_model_probability_tokens(self):
        for path in NEW_JS_FILES:
            text = _read(path)
            for token in BANNED_PROBABILITY_TOKENS:
                self.assertNotIn(token, text, f"{path.name}: banned token {token!r}")


class DayRecapHistoricalBacktest(unittest.TestCase):
    def test_historical_backtest_literal_present(self):
        self.assertIn("HISTORICAL BACKTEST", _read(DAYRECAP_PATH))

    def test_frozen_position_row_reused_not_forked(self):
        # dayrecap.js must import the shared row renderer from
        # matchups.js rather than redefining it -- one place a
        # class/settlement chip can be wrong, not two.
        text = _read(DAYRECAP_PATH)
        self.assertIn('from "./matchups.js"', text)
        self.assertIn("frozenPositionRow", text)
        self.assertNotRegex(text, r"function frozenPositionRow\s*\(")


class NoBannedVocabulary(unittest.TestCase):
    """Reuses tests/test_customer_language's own banned-phrase lists,
    applied to the three new files this change adds -- independent of
    tests/test_web_structure.py's web-wide (HARD_BANNED-only) sweep."""

    def test_no_hard_banned_or_unnegated_phrases(self):
        violations = []
        for path in NEW_JS_FILES:
            text = _read(path)
            for pattern, label in HARD_BANNED:
                if re.search(pattern, text, re.IGNORECASE):
                    violations.append(f"{path.name}: hard-banned {label!r}")
            for pattern, label in NEGATION_ONLY:
                for m in re.finditer(pattern, text, re.IGNORECASE):
                    window = text[max(0, m.start() - 90):m.start()]
                    if not NEGATORS.search(window):
                        violations.append(f"{path.name}: {label!r} affirmed (no negation nearby)")
        self.assertEqual(violations, [], "\n".join(violations))

    def test_no_bare_ev_or_clv(self):
        for path in NEW_JS_FILES:
            text = _read(path)
            self.assertNotRegex(text, r"\bEV\b", f"{path.name}: bare EV")
            self.assertNotIn("CLV", text, f"{path.name}: CLV")


class CssSectionBalanced(unittest.TestCase):
    def test_screens_css_braces_balanced(self):
        text = (ROOT / "web" / "css" / "screens.css").read_text(encoding="utf-8")
        self.assertEqual(text.count("{"), text.count("}"))

    def test_new_css_classes_present(self):
        text = (ROOT / "web" / "css" / "screens.css").read_text(encoding="utf-8")
        for cls in (".rec-strip", ".mx-grid", ".mx-card", ".day-gallery",
                    ".day-settle--win", ".day-settle--loss", ".day-settle--push"):
            self.assertIn(cls, text, f"missing CSS class {cls!r}")

    def test_win_token_defined_in_tokens_css(self):
        text = (ROOT / "web" / "css" / "tokens.css").read_text(encoding="utf-8")
        self.assertIn("--v-win:", text)


if __name__ == "__main__":
    unittest.main()
