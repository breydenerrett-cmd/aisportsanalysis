"""Tests for src/model/seal.py.

A holdout is evidence only while unseen, and the discipline fails silently --
nothing normally counts the touches. The 2025 split in this project was evaluated
four times over an afternoon and would still have been reported as held-out.
"""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.model import seal
from src.model.seal import SealError


class TempSeal:
    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "seal.json"
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()
        return False


class TestSplitIdentity(unittest.TestCase):
    def test_identity_is_the_boundaries_not_a_name(self):
        # Renaming a split or rebuilding the table must not reset its count.
        self.assertEqual(seal.split_id("2025-01-01", "2025-02-01", 100),
                         seal.split_id("2025-01-01", "2025-02-01", 100))

    def test_different_boundaries_are_different_splits(self):
        self.assertNotEqual(seal.split_id("2025-01-01", "2025-02-01", 100),
                            seal.split_id("2025-01-01", "2025-03-01", 100))

    def test_different_row_counts_are_different_splits(self):
        self.assertNotEqual(seal.split_id("2025-01-01", "2025-02-01", 100),
                            seal.split_id("2025-01-01", "2025-02-01", 101))


class TestCounting(unittest.TestCase):
    def test_an_unseen_split_has_zero_evaluations(self):
        with TempSeal() as t:
            result = seal.status("2025-08-26", "2025-09-28", 456, path=t.path)
        self.assertEqual(result["evaluations"], 0)
        self.assertFalse(result["burned"])

    def test_the_first_evaluation_does_not_burn_the_split(self):
        with TempSeal() as t:
            result = seal.record_evaluation("2025-08-26", "2025-09-28", 456,
                                            path=t.path)
        self.assertEqual(result["evaluations"], 1)
        self.assertFalse(result["burned"])
        self.assertIsNone(result["warning"])

    def test_a_second_evaluation_burns_it(self):
        with TempSeal() as t:
            seal.record_evaluation("2025-08-26", "2025-09-28", 456, path=t.path)
            result = seal.record_evaluation("2025-08-26", "2025-09-28", 456,
                                            path=t.path)
        self.assertEqual(result["evaluations"], 2)
        self.assertTrue(result["burned"])
        self.assertIn("optimistically biased", result["warning"])

    def test_the_count_survives_a_reread(self):
        # The count must be durable, or restarting the process resets discipline.
        with TempSeal() as t:
            seal.record_evaluation("2025-08-26", "2025-09-28", 456, path=t.path)
            seal.record_evaluation("2025-08-26", "2025-09-28", 456, path=t.path)
            self.assertEqual(
                seal.status("2025-08-26", "2025-09-28", 456,
                            path=t.path)["evaluations"], 2)

    def test_reasons_are_retained(self):
        with TempSeal() as t:
            seal.record_evaluation("2025-08-26", "2025-09-28", 456,
                                   reason="locked model", path=t.path)
            result = seal.status("2025-08-26", "2025-09-28", 456, path=t.path)
        self.assertEqual(result["reasons"][0]["reason"], "locked model")

    def test_splits_are_counted_independently(self):
        with TempSeal() as t:
            seal.record_evaluation("2025-08-26", "2025-09-28", 456, path=t.path)
            seal.record_evaluation("2025-08-26", "2025-09-28", 456, path=t.path)
            other = seal.status("2024-08-26", "2024-09-28", 400, path=t.path)
        self.assertEqual(other["evaluations"], 0)
        self.assertFalse(other["burned"])


class TestDeclareBurned(unittest.TestCase):
    def test_history_predating_the_seal_can_be_declared(self):
        with TempSeal() as t:
            result = seal.declare_burned("2025-08-26", "2025-09-28", 456,
                                         reason="evaluated 4x in development",
                                         evaluations=4, path=t.path)
        self.assertEqual(result["evaluations"], 4)
        self.assertTrue(result["burned"])

    def test_a_declared_burn_is_marked_as_such_on_disk(self):
        with TempSeal() as t:
            seal.declare_burned("2025-08-26", "2025-09-28", 456,
                                reason="x", evaluations=4, path=t.path)
            record = seal.read_seal(t.path)["splits"][
                seal.split_id("2025-08-26", "2025-09-28", 456)]
        self.assertTrue(record["declared_burned"])

    def test_the_reason_is_required_to_be_recorded(self):
        with TempSeal() as t:
            seal.declare_burned("2025-08-26", "2025-09-28", 456,
                                reason="four development evaluations",
                                evaluations=4, path=t.path)
            result = seal.status("2025-08-26", "2025-09-28", 456, path=t.path)
        self.assertIn("four development", result["reasons"][0]["reason"])


class TestPersistence(unittest.TestCase):
    def test_missing_seal_reads_as_empty(self):
        self.assertEqual(seal.read_seal("/nonexistent/seal.json"), {"splits": {}})

    def test_corrupt_seal_raises_rather_than_resetting(self):
        # Silently treating a corrupt seal as empty would erase the count, which
        # is the exact discipline the file exists to enforce.
        with TempSeal() as t:
            t.path.parent.mkdir(parents=True, exist_ok=True)
            t.path.write_text("{not json}")
            with self.assertRaises(SealError):
                seal.read_seal(t.path)

    def test_malformed_seal_raises(self):
        with TempSeal() as t:
            t.path.write_text('{"wrong": "shape"}')
            with self.assertRaises(SealError):
                seal.read_seal(t.path)

    def test_default_seal_path_is_absolute(self):
        self.assertTrue(Path(seal.DEFAULT_SEAL).is_absolute())


class TestTheRealSplitIsRecorded(unittest.TestCase):
    """The actual 2025 split in this repo is declared burned. If someone re-seals
    or resets it, this test fails and they have to do it deliberately."""

    def test_the_2025_split_is_on_record_as_burned(self):
        result = seal.status("2025-08-26", "2025-09-28", 456)
        self.assertTrue(result["burned"])
        self.assertGreaterEqual(result["evaluations"], 4)


if __name__ == "__main__":
    unittest.main()
