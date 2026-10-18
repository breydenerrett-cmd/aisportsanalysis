"""The desk hounds' copy says what the code does, and the pre-registration is intact.

`config/desk_hounds.json` is generated from `src/hounds/desk/roles.py` and compared here, so the plain-English
`rule_text` a visitor reads cannot drift from the prompt a model was given; the numbers the rules quote are
checked against the code's constants; and the house style (no em dashes, no profit language except denials, no
"Bet Check") holds in every doc and prompt this family owns.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from src.hounds.desk import cli, ledger, publish, risk, roles, state

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config" / "desk_hounds.json").read_text(encoding="utf-8"))
PREREG_RAW = (ROOT / "docs" / "PREREG_DESK_HOUNDS.md").read_text(encoding="utf-8")
PREREG = re.sub(r"\s+", " ", PREREG_RAW)          # the file is wrapped; phrases are matched unwrapped
DOC = (ROOT / "docs" / "DESK_HOUNDS.md").read_text(encoding="utf-8")
RUNBOOK = (ROOT / "docs" / "BRIEF_RUNBOOK.md").read_text(encoding="utf-8")
SECTION_START = RUNBOOK.index("## Desk and persona hounds")
SECTION = RUNBOOK[SECTION_START:]

PERSONA_IDS = ["desk_sharp", "desk_square", "desk_fader", "desk_weather", "desk_grinder", "desk_historian"]


class TheConfigIsTheCode(unittest.TestCase):
    def test_the_config_is_what_roles_py_generates(self):
        self.assertEqual(CONFIG, roles.config_document())

    def test_the_config_check_command_agrees(self):
        lines: list = []
        self.assertEqual(cli.main(["config", "--check"], out=lines.append), 0, lines)

    def test_every_hound_has_the_fields_the_pre_registration_names(self):
        self.assertEqual(len(CONFIG["hounds"]), 7)
        for h in CONFIG["hounds"]:
            for key in ("id", "name", "tagline", "category", "style", "rule_text", "prompt_version", "prompt_hash"):
                self.assertTrue(h[key], (h["id"], key))
            self.assertIn(h["category"], ("ai-desk", "persona"))
            self.assertEqual(h["prompt_version"], roles.PROMPT_VERSION)
            self.assertRegex(h["prompt_hash"], r"^[0-9a-f]{64}$")
            self.assertEqual(h["who_decided"], "model")
        self.assertEqual([h["id"] for h in CONFIG["hounds"]], ["desk_ai"] + PERSONA_IDS)
        self.assertEqual(sum(1 for h in CONFIG["hounds"] if h["category"] == "persona"), 6)

    def test_a_prompt_change_changes_the_hash(self):
        role = roles.ROLES["persona_sharp"]
        changed = roles.Role(role.stage, role.kind, role.title, role.system + " ", role.needs, role.hound_id,
                             role.words)
        self.assertNotEqual(role.prompt_hash(), changed.prompt_hash())

    def test_the_hashes_in_the_config_are_the_roles_hashes(self):
        for h in CONFIG["hounds"]:
            self.assertEqual(h["prompt_hash"], roles.hound_prompt_hash(h["id"]))

    def test_rule_text_quotes_the_codes_numbers(self):
        by_id = {h["id"]: h["rule_text"] for h in CONFIG["hounds"]}
        for hid, text in by_id.items():
            self.assertIn("-200", text, hid)
            self.assertIn("paper only", text.lower(), hid)
            self.assertIn("unproven", text.lower(), hid)
        self.assertIn(f"at most two", by_id["desk_ai"])
        self.assertEqual(risk.MAX_TAKES, 2)
        self.assertIn(str(risk.GRINDER_SHORT_FAVOURITE), by_id["desk_grinder"])
        self.assertIn(f"{round(risk.GRINDER_MAX_GAP * 100)} percentage points", by_id["desk_grinder"])
        self.assertEqual(risk.TAKE_PRICE_FLOOR, -200)

    def test_the_persona_prompts_state_the_rules_code_enforces(self):
        system = {s: roles.ROLES[s].system for s in roles.PERSONA_STAGES}
        self.assertIn("-150 or shorter", system["persona_grinder"])
        self.assertIn("at most 5 percentage points", system["persona_grinder"])
        self.assertIn("break-even probability of the best quote must be below", system["persona_sharp"])
        self.assertIn("moneyline favourite", system["persona_square"])
        self.assertIn("Over on the game total", system["persona_square"])
        self.assertIn("game total and the team totals", system["persona_weather"])
        self.assertIn("side that gets points", system["persona_fader"])
        self.assertIn("head-to-head", system["persona_historian"])
        for stage, text in system.items():
            self.assertIn("-200 or worse", text, stage)
            self.assertIn("E. ", text, stage)

    def test_every_stage_tells_the_model_the_data_is_its_only_source(self):
        for stage, role in roles.ROLES.items():
            self.assertIn("THE DATA IS YOUR ONLY SOURCE", role.system, stage)
            self.assertIn("never \"the packet\"", role.system, stage)


class HouseStyle(unittest.TestCase):
    TEXTS = {"PREREG": PREREG, "DESK_HOUNDS": DOC, "RUNBOOK section": SECTION,
             "config": json.dumps(CONFIG, ensure_ascii=False)}

    def test_no_em_dashes_and_no_banned_names(self):
        texts = dict(self.TEXTS)
        texts.update({f"prompt {s}": r.system for s, r in roles.ROLES.items()})
        for name, text in texts.items():
            self.assertNotIn("—", text, name)
            self.assertNotRegex(text, r"(?i)bet[\s-]*check", name)

    def test_the_only_profit_words_are_denials(self):
        blob = "\n".join(self.TEXTS.values())
        for match in re.finditer(r"(?i)\bprofit\w*|\bedge\b|\bguarantee\w*|\bfree money\b|\+EV", blob):
            window = blob[max(0, match.start() - 90):match.end() + 50].lower()
            self.assertRegex(window, r"\b(no|not|never|nor|nothing|without|cannot|any)\b|banned|strikes",
                             msg=f"{match.group(0)!r} near {window!r}")

    def test_the_prompts_never_tell_a_model_to_claim_a_profit_or_an_edge(self):
        for stage, role in roles.ROLES.items():
            for match in re.finditer(r"(?i)\bprofit\w*|\bedges?\b|\bguarantee\w*|\bfree money\b", role.system):
                window = role.system[max(0, match.start() - 60):match.end() + 40].lower()
                self.assertRegex(window, r"\bnever\b", msg=f"{stage}: {match.group(0)!r} near {window!r}")

    def test_personas_are_archetypes_not_people(self):
        for h in roles.HOUNDS:
            self.assertRegex(h["name"], r"^The [A-Z][A-Za-z ]+$", h["name"])


class ThePreRegistration(unittest.TestCase):
    def test_it_registers_the_menus_the_rules_the_publication_rule_and_the_expectation(self):
        for needle in ("## 2. The decision menu", "## 3. The code risk manager", "## 4. The publication rule",
                       "## 5. The persona rules", "## 6. Rows, forward only, and grading",
                       "## 7. The honest expectation", "Forward only", "model-written analysis",
                       "unproven", "closing-price referee", "-200", "at most 2 games", "30 subagent answers",
                       "90 minutes", "5 percentage points", "-150"):
            self.assertIn(needle, PREREG, needle)

    def test_it_names_every_hound(self):
        for h in roles.HOUNDS:
            self.assertIn(f"`{h['id']}`", PREREG)

    def test_its_numbers_are_the_codes(self):
        self.assertEqual((state.MAX_GAMES_PER_RUN, state.MAX_ANSWERS_PER_RUN, state.MAX_ATTEMPTS, risk.MAX_TAKES),
                         (2, 30, 3, 2))
        self.assertIn("three attempts per stage", PREREG)
        self.assertIn("at most 2 takes", PREREG.lower())

    def test_the_pre_registration_was_not_changed_after_the_first_registration(self):
        """Once the ledger holds definition rows, each carries the sha256 of the pre-registration it was
        registered under. If this file changes later, this test names it."""
        path = ledger.path()
        if not path.exists():
            self.skipTest("nothing registered yet")
        defs = [r for r in ledger.rows() if r.get("kind") == ledger.KIND_HOUND]
        for row in defs:
            self.assertEqual(row["prereg_sha256"], publish.prereg_sha256(), row["hound_id"])


class TheDocs(unittest.TestCase):
    def test_the_runbook_section_exists_is_last_and_has_the_parent_steps(self):
        self.assertTrue(RUNBOOK.startswith("# Running a matchup brief (session-assisted)"))
        self.assertEqual(RUNBOOK.count("## Desk and persona hounds"), 1)
        self.assertEqual(re.findall(r"^## .*$", SECTION, re.M), ["## Desk and persona hounds"])
        for command in ("prepare --date", "session-plan --date", "session-check --date", "publish --date",
                        "session-status --date", "grade --date", "verify"):
            self.assertIn(f"python -m src.hounds.desk {command}", SECTION.replace("\r", ""), command)
        for needle in ("FOREGROUND Sonnet subagent", "at most 2 games", "at most 30 subagent answers",
                       "EVERY STAGE IS FINAL", "90 minutes"):
            self.assertIn(needle, SECTION, needle)

    def test_the_old_runbook_text_is_untouched_above_the_new_section(self):
        head = RUNBOOK[:SECTION_START]
        self.assertIn("## NFL (session-assisted, its own files)", head)
        self.assertIn("## What never happens", head)
        self.assertTrue(head.rstrip().endswith("Nothing here turns billing on or sends a message to anyone."))

    def test_the_commands_in_the_docs_are_real_subcommands(self):
        parser = cli.build_parser()
        subcommands = set(parser._subparsers._group_actions[0].choices)
        for text in (SECTION, DOC):
            for m in re.finditer(r"python -m src\.hounds\.desk (?:--root \S+ )?([a-z-]+)", text):
                self.assertIn(m.group(1), subcommands, m.group(0))

    def test_the_doc_names_the_files_and_the_row_kinds_the_code_writes(self):
        for needle in ("hound_bet", "hound_graded", "desk_game", "transcript.json", "disagreement.json",
                       "evidence/hounds_desk_v1.jsonl", "lock_utc", "price_average", "price_best"):
            self.assertIn(needle, DOC, needle)
        self.assertIn(ledger.KIND_BET, DOC)
        self.assertIn(ledger.KIND_GAME, DOC)

    def test_the_doc_is_honest_about_what_it_cannot_do(self):
        self.assertIn("## What it cannot do", DOC)
        self.assertIn("one model", DOC.lower())
        self.assertIn("no line-movement history", DOC)


if __name__ == "__main__":
    unittest.main()
