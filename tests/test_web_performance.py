"""Structural checks for the hosted-demo sprint's new front-end surfaces:

  - web/js/performance.js (#/performance, GET /performance)
  - web/js/opportunities.js (TOP OPPORTUNITIES, wired into today.js)
  - web/js/valuemeter.js (the shared MARKET-IMPLIED vs YOUR-PRICE bars)
  - main.js's #/performance route registration and RESULTS nav item
  - betcheck.js's new price-verdict block and games.js's MODEL vs MARKET
    panel, at least at the "does not violate the honesty boundary" level

A plain-text scan, like tests/test_web_structure.py and
tests/test_web_v2_betcheck.py -- never starts a server, never imports a JS
engine.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.test_customer_language import HARD_BANNED, NEGATION_ONLY, NEGATORS

ROOT = Path(__file__).resolve().parent.parent
WEB_JS = ROOT / "web" / "js"

PERFORMANCE_PATH = WEB_JS / "performance.js"
OPPORTUNITIES_PATH = WEB_JS / "opportunities.js"
VALUEMETER_PATH = WEB_JS / "valuemeter.js"
MAIN_PATH = WEB_JS / "main.js"
BETCHECK_PATH = WEB_JS / "betcheck.js"
GAMES_PATH = WEB_JS / "games.js"
TODAY_PATH = WEB_JS / "today.js"
DOM_PATH = WEB_JS / "dom.js"

NEW_JS_FILES = (PERFORMANCE_PATH, OPPORTUNITIES_PATH, VALUEMETER_PATH)

BANNED_PROBABILITY_TOKENS = (
    "win_probability", "winProbability", "modelProbability", "true_probability",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class NewFilesExist(unittest.TestCase):
    def test_new_files_present_and_nonempty(self):
        for path in NEW_JS_FILES:
            self.assertTrue(path.is_file(), f"{path.name} missing")
            self.assertTrue(_read(path).strip(), f"{path.name} is empty")


class MainJsRegistersPerformanceRoute(unittest.TestCase):
    def setUp(self):
        self.text = _read(MAIN_PATH)

    def test_imports_performance_js(self):
        self.assertIn('from "./performance.js"', self.text)
        self.assertIn("renderPerformance", self.text)

    def test_hash_route_registered(self):
        """The router dispatches #/performance.

        This used to also assert the literal `"#/performance"` appeared in
        main.js, which was really asserting a NAV ENTRY while claiming to
        test route registration. When RESULTS was repointed to
        #/record-card the assertion failed against a router that was working
        perfectly -- and, worse, it did not fail for the thing that had
        actually broken. See `test_route_has_an_entry_point_somewhere`.
        """
        self.assertIn('route === "performance"', self.text)

    def test_route_has_an_entry_point_somewhere(self):
        """Something a user can click must lead here.

        Taking RESULTS out of the nav orphaned #/performance for a day: the
        route dispatched, performance.js rendered, every test was green, and
        the only hrefs left were dayrecap.js's "back to performance" --
        reachable only FROM #/performance -- and a mention inside an HTML
        comment on the landing page.

        So this test deliberately ignores main.js and dayrecap.js and looks
        for a link from a surface a visitor reaches without already being
        there. A green suite proved the module worked; nothing proved
        anything ran it.
        """
        entry_points = []
        for path in sorted(WEB_JS.glob("*.js")):
            if path.name in ("main.js", "dayrecap.js", "performance.js"):
                continue
            for line in _read(path).splitlines():
                stripped = line.strip()
                if stripped.startswith("*") or stripped.startswith("//"):
                    continue
                if 'href: "#/performance"' in line or "'#/performance'" in line:
                    entry_points.append(f"{path.name}: {stripped[:70]}")
        self.assertTrue(
            entry_points,
            "#/performance has no entry point outside itself -- the route "
            "dispatches but nothing in the app links to it")

    def test_section_label_registered(self):
        self.assertIn("performance: \"PERFORMANCE\"", self.text)

    def test_nav_item_present(self):
        self.assertIn('label: "RESULTS"', self.text)


class OpportunitiesNeverInventsAnEmptyMessage(unittest.TestCase):
    def test_empty_literal_matches_the_api_verbatim(self):
        """The client's fallback string must be the API's own, character for
        character. Compared against the Python constant rather than a literal
        typed here, so the two can never drift -- they did drift once already
        (the 2026-09-10 rename away from "BEST BETS", which is pick language
        for a price board)."""
        from src.analysis import opportunities as opp
        text = _read(OPPORTUNITIES_PATH)
        self.assertIn(opp.EMPTY_REASON, text)

    def test_qualifying_rows_never_a_fabricated_default(self):
        text = _read(OPPORTUNITIES_PATH)
        # qualifying is always read from the payload, never defaulted to a
        # non-empty literal array of invented rows.
        self.assertIn("payload.qualifying || []", text)


class ValueMeterLabelsHonestlyMarketImplied(unittest.TestCase):
    def test_market_implied_label_present(self):
        text = _read(VALUEMETER_PATH)
        self.assertIn("MARKET-IMPLIED", text)

    def test_no_verdict_or_probability_fabrication(self):
        text = _read(VALUEMETER_PATH)
        self.assertNotRegex(text, r"verdict\s*\|\|\s*[\"']\w+[\"']")


class NeverFabricateGuardsAcrossNewFiles(unittest.TestCase):
    """This sprint's own honesty invariant, restated as a tripwire, scoped
    to the three genuinely NEW files this change adds (performance.js,
    opportunities.js, valuemeter.js) -- the pre-existing files
    (betcheck.js, games.js, today.js, dom.js) already carry their own
    tailored guards in test_web_v2_betcheck.py / test_web_v2_game.py /
    test_web_v2_gameday.py, and their long module docstrings legitimately
    NAME banned words in prose (negated, explaining why something is not
    done) -- a whole-file regex sweep over those would false-positive on
    exactly the sentences that enforce the rule."""

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


class PriceVerdictBlockWiredHonestly(unittest.TestCase):
    """betcheck.js's new renderPriceVerdict block: a new hook, distinct
    from the five mandated data-hook markers, never reusing or
    interfering with block 01's verdict-free contract."""

    def setUp(self):
        self.text = _read(BETCHECK_PATH)

    def test_price_verdict_hook_present(self):
        self.assertIn('"bet-check-price-verdict"', self.text)

    def test_price_verdict_function_defined(self):
        self.assertRegex(self.text, r"\bfunction renderPriceVerdict\s*\(")

    def test_called_in_render_result(self):
        assembly = self.text.split("function renderResult(")[1].split("\nfunction ")[0]
        self.assertIn("renderPriceVerdict(result)", assembly)

    def test_block_01_still_verdict_free(self):
        # renderTheBet (block 01) must still pass no verdict/priceStanding
        # literal to the Featured Bet mapper -- the price-verdict addition
        # lives in its own new block, never folded into block 01.
        the_bet = self.text.split("function renderTheBet(")[1].split("\nfunction ")[0]
        self.assertNotRegex(the_bet, r"verdict\s*:\s*[\"']\w+[\"']")
        self.assertNotRegex(the_bet, r"priceStanding\s*:\s*\{")


