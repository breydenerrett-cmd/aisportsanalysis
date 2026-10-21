"""GET /hounds/quiz/library and POST /hounds/quiz/compose (api/hounds_quiz.py): public, paper-only, rate-limited, mounted
before api.hounds, and nothing a request can say gets a spec past the real validator. Skipped without FastAPI (the Linux CI
run has none; the same logic is covered FastAPI-free by tests/test_hounds_quiz_compose.py).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
    HAS_FASTAPI = True
except ImportError:  # CI's no-FastAPI run
    HAS_FASTAPI = False

from src.hounds import user_spec

REPO = Path(__file__).resolve().parent.parent


@unittest.skipUnless(HAS_FASTAPI, "FastAPI is not installed")
class TheQuizDoors(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from api import hounds_quiz
        from api.app import app
        cls.module = hounds_quiz
        cls.client = TestClient(app)

    def test_the_library_is_public_paper_only_and_cacheable(self):
        r = self.client.get("/hounds/quiz/library")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["paper_only"])
        self.assertEqual(data["not_advice"], user_spec.NOT_ADVICE)
        self.assertIn("max-age", r.headers["cache-control"])
        self.assertGreaterEqual(len(data["archetypes"]), 30)
        first = data["archetypes"][0]
        for key in ("id", "name", "pitch", "icon", "spec_fragment", "english", "sentences", "works_in", "stance"):
            self.assertIn(key, first)
        self.assertEqual(data["limits"]["archetype_picks"], 2)
        self.assertEqual(data["limits"]["max_rules"], 4)
        self.assertEqual({p["id"] for p in data["personalities"]},
                         {"underdog_hunter", "chalk_eater", "chaos_agent", "stats_nerd", "steam_chaser", "mystic", "gematria"})
        self.assertNotIn("recipes", data["personalities"][0])             # recipes stay server side

    def test_compose_returns_a_validated_spec_with_english_and_warnings(self):
        r = self.client.post("/hounds/quiz/compose", json={"answers": {
            "personality": "chalk_eater", "price_comfort": "plus", "markets": ["moneyline"], "archetypes": ["steam_chaser"]}})
        self.assertEqual(r.status_code, 200)
        out = r.json()
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertTrue(out["paper_only"])
        user_spec.validate_spec(out["spec"])
        self.assertIn("Paper only", out["english"])
        self.assertIn("price_conflict", [w["code"] for w in out["warnings"]])
        self.assertEqual([c["source"] for c in out["rule_cards"]], ["personality", "archetype"])

    def test_compose_with_nothing_is_the_starter_pup_not_an_error(self):
        for body in ({}, {"answers": {}}, {"answers": {"personality": "wizard"}}):
            r = self.client.post("/hounds/quiz/compose", json=body)
            self.assertEqual(r.status_code, 200, body)
            self.assertTrue(r.json()["starter"])

    def test_the_english_text_and_draft_paths_both_merge(self):
        r = self.client.post("/hounds/quiz/compose", json={"answers": {"personality": "mystic"},
                                                           "english_text": "also bet home underdogs. Max 4 bets a day"})
        out = r.json()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(out["rule_cards"][-1]["source"], "english")
        self.assertEqual(out["spec"]["max_bets_per_day"], 4)
        draft = {"rules": [{"markets": ["moneyline"], "sports": ["MLB"], "side": "home", "price_min": 110,
                            "price_max": 200}]}
        r2 = self.client.post("/hounds/quiz/compose", json={"answers": {}, "english_draft": draft})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["spec"]["rules"][0]["side"], "home")

    def test_a_hostile_body_is_refused_or_repaired_never_passed_through(self):
        too_long = self.client.post("/hounds/quiz/compose", json={"answers": {}, "english_text": "x" * 700})
        self.assertEqual(too_long.status_code, 422)
        self.assertEqual(too_long.json()["detail"]["error"], "text_too_long")
        bad_type = self.client.post("/hounds/quiz/compose", json={"answers": "nope"})
        self.assertEqual(bad_type.status_code, 422)                       # pydantic: answers must be an object
        evil = self.client.post("/hounds/quiz/compose", json={"answers": {}, "english_draft": {
            "rules": [{"markets": ["moneyline"], "sports": ["MLB"], "side": "either", "price_min": -400,
                       "price_max": 100}]}})
        self.assertEqual(evil.status_code, 200)
        for rule in evil.json()["spec"]["rules"]:
            self.assertGreaterEqual(rule["price_min"], user_spec.SHORTEST_ALLOWED_PRICE)
        self.assertIn("rule_refused", [w["code"] for w in evil.json()["warnings"]])

    def test_a_taken_name_is_never_suggested(self):
        first = self.client.post("/hounds/quiz/compose", json={"answers": {"personality": "mystic"}}).json()
        original = self.module._taken_names
        try:
            self.module._taken_names = lambda: [first["name_suggestions"][0]]
            again = self.client.post("/hounds/quiz/compose", json={"answers": {"personality": "mystic"}}).json()
        finally:
            self.module._taken_names = original
        self.assertNotIn(first["name_suggestions"][0], again["name_suggestions"])

    def test_the_quiz_router_is_mounted_before_the_dog_id_routes(self):
        source = (REPO / "api" / "app.py").read_text(encoding="utf-8")
        quiz_at = source.index("app.include_router(hounds_quiz_router)")
        self.assertLess(quiz_at, source.index("app.include_router(hounds_router)"))
        self.assertLess(source.index("app.include_router(hounds_create_router)"), quiz_at + 1)
        # and the dog routes still answer, with the quiz literal paths beside them
        self.assertEqual(self.client.get("/hounds/menu").status_code, 200)
        self.assertEqual(self.client.get("/hounds/quiz/library").status_code, 200)

    def test_the_library_lists_every_sport_popular_first_and_any_sport(self):
        data = self.client.get("/hounds/quiz/library").json()
        values = [s["value"] for s in data["sports"]]
        self.assertEqual(values[:8], ["NBA", "NFL", "NHL", "NCAAF", "SOCCER", "TENNIS", "MLB", "MMA"])
        self.assertEqual(sorted(values), sorted(user_spec.SPORTS))
        self.assertEqual(data["sports_any"]["value"], user_spec.ANY)
        self.assertEqual(data["sports"][0]["label"], "NBA")
        self.assertEqual(data["sports"][3]["label"], "College football")
        for card in data["archetypes"]:
            self.assertTrue(card["short"])

    def test_moves_returns_four_cards_a_page_and_cycles(self):
        body = {"answers": {"sports": ["NBA"], "personality": "underdog_hunter"}}
        first = self.client.post("/hounds/quiz/moves", json=body)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.headers["cache-control"], "no-store")
        out = first.json()
        self.assertTrue(out["paper_only"])
        self.assertEqual(len(out["moves"]), 4)
        for card in out["moves"]:
            for key in ("id", "name", "short", "sport_badge", "english", "sentences", "stance"):
                self.assertIn(key, card)
            self.assertEqual(card["sports"], ["NBA"])
        nxt = self.client.post("/hounds/quiz/moves", json={**body, "page": out["next_page"]}).json()
        self.assertEqual(nxt["page"], 1)
        self.assertFalse({c["id"] for c in out["moves"]} & {c["id"] for c in nxt["moves"]})
        wrapped = self.client.post("/hounds/quiz/moves", json={**body, "page": out["pages"]}).json()
        self.assertEqual(wrapped["moves"], out["moves"])
        huge = self.client.post("/hounds/quiz/moves", json={**body, "page": 10 ** 9})
        self.assertEqual(huge.status_code, 200)
        self.assertEqual(self.client.post("/hounds/quiz/moves", json={**body, "page": -5}).json()["page"], 0)

    def test_moves_survives_nothing_and_hostile_answers(self):
        for body in ({}, {"answers": {}}, {"answers": {"sports": ["CURLING"]}}, {"answers": {"sports": 7}},
                     {"answers": {"sports": ["ANY"], "personality": "wizard"}}):
            r = self.client.post("/hounds/quiz/moves", json=body)
            self.assertEqual(r.status_code, 200, body)
            self.assertEqual(len(r.json()["moves"]), 4)
        self.assertEqual(self.client.post("/hounds/quiz/moves", json={"answers": "nope"}).status_code, 422)

    def test_pick_for_me_is_the_top_move_and_it_composes(self):
        body = {"answers": {"sports": ["TENNIS"], "price_comfort": "plus"}}
        pick = self.client.post("/hounds/quiz/pick", json=body).json()
        top = self.client.post("/hounds/quiz/moves", json=body).json()
        self.assertEqual(pick["id"], top["recommended"])
        self.assertEqual(pick["card"]["id"], pick["id"])
        out = self.client.post("/hounds/quiz/compose", json={"answers": {**body["answers"], "archetypes": [pick["id"]]}})
        self.assertIn(pick["id"], out.json()["archetypes"])
        self.assertTrue(pick["paper_only"])

    def test_the_whole_response_is_json_safe_and_free_of_a_minus_200_price(self):
        out = self.client.post("/hounds/quiz/compose", json={"answers": {
            "personality": "chalk_eater", "markets": ["mix"], "price_comfort": "short"}}).json()
        text = json.dumps(out)
        self.assertNotRegex(text, r'"price_(min|max)": -(2\d\d|[3-9]\d\d)')


if __name__ == "__main__":
    unittest.main()
