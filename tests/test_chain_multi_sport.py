"""Multi-sport scheduling in capture_slot.sh and daily_loop.sh.

These tests verify that NFL, tennis and live betting steps are scheduled
in the right order in both the capture and settlement chains.
"""

from __future__ import annotations

import re
import unittest
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CAPTURE = (REPO / "scripts" / "capture_slot.sh").read_text(encoding="utf-8")
DAILY = (REPO / "scripts" / "daily_loop.sh").read_text(encoding="utf-8")


def _code(text):
    """Remove comments for cleaner analysis."""
    return "\n".join(line for line in text.splitlines()
                     if not line.strip().startswith("#"))


def _bash():
    """Find a POSIX bash, preferring Git Bash on Windows."""
    candidates = []
    if sys.platform == "win32":
        candidates += [r"C:\Program Files\Git\bin\bash.exe",
                       r"C:\Program Files\Git\usr\bin\bash.exe"]
    candidates.append(shutil.which("bash"))
    for path in candidates:
        if not path or not Path(path).exists():
            continue
        low = path.lower()
        if sys.platform == "win32" and ("windowsapps" in low or "system32" in low):
            continue
        return path
    return None


BASH = _bash()


class CaptureHasMultiSportSteps(unittest.TestCase):
    def test_nfl_capture_step_exists(self):
        """nfl capture runs after MLB card publish and before git staging."""
        code = _code(CAPTURE)
        self.assertIn("nfl capture", code)
        self.assertIn("python3 -m src.cli nfl capture", code)

    def test_tennis_capture_step_exists(self):
        """tennis capture runs after nfl capture."""
        code = _code(CAPTURE)
        self.assertIn("tennis capture", code)
        self.assertIn("python3 -m src.cli tennis capture", code)

    def test_nfl_card_publish_step_exists(self):
        """NFL card publish runs after tennis capture."""
        code = _code(CAPTURE)
        self.assertIn("nfl card publish", code)
        self.assertIn('card publish --sport nfl --date', code)
        # Should reference NFL_DATE
        self.assertIn('NFL_DATE="$SLATE_DATE"', code)

    def test_nfl_and_tennis_capture_before_git_staging(self):
        """All capture steps complete before git add."""
        code = _code(CAPTURE)
        mlb_pub_idx = code.index("card publish --date")
        nfl_cap_idx = code.index("nfl capture")
        tennis_cap_idx = code.index("tennis capture")
        nfl_pub_idx = code.index("nfl card publish")
        git_idx = code.index("git add data/watch")

        # Order: MLB card -> NFL capture -> tennis capture -> NFL card -> git
        self.assertLess(mlb_pub_idx, nfl_cap_idx)
        self.assertLess(nfl_cap_idx, tennis_cap_idx)
        self.assertLess(tennis_cap_idx, nfl_pub_idx)
        self.assertLess(nfl_pub_idx, git_idx)

    def test_nfl_and_tennis_captures_are_tolerant(self):
        """Capture steps use || true to not fail the slot."""
        code = _code(CAPTURE)
        nfl_line = [l for l in code.splitlines() if "python3 -m src.cli nfl capture" in l][0]
        tennis_line = [l for l in code.splitlines() if "python3 -m src.cli tennis capture" in l][0]
        self.assertTrue(nfl_line.rstrip().endswith("|| true"), nfl_line)
        self.assertTrue(tennis_line.rstrip().endswith("|| true"), tennis_line)

    def test_live_dispatch_step_exists(self):
        """Live-window dispatch step checks for DISPATCH output."""
        code = _code(CAPTURE)
        self.assertIn("live-window dispatch", code)
        self.assertIn("live_window --should-dispatch", code)
        self.assertIn('grep -q "^DISPATCH"', code)
        self.assertIn("live-window.yml", code)

    def test_live_dispatch_is_guarded_by_env_switch(self):
        """LIVE_WINDOW_DISPATCH env var controls live dispatch."""
        code = _code(CAPTURE)
        self.assertIn('LIVE_WINDOW_DISPATCH="${LIVE_WINDOW_DISPATCH:-1}"', code)
        self.assertIn('if [ "$LIVE_WINDOW_DISPATCH" = "1" ]; then', code)

    def test_live_dispatch_checks_both_sports(self):
        """Live dispatch checks mlb and nfl."""
        code = _code(CAPTURE)
        # The for loop iterates over mlb and nfl before the dispatch check
        self.assertIn("for sport in mlb nfl", code)
        # Verify that each sport is passed to the dispatch check
        self.assertIn('--should-dispatch --sport "$sport"', code)

    def test_live_dispatch_uses_gh_workflow_run(self):
        """Live dispatch uses gh workflow run like chain_dispatch."""
        code = _code(CAPTURE)
        dispatch_block = code[code.index("live-window dispatch"):]
        self.assertIn("gh workflow run live-window.yml", dispatch_block)
        self.assertIn("-f sport=", dispatch_block)

    def test_git_staging_includes_data_live(self):
        """git add includes data/live."""
        code = _code(CAPTURE)
        git_block = code[code.index("git add data/watch"):]
        self.assertIn("data/live", git_block)

    def test_git_staging_includes_evidence_for_new_ledgers(self):
        """git add evidence covers all card and live ledger files."""
        code = _code(CAPTURE)
        staging = code[code.index("git add data/watch"):]
        # evidence is already in the git add, which covers both
        # evidence/cards_nfl_v1.jsonl and evidence/live_candidates_v1.jsonl
        self.assertIn("evidence", staging)


