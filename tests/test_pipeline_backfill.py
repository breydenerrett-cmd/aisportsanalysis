"""Tests for src/pipeline/backfill.py.

Two things matter more than the rest.

TestBudgetIsEnforced: the budget is checked BEFORE each request, using that request's
cost. Checking afterwards discovers an overspend once it has already happened, and the
credits do not come back.

TestResumability: several thousand metered requests will be interrupted. A restart that
re-fetches what it already has spends a one-month subscription twice.
"""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.pipeline import backfill
from src.providers import odds as odds_provider


def payload(timestamp="2025-07-15T22:45:00Z", events=None):
    return {"timestamp": timestamp, "data": events if events is not None else []}


def usage(last=10, remaining=99_000):
    return {"remaining": remaining, "used": 100_000 - remaining, "last": last}


class Recorder:
    """A stand-in fetcher that counts calls and can be told to fail."""

    def __init__(self, events_per_call=1, fail_on=()):
        self.calls = []
        self.events_per_call = events_per_call
        self.fail_on = set(fail_on)

    def __call__(self, stamp, markets=None, timeout=30):
        self.calls.append(stamp)
        if len(self.calls) in self.fail_on:
            raise odds_provider.OddsProviderError("simulated failure")
        events = [{"id": f"e{len(self.calls)}", "commence_time": "2025-07-15T23:05:00Z",
                   "home_team": "New York Yankees", "away_team": "Houston Astros",
                   "bookmakers": []} for _ in range(self.events_per_call)]
        return payload(events=events), usage()


