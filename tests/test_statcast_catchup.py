"""Tests for `src.providers.statcast_pitches.catchup` -- the forward cadence
that extends the pitch store day by day between manual backfills.

Network is stubbed throughout: `fetch_window` is monkeypatched to a
deterministic, in-memory fake, so these tests never touch Baseball Savant
and run in well under a second regardless of `INTER_REQUEST_SECONDS` (also
patched to 0, since the real 10-second politeness pause has no reason to
slow a test down).
"""

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from src.providers import statcast_pitches as sp


def _row(game_date):
    return {"game_date": game_date, "game_pk": 1}


def make_store(root, windows):
    """windows: {'start..end': [row, ...]} written exactly the way
    build()/catchup() write them, so a test store looks indistinguishable
    from a real one."""
    manifest = {"windows": {}}
    for key, rows in windows.items():
        name = f"pitches_{key}.jsonl.gz"
        with gzip.open(Path(root) / name, "wt", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        manifest["windows"][key] = {"rows": len(rows), "file": name}
    (Path(root) / "manifest.json").write_text(json.dumps(manifest, indent=1,
                                                         sort_keys=True),
                                              encoding="utf-8")


class CatchupTestCase(unittest.TestCase):
    """Shared plumbing: a temp store, a fake clock, and a scripted
    `fetch_window` stand-in with call recording."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = self._tmp.name
        self.calls = []
        self._orig_fetch = sp.fetch_window
        self._orig_sleep = sp.time.sleep
        self._orig_now = sp.datetime
        sp.time.sleep = lambda seconds: None  # no politeness pause in tests
        self.addCleanup(self._restore)

    def _restore(self):
        sp.fetch_window = self._orig_fetch
        sp.time.sleep = self._orig_sleep
        sp.datetime = self._orig_now
        self._tmp.cleanup()

    def freeze_today(self, iso_date):
        """Pins `datetime.now(timezone.utc)` (as `catchup` calls it) to
        midnight UTC on `iso_date`, so 'yesterday' and 'today or later'
        become deterministic without depending on the real wall clock."""
        real_datetime = self._orig_now
        year, month, day = (int(p) for p in iso_date.split("-"))

        class _FrozenDatetime(real_datetime):
            @classmethod
            def now(cls, tz=None):
                return real_datetime(year, month, day, tzinfo=tz)

        sp.datetime = _FrozenDatetime

    def stub_fetch(self, rows_by_window=None, fail_windows=()):
        """Replaces `sp.fetch_window` with a fake that records every call
        and returns canned rows (one row per day in the window, by default)
        or raises `StatcastPitchError` for a window key listed in
        `fail_windows` -- every attempt, so retries are exhausted exactly
        like a persistently unreachable Savant."""
        rows_by_window = rows_by_window or {}

        def _fake(start, end, timeout=sp.DEFAULT_TIMEOUT):
            key = f"{start}..{end}"
            self.calls.append(key)
            if key in fail_windows:
                raise sp.StatcastPitchError(f"synthetic failure for {key}")
            if key in rows_by_window:
                return rows_by_window[key]
            lo = sp.date.fromisoformat(start)
            hi = sp.date.fromisoformat(end)
            out, day = [], lo
            while day <= hi:
                out.append(_row(day.isoformat()))
                day += sp.timedelta(days=1)
            return out

        sp.fetch_window = _fake


class TestRefusesWithNoPriorWindows(CatchupTestCase):

    def test_an_empty_store_refuses_rather_than_guessing_a_start(self):
        self.stub_fetch()
        with self.assertRaises(sp.StatcastPitchError):
            sp.catchup(store=self.store)
        self.assertEqual(self.calls, [])  # never even tried to fetch


class TestRefusesFutureOrToday(CatchupTestCase):

    def setUp(self):
        super().setUp()
        make_store(self.store, {"2026-08-24..2026-08-27": [_row("2026-08-27")]})

    def test_through_today_is_refused(self):
        self.freeze_today("2026-09-03")
        self.stub_fetch()
        with self.assertRaises(sp.StatcastPitchError):
            sp.catchup(through="2026-09-03", store=self.store)
        self.assertEqual(self.calls, [])

    def test_through_the_future_is_refused(self):
        self.freeze_today("2026-09-03")
        self.stub_fetch()
        with self.assertRaises(sp.StatcastPitchError):
            sp.catchup(through="2026-09-10", store=self.store)
        self.assertEqual(self.calls, [])

    def test_a_failed_or_refused_call_never_touches_the_manifest(self):
        before = sp.read_manifest(self.store)
        self.freeze_today("2026-09-03")
        self.stub_fetch()
        try:
            sp.catchup(through="2026-09-03", store=self.store)
        except sp.StatcastPitchError:
            pass
        self.assertEqual(sp.read_manifest(self.store), before)


class TestWindowNamingAndOrdering(CatchupTestCase):

    def setUp(self):
        super().setUp()
        make_store(self.store, {
            "2026-08-20..2026-08-23": [_row("2026-08-23")],
            "2026-08-24..2026-08-27": [_row("2026-08-27")],
        })
        self.freeze_today("2026-09-03")  # yesterday = 2026-09-02

    def test_extends_from_the_day_after_the_last_covered_date(self):
        self.stub_fetch()
        sp.catchup(store=self.store)
        # last covered was 2026-08-27; the new window must start the day
        # after it, never re-touching or overlapping what was already there.
        self.assertEqual(self.calls, ["2026-08-28..2026-08-31",
                                      "2026-09-01..2026-09-02"])

    def test_new_windows_are_named_and_recorded_like_build_writes_them(self):
        self.stub_fetch()
        sp.catchup(store=self.store)
        manifest = sp.read_manifest(self.store)
        key = "2026-08-28..2026-08-31"
        self.assertIn(key, manifest["windows"])
        self.assertEqual(manifest["windows"][key]["file"],
                         f"pitches_{key}.jsonl.gz")
        self.assertTrue((Path(self.store) / manifest["windows"][key]["file"])
                        .exists())

    def test_the_two_pre_existing_windows_are_left_byte_identical(self):
        before = {
            key: (Path(self.store) / rec["file"]).read_bytes()
            for key, rec in sp.read_manifest(self.store)["windows"].items()
        }
        self.stub_fetch()
        sp.catchup(store=self.store)
        after_manifest = sp.read_manifest(self.store)
        for key, raw in before.items():
            self.assertEqual(after_manifest["windows"][key],
                             {"rows": 1, "file": f"pitches_{key}.jsonl.gz"})
            self.assertEqual((Path(self.store) / f"pitches_{key}.jsonl.gz")
                            .read_bytes(), raw)

    def test_manifest_windows_read_back_in_chronological_order(self):
        self.stub_fetch()
        sp.catchup(store=self.store)
        keys = sorted(sp.read_manifest(self.store)["windows"])
        self.assertEqual(keys, ["2026-08-20..2026-08-23",
                                "2026-08-24..2026-08-27",
                                "2026-08-28..2026-08-31",
                                "2026-09-01..2026-09-02"])

    def test_rows_are_readable_through_iter_rows_after_catchup(self):
        self.stub_fetch()
        sp.catchup(store=self.store)
        dates = [row["game_date"] for row in sp.iter_rows(self.store)]
        self.assertEqual(dates, ["2026-08-23", "2026-08-27", "2026-08-28",
                                 "2026-08-29", "2026-08-30", "2026-08-31",
                                 "2026-09-01", "2026-09-02"])


class TestIdempotence(CatchupTestCase):

    def setUp(self):
        super().setUp()
        make_store(self.store, {"2026-08-24..2026-08-27": [_row("2026-08-27")]})
        self.freeze_today("2026-09-03")

    def test_rerunning_with_the_same_through_fetches_nothing_new(self):
        self.stub_fetch()
        first = sp.catchup(store=self.store)
        self.assertGreater(first["windows"], 0)
        manifest_after_first = sp.read_manifest(self.store)

        self.calls.clear()
        second = sp.catchup(store=self.store)
        self.assertEqual(self.calls, [])  # no fetch_window call at all
        self.assertEqual(second["windows"], 0)
        self.assertEqual(second["failed"], 0)
        self.assertEqual(sp.read_manifest(self.store), manifest_after_first)

    def test_an_earlier_through_than_already_covered_fetches_nothing(self):
        self.stub_fetch()
        sp.catchup(store=self.store)  # brings coverage through 2026-09-02
        self.calls.clear()
        report = sp.catchup(through="2026-08-28", store=self.store)
        self.assertEqual(self.calls, [])
        self.assertEqual(report["windows"], 0)


class TestResumabilityFromAPartialRun(CatchupTestCase):

    def setUp(self):
        super().setUp()
        make_store(self.store, {"2026-08-24..2026-08-27": [_row("2026-08-27")]})

    def test_a_failed_window_is_not_recorded_and_retries_next_run(self):
        # Frozen so the gap is exactly one window (2026-08-28..2026-08-30):
        # isolates "one window fails" from "a later window still succeeds".
        self.freeze_today("2026-08-31")  # yesterday = 2026-08-30
        self.stub_fetch(fail_windows={"2026-08-28..2026-08-30"})
        first = sp.catchup(store=self.store)
        self.assertEqual(first["failed"], 1)
        self.assertEqual(first["windows"], 0)
        manifest = sp.read_manifest(self.store)
        self.assertNotIn("2026-08-28..2026-08-30", manifest["windows"])
        self.assertFalse((Path(self.store) /
                          "pitches_2026-08-28..2026-08-30.jsonl.gz").exists())

        # The next run (Savant recovered) picks the SAME window back up
        # rather than skipping it as though it had already happened.
        self.calls.clear()
        self.stub_fetch()  # no more failures
        second = sp.catchup(store=self.store)
        self.assertEqual(self.calls, ["2026-08-28..2026-08-30"])
        self.assertEqual(second["windows"], 1)
        self.assertIn("2026-08-28..2026-08-30",
                      sp.read_manifest(self.store)["windows"])

    def test_a_multi_window_gap_stops_at_the_first_failure_not_past_it(self):
        # Freeze further out so the gap needs three windows, and fail the
        # middle one. catchup must NOT go on to fetch the third window
        # after a failure: doing so would record a later window as covered
        # while an earlier one is still missing, and every freshness
        # reader (latest_covered_date / _pitch_coverage_end) trusts the
        # single latest window end as the WHOLE store's coverage bound --
        # a gap like that would silently grade stale data as fresh.
        self.freeze_today("2026-09-07")  # yesterday = 2026-09-06
        self.stub_fetch(fail_windows={"2026-09-01..2026-09-04"})
        first = sp.catchup(store=self.store)
        # The failing window is attempted RETRIES times (with backoff, here
        # a no-op) before the run gives up and stops -- the third window is
        # never even attempted.
        self.assertEqual(self.calls, ["2026-08-28..2026-08-31"]
                         + ["2026-09-01..2026-09-04"] * sp.RETRIES)
        self.assertEqual(first["windows"], 1)  # only 08-28..08-31
        self.assertEqual(first["failed"], 1)   # 09-01..09-04 did not
        manifest = sp.read_manifest(self.store)
        self.assertIn("2026-08-28..2026-08-31", manifest["windows"])
        self.assertNotIn("2026-09-01..2026-09-04", manifest["windows"])
        self.assertNotIn("2026-09-05..2026-09-06", manifest["windows"])
        self.assertEqual(sp.latest_covered_date(self.store), "2026-08-31")

        self.calls.clear()
        self.stub_fetch()
        second = sp.catchup(store=self.store)
        # Resumes from the true high-water mark: both the previously-failed
        # window and the one after it (never attempted the first time) are
        # fetched now, in order, and coverage remains contiguous.
        self.assertEqual(self.calls, ["2026-09-01..2026-09-04",
                                      "2026-09-05..2026-09-06"])
        self.assertEqual(second["windows"], 2)
        manifest = sp.read_manifest(self.store)
        self.assertIn("2026-09-01..2026-09-04", manifest["windows"])
        self.assertIn("2026-09-05..2026-09-06", manifest["windows"])
        self.assertEqual(sp.latest_covered_date(self.store), "2026-09-06")


class TestAlreadyCurrent(CatchupTestCase):

    def test_coverage_already_at_through_fetches_nothing_and_is_not_an_error(self):
        make_store(self.store, {"2026-08-24..2026-08-27": [_row("2026-08-27")]})
        self.freeze_today("2026-08-28")  # yesterday = 2026-08-27, already covered
        self.stub_fetch()
        report = sp.catchup(store=self.store)
        self.assertEqual(self.calls, [])
        self.assertEqual(report["windows"], 0)
        self.assertEqual(report["failed"], 0)


if __name__ == "__main__":
    unittest.main()
