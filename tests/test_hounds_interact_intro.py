"""The "who are you?" introduction (owner, 2026-10-25).

"Who are you?" answers in two or three short lines in the hound's voice: its name and personality line, what it bets
   (sports through the sport label map, markets, the price band), and its record so far. No canine word in that copy (a
   hound's own name and a builder's tagline are the only text that can carry one, and a tagline with the word is left out),
   and no Good call / Bad call row under an introduction.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from src.hounds.interact import ask
from tests.test_hounds_interact_ask import SUMMARY, context

ROOT = Path(__file__).resolve().parent.parent
DOG = re.compile(r"(?<![-_A-Za-z])[Dd]ogs?(?![-_A-Za-z])")
SPEC = {"sports": ["MLB", "GRIDIRON"], "markets": ["moneyline", "total"], "price_min": -150, "price_max": 150,
        "lock_minutes": 120, "max_bets_per_day": 2, "min_books": 3}


class TheIntroduction(unittest.TestCase):
    def test_it_names_the_hound_then_what_it_bets_then_its_record(self):
        out = ask.answer("who are you", context(name="Classic Pup", catchphrase="Fetch the plus money.", spec=SPEC))
        lines = out["lines"]
        self.assertEqual(lines[0], "Classic Pup · Fetch the plus money.")
        self.assertEqual(len(lines), 3)
        bets = lines[1]
        self.assertIn("MLB", bets)
        self.assertIn("CFL and UFL", bets)              # GRIDIRON through the sport label map, never the raw key
        self.assertNotIn("GRIDIRON", out["answer"])
        self.assertIn("moneylines and game totals", bets)
        self.assertIn("from -150 to +150", bets)
        self.assertIn("-200 or worse", bets)
        self.assertTrue(lines[2].startswith("So far: "), lines[2])
        self.assertIn(f"{SUMMARY['record']['wins']}-{SUMMARY['record']['losses']}", lines[2])

    def test_a_tagline_with_the_canine_word_is_left_out_and_no_copy_carries_it(self):
        out = ask.answer("who are you", context(name="Closer", catchphrase="Takes dogs.", spec=SPEC))
        self.assertEqual(out["lines"][0], "Closer")
        for line in out["lines"]:
            self.assertIsNone(DOG.search(line), line)

    def test_a_hound_with_no_graded_bets_says_so(self):
        empty = dict(SUMMARY, record={"bets": 0, "wins": 0, "losses": 0})
        out = ask.answer("hi", context(spec=SPEC, summary=empty))
        self.assertEqual(out["lines"][-1], "No graded bets yet.")

    def test_a_house_dog_with_no_spec_says_its_trigger_instead(self):
        out = ask.answer("who are you", context(kind="house", spec=None, trigger="a favourite is priced between -101 and -199"))
        self.assertEqual(out["lines"][1], "I bet when a favourite is priced between -101 and -199.")

    def test_the_intro_is_never_more_than_three_lines(self):
        out = ask.answer("who are you", context(spec=SPEC, trigger="x"))
        self.assertLessEqual(len(out["lines"]), 3)

    def test_the_page_skips_the_vote_row_for_an_introduction(self):
        js = (ROOT / "web" / "js" / "dog-ask.js").read_text(encoding="utf-8")
        self.assertIn('if (out.intent !== "hello") msg.appendChild(voteRow(', js)


if __name__ == "__main__":
    unittest.main()
