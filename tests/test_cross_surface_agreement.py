"""Two surfaces, one board, one number -- the guard a per-surface suite cannot be.

WHY THIS FILE EXISTS
--------------------
Finding F-3 (docs/DEMO_SHIP_CHECKLIST.md, 2026-09-07): the Gameday screen
printed "No priced market for this game yet" four lines under a Featured Bet
quoting that same game across nine books, at the same capture instant. Every
surface was individually correct against its own fixture, and every
per-surface test passed, because the defect was in a field that was wrong the
SAME way everywhere -- `market_implied_consensus` read a dossier section the
API never populates while the board sat beside it holding the number.

That is the generalisable shape: a per-surface suite verifies each surface
against its own fixture, so a shared upstream field that is wrong everywhere
looks correct everywhere. The cheap standing guard is a test that builds ONE
slate and asserts two different payload builders report the SAME number for
the same game -- which is what this file is. New cross-surface invariants
belong here rather than in either surface's own module tests.

Hermetic: one entry built through the real `briefing.build_slate`, deliberately
WITHOUT `prices_by_matchup` (exactly how `api.games._build_entries` calls it),
so the fixture reproduces the API's real shape rather than the CLI's.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from src.analysis import gamepayload, opportunities
from src.pipeline import briefing, history

GAME_DATE = "2026-08-31"
OBSERVED = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 8, 31, 12, 30, 0, tzinfo=timezone.utc)


def _game(game_pk=880001, away="BOS", home="NYY", date=GAME_DATE):
    return {"game_pk": game_pk, "away_team": away, "home_team": home,
            "date": date, "start_time_utc": f"{date}T23:05:00Z",
            "venue": "Yankee Stadium"}


def _entries(*, with_board=True):
    """One slate entry, built the way the API builds it: a multi-book board
    and NO `prices_by_matchup`, so the dossier carries `price_improvement`
    but no `market` section."""
    game = _game()
    kwargs = {"roster_events_by_pk": {}}
    if with_board:
        kwargs["price_boards_by_key"] = {
            (game["away_team"], game["home_team"], game["date"]): {
                "quotes": [{"ts": OBSERVED.isoformat(), "book": b,
                            "away_price": 110 + i, "home_price": -130 - i}
                           for i, b in enumerate(
                               ["a", "b", "c", "d", "e", "f", "g"])],
                "observed_utc": OBSERVED.isoformat(),
                "source": "test",
            }
        }
    slate = briefing.build_slate([game], history.read_results(), **kwargs)
    return slate["games"]


class ConsensusAgreesAcrossSurfaces(unittest.TestCase):
    """The slate list and Top Opportunities must never disagree about the
    de-vigged consensus for the same game, nor about whether it exists."""

    def test_the_same_board_yields_the_same_number_on_both_surfaces(self):
        entries = _entries()
        row = gamepayload.build_slate_list(entries, date=GAME_DATE,
                                           now=NOW)["games"][0]
        opp = opportunities.build_opportunities(entries, date=GAME_DATE, now=NOW)

        consensus = row["market_implied_consensus"]
        self.assertIsNotNone(consensus, "a seven-book board is a priced market")
        by_side = {r["side"]: r for r in opp["rows"]}
        self.assertIn("away", by_side)
        self.assertIn("home", by_side)
        self.assertAlmostEqual(consensus["away_fair"],
                               by_side["away"]["market_implied_probability"],
                               places=9)
        self.assertAlmostEqual(consensus["home_fair"],
                               by_side["home"]["market_implied_probability"],
                               places=9)

    def test_an_unpriced_game_is_unpriced_on_both_surfaces(self):
        """The obvious way the F-3 fix could have gone wrong: a fallback that
        manufactures a consensus for a game nobody quoted. It must stay null
        on the slate AND stay out of the priced rows."""
        entries = _entries(with_board=False)
        row = gamepayload.build_slate_list(entries, date=GAME_DATE,
                                           now=NOW)["games"][0]
        opp = opportunities.build_opportunities(entries, date=GAME_DATE, now=NOW)

        self.assertIsNone(row["market_implied_consensus"])
        self.assertEqual(opp["rows"], [])
        self.assertEqual(len(opp["unpriced"]), 1)
        self.assertTrue(opp["unpriced"][0]["reason"],
                        "an unpriced game must say why, never just vanish")

    def test_board_depth_agrees_across_surfaces(self):
        """Same discipline for the book count: one board, one number."""
        entries = _entries()
        row = gamepayload.build_slate_list(entries, date=GAME_DATE,
                                           now=NOW)["games"][0]
        opp = opportunities.build_opportunities(entries, date=GAME_DATE, now=NOW)
        self.assertEqual(row["board_summary"]["books"], opp["rows"][0]["books"])


if __name__ == "__main__":
    unittest.main()
