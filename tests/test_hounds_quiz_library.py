"""The hound quiz's rule library (config/hounds_archetypes.json, src/hounds/quiz/library.py).

Every archetype is a spec fragment the real builder must accept: this module pushes EVERY one through the real validator
(`user_spec.validate_spec`, the same gate a created dog goes through) and checks the hard lines (no price at -200 or worse,
no claim of profit or edge, paper only), that the English beside each card is the renderer's output and not hand-written,
and that every answer table (personalities, quirks, markets...) is something the builder menu accepts.
"""
from __future__ import annotations

import copy
import json
import re
import unittest

from src.hounds import user_rules as R
from src.hounds import user_spec
from src.hounds.english import render
from src.hounds.interact import look as look_mod
from src.hounds.quiz import compose, fit, library as L

LIB = L.load()


def walk_numbers(node, key_names, found):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in key_names and isinstance(v, (int, float)):
                found.append(v)
            walk_numbers(v, key_names, found)
    elif isinstance(node, list):
        for v in node:
            walk_numbers(v, key_names, found)
    return found


def all_strings(node, out):
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, dict):
        for v in node.values():
            all_strings(v, out)
    elif isinstance(node, list):
        for v in node:
            all_strings(v, out)
    return out


class EveryArchetypeIsOnTheRealMenu(unittest.TestCase):

    def test_there_are_at_least_thirty_and_the_named_ideas_are_among_them(self):
        names = {a["name"] for a in LIB["archetypes"]}
        self.assertGreaterEqual(len(LIB["archetypes"]), 30)
        for wanted in ("Revenge Tour", "Primetime Underdog", "Steam Chaser", "Fade the Public Darling", "Tired Legs",
                       "Road Warriors", "Hot Bat Props", "Strikeout King", "Windy Overs", "Full Moon Chaos",
                       "Coin Flip Gremlin", "Lucky Letters", "Sunday Funday", "Plus Money Only", "Chalk Eater"):
            self.assertIn(wanted, names)

    def test_every_fragment_validates_against_the_real_validator(self):
        for a in LIB["archetypes"]:
            with self.subTest(archetype=a["id"]):
                spec = user_spec.validate_spec(L.draft_spec(a["fragment"]))
                self.assertEqual(spec["version"], user_spec.SPEC_VERSION_V2)
                self.assertTrue(1 <= len(spec["rules"]) <= R.MAX_RULES)
                # the spec is what the engine reads: every rule keeps its sports inside works_in
                for rule in spec["rules"]:
                    self.assertTrue(set(rule["sports"]) <= set(fit.resolve_sports(a["works_in"])), a["id"])

    def test_the_library_check_is_clean_and_it_catches_a_bad_fragment(self):
        self.assertEqual(L.validate_library(), [])
        broken = copy.deepcopy(LIB)
        broken["archetypes"][0]["fragment"]["rules"][0]["price_min"] = -250
        problems = L.validate_library(broken)
        self.assertTrue(any("refuses" in p for p in problems), problems)
        unknown = copy.deepcopy(LIB)
        unknown["archetypes"][1]["fragment"]["rules"][0]["when"]["items"][0] = {"id": "not_a_condition"}
        self.assertTrue(any("refuses" in p for p in L.validate_library(unknown)))
        claimy = copy.deepcopy(LIB)
        claimy["archetypes"][2]["pitch"] = "A guaranteed edge on every game."
        self.assertTrue(any("claim" in p for p in L.validate_library(claimy)))

    def test_the_english_beside_each_card_is_generated_by_the_renderer(self):
        for a in L.archetypes():
            with self.subTest(archetype=a["id"]):
                spec = L.validate_fragment(a["spec_fragment"])
                self.assertEqual(a["sentences"], render.rule_sentences(spec))
                self.assertEqual(a["english"], " ".join(render.rule_sentences(spec)))
                if any(r["price_min"] < 0 for r in spec["rules"]):
                    self.assertIn("never -200 or worse", a["english"])
                self.assertEqual(a["rule_count"], len(spec["rules"]))

    def test_ids_are_unique_and_names_fit_a_dog_name(self):
        ids = [a["id"] for a in LIB["archetypes"]]
        self.assertEqual(len(ids), len(set(ids)))
        for a in LIB["archetypes"]:
            self.assertRegex(a["name"], r"^[A-Za-z0-9][A-Za-z0-9 \-]*$")

    def test_the_icon_keys_are_all_known(self):
        for table in ("archetypes", "personalities", "markets", "price_comforts", "quirks", "timings"):
            for row in LIB[table]:
                self.assertIn(row["icon"], L.ICON_KEYS, f"{table}.{row['id']}")


