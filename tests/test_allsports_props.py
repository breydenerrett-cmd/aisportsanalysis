"""src/pipeline/allsports_props.py: player props for NBA, NFL, NHL and NCAAF.

Every provider seam is injected (FakeProps below) and every store is a temp file: nothing here touches the network,
a real data store or the real API key.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src import cli
from src.capture import budget
from src.pipeline import allsports_props as ap
from src.pipeline import batter_props, creditlog, store_archive
from src.providers import odds as odds_provider
from src.sports import catalog

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 20, 18, 0, 0, tzinfo=timezone.utc)
ENV = {"ODDS_API_KEY": "test-key-not-real"}
NBA, NHL, NFL, NCAAF = "basketball_nba", "icehockey_nhl", "americanfootball_nfl", "americanfootball_ncaaf"


def iso(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def minutes(n):
    return timedelta(minutes=n)


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def list_item(event_id, start, home="Boston Celtics", away="New York Knicks"):
    return {"id": event_id, "sport_key": "x", "commence_time": iso(start), "home_team": home, "away_team": away}


def prop_payload(event_id, start, markets, *, books=("fanduel", "draftkings"), home="Boston Celtics",
                 away="New York Knicks"):
    """One /events/{id}/odds payload: two players per market, an Over/Under (or Yes) pair per book."""
    bookmakers = []
    for book in books:
        out_markets = []
        for market in markets:
            outcomes = []
            for player, point in (("Jayson Tatum", 27.5), ("Jalen Brunson", 24.5)):
                if "anytime" in market:
                    outcomes.append({"name": "Yes", "description": player, "price": 150})
                else:
                    outcomes.append({"name": "Over", "description": player, "price": -115, "point": point})
                    outcomes.append({"name": "Under", "description": player, "price": -105, "point": point})
            out_markets.append({"key": market, "last_update": iso(start - minutes(200)), "outcomes": outcomes})
        bookmakers.append({"key": book, "title": book, "last_update": iso(start - minutes(200)),
                           "markets": out_markets})
    return {"id": event_id, "sport_key": "x", "commence_time": iso(start), "home_team": home, "away_team": away,
            "bookmakers": bookmakers}


class FakeProps:
    """The injected seams for allsports_props.run: event lists, per-event prop boards, the quota."""

    def __init__(self, events_by_key, remaining=90000, bill=None, empty=(), fail=None):
        self.events_by_key = events_by_key              # sport_key -> [(event_id, start)]
        self.remaining = remaining
        self.bill = bill or {}
        self.empty = set(empty)                         # event ids whose board is empty
        self.fail = fail or {}                          # event id -> exception to raise
        self.list_calls = []
        self.fetch_calls = []

    def list_events(self, key):
        self.list_calls.append(key)
        return [list_item(eid, start) for eid, start in self.events_by_key.get(key, [])]

    def fetch(self, key, event_id, markets, regions):
        self.fetch_calls.append((key, event_id, tuple(markets), tuple(regions)))
        if event_id in self.fail:
            raise self.fail[event_id]
        cost = self.bill.get(event_id, len(markets) * len(regions))
        self.remaining -= cost
        start = dict(self.events_by_key[key])[event_id]
        payload = prop_payload(event_id, start, [] if event_id in self.empty else markets)
        return payload, {"remaining": self.remaining, "last": cost}

    def quota(self):
        return {"remaining": self.remaining}


def config(**capture):
    cfg = copy.deepcopy(catalog.load())
    cfg["capture"].update(capture)
    return cfg


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = self._tmp.name
        self.rows = os.path.join(root, "props.jsonl")
        self.done = os.path.join(root, "props_done.jsonl")
        self.credit = os.path.join(root, "credit_log.jsonl")

    def go(self, fake, *, now=NOW, cfg=None, env=ENV, **kw):
        return ap.run(now=now, env=env, config=cfg, list_events=fake.list_events, fetch_event_odds=fake.fetch,
                      quota=fake.quota, rows_path=self.rows, done_path=self.done, credit_store=self.credit, **kw)

    def phases(self):
        return [(r["event_id"], r["phase"], r["status"]) for r in read_jsonl(self.done) if r["kind"] == "phase"]


class TheWindows(Base):
    def test_a_game_five_hours_out_buys_t6h_with_every_market_once(self):
        fake = FakeProps({NBA: [("nba1", NOW + minutes(300))]})
        result = self.go(fake)
        self.assertEqual(fake.fetch_calls, [(NBA, "nba1", tuple(catalog.props_families()["NBA"]["markets"]), ("us",))])
        self.assertEqual(result["credits"], 5)
        self.assertEqual([c["phase"] for c in result["calls"]], ["t6h"])
        self.assertEqual(self.phases(), [("nba1", "t6h", "done")])

    def test_a_second_run_buys_nothing_until_the_next_window_opens(self):
        fake = FakeProps({NBA: [("nba1", NOW + minutes(300))]})
        self.go(fake)
        again = self.go(fake, now=NOW + minutes(13))
        self.assertEqual(again["calls"], [])
        self.assertEqual(len(fake.fetch_calls), 1)
        t2h = self.go(fake, now=NOW + minutes(190))               # 110 minutes to the start: t2h
        self.assertEqual([c["phase"] for c in t2h["calls"]], ["t2h"])
        t30 = self.go(fake, now=NOW + minutes(275))               # 25 minutes to the start: t30m
        self.assertEqual([c["phase"] for c in t30["calls"]], ["t30m"])
        self.assertEqual([p[1] for p in self.phases()], ["t6h", "t2h", "t30m"])
        self.assertEqual(len(fake.fetch_calls), 3)

    def test_a_window_that_closed_unbought_is_recorded_missed_and_never_filled(self):
        fake = FakeProps({NBA: [("nba1", NOW + minutes(100))]})   # first seen at t-100m: t6h is over
        result = self.go(fake)
        self.assertEqual([c["phase"] for c in result["calls"]], ["t2h"])
        self.assertIn(("nba1", "t6h", "missed"), self.phases())
        self.assertEqual(result["missed"], 1)
        self.assertEqual(len(fake.fetch_calls), 1)                # one snapshot, labelled with the window it is in
        again = self.go(fake, now=NOW + minutes(14))
        self.assertEqual(again["calls"], [])

    def test_a_game_outside_the_lookahead_and_a_game_that_started_are_never_bought(self):
        fake = FakeProps({NBA: [("far", NOW + minutes(30 * 60)), ("live", NOW - minutes(20)),
                                ("soon", NOW + minutes(20))]})
        result = self.go(fake)
        self.assertEqual([c["event_id"] for c in result["calls"]], ["soon"])
        self.assertEqual([c["phase"] for c in result["calls"]], ["t30m"])

    def test_soonest_game_first_across_leagues(self):
        fake = FakeProps({NBA: [("nba_late", NOW + minutes(300))], NHL: [("nhl_soon", NOW + minutes(150))]})
        result = self.go(fake)
        self.assertEqual([c["event_id"] for c in result["calls"]], ["nhl_soon", "nba_late"])

    def test_each_family_buys_its_own_markets(self):
        fake = FakeProps({NBA: [("a", NOW + minutes(300))], NHL: [("b", NOW + minutes(300))],
                          NFL: [("c", NOW + minutes(300))], NCAAF: [("d", NOW + minutes(300))]})
        self.go(fake)
        got = {call[0]: call[2] for call in fake.fetch_calls}
        for code, fam in catalog.props_families().items():
            self.assertEqual(got[fam["sport_key"]], tuple(fam["markets"]), code)

    def test_plan_only_lists_events_but_spends_and_writes_nothing(self):
        fake = FakeProps({NBA: [("nba1", NOW + minutes(300))]})
        result = self.go(fake, plan_only=True)
        self.assertEqual(result["planned"], 1)
        self.assertEqual(result["est_credits"], 5)
        self.assertEqual(fake.fetch_calls, [])
        for path in (self.rows, self.done, self.credit):
            self.assertFalse(os.path.exists(path), path)

    def test_a_killed_run_resumes_from_the_done_store(self):
        fake = FakeProps({NBA: [("nba1", NOW + minutes(300)), ("nba2", NOW + minutes(310))]})
        with mock.patch.object(ap, "_append_rows", wraps=ap._append_rows) as spy:
            self.go(fake)
        self.assertTrue(spy.called)
        fresh = FakeProps({NBA: [("nba1", NOW + minutes(300)), ("nba2", NOW + minutes(310))]})
        again = self.go(fresh)                                    # a new process, the same done file
        self.assertEqual(again["calls"], [])
        self.assertEqual(fresh.fetch_calls, [])

    def test_max_calls_per_run(self):
        fake = FakeProps({NBA: [(f"g{i}", NOW + minutes(300 + i)) for i in range(5)]})
        result = self.go(fake, cfg=config(props_max_calls_per_run=2))
        self.assertEqual(len(result["calls"]), 2)
        self.assertEqual(sum(1 for why in result["skipped"].values() if why == "max_calls_per_run"), 3)


class TheRows(Base):
    def setUp(self):
        super().setUp()
        self.start = datetime(2026, 10, 21, 0, 30, tzinfo=timezone.utc)     # 8:30 pm Eastern on the 20th
        self.fake = FakeProps({NBA: [("nba1", self.start)], NHL: [("nhl1", self.start)]})
        self.go(self.fake, now=self.start - minutes(300))
        self.stored = read_jsonl(self.rows)

    def test_every_row_has_the_documented_fields(self):
        self.assertTrue(self.stored)
        for row in self.stored:
            self.assertEqual(sorted(row), sorted(ap.ROW_FIELDS))

    def test_row_values(self):
        row = next(r for r in self.stored if r["league"] == NBA and r["market"] == "player_points"
                   and r["player"] == "Jayson Tatum" and r["side"] == "Over" and r["book"] == "fanduel")
        self.assertEqual((row["line"], row["price"], row["sport"], row["capture_phase"]), ("27.5", -115, "nba", "t6h"))
        self.assertEqual(row["selection"], "Jayson Tatum:Over")
        self.assertEqual(row["event_id"], "nba1")
        self.assertEqual(row["game_date"], "2026-10-20")                    # Eastern slate date, like the MLB store
        self.assertEqual(row["home_team"], "Boston Celtics")
        self.assertEqual(row["observed_utc"], iso(self.start - minutes(300)))
        self.assertTrue(row["book_last_update"])

    def test_an_anytime_market_has_no_line(self):
        fake = FakeProps({NHL: [("nhl2", NOW + minutes(300))]})
        self.go(fake)
        anytime = [r for r in read_jsonl(self.rows) if r["market"] == "player_goal_scorer_anytime"]
        self.assertTrue(anytime)
        for row in anytime:
            self.assertEqual((row["side"], row["line"]), ("Yes", None))

    def test_the_row_shape_is_the_mlb_prop_stores_shape_plus_sport_and_league(self):
        start = NOW + minutes(300)
        payload = prop_payload("e1", start, ["batter_hits"])
        mlb = batter_props._project(payload, {}, "2026-10-20T18:00:00Z", "2026-10-20", "gate", ("batter_hits",))
        ours = ap.project(payload, "2026-10-20T18:00:00Z", "gate", "NBA", NBA, ["batter_hits"])
        self.assertTrue(mlb and ours)
        self.assertEqual(set(ours[0]), set(mlb[0]) | {"sport", "league"})
        self.assertEqual({k: v for k, v in ours[0].items() if k not in ("sport", "league")}, mlb[0])

    def test_a_market_nobody_asked_for_is_not_projected(self):
        payload = prop_payload("e1", NOW + minutes(300), ["player_points", "player_blocks"])
        rows = ap.project(payload, "T", "t6h", "NBA", NBA, ["player_points"])
        self.assertEqual({r["market"] for r in rows}, {"player_points"})

    def test_an_outcome_without_a_player_is_skipped(self):
        payload = prop_payload("e1", NOW + minutes(300), ["player_points"])
        payload["bookmakers"][0]["markets"][0]["outcomes"].append({"name": "Over", "price": -110, "point": 1.5})
        rows = ap.project(payload, "T", "t6h", "NBA", NBA, ["player_points"])
        self.assertTrue(all(r["player"] for r in rows))

    def test_rows_are_appended_never_rewritten_and_every_snapshot_is_whole(self):
        first = len(read_jsonl(self.rows))
        self.go(self.fake, now=self.start - minutes(100))                     # t2h
        both = read_jsonl(self.rows)
        self.assertEqual(len(both), first * 2)
        phases = [r["capture_phase"] for r in both]
        self.assertEqual(phases[:first], ["t6h"] * first)
        self.assertEqual(set(phases[first:]), {"t2h"})

    def test_iter_rows_reads_the_archive_and_the_hot_file_as_one_store(self):
        before = list(ap.iter_rows(self.rows))
        self.go(self.fake, now=self.start - minutes(100))
        total = list(ap.iter_rows(self.rows))
        report = store_archive.rotate(self.rows, keep_days=0, now=datetime(2026, 10, 25, tzinfo=timezone.utc),
                                      threshold_bytes=1)
        self.assertTrue(report.get("rotated") or report.get("segment"), report)
        self.assertEqual(list(ap.iter_rows(self.rows)), total)
        self.assertGreater(len(total), len(before))


class TheCreditLog(Base):
    def test_every_call_is_logged_in_the_props_band_with_the_vendors_own_cost(self):
        fake = FakeProps({NBA: [("nba1", NOW + minutes(300))]}, bill={"nba1": 4})
        self.go(fake)
        logged = read_jsonl(self.credit)
        self.assertEqual(len(logged), 1)
        self.assertEqual((logged[0]["budget_band"], logged[0]["credits_used_last"], logged[0]["caller"]),
                         (budget.ALLSPORTS_PROPS, 4, "allsports_props.t6h"))
        self.assertEqual(logged[0]["credits_remaining"], 90000 - 4)
        self.assertEqual(read_jsonl(self.done)[-1]["credits"], 4)             # the marker repeats the vendor's number

    def test_a_missing_billing_header_falls_back_to_the_estimate(self):
        fake = FakeProps({NBA: [("nba1", NOW + minutes(300))]})
        original = fake.fetch

        def no_last(*a):
            payload, usage = original(*a)
            return payload, {"remaining": usage["remaining"], "last": None}

        result = ap.run(now=NOW, env=ENV, list_events=fake.list_events, fetch_event_odds=no_last, quota=fake.quota,
                        rows_path=self.rows, done_path=self.done, credit_store=self.credit)
        self.assertEqual(result["credits"], 5)

    def test_the_props_band_is_a_direct_sum_band_with_its_own_cap_reading(self):
        self.assertIn(budget.ALLSPORTS_PROPS, budget.VALID_BANDS)
        self.assertIn(budget.ALLSPORTS_PROPS, budget.DIRECT_SUM_BANDS)
        fake = FakeProps({NBA: [("nba1", NOW + minutes(300))]})
        self.go(fake)
        self.assertEqual(budget.allsports_props_spent_today(now=NOW, store=self.credit), 5)
        self.assertEqual(budget.allsports_spent_today(now=NOW, store=self.credit), 0)    # the other band is untouched
        self.assertEqual(budget.spent_today(now=NOW, store=self.credit, band=budget.ALLSPORTS_PROPS), 5)
        self.assertEqual(budget.capture_spent_today(now=NOW, store=self.credit), 0)       # nor the pre-game envelope

    def test_the_all_sports_band_does_not_eat_the_props_cap(self):
        creditlog.log(90000, 1500, "allsports_capture.pregame", store=self.credit, now=NOW,
                      budget_band=budget.ALLSPORTS)
        fake = FakeProps({NBA: [("nba1", NOW + minutes(300))]})
        result = self.go(fake)
        self.assertEqual(result["credits"], 5)
        self.assertIsNone(result["halt"])

    def test_status_reports_the_props_band(self):
        self.assertIn("allsports_props", budget.status(now=NOW, store=self.credit))


class FloorAndCaps(Base):
    def test_the_floor_stops_everything_before_a_fetch(self):
        fake = FakeProps({NBA: [("nba1", NOW + minutes(300))]}, remaining=5004)      # 5004 - 5 <= 5000
        result = self.go(fake)
        self.assertEqual(fake.fetch_calls, [])
        self.assertIn("credit floor", result["halt"])
        self.assertFalse(os.path.exists(self.rows))
        self.assertEqual(self.phases(), [])                                          # not marked done: the next run may buy

    def test_just_above_the_floor_buys(self):
        fake = FakeProps({NBA: [("nba1", NOW + minutes(300))]}, remaining=5006)
        self.assertEqual(len(self.go(fake)["calls"]), 1)

    def test_an_unreadable_quota_fails_closed(self):
        fake = FakeProps({NBA: [("nba1", NOW + minutes(300))]})

        def broken():
            raise odds_provider.OddsProviderError("no route")

        result = ap.run(now=NOW, env=ENV, list_events=fake.list_events, fetch_event_odds=fake.fetch, quota=broken,
                        rows_path=self.rows, done_path=self.done, credit_store=self.credit)
        self.assertEqual(fake.fetch_calls, [])
        self.assertIn("quota unreadable", result["halt"])

    def test_the_daily_cap_is_a_config_value_and_stops_the_run(self):
        fake = FakeProps({NBA: [("a", NOW + minutes(300)), ("b", NOW + minutes(301)), ("c", NOW + minutes(302))]})
        result = self.go(fake, cfg=config(props_daily_cap_credits=10))
        self.assertEqual(len(result["calls"]), 2)                                    # 5 + 5 = 10
        self.assertIn("props daily cap", result["halt"])
        again = self.go(fake, now=NOW + minutes(15), cfg=config(props_daily_cap_credits=10))
        self.assertEqual(again["calls"], [])                                         # same UTC day: still capped
        next_day = self.go(fake, now=NOW + timedelta(days=1) - minutes(300) + minutes(299),
                           cfg=config(props_daily_cap_credits=10))
        self.assertIsNone(next_day["halt"])

    def test_the_default_cap_is_1200(self):
        self.assertEqual(catalog.props_daily_cap_credits(), 1200)
        self.assertEqual(budget.allsports_props_daily_cap(), 1200)
        self.assertEqual(catalog.props_daily_cap_credits({"capture": {}, "families": {"X": {}}}), 1200)

    def test_a_decision_below_the_cap_is_allowed_and_explains_itself(self):
        decision = budget.can_spend_allsports_props(5, now=NOW, store=self.credit, remaining=90000)
        self.assertTrue(decision.allowed)
        self.assertIn("of 1200", decision.reason)
        self.assertTrue(budget.can_spend_allsports_props(0, now=NOW, store=self.credit, remaining=1).allowed)


class KillSwitches(Base):
    def setUp(self):
        super().setUp()
        self.fake = FakeProps({NBA: [("nba1", NOW + minutes(300))]})

    def assert_off(self, result):
        self.assertTrue(result["disabled"])
        self.assertEqual((self.fake.list_calls, self.fake.fetch_calls), ([], []))
        for path in (self.rows, self.done, self.credit):
            self.assertFalse(os.path.exists(path), path)

    def test_allsports_props_zero(self):
        for value in ("0", "false", "off", "no", " 0 "):
            with self.subTest(value=value):
                self.assert_off(self.go(self.fake, env=dict(ENV, ALLSPORTS_PROPS=value)))

    def test_the_all_sports_master_switch_stops_props_too(self):
        self.assert_off(self.go(self.fake, env=dict(ENV, ALLSPORTS_CAPTURE="0")))

    def test_the_config_flag(self):
        self.assert_off(self.go(self.fake, cfg=config(props_enabled=False)))

    def test_any_other_value_leaves_it_on(self):
        result = self.go(self.fake, env=dict(ENV, ALLSPORTS_PROPS="1"))
        self.assertEqual(len(result["calls"]), 1)

    def test_no_api_key_buys_nothing(self):
        result = self.go(self.fake, env={})
        self.assertIs(result.get("configured"), False)
        self.assertEqual(self.fake.fetch_calls, [])


class ErrorsAndQuietGames(Base):
    def test_a_fetch_error_is_recorded_and_retried_at_most_three_times_then_missed(self):
        boom = odds_provider.OddsProviderError("odds API returned HTTP 500")
        fake = FakeProps({NBA: [("nba1", NOW + minutes(300))]}, fail={"nba1": boom})
        for n in range(4):
            self.go(fake, now=NOW + minutes(n))
        errors = [r for r in read_jsonl(self.done) if r["kind"] == "error"]
        self.assertEqual(len(errors), 3)
        self.assertEqual(len(fake.fetch_calls), 3)
        self.assertIn(("nba1", "t6h", "missed"), self.phases())
        self.assertFalse(os.path.exists(self.credit))                                  # a failed fetch bills and logs nothing

    def test_a_422_is_surfaced_with_an_escalate_line_and_bills_nothing(self):
        boom = odds_provider.OddsProviderError("odds API rejected the request (HTTP 422); check the markets")
        fake = FakeProps({NBA: [("nba1", NOW + minutes(300))]}, fail={"nba1": boom})
        result = self.go(fake)
        text = "\n".join(ap.summary_lines(result))
        self.assertIn("ESCALATE", text)
        self.assertIn("props_markets", text)
        self.assertEqual(result["credits"], 0)

    def test_quota_exhausted_halts_the_run(self):
        boom = odds_provider.OddsProviderError("odds API quota exhausted (HTTP 429) -- check remaining credits")
        fake = FakeProps({NBA: [("a", NOW + minutes(300)), ("b", NOW + minutes(301))]}, fail={"a": boom})
        result = self.go(fake)
        self.assertIn("quota exhausted", result["halt"])
        self.assertEqual(len(fake.fetch_calls), 1)

    def test_a_game_with_no_props_is_bought_twice_then_left_alone(self):
        fake = FakeProps({NCAAF: [("cfb1", NOW + minutes(300))]}, empty=["cfb1"])
        self.go(fake)                                                                 # t6h: empty
        self.go(fake, now=NOW + minutes(190))                                         # t2h: empty
        third = self.go(fake, now=NOW + minutes(275))                                 # t30m: dark, not bought
        self.assertEqual(len(fake.fetch_calls), 2)
        self.assertEqual(third["calls"], [])
        done = [r for r in read_jsonl(self.done) if r["kind"] == "phase" and r["status"] == "missed"]
        self.assertTrue(any("dark" in r["reason"] for r in done))

    def test_a_game_that_gets_props_later_resets_the_streak(self):
        state = ap.State([{"kind": "call", "sport_key": NBA, "event_id": "e", "stored": 0},
                          {"kind": "call", "sport_key": NBA, "event_id": "e", "stored": 12}])
        self.assertEqual(state.empty_streak[(NBA, "e")], 0)

    def test_one_league_failing_to_list_does_not_stop_the_others(self):
        fake = FakeProps({NHL: [("nhl1", NOW + minutes(300))]})
        original = fake.list_events

        def flaky(key):
            if key == NBA:
                raise odds_provider.OddsProviderError("boom")
            return original(key)

        result = ap.run(now=NOW, env=ENV, list_events=flaky, fetch_event_odds=fake.fetch, quota=fake.quota,
                        rows_path=self.rows, done_path=self.done, credit_store=self.credit)
        self.assertEqual([c["sport_key"] for c in result["calls"]], [NHL])
        self.assertIn(NBA, result["skipped"])


class QuietLeaguesAreNotRelisted(Base):
    def test_a_league_with_nothing_inside_the_lookahead_is_peeked_then_skipped_until_it_could_matter(self):
        fake = FakeProps({NBA: [("later", NOW + minutes(30 * 60))]})
        self.go(fake)
        self.assertEqual(fake.list_calls.count(NBA), 1)
        peeks = [r for r in read_jsonl(self.done) if r["kind"] == "peek" and r["sport_key"] == NBA]
        self.assertEqual(len(peeks), 1)
        self.go(fake, now=NOW + minutes(15))
        self.assertEqual(fake.list_calls.count(NBA), 1)                               # skipped: not due yet
        self.go(fake, now=NOW + minutes(185))                                         # past the 3 hour recheck
        self.assertEqual(fake.list_calls.count(NBA), 2)

    def test_a_league_with_a_game_inside_the_lookahead_is_listed_every_run(self):
        fake = FakeProps({NBA: [("soon", NOW + minutes(300))]})
        self.go(fake)
        self.go(fake, now=NOW + minutes(15))
        self.assertEqual(fake.list_calls.count(NBA), 2)


class TheProviderCall(unittest.TestCase):
    def test_it_asks_the_per_event_endpoint_with_validated_parts(self):
        with mock.patch.object(odds_provider, "_get_json_with_usage",
                               return_value=({"id": "x"}, {"remaining": 1, "used": 2, "last": 5})) as get:
            payload, usage = odds_provider.fetch_sport_event_odds_with_usage(
                NBA, "0123456789abcdef0123456789abcdef", ["player_points", "player_assists"], ("us",), env=ENV)
        path, params = get.call_args[0][0], get.call_args[0][1]
        self.assertEqual(path, f"sports/{NBA}/events/0123456789abcdef0123456789abcdef/odds")
        self.assertEqual((params["markets"], params["regions"], params["oddsFormat"]),
                         ("player_points,player_assists", "us", "american"))
        self.assertEqual(usage["last"], 5)

    def test_bad_parts_are_refused_before_any_request(self):
        with mock.patch.object(odds_provider, "_get_json_with_usage") as get:
            for args in ((NBA, "../etc", ["player_points"], ("us",)),
                         (NBA, "0123456789abcdef", ["Player Points"], ("us",)),
                         (NBA, "0123456789abcdef", [], ("us",)),
                         (NBA, "0123456789abcdef", ["player_points"], ("mars",)),
                         ("../x", "0123456789abcdef", ["player_points"], ("us",))):
                with self.subTest(args=args), self.assertRaises(odds_provider.OddsProviderError):
                    odds_provider.fetch_sport_event_odds_with_usage(*args, env=ENV)
            get.assert_not_called()

    def test_no_key_is_not_configured(self):
        with self.assertRaises(odds_provider.NotConfigured):
            odds_provider.fetch_sport_event_odds_with_usage(NBA, "0123456789abcdef", ["player_points"], env={})


class TheConfig(unittest.TestCase):
    def test_four_families_each_with_markets_of_a_valid_shape(self):
        fams = catalog.props_families()
        self.assertEqual(sorted(fams), ["NBA", "NCAAF", "NFL", "NHL"])
        for code, fam in fams.items():
            self.assertTrue(fam["markets"], code)
            self.assertEqual(len(set(fam["markets"])), len(fam["markets"]), code)
            self.assertTrue(all(odds_provider.valid_prop_market(m) for m in fam["markets"]), code)
            self.assertTrue(all(m.startswith("player_") for m in fam["markets"]), code)
            self.assertIn(fam["sport_key"], catalog.family(code)["prefixes"], code)
            self.assertEqual(catalog.family_for_key(fam["sport_key"]), code)

    def test_the_cap_sits_in_the_capture_block_of_the_config_file(self):
        data = json.loads((ROOT / "config" / "sports_catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(data["capture"]["props_daily_cap_credits"], 1200)
        self.assertEqual(data["capture"]["props_phases_minutes"], {"t6h": 360, "t2h": 120, "t30m": 30})

    def test_the_default_credit_estimate_stays_inside_the_cap_on_a_heavy_saturday(self):
        # 8 NBA + 8 NHL + 30 college games with props, 3 windows each, at the configured market counts.
        fams = catalog.props_families()
        saturday = 3 * (8 * len(fams["NBA"]["markets"]) + 8 * len(fams["NHL"]["markets"])
                        + 30 * len(fams["NCAAF"]["markets"]))
        self.assertLess(saturday, catalog.props_daily_cap_credits())


class TheStoresAreWiredIn(unittest.TestCase):
    def test_the_rows_file_is_a_registered_rotatable_store(self):
        cfg = store_archive.ROTATABLE_STORES["allsports_props"]
        self.assertEqual(cfg["stamp_field"], "observed_utc")
        self.assertEqual(Path(cfg["path"]()).name, "allsports_props.jsonl")
        self.assertEqual(Path(cfg["path"]()), ap.DEFAULT_ROWS_PATH)

    def test_both_stores_are_protected_from_tests_writing_to_the_real_files(self):
        import tests
        names = {p.name for p in tests.PROTECTED_STORES}
        self.assertTrue({"allsports_props.jsonl", "allsports_props_done.jsonl"} <= names)

    def test_the_default_paths_are_the_documented_ones(self):
        self.assertEqual(ap.DEFAULT_ROWS_PATH.name, "allsports_props.jsonl")
        self.assertEqual(ap.DEFAULT_DONE_PATH.name, "allsports_props_done.jsonl")
        self.assertEqual(ap.DEFAULT_DONE_PATH.parent.name, "processed")


class GitAndImageGuards(unittest.TestCase):
    def test_gitignore_lets_both_stores_through(self):
        lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        for name in ("allsports_props_done.jsonl", "allsports_props.jsonl"):
            self.assertIn(f"!data/processed/{name}", lines)

    @unittest.skipUnless(shutil.which("git") and (ROOT / ".git").exists(), "no git checkout")
    def test_git_itself_does_not_ignore_them_but_still_ignores_an_unlisted_neighbour(self):
        def ignored(path):
            done = subprocess.run(["git", "check-ignore", "-q", path], cwd=str(ROOT), capture_output=True)
            return done.returncode == 0

        self.assertFalse(ignored("data/processed/allsports_props_done.jsonl"))
        self.assertFalse(ignored("data/processed/allsports_props.jsonl"))
        self.assertFalse(ignored("data/processed/archive/allsports_props/0001_2026-10-20_2026-10-21.jsonl.gz"))
        self.assertTrue(ignored("data/processed/allsports_props_scratch.jsonl"))

    def test_the_image_leaves_the_props_out_and_keeps_everything_else_it_had(self):
        from tests.test_image_ships_ufc_data import _rules, excluded_from_build_context
        rules = _rules(ROOT / ".dockerignore")
        for path in ("data/processed/allsports_props.jsonl", "data/processed/allsports_props_done.jsonl",
                     "data/processed/archive/allsports_props/0001_2026-10-20_2026-10-21.jsonl.gz"):
            self.assertTrue(excluded_from_build_context(path, rules), path)
        for path in ("data/processed/odds_multibook.jsonl", "data/processed/allsports_capture_done.jsonl",
                     "data/processed/archive/odds_multibook/0001_2026-10-20_2026-10-21.jsonl.gz",
                     "data/processed/batter_props.jsonl"):
            self.assertFalse(excluded_from_build_context(path, rules), path)

    def test_nothing_serves_the_props_so_the_dockerfile_copies_nothing_for_them(self):
        dockerfile = (ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
        self.assertNotIn("allsports_props", dockerfile)
        served = [p for p in (ROOT / "api").rglob("*.py") if "allsports_props" in p.read_text(encoding="utf-8")]
        self.assertEqual(served, [])


class TheSlotScript(unittest.TestCase):
    TEXT = (ROOT / "scripts" / "capture_slot.sh").read_text(encoding="utf-8")

    @classmethod
    def code(cls):
        return [l for l in cls.TEXT.splitlines() if l.strip() and not l.strip().startswith("#")]

    def test_the_props_step_has_a_timeout_and_cannot_cost_the_slot(self):
        line = next(l for l in self.code() if "src.cli allsports props" in l)
        self.assertTrue(line.strip().startswith("timeout "), line)
        self.assertTrue(line.rstrip().endswith("|| true"), line)

    def test_the_props_step_runs_before_the_files_are_staged(self):
        self.assertLess(self.TEXT.index("src.cli allsports props"), self.TEXT.index("STAGE_PATHS=\"\""))
        self.assertGreater(self.TEXT.index("src.cli allsports props"), self.TEXT.index("src.cli allsports capture"))

    def test_the_mlb_box_and_play_by_play_steps_use_the_requested_arguments_and_timeouts(self):
        mlb = next(l for l in self.code() if "datasvc mlbbox refresh" in l and "timeout" in l)
        self.assertIn("--min-age-minutes 180 --max-requests 120", mlb)
        pbp = next(l for l in self.code() if "pbp-fill" in l and "timeout" in l)
        self.assertIn("--limit 40", pbp)
        for line in (mlb, pbp):
            self.assertRegex(line, r"^\s*timeout \d+ python3 -m src\.cli datasvc ")
        for chunk in ("datasvc mlbbox refresh --min-age-minutes", "datasvc all pbp-fill --limit 40"):
            continuation = self.TEXT[self.TEXT.index(chunk):].split("\n")[1]
            self.assertTrue(continuation.rstrip().endswith("|| true"), continuation)

    def test_the_script_still_parses(self):
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("no bash")
        done = subprocess.run([bash, "-n", str(ROOT / "scripts" / "capture_slot.sh")], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    @classmethod
    def gate_function(cls):
        start = cls.TEXT.index("_datasvc_local_cache() {")
        return cls.TEXT[start:cls.TEXT.index("\n}\n", start) + 3]

    def run_gate(self, cache_exists, env_value=None):
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("no bash")
        with tempfile.TemporaryDirectory() as tmp:
            if cache_exists:
                Path(tmp, "data", "datasvc", "mlb").mkdir(parents=True)
                Path(tmp, "data", "datasvc", "mlb", "MANIFEST.json").write_text("{}", encoding="utf-8")
            env = dict(os.environ)
            env.pop("DATASVC_LOCAL_CACHE", None)
            if env_value is not None:
                env["DATASVC_LOCAL_CACHE"] = env_value
            script = self.gate_function() + '\nif _datasvc_local_cache "data/datasvc/mlb/MANIFEST.json"; then echo RUN; else echo SKIP; fi\n'
            done = subprocess.run([bash, "-c", script], cwd=tmp, capture_output=True, text=True, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def test_the_local_cache_steps_run_only_where_the_cache_persists(self):
        self.assertEqual(self.run_gate(cache_exists=False), "SKIP")            # a fresh GitHub runner
        self.assertEqual(self.run_gate(cache_exists=True), "RUN")              # a machine that kept its checkout
        self.assertEqual(self.run_gate(cache_exists=False, env_value="1"), "RUN")
        self.assertEqual(self.run_gate(cache_exists=True, env_value="0"), "SKIP")
        self.assertEqual(self.run_gate(cache_exists=True, env_value="auto"), "RUN")


class TheCommand(unittest.TestCase):
    def test_allsports_props_is_a_cli_subcommand_and_plan_prints_the_plan(self):
        fake_result = {"observed_utc": "T", "listed": 1, "planned": 1, "est_credits": 5, "calls": [], "credits": 0,
                       "rows": 0, "missed": 0, "skipped": {}, "errors": [], "halt": None,
                       "plan": [{"sport_key": NBA, "event_id": "e1", "phase": "t6h", "markets": ["player_points"],
                                 "regions": ["us"], "est_credits": 5}]}
        with mock.patch.object(ap, "run", return_value=fake_result) as run:
            with mock.patch("builtins.print") as out:
                code = cli.main(["allsports", "props", "--plan"])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertTrue(run.call_args.kwargs["plan_only"])
        printed = "\n".join(str(c.args[0]) for c in out.call_args_list if c.args)
        self.assertIn("plan basketball_nba e1 t6h", printed)

    def test_a_crash_is_an_error_exit_not_a_traceback(self):
        with mock.patch.object(ap, "run", side_effect=RuntimeError("boom")):
            with mock.patch("sys.stderr"):
                self.assertEqual(cli.main(["allsports", "props"]), cli.EXIT_ERROR)


if __name__ == "__main__":
    unittest.main()
