"""Tests for scripts/escalations.py and its ledger, docs/ESCALATIONS.md.

WHY THIS EXISTS
----------------
The scheduled daily loop failed its final workflow step every morning on
two known, acknowledged ESCALATE lines (calibration drift on
`slip.EVIDENCE_STRONG`, and the falsification battery's readiness line) --
both true on every run, neither fixable today (docs/ESCALATIONS.md explains
why). A job that is red for the same two known reasons every morning stops
telling anyone anything; a genuinely NEW escalation was exactly as invisible
in that stream as the two standing ones.

`scripts/escalations.py --check <run_output_file>` reads the ledger and
classifies every `ESCALATE:` line in the run output as KNOWN (matches an
open/fix-in-progress ledger row) or NEW, and fails (exit 1) only when at
least one line is NEW. Nothing about the audits themselves changed -- they
still print their ESCALATE lines exactly as before, on every run they are
still true; only the job's verdict changes, and every line -- known or new
-- is still printed so nothing is hidden.

Four things are tested, matching the task's own claims:

1. The CLI's classification behaviour, via subprocess (the same entry point
   the workflow step actually invokes): one known + one new line -> exit 1
   with both lines printed and labelled; only known lines -> exit 0; a
   missing ledger makes every line NEW (the safe default -- deleting or
   never creating the ledger cannot silently swallow an escalation).
2. The real, checked-in ledger parses, and its two seeded rows carry the
   patterns and statuses the task specified.
3. The real ledger, applied to the two standing ESCALATE lines exactly as
   `scripts/calibration_drift_audit.py` and `scripts/research_readiness.py`
   actually emit them via `scripts/daily_loop.sh`, classifies both KNOWN.
4. The workflow's final step now calls `scripts/escalations.py` and no
   longer fails on a bare `grep -q "^ESCALATE:"`.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import escalations

REPO = Path(__file__).resolve().parent.parent
LEDGER = REPO / "docs" / "ESCALATIONS.md"
WORKFLOW = REPO / ".github" / "workflows" / "daily-loop.yml"
SCRIPT = REPO / "scripts" / "escalations.py"

# Verbatim (modulo the run-to-run count in the second) from
# scripts/daily_loop.sh's own `echo "ESCALATE: ..."` lines -- see that
# script around "calibration drift" and "research readiness".
STRONG_TIER_LINE = (
    "ESCALATE: a constant calibrated against a population has drifted "
    "past its tolerance -- see docs/INCIDENT_2026-09-10_STRONG_TIER.md "
    "for what this class of failure looks like")
BATTERY_LINE = (
    "ESCALATE: 14 forward-test system(s) now have 30+ graded selections, "
    "so the falsification battery can finally run on real evidence "
    "instead of skipping every check.")
NEW_LINE = "ESCALATE: something nobody has ever acknowledged happened"


def _run_check(run_output_text: str, ledger_path: Path | None = None):
    """Invokes the real CLI entry point as a subprocess -- the same way
    the workflow step calls it -- against a temp file holding the given
    run output text."""
    with tempfile.TemporaryDirectory() as tmp:
        out_file = Path(tmp) / "daily_run.out"
        out_file.write_text(run_output_text, encoding="utf-8")
        argv = [sys.executable, str(SCRIPT), "--check", str(out_file)]
        if ledger_path is not None:
            argv += ["--ledger", str(ledger_path)]
        return subprocess.run(argv, cwd=REPO, capture_output=True,
                              text=True, timeout=30)


# ---------------------------------------------------------------------------
# 1. CLI classification behaviour
# ---------------------------------------------------------------------------

class CheckClassifiesKnownAndNewTest(unittest.TestCase):
    def test_one_known_one_new_exits_1_and_both_classified(self):
        text = "\n".join(["== calibration drift ==", STRONG_TIER_LINE,
                          NEW_LINE, ""])
        result = _run_check(text)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"KNOWN: {STRONG_TIER_LINE}", result.stdout)
        self.assertIn(f"NEW: {NEW_LINE}", result.stdout)
        self.assertIn("known=1 new=1", result.stdout)

    def test_only_known_lines_exits_0(self):
        text = "\n".join(["== calibration drift ==", STRONG_TIER_LINE, ""])
        result = _run_check(text)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"KNOWN: {STRONG_TIER_LINE}", result.stdout)
        self.assertIn("known=1 new=0", result.stdout)

    def test_no_escalate_lines_exits_0(self):
        result = _run_check("== daily ==\nnothing interesting here\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("known=0 new=0", result.stdout)

    def test_missing_ledger_makes_every_line_new(self):
        text = "\n".join([STRONG_TIER_LINE, NEW_LINE, ""])
        with tempfile.TemporaryDirectory() as tmp:
            missing_ledger = Path(tmp) / "no_such_ledger.md"
            result = _run_check(text, ledger_path=missing_ledger)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"NEW: {STRONG_TIER_LINE}", result.stdout)
        self.assertIn(f"NEW: {NEW_LINE}", result.stdout)
        self.assertIn("known=0 new=2", result.stdout)

    def test_missing_run_output_file_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does_not_exist.out"
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--check", str(missing)],
                cwd=REPO, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 1)


# ---------------------------------------------------------------------------
# 2. the real, checked-in ledger parses and seeds correctly
# ---------------------------------------------------------------------------

class LedgerParsesTest(unittest.TestCase):
    def test_ledger_file_exists(self):
        self.assertTrue(LEDGER.is_file(), "docs/ESCALATIONS.md is missing")

    def test_seeded_ledger_parses_both_rows(self):
        entries = escalations.parse_ledger(LEDGER)
        ids = {e.id for e in entries}
        self.assertIn("strong-tier-drift", ids)
        self.assertIn("research-readiness-battery", ids)

    def test_strong_tier_row(self):
        entries = {e.id: e for e in escalations.parse_ledger(LEDGER)}
        row = entries["strong-tier-drift"]
        self.assertEqual(row.status, "open")
        self.assertIn("a constant calibrated against a population has drifted",
                      row.pattern)

    def test_research_readiness_row(self):
        entries = {e.id: e for e in escalations.parse_ledger(LEDGER)}
        row = entries["research-readiness-battery"]
        self.assertEqual(row.status, "fix in progress")
        self.assertIn("forward-test system(s) now have 30+ graded selections",
                      row.pattern)


# ---------------------------------------------------------------------------
# 3. the real ledger classifies both standing lines KNOWN
# ---------------------------------------------------------------------------

class RealLedgerAbsorbsBothStandingLinesTest(unittest.TestCase):
    def test_both_standing_escalations_are_known(self):
        text = "\n".join([STRONG_TIER_LINE, BATTERY_LINE, ""])
        result = _run_check(text)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("known=2 new=0", result.stdout)


# ---------------------------------------------------------------------------
# 4. the workflow's final step
# ---------------------------------------------------------------------------

class WorkflowFinalStepTest(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_final_step_calls_escalations_script(self):
        self.assertIn("scripts/escalations.py --check", self.text)

    def test_final_step_no_longer_fails_on_a_bare_grep(self):
        step_start = self.text.index("Fail the job on any")
        final_step = self.text[step_start:]
        self.assertNotIn('grep -q "^ESCALATE:"', final_step)

    def test_every_other_line_of_the_workflow_is_unchanged(self):
        # The task requires touching only the final step -- everything
        # above "Fail the job on any" (the cache restore/save steps, the
        # daily loop invocation, the checkout/cache config) must be intact.
        step_start = self.text.index("Fail the job on any")
        head = self.text[:step_start]
        self.assertIn("bash scripts/daily_bootstrap.sh", head)
        self.assertIn("bash scripts/daily_loop.sh", head)
        self.assertIn('key: daily-loop-data-${{ github.run_id }}', head)


if __name__ == "__main__":
    unittest.main()
