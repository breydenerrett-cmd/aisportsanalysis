"""The quiz offers every sport (src/hounds/quiz/fit.py, moves.py, library sports table, compose).

Three things are held here, FastAPI-free (the doors are covered in test_hounds_quiz_api.py):

  * the sport question lists EVERY dog-menu family in the catalog plus "Any sport", most popular first, the rest under More;
  * the SWEEP: every archetype crossed with every sport set composes a hound the real validator accepts, with no rule the
    composer had to repair (a refused rule would mean the fit let one through that cannot run);
  * question 6: four move cards at a time, each valid for the sports picked, ranked by the earlier answers, cycling, and a
    Pick for me that takes the top one. A move that is offered is a move that composes.
"""
from __future__ import annotations

import unittest

from src.hounds import user_rules as R
from src.hounds import user_spec
from src.hounds.quiz import compose as C
from src.hounds.quiz import fit
from src.hounds.quiz import library as L
from src.hounds.quiz import moves as M

LIB = L.load()
FAMILIES = list(user_spec.SPORTS)
MIX_SETS = [["NBA", "NFL"], ["MLB", "NFL"], ["TENNIS", "MMA"], ["SOCCER", "TENNIS", "NBA"], ["NHL", "MLB"],
            ["MLB", "TENNIS"], ["NCAAF", "NFL", "NBA", "MMA"], ["NBA", "NHL", "MLB", "NFL", "SOCCER"]]
SPORT_SETS = [[f] for f in FAMILIES] + [["ANY"]] + MIX_SETS
POPULAR = ["NBA", "NFL", "NHL", "NCAAF", "SOCCER", "TENNIS", "MLB", "MMA"]
# the families that differ in what they post or read (the rest behave like NBA); the base-rule sweep is the wide one
KINDS_OF_SPORT = [["MLB"], ["NFL"], ["NCAAF"], ["NBA"], ["SOCCER"], ["TENNIS"], ["MMA"], ["CRICKET"], ["ANY"]] + MIX_SETS
REPAIR_CODES = {"rule_refused", "setting_refused", "tagline_rejected"}


def codes(out):
    return [w["code"] for w in out["warnings"]]


def condition_ids(rule):
    return [c["id"] for c in R.walk(rule.get("when"))]


class TheSportQuestionOffersEverySport(unittest.TestCase):

    def test_every_dog_menu_family_is_offered_and_nothing_else(self):
        offered = [c["value"] for c in L.sport_choices(LIB)]
        self.assertEqual(sorted(offered), sorted(FAMILIES))
        self.assertGreaterEqual(len(offered), 17)

    def test_the_popular_eight_come_first_in_the_owners_order_then_more(self):
        rows = L.sport_choices(LIB)
        self.assertEqual([r["value"] for r in rows[:8]], POPULAR)
        self.assertTrue(all(r["popular"] and not r["more"] for r in rows[:8]))
        self.assertTrue(all(r["more"] and not r["popular"] for r in rows[8:]))
        self.assertEqual(next(r for r in rows if r["value"] == "NCAAF")["label"], "College football")

    def test_every_sport_has_a_label_and_a_short_badge(self):
        for row in L.sport_choices(LIB):
            with self.subTest(sport=row["value"]):
                self.assertTrue(row["label"].strip())
                self.assertTrue(row["badge"].strip())
                self.assertLessEqual(len(row["badge"]), 10)

    def test_any_sport_is_its_own_choice_and_the_library_check_is_clean(self):
        self.assertEqual(L.any_sport_choice(LIB)["value"], user_spec.ANY)
        self.assertEqual(L.any_sport_choice(LIB)["label"], "Any sport")
        self.assertEqual(L.validate_library(LIB), [])
        public = L.public_library(LIB)
        self.assertEqual([s["value"] for s in public["sports"]][:8], POPULAR)
        self.assertEqual(public["sports_any"]["value"], user_spec.ANY)

    def test_the_sport_answer_takes_many_or_any_and_refuses_the_rest(self):
        warnings: list = []
        ans = C.clean_answers({"sports": ["NBA", "TENNIS", "NBA", "CURLING"]}, LIB, warnings)
        self.assertEqual(ans["sports"], ["NBA", "TENNIS"])
        self.assertIn("answer_ignored", [w["code"] for w in warnings])
        every = C.clean_answers({"sports": ["ANY"]}, LIB, [])
        self.assertEqual(every["sports"], FAMILIES)
        self.assertTrue(every["sports_any"])


