"""web/js/mybets.js: the save form waits for the board.

THE DEFECT
----------
Swept live on 2026-09-12, signed out: a working-looking GAME / SIDE / PRICE
/ SAVE BET form sat directly ABOVE a "SIGN IN REQUIRED" wall. The form
rendered first and unconditionally; the board request ran after it and
failed with a 401. A reader could fill the form in and submit it into that
401. Offering a control that cannot work reads as a broken app.

Plain-text scan of the module, like the other web structure tests.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MYBETS = ROOT / "web" / "js" / "mybets.js"


def _body(text: str, name: str) -> str:
    return text.split(f"function {name}(")[1].split("\nfunction ")[0]


class TheFormWaitsForTheBoard(unittest.TestCase):
    def setUp(self):
        self.text = MYBETS.read_text(encoding="utf-8")
        self.render = _body(self.text, "renderMyBets")

    def test_the_form_is_not_rendered_before_the_board_loads(self):
        """`renderSaveForm` must sit INSIDE `reload`, after the fetch."""
        before_reload = self.render.split("async function reload()")[0]
        self.assertNotIn("renderSaveForm(", before_reload,
                         "the save form renders before we know a save could work")

    def test_the_form_is_rendered_after_a_successful_fetch(self):
        reload = self.render.split("async function reload()")[1]
        fetch_at = reload.find('apiGet("/my-bets")')
        form_at = reload.find("renderSaveForm(")
        self.assertGreater(fetch_at, -1)
        self.assertGreater(form_at, fetch_at,
                           "the form must render after the board fetch")

    def test_a_failed_fetch_clears_the_form_rather_than_leaving_it_above_the_wall(self):
        reload = self.render.split("async function reload()")[1]
        catch_block = reload.split("catch (err)")[1].split("}")[0]
        self.assertIn("clear(formHost)", catch_block)

    def test_the_false_bet_check_instruction_stays_gone(self):
        # Rendered strings only: the comment explaining why the instruction
        # was removed necessarily quotes it.
        from tests.test_no_developer_notes_on_screen import _rendered_strings
        rendered = [t for _n, t in _rendered_strings(MYBETS)]
        self.assertFalse(any("Bet Check" in t for t in rendered),
                         "My Bets points at a save action Bet Check does not have")


if __name__ == "__main__":
    unittest.main()
