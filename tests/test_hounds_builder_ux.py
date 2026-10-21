"""The builder never goes dead, a dog can be removed, and an old dog can be edited: the page, run for real under node.

THE REPORT (a real member, phone, 2026-10-19): he typed a long free-form strategy, pressed "Read my strategy" and
"it's just greyed out"; Step 2 still said "Describe a strategy above". And: "I can't delete my two dawgs and/or edit the
old strategies." The first answer's draft was held hostage by the translator job, nothing said a text was too long,
and there was no button to remove a dog. These tests hold the page to:

  * the parser's draft (cards, understood lines, the words it could not read, assumptions, suggestions) is on the page
    the moment the answer arrives, whatever the second reader is doing;
  * the Read button is never disabled, and every way the read can go wrong (a 422, the per-minute limit, a dead
    connection, a signed-out visitor, a rate-limited translator, a 90 second wait, a failing poll) ends in a sentence
    and leaves the text, the draft and the buttons usable;
  * a live "x / 600" count, no silent cut-off (an over-long paste reads whole sentences and lists what was left out);
  * "Remove from my kennel" asks first, retires, says so, and a "no" removes nothing; a classic dog edits and saves.

Skipped without node. (tests/test_hounds_retire_and_edit.py holds the server half.)
"""
from __future__ import annotations

import json
import unittest

from src.hounds import user_spec
from src.hounds.english import parser, render
from tests import _hounds_rules_fixtures as F
from tests._hounds_user_fixtures import spec_dict
from tests.hounds_web_runner import HAS_NODE, run_page
from tests.test_hounds_builder_web import (MENU, SIGNED, TOKEN_KEY, base_routes, build, dog, english_answer, posts_to, preview_answer, q)

JACOB = ("use statistics, previous head-to-head matchups, previous matchups as in last five games, use home advantage and "
         "away games data matched with offensive and defensive stats")
INPUT = "[data-hook='english-input']"
GO = "[data-hook='english-go']"
TRANSLATING = {"status": "translating", "job_id": "j-1"}
DRAFT_KEY = "linehound.builder.draft.v1"
TIMEOUT_TEXT = "The second reader didn't answer. Here's what I could read; finish the rest with the rule cards or rephrase."


def read_actions(text, wait=350):
    return [dict(do="set", sel=INPUT, value=text), dict(do="click", sel=GO, wait=wait, label="read")]


def routes_for(text, **extra):
    answer = english_answer(text, **extra.pop("answer", {}))
    r = base_routes(**{"POST /hounds/english": [200, answer],
                       "POST /hounds/builder/preview": [200, preview_answer(sentences=answer.get("sentences", []))]})
    r.update(extra)
    return r


