"""Structural checks for LANE L19 -- LINEHOUND V2 Wave 1, Group Gameday:
web/js/today.js's V2-01 (carousel default), V2-01a NO_PLAY, V2-01b
FLAGGED, V2-01c MARKET_UNAVAILABLE, V2-22 (mobile) and V2-33 (the
Featured Bet carousel head).

Static text scan, like tests/test_web_structure.py and
tests/test_web_v2_primitives.py -- never starts a server, never imports
a JS engine. Checks:

  - today.js exists, is non-empty, and still exports `renderToday` (the
    one function main.js imports -- IMPLEMENTATION_PLAN.md's ownership
    rule for this lane).
  - main.js was not touched (routing changes are out of this lane's
    ownership; a routing need gets reported, not silently made).
  - today.js wires in the two Wave 0 shared primitives (states.js,
    featuredbet.js) rather than forking their markup.
  - the three verdict-state hero builders exist (V2-01a/b/c) and the
    feature-selection rule never hardcodes a favourite side.
  - no banned customer-facing vocabulary, reusing
    tests/test_customer_language's own lists.
  - a short list of "never fabricate" guards specific to this lane's
    boundary: no hardcoded forward-ledger percentage, no default verdict
    on the Featured Bet standing, POST /betcheck's price always reads a
    real field.
  - the new screens.css section exists, is scoped to the `gv2-` prefix,
    and carries a mobile (<=899px) reflow for V2-22.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.test_customer_language import HARD_BANNED, NEGATION_ONLY, NEGATORS

ROOT = Path(__file__).resolve().parent.parent
WEB_JS = ROOT / "web" / "js"
TODAY_PATH = WEB_JS / "today.js"
MAIN_PATH = WEB_JS / "main.js"
SCREENS_CSS_PATH = ROOT / "web" / "css" / "screens.css"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class FileExists(unittest.TestCase):
    def test_today_js_exists_and_nonempty(self):
        self.assertTrue(TODAY_PATH.is_file())
        self.assertTrue(_read(TODAY_PATH).strip())


class MainJsUntouchedContract(unittest.TestCase):
    """OWNERSHIP: "keep every exported function name main.js imports ...
    do NOT edit main.js". This checks the contract from the outside --
    main.js still imports exactly `renderToday` from today.js, and
    today.js still exports it."""

    def test_render_today_is_exported(self):
        text = _read(TODAY_PATH)
        self.assertRegex(text, r"\bexport\s+async\s+function\s+renderToday\s*\(")

    def test_main_js_still_imports_render_today_from_today_js(self):
        text = _read(MAIN_PATH)
        self.assertRegex(text, r'import\s*\{\s*renderToday\s*\}\s*from\s*"\./today\.js"')


class WiresWave0PrimitivesWithoutForking(unittest.TestCase):
    def test_imports_states_js_primitives(self):
        text = _read(TODAY_PATH)
        self.assertIn('from "./states.js"', text)
        for name in ("renderError", "renderLoadingSkeleton", "renderEmptySlate",
                     "renderCaptureUnavailable"):
            self.assertIn(name, text, f"{name} should be imported from states.js")

    def test_imports_featured_bet_primitive(self):
        text = _read(TODAY_PATH)
        self.assertIn('from "./featuredbet.js"', text)
        self.assertIn("renderFeaturedBet", text)
        self.assertIn("mapBetCheckPayloadToStanding", text)

    def test_does_not_redefine_shared_primitives(self):
        text = _read(TODAY_PATH)
        for name in ("renderFeaturedBet", "renderLoadingSkeleton", "renderEmptySlate",
                     "renderCaptureUnavailable", "mapBetCheckPayloadToStanding"):
            self.assertNotRegex(text, rf"\bfunction\s+{name}\s*\(",
                                 f"today.js must not redefine {name} -- it owns exactly one definition")

    def test_render_featured_bet_still_defined_only_in_featuredbet_js(self):
        matches = []
        for path in sorted(WEB_JS.glob("*.js")):
            text = _read(path)
            if re.search(r"\bfunction\s+renderFeaturedBet\s*\(", text):
                matches.append(path.name)
        self.assertEqual(matches, ["featuredbet.js"])


class VerdictStatesAndFeatureSelection(unittest.TestCase):
    def test_three_verdict_state_hero_builders_exist(self):
        text = _read(TODAY_PATH)
        for name in ("heroNoPlay", "heroFlagged", "heroMarketUnavailable"):
            self.assertRegex(text, rf"\bfunction {name}\s*\(", name)

    def test_gap_candidate_checks_both_sides_never_one_favourite(self):
        # V2-33's own rule ("largest price gap against consensus") must
        # not collapse into "always check the away side" -- both sides
        # are considered for every game.
        text = _read(TODAY_PATH)
        self.assertIn('["away", "home"]', text)

    def test_betcheck_price_is_the_real_best_price_never_a_literal(self):
        text = _read(TODAY_PATH)
        self.assertIn("american_price: best.price", text)
        # No hardcoded American price literal anywhere near the POST body.
        self.assertNotRegex(text, r"american_price:\s*-?\d")

    def test_featured_bet_verdict_is_never_defaulted_to_no_play(self):
        text = _read(TODAY_PATH)
        self.assertNotRegex(text, r"verdict\s*\|\|\s*[\"']no_play[\"']")

    def test_market_unavailable_hero_reads_the_real_gap_reason(self):
        text = _read(TODAY_PATH)
        self.assertIn("row.data_quality && row.data_quality.gaps", text)
        self.assertIn("gaps.market", text)
        # And never claims a live consensus_unavailable_reason field that
        # this row's shape does not actually carry.
        self.assertNotIn("row.consensus_unavailable_reason", text)


def _strip_js_comments(text: str) -> str:
    """Remove /* block */ and // line comments so a vocabulary scan checks
    what actually reaches the DOM, not engineering commentary that cites
    the very numbers it forbids being RENDERED (e.g. this file's own
    module docstring explains why 93.0%/2.3%/4.7% are never printed --
    that explanation necessarily names them)."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", " ", text)
    return text


