"""A published slip pick, rendered for the page with the club, the side and
the book -- `src.board.readable.readable_pick` / `readable_slip`.

#/today printed "Moneyline at -182 (betrivers)" on 2026-09-11: the slip
names a pick by event_id, market_key and a selection hash, and the page
had nothing to join them to. GET /today now attaches `wager_text`, `side`,
`away_team` and `home_team` on the way out; the ledger row is untouched.
"""

from __future__ import annotations

import unittest

from src.board import readable
from src.board.ids import selection_id

EVENTS = {
    "e1": {"home_team": "Milwaukee Brewers", "away_team": "Cincinnati Reds",
           "commence_time": "2026-09-11T23:45:00Z"},
}


def _pick(**over):
    base = {
        "event_id": "e1", "market_key": "h2h", "line": None,
        "selection_id": selection_id(sport="mlb", market_key="h2h",
                                     side="home", line=None),
        "price_american": -182, "book": "betrivers", "rank": 1,
    }
    base.update(over)
    return base


class TheWagerReadsInEnglish(unittest.TestCase):

    def test_club_side_price_and_book(self):
        out = readable.readable_pick(_pick(), EVENTS)
        self.assertEqual(out["wager_text"],
                         "Milwaukee Brewers (home) moneyline (-182, BetRivers)")
        self.assertEqual(out["side"], "home")
        self.assertEqual(out["home_team"], "Milwaukee Brewers")
        self.assertEqual(out["away_team"], "Cincinnati Reds")

    def test_an_unknown_event_names_the_side_not_a_club(self):
        out = readable.readable_pick(_pick(event_id="nope"), EVENTS)
        self.assertEqual(out["wager_text"], "the home side moneyline (-182, BetRivers)")
        self.assertIsNone(out["home_team"])
        self.assertIsNone(out["away_team"])

    def test_nothing_the_ledger_wrote_is_removed_or_changed(self):
        pick = _pick()
        out = readable.readable_pick(pick, EVENTS)
        for key, value in pick.items():
            self.assertEqual(out[key], value, key)
        self.assertNotIn("wager_text", pick, "the input was mutated")


class TheSlipRowRidesThrough(unittest.TestCase):

    def test_none_stays_none(self):
        self.assertIsNone(readable.readable_slip(None, EVENTS))

    def test_hashes_and_fields_are_copied_and_picks_are_rendered(self):
        slip = {"date": "2026-09-11", "rule": "r", "row_hash": "abc",
                "picks": [_pick()]}
        out = readable.readable_slip(slip, EVENTS)
        self.assertEqual(out["row_hash"], "abc")
        self.assertEqual(out["picks"][0]["wager_text"],
                         "Milwaukee Brewers (home) moneyline (-182, BetRivers)")
        self.assertNotIn("wager_text", slip["picks"][0])


if __name__ == "__main__":
    unittest.main()
