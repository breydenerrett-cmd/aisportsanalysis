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
        self.assertIn("workflow_dispatch", WORKFLOW)
        self.assertIn("CAPTURE_NOW: ${{ github.event_name == 'workflow_dispatch' && '1' || '' }}",
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

    def test_it_publishes_for_the_slate_date_not_the_utc_date(self):
        self.assertIn("SLATE_DATE=$(TZ=America/New_York date +%Y-%m-%d)", _code(SLOT))

    def test_it_never_fails_the_slot(self):
        line = [ln for ln in _code(SLOT).splitlines() if "card publish --date" in ln][0]
        self.assertTrue(line.rstrip().endswith("|| true"), line)

    def test_the_ledger_it_writes_is_staged(self):
        code = _code(SLOT)
        staging = code[code.index("git add data/watch"):]
        self.assertTrue(re.match(r"git add data/watch[^\n]*\\\n\s*evidence\b", staging),
                        "evidence/ (the card ledger) is not staged by the slot's commit")
        self.assertLess(code.index("card publish"), code.index("git add data/watch"))


if __name__ == "__main__":
    unittest.main()
