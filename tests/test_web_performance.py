"""Structural checks for the hosted-demo sprint's new front-end surfaces:

  - web/js/performance.js (#/performance, GET /performance)
  - web/js/opportunities.js -- DELETED 2026-09-12 with the price-comparison register
  - web/js/valuemeter.js (the shared MARKET-IMPLIED vs YOUR-PRICE bars)
  - main.js's #/performance route registration and RESULTS nav item
  - betcheck.js's new price-verdict block and games.js's MODEL vs MARKET
    panel, at least at the "does not violate the honesty boundary" level

A plain-text scan, like tests/test_web_structure.py and
tests/test_web_v2_betcheck.py -- never starts a server, never imports a JS
engine.

ADDED 2026-09-12 (docs/DECISION_TODAY_ONE_ANSWER.md option A1,
owner-approved): `TheEngineSlipMovedHere` covers the slip's move from
#/today to this screen -- web/js/slip.js now owns `renderTonightsPicks`
and this module is its only caller.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.test_customer_language import HARD_BANNED, NEGATION_ONLY, NEGATORS

ROOT = Path(__file__).resolve().parent.parent
WEB_JS = ROOT / "web" / "js"

PERFORMANCE_PATH = WEB_JS / "performance.js"
VALUEMETER_PATH = WEB_JS / "valuemeter.js"
MAIN_PATH = WEB_JS / "main.js"
BETCHECK_PATH = WEB_JS / "betcheck.js"
GAMES_PATH = WEB_JS / "games.js"
TODAY_PATH = WEB_JS / "today.js"
DOM_PATH = WEB_JS / "dom.js"
SLIP_PATH = WEB_JS / "slip.js"

NEW_JS_FILES = (PERFORMANCE_PATH, VALUEMETER_PATH)

BANNED_PROBABILITY_TOKENS = (
    "win_probability", "winProbability", "modelProbability", "true_probability",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_body(text: str, start: int) -> str:
    """`text` from `start` up to (not including) the next top-level
    function declaration, or to end-of-file when `start`'s function is the
    last one in the module -- `renderEngineSlipSection` is, in
    performance.js, so a fixed "\\nfunction " sentinel (this file's older
    pattern) raises ValueError instead of finding the boundary, since the
    next declaration is `export async function renderPerformance(`."""
    m = re.search(r"\n(?:export\s+(?:async\s+)?)?function\s", text[start + 1:])
    return text[start:start + 1 + m.start()] if m else text[start:]


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


class PriceVerdictBlockRetired(unittest.TestCase):
    """betcheck.js's PRICE VERDICT panel is gone, and stays gone.

    This class used to pin the panel IN: its hook, its function, its call
    in renderResult. The panel printed a one-word verdict ("PASS") on the
    gap between the reader's price and the de-vigged consensus, under a
    value meter -- the price-comparison register the owner retired on
    2026-09-10. Swept live on 2026-09-12 it was still there. The
    assertions are now inverted, deliberately, with this note so nobody
    reads the old version out of git and restores it as a regression fix.
    """

    def setUp(self):
        self.text = _read(BETCHECK_PATH)

    def test_price_verdict_hook_absent(self):
        self.assertNotIn('"bet-check-price-verdict"', self.text)

    def test_price_verdict_function_gone(self):
        self.assertNotRegex(self.text, r"\bfunction renderPriceVerdict\s*\(")

    def test_not_called_in_render_result(self):
        assembly = self.text.split("function renderResult(")[1].split("\nfunction ")[0]
        self.assertNotIn("renderPriceVerdict(", assembly)

    def test_block_01_still_verdict_free(self):
        the_bet = self.text.split("function renderTheBet(")[1].split("\nfunction ")[0]
        self.assertNotRegex(the_bet, r"verdict\s*:\s*[\"']\w+[\"']")
        self.assertNotRegex(the_bet, r"priceStanding\s*:\s*\{")


class GamesModelVsMarketWiredHonestly(unittest.TestCase):
    def setUp(self):
        self.text = _read(GAMES_PATH)

    def test_model_vs_market_block_is_retired(self):
        """Retired 2026-09-12 with the rest of the price-comparison
        register; see tests/test_web_v2_game.py::SpotlightRetired."""
        self.assertNotIn('"model-vs-market"', self.text)

    def test_reads_the_engine_record_but_no_price_verdicts(self):
        self.assertNotIn("payload.price_verdicts", self.text)
        self.assertIn("payload.engine", self.text)

    def test_the_no_independent_model_line_is_gone(self):
        """It stopped being true when the card got its own run model."""
        self.assertNotIn("NO INDEPENDENT MODEL YET", self.text)


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


class TheEngineSlipMovedHere(unittest.TestCase):
    """A1: the slip that used to lead #/today now renders on #/performance,
    under a heading that says plainly it is research, not the card."""

    def test_slip_module_exists_and_is_imported(self):
        self.assertTrue(SLIP_PATH.is_file(), "web/js/slip.js is missing")
        self.assertTrue(_read(SLIP_PATH).strip(), "slip.js is empty")
        text = _read(PERFORMANCE_PATH)
        self.assertIn('from "./slip.js"', text)
        self.assertIn("renderTonightsPicks", text)

    def test_performance_mounts_the_tonights_picks_hook(self):
        # UPDATED 2026-09-12 (checker finding): the previous version of this
        # test only checked the hook STRING exists somewhere in slip.js --
        # true of a performance.js that defined renderEngineSlipSection and
        # never called it, or called it and never mounted the result. This
        # walks the real call chain instead: the hook lives in slip.js's own
        # markup (reached only through renderTonightsPicks), and that
        # function is reachable only by tracing renderEngineSlipSection
        # actually calling it AND appending what it returns, and
        # renderPerformance actually calling renderEngineSlipSection AND
        # appending its result to the screen.
        self.assertIn('"data-hook": "tonights-picks"', _read(SLIP_PATH))

        text = _read(PERFORMANCE_PATH)
        fn_at = text.find("function renderEngineSlipSection(")
        self.assertNotEqual(-1, fn_at, "renderEngineSlipSection is gone")
        fn_body = _function_body(text, fn_at)
        self.assertRegex(fn_body, r"renderTonightsPicks\(\s*slip",
                         "renderEngineSlipSection never calls renderTonightsPicks")
        self.assertIn("section.appendChild(picks)", fn_body,
                     "renderEngineSlipSection builds the picks node but "
                     "never mounts it into the section it returns")

        render_at = text.find("export async function renderPerformance(")
        self.assertNotEqual(-1, render_at, "renderPerformance is gone")
        render_body = text[render_at:]
        call_at = render_body.find("renderEngineSlipSection(")
        mount_at = render_body.find("screen.appendChild(slipSection)")
        self.assertNotEqual(-1, call_at,
                            "renderPerformance never calls renderEngineSlipSection")
        self.assertNotEqual(-1, mount_at,
                            "renderPerformance builds the slip section but "
                            "never mounts it onto the screen")
        self.assertLess(call_at, mount_at,
                        "the slip section is mounted before it is built")

    def test_performance_fetches_today_for_the_slip_not_a_new_endpoint(self):
        # GET /today is where the slip is served (src/engine/slip.py via
        # the /today route) -- this screen must read it from there, not
        # invent a dedicated endpoint the mission explicitly forbids adding.
        text = _read(PERFORMANCE_PATH)
        self.assertIn('apiGet("/today")', text)

    def test_the_slip_section_does_not_point_at_a_card_not_on_this_page(self):
        # Checker finding, 2026-09-12: the section used to say "a different,
        # stricter rule than the card's market-confidence ranking above" --
        # but nothing named "the card" renders above it on #/performance,
        # only the RESEARCH — NOT THE CARD banner and a link to
        # #/record-card. Honesty rule: a page must not point a reader at
        # something that is not on the screen.
        text = _read(PERFORMANCE_PATH)
        fn_at = text.find("function renderEngineSlipSection(")
        self.assertNotEqual(-1, fn_at, "renderEngineSlipSection is gone")
        fn_body = _function_body(text, fn_at)
        self.assertNotIn("ranking above", fn_body,
                         "this section still claims something renders "
                         "\"above\" it that is not actually on this page")

    def test_the_slip_section_is_not_the_amber_warn_callout(self):
        # Checker finding, 2026-09-12: reusing .perf-whose (a warn-amber
        # callout sized for one short paragraph) around the whole picks
        # grid, itself still carrying .gutter, doubled up the padding and
        # rendered as an oversized amber warning box. The slip section must
        # use its own, non-warn wrapper class, and the nested picks grid
        # must not carry a second full-bleed gutter inside it.
        text = _read(PERFORMANCE_PATH)
        fn_at = text.find("function renderEngineSlipSection(")
        self.assertNotEqual(-1, fn_at, "renderEngineSlipSection is gone")
        fn_body = _function_body(text, fn_at)
        self.assertNotIn("perf-whose", fn_body,
                         "the slip section reuses the amber warn-callout class")
        self.assertRegex(fn_body, r"nested:\s*true",
                         "the nested picks grid keeps its own full gutter, "
                         "double-padding inside this section's panel")

    def test_the_slip_section_names_its_own_thin_history_honestly(self):
        # The slip has seven bets ever tagged published -- too few for a
        # record, and this section must say so rather than pool it with
        # the FORWARD_TEST classes' hundreds of paper positions below.
        text = _read(PERFORMANCE_PATH).lower()
        self.assertIn("seven bets", text)
        self.assertIn("too few for a record", text)

    def test_the_research_heading_is_present(self):
        # UPDATED 2026-09-12 (checker finding): "RESEARCH" and
        # "renderEngineSlipSection" both existing SOMEWHERE in the file
        # passes even if they never appear together -- the top-of-page
        # "RESEARCH — NOT THE CARD" banner alone would satisfy it. Scoped
        # to renderEngineSlipSection's own body so the heading text is
        # actually the one this section renders, not a different banner
        # elsewhere on the page.
        text = _read(PERFORMANCE_PATH)
        fn_at = text.find("function renderEngineSlipSection(")
        self.assertNotEqual(-1, fn_at, "renderEngineSlipSection is gone")
        fn_body = _function_body(text, fn_at)
        self.assertIn("RESEARCH", fn_body,
                      "renderEngineSlipSection's own heading no longer says RESEARCH")

    def test_the_slip_section_has_no_duplicate_leading_heading(self):
        # Checker finding, 2026-09-12: the moved renderer used to print its
        # own Today-era eyebrow/headline ("TONIGHT'S PICKS" / "Where our
        # systems currently see the strongest case.") immediately under
        # this section's "THE ENGINE'S OWN SLIP — RESEARCH" heading -- two
        # stacked headings reading as a second pick feed directly under the
        # label saying this is not one. renderEngineSlipSection must pass
        # slip.js's renderTonightsPicks an explicit eyebrow/headline
        # override (null or otherwise), not rely on that function's
        # Today-flavoured defaults.
        text = _read(PERFORMANCE_PATH)
        fn_at = text.find("function renderEngineSlipSection(")
        self.assertNotEqual(-1, fn_at, "renderEngineSlipSection is gone")
        fn_body = _function_body(text, fn_at)
        call = re.search(r"renderTonightsPicks\(\s*slip\s*,\s*\{", fn_body)
        self.assertIsNotNone(call,
                             "renderEngineSlipSection calls renderTonightsPicks "
                             "with no copy override, so it renders Today's own "
                             "eyebrow/headline as a second heading here")
        self.assertNotIn("TONIGHT'S PICKS", fn_body)
        self.assertNotIn("strongest case", fn_body)


if __name__ == "__main__":
    unittest.main()
