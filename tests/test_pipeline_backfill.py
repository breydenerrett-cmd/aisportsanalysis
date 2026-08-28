"""Tests for src/pipeline/backfill.py.

Two properties decide whether this module is safe to run unattended against a
metered account: the budget must be checked BEFORE a request rather than after
it, and an interruption must cost one snapshot rather than the whole run.
"""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.pipeline import backfill
from src.providers import odds as odds_provider


def stamp(day=20, hour=22, minute=50, year=2025, month=3):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class TestPlanning(unittest.TestCase):

    def test_historical_costs_ten_times_a_live_call(self):
        plan = backfill.plan([2025], ["h2h"], snapshot_times=("22:50",))
        self.assertEqual(plan["credits_per_snapshot"], 10)

    def test_cost_scales_with_markets_and_snapshot_times(self):
        one = backfill.plan([2025], ["h2h"], snapshot_times=("22:50",))
        two = backfill.plan([2025], ["h2h", "totals"],
                            snapshot_times=("16:50", "22:50"))
        self.assertEqual(two["credits_total"], one["credits_total"] * 4)

    def test_three_seasons_of_two_markets_is_the_planned_number(self):
        # The number the subscription decision was made on. If this changes, the
        # budget conversation changes with it.
        plan = backfill.plan([2023, 2024, 2025], ["h2h", "totals"])
        self.assertEqual(plan["credits_total"], 36000)


class TestSnapshotIdentity(unittest.TestCase):

    def test_the_key_includes_the_markets(self):
        # A snapshot fetched for h2h alone is not the same observation as one
        # fetched for h2h and totals; treating them as interchangeable would make
        # a later run skip work it never did.
        self.assertNotEqual(backfill.snapshot_key(stamp(), ["h2h"]),
                            backfill.snapshot_key(stamp(), ["h2h", "totals"]))

    def test_market_order_does_not_change_the_key(self):
        self.assertEqual(backfill.snapshot_key(stamp(), ["totals", "h2h"]),
                         backfill.snapshot_key(stamp(), ["h2h", "totals"]))

    def test_the_key_is_minute_resolution_and_readable(self):
        self.assertEqual(backfill.snapshot_key(stamp(), ["h2h"]),
                         "2025-03-20T22:50Z:h2h")


