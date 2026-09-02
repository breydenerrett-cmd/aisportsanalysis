"""Tests for src/pipeline/umpirewatch.py.

What matters here, mirroring tests/test_rosterwatch.py: a reveal is bracketed
between two of OUR OWN polls, a first sighting with no prior poll is honestly
marked inadmissible rather than pretending to be a bracket, identical content
across polls never duplicates a data row (markers still accumulate every
poll), and one source failing never blocks the other. The network is faked
throughout; the injected clock makes every timestamp exact.
"""

import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.pipeline import umpirewatch

REPO = Path(__file__).resolve().parent.parent


def _ts(hour, minute=0, day=31):
    return datetime(2026, 8, day, hour, minute, tzinfo=timezone.utc)


def _iso(hour, minute=0, day=31):
    return _ts(hour, minute, day).isoformat()


def _official(uid, official_type, name=None):
    return {"id": uid, "name": name or f"Ump{uid}", "officialType": official_type}


def _crew(base_id=1):
    return [
        _official(base_id, "Home Plate"),
        _official(base_id + 1, "First Base"),
        _official(base_id + 2, "Second Base"),
        _official(base_id + 3, "Third Base"),
    ]


def _record(game_pk, officials=None, game_state="Scheduled",
           first_pitch="2026-09-01T23:00:00Z"):
    return {"game_pk": game_pk, "officials": officials or [],
            "game_state": game_state, "first_pitch_utc": first_pitch}


class Fixed:
    """A clock whose reading the test moves by hand."""

    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now


class WatchCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.clock = Fixed(_ts(9))

    def poll(self, by_date=None, game_date="2026-08-31"):
        by_date = by_date or {}

        def fetch(iso, timeout=20):
            value = by_date.get(iso)
            if isinstance(value, Exception):
                raise value
            return value or []

        return umpirewatch.poll(game_date=game_date, watch_dir=self.dir,
                                clock=self.clock, fetch_officials=fetch)

    def rows(self, data_only=True):
        path = self.dir / umpirewatch.UMPIRES_FILE
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return [r for r in rows if not r.get("poll")] if data_only else rows

    def markers(self):
        return [r for r in self.rows(False) if r.get("poll")]


class TestWhichDatesArePolled(WatchCase):

    def test_polls_today_and_tomorrow(self):
        asked = []

        def fetch(iso, timeout=20):
            asked.append(iso)
            return []

        umpirewatch.poll(game_date="2026-08-31", watch_dir=self.dir,
                         clock=self.clock, fetch_officials=fetch)
        self.assertEqual(asked, ["2026-08-31", "2026-09-01"])

    def test_an_explicit_date_is_obeyed_and_tomorrow_follows_it(self):
        asked = []

        def fetch(iso, timeout=20):
            asked.append(iso)
            return []

        umpirewatch.poll(game_date="2026-07-04", watch_dir=self.dir,
                         clock=self.clock, fetch_officials=fetch)
        self.assertEqual(asked, ["2026-07-04", "2026-07-05"])

    def test_default_date_comes_from_the_clock_via_mlbs_eastern_day(self):
        # 01:30 UTC is 21:30 Eastern -- still the 30th's slate.
        asked = []
        clock = Fixed(datetime(2026, 8, 31, 1, 30, tzinfo=timezone.utc))

        def fetch(iso, timeout=20):
            asked.append(iso)
            return []

        umpirewatch.poll(watch_dir=self.dir, clock=clock, fetch_officials=fetch)
        self.assertEqual(asked, ["2026-08-30", "2026-08-31"])


class TestNoReveal(WatchCase):

    def test_an_unrevealed_game_writes_no_data_row(self):
        self.poll(by_date={"2026-08-31": [_record(1)], "2026-09-01": [_record(2)]})
        self.assertEqual(self.rows(), [])

    def test_but_a_marker_is_written_per_date_proving_we_looked(self):
        self.poll(by_date={"2026-08-31": [_record(1)], "2026-09-01": [_record(2)]})
        markers = self.markers()
        self.assertEqual(len(markers), 2)
        dates = {m["game_date"] for m in markers}
        self.assertEqual(dates, {"2026-08-31", "2026-09-01"})
        for marker in markers:
            self.assertEqual(marker["observed_utc"], _iso(9))


