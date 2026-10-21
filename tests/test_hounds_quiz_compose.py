"""Quiz answers -> a hound spec (src/hounds/quiz/compose.py).

Fifteen-plus answer combinations including all-skipped, every conflict rule ("the later answer wins", said in a warning),
the English add-on merge, names, and a seeded sweep that proves no combination can build a price at -200 or worse or a spec
the real validator refuses. Pure and offline.
"""
from __future__ import annotations

import json
import random
import unittest

from src.hounds import user_rules as R
from src.hounds import user_spec
from src.hounds.english import parser, render
from src.hounds.interact import look as look_mod
from src.hounds.quiz import compose as C, library as L

LIB = L.load()


def codes(out):
    return [w["code"] for w in out["warnings"]]


def rules(out):
    return out["spec"]["rules"]


def conds(rule):
    return [c["id"] for c in R.walk(rule.get("when"))]


def assert_sound(test, out):
    """The invariants EVERY composed hound keeps."""
    spec = out["spec"]
    again = user_spec.validate_spec(spec)                   # the real validator accepts what compose returned
    test.assertEqual(again["rules"], spec["rules"])
    test.assertTrue(1 <= len(spec["rules"]) <= R.MAX_RULES)
    for rule in spec["rules"]:
        test.assertFalse(rule["price_min"] < 0 and rule["price_min"] <= user_spec.MAX_FAVOURITE_PRICE)
        test.assertFalse(rule["price_max"] < 0 and rule["price_max"] <= user_spec.MAX_FAVOURITE_PRICE)
    test.assertEqual(out["sentences"], render.rule_sentences(spec))
    test.assertEqual(out["english"], render.rule_text(spec))
    test.assertIn("Paper only", out["english"])
    test.assertEqual(len(out["rule_cards"]), len(spec["rules"]))
    test.assertTrue(out["paper_only"])
    look_mod.validate_look({**look_mod.DEFAULT_LOOK, **out["look"]})
    test.assertTrue(out["name_suggestions"])
    test.assertEqual(json.loads(json.dumps(out)), out)       # plain JSON all the way down


COMBOS = [
    {},
    {"sports": ["MLB"]},
    {"sports": ["NFL"], "markets": ["spread"], "personality": "underdog_hunter"},
    {"markets": ["moneyline"], "personality": "chalk_eater", "bets_per_day": 3, "stake": 0.5},
    {"markets": ["total"], "personality": "stats_nerd", "timing": "late"},
    {"markets": ["props"], "personality": "stats_nerd", "sports": ["MLB"], "price_comfort": "even"},
    {"markets": ["mix"], "personality": "chaos_agent", "stake": 3, "bets_per_day": 5},
    {"personality": "steam_chaser", "price_comfort": "short", "timing": "early"},
    {"personality": "mystic", "markets": ["moneyline", "total", "props"], "sports": ["MLB", "NFL"]},
    {"archetypes": ["steam_chaser"]},
    {"archetypes": ["revenge_tour", "primetime_underdog", "tired_legs"], "sports": ["MLB"]},
    {"archetypes": ["hot_bat_props", "strikeout_king"], "quirks": ["warm_nights"]},
    {"archetypes": ["lucky_letters"], "quirks": ["lucky_letter"], "letter": "r"},
    {"quirks": ["full_moon", "weekend"]},
    {"look": {"coat": "golden", "accessory": "cap"}, "name": "Biscuit Boss", "tagline": "Good dog."},
    {"personality": "underdog_hunter", "price_comfort": "long", "markets": ["props"], "archetypes": ["long_ball_dreamer"]},
    {"markets": ["mix"], "price_comfort": "plus", "quirks": ["steam_only", "primetime", "coin_flip"]},
]


