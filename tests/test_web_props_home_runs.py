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

    def test_it_never_prints_a_zero_for_the_absent_number(self):
        """`percent(null)` is null and the row has no market column, so a
        None market_probability can never render as "0%"."""
        self.assertNotIn("row.market_probability)", self.text)


if __name__ == "__main__":
    unittest.main()
