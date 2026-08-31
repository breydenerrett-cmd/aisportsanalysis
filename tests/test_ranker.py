"""The Ranker gate, enforced structurally.

These tests exist so the gate cannot be removed by accident: while no
demonstrated edge exists, the Ranker publishes no bet recommendation, no
pick, and no edge language -- and a change to any of that fails here until
someone deliberately updates BOTH the evidence and this file.
"""

import unittest

import src.analysis as analysis
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


ALL_NEGATIVE_INDEX = {
    ("MIA", "WSH", "2026-08-31"): {
        "sides": {
            "home": {"best_book": "williamhill_us", "best_price": 110,
                     "consensus_probability": 0.474,
                     "improvement_points": -0.0022,
                     "improvement_return_pct": -0.46},
            "away": {"best_book": "betus", "best_price": -117,
                     "consensus_probability": 0.526,
                     "improvement_points": -0.0132,
                     "improvement_return_pct": -2.45},
        },
        "dispersion": {"books": 11, "home_probability_range": 0.01},
        "label": "price improvement / line-shopping value",
    },
}


class BannerTellsTheTruthAboutTheSign(unittest.TestCase):
    """The banner asserted a fact about its own rows that was false for all of
    them.

    It read "Everything below is PRICE IMPROVEMENT -- where the best available
    price beats the market's own consensus", above a real board of twenty-four
    rows every one of which was NEGATIVE. That is arithmetic, not a bad night:
    the best available price still carries vig, the consensus it is measured
    against does not. Sorted best-first, the top row then read as the day's
    best opportunity while being 0.46% worse than fair.
    """

    def test_the_banner_no_longer_promises_a_sign(self):
        self.assertNotIn("where the best available price beats", ranker.BANNER)
        self.assertIn("normally NEGATIVE", ranker.BANNER)

    def test_an_all_negative_board_says_nothing_on_it_is_an_improvement(self):
        page = ranker.render(ALL_NEGATIVE_INDEX)
        self.assertIn("Not one side on today&#x27;s board beats", page)
        self.assertIn("none of them is a price improvement", page)

    def test_every_row_states_its_own_side_of_zero(self):
        page = ranker.render(ALL_NEGATIVE_INDEX)
        self.assertEqual(page.count("worse than consensus"), 2)
        self.assertNotIn("beats consensus", page)

    def test_a_board_with_a_winner_marks_the_winner_and_keeps_the_losers(self):
        page = ranker.render(INDEX)
        self.assertIn("beats consensus", page)
        self.assertIn("worse than consensus", page)
        self.assertNotIn("Not one side on today", page)

    def test_negative_rows_are_never_dropped_to_make_the_board_look_better(self):
        # Hiding them would make an all-negative board render as an empty one,
        # which reads as "no data" rather than "no improvement".
        page = ranker.render(ALL_NEGATIVE_INDEX)
        self.assertIn("MIA @ WSH", page)
        self.assertNotIn("No multi-book board is thick enough", page)


class ImprovementColumnUsesTheUnitsItsHeadingClaims(unittest.TestCase):

    def test_points_are_points_not_fractions(self):
        page = ranker.render(ALL_NEGATIVE_INDEX)
        self.assertIn("win-prob points", page)
        self.assertIn("-0.22", page)
        self.assertNotIn("-0.0022", page)

    def test_a_missing_number_is_a_dash_not_a_confident_zero(self):
        index = {("A", "B", "2026-08-31"): {
            "sides": {"away": {"best_book": "b", "best_price": 100}},
            "dispersion": {"books": 9}, "label": "x"}}
        page = ranker.render(index)
        self.assertNotIn("+0.0000", page)
        self.assertNotIn("+0.00%", page)
        self.assertIn("--", page)


class TheCountMatchesEverywhereElse(unittest.TestCase):
    """13 / 24 / 27 for one fact, two of them on one page. Now one constant."""

    def test_the_banner_reads_the_shared_constant(self):
        self.assertIn(analysis.HYPOTHESES_TESTED_WORD, ranker.BANNER)
        self.assertIn(analysis.HYPOTHESIS_FAMILIES_WORD, ranker.BANNER)

    def test_no_stale_count_survives_in_the_banner(self):
        for stale in ("Twenty-four", "twenty-four", "Thirteen", "thirteen",
                      "three research families"):
            self.assertNotIn(stale, ranker.BANNER)
