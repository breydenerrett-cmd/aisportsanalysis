"""Tests for src/pipeline/rosterwatch.py.

What matters here are the capture properties the V3 timing study leans on:
identical content never duplicates a row, a change always appends one, every
derived event is bracketed by two of our own fetch times, and a first sighting
is honestly marked inadmissible instead of pretending to be a bracket. The
network is faked throughout; the injected clock makes every timestamp exact.
"""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.pipeline import rosterwatch


def _ts(hour, minute=0):
    return datetime(2026, 8, 31, hour, minute, tzinfo=timezone.utc)


def _iso(hour, minute=0):
    return _ts(hour, minute).isoformat()


def _game(game_pk, away=None, home=None):
    return {"game_pk": game_pk, "away_probable_id": away,
            "home_probable_id": home}


def _lineup(*person_ids):
    return [{"order": i, "person_id": pid, "name": f"P{pid}", "position": "1B"}
            for i, pid in enumerate(person_ids, 1)]


class Fixed:
    """A clock whose reading the test moves by hand."""

    def __init__(self):
        self.now = _ts(9)

    def __call__(self):
        return self.now


class WatchCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.clock = Fixed()

    def poll(self, probables=None, lineups=None, transactions=None):
        return rosterwatch.poll(
            game_date="2026-08-31", watch_dir=self.dir, clock=self.clock,
            fetch_probables=self._raise_or(probables, []),
            fetch_lineups=self._raise_or(lineups, {}),
            fetch_transactions=self._raise_or(transactions, []))

    @staticmethod
    def _raise_or(value, default):
        def fetch(iso, timeout=20):
            if isinstance(value, Exception):
                raise value
            return default if value is None else value
        return fetch

    def rows(self, name, data_only=True):
        path = self.dir / name
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # the corruption-handling tests plant these on purpose
        return [r for r in rows if not r.get("poll")] if data_only else rows


class TestProbablesStore(WatchCase):

    def test_first_sighting_always_writes(self):
        self.poll(probables=[_game(1, away=10, home=20)])
        rows = self.rows(rosterwatch.PROBABLES_FILE)
        self.assertEqual(rows, [{"fetched_utc": _iso(9), "game_pk": 1,
                                 "away_probable_id": 10,
                                 "home_probable_id": 20}])

    def test_identical_content_appends_no_data_row(self):
        for hour in (9, 10, 11):
            self.clock.now = _ts(hour)
            self.poll(probables=[_game(1, away=10, home=20)])
        self.assertEqual(len(self.rows(rosterwatch.PROBABLES_FILE)), 1)
        # ...but every successful poll left a marker, which is the bracket.
        markers = [r for r in self.rows(rosterwatch.PROBABLES_FILE, False)
                   if r.get("poll")]
        self.assertEqual([m["fetched_utc"] for m in markers],
                         [_iso(9), _iso(10), _iso(11)])

    def test_change_appends_one_row(self):
        self.poll(probables=[_game(1, away=10, home=20)])
        self.clock.now = _ts(10)
        self.poll(probables=[_game(1, away=99, home=20)])
        rows = self.rows(rosterwatch.PROBABLES_FILE)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["away_probable_id"], 99)

    def test_a_pair_of_none_probables_is_still_a_first_sighting(self):
        self.poll(probables=[_game(1)])
        self.assertEqual(len(self.rows(rosterwatch.PROBABLES_FILE)), 1)


