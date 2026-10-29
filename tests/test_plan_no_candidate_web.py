"""The page's answer to a rebuild that comes back with nothing (web/js/dog-plans.js), owner 2026-10-29: "this doesn't feel very helpful".

Before, the card said one sentence, showed a rehearsal block with "Updated rules, same days: Not rehearsed / 0 graded bets in the rehearsal",
and had only a Close button. Now it must:

  * SAY WHY, in 2 to 4 short lines the server wrote from what the rebuild really did (the page works out nothing);
  * NOT SHOW a side of the rehearsal that was never rehearsed;
  * OFFER THE NEXT STEP: Try fine-tune (the flow that already exists), Ask the coach (the studio's Ask tab), and Close;
  * keep every word as text, and say nothing about winning.

The card is made by the real Python (training_plans.full_rebuild over a temp database, fake client) so a drift between the server and the page
fails here. Skipped when node is not installed.
"""

from __future__ import annotations

import json
import unittest

from tests.hounds_web_runner import HAS_NODE, run_js
from tests.test_fetch_game import OPEN, PRELUDE, SHEET_Q, click, flow, hook, job, q, routes
from tests.test_rebuild_no_candidate import TheWhy, tweak_responder
from tests.test_training_plans import Base, FakeClient

BANNED = ("beta", "counted as one", "nothing cleared the bar", "bet check", "will win", "guarantee")


class World(Base):
    runTest = lambda self: None            # noqa: E731 -- a TestCase used as a fixture, never run

    @classmethod
    def build(cls):
        w = cls()
        w.setUp()
        try:
            nothing, _c = w.rebuild(client=FakeClient(tweak_responder(w.dog_obj().spec)))
            return {"nothing": nothing, "mixed": TheWhy.run_mixed(w)}          # neither uses up the day, so one hound can make both
        finally:
            w.doCleanups()


_CARDS: dict = {}


def cards():
    if not _CARDS:
        _CARDS.update(World.build())
    return _CARDS


