"""The quiz's two doors and the expert presets (owner request, LINEHOUND, 2026-10-25).

  * "Describe it first": one sentence goes to the English reader (src/hounds/quiz/describe.py). The follow-up questions are the
    ones the draft leaves open, by plain rules. A hockey sentence asks for the risk and the name, NOT the sports.
  * "Expert presets": Hockey Pro, Basketball Pro and Football Pro are whole specs in config/hounds_archetypes.json. Each one must
    pass the real validator, and none may reach -200.

Pure Python, no FastAPI: the route itself is a thin wrapper (api/hounds_quiz.py) pinned elsewhere.
"""
from __future__ import annotations

import copy
import re
import unittest

from tests.hounds_web_runner import HAS_NODE

from src.hounds import user_spec
from src.hounds.quiz import compose as C
from src.hounds.quiz import describe as D
from src.hounds.quiz import library as L
from tests.hounds_web_runner import WEB

LIB = L.load()
LEVELS = LIB["risk_levels"]
HTML = (WEB / "quiz.html").read_text(encoding="utf-8")
PRESET = {p["id"]: p for p in LIB["expert_presets"]}


def qids(out):
    return [x["id"] for x in out["questions"]]


class FollowUpSelector(unittest.TestCase):

    def test_a_hockey_sentence_asks_risk_and_name_but_not_sports(self):
        out = D.read("NHL underdog moneylines, at most four bets a day", LEVELS)
        ids = qids(out)
        self.assertNotIn("sports", ids)
        self.assertIn("risk", ids)
        self.assertIn("finish", ids)
        self.assertEqual(out["named_sports"], ["NHL"])
        self.assertEqual(out["draft"]["rules"][0]["sports"], ["NHL"])

    def test_hockey_by_its_everyday_name_is_read_as_nhl_not_as_mlb_and_nfl(self):
        out = D.read("Hockey moneyline underdogs, four bets a day at most", LEVELS)
        self.assertEqual(out["draft"]["rules"][0]["sports"], ["NHL"])
        self.assertFalse(any("MLB" in a for a in out["assumed"]), out["assumed"])
        self.assertFalse(any("hockey" in n["text"] for n in out["not_understood"]))

    def test_no_sport_named_asks_the_sports_first(self):
        out = D.read("Underdog moneylines, plus money only", LEVELS)
        self.assertEqual(qids(out)[0], "sports")

    def test_no_price_band_asks_risk_with_the_three_levels_and_a_missing_cap_asks_aggression(self):
        out = D.read("NBA underdogs on the moneyline", LEVELS)
        by_id = {x["id"]: x for x in out["questions"]}
        self.assertEqual([c["id"] for c in by_id["risk"]["choices"]], [lv["id"] for lv in LEVELS])
        self.assertEqual(len(by_id["aggression"]["choices"]), 3)

    def test_a_bets_a_day_and_a_price_band_already_given_ask_neither_risk_nor_aggression(self):
        out = D.read("NBA underdog moneylines at +120 to +250, four bets a day at most, 1 unit a bet", LEVELS)
        ids = qids(out)
        self.assertNotIn("risk", ids)
        self.assertNotIn("aggression", ids)

    def test_props_named_without_a_stat_ask_the_mlb_stats_and_nothing_else_is_asked_for_them(self):
        out = D.questions({"rules": [{"sports": ["MLB"], "markets": ["moneyline"], "price_min": 100}],
                           "max_bets_per_day": 2, "stake_units": 1.0}, ["MLB"], text="MLB player props at plus money", levels=LEVELS)
        stats = [x for x in out if x["id"] == "stats"]
        self.assertEqual(len(stats), 1)
        self.assertEqual({c["id"] for c in stats[0]["choices"]}, {sid for sid, _ in D.PROP_STATS})

    def test_name_and_look_are_always_asked_last(self):
        for text in ("NHL underdog moneylines", "Underdogs", "MLB batter hits over, plus money"):
            with self.subTest(text=text):
                self.assertEqual(qids(D.read(text, LEVELS))[-1], "finish")


