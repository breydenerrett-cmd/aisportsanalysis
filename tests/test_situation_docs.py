"""The docs say what the code does: the prompt sections, the switch, the files, the costs, the result.

`tests/test_analyst_docs.py` pins that docs/AI_ANALYST.md holds arm A's prompt. This pins the same for
arm B's added section in docs/SITUATION_LAYER.md, and that the pages name the switch and the files.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from src import paths
from src.analyst import analyst, situation_arm, situation_prompt, ufc_analyst

ROOT = Path(paths.repo_root())
LAYER = (ROOT / "docs" / "SITUATION_LAYER.md").read_text(encoding="utf-8")
ANALYST = (ROOT / "docs" / "AI_ANALYST.md").read_text(encoding="utf-8")
ENABLE = (ROOT / "docs" / "decisions" / "AI_ANALYST_ENABLE.md").read_text(encoding="utf-8")
PLAN = (ROOT / "docs" / "SITUATION_LAYER_PLAN.md").read_text(encoding="utf-8")
NOTE = (ROOT / "docs" / "research" / "SITUATION_REST_VS_RHYTHM_DIVISION_SERIES.md").read_text(encoding="utf-8")


def flat(text: str) -> str:
    """The text with every run of whitespace one space: a sentence wrapped across two lines is the same sentence."""
    return re.sub(r"\s+", " ", text)


LAYER_FLAT, ANALYST_FLAT, ENABLE_FLAT, NOTE_FLAT = flat(LAYER), flat(ANALYST), flat(ENABLE), flat(NOTE)


class ThePromptIsThePromptInTheCode(unittest.TestCase):
    def test_the_mlb_situation_section_is_verbatim_in_the_doc(self):
        self.assertIn(situation_prompt.MLB_SITUATION_SECTION, LAYER)

    def test_the_ufc_situation_section_is_verbatim_in_the_doc(self):
        self.assertIn(situation_prompt.UFC_SITUATION_SECTION, LAYER)

    def test_the_prompts_in_the_code_are_those_sections_added_to_arm_as(self):
        self.assertTrue(analyst.SITUATION_SYSTEM_PROMPT.startswith(analyst.SYSTEM_PROMPT[: -len(situation_prompt.CLOSING_LINE)]))
        self.assertIn(situation_prompt.MLB_SITUATION_SECTION, analyst.SITUATION_SYSTEM_PROMPT)
        self.assertIn(situation_prompt.UFC_SITUATION_SECTION, ufc_analyst.UFC_SITUATION_SYSTEM_PROMPT)

    def test_arm_as_prompts_are_still_verbatim_in_the_analyst_doc(self):
        self.assertIn(analyst.SYSTEM_PROMPT, ANALYST)
        self.assertIn(ufc_analyst.UFC_SYSTEM_PROMPT, ANALYST)


class TheSwitchAndTheFilesAreNamed(unittest.TestCase):
    def test_the_layer_doc_names_the_switch_and_both_arms_files(self):
        self.assertIn('"situation_arm": {"enabled": true}', LAYER)
        for rel in (situation_arm.MLB_B_STORE, situation_arm.UFC_B_STORE):
            self.assertIn(rel.replace("\\", "/"), LAYER)
        self.assertIn("analyst compare", LAYER)
        self.assertIn("--arm both", LAYER + ENABLE)

    def test_the_shipped_config_has_the_switch_off(self):
        cfg = json.loads((ROOT / "config" / "analyst.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["situation_arm"], {"enabled": False})

    def test_the_enable_page_and_the_analyst_doc_state_the_cost_and_say_it_is_off(self):
        for text in (ENABLE_FLAT, ANALYST_FLAT):
            self.assertIn("arm B", text)
            self.assertRegex(text, r"(?i)roughly doubles")
        self.assertIn("$0.17 to $0.24", ANALYST_FLAT)
        self.assertIn("$0.17 to $0.24", LAYER_FLAT)
        self.assertIn("It is off.", ANALYST_FLAT)

    def test_the_cost_the_doc_states_is_consistent_with_the_arm_a_estimate_it_builds_on(self):
        # the analyst doc's own per-game estimate for arm A is $0.08 to $0.11; both arms are about twice that
        self.assertIn("about $0.08 to $0.11", ANALYST_FLAT)
        self.assertIn("$0.08 to $0.11", LAYER_FLAT)

    def test_the_doc_states_the_thirty_call_rule_and_the_paired_games_rule(self):
        self.assertIn("30 graded calls per family", LAYER_FLAT)
        self.assertRegex(LAYER_FLAT, r"Only games both arms froze are compared")


class ThePlanAndTheNoteAgreeWithTheRun(unittest.TestCase):
    def test_the_plan_status_table_says_what_was_built(self):
        for piece in ("MLB and UFC situation records", "Side-by-side analysts", "Rest vs rhythm test"):
            row = next(ln for ln in PLAN.splitlines() if piece in ln)
            self.assertNotIn("building", row, row)

    def test_the_note_was_frozen_before_it_was_run_and_says_so(self):
        self.assertIn("PRE-REGISTRATION, written and committed before any Game 1 result", NOTE)
        self.assertIn("## 9. Result", NOTE)
        self.assertNotIn("(Added after the run. Everything above", NOTE.split("## 9. Result")[0])

    def test_the_note_reports_a_null_as_a_null_with_its_numbers(self):
        result = NOTE.split("## 9. Result")[1]
        self.assertIn("**A null result.**", result)
        for fragment in ("19 of 28", "15 of 28", "0.41", "0.52", "about 18 points"):
            self.assertIn(fragment, result)

    def test_the_note_and_the_layer_doc_agree_on_the_sample_and_the_price(self):
        for text in (NOTE_FLAT, LAYER_FLAT):
            self.assertIn("28", text)
            self.assertRegex(text, r"2026 only|for 2026 only")
        self.assertRegex(NOTE_FLAT, r"every Price cell reads \"none\"")

    def test_the_sample_table_in_the_note_adds_up(self):
        rows = re.findall(r"^\| (20\d\d) \| (\d) \| (\d) \| (\d) \| (\d) \|$", NOTE, re.M)
        self.assertEqual(len(rows), 11)
        self.assertEqual(sum(int(r[1]) for r in rows), 44)
        self.assertEqual(sum(int(r[2]) for r in rows), 28)
        self.assertEqual(sum(int(r[3]) for r in rows), 12)
        self.assertEqual(sum(int(r[4]) for r in rows), 4)
        for r in rows:
            self.assertEqual(int(r[1]), int(r[2]) + int(r[3]) + int(r[4]), r)


if __name__ == "__main__":
    unittest.main()