class TheHardLines(unittest.TestCase):

    def test_no_price_in_the_library_reaches_minus_200(self):
        prices = walk_numbers(LIB, {"price_min", "price_max"}, [])
        self.assertGreater(len(prices), 60)
        for p in prices:
            self.assertFalse(p < 0 and p <= user_spec.MAX_FAVOURITE_PRICE, p)
        # and the shortest any archetype or comfort offers is the cap's own edge
        self.assertGreaterEqual(min(prices), user_spec.SHORTEST_ALLOWED_PRICE)

    def test_the_chalk_cards_say_the_cap_in_their_own_words(self):
        by_id = {a["id"]: a for a in LIB["archetypes"]}
        self.assertIn("-199", by_id["chalk_eater"]["pitch"])
        self.assertIn("-200", by_id["chalk_eater"]["pitch"])
        self.assertEqual(by_id["chalk_eater"]["fragment"]["rules"][0]["price_min"], -199)

    def test_no_copy_makes_a_claim_of_profit_or_edge(self):
        for text in all_strings({k: LIB[k] for k in ("archetypes", "personalities", "markets", "price_comforts", "quirks",
                                                     "timings", "name_pools")}, []):
            for pat in L.CLAIM_PATTERNS:
                self.assertIsNone(re.search(pat, text.lower()), f"{pat!r} in {text!r}")
        public = json.dumps(L.public_library())
        self.assertNotRegex(public.lower(), r"\bedge\b|\bprofit|guarantee")

    def test_the_library_is_paper_only_and_says_no_card_is_known_to_win(self):
        pub = L.public_library()
        self.assertTrue(pub["paper_only"])
        self.assertIn("Paper only", pub["not_advice"])
        self.assertIn("none of these is known to win", pub["honesty"])
        self.assertIn("-200", pub["price_cap_note"])

    def test_copy_has_no_emoji(self):
        for text in all_strings(L.public_library(), []):
            self.assertIsNone(re.search(r"[^\x00-\x7f]", text), text)


