"""Tests for src/pipeline/creditlog.py. Hermetic: every write goes to a
tempfile store, never to data/processed/credit_log.jsonl."""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.pipeline import creditlog

NOW = dt.datetime(2026, 9, 2, 12, 0, tzinfo=dt.timezone.utc)


class LoggingTests(unittest.TestCase):
    def test_a_row_carries_the_four_documented_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            ok = creditlog.log(48213, 3, "dense.run", store=store, now=NOW)
            rows = creditlog.read(store)
        self.assertTrue(ok)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(set(row), {"utc", "credits_remaining",
                                     "credits_used_last", "caller"})
        self.assertEqual(row["credits_remaining"], 48213)
        self.assertEqual(row["credits_used_last"], 3)
        self.assertEqual(row["caller"], "dense.run")
        self.assertEqual(row["utc"], "2026-09-02T12:00:00Z")

    def test_a_none_used_last_is_stored_as_null_not_invented(self):
        # The sports-list endpoint always returns x-requests-last, but a
        # caller reading it must not pretend to know a number it was never
        # given.
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            creditlog.log(100, None, "prop_listing.run", store=store, now=NOW)
            row = creditlog.read(store)[0]
        self.assertIsNone(row["credits_used_last"])

    def test_repeated_calls_append_never_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            creditlog.log(100, 1, "a", store=store, now=NOW)
            creditlog.log(97, 3, "b", store=store,
                         now=NOW + dt.timedelta(minutes=15))
            rows = creditlog.read(store)
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["caller"] for r in rows], ["a", "b"])

    def test_an_interrupted_append_does_not_corrupt_the_next_row(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            store.write_text('{"utc":"a","credits_remaining":1}\n'
                             '{"utc":"b","credits_rem', encoding="utf-8")
            creditlog.log(99, 1, "c", store=store, now=NOW)
            lines = store.read_text(encoding="utf-8").splitlines()
            rows = creditlog.read(store)
        self.assertEqual(len(lines), 3)
        self.assertEqual(len(rows), 2)  # the fragment is skipped, not merged
        self.assertEqual(json.loads(lines[2])["caller"], "c")


class LatestTests(unittest.TestCase):
    def test_latest_is_none_for_a_missing_store(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "does_not_exist.jsonl"
            self.assertIsNone(creditlog.latest(store))

    def test_latest_is_none_for_an_empty_store(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            store.write_text("", encoding="utf-8")
            self.assertIsNone(creditlog.latest(store))

    def test_latest_is_the_last_appended_row_not_the_biggest_balance(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            creditlog.log(500, 1, "first", store=store, now=NOW)
            creditlog.log(50, 400, "second", store=store,
                         now=NOW + dt.timedelta(hours=1))
            latest = creditlog.latest(store)
        self.assertEqual(latest["caller"], "second")
        self.assertEqual(latest["credits_remaining"], 50)


class NeverRaisesTests(unittest.TestCase):
    """The critical-path contract: a log write must never break its caller."""

    def test_log_returns_false_rather_than_raising_on_a_write_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            # A directory where the store file should be: opening it for
            # append raises IsADirectoryError, which log() must swallow.
            store = Path(folder) / "credit_log.jsonl"
            store.mkdir()
            ok = creditlog.log(1, 1, "caller", store=store, now=NOW)
        self.assertFalse(ok)

    def test_log_swallows_a_write_guard_style_exception(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            with mock.patch.object(Path, "open",
                                   side_effect=RuntimeError("blocked")):
                ok = creditlog.log(1, 1, "caller", store=store, now=NOW)
        self.assertFalse(ok)

    def test_a_naive_clock_is_rejected_but_still_returns_false(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            naive = dt.datetime(2026, 9, 2, 12, 0)  # no tzinfo
            ok = creditlog.log(1, 1, "caller", store=store, now=naive)
        self.assertFalse(ok)


class MainTests(unittest.TestCase):
    def test_main_reports_no_rows_yet_for_an_empty_store(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            with mock.patch("builtins.print") as fake_print:
                creditlog.main(store=store)
            fake_print.assert_called_once()
            self.assertIn("no rows yet", fake_print.call_args[0][0])

    def test_main_prints_the_latest_row(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "credit_log.jsonl"
            creditlog.log(4200, 3, "dense.run", store=store, now=NOW)
            with mock.patch("builtins.print") as fake_print:
                creditlog.main(store=store)
            printed = fake_print.call_args[0][0]
        self.assertIn("4200", printed)
        self.assertIn("dense.run", printed)


if __name__ == "__main__":
    unittest.main()