class TestStarterScratch(WatchCase):

    def test_scratch_event_uses_last_unchanged_poll_as_interval_start(self):
        # Listed at 09:00, unchanged at 10:00, scratched by 11:00. The honest
        # bracket is (10:00, 11:00) -- the 09:00 row would be twice as wide.
        self.poll(probables=[_game(1, away=10, home=20)])
        self.clock.now = _ts(10)
        self.poll(probables=[_game(1, away=10, home=20)])
        self.clock.now = _ts(11)
        self.poll(probables=[_game(1, away=99, home=20)])

        scratches = [e for e in rosterwatch.events(self.dir)
                     if e["class"] == rosterwatch.STARTER_SCRATCH]
        self.assertEqual(len(scratches), 1)
        event = scratches[0]
        self.assertEqual(event["game_pk"], 1)
        self.assertEqual(event["interval"], (_iso(10), _iso(11)))
        self.assertFalse(event["inadmissible"])
        self.assertEqual(event["detail"],
                         {"side": "away", "from": 10, "to": 99})

    def test_probable_being_announced_is_not_a_scratch(self):
        self.poll(probables=[_game(1)])
        self.clock.now = _ts(10)
        self.poll(probables=[_game(1, away=10, home=20)])
        self.assertEqual([e for e in rosterwatch.events(self.dir)
                          if e["class"] == rosterwatch.STARTER_SCRATCH], [])

    def test_scratch_to_none_is_a_scratch(self):
        self.poll(probables=[_game(1, away=10, home=20)])
        self.clock.now = _ts(10)
        self.poll(probables=[_game(1, away=None, home=20)])
        scratches = [e for e in rosterwatch.events(self.dir)
                     if e["class"] == rosterwatch.STARTER_SCRATCH]
        self.assertEqual(len(scratches), 1)
        self.assertEqual(scratches[0]["detail"]["to"], None)


class TestLineupsStore(WatchCase):

    def test_no_lineup_writes_nothing_for_the_game(self):
        self.poll(lineups={})
        self.assertEqual(self.rows(rosterwatch.LINEUPS_FILE), [])
        # The marker still proves the poll looked.
        self.assertEqual(len(self.rows(rosterwatch.LINEUPS_FILE, False)), 1)

    def test_first_nonempty_lineup_writes_and_identical_repolls_do_not(self):
        posted = {1: {"away": _lineup(1, 2, 3), "home": []}}
        for hour in (9, 10):
            self.clock.now = _ts(hour)
            self.poll(lineups=posted)
        rows = self.rows(rosterwatch.LINEUPS_FILE)
        self.assertEqual(rows, [{"fetched_utc": _iso(9), "game_pk": 1,
                                 "away_lineup": [1, 2, 3],
                                 "home_lineup": []}])

    def test_changed_lineup_appends(self):
        self.poll(lineups={1: {"away": _lineup(1, 2, 3), "home": []}})
        self.clock.now = _ts(10)
        self.poll(lineups={1: {"away": _lineup(1, 2, 4), "home": []}})
        rows = self.rows(rosterwatch.LINEUPS_FILE)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["away_lineup"], [1, 2, 4])


class TestLineupEvents(WatchCase):

    def test_lineup_posted_bracketed_by_prior_empty_poll(self):
        self.poll(lineups={})  # 09:00 looked, saw no lineup
        self.clock.now = _ts(10)
        self.poll(lineups={1: {"away": _lineup(1, 2, 3), "home": []}})
        posted = [e for e in rosterwatch.events(self.dir)
                  if e["class"] == rosterwatch.LINEUP_POSTED]
        self.assertEqual(len(posted), 1)
        self.assertEqual(posted[0]["interval"], (_iso(9), _iso(10)))
        self.assertFalse(posted[0]["inadmissible"])
        self.assertEqual(posted[0]["detail"], {"side": "away"})

    def test_first_sighting_is_marked_inadmissible(self):
        # The very first poll already sees the lineup: no prior look exists,
        # so there is no lower bound -- grade C, and it must say so.
        self.poll(lineups={1: {"away": _lineup(1, 2, 3), "home": []}})
        posted = [e for e in rosterwatch.events(self.dir)
                  if e["class"] == rosterwatch.LINEUP_POSTED]
        self.assertEqual(len(posted), 1)
        self.assertEqual(posted[0]["interval"], (None, _iso(9)))
        self.assertTrue(posted[0]["inadmissible"])
        self.assertEqual(posted[0]["detail"]["note"], "first sighting")

    def test_each_side_posts_its_own_event(self):
        self.poll(lineups={})
        self.clock.now = _ts(10)
        self.poll(lineups={1: {"away": _lineup(1, 2), "home": []}})
        self.clock.now = _ts(11)
        self.poll(lineups={1: {"away": _lineup(1, 2), "home": _lineup(7, 8)}})
        posted = [e for e in rosterwatch.events(self.dir)
                  if e["class"] == rosterwatch.LINEUP_POSTED]
        self.assertEqual([(e["detail"]["side"], e["interval"]) for e in posted],
                         [("away", (_iso(9), _iso(10))),
                          ("home", (_iso(10), _iso(11)))])

    def test_hitter_removal_is_detected_with_tight_bracket(self):
        self.poll(lineups={1: {"away": _lineup(1, 2, 3), "home": []}})
        self.clock.now = _ts(10)
        self.poll(lineups={1: {"away": _lineup(1, 2, 3), "home": []}})  # same
        self.clock.now = _ts(11)
        self.poll(lineups={1: {"away": _lineup(1, 2, 9), "home": []}})
        scratches = [e for e in rosterwatch.events(self.dir)
                     if e["class"] == rosterwatch.HITTER_SCRATCH]
        self.assertEqual(len(scratches), 1)
        self.assertEqual(scratches[0]["interval"], (_iso(10), _iso(11)))
        self.assertEqual(scratches[0]["detail"], {"side": "away",
                                                  "removed": [3]})

    def test_pure_reorder_or_addition_is_not_a_hitter_scratch(self):
        self.poll(lineups={1: {"away": _lineup(1, 2), "home": []}})
        self.clock.now = _ts(10)
        self.poll(lineups={1: {"away": _lineup(2, 1, 3), "home": []}})
        self.assertEqual([e for e in rosterwatch.events(self.dir)
                          if e["class"] == rosterwatch.HITTER_SCRATCH], [])


