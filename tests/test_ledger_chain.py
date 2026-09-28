"""tests for src.ledger.chain: the append-only hash-chained JSONL primitive."""

from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.ledger import chain as chain_module
from src.ledger.chain import (
    GENESIS_HASH,
    HashChainLedger,
    canonical_bytes,
    row_hash,
)
from src.pipeline import store_archive


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


class ArchiveAwareTests(unittest.TestCase):
    """`HashChainLedger.read()`/`verify()`/`last_hash()` against a manually
    laid-out archive segment + hot file -- never via
    `src.pipeline.store_archive.rotate()` itself, which is
    `tests/test_store_archive.py`'s job to prove correct. This isolates
    chain.py's OWN read/verify/last_hash contract (DESIGN: archive-aware via
    a lazy `store_archive` import) from whatever mechanism actually produced
    the split.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "chain.jsonl"

    def _split_into_segment_and_hot(self, n_in_segment: int):
        """A 5-row chain, built with real `append()` calls, then the first
        `n_in_segment` complete lines moved by hand into a gzip segment --
        the same shape a real rotation leaves behind, laid out directly so
        this test does not depend on `rotate()`'s own logic.
        """
        ledger = HashChainLedger(self.path)
        rows = [ledger.append({"n": i}) for i in range(5)]
        raw_lines = self.path.read_bytes().splitlines(keepends=True)

        seg_dir = self.path.parent / "archive" / self.path.stem
        seg_dir.mkdir(parents=True)
        segment = seg_dir / "0001_2026-01-01_2026-01-01.jsonl.gz"
        with open(segment, "wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
                gz.write(b"".join(raw_lines[:n_in_segment]))
        self.path.write_bytes(b"".join(raw_lines[n_in_segment:]))
        return rows, segment

    def test_read_and_verify_span_a_manually_built_segment_and_hot_file(self):
        rows, _ = self._split_into_segment_and_hot(3)
        self.assertEqual(HashChainLedger(self.path).read(), rows)
        self.assertEqual(list(HashChainLedger(self.path)), rows)

        result = HashChainLedger(self.path).verify()
        self.assertTrue(result.ok)
        self.assertEqual(result.rows_checked, 5)

    def test_tampering_a_row_inside_the_segment_reports_its_logical_line(self):
        rows, segment = self._split_into_segment_and_hot(3)
        with gzip.open(segment, "rt", encoding="utf-8") as fh:
            seg_rows = [json.loads(line) for line in fh if line.strip()]
        seg_rows[1]["n"] = 999  # tamper row 2 (logical line 2) without rehashing
        body = "".join(json.dumps(r, sort_keys=True) + "\n" for r in seg_rows).encode()
        with open(segment, "wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
                gz.write(body)

        result = HashChainLedger(self.path).verify()
        self.assertFalse(result.ok)
        self.assertEqual(result.broken_at_line, 2)

    def test_last_hash_uses_the_hot_file_alone_without_opening_the_archive(self):
        rows, _ = self._split_into_segment_and_hot(3)
        with mock.patch("gzip.open",
                        side_effect=AssertionError("must not open the archive "
                                                   "when the hot file has a row")):
            self.assertEqual(HashChainLedger(self.path).last_hash(), rows[-1]["row_hash"])

    def test_last_hash_falls_back_to_the_last_segment_when_hot_file_is_empty(self):
        rows, _ = self._split_into_segment_and_hot(5)  # everything moved to the segment
        self.path.write_bytes(b"")
        self.assertEqual(HashChainLedger(self.path).last_hash(), rows[-1]["row_hash"])

    def test_last_hash_falls_back_to_the_last_segment_when_hot_file_is_absent(self):
        rows, _ = self._split_into_segment_and_hot(5)
        self.path.unlink()
        self.assertEqual(HashChainLedger(self.path).last_hash(), rows[-1]["row_hash"])

    def test_append_after_a_manual_split_chains_to_the_true_last_row(self):
        rows, _ = self._split_into_segment_and_hot(3)
        new_row = HashChainLedger(self.path).append({"n": "new"})
        self.assertEqual(new_row["prev_hash"], rows[-1]["row_hash"])
        self.assertTrue(HashChainLedger(self.path).verify().ok)

    def test_a_path_with_no_archive_directory_is_completely_unaffected(self):
        ledger = HashChainLedger(self.path)
        rows = [ledger.append({"n": i}) for i in range(3)]
        self.assertEqual(store_archive.segments(self.path), [])
        self.assertFalse((self.path.parent / "archive").exists())
        self.assertEqual(ledger.read(), rows)
        self.assertEqual(ledger.last_hash(), rows[-1]["row_hash"])
        self.assertTrue(ledger.verify().ok)


if __name__ == "__main__":
    unittest.main()


class LastHashSplitsLinesLikeEveryOtherReader(unittest.TestCase):
    """2026-09-28 validation: last_hash() reads the hot file with the same
    b"\n"-only line rule as read()/verify() (store_archive.iter_lines). A
    bare carriage return inside a physical line, a torn CRLF write followed
    by an append, must look the same to all three: one merged line, never a
    clean boundary for one reader and a merged line for another."""

    def test_a_bare_carriage_return_is_not_a_line_boundary_for_last_hash(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chain.jsonl"
            ledger = HashChainLedger(path)
            ledger.append({"n": 1})
            second = ledger.append({"n": 2})
            raw = path.read_bytes()
            # The torn CRLF tail: the last row ends in a lone CR and the next
            # physical bytes are another row with no separator.
            torn = raw[:-1] + b"\r" + json.dumps(
                {"n": 3, "prev_hash": "x", "row_hash": "y"}).encode() + b"\n"
            path.write_bytes(torn)
            try:
                rows_seen = len(ledger.read())
            except ValueError:
                read_raised, rows_seen = True, None
            else:
                read_raised = False
            try:
                last = ledger.last_hash()
            except ValueError:
                last_raised, last = True, None
            else:
                last_raised = False
            self.assertEqual(read_raised, last_raised,
                             "read() and last_hash() must agree on the merged line")
            if not read_raised:
                self.assertEqual(rows_seen, 2)
                self.assertEqual(last, second["row_hash"])
