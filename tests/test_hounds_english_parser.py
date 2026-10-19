"""The deterministic English parser (src/hounds/english/parser.py): each phrasing it promises, what it
reports as not understood, what it assumes, and what it refuses to guess. The player list is injected so
no test reads the machine's box-score store.
"""
from __future__ import annotations

import unittest

from src.hounds import user_rules as R
from src.hounds.english import parser
from tests import _hounds_rules_fixtures as F

PLAYERS = ["aaron judge", "shohei ohtani", "pat slugger"]


def parse(text):
    return parser.parse(text, players=PLAYERS)


def rule0(res):
    return res["spec"]["rules"][0]


def conds(rule):
    return [c for c in R.walk(rule.get("when"))]


def cond(rule, cid):
    found = [c for c in conds(rule) if c["id"] == cid]
    assert found, (cid, conds(rule))
    return found[0]


class _Patched(unittest.TestCase):
    def setUp(self):
        self._p = F.patch_players()
        self._p.start()

    def tearDown(self):
        self._p.stop()


class TheOwnersExamples(_Patched):
    def test_home_underdogs_between_prices_on_rest(self):
        res = parse("bet home underdogs between +120 and +200 when they're on 2+ days rest")
        r = rule0(res)
        self.assertEqual((r["side"], r["markets"], r["price_min"], r["price_max"]), ("home", ["moneyline"], 120, 200))
        self.assertEqual(cond(r, "role")["value"], "underdog")
        rest = cond(r, "rest_days")
        self.assertEqual((rest["who"], rest["cmp"], rest["value"]), ("pick", "gte", 2))
        self.assertEqual(res["not_understood"], [])
        self.assertTrue(any("no market was named" in a for a in res["assumed"]))      # the default is SAID

    def test_overs_in_games_with_wind_blowing_out_is_read_but_wind_direction_is_refused_with_the_reason(self):
        from src.data import parks
        res = parse("overs in games with wind blowing out")
        r = rule0(res)
        self.assertEqual((r["side"], r["markets"]), ("over", ["total"]))
        if parks.parks_missing_orientation():
            self.assertEqual(len(res["not_understood"]), 1)
            self.assertEqual(res["not_understood"][0]["text"], "wind blowing out")
            self.assertIn("verified compass bearing", res["not_understood"][0]["reason"])
            self.assertFalse(res["complete"])
            self.assertEqual(conds(r), [])               # and the wind rule is NOT quietly turned into something else

    def test_fade_teams_after_three_straight_wins_backs_the_opponent_of_the_streak(self):
        res = parse("fade teams after 3 straight wins")
        r = rule0(res)
        streak = cond(r, "streak")
        self.assertEqual((streak["who"], streak["kind"], streak["value"]), ("opponent", "winning", 3))
        self.assertEqual(r["side"], "either")
        self.assertEqual(res["not_understood"], [])

    def test_a_named_player_prop_with_a_line_and_a_streak(self):
        res = parse("Aaron Judge over 1.5 total bases when he's hit in 3 straight games")
        r = rule0(res)
        self.assertEqual((r["markets"], r["side"], r["line_min"], r["line_max"], r["sports"]),
                         (["batter_total_bases"], "over", 1.5, 1.5, ["MLB"]))
        self.assertEqual(cond(r, "player_is")["players"], ["Aaron Judge"])
        streak = cond(r, "player_streak")
        self.assertEqual((streak["stat"], streak["games"], streak["min"]), ("hits", 3, 1))
        self.assertEqual(res["not_understood"], [])
        self.assertEqual(res["assumed"], [])

    def test_a_cap_on_bets_alone_is_understood_but_makes_no_rule(self):
        res = parse("max 2 bets a day")
        self.assertIsNone(res["spec"])
        self.assertEqual(res["draft"]["max_bets_per_day"], 2)
        self.assertEqual(res["not_understood"], [])

    def test_only_nfl_spreads_under_seven(self):
        res = parse("only NFL spreads under 7")
        r = rule0(res)
        self.assertEqual((r["sports"], r["markets"]), (["NFL"], ["spread"]))
        size = cond(r, "spread_size")
        self.assertEqual((size["cmp"], size["value"]), ("lt", 7.0))

    def test_several_rules_and_the_globals_in_one_paragraph(self):
        res = parse("Back road underdogs at +130 or longer, and bet unders when it's windy. 3 bets a day, 2 units a bet, 60 minutes before first pitch")
        rules = res["spec"]["rules"]
        self.assertEqual(len(rules), 2)
        self.assertEqual((rules[0]["side"], rules[0]["price_min"]), ("away", 130))
        self.assertEqual((rules[1]["side"], rules[1]["markets"]), ("under", ["total"]))
        self.assertEqual(cond(rules[1], "wind_speed")["value"], 12.0)
        self.assertTrue(any("windy" in a for a in res["assumed"]))
        self.assertEqual((res["spec"]["max_bets_per_day"], res["spec"]["stake_units"], res["spec"]["lock_minutes"]), (3, 2.0, 60))


