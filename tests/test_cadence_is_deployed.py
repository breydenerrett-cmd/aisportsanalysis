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

    def test_the_gate_never_takes_the_capture_down(self):
        """ENRICHMENT, never a blocker: the slate pass is optional, the
        capture is not. A gate that can abort the run would trade a working
        capture cadence for an optional one."""
        gate_region = self.code.split("lineup cadence gate", 1)
        self.assertEqual(len(gate_region), 2, "gate block not found")
        block = gate_region[1].split("GIT_LOCK", 1)[0]
        self.assertNotIn("ESCALATE", block,
                         "a refused or failed optional slate pass must not "
                         "escalate -- the scheduled passes are unaffected")
        self.assertIn("except Exception", block,
                      "the gate must answer rather than raise when a store "
                      "is missing or unreadable")

    def test_the_pass_spends_no_odds_credits(self):
        """`engine slate` reads L1 off disk. If a future edit made this buy
        prices, a 15-minute cadence would multiply the odds bill by ~40x."""
        gate_block = self.code.split("lineup cadence gate", 1)[1]
        block = gate_block.split("GIT_LOCK", 1)[0]
        for spender in ("dense", "capture_extras", "prop_prices",
                        "odds_snapshot"):
            self.assertNotIn(
                spender, block,
                f"the gated block invokes {spender!r}, which spends odds-API "
                "credits on a 15-minute cadence")


if __name__ == "__main__":
    unittest.main()
