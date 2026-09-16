"""Every V2 pick and fill carries the fields registration 11.1-11.3 name;
code_fingerprint and v1_code_fingerprint cover exactly their own registered
file lists and react to a byte changing; the two fingerprints never share
one input list.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from src.appstate import card_ledger as cl
from tests._card_v2_fixtures import game_entry, prop_entry, select_result


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v2.jsonl")


class FrozenFieldsPresent(LedgerCase):
    def test_every_pick_and_fill_carries_the_registered_fields(self):
        pick = game_entry(game_pk=1, price=-140, our_probability=0.62,
                          market_probability=0.58)
        fill = game_entry(game_pk=2, price=-140, entry_class="fill",
                          failed_gates=["G7_VALUE"])
        row = cl.publish_v2(select_result(picks=[pick], fills=[fill]),
                            now="2026-09-20T10:00:00Z", path=self.path)

        for entry in row["picks"] + row["fills"]:
            self.assertIn("game_type", entry)
            self.assertIn("entry_class", entry)
            self.assertIn("price_class", entry)
            self.assertIsNotNone(entry["price_class"])
            self.assertIn("our_probability", entry)
            self.assertIn("our_probability_used", entry)
            self.assertIn("score", entry)

    def test_every_prop_carries_lineup_posted(self):
        prop = prop_entry(game_pk=3, price=120, our_probability=0.34,
                          market_probability=0.30, lineup_posted=False)
        row = cl.publish_v2(select_result(prop_picks=[prop]),
                            now="2026-09-20T10:00:00Z", path=self.path)
        prop_entries = [e for e in row["all_bets"] if e.get("kind") == "prop"]
        self.assertEqual(1, len(prop_entries))
        self.assertIn("lineup_posted", prop_entries[0])
        self.assertFalse(prop_entries[0]["lineup_posted"])

    def test_every_row_carries_code_fingerprint_and_params(self):
        pick = game_entry(game_pk=1, price=-140)
        row = cl.publish_v2(select_result(picks=[pick]), now="2026-09-20T10:00:00Z",
                            path=self.path)
        self.assertTrue(row["code_fingerprint"])
        self.assertIn("markdown", row["params"])
        self.assertIn("base_edge", row["params"])
        self.assertIn("plus_money_subcap", row["params"])
        self.assertIn("ceiling", row["params"])
        self.assertIn("floor", row["params"])


class CodeFingerprintCoversTheRegisteredFiles(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name

    def _write(self, name, content):
        path = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_v2_fingerprint_covers_exactly_the_registered_seven_files(self):
        self.assertEqual(7, len(cl.V2_FINGERPRINT_FILES))
        self.assertIn(os.path.join("src", "report", "card_v2.py")
                       if os.sep != "/" else "src/report/card_v2.py",
                       [p.replace("/", os.sep) for p in cl.V2_FINGERPRINT_FILES])

    def test_v1_fingerprint_covers_exactly_the_registered_eight_paths(self):
        self.assertEqual(8, len(cl.V1_FINGERPRINT_FILES))
        for expected in ("strength.py", "playerprops.py", "propboard.py",
                         "props.py", "daily_card.py", "card.py",
                         "card_ledger.py", "card_calibration.json"):
            self.assertTrue(any(expected in p for p in cl.V1_FINGERPRINT_FILES),
                            f"{expected} missing from V1_FINGERPRINT_FILES")

    def test_changing_a_fingerprinted_files_bytes_changes_the_fingerprint(self):
        for name in ("a.py", "b.py", "c.json"):
            self._write(name, "original")
        paths = ("a.py", "b.py", "c.json")
        before = cl.code_fingerprint(paths, root=self.root)

        self._write("b.py", "changed")
        after = cl.code_fingerprint(paths, root=self.root)
        self.assertNotEqual(before, after)

    def test_a_missing_file_still_produces_a_stable_fingerprint(self):
        self._write("a.py", "x")
        paths = ("a.py", "does_not_exist.py")
        fp1 = cl.code_fingerprint(paths, root=self.root)
        fp2 = cl.code_fingerprint(paths, root=self.root)
        self.assertEqual(fp1, fp2)

    def test_every_v1_shadow_row_carries_v1_code_fingerprint_pinned_to_its_own_list(self):
        path = os.path.join(self.root, "cards_v1_shadow.jsonl")
        row = cl.publish_v1_shadow(
            {"date": "2026-09-20", "rule": "DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1",
             "picks": [{"rank": 1}]},
            now="2026-09-20T10:00:00Z", path=path)
        self.assertIn("v1_code_fingerprint", row)
        self.assertEqual(cl.code_fingerprint(cl.V1_FINGERPRINT_FILES), row["v1_code_fingerprint"])

    def test_v1_code_fingerprint_and_code_fingerprint_never_share_one_input_list(self):
        v2_only = set(cl.V2_FINGERPRINT_FILES) - set(cl.V1_FINGERPRINT_FILES)
        v1_only = set(cl.V1_FINGERPRINT_FILES) - set(cl.V2_FINGERPRINT_FILES)
        self.assertTrue(v2_only, "V2's fingerprint must name at least one file V1's does not")
        self.assertTrue(v1_only, "V1's fingerprint must name at least one file V2's does not")


if __name__ == "__main__":
    unittest.main()
