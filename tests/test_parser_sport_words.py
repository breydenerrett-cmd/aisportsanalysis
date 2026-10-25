"""Sport words in the English parser set the rule's sport, and a prop request never falls back to MLB.

Pinned on 2026-10-24 after a production sentence about hockey came back as MLB batter props at any price with
one book. The prop menu (user_rules.PROP_MARKETS) is MLB batter and pitcher stats only, so a prop request for any
other named sport is said to be not available yet, and the game-level rule for that sport is kept. The player
list is injected so no test reads the machine's box-score store.
"""
from __future__ import annotations

import unittest

from src.hounds import user_rules as R
from src.hounds import user_spec
from src.hounds.english import parser

OWNER_SENTENCE = ("Find undervalued prices on hockey games, be aggressive on unit sizing and on how many bets "
                  "you're taking, and seek out player props")


def parse(text):
    return parser.parse(text, players=[])


def not_understood_texts(res):
    return [item["text"] for item in res["not_understood"]]


def understood_meanings(res):
    return [item["meaning"] for item in res["understood"]]


class OwnerSentenceTests(unittest.TestCase):
    def setUp(self):
        self.res = parse(OWNER_SENTENCE)
        self.spec = self.res["spec"]
        self.rule = self.spec["rules"][0]

    def test_hockey_sets_the_rule_sport_and_no_mlb_anywhere(self):
        self.assertEqual(self.rule["sports"], ["NHL"])
        self.assertNotIn("MLB", self.rule["sports"])
        mlb_props = R.PROP_SPORT_MARKETS["MLB"]
        for market in self.rule["markets"]:
            self.assertNotIn(market, mlb_props)
            self.assertIn(market, R.PROP_SPORT_MARKETS["NHL"])   # NHL props exist since 2026-10-25

    def test_aggressive_unit_sizing_takes_the_top_of_the_stake_menu(self):
        self.assertEqual(self.spec["stake_units"], max(R.STAKE_CHOICES))
        self.assertLessEqual(self.spec["stake_units"], max(R.STAKE_CHOICES))

    def test_aggressive_bet_count_takes_the_top_of_the_bets_menu(self):
        self.assertEqual(self.spec["max_bets_per_day"], user_spec.MAX_BETS_RANGE[1])

    def test_min_books_is_the_validator_default_for_the_rule_kind(self):
        # prop rules default to DEFAULT_MIN_BOOKS_PROP (props are quoted by fewer books); the parser never invents one
        self.assertEqual(self.rule["min_books"], user_spec.DEFAULT_MIN_BOOKS_PROP)

    def test_value_is_said_to_be_not_checkable_in_plain_words(self):
        missing = not_understood_texts(self.res)
        self.assertNotIn("player props for hockey", missing)
        self.assertIn("undervalued prices", missing)

    def test_the_understood_list_reports_the_sport_and_both_sizing_words(self):
        self.assertIn("NHL", understood_meanings(self.res))
        understood_text = [i["text"] for i in self.res["understood"]]
        self.assertIn("hockey", understood_text)
        self.assertIn("how many bets", understood_text)


class SportWordTests(unittest.TestCase):
    # NHL and NBA props exist since 2026-10-25; a sport with no priced props is refused in words, never switched to MLB
    def test_nba_player_props_read_as_nba_props_not_mlb(self):
        rule = parse("nba player props")["spec"]["rules"][0]
        self.assertEqual(rule["sports"], ["NBA"])
        for market in rule["markets"]:
            self.assertIn(market, R.PROP_SPORT_MARKETS["NBA"])

    def test_plain_player_props_still_reads_every_mlb_prop_market(self):
        res = parse("player props")
        rule = res["spec"]["rules"][0]
        self.assertEqual(rule["sports"], ["MLB"])
        self.assertEqual(sorted(rule["markets"]), sorted(R.PROP_SPORT_MARKETS["MLB"]))


if __name__ == "__main__":
    unittest.main()
