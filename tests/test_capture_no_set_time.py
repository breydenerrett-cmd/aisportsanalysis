"""No set time for the first look at a slate (owner, 2026-09-14).

On 2026-09-14 the card published at 15:12Z on the previous night's 23:19Z
board, the engine slate refused ("no price capture observed for 2026-09-14
at all"), and no player prop had been captured, because every capture was
pinned to a window near first pitch and the card was published once, at
15:40Z. The owner: "we dont need a set time for analysis on props or MLs or
all other bets ... analysis needs to be ran pre emtively before any games".

These tests hold the four pieces that remove the set time: an hourly full-
slate board, a baseline prop window that opens a day out, an on-demand
switch for a hand-dispatched run, and a card republished every slot.
"""

from __future__ import annotations

import datetime as dt
import re
import unittest
from pathlib import Path

from src.pipeline import batter_props

REPO = Path(__file__).resolve().parents[1]
SLOT = (REPO / "scripts" / "capture_slot.sh").read_text(encoding="utf-8")
WORKFLOW = (REPO / ".github" / "workflows" / "forward-capture.yml").read_text(encoding="utf-8")

NOW = dt.datetime(2026, 9, 14, 15, 45, tzinfo=dt.timezone.utc)


def _event(minutes_out):
    commence = NOW + dt.timedelta(minutes=minutes_out)
    return {"id": "e1", "commence_time": commence.isoformat().replace("+00:00", "Z")}


def _code(text):
    return "\n".join(line for line in text.splitlines()
                     if not line.strip().startswith("#"))


class TheBoardIsNeverMoreThanAnHourOld(unittest.TestCase):
    def test_dense_is_called_with_a_window(self):
        self.assertIn('dense --captures 1 --interval 0 --window "$DENSE_WINDOW"', _code(SLOT))

    def test_the_first_slot_of_each_hour_or_a_manual_run_widens_it_to_a_day(self):
        code = _code(SLOT)
        self.assertIn("DENSE_WINDOW=180", code)
        self.assertIn("DENSE_WINDOW=1440", code)
        self.assertRegex(code, r'\[ "\$CAPTURE_NOW" = "1" \] \|\| \[ .*date -u \+%M.* -lt 15 \]')


class PropsHaveNoSetTime(unittest.TestCase):
    def test_a_night_game_is_baseline_due_in_the_morning(self):
        """22:40Z first pitch, 15:45Z now: 415 minutes out. Also true under
        the old 420 edge, so the test that matters is the next one."""
        self.assertEqual(batter_props._capture_phase(_event(415), NOW), "baseline")

    def test_a_game_twenty_hours_out_is_baseline_due(self):
        """Fails on the 5-7h band: a game this far out had no prop capture
        at all until seven hours before first pitch."""
        self.assertEqual(batter_props._capture_phase(_event(20 * 60), NOW), "baseline")

    def test_the_near_edge_still_keeps_baseline_pre_lineup(self):
        """The V7 slot study reads `baseline` as pre-lineup; the near edge
        must not move."""
        self.assertEqual(batter_props.BASELINE_LEAD_MIN_MINUTES, 300)
        self.assertIsNone(batter_props._capture_phase(_event(200), NOW))

    def test_on_demand_takes_the_dead_zone_under_its_own_label(self):
        self.assertEqual(
            batter_props._capture_phase(_event(200), NOW, on_demand=True),
            batter_props.PHASE_ON_DEMAND)
        self.assertIsNone(
            batter_props._capture_phase(_event(-5), NOW, on_demand=True),
            "a started game is never captured, on demand or not")
        self.assertEqual(batter_props._capture_phase(_event(90), NOW, on_demand=True), "gate")

    def test_the_switch_reads_capture_now(self):
        self.assertTrue(batter_props._on_demand({"CAPTURE_NOW": "1"}))
        self.assertFalse(batter_props._on_demand({}))


class AHandDispatchedRunIsOnDemand(unittest.TestCase):
    def test_the_workflow_sets_capture_now_only_on_dispatch(self):
        # 2026-09-14 (cadence): a chained dispatch is also a workflow_dispatch
        # event, so the event name alone would mark every chained slot
        # on-demand; the capture_now input now carries hand vs chain.
        self.assertIn("workflow_dispatch", WORKFLOW)
        self.assertIn("CAPTURE_NOW: ${{ github.event_name == 'workflow_dispatch' "
                      "&& inputs.capture_now == '1' && '1' || '' }}",
                      WORKFLOW)

    def test_the_slot_exports_it_to_the_extras_pass(self):
        code = _code(SLOT)
        self.assertIn("export CAPTURE_NOW", code)
        self.assertLess(code.index("export CAPTURE_NOW"), code.index("capture_extras.sh"))


