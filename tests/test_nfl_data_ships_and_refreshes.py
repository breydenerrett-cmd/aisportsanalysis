"""The NFL data layer ships in the image and the daily loop keeps it current.

2026-10-03: /data/v1/nfl reads data/datasvc/nfl (src/datasvc/nfl/store.py). The worker that
built it left the image and the daily loop naming only the UFC directory, so production would
have answered every NFL data route from an empty store, and the files would have stayed at the
day of the backfill. Same failure class as tests/test_image_ships_ufc_data.py and
tests/test_daily_loop_ufc_data.py, which this mirrors.
"""
import re
import unittest
from pathlib import Path

from src.datasvc.nfl import store as nfl_store
from tests.test_image_ships_ufc_data import _rules, excluded_from_build_context

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
SCRIPT = (ROOT / "scripts" / "daily_loop.sh").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "daily-loop.yml").read_text(encoding="utf-8")
STEP = "python3 -m src.datasvc.cli nfl update"


class TheImageCarriesTheNflData(unittest.TestCase):
    def test_the_directory_is_copied_to_where_the_store_reads_it(self):
        self.assertRegex(DOCKERFILE, re.compile(r"^COPY data/datasvc/nfl/ data/datasvc/nfl/\s*$", re.M))
        self.assertEqual(nfl_store.DEFAULT_DIR.relative_to(ROOT).as_posix(), "data/datasvc/nfl")

    def test_the_copy_sits_before_the_display_refresh_step(self):
        self.assertLess(DOCKERFILE.index("COPY data/datasvc/nfl/"),
                        DOCKERFILE.index("python -m src.pipeline.display_refresh"))

    def test_the_build_context_admits_the_files_and_not_the_raw_cache(self):
        rules = _rules(ROOT / ".dockerignore")
        on_disk = sorted(p.name for p in (ROOT / "data" / "datasvc" / "nfl").glob("*") if p.is_file())
        self.assertIn("games.jsonl", on_disk)
        for name in on_disk:
            self.assertFalse(excluded_from_build_context(f"data/datasvc/nfl/{name}", rules), name)
        self.assertTrue(excluded_from_build_context("data/datasvc/raw/github.com/x.csv", rules))


class TheDailyLoopUpdatesTheNflData(unittest.TestCase):
    def test_one_guarded_capped_update(self):
        lines = [line for line in SCRIPT.splitlines() if STEP in line]
        self.assertEqual(len(lines), 1, lines)
        self.assertRegex(lines[0], r"--max-requests \d+")
        self.assertTrue(lines[0].rstrip().endswith("|| true"), lines[0])

    def test_it_runs_before_the_commit_and_its_directory_is_staged(self):
        self.assertLess(SCRIPT.index(STEP), SCRIPT.index("git add data/processed"))
        joined = " ".join(line for line in SCRIPT.splitlines() if line.strip().startswith("git add "))
        self.assertIn("data/datasvc/nfl", joined.split())

    def test_the_directory_is_not_restored_from_the_cache(self):
        self.assertNotIn("datasvc", WORKFLOW)


if __name__ == "__main__":
    unittest.main()
