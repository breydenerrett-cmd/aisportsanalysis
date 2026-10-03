"""The deployed image carries the earlier postseasons the game page's Situation block reads.

2026-10-03: the situation layer reads 2015-2025 postseason games and season records from
`data/research/postseason_history/` at request time (api/games.py -> src.analyst.source ->
src.situation.postseason_history). `.dockerignore` admitted only the research registry under
`data/research/`, so the image would have shipped without the store and the block would have
fallen back, silently, to the results store's 2023 start. Same failure class as config/ and the
UFC data earlier that day (tests/test_image_ships_config.py, tests/test_image_ships_ufc_data.py).
"""
import re
import unittest
from pathlib import Path

from src.situation import postseason_history
from tests.test_image_ships_ufc_data import _rules, excluded_from_build_context

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
STORE = "data/research/postseason_history"


class TheImageCarriesThePostseasonHistory(unittest.TestCase):
    def test_the_store_is_copied_to_where_the_reader_looks(self):
        self.assertRegex(DOCKERFILE, re.compile(rf"^COPY {STORE}/ {STORE}/\s*$", re.M))
        self.assertEqual(postseason_history.default_root().relative_to(ROOT).as_posix(), STORE)

    def test_the_copy_sits_before_the_display_refresh_step(self):
        self.assertLess(DOCKERFILE.index(f"COPY {STORE}/"),
                        DOCKERFILE.index("python -m src.pipeline.display_refresh"))

    def test_the_build_context_admits_its_files_and_still_drops_other_research(self):
        rules = _rules(ROOT / ".dockerignore")
        for name in (postseason_history.GAMES_FILE, postseason_history.RECORDS_FILE,
                     postseason_history.MANIFEST_FILE):
            self.assertFalse(excluded_from_build_context(f"{STORE}/{name}", rules), name)
        self.assertTrue(excluded_from_build_context("data/research/sweeps/run.json", rules))
        self.assertFalse(excluded_from_build_context("data/research/alpha_registry.jsonl", rules))

    def test_the_files_are_in_the_repository(self):
        for name in (postseason_history.GAMES_FILE, postseason_history.RECORDS_FILE):
            self.assertTrue((ROOT / STORE / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
