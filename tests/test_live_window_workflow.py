"""Tests for live-window workflow YAML and scripts.

YAML/text assertions and bash syntax checks.
"""

import subprocess
import unittest
from pathlib import Path
import yaml


class TestLiveWindowWorkflow(unittest.TestCase):
    """Tests for .github/workflows/live-window.yml."""

    def test_workflow_file_exists(self):
        """live-window.yml exists."""
        path = Path(".github/workflows/live-window.yml")
        self.assertTrue(path.exists(), f"{path} does not exist")

    def test_workflow_yaml_valid(self):
        """Workflow file is valid YAML."""
        with open(".github/workflows/live-window.yml", "r") as f:
            config = yaml.safe_load(f)
        self.assertIsNotNone(config)

    def test_workflow_dispatch_input_sport(self):
        """Workflow has sport input."""
        with open(".github/workflows/live-window.yml", "r") as f:
            config = yaml.safe_load(f)
        inputs = config.get("on", {}).get("workflow_dispatch", {}).get("inputs", {})
        self.assertIn("sport", inputs)
        self.assertIn("mlb", inputs["sport"].get("options", []))
        self.assertIn("nfl", inputs["sport"].get("options", []))

    def test_workflow_dispatch_input_max_minutes(self):
        """Workflow has max_minutes input with default 330."""
        with open(".github/workflows/live-window.yml", "r") as f:
            config = yaml.safe_load(f)
        inputs = config.get("on", {}).get("workflow_dispatch", {}).get("inputs", {})
        self.assertIn("max_minutes", inputs)
        self.assertEqual(inputs["max_minutes"].get("default"), "330")

    def test_workflow_concurrency_group_contains_sport(self):
        """Concurrency group contains sport input expression."""
        with open(".github/workflows/live-window.yml", "r") as f:
            config = yaml.safe_load(f)
        concurrency = config.get("concurrency", {})
        group = concurrency.get("group", "")
        self.assertIn("live-window", group)
        self.assertIn("inputs.sport", group)

    def test_workflow_concurrency_cancel_false(self):
        """Concurrency cancel-in-progress is false."""
        with open(".github/workflows/live-window.yml", "r") as f:
            config = yaml.safe_load(f)
        concurrency = config.get("concurrency", {})
        self.assertFalse(concurrency.get("cancel-in-progress"))

    def test_workflow_timeout_350_minutes(self):
        """Job timeout is 350 minutes."""
        with open(".github/workflows/live-window.yml", "r") as f:
            config = yaml.safe_load(f)
        run_job = config.get("jobs", {}).get("run", {})
        timeout = run_job.get("timeout-minutes")
        self.assertEqual(timeout, 350)

    def test_workflow_env_odds_api_key_from_secrets(self):
        """Workflow env ODDS_API_KEY uses secrets.ODDS_API_KEY expression."""
        with open(".github/workflows/live-window.yml", "r") as f:
            content = f.read()
        self.assertIn("secrets.ODDS_API_KEY", content)
        self.assertIn("ODDS_API_KEY: ${{ secrets.ODDS_API_KEY }}", content)

    def test_workflow_env_live_odds_from_vars(self):
        """Workflow env LIVE_ODDS uses vars.LIVE_ODDS."""
        with open(".github/workflows/live-window.yml", "r") as f:
            content = f.read()
        self.assertIn("vars.LIVE_ODDS", content)

    def test_workflow_no_echo_secrets(self):
        """Workflow file has no echo of secrets."""
        with open(".github/workflows/live-window.yml", "r") as f:
            content = f.read()
        # Should not have echo ${{ secrets.ODDS_API_KEY }}
        self.assertNotIn("echo ${{ secrets", content)

    def test_workflow_no_cron_schedule(self):
        """Workflow has no cron schedule."""
        with open(".github/workflows/live-window.yml", "r") as f:
            config = yaml.safe_load(f)
        on_config = config.get("on", {})
        # schedule should not exist
        self.assertNotIn("schedule", on_config)

    def test_script_exists(self):
        """live_window.sh script exists."""
        path = Path("scripts/live_window.sh")
        self.assertTrue(path.exists(), f"{path} does not exist")

    def test_script_bash_syntax(self):
        """Script passes bash -n syntax check."""
        try:
            result = subprocess.run(
                ["bash", "-n", "scripts/live_window.sh"],
                capture_output=True,
                timeout=5
            )
        except FileNotFoundError:
            self.skipTest("bash not available on this system")
        except subprocess.TimeoutExpired:
            self.skipTest("bash syntax check timed out")

        # Check for WSL/bash unavailability in either stdout or stderr
        output = result.stdout.decode('utf-16le', errors='ignore') if result.stdout else ""
        output += result.stderr.decode('utf-16le', errors='ignore') if result.stderr else ""

        if (result.returncode != 0 and
            ("wsl" in output.lower() or "windows subsystem" in output.lower() or
             "not installed" in output.lower())):
            self.skipTest("bash not available on this system")
        self.assertEqual(result.returncode, 0, f"Bash syntax error")

    def test_script_exports_commit_env(self):
        """Script exports LIVE_WINDOW_COMMIT=1."""
        with open("scripts/live_window.sh", "r") as f:
            content = f.read()
        self.assertIn("LIVE_WINDOW_COMMIT=1", content)
        self.assertIn("export LIVE_WINDOW_COMMIT", content)

    def test_script_stages_live_data(self):
        """live_window module stages data/live and evidence/live_candidates_v1.jsonl."""
        with open("src/pipeline/live_window.py", "r") as f:
            content = f.read()
        # Check that the commit command includes these paths
        self.assertIn("data/live", content)
        self.assertIn("evidence/live_candidates_v1.jsonl", content)


if __name__ == "__main__":
    unittest.main()
