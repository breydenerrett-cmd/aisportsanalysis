"""`spread_cents` must not count the hole in the American scale.

-105 and +100 are five cents apart: both sit within a nickel of even money.
Plain subtraction says 205, because the scale skips from -100 to +100. On
2026-09-11 the live board printed "205c between books" for LAA quoted
between -105 and +100, and the slate's WIDEST SPREAD headline was that same
artefact ("207c apart on CWS"). The module docstring had already said the
two gaps should both read 5; the code did not do what its docstring said.
"""

from __future__ import annotations

import unittest

from src.analysis import oddspayload
from tests.test_analysis_oddspayload import NOW, TS, _quote


def _snapshot(quotes):
    return {"quotes": quotes, "observed_utc": TS, "source": "test"}


def _board_straddling_even_money():
    """Seven books (above the consensus floor). Away quotes run -105 to +100
    -- five cents apart -- and home quotes -110 to -118, eight apart."""
    return _snapshot([
        _quote("fanduel", -102, -116),
        _quote("betonline", 100, -110),
        _quote("lowvig", 100, -110),
        _quote("draftkings", -102, -118),
        _quote("caesars", -105, -115),
        _quote("betmgm", -104, -112),
        _quote("bovada", -101, -117),
    ])


class TheSpreadReadsTheBoardNotTheScale(unittest.TestCase):

    def test_minus_105_to_plus_100_is_five_cents(self):
        """THE ONE THAT MATTERS. Plain subtraction returns 205 here."""
        section = oddspayload.build_market_h2h(_board_straddling_even_money(), now=NOW)
        self.assertAlmostEqual(section["spread_cents"]["away"], 5)
        self.assertAlmostEqual(section["spread_cents"]["home"], 8)

    def test_the_scale_has_no_hole(self):
        self.assertEqual(oddspayload._cents(-105), -5)
        self.assertEqual(oddspayload._cents(-100), 0)
        self.assertEqual(oddspayload._cents(100), 0)
        self.assertEqual(oddspayload._cents(105), 5)
        self.assertEqual(oddspayload._cents(-150), -50)
        self.assertEqual(oddspayload._cents(150), 50)

    def test_same_sign_spreads_are_unchanged(self):
        """-105 best against -120 worst is still 15, exactly as the module
        docstring's own example reads."""
        board = _snapshot([_quote(f"book{i}", price, -110)
                           for i, price in enumerate((-105, -108, -110, -112, -115, -118, -120))])
        section = oddspayload.build_market_h2h(board, now=NOW)
        self.assertAlmostEqual(section["spread_cents"]["away"], 15)
        self.assertAlmostEqual(section["spread_cents"]["home"], 0)


if __name__ == "__main__":
    unittest.main()
