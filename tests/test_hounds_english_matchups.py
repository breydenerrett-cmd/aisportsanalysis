"""The English parser's reading of matchup and team-strength language, and what it says about the rest.

THE TEXT THAT STARTED IT (a real member, 2026-10-19, on a phone): "use statistics, previous head-to-head
matchups, previous matchups as in last five games, use home advantage and away games data matched with
offensive and defensive stats". The parser read exactly one word of it ("away", as the away side, which is the
OPPOSITE of what he meant) and threw the rest at a translator. These tests pin what that sentence reads as now
(head-to-head, last-five form, one home/road record, offense and defense against the other team) and that a
default is never silent: every number the person did not say is listed under `assumed`.
"""
from __future__ import annotations

import unittest

from src.hounds import user_rules as R
from src.hounds.english import parser
from tests import _hounds_rules_fixtures as F

JACOB = ("use statistics, previous head-to-head matchups, previous matchups as in last five games, use home "
         "advantage and away games data matched with offensive and defensive stats")


def parse(text):
    return parser.parse(text, players=["aaron judge"])


def conds(res, rule=0):
    return list(R.walk(res["spec"]["rules"][rule].get("when")))


def ids(res, rule=0):
    return [c["id"] for c in conds(res, rule)]


class _Patched(unittest.TestCase):
    def setUp(self):
        self._p = F.patch_players()
        self._p.start()

    def tearDown(self):
        self._p.stop()


class TheMembersExactText(_Patched):
    def test_it_reads_head_to_head_last_five_form_a_home_road_record_and_offense_and_defense(self):
        res = parse(JACOB)
        self.assertEqual(sorted(ids(res)), sorted(["head_to_head", "last_n_wins", "venue_record",
                                                   "matchup_edge", "matchup_edge"]))
        by = {}
        for c in conds(res):
            by.setdefault(c["id"], []).append(c)
        h2h = by["head_to_head"][0]
        self.assertEqual((h2h["who"], h2h["n"], h2h["cmp"], h2h["wins"], h2h["window"]), ("pick", 5, "gte", 3, "all"))
        form = by["last_n_wins"][0]
        self.assertEqual((form["n"], form["cmp"], form["wins"]), (5, "gte", 3))
        venue = by["venue_record"][0]
        self.assertEqual((venue["ground"], venue["cmp"], venue["pct"]), ("today", "gte", 60.0))
        self.assertEqual({c["unit"] for c in by["matchup_edge"]}, {"offense", "defense"})

    def test_away_games_data_is_not_the_away_side(self):
        res = parse(JACOB)
        self.assertEqual(res["spec"]["rules"][0]["side"], "either")          # the old reading backed every visitor
        self.assertFalse(any(u["meaning"] == "the away side" for u in res["understood"]))

    def test_the_only_thing_left_unread_is_best_and_it_comes_with_a_suggestion(self):
        res = parse(JACOB + " to pick the best teams to win")
        self.assertEqual([n["text"] for n in res["not_understood"]], ["best"])
        self.assertTrue(res["suggestions"])
        self.assertIn("won at least 4 of the last 5 games", [s["try"] for s in res["suggestions"]])

    def test_every_default_it_chose_is_listed_so_the_person_can_change_it(self):
        assumed = " ".join(parse(JACOB)["assumed"])
        for part in ("last 5 meetings", "at least 3 wins in the last 5 meetings", "at least 3 wins in the last 5 games",
                     "win rate of at least 60%", "last 10 games", "at least 1 place better"):
            self.assertIn(part, assumed)

    def test_the_draft_is_a_valid_spec_not_just_a_pile_of_phrases(self):
        res = parse(JACOB)
        self.assertTrue(res["spec"])
        self.assertEqual(res["spec"]["rules"][0]["markets"], ["moneyline"])
        self.assertTrue(res["sentences"])
        self.assertTrue(any("meetings between these two clubs" in s for s in res["sentences"]))


