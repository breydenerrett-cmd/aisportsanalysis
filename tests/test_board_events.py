"""Tests for src/board/events.py: the InformationEvent free-environment layer.

Every test builds its own tiny JSONL rows and passes them straight to the
emitters, rather than depending on the real data/ tree, so this suite is
hermetic. The idempotency and as_of-integration tests write to a tempdir
store instead.
"""

import json
import tempfile
import unittest
from pathlib import Path

from src.board.events import (
    BOXSCORE_FINAL,
    LINEUP_CHANGED,
    LINEUP_POSTED,
    PROBABLE_CHANGED,
    TRANSACTION_RELEVANT,
    UMPIRE_ASSIGNED,
    WEATHER_FORECAST_UPDATED,
    InformationEvent,
    boxscore_events,
    lineup_events,
    probable_events,
    read_events,
    transaction_events,
    umpire_events,
    weather_events,
    write_events,
)
from src.core.asof import as_of


class IdempotencyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.path = self.tmp / "information_events.jsonl"

    def test_same_event_id_for_identical_inputs(self):
        ev1 = InformationEvent(
            event_kind=LINEUP_POSTED, game_pk="123", subject="home_lineup",
            payload={"side": "home", "lineup": [1, 2, 3]},
            observed_utc="2026-09-01T00:00:00+00:00",
            source="lineups_watch", dedup_key="posted:home")
        ev2 = InformationEvent(
            event_kind=LINEUP_POSTED, game_pk="123", subject="home_lineup",
            payload={"side": "home", "lineup": [1, 2, 3]},
            observed_utc="2026-09-01T00:00:00+00:00",
            source="lineups_watch", dedup_key="posted:home")
        self.assertEqual(ev1.event_id, ev2.event_id)

    def test_write_events_is_append_only_and_dedupes(self):
        rows = [InformationEvent(
            event_kind=BOXSCORE_FINAL, game_pk="1", subject="boxscore",
            payload={"date": "2026-09-01"},
            observed_utc="2026-09-01T00:00:00+00:00",
            source="boxscores", dedup_key="final")]
        written1 = write_events(rows, path=self.path)
        written2 = write_events(rows, path=self.path)  # re-run, same input
        self.assertEqual(written1, 1)
        self.assertEqual(written2, 0)
        self.assertEqual(len(read_events(self.path)), 1)

    def test_write_events_dedupes_within_a_single_call(self):
        row = InformationEvent(
            event_kind=BOXSCORE_FINAL, game_pk="1", subject="boxscore",
            payload={"date": "2026-09-01"},
            observed_utc="2026-09-01T00:00:00+00:00",
            source="boxscores", dedup_key="final")
        written = write_events([row, row], path=self.path)
        self.assertEqual(written, 1)


class LineupEmitterTests(unittest.TestCase):
    def test_first_lineup_is_posted_then_change_is_changed(self):
        rows = [
            {"game_pk": 100, "observed_utc": "2026-09-01T18:00:00+00:00",
             "home_lineup": [1, 2, 3], "away_lineup": []},
            {"game_pk": 100, "observed_utc": "2026-09-01T18:10:00+00:00",
             "home_lineup": [1, 2, 9], "away_lineup": []},
        ]
        events = lineup_events(rows)
        kinds = [e.event_kind for e in events]
        self.assertIn(LINEUP_POSTED, kinds)
        self.assertIn(LINEUP_CHANGED, kinds)
        posted = next(e for e in events if e.event_kind == LINEUP_POSTED)
        self.assertEqual(posted.game_pk, "100")
        self.assertEqual(posted.payload["lineup"], [1, 2, 3])
        changed = next(e for e in events if e.event_kind == LINEUP_CHANGED)
        self.assertEqual(changed.payload["from"], [1, 2, 3])
        self.assertEqual(changed.payload["to"], [1, 2, 9])

    def test_unposted_lineup_emits_nothing(self):
        rows = [{"game_pk": 100, "observed_utc": "2026-09-01T18:00:00+00:00",
                 "home_lineup": [], "away_lineup": []}]
        self.assertEqual(lineup_events(rows), [])

    def test_poll_marker_rows_are_ignored(self):
        rows = [{"fetched_utc": "2026-09-01T18:00:00+00:00", "poll": True}]
        self.assertEqual(lineup_events(rows), [])


class ProbableEmitterTests(unittest.TestCase):
    def test_probable_change_emits_event_but_first_announcement_does_not(self):
        rows = [
            {"game_pk": 200, "observed_utc": "2026-09-01T12:00:00+00:00",
             "home_probable_id": 555, "away_probable_id": None},
            {"game_pk": 200, "observed_utc": "2026-09-01T15:00:00+00:00",
             "home_probable_id": 777, "away_probable_id": 888},
        ]
        events = probable_events(rows)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev.event_kind, PROBABLE_CHANGED)
        self.assertEqual(ev.payload, {"side": "home", "from": 555, "to": 777})