STATE = [q("go_disabled", GO, "disabled"), q("blank_disabled", "[data-hook='blank-rule']", "disabled"),
         q("status", "[data-hook='english-status']"), q("input", INPUT, "value"), q("cards", "[data-hook='rule-card']", "count"),
         q("rules_empty", "[data-hook='rules-empty']", "hidden"), q("rules_body", "[data-hook='rules-body']", "hidden"),
         q("translator", "[data-hook='english-translator']"), q("intervals_note", "[data-hook='english-translator']", "attr", attr="data-state")]


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheCount(unittest.TestCase):
    def test_a_live_count_warns_near_the_limit_and_says_what_happens_at_and_over_it(self):
        caps = [q("count", "[data-hook='english-count']"), q("state", "[data-hook='english-count']", "attr", attr="data-state"),
                q("limit_hidden", "[data-hook='english-limit']", "hidden"), q("limit", "[data-hook='english-limit']")]
        out = build(captureInitial=caps, actions=[
            dict(do="set", sel=INPUT, value="x" * 12, label="small", capture=caps),
            dict(do="set", sel=INPUT, value="x" * 560, label="near", capture=caps),
            dict(do="set", sel=INPUT, value="x" * 600, label="limit", capture=caps),
            dict(do="set", sel=INPUT, value="x" * 655, label="over", capture=caps)])
        c = out["captures"]
        self.assertEqual(c["initial"]["count"], "0 / 600")
        self.assertEqual((c["small"]["count"], c["small"]["state"], c["small"]["limit_hidden"]), ("12 / 600", None, True))
        self.assertEqual((c["near"]["count"], c["near"]["state"], c["near"]["limit_hidden"]), ("560 / 600", "near", True))
        self.assertEqual((c["limit"]["state"], c["limit"]["limit_hidden"]), ("limit", False))
        self.assertIn("600 character limit", c["limit"]["limit"])
        self.assertEqual((c["over"]["count"], c["over"]["state"]), ("655 / 600", "over"))
        self.assertIn("655 characters and the limit is 600", c["over"]["limit"])

    def test_the_box_has_no_maxlength_because_a_browser_cuts_a_paste_without_a_word(self):
        out = build(queries=[q("max", INPUT, "attr", attr="maxlength")])
        self.assertIsNone(out["final"]["max"])

    def test_an_over_long_text_reads_the_whole_sentences_that_fit_and_lists_what_was_left_out(self):
        sentence = "Bet home underdogs on 2+ days rest. "
        text = (sentence * 20).strip()                     # 719 characters
        self.assertGreater(len(text), 600)
        out = build(routes_for(sentence.strip()), actions=read_actions(text), queries=STATE + [
            q("notread", "[data-hook='english-notread'] li", "texts"), q("count", "[data-hook='english-count']")])
        sent = posts_to(out, "/hounds/english")[0]["body"]["text"]
        self.assertLessEqual(len(sent), 600)
        self.assertTrue(sent.endswith("rest."), sent[-20:])                 # cut at a sentence, not mid-word
        f = out["final"]
        self.assertTrue(any("past the 600 character limit" in n for n in f["notread"]), f["notread"])
        self.assertEqual(f["input"], text)                                  # the box is never touched
        self.assertEqual(f["cards"], 1)                                     # and the draft is on the page
        self.assertFalse(f["go_disabled"])

    def test_one_giant_sentence_is_cut_at_the_last_space_that_fits(self):
        text = "bet " + "home underdogs " * 60                              # no sentence end at all
        out = build(routes_for("bet home underdogs"), actions=read_actions(text.strip()))
        sent = posts_to(out, "/hounds/english")[0]["body"]["text"]
        self.assertLessEqual(len(sent), 600)
        self.assertIn(sent.split()[-1], ("home", "underdogs"), sent[-20:])      # a whole word, never "underd"


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheDraftIsNeverHeldBackByTheSecondReader(unittest.TestCase):
    TEXT = JACOB + " to pick the best teams to win"

    def test_the_members_text_fills_step_two_at_once_while_the_second_reader_works(self):
        out = build(routes_for(self.TEXT, answer=dict(translation=TRANSLATING, job_id="j-1", status="translating")), **SIGNED,
                    actions=read_actions(self.TEXT), queries=STATE + [
            q("understood", "[data-hook='english-understood'] li", "texts"), q("notread", "[data-hook='english-notread'] li", "texts"),
            q("assumed", "[data-hook='english-assumed']"), q("suggestions", "[data-hook='suggestion']", "count"),
            q("spinner", "[data-hook='translator-spinner']", "count"), q("read_hidden", "[data-hook='english-read']", "hidden")])
        f = out["final"]
        # step 2 is drawn from the FIRST answer
        self.assertEqual((f["rules_empty"], f["rules_body"], f["cards"]), (True, False, 1))
        self.assertTrue(any("head-to-head" in u for u in f["understood"]), f["understood"])
        self.assertTrue(any("home advantage" in u for u in f["understood"]))
        self.assertTrue(any('"best"' in n and "was not understood" in n for n in f["notread"]), f["notread"])
        self.assertIn("Assumed", f["assumed"])
        self.assertIn("at least 3 wins in the last 5 meetings", f["assumed"])
        self.assertGreaterEqual(f["suggestions"], 1)
        # and the second reader is a spinner with its own words, the buttons still live
        self.assertEqual(f["spinner"], 1)
        self.assertEqual(f["translator"], "A second reader is translating the rest (about 30 seconds)...")
        self.assertFalse(f["go_disabled"])
        self.assertFalse(f["blank_disabled"])
        self.assertEqual(f["status"], "Read. Your draft is in step 2 below.")
        self.assertEqual(out["intervals"], [1000])

    def test_the_cards_hold_the_new_conditions_from_the_menu(self):
        out = build(routes_for(self.TEXT), actions=read_actions(self.TEXT), queries=[
            q("conds", "[data-hook='condition']", "attrs", attr="data-cond")])
        self.assertEqual(sorted(out["final"]["conds"]), sorted(["head_to_head", "last_n_wins", "venue_record", "matchup_edge", "matchup_edge"]))

    def test_a_poll_that_keeps_saying_translating_backs_off_and_gives_up_at_ninety_seconds(self):
        still = {"job_id": "j-1", "status": "translating", "paper_only": True}
        routes = routes_for(self.TEXT, answer=dict(translation=TRANSLATING, job_id="j-1", status="translating"),
                            **{"/hounds/english/j-1": [200, still]})
        out = build(routes, **SIGNED, actions=read_actions(self.TEXT) + [
            dict(do="fire_timers", times=30, gap=3, wait=60, label="thirty", capture=[q("line", "[data-hook='english-translator']")]),
            dict(do="fire_timers", times=70, gap=3, wait=120, label="timeout")], queries=STATE)
        thirty = out["captures"]["thirty"]["line"]
        self.assertIn("A second reader is translating", thirty)             # still waiting at 30 seconds
        f = out["final"]
        self.assertEqual(f["translator"], TIMEOUT_TEXT)
        self.assertEqual(out["intervals"], [])                              # the timer is gone
        polls = [g for g in out["gets"] if g.endswith("/hounds/english/j-1")]
        self.assertGreaterEqual(len(polls), 5)
        self.assertLessEqual(len(polls), 20, "polls back off; they are not one a second")
        # ...and nothing is disabled or lost
        self.assertFalse(f["go_disabled"])
        self.assertEqual(f["cards"], 1)
        self.assertIn("head-to-head", out["text"])

    def test_a_poll_that_fails_three_times_stops_and_says_so(self):
        routes = routes_for(self.TEXT, answer=dict(translation=TRANSLATING, job_id="j-1", status="translating"),
                            **{"/hounds/english/j-1": [503, {"detail": "down"}]})
        out = build(routes, **SIGNED, actions=read_actions(self.TEXT) + [dict(do="fire_timers", times=40, gap=3, wait=120)], queries=STATE)
        self.assertEqual(out["intervals"], [])
        self.assertIn("could not be loaded", out["final"]["translator"])
        self.assertIn("finish the rest with the rule cards", out["final"]["translator"])
        self.assertFalse(out["final"]["go_disabled"])

    def test_a_lapsed_sign_in_during_the_wait_offers_the_sign_in_link(self):
        routes = routes_for(self.TEXT, answer=dict(translation=TRANSLATING, job_id="j-1", status="translating"),
                            **{"/hounds/english/j-1": [401, {"detail": "no"}]})
        out = build(routes, **SIGNED, actions=read_actions(self.TEXT) + [dict(do="fire_timers", times=3, gap=3, wait=120)],
                    queries=STATE + [q("link", "[data-hook='translator-signin']", "attr", attr="href")])
        self.assertEqual(out["final"]["link"], "index.html#/signin")
        self.assertEqual(out["intervals"], [])

    def test_reading_again_cancels_the_old_wait(self):
        routes = routes_for(self.TEXT, answer=dict(translation=TRANSLATING, job_id="j-1", status="translating"))
        out = build(routes, **SIGNED, actions=read_actions(self.TEXT) + [
            dict(do="set", sel=INPUT, value="Bet home underdogs"), dict(do="click", sel=GO, wait=200)])
        self.assertEqual(len(out["intervals"]), 1)                          # one timer, for the newest job only


