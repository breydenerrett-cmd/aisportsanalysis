"""The dog builder page (web/build-a-hound.html + web/js/hounds-build.js), run for real under node against the
fake DOM of tests/hounds_web_harness.mjs: its own HTML, its own script, the REAL menu (user_spec.builder_menu)
and the REAL English parser's answers as fixtures. What the page posts is checked against the real request
models and the real validator. Skipped when node is not installed; the static checks need no node.
"""
from __future__ import annotations

import copy
import json
import re
import unittest

from src.hounds import user_spec
from src.hounds.english import parser, render
from tests import _hounds_rules_fixtures as F
from tests.hounds_web_runner import HAS_NODE, WEB, run_page

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # CI's no-FastAPI run
    HAS_FASTAPI = False

HTML = (WEB / "build-a-hound.html").read_text(encoding="utf-8")
JS = (WEB / "js" / "hounds-build.js").read_text(encoding="utf-8")
TOKEN_KEY = "aisportsanalysis.invite_token"
MENU = json.loads(json.dumps(user_spec.builder_menu()))


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


def english_answer(text, **extra):
    """What POST /hounds/english returns for `text`, built by the real parser."""
    parsed = parser.parse(text, players=["aaron judge", "pat slugger"])
    out = {"status": "parsed" if parsed["complete"] else "partial", "text": text, **parsed,
           "unread": [c["text"] for c in parsed["not_understood"] if c.get("text")],
           "paper_only": True, "not_advice": user_spec.NOT_ADVICE}
    out.update(extra)
    return json.loads(json.dumps(out))


def preview_answer(spec_rules=1, qualifying=1, cap=2, **extra):
    picks = [{"event_id": f"e{i}", "sport": "MLB", "market": "moneyline", "away_team": "Boston Red Sox",
              "home_team": "Seattle Mariners", "start_utc": "2026-10-20T23:10:00Z", "lock_utc": "2026-10-20T21:10:00Z",
              "locked": True, "selection": "Boston Red Sox to win", "side": "away", "line": None, "player": None,
              "price": 120, "best_price": 125, "n_books": 5, "rule_index": 0, "would_bet": i < cap, "rank": i + 1}
             for i in range(qualifying)]
    out = {"date": "2026-10-20", "qualifying": qualifying, "would_bet": min(qualifying, cap), "max_bets_per_day": cap,
           "picks": picks, "skipped": {}, "games_considered": 3, "games_on_board": 3, "read_only": True,
           "sentences": ["MLB moneylines: it backs either side."], "paper_only": True,
           "not_advice": user_spec.NOT_ADVICE}
    out.update(extra)
    return out


def dog(hid="u-1", name="Dog One", version_no=1, status="running", **over):
    spec = user_spec.validate_spec(F.v2(name=name, rules=[F.rule(side="away", price_min=100)]))
    out = {"id": hid, "name": name, "tagline": "Bites", "status": status, "version_no": version_no, "color": "mint",
           "badge": "crown", "record": {"bets": 12, "wins": 7, "losses": 5, "pushes": 0}, "spec": spec,
           "rule_sentences": render.rule_sentences(spec) + render.global_sentences(spec)}
    out.update(over)
    return json.loads(json.dumps(out))


def base_routes(**over):
    r = {"/hounds/builder/menu": [200, MENU], "POST /hounds/builder/preview": [200, preview_answer()],
         "/hounds/mine": [200, {"hounds": [], "limit_running": 3}]}
    r.update(over)
    return r


def build(routes=None, **kw):
    return run_page("build", routes=routes or base_routes(), **kw)


def preview_posts(out):
    return [p["body"]["spec"] for p in out["posts"] if p["url"].endswith("/hounds/builder/preview")]


def posts_to(out, suffix):
    return [p for p in out["posts"] if p["url"].endswith(suffix)]


CLICK_BLANK = dict(do="click", sel="[data-hook='blank-rule']", label="blank", wait=60)
SIGNED = dict(stored={TOKEN_KEY: "tok"})