class EveryArchetypeComposesForEverySportSet(unittest.TestCase):
    """The sweep: 42 archetypes against every family on its own, Any sport and eight mixed sets."""

    def test_every_archetype_times_every_sport_set_passes_the_validator(self):
        problems: list = []
        checked = 0
        no_home = L.no_home_side(LIB)
        for sports in SPORT_SETS:
            resolved = fit.resolve_sports(sports)
            for arch in LIB["archetypes"]:
                where = f"{sports if len(sports) < 4 else f'{len(sports)} sports'} x {arch['id']}"
                checked += 1
                try:
                    out = C.compose({"sports": sports, "archetypes": [arch["id"]]})
                    user_spec.validate_spec(out["spec"])                     # the real gate, again, on the finished spec
                except user_spec.SpecError as exc:
                    problems.append(f"{where}: validator refused {exc.errors}")
                    continue
                if REPAIR_CODES & set(codes(out)):
                    problems.append(f"{where}: the composer had to repair a rule: {codes(out)}")
                if any(not set(rule["sports"]) <= set(resolved) for rule in out["spec"]["rules"]):
                    problems.append(f"{where}: a rule covers a sport nobody picked")
                runs = fit.archetype_rules(arch, resolved, no_home)["rules"]
                if runs and (arch["id"] not in out["archetypes"] or "move_unavailable" in codes(out)):
                    problems.append(f"{where}: a move that runs was left out")
                if not runs and (arch["id"] in out["archetypes"] or "move_unavailable" not in codes(out)):
                    problems.append(f"{where}: a move that cannot run was kept or not explained")
        self.assertEqual(problems, [])
        self.assertEqual(checked, len(SPORT_SETS) * len(LIB["archetypes"]))
        self.assertGreater(checked, 900)

    def test_every_personality_market_and_sport_set_composes_without_a_repair(self):
        problems: list = []
        comforts = [None] + [c["id"] for c in LIB["price_comforts"]][:2]
        for sports in KINDS_OF_SPORT:
            resolved = set(fit.resolve_sports(sports))
            for market in [None] + [m["id"] for m in LIB["markets"]]:
                for pers in [None] + [p["id"] for p in LIB["personalities"]]:
                    for comfort in comforts:
                        answers = {"sports": sports}
                        if market:
                            answers["markets"] = [market]
                        if pers:
                            answers["personality"] = pers
                        if comfort:
                            answers["price_comfort"] = comfort
                        try:
                            out = C.compose(answers)
                            user_spec.validate_spec(out["spec"])
                        except user_spec.SpecError as exc:
                            problems.append(f"{answers}: validator refused {exc.errors}")
                            continue
                        if REPAIR_CODES & set(codes(out)):
                            problems.append(f"{answers}: repaired {codes(out)}")
                        if any(not set(r["sports"]) <= resolved for r in out["spec"]["rules"]):
                            problems.append(f"{answers}: a rule covers a sport nobody picked")
        self.assertEqual(problems, [])

    def test_a_market_a_sport_does_not_post_is_said_and_never_faked(self):
        out = C.compose({"sports": ["TENNIS"], "markets": ["total"]})
        self.assertIn("market_unavailable", codes(out))
        self.assertTrue(out["starter"])
        self.assertEqual(out["spec"]["rules"][0]["markets"], ["moneyline"])
        soccer = C.compose({"sports": ["SOCCER"], "markets": ["mix"], "personality": "chalk_eater"})
        markets = {m for r in soccer["spec"]["rules"] for m in r["markets"]}
        self.assertTrue({"moneyline", "total"} <= markets)                       # what soccer posts is bet
        tennis_mix = C.compose({"sports": ["TENNIS"], "markets": ["mix"]})
        self.assertEqual({m for r in tennis_mix["spec"]["rules"] for m in r["markets"]} - {"spread"}, {"moneyline"})
        self.assertIn("market_unavailable", codes(tennis_mix))                   # the totals it cannot bet, said once

    def test_a_home_or_away_rule_is_never_asked_of_tennis_or_mmaand_nfl_stays_whole(self):
        for sport in L.no_home_side(LIB):
            out = C.compose({"sports": [sport], "archetypes": ["home_dog_howl"]})
            self.assertIn("move_unavailable", codes(out))
            for rule in out["spec"]["rules"]:
                self.assertNotIn(rule["side"], ("home", "away"))
        nfl = C.compose({"sports": ["NFL"], "archetypes": ["home_dog_howl"]})
        self.assertIn("home_dog_howl", nfl["archetypes"])

    def test_mlb_and_nfl_only_stat_conditions_drop_out_or_go_generic_elsewhere(self):
        mlb_nfl_only = {c.id for c in R.CONDITIONS if not c.any_sport}
        self.assertTrue(mlb_nfl_only)
        for sports in ([f] for f in FAMILIES if f not in user_spec.LEGACY_SPORTS):
            for arch in LIB["archetypes"]:
                out = C.compose({"sports": sports[0:1], "archetypes": [arch["id"]]})
                for rule in out["spec"]["rules"]:
                    for cid in condition_ids(rule):
                        self.assertTrue(R.BY_ID[cid].any_sport or rule["sports"][0] in R.BY_ID[cid].sports,
                                        (sports, arch["id"], cid))
        road = C.compose({"sports": ["NBA"], "archetypes": ["road_warriors"]})
        self.assertIn("road_warriors", road["archetypes"])
        self.assertIn("move_generic", codes(road))
        self.assertNotIn("split_pct", [c for r in road["spec"]["rules"] for c in condition_ids(r)])
        mlb = C.compose({"sports": ["MLB"], "archetypes": ["road_warriors"]})
        self.assertIn("split_pct", [c for r in mlb["spec"]["rules"] for c in condition_ids(r)])
        self.assertNotIn("move_generic", codes(mlb))

    def test_a_move_that_repeats_the_personalitys_own_rule_is_counted_once(self):
        out = C.compose({"sports": ["NBA", "NFL", "TENNIS"], "markets": ["moneyline"], "personality": "chalk_eater",
                         "archetypes": ["chalk_eater"]})
        self.assertEqual(out["rule_count"], 1)
        self.assertIn("rule_repeated", codes(out))
        self.assertIn("chalk_eater", out["archetypes"])                       # still picked, still named
        other = C.compose({"sports": ["NBA"], "markets": ["moneyline"], "personality": "chalk_eater", "archetypes": ["steam_chaser"]})
        self.assertEqual(other["rule_count"], 2)
        self.assertNotIn("rule_repeated", codes(other))

    def test_personality_base_rules_go_generic_for_a_sport_without_form_data(self):
        out = C.compose({"sports": ["NBA"], "markets": ["moneyline"], "personality": "stats_nerd"})
        self.assertIn("base_generic", codes(out))
        nba_ids = {c for r in out["spec"]["rules"] for c in condition_ids(r)}
        self.assertTrue(all(R.BY_ID[c].any_sport or "NBA" in R.BY_ID[c].sports for c in nba_ids), nba_ids)
        both = C.compose({"sports": ["NBA", "MLB"], "markets": ["moneyline"], "personality": "stats_nerd"})
        self.assertEqual({tuple(r["sports"]) for r in both["spec"]["rules"]} - {("NBA",), ("MLB",)}, set())


