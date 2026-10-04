"""The analyst's docs say what the code does, and the enable patch is one line."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from src.analyst import analyst as A

ROOT = Path(__file__).resolve().parent.parent
DOC = (ROOT / "docs" / "AI_ANALYST.md").read_text(encoding="utf-8")
ENABLE = (ROOT / "docs" / "decisions" / "AI_ANALYST_ENABLE.md").read_text(encoding="utf-8")
PATCH = (ROOT / "docs" / "decisions" / "ai-analyst-key.patch").read_text(encoding="utf-8")
LABEL = "Written by an AI model from the data on this page. Unproven. Analysis, not advice."


class TheDocQuotesTheCode(unittest.TestCase):
    def test_the_prompt_in_the_doc_is_the_prompt_in_the_code(self):
        self.assertIn(A.SYSTEM_PROMPT, DOC)
        self.assertIn(A.CRITIC_SYSTEM_PROMPT, DOC)
        self.assertIn(A.PROMPT_VERSION, DOC)

    def test_the_schema_in_the_doc_is_the_schema_in_the_code(self):
        self.assertIn(json.dumps(A.MLB_RESPONSE_SCHEMA, indent=2), DOC)

    def test_the_cost_numbers_in_the_doc_are_the_configs(self):
        from src.analyst import config
        cfg = config.load()
        self.assertIn(f"${cfg['price_per_million_usd']['input']:.2f} per million input", DOC)
        self.assertIn(f"${cfg['price_per_million_usd']['output']:.2f} per million output", DOC)
        self.assertIn(f"${cfg['spend_cap']['max_usd_per_run']:.2f}", DOC)
        self.assertIn(f"{cfg['spend_cap']['max_tokens_per_run']:,}", ENABLE)

    def test_costs_are_called_estimates_until_measured(self):
        self.assertIn("estimate until the first measured day", DOC)
        self.assertIn("estimates until the first measured day", ENABLE.lower())

    def test_the_label_is_stated(self):
        self.assertIn(LABEL, DOC)


class HouseStyle(unittest.TestCase):
    def test_no_em_dashes_and_no_banned_names(self):
        for name, text in (("AI_ANALYST.md", DOC), ("AI_ANALYST_ENABLE.md", ENABLE)):
            self.assertNotIn("—", text, name)
            self.assertNotRegex(text, r"(?i)bet[\s-]*check", name)

    def test_the_only_profit_words_are_denials(self):
        for match in re.finditer(r"(?i)\bprofit\w*|\bedge\b|\bguarantee\w*|\bfree money\b", DOC + ENABLE):
            window = (DOC + ENABLE)[max(0, match.start() - 80):match.end() + 40].lower()
            self.assertRegex(window, r"\b(no|not|never|nor|without|cannot|any)\b|never says|banned|strikes",
                             msg=f"{match.group(0)!r} near {window!r}")

    def test_it_says_what_it_does_not_claim(self):
        self.assertIn("## What it does not claim", DOC)
        self.assertIn("a page view never calls the model", DOC)


class TheEnablePatch(unittest.TestCase):
    def test_it_adds_exactly_one_line_to_the_daily_loop_workflow(self):
        added = [l for l in PATCH.splitlines() if l.startswith("+") and not l.startswith("+++")]
        removed = [l for l in PATCH.splitlines() if l.startswith("-") and not l.startswith("---")]
        self.assertEqual(len(added), 1)
        self.assertEqual(removed, [])
        self.assertIn("ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}", added[0])
        self.assertEqual(re.findall(r"^\+\+\+ b/(.+)$", PATCH, re.M), [".github/workflows/daily-loop.yml"])

    def test_the_secret_is_named_never_valued(self):
        self.assertNotRegex(DOC + ENABLE + PATCH, r"sk-ant-[A-Za-z0-9_-]{8,}")
        self.assertIn("`ANTHROPIC_API_KEY`", ENABLE)

    def test_the_steps_cover_key_secret_line_cost_and_off(self):
        for heading in ("### 1. Create the key", "### 2. Add the repository secret",
                        "### 3. Apply the one workflow line", "## Expected cost", "## Turning it off"):
            self.assertIn(heading, ENABLE)


if __name__ == "__main__":
    unittest.main()