class TheAnswerTablesAreOnTheMenu(unittest.TestCase):

    def test_each_personality_recipe_makes_a_valid_rule_for_every_kind_and_sport_choice(self):
        kinds = {"ml": ["moneyline", "spread"], "total": ["total"], "prop": ["batter_hits", "pitcher_strikeouts"]}
        for p in LIB["personalities"]:
            for sports in (["MLB"], ["NFL"], ["MLB", "NFL"]):
                for kind, markets in kinds.items():
                    if kind == "prop" and sports != ["MLB"]:
                        continue
                    rule = compose._base_rule(kind, markets, p, None, sports, [])
                    with self.subTest(personality=p["id"], kind=kind, sports=sports):
                        spec = {"version": 2, "name": "Test Pup", "rules": [rule]}
                        try:
                            user_spec.validate_spec(spec)
                        except user_spec.SpecError as exc:
                            # an MLB-only condition on an NFL rule is narrowed by the quiz, never shipped as is
                            self.assertTrue(any("MLB" in v or "only" in v for v in exc.errors.values()), exc.errors)

    def test_each_quirk_validates_wherever_it_says_it_applies(self):
        for q in LIB["quirks"]:
            for kind in q["kinds"]:
                markets = {"ml": ["moneyline"], "total": ["total"], "prop": ["batter_hits"]}[kind]
                for sport in q["sports"]:
                    if kind == "prop" and sport != "MLB":
                        continue
                    rule = {"label": "", "sports": [sport], "markets": markets, "side": "either", "price_min": -150,
                            "price_max": 250, "line_min": None, "line_max": None, "min_books": 1,
                            "when": {"op": "all", "items": [copy.deepcopy(q["condition"])]}}
                    with self.subTest(quirk=q["id"], kind=kind, sport=sport):
                        user_spec.validate_spec({"version": 2, "name": "Test Pup", "rules": [rule]})

    def test_personality_colours_and_badges_are_on_the_menu_and_breeds_exist(self):
        breeds = {"retriever", "bulldog", "schnauzer", "husky", "mutt", "hound", "bloodhound"}
        for p in LIB["personalities"]:
            self.assertIn(p["color"], R.COLOR_IDS)
            self.assertIn(p["badge"], R.BADGE_IDS)
            self.assertIn(p["breed"], breeds)
            self.assertIn(p["rank_by"], R.RANK_RULES)
            self.assertTrue(1 <= p["bets_hint"] <= 5)
        self.assertEqual({p["id"] for p in LIB["personalities"]},
                         {"underdog_hunter", "chalk_eater", "chaos_agent", "stats_nerd", "steam_chaser", "mystic", "gematria"})

    def test_looks_are_on_the_locker_room_whitelist(self):
        for coat in LIB["looks"]["coats"]:
            self.assertIn(coat, look_mod.COATS)
        for acc in LIB["looks"]["accessories"]:
            look_mod.validate_look({**look_mod.DEFAULT_LOOK, **acc["look"]})

    def test_timings_and_markets(self):
        self.assertEqual({t["lock_minutes"] for t in LIB["timings"]} - set(user_spec.LOCK_CHOICES), set())
        self.assertEqual({m["id"] for m in LIB["markets"]}, {"moneyline", "spread", "total", "props", "mix"})
        for m in LIB["markets"]:
            for market in m["markets"]:
                self.assertIn(market, R.ALL_MARKETS)

    def test_every_suggested_name_passes_the_real_name_checks(self):
        for pool, names in LIB["name_pools"].items():
            for name in names:
                with self.subTest(pool=pool, name=name):
                    self.assertIsNone(compose._name_ok(name, []))

    def test_a_quirk_card_shows_the_renderers_words_for_its_condition(self):
        for q in L.public_library()["quirks"]:
            self.assertTrue(q["english"], q["id"])
        weather = next(q for q in L.public_library()["quirks"] if q["id"] == "windy")
        self.assertIn("12 mph", weather["english"])


class TheRiskChoiceMapsToRealAnswers(unittest.TestCase):
    """OWNER RULING 2026-10-21 (four-step quiz): the one risk question maps to a price band, a stake and a bets-a-day cap. The table lives in
    the library (`risk_levels`), so the page owns no number; every level must be something the composer and the real validator accept."""

    def test_the_library_serves_three_levels_and_validates(self):
        self.assertEqual(L.validate_library(), [])
        levels = L.public_library()["risk_levels"]
        self.assertEqual([r["id"] for r in levels], ["steady", "balanced", "bold"])
        for r in levels:
            self.assertIn(r["stake"], R.STAKE_CHOICES)
            self.assertIn(r["price_comfort"], {c["id"] for c in LIB["price_comforts"]})

    def test_a_level_that_names_a_missing_comfort_or_a_stake_off_the_menu_is_a_library_problem(self):
        bad = copy.deepcopy(LIB)
        bad["risk_levels"][0]["price_comfort"] = "nowhere"
        bad["risk_levels"][1]["stake"] = 0.7
        problems = L.validate_library(bad)
        self.assertTrue(any("unknown price comfort" in p for p in problems), problems)
        self.assertTrue(any("not a builder stake" in p for p in problems), problems)

    def test_every_personality_at_every_level_composes_a_valid_spec(self):
        for p in LIB["personalities"]:
            for r in LIB["risk_levels"]:
                with self.subTest(personality=p["id"], risk=r["id"]):
                    answers = {"sports": ["MLB"], "personality": p["id"], "markets": ["moneyline"], "bets_per_day": r["bets_per_day"], "stake": r["stake"]}
                    if p.get("stance") not in ("chalk", "dog") and not p.get("style"):      # the page leaves the price band to a style that owns one
                        answers["price_comfort"] = r["price_comfort"]
                    res = compose.compose(answers)
                    user_spec.validate_spec(res["spec"])
                    self.assertEqual([w["code"] for w in res["warnings"] if w["level"] == "heads_up"], [])


if __name__ == "__main__":
    unittest.main()
