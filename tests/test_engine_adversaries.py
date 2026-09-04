import unittest

from src.engine.adversaries import (
    DEFAULT_ADVERSARIES, DegradedInformation, PriceMovedAgainst, StaleBook,
    ThinBoard,
)
from src.engine.analyze import FATAL, MAJOR, Candidate, Proposal


def _candidate(**kw):
    base = dict(
        proposal=Proposal(system_id="s", system_version="1",
                           market_key="h2h", side="home", p_model=0.6,
                           p_model_provenance="model_derived"),
        selection_id="sel1", consensus_fair=0.55, books_at_decision=3,
        friction={"vig": 0.02, "book_count": 3, "staleness_seconds": 60,
                  "dispersion": 0.01},
        price_american=-150, edge_bps=100,
    )
    base.update(kw)
    return Candidate(**base)


class TestStaleBook(unittest.TestCase):
    def test_fresh_price_no_veto(self):
        adv = StaleBook(max_staleness_seconds=1800)
        cargs = adv.attack(_candidate(), None, None)
        self.assertEqual(cargs, ())

    def test_stale_price_is_fatal_with_registered_cause(self):
        adv = StaleBook(max_staleness_seconds=1800)
        cand = _candidate(friction={"vig": 0.02, "book_count": 3,
                                    "staleness_seconds": 5000,
                                    "dispersion": 0.01})
        cargs = adv.attack(cand, None, None)
        self.assertEqual(len(cargs), 1)
        self.assertEqual(cargs[0].severity, FATAL)
        self.assertEqual(cargs[0].cause, StaleBook.CAUSE)
        self.assertEqual(cargs[0].adversary_id, "stale_book")


class TestThinBoard(unittest.TestCase):
    def test_enough_books_no_veto(self):
        adv = ThinBoard(min_books=2)
        cargs = adv.attack(_candidate(books_at_decision=3), None, None)
        self.assertEqual(cargs, ())

    def test_too_few_books_is_fatal(self):
        adv = ThinBoard(min_books=3)
        cargs = adv.attack(_candidate(books_at_decision=1), None, None)
        self.assertEqual(len(cargs), 1)
        self.assertEqual(cargs[0].severity, FATAL)
        self.assertEqual(cargs[0].cause, ThinBoard.CAUSE)


class TestPriceMovedAgainst(unittest.TestCase):
    def test_no_reference_no_veto(self):
        adv = PriceMovedAgainst()
        cargs = adv.attack(_candidate(selection_id="sel1"), None, None)
        self.assertEqual(cargs, ())

    def test_improved_price_no_veto(self):
        adv = PriceMovedAgainst(reference_prices={"sel1": -160})
        cargs = adv.attack(_candidate(selection_id="sel1", price_american=-150),
                            None, None)
        self.assertEqual(cargs, ())

    def test_worse_price_is_major(self):
        adv = PriceMovedAgainst(reference_prices={"sel1": -110})
        cargs = adv.attack(_candidate(selection_id="sel1", price_american=-150),
                            None, None)
        self.assertEqual(len(cargs), 1)
        self.assertEqual(cargs[0].severity, MAJOR)
        self.assertEqual(cargs[0].cause, PriceMovedAgainst.CAUSE)


class TestDegradedInformation(unittest.TestCase):
    def _snapshot(self, exposure):
        class _Snap:
            assumption_exposure = exposure
        return _Snap()

    def test_all_sentinel_fields_grade_a_no_veto(self):
        adv = DegradedInformation()
        exposure = {f"A:{f}": 1 for f in adv.sentinel_fields}
        cargs = adv.attack(_candidate(), self._snapshot(exposure), None)
        self.assertEqual(cargs, ())

    def test_missing_sentinel_field_is_major_with_replay_label(self):
        adv = DegradedInformation()
        exposure = {}  # nothing present at all
        cargs = adv.attack(_candidate(), self._snapshot(exposure), None)
        self.assertEqual(len(cargs), 1)
        self.assertEqual(cargs[0].severity, MAJOR)
        self.assertEqual(cargs[0].cause, DegradedInformation.CAUSE)
        self.assertIn("DEGRADED_INFORMATION", cargs[0].detail)

    def test_grade_d_sentinel_field_is_major(self):
        adv = DegradedInformation()
        exposure = {f"D:{f}": 1 for f in adv.sentinel_fields}
        cargs = adv.attack(_candidate(), self._snapshot(exposure), None)
        self.assertEqual(len(cargs), 1)
        self.assertEqual(cargs[0].severity, MAJOR)


class TestDefaultRoster(unittest.TestCase):
    def test_default_adversaries_has_all_four_with_unique_causes(self):
        self.assertEqual(len(DEFAULT_ADVERSARIES), 4)
        ids = {a.id for a in DEFAULT_ADVERSARIES}
        self.assertEqual(
            ids, {"stale_book", "thin_board", "price_moved_against",
                  "degraded_information"})
        causes = {a.CAUSE for a in DEFAULT_ADVERSARIES}
        self.assertEqual(len(causes), 4, "every adversary must register a "
                          "distinct cause string")


if __name__ == "__main__":
    unittest.main()
