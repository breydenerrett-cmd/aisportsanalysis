"""OWNER RULING 2026-10-21 (four-step quiz): the quiz's style step is step 2 of 4 and its risk step is one three-way choice, so the flows below were
rewritten for it (sports, style, risk, name and look); nothing about Gematria was loosened.

The member Gematria style on the pages: the quiz's "Pick its style." step and the builder's base-style picker, run for real
under node against the fake DOM of tests/hounds_web_harness.mjs (the REAL quiz library, the REAL composer, the REAL builder menu and
the REAL English parser as fixtures). The server half is tests/test_gematria_member_style.py. Skipped when node is not installed.
"""
from __future__ import annotations

import json
import re
import unittest

from src.hounds import user_spec
from src.hounds.english import parser
from tests import hounds_web_fixtures as F
from tests.hounds_web_runner import HAS_NODE, WEB, run_page
from tests.test_hounds_builder_web import MENU, SIGNED as BUILD_SIGNED, base_routes as build_routes, build, preview_posts, q as bq
from tests.test_hounds_quiz_web import LIB, NEXT, SKIP, START, base_routes as quiz_routes, card, click, composed, derive, hook, posts_to, q, quiz

QUIZ_JS = (WEB / "js" / "hound-quiz.js").read_text(encoding="utf-8")
QUIZ_CSS = (WEB / "css" / "quiz.css").read_text(encoding="utf-8")
GEM_ANSWERS = derive(["NBA", "NHL"], "gematria", "bold")           # Gematria has one fixed rule, so no price band is sent for it
TO_Q3 = [click(card("sports", "MLB")), NEXT]                        # one sport picked, Next: the style step is open


