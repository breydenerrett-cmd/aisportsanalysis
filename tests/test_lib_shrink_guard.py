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
    """Textual proof that both data-plane scripts actually source the guard,
    read the declaration (not a literal filename list), stage exactly those
    declared paths, and invoke the guard on them afterwards -- complements
    GuardOnAThrowawayRepo's proof that the guard itself works.

    H4 (2026-09-16): this used to assert the literal string "git add
    data/historical/lineups.jsonl" appeared in both scripts -- that was
    itself the hand-kept-list problem H4 removes, so the assertion changed
    along with the fix. What must stay true is the invariant, not the
    wording: both scripts source read_append_only_stores, stage whatever
    it returns, and guard exactly that same set, in that order."""

    def test_capture_slot_and_forward_capture_read_the_declaration(self):
        for rel in ("scripts/capture_slot.sh", "scripts/forward_capture.sh"):
            with self.subTest(script=rel):
                text = (REPO / rel).read_text(encoding="utf-8")
                self.assertIn("lib_shrink_guard.sh", text,
                             f"{rel} does not source the shrink guard")
                self.assertIn("read_append_only_stores", text,
                             f"{rel} does not read the single declaration "
                             "of append-only stores -- it must not carry "
                             "its own literal list")
                self.assertNotIn("git add data/historical/lineups.jsonl", text,
                                 f"{rel} still hardcodes a store's git add "
                                 "instead of reading the declaration "
                                 "(mentioning the path in a comment is fine "
                                 "-- staging it literally is not)")
                self.assertIn("guard_staged_no_shrink", text,
                             f"{rel} sources the guard but never calls it")
                # The declared paths must be read, then staged, then
                # guarded, in that order -- guarding before staging would
                # have nothing to check; staging before reading the
                # declaration would have nothing to stage.
                read_pos = text.index("read_append_only_stores)")
                add_pos = text.index("git add $DECLARED_STORES")
                guard_pos = text.index("guard_staged_no_shrink $DECLARED_STORES")
                self.assertLess(read_pos, add_pos,
                                f"{rel} stages before reading the declaration")
                self.assertLess(add_pos, guard_pos,
                                f"{rel} calls the guard before staging the "
                                "declared stores, so it would have nothing "
                                "to check")

    def test_declaration_file_lists_the_three_known_stores(self):
        """The declaration itself must still carry (at minimum) the three
        stores the original incident and guard were built around -- H4
        generalises HOW a store gets protected, not WHICH ones currently
        are."""
        sys.path.insert(0, str(REPO))
        from scripts.store_registry import load_declared_stores
        declared = load_declared_stores()
        for path in ("data/historical/lineups.jsonl",
                     "data/historical/matchup_history.jsonl",
                     "data/historical/matchup_pairs.json"):
            self.assertIn(path, declared)


