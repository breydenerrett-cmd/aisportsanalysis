"""web/js/performance.js: Live research record panel.

Structural tests for the live research record panel added to
performance.js. This is a plain-text scan, no server, no JS engine.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.test_customer_language import HARD_BANNED, NEGATION_ONLY, NEGATORS

ROOT = Path(__file__).resolve().parent.parent
PERFORMANCE_PATH = ROOT / "web" / "js" / "performance.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class LivePanelStructure(unittest.TestCase):
    """Test the live research record panel structure."""

    def setUp(self):
        self.text = _read(PERFORMANCE_PATH)

    def test_live_panel_function_exists(self):
        """renderLiveResearchRecord function must be defined."""
        self.assertIn("function renderLiveResearchRecord(", self.text)

    def test_live_performance_fetched_in_main_render(self):
        """renderPerformance must fetch /performance/live and render the panel."""
        # The live panel is mounted inside renderPerformance, not as a separate export
        render_at = self.text.find("export async function renderPerformance(")
        self.assertNotEqual(-1, render_at, "renderPerformance is gone")
        render_body = self.text[render_at:]
        # renderPerformance should call renderLiveResearchRecord via apiGet
        self.assertIn('apiGet("/performance/live', render_body)

    def test_panel_fetches_live_endpoint(self):
        """Panel must fetch /performance/live endpoint."""
        self.assertIn('apiGet("/performance/live', self.text)

    def test_panel_contains_live_research_record_heading(self):
        """Panel must have 'Live research record' heading text."""
        self.assertIn("Live research record", self.text)

    def test_notice_sentence_is_present(self):
        """Panel must contain the exact notice sentence."""
        self.assertIn(
            "Live analysis is in internal testing. No alerts are sent.",
            self.text)

    def test_empty_state_message_present(self):
        """Panel must have the correct empty state message."""
        self.assertIn(
            "No live research candidates have settled yet.",
            self.text)

    def test_says_candidates_not_picks(self):
        """Panel must say 'research candidates', never 'picks'."""
        # Find the live panel function
        fn_start = self.text.find("function renderLiveResearchRecord(")
        self.assertNotEqual(-1, fn_start, "renderLiveResearchRecord not found")

        # Find the next function to bound the body
        fn_end = self.text.find("\nfunction ", fn_start + 1)
        if fn_end == -1:
            fn_end = self.text.find("\nexport ", fn_start + 1)
        if fn_end == -1:
            fn_end = len(self.text)

        fn_body = self.text[fn_start:fn_end]

        # Check that "candidates" appears in the function
        self.assertIn("candidates", fn_body,
                      "renderLiveResearchRecord never mentions 'candidates'")

        # Check that we don't call it a "record of picks"
        self.assertNotIn("record of picks", fn_body.lower(),
                         "panel incorrectly calls it a 'record of picks'")


class LivePanelLanguage(unittest.TestCase):
    """Test that the live panel has no banned vocabulary."""

    def setUp(self):
        # Extract just the live panel functions
        text = _read(PERFORMANCE_PATH)
        start = text.find("function renderLiveResearchRecord(")
        if start == -1:
            self.fn_body = ""
            return
        end = text.find("\nexport async function renderLivePerformance(", start)
        if end == -1:
            end = len(text)
        self.fn_body = text[start:end]

    def test_no_hard_banned_phrases(self):
        """Panel must not contain hard-banned phrases."""
        violations = []
        for pattern, label in HARD_BANNED:
            if re.search(pattern, self.fn_body, re.IGNORECASE):
                violations.append(f"hard-banned {label!r}")
        self.assertEqual(violations, [], f"Live panel has banned phrases: {violations}")

    def test_no_unnegated_negation_only_phrases(self):
        """Panel must not contain negation-only phrases without negation."""
        violations = []
        for pattern, label in NEGATION_ONLY:
            for m in re.finditer(pattern, self.fn_body, re.IGNORECASE):
                window = self.fn_body[max(0, m.start() - 90):m.start()]
                if not NEGATORS.search(window):
                    violations.append(f"{label!r} affirmed without negation")
        self.assertEqual(violations, [], f"Live panel language violations: {violations}")

    def test_no_bare_ev(self):
        """Panel must not contain bare EV."""
        self.assertNotRegex(self.fn_body, r"\bEV\b", "bare EV found")

    def test_no_clv(self):
        """Panel must not contain CLV."""
        self.assertNotIn("CLV", self.fn_body, "CLV found")


class LivePanelDataHooks(unittest.TestCase):
    """Test that the live panel has proper data-hook attributes for testing."""

    def setUp(self):
        self.text = _read(PERFORMANCE_PATH)

    def test_performance_live_record_hook_present(self):
        """Main panel must have data-hook='performance-live-record'."""
        self.assertIn('"data-hook": "performance-live-record"', self.text)

    def test_live_notice_hook_present(self):
        """Notice text must have data-hook='live-notice'."""
        self.assertIn('"data-hook": "live-notice"', self.text)


class LiveHistoryTable(unittest.TestCase):
    """Test the live history table structure."""

    def setUp(self):
        # Extract just the live panel function
        text = _read(PERFORMANCE_PATH)
        start = text.find("function renderLiveResearchRecord(")
        self.assertNotEqual(-1, start, "renderLiveResearchRecord not found")
        end = text.find("\nexport async function renderLivePerformance(", start)
        if end == -1:
            end = len(text)
        self.fn_body = text[start:end]

    def test_table_renders_rule_column(self):
        """History table must have RULE column."""
        self.assertIn('"RULE"', self.fn_body)

    def test_table_renders_bet_column(self):
        """History table must have BET column."""
        self.assertIn('"BET"', self.fn_body)

    def test_table_renders_price_column(self):
        """History table must have PRICE column."""
        self.assertIn('"PRICE"', self.fn_body)

    def test_table_renders_result_column(self):
        """History table must have RESULT column."""
        self.assertIn('"RESULT"', self.fn_body)

    def test_uses_outcome_chips_for_results(self):
        """Results must use the same chip styling as other outcome displays."""
        # Check that outcome tones money, outline, live, warn are used
        self.assertIn('"money"', self.fn_body)
        self.assertIn('"outline"', self.fn_body)
        self.assertIn('"live"', self.fn_body)
        self.assertIn('"warn"', self.fn_body)
        # Check that pv-chip class is used with template substitution
        self.assertIn('pv-chip pv-chip--${resultTone}', self.fn_body)


if __name__ == "__main__":
    unittest.main()
