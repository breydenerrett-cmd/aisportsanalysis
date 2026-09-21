"""The capture slot's `git add` must stage what exists even when a listed
path does not (2026-09-19 incident).

`scripts/capture_slot.sh` staged its output with one multi-path
`git add ... 2>/dev/null || true`. git validates every pathspec before
staging anything, so the single missing path `data/live` (added to that line
2026-09-15; zero tracked files; created only by the separate live-window
job) made git refuse the WHOLE add on nearly every fresh checkout. Every
morning capture then reported "no data changes" and died with the runner.

These tests run the script's own staging block -- sliced out of the real
file between two comment anchors that exist in both the broken and fixed
versions -- inside a throwaway repo with no `data/live`, and check that
`data/processed` actually gets staged.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CAPTURE = (REPO / "scripts" / "capture_slot.sh").read_text(encoding="utf-8")
LIVE_WINDOW = (REPO / "src" / "pipeline" / "live_window.py").read_text(encoding="utf-8")

START_ANCHOR = "# commit made ninety-six times a day."
END_ANCHOR = "# H4 (2026-09-16)"


def _bash():
    """A POSIX bash, preferring Git Bash on Windows (WSL's bash.exe cannot
    see Windows temp paths)."""
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


def _staging_block() -> str:
    start = CAPTURE.index(START_ANCHOR) + len(START_ANCHOR)
    end = CAPTURE.index(END_ANCHOR, start)
    return CAPTURE[start:end]


@unittest.skipUnless(BASH and shutil.which("git"), "needs bash and git")
class CaptureStagingSurvivesAMissingPath(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="capture_staging_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self._git("init", "-q")
        self._git("config", "user.email", "t@example.invalid")
        self._git("config", "user.name", "t")
        self._git("config", "core.autocrlf", "false")
        for rel in ("data/processed/odds_snapshots.jsonl", "evidence/slips_v1.jsonl",
                    "docs/OVERNIGHT_RUN.md"):
            path = self.tmp / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("seed\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "seed")

    def _git(self, *argv):
        return subprocess.run(["git", *argv], cwd=self.tmp, capture_output=True,
                              text=True, check=True)

    def _run_block(self):
        return subprocess.run([BASH, "-c", _staging_block()], cwd=self.tmp,
                              capture_output=True, text=True, timeout=30)

    def _staged(self):
        return set(self._git("diff", "--cached", "--name-only").stdout.split())

    def test_capture_output_is_staged_when_data_live_is_absent(self):
        # A capture pass appended a row; data/live does not exist, exactly
        # as on a fresh Actions checkout.
        with open(self.tmp / "data/processed/odds_snapshots.jsonl", "a",
                  encoding="utf-8") as fh:
            fh.write("new row\n")
        self.assertFalse((self.tmp / "data" / "live").exists())

        result = self._run_block()

        self.assertIn("data/processed/odds_snapshots.jsonl", self._staged(),
                      "capture output was not staged -- one missing pathspec "
                      f"made git refuse the whole add.\nstdout={result.stdout}"
                      f"\nstderr={result.stderr}")

    def test_data_live_is_staged_too_when_it_exists(self):
        live = self.tmp / "data" / "live" / "mlb"
        live.mkdir(parents=True)
        (live / "2026-09-19.jsonl").write_text("state\n", encoding="utf-8")

        self._run_block()

        self.assertIn("data/live/mlb/2026-09-19.jsonl", self._staged())

    def test_a_failed_add_turns_the_job_red(self):
        """An ESCALATE line alone changed nothing for five days: the
        forward-capture job has no ESCALATE-to-failure step. A failed add
        must set GIT_FAILED, which ends the script with exit 1."""
        block = _staging_block()
        self.assertIn("ESCALATE: git add of capture output failed", block)
        after = block[block.index("ESCALATE: git add of capture output failed"):]
        self.assertIn("GIT_FAILED=1", after[:after.index("fi")])
        self.assertIn('if [ "$GIT_FAILED" -eq 1 ]; then\n    exit 1', CAPTURE)

    def test_a_failed_add_is_not_silent(self):
        """The old line discarded git's error, which is why this went
        unnoticed for four days. Whatever form the block takes, it must not
        route git add's stderr to /dev/null."""
        block = _staging_block()
        for line in block.splitlines():
            code = line.split("#", 1)[0]
            if "git add" in code:
                self.assertNotIn("2>/dev/null", code, line)


class LiveWindowStagingSurvivesAMissingPath(unittest.TestCase):
    """src/pipeline/live_window.py's _commit had the same shape:
    `git add data/live evidence/live_candidates_v1.jsonl`, where the
    candidates ledger does not exist until a window produces a candidate --
    so a zero-candidate window (the usual case) staged nothing and dropped
    its polling. `_commit` is nested inside `main`, so this pins the
    existence filter at source level."""

    def test_commit_filters_to_existing_paths(self):
        idx = LIVE_WINDOW.index('"evidence/live_candidates_v1.jsonl"')
        window = LIVE_WINDOW[idx - 400: idx + 400]
        self.assertIn(".exists()", window,
                      "live_window stages data/live and the candidates ledger "
                      "without checking they exist; one missing path makes git "
                      "refuse the whole add")
        self.assertNotIn('_git("add", "data/live", "evidence/live_candidates_v1.jsonl")',
                         LIVE_WINDOW)


if __name__ == "__main__":
    unittest.main()