class FifteenAnswerCombos(unittest.TestCase):

    def test_every_combo_composes_a_sound_hound(self):
        for answers in COMBOS:
            with self.subTest(answers=answers):
                assert_sound(self, C.compose(answers))

    def test_it_is_deterministic(self):
        for answers in COMBOS[:8]:
            self.assertEqual(C.compose(answers), C.compose(answers))
            self.assertEqual(C.compose(answers)["spec"]["name"], C.compose(answers)["spec"]["name"])

    def test_all_skipped_is_the_starter_pup_and_says_so(self):
        for skipped in ({}, None, {"personality": None, "markets": [], "archetypes": [], "quirks": None},
                        {"personality": "", "sports": "", "stake": ""}):
            out = C.compose(skipped)
            assert_sound(self, out)
            self.assertTrue(out["starter"])
            self.assertIn("starter", codes(out))
            self.assertEqual(out["rule_count"], 1)
            self.assertEqual(rules(out)[0]["when"]["items"][0]["id"], "role")
            self.assertEqual(out["answered"], [])
            self.assertEqual(out["settings"]["max_bets_per_day"], 2)
            self.assertEqual(out["settings"]["stake_units"], 1.0)

    def test_the_first_pick_builds_the_base_rule_in_the_chosen_sport(self):
        out = C.compose({"sports": ["NFL"], "markets": ["spread"], "personality": "underdog_hunter"})
        rule = rules(out)[0]
        self.assertEqual((rule["sports"], rule["markets"]), (["NFL"], ["spread"]))
        self.assertEqual((rule["price_min"], rule["price_max"]), (100, 300))
        self.assertEqual(conds(rule), ["role"])
        self.assertEqual(out["spec"]["rank_by"], "longest_price")
        self.assertEqual(out["spec"]["color"], "ember")
        self.assertEqual(out["breed"], "husky")

    def test_mix_is_one_game_rule_and_one_totals_rule(self):
        out = C.compose({"markets": ["mix"], "personality": "chalk_eater"})
        self.assertEqual([r["markets"] for r in rules(out)], [["moneyline", "spread"], ["total"]])

    def test_props_get_their_own_mlb_only_rule(self):
        out = C.compose({"markets": ["props"], "personality": "stats_nerd"})
        rule = rules(out)[0]
        self.assertEqual(rule["sports"], ["MLB"])
        self.assertEqual(rule["side"], "over")
        self.assertEqual(conds(rule), ["player_form"])
        self.assertEqual(rule["min_books"], 1)

    def test_risk_timing_and_stake_set_the_whole_hound_settings(self):
        out = C.compose({"personality": "steam_chaser", "bets_per_day": 4, "stake": 2.5, "timing": "early"})
        self.assertEqual(out["settings"], {"max_bets_per_day": 4, "stake_units": 2.5, "lock_minutes": 180,
                                           "rank_by": "biggest_steam"})
        late = C.compose({"timing": "late", "personality": "mystic"})
        self.assertEqual(late["settings"]["lock_minutes"], 60)
        self.assertEqual(C.compose({"personality": "chalk_eater"})["settings"]["max_bets_per_day"], 3)    # the personality's own hint

    def test_a_card_pick_adds_its_rule_verbatim(self):
        out = C.compose({"archetypes": ["windy_overs"]})
        card = next(a for a in LIB["archetypes"] if a["id"] == "windy_overs")
        got = rules(out)[0]
        self.assertEqual(got["markets"], ["total"])
        self.assertEqual(got["side"], "over")
        self.assertEqual(conds(got), ["wind_speed", "roof"])
        self.assertEqual(out["rule_cards"][0]["source"], "archetype")
        self.assertEqual(out["rule_cards"][0]["source_id"], "windy_overs")
        self.assertEqual(card["fragment"]["rules"][0]["when"]["items"], got["when"]["items"])

    def test_a_cards_ranking_rule_is_used_when_there_is_no_personality(self):
        self.assertEqual(C.compose({"archetypes": ["steam_chaser"]})["spec"]["rank_by"], "biggest_steam")
        self.assertEqual(C.compose({"archetypes": ["revenge_tour"]})["spec"]["rank_by"], "earliest_lock")

    def test_the_lucky_letter_reaches_both_the_card_and_the_quirk(self):
        out = C.compose({"archetypes": ["lucky_letters"], "quirks": ["lucky_letter"], "letter": "r"})
        letters = [c["letter"] for r in rules(out) for c in R.walk(r["when"]) if c["id"] == "name_letter"]
        self.assertEqual(letters, ["R"])
        self.assertIn("quirk_replaced", codes(out))                 # the quirk replaced the card's own letter rule


