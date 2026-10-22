"""The dog kit and the Training camp, run for real under node against the pages' own HTML
(web/hound.html + web/js/dog-*.js, web/learning.html + web/js/dog-camp.js), through the same harness the other
Hounds pages use (tests/hounds_web_harness.mjs). The payloads the pages read are built by the real Python code
(fire, ask, drill, camp), so a drift between server and page fails here and not in front of a visitor.

Skipped when node is not installed.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.hounds import user_engine as eng
from src.hounds.interact import ask, camp, common, drill, fire, look
from tests import hounds_web_fixtures as F
from tests.hounds_web_runner import HAS_NODE, WEB, run_js, run_page
from tests.test_hounds_interact_ask import FIRE_NOTHING, context
from tests.test_hounds_interact_drill import NOW as DRILL_NOW, run as run_drill, user_dog as drill_dog
from tests.test_hounds_interact_fire import NOW, OWNER, dog_of, rows_for
from tests._hounds_user_fixtures import standard_rows

HID = "closer"
TOKEN = "aisportsanalysis.invite_token"
BANNED = re.compile(r"\block\b|\bedge\b|guarantee|sure thing|can'?t lose|free money|\bprofit|\bev\b|expected value", re.I)


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


def hook(name):
    return f"[data-hook='{name}']"


class Payloads:
    """The real server payloads, built once from fixtures."""
    tmp = None

    @classmethod
    def fire_payload(cls, owner=True, **dog_over):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(eng, "ledger_path", lambda p=None: p or os.path.join(tmp, "u.jsonl")):
                dog = dog_of(hid=HID, **dog_over)
                out = fire.fire_user(dog, now=NOW, rows_for=rows_for(standard_rows()), ledger=os.path.join(tmp, "u.jsonl"))
                with mock.patch.object(common, "now_utc", lambda: NOW):
                    return camp.decorate_fire(dog, out, OWNER if owner else None, now=NOW)

    @classmethod
    def kit(cls, owner=True, signed_in=True, **over):
        base = {"dog_id": HID, "kind": "user", "name": "Closer", "status": "running", "is_owner": owner,
                "signed_in": signed_in, "can_fire": True, "can_record_manual": owner, "can_customize": owner,
                "can_suggest": signed_in and not owner, "look": None,
                "feedback": {"good": 0, "bad": 0, "notes": 0, "by_kind": {}, "by_target": {}, "suggestions": 0},
                "manual": {"limit_per_day": 5, "remaining_today": 5}, "builder_href": f"build-a-hound.html?from={HID}",
                "paper_only": True}
        base.update(over)
        return base


UNLEASH_DAY = {"headline": "Closer is unleashed. It placed 1 pick on today's board.", "placed_now": 1, "games_on_board": 12, "already_running": False,
               "picks": [{"event_id": "e1", "market": "moneyline", "market_label": "Moneyline", "selection": "Boston Red Sox to win",
                          "game": "Boston Red Sox @ Tampa Bay Rays", "price_average": 120, "stake_units": 1.0, "placed_now": True,
                          "start_utc": "2026-10-20T23:10:00Z", "started": False, "live": False}],
               "before": [{"event_id": "e0", "selection": "Chicago Cubs to win", "price_average": 110, "game": "Chicago Cubs @ Reds", "stake_units": 1.0,
                           "outcome": "Would have won", "result": "won", "state": "final"}],
               "no_board": [], "open_tickets": [], "other_picks": [], "before_label": "Before you unleashed. Not on its record.", "paper_only": True}


def dog_routes(*, owner=True, signed_in=True, kind="user", kit=None, fire_payload=None, status=200):
    r = {k: list(v) for k, v in F.routes(True, 12).items()}
    detail = F.detail(HID, True, 12)
    detail["kind"] = kind
    r[f"/hounds/{HID}"] = [200, detail]
    r[f"/hounds/{HID}/rulebook"] = [404, {"detail": "no"}]
    r[f"/hounds/{HID}/tips"] = [200, {"hound_id": HID, "count": 0, "tips": [], "note": "n"}]
    if kit is not False:
        r[f"/hounds/{HID}/kit"] = [200, kit if kit is not None else Payloads.kit(owner=owner, signed_in=signed_in)]
    payload = fire_payload if fire_payload is not None else Payloads.fire_payload(owner=owner)
    r[f"POST /hounds/{HID}/fire"] = [200, payload]
    # the owner's Unleash (dog-fire.js `today`) starts the hound: the same route and answer shape the kennel studio draws
    r[f"POST /hounds/{HID}/unleash"] = [200, UNLEASH_DAY]
    ctx = context(dog_id=HID, name="Closer")
    r[f"/hounds/{HID}/ask"] = [200, {"dog_id": HID, "dog_name": "Closer", "greeting": ask.answer("who are you", ctx)["lines"],
                                     "suggestions": ask.suggestions(ctx), "warming": False}]
    r[f"POST /hounds/{HID}/ask"] = [200, ask.answer("How are you doing?", ctx)]
    counts = {"good": 1, "bad": 0, "notes": 0, "by_kind": {"answer": {"good": 1, "bad": 0}}, "by_target": {}, "suggestions": 0}
    r[f"/hounds/{HID}/feedback"] = [200, {"dog_id": HID, "counts": {"good": 0, "bad": 0, "notes": 0, "by_kind": {}, "by_target": {}, "suggestions": 0}}]
    r[f"POST /hounds/{HID}/feedback"] = [200, {"saved": {}, "counts": counts, "note": "n"}]
    r[f"/hounds/{HID}/manual"] = [200, {"dog_id": HID, "tickets": [], "record": {"tickets": 0}, "limit_per_day": 5, "note": "n"}]
    r[f"POST /hounds/{HID}/manual"] = [200, {"ticket": {"price_average": 120, "selection": "Boston Red Sox to win"},
                                             "record": {}, "remaining_today": 4, "note": "n"}]
    r[f"POST /hounds/{HID}/suggest"] = [200, {"saved": {}, "note": "Your suggestion goes to the owner. It changes nothing on its own."}]
    # the server answers with the look it validated and stored, which is what the studio now redraws: the same choices the test makes
    r[f"PUT /hounds/{HID}/look"] = [200, {"dog_id": HID, "look": look.validate_look({"coat": "red", "head": "cap", "body": "jersey", "number": 23})}]
    return r


def page(routes, **kw):
    kw.setdefault("stored", {TOKEN: "tok"})
    kw.setdefault("search", f"?id={HID}")
    return run_page("hound", routes=routes, **kw)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheKitOnADogPage(unittest.TestCase):
    def test_the_owner_sees_fire_ask_ratings_and_the_locker_room(self):
        out = page(dog_routes(), queries=[
            q("fire", hook("dog-fire-section"), "hidden"), q("ask", hook("dog-ask-section"), "hidden"),
            q("fans", hook("dog-fans-section"), "hidden"), q("locker", hook("dog-locker-section"), "hidden"),
            q("manual", hook("dog-manual-section"), "hidden"),
            q("firebtn", hook("fire-btn")), q("chips", hook("ask-chip"), "texts"), q("greet", hook("ask-answer")),
            q("note", hook("ask-note"))])
        f = out["final"]
        for key in ("fire", "ask", "fans", "locker", "manual"):
            self.assertFalse(f[key], key)
        self.assertEqual(f["firebtn"], "Unleash")
        self.assertIn("What did you bet today?", f["chips"])
        self.assertIn("Closer", f["greet"])
        self.assertNotIn("What I do", f["greet"])
        self.assertFalse(f["note"])                      # the "not written by an AI model" line is gone (not true of every answer)
        self.assertIn("/hounds/closer/kit", out["gets"])

    def test_the_preview_draws_the_picks_and_the_checks_for_a_visitor_under_its_own_name(self):
        out = page(dog_routes(owner=False), captureInitial=[q("btn", hook("fire-btn")), q("head", "#fire-h")], actions=[dict(do="click", sel=hook("fire-btn"), wait=80, capture=[
            q("headline", hook("fire-headline")), q("picks", hook("fire-pick"), "count"),
            q("sel", ".dk-pick__sel"), q("price", ".dk-pick__price"), q("reason", hook("pick-reason")),
            q("checks", ".dk-checks li", "count"), q("record", hook("record-manual"), "count"),
            q("note", hook("fire-preview-note")), q("btn", hook("fire-btn"))])])
        # "Unleash" is the owner's real button (it bets today); the visitor's read-only run is "See what it would pick"
        self.assertEqual(out["captures"]["initial"]["btn"], "See what it would pick")
        self.assertEqual(out["captures"]["initial"]["head"], "See what it would pick")
        c = out["captures"]["0"]
        self.assertEqual(c["headline"], "1 pick qualifies on the latest stored boards.")
        self.assertEqual(c["picks"], 1)
        self.assertEqual(c["sel"], "Boston Red Sox to win")
        self.assertIn("Average price +120", c["price"])
        self.assertIn("5 books quoting", c["price"])
        self.assertIn("Rule: the underdog", c["reason"])
        self.assertEqual(c["checks"], 5)
        self.assertEqual(c["record"], 0)
        self.assertIn("preview", c["note"].lower())
        self.assertEqual(c["btn"], "See what it would pick again")
        self.assertEqual([p["url"] for p in out["posts"]], [f"/hounds/{HID}/fire"])      # read only: nothing is recorded

    def test_the_owners_unleash_on_the_hound_page_is_the_real_one_the_studio_runs(self):
        """Live QA 2026-10-22: the hound page's Unleash was the nothing-is-recorded preview while the studio's bet today. The owner
        gets the studio's component (dog-fire.js `today`): POST /unleash, never /fire, and the day it answers with."""
        out = page(dog_routes(), captureInitial=[q("btn", hook("fire-btn")), q("head", "#fire-h"), q("intro", hook("dog-fire"))],
                   actions=[dict(do="click", sel=hook("fire-btn"), wait=120, capture=[
                       q("title", hook("unleash-title")), q("headline", hook("unleash-headline")), q("picks", hook("unleash-pick"), "count"),
                       q("before", hook("unleash-before-item"), "count"), q("label", hook("unleash-before-label")),
                       q("preview", hook("fire-preview-note"), "count"), q("record", hook("record-manual"), "count")])])
        self.assertEqual(out["captures"]["initial"]["btn"], "Unleash")
        self.assertEqual(out["captures"]["initial"]["head"], "Unleash")
        self.assertIn("starts Closer betting today", out["captures"]["initial"]["intro"])
        self.assertNotIn("Nothing is recorded", out["captures"]["initial"]["intro"])
        c = out["captures"]["0"]
        self.assertEqual(c["title"], "Closer's day")
        self.assertIn("placed 1 pick", c["headline"])
        self.assertEqual((c["picks"], c["before"], c["preview"], c["record"]), (1, 1, 0, 0))
        self.assertIn("Not on its record", c["label"])
        self.assertEqual([p["url"] for p in out["posts"]], [f"/hounds/{HID}/unleash"])

    def test_a_visitor_who_is_not_the_owner_gets_the_preview_without_the_button(self):
        routes = dog_routes(owner=False)
        out = page(routes, actions=[dict(do="click", sel=hook("fire-btn"), wait=80, capture=[
            q("picks", hook("fire-pick"), "count"), q("record", hook("record-manual"), "count")])],
            queries=[q("locker", hook("dog-locker-section"), "hidden")])
        self.assertEqual(out["captures"]["0"]["picks"], 1)
        self.assertEqual(out["captures"]["0"]["record"], 0)
        self.assertTrue(out["final"]["locker"])                         # the locker room is the owner's alone

    def test_nothing_qualifies_lists_the_closest_misses_with_their_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(eng, "ledger_path", lambda p=None: p or os.path.join(tmp, "u.jsonl")):
                dog = dog_of(hid=HID, price_min=150, price_max=250)
                data = fire.fire_user(dog, now=NOW, rows_for=rows_for(standard_rows()), ledger=os.path.join(tmp, "u.jsonl"))
                payload = camp.decorate_fire(dog, data, OWNER, now=NOW)
        out = page(dog_routes(owner=False, fire_payload=payload), actions=[dict(do="click", sel=hook("fire-btn"), wait=80, capture=[
            q("headline", hook("fire-headline")), q("misses", hook("fire-misses") + " li", "count"),
            q("first", hook("fire-misses") + " li"), q("picks", hook("fire-pick"), "count")])])
        c = out["captures"]["0"]
        self.assertEqual(c["headline"], "Nothing qualifies right now.")
        self.assertEqual(c["picks"], 0)
        self.assertGreaterEqual(c["misses"], 1)
        self.assertIn("Priced outside the band", c["first"])
        self.assertIn("5.5 points of win probability", c["first"])

    def test_ask_posts_the_question_and_shows_the_computed_answer_with_rating_buttons(self):
        out = page(dog_routes(), actions=[
            dict(do="set", sel=hook("ask-input"), value="How are you doing?", wait=10),
            dict(do="click", sel=hook("ask-send"), wait=80, capture=[
                q("n", hook("ask-answer"), "count"), q("last", hook("ask-answer")), q("you", hook("ask-question")),
                q("votes", hook("vote-row"), "count"), q("input", hook("ask-input"), "value")])])
        post = [p for p in out["posts"] if p["url"].endswith("/ask")][0]
        # 2026-10-21: the question carries the asker's unit size so the dog's dollars are theirs (the runner's pinned $10 viewer)
        self.assertEqual(post["body"], {"question": "How are you doing?",
                                        "sizing": {"mode": "fixed", "unit_usd": 10, "pct": None, "start_usd": 1000}})
        c = out["captures"]["1"]
        self.assertEqual(c["n"], 2)                                      # the greeting and the answer
        self.assertEqual(c["you"], "How are you doing?")
        self.assertEqual(c["input"], "")
        self.assertGreaterEqual(c["votes"], 3)                           # the dog-level row, the ticket rows, the answer's

    def test_a_suggested_question_asks_itself(self):
        out = page(dog_routes(), actions=[dict(do="click", sel=hook("ask-chip"), index=1, wait=80)])
        post = [p for p in out["posts"] if p["url"].endswith("/ask")][0]
        self.assertTrue(post["body"]["question"].endswith("?"))

    def test_good_call_on_an_answer_posts_the_vote_when_signed_in(self):
        out = page(dog_routes(), actions=[
            dict(do="click", sel=hook("ask-chip"), index=0, wait=80),
            dict(do="click", sel=f".dk-msg--dog .dk-vote__btn[data-verdict='good']", index=0, wait=80, capture=[
                q("status", ".dk-msg--dog " + hook("vote-status")), q("pressed", ".dk-msg--dog .dk-vote__btn[data-verdict='good']", "attr", attr="aria-pressed"),
                q("note", ".dk-msg--dog " + hook("vote-note"), "exists")])])
        vote = [p for p in out["posts"] if p["url"].endswith("/feedback")][0]
        self.assertEqual(vote["body"], {"target_kind": "answer", "target_id": "record", "verdict": "good"})
        self.assertEqual(out["captures"]["1"]["status"], "Saved.")
        self.assertEqual(out["captures"]["1"]["pressed"], "true")
        self.assertTrue(out["captures"]["1"]["note"])

    def test_a_signed_out_visitor_is_asked_to_sign_in_and_nothing_is_posted(self):
        out = page(dog_routes(signed_in=False, owner=False), stored={}, actions=[
            dict(do="click", sel=hook("fans-tickets") + " " + ".dk-vote__btn[data-verdict='good']", index=0, wait=60,
                 capture=[q("status", hook("fans-tickets") + " " + hook("vote-status"))])])
        self.assertIn("Sign in to rate", out["captures"]["0"]["status"])
        self.assertEqual([p for p in out["posts"] if p["url"].endswith("/feedback")], [])

    def test_a_ticket_vote_carries_the_date_and_the_pick(self):
        out = page(dog_routes(), actions=[
            dict(do="click", sel=hook("fans-tickets") + " .dk-vote__btn[data-verdict='bad']", index=0, wait=60)])
        vote = [p for p in out["posts"] if p["url"].endswith("/feedback")][0]
        self.assertEqual(vote["body"]["target_kind"], "ticket")
        self.assertRegex(vote["body"]["target_id"], r"^\d{4}-\d{2}-\d{2}\|.+")
        self.assertEqual(vote["body"]["verdict"], "bad")

    def test_a_house_model_gets_the_read_only_parts_and_a_dog_face_in_the_header(self):
        kit = Payloads.kit(owner=False, kind="house", can_fire=True, can_record_manual=False, can_customize=False,
                           can_suggest=False, builder_href=None)
        out = page(dog_routes(kind="house", kit=kit, owner=False), queries=[
            q("fire", hook("dog-fire-section"), "hidden"), q("manual", hook("dog-manual-section"), "hidden"),
            q("locker", hook("dog-locker-section"), "hidden"), q("svg", ".hd-modelhead svg", "count"),
            q("mono", ".hd-modelhead .hd-mono", "count"), q("train", hook("dog-train"))])
        f = out["final"]
        self.assertFalse(f["fire"])
        self.assertTrue(f["manual"] and f["locker"])
        # design system v2 (2026-10-19): every model, house or member's, is a dog (the rig in web/js/dog-rig.js); a house model
        # simply has no saved look, so it wears the default look its id picks. The initials tile is gone from the header.
        self.assertEqual((f["svg"], f["mono"]), (1, 0))
        self.assertIn("Coach this model", f["train"])

    def test_a_server_without_the_kit_leaves_the_page_exactly_as_it_was(self):
        out = page(dog_routes(kit=False), queries=[
            q("fire", hook("dog-fire-section"), "hidden"), q("ask", hook("dog-ask-section"), "hidden"),
            q("fans", hook("dog-fans-section"), "hidden"), q("locker", hook("dog-locker-section"), "hidden"),
            q("name", hook("hound-name"))])
        for key in ("fire", "ask", "fans", "locker"):
            self.assertTrue(out["final"][key], key)
        self.assertEqual(out["final"]["name"], "Closer")

    def test_a_dressed_dog_wears_its_badge_in_the_header(self):
        kit = Payloads.kit(look=look.validate_look({"coat": "golden", "head": "cap", "face": "sunglasses", "body": "jersey", "number": 7}))
        out = page(dog_routes(kit=kit), queries=[
            q("badge", ".hd-modelhead svg.dk-badge", "count"), q("coat", ".hd-modelhead svg.dk-badge", "attr", attr="data-coat"),
            q("mono", ".hd-modelhead .hd-mono", "count"), q("num", ".hd-modelhead svg.dk-badge text")])
        self.assertEqual(out["final"]["badge"], 1)
        self.assertEqual(out["final"]["coat"], "golden")
        self.assertEqual(out["final"]["mono"], 0)
        self.assertEqual(out["final"]["num"], "7")

    def test_the_dogs_page_still_has_no_cartoon_avatar_class(self):
        out = page(dog_routes())
        self.assertNotIn("hd-avatar", json.dumps(out["hooks"]))

    def test_manual_tickets_show_apart_with_their_own_record(self):
        routes = dog_routes()
        routes[f"/hounds/{HID}/manual"] = [200, {"dog_id": HID, "limit_per_day": 5, "note": "n", "record": {
            "tickets": 2, "graded": 1, "wins": 1, "losses": 0, "pushes": 0, "open": 1, "units_average_price": 1.2},
            "tickets": [
                {"selection": "Boston Red Sox to win", "game": "BOS @ SEA", "price_average": 120, "price_best": 125, "book": "book_a",
                 "recorded_utc": "2026-10-20T21:30:00Z", "status": "WON", "units_average_price": 1.2},
                {"selection": "Cleveland Guardians to win", "game": "CLE @ TB", "price_average": 131, "price_best": 131,
                 "recorded_utc": "2026-10-20T21:31:00Z", "status": "PENDING", "units_average_price": None}]}]
        out = page(routes, queries=[q("rec", hook("manual-record")), q("n", hook("manual-list") + " li", "count"),
                                    q("note", hook("manual-note")), q("first", hook("manual-list") + " li")])
        f = out["final"]
        self.assertIn("1 graded (1-0), +1.20u at the average price, 1 open.", f["rec"])
        self.assertEqual(f["n"], 2)
        self.assertIn("never counted in this hound's rule record", f["note"])
        self.assertIn("Manual pick, not counted in the record.", f["first"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheLockerRoom(unittest.TestCase):
    def test_picking_redraws_the_badge_and_saving_puts_the_whitelisted_look(self):
        out = page(dog_routes(), actions=[
            # an undressed dog starts from the look its id picks (dog-look.js lookFor), so the test chooses every colour it asserts on
            dict(do="click", sel=hook("locker-opt") + "[data-value='red']", wait=20),
            dict(do="click", sel="[data-group='eyes'] " + hook("locker-opt") + "[data-value='brown']", wait=20),
            dict(do="click", sel="[data-group='bg'] " + hook("locker-opt") + "[data-value='navy']", wait=20),
            dict(do="click", sel=hook("locker-opt") + "[data-value='cap']", wait=20),
            dict(do="click", sel=hook("locker-opt") + "[data-value='jersey']", wait=20),
            dict(do="set", sel=hook("locker-number"), value="23", wait=20),
            dict(do="click", sel=hook("locker-save"), wait=80, capture=[
                q("preview", hook("locker-preview") + " svg", "attr", attr="data-coat"),
                q("head", hook("locker-preview") + " svg", "attr", attr="data-head"),
                q("num", hook("locker-preview") + " svg text"), q("status", hook("locker-status"))])])
        put = [p for p in out["posts"] if p["method"] == "PUT"][0]
        self.assertEqual(put["url"], f"/hounds/{HID}/look")
        self.assertEqual(put["body"]["look"], {"coat": "red", "eyes": "brown", "bg": "navy", "head": "cap", "face": "none",
                                               "neck": "none", "body": "jersey", "number": 23, "style": "mascot", "breed": "auto"})
        c = out["captures"]["6"]
        self.assertEqual((c["preview"], c["head"], c["num"]), ("red", "cap", "23"))
        self.assertIn("Saved.", c["status"])

    def test_the_number_field_only_shows_on_a_jersey(self):
        out = page(dog_routes(), queries=[q("hidden", hook("locker-number") + "", "exists")], actions=[
            dict(do="click", sel=hook("locker-opt") + "[data-value='hoodie']", wait=20, capture=[
                q("pressed", hook("locker-opt") + "[data-value='hoodie']", "attr", attr="aria-pressed")])])
        self.assertEqual(out["captures"]["0"]["pressed"], "true")

    def test_the_server_refusing_a_look_is_said_not_swallowed(self):
        routes = dog_routes()
        routes[f"PUT /hounds/{HID}/look"] = [422, {"detail": {"error": "look_invalid", "message": "that look is not on the menu",
                                                               "fields": {"head": "choose one of: none, cap"}}}]
        out = page(routes, actions=[dict(do="click", sel=hook("locker-save"), wait=80, capture=[q("status", hook("locker-status"))])])
        self.assertIn("that look is not on the menu", out["captures"]["0"]["status"])

    def test_the_name_and_catchphrase_are_edited_in_the_builder(self):
        out = page(dog_routes(), queries=[q("href", hook("locker-builder"), "attr", attr="href")])
        self.assertEqual(out["final"]["href"], f"build-a-hound.html?from={HID}")

    # ---- the character creator (design system v2, 2026-10-19) ---------------------------------------------------

    def test_the_stage_shows_the_dog_in_a_pose_you_can_preview_and_each_accessory_option_is_a_small_dog(self):
        out = page(dog_routes(), queries=[
            q("poses", hook("locker-pose"), "texts"), q("dog", hook("locker-preview") + " svg.dk-badge", "attr", attr="data-pose"),
            q("thumbs", hook("locker-opt") + " svg.dk-badge", "count"), q("breed", hook("locker-preview") + " svg.dk-badge", "attr", attr="data-breed")],
            actions=[dict(do="click", sel=hook("locker-pose") + "[data-pose='sad']", wait=20, capture=[
                q("dog", hook("locker-preview") + " svg.dk-badge", "attr", attr="data-pose"),
                q("pressed", hook("locker-pose") + "[data-pose='sad']", "attr", attr="aria-pressed")])])
        f = out["final"]
        self.assertEqual(f["poses"], ["Idle", "Grin", "Snarl", "Focus", "Howl"], "the labels are the expressions the poses draw")
        self.assertEqual(out["captures"]["0"]["dog"], "sad")
        self.assertEqual(out["captures"]["0"]["pressed"], "true")
        self.assertEqual(f["thumbs"], 3 + 34 + 4 + 2 + 4 + 3, "one small dog on every style, breed (and the name's own), head, face, neck and body option")
        self.assertIn(f["breed"], ["retriever", "bulldog", "schnauzer", "husky", "mutt", "hound"])
        self.assertNotIn("PUT", [p["method"] for p in out["posts"]], "previewing a pose saves nothing")

    def test_randomize_rolls_a_whitelisted_look_and_saves_nothing_until_you_save(self):
        out = page(dog_routes(), actions=[dict(do="click", sel=hook("locker-random"), wait=30, capture=[
            q("coat", hook("locker-preview") + " svg.dk-badge", "attr", attr="data-coat"),
            q("head", hook("locker-preview") + " svg.dk-badge", "attr", attr="data-head"),
            q("dirty", hook("locker-dirty"), "exists")])])
        c = out["captures"]["0"]
        self.assertIn(c["coat"], list(look.COATS))
        self.assertIn(c["head"], list(look.HEAD))
        self.assertEqual([p for p in out["posts"] if p["method"] == "PUT"], [], "randomize is a preview until Save")

    def test_saving_a_look_celebrates_and_a_refusal_is_sad(self):
        ok = page(dog_routes(), actions=[dict(do="click", sel=hook("locker-save"), wait=60, capture=[
            q("pose", hook("locker-preview") + " svg.dk-badge", "attr", attr="data-pose"), q("status", hook("locker-status"))])])
        self.assertEqual(ok["captures"]["0"]["pose"], "celebrate")
        self.assertIn("Saved.", ok["captures"]["0"]["status"])
        routes = dog_routes()
        routes[f"PUT /hounds/{HID}/look"] = [422, {"detail": {"error": "look_invalid", "message": "not on the menu", "fields": {}}}]
        bad = page(routes, actions=[dict(do="click", sel=hook("locker-save"), wait=60, capture=[
            q("pose", hook("locker-preview") + " svg.dk-badge", "attr", attr="data-pose")])])
        self.assertEqual(bad["captures"]["0"]["pose"], "sad")


@unittest.skipUnless(HAS_NODE, "node not installed")
class SuggestionsAndTraining(unittest.TestCase):
    def test_a_stranger_sends_a_suggestion_the_owner_reads(self):
        out = page(dog_routes(owner=False), actions=[
            dict(do="set", sel=hook("suggest-field"), value="price_max", wait=20),
            dict(do="set", sel=hook("suggest-value"), value="150", wait=20),
            dict(do="set", sel=hook("suggest-note"), value="a shorter ceiling", wait=20),
            dict(do="click", sel=hook("suggest-send"), wait=80, capture=[q("status", hook("suggest-status"))])])
        post = [p for p in out["posts"] if p["url"].endswith("/suggest")][0]
        self.assertEqual(post["body"], {"change": {"price_max": 150}, "note": "a shorter ceiling"})
        self.assertIn("changes nothing on its own", out["captures"]["3"]["status"])

    def test_the_owner_opens_the_builder_with_the_change_filled_in(self):
        out = page(dog_routes(), actions=[
            dict(do="set", sel=hook("suggest-field"), value="min_books", wait=20),
            dict(do="set", sel=hook("suggest-value"), value="5", wait=20),
            dict(do="click", sel=hook("suggest-send"), wait=40)])
        self.assertEqual(out["navigations"], [f"build-a-hound.html?from={HID}&change=min_books%3A5"])
        self.assertEqual([p for p in out["posts"] if p["url"].endswith("/suggest")], [])

    def test_the_owner_sees_the_suggestions_people_sent_each_with_its_own_builder_link(self):
        routes = dog_routes()
        routes[f"/hounds/{HID}/feedback"] = [200, {"dog_id": HID, "counts": {"good": 0, "bad": 0, "notes": 0, "by_kind": {}, "by_target": {}, "suggestions": 1},
                                                    "suggestions": [{"id": 3, "hound_id": HID, "note": "fewer overs", "change": {"price_max": 200, "min_books": 4}, "created_at": "2026-10-19T12:00:00Z"}],
                                                    "notes": [{"target_kind": "ticket", "target_id": "x", "verdict": "bad", "note": "Too long a price", "created_at": "2026-10-19T12:00:00Z"}]}]
        out = page(routes, queries=[q("n", hook("owner-suggestions") + " li", "count"), q("text", hook("owner-suggestions")),
                                    q("href", hook("suggestion-open"), "attr", attr="href"), q("notes", hook("owner-notes"))])
        f = out["final"]
        self.assertEqual(f["n"], 1)
        self.assertIn("Longest price: +200", f["text"])
        self.assertIn("Books quoting at least: 4", f["text"])
        self.assertEqual(f["href"], f"build-a-hound.html?from={HID}&change=price_max%3A200%2Cmin_books%3A4")
        self.assertIn("Bad call: Too long a price", f["notes"])

    def test_the_what_fans_think_counts_say_small_sample(self):
        routes = dog_routes()
        routes[f"/hounds/{HID}/feedback"] = [200, {"dog_id": HID, "counts": {"good": 6, "bad": 2, "notes": 0, "by_kind": {"dog": {"good": 6, "bad": 2}}, "by_target": {}, "suggestions": 0}}]
        out = page(routes, queries=[q("counts", hook("fans-counts"))])
        self.assertIn("8 ratings: 6 Good call, 2 Bad call.", out["final"]["counts"])
        self.assertNotIn("small sample", out["final"]["counts"])   # owner ruling 2026-10-20, complete-product positioning


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheTrainingCamp(unittest.TestCase):
    def camp_payload(self):
        return {"dogs": [{
            "id": "u-1", "name": "Plus Money Pete", "tagline": "Fetch.", "status": "running", "version_no": 1, "look": look.validate_look({"coat": "golden"}),
            "record": {"bets": 21, "wins": 11, "losses": 10, "pushes": 0, "units_average_price": 3.58, "units_recorded_price": 4.1},
            "verdict": {"label": "TOO EARLY"}, "open_bets": 1,
            "last_tickets": [{"date": f"2026-10-1{i}", "selection": f"Pick {i}", "price_average": 120 + i, "result": "win" if i % 2 else "loss", "units": 1.2 if i % 2 else -1.0} for i in range(5)],
            "feedback": {"good": 3, "bad": 1, "notes": 1, "suggestions": 1}, "feedback_notes": [],
            "suggestions": [{"id": 1, "hound_id": "u-1", "note": "shorter band", "change": {"price_max": 200}, "created_at": "x"}],
            "manual": {"tickets": 2, "graded": 1, "wins": 1, "losses": 0, "pushes": 0, "voids": 0, "open": 1, "units_average_price": 1.2, "remaining_today": 4, "note": "n"},
            "page_href": "hound.html?id=u-1", "builder_href": "build-a-hound.html?from=u-1", "warming": False}],
            "count": 1, "paper_only": True}

    def routes(self, **over):
        from tests.test_hounds_learning_web import learning_payload
        with tempfile.TemporaryDirectory() as tmp:
            payload = learning_payload(Path(tmp), lesson_count=6)
        lessons = {"items": [{"lesson_id": f"l{i}", "outcome": "promoted" if i % 3 == 0 else "retired" if i % 3 == 1 else "undecided",
                              "lesson": f"Challenger c-{i} was promoted to champion: it did worse than the champion." if i % 3 == 0 else f"Challenger c-{i} was retired: it did worse than the champion.",
                              "utc": f"2026-10-{10 + i}T00:00:00Z"} for i in range(6)], "page": 1, "pages": 1, "total": 6}
        r = {"/hounds/learning": [200, payload], "/hounds/coach/report": [404, {"detail": "no"}],
             "/hounds/learning/lessons": [200, lessons], "/hounds/camp/mine": [200, self.camp_payload()],
             "/hounds": [200, F.leaderboard(True)]}
        r.update(over)
        return r

    def go(self, routes=None, **kw):
        kw.setdefault("stored", {TOKEN: "tok"})
        return run_page("camp", routes=routes or self.routes(), **kw)

    def test_your_dogs_in_training_shows_record_tickets_feedback_and_suggestions(self):
        out = self.go(queries=[
            q("n", hook("camp-dog"), "count"), q("name", ".dk-camp-dog__name"), q("facts", ".dk-camp-dog__facts"),
            q("rows", hook("camp-tickets") + " tbody tr", "count"), q("sug", hook("camp-suggestions")),
            q("badge", ".dk-camp-dog svg.dk-badge", "count"), q("buttons", ".dk-camp-dog__tools .btn", "texts")])
        f = out["final"]
        self.assertEqual(f["n"], 1)
        self.assertEqual(f["name"], "Plus Money Pete")
        self.assertIn("11-10 over 21 bets", f["facts"])
        self.assertNotIn("small sample", f["facts"])   # owner ruling 2026-10-20, complete-product positioning
        self.assertIn("+3.58u", f["facts"])
        self.assertIn("3 good, 1 bad, 1 notes", f["facts"])
        self.assertIn("1-0 of 1 graded, 1 open", f["facts"])
        self.assertEqual(f["rows"], 5)
        self.assertIn("Longest price: +200", f["sug"])
        self.assertEqual(f["badge"], 1)
        self.assertEqual(f["buttons"][:3], ["Unleash", "Ask", "Backtest this dog"])

    def test_signed_out_it_asks_you_to_sign_in_and_still_shows_the_rest_of_camp(self):
        out = self.go(stored={}, queries=[q("prompt", hook("camp-dogs")), q("href", hook("camp-dogs") + " a", "attr", attr="href"),
                                           q("coach", hook("coach-section"), "exists")])
        self.assertIn("Sign in to see the dogs you built", out["final"]["prompt"])
        self.assertTrue(out["final"]["coach"])
        self.assertNotIn("/hounds/camp/mine", out["gets"])

    def test_a_signed_in_user_with_no_dog_is_pointed_at_the_builder(self):
        out = self.go(routes=self.routes(**{"/hounds/camp/mine": [200, {"dogs": [], "count": 0}]}),
                       queries=[q("empty", hook("camp-dogs-empty"))])
        self.assertIn("You have not built a dog yet", out["final"]["empty"])

    def test_an_expired_sign_in_is_said(self):
        out = self.go(routes=self.routes(**{"/hounds/camp/mine": [401, {"detail": "no"}]}),
                       queries=[q("prompt", hook("camp-dogs"))])
        self.assertIn("Your sign-in has expired", out["final"]["prompt"])

    def test_fire_now_on_a_camp_card_posts_and_shows_the_preview_inline(self):
        payload = Payloads.fire_payload()
        out = self.go(routes=self.routes(**{"POST /hounds/u-1/fire": [200, payload]}), actions=[
            dict(do="click", sel=hook("camp-dog-fire"), wait=100, capture=[
                q("inline", hook("camp-inline"), "hidden"), q("picks", hook("fire-pick"), "count"), q("headline", hook("fire-headline"))])])
        self.assertEqual([p["url"] for p in out["posts"]], ["/hounds/u-1/fire"])
        self.assertFalse(out["captures"]["0"]["inline"])
        self.assertEqual(out["captures"]["0"]["picks"], 1)

    def test_ask_on_a_camp_card_opens_a_small_chat(self):
        ctx = context(dog_id="u-1", name="Plus Money Pete")
        routes = self.routes(**{"POST /hounds/u-1/ask": [200, ask.answer("How are you doing?", ctx)]})
        out = self.go(routes=routes, actions=[
            dict(do="click", sel=hook("camp-dog-ask"), wait=40),
            dict(do="click", sel=hook("camp-inline") + " " + hook("ask-chip"), index=1, wait=100, capture=[q("n", hook("ask-answer"), "count")])])
        self.assertEqual(out["captures"]["1"]["n"], 1)
        self.assertTrue(any(p["url"] == "/hounds/u-1/ask" for p in out["posts"]))

    def test_a_drill_posts_the_dog_and_the_days_and_is_labelled_not_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(eng, "ledger_path", lambda p=None: p or os.path.join(tmp, "u.jsonl")):
                result = run_drill(drill_dog(), days=14)
        out = self.go(routes=self.routes(**{"POST /hounds/drill": [200, result]}), actions=[
            dict(do="click", sel=hook("drill-days") + "[data-days='14']", wait=20),
            dict(do="click", sel=hook("drill-run"), wait=120, capture=[
                q("label", hook("drill-label")), q("record", hook("drill-record")), q("units", hook("drill-units")),
                q("sample", hook("drill-sample")), q("best", hook("drill-best") + " li", "count"),
                q("picks", hook("drill-picks") + " tbody tr", "count")])])
        post = [p for p in out["posts"] if p["url"] == "/hounds/drill"][0]
        self.assertEqual(post["body"], {"dog_id": "u-1", "days": 14})
        c = out["captures"]["1"]
        self.assertIn("Backtest (hindsight, not counted in the record)", c["label"])
        self.assertIn("never added to a record", c["label"])
        self.assertEqual(c["record"], "1-0")
        self.assertEqual(c["units"], "+1.20u")
        self.assertIn("small sample", c["sample"])
        self.assertEqual(c["best"], 1)
        self.assertEqual(c["picks"], 1)

    def test_a_drill_needs_a_sign_in_and_says_so(self):
        out = self.go(stored={}, actions=[dict(do="click", sel=hook("drill-run"), wait=60, capture=[q("status", hook("drill-status"))])])
        # signed out there are no 'your dogs'; the house models are still listed, so the button exists and asks to sign in
        self.assertIn("Sign in to run a backtest", out["captures"]["0"]["status"])
        self.assertEqual([p for p in out["posts"] if p["url"] == "/hounds/drill"], [])

    def test_the_drill_dog_list_has_your_dogs_and_the_house_models(self):
        out = self.go(queries=[q("opts", hook("drill-dog") + " option", "texts"), q("groups", hook("drill-dog") + " optgroup", "attrs", attr="label")])
        self.assertEqual(out["final"]["groups"], ["Your dogs", "House models"])
        self.assertEqual(out["final"]["opts"][0], "Plus Money Pete")
        self.assertIn("Closer", out["final"]["opts"])
        self.assertNotIn("Rusty's Revenge", out["final"]["opts"])        # a builder dog that is not yours is not drillable here

    def test_a_server_error_in_a_drill_is_said_in_the_servers_words(self):
        out = self.go(routes=self.routes(**{"POST /hounds/drill": [422, {"detail": {"error": "not_drillable", "message": "Desk cannot be drilled"}}]}),
                       actions=[dict(do="click", sel=hook("drill-run"), wait=80, capture=[q("status", hook("drill-status"))])])
        self.assertIn("Desk cannot be drilled", out["captures"]["0"]["status"])

    def test_promotions_and_cuts_come_from_the_lessons_and_say_made_the_team_or_cut(self):
        out = self.go(queries=[q("n", hook("camp-event"), "count"), q("chips", hook("camp-event") + " .dk-chip", "texts"),
                                q("text", hook("camp-event-list"))])
        self.assertEqual(out["final"]["n"], 4)                           # 2 promoted + 2 retired; the undecided are not events
        self.assertEqual(sorted(set(out["final"]["chips"])), ["Cut", "Made the team"])
        self.assertIn("made the team", out["final"]["text"])
        self.assertIn("was cut", out["final"]["text"])
        self.assertNotIn("champion", out["final"]["text"])

    def test_before_any_promotion_it_says_so(self):
        out = self.go(routes=self.routes(**{"/hounds/learning/lessons": [200, {"items": [], "page": 1, "pages": 1, "total": 0}]}),
                       queries=[q("empty", hook("camp-events-empty"))])
        self.assertIn("No rookie has made the team or been cut yet", out["final"]["empty"])

    def test_the_sections_are_in_the_order_the_owner_asked_for(self):
        html = (WEB / "learning.html").read_text(encoding="utf-8")
        order = [html.index(h) for h in ('data-hook="camp-dogs-section"', 'data-hook="coach-section"',
                                         'data-hook="camp-drills-section"', 'data-hook="camp-events-section"',
                                         'data-hook="learning-chance-section"')]
        self.assertEqual(order, sorted(order))

    def test_the_camp_makes_no_claim_in_its_words(self):
        out = self.go(actions=[dict(do="click", sel=hook("drill-run"), wait=60)])
        self.assertIsNone(BANNED.search(out["text"]), BANNED.search(out["text"]))
        self.assertNotIn("undefined", out["text"])
        self.assertNotIn("NaN", out["text"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheAvatarModule(unittest.TestCase):
    def test_the_key_lists_are_the_servers(self):
        got = run_js('import * as A from "./dog-avatar.js";\n'
                     'console.log(JSON.stringify({coat: Object.keys(A.COATS), eyes: Object.keys(A.EYES), bg: Object.keys(A.BACKGROUNDS),'
                     ' head: A.HEAD, face: A.FACE, neck: A.NECK, body: A.BODY, style: A.STYLES, breed: A.BREED_CHOICES, d: A.DEFAULT_LOOK}));')
        self.assertEqual(got["coat"], list(look.COATS))
        self.assertEqual(got["eyes"], list(look.EYES))
        self.assertEqual(got["bg"], list(look.BACKGROUNDS))
        self.assertEqual((got["head"], got["face"], got["neck"], got["body"]),
                         (list(look.HEAD), list(look.FACE), list(look.NECK), list(look.BODY)))
        self.assertEqual((got["style"], got["breed"]), (list(look.STYLES), list(look.BREED_CHOICES)))
        self.assertEqual({k: v for k, v in got["d"].items()}, {k: v for k, v in look.DEFAULT_LOOK.items() if k != "v"})

    def test_a_junk_look_becomes_the_default_and_never_reaches_a_colour(self):
        got = run_js('import * as A from "./dog-avatar.js";\n'
                     'console.log(JSON.stringify(A.cleanLook({coat: "#ff0000", eyes: "<script>", bg: "url(x)", head: "crown", body: "hoodie", number: 7, extra: 1})));')
        self.assertEqual(got, {"coat": "tan", "eyes": "brown", "bg": "navy", "head": "none", "face": "none", "neck": "none",
                               "body": "hoodie", "number": None, "style": "mascot", "breed": "auto"})


if __name__ == "__main__":
    unittest.main()