class StaticFacts(unittest.TestCase):
    def test_the_paper_notice_and_the_minus_200_line_are_static_text(self):
        text = re.sub(r"<[^>]+>", " ", re.sub(r"<!--.*?-->", "", HTML, flags=re.S))
        # one short line (2026-10-19 minimalism pass): paper only, the -200 cap, not advice, 21+
        self.assertIn("Paper bets only. Your dog never takes a price of -200 or worse. Not advice. 21+.", " ".join(text.split()))
        self.assertIn("21+", text)
        self.assertIn("Gamble responsibly.", text)

    def test_three_steps_in_order_and_the_side_panels(self):
        order = [HTML.index(h) for h in ('data-hook="step-describe"', 'data-hook="step-rules"', 'data-hook="step-identity"')]
        self.assertEqual(order, sorted(order))
        for hook in ("english-input", "example-chips", "rule-cards", "preview-count", "my-dogs", "build-submit", "diff"):
            self.assertIn(f'data-hook="{hook}"', HTML, hook)
        self.assertIn(">Say it<", HTML)
        self.assertIn(">Check it<", HTML)
        self.assertIn(">Name it<", HTML)
        self.assertIn("Would have bet today", HTML)

    def test_the_advanced_rule_cards_are_collapsed_until_edit_rules_is_opened(self):
        # the sentences stay visible; the cards, "add a rule" and the whole-dog settings sit in a closed <details>
        match = re.search(r'<details[^>]*data-hook="rules-advanced"[^>]*>(.*?)</details>', HTML, re.S)
        self.assertIsNotNone(match)
        self.assertNotRegex(match.group(0).split(">", 1)[0], r"open")
        self.assertIn("<summary>Edit rules</summary>", match.group(0))
        for hook in ("rule-cards", "add-rule", "globals-grid"):
            self.assertIn(f'data-hook="{hook}"', match.group(1), hook)
        sentences = HTML.index('data-hook="rule-sentences"')
        self.assertLess(sentences, match.start())
        self.assertNotIn('data-hook="rule-sentences"', match.group(0))

    def test_the_script_names_no_sport_market_or_condition_outside_its_examples(self):
        code = re.sub(r"export const EXAMPLES = \[.*?\];", "", JS, flags=re.S)
        code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
        code = re.sub(r"(?m)^\s*//.*$", "", code)
        for word in ('"MLB"', '"NFL"', "moneyline", "batter_", "pitcher_", "rest_days", "wind_speed", "wind_direction", "player_streak"):
            self.assertNotIn(word, code, word)

    def test_the_builder_has_its_own_stylesheet_and_no_external_assets(self):
        self.assertIn('href="css/builder.css"', HTML)
        self.assertTrue((WEB / "css" / "builder.css").is_file())
        self.assertNotRegex(HTML, r"<img\b")
        self.assertNotRegex(HTML, r'(src|href)="https?://')


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheMenuDrivesThePage(unittest.TestCase):
    def test_every_choice_comes_from_the_menu(self):
        out = build(actions=[CLICK_BLANK], queries=[
            q("sports", "[data-hook='rule-sports'] button", "texts"), q("markets", "[data-hook='rule-markets'] button", "texts"),
            q("sides", "[data-hook='rule-side'] option", "texts"), q("lock", "[data-hook='g-lock'] option", "texts"),
            q("stake", "[data-hook='g-stake'] option", "texts"), q("rank", "[data-hook='g-rank'] option", "texts"),
            q("colors", "[data-hook='color-picker'] button", "count"), q("badges", "[data-hook='badge-picker'] button", "count"),
            q("pmin", "[data-hook='price-min']", "attr", attr="min"), q("pmax", "[data-hook='price-max']", "attr", attr="max"),
            q("books", "[data-hook='min-books']", "attr", attr="max"), q("bets", "[data-hook='g-bets']", "attr", attr="max"),
            q("name_max", "[data-hook='f-name']", "attr", attr="maxlength"),
            q("tag_max", "[data-hook='f-tagline']", "attr", attr="maxlength")])
        f = out["final"]
        # the page always puts "Any sport" first, wherever the menu lists it
        anys = [s["label"] for s in MENU["sports"] if s["value"] == "ANY"]
        self.assertEqual(f["sports"], anys + [s["label"] for s in MENU["sports"] if s["value"] != "ANY"])
        self.assertEqual(f["markets"], [m["label"] for m in MENU["markets"]])
        self.assertEqual(f["sides"], [s["label"] for s in MENU["sides"] if s["value"] in MENU["side_by_kind"]["ml_spread"]])
        self.assertEqual(f["lock"], [f"{v} minutes" for v in MENU["lock_minutes"]["choices"]])
        self.assertEqual(f["stake"], [f"{v:g} unit{'' if v == 1 else 's'}" for v in MENU["stake_units"]["choices"]])
        self.assertEqual(f["rank"], [r["label"] for r in MENU["rank_by"]])
        self.assertEqual((f["colors"], f["badges"]), (len(MENU["colors"]), len(MENU["badges"])))
        self.assertEqual((f["pmin"], f["pmax"]), (str(MENU["price"]["lowest"]), str(MENU["price"]["highest"])))
        self.assertEqual((f["books"], f["bets"]), (str(MENU["min_books"]["max"]), str(MENU["max_bets_per_day"]["max"])))
        self.assertEqual((f["name_max"], f["tag_max"]), (str(MENU["name"]["max"]), str(MENU["tagline"]["max"])))

    def test_nothing_is_hard_coded_an_invented_menu_builds_an_invented_builder(self):
        odd = copy.deepcopy(MENU)
        odd["sports"] = [{"value": "curling", "label": "Curling"}]
        odd["markets"] = [{"value": "outright", "label": "Outright", "kind": "ml_spread", "sports": ["curling"]}]
        odd["sides"] = [{"value": "either", "label": "Whoever"}, {"value": "home", "label": "The hammer"}]
        odd["side_by_kind"] = {"ml_spread": ["either", "home"], "total": ["either"], "prop": ["either"]}
        odd["conditions"] = [{"id": "zebra", "label": "Zebra stripes", "group": "Odd", "kinds": ["ml_spread"], "sports": ["curling"],
                              "only_markets": [], "fun": True, "available": True, "unavailable_reason": None,
                              "params": [{"name": "n", "kind": "int", "label": "How many", "min": 1, "max": 9, "step": 1, "default": 3}]}]
        odd["colors"] = [{"value": "teal", "label": "Teal", "hex": "#008080"}]
        odd["badges"] = [{"value": "kite", "label": "Kite"}]
        out = build(base_routes(**{"/hounds/builder/menu": [200, odd]}),
                    actions=[CLICK_BLANK, dict(do="set", sel="[data-hook='add-condition']", value="zebra", label="add", wait=450)],
                    queries=[q("sports", "[data-hook='rule-sports'] button", "texts"), q("markets", "[data-hook='rule-markets'] button", "texts"),
                             q("sides", "[data-hook='rule-side'] option", "texts"), q("conds", "[data-hook='add-condition'] option", "texts"),
                             q("param", "[data-hook='condition'] [data-param='n']", "attr", attr="max"),
                             q("cond_name", "[data-hook='condition'] .bd-cond__name"), q("colors", "[data-hook='color-picker'] button", "count")])
        f = out["final"]
        self.assertEqual((f["sports"], f["markets"], f["sides"]), (["Curling"], ["Outright"], ["Whoever", "The hammer"]))
        self.assertEqual(f["conds"], ["Add a condition...", "Zebra stripes"])
        self.assertEqual((f["param"], f["cond_name"], f["colors"]), ("9", "Zebra stripes", 1))
        self.assertEqual(preview_posts(out)[-1]["rules"][0]["sports"], ["curling"])

    def test_a_missing_menu_says_so_in_words_and_offers_no_builder(self):
        out = build({"/hounds/builder/menu": [404, {"detail": "Not Found"}]}, queries=[
            q("state", "[data-hook='rules-empty']"), q("go", "[data-hook='english-go']", "disabled"), q("cards", "[data-hook='rule-card']", "count")])
        self.assertIn("not switched on", out["final"]["state"])
        self.assertTrue(out["final"]["go"])
        self.assertEqual(out["final"]["cards"], 0)

    def test_a_condition_the_menu_marks_unavailable_is_shown_disabled_with_no_way_to_add_it(self):
        out = build(actions=[CLICK_BLANK], queries=[q("opts", "[data-hook='add-condition'] option", "texts"),
                                                      q("dis", "[data-hook='add-condition'] option", "attrs", attr="disabled")])
        wind = [i for i, t in enumerate(out["final"]["opts"]) if t.startswith("Wind blowing out")]
        available = next(c["available"] for c in MENU["conditions"] if c["id"] == "wind_direction")
        if not available:
            self.assertEqual(len(wind), 1)
            self.assertEqual(out["final"]["opts"][wind[0]], "Wind blowing out or in (not available yet)")
            self.assertEqual(out["final"]["dis"][wind[0]], "")           # present as a disabled option
        else:
            self.assertEqual(out["final"]["opts"][wind[0]], "Wind blowing out or in")