class TheCardIsRepublishedEverySlot(unittest.TestCase):
    def test_card_publish_runs_in_the_slot_after_the_captures(self):
        code = _code(SLOT)
        self.assertIn('card publish --date "$SLATE_DATE"', code)
        self.assertLess(code.index("capture_extras.sh"), code.index("card publish"))

    def test_the_event_map_is_built_before_the_publish_that_joins_through_it(self):
        """2026-09-14: the map was built only by the daily loop, which had
        failed two days running, so no prop could join its game."""
        code = _code(SLOT)
        self.assertIn('src.cli gamekey --date "$SLATE_DATE"', code)
        self.assertLess(code.index("src.cli gamekey"), code.index("card publish --date"))

    def test_it_publishes_for_the_slate_date_not_the_utc_date(self):
        self.assertIn("SLATE_DATE=$(TZ=America/New_York date +%Y-%m-%d)", _code(SLOT))

    def test_it_never_fails_the_slot(self):
        line = [ln for ln in _code(SLOT).splitlines() if "card publish --date" in ln][0]
        self.assertTrue(line.rstrip().endswith("|| true"), line)

    def test_the_ledger_it_writes_is_staged(self):
        # Since 2026-09-19 the slot stages its paths through an existence-
        # filtered loop (one missing path used to make git refuse the whole
        # add); evidence/ must still be one of the paths that loop stages.
        code = _code(SLOT)
        staging = code[code.index("STAGE_PATHS="):]
        loop = staging[staging.index("for p in"):staging.index("done")]
        self.assertTrue(re.search(r"\bevidence\b", loop),
                        "evidence/ (the card ledger) is not staged by the slot's commit")
        self.assertLess(code.index("card publish"), code.index("STAGE_PATHS="))


# ---------------------------------------------------------------------------
# THE SELF-CHAINING CADENCE (2026-09-14). GitHub's */15 cron fired every 2-5
# hours, so a slot every 15 minutes existed only while someone dispatched runs
# by hand. Each forward-capture run now dispatches the next one
# (docs/CAPTURE_EXTERNALIZATION.md, "Self-chaining cadence").
#
# REVISED 2026-09-14 after review. The first version slept inside the shared
# concurrency group and stopped chaining whenever a rival waited: the chain
# died at every afternoon-slate, and the group was held so constantly that the
# rival went pending where an unchecked cron-copy run could cancel it. The
# wait and the dispatch now run in a `pace` job outside the group; the slot
# joins the group only through a gate. The behavioural tests run the real
# script's --space-only / --chain-only / --gate-only modes against a fake `gh`
# and a fake `sleep`; every mode exits before the slot, so nothing here
# touches the network, git, or an odds credit.

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

SLOT_PATH = REPO / "scripts" / "capture_slot.sh"
WORKING_BRANCH = "claude/sports-betting-analysis-review-g1o0co"
DEFAULT_BRANCH = "claude/cowork-session-migration-tn3sx2"


def _bash():
    """A POSIX bash. On Windows `bash` on PATH is often the WSL shim, which
    cannot see Windows paths; Git Bash is preferred there."""
    candidates = [os.environ.get("LINEHOUND_BASH")]
    if os.name == "nt":
        candidates += [r"C:\Program Files\Git\bin\bash.exe",
                       r"C:\Program Files\Git\usr\bin\bash.exe"]
    candidates.append(shutil.which("bash"))
    for path in candidates:
        if not path or not os.path.exists(path):
            continue
        low = path.lower()
        if os.name == "nt" and ("windowsapps" in low or "system32" in low):
            continue
        return path
    return None


BASH = _bash()

# `run list` answers FAKE_GH_RUNS, or FAKE_GH_RUNS_LATER once it has been
# called more than FAKE_GH_LATER_AFTER times (a rival that starts running).
FAKE_GH = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$FAKE_GH_LOG"
if [ "$1 $2" = "run list" ]; then
    if [ -n "${FAKE_GH_FAIL_LIST:-}" ]; then exit 1; fi
    calls=$(grep -c '^run list' "$FAKE_GH_LOG")
    if [ -n "${FAKE_GH_LATER_AFTER:-}" ] && [ "$calls" -gt "$FAKE_GH_LATER_AFTER" ]; then
        printf '%s' "$FAKE_GH_RUNS_LATER"
    else
        printf '%s' "$FAKE_GH_RUNS"
    fi
    exit 0
