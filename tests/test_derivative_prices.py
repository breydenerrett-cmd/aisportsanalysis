"""Guards for src/analysis/derivative_prices.py.

The value of this module is entirely in what it REFUSES to do, so most of
these tests assert a refusal: it must not pool two different lines into one
consensus, must not lower the six-book floor because a market is thinly
quoted, must not drop a thin contract silently, and must not invent a label
for a market it does not know how to phrase. A regression in any of those
would not crash anything -- it would quietly produce a confident-looking
edge that is not real, which is the failure this whole product exists to
avoid.
"""

import unittest

from src.analysis import derivative_prices as dp
from src.analysis import prices


def deriv_row(**kw):
    row = {
        "game_date": "2026-09-07",
        "event_id": "evt1",
        "market": "totals_1st_5_innings",
        "line": "4.5",
        "team": None,
        "side": "Over",
        "price": -110,
        "book": "fanduel",
        "observed_utc": "2026-09-07T14:00:00Z",
        "commence_time": "2026-09-07T17:00:00Z",
        "away_team": "Chicago Cubs",
        "home_team": "Milwaukee Brewers",
    }
    row.update(kw)
    return row


def two_sided_board(books, *, line="4.5", market="totals_1st_5_innings",
                    over=-110, under=-110, book_prefix="book", **kw):
    """One instant, `books` books, both sides quoted by each.

    `book_prefix` matters: a test that builds two boards to prove they are
    NOT pooled must give them distinct book names, or pooling collapses
    them onto the same keys and the depth never grows -- which would make
    the test pass whether or not the pooling bug is present.
    """
    rows = []
    for i in range(books):
        for side, price in (("Over", over), ("Under", under)):
            rows.append(deriv_row(book=f"{book_prefix}{i}", side=side,
                                  price=price, line=line, market=market, **kw))
    return rows


class FloorTests(unittest.TestCase):
    def test_below_the_floor_is_reported_not_hidden(self):
        rows = dp.candidates_for_date(
            "2026-09-07", derivative_rows=two_sided_board(3), prop_rows=[])
        self.assertTrue(rows, "a thin contract must still be returned")
        for row in rows:
            self.assertIsNone(row["consensus_probability"])
            self.assertIsNone(row["best_price"])
            self.assertIn("3 book(s)", row["thin_reason"])
            self.assertIn(str(prices.MIN_BOOKS), row["thin_reason"])

    def test_the_floor_is_not_lowered_for_derivatives(self):
        """Five books is below the floor for a first-five total exactly as
        it is for a moneyline. Fewer books quote these markets; that is a
        reason to say so, never a reason to move the line."""
        rows = dp.candidates_for_date(
            "2026-09-07",
            derivative_rows=two_sided_board(prices.MIN_BOOKS - 1),
            prop_rows=[])
        self.assertTrue(all(r["consensus_probability"] is None for r in rows))

    def test_at_the_floor_it_prices(self):
        rows = dp.candidates_for_date(
            "2026-09-07", derivative_rows=two_sided_board(prices.MIN_BOOKS),
            prop_rows=[])
        self.assertTrue(rows)
        for row in rows:
            self.assertIsNotNone(row["consensus_probability"])
            self.assertIsNone(row["thin_reason"])
            self.assertEqual(row["books"], prices.MIN_BOOKS)


class LineIdentityTests(unittest.TestCase):
    def test_two_lines_are_two_contracts_never_one_consensus(self):
        """Over 4.5 and Over 5.0 are different bets. Pooling them would
        average two propositions and call the result a fair price."""
        # DISTINCT book names per line, so that pooling would actually show
        # up as an eight-book board rather than collapsing onto shared keys.
        board = (two_sided_board(4, line="4.5", book_prefix="a")
                 + two_sided_board(4, line="5.5", book_prefix="b"))
        rows = dp.candidates_for_date(
            "2026-09-07", derivative_rows=board, prop_rows=[])
        # Eight books across the two lines, four on each -- so BOTH
        # contracts sit below the floor and neither is priced. Pooling would
        # have produced one priced eight-book row instead.
        self.assertTrue(rows)
        self.assertTrue(all(r["consensus_probability"] is None for r in rows),
                        "lines were pooled into one consensus")
        self.assertEqual({r["books"] for r in rows}, {4})
        self.assertEqual({str(r["line"]) for r in rows}, {"4.5", "5.5"})

    def test_team_totals_separate_by_team(self):
        board = (two_sided_board(4, market="team_totals", team="Chicago Cubs",
                                 book_prefix="a")
                 + two_sided_board(4, market="team_totals",
                                   team="Milwaukee Brewers", book_prefix="b"))
        rows = dp.candidates_for_date(
            "2026-09-07", derivative_rows=board, prop_rows=[])
        self.assertEqual({r["books"] for r in rows}, {4})
        self.assertEqual({r["team"] for r in rows},
                         {"Chicago Cubs", "Milwaukee Brewers"})


