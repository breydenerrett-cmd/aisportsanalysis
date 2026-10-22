"""The review of a training and Retune me, run for real under node against the pages' own HTML (tests/hounds_web_harness.mjs).

  * REVIEW   every training shows the proposal first: each change old -> new with its reason, a tick on each, what today's board says,
             and Apply / Veto / Tweak. Nothing is written until Apply: the page posts the proposal (read only) and then, only after Apply,
             the training with the ids still ticked.
  * VETO     posts the veto and nothing else; the sheet says nothing was changed and it does not count.
  * UNTICK   a cleared tick is left out of the apply; with every tick cleared Apply cannot be pressed.
  * TWEAK    a box for "why, or what instead", a second proposal request carrying the words and the round, and a revised list.
  * RETUNE   the Ask answer's "Retune me" button exists only when the server sent one (it sends it to the owner alone), and starts the
             same review from the owner's own lines in the chat.
  * ESCAPING what the owner typed is drawn as text, never as markup.

The proposal payloads are made by the real Python (training.review over a temp database), so a drift between the server and the page
fails here and not in front of a member. Skipped when node is not installed.
"""

from __future__ import annotations

import copy
import json
import re
import unittest

from tests.hounds_web_runner import HAS_NODE, run_page
from tests import test_hounds_interact_web as interact_web
from tests import test_hounds_rites_web as rites_web
from tests.test_hounds_retune import OWNER_LINE

HID, Payloads, dog_routes, hook, page, q = (interact_web.HID, interact_web.Payloads, interact_web.dog_routes, interact_web.hook,
                                            interact_web.page, interact_web.q)
click, payloads, kennel_routes, dog, SIGNED = rites_web.click, rites_web.payloads, rites_web.kennel_routes, rites_web.dog, rites_web.SIGNED

OPEN = "[data-hook='dog-action-train']"
BANNED = re.compile(r"\b(better|improve\w*|stronger|smarter|profit\w*|will win|edge|bet check|dogs?)\b", re.I)


def reviewed(proposal=None, **over):
    routes = kennel_routes([dog("u-1")])
    if proposal is not None:
        routes["POST /hounds/u-1/train/propose"] = [200, proposal]
    routes.update(over)
    return routes


def sent(post):
    """What a post carried, without the transport details (headers, method)."""
    return {"url": post["url"], "body": post["body"]}


def flow(routes, actions, **kw):
    return run_page("kennel", routes=routes, **SIGNED, reducedMotion=True, actions=actions, **kw)


def review_caps():
    return [q("kind", ".rt-sheet", "attr", attr="data-hook"), q("title", hook("rites-title")), q("changes", hook("review-change"), "count"),
            q("labels", hook("review-change") + " strong", "texts"), q("whys", hook("review-why"), "texts"), q("cites", hook("review-cite"), "texts"),
            q("today", hook("review-today")), q("honesty", hook("review-honesty")), q("limit", hook("review-limit")),
            q("buttons", hook("rites-actions") + " button", "texts"), q("ticks", hook("review-tick"), "count"),
            q("applyDisabled", hook("review-apply"), "attr", attr="disabled"), q("left", hook("review-tweaks-left")),
            q("framing", hook("review-framing")), q("card", hook("training-card"), "count")]