class TempStore(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()


class TestPlanning(unittest.TestCase):

    def test_cost_uses_the_ten_times_historical_multiplier(self):
        # Verified against the live API: one market, one region, one snapshot = 10.
        p = backfill.plan([2025], ["h2h"], snapshot_times=("22:50",))
        self.assertEqual(p["credits_per_snapshot"], 10)

    def test_cost_scales_with_markets(self):
        p = backfill.plan([2025], ["h2h", "totals"], snapshot_times=("22:50",))
        self.assertEqual(p["credits_per_snapshot"], 20)

    def test_cost_scales_with_seasons_and_snapshot_times(self):
        one = backfill.plan([2025], ["h2h"], snapshot_times=("22:50",))
        many = backfill.plan([2023, 2024, 2025], ["h2h"],
                             snapshot_times=("16:50", "22:50", "01:50"))
        self.assertEqual(many["snapshots"], one["snapshots"] * 9)

    def test_a_season_spans_the_regular_season_not_the_calendar(self):
        stamps = backfill.season_timestamps(2025, snapshot_times=("22:50",))
        self.assertEqual(stamps[0].month, backfill.SEASON_START[0])
        self.assertEqual(stamps[-1].month, backfill.SEASON_END[0])
        self.assertTrue(all(s.tzinfo == timezone.utc for s in stamps))


class TestBudgetIsEnforced(TempStore):
    """Checked before the request, not after. Credits do not come back."""

    def test_the_run_stops_before_exceeding_the_budget(self):
        fetch = Recorder()
        report = backfill.run([2025], ["h2h"], snapshot_times=("22:50",),
                              budget=35, store=self.store, fetch=fetch)
        # 10 credits each, so three fit in 35 and the fourth must not be attempted.
        self.assertEqual(len(fetch.calls), 3)
        self.assertEqual(report["credits_spent"], 30)
        self.assertIsNotNone(report["stopped_early"])

    def test_a_budget_smaller_than_one_request_spends_nothing(self):
        fetch = Recorder()
        report = backfill.run([2025], ["h2h"], snapshot_times=("22:50",),
                              budget=5, store=self.store, fetch=fetch)
        self.assertEqual(fetch.calls, [])
        self.assertEqual(report["credits_spent"], 0)

    def test_stopping_early_keeps_everything_already_fetched(self):
        backfill.run([2025], ["h2h"], snapshot_times=("22:50",),
                     budget=25, store=self.store, fetch=Recorder())
        self.assertEqual(len(backfill.read_season(2025, self.store)), 2)

    def test_credits_spent_uses_the_reported_cost_not_the_estimate(self):
        # The API is the authority on what a call cost. An estimate that drifts from
        # the real billing would silently overrun the budget.
        def pricey(stamp, markets=None, timeout=30):
            return payload(), usage(last=25)
        report = backfill.run([2025], ["h2h"], snapshot_times=("22:50",),
                              budget=60, store=self.store, fetch=pricey)
        # Estimated at 10 each, actually billed 25. Costing the next request at the
        # estimate would approve a third call and overrun by 15; costing it at the
        # observed price stops at two.
        self.assertEqual(report["credits_spent"], 50)
        self.assertIsNotNone(report["stopped_early"])

    def test_remaining_credits_are_reported_from_the_response(self):
        def dwindling(stamp, markets=None, timeout=30):
            return payload(), usage(remaining=42)
        report = backfill.run([2025], ["h2h"], snapshot_times=("22:50",),
                              budget=20, store=self.store, fetch=dwindling)
        self.assertEqual(report["credits_remaining"], 42)


class TestResumability(TempStore):

    def test_a_second_run_refetches_nothing(self):
        first = Recorder()
        backfill.run([2025], ["h2h"], snapshot_times=("22:50",), budget=30,
                     store=self.store, fetch=first)
        second = Recorder()
        report = backfill.run([2025], ["h2h"], snapshot_times=("22:50",), budget=0,
                              store=self.store, fetch=second)
        self.assertEqual(second.calls, [])
        self.assertEqual(report["skipped_cached"], 3)

    def test_resuming_continues_where_it_stopped(self):
        backfill.run([2025], ["h2h"], snapshot_times=("22:50",), budget=20,
                     store=self.store, fetch=Recorder())
        again = Recorder()
        backfill.run([2025], ["h2h"], snapshot_times=("22:50",), budget=20,
                     store=self.store, fetch=again)
        self.assertEqual(len(again.calls), 2)
        self.assertEqual(len(backfill.read_season(2025, self.store)), 4)

    def test_a_failed_snapshot_is_retried_rather_than_marked_done(self):
        # Recording a failure as complete would leave a permanent hole that no later
        # run could ever notice.
        first = Recorder(fail_on=(1,))
        backfill.run([2025], ["h2h"], snapshot_times=("22:50",), budget=30,
                     store=self.store, fetch=first)
        second = Recorder()
        backfill.run([2025], ["h2h"], snapshot_times=("22:50",), budget=10,
                     store=self.store, fetch=second)
        # The retry is the FIRST stamp -- the one that failed -- not the next unfetched
        # one, which would leave the hole in place forever.
        self.assertEqual(second.calls, [first.calls[0]])

    def test_a_different_market_set_is_a_different_snapshot(self):
        # h2h alone is not the same observation as h2h plus totals, and treating them
        # as interchangeable would skip work that was never done.
        backfill.run([2025], ["h2h"], snapshot_times=("22:50",), budget=10,
                     store=self.store, fetch=Recorder())
        other = Recorder()
        backfill.run([2025], ["h2h", "totals"], snapshot_times=("22:50",), budget=20,
                     store=self.store, fetch=other)
        self.assertEqual(len(other.calls), 1)

    def test_an_empty_slate_is_recorded_not_skipped(self):
        # An off-day must be distinguishable from a date that was never fetched.
        def empty(stamp, markets=None, timeout=30):
            return payload(events=[]), usage()
        report = backfill.run([2025], ["h2h"], snapshot_times=("22:50",), budget=20,
                              store=self.store, fetch=empty)
        self.assertEqual(report["empty_snapshots"], 2)
        second = Recorder()
        again = backfill.run([2025], ["h2h"], snapshot_times=("22:50",), budget=0,
                             store=self.store, fetch=second)
        self.assertEqual(second.calls, [])
        self.assertEqual(again["skipped_cached"], 2)

    def test_a_corrupt_season_file_is_named_not_silently_empty(self):
        target = self.store / "mlb_2025.jsonl"
        target.write_text('{"ok": 1}\nnot json\n', encoding="utf-8")
        with self.assertRaises(backfill.BackfillError) as ctx:
            backfill.read_season(2025, self.store)
        self.assertIn(":2", str(ctx.exception))


class TestClosingPriceMatching(TempStore):
    """The close is approximated from daily snapshots, and the staleness is recorded."""

    def write(self, snapshots):
        target = self.store / "mlb_2025.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            for snapshot_at, commence in snapshots:
                handle.write(json.dumps({
                    "snapshot_at": snapshot_at, "markets": ["h2h"],
                    "events": [{"id": "g1", "commence_time": commence,
                                "home_team": "NYY", "away_team": "HOU",
                                "bookmakers": []}]}) + "\n")

    def test_the_latest_snapshot_before_first_pitch_wins(self):
        self.write([("2025-07-15T16:50:00Z", "2025-07-15T23:05:00Z"),
                    ("2025-07-15T22:50:00Z", "2025-07-15T23:05:00Z")])
        match = backfill.closing_prices(2025, self.store)["g1"]
        self.assertEqual(match["snapshot_at"], "2025-07-15T22:50:00Z")
        self.assertEqual(match["closing_gap_minutes"], 15.0)

    def test_a_snapshot_after_first_pitch_is_never_used(self):
        # An in-play price is not a closing price, and using one would be lookahead
        # of the worst kind -- the market has already seen the first innings.
        self.write([("2025-07-15T22:50:00Z", "2025-07-15T23:05:00Z"),
                    ("2025-07-16T01:50:00Z", "2025-07-15T23:05:00Z")])
        match = backfill.closing_prices(2025, self.store)["g1"]
        self.assertEqual(match["snapshot_at"], "2025-07-15T22:50:00Z")

    def test_a_game_with_only_post_start_snapshots_is_absent(self):
        self.write([("2025-07-16T01:50:00Z", "2025-07-15T23:05:00Z")])
        self.assertEqual(backfill.closing_prices(2025, self.store), {})

    def test_staleness_is_reported_so_it_can_be_filtered(self):
        # A price caught two hours out is not the same evidence as one caught ten
        # minutes out, and averaging them without knowing which is which hides it.
        self.write([("2025-07-15T16:50:00Z", "2025-07-15T23:05:00Z")])
        match = backfill.closing_prices(2025, self.store)["g1"]
        self.assertEqual(match["closing_gap_minutes"], 375.0)


if __name__ == "__main__":
    unittest.main()
