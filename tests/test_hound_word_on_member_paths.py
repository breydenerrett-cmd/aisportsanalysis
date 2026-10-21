"""Kennel-first product language (docs/design/KENNEL_FIRST_BRIEF.md): the UI says hound, never dog.

Rebuild QA 2026-10-21 found "dog" on the screens a free member meets first: every Ask/Backtest/Live upgrade prompt
("A free account keeps one dog"), every Unleash preview ("The dog's real ticket..."), the second-hound refusal and the
Training camp count ("2 dogs"). These pin the member-path strings. Plain text reads, so no FastAPI or node is needed.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOG = re.compile(r"(?<![-_A-Za-z])[Dd]ogs?(?![-_A-Za-z])")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


class TheHoundWordOnMemberPaths(unittest.TestCase):
    def test_the_upgrade_prompt_says_hound(self):
        src = read("web/js/upgrade.js")
        titles = re.search(r"const FEATURE_TITLES = \{(.*?)\};", src, re.S).group(1)
        fallback = re.search(r"export const FALLBACK_MESSAGE =\s*\"([^\"]+)\"", src).group(1)
        for text in re.findall(r":\s*\"([^\"]+)\"", titles) + [fallback]:
            self.assertIsNone(DOG.search(text), text)
        self.assertIn("A free account keeps one hound", fallback)

    def test_the_server_refusals_say_hound(self):
        ent = read("api/entitlements.py")
        words = re.search(r"_FEATURE_WORDS = \{(.*?)\}", ent, re.S).group(1)
        message = re.search(r'"message": message or (f"[^\n]+\n\s+"[^"]+")', ent).group(1)
        for text in re.findall(r":\s*\"([^\"]+)\"", words) + [message]:
            self.assertIsNone(DOG.search(text), text)
        from src.hounds import user_store
        self.assertIsNone(DOG.search(user_store.FREE_LIMIT_MESSAGE), user_store.FREE_LIMIT_MESSAGE)

    def test_the_unleash_preview_says_hound(self):
        from src.hounds.interact import fire, fire_event
        self.assertIsNone(DOG.search(fire.PREVIEW_NOTE), fire.PREVIEW_NOTE)
        self.assertIn("this hound's sports", read("src/hounds/interact/fire.py"))
        for text in fire_event.LIVE_CODES.values():
            self.assertIsNone(DOG.search(text), text)

    def test_the_backtest_result_says_hound(self):
        from src.hounds.interact import drill
        self.assertIsNone(DOG.search(drill.DISCLOSURE), drill.DISCLOSURE)
        src = read("web/js/dog-backtest.js")
        self.assertIn('h("dt", { text: "Hound" })', src)
        self.assertIn('"Sign in to run a backtest on this hound."', src)
        self.assertIn('text: "Hound" }), select', read("web/js/dog-camp.js"))

    def test_the_training_camp_counts_hounds(self):
        self.assertIn('plural(dogCount, "hound", "hounds")', read("web/js/camp-overview.js"))


if __name__ == "__main__":
    unittest.main()
