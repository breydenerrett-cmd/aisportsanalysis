"""Structural checks for LINEHOUND V2 Wave 1's Bet Check screen
(web/js/betcheck.js) -- artboards V2-04 (desktop ten-block skeleton),
V2-24 (mobile), V2-25 (blocks 05/06/08/09's usual NOT YET AVAILABLE
render), V2-26 (free checks used up / 402) and V2-32 (the Featured Bet
hero as block 01) -- design/linehound-v2/IMPLEMENTATION_PLAN.md's Wave 1,
Group Bet Check.

A plain-text scan, like tests/test_web_structure.py and
tests/test_web_v2_primitives.py -- it never starts a server and never
imports a JS engine. tests/test_web_structure.py's BetCheckSkeletonOrder
already pins the five mandated data-hook markers in order; this file adds
the checks specific to this lane's boundary:

  - block 01 states the bet in words and no longer mounts the shared
    Featured Bet tile -- that tile is the price-comparison register the
    owner retired on 2026-09-10 (see tests/test_web_betcheck_register.py);
    it still never guesses a verdict or price standing;
  - the ten-block skeleton keeps SIMILAR BETS / YOUR HISTORY as
    permanently NOT YET AVAILABLE (no field anywhere backs either);
  - the free-check meter and the 402 wall read the server's own
    remaining/limit counters, never a hardcoded count;
  - main.js's only import from this file (`renderBetCheck`) still exists,
    so this rewrite has not silently changed the routing contract;
  - no banned customer-facing vocabulary, reusing tests/test_customer_language's
    own lists.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.test_customer_language import HARD_BANNED, NEGATION_ONLY, NEGATORS

ROOT = Path(__file__).resolve().parent.parent
WEB_JS = ROOT / "web" / "js"
BETCHECK_PATH = WEB_JS / "betcheck.js"
MAIN_PATH = WEB_JS / "main.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class BlockOneIsThePlainBet(unittest.TestCase):
    """Block 01 states the bet in words. It no longer mounts featuredbet.js.

    V2-32 had it mount the shared Featured Bet tile, and this class used to
    enforce that. The tile is five rows of price comparison -- PRICE
    STANDING, BEATS CONSENSUS, IMPROVEMENT, BOARD DEPTH, "N BOOKS COMPARED"
    -- which the owner retired on 2026-09-10 ("that has to stop. None of
    that's important."). tests/test_web_betcheck_register.py owns the
    full ban; this keeps the V2 contract that block 01 never GUESSES.
    """

    def setUp(self):
        self.text = _read(BETCHECK_PATH)

    def test_does_not_mount_the_price_tile(self):
        self.assertNotIn('from "./featuredbet.js"', self.text)
        self.assertNotIn("renderFeaturedBet", self.text)

    def test_never_guesses_a_verdict_or_price_standing(self):
        # Still true, and now trivially: there is no tile to hand them to.
        self.assertNotRegex(self.text, r"verdict\s*:\s*[\"']\w+[\"']")
        self.assertNotRegex(self.text, r"priceStanding\s*:\s*\{")

    def test_the_bet_sentence_reads_off_real_fields_only(self):
        body = self.text.split("function renderTheBet(")[1].split("\nfunction ")[0]
        self.assertIn("result.query", body)
        self.assertIn("result.game", body)
        self.assertIn("teamName(", body)


class TenBlockSkeletonV2(unittest.TestCase):
    """The V2 skeleton's own shape -- ten numbered blocks, two of which
    (08 SIMILAR BETS, 09 YOUR HISTORY) have no backing field anywhere and
    must never be computed or hidden."""

    def setUp(self):
        self.text = _read(BETCHECK_PATH)

    def test_ten_blocks_present_in_order(self):
        # 02 was THE MARKET until 2026-09-12 -- a your-price / fair-price /
        # best-available section with a YES/NO line under it. Now THE
        # NUMBERS: how likely, then what the price needs, no verdict.
        titles = ["THE BET", "THE NUMBERS", "THE CASE", "COUNTERARGUMENT",
                  "WHAT CHANGED", "HISTORICAL SUPPORT", "EVIDENCE STATUS",
                  "SIMILAR BETS", "YOUR HISTORY", "BOTTOM LINE"]
        positions = []
        for title in titles:
            needle = f'"{title}"'
            index = self.text.find(needle)
            self.assertGreaterEqual(index, 0, f"missing block title {title!r}")
            positions.append(index)
        # Definition order need not match visual order (function
        # declarations are hoisted) -- what matters is that renderResult's
        # own assembly calls land in the true 01->10 order. Checked instead
        # via the render* call sequence, not string position, since block
        # 02 (THE MARKET) is deliberately defined later in the file (see
        # betcheck.js's own comment) to satisfy the mandated data-hook
        # order tests/test_web_structure.py pins.
        assembly = self.text.split("function renderResult(")[1].split("\nfunction ")[0]
        call_order = [m.group(1) for m in re.finditer(r"render(\w+)\(", assembly)]
        # The ten render calls, in the order they must be appended.
        expected_calls = ["TheBet", "Numbers", "Case", "Counterargument",
                           "WhatChanged", "Historical", "EvidenceStatus",
                           "SimilarBets", "YourHistory", "BottomLine"]
        filtered = [c for c in call_order if c in expected_calls]
        self.assertEqual(filtered, expected_calls,
                          "blocks are not assembled 01->10 in renderResult")

    def test_similar_bets_and_your_history_always_not_yet_available(self):
        # Both functions take no `result` argument at all -- there is no
        # field anywhere in the contract either could read, so neither
        # may be conditioned on the payload.
        self.assertRegex(self.text, r"function renderSimilarBets\s*\(\s*\)\s*\{")
        self.assertRegex(self.text, r"function renderYourHistory\s*\(\s*\)\s*\{")

    def test_strongest_weakest_reason_fields_not_read_as_dedicated_blocks(self):
        # V2-04/24/25/32's skeleton replaces V1's STRONGEST/WEAKEST blocks
        # with WHAT CHANGED / HISTORICAL SUPPORT at 05/06 -- a deliberate,
        # flagged deviation documented in this file's own module docstring
        # (which legitimately names both fields in prose). What must NOT
        # exist is a live field READ off the response object for either.
        self.assertNotIn("result.strongest_reason", self.text)
        self.assertNotIn("result.weakest_reason", self.text)


class FreeCheckMeterReadsRealCounters(unittest.TestCase):
    """The 'N of 3 left' meter and the 402 wall must reflect the real
    entitlement fields, never a hardcoded count (this lane's HARD RULES)."""

    def setUp(self):
        self.text = _read(BETCHECK_PATH)

    def test_meter_reads_remaining_and_limit_from_the_response(self):
        self.assertIn("freeCheck.remaining", self.text)
        self.assertIn("freeCheck.limit", self.text)

    def test_no_hardcoded_three_of_three_before_a_real_count_exists(self):
        # Before any check has been made, no per-visitor count is knowable
        # (the server has not minted an identity yet) -- the pre-first-
        # check state must not print a specific N/3 figure.
        self.assertNotRegex(self.text, r"[\"']3 OF 3")
        self.assertNotRegex(self.text, r"[\"']0 OF 3")
        self.assertNotRegex(self.text, r"[\"']1 OF 3")
        self.assertNotRegex(self.text, r"[\"']2 OF 3")

    def test_exhaustion_wall_reads_detail_remaining_and_limit(self):
        self.assertIn("renderExhausted", self.text)
        exhausted_body = self.text.split("function renderExhausted(")[1].split("\nfunction ")[0]
        self.assertIn("detail.remaining", exhausted_body)
        self.assertIn("detail.limit", exhausted_body)

    def test_meter_bar_fill_represents_remaining_not_a_fabricated_ratio(self):
        # meterBar(remaining, limit) draws exactly `remaining` filled
        # segments out of `limit` -- both server-supplied, never derived
        # from a client-side guess.
        self.assertRegex(self.text, r"function meterBar\(remaining,\s*limit\)")


class RoutingContractUnchanged(unittest.TestCase):
    """main.js is out of this lane's ownership -- confirm the one export
    it imports still exists, and that this file exports nothing main.js
    does not already expect."""

    def test_main_js_still_imports_renderBetCheck_only(self):
        main_text = _read(MAIN_PATH)
        self.assertRegex(main_text, r'import\s*\{\s*renderBetCheck\s*\}\s*from\s*"\./betcheck\.js"')

    def test_renderBetCheck_is_exported(self):
        text = _read(BETCHECK_PATH)
        self.assertRegex(text, r"\bexport async function renderBetCheck\s*\(")


class NoBannedVocabulary(unittest.TestCase):
    """Reuses tests/test_customer_language's own banned-phrase lists,
    applied here explicitly to betcheck.js -- independent of
    tests/test_web_structure.py's web-wide (HARD_BANNED-only) sweep, this
    also checks the stricter NEGATION_ONLY list (e.g. "edge" as a customer
    noun), matching the standard tests/test_web_v2_primitives.py already
    set for the Wave 0 primitives this file wires in."""

    def test_no_hard_banned_or_unnegated_phrases(self):
        text = _read(BETCHECK_PATH)
        violations = []
        for pattern, label in HARD_BANNED:
            if re.search(pattern, text, re.IGNORECASE):
                violations.append(f"hard-banned {label!r}")
        for pattern, label in NEGATION_ONLY:
            for m in re.finditer(pattern, text, re.IGNORECASE):
                window = text[max(0, m.start() - 90):m.start()]
                if not NEGATORS.search(window):
                    violations.append(f"{label!r} affirmed (no negation nearby)")
        self.assertEqual(violations, [], "\n".join(violations))

    def test_never_calls_price_improvement_ev_or_edge(self):
        text = _read(BETCHECK_PATH)
        self.assertNotRegex(text, r"\bEV\b")

    def test_late_move_never_called_clv(self):
        text = _read(BETCHECK_PATH)
        self.assertNotIn("CLV", text)


if __name__ == "__main__":
    unittest.main()
