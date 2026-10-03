"""US Eastern time without a tz database: correct after daylight time ends.

2026-10-03: `src/providers/nfl.py`, `src/pipeline/snapshots.py` and `src/pipeline/nfl_capture.py`
fell back to a fixed -04:00 when `zoneinfo` had no tz database (this repo's Windows machines),
each on the claim that every game falls inside daylight time. US daylight time ends on the first
Sunday of November and the NFL season runs into February, so every kickoff from November on was
computed an hour early. They now fall back to `src.data.eastern.EASTERN_FALLBACK`, the US rules
written out. These tests force the fallback (ZoneInfo patched to raise) and, where the tz database
exists, check the fallback against it hour by hour.
"""
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from src.data import eastern
from src.data.eastern import EASTERN_FALLBACK, us_dst_dates
from src.pipeline import nfl_capture, snapshots
from src.providers import nfl

UTC = timezone.utc


def _no_tz_database(*_args, **_kwargs):
    raise LookupError("no time zone database on this machine")


def _forced(module):
    """The module's own `_eastern()` with ZoneInfo unavailable."""
    with mock.patch("zoneinfo.ZoneInfo", side_effect=_no_tz_database):
        return module._eastern()


def _real_new_york():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/New_York")
    except Exception:  # noqa: BLE001
        return None


def _local(*args, fold=0):
    return datetime(*args, tzinfo=EASTERN_FALLBACK, fold=fold)


class TheRules(unittest.TestCase):
    def test_daylight_dates(self):
        self.assertEqual([d.isoformat() for d in us_dst_dates(2026)], ["2026-03-08", "2026-11-01"])
        self.assertEqual([d.isoformat() for d in us_dst_dates(2027)], ["2027-03-14", "2027-11-07"])
        self.assertEqual([d.isoformat() for d in us_dst_dates(2006)], ["2006-04-02", "2006-10-29"])

    def test_offsets_either_side_of_each_change(self):
        cases = [
            ((2026, 10, 4, 13, 0), 0, -4),          # a Sunday 1 pm in October
            ((2026, 11, 1, 0, 30), 0, -4),          # the night it ends, before 01:00
            ((2026, 11, 1, 1, 30), 0, -4),          # the repeated hour, first time through
            ((2026, 11, 1, 1, 30), 1, -5),          # the repeated hour, second time
            ((2026, 11, 1, 2, 30), 0, -5),
            ((2026, 12, 20, 13, 0), 0, -5),         # a Sunday 1 pm in December
            ((2027, 1, 17, 16, 30), 0, -5),         # a January playoff game
            ((2027, 2, 14, 18, 30), 0, -5),         # a February final
            ((2027, 3, 14, 1, 30), 0, -5),
            ((2027, 3, 14, 2, 30), 0, -5),          # the skipped hour: fold=0 keeps the old offset
            ((2027, 3, 14, 2, 30), 1, -4),
            ((2027, 3, 14, 3, 0), 0, -4),
            ((2006, 10, 29, 1, 30), 1, -5),         # the 1987-2006 rule
            ((2006, 4, 2, 3, 0), 0, -4),
        ]
        for fields, fold, hours in cases:
            with self.subTest(fields=fields, fold=fold):
                self.assertEqual(_local(*fields, fold=fold).utcoffset(), timedelta(hours=hours))

    def test_utc_to_eastern_across_the_autumn_change(self):
        first = datetime(2026, 11, 1, 5, 30, tzinfo=UTC).astimezone(EASTERN_FALLBACK)
        second = datetime(2026, 11, 1, 6, 30, tzinfo=UTC).astimezone(EASTERN_FALLBACK)
        self.assertEqual((first.hour, first.minute, first.fold, first.tzname()), (1, 30, 0, "EDT"))
        self.assertEqual((second.hour, second.minute, second.fold, second.tzname()), (1, 30, 1, "EST"))
        self.assertEqual(datetime(2026, 12, 20, 18, 0, tzinfo=UTC).astimezone(EASTERN_FALLBACK).hour, 13)

    def test_utc_to_eastern_across_the_spring_change(self):
        before = datetime(2027, 3, 14, 6, 59, tzinfo=UTC).astimezone(EASTERN_FALLBACK)
        after = datetime(2027, 3, 14, 7, 0, tzinfo=UTC).astimezone(EASTERN_FALLBACK)
        self.assertEqual((before.hour, before.minute), (1, 59))
        self.assertEqual((after.hour, after.minute), (3, 0))

    def test_every_half_hour_round_trips_through_both_changes(self):
        for start in (datetime(2026, 10, 25, tzinfo=UTC), datetime(2027, 3, 7, tzinfo=UTC)):
            moment = start
            while moment < start + timedelta(days=14):
                self.assertEqual(moment.astimezone(EASTERN_FALLBACK).astimezone(UTC), moment, moment)
                moment += timedelta(minutes=30)

    def test_eastern_returns_the_fallback_without_a_tz_database(self):
        with mock.patch("zoneinfo.ZoneInfo", side_effect=_no_tz_database):
            self.assertIs(eastern.eastern(), EASTERN_FALLBACK)


