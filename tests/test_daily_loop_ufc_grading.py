"""The daily loop grades yesterday's UFC card from ESPN and commits only the UFC results file.

2026-10-03: `ufc autograde` reads ESPN by default (src/providers/espn_mma_results.py), but
nothing ran it, so grading stayed a manual step. The daily loop now runs it for yesterday,
then settles the card, and stages data/historical/ufc_results.jsonl. That file is not in the
daily loop's actions/cache restore, so the copy on disk is git's own and staging it only adds
rows; the cache-restored stores stay unstaged (tests/test_daily_loop_wiring.py).
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = (REPO / "scripts" / "daily_loop.sh").read_text(encoding="utf-8")
WORKFLOW = (REPO / ".github" / "workflows" / "daily-loop.yml").read_text(encoding="utf-8")


class TheDailyLoopGradesTheUfcCard(unittest.TestCase):
    def test_autograde_then_settle_for_yesterday(self):
        grade = SCRIPT.index('python3 -m src.cli ufc autograde --date "$YESTERDAY"')
        settle = SCRIPT.index('python3 -m src.cli card settle --sport mma --date "$YESTERDAY"')
        self.assertLess(grade, settle)

    def test_both_steps_are_guarded(self):
        for line in SCRIPT.splitlines():
            if "ufc autograde --date" in line or "card settle --sport mma" in line:
                self.assertTrue(line.rstrip().endswith("|| true"), line)

    def test_the_results_file_is_staged_and_nothing_else_from_historical(self):
        add_lines = [l for l in SCRIPT.splitlines() if l.strip().startswith("git add ")]
        joined = " ".join(add_lines)
        self.assertIn("data/historical/ufc_results.jsonl", joined)
        historical = re.findall(r"data/historical/\S*", joined)
        self.assertEqual(historical, ["data/historical/ufc_results.jsonl"])

    def test_the_results_file_is_not_restored_from_the_cache(self):
        self.assertNotIn("ufc_results", WORKFLOW)


if __name__ == "__main__":
    unittest.main()
