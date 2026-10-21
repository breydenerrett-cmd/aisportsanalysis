"""web/interview.html and web/js/interview.js: the page's own script run under node against a fake DOM built from the real HTML.

The views the page is fed are produced by the REAL service (src/hounds/interview), so a drift between what the server sends and
what the page reads fails here and not for a visitor. What is pinned:

  * the page draws the server's question, its controls (a chip for every sport the menu offers), the chat and the progress;
  * Continue waits for the required choices and posts exactly {topic, fields, texts, data, skip};
  * ALL USER TEXT IS ESCAPED: a strategy that contains markup is shown as characters (no element is ever made from it, and the
    script uses no innerHTML, no inline handler and no document.write);
  * a free account at its limit sees the upgrade prompt, not the form; a signed-out visitor sees a sign-in link and no request is made;
  * a clarification shows its choices and posts the one picked; the review shows the summary, the can't-automate list and the claimed
    history under its label, and confirming posts the fingerprint that was shown;
  * the entry points exist (the builder, the studio's builder skeleton, My Kennel) and the page is in the two page lists.
"""
from __future__ import annotations

import json
import re
import unittest

from tests._hounds_interview_fixtures import NOW, Db, FakeRouter, reading, standard_answers
from tests.hounds_web_runner import HAS_NODE, WEB, run_page

from src.hounds.interview import service as SV

TOKEN_KEY = "aisportsanalysis.invite_token"
SIGNED = dict(stored={TOKEN_KEY: "tok"})
PAGE = (WEB / "interview.html").read_text(encoding="utf-8")
JS = (WEB / "js" / "interview.js").read_text(encoding="utf-8")
CSS = (WEB / "css" / "interview.css").read_text(encoding="utf-8")


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


def hook(name):
    return f"[data-hook='{name}']"


def opt(name, value):
    return f"[data-hook='iv-option'][data-name='{name}'][data-value='{value}']"


def wire(view):
    return json.loads(json.dumps(view, default=str))


