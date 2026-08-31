"""The Ranker gate, enforced structurally.

These tests exist so the gate cannot be removed by accident: while no
demonstrated edge exists, the Ranker publishes no bet recommendation, no
pick, and no edge language -- and a change to any of that fails here until
someone deliberately updates BOTH the evidence and this file.
"""

import unittest

from src.report import ranker

FULL_SECTION = {
    "sides": {
        "away": {"best_book": "book_a", "best_price": 105,
                 "consensus_probability": 0.49,
                 "improvement_points": 0.012,
                 "improvement_return_pct": 2.4},
        "home": {"best_book": "book_b", "best_price": -108,
                 "consensus_probability": 0.51,
                 "improvement_points": -0.005,
                 "improvement_return_pct": -0.9},
    },
    "dispersion": {"books": 8, "home_probability_range": 0.02},
    "label": "price improvement / line-shopping value",
}
INDEX = {("CIN", "NYM", "2026-08-31"): FULL_SECTION}


class GateTests(unittest.TestCase):
    def test_engine_two_is_empty(self):
        """THE gate. Twenty-four hypotheses, zero survivors: there is no
        predictive engine, and this constant saying otherwise must be a
        deliberate, evidence-carrying diff."""
        self.assertIsNone(ranker.ENGINE2)

    def test_the_page_never_recommends_while_the_engine_is_empty(self):
        page = ranker.render(INDEX).lower()
        # The forbidden vocabulary appears in the page ONLY inside explicit
        # negations. Assert each negation is present, strip them, then
        # demand the vocabulary is gone -- so a positive use can never hide
        # behind the banner's honest sentences.
        negations = ("nothing here is a recommendation",
                     "no predictive edge exists",
                     "not expected value and not a prediction")
        stripped = page
        for negation in negations:
            self.assertIn(negation, stripped)
            stripped = stripped.replace(negation, "")
        for forbidden in ("recommend", "best bet", "top pick", "our pick",
                          "bet this", "edge", "expected value", "+ev",
                          "units"):
            self.assertNotIn(forbidden, stripped,
                             f"the empty-engine page says {forbidden!r}")

    def test_the_banner_states_the_null_result_plainly(self):
        page = ranker.render(INDEX)
        self.assertIn("No predictive edge exists", page)
        self.assertIn("Nothing here is a recommendation", page)

    def test_an_empty_board_is_empty_not_padded(self):
        page = ranker.render({})
        self.assertIn("empty rather than", page)
        self.assertNotIn("<table>", page)


class ListTests(unittest.TestCase):
    def test_rows_sort_by_improvement_and_skip_thin_boards(self):
        index = dict(INDEX)
        index[("BOS", "NYY", "2026-08-31")] = {"skipped": "2 books"}
        rows = ranker.rows(index)
        self.assertEqual([r["side"] for r in rows], ["away", "home"])
        self.assertEqual(rows[0]["improvement_points"], 0.012)
        self.assertNotIn("BOS", [r["away"] for r in rows])

    def test_the_page_shows_the_priced_side_without_advising_it(self):
        page = ranker.render(INDEX)
        self.assertIn("CIN @ NYM", page)
        self.assertIn("book_a", page)
        self.assertIn("+105", page)


if __name__ == "__main__":
    unittest.main()
