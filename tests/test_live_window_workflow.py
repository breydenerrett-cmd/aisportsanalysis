"""Tests for the live-window workflow file and its runner script.

Text assertions only. The first version parsed the workflow with PyYAML,
which is not in the standard library; CI runs `python -m unittest discover`
on a bare interpreter, so that import failed the whole module on every
Python version while passing on the one developer box that happened to
have PyYAML installed. Every check below reads the file as text, which is
also what tests/test_capture_no_set_time.py does for the capture workflow.
"""

import re
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "live-window.yml"
SCRIPT = REPO / "scripts" / "live_window.sh"
MODULE = REPO / "src" / "pipeline" / "live_window.py"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _block(text: str, start_key: str) -> str:
    """The lines from `start_key` up to the next line at column 0."""
    lines = text.splitlines()
    out = []
    capturing = False
    for line in lines:
        if capturing:
            if line and not line[0].isspace():
                break
            out.append(line)
        elif line.startswith(start_key):
            capturing = True
            out.append(line)
    return "\n".join(out)


class TestLiveWindowWorkflow(unittest.TestCase):
    """Tests for .github/workflows/live-window.yml."""

    def test_workflow_file_exists(self):
        self.assertTrue(WORKFLOW.exists(), f"{WORKFLOW} does not exist")

    def test_workflow_dispatch_input_sport(self):
        text = _text(WORKFLOW)
        on_block = _block(text, '"on":') or _block(text, "on:")
        self.assertIn("workflow_dispatch:", on_block)
        start = on_block.find("sport:")
        self.assertNotEqual(start, -1, "no `sport` input under workflow_dispatch")
        end = on_block.find("max_minutes:", start)
        sport_block = on_block[start:end if end != -1 else None]
        self.assertRegex(sport_block, r"-\s*mlb")
        self.assertRegex(sport_block, r"-\s*nfl")

    def test_workflow_dispatch_input_max_minutes(self):
        text = _text(WORKFLOW)
        start = text.find("max_minutes:")
        self.assertNotEqual(start, -1, "no `max_minutes` input")
        end = text.find("permissions:", start)
        block = text[start:end if end != -1 else None]
        self.assertRegex(block, r'default:\s*"?330"?')

    def test_workflow_concurrency_group_contains_sport(self):
        block = _block(_text(WORKFLOW), "concurrency:")
        self.assertIn("live-window", block)
        self.assertIn("inputs.sport", block)

    def test_workflow_concurrency_cancel_false(self):
        block = _block(_text(WORKFLOW), "concurrency:")
        self.assertRegex(block, r"cancel-in-progress:\s*false")

    def test_workflow_timeout_350_minutes(self):
        self.assertRegex(_text(WORKFLOW), r"timeout-minutes:\s*350")

    def test_workflow_env_odds_api_key_from_secrets(self):
        content = _text(WORKFLOW)
        self.assertIn("ODDS_API_KEY: ${{ secrets.ODDS_API_KEY }}", content)
        # The secret is referenced by name exactly once, never anywhere else.
        self.assertEqual(content.count("secrets.ODDS_API_KEY"), 1)

    def test_workflow_env_live_odds_from_vars(self):
        self.assertIn("vars.LIVE_ODDS", _text(WORKFLOW))

    def test_workflow_no_echo_secrets(self):
        self.assertNotIn("echo ${{ secrets", _text(WORKFLOW))

    def test_workflow_no_cron_schedule(self):
        on_block = _block(_text(WORKFLOW), '"on":') or _block(_text(WORKFLOW), "on:")
        self.assertNotIn("schedule:", on_block)
        self.assertNotIn("cron:", _text(WORKFLOW))

    def test_workflow_runs_the_script_with_both_inputs(self):
        content = _text(WORKFLOW)
        self.assertIn("scripts/live_window.sh", content)
        self.assertIn("inputs.sport", content)
        self.assertIn("inputs.max_minutes", content)


class TestLiveWindowScript(unittest.TestCase):
    """Tests for scripts/live_window.sh and the module's commit path."""

    def test_script_exists(self):
        self.assertTrue(SCRIPT.exists(), f"{SCRIPT} does not exist")

    def test_script_bash_syntax(self):
        try:
            result = subprocess.run(["bash", "-n", str(SCRIPT)],
                                    capture_output=True, timeout=5)
        except FileNotFoundError:
            self.skipTest("bash not available on this system")
        except subprocess.TimeoutExpired:
            self.skipTest("bash syntax check timed out")
        output = ""
        for stream in (result.stdout, result.stderr):
            if stream:
                output += stream.decode("utf-16le", errors="ignore")
                output += stream.decode("utf-8", errors="ignore")
        lowered = output.lower()
        if result.returncode != 0 and ("wsl" in lowered or "windows subsystem" in lowered
                                       or "not installed" in lowered):
            self.skipTest("bash not available on this system")
        self.assertEqual(result.returncode, 0, "bash -n failed for scripts/live_window.sh")

    def test_script_exports_commit_env(self):
        content = _text(SCRIPT)
        self.assertIn("LIVE_WINDOW_COMMIT=1", content)
        self.assertIn("export LIVE_WINDOW_COMMIT", content)

    def test_module_stages_live_data(self):
        content = _text(MODULE)
        self.assertIn("data/live", content)
        self.assertIn("evidence/live_candidates_v1.jsonl", content)

    def test_module_pushes_what_it_commits(self):
        """A commit on the runner that is never pushed dies with the job."""
        content = _text(MODULE)
        self.assertIn('"push"', content)
        self.assertIn('"--rebase"', content)
        self.assertIn('"--autostash"', content)
        self.assertIn("user.email", content)


if __name__ == "__main__":
    unittest.main()