class UmpireEmitterTests(unittest.TestCase):
    def test_umpire_assigned_once_per_name(self):
        rows = [
            {"game_pk": 300, "observed_utc": "2026-09-01T22:00:00+00:00",
             "home_plate_umpire": "Jane Doe", "crew": []},
            {"game_pk": 300, "observed_utc": "2026-09-01T22:30:00+00:00",
             "home_plate_umpire": "Jane Doe", "crew": []},
        ]
        events = umpire_events(rows)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_kind, UMPIRE_ASSIGNED)
        self.assertEqual(events[0].game_pk, "300")


class WeatherEmitterTests(unittest.TestCase):
    def test_material_change_emits_event_small_change_does_not(self):
        rows = [
            {"game_pk": 400, "observed_utc": "2026-09-01T10:00:00+00:00",
             "temp_f": 70.0, "wind_mph": 5.0},
            {"game_pk": 400, "observed_utc": "2026-09-01T14:00:00+00:00",
             "temp_f": 71.0, "wind_mph": 5.5},  # below threshold
            {"game_pk": 400, "observed_utc": "2026-09-01T18:00:00+00:00",
             "temp_f": 80.0, "wind_mph": 5.5},  # temp jumps 9F
        ]
        events = weather_events(rows)
        # first row always emits (no prior baseline); third row emits (material)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[-1].event_kind, WEATHER_FORECAST_UPDATED)
        self.assertIn("temp_f", events[-1].payload)
        self.assertNotIn("wind_mph", events[-1].payload)


class BoxscoreEmitterTests(unittest.TestCase):
    def test_one_event_per_game_first_row_only(self):
        rows = [
            {"game_pk": 500, "observed_utc": "2026-09-01T23:00:00+00:00",
             "date": "2026-09-01", "type": "pitcher"},
            {"game_pk": 500, "observed_utc": "2026-09-01T23:00:01+00:00",
             "date": "2026-09-01", "type": "batter"},
        ]
        events = boxscore_events(rows)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_kind, BOXSCORE_FINAL)


class TransactionEmitterTests(unittest.TestCase):
    def test_transaction_maps_to_game_pk_via_team_and_date(self):
        transactions = [
            {"first_seen_utc": "2026-09-01T20:00:00+00:00",
             "transaction_id": 1, "team": "DET", "player": "Someone",
             "player_id": 42, "category": "recalled", "date": "2026-09-01"},
        ]
        boxscores = [
            {"game_pk": 999, "date": "2026-09-01",
             "team_name": "Detroit Tigers"},
        ]
        events = transaction_events(transactions, boxscores)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev.event_kind, TRANSACTION_RELEVANT)
        self.assertEqual(ev.game_pk, "999")
        self.assertEqual(ev.payload["transaction_id"], 1)

    def test_transaction_with_no_matching_boxscore_is_skipped(self):
        transactions = [
            {"first_seen_utc": "2026-09-01T20:00:00+00:00",
             "transaction_id": 2, "team": "DET", "player": None,
             "player_id": None, "category": "other", "date": "2026-09-01"},
        ]
        events = transaction_events(transactions, boxscore_rows=[])
        self.assertEqual(events, [])

    def test_poll_marker_rows_are_ignored(self):
        transactions = [{"fetched_utc": "2026-09-01T20:00:00+00:00",
                          "poll": True}]
        events = transaction_events(transactions, boxscore_rows=[])
        self.assertEqual(events, [])


class AsOfReadsEventsTests(unittest.TestCase):
    """as_of reads information_events, stop-at-T, same as every other store."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.path = self.tmp / "information_events.jsonl"

    def _write(self, rows):
        with self.path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")

    def _spec(self):
        from src.core.asof import StoreSpec

        def _pk(row):
            v = row.get("game_pk")
            return str(v) if v is not None else None

        def _obs(row):
            return row.get("observed_utc")

        return StoreSpec(
            name="information_events", path=self.path,
            game_key_of=_pk, time_of=_obs,
            fields={
                "transaction_relevant": lambda r: (
                    r.get("payload") if r.get("event_kind") ==
                    "transaction_relevant" else None),
            },
        )

    def test_transaction_reachable_before_t_absent_after(self):
        ev = InformationEvent(
            event_kind=TRANSACTION_RELEVANT, game_pk="999", subject="DET",
            payload={"transaction_id": 1, "team": "DET"},
            observed_utc="2026-09-01T20:00:00+00:00",
            source="transactions_watch", dedup_key="1")
        self._write([ev.to_dict()])

        before = as_of("999", "2026-09-01T19:59:59+00:00",
                        stores=[self._spec()])
        self.assertNotIn("transaction_relevant", before.fields)

        after = as_of("999", "2026-09-01T20:00:01+00:00",
                       stores=[self._spec()])
        self.assertIn("transaction_relevant", after.fields)
        self.assertEqual(
            after.fields["transaction_relevant"].value["transaction_id"], 1)


if __name__ == "__main__":
    unittest.main()
