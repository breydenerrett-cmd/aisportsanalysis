"""Tests for bounded UFC/MMA h2h capture (src/pipeline/mma_capture.py).

Covers:
- no upcoming events -> nothing captured, no credits spent
- events outside the fight-week horizon -> nothing captured
- a bout inside its own pre-fight window is captured and marked done
- the 60-minute general cadence gates a second run at the same clock
- an unmeasured family (budget refuses) never spends -- the capture
  respects the same never-spend-when-unmeasured convention every other
  family follows
- rows written carry sport="mma"
"""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.pipeline import mma_capture


@dataclass(frozen=True)
class _Decision:
    allowed: bool
    reason: str


def _allow(family, credits, now=None):
    return _Decision(True, "ok: test allow")


def _refuse(family, credits, now=None):
    return _Decision(False, "PROBE_REQUIRED: mma_h2h has no measured credits_per_event")


class MmaCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.snap_path = Path(self.tmp.name) / "snap.jsonl"
        self.mb_path = Path(self.tmp.name) / "mb.jsonl"
        self.done_path = Path(self.tmp.name) / "done.jsonl"
        self.now = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)

    def _payload(self, event_id, home_price=-150, away_price=130, commence=None):
        commence = commence or (self.now + timedelta(hours=1)).isoformat()
        return {
            "events": [{
                "event_id": event_id,
                "commence_time": commence,
                "home_team": "Fighter A",
                "away_team": "Fighter B",
                "markets": {"h2h": {"book": "bet365", "home_price": home_price,
                                    "away_price": away_price}},
                "all_books": {"h2h": [{"book": "bet365", "home_price": home_price,
                                       "away_price": away_price}]},
            }]
        }

    def test_no_upcoming_events_captures_nothing(self):
        result = mma_capture.run(
            now=self.now, list_events=lambda *, env, sport: [],
            fetch_normalized=lambda *a, **k: {"events": []},
            spend_guard=_allow, snapshot_path=self.snap_path,
            multibook_path=self.mb_path, done_path=self.done_path)
        self.assertFalse(result["captured"])
        self.assertEqual(result["credits"], 0)

    def test_event_outside_fight_week_horizon_captures_nothing(self):
        far = (self.now + timedelta(days=30)).isoformat()
        events = [{"id": "far1", "commence_time": far}]
        result = mma_capture.run(
            now=self.now, list_events=lambda *, env, sport: events,
            fetch_normalized=lambda *a, **k: self._payload("far1", commence=far),
            spend_guard=_allow, snapshot_path=self.snap_path,
            multibook_path=self.mb_path, done_path=self.done_path)
        self.assertFalse(result["captured"])
        self.assertIn("fight-week horizon", result["reason"])

    def test_bout_in_prefight_window_is_captured_and_marked_done(self):
        commence = (self.now + timedelta(minutes=90)).isoformat()
        events = [{"id": "bout1", "commence_time": commence}]

        def fetch(*, markets, env, sport):
            return self._payload("bout1", commence=commence)

        result = mma_capture.run(
            now=self.now, list_events=lambda *, env, sport: events,
            fetch_normalized=fetch, spend_guard=_allow,
            snapshot_path=self.snap_path, multibook_path=self.mb_path,
            done_path=self.done_path)
        self.assertTrue(result["captured"])
        self.assertIn("bout1", result["prefight_events"])
        self.assertTrue(result["rows"] > 0)

        # Rows carry sport="mma".
        legacy_rows = [l for l in self.snap_path.read_text(encoding="utf-8").splitlines() if l]
        self.assertTrue(legacy_rows)
        import json
        self.assertEqual(json.loads(legacy_rows[0])["sport"], "mma")

        # Running again at the same instant: the bout's own prefight pair is
        # already done, and the general cadence has not elapsed -> nothing
        # to capture.
        result2 = mma_capture.run(
            now=self.now, list_events=lambda *, env, sport: events,
            fetch_normalized=fetch, spend_guard=_allow,
            snapshot_path=self.snap_path, multibook_path=self.mb_path,
            done_path=self.done_path)
        self.assertFalse(result2["captured"])

    def test_general_cadence_fires_again_after_the_interval(self):
        # A bout far enough out that its own prefight window never triggers,
        # so only the general GENERAL_INTERVAL_MINUTES cadence is in play.
        commence = (self.now + timedelta(hours=24)).isoformat()
        events = [{"id": "boutX", "commence_time": commence}]

        def fetch(*, markets, env, sport):
            return self._payload("boutX", commence=commence)

        r1 = mma_capture.run(
            now=self.now, list_events=lambda *, env, sport: events,
            fetch_normalized=fetch, spend_guard=_allow,
            snapshot_path=self.snap_path, multibook_path=self.mb_path,
            done_path=self.done_path)
        self.assertTrue(r1["captured"])
        self.assertTrue(r1["general"])

        soon = self.now + timedelta(minutes=30)
        r2 = mma_capture.run(
            now=soon, list_events=lambda *, env, sport: events,
            fetch_normalized=fetch, spend_guard=_allow,
            snapshot_path=self.snap_path, multibook_path=self.mb_path,
            done_path=self.done_path)
        self.assertFalse(r2["captured"])

        later = self.now + timedelta(minutes=mma_capture.GENERAL_INTERVAL_MINUTES + 1)
        r3 = mma_capture.run(
            now=later, list_events=lambda *, env, sport: events,
            fetch_normalized=fetch, spend_guard=_allow,
            snapshot_path=self.snap_path, multibook_path=self.mb_path,
            done_path=self.done_path)
        self.assertTrue(r3["captured"])
        self.assertTrue(r3["general"])

    def test_unmeasured_family_refuses_to_spend(self):
        commence = (self.now + timedelta(minutes=30)).isoformat()
        events = [{"id": "bout1", "commence_time": commence}]
        fetch_called = []

        def fetch(*, markets, env, sport):
            fetch_called.append(True)
            return self._payload("bout1", commence=commence)

        result = mma_capture.run(
            now=self.now, list_events=lambda *, env, sport: events,
            fetch_normalized=fetch, spend_guard=_refuse,
            snapshot_path=self.snap_path, multibook_path=self.mb_path,
            done_path=self.done_path)
        self.assertFalse(result["captured"])
        self.assertIn("PROBE_REQUIRED", result["reason"])
        self.assertEqual(result["credits"], 0)
        self.assertFalse(fetch_called, "no fetch (and no spend) once the "
                                        "budget guard refuses")

    def test_real_budget_refuses_an_unmeasured_mma_h2h_family(self):
        """The real budget.can_spend refuses mma_h2h while it is unmeasured.

        UPDATED 2026-09-22: this used to read the live
        config/capture_families.json and assert mma_h2h was unmeasured. The
        daily loop's probe measured it that morning (1 credit, non-degenerate),
        which is the pipeline working, and it turned the test red. The rule
        under test is "no spend before a probe", so it now runs against its
        own unmeasured config rather than the live one."""
        import json
        import tempfile
        from pathlib import Path
        from src.capture import budget

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "capture_families.json"
            path.write_text(json.dumps({"families": {mma_capture.FAMILY: {
                "measured": False, "credits_per_event": None, "measured_utc": None}}}),
                encoding="utf-8")
            decision = budget.can_spend(mma_capture.FAMILY, mma_capture.CREDITS_PER_CAPTURE,
                                        now=self.now, remaining=99000, spent=0,
                                        families_path=path)
        self.assertFalse(decision.allowed)
        self.assertIn("PROBE_REQUIRED", decision.reason)


if __name__ == "__main__":
    unittest.main()