class DescribeFirstMakesAValidSpec(unittest.TestCase):

    def test_the_hockey_sentence_with_its_risk_answer_composes_to_a_valid_hound(self):
        out = D.read("NHL underdog moneylines, at most four bets a day", LEVELS)
        draft = copy.deepcopy(out["draft"])
        balanced = next(lv for lv in LEVELS if lv["id"] == "balanced")
        comfort = next(c for c in LIB["price_comforts"] if c["id"] == balanced["price_comfort"])
        for rule in draft["rules"]:                       # what the page does with the risk answer: fill only the silent fields
            if rule.get("price_min") is None and rule.get("price_max") is None:
                rule["price_min"], rule["price_max"] = comfort["price_min"], comfort["price_max"]
        draft.setdefault("stake_units", balanced["stake"])
        composed = C.compose({"sports": ["NHL"]}, english_draft=draft)
        spec = composed["spec"]
        self.assertEqual(spec["version"], user_spec.SPEC_VERSION_V2)
        self.assertTrue(all(rule["price_min"] > -200 for rule in spec["rules"]))
        self.assertEqual(spec["max_bets_per_day"], 4)               # the person's own words win over the risk level
        self.assertTrue(all(set(rule["sports"]) == {"NHL"} for rule in spec["rules"]))

    def test_a_described_draft_never_reaches_minus_200(self):
        out = D.read("NHL favourites at -250 on the moneyline", LEVELS)
        for rule in out["draft"].get("rules") or []:
            self.assertTrue(rule.get("price_min") is None or rule["price_min"] > -200, rule)


class ExpertPresets(unittest.TestCase):

    def test_the_three_presets_are_there_and_the_library_check_is_clean(self):
        self.assertEqual(set(PRESET), {"hockey_pro", "basketball_pro", "football_pro"})
        self.assertEqual(L.validate_library(), [])

    def test_every_preset_validates_through_the_real_validator_and_names_only_its_own_sports(self):
        for pid, pr in PRESET.items():
            with self.subTest(preset=pid):
                spec = user_spec.validate_spec(L.draft_spec(pr["fragment"]))
                self.assertTrue(spec["rules"])
                for rule in spec["rules"]:
                    self.assertTrue(set(rule["sports"]) <= set(pr["sports"]))
                    self.assertGreater(rule["price_min"], -200)

    def test_hockey_pro_is_the_brief_nhl_four_books_four_bets_two_units_and_the_market_moving_toward_the_pick(self):
        pr = PRESET["hockey_pro"]
        self.assertEqual(pr["sports"], ["NHL"])
        self.assertEqual((pr["fragment"]["max_bets_per_day"], pr["fragment"]["stake_units"]), (4, 2.0))
        moneyline = next(r for r in pr["fragment"]["rules"] if r["markets"] == ["moneyline"])
        self.assertEqual((moneyline["price_min"], moneyline["price_max"], moneyline["min_books"]), (110, 220, 4))
        self.assertIn({"id": "steam", "direction": "toward"}, moneyline["when"]["items"])
        self.assertIn({"id": "role", "value": "underdog"}, moneyline["when"]["items"])

    def test_the_presets_are_served_with_their_generated_english_and_say_hound_not_dog(self):
        served = L.expert_presets()
        self.assertEqual([p["id"] for p in served], ["hockey_pro", "basketball_pro", "football_pro"])
        for p in served:
            self.assertTrue(p["sentences"])
            self.assertIsNone(re.search(r"\bdogs?\b", p["name"] + " " + p["pitch"], re.I))
            self.assertIn(p["english"], " ".join(p["sentences"]))

    def test_a_preset_that_breaks_a_line_is_refused_by_the_library_check(self):
        broken = copy.deepcopy(LIB)
        broken["expert_presets"][0]["fragment"]["rules"][0]["price_min"] = -250
        self.assertTrue(any("hockey_pro" in p for p in L.validate_library(broken)))
        dogged = copy.deepcopy(LIB)
        dogged["expert_presets"][1]["pitch"] = "Plus money dogs at four books."
        self.assertTrue(any("says dog" in p for p in L.validate_library(dogged)))


def _page(**kw):
    # imported here so the page harness is only needed by the node tests below
    from tests.test_hounds_quiz_web import quiz
    return quiz(**kw)


