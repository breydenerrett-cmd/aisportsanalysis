"""The per-game note on #/day is read by a customer.

"no linescore row found in boxscores_2026.jsonl for game_pk=822767" was
under Baltimore Orioles @ Toronto Blue Jays on 2026-09-11. The store name
and the lookup key belong in a log.
"""

from __future__ import annotations

import unittest

from src.report import daily_record


class TheMissingScoreNoteIsForAReader(unittest.TestCase):

    def test_no_store_name_or_key_reaches_the_page(self):
        score, note = daily_record._final_score_for(822767, {})
        self.assertIsNone(score)
        for token in (".jsonl", "game_pk=", "822767"):
            self.assertNotIn(token, note)
        self.assertEqual(note, "final score not recorded yet")

    def test_a_found_score_carries_no_note(self):
        score, note = daily_record._final_score_for(1, {1: {"away": 3, "home": 5}})
        self.assertEqual(score, {"away": 3, "home": 5})
        self.assertIsNone(note)


if __name__ == "__main__":
    unittest.main()