class TheFallbackMatchesTheRepositorysOtherWrittenRules(unittest.TestCase):
    """Runs everywhere, tz database or not: two rules written separately elsewhere in the repo."""

    def test_utc_side_matches_store_freshness_every_hour_of_three_years(self):
        from src.pipeline import store_freshness
        moment = datetime(2025, 1, 1, tzinfo=UTC)
        while moment.year < 2028:
            self.assertEqual(moment.astimezone(EASTERN_FALLBACK).utcoffset(),
                             store_freshness.eastern_offset(moment), moment)
            moment += timedelta(hours=1)

    def test_local_side_matches_the_nfl_clock_every_unambiguous_hour(self):
        from src.datasvc.nfl import timeutil
        wall = datetime(2025, 1, 1, 0, 0)
        while wall.year < 2028:
            if not 1 <= wall.hour <= 2:          # the skipped and repeated hours are tested above
                ours = wall.replace(tzinfo=EASTERN_FALLBACK).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                self.assertEqual(ours, timeutil.eastern_to_utc(wall.date().isoformat(), wall.strftime("%H:%M")),
                                 wall)
            wall += timedelta(hours=1)


@unittest.skipUnless(_real_new_york(), "no tz database on this machine; Linux CI runs this")
class TheFallbackMatchesZoneinfo(unittest.TestCase):
    def test_every_utc_hour_of_three_years(self):
        real = _real_new_york()
        moment = datetime(2025, 1, 1, tzinfo=UTC)
        while moment.year < 2028:
            ours, theirs = moment.astimezone(EASTERN_FALLBACK), moment.astimezone(real)
            self.assertEqual((ours.replace(tzinfo=None), ours.fold, ours.utcoffset()),
                             (theirs.replace(tzinfo=None), theirs.fold, theirs.utcoffset()), moment)
            moment += timedelta(hours=1)

    def test_every_local_hour_and_fold_of_three_years(self):
        real = _real_new_york()
        wall = datetime(2025, 1, 1, 0, 30)
        while wall.year < 2028:
            for fold in (0, 1):
                self.assertEqual(wall.replace(tzinfo=EASTERN_FALLBACK, fold=fold).utcoffset(),
                                 wall.replace(tzinfo=real, fold=fold).utcoffset(), (wall, fold))
            wall += timedelta(hours=1)


class TheModulesFallBackToTheRules(unittest.TestCase):
    """Each module's `_eastern()` with ZoneInfo unavailable, used the way the module uses it."""

    def test_nfl_kickoffs_after_daylight_time_ends(self):
        with mock.patch.object(nfl, "_EASTERN", _forced(nfl)):
            self.assertEqual(nfl.start_utc("2026-10-04", "13:00"), "2026-10-04T17:00:00Z")
            self.assertEqual(nfl.start_utc("2026-12-20", "13:00"), "2026-12-20T18:00:00Z")
            self.assertEqual(nfl.start_utc("2026-11-26", "20:20"), "2026-11-27T01:20:00Z")   # Thanksgiving night
            self.assertEqual(nfl.start_utc("2027-01-17", "16:30"), "2027-01-17T21:30:00Z")   # January playoff

    def test_snapshot_eastern_date_late_at_night_in_winter(self):
        with mock.patch.object(snapshots, "_EASTERN", _forced(snapshots)):
            # 04:30 UTC on Nov 15 is 23:30 on Nov 14 in Eastern standard time
            self.assertEqual(snapshots.official_date("2026-11-15T04:30:00Z"), "2026-11-14")
            self.assertEqual(snapshots.official_date("2026-09-15T03:30:00Z"), "2026-09-14")

    def test_nfl_capture_days_late_at_night_in_winter(self):
        with mock.patch.object(nfl_capture, "_EASTERN", _forced(nfl_capture)):
            now = datetime(2026, 12, 21, 4, 30, tzinfo=UTC)                 # 23:30 Dec 20 Eastern
            self.assertEqual(nfl_capture._et_today_date_strs(now, count=2), ["2026-12-20", "2026-12-21"])


if __name__ == "__main__":
    unittest.main()
