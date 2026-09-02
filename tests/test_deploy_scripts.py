"""Tests for the deploy/ops scripts added alongside deploy/DEPLOY_RUNBOOK.md:
scripts/backup_app_db.sh, scripts/monitor_remote.sh, and the BASE-aware
remote branch added to scripts/smoke_api.sh.

WHY `bash -n`, NOT A FULL RUN, FOR MOST OF THESE
-----------------------------------------------------
scripts/smoke_api.sh and scripts/load_smoke.sh already exercise the real
uvicorn process in their own right (that's their whole job -- see
scripts/ci.sh, which runs smoke_api.sh as its own step rather than a
unittest). Re-running a full uvicorn cycle from inside `python3 -m
unittest discover` would duplicate that and slow the whole suite down for
no new signal. What IS new and testable here without a live server or a
Fly account:

1. Every script in scripts/ and deploy/ still parses as valid bash
   (`bash -n`) -- the cheap, fast regression net for a typo that would
   otherwise only surface the next time someone actually runs the script,
   possibly against a live remote deploy.
2. scripts/backup_app_db.sh's actual behavior (round-trip a real sqlite
   db, prune old backups) -- this has no dependency on a server process
   at all, so it's fully testable by invoking the script against a temp
   db.
3. scripts/smoke_api.sh's BASE branch requires APP_ADMIN_TOKEN and exits
   1 with a clear message otherwise, rather than silently trying (and
   failing confusingly) to mint an invite against a token it never had.

Nothing here talks to Fly, Cloudflare, or any network service --
deploy/fly.*.toml and deploy/CLOUDFLARE.md are read-only documents/config
with no code path to execute, so there is nothing to unit-test in them
beyond the syntax checks below.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import sqlite3
import subprocess
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent

# Every shell script this task added or touched, plus the pre-existing
# ones -- a single list means a future script only needs adding here once
# for both to be covered, the same "name it explicitly" reasoning
# scripts/ci.sh's own docstring gives for naming test_api_boundary.py and
# test_customer_language.py rather than trusting discovery alone.
SHELL_SCRIPTS = [
    "scripts/backup_app_db.sh",
    "scripts/monitor_remote.sh",
    "scripts/smoke_api.sh",
    "scripts/load_smoke.sh",
    "scripts/funnel_smoke.sh",
    "scripts/ci.sh",
    "scripts/forward_capture.sh",
    "scripts/daily_loop.sh",
]


class ShellScriptsParseTest(unittest.TestCase):
    """`bash -n` catches a syntax error without running a single line --
    the same reasoning deploy/secrets.md's NEVER-COMMIT test applies to
    secrets: a mistake here is cheap to catch mechanically and expensive
    to discover for the first time against a live remote deploy."""

    def test_every_listed_script_parses(self):
        for rel in SHELL_SCRIPTS:
            path = REPO / rel
            with self.subTest(script=rel):
                self.assertTrue(path.is_file(), f"{rel} does not exist")
                result = subprocess.run(
                    ["bash", "-n", str(path)],
                    capture_output=True, text=True,
                )
                self.assertEqual(
                    result.returncode, 0,
                    f"bash -n failed for {rel}:\n{result.stderr}",
                )

    def test_scripts_are_executable(self):
        # Not a correctness requirement for `bash scripts/foo.sh`, but
        # every script in this repo's scripts/ dir is invoked directly
        # (`scripts/foo.sh`) somewhere in its own docs/runbooks -- a
        # script that lost its execute bit would fail exactly there, not
        # in `bash -n`, so this catches the other half of "can this
        # actually be run."
        for rel in SHELL_SCRIPTS:
            path = REPO / rel
            with self.subTest(script=rel):
                self.assertTrue(
                    path.stat().st_mode & 0o111,
                    f"{rel} is not executable",
                )


class BackupAppDbRoundTripTest(unittest.TestCase):
    """scripts/backup_app_db.sh against a real temp sqlite db -- no
    server, no Fly, no network: exactly the "testable where testable"
    scope this script's own task called for."""

    def setUp(self):
        self.tmp_dir = REPO / "tests" / "_tmp_backup_app_db_test"
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
        self.tmp_dir.mkdir(parents=True)
        self.src_db = self.tmp_dir / "app.db"
        self.backup_dir = self.tmp_dir / "backups"

        conn = sqlite3.connect(self.src_db)
        conn.execute("CREATE TABLE invites (token TEXT, email TEXT)")
        conn.execute(
            "INSERT INTO invites VALUES (?, ?)", ("tok-1", "a@example.com")
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _run_backup(self, retention_days=None):
        env = dict(os.environ)
        if retention_days is not None:
            env["BACKUP_RETENTION_DAYS"] = str(retention_days)
        return subprocess.run(
            ["bash", str(REPO / "scripts" / "backup_app_db.sh"),
             str(self.src_db), str(self.backup_dir)],
            capture_output=True, text=True, env=env,
        )

    def test_backup_produces_a_readable_copy_with_the_same_rows(self):
        result = self._run_backup()
        self.assertEqual(result.returncode, 0, result.stderr)

        produced = list(self.backup_dir.glob("app-*.db"))
        self.assertEqual(
            len(produced), 1,
            f"expected exactly one backup file, found {produced}",
        )

        conn = sqlite3.connect(produced[0])
        rows = conn.execute("SELECT token, email FROM invites").fetchall()
        conn.close()
        self.assertEqual(rows, [("tok-1", "a@example.com")])

    def test_missing_source_db_fails_loudly_not_silently(self):
        result = subprocess.run(
            ["bash", str(REPO / "scripts" / "backup_app_db.sh"),
             str(self.tmp_dir / "does-not-exist.db"), str(self.backup_dir)],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not found", result.stderr)
        # No backup directory should be created for a source that never
        # existed -- an empty backups/ dir left behind would look like a
        # successful-but-empty backup to anyone glancing at the filesystem.
        self.assertFalse(self.backup_dir.exists())

    def test_prunes_backups_older_than_retention_window(self):
        self.backup_dir.mkdir(parents=True)
        old_backup = self.backup_dir / "app-20200101T000000Z.db"
        old_backup.write_bytes(b"")
        # Old enough to definitely clear a 14-day (or even 1-day) window
        # regardless of what "now" the test runs under.
        old_mtime = 0  # epoch -- unambiguously older than any retention window
        os.utime(old_backup, (old_mtime, old_mtime))

        result = self._run_backup(retention_days=1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(
            old_backup.exists(),
            "backup older than the retention window was not pruned",
        )
        # The fresh backup this same run just wrote must survive its own
        # prune pass -- proves the prune targets *old* files, not every
        # file matching the glob.
        remaining = list(self.backup_dir.glob("app-*.db"))
        self.assertEqual(len(remaining), 1)


class SmokeApiRemoteBranchTest(unittest.TestCase):
    """scripts/smoke_api.sh's BASE-aware branch (deploy/DEPLOY_RUNBOOK.md
    Step 2) -- checked here without a live remote deploy by asserting the
    one thing that doesn't need one: BASE set with no APP_ADMIN_TOKEN
    fails fast with a clear message, rather than limping into an
    unauthenticated admin-invite call and failing confusingly later."""

    def test_base_without_admin_token_fails_fast_with_clear_message(self):
        env = dict(os.environ)
        env.pop("APP_ADMIN_TOKEN", None)
        env["BASE"] = "http://127.0.0.1:1"  # never dialed -- token check
                                             # must happen before any
                                             # network access
        result = subprocess.run(
            ["bash", str(REPO / "scripts" / "smoke_api.sh")],
            capture_output=True, text=True, env=env, timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("APP_ADMIN_TOKEN", result.stderr + result.stdout)


class DataPlaneGitRaceTest(unittest.TestCase):
    """scripts/forward_capture.sh and scripts/daily_loop.sh commit and push
    forward-evidence data from a shared checkout, hourly and daily
    respectively, with no coordination between the two. Git history shows
    four stranded/raced recoveries in 30h (87312f2, de8a582, b258fc1,
    9d30526) before this test existed. These are pure text assertions on
    the checked-in scripts -- no script is executed, so there is no lock
    contention, network call, or git state to fake.
    """

    DATA_PLANE_SCRIPTS = ("scripts/forward_capture.sh", "scripts/daily_loop.sh")

    def _text(self, rel):
        return (REPO / rel).read_text()

    def test_both_scripts_share_the_same_flock_lock_file(self):
        for rel in self.DATA_PLANE_SCRIPTS:
            with self.subTest(script=rel):
                text = self._text(rel)
                self.assertIn(
                    "/tmp/linehound_git.lock", text,
                    f"{rel} does not use the shared git lock file -- it can "
                    "still race the other data-plane script's commit",
                )
                self.assertIn(
                    "flock", text,
                    f"{rel} references the lock file but never calls flock "
                    "on it",
                )

    def test_both_scripts_rebase_onto_origin_before_pushing(self):
        for rel in self.DATA_PLANE_SCRIPTS:
            with self.subTest(script=rel):
                text = self._text(rel)
                self.assertIn(
                    "git fetch", text,
                    f"{rel} pushes without first fetching origin",
                )
                self.assertIn(
                    "--rebase", text,
                    f"{rel} does not rebase its own commit onto origin "
                    "before pushing -- concurrent pushes can still race",
                )
                self.assertIn(
                    "--autostash", text,
                    f"{rel} rebases without --autostash",
                )
                # The rebase must run, textually, before the push it is
                # meant to protect -- a rebase call added anywhere else in
                # the file wouldn't actually order-before the push.
                rebase_pos = text.index("--rebase")
                push_pos = text.index("git push")
                self.assertLess(
                    rebase_pos, push_pos,
                    f"{rel} calls git push before its rebase-onto-origin "
                    "step, so the rebase does not protect that push",
                )

    def test_both_scripts_escalate_on_push_failure_instead_of_lying(self):
        # The bug this closes: both scripts used to print '== committed =='
        # unconditionally, never checking git commit's or git push's real
        # exit status (set -uo pipefail with no -e lets both fail silently).
        for rel in self.DATA_PLANE_SCRIPTS:
            with self.subTest(script=rel):
                text = self._text(rel)
                self.assertRegex(
                    text, r"ESCALATE:.*push failed",
                    f"{rel} has no ESCALATE line for a failed push -- a "
                    "failed push can still be reported as committed",
                )
                self.assertRegex(
                    text, r"ESCALATE: git lock not acquired",
                    f"{rel} does not escalate on a flock timeout",
                )

    def test_daily_loop_no_longer_stages_bare_data(self):
        text = self._text("scripts/daily_loop.sh")
        add_lines = [
            line for line in text.splitlines()
            if line.strip().startswith("git add ")
        ]
        self.assertTrue(add_lines, "daily_loop.sh has no git add line")
        for line in add_lines:
            tokens = line.split()
            self.assertNotIn(
                "data", tokens,
                f"daily_loop.sh stages bare 'data' ({line!r}), which pulls "
                "in data/app and data/raw -- it must name explicit paths "
                "under data/ instead",
            )
            self.assertNotIn("data/app", tokens)
            self.assertNotIn("data/raw", tokens)
        # The narrowed set this task specified -- explicit, not inferred.
        for expected in ("data/processed", "data/watch", "data/research",
                          "evidence", "docs/OVERNIGHT_RUN.md", "artifacts"):
            self.assertIn(
                expected, text,
                f"daily_loop.sh no longer stages {expected}",
            )


if __name__ == "__main__":
    unittest.main()