class HeadToHead(_Patched):
    def check(self, text, **want):
        res = parse(text)
        h = [c for c in conds(res) if c["id"] == "head_to_head"]
        self.assertEqual(len(h), 1, (text, conds(res)))
        for key, value in want.items():
            self.assertEqual(h[0][key], value, (text, key))
        return res

    def test_explicit_counts(self):
        self.check("back teams that have won 4 of the last 6 meetings", n=6, wins=4, who="pick", window="all")
        self.check("home teams that won at least 2 of the last 3 head-to-head matchups", n=3, wins=2)
        self.check("bet teams that have won 3 of their last 5 games against the opponent", n=5, wins=3)

    def test_won_the_last_n_meetings_means_all_of_them(self):
        self.check("bet teams that won the last 3 meetings", n=3, wins=3)

    def test_the_season_series_and_this_season_windows(self):
        self.check("teams that won 2 of the last 3 meetings this season", n=3, wins=2, window="season")
        self.check("teams leading the season series", window="season", n=5, wins=3)

    def test_a_bare_head_to_head_gets_five_meetings_and_a_majority_and_says_so(self):
        for text in ("underdogs with a good head-to-head record", "h2h history", "previous matchups"):
            res = self.check(text, n=5, wins=3, cmp="gte", window="all")
            self.assertTrue(any("last 5 meetings" in a for a in res["assumed"]), text)
            self.assertTrue(any("at least 3 wins in the last 5 meetings" in a for a in res["assumed"]), text)
        res = self.check("a winning head-to-head record in the last 4 meetings", n=4, wins=3)
        self.assertTrue(any("at least 3 wins in the last 4 meetings" in a for a in res["assumed"]))

    def test_the_opponent_and_a_fade(self):
        self.check("the opponent has won 3 of the last 5 meetings", who="opponent", n=5, wins=3)
        self.check("fade teams that won 3 of the last 5 meetings", who="opponent", n=5, wins=3)

    def test_out_of_range_counts_are_refused_with_a_reason_not_clamped(self):
        res = parse("won 4 of the last 12 meetings")
        self.assertIn("head-to-head looks back 1 to 10 meetings", [n["reason"] for n in res["not_understood"]])
        self.assertNotIn("head_to_head", [c["id"] for c in conds(res)] if res["spec"] else [])
        res = parse("won 7 of the last 5 meetings")
        self.assertIn("wins cannot be more than the number of meetings counted", [n["reason"] for n in res["not_understood"]])

    def test_the_same_idea_said_twice_is_one_condition(self):
        res = parse("head-to-head record in the last 5 meetings, previous matchups")
        self.assertEqual(ids(res).count("head_to_head"), 1)

    def test_won_n_of_the_last_m_games_is_still_plain_form_not_a_head_to_head(self):
        res = parse("teams that won 4 of their last 5 games")
        self.assertEqual(ids(res), ["last_n_wins"])
        self.assertEqual((conds(res)[0]["n"], conds(res)[0]["wins"]), (5, 4))


class RecentForm(_Patched):
    def test_last_five_games_with_no_wins_named_is_a_winning_record_and_says_so(self):
        res = parse("bet teams with a good last 5 games")
        c = conds(res)[0]
        self.assertEqual((c["id"], c["n"], c["wins"], c["cmp"]), ("last_n_wins", 5, 3, "gte"))
        self.assertTrue(any("at least 3 wins in the last 5 games" in a for a in res["assumed"]))

    def test_recent_form_with_no_number_is_the_last_five(self):
        res = parse("favorites with strong recent form")
        c = [x for x in conds(res) if x["id"] == "last_n_wins"][0]
        self.assertEqual((c["n"], c["wins"]), (5, 3))

    def test_the_opponents_last_games_is_about_the_opponent(self):
        c = [x for x in conds(parse("fade the opponent's last 10 games")) if x["id"] == "last_n_wins"][0]
        self.assertEqual(c["who"], "pick")      # a fade flips "the opponent" back to the pick
        c = [x for x in conds(parse("the opponent's last 10 games")) if x["id"] == "last_n_wins"][0]
        self.assertEqual((c["who"], c["n"], c["wins"]), ("opponent", 10, 6))

    def test_a_player_average_over_the_last_games_is_not_team_form(self):
        res = parse("Aaron Judge over 1.5 total bases when his last 7 games average above the line")
        self.assertEqual(ids(res).count("last_n_wins"), 0)
        self.assertIn("player_form", ids(res))

    def test_one_or_two_games_is_not_form(self):
        res = parse("teams after their last 2 games")
        self.assertIn("last-N form is 3 to 20 games", [n["reason"] for n in res["not_understood"]])


