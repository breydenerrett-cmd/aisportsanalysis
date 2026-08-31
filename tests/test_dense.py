"""Tests for dense snapshot capture."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.pipeline import dense


NOW = datetime(2026, 8, 30, 15, 0, tzinfo=timezone.utc)

# The real card, from the free MLB schedule endpoint on 2026-08-31. Kept
# verbatim because the shape is the whole point: twelve of fifteen first
# pitches at :38-:45 past the hour, which is exactly where an hourly run that
# always ends at :00 cannot look.
REAL_SLATE_2026_09_01 = [
    "2026-09-01T22:40:00Z", "2026-09-01T22:40:00Z", "2026-09-01T22:40:00Z",
    "2026-09-01T22:40:00Z", "2026-09-01T22:45:00Z", "2026-09-01T22:45:00Z",
    "2026-09-01T23:40:00Z", "2026-09-01T23:40:00Z", "2026-09-01T23:40:00Z",
    "2026-09-02T00:05:00Z", "2026-09-02T00:10:00Z", "2026-09-02T00:40:00Z",
    "2026-09-02T01:38:00Z", "2026-09-02T01:40:00Z", "2026-09-02T02:10:00Z",
]

# scripts/forward_capture.sh is triggered hourly; the observed commit minutes
# on 2026-08-31 were 13:55 14:21 15:19 16:17 17:15 18:16 20:02.
TRIGGER_MINUTE = 15


def _rows(*times):
    return [{"commence_time": t} for t in times]


class WindowTests(unittest.TestCase):
    def test_a_game_inside_the_window_counts(self):
        rows = _rows("2026-08-30T17:00:00Z")
        self.assertEqual(dense.games_in_window(rows, NOW), 1)

    def test_a_game_beyond_the_window_does_not(self):
        rows = _rows("2026-08-30T22:00:00Z")
        self.assertEqual(dense.games_in_window(rows, NOW), 0)

    def test_a_game_already_under_way_does_not(self):
        # In-play pricing is a different product and is never what this samples.
        rows = _rows("2026-08-30T14:00:00Z")
        self.assertEqual(dense.games_in_window(rows, NOW), 0)

    def test_a_game_starting_exactly_now_does_not(self):
        rows = _rows("2026-08-30T15:00:00Z")
        self.assertEqual(dense.games_in_window(rows, NOW), 0)

    def test_an_unparseable_start_time_is_skipped_not_counted(self):
        rows = _rows("not a timestamp", None, "2026-08-30T17:00:00Z")
        self.assertEqual(dense.games_in_window(rows, NOW), 1)

    def test_a_naive_timestamp_is_treated_as_utc(self):
        rows = _rows("2026-08-30T17:00:00")
        self.assertEqual(dense.games_in_window(rows, NOW), 1)


class CostTests(unittest.TestCase):
    def test_the_daily_estimate_multiplies_out(self):
        cost = dense.estimate_daily_credits(hours_of_baseball=11)
        self.assertEqual(cost["credits_per_hour"],
                         cost["credits_per_call"] * cost["captures_per_hour"])
        self.assertEqual(cost["credits_per_day"], cost["credits_per_hour"] * 11)
        self.assertEqual(cost["credits_per_month"], cost["credits_per_day"] * 30)


class RunTests(unittest.TestCase):
    """The guards, each of which exists to stop a spend."""

    def setUp(self):
        self.calls = []
        self.real_quota = dense.odds_provider.quota
        self.real_status = dense.odds_provider.status
        self.real_capture = dense.snapshots.capture
        self.real_upcoming = dense._upcoming
        dense.odds_provider.status = lambda env=None: {"configured": True}
        dense.snapshots.capture = self._capture

    def tearDown(self):
        dense.odds_provider.quota = self.real_quota
        dense.odds_provider.status = self.real_status
        dense.snapshots.capture = self.real_capture
        dense._upcoming = self.real_upcoming

    def _capture(self, env=None):
        self.calls.append("capture")
        return {"captured": 30, "events": 15, "configured": True}

    def test_nothing_is_spent_below_the_credit_floor(self):
        dense.odds_provider.quota = lambda env=None: {"remaining": 100}
        dense._upcoming = lambda now=None, timeout=20: _rows("2026-08-30T17:00:00Z")
        result = dense.run(credit_floor=5000, now=NOW, sleep=None)
        self.assertEqual(result["skipped"], "credit floor")
        self.assertEqual(self.calls, [])

    def test_nothing_is_spent_when_no_game_is_approaching(self):
        dense.odds_provider.quota = lambda env=None: {"remaining": 50000}
        dense._upcoming = lambda now=None, timeout=20: _rows("2026-08-30T23:00:00Z")
        result = dense.run(now=NOW, sleep=None)
        self.assertEqual(result["captures"], 0)
        self.assertEqual(result["stopped_early"], "no game inside the window")
        self.assertEqual(self.calls, [])

    def test_nothing_is_spent_when_the_schedule_is_unreachable(self):
        # A schedule outage must not become a reason to spend blindly.
        dense.odds_provider.quota = lambda env=None: {"remaining": 50000}
        dense._upcoming = lambda now=None, timeout=20: None
        result = dense.run(now=NOW, sleep=None)
        self.assertEqual(result["stopped_early"], "schedule unreachable")
        self.assertEqual(self.calls, [])

    def test_nothing_is_spent_when_the_quota_cannot_be_read(self):
        def boom(env=None):
            raise dense.odds_provider.OddsProviderError("down")
        dense.odds_provider.quota = boom
        dense._upcoming = lambda now=None, timeout=20: _rows("2026-08-30T17:00:00Z")
        result = dense.run(now=NOW, sleep=None)
        self.assertEqual(result["skipped"], "quota unreadable")
        self.assertEqual(self.calls, [])

    def test_a_full_run_captures_the_requested_number_of_times(self):
        dense.odds_provider.quota = lambda env=None: {"remaining": 50000}
        dense._upcoming = lambda now=None, timeout=20: _rows("2026-08-30T17:00:00Z")
        result = dense.run(captures=4, now=NOW, sleep=None)
        self.assertEqual(result["captures"], 4)
        self.assertEqual(result["observations"], 120)
        self.assertIsNone(result["stopped_early"])
        self.assertEqual(len(self.calls), 4)

    def test_the_window_is_rechecked_before_every_capture(self):
        """A run that outlives its window stops, rather than buying in-play prices."""
        dense.odds_provider.quota = lambda env=None: {"remaining": 50000}
        seen = {"n": 0}

        def shrinking(now=None, timeout=20):
            seen["n"] += 1
            # The game is gone from the window by the third check.
            return (_rows("2026-08-30T17:00:00Z") if seen["n"] < 3
                    else _rows("2026-08-30T14:00:00Z"))

        dense._upcoming = shrinking
        result = dense.run(captures=4, now=NOW, sleep=None)
        self.assertEqual(result["captures"], 2)
        self.assertEqual(result["stopped_early"], "no game inside the window")


class ScheduleHorizonTests(unittest.TestCase):
    """Which calendar dates the window gate is allowed to ask MLB about."""

    # MLB files a game under its EASTERN date. A 22:10 ET first pitch on the
    # 30th is filed under the 30th and starts at 02:10 UTC on the 31st.
    SCHEDULE = {
        "2026-08-30": [{"gameDate": "2026-08-31T02:10:00Z"}],
        "2026-08-31": [{"gameDate": "2026-08-31T17:05:00Z"}],
        "2026-09-01": [],
    }

    def setUp(self):
        self.asked = []
        self.real_schedule = dense.mlb.fetch_schedule

        def fake(day, timeout=20):
            self.asked.append(day)
            return self.SCHEDULE.get(day, [])

        dense.mlb.fetch_schedule = fake

    def tearDown(self):
        dense.mlb.fetch_schedule = self.real_schedule

    def test_yesterdays_slate_is_still_asked_about_after_midnight_utc(self):
        # 01:50 UTC is 21:50 in Seattle: twenty minutes to first pitch, the
        # closing line still uncaptured. Asking only for today and tomorrow
        # made that game invisible -- the loop stopped with "no game inside
        # the window", the close pass never fired, and _missed_windows could
        # not report the gap because the game was not in its list either.
        now = datetime(2026, 8, 31, 1, 50, tzinfo=timezone.utc)
        events = dense._upcoming(now)
        self.assertIn("2026-08-30", self.asked)
        self.assertEqual(dense.games_in_window(events, now), 1)
        self.assertEqual(
            dense.games_in_window(events, now, dense.CLOSE_WINDOW_MINUTES), 1)

    def test_a_game_that_already_started_yesterday_still_does_not_count(self):
        # The extra day widens what we LOOK at, never what counts as upcoming.
        now = datetime(2026, 8, 31, 3, 0, tzinfo=timezone.utc)
        self.assertEqual(dense.games_in_window(dense._upcoming(now), now), 0)


class HourlyCadenceClosePassTests(unittest.TestCase):
    """The F5 close pass under the REAL schedule, not a convenient one.

    data/processed/f5_close.jsonl did not exist. The pass had not errored and
    nothing had been lost: it had simply never had a game in front of it. It
    hung off `run_end`, and `run_end` is pinned to run_start + 45 minutes,
    because a run that finds any game inside the three-hour window always
    takes all four captures -- and a run that finds none breaks early, but
    then nothing is inside twenty-five minutes either, so the break path can
    never price anything. One instant per hour, one 25-minute slice of every
    hour, and a slate that starts its games at :38-:45.

    These tests replay the true cadence. Each fails against a close pass that
    only fires at the end of a run.
    """

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = Path(self.folder.name) / "f5.jsonl"
        self.fetched = []

    def _replay(self, starts, hours=30, trigger_minute=TRIGGER_MINUTE,
                skew_minutes=1, priced=True, captures=4, interval=15):
        """Run the hourly trigger across a whole slate day.

        `skew_minutes` reproduces a measured fact: the free MLB schedule and
        the odds feed disagree about first pitch by about a minute, so the
        gate and the pass are never reading the same clock.
        """
        parsed = [datetime.fromisoformat(s.replace("Z", "+00:00"))
                  for s in starts]
        base = (min(parsed).replace(minute=0, second=0, microsecond=0)
                - timedelta(hours=3))
        hours = max(hours, int((max(parsed) - base).total_seconds() // 3600) + 2)
        schedule = [{"commence_time": s} for s in starts]
        listed = [
            {"id": f"g{i}",
             "commence_time": (datetime.fromisoformat(s.replace("Z", "+00:00"))
                               + timedelta(minutes=skew_minutes))
             .isoformat().replace("+00:00", "Z"),
             "home_team": "Home Nine", "away_team": "Away Nine"}
            for i, s in enumerate(starts)]

        def fetch(event_id, markets, env):
            self.fetched.append(event_id)
            event = next(e for e in listed if e["id"] == event_id)
            if not priced:
                return {"id": event_id, "bookmakers": []}
            return {
                "id": event_id, "commence_time": event["commence_time"],
                "home_team": "Home Nine", "away_team": "Away Nine",
                "bookmakers": [{"key": "fanduel", "markets": [{
                    "key": dense.F5_CLOSE_MARKET,
                    "last_update": event["commence_time"],
                    "outcomes": [{"name": "Home Nine", "price": -125},
                                 {"name": "Away Nine", "price": 105}]}]}],
            }

        reports = []
        for hour in range(hours):
            clock = {"t": base + timedelta(hours=hour, minutes=trigger_minute)}
            with mock.patch.object(dense, "F5_CLOSE_STORE", self.store), \
                 mock.patch.object(dense.odds_provider, "status",
                                   return_value={"configured": True}), \
                 mock.patch.object(dense.odds_provider, "quota",
                                   return_value={"remaining": 50000}), \
                 mock.patch.object(dense.odds_provider, "list_events",
                                   return_value=listed), \
                 mock.patch.object(dense.odds_provider, "fetch_event_odds",
                                   side_effect=fetch), \
                 mock.patch.object(dense.snapshots, "capture",
                                   return_value={"captured": 30,
                                                 "events": 15}), \
                 mock.patch.object(dense.snapshots, "read", return_value=[]), \
                 mock.patch.object(dense, "_upcoming", return_value=schedule):
                reports.append(dense.run(
                    env={}, captures=captures, interval_minutes=interval,
                    now=lambda: clock["t"],
                    sleep=lambda s: clock.__setitem__(
                        "t", clock["t"] + timedelta(seconds=s))))
        return reports

    def _rows(self):
        if not self.store.exists():
            return []
        return [json.loads(line) for line
                in self.store.read_text(encoding="utf-8").splitlines()]

    def test_a_game_at_the_modal_first_pitch_gets_a_close(self):
        """22:40Z is the single most common first pitch on a real card.

        Under the old close-pass-only design the hourly runs ended at 22:00
        and 23:00 and the T-25 window never contained 22:40, so this game was
        never priced on any night, forever.
        """
        self._replay(["2026-09-01T22:40:00Z"])
        self.assertEqual(self.fetched, ["g0"])
        row = self._rows()[0]
        self.assertLess(row["observed_utc"], row["commence_time"])

    def test_every_first_pitch_on_a_real_slate_is_priced_exactly_once(self):
        """The regression test for the silence itself.

        Before the fix this replay priced 3 of 15 games. The 'exactly once'
        half matters as much as the coverage half: the pass bills a credit per
        event, so covering the slate by pricing every game at every capture
        moment would be four times the approved spend.
        """
        self._replay(REAL_SLATE_2026_09_01)
        self.assertEqual(len(self.fetched), len(REAL_SLATE_2026_09_01))
        self.assertEqual(sorted(self.fetched), sorted(set(self.fetched)))
        self.assertEqual(len(self._rows()), len(REAL_SLATE_2026_09_01))

    def test_the_close_lands_within_a_capture_interval_of_first_pitch(self):
        """A "close" taken an hour out is not a close.

        Each game is priced at the last capture moment before its first pitch,
        so the observation is never further out than the capture spacing.
        """
        self._replay(REAL_SLATE_2026_09_01)
        rows = self._rows()
        self.assertEqual(len(rows), len(REAL_SLATE_2026_09_01))
        for row in rows:
            out = (dense._parse(row["commence_time"])
                   - dense._parse(row["observed_utc"]))
            self.assertGreater(out.total_seconds(), 0)
            self.assertLessEqual(out, timedelta(minutes=dense.INTERVAL_MINUTES))

    def test_coverage_does_not_depend_on_which_minute_the_trigger_fires(self):
        """The old design's coverage swung with the trigger's phase.

        That is a scheduler detail no research lane should be hostage to, so
        every phase has to reach the whole slate.
        """
        for minute in (0, 15, 30, 45, 7):
            with self.subTest(trigger_minute=minute):
                self.fetched = []
                self.store.unlink(missing_ok=True)
                self._replay(REAL_SLATE_2026_09_01, trigger_minute=minute)
                self.assertEqual(len(set(self.fetched)),
                                 len(REAL_SLATE_2026_09_01))

    def test_one_run_never_pays_for_more_events_than_the_cap(self):
        """The cap bounds the RUN, not each moment inside it.

        Four moments each free to spend the cap would be a fourfold spend on a
        doubleheader-heavy hour -- the exact failure the cap was added for.
        """
        crowded = [f"2026-09-01T22:{m:02d}:00Z" for m in
                   (20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 35, 40, 45)]
        reports = self._replay(crowded, trigger_minute=15)
        spends = [r["f5_closes"]["events"] for r in reports]
        for spend in spends:
            self.assertLessEqual(spend, dense.F5_CLOSE_MAX_EVENTS)
        # The cap has to actually bind here, or the test proves nothing.
        self.assertEqual(max(spends), dense.F5_CLOSE_MAX_EVENTS)

    def test_a_game_that_got_no_close_is_reported_not_silently_skipped(self):
        """The failure mode of this lane is silence, so silence must speak.

        A run whose games reached first pitch with nothing in the F5 store
        says so; that line is what turns a month of empty file into a same-day
        escalation.
        """
        reports = self._replay(["2026-09-01T22:40:00Z"], priced=False)
        missed = [m for r in reports for m in r["missed_f5_closes"]]
        self.assertEqual(len(missed), 1)
        self.assertEqual(missed[0]["commence_time"], "2026-09-01T22:40:00Z")
        self.assertIn(dense.F5_CLOSE_MARKET, missed[0]["reason"])

    def test_a_priced_game_is_not_reported_as_missed(self):
        reports = self._replay(REAL_SLATE_2026_09_01)
        self.assertEqual([m for r in reports for m in r["missed_f5_closes"]],
                         [])

    def test_a_close_already_in_the_store_counts_as_coverage(self):
        """Reporting reads the store, not just this run's own spend.

        A close bought by an earlier run is coverage, and treating it as
        anything else would open every night with a false alarm and teach the
        operator to ignore the line that matters.
        """
        start = "2026-09-01T22:40:00Z"
        self.store.write_text(json.dumps({
            "observed_utc": "2026-09-01T22:30:00Z", "commence_time": start,
            "event_id": "already", "market": dense.F5_CLOSE_MARKET}) + "\n",
            encoding="utf-8")
        reports = self._replay([start], priced=False)
        self.assertEqual([m for r in reports for m in r["missed_f5_closes"]],
                         [])

    def test_the_break_path_can_never_produce_a_close(self):
        """Why run_end alone was never enough, stated as a test.

        A run stops when nothing is inside the three-hour window -- and then
        nothing can be inside twenty-five minutes either, so the moment the
        old code called "the close" was, on a quiet hour, guaranteed empty.
        """
        quiet = _rows("2026-09-01T22:40:00Z")
        moment = datetime(2026, 9, 1, 3, 0, tzinfo=timezone.utc)
        self.assertEqual(dense.games_in_window(quiet, moment), 0)
        self.assertEqual(
            dense.games_in_window(quiet, moment, dense.CLOSE_WINDOW_MINUTES), 0)


if __name__ == "__main__":
    unittest.main()
