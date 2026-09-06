"""P0-2 (docs/AUTONOMOUT_PRODUCT_QUEUE.md): the 10:00Z daily loop, runnable
from GitHub Actions with no interactive session -- the same externalization
scripts/capture_slot.sh + .github/workflows/forward-capture.yml already did
for forward capture (see docs/CAPTURE_EXTERNALIZATION.md, "Daily loop
externalization").

Three things are tested, matching the task's own three deliverables:

1. `scripts/daily_bootstrap.sh` parses as valid bash (also covered by
   tests/test_deploy_scripts.py's SHELL_SCRIPTS list, repeated here as a
   fast standalone signal) and genuinely refuses -- ESCALATE line, non-zero
   exit, no season build attempted -- when the Statcast manifest is
   missing, using a scratch `AISPORTS_DATA_DIR` so this never touches the
   real (large, gitignored) data/historical/ tree. Hermetic: no network.
2. The same refusal path leaves the mlb_results/pitcher/bullpen stores
   untouched -- a hard stop must not partially rebuild other inputs first.
3. `.github/workflows/daily-loop.yml` has the shared `forward-capture`
   concurrency group (the cross-runner substitute for the process-local
   flock both scripts otherwise rely on), the 10:00 UTC cron, the explicit
   working-branch checkout ref (the default-branch constraint
   docs/CAPTURE_EXTERNALIZATION.md documents), no `git add -A` anywhere in
   the workflow, and a step that fails the job when the loop's own output
   carries an `ESCALATE:` line.

What is NOT re-tested here: `scripts/daily_loop.sh`'s own step wiring
(order, exit-status capture, escalation) already has full coverage in
tests/test_daily_loop_wiring.py and is unchanged by this task -- this
module only covers the two new files that make that script runnable from a
cold checkout.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
BOOTSTRAP = REPO / "scripts" / "daily_bootstrap.sh"
WORKFLOW = REPO / ".github" / "workflows" / "daily-loop.yml"


def _run_bootstrap(data_dir, timeout=60):
    env = {"AISPORTS_DATA_DIR": str(data_dir), "PATH": __import__("os").environ["PATH"]}
    return subprocess.run(
        ["bash", str(BOOTSTRAP)],
        cwd=REPO, capture_output=True, text=True, env=env, timeout=timeout,
    )


class DailyBootstrapParsesTest(unittest.TestCase):
    def test_parses_as_valid_bash(self):
        result = subprocess.run(["bash", "-n", str(BOOTSTRAP)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_is_executable(self):
        self.assertTrue(BOOTSTRAP.stat().st_mode & 0o111,
                        "scripts/daily_bootstrap.sh is not executable")


class DailyBootstrapRefusesOnMissingStatcastManifestTest(unittest.TestCase):
    """The one hard stop condition the task called out explicitly: with NO
    Statcast manifest, the bootstrap must refuse rather than fetch a whole
    season. Exercised against a genuinely empty scratch data root -- no
    stubbing of the python calls themselves, since the script's own
    statcast check runs before any of them."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = pathlib.Path(self._tmp.name)

    def test_refuses_with_escalate_and_nonzero_exit(self):
        result = _run_bootstrap(self.data_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ESCALATE:", result.stdout)
        self.assertIn("statcast", result.stdout.lower())

    def test_refuses_before_touching_any_other_store(self):
        # A partially-completed rebuild after a hard stop would be worse
        # than no rebuild at all -- it would look like a successful
        # bootstrap on the next run's file-existence checks.
        result = _run_bootstrap(self.data_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.data_dir / "historical" / "mlb_results.csv").exists())
        self.assertFalse((self.data_dir / "historical" / "pitcher_logs.jsonl").exists())
        self.assertFalse((self.data_dir / "historical" / "bullpen_log.jsonl").exists())

    def test_never_calls_statcast_build(self):
        # The refusal must be the script's OWN file check, not a downstream
        # failure from attempting build() and catching its error -- grep
        # the script text for the one command that would fetch a whole
        # season, and confirm it is never invoked at all.
        text = BOOTSTRAP.read_text()
        self.assertNotIn("statcast_pitches.build(", text)
        self.assertNotIn(".build(", text)


