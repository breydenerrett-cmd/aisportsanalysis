"""data/app/ must be gitignored -- it holds real user records and hashed
auth tokens (src/appstate/users.py, src/appstate/savedbets.py), never
reproducible from a provider and never something to commit.

Same technique as the forward-evidence tracked-files tests: ask git
itself, not a hand-parsed .gitignore, since git is the actual authority
on what a commit would include.
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


class AppDataGitignoreTests(unittest.TestCase):

    def test_data_app_db_file_is_gitignored(self):
        probe = REPO / "data" / "app" / "app.db"
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", str(probe)],
            cwd=REPO, capture_output=True, text=True, check=False)
        self.assertEqual(
            result.returncode, 0,
            f"data/app/app.db is NOT gitignored (git check-ignore exit "
            f"{result.returncode}); stdout={result.stdout!r} "
            f"stderr={result.stderr!r}")

    def test_data_app_gitkeep_survives_and_is_not_ignored(self):
        """The directory itself must still be creatable from a fresh
        checkout -- .gitkeep is deliberately NOT ignored so the empty
        directory exists before any code ever runs."""
        gitkeep = REPO / "data" / "app" / ".gitkeep"
        self.assertTrue(gitkeep.exists(), "data/app/.gitkeep is missing")
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", str(gitkeep)],
            cwd=REPO, capture_output=True, text=True, check=False)
        self.assertEqual(
            result.returncode, 1,
            "data/app/.gitkeep must NOT be gitignored (it needs to be "
            f"trackable); git check-ignore exit={result.returncode}")


if __name__ == "__main__":
    unittest.main()
