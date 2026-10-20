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
    picks = [{"event_id": f"e{i}", "selection": "Boston Red Sox to win", "price": 120, "would_bet": i < cap} for i in range(qualifying)]
    return {"qualifying": qualifying, "would_bet": min(qualifying, cap), "max_bets_per_day": cap, "picks": picks,
            "games_on_board": board, "read_only": True, "paper_only": True, "not_advice": user_spec.NOT_ADVICE}


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
        self.assertEqual(caps[START["label"]]["cards"], 2)
        steps = [caps[f"after{i}"]["step"] for i in range(7)]
        self.assertEqual(steps, ["markets", "personality", "risk", "timing", "archetypes", "quirks", "look"])
        self.assertEqual([caps[f"after{i}"]["valuenow"] for i in range(7)], ["1", "2", "3", "4", "5", "6", "7"])
        self.assertEqual(caps["after0"]["cards"], 5)
        self.assertEqual(caps["after1"]["cards"], 6)
        self.assertEqual((caps["after2"]["segs"], caps["after2"]["cards"]), (11, 4))
        self.assertEqual(caps["after3"]["cards"], 2)
        self.assertEqual(caps["after4"]["cards"], len(LIB["archetypes"]))
        self.assertEqual(caps["after5"]["cards"], len(LIB["quirks"]))
        self.assertEqual((caps["after6"]["coats"], caps["after6"]["cards"]), (8, 8))
        self.assertEqual(caps["after0"]["q"], "What does it bet on?")
        self.assertEqual(caps["after4"]["q"], "Pick up to 3 favorite moves.")

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

    def test_the_card_picker_limits_to_three_filters_and_reads_the_generated_rule(self):
        pick = [START, SKIP, SKIP, SKIP, SKIP, SKIP]
        ids = [a["id"] for a in LIB["archetypes"]]
        out = quiz(actions=pick + [
            click(card("archetypes", ids[0])), click(card("archetypes", ids[1])), click(card("archetypes", ids[2])),
            dict(do="click", sel=card("archetypes", ids[3]), label="fourth", capture=[
                q("count", hook("quiz-tray-count")), q("notice", hook("quiz-notice")), q("fourth", card("archetypes", ids[3]), "attr", attr="aria-pressed"),
                q("next", hook("quiz-next"))]),
            dict(do="click", sel=f"[data-hook='quiz-tray-chip'][data-id='{ids[0]}']", label="remove", capture=[q("count", hook("quiz-tray-count"))]),
            dict(do="click", sel=f"[data-hook='quiz-read'][data-id='{ids[5]}']", label="read", capture=[
                q("english", f".qz-cardwrap[data-id='{ids[5]}'] [data-hook='quiz-english']"), q("hidden", f".qz-cardwrap[data-id='{ids[5]}'] [data-hook='quiz-english']", "hidden")]),
            dict(do="click", sel="[data-hook='quiz-filter'][data-id='nfl']", label="nfl", capture=[q("cards", "[data-hook='quiz-card']", "count")]),
            dict(do="click", sel="[data-hook='quiz-filter'][data-id='props']", label="props", capture=[q("cards", "[data-hook='quiz-card']", "count")]),
        ])
        c = out["captures"]
        self.assertEqual((c["fourth"]["count"], c["fourth"]["fourth"]), ("3 of 3 picked", "false"))
        self.assertIn("3 cards", c["fourth"]["notice"])
        self.assertEqual(c["fourth"]["next"], "Next (3 of 3)")
        self.assertEqual(c["remove"]["count"], "2 of 3 picked")
        self.assertEqual(c["read"]["english"], LIB["archetypes"][5]["english"])
        self.assertFalse(c["read"]["hidden"])
        self.assertEqual(c["nfl"]["cards"], sum(1 for a in LIB["archetypes"] if a["works_in"] == ["NFL"]))
        self.assertEqual(c["props"]["cards"], sum(1 for a in LIB["archetypes"] if "prop" in a["kinds"]))

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

    def test_the_preview_says_how_many_it_would_have_bet_today(self):
        out = quiz(routes=base_routes(preview=None, **{"POST /hounds/builder/preview": [200, preview_answer(qualifying=3, cap=2)]}),
                   actions=skip_all(), queries=[q("count", hook("reveal-preview-count")), q("picks", hook("reveal-pick"), "texts")])
        self.assertEqual(out["final"]["count"], "2 of 3 qualifying picks, with a cap of 2 a day.")
        self.assertEqual(out["final"]["picks"], ["Boston Red Sox to win at +120"] * 2)
        spec = posts_to(out, "/hounds/builder/preview")[0]["body"]["spec"]
        user_spec.validate_spec(spec)
        empty = quiz(routes=base_routes(**{"POST /hounds/builder/preview": [200, preview_answer(qualifying=0)]}), actions=skip_all(),
                     queries=[q("count", hook("reveal-preview-count"))])
        self.assertEqual(empty["final"]["count"], "Nothing on today's board fits these rules.")
        down = quiz(routes=base_routes(**{"POST /hounds/builder/preview": [503, {"detail": {"error": "board_unavailable"}}]}), actions=skip_all(),
                    queries=[q("count", hook("reveal-preview-count"))])
        self.assertEqual(down["final"]["count"], "Today's board is not loaded right now.")

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

    def test_the_kennels_build_a_dog_card_opens_the_quiz(self):
        from tests import test_kennel_page as K
        out = run_page("kennel", routes={"/hounds/kennels/mine": K.mine([K.dog()])}, **SIGNED,
                       actions=[click(hook("kennel-build-card"), "build")], queries=[q("sub", ".kn-build__sub")])
        self.assertEqual(out["navigations"], ["quiz.html"])
        self.assertIn("Take the quiz", out["final"]["sub"])

    def test_the_landing_kennels_card_links_the_quiz(self):
        html = (WEB / "landing.html").read_text(encoding="utf-8")
        self.assertRegex(html, r'<a [^>]*href="quiz.html"[^>]*data-hook="kennels-card-quiz"[^>]*>Take the hound quiz</a>')
        card = html.split('data-hook="kennels-card"')[1].split("</section>")[0]
        self.assertIn('data-hook="kennels-card-quiz"', card)

    def test_the_build_link_in_the_navigation_goes_to_the_quiz_everywhere(self):
        for name in ("hound.html", "hounds.html", "index.html", "kennel.html", "kennels.html", "landing.html", "learning.html",
                     "postseason.html", "sample.html", "why-we-paused.html", "build-a-hound.html", "quiz.html"):
            html = (WEB / name).read_text(encoding="utf-8")
            self.assertRegex(html, r'<a href="quiz.html" data-nav="build"', name)
        out = run_page("nav", page_html="hounds.html", queries=[q("hrefs", ".lh-nav__links a", "attrs", attr="href"), q("tabs", "[data-hook='site-tabbar'] .lh-tab", "attrs", attr="href")])
        self.assertIn("quiz.html", out["final"]["hrefs"])
        self.assertIn("quiz.html", out["final"]["tabs"])
        on_quiz = run_page("nav", page_html="quiz.html", pathname="/web/quiz.html", queries=[q("current", ".lh-nav__links a[aria-current='page']", "texts")])
        self.assertEqual(on_quiz["final"]["current"], ["Build"])

    def test_the_quiz_page_itself_offers_skip_to_builder_twice(self):
        out = quiz(queries=[q("top", hook("quiz-skip-builder"), "attr", attr="href"), q("intro", hook("quiz-intro-builder"), "attr", attr="href")])
        self.assertEqual(out["final"], {"top": "build-a-hound.html", "intro": "build-a-hound.html"})


if __name__ == "__main__":
    unittest.main()
