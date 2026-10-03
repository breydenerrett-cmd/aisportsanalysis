"""The deployed image carries the settings that request-time code reads.

2026-10-03: the "If you had followed every pick" section answered "The example
account settings could not be read." on staging while every local test passed,
because deploy/Dockerfile never copied config/ and the loader read a path
relative to the working directory. These tests pin both halves.
"""
import os
import re
import unittest
from pathlib import Path

from src.appstate import example_accounts

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")


class TheImageCopiesConfig(unittest.TestCase):
    def test_config_directory_is_copied(self):
        self.assertRegex(DOCKERFILE, re.compile(r"^COPY config/ config/\s*$", re.M))

    def test_dockerignore_does_not_drop_config(self):
        ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        rules = [line.strip() for line in ignore if line.strip() and not line.strip().startswith("#")]
        for rule in rules:
            self.assertFalse(rule.rstrip("/") in ("config", "config/*", "/config"),
                             f".dockerignore excludes config/: {rule}")

    def test_every_config_file_request_code_reads_exists_in_the_repo(self):
        self.assertTrue(Path(example_accounts.CONFIG_PATH).is_file(), example_accounts.CONFIG_PATH)


class TheLoaderDoesNotDependOnTheWorkingDirectory(unittest.TestCase):
    def test_config_path_is_absolute_and_under_the_repo(self):
        path = Path(example_accounts.CONFIG_PATH)
        self.assertTrue(path.is_absolute(), path)
        self.assertEqual(path.relative_to(ROOT).as_posix(), "config/example_accounts.json")

    def test_loading_works_from_another_directory(self):
        here = os.getcwd()
        try:
            os.chdir(str(ROOT / "deploy"))
            config = example_accounts.load_config()
        finally:
            os.chdir(here)
        self.assertTrue(config["accounts"])


if __name__ == "__main__":
    unittest.main()
