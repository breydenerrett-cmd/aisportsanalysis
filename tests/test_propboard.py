"""The shared prop board: the two settlement rules that can be silently wrong.

WHY THIS EXISTS
---------------
`scripts/_propboard.py` decides two things that no downstream number can
recover from if they are wrong, and both fail QUIETLY rather than loudly.

  1. **Whether a bet won.** A whole-number line pushes -- the book returns
     the stake. Scoring a push as an under win inflates the under arm, and
     the under arm is exactly what `docs/PREREG_UNDER_SIDE.md` was written to
     measure. Every line in today's capture is a half, so this would not have
     fired yet; it would have waited for the first integer line and then
     produced a wrong number that looked like a result.

  2. **Which price counts.** `devig()` returns the best price on BOTH sides.
     It read only the over until 2026-09-10, which drew every possible pick
     from one tail of the model's own error. A regression to one-sided
     reading would not crash anything -- it would just quietly halve the
     board and bias what remained.

Neither is arithmetic worth testing. Both are judgement calls that were made
once and must not drift back.
"""

from __future__ import annotations

import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARD = os.path.join(ROOT, "scripts", "_propboard.py")


def _load():
    spec = importlib.util.spec_from_file_location("_propboard", BOARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


board = _load()


def _batter(date, **stats):
    row = {"type": "batter", "player_name": "Test Batter", "date": date}
    row.update(stats)
    return row


class AWholeNumberLineIsRefused(unittest.TestCase):
    """A push is neither a win nor a loss, and guessing is not allowed."""

    def setUp(self):
        self.by_name = {"Test Batter": [_batter("2026-09-01", h=1,
                                                total_bases=1, hr=0, r=1)]}

    def test_a_half_line_settles_normally(self):
        resolved = board.resolve(self.by_name, "Test Batter", "2026-09-01",
                                 "batter_hits", 0.5)
        self.assertEqual(resolved, 1, "one hit clears a 0.5 line")

    def test_a_half_line_can_also_lose(self):
        resolved = board.resolve(self.by_name, "Test Batter", "2026-09-01",
                                 "batter_hits", 1.5)
        self.assertEqual(resolved, 0, "one hit does not clear a 1.5 line")

    def test_an_exact_landing_is_refused_not_scored_as_an_under(self):
        """THE ONE THAT MATTERS. One hit against a line of 1.0 is a PUSH.

        The tempting wrong answer is `1 > 1.0` is False, therefore the under
        won. That silently converts a refunded stake into a winning bet, and
        it does so only on the under side -- the side being measured.
        """
        resolved = board.resolve(self.by_name, "Test Batter", "2026-09-01",
                                 "batter_hits", 1.0)
        self.assertIsNone(resolved,
                          "a whole-number line pushes and must be refused")

    def test_whole_numbers_are_refused_even_when_the_outcome_is_not_a_push(self):
        """Three hits against a line of 1.0 is a clear over -- and still
        refused. The rule is about the LINE, not about how this particular
        game happened to land; a rule that inspected the outcome first would
        be deciding what to settle based on what happened."""
        by_name = {"Test Batter": [_batter("2026-09-01", h=3)]}
        self.assertIsNone(board.resolve(by_name, "Test Batter", "2026-09-01",
                                        "batter_hits", 1.0))

    def test_an_absent_batter_is_none_and_never_zero(self):
        """ABSENT IS NOT ZERO. A batter with no line did not go 0-for-4 --
        he may have been scratched or the game may not be ingested."""
        self.assertIsNone(board.resolve(self.by_name, "Nobody At All",
                                        "2026-09-01", "batter_hits", 0.5))
        self.assertIsNone(board.resolve(self.by_name, "Test Batter",
                                        "2026-09-02", "batter_hits", 0.5))

    def test_a_missing_stat_is_none_and_never_zero(self):
        """Same rule one level down: the batter played, but the column that
        settles this market is absent from his line."""
        by_name = {"Test Batter": [_batter("2026-09-01", h=2)]}
        self.assertIsNone(board.resolve(by_name, "Test Batter", "2026-09-01",
                                        "batter_total_bases", 1.5))

    def test_an_unknown_market_settles_nothing(self):
        self.assertIsNone(board.resolve(self.by_name, "Test Batter",
                                        "2026-09-01", "batter_moon_landings",
                                        0.5))


class BothSidesArePriced(unittest.TestCase):
    """`devig` reading one side is the bug docs/PREREG_UNDER_SIDE.md names."""

    BOOKS = {
        "alpha": {"Over": -110, "Under": -110},
        "beta": {"Over": +105, "Under": -125},
    }

    def test_the_best_price_is_returned_for_each_side_separately(self):
        fair, best = board.devig(self.BOOKS)
        self.assertEqual(len(fair), 2)
        self.assertIn("Over", best)
        self.assertIn("Under", best)
        self.assertEqual(best["Over"][0], 105,
                         "beta's +105 is the better over price")
        self.assertEqual(best["Over"][2], "beta")
        self.assertEqual(best["Under"][0], -110,
                         "alpha's -110 is the better under price")
        self.assertEqual(best["Under"][2], "alpha")

    def test_the_best_side_prices_may_come_from_different_books(self):
        """Line shopping is per side. A board that took both sides from one
        book would understate what was actually available."""
        _fair, best = board.devig(self.BOOKS)
        self.assertNotEqual(best["Over"][2], best["Under"][2])

    def test_a_one_sided_book_contributes_no_fair_probability(self):
        """A book quoting only the over has no margin to remove, so its
        raw price is not a fair probability and must not be averaged in."""
        fair, best = board.devig({"alpha": {"Over": -110}})
        self.assertEqual(fair, [])
        self.assertEqual(best, {})

    def test_a_pair_that_sums_below_the_floor_is_rejected(self):
        """Two sides summing under 100% is not a market a book would offer;
        it is a capture error, and de-vigging it would invent value."""
        fair, _best = board.devig({"alpha": {"Over": +200, "Under": +200}})
        self.assertEqual(fair, [], "a 66% book sum cannot be a real two-way")

    def test_the_fair_probability_has_the_margin_removed(self):
        """A -110/-110 pair is 52.4% each side raw, 50% each after de-vig.
        A gap measured against the raw price would partly BE the margin."""
        fair, _best = board.devig({"alpha": {"Over": -110, "Under": -110}})
        self.assertAlmostEqual(fair[0], 0.5, places=6)


class TheGatesAskDifferentQuestions(unittest.TestCase):
    """`assessable` needs BOTH, and conflating them re-admits home runs."""

    def test_home_runs_are_refused_because_no_fair_price_exists(self):
        """Home runs pass `publishable` -- the model measured fine -- and
        fail `deviggable`, because no book quotes the under. A gap there is
        measured against a raw price that still holds the whole margin."""
        from src.analysis import playerprops
        self.assertTrue(playerprops.publishable("batter_home_runs"))
        self.assertFalse(playerprops.deviggable("batter_home_runs"))
        self.assertFalse(board.assessable("batter_home_runs"))

    def test_a_market_the_model_is_bad_at_is_refused(self):
        self.assertFalse(board.assessable("batter_rbis"))

    def test_the_surviving_markets_are_the_ones_the_probes_report(self):
        for market in ("batter_hits", "batter_total_bases",
                       "batter_runs_scored"):
            self.assertTrue(board.assessable(market), market)

    def test_nothing_is_assessable_by_accident(self):
        self.assertFalse(board.assessable(""))
        self.assertFalse(board.assessable(None))


class ContractsKeepOnlyTheNewestQuote(unittest.TestCase):
    """A book that moved during the day is read where it ENDED."""

    ROWS = [
        {"market": "batter_hits", "game_date": "2026-09-01", "event_id": "e1",
         "player": "Test Batter", "line": 0.5, "side": "Over", "book": "alpha",
         "price": -110, "observed_utc": "2026-09-01T12:00:00Z"},
        {"market": "batter_hits", "game_date": "2026-09-01", "event_id": "e1",
         "player": "Test Batter", "line": 0.5, "side": "Over", "book": "alpha",
         "price": -130, "observed_utc": "2026-09-01T18:00:00Z"},
        {"market": "batter_hits", "game_date": "2026-09-01", "event_id": "e1",
         "player": "Test Batter", "line": 0.5, "side": "Under", "book": "alpha",
         "price": +105, "observed_utc": "2026-09-01T18:00:00Z"},
    ]

    def test_the_later_price_replaces_the_earlier_one(self):
        contracts = board.build_contracts(self.ROWS)
        self.assertEqual(len(contracts), 1)
        (books,) = contracts.values()
        self.assertEqual(books["alpha"]["Over"], -130)

    def test_a_stale_row_does_not_survive_as_a_second_book(self):
        """The failure to guard against: one book's morning and evening
        quotes counted as two books, manufacturing a consensus out of one
        opinion and clearing MIN_BOOKS on a single source."""
        contracts = board.build_contracts(self.ROWS)
        (books,) = contracts.values()
        self.assertEqual(len(books), 1, "one book, not two")

    def test_an_unassessable_market_never_reaches_the_board(self):
        rows = [dict(r, market="batter_rbis") for r in self.ROWS]
        self.assertEqual(len(board.build_contracts(rows)), 0)


if __name__ == "__main__":
    unittest.main()
