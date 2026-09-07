"""Structural checks for the F3 final-polish lane's three jobs:

  - web/js/landing.js + web/landing.html: a public-demo entry point beside
    the existing signup CTA, revealed only when GET /meta says
    `public_demo` is true.
  - web/js/games.js: one consolidated explainer panel above a long
    (4+) gap ledger on the Game Advanced view, with the per-gap detail
    collapsed beneath a labelled `<details>` rather than deleted.
  - web/js/today.js: a "LAST NIGHT'S RESULTS" link near the slate-date
    banner, shown only when the slate has rolled to the next Eastern date.

A plain-text scan, like tests/test_web_structure.py and
tests/test_web_matchups.py -- never starts a server, never imports a JS
engine.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.test_customer_language import HARD_BANNED, NEGATION_ONLY, NEGATORS

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
WEB_JS = WEB_DIR / "js"

LANDING_JS = WEB_JS / "landing.js"
LANDING_HTML = WEB_DIR / "landing.html"
GAMES_JS = WEB_JS / "games.js"
TODAY_JS = WEB_JS / "today.js"

TOUCHED_FILES = (LANDING_JS, LANDING_HTML, GAMES_JS, TODAY_JS)

# Same tripwire tests/test_web_matchups.py already checks for
# BANNED_PROBABILITY_TOKENS -- restated here rather than imported since it
# is a plain tuple, not part of test_customer_language.py's own exports
# (which only carry the phrase-level HARD_BANNED/NEGATION_ONLY lists).
BANNED_IDENTIFIER_TOKENS = (
    "win_probability", "winProbability", "modelProbability", "true_probability",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class LandingPublicDemoEntryTests(unittest.TestCase):
    """Job 1: a way into the demo from the front door."""

    def setUp(self):
        self.js = _read(LANDING_JS)
        self.html = _read(LANDING_HTML)

    def test_fetches_meta_and_gates_on_public_demo(self):
        self.assertIn("apiGet", self.js)
        self.assertIn('"/meta"', self.js)
        self.assertIn("public_demo", self.js)

    def test_contains_the_literal_open_the_live_demo_copy(self):
        self.assertIn("OPEN THE LIVE DEMO", self.js + self.html)

    def test_demo_entry_links_to_today_with_no_signup(self):
        self.assertIn("index.html#/today", self.js + self.html)

    def test_entry_point_starts_hidden_in_markup(self):
        # Revealed only by JS once /meta confirms public_demo -- if /meta
        # never resolves (or resolves false) the element must never show.
        match = re.search(
            r'<div class="hero__demo-entry" data-hook="public-demo-entry"[^>]*>',
            self.html)
        self.assertIsNotNone(match, "public-demo-entry host not found in landing.html")
        self.assertIn("hidden", match.group(0))

    def test_reveal_only_flips_hidden_false_never_removes_the_gate(self):
        # The gate itself (host.hidden = false) must be conditioned on the
        # meta.public_demo read, not unconditional.
        fn_match = re.search(
            r"async function revealPublicDemoEntry\(\)\s*\{(.*?)\n\}",
            self.js, re.DOTALL)
        self.assertIsNotNone(fn_match, "revealPublicDemoEntry() not found")
        body = fn_match.group(1)
        self.assertIn("public_demo", body)
        self.assertIn("hidden = false", body)
        # The catch branch must not also reveal the entry -- an unreachable
        # /meta must change nothing about the page.
        try_catch = re.search(r"try\s*\{(.*?)\}\s*catch[^{]*\{(.*?)\n  \}", body, re.DOTALL)
        self.assertIsNotNone(try_catch, "expected a try/catch around the /meta fetch")
        self.assertNotIn("hidden = false", try_catch.group(2))

    def test_existing_ctas_and_sample_slate_label_untouched(self):
        # Every pre-existing primary CTA and the sample-slate badge must
        # still be present verbatim -- this job only adds an element, never
        # removes or rewords one.
        for needle in (
            "Try 3 Bet Checks free",
            'data-hook="cta-signup-hero"',
            'data-hook="cta-signup"',
            'data-hook="cta-signup-bottom"',
            'data-hook="sample-slate-badge"',
            "Sample slate · demo data",
        ):
            self.assertIn(needle, self.html, f"missing pre-existing copy/hook: {needle!r}")

    def test_pricing_and_faq_copy_untouched(self):
        self.assertIn("Run three bets on us first.", self.html)
        self.assertIn("Frequently asked questions.", self.html)


class GamesConsolidatedGapPanelTests(unittest.TestCase):
    """Job 2: explain the empty game screen once instead of twelve times."""

    def setUp(self):
        self.js = _read(GAMES_JS)

    def test_consolidated_panel_explains_what_is_actually_true(self):
        """The panel must describe THIS game's gaps, never a fixed list.

        It used to pin the sentence "team records, bullpen, splits,
        handedness, lineups -- are not in this build". F-2 (2026-09-07)
        wired those stores in, and that sentence then sat directly under an
        identity panel showing 69-74 -- a contradiction, not an
        explanation. The invariant this test is named for is truthfulness,
        so it now asserts the panel is built from the payload's own gap
        keys and that the stale fixed list is gone for good.
        """
        self.assertIn("gavGapsConsolidated(gapKeys)", self.js)
        self.assertNotIn("team records, bullpen, splits, handedness, lineups", self.js,
                         "the fixed gap list is back -- it was false the day F-2 landed")
        # The RENDERED template literal, not the bare phrase: the phrase also
        # appears in a code comment describing the old design, and a comment
        # is not something a customer sees.
        self.assertNotIn("${keys.length} SECTIONS NOT IN THIS BUILD", self.js,
                         "a night with no prices is a gap on the game, not in the build")
        for phrase in (
            "NOT AVAILABLE FOR THIS GAME",
            "named gap",
            "reported as",
            "humanizeKey(k)",   # the names come from the gap keys themselves
        ):
            self.assertIn(phrase, self.js, f"consolidated panel missing: {phrase!r}")

    def test_consolidated_panel_reuses_not_yet_available_not_new_markup(self):
        # Per the lane's own rule: absent data uses dom.js's notYetAvailable
        # or an honest sentence -- never invented markup.
        fn_match = re.search(
            r"function gavGapsConsolidated\([^)]*\)\s*\{(.*?)\n\}",
            self.js, re.DOTALL)
        self.assertIsNotNone(fn_match, "gavGapsConsolidated() not found")
        self.assertIn("notYetAvailable(", fn_match.group(1))

    def test_four_or_more_gaps_triggers_consolidation(self):
        self.assertIn("keys.length >= 4", self.js)

    def test_collapsed_details_labelled_with_the_gap_count(self):
        self.assertIn("SECTIONS NOT IN THIS BUILD -- SHOW REASONS", self.js)
        self.assertIn('"gav-gaps__collapse"', self.js)
        self.assertIn('"data-hook": "coverage-gaps-collapsed"', self.js)

    def test_per_gap_detail_still_rendered_verbatim_inside_the_collapse(self):
        # The individual gap rows (data-hook + verbatim reason string) must
        # still exist unconditionally -- this job collapses them, never
        # deletes them, and never invents a reason of its own.
        self.assertIn('"data-hook": "coverage-gap"', self.js)
        self.assertIn('"data-hook": "coverage-gap-reason"', self.js)
        self.assertIn("text: String(gaps[key])", self.js)

    def test_one_or_two_gaps_render_inline_unchanged(self):
        # The consolidate branch must be conditioned on the >=4 threshold,
        # not applied unconditionally -- so gavGaps has a real branch.
        fn_match = re.search(
            r"function gavGaps\(advanced\)\s*\{(.*?)\n\}\n",
            self.js, re.DOTALL)
        self.assertIsNotNone(fn_match, "gavGaps() not found")
        body = fn_match.group(1)
        self.assertIn("if (consolidate)", body)
        self.assertIn("} else {", body)


class PriceWindowNoteTests(unittest.TestCase):
    """The board correctly stops ageing forward overnight: the capture only
    buys prices within three hours of a first pitch (dense.py's
    WINDOW_MINUTES), so a morning visitor sees a ten-hour-old board. Without
    a sentence saying why, that reads as a broken feed. It must say so ONLY
    when no game is close -- a stale board with a game inside the window is a
    real problem and must not be explained away."""

    def setUp(self):
        self.js = (WEB_JS / "today.js").read_text(encoding="utf-8")

    def test_mirrors_the_server_window_and_says_so(self):
        self.assertIn("PRICE_WINDOW_MINUTES = 180", self.js)
        self.assertIn("WINDOW_MINUTES", self.js)  # names the server constant it mirrors

    def test_requires_both_a_stale_board_and_a_distant_first_pitch(self):
        body = re.search(r"function priceWindowNote\(([^)]*)\)\s*\{(.*?)\n\}",
                         self.js, re.DOTALL)
        self.assertIsNotNone(body, "priceWindowNote() not found")
        text = body.group(2)
        # returns nothing while the board is fresh...
        self.assertIn("ageMinutes <= PRICE_WINDOW_MINUTES", text)
        # ...and nothing once a game is inside the window, when an old board
        # would be a genuine problem rather than the design.
        self.assertIn("minutesToFirstPitch <= PRICE_WINDOW_MINUTES", text)
        self.assertIn("first_pitch_utc", text)

    def test_renders_through_its_own_hook(self):
        self.assertIn('"data-hook": "price-window-note"', self.js)


class TodayLastNightLinkTests(unittest.TestCase):
    """Job 3: reach last night's result from Today."""

    def setUp(self):
        self.js = _read(TODAY_JS)

    def test_contains_last_night_results_link_text(self):
        self.assertIn("LAST NIGHT'S RESULTS", self.js)

    def test_links_to_the_day_route_for_the_current_eastern_date(self):
        self.assertIn("#/day/${encodeURIComponent(currentEastern)}", self.js)

    def test_reuses_the_existing_eastern_date_helper_no_second_convention(self):
        # Exactly one definition of the helper -- this job must not add a
        # second, competing date convention.
        self.assertEqual(
            len(re.findall(r"function currentEasternDateIso\(\)", self.js)), 1)
        # And renderSlateBanner calls it (rather than reimplementing the
        # comparison against a differently-sourced date).
        fn_match = re.search(
            r"function renderSlateBanner\(dateIso[^)]*\)\s*\{(.*?)\n\}",
            self.js, re.DOTALL)
        self.assertIsNotNone(fn_match, "renderSlateBanner() not found")
        body = fn_match.group(1)
        self.assertIn("currentEasternDateIso()", body)
        self.assertEqual(body.count("currentEasternDateIso()"), 1,
                          "currentEastern should be computed once and reused, "
                          "not called again for the link")

    def test_link_only_renders_when_slate_date_is_ahead_of_eastern_date(self):
        fn_match = re.search(
            r"function renderSlateBanner\(dateIso[^)]*\)\s*\{(.*?)\n\}",
            self.js, re.DOTALL)
        self.assertIsNotNone(fn_match)
        body = fn_match.group(1)
        if_match = re.search(r"if \(isNext\)\s*\{(.*?)\n  \}", body, re.DOTALL)
        self.assertIsNotNone(if_match, "expected an `if (isNext)` guard")
        self.assertIn("LAST NIGHT'S RESULTS", if_match.group(1))
        # And nothing outside that guard mentions the link -- so it truly
        # renders nothing when the slate date equals today's ET date.
        outside = body.replace(if_match.group(0), "")
        self.assertNotIn("LAST NIGHT'S RESULTS", outside)