class TestReveal(WatchCase):

    def test_reveal_is_bracketed_by_the_last_empty_poll_and_the_first_full_one(self):
        self.poll(by_date={"2026-08-31": [_record(1)], "2026-09-01": []})
        self.clock.now = _ts(10)
        self.poll(by_date={"2026-08-31": [_record(1, officials=_crew(),
                                                    game_state="Pre-Game")],
                           "2026-09-01": []})
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["game_pk"], 1)
        self.assertEqual(row["observed_utc"], _iso(10))
        self.assertEqual(row["prev_poll_utc"], _iso(9))
        self.assertTrue(row["revealed"])
        self.assertEqual(len(row["crew"]), 4)
        self.assertEqual(row["game_state"], "Pre-Game")
        self.assertEqual(row["commence_time"], "2026-09-01T23:00:00Z")
        self.assertEqual(row["game_date"], "2026-08-31")

    def test_home_plate_umpire_is_pulled_out_of_the_crew(self):
        self.poll(by_date={"2026-08-31": [_record(1, officials=_crew(base_id=50))],
                           "2026-09-01": []})
        row = self.rows()[0]
        self.assertEqual(row["home_plate_umpire"], "Ump50")

    def test_a_reveal_with_no_prior_poll_is_a_first_sighting_and_inadmissible(self):
        # The very first poll already sees a full crew: no prior look exists,
        # so there is no lower bound -- grade C, and the row says so honestly.
        self.poll(by_date={"2026-08-31": [_record(1, officials=_crew())],
                           "2026-09-01": []})
        row = self.rows()[0]
        self.assertIsNone(row["prev_poll_utc"])

    def test_each_game_gets_its_own_bracket(self):
        self.poll(by_date={"2026-08-31": [_record(1), _record(2)], "2026-09-01": []})
        self.clock.now = _ts(10)
        self.poll(by_date={"2026-08-31": [_record(1, officials=_crew()),
                                          _record(2)],
                           "2026-09-01": []})
        self.clock.now = _ts(11)
        self.poll(by_date={"2026-08-31": [_record(1, officials=_crew()),
                                          _record(2, officials=_crew(base_id=9))],
                           "2026-09-01": []})
        rows = {r["game_pk"]: r for r in self.rows()}
        self.assertEqual((rows[1]["prev_poll_utc"], rows[1]["observed_utc"]),
                         (_iso(9), _iso(10)))
        self.assertEqual((rows[2]["prev_poll_utc"], rows[2]["observed_utc"]),
                         (_iso(10), _iso(11)))


class TestIdempotency(WatchCase):

    def test_an_already_revealed_game_is_never_rewritten(self):
        self.poll(by_date={"2026-08-31": [_record(1, officials=_crew())],
                           "2026-09-01": []})
        self.clock.now = _ts(10)
        self.poll(by_date={"2026-08-31": [_record(1, officials=_crew())],
                           "2026-09-01": []})
        self.clock.now = _ts(11)
        self.poll(by_date={"2026-08-31": [_record(1, officials=_crew())],
                           "2026-09-01": []})
        self.assertEqual(len(self.rows()), 1)
        # ...but every successful poll left its own marker.
        markers = [m for m in self.markers() if m["game_date"] == "2026-08-31"]
        self.assertEqual(len(markers), 3)

    def test_a_re_served_but_different_crew_is_still_not_rewritten(self):
        # Exactly one event per game, per docs/RESEARCH_V3_UMPIRE_CLASS.md --
        # a later correction to the crew is not a second registered event.
        self.poll(by_date={"2026-08-31": [_record(1, officials=_crew())],
                           "2026-09-01": []})
        self.clock.now = _ts(10)
        self.poll(by_date={"2026-08-31": [_record(1, officials=_crew(base_id=99))],
                           "2026-09-01": []})
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["home_plate_umpire"], "Ump1")