def caps():
    return [q("sheet", ".rt-sheet", "attr", attr="data-hook"), q("found", hook("plan-card"), "attr", attr="data-found"), q("kind", hook("plan-card"), "attr", attr="data-kind"),
            q("message", hook("plan-none")), q("why", hook("plan-why") + " li", "texts"), q("buttons", hook("rites-actions") + " button", "texts"),
            q("before", hook("plan-before")), q("afterRows", hook("plan-after"), "count"), q("sides", hook("plan-rehearsal-sides") + " dt", "texts"),
            q("sample", hook("plan-sample")), q("all", hook("plan-card"))]


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheNothingCard(unittest.TestCase):
    def open_card(self, which="mixed", more=()):
        rts = routes(**{"POST /hounds/u-1/train/rebuild": job("done", result=cards()[which]),
                        "POST /hounds/u-1/train/fine-tune": job("done", result=rites_web_fine_none())})
        return flow(rts, [click(OPEN, "a"), click(hook("training-rebuild"), "card", wait=400, capture=caps()), *more], reducedMotion=True)

    def test_it_says_why_in_short_lines_and_offers_the_next_steps(self):
        cap = self.open_card()["captures"]["card"]
        card = cards()["mixed"]
        self.assertEqual((cap["sheet"], cap["found"], cap["kind"]), ("training-plan-sheet", "0", "rebuild"))
        self.assertEqual(cap["why"], card["why"]["lines"])                              # the server's own words, nothing added
        self.assertTrue(2 <= len(cap["why"]) <= 4)
        self.assertIn("did not use up one of today's rebuilds", cap["message"])
        self.assertEqual(cap["buttons"], ["Close", "Ask the coach", "Try fine-tune"])
        low = cap["all"].lower()
        for word in BANNED:
            self.assertNotIn(word, low)

    def test_there_is_no_row_for_rules_that_were_never_rehearsed(self):
        cap = self.open_card()["captures"]["card"]
        self.assertEqual(cap["afterRows"], 0)
        self.assertEqual(cap["sides"], [f"Rules it has now, last {cards()['mixed']['rehearsal']['days']} days"])
        self.assertNotIn("Not rehearsed", cap["all"])
        self.assertNotIn("Updated rules", cap["all"])
        self.assertNotRegex(cap["all"], r"(?<!\d)0 graded bets")             # the old placeholder for a side that was never rehearsed
        self.assertIn("graded bets in the rehearsal of the rules it has now", cap["all"])

    def test_try_fine_tune_starts_the_fine_tune_that_already_exists(self):
        out = self.open_card(more=[click(hook("plan-try-fine-tune"), "ft", wait=500, capture=caps())])
        posts = [p["url"] for p in out["posts"] if p["url"].endswith("/train/fine-tune")]
        self.assertEqual(len(posts), 1)
        cap = out["captures"]["ft"]
        self.assertEqual((cap["sheet"], cap["kind"]), ("training-plan-sheet", "minor"))
        self.assertEqual(cap["buttons"], ["Close", "Full rebuild"])                     # the fine-tune's own card, with its own next step
        self.assertEqual(cap["afterRows"], 0)                                           # it found nothing either: no phantom "Updated rules" row
        self.assertNotIn("Not rehearsed", cap["all"])

    def test_ask_the_coach_closes_the_sheet_and_hands_over_to_the_studio(self):
        out = self.open_card(more=[click(hook("plan-ask-coach"), "ask", wait=300, capture=[q("sheet", ".rt-sheet", "count"), q("layers", hook("rites-layer"), "count")])])
        cap = out["captures"]["ask"]
        self.assertEqual((cap["sheet"], cap["layers"]), (0, 0))
        self.assertEqual([u for u in out["navigations"] if "tab=ask" in u], [])         # on the kennel the studio listens: no page change

    def test_close_still_closes(self):
        out = self.open_card(more=[click(hook("plan-close"), "closed", wait=300, capture=[q("sheet", ".rt-sheet", "count")])])
        self.assertEqual(out["captures"]["closed"]["sheet"], 0)
        self.assertEqual([p for p in out["posts"] if "fine-tune" in p["url"]], [])

    def test_a_rebuild_that_was_refused_before_it_ran_is_not_this_card(self):
        refusal = [429, {"detail": {"error": "daily_limit", "message": "You have used today's 1 full rebuild. Fine-tune is still open, and the rebuild resets tomorrow (UTC)."}}]
        out = flow(routes(**{"POST /hounds/u-1/train/rebuild": refusal}), [click(OPEN, "a"), click(hook("training-rebuild"), "r", wait=300, capture=SHEET_Q)], reducedMotion=True)
        self.assertEqual(out["captures"]["r"]["sheet"], "training-refused-sheet")


def rites_web_fine_none():
    """What the server sends when a fine-tune finds nothing, after this change (the rehearsal has no updated side)."""
    return {"kind": "minor", "found": False, "name": "Rusty Pup", "message": "None of the small changes did better in the rehearsal.", "rebuild_offer": True,
            "rehearsal": {"label": "Rehearsal (hindsight, not counted in the record)", "days": 30, "counted": False,
                          "before": {"graded": 40, "wins": 20, "losses": 20, "pushes": 0, "units": -4.0, "per_bet": -0.1}, "after": None,
                          "sample_text": "40 graded bets in the rehearsal of the rules it has now.", "note": "A rehearsal replays the rules on games that already happened."}}