@unittest.skipUnless(HAS_NODE, "node not installed")
class EveryWayAReadCanFailEndsInWordsAndAUsableBuilder(unittest.TestCase):
    def failing(self, status, body, text="home underdogs with a sharks theme"):
        routes = base_routes(**{"POST /hounds/english": [status, body]})
        return build(routes, actions=read_actions(text, wait=200), queries=STATE)

    def check(self, f, *, text="home underdogs with a sharks theme"):
        self.assertFalse(f["go_disabled"], "the Read button is never left disabled")
        self.assertFalse(f["blank_disabled"])
        self.assertEqual(f["input"], text)                                  # the person's words are still in the box
        self.assertTrue(f["status"])

    def test_a_422_for_a_long_text_says_how_long_and_what_to_do(self):
        out = self.failing(422, {"detail": {"error": "text_too_long", "max": 600, "length": 650,
                                            "message": "That is 650 characters and the limit is 600. Shorten it, or send it as a few shorter sentences."}})
        self.check(out["final"])
        self.assertIn("650 characters and the limit is 600", out["final"]["status"])
        self.assertEqual(out["final"]["cards"], 0)

    def test_a_422_with_no_message_still_says_something_useful(self):
        out = self.failing(422, {"detail": {"error": "text_too_long"}})
        self.check(out["final"])
        self.assertIn("Shorten it", out["final"]["status"])
        self.assertIn("blank rule", out["final"]["status"])

    def test_the_per_minute_limit_says_to_wait_and_keeps_the_text(self):
        out = self.failing(429, {"detail": {"error": "rate_limited", "retry_after": 30}})
        self.check(out["final"])
        self.assertIn("Wait a few seconds", out["final"]["status"])

    def test_a_dead_connection_says_so_and_offers_a_blank_rule(self):
        routes = base_routes()
        out = build(routes, actions=read_actions("home dogs", wait=200), down=["/hounds/english"], queries=STATE)
        self.check(out["final"], text="home dogs")
        self.assertIn("could not reach", out["final"]["status"])
        self.assertIn("blank rule", out["final"]["status"])

    def test_a_builder_whose_menu_never_loaded_offers_to_try_again_and_then_works(self):
        out = build(base_routes(**{"/hounds/builder/menu": [500, {"detail": "down"}]}), switchAfter={"/hounds/builder/menu": [1, [200, MENU]]},
                    captureInitial=[q("go", GO, "disabled"), q("retry", "[data-hook='menu-retry']", "count")],
                    actions=[dict(do="click", sel="[data-hook='menu-retry']", wait=300, label="retry", capture=[
                        q("go", GO, "disabled"), q("blank", "[data-hook='blank-rule']", "disabled"), q("retry", "[data-hook='menu-retry']", "count"),
                        q("empty", "[data-hook='rules-empty']")]),
                        dict(do="click", sel="[data-hook='blank-rule']", wait=150)], queries=[q("cards", "[data-hook='rule-card']", "count")])
        self.assertEqual(out["captures"]["initial"], {"go": True, "retry": 1})
        self.assertEqual(out["captures"]["retry"], {"go": False, "blank": False, "retry": 0,
                                                    "empty": "Describe a strategy above, or start from a blank rule."})
        self.assertEqual(out["final"]["cards"], 1)

    def test_a_server_error_says_so(self):
        out = self.failing(500, {"detail": "boom"})
        self.check(out["final"])
        self.assertIn("500", out["final"]["status"])

    def test_the_page_can_still_be_driven_by_hand_after_a_failure(self):
        out = build(base_routes(**{"POST /hounds/english": [500, {"detail": "boom"}]}), actions=read_actions("home dogs", wait=150) + [
            dict(do="click", sel="[data-hook='blank-rule']", wait=200)], queries=STATE)
        self.assertEqual(out["final"]["cards"], 1)

    def test_signed_out_the_draft_is_shown_with_a_sign_in_link_that_keeps_it(self):
        text = "home underdogs with a sharks theme"
        out = build(routes_for(text, answer=dict(translation={"status": "sign_in_required"},
                                                 message="Sign in and I can have the translator take a second look.")),
                    actions=read_actions(text) + [dict(do="click", sel="[data-hook='translator-signin']", wait=60)], queries=STATE + [
            q("link", "[data-hook='translator-signin']", "attr", attr="href"), q("understood", "[data-hook='english-understood'] li", "texts")])
        f = out["final"]
        self.assertEqual(f["link"], "index.html#/signin")
        self.assertIn("(your draft is kept)", f["translator"])
        self.assertEqual(f["cards"], 1)                                     # the draft is there before anyone signs in
        self.assertEqual(out["intervals"], [])
        saved = json.loads(out["storedAfter"][DRAFT_KEY])
        self.assertEqual(saved["text"], text)
        self.assertEqual(saved["spec"]["rules"][0]["side"], "home")
        self.assertNotIn("name", {k for k, v in saved["spec"].items() if v and k == "name"})

    def test_after_signing_in_the_saved_draft_comes_back(self):
        text = "home underdogs with a sharks theme"
        first = build(routes_for(text, answer=dict(translation={"status": "sign_in_required"})),
                      actions=read_actions(text) + [dict(do="click", sel="[data-hook='translator-signin']", wait=60)])
        stored = {DRAFT_KEY: first["storedAfter"][DRAFT_KEY], TOKEN_KEY: "tok"}
        out = build(base_routes(), stored=stored, queries=STATE + [q("note", "[data-hook='build-from-note']")])
        f = out["final"]
        self.assertEqual(f["input"], text)
        self.assertEqual(f["cards"], 1)
        self.assertIn("Welcome back", f["note"])
        self.assertNotIn(DRAFT_KEY, out["storedAfter"])                     # used once

    def test_a_stale_saved_draft_is_ignored_and_blocked_storage_does_not_break_the_page(self):
        stale = json.dumps({"at": 1, "text": "old", "spec": None})
        out = build(base_routes(), stored={DRAFT_KEY: stale}, queries=STATE)
        self.assertEqual((out["final"]["input"], out["final"]["cards"]), ("", 0))
        out = build(routes_for("home underdogs with a sharks theme", answer=dict(translation={"status": "sign_in_required"})),
                    storageThrows="methods", actions=read_actions("home underdogs with a sharks theme") +
                    [dict(do="click", sel="[data-hook='translator-signin']", wait=60)], queries=STATE)
        self.assertEqual(out["final"]["cards"], 1)

    def test_a_rate_limited_translator_says_so_and_keeps_the_draft(self):
        text = "home underdogs with a sharks theme"
        msg = "You have used all 8 second-reader tries for this hour (more in about 41 minutes). Here is what I could read; finish the rest with the rule cards or rephrase."
        out = build(routes_for(text, answer=dict(translation={"status": "rate_limited", "retry_after": 2460, "per_hour": 8}, message=msg)),
                    **SIGNED, actions=read_actions(text), queries=STATE)
        f = out["final"]
        self.assertEqual(f["translator"], msg)
        self.assertEqual(f["cards"], 1)
        self.assertEqual(out["intervals"], [])
        self.assertFalse(f["go_disabled"])

    def test_a_refused_answer_from_the_second_reader_says_why_and_keeps_the_draft(self):
        text = "home underdogs with a sharks theme"
        refused = {"job_id": "j-1", "status": "refused", "reasons": {"rules[0].price_min": "cannot be -200 or worse"}, "paper_only": True}
        out = build(routes_for(text, answer=dict(translation=TRANSLATING, job_id="j-1", status="translating"),
                               **{"/hounds/english/j-1": [200, refused]}), **SIGNED,
                    actions=read_actions(text) + [dict(do="fire_timers", wait=150)], queries=STATE)
        self.assertIn("cannot be -200 or worse", out["final"]["translator"])
        self.assertEqual(out["final"]["cards"], 1)
        self.assertEqual(out["intervals"], [])

    def test_a_render_failure_is_a_sentence_not_a_dead_page(self):
        broken = english_answer("home dogs")
        broken["understood"] = [None]                     # showRead cannot draw this
        out = build(base_routes(**{"POST /hounds/english": [200, broken]}), actions=read_actions("home dogs", wait=200), queries=STATE)
        self.assertIn("could not draw the result", out["final"]["status"])
        self.assertFalse(out["final"]["go_disabled"])
        self.assertEqual(out["final"]["input"], "home dogs")


