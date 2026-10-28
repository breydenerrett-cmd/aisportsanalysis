"""The kennel studio's Ask tab as a conversation (web/js/dog-chat.js, wired in web/js/kennel.js), run for real under node.

Owner request 2026-10-28: talk to the hound in chat bubbles, with the history showing, and change its rules from the conversation.

  the thread   the member's lines on the right, the hound's on the left with its own face; the saved history is there on open
  the card     a proposed change is Before and After in words with Apply and Cancel; Apply posts, marks the card, hands the kennel the next
               version's id and keeps the conversation going; Cancel posts and changes nothing
  the box      send posts the message and draws both lines; a refusal puts the words back; no chat available says so and disables the box;
               Clear chat asks a second time before it deletes
  who          only the OWNER of a member hound gets it; anyone else, and a server with no chat, keep the computed Ask

Skipped without node. The server half is tests/test_hounds_chat.py.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from src.hounds import user_spec
from tests.hounds_web_runner import HAS_NODE, WEB, run_page
from tests.test_kennel_page import SIGNED, dog, kit, mine, q

REPO = Path(__file__).resolve().parent.parent
MENU = json.loads(json.dumps(user_spec.builder_menu()))

CARD = {"status": "pending", "request": "bet fewer games a day", "rule_after": "At most 1 bet a day.",
        "changes": [{"what": "Most bets a day", "before": "2", "after": "1"}, {"what": "Stake", "before": "1 paper unit", "after": "2 paper units"}]}
HISTORY = [
    {"id": 11, "role": "member", "text": "Bet fewer games a day", "created_at": "2026-10-28T20:00:00Z", "version_no": 1, "proposal": None},
    {"id": 12, "role": "hound", "text": "I'd cut it to one bet a day and double the stake.\nTap Apply to make it so.", "created_at": "2026-10-28T20:00:05Z",
     "version_no": 1, "proposal": CARD},
]
LIMITS = {"limit_per_day": 20, "used_today": 3, "left_today": 17, "paid": False, "message_max_chars": 500}


def chat_state(**over):
    out = {"hound": {"id": "u-1", "root_id": "u-1", "name": "Underdog Gus", "version_no": 1, "status": "running", "style": "rules", "can_edit": True,
                     "edit_note": ""},
           "available": True, "reason": None, "messages": HISTORY, "limits": LIMITS, "window": 20, "paper_only": True}
    out.update(over)
    return out


def routes(chat=None, dogs=None, **over):
    r = {"/hounds/kennels/mine": mine(dogs or [dog("u-1")]), "/hounds/builder/menu": [200, MENU],
         "/hounds/mine": [200, {"hounds": [], "limit_running": 3}], "/hounds/u-1/kit": [200, kit("u-1")],
         "/hounds/u-1/ask": [200, {"greeting": ["Woof. Ask me about my bets."], "suggestions": ["Why that pick?"]}],
         "/hounds/u-1/chat": [200, chat if chat is not None else chat_state()]}
    r.update(over)
    return r


OPEN = [dict(do="click", sel="[data-hook='dog-avatar']", label="open", wait=120)]


def open_ask(extra=(), **kw):
    actions = OPEN + [dict(do="click", sel="[role='tab'][data-tab='ask']", label="ask", wait=300, capture=kw.pop("capture", []))] + list(extra)
    return run_page("kennel", routes=kw.pop("routes", routes()), **SIGNED, actions=actions, **kw)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheThread(unittest.TestCase):
    def test_the_owner_gets_the_conversation_with_the_saved_history_showing(self):
        out = open_ask(capture=[
            q("selected", "[role='tab'][aria-selected='true']", "texts"), q("you", "[data-hook='chat-you-text']", "texts"),
            q("hound", "[data-hook='chat-hound-text'] .dc-line", "texts"), q("faces", "[data-hook='chat-face'] svg", "count"),
            q("rows_you", "[data-hook='chat-you']", "count"), q("rows_hound", "[data-hook='chat-hound']", "count"),
            q("classic", "[data-hook='ask-thread']", "count"), q("clear", "[data-hook='chat-clear']"),
            q("allowance", "[data-hook='chat-allowance']"), q("input", "[data-hook='chat-input']", "disabled")])
        cap = out["captures"]["ask"]
        self.assertEqual(cap["selected"], ["Ask"])
        self.assertEqual(cap["you"], ["Bet fewer games a day"])
        self.assertEqual(cap["hound"], ["I'd cut it to one bet a day and double the stake.", "Tap Apply to make it so."])
        self.assertEqual((cap["rows_you"], cap["rows_hound"], cap["faces"]), (1, 1, 1), "the hound's line carries its face, the member's does not")
        self.assertEqual(cap["classic"], 0, "the computed Ask is not drawn under the conversation")
        self.assertEqual(cap["clear"], "Clear chat")
        self.assertEqual(cap["allowance"], "17 of 20 messages left today")
        self.assertFalse(cap["input"])
        self.assertEqual([g for g in out["gets"] if g.endswith("/chat")], ["/hounds/u-1/chat"], "one read of the saved conversation on open")

    def test_the_members_lines_sit_on_the_right_and_the_hounds_on_the_left(self):
        out = open_ask(capture=[q("you", "[data-hook='chat-you']", "attrs", attr="class"), q("hound", "[data-hook='chat-hound']", "attrs", attr="class")])
        cap = out["captures"]["ask"]
        self.assertIn("dc-row--you", cap["you"][0])
        self.assertIn("dc-row--hound", cap["hound"][0])
        css = (WEB / "css" / "dog-kit.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.dc-row--you \{ justify-content: flex-end; \}")
        self.assertRegex(css, r"\.dc-thread \{[^}]*overflow-y: auto")

    def test_an_empty_history_opens_with_the_hounds_hello(self):
        out = open_ask(routes=routes(chat=chat_state(messages=[])), capture=[q("hound", "[data-hook='chat-hound-text']", "texts"),
                                                                              q("chips", "[data-hook='chat-chip']", "texts")])
        cap = out["captures"]["ask"]
        self.assertIn("Hi, I'm Underdog Gus", cap["hound"][0])
        self.assertIn("nothing changes until you tap Apply", cap["hound"][0])
        self.assertEqual(cap["chips"], ["How am I doing?", "Why did you take your last bet?", "Explain my rule", "Bet fewer games a day"])

    def test_a_proposed_change_is_a_card_with_before_and_after_and_two_buttons(self):
        out = open_ask(capture=[
            q("status", "[data-hook='chat-proposal']", "attr", attr="data-status"), q("what", "[data-hook='chat-change'] strong", "texts"),
            q("before", "[data-hook='chat-before']", "texts"), q("after", "[data-hook='chat-after']", "texts"),
            q("apply", "[data-hook='chat-apply']"), q("cancel", "[data-hook='chat-cancel']"), q("rule", ".dc-card__rule p")])
        cap = out["captures"]["ask"]
        self.assertEqual(cap["status"], "pending")
        self.assertEqual(cap["what"], ["Most bets a day", "Stake"])
        self.assertEqual(cap["before"], ["Before 2", "Before 1 paper unit"])
        self.assertEqual(cap["after"], ["After 1", "After 2 paper units"])
        self.assertEqual((cap["apply"], cap["cancel"]), ("Apply", "Cancel"))
        self.assertEqual(cap["rule"], "At most 1 bet a day.")

    def test_a_card_that_was_already_settled_has_no_buttons(self):
        for status, word in (("applied", "Applied"), ("cancelled", "Cancelled"), ("replaced", "Replaced"), ("stale", "Out of date")):
            history = [dict(HISTORY[1], proposal=dict(CARD, status=status, applied={"version_no": 2}))]
            out = open_ask(routes=routes(chat=chat_state(messages=history)), capture=[q("buttons", "[data-hook='chat-apply']", "count"),
                                                                                   q("result", "[data-hook='chat-proposal-status']")])
            with self.subTest(status=status):
                self.assertEqual(out["captures"]["ask"]["buttons"], 0)
                self.assertIn(word, out["captures"]["ask"]["result"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheBox(unittest.TestCase):
    REPLY = {"messages": [{"id": 21, "role": "member", "text": "How am I doing?", "created_at": "x", "version_no": 1, "proposal": None},
                          {"id": 22, "role": "hound", "text": "I have 2 settled bets, so it is too early to say much.", "created_at": "x", "version_no": 1, "proposal": None}],
             "hound": {"id": "u-1", "name": "Underdog Gus", "version_no": 1}, "limits": dict(LIMITS, used_today=4, left_today=16)}

    def test_send_posts_the_message_and_draws_both_lines(self):
        out = open_ask(routes=routes(**{"POST /hounds/u-1/chat": [200, self.REPLY]}), extra=[
            dict(do="set", sel="[data-hook='chat-input']", value="How am I doing?", label="typed", wait=10),
            dict(do="click", sel="[data-hook='chat-send']", label="sent", wait=200, capture=[
                q("you", "[data-hook='chat-you-text']", "texts"), q("hound", "[data-hook='chat-hound-text']", "texts"),
                q("typing", "[data-hook='chat-typing']", "count"), q("input", "[data-hook='chat-input']", "value"),
                q("allowance", "[data-hook='chat-allowance']")])])
        cap = out["captures"]["sent"]
        self.assertEqual([p["body"] for p in out["posts"] if p["url"].endswith("/chat")], [{"message": "How am I doing?"}])
        self.assertEqual(cap["you"][-1], "How am I doing?")
        self.assertIn("2 settled bets", cap["hound"][-1])
        self.assertEqual(cap["typing"], 0)
        self.assertEqual(cap["input"], "")
        self.assertEqual(cap["allowance"], "16 of 20 messages left today")

    def test_enter_sends_and_a_suggestion_chip_sends_its_words(self):
        out = open_ask(routes=routes(chat=chat_state(messages=[]), **{"POST /hounds/u-1/chat": [200, self.REPLY]}), extra=[
            dict(do="click", sel="[data-hook='chat-chip']", index=2, label="chip", wait=200)])
        self.assertEqual([p["body"] for p in out["posts"] if p["url"].endswith("/chat")], [{"message": "Explain my rule"}])

    def test_an_empty_message_is_not_sent(self):
        out = open_ask(extra=[dict(do="click", sel="[data-hook='chat-send']", label="empty", wait=60, capture=[q("status", "[data-hook='chat-status']")])])
        self.assertEqual(out["captures"]["empty"]["status"], "Type a message first.")
        self.assertEqual([p for p in out["posts"] if p["url"].endswith("/chat")], [])

    def test_a_refusal_shows_the_servers_words_and_puts_the_message_back(self):
        refused = [429, {"detail": {"error": "daily_limit", "message": "You have used today's 20 messages. They come back tomorrow."}}]
        out = open_ask(routes=routes(**{"POST /hounds/u-1/chat": refused}), extra=[
            dict(do="set", sel="[data-hook='chat-input']", value="one more", label="typed", wait=10),
            dict(do="click", sel="[data-hook='chat-send']", label="sent", wait=200, capture=[
                q("status", "[data-hook='chat-status']"), q("input", "[data-hook='chat-input']", "value"), q("typing", "[data-hook='chat-typing']", "count"),
                q("you", "[data-hook='chat-you']", "count"), q("disabled", "[data-hook='chat-input']", "disabled"), q("note", "[data-hook='chat-unavailable']")])])
        cap = out["captures"]["sent"]
        self.assertIn("20 messages", cap["status"])
        self.assertEqual((cap["input"], cap["typing"], cap["you"]), ("one more", 0, 1), "the half-sent line is gone and the words are the member's again")
        self.assertTrue(cap["disabled"])
        self.assertIn("They come back tomorrow", cap["note"])

    def test_chat_that_cannot_answer_says_so_keeps_the_history_and_disables_the_box(self):
        state = chat_state(available=False, reason="Chat is unavailable right now. Try again later.")
        out = open_ask(routes=routes(chat=state), capture=[
            q("note", "[data-hook='chat-unavailable']"), q("hidden", "[data-hook='chat-unavailable']", "hidden"), q("input", "[data-hook='chat-input']", "disabled"),
            q("send", "[data-hook='chat-send']", "disabled"), q("link", "[data-hook='chat-quick-link']", "attr", attr="href"),
            q("history", "[data-hook='chat-you-text']", "texts"), q("chips", "[data-hook='chat-suggestions']", "hidden")])
        cap = out["captures"]["ask"]
        self.assertIn("Chat is unavailable right now", cap["note"])
        self.assertFalse(cap["hidden"])
        self.assertTrue(cap["input"] and cap["send"] and cap["chips"])
        self.assertEqual(cap["link"], "hound.html?id=u-1&tab=ask")
        self.assertEqual(cap["history"], ["Bet fewer games a day"])

    def test_with_no_messages_left_the_box_is_off_and_says_when_they_come_back(self):
        out = open_ask(routes=routes(chat=chat_state(limits=dict(LIMITS, used_today=20, left_today=0))), capture=[
            q("note", "[data-hook='chat-unavailable']"), q("input", "[data-hook='chat-input']", "disabled"), q("allowance", "[data-hook='chat-allowance']")])
        cap = out["captures"]["ask"]
        self.assertIn("come back tomorrow", cap["note"])
        self.assertTrue(cap["input"])
        self.assertEqual(cap["allowance"], "0 of 20 messages left today")

    def test_clear_chat_asks_a_second_time_then_deletes_and_goes_back_to_the_hello(self):
        out = open_ask(routes=routes(**{"DELETE /hounds/u-1/chat": [200, {"cleared": 2}]}), extra=[
            dict(do="click", sel="[data-hook='chat-clear']", label="first", wait=40, capture=[
                q("sure", "[data-hook='chat-clear-sure']", "hidden"), q("clear", "[data-hook='chat-clear']", "attr", attr="hidden")]),
            dict(do="click", sel="[data-hook='chat-clear-no']", label="keep", wait=40, capture=[q("sure", "[data-hook='chat-clear-sure']", "hidden"),
                                                                                                  q("you", "[data-hook='chat-you']", "count")]),
            dict(do="click", sel="[data-hook='chat-clear']", label="again", wait=40),
            dict(do="click", sel="[data-hook='chat-clear-yes']", label="yes", wait=120, capture=[
                q("you", "[data-hook='chat-you']", "count"), q("hello", "[data-hook='chat-hound-text']", "texts"), q("status", "[data-hook='chat-status']")])])
        self.assertEqual(out["captures"]["first"]["sure"], False)
        self.assertIsNotNone(out["captures"]["first"]["clear"])
        self.assertEqual((out["captures"]["keep"]["sure"], out["captures"]["keep"]["you"]), (True, 1))
        self.assertEqual([p["method"] for p in out["posts"] if p["url"].endswith("/chat")], ["DELETE"], "one delete, only after the second tap")
        cap = out["captures"]["yes"]
        self.assertEqual(cap["you"], 0)
        self.assertIn("Hi, I'm Underdog Gus", cap["hello"][0])
        self.assertEqual(cap["status"], "Chat cleared.")


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheCard(unittest.TestCase):
    NEXT = {"/hounds/u-1/chat/proposals/12/apply": [200, {
        "messages": [dict(HISTORY[1], proposal=dict(CARD, status="applied", applied={"hound_id": "u-2", "version_no": 2})),
                     {"id": 31, "role": "notice", "text": "Applied. Underdog Gus is now on version 2. The earlier version keeps its record.",
                      "created_at": "x", "version_no": 2, "proposal": None}],
        "hound": {"id": "u-2", "root_id": "u-1", "name": "Underdog Gus", "version_no": 2, "status": "running"}, "previous_id": "u-1"}]}

    def test_apply_posts_marks_the_card_and_hands_the_kennel_the_next_version(self):
        base = routes(**{"POST " + k: v for k, v in self.NEXT.items()})
        v2 = dog("u-2", name="Underdog Gus", version_no=2)
        v2["root_id"] = "u-1"
        out = run_page("kennel", routes=base, **SIGNED, switchAfter={"/hounds/kennels/mine": [1, mine([v2])]}, actions=OPEN + [
            dict(do="click", sel="[role='tab'][data-tab='ask']", label="ask", wait=300),
            dict(do="click", sel="[data-hook='chat-apply']", label="apply", wait=300, capture=[
                q("status", "[data-hook='chat-proposal']", "attr", attr="data-status"), q("result", "[data-hook='chat-proposal-status']"),
                q("buttons", "[data-hook='chat-apply']", "count"), q("notice", "[data-hook='chat-notice']"),
                q("version", "[data-hook='studio-version']"), q("selected", "[role='tab'][aria-selected='true']", "texts"),
                q("thread", "[data-hook='chat-you']", "count")])])
        cap = out["captures"]["apply"]
        self.assertEqual([p["url"] for p in out["posts"]], ["/hounds/u-1/chat/proposals/12/apply"])
        self.assertEqual(cap["status"], "applied")
        self.assertIn("Version 2 is running", cap["result"])
        self.assertEqual(cap["buttons"], 0)
        self.assertIn("now on version 2", cap["notice"])
        self.assertEqual(cap["version"], "v2", "the studio points at the next version")
        self.assertEqual((cap["selected"], cap["thread"]), (["Ask"], 1), "the conversation carries on in the same tab")
        mine_loads = [g for g in out["gets"] if g.endswith("/hounds/kennels/mine")]
        self.assertGreaterEqual(len(mine_loads), 2, "the kennel was read again after the apply")

    def test_after_an_apply_the_next_message_goes_to_the_new_version(self):
        base = routes(**{"POST " + k: v for k, v in self.NEXT.items()})
        base["POST /hounds/u-2/chat"] = [200, TheBox.REPLY]
        v2 = dog("u-2", name="Underdog Gus", version_no=2)
        out = run_page("kennel", routes=base, **SIGNED, switchAfter={"/hounds/kennels/mine": [1, mine([v2])]}, actions=OPEN + [
            dict(do="click", sel="[role='tab'][data-tab='ask']", label="ask", wait=300),
            dict(do="click", sel="[data-hook='chat-apply']", label="apply", wait=300),
            dict(do="set", sel="[data-hook='chat-input']", value="Did that work?", label="typed", wait=10),
            dict(do="click", sel="[data-hook='chat-send']", label="sent", wait=200)])
        self.assertEqual([p["url"] for p in out["posts"]], ["/hounds/u-1/chat/proposals/12/apply", "/hounds/u-2/chat"])

    def test_cancel_posts_and_changes_nothing_else(self):
        cancelled = {"messages": [dict(HISTORY[1], proposal=dict(CARD, status="cancelled")),
                                  {"id": 32, "role": "notice", "text": "Cancelled. No change was made.", "created_at": "x", "version_no": 1, "proposal": None}],
                     "hound": {"id": "u-1", "name": "Underdog Gus", "version_no": 1}}
        out = open_ask(routes=routes(**{"POST /hounds/u-1/chat/proposals/12/cancel": [200, cancelled]}), extra=[
            dict(do="click", sel="[data-hook='chat-cancel']", label="cancel", wait=200, capture=[
                q("status", "[data-hook='chat-proposal']", "attr", attr="data-status"), q("result", "[data-hook='chat-proposal-status']"),
                q("notice", "[data-hook='chat-notice']"), q("title", "[data-hook='studio-title']"), q("version", "[data-hook='studio-version']")])])
        cap = out["captures"]["cancel"]
        self.assertEqual([p["url"] for p in out["posts"]], ["/hounds/u-1/chat/proposals/12/cancel"])
        self.assertEqual((cap["status"], cap["version"], cap["title"]), ("cancelled", "v1", "Underdog Gus"))
        self.assertIn("No change was made", cap["notice"])
        self.assertEqual([g for g in out["gets"] if g.endswith("/hounds/kennels/mine")], ["/hounds/kennels/mine"], "no reload: nothing changed")

    def test_a_card_that_went_stale_says_so_and_loses_its_buttons(self):
        stale = [409, {"detail": {"error": "proposal_stale", "message": "That change was made for an earlier version. Ask again."}}]
        out = open_ask(routes=routes(**{"POST /hounds/u-1/chat/proposals/12/apply": stale}), extra=[
            dict(do="click", sel="[data-hook='chat-apply']", label="apply", wait=200, capture=[
                q("result", "[data-hook='chat-proposal-status']"), q("disabled", "[data-hook='chat-apply']", "disabled")])])
        cap = out["captures"]["apply"]
        self.assertIn("earlier version", cap["result"])
        self.assertTrue(cap["disabled"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class WhoGetsIt(unittest.TestCase):
    def test_a_server_with_no_chat_leaves_the_computed_ask_in_the_tab(self):
        r = routes()
        del r["/hounds/u-1/chat"]
        out = open_ask(routes=r, capture=[q("thread", "[data-hook='ask-thread']"), q("chat", "[data-hook='chat-thread']", "count")])
        self.assertIn("Ask me about my bets", out["captures"]["ask"]["thread"])
        self.assertEqual(out["captures"]["ask"]["chat"], 0)

    def test_someone_who_is_not_the_owner_never_asks_for_a_chat(self):
        r = routes(**{"/hounds/u-1/kit": [200, kit("u-1", is_owner=False)]})
        out = open_ask(routes=r, capture=[q("thread", "[data-hook='ask-thread']", "count"), q("chat", "[data-hook='chat-thread']", "count")])
        self.assertEqual((out["captures"]["ask"]["thread"], out["captures"]["ask"]["chat"]), (1, 0))
        self.assertEqual([g for g in out["gets"] if g.endswith("/chat")], [])

    def test_the_hound_page_keeps_the_computed_ask(self):
        source = (WEB / "js" / "hounds-detail.js").read_text(encoding="utf-8") + (WEB / "js" / "dog-kit.js").read_text(encoding="utf-8")
        self.assertNotIn("dog-chat", source)


class StaticChecks(unittest.TestCase):
    def test_the_kennel_wires_the_chat_and_keeps_the_computed_ask_as_the_fallback(self):
        source = (WEB / "js" / "kennel.js").read_text(encoding="utf-8")
        self.assertIn('import { bootChat } from "./dog-chat.js";', source)
        self.assertIn('import { bootAsk } from "./dog-ask.js";', source)
        self.assertRegex(source, r"if \(!chatting\) await bootAsk")
        self.assertRegex(source, r"onApplied: afterChatApply")

    def test_the_page_script_never_names_a_model_a_key_or_an_endpoint_outside_the_chat_routes(self):
        source = (WEB / "js" / "dog-chat.js").read_text(encoding="utf-8")
        code = re.sub(r"/\*.*?\*/", " ", source, flags=re.S).lower()
        for needle in ("anthropic", "haiku", "api_key", "sk-"):
            self.assertNotIn(needle, code, needle)
        for path in re.findall(r"`(/hounds/[^`]*)`", source):
            self.assertIn("/chat", path)


if __name__ == "__main__":
    unittest.main()
