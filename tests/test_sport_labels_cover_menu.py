"""Every sport a hound can carry has a readable label on the hound page and the leaderboard filter.

Rebuild QA 2026-10-21: web/js/hounds-board.js labelled six sports and uppercased the rest, so the Gematria Hound (all
seventeen) read "NCAAF, GRIDIRON, ... BASKETBALL, HOCKEY, BASEBALL, SOCCER, Tennis, CRICKET" on its page.
"""
import re
import unittest
from pathlib import Path

from src.hounds import user_spec

ROOT = Path(__file__).resolve().parents[1]


class TheSportLabels(unittest.TestCase):
    def test_every_builder_sport_has_a_label(self):
        src = (ROOT / "web" / "js" / "hounds-board.js").read_text(encoding="utf-8")
        block = re.search(r"export const SPORT_LABELS = \{(.*?)\};", src, re.S).group(1)
        labels = dict(re.findall(r"(\w+):\s*\"([^\"]+)\"", block))
        for sport in user_spec.builder_menu()["sports"]:
            key = sport["value"].lower()
            if key == "any":
                continue
            self.assertIn(key, labels, f"{key} would be shown as {key.upper()}")
            self.assertNotEqual(labels[key], key.upper() if len(key) > 4 else "", key)


if __name__ == "__main__":
    unittest.main()