class InstantTests(unittest.TestCase):
    def test_only_the_newest_instant_counts(self):
        """Mixing instants compares a stale best against a fresh consensus
        and manufactures improvement out of latency."""
        old = two_sided_board(6, observed_utc="2026-09-07T10:00:00Z")
        new = two_sided_board(2, observed_utc="2026-09-07T14:00:00Z")
        rows = dp.candidates_for_date(
            "2026-09-07", derivative_rows=old + new, prop_rows=[])
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row["books"], 2, "an older instant was pooled in")
            self.assertIsNotNone(row["thin_reason"])

    def test_a_book_quoting_one_side_only_is_not_counted(self):
        """A one-sided quote cannot be de-vigged; counting it would inflate
        the depth behind the consensus."""
        board = two_sided_board(6)
        board.append(deriv_row(book="halfbook", side="Over", price=-105))
        rows = dp.candidates_for_date(
            "2026-09-07", derivative_rows=board, prop_rows=[])
        self.assertTrue(rows)
        self.assertTrue(all(r["books"] == 6 for r in rows))


class LabelTests(unittest.TestCase):
    def test_known_markets_are_phrased_as_bets(self):
        cases = {
            "totals_1st_5_innings": "First 5: Over 4.5",
            "team_totals": "Chicago Cubs team total Over 4.5",
        }
        for market, expected in cases.items():
            team = "Chicago Cubs" if market == "team_totals" else None
            rows = dp.candidates_for_date(
                "2026-09-07",
                derivative_rows=two_sided_board(6, market=market, team=team),
                prop_rows=[])
            texts = {r["wager_text"] for r in rows}
            self.assertIn(expected, texts, f"{market} -> {texts}")

    def test_an_unknown_market_is_dropped_not_guessed(self):
        rows = dp.candidates_for_date(
            "2026-09-07",
            derivative_rows=two_sided_board(6, market="pitcher_outs_recorded"),
            prop_rows=[])
        self.assertEqual(rows, [], "an unsupported market was rendered anyway")

    def test_a_three_way_market_is_dropped_not_forced_into_a_pair(self):
        board = two_sided_board(6)
        board.append(deriv_row(book="book0", side="Push", price=+900))
        rows = dp.candidates_for_date(
            "2026-09-07", derivative_rows=board, prop_rows=[])
        self.assertEqual(rows, [])


class PropTests(unittest.TestCase):
    def prop_rows(self, books, point=7.5):
        return [{
            "game_date": "2026-09-07", "event_id": "evt1",
            "market": dp.PROP_MARKET, "player": "Jesus Luzardo",
            "point": point, "book": f"book{i}",
            "over_price": 110, "under_price": -130,
            "observed_utc": "2026-09-07T14:00:00Z",
            "commence_time": "2026-09-07T17:00:00Z",
            "away_team": "Atlanta Braves",
            "home_team": "Philadelphia Phillies",
        } for i in range(books)]

    def test_a_priced_prop_is_phrased_as_a_bet(self):
        rows = dp.candidates_for_date(
            "2026-09-07", derivative_rows=[],
            prop_rows=self.prop_rows(prices.MIN_BOOKS))
        texts = {r["wager_text"] for r in rows}
        self.assertIn("Jesus Luzardo Over 7.5 strikeouts", texts)
        self.assertIn("Jesus Luzardo Under 7.5 strikeouts", texts)

    def test_a_thin_prop_states_its_reason(self):
        rows = dp.candidates_for_date(
            "2026-09-07", derivative_rows=[], prop_rows=self.prop_rows(2))
        self.assertTrue(rows)
        self.assertTrue(all(r["thin_reason"] for r in rows))

    def test_two_points_are_two_contracts(self):
        rows = dp.candidates_for_date(
            "2026-09-07", derivative_rows=[],
            prop_rows=self.prop_rows(4, point=6.5) + self.prop_rows(4, point=7.5))
        self.assertTrue(all(r["books"] == 4 for r in rows))


class ModelHonestyTests(unittest.TestCase):
    def test_no_row_ever_carries_a_model_probability(self):
        rows = dp.candidates_for_date(
            "2026-09-07", derivative_rows=two_sided_board(8), prop_rows=[])
        self.assertTrue(rows)
        for row in rows:
            self.assertNotIn("p_model", row)
            self.assertNotIn("edge_bps", row)
            self.assertNotIn("win_probability", row)


if __name__ == "__main__":
    unittest.main()
