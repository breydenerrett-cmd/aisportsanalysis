"""tests for src.ledger.chain: the append-only hash-chained JSONL primitive."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.ledger import chain as chain_module
from src.ledger.chain import (
    GENESIS_HASH,
    HashChainLedger,
    canonical_bytes,
    row_hash,
)


class CanonicalisationTests(unittest.TestCase):
    def test_key_order_does_not_affect_bytes(self):
        a = canonical_bytes({"b": 1, "a": 2})
        b = canonical_bytes({"a": 2, "b": 1})
        self.assertEqual(a, b)

    def test_output_is_ascii_and_compact(self):
        out = canonical_bytes({"x": "café", "y": [1, 2]})
        text = out.decode("ascii")  # raises if non-ascii leaked through
        self.assertNotIn(" ", text)  # separators=(",", ":") -- no incidental whitespace

    def test_row_hash_is_deterministic(self):
        h1 = row_hash({"a": 1}, "prev")
        h2 = row_hash({"a": 1}, "prev")
        self.assertEqual(h1, h2)

    def test_row_hash_changes_with_prev_hash(self):
        h1 = row_hash({"a": 1}, "prevA")
        h2 = row_hash({"a": 1}, "prevB")
        self.assertNotEqual(h1, h2)

    def test_row_hash_changes_with_dict_order_of_construction_not_content(self):
        # Same logical content, different insertion order -- must hash the same.
        p1 = {}
        p1["a"] = 1
        p1["b"] = 2
        p2 = {}
        p2["b"] = 2
        p2["a"] = 1
        self.assertEqual(row_hash(p1, "x"), row_hash(p2, "x"))

    def test_row_hash_rejects_payload_carrying_row_hash(self):
        with self.assertRaises(chain_module.ChainError):
            row_hash({"row_hash": "x"}, "prev")


class AppendAndReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "chain.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_chain_last_hash_is_genesis(self):
        ledger = HashChainLedger(self.path)
        self.assertEqual(ledger.last_hash(), GENESIS_HASH)

    def test_first_row_chains_to_genesis(self):
        ledger = HashChainLedger(self.path)
        row = ledger.append({"n": 1})
        self.assertEqual(row["prev_hash"], GENESIS_HASH)
        self.assertIn("row_hash", row)

    def test_second_row_chains_to_first(self):
        ledger = HashChainLedger(self.path)
        row1 = ledger.append({"n": 1})
        row2 = ledger.append({"n": 2})
        self.assertEqual(row2["prev_hash"], row1["row_hash"])

    def test_append_rejects_caller_supplied_hash_fields(self):
        ledger = HashChainLedger(self.path)
        with self.assertRaises(chain_module.ChainError):
            ledger.append({"n": 1, "prev_hash": "x"})
        with self.assertRaises(chain_module.ChainError):
            ledger.append({"n": 1, "row_hash": "x"})

    def test_read_round_trips_appended_rows(self):
        ledger = HashChainLedger(self.path)
        ledger.append({"n": 1})
        ledger.append({"n": 2})
        rows = ledger.read()
        self.assertEqual([r["n"] for r in rows], [1, 2])

    def test_read_on_missing_file_is_empty(self):
        ledger = HashChainLedger(self.path)
        self.assertEqual(ledger.read(), [])

    def test_file_contains_one_json_object_per_line(self):
        ledger = HashChainLedger(self.path)
        ledger.append({"n": 1})
        ledger.append({"n": 2})
        lines = self.path.read_text(encoding="utf-8").strip().split("\n")
        self.assertEqual(len(lines), 2)
        for line in lines:
            json.loads(line)  # raises if not valid JSON


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "chain.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_file_verifies_ok(self):
        result = HashChainLedger(self.path).verify()
        self.assertTrue(result.ok)
        self.assertEqual(result.rows_checked, 0)

    def test_untouched_chain_verifies_ok(self):
        ledger = HashChainLedger(self.path)
        for i in range(5):
            ledger.append({"n": i})
        result = ledger.verify()
        self.assertTrue(result.ok)
        self.assertEqual(result.rows_checked, 5)
        self.assertIsNone(result.broken_at_line)

    def test_tampering_with_a_field_breaks_verification_at_that_line(self):
        ledger = HashChainLedger(self.path)
        ledger.append({"n": 1})
        ledger.append({"n": 2})
        ledger.append({"n": 3})

        lines = self.path.read_text(encoding="utf-8").splitlines()
        row2 = json.loads(lines[1])
        row2["n"] = 999  # tamper without recomputing row_hash
        lines[1] = json.dumps(row2)
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = ledger.verify()
        self.assertFalse(result.ok)
        self.assertEqual(result.broken_at_line, 2)
        self.assertIn("row_hash", result.reason)

    def test_deleting_a_row_breaks_the_next_rows_prev_hash(self):
        ledger = HashChainLedger(self.path)
        ledger.append({"n": 1})
        ledger.append({"n": 2})
        ledger.append({"n": 3})

        lines = self.path.read_text(encoding="utf-8").splitlines()
        del lines[1]  # remove the middle row entirely
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = ledger.verify()
        self.assertFalse(result.ok)
        self.assertEqual(result.broken_at_line, 2)
        self.assertIn("prev_hash", result.reason)

    def test_reordering_rows_breaks_verification(self):
        ledger = HashChainLedger(self.path)
        ledger.append({"n": 1})
        ledger.append({"n": 2})

        lines = self.path.read_text(encoding="utf-8").splitlines()
        lines.reverse()
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = ledger.verify()
        self.assertFalse(result.ok)

    def test_replacing_row_hash_with_a_forged_value_is_caught(self):
        ledger = HashChainLedger(self.path)
        ledger.append({"n": 1})

        lines = self.path.read_text(encoding="utf-8").splitlines()
        row = json.loads(lines[0])
        row["row_hash"] = "f" * 64
        lines[0] = json.dumps(row)
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = ledger.verify()
        self.assertFalse(result.ok)
        self.assertEqual(result.broken_at_line, 1)

    def test_missing_hash_field_is_reported(self):
        ledger = HashChainLedger(self.path)
        ledger.append({"n": 1})
        lines = self.path.read_text(encoding="utf-8").splitlines()
        row = json.loads(lines[0])
        del row["row_hash"]
        lines[0] = json.dumps(row)
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = ledger.verify()
        self.assertFalse(result.ok)
        self.assertEqual(result.broken_at_line, 1)

    def test_verify_result_bool_reflects_ok(self):
        result = HashChainLedger(self.path).verify()
        self.assertTrue(bool(result))


class FileSha256Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "f.txt"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_returns_none(self):
        self.assertIsNone(chain_module.file_sha256(self.path))

    def test_same_content_hashes_identically(self):
        self.path.write_text("hello")
        h1 = chain_module.file_sha256(self.path)
        h2 = chain_module.file_sha256(self.path)
        self.assertEqual(h1, h2)

    def test_different_content_hashes_differently(self):
        self.path.write_text("hello")
        h1 = chain_module.file_sha256(self.path)
        self.path.write_text("world")
        h2 = chain_module.file_sha256(self.path)
        self.assertNotEqual(h1, h2)


if __name__ == "__main__":
    unittest.main()