class TheReviewComesBeforeAnyChange(unittest.TestCase):
    def test_the_proposal_is_drawn_with_every_change_its_reason_and_the_three_choices(self):
        data = payloads()["proposal"]
        out = flow(reviewed(), [click(OPEN, "a"), click(hook("training-go"), "r", wait=300, capture=review_caps())])
        cap = out["captures"]["r"]
        self.assertEqual(cap["kind"], "training-review-sheet")
        self.assertEqual(cap["title"], "Review Underdog Gus's training")
        self.assertEqual(cap["changes"], len(data["changes"]))
        self.assertEqual(cap["ticks"], cap["changes"])
        self.assertEqual(cap["labels"], [c["label"] for c in data["changes"]])
        self.assertEqual(cap["whys"], [c["why"] for c in data["changes"]])
        self.assertEqual(cap["buttons"], ["Veto", "Tweak", "Apply"])
        self.assertIsNone(cap["applyDisabled"])
        self.assertEqual(cap["honesty"], data["honesty"])
        self.assertIn("Saying no changes nothing and does not count.", cap["limit"])
        self.assertEqual(cap["left"], "Tweaks left: 3")
        self.assertEqual(cap["card"], 0, "no upgrade card exists before Apply")

    def test_nothing_is_posted_to_the_training_route_before_apply(self):
        out = flow(reviewed(), [click(OPEN, "a"), click(hook("training-go"), "r", wait=300)])
        self.assertEqual([p["url"] for p in out["posts"]], ["/hounds/u-1/train/diagnose", "/hounds/u-1/train/propose"])

    def test_apply_posts_the_ticked_ids_and_then_the_card_follows(self):
        data = payloads()["proposal"]
        out = flow(reviewed(), [click(OPEN, "a"), click(hook("training-go"), "r", wait=300),
                                click(hook("review-apply"), "done", wait=400, capture=[q("card", hook("training-card"), "count"), q("kind", ".rt-sheet", "attr", attr="data-hook")])])
        self.assertEqual(sent(out["posts"][-1]), {"url": "/hounds/u-1/train", "body": {"confirm": True, "picks": data["picks"]}})
        self.assertEqual(out["captures"]["done"]["card"], 1)

    def test_clearing_a_tick_leaves_that_change_out_of_the_apply(self):
        data = payloads()["retune_proposal"]
        self.assertGreaterEqual(len(data["picks"]), 2)
        out = flow(reviewed(data), [click(OPEN, "a"), click(hook("training-go"), "r", wait=300),
                                dict(do="check", sel=hook("review-tick"), index=0, checked=False, wait=30),
                                click(hook("review-apply"), "done", wait=300)])
        self.assertEqual(out["posts"][-1]["body"]["picks"], data["picks"][1:])

    def test_with_every_tick_cleared_apply_cannot_be_pressed(self):
        data = payloads()["retune_proposal"]
        actions = [click(OPEN, "a"), click(hook("training-go"), "r", wait=300)]
        actions += [dict(do="check", sel=hook("review-tick"), index=i, checked=False, wait=20) for i in range(len(data["picks"]))]
        actions += [dict(do="wait", label="cleared", wait=20, capture=[q("applyDisabled", hook("review-apply"), "attr", attr="disabled")]),
                    dict(do="click", sel=hook("review-apply"), wait=200)]
        out = flow(reviewed(data), actions)
        self.assertIsNotNone(out["captures"]["cleared"]["applyDisabled"])
        self.assertEqual([p["url"] for p in out["posts"]], ["/hounds/u-1/train/diagnose", "/hounds/u-1/train/propose"], "nothing was sent")

    def test_veto_posts_the_veto_and_never_the_training(self):
        out = flow(reviewed(), [click(OPEN, "a"), click(hook("training-go"), "r", wait=300),
                                click(hook("review-veto"), "v", wait=300, capture=[q("note", hook("training-vetoed-note")), q("title", hook("rites-title")),
                                                                                 q("card", hook("training-card"), "count"), q("evolve", hook("evolve"), "count"),
                                                                                 q("buttons", hook("rites-actions") + " button", "texts")])])
        self.assertEqual([p["url"] for p in out["posts"]], ["/hounds/u-1/train/diagnose", "/hounds/u-1/train/propose", "/hounds/u-1/train/veto"])
        cap = out["captures"]["v"]
        self.assertEqual(cap["note"], "Nothing was changed. This does not count as a training.")
        self.assertEqual((cap["card"], cap["evolve"], cap["buttons"]), (0, 0, ["Close"]))
        self.assertTrue(cap["title"].endswith("stays as it is"))

    def test_veto_still_says_nothing_changed_when_the_server_cannot_be_reached(self):
        routes = reviewed(**{"POST /hounds/u-1/train/veto": [500, {"detail": "down"}]})
        out = flow(routes, [click(OPEN, "a"), click(hook("training-go"), "r", wait=300),
                            click(hook("review-veto"), "v", wait=300, capture=[q("note", hook("training-vetoed-note"))])])
        self.assertEqual(out["captures"]["v"]["note"], "Nothing was changed. This does not count as a training.")

    def test_a_proposal_that_cannot_be_prepared_is_a_refusal_and_nothing_is_applied(self):
        refusal = [409, {"detail": {"error": "open_tickets", "message": "Underdog Gus has 1 open ticket. Wait until its open tickets settle."}}]
        out = flow(reviewed(**{"POST /hounds/u-1/train/propose": refusal}), [click(OPEN, "a"), click(hook("training-go"), "r", wait=300, capture=[
            q("refused", hook("training-refused")), q("title", hook("rites-title"))])])
        self.assertIn("Wait until its open tickets settle", out["captures"]["r"]["refused"])
        self.assertEqual([p["url"] for p in out["posts"]][-1], "/hounds/u-1/train/propose")

    def test_a_hound_with_nothing_sensible_to_change_says_so_and_cannot_be_applied(self):
        data = copy.deepcopy(payloads()["proposal"])
        data.update(changes=[], picks=[], nothing=True, today=None, message="Underdog Gus has not bet yet, and none of the changes it is allowed to make "
                                                                           "would add a game to today's board, so there is nothing sensible to change.")
        out = flow(reviewed(data), [click(OPEN, "a"), click(hook("training-go"), "r", wait=300, capture=review_caps() + [q("message", hook("review-message"))])])
        cap = out["captures"]["r"]
        self.assertEqual((cap["changes"], cap["ticks"]), (0, 0))
        self.assertIn("nothing sensible to change", cap["message"])
        self.assertIsNotNone(cap["applyDisabled"])

    def test_a_hound_that_has_not_bet_is_asked_whether_to_look_at_more_games(self):
        data = copy.deepcopy(payloads()["proposal"])
        data["framing"] = "Underdog Gus has not bet yet. Want it to look at more games?"
        out = flow(reviewed(data), [click(OPEN, "a"), click(hook("training-go"), "r", wait=300, capture=review_caps())])
        self.assertEqual(out["captures"]["r"]["framing"], "Underdog Gus has not bet yet. Want it to look at more games?")

    def test_nothing_on_the_review_promises_a_result_or_says_dog(self):
        out = flow(reviewed(), [click(OPEN, "a"), click(hook("training-go"), "r", wait=300, capture=[q("all", hook("training-review"))])])
        text = out["captures"]["r"]["all"]
        self.assertIsNone(BANNED.search(text), text)
        self.assertIn("makes no promise about results", text)


