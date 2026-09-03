"""Forward evidence must be backed up, and the repo must prove it.

WHY THIS TEST EXISTS
--------------------
On 2026-08-31 a resume audit found that `data/processed/*` was gitignored.
Five days of h2h snapshots and every multi-book board existed only on the
disk of one ephemeral container, which the platform reclaims after a period
of inactivity. Nothing had failed, nothing had errored, and every routine
health check passed -- the data was simply one recycle away from being gone
forever, and a price observed at 19:47 on a particular night cannot be
refetched at any cost the next morning.

The ignore rule was not wrong when it was written: `data/processed/` held
regenerable provider pulls. Forward captures were added to that directory
later and silently inherited an ignore meant for reproducible files. That is
the whole failure -- a correct rule outliving the assumption behind it.

So this test does not check a code path. It checks a PROPERTY of the
repository: every store that holds unbackfillable forward evidence is
tracked by git. A future refactor that moves a store, or a new store added
to an ignored directory, fails here rather than in six months when someone
notices the history is missing.

The companion lesson, recorded in docs/ROADMAP.md, is the other half: a
store that should be growing must be checked for ROWS, not for the absence
of errors. Silence is not success.
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

import tests as tests_pkg

REPO = Path(__file__).resolve().parent.parent

# Every path here holds evidence that cannot be reconstructed after the fact.
# A price, a lineup posting time, or a market's first appearance is evidence
# only because it was recorded at the moment it was true.
FORWARD_EVIDENCE = (
    "data/processed/odds_snapshots.jsonl",
    "data/processed/odds_multibook.jsonl",
    "data/processed/f5_close.jsonl",
    "data/processed/prop_listing.jsonl",
    # Added with the weather/credit-log/prop-price capture streams
    # (docs/COLLECTION_POLICY.md's capture-now amendment): a forecast, a
    # credit balance, or a prop price observed at a moment is exactly as
    # unbackfillable as an odds snapshot, for the same reason.
    "data/processed/weather_forecast.jsonl",
    "data/processed/prop_prices.jsonl",
    "data/processed/credit_log.jsonl",
    # Batter-prop capture (owner decision 3, 2026-09-03): the raw/marker
    # store and the projected price store are exactly as unbackfillable as
    # every other forward store above -- a batter prop observed at a moment
    # cannot be refetched after the fact either.
    "data/processed/batter_props_raw.jsonl",
    "data/processed/batter_props.jsonl",
    # Derivative-markets capture (team_totals/alternates/f5_trio,
    # docs/SGP_PARLAY_CAPTURE.md's proposed next families): the raw/marker
    # store and the projected price store are exactly as unbackfillable as
    # every other forward store above.
    "data/processed/derivative_markets_raw.jsonl",
    "data/processed/derivative_markets.jsonl",
    "data/watch/probables_watch.jsonl",
    "data/watch/lineups_watch.jsonl",
    "data/watch/transactions_watch.jsonl",
    "data/watch/umpires_watch.jsonl",
    # Per-game, per-player box lines (P0-B): the only way a batter prop or a
    # non-strikeout pitcher prop is ever settled. One store per season;
    # 2026 is the year this lane's smoke test writes into.
    "data/processed/boxscores_2026.jsonl",
    # InformationEvent store (packet W6, src/board/events.py): a projected
    # event is deterministically re-derivable from the stores above, but the
    # projection's own ids and dedup state are append-only evidence of what
    # was captured and when, same as everything else in this list.
    "data/processed/information_events.jsonl",
)


def _is_ignored(path: str) -> bool:
    """True when the ignore RULES would exclude this path.

    `--no-index` is load-bearing and was found the hard way. Without it, git
    reports an already-tracked file as "not ignored" no matter what the rules
    say -- tracking wins over .gitignore -- so this check would pass
    vacuously for exactly the stores that already survived, and would only
    notice a mistake once a store had been lost and re-created. With
    `--no-index` the question becomes the one worth asking: if this file
    appeared fresh right now, would the rules keep it out of the repository?

    Exit 0 means ignored, 1 means not. It answers for paths that do not exist
    yet, which is the case that matters most: a store whose first row has not
    been written must already be trackable, or its first day is lost before
    anyone thinks to look.
    """
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", path],
        cwd=REPO, capture_output=True, check=False)
    return result.returncode == 0


# The raw L0 capture store (docs/COLLECTION_POLICY.md, "Raw layer and
# all-books persistence") is not a fixed filename -- one gzip file per API
# call, named by capture time -- so it cannot join FORWARD_EVIDENCE above.
# It is exercised separately below against a representative dated path.
RAW_ODDS_SAMPLE = "data/raw/oddsapi/2026/09/03/20260903T010203Z-abcd1234.jsonl.gz"


class ForwardEvidenceIsTrackedTests(unittest.TestCase):

    def test_no_forward_evidence_store_is_gitignored(self):
        ignored = [path for path in FORWARD_EVIDENCE if _is_ignored(path)]
        self.assertEqual(
            ignored, [],
            "These forward-evidence stores are gitignored, so they exist only "
            "on this container's disk and vanish when it is reclaimed. Add a "
            "negation to .gitignore for each: " + ", ".join(ignored))

    def test_existing_forward_stores_are_actually_tracked(self):
        """Not ignored is necessary but not sufficient -- it must be added too.

        A store can be un-ignored and still untracked, which looks identical
        from the ignore rules and loses the data just the same.
        """
        untracked = []
        for path in FORWARD_EVIDENCE:
            if not (REPO / path).exists():
                continue  # a store with no rows yet cannot be tracked
            result = subprocess.run(
                ["git", "ls-files", "--error-unmatch", path],
                cwd=REPO, capture_output=True, check=False)
            if result.returncode != 0:
                untracked.append(path)
        self.assertEqual(
            untracked, [],
            "These forward-evidence stores exist on disk but are not tracked "
            "by git, so they are not backed up: " + ", ".join(untracked))

    def test_a_raw_odds_capture_would_be_stageable(self):
        """A dated raw-capture path is not swallowed by `data/raw/*`.

        NOTE ON METHOD: `git check-ignore --no-index` gives a false positive
        here -- it reports a fresh file under a directory-tree negation
        (`!data/raw/oddsapi/**`) as ignored when none of the intermediate
        directories exist on disk yet, even though `git add` on the same
        path succeeds (verified by hand against both this rule and the
        pre-existing `!data/archive/historical/**` rule it is modelled on).
        `git add --dry-run` asks the real question -- would this path
        actually be staged -- so that is what this test uses.

        Written through the suite's own unwrapped `open` (`tests._real_open`),
        not the guarded one: `data/raw/oddsapi/` is itself a protected
        directory (tests/__init__.py's `PROTECTED_DIRS`) precisely so a test
        that exercises the real capture code cannot leave a permanent file
        there by accident. This test's file is deliberate, disposable, and
        removed in `finally` below -- the guard exists for the accidental
        case, not this one.
        """
        target = REPO / RAW_ODDS_SAMPLE
        created_dirs = []
        try:
            parent = target.parent
            for candidate in list(parent.parents) + [parent]:
                if not candidate.exists() and candidate != REPO:
                    created_dirs.append(candidate)
            parent.mkdir(parents=True, exist_ok=True)
            with tests_pkg._real_open(target, "wb") as handle:
                handle.write(b"\x1f\x8b")  # gzip magic bytes; content is irrelevant
            result = subprocess.run(
                ["git", "add", "--dry-run", RAW_ODDS_SAMPLE],
                cwd=REPO, capture_output=True, text=True, check=False)
            self.assertEqual(
                result.returncode, 0,
                "a raw odds capture at a realistic dated path could not be "
                f"staged: {result.stderr}")
            self.assertIn("add", result.stdout,
                          f"expected 'add', got: {result.stdout!r} / {result.stderr!r}")
        finally:
            if target.exists():
                target.unlink()
            for directory in sorted(created_dirs, key=lambda p: -len(str(p))):
                try:
                    directory.rmdir()
                except OSError:
                    pass

    def test_the_capture_script_commits_the_store_directories(self):
        """The hourly script is what actually persists the evidence.

        If it stops staging these directories, the stores are tracked but
        their new rows never leave the container -- the same loss, one step
        further along.
        """
        script = (REPO / "scripts" / "forward_capture.sh").read_text()
        self.assertIn("git add", script)
        for directory in ("data/watch", "data/processed"):
            self.assertIn(
                directory, script,
                f"forward_capture.sh no longer stages {directory}, so new "
                "forward evidence would never be pushed anywhere")


if __name__ == "__main__":
    unittest.main()