class TestTransactions(WatchCase):

    @staticmethod
    def _txn(*ids):
        return [{"transaction_id": i, "date": "2026-08-31"} for i in ids]

    def test_first_seen_dedup(self):
        self.poll(transactions=self._txn(101, 102))
        self.clock.now = _ts(10)
        self.poll(transactions=self._txn(101, 102, 103))
        rows = self.rows(rosterwatch.TRANSACTIONS_FILE)
        self.assertEqual([(r["transaction_id"], r["first_seen_utc"])
                          for r in rows],
                         [(101, _iso(9)), (102, _iso(9)), (103, _iso(10))])

    def test_intervals_first_poll_inadmissible_later_polls_bracketed(self):
        self.poll(transactions=self._txn(101))
        self.clock.now = _ts(10)
        self.poll(transactions=self._txn(101, 103))
        by_id = {e["transaction_id"]: e for e in rosterwatch.events(self.dir)
                 if e["class"] == rosterwatch.TRANSACTION_SEEN}
        self.assertEqual(by_id[101]["interval"], (None, _iso(9)))
        self.assertTrue(by_id[101]["inadmissible"])
        self.assertEqual(by_id[103]["interval"], (_iso(9), _iso(10)))
        self.assertFalse(by_id[103]["inadmissible"])

    def test_rows_without_ids_are_skipped(self):
        self.poll(transactions=[{"transaction_id": None, "date": "2026-08-31"}])
        self.assertEqual(self.rows(rosterwatch.TRANSACTIONS_FILE), [])


class TestFailureIsolation(WatchCase):

    def test_one_source_failing_never_blocks_the_others(self):
        report = self.poll(probables=RuntimeError("MLB API down"),
                           lineups={1: {"away": _lineup(1), "home": []}},
                           transactions=self._txn())
        self.assertEqual([e["source"] for e in report["errors"]], ["probables"])
        self.assertIsNone(report["probables"])
        self.assertEqual(report["lineups"]["written"], 1)
        self.assertEqual(report["transactions"]["new"], 1)
        # The failed source wrote nothing, marker included: a look that never
        # happened must not open anyone's bracket.
        self.assertFalse((self.dir / rosterwatch.PROBABLES_FILE).exists())

    @staticmethod
    def _txn():
        return [{"transaction_id": 500, "date": "2026-08-31"}]

    def test_all_sources_can_fail_without_raising(self):
        report = self.poll(probables=RuntimeError("down"),
                           lineups=RuntimeError("down"),
                           transactions=RuntimeError("down"))
        self.assertEqual(len(report["errors"]), 3)

    def test_naive_clock_is_refused(self):
        with self.assertRaises(rosterwatch.RosterWatchError):
            rosterwatch.poll(
                game_date="2026-08-31", watch_dir=self.dir,
                clock=lambda: datetime(2026, 8, 31, 9),  # naive: no tz
                fetch_probables=lambda iso, timeout=20: [_game(1)],
                fetch_lineups=lambda iso, timeout=20: {},
                fetch_transactions=lambda iso, timeout=20: [])