class TheDoorsWorkInTheBrowserHarness(unittest.TestCase):
    """The entry doors, the describe step and the preset row, run for real under node (skipped when node is not installed)."""

    @unittest.skipUnless(HAS_NODE, "node is not installed")
    def test_describe_it_first_opens_a_sentence_box_on_the_describe_step(self):
        from tests.test_hounds_quiz_web import click, hook, q
        out = _page(actions=[click(hook("quiz-describe"), "describe", wait=120)],
                    queries=[q("box", hook("describe-input"), "count"), q("title", hook("quiz-question")),
                             q("step", "[data-hook='quiz-step-body']", "attr", attr="data-step")])
        self.assertEqual(out["final"]["box"], 1)
        self.assertEqual(out["final"]["title"], "Describe it first.")
        self.assertEqual(out["final"]["step"], "describe")

    @unittest.skipUnless(HAS_NODE, "node is not installed")
    def test_the_style_step_offers_the_three_expert_presets_and_one_skips_risk_to_the_name_and_look(self):
        from tests.test_hounds_quiz_web import TAKE, card, click, hook, NEXT, q
        out = _page(actions=[TAKE, click(card("sports", "NHL"), "nhl"),
                             dict(NEXT, label="next", capture=[q("presets", hook("quiz-preset"), "count")]),
                             click(hook("quiz-preset") + "[data-id='hockey_pro']", "hockey", wait=120)],
                    queries=[q("step", "[data-hook='quiz-step-body']", "attr", attr="data-step"),
                             q("next", hook("quiz-next"))])
        self.assertEqual(out["captures"]["next"]["presets"], 3)
        self.assertEqual(out["final"]["step"], "finish")
        self.assertEqual(out["final"]["next"], "Meet my hound")


    @unittest.skipUnless(HAS_NODE, "node is not installed")
    def test_describe_first_asks_only_the_open_questions_and_reaches_the_reveal_with_the_draft(self):
        import json
        from tests.test_hounds_quiz_web import NEXT, base_routes, card, click, composed, hook, q
        text ="NHL underdog moneylines, at most four bets a day"
        read = json.loads(json.dumps(D.read(text, LEVELS)))
        fixture = composed({"sports": ["NHL"]}, english_draft=read["draft"])
        routes = base_routes(**{"POST /hounds/quiz/describe": [200, read], "POST /hounds/quiz/compose": [200, fixture]})
        out = _page(routes=routes, actions=[
            click(hook("quiz-describe"), "describe", wait=120),
            dict(do="set", sel=hook("describe-input"), value=text, label="type"),
            click(hook("describe-go"), "read", wait=150),
            click(card("risk", "balanced"), "risk", wait=60),
            dict(NEXT, label="n2", capture=[]),
            click(card("aggression", "steady"), "aggr", wait=60),
            dict(NEXT, label="n3", capture=[]),
            dict(NEXT, label="n4", capture=[]),
        ], queries=[q("title", hook("quiz-question"))])
        posts = [p for p in out["posts"] if p["url"].endswith("/hounds/quiz/compose")]
        self.assertTrue(posts, "the reveal composes the draft")
        body = posts[-1]["body"]
        self.assertIn("english_draft", body)
        self.assertNotIn("personality", body["answers"])
        self.assertNotIn("markets", body["answers"])
        self.assertEqual(body["english_draft"]["max_bets_per_day"], 4)      # the words win over the steady cap
        self.assertTrue(all(r["sports"] == ["NHL"] for r in body["english_draft"]["rules"]))
        self.assertTrue(all(r["price_min"] > -200 for r in body["english_draft"]["rules"] if r.get("price_min") is not None))


class EntryHasTwoDoors(unittest.TestCase):

    def test_the_quiz_page_offers_take_the_quiz_and_describe_it_first(self):
        self.assertRegex(HTML, r'data-hook="quiz-entry"')
        self.assertRegex(HTML, r'<button type="button" class="qz-entry__door" data-hook="quiz-take">')
        self.assertRegex(HTML, r'<button type="button" class="qz-entry__door" data-hook="quiz-describe">')
        self.assertIn("Take the quiz", HTML)
        self.assertIn("Describe it first", HTML)

    def test_the_entry_copy_says_no_dog_and_no_claim(self):
        entry = HTML[HTML.index('data-hook="quiz-entry"'):HTML.index('data-hook="quiz-shell"')]
        self.assertIsNone(re.search(r"\bdogs?\b", entry, re.I))
        self.assertIsNone(re.search(r"\bedge\b|guarantee|\bprofit", entry, re.I))


if __name__ == "__main__":
    unittest.main()
