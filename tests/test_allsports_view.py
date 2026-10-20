"""The catalog, GET /sports/now's builder, the budget band and the "No games today" path of Fire now.

Fixture rows and injected seams only; the API module is checked for importing without FastAPI.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from src.capture import budget
from src.hounds import user_engine as eng
from src.hounds.interact import fire
from src.sports import allsports_view as V
from src.sports import catalog
from tests._allsports_fixtures import NOW, iso
from tests._hounds_user_fixtures import utc

REPO = Path(__file__).resolve().parent.parent


def mrow(event_id, sport, start, observed, home="Home FC", away="Away FC", prices=((-120, 100),), league=None,
         title=None, draw=None, in_play=False, market=None):
    rows = []
    for i, (hp, ap) in enumerate(prices):
        row = {"observed_utc": iso(observed), "event_id": event_id, "commence_time": iso(start), "home_team": home,
               "away_team": away, "book": f"book_{i}", "home_price": hp, "away_price": ap}
        if sport != "mlb":
            row["sport"] = sport
        if league:
            row["league"], row["league_title"] = league, title or league
        if draw is not None:
            row["draw_price"] = draw
        if in_play:
            row["in_play"] = True
        if market:
            row["market"] = market
        rows.append(row)
    return rows


class TheCatalog(unittest.TestCase):
    def test_keys_map_to_the_longest_matching_prefix(self):
        cases = {
            "basketball_nba": "NBA", "basketball_wnba": "WNBA", "basketball_ncaab": "NCAAB",
            "basketball_euroleague": "BASKETBALL", "basketball_nbl": "BASKETBALL",
            "icehockey_nhl": "NHL", "icehockey_sweden_hockey_league": "HOCKEY",
            "americanfootball_nfl": "NFL", "americanfootball_ncaaf": "NCAAF", "americanfootball_cfl": "GRIDIRON",
            "baseball_mlb": "MLB", "baseball_kbo": "BASEBALL",
            "soccer_epl": "SOCCER", "soccer_usa_mls": "SOCCER", "tennis_atp_us_open": "TENNIS",
            "tennis_wta_wuhan": "TENNIS", "cricket_ipl": "CRICKET", "cricket_test_match": "CRICKET",
            "mma_mixed_martial_arts": "MMA", "boxing_boxing": "BOXING", "rugbyleague_nrl": "RUGBY",
            "rugbyunion_six_nations": "RUGBY", "aussierules_afl": "AFL", "lacrosse_pll": "OTHER",
            "darts_pdc": "OTHER",
        }
        for key, code in cases.items():
            self.assertEqual(catalog.family_for_key(key), code, key)

    def test_markets_h2h_everywhere_spreads_and_totals_where_the_sport_has_them(self):
        for code in catalog.family_codes():
            self.assertIn("h2h", catalog.markets_for(code), code)
        for code in ("NBA", "NHL", "NCAAF", "RUGBY", "AFL", "MLB", "NFL"):
            self.assertEqual(catalog.markets_for(code), ["h2h", "spreads", "totals"], code)
        self.assertEqual(catalog.markets_for("SOCCER"), ["h2h", "totals"])
        for code in ("TENNIS", "CRICKET", "MMA", "BOXING", "OTHER"):
            self.assertEqual(catalog.markets_for(code), ["h2h"], code)

    def test_a_catch_all_exists_and_unknown_keys_land_in_it(self):
        self.assertEqual(catalog.family_for_key("curling_world_cup"), "OTHER")
        self.assertEqual(catalog.CATCH_ALL, "OTHER")

    def test_mlb_nfl_and_mma_are_bought_by_their_own_pipelines(self):
        for code in ("MLB", "NFL", "MMA"):
            self.assertTrue(catalog.is_dedicated(code), code)
        self.assertFalse(catalog.is_dedicated("NBA"))

    def test_draws_are_possible_in_the_three_way_families_only(self):
        for code in ("SOCCER", "CRICKET", "RUGBY", "AFL", "BOXING"):
            self.assertTrue(catalog.draw_possible(code), code)
        for code in ("NBA", "NHL", "MLB", "NFL", "TENNIS"):
            self.assertFalse(catalog.draw_possible(code), code)

    def test_outrights_and_futures_are_skipped_by_name(self):
        self.assertEqual(catalog.is_skipped_key("golf_masters_tournament_winner"), "outrights")
        self.assertEqual(catalog.is_skipped_key("basketball_nba_championship_winner"), "outrights")
        self.assertEqual(catalog.is_skipped_key("soccer_epl", {"has_outrights": True}), "outrights")
        self.assertEqual(catalog.is_skipped_key("golf_pga_championship"), "not_an_event_sport")
        self.assertEqual(catalog.is_skipped_key("politics_us_presidential_election"), "not_an_event_sport")
        self.assertIsNone(catalog.is_skipped_key("soccer_epl", {"has_outrights": False, "title": "EPL"}))

    def test_the_public_catalog_lists_families_markets_and_the_dog_menu(self):
        body = {f["code"]: f for f in catalog.public_catalog()}
        self.assertEqual(body["NBA"]["markets"], ["h2h", "spreads", "totals"])
        self.assertTrue(body["NBA"]["dog_menu"])
        self.assertFalse(body["TENNIS"]["dog_menu"])
        self.assertIn("scores", body["TENNIS"]["note"].lower())
        self.assertEqual(body["SOCCER"]["label"], "Soccer")

    def test_the_catalog_file_is_valid_json_with_the_documented_keys(self):
        data = json.loads((REPO / "config" / "sports_catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(data["capture"]["daily_cap_credits"], 1500)
        for code, fam in data["families"].items():
            for key in ("label", "prefixes", "markets", "since_margin_days", "live_window_hours", "capture", "settles"):
                self.assertIn(key, fam, (code, key))
            self.assertIn(fam["capture"], ("allsports", "dedicated"))
            self.assertIn(fam["settles"], ("existing", "odds_api_scores", "none"))

    def test_a_missing_catalog_falls_back_to_mlb_and_nfl(self):
        data = catalog.load("/no/such/file.json")
        self.assertEqual(sorted(data["families"]), ["MLB", "NFL"])
        catalog.clear_cache()


class TheBudgetBand(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = os.path.join(self._tmp.name, "credit_log.jsonl")

    def write(self, *rows):
        with open(self.store, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")

    def test_the_band_is_valid_and_a_direct_sum_band(self):
        self.assertIn("allsports_capture", budget.VALID_BANDS)
        self.assertIn(budget.ALLSPORTS, budget.DIRECT_SUM_BANDS)

    def test_interleaved_allsports_rows_are_not_billed_to_the_live_capture_envelope(self):
        # live capture at 10000 -> an all-sports call (3 credits, balance 9997) -> live capture at 9990:
        # live capture spent 7 (10000 -> 9997 -> 9990 is 3 + 7; the 3 are the all-sports call's).
        self.write(
            {"utc": "2026-10-20T10:00:00Z", "credits_remaining": 10000, "credits_used_last": 3,
             "caller": "dense.run", "budget_band": "live_capture"},
            {"utc": "2026-10-20T10:01:00Z", "credits_remaining": 9997, "credits_used_last": 3,
             "caller": "allsports_capture.pregame", "budget_band": "allsports_capture"},
            {"utc": "2026-10-20T10:02:00Z", "credits_remaining": 9990, "credits_used_last": 7,
             "caller": "dense.run", "budget_band": "live_capture"})
        now = utc("2026-10-20T12:00:00Z")
        self.assertEqual(budget.capture_spent_today(now=now, store=self.store), 7)
        self.assertEqual(budget.allsports_spent_today(now=now, store=self.store), 3)
        self.assertEqual(budget.spent_today(now=now, store=self.store), 10)

    def test_a_row_with_no_remaining_is_still_summed_and_subtracted_once(self):
        self.write(
            {"utc": "2026-10-20T10:00:00Z", "credits_remaining": 10000, "credits_used_last": 3,
             "caller": "dense.run", "budget_band": "live_capture"},
            {"utc": "2026-10-20T10:01:00Z", "credits_remaining": None, "credits_used_last": 3,
             "caller": "allsports_capture.pregame", "budget_band": "allsports_capture"},
            {"utc": "2026-10-20T10:02:00Z", "credits_remaining": 9990, "credits_used_last": 7,
             "caller": "dense.run", "budget_band": "live_capture"})
        now = utc("2026-10-20T12:00:00Z")
        self.assertEqual(budget.capture_spent_today(now=now, store=self.store), 7)
        self.assertEqual(budget.allsports_spent_today(now=now, store=self.store), 3)

    def test_the_caller_prefix_reads_the_sub_caps_out_of_the_band(self):
        self.write(
            {"utc": "2026-10-20T10:00:00Z", "credits_remaining": 9000, "credits_used_last": 5,
             "caller": "allsports_capture.inplay", "budget_band": "allsports_capture"},
            {"utc": "2026-10-20T10:01:00Z", "credits_remaining": 8998, "credits_used_last": 2,
             "caller": "allsports_scores.poll", "budget_band": "allsports_capture"})
        now = utc("2026-10-20T12:00:00Z")
        self.assertEqual(budget.allsports_spent_today(now=now, store=self.store, caller_prefix="allsports_capture.inplay"), 5)
        self.assertEqual(budget.allsports_spent_today(now=now, store=self.store, caller_prefix="allsports_scores"), 2)
        self.assertEqual(budget.allsports_spent_today(now=now, store=self.store), 7)

    def test_the_guard_checks_floor_then_cap_then_sub_cap(self):
        self.write({"utc": "2026-10-20T10:00:00Z", "credits_remaining": 90000, "credits_used_last": 1000,
                    "caller": "allsports_capture.pregame", "budget_band": "allsports_capture"})
        now = utc("2026-10-20T12:00:00Z")
        ok = budget.can_spend_allsports(3, now=now, store=self.store, remaining=90000)
        self.assertTrue(ok.allowed)
        self.assertFalse(budget.can_spend_allsports(501, now=now, store=self.store, remaining=90000).allowed)
        floor = budget.can_spend_allsports(3, now=now, store=self.store, remaining=5003)
        self.assertFalse(floor.allowed)
        self.assertIn("credit floor", floor.reason)
        unread = budget.can_spend_allsports(3, now=utc("2026-10-21T12:00:00Z"), store=self.store, remaining=None)
        self.assertFalse(unread.allowed)                       # no credit-log row for that day: fails CLOSED
        self.assertIn("quota unreadable", unread.reason)
        sub = budget.can_spend_allsports(3, now=now, store=self.store, remaining=90000, sub_cap=1000,
                                         caller_prefix="allsports_capture")
        self.assertIn("sub-cap", sub.reason)
        self.assertTrue(budget.can_spend_allsports(0, now=now, store=self.store, remaining=None).allowed)

    def test_status_reports_the_allsports_band(self):
        self.write({"utc": "2026-10-20T10:00:00Z", "credits_remaining": 90000, "credits_used_last": 12,
                    "caller": "allsports_capture.pregame", "budget_band": "allsports_capture"})
        status = budget.status(now=utc("2026-10-20T12:00:00Z"), store=self.store)
        self.assertEqual(status["allsports"], {"spent_today": 12, "cap": 1500})


def standard_now_rows():
    rows = []
    # NBA game in play: started 40 min ago, a snapshot 5 minutes ago; two books, best prices differ
    rows += mrow("nba_live", "nba", NOW - timedelta(minutes=40), NOW - timedelta(minutes=5), "Boston Celtics",
                 "New York Knicks", prices=((-300, 240), (-280, 260)), league="basketball_nba", title="NBA",
                 in_play=True)
    # an older snapshot of the same game must lose to the newer one
    rows += mrow("nba_live", "nba", NOW - timedelta(minutes=40), NOW - timedelta(hours=3), "Boston Celtics",
                 "New York Knicks", prices=((-150, 130),), league="basketball_nba", title="NBA")
    # tennis match tonight (5 hours away), pre-game
    rows += mrow("ten1", "tennis", NOW + timedelta(hours=5), NOW - timedelta(minutes=20), "Coco Gauff",
                 "Iga Swiatek", prices=((-1260, 700),), league="tennis_wta_wuhan", title="WTA Wuhan")
    # soccer 30 hours away: not in the 24h list, but it sets the family's next start
    rows += mrow("soc_far", "soccer", NOW + timedelta(hours=30), NOW - timedelta(minutes=10), "Arsenal", "Chelsea",
                 prices=((-110, 270),), league="soccer_epl", title="EPL", draw=240)
    # soccer live with a stale last snapshot: NOT live (no recent in-play price)
    rows += mrow("soc_stale", "soccer", NOW - timedelta(minutes=60), NOW - timedelta(hours=2), "Leeds", "Burnley",
                 prices=((120, 200),), league="soccer_epl", title="EPL", draw=230)
    # a cricket match live now
    rows += mrow("cri1", "cricket", NOW - timedelta(hours=2), NOW - timedelta(minutes=30), "Mumbai", "Chennai",
                 prices=((-130, 110),), league="cricket_ipl", title="IPL", draw=900, in_play=True)
    # an MLB game (no sport field) starting in 3 hours
    rows += mrow("mlb1", "mlb", NOW + timedelta(hours=3), NOW - timedelta(minutes=15), "Seattle Mariners",
                 "Boston Red Sox", prices=((-140, 120),))
    # a spreads row of a live game is not a moneyline and must be ignored
    rows += mrow("nba_live", "nba", NOW - timedelta(minutes=40), NOW - timedelta(minutes=1), prices=((-110, -110),),
                 league="basketball_nba", market="spreads")
    return rows


class TheSportsNowBoard(unittest.TestCase):
    def body(self, rows=None, scores=None):
        return V.sports_now(NOW, rows=standard_now_rows() if rows is None else rows, scores_index=scores or {})

    def family(self, body, code):
        return next(f for f in body["families"] if f["code"] == code)

    def test_the_shape_and_catalog_order(self):
        body = self.body()
        self.assertEqual(set(body), {"generated_utc", "families", "paper_only"})
        self.assertEqual(body["generated_utc"], "2026-10-20T18:00:00Z")
        order = [f["code"] for f in body["families"]]
        self.assertEqual(order, ["MLB", "NBA", "SOCCER", "TENNIS", "CRICKET"])
        for f in body["families"]:
            self.assertEqual(set(f), {"code", "label", "live", "upcoming_24h", "next_start_utc"})

    def test_a_live_event_carries_its_newest_best_prices(self):
        live = self.family(self.body(), "NBA")["live"]
        self.assertEqual(len(live), 1)
        event = live[0]
        for key in ("event_id", "league_title", "home", "away", "start_utc", "in_play", "best_price_home",
                    "best_price_away"):
            self.assertIn(key, event)
        self.assertEqual((event["event_id"], event["league_title"], event["in_play"]), ("nba_live", "NBA", True))
        self.assertEqual((event["home"], event["away"]), ("Boston Celtics", "New York Knicks"))
        self.assertEqual((event["best_price_home"], event["best_price_away"]), (-280, 260))     # the best of two books
        self.assertEqual(event["start_utc"], iso(NOW - timedelta(minutes=40)))

    def test_a_game_with_no_recent_in_play_price_is_not_called_live(self):
        soccer = self.family(self.body(), "SOCCER")
        self.assertEqual(soccer["live"], [])
        self.assertEqual([e["event_id"] for e in soccer["upcoming_24h"]], [])
        self.assertEqual(soccer["next_start_utc"], iso(NOW + timedelta(hours=30)))

    def test_upcoming_is_the_next_24_hours_only_and_next_start_is_the_earliest(self):
        body = self.body()
        tennis = self.family(body, "TENNIS")
        self.assertEqual([e["event_id"] for e in tennis["upcoming_24h"]], ["ten1"])
        self.assertEqual(tennis["upcoming_24h"][0]["best_price_home"], -1260)
        self.assertEqual(tennis["next_start_utc"], iso(NOW + timedelta(hours=5)))
        self.assertEqual(self.family(body, "MLB")["upcoming_24h"][0]["home"], "Seattle Mariners")

    def test_a_three_way_event_shows_the_draw_price_and_a_two_way_one_does_not(self):
        cricket = self.family(self.body(), "CRICKET")["live"][0]
        self.assertEqual(cricket["best_price_draw"], 900)
        self.assertNotIn("best_price_draw", self.family(self.body(), "NBA")["live"][0])

    def test_a_score_is_attached_only_when_the_scores_store_has_one(self):
        scores = {"nba_live": {"home_score": 61, "away_score": 58, "completed": False,
                               "observed_utc": iso(NOW - timedelta(minutes=10))}}
        event = self.family(self.body(scores=scores), "NBA")["live"][0]
        self.assertEqual(event["score"], {"home": 61, "away": 58, "detail": "Live", "completed": False,
                                          "as_of": iso(NOW - timedelta(minutes=10))})
        self.assertNotIn("score", self.family(self.body(), "NBA")["live"][0])
        stale = {"nba_live": {"home_score": 61, "away_score": 58, "completed": False,
                              "observed_utc": iso(NOW - timedelta(hours=9))}}
        self.assertNotIn("score", self.family(self.body(scores=stale), "NBA")["live"][0])

    def test_families_with_nothing_are_left_out_and_an_empty_store_is_an_empty_board(self):
        self.assertEqual(self.body(rows=[])["families"], [])

    def test_a_finished_game_is_not_listed(self):
        rows = mrow("old", "nba", NOW - timedelta(hours=9), NOW - timedelta(hours=9, minutes=5), prices=((-120, 100),),
                    league="basketball_nba")
        self.assertEqual(self.body(rows=rows)["families"], [])

    def test_no_api_is_called_per_request_and_the_reader_streams_the_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "odds_multibook.jsonl")
            with open(path, "w", encoding="utf-8") as fh:
                for r in standard_now_rows():
                    fh.write(json.dumps(r, separators=(",", ":")) + "\n")
            with mock.patch("urllib.request.urlopen", side_effect=AssertionError("no network in /sports/now")):
                body = V.sports_now(NOW, path=path, scores_index={})
        self.assertEqual([f["code"] for f in body["families"]], ["MLB", "NBA", "SOCCER", "TENNIS", "CRICKET"])

    def test_the_cached_wrapper_remembers_a_read(self):
        V.clear_cache()
        calls = []
        with mock.patch.object(V, "sports_now", side_effect=lambda now=None, **kw: calls.append(1) or {"families": []}):
            V.cached_sports_now()
            V.cached_sports_now()
        V.clear_cache()
        self.assertEqual(calls, [1])


class TheUiContract(unittest.TestCase):
    """Contract additions from the UI worker (2026-10-19)."""

    def test_the_builder_menu_offers_any_sport_with_the_exact_entry(self):
        from src.hounds import user_spec
        for menu in (user_spec.builder_menu(), user_spec.menu()):
            self.assertIn({"value": "ANY", "label": "Any sport", "any": True}, menu["sports"])
            self.assertEqual(sum(1 for s in menu["sports"] if s.get("any")), 1)

    def test_every_market_and_every_condition_names_the_families_it_supports(self):
        from src.hounds import user_spec
        menu = user_spec.builder_menu()
        dog_sports = list(user_spec.SPORTS)
        for market in menu["markets"]:
            self.assertIn("sports", market, market["value"])
            self.assertEqual(market["sports"], ["MLB"] if market["kind"] == "prop" else dog_sports, market["value"])
        for market in user_spec.menu()["markets"]:
            self.assertEqual(market["sports"], dog_sports)
        conditions = {c["id"]: c for c in menu["conditions"]}
        for cond in conditions.values():
            self.assertTrue(cond["sports"], cond["id"])
            self.assertTrue(set(cond["sports"]) <= set(dog_sports), cond["id"])
        # generic conditions list every family; the stat conditions stay MLB/NFL only
        for cid in ("role", "steam", "day_of_week", "time_of_day", "coin_flip"):
            self.assertEqual(conditions[cid]["sports"], dog_sports, cid)
        for cid in ("rest_days", "streak", "head_to_head", "scoring_rate", "league_rank", "team_is"):
            self.assertEqual(conditions[cid]["sports"], ["MLB", "NFL"], cid)
        for cid in ("temperature", "wind_speed", "roof", "travel_miles", "player_is"):
            self.assertEqual(conditions[cid]["sports"], ["MLB"], cid)

    def test_sports_now_event_ids_are_unique_across_every_list(self):
        rows = standard_now_rows()
        # the same event seen by several captures and books must still be ONE event
        rows += mrow("nba_live", "nba", NOW - timedelta(minutes=40), NOW - timedelta(minutes=5), "Boston Celtics",
                     "New York Knicks", prices=((-310, 235),), league="basketball_nba", title="NBA", in_play=True)
        body = V.sports_now(NOW, rows=rows, scores_index={})
        ids = [e["event_id"] for f in body["families"] for key in ("live", "upcoming_24h") for e in f[key]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 4)

    def test_a_score_is_an_object_with_home_away_and_detail(self):
        rows = standard_now_rows()
        scores = {"nba_live": {"home_score": 61, "away_score": 58, "completed": False,
                               "observed_utc": iso(NOW - timedelta(minutes=10))}}
        event = V.sports_now(NOW, rows=rows, scores_index=scores)["families"][1]["live"][0]
        self.assertEqual((event["score"]["home"], event["score"]["away"], event["score"]["detail"]),
                         (61, 58, "Live"))
        scores["nba_live"]["completed"] = True
        done = V.sports_now(NOW, rows=rows, scores_index=scores)["families"][1]["live"][0]
        self.assertEqual(done["score"]["detail"], "Final")


class LiveElsewhere(unittest.TestCase):
    def test_other_sports_live_are_counted_and_named_busiest_first(self):
        body = V.sports_now(NOW, rows=standard_now_rows(), scores_index={})
        out = V.live_elsewhere(["MLB", "NFL"], payload=body)
        self.assertEqual(out["games"], 2)
        self.assertEqual({f["code"] for f in out["families"]}, {"NBA", "CRICKET"})
        self.assertEqual(out["text"], "Live now in other sports: 2 games (nba, cricket).")

    def test_the_dogs_own_sports_are_not_other_sports(self):
        body = V.sports_now(NOW, rows=standard_now_rows(), scores_index={})
        out = V.live_elsewhere(["NBA", "CRICKET"], payload=body)
        self.assertEqual((out["games"], out["text"]), (0, ""))

    def test_one_game_reads_singular(self):
        body = V.sports_now(NOW, rows=standard_now_rows(), scores_index={})
        self.assertEqual(V.live_elsewhere(["MLB", "NBA"], payload=body)["text"],
                         "Live now in other sports: 1 game (cricket).")


class TheEmptyBoardPathOfFireNow(unittest.TestCase):
    """slate_view / fire_user: the NEXT game in the dog's sports, and what is live elsewhere."""

    TUESDAY = utc("2026-10-20T14:00:00Z")

    def setUp(self):
        fire.clear_cache()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger = os.path.join(self._tmp.name, "l.jsonl")
        patcher = mock.patch.object(eng, "ledger_path", lambda p=None: p or self.ledger)
        patcher.start()
        self.addCleanup(patcher.stop)

    def thursday_game(self):
        start = utc("2026-10-22T23:10:00Z")
        return [("Boston Red Sox @ Seattle Mariners", start, start - timedelta(minutes=120))]

    def test_nothing_today_names_the_next_game(self):
        view = fire.slate_view(self.TUESDAY, [], self.thursday_game())
        self.assertEqual(view["today_state"], "none")
        self.assertEqual(view["line"], "No games today. Next slate: Thursday. "
                                       "Next game: Boston Red Sox @ Seattle Mariners (7:10 pm ET).")
        self.assertEqual(view["next_game"]["game"], "Boston Red Sox @ Seattle Mariners")
        self.assertIsNone(view["other_live"])

    def test_and_says_what_is_live_in_other_sports(self):
        other = {"games": 7, "families": [], "text": "Live now in other sports: 7 games (tennis, cricket)."}
        view = fire.slate_view(self.TUESDAY, [], self.thursday_game(), other)
        self.assertTrue(view["line"].endswith("Live now in other sports: 7 games (tennis, cricket)."), view["line"])
        self.assertEqual(view["other_live"]["games"], 7)

    def test_with_no_game_on_file_at_all_it_still_names_what_is_live_elsewhere(self):
        other = {"games": 2, "families": [], "text": "Live now in other sports: 2 games (nba)."}
        view = fire.slate_view(self.TUESDAY, [], [], other)
        self.assertEqual(view["line"], "No games today, and none are on the stored boards yet. "
                                       "Live now in other sports: 2 games (nba).")

    def test_other_sports_are_not_mentioned_when_the_dog_has_games_today(self):
        today = [("A @ B", utc("2026-10-20T23:10:00Z"), utc("2026-10-20T21:10:00Z"))]
        other = {"games": 7, "families": [], "text": "Live now in other sports: 7 games (tennis)."}
        view = fire.slate_view(self.TUESDAY, [], today, other)
        self.assertNotIn("other sports", view["line"])
        self.assertIsNone(view["other_live"])

    def test_zero_other_games_adds_nothing(self):
        view = fire.slate_view(self.TUESDAY, [], self.thursday_game(), {"games": 0, "families": [], "text": ""})
        self.assertNotIn("other sports", view["line"])

    def test_fire_user_asks_the_other_sports_board_only_when_nothing_is_on_today(self):
        from tests.test_hounds_interact_slate import dog_of, nfl_rows
        asked = []

        def other_live(sports, at):
            asked.append(tuple(sports))
            return {"games": 3, "families": [], "text": "Live now in other sports: 3 games (soccer)."}
        out = fire.fire_user(dog_of(), now=self.TUESDAY, rows_for=lambda date, sports: nfl_rows()
                             if date == "2026-10-22" else [], ledger=self.ledger, other_live=other_live)
        self.assertEqual(out["slate"]["today_state"], "none")
        self.assertIn("Live now in other sports: 3 games (soccer).", out["slate"]["line"])
        self.assertEqual(len(asked), 1)

    def test_an_unreadable_other_sports_board_is_never_fatal(self):
        from tests.test_hounds_interact_slate import dog_of

        def broken(sports, at):
            raise OSError("store unreadable")
        out = fire.fire_user(dog_of(), now=self.TUESDAY, rows_for=lambda date, sports: [], ledger=self.ledger,
                             other_live=broken)
        self.assertEqual(out["slate"]["line"], "No games today, and none are on the stored boards yet.")

    def test_injected_stores_never_trigger_the_real_default_lookup(self):
        from tests.test_hounds_interact_slate import dog_of
        with mock.patch.object(V, "live_elsewhere", side_effect=AssertionError("must not read the real store")):
            out = fire.fire_user(dog_of(), now=self.TUESDAY, rows_for=lambda date, sports: [], ledger=self.ledger)
        self.assertEqual(out["slate"]["today_state"], "none")


