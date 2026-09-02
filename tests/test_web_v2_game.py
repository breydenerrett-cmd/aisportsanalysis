"""Structural checks for LANE L21 -- LINEHOUND V2 Wave 1, Group Game:
web/js/games.js's rebuild of V2-03 (COVERAGE LEDGER), V2-13/14/15 (GAME
QUICK desktop/mobile/absent-states) and V2-31 (GAME ADVANCED mobile), plus
the V2-34 Game spotlight placement of web/js/featuredbet.js's shared
Featured Bet primitive.

Static text scan only -- like tests/test_web_structure.py and
tests/test_web_v2_primitives.py, this never starts a server and never
imports a JS engine. It checks:

  - main.js's two games.js imports (`renderGamesList`, `renderGameDetail`)
    are unchanged -- this lane must never touch main.js's routing;
  - games.js wires in the shared Featured Bet primitive (not a fork);
  - the 11-gap coverage ledger is rendered from the real payload's own
    `gaps`/`sections` keys, never a hardcoded (and stale, per
    RECONCILED_CONTRACT_CURRENT_HEAD.md) artboard gap-name list;
  - the V2-34 spotlight never invents a side/pick for the dominant
    no_play case;
  - screens.css carries the two mandated bannered sections, additive
    only;
  - no banned customer-facing vocabulary, reusing
    tests/test_customer_language's own lists.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.test_customer_language import HARD_BANNED, NEGATION_ONLY, NEGATORS

ROOT = Path(__file__).resolve().parent.parent
WEB_JS = ROOT / "web" / "js"
GAMES_PATH = WEB_JS / "games.js"
MAIN_PATH = WEB_JS / "main.js"
SCREENS_CSS_PATH = ROOT / "web" / "css" / "screens.css"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class RoutingUntouched(unittest.TestCase):
    """This lane owns games.js only -- main.js's routing must be unchanged
    (an "unavoidable routing change" would be reported, not made)."""

    def test_main_js_still_imports_the_two_exported_functions(self):
        main_text = _read(MAIN_PATH)
        self.assertIn('import { renderGamesList, renderGameDetail } from "./games.js";', main_text)

    def test_games_js_still_exports_both_functions(self):
        text = _read(GAMES_PATH)
        self.assertRegex(text, r"\bexport async function renderGamesList\s*\(")
        self.assertRegex(text, r"\bexport async function renderGameDetail\s*\(")


class FeaturedBetWiredNotForked(unittest.TestCase):
    def test_imports_the_shared_primitive(self):
        text = _read(GAMES_PATH)
        self.assertIn('import { renderFeaturedBet } from "./featuredbet.js";', text)
        self.assertIn("renderFeaturedBet(", text)

    def test_does_not_redefine_render_featured_bet(self):
        text = _read(GAMES_PATH)
        self.assertNotRegex(text, r"\bfunction\s+renderFeaturedBet\s*\(")

    def test_does_not_reuse_the_betcheck_mapper_for_a_different_payload_shape(self):
        # mapBetCheckPayloadToStanding expects POST /betcheck's response
        # shape (query/price_improvement/thesis_support/...) -- this
        # screen's own quick/advanced payload has none of those field
        # names, so games.js must build its own mapper (mapGameToStanding)
        # rather than call the wrong mapper for the payload it actually
        # has. games.js's docstring is allowed to NAME the other mapper
        # to explain why it is not used -- only an import or a call site
        # is actually forbidden.
        text = _read(GAMES_PATH)
        self.assertNotRegex(text, r"^\s*import\b.*mapBetCheckPayloadToStanding", re.MULTILINE)
        self.assertNotRegex(text, r"\bmapBetCheckPayloadToStanding\s*\(")
        self.assertIn("mapGameToStanding", text)
        self.assertRegex(text, r"\bfunction\s+mapGameToStanding\s*\(")


class SpotlightNeverInventsASide(unittest.TestCase):
    """V2-34's honesty-critical rule: quick.side names a real side only
    for the rare flagged verdict; the dominant no_play case must never
    get an arbitrary default side/team so the spotlight can fill its
    SIDE/LINE cells."""

    def test_side_is_read_from_the_payload_not_defaulted(self):
        text = _read(GAMES_PATH)
        self.assertIn('quick.side === "away" || quick.side === "home" ? quick.side : null', text)

    def test_no_default_side_fallback_to_away_or_home(self):
        text = _read(GAMES_PATH)
        self.assertNotRegex(text, r"side\s*\|\|\s*[\"']away[\"']")
        self.assertNotRegex(text, r"side\s*\|\|\s*[\"']home[\"']")

    def test_query_parsed_always_true_never_a_parse_failure_path(self):
        # This mapper never feeds featuredbet.js's "COULD NOT READ THIS
        # BET" fallback -- nobody typed anything on this screen for it to
        # fail to parse.
        text = _read(GAMES_PATH)
        self.assertIn("parsed: true,", text)


class SpotlightHeaderSurvivesNoSide(unittest.TestCase):
    """L23 fix: featuredbet.js's SIDE fallback is now null-safe (only
    reads s.game.home/away when s.query.side is literally "home"/"away"),
    so this mapper no longer needs to withhold `game` to keep the SIDE
    pill honest -- the matchup header should render for every game."""

    def test_game_is_no_longer_withheld_as_a_workaround(self):
        text = _read(GAMES_PATH)
        self.assertNotIn("game: side ?", text)
        self.assertNotIn("game: null", text)

    FEATUREDBET_PATH = WEB_JS / "featuredbet.js"

    def test_featuredbet_side_fallback_has_a_null_safe_branch(self):
        text = _read(self.FEATUREDBET_PATH)
        # Must not resolve to away for anything other than the literal
        # "home" -- the old bug's shape (a bare else with no explicit
        # "away" check).
        self.assertNotRegex(
            text,
            r's\.query\.side === "home" \? \(s\.game && s\.game\.home\) : \(s\.game && s\.game\.away\)',
        )
        self.assertIn('s.query.side === "away" ? (s.game && s.game.away)', text)


class CoverageLedgerIsDynamic(unittest.TestCase):
    """The artboard's own gap-name list (starter_stat_lines, xwoba, xfip,
    platoon_splits, team_news...) is stale versus the real API
    (RECONCILED_CONTRACT_CURRENT_HEAD.md PRIORITY ANSWER 2: 5 sections /
    11 gaps, different names) -- this file must never hardcode either
    list, only walk the payload's own keys."""

    STALE_ARTBOARD_GAP_NAMES = (
        "starter_stat_lines", "bullpen_usage", "platoon_splits",
        "pitch_mix", "velocity", "xwoba", "xfip", "team_news",
    )

    def test_never_hardcodes_the_stale_artboard_gap_names(self):
        text = _read(GAMES_PATH)
        for name in self.STALE_ARTBOARD_GAP_NAMES:
            self.assertNotIn(name, text, f"{name!r} is a stale artboard gap name, not a real API key")

    def test_gaps_and_sections_are_walked_from_the_payload(self):
        text = _read(GAMES_PATH)
        self.assertIn("Object.keys(gaps)", text)
        self.assertIn("Object.keys(sections)", text)

    def test_gap_reason_rendered_verbatim_from_the_payload(self):
        text = _read(GAMES_PATH)
        self.assertIn("text: String(gaps[key])", text)