@unittest.skipUnless(HAS_NODE, "node not installed")
class SuggestionsAndWhySendIsGreyedOut(unittest.TestCase):
    TEXT = "teams with historical dominance in the series"

    def test_unread_words_come_with_a_wording_the_parser_reads_and_a_button_that_adds_it(self):
        out = build(routes_for(self.TEXT), actions=read_actions(self.TEXT) + [
            dict(do="click", sel="[data-hook='suggest-add']", wait=80, label="add", capture=[
                q("input", INPUT, "value"), q("count", "[data-hook='english-count']"), q("status", "[data-hook='english-status']")])],
            queries=[q("suggestions", "[data-hook='suggestion']", "texts"), q("box_hidden", "[data-hook='english-suggestions']", "hidden")])
        self.assertFalse(out["final"]["box_hidden"])
        self.assertIn('Try: "won at least 3 of the last 5 meetings"', out["final"]["suggestions"][0])
        cap = out["captures"]["add"]
        self.assertEqual(cap["input"], self.TEXT + ". won at least 3 of the last 5 meetings.")
        self.assertEqual(cap["count"], f"{len(cap['input'])} / 600")
        self.assertIn("Press Read my strategy", cap["status"])
        # the wording it added really does read in full
        res = parser.parse("won at least 3 of the last 5 meetings", players=[])
        self.assertEqual(res["not_understood"], [])

    def test_the_things_the_rules_do_not_have_are_said_plainly(self):
        text = "bet teams with a better starting pitcher and fewer injuries"
        out = build(routes_for(text), actions=read_actions(text), queries=[
            q("suggestions", "[data-hook='suggestion']", "texts"), q("buttons", "[data-hook='suggest-add']", "count")])
        self.assertTrue(any("not available to the rules yet" in s for s in out["final"]["suggestions"]))
        self.assertEqual(out["final"]["buttons"], 0)               # nothing to add: it is not on the menu

    def test_a_fully_read_text_has_no_suggestion_box(self):
        text = "Bet home underdogs between +120 and +200"
        out = build(routes_for(text), actions=read_actions(text), queries=[q("box_hidden", "[data-hook='english-suggestions']", "hidden")])
        self.assertTrue(out["final"]["box_hidden"])

    def test_a_matchup_condition_added_by_hand_shows_the_menus_note_about_its_data(self):
        out = build(actions=[dict(do="click", sel="[data-hook='blank-rule']", wait=100),
                             dict(do="set", sel="[data-hook='add-condition']", value="head_to_head", wait=100)],
                    queries=[q("conds", "[data-hook='condition']", "attrs", attr="data-cond"), q("note", "[data-hook='cond-note']", "texts")])
        self.assertEqual(out["final"]["conds"], ["head_to_head"])
        self.assertIn("held back", out["final"]["note"][0])

    def test_the_greyed_out_send_button_says_why(self):
        both = [q("hint", "[data-hook='save-hint']"), q("btn", "[data-hook='build-submit']", "disabled")]
        out = build(base_routes(), captureInitial=both, actions=[dict(do="click", sel="[data-hook='blank-rule']", wait=100, label="blank", capture=both)])
        first = out["captures"]["initial"]
        self.assertTrue(first["btn"])
        self.assertIn("wakes up once your strategy is read", first["hint"])
        self.assertEqual(out["captures"]["blank"], {"hint": "", "btn": False})


