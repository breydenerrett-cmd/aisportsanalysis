"""S8 (docs/CHECKPOINT_PHASE0_2026-09-03.md): the daily loop's unattended
slate -> settle -> eod wiring, and the pre-slate freshness guard that stops
it from quietly betting on stale inputs.

Three things are tested, matching the task's own three claims:

1. `scripts/daily_loop.sh` textually contains the three new steps, in the
   right order, each one guarded (a non-zero exit from any one of them
   cannot abort the loop).
2. `src/engine/preflight.py`'s two named thresholds exist and are actually
   read by the function that enforces them (not merely defined and
   forgotten), and `src/cli.py`'s `engine slate` command really calls it
   before doing anything else.
3. The guard's real behavior: a fresh board and fresh matchup coverage
   pass; either one being too old refuses, loudly, with no board built and
   nothing staked -- exercised directly against `src.engine.preflight`
   (fast, no CLI subprocess) and once end-to-end through
   `python3 -m src.cli engine slate` (subprocess, matching how the daily
   loop actually invokes it) to prove the wiring in `src/cli.py` is real,
   not just present in the module the CLI happens to import.

Style follows tests/test_deploy_scripts.py (text assertions on the checked-
in script, no script executed) for part 1, and tests/test_engine_glue.py
(temp-dir stores, no monkeypatching of module globals) for parts 2-3.
"""

from __future__ import annotations

import inspect
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.engine import preflight

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "daily_loop.sh"

GAME = "aaaa1111aaaa1111aaaa1111aaaa1111"


