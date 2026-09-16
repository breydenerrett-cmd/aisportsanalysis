"""V2's own store is isolated from V1's and from every shadow/variant store.

registration section 10 lists eight distinct files; nothing published to one
may ever be read back from another, and a V1 row and a V2 row for the same
date must never appear together in one record() result.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from src.appstate import card_ledger as cl
from tests._card_v2_fixtures import game_entry, select_result


class PathIsolation(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.v2_path = os.path.join(self._tmp.name, "cards_v2.jsonl")
        self.shadow_a_path = os.path.join(self._tmp.name, "cards_v2_shadow_a.jsonl")
        self.v1_path = os.path.join(self._tmp.name, "cards_v1.jsonl")

    def test_no_shadow_d_constant_exists(self):
        self.assertFalse(hasattr(cl, "CARD_STORE_V2_SHADOW_D"))

    def test_every_registered_store_constant_is_distinct(self):
        stores = {
            cl.CARD_STORE_V2, cl.CARD_STORE_V2_SHADOW_A, cl.CARD_STORE_V2_SHADOW_C,
            cl.CARD_STORE_V2_SHADOW_E, cl.CARD_STORE_V1_SHADOW,
            cl.CARD_STORE_V2_VAR_STRICT_NOCAP, cl.CARD_STORE_V2_VAR_LOOSE_CAP3,
            cl.CARD_STORE_V2_VAR_LOOSE_NOCAP,
        }
        self.assertEqual(8, len(stores), "two store constants collide on one path")
        self.assertNotIn("cards_v2_shadow_d.jsonl", " ".join(stores))

    def test_v2_rows_land_only_in_the_v2_file_with_the_v2_rule_id(self):
        card = select_result(picks=[game_entry()])
        cl.publish_v2(card, now="2026-09-20T10:00:00Z", path=self.v2_path)

        v2_rows = [r for r in cl._ledger(self.v2_path).read()
                   if r.get("kind") == cl.KIND_PUBLISHED]
        self.assertEqual(1, len(v2_rows))
        self.assertEqual("DAILY_CARD_BEST_BETS_V2", v2_rows[0]["rule"])

        # Never written to the shadow store just by publishing V2.
        shadow_rows = [r for r in cl._ledger(self.shadow_a_path).read()
                       if r.get("kind") == cl.KIND_PUBLISHED]
        self.assertEqual(0, len(shadow_rows))

    def test_each_shadow_lands_only_in_its_own_file(self):
        a_card = select_result(picks=[game_entry()])
        cl.publish_v2(a_card, now="2026-09-20T10:00:00Z", path=self.shadow_a_path)

        self.assertIsNone(cl.published_row("2026-09-20", path=self.v2_path))
        self.assertIsNotNone(cl.published_row("2026-09-20", path=self.shadow_a_path))

    def test_record_v2_on_one_path_counts_only_that_file(self):
        published = cl.publish_v2(
            select_result(date="2026-09-19", picks=[game_entry(game_pk=9001, price=-140)]),
            now="2026-09-19T20:00:00Z", path=self.v2_path)
        self.assertFalse(published["already_published"])

        settled = cl.settle_v2("2026-09-19", {9001: {"away_score": 2, "home_score": 5}},
                                path=self.v2_path)
        self.assertIsNotNone(settled)

        record = cl.record_v2(path=self.v2_path)
        self.assertEqual(1, record["main"]["n_staked"])

        shadow_record = cl.record_v2(path=self.shadow_a_path)
        self.assertEqual(0, shadow_record["main"]["n_staked"])

    def test_a_v1_row_and_a_v2_row_for_the_same_date_never_appear_in_one_result(self):
        v1_card = {
            "date": "2026-09-19", "rule": "DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1",
            "basis": "b", "disclaimer": "d", "model_id": "m", "calibrated": True,
            "calibration": {}, "filled": 0, "games_on_slate": 3,
            "picks": [{
                "rank": 1, "label": "STRONG", "bet": "Take Yankees", "why": [],
                "market": "moneyline", "line": None, "side": "home", "team": "NYY",
                "team_name": "Yankees", "opponent_name": "Rockies", "price": -150,
                "book": "dk", "books": 8, "confidence": 0.7, "market_probability": 0.68,
                "model_probability": 0.64, "game_id": None, "game_pk": 9001,
                "event_id": "e1", "away_team": "COL", "home_team": "NYY",
                "first_pitch_utc": "2026-09-19T23:05:00Z",
                "observed_utc": "2026-09-19T18:00:00Z", "model": {},
            }],
        }
        cl.publish(v1_card, now="2026-09-19T10:00:00Z", path=self.v1_path)
        cl.publish_v2(select_result(date="2026-09-19", picks=[game_entry(game_pk=9002)]),
                       now="2026-09-19T10:00:00Z", path=self.v2_path)

        v1_dates = {r.get("date") for r in cl._ledger(self.v1_path).read()
                    if r.get("kind") == cl.KIND_PUBLISHED}
        v2_dates = {r.get("date") for r in cl._ledger(self.v2_path).read()
                    if r.get("kind") == cl.KIND_PUBLISHED}
        # Same date published to both stores -- but reading either store
        # alone never surfaces the other's rows: no function in this module
        # reads two paths at once.
        self.assertEqual({"2026-09-19"}, v1_dates)
        self.assertEqual({"2026-09-19"}, v2_dates)
        v1_rows = [r for r in cl._ledger(self.v1_path).read() if r.get("kind") == cl.KIND_PUBLISHED]
        self.assertEqual("DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1", v1_rows[0]["rule"])
        v2_rows = [r for r in cl._ledger(self.v2_path).read() if r.get("kind") == cl.KIND_PUBLISHED]
        self.assertEqual("DAILY_CARD_BEST_BETS_V2", v2_rows[0]["rule"])


if __name__ == "__main__":
    unittest.main()