class TouchedFilesVocabularyTests(unittest.TestCase):
    """No banned customer-facing vocabulary or banned identifier tokens in
    any file this lane touched -- same tripwire lists
    tests/test_web_structure.py already applies across all of web/."""

    def test_no_hard_banned_phrases(self):
        violations = []
        for path in TOUCHED_FILES:
            text = _read(path)
            for pattern, label in HARD_BANNED:
                if re.search(pattern, text, re.IGNORECASE):
                    violations.append(f"{path.relative_to(ROOT)}: {label!r}")
        self.assertEqual(violations, [], "\n".join(violations))

    def test_no_unnegated_negation_only_phrases(self):
        violations = []
        for path in TOUCHED_FILES:
            text = _read(path)
            for pattern, label in NEGATION_ONLY:
                for m in re.finditer(pattern, text, re.IGNORECASE):
                    window = text[max(0, m.start() - 90):m.start()]
                    if not NEGATORS.search(window):
                        violations.append(
                            f"{path.relative_to(ROOT)}: {label!r} affirmed "
                            f"(no negation nearby)")
        self.assertEqual(violations, [], "\n".join(violations))

    def test_no_banned_identifier_tokens(self):
        violations = []
        for path in TOUCHED_FILES:
            text = _read(path)
            for token in BANNED_IDENTIFIER_TOKENS:
                if token in text:
                    violations.append(f"{path.relative_to(ROOT)}: {token!r}")
        self.assertEqual(violations, [], "\n".join(violations))

    def test_no_verdict_or_default_style_fallback(self):
        # Vocabulary tripwire: never a `verdict || "no_play"` style default.
        pattern = re.compile(r'verdict\s*\|\|\s*["\']no_play["\']')
        for path in TOUCHED_FILES:
            text = _read(path)
            self.assertIsNone(pattern.search(text),
                               f"{path.relative_to(ROOT)} defaults a verdict")


if __name__ == "__main__":
    unittest.main()