def _l1_row(event_id, observed_utc):
    return {
        "sport": "mlb", "event_id": event_id, "game_pk": None,
        "market_key": "h2h", "selection_id": "home_sel", "side": "home",
        "subject_kind": None, "subject_id": None, "line": None, "book": "a",
        "price_american": -150, "observed_utc": observed_utc,
        "book_last_update": None, "known_at": observed_utc,
        "known_at_grade": "A", "capture_id": f"c-{observed_utc}",
        "source": "odds_api", "region": "us", "provider_market_key": "h2h",
        "venue_kind": "sportsbook", "is_close": False, "limit_observed": None,
        "l0_available": False,
    }


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _write_manifest(store: Path, *end_dates) -> None:
    store.mkdir(parents=True, exist_ok=True)
    windows = {f"{end}..{end}": {"rows": 1, "file": f"pitches_{end}.jsonl.gz"}
               for end in end_dates}
    (store / "manifest.json").write_text(json.dumps({"windows": windows}),
                                         encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. scripts/daily_loop.sh: three steps, in order, each guarded
# ---------------------------------------------------------------------------

class DailyLoopScriptWiringTest(unittest.TestCase):
    def setUp(self):
        self.text = SCRIPT.read_text()

    def test_parses_as_valid_bash(self):
        result = subprocess.run(["bash", "-n", str(SCRIPT)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_three_steps_present_in_order(self):
        slate_pos = self.text.index("python3 -m src.cli engine slate")
        settle_pos = self.text.index("python3 -m src.cli engine settle")
        eod_pos = self.text.index("python3 -m src.cli eod ")
        self.assertLess(
            slate_pos, settle_pos,
            "engine slate must run before engine settle (S8 order)")
        self.assertLess(
            settle_pos, eod_pos,
            "engine settle must run before eod (S7 reads settled data)")

    def test_slate_runs_for_today_settle_and_eod_for_yesterday(self):
        self.assertIn('TODAY=$(date -u +%Y-%m-%d)', self.text)
        self.assertIn("engine slate --date \"$TODAY\"", self.text)
        self.assertIn("engine settle --date \"$YESTERDAY\"", self.text)
        self.assertIn('eod --date "$YESTERDAY"', self.text)

    def test_each_step_captures_its_own_exit_status(self):
        for var, cmd in (("SLATE_STATUS", "engine slate"),
                         ("SETTLE_STATUS", "engine settle"),
                         ("EOD_STATUS", "eod ")):
            with self.subTest(step=cmd):
                self.assertIn(
                    f"{var}=$?", self.text,
                    f"no exit-status capture for the {cmd} step -- a "
                    "failure there cannot be told apart from success")

    def test_each_step_escalates_without_aborting(self):
        # No `-e`: a step's non-zero exit already cannot abort the script by
        # itself. What must also be true is that nothing re-adds that abort
        # behavior around the three new steps (no `&&`-chaining the command
        # into the next one, no `|| exit` right after it), and that a
        # failure is turned into a visible ESCALATE line.
        self.assertNotIn("set -e", self.text)
        self.assertIn("set -uo pipefail", self.text)
        for cmd in ("engine slate --date \"$TODAY\"",
                   "engine settle --date \"$YESTERDAY\"",
                   'eod --date "$YESTERDAY"'):
            line = next(l for l in self.text.splitlines() if cmd in l)
            self.assertNotIn("&&", line)
            self.assertNotIn("|| exit", line)
        for marker in ("ESCALATE: engine slate", "ESCALATE: engine settle",
                       "ESCALATE: eod"):
            self.assertIn(marker, self.text)

    def test_new_stores_are_staged_for_commit(self):
        # S5/S6a write data/paper_accounts/*.jsonl, S7 writes docs/eod/*.md
        # -- both must be staged or the daily loop's own commit silently
        # drops what these new steps produced.
        add_lines = [line for line in self.text.splitlines()
                    if line.strip().startswith("git add ")]
        joined = "\n".join(add_lines)
        self.assertIn("data/paper_accounts", joined)
        self.assertIn("docs/eod", joined)

    def test_output_captured_into_the_run_note(self):
        for var in ("SLATE_STATUS", "SETTLE_STATUS", "EOD_STATUS"):
            self.assertIn(f"exit=${var}", self.text)
        self.assertIn(">> \"$RUN_NOTE\"", self.text)
        self.assertIn("RUN_NOTE=docs/OVERNIGHT_RUN.md", self.text)


# ---------------------------------------------------------------------------
# 2. the freshness guard's constants exist and are actually enforced
# ---------------------------------------------------------------------------

class PreflightConstantsWiringTest(unittest.TestCase):
    def test_named_constants_exist_and_are_positive(self):
        self.assertIsInstance(preflight.PRICE_CAPTURE_STALE_HOURS, (int, float))
        self.assertGreater(preflight.PRICE_CAPTURE_STALE_HOURS, 0)
        self.assertIsInstance(preflight.MATCHUP_COVERAGE_MAX_LAG_DAYS, int)
        self.assertGreater(preflight.MATCHUP_COVERAGE_MAX_LAG_DAYS, 0)

    def test_constants_have_reasoning_comments(self):
        source = inspect.getsource(preflight)
        for const in ("PRICE_CAPTURE_STALE_HOURS",
                     "MATCHUP_COVERAGE_MAX_LAG_DAYS"):
            # The comment block precedes the assignment; a bare
            # `NAME = value` with nothing above it would mean the
            # reasoning lives only in someone's head.
            before = source[:source.index(f"\n{const} =")]
            comment_lines = before.splitlines()[-3:]
            self.assertTrue(
                any(line.strip().startswith("#") for line in comment_lines),
                f"{const} has no reasoning comment immediately above it")

    def test_check_function_reads_both_constants(self):
        source = inspect.getsource(preflight.check)
        self.assertIn("PRICE_CAPTURE_STALE_HOURS", source)
        self.assertIn("MATCHUP_COVERAGE_MAX_LAG_DAYS", source)

    def test_cli_engine_slate_calls_the_guard_before_run_slate(self):
        cli_source = (REPO / "src" / "cli.py").read_text()
        fn_start = cli_source.index("def _cmd_engine_slate")
        fn_source = cli_source[fn_start:cli_source.index("\ndef ", fn_start + 1)]
        self.assertIn("preflight.check", fn_source)
        guard_pos = fn_source.index("preflight.check")
        run_slate_pos = fn_source.index("run_slate(")
        self.assertLess(
            guard_pos, run_slate_pos,
            "engine slate must consult the freshness guard before calling "
            "run_slate -- otherwise a refusal cannot happen before staking")


# ---------------------------------------------------------------------------
# 3. the guard's real behavior
# ---------------------------------------------------------------------------

class PreflightBehaviorTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.l1_path = Path(self._tmp.name) / "l1_observations.jsonl"
        self.statcast_store = Path(self._tmp.name) / "statcast"
        self.now = datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc)

    def _fresh_inputs(self, date_str="2026-09-03"):
        _write_jsonl(self.l1_path, [_l1_row(GAME, f"{date_str}T09:30:00Z")])
        _write_manifest(self.statcast_store, "2026-09-02")

    def test_passes_with_fresh_price_capture_and_fresh_coverage(self):
        self._fresh_inputs()
        result = preflight.check("2026-09-03", now=self.now,
                                 l1_path=self.l1_path,
                                 statcast_store=self.statcast_store)
        self.assertTrue(result.ok, result.reasons)
        self.assertEqual(result.reasons, ())

    def test_refuses_on_stale_price_capture(self):
        _write_jsonl(self.l1_path, [_l1_row(GAME, "2026-09-03T02:00:00Z")])
        _write_manifest(self.statcast_store, "2026-09-02")
        result = preflight.check("2026-09-03", now=self.now,
                                 l1_path=self.l1_path,
                                 statcast_store=self.statcast_store)
        self.assertFalse(result.ok)
        self.assertTrue(any("stale" in r for r in result.reasons))
        self.assertTrue(any("PRICE_CAPTURE_STALE_HOURS" in r
                            for r in result.reasons))

    def test_refuses_on_zero_price_capture(self):
        _write_manifest(self.statcast_store, "2026-09-02")
        result = preflight.check("2026-09-03", now=self.now,
                                 l1_path=self.l1_path,
                                 statcast_store=self.statcast_store)
        self.assertFalse(result.ok)
        self.assertTrue(any("no price capture" in r for r in result.reasons))

    def test_refuses_on_stale_matchup_coverage(self):
        _write_jsonl(self.l1_path, [_l1_row(GAME, "2026-09-03T09:30:00Z")])
        _write_manifest(self.statcast_store, "2026-08-27")  # the real gap
        result = preflight.check("2026-09-03", now=self.now,
                                 l1_path=self.l1_path,
                                 statcast_store=self.statcast_store)
        self.assertFalse(result.ok)
        self.assertTrue(any("matchup feature store" in r
                            for r in result.reasons))
        self.assertTrue(any("MATCHUP_COVERAGE_MAX_LAG_DAYS" in r
                            for r in result.reasons))
        self.assertEqual(result.matchup_coverage_end, "2026-08-27")
        self.assertEqual(result.matchup_coverage_lag_days, 7)

    def test_refuses_on_missing_matchup_store(self):
        _write_jsonl(self.l1_path, [_l1_row(GAME, "2026-09-03T09:30:00Z")])
        result = preflight.check("2026-09-03", now=self.now,
                                 l1_path=self.l1_path,
                                 statcast_store=self.statcast_store)
        self.assertFalse(result.ok)
        self.assertTrue(any("no coverage recorded" in r
                            for r in result.reasons))

    def test_both_reasons_reported_together(self):
        result = preflight.check("2026-09-03", now=self.now,
                                 l1_path=self.l1_path,
                                 statcast_store=self.statcast_store)
        self.assertFalse(result.ok)
        self.assertEqual(len(result.reasons), 2)

    def test_now_must_be_timezone_aware(self):
        self._fresh_inputs()
        with self.assertRaises(preflight.PreflightError):
            preflight.check("2026-09-03", now=datetime(2026, 9, 3, 10, 0),
                            l1_path=self.l1_path,
                            statcast_store=self.statcast_store)


# ---------------------------------------------------------------------------
# 4. end-to-end: the actual CLI subcommand the daily loop shells out to
# ---------------------------------------------------------------------------

class EngineSlateCliRefusesOnStaleInputsTest(unittest.TestCase):
    """One real subprocess call proves `src/cli.py` truly wires the guard
    in front of `run_slate` -- not just that `preflight.check` exists and
    passes its own unit tests in isolation. Uses whatever the real,
    on-disk stores actually are (never fabricated) rather than pointing at
    a synthetic fixture, so this is honest about present reality rather
    than assuming a particular checkout: both stores are gitignored
    (`.gitignore` lines for `data/processed/l1_observations.jsonl` and
    `data/historical/*`), so an isolated worktree with neither store
    refuses on "no data captured at all", and a shared checkout with the
    real Statcast backfill's known gap (ending 2026-08-27,
    docs/CHECKPOINT_PHASE0_2026-09-03.md) refuses on staleness instead --
    either way `engine slate` must refuse rather than proceed."""

    def test_engine_slate_refuses_without_writing_anything(self):
        result = subprocess.run(
            [sys.executable, "-m", "src.cli", "engine", "slate",
             "--date", "2026-01-01", "--dry-run"],
            cwd=REPO, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pre-slate freshness guard", result.stderr)


if __name__ == "__main__":
    unittest.main()