try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheRoutes(unittest.TestCase):
    """api/sports.py, called directly (this repo's api test style). Skipped where FastAPI is absent."""

    def test_sports_now_returns_the_cached_board(self):
        from api import sports as api_sports
        payload = {"generated_utc": "x", "families": [], "paper_only": True}
        with mock.patch.object(V, "cached_sports_now", return_value=payload):
            self.assertEqual(api_sports.get_sports_now(), payload)

    def test_sports_catalog_lists_the_families(self):
        from api import sports as api_sports
        body = api_sports.get_sports_catalog()
        self.assertIn("NBA", [f["code"] for f in body["families"]])
        self.assertTrue(body["paper_only"])

    def test_the_app_mounts_both_routes(self):
        import api.app as app_mod
        src = (REPO / "api" / "app.py").read_text(encoding="utf-8")
        self.assertIn("app.include_router(sports_public_router)", src)
        self.assertIn("app.include_router(sports_router, dependencies=_authed_paid)", src)
        self.assertTrue(hasattr(app_mod, "sports_router") and hasattr(app_mod, "sports_public_router"))
        self.assertEqual({r.path for r in app_mod.sports_router.routes}, {"/sports/now"})
        self.assertEqual({r.path for r in app_mod.sports_public_router.routes}, {"/sports/catalog"})


class NoFastapiSafe(unittest.TestCase):
    """Linux CI has no FastAPI: every module with logic must import without it."""

    def test_the_logic_modules_import_with_fastapi_hidden(self):
        code = (
            "import sys\n"
            "for n in ('fastapi','starlette','pydantic','uvicorn'): sys.modules[n] = None\n"
            "from src.sports import catalog, allsports_view\n"
            "from src.pipeline import allsports_capture, allsports_scores\n"
            "from src.hounds import user_spec, user_settle, user_engine\n"
            "from src.hounds.interact import fire, ask_eval\n"
            "assert catalog.family_for_key('soccer_epl') == 'SOCCER'\n"
            "assert allsports_view.sports_now.__name__ == 'sports_now'\n"
            "print('ok')\n")
        done = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(REPO)!r})\n" + code],
                              capture_output=True, text=True, cwd=str(REPO), timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-800:])
        self.assertIn("ok", done.stdout)


if __name__ == "__main__":
    unittest.main()