@unittest.skipUnless(HAS_NODE, "node not installed")
class StepOneEnglish(unittest.TestCase):
    TEXT = "Bet home underdogs between +120 and +200 when they're on 2+ days rest. Max 2 bets a day."

    def read(self, text=None, answer=None, extra_routes=None, **kw):
        text = text or self.TEXT
        answer = answer or english_answer(text)
        routes = base_routes(**{"POST /hounds/english": [200, answer],
                                "POST /hounds/builder/preview": [200, preview_answer(sentences=answer.get("sentences", []))]})
        routes.update(extra_routes or {})
        actions = [dict(do="set", sel="[data-hook='english-input']", value=text),
                   dict(do="click", sel="[data-hook='english-go']", label="read", wait=400)]
        return build(routes, actions=actions + kw.pop("more", []), **kw)

    def test_reading_posts_the_text_and_shows_how_each_phrase_was_read(self):
        out = self.read(queries=[q("understood", "[data-hook='english-understood'] li", "texts"),
                                 q("assumed", "[data-hook='english-assumed']"), q("cards", "[data-hook='rule-card']", "count"),
                                 q("sentences", "[data-hook='rule-sentences']"), q("unread_hidden", "[data-hook='english-unread']", "hidden")])
        self.assertEqual(posts_to(out, "/hounds/english")[0]["body"], {"text": self.TEXT})
        f = out["final"]
        self.assertTrue(any('"on 2+ days rest" is read as' in u for u in f["understood"]), f["understood"])
        self.assertTrue(any("home" in u for u in f["understood"]))
        self.assertIn("Assumed", f["assumed"])
        self.assertIn("moneyline", f["assumed"])
        self.assertEqual(f["cards"], 1)
        self.assertIn("backs the home side", f["sentences"])
        self.assertTrue(f["unread_hidden"])

    def test_an_example_chip_reads_its_own_text(self):
        out = build(base_routes(**{"POST /hounds/english": [200, english_answer("Fade teams after 3 straight wins")]}),
                    actions=[dict(do="click", sel="[data-hook='example-chip']", index=1, label="chip", wait=300)],
                    queries=[q("input", "[data-hook='english-input']", "value"), q("chips", "[data-hook='example-chip']", "count")])
        self.assertEqual(out["final"]["input"], "Fade teams after 3 straight wins")
        self.assertGreaterEqual(out["final"]["chips"], 5)
        self.assertEqual(posts_to(out, "/hounds/english")[0]["body"]["text"], "Fade teams after 3 straight wins")

    def test_every_example_is_one_the_real_parser_reads_in_full_or_says_why_not(self):
        # the page's own list, read from its module source
        examples = re.findall(r'^\s+"([^"]+)",?$', re.search(r"export const EXAMPLES = \[(.*?)\];", JS, re.S).group(1), re.M)
        self.assertGreaterEqual(len(examples), 5)
        with F.patch_players():
            for text in examples:
                res = parser.parse(text, players=["aaron judge"])
                self.assertTrue(res["spec"], text)
                self.assertEqual(res["not_understood"], [], text)

    def test_what_could_not_be_read_is_shown_with_its_reason_and_the_translator_state(self):
        text = "home underdogs with a sharks theme"
        for translation, expect in (({"status": "unavailable"}, "finish it by hand"),
                                    ({"status": "sign_in_required"}, "Sign in"),
                                    ({"status": "translating", "job_id": "j-1"}, "second reader")):
            answer = english_answer(text, translation=translation, message="I could not read \"sharks theme\". The rule cards below let you finish it by hand."
                                    if translation["status"] == "unavailable" else "Sign in and I can have the translator take a second look.")
            if translation["status"] == "translating":
                answer.update(job_id="j-1", status="translating")
            out = self.read(text, answer, queries=[q("unread", "[data-hook='english-notread'] li", "texts"),
                                                   q("line", "[data-hook='english-translator']"),
                                                   q("cards", "[data-hook='rule-card']", "count")])
            self.assertTrue(any("sharks" in u and "was not understood" in u for u in out["final"]["unread"]), out["final"]["unread"])
            self.assertIn(expect, out["final"]["line"])
            self.assertEqual(out["final"]["cards"], 1)             # the part that WAS read is already editable

    def test_wind_direction_is_reported_with_the_servers_reason_not_papered_over(self):
        reason = "wind direction needs each ballpark's verified compass bearing, which is not on file yet"
        answer = english_answer("overs in games with wind blowing out")
        answer["not_understood"] = [{"text": "wind blowing out", "reason": reason}]
        out = self.read("overs in games with wind blowing out", answer, queries=[q("unread", "[data-hook='english-notread']")])
        self.assertIn("verified compass bearing", out["final"]["unread"])

    def test_a_translation_in_flight_is_polled_and_offered_as_a_replacement_the_person_must_accept(self):
        text = "home underdogs with a sharks theme"
        answer = english_answer(text, translation={"status": "translating", "job_id": "j-1"}, job_id="j-1", status="translating")
        spec = user_spec.validate_spec(F.v2(name="Draft Dog", rules=[F.rule(side="home", price_min=150, price_max=300)]))
        spec["name"] = ""
        job = {"job_id": "j-1", "status": "done", "spec": spec, "sentences": ["The translator's sentence."], "reasons": {},
               "paper_only": True}
        routes = base_routes(**{"POST /hounds/english": [200, answer], "/hounds/english/j-1": [200, job]})
        out = build(routes, **SIGNED, actions=[
            dict(do="set", sel="[data-hook='english-input']", value=text), dict(do="click", sel="[data-hook='english-go']", wait=300),
            dict(do="fire_timers", label="poll", wait=200,
                 capture=[q("line", "[data-hook='english-translator']"), q("use", "[data-hook='use-translation']", "exists"),
                          q("pmin", "[data-hook='price-min']", "value")]),
            dict(do="click", sel="[data-hook='use-translation']", label="use", wait=300)],
            queries=[q("pmin", "[data-hook='price-min']", "value"), q("line", "[data-hook='english-translator']")])
        self.assertIn("/hounds/english/j-1", " ".join(out["gets"]))
        poll = out["captures"]["poll"]
        self.assertTrue(poll["use"])
        self.assertNotEqual(poll["pmin"], "150")                  # the draft is NOT replaced until the person says so
        self.assertEqual(out["final"]["pmin"], "150")
        self.assertIn("Check every card", out["final"]["line"])
        self.assertEqual(out["intervals"], [])                    # polling stopped

    def test_a_refused_or_failed_translation_says_why_and_leaves_the_draft_alone(self):
        text = "home underdogs with a sharks theme"
        answer = english_answer(text, translation={"status": "translating", "job_id": "j-1"}, job_id="j-1", status="translating")
        job = {"job_id": "j-1", "status": "refused", "reasons": {"rules[0].price_min": "cannot be -200 or worse"}, "paper_only": True}
        out = build(base_routes(**{"POST /hounds/english": [200, answer], "/hounds/english/j-1": [200, job]}), **SIGNED, actions=[
            dict(do="set", sel="[data-hook='english-input']", value=text), dict(do="click", sel="[data-hook='english-go']", wait=300),
            dict(do="fire_timers", wait=200)], queries=[q("line", "[data-hook='english-translator']"), q("use", "[data-hook='use-translation']", "exists")])
        self.assertIn("cannot be -200 or worse", out["final"]["line"])
        self.assertFalse(out["final"]["use"])

    def test_an_empty_box_and_a_server_failure_are_said_in_words(self):
        out = build(actions=[dict(do="click", sel="[data-hook='english-go']", wait=100, capture=[q("s", "[data-hook='english-status']")])])
        self.assertIn("Type a strategy first", out["captures"]["0"]["s"])
        out = build(actions=[dict(do="set", sel="[data-hook='english-input']", value="home dogs"),
                             dict(do="click", sel="[data-hook='english-go']", wait=200)], queries=[q("s", "[data-hook='english-status']")])
        self.assertTrue(out["final"]["s"])                          # no english route: the 404 is described, not swallowed


