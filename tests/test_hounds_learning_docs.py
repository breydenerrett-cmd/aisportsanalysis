"""The docs say what the code does: every command, route and tunable hound they name exists, and the
pre-registration is where the code says it is."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from src.hounds.learning import cli, rules, tunables

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "docs" / "HOUNDS_LEARNING.md").read_text(encoding="utf-8")
HOUNDS = (ROOT / "docs" / "HOUNDS.md").read_text(encoding="utf-8")
USER = (ROOT / "docs" / "HOUNDS_USER.md").read_text(encoding="utf-8")


class TheOperatorGuide(unittest.TestCase):
    def test_every_cli_command_is_documented(self):
        names = set(cli.build_parser()._subparsers._group_actions[0].choices)
        for name in names:
            self.assertIn(name, DOC, name)

    def test_the_hounds_the_guide_lists_as_tunable_are_the_hounds_the_config_declares(self):
        section = DOC[DOC.index("Hounds with a declaration today:"):]
        line = section[:section.index("have none") if "have none" in section else 400]
        named = set(re.findall(r"[a-z]+_[a-z_]+", line)) - {"jetlag"}
        declared = set(tunables.load())
        self.assertEqual({n for n in named if n in declared}, declared)

    def test_the_routes_are_in_the_race_docs(self):
        for route in ("GET /hounds/learning", "GET /hounds/learning/lessons", "GET /hounds/{id}/lineage"):
            self.assertIn(route, HOUNDS)
            self.assertIn(route.replace("GET ", "").split("?")[0], DOC + HOUNDS)

    def test_the_user_coach_doc_no_longer_says_a_proposal_applies(self):
        self.assertIn("a proposal creates a challenger, never a change", USER)
        self.assertNotIn("**Applying** creates a new version", USER)

    def test_the_guide_states_what_is_not_done(self):
        self.assertIn("What is not done", DOC)
        for needle in ("The coach is not built", "One BH family per scope", "scripts/capture_slot.sh"):
            self.assertIn(needle, DOC)

    def test_the_guide_and_the_prereg_agree_on_the_headline_numbers(self):
        prereg = (ROOT / "docs" / "PREREG_LEARNING_LOOP.md").read_text(encoding="utf-8")
        self.assertIn("100/150/200/250/300", DOC)
        self.assertIn("100, 150, 200, 250 and 300", prereg)
        self.assertEqual(rules.LOOKS, (100, 150, 200, 250, 300))
        self.assertIn("150/225/300/375/450", DOC)
        self.assertEqual(rules.ANALYST_LOOKS, (150, 225, 300, 375, 450))

    def test_the_coach_kill_switch_still_ships_off(self):
        cfg = json.loads((ROOT / "config" / "hounds_coach.json").read_text(encoding="utf-8"))
        self.assertIs(cfg["enabled"], False)

    def test_nothing_in_the_loop_can_place_a_bet_or_claim_an_edge(self):
        banned = re.compile(r"(?i)\b(place_bet|stake_money|place a bet|guaranteed|sure thing)\b")
        for path in list((ROOT / "src" / "hounds" / "learning").glob("*.py")) + [ROOT / "src" / "analyst" / "prompt_arm.py"]:
            text = path.read_text(encoding="utf-8")
            text = re.sub(r'"""[\s\S]*?"""', "", text)               # docstrings may NAME what is forbidden
            self.assertIsNone(banned.search(text), path.name)

    def test_the_minus_200_rule_is_enforced_by_the_engines_the_shadow_runner_reuses(self):
        pack_run = (ROOT / "src" / "hounds" / "pack_run.py").read_text(encoding="utf-8")
        user_engine = (ROOT / "src" / "hounds" / "user_engine.py").read_text(encoding="utf-8")
        self.assertIn("price_average\"] <= -200", pack_run)
        self.assertIn("beyond_cap", user_engine)
        shadow = (ROOT / "src" / "hounds" / "learning" / "shadow.py").read_text(encoding="utf-8")
        self.assertIn("pack_run.run", shadow)
        self.assertIn("user_engine.run", shadow)
        self.assertNotIn("replay=True", shadow)


if __name__ == "__main__":
    unittest.main()
