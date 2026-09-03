import dataclasses
import unittest

from src.board.record import PriceObservation
from src.core.asof import FieldObservation, Snapshot as AsOfSnapshot
from src.engine.snapshot import (
    FORBIDDEN_PRICE_NAMES, PointMeta, PriceBlindSnapshot, PricedBoard,
)


def _po(selection_id, side, price, line=None, book="fanduel",
        market_key="h2h", subject_id=None):
    return PriceObservation(
        sport="mlb", event_id="e1", game_pk=123, market_key=market_key,
        selection_id=selection_id, side=side, subject_kind=None,
        subject_id=subject_id, line=line, book=book, price_american=price,
        observed_utc="2023-04-11T20:00:00Z", book_last_update=None,
        known_at="2023-04-11T20:00:00Z", known_at_grade="A",
        capture_id="c1", source="test", region="us",
        provider_market_key=market_key,
    )


class TestPriceBlindSnapshotStructural(unittest.TestCase):
    def test_no_price_shaped_field_declared(self):
        names = {f.name for f in dataclasses.fields(PriceBlindSnapshot)}
        for forbidden in FORBIDDEN_PRICE_NAMES:
            self.assertNotIn(
                forbidden, names,
                f"{forbidden!r} must not be a declared field")

    def test_getattr_refuses_every_forbidden_name(self):
        snap = PriceBlindSnapshot(
            game_pk="1", t="2023-04-11T20:00:00Z", point_class="LATE_BOARD",
            features={"away_x": 1.0, "home_x": 2.0})
        for name in sorted(FORBIDDEN_PRICE_NAMES):
            with self.assertRaises(AttributeError):
                getattr(snap, name)

    def test_reflection_over_dir_finds_no_price_value(self):
        """A PROPOSE-side system reflecting over every live attribute name
        can never find a price -- either the name is absent from `dir()`
        entirely, or accessing it raises."""
        snap = PriceBlindSnapshot(
            game_pk="1", t="2023-04-11T20:00:00Z", point_class="LATE_BOARD",
            features={"away_x": 1.0, "home_x": 2.0})
        for name in dir(snap):
            if name.startswith("_"):
                continue
            try:
                value = getattr(snap, name)
            except AttributeError:
                continue
            # Every attribute that DOES resolve must not itself be (or
            # contain) a PriceObservation / price-shaped payload.
            self.assertNotIsInstance(value, PriceObservation)

    def test_differential(self):
        snap = PriceBlindSnapshot(
            game_pk="1", t="t", point_class="LATE_BOARD",
            features={"away_x": 3.0, "home_x": 1.0})
        self.assertEqual(snap.differential("x"), 2.0)
        self.assertIsNone(snap.differential("missing"))

    def test_from_asof_folds_grade_into_assumption_exposure(self):
        asof_snap = AsOfSnapshot(
            game_key="123", t="2023-04-11T20:00:00Z",
            fields={
                "home_lineup": FieldObservation(
                    value=["a"], source="lineups_watch",
                    observed_utc="2023-04-11T19:00:00Z", known_at=None,
                    known_at_grade="D"),
            })
        snap = PriceBlindSnapshot.from_asof(
            game_pk="123", t="2023-04-11T20:00:00Z", point_class="LATE_BOARD",
            features={}, as_of_snapshot=asof_snap)
        self.assertEqual(snap.assumption_exposure, {"D:home_lineup": 1})


class TestPricedBoard(unittest.TestCase):
    def setUp(self):
        self.home = "aaaaaaaaaaaaaaaa"
        self.away = "bbbbbbbbbbbbbbbb"
        self.rows = (
            _po(self.home, "home", -150, book="a"),
            _po(self.away, "away", 130, book="a"),
            _po(self.home, "home", -140, book="b"),
            _po(self.away, "away", 120, book="b"),
        )
        self.board = PricedBoard.from_price_observations("123", "t", self.rows)

    def test_selections(self):
        self.assertEqual(self.board.selections(), tuple(sorted(
            [self.home, self.away])))

    def test_best_picks_most_favorable_decimal(self):
        best = self.board.best(self.away)
        self.assertEqual(best.book, "a")  # +130 > +120

    def test_consensus_devigs_across_common_books(self):
        consensus = self.board.consensus(self.home, min_books=1)
        self.assertIsNotNone(consensus)
        self.assertEqual(consensus.n_books, 2)
        self.assertTrue(0.0 < consensus.fair_probability < 1.0)

    def test_consensus_undefined_below_min_books(self):
        consensus = self.board.consensus(self.home, min_books=5)
        self.assertIsNone(consensus)

    def test_consensus_undefined_with_no_opposite_side(self):
        board = PricedBoard.from_price_observations(
            "123", "t", (_po(self.home, "home", -150, book="a"),))
        self.assertIsNone(board.consensus(self.home))

    def test_friction_reports_book_count_and_dispersion(self):
        friction = self.board.friction(self.home)
        self.assertEqual(friction.book_count, 2)
        self.assertGreaterEqual(friction.dispersion, 0.0)


if __name__ == "__main__":
    unittest.main()
