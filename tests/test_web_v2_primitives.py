"""Structural checks for LINEHOUND V2 Wave 0's two shared primitives:
web/js/states.js (V2-27..30, the shared loading/empty/unavailable/error
states) and web/js/featuredbet.js (V2-32's Tier A "bet standing" hero
card) -- design/linehound-v2/IMPLEMENTATION_PLAN.md's Wave 0, Group F
and Group S.

This is a static text scan, like tests/test_web_structure.py -- it never
starts a server and never imports a JS engine. It checks:

  - the two files exist and are non-empty;
  - states.js does not FORK dom.js's existing loading/error/not-yet-
    available primitives (re-exports them, never redefines a function of
    the same name);
  - featuredbet.js is the ONE definition of `renderFeaturedBet` under
    web/js/ -- no Wave-1 screen has copy-pasted it yet;
  - neither module has been wired into a Wave-1 screen file yet (Wave 0
    "ships the component and its call signature", per the plan -- the
    day a Wave-1 worker wires one in, this specific assertion is
    expected to be updated alongside that work, not silently routed
    around);
  - no banned customer-facing vocabulary, reusing tests/test_customer_language's
    own lists rather than retyping them (the task's own instruction);
  - a short list of "never fabricate" guards specific to this lane's
    boundary (see BOUNDARIES in the launching task): no default verdict,
    no counterargument count taken from the padded `counterargument_lines`
    array, no fabricated loading-progress figure, no fabricated "next
    slate" tile.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.test_customer_language import HARD_BANNED, NEGATION_ONLY, NEGATORS

ROOT = Path(__file__).resolve().parent.parent
WEB_JS = ROOT / "web" / "js"

STATES_PATH = WEB_JS / "states.js"
FEATUREDBET_PATH = WEB_JS / "featuredbet.js"

WAVE1_SCREEN_FILES = ("betcheck.js", "games.js", "odds.js", "mybets.js", "main.js")
# today.js was wired in by LANE L19 (V2-01/01a/b/c/22/33, the Gameday
# family) -- see tests/test_web_v2_gameday.py for its own coverage of
# that wiring. Removed from this "not yet wired" list per this file's
# own docstring instruction to update it in the same change that adds
# the real import, not route around it.


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class FilesExist(unittest.TestCase):
    def test_states_js_exists_and_nonempty(self):
        self.assertTrue(STATES_PATH.is_file())
        self.assertTrue(_read(STATES_PATH).strip())

    def test_featuredbet_js_exists_and_nonempty(self):
        self.assertTrue(FEATUREDBET_PATH.is_file())
        self.assertTrue(_read(FEATUREDBET_PATH).strip())


class SharedStatesWrapDomJs(unittest.TestCase):
    """V2-27..30's implementer note: 'if web/js/dom.js already exports
    renderLoading/renderError etc., states.js must WRAP or re-export
    them so there is ONE definition; do not fork the markup.'"""

    def test_reexports_not_redefines_existing_dom_primitives(self):
        text = _read(STATES_PATH)
        # Re-exported (imported from dom.js and/or named in an `export {...}`
        # list) -- never redefined with `function renderLoading(...)` etc.,
        # which would be a second, forkable definition of the same markup.
        for name in ("renderLoading", "renderError", "notYetAvailable"):
            self.assertIn(name, text, f"{name} should be re-exported from dom.js")
            self.assertNotRegex(
                text, rf"\bfunction\s+{name}\s*\(",
                f"states.js must not redefine {name} -- re-export dom.js's own")
        self.assertIn('from "./dom.js"', text)

    def test_adds_four_new_v2_state_primitives(self):
        text = _read(STATES_PATH)
        for name in ("renderLoadingSkeleton", "renderEmptySlate",
                     "renderCaptureUnavailable", "renderWriteFailed"):
            self.assertRegex(text, rf"\bexport function {name}\s*\(", name)


