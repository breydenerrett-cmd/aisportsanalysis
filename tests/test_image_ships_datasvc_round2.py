"""Round 2 of the data service adds three stores that must NOT grow the web image or the repository.

* play-by-play (`data/datasvc/espn/<league>/pbp_*`, ~43-57 MB a season) lives inside a directory the image copies, so
  `.dockerignore` re-excludes it after the admission;
* the MLB statsapi box-score cache (`data/datasvc/mlb/`, ~100 MB a season) and the football-data.co.uk store
  (`data/datasvc/footballdata/`, private-use data in a public repository) sit under `data/datasvc/*`, which the image
  excludes unless a directory is named;
* all three are git-ignored (a local, rebuildable cache), and the tracked ESPN files still ship.
"""

import re
import unittest
from pathlib import Path

from tests.test_image_ships_ufc_data import _rules, excluded_from_build_context

ROOT = Path(__file__).resolve().parents[1]
RULES = _rules(ROOT / ".dockerignore")
GITIGNORE = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def excluded(path):
    return excluded_from_build_context(path, RULES)


class PlayByPlayStaysOutOfTheImage(unittest.TestCase):
    def test_the_tracked_espn_files_still_ship(self):
        for name in ("MANIFEST.json", "games_2027.jsonl", "team_games_2027.jsonl", "player_games_2027.jsonl", "teams.jsonl"):
            self.assertFalse(excluded(f"data/datasvc/espn/nba/{name}"), name)
        self.assertFalse(excluded("data/datasvc/espn/epl/standings_2026.jsonl"))

    def test_play_by_play_files_are_excluded(self):
        for league in ("nba", "nhl", "ncaaf", "wnba"):
            for name in ("pbp_2027.jsonl.gz", "pbp_2027.index.jsonl"):
                self.assertTrue(excluded(f"data/datasvc/espn/{league}/{name}"), f"{league}/{name}")

    def test_the_image_still_copies_the_espn_directory(self):
        dockerfile = (ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
        self.assertRegex(dockerfile, re.compile(r"^COPY data/datasvc/espn/ data/datasvc/espn/\s*$", re.M))


class OtherNewStoresAreNotShipped(unittest.TestCase):
    def test_mlb_box_and_football_data_are_outside_the_build_context(self):
        for path in ("data/datasvc/mlb/games_2026.jsonl", "data/datasvc/mlb/player_games_2026.jsonl",
                     "data/datasvc/footballdata/epl/matches_2025.jsonl", "data/datasvc/footballdata/epl/MANIFEST.json"):
            self.assertTrue(excluded(path), path)

    def test_the_dockerfile_copies_neither(self):
        dockerfile = (ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
        self.assertNotIn("datasvc/mlb", dockerfile)
        self.assertNotIn("datasvc/footballdata", dockerfile)


class TheCachesAreGitIgnored(unittest.TestCase):
    def test_patterns_present(self):
        for pattern in ("data/datasvc/espn/*/pbp_*", "data/datasvc/mlb/", "data/datasvc/footballdata/", "data/datasvc/raw/"):
            self.assertIn(pattern, GITIGNORE, pattern)


if __name__ == "__main__":
    unittest.main()