@unittest.skipUnless(HAS_NODE, "node is not installed")
class ThePieces(unittest.TestCase):
    def run_it(self, body, **opts):
        head = f"globalThis.OPTS = {json.dumps(opts)};\n"
        return run_js(head + PRELUDE + 'const DP = await import("./dog-plans.js");\n' + body, viewer=None)

    def test_ask_the_coach_sends_the_studio_tab_event_with_the_hound_and_the_ask_tab(self):
        got = self.run_it('''
document.querySelector = (sel) => (sel.includes("studio") ? new El("aside") : null);
const ok = DP.askCoach({ id: "u-9", name: "Rusty Pup" });
out({ ok, events: events.map((e) => ({ type: e.type, detail: e.detail })), href: window.location.href });''')
        self.assertTrue(got["ok"])
        self.assertEqual(got["events"], [{"type": "linehound:studio-tab", "detail": {"id": "u-9", "tab": "ask"}}])
        self.assertEqual(got["href"], "")

    def test_off_the_kennel_page_ask_the_coach_is_a_link_to_the_kennels_ask_tab(self):
        got = self.run_it('''
const ok = DP.askCoach({ id: "u/9 x" });
out({ ok, events: events.length, href: window.location.href });''')
        self.assertTrue(got["ok"])
        self.assertEqual(got["events"], 0)
        self.assertEqual(got["href"], "kennel.html?dog=u%2F9%20x&tab=ask")

    def test_without_a_hound_it_does_nothing(self):
        got = self.run_it('''out({ a: DP.askCoach(null), b: DP.askCoach({}), events: events.length, href: window.location.href });''')
        self.assertEqual((got["a"], got["b"], got["events"], got["href"]), (False, False, 0, ""))

    def test_the_three_buttons_resolve_the_three_decisions(self):
        got = self.run_it('''
const card = { kind: "rebuild", found: false, message: "m", why: { lines: ["a", "b"] }, rehearsal: { days: 14, before: null, after: null, counted: false } };
const seen = [];
for (const name of ["plan-close", "plan-ask-coach", "plan-try-fine-tune"]) {
  const body = new El("div"); const p = DP.showPlan({ body, card });
  one(body, name).click(); seen.push((await p).action);
}
const body = new El("div"); const p = DP.showPlan({ body, card: { kind: "minor", found: false, message: "m", rebuild_offer: true } });
out({ seen, minor: byHook(body, "rites-actions")[0].children.map((b) => b.textContent) });''')
        self.assertEqual(got["seen"], ["close", "ask", "fine-tune"])
        self.assertEqual(got["minor"], ["Close", "Full rebuild"])

    def test_why_lines_are_text_capped_at_four_and_an_empty_why_draws_nothing(self):
        got = self.run_it('''
const evil = '<img src=x onerror="alert(1)">';
const block = DP.whyBlock({ lines: [evil, "b", "c", "d", "e", "", 7] });
out({ n: block.children.length, first: block.children[0].textContent, kids: block.children[0].children.length, none: [DP.whyBlock(null), DP.whyBlock({}), DP.whyBlock({ lines: [] })] });''')
        self.assertEqual(got["n"], 4)
        self.assertEqual(got["first"], '<img src=x onerror="alert(1)">')
        self.assertEqual(got["kids"], 0)
        self.assertEqual(got["none"], [None, None, None])

    def test_the_rehearsal_block_drops_the_updated_side_only_when_there_is_none(self):
        got = self.run_it('''
const one_ = DP.rehearsalBlock({ days: 14, before: { graded: 12, wins: 3, losses: 9, pushes: 0, units: -5.67 }, after: null, sample_text: "s" });
const two = DP.rehearsalBlock({ days: 14, before: { graded: 12, wins: 3, losses: 9, pushes: 0, units: -5.67 }, after: { graded: 1, wins: 1, losses: 0, pushes: 0, units: 1 }, sample_text: "s" });
out({ a: byHook(one_, "plan-after").length, b: byHook(two, "plan-after").length, c: byHook(two, "plan-after")[0].textContent, d: one(one_, "plan-before").textContent });''')
        self.assertEqual((got["a"], got["b"]), (0, 1))
        self.assertEqual(got["c"], "1 graded bet, 1-0, +1 units")
        self.assertEqual(got["d"], "12 graded bets, 3-9, -5.67 units")


if __name__ == "__main__":
    unittest.main()