class StaticPage(unittest.TestCase):
    def test_the_hooks_the_script_reads_are_in_the_page(self):
        for name in set(re.findall(r"HOOK\(\"([a-z-]+)\"\)", JS)):
            if name.startswith("iv-"):
                self.assertIn(f'data-hook="{name}"', PAGE, name)

    def test_the_paper_notice_and_the_footer_line_are_static_and_appear_once(self):
        self.assertEqual(PAGE.count("Paper bets only. Your hound never takes a price of -200 or worse."), 1)
        self.assertEqual(PAGE.count("1-800-GAMBLER"), 1)
        self.assertIn('href="tel:1-800-426-2537"', PAGE)

    def test_the_bar_carries_the_one_nav_and_no_primary_button(self):
        self.assertEqual(PAGE.count('class="lh-nav"'), 1)
        self.assertNotIn('data-hook="nav-cta"', PAGE)
        self.assertIn('<script type="module" src="js/nav.js"></script>', PAGE)
        self.assertIn('href="css/tokens.css"', PAGE)
        self.assertIn('href="css/interview.css"', PAGE)

    def test_the_script_never_builds_markup_from_text(self):
        for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "onclick:"):
            self.assertFalse(banned in JS, banned)
        self.assertIsNone(re.search(r"\son(?:click|load|error)=", PAGE))

    def test_no_emoji_no_exclamation_marks_and_none_of_the_banned_claim_words_in_the_page_copy(self):
        visible = re.sub(r"<(script|style|head)\b.*?</\1>|<!--.*?-->", " ", PAGE, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", visible)
        self.assertNotRegex(text, "[\U0001F000-\U0001FFFF☀-➿]")
        self.assertNotIn("!", text)
        for word in (r"\block", r"guarantee", r"\bedge\b", r"\bprofit", r"free money", r"bet\s*check", r"beta\b", r"early access"):
            self.assertIsNone(re.search(word, text.lower()), word)
        self.assertIsNone(re.search(r"bet\s*check", JS.lower() + CSS.lower()))

    def test_the_entry_points_are_on_the_builder_the_studio_skeleton_and_my_kennel(self):
        for name, needle in (("build-a-hound.html", 'data-hook="build-interview-cta"'), ("kennel.html", 'data-hook="kennel-interview-link"')):
            html = (WEB / name).read_text(encoding="utf-8")
            self.assertIn(needle, html, name)
            self.assertIn('href="interview.html"', html, name)
            self.assertIn("Turn your strategy into a hound", html, name)
        skeleton = (WEB / "js" / "builder-skeleton.js").read_text(encoding="utf-8")
        self.assertIn('"data-hook": "build-interview-cta"', skeleton)
        self.assertIn("Turn your strategy into a hound", skeleton)
        # the builder's static page and the studio skeleton keep the same interview hooks
        static = (WEB / "build-a-hound.html").read_text(encoding="utf-8")
        for name in ("build-interview", "build-interview-cta"):
            self.assertIn(f'data-hook="{name}"', static)
            self.assertTrue(f'"data-hook": "{name}"' in skeleton, name)

    def test_the_page_is_in_the_kennel_page_list_and_the_overflow_list(self):
        kennel = (WEB.parent / "tests" / "test_kennel_page.py").read_text(encoding="utf-8")
        overflow = (WEB.parent / "tests" / "test_no_horizontal_overflow.py").read_text(encoding="utf-8")
        self.assertIn('"interview.html"', kennel)
        self.assertIn('"interview.html"', overflow)

    def test_the_stylesheet_reads_the_shared_tokens_and_leaves_room_for_the_phone_tab_bar(self):
        self.assertIn("--lh-tabbar-h", CSS)
        self.assertIn("var(--accent", CSS)
        self.assertIn("prefers-reduced-motion: no-preference", CSS)
        self.assertGreaterEqual(len(re.findall(r"min-height: 44px", CSS)), 2)


@unittest.skipUnless(HAS_NODE, "node is needed to run the page script")
class InterviewPage(Db):
    def setUp(self):
        super().setUp()
        self.start_view = wire(SV.start(self.user.id, free=False, now=NOW, db=self.db))
        self.sid = self.start_view["id"]
        self.answers = standard_answers()

    def view_after(self, topics=1, router=None, overrides=None):
        out = None
        sid = SV.start(self.user.id, free=False, now=NOW, db=self.db)["id"]
        for topic, payload in standard_answers(overrides)[:topics]:
            out = SV.answer(self.user.id, sid, topic, payload, router=router, now=NOW, db=self.db)
        return wire(out), sid

    def routes(self, **extra):
        out = {"POST /hounds/interview": [200, self.start_view]}
        out.update(extra)
        return out

    def test_signed_out_it_asks_for_a_sign_in_and_makes_no_request(self):
        out = run_page("interview", routes={}, queries=[q("signin", hook("iv-signin"), "attr", attr="href"), q("shell", hook("iv-shell"), "hidden"),
                                                         q("gate", hook("iv-gate"), "hidden"), q("title", "h1")])
        self.assertEqual(out["final"]["signin"], "index.html#/signin")
        self.assertTrue(out["final"]["shell"])
        self.assertFalse(out["final"]["gate"])
        self.assertEqual(out["posts"], [])
        self.assertEqual(out["final"]["title"], "Turn your strategy into a hound")

    def test_it_draws_the_first_question_its_chat_progress_and_one_chip_for_every_sport_on_the_menu(self):
        from src.hounds import user_spec
        out = run_page("interview", **SIGNED, routes=self.routes(), queries=[
            q("asked", hook("iv-asked"), "texts"), q("said", hook("iv-said"), "count"), q("stepno", hook("iv-stepno")),
            q("title", hook("iv-step-title")), q("sports", opt("sports", "MLB"), "count"),
            q("sport_chips", "[data-hook='iv-option'][data-name='sports']", "count"), q("go_disabled", hook("iv-continue"), "disabled"),
            q("progress", hook("iv-progress"), "attr", attr="aria-valuenow"), q("skip", hook("iv-skip"), "count"),
            q("shell_hidden", hook("iv-shell"), "hidden"), q("unsupported", ".iv-chip--unsupported", "count")])
        f = out["final"]
        self.assertEqual(f["asked"], [self.start_view["step"]["prompt"]])
        self.assertEqual(f["said"], 0)
        self.assertEqual(f["stepno"], "Question 1 of 11")
        self.assertEqual(f["title"], "Sports and markets")
        self.assertEqual(f["sport_chips"], len(user_spec.sports_menu()))
        self.assertEqual(f["sports"], 1)
        self.assertTrue(f["go_disabled"])
        self.assertEqual(f["progress"], "0")
        self.assertEqual(f["skip"], 0)                       # the first question cannot be skipped
        self.assertFalse(f["shell_hidden"])
        self.assertGreaterEqual(f["unsupported"], 3)         # live, both, first five, parlays are offered and labelled
        self.assertEqual(out["posts"][0]["url"], "/hounds/interview")
        self.assertTrue(any("interview.html?id=" + self.sid in r for r in out["replaced"]))

    def test_continue_waits_for_the_required_choices_then_posts_exactly_the_answer(self):
        after, _sid = self.view_after(1)
        route = f"POST /hounds/interview/{self.sid}/answer"
        out = run_page("interview", **SIGNED, routes=self.routes(**{route: [200, after]}), actions=[
            dict(do="click", sel=opt("sports", "MLB")),
            dict(do="click", sel=opt("markets", "moneyline")),
            dict(do="click", sel=opt("markets", "total"), capture=[q("disabled", hook("iv-continue"), "disabled")], label="two_markets"),
            dict(do="click", sel=opt("timing", "pregame"), capture=[q("disabled", hook("iv-continue"), "disabled"), q("pressed", opt("timing", "pregame"), "attr", attr="aria-pressed")], label="ready"),
            dict(do="click", sel=hook("iv-continue"))],
            queries=[q("title", hook("iv-step-title")), q("said", hook("iv-said"), "texts"), q("stepno", hook("iv-stepno")),
                     q("progress", hook("iv-progress"), "attr", attr="aria-valuenow"), q("edit_chips", hook("iv-edit-topic"), "texts")])
        self.assertTrue(out["captures"]["two_markets"]["disabled"])
        self.assertFalse(out["captures"]["ready"]["disabled"])
        self.assertEqual(out["captures"]["ready"]["pressed"], "true")
        body = out["posts"][1]["body"]
        self.assertEqual(body, {"topic": "scope", "fields": {"sports": ["MLB"], "markets": ["moneyline", "total"], "timing": "pregame"},
                                "texts": {}, "data": [], "skip": False})
        f = out["final"]
        self.assertEqual(f["title"], "Side and triggers")
        self.assertEqual(f["stepno"], "Question 2 of 11")
        self.assertEqual(f["progress"], "1")
        self.assertEqual(f["edit_chips"], ["Sports and markets"])
        self.assertEqual(len(f["said"]), 1)
        self.assertIn("MLB", f["said"][0])

    def test_a_chip_can_be_unpicked_and_a_single_choice_replaces_the_last(self):
        out = run_page("interview", **SIGNED, routes=self.routes(), actions=[
            dict(do="click", sel=opt("timing", "live")), dict(do="click", sel=opt("timing", "pregame")),
            dict(do="click", sel=opt("sports", "MLB")), dict(do="click", sel=opt("sports", "MLB"))],
            queries=[q("live", opt("timing", "live"), "attr", attr="aria-pressed"), q("pre", opt("timing", "pregame"), "attr", attr="aria-pressed"),
                     q("mlb", opt("sports", "MLB"), "attr", attr="aria-pressed")])
        self.assertEqual((out["final"]["live"], out["final"]["pre"], out["final"]["mlb"]), ("false", "true", "false"))

    def test_skip_is_offered_where_the_server_allows_it_and_posts_skip_true(self):
        view, sid = self.view_after(5)           # the pass_rules question is next and skippable
        self.assertTrue(view["step"]["skippable"])
        route = f"POST /hounds/interview/{sid}/answer"
        out = run_page("interview", **SIGNED, routes={f"/hounds/interview/{sid}": [200, view], route: [200, view]},
                       search=f"?id={sid}", actions=[dict(do="click", sel=hook("iv-skip"))], queries=[q("skip", hook("iv-skip"), "count")])
        self.assertEqual(out["posts"][0]["body"], {"topic": "pass_rules", "fields": {}, "texts": {}, "data": [], "skip": True})

    def test_text_is_sent_as_typed_and_shown_back_as_text_never_as_markup(self):
        evil = '<img src=x onerror=alert(1)><script>alert(2)</script> & "quotes"'
        view, sid = self.view_after(1)
        view["log"].append({"role": "person", "text": evil})
        view["log"].append({"role": "assistant", "text": "<b>bold</b> question?"})
        view["cant_automate"] = [{"id": "x", "topic": "side", "text": evil, "reason": "<i>reason</i>", "code": ""}]
        view["assistant_note"] = "<u>note</u>"
        route = f"POST /hounds/interview/{self.sid}/answer"
        out = run_page("interview", **SIGNED, routes=self.routes(**{route: [200, view]}), actions=[
            dict(do="set", sel="[data-hook='iv-text'][data-name='text']", value=evil),
            dict(do="click", sel=opt("sports", "MLB")), dict(do="click", sel=opt("markets", "moneyline")), dict(do="click", sel=opt("timing", "pregame")),
            dict(do="click", sel=hook("iv-continue"))],
            queries=[q("said", hook("iv-said"), "texts"), q("asked", hook("iv-asked"), "texts"), q("cant", hook("iv-cant-item"), "texts"),
                     q("note", hook("iv-assistant-note")), q("imgs", "img", "count"), q("scripts", "script", "count"), q("bold", "b", "count"),
                     q("italic", "i", "count"), q("under", "u", "count"), q("summary", hook("iv-cant-summary"))])
        self.assertEqual(out["posts"][1]["body"]["texts"]["text"], evil)
        f = out["final"]
        self.assertIn(evil, f["said"])
        self.assertIn("<b>bold</b> question?", f["asked"])
        self.assertEqual(f["note"], "<u>note</u>")
        self.assertIn("<i>reason</i>", f["cant"][0])
        self.assertEqual((f["imgs"], f["scripts"], f["bold"], f["italic"], f["under"]), (0, 0, 0, 0, 0))
        self.assertEqual(f["summary"], "Can't automate yet (1)")

    def test_the_assistant_resting_note_is_shown_and_the_form_is_the_same(self):
        view, _ = self.view_after(1, router=FakeRouter())        # capped: no answer
        self.assertTrue(view["assistant_note"])
        route = f"POST /hounds/interview/{self.sid}/answer"
        out = run_page("interview", **SIGNED, routes=self.routes(**{route: [200, view]}), actions=[
            dict(do="click", sel=opt("sports", "MLB")), dict(do="click", sel=opt("markets", "moneyline")), dict(do="click", sel=opt("timing", "pregame")),
            dict(do="click", sel=hook("iv-continue"))],
            queries=[q("note", hook("iv-assistant-note")), q("note_hidden", hook("iv-assistant-note"), "hidden"), q("title", hook("iv-step-title")),
                     q("side_chips", "[data-hook='iv-option'][data-name='side']", "count")])
        self.assertIn("resting", out["final"]["note"])
        self.assertFalse(out["final"]["note_hidden"])
        self.assertEqual(out["final"]["title"], "Side and triggers")
        self.assertEqual(out["final"]["side_chips"], 5)

    def test_a_free_account_at_its_limit_sees_the_upgrade_prompt_and_no_form(self):
        refusal = {"detail": {"error": "upgrade_required", "feature": "more_dogs",
                              "message": "A free account keeps one dog. Become a member to run up to 5 dogs, or remove your current dog to build a new one."}}
        out = run_page("interview", **SIGNED, routes={"POST /hounds/interview": [402, refusal]}, queries=[
            q("prompt", hook("upgrade-prompt"), "count"), q("feature", hook("upgrade-prompt"), "attr", attr="data-feature"),
            q("title", ".upgrade-prompt__title"), q("body", ".upgrade-prompt__body"), q("link", hook("upgrade-link"), "attr", attr="href"),
            q("gate_hidden", hook("iv-gate"), "hidden"), q("shell_hidden", hook("iv-shell"), "hidden"), q("controls", hook("iv-option"), "count")])
        f = out["final"]
        self.assertEqual(f["prompt"], 1)
        self.assertEqual(f["feature"], "more_dogs")
        self.assertEqual(f["title"], "A free account keeps one dog")
        self.assertIn("remove your current dog", f["body"])
        self.assertEqual(f["link"], "index.html#/billing")
        self.assertFalse(f["gate_hidden"])
        self.assertTrue(f["shell_hidden"])
        self.assertEqual(f["controls"], 0)

    def test_a_network_failure_is_said_plainly(self):
        out = run_page("interview", **SIGNED, routes={}, down=["/hounds/interview"], queries=[q("gate", hook("iv-gate")), q("hidden", hook("iv-gate"), "hidden")])
        self.assertIn("Could not reach LINEHOUND", out["final"]["gate"])
        self.assertFalse(out["final"]["hidden"])

    def test_a_clarification_shows_its_choices_and_posts_the_one_picked(self):
        sid = SV.start(self.user.id, free=False, now=NOW, db=self.db)["id"]
        view = None
        for topic, payload in standard_answers({"price": {"fields": {"price_min": -150, "price_max": -120}}}):
            view = SV.answer(self.user.id, sid, topic, payload, now=NOW, db=self.db)
        view = wire(view)
        self.assertEqual(view["step"]["kind"], "clarify")
        clar = view["step"]["clarification"]
        after = wire(SV.show(self.user.id, sid, db=self.db))
        out = run_page("interview", **SIGNED, search=f"?id={sid}", routes={
            f"/hounds/interview/{sid}": [200, view], f"POST /hounds/interview/{sid}/resolve": [200, after]},
            actions=[dict(do="click", sel=f"{hook('iv-resolve')}[data-option='{clar['options'][0]['id']}']")],
            captureInitial=[q("question", hook("iv-clarify")), q("options", hook("iv-resolve"), "texts"), q("title", hook("iv-step-title")),
                            q("bubble", hook("iv-asked"), "texts")],
            queries=[q("clarify_left", hook("iv-clarify"), "count")])
        init = out["captures"]["initial"]
        self.assertEqual(init["title"], "One thing to settle")
        self.assertEqual(init["question"], clar["question"])
        self.assertEqual(sorted(init["options"]), sorted(o["label"] for o in clar["options"]))
        self.assertIn(clar["question"], init["bubble"])
        self.assertEqual(out["posts"][0]["body"], {"clarification": clar["id"], "option": clar["options"][0]["id"]})

    def test_the_review_shows_the_summary_the_cant_automate_list_and_the_claimed_history_and_confirm_posts_the_fingerprint(self):
        sid = SV.start(self.user.id, free=False, now=NOW, db=self.db)["id"]
        view = None
        overrides = {"history": {"texts": {"text": "2026-09-01, Cubs ML, +120, W\n2026-09-02, Mets ML, -110, L"}},
                     "stake": {"fields": {"stake_units": 1.0}, "texts": {"text": "stop after a 10 unit drawdown"}}}
        for topic, payload in standard_answers(overrides):
            view = SV.answer(self.user.id, sid, topic, payload, now=NOW, db=self.db)
        view = wire(view)
        self.assertEqual(view["step"]["kind"], "review")
        shown = wire(SV.review(self.user.id, sid, "Rested Home Dogs", now=NOW, db=self.db))
        done = {"hound_id": "u-abc123", "record_id": "sr-1", "already": False, "freeze_hash": shown["freeze_hash"],
                "hound": {"id": "u-abc123", "name": "Rested Home Dogs"}, "record": {"effective_date": "2026-10-21"}}
        out = run_page("interview", **SIGNED, search=f"?id={sid}", routes={
            f"/hounds/interview/{sid}": [200, view], f"POST /hounds/interview/{sid}/review": [200, shown],
            f"POST /hounds/interview/{sid}/confirm": [200, done]},
            actions=[dict(do="set", sel=hook("iv-name"), value="Rested Home Dogs"),
                     dict(do="click", sel=hook("iv-review-go"), capture=[
                         q("lines", hook("iv-summary-line"), "texts"), q("cant", hook("iv-review-cant-item"), "texts"), q("claimed", hook("iv-claimed")),
                         q("effective", hook("iv-effective")), q("hash", hook("iv-hash")), q("confirm", hook("iv-confirm")),
                         q("shell_hidden", hook("iv-shell"), "hidden")], label="review"),
                     dict(do="click", sel=hook("iv-confirm"))],
            queries=[q("done_title", hook("iv-done-title")), q("open", hook("iv-open-hound"), "attr", attr="href"), q("kennel", hook("iv-open-kennel"), "attr", attr="href"),
                     q("line", hook("iv-done-line"))])
        review = out["captures"]["review"]
        self.assertTrue(review["lines"][0].startswith("MLB moneylines"))
        self.assertEqual(len(review["lines"]), len(shown["summary"]))
        self.assertTrue(any("drawdown" in c for c in review["cant"]))
        self.assertIn("claimed, unverified", review["claimed"])
        self.assertIn("1-1-0", review["claimed"])
        self.assertNotRegex(review["claimed"].lower(), r"profit|units|roi")
        self.assertIn("2026-10-21", review["effective"])
        self.assertEqual(review["hash"], shown["freeze_hash"])
        self.assertEqual(review["confirm"], "Create Rested Home Dogs")
        self.assertTrue(review["shell_hidden"])
        self.assertEqual([p["url"].split("/")[-1] for p in out["posts"]], ["review", "confirm"])
        self.assertEqual(out["posts"][0]["body"], {"name": "Rested Home Dogs"})
        self.assertEqual(out["posts"][1]["body"], {"name": "Rested Home Dogs", "freeze_hash": shown["freeze_hash"]})
        f = out["final"]
        self.assertEqual(f["done_title"], "Rested Home Dogs is in your kennel")
        self.assertEqual(f["open"], "hound.html?id=u-abc123")
        self.assertEqual(f["kennel"], "kennel.html")
        self.assertNotRegex(f["line"].lower(), r"profit|win|edge|guarantee")

    def test_a_name_the_menu_refuses_is_shown_under_the_name_box_and_nothing_is_confirmed(self):
        sid = SV.start(self.user.id, free=False, now=NOW, db=self.db)["id"]
        view = None
        for topic, payload in standard_answers():
            view = SV.answer(self.user.id, sid, topic, payload, now=NOW, db=self.db)
        refusal = {"detail": {"error": "spec_invalid", "fields": {"name": "contains language that is not allowed"}}}
        out = run_page("interview", **SIGNED, search=f"?id={sid}", routes={
            f"/hounds/interview/{sid}": [200, wire(view)], f"POST /hounds/interview/{sid}/review": [422, refusal]},
            actions=[dict(do="set", sel=hook("iv-name"), value="Rude Name"), dict(do="click", sel=hook("iv-review-go"))],
            queries=[q("error", hook("iv-error")), q("confirm", hook("iv-confirm"), "count")])
        self.assertIn("name: contains language that is not allowed", out["final"]["error"])
        self.assertEqual(out["final"]["confirm"], 0)

    def test_the_upgrade_prompt_also_replaces_the_review_when_the_limit_is_reached_at_confirm(self):
        sid = SV.start(self.user.id, free=False, now=NOW, db=self.db)["id"]
        view = None
        for topic, payload in standard_answers():
            view = SV.answer(self.user.id, sid, topic, payload, now=NOW, db=self.db)
        shown = wire(SV.review(self.user.id, sid, "Rested Home Dogs", now=NOW, db=self.db))
        refusal = {"detail": {"error": "upgrade_required", "feature": "more_dogs", "message": "A free account keeps one dog."}}
        out = run_page("interview", **SIGNED, search=f"?id={sid}", routes={
            f"/hounds/interview/{sid}": [200, wire(view)], f"POST /hounds/interview/{sid}/review": [200, shown],
            f"POST /hounds/interview/{sid}/confirm": [402, refusal]},
            actions=[dict(do="set", sel=hook("iv-name"), value="Rested Home Dogs"), dict(do="click", sel=hook("iv-review-go")), dict(do="click", sel=hook("iv-confirm"))],
            queries=[q("prompt", f"{hook('iv-review')} {hook('upgrade-prompt')}", "count"), q("done", hook("iv-done-title"), "count")])
        self.assertEqual(out["final"]["prompt"], 1)
        self.assertEqual(out["final"]["done"], 0)

    def test_an_answered_topic_can_be_opened_again_prefilled(self):
        view, sid = self.view_after(1)
        edit, _ = self.view_after(1)
        reopened = wire(SV.show(self.user.id, sid, edit="scope", db=self.db))
        out = run_page("interview", **SIGNED, search=f"?id={sid}", routes={
            f"/hounds/interview/{sid}": [200, view], f"/hounds/interview/{sid}?edit=scope": [200, reopened]},
            actions=[dict(do="click", sel=f"{hook('iv-edit-topic')}[data-topic='scope']")],
            queries=[q("title", hook("iv-step-title")), q("mlb", opt("sports", "MLB"), "attr", attr="aria-pressed"),
                     q("pre", opt("timing", "pregame"), "attr", attr="aria-pressed"), q("go", hook("iv-continue"), "disabled")])
        self.assertEqual(out["final"]["title"], "Sports and markets")
        self.assertEqual((out["final"]["mlb"], out["final"]["pre"], out["final"]["go"]), ("true", "true", False))

    def test_the_data_question_posts_its_choices_in_data_and_labels_the_unsupported_ones(self):
        view, sid = self.view_after(3)
        self.assertEqual(view["step"]["topic"], "data")
        out = run_page("interview", **SIGNED, search=f"?id={sid}", routes={
            f"/hounds/interview/{sid}": [200, view], f"POST /hounds/interview/{sid}/answer": [200, view]},
            actions=[dict(do="click", sel=opt("data", "weather")), dict(do="click", sel=opt("data", "injuries")), dict(do="click", sel=hook("iv-continue"))],
            queries=[q("tags", ".iv-tag", "texts")])
        self.assertEqual(out["posts"][0]["body"]["data"], ["weather", "injuries"])
        self.assertEqual(out["posts"][0]["body"]["fields"], {})
        self.assertTrue(all("can't automate yet" in t for t in out["final"]["tags"]))
        self.assertGreaterEqual(len(out["final"]["tags"]), 6)

    def test_the_history_question_has_a_text_box_and_no_upload_without_filereader(self):
        view, sid = self.view_after(8)
        self.assertEqual(view["step"]["topic"], "history")
        out = run_page("interview", **SIGNED, search=f"?id={sid}", routes={f"/hounds/interview/{sid}": [200, view]},
                       queries=[q("box", "[data-hook='iv-text'][data-name='text']", "count"), q("file", hook("iv-file"), "count")])
        self.assertEqual(out["final"]["box"], 1)
        self.assertEqual(out["final"]["file"], 0)
        self.assertIn("FileReader", JS)


if __name__ == "__main__":
    unittest.main()
