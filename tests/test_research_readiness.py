"""Tests for scripts/research_readiness.py's behavioural escalation.

WHY THIS EXISTS
----------------
Before 2026-09-15, `src/research/battery.run` was not wired into
`src/engine/settle_slate.py`, so every scorecard read `battery_verdict:
NOT_RUN` no matter what -- and `scripts/research_readiness.py` escalated
unconditionally the moment a forward-test system crossed `battery.MIN_N`
graded selections, correctly, because there was nothing else to check: data
readiness WAS the whole story.

Now the wiring exists (`run_settle` computes a real battery verdict for
every system with >= `battery.MIN_N` point-in-time graded selections and
passes it to `build_scorecard`). Escalating on readiness alone would now
print a stale claim ("the wiring doesn't exist yet") forever, even after the
first daily settle actually ran it. So the script now also reads each ready
system's LATEST scorecard row (`evidence/scorecards_v2.jsonl`, named by
`src.ledger.writer.SCORECARD_LEDGER_PATH`) and escalates only when that row
is still `NOT_RUN` or does not exist yet -- the behavioural question, not
just the data-readiness one.

These tests exercise `compute_readiness`/`format_report`/
`latest_battery_verdicts` directly with a fabricated `forward` dict (fake
selection counts -- no evidence/ file is ever read) and temp-directory
scorecard ledgers, per the task's own seam requirement.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import escalations
from scripts.research_readiness import (
    NOT_RUN,
    compute_readiness,
    format_report,
    latest_battery_verdicts,
)
from src.research import battery

MIN_N = battery.MIN_N  # 30 today; every test derives from this, never hardcodes it
LEDGER = Path(__file__).resolve().parent.parent / "docs" / "ESCALATIONS.md"

# The exact substring docs/ESCALATIONS.md's research-readiness-battery row
# matches on -- see that row's `pattern` cell. Must survive verbatim inside
# the new ESCALATE wording so the line stays acknowledged (KNOWN) rather
# than paging as a brand-new escalation.
ACKNOWLEDGED_SUBSTRING = f"forward-test system(s) now have {MIN_N}+ graded selections"


def _write_scorecard_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _row(system_id: str, window: str, verdict: str) -> dict:
    """A minimal scorecard-shaped row -- only the fields
    `latest_battery_verdicts` reads. Real rows carry many more fields
    (see src/ledger/records.py's Scorecard) plus prev_hash/row_hash, but
    the function under test ignores anything it does not need."""
    return {"system_id": system_id, "window": window, "battery_verdict": verdict}


def _ready_forward(system_id: str, n: int = MIN_N) -> dict:
    """A `forward` dict with one system carrying `n` fake graded rows --
    real callers build this from `graded_by_system()` + `engine_bridge`;
    tests fabricate it directly so nothing under evidence/ is ever read."""
    return {system_id: [{"date": "2026-09-01", "won": True, "implied": 0.5}] * n}


# ---------------------------------------------------------------------------
# latest_battery_verdicts
# ---------------------------------------------------------------------------

class LatestBatteryVerdictsTest(unittest.TestCase):
    def test_single_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scorecards_v2.jsonl"
            _write_scorecard_rows(path, [_row("sys_a", "2026-09-10", "PASS")])
            latest = latest_battery_verdicts({"sys_a"}, path)
        self.assertEqual(latest["sys_a"], ("2026-09-10", "PASS"))

    def test_newest_window_wins_over_older_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scorecards_v2.jsonl"
            _write_scorecard_rows(path, [
                _row("sys_a", "2026-09-05", "PASS"),
                _row("sys_a", "2026-09-12", NOT_RUN),
            ])
            latest = latest_battery_verdicts({"sys_a"}, path)
        self.assertEqual(latest["sys_a"], ("2026-09-12", NOT_RUN))

    def test_out_of_order_file_still_picks_newest_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scorecards_v2.jsonl"
            _write_scorecard_rows(path, [
                _row("sys_a", "2026-09-12", "FAILED"),
                _row("sys_a", "2026-09-05", "PASS"),
            ])
            latest = latest_battery_verdicts({"sys_a"}, path)
        self.assertEqual(latest["sys_a"], ("2026-09-12", "FAILED"))

    def test_missing_ledger_returns_empty_without_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "does_not_exist.jsonl"
            latest = latest_battery_verdicts({"sys_a"}, path)
        self.assertEqual(latest, {})

    def test_malformed_lines_are_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scorecards_v2.jsonl"
            path.write_text(
                "not json at all\n"
                + json.dumps(_row("sys_a", "2026-09-10", "PASS")) + "\n"
                + "{also not valid\n",
                encoding="utf-8",
            )
            latest = latest_battery_verdicts({"sys_a"}, path)
        self.assertEqual(latest["sys_a"], ("2026-09-10", "PASS"))

    def test_other_systems_and_windowless_rows_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scorecards_v2.jsonl"
            _write_scorecard_rows(path, [
                _row("sys_other", "2026-09-10", "PASS"),
                {"system_id": "sys_a", "battery_verdict": "PASS"},  # no window
            ])
            latest = latest_battery_verdicts({"sys_a"}, path)
        self.assertNotIn("sys_a", latest)


# ---------------------------------------------------------------------------
# compute_readiness
# ---------------------------------------------------------------------------

class ComputeReadinessTest(unittest.TestCase):
    def test_ready_system_with_pass_lands_in_ran(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scorecards_v2.jsonl"
            _write_scorecard_rows(path, [_row("sys_a", "2026-09-14", "PASS")])
            readiness = compute_readiness(_ready_forward("sys_a"), path)
        self.assertEqual(readiness["ready"], ["sys_a"])
        self.assertEqual(readiness["ran"], ["sys_a"])
        self.assertEqual(readiness["not_run"], [])

    def test_ready_system_with_not_run_lands_in_not_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scorecards_v2.jsonl"
            _write_scorecard_rows(path, [_row("sys_a", "2026-09-14", NOT_RUN)])
            readiness = compute_readiness(_ready_forward("sys_a"), path)
        self.assertEqual(readiness["not_run"], ["sys_a"])
        self.assertEqual(readiness["ran"], [])

    def test_ready_system_with_no_row_lands_in_not_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scorecards_v2.jsonl"
            _write_scorecard_rows(path, [_row("sys_other", "2026-09-14", "PASS")])
            readiness = compute_readiness(_ready_forward("sys_a"), path)
        self.assertEqual(readiness["not_run"], ["sys_a"])

    def test_older_pass_then_newer_not_run_escalates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scorecards_v2.jsonl"
            _write_scorecard_rows(path, [
                _row("sys_a", "2026-09-01", "PASS"),
                _row("sys_a", "2026-09-14", NOT_RUN),
            ])
            readiness = compute_readiness(_ready_forward("sys_a"), path)
        self.assertEqual(readiness["not_run"], ["sys_a"])
        self.assertEqual(readiness["ran"], [])

    def test_missing_ledger_is_not_run_and_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "no_such_file.jsonl"
            readiness = compute_readiness(_ready_forward("sys_a"), path)
        self.assertFalse(readiness["ledger_existed"])
        self.assertEqual(readiness["not_run"], ["sys_a"])

    def test_below_floor_system_never_counted_even_with_stale_not_run_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scorecards_v2.jsonl"
            _write_scorecard_rows(path, [_row("sys_a", "2026-09-14", NOT_RUN)])
            below_floor = {"sys_a": [{"date": "2026-09-01", "won": True,
                                      "implied": 0.5}] * (MIN_N - 1)}
            readiness = compute_readiness(below_floor, path)
        self.assertEqual(readiness["ready"], [])
        self.assertEqual(readiness["ran"], [])
        self.assertEqual(readiness["not_run"], [])

    def test_mixed_ready_systems_only_the_not_run_one_escalates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scorecards_v2.jsonl"
            _write_scorecard_rows(path, [
                _row("sys_pass", "2026-09-14", "PASS"),
                _row("sys_stale", "2026-09-14", NOT_RUN),
            ])
            forward = {**_ready_forward("sys_pass"), **_ready_forward("sys_stale")}
            readiness = compute_readiness(forward, path)
        self.assertEqual(sorted(readiness["ran"]), ["sys_pass"])
        self.assertEqual(sorted(readiness["not_run"]), ["sys_stale"])


# ---------------------------------------------------------------------------
# format_report -- the printed ESCALATE / INFO wording
# ---------------------------------------------------------------------------

class FormatReportTest(unittest.TestCase):
    def test_not_run_system_prints_escalate_with_acknowledged_substring(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scorecards_v2.jsonl"
            _write_scorecard_rows(path, [_row("sys_a", "2026-09-14", NOT_RUN)])
            forward = _ready_forward("sys_a")
            readiness = compute_readiness(forward, path)
            text = format_report(readiness, len(forward), path)
        escalate_lines = [l for l in text.splitlines() if l.startswith("ESCALATE:")]
        self.assertEqual(len(escalate_lines), 1)
        self.assertIn(ACKNOWLEDGED_SUBSTRING, escalate_lines[0])
        self.assertIn("NOT_RUN", escalate_lines[0])
        self.assertIn("sys_a", escalate_lines[0])
        self.assertNotIn("INFO:", text)

    def test_no_row_system_prints_escalate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scorecards_v2.jsonl"
            path.write_text("", encoding="utf-8")
            forward = _ready_forward("sys_a")
            readiness = compute_readiness(forward, path)
            text = format_report(readiness, len(forward), path)
        self.assertTrue(any(l.startswith("ESCALATE:") for l in text.splitlines()))

    def test_all_ready_systems_ran_prints_info_not_escalate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scorecards_v2.jsonl"
            _write_scorecard_rows(path, [_row("sys_a", "2026-09-14", "PASS")])
            forward = _ready_forward("sys_a")
            readiness = compute_readiness(forward, path)
            text = format_report(readiness, len(forward), path)
        self.assertFalse(any(l.startswith("ESCALATE:") for l in text.splitlines()))
        info_lines = [l for l in text.splitlines() if l.startswith("INFO:")]
        self.assertEqual(len(info_lines), 1)
        self.assertIn("battery ran on 1 of 1 ready systems", info_lines[0])
        self.assertIn("sys_a=PASS", info_lines[0])

    def test_no_ready_systems_prints_not_yet_no_escalate_no_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scorecards_v2.jsonl"
            forward = {"sys_a": [{"date": "2026-09-01", "won": True,
                                  "implied": 0.5}] * (MIN_N - 5)}
            readiness = compute_readiness(forward, path)
            text = format_report(readiness, len(forward), path)
        self.assertIn("VERDICT: NOT YET", text)
        self.assertFalse(any(l.startswith("ESCALATE:") for l in text.splitlines()))
        self.assertNotIn("INFO:", text)

    def test_missing_ledger_notes_it_in_one_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "no_such_file.jsonl"
            forward = _ready_forward("sys_a")
            readiness = compute_readiness(forward, path)
            text = format_report(readiness, len(forward), path)
        note_lines = [l for l in text.splitlines() if "scorecard ledger not found" in l]
        self.assertEqual(len(note_lines), 1)


# ---------------------------------------------------------------------------
# Cross-check: the new ESCALATE wording still classifies KNOWN against the
# real, checked-in docs/ESCALATIONS.md ledger (scripts/escalations.py's own
# substring-match rule) -- the whole reason the substring was preserved.
# ---------------------------------------------------------------------------

class NewEscalateLineStaysAcknowledgedTest(unittest.TestCase):
    def test_generated_escalate_line_classifies_known_against_real_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scorecards_v2.jsonl"
            _write_scorecard_rows(path, [_row("sys_a", "2026-09-14", NOT_RUN)])
            forward = _ready_forward("sys_a")
            readiness = compute_readiness(forward, path)
            text = format_report(readiness, len(forward), path)
        escalate_line = next(l for l in text.splitlines()
                             if l.startswith("ESCALATE:"))
        ledger = escalations.parse_ledger(LEDGER)
        classified = escalations.classify([escalate_line], ledger)
        self.assertEqual(classified, [(escalate_line, "KNOWN")])


if __name__ == "__main__":
    unittest.main()