class TweakingAProposal(unittest.TestCase):
    def revised(self):
        data = copy.deepcopy(payloads()["proposal"])
        data["tweak"] = {"used": 1, "left": 2, "max": 3}
        data["changes"] = data["changes"][:1]
        data["picks"] = data["picks"][:1]
        data["changes"][0]["cite"] = {"line": 0, "text": "look at more sports", "quote": "more sports"}
        return data

    def test_the_box_opens_and_a_second_proposal_is_asked_for_with_the_words_and_the_round(self):
        routes = reviewed()
        out = flow(routes, [click(OPEN, "a"), click(hook("training-go"), "r", wait=300),
                            click(hook("review-tweak"), "open", wait=50, capture=[q("box", hook("review-tweak-box"), "hidden")]),
                            dict(do="set", sel=hook("review-tweak-input"), value="look at more sports", wait=20),
                            click(hook("review-tweak-send"), "sent", wait=300, capture=[q("changes", hook("review-change"), "count"), q("cites", hook("review-cite"), "texts"),
                                                                                         q("left", hook("review-tweaks-left")), q("box", hook("review-tweak-box"), "hidden")])],
                   switchAfter={"/hounds/u-1/train/propose": [1, [200, self.revised()]]})
        self.assertFalse(out["captures"]["open"]["box"])
        self.assertEqual(sent(out["posts"][-1]), {"url": "/hounds/u-1/train/propose", "body": {"tweak": "look at more sports", "round": 0}})
        cap = out["captures"]["sent"]
        self.assertEqual(cap["changes"], 1)
        self.assertEqual(cap["cites"], ["You said: “look at more sports”"])
        self.assertEqual(cap["left"], "Tweaks left: 2")
        self.assertTrue(cap["box"], "the box closes once the revised list is up")

    def test_the_revised_list_is_what_apply_sends(self):
        revised = self.revised()
        routes = reviewed()
        out = flow(routes, [click(OPEN, "a"), click(hook("training-go"), "r", wait=300), click(hook("review-tweak"), "o", wait=30),
                            dict(do="set", sel=hook("review-tweak-input"), value="more sports", wait=20),
                            click(hook("review-tweak-send"), "s", wait=300, capture=[q("changes", hook("review-change"), "count")]),
                            click(hook("review-apply"), "done", wait=300)],
                   switchAfter={"/hounds/u-1/train/propose": [1, [200, revised]]})
        self.assertEqual(out["captures"]["s"]["changes"], 1, "the revised card replaced the first list")
        self.assertEqual(out["posts"][-1]["body"], {"confirm": True, "picks": revised["picks"]})

    def test_an_empty_tweak_asks_for_words_and_sends_nothing(self):
        out = flow(reviewed(), [click(OPEN, "a"), click(hook("training-go"), "r", wait=300), click(hook("review-tweak"), "o", wait=30),
                                click(hook("review-tweak-send"), "s", wait=100, capture=[q("err", hook("review-error"))])])
        self.assertEqual(out["captures"]["s"]["err"], "Say what you want changed, or why.")
        self.assertEqual([p["url"] for p in out["posts"]].count("/hounds/u-1/train/propose"), 1)

    def test_when_no_tweaks_are_left_the_button_is_off(self):
        data = copy.deepcopy(payloads()["proposal"])
        data["tweak"] = {"used": 3, "left": 0, "max": 3}
        out = flow(reviewed(data), [click(OPEN, "a"), click(hook("training-go"), "r", wait=300, capture=[
            q("off", hook("review-tweak"), "attr", attr="disabled"), q("left", hook("review-tweaks-left"))])])
        self.assertIsNotNone(out["captures"]["r"]["off"])
        self.assertEqual(out["captures"]["r"]["left"], "No tweaks left.")

    def test_a_tweak_the_server_cannot_map_keeps_the_list_and_says_why(self):
        data = payloads()["proposal"]
        nothing = copy.deepcopy(data)
        nothing.update(changes=[], picks=[], nothing=True, message="I could not turn that into a change I am allowed to make. Say it another way.",
                       tweak={"used": 1, "left": 2, "max": 3})
        out = flow(reviewed(), [click(OPEN, "a"), click(hook("training-go"), "r", wait=300), click(hook("review-tweak"), "o", wait=30),
                                dict(do="set", sel=hook("review-tweak-input"), value="avoid back to back games", wait=20),
                                click(hook("review-tweak-send"), "s", wait=300, capture=[q("changes", hook("review-change"), "count"), q("err", hook("review-error")),
                                                                                         q("left", hook("review-tweaks-left"))])],
                   switchAfter={"/hounds/u-1/train/propose": [1, [200, nothing]]})
        cap = out["captures"]["s"]
        self.assertEqual(cap["changes"], len(data["changes"]), "the list the owner was looking at is still there")
        self.assertIn("could not turn that into a change I am allowed to make", cap["err"])
        self.assertEqual(cap["left"], "Tweaks left: 2")

    def test_a_refused_tweak_shows_the_servers_sentence_and_keeps_the_list(self):
        refusal = [409, {"detail": {"error": "tweak_limit", "message": "That is 3 tweaks. Apply the proposal, or say no and start again."}}]
        out = flow(reviewed(), [click(OPEN, "a"), click(hook("training-go"), "r", wait=300), click(hook("review-tweak"), "o", wait=30),
                                dict(do="set", sel=hook("review-tweak-input"), value="once more", wait=20),
                                click(hook("review-tweak-send"), "s", wait=300, capture=[q("changes", hook("review-change"), "count"), q("err", hook("review-error")),
                                                                                         q("off", hook("review-tweak"), "attr", attr="disabled")])],
                   switchAfter={"/hounds/u-1/train/propose": [1, refusal]})
        cap = out["captures"]["s"]
        self.assertIn("That is 3 tweaks", cap["err"])
        self.assertGreater(cap["changes"], 0)
        self.assertIsNotNone(cap["off"])


