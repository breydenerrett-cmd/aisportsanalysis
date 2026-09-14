"""Two false sentences on the live site, fixed with the owner's approval on
2026-09-14.

1. The card said totals were CHECKED ("No game total on the board both agreed
   with our own numbers and cleared its price when this card was frozen")
   while totals were switched off and never evaluated.
2. The shared footer's product line said "price comparisons ... not picks",
   the retired positioning, under a page that sells tonight's picks.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from src.appstate import card_ledger
from src.report import card as card_mod

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


def _pick():
    return {
        "rank": 1, "label": "STRONG", "bet": "Take Yankees to win at -150",
        "why": ["because"], "market": "moneyline", "line": None, "side": "home",
        "team": "NYY", "team_name": "Yankees", "opponent_name": "Rockies",
        "price": -150, "book": "dk", "books": 8, "confidence": 0.74,
        "market_probability": 0.74, "model_probability": 0.64, "game_id": "g1",
        "game_pk": 1001, "event_id": "e1", "away_team": "COL", "home_team": "NYY",
        "first_pitch_utc": "2026-09-14T23:10:00Z",
        "observed_utc": "2026-09-14T16:00:00Z", "model": {},
    }


def _card(**extra):
    card = {"date": "2026-09-14", "rule": "r", "basis": "b", "disclaimer": "d",
            "model_id": "m", "calibrated": True, "calibration": {}, "filled": 0,
            "games_on_slate": 1, "picks": [_pick()], "prop_picks": [],
            "total_picks": []}
    card.update(extra)
    return card


class PausedTotalsAreNotDescribedAsEvaluated(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v1.jsonl")

    def _frozen(self):
        row = card_ledger.published_row("2026-09-14", path=self.path)
        with mock.patch("src.appstate.card_ledger.published_row", return_value=row):
            return card_mod.frozen_card("2026-09-14")

    def test_a_card_built_while_paused_says_paused(self):
        """Fails on the pre-fix frozen_card, which served the 'none cleared
        its price' sentence for an empty total_picks."""
        card_ledger.publish(_card(totals_paused=True), path=self.path,
                            now="2026-09-14T16:00:00+00:00")
        served = self._frozen()
        self.assertEqual(card_mod._TOTALS_PAUSED_FROZEN, served["total_reason"])
        self.assertTrue(served["totals_paused"])
        self.assertNotIn("cleared its price", served["total_reason"])

    def test_a_row_frozen_before_the_flag_existed_reads_as_paused(self):
        """The 16:52 UTC 2026-09-14 row carries total_picks = [] and no flag;
        totals were already switched off when that key first appeared."""
        card_ledger.publish(_card(), path=self.path, now="2026-09-14T16:00:00+00:00")
        row = card_ledger.published_row("2026-09-14", path=self.path)
        row = {k: v for k, v in row.items() if k != "totals_paused"}
        with mock.patch("src.appstate.card_ledger.published_row", return_value=row):
            served = card_mod.frozen_card("2026-09-14")
        self.assertEqual(card_mod._TOTALS_PAUSED_FROZEN, served["total_reason"])

    def test_evaluated_totals_with_nothing_selected_still_say_so(self):
        card_ledger.publish(_card(totals_paused=False), path=self.path,
                            now="2026-09-14T16:00:00+00:00")
        served = self._frozen()
        self.assertEqual(card_mod._TOTAL_NONE_SELECTED_FROZEN, served["total_reason"])

    def test_a_card_from_before_totals_existed_says_not_part_of_card(self):
        card_ledger.publish(_card(), path=self.path, now="2026-09-14T16:00:00+00:00")
        row = card_ledger.published_row("2026-09-14", path=self.path)
        row = {k: v for k, v in row.items() if k not in ("total_picks", "totals_paused")}
        with mock.patch("src.appstate.card_ledger.published_row", return_value=row):
            served = card_mod.frozen_card("2026-09-14")
        self.assertEqual(card_mod._TOTAL_NOT_PART_OF_CARD, served["total_reason"])

    def test_the_ledger_records_the_flag(self):
        row = card_ledger.publish(_card(totals_paused=True), path=self.path,
                                  now="2026-09-14T16:00:00+00:00")
        self.assertTrue(row["totals_paused"])


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheProductLineSellsThePicks(unittest.TestCase):
    def test_no_retired_positioning(self):
        from api.meta import PRODUCT_ONE_LINER
        text = PRODUCT_ONE_LINER.lower()
        self.assertNotIn("price comparison", text)
        self.assertNotIn("not picks", text)
        self.assertIn("picks", text)
        self.assertIn("not guarantees", text)


if __name__ == "__main__":
    unittest.main()
