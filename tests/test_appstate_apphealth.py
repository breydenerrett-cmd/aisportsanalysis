"""src/appstate/apphealth.py: process + store health for GET /health.

Stdlib-only, same fixture style as tests/test_appstate_users.py -- real
sqlite files and real jsonl stores on a tmp dir, not mocked I/O, because the
whole point of this module is telling a healthy store apart from a missing,
empty, or corrupt one (the honesty rule its own docstring states).
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.appstate import apphealth

NOW = datetime(2026, 8, 31, 20, 0, tzinfo=timezone.utc)


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


class CheckStoreTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_missing_store_reports_absent_never_zero(self):
        result = apphealth.check_store(self.root / "nope.jsonl", "observed_utc", now=NOW)
        self.assertFalse(result.present)
        self.assertIsNone(result.rows)
        self.assertIsNone(result.newest_row_age_seconds)
        self.assertEqual(result.status, "missing")
        self.assertIn("absent", result.reason)

    def test_present_but_empty_store_reads_as_zero_rows(self):
        path = self.root / "empty.jsonl"
        path.touch()
        result = apphealth.check_store(path, "observed_utc", now=NOW)
        self.assertTrue(result.present)
        self.assertEqual(result.rows, 0)
        self.assertIsNone(result.newest_row_age_seconds)
        self.assertEqual(result.status, "empty")

    def test_fresh_row_reports_a_small_age(self):
        path = self.root / "fresh.jsonl"
        observed = NOW - timedelta(minutes=5)
        _write_jsonl(path, [{"observed_utc": observed.isoformat()}])
        result = apphealth.check_store(path, "observed_utc", now=NOW)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.rows, 1)
        self.assertAlmostEqual(result.newest_row_age_seconds, 300, delta=1)

    def test_newest_of_several_rows_is_picked_not_the_last_line(self):
        path = self.root / "many.jsonl"
        older = NOW - timedelta(hours=2)
        newer = NOW - timedelta(minutes=1)
        # Newest row written FIRST -- proves this isn't just "last line wins".
        _write_jsonl(path, [{"observed_utc": newer.isoformat()},
                            {"observed_utc": older.isoformat()}])
        result = apphealth.check_store(path, "observed_utc", now=NOW)
        self.assertAlmostEqual(result.newest_row_age_seconds, 60, delta=1)

    def test_corrupt_line_costs_one_row_not_the_store(self):
        path = self.root / "corrupt.jsonl"
        observed = NOW - timedelta(minutes=1)
        path.write_text(
            '{"observed_utc": "' + observed.isoformat() + '"}\n'
            '{"observed_utc": "2026-08-3\n',  # truncated / corrupt line
            encoding="utf-8")
        result = apphealth.check_store(path, "observed_utc", now=NOW)
        self.assertEqual(result.rows, 2)
        self.assertEqual(result.status, "ok")
        self.assertAlmostEqual(result.newest_row_age_seconds, 60, delta=1)

    def test_rows_present_but_no_parseable_timestamp_is_unreadable_not_ok(self):
        path = self.root / "no_ts.jsonl"
        _write_jsonl(path, [{"poll": True}])
        result = apphealth.check_store(path, "observed_utc", now=NOW)
        self.assertEqual(result.status, "unreadable")
        self.assertEqual(result.rows, 1)
        self.assertIsNone(result.newest_row_age_seconds)

    def test_watch_store_timestamp_field_is_fetched_utc(self):
        path = self.root / "watch.jsonl"
        observed = NOW - timedelta(minutes=10)
        _write_jsonl(path, [{"fetched_utc": observed.isoformat(), "poll": True}])
        result = apphealth.check_store(path, "fetched_utc", now=NOW)
        self.assertEqual(result.status, "ok")
        self.assertAlmostEqual(result.newest_row_age_seconds, 600, delta=1)


class CheckAppDbTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_a_fresh_path_is_reachable_sqlite_creates_it_on_connect(self):
        db = self.root / "new.db"
        result = apphealth.check_app_db(db)
        self.assertTrue(result.reachable)
        self.assertIsNone(result.reason)

    def test_a_directory_at_the_db_path_is_unreachable_with_a_reason(self):
        bad = self.root / "not_a_file"
        bad.mkdir()
        result = apphealth.check_app_db(bad)
        self.assertFalse(result.reachable)
        self.assertIsNotNone(result.reason)

    def test_a_corrupt_sqlite_file_is_unreachable(self):
        bad = self.root / "corrupt.db"
        bad.write_bytes(b"not a real sqlite file at all, just garbage bytes")
        result = apphealth.check_app_db(bad)
        self.assertFalse(result.reachable)


class ReportTests(unittest.TestCase):
    """The combined /health payload -- overall status must track the
    honesty rule, not just parrot 'ok'."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.db = self.root / "app.db"

    def _fresh_forward_stores(self):
        observed = NOW - timedelta(minutes=5)
        for subdir, filename, field in apphealth.FORWARD_STORES.values():
            _write_jsonl(self.root / subdir / filename,
                        [{field: observed.isoformat()}])
        _write_jsonl(self.root / "processed" / "odds_multibook.jsonl",
                    [{"observed_utc": observed.isoformat()}])

    def test_fully_populated_stores_and_reachable_db_report_ok(self):
        self._fresh_forward_stores()
        data = apphealth.report(data_dir=self.root, db_path=self.db, now=NOW)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["reasons"], [])
        self.assertTrue(data["app_db"]["reachable"])
        self.assertEqual(data["odds"]["odds_multibook"]["status"], "ok")
        for name in apphealth.FORWARD_STORES:
            self.assertEqual(data["forward_captures"][name]["status"], "ok")

    def test_all_stores_absent_is_reported_honestly_not_faked_ok(self):
        """A brand-new checkout with no captures yet -- every store missing,
        db reachable. This must never read as a clean bill of health with
        fabricated freshness; every store says 'missing' by name."""
        data = apphealth.report(data_dir=self.root, db_path=self.db, now=NOW)
        self.assertTrue(data["app_db"]["reachable"])
        self.assertEqual(data["odds"]["odds_multibook"]["status"], "missing")
        for name in apphealth.FORWARD_STORES:
            self.assertEqual(data["forward_captures"][name]["status"], "missing")
        # Missing stores alone (fresh env) don't flip the top-level flag --
        # only an unreachable db or a store that IS present but unreadable
        # does. See module docstring for why.
        self.assertEqual(data["status"], "ok")

    def test_unreachable_db_flips_overall_status_to_degraded(self):
        bad_db = self.root / "is_a_dir"
        bad_db.mkdir()
        self._fresh_forward_stores()
        data = apphealth.report(data_dir=self.root, db_path=bad_db, now=NOW)
        self.assertFalse(data["app_db"]["reachable"])
        self.assertEqual(data["status"], "degraded")
        self.assertTrue(any("app db unreachable" in r for r in data["reasons"]))

    def test_an_unreadable_present_store_flips_overall_status_to_degraded(self):
        self._fresh_forward_stores()
        _write_jsonl(self.root / "processed" / "odds_multibook.jsonl",
                    [{"poll": True}])  # present, but no usable timestamp
        data = apphealth.report(data_dir=self.root, db_path=self.db, now=NOW)
        self.assertEqual(data["odds"]["odds_multibook"]["status"], "unreadable")
        self.assertEqual(data["status"], "degraded")
        self.assertTrue(any("odds_multibook" in r for r in data["reasons"]))

    def test_report_never_contains_a_token_or_email_shaped_string(self):
        """No secrets in output -- a sanity net, not proof of absence."""
        self._fresh_forward_stores()
        data = apphealth.report(data_dir=self.root, db_path=self.db, now=NOW)
        blob = json.dumps(data)
        self.assertNotIn("token", blob.lower())
        self.assertNotIn("@", blob)


if __name__ == "__main__":
    unittest.main()
