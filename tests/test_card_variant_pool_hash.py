"""T3v: pool_hash proves all four arms screened the same board; published/
family_id/arm are stamped correctly on every arm's rows, A1's included."""

from __future__ import annotations

import os
import tempfile
import unittest

from src.analysis import card_variants
from src.appstate import card_ledger as cl


def _candidate(game_pk, price=-140, our_probability=0.62):
    return {
        "kind": "game",
        "game_pk": game_pk,
        "game_id": game_pk,
        "player_id": None,
        "market": "moneyline",
        "side": "home",
        "line": None,
        "price": price,
        "our_probability": our_probability,
        "market_probability": 0.55,
        "first_pitch_utc": "2026-09-20T23:05:00Z",
        "observed_utc": "2026-09-20T18:00:00Z",
        "game_type": "R",
        "books": 8,
        "take": True,
    }


class TestPoolHashAndStamps(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.stores = {
            arm: os.path.join(self._tmp.name, f"{arm}.jsonl")
            for arm in ("A1", "A2", "A3", "A4")
        }

    def _publish(self, pool, date="2026-09-20"):
        family = card_variants.run_family(pool, now="2026-09-20T14:00:00Z")
        for result in family.values():
            result["date"] = date
        cl.publish_variants(family, now="2026-09-20T14:00:00Z", store_by_arm=self.stores)
        return {arm: cl._ledger(path).read()[-1] for arm, path in self.stores.items()}

    def test_all_four_rows_share_one_pool_hash(self):
        pool = [_candidate(5001), _candidate(5002, price=140, our_probability=0.44)]
        rows = self._publish(pool)
        hashes = {row["pool_hash"] for row in rows.values()}
        self.assertEqual(len(hashes), 1)

    def test_different_pools_produce_different_hashes(self):
        rows_1 = self._publish([_candidate(5001)], date="2026-09-20")
        stores_2 = {arm: os.path.join(self._tmp.name, f"{arm}_2.jsonl") for arm in self.stores}
        self.stores = stores_2
        rows_2 = self._publish([_candidate(5001), _candidate(6001, price=150, our_probability=0.42)],
                                date="2026-09-21")
        self.assertNotEqual(
            rows_1["A1"]["pool_hash"],
            rows_2["A1"]["pool_hash"],
        )

    def test_published_true_only_on_a1(self):
        rows = self._publish([_candidate(5001)])
        self.assertTrue(rows["A1"]["published"])
        for arm in ("A2", "A3", "A4"):
            self.assertFalse(rows[arm]["published"])

    def test_family_id_and_arm_present_on_every_row_including_a1(self):
        rows = self._publish([_candidate(5001)])
        for arm, row in rows.items():
            self.assertEqual(row["family_id"], card_variants.FAMILY_ID)
            self.assertEqual(row["arm"], arm)


if __name__ == "__main__":
    unittest.main()