@unittest.skipUnless(HAS_NODE, "node not installed")
class StepTwoCards(unittest.TestCase):
    def test_a_blank_rule_has_defaults_from_the_menu_and_posts_a_valid_spec_for_preview(self):
        out = build(actions=[CLICK_BLANK, dict(do="fire_timers", wait=400)], queries=[
            q("cards", "[data-hook='rule-card']", "count"), q("pmin", "[data-hook='price-min']", "value"),
            q("books", "[data-hook='min-books']", "value"), q("limit", "[data-hook='rule-limit']")])
        self.assertEqual(out["final"]["cards"], 1)
        self.assertEqual((out["final"]["pmin"], out["final"]["books"]), (str(MENU["price"]["lowest"]), str(MENU["min_books"]["default_game"])))
        specs = preview_posts(out)
        self.assertTrue(specs)
        spec = user_spec.validate_spec(specs[-1])             # the real validator takes exactly what the page sent
        self.assertEqual(spec["rules"][0]["markets"], ["moneyline"])
        self.assertEqual(specs[-1]["name"], "Draft Dog")      # a draft is previewed under a placeholder name

    def test_editing_a_price_a_market_and_a_condition_changes_the_posted_rule(self):
        out = build(actions=[
            CLICK_BLANK,
            dict(do="set", sel="[data-hook='price-min']", value="100"),
            dict(do="click", sel="[data-hook='rule-markets'] button", index=1, label="spread", wait=40),   # + spread
            dict(do="set", sel="[data-hook='rule-side']", value="home", wait=40),
            dict(do="set", sel="[data-hook='add-condition']", value="rest_days", wait=60),
            dict(do="set", sel="[data-hook='condition'] [data-param='value']", value="3", wait=40),
            dict(do="set", sel="[data-hook='add-condition']", value="role", wait=60),
            dict(do="set", sel="[data-hook='condition'] [data-param='who']", value="opponent", index=0, wait=40),
            dict(do="fire_timers", wait=450)])
        spec = preview_posts(out)[-1]
        rule = spec["rules"][0]
        self.assertEqual((rule["price_min"], rule["markets"], rule["side"]), (100, ["moneyline", "spread"], "home"))
        ids = [c["id"] for c in rule["when"]["items"]]
        self.assertEqual(ids, ["rest_days", "role"])
        rest = rule["when"]["items"][0]
        self.assertEqual((rest["value"], rest["who"], rest["cmp"]), (3, "opponent", "gte"))
        user_spec.validate_spec(spec)

    def test_groups_and_or_nest_and_conditions_and_groups_can_be_removed(self):
        out = build(actions=[
            CLICK_BLANK,
            dict(do="set", sel="[data-hook='add-condition']", value="role", wait=60),
            dict(do="click", sel="[data-hook='add-group']", wait=60),
            dict(do="set", sel="[data-hook='cond-group'] [data-hook='cond-group'] [data-hook='add-condition']", value="steam", wait=60),
            dict(do="set", sel="[data-hook='cond-group'] [data-hook='cond-group'] [data-hook='group-op']", value="any", wait=40),
            dict(do="fire_timers", wait=450, label="nested", capture=[q("groups", "[data-hook='cond-group']", "count"),
                                                                       q("conds", "[data-hook='condition']", "count")]),
            dict(do="click", sel="[data-hook='remove-group']", wait=60),
            dict(do="click", sel="[data-hook='remove-condition']", wait=60),
            dict(do="fire_timers", wait=450)],
            queries=[q("groups", "[data-hook='cond-group']", "count"), q("conds", "[data-hook='condition']", "count")])
        self.assertEqual(out["captures"]["nested"], {"groups": 2, "conds": 2})
        nested = [s for s in preview_posts(out) if s["rules"][0].get("when") and
                  any("items" in i for i in s["rules"][0]["when"]["items"])]
        self.assertTrue(nested)
        group = [i for i in nested[-1]["rules"][0]["when"]["items"] if "items" in i][0]
        self.assertEqual((group["op"], group["items"][0]["id"]), ("any", "steam"))
        user_spec.validate_spec(nested[-1])
        self.assertEqual(out["final"], {"groups": 1, "conds": 0})
        self.assertIsNone(preview_posts(out)[-1]["rules"][0]["when"])      # an empty tree is not sent at all

    def test_a_second_rule_can_be_added_removed_and_the_limit_is_shown(self):
        out = build(actions=[CLICK_BLANK, dict(do="click", sel="[data-hook='add-rule']", wait=60)],
                    queries=[q("cards", "[data-hook='rule-card']", "count"), q("limit", "[data-hook='rule-limit']"),
                             q("removes", "[data-hook='remove-rule']", "count")])
        self.assertEqual((out["final"]["cards"], out["final"]["removes"]), (2, 2))
        self.assertEqual(out["final"]["limit"], f"2 of {MENU['limits']['max_rules']} rules")
        many = build(actions=[CLICK_BLANK] + [dict(do="click", sel="[data-hook='add-rule']", wait=40)] * 6,
                     queries=[q("cards", "[data-hook='rule-card']", "count"), q("add", "[data-hook='add-rule']", "disabled")])
        self.assertEqual(many["final"]["cards"], MENU["limits"]["max_rules"])
        self.assertTrue(many["final"]["add"])
        gone = build(actions=[CLICK_BLANK, dict(do="click", sel="[data-hook='add-rule']", wait=40),
                              dict(do="click", sel="[data-hook='remove-rule']", index=0, wait=40)],
                     queries=[q("cards", "[data-hook='rule-card']", "count")])
        self.assertEqual(gone["final"]["cards"], 1)

    def test_picking_another_kind_of_bet_switches_the_rule_and_drops_conditions_that_no_longer_fit(self):
        out = build(actions=[
            CLICK_BLANK, dict(do="set", sel="[data-hook='add-condition']", value="role", wait=60),
            dict(do="click", sel="[data-market='total']", wait=60),
            dict(do="fire_timers", wait=450)],
            queries=[q("conds", "[data-hook='condition']", "count"), q("sides", "[data-hook='rule-side'] option", "texts"),
                     q("pressed", "[data-market='total']", "attr", attr="aria-pressed")])
        self.assertEqual(out["final"]["conds"], 0)                                  # "favourite or underdog" does not fit a total
        self.assertIn("The over", out["final"]["sides"])
        self.assertEqual(out["final"]["pressed"], "true")
        rule = preview_posts(out)[-1]["rules"][0]
        self.assertEqual((rule["markets"], rule["side"]), (["total"], "either"))

    def test_props_are_offered_for_the_sports_the_menu_names_and_switch_the_rule_to_mlb(self):
        out = build(actions=[CLICK_BLANK, dict(do="click", sel="[data-sport='NFL']", wait=40),
                             dict(do="click", sel="[data-market='batter_total_bases']", wait=60)],
                    queries=[q("nfl", "[data-sport='NFL']", "disabled"), q("books", "[data-hook='min-books']", "value"),
                             q("props", "[data-hook='condition']", "count")])
        self.assertTrue(out["final"]["nfl"])                                      # no NFL prop prices: the chip is off
        self.assertEqual(out["final"]["books"], str(MENU["min_books"]["default_prop"]))
        out2 = build(actions=[CLICK_BLANK, dict(do="click", sel="[data-market='batter_total_bases']", wait=60),
                              dict(do="fire_timers", wait=450)])
        self.assertEqual(preview_posts(out2)[-1]["rules"][0]["sports"], ["MLB"])

    def test_the_server_refusing_the_rules_is_listed_with_its_reasons_and_the_count_says_to_fix_them(self):
        refusal = [422, {"detail": {"error": "spec_invalid", "fields": {"rules[0].price_min": "cannot be -200 or worse; this program never selects a price that short"}}}]
        out = build(base_routes(**{"POST /hounds/builder/preview": refusal}), actions=[CLICK_BLANK, dict(do="fire_timers", wait=450)],
                    queries=[q("problems", "[data-hook='build-problems']"), q("hidden", "[data-hook='build-problems']", "hidden"),
                             q("count", "[data-hook='preview-count']")])
        self.assertFalse(out["final"]["hidden"])
        self.assertIn("Rule 1, price min: cannot be -200 or worse", out["final"]["problems"])
        self.assertIn("Fix the rules", out["final"]["count"])

    def test_the_live_preview_counts_names_the_picks_and_marks_those_over_the_cap(self):
        out = build(base_routes(**{"POST /hounds/builder/preview": [200, preview_answer(qualifying=3, cap=2)]}),
                    actions=[CLICK_BLANK, dict(do="fire_timers", wait=450)],
                    queries=[q("count", "[data-hook='preview-count']"), q("picks", "[data-hook='preview-pick']", "texts"),
                             q("pill", "[data-hook='preview-pill']"), q("over", "[data-hook='preview-pick']", "attrs", attr="class")])
        f = out["final"]
        self.assertEqual(f["count"], "2 bets today: 3 qualify and your cap is 2.")
        self.assertEqual(f["pill"], f["count"])
        self.assertEqual(len(f["picks"]), 3)
        self.assertIn("over your daily cap", f["picks"][2])
        self.assertIn("+120", f["picks"][0])
        self.assertIn("bd-pick--over", f["over"][2])
        for empty, text in ((preview_answer(qualifying=0), "0 bets today"), (preview_answer(qualifying=0, games_on_board=0), "No games on today's board")):
            o = build(base_routes(**{"POST /hounds/builder/preview": [200, empty]}), actions=[CLICK_BLANK, dict(do="fire_timers", wait=450)],
                      queries=[q("count", "[data-hook='preview-count']")])
            self.assertIn(text, o["final"]["count"])

    def test_the_preview_never_posts_to_a_route_that_writes(self):
        out = build(actions=[CLICK_BLANK, dict(do="set", sel="[data-hook='price-min']", value="100"), dict(do="fire_timers", wait=450)])
        self.assertEqual({p["url"] for p in out["posts"]}, {"/hounds/builder/preview"})

    def test_a_rapid_run_of_edits_sends_one_preview_for_the_last_state(self):
        edits = [dict(do="set", sel="[data-hook='price-min']", value=str(100 + i), wait=5) for i in range(6)]
        out = build(actions=[CLICK_BLANK, dict(do="fire_timers", wait=450)] + edits + [dict(do="fire_timers", wait=450)])
        self.assertEqual(preview_posts(out)[-1]["rules"][0]["price_min"], 105)
        self.assertLessEqual(len(preview_posts(out)), 4)