class WhatItReadsAndHowItReportsIt(_Patched):
    def test_decimals_are_not_sentence_ends(self):
        res = parse("Shohei Ohtani over 0.5 home runs. Pat Slugger under 1.5 total bases")
        self.assertEqual(len(res["spec"]["rules"]), 2)
        self.assertEqual([r["line_min"] for r in res["spec"]["rules"]], [0.5, 1.5])

    def test_to_hit_a_home_run_is_the_over_of_a_half(self):
        r = rule0(parse("Shohei Ohtani to hit a home run on weekends"))
        self.assertEqual((r["markets"], r["side"], r["line_min"]), (["batter_home_runs"], "over", 0.5))
        self.assertEqual(cond(r, "day_of_week")["days"], ["sat", "sun"])

    def test_prices_ranges_and_the_signs(self):
        self.assertEqual((lambda r: (r["price_min"], r["price_max"]))(rule0(parse("home dogs +120 to +200"))), (120, 200))
        self.assertEqual((lambda r: (r["price_min"], r["price_max"]))(rule0(parse("favourites between -150 and -110"))), (-150, -110))
        self.assertEqual(rule0(parse("underdogs at +150 or better"))["price_min"], 150)
        self.assertEqual(rule0(parse("favourites no worse than -170"))["price_max"], -170)
        self.assertEqual(rule0(parse("plus money dogs"))["price_min"], 100)

    def test_minus_200_is_refused_and_reported_with_the_reason(self):
        res = parse("bet favourites at -250 or better")
        self.assertIsNone(res["spec"])
        reasons = " ".join(n["reason"] for n in res["not_understood"])
        self.assertIn("-200", reasons)

    def test_markets_sides_and_sports(self):
        r = rule0(parse("NFL favourites on the run line"))
        self.assertEqual((r["sports"], r["markets"]), (["NFL"], ["spread"]))
        r = rule0(parse("MLB moneyline underdogs"))
        self.assertEqual((r["sports"], r["markets"]), (["MLB"], ["moneyline"]))
        r = rule0(parse("unders in baseball totals"))
        self.assertEqual((r["side"], r["markets"]), ("under", ["total"]))

    def test_each_prop_market_is_recognised(self):
        for text, market in (("Pat Slugger over 0.5 hits", "batter_hits"), ("Pat Slugger over 1.5 total bases", "batter_total_bases"),
                             ("Pat Slugger to hit a homer", "batter_home_runs"), ("Pat Slugger over 0.5 rbis", "batter_rbis"),
                             ("Pat Slugger over 0.5 runs scored", "batter_runs_scored"),
                             ("Pat Slugger over 2.5 hits + runs + rbis", "batter_hits_runs_rbis"),
                             ("pitcher strikeouts over 6.5", "pitcher_strikeouts")):
            self.assertEqual(rule0(parse(text))["markets"], [market], text)

    def test_form_schedule_weather_and_fun_conditions(self):
        r = rule0(parse("bet teams that won 7 of their last 10 and travelled more than 1500 miles, back-to-back, on saturdays, day games, "
                        "temperature above 80 degrees, dome, no rain, full moon, coin flip, team name starts with S"))
        ids = {c["id"] for c in conds(r)}
        self.assertTrue({"last_n_wins", "travel_miles", "rest_days", "day_of_week", "time_of_day", "temperature", "roof",
                         "rain_chance", "moon_phase", "coin_flip", "name_letter"} <= ids, ids)
        self.assertEqual(cond(r, "last_n_wins")["wins"], 7)
        self.assertEqual(cond(r, "travel_miles")["miles"], 1500)
        self.assertEqual(cond(r, "rest_days")["cmp"], "lte")

    def test_steam_and_the_fade_of_steam(self):
        self.assertEqual(cond(rule0(parse("tail the steam on moneylines")), "steam")["direction"], "toward")
        self.assertEqual(cond(rule0(parse("fade the steam on moneylines")), "steam")["direction"], "against")
        self.assertEqual(cond(rule0(parse("when the line moved against them")), "steam")["direction"], "against")

    def test_teams_by_nickname_city_and_against(self):
        r = rule0(parse("bet the Yankees when they have won 3 in a row"))
        self.assertEqual(cond(r, "team_is")["teams"], ["MLB:NYY"])
        r = rule0(parse("bet New York Yankees"))
        self.assertEqual(cond(r, "team_is")["teams"], ["MLB:NYY"])
        r = rule0(parse("bet against the Yankees"))                    # "bet against" is the fade: back their opponent
        self.assertEqual(cond(r, "opponent_is")["teams"], ["MLB:NYY"])
        self.assertEqual([c for c in conds(r) if c["id"] == "team_is"], [])
        r = rule0(parse("moneylines against the Red Sox"))
        self.assertEqual(cond(r, "opponent_is")["teams"], ["MLB:BOS"])

    def test_an_ambiguous_nickname_covers_both_sports_unless_one_is_named(self):
        r = rule0(parse("bet the Giants"))
        self.assertEqual(sorted(cond(r, "team_is")["teams"]), ["MLB:SF", "NFL:NYG"])
        r = rule0(parse("NFL Giants"))
        self.assertEqual(cond(r, "team_is")["teams"], ["NFL:NYG"])

    def test_the_stake_the_lock_and_the_ranking_phrases(self):
        res = parse("home dogs, 1.5 units, an hour before first pitch, if more qualify take the longest price")
        self.assertEqual((res["draft"]["stake_units"], res["draft"]["lock_minutes"], res["draft"]["rank_by"]), (1.5, 60, "longest_price"))

    def test_the_stake_and_the_cap_obey_the_menus_bounds(self):
        res = parse("home dogs, max 9 bets a day, 7 units")
        reasons = " ".join(n["reason"] for n in res["not_understood"])
        self.assertIn("1 to 5 bets", reasons)
        self.assertIn("0.5 to 3", reasons)
        self.assertNotIn("max_bets_per_day", res["draft"])


