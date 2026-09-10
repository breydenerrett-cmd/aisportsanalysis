"""A price board may never de-vig two bets that are not each other's complement.

WHY THIS FILE EXISTS
---------------------
This is the arithmetic behind the 2026-09-09 incident, and it took two
passes to find because the first diagnosis was wrong.

`_derivative_contracts` groups on (event_id, market, line, team). Every
spread row arrives with `team` null, and in alternate_spreads EACH SIDE
CARRIES ITS OWN LINE -- so `NYM -2.5` and `MIA -2.5` collapsed into one
group and were handed to `_pair_sides` as the two sides of one two-way
market. They are not. The complement of NYM -2.5 is MIA **+2.5**; two teams
cannot both be -2.5.

`odds.devig` normalises to 1.0 unconditionally, so the pair was rescaled in
whichever direction it was wrong and BOTH legs came out fabricated:

    Tigers -8.5 (+1400) & Twins -8.5 (+1500)   implied sum 0.129
      -> scaled up ~8x; board claimed +45 and +42 points of "value"
         on two outcomes that cannot both happen
    NYM +2.5 (-310) & MIA +2.5 (-330)          implied sum 1.523
      -> scaled down; board claimed -26 points OVERPRICED

387 such pairs existed on that one date. A reader saw one of them, read
"+286 crazy value" as a system recommendation, and told the owner the
product had called a great bet.

That incident was recorded at the time as "a price-gap flag on a thin
book". It was not. The book was fine; the number was invented. Removing the
TOP PLAY label from the card -- which is what shipped first -- left the
number that made it dangerous.

Two independent guards, because they fail differently:
  * spreads are not paired at all until the pairing is correct
  * ANY market whose two legs sum below 1.0 is refused, since a real
    two-way quote always exceeds 1.0 -- that excess is the vig
"""

from __future__ import annotations

import unittest

from src.analysis import derivative_prices as dp
from src.core import odds as odds_math


def _row(event_id, market, line, side, price, book, **extra):
    row = {
        "event_id": event_id, "market": market, "line": line, "side": side,
        "price": price, "book": book, "team": None,
        "game_date": "2026-09-09", "observed_utc": "2026-09-09T20:00:00Z",
        "commence_time": "2026-09-09T23:10:00Z",
        "away_team": "NYM", "home_team": "MIA",
    }
    row.update(extra)
    return row


class SpreadsAreNotPaired(unittest.TestCase):
    """Until a spread is paired with the other team at the NEGATED line,
    this module publishes no value claim on one at all."""

    def test_two_teams_at_the_same_line_produce_no_contract(self):
        rows = [
            _row("e1", "alternate_spreads", -2.5, "New York Mets", 286, "b1"),
            _row("e1", "alternate_spreads", -2.5, "Miami Marlins", 250, "b1"),
        ]
        self.assertEqual([], dp._derivative_contracts(rows, date="2026-09-09"))

    def test_the_real_live_shape_produces_no_contract(self):
        """The exact rows from 2026-09-09 that claimed +45 and +42 points."""
        rows = [
            _row("e2", "alternate_spreads", -8.5, "Detroit Tigers", 1400, "fanduel"),
            _row("e2", "alternate_spreads", -8.5, "Minnesota Twins", 1500, "fanduel"),
        ]
        self.assertEqual([], dp._derivative_contracts(rows, date="2026-09-09"))

    def test_the_favourite_direction_too(self):
        """Summing ABOVE 1.0 is not evidence of a valid pair -- these two
        also cannot both happen, and de-vigging them invented -26 points."""
        rows = [
            _row("e3", "alternate_spreads", 2.5, "New York Mets", -310, "b1"),
            _row("e3", "alternate_spreads", 2.5, "Miami Marlins", -330, "b1"),
        ]
        self.assertEqual([], dp._derivative_contracts(rows, date="2026-09-09"))

    def test_every_spread_market_is_covered(self):
        for market in dp.SPREAD_MARKETS:
            rows = [
                _row("e4", market, -1.5, "New York Mets", 200, "b1"),
                _row("e4", market, -1.5, "Miami Marlins", 210, "b1"),
            ]
            self.assertEqual(
                [], dp._derivative_contracts(rows, date="2026-09-09"),
                f"{market} still produces a paired contract")


class ImpossibleBooksumsAreRefused(unittest.TestCase):
    """The second guard, which covers every market including any future one
    whose pairing rule is also wrong."""

    def test_a_pair_summing_below_one_is_dropped(self):
        """Two long shots cannot be the two sides of one market: a book
        always prices a real pair above 100%, and that excess is the vig."""
        rows = [
            _row("e5", "alternate_totals", 12.5, "Over", 1400, "b1"),
            _row("e5", "alternate_totals", 12.5, "Under", 1500, "b1"),
        ]
        total = (odds_math.american_to_probability(1400)
                 + odds_math.american_to_probability(1500))
        self.assertLess(total, dp.MIN_TWO_WAY_BOOKSUM)
        self.assertEqual([], dp._derivative_contracts(rows, date="2026-09-09"))

    def test_a_normal_vigged_pair_survives(self):
        """The guard must not eat real markets. -110/-110 sums to ~1.048."""
        rows = [
            _row("e6", "alternate_totals", 8.5, "Over", -110, "b1"),
            _row("e6", "alternate_totals", 8.5, "Under", -110, "b1"),
        ]
        contracts = dp._derivative_contracts(rows, date="2026-09-09")
        self.assertEqual(1, len(contracts))
        self.assertEqual(1, len(contracts[0]["quotes"]))

    def test_only_the_impossible_book_is_dropped_not_the_contract(self):
        """One bad book must not take a contract's honest books with it."""
        rows = [
            _row("e7", "alternate_totals", 8.5, "Over", -110, "good"),
            _row("e7", "alternate_totals", 8.5, "Under", -110, "good"),
            _row("e7", "alternate_totals", 8.5, "Over", 1400, "bad"),
            _row("e7", "alternate_totals", 8.5, "Under", 1500, "bad"),
        ]
        contracts = dp._derivative_contracts(rows, date="2026-09-09")
        self.assertEqual(1, len(contracts))
        books = {q["book"] for q in contracts[0]["quotes"]}
        self.assertEqual({"good"}, books)

    def test_the_floor_is_at_or_below_one(self):
        """A zero-margin book is theoretically possible; anything above 1.0
        would start rejecting real quotes."""
        self.assertLessEqual(dp.MIN_TWO_WAY_BOOKSUM, 1.0)
        self.assertGreater(dp.MIN_TWO_WAY_BOOKSUM, 0.9)


class NoFabricatedValueOnTheLiveBoard(unittest.TestCase):
    """The end-to-end assertion, on real captured data."""

    def test_no_row_claims_an_implausible_edge(self):
        from src.analysis import opportunities
        payload = opportunities.build_opportunities([], date="2026-09-09")
        rows = payload.get("derivative_rows") or []
        if not rows:
            self.skipTest("no derivative rows captured for 2026-09-09 here")
        worst = max(
            (abs((r.get("price_verdict") or {}).get("value_points") or 0)
             for r in rows), default=0)
        # Line-shopping gaps live in single digits. Before the fix the board
        # carried 45.
        self.assertLess(
            worst, 15,
            f"a row claims {worst:.1f} points against consensus; a gap that "
            f"size on a liquid market is an arithmetic error, not an "
            f"opportunity")


if __name__ == "__main__":
    unittest.main()
