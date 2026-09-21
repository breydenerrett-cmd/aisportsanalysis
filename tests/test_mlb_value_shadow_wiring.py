"""MLB_VALUE_SHADOW_V1 is wired where the prices, lineups and finals exist,
and can never fail the job it rides in.

  * scripts/capture_slot.sh (what the forward-capture schedule runs) publishes
    after the batter-prop capture, the dense odds capture and the
    event->game_pk map it needs, and before staging -- so a decision is
    committed in the same slot it was made.
  * scripts/daily_loop.sh settles after `daily` has ingested yesterday's box
    scores, next to the other settles, and prints the per-arm record next to
    the card's.
  * Both new steps end in `|| true`, and are proved tolerant by running them
    under `set -euo pipefail` with `python3` stubbed to fail.
  * Both scripts already stage `evidence`, which holds the ledgers.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from src.analysis import mlb_value_shadow as shadow
from tests.test_capture_stages_what_it_writes import _covered, _staged_paths

ROOT = Path(__file__).resolve().parent.parent
SLOT = ROOT / "scripts" / "capture_slot.sh"
LOOP = ROOT / "scripts" / "daily_loop.sh"

PUBLISH = 'python3 -m src.analysis.mlb_value_shadow publish --date "$SLATE_DATE"'
SETTLE = "python3 -m src.analysis.mlb_value_shadow settle --recent"
RECORD = "python3 -m src.analysis.mlb_value_shadow record"
SLOT_HEADER = 'echo "== mlb value shadow ($SLATE_DATE) =="'
SETTLE_HEADER = 'echo "== mlb value shadow grading'
RECORD_HEADER = 'echo "== mlb value shadow record'


def _code(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))


def _line_with(text: str, needle: str) -> str:
    lines = [line for line in _code(text).splitlines() if needle in line]
    if len(lines) != 1:
        raise AssertionError(f"expected exactly one line containing {needle!r}, found {len(lines)}")
    return lines[0]


def _block(text: str, header: str, last: str) -> str:
    """The script lines from the step's header echo through `last`."""
    lines = _code(text).splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().startswith(header))
    end = next(i for i in range(start, len(lines)) if last in lines[i])
    return "\n".join(lines[start:end + 1])


def _bash():
    candidates = []
    if sys.platform == "win32":
        candidates += [r"C:\Program Files\Git\bin\bash.exe",
                       r"C:\Program Files\Git\usr\bin\bash.exe"]
    candidates.append(shutil.which("bash"))
    for path in candidates:
        if not path or not Path(path).exists():
            continue
        low = path.lower()
        if sys.platform == "win32" and ("windowsapps" in low or "system32" in low):
            continue
        return path
    return None


def _run_failing(block: str, env_lines: str = "") -> subprocess.CompletedProcess:
    """Run `block` under `set -euo pipefail` (stricter than either script)
    with python3 stubbed to print and exit 3."""
    bash = _bash()
    script = ("set -euo pipefail\n"
              "python3() { echo 'Traceback: simulated failure'; return 3; }\n"
              f"{env_lines}\n{block}\necho STEP_SURVIVED\n")
    return subprocess.run([bash, "-c", script], capture_output=True, text=True, timeout=60)