class DeclarationDrivenGuardTest(unittest.TestCase):
    """Proves the guard is actually driven BY the declaration file, not
    just by whatever paths a caller happens to pass -- i.e. that
    read_append_only_stores + guard_staged_no_shrink together reproduce
    exactly the behaviour the old hand-kept lists gave, for a store that
    exists ONLY in the declaration, never typed into this test by name
    anywhere else."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name) / "repo"
        (self.repo / "data" / "historical").mkdir(parents=True)
        _run("git", "init", "-q", cwd=self.repo)
        _run("git", "config", "user.email", "test@example.com", cwd=self.repo)
        _run("git", "config", "user.name", "Test", cwd=self.repo)
        shutil.copy(GUARD, self.repo / "lib_shrink_guard.sh")
        # A declaration naming a store this test never hardcodes anywhere
        # else -- proves the guard follows the FILE, not a copy of the list
        # baked into this test.
        (self.repo / "append_only_stores.txt").write_text(
            "# test declaration\n"
            "data/historical/quietly_declared.jsonl\n",
            encoding="utf-8")

    def _declared_guard(self):
        script = ("set -uo pipefail\n"
                 ". ./lib_shrink_guard.sh\n"
                 "STORES=$(read_append_only_stores)\n"
                 "guard_staged_no_shrink $STORES\n")
        return _run(BASH, "-c", script, cwd=self.repo)

    def test_a_store_named_only_in_the_declaration_is_still_protected(self):
        (self.repo / "data/historical/quietly_declared.jsonl").write_text(
            '{"r":0}\n{"r":1}\n{"r":2}\n', encoding="utf-8")
        _run("git", "add", "data/historical/quietly_declared.jsonl", cwd=self.repo)
        _run("git", "commit", "-q", "-m", "initial", cwd=self.repo)

        (self.repo / "data/historical/quietly_declared.jsonl").write_text(
            '{"r":0}\n', encoding="utf-8")  # 3 -> 1
        _run("git", "add", "data/historical/quietly_declared.jsonl", cwd=self.repo)

        result = self._declared_guard()

        self.assertIn(
            "ESCALATE: data/historical/quietly_declared.jsonl would shrink "
            "3 -> 1 rows, refusing", result.stdout)
        staged = _run("git", "diff", "--cached", "--name-only", cwd=self.repo).stdout
        self.assertNotIn("quietly_declared.jsonl", staged)

    def test_an_undeclared_store_is_not_protected_by_the_declaration_reader(self):
        """Sanity check on the other side of the same mechanism: a store
        NOT in append_only_stores.txt gets no protection from
        read_append_only_stores, because it never reads that path at all.
        (It could still be protected if a caller passed its path directly,
        as the pre-H4 scripts used to -- this test is about the
        declaration-driven path specifically.)"""
        (self.repo / "data/historical/undeclared.jsonl").write_text(
            '{"r":0}\n{"r":1}\n', encoding="utf-8")
        _run("git", "add", "data/historical/undeclared.jsonl", cwd=self.repo)
        _run("git", "commit", "-q", "-m", "initial", cwd=self.repo)

        (self.repo / "data/historical/undeclared.jsonl").write_text(
            '{"r":0}\n', encoding="utf-8")  # 2 -> 1, would shrink
        _run("git", "add", "data/historical/undeclared.jsonl", cwd=self.repo)

        result = self._declared_guard()

        self.assertNotIn("undeclared.jsonl", result.stdout)


class LintCatchesUndeclaredStoresTest(unittest.TestCase):
    """H4 requirement 3: an append-only store that exists in the tree but
    is NOT declared must fail a test -- scripts/lint_append_only_declarations.py
    is that lint. This exercises it against a throwaway repo built to have
    exactly the append-only growth signature (rows only ever increase
    across >= 2 commits, top-level under data/historical/*.jsonl), the same
    signature the lint itself looks for -- see that script's module
    docstring for the full definition and its documented blind spots
    (single-commit stores, nested subdirectories, and anything outside
    data/historical/ are NOT checked by this lint)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name) / "repo"
        (self.repo / "data" / "historical").mkdir(parents=True)
        (self.repo / "scripts").mkdir()
        _run("git", "init", "-q", cwd=self.repo)
        _run("git", "config", "user.email", "test@example.com", cwd=self.repo)
        _run("git", "config", "user.name", "Test", cwd=self.repo)

    def _commit_jsonl(self, rel, row_counts):
        for n in row_counts:
            (self.repo / rel).write_text(
                "".join(f'{{"row":{i}}}\n' for i in range(n)), encoding="utf-8")
            _run("git", "add", rel, cwd=self.repo)
            _run("git", "commit", "-q", "-m", f"{rel} -> {n} rows", cwd=self.repo)

    def _lint(self):
        return subprocess.run(
            [sys.executable, str(REPO / "scripts" / "lint_append_only_declarations.py"),
             str(self.repo)],
            capture_output=True, text=True)

    def test_a_grows_only_store_with_no_declaration_fails_the_lint(self):
        self._commit_jsonl("data/historical/new_store.jsonl", [2, 3, 5])
        (self.repo / "scripts" / "append_only_stores.txt").write_text(
            "", encoding="utf-8")

        result = self._lint()

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("UNDECLARED: data/historical/new_store.jsonl",
                      result.stdout)

    def test_a_declared_grows_only_store_passes_the_lint(self):
        self._commit_jsonl("data/historical/known_store.jsonl", [2, 3, 5])
        (self.repo / "scripts" / "append_only_stores.txt").write_text(
            "data/historical/known_store.jsonl\n", encoding="utf-8")

        result = self._lint()

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("UNDECLARED", result.stdout)

    def test_documented_blind_spot_a_single_commit_store_is_not_caught(self):
        """Names the limitation instead of hiding it: with only one commit
        there is no growth history to test "never shrinks" against, so the
        lint skips it rather than guessing. An undeclared brand-new store
        will NOT be caught until its second commit."""
        self._commit_jsonl("data/historical/brand_new.jsonl", [3])
        (self.repo / "scripts" / "append_only_stores.txt").write_text(
            "", encoding="utf-8")

        result = self._lint()

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("brand_new.jsonl", result.stdout)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
