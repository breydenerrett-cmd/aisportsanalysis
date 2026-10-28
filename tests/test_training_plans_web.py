"""The training screen's two choices on the page, run for real under node (tests/hounds_web_harness.mjs): Fine-tune and Full rebuild.

The plan cards are made by the real Python (training_plans.fine_tune / full_rebuild over a temp database, with a fake replay and a fake
client), so a drift between the server and the page fails here. Skipped when node is not installed.
"""

from __future__ import annotations

import json
import unittest

from tests.hounds_web_runner import HAS_NODE, run_page
from tests import test_hounds_interact_web as interact_web
from tests import test_hounds_rites_web as rites_web
from tests.test_training_plans import Base, FakeClient, standard_responder

hook, q = interact_web.hook, interact_web.q
click, kennel_routes, dog, SIGNED = rites_web.click, rites_web.kennel_routes, rites_web.dog, rites_web.SIGNED
OPEN = "[data-hook='dog-action-train']"
BANNED = ("beta", "nothing cleared the bar", "bet check")


def _flat(spec, days, now):
    return {"record": {"graded": 40, "wins": 20, "losses": 20, "pushes": 0}, "units_average_price": -4.0, "days": days, "picks": []}


class World(Base):
    runTest = lambda self: None            # noqa: E731 -- a TestCase used as a fixture, never run

    @classmethod
    def build(cls):
        w = cls()
        w.setUp()
        try:
            found = w.fine()
            none = w.fine(replay_fn=_flat)
            w.ledger_book.rows()                       # the rebuild below is the first of the day
            rebuilt, _c = w.rebuild(client=FakeClient(standard_responder()))
            return {"found": found, "none": none, "rebuilt": rebuilt}
        finally:
            w.doCleanups()


_CARDS: dict = {}


def cards():
    if not _CARDS:
        _CARDS.update(World.build())
    return _CARDS


def routes(**over):
    r = kennel_routes([dog("u-1")])
    r["/hounds/u-1/train/options"] = [200, {"fine_tune": {"available": True}, "rebuild": {"available": True, "reason": None, "used_today": 0,
                                                                                               "limit_per_day": 1, "left_today": 1}}]
    r.update(over)
    return r


def job(card, kind):
    return [200, {"job_id": "j" * 24, "kind": kind, "state": "done", "stage": "Done", "result": card, "error": None}]


def flow(rts, actions):
    return run_page("kennel", routes=rts, **SIGNED, reducedMotion=True, actions=actions)


def caps():
    return [q("kind", ".rt-sheet", "attr", attr="data-hook"), q("buttons", hook("rites-actions") + " button", "texts"),
            q("found", hook("plan-card"), "attr", attr="data-found"), q("lines", hook("plan-explanation") + " p", "texts"),
            q("changed", hook("plan-changed") + " li", "texts"), q("label", hook("plan-rehearsal-label")), q("before", hook("plan-before")),
            q("after", hook("plan-after")), q("sample", hook("plan-sample")), q("none", hook("plan-none")), q("notBetter", hook("plan-not-better")),
            q("others", hook("plan-choice"), "count"), q("usage", hook("plan-usage")), q("all", hook("plan-card"))]


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheChoiceScreen(unittest.TestCase):
    def test_it_offers_the_two_choices_and_says_how_many_rebuilds_are_left(self):
        out = flow(routes(), [click(OPEN, "a", wait=300, capture=[
            q("buttons", hook("training-options") + " button", "texts"), q("note", hook("training-rebuild-note")), q("all", ".rt-sheet")])])
        cap = out["captures"]["a"]
        self.assertEqual(cap["buttons"], ["Fine-tune", "Full rebuild"])
        self.assertIn("1 of 1", cap["note"])
        self.assertNotIn("beta", cap["all"].lower())

    def test_an_unavailable_rebuild_is_said_before_the_tap_and_cannot_be_tapped(self):
        rts = routes(**{"/hounds/u-1/train/options": [200, {"fine_tune": {"available": True}, "rebuild": {
            "available": False, "reason": "The full rebuild is unavailable right now. Fine-tune still works, and you can try the rebuild again later.",
            "used_today": 0, "limit_per_day": 1, "left_today": 1}}]})
        out = flow(rts, [click(OPEN, "a", wait=300, capture=[q("note", hook("training-rebuild-note")),
                                                              q("disabled", hook("training-rebuild"), "attr", attr="disabled")])])
        cap = out["captures"]["a"]
        self.assertIn("unavailable right now", cap["note"])
        self.assertIsNotNone(cap["disabled"])


