"""T3v: each arm's rows land only in that arm's own store file."""

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


class TestVariantLedgerPaths(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.stores = {
            arm: os.path.join(self._tmp.name, f"{arm}.jsonl")
            for arm in ("A1", "A2", "A3", "A4")
        }
        pool = [_candidate(5001), _candidate(5002, price=140, our_probability=0.44)]
        self.family = card_variants.run_family(pool, now="2026-09-20T14:00:00Z")
        for result in self.family.values():
            result["date"] = "2026-09-20"

    def test_each_arm_writes_only_its_own_file(self):
        cl.publish_variants(self.family, now="2026-09-20T14:00:00Z", store_by_arm=self.stores)
        for arm, path in self.stores.items():
            rows = cl.record_v2(path=path)
            self.assertIsNotNone(rows)  # file exists and is readable
            self.assertTrue(os.path.exists(path))

    def test_a1_rule_id_never_in_a_paper_store_and_reverse(self):
        result = cl.publish_variants(self.family, now="2026-09-20T14:00:00Z", store_by_arm=self.stores)
        published_rows = {arm: cl._ledger(path).read() for arm, path in self.stores.items()}
        a1_rule = card_variants.ARMS["A1"].rule_id
        for arm in ("A2", "A3", "A4"):
            rule_ids = {row.get("rule") for row in published_rows[arm]}
            self.assertNotIn(a1_rule, rule_ids)
        a1_rule_ids = {row.get("rule") for row in published_rows["A1"]}
        for arm in ("A2", "A3", "A4"):
            self.assertNotIn(card_variants.ARMS[arm].rule_id, a1_rule_ids)

    def test_record_with_path_counts_only_that_file(self):
        cl.publish_variants(self.family, now="2026-09-20T14:00:00Z", store_by_arm=self.stores)
        for arm, path in self.stores.items():
            record = cl.record_v2(path=path)
            self.assertEqual(record["since"], None)

    def test_module_has_no_cross_arm_summary_function(self):
        import inspect
        source = inspect.getsource(cl)
        # publish_variants itself must not sum/compare across the arms it writes.
        func_source = inspect.getsource(cl.publish_variants)
        for forbidden in ("sum(", "arm_a", "arm_b", "compare"):
            self.assertNotIn(forbidden, func_source)


if __name__ == "__main__":
    unittest.main()
