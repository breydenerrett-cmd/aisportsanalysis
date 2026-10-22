"""The Unleash reveal in the kennel studio (web/js/dog-fire.js, web/css/dog-kit.css), run for real under node.

The payload the page reads is built by the real ``unleash.unleash`` over fixture boards (tests/test_hounds_unleash.py), so a drift between
the server and the page fails here. Skipped without node; the static checks need none.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import unittest

from src.hounds.interact import unleash
from tests.hounds_web_runner import HAS_NODE, WEB
from tests._hounds_user_fixtures import hound
from tests.test_hounds_unleash import NOW, OWNER, _Case, day_rows, game
from tests import test_kennel_page as K
from tests.hounds_web_runner import run_page
from tests.test_kennel_page import SIGNED, dog, q


def payload(rows=None, dog=None, **kw) -> dict:
    case = _Case("setUp")
    case.setUp()
    try:
        out = case.go(dog() if callable(dog) else dog, rows=rows, **kw)
    finally:
        case._tmp.cleanup()
    return json.loads(json.dumps(out))


def routes(data, **over):
    r = K.TheStudio().routes([dog("u-1")])
    r["POST /hounds/u-1/unleash"] = [200, data]
    r.update(over)
    return r


HOOK = "[data-hook='{}']".format
OPEN = dict(do="click", sel=HOOK("dog-action-fire"), label="open", wait=300)


def read(name):
    return (WEB / name).read_text(encoding="utf-8")


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheRevealInTheStudio(unittest.TestCase):
    DAY = [q("title", HOOK("unleash-title")), q("headline", HOOK("unleash-headline")), q("steps", HOOK("unleash-steps") + " li", "texts"),
           q("picks", HOOK("unleash-pick"), "count"), q("sel", HOOK("unleash-pick") + " .dk-pick__sel", "texts"),
           q("price", HOOK("unleash-pick-price"), "texts"), q("games", HOOK("unleash-pick") + " .dk-pick__game", "texts"),
           q("label", HOOK("unleash-before-label")), q("before", HOOK("unleash-before-item"), "count"),
           q("outcomes", HOOK("unleash-outcome"), "texts"), q("noboard", HOOK("unleash-noboard") + " li", "texts"),
           q("working", HOOK("unleash-working"), "count"), q("btn", HOOK("fire-btn")), q("disabled", HOOK("fire-btn"), "disabled"),
           q("preview", HOOK("fire-headline"), "count")]

    def test_the_card_button_starts_the_hound_and_reveals_picks_then_the_before_list(self):
        data = payload()
        out = run_page("kennel", routes=routes(data), **SIGNED, actions=[dict(OPEN, capture=self.DAY)])
        self.assertEqual([p["url"] for p in out["posts"] if "/hounds/u-1/" in p["url"]], ["/hounds/u-1/unleash"])   # the new route, not the preview
        c = out["captures"]["open"]
        self.assertEqual(c["title"], "Underdog Gus's day")
        self.assertEqual(c["picks"], 2)
        self.assertEqual(c["sel"], ["Boston Red Sox to win", "Toronto Blue Jays to win"])
        self.assertIn("+125", c["price"][0])
        self.assertIn("Stake 1 unit ($10)", c["price"][0])             # game, side, price and stake
        self.assertEqual(c["games"][0], "Boston Red Sox @ Seattle Mariners")
        self.assertEqual(c["steps"], ["Read today's board", "Checked 6 games", "Locked 2 picks"])
        self.assertEqual(c["label"], "Before you unleashed. Not on its record.")
        self.assertEqual(c["before"], 2)
        self.assertIn("Would have won", c["outcomes"])
        self.assertEqual(c["noboard"], ["New York Mets @ Atlanta Braves no board saved for this game"])
        self.assertEqual((c["working"], c["preview"], c["disabled"]), (0, 0, False))

    def test_every_stake_is_in_the_viewers_sizing_never_the_servers_ten_dollar_unit(self):
        """The payload carries units only. The picks and the before-list print the stake in the viewer's own terms: dollars at
        their unit, or a share of their bankroll in percent mode (a pick has no balance of its own to turn into dollars)."""
        data = payload()
        self.assertTrue(all("stake_usd" not in p for p in data["picks"] + data["before"]))
        for viewer, want in (({"mode": "fixed", "unit_usd": 50, "pct": None, "start_usd": 5000}, "Stake 1 unit ($50)"),
                             ({"mode": "fixed", "unit_usd": 1000, "pct": None, "start_usd": 100000}, "Stake 1 unit ($1,000)"),
                             ({"mode": "percent", "unit_usd": None, "pct": 2, "start_usd": 5000}, "Stake 1 unit (2% of bankroll)")):
            with self.subTest(viewer=viewer):
                out = run_page("kennel", viewer=viewer, routes=routes(data), **SIGNED, actions=[dict(OPEN, capture=[
                    q("price", HOOK("unleash-pick-price"), "texts"), q("before", HOOK("unleash-before-item"), "texts")])])
                c = out["captures"]["open"]
                self.assertIn(want, c["price"][0])
                self.assertTrue(all("$10" not in t for t in c["price"] + c["before"]), c)

    def test_while_the_request_runs_the_dog_sniffs_and_the_steps_wait_with_no_numbers_made_up(self):
        data = payload()
        out = run_page("kennel", routes=routes(data), delay={"POST /hounds/u-1/unleash": 500}, **SIGNED, actions=[
            dict(OPEN, wait=150, capture=self.DAY),
            dict(do="wait", label="after", wait=700, capture=self.DAY)])
        mid, after = out["captures"]["open"], out["captures"]["after"]
        self.assertEqual(mid["working"], 1)
        self.assertEqual(mid["steps"], ["Reading today's board", "Checking today's games", "Locking picks"])
        self.assertEqual((mid["picks"], mid["before"], mid["disabled"]), (0, 0, True))     # nothing is shown before the server answers
        self.assertEqual((after["working"], after["picks"], after["disabled"]), (0, 2, False))

    def test_a_second_tap_on_a_running_hound_shows_the_day_with_nothing_newly_placed(self):
        first = payload()
        again = dict(first, already_running=True, placed_now=0, picks=[dict(p, placed_now=False) for p in first["picks"]],
                     headline="Underdog Gus is already running. Here is today.")
        out = run_page("kennel", routes=routes(again), **SIGNED, actions=[dict(OPEN, capture=[
            q("headline", HOOK("unleash-headline")), q("chips", HOOK("unleash-pick") + " .dk-chip", "texts")])])
        c = out["captures"]["open"]
        self.assertEqual(c["headline"], "Underdog Gus is already running. Here is today.")
        self.assertIn("On its record", c["chips"])
        self.assertNotIn("Placed now", c["chips"])

    def test_an_empty_day_says_so_and_keeps_the_before_list(self):
        data = payload(rows=[r for r in day_rows() if r["event_id"] not in ("ahead1", "ahead2")])
        out = run_page("kennel", routes=routes(data), **SIGNED, actions=[dict(OPEN, capture=self.DAY)])
        c = out["captures"]["open"]
        self.assertEqual(c["picks"], 0)
        self.assertIn("Nothing on today's board fits its rule yet", c["headline"])
        self.assertEqual(c["steps"][-1], "Nothing to lock yet")
        self.assertEqual(c["before"], 2)

    def test_a_refusal_shows_the_servers_words_and_no_half_drawn_day(self):
        refusal = [409, {"detail": {"error": "not_running", "message": "this dog is retired; only a running dog can be unleashed"}}]
        out = run_page("kennel", routes=routes({}, **{"POST /hounds/u-1/unleash": refusal}), **SIGNED, actions=[dict(OPEN, capture=[
            q("status", HOOK("fire-status")), q("working", HOOK("unleash-working"), "count"), q("picks", HOOK("unleash-pick"), "count"),
            q("disabled", HOOK("fire-btn"), "disabled")])])
        c = out["captures"]["open"]
        self.assertIn("only a running dog can be unleashed", c["status"])
        self.assertEqual((c["working"], c["picks"], c["disabled"]), (0, 0, False))

    def test_names_that_look_like_markup_are_text_not_elements(self):
        evil = "<img src=x onerror=alert(1)>"
        rows = game("ahead1", "2026-10-20T17:30:00Z", 125, -145, "2026-10-20T23:10:00Z", "<script>boom()</script>", evil)
        rows += game("fin", "2026-10-20T12:50:00Z", 120, -140, "2026-10-20T15:10:00Z", "A&amp;B <b>Rangers</b>", evil + "Tigers")
        data = payload(rows=rows)
        out = run_page("kennel", routes=routes(data), **SIGNED, actions=[dict(OPEN, capture=[
            q("games", HOOK("unleash-pick") + " .dk-pick__game", "texts"), q("sel", HOOK("unleash-pick") + " .dk-pick__sel", "texts"),
            q("before", HOOK("unleash-before-item"), "texts"),
            q("imgs", HOOK("fire-result") + " img", "count"), q("scripts", HOOK("fire-result") + " script", "count"),
            q("bold", HOOK("fire-result") + " b", "count")])])
        c = out["captures"]["open"]
        self.assertEqual((c["imgs"], c["scripts"], c["bold"]), (0, 0, 0))
        self.assertEqual(c["games"], [f"{evil} @ <script>boom()</script>"])
        self.assertTrue(any("A&amp;B <b>Rangers</b>" in t for t in c["before"]), c["before"])


def batch_result(picks) -> dict:
    """What POST /hounds/{id}/manual/batch answers, from the real ``manual.record_batch`` over the same fixture day."""
    from src.hounds.interact import fire, manual
    case = _Case("setUp")
    case.setUp()
    try:
        dog = case.dog(hound("u-unl9", created_at="2026-10-20T06:00:00Z", max_bets_per_day=1))
        case.go(dog)
        games = fire.load_games(["MLB"], NOW, lambda _d, _s: day_rows())
        out = manual.record_batch(dog, OWNER, picks, now=NOW, games=games, ledger=case.manual_ledger, rule_ledger=case.ledger)
    finally:
        case._tmp.cleanup()
    return json.loads(json.dumps(out))


def limited_dog():
    case = _Case("setUp")
    case.setUp()
    try:
        return case.dog(hound("u-unl9", created_at="2026-10-20T06:00:00Z", max_bets_per_day=1))
    finally:
        case._tmp.cleanup()


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheBulkManualButton(unittest.TestCase):
    """"Add the other N as manual picks" at the top of the picks that were not placed (owner addition 2026-10-21)."""

    def day(self):
        return payload(dog=limited_dog())

    BULK = [q("btn", HOOK("unleash-bulk")), q("head", HOOK("unleash-others") + " .hd-h3"), q("items", HOOK("unleash-other"), "count"),
            q("chips", HOOK("unleash-other-chip"), "texts"), q("result", HOOK("unleash-bulk-result")), q("sel", HOOK("unleash-other") + " .dk-pick__sel", "texts"),
            q("placed", HOOK("unleash-pick"), "count")]

    def test_it_sits_above_the_unplaced_picks_and_names_how_many(self):
        out = run_page("kennel", routes=routes(self.day()), **SIGNED, actions=[dict(OPEN, capture=self.BULK)])
        c = out["captures"]["open"]
        self.assertEqual(c["btn"], "Add the other 1 as manual picks")
        self.assertEqual((c["head"], c["items"], c["placed"]), ("Other picks on the board", 1, 1))
        self.assertEqual(c["sel"], ["Toronto Blue Jays to win"])
        self.assertEqual(c["chips"], ["Over today's limit of 1 a day"])
        self.assertEqual(c["result"], "")
        # the button comes before the list it acts on
        html_order = [h for h in out["hooks"] if h in ("unleash-bulk", "unleash-others-list")]
        self.assertEqual(html_order, ["unleash-bulk", "unleash-others-list"])

    def test_one_tap_sends_one_batch_request_and_shows_the_result_line(self):
        answer = batch_result([{"event_id": "ahead2", "market": "moneyline"}, {"event_id": "play", "market": "moneyline"}])
        out = run_page("kennel", routes=routes(self.day(), **{"POST /hounds/u-1/manual/batch": [200, answer]}), **SIGNED, actions=[
            dict(OPEN),
            dict(do="click", sel=HOOK("unleash-bulk"), label="bulk", wait=200, capture=self.BULK)])
        batches = [p for p in out["posts"] if p["url"].endswith("/manual/batch")]
        self.assertEqual(len(batches), 1)                                             # one request, not one per pick
        self.assertEqual(batches[0]["body"], {"picks": [{"event_id": "ahead2", "market": "moneyline"}]})
        self.assertEqual([p["url"] for p in out["posts"] if p["url"].endswith("/manual")], [])
        c = out["captures"]["bulk"]
        self.assertEqual(c["result"], "Added 1 · skipped 1 (game already started)")
        self.assertEqual(c["chips"], ["Added as a manual pick"])

    def test_a_skip_is_shown_with_its_reason_on_the_pick(self):
        answer = {"requested": 1, "added": 0, "skipped": 1, "line": "Added 0 · skipped 1 (already on the other side of this game)",
                  "reasons": [{"code": "one_side_per_game", "reason": "already on the other side of this game", "count": 1}],
                  "results": [{"event_id": "ahead2", "market": "moneyline", "status": "skipped", "code": "one_side_per_game",
                               "reason": "already on the other side of this game"}], "paper_only": True}
        out = run_page("kennel", routes=routes(self.day(), **{"POST /hounds/u-1/manual/batch": [200, answer]}), **SIGNED, actions=[
            dict(OPEN), dict(do="click", sel=HOOK("unleash-bulk"), label="bulk", wait=200, capture=self.BULK)])
        c = out["captures"]["bulk"]
        self.assertEqual(c["result"], "Added 0 · skipped 1 (already on the other side of this game)")
        self.assertEqual(c["chips"], ["Skipped: already on the other side of this game"])

    def test_there_is_no_button_when_nothing_is_left_over_and_a_refusal_is_said(self):
        out = run_page("kennel", routes=routes(payload()), **SIGNED, actions=[dict(OPEN, capture=self.BULK)])
        self.assertEqual(out["captures"]["open"]["items"], 0)
        self.assertIsNone(out["captures"]["open"]["btn"])
        refusal = [429, {"detail": {"error": "rate_limited", "message": "slow down"}}]
        out = run_page("kennel", routes=routes(self.day(), **{"POST /hounds/u-1/manual/batch": refusal}), **SIGNED, actions=[
            dict(OPEN), dict(do="click", sel=HOOK("unleash-bulk"), label="bulk", wait=200, capture=self.BULK)])
        self.assertEqual(out["captures"]["bulk"]["result"], "slow down")


class TheMotionRules(unittest.TestCase):
    CSS = read("css/dog-kit.css")
    JS = read("js/dog-fire.js")

    def test_the_reveal_has_no_timer_and_no_html_injection(self):
        self.assertNotRegex(self.JS, r"setTimeout|setInterval|requestAnimationFrame")      # progress is the request's own, never a pause
        self.assertNotRegex(self.JS, r"innerHTML|insertAdjacentHTML|outerHTML|document\.write")

    def test_all_of_its_motion_sits_inside_the_no_preference_block_and_the_reveal_is_under_three_seconds(self):
        css = re.sub(r"/\*.*?\*/", "", self.CSS, flags=re.S)
        blocks = re.findall(r"@media \(prefers-reduced-motion: no-preference\)\s*\{(.*?)\n\}", css, re.S)
        inside = "\n".join(blocks)
        for needle in (".ul-dog", ".ul-board__row", ".ul-in", "ul-sniff", "ul-scan", "ul-rise"):
            self.assertIn(needle, inside, needle)
        outside = css
        for b in blocks:
            outside = outside.replace(b, "")
        outside = re.sub(r"@keyframes [\w-]+\s*\{(?:[^{}]|\{[^{}]*\})*\}", "", outside)
        self.assertNotRegex(outside, r"animation(-name)?\s*:", "an animation outside the no-preference block")
        rise = re.search(r"\.ul-in\s*\{[^}]*animation:\s*ul-rise\s+([\d.]+)s[^}]*animation-delay:\s*calc\(var\(--i, 0\) \* (\d+)ms\)", inside, re.S)
        self.assertIsNotNone(rise)
        longest = float(rise.group(1)) + 7 * int(rise.group(2)) / 1000.0              # --i is capped at 7 in dog-fire.js
        self.assertLess(longest, 3.0)
        self.assertIn("Math.min(i++, 7)", self.JS)

    def test_the_stage_does_not_widen_a_phone(self):
        self.assertRegex(self.CSS, r"\.ul-stage__art\s*\{[^}]*overflow:\s*hidden")
        self.assertRegex(self.CSS, r"\.ul-board\s*\{[^}]*min-width:\s*0")


if __name__ == "__main__":      # pragma: no cover
    unittest.main()