class TestFailureIsolation(WatchCase):

    def test_one_dates_failure_never_blocks_the_other(self):
        report = self.poll(by_date={
            "2026-08-31": RuntimeError("MLB API down"),
            "2026-09-01": [_record(2, officials=_crew())]})
        self.assertEqual(report["errors"],
                         [{"date": "2026-08-31", "error": "MLB API down"}])
        self.assertIsNone(report["per_date"].get("2026-08-31"))
        self.assertEqual(report["per_date"]["2026-09-01"]["written"], 1)
        # The failed date wrote no marker: a look that never happened must
        # not open a bracket for that date later.
        dates_marked = {m["game_date"] for m in self.markers()}
        self.assertNotIn("2026-08-31", dates_marked)
        self.assertIn("2026-09-01", dates_marked)

    def test_both_dates_can_fail_without_raising(self):
        report = self.poll(by_date={"2026-08-31": RuntimeError("down"),
                                    "2026-09-01": RuntimeError("down")})
        self.assertEqual(len(report["errors"]), 2)
        self.assertEqual(self.rows(), [])

    def test_naive_clock_is_refused(self):
        with self.assertRaises(umpirewatch.UmpireWatchError):
            umpirewatch.poll(
                game_date="2026-08-31", watch_dir=self.dir,
                clock=lambda: datetime(2026, 8, 31, 9),  # naive: no tz
                fetch_officials=lambda iso, timeout=20: [])

    def test_a_naive_clock_cannot_even_choose_a_slate(self):
        with self.assertRaises(umpirewatch.UmpireWatchError):
            umpirewatch.poll(watch_dir=self.dir,
                             clock=lambda: datetime(2026, 8, 31, 1, 30),
                             fetch_officials=lambda iso, timeout=20: [])


class TestEventDerivation(WatchCase):

    def test_events_on_empty_dir_is_empty(self):
        self.assertEqual(umpirewatch.events(self.dir), [])

    def test_an_admissible_reveal_becomes_a_graded_event(self):
        self.poll(by_date={"2026-08-31": [_record(1)], "2026-09-01": []})
        self.clock.now = _ts(10)
        self.poll(by_date={"2026-08-31": [_record(1, officials=_crew())],
                           "2026-09-01": []})
        events = umpirewatch.events(self.dir)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["class"], umpirewatch.UMPIRE_CREW_REVEALED)
        self.assertEqual(event["game_pk"], 1)
        self.assertEqual(event["interval"], (_iso(9), _iso(10)))
        self.assertFalse(event["inadmissible"])
        self.assertEqual(event["detail"]["home_plate_umpire"], "Ump1")
        self.assertEqual(event["detail"]["crew_size"], 4)

    def test_a_first_sighting_event_is_marked_inadmissible(self):
        self.poll(by_date={"2026-08-31": [_record(1, officials=_crew())],
                           "2026-09-01": []})
        event, = umpirewatch.events(self.dir)
        self.assertIsNone(event["interval"][0])
        self.assertTrue(event["inadmissible"])

    def test_an_unrevealed_game_produces_no_event(self):
        self.poll(by_date={"2026-08-31": [_record(1)], "2026-09-01": []})
        self.assertEqual(umpirewatch.events(self.dir), [])


class TestStoreReading(WatchCase):

    def test_corrupt_line_is_skipped_with_a_warning(self):
        self.poll(by_date={"2026-08-31": [_record(1, officials=_crew())],
                           "2026-09-01": []})
        path = self.dir / umpirewatch.UMPIRES_FILE
        content = path.read_text(encoding="utf-8")
        path.write_text("not json\n" + content, encoding="utf-8")
        with self.assertLogs("src.pipeline.umpirewatch", level="WARNING"):
            self.clock.now = _ts(10)
            report = self.poll(by_date={"2026-08-31": [_record(1, officials=_crew())],
                                        "2026-09-01": []})
        self.assertEqual(report["errors"], [])
        self.assertEqual(len(self.rows()), 1)  # not re-written


class TestForwardEvidenceIsGitTracked(unittest.TestCase):
    """data/watch is git-tracked forward evidence, per the module docstring
    and tests/test_forward_evidence_tracked.py. Confirmed directly here too,
    the same way that file confirms it for rosterwatch's stores.
    """

    def test_the_store_path_is_not_gitignored(self):
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--no-index",
             "data/watch/umpires_watch.jsonl"],
            cwd=REPO, capture_output=True, check=False)
        self.assertEqual(
            result.returncode, 1,
            "data/watch/umpires_watch.jsonl would be gitignored if it "
            "appeared fresh right now -- forward evidence must be tracked")


if __name__ == "__main__":
    unittest.main()