class NoBetPlacementOrRankOrEdge(unittest.TestCase):
    def test_no_save_this_bet_affordance(self):
        # The artboard's own "SAVE THIS BET" control is out of scope --
        # Quick View has no stated side+price to save, and My Bets is a
        # different lane's file. A code comment is allowed to NAME the
        # omitted control to explain the decision; only rendering it as
        # actual button/link text (`text: "SAVE THIS BET"`) is forbidden.
        text = _read(GAMES_PATH)
        self.assertNotIn('text: "SAVE THIS BET"', text)

    def test_price_standing_never_computed_here(self):
        text = _read(GAMES_PATH)
        self.assertIn("priceStanding: null", text)

    def test_no_book_link_or_placement_affordance(self):
        text = _read(GAMES_PATH)
        for banned in ("sportsbook.com", "placeBet", "wager_id"):
            self.assertNotIn(banned, text)


class SharedPrimitivesUsedForStates(unittest.TestCase):
    def test_imports_shared_states_not_dom_directly_for_loading_and_error(self):
        text = _read(GAMES_PATH)
        self.assertIn('from "./states.js"', text)
        self.assertIn("renderLoadingSkeleton", text)


class ScreensCssBanneredSectionsAdditive(unittest.TestCase):
    def test_two_bannered_sections_present(self):
        css = _read(SCREENS_CSS_PATH)
        self.assertIn("/* =====================================================================\n   GAME QUICK V2", css)
        self.assertIn("/* =====================================================================\n   GAME ADVANCED V2", css)

    def test_v1_game_view_section_untouched_marker_still_present(self):
        # This lane must never edit the pre-existing V1 "GAME VIEW"
        # section (still read by web/js/betcheck.js and web/js/today.js's
        # shared gv-*/bc-* classes) -- its banner should still be there,
        # unchanged, alongside the two new ones.
        css = _read(SCREENS_CSS_PATH)
        self.assertIn("GAME VIEW -- Quick, with Advanced APPENDED beneath (never replacing)", css)

    def test_new_css_scoped_to_gqv_and_gav_prefixes_only(self):
        css = _read(SCREENS_CSS_PATH)
        quick_start = css.index("GAME QUICK V2")
        advanced_start = css.index("GAME ADVANCED V2")
        quick_block = css[quick_start:advanced_start]
        # A spot check that the new Quick block does not redefine any V1
        # "gv-" (old Game View) class -- it must use the new gqv- prefix.
        self.assertNotRegex(quick_block, r"\n\.gv-[a-z]")


class NoBannedCustomerVocabularyInThisFile(unittest.TestCase):
    """Reuses tests/test_customer_language's own lists rather than
    retyping them, per this task's own instruction."""

    def test_no_banned_language_in_games_js(self):
        text = _read(GAMES_PATH)
        violations = []
        for pattern, label in HARD_BANNED:
            if re.search(pattern, text, re.IGNORECASE):
                violations.append(label)
        for pattern, label in NEGATION_ONLY:
            for m in re.finditer(pattern, text, re.IGNORECASE):
                window = text[max(0, m.start() - 90):m.start()]
                if not NEGATORS.search(window):
                    violations.append(f"{label} (unnegated)")
        self.assertEqual(violations, [], "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
