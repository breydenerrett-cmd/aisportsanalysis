"""Card calibration freeze, 2026-09-15 (owner decision: "Freeze it now",
docs/CARD_CALIBRATION_FREEZE_2026-09-15.md).

`scripts/fit_card_calibration.py` was reading the sealed 2026-01-01..08-27
evaluation window every night (docs/CARD_V2_DIAGNOSIS_2026-09-15.md section
0). Brey chose to freeze the current card's calibration rather than keep
refitting it. Four things are tested, matching the task's own claims:

1. `scripts/daily_loop.sh` no longer invokes `fit_card_calibration.py`
   anywhere outside a comment.
2. Run with no flag, the script refuses to write the live store, exits
   non-zero, prints a line naming the freeze record, and leaves the store's
   bytes untouched -- proved twice: once against a bare temp directory
   (nothing else on disk at all) and once with a pre-existing dummy store
   file at that same relative path, to show the refusal is not merely "the
   fit had no real data to run on".
3. Run with `--out` pointed elsewhere, it gets past the freeze guard (the
   refusal text and exit-1-before-fitting behavior seen in #2 do not
   happen); if the real stores this checkout has are enough to complete a
   fit, the output file is written, but the assertion itself only requires
   clearing the guard, per the task.
4. The freeze record doc exists and names the sha256 that matches the
   committed file's bytes at HEAD.
"""

from __future__ import annotations

import hashlib
import pathlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "daily_loop.sh"
FIT_SCRIPT = REPO / "scripts" / "fit_card_calibration.py"
FREEZE_RECORD = REPO / "docs" / "CARD_CALIBRATION_FREEZE_2026-09-15.md"
LIVE_STORE_REL = "data/processed/card_calibration.json"
LIVE_STORE = REPO / LIVE_STORE_REL


def _code(text: str) -> str:
    """Strip comment-only lines, same technique as
    tests/test_chain_multi_sport.py -- the freeze record's own name is
    expected to appear in a comment near where the step used to be, and
    that must not count as an invocation."""
    return "\n".join(line for line in text.splitlines()
                      if not line.strip().startswith("#"))


# ---------------------------------------------------------------------------
# 1. daily_loop.sh no longer runs the refit
# ---------------------------------------------------------------------------

class DailyLoopNoLongerRefitsTest(unittest.TestCase):
    def setUp(self):
        self.text = SCRIPT.read_text(encoding="utf-8")

    def test_no_invocation_outside_a_comment(self):
        code = _code(self.text)
        self.assertNotIn("fit_card_calibration.py", code)

    def test_run_note_line_names_the_freeze_record(self):
        # The step is replaced, not deleted outright: one run-note line
        # still records that the card calibration is frozen, and names
        # this record doc, so the overnight run log says why the step is
        # gone instead of just going silent.
        self.assertIn("card calibration frozen", self.text)
        self.assertIn("CARD_CALIBRATION_FREEZE_2026-09-15.md", self.text)

    def test_daily_loop_still_parses_as_valid_bash(self):
        candidates = []
        if sys.platform == "win32":
            candidates += [r"C:\Program Files\Git\bin\bash.exe",
                           r"C:\Program Files\Git\usr\bin\bash.exe"]
        import shutil
        candidates.append(shutil.which("bash"))
        bash = next((p for p in candidates if p and Path(p).exists()
                     and "windowsapps" not in p.lower()
                     and "system32" not in p.lower()), None)
        if not bash:
            self.skipTest("no POSIX bash available")
        result = subprocess.run([bash, "-n", str(SCRIPT)],
                                 capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


# ---------------------------------------------------------------------------
# 2 & 3. fit_card_calibration.py's freeze guard, exercised directly
# ---------------------------------------------------------------------------

class FitCardCalibrationFreezeGuardTest(unittest.TestCase):
    """Runs the real script as a subprocess with `cwd` set to a temp
    directory. `scripts/fit_card_calibration.py` resolves its own imports
    off `__file__` (`sys.path.insert(0, ... os.path.abspath(__file__) ...)`),
    not off `cwd`, so it imports the real `src` package regardless of where
    it is run from -- that is the seam this test uses: the default `--out`
    is the literal relative string "data/processed/card_calibration.json"
    (`src/report/card.py:CALIBRATION_STORE`), so running with `cwd` in a
    scratch temp dir makes "the live store" resolve to a harmless path
    under that temp dir, never the real repo's committed file, while still
    exercising the exact guard condition (`--out` left at its default)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cwd = Path(self._tmp.name)
        self.store_path = self.cwd / "data" / "processed" / "card_calibration.json"

    def _run(self, extra_args):
        return subprocess.run(
            [sys.executable, str(FIT_SCRIPT), *extra_args],
            cwd=self.cwd, capture_output=True, text=True, timeout=60)

    def test_refuses_with_no_flag_against_bare_temp_dir(self):
        result = self._run([])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CARD_CALIBRATION_FREEZE_2026-09-15.md", result.stderr)
        self.assertFalse(self.store_path.exists(),
                          "the freeze guard must refuse before writing "
                          "anything, not merely fail later for lack of data")

    def test_refuses_and_leaves_a_pre_existing_store_byte_for_byte(self):
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        original = b'{"a": 0.0, "b": 1.0, "n": 1, "base_rate": 0.5}\n'
        self.store_path.write_bytes(original)
        result = self._run([])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.store_path.read_bytes(), original)

    def test_overwrite_flag_alone_without_owner_decision_still_only_a_flag(self):
        # The flag is necessary but the record doc (checked in section 4)
        # is what actually carries the dated owner decision; this test
        # only pins that the flag is what lets `--out` at the default path
        # proceed past the guard technically, matching the script's own
        # docstring ("Lifting the freeze for real needs a new dated owner
        # decision, not just the flag").
        result = self._run(["--overwrite-frozen-store"])
        self.assertNotIn("CARD_CALIBRATION_FREEZE_2026-09-15.md",
                          result.stderr)

    def test_out_elsewhere_clears_the_guard_without_the_flag(self):
        out_path = self.cwd / "scratch_calibration.json"
        result = self._run(["--out", str(out_path)])
        # Whatever happens next (this temp dir has none of the real
        # historical stores, so the fit itself is expected to refuse for
        # lack of data) must NOT be the freeze refusal -- the guard must
        # already be cleared.
        self.assertNotIn("CARD_CALIBRATION_FREEZE_2026-09-15.md",
                          result.stderr)
        self.assertFalse(self.store_path.exists())


# ---------------------------------------------------------------------------
# 4. the freeze record exists and names the right sha256
# ---------------------------------------------------------------------------

class FreezeRecordTest(unittest.TestCase):
    def test_record_exists(self):
        self.assertTrue(FREEZE_RECORD.exists(),
                         f"missing {FREEZE_RECORD}")

    def test_record_names_the_committed_files_sha256(self):
        text = FREEZE_RECORD.read_text(encoding="utf-8")
        # Computed via `git show <commit>:data/processed/card_calibration.json`
        # (not the working-tree copy -- its line endings can differ from
        # the committed blob's) at the commit this freeze was made against.
        committed = subprocess.run(
            ["git", "show",
             "b238942033a0b7b86044d8c9e90ed835ef39b3b0:" + LIVE_STORE_REL],
            cwd=REPO, capture_output=True, timeout=30)
        if committed.returncode != 0:
            self.skipTest("git show unavailable or commit not reachable "
                           "in this checkout")
        digest = hashlib.sha256(committed.stdout).hexdigest()
        self.assertIn(digest, text)


if __name__ == "__main__":
    unittest.main()
