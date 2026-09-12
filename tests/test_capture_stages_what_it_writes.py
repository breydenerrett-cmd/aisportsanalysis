"""Every store the capture WRITES must be a store the capture STAGES.

THE DEFECT THIS EXISTS FOR
--------------------------
`scripts/forward_capture.sh` has called `lineup_store.build` every fifteen
minutes since 2026-09-08. It writes `data/historical/lineups.jsonl`. The
script's `git add` line named `data/watch`, `data/processed`,
`data/raw/oddsapi`, `evidence` and `data/paper_accounts` -- and not
`data/historical`.

So every run rebuilt the store on the runner, and every run threw it away.
Measured 2026-09-11: `data/watch/lineups_watch.jsonl` was current to the hour
with 25 games fetched that day, while `data/historical/lineups.jsonl` had not
moved since 2026-09-08 and carried exactly ONE commit in its entire history.

It is not a research artefact. `api/games.py` and `src/pipeline/enrichment.py`
read it for tonight's batting orders, so the product had been pricing
three-day-old lineups while the block that exists to fix lineup cadence
reported success ninety-six times a day.

Nothing was red. The write succeeded, the build reported success, the commit
succeeded -- it just never contained the file. This is the ninth instance in
this repo of code that is correct, tested, and that nothing preserves, and a
green suite will not catch the tenth either unless something asks this
question directly.

Pure text analysis: never runs the script, never needs bash.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAPTURE = ROOT / "scripts" / "forward_capture.sh"

# Builders the capture script invokes, and the store each one writes.
# Resolved from the modules themselves so a store that MOVES cannot leave a
# stale literal here passing while the real file goes unstaged.
WRITERS = (
    ("src.pipeline.lineup_store", "DEFAULT_STORE"),
    ("src.pipeline.matchup_history", "DEFAULT_STORE"),
    ("src.pipeline.matchup_history", "DEFAULT_PAIR_CACHE"),
)


def _staged_paths(text: str) -> list:
    """Every path named on a `git add` line in the script."""
    staged = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("git add "):
            continue
        body = stripped[len("git add "):]
        body = re.split(r"\s+2>|\s+\|\||\s+&&", body)[0]
        staged.extend(part for part in body.split() if not part.startswith("-"))
    return staged


def _covered(target: str, staged) -> bool:
    """Is `target` staged, either by name or by an ancestor directory?"""
    target = target.replace("\\", "/").lstrip("./")
    for path in staged:
        path = path.replace("\\", "/").lstrip("./")
        if target == path or target.startswith(path.rstrip("/") + "/"):
            return True
    return False


class CaptureStagesEveryStoreItWrites(unittest.TestCase):
    def setUp(self):
        self.text = CAPTURE.read_text(encoding="utf-8")
        self.staged = _staged_paths(self.text)

    def test_the_script_stages_something(self):
        self.assertTrue(self.staged, "no `git add` line found at all")

    def test_every_builder_the_script_calls_has_its_store_staged(self):
        import importlib

        for module_name, attribute in WRITERS:
            module = importlib.import_module(module_name)
            store = getattr(module, attribute)
            relative = str(store).replace("\\", "/")
            marker = module_name.rsplit(".", 1)[-1]
            # Only demand staging for builders this script actually invokes.
            if marker not in self.text:
                continue
            index = relative.find("data/")
            self.assertGreater(index, -1,
                               f"{module_name}.{attribute} is not under data/")
            relative = relative[index:]
            self.assertTrue(
                _covered(relative, self.staged),
                f"{module_name}.{attribute} writes {relative}, which "
                f"forward_capture.sh never stages -- every run will rebuild "
                f"it and throw it away. Staged: {self.staged}")

    def test_data_historical_is_never_staged_wholesale(self):
        """Named files only.

        `data/historical` also holds mlb_results.csv and the arsenals tree.
        Staging it bare would put multi-megabyte churn into a commit that
        runs ninety-six times a day.
        """
        for path in self.staged:
            self.assertNotIn(
                path.rstrip("/"), ("data/historical", "data", "."),
                f"{path!r} is staged wholesale by a 15-minute job")

    def test_customer_state_is_never_staged_by_an_automated_pass(self):
        """data/app holds auth and customer state and must never be
        committed by a robot."""
        for path in self.staged:
            self.assertFalse(
                path.replace("\\", "/").rstrip("/").startswith("data/app"),
                f"{path!r} would commit customer state")


if __name__ == "__main__":
    unittest.main()