class QuestionSixShowsFourMoves(unittest.TestCase):

    def test_exactly_four_cards_a_page_each_with_a_name_a_short_line_and_a_sport_badge(self):
        for sports in SPORT_SETS:
            out = M.suggest({"sports": sports})
            with self.subTest(sports=sports if len(sports) < 4 else f"{len(sports)} sports"):
                self.assertEqual(len(out["moves"]), M.PAGE)
                for card in out["moves"]:
                    self.assertTrue(card["name"].strip())
                    self.assertTrue(card["sport_badge"].strip())
                    self.assertTrue(0 < len(card["short"].split()) <= L.SHORT_MAX_WORDS, card["short"])
                    self.assertTrue(card["english"].strip())                    # the full rule, for "How it works"
                    self.assertTrue(card["sentences"])

    def test_show_me_4_others_pages_through_every_valid_move_and_wraps(self):
        answers = {"sports": ["NBA", "NHL"]}
        first = M.suggest(answers)
        total, pages = first["total"], first["pages"]
        self.assertEqual(pages, -(-total // M.PAGE))
        seen: list = []
        page = 0
        for _ in range(pages):
            out = M.suggest(answers, page=page)
            self.assertEqual(out["page"], page)
            self.assertEqual(len(out["moves"]), M.PAGE)
            seen.extend(c["id"] for c in out["moves"])
            page = out["next_page"]
        self.assertEqual(page, 0)                                                # one full lap, back at the start
        self.assertEqual(set(seen), set(first["order"]))                         # every valid move was shown
        self.assertEqual(M.suggest(answers, page=pages)["moves"], first["moves"])  # past the end wraps to the first
        self.assertEqual(M.suggest(answers, page=-1)["page"], pages - 1)

    def test_a_card_on_a_page_is_not_repeated_on_it(self):
        for sports in (["MLB"], ["NFL"], ["ANY"], ["NBA"], ["TENNIS"]):
            out = M.suggest({"sports": sports})
            for page in range(out["pages"]):
                ids = [c["id"] for c in M.suggest({"sports": sports}, page=page)["moves"]]
                self.assertEqual(len(ids), len(set(ids)), (sports, page))

    def test_only_moves_that_can_run_in_the_sports_picked_are_offered(self):
        tennis = M.suggest({"sports": ["TENNIS"]})
        names = {c["id"] for c in tennis["moves"]}
        self.assertTrue(set(tennis["order"]) >= names)
        for dead in ("windy_overs", "hot_bat_props", "thursday_night_gremlins", "home_dog_howl", "tired_legs"):
            self.assertNotIn(dead, tennis["order"])
        nba = M.suggest({"sports": ["NBA"]})
        for dead in ("windy_overs", "hot_bat_props", "bye_week_believer"):
            self.assertNotIn(dead, nba["order"])
        self.assertIn("road_warriors", nba["order"])                             # runs on its generic variant
        mlb = M.suggest({"sports": ["MLB"]})
        self.assertIn("windy_overs", mlb["order"])
        self.assertGreater(mlb["total"], nba["total"])

    def test_every_offered_move_composes_and_stays_in_the_hound(self):
        refused_anywhere: list = []
        for sports in SPORT_SETS:
            entries, refused = M.valid_moves({"sports": sports}, LIB)
            refused_anywhere.extend(refused)
            resolved = fit.resolve_sports(sports)
            for arch, fitted, sentences in entries:
                out = C.compose({"sports": sports, "archetypes": [arch["id"]]})
                with self.subTest(sports=sports if len(sports) < 4 else f"{len(sports)} sports", move=arch["id"]):
                    self.assertIn(arch["id"], out["archetypes"])
                    self.assertTrue(sentences)
                    self.assertTrue(set(fitted["covers"]) <= set(resolved))
        self.assertEqual(refused_anywhere, [])

    def test_the_badge_names_the_sports_the_move_covers(self):
        nba = {c["id"]: c for c in M.suggest({"sports": ["NBA"]}, page=0)["moves"]}
        for card in nba.values():
            self.assertEqual(card["sports"], ["NBA"])
            self.assertEqual(card["sport_badge"], "NBA")
        every = M.suggest({"sports": ["ANY"]})
        anywhere = [c for p in range(every["pages"]) for c in M.suggest({"sports": ["ANY"]}, page=p)["moves"]]
        self.assertIn("Any sport", {c["sport_badge"] for c in anywhere})
        mlb_only = next(c for c in anywhere if c["id"] == "tired_legs")
        self.assertEqual(mlb_only["sport_badge"], "MLB")

    def test_the_order_follows_the_earlier_answers(self):
        dog = M.suggest({"sports": ["NBA"], "personality": "underdog_hunter", "price_comfort": "plus"})["order"]
        chalk = M.suggest({"sports": ["NBA"], "personality": "chalk_eater", "price_comfort": "short"})["order"]
        self.assertLess(dog.index("plus_money_only"), dog.index("chalk_eater"))
        self.assertLess(chalk.index("chalk_eater"), chalk.index("plus_money_only"))
        self.assertNotEqual(dog[:4], chalk[:4])
        totals = M.suggest({"sports": ["NBA"], "markets": ["total"]})["order"]
        self.assertIn(totals.index("under_the_lights"), range(0, 4))
        self.assertGreater(totals.index("chalk_eater"), totals.index("under_the_lights"))

    def test_a_pick_that_no_longer_runs_is_reported_dropped(self):
        out = M.suggest({"sports": ["TENNIS"], "archetypes": ["windy_overs", "steam_chaser"]})
        self.assertEqual(out["dropped"], ["windy_overs"])

    def test_the_markets_the_sports_post_are_told_to_the_page(self):
        self.assertEqual(M.suggest({"sports": ["TENNIS"]})["markets_available"], ["moneyline", "mix"])
        self.assertEqual(M.suggest({"sports": ["SOCCER"]})["markets_available"], ["moneyline", "total", "mix"])
        self.assertEqual(M.suggest({"sports": ["MLB"]})["markets_available"],
                         ["moneyline", "spread", "total", "props", "mix"])
        self.assertNotIn("props", M.suggest({"sports": ["NBA", "NFL"]})["markets_available"])

    def test_the_pick_limit_is_one_with_an_optional_second(self):
        self.assertEqual(L.PICK_LIMIT, 2)
        self.assertEqual(M.suggest({})["pick_limit"], 2)


class PickForMe(unittest.TestCase):

    def test_pick_for_me_takes_the_top_move_deterministically(self):
        for answers in ({}, {"sports": ["NBA"]}, {"sports": ["MLB", "NFL"], "personality": "mystic"},
                        {"sports": ["TENNIS"], "price_comfort": "plus"}):
            with self.subTest(answers=answers):
                first = M.pick_for_me(answers)
                self.assertEqual(first, M.pick_for_me(answers))
                page = M.suggest(answers)
                self.assertEqual(first["id"], page["recommended"])
                self.assertEqual(first["id"], page["moves"][0]["id"])
                self.assertEqual(first["card"]["id"], first["id"])
                self.assertEqual(page["recommended_card"]["id"], first["id"])

    def test_the_pick_fits_the_personality_and_composes(self):
        chalk = M.pick_for_me({"sports": ["NBA"], "personality": "chalk_eater", "price_comfort": "short"})
        self.assertEqual(chalk["card"]["stance"], "chalk")
        dog = M.pick_for_me({"sports": ["NBA"], "personality": "underdog_hunter"})
        self.assertEqual(dog["card"]["stance"], "dog")
        for pick in (chalk, dog):
            out = C.compose({"sports": ["NBA"], "archetypes": [pick["id"]]})
            self.assertIn(pick["id"], out["archetypes"])
            user_spec.validate_spec(out["spec"])


if __name__ == "__main__":
    unittest.main()