class RetuneMe(unittest.TestCase):
    ASK = "I don't like that you won't take a single bet on anything today"

    def routes(self, retune=True, owner=True):
        routes = dog_routes(kit=Payloads.kit(owner=owner) if owner else None) if owner else dog_routes()
        answer = {"intent": "retune", "question": self.ASK, "answer": "x", "lines": ["Today I checked 60 games and 52 failed my price band. None cleared my rule.",
                                                                                        "Tap Retune me and I will show what I would change and why."],
                  "ui_lines": None, "cards": [], "cards_at": None, "hindsight": False, "busy": None, "details": None, "fine": None, "tickets": [],
                  "followups": [], "matched": True, "dog_id": HID, "dog_name": "Closer", "paper_only": True,
                  "retune": {"offer": True, "label": "Retune me", "enabled": True, "note": ""} if retune else None}
        routes[f"POST /hounds/{HID}/ask"] = [200, answer]
        routes[f"POST /hounds/{HID}/train/propose"] = [200, payloads()["retune_proposal"]]
        routes[f"POST /hounds/{HID}/train"] = [200, payloads()["retuned"]]
        routes[f"POST /hounds/{HID}/train/veto"] = [200, payloads()["veto"]]
        return routes

    def ask(self, routes, more=(), **kw):
        actions = [dict(do="set", sel=hook("ask-input"), value=self.ASK, wait=10), dict(do="click", sel=hook("ask-send"), wait=150, capture=[
            q("button", hook("ask-retune"), "count"), q("label", hook("ask-retune")), q("lines", hook("ask-answer") + " p", "texts")])]
        return page(routes, reducedMotion=True, actions=actions + list(more), **kw)

    def test_the_button_is_there_when_the_server_sent_one(self):
        out = self.ask(self.routes())
        cap = out["captures"]["1"]
        self.assertEqual((cap["button"], cap["label"]), (1, "Retune me"))
        self.assertIn("Today I checked 60 games", " ".join(cap["lines"]))

    def test_without_the_servers_offer_there_is_no_button_a_visitor_never_gets_one(self):
        out = self.ask(self.routes(retune=False))
        self.assertEqual(out["captures"]["1"]["button"], 0)

    def test_a_retune_that_is_not_allowed_right_now_shows_a_disabled_button_and_the_reason(self):
        routes = self.routes()
        routes[f"POST /hounds/{HID}/ask"][1]["retune"] = {"offer": True, "label": "Retune me", "enabled": False, "note": "Closer has 1 open ticket."}
        out = self.ask(routes, [dict(do="wait", wait=10, capture=[q("off", hook("ask-retune"), "attr", attr="disabled"), q("note", hook("ask-retune-note"))])])
        cap = out["captures"]["2"]
        self.assertIsNotNone(cap["off"])
        self.assertEqual(cap["note"], "Closer has 1 open ticket.")

    def test_the_button_starts_the_review_from_the_owners_own_lines_and_posts_nothing_that_writes(self):
        out = self.ask(self.routes(), [dict(do="click", sel=hook("ask-retune"), wait=300, capture=review_caps() + [q("mapper", hook("review-mapper")), q("cite", hook("review-cite"))])])
        self.assertEqual(out["posts"][-1]["url"], f"/hounds/{HID}/train/propose")
        self.assertEqual(out["posts"][-1]["body"], {"origin": "chat", "chat": [self.ASK]})
        self.assertNotIn(f"/hounds/{HID}/train", [p["url"] for p in out["posts"]])
        cap = out["captures"]["2"]
        self.assertEqual(cap["title"], "Retune Closer?")
        self.assertEqual(cap["buttons"], ["Veto", "Tweak", "Apply"])
        self.assertTrue(cap["cite"].startswith("You said: "))

    def test_apply_sends_the_ticked_ids_with_the_chat_origin_and_the_card_names_the_lineage(self):
        data = payloads()["retune_proposal"]
        out = self.ask(self.routes(), [dict(do="click", sel=hook("ask-retune"), wait=300), dict(do="click", sel=hook("review-apply"), wait=400, capture=[
            q("lineage", hook("training-lineage")), q("label", hook("training-label")), q("honesty", hook("training-honesty")),
            q("card", hook("training-card"), "count")])])
        self.assertEqual(sent(out["posts"][-1]), {"url": f"/hounds/{HID}/train", "body": {"confirm": True, "picks": data["picks"], "origin": "chat"}})
        cap = out["captures"]["3"]
        self.assertEqual(cap["card"], 1)
        self.assertEqual(cap["label"], "Retuned")
        self.assertEqual(cap["lineage"], "Marked in its lineage: owner retune (from chat)")
        self.assertIn("makes no promise about results", cap["honesty"])

    def test_veto_from_a_retune_changes_nothing(self):
        out = self.ask(self.routes(), [dict(do="click", sel=hook("ask-retune"), wait=300), dict(do="click", sel=hook("review-veto"), wait=300, capture=[
            q("note", hook("training-vetoed-note"))])])
        self.assertEqual([p["url"] for p in out["posts"]][-2:], [f"/hounds/{HID}/train/propose", f"/hounds/{HID}/train/veto"])
        self.assertEqual(out["captures"]["3"]["note"], "Nothing was changed. This does not count as a training.")