class ConflictsTheLaterAnswerWins(unittest.TestCase):

    def test_chalk_eater_then_plus_money_takes_the_later_price_and_drops_the_favourite_rule(self):
        out = C.compose({"markets": ["moneyline"], "personality": "chalk_eater", "price_comfort": "plus"})
        rule = rules(out)[0]
        self.assertEqual((rule["price_min"], rule["price_max"]), (100, 250))
        self.assertNotIn("role", conds(rule))
        warn = next(w for w in out["warnings"] if w["code"] == "price_conflict")
        self.assertIn("later answer wins", warn["message"])
        self.assertIn("Chalk Eater", warn["message"])
        self.assertIn("Plus money", warn["message"])

    def test_underdog_hunter_then_short_prices_conflicts_the_other_way(self):
        out = C.compose({"markets": ["moneyline"], "personality": "underdog_hunter", "price_comfort": "short"})
        rule = rules(out)[0]
        self.assertEqual((rule["price_min"], rule["price_max"]), (-199, -110))
        self.assertNotIn("role", conds(rule))
        self.assertIn("price_conflict", codes(out))

    def test_an_agreeing_price_comfort_is_no_conflict(self):
        out = C.compose({"markets": ["moneyline"], "personality": "underdog_hunter", "price_comfort": "plus"})
        self.assertNotIn("price_conflict", codes(out))
        self.assertIn("role", conds(rules(out)[0]))

    def test_plus_money_is_not_forced_onto_totals(self):
        out = C.compose({"markets": ["total"], "price_comfort": "long"})
        self.assertIn("totals_price", codes(out))
        self.assertEqual((rules(out)[0]["price_min"], rules(out)[0]["price_max"]),
                         (C.NEUTRAL["total"]["price_min"], C.NEUTRAL["total"]["price_max"]))

    def test_a_dog_card_beside_a_chalk_card_is_a_heads_up_and_both_stay(self):
        out = C.compose({"archetypes": ["plus_money_only", "chalk_eater"]})
        self.assertIn("stance_mix", codes(out))
        self.assertEqual(out["rule_count"], 2)

    def test_a_quirk_replaces_the_same_kind_of_condition_inside_a_card(self):
        out = C.compose({"archetypes": ["full_moon_chaos"], "quirks": ["new_moon"]})
        moons = [c["value"] for r in rules(out) for c in R.walk(r["when"]) if c["id"] == "moon_phase"]
        self.assertEqual(moons, ["new"])
        self.assertIn("quirk_replaced", codes(out))

    def test_an_nfl_card_is_left_out_when_only_mlb_was_picked(self):
        # a hound never bets a sport nobody picked (this used to run the card in NFL anyway)
        out = C.compose({"sports": ["MLB"], "archetypes": ["thursday_night_gremlins"]})
        self.assertIn("move_unavailable", codes(out))
        self.assertNotIn("sport_override", codes(out))
        self.assertEqual(out["archetypes"], [])
        self.assertTrue(all(r["sports"] == ["MLB"] for r in rules(out)))

    def test_an_mlb_only_quirk_narrows_a_both_sports_rule_and_says_so(self):
        out = C.compose({"markets": ["moneyline"], "personality": "mystic", "quirks": ["windy"]})
        self.assertEqual(rules(out)[0]["sports"], ["MLB"])
        self.assertIn("quirk_narrowed", codes(out))

    def test_a_quirk_that_cannot_apply_is_skipped_not_forced(self):
        nfl = C.compose({"sports": ["NFL"], "markets": ["moneyline"], "personality": "chaos_agent", "quirks": ["chilly"]})
        self.assertIn("quirk_skipped", codes(nfl))
        self.assertNotIn("temperature", conds(rules(nfl)[0]))
        totals = C.compose({"markets": ["total"], "quirks": ["lucky_letter"]})
        self.assertIn("quirk_skipped", codes(totals))

    def test_props_with_nfl_alone_are_left_out_with_a_reason(self):
        out = C.compose({"sports": ["NFL"], "markets": ["props"]})
        self.assertIn("props_mlb_only", codes(out))
        self.assertEqual(out["spec"]["rules"][0]["markets"], ["moneyline"])             # the starter pup, in NFL
        self.assertEqual(out["spec"]["rules"][0]["sports"], ["NFL"])

    def test_more_than_four_rules_drops_the_last_and_names_it(self):
        out = C.compose({"markets": ["mix", "props"], "personality": "steam_chaser",
                         "archetypes": ["windy_overs", "sunday_funday"]})
        self.assertEqual(out["rule_count"], R.MAX_RULES)
        warn = next(w for w in out["warnings"] if w["code"] == "rule_cap")
        self.assertIn("Sunday Funday", warn["message"])

    def test_more_than_two_cards_keep_the_first_two(self):
        out = C.compose({"archetypes": ["revenge_tour", "steam_chaser", "tired_legs", "chalk_eater", "windy_overs"]})
        self.assertEqual(out["archetypes"], ["revenge_tour", "steam_chaser"])
        self.assertIn("archetype_limit", codes(out))

    def test_bad_answers_are_dropped_with_a_warning_and_never_guessed(self):
        out = C.compose({"sports": ["NBA"], "personality": "wizard", "bets_per_day": 9, "stake": 7, "timing": "never",
                         "price_comfort": [], "markets": ["nope"], "archetypes": ["not_a_card"], "quirks": [5],
                         "letter": "ab", "look": {"coat": "neon"}})
        assert_sound(self, out)
        self.assertGreaterEqual(codes(out).count("answer_ignored"), 8)
        self.assertTrue(out["starter"])
        self.assertEqual(C.compose("not a dict")["starter"], True)
        self.assertEqual(C.compose([1, 2])["starter"], True)