fi
if [ "$1 $2" = "workflow run" ]; then exit "${FAKE_GH_DISPATCH_RC:-0}"; fi
exit 0
"""

FAKE_SLEEP = """#!/usr/bin/env bash
printf '%s\\n' "$1" >> "$FAKE_SLEEP_LOG"
"""


def _iso(seconds_from_now):
    moment = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=seconds_from_now)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(name, status, branch=WORKING_BRANCH, event="workflow_dispatch", run_id=1):
    return {"databaseId": run_id, "workflowName": name, "status": status,
            "headBranch": branch, "event": event}


@unittest.skipUnless(BASH, "no POSIX bash available")
class _ChainHarness(unittest.TestCase):
    SELF_RUN_ID = "500"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chain_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name, body in (("gh", FAKE_GH), ("fakesleep", FAKE_SLEEP)):
            path = self.tmp / name
            path.write_bytes(body.encode("utf-8"))
            path.chmod(0o755)
        self.gh_log = self.tmp / "gh.log"
        self.sleep_log = self.tmp / "sleep.log"
        self.output = self.tmp / "github_output"
        self.reset()

    def reset(self):
        for path in (self.gh_log, self.sleep_log, self.output):
            path.write_text("", encoding="utf-8")

    def invoke(self, mode, runs=(), later=None, **env):
        base = {k: v for k, v in os.environ.items()
                if not k.startswith(("GITHUB_", "GH_", "CAPTURE_", "CHAIN_",
                                     "PREV_SLOT", "SPACING_", "SLOT_START"))}
        base.update({
            "PATH": str(self.tmp) + os.pathsep + os.environ.get("PATH", ""),
            "GH_TOKEN": "fake-token-for-tests",
            "CHAIN_PY": sys.executable,
            "CHAIN_SLEEP": (self.tmp / "fakesleep").as_posix(),
            "CHAIN_SELF_RUN_ID": self.SELF_RUN_ID,
            "FAKE_GH_LOG": self.gh_log.as_posix(),
            "FAKE_SLEEP_LOG": self.sleep_log.as_posix(),
            "FAKE_GH_RUNS": json.dumps(list(runs)),
            "GITHUB_OUTPUT": self.output.as_posix(),
            "CHAIN_FIRST_PITCHES": _iso(2 * 3600),
        })
        if later is not None:
            after, later_runs = later
            base["FAKE_GH_LATER_AFTER"] = str(after)
            base["FAKE_GH_RUNS_LATER"] = json.dumps(list(later_runs))
        base.update(env)
        return subprocess.run([BASH, SLOT_PATH.as_posix(), mode], capture_output=True,
                              text=True, env=base, timeout=120, cwd=str(REPO))

    def dispatches(self):
        return [line for line in self.gh_log.read_text(encoding="utf-8").splitlines()
                if line.startswith("workflow run")]

    def queue_reads(self):
        return [line for line in self.gh_log.read_text(encoding="utf-8").splitlines()
                if line.startswith("run list")]

    def sleeps(self):
        return [int(x) for x in self.sleep_log.read_text(encoding="utf-8").split()]

    def outputs(self):
        pairs = (line.split("=", 1) for line in
                 self.output.read_text(encoding="utf-8").splitlines() if "=" in line)
        return dict(pairs)


class TheChainDispatchesTheNextSlot(_ChainHarness):
    def test_an_empty_queue_dispatches_exactly_one_chained_slot(self):
        """Fails without the chain: nothing dispatched the next slot, so the
        cadence was whatever GitHub's cron felt like (every 2-5 hours)."""
        r = self.invoke("--chain-only", SLOT_START_EPOCH="1789400000")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        sent = self.dispatches()
        self.assertEqual(len(sent), 1, sent)
        self.assertIn("forward-capture.yml --ref " + WORKING_BRANCH, sent[0])
        self.assertIn("capture_now=0", sent[0])
        self.assertIn("prev_slot_start=1789400000", sent[0])
        self.assertIn("spacing_minutes=13", sent[0])

    def test_a_waiting_rival_does_not_end_the_chain(self):
        """Review finding 2: the first version did not dispatch while a
        daily-loop/afternoon-slate waited, and nothing re-dispatched after it,
        so the chain died at every rival until a cron firing hours later --
        across today's first pitches. The dispatched run cannot cancel the
        rival (its slot joins the group only through --gate-only), so the
        chain dispatches. Verified failing against the pre-revision script."""
        for rival in (_run("afternoon-slate", "pending", event="schedule"),
                      _run("daily-loop", "queued", event="schedule")):
            with self.subTest(rival=rival["workflowName"]):
                self.reset()
                r = self.invoke("--chain-only", runs=[rival])
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(len(self.dispatches()), 1, r.stdout)

    def test_a_newer_live_run_of_this_branch_carries_the_chain(self):
        """A hand dispatch made while this run slept is newer; it dispatches
        its own successor, so this one must not, or the chains multiply."""
        for status in ("queued", "in_progress"):
            with self.subTest(status=status):
                self.reset()
                r = self.invoke("--chain-only",
                                runs=[_run("forward-capture", status, run_id=900)])
                self.assertEqual(self.dispatches(), [], r.stdout)
                self.assertEqual(r.returncode, 0)

    def test_an_older_live_run_of_this_branch_does_not_stop_the_newest(self):
        r = self.invoke("--chain-only", runs=[_run("forward-capture", "pending", run_id=100)])
        self.assertEqual(len(self.dispatches()), 1, r.stdout)

    def test_two_live_chains_collapse_to_one(self):
        """(d) Chains cannot multiply: of two live runs each seeing the other,
        exactly one (the newer) dispatches."""
        older, newer = _run("forward-capture", "in_progress", run_id=100), \
            _run("forward-capture", "in_progress", run_id=200)
        self.invoke("--chain-only", runs=[older, newer], CHAIN_SELF_RUN_ID="100")
        from_older = len(self.dispatches())
        self.reset()
        self.invoke("--chain-only", runs=[older, newer], CHAIN_SELF_RUN_ID="200")
        from_newer = len(self.dispatches())
        self.assertEqual((from_older, from_newer), (0, 1))

    def test_the_cron_copy_only_restarts_a_dead_chain(self):
        """The default branch's cron copy chains from the script's exit trap
        as a RESTARTER: any live run of this branch already carries the chain,
        older or newer."""
        live = [_run("forward-capture", "in_progress", run_id=100)]
        self.invoke("--chain-only", runs=live, CHAIN_RESTARTER="1", CHAIN_SELF_RUN_ID="900")
        self.assertEqual(self.dispatches(), [])
        self.reset()
        self.invoke("--chain-only", CHAIN_RESTARTER="1", CHAIN_SELF_RUN_ID="900")
        self.assertEqual(len(self.dispatches()), 1)

    def test_a_waiting_cron_copy_does_not_stop_the_chain(self):
        runs = [_run("forward-capture", "pending", branch=DEFAULT_BRANCH,
                     event="schedule", run_id=900)]
        self.invoke("--chain-only", runs=runs)
        self.assertEqual(len(self.dispatches()), 1)

    def test_an_unreadable_queue_still_dispatches(self):
        """Not dispatching costs hours (until cron); dispatching blind costs
        at most a duplicate chain that the next readable check collapses, and
        cannot cancel anything."""
        r = self.invoke("--chain-only", FAKE_GH_FAIL_LIST="1")
        self.assertEqual(len(self.dispatches()), 1, r.stdout)
        self.assertEqual(r.returncode, 0)

    def test_a_refused_dispatch_fails_the_step(self):
        r = self.invoke("--chain-only", FAKE_GH_DISPATCH_RC="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("BROKEN", r.stdout)

    def test_quiet_hours_space_the_chain_hourly(self):
        """No first pitch within 26 hours -> hourly, not 96 slots of nothing."""
        for pitches in ("", _iso(30 * 3600), _iso(-3600)):
            with self.subTest(first_pitches=pitches):
                self.reset()
                self.invoke("--chain-only", CHAIN_FIRST_PITCHES=pitches)
                sent = self.dispatches()
                self.assertEqual(len(sent), 1)
                self.assertIn("spacing_minutes=60", sent[0])

    def test_an_unreadable_schedule_keeps_the_game_day_cadence(self):
        self.invoke("--chain-only", CHAIN_FIRST_PITCHES="not-a-time")
        self.assertIn("spacing_minutes=13", self.dispatches()[0])

    def test_the_kill_switch_stops_the_chain(self):
        r = self.invoke("--chain-only", CAPTURE_CHAIN="off")
        self.assertEqual(self.dispatches(), [])
        self.assertEqual(r.returncode, 0)

    def test_the_token_is_never_printed(self):
        r = self.invoke("--chain-only", GH_TOKEN="ghs_SECRETVALUE123")
        self.assertNotIn("SECRETVALUE123", r.stdout + r.stderr)


class AChainedSlotIsSpaced(_ChainHarness):
    def test_a_hand_or_cron_run_does_not_wait(self):
        r = self.invoke("--space-only")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.sleeps(), [])
        self.assertTrue(self.outputs().get("slot_start", "").isdigit())

    def test_a_chained_run_waits_out_the_rest_of_13_minutes(self):
        """Fails without spacing: a chained run would start the moment the
        previous one finished, a slot every ~2 minutes."""
        prev = int(time.time()) - 100
        self.invoke("--space-only", PREV_SLOT_START=str(prev), SPACING_MINUTES="13")
        waited = self.sleeps()
        self.assertTrue(675 <= sum(waited) <= 680, waited)
        self.assertTrue(all(0 < s <= 60 for s in waited), waited)

    def test_the_wait_is_bounded_even_for_a_start_in_the_future(self):
        future = int(time.time()) + 100000
        self.invoke("--space-only", PREV_SLOT_START=str(future), SPACING_MINUTES="13")
        self.assertEqual(sum(self.sleeps()), 13 * 60)
        self.reset()
        self.invoke("--space-only", PREV_SLOT_START=str(future), SPACING_MINUTES="999")
        self.assertEqual(sum(self.sleeps()), 60 * 60)

    def test_spacing_below_13_minutes_is_raised_to_13(self):
        now = int(time.time())
        self.invoke("--space-only", PREV_SLOT_START=str(now), SPACING_MINUTES="1")
        self.assertTrue(770 <= sum(self.sleeps()) <= 780, self.sleeps())

    def test_a_slot_long_past_starts_now(self):
        self.invoke("--space-only", PREV_SLOT_START=str(int(time.time()) - 5000),
                    SPACING_MINUTES="13")
        self.assertEqual(self.sleeps(), [])

    def test_the_wait_neither_yields_nor_skips_the_slot(self):
        """Review finding 2/3: the old wait yielded (skipped its slot and
        stopped the chain) when a rival queued. The wait now holds no group,
        so a rival is irrelevant to it: it sleeps the full spacing and never
        reads the queue. Verified failing against the pre-revision script,
        which slept zero seconds and wrote yielded=true here."""
        r = self.invoke("--space-only", runs=[_run("afternoon-slate", "pending", event="schedule")],
                        PREV_SLOT_START=str(int(time.time())), SPACING_MINUTES="13")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(770 <= sum(self.sleeps()) <= 780, self.sleeps())
        self.assertNotEqual(self.outputs().get("yielded"), "true")
        self.assertEqual(self.queue_reads(), [])


