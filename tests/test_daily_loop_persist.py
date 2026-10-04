"""The daily loop persists the refreshed MLB display stores (2026-10-04).

Two kinds of proof.

TEXT (style of tests/test_daily_loop_wiring.py): the refresh sits after every
step that prices or settles anything and before the git lock, the persist step
sits under the lock before `git add`, every line is guarded so it cannot fail
the loop, and the directory is never staged wholesale.

BEHAVIOUR: the persist block, extracted from the real script, is RUN under bash
in a throwaway git repository (a copy of `src/`, a committed store, a "cache
copy" on disk that lacks a row only git holds). What is staged must hold the row
only git held, the row the refresh added, and the corrected value.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.pipeline import bullpen, history
from tests.test_daily_loop_wiring import BASH, REPO, SCRIPT
from tests.test_display_refresh import seed_root

TEXT = SCRIPT.read_text(encoding="utf-8")


def pos(needle):
    found = TEXT.find(needle)
    assert found >= 0, needle
    return found


class TheStepsAreWiredAndGuarded(unittest.TestCase):

    def test_the_refresh_runs_after_pricing_and_settling_and_before_the_lock(self):
        refresh = pos("python3 -m src.pipeline.display_refresh")
        self.assertGreater(refresh, pos("engine settle --date"))
        self.assertGreater(refresh, pos("python3 -m src.cli engine slate"))
        self.assertLess(refresh, pos("exec 9>\"$GIT_LOCK\""), "a network call must not hold the git lock")

    def test_the_persist_step_is_under_the_lock_and_before_the_add(self):
        persist = pos("store_persist persist")
        self.assertGreater(persist, pos("exec 9>\"$GIT_LOCK\""))
        self.assertGreater(persist, pos("store rotate --all"))
        self.assertLess(persist, pos("guard_staged_size"))
        self.assertGreater(persist, pos("git add data/processed data/watch"))

    def test_every_new_line_is_guarded_so_it_cannot_fail_the_loop(self):
        block = TEXT[pos("== MLB display stores (merge with committed copy"):pos("# Concurrent runs of this script")]
        for command in ("store_persist union", "src.pipeline.display_refresh"):
            line = next(l for l in block.splitlines() if command in l and not l.lstrip().startswith("#"))
            tail = block[block.find(line):].split("echo \"- ")[0]
            self.assertIn("timeout", line)
            self.assertIn("||", tail, command)
        self.assertIn("|| PERSIST_PATHS=\"\"", TEXT)
        self.assertNotRegex(TEXT, r"(?m)^set -[a-z]*e")

    def test_the_stores_are_staged_by_name_never_as_a_directory(self):
        self.assertIn("git add $PERSIST_PATHS", TEXT)
        self.assertIn("guard_staged_no_shrink $PERSIST_PATHS", TEXT)
        for line in TEXT.splitlines():
            if line.lstrip().startswith("git add") and "data/historical" in line:
                self.assertNotRegex(line, r"data/historical/?(\s|$)", "the directory is never staged")

    def test_the_script_is_still_valid_bash(self):
        if BASH is None:
            self.skipTest("no usable bash")
        done = subprocess.run([BASH, "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)


@unittest.skipIf(BASH is None, "no usable bash")
class TheRealPersistBlockStagesTheUnion(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name) / "repo"
        shutil.copytree(REPO / "src", self.repo / "src",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (self.repo / "scripts").mkdir()
        shutil.copy(REPO / "scripts" / "lib_shrink_guard.sh", self.repo / "scripts")
        self.root = seed_root(self.repo / "data")
        self.hist = self.root / "historical"
        # the throwaway repository's HEAD is the seeded store, minus the sentinels
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.test")
        self.git("config", "user.name", "t")
        self.git("config", "core.autocrlf", "false")
        self.git("add", "data/historical")
        self.git("commit", "-q", "-m", "committed copy")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True, check=True).stdout

    def run_block(self):
        match = re.search(r"(?ms)^PERSIST_PATHS=.*?^fi$", TEXT)
        self.assertIsNotNone(match)
        import sys
        harness = (f'python3() {{ "{Path(sys.executable).as_posix()}" "$@"; }}\n'
                   f'. scripts/lib_shrink_guard.sh\n{match.group(0)}\n')
        done = subprocess.run([BASH, "-c", harness], cwd=self.repo, capture_output=True, text=True,
                              env={**__import__("os").environ, "PYTHONPATH": str(self.repo),
                                   "PYTHONIOENCODING": "utf-8"})
        return done

    def staged(self):
        return [l for l in self.git("diff", "--cached", "--name-only").splitlines() if l]

    def staged_text(self, path):
        return subprocess.run(["git", "show", f":{path}"], cwd=self.repo, capture_output=True,
                              check=True).stdout.decode("utf-8")

    def test_a_cache_copy_that_lost_a_git_only_row_commits_the_union(self):
        # the runner's disk copy is the cache's: refreshed (a new game, a new
        # reliever row, a corrected score) but without game 900, which only git holds
        rows = history.read_results(self.hist / "mlb_results.csv")
        rows.pop("900")
        rows["5"] = {**rows["1"], "game_pk": "5", "date": "2026-09-24"}
        rows["1"] = {**rows["1"], "away_score": "9"}
        history.write_results(rows, self.hist / "mlb_results.csv")
        log = self.hist / "bullpen_log.jsonl"
        log.write_text(log.read_text(encoding="utf-8") + json.dumps(
            {"date": "2026-10-02", "game_pk": 14, "team": "NYY", "person_id": 9014, "name": "New Arm",
             "started": False, "innings": 1.0, "pitches": 15}, sort_keys=True) + "\n", encoding="utf-8")

        done = self.run_block()

        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(sorted(self.staged()),
                         ["data/historical/bullpen_log.jsonl", "data/historical/mlb_results.csv"],
                         done.stdout + done.stderr)
        committed_csv = self.staged_text("data/historical/mlb_results.csv")
        self.assertIn("900", [l.split(",")[0] for l in committed_csv.splitlines()],
                      "the postseason game only git held is in what is about to be committed")
        staged = {l.split(",")[0]: l for l in committed_csv.splitlines()}
        self.assertIn("5", staged, "the game the refresh added")
        self.assertIn(",9,", staged["1"], "the corrected score")
        staged_log = self.staged_text("data/historical/bullpen_log.jsonl")
        self.assertIn('"game_pk": 14', staged_log)
        self.assertIn('"game_pk": 5,', staged_log, "the September row from git is still there")

    def test_nothing_changed_stages_nothing(self):
        done = self.run_block()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.staged(), [])

    def test_a_broken_python_leaves_the_loop_running_and_nothing_staged(self):
        shutil.rmtree(self.repo / "src" / "pipeline" / "__pycache__", ignore_errors=True)
        (self.repo / "src" / "pipeline" / "store_persist.py").write_text("raise SystemExit(7)\n", encoding="utf-8")
        done = self.run_block()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.staged(), [])


@unittest.skipIf(BASH is None, "no usable bash")
class AConflictOnADisplayStoreDoesNotStrandTheDaysOtherData(unittest.TestCase):
    """The persisted display stores ride in the same commit as the day's other
    data. When another writer advanced the same store on origin, `git pull
    --rebase` conflicts in that one file; the loop used to abort and leave the
    whole commit local, and every later run did the same. The commit-and-push tail
    of the REAL script is run under bash against a real bare origin."""

    STORE = "data/historical/bullpen_log.jsonl"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.origin = base / "origin.git"
        self.repo = base / "repo"
        self.other = base / "other"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        self.repo.mkdir()
        self.g(self.repo, "init", "-q", "-b", "main")
        for who in (self.repo,):
            self.config(who)
        (self.repo / "data" / "historical").mkdir(parents=True)
        (self.repo / "data" / "watch").mkdir(parents=True)
        (self.repo / self.STORE).write_text('{"date": "2026-09-05", "game_pk": 5}\n', encoding="utf-8")
        (self.repo / "data/watch/shared.jsonl").write_text('{"k": 0}\n', encoding="utf-8")
        self.g(self.repo, "add", "data")
        self.g(self.repo, "commit", "-q", "-m", "seed")
        self.g(self.repo, "remote", "add", "origin", str(self.origin))
        self.g(self.repo, "push", "-q", "-u", "origin", "main")
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.other)], check=True)
        self.config(self.other)

    def config(self, where):
        self.g(where, "config", "user.email", "t@example.test")
        self.g(where, "config", "user.name", "t")
        self.g(where, "config", "core.autocrlf", "false")

    @staticmethod
    def g(where, *args):
        return subprocess.run(["git", *args], cwd=where, capture_output=True, text=True, check=True).stdout

    def write(self, where, rel, text, mode="a"):
        path = where / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open(mode, encoding="utf-8") as handle:
            handle.write(text)

    def upstream_moves(self, rel, text):
        self.write(self.other, rel, text)
        self.g(self.other, "add", "-A")
        self.g(self.other, "commit", "-q", "-m", "another writer")
        self.g(self.other, "push", "-q", "origin", "main")

    def run_tail(self):
        func = re.search(r"(?ms)^pull_rebase_dropping_display_conflicts\(\) \{.*?^\}$", TEXT)
        block = re.search(r"(?ms)^if ! git diff --cached --quiet; then.*?^fi$", TEXT)
        self.assertIsNotNone(func)
        self.assertIsNotNone(block)
        harness = f"GIT_FAILED=0\n{func.group(0)}\n{block.group(0)}\necho GIT_FAILED=$GIT_FAILED\n"
        return subprocess.run([BASH, "-c", harness], cwd=self.repo, capture_output=True, text=True,
                              env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})

    def origin_file(self, rel):
        done = subprocess.run(["git", "show", f"main:{rel}"], cwd=self.origin, capture_output=True, text=True)
        return done.stdout if done.returncode == 0 else None

    def not_mid_rebase(self):
        self.assertFalse((self.repo / ".git" / "rebase-merge").exists())
        self.assertFalse((self.repo / ".git" / "rebase-apply").exists())

    def test_the_script_calls_the_helper_in_place_of_the_bare_pull(self):
        self.assertIn('pull_rebase_dropping_display_conflicts "$BRANCH"', TEXT)
        self.assertNotIn('elif ! git pull -q --rebase --autostash origin "$BRANCH"', TEXT)

    def test_a_conflict_on_a_display_store_alone_drops_it_and_still_pushes_the_rest(self):
        self.upstream_moves(self.STORE, '{"date": "2026-09-06", "game_pk": 6}\n')
        self.write(self.repo, self.STORE, '{"date": "2026-09-07", "game_pk": 7}\n')
        self.write(self.repo, "data/watch/capture.jsonl", '{"captured": 1}\n')
        self.g(self.repo, "add", self.STORE, "data/watch/capture.jsonl")

        done = self.run_tail()

        out = done.stdout + done.stderr
        self.assertIn("GIT_FAILED=0", out, out)
        self.not_mid_rebase()
        self.assertEqual(self.origin_file("data/watch/capture.jsonl"), '{"captured": 1}\n',
                         "the day's other data reached origin\n" + out)
        store = self.origin_file(self.STORE)
        self.assertIn('"game_pk": 6', store, "the other writer's store is what origin holds")
        self.assertNotIn('"game_pk": 7', store, "our conflicting store was left out of the commit")
        self.assertEqual((self.repo / self.STORE).read_text(encoding="utf-8"), store,
                         "no conflict markers or half-merged copy left in the working tree")
        self.assertEqual(self.g(self.repo, "status", "--porcelain", "--untracked-files=no").strip(), "")

    def test_a_conflict_that_also_names_other_files_is_not_touched(self):
        self.upstream_moves(self.STORE, '{"date": "2026-09-06", "game_pk": 6}\n')
        self.write(self.other, "data/watch/shared.jsonl", '{"k": "other"}\n')
        self.g(self.other, "commit", "-q", "-am", "another writer, watch")
        self.g(self.other, "push", "-q", "origin", "main")
        self.write(self.repo, self.STORE, '{"date": "2026-09-07", "game_pk": 7}\n')
        self.write(self.repo, "data/watch/shared.jsonl", '{"k": "ours"}\n')
        self.g(self.repo, "add", self.STORE, "data/watch/shared.jsonl")

        done = self.run_tail()

        out = done.stdout + done.stderr
        self.assertIn("GIT_FAILED=1", out, out)
        self.assertIn("rebase onto origin/main failed", out)
        self.not_mid_rebase()
        self.assertIn("Daily loop", self.g(self.repo, "log", "-1", "--format=%s"), "the local commit is kept")
        self.assertNotIn('"ours"', self.origin_file("data/watch/shared.jsonl"))

    def test_no_conflict_is_the_old_path(self):
        self.upstream_moves("data/watch/elsewhere.jsonl", '{"k": 1}\n')
        self.write(self.repo, self.STORE, '{"date": "2026-09-07", "game_pk": 7}\n')
        self.g(self.repo, "add", self.STORE)

        done = self.run_tail()

        out = done.stdout + done.stderr
        self.assertIn("GIT_FAILED=0", out, out)
        self.assertIn('"game_pk": 7', self.origin_file(self.STORE))
        self.assertNotIn("dropping them", out)


if __name__ == "__main__":
    unittest.main()