@unittest.skipUnless(HAS_NODE, "node not installed")
class RemoveFromMyKennelInTheBuilder(unittest.TestCase):
    def routes(self, **over):
        mine = {"hounds": [dog("u-1", "Dog One"), dog("u-2", "Dog Two", version_no=3)], "limit_running": 3}
        after = {"hounds": [dog("u-2", "Dog Two", version_no=3)], "limit_running": 3}
        r = base_routes(**{"/hounds/mine": [200, mine], "POST /hounds/u-1/retire": [200, {"hound": dog("u-1", "Dog One", status="retired")}]})
        r.update(over)
        return r, after

    def test_remove_asks_first_retires_says_so_and_drops_the_dog_from_the_list(self):
        routes, after = self.routes()
        out = build(routes, **SIGNED, switchAfter={"/hounds/mine": [1, [200, after]]}, actions=[
            dict(do="click", sel="[data-hook='remove-dog']", index=0, wait=250, label="remove",
                 capture=[q("msg", "[data-hook='build-message']"), q("names", "[data-hook='my-dog'] .bd-dogrow__name a", "texts"),
                          q("limit", "[data-hook='limit-text']")])])
        self.assertEqual(len(out["confirms"]), 1)
        ask = out["confirms"][0]
        self.assertIn("Remove Dog One from your kennel?", ask)
        self.assertIn("record stay on the ledger", ask)
        self.assertIn("Retired by the owner", ask)
        self.assertIn("cannot be undone", ask)
        retire = posts_to(out, "/hounds/u-1/retire")
        self.assertEqual(len(retire), 1)
        self.assertEqual(retire[0]["body"], {})                         # no words needed
        cap = out["captures"]["remove"]
        self.assertEqual(cap["names"], ["Dog Two"])
        self.assertIn("Dog One was removed from your kennel", cap["msg"])
        self.assertIn("tickets and record stay on the ledger", cap["msg"])
        self.assertEqual(cap["limit"], "1 of 5 hounds running.")

    def test_saying_no_removes_nothing(self):
        routes, _ = self.routes()
        out = build(routes, **SIGNED, confirm=False, actions=[dict(do="click", sel="[data-hook='remove-dog']", index=0, wait=150)],
                    queries=[q("names", "[data-hook='my-dog'] .bd-dogrow__name a", "texts"), q("msg", "[data-hook='build-message']")])
        self.assertEqual(len(out["confirms"]), 1)
        self.assertEqual(posts_to(out, "/hounds/u-1/retire"), [])
        self.assertEqual(out["final"]["names"], ["Dog One", "Dog Two"])
        self.assertEqual(out["final"]["msg"], "")

    def test_a_refused_removal_is_said_and_the_dog_stays(self):
        routes, _ = self.routes(**{"POST /hounds/u-1/retire": [429, {"detail": {"error": "rate_limited", "retry_after": 10}}]})
        out = build(routes, **SIGNED, actions=[dict(do="click", sel="[data-hook='remove-dog']", index=0, wait=200)],
                    queries=[q("names", "[data-hook='my-dog'] .bd-dogrow__name a", "texts"), q("err", "[data-hook='build-server-error']"),
                             q("err_hidden", "[data-hook='build-server-error']", "hidden")])
        self.assertFalse(out["final"]["err_hidden"])
        self.assertIn("lot of tries", out["final"]["err"])
        self.assertEqual(out["final"]["names"], ["Dog One", "Dog Two"])

    def test_removing_the_dog_being_edited_returns_to_a_new_dog(self):
        routes, after = self.routes()
        out = build(routes, **SIGNED, switchAfter={"/hounds/mine": [1, [200, after]]}, actions=[
            dict(do="click", sel="[data-hook='edit-dog']", index=0, wait=200),
            dict(do="click", sel="[data-hook='remove-dog']", index=0, wait=250)],
            queries=[q("title", "[data-hook='build-title']"), q("btn", "[data-hook='build-submit']"), q("msg", "[data-hook='build-message']")])
        self.assertEqual(out["final"]["title"], "Build your hound")
        self.assertTrue(out["final"]["btn"].startswith("Keep "))
        self.assertIn("was removed from your kennel", out["final"]["msg"])

    def test_every_dog_row_has_both_buttons(self):
        routes, _ = self.routes()
        out = build(routes, **SIGNED, queries=[q("edit", "[data-hook='edit-dog']", "count"), q("remove", "[data-hook='remove-dog']", "texts")])
        self.assertEqual(out["final"]["edit"], 2)
        self.assertEqual(out["final"]["remove"], ["Remove from my kennel"] * 2)