class TestRun(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Path(self.dir.name)
        self.calls = []

    def tearDown(self):
        self.dir.cleanup()

    def fetch(self, remaining_start=1000, events=2, fail_on=()):
        state = {"remaining": remaining_start}

        def _fetch(when, markets=None, timeout=30):
            self.calls.append(when)
            if len(self.calls) in fail_on:
                raise odds_provider.OddsProviderError("boom")
            state["remaining"] -= 10 * len(markets)
            return ({"timestamp": when.isoformat(),
                     "data": [{"id": f"e{i}"} for i in range(events)]},
                    {"remaining": state["remaining"], "last": 10 * len(markets)})
        return _fetch

    def run_one_day(self, **kwargs):
        kwargs.setdefault("fetch", self.fetch())
        return backfill.run([2025], ["h2h"], snapshot_times=("22:50",),
                            store=self.store, **kwargs)

    def test_the_budget_is_checked_before_the_request_not_after(self):
        # A check afterwards discovers the overspend once it has happened, which
        # on a metered account is the difference between a plan and an overdraft.
        report = self.run_one_day(budget=25)
        self.assertEqual(report["fetched"], 2)
        self.assertEqual(report["credits_spent"], 20)
        self.assertIn("would be exceeded", report["stopped_early"])

    def test_a_zero_budget_spends_nothing(self):
        report = self.run_one_day(budget=0)
        self.assertEqual(report["fetched"], 0)
        self.assertEqual(self.calls, [])

    def test_progress_survives_the_budget_stop(self):
        self.run_one_day(budget=25)
        self.assertEqual(len(backfill.read_season(2025, self.store)), 2)

    def test_a_resumed_run_skips_what_is_already_stored(self):
        self.run_one_day(budget=25)
        second = self.run_one_day(budget=25)
        self.assertEqual(second["skipped_cached"], 2)

    def test_a_failed_snapshot_is_not_recorded_so_it_retries(self):
        # Recording a failure as done leaves a permanent hole that no later run
        # will ever fill.
        report = self.run_one_day(budget=100, fetch=self.fetch(fail_on=(1,)))
        self.assertEqual(report["failed"], 1)
        manifest = backfill.read_manifest(self.store)
        self.assertEqual(len(manifest["snapshots"]), report["fetched"])

    def test_credits_remaining_is_read_from_the_response(self):
        report = self.run_one_day(budget=100)
        self.assertIsNotNone(report["credits_remaining"])

    def test_an_empty_slate_is_recorded_rather_than_skipped(self):
        # A genuine off-day must be distinguishable from a date never fetched.
        report = self.run_one_day(budget=100, fetch=self.fetch(events=0))
        self.assertGreater(report["empty_snapshots"], 0)
        self.assertEqual(report["empty_snapshots"], report["fetched"])


class TestClosingPrices(unittest.TestCase):
    """The closing price is an approximation, and the staleness is reported."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def write(self, snapshots):
        path = self.store / "mlb_2025.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for record in snapshots:
                handle.write(json.dumps(record) + "\n")

    def game(self, start="2025-04-01T23:05:00Z"):
        return {"id": "g1", "commence_time": start, "home_team": "NYY",
                "away_team": "BOS", "bookmakers": [{"key": "dk"}]}

    def test_the_latest_snapshot_before_first_pitch_wins(self):
        self.write([
            {"snapshot_at": "2025-04-01T16:50:00Z", "events": [self.game()]},
            {"snapshot_at": "2025-04-01T22:50:00Z", "events": [self.game()]},
        ])
        close = backfill.closing_prices(2025, self.store)
        self.assertEqual(close["g1"]["snapshot_at"], "2025-04-01T22:50:00Z")

    def test_a_snapshot_after_first_pitch_is_never_used(self):
        # An in-play price is not a closing price, and using one would flatter
        # every CLV number computed from it.
        self.write([
            {"snapshot_at": "2025-04-01T23:50:00Z", "events": [self.game()]},
        ])
        self.assertEqual(backfill.closing_prices(2025, self.store), {})

    def test_the_staleness_is_reported_in_minutes(self):
        self.write([
            {"snapshot_at": "2025-04-01T22:50:00Z", "events": [self.game()]}])
        close = backfill.closing_prices(2025, self.store)
        self.assertEqual(close["g1"]["closing_gap_minutes"], 15.0)

    def test_an_unparseable_timestamp_is_skipped_not_fatal(self):
        self.write([{"snapshot_at": "not a time", "events": [self.game()]}])
        self.assertEqual(backfill.closing_prices(2025, self.store), {})

    def test_a_missing_season_file_is_empty(self):
        self.assertEqual(backfill.closing_prices(2099, self.store), {})


class TestSeasonTimestamps(unittest.TestCase):

    def test_every_configured_time_is_emitted_each_day(self):
        stamps = backfill.season_timestamps(2025, ("16:50", "22:50"))
        self.assertEqual(len(stamps) % 2, 0)
        self.assertEqual({s.hour for s in stamps}, {16, 22})

    def test_the_window_spans_the_regular_season(self):
        stamps = backfill.season_timestamps(2025, ("22:50",))
        self.assertEqual(stamps[0].month, backfill.SEASON_START[0])
        self.assertEqual(stamps[-1].month, backfill.SEASON_END[0])


if __name__ == "__main__":
    unittest.main()


class TestFirstFiveBackfill(unittest.TestCase):
    """Billed per game, so the run has to be picky, resumable, and honest about
    dates the archive simply does not cover."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def games(self, n=2, date="2023-06-04"):
        return [{"date": date, "away_team": "TB", "home_team": "BOS",
                 "game_pk": 1}][:n] or []

    def events(self, teams=(("Tampa Bay Rays", "Boston Red Sox"),),
               only_instant=None):
        self.lookups = []

        def _fetch(game_date, timeout=30, instant=None):
            self.lookups.append(instant)
            listed = teams if (only_instant is None or instant == only_instant) else ()
            return ({"data": [{"id": f"e{i}", "away_team": a, "home_team": h,
                               "commence_time": f"{game_date}T23:05:00Z"}
                              for i, (a, h) in enumerate(listed)]},
                    {"remaining": 1000, "last": 1})
        return _fetch

    def odds(self, raise_with=None):
        self.odds_instants = []

        def _fetch(game_date, event_id, markets, timeout=30, instant=None):
            self.odds_instants.append(instant)
            if raise_with:
                raise raise_with
            return ({"timestamp": f"{game_date}T22:45:00Z",
                     "data": {"bookmakers": [{"key": "dk"}]}},
                    {"remaining": 990, "last": 20})
        return _fetch

    def test_both_instants_are_looked_up_per_date(self):
        # A single late-evening lookup misses every afternoon game: by 22:50 UTC
        # a 1pm Eastern start is over and off the board entirely.
        events = self.events()
        backfill.run_first_five(self.games(), store=self.store,
                                fetch_events=events, fetch_odds=self.odds())
        self.assertEqual(len(self.lookups), len(backfill.SNAPSHOT_INSTANTS))

    def test_a_day_game_only_on_the_early_board_is_still_found(self):
        early = backfill._snapshot_instants("2023-06-04")[0]
        report = backfill.run_first_five(
            self.games(), store=self.store,
            fetch_events=self.events(only_instant=early),
            fetch_odds=self.odds())
        self.assertEqual(report["fetched"], 1)
        self.assertEqual(report["unmatched"], 0)
        # And its odds are asked for at the instant it was actually on the board.
        self.assertEqual(self.odds_instants, [early])

    def test_the_later_instant_wins_when_a_game_is_on_both_boards(self):
        # Later is closer to first pitch, which is the price worth having.
        backfill.run_first_five(self.games(), store=self.store,
                                fetch_events=self.events(),
                                fetch_odds=self.odds())
        self.assertEqual(self.odds_instants,
                         [backfill._snapshot_instants("2023-06-04")[-1]])

    def test_the_per_game_plan_includes_the_events_lookups(self):
        plan = backfill.first_five_plan(
            [{"date": "2023-06-04"}, {"date": "2023-06-05"}])
        self.assertEqual(plan["credits_per_game"], 20)
        # Two lookups per date, because one misses the afternoon slate.
        self.assertEqual(plan["credits_events"], 4)
        self.assertEqual(plan["credits_total"], 44)

    def test_three_seasons_of_candidates_is_affordable(self):
        # The number that made the whole approach viable: every game would be
        # 145,800 credits, the scanner's ~10% is under 15,000.
        plan = backfill.first_five_plan([{"date": f"2024-06-{d:02d}"}
                                         for d in range(1, 29)] * 26)
        self.assertLess(plan["credits_total"], 15000)

    def test_a_matched_game_is_stored_with_its_event_and_snapshot(self):
        report = backfill.run_first_five(
            self.games(), store=self.store, fetch_events=self.events(),
            fetch_odds=self.odds())
        self.assertEqual(report["fetched"], 1)
        rows = backfill.read_season(2023, self.store)
        self.assertEqual(rows[0]["away_team"], "TB")
        self.assertEqual(rows[0]["snapshot_at"], "2023-06-04T22:45:00Z")

    def test_an_unmatched_game_is_reported_not_silently_dropped(self):
        # An unmatched pair is nearly always a team-code mismatch, which has
        # silently cost this project data twice before.
        report = backfill.run_first_five(
            self.games(), store=self.store,
            fetch_events=self.events((("Miami Marlins", "New York Mets"),)),
            fetch_odds=self.odds())
        self.assertEqual(report["unmatched"], 1)
        self.assertEqual(report["fetched"], 0)

    def test_a_date_outside_the_archive_is_recorded_and_never_retried(self):
        # First-five history begins in mid-May 2023, so earlier dates answer 422
        # forever. Retrying them would re-ask a dead question on every run.
        report = backfill.run_first_five(
            self.games(date="2023-04-24"), store=self.store,
            fetch_events=self.events(),
            fetch_odds=self.odds(odds_provider.MarketsUnavailableAtDate("nope")))
        self.assertEqual(report["unavailable_at_date"], 1)
        self.assertEqual(report["failed"], 0)
        again = backfill.run_first_five(
            self.games(date="2023-04-24"), store=self.store,
            fetch_events=self.events(), fetch_odds=self.odds())
        self.assertEqual(again["skipped_cached"], 1)

    def test_a_real_failure_is_counted_and_left_to_retry(self):
        report = backfill.run_first_five(
            self.games(), store=self.store, fetch_events=self.events(),
            fetch_odds=self.odds(odds_provider.OddsProviderError("boom")))
        self.assertEqual(report["failed"], 1)
        self.assertEqual(backfill.read_manifest(self.store)["snapshots"], {})

    def test_the_budget_stops_before_a_game_is_bought(self):
        report = backfill.run_first_five(
            self.games(), store=self.store, budget=5,
            fetch_events=self.events(), fetch_odds=self.odds())
        self.assertEqual(report["fetched"], 0)
        self.assertIn("would be exceeded", report["stopped_early"])
