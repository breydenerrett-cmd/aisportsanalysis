"""The card-calibration staleness check must not accuse a refit that no
longer exists.

On 2026-09-15 the owner froze the card calibration
(docs/CARD_CALIBRATION_FREEZE_2026-09-15.md): scripts/daily_loop.sh no
longer calls scripts/fit_card_calibration.py, so the old staleness
message -- "the nightly refit in scripts/daily_loop.sh has been failing
quietly" -- would become false the moment the frozen fit passed
CALIBRATION_STALE_DAYS, and scripts/capture_slot.sh runs the audit about 96
times a day, so a false accusation would repeat constantly in the ops log.

These tests pin the fix at the level of `_calibration_findings`, the seam
split out of `audit_card` for exactly this reason: `audit_card` itself
reaches into the real card ledger and calibration store through
`src.appstate.card_ledger` and `src.report.card`, and this suite must not
read or write either. Every calibration file and freeze marker here lives
under a `tempfile.TemporaryDirectory()`.
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.publication_audit import (
    CALIBRATION_STALE_DAYS,
    calibration_freeze_marker,
    _calibration_findings,
)

NOW = datetime(2026, 9, 15, tzinfo=timezone.utc)
LABEL = "data/processed/card_calibration.json"


def _severities(findings):
    return {sev for sev, _ in findings}


def _blob(findings):
    return " ".join(msg for _sev, msg in findings)


class CalibrationFreezeMarkerLookup(unittest.TestCase):
    """calibration_freeze_marker() reads docs/CARD_CALIBRATION_FREEZE_*.md
    relative to whatever `repo` it is given -- never the real repo root in
    these tests."""

    def test_no_docs_dir_is_no_marker(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(calibration_freeze_marker(repo=Path(td)))

    def test_no_matching_file_is_no_marker(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "docs").mkdir()
            (repo / "docs" / "SOMETHING_ELSE.md").write_text("x")
            self.assertIsNone(calibration_freeze_marker(repo=repo))

    def test_one_marker_is_found(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "docs").mkdir()
            marker = repo / "docs" / "CARD_CALIBRATION_FREEZE_2026-09-15.md"
            marker.write_text("freeze record")
            self.assertEqual(calibration_freeze_marker(repo=repo), marker)

    def test_a_later_dated_marker_is_also_found(self):
        """A future freeze record, with a different date in the filename,
        must be picked up with no code change -- that is the point of
        globbing rather than hardcoding the 2026-09-15 name."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "docs").mkdir()
            older = repo / "docs" / "CARD_CALIBRATION_FREEZE_2026-09-15.md"
            newer = repo / "docs" / "CARD_CALIBRATION_FREEZE_2027-01-05.md"
            older.write_text("older")
            newer.write_text("newer")
            self.assertEqual(calibration_freeze_marker(repo=repo), newer)


class CalibrationFindingsUnfrozen(unittest.TestCase):
    """No freeze marker: behaviour must be exactly what it was before."""

    def test_stale_calibration_warns_with_the_original_message(self):
        with tempfile.TemporaryDirectory() as td:
            cal_path = Path(td) / "card_calibration.json"
            fitted_at = NOW - timedelta(days=30)
            cal_path.write_text(json.dumps({
                "a": 0.028644, "b": 0.735183,
                "fitted_at": fitted_at.isoformat()}))

            findings = _calibration_findings(
                cal_path, LABEL, NOW, freeze_marker=None)

        self.assertEqual(_severities(findings), {"WARN"})
        blob = _blob(findings)
        self.assertIn("failing quietly", blob)
        self.assertIn("scripts/daily_loop.sh", blob)
        self.assertIn("30 days ago", blob)
        self.assertIn(f"limit {CALIBRATION_STALE_DAYS}", blob)

    def test_fresh_calibration_is_clean(self):
        with tempfile.TemporaryDirectory() as td:
            cal_path = Path(td) / "card_calibration.json"
            fitted_at = NOW - timedelta(hours=3)
            cal_path.write_text(json.dumps({
                "a": 0.028644, "b": 0.735183,
                "fitted_at": fitted_at.isoformat()}))

            findings = _calibration_findings(
                cal_path, LABEL, NOW, freeze_marker=None)

        self.assertEqual(findings, [])

    def test_missing_file_escalates(self):
        with tempfile.TemporaryDirectory() as td:
            cal_path = Path(td) / "does_not_exist.json"
            findings = _calibration_findings(
                cal_path, LABEL, NOW, freeze_marker=None)

        self.assertEqual(_severities(findings), {"ESCALATE"})
        self.assertIn("is missing", _blob(findings))
        self.assertIn(LABEL, _blob(findings))

    def test_unreadable_file_escalates(self):
        with tempfile.TemporaryDirectory() as td:
            cal_path = Path(td) / "corrupt.json"
            cal_path.write_text("{not valid json")
            findings = _calibration_findings(
                cal_path, LABEL, NOW, freeze_marker=None)

        self.assertEqual(_severities(findings), {"ESCALATE"})
        self.assertIn("could not be read", _blob(findings))


class CalibrationFindingsFrozen(unittest.TestCase):
    """A freeze marker is present: the "failing quietly" accusation must
    never appear, and the two ESCALATE checks must still fire."""

    def _marker(self, repo):
        (repo / "docs").mkdir(exist_ok=True)
        marker = repo / "docs" / "CARD_CALIBRATION_FREEZE_2026-09-15.md"
        marker.write_text("freeze record")
        return marker

    def test_stale_calibration_produces_no_failing_quietly_claim(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            marker = self._marker(repo)
            cal_path = repo / "card_calibration.json"
            fitted_at = NOW - timedelta(days=30)
            cal_path.write_text(json.dumps({
                "a": 0.028644, "b": 0.735183,
                "fitted_at": fitted_at.isoformat()}))

            findings = _calibration_findings(
                cal_path, LABEL, NOW, freeze_marker=marker)

        blob = _blob(findings)
        self.assertNotIn("failing quietly", blob)
        # Option (a): the staleness finding is skipped entirely while
        # frozen, not reworded -- see _calibration_findings' docstring.
        self.assertEqual(findings, [])

    def test_fresh_calibration_inside_the_limit_is_clean(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            marker = self._marker(repo)
            cal_path = repo / "card_calibration.json"
            fitted_at = NOW - timedelta(hours=3)
            cal_path.write_text(json.dumps({
                "a": 0.028644, "b": 0.735183,
                "fitted_at": fitted_at.isoformat()}))

            findings = _calibration_findings(
                cal_path, LABEL, NOW, freeze_marker=marker)

        self.assertEqual(findings, [])

    def test_missing_file_still_escalates_while_frozen(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            marker = self._marker(repo)
            cal_path = repo / "does_not_exist.json"

            findings = _calibration_findings(
                cal_path, LABEL, NOW, freeze_marker=marker)

        self.assertEqual(_severities(findings), {"ESCALATE"})
        self.assertIn("is missing", _blob(findings))

    def test_unreadable_file_still_escalates_while_frozen(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            marker = self._marker(repo)
            cal_path = repo / "corrupt.json"
            cal_path.write_text("{not valid json")

            findings = _calibration_findings(
                cal_path, LABEL, NOW, freeze_marker=marker)

        self.assertEqual(_severities(findings), {"ESCALATE"})
        self.assertIn("could not be read", _blob(findings))


if __name__ == "__main__":
    unittest.main()
