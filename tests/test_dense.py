"""Tests for dense snapshot capture."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.pipeline import dense
from tests import HERMETIC_CREDIT_LOG_STORE


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
        result = dense.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, credit_floor=5000, now=NOW, sleep=None)
        self.assertEqual(result["skipped"], "credit floor")
        self.assertEqual(self.calls, [])

    def test_nothing_is_spent_when_no_game_is_approaching(self):
        dense.odds_provider.quota = lambda env=None: {"remaining": 50000}
        dense._upcoming = lambda now=None, timeout=20: _rows("2026-08-30T23:00:00Z")
        result = dense.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, now=NOW, sleep=None)
        self.assertEqual(result["captures"], 0)
        self.assertEqual(result["stopped_early"], "no game inside the window")
        self.assertEqual(self.calls, [])

    def test_nothing_is_spent_when_the_schedule_is_unreachable(self):
        # A schedule outage must not become a reason to spend blindly.
        dense.odds_provider.quota = lambda env=None: {"remaining": 50000}
        dense._upcoming = lambda now=None, timeout=20: None
        result = dense.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, now=NOW, sleep=None)
        self.assertEqual(result["stopped_early"], "schedule unreachable")
        self.assertEqual(self.calls, [])

    def test_nothing_is_spent_when_the_quota_cannot_be_read(self):
        def boom(env=None):
            raise dense.odds_provider.OddsProviderError("down")
        dense.odds_provider.quota = boom
        dense._upcoming = lambda now=None, timeout=20: _rows("2026-08-30T17:00:00Z")
        result = dense.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, now=NOW, sleep=None)
        self.assertEqual(result["skipped"], "quota unreadable")
        self.assertEqual(self.calls, [])

    def test_a_full_run_captures_the_requested_number_of_times(self):
        dense.odds_provider.quota = lambda env=None: {"remaining": 50000}
        dense._upcoming = lambda now=None, timeout=20: _rows("2026-08-30T17:00:00Z")
        result = dense.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, captures=4, now=NOW, sleep=None)
        self.assertEqual(result["captures"], 4)
        self.assertEqual(result["observations"], 120)
        self.assertIsNone(result["stopped_early"])
        self.assertEqual(len(self.calls), 4)

    def test_a_single_slot_run_captures_once_and_never_sleeps(self):
        """captures=1, interval_minutes=0 is the external-scheduler mode
        (docs/CAPTURE_EXTERNALIZATION.md, scripts/capture_slot.sh): one
        capture, no in-process sleep, so a 15-minute cron invocation can
        each do exactly one slot and exit instead of owning a 45-minute
        internal loop.
        """
        dense.odds_provider.quota = lambda env=None: {"remaining": 50000}
        dense._upcoming = lambda now=None, timeout=20: _rows("2026-08-30T17:00:00Z")
        slept = []
        result = dense.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, captures=1, interval_minutes=0, now=NOW,
                            sleep=slept.append)
        self.assertEqual(result["captures"], 1)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(slept, [])

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
        result = dense.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, captures=4, now=NOW, sleep=None)
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
        # Per-test copy: a test that adds a game must not leak it into the
        # next one.
        self.SCHEDULE = {day: list(games)
                         for day, games in type(self).SCHEDULE.items()}
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

    def test_schedule_rows_carry_the_identity_the_miss_detector_needs(self):
        # Without the clubs, the detector can only match on first pitch, and
        # four games share 22:40 on a normal card.
        self.SCHEDULE["2026-08-31"] = [{
            "gamePk": 778899, "gameDate": "2026-08-31T17:05:00Z",
            "teams": {"home": {"team": {"name": "New York Mets"}},
                      "away": {"team": {"name": "Cincinnati Reds"}}}}]
        rows = dense._upcoming(datetime(2026, 8, 31, 16, 0,
                                        tzinfo=timezone.utc))
        row = next(r for r in rows if r["game_pk"] == 778899)
        self.assertEqual(row["home_team"], "New York Mets")
        self.assertEqual(row["away_team"], "Cincinnati Reds")
        self.assertEqual(row["commence_time"], "2026-08-31T17:05:00Z")

    def test_a_schedule_row_with_no_teams_still_yields_a_start_time(self):
        # A malformed record must not take the window gate down with it.
        rows = dense._upcoming(datetime(2026, 8, 31, 1, 50,
                                        tzinfo=timezone.utc))
        self.assertTrue(all("commence_time" in r for r in rows))
        self.assertTrue(all(r["home_team"] is None for r in rows))


class AnyGameScheduledTests(unittest.TestCase):
    """The free-schedule gate the daily snapshot spends against.

    snapshots.capture() bills the whole-sport odds request whether the slate
    has fifteen games or zero, so a slate-less off-season day would cost ~3
    credits every day for nothing. any_game_scheduled() is the free question
    that stops that -- and it is three-valued so that a schedule OUTAGE (None)
    never masquerades as an empty season, which would drop irreplaceable
    movement on a live day.
    """

    def setUp(self):
        self.real_upcoming = dense._upcoming

    def tearDown(self):
        dense._upcoming = self.real_upcoming

    def test_true_when_the_schedule_lists_games(self):
        dense._upcoming = lambda now=None, timeout=20: _rows(
            "2026-09-01T22:40:00Z")
        self.assertIs(dense.any_game_scheduled(now=NOW), True)

    def test_false_only_when_the_schedule_is_reachable_and_empty(self):
        dense._upcoming = lambda now=None, timeout=20: []
        self.assertIs(dense.any_game_scheduled(now=NOW), False)

    def test_none_when_the_schedule_is_unreachable(self):
        # Unknown, never False -- the caller must spend rather than skip.
        dense._upcoming = lambda now=None, timeout=20: None
        self.assertIsNone(dense.any_game_scheduled(now=NOW))


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
                skew_minutes=1, priced=True, captures=4, interval=15,
                unlisted=()):
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
        # Every game gets its OWN clubs. A real card names sixteen different
        # matchups, and a replay in which every game is "Home Nine at Away
        # Nine" cannot tell an identity-matched detector from a clock-matched
        # one -- which is how a detector blind to simultaneous starts passed
        # its whole suite.
        def clubs(index):
            return {"home_team": f"Home {index}", "away_team": f"Away {index}"}

        schedule = [dict(clubs(i), commence_time=s, game_pk=1000 + i)
                    for i, s in enumerate(starts)]
        # `unlisted` are schedule indices the odds feed never offers, so no
        # spend can reach them: the shape of a genuinely lost close.
        listed = [
            dict(clubs(i), id=f"g{i}",
                 commence_time=(datetime.fromisoformat(s.replace("Z", "+00:00"))
                                + timedelta(minutes=skew_minutes))
                 .isoformat().replace("+00:00", "Z"))
            for i, s in enumerate(starts) if i not in set(unlisted)]

        def fetch(event_id, markets, env):
            self.fetched.append(event_id)
            event = next(e for e in listed if e["id"] == event_id)
            if not priced:
                return {"id": event_id, "bookmakers": []}
            names = clubs(int(event_id[1:]))
            return {
                "id": event_id, "commence_time": event["commence_time"],
                "home_team": names["home_team"],
                "away_team": names["away_team"],
                "bookmakers": [{"key": "fanduel", "markets": [{
                    "key": dense.F5_CLOSE_MARKET,
                    "last_update": event["commence_time"],
                    "outcomes": [
                        {"name": names["home_team"], "price": -125},
                        {"name": names["away_team"], "price": 105}]}]}],
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
                reports.append(dense.run(credit_log_store=HERMETIC_CREDIT_LOG_STORE, 
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

    def test_a_clustered_start_band_fits_inside_the_cap(self):
        """The reason the cap is 8 and not 6, pinned so it cannot drift back.

        MLB clusters its starts. On 2026-09-01 four games begin at 22:40 and
        two at 22:45 -- six starts inside a single run's span, which spent 6
        of 6 under the old cap with zero headroom. A seventh simultaneous
        start was dropped permanently: `seen` and `budget` are per-run, the
        next run begins after first pitch, and an F5 close cannot be refetched
        at any price the next morning.

        Seven starts in one band is ordinary on a 16-game night, so the cap
        has to clear it. This asserts the real band shape plus one, and that
        nothing is dropped.
        """
        band = ["2026-09-01T22:40:00Z"] * 5 + ["2026-09-01T22:45:00Z"] * 2
        reports = self._replay(band, trigger_minute=15)
        dropped = [d for r in reports for d in r["f5_closes"]["dropped"]]
        self.assertEqual(
            dropped, [],
            "a clustered start band must fit inside the cap; a dropped F5 "
            "close is unrecoverable")
        self.assertFalse(any(r["f5_closes"]["budget_exhausted"]
                             for r in reports))
        # Deliberately NOT asserted here: that every game in the band gets
        # priced. Writing this test found that two of the seven do not -- and
        # that they are correctly REPORTED as missed rather than lost in
        # silence, which is the property that matters. The cause is the close
        # window's reach, not the budget (5 events against a cap of 8, never
        # exhausted), so it is a separate question from this constant and is
        # recorded as such rather than folded in here. The real-slate test
        # above still prices all fifteen games exactly once.

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

    def test_a_lost_close_hiding_behind_a_simultaneous_start_is_reported(self):
        """DEFECT 1, reproduced on the real card plus one extra 22:40 start.

        Sixteen games, fifteen priced: the sixteenth shares its first pitch
        with four others, and matching stored closes to scheduled games on
        first pitch alone let one of those four mark it covered. Sixteen
        games, one lost close, `missed_f5_closes == []`. Identity matching is
        what makes the loss visible; on a card with four simultaneous starts
        a timestamp is not a key.
        """
        card = REAL_SLATE_2026_09_01 + ["2026-09-01T22:40:00Z"]
        ghost = len(card) - 1
        reports = self._replay(card, unlisted=(ghost,))
        self.assertEqual(len(set(self.fetched)), len(card) - 1)
        missed = [m for r in reports for m in r["missed_f5_closes"]]
        self.assertEqual([m["home_team"] for m in missed], [f"Home {ghost}"])
        self.assertEqual(missed[0]["commence_time"], "2026-09-01T22:40:00Z")

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


class DenseCommandOutputTests(unittest.TestCase):
    """A miss-detector nobody can read is not a miss-detector.

    `run()` returned `missed_f5_closes` and `cmd_dense` never printed it, so
    the line scripts/forward_capture.sh greps and the operator reads did not
    exist for the F5 lane at all.
    """

    def _stdout(self, result):
        import io
        import contextlib
        from src import cli

        args = mock.Mock(estimate=False, captures=4, interval=15, window=180)
        buffer = io.StringIO()
        with mock.patch.object(dense, "run", return_value=result), \
             contextlib.redirect_stdout(buffer):
            self.assertEqual(cli.cmd_dense(args), cli.EXIT_OK)
        return buffer.getvalue()

    def _result(self, **extra):
        base = {"captures": 1, "observations": 30, "detail": [], "close_capture": None,
                "missed_windows": [], "missed_f5_closes": [],
                "f5_closes": {"events": 1, "rows": 1, "errors": [],
                              "dropped": []}}
        base.update(extra)
        return base

    def test_a_missed_f5_close_reaches_stdout_named(self):
        out = self._stdout(self._result(missed_f5_closes=[{
            "commence_time": "2026-09-01T22:40:00Z",
            "home_team": "Chicago Cubs", "away_team": "Atlanta Braves",
            "reason": "no price stored"}]))
        self.assertIn("MISSED F5 CLOSE", out)
        self.assertIn("Atlanta Braves at Chicago Cubs", out)
        self.assertIn("2026-09-01T22:40:00Z", out)

    def test_a_budget_drop_reaches_stdout(self):
        out = self._stdout(self._result(f5_closes={
            "events": 6, "rows": 6, "errors": [], "dropped": [{
                "event_id": "g7", "commence_time": "2026-09-01T22:40:00Z",
                "home_team": "Seattle Mariners", "away_team": "Texas Rangers",
                "reason": "F5 close budget bound"}]}))
        self.assertIn("F5 BUDGET DROP", out)
        self.assertIn("Seattle Mariners", out)

    def test_a_clean_run_prints_no_alarm(self):
        out = self._stdout(self._result())
        self.assertNotIn("MISSED F5 CLOSE", out)
        self.assertNotIn("F5 BUDGET DROP", out)


if __name__ == "__main__":
    unittest.main()
