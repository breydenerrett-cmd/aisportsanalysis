"""A booked card is a schedule, not fresh data.

Until 2026-10-03 the store's `newest` took the latest date in events and bouts, so a card
booked for December made the operator's `status` and the paid `/data/v1/status` report a
date ten weeks ahead and a negative age: the freshness check said "fresher than now" for a
store whose last finished card was days old. `newest` now counts only cards and bouts that
took place (booked, postponed and cancelled ones do not), and the operator's status names
the soonest booked card separately.
"""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.datasvc.ufc import pipeline
from src.datasvc.ufc import store as ufc_store
from src.datasvc.ufc.store import UfcStore

NOW = datetime(2026, 10, 3, 18, 0, tzinfo=timezone.utc)


def _event(event_id, date_utc, status):
    return {"event_id": event_id, "date_utc": date_utc, "status": status}


def _bout(bout_id, date_utc, status):
    return {"bout_id": bout_id, "event_id": "e", "date_utc": date_utc, "status": status,
            "fighter_a_id": "a", "fighter_b_id": "b"}


class NewestCountsWhatTookPlace(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = UfcStore(Path(tmp.name))
        self.store.upsert("events", [
            _event("done", "2026-09-27T23:00Z", "final"),
            _event("tonight", "2026-10-03T23:00Z", "scheduled"),
            _event("december", "2026-12-12T22:00Z", "scheduled"),
            _event("moved", "2026-11-01T22:00Z", "postponed"),
            _event("off", "2026-09-30T22:00Z", "canceled"),
            _event("zombie", "2026-08-01T22:00Z", "scheduled"),     # never updated after it passed
        ])
        self.store.upsert("bouts", [
            _bout("b1", "2026-09-28T03:00Z", "final"),
            _bout("b2", "2026-10-04T03:00Z", "scheduled"),
            _bout("b3", "2026-10-03T17:00Z", "in_progress"),
        ])

    def test_events_newest_is_the_last_finished_card(self):
        self.assertEqual(self.store.newest("events"), "2026-09-27T23:00Z")

    def test_a_bout_under_way_counts_and_a_booked_one_does_not(self):
        self.assertEqual(self.store.newest("bouts"), "2026-10-03T17:00Z")

    def test_the_soonest_booked_card_after_now(self):
        self.assertEqual(self.store.next_scheduled("events", after=NOW), "2026-10-03T23:00Z")
        self.assertEqual(self.store.next_scheduled("bouts", after=NOW), "2026-10-04T03:00Z")

    def test_without_a_clock_a_stale_booking_is_the_soonest(self):
        self.assertEqual(self.store.next_scheduled("events"), "2026-08-01T22:00Z")

    def test_datasets_without_a_schedule_have_no_next(self):
        self.assertIsNone(self.store.next_scheduled("odds", after=NOW))
        self.assertIsNone(self.store.next_scheduled("fighters"))

    def test_only_booked_cards_are_withheld(self):
        for status in ("scheduled", "postponed", "canceled"):
            self.assertFalse(ufc_store.counts_toward_newest("events", {"status": status}), status)
        for status in ("final", "in_progress", "unknown", None):
            self.assertTrue(ufc_store.counts_toward_newest("events", {"status": status}), status)
        # odds and fighters have no schedule: a stray status field never hides a fetch time
        self.assertTrue(ufc_store.counts_toward_newest("odds", {"status": "scheduled"}))

    def test_the_manifest_records_the_same_newest(self):
        manifest = self.store.write_manifest()
        self.assertEqual(manifest["files"]["events.jsonl"]["newest"], "2026-09-27T23:00Z")
        self.assertEqual(manifest["files"]["bouts.jsonl"]["newest"], "2026-10-03T17:00Z")

    def test_operator_status_reports_a_positive_age_and_the_next_card(self):
        out = pipeline.status(self.store, now=NOW)
        self.assertEqual(out["events"], {"records": 6, "newest": "2026-09-27T23:00Z", "age_hours": 139.0,
                                         "next_scheduled": "2026-10-03T23:00Z"})
        self.assertEqual(out["bouts"]["next_scheduled"], "2026-10-04T03:00Z")
        self.assertIsNone(out["odds"]["next_scheduled"])

    def test_a_store_with_only_booked_cards_has_no_newest(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = UfcStore(Path(tmp))
            store.upsert("events", [_event("x", "2026-12-12T22:00Z", "scheduled")])
            out = pipeline.status(store, now=NOW)
            self.assertEqual((out["events"]["newest"], out["events"]["age_hours"], out["events"]["next_scheduled"]),
                             (None, None, "2026-12-12T22:00Z"))


if __name__ == "__main__":
    unittest.main()
