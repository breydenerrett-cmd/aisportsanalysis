"""Tests for src/paths.py and the cwd-dependence bug it fixes.

The bug: every data path was a bare relative string resolved against the current
working directory, and every writer called mkdir(parents=True). Reading from the
wrong directory returned an EMPTY dataset with no error; writing from the wrong
directory silently created a second one. Harmless while a human runs commands from
the project folder, fatal the moment anything is scheduled -- cron's working
directory is not the repo.
"""

import os
import tempfile
import unittest
from pathlib import Path

from src import paths


class TestRepoRoot(unittest.TestCase):
    def test_repo_root_is_absolute(self):
        self.assertTrue(paths.repo_root().is_absolute())

    def test_repo_root_contains_the_source_tree(self):
        self.assertTrue((paths.repo_root() / "src" / "paths.py").exists())

    def test_repo_root_is_independent_of_cwd(self):
        # The whole point: deriving from __file__ rather than os.getcwd().
        before = paths.repo_root()
        original = os.getcwd()
        try:
            os.chdir(tempfile.gettempdir())
            self.assertEqual(paths.repo_root(), before)
        finally:
            os.chdir(original)


class TestDataPaths(unittest.TestCase):
    def test_data_paths_are_absolute(self):
        for builder in (paths.data_path, paths.raw_path,
                        paths.processed_path, paths.historical_path):
            with self.subTest(builder=builder.__name__):
                self.assertTrue(builder("x.csv").is_absolute())

    def test_data_path_does_not_move_with_cwd(self):
        before = paths.data_path("historical", "mlb_results.csv")
        original = os.getcwd()
        try:
            os.chdir(tempfile.gettempdir())
            self.assertEqual(paths.data_path("historical", "mlb_results.csv"),
                             before)
        finally:
            os.chdir(original)

    def test_subdirectory_helpers_agree_with_data_path(self):
        self.assertEqual(paths.raw_path("a.csv"), paths.data_path("raw", "a.csv"))
        self.assertEqual(paths.processed_path("b.csv"),
                         paths.data_path("processed", "b.csv"))
        self.assertEqual(paths.historical_path("c.csv"),
                         paths.data_path("historical", "c.csv"))


class TestDataDirOverride(unittest.TestCase):
    def test_override_redirects_the_data_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = os.environ.get(paths.ENV_DATA_DIR)
            try:
                os.environ[paths.ENV_DATA_DIR] = tmp
                self.assertEqual(paths.data_root(), Path(tmp).resolve())
            finally:
                if original is None:
                    os.environ.pop(paths.ENV_DATA_DIR, None)
                else:
                    os.environ[paths.ENV_DATA_DIR] = original

    def test_blank_override_falls_back_to_the_repo(self):
        original = os.environ.get(paths.ENV_DATA_DIR)
        try:
            os.environ[paths.ENV_DATA_DIR] = "   "
            self.assertEqual(paths.data_root(), paths.repo_root() / "data")
        finally:
            if original is None:
                os.environ.pop(paths.ENV_DATA_DIR, None)
            else:
                os.environ[paths.ENV_DATA_DIR] = original


class TestModulesUseAnchoredPaths(unittest.TestCase):
    """Every store constant must be absolute, or a scheduled job forks a second
    empty dataset while the real one goes stale and every report still looks fine."""

    def test_every_default_store_path_is_absolute(self):
        from src.pipeline import grading, history, pitchers, snapshots
        for name, value in (
            ("history.DEFAULT_STORE", history.DEFAULT_STORE),
            ("history.DEFAULT_MANIFEST", history.DEFAULT_MANIFEST),
            ("snapshots.DEFAULT_SNAPSHOT_PATH", snapshots.DEFAULT_SNAPSHOT_PATH),
            ("pitchers.DEFAULT_LOG_STORE", pitchers.DEFAULT_LOG_STORE),
            ("grading.DEFAULT_LOG", grading.DEFAULT_LOG),
        ):
            with self.subTest(constant=name):
                self.assertTrue(Path(value).is_absolute(), f"{name} is relative")


if __name__ == "__main__":
    unittest.main()