@unittest.skipUnless(HAS_NODE, "node not installed")
class StepThreeAndSaving(unittest.TestCase):
    NAME = [dict(do="set", sel="[data-hook='f-name']", value="  Pup Test  "), dict(do="set", sel="[data-hook='f-tagline']", value="Fetches")]

    def test_the_dog_card_and_the_pickers_follow_what_is_typed_and_chosen(self):
        out = build(actions=[CLICK_BLANK] + self.NAME + [
            dict(do="click", sel="[data-color='gold']", wait=40), dict(do="click", sel="[data-badge='crown']", wait=40)],
            queries=[q("name", "[data-hook='dog-name']"), q("tag", "[data-hook='dog-tagline']"),
                     q("count", "[data-hook='name-count']"), q("tcount", "[data-hook='tagline-count']"),
                     q("gold", "[data-color='gold']", "attr", attr="aria-checked"), q("crown", "[data-badge='crown']", "attr", attr="aria-checked"),
                     q("card_badge", "[data-hook='dog-badge']", "attr", attr="data-badge"),
                     q("card_style", "[data-hook='build-dog-card'] .bd-dog", "attr", attr="style")])
        f = out["final"]
        self.assertEqual((f["name"], f["tag"]), ("Pup Test", "Fetches"))
        self.assertEqual((f["count"], f["tcount"]), ("12 / 24", "7 / 80"))
        self.assertEqual((f["gold"], f["crown"], f["card_badge"]), ("true", "true", "crown"))
        self.assertIn("#F2B84B", f["card_style"])

    def test_signed_out_a_draft_can_be_built_but_saving_asks_for_a_sign_in_and_posts_nothing(self):
        out = build(actions=[CLICK_BLANK] + self.NAME + [dict(do="click", sel="[data-hook='build-submit']", wait=100)],
                    queries=[q("gate", "[data-hook='build-gate']"), q("hidden", "[data-hook='build-gate']", "hidden"),
                             q("limit", "[data-hook='limit-text']"), q("mine", "[data-hook='my-dogs-state']"),
                             q("btn", "[data-hook='build-submit']")])
        self.assertFalse(out["final"]["hidden"])
        self.assertIn("Sign in to save your dog", out["final"]["gate"])
        self.assertEqual(posts_to(out, "/hounds"), [])
        self.assertIn("Sign in to see the dogs", out["final"]["mine"])
        self.assertEqual(out["final"]["btn"], "Send my dog in")
        self.assertNotIn("/hounds/mine", out["gets"])         # no token, no account read

    @unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
    def test_signed_in_the_post_is_what_the_real_create_route_accepts(self):
        from api.hounds_create import CreateHoundRequest
        text = "bet home underdogs between +120 and +200 when they're on 2+ days rest. max 2 bets a day"
        routes = base_routes(**{"POST /hounds/english": [200, english_answer(text)], "POST /hounds": [200, {"hound": {"id": "u-x", "name": "Pup Test"}}]})
        out = build(routes, **SIGNED, actions=[
            dict(do="set", sel="[data-hook='english-input']", value=text), dict(do="click", sel="[data-hook='english-go']", wait=300)]
            + self.NAME + [dict(do="click", sel="[data-color='mint']", wait=30), dict(do="click", sel="[data-badge='bolt']", wait=30),
                           dict(do="click", sel="[data-hook='build-submit']", wait=200)],
            queries=[q("msg", "[data-hook='build-message']"), q("link", "[data-hook='new-dog-link']", "attr", attr="href")])
        posted = posts_to(out, "/hounds")
        self.assertEqual(len(posted), 1)
        model = CreateHoundRequest(**posted[0]["body"])
        spec = user_spec.validate_spec(model.spec)                # and the menu's own validation takes it as it stands
        self.assertEqual((spec["name"], spec["tagline"], spec["color"], spec["badge"]), ("Pup Test", "Fetches", "mint", "bolt"))
        rule = spec["rules"][0]
        self.assertEqual((rule["side"], rule["price_min"], rule["price_max"], spec["max_bets_per_day"]), ("home", 120, 200, 2))
        self.assertNotIn("sports", posted[0]["body"]["spec"])      # derived fields are not sent; the server derives them
        self.assertIn("is in the kennel", out["final"]["msg"])
        self.assertEqual(out["final"]["link"], "hound.html?id=u-x")

    def test_a_missing_name_is_asked_for_before_anything_is_posted(self):
        out = build(**SIGNED, actions=[CLICK_BLANK, dict(do="click", sel="[data-hook='build-submit']", wait=100)],
                    queries=[q("p", "[data-hook='build-problems']")])
        self.assertIn("give your dog a name", out["final"]["p"].lower())
        self.assertEqual(posts_to(out, "/hounds"), [])

    def test_server_refusals_are_said_in_words(self):
        def run(status, payload):
            return build(base_routes(**{"POST /hounds": [status, payload]}), **SIGNED,
                         actions=[CLICK_BLANK] + self.NAME + [dict(do="click", sel="[data-hook='build-submit']", wait=200)],
                         queries=[q("err", "[data-hook='build-server-error']"), q("problems", "[data-hook='build-problems']"),
                                  q("gate", "[data-hook='build-gate']", "hidden")])
        out = run(422, {"detail": {"error": "spec_invalid", "fields": {"name": "is already taken"}}})
        self.assertIn("name: is already taken", out["final"]["problems"])
        out = run(409, {"detail": {"error": "limit", "message": "an account can run at most 3 hounds; retire one first"}})
        self.assertIn("at most 3 hounds", out["final"]["err"])
        out = run(401, {"detail": "no"})
        self.assertFalse(out["final"]["gate"])
        out = run(500, {})
        self.assertTrue(out["final"]["err"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class MyDogsAndEditing(unittest.TestCase):
    def routes(self, **over):
        mine = {"hounds": [dog("u-1", "Dog One"), dog("u-2", "Dog Two", version_no=3), dog("u-0", "Old Dog", status="retired")], "limit_running": 3}
        merged = {"/hounds/mine": [200, mine]}
        merged.update(over)
        return base_routes(**merged)

    def test_my_dogs_lists_running_dogs_with_their_rules_and_hides_retired_ones(self):
        out = build(self.routes(), **SIGNED, queries=[
            q("names", "[data-hook='my-dog'] .bd-dogrow__name a", "texts"), q("rules", "[data-hook='my-dog'] summary", "count"),
            q("limit", "[data-hook='limit-text']"), q("signin_hidden", "[data-hook='nav-signin']", "hidden"),
            q("state", "[data-hook='my-dogs-state']")])
        f = out["final"]
        self.assertEqual(f["names"], ["Dog One", "Dog Two"])
        self.assertEqual(f["rules"], 2)
        self.assertEqual(f["limit"], "2 of 5 dogs running.")
        self.assertTrue(f["signin_hidden"])

    def test_a_stale_token_returns_to_the_signed_out_state(self):
        out = build(self.routes(**{"/hounds/mine": [401, {"detail": "no"}]}), **SIGNED, queries=[
            q("state", "[data-hook='my-dogs-state']"), q("limit", "[data-hook='limit-text']")])
        self.assertIn("Sign in", out["final"]["state"])
        self.assertIn("Sign in to save", out["final"]["limit"])

    def test_editing_loads_the_dog_and_saving_shows_the_diff_first_then_makes_a_new_version(self):
        diff = {"changes": [{"what": "Rule 1 changed", "before": "old sentence", "after": "new sentence"},
                            {"what": "Stake", "before": "1 paper unit", "after": "2 paper units"}], "paper_only": True}
        saved = {"hound": {"id": "u-1b", "name": "Dog One", "version_no": 2}, "previous_id": "u-1", "changes": diff["changes"], "paper_only": True}
        routes = self.routes(**{"POST /hounds/u-1/diff": [200, diff], "POST /hounds/u-1/version": [200, saved]})
        out = build(routes, **SIGNED, actions=[
            dict(do="click", sel="[data-hook='edit-dog']", index=0, wait=200, label="edit",
                 capture=[q("title", "[data-hook='build-title']"), q("note", "[data-hook='build-from-note']"),
                          q("name", "[data-hook='f-name']", "value"), q("btn", "[data-hook='build-submit']"),
                          q("pmin", "[data-hook='price-min']", "value"), q("cancel", "[data-hook='edit-cancel']", "hidden")]),
            dict(do="set", sel="[data-hook='g-stake']", value="2", wait=40),
            dict(do="click", sel="[data-hook='build-submit']", wait=200, label="review",
                 capture=[q("diff_hidden", "[data-hook='diff']", "hidden"), q("items", "[data-hook='diff-item']", "texts"),
                          q("btn", "[data-hook='build-submit']")]),
            dict(do="click", sel="[data-hook='build-submit']", wait=200, label="save",
                 capture=[q("msg", "[data-hook='build-message']"), q("link", "[data-hook='new-dog-link']", "attr", attr="href")])])
        edit = out["captures"]["edit"]
        self.assertEqual(edit["title"], "Edit Dog One")
        self.assertIn("Saving makes version 2", edit["note"])
        self.assertEqual((edit["name"], edit["btn"], edit["pmin"], edit["cancel"]), ("Dog One", "Review the changes", "100", False))
        review = out["captures"]["review"]
        self.assertFalse(review["diff_hidden"])
        self.assertEqual(len(review["items"]), 2)
        self.assertIn("Before: old sentence", review["items"][0])
        self.assertIn("After: new sentence", review["items"][0])
        self.assertEqual(review["btn"], "Save as version 2")
        self.assertEqual(len(posts_to(out, "/hounds/u-1/diff")), 1)
        version = posts_to(out, "/hounds/u-1/version")
        self.assertEqual(len(version), 1)
        self.assertEqual(posts_to(out, "/hounds"), [])             # an edit never creates a second dog
        spec = user_spec.validate_spec(version[0]["body"]["spec"])
        self.assertEqual((spec["name"], spec["stake_units"]), ("Dog One", 2.0))
        self.assertIn("Saved as version 2", out["captures"]["save"]["msg"])
        self.assertEqual(out["captures"]["save"]["link"], "hound.html?id=u-1b")

    def test_changing_anything_after_the_diff_asks_for_a_new_review(self):
        diff = {"changes": [{"what": "Stake", "before": "1", "after": "2"}], "paper_only": True}
        out = build(self.routes(**{"POST /hounds/u-1/diff": [200, diff]}), **SIGNED, actions=[
            dict(do="click", sel="[data-hook='edit-dog']", index=0, wait=200),
            dict(do="click", sel="[data-hook='build-submit']", wait=200),
            dict(do="set", sel="[data-hook='g-bets']", value="4", wait=60, label="after",
                 capture=[q("btn", "[data-hook='build-submit']"), q("diff_hidden", "[data-hook='diff']", "hidden")])])
        self.assertEqual(out["captures"]["after"], {"btn": "Review the changes", "diff_hidden": True})

    def test_a_diff_with_no_changes_says_so_and_does_not_offer_to_save(self):
        out = build(self.routes(**{"POST /hounds/u-1/diff": [200, {"changes": []}]}), **SIGNED, actions=[
            dict(do="click", sel="[data-hook='edit-dog']", index=0, wait=200), dict(do="click", sel="[data-hook='build-submit']", wait=200)],
            queries=[q("diff", "[data-hook='diff-list']"), q("btn", "[data-hook='build-submit']")])
        self.assertIn("Nothing has changed", out["final"]["diff"])
        self.assertEqual(out["final"]["btn"], "Review the changes")

    def test_stop_editing_returns_to_a_new_dog(self):
        out = build(self.routes(), **SIGNED, actions=[dict(do="click", sel="[data-hook='edit-dog']", index=1, wait=200),
                                                      dict(do="click", sel="[data-hook='edit-cancel']", wait=60)],
                    queries=[q("title", "[data-hook='build-title']"), q("btn", "[data-hook='build-submit']"), q("note", "[data-hook='build-from-note']", "hidden")])
        self.assertEqual(out["final"], {"title": "Build your dog", "btn": "Send my dog in", "note": True})

    def test_edit_in_the_address_opens_that_dog(self):
        out = build(self.routes(), **SIGNED, search="?edit=u-2", queries=[q("title", "[data-hook='build-title']"), q("cards", "[data-hook='rule-card']", "count")])
        self.assertEqual((out["final"]["title"], out["final"]["cards"]), ("Edit Dog Two", 1))

    @unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
    def test_a_copy_opens_the_other_dogs_rules_as_a_new_dog_posted_with_copied_from(self):
        from api.hounds_create import CreateHoundRequest
        source = dog("alpha", "Alpha")
        copy_draft = dict(source["spec"], name="Alpha II")
        routes = self.routes(**{"/hounds/alpha/spec": [200, {"spec": copy_draft, "draft": copy_draft, "copied_from": "alpha",
                                                          "rule_sentences": source["rule_sentences"], "rule_text": "x"}],
                                "POST /hounds": [200, {"hound": {"id": "u-new", "name": "Alpha II"}}]})
        out = build(routes, **SIGNED, search="?from=alpha", actions=[dict(do="click", sel="[data-hook='build-submit']", wait=200)],
                    queries=[q("note", "[data-hook='build-from-note']"), q("name", "[data-hook='f-name']", "value")])
        self.assertEqual(out["final"]["name"], "Alpha II")
        self.assertIn("copy of another dog", out["final"]["note"])
        body = posts_to(out, "/hounds")[0]["body"]
        model = CreateHoundRequest(**body)
        self.assertEqual(model.copied_from, "alpha")
        user_spec.validate_spec(model.spec)

    def test_a_copy_that_cannot_be_loaded_leaves_a_blank_builder_and_says_so(self):
        out = build(self.routes(), **SIGNED, search="?from=ghost", queries=[q("note", "[data-hook='build-from-note']"), q("cards", "[data-hook='rule-card']", "count")])
        self.assertIn("could not be loaded", out["final"]["note"])
        self.assertEqual(out["final"]["cards"], 0)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheBadgeIcons(unittest.TestCase):
    def test_every_badge_on_the_menu_has_an_icon_drawn(self):
        ids = [b["value"] for b in MENU["badges"]]
        # the icon table is the page's own; each menu badge id must be a key (a missing one falls back to the bone, which would hide a typo)
        for badge in ids:
            self.assertRegex(JS, rf"\b{badge}: \[\[", badge)


def many_sports_menu():
    """The menu as the all-sports backend is meant to send it: many families and an ANY entry, with the stat conditions still marked
    for the sports that have the data (the old two) and the player props for one."""
    menu = copy.deepcopy(MENU)
    families = [("ANY", "Any sport"), ("MLB", "MLB"), ("NFL", "NFL"), ("tennis", "Tennis"), ("soccer", "Soccer"), ("cricket", "Cricket"),
                ("nba", "NBA"), ("nhl", "NHL"), ("ncaaf", "NCAAF"), ("ncaab", "NCAAB"), ("mma", "MMA"), ("boxing", "Boxing"), ("rugby", "Rugby")]
    menu["sports"] = [{"value": v, "label": label} for v, label in families]
    every = [v for v, _ in families]
    real = {s["value"] for s in MENU["sports"] if s["value"] != "ANY"}
    for m in menu["markets"]:
        m["sports"] = ["MLB"] if m["kind"] == "prop" else list(every)
    for c in menu["conditions"]:
        # a generic condition (every family the real menu has) covers the fixture's families too
        if real and real <= set(c.get("sports") or ()):
            c["sports"] = list(every)
    return menu


def short_sports_menu():
    menu = copy.deepcopy(MENU)
    menu["sports"] = [{"value": "MLB", "label": "MLB"}, {"value": "NFL", "label": "NFL"}]
    return menu


def strip_for_names(js):
    code = re.sub(r"export const EXAMPLES = \[.*?\];", "", js, flags=re.S)
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", code)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheSportChoiceIsASearchableChipGrid(unittest.TestCase):
    MANY = many_sports_menu()

    def go(self, extra_actions=(), queries=(), menu=None):
        routes = base_routes(**{"/hounds/builder/menu": [200, menu or self.MANY]})
        return build(routes, actions=[CLICK_BLANK, *extra_actions], queries=[
            q("chips", "[data-hook='rule-sports'] button", "texts"), q("pressed", "[data-hook='rule-sports'] button[aria-pressed='true']", "texts"),
            q("search", "[data-hook='sport-search']", "count"), *queries])

    def test_every_family_is_a_chip_with_any_sport_first_and_the_first_real_sport_picked(self):
        f = self.go()["final"]
        self.assertEqual(f["chips"][0], "Any sport")
        self.assertEqual(f["chips"][1:], [s["label"] for s in self.MANY["sports"] if s["value"] != "ANY"])
        self.assertEqual(f["pressed"], ["MLB"])
        self.assertEqual(f["search"], 1)

    def _stat_only_count(self, sport):
        # game-line conditions the menu does not list for this sport (prop conditions are not offered on a game-line rule)
        return sum(1 for c in self.MANY["conditions"]
                   if sport not in (c.get("sports") or ()) and "ml_spread" in c.get("kinds", ()))

    def test_a_short_menu_has_no_search_box(self):
        self.assertEqual(self.go(menu=short_sports_menu())["final"]["search"], 0)

    def test_the_search_box_narrows_the_chips_and_keeps_a_picked_sport_and_any_sport(self):
        f = self.go([dict(do="set", sel="[data-hook='sport-search']", value="ten", wait=60)])["final"]
        self.assertEqual(f["chips"], ["Any sport", "MLB", "Tennis"])                  # MLB stays: it is picked
        out = self.go([dict(do="set", sel="[data-hook='sport-search']", value="zzz", wait=60)], [q("none", "[data-hook='sport-none']", "hidden")])
        self.assertFalse(out["final"]["none"])
        out = self.go([dict(do="set", sel="[data-hook='sport-search']", value="zzz", wait=40), dict(do="set", sel="[data-hook='sport-search']", value="", wait=60)])
        self.assertEqual(len(out["final"]["chips"]), len(self.MANY["sports"]))

    def test_picking_a_sport_adds_it_and_any_sport_clears_the_rest(self):
        out = self.go([dict(do="click", sel="[data-sport='tennis']", wait=500)])
        self.assertEqual(out["final"]["pressed"], ["MLB", "Tennis"])
        self.assertEqual(preview_posts(out)[-1]["rules"][0]["sports"], ["MLB", "tennis"])
        out = self.go([dict(do="click", sel="[data-sport='tennis']", wait=80), dict(do="click", sel="[data-sport='ANY']", wait=500)])
        self.assertEqual(out["final"]["pressed"], ["Any sport"])
        self.assertEqual(preview_posts(out)[-1]["rules"][0]["sports"], ["ANY"])
        out = self.go([dict(do="click", sel="[data-sport='ANY']", wait=80), dict(do="click", sel="[data-sport='soccer']", wait=80)])
        self.assertEqual(out["final"]["pressed"], ["Soccer"])                          # a real sport replaces Any sport

    def test_player_props_are_greyed_for_sports_the_menu_does_not_list_them_for(self):
        prop = next(m["value"] for m in self.MANY["markets"] if m["kind"] == "prop")
        out = self.go([dict(do="click", sel=f"[data-market='{prop}']", wait=80)], [q("dis", "[data-hook='rule-sports'] button", "attrs", attr="disabled")])
        # a prop rule can only be MLB, so every other chip (Any sport included) is disabled
        labels, disabled = out["final"]["chips"], out["final"]["dis"]
        self.assertEqual([lab for lab, d in zip(labels, disabled) if d is None], ["MLB"])

    def test_stat_conditions_grey_out_with_one_line_when_a_non_mlb_nfl_sport_is_picked(self):
        mlb_only = [c for c in self.MANY["conditions"] if c["sports"] == ["MLB"] and "ml_spread" in c["kinds"]][0]
        both = [c for c in self.MANY["conditions"] if c["sports"] == ["MLB", "NFL"] and "ml_spread" in c["kinds"]][0]
        qs = [q("opts", "[data-hook='add-condition'] option", "texts"), q("greyed", "[data-hook='add-condition'] option[data-greyed='sport']", "count"),
              q("note", "[data-hook='conditions-greyed']"), q("note_n", "[data-hook='conditions-greyed']", "count")]
        # MLB (the default): the MLB-and-NFL-only ones are fine; nothing is greyed for the sport, and there is no note
        base = self.go(queries=qs)["final"]
        self.assertEqual((base["greyed"], base["note_n"]), (0, 0))
        # Tennis alone: every stat condition is greyed and says which sports have it, in the menu's own words
        out = self.go([dict(do="click", sel="[data-sport='tennis']", wait=80), dict(do="click", sel="[data-sport='MLB']", wait=80)], qs)
        f = out["final"]
        self.assertEqual(f["greyed"], self._stat_only_count("tennis"))
        self.assertIn(f"{both['label']} (MLB and NFL only)", f["opts"])
        self.assertIn(f"{mlb_only['label']} (MLB only)", f["opts"])
        self.assertEqual(f["note_n"], 1)                                              # one line, not one per condition
        self.assertRegex(f["note"], r"^\d+ stat conditions are greyed out \(MLB and NFL only; MLB only\)\.")

    def test_a_greyed_condition_cannot_be_added(self):
        both = [c for c in self.MANY["conditions"] if c["sports"] == ["MLB", "NFL"] and "ml_spread" in c["kinds"]][0]
        out = self.go([dict(do="click", sel="[data-sport='soccer']", wait=60), dict(do="click", sel="[data-sport='MLB']", wait=60),
                       dict(do="set", sel="[data-hook='add-condition']", value=both["id"], wait=200)], [q("conds", "[data-hook='condition']", "count")])
        self.assertEqual(out["final"]["conds"], 0)

    def test_any_sport_greys_the_stat_conditions_too(self):
        out = self.go([dict(do="click", sel="[data-sport='ANY']", wait=80)], [q("greyed", "[data-hook='add-condition'] option[data-greyed='sport']", "count")])
        self.assertEqual(out["final"]["greyed"], self._stat_only_count("tennis"))

    def test_moving_to_a_sport_without_the_data_removes_a_stat_condition_and_says_so(self):
        cond = [c for c in self.MANY["conditions"] if c["sports"] == ["MLB", "NFL"] and "ml_spread" in c["kinds"] and c["available"]][0]
        out = self.go([dict(do="set", sel="[data-hook='add-condition']", value=cond["id"], wait=250),
                       dict(do="click", sel="[data-sport='soccer']", wait=100)],
                      [q("conds", "[data-hook='condition']", "count"), q("dropped", "[data-hook='sport-dropped']")])
        self.assertEqual(out["final"]["conds"], 0)
        self.assertIn("1 stat condition was removed", out["final"]["dropped"])

    def test_the_script_still_names_no_sport(self):
        code = strip_for_names(JS)
        for word in ('"MLB"', '"NFL"', '"tennis"', '"soccer"', '"cricket"'):
            self.assertNotIn(word, code, word)


if __name__ == "__main__":
    unittest.main()
