"""src/pipeline/allsports_capture.py: discovery, phases, in-play, caps, the credit log, the row shape.

Every provider seam is injected (tests/_allsports_fixtures.FakeOdds) and every store is a temp file; nothing
here touches the network or a real data store.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import timedelta

from src.capture import budget
from src.hounds import user_engine as eng
from src.pipeline import allsports_capture as ac
from tests._allsports_fixtures import (ENV, NOW, FakeOdds, Paths, config, iso, list_item, minutes, raw_event,
                                       read_jsonl, sport_entry)

NBA = "basketball_nba"
SOCCER = "soccer_epl"


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = Paths(self._tmp.name)

    def go(self, fake, *, now=NOW, cfg=None, **kw):
        return ac.run(now=now, env=ENV, config=cfg, fetch_sports=fake.fetch_sports, list_events=fake.list_events,
                      fetch_odds=fake.fetch_odds, quota=fake.quota, **self.paths.kwargs(), **kw)

    def nba_game(self, start_in_minutes, event_id="nba1", **kw):
        return raw_event(event_id, "Boston Celtics", "New York Knicks", NOW + minutes(start_in_minutes),
                         total=(221.5, -110, -110), spread=(-4.5, -110, -110), **kw)

    def fake(self, events_by_key, sports=None, **kw):
        return FakeOdds(sports or [sport_entry(k) for k in events_by_key], events_by_key, **kw)


class Discovery(Base):
    def test_only_active_event_keys_a_family_here_buys_are_kept(self):
        sports = [
            sport_entry(NBA), sport_entry("basketball_euroleague"), sport_entry("tennis_atp_us_open", group="Tennis"),
            sport_entry("basketball_ncaab", active=False),                                  # inactive
            sport_entry("basketball_nba_championship_winner", outrights=True),              # outrights
            sport_entry("golf_masters_tournament_winner", outrights=True, group="Golf"),    # outrights
            sport_entry("americanfootball_nfl"), sport_entry("baseball_mlb"),               # bought elsewhere
            sport_entry("mma_mixed_martial_arts"),                                          # bought elsewhere
        ]
        eligible, skipped = ac.eligible_keys(sports)
        self.assertEqual(sorted(e["key"] for e in eligible),
                         ["basketball_euroleague", NBA, "tennis_atp_us_open"])
        self.assertEqual({e["key"]: e["family"] for e in eligible},
                         {NBA: "NBA", "basketball_euroleague": "BASKETBALL", "tennis_atp_us_open": "TENNIS"})
        self.assertEqual(skipped["basketball_nba_championship_winner"], "outrights")
        self.assertEqual(skipped["golf_masters_tournament_winner"], "outrights")
        self.assertTrue(skipped["americanfootball_nfl"].startswith("bought_elsewhere"))
        self.assertNotIn("basketball_ncaab", skipped)       # inactive keys are not even mentioned

    def test_a_malformed_key_is_never_bought(self):
        eligible, skipped = ac.eligible_keys([sport_entry("../etc/passwd")])
        self.assertEqual(eligible, [])
        self.assertEqual(skipped["../etc/passwd"], "invalid_key")

    def test_discovery_is_recorded_once_until_the_key_set_changes(self):
        fake = self.fake({NBA: []})
        self.go(fake)
        self.go(fake, now=NOW + minutes(13))
        self.assertEqual(len(read_jsonl(self.paths.sports)), 1)
        fake.sports.append(sport_entry("icehockey_nhl", group="Ice Hockey"))
        self.go(fake, now=NOW + minutes(26))
        rows = read_jsonl(self.paths.sports)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["families"], {"NBA": 1, "NHL": 1})


class PregameCapture(Base):
    def test_a_due_phase_buys_the_key_once_and_writes_the_multibook_shape(self):
        fake = self.fake({NBA: [self.nba_game(300)]})                  # tips off in 5 hours: t6h is due
        result = self.go(fake)
        self.assertEqual(fake.odds_calls, [(NBA, ("h2h", "spreads", "totals"), ("us",))])
        self.assertEqual(result["credits"], 3)
        rows = read_jsonl(self.paths.multibook)
        self.assertTrue(rows)
        markets = {r.get("market") for r in rows}
        self.assertEqual(markets, {None, "spreads", "totals"})       # h2h rows keep the legacy shape: no key
        for r in rows:
            self.assertEqual(r["sport"], "nba")                      # the lower-case family code
            self.assertEqual(r["league"], NBA)
            self.assertEqual(r["league_title"], NBA)
            self.assertNotIn("in_play", r)
            self.assertEqual(r["event_id"], "nba1")
            self.assertIn("observed_utc", r)
        h2h = [r for r in rows if r.get("market") is None][0]
        self.assertEqual((h2h["home_price"], h2h["away_price"]), (-120, 100))
        spread = [r for r in rows if r.get("market") == "spreads"][0]
        self.assertEqual((spread["home_line"], spread["away_line"]), ("-4.5", "4.5"))   # decimal strings
        total = [r for r in rows if r.get("market") == "totals"][0]
        self.assertEqual((total["total"], total["over_price"]), ("221.5", -110))

    def test_rows_flow_through_the_dog_engine_readers_unchanged(self):
        fake = self.fake({NBA: [self.nba_game(300)]})
        self.go(fake)
        rows = eng.load_rows("2026-10-20", ["NBA"], multibook_path=self.paths.multibook)
        self.assertTrue(rows)
        games = eng.build_games(rows, near_date="2026-10-20")
        self.assertEqual(list(games), ["nba1"])
        game = games["nba1"]
        self.assertEqual((game.sport, game.league, game.home_team), ("NBA", NBA, "Boston Celtics"))
        self.assertEqual(sorted(game.captures), ["moneyline", "spread", "total"])
        # and the window helper knows the new family's margin
        from src.pipeline import snapshots
        since, until = snapshots.window_for_date("2026-10-20", "nba")
        self.assertEqual((since, until), ("2026-10-16", "2026-10-22"))

    def test_a_second_run_buys_nothing_until_the_next_phase_opens(self):
        fake = self.fake({NBA: [self.nba_game(300)]})
        self.go(fake)
        again = self.go(fake, now=NOW + minutes(13))
        self.assertEqual(again["calls"], [])
        self.assertEqual(len(fake.odds_calls), 1)
        done = [r for r in read_jsonl(self.paths.done) if r["kind"] == "phase"]
        self.assertEqual({(r["event_id"], r["phase"]) for r in done}, {("nba1", "t24h"), ("nba1", "t6h")})
        t2h = self.go(fake, now=NOW + minutes(190))                    # 110 minutes to tip-off: t2h opens
        self.assertEqual(len(t2h["calls"]), 1)
        self.assertEqual(t2h["calls"][0]["phases_marked"], 1)
        self.assertEqual(len(fake.odds_calls), 2)

    def test_one_call_serves_every_event_of_the_key_and_marks_each_due_phase(self):
        fake = self.fake({NBA: [self.nba_game(300, "nba1"), self.nba_game(350, "nba2")]})
        result = self.go(fake)
        self.assertEqual(len(fake.odds_calls), 1)
        self.assertEqual(result["calls"][0]["phases_marked"], 4)       # t24h and t6h for each event
        self.assertEqual({r["event_id"] for r in read_jsonl(self.paths.multibook)}, {"nba1", "nba2"})

    def test_an_event_that_has_started_is_never_a_pregame_phase(self):
        fake = self.fake({NBA: [self.nba_game(-20)]})
        result = self.go(fake)
        self.assertEqual([c["kind"] for c in result["calls"]], ["inplay"])

    def test_events_beyond_the_store_horizon_are_listed_but_not_stored(self):
        start = NOW + minutes(300)
        near = raw_event("near", "A", "B", start)
        far = raw_event("far", "C", "D", NOW + timedelta(hours=60))
        rows, seen, n = ac.build_rows("2026-10-20T18:00:00+00:00", NOW, [near, far], NBA, "NBA", "NBA",
                                      ac.catalog.capture_config())
        self.assertEqual({r["event_id"] for r in rows}, {"near"})
        self.assertEqual(n, 2)
        self.assertGreater(seen, 0)

    def test_a_three_way_h2h_row_carries_the_draw_price(self):
        game = raw_event("soc1", "Arsenal", "Chelsea", NOW + minutes(300), h2h=(-110, 270), draw=240)
        fake = self.fake({SOCCER: [game]}, sports=[sport_entry(SOCCER, group="Soccer")])
        result = self.go(fake)
        self.assertEqual(fake.odds_calls, [(SOCCER, ("h2h", "totals"), ("us",))])
        rows = read_jsonl(self.paths.multibook)
        h2h = [r for r in rows if r.get("market") is None]
        self.assertTrue(h2h)
        self.assertEqual({r["draw_price"] for r in h2h}, {240})
        self.assertEqual({r["sport"] for r in rows}, {"soccer"})
        self.assertEqual(result["calls"][0]["family"], "SOCCER")

    def test_tennis_buys_h2h_only(self):
        game = raw_event("ten1", "Iga Swiatek", "Coco Gauff", NOW + minutes(300), h2h=(-1260, 700))
        fake = self.fake({"tennis_wta_wuhan": [game]}, sports=[sport_entry("tennis_wta_wuhan", group="Tennis")])
        self.go(fake)
        self.assertEqual(fake.odds_calls, [("tennis_wta_wuhan", ("h2h",), ("us",))])
        self.assertEqual({r["sport"] for r in read_jsonl(self.paths.multibook)}, {"tennis"})

    def test_soonest_start_is_bought_first_when_the_run_is_cut_short(self):
        far = raw_event("far1", "A", "B", NOW + minutes(400))
        near = raw_event("near1", "C", "D", NOW + minutes(40))
        fake = self.fake({"basketball_wnba": [far], NBA: [near]})
        result = self.go(fake, cfg=config(max_calls_per_run=1))
        self.assertEqual([c[0] for c in fake.odds_calls], [NBA])
        self.assertEqual(result["skipped"]["basketball_wnba"], "max_calls_per_run")


class InPlay(Base):
    def test_a_live_event_gets_a_cheap_h2h_snapshot_marked_in_play(self):
        fake = self.fake({NBA: [self.nba_game(-30, h2h=(220, -260))]})
        result = self.go(fake)
        self.assertEqual(fake.odds_calls, [(NBA, ("h2h",), ("us",))])
        self.assertEqual(result["credits"], 1)
        rows = read_jsonl(self.paths.multibook)
        self.assertTrue(rows)
        for r in rows:
            self.assertIs(r["in_play"], True)
            self.assertEqual(r["sport"], "nba")
            self.assertIsNone(r.get("market"))
        self.assertEqual(rows[0]["home_price"], 220)

    def test_the_in_play_cadence_is_per_key(self):
        fake = self.fake({NBA: [self.nba_game(-30)]})
        self.go(fake)
        self.go(fake, now=NOW + minutes(10))
        self.assertEqual(len(fake.odds_calls), 1)
        self.go(fake, now=NOW + minutes(31))
        self.assertEqual(len(fake.odds_calls), 2)

    def test_a_game_past_its_live_window_is_not_polled_in_play(self):
        fake = self.fake({NBA: [self.nba_game(-300)]})                   # NBA live window is 3.5 hours
        result = self.go(fake)
        self.assertEqual(result["calls"], [])

    def test_the_in_play_sub_cap_stops_in_play_but_not_pregame(self):
        # 450 credits of in-play already spent today
        with open(self.paths.credit, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"utc": "2026-10-20T10:00:00Z", "credits_remaining": 80000,
                                 "credits_used_last": 450, "caller": "allsports_capture.inplay",
                                 "budget_band": "allsports_capture"}) + "\n")
        fake = self.fake({NBA: [self.nba_game(-30)], "icehockey_nhl": [raw_event("n1", "A", "B", NOW + minutes(300))]},
                         sports=[sport_entry(NBA), sport_entry("icehockey_nhl", group="Ice Hockey")])
        result = self.go(fake)
        self.assertEqual([c[0] for c in fake.odds_calls], ["icehockey_nhl"])
        self.assertIn("sub-cap", result["skipped"][NBA])
        self.assertIsNone(result["halt"])


class CapsAndCredits(Base):
    def credit_rows(self):
        return read_jsonl(self.paths.credit)

    def test_every_call_is_logged_in_the_allsports_band_with_its_own_cost(self):
        fake = self.fake({NBA: [self.nba_game(300)]}, bill={NBA: 3})
        self.go(fake)
        rows = self.credit_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["budget_band"], budget.ALLSPORTS)
        self.assertEqual(rows[0]["credits_used_last"], 3)
        self.assertEqual(rows[0]["credits_remaining"], 89997)
        self.assertEqual(rows[0]["caller"], ac.CALLER_PREGAME)
        self.assertEqual(budget.spent_today(now=NOW, store=self.paths.credit, band=budget.ALLSPORTS), 3)
        self.assertEqual(budget.allsports_spent_today(now=NOW, store=self.paths.credit), 3)

    def test_the_vendors_billed_cost_is_what_is_logged_not_the_estimate(self):
        fake = self.fake({NBA: [self.nba_game(300)]}, bill={NBA: 2})
        result = self.go(fake)
        self.assertEqual(self.credit_rows()[0]["credits_used_last"], 2)
        self.assertEqual(result["credits"], 2)

    def test_the_daily_cap_is_a_config_value_and_stops_spending(self):
        fake = self.fake({NBA: [self.nba_game(300)], "icehockey_nhl": [raw_event("n1", "A", "B", NOW + minutes(310))]},
                         sports=[sport_entry(NBA), sport_entry("icehockey_nhl", group="Ice Hockey")])
        result = self.go(fake, cfg=config(daily_cap_credits=4))
        self.assertEqual(len(fake.odds_calls), 1)                 # 3 spent; the next 3 would pass the cap of 4
        self.assertIn("daily cap", result["halt"])
        self.assertEqual(budget.allsports_daily_cap(config(daily_cap_credits=4)), 4)

    def test_prior_spend_today_counts_against_the_cap(self):
        with open(self.paths.credit, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"utc": "2026-10-20T10:00:00Z", "credits_remaining": 80000,
                                 "credits_used_last": 1499, "caller": "allsports_capture.pregame",
                                 "budget_band": "allsports_capture"}) + "\n")
        fake = self.fake({NBA: [self.nba_game(300)]})
        result = self.go(fake)
        self.assertEqual(fake.odds_calls, [])
        self.assertIn("daily cap", result["halt"])

    def test_the_default_cap_is_fifteen_hundred(self):
        self.assertEqual(budget.allsports_daily_cap(), 1500)

    def test_the_credit_floor_stops_everything(self):
        fake = self.fake({NBA: [self.nba_game(300)]}, remaining=5002)
        result = self.go(fake)
        self.assertEqual(fake.odds_calls, [])
        self.assertIn("credit floor", result["halt"])

    def test_an_unreadable_quota_fails_closed(self):
        fake = self.fake({NBA: [self.nba_game(300)]})
        result = ac.run(now=NOW, env=ENV, fetch_sports=fake.fetch_sports, list_events=fake.list_events,
                        fetch_odds=fake.fetch_odds, quota=lambda: {"remaining": None}, **self.paths.kwargs())
        self.assertEqual(fake.odds_calls, [])
        self.assertIn("quota unreadable", result["halt"])

    def test_allsports_spend_never_counts_against_the_live_capture_envelope(self):
        fake = self.fake({NBA: [self.nba_game(300)]})
        self.go(fake)
        self.assertEqual(budget.capture_spent_today(now=NOW, store=self.paths.credit), 0)
        self.assertEqual(budget.spent_today(now=NOW, store=self.paths.credit), 3)     # whole-day total includes it

    def test_a_failed_fetch_costs_nothing_and_does_not_stop_the_other_keys(self):
        fake = self.fake({NBA: [self.nba_game(300)], "icehockey_nhl": [raw_event("n1", "A", "B", NOW + minutes(310))]},
                         sports=[sport_entry(NBA), sport_entry("icehockey_nhl", group="Ice Hockey")])
        real = fake.fetch_odds

        def flaky(key, markets, regions):
            if key == NBA:
                raise RuntimeError("odds API returned HTTP 500")
            return real(key, markets, regions)
        result = ac.run(now=NOW, env=ENV, fetch_sports=fake.fetch_sports, list_events=fake.list_events,
                        fetch_odds=flaky, quota=fake.quota, **self.paths.kwargs())
        self.assertIn("fetch error", result["skipped"][NBA])
        self.assertEqual([c["sport_key"] for c in result["calls"]], ["icehockey_nhl"])
        # the failed key's phases are NOT marked done, so the next slot retries it
        self.assertFalse([r for r in read_jsonl(self.paths.done) if r.get("sport_key") == NBA and r["kind"] == "phase"])


class Coverage(Base):
    def write_calls(self, key, regions, n, *, events=3, rows=0):
        with open(self.paths.done, "a", encoding="utf-8") as fh:
            for i in range(n):
                fh.write(json.dumps({"kind": "call", "sport_key": key, "call_kind": "pregame",
                                     "observed_utc": iso(NOW - minutes(300 - i)), "regions": regions,
                                     "markets": ["h2h"], "events": events, "rows": rows, "credits": 1}) + "\n")

    def test_a_region_that_prices_nothing_twice_hands_over_to_the_next_rung(self):
        key = "cricket_ipl"
        self.write_calls(key, ["us"], 2)
        game = raw_event("c1", "Mumbai", "Chennai", NOW + minutes(300), h2h=(-110, -110), draw=900)
        fake = self.fake({key: [game]}, sports=[sport_entry(key, group="Cricket")])
        self.go(fake)
        self.assertEqual(fake.odds_calls, [(key, ("h2h",), ("au",))])

    def test_a_key_dark_on_every_region_is_left_alone_for_a_day(self):
        key = "aussierules_afl"
        self.write_calls(key, ["us"], 2)
        self.write_calls(key, ["au"], 2)
        game = raw_event("a1", "Collingwood", "Geelong", NOW + minutes(300))
        fake = self.fake({key: [game]}, sports=[sport_entry(key, group="Aussie Rules")])
        result = self.go(fake)
        self.assertEqual(fake.odds_calls, [])
        # a day after the last attempt it is tried again, on the first rung
        later = self.go(fake, now=NOW + timedelta(hours=25))
        self.assertEqual(len(later["calls"]), 0)         # (the event has started by then; the retry rung is what matters)
        regions, note = ac.choose_regions(key, "AFL", ac.State.load(self.paths.done), NOW + timedelta(hours=25),
                                          ac.catalog.capture_config())
        self.assertEqual((regions, note), (["us"], "dark_retry"))
        regions, note = ac.choose_regions(key, "AFL", ac.State.load(self.paths.done), NOW,
                                          ac.catalog.capture_config())
        self.assertEqual((regions, note), (None, "dark_on_every_region"))

    def test_zero_events_is_not_darkness(self):
        key = NBA
        self.write_calls(key, ["us"], 3, events=0, rows=0)
        regions, _ = ac.choose_regions(key, "NBA", ac.State.load(self.paths.done), NOW, ac.catalog.capture_config())
        self.assertEqual(regions, ["us"])


class QuietKeys(Base):
    def test_a_key_with_nothing_soon_is_not_listed_again_until_it_could_matter(self):
        far = raw_event("f1", "A", "B", NOW + timedelta(days=5))
        fake = self.fake({NBA: [far]})
        self.go(fake)
        self.assertEqual(fake.event_calls, [NBA])
        self.go(fake, now=NOW + minutes(13))
        self.assertEqual(fake.event_calls, [NBA])                      # peek row says: not before ~6 hours
        peeks = [r for r in read_jsonl(self.paths.done) if r["kind"] == "peek"]
        self.assertEqual(len(peeks), 1)
        self.go(fake, now=NOW + timedelta(hours=7))
        self.assertEqual(fake.event_calls, [NBA, NBA])


class Switches(Base):
    def test_the_env_kill_switch_spends_nothing(self):
        fake = self.fake({NBA: [self.nba_game(300)]})
        result = ac.run(now=NOW, env={**ENV, "ALLSPORTS_CAPTURE": "0"}, fetch_sports=fake.fetch_sports,
                        list_events=fake.list_events, fetch_odds=fake.fetch_odds, quota=fake.quota,
                        **self.paths.kwargs())
        self.assertTrue(result["disabled"])
        self.assertEqual((fake.odds_calls, fake.event_calls), ([], []))

    def test_the_config_switch_spends_nothing(self):
        fake = self.fake({NBA: [self.nba_game(300)]})
        result = self.go(fake, cfg=config(enabled=False))
        self.assertTrue(result["disabled"])
        self.assertEqual(fake.odds_calls, [])

    def test_no_key_means_no_spend_and_no_error(self):
        fake = self.fake({NBA: [self.nba_game(300)]})
        result = ac.run(now=NOW, env={}, fetch_sports=fake.fetch_sports, list_events=fake.list_events,
                        fetch_odds=fake.fetch_odds, quota=fake.quota, **self.paths.kwargs())
        self.assertIs(result["configured"], False)
        self.assertEqual(fake.odds_calls, [])

    def test_plan_only_lists_the_plan_and_writes_and_spends_nothing(self):
        fake = self.fake({NBA: [self.nba_game(300)]})
        result = self.go(fake, plan_only=True)
        self.assertEqual(result["planned"], 1)
        self.assertEqual(result["plan"][0]["est_credits"], 3)
        self.assertEqual(fake.odds_calls, [])
        for path in (self.paths.done, self.paths.sports, self.paths.multibook, self.paths.credit):
            self.assertEqual(read_jsonl(path), [])

    def test_discovery_failing_spends_nothing(self):
        fake = self.fake({NBA: []})

        def boom():
            raise RuntimeError("odds API returned HTTP 503")
        result = ac.run(now=NOW, env=ENV, fetch_sports=boom, list_events=fake.list_events,
                        fetch_odds=fake.fetch_odds, quota=fake.quota, **self.paths.kwargs())
        self.assertIn("discovery failed", result["halt"])
        self.assertEqual(fake.odds_calls, [])


class AppendOnly(Base):
    def test_the_multibook_store_is_only_ever_appended_to(self):
        fake = self.fake({NBA: [self.nba_game(300)]})
        self.go(fake)
        with open(self.paths.multibook, "rb") as fh:
            before = fh.read()
        self.go(fake, now=NOW + minutes(190))
        with open(self.paths.multibook, "rb") as fh:
            after = fh.read()
        self.assertTrue(after.startswith(before))
        self.assertGreater(len(after), len(before))

    def test_a_ragged_final_line_costs_one_row_not_two(self):
        with open(self.paths.done, "w", encoding="utf-8") as fh:
            fh.write('{"kind": "phase", "sport_key": "x", "ev')          # an interrupted append
        fake = self.fake({NBA: [self.nba_game(300)]})
        self.go(fake)
        good = []
        for line in open(self.paths.done, encoding="utf-8").read().splitlines():
            try:
                good.append(json.loads(line)["kind"])
            except (ValueError, KeyError):
                pass            # the interrupted fragment, on a line of its own
        self.assertEqual(good.count("call"), 1)
        self.assertEqual(good.count("phase"), 2)                   # t24h and t6h: nothing was merged into the fragment


if __name__ == "__main__":
    unittest.main()
