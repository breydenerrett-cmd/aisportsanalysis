"""A V2 board can offer fewer than the floor -- even zero -- and that is a
real, recordable state, not an error (design board risk 9). V1's refusal of
an empty card stays exactly as it is.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from src.appstate import card_ledger as cl
from tests._card_v2_fixtures import select_result


class EmptyDay(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.v2_path = os.path.join(self._tmp.name, "cards_v2.jsonl")

    def test_publish_v2_writes_a_zero_pick_row(self):
        card = select_result(picks=[], prop_picks=[], fills=[])
        row = cl.publish_v2(card, now="2026-09-20T10:00:00Z", path=self.v2_path)
        self.assertFalse(row["already_published"])
        self.assertEqual(0, row["n_picks"])

        published_rows = [r for r in cl._ledger(self.v2_path).read()
                          if r.get("kind") == cl.KIND_PUBLISHED]
        self.assertEqual(1, len(published_rows), "a zero-pick day was not written")

    def test_publish_v2_carries_fills_on_a_zero_pick_day(self):
        from tests._card_v2_fixtures import game_entry
        fill = game_entry(price=-140, entry_class="fill",
                          failed_gates=["G7_VALUE"])
        card = select_result(picks=[], fills=[fill])
        row = cl.publish_v2(card, now="2026-09-20T10:00:00Z", path=self.v2_path)
        self.assertEqual(0, row["n_picks"])
        self.assertEqual(1, row["n_fills"])

    def test_v1_publish_still_raises_on_an_empty_card(self):
        v1_path = os.path.join(os.path.dirname(self.v2_path), "cards_v1.jsonl")
        with self.assertRaises(cl.CardLedgerError):
            cl.publish({"date": "2026-09-20", "picks": []}, path=v1_path)

    def test_a_date_with_no_date_key_is_refused(self):
        with self.assertRaises(cl.CardLedgerError):
            cl.publish_v2({"picks": []}, path=self.v2_path)


if __name__ == "__main__":
    unittest.main()
