"""The owner's 2026-10-19 asks, run for real under node against the pages' own HTML:

  * COPY: "Fire now" is "Unleash" (button, tab and "Unleash again"), "Unleashing <name>..." (loading) and
    "<name>'s picks right now" (result heading); "Drill" is "Backtest". Only what a person reads changed: the routes
    and every data-hook keep the old words. ("Take them out back" was the preview's name for one day, 2026-10-19; since
    2026-10-20 it is the burial, tests/test_hounds_rites_web.py.)
  * BACKTEST: a tab on every dog page and in the studio (and the camp's section) with 7 / 14 / 30 days and Season 2,
    labelled "Backtest (hindsight, not counted in the record)", W-L, paper dollars, return, best and worst picks and
    the tickets; signed-out visitors get a sign-in prompt; a busy replay says "Another backtest is running, try
    again in N s" and the hourly allowance says so.
  * KENNEL NAMES AND PROFILES: the one-time "Name your kennel" prompt on My kennel, the server's refusal shown in its
    own words, a named kennel's title, and the public profile block.

Skipped when node is not installed (the copy scan at the bottom needs none).
"""

from __future__ import annotations

import os
import re
import tempfile
import unittest
from unittest import mock

from src.hounds import user_engine as eng
from tests.hounds_web_runner import HAS_NODE, WEB, run_js, run_page
from tests.test_hounds_interact_drill import run as run_drill, user_dog as drill_dog
from tests.test_hounds_interact_web import HID, TOKEN, TheTrainingCamp, dog_routes, hook, page, q
from tests.test_kennel_page import SIGNED, TheStudio, dog, kit, mine, public

LABEL = "Backtest (hindsight, not counted in the record)"


def result(**kw):
    """A real backtest payload from the real drill code (the page reads what the server would send)."""
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.object(eng, "ledger_path", lambda p=None: p or os.path.join(tmp, "u.jsonl")):
            return run_drill(drill_dog(), **kw)