class TheEnglishBoxMergesIn(unittest.TestCase):

    def test_typed_words_become_an_extra_rule_labelled_in_your_words(self):
        out = C.compose({"personality": "chalk_eater", "markets": ["moneyline"]},
                        english_text="Bet home underdogs between +120 and +200 when they're on 2+ days rest.")
        assert_sound(self, out)
        self.assertEqual(out["rule_count"], 2)
        card = out["rule_cards"][1]
        self.assertEqual((card["source"], card["label"]), ("english", C.ENGLISH_LABEL))
        self.assertEqual(rules(out)[1]["side"], "home")
        self.assertEqual((rules(out)[1]["price_min"], rules(out)[1]["price_max"]), (120, 200))

    def test_a_draft_from_post_hounds_english_merges_the_same_as_the_text(self):
        text = "Aaron Judge over 1.5 total bases when he's hit in 3 straight games"
        parsed = parser.parse(text, players=["aaron judge"])
        by_text = C.compose({}, english_text="Bet home underdogs when it's windy")
        by_draft = C.compose({}, english_draft=parser.parse("Bet home underdogs when it's windy")["draft"])
        self.assertEqual(by_text["spec"]["rules"], by_draft["spec"]["rules"])
        self.assertEqual(by_text["rule_cards"][0]["source"], "english")
        self.assertTrue(parsed["draft"]["rules"])

    def test_english_only_has_no_starter_rule_and_no_base_rule(self):
        out = C.compose({}, english_text="Only NFL spreads under 7. Max 2 bets a day")
        self.assertFalse(out["starter"])
        self.assertEqual([c["source"] for c in out["rule_cards"]], ["english"])

    def test_a_number_in_the_words_replaces_the_quiz_answer_and_says_so(self):
        out = C.compose({"personality": "mystic", "bets_per_day": 2}, english_text="also bet unders. Max 4 bets a day")
        self.assertEqual(out["settings"]["max_bets_per_day"], 4)
        warn = next(w for w in out["warnings"] if w["code"] == "english_override")
        self.assertIn("later answer wins", warn["message"])
        quiet = C.compose({"personality": "mystic"}, english_text="also bet unders. Max 4 bets a day")
        self.assertEqual(quiet["settings"]["max_bets_per_day"], 4)
        self.assertNotIn("english_override", codes(quiet))                # nothing was answered, so nothing was replaced

    def test_words_the_parser_cannot_read_are_reported(self):
        out = C.compose({"personality": "mystic"}, english_text="bet when Mercury is in retrograde")
        self.assertIn("english_not_understood", codes(out))
        assert_sound(self, out)

    def test_extra_english_rules_past_the_cap_are_dropped_and_named(self):
        out = C.compose({"markets": ["mix"], "archetypes": ["windy_overs", "steam_chaser"]},
                        english_text="Bet home underdogs. Bet road favourites. Bet the over when it's windy.")
        self.assertEqual(out["rule_count"], R.MAX_RULES)
        self.assertIn("rule_cap", codes(out))

    def test_a_hostile_draft_cannot_break_or_bypass_the_validator(self):
        evil = {"rules": [{"markets": ["moneyline"], "sports": ["MLB"], "side": "either", "price_min": -300,
                           "price_max": 100},
                          {"markets": ["bogus"], "sports": ["MLB"]}, "not a rule", 7,
                          {"label": 5, "markets": ["moneyline"], "sports": ["MLB"], "side": "either", "price_min": -150,
                           "price_max": 200}],
                "max_bets_per_day": 99, "stake_units": "lots", "rank_by": "luck", "color": "red", "extra": 1}
        out = C.compose({"personality": "chaos_agent"}, english_draft=evil)
        assert_sound(self, out)
        self.assertGreaterEqual(codes(out).count("rule_refused"), 2)
        self.assertEqual(out["spec"]["max_bets_per_day"], 3)              # the refused 99 fell back to the personality's
        self.assertEqual(out["spec"]["rank_by"], "earliest_lock")
        self.assertEqual(out["spec"]["stake_units"], 1.0)
        self.assertNotIn("extra", out["spec"])
        huge = {"rules": [{"markets": ["moneyline"], "sports": ["MLB"], "side": "home", "price_min": -150,
                           "price_max": 200}] * 50}
        assert_sound(self, C.compose({}, english_draft=huge))