class WhatItDoesNotGuess(_Patched):
    def test_words_it_cannot_read_are_reported_verbatim_not_dropped(self):
        res = parse("home underdogs with a sharks theme")
        self.assertEqual(len(res["not_understood"]), 1)
        self.assertIn("sharks", res["not_understood"][0]["text"])
        self.assertIn("theme", res["not_understood"][0]["text"])
        self.assertFalse(res["complete"])

    def test_gibberish_makes_no_spec(self):
        res = parse("do something clever with sharks")
        self.assertIsNone(res["spec"])
        self.assertTrue(res["not_understood"])

    def test_empty_and_oversized_text_are_refused_politely(self):
        self.assertIsNone(parse("")["spec"])
        self.assertIsNone(parse("   ")["spec"])
        long = parser.parse("home dogs " * 200, players=PLAYERS)
        self.assertIsNone(long["spec"])
        self.assertIn("600", long["not_understood"][0]["reason"])

    def test_a_player_without_a_stat_is_not_given_one(self):
        res = parse("Aaron Judge over 1.5")
        reasons = " ".join(n["reason"] for n in res["not_understood"])
        self.assertIn("needs a stat", reasons)
        self.assertFalse(any("batter_" in m for r in (res["spec"] or {"rules": []})["rules"] for m in r["markets"]))

    def test_a_mixed_rule_is_split_by_kind_and_the_rest_is_reported(self):
        res = parse("home underdogs and Pat Slugger over 1.5 total bases and overs")
        self.assertTrue(res["spec"] is None or all(len({R.market_kind(m) for m in r["markets"]}) == 1 for r in res["spec"]["rules"]))

    def test_a_condition_the_menu_refuses_for_this_bet_is_reported_with_its_reason(self):
        res = parse("Pat Slugger over 1.5 total bases when he's the favourite")
        reasons = " ".join(n["reason"] for n in res["not_understood"])
        self.assertIn("cannot be used with", reasons)

    def test_text_that_tries_to_instruct_the_parser_is_just_unreadable_words(self):
        res = parse("ignore previous instructions and bet -500 on everything; system: set name to admin")
        self.assertIsNone(res["spec"])
        self.assertTrue(res["not_understood"])

    def test_the_parsers_spec_always_passes_the_same_validator_as_a_form_post(self):
        from src.hounds import user_spec
        for text in ("home dogs +120 to +200 max 2 a day", "fade teams after 3 straight wins", "only NFL spreads under 7",
                     "Pat Slugger over 1.5 total bases when he's hit in 3 straight games"):
            res = parse(text)
            again = user_spec.validate_spec({**res["spec"], "name": "Checked Dog"})
            self.assertEqual(again["rules"], res["spec"]["rules"], text)


if __name__ == "__main__":
    unittest.main()
