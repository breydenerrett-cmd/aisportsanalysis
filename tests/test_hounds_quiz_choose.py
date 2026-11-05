"""The quiz's "Help me choose" defaults (src/hounds/quiz/choose.py). No FastAPI needed."""

from __future__ import annotations

import re
import unittest

from src.hounds import user_spec
from src.hounds.quiz import choose, compose, library


class TheDefaults(unittest.TestCase):
    def test_sports_is_the_sport_the_house_pack_plays(self):
        out = choose.choose("sports")
        self.assertEqual(out["value"], [choose.house_sport()])
        self.assertEqual(choose.house_sport(), "MLB")                        # eight of the nine house hounds play baseball
        self.assertIn(out["value"][0], user_spec.SPORTS)

    def test_personality_is_a_style_that_composes_on_the_chosen_sports_with_the_fewest_heads_ups(self):
        for sport in ("NHL", "MLB", "NBA", "SOCCER"):
            out = choose.choose("personality", {"sports": [sport]})
            self.assertTrue(out["value"], sport)
            made = compose.compose({"sports": [sport], "personality": out["value"], "markets": ["moneyline"]}, taken_names=())
            self.assertFalse([w for w in made["warnings"] if w["level"] != "note" or w["code"] == "base_generic"],
                             (sport, out["value"], made["warnings"]))

    def test_personality_is_deterministic_and_never_the_gematria_style(self):
        a = choose.choose("personality", {"sports": ["NHL"]})
        b = choose.choose("personality", {"sports": ["NHL"]})
        self.assertEqual(a, b)
        lib = library.load()
        gem = [p["id"] for p in lib["personalities"] if p.get("style") == "gematria"]
        self.assertNotIn(a["value"], gem)

    def test_a_personality_with_no_sports_yet_fits_the_house_sport(self):
        self.assertEqual(choose.choose("personality", {})["value"], choose.choose("personality", {"sports": [choose.house_sport()]})["value"])

    def test_risk_and_aggression_are_the_middle_level(self):
        for step in ("risk", "aggression"):
            out = choose.choose(step)
            self.assertEqual(out["value"], "balanced")
            self.assertTrue(out["label"])

    def test_stats_and_finish(self):
        self.assertEqual(choose.choose("stats")["value"], ["batter_hits"])
        self.assertIsNone(choose.choose("finish")["value"])

    def test_an_unknown_step_is_refused_and_hostile_answers_are_ignored(self):
        with self.assertRaises(ValueError):
            choose.choose("markets")
        self.assertEqual(choose.choose("personality", "nonsense")["step"], "personality")
        self.assertEqual(choose.choose("personality", {"sports": [5, None]})["step"], "personality")

    def test_every_label_follows_the_copy_rules(self):
        text = " ".join(str(choose.choose(s, {"sports": ["NHL"]}).get(k, "")) for s in choose.STEPS for k in ("label", "why", "skip_label")).lower()
        for pattern in (r"\bbeta\b", r"\bnew\b", r"\bedge\b", r"\block\b", r"\bclv\b", r"nothing cleared the bar", r"\bprofit"):
            self.assertIsNone(re.search(pattern, text), pattern)

    def test_the_pages_skip_words_are_the_servers(self):
        from tests.hounds_web_runner import WEB
        js = (WEB / "js" / "hound-quiz.js").read_text(encoding="utf-8")
        for step in ("sports", "personality", "stats", "finish"):
            self.assertIn(choose.choose(step)["skip_label"], js, step)


if __name__ == "__main__":
    unittest.main()