class CaptureSlotPublishes(unittest.TestCase):
    def setUp(self):
        self.text = SLOT.read_text(encoding="utf-8")
        self.code = _code(self.text)

    def test_the_slot_publishes_the_shadow_for_the_slate_date(self):
        self.assertIn(PUBLISH, self.code)
        self.assertIn(SLOT_HEADER, self.code)

    def test_it_runs_after_the_prices_props_and_game_map_and_before_staging(self):
        at = self.code.index(PUBLISH)
        for before in ("bash scripts/capture_extras.sh",            # batter props (gate capture)
                       'dense --captures 1 --interval 0',          # the multi-book odds
                       'python3 -m src.cli gamekey --date "$SLATE_DATE"',
                       'python3 -m src.cli card publish --date "$SLATE_DATE"'):
            self.assertLess(self.code.index(before), at, before)
        for after in ('echo "== nfl capture =="', "STAGE_PATHS="):
            self.assertLess(at, self.code.index(after), after)

    def test_the_step_ends_in_or_true_and_never_escalates(self):
        line = _line_with(self.text, PUBLISH)
        self.assertTrue(line.rstrip().endswith("|| true"), line)
        block = _block(self.text, SLOT_HEADER, PUBLISH)
        self.assertNotIn("ESCALATE", block)
        self.assertNotIn("exit", block)

    def test_the_block_carries_no_string_other_tests_order_by(self):
        block = _block(self.text, SLOT_HEADER, PUBLISH)
        for anchor in ("card publish --date", "nfl capture", "tennis capture",
                       "nfl card publish", "STAGE_PATHS="):
            self.assertNotIn(anchor, block)

    def test_the_slot_stages_the_decision_ledgers(self):
        staged = _staged_paths(self.text)
        for arm in shadow.ARMS:
            for path in (shadow.decisions_path(Path("evidence/mlb_value_shadow_v1"), arm),
                         shadow.scans_path(Path("evidence/mlb_value_shadow_v1"), arm)):
                self.assertTrue(_covered(str(path), staged), path)
        self.assertEqual(shadow.default_ledger_dir(), ROOT / "evidence" / "mlb_value_shadow_v1")

    @unittest.skipUnless(_bash(), "bash not available")
    def test_a_crashing_publish_cannot_fail_the_slot(self):
        block = _block(self.text, SLOT_HEADER, PUBLISH)
        out = _run_failing(block, "SLATE_DATE=2026-09-21")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("== mlb value shadow (2026-09-21) ==", out.stdout)
        self.assertIn("STEP_SURVIVED", out.stdout)


class DailyLoopSettlesAndRecords(unittest.TestCase):
    def setUp(self):
        self.text = LOOP.read_text(encoding="utf-8")
        self.code = _code(self.text)

    def test_the_loop_settles_after_the_box_ingest_next_to_the_other_settles(self):
        at = self.code.index(SETTLE)
        self.assertLess(self.code.index("python3 -m src.cli daily"), at)
        self.assertLess(self.code.index("== card settle (self-healing window"), at)
        self.assertLess(self.code.index("== nfl card settle"), at)
        self.assertLess(at, self.code.index("== tennis discover"))
        self.assertLess(at, self.code.index("git add data/processed"))

    def test_the_loop_prints_the_per_arm_record_after_the_card_record(self):
        at = self.code.index(RECORD)
        self.assertLess(self.code.index("== card record (running) =="), at)
        self.assertLess(at, self.code.index("git add data/processed"))

    def test_both_steps_end_in_or_true(self):
        for needle in (SETTLE, RECORD):
            line = _line_with(self.text, needle)
            self.assertTrue(line.rstrip().endswith("|| true"), line)

    def test_the_settle_step_notes_the_run(self):
        block = _block(self.text, SETTLE_HEADER, SETTLE)
        after = self.code[self.code.index(SETTLE):]
        next_line = after.splitlines()[1]
        self.assertIn('>> "$RUN_NOTE"', next_line)
        self.assertNotIn("ESCALATE", block)

    def test_the_loop_stages_the_settled_ledgers_without_a_new_pathspec(self):
        staged = _staged_paths(self.text)
        for arm in shadow.ARMS:
            path = shadow.settled_path(Path("evidence/mlb_value_shadow_v1"), arm)
            self.assertTrue(_covered(str(path), staged), path)
        # The loop's add is still all-or-nothing: no new, possibly-missing
        # pathspec may be added to it for this.
        self.assertNotIn("mlb_value_shadow", _line_with(self.text, "git add data/processed"))

    @unittest.skipUnless(_bash(), "bash not available")
    def test_a_crashing_settle_or_record_cannot_fail_the_loop(self):
        for header, last in ((SETTLE_HEADER, SETTLE), (RECORD_HEADER, RECORD)):
            with self.subTest(step=last):
                block = _block(self.text, header, last)
                out = _run_failing(block, "RUN_NOTE=/dev/null")
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertIn("STEP_SURVIVED", out.stdout)


class ScriptsStillParse(unittest.TestCase):
    @unittest.skipUnless(_bash(), "bash not available")
    def test_bash_n(self):
        for script in (SLOT, LOOP):
            out = subprocess.run([_bash(), "-n", str(script)], capture_output=True, text=True,
                                 timeout=60)
            self.assertEqual(out.returncode, 0, f"{script.name}: {out.stderr}")


if __name__ == "__main__":
    unittest.main()
