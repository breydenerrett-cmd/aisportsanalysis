"""Tests for src/model/selections.py.

TestTheLabel is the important one. The results store is a CSV, so the home-win
label arrives as the STRING "0" or "1" -- and bool("0") is True. Coercing with
bool() made every selection's outcome read as "did we pick the home side", which
produced a 9.6-point apparent edge on a detector that mostly picks home teams.
Nothing raised, every number was plausible, and the entire first discovery run
was wrong.
"""

import unittest

from src.detect import base, detectors
from src.model import pointintime as pit
from src.model import selections


class TestTheLabel(unittest.TestCase):

    def test_the_string_zero_is_a_loss_not_a_win(self):
        # The whole bug in one line.
        self.assertEqual(selections._label("0"), 0)
        self.assertTrue(bool("0"))

    def test_string_and_integer_labels_agree(self):
        for text, number in (("0", 0), ("1", 1)):
            self.assertEqual(selections._label(text), selections._label(number))

    def test_booleans_are_accepted(self):
        self.assertEqual(selections._label(True), 1)
        self.assertEqual(selections._label(False), 0)

    def test_unrecognisable_values_are_none_rather_than_guessed(self):
        # A game that cannot be scored must be counted unresolved, never
        # silently assigned an outcome.
        for value in (None, "", "x", 2, -1, "maybe"):
            self.assertIsNone(selections._label(value), repr(value))

    def test_a_losing_home_pick_is_a_loss(self):
        # The end-to-end statement the bug violated.
        home_won = selections._label("0")
        self.assertFalse(bool(home_won))
        self.assertTrue(not home_won)


class TestCleanDetectorsOnly(unittest.TestCase):

    def setUp(self):
        self._saved = base.registry()
        base.clear_registry()
        detectors.register_defaults()

    def tearDown(self):
        base.clear_registry()
        for detector in self._saved.values():
            base.register(detector)

    def test_leaky_detectors_are_excluded(self):
        chosen = {d.name for d in selections.clean_detectors(base.registry())}
        for name in ("platoon_mismatch", "pitch_mix_mismatch",
                     "thin_matchup_history", "lineup_vs_starter"):
            self.assertNotIn(name, chosen)

    def test_clean_detectors_are_included(self):
        chosen = {d.name for d in selections.clean_detectors(base.registry())}
        self.assertIn("starter_mismatch", chosen)
        self.assertIn("travel_load", chosen)

    def test_the_whitelist_excludes_leaky_sections_by_construction(self):
        # It is not enough for the detector to be clean if the dossier hands it
        # a leaky section anyway.
        for name in ("splits", "arsenals", "matchup_history"):
            self.assertNotIn(name, selections.HISTORICAL_SECTIONS)
            self.assertEqual(pit.input_status(name)["status"], pit.LEAKY)


class TestConsensusPricing(unittest.TestCase):

    def books(self, *pairs):
        return [{"key": f"b{i}", "markets": [{"key": "h2h", "outcomes": [
            {"name": "AWAY", "price": away}, {"name": "HOME", "price": home}]}]}
            for i, (away, home) in enumerate(pairs)]

    def test_fair_probabilities_are_devigged_and_sum_to_one(self):
        fair = selections._fair(self.books((150, -170)), "HOME", "AWAY")
        self.assertAlmostEqual(fair["away_fair"] + fair["home_fair"], 1.0, places=6)

    def test_the_consensus_averages_across_books(self):
        # One book's number is that book's opinion plus its margin. A base-rate
        # control measured against a single quote moves with whichever book
        # happened to be listed first.
        fair = selections._fair(self.books((150, -170), (160, -180)),
                                "HOME", "AWAY")
        self.assertEqual(fair["books"], 2)

    def test_the_best_price_per_side_is_kept_not_the_average(self):
        # A bet gets the best available number, not the mean of the board.
        fair = selections._fair(self.books((150, -170), (160, -160)),
                                "HOME", "AWAY")
        self.assertEqual(fair["away_price"], 160)
        self.assertEqual(fair["home_price"], -160)

    def test_every_quote_is_kept_for_the_stale_book_detector(self):
        # Handing it a single consensus number silently produced zero
        # selections on the first run.
        fair = selections._fair(self.books((150, -170), (160, -180)),
                                "HOME", "AWAY")
        self.assertEqual(len(fair["quotes"]), 2)

    def test_an_unquotable_market_is_none_rather_than_a_default(self):
        self.assertIsNone(selections._fair([], "HOME", "AWAY"))

    def test_a_book_missing_one_side_is_skipped(self):
        books = [{"key": "b", "markets": [{"key": "h2h", "outcomes": [
            {"name": "AWAY", "price": 150}]}]}]
        self.assertIsNone(selections._fair(books, "HOME", "AWAY"))


class TestDateIndexing(unittest.TestCase):

    def test_both_candidate_dates_are_indexed_for_a_late_start(self):
        # A west-coast night game's UTC date is the day after its official date,
        # and guessing one would drop those games from every evaluation.
        dates = selections._candidate_dates("2026-08-29T02:10:00Z")
        self.assertIn("2026-08-29", dates)
        self.assertIn("2026-08-28", dates)

    def test_an_unparseable_time_yields_no_dates(self):
        self.assertEqual(selections._candidate_dates("not a time"), [])


if __name__ == "__main__":
    unittest.main()
