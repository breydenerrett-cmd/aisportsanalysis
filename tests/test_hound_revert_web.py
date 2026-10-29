"""The Versions list and "Go back to this version" on the page, run for real under node (tests/hounds_web_harness.mjs).

The payloads are made by the real Python (revert.versions / revert.go_back over a temp database), so a drift between the server and the page
fails here. Pinned: the studio's Versions tab shows every version with its status, when, why and forward record; the button asks once, in
the row, and sends ONLY a version number (and the id of the version the list was drawn on) with confirm; a refusal shows the server's own
sentence; the card a training leaves carries the same button as "Undo (go back to version N)". Skipped when node is not installed.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from src.hounds.interact import common, revert
from tests.hounds_web_runner import HAS_NODE, run_page
from tests import test_hounds_interact_web as interact_web
from tests import test_hounds_rites_web as rites_web
from tests import test_training_plans_web as plans_web
from tests.test_hound_revert import Lineage
from tests._hounds_rites_fixtures import NOW

hook, q = interact_web.hook, interact_web.q
click, SIGNED, dog = rites_web.click, rites_web.SIGNED, rites_web.dog
WEB = Path(__file__).resolve().parents[1] / "web"
BANNED = ("beta", "nothing cleared the bar", "bet check")


class World(Lineage):
    runTest = lambda self: None            # noqa: E731 -- a TestCase used as a fixture, never run

    @classmethod
    def build(cls):
        w = cls()
        w.setUp()
        try:
            listed = revert.versions(w.dog_of(w.v2), w.owner.id, rows=w.rows, db=w.db)
            done = revert.go_back(w.dog_of(w.v2), w.owner.id, 1, now=NOW, db=w.db)
            return {"listed": json.loads(json.dumps(listed)), "done": json.loads(json.dumps(done))}
        finally:
            w.doCleanups()


_CACHE: dict = {}


def payloads():
    if not _CACHE:
        _CACHE.update(World.build())
    return _CACHE


def routes(**over):
    r = rites_web.kennel_routes([dog("u-1", version_no=2)])
    r["/hounds/u-1/versions"] = [200, payloads()["listed"]]
    r.update(over)
    return r


def studio_versions(rts, actions):
    # 2026-10-29: the Versions list is the foot of the Coach tab
    return run_page("kennel", routes=rts, **SIGNED, reducedMotion=True,
                    actions=[click("[data-hook='dog-avatar']", "open", wait=250), click("[role='tab'][data-tab='coach']", "tab", wait=400)] + actions)


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheStudiosVersionsTab(unittest.TestCase):
    def test_the_tab_shows_every_version_with_status_why_and_the_forward_record(self):
        out = studio_versions(routes(), [dict(do="wait", ms=10, label="x", capture=[
            q("rows", hook("version"), "count"), q("nos", hook("version-no"), "texts"), q("status", hook("version-status"), "texts"),
            q("when", hook("version-when"), "texts"), q("records", hook("version-record"), "texts"), q("buttons", hook("version-go-back"), "texts"),
            q("cannot", hook("version-cannot"), "texts"), q("menu_hidden", "[data-hook='studio-versions-open']", "hidden"),
            q("all", hook("studio-versions"))])])
        cap = out["captures"]["x"]
        self.assertEqual(cap["rows"], 2)
        self.assertEqual(cap["nos"], ["Version 1", "Version 2"])
        self.assertEqual(cap["status"], ["Earlier", "Current, running"])
        self.assertTrue(any("The first version" in t for t in cap["when"]) and any("Edited by its owner" in t for t in cap["when"]))
        self.assertEqual(cap["records"], ["3-2, " + cap["records"][0].split(", ", 1)[1], cap["records"][1]])
        self.assertIn("(5 graded bets)", cap["records"][0])
        self.assertEqual(cap["buttons"], ["Go back to this version"])             # only the earlier version has the button
        self.assertEqual(cap["cannot"], ["This is the version it is on now."])
        self.assertFalse(cap["menu_hidden"], "the menu offers Versions for a hound past its first version")
        low = cap["all"].lower()
        for word in BANNED:
            self.assertNotIn(word, low)
        self.assertIsNone(re.search(r"\bnew\b", low.replace("next version", "")))

    def test_the_button_asks_once_and_sends_only_a_version_number_and_the_confirm(self):
        done = payloads()["done"]
        rts = routes(**{"POST /hounds/u-1/revert": [200, done]})
        out = studio_versions(rts, [
            click(hook("version-go-back"), "ask", wait=150, capture=[q("ask", hook("version-go-back-ask")), q("buttons", hook("version-go-back-box") + " button", "texts")]),
            click(hook("version-go-back-confirm"), "done", wait=400, capture=[q("status", hook("kennel-status"))])])
        ask = out["captures"]["ask"]
        self.assertIn("Go back to version 1?", ask["ask"])
        self.assertIn("starts with an empty record", ask["ask"])
        self.assertEqual(ask["buttons"], ["Keep it as it is", "Go back"])
        posts = [p for p in out["posts"] if p["url"].endswith("/revert")]
        self.assertEqual(len(posts), 1)
        body = posts[0]["body"] if isinstance(posts[0]["body"], dict) else json.loads(posts[0]["body"])
        self.assertEqual(sorted(body), ["confirm", "current_id", "version_no"])
        self.assertEqual((body["version_no"], body["confirm"], body["current_id"]), (1, True, payloads()["listed"]["current"]["id"]))
        self.assertNotIn("spec", json.dumps(body))
        self.assertIn("went back to the rules of version 1", out["captures"]["done"]["status"])

    def test_keeping_it_as_it_is_sends_nothing(self):
        out = studio_versions(routes(), [click(hook("version-go-back"), "ask", wait=100), click(hook("version-go-back-cancel"), "kept", wait=100, capture=[
            q("buttons", hook("version-go-back-box") + " button", "texts")])])
        self.assertEqual(out["captures"]["kept"]["buttons"], ["Go back to this version"])
        self.assertEqual([p for p in out["posts"] if p["url"].endswith("/revert")], [])

    def test_a_refusal_is_the_servers_own_sentence(self):
        refusal = [409, {"detail": {"error": "version_stale", "message": "Underdog Gus moved to another version since this list was opened. Nothing was changed."}}]
        out = studio_versions(routes(**{"POST /hounds/u-1/revert": refusal}), [
            click(hook("version-go-back"), "ask", wait=100), click(hook("version-go-back-confirm"), "r", wait=300, capture=[
                q("text", hook("version-go-back-refused")), q("code", hook("version-go-back-refused"), "attr", attr="data-code")])])
        cap = out["captures"]["r"]
        self.assertEqual(cap["code"], "version_stale")
        self.assertIn("moved to another version", cap["text"])

    def test_a_first_version_has_no_versions_list_and_no_menu_item(self):
        out = run_page("kennel", routes=rites_web.kennel_routes([dog("u-1", version_no=1)]), **SIGNED, reducedMotion=True,
                       actions=[click("[data-hook='dog-avatar']", "open", wait=250), click("[role='tab'][data-tab='coach']", "coach", wait=400, capture=[
                           q("hidden", "[data-hook='studio-versions-open']", "hidden"), q("title", hook("coach-versions-title"), "count"),
                           q("rows", hook("version"), "count")])])
        self.assertTrue(out["captures"]["coach"]["hidden"])
        self.assertEqual((out["captures"]["coach"]["title"], out["captures"]["coach"]["rows"]), (0, 0))


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheUndoOnTheCardATrainingLeaves(unittest.TestCase):
    def test_the_card_carries_the_undo_and_it_goes_back_to_the_version_just_retired(self):
        trained = rites_web.payloads()["trained"]
        self.assertTrue(trained["undo"]["available"])
        fresh = trained["new"]["id"]
        card = plans_web.cards()["found"]
        rts = plans_web.routes(**{"POST /hounds/u-1/train/fine-tune": plans_web.job(card, "minor"),
                                  "POST /hounds/u-1/train/plan/apply": [200, trained],
                                  f"POST /hounds/{fresh}/revert": [200, payloads()["done"]]})
        out = run_page("kennel", routes=rts, **SIGNED, reducedMotion=True, actions=[
            click(plans_web.OPEN, "a"), click(hook("training-fine-tune"), "plan", wait=300), click(hook("plan-apply"), "card", wait=500, capture=[
                q("undo", hook("training-undo"), "texts"), q("block", hook("training-undo-block"))]),
            click(hook("training-undo"), "ask", wait=150, capture=[q("ask", hook("training-undo-ask"))]),
            click(hook("training-undo-confirm"), "done", wait=400, capture=[q("done", hook("training-undo-done")), q("open", hook("training-undo-open"), "texts")])])
        self.assertEqual(out["captures"]["card"]["undo"], [trained["undo"]["label"]])
        self.assertIn("Go back to version %d?" % trained["undo"]["to_version"], out["captures"]["ask"]["ask"])
        posts = [p for p in out["posts"] if p["url"].endswith("/revert")]
        self.assertEqual(len(posts), 1)
        self.assertTrue(posts[0]["url"].endswith(f"/hounds/{fresh}/revert"))
        body = posts[0]["body"] if isinstance(posts[0]["body"], dict) else json.loads(posts[0]["body"])
        self.assertEqual((body["version_no"], body["current_id"], body["confirm"]), (trained["undo"]["to_version"], fresh, True))
        self.assertTrue(out["captures"]["done"]["done"])
        self.assertTrue(out["captures"]["done"]["open"][0].startswith("Open version"))


@unittest.skipUnless(HAS_NODE, "node is not installed")
class OnTheHoundPage(unittest.TestCase):
    HID = interact_web.HID

    def routes(self, **kw):
        r = interact_web.dog_routes(**kw)
        r[f"/hounds/{self.HID}/versions"] = [200, payloads()["listed"]]
        return r

    def test_the_owner_of_a_hound_with_more_than_one_version_sees_the_list(self):
        out = interact_web.page(self.routes(owner=True), queries=[
            q("section", hook("dog-versions-section"), "hidden"), q("rows", hook("version"), "count"),
            q("buttons", hook("version-go-back"), "texts")])
        f = out["final"]
        self.assertFalse(f["section"])
        self.assertEqual((f["rows"], f["buttons"]), (2, ["Go back to this version"]))
        self.assertIn(f"/hounds/{self.HID}/versions", out["gets"])

    def test_a_visitor_never_sees_it_and_the_page_never_asks_for_it(self):
        out = interact_web.page(self.routes(owner=False), queries=[q("section", hook("dog-versions-section"), "hidden")])
        self.assertTrue(out["final"]["section"])
        self.assertNotIn(f"/hounds/{self.HID}/versions", out["gets"])

    def test_a_single_version_keeps_the_section_hidden(self):
        r = self.routes(owner=True)
        single = json.loads(json.dumps(payloads()["listed"]))
        single["versions"] = single["versions"][-1:]
        r[f"/hounds/{self.HID}/versions"] = [200, single]
        out = interact_web.page(r, queries=[q("section", hook("dog-versions-section"), "hidden")])
        self.assertTrue(out["final"]["section"])


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheChalkLineOnAPlanCard(unittest.TestCase):
    LINE = "It leans on favourites: 13 of its 16 bets were on favourites, 13 of them at -150 or worse."

    def test_a_gematria_hounds_card_says_how_it_leans_with_and_without_a_change_to_offer(self):
        for which in ("found", "none"):
            with self.subTest(card=which):
                card = dict(plans_web.cards()[which], chalk={"text": self.LINE, "chalk": True})
                rts = plans_web.routes(**{"POST /hounds/u-1/train/fine-tune": plans_web.job(card, "minor")})
                out = run_page("kennel", routes=rts, **SIGNED, reducedMotion=True, actions=[
                    click(plans_web.OPEN, "a"), click(hook("training-fine-tune"), "plan", wait=300, capture=[q("chalk", hook("plan-chalk"))])])
                self.assertEqual(out["captures"]["plan"]["chalk"], self.LINE)

    def test_an_ordinary_hounds_card_has_no_chalk_line(self):
        rts = plans_web.routes(**{"POST /hounds/u-1/train/fine-tune": plans_web.job(plans_web.cards()["found"], "minor")})
        out = run_page("kennel", routes=rts, **SIGNED, reducedMotion=True, actions=[
            click(plans_web.OPEN, "a"), click(hook("training-fine-tune"), "plan", wait=300, capture=[q("chalk", hook("plan-chalk"), "count")])])
        self.assertEqual(out["captures"]["plan"]["chalk"], 0)


class TheStaticPages(unittest.TestCase):
    def test_the_hound_page_has_the_versions_section_hidden_until_the_owner_has_more_than_one_version(self):
        html = (WEB / "hound.html").read_text(encoding="utf-8")
        self.assertRegex(html, r'data-hook="dog-versions-section" hidden>')
        self.assertIn('data-hook="dog-versions"', html)
        self.assertEqual(len(re.findall(r'role="tab" data-tab="', html)), 6)         # the page's six tabs are unchanged
        js = (WEB / "js" / "dog-kit.js").read_text(encoding="utf-8")
        self.assertIn("mountVersions", js)
        self.assertIn("kit.is_owner", js)

    def test_the_studio_holds_the_versions_list_in_the_coach_tab_and_a_menu_item_hidden_by_default(self):
        # 2026-10-29: no Versions tab; the list is the foot of Coach and the ... menu has an item that brings it into view
        html = (WEB / "kennel.html").read_text(encoding="utf-8")
        self.assertNotIn('data-tab="versions"', html)
        self.assertRegex(html, r'data-hook="studio-versions-open" hidden>Versions<')
        self.assertIn('data-hook="studio-versions"', html)
        self.assertLess(html.index('data-tabpanel="coach"'), html.index('data-hook="studio-versions"'))

    def test_the_words_on_the_page_follow_the_copy_rules(self):
        text = (WEB / "js" / "dog-versions.js").read_text(encoding="utf-8")
        said = [a or b for a, b in re.findall(r'"([^"\n]{12,})"|`([^`\n]{12,})`', text)]
        low = " ".join(t for t in said if " " in t).lower()                       # sentences, not hook names and paths
        self.assertIn("go back to version", low)
        for word in ("beta", "nothing cleared the bar", "profit", "guarantee"):
            self.assertNotIn(word, low)
        self.assertIsNone(re.search(r"\b(new|dog|dogs)\b", low))


if __name__ == "__main__":
    unittest.main()
