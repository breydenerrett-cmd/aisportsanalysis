"""Home runs on the prop board, likelihood only (web/js/props.js).

No book quotes the under, so there is no fair price; the row shows OURS
and PRICE NEEDS as every row does and says in words what is missing.
Plain-text scans like the other web structure tests.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tests.test_no_developer_notes_on_screen import _rendered_strings

ROOT = Path(__file__).resolve().parent.parent
PROPS_JS = ROOT / "web" / "js" / "props.js"


class HomeRunsReadAsHomeRuns(unittest.TestCase):
    def setUp(self):
        self.text = PROPS_JS.read_text(encoding="utf-8")

    def test_the_market_has_a_label(self):
        labels = self.text.split("const MARKET_LABELS = {")[1].split("};")[0]
        self.assertIn('batter_home_runs: "home runs"', labels)

    def test_the_missing_market_number_is_said_in_words(self):
        body = self.text.split("function propRow(")[1].split("\nfunction ")[0]
        self.assertIn("row.market_probability_absent", body)
        self.assertIn('"prop-market-absent"', body)
        rendered = " ".join(t for _n, t in _rendered_strings(PROPS_JS)).lower()
        self.assertIn("no book quotes the under", rendered)

    def test_home_runs_have_their_own_list_under_an_honest_heading(self):
        body = self.text.split("function longShots(")[1].split("\nfunction ")[0]
        self.assertIn("payload.long_shots", body)
        self.assertIn('"props-long-shots-list"', body)
        self.assertIn("none of these is likely", body)
        # Mounted after the likely list, and on an empty likely list too.
        render = self.text.split("export async function renderProps(")[1].split("\nfunction ")[0]
        self.assertIn("host.appendChild(longShots(payload))", render)

    def test_the_book_is_named_not_keyed(self):
        """"+500 at williamhill_us" was on the page (2026-09-12); the book
        resolver every other screen uses names it."""
        body = self.text.split("function propRow(")[1].split("\nfunction ")[0]
        self.assertIn("bookLabel(row.book)", body)
        self.assertIn('import { bookLabel } from "./labels.js";', self.text)

    def test_it_never_prints_a_zero_for_the_absent_number(self):
        """`percent(null)` is null and the row has no market column, so a
        None market_probability can never render as "0%"."""
        self.assertNotIn("row.market_probability)", self.text)


if __name__ == "__main__":
    unittest.main()