class QuizStaticFacts(unittest.TestCase):
    def test_a_phone_sees_at_most_one_page_of_four_personalities(self):
        self.assertIn("export const PERSONALITY_PAGE = 4;", QUIZ_JS)
        # the css hides every card off the grid's page below 720px, and hides the button on a wide screen
        self.assertRegex(QUIZ_CSS, r"@media \(max-width: 719px\) \{\s*\.qz-grid--dogs\[data-page=\"0\"\] > \[data-page\]:not\(\[data-page=\"0\"\]\)")
        self.assertRegex(QUIZ_CSS, r"@media \(min-width: 720px\) \{ \.qz-actions--personality \{ display: none; \} \}")

    def test_the_library_gives_the_card_its_line_and_it_claims_nothing(self):
        gem = next(p for p in LIB["personalities"] if p["id"] == "gematria")
        self.assertEqual(gem["pitch"], "Reads the numbers in names, dates and streaks. Bets when they line up.")
        self.assertEqual(gem["style"], "gematria")
        self.assertIsNone(re.search(r"\bedge\b|\bprofit|\bproven\b|guarantee", json.dumps(gem).lower()))


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheQuizCard(unittest.TestCase):
    def test_gematria_is_the_last_card_beside_mystic_with_its_own_bloodhound(self):
        out = quiz(actions=TO_Q3, queries=[
            q("ids", "[data-hook='quiz-card'][data-group='personality']", "attrs", attr="data-id"),
            q("pages", "[data-hook='quiz-card'][data-group='personality']", "attrs", attr="data-page"),
            q("breeds", "[data-hook='quiz-card'][data-group='personality'] svg.dk-badge", "attrs", attr="data-breed"),
            q("styles", "[data-hook='quiz-card'][data-group='personality'] svg.dk-badge", "attrs", attr="data-style"),
            q("gem_title", f"{card('personality', 'gematria')} .qz-pin__title"), q("gem_pitch", f"{card('personality', 'gematria')} .qz-pin__pitch")])
        f = out["final"]
        self.assertEqual(f["ids"], ["underdog_hunter", "chalk_eater", "chaos_agent", "stats_nerd", "steam_chaser", "mystic", "gematria"])
        self.assertEqual(f["pages"], ["0", "0", "0", "0", "1", "1", "1"])
        self.assertEqual(f["breeds"][-1], "bloodhound")
        self.assertEqual(f["breeds"].count("bloodhound"), 1)                       # no other personality draws that dog
        self.assertEqual(f["styles"][-1], "elite")
        self.assertEqual((f["gem_title"], f["gem_pitch"]), ("Gematria", "Reads the numbers in names, dates and streaks. Bets when they line up."))

    def test_show_me_others_turns_to_the_second_page_and_back(self):
        out = quiz(actions=TO_Q3 + [click(hook("quiz-personality-more"), "more")], queries=[
            q("page", hook("quiz-personality-grid"), "attr", attr="data-page"), q("count", hook("quiz-personality-count")),
            q("button", hook("quiz-personality-more"))])
        self.assertEqual((out["final"]["page"], out["final"]["count"], out["final"]["button"]), ("1", "Page 2 of 2.", "Show me others"))
        again = quiz(actions=TO_Q3 + [click(hook("quiz-personality-more"), "more"), click(hook("quiz-personality-more"), "more again")],
                     queries=[q("page", hook("quiz-personality-grid"), "attr", attr="data-page")])
        self.assertEqual(again["final"]["page"], "0")

    def test_the_page_with_the_picked_card_opens_first_and_the_pick_survives_the_page_turn(self):
        out = quiz(actions=TO_Q3 + [click(hook("quiz-personality-more"), "more"), click(card("personality", "gematria")),
                                    click(hook("quiz-personality-more"), "back to page one")],
                   queries=[q("page", hook("quiz-personality-grid"), "attr", attr="data-page"),
                            q("pressed", card("personality", "gematria"), "attr", attr="aria-pressed")])
        self.assertEqual(out["final"]["pressed"], "true")
        resumed = quiz(actions=TO_Q3 + [click(hook("quiz-personality-more"), "more"), click(card("personality", "gematria")), NEXT,
                                        click(hook("quiz-back"), "back")],
                       queries=[q("page", hook("quiz-personality-grid"), "attr", attr="data-page")])
        self.assertEqual(resumed["final"]["page"], "1")

    def test_choosing_it_tells_the_steps_it_ignores_why(self):
        out = quiz(actions=TO_Q3 + [click(card("personality", "gematria")), NEXT], queries=[
            q("note", hook("quiz-risk-note")), q("step", hook("quiz-step"))])
        self.assertIn("fixed rule", out["final"]["note"])
        self.assertIn("does not apply", out["final"]["note"])
        other = quiz(actions=TO_Q3 + [click(card("personality", "stats_nerd")), NEXT], queries=[q("note", hook("quiz-risk-note"))])
        self.assertEqual(other["final"]["note"], "")

    def test_the_answers_reach_compose_and_the_reveal_shows_the_gematria_rule(self):
        fixture = composed(GEM_ANSWERS)
        actions = [click(card("sports", "NBA")), click(card("sports", "NHL")), NEXT,
                   click(card("personality", "gematria")), NEXT, click(card("risk", "bold")), NEXT, NEXT]
        out = quiz(routes=quiz_routes(GEM_ANSWERS), actions=actions, queries=[
            q("labels", ".qz-rule__label", "texts"), q("breed", "[data-hook='reveal-dog'] svg.dk-badge", "attr", attr="data-breed"),
            q("number", "[data-hook='reveal-dog'] svg.dk-badge", "attr", attr="data-number"),
            q("rules", "[data-hook='reveal-rule']", "texts")])
        body = posts_to(out, "/hounds/quiz/compose")[0]["body"]
        self.assertEqual(body["answers"]["personality"], "gematria")
        self.assertEqual(body["answers"], GEM_ANSWERS)
        self.assertNotIn("price_comfort", body["answers"])
        self.assertEqual(out["final"]["labels"], ["Gematria"])
        self.assertEqual(out["final"]["breed"], "bloodhound")
        self.assertIn("house Gematria Hound", out["final"]["rules"][0])
        self.assertEqual(fixture["spec"]["style"], "gematria")

    def test_keep_posts_the_spec_the_composer_made_and_the_server_accepts_it(self):
        fixture = composed(GEM_ANSWERS)
        saved = {"id": "u-gem1", "name": fixture["spec"]["name"], "status": "running", "version_no": 1}
        routes = quiz_routes(GEM_ANSWERS, **{"POST /hounds": [200, {"hound": saved}], "PUT /hounds/u-gem1/look": [200, {"look": fixture["look"]}],
                                             "/hounds/mine": [200, {"hounds": [], "limit_running": 5}]})
        actions = [click(card("sports", "NBA")), click(card("sports", "NHL")), NEXT,
                   click(card("personality", "gematria")), NEXT, click(card("risk", "bold")), NEXT, NEXT,
                   click(hook("reveal-save"), "keep")]
        out = quiz(routes=routes, actions=actions, **dict(stored={"aisportsanalysis.invite_token": "tok"}))
        posted = posts_to(out, "/hounds")
        mine = [p for p in posted if p["url"].endswith("/hounds") and "spec" in (p["body"] or {})]
        self.assertTrue(mine, [p["url"] for p in out["posts"]])
        spec = mine[0]["body"]["spec"]
        self.assertEqual(spec["style"], "gematria")
        self.assertEqual(user_spec.validate_spec(spec)["style"], "gematria")        # exactly what the server will accept


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheBuilderPicker(unittest.TestCase):
    def test_the_picker_lists_the_menus_styles_and_starts_on_your_own_rules(self):
        out = build(queries=[bq("labels", "[data-hook='style-choice']", "texts"), bq("pressed", "[data-hook='style-choice']", "attrs", attr="aria-pressed"),
                             bq("panel_hidden", "[data-hook='style-gematria']", "hidden")])
        f = out["final"]
        self.assertEqual(f["labels"], [s["label"] for s in MENU["styles"]])
        self.assertEqual(f["pressed"], ["true", "false"])
        self.assertTrue(f["panel_hidden"])

    def test_choosing_gematria_shows_its_paragraph_the_house_link_and_hides_the_rule_cards(self):
        out = build(actions=[click_style("gematria")], queries=[
            bq("panel_hidden", "[data-hook='style-gematria']", "hidden"), bq("explain", "[data-hook='style-explain']"),
            bq("link", "[data-hook='style-house-link']", "attr", attr="href"), bq("fixed", "[data-hook='style-fixed']"),
            bq("advanced_hidden", "[data-hook='rules-advanced']", "hidden"), bq("cards", "[data-hook='rule-card']", "count"),
            bq("bets", "[data-hook='style-globals'] [data-hook='g-bets']", "count"), bq("lock", "[data-hook='style-globals'] [data-hook='g-lock']", "count"),
            bq("rank", "[data-hook='style-globals'] [data-hook='g-rank']", "count"),
            bq("sports", "[data-hook='style-sports'] [data-hook='rule-sports'] button", "count"),
            bq("pressed", "[data-hook='style-choice']", "attrs", attr="aria-pressed")])
        f = out["final"]
        gem = next(s for s in MENU["styles"] if s["value"] == "gematria")
        self.assertFalse(f["panel_hidden"])
        self.assertEqual(f["explain"], gem["summary"])
        self.assertEqual(f["link"], "hound.html?id=gematria")
        self.assertEqual(f["fixed"], gem["fixed"]["text"])
        self.assertTrue(f["advanced_hidden"])
        self.assertEqual((f["cards"], f["bets"], f["lock"], f["rank"]), (0, 1, 0, 0))
        self.assertGreater(f["sports"], 5)
        self.assertEqual(f["pressed"], ["false", "true"])

    def test_the_preview_and_the_save_carry_the_style_and_the_server_accepts_it(self):
        out = build(actions=[click_style("gematria")], queries=[])
        spec = preview_posts(out)[-1]
        self.assertEqual(spec["style"], "gematria")
        self.assertEqual((spec["lock_minutes"], spec["rank_by"]), (60, "earliest_lock"))
        self.assertEqual(len(spec["rules"]), 1)
        self.assertEqual(spec["sports"], spec["rules"][0]["sports"])
        spec = {**spec, "name": "Numbers Pup"}
        self.assertEqual(user_spec.validate_spec(spec)["style"], "gematria")

    def test_switching_back_restores_the_rules_and_drops_the_style(self):
        out = build(actions=[dict(do="click", sel="[data-hook='blank-rule']", label="blank", wait=60), click_style("gematria"), click_style("rules")],
                    queries=[bq("panel_hidden", "[data-hook='style-gematria']", "hidden"), bq("cards", "[data-hook='rule-card']", "count"),
                             bq("advanced_hidden", "[data-hook='rules-advanced']", "hidden")])
        self.assertTrue(out["final"]["panel_hidden"])
        self.assertEqual((out["final"]["cards"], out["final"]["advanced_hidden"]), (1, False))
        self.assertNotIn("style", preview_posts(out)[-1])

    def test_the_english_box_reading_gematria_opens_the_style(self):
        text = "Use gematria on NBA and NHL, max 3 bets a day"
        parsed = parser.parse(text)
        answer = {"status": "parsed", "text": text, **parsed, "unread": [], "paper_only": True, "not_advice": user_spec.NOT_ADVICE}
        out = build(build_routes(**{"POST /hounds/english": [200, json.loads(json.dumps(answer))]}),
                    actions=[dict(do="set", sel="[data-hook='english-input']", value=text, label="type"),
                             dict(do="click", sel="[data-hook='english-go']", label="read", wait=500)],
                    queries=[bq("panel_hidden", "[data-hook='style-gematria']", "hidden"),
                             bq("pressed", "[data-hook='style-choice']", "attrs", attr="aria-pressed"),
                             bq("bets", "[data-hook='style-globals'] [data-hook='g-bets']", "value")])
        self.assertFalse(out["final"]["panel_hidden"])
        self.assertEqual(out["final"]["pressed"], ["false", "true"])
        self.assertEqual(out["final"]["bets"], "3")
        self.assertEqual(preview_posts(out)[-1]["sports"], ["NBA", "NHL"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheMemberHoundsEvidenceFold(unittest.TestCase):
    """A member's hound in the Gematria style is a numerology hound to the page (user_defs gives it that category), so the same
    Evidence fold shows, and it asks for the member's own id."""
    HID = "u-gem1"

    def routes(self, picks=2):
        from dataclasses import replace
        from src.hounds import contract
        from src.hounds.contract import paginate
        summary = replace(F.gematria_summary(), id=self.HID, name="Numbers Pup", kind="user", source="user_store",
                          tagline="Counts the numbers. Passes when they do not line up.")
        detail = contract.hound_payload(summary, [], paginate([], 1, 25), F.AS_OF)
        payload = dict(F.gematria_payload(picks), hound_id=self.HID)
        return {f"/hounds/{self.HID}": (200, detail), f"/hounds/{self.HID}/gematria": (200, payload)}

    def test_the_fold_shows_both_sides_of_each_pick_for_a_members_hound(self):
        from tests.test_hounds_web_pages import q as pq
        out = run_page("hound", routes=self.routes(), search=f"?id={self.HID}", queries=[
            pq("hidden", "[data-hook='hound-evidence']", "hidden"), pq("picks", "[data-hook='evidence-pick']", "count"),
            pq("sides", ".hd-ev__side", "count"), pq("summary", "[data-hook='evidence-summary']", "texts")])
        f = out["final"]
        self.assertFalse(f["hidden"])
        self.assertEqual((f["picks"], f["sides"]), (2, 4))
        self.assertIn("Rules v1", f["summary"][0])
        self.assertTrue(any(u.split("?")[0].endswith(f"/hounds/{self.HID}/gematria") for u in out["gets"]), out["gets"])

    def test_an_ordinary_members_hound_never_sees_it(self):
        from dataclasses import replace
        from src.hounds import contract
        from src.hounds.contract import paginate
        from tests.test_hounds_web_pages import q as pq
        summary = replace(F.gematria_summary(), id="u-plain", name="Plain Pup", kind="user", category="mixed", source="user_store")
        detail = contract.hound_payload(summary, [], paginate([], 1, 25), F.AS_OF)
        out = run_page("hound", routes={"/hounds/u-plain": (200, detail)}, search="?id=u-plain",
                       queries=[pq("hidden", "[data-hook='hound-evidence']", "hidden")])
        self.assertTrue(out["final"]["hidden"])


def click_style(value):
    return dict(do="click", sel=f"[data-hook='style-choice'][data-style='{value}']", label=f"style {value}", wait=450)


if __name__ == "__main__":
    unittest.main()