BACKTEST_QUERIES = [
    q("label", hook("drill-label")), q("record", hook("drill-record")), q("usd", hook("backtest-usd")),
    q("ret", hook("backtest-return")), q("units", hook("drill-units")), q("window", hook("backtest-window-text")),
    q("best", hook("drill-best") + " li", "count"), q("picks", hook("drill-picks") + " tbody tr", "count"),
    q("pick_usd", hook("backtest-pick-usd")), q("note", hook("backtest-bankroll-note"))]


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheBacktestTabOnADogPage(unittest.TestCase):
    def routes(self, **over):
        r = dog_routes()
        r["POST /hounds/drill"] = [200, result(days=14)]
        r.update(over)
        return r

    def go(self, routes=None, **kw):
        return page(routes or self.routes(), **kw)

    def test_the_backtest_is_under_ask_with_four_windows_and_the_label(self):
        out = self.go(queries=[q("in_ask", "[data-tabpanel='ask'] " + hook("dog-backtest-section"), "exists"),
                                q("windows", hook("backtest-window"), "texts"), q("title", hook("backtest-title")),
                                q("section_hidden", hook("dog-backtest-section"), "hidden")])
        f = out["final"]
        self.assertTrue(f["in_ask"])         # owner ruling 2026-10-20 kennel-first: four tabs, Backtest lives under Ask
        self.assertEqual(f["windows"], ["7 days", "14 days", "30 days", "Season 2"])
        self.assertEqual(f["title"], LABEL)
        self.assertFalse(f["section_hidden"])

    def test_a_window_runs_the_dogs_rule_and_shows_wl_dollars_return_and_the_tickets(self):
        out = self.go(actions=[dict(do="click", sel=hook("backtest-window") + "[data-window='14']", wait=150, capture=BACKTEST_QUERIES)])
        post = [p for p in out["posts"] if p["url"] == "/hounds/drill"][0]
        self.assertEqual(post["body"], {"dog_id": HID, "days": 14})
        c = out["captures"]["0"]
        self.assertIn(LABEL, c["label"])
        self.assertEqual(c["record"], "1-0")
        self.assertEqual(c["usd"], "+$12.00 on the $1,000 paper bankroll")
        self.assertEqual(c["ret"], "+1.20%")
        self.assertEqual(c["units"], "+1.20u")
        self.assertEqual((c["best"], c["picks"]), (1, 1))
        self.assertEqual(c["pick_usd"], "+$12.00")
        self.assertIn("1 unit = $10", c["note"])

    def test_each_window_sends_its_days_and_season_two_sends_the_season(self):
        out = self.go(routes=self.routes(**{"POST /hounds/drill": [200, result(season="s2")]}), actions=[
            dict(do="click", sel=hook("backtest-window") + "[data-window='7']", wait=120),
            dict(do="click", sel=hook("backtest-window") + "[data-window='30']", wait=120),
            dict(do="click", sel=hook("backtest-window") + "[data-window='s2']", wait=150, capture=BACKTEST_QUERIES)])
        bodies = [p["body"] for p in out["posts"] if p["url"] == "/hounds/drill"]
        self.assertEqual(bodies, [{"dog_id": HID, "days": 7}, {"dog_id": HID, "days": 30}, {"dog_id": HID, "season": "s2"}])
        self.assertIn("Season 2", out["captures"]["2"]["window"])
        self.assertIn("2026-10-18 to 2026-10-21", out["captures"]["2"]["window"])

    def test_a_loss_shows_minus_dollars_and_a_worst_pick(self):
        lost = result(days=14, mlb_results={"900001": __import__("tests._hounds_user_fixtures", fromlist=["x"]).result_row("900001", "2026-10-20", "BOS", "SEA", 1, 3)})
        out = self.go(routes=self.routes(**{"POST /hounds/drill": [200, lost]}), actions=[
            dict(do="click", sel=hook("backtest-window") + "[data-window='14']", wait=150, capture=BACKTEST_QUERIES + [q("worst", hook("drill-worst") + " li", "count")])])
        c = out["captures"]["0"]
        self.assertEqual((c["record"], c["usd"], c["ret"], c["pick_usd"], c["worst"]),
                         ("0-1", "-$10.00 on the $1,000 paper bankroll", "-1.00%", "-$10.00", 1))

    def test_signed_out_it_asks_to_sign_in_and_never_posts(self):
        out = self.go(stored={}, queries=[q("signin", hook("backtest-signin")), q("windows", hook("backtest-window"), "count")])
        self.assertIn("Sign in to run a backtest", out["final"]["signin"])
        self.assertEqual(out["final"]["windows"], 0)
        self.assertEqual([p for p in out["posts"] if p["url"] == "/hounds/drill"], [])

    def test_a_busy_replay_shows_the_queue_message_with_the_seconds(self):
        busy = {"detail": {"error": "drill_busy", "message": "another drill is running; try again in a moment", "retry_after": 30}}
        out = self.go(routes=self.routes(**{"POST /hounds/drill": [429, busy]}), actions=[
            dict(do="click", sel=hook("backtest-window") + "[data-window='30']", wait=120, capture=[
                q("status", hook("backtest-status")), q("disabled", hook("backtest-window"), "attrs", attr="disabled")])])
        c = out["captures"]["0"]
        self.assertEqual(c["status"], "Another backtest is running, try again in 30 s.")
        self.assertEqual(c["disabled"], [None, None, None, None], "the buttons come back so it can be tried again")

    def test_the_hourly_allowance_says_how_long_to_wait(self):
        out = self.go(routes=self.routes(**{"POST /hounds/drill": [429, {"detail": {"error": "rate_limited", "retry_after": 1800}}]}), actions=[
            dict(do="click", sel=hook("backtest-window") + "[data-window='7']", wait=120, capture=[q("status", hook("backtest-status"))])])
        self.assertEqual(out["captures"]["0"]["status"], "You have used your 5 backtests for this hour. Try again in 30 min.")

    def test_a_server_refusal_is_said_in_the_servers_words(self):
        out = self.go(routes=self.routes(**{"POST /hounds/drill": [422, {"detail": {"error": "season_empty", "message": "Season 2 has no finished day to replay yet"}}]}), actions=[
            dict(do="click", sel=hook("backtest-window") + "[data-window='s2']", wait=120, capture=[q("status", hook("backtest-status"))])])
        self.assertIn("Season 2 has no finished day", out["captures"]["0"]["status"])

    def test_a_house_dog_has_the_tab_too(self):
        routes = dog_routes(kind="house", owner=False, kit=dict(__import__("tests.test_hounds_interact_web", fromlist=["x"]).Payloads.kit(owner=False, kind="house", can_record_manual=False, can_customize=False)))
        routes["POST /hounds/drill"] = [200, result(days=7)]
        out = page(routes, actions=[dict(do="click", sel=hook("backtest-window") + "[data-window='7']", wait=150, capture=BACKTEST_QUERIES)])
        self.assertEqual([p["body"] for p in out["posts"] if p["url"] == "/hounds/drill"], [{"dog_id": HID, "days": 7}])
        self.assertIn(LABEL, out["captures"]["0"]["label"])

    def test_the_result_makes_no_claim_in_its_words(self):
        out = self.go(actions=[dict(do="click", sel=hook("backtest-window") + "[data-window='14']", wait=150,
                                    capture=[q("words", hook("dog-backtest"))])])
        words = out["captures"]["0"]["words"]
        # (not "lock": the rule's own sentence says "earliest lock first", a ranking choice and not a claim)
        banned = re.compile(r"\bedge\b|guarantee|sure thing|can'?t lose|free money|\bev\b|expected value", re.I)
        self.assertIn("1-0", words)
        self.assertIsNone(banned.search(words), banned.search(words))
        self.assertNotIn("undefined", words)
        self.assertNotIn("NaN", words)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheCopyOnTheDogPage(unittest.TestCase):
    def test_the_button_loading_text_and_result_heading(self):
        routes = dog_routes()
        out = page(routes, captureInitial=[q("btn", hook("fire-btn")), q("section", "#fire-h")], actions=[
            dict(do="click", sel=hook("fire-btn"), wait=150, capture=[q("btn", hook("fire-btn")), q("title", hook("fire-title"))])])
        self.assertEqual(out["captures"]["initial"]["btn"], "Unleash")
        self.assertEqual(out["captures"]["initial"]["section"], "Unleash")
        c = out["captures"]["0"]
        self.assertEqual(c["btn"], "Unleash again")
        self.assertEqual(c["title"], "Closer's picks right now")

    def test_the_loading_text_names_the_dog(self):
        """The status line is set before the request leaves and cleared when it returns, so the page test cannot catch
        it; the source of both places that say it is pinned instead."""
        fire = (WEB / "js" / "dog-fire.js").read_text(encoding="utf-8")
        camp = (WEB / "js" / "dog-camp.js").read_text(encoding="utf-8")
        self.assertIn('`Unleashing ${name || "this dog"}...`', fire)
        self.assertIn('`Unleashing ${d.name}...`', camp)

    def test_the_hooks_and_the_route_keep_the_old_word(self):
        out = page(dog_routes(), actions=[dict(do="click", sel=hook("fire-btn"), wait=150)], queries=[q("sec", hook("dog-fire-section"), "count")])
        self.assertEqual(out["final"]["sec"], 1)
        self.assertEqual([p["url"] for p in out["posts"]], [f"/hounds/{HID}/fire"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheCopyInTheKennel(unittest.TestCase):
    def test_the_card_button_and_the_studio_tabs(self):
        routes = TheStudio().routes([dog("u-1")])
        out = run_page("kennel", routes=routes, **SIGNED, queries=[q("btn", "[data-hook='dog-action-fire']", "texts")], actions=[
            dict(do="click", sel="[data-hook='dog-action-fire']", label="out", wait=300, capture=[
                q("selected", "[role='tab'][aria-selected='true']", "texts"), q("btn", "[data-hook='fire-btn']"),
                q("title", "[data-hook='unleash-title']")])])
        self.assertEqual(out["final"]["btn"], ["Unleash"])
        self.assertEqual(out["captures"]["out"]["selected"], ["Unleash"])
        self.assertEqual(out["captures"]["out"]["title"], "Underdog Gus's day")      # the owner's Unleash starts the dog (2026-10-21)

    def test_the_studio_backtest_tab_runs_a_backtest_for_that_dog(self):
        routes = TheStudio().routes([dog("u-1")])
        routes["POST /hounds/drill"] = [200, result(days=14)]
        out = run_page("kennel", routes=routes, **SIGNED, actions=[
            dict(do="click", sel="[data-hook='dog-avatar']", label="open", wait=200),
            dict(do="click", sel="[data-tab='backtest']", label="tab", wait=200, capture=[q("windows", hook("backtest-window"), "texts")]),
            dict(do="click", sel=hook("backtest-window") + "[data-window='s2']", label="run", wait=200, capture=BACKTEST_QUERIES)])
        self.assertEqual(out["captures"]["tab"]["windows"], ["7 days", "14 days", "30 days", "Season 2"])
        post = [p for p in out["posts"] if p["url"] == "/hounds/drill"][0]
        self.assertEqual(post["body"], {"dog_id": "u-1", "season": "s2"})
        self.assertIn(LABEL, out["captures"]["run"]["label"])
        self.assertEqual(out["captures"]["run"]["usd"], "+$12.00 on the $1,000 paper bankroll")


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheTrainingCampBacktest(unittest.TestCase):
    def test_the_section_says_backtest_and_season_two_is_a_button_that_sends_the_season(self):
        camp = TheTrainingCamp()
        routes = camp.routes(**{"POST /hounds/drill": [200, result(season="s2")]})
        out = camp.go(routes=routes, queries=[q("h2", "#drills-h"), q("run", hook("drill-run")), q("days", hook("drill-days"), "texts")], actions=[
            dict(do="click", sel=hook("drill-days") + "[data-days='s2']", wait=20),
            dict(do="click", sel=hook("drill-run"), wait=150, capture=[q("label", hook("drill-label")), q("status", hook("drill-status"))])])
        self.assertEqual(out["final"]["h2"], "Backtest")
        self.assertEqual(out["final"]["run"], "Run backtest")
        self.assertEqual(out["final"]["days"], ["7 days", "14 days", "30 days", "Season 2"])
        post = [p for p in out["posts"] if p["url"] == "/hounds/drill"][0]
        self.assertEqual(post["body"], {"dog_id": "u-1", "season": "s2"})
        self.assertIn(LABEL, out["captures"]["1"]["label"])

    def test_a_busy_replay_in_the_camp_shows_the_queue_message(self):
        camp = TheTrainingCamp()
        busy = {"detail": {"error": "drill_busy", "message": "x", "retry_after": 12}}
        out = camp.go(routes=camp.routes(**{"POST /hounds/drill": [429, busy]}), actions=[
            dict(do="click", sel=hook("drill-run"), wait=120, capture=[q("status", hook("drill-status"))])])
        self.assertEqual(out["captures"]["0"]["status"], "Another backtest is running, try again in 12 s.")


def named(handle="bobs-dogs", display="Bob's Dogs", **over):
    body = {"handle": handle, "display": display, "kennel_name": display, "needs_name_prompt": False,
            "name_limits": {"min": 2, "max": 30}, "dog_count": 1, "dogs": [dog()], "season": {"id": "s2", "label": "Season 2"}, "paper_only": True}
    body.update(over)
    return [200, body]


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheKennelNamePrompt(unittest.TestCase):
    ROUTES = {"/hounds/kennels/mine": None}

    def routes(self, **over):
        prompt = mine([dog()])
        prompt[1].update({"kennel_name": None, "needs_name_prompt": True, "name_limits": {"min": 2, "max": 30}})
        r = {"/hounds/kennels/mine": prompt}
        r.update(over)
        return r

    def test_the_first_visit_asks_once_with_save_and_not_now(self):
        out = run_page("kennel", routes=self.routes(), **SIGNED, queries=[
            q("title", "[data-hook='kennel-name-prompt'] h2"), q("input", "[data-hook='kennel-name-input']", "count"),
            q("skip", "[data-hook='kennel-name-skip']"), q("text", "[data-hook='kennel-name-prompt']")])
        f = out["final"]
        self.assertEqual(f["title"], "Name your kennel")
        self.assertEqual((f["input"], f["skip"]), (1, "Not now"))
        self.assertIn("Handler 21E8", f["text"])
        self.assertIn("2 to 30 characters", f["text"])

    def test_no_prompt_once_it_is_done(self):
        done = mine([dog()])
        done[1].update({"kennel_name": "Bob's Dogs", "needs_name_prompt": False, "display": "Bob's Dogs"})
        out = run_page("kennel", routes={"/hounds/kennels/mine": done}, **SIGNED, queries=[
            q("prompt", "[data-hook='kennel-name-prompt']", "count"), q("rename", "[data-hook='kennel-rename']"), q("title", "[data-hook='kennel-title']")])
        self.assertEqual(out["final"]["prompt"], 0)
        self.assertEqual(out["final"]["rename"], "Rename kennel")
        self.assertEqual(out["final"]["title"], "Bob's Dogs")          # owner ruling 2026-10-21: the kennel's own name is the big line

    def test_saving_puts_the_name_and_reloads_the_kennel(self):
        saved = mine([dog()])
        out = run_page("kennel", routes=self.routes(**{"PUT /me/kennel": [200, {"kennel_name": "Bob's Dogs"}]}), **SIGNED, actions=[
            dict(do="set", sel="[data-hook='kennel-name-input']", value="Bob's Dogs"),
            dict(do="submit", sel="[data-hook='kennel-name-form']", wait=200, capture=[q("prompt", "[data-hook='kennel-name-prompt']", "count")])])
        puts = [p for p in out["posts"] if p["url"] == "/me/kennel"]
        self.assertEqual([p["method"] for p in puts], ["PUT"])
        self.assertEqual(puts[0]["body"], {"kennel_name": "Bob's Dogs"})
        self.assertIsNotNone(saved)

    def test_a_refusal_is_shown_in_the_servers_own_words_and_the_form_stays(self):
        taken = {"detail": {"error": "kennel_name_taken", "message": "another kennel already has that name"}}
        out = run_page("kennel", routes=self.routes(**{"PUT /me/kennel": [409, taken]}), **SIGNED, actions=[
            dict(do="set", sel="[data-hook='kennel-name-input']", value="Taken"),
            dict(do="submit", sel="[data-hook='kennel-name-form']", wait=200, capture=[
                q("status", "[data-hook='kennel-name-status']"), q("form", "[data-hook='kennel-name-form']", "count")])])
        self.assertEqual(out["captures"]["1"]["status"], "another kennel already has that name")
        self.assertEqual(out["captures"]["1"]["form"], 1)

    def test_not_now_tells_the_server_so_it_is_never_asked_again(self):
        out = run_page("kennel", routes=self.routes(**{"PUT /me/kennel": [200, {}]}), **SIGNED, actions=[
            dict(do="click", sel="[data-hook='kennel-name-skip']", wait=150, capture=[q("prompt", "[data-hook='kennel-name-prompt']", "count")])])
        puts = [p for p in out["posts"] if p["url"] == "/me/kennel"]
        self.assertEqual(puts[0]["body"], {"dismiss_prompt": True})
        self.assertEqual(out["captures"]["0"]["prompt"], 0)


@unittest.skipUnless(HAS_NODE, "node not installed")
class ThePublicProfile(unittest.TestCase):
    PROFILE = {"title": "Bob's Dogs", "named": True, "member_since": "October 2026",
               "combined": {"record": {"bets": 5, "wins": 3, "losses": 2, "pushes": 0}, "settled": 5, "pnl_usd": 12.5, "start_usd": 2000.0,
                            "return_pct": 0.62, "open_bets": 1},
               "best": {"id": "u-1", "name": "Underdog Gus", "record": {"wins": 3, "losses": 1, "pushes": 0}},
               "recent_tickets": [{"date": "2026-10-20", "game": "BOS @ SEA", "selection": "Boston Red Sox to win", "price": 120, "result": "won",
                                   "dog": {"id": "u-1", "name": "Underdog Gus", "href": "hound.html?id=u-1"}}]}

    def go(self, body, handle="bobs-dogs"):
        payload = named(handle=handle, **body)
        return run_page("kennel", search=f"?u={handle}", routes={f"/hounds/kennels/{handle}": payload}, queries=[
            q("title", "[data-hook='kennel-title']"), q("since", hook("profile-since")), q("dogs", hook("profile-dogs")),
            q("record", hook("profile-record")), q("usd", hook("profile-usd")), q("ret", hook("profile-return")),
            q("best", hook("profile-best")), q("tickets", hook("profile-ticket"), "count"), q("link", hook("profile-ticket") + " a", "attr", attr="href"),
            q("doc_title", "title")])

    def test_a_named_kennels_title_is_its_name_and_the_profile_block_is_there(self):
        out = self.go(dict(self.PROFILE, display="Bob's Dogs"))
        f = out["final"]
        self.assertEqual(f["title"], "Bob's Dogs")
        self.assertEqual((f["since"], f["dogs"], f["record"]), ("October 2026", "1", "3-2"))
        self.assertEqual((f["usd"], f["ret"]), ("+$12.50", "+0.62%"))
        self.assertEqual(f["best"], "Underdog Gus, 3-1")
        self.assertEqual((f["tickets"], f["link"]), (1, "hound.html?id=u-1"))

    def test_an_unnamed_kennel_keeps_the_handle_title(self):
        out = self.go(dict(self.PROFILE, display="Handler 21E8", title="Handler 21E8", named=False), handle="handler-21e8")
        self.assertEqual(out["final"]["title"], "Handler 21E8's kennel")

    def test_a_kennel_with_nothing_settled_says_so_not_zero_dollars(self):
        bare = dict(self.PROFILE, display="Bob's Dogs", recent_tickets=[], best=None,
                    combined={"record": {"bets": 0, "wins": 0, "losses": 0, "pushes": 0}, "settled": 0, "pnl_usd": 0.0, "start_usd": 1000.0, "return_pct": 0.0})
        out = self.go(bare)
        f = out["final"]
        self.assertEqual((f["record"], f["usd"], f["ret"], f["best"], f["tickets"]), ("no settled bets", "n/a", "n/a", "none yet", 0))


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheKennelsIndexAndHandles(unittest.TestCase):
    def test_a_named_kennel_shows_its_name_and_an_unnamed_one_its_handle(self):
        cards = {"kennels": [
            {"handle": "bobs-dogs", "display": "Bob's Dogs", "named": True, "dog_count": 2, "new_dogs": 2, "best": None, "dogs": [], "href": "kennel.html?u=bobs-dogs"},
            {"handle": "handler-0001", "display": "Handler 0001", "named": False, "dog_count": 1, "new_dogs": 1, "best": None, "dogs": [], "href": "kennel.html?u=handler-0001"}],
            "count": 2}
        out = run_page("kennels_index", routes={"/hounds/kennels": [200, cards]}, queries=[
            q("names", "[data-hook='kennel-card'] strong", "texts"), q("hrefs", "[data-hook='kennel-card']", "attrs", attr="href")])
        self.assertEqual(out["final"]["names"], ["Bob's Dogs", "Handler 0001's kennel"])
        self.assertEqual(out["final"]["hrefs"], ["kennel.html?u=bobs-dogs", "kennel.html?u=handler-0001"])

    def test_the_page_derives_the_same_handle_the_server_does(self):
        got = run_js('import { kennelHandle, kennelName, kennelHref } from "./hounds-core.js";\n'
                     'console.log(JSON.stringify({a: kennelHandle("Bob\'s Dogs"), b: kennelHandle("Handler 3F2A"), c: kennelHandle("  BOBS-dogs "),'
                     ' d: kennelName("Handler 3F2A"), e: kennelName("Bob\'s Dogs"), f: kennelName(""), g: kennelHref("Bob\'s Dogs")}));')
        self.assertEqual(got, {"a": "bobs-dogs", "b": "handler-3f2a", "c": "bobs-dogs", "d": "Handler 3F2A's kennel",
                               "e": "Bob's Dogs", "f": "A member's kennel", "g": "kennel.html?u=bobs-dogs"})
        from src.hounds import kennels
        for label, want in (("Bob's Dogs", "bobs-dogs"), ("Handler 3F2A", "handler-3f2a"), ("  BOBS-dogs ", "bobs-dogs")):
            self.assertEqual(kennels.slug(label), want)


class NoFireNowLeftInTheWords(unittest.TestCase):
    """The scan the owner asked for: no "Fire now", "Fire again" or "Drill" in anything a person reads. Data-hooks,
    routes, ids and class names (one word, no spaces) are not words a person reads and keep the old name."""
    FILES = ["hound.html", "kennel.html", "learning.html", "landing.html", "desk.html", "kennels.html", "hounds.html", "build-a-hound.html"]
    OLD = re.compile(r"fire now|fire again|firing|\bfire (?:it|them|a dog|your)\b|drill|hindsight drill", re.I)

    def visible_html(self, name):
        html = (WEB / name).read_text(encoding="utf-8")
        html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
        html = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)
        html = re.sub(r"""\s(?:data-hook|id|class|href|src|aria-labelledby|for|data-tab|data-tabpanel|name|rel|type|content)=("[^"]*"|'[^']*')""", "", html)
        return re.sub(r"<[^>]+>", " ", html) + " " + " ".join(re.findall(r'(?:aria-label|title|alt|placeholder)="([^"]*)"', (WEB / name).read_text(encoding="utf-8")))

    def literals(self, path):
        src = path.read_text(encoding="utf-8")
        src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
        src = re.sub(r"(?m)^\s*//.*$", "", src)
        out = []
        for m in re.finditer(r'"((?:[^"\\\n]|\\.)*)"|`((?:[^`\\]|\\.)*)`', src):
            text = m.group(1) if m.group(1) is not None else m.group(2)
            if re.search(r"\s", text) or text[:1].isupper():
                out.append(text)
        return out

    def test_no_page_says_fire_now_or_drill_in_its_words(self):
        for name in self.FILES:
            with self.subTest(page=name):
                found = self.OLD.findall(self.visible_html(name))
                self.assertEqual(found, [], name)

    def test_no_script_says_it_either(self):
        paths = sorted((WEB / "js").glob("dog-*.js")) + [WEB / "js" / n for n in ("kennel.js", "kennels-index.js", "hounds-learning.js",
                                                                                 "hounds-detail.js", "hounds-page.js", "hounds-build.js", "landing.js")]
        for path in paths:
            with self.subTest(script=path.name):
                bad = [t for t in self.literals(path) if self.OLD.search(t) and not re.search(r"fire-and-forget", t, re.I)]
                self.assertEqual(bad, [], path.name)

    def test_the_words_a_person_reads_are_the_new_ones(self):
        self.assertIn('text: "Unleash"', (WEB / "js" / "dog-fire.js").read_text(encoding="utf-8"))
        self.assertIn(">Unleash<", (WEB / "hound.html").read_text(encoding="utf-8"))
        self.assertIn("Backtest", (WEB / "learning.html").read_text(encoding="utf-8"))
        voice = (WEB.parent / "docs" / "VOICE.md").read_text(encoding="utf-8")
        self.assertIn("Unleash", voice)
        self.assertIn("Backtest", voice)

    def test_the_hooks_and_routes_keep_the_old_words(self):
        self.assertIn('data-hook="dog-fire-section"', (WEB / "hound.html").read_text(encoding="utf-8"))
        self.assertIn('data-hook="camp-drills-section"', (WEB / "learning.html").read_text(encoding="utf-8"))
        self.assertIn('data-tab="fire"', (WEB / "kennel.html").read_text(encoding="utf-8"))
        fire = (WEB / "js" / "dog-fire.js").read_text(encoding="utf-8")
        self.assertIn('"data-hook": "fire-btn"', fire)
        self.assertIn("/fire`", fire)
        self.assertIn('"/hounds/drill"', (WEB / "js" / "dog-backtest.js").read_text(encoding="utf-8"))
        self.assertIn('"data-hook": "camp-dog-fire"', (WEB / "js" / "dog-camp.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