class WhatTheOwnerTypedIsOnlyEverText(unittest.TestCase):
    EVIL = "<img src=x onerror=alert(1)> & <script>alert(2)</script>"

    def test_the_cited_line_is_drawn_as_text_not_markup(self):
        data = copy.deepcopy(payloads()["retune_proposal"])
        for c in data["changes"]:
            c["cite"] = {"line": 0, "text": self.EVIL, "quote": "x"}
        out = flow(reviewed(data), [click(OPEN, "a"), click(hook("training-go"), "r", wait=300, capture=[
            q("cites", hook("review-cite"), "texts"), q("imgs", ".rt-sheet img", "count"), q("scripts", ".rt-sheet script", "count")])])
        cap = out["captures"]["r"]
        self.assertTrue(cap["cites"] and all(self.EVIL in c for c in cap["cites"]), cap["cites"])
        self.assertEqual((cap["imgs"], cap["scripts"]), (0, 0))

    def test_a_change_label_or_reason_with_markup_in_it_is_text_too(self):
        data = copy.deepcopy(payloads()["proposal"])
        data["changes"][0].update(label=self.EVIL, why=self.EVIL, old_text=self.EVIL, new_text=self.EVIL)
        out = flow(reviewed(data), [click(OPEN, "a"), click(hook("training-go"), "r", wait=300, capture=[
            q("labels", hook("review-change") + " strong", "texts"), q("imgs", ".rt-sheet img", "count")])])
        self.assertEqual(out["captures"]["r"]["labels"][0], self.EVIL)
        self.assertEqual(out["captures"]["r"]["imgs"], 0)

    def test_the_review_module_never_writes_markup(self):
        from pathlib import Path
        for name in ("dog-review.js",):
            text = (Path(__file__).resolve().parent.parent / "web" / "js" / name).read_text(encoding="utf-8")
            self.assertNotIn("innerHTML", text)
            self.assertNotIn("insertAdjacentHTML", text)
            self.assertNotIn("document.write", text)


if __name__ == "__main__":
    unittest.main()
