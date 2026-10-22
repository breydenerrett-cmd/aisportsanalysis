"""OWNER RULING 2026-10-21 (kennel front): "fewer steps and simpler ... the hound is the foundation". The quiz is FOUR steps now (sports,
style, risk, name and look) in place of eight; the markets, timing, move cards and quirks fall to defaults derived from the four answers and
stay editable in the builder. The tests that pinned the eight-question flow, its intro screen and its Skip button were rewritten here
deliberately, not loosened: TheFourSteps pins the new flow, and every personality is run through the page and the real composer.

The hound quiz page (web/quiz.html + web/js/hound-quiz.js + hound-quiz-art.js), run for real under node against the fake DOM of
tests/hounds_web_harness.mjs: its own HTML, its own scripts, the REAL library (src/hounds/quiz/library.py) and the REAL composer's
answers (src/hounds/quiz/compose.py) as fixtures. What the page posts is checked against what the composer expects, so the page
and the server cannot drift apart. Skipped when node is not installed; the static checks need no node.
"""
from __future__ import annotations

import json
import re
import unittest

from src.hounds import user_spec
from src.hounds.english import parser
from src.hounds.quiz import compose as C, library as L
from tests.hounds_web_runner import HAS_NODE, WEB, run_js, run_page

HTML = (WEB / "quiz.html").read_text(encoding="utf-8")
JS = (WEB / "js" / "hound-quiz.js").read_text(encoding="utf-8")
CSS = (WEB / "css" / "quiz.css").read_text(encoding="utf-8")
TOKEN_KEY = "aisportsanalysis.invite_token"
DRAFT_KEY = "linehound.quiz.draft.v1"
HANDOFF_KEY = "linehound.quiz.handoff.v1"
LIB = json.loads(json.dumps(L.public_library()))
SIGNED = dict(stored={TOKEN_KEY: "tok"})

CLAIMS = (r"\block\b", r"can'?t lose", r"sure thing", r"free money", r"\bedge\b", r"\bprofit", r"\bev\b", r"guarantee")


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


def hook(name):
    return f"[data-hook='{name}']"


def card(group, ident):
    return f"[data-hook='quiz-card'][data-group='{group}'][data-id='{ident}']"


def click(sel, label=None, **kw):
    return dict(do="click", sel=sel, label=label or sel, **kw)


NEXT = click(hook("quiz-next"), "next")
SKIP = click(hook("quiz-skip"), "skip")
BACK = click(hook("quiz-back"), "back")
START = click(hook("quiz-start"), "start")


def composed(answers, **kw):
    return json.loads(json.dumps(C.compose(answers, **kw)))


def preview_answer(qualifying=2, cap=2, board=3):
    picks = [{"event_id": f"e{i}", "selection": "Boston Red Sox to win", "away_team": "Boston Red Sox", "home_team": "New York Yankees",
              "price": 120, "would_bet": i < cap} for i in range(qualifying)]
    return {"qualifying": qualifying, "would_bet": min(qualifying, cap), "max_bets_per_day": cap, "picks": picks,
            "games_fit": len({p["event_id"] for p in picks}), "board_size": board,
            "games_on_board": board, "read_only": True, "paper_only": True, "not_advice": user_spec.NOT_ADVICE}



def derive(sports, personality, risk="balanced", look=None):
    """What the page must post to compose for these four answers: the answers plus the defaults it derives (config risk_levels)."""
    level = next(r for r in LIB["risk_levels"] if r["id"] == risk)
    p = next(x for x in LIB["personalities"] if x["id"] == personality)
    out = {"sports": list(sports), "personality": personality, "markets": ["moneyline"], "bets_per_day": level["bets_per_day"], "stake": level["stake"]}
    if p["stance"] not in ("chalk", "dog") and p.get("style") != "gematria":      # a chalk or underdog style owns its price band; Gematria has one rule
        out["price_comfort"] = level["price_comfort"]
    if look:
        out["look"] = dict(look)
    return out


def base_routes(answers=None, **over):
    fixture = composed(answers or {})
    r = {"/hounds/quiz/library": [200, LIB], "POST /hounds/quiz/compose": [200, fixture],
         "POST /hounds/builder/preview": [200, preview_answer()]}
    r.update(over)
    return r


def quiz(routes=None, **kw):
    return run_page("quiz", routes=routes or base_routes(), **kw)


def posts_to(out, suffix):
    return [p for p in out["posts"] if p["url"].endswith(suffix)]


QUICK_ANSWERS = derive(["MLB"], "chalk_eater")
QUICK = [click(card("sports", "MLB")), NEXT, click(card("personality", "chalk_eater")), NEXT, NEXT, NEXT]      # risk keeps its default


def skip_all():
    """The shortest way through the four steps (the name is the old tests' word for it: nothing here is skippable any more)."""
    return list(QUICK)


COMBO_ANSWERS = derive(["MLB"], "chalk_eater", "bold", look={"coat": "golden", "accessory": "cap"})
COMBO_ACTIONS = [
    click(card("sports", "MLB")), NEXT,
    click(card("personality", "chalk_eater")), NEXT,
    click(card("risk", "bold")), NEXT,
    click("[data-hook='quiz-coat'][data-id='golden']"), click(card("accessory", "cap")), NEXT,
]