@unittest.skipUnless(HAS_NODE, "node is not installed")
class FineTuneOnThePage(unittest.TestCase):
    def test_the_plan_shows_before_and_after_labelled_as_a_rehearsal_and_apply_sends_only_the_plan_id(self):
        card = cards()["found"]
        rts = routes(**{"POST /hounds/u-1/train/fine-tune": job(card, "minor"), "POST /hounds/u-1/train/plan/apply": [200, rites_web.payloads()["trained"]]})
        out = flow(rts, [click(OPEN, "a"), click(hook("training-fine-tune"), "plan", wait=300, capture=caps()),
                         click(hook("plan-apply"), "done", wait=400, capture=[q("kind", ".rt-sheet", "attr", attr="data-hook")])])
        cap = out["captures"]["plan"]
        self.assertEqual((cap["kind"], cap["found"]), ("training-plan-sheet", "1"))
        self.assertIn("not counted", cap["label"])
        self.assertIn("40 graded bets", cap["before"])
        self.assertIn("30 graded bets", cap["after"])
        self.assertTrue(cap["lines"])
        self.assertEqual(cap["buttons"], ["Not now", "Apply"])
        posts = [p for p in out["posts"] if "plan/apply" in p["url"]]
        self.assertEqual(len(posts), 1)
        body = posts[0]["body"] if isinstance(posts[0]["body"], dict) else json.loads(posts[0]["body"])
        self.assertEqual(sorted(body), ["basis", "confirm", "plan_id"])
        self.assertEqual(body["plan_id"], card["plan_id"])
        self.assertNotIn("spec", json.dumps(body))
        self.assertEqual(out["captures"]["done"]["kind"], "training-reveal")
        low = cap["all"].lower()
        for word in BANNED:
            self.assertNotIn(word, low)

    def test_nothing_that_is_not_better_is_shown_and_the_rebuild_is_offered(self):
        card = cards()["none"]
        rts = routes(**{"POST /hounds/u-1/train/fine-tune": job(card, "minor"), "POST /hounds/u-1/train/rebuild": job(cards()["rebuilt"], "rebuild")})
        out = flow(rts, [click(OPEN, "a"), click(hook("training-fine-tune"), "none", wait=300, capture=caps()),
                         click(hook("plan-to-rebuild"), "rebuilt", wait=300, capture=caps())])
        none = out["captures"]["none"]
        self.assertEqual(none["found"], "0")
        self.assertIn("None of the", none["none"])
        self.assertEqual(none["buttons"], ["Close", "Full rebuild"])
        self.assertEqual(none["changed"], [])
        self.assertTrue([p for p in out["posts"] if p["url"].endswith("/train/rebuild")])
        self.assertEqual(out["captures"]["rebuilt"]["found"], "1")


@unittest.skipUnless(HAS_NODE, "node is not installed")
class FullRebuildOnThePage(unittest.TestCase):
    def test_the_rebuild_card_has_the_rehearsal_the_other_options_and_the_days_allowance(self):
        card = cards()["rebuilt"]
        rts = routes(**{"POST /hounds/u-1/train/rebuild": job(card, "rebuild")})
        out = flow(rts, [click(OPEN, "a"), click(hook("training-rebuild"), "plan", wait=300, capture=caps())])
        cap = out["captures"]["plan"]
        self.assertEqual(cap["found"], "1")
        self.assertIn("-4", cap["before"])
        self.assertIn("graded bets", cap["after"])
        self.assertIn("Full rebuilds left today", cap["usage"])
        self.assertEqual(cap["others"], (1 + len(card["runners_up"])) if card["runners_up"] else 0)

    def test_a_refused_rebuild_shows_the_servers_own_sentence(self):
        refusal = [429, {"detail": {"error": "daily_limit", "message": "You have used today's 1 full rebuild. Fine-tune is still open, and the rebuild resets tomorrow (UTC)."}}]
        out = flow(routes(**{"POST /hounds/u-1/train/rebuild": refusal}), [click(OPEN, "a"), click(hook("training-rebuild"), "r", wait=300, capture=[
            q("text", hook("training-refused")), q("code", hook("training-refused"), "attr", attr="data-code")])])
        cap = out["captures"]["r"]
        self.assertEqual(cap["code"], "daily_limit")
        self.assertIn("used today's 1 full rebuild", cap["text"])


if __name__ == "__main__":
    unittest.main()
