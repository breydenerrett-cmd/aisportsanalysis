"""The UFC section of docs/AI_ANALYST.md says what the code does.

The prompt in the doc is the prompt in the code, the grading rules are the grader's, the slots are
the packet's, and the cost section calls its numbers estimates. The house-style tests of
tests/test_analyst_docs.py already run over the whole file, this section included.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from src.analyst import ufc_analyst as U
from src.analyst import ufc_grading as G
from src.analyst import ufc_ledger as L
from src.analyst import ufc_packet as P

ROOT = Path(__file__).resolve().parent.parent
DOC = (ROOT / "docs" / "AI_ANALYST.md").read_text(encoding="utf-8")
UFC = DOC[DOC.index("## The UFC analyst"):]
LABEL = "Written by an AI model from the data on this page. Unproven. Analysis, not advice."


class TheDocQuotesTheCode(unittest.TestCase):
    def test_the_ufc_section_exists_and_the_top_of_the_file_points_to_it(self):
        self.assertTrue(UFC.startswith("## The UFC analyst"))
        self.assertIn('UFC has its own at the end of this file,\n"The UFC analyst"', DOC[:1800])

    def test_the_prompt_in_the_doc_is_the_prompt_in_the_code(self):
        self.assertIn(U.UFC_SYSTEM_PROMPT, UFC)
        self.assertIn(U.UFC_PROMPT_VERSION, UFC)

    def test_the_prompt_is_in_the_ufc_section_and_the_mlb_prompt_is_not_repeated_there(self):
        from src.analyst import analyst as A
        self.assertNotIn(A.SYSTEM_PROMPT, UFC)
        self.assertIn(A.SYSTEM_PROMPT, DOC)

    def test_the_label_is_stated(self):
        self.assertIn(LABEL, UFC)

    def test_every_slot_the_packet_can_have_is_in_the_slot_table(self):
        for slot in ("`moneyline`", "`rounds_total`", "`method_a_ko`", "`method_b_ko`", "`method_a_sub`",
                     "`method_b_sub`", "`method_a_dec`", "`method_b_dec`"):
            self.assertIn(slot, UFC)
        self.assertEqual(P.method_slot_id("a", "ko_tko_dq"), "method_a_ko")
        self.assertEqual(P.method_slot_id("b", "decision"), "method_b_dec")

    def test_the_grading_rules_in_the_doc_are_the_graders(self):
        for family in G.FAMILIES:
            self.assertIn(f"`{family}`", UFC)
        self.assertIn("exactly on the line", UFC)
        self.assertIn("PUSH", UFC)
        self.assertIn("(`end_round` - 1) x 300 + `end_time_s`", UFC)
        self.assertEqual(G.ROUND_SECONDS, 300.0)
        for raw in ("KO_TKO", "DQ", "SUB", "DEC_UNANIMOUS", "DEC_SPLIT", "DEC_MAJORITY", "DECISION"):
            self.assertIn(f"`{raw}`", UFC)
            self.assertIn(raw, G.METHOD_OF_RESULT)
        self.assertIn("tko---doctors-stoppage", UFC)
        self.assertEqual(G.OTHER_TKO_PREFIX, "tko")
        self.assertIn("draw, no contest", UFC)
        self.assertIn("VOID in every family", UFC)

    def test_the_half_round_rule_is_documented_as_unchecked_against_a_book(self):
        self.assertIn("It was not checked against any one book's published rule", UFC)

    def test_the_files_it_names_are_the_ledgers(self):
        for name in (L.STORE, L.USAGE_STORE, L.PACKET_DIR):
            self.assertIn(name.replace("\\", "/"), UFC)

    def test_the_small_sample_rule_is_stated(self):
        self.assertIn("**30 graded calls**", UFC)

    def test_the_mount_snippet_names_the_real_exports(self):
        text = (ROOT / "web" / "js" / "analyst_ufc.js").read_text(encoding="utf-8")
        for name in ("fetchUfcAnalyst", "renderUfcAnalystEvent", "renderUfcAnalystRecord", "mountUfcAnalystRecord"):
            self.assertIn(f"export function {name}" if name != "fetchUfcAnalyst" and name != "mountUfcAnalystRecord"
                          else f"export async function {name}", text)
            self.assertIn(name, UFC)

    def test_the_commands_in_the_doc_parse(self):
        from src import cli as top
        lines = re.findall(r"^python -m src\.cli (analyst .+?)(?:\s+#.*)?$", UFC, re.M)
        self.assertEqual(len(lines), 5)                       # a scan that matches nothing proves nothing
        for line in lines:
            args = top.build_parser().parse_args(line.split())
            self.assertEqual(args.sport, "ufc", line)


class TheCostSectionIsHonest(unittest.TestCase):
    def test_costs_are_called_estimates_until_measured(self):
        self.assertIn("estimate until the first measured day", UFC)

    def test_the_prices_are_the_configs(self):
        from src.analyst import config
        cfg = config.load()
        self.assertIn(f"${cfg['price_per_million_usd']['input']:.2f} per million input", UFC)
        self.assertIn(f"${cfg['price_per_million_usd']['output']:.2f} per million output", UFC)
        self.assertIn(f"${cfg['spend_cap']['max_usd_per_run']:.2f}", UFC)
        self.assertIn(f"{cfg['spend_cap']['max_tokens_per_run']:,}", UFC)

    def test_the_worst_case_per_bout_is_the_caps_reservation(self):
        from src.analyst import config
        cfg = config.load()
        price = cfg["price_per_million_usd"]
        worst = (10_000 * price["input"] + cfg["max_output_tokens"] * price["output"]) / 1e6
        self.assertAlmostEqual(worst, 0.18, places=2)
        self.assertIn("is $0.18", UFC)

    def test_the_measured_packet_sizes_are_labelled_as_measured_and_dated(self):
        self.assertIn("measured by the dry run above", UFC)
        self.assertIn("2026-10-03", UFC)

    def test_it_says_it_is_the_same_key_and_the_same_cap_as_mlb(self):
        self.assertIn("same `ANTHROPIC_API_KEY` as the MLB analyst", UFC)
        self.assertIn("The hard cap is the MLB one", UFC)


class WhatItDoesNotClaim(unittest.TestCase):
    def test_it_says_what_it_does_not_claim(self):
        self.assertIn("### 8. What it does not claim", UFC)
        self.assertIn("A page view never calls the model", UFC)
        self.assertIn("That the card is affected", UFC)
        self.assertIn("places nothing", UFC)

    def test_it_names_the_data_it_does_not_have(self):
        for word in ("injuries", "weight cuts", "short-notice replacements"):
            self.assertIn(word, UFC)

    def test_house_style_holds_in_the_ufc_section(self):
        self.assertNotIn("—", UFC)
        self.assertNotRegex(UFC, r"(?i)bet[\s-]*check")
        for match in re.finditer(r"(?i)\bprofit\w*|\bedge\b|\bguarantee\w*|\bfree money\b", UFC):
            window = UFC[max(0, match.start() - 80):match.end() + 40].lower()
            self.assertRegex(window, r"\b(no|not|never|nor|without|cannot|any)\b|never says|banned|strikes",
                             msg=f"{match.group(0)!r} near {window!r}")


if __name__ == "__main__":
    unittest.main()