class NamesAndLooks(unittest.TestCase):

    def test_suggestions_come_from_the_personality_pool_and_skip_taken_names(self):
        free = C.compose({"personality": "mystic"})
        pool = LIB["name_pools"]["mystic"]
        self.assertTrue(set(free["name_suggestions"]) <= set(pool))
        self.assertEqual(len(free["name_suggestions"]), 3)
        first = free["name_suggestions"][0]
        taken = C.compose({"personality": "mystic"}, taken_names=[first])
        self.assertNotIn(first, taken["name_suggestions"])
        self.assertNotEqual(taken["spec"]["name"], first)

    def test_a_good_name_is_kept_and_a_refused_one_is_replaced_with_a_warning(self):
        self.assertEqual(C.compose({"name": "Biscuit Boss"})["spec"]["name"], "Biscuit Boss")
        for bad in ("Yankees Fan", "x", "a" * 40, "Official Hound", "Dog!!"):
            out = C.compose({"name": bad})
            self.assertIn("name_rejected", codes(out), bad)
            self.assertNotEqual(out["spec"]["name"], bad)
        taken = C.compose({"name": "Biscuit Boss"}, taken_names=["biscuit boss"])
        self.assertIn("name_rejected", codes(taken))

    def test_the_catchphrase_is_validated_and_defaults_from_the_personality(self):
        self.assertEqual(C.compose({"personality": "chalk_eater"})["spec"]["tagline"], "Eats the chalk. Never -200 or worse.")
        bad = C.compose({"tagline": "fuck this"})
        self.assertIn("tagline_rejected", codes(bad))
        self.assertEqual(bad["spec"]["tagline"], "")
        self.assertEqual(C.compose({"tagline": "Good dog."})["spec"]["tagline"], "Good dog.")

    def test_the_look_follows_the_picks_and_stays_on_the_whitelist(self):
        out = C.compose({"look": {"coat": "golden", "accessory": "sunglasses"}, "personality": "mystic"})
        self.assertEqual((out["look"]["coat"], out["look"]["face"]), ("golden", "sunglasses"))
        self.assertEqual(out["look"]["bg"], "violet")                      # the mystic's own tile
        other = C.compose({"look": {"coat": "red", "accessory": "hoodie"}})
        self.assertEqual((other["look"]["coat"], other["look"]["body"]), ("red", "hoodie"))


class NoComboCanBreakTheHardLines(unittest.TestCase):

    def test_a_seeded_sweep_of_random_answers_always_validates_and_never_reaches_minus_200(self):
        rng = random.Random(20261019)
        sports_opts = [None, ["MLB"], ["NFL"], ["MLB", "NFL"]]
        for i in range(160):
            answers = {
                "sports": rng.choice(sports_opts),
                "markets": rng.sample([m["id"] for m in LIB["markets"]], rng.randint(0, 3)),
                "personality": rng.choice([None] + [p["id"] for p in LIB["personalities"]]),
                "bets_per_day": rng.choice([None, 1, 2, 3, 4, 5]),
                "stake": rng.choice([None, 0.5, 1, 1.5, 2, 2.5, 3]),
                "price_comfort": rng.choice([None] + [c["id"] for c in LIB["price_comforts"]]),
                "timing": rng.choice([None, "early", "late"]),
                "archetypes": rng.sample([a["id"] for a in LIB["archetypes"]], rng.randint(0, 3)),
                "quirks": rng.sample([q["id"] for q in LIB["quirks"]], rng.randint(0, 4)),
                "letter": rng.choice([None, "Q", "m"]),
            }
            with self.subTest(i=i, answers=answers):
                assert_sound(self, C.compose(answers))

    def test_compose_never_builds_a_band_the_validator_would_refuse(self):
        # even when the library itself were edited to a bad price, the validator's refusal becomes a warning
        bad = json.loads(json.dumps(LIB))
        bad["price_comforts"][0]["price_min"] = -300
        out = C.compose({"markets": ["moneyline"], "price_comfort": "short"}, lib=bad)
        self.assertIn("rule_refused", codes(out))
        assert_sound(self, out)


if __name__ == "__main__":
    unittest.main()
