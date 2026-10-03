"""The deployed image carries the UFC data layer that request-time code reads.

2026-10-03: the fight-night page (`api/ufc_fights.py`) and the data API (`api/datasvc.py`)
read the normalised UFC files from `src.datasvc.ufc.store.DEFAULT_DIR`, but `.dockerignore`
dropped everything under `data/` it did not name and `deploy/Dockerfile` copied none of it,
so production would have answered every UFC request with "data unavailable" while every
local test passed against the repo copy. These tests pin the copy, the build context, and
the raw fetch cache staying out of both git and the image.
"""
import re
import unittest
from pathlib import Path

from src.datasvc.ufc import store as ufc_store

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")


def _rules(path: Path) -> list:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def _regex(pattern: str) -> "re.Pattern":
    """A .dockerignore pattern as a regex: `*` and `?` stop at a slash, `**` does not."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def excluded_from_build_context(path: str, rules: list) -> bool:
    """Docker's rule: the LAST pattern matching the path or one of its parent directories wins."""
    parts = path.split("/")
    excluded = False
    for rule in rules:
        negated = rule.startswith("!")
        pattern = _regex((rule[1:] if negated else rule).strip("/"))
        if any(pattern.match("/".join(parts[:n])) for n in range(1, len(parts) + 1)):
            excluded = not negated
    return excluded


class TheImageCopiesTheUfcData(unittest.TestCase):
    def test_the_ufc_directory_is_copied_to_where_the_store_reads_it(self):
        self.assertRegex(DOCKERFILE, re.compile(r"^COPY data/datasvc/ufc/ data/datasvc/ufc/\s*$", re.M))
        self.assertEqual(ufc_store.DEFAULT_DIR.relative_to(ROOT).as_posix(), "data/datasvc/ufc")

    def test_the_copy_sits_before_the_display_refresh_step(self):
        # The refresh step's own comment promises it runs after the last COPY.
        copy_at = DOCKERFILE.index("COPY data/datasvc/ufc/ data/datasvc/ufc/")
        refresh_at = DOCKERFILE.index("python -m src.pipeline.display_refresh")
        self.assertLess(copy_at, refresh_at)

    def test_nothing_is_copied_from_the_raw_fetch_cache(self):
        copies = [line.split() for line in DOCKERFILE.splitlines() if line.startswith("COPY ")]
        wholesale = [c for c in copies if "datasvc/raw" in " ".join(c) or c[1] in (".", "data/", "data/datasvc/")]
        self.assertEqual(wholesale, [])


class TheBuildContextAdmitsIt(unittest.TestCase):
    RULES = _rules(ROOT / ".dockerignore")

    def excluded(self, path):
        return excluded_from_build_context(path, self.RULES)

    def test_every_dataset_file_and_the_manifest_are_sent(self):
        for filename in list(ufc_store.FILES.values()) + ["MANIFEST.json"]:
            self.assertFalse(self.excluded(f"data/datasvc/ufc/{filename}"), filename)

    def test_the_raw_fetch_cache_is_not_sent(self):
        self.assertTrue(self.excluded("data/datasvc/raw/sports.core.api.espn.com/abc.json"))
        self.assertTrue(self.excluded("data/datasvc/raw"))

    def test_the_rest_of_data_is_unchanged(self):
        # Spot checks of the rules that were there before: still out, still in.
        for path in ("data/raw/x.json", "data/historical/statcast/2026.csv", "data/research/sweeps/a.json",
                     "data/datasvc/nba/games.jsonl"):
            self.assertTrue(self.excluded(path), path)
        for path in ("data/historical/mlb_results.csv", "data/research/alpha_registry.jsonl",
                     "data/processed/odds_snapshots.jsonl", "config/example_accounts.json"):
            self.assertFalse(self.excluded(path), path)

    def test_the_matcher_follows_last_match_wins(self):
        rules = ["data/*", "!data/keep/", "data/keep/*", "!data/keep/this/"]
        self.assertTrue(excluded_from_build_context("data/other/file", rules))
        self.assertTrue(excluded_from_build_context("data/keep/that/file", rules))
        self.assertFalse(excluded_from_build_context("data/keep/this/file", rules))
        self.assertFalse(excluded_from_build_context("src/file", rules))


class GitKeepsTheRawCacheOut(unittest.TestCase):
    def test_the_raw_cache_is_ignored_and_the_ufc_files_are_not(self):
        rules = _rules(ROOT / ".gitignore")
        self.assertIn("data/datasvc/raw/", rules)
        self.assertFalse([r for r in rules if r.rstrip("/") in ("data/datasvc", "data/datasvc/ufc", "data/datasvc/*")])


if __name__ == "__main__":
    unittest.main()