class HomeAndRoadRecord(_Patched):
    def venue(self, text):
        found = [c for c in conds(parse(text)) if c["id"] == "venue_record"]
        self.assertEqual(len(found), 1, (text, found))
        return found[0]

    def test_home_advantage_is_a_record_on_todays_ground_at_the_default_rate(self):
        c = self.venue("teams with home advantage")
        self.assertEqual((c["ground"], c["cmp"], c["pct"]), ("today", "gte", 60.0))

    def test_home_record_and_road_record_name_their_ground(self):
        self.assertEqual(self.venue("teams with a good home record")["ground"], "home")
        self.assertEqual(self.venue("teams with a strong road record")["ground"], "road")
        self.assertEqual(self.venue("look at away games data")["ground"], "road")

    def test_home_and_away_together_are_one_record_on_todays_ground(self):
        self.assertEqual(self.venue("use home and away splits")["ground"], "today")
        self.assertEqual(self.venue("home advantage and away games data")["ground"], "today")

    def test_numbers_are_read_not_defaulted(self):
        c = self.venue("teams with a home win rate of at least 65%")
        self.assertEqual((c["ground"], c["cmp"], c["pct"]), ("home", "gte", 65.0))
        c = self.venue("teams with a road record under 45%")
        self.assertEqual((c["ground"], c["cmp"], c["pct"]), ("road", "lt", 45.0))
        c = self.venue("teams that win at least 70% of their home games")
        self.assertEqual((c["ground"], c["pct"]), ("home", 70.0))
        c = self.venue("win rate of 55% at home")
        self.assertEqual((c["ground"], c["pct"]), ("home", 55.0))

    def test_an_off_step_percentage_is_refused_not_rounded(self):
        res = parse("teams with a home win rate of at least 62%")
        self.assertIn("a win rate is 0 to 100 percent in steps of 5", [n["reason"] for n in res["not_understood"]])

    def test_home_and_away_as_sides_still_mean_sides(self):
        self.assertEqual(parse("bet home underdogs")["spec"]["rules"][0]["side"], "home")
        self.assertEqual(parse("road underdogs")["spec"]["rules"][0]["side"], "away")
        self.assertEqual(parse("bet the away team on the road")["spec"]["rules"][0]["side"], "away")