class FeaturedBetSingleDefinition(unittest.TestCase):
    def test_render_featured_bet_exported_once_under_web_js(self):
        matches = []
        for path in sorted(WEB_JS.glob("*.js")):
            text = _read(path)
            if re.search(r"\bfunction\s+renderFeaturedBet\s*\(", text):
                matches.append(path.name)
        self.assertEqual(matches, ["featuredbet.js"],
                          "renderFeaturedBet must be defined in exactly one file")

    def test_exports_the_documented_call_signature(self):
        text = _read(FEATUREDBET_PATH)
        self.assertRegex(text, r"\bexport function renderFeaturedBet\s*\(")
        self.assertRegex(text, r"\bexport function mapBetCheckPayloadToStanding\s*\(")

    def test_wave1_screens_not_wired_in_yet(self):
        # Wave 0 publishes the component and its call signature only --
        # IMPLEMENTATION_PLAN.md is explicit that wiring it into a
        # consuming screen is Wave 1's job, in that screen's own file.
        # This assertion documents that boundary; a Wave-1 worker should
        # update it in the same change that adds the real import.
        for name in WAVE1_SCREEN_FILES:
            path = WEB_JS / name
            if not path.is_file():
                continue
            text = _read(path)
            self.assertNotIn("featuredbet.js", text,
                              f"{name} should not import featuredbet.js yet (Wave 1's job)")


class NeverFabricateGuards(unittest.TestCase):
    """Boundary-specific tripwires -- narrower than the general banned-
    vocabulary scan, these catch the specific shortcuts this lane's
    BOUNDARIES section calls out by name."""

    def test_no_default_verdict(self):
        text = _read(FEATUREDBET_PATH)
        # A caller-absent verdict must render NOT AVAILABLE, never fall
        # back to "no_play" (the majority real-world case) as if that
        # were a real answer for THIS bet.
        self.assertNotRegex(text, r"verdict\s*\|\|\s*[\"']no_play[\"']")
        self.assertNotRegex(text, r"verdict\s*(:|=)\s*[\"']no_play[\"']\s*;?\s*//.*default", re.IGNORECASE)

    def test_counterargument_count_uses_raw_array_not_padded_lines(self):
        text = _read(FEATUREDBET_PATH)
        self.assertIn("p.counterargument.length", text)
        self.assertNotIn("counterargument_lines.length", text)

    def test_price_standing_never_computed_from_a_rank(self):
        text = _read(FEATUREDBET_PATH)
        # "priceStanding" may only ever be READ from caller-supplied
        # input (mapBetCheckPayloadToStanding's `extra.priceStanding`)
        # -- never derived from board/price fields on this module's own.
        self.assertIn("extra.priceStanding", text)
        self.assertNotRegex(text, r"priceStanding\s*=\s*\{[^}]*betterThan\s*:\s*\w+\.length")

    def test_loading_skeleton_never_prints_a_fabricated_progress_figure(self):
        text = _read(STATES_PATH)
        # The manifest's own artboard illustrates "9 OF 11 BOOKS IN" --
        # explicitly listed under V2-27's fields_NOT_available. Guard
        # against that example fixture leaking into the shared primitive
        # as if it were real.
        self.assertNotIn("BOOKS IN", text)
        self.assertNotRegex(text, r"\d+\s+OF\s+\d+\s+BOOKS")

    def test_empty_slate_never_fabricates_a_next_slate_tile(self):
        text = _read(STATES_PATH)
        # The artboard's "NEXT SLATE: TOMORROW" tile has no backing field
        # anywhere in the API -- never hardcode it into the shared helper.
        self.assertNotIn("NEXT SLATE", text)
        self.assertNotIn("TOMORROW", text)


class NoBannedVocabulary(unittest.TestCase):
    """Reuses tests/test_customer_language's own banned-phrase lists
    (per this lane's instruction to reuse rather than duplicate) --
    applied here explicitly to the two new files, independent of
    tests/test_web_structure.py's separate (and already-passing) sweep
    of every file under web/."""

    def test_no_hard_banned_or_unnegated_phrases(self):
        violations = []
        for path in (STATES_PATH, FEATUREDBET_PATH):
            text = path.read_text(encoding="utf-8")
            for pattern, label in HARD_BANNED:
                if re.search(pattern, text, re.IGNORECASE):
                    violations.append(f"{path.name}: hard-banned {label!r}")
            for pattern, label in NEGATION_ONLY:
                for m in re.finditer(pattern, text, re.IGNORECASE):
                    window = text[max(0, m.start() - 90):m.start()]
                    if not NEGATORS.search(window):
                        violations.append(f"{path.name}: {label!r} affirmed (no negation nearby)")
        self.assertEqual(violations, [], "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
