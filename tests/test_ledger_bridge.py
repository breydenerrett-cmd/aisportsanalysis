"""tests for src.ledger.bridge: the v1/v2 ledger bridge's grew-vs-tampered
classification (`_classify_v1`) and the `verify()` report it feeds.

The bug this guards against: a v1 ledger that only ever grows by pure
append (the real, expected shape of `evidence/forward_ledger.jsonl`) must
never be reported as changed/tampered just because its whole-file sha256
no longer matches the one recorded at genesis time -- only a modification
inside the ALREADY-RECORDED prefix (an edit, a deleted/reordered row, a
truncation) is a tamper.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.ledger import bridge


def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line + "\n")


class ClassifyV1Test(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "forward_ledger.jsonl"

    def _hash_of(self, lines: list[str]) -> str:
        import hashlib
        h = hashlib.sha256()
        for line in lines:
            h.update((line + "\n").encode("utf-8"))
        return h.hexdigest()

    def test_untouched_when_whole_file_hash_matches(self):
        lines = ['{"a": 1}', '{"a": 2}']
        _write_lines(self.path, lines)
        recorded = self._hash_of(lines)
        result = bridge._classify_v1(self.path, recorded)
        self.assertEqual(result["status"], bridge.V1_UNTOUCHED)
        self.assertEqual(result["rows_recorded"], 2)
        self.assertEqual(result["rows_current"], 2)

    def test_grew_when_recorded_prefix_is_byte_identical(self):
        original = ['{"a": 1}', '{"a": 2}', '{"a": 3}']
        recorded = self._hash_of(original)
        # Real-world shape: 427 -> 451 by pure append. Here: 3 -> 5.
        grown = original + ['{"a": 4}', '{"a": 5}']
        _write_lines(self.path, grown)
        result = bridge._classify_v1(self.path, recorded)
        self.assertEqual(result["status"], bridge.V1_GREW)
        self.assertEqual(result["rows_recorded"], 3)
        self.assertEqual(result["rows_current"], 5)

    def test_tampered_when_an_old_row_is_edited(self):
        original = ['{"a": 1}', '{"a": 2}', '{"a": 3}']
        recorded = self._hash_of(original)
        tampered = ['{"a": 1}', '{"a": 999}', '{"a": 3}', '{"a": 4}']
        _write_lines(self.path, tampered)
        result = bridge._classify_v1(self.path, recorded)
        self.assertEqual(result["status"], bridge.V1_TAMPERED)
        self.assertIsNone(result["rows_recorded"])

    def test_tampered_when_a_row_is_deleted(self):
        original = ['{"a": 1}', '{"a": 2}', '{"a": 3}']
        recorded = self._hash_of(original)
        tampered = ['{"a": 1}', '{"a": 3}']  # row 2 removed, prefix broken
        _write_lines(self.path, tampered)
        result = bridge._classify_v1(self.path, recorded)
        self.assertEqual(result["status"], bridge.V1_TAMPERED)

    def test_tampered_when_rows_are_reordered(self):
        original = ['{"a": 1}', '{"a": 2}', '{"a": 3}']
        recorded = self._hash_of(original)
        tampered = ['{"a": 2}', '{"a": 1}', '{"a": 3}']
        _write_lines(self.path, tampered)
        result = bridge._classify_v1(self.path, recorded)
        self.assertEqual(result["status"], bridge.V1_TAMPERED)

    def test_tampered_when_file_shrinks_below_recorded_size(self):
        original = ['{"a": 1}', '{"a": 2}', '{"a": 3}']
        recorded = self._hash_of(original)
        _write_lines(self.path, original[:1])
        result = bridge._classify_v1(self.path, recorded)
        self.assertEqual(result["status"], bridge.V1_TAMPERED)

    def test_tampered_when_recorded_file_is_deleted_entirely(self):
        recorded = self._hash_of(['{"a": 1}'])
        # self.path never written -- simulates the anchored file vanishing.
        result = bridge._classify_v1(self.path, recorded)
        self.assertEqual(result["status"], bridge.V1_TAMPERED)
        self.assertEqual(result["rows_current"], 0)

    def test_untouched_when_recorded_hash_is_none_and_file_absent(self):
        result = bridge._classify_v1(self.path, None)
        self.assertEqual(result["status"], bridge.V1_UNTOUCHED)

    def test_grew_when_recorded_hash_is_none_but_file_now_has_rows(self):
        _write_lines(self.path, ['{"a": 1}'])
        result = bridge._classify_v1(self.path, None)
        self.assertEqual(result["status"], bridge.V1_GREW)
        self.assertEqual(result["rows_recorded"], 0)
        self.assertEqual(result["rows_current"], 1)

    def test_legacy_genesis_with_only_a_whole_file_hash_still_classifies(self):
        """A genesis row written before this fix carries nothing but a
        whole-file sha256 (no stored row count or byte length) -- proves no
        migration of old genesis rows is needed for correct classification."""
        original = ['{"kind": "genesis"}']
        recorded = self._hash_of(original)
        grown = original + ['{"a": "new"}']
        _write_lines(self.path, grown)
        result = bridge._classify_v1(self.path, recorded)
        self.assertEqual(result["status"], bridge.V1_GREW)


class VerifyReportTest(unittest.TestCase):
    """`verify()`'s report and `ok` flag over a real genesis + v1 pair, using
    its `v1_path`/`v2_path` overrides so this exercises the real `verify()`
    function (not just `_classify_v1`) without touching the real evidence
    stores."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.v1_path = Path(self._tmp.name) / "forward_ledger.jsonl"
        self.v2_path = Path(self._tmp.name) / "decisions_v2.jsonl"

    def test_grew_reports_ok_true(self):
        _write_lines(self.v1_path, ['{"a": 1}', '{"a": 2}'])
        bridge.ensure_genesis(self.v2_path, self.v1_path)
        _write_lines(self.v1_path, ['{"a": 1}', '{"a": 2}', '{"a": 3}'])
        report = bridge.verify(v1_path=self.v1_path, v2_path=self.v2_path)
        self.assertEqual(report["v1_status"], bridge.V1_GREW)
        self.assertTrue(report["v1_untouched"])  # "did v1 pass"
        self.assertTrue(report["ok"])
        self.assertEqual(report["v1_rows_recorded"], 2)
        self.assertEqual(report["v1_rows_current"], 3)

    def test_tampered_reports_ok_false(self):
        _write_lines(self.v1_path, ['{"a": 1}', '{"a": 2}'])
        bridge.ensure_genesis(self.v2_path, self.v1_path)
        _write_lines(self.v1_path, ['{"a": 1}', '{"a": 999}'])
        report = bridge.verify(v1_path=self.v1_path, v2_path=self.v2_path)
        self.assertEqual(report["v1_status"], bridge.V1_TAMPERED)
        self.assertFalse(report["v1_untouched"])
        self.assertFalse(report["ok"])

    def test_untouched_reports_ok_true(self):
        _write_lines(self.v1_path, ['{"a": 1}'])
        bridge.ensure_genesis(self.v2_path, self.v1_path)
        report = bridge.verify(v1_path=self.v1_path, v2_path=self.v2_path)
        self.assertEqual(report["v1_status"], bridge.V1_UNTOUCHED)
        self.assertTrue(report["ok"])


if __name__ == "__main__":
    unittest.main()