class DailyBootstrapProceedsWithStatcastManifestTest(unittest.TestCase):
    """A present manifest must not be treated as a reason to refuse -- the
    opposite failure mode (refusing forever because some unrelated check is
    too strict) is just as bad as never refusing at all."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = pathlib.Path(self._tmp.name)
        statcast_dir = self.data_dir / "historical" / "statcast"
        statcast_dir.mkdir(parents=True)
        (statcast_dir / "manifest.json").write_text(json.dumps(
            {"windows": {"2020-01-01..2020-01-04": {"rows": 1, "file": "x.jsonl.gz"}}}
        ))

    def test_does_not_escalate_on_the_statcast_check(self):
        # A short timeout is deliberate: once past the statcast gate this
        # command starts a real (network) season rebuild that legitimately
        # takes minutes (see scripts/daily_bootstrap.sh's own header for
        # measured per-date costs) -- this test only needs to observe that
        # it GOT PAST the statcast gate and started that work, not that it
        # finished. A timeout is treated as "still running the rebuild",
        # not a test failure.
        try:
            result = _run_bootstrap(self.data_dir, timeout=8)
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or "")
            if isinstance(output, bytes):
                output = output.decode("utf-8", "replace")
        else:
            output = result.stdout
        self.assertIn("statcast manifest present", output)
        self.assertNotIn("ESCALATE: no Statcast manifest", output)


class DailyLoopWorkflowWiringTest(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text()

    def test_workflow_file_exists(self):
        self.assertTrue(WORKFLOW.is_file())

    def test_cron_is_10_utc_daily(self):
        self.assertIn('cron: "0 10 * * *"', self.text)

    def test_workflow_dispatch_present(self):
        self.assertIn("workflow_dispatch:", self.text)

    def test_checkout_pins_the_working_branch(self):
        self.assertIn("ref: claude/sports-betting-analysis-review-g1o0co",
                      self.text)

    def test_shares_the_forward_capture_concurrency_group(self):
        # Both workflows commit+push to the same shared checkout under the
        # same process-local flock -- across two Actions runners that lock
        # cannot serialize them, so the concurrency group must, and it must
        # be the SAME group forward-capture.yml uses, not a same-named but
        # independent one.
        self.assertIn("group: forward-capture", self.text)
        self.assertIn("cancel-in-progress: false", self.text)
        capture_workflow = (REPO / ".github" / "workflows"
                           / "forward-capture.yml").read_text()
        self.assertIn("group: forward-capture", capture_workflow)

    def test_no_blanket_git_add(self):
        self.assertNotIn("git add -A", self.text)
        self.assertNotIn("git add .", self.text)

    def test_runs_bootstrap_then_the_daily_loop(self):
        # The header comment mentions daily_loop.sh before the workflow's
        # first real step, so anchor on the actual invocations
        # (`run: bash scripts/...`), not on any textual mention.
        bootstrap_pos = self.text.index("bash scripts/daily_bootstrap.sh")
        loop_pos = self.text.index("bash scripts/daily_loop.sh")
        self.assertLess(bootstrap_pos, loop_pos,
                        "bootstrap must run before daily_loop.sh")

    def test_bootstrap_output_feeds_the_same_escalate_check_as_the_loop(self):
        # A bootstrap-level escalation that does not itself exit non-zero
        # (e.g. a failed bullpen backfill -- recoverable next run) must
        # still reach the ESCALATE check, not just daily_loop.sh's own
        # output -- both steps tee into the same combined log file.
        bootstrap_step = self.text[self.text.index("Bootstrap git-ignored"):
                                   self.text.index("Run the daily loop")]
        loop_step = self.text[self.text.index("Run the daily loop"):
                              self.text.index("Fail the job")]
        self.assertIn("tee ", bootstrap_step)
        self.assertIn("tee ", loop_step)
        # Same log file on both sides, and the same file the ESCALATE
        # check greps.
        import re
        bootstrap_log = re.search(r"tee (?:-a )?(\S+)", bootstrap_step).group(1)
        loop_log = re.search(r"tee (?:-a )?(\S+)", loop_step).group(1)
        self.assertEqual(bootstrap_log, loop_log)
        check_step = self.text[self.text.index("Fail the job"):]
        self.assertIn(bootstrap_log, check_step)

    def test_fails_the_job_on_any_escalate_line(self):
        self.assertIn("ESCALATE:", self.text)
        # The failing step must actually exit non-zero, not just print.
        fail_step_pos = self.text.index("Fail the job on any ESCALATE line")
        fail_step_text = self.text[fail_step_pos:fail_step_pos + 400]
        self.assertIn("exit 1", fail_step_text)

    def test_git_identity_is_daily_loop_bot(self):
        self.assertIn('user.name "daily-loop-bot"', self.text)

    def test_only_declares_the_odds_api_key_secret(self):
        # The mission's one hard boundary: no secret other than
        # ODDS_API_KEY may be referenced.
        import re
        secrets_used = set(re.findall(r"secrets\.([A-Za-z0-9_]+)", self.text))
        self.assertEqual(secrets_used, {"ODDS_API_KEY"})


if __name__ == "__main__":
    unittest.main()