class TestStoreReading(WatchCase):

    def test_truncated_final_line_is_tolerated(self):
        # The signature of an append cut off mid-write. Months of polling must
        # survive it rather than fail every subsequent run.
        self.poll(probables=[_game(1, away=10, home=20)])
        path = self.dir / rosterwatch.PROBABLES_FILE
        with path.open("a", encoding="utf-8") as handle:
            handle.write('{"fetched_utc": "2026-08-31T1')  # no newline, cut
        self.clock.now = _ts(10)
        with self.assertLogs("src.pipeline.rosterwatch", level="WARNING"):
            report = self.poll(probables=[_game(1, away=10, home=20)])
        self.assertEqual(report["errors"], [])
        self.assertEqual(len(self.rows(rosterwatch.PROBABLES_FILE)), 1)

    def test_corrupt_line_is_skipped_with_a_warning(self):
        self.poll(probables=[_game(1, away=10, home=20)])
        path = self.dir / rosterwatch.PROBABLES_FILE
        content = path.read_text(encoding="utf-8")
        path.write_text("not json\n" + content, encoding="utf-8")
        with self.assertLogs("src.pipeline.rosterwatch", level="WARNING"):
            self.clock.now = _ts(10)
            report = self.poll(probables=[_game(1, away=10, home=20)])
        self.assertEqual(report["errors"], [])
        self.assertEqual(len(self.rows(rosterwatch.PROBABLES_FILE)), 1)

    def test_events_on_empty_dir_is_empty(self):
        self.assertEqual(rosterwatch.events(self.dir), [])

    def test_events_sorted_by_interval_end(self):
        self.poll(probables=[_game(1, away=10, home=20)],
                  lineups={1: {"away": _lineup(1), "home": []}})
        self.clock.now = _ts(10)
        self.poll(probables=[_game(1, away=99, home=20)],
                  lineups={1: {"away": _lineup(1), "home": []}})
        ends = [e["interval"][1] for e in rosterwatch.events(self.dir)]
        self.assertEqual(ends, sorted(ends))


class TestWhichSlateIsToday(WatchCase):
    """The default date is MLB's, and it comes from the injected clock."""

    def _asked(self, clock):
        asked = []

        def fetch(iso, timeout=20):
            asked.append(iso)
            return []

        rosterwatch.poll(watch_dir=self.dir, clock=clock,
                         fetch_probables=fetch, fetch_lineups=lambda i, timeout=20: {},
                         fetch_transactions=fetch)
        return asked

    def test_the_evening_slate_is_watched_until_it_is_actually_over(self):
        # 01:30 UTC is 21:30 Eastern: the West Coast games are an hour from
        # first pitch and posting lineups. Defaulting to the UTC date rolled
        # the poller onto TOMORROW at 20:00 Eastern, so every late lineup and
        # every late scratch went unwatched -- during exactly the hours the
        # dense runner calls this hook every fifteen minutes.
        clock = lambda: datetime(2026, 8, 31, 1, 30, tzinfo=timezone.utc)
        self.assertEqual(set(self._asked(clock)), {"2026-08-30"})

    def test_it_rolls_over_at_midnight_eastern_not_midnight_utc(self):
        clock = lambda: datetime(2026, 8, 31, 5, 30, tzinfo=timezone.utc)
        self.assertEqual(set(self._asked(clock)), {"2026-08-31"})

    def test_an_explicit_date_is_still_obeyed(self):
        clock = lambda: datetime(2026, 8, 31, 1, 30, tzinfo=timezone.utc)
        asked = []

        def fetch(iso, timeout=20):
            asked.append(iso)
            return []

        rosterwatch.poll(game_date="2026-07-04", watch_dir=self.dir,
                         clock=clock, fetch_probables=fetch,
                         fetch_lineups=lambda i, timeout=20: {},
                         fetch_transactions=fetch)
        self.assertEqual(set(asked), {"2026-07-04"})

    def test_a_naive_clock_cannot_choose_a_slate(self):
        with self.assertRaises(rosterwatch.RosterWatchError):
            rosterwatch.poll(watch_dir=self.dir,
                             clock=lambda: datetime(2026, 8, 31, 1, 30))


if __name__ == "__main__":
    unittest.main()