class StaticFacts(unittest.TestCase):
    def visible(self):
        text = re.sub(r"<!--.*?-->", "", HTML, flags=re.S)
        text = re.sub(r"<(script|style|head)\b.*?</\1>", " ", text, flags=re.S)
        return " ".join(re.sub(r"<[^>]+>", " ", text).split())

    def test_the_hard_lines_are_static_text(self):
        text = self.visible()
        self.assertIn("Paper bets only. Your hound never takes a price of -200 or worse. Not advice. 21+.", text)
        self.assertIn("Gamble responsibly.", text)
        self.assertIn('href="tel:1-800-426-2537"', HTML)
        self.assertIn("1-800-GAMBLER", HTML)

    def test_no_claim_and_no_academic_words_in_the_static_page(self):
        text = self.visible().lower()
        for pattern in CLAIMS:
            self.assertIsNone(re.search(pattern, text), pattern)
        for word in ("pre-registered", "hypothesis", "bootstrap", "confidence interval"):
            self.assertNotIn(word, text)

    def test_the_shell_has_progress_stage_bar_and_a_builder_link_and_no_skip_button(self):
        for h in ("quiz-progress", "quiz-stage", "quiz-back", "quiz-next", "quiz-skip-builder", "quiz-reveal", "quiz-restart"):
            self.assertIn(f'data-hook="{h}"', HTML, h)
        self.assertNotIn('data-hook="quiz-skip"', HTML)                                   # one primary action per screen: Next
        self.assertRegex(HTML, r'<a [^>]*href="build-a-hound.html"[^>]*data-hook="quiz-skip-builder"[^>]*>Build from a sentence</a>')
        self.assertIn('aria-valuemax="4"', HTML)
        self.assertIn('role="progressbar"', HTML)
        self.assertIn('<script type="module" src="js/hound-quiz.js"></script>', HTML)
        self.assertIn('data-current="build"', HTML)

    def test_a_visitor_without_scripts_is_pointed_at_the_builder(self):
        match = re.search(r"<noscript>(.*?)</noscript>", HTML, re.S)
        self.assertIsNotNone(match)
        self.assertIn('href="build-a-hound.html"', match.group(1))

    def test_every_animation_is_inside_the_reduced_motion_guard(self):
        guarded = CSS.split("@media (prefers-reduced-motion: no-preference)")[1]
        before = CSS.split("@media (prefers-reduced-motion: no-preference)")[0]
        self.assertNotRegex(before, r"animation\s*:")
        self.assertIn("animation:", guarded)

    def test_the_script_names_no_rule_and_no_sport_list_of_its_own(self):
        # it draws what the library sent; it never lists an archetype, a quirk or a personality
        for archetype in LIB["archetypes"]:
            self.assertNotIn(archetype["name"], JS, archetype["id"])
        for word in ("Underdog Hunter", "Chalk Eater", "Full moon", "Windy days", "Steady", "Balanced", "Bold"):
            self.assertNotIn(word, JS)

    @unittest.skipUnless(HAS_NODE, "node not installed")
    def test_every_icon_the_library_uses_has_a_drawing(self):
        keys = run_js('import { ICON_KEYS } from "./hound-quiz-art.js";\nconsole.log(JSON.stringify(ICON_KEYS));')
        used = set()
        for table in ("archetypes", "personalities", "markets", "price_comforts", "quirks", "timings"):
            used |= {row["icon"] for row in LIB[table]}
        used |= {"baseball", "football", "check"}
        self.assertEqual(used - set(keys), set())
        self.assertEqual(set(L.ICON_KEYS) - set(keys), set())


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheFourSteps(unittest.TestCase):
    """Owner ruling 2026-10-21: four steps, one primary action each, a real "Step n of 4" indicator, no intro, no Skip."""

    def test_the_quiz_opens_straight_on_step_one_with_no_intro_and_no_skip(self):
        out = quiz(queries=[q("q", hook("quiz-question")), q("step", hook("quiz-step")), q("intro", hook("quiz-intro"), "count"),
                            q("skip", hook("quiz-skip"), "count"), q("back_hidden", hook("quiz-back"), "hidden"),
                            q("next", hook("quiz-next")), q("next_disabled", hook("quiz-next"), "disabled"),
                            q("builder", hook("quiz-skip-builder"), "attr", attr="href"), q("restart_hidden", hook("quiz-restart"), "hidden"),
                            q("shell_hidden", hook("quiz-shell"), "hidden")])
        f = out["final"]
        self.assertEqual((f["q"], f["step"]), ("Which sports should it bet?", "Step 1 of 4"))
        self.assertEqual((f["intro"], f["skip"], f["back_hidden"], f["shell_hidden"]), (0, 0, True, False))
        self.assertEqual((f["next"], f["next_disabled"], f["builder"], f["restart_hidden"]), ("Next", True, "build-a-hound.html", True))
        self.assertEqual([g for g in out["gets"] if "quiz" in g], ["/hounds/quiz/library"])

    def test_a_library_that_will_not_load_says_so_and_offers_the_builder(self):
        out = run_page("quiz", routes={}, queries=[q("err", hook("quiz-error")), q("retry", hook("quiz-retry"), "count"),
                                                    q("links", "[data-hook='quiz-error'] a", "attrs", attr="href")])
        self.assertIn("The quiz is not loading", out["final"]["err"])
        self.assertEqual(out["final"]["retry"], 1)
        self.assertEqual(out["final"]["links"], ["build-a-hound.html"])

    def test_exactly_four_steps_in_order_each_drawn_from_the_library(self):
        capture = [q("q", hook("quiz-question")), q("step", "[data-hook='quiz-step-body']", "attr", attr="data-step"),
                   q("label", hook("quiz-step")), q("valuenow", hook("quiz-progress"), "attr", attr="aria-valuenow"),
                   q("valuemax", hook("quiz-progress"), "attr", attr="aria-valuemax"), q("cards", "[data-hook='quiz-card']", "count"),
                   q("next", hook("quiz-next")), q("coats", "[data-hook='quiz-coat']", "count"), q("back_hidden", hook("quiz-back"), "hidden")]
        out = quiz(actions=[dict(click(card("sports", "MLB")), label="s1", capture=capture), dict(NEXT, label="s2", capture=capture),
                            dict(click(card("personality", "chalk_eater")), label="p", capture=capture), dict(NEXT, label="s3", capture=capture),
                            dict(NEXT, label="s4", capture=capture)])
        c = out["captures"]
        self.assertEqual([c[k]["step"] for k in ("s1", "s2", "s3", "s4")], ["sports", "personality", "risk", "finish"])
        self.assertEqual([c[k]["label"] for k in ("s1", "s2", "s3", "s4")], [f"Step {i} of 4" for i in (1, 2, 3, 4)])
        self.assertEqual([c[k]["valuenow"] for k in ("s1", "s2", "s3", "s4")], ["1", "2", "3", "4"])
        self.assertEqual({c[k]["valuemax"] for k in c}, {"4"})
        self.assertEqual(c["s1"]["cards"], len(LIB["sports"]) + 1)                       # every sport, plus All sports
        self.assertEqual(c["s2"]["cards"], len(LIB["personalities"]))
        self.assertEqual(c["s3"]["cards"], len(LIB["risk_levels"]))
        self.assertEqual((c["s4"]["coats"], c["s4"]["cards"]), (len(LIB["looks"]["coats"]), len(LIB["looks"]["accessories"])))
        self.assertEqual([c[k]["next"] for k in ("s1", "s2", "s3", "s4")], ["Next", "Next", "Next", "Meet my hound"])
        self.assertEqual((c["s1"]["back_hidden"], c["s2"]["back_hidden"]), (True, False))
        self.assertEqual(c["s1"]["q"], "Which sports should it bet?")

    def test_next_waits_for_a_sport_and_a_style_and_back_keeps_the_answer(self):
        out = quiz(actions=[
            dict(click(card("sports", "MLB"), "pick"), capture=[q("pressed", card("sports", "MLB"), "attr", attr="aria-pressed"), q("d", hook("quiz-next"), "disabled")]),
            dict(NEXT, label="n", capture=[q("d", hook("quiz-next"), "disabled")]),
            dict(click(card("personality", "mystic"), "style"), capture=[q("d", hook("quiz-next"), "disabled")]),
            dict(click(card("personality", "mystic"), "unstyle"), capture=[q("d", hook("quiz-next"), "disabled")]),
            dict(click(card("personality", "mystic"), "again")),
            dict(BACK, label="back", capture=[q("step", "[data-hook='quiz-step-body']", "attr", attr="data-step")]),
        ])
        c = out["captures"]
        self.assertEqual(c["pick"], {"pressed": "true", "d": False})
        self.assertEqual((c["n"]["d"], c["style"]["d"], c["unstyle"]["d"]), (True, False, True))
        self.assertEqual(c["back"]["step"], "sports")
        back_to_sports = quiz(actions=[click(card("sports", "MLB")), NEXT, BACK], queries=[q("pressed", card("sports", "MLB"), "attr", attr="aria-pressed")])
        self.assertEqual(back_to_sports["final"]["pressed"], "true")

    def test_the_personality_cards_draw_a_dog_each_and_gematria_and_mystic_are_there(self):
        out = quiz(actions=[click(card("sports", "MLB")), NEXT], queries=[
            q("dogs", "[data-hook='quiz-card'][data-group='personality'] svg.dk-badge", "attrs", attr="data-breed"),
            q("ids", "[data-hook='quiz-card'][data-group='personality']", "attrs", attr="data-id"),
            q("pages", "[data-hook='quiz-card'][data-group='personality']", "attrs", attr="data-page"),
            q("more", hook("quiz-personality-more")), q("count", hook("quiz-personality-count"))])
        f = out["final"]
        self.assertEqual(f["dogs"], [p["breed"] for p in LIB["personalities"]])
        self.assertIn("gematria", f["ids"])
        self.assertIn("mystic", f["ids"])
        self.assertEqual(f["more"], "Show me others")
        self.assertEqual(f["count"], "Page 1 of 2.")
        self.assertLessEqual(max(f["pages"].count(str(n)) for n in range(5)), 4)             # four to a page

    def test_show_me_others_turns_the_personality_page(self):
        out = quiz(actions=[click(card("sports", "MLB")), NEXT, dict(click(hook("quiz-personality-more"), "more"), capture=[
            q("page", hook("quiz-personality-grid"), "attr", attr="data-page"), q("count", hook("quiz-personality-count"))])])
        self.assertEqual(out["captures"]["more"], {"page": "1", "count": "Page 2 of 2."})

    def test_the_risk_step_is_one_three_way_choice_that_starts_in_the_middle(self):
        pressed = lambda r: q(r, card("risk", r), "attr", attr="aria-pressed")          # noqa: E731
        out = quiz(actions=[click(card("sports", "MLB")), NEXT, click(card("personality", "stats_nerd")), NEXT,
                            dict(click(card("risk", "bold"), "bold"), capture=[pressed("steady"), pressed("balanced"), pressed("bold")])],
                   queries=[q("levels", "[data-hook='quiz-card'][data-group='risk'] .qz-pin__title", "texts"), q("segs", "[data-hook='quiz-seg']", "count"),
                            q("cap", "[data-hook='quiz-risk'] .qz-fine", "texts")])
        self.assertEqual(out["final"]["levels"], ["Steady", "Balanced", "Bold"])
        self.assertEqual(out["final"]["segs"], 0)                                          # no number pickers: one choice maps to all three
        self.assertEqual(out["captures"]["bold"], {"steady": "false", "balanced": "false", "bold": "true"})
        self.assertTrue(any("-200 or worse" in t for t in out["final"]["cap"]))
        default = quiz(actions=[click(card("sports", "MLB")), NEXT, click(card("personality", "stats_nerd")), NEXT],
                       queries=[pressed("balanced")])
        self.assertEqual(default["final"]["balanced"], "true")

    def test_the_risk_choice_maps_to_the_price_band_stake_and_cap_the_library_names(self):
        for risk in ("steady", "balanced", "bold"):
            with self.subTest(risk=risk):
                out = quiz(routes=base_routes(derive(["NBA"], "stats_nerd", risk)),
                           actions=[click(card("sports", "NBA")), NEXT, click(card("personality", "stats_nerd")), NEXT, click(card("risk", risk)), NEXT, NEXT])
                body = posts_to(out, "/hounds/quiz/compose")[0]["body"]
                self.assertEqual(body, {"answers": derive(["NBA"], "stats_nerd", risk)})
                level = next(r for r in LIB["risk_levels"] if r["id"] == risk)
                self.assertEqual((body["answers"]["stake"], body["answers"]["bets_per_day"], body["answers"]["price_comfort"]),
                                 (level["stake"], level["bets_per_day"], level["price_comfort"]))

    def test_a_chalk_or_underdog_style_keeps_its_own_prices_and_says_so(self):
        for style in ("chalk_eater", "underdog_hunter"):
            with self.subTest(style=style):
                out = quiz(routes=base_routes(derive(["MLB"], style, "bold")), queries=[q("note", hook("quiz-risk-note"))], actions=[
                    click(card("sports", "MLB")), NEXT, click(card("personality", style)), NEXT, click(card("risk", "bold"))])
                self.assertIn("keeps its own prices", out["final"]["note"])
                out = quiz(routes=base_routes(derive(["MLB"], style, "bold")), actions=[
                    click(card("sports", "MLB")), NEXT, click(card("personality", style)), NEXT, click(card("risk", "bold")), NEXT, NEXT])
                body = posts_to(out, "/hounds/quiz/compose")[0]["body"]["answers"]
                self.assertNotIn("price_comfort", body)
                self.assertEqual((body["stake"], body["bets_per_day"]), (2.0, 3))

    def test_the_last_step_names_and_dresses_the_hound_and_the_name_is_sent(self):
        out = quiz(routes=base_routes({"name": "Biscuit Boss"}), actions=[
            click(card("sports", "MLB")), NEXT, click(card("personality", "chalk_eater")), NEXT, NEXT,
            dict(do="set", sel=hook("quiz-name"), value="Biscuit Boss"),
            dict(click(card("accessory", "sunglasses"), "acc"), capture=[q("face", "[data-hook='quiz-look-preview'] svg.dk-badge", "attr", attr="data-face")]),
            dict(click("[data-hook='quiz-coat'][data-id='red']", "coat"), capture=[
                q("coat", "[data-hook='quiz-look-preview'] svg.dk-badge", "attr", attr="data-coat"), q("face", "[data-hook='quiz-look-preview'] svg.dk-badge", "attr", attr="data-face"),
                q("name", hook("quiz-name"), "value")]),
            NEXT])
        self.assertEqual(out["captures"]["acc"]["face"], "sunglasses")
        self.assertEqual(out["captures"]["coat"], {"coat": "red", "face": "sunglasses", "name": "Biscuit Boss"})    # a pick does not wipe the name box
        body = posts_to(out, "/hounds/quiz/compose")[0]["body"]["answers"]
        self.assertEqual(body["name"], "Biscuit Boss")
        self.assertEqual(body["look"], {"coat": "red", "accessory": "sunglasses"})

    def test_every_personality_makes_a_valid_spec_through_the_page_and_the_real_composer(self):
        """The page is driven for each personality and two risk levels; what it posts goes to the REAL composer, and the spec that comes
        back must pass the real validator with no refused answer. A quiz that could post something compose refuses is a broken quiz."""
        for p in LIB["personalities"]:
            for risk in ("steady", "bold"):
                with self.subTest(personality=p["id"], risk=risk):
                    out = quiz(actions=[click(card("sports", "MLB")), NEXT, click(card("personality", p["id"])), NEXT, click(card("risk", risk)), NEXT, NEXT])
                    answers = posts_to(out, "/hounds/quiz/compose")[0]["body"]["answers"]
                    self.assertEqual(answers, derive(["MLB"], p["id"], risk))
                    res = C.compose(answers)
                    user_spec.validate_spec(res["spec"])
                    self.assertEqual(res["spec"].get("style") == "gematria", p.get("style") == "gematria")
                    refused = [w["code"] for w in res["warnings"] if w["level"] != "note"]
                    self.assertFalse([c for c in refused if c in ("answer_ignored", "name_rejected")], refused)

    def test_every_sport_the_library_offers_composes_with_the_defaults(self):
        for row in LIB["sports"] + [LIB["sports_any"]]:
            with self.subTest(sport=row["value"]):
                res = C.compose(derive([row["value"]], "stats_nerd"))
                user_spec.validate_spec(res["spec"])
                self.assertEqual([w["code"] for w in res["warnings"] if w["level"] == "heads_up"], [])

    def test_the_four_answers_are_saved_and_start_over_clears_them(self):
        out = quiz(actions=[click(card("sports", "NFL")), click(card("sports", "MLB")), NEXT, click(card("personality", "mystic")), NEXT, click(card("risk", "steady"))],
                   queries=[q("restart_hidden", hook("quiz-restart"), "hidden")])
        saved = json.loads(out["storedAfter"][DRAFT_KEY])
        self.assertEqual((saved["answers"]["sports"], saved["answers"]["personality"], saved["answers"]["risk"], saved["step"]),
                         (["NFL", "MLB"], "mystic", "steady", 2))
        self.assertFalse(out["final"]["restart_hidden"])
        cleared = quiz(actions=[click(card("sports", "NFL")), click(hook("quiz-restart"), "restart")],
                       queries=[q("pressed", card("sports", "NFL"), "attr", attr="aria-pressed"), q("step", hook("quiz-step"))])
        self.assertEqual((cleared["final"]["pressed"], cleared["final"]["step"]), ("false", "Step 1 of 4"))
        self.assertNotIn(DRAFT_KEY, cleared["storedAfter"])

    def test_no_card_text_makes_a_claim_or_names_a_price_at_minus_200(self):
        out = quiz(actions=QUICK[:-1])
        text = out["text"].lower()
        for pattern in CLAIMS:
            self.assertIsNone(re.search(pattern, text), pattern)
        for m in re.finditer(r"(?<![\w-])-(\d{3,4})\b", text):
            if int(m.group(1)) >= 200:
                self.assertTrue(text[m.start():].startswith("-200 or worse"), text[m.start() - 20:m.start() + 30])

    # ---- the sports step (a chip grid with an All sports chip) -------------------------------------------------------------

    def test_the_sport_step_is_a_chip_grid_with_every_sport_most_popular_first_and_an_all_sports_chip(self):
        out = quiz(queries=[
            q("chips", "[data-hook='quiz-sports-grid'] [data-hook='quiz-card']", "texts"),
            q("more", hook("quiz-sports-more")), q("more_open", hook("quiz-sports-more"), "attr", attr="aria-expanded"),
            q("extra_hidden", hook("quiz-sports-extra"), "hidden"), q("extra", "[data-hook='quiz-sports-extra'] [data-hook='quiz-card']", "texts"),
            q("all", "[data-hook='quiz-card']", "count"), q("pins", ".qz-pin", "count")])
        f = out["final"]
        self.assertEqual(f["chips"], ["NBA", "NFL", "NHL", "College football", "Soccer", "Tennis", "MLB", "MMA", "All sports"])
        self.assertEqual(f["more"], f"More ({len(LIB['sports']) - 8})")
        self.assertEqual((f["more_open"], f["extra_hidden"]), ("false", True))
        self.assertEqual(f["pins"], 0)
        self.assertEqual(sorted(f["chips"][:8] + f["extra"]), sorted(r["label"] for r in LIB["sports"]))
        self.assertEqual(f["all"], len(LIB["sports"]) + 1)

    def test_more_opens_the_rest_and_a_pick_in_it_keeps_it_open(self):
        out = quiz(actions=[click(hook("quiz-sports-more"), "open", capture=[q("hidden", hook("quiz-sports-extra"), "hidden"), q("label", hook("quiz-sports-more")),
                                                                          q("expanded", hook("quiz-sports-more"), "attr", attr="aria-expanded")]),
                            click(card("sports", "WNBA"), "wnba", capture=[q("on", card("sports", "WNBA"), "attr", attr="aria-pressed")]),
                            click(hook("quiz-sports-more"), "close", capture=[q("hidden", hook("quiz-sports-extra"), "hidden")])])
        c = out["captures"]
        self.assertEqual(c["open"], {"hidden": False, "label": "Fewer", "expanded": "true"})
        self.assertEqual(c["wnba"]["on"], "true")
        self.assertFalse(c["close"]["hidden"])                      # WNBA is picked, so its row stays showing even after Fewer

    def test_sports_take_many_and_all_sports_is_a_different_answer_from_a_list(self):
        pressed = lambda ident: q(ident, card("sports", ident), "attr", attr="aria-pressed")           # noqa: E731
        caps = [pressed("NBA"), pressed("NHL"), pressed("ANY")]
        out = quiz(actions=[click(card("sports", "NBA")), click(card("sports", "NHL"), "two", capture=caps),
                            click(card("sports", "ANY"), "any", capture=caps),
                            click(card("sports", "NBA"), "list_again", capture=caps),
                            click(card("sports", "ANY"), "any2"), click(card("sports", "ANY"), "off", capture=caps)])
        c = out["captures"]
        self.assertEqual(c["two"], {"NBA": "true", "NHL": "true", "ANY": "false"})
        self.assertEqual(c["any"], {"NBA": "false", "NHL": "false", "ANY": "true"})
        self.assertEqual(c["list_again"], {"NBA": "true", "NHL": "false", "ANY": "false"})
        self.assertEqual(c["off"], {"NBA": "false", "NHL": "false", "ANY": "false"})

    def test_the_sports_go_to_compose_as_the_composer_expects_them(self):
        pick = [click(card("sports", "TENNIS")), click(card("sports", "NCAAF")), NEXT, click(card("personality", "chalk_eater")), NEXT, NEXT, NEXT]
        out = quiz(routes=base_routes(derive(["TENNIS", "NCAAF"], "chalk_eater")), actions=pick)
        self.assertEqual(posts_to(out, "/hounds/quiz/compose")[0]["body"], {"answers": derive(["TENNIS", "NCAAF"], "chalk_eater")})
        anything = quiz(routes=base_routes(derive([user_spec.ANY], "chalk_eater")),
                        actions=[click(card("sports", "ANY")), NEXT, click(card("personality", "chalk_eater")), NEXT, NEXT, NEXT])
        self.assertEqual(posts_to(anything, "/hounds/quiz/compose")[0]["body"]["answers"]["sports"], ["ANY"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheReveal(unittest.TestCase):

    def test_the_shortest_path_posts_the_four_answers_and_their_defaults_and_reveals_the_hound(self):
        fixture = composed(QUICK_ANSWERS)
        out = quiz(routes=base_routes(QUICK_ANSWERS), actions=skip_all(), queries=[
            q("rules", "[data-hook='reveal-rule-text']", "texts"), q("cards", "[data-hook='reveal-rule']", "count"),
            q("name", hook("reveal-name"), "value"), q("chips", hook("reveal-name-chip"), "texts"),
            q("dog_pose", "[data-hook='reveal-dog'] svg.dk-badge", "attr", attr="data-pose"),
            q("globals", hook("reveal-global"), "texts"), q("save_disabled", hook("reveal-save"), "disabled"),
            q("shell_hidden", hook("quiz-shell"), "hidden"), q("reveal_hidden", hook("quiz-reveal"), "hidden"),
            q("honesty", hook("reveal-honesty"))])
        f = out["final"]
        self.assertEqual(posts_to(out, "/hounds/quiz/compose")[0]["body"], {"answers": QUICK_ANSWERS})
        self.assertEqual(f["rules"], [c["body"] for c in fixture["rule_cards"]])
        self.assertEqual(f["globals"], fixture["global_sentences"])
        self.assertEqual(f["name"], fixture["spec"]["name"])
        self.assertEqual(f["chips"], fixture["name_suggestions"])
        self.assertEqual(f["dog_pose"], "celebrate")
        self.assertEqual((f["shell_hidden"], f["reveal_hidden"], f["save_disabled"]), (True, False, False))
        self.assertIn("none of these is known to win", f["honesty"])

    def test_every_pick_goes_to_compose_as_the_composer_expects_it(self):
        out = quiz(routes=base_routes(COMBO_ANSWERS), actions=COMBO_ACTIONS, queries=[
            q("labels", ".qz-rule__label", "texts"), q("sources", "[data-hook='reveal-rule']", "attrs", attr="data-source"),
            q("breed", "[data-hook='reveal-dog'] svg.dk-badge", "attr", attr="data-breed"),
            q("coat", "[data-hook='reveal-dog'] svg.dk-badge", "attr", attr="data-coat"), q("head", "[data-hook='reveal-dog'] svg.dk-badge", "attr", attr="data-head")])
        body = posts_to(out, "/hounds/quiz/compose")[0]["body"]
        self.assertEqual(body, {"answers": COMBO_ANSWERS})
        fixture = composed(COMBO_ANSWERS)
        self.assertEqual(out["final"]["labels"], [c["label"] for c in fixture["rule_cards"]])
        self.assertEqual(out["final"]["breed"], "bulldog")
        self.assertEqual((out["final"]["coat"], out["final"]["head"]), ("golden", "cap"))
        # the answers were saved on the way, so a reload could pick the quiz back up
        draft = json.loads(out["storedAfter"][DRAFT_KEY])
        self.assertEqual(draft["answers"]["risk"], "bold")
        self.assertEqual(draft["stage"], "reveal")

    def test_warnings_from_the_composer_are_shown_as_heads_up(self):
        answers = {"markets": ["moneyline"], "personality": "chalk_eater", "price_comfort": "plus"}      # the composer's own price conflict
        fixture = composed(answers)
        out = quiz(routes=base_routes(answers), actions=skip_all(),
                   queries=[q("warn", hook("reveal-warning"), "texts"), q("eyebrow", "[data-hook='reveal-warnings'] .qz-eyebrow")])
        self.assertIn("price_conflict", [w["code"] for w in fixture["warnings"]])
        self.assertTrue(any("later answer wins" in w for w in out["final"]["warn"]))
        self.assertEqual(out["final"]["eyebrow"], "Heads up")

    def test_the_preview_says_how_many_games_fit_and_how_many_it_would_have_bet(self):
        out = quiz(routes=base_routes(preview=None, **{"POST /hounds/builder/preview": [200, preview_answer(qualifying=3, cap=2, board=41)]}),
                   actions=skip_all(), queries=[q("count", hook("reveal-preview-count")), q("sub", hook("reveal-preview-sub")),
                                                q("picks", hook("reveal-pick"), "texts"), q("state", hook("reveal-preview"), "attr", attr="data-state")])
        name = "Good Boy Gary"
        self.assertEqual(out["final"]["count"], f"3 of 41 games fit {name}'s rule today.")
        self.assertEqual(out["final"]["sub"], f"{name} would have bet 2, with a cap of 2 a day.")
        self.assertEqual(out["final"]["picks"], ["Boston Red Sox at New York Yankees · Boston Red Sox to win · +120"] * 2)
        self.assertEqual(out["final"]["state"], "picks")
        spec = posts_to(out, "/hounds/builder/preview")[0]["body"]["spec"]
        user_spec.validate_spec(spec)

    def test_a_board_that_fits_nothing_is_a_pass_and_part_of_the_record(self):
        out = quiz(routes=base_routes(**{"POST /hounds/builder/preview": [200, preview_answer(qualifying=0, board=12)]}), actions=skip_all(),
                   queries=[q("count", hook("reveal-preview-count")), q("sub", hook("reveal-preview-sub")),
                            q("state", hook("reveal-preview"), "attr", attr="data-state"), q("picks", hook("reveal-pick"), "count"),
                            q("loosen", "[data-hook='reveal-preview'] button", "count"), q("retry_row", hook("reveal-preview-retry-row"), "hidden")])
        self.assertEqual(out["final"]["count"], "Good Boy Gary passes today. Nothing on the board fits its rule.")
        self.assertEqual(out["final"]["sub"], "A pass is a valid day for a hound.")
        self.assertEqual((out["final"]["state"], out["final"]["picks"]), ("zero", 0))
        # no "loosen your rule" action: the only button in the panel is the retry, and it is hidden
        self.assertEqual(out["final"]["loosen"], 1)
        self.assertTrue(out["final"]["retry_row"])

    def test_a_board_that_did_not_load_shows_no_number_and_a_retry(self):
        down = quiz(routes=base_routes(**{"POST /hounds/builder/preview": [503, {"detail": {"error": "board_unavailable"}}]}), actions=skip_all(),
                    queries=[q("count", hook("reveal-preview-count")), q("retry_row", hook("reveal-preview-retry-row"), "hidden"),
                             q("state", hook("reveal-preview"), "attr", attr="data-state")])
        self.assertEqual(down["final"]["count"], "Today's board is not loaded right now.")
        self.assertFalse(down["final"]["retry_row"])
        self.assertEqual(down["final"]["state"], "not_loaded")
        self.assertNotRegex(down["final"]["count"], r"\d")

    def test_a_game_board_with_no_games_says_so(self):
        empty = quiz(routes=base_routes(**{"POST /hounds/builder/preview": [200, preview_answer(qualifying=0, board=0)]}), actions=skip_all(),
                     queries=[q("count", hook("reveal-preview-count"))])
        self.assertEqual(empty["final"]["count"], "No games on today's board yet.")

    def test_a_price_of_minus_200_or_worse_is_never_shown(self):
        answer = preview_answer(qualifying=2, cap=2, board=5)
        answer["picks"][0]["price"] = -200
        answer["picks"][1]["price"] = -135
        out = quiz(routes=base_routes(**{"POST /hounds/builder/preview": [200, answer]}), actions=skip_all(),
                   queries=[q("picks", hook("reveal-pick"), "texts"), q("count", hook("reveal-preview-count"))])
        self.assertEqual(len(out["final"]["picks"]), 1)
        self.assertIn("-135", out["final"]["picks"][0])
        self.assertNotIn("-200", " ".join(out["final"]["picks"]))
        self.assertTrue(out["final"]["count"].startswith("1 of 5 games fit"))

    def test_a_compose_failure_says_so_and_offers_retry_and_the_builder(self):
        out = quiz(routes=base_routes(**{"POST /hounds/quiz/compose": [500, {}]}), actions=skip_all(), queries=[
            q("state", hook("reveal-state")), q("retry", hook("reveal-retry"), "count"), q("body_hidden", hook("reveal-body"), "hidden"),
            q("link", "[data-hook='reveal-state'] a", "attr", attr="href")])
        self.assertIn("could not be loaded", out["final"]["state"])
        self.assertEqual((out["final"]["retry"], out["final"]["body_hidden"], out["final"]["link"]), (1, True, "build-a-hound.html"))

    def test_english_add_on_parses_then_composes_in_and_shows_how_it_was_read(self):
        text = "also bet home underdogs between +120 and +200 when they're on 2+ days rest"
        parsed = json.loads(json.dumps(parser.parse(text)))
        merged = composed({}, english_text=text)
        routes = base_routes({})
        routes["POST /hounds/english"] = [200, {"status": "parsed", "text": text, **parsed, "unread": [], "paper_only": True}]
        out = quiz(routes=routes, actions=skip_all() + [
            dict(do="set", sel=hook("reveal-english-input"), value=text, label="type"),
            dict(do="click", sel=hook("reveal-english-go"), label="add", capture=[
                q("understood", "[data-hook='reveal-english-understood'] li", "texts"), q("read_hidden", hook("reveal-english-read"), "hidden")])],
                   switchAfter={"/hounds/quiz/compose": [1, [200, merged]]},
                   queries=[q("sources", "[data-hook='reveal-rule']", "attrs", attr="data-source"), q("labels", ".qz-rule__label", "texts")])
        c = out["captures"]["add"]
        self.assertFalse(c["read_hidden"])
        self.assertTrue(any("is read as" in u for u in c["understood"]))
        english_posts = posts_to(out, "/hounds/english")
        self.assertEqual(english_posts[0]["body"], {"text": text})
        composes = posts_to(out, "/hounds/quiz/compose")
        self.assertEqual(len(composes), 2)
        self.assertEqual(composes[1]["body"]["english_draft"], parsed["draft"])
        self.assertEqual(out["final"]["sources"][-1], "english")
        self.assertEqual(out["final"]["labels"][-1], C.ENGLISH_LABEL)
        draft = json.loads(out["storedAfter"][DRAFT_KEY])
        self.assertEqual(draft["english"]["text"], text)

    def test_words_the_reader_cannot_use_are_listed_and_not_composed(self):
        text = "bet when Mercury is in retrograde"
        parsed = json.loads(json.dumps(parser.parse(text)))
        routes = base_routes({})
        routes["POST /hounds/english"] = [200, {"status": "partial", "text": text, **parsed, "unread": ["Mercury"], "paper_only": True}]
        out = quiz(routes=routes, actions=skip_all() + [dict(do="set", sel=hook("reveal-english-input"), value=text),
                                                       click(hook("reveal-english-go"), "go")],
                   queries=[q("bad", "[data-hook='reveal-english-notread'] li", "texts")])
        self.assertTrue(any("was not understood" in t for t in out["final"]["bad"]))
        self.assertEqual(len(posts_to(out, "/hounds/quiz/compose")), 1)         # nothing readable, nothing re-composed

    def test_edit_rules_hands_the_spec_to_the_builder(self):
        fixture = composed({})
        out = quiz(actions=skip_all() + [click(hook("reveal-edit"), "edit", wait=80)])
        handoff = json.loads(out["storedAfter"][HANDOFF_KEY])
        self.assertEqual(handoff["spec"]["rules"], fixture["spec"]["rules"])
        self.assertEqual(handoff["spec"]["name"], fixture["spec"]["name"])
        self.assertTrue(handoff["sentences"])
        self.assertEqual(out["navigations"], ["build-a-hound.html?quiz=1"])

    def test_a_typed_name_is_what_gets_sent(self):
        fixture = composed({"name": "Biscuit Boss"})
        out = quiz(routes=base_routes({}, **{"POST /hounds": [201, {"hound": {"id": "u-9", "name": "Biscuit Boss"}}],
                                             "PUT /hounds/u-9/look": [200, {}]}), **SIGNED, actions=skip_all() + [
            dict(do="set", sel=hook("reveal-name"), value="Biscuit Boss", label="name"),
            click(hook("reveal-save"), "save", wait=100)])
        sent = posts_to(out, "/hounds")[0]["body"]["spec"]
        self.assertEqual(sent["name"], "Biscuit Boss")
        self.assertEqual(fixture["spec"]["name"], "Biscuit Boss")


@unittest.skipUnless(HAS_NODE, "node not installed")
class KeepTheHound(unittest.TestCase):
    """"Keep {Name}" on the reveal: one form makes a free account, signs in, saves the hound, with no redirect."""
    FILL = [dict(do="set", sel=hook("reveal-keep-email"), value="fan@example.com", label="email"),
            dict(do="set", sel=hook("reveal-keep-password"), value="correct horse battery", label="pw")]
    SUBMIT = dict(do="submit", sel=hook("reveal-keep-form"), label="keep", wait=150)

    def routes(self, **over):
        return base_routes(COMBO_ANSWERS, **{"POST /auth/signup": [200, {"token": "newtok", "kind": "free"}],
                                             "POST /hounds": [201, {"hound": {"id": "u-7", "name": "Chalk Chomper"}}],
                                             "PUT /hounds/u-7/look": [200, {}], **over})

    def test_a_signed_out_visitor_sees_the_form_and_a_keep_button_with_the_name(self):
        out = quiz(routes=self.routes(), actions=COMBO_ACTIONS, queries=[
            q("hidden", hook("reveal-keep"), "hidden"), q("btn", hook("reveal-keep-submit")), q("age", hook("reveal-keep-age"), "exists"),
            q("title", hook("reveal-keep-title"))])
        f = out["final"]
        self.assertFalse(f["hidden"])
        self.assertTrue(f["btn"].startswith("Keep ") and len(f["btn"]) > 5)
        self.assertTrue(f["age"])

    def test_without_the_21_plus_box_nothing_is_sent_and_the_sentence_says_why(self):
        out = quiz(routes=self.routes(), actions=COMBO_ACTIONS + self.FILL + [self.SUBMIT],
                   queries=[q("status", hook("reveal-keep-status"))])
        self.assertEqual(posts_to(out, "/auth/signup"), [])
        self.assertEqual(posts_to(out, "/hounds"), [])
        self.assertIn("21 or older", out["final"]["status"])

    def test_with_the_box_it_signs_up_signs_in_saves_the_hound_and_does_not_redirect(self):
        out = quiz(routes=self.routes(), actions=COMBO_ACTIONS + self.FILL + [
            dict(do="check", sel=hook("reveal-keep-age"), label="age"), self.SUBMIT],
            queries=[q("saved", hook("reveal-saved"), "exists")])
        signup = posts_to(out, "/auth/signup")[0]["body"]
        self.assertIs(signup["age_confirmed"], True)
        self.assertEqual(signup["email"], "fan@example.com")
        sent = posts_to(out, "/hounds")[0]["body"]
        user_spec.validate_spec(sent["spec"])
        self.assertEqual(out["storedAfter"][TOKEN_KEY], "newtok")
        self.assertEqual(out["navigations"], [])
        self.assertTrue(out["final"]["saved"])

    def test_a_refused_signup_saves_nothing(self):
        out = quiz(routes=self.routes(**{"POST /auth/signup": [400, {"detail": {"error": "age_required", "message": "Confirm that you are 21 or older to make an account."}}]}),
                   actions=COMBO_ACTIONS + self.FILL + [dict(do="check", sel=hook("reveal-keep-age"), label="age"), self.SUBMIT],
                   queries=[q("status", hook("reveal-keep-status"))])
        self.assertEqual(posts_to(out, "/hounds"), [])
        self.assertNotIn(TOKEN_KEY, out["storedAfter"])
        self.assertIn("21 or older", out["final"]["status"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class SavingAndSigningIn(unittest.TestCase):

    def test_signed_out_send_asks_for_sign_in_keeps_the_draft_and_posts_nothing(self):
        out = quiz(routes=base_routes(COMBO_ANSWERS), actions=COMBO_ACTIONS + [click(hook("reveal-save"), "save")], queries=[
            q("panel_hidden", hook("reveal-signin"), "hidden"), q("signin", hook("reveal-signin-link"), "attr", attr="href"),
            q("signup", hook("reveal-signup-link"), "attr", attr="href"), q("text", hook("reveal-signin-text"))])
        f = out["final"]
        self.assertFalse(f["panel_hidden"])
        self.assertEqual((f["signin"], f["signup"]), ("index.html#/signin", "index.html#/signup"))
        self.assertIn("saved on this device", f["text"])
        self.assertEqual(posts_to(out, "/hounds"), [])
        draft = json.loads(out["storedAfter"][DRAFT_KEY])
        self.assertTrue(draft["pendingSave"])
        self.assertEqual(draft["answers"]["personality"], "chalk_eater")
        self.assertEqual(draft["answers"]["look"], {"coat": "golden", "accessory": "cap"})

    def test_the_draft_survives_a_sign_in_and_the_hound_is_waiting_on_the_reveal(self):
        first = quiz(routes=base_routes(COMBO_ANSWERS), actions=COMBO_ACTIONS + [click(hook("reveal-save"), "save")])
        draft = first["storedAfter"][DRAFT_KEY]
        # the person signs in elsewhere and comes back to quiz.html: same store, now with a token
        out = quiz(routes=base_routes(COMBO_ANSWERS, **{"POST /hounds": [201, {"hound": {"id": "u-5", "name": "Chalk Chomper"}}],
                                                       "PUT /hounds/u-5/look": [200, {}]}),
                   stored={TOKEN_KEY: "tok", DRAFT_KEY: draft}, actions=[click(hook("reveal-save"), "save", wait=100)], queries=[
            q("reveal_hidden", hook("quiz-reveal"), "hidden"), q("msg", hook("reveal-message")), q("saved", hook("reveal-saved"), "exists"),
            q("link", hook("reveal-saved-link"), "attr", attr="href")])
        self.assertEqual(posts_to(out, "/hounds/quiz/compose")[0]["body"], {"answers": COMBO_ANSWERS})   # rebuilt from the saved answers
        self.assertTrue(out["final"]["saved"])
        self.assertEqual(out["final"]["link"], "hound.html?id=u-5")
        sent = posts_to(out, "/hounds")[0]["body"]
        self.assertEqual(list(sent), ["spec"])
        user_spec.validate_spec(sent["spec"])
        look = posts_to(out, "/hounds/u-5/look")[0]["body"]["look"]
        self.assertEqual((look["coat"], look["head"]), ("golden", "cap"))
        self.assertNotIn(DRAFT_KEY, out["storedAfter"])                                                   # sent in: nothing left to resume

    def test_a_signed_in_return_shows_a_welcome_and_a_signed_out_return_resumes_the_step(self):
        first = quiz(routes=base_routes(COMBO_ANSWERS), actions=COMBO_ACTIONS + [click(hook("reveal-save"), "save")])
        draft = first["storedAfter"][DRAFT_KEY]
        member = quiz(routes=base_routes(COMBO_ANSWERS), stored={TOKEN_KEY: "tok", DRAFT_KEY: draft},
                      queries=[q("msg", hook("reveal-message")), q("reveal_hidden", hook("quiz-reveal"), "hidden")])
        self.assertIn("You are signed in", member["final"]["msg"])
        self.assertFalse(member["final"]["reveal_hidden"])
        # a signed-out visitor with a saved quiz reopens it at the step it was left on (the quiz has no intro screen to choose from)
        visitor = quiz(routes=base_routes(COMBO_ANSWERS), stored={DRAFT_KEY: draft},
                       queries=[q("start", hook("quiz-start"), "count"), q("restart_hidden", hook("quiz-restart"), "hidden"), q("step", hook("quiz-step"))])
        self.assertEqual(visitor["final"]["start"], 0)
        self.assertFalse(visitor["final"]["restart_hidden"])

    def test_resume_goes_back_to_the_saved_step_with_the_answers_in_place(self):
        draft = {"v": 1, "answers": {"sports": ["NFL"], "personality": "mystic", "risk": "steady", "look": {"coat": None, "accessory": None}},
                 "step": 2, "stage": "quiz", "name": "", "tagline": "", "english": {"text": "", "draft": None}, "pendingSave": False}
        out = quiz(stored={DRAFT_KEY: json.dumps(draft)}, queries=[
            q("step", "[data-hook='quiz-step-body']", "attr", attr="data-step"), q("steady", card("risk", "steady"), "attr", attr="aria-pressed")],
            actions=[dict(BACK, label="b1", capture=[q("mystic", card("personality", "mystic"), "attr", attr="aria-pressed")]),
                     dict(BACK, label="b2", capture=[q("nfl", card("sports", "NFL"), "attr", attr="aria-pressed")])])
        self.assertEqual(out["captures"]["b1"]["mystic"], "true")
        self.assertEqual(out["captures"]["b2"]["nfl"], "true")

    def test_a_draft_from_the_eight_question_quiz_still_opens_without_breaking(self):
        old = {"v": 1, "answers": {"sports": ["NFL"], "markets": ["spread"], "personality": "chalk_eater", "bets_per_day": 3, "stake": 1.0,
                                  "price_comfort": "even", "timing": "late", "archetypes": ["windy_overs"], "quirks": ["full_moon"], "letter": None,
                                  "look": {"coat": "golden", "accessory": None}}, "step": 6, "stage": "quiz", "name": "", "tagline": "",
               "english": {"text": "", "draft": None}, "pendingSave": False}
        out = quiz(stored={DRAFT_KEY: json.dumps(old)}, queries=[q("q", hook("quiz-question")), q("step", hook("quiz-step"))])
        self.assertEqual((out["final"]["q"], out["final"]["step"]), ("Which sports should it bet?", "Step 1 of 4"))     # a step past 4 starts over, answers kept

    def test_a_blocked_or_throwing_store_never_breaks_the_quiz(self):
        for mode in ("methods", "accessor"):
            with self.subTest(mode=mode):
                out = quiz(storageThrows=mode, actions=COMBO_ACTIONS + [click(hook("reveal-save"), "save")], queries=[
                    q("panel_hidden", hook("reveal-signin"), "hidden"), q("cards", "[data-hook='reveal-rule']", "count")])
                self.assertFalse(out["final"]["panel_hidden"])                 # signed out: still asked to sign in
                self.assertGreater(out["final"]["cards"], 0)

    def test_save_errors_are_said_not_swallowed(self):
        cases = [(422, {"detail": {"error": "spec_invalid", "message": "x", "fields": {"name": "is already taken"}}}, "name: is already taken"),
                 (409, {"detail": {"error": "limit", "message": "You already have 3 hounds running."}}, "3 hounds running"),
                 (500, {}, "could not be loaded")]
        for status, body, wanted in cases:
            with self.subTest(status=status):
                out = quiz(routes=base_routes({}, **{"POST /hounds": [status, body]}), **SIGNED,
                           actions=skip_all() + [click(hook("reveal-save"), "save", wait=100)], queries=[q("err", hook("reveal-error")), q("saved", hook("reveal-saved"), "exists")])
                self.assertIn(wanted, out["final"]["err"])
                self.assertFalse(out["final"]["saved"])
        lapsed = quiz(routes=base_routes({}, **{"POST /hounds": [401, {"detail": "no"}]}), **SIGNED,
                      actions=skip_all() + [click(hook("reveal-save"), "save", wait=100)], queries=[q("panel_hidden", hook("reveal-signin"), "hidden")])
        self.assertFalse(lapsed["final"]["panel_hidden"])

    def test_backtest_needs_a_sign_in_and_labels_hindsight_when_it_runs(self):
        visitor = quiz(actions=skip_all() + [click(hook("reveal-backtest-go"), "bt")], queries=[
            q("panel_hidden", hook("reveal-signin"), "hidden"), q("text", hook("reveal-signin-text"))])
        self.assertFalse(visitor["final"]["panel_hidden"])
        self.assertIn("backtest", visitor["final"]["text"])
        self.assertEqual(posts_to(visitor, "/hounds/drill"), [])
        drill = {"label": "Hindsight drill: not counted", "disclosure": "A rehearsal and not evidence.",
                 "record": {"bets": 9, "graded": 9, "wins": 4, "losses": 5, "pushes": 0}, "units_average_price": -1.25,
                 "sample_note": "9 graded bets: a small sample, so wins and losses this few are mostly luck.", "counted": False}
        member = quiz(routes=base_routes({}, **{"POST /hounds/drill": [200, drill]}), **SIGNED,
                      actions=skip_all() + [click(hook("reveal-backtest-go"), "bt", wait=100)], queries=[
            q("label", hook("reveal-backtest-label")), q("record", hook("reveal-backtest-record")), q("note", hook("reveal-backtest-note"))])
        body = posts_to(member, "/hounds/drill")[0]["body"]
        self.assertEqual(body["days"], 14)
        user_spec.validate_spec(body["spec"])
        self.assertEqual(member["final"]["label"], "Hindsight drill: not counted")
        self.assertEqual(member["final"]["record"], "4-5 over 9 bets, -1.25u at the average price")
        self.assertIn("small sample", member["final"]["note"])
        busy = quiz(routes=base_routes({}, **{"POST /hounds/drill": [429, {"detail": {"error": "drill_busy"}}]}), **SIGNED,
                    actions=skip_all() + [click(hook("reveal-backtest-go"), "bt", wait=100)], queries=[q("err", hook("reveal-backtest-error"))])
        self.assertIn("Another backtest is running", busy["final"]["err"])

    def test_backtest_for_a_free_account_shows_the_member_prompt_not_a_plain_error(self):
        """Backtest is a member tool: a free account's POST /hounds/drill is a 402 `upgrade_required`, and the quiz
        shows the same prompt the builder, Ask and Live show (web/js/upgrade.js) instead of an error line."""
        refusal = {"detail": {"error": "upgrade_required", "feature": "backtest",
                              "message": "Backtest is for members. A free account keeps one dog."}}
        out = quiz(routes=base_routes({}, **{"POST /hounds/drill": [402, refusal]}), **SIGNED,
                   actions=skip_all() + [click(hook("reveal-backtest-go"), "bt", wait=100)], queries=[
            q("prompt", hook("upgrade-prompt"), "count"), q("title", ".upgrade-prompt__title"),
            q("body", ".upgrade-prompt__body"), q("link", hook("upgrade-link"), "attr", attr="href"),
            q("plain_error", hook("reveal-backtest-error"), "count"), q("inside", "[data-hook='reveal-backtest-result'] [data-hook='upgrade-prompt']", "count"),
            q("signin_hidden", hook("reveal-signin"), "hidden"), q("go_disabled", hook("reveal-backtest-go"), "attr", attr="disabled")])
        f = out["final"]
        self.assertEqual((f["prompt"], f["inside"], f["plain_error"]), (1, 1, 0))
        self.assertEqual(f["title"], "Backtest is a member tool")
        self.assertIn("A free account keeps one dog", f["body"])
        self.assertEqual(f["link"], "index.html#/billing")
        self.assertTrue(f["signin_hidden"], "a 402 is not a sign-in problem")
        self.assertFalse(f["go_disabled"], "the button must work again after the refusal")
        # A 402 that is NOT the upgrade refusal still gets the ordinary error line.
        other = quiz(routes=base_routes({}, **{"POST /hounds/drill": [402, {"detail": {"error": "subscription_expired", "message": "Your plan ended."}}]}),
                     **SIGNED, actions=skip_all() + [click(hook("reveal-backtest-go"), "bt", wait=100)], queries=[
            q("prompt", hook("upgrade-prompt"), "count"), q("err", hook("reveal-backtest-error"))])
        self.assertEqual(other["final"]["prompt"], 0)
        self.assertIn("Your plan ended", other["final"]["err"])

    def test_reveal_text_has_no_claims_and_no_price_at_minus_200(self):
        out = quiz(routes=base_routes(COMBO_ANSWERS), actions=COMBO_ACTIONS)
        text = out["text"].lower()
        for pattern in CLAIMS:
            self.assertIsNone(re.search(pattern, text), pattern)
        for m in re.finditer(r"(?<![\w-])-(\d{3,4})\b", text):
            if int(m.group(1)) >= 200:
                self.assertTrue(text[m.start():].startswith("-200 or worse"), text[m.start() - 20:m.start() + 30])
        self.assertIn("paper bets only", text)
        self.assertIn("21+", text)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheEntryPoints(unittest.TestCase):
    """Four small hooks into other pages: the builder's top CTA and its ?quiz=1 hand-off, the kennel's Build a dog card, the landing
    Kennels card, and the navigation's Build link (quiz first, with Skip to builder on the quiz itself)."""

    def test_the_builder_page_opens_with_a_take_the_quiz_button(self):
        html = (WEB / "build-a-hound.html").read_text(encoding="utf-8")
        self.assertRegex(html, r'<a [^>]*href="quiz.html"[^>]*data-hook="build-quiz-cta"[^>]*>Take the quiz</a>')
        self.assertLess(html.index('data-hook="build-quiz-cta"'), html.index('data-hook="step-describe"'))

    def test_the_quiz_hands_its_spec_to_the_builder_which_shows_it_as_a_draft(self):
        from tests import test_hounds_builder_web as B
        fixture = composed({"personality": "mystic", "markets": ["moneyline"], "name": "Biscuit Boss"})
        handoff = json.dumps({"spec": fixture["spec"], "sentences": fixture["sentences"], "at": 1})
        out = run_page("build", routes=B.base_routes(), search="?quiz=1", stored={HANDOFF_KEY: handoff}, settleMs=600, queries=[
            q("note", hook("build-from-note")), q("name", hook("f-name"), "value"), q("cards", "[data-hook='rule-card']", "count"),
            q("sentences", "[data-hook='rule-sentences'] li", "texts")])
        self.assertIn("Built from your quiz", out["final"]["note"])
        self.assertEqual(out["final"]["name"], "Biscuit Boss")
        posted = B.preview_posts(out)
        self.assertTrue(posted)
        self.assertEqual(posted[-1]["rules"][0]["markets"], ["moneyline"])
        self.assertNotIn("sports", posted[-1])                          # the builder strips the derived keys, as for any draft
        user_spec.validate_spec({**posted[-1], "name": "Biscuit Boss"})

    def test_the_builder_without_a_hand_off_says_so_and_stays_blank(self):
        from tests import test_hounds_builder_web as B
        out = run_page("build", routes=B.base_routes(), search="?quiz=1", queries=[q("note", hook("build-from-note")), q("cards", "[data-hook='rule-card']", "count")])
        self.assertIn("could not be found", out["final"]["note"])
        self.assertEqual(out["final"]["cards"], 0)
        broken = run_page("build", routes=B.base_routes(), search="?quiz=1", stored={HANDOFF_KEY: "{not json"}, queries=[q("note", hook("build-from-note"))])
        self.assertIn("could not be found", broken["final"]["note"])

    def test_my_kennels_create_a_hound_button_opens_the_quiz(self):
        # # owner ruling 2026-10-20 kennel-first: the "Build a dog" card became one quiet "Create a hound" link in the header
        from tests import test_kennel_page as K
        out = run_page("kennel", routes={"/hounds/kennels/mine": K.mine([K.dog()])}, **SIGNED,
                       queries=[q("href", hook("kennel-build"), "attr", attr="href"), q("label", hook("kennel-build"))])
        self.assertEqual(out["final"], {"href": "quiz.html", "label": "Create a hound"})

    def test_the_landing_pages_one_button_opens_the_quiz_at_its_first_question(self):
        html = (WEB / "landing.html").read_text(encoding="utf-8")
        # owner ruling 2026-10-21: the landing's "Make my first hound" choice opens the quiz, which now has no intro card at all
        self.assertRegex(html, r'<a class="kh-choice kh-choice--primary" href="quiz.html\?start=1" data-hook="cta-kennel-quiz">')
        self.assertNotIn("quiz-intro", JS)

    def test_create_in_the_navigation_goes_to_the_quiz_everywhere(self):
        # # owner ruling 2026-10-20 kennel-first: a member's "Create" place and a visitor's "Find your hound" button both open the quiz
        for name in ("hound.html", "hounds.html", "index.html", "kennel.html", "kennels.html", "landing.html", "learning.html",
                     "postseason.html", "sample.html", "why-we-paused.html"):
            html = (WEB / name).read_text(encoding="utf-8")
            self.assertRegex(html, r'<a class="lh-btn lh-btn--solid lh-btn--lg" href="quiz.html" data-hook="(nav-cta|cta-primary)"', name)
        out = run_page("nav", page_html="hounds.html", **SIGNED, queries=[q("hrefs", ".lh-nav__links a", "attrs", attr="href"), q("tabs", "[data-hook='site-tabbar'] .lh-tab", "attrs", attr="href")])
        self.assertIn("quiz.html", out["final"]["hrefs"])
        self.assertIn("quiz.html", out["final"]["tabs"])
        visitor = run_page("nav", page_html="hounds.html", queries=[q("cta", "[data-hook='nav-cta']", "attr", attr="href"), q("tab", "[data-hook='tab-cta']", "attr", attr="href")])
        self.assertEqual(visitor["final"], {"cta": "quiz.html", "tab": "quiz.html"})
        on_quiz = run_page("nav", page_html="quiz.html", pathname="/web/quiz.html", **SIGNED, queries=[q("current", ".lh-nav__links a[aria-current='page']", "texts")])
        self.assertEqual(on_quiz["final"]["current"], ["Create"])

    def test_the_phone_tab_bar_drops_the_primary_button_on_the_quiz_itself(self):
        # rebuild QA 2026-10-20: the desktop bar hid the button on the quiz, the phone tab bar still drew a second green
        # "Make your first hound" under the quiz's own Next (two primaries on one screen)
        on_quiz = run_page("nav", page_html="quiz.html", pathname="/web/quiz.html",
                           queries=[q("tab", "[data-hook='tab-cta']", "texts"), q("count", "[data-hook='site-tabbar']", "attr", attr="data-count"),
                                    q("tabs", "[data-hook='site-tabbar'] .lh-tab", "attrs", attr="href")])
        self.assertEqual(on_quiz["final"]["tab"], [])
        self.assertEqual(on_quiz["final"]["count"], "3")
        self.assertEqual(len(on_quiz["final"]["tabs"]), 3)
        elsewhere = run_page("nav", page_html="hounds.html", queries=[q("tab", "[data-hook='tab-cta']", "texts")])
        self.assertEqual(elsewhere["final"]["tab"], ["Make your first hound"])

    def test_the_quiz_page_offers_the_builder_once_as_a_quiet_link(self):
        out = quiz(queries=[q("top", hook("quiz-skip-builder"), "attr", attr="href"), q("intro", hook("quiz-intro-builder"), "count")])
        self.assertEqual(out["final"], {"top": "build-a-hound.html", "intro": 0})


if __name__ == "__main__":
    unittest.main()
