"""The hound quiz page (web/quiz.html + web/js/hound-quiz.js + hound-quiz-art.js), run for real under node against the fake DOM of
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
from src.hounds.quiz import compose as C, library as L, moves as M
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


# what the first five questions have set when question 6 opens in COMBO_ACTIONS
BEFORE_Q6 = {"sports": ["MLB"], "markets": ["moneyline", "total"], "personality": "chalk_eater", "bets_per_day": 3, "stake": 1.0,
             "price_comfort": "even", "timing": "late"}
PAGE_IDS = ["windy_overs", "steam_chaser", "tired_legs", "hot_bat_props"]
OTHER_IDS = ["revenge_tour", "road_warriors", "home_cooking", "chalk_eater"]


def moves_page(answers, ids=None, page=0):
    """POST /hounds/quiz/moves's answer: the REAL suggestion for these answers (src/hounds/quiz/moves.py). `ids` picks which of the
    real cards sit on the page, so a test can name the moves it clicks."""
    out = json.loads(json.dumps(M.suggest(answers, page=page)))
    if ids:
        every = {c["id"]: c for p in range(out["pages"]) for c in M.suggest(answers, page=p)["moves"]}
        out["moves"] = [json.loads(json.dumps(every[i])) for i in ids]
        out["recommended"], out["recommended_card"] = ids[0], out["moves"][0]
    return out


def base_routes(answers=None, **over):
    fixture = composed(answers or {})
    r = {"/hounds/quiz/library": [200, LIB], "POST /hounds/quiz/compose": [200, fixture],
         "POST /hounds/quiz/moves": [200, moves_page(BEFORE_Q6, PAGE_IDS)],
         "POST /hounds/builder/preview": [200, preview_answer()]}
    r.update(over)
    return r


def quiz(routes=None, **kw):
    return run_page("quiz", routes=routes or base_routes(), **kw)


def posts_to(out, suffix):
    return [p for p in out["posts"] if p["url"].endswith(suffix)]


def skip_all():
    return [START] + [SKIP] * 8


COMBO_ANSWERS = {"sports": ["MLB"], "markets": ["moneyline", "total"], "personality": "chalk_eater", "bets_per_day": 3, "stake": 1.0,
                 "price_comfort": "even", "timing": "late", "archetypes": ["windy_overs", "steam_chaser"],
                 "quirks": ["full_moon", "lucky_letter"], "letter": "R", "look": {"coat": "golden", "accessory": "cap"}}
COMBO_ACTIONS = [
    START,
    click(card("sports", "MLB")), NEXT,
    click(card("markets", "moneyline")), click(card("markets", "total")), NEXT,
    click(card("personality", "chalk_eater")), NEXT,
    click("[data-hook='quiz-seg'][data-group='bets_per_day'][data-id='3']"),
    click("[data-hook='quiz-seg'][data-group='stake'][data-id='1']"),
    click(card("price_comfort", "even")), NEXT,
    click(card("timing", "late")), NEXT,
    click(card("archetypes", "windy_overs")), click(card("archetypes", "steam_chaser")), NEXT,
    click(card("quirks", "full_moon")), click(card("quirks", "lucky_letter")),
    click("[data-hook='quiz-letter'][data-id='R']"), NEXT,
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

    def test_the_shell_has_progress_stage_bar_and_skip_to_builder(self):
        for h in ("quiz-progress", "quiz-stage", "quiz-back", "quiz-skip", "quiz-next", "quiz-skip-builder", "quiz-reveal"):
            self.assertIn(f'data-hook="{h}"', HTML, h)
        self.assertRegex(HTML, r'<a [^>]*href="build-a-hound.html"[^>]*data-hook="quiz-skip-builder"[^>]*>Skip to builder</a>')
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
        for word in ("Underdog Hunter", "Chalk Eater", "Full moon", "Windy days"):
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
class TheQuestions(unittest.TestCase):

    def test_the_intro_offers_start_and_skip_to_builder(self):
        out = quiz(queries=[q("title", hook("quiz-title")), q("start", hook("quiz-start")), q("builder", hook("quiz-intro-builder"), "attr", attr="href"),
                            q("resume", hook("quiz-resume"), "count"), q("shell_hidden", hook("quiz-shell"), "hidden")])
        f = out["final"]
        self.assertEqual(f["title"], "Build your hound in eight picks.")
        self.assertEqual((f["start"], f["builder"], f["resume"], f["shell_hidden"]), ("Start the quiz", "build-a-hound.html", 0, False))
        self.assertEqual([g for g in out["gets"] if "quiz" in g], ["/hounds/quiz/library"])

    def test_a_library_that_will_not_load_says_so_and_offers_the_builder(self):
        out = run_page("quiz", routes={}, queries=[q("err", hook("quiz-error")), q("retry", hook("quiz-retry"), "count"),
                                                    q("links", "[data-hook='quiz-error'] a", "attrs", attr="href")])
        self.assertIn("The quiz is not loading", out["final"]["err"])
        self.assertEqual(out["final"]["retry"], 1)
        self.assertEqual(out["final"]["links"], ["build-a-hound.html"])

    def test_eight_questions_in_order_each_drawn_from_the_library(self):
        capture = [q("q", hook("quiz-question")), q("step", "[data-hook='quiz-step-body']", "attr", attr="data-step"),
                   q("valuenow", hook("quiz-progress"), "attr", attr="aria-valuenow"), q("cards", "[data-hook='quiz-card']", "count"),
                   q("segs", "[data-hook='quiz-seg']", "count"), q("coats", "[data-hook='quiz-coat']", "count")]
        out = quiz(actions=[dict(START, capture=capture)] + [dict(SKIP, label=f"after{i}", capture=capture) for i in range(7)])
        caps = out["captures"]
        self.assertEqual(caps[START["label"]]["step"], "sports")
        self.assertEqual(caps[START["label"]]["q"], "Where does your hound hunt?")
        self.assertEqual(caps[START["label"]]["cards"], len(LIB["sports"]) + 1)              # every sport, plus Any sport
        steps = [caps[f"after{i}"]["step"] for i in range(7)]
        self.assertEqual(steps, ["markets", "personality", "risk", "timing", "archetypes", "quirks", "look"])
        self.assertEqual([caps[f"after{i}"]["valuenow"] for i in range(7)], ["1", "2", "3", "4", "5", "6", "7"])
        self.assertEqual(caps["after0"]["cards"], 5)
        self.assertEqual(caps["after1"]["cards"], 6)
        self.assertEqual((caps["after2"]["segs"], caps["after2"]["cards"]), (11, 4))
        self.assertEqual(caps["after3"]["cards"], 2)
        self.assertEqual(caps["after4"]["cards"], 4)                                          # four moves at a time, not the library
        self.assertEqual(caps["after5"]["cards"], len(LIB["quirks"]))
        self.assertEqual((caps["after6"]["coats"], caps["after6"]["cards"]), (8, 8))
        self.assertEqual(caps["after0"]["q"], "What does it bet on?")
        self.assertEqual(caps["after4"]["q"], "Pick a move.")

    def test_next_waits_for_a_pick_skip_never_does_and_back_keeps_the_answer(self):
        out = quiz(actions=[
            START,
            dict(do="click", sel=hook("quiz-skip"), label="x", capture=[]),                                   # skip question 1 -> 2
            BACK.copy() | {"label": "b"},
            dict(do="click", sel=card("sports", "MLB"), label="pick", capture=[
                q("pressed", card("sports", "MLB"), "attr", attr="aria-pressed"), q("next_disabled", hook("quiz-next"), "disabled")]),
            dict(do="click", sel=hook("quiz-next"), label="n", capture=[q("step", "[data-hook='quiz-step-body']", "attr", attr="data-step")]),
            dict(do="click", sel=hook("quiz-back"), label="back", capture=[
                q("step", "[data-hook='quiz-step-body']", "attr", attr="data-step"), q("pressed", card("sports", "MLB"), "attr", attr="aria-pressed")]),
        ], captureInitial=[q("x", hook("quiz-start"))])
        caps = out["captures"]
        self.assertEqual(caps["pick"], {"pressed": "true", "next_disabled": False})
        self.assertEqual(caps["n"]["step"], "markets")
        self.assertEqual(caps["back"], {"step": "sports", "pressed": "true"})

    def test_next_is_disabled_until_something_is_picked_and_skip_clears_the_answer(self):
        out = quiz(actions=[
            START,
            dict(do="click", sel=card("sports", "NFL"), label="p", capture=[q("d", hook("quiz-next"), "disabled")]),
            dict(do="click", sel=card("sports", "NFL"), label="unpick", capture=[q("d", hook("quiz-next"), "disabled"), q("pressed", card("sports", "NFL"), "attr", attr="aria-pressed")]),
            dict(do="click", sel=card("sports", "NFL"), label="again"),
            SKIP, BACK.copy() | {"label": "b"},
            dict(do="click", sel=hook("quiz-skip"), label="end", capture=[]),
        ], captureInitial=[q("d", hook("quiz-start"))])
        self.assertEqual(out["captures"]["p"], {"d": False})
        self.assertEqual(out["captures"]["unpick"], {"d": True, "pressed": "false"})
        saved = json.loads(out["storedAfter"].get(DRAFT_KEY, "{}") or "{}")
        self.assertEqual(saved.get("answers", {}).get("sports", []), [])           # skipping cleared it

    def test_markets_mix_is_exclusive_and_props_say_mlb_only(self):
        out = quiz(actions=[START, SKIP,
                            click(card("markets", "moneyline")), click(card("markets", "props")),
                            dict(do="click", sel=card("markets", "mix"), label="mix", capture=[
                                q("mix", card("markets", "mix"), "attr", attr="aria-pressed"), q("ml", card("markets", "moneyline"), "attr", attr="aria-pressed")]),
                            dict(do="click", sel=card("markets", "total"), label="total", capture=[
                                q("mix", card("markets", "mix"), "attr", attr="aria-pressed"), q("total", card("markets", "total"), "attr", attr="aria-pressed")])])
        self.assertEqual(out["captures"]["mix"], {"mix": "true", "ml": "false"})
        self.assertEqual(out["captures"]["total"], {"mix": "false", "total": "true"})
        self.assertIn("MLB only", out["text"])

    def test_the_personality_cards_draw_a_dog_each_with_its_breed(self):
        out = quiz(actions=[START, SKIP, SKIP], queries=[q("dogs", "[data-hook='quiz-card'][data-group='personality'] svg.dk-badge", "attrs", attr="data-breed")])
        self.assertEqual(out["final"]["dogs"], [p["breed"] for p in LIB["personalities"]])

    def test_the_sport_question_is_a_chip_grid_with_every_sport_most_popular_first(self):
        out = quiz(actions=[START], queries=[
            q("chips", "[data-hook='quiz-sports-grid'] [data-hook='quiz-card']", "texts"),
            q("more", hook("quiz-sports-more")), q("more_open", hook("quiz-sports-more"), "attr", attr="aria-expanded"),
            q("extra_hidden", hook("quiz-sports-extra"), "hidden"), q("extra", "[data-hook='quiz-sports-extra'] [data-hook='quiz-card']", "texts"),
            q("all", "[data-hook='quiz-card']", "count"), q("pins", ".qz-pin", "count")])
        f = out["final"]
        self.assertEqual(f["chips"], ["NBA", "NFL", "NHL", "College football", "Soccer", "Tennis", "MLB", "MMA", "Any sport"])
        self.assertEqual(f["more"], f"More ({len(LIB['sports']) - 8})")
        self.assertEqual((f["more_open"], f["extra_hidden"]), ("false", True))
        self.assertEqual(f["pins"], 0)                                                                  # chips, not the old two big cards
        self.assertEqual(sorted(f["chips"][:8] + f["extra"]), sorted(r["label"] for r in LIB["sports"]))
        self.assertEqual(f["all"], len(LIB["sports"]) + 1)

    def test_more_opens_the_rest_and_a_pick_in_it_keeps_it_open(self):
        out = quiz(actions=[START,
                            click(hook("quiz-sports-more"), "open", capture=[q("hidden", hook("quiz-sports-extra"), "hidden"), q("label", hook("quiz-sports-more")),
                                                                          q("expanded", hook("quiz-sports-more"), "attr", attr="aria-expanded")]),
                            click(card("sports", "WNBA"), "wnba", capture=[q("on", card("sports", "WNBA"), "attr", attr="aria-pressed")]),
                            click(hook("quiz-sports-more"), "close", capture=[q("hidden", hook("quiz-sports-extra"), "hidden")])])
        c = out["captures"]
        self.assertEqual(c["open"], {"hidden": False, "label": "Fewer", "expanded": "true"})
        self.assertEqual(c["wnba"]["on"], "true")
        self.assertFalse(c["close"]["hidden"])                      # WNBA is picked, so its row stays showing even after Fewer

    def test_sports_take_many_and_any_sport_is_a_different_answer_from_a_list(self):
        pressed = lambda ident: q(ident, card("sports", ident), "attr", attr="aria-pressed")           # noqa: E731
        caps = [pressed("NBA"), pressed("NHL"), pressed("ANY")]
        out = quiz(actions=[START, click(card("sports", "NBA")), click(card("sports", "NHL"), "two", capture=caps),
                            click(card("sports", "ANY"), "any", capture=caps),
                            click(card("sports", "NBA"), "list_again", capture=caps),
                            click(card("sports", "ANY"), "any2"), click(card("sports", "ANY"), "off", capture=caps)])
        c = out["captures"]
        self.assertEqual(c["two"], {"NBA": "true", "NHL": "true", "ANY": "false"})
        self.assertEqual(c["any"], {"NBA": "false", "NHL": "false", "ANY": "true"})
        self.assertEqual(c["list_again"], {"NBA": "true", "NHL": "false", "ANY": "false"})
        self.assertEqual(c["off"], {"NBA": "false", "NHL": "false", "ANY": "false"})

    def test_the_sports_go_to_compose_as_the_composer_expects_them(self):
        pick = [START, click(card("sports", "TENNIS")), click(card("sports", "NCAAF")), NEXT] + [SKIP] * 7
        out = quiz(routes=base_routes({"sports": ["NCAAF", "TENNIS"]}), actions=pick)
        body = posts_to(out, "/hounds/quiz/compose")[0]["body"]
        self.assertEqual(body, {"answers": {"sports": ["TENNIS", "NCAAF"]}})
        anything = quiz(routes=base_routes({"sports": [user_spec.ANY]}), actions=[START, click(card("sports", "ANY")), NEXT] + [SKIP] * 7)
        self.assertEqual(posts_to(anything, "/hounds/quiz/compose")[0]["body"], {"answers": {"sports": ["ANY"]}})

    def test_a_market_the_picked_sports_do_not_post_is_greyed_out_and_cannot_be_picked(self):
        attr = lambda ident: q(ident, card("markets", ident), "attr", attr="disabled")                  # noqa: E731
        pitch = lambda ident: q(ident + "_pitch", card("markets", ident) + " .qz-pin__pitch")           # noqa: E731
        out = quiz(actions=[START, click(card("sports", "TENNIS")), NEXT,
                            click(card("markets", "total"), "click_total", capture=[q("on", card("markets", "total"), "attr", attr="aria-pressed")])],
                   queries=[attr("moneyline"), attr("spread"), attr("total"), attr("props"), attr("mix"), pitch("total")])
        f = out["final"]
        self.assertIsNone(f["moneyline"])
        self.assertIsNone(f["mix"])
        for ident in ("spread", "total", "props"):
            self.assertIsNotNone(f[ident], ident)
        self.assertEqual(f["total_pitch"], "Not posted for the sports you picked.")
        mlb = quiz(actions=[START, click(card("sports", "MLB")), NEXT], queries=[attr("props"), attr("spread")])
        self.assertEqual((mlb["final"]["props"], mlb["final"]["spread"]), (None, None))
        every = quiz(actions=[START, click(card("sports", "ANY")), NEXT], queries=[attr("props"), attr("total")])
        self.assertEqual((every["final"]["props"], every["final"]["total"]), (None, None))

    def test_changing_the_sports_drops_a_market_they_do_not_post(self):
        out = quiz(actions=[START, click(card("sports", "NBA")), NEXT, click(card("markets", "total")), BACK.copy() | {"label": "b"},
                            click(card("sports", "NBA"), "unpick"), click(card("sports", "TENNIS")), NEXT],
                   queries=[q("total", card("markets", "total"), "attr", attr="aria-pressed")])
        self.assertEqual(out["final"]["total"], "false")


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheMoveQuestion(unittest.TestCase):
    """Question 6: four move cards from POST /hounds/quiz/moves, pick one (a second is optional), Show me 4 others, Pick for me."""

    TO_Q6 = [START, click(card("sports", "MLB")), NEXT, click(card("markets", "moneyline")), click(card("markets", "total")), NEXT,
             click(card("personality", "chalk_eater")), NEXT,
             click("[data-hook='quiz-seg'][data-group='bets_per_day'][data-id='3']"), click("[data-hook='quiz-seg'][data-group='stake'][data-id='1']"),
             click(card("price_comfort", "even")), NEXT, click(card("timing", "late")), NEXT]

    def at_q6(self, routes=None, actions=(), **kw):
        return quiz(routes=routes or base_routes(), actions=self.TO_Q6 + list(actions), **kw)

    def test_it_asks_the_server_with_the_answers_so_far_and_shows_exactly_four_cards(self):
        out = self.at_q6(queries=[
            q("cards", "[data-hook='quiz-archetype-grid'] [data-hook='quiz-card']", "count"),
            q("names", "[data-hook='quiz-archetype-grid'] .qz-pin__title", "texts"), q("shorts", "[data-hook='quiz-archetype-grid'] .qz-pin__pitch", "texts"),
            q("badges", hook("quiz-move-badge"), "texts"), q("reads", hook("quiz-read"), "texts"),
            q("english_hidden", "[data-hook='quiz-english']", "attrs", attr="hidden"), q("title", hook("quiz-question")),
            q("count", hook("quiz-moves-count"))])
        f = out["final"]
        self.assertEqual(posts_to(out, "/hounds/quiz/moves")[0]["body"], {"answers": BEFORE_Q6, "page": 0})
        self.assertEqual(f["cards"], 4)
        page = moves_page(BEFORE_Q6, PAGE_IDS)["moves"]
        self.assertEqual(f["names"], [m["name"] for m in page])
        self.assertEqual(f["shorts"], [m["short"] for m in page])
        for short in f["shorts"]:
            self.assertLessEqual(len(short.split()), 10, short)
        self.assertEqual(len(f["badges"]), 4)
        self.assertTrue(all(b.strip() for b in f["badges"]))
        self.assertEqual(f["reads"], ["How it works"] * 4)
        self.assertEqual(f["english_hidden"], ["", "", "", ""])                      # the full rule is behind "How it works"
        self.assertEqual(f["title"], "Pick a move.")
        self.assertIn("moves fit MLB", f["count"])

    def test_how_it_works_opens_the_full_rule_the_server_wrote(self):
        out = self.at_q6(actions=[click(f"[data-hook='quiz-read'][data-id='{PAGE_IDS[1]}']", "open", capture=[
            q("english", f".qz-cardwrap[data-id='{PAGE_IDS[1]}'] [data-hook='quiz-english']"),
            q("hidden", f".qz-cardwrap[data-id='{PAGE_IDS[1]}'] [data-hook='quiz-english']", "hidden"),
            q("label", f"[data-hook='quiz-read'][data-id='{PAGE_IDS[1]}']")]),
            click(f"[data-hook='quiz-read'][data-id='{PAGE_IDS[1]}']", "close", capture=[
                q("hidden", f".qz-cardwrap[data-id='{PAGE_IDS[1]}'] [data-hook='quiz-english']", "hidden")])])
        c = out["captures"]
        wanted = next(m for m in moves_page(BEFORE_Q6, PAGE_IDS)["moves"] if m["id"] == PAGE_IDS[1])["english"]
        self.assertEqual(c["open"]["english"], wanted)
        self.assertFalse(c["open"]["hidden"])
        self.assertEqual(c["open"]["label"], "Hide the rule")
        self.assertTrue(c["close"]["hidden"])

    def test_pick_one_a_second_is_optional_and_a_third_is_refused(self):
        limit = LIB["limits"]["archetype_picks"]
        self.assertEqual(limit, 2)
        out = self.at_q6(actions=[
            dict(do="click", sel=card("archetypes", PAGE_IDS[0]), label="one", capture=[q("count", hook("quiz-tray-count")), q("next", hook("quiz-next")),
                                                                                  q("disabled", hook("quiz-next"), "disabled")]),
            click(card("archetypes", PAGE_IDS[1]), "two", capture=[q("count", hook("quiz-tray-count")), q("next", hook("quiz-next"))]),
            click(card("archetypes", PAGE_IDS[2]), "three", capture=[q("count", hook("quiz-tray-count")), q("notice", hook("quiz-notice")),
                                                               q("on", card("archetypes", PAGE_IDS[2]), "attr", attr="aria-pressed")]),
            click(f"[data-hook='quiz-tray-chip'][data-id='{PAGE_IDS[0]}']", "remove", capture=[q("count", hook("quiz-tray-count"))])])
        c = out["captures"]
        self.assertEqual(c["one"], {"count": "1 of 2 picked", "next": "Next (1 of 2)", "disabled": False})
        self.assertEqual(c["two"], {"count": "2 of 2 picked", "next": "Next (2 of 2)"})
        self.assertEqual((c["three"]["count"], c["three"]["on"]), ("2 of 2 picked", "false"))
        self.assertIn("2 moves", c["three"]["notice"])
        self.assertEqual(c["remove"]["count"], "1 of 2 picked")

    def test_show_me_4_others_asks_for_the_next_page_and_keeps_what_was_picked(self):
        first = moves_page(BEFORE_Q6, PAGE_IDS)
        second = moves_page(BEFORE_Q6, OTHER_IDS)
        second["page"] = first["next_page"]
        out = self.at_q6(routes=base_routes(), actions=[click(card("archetypes", PAGE_IDS[0]), "pick"),
                                                        click(hook("quiz-moves-more"), "others", capture=[
                                                            q("names", "[data-hook='quiz-archetype-grid'] .qz-pin__title", "texts"),
                                                            q("count", hook("quiz-tray-count")), q("cards", "[data-hook='quiz-archetype-grid'] [data-hook='quiz-card']", "count")])],
                         switchAfter={"/hounds/quiz/moves": [1, [200, second]]})
        bodies = [p["body"] for p in posts_to(out, "/hounds/quiz/moves")]
        self.assertEqual([b["page"] for b in bodies], [0, first["next_page"]])
        self.assertEqual(bodies[1]["answers"], {**BEFORE_Q6, "archetypes": [PAGE_IDS[0]]})
        c = out["captures"]["others"]
        self.assertEqual(c["cards"], 4)
        self.assertEqual(c["names"], [m["name"] for m in second["moves"]])
        self.assertEqual(c["count"], "1 of 2 picked")                           # the pick from the first four is still counted

    def test_pick_for_me_takes_the_servers_top_move_in_place_of_the_picks(self):
        page = moves_page(BEFORE_Q6, PAGE_IDS)
        out = self.at_q6(actions=[click(card("archetypes", PAGE_IDS[2]), "first"),
                          click(hook("quiz-moves-pick"), "pick", capture=[q("count", hook("quiz-tray-count")), q("chips", hook("quiz-tray-chip"), "texts"),
                                                                       q("top", card("archetypes", page["recommended"]), "attr", attr="aria-pressed"),
                                                                       q("old", card("archetypes", PAGE_IDS[2]), "attr", attr="aria-pressed"),
                                                                       q("notice", hook("quiz-notice"))])])
        c = out["captures"]["pick"]
        name = next(a["name"] for a in LIB["archetypes"] if a["id"] == page["recommended"])
        self.assertEqual((c["count"], c["top"], c["old"]), ("1 of 2 picked", "true", "false"))
        self.assertEqual(c["chips"], [f"{name} (remove)"])
        self.assertIn(name, c["notice"])
        self.assertEqual(len(posts_to(out, "/hounds/quiz/moves")), 1)           # the top move came with the page: no second request

    def test_the_filter_chips_are_gone(self):
        out = self.at_q6(queries=[q("filters", hook("quiz-filter"), "count"), q("bar", hook("quiz-filters"), "count")])
        self.assertEqual((out["final"]["filters"], out["final"]["bar"]), (0, 0))
        self.assertNotIn("quiz-filter", JS)
        self.assertNotIn("FILTERS", JS)

    def test_a_move_that_no_longer_runs_is_dropped_from_the_picks(self):
        page = moves_page(BEFORE_Q6, PAGE_IDS)
        page["dropped"] = [PAGE_IDS[0]]
        draft = {"v": 1, "answers": {**{k: None for k in ("personality", "bets_per_day", "stake", "price_comfort", "timing", "letter")},
                                    "sports": ["MLB"], "markets": [], "archetypes": [PAGE_IDS[0]], "quirks": [],
                                    "look": {"coat": None, "accessory": None}},
                 "step": 5, "stage": "quiz", "name": "", "tagline": "", "english": {"text": "", "draft": None}, "pendingSave": False}
        out = quiz(routes=base_routes(**{"POST /hounds/quiz/moves": [200, page]}), stored={DRAFT_KEY: json.dumps(draft)},
                   actions=[click(hook("quiz-resume"), "resume")], queries=[q("count", hook("quiz-tray-count"))])
        self.assertEqual(out["final"]["count"], "0 of 2 picked")

    def test_a_failed_moves_call_says_so_offers_a_retry_and_skip_still_works(self):
        out = self.at_q6(routes=base_routes(**{"POST /hounds/quiz/moves": [500, {"detail": "boom"}]}), queries=[
            q("err", hook("quiz-moves-error")), q("retry", hook("quiz-moves-retry"), "count"), q("cards", hook("quiz-card"), "count"),
            q("skip_disabled", hook("quiz-skip"), "disabled")])
        f = out["final"]
        self.assertIn("skip this question", f["err"].lower())
        self.assertEqual((f["retry"], f["cards"], f["skip_disabled"]), (1, 0, False))
        skipped = self.at_q6(routes=base_routes(**{"POST /hounds/quiz/moves": [500, {}]}), actions=[SKIP], queries=[
            q("step", "[data-hook='quiz-step-body']", "attr", attr="data-step")])
        self.assertEqual(skipped["final"]["step"], "quirks")

    def test_going_back_to_question_6_asks_again_so_the_cards_follow_new_answers(self):
        out = self.at_q6(actions=[click(hook("quiz-skip"), "skip6"), BACK.copy() | {"label": "back7"}])
        self.assertEqual(len(posts_to(out, "/hounds/quiz/moves")), 2)

    def test_no_move_card_text_makes_a_claim(self):
        out = self.at_q6(actions=[click(f"[data-hook='quiz-read'][data-id='{i}']") for i in PAGE_IDS])
        text = out["text"].lower()
        for pattern in CLAIMS:
            self.assertIsNone(re.search(pattern, text), pattern)

    def test_the_composed_hound_carries_the_picked_moves(self):
        out = quiz(routes=base_routes(COMBO_ANSWERS), actions=COMBO_ACTIONS)
        self.assertEqual(posts_to(out, "/hounds/quiz/compose")[0]["body"], {"answers": COMBO_ANSWERS})


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheRestOfTheQuestions(unittest.TestCase):

    def test_the_lucky_letter_row_shows_only_with_the_quirk(self):
        out = quiz(actions=[START] + [SKIP] * 6 + [
            dict(do="click", sel=card("quirks", "lucky_letter"), label="on", capture=[
                q("hidden", hook("quiz-letters"), "hidden"), q("s", "[data-hook='quiz-letter'][data-id='S']", "attr", attr="aria-pressed")]),
            dict(do="click", sel="[data-hook='quiz-letter'][data-id='Q']", label="q", capture=[q("q", "[data-hook='quiz-letter'][data-id='Q']", "attr", attr="aria-pressed")]),
            dict(do="click", sel=card("quirks", "lucky_letter"), label="off", capture=[q("hidden", hook("quiz-letters"), "hidden")])])
        c = out["captures"]
        self.assertEqual(c["on"], {"hidden": False, "s": "true"})
        self.assertEqual(c["q"]["q"], "true")
        self.assertTrue(c["off"]["hidden"])

    def test_the_look_question_previews_the_dog_and_updates_with_a_pick(self):
        out = quiz(actions=[START] + [SKIP] * 7 + [
            dict(do="click", sel=card("accessory", "sunglasses"), label="acc", capture=[q("face", "[data-hook='quiz-look-preview'] svg.dk-badge", "attr", attr="data-face")]),
            dict(do="click", sel="[data-hook='quiz-coat'][data-id='red']", label="coat", capture=[
                q("coat", "[data-hook='quiz-look-preview'] svg.dk-badge", "attr", attr="data-coat"), q("face", "[data-hook='quiz-look-preview'] svg.dk-badge", "attr", attr="data-face")])])
        self.assertEqual(out["captures"]["acc"]["face"], "sunglasses")
        self.assertEqual(out["captures"]["coat"], {"coat": "red", "face": "sunglasses"})

    def test_no_card_text_makes_a_claim_or_names_a_price_at_minus_200(self):
        out = quiz(actions=[START] + [SKIP] * 7)
        text = out["text"].lower()
        for pattern in CLAIMS:
            self.assertIsNone(re.search(pattern, text), pattern)
        for m in re.finditer(r"(?<![\w-])-(\d{3,4})\b", text):
            if int(m.group(1)) >= 200:
                self.assertTrue(text[m.start():].startswith("-200 or worse"), text[m.start() - 20:m.start() + 30])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheReveal(unittest.TestCase):

    def test_skipping_everything_posts_no_answers_and_reveals_the_starter_pup(self):
        fixture = composed({})
        out = quiz(routes=base_routes({}), actions=skip_all(), queries=[
            q("rules", "[data-hook='reveal-rule-text']", "texts"), q("cards", "[data-hook='reveal-rule']", "count"),
            q("name", hook("reveal-name"), "value"), q("chips", hook("reveal-name-chip"), "texts"),
            q("dog_pose", "[data-hook='reveal-dog'] svg.dk-badge", "attr", attr="data-pose"), q("warn", hook("reveal-warning"), "texts"),
            q("globals", hook("reveal-global"), "texts"), q("save_disabled", hook("reveal-save"), "disabled"),
            q("shell_hidden", hook("quiz-shell"), "hidden"), q("reveal_hidden", hook("quiz-reveal"), "hidden"),
            q("honesty", hook("reveal-honesty"))])
        f = out["final"]
        self.assertEqual(posts_to(out, "/hounds/quiz/compose")[0]["body"], {"answers": {}})
        self.assertEqual(f["rules"], [c["body"] for c in fixture["rule_cards"]])
        self.assertEqual(f["globals"], fixture["global_sentences"])
        self.assertEqual(f["name"], fixture["spec"]["name"])
        self.assertEqual(f["chips"], fixture["name_suggestions"])
        self.assertEqual(f["dog_pose"], "celebrate")
        self.assertTrue(any("starter pup" in w for w in f["warn"]))
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
        self.assertEqual(draft["answers"]["archetypes"], ["windy_overs", "steam_chaser"])
        self.assertEqual(draft["stage"], "reveal")

    def test_warnings_from_the_composer_are_shown_as_heads_up(self):
        answers = {"markets": ["moneyline"], "personality": "chalk_eater", "price_comfort": "plus"}
        fixture = composed(answers)
        out = quiz(routes=base_routes(answers), actions=[START, SKIP, click(card("markets", "moneyline")), NEXT, click(card("personality", "chalk_eater")), NEXT,
                                                       click(card("price_comfort", "plus")), NEXT, SKIP, SKIP, SKIP, SKIP],
                   queries=[q("warn", hook("reveal-warning"), "texts"), q("eyebrow", "[data-hook='reveal-warnings'] .qz-eyebrow")])
        self.assertEqual(posts_to(out, "/hounds/quiz/compose")[0]["body"], {"answers": answers})
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

    def test_a_signed_in_return_shows_a_welcome_and_a_signed_out_return_offers_resume(self):
        first = quiz(routes=base_routes(COMBO_ANSWERS), actions=COMBO_ACTIONS + [click(hook("reveal-save"), "save")])
        draft = first["storedAfter"][DRAFT_KEY]
        member = quiz(routes=base_routes(COMBO_ANSWERS), stored={TOKEN_KEY: "tok", DRAFT_KEY: draft},
                      queries=[q("msg", hook("reveal-message")), q("reveal_hidden", hook("quiz-reveal"), "hidden")])
        self.assertIn("You are signed in", member["final"]["msg"])
        self.assertFalse(member["final"]["reveal_hidden"])
        visitor = quiz(routes=base_routes(COMBO_ANSWERS), stored={DRAFT_KEY: draft},
                       queries=[q("resume", hook("quiz-resume")), q("welcome", hook("quiz-welcome")), q("start", hook("quiz-start"))])
        self.assertEqual(visitor["final"]["resume"], "Pick up where I left off")
        self.assertEqual(visitor["final"]["start"], "Start fresh")
        self.assertIn("saved on this device", visitor["final"]["welcome"])

    def test_resume_goes_back_to_the_saved_question_with_the_answers_in_place(self):
        draft = {"v": 1, "answers": {**{k: None for k in ("personality", "bets_per_day", "stake", "price_comfort", "timing", "letter")},
                                    "sports": ["NFL"], "markets": ["spread"], "archetypes": [], "quirks": [],
                                    "look": {"coat": None, "accessory": None}},
                 "step": 2, "stage": "quiz", "name": "", "tagline": "", "english": {"text": "", "draft": None}, "pendingSave": False}
        out = quiz(stored={DRAFT_KEY: json.dumps(draft)}, actions=[
            click(hook("quiz-resume"), "resume", capture=[q("step", "[data-hook='quiz-step-body']", "attr", attr="data-step")]),
            click(hook("quiz-back"), "b1"),
            click(hook("quiz-back"), "b2", capture=[q("nfl", card("sports", "NFL"), "attr", attr="aria-pressed")])])
        self.assertEqual(out["captures"]["resume"]["step"], "personality")
        self.assertEqual(out["captures"]["b2"]["nfl"], "true")

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
        self.assertRegex(html, r'<a class="btn btn--primary btn--lg" href="quiz.html\?start=1" data-hook="cta-kennel-quiz">Find your hound</a>')
        # ?start=1 skips the intro card when nothing is saved; a saved quiz still gets "pick up where I left off"
        self.assertIn('params.get("start")', JS)

    def test_create_in_the_navigation_goes_to_the_quiz_everywhere(self):
        # # owner ruling 2026-10-20 kennel-first: a member's "Create" place and a visitor's "Find your hound" button both open the quiz
        for name in ("hound.html", "hounds.html", "index.html", "kennel.html", "kennels.html", "landing.html", "learning.html",
                     "postseason.html", "sample.html", "why-we-paused.html"):
            html = (WEB / name).read_text(encoding="utf-8")
            self.assertRegex(html, r'<a class="lh-btn lh-btn--solid" href="quiz.html" data-hook="(nav-cta|cta-primary)"', name)
        out = run_page("nav", page_html="hounds.html", **SIGNED, queries=[q("hrefs", ".lh-nav__links a", "attrs", attr="href"), q("tabs", "[data-hook='site-tabbar'] .lh-tab", "attrs", attr="href")])
        self.assertIn("quiz.html", out["final"]["hrefs"])
        self.assertIn("quiz.html", out["final"]["tabs"])
        visitor = run_page("nav", page_html="hounds.html", queries=[q("cta", "[data-hook='nav-cta']", "attr", attr="href"), q("tab", "[data-hook='tab-cta']", "attr", attr="href")])
        self.assertEqual(visitor["final"], {"cta": "quiz.html", "tab": "quiz.html"})
        on_quiz = run_page("nav", page_html="quiz.html", pathname="/web/quiz.html", **SIGNED, queries=[q("current", ".lh-nav__links a[aria-current='page']", "texts")])
        self.assertEqual(on_quiz["final"]["current"], ["Create"])

    def test_the_phone_tab_bar_drops_find_your_hound_on_the_quiz_itself(self):
        # rebuild QA 2026-10-20: the desktop bar hid the button on the quiz, the phone tab bar still drew a second green
        # "Find your hound" under the quiz's own Next (two primaries on one screen)
        on_quiz = run_page("nav", page_html="quiz.html", pathname="/web/quiz.html",
                           queries=[q("tab", "[data-hook='tab-cta']", "texts"), q("count", "[data-hook='site-tabbar']", "attr", attr="data-count"),
                                    q("tabs", "[data-hook='site-tabbar'] .lh-tab", "attrs", attr="href")])
        self.assertEqual(on_quiz["final"]["tab"], [])
        self.assertEqual(on_quiz["final"]["count"], "3")
        self.assertEqual(len(on_quiz["final"]["tabs"]), 3)
        elsewhere = run_page("nav", page_html="hounds.html", queries=[q("tab", "[data-hook='tab-cta']", "texts")])
        self.assertEqual(elsewhere["final"]["tab"], ["Find your hound"])

    def test_the_quiz_page_itself_offers_skip_to_builder_twice(self):
        out = quiz(queries=[q("top", hook("quiz-skip-builder"), "attr", attr="href"), q("intro", hook("quiz-intro-builder"), "attr", attr="href")])
        self.assertEqual(out["final"], {"top": "build-a-hound.html", "intro": "build-a-hound.html"})


if __name__ == "__main__":
    unittest.main()
