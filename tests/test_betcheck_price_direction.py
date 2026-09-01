"""Regression: which way is "better" when Bet Check talks about a price.

THE BUG THIS FILE EXISTS FOR
-----------------------------
`build_contract`'s bottom line described `cents_delta` (the stated price
minus the best price on our board) with the two directions swapped. For two
same-sign American prices on the same side, the HIGHER number is the better
price for the bettor: -105 risks 105 to win 100 where -110 risks 110, and
+150 pays more than +140. `cents_delta` is stated MINUS best, so a positive
delta means the customer's price BEATS our board.

The shipped sentence said the opposite. A customer holding -130 against a
board whose best was -106 -- a materially worse number -- was told, in the
paid-beta core loop's bottom line, that their price was "24 cents better
than the best available -106". That is a false price claim, in the one
place the product promises never to make one, and it was the common case:
`best_price` is by construction the best number on the board, so `cents < 0`
(the "your price loses to the board" branch) is what most real checks hit.

Every assertion below is written against the ARITHMETIC of American odds
rather than against the sentence's current wording, so a future rewrite of
the copy cannot quietly restore the inversion.
"""

from __future__ import annotations

import unittest

from src.analysis import betcheck
from src.core import odds as odds_math


def board(rows=9, away_price=-110, home_price=-110,
          observed_utc="2026-08-31T18:00:00+00:00"):
    return {"quotes": [{"book": f"book_{i}", "away_price": away_price,
                        "home_price": home_price} for i in range(rows)],
            "observed_utc": observed_utc}


def bottom_line(side, stated, best_on_board):
    """The contract's bottom line for one stated price against a board whose
    best number for `side` is `best_on_board`."""
    prices = {"away_price": best_on_board, "home_price": best_on_board}
    result = betcheck.build_contract(
        "2026-08-31", "BOS", "NYY", side, stated,
        board=board(**prices), findings=[])
    return result.bottom_line


class CentsDeltaArithmeticTests(unittest.TestCase):
    """The premise the sentence rests on, proven independently of the
    sentence: a positive cents_delta really does mean the better price."""

    def _better_of(self, a, b):
        """Whichever of two same-side American prices pays the bettor more."""
        return a if (odds_math.american_to_decimal(a)
                     > odds_math.american_to_decimal(b)) else b

    def test_positive_cents_delta_means_the_stated_price_is_the_better_one(self):
        for stated, best in [(-105, -110), (-105, -106), (150, 140), (110, 105)]:
            with self.subTest(stated=stated, best=best):
                self.assertGreater(betcheck._cents_delta(stated, best), 0)
                self.assertEqual(self._better_of(stated, best), stated)

    def test_negative_cents_delta_means_the_stated_price_is_the_worse_one(self):
        for stated, best in [(-130, -106), (-115, -110), (140, 150)]:
            with self.subTest(stated=stated, best=best):
                self.assertLess(betcheck._cents_delta(stated, best), 0)
                self.assertEqual(self._better_of(stated, best), best)

    def test_mixed_sign_prices_are_not_compared_in_cents_at_all(self):
        self.assertIsNone(betcheck._cents_delta(-130, 120))
        self.assertIsNone(betcheck._cents_delta(120, -130))


class BottomLineDirectionTests(unittest.TestCase):

    def test_a_worse_stated_price_is_never_called_better(self):
        # -130 against a board best of -106: the customer's number loses.
        line = bottom_line("home", -130, -106)
        self.assertIn("24 cents worse than the best available -106", line)
        self.assertNotIn("cents better", line)

    def test_a_better_stated_price_is_never_called_worse(self):
        # -105 against a board best of -106: the customer found a number our
        # board does not have.
        line = bottom_line("home", -105, -106)
        self.assertIn("1 cents better than the best available -106", line)
        self.assertNotIn("cents worse", line)

    def test_underdog_direction_reads_the_same_way(self):
        # Positive prices, same rule: +150 beats +140.
        line = bottom_line("home", 150, 140)
        self.assertIn("10 cents better than the best available +140", line)
        line = bottom_line("home", 140, 150)
        self.assertIn("10 cents worse than the best available +150", line)

    def test_matching_the_board_claims_neither_direction(self):
        line = bottom_line("home", -110, -110)
        self.assertIn("matches the best available price on the board", line)
        self.assertNotIn("cents better", line)
        self.assertNotIn("cents worse", line)

    def test_the_price_sentence_never_promotes_itself_to_an_edge(self):
        for stated, best in [(-130, -106), (-105, -106), (150, 140)]:
            with self.subTest(stated=stated, best=best):
                line = bottom_line("home", stated, best)
                self.assertIn("line-shopping value, not a prediction", line)
                self.assertIn("No predictive edge is claimed", line)


if __name__ == "__main__":
    unittest.main()