class GamesModelVsMarketWiredHonestly(unittest.TestCase):
    def setUp(self):
        self.text = _read(GAMES_PATH)

    def test_model_vs_market_hook_present(self):
        self.assertIn('"model-vs-market"', self.text)

    def test_reads_price_verdicts_and_engine_from_the_payload(self):
        self.assertIn("payload.price_verdicts", self.text)
        self.assertIn("payload.engine", self.text)

    def test_independent_model_line_states_the_literal(self):
        self.assertIn("NO INDEPENDENT MODEL YET", self.text)


class AnalyticalCutsRendered(unittest.TestCase):
    """Task C3: the four cuts tables plus the ROLLING row and the THIN
    SAMPLE chip, all rendered below the class sections and above recent
    picks (see performance.js's own `renderPerformance` assembly order)."""

    def setUp(self):
        self.text = _read(PERFORMANCE_PATH)

    def test_four_table_titles_present(self):
        for title in ("BY MARKET", "BY ODDS RANGE", "BY DECISION GRADE", "BY CLASS"):
            self.assertIn(title, self.text)

    def test_rolling_row_present(self):
        self.assertIn("ROLLING", self.text)
        self.assertIn("LAST 7 DAYS", self.text)
        self.assertIn("LAST 30 DAYS", self.text)

    def test_thin_sample_literal_present(self):
        self.assertIn("THIN SAMPLE", self.text)

    def test_cuts_render_function_defined_and_called(self):
        self.assertRegex(self.text, r"\bfunction renderCuts\s*\(")
        self.assertIn("renderCuts(payload.cuts, payload.cuts_note)", self.text)

    def test_cuts_rendered_between_class_sections_and_recent_picks(self):
        classes_at = self.text.index("renderClassSections(payload.classes, payload.systems)")
        cuts_at = self.text.index("renderCuts(payload.cuts, payload.cuts_note)")
        picks_at = self.text.index("renderRecentPicks(payload.recent_picks)")
        self.assertLess(classes_at, cuts_at)
        self.assertLess(cuts_at, picks_at)

    def test_thin_bucket_never_gets_a_pos_or_neg_colour_class(self):
        # cutsSignedCell must early-return a plain, class-free <td> when
        # the bucket is thin, before ever computing perf-cuts__figure--pos
        # /--neg -- i.e. the thin guard reads BEFORE the colour ternary.
        fn = self.text.split("function cutsSignedCell(")[1].split("\nfunction ")[0]
        thin_check_at = fn.index("if (thin)")
        colour_ternary_at = fn.index("perf-cuts__figure--pos")
        self.assertLess(thin_check_at, colour_ternary_at)

    def test_units_and_return_never_zero_filled_when_absent(self):
        # cutsSignedCell must render "—" for a non-number, never coerce a
        # missing units/return figure to 0.
        fn = self.text.split("function cutsSignedCell(")[1].split("\nfunction ")[0]
        self.assertIn('"—"', fn)
        self.assertNotRegex(fn, r"\|\|\s*0\b")


if __name__ == "__main__":
    unittest.main()
