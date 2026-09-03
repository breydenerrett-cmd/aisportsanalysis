"""tests for src.engine.preflight's LIVE/REPLAY split.

The bug this guards against: `engine slate --date DATE` for a past DATE
compared that date's own last L1 capture against TODAY's wall clock, so any
non-today date was refused as "stale" no matter how fresh its inputs
actually were at the time -- making replay of a past date structurally
impossible. `check()` must instead measure a past date's freshness against
that date's OWN decision time (its own close, for the price check; its own
calendar date, for the matchup-coverage lag), while a live (today's) slate
keeps the original wall-clock rule unchanged.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.engine import preflight

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


class LiveVsReplayModeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.l1_path = Path(self._tmp.name) / "l1_observations.jsonl"
        self.statcast_store = Path(self._tmp.name) / "statcast"
        self.now = datetime(2026, 9, 3, 20, 0, tzinfo=timezone.utc)

    def test_today_is_live_mode(self):
        _write_jsonl(self.l1_path, [_l1_row(GAME, "2026-09-03T19:30:00Z")])
        _write_manifest(self.statcast_store, "2026-09-02")
        result = preflight.check("2026-09-03", now=self.now,
                                 l1_path=self.l1_path,
                                 statcast_store=self.statcast_store)
        self.assertEqual(result.mode, "LIVE")
        self.assertTrue(result.ok, result.reasons)

    def test_future_date_is_also_live_mode(self):
        _write_jsonl(self.l1_path, [_l1_row(GAME, "2026-09-03T19:30:00Z")])
        _write_manifest(self.statcast_store, "2026-09-02")
        result = preflight.check("2026-09-04", now=self.now,
                                 l1_path=self.l1_path,
                                 statcast_store=self.statcast_store)
        self.assertEqual(result.mode, "LIVE")

    def test_past_date_is_replay_mode(self):
        _write_jsonl(self.l1_path, [_l1_row(GAME, "2026-09-01T09:30:00Z")])
        _write_manifest(self.statcast_store, "2026-09-02")
        result = preflight.check("2026-09-01", now=self.now,
                                 l1_path=self.l1_path,
                                 statcast_store=self.statcast_store)
        self.assertEqual(result.mode, "REPLAY")

    def test_replay_of_a_two_day_old_capture_passes_on_its_own_freshness(self):
        """The exact reported bug: a capture from two days ago, genuinely
        fresh relative to ITS OWN day, must not be refused merely because
        two days of wall-clock time have since passed."""
        _write_jsonl(self.l1_path, [_l1_row(GAME, "2026-09-01T23:30:00Z")])
        _write_manifest(self.statcast_store, "2026-08-31")
        result = preflight.check("2026-09-01", now=self.now,
                                 l1_path=self.l1_path,
                                 statcast_store=self.statcast_store)
        self.assertEqual(result.mode, "REPLAY")
        self.assertTrue(result.ok, result.reasons)
        # Age is measured against the CLOSE of 2026-09-01, not `self.now`:
        # a capture 30 minutes before that midnight is ~0.5h stale, not the
        # ~44h a wall-clock comparison against `self.now` would report.
        self.assertLess(result.price_capture_age_hours, 1.0)

    def test_replay_still_refuses_when_capture_stopped_mid_day(self):
        """A REPLAY date whose LAST capture that day was still hours before
        that day's own close is honestly stale -- REPLAY mode changes the
        reference instant, not the threshold."""
        _write_jsonl(self.l1_path, [_l1_row(GAME, "2026-09-01T09:00:00Z")])
        _write_manifest(self.statcast_store, "2026-08-31")
        result = preflight.check("2026-09-01", now=self.now,
                                 l1_path=self.l1_path,
                                 statcast_store=self.statcast_store)
        self.assertEqual(result.mode, "REPLAY")
        self.assertFalse(result.ok)
        self.assertTrue(any("stale" in r for r in result.reasons))

    def test_replay_zero_capture_still_refuses_as_zero_data_not_staleness(self):
        _write_manifest(self.statcast_store, "2026-08-31")
        result = preflight.check("2026-09-01", now=self.now,
                                 l1_path=self.l1_path,
                                 statcast_store=self.statcast_store)
        self.assertEqual(result.mode, "REPLAY")
        self.assertFalse(result.ok)
        self.assertTrue(any("no price capture" in r for r in result.reasons))

    def test_live_mode_stale_capture_still_refuses(self):
        """A live slate on stale inputs must still refuse -- LIVE mode is
        unchanged by this fix."""
        _write_jsonl(self.l1_path, [_l1_row(GAME, "2026-09-01T09:00:00Z")])
        _write_manifest(self.statcast_store, "2026-09-02")
        result = preflight.check("2026-09-03", now=self.now,
                                 l1_path=self.l1_path,
                                 statcast_store=self.statcast_store)
        self.assertEqual(result.mode, "LIVE")
        self.assertFalse(result.ok)

    def test_replay_matchup_coverage_lag_measured_against_slate_date(self):
        """A far-future-looking pitch store (relative to an old replay date)
        is NOT stale for that replay -- the store already covers it."""
        _write_jsonl(self.l1_path, [_l1_row(GAME, "2023-08-15T23:00:00Z")])
        _write_manifest(self.statcast_store, "2026-08-27")  # far ahead
        result = preflight.check("2023-08-15", now=self.now,
                                 l1_path=self.l1_path,
                                 statcast_store=self.statcast_store)
        self.assertEqual(result.mode, "REPLAY")
        self.assertLess(result.matchup_coverage_lag_days, 0)
        self.assertFalse(any("matchup feature store's coverage" in r
                            for r in result.reasons))

    def test_replay_reasons_are_labelled_with_mode(self):
        _write_manifest(self.statcast_store, "2026-08-31")
        result = preflight.check("2026-09-01", now=self.now,
                                 l1_path=self.l1_path,
                                 statcast_store=self.statcast_store)
        self.assertTrue(all(r.startswith("[REPLAY]") for r in result.reasons))

    def test_live_reasons_are_labelled_with_mode(self):
        result = preflight.check("2026-09-03", now=self.now,
                                 l1_path=self.l1_path,
                                 statcast_store=self.statcast_store)
        self.assertTrue(all(r.startswith("[LIVE]") for r in result.reasons))


if __name__ == "__main__":
    unittest.main()
