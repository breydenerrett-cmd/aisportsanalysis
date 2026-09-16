"""scripts/lib_shrink_guard.sh -- the pre-commit shrink guard added after the
2026-09-16 incident: a CI cache-restore step (actions/cache/restore@v4,
.github/workflows/forward-capture.yml:186-221) unpacked a stale cached copy
of data/historical/lineups.jsonl over the freshly checked-out worktree
("last restore wins", per that workflow's own comment). scripts/capture_slot.sh
and scripts/forward_capture.sh then staged and committed whatever bytes were
on disk, no questions asked -- nine times, once shrinking a 4,993-row store
to 119 rows eleven minutes after a backfill had landed it. The writer
(src/pipeline/lineup_store.py:198, append-only "a" mode) was never at fault.

These tests exercise the guard FOR REAL, sourcing scripts/lib_shrink_guard.sh
into a throwaway git repository under a temp directory and calling
guard_staged_no_shrink exactly the way scripts/capture_slot.sh and
scripts/forward_capture.sh do -- never against this repo's own working tree,
and never touching data/historical/lineups.jsonl, which now holds the
restored 4,993 rows.

WHY REAL bash AND A REAL git REPO, NOT A TEXTUAL ASSERTION
------------------------------------------------------------
tests/test_deploy_scripts.py's DataPlaneGitRaceTest proves the two capture
scripts source and call this guard (textually, on the checked-in scripts --
see test_capture_slot_and_forward_capture_call_the_guard below). That is not
the same claim as "the guard actually restores a shrunk file and lets a
grown one commit" -- proving THAT needs the guard to run against a real git
index, because git rev-parse/cat-file/restore are the guard's entire
mechanism and a fake filesystem would not exercise them.

WHY bash -n IS NOT ENOUGH HERE EITHER
--------------------------------------
`bash -n scripts/lib_shrink_guard.sh` (covered by
tests/test_deploy_scripts.py's ShellScriptsParseTest) proves the file parses.
It says nothing about whether the shrink comparison, the byte-vs-line-count
branch, or the restore call are actually correct -- that is what this file
checks by running them.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GUARD = REPO / "scripts" / "lib_shrink_guard.sh"


def _bash():
    """Find a POSIX bash, preferring Git Bash on Windows -- the same
    resolution tests/test_chain_multi_sport.py uses, because a bare "bash"
    on PATH can resolve to the WSL shim in System32, which fails outright
    with no WSL distro installed (this repo's own known, pre-existing,
    not-ours-to-fix Windows gap)."""
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


def _run(*args, cwd):
    return subprocess.run(list(args), cwd=str(cwd), capture_output=True,
                          text=True)


@unittest.skipUnless(BASH, "no usable POSIX bash found on this machine")
class GuardOnAThrowawayRepo(unittest.TestCase):
    """A real git repo under tempfile.TemporaryDirectory() -- never this
    repo's own working tree, and never data/historical/lineups.jsonl."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name) / "repo"
        self.repo.mkdir()
        _run("git", "init", "-q", cwd=self.repo)
        _run("git", "config", "user.email", "test@example.com", cwd=self.repo)
        _run("git", "config", "user.name", "Test", cwd=self.repo)
        (self.repo / "data" / "historical").mkdir(parents=True)
        shutil.copy(GUARD, self.repo / "lib_shrink_guard.sh")

    def _write(self, rel, text):
        path = self.repo / rel
        path.write_text(text, encoding="utf-8", newline="\n")

    def _commit_initial(self, lineup_rows=5, pairs_bytes=b'{"pairs":[1,2,3]}'):
        self._write("data/historical/lineups.jsonl",
                    "".join(f'{{"row":{i}}}\n' for i in range(lineup_rows)))
        (self.repo / "data/historical/matchup_pairs.json").write_bytes(pairs_bytes)
        self._write("data/historical/matchup_history.jsonl", '{"m":1}\n{"m":2}\n')
        _run("git", "add", "data/historical", cwd=self.repo)
        _run("git", "commit", "-q", "-m", "initial", cwd=self.repo)

    def _guard(self, *paths):
        script = ("set -uo pipefail\n"
                 ". ./lib_shrink_guard.sh\n"
                 f"guard_staged_no_shrink {' '.join(paths)}\n")
        return _run(BASH, "-c", script, cwd=self.repo)

    def _staged_names(self):
        result = _run("git", "diff", "--cached", "--name-only", cwd=self.repo)
        return set(result.stdout.split())

    # -- the incident, reproduced ------------------------------------

    def test_a_shrunk_jsonl_is_refused_restored_and_escalated(self):
        self._commit_initial(lineup_rows=5)
        self._write("data/historical/lineups.jsonl", '{"row":0}\n')  # 5 -> 1
        _run("git", "add", "data/historical/lineups.jsonl", cwd=self.repo)

        result = self._guard("data/historical/lineups.jsonl")

        self.assertIn("ESCALATE: data/historical/lineups.jsonl would shrink "
                      "5 -> 1 rows, refusing", result.stdout)
        self.assertNotIn("data/historical/lineups.jsonl", self._staged_names())
        self.assertEqual(
            (self.repo / "data/historical/lineups.jsonl").read_text(),
            "".join(f'{{"row":{i}}}\n' for i in range(5)),
            "the worktree copy was not restored from HEAD")

    def test_other_files_in_the_same_commit_still_land(self):
        """One poisoned file must not block a whole capture slot."""
        self._commit_initial(lineup_rows=5)
        self._write("data/historical/lineups.jsonl", '{"row":0}\n')  # shrinks
        self._write("data/historical/matchup_history.jsonl",
                    '{"m":1}\n{"m":2}\n{"m":3}\n')  # grows
        _run("git", "add", "data/historical/lineups.jsonl",
            "data/historical/matchup_history.jsonl", cwd=self.repo)

        self._guard("data/historical/lineups.jsonl",
                    "data/historical/matchup_history.jsonl")

        staged = self._staged_names()
        self.assertNotIn("data/historical/lineups.jsonl", staged,
                         "the shrunk file must be unstaged")
        self.assertIn("data/historical/matchup_history.jsonl", staged,
                      "the grown file in the same commit must still be staged")

    def test_a_grown_or_equal_file_commits_normally_and_is_silent(self):
        self._commit_initial(lineup_rows=5)
        self._write("data/historical/lineups.jsonl",
                    "".join(f'{{"row":{i}}}\n' for i in range(7)))  # 5 -> 7
        _run("git", "add", "data/historical/lineups.jsonl", cwd=self.repo)

        result = self._guard("data/historical/lineups.jsonl")

        self.assertNotIn("ESCALATE:", result.stdout)
        self.assertIn("data/historical/lineups.jsonl", self._staged_names(),
                      "a grown file must remain staged, not be touched")

    def test_matchup_pairs_json_is_compared_by_bytes_not_lines(self):
        """matchup_pairs.json is single-line JSON: a line count would read
        1 -> 1 for any edit and protect nothing, so this path must use byte
        size instead."""
        pairs = b'{"pairs":[1,2,3,4,5]}'
        self._commit_initial(pairs_bytes=pairs)
        (self.repo / "data/historical/matchup_pairs.json").write_bytes(b"{}")
        _run("git", "add", "data/historical/matchup_pairs.json", cwd=self.repo)

        result = self._guard("data/historical/matchup_pairs.json")

        self.assertIn(
            f"ESCALATE: data/historical/matchup_pairs.json would "
            f"shrink {len(pairs)} -> 2 bytes, refusing", result.stdout,
            result.stdout)
        self.assertNotIn("data/historical/matchup_pairs.json",
                         self._staged_names())
        self.assertEqual(
            (self.repo / "data/historical/matchup_pairs.json").read_bytes(),
            b'{"pairs":[1,2,3,4,5]}')

    def test_a_grown_matchup_pairs_json_is_not_flagged(self):
        self._commit_initial(pairs_bytes=b"{}")  # 2 bytes
        (self.repo / "data/historical/matchup_pairs.json").write_bytes(
            b'{"pairs":[1,2,3,4,5]}')  # grows
        _run("git", "add", "data/historical/matchup_pairs.json", cwd=self.repo)

        result = self._guard("data/historical/matchup_pairs.json")

        self.assertNotIn("ESCALATE:", result.stdout)
        self.assertIn("data/historical/matchup_pairs.json",
                      self._staged_names())

    def test_the_escalate_line_is_picked_up_by_scripts_escalations_py(self):
        """scripts/escalations.py:extract_escalate_lines matches any line
        starting 'ESCALATE:' (escalations.py:109-116) and cmd_check exits
        non-zero for one the ledger has never seen. Confirms the guard's
        output actually routes into that alarm channel, not just that it
        looks similar to it."""
        self._commit_initial(lineup_rows=5)
        self._write("data/historical/lineups.jsonl", '{"row":0}\n')
        _run("git", "add", "data/historical/lineups.jsonl", cwd=self.repo)
        guard_result = self._guard("data/historical/lineups.jsonl")

        out_file = self.repo / "guard_output.txt"
        out_file.write_text(guard_result.stdout, encoding="utf-8")

        import sys as _sys
        check = subprocess.run(
            [_sys.executable, str(REPO / "scripts" / "escalations.py"),
             "--check", str(out_file)],
            capture_output=True, text=True,
        )
        self.assertEqual(check.returncode, 1,
                         f"escalations.py did not treat the guard's line as "
                         f"a new escalation: {check.stdout} {check.stderr}")
        self.assertIn("NEW: ESCALATE:", check.stdout)

    def test_a_newly_added_file_with_no_head_version_is_never_flagged(self):
        """A brand-new file cannot 'shrink' -- there is nothing in HEAD to
        compare it against. No initial commit here, so HEAD has no
        data/historical/lineups.jsonl at all yet."""
        self._write("data/historical/lineups.jsonl", '{"row":0}\n')
        _run("git", "add", "data/historical/lineups.jsonl", cwd=self.repo)

        result = self._guard("data/historical/lineups.jsonl")

        self.assertNotIn("ESCALATE:", result.stdout, result.stdout)


class CaptureScriptsCallTheGuard(unittest.TestCase):
    """Textual proof that both data-plane scripts actually source and
    invoke the guard where they stage the three historical stores --
    complements GuardOnAThrowawayRepo's proof that the guard itself works."""

    def test_capture_slot_and_forward_capture_call_the_guard(self):
        for rel in ("scripts/capture_slot.sh", "scripts/forward_capture.sh"):
            with self.subTest(script=rel):
                text = (REPO / rel).read_text(encoding="utf-8")
                self.assertIn("lib_shrink_guard.sh", text,
                             f"{rel} does not source the shrink guard")
                self.assertIn("guard_staged_no_shrink", text,
                             f"{rel} sources the guard but never calls it")
                # The call must come after the git add of the three
                # historical stores, or it would check nothing staged yet.
                add_pos = text.index(
                    "git add data/historical/lineups.jsonl")
                guard_pos = text.index("guard_staged_no_shrink")
                self.assertLess(
                    add_pos, guard_pos,
                    f"{rel} calls the guard before staging the historical "
                    "stores, so it would have nothing to check")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