class TheSlotJoinsTheGroupOnlyWhenNoRivalWaits(_ChainHarness):
    """(a) GitHub cancels a PENDING entry in a concurrency group when a newer
    one queues. The gate is the only door into the group for a chained or hand
    dispatched slot of this branch."""

    def test_an_empty_group_is_joined_at_once(self):
        r = self.invoke("--gate-only")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.outputs().get("yielded"), "false")
        self.assertEqual(self.sleeps(), [])

    def test_a_waiting_rival_is_let_in_first(self):
        """afternoon-slate pending for three reads, then running: the slot
        waits three minutes, then joins behind it -- neither cancelled."""
        waiting = [_run("afternoon-slate", "pending", event="schedule")]
        running = [_run("afternoon-slate", "in_progress", event="schedule")]
        r = self.invoke("--gate-only", runs=waiting, later=(3, running))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.sleeps(), [60, 60, 60])
        self.assertEqual(self.outputs().get("yielded"), "false")

    def test_queued_and_pending_runs_of_both_rivals_block(self):
        for rival in (_run("daily-loop", "queued", event="schedule"),
                      _run("daily-loop", "pending", event="schedule"),
                      _run("afternoon-slate", "queued", event="workflow_dispatch"),
                      _run("afternoon-slate", "waiting", event="schedule")):
            with self.subTest(rival=rival):
                self.reset()
                self.invoke("--gate-only", runs=[rival], later=(1, []))
                self.assertEqual(self.sleeps(), [60])

    def test_a_rival_that_never_starts_costs_the_slot_not_the_rival(self):
        r = self.invoke("--gate-only", runs=[_run("daily-loop", "pending", event="schedule")])
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.outputs().get("yielded"), "true")
        self.assertEqual(sum(self.sleeps()), 30 * 60)

    def test_running_rivals_and_forward_capture_runs_do_not_block(self):
        runs = [_run("daily-loop", "in_progress", event="schedule"),
                _run("forward-capture", "pending", branch=DEFAULT_BRANCH, event="schedule"),
                _run("forward-capture", "queued", run_id=900)]
        self.invoke("--gate-only", runs=runs)
        self.assertEqual(self.outputs().get("yielded"), "false")

    def test_an_unreadable_queue_never_joins_and_goes_red(self):
        r = self.invoke("--gate-only", FAKE_GH_FAIL_LIST="1")
        self.assertEqual(self.outputs().get("yielded"), "true")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("BROKEN", r.stdout)