@unittest.skipUnless(HAS_NODE, "node not installed")
class AClassicDogOpensAndSavesInTheBuilder(unittest.TestCase):
    """A version-1 dog is listed by the server as its equivalent rule set (upgrade_v1); the page edits that and saves a version."""

    def classic_dog(self):
        classic = user_spec.validate_spec(spec_dict(name="Old Strategy", side_rule="underdog", markets=["moneyline", "spread"],
                                                    price_min=100, price_max=250, min_books=4, lock_minutes=60, max_bets_per_day=3))
        self.assertEqual(classic["version"], 1)
        draft = user_spec.upgrade_v1(classic)
        row = dog("u-9", "Old Strategy")
        row.update(spec=json.loads(json.dumps(draft)), rule_sentences=render.rule_sentences(draft) + render.global_sentences(draft),
                   custom_rules=False)
        return row

    def test_it_opens_with_its_rules_in_the_cards_and_saves_as_the_next_version(self):
        row = self.classic_dog()
        diff = {"changes": [{"what": "Rule 1 changed", "before": "a", "after": "b"}], "paper_only": True}
        saved = {"hound": {"id": "u-9b", "name": "Old Strategy", "version_no": 2}, "previous_id": "u-9", "changes": diff["changes"], "paper_only": True}
        routes = base_routes(**{"/hounds/mine": [200, {"hounds": [row], "limit_running": 3}], "POST /hounds/u-9/diff": [200, diff],
                                "POST /hounds/u-9/version": [200, saved]})
        out = build(routes, **SIGNED, actions=[
            dict(do="click", sel="[data-hook='edit-dog']", wait=250, label="edit", capture=[
                q("title", "[data-hook='build-title']"), q("cards", "[data-hook='rule-card']", "count"),
                q("conds", "[data-hook='condition']", "attrs", attr="data-cond"), q("pmin", "[data-hook='price-min']", "value"),
                q("pmax", "[data-hook='price-max']", "value"), q("books", "[data-hook='min-books']", "value"), q("bets", "[data-hook='g-bets']", "value")]),
            dict(do="set", sel="[data-hook='min-books']", value="5", wait=60),
            dict(do="click", sel="[data-hook='build-submit']", wait=200),
            dict(do="click", sel="[data-hook='build-submit']", wait=200, label="save", capture=[q("msg", "[data-hook='build-message']")])])
        edit = out["captures"]["edit"]
        self.assertEqual(edit["title"], "Edit Old Strategy")
        self.assertEqual(edit["cards"], 1)                                 # moneyline + spread are ONE rule with the underdog condition
        self.assertEqual(edit["conds"], ["role"])
        self.assertEqual((edit["pmin"], edit["pmax"], edit["books"], edit["bets"]), ("100", "250", "4", "3"))
        version = posts_to(out, "/hounds/u-9/version")
        self.assertEqual(len(version), 1)
        spec = user_spec.validate_spec(version[0]["body"]["spec"])         # the REAL validator accepts what the page posted
        self.assertEqual(spec["version"], 2)
        self.assertEqual(spec["rules"][0]["markets"], ["moneyline", "spread"])
        self.assertEqual(spec["rules"][0]["when"]["items"], [{"id": "role", "value": "underdog"}])
        self.assertEqual((spec["rules"][0]["min_books"], spec["name"], spec["lock_minutes"], spec["max_bets_per_day"]), (5, "Old Strategy", 60, 3))
        self.assertEqual(posts_to(out, "/hounds"), [])
        self.assertIn("Saved as version 2", out["captures"]["save"]["msg"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheKennelRemoveAndEdit(unittest.TestCase):
    CARDS = "[data-hook='kennel-dog']"

    def kennel(self, dogs):
        return [200, {"handle": "handler-21e8", "display": "Handler 21E8", "dog_count": len(dogs), "dogs": dogs, "removed_count": 0,
                      "season": {"id": "s2", "label": "Season 2"}, "paper_only": True}]

    def dogs(self, *ids):
        names = {"u-1": "Underdog Gus", "u-2": "Totals Tina"}
        out = []
        for i in ids:
            out.append({"id": i, "name": names[i], "tagline": "", "status": "running", "version_no": 1, "look": None, "sports": ["mlb"],
                        "record": {"bets": 0, "wins": 0, "losses": 0, "pushes": 0, "units_average_price": None}, "settled": 0,
                        "open_bets": 0, "new": True, "last_pick": None, "page_href": f"hound.html?id={i}", "retired": False,
                        "builder_href": f"build-a-hound.html?from={i}",
                        "bankroll": {"start": 1000.0, "current": 1000.0, "pnl_usd": 0.0, "return_pct": 0.0, "units_total": 0.0, "bets": 0,
                                     "settled": 0, "small_sample": True, "small_sample_min": 20, "basis": "average_price"}})
        return out

    def routes(self, **over):
        from tests.test_kennel_page import kit
        r = {"/hounds/kennels/mine": self.kennel(self.dogs("u-1", "u-2")), "/hounds/builder/menu": [200, MENU],
             "/hounds/mine": [200, {"hounds": [], "limit_running": 3}], "/hounds/u-1/kit": [200, kit("u-1")],
             "POST /hounds/u-1/retire": [200, {"hound": {"id": "u-1", "status": "retired"}}]}
        r.update(over)
        return r

    def test_a_remove_button_on_every_card_asks_retires_and_redraws_the_kennel(self):
        out = run_page("kennel", routes=self.routes(), **SIGNED, switchAfter={"/hounds/kennels/mine": [1, self.kennel(self.dogs("u-2"))]}, actions=[
            dict(do="click", sel="[data-hook='dog-action-remove']", index=0, wait=300, label="gone", capture=[
                q("names", f"{self.CARDS} [data-hook='dog-name']", "texts"), q("status", "[data-hook='kennel-status']")])],
            queries=[q("buttons", "[data-hook='dog-action-remove']", "count")])
        self.assertEqual(len(out["confirms"]), 1)
        self.assertIn("Remove Underdog Gus from your kennel?", out["confirms"][0])
        self.assertEqual(posts_to_url(out, "/hounds/u-1/retire"), 1)
        cap = out["captures"]["gone"]
        self.assertEqual(cap["names"], ["Totals Tina"])
        self.assertIn("Underdog Gus was removed from your kennel", cap["status"])
        self.assertEqual(out["final"]["buttons"], 1)

    def test_cancelling_leaves_the_kennel_alone(self):
        out = run_page("kennel", routes=self.routes(), **SIGNED, confirm=False, actions=[
            dict(do="click", sel="[data-hook='dog-action-remove']", index=0, wait=200)],
            queries=[q("names", f"{self.CARDS} [data-hook='dog-name']", "texts"), q("status", "[data-hook='kennel-status']")])
        self.assertEqual(posts_to_url(out, "/hounds/u-1/retire"), 0)
        self.assertEqual(out["final"], {"names": ["Underdog Gus", "Totals Tina"], "status": ""})

    def test_a_failed_removal_is_said_and_the_card_stays(self):
        routes = self.routes(**{"POST /hounds/u-1/retire": [500, {"detail": "boom"}]})
        out = run_page("kennel", routes=routes, **SIGNED, actions=[dict(do="click", sel="[data-hook='dog-action-remove']", index=0, wait=200)],
                       queries=[q("names", f"{self.CARDS} [data-hook='dog-name']", "texts"), q("status", "[data-hook='kennel-status']"),
                                q("kind", "[data-hook='kennel-status']", "attr", attr="data-kind")])
        self.assertEqual(out["final"]["names"], ["Underdog Gus", "Totals Tina"])
        self.assertIn("could not be removed", out["final"]["status"])
        self.assertEqual(out["final"]["kind"], "error")

    def test_the_studio_has_a_remove_button_for_the_open_dog_and_a_new_dog_has_none(self):
        out = run_page("kennel", routes=self.routes(), **SIGNED,
                       switchAfter={"/hounds/kennels/mine": [1, self.kennel(self.dogs("u-2"))]}, actions=[
            dict(do="click", sel="[data-hook='dog-avatar']", index=0, wait=250, label="open", capture=[
                q("hidden", "[data-hook='studio-remove']", "hidden"), q("label", "[data-hook='studio-remove']")]),
            dict(do="click", sel="[data-hook='studio-remove']", wait=300, label="removed", capture=[
                q("studio_hidden", "[data-hook='studio']", "hidden"), q("names", f"{self.CARDS} [data-hook='dog-name']", "texts")])])
        self.assertEqual(out["captures"]["open"], {"hidden": False, "label": "Remove from my kennel"})
        self.assertEqual(posts_to_url(out, "/hounds/u-1/retire"), 1)
        self.assertEqual(out["captures"]["removed"], {"studio_hidden": True, "names": ["Totals Tina"]})
        out = run_page("kennel", routes=self.routes(**{"/hounds/kennels/mine": self.kennel([])}), **SIGNED, actions=[
            dict(do="click", sel="[data-hook='kennel-empty-build']", wait=200)], queries=[q("hidden", "[data-hook='studio-remove']", "hidden")])
        self.assertTrue(out["final"]["hidden"])

    def test_edit_that_cannot_open_says_why_and_offers_a_retry_instead_of_sign_in_again(self):
        # the rule menu never loads: the old page said "Sign in again to edit this dog."
        routes = self.routes(**{"/hounds/builder/menu": [500, {"detail": "down"}]})
        out = run_page("kennel", routes=routes, **SIGNED, settleMs=200, actions=[
            dict(do="click", sel="[data-hook='dog-action-edit']", index=0, wait=500, label="edit", capture=[
                q("problem", "[data-hook='studio-edit-problem']"), q("retry", "[data-hook='studio-edit-retry']", "count")])])
        cap = out["captures"]["edit"]
        self.assertIn("The rule builder did not load", cap["problem"])
        self.assertNotIn("Sign in again", cap["problem"])
        self.assertEqual(cap["retry"], 1)

    def test_try_again_fetches_the_menu_again_and_opens_the_dog(self):
        from tests.test_hounds_builder_web import dog as builder_dog
        mine = {"hounds": [builder_dog("u-1", "Underdog Gus")], "limit_running": 3}
        routes = self.routes(**{"/hounds/builder/menu": [500, {"detail": "down"}], "/hounds/mine": [200, mine],
                                "POST /hounds/builder/preview": [200, preview_answer()]})
        out = run_page("kennel", routes=routes, **SIGNED, settleMs=200, switchAfter={"/hounds/builder/menu": [1, [200, MENU]]}, actions=[
            dict(do="click", sel="[data-hook='dog-action-edit']", index=0, wait=500, label="edit", capture=[
                q("retry", "[data-hook='studio-edit-retry']", "count")]),
            dict(do="click", sel="[data-hook='studio-edit-retry']", wait=700, label="again", capture=[
                q("title", "[data-hook='build-title']"), q("problem", "[data-hook='studio-edit-problem']", "count"),
                q("go", "[data-hook='english-go']", "disabled")])])
        self.assertEqual(out["captures"]["edit"]["retry"], 1)
        self.assertEqual(out["captures"]["again"], {"title": "Edit Underdog Gus", "problem": 0, "go": False})
        self.assertEqual(len([g for g in out["gets"] if g.endswith("/hounds/builder/menu")]), 2)

    def test_a_lapsed_token_in_edit_says_sign_in_with_a_link(self):
        routes = self.routes(**{"/hounds/mine": [401, {"detail": "no"}]})
        out = run_page("kennel", routes=routes, **SIGNED, settleMs=200, actions=[
            dict(do="click", sel="[data-hook='dog-action-edit']", index=0, wait=500, label="edit", capture=[
                q("problem", "[data-hook='studio-edit-problem']"), q("link", "[data-hook='studio-edit-problem'] a", "attr", attr="href")])])
        self.assertIn("sign-in has lapsed", out["captures"]["edit"]["problem"])
        self.assertEqual(out["captures"]["edit"]["link"], "index.html#/signin")

    def test_a_dog_missing_from_the_builders_list_says_so(self):
        out = run_page("kennel", routes=self.routes(), **SIGNED, settleMs=200, actions=[
            dict(do="click", sel="[data-hook='dog-action-edit']", index=0, wait=500, label="edit", capture=[q("problem", "[data-hook='studio-edit-problem']")])])
        self.assertIn("could not be found in your list", out["captures"]["edit"]["problem"])


def posts_to_url(out, suffix):
    return len([p for p in out["posts"] if p["url"].endswith(suffix)])


@unittest.skipUnless(HAS_NODE, "node not installed")
class AnOwnerRemovedDogsPageSaysSo(unittest.TestCase):
    """The dog's address still opens after a removal (the ledger keeps its record) and says who retired it."""

    def page(self, cause):
        from tests import hounds_web_fixtures as WF
        from tests.test_hounds_board_pages import routes as board_routes
        d = dict(WF.detail("closer"), status="retired", retired={"date": "2026-10-20", "cause": cause})
        return run_page("hound", routes=board_routes(**{"/hounds/closer": [200, d]}), search="?id=closer", queries=[
            q("cause", "[data-hook='hound-cause']"), q("stays", "[data-hook='retired-record-stays']", "count"),
            q("status", "[data-hook='hound-status']"), q("name", "[data-hook='hound-name']")])

    def test_the_page_says_retired_by_the_owner_and_that_the_record_stays(self):
        f = self.page("retired by the owner")["final"]
        self.assertIn("Retired by the owner.", f["cause"])
        self.assertIn("Its tickets and record stay on the ledger.", f["cause"])
        self.assertEqual(f["stays"], 1)
        self.assertTrue(f["name"])                                   # the page opens: nothing was deleted

    def test_a_moderators_retirement_and_a_rule_retirement_do_not_claim_the_owner_did_it(self):
        for cause in ("retired by a moderator: name complaint", "down more than 25 units"):
            f = self.page(cause)["final"]
            self.assertNotIn("Retired by the owner", f["cause"], cause)
            self.assertEqual(f["stays"], 0, cause)


if __name__ == "__main__":
    unittest.main()
