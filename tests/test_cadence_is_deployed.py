"""The lineup-cadence gate must live where the scheduler can actually reach it.

WHY THIS FILE EXISTS
---------------------
The gate was first built into `scripts/forward_capture.sh` and into the working
branch's `.github/workflows/forward-capture.yml`. Both are plausible homes.
Neither runs.

The deployment path is narrow and non-obvious:

  * Scheduled workflows fire from the repository's DEFAULT branch
    (`claude/cowork-session-migration-tn3sx2`, an orphan holding five files),
    so cron reads THAT copy of forward-capture.yml. Editing the working
    branch's copy changes nothing on a schedule.
  * That workflow checks out the WORKING branch and invokes
    `scripts/capture_slot.sh`.
  * `capture_slot.sh` is a separate implementation from `forward_capture.sh` --
    its own header says "forward_capture.sh itself is left unchanged and still
    works standalone". It does not call it.

So of the three places the gate could sit, only `scripts/capture_slot.sh`
executes on a schedule. This file pins that, because the failure mode is
silent: the code is committed, the tests are green, the reviewer sees a fix,
and no slate pass ever runs.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# The script the scheduled workflow invokes. If this ever changes, the gate
# has to move with it -- which is the point of naming it here.
SCHEDULED_ENTRYPOINT = REPO / "scripts" / "capture_slot.sh"


class TheGateIsInTheScriptTheSchedulerRunsTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCHEDULED_ENTRYPOINT.exists(),
                        "scripts/capture_slot.sh is missing -- it is the "
                        "script the scheduled workflow invokes")
        self.text = SCHEDULED_ENTRYPOINT.read_text(encoding="utf-8",
                                                   errors="replace")
        # COMMENTS STRIPPED BEFORE MATCHING. The block above documents the
        # cadence at length and names `slate_due` and `engine slate` in prose,
        # so a scan of the raw text passes on the documentation alone. That is
        # not hypothetical: the first version of this file did exactly that,
        # and stayed green when the slate call was deleted outright.
        self.code = "\n".join(
            line for line in self.text.splitlines()
            if not line.lstrip().startswith("#"))

    def test_the_gate_is_called(self):
        """`slate_due` is the whole cadence. If it is not called from here it
        is not called on any schedule."""
        self.assertIn(
            "slate_due", self.code,
            "scripts/capture_slot.sh does not call lineup_store.slate_due. "
            "A gate in forward_capture.sh or in the working branch's "
            "forward-capture.yml runs nowhere: cron reads the DEFAULT "
            "branch's workflow, and that workflow runs capture_slot.sh")

    def test_a_slate_pass_can_actually_fire(self):
        """The gate is worthless if nothing acts on RUN."""
        self.assertIn(
            "engine slate", self.code,
            "capture_slot.sh evaluates the gate but never runs a slate, so a "
            "RUN verdict changes nothing")

    def test_the_ledgers_the_pass_writes_are_staged(self):
        """A gated pass freezes decisions and stakes wagers. If those paths
        are not staged, the commit misses them and the next
        `pull --rebase --autostash` inherits an uncommitted ledger."""
        staged = [line for line in self.code.splitlines()
                  if line.strip().startswith("git add")
                  or (line.strip().startswith("evidence")
                      and "paper_accounts" in line)]
        blob = "\n".join(staged)
        self.assertIn("evidence", blob,
                      "capture_slot.sh does not stage evidence/, so a gated "
                      "slate pass would strand its frozen decisions")
        self.assertIn("data/paper_accounts", blob,
                      "capture_slot.sh does not stage data/paper_accounts, "
                      "so a gated slate pass would strand its wagers")

    def _gate_block(self):
        """The gated pass ONLY: from the gate comment to the `fi` that closes
        its `if`.

        Originally bounded at GIT_LOCK, which was the same span while nothing
        sat between. It is not any more -- the publication audit
        (scripts/publication_audit.py) runs after the gate and deliberately
        escalates, because it reports customer-visible wrongness rather than
        a skipped optional pass. Bounding on the `fi` restores what these
        assertions always meant, rather than widening them to whatever
        happens to precede the git section.
        """
        region = self.code.split("lineup cadence gate", 1)
        self.assertEqual(len(region), 2, "gate block not found")
        lines = region[1].splitlines()
        for i, line in enumerate(lines):
            if line.strip() == "fi":
                return "\n".join(lines[:i + 1])
        self.fail("the gate's `if` block is never closed by an `fi`")

    def test_the_gate_never_takes_the_capture_down(self):
        """ENRICHMENT, never a blocker: the slate pass is optional, the
        capture is not. A gate that can abort the run would trade a working
        capture cadence for an optional one."""
        block = self._gate_block()
        self.assertNotIn("ESCALATE", block,
                         "a refused or failed optional slate pass must not "
                         "escalate -- the scheduled passes are unaffected")
        self.assertIn("except Exception", block,
                      "the gate must answer rather than raise when a store "
                      "is missing or unreadable")

    def test_the_pass_spends_no_odds_credits(self):
        """`engine slate` reads L1 off disk. If a future edit made this buy
        prices, a 15-minute cadence would multiply the odds bill by ~40x."""
        block = self._gate_block()
        for spender in ("dense", "capture_extras", "prop_prices",
                        "odds_snapshot"):
            self.assertNotIn(
                spender, block,
                f"the gated block invokes {spender!r}, which spends odds-API "
                "credits on a 15-minute cadence")


DAILY_LOOP = REPO / "scripts" / "daily_loop.sh"


class TheLearningLoopHasItsInputTests(unittest.TestCase):
    """The same silent-deployment failure, found again on 2026-09-10.

    `docs/PREREG_MECHANISM_CHECKS.md` describes a fully-wired post-game
    classifier. It was wired. It had also never once produced a verdict --
    0 CONFIRMED and 0 REFUTED across 624 reviews -- and the reason was not in
    any of the code the document describes: NO SCRIPT AND NO WORKFLOW IN THIS
    REPO EVER CALLED `gameflow`. The play-by-play store the checks read did
    not exist, so every check honestly returned UNDETERMINED, and the honesty
    of that answer is exactly what made it invisible.

    Reviews are frozen on write and never re-scored, so a night that runs
    settle without the store loses those classifications permanently. That
    makes the ORDER load-bearing, not just the presence.
    """

    def setUp(self):
        self.assertTrue(DAILY_LOOP.exists(), "scripts/daily_loop.sh is missing")
        text = DAILY_LOOP.read_text(encoding="utf-8", errors="replace")
        # Comments stripped for the same reason as above: this block is
        # heavily documented and a raw scan would pass on the prose alone.
        self.code = "\n".join(line for line in text.splitlines()
                              if not line.lstrip().startswith("#"))

    def test_gameflow_is_ingested(self):
        self.assertIn(
            "cli gameflow", self.code,
            "daily_loop.sh never ingests play-by-play, so every mechanism "
            "check tonight freezes as UNDETERMINED and the learning loop "
            "stays at 0 classifications forever")

    def test_gameflow_runs_before_settle(self):
        """Settle writes the reviews the checks land on, and a review is
        frozen on write -- so an ingest that runs after it is too late."""
        flow = self.code.find("cli gameflow")
        settle = self.code.find("engine settle")
        self.assertNotEqual(flow, -1, "no gameflow ingest in daily_loop.sh")
        self.assertNotEqual(settle, -1, "no settle in daily_loop.sh")
        self.assertLess(
            flow, settle,
            "gameflow runs AFTER settle, so tonight's reviews are written "
            "against a store that does not yet hold tonight's games and "
            "freeze UNDETERMINED; append-only means they never get re-scored")

    def test_gameflow_ingests_a_finished_day(self):
        """Today's games have not finished. Ingesting TODAY would store
        partial play-by-play and score mechanisms off half a game."""
        line = next((l for l in self.code.splitlines()
                     if "cli gameflow" in l), "")
        self.assertIn(
            "YESTERDAY", line,
            "gameflow must ingest a completed day; ingesting today scores "
            f"mechanisms off unfinished games (line was: {line.strip()!r})")


CI_SH = REPO / "scripts" / "ci.sh"
REACHABILITY = REPO / "scripts" / "reachability_audit.py"


class TheOrphanDetectorIsNotItselfAnOrphanTests(unittest.TestCase):
    """scripts/reachability_audit.py finds code nothing calls. If nothing
    calls IT, it joins the list it was written to produce."""

    def test_the_audit_exists(self):
        self.assertTrue(REACHABILITY.is_file(),
                        "scripts/reachability_audit.py is missing")

    def test_ci_runs_it(self):
        code = "\n".join(l for l in _read_code(CI_SH).splitlines()
                         if not l.lstrip().startswith("#"))
        self.assertIn(
            "reachability_audit.py", code,
            "scripts/ci.sh does not run the reachability audit, so the check "
            "for code nothing calls is itself code nothing calls")

    def test_it_reads_the_branch_cron_actually_reads(self):
        """The audit's own blind spot, found the day after it shipped.

        GitHub fires a scheduled workflow from the DEFAULT branch's copy of
        the file -- the whole reason this test file exists. The audit walked
        the WORKING tree's .github/workflows, so a command wired only in a
        working-branch workflow looked reachable while cron never touched
        it. The exact failure it was written to catch, inside itself.
        """
        source = _read_code(REACHABILITY)
        self.assertIn("DEFAULT_BRANCH", source,
                      "reachability_audit.py reads the working tree's "
                      "workflows, which cron does not run")
        self.assertIn("git", source,
                      "it does not fetch the default branch's copy")

    def test_it_says_so_when_it_falls_back_to_the_working_tree(self):
        """A shallow clone or a missing remote must produce a LOUD note, not
        a quietly wrong answer -- auditing the wrong branch while claiming
        to audit the right one is worse than not auditing."""
        source = _read_code(REACHABILITY)
        self.assertIn("WORKING TREE", source,
                      "the fallback path does not announce itself")

    def test_it_fails_the_build_rather_than_only_printing(self):
        """ci.sh is `set -euo pipefail`, so a non-zero exit stops the build.
        A checker that only prints is a checker that gets scrolled past."""
        self.assertIn("set -euo pipefail", _read_code(CI_SH))
        source = _read_code(REACHABILITY)
        self.assertIn("return 1", source,
                      "the audit never exits non-zero, so CI would pass with "
                      "orphans reported")


def _read_code(path):
    return path.read_text(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    unittest.main()