def _job(workflow, name):
    """The text of one job under `jobs:`, comments dropped."""
    code = _code(workflow)
    body = code[code.index("\njobs:\n") + len("\njobs:\n"):]
    match = re.search(r"^  %s:\n" % re.escape(name), body, re.M)
    if not match:
        raise AssertionError("no job named %r" % name)
    rest = body[match.end():]
    end = re.search(r"^  [\w-]+:\n", rest, re.M)
    return rest[:end.start()] if end else rest


def _steps(job_text):
    """Step blocks of one job, in file order."""
    body = job_text[job_text.index("    steps:\n") + len("    steps:\n"):]
    blocks, current = [], []
    for line in body.splitlines():
        if line.startswith("      - "):
            if current:
                blocks.append("\n".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def _step(job_text, name):
    matches = [b for b in _steps(job_text) if ("name: " + name) in b]
    if len(matches) != 1:
        raise AssertionError("expected one step named %r, found %d" % (name, len(matches)))
    return matches[0]


class TheWorkflowWiresTheChain(unittest.TestCase):
    def setUp(self):
        self.pace = _job(WORKFLOW, "pace")
        self.capture = _job(WORKFLOW, "capture")

    def test_dispatch_inputs_default_a_hand_run_to_capture_now(self):
        code = _code(WORKFLOW)
        self.assertRegex(code, r"workflow_dispatch:\n\s+inputs:\n\s+capture_now:")
        block = code[code.index("capture_now:"):code.index("prev_slot_start:")]
        self.assertIn('default: "1"', block)
        self.assertIn("prev_slot_start:", code)
        self.assertIn("spacing_minutes:", code)

    def test_the_cron_stays_as_the_backstop(self):
        self.assertIn('- cron: "*/15 * * * *"', _code(WORKFLOW))

    def test_only_the_slot_holds_the_shared_group(self):
        """Review finding 3: a workflow-level group put the pacing wait inside
        the group, holding it ~13 minutes of every 13 so rivals went pending
        where an unchecked run could cancel them. Verified failing against the
        pre-revision workflow (workflow-level group, no `pace` job)."""
        head = _code(WORKFLOW)[:_code(WORKFLOW).index("\njobs:\n")]
        self.assertNotIn("concurrency:", head)
        self.assertNotIn("concurrency:", self.pace)
        self.assertRegex(self.capture,
                         r"concurrency:\n\s+group: forward-capture\n\s+cancel-in-progress: false")

    def test_the_rival_still_shares_the_group(self):
        """afternoon-slate commits to the same branch; the group is what
        serialises it against a slot. (daily-loop.yml moved to its own group on
        2026-09-14, another track; cron still runs the DEFAULT branch's copy,
        which is why the gate keeps treating daily-loop as a rival.)"""
        text = _code((REPO / ".github" / "workflows" / "afternoon-slate.yml").read_text(encoding="utf-8"))
        self.assertRegex(text, r"concurrency:\n\s+group: forward-capture\n\s+cancel-in-progress: false")

    def test_pace_waits_then_chains_then_gates_last(self):
        names = [re.search(r"name: (.*)", b).group(1) for b in _steps(self.pace) if "name:" in b]
        self.assertEqual(names, ["Space this slot from the previous one (chained runs only)",
                                 "Chain the next slot",
                                 "Wait until joining the shared group cancels nobody"])
        self.assertIn("id: gate", _steps(self.pace)[-1])
        self.assertIn("--gate-only", _steps(self.pace)[-1])
        space = _step(self.pace, "Space this slot")
        self.assertIn("id: spacing", space)
        self.assertIn("PREV_SLOT_START: ${{ inputs.prev_slot_start }}", space)
        self.assertIn("SPACING_MINUTES: ${{ inputs.spacing_minutes }}", space)
        self.assertIn("--space-only", space)
        self.assertIn("yielded: ${{ steps.gate.outputs.yielded }}", self.pace)

    def test_the_chain_step_runs_whatever_happens_to_the_slot(self):
        """(e) The dispatch happens in `pace`, before the slot, with always():
        a failed, skipped or cancelled slot cannot end the chain."""
        chain = _step(self.pace, "Chain the next slot")
        self.assertRegex(chain, r"if: always\(\)")
        self.assertIn("bash scripts/capture_slot.sh --chain-only", chain)
        self.assertIn("GH_TOKEN: ${{ github.token }}", chain)
        self.assertIn("SLOT_START_EPOCH: ${{ steps.spacing.outputs.slot_start }}", chain)
        self.assertIn("CHAIN_SELF_RUN_ID: ${{ github.run_id }}", chain)
        self.assertNotIn("--chain-only", self.capture)

    def test_the_slot_runs_only_through_the_gate(self):
        self.assertRegex(self.capture, r"needs: pace\b")
        self.assertIn("if: ${{ !cancelled() && needs.pace.outputs.yielded == 'false' }}",
                      self.capture)
        self.assertIn("run: bash scripts/capture_slot.sh\n", self.capture + "\n")

    def test_the_workflow_has_exactly_one_slot_invocation(self):
        """Mirrors tests/test_capture_stages_what_it_writes.py, which reads the
        single one-line `run:` naming the script as THE slot: the mode calls
        are `run: |` blocks, and there must be exactly one slot."""
        lines = [l.strip() for l in _code(WORKFLOW).splitlines()
                 if "scripts/capture_slot.sh" in l and l.strip().startswith("run:")]
        self.assertEqual(lines, ["run: bash scripts/capture_slot.sh"])

    def test_the_token_may_dispatch(self):
        self.assertRegex(_code(WORKFLOW), r"permissions:\n(\s+\w+: \w+\n)*\s+actions: write")

    def test_the_slot_does_not_chain_a_second_time_from_this_file(self):
        """Two dispatches per run would be two chains."""
        self.assertIn('CHAIN_BY_WORKFLOW_STEP: "1"', _step(self.capture, "Capture one slot"))
        self.assertEqual(_code(SLOT).count("gh workflow run forward-capture.yml"), 1)
        self.assertNotIn("gh workflow run forward-capture", _code(WORKFLOW))

    def test_blockers_cover_queued_and_pending_runs_of_both_rivals(self):
        code = _code(SLOT)
        self.assertIn("gh run list", code)
        for token in ('"queued"', '"pending"', '"daily-loop"', '"afternoon-slate"'):
            self.assertIn(token, code)


class DenseWindowStalenessFallback(unittest.TestCase):
    """2026-09-15: afternoon-slate refused a slate on a 3.2h-stale board
    (docs/OVERNIGHT_RUN.md) while every forward-capture slot in between
    reported success, because the minute<15 widen was never hit -- the
    chain's gate had yielded slots to a rival and the misses compounded.
    This exercises the REAL snippet from the script (extracted verbatim,
    never re-typed) against a fake `date` and a fabricated
    `data/raw/oddsapi/` tree, so a regression in the fallback shows up here
    without touching the network or an odds credit."""

    START = 'CAPTURE_NOW="${CAPTURE_NOW:-}"'
    END = 'echo "  window:'

    FAKE_DATE = """#!/usr/bin/env bash
case "$*" in
  "-u +%M") echo "45" ;;
  "-u +%Y/%m/%d") echo "2026/09/15" ;;
  "-u -d yesterday +%Y/%m/%d") echo "2026/09/14" ;;
  "-u +%s") echo "$FAKE_NOW_EPOCH" ;;
  "-u -d "*" +%s")
    if [ -n "${FAKE_LATEST_EPOCH:-}" ]; then echo "$FAKE_LATEST_EPOCH"; else exit 1; fi ;;
  *) echo "unhandled fake date args: $*" >&2; exit 1 ;;
esac
"""

    def _snippet(self):
        start = SLOT.index(self.START)
        end = SLOT.index(self.END)
        return SLOT[start:end]

    def _run(self, oddsapi_files=(), **env):
        tmp = Path(tempfile.mkdtemp(prefix="dense_window_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        bindir = tmp / "bin"
        bindir.mkdir()
        date_stub = bindir / "date"
        date_stub.write_text(self.FAKE_DATE, encoding="utf-8")
        date_stub.chmod(0o755)
        for rel in oddsapi_files:
            path = tmp / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"")
        script = tmp / "check_window.sh"
        script.write_text(
            "#!/usr/bin/env bash\nset -uo pipefail\ncd \"$(dirname \"$0\")\"\n"
            + self._snippet() + '\necho "RESULT=$DENSE_WINDOW"\n',
            encoding="utf-8")
        script.chmod(0o755)
        base = {"PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")}
        base.update(env)
        r = subprocess.run([BASH, script.as_posix()], capture_output=True,
                           text=True, env=base, timeout=30)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (result,) = [ln.split("=", 1)[1] for ln in r.stdout.splitlines()
                     if ln.startswith("RESULT=")]
        return int(result)

    @unittest.skipUnless(BASH, "no POSIX bash available")
    def test_a_recent_capture_stays_at_the_narrow_window(self):
        result = self._run(
            oddsapi_files=["data/raw/oddsapi/2026/09/15/20260915T180000Z-a.jsonl.gz"],
            FAKE_NOW_EPOCH="1789489200",  # 2026-09-15T18:20:00Z
            FAKE_LATEST_EPOCH="1789488000",  # 2026-09-15T18:00:00Z -- 20m old
        )
        self.assertEqual(result, 180)

    @unittest.skipUnless(BASH, "no POSIX bash available")
    def test_a_capture_stale_past_55_minutes_widens_to_a_day(self):
        """The exact regression: a minute>=15 slot (FAKE_DATE always answers
        45) with the last real capture over 55 minutes old must still widen,
        not wait for a lucky minute<15 slot that may not come for hours."""
        result = self._run(
            oddsapi_files=["data/raw/oddsapi/2026/09/15/20260915T143130Z-a.jsonl.gz"],
            FAKE_NOW_EPOCH="1789489200",  # 2026-09-15T18:20:00Z
            FAKE_LATEST_EPOCH="1789475490",  # 2026-09-15T14:31:30Z -- ~228m old
        )
        self.assertEqual(result, 1440)

    @unittest.skipUnless(BASH, "no POSIX bash available")
    def test_no_prior_capture_on_disk_widens_immediately(self):
        result = self._run(FAKE_NOW_EPOCH="1789489200")
        self.assertEqual(result, 1440)


class TheCronCopyRestartsTheChain(unittest.TestCase):
    """Cron runs the DEFAULT branch's forward-capture.yml, which this branch
    cannot edit and which has no chain step -- but it runs this branch's
    capture_slot.sh. Without the exit trap a dead chain stays dead until
    someone dispatches by hand."""

    def test_the_slot_chains_on_exit_from_a_workflow_file_without_a_chain_step(self):
        code = _code(SLOT)
        self.assertIn("trap _chain_from_script EXIT", code)
        self.assertLess(code.index("trap _chain_from_script EXIT"), code.index("== dense (one slot) =="))
        fn = code[code.index("_chain_from_script() {"):code.index("trap _chain_from_script EXIT")]
        self.assertIn('*/forward-capture.yml@refs/heads/"$CHAIN_BRANCH") return 0', fn)
        self.assertIn('"${CHAIN_BY_WORKFLOW_STEP:-}" = "1" ] && return 0', fn)
        self.assertIn('"${GITHUB_ACTIONS:-}" = "true" ] || return 0', fn)
        self.assertIn("CHAIN_RESTARTER=1 chain_dispatch", fn)

    def test_the_modes_exit_before_the_slot_spends_anything(self):
        code = _code(SLOT)
        self.assertLess(code.index("--chain-only) chain_dispatch; exit"), code.index("src.cli dense"))
        self.assertLess(code.index("--space-only) chain_space; exit"), code.index("src.cli watch"))
        self.assertLess(code.index("--gate-only) chain_gate; exit"), code.index("src.cli watch"))


if __name__ == "__main__":
    unittest.main()
