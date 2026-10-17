"""The NFL packet: what it holds, what it refuses to hold, and what it says it could not use.

Offline and injected: a temp folder holds the synthetic league of tests/_nfl_world.py, the odds rows
are built by hand, and the clock is an argument. Nothing here reads the repo's data.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.analyst import analyst as A
from src.analyst import ledger, nfl_packet
from src.analyst import packet as packet_mod
from tests import nfl_analyst_fixtures as F


class Env(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.store = F.make_store(Path(cls._tmp.name) / "league")
        cls.bare = F.make_store(Path(cls._tmp.name) / "league_no_injuries", injuries=False)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def build(self, **kw):
        return F.build(self.store, **kw)

    def missing(self, packet, item=None):
        return [m for m in packet["missing"] if item is None or m["item"] == item]


class WhatItHolds(Env):
    def test_it_prices_the_moneyline_the_spread_and_the_total_with_every_books_quote(self):
        p = self.build()
        self.assertEqual([s["slot_id"] for s in p["slots"]], ["moneyline", "spread", "total"])
        for slot, market in p["markets"].items():
            self.assertEqual(market["slot_id"], slot)
            for opt in market["options"]:
                self.assertEqual(opt["books"], 3, (slot, opt["selection"]))
                for q in opt["quotes"]:
                    self.assertEqual(set(q), {"book", "price", "captured_utc"})
                    self.assertEqual(q["captured_utc"], "2025-10-26T16:51:16Z")
                self.assertIsNotNone(opt["best"])

    def test_the_consensus_is_the_mean_of_each_books_own_de_vig_and_the_pair_sums_to_one(self):
        p = self.build()
        for market in p["markets"].values():
            a, b = (o["fair_probability"] for o in market["options"])
            self.assertAlmostEqual(a + b, 1.0, places=3)
            self.assertGreaterEqual(a, b)                       # the lean is the likelier side, first
        ml = p["markets"]["moneyline"]
        self.assertEqual((ml["lean"], ml["options"][1]["selection"]), ("KC", "BUF"))

    def test_a_spread_selection_names_its_side_and_its_own_signed_number(self):
        p = self.build()
        spread = p["markets"]["spread"]
        self.assertEqual(sorted(o["selection"] for o in spread["options"]), ["BUF +3.5", "KC -3.5"])
        by_side = {o["side"]: o for o in spread["options"]}
        self.assertEqual((by_side["away"]["line"], by_side["home"]["line"]), (3.5, -3.5))
        total = p["markets"]["total"]
        self.assertEqual(sorted(o["selection"] for o in total["options"]), ["Over 47.5", "Under 47.5"])

    def test_the_main_number_is_the_one_most_books_quote_and_the_others_are_counted(self):
        rows = F.odds_rows()
        odd = [r for r in rows if r.get("market") == "spreads" and r["book"] == "betmgm"][0]
        odd["away_line"], odd["home_line"] = "4", "-4"
        p = self.build(rows=rows)
        spread = p["markets"]["spread"]
        self.assertEqual({o["selection"] for o in spread["options"]}, {"BUF +3.5", "KC -3.5"})
        self.assertEqual(spread["context"]["books_on_this_number"], 2)
        self.assertEqual(spread["context"]["books_on_other_numbers"], 1)

    def test_it_says_where_the_number_was_first_captured_so_a_move_can_be_discussed(self):
        early = F.odds_rows(captured="2025-10-22T09:00:00.000000+00:00")
        for r in early:
            if r.get("market") == "spreads":
                r["away_line"], r["home_line"] = "2.5", "-2.5"
            if r.get("market") == "totals":
                r["total"] = "46.5"
        p = self.build(rows=early + F.odds_rows())
        ctx = p["markets"]["spread"]["context"]
        self.assertEqual((ctx["away_number_first_captured"], ctx["first_captured_utc"]),
                         (2.5, "2025-10-22T09:00:00Z"))
        self.assertEqual(p["markets"]["total"]["context"]["number_first_captured"], 46.5)
        self.assertEqual(p["markets"]["spread"]["options"][0]["line"] in (3.5, -3.5), True)  # the current number

    def test_the_sections_carry_form_rest_travel_quarterback_injuries_and_head_to_head(self):
        p = self.build()
        self.assertEqual(set(p["sections"]), {"schedule", "away", "home", "matchup", "reference"})
        away, home = p["sections"]["away"]["values"], p["sections"]["home"]["values"]
        self.assertEqual((away["team"], home["team"]), ("BUF", "KC"))
        for side in (away, home):
            self.assertEqual(set(side["form"]), {"last_3", "last_5", "season_to_date"})
            self.assertEqual(side["form"]["last_3"]["games"], 3)
            self.assertEqual(len(side["last_three"]), 3)
            self.assertIn("days_since_last_game", side["rest"])
            self.assertIn("miles_from_home_base", side["travel"])
        self.assertEqual(home["travel"]["miles_from_home_base"], 0.0)
        self.assertEqual(home["qb"]["listed_for_this_game"]["projected"], True)
        self.assertEqual(away["injuries"]["skill_players_listed"][0]["name"], "Bee Quarterback")
        h2h = p["sections"]["matchup"]["values"]["head_to_head"]
        self.assertIsInstance(h2h["meetings"], int)
        self.assertEqual(p["sections"]["matchup"]["values"]["differentials"]["rest_days_since_last_game"]["diff"],
                         (home["rest"]["days_since_last_game"] - away["rest"]["days_since_last_game"]))

    def test_a_difference_is_home_minus_away_and_the_packet_says_so(self):
        p = self.build()
        d = p["sections"]["matchup"]["values"]["differentials"]["form_last_3_points_for_per_game"]
        self.assertAlmostEqual(d["diff"], d["home"] - d["away"], places=3)
        self.assertTrue(any("home minus away" in line for line in p["how_to_read"]))

    def test_the_scoring_facts_that_key_numbers_rest_on_are_in_the_packet_and_no_frequency_is(self):
        ref = self.build()["sections"]["reference"]["values"]
        self.assertEqual(ref["key_numbers"], [3, 6, 7, 10, 14])
        self.assertEqual((ref["scoring"]["field_goal"], ref["scoring"]["touchdown"]), (3, 6))
        text = json.dumps(self.build()["sections"]["reference"]).lower()
        self.assertNotIn("percent", text)
        self.assertNotIn("%", text)

    def test_the_game_block_is_a_whitelist_and_never_carries_a_score(self):
        game = self.build()["game"]
        self.assertEqual(set(game), {"game_id", "date", "season", "week", "game_type", "away", "home",
                                     "away_name", "home_name", "kickoff_utc", "state", "stadium",
                                     "neutral_site"})
        self.assertEqual((game["state"], game["kickoff_utc"], game["date"]), ("pending", F.KICKOFF, F.DATE))
        self.assertEqual((game["away_name"], game["home_name"]), ("Buffalo Bills", "Kansas City Chiefs"))

    def test_it_is_the_kind_of_packet_the_analyst_treats_as_having_a_case_against(self):
        p = self.build()
        self.assertTrue(A.is_mlb_packet(p))
        self.assertEqual(A.schema_for(p), A.MLB_RESPONSE_SCHEMA)

    def test_it_is_deterministic_and_does_not_depend_on_the_order_of_the_rows(self):
        a = self.build()
        b = self.build(rows=list(reversed(F.odds_rows())))
        self.assertEqual(packet_mod.packet_hash(a), packet_mod.packet_hash(b))
        self.assertEqual(json.dumps(a), json.dumps(self.build()))


class PointInTime(Env):
    def test_a_quote_captured_after_the_packet_was_built_is_dropped(self):
        late = F.odds_rows(captured="2025-10-26T18:30:00.000000+00:00")
        p = self.build(rows=F.odds_rows() + late)
        stamps = {q["captured_utc"] for m in p["markets"].values() for o in m["options"] for q in o["quotes"]}
        self.assertEqual(stamps, {"2025-10-26T16:51:16Z"})

    def test_a_quote_captured_at_or_after_the_start_is_dropped_even_when_the_packet_is_built_later(self):
        after = F.odds_rows(captured="2025-10-26T20:25:00+00:00")
        p = self.build(rows=after, built_at="2025-10-26T21:00:00Z")
        self.assertEqual(p["markets"], {})
        self.assertEqual({m["item"] for m in self.missing(p) if m["kind"] == "absent"} >= {"moneyline", "spread", "total"},
                         True)

    def test_the_feed_starting_the_game_earlier_than_the_schedule_cuts_quotes_at_the_earlier_time(self):
        moved = F.odds_rows(captured="2025-10-26T19:50:00+00:00", commence="2025-10-26T19:30:00Z")
        p = self.build(rows=F.odds_rows() + moved, built_at="2025-10-26T20:00:00Z")
        stamps = {q["captured_utc"] for m in p["markets"].values() for o in m["options"] for q in o["quotes"]}
        self.assertEqual(stamps, {"2025-10-26T16:51:16Z"})
        self.assertTrue(any(m["item"] == "game.kickoff" and "earlier is used" in m["reason"] for m in p["missing"]))

    def test_a_quote_that_cannot_be_dated_is_dropped(self):
        rows = F.odds_rows()
        for r in rows:
            r["observed_utc"] = None
        self.assertEqual(self.build(rows=rows)["markets"], {})

    def test_form_is_as_of_the_packet_not_the_kickoff_so_a_game_finished_after_the_freeze_is_not_in_it(self):
        # BUF played SEA on 2025-10-19 at 13:30Z; a packet built mid-game must not count that result
        mid = self.build(rows=[], built_at="2025-10-19T15:00:00Z")
        full = self.build()
        self.assertEqual(mid["sections"]["away"]["values"]["last_three"][0]["week"], 5)
        self.assertEqual(full["sections"]["away"]["values"]["last_three"][0]["week"], 7)
        self.assertEqual(mid["sections"]["away"]["as_of"], "2025-10-19T15:00:00Z")

    def test_the_game_s_own_result_never_reaches_the_packet(self):
        # the same game, once played (the store now holds a score): nothing of it may appear
        with tempfile.TemporaryDirectory() as d:
            store = F.make_store(Path(d))
            row = store.game_by_id()[F.GAME_ID]
            row.update(status="final", away_score=77, home_score=3)
            p = F.build(store)
            text = json.dumps(p)
            self.assertNotIn("77", [str(v) for _p, v in packet_mod.iter_leaves(p)])
            self.assertNotIn('"away_score"', text.split('"head_to_head"')[0])
            self.assertEqual(p["game"]["state"], "final")

    def test_the_listed_quarterback_is_dropped_when_the_schedule_was_fetched_after_the_packet(self):
        p = self.build(built_at="2025-10-19T15:00:00Z", rows=[])
        for side in ("away", "home"):
            self.assertNotIn("listed_for_this_game", p["sections"][side]["values"]["qb"])
        self.assertTrue(any(m["item"] == "KC.qb" and "after this packet was built" in m["reason"] for m in p["missing"]))

    def test_injury_rows_first_fetched_after_the_packet_withdraw_the_teams_report(self):
        with tempfile.TemporaryDirectory() as d:
            store = F.make_store(Path(d))
            for row in store.injuries:
                if row["game_id"] == F.GAME_ID and row["team"] == "KC":
                    row["fetched_utc"] = "2025-10-26T19:00:00Z"
            p = F.build(store)
        self.assertNotIn("injuries", p["sections"]["home"]["values"])
        self.assertIn("injuries", p["sections"]["away"]["values"])
        gone = [m for m in p["missing"] if m["item"] == "KC.injuries"]
        self.assertEqual(len(gone), 1)
        self.assertIn("first fetched after this packet was built", gone[0]["reason"])

    def test_the_schedule_s_own_market_is_never_used(self):
        # the world's game row carries spread_line 3.5 and moneylines; with no odds rows there is no market
        p = self.build(rows=[])
        self.assertEqual(p["markets"], {})
        self.assertNotIn("market", p["sections"])
        self.assertNotIn("spread_line", json.dumps(p))


class WhatItSaysItCouldNotUse(Env):
    def test_every_missing_entry_has_a_typed_reason(self):
        p = self.build()
        for m in p["missing"]:
            self.assertEqual(set(m), {"item", "kind", "reason"})
            self.assertIn(m["kind"], ("absent", "stale", "thin"))
            self.assertTrue(m["reason"].strip())

    def test_props_and_weather_are_absent_and_say_why(self):
        p = self.build()
        self.assertEqual([m["kind"] for m in self.missing(p, "props")], ["absent"])
        self.assertIn("no NFL player-prop prices", self.missing(p, "props")[0]["reason"])
        self.assertEqual([m["kind"] for m in self.missing(p, "weather")], ["absent"])

    def test_a_dome_does_not_get_a_weather_gap(self):
        with tempfile.TemporaryDirectory() as d:
            store = F.make_store(Path(d))
            store.game_by_id()[F.GAME_ID]["roof"] = "dome"
            p = F.build(store)
        self.assertEqual(self.missing(p, "weather"), [])

    def test_an_unknown_roof_is_missing(self):
        with tempfile.TemporaryDirectory() as d:
            store = F.make_store(Path(d))
            store.game_by_id()[F.GAME_ID]["roof"] = None
            p = F.build(store)
        self.assertEqual([m["kind"] for m in self.missing(p, "venue.roof")], ["absent"])

    def test_a_market_with_no_quotes_is_absent_and_has_no_slot(self):
        rows = [r for r in F.odds_rows() if r.get("market") != "spreads"]
        p = self.build(rows=rows)
        self.assertNotIn("spread", p["markets"])
        self.assertEqual([s["slot_id"] for s in p["slots"]], ["moneyline", "total"])
        self.assertEqual([m["kind"] for m in self.missing(p, "spread")], ["absent"])

    def test_one_sided_quotes_make_no_slot(self):
        rows = F.odds_rows()
        for r in rows:
            if r.get("market") == "totals":
                r["under_price"] = None
        self.assertNotIn("total", self.build(rows=rows)["markets"])

    def test_a_stale_quote_is_flagged_stale(self):
        p = self.build(built_at="2025-10-26T19:45:00Z")           # the quotes are 174 minutes old: not yet stale
        self.assertEqual([m for m in p["missing"] if m["kind"] == "stale"], [])
        old = self.build(rows=F.odds_rows(captured="2025-10-26T09:00:00+00:00"))   # 8 hours old
        stale = [m for m in old["missing"] if m["kind"] == "stale"]
        self.assertEqual({m["item"] for m in stale}, {"moneyline", "spread", "total"})
        self.assertIn("minutes old", stale[0]["reason"])

    def test_a_week_with_no_injury_report_in_the_store_is_missing_not_zero(self):
        p = F.build(self.bare)
        for side in ("away", "home"):
            self.assertNotIn("injuries", p["sections"][side]["values"])
        gone = [m for m in p["missing"] if m["item"].endswith(".injuries")]
        self.assertEqual({m["item"] for m in gone}, {"BUF.injuries", "KC.injuries"})
        self.assertTrue(all(m["kind"] == "absent" and "week 8" in m["reason"] for m in gone))

    def test_early_season_samples_are_called_thin(self):
        # before week 3 of 2025 neither club has three finished games this season
        p = self.build(rows=[], built_at="2025-09-10T12:00:00Z")
        thin = [m for m in p["missing"] if m["kind"] == "thin"]
        self.assertTrue(thin)
        self.assertTrue(any("very small sample" in m["reason"] or "fewer than its" in m["reason"] for m in thin))

    def test_the_neutral_venue_quirk_in_the_data_is_passed_on_not_hidden(self):
        p = self.build()
        self.assertTrue(any("venue" in m["reason"] and m["item"].startswith("BUF.") for m in p["missing"]))

    def test_the_limits_say_what_is_not_covered(self):
        limits = " ".join(self.build()["limits"])
        for needle in ("point spread", "player props", "Weather forecasts", "projection", "neutral-site"):
            self.assertIn(needle, limits)


class WhatItRefuses(Env):
    def test_a_game_that_is_not_in_the_store_is_an_error(self):
        with self.assertRaises(nfl_packet.NflPacketError):
            nfl_packet.build_packet(self.store, "2099_01_AAA_BBB", built_at=F.BUILT_AT)

    def test_a_built_at_that_is_not_a_time_is_an_error(self):
        with self.assertRaises(ValueError):
            nfl_packet.build_packet(self.store, F.GAME_ID, built_at="yesterday-ish")

    def test_rows_for_another_game_or_a_rematch_weeks_away_are_not_this_games(self):
        other = F.odds_rows(commence="2025-11-30T18:00:00Z")           # the same clubs, five weeks later
        mlb = [{"observed_utc": F.CAPTURED, "book": "draftkings", "away_team": "New York Yankees",
                "home_team": "Tampa Bay Rays", "away_price": 100, "home_price": -120}]
        self.assertEqual(self.build(rows=other + mlb)["markets"], {})

    def test_a_row_the_feed_did_not_tag_as_nfl_is_not_used(self):
        untagged = [{k: v for k, v in r.items() if k != "sport"} for r in F.odds_rows()]
        self.assertEqual(self.build(rows=untagged)["markets"], {})

    def test_a_started_or_final_game_cannot_be_published(self):
        p = self.build()
        self.assertIsNone(ledger.publish_refusal(p, F.NOW, 0.0))
        why = ledger.publish_refusal(p, F.NOW.replace(hour=21), 0.0)
        self.assertIn("kickoff 2025-10-26T20:25:00Z has passed", why)
        with tempfile.TemporaryDirectory() as d:
            store = F.make_store(Path(d))
            store.game_by_id()[F.GAME_ID]["status"] = "final"
            done = F.build(store)
        self.assertIn("not pending", ledger.publish_refusal(done, F.NOW, 0.0))


if __name__ == "__main__":
    unittest.main()
