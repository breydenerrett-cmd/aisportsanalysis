"""The evolab thesis is the first thing under a pick on #/today, cut to a
~90-character teaser. On 2026-09-11 that teaser read, in full:

    Backing the home side of h2h because 1 pre-registered signal fired:
    (1) primary_pitch_share…

A market key and a feature id. The market is now named in words and the
plain-words quantity leads each signal sentence, with the feature id after
it in brackets; the closing no-claim sentence no longer names fields or a
docs path.
"""

from __future__ import annotations

import unittest

from src.engine import explain
from tests.test_decision_explanations import LOUD_FEATURES

FIRED = (("top_minus_bottom", 1),)


def _thesis(market="h2h", side="away"):
    return explain.evolab_thesis("606be696ff199952", market, side, FIRED,
                                 dict(LOUD_FEATURES))


class TheThesisNamesTheMarketInWords(unittest.TestCase):

    def test_h2h_is_the_moneyline(self):
        thesis = _thesis()
        self.assertIn("Backing the away side of the moneyline because", thesis)
        self.assertNotIn("side of h2h", thesis)

    def test_every_scope_market_has_words(self):
        for key in ("h2h", "spreads", "totals", "h2h_1st_5_innings"):
            self.assertIn(key, explain.MARKET_PHRASE)
            self.assertNotIn("_", explain.MARKET_PHRASE[key])

    def test_an_unknown_market_falls_through_verbatim(self):
        """Never a guess: a key with no phrase prints as itself."""
        self.assertIn("side of weird_market", _thesis(market="weird_market"))


class TheSignalSentenceLeadsWithTheQuantity(unittest.TestCase):

    def test_the_quantity_comes_first_and_the_id_follows(self):
        thesis = _thesis()
        self.assertIn("(1) this lineup's top-of-order minus bottom-of-order", thesis)
        self.assertNotIn("(1) top_minus_bottom", thesis)
        self.assertIn("(top_minus_bottom;", thesis)


class TheClosingSentenceCarriesNoFieldNames(unittest.TestCase):

    def test_no_field_or_path_in_the_no_claim_sentence(self):
        for token in ("p_model", "edge_bps", "docs/", "genome"):
            self.assertNotIn(token, explain.NO_EDGE_CLAIM)

    def test_it_still_claims_nothing(self):
        self.assertFalse(explain.claims_edge(explain.NO_EDGE_CLAIM))
        self.assertFalse(explain.claims_edge(_thesis()))


if __name__ == "__main__":
    unittest.main()
