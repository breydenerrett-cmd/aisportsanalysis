"""The daily loop keeps the UFC data layer current and commits only its normalised files.

2026-10-03: the fight-night page and the data API read data/datasvc/ufc, which now ships in
the image (tests/test_image_ships_ufc_data.py). Nothing refreshed it, so the page would have
served the day of the backfill forever. The daily loop now runs `ufc update` (the last 10
days of results and the next 21 days of booked cards) and stages that directory. It is not in
the daily loop's actions/cache restore, so the copy on disk is git's own and staging it only
adds rows; the raw fetch cache beside it is git-ignored and never staged.
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = (REPO / "scripts" / "daily_loop.sh").read_text(encoding="utf-8")
WORKFLOW = (REPO / ".github" / "workflows" / "daily-loop.yml").read_text(encoding="utf-8")
STEP = "python3 -m src.datasvc.cli ufc update"


class TheDailyLoopUpdatesTheUfcData(unittest.TestCase):
    def test_one_guarded_capped_update_without_profiles(self):
        lines = [line for line in SCRIPT.splitlines() if STEP in line]
        self.assertEqual(len(lines), 1, lines)
        line = lines[0]
        self.assertIn("--no-profiles", line)
        self.assertRegex(line, r"--max-requests \d+")
        self.assertTrue(line.rstrip().endswith("|| true"), line)

    def test_it_runs_before_the_commit(self):
        self.assertLess(SCRIPT.index(STEP), SCRIPT.index("git add data/processed"))

    def test_only_the_normalised_sport_directories_are_staged(self):
        # The NFL directory joined the UFC one on 2026-10-03 (tests/test_nfl_data_ships_and_refreshes.py).
        # Never data/datasvc wholesale and never the raw fetch cache.
        joined = " ".join(line for line in SCRIPT.splitlines() if line.strip().startswith("git add "))
        self.assertEqual(sorted(re.findall(r"data/datasvc\S*", joined)), ["data/datasvc/nfl", "data/datasvc/ufc"])

    def test_the_data_is_not_restored_from_the_cache(self):
        self.assertNotIn("datasvc", WORKFLOW)


if __name__ == "__main__":
    unittest.main()
