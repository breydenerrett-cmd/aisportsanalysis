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


class BottomLineSaysWhatThePriceNeeds(unittest.TestCase):
    """Probability before price, in the one block every check renders.

    This clause used to compare the stated price to the board's best number
    ("24 cents worse than the best available -106") -- the register the
    owner retired on 2026-09-10 -- and an independent review found it still
    here on 2026-09-12, after the caption that used to flag it had gone.
    Now it says what the stated price needs to break even, then what the
    market makes it. The direction arithmetic above still guards
    `cents_delta`, which stays on the contract but is no longer a sentence.
    """

    def test_a_minus_price_states_its_break_even(self):
        # -130 needs 130/230 = 56.5% -> "57%"; a -106/-106 board de-vigs to 50%.
        line = bottom_line("home", -130, -106)
        self.assertIn("At -130 this bet needs 57% to break even", line)
        self.assertIn("the market makes it 50%", line)

    def test_a_plus_price_states_its_break_even(self):
        # +150 needs 100/250 = 40%.
        line = bottom_line("home", 150, 140)
        self.assertIn("At +150 this bet needs 40% to break even", line)

    def test_the_break_even_follows_the_stated_price_not_the_board(self):
        self.assertIn("needs 52% to break even", bottom_line("home", -110, -106))
        self.assertIn("needs 57% to break even", bottom_line("home", -130, -106))

    def test_no_comparison_to_the_best_available_price(self):
        for stated, best in [(-130, -106), (-105, -106), (150, 140), (-110, -110)]:
            with self.subTest(stated=stated, best=best):
                line = bottom_line("home", stated, best).lower()
                for phrase in ("cents better", "cents worse", "cent better",
                               "cent worse", "best available", "matches the best"):
                    self.assertNotIn(phrase, line, phrase)

    def test_the_retired_register_never_reaches_the_screen_from_python(self):
        """The client sweep (tests/test_web_betcheck_register.py) scans JS
        literals; this sentence is composed in Python and rendered verbatim,
        so it is swept with the same list."""
        from tests.test_web_betcheck_register import RETIRED
        for stated, best in [(-130, -106), (-105, -106), (150, 140)]:
            line = bottom_line("home", stated, best).lower()
            for phrase in RETIRED:
                self.assertNotIn(phrase, line, phrase)

    def test_the_price_sentence_never_promotes_itself_to_an_edge(self):
        for stated, best in [(-130, -106), (-105, -106), (150, 140)]:
            with self.subTest(stated=stated, best=best):
                line = bottom_line("home", stated, best)
                self.assertNotIn("line-shopping", line)
                self.assertIn("No predictive edge is claimed", line)

    def test_no_market_context_says_so_and_states_no_number(self):
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -130,
            board={"quotes": []}, findings=[])
        self.assertIn("Market context is unavailable", result.bottom_line)
        self.assertNotIn("break even", result.bottom_line)


class YourPriceBeatsConsensusTests(unittest.TestCase):
    """The renamed field (`your_price_beats_consensus`, formerly the
    ambiguous `your_price_below_market`) verified against american_to_decimal
    arithmetic directly -- not against the sentence copy above, so a future
    rewrite of either cannot quietly re-invert the other."""

    def _beats_consensus(self, side, stated, consensus_side_price):
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", side, stated,
            board=board(**{f"{side}_price": consensus_side_price,
                          ("home_price" if side == "away" else "away_price"):
                              consensus_side_price}),
            findings=[])
        return result.your_price_beats_consensus

    def test_a_higher_decimal_payout_than_consensus_beats_it(self):
        # +150 pays a higher decimal than a -110/-110 (~1.909) consensus.
        self.assertTrue(self._beats_consensus("home", 150, -110))
        self.assertGreater(odds_math.american_to_decimal(150),
                           odds_math.american_to_decimal(-110))

    def test_a_lower_decimal_payout_than_consensus_does_not_beat_it(self):
        self.assertFalse(self._beats_consensus("home", -500, -110))
        self.assertLess(odds_math.american_to_decimal(-500),
                        odds_math.american_to_decimal(-110))

    def test_no_board_leaves_it_none_not_a_guess(self):
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=[])
        self.assertIsNone(result.your_price_beats_consensus)


if __name__ == "__main__":
    unittest.main()
