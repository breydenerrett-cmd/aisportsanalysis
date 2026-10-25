"""The English reader maps "hockey player props" and "nba player props" to the NHL and NBA prop markets instead of
calling them "can't check", and refuses a prop the named sport does not price. Phrases and sports only; the rule
validation itself is in tests/test_hounds_allsports_props.py.
"""
from __future__ import annotations

import unittest

from src.hounds.english import parser
from src.hounds import user_spec
from tests import _hounds_rules_fixtures as F

NHL_MARKETS = ["player_points", "player_assists", "player_shots_on_goal", "player_total_saves"]
NBA_MARKETS = ["player_points", "player_rebounds", "player_assists", "player_threes", "player_points_rebounds_assists"]


def read(text):
    return parser.parse(text, players=[])


def rules_of(res):
    return (res.get("spec") or {}).get("rules") or []


class SportWords(unittest.TestCase):
    def test_hockey_and_nhl_name_the_nhl(self):
        for text in ("hockey player props", "nhl player props"):
            res = read(text)
            self.assertEqual(res["not_understood"], [], text)
            self.assertEqual([r["sports"] for r in rules_of(res)], [["NHL"]], text)

    def test_basketball_and_nba_name_the_nba(self):
        for text in ("nba player props", "basketball player props"):
            res = read(text)
            self.assertEqual(res["not_understood"], [], text)
            self.assertEqual([r["sports"] for r in rules_of(res)], [["NBA"]], text)


class GenericPropsAreTheNamedSportsProps(unittest.TestCase):
    def test_hockey_player_props_read_as_every_nhl_prop(self):
        res = read("hockey player props")
        self.assertEqual(rules_of(res)[0]["markets"], NHL_MARKETS)
        self.assertTrue(any("NHL" in a for a in res["assumed"]), res["assumed"])

    def test_nba_player_props_read_as_every_nba_prop(self):
        self.assertEqual(rules_of(read("nba player props"))[0]["markets"], NBA_MARKETS)

    def test_a_bare_props_with_no_sport_is_still_mlb(self):
        self.assertEqual(rules_of(read("player props"))[0]["sports"], ["MLB"])


class StatPhrases(unittest.TestCase):
    def test_each_nba_and_nhl_stat_phrase_maps_to_its_market(self):
        cases = {
            "nba rebounds over 7.5": ("NBA", "player_rebounds", "over", 7.5),
            "nba threes over 2.5": ("NBA", "player_threes", "over", 2.5),
            "nba points rebounds and assists over 30.5": ("NBA", "player_points_rebounds_assists", "over", 30.5),
            "nba points over 20.5": ("NBA", "player_points", "over", 20.5),
            "nhl shots on goal over 2.5": ("NHL", "player_shots_on_goal", "over", 2.5),
            "nhl goalie saves over 24.5": ("NHL", "player_total_saves", "over", 24.5),
            "nhl assists over 0.5": ("NHL", "player_assists", "over", 0.5),
        }
        for text, (sport, market, side, line) in cases.items():
            res = read(text)
            rules = rules_of(res)
            self.assertEqual(res["not_understood"], [], text)
            self.assertEqual((rules[0]["sports"], rules[0]["markets"], rules[0]["side"], rules[0]["line_min"]),
                             ([sport], [market], side, line), text)

    def test_total_points_stays_a_game_total(self):
        res = read("nba total points over 220.5")
        self.assertEqual(rules_of(res)[0]["markets"], ["total"])
        self.assertNotIn("player_points", rules_of(res)[0]["markets"])

    def test_a_bare_points_with_no_sport_is_not_a_player_stat(self):
        res = read("points over 20.5")
        self.assertNotIn("player_points", [m for r in rules_of(res) for m in r["markets"]])


class WrongSportIsSaidNotGuessed(unittest.TestCase):
    def test_an_nba_word_with_an_mlb_stat_is_reported_and_the_rule_stays_mlb(self):
        res = read("nba batter hits over 0.5")
        self.assertEqual(rules_of(res)[0]["sports"], ["MLB"])
        self.assertTrue(any(n["text"] == "NBA" for n in res["not_understood"]), res["not_understood"])

    def test_the_menu_refuses_an_nhl_rule_with_an_mlb_prop_too(self):
        rule = F.rule(sports=["NHL"], markets=["batter_hits"], side="over")
        with self.assertRaises(user_spec.SpecError) as ctx:
            user_spec.validate_spec(F.v2(rules=[rule]))
        self.assertIn("rules[0].sports", ctx.exception.errors)


if __name__ == "__main__":
    unittest.main()