class NeverFabricateGuards(unittest.TestCase):
    def test_no_hardcoded_forward_ledger_percentage(self):
        # 93.0% / 2.3% / 4.7% are measured from evidence/forward_ledger.jsonl
        # (n=129) with no customer endpoint -- must never be hardcoded as
        # if it were live, i.e. never appear outside a comment. (The
        # "27 hypotheses" line IS a fixed, closed research-record constant
        # and is explicitly allowed -- see the next test.)
        code = _strip_js_comments(_read(TODAY_PATH))
        for banned in ("93.0%", "93%", "2.3%", "4.7%"):
            self.assertNotIn(banned, code, f"hardcoded ledger frequency {banned!r} found in live code")

    def test_the_27_hypotheses_line_is_framed_as_a_static_constant(self):
        text = _read(TODAY_PATH)
        self.assertIn("27 hypotheses", text)
        self.assertIn("Static constant, not tonight's count", text)

    def test_empty_slate_never_conflated_with_a_fetch_failure(self):
        # `(slate && slate.games) || []` alone would render "no games
        # tonight" on a network failure indistinguishably from an honest
        # empty slate -- today.js must branch on the fetch itself first.
        text = _read(TODAY_PATH)
        self.assertIn("if (!slate)", text)

    def test_no_win_probability_or_rating_language(self):
        text = _read(TODAY_PATH)
        for token in ("win_probability", "winProbability", "modelProbability", "true_probability"):
            self.assertNotIn(token, text)


class NoBannedVocabulary(unittest.TestCase):
    def test_no_hard_banned_or_unnegated_phrases_in_today_js(self):
        text = _read(TODAY_PATH)
        violations = []
        for pattern, label in HARD_BANNED:
            if re.search(pattern, text, re.IGNORECASE):
                violations.append(f"today.js: hard-banned {label!r}")
        for pattern, label in NEGATION_ONLY:
            for m in re.finditer(pattern, text, re.IGNORECASE):
                window = text[max(0, m.start() - 90):m.start()]
                if not NEGATORS.search(window):
                    violations.append(f"today.js: {label!r} affirmed (no negation nearby)")
        self.assertEqual(violations, [], "\n".join(violations))


class ScreensCssSection(unittest.TestCase):
    def test_gameday_v2_section_present(self):
        text = _read(SCREENS_CSS_PATH)
        self.assertIn("GAMEDAY V2", text)

    def test_gameday_v2_has_a_mobile_reflow_block(self):
        text = _read(SCREENS_CSS_PATH)
        idx = text.index("GAMEDAY V2")
        tail = text[idx:]
        self.assertIn("@media (max-width: 899px)", tail)
        self.assertIn(".gv2-", tail)


if __name__ == "__main__":
    unittest.main()
