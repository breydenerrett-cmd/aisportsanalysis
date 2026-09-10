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

THREE GUARDS NOW, BECAUSE THEY FAIL DIFFERENTLY
------------------------------------------------
  * `_spread_key` orients every spread from the away club, so the two real
    sides of one contract -- away at L, home at -L -- group together and
    nothing else does. This is the actual fix.
  * `_pair_sides` returns spreads away-then-home rather than alphabetically,
    because everything downstream maps the first side to `away_price` and
    the two sides of a spread carry DIFFERENT lines. Sorting by name would
    attach roughly half of all contracts' prices to the other club's line.
  * ANY market whose two legs sum below 1.0 is still refused, since a real
    two-way quote always exceeds 1.0 -- that excess is the vig. This one
    covers every market at once, including a future one whose pairing rule
    turns out to be wrong too.

The first guard shipped only after the second and third: for a day this
module published no spread value claim at all, on the principle that an
absence is honest where a manufactured edge is not. Measured on the incident
date after the real fix, the largest claimed value on the whole board is
3.87 points and no row claims 15 or more. Before it, one claimed 45.
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


class SpreadsPairAtTheNegatedLine(unittest.TestCase):
    """The fix itself: away at L pairs with home at -L, and only that."""

    def test_the_true_complement_produces_one_contract(self):
        rows = [
            _row("e10", "alternate_spreads", -1.5, "New York Mets", 150, "b1"),
            _row("e10", "alternate_spreads", 1.5, "Miami Marlins", -180, "b1"),
        ]
        contracts = dp._derivative_contracts(rows, date="2026-09-09")
        self.assertEqual(1, len(contracts))
        self.assertEqual(("New York Mets", "Miami Marlins"),
                         contracts[0]["sides"])

    def test_each_side_keeps_its_own_line(self):
        """The two sides of a spread do not share a line. Rendering both
        from one stored value prints the wrong bet on one of them."""
        rows = [
            _row("e11", "alternate_spreads", -1.5, "New York Mets", 150, "b1"),
            _row("e11", "alternate_spreads", 1.5, "Miami Marlins", -180, "b1"),
        ]
        contract = dp._derivative_contracts(rows, date="2026-09-09")[0]
        self.assertEqual({"New York Mets": -1.5, "Miami Marlins": 1.5},
                         contract["side_lines"])

    def test_sides_are_away_then_home_not_alphabetical(self):
        """Downstream maps the FIRST side to `away_price`. Alphabetical
        order would swap the two clubs' prices whenever the home club's
        name sorts first -- roughly half of all contracts."""
        rows = [
            # "Atlanta" sorts before "Tampa Bay"; Atlanta is the HOME club.
            _row("e12", "alternate_spreads", -1.5, "Tampa Bay Rays", 150, "b1",
                 away_team="Tampa Bay Rays", home_team="Atlanta Braves"),
            _row("e12", "alternate_spreads", 1.5, "Atlanta Braves", -180, "b1",
                 away_team="Tampa Bay Rays", home_team="Atlanta Braves"),
        ]
        contract = dp._derivative_contracts(rows, date="2026-09-09")[0]
        self.assertEqual(("Tampa Bay Rays", "Atlanta Braves"),
                         contract["sides"])

    def test_a_side_that_is_neither_club_is_dropped(self):
        """An unrecognised `side` must not be oriented by guessing."""
        rows = [
            _row("e13", "alternate_spreads", -1.5, "Detroit Tigers", 150, "b1"),
            _row("e13", "alternate_spreads", 1.5, "Miami Marlins", -180, "b1"),
        ]
        self.assertEqual([], dp._derivative_contracts(rows, date="2026-09-09"))

    def test_an_unparseable_line_is_dropped(self):
        rows = [
            _row("e14", "alternate_spreads", "pk", "New York Mets", 150, "b1"),
            _row("e14", "alternate_spreads", 1.5, "Miami Marlins", -180, "b1"),
        ]
        self.assertEqual([], dp._derivative_contracts(rows, date="2026-09-09"))

    def test_different_lines_are_different_contracts(self):
        """-1.5 and -2.5 are different bets and must never be pooled into
        one consensus, which would average two propositions and call the
        result a fair price."""
        rows = [
            _row("e15", "alternate_spreads", -1.5, "New York Mets", 150, "b1"),
            _row("e15", "alternate_spreads", 1.5, "Miami Marlins", -180, "b1"),
            _row("e15", "alternate_spreads", -2.5, "New York Mets", 260, "b1"),
            _row("e15", "alternate_spreads", 2.5, "Miami Marlins", -320, "b1"),
        ]
        contracts = dp._derivative_contracts(rows, date="2026-09-09")
        self.assertEqual(2, len(contracts))
        self.assertEqual(
            {"-1.5", "-2.5"},
            {f"{contract['side_lines']['New York Mets']}" for contract in contracts})


class SpreadsAreNotPaired(unittest.TestCase):
    """The bug: two clubs at the SAME line are not each other's complement
    and must never be de-vigged against one another."""

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

    def test_the_live_board_carries_no_implausible_spread_claim(self):
        """End-to-end on the incident date's own captured rows. Before the
        pairing fix this produced 387 fabricated pairs, one claiming 45
        points; the guard alone dropped every spread instead."""
        rows = dp.candidates_for_date("2026-09-09")
        spreads = [r for r in rows if r["market"] in dp.SPREAD_MARKETS
                   and r.get("consensus_probability") is not None]
        if not spreads:
            self.skipTest("no spread rows captured for 2026-09-09 here")
        worst = max(
            abs(odds_math.american_to_probability(r["best_price"])
                - r["consensus_probability"]) * 100.0
            for r in spreads if r.get("best_price") is not None)
        self.assertLess(
            worst, 15,
            f"a spread claims {worst:.1f} points against consensus; a gap "
            f"that size is an arithmetic error, not an opportunity")


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