class DailyLoopHasMultiSportSteps(unittest.TestCase):
    def test_nfl_card_settle_step_exists(self):
        """NFL card settle runs after MLB card settle."""
        code = _code(DAILY)
        self.assertIn("nfl card settle", code)
        self.assertIn('card settle --sport nfl', code)

    def test_tennis_discover_step_exists(self):
        """Tennis discover runs after NFL settle."""
        code = _code(DAILY)
        self.assertIn("tennis discover", code)
        self.assertIn("python3 -m src.cli tennis discover", code)

    def test_live_settle_step_exists(self):
        """Live settle runs after tennis discover."""
        code = _code(DAILY)
        self.assertIn("live settle", code)
        self.assertIn("live_window --settle", code)

    def test_nfl_settle_after_mlb_settle(self):
        """NFL settle comes immediately after MLB settle."""
        code = _code(DAILY)
        mlb_idx = code.index("== card settle (yesterday")
        nfl_idx = code.index("== nfl card settle")
        self.assertLess(mlb_idx, nfl_idx)

    def test_tennis_discover_after_nfl_settle(self):
        """Tennis discover comes after NFL settle."""
        code = _code(DAILY)
        nfl_idx = code.index("== nfl card settle")
        tennis_idx = code.index("== tennis discover")
        self.assertLess(nfl_idx, tennis_idx)

    def test_live_settle_after_tennis_discover(self):
        """Live settle comes after tennis discover."""
        code = _code(DAILY)
        tennis_idx = code.index("== tennis discover")
        live_idx = code.index("== live settle")
        self.assertLess(tennis_idx, live_idx)

    def test_nfl_settle_is_tolerant(self):
        """NFL settle captures exit status and escalates if needed."""
        code = _code(DAILY)
        # NFL settle captures exit status and can escalate on error
        self.assertIn("NFLSETTLE_OUT=$(python3 -m src.cli card settle --sport nfl", code)
        self.assertIn("NFLSETTLE_STATUS=$?", code)

    def test_tennis_and_live_steps_are_tolerant(self):
        """Tennis discover and live settle use || true."""
        code = _code(DAILY)
        tennis_line = [l for l in code.splitlines() if "python3 -m src.cli tennis discover" in l][0]
        live_line = [l for l in code.splitlines() if "live_window --settle" in l][0]
        self.assertTrue(tennis_line.rstrip().endswith("|| true"), tennis_line)
        self.assertTrue(live_line.rstrip().endswith("|| true"), live_line)

    def test_nfl_settle_uses_yesterday_date(self):
        """NFL settle references $YESTERDAY."""
        code = _code(DAILY)
        self.assertIn('card settle --sport nfl --date "$YESTERDAY"', code)

    def test_live_settle_uses_yesterday_date(self):
        """Live settle references $YESTERDAY."""
        code = _code(DAILY)
        self.assertIn('live_window --settle --date "$YESTERDAY"', code)

    def test_steps_append_to_run_note(self):
        """All new steps append to RUN_NOTE."""
        code = _code(DAILY)
        # Check that lines append to RUN_NOTE
        self.assertGreater(code.count('>> "$RUN_NOTE"'), code[:code.index("== nfl card settle")].count('>> "$RUN_NOTE"'),
                          "new steps should append to RUN_NOTE")


@unittest.skipUnless(BASH, "no POSIX bash available")
class BashSyntaxIsValid(unittest.TestCase):
    def test_capture_slot_sh_syntax(self):
        """capture_slot.sh passes bash -n."""
        result = subprocess.run([BASH, "-n", str(REPO / "scripts" / "capture_slot.sh")],
                              capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_daily_loop_sh_syntax(self):
        """daily_loop.sh passes bash -n."""
        result = subprocess.run([BASH, "-n", str(REPO / "scripts" / "daily_loop.sh")],
                              capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