class OffenseAndDefense(_Patched):
    def one(self, text, cid):
        found = [c for c in conds(parse(text)) if c["id"] == cid]
        self.assertEqual(len(found), 1, (text, [c["id"] for c in conds(parse(text))]))
        return found[0]

    def test_its_offense_ranks_better_than_the_opponents_defense(self):
        c = self.one("its offense ranks better than the opponent's defense", "matchup_edge")
        self.assertEqual((c["who"], c["unit"], c["gap"], c["n"]), ("pick", "offense", 1, 10))
        c = self.one("the team's defense is better than the opponent's offense over the last 15 games", "matchup_edge")
        self.assertEqual((c["unit"], c["n"]), ("defense", 15))

    def test_offense_vs_defense_phrasings(self):
        self.assertEqual(self.one("good offense against a weak defense", "matchup_edge")["unit"], "offense")
        self.assertEqual(self.one("offense vs defense", "matchup_edge")["unit"], "offense")
        self.assertEqual(self.one("offensive stats", "matchup_edge")["unit"], "offense")
        self.assertEqual(self.one("defensive rankings", "matchup_edge")["unit"], "defense")

    def test_offensive_and_defensive_together_are_two_conditions_and_say_so(self):
        res = parse("compare offensive and defensive numbers")
        self.assertEqual(ids(res), ["matchup_edge", "matchup_edge"])
        self.assertEqual({c["unit"] for c in conds(res)}, {"offense", "defense"})
        self.assertTrue(any("offense AND its defense" in a for a in res["assumed"]))

    def test_top_and_bottom_n_in_the_league(self):
        c = self.one("teams with a top 10 offense", "league_rank")
        self.assertEqual((c["who"], c["unit"], c["end"], c["places"], c["n"]), ("pick", "offense", "top", 10, 10))
        c = self.one("against a bottom 5 defense", "league_rank")
        self.assertEqual((c["who"], c["unit"], c["end"], c["places"]), ("opponent", "defense", "bottom", 5))
        c = self.one("a top-3 defense in the league this season", "league_rank")
        self.assertEqual((c["unit"], c["places"], c["n"]), ("defense", 3, 0))

    def test_a_league_rank_beyond_the_menu_is_refused_with_a_reason(self):
        res = parse("teams with a top 20 offense")
        self.assertIn("a league rank is the top or bottom 1 to 15", [n["reason"] for n in res["not_understood"]])

    def test_runs_and_points_per_game_pick_the_sport_when_none_is_named(self):
        res = parse("teams that score at least 5 runs per game")
        c = conds(res)[0]
        self.assertEqual((c["id"], c["unit"], c["cmp"], c["value"]), ("scoring_rate", "offense", "gte", 5.0))
        self.assertEqual(res["spec"]["rules"][0]["sports"], ["MLB"])
        res = parse("teams that average over 24.5 points per game over the last 5 games")
        c = conds(res)[0]
        self.assertEqual((c["value"], c["cmp"], c["n"]), (24.5, "gt", 5))
        self.assertEqual(res["spec"]["rules"][0]["sports"], ["NFL"])

    def test_allowing_runs_is_the_defense_and_defaults_to_at_most(self):
        c = conds(parse("teams that allow 3 runs per game"))[0]
        self.assertEqual((c["unit"], c["cmp"], c["value"]), ("defense", "lte", 3.0))
        c = conds(parse("the opponent gives up more than 5 runs a game this season"))[0]
        self.assertEqual((c["who"], c["cmp"], c["n"]), ("opponent", "gt", 0))

    def test_a_per_game_figure_in_odd_steps_is_refused_not_rounded(self):
        res = parse("teams that score at least 4.55 runs per game")
        self.assertIn("runs or points per game is in steps of 0.1", [n["reason"] for n in res["not_understood"]])


class WhatItStillCannotReadAndWhatToSayInstead(_Patched):
    def test_every_suggested_wording_is_one_the_parser_reads_in_full(self):
        for row in parser._SUGGEST:
            if row[1] is None:
                continue
            res = parse(row[1])
            self.assertTrue(res["spec"], row[1])
            self.assertEqual(res["not_understood"], [], row[1])

    def test_head_to_head_words_that_stay_unread_get_the_head_to_head_wording(self):
        res = parse("teams with historical dominance in the series")
        self.assertTrue(res["not_understood"])
        self.assertEqual(res["suggestions"][0]["try"], "won at least 3 of the last 5 meetings")

    def test_things_the_rules_do_not_have_are_said_plainly_with_no_wording_offered(self):
        res = parse("bet teams with a better starting pitcher and fewer injuries")
        sugg = [s for s in res["suggestions"] if s["try"] is None]
        self.assertTrue(sugg)
        self.assertIn("not available to the rules yet", sugg[0]["why"])

    def test_an_over_long_text_is_a_reason_not_a_crash(self):
        res = parse("a " * 400)
        self.assertTrue(res["too_long"])
        self.assertIsNone(res["spec"])
        self.assertEqual(res["max_text"], 600)

    def test_a_text_that_is_fully_read_has_no_suggestions(self):
        self.assertEqual(parse("bet home underdogs between +120 and +200")["suggestions"], [])


if __name__ == "__main__":
    unittest.main()
