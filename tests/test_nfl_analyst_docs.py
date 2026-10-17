"""The NFL docs say what the code does: the prompt, the stores, the commands, and what ships in the image."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from src.analyst import nfl_analyst, nfl_packet, nfl_pilot

ROOT = Path(__file__).resolve().parent.parent
DOC = (ROOT / "docs" / "AI_ANALYST.md").read_text(encoding="utf-8")
RUNBOOK = (ROOT / "docs" / "BRIEF_RUNBOOK.md").read_text(encoding="utf-8")
START = DOC.index("## The NFL brief")
NFL = DOC[START:DOC.index("\n## ", START + 5)]
RUN_START = RUNBOOK.index("## NFL (session-assisted")
RUN_NFL = RUNBOOK[RUN_START:RUNBOOK.index("\n## ", RUN_START + 5)]


def commands(text: str) -> list:
    """Every `python -m src.cli analyst ...` command in a block of docs, continuations joined and
    trailing comments dropped."""
    joined = re.sub(r"\\\n\s*", "", text)
    found = [m.group(1) for m in re.finditer(r"^python -m src\.cli (analyst .+?)(?:\s+#.*)?$", joined, re.M)]
    found = [re.sub(r"\s*\[[^\]]*\]", "", line) for line in found]        # "[--scratch DIR]" is an optional part
    return [re.sub(r"(--[a-z-]+) [NSM]\b", r"\1 1", line) for line in found]   # "--tokens-in N" is a number to fill in


class TheDocQuotesTheCode(unittest.TestCase):
    def test_the_prompt_in_the_doc_is_the_prompt_in_the_code(self):
        self.assertIn(nfl_analyst.NFL_SYSTEM_PROMPT, NFL)
        self.assertIn(nfl_analyst.NFL_PROMPT_VERSION, NFL)

    def test_the_section_sits_before_the_ufc_section_which_counts_what_follows_it(self):
        self.assertLess(DOC.index("## The NFL brief"), DOC.index("## The UFC analyst"))

    def test_the_files_it_names_are_the_nfl_pilots(self):
        for name in (nfl_pilot.STORE, nfl_pilot.USAGE_STORE, nfl_pilot.PACKET_DIR, nfl_pilot.PILOT_DIR):
            self.assertIn(name.replace("\\", "/"), NFL)

    def test_the_packet_fields_it_lists_are_the_packets(self):
        self.assertIn(nfl_packet.PACKET_VERSION, NFL)
        for slot in nfl_packet.SLOT_ORDER:
            self.assertIn(slot, NFL)
        for key in ("figure_units", "how_to_read", "missing", "limits", "slots"):
            self.assertIn(key, NFL)

    def test_the_key_numbers_and_scoring_it_states_are_the_packets(self):
        self.assertEqual(nfl_packet.KEY_NUMBERS, [3, 6, 7, 10, 14])
        self.assertIn("the key numbers 3, 6, 7, 10 and 14", NFL)
        self.assertEqual(nfl_packet.SCORING["field_goal"], 3)

    def test_the_commands_in_the_doc_and_the_runbook_parse_as_nfl_commands(self):
        from src import cli as top
        for block, expected in ((NFL, 5), (RUN_NFL, 5)):
            found = commands(block)
            self.assertEqual(len(found), expected, found)           # a scan that matches nothing proves nothing
            for line in found:
                args = top.build_parser().parse_args(line.split())
                self.assertEqual(args.sport, "nfl", line)

    def test_the_thin_spots_are_named(self):
        for needle in ("No player-prop prices", "No weather forecast", "carry no timestamp", "a projection",
                       "No depth chart", "nominal home team"):
            self.assertIn(needle, NFL)


class TheRunbook(unittest.TestCase):
    def test_it_gives_the_freeze_times_for_the_sunday_slate(self):
        for needle in ("Sun 07:00", "Sun 10:00", "about three hours before kickoff", "90 minutes",
                       "HOU@JAX", "LAC@KC", "DAL@GB", "BAL@CLE"):
            self.assertIn(needle, RUN_NFL)

    def test_it_names_the_sport_field_of_the_sample(self):
        self.assertIn('"sport": "nfl"', RUN_NFL)


class HouseStyle(unittest.TestCase):
    def test_no_em_dashes_and_no_banned_names(self):
        for name, text in (("AI_ANALYST NFL section", NFL), ("BRIEF_RUNBOOK NFL section", RUN_NFL)):
            self.assertNotIn("—", text, name)
            self.assertNotRegex(text, r"(?i)bet[\s-]*check", name)

    def test_the_only_profit_words_are_denials(self):
        for match in re.finditer(r"(?i)\bprofit\w*|\bedge\b|\bguarantee\w*|\bfree money\b", NFL + RUN_NFL):
            window = (NFL + RUN_NFL)[max(0, match.start() - 80):match.end() + 40].lower()
            self.assertRegex(window, r"\b(no|not|never|nor|without|cannot|any)\b|never says|banned|strikes",
                             msg=f"{match.group(0)!r} near {window!r}")


class TheImageShipsIt(unittest.TestCase):
    """api/analyst_nfl.py reads evidence/analyst_pilot_nfl_v1.jsonl and the packet folder at request time,
    and /sample/brief reads config/sample_brief.json: all three must be in the image."""

    def test_evidence_and_config_are_copied_whole_and_nothing_ignores_the_nfl_files(self):
        dockerfile = (ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
        self.assertRegex(dockerfile, r"(?m)^COPY evidence/ evidence/\s*$")
        self.assertRegex(dockerfile, r"(?m)^COPY config/ config/\s*$")
        ignore = [l.strip() for l in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
                  if l.strip() and not l.strip().startswith("#")]
        for pattern in ignore:
            self.assertFalse(pattern.startswith("evidence") and not pattern.startswith("evidence/archive"),
                             f".dockerignore drops {pattern!r}")
            self.assertNotIn("analyst_pilot", pattern)
            self.assertNotEqual(pattern.rstrip("/"), "config")

    def test_git_does_not_ignore_the_nfl_pilot_files(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for line in (l.strip() for l in gitignore.splitlines()):
            if line and not line.startswith(("#", "!")):
                self.assertNotIn("analyst_pilot", line, line)


if __name__ == "__main__":
    unittest.main()
