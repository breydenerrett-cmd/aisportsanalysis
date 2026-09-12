"""A served card is numbered by where each pick sits on it, not by the slot
it was frozen in.

`rank` is a frozen field (card_ledger.FROZEN_FIELDS) and is never rewritten.
But the card is assembled through the day: each pick locks against its own
first pitch and is carried forward with the rank it held in that freeze.
The row served for 2026-09-11 carried nine picks with ranks
[3,2,3,1,2,4,5,5,4] in lock order, and #/today printed "3 OF 9" twice,
"5 OF 9" twice, "1 OF 9" fourth.

`src.report.card._served_order` sorts the frozen picks by the rule the card
states -- "ranked by how confident the market is", `daily_card._rank_key` --
and stamps `position` 1..n. The page prints `position`; `rank` stays as the
receipt of where the pick sat when it froze.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from src.appstate import card_ledger
from src.report import card as card_mod
from tests.test_card_ledger import _card, _pick


def _frozen_pick(rank, confidence, game_pk):
    pick = _pick(rank=rank, game_pk=game_pk)
    pick["confidence"] = confidence
    pick["market_probability"] = confidence
    return pick


class ServedPicksArePositioned(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v1.jsonl")
        self._real = card_ledger.CARD_STORE
        card_ledger.CARD_STORE = self.path
        self.addCleanup(setattr, card_ledger, "CARD_STORE", self._real)

    def _publish(self, picks):
        card_ledger.publish(_card(picks=picks), path=self.path)
        return card_mod.frozen_card("2026-09-10")

    def test_duplicate_frozen_ranks_serve_as_distinct_positions(self):
        """THE ONE THAT MATTERS: three picks frozen as 3, 3 and 1 -- in
        that order, the way lock order laid them down."""
        served = self._publish([
            _frozen_pick(rank=3, confidence=0.60, game_pk=1),
            _frozen_pick(rank=3, confidence=0.70, game_pk=2),
            _frozen_pick(rank=1, confidence=0.65, game_pk=3),
        ])
        self.assertEqual([p["position"] for p in served["picks"]], [1, 2, 3])

    def test_positions_follow_the_rule_the_card_states(self):
        """Most confident first, whatever slot it froze in."""
        served = self._publish([
            _frozen_pick(rank=3, confidence=0.60, game_pk=1),
            _frozen_pick(rank=3, confidence=0.70, game_pk=2),
            _frozen_pick(rank=1, confidence=0.65, game_pk=3),
        ])
        self.assertEqual([p["game_pk"] for p in served["picks"]], [2, 3, 1])

    def test_the_frozen_rank_is_untouched(self):
        """`rank` is the receipt; reordering must not rewrite it."""
        served = self._publish([
            _frozen_pick(rank=3, confidence=0.60, game_pk=1),
            _frozen_pick(rank=1, confidence=0.70, game_pk=2),
        ])
        by_game = {p["game_pk"]: p for p in served["picks"]}
        self.assertEqual(by_game[1]["rank"], 3)
        self.assertEqual(by_game[2]["rank"], 1)

    def test_the_ledger_row_itself_is_not_reordered(self):
        """Serving order is derived on read; the published row is the
        receipt and keeps lock order."""
        self._publish([
            _frozen_pick(rank=3, confidence=0.60, game_pk=1),
            _frozen_pick(rank=1, confidence=0.70, game_pk=2),
        ])
        row = card_ledger.published_row("2026-09-10", path=self.path)
        self.assertEqual([p["game_pk"] for p in row["picks"]], [1, 2])
        self.assertNotIn("position", row["picks"][0])


if __name__ == "__main__":
    unittest.main()
