import dataclasses
import unittest

from src.board.record import PriceObservation
from src.core.asof import FieldObservation, Snapshot as AsOfSnapshot
from src.engine.snapshot import (
    FORBIDDEN_PRICE_NAMES, PointMeta, PriceBlindSnapshot, PricedBoard,
)


def _po(selection_id, side, price, line=None, book="fanduel",
        market_key="h2h", subject_id=None,
        observed_utc="2023-04-11T20:00:00Z"):
    return PriceObservation(
        sport="mlb", event_id="e1", game_pk=123, market_key=market_key,
        selection_id=selection_id, side=side, subject_kind=None,
        subject_id=subject_id, line=line, book=book, price_american=price,
        observed_utc=observed_utc, book_last_update=None,
        known_at=observed_utc, known_at_grade="A",
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


class TestStaleAndHistoricalQuotesExcluded(unittest.TestCase):
    """Regressions for bugs #3 (book_count counts rows, not books), #4
    (dispersion mixes all rows through t), and #6 (best() returns the best
    price EVER seen, not at t): a book that repriced several times, and a
    book that went stale, must each count once -- as their own latest
    quote at t -- not as every row they ever posted."""

    def setUp(self):
        self.home = "aaaaaaaaaaaaaaaa"
        self.away = "bbbbbbbbbbbbbbbb"
        self.t = "2023-04-11T20:00:00Z"
        self.rows = (
            # book "a" quoted three times; only the LATEST (-150, at
            # 19:50) should count -- the earlier -200/-180 rows are the
            # exact shape of the reported book_count=575-vs-11 bug.
            _po(self.home, "home", -200, book="a",
                observed_utc="2023-04-11T10:00:00Z"),
            _po(self.home, "home", -180, book="a",
                observed_utc="2023-04-11T18:00:00Z"),
            _po(self.home, "home", -150, book="a",
                observed_utc="2023-04-11T19:50:00Z"),
            # book "b" quoted once, hours before t -- gone stale by t and
            # must be excluded from book_count/dispersion/best entirely.
            _po(self.home, "home", -140, book="b",
                observed_utc="2023-04-11T10:00:00Z"),
            # book "c" quoted once, fresh -- the most bettor-favorable
            # PRESENT price, even though it is neither the highest price
            # ever posted (that's -200/"a"'s oldest row) nor the most
            # recent absolute price update overall.
            _po(self.home, "home", -130, book="c",
                observed_utc="2023-04-11T19:59:00Z"),
            _po(self.away, "away", 120, book="a",
                observed_utc="2023-04-11T19:50:00Z"),
            _po(self.away, "away", 110, book="c",
                observed_utc="2023-04-11T19:59:00Z"),
        )
        self.board = PricedBoard.from_price_observations(
            "123", self.t, self.rows)

    def test_book_count_is_distinct_fresh_books_not_row_count(self):
        friction = self.board.friction(self.home, as_of_utc=self.t)
        # 5 rows total for "home", but only 2 books ("a", "c") are fresh
        # at t -- "b" is stale.
        self.assertEqual(friction.book_count, 2)

    def test_dispersion_uses_only_fresh_latest_quotes(self):
        friction = self.board.friction(self.home, as_of_utc=self.t)
        # Across a's LATEST (-150) and c's (-130) only -- NOT a's stale
        # -200/-180 history, NOT b's stale -140.
        from src.core import odds as odds_math
        expected = (odds_math.american_to_probability(-150)
                    - odds_math.american_to_probability(-130))
        self.assertAlmostEqual(friction.dispersion, expected, places=9)

    def test_best_is_the_best_fresh_price_not_the_best_ever_seen(self):
        best = self.board.best(self.home)
        self.assertIsNotNone(best)
        # -130 (book c, fresh) pays out more than -150 (book a's latest);
        # -200 (book a's stale HISTORY) is the best price ever posted but
        # must never be returned.
        self.assertEqual(best.book, "c")
        self.assertEqual(best.price_american, -130)

    def test_stale_book_is_excluded_from_best_entirely(self):
        # Only book "b" quotes the selection at all in a variant board --
        # its sole quote is stale by t, so best() must be None, not the
        # long-dead -140 price.
        board = PricedBoard.from_price_observations("123", self.t, (
            _po(self.home, "home", -140, book="b",
                observed_utc="2023-04-11T10:00:00Z"),
        ))
        self.assertIsNone(board.best(self.home))


if __name__ == "__main__":
    unittest.main()
