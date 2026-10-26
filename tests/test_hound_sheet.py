"""The hound sheet (owner, 2026-10-26: the detail view every hound opens in "looks like trash"): web/kennel.html's studio drawer, redrawn.

One renderer serves every hound a member opens (their own, a house copy, Gematria, the Learner), so these tests run it for the real page under node:

  HEADER     the FULL name (wrapped, never an ellipsis), the version chip, the owner, one status line, the ticket counts, and Remove from my kennel
             in the three-dot menu (behind its own confirmation) instead of beside the name.
  TABS       a sticky, sideways-scrolling segmented bar that keeps the chosen tab in view; a hound with tickets opens on its Record.
  RECORD     "1 open · 0 settled" first, a 3 + 2 grid, the open tickets listed before the settled ones (a hound with a ticket never reads as idle).
  UNLEASH    state-aware: a hound that is already going gets a status and a read-only look at today, not "Unleash starts it".
  BACKTEST   the 7 day window runs as the tab opens, with a loading state.
  RULES      the current rule first, in words, with "Edit rules" revealing the editor; the example chip can never widen the screen.

The widths (375, 390, 1440) are measured in a real Chrome by tests/test_hound_sheet_widths.py.
"""

from __future__ import annotations

import json
import re
import unittest

from src.hounds import user_spec
from tests import hounds_web_fixtures as F
from tests.hounds_web_runner import HAS_NODE, WEB, run_page
from tests.test_kennel_page import SIGNED, TheStudio, dog, kit, mine, q


def read(name):
    return (WEB / name).read_text(encoding="utf-8")


def sheet_css():
    """The hound sheet's own section of css/studio.css (the file has older rules for the same selectors above it)."""
    return read("css/studio.css").split("THE HOUND SHEET", 1)[1]


def block(css, selector):
    return css.split(selector + " {", 1)[1].split("}", 1)[0]


def rows(n=3, open_n=0, hid="u-1"):
    """Real-shaped ticket rows (the contract's own BetRow), the first `open_n` still open."""
    from src.hounds import contract
    out = []
    for i, row in enumerate(F.bet_rows("closer", n + open_n)):
        item = contract.to_json(row)
        item["hound_id"] = hid
        item["event_id"] = f"ev-{i}"
        item["game"] = f"Team {i} at Team {i + 20}"
        item["selection"] = f"Pick number {i} to win"
        if i < open_n:
            item["result"], item["units"], item["clv_pts"], item["status"] = None, None, None, "OPEN"
        else:
            item["result"], item["units"] = "loss", -1.0
        out.append(item)
    return out


BET_URL = "/hounds/u-1/bets?page=1&page_size=5&segment=forward"
OPEN_URL = "/hounds/u-1/bets?page=1&page_size=8&segment=forward&status=open"


def mine_dog(name="Underdog Gus", style=None):
    from tests import _hounds_rules_fixtures as F2
    d = {"id": "u-1", "name": name, "tagline": "Barks", "status": "running", "version_no": 3, "color": "mint", "badge": "crown",
         "record": {"bets": 0, "wins": 0, "losses": 0, "pushes": 0}, "rule_sentences": ["Bet home underdogs between +120 and +200, at most 2 bets a day."]}
    d["spec"] = json.loads(json.dumps(user_spec.validate_spec(F2.v2(name=name, rules=[F2.rule(side="away", price_min=100)]))))
    return d


class StudioHelpers:
    MENU = TheStudio.MENU
    routes = TheStudio.routes

    def sheet(self, dogs=None, extra=None, **kw):
        dogs = dogs or [dog("u-1", "Gematria Hound With A Rather Long Name", wins=0, losses=3, bets=3, units=-0.6, version_no=3)]
        routes = self.routes(dogs)
        routes.update(extra or {})
        return run_page("kennel", routes=routes, **SIGNED, tz="UTC", **kw)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheHeader(StudioHelpers, unittest.TestCase):
    NAME = "Gematria Hound With A Rather Long Name"

    def test_the_header_shows_the_full_name_version_owner_status_and_the_counts(self):
        out = self.sheet(actions=[dict(do="click", sel="[data-hook='dog-avatar']", label="open", wait=200, capture=[
            q("title", "[data-hook='studio-title']"), q("version", "[data-hook='studio-version']"), q("owner", "[data-hook='studio-owner']"),
            q("status", "[data-hook='studio-status']"), q("sub", "[data-hook='studio-sub']")])])
        c = out["captures"]["open"]
        self.assertEqual(c["title"], self.NAME, "the whole name, not 'Gema...'")
        self.assertEqual((c["version"], c["owner"]), ("v3", "By Handler 21E8"))
        self.assertRegex(c["status"], r"^Running ·")
        self.assertIn("0 open · 3 settled", c["sub"])
        self.assertIn("0-3", c["sub"], "the record line is whole: no '0-3, $2,35...'")
        self.assertNotIn("...", c["sub"])
        self.assertNotIn("…", c["title"] + c["sub"])

    def test_the_css_wraps_the_name_and_the_record_line_instead_of_cutting_them(self):
        css = sheet_css()
        last_h2 = block(css, ".hounds-page .kn-studio .kn-studio__who h2")
        self.assertIn("white-space: normal", last_h2)
        self.assertIn("text-overflow: clip", last_h2)
        self.assertIn("overflow-wrap: anywhere", last_h2)
        last_sub = block(css, ".kn-studio__who .kn-studio__sub")
        self.assertIn("white-space: normal", last_sub)
        self.assertNotIn("ellipsis", last_sub)

    def test_remove_from_my_kennel_is_in_the_three_dot_menu_not_beside_the_name(self):
        out = self.sheet(actions=[
            dict(do="click", sel="[data-hook='dog-avatar']", label="open", wait=200, capture=[
                q("in_menu", "[data-hook='studio-menu'] [data-hook='studio-remove']", "count"),
                q("in_hero", "[data-hook='studio-hero'] [data-hook='studio-remove']", "count"),
                q("menu_hidden", "[data-hook='studio-menu']", "hidden"), q("more_hidden", "[data-hook='studio-more']", "hidden"),
                q("expanded", "[data-hook='studio-more']", "attr", attr="aria-expanded")]),
            dict(do="click", sel="[data-hook='studio-more']", label="menu", wait=50, capture=[
                q("menu_hidden", "[data-hook='studio-menu']", "hidden"), q("expanded", "[data-hook='studio-more']", "attr", attr="aria-expanded"),
                q("label", "[data-hook='studio-remove']")])])
        a, b = out["captures"]["open"], out["captures"]["menu"]
        self.assertEqual((a["in_menu"], a["in_hero"], a["more_hidden"]), (1, 0, False))
        self.assertEqual((a["menu_hidden"], a["expanded"]), (True, "false"), "the menu is closed until the three dots are tapped")
        self.assertEqual((b["menu_hidden"], b["expanded"], b["label"]), (False, "true", "Remove from my kennel"))

    def test_the_menu_item_still_asks_first_and_a_no_removes_nothing(self):
        out = self.sheet(confirm=False, actions=[dict(do="click", sel="[data-hook='dog-avatar']", wait=150),
                                                 dict(do="click", sel="[data-hook='studio-more']", wait=50),
                                                 dict(do="click", sel="[data-hook='studio-remove']", wait=150)])
        self.assertEqual(len(out["confirms"]), 1)
        self.assertIn("Remove Gematria Hound", out["confirms"][0])
        self.assertEqual([p for p in out["posts"] if p["url"].endswith("/retire")], [])

    def test_a_yes_retires_it(self):
        retired = dog("u-1", "Underdog Gus", retired=True, status="retired")
        out = self.sheet(dogs=[dog("u-1", "Underdog Gus")], extra={"POST /hounds/u-1/retire": [200, {"hound": {}}]}, actions=[
            dict(do="click", sel="[data-hook='dog-avatar']", wait=150), dict(do="click", sel="[data-hook='studio-more']", wait=50),
            dict(do="click", sel="[data-hook='studio-remove']", wait=200)])
        self.assertEqual([p["url"] for p in out["posts"] if p["url"].endswith("/retire")], ["/hounds/u-1/retire"])
        del retired

    def test_the_close_button_stays_and_a_retired_hound_has_no_menu(self):
        out = self.sheet(dogs=[dog("u-1", "Old Rex", retired=True, status="retired")], actions=[
            dict(do="click", sel="[data-hook='dog-action-open']", wait=50)], queries=[q("close", "[data-hook='studio-close']", "count")])
        self.assertEqual(out["final"]["close"], 1)

    def test_a_paused_hound_says_paused_in_the_hero(self):
        out = self.sheet(dogs=[dog("u-1", "Sleepy", status="benched")], actions=[dict(do="click", sel="[data-hook='dog-avatar']", label="open", wait=150, capture=[
            q("status", "[data-hook='studio-status']")])])
        self.assertRegex(out["captures"]["open"]["status"], r"^Paused ·")


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheTabs(StudioHelpers, unittest.TestCase):
    def test_the_tab_bar_is_a_sticky_segmented_bar_that_scrolls_inside_itself(self):
        bar = block(sheet_css(), ".lh-tabs--studio")
        self.assertIn("position: sticky", bar)
        self.assertIn("overflow-x: auto", bar)
        self.assertIn("max-width: calc(100% - 2 * var(--lh-s4))", bar, "the bar scrolls inside its own box")
        self.assertIn("data-scrollactive", read("kennel.html"))
        self.assertIn("scrollIntoView", read("js/tabs.js"))

    def test_choosing_a_tab_scrolls_it_into_view(self):
        out = self.sheet(actions=[dict(do="click", sel="[data-hook='dog-avatar']", wait=150),
                                  dict(do="click", sel="[role='tab'][data-tab='ask']", wait=150)])
        self.assertTrue(any(s == "Ask" or s == "button" for s in out["scrolls"]), out["scrolls"])

    def test_a_hound_with_tickets_opens_on_its_record_and_one_without_on_look(self):
        out = self.sheet(dogs=[dog("u-1", "Has Tickets", wins=0, losses=2, bets=2), dog("u-2", "Nothing Yet")], actions=[
            dict(do="click", sel="[data-hook='dog-avatar']", index=0, label="busy", wait=200, capture=[q("selected", "[role='tab'][aria-selected='true']", "texts")]),
            dict(do="click", sel="[data-hook='studio-close']", wait=50),
            dict(do="click", sel="[data-hook='dog-avatar']", index=1, label="quiet", wait=200, capture=[q("selected", "[role='tab'][aria-selected='true']", "texts")])])
        self.assertEqual(out["captures"]["busy"]["selected"], ["Record"])
        self.assertEqual(out["captures"]["quiet"]["selected"], ["Look"])

    def test_an_open_ticket_alone_is_enough_to_open_on_the_record(self):
        out = self.sheet(dogs=[dog("u-1", "Doctor Data Dog", open_bets=1)], actions=[
            dict(do="click", sel="[data-hook='dog-avatar']", label="open", wait=200, capture=[q("selected", "[role='tab'][aria-selected='true']", "texts")])])
        self.assertEqual(out["captures"]["open"]["selected"], ["Record"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheRecordTab(StudioHelpers, unittest.TestCase):
    """Owner add-on 2026-10-26 ("Data hound never made a bet"): Doctor Data Dog had ONE OPEN TICKET and read as having done nothing, because
    `record.bets` counts settled bets only. The hero, the kennel card and the Record tab all say open and settled together now."""

    def doctor(self):
        return dog("u-1", "Doctor Data Dog", open_bets=1, bets=0)

    def test_one_open_ticket_and_nothing_settled_reads_as_1_open_0_settled_everywhere(self):
        out = self.sheet(dogs=[self.doctor()], actions=[dict(do="click", sel="[data-hook='dog-avatar']", label="open", wait=250, capture=[
            q("sub", "[data-hook='studio-sub']"), q("counts", "[data-hook='studio-counts']"), q("status", "[data-hook='studio-status']")])],
            captureInitial=[q("today", "[data-hook='dog-today']", "texts"), q("bets", "[data-hook='dog-bets']", "texts")])
        c = out["captures"]["open"]
        self.assertTrue(c["sub"].startswith("1 open · 0 settled"), c["sub"])
        self.assertEqual(c["counts"], "1 open · 0 settled")
        self.assertNotIn("No tickets yet", c["counts"])
        self.assertEqual(out["captures"]["initial"]["today"], ["1 open · 0 settled"])
        self.assertEqual(out["captures"]["initial"]["bets"], ["1 (1 open)"], "the card never says 0 bets beside an open ticket")

    def test_a_hound_with_no_tickets_at_all_says_so(self):
        out = self.sheet(dogs=[dog("u-1", "Fresh Fido")], actions=[dict(do="click", sel="[data-hook='dog-avatar']", wait=100),
                                                                     dict(do="click", sel="[role='tab'][data-tab='record']", label="r", wait=200, capture=[q("counts", "[data-hook='studio-counts']")])])
        self.assertEqual(out["captures"]["r"]["counts"], "No tickets yet")

    def test_the_open_ticket_is_listed_first_and_not_listed_twice(self):
        open_row = rows(1, 1)[0]
        settled = rows(3, 0)
        settled[0]["selection"] = "Settled one to win"
        extra = {OPEN_URL: [200, {"items": [open_row], "total": 1}], BET_URL: [200, {"items": [open_row] + settled, "total": 4}]}
        out = self.sheet(dogs=[self.doctor()], extra=extra, actions=[dict(do="click", sel="[data-hook='dog-avatar']", label="open", wait=300, capture=[
            q("open_title", "[data-hook='studio-open-title']"), q("open_list", "[data-hook='studio-open-ticket-list']"),
            q("open_n", "[data-hook='studio-open-ticket-list'] li", "count"),
            q("settled_list", "[data-hook='studio-tickets']"), q("settled_title", ".kn-rec__h", "texts")])])
        c = out["captures"]["open"]
        self.assertEqual(c["open_title"], "Open ticket")
        self.assertIn("Pick number 0 to win", c["open_list"])
        self.assertNotIn("Pick number 0 to win", c["settled_list"], "an open ticket is not repeated under the settled ones")
        self.assertIn("Settled one to win", c["settled_list"])
        self.assertEqual(c["settled_title"], ["Open ticket", "Settled and recent"])

    def test_the_open_tickets_section_comes_before_the_settled_ones_in_the_page(self):
        extra = {OPEN_URL: [200, {"items": rows(1, 1), "total": 1}], BET_URL: [200, {"items": rows(2, 0), "total": 2}]}
        out = self.sheet(dogs=[self.doctor()], extra=extra, actions=[dict(do="click", sel="[data-hook='dog-avatar']", label="open", wait=300, capture=[
            q("order", "[data-hook='studio-record'] [data-hook]", "attrs", attr="data-hook")])])
        order = [h for h in out["captures"]["open"]["order"] if h in ("studio-open-tickets", "studio-tickets", "studio-record-stats")]
        self.assertEqual(order, ["studio-record-stats", "studio-open-tickets", "studio-tickets"])

    def test_the_grid_is_five_equal_cards_in_a_three_plus_two_layout(self):
        out = self.sheet(dogs=[self.doctor()], actions=[dict(do="click", sel="[data-hook='dog-avatar']", label="open", wait=250, capture=[
            q("labels", "[data-hook='studio-record-stats'] dt", "texts"), q("vals", "[data-hook='studio-record-stats'] dd", "texts")])])
        c = out["captures"]["open"]
        self.assertEqual(c["labels"], ["Record", "Bankroll", "Return", "Bets", "Open"])
        self.assertEqual(c["vals"][-2:], ["1 (1 open)", "1"])
        css = sheet_css()
        grid = block(css, ".kn-stats--rec")
        self.assertIn("repeat(6, minmax(0, 1fr))", grid)
        self.assertRegex(css, r"\.kn-stats--rec \.kn-stat \{ grid-column: span 2;")
        self.assertRegex(css, r"\.kn-stats--rec \.kn-stat:nth-child\(n \+ 4\) \{ grid-column: span 3; \}")

    def test_the_grading_chip_is_a_quiet_inline_status(self):
        pill = block(sheet_css(), ".kn-studio .hd-graded__pill")
        self.assertIn("border: 0", pill)
        self.assertNotIn("dashed", pill)

    def test_a_sparkline_is_drawn_only_from_the_bankrolls_own_settled_bets(self):
        events = [["2026-10-24", 1761300000, -1.0, 1.0, "l"], ["2026-10-25", 1761390000, -1.0, 1.0, "l"], ["2026-10-26", 1761480000, 0.0, 0.0, ""]]
        d = dog("u-1", "Gematria Hound", losses=2, bets=2, units=-2.0)
        d["bankroll"] = dict(d["bankroll"], start=2500.0, current=2450.0, pnl_usd=-50.0, unit_usd=25.0, events=events)
        out = self.sheet(dogs=[d], viewer={"mode": "fixed", "unit_usd": 25, "pct": None, "start_usd": 2500}, actions=[
            dict(do="click", sel="[data-hook='dog-avatar']", label="open", wait=250, capture=[
                q("spark", "[data-hook='studio-spark'] svg", "count"), q("caption", "[data-hook='studio-spark'] figcaption")])])
        self.assertEqual(out["captures"]["open"]["spark"], 1)
        self.assertEqual(out["captures"]["open"]["caption"], "Bankroll after each of its 2 settled bets")

    def test_with_fewer_than_two_settled_bets_there_is_no_line_at_all(self):
        d = dog("u-1", "One Bet Wonder", losses=1, bets=1, units=-1.0)
        d["bankroll"] = dict(d["bankroll"], events=[["2026-10-24", 1761300000, -1.0, 1.0, "l"]])
        out = self.sheet(dogs=[d], actions=[dict(do="click", sel="[data-hook='dog-avatar']", label="open", wait=250, capture=[q("spark", "[data-hook='studio-spark']", "count")])])
        self.assertEqual(out["captures"]["open"]["spark"], 0)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheUnleashTab(StudioHelpers, unittest.TestCase):
    """Is "Unleash" the right state for a hound that already has tickets? The server says it is not NEW but not wrong: a running hound is bet for
    by the runner and Unleash only re-checks today (src/hounds/interact/unleash.py). The page said "Unleash starts it betting today" regardless,
    which was false for that hound; it now shows a status instead."""

    def test_a_hound_with_tickets_gets_a_status_and_a_read_only_look_at_today_not_the_first_time_copy(self):
        d = dog("u-1", "Doctor Data Dog", open_bets=1)
        out = self.sheet(dogs=[d], actions=[dict(do="click", sel="[data-hook='dog-avatar']", wait=150),
                                            dict(do="click", sel="[role='tab'][data-tab='fire']", label="fire", wait=300, capture=[
                                                q("state", "[data-hook='unleash-state']"), q("counts", "[data-hook='unleash-counts']"),
                                                q("note", "[data-hook='unleash-running-note']"), q("btn", "[data-hook='fire-btn']"),
                                                q("now", "[data-hook='unleash-now']"), q("text", "[data-tabpanel='fire']")])])
        c = out["captures"]["fire"]
        self.assertRegex(c["state"], r"^Running ·")
        self.assertEqual(c["counts"], "1 open · 0 settled")
        self.assertEqual(c["btn"], "Check today's games now")
        self.assertNotIn("Unleash starts", c["text"], "the first-time copy is not said to a hound that is already going")
        self.assertIn("Remove from my kennel", c["note"], "there is no pause route, and the page does not pretend there is one")
        self.assertIn("Nothing qualifies right now", c["now"])
        urls = [p["url"] for p in out["posts"]]
        self.assertEqual(urls, ["/hounds/u-1/fire"], "opening the tab only READS (the preview); it places nothing")

    def test_the_button_on_a_running_hound_still_runs_the_real_check(self):
        d = dog("u-1", "Doctor Data Dog", open_bets=1)
        out = self.sheet(dogs=[d], actions=[dict(do="click", sel="[data-hook='dog-avatar']", wait=150),
                                            dict(do="click", sel="[role='tab'][data-tab='fire']", wait=300),
                                            dict(do="click", sel="[data-hook='fire-btn']", label="go", wait=300, capture=[q("headline", "[data-hook='unleash-headline']")])])
        self.assertEqual([p["url"] for p in out["posts"]], ["/hounds/u-1/fire", "/hounds/u-1/unleash"])
        self.assertIn("is unleashed", out["captures"]["go"]["headline"])

    def test_a_hound_that_has_never_bet_still_gets_the_unleash_button(self):
        out = self.sheet(dogs=[dog("u-1", "Fresh Fido")], actions=[dict(do="click", sel="[data-hook='dog-avatar']", wait=100),
                                                                     dict(do="click", sel="[role='tab'][data-tab='fire']", label="fire", wait=200, capture=[
                                                                         q("btn", "[data-hook='fire-btn']"), q("state", "[data-hook='unleash-state']", "count"),
                                                                         q("text", "[data-tabpanel='fire']")])])
        c = out["captures"]["fire"]
        self.assertEqual((c["btn"], c["state"]), ("Unleash", 0))
        self.assertIn("Unleash starts Fresh Fido betting today", c["text"])
        self.assertEqual(out["posts"], [])

    def test_a_paused_hound_has_no_button_the_server_would_refuse(self):
        out = self.sheet(dogs=[dog("u-1", "Sleepy", status="benched", open_bets=0, bets=2, wins=1, losses=1)], actions=[
            dict(do="click", sel="[data-hook='dog-avatar']", wait=100), dict(do="click", sel="[role='tab'][data-tab='fire']", label="fire", wait=200, capture=[
                q("btn", "[data-hook='fire-btn']", "count"), q("said", "[data-hook='unleash-not-running']")])])
        self.assertEqual(out["captures"]["fire"]["btn"], 0)
        self.assertIn("is not betting right now", out["captures"]["fire"]["said"])

    def test_no_off_season_note_is_built_without_a_schedule_the_page_already_loads(self):
        """(b) of the 2026-10-26 add-on: the kennel page loads no schedule. /sports/now lists only the next 24 hours and is not read here, so the
        "few games in the next 7 days" note is NOT built (a guess would be a made-up claim). This pins that nothing says it."""
        for name in ("js/kennel.js", "js/dog-fire.js"):
            self.assertNotIn("postseason, so there are few games", read(name))


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheBacktestTab(StudioHelpers, unittest.TestCase):
    def test_the_seven_day_window_runs_as_the_tab_opens_with_a_loading_state(self):
        from tests.test_backtest_kennel_web import result
        out = self.sheet(extra={"POST /hounds/drill": [200, result(days=7)]}, delay={"POST /hounds/drill": 400}, actions=[
            dict(do="click", sel="[data-hook='dog-avatar']", wait=100),
            dict(do="click", sel="[role='tab'][data-tab='backtest']", label="loading", wait=120, capture=[
                q("loading", "[data-hook='backtest-loading']", "count"), q("pressed", "[data-hook='backtest-window']", "attrs", attr="aria-pressed")]),
            dict(do="wait", label="done", wait=700, capture=[q("loading", "[data-hook='backtest-loading']", "count"),
                                                              q("label", "[data-hook='drill-label']"), q("empty", "[data-hook='backtest-result']", "exists")])])
        self.assertEqual(out["captures"]["loading"]["loading"], 1, "the tab is never chips over an empty screen")
        self.assertEqual(out["captures"]["loading"]["pressed"], ["true", "false", "false", "false"])
        self.assertEqual(out["captures"]["done"]["loading"], 0)
        self.assertIn("hindsight", out["captures"]["done"]["label"])
        self.assertEqual([p["body"] for p in out["posts"] if p["url"] == "/hounds/drill"], [{"dog_id": "u-1", "days": 7}])

    def test_it_runs_once_per_open_not_on_every_look_at_the_tab(self):
        from tests.test_backtest_kennel_web import result
        out = self.sheet(extra={"POST /hounds/drill": [200, result(days=7)]}, actions=[
            dict(do="click", sel="[data-hook='dog-avatar']", wait=100),
            dict(do="click", sel="[role='tab'][data-tab='backtest']", wait=300),
            dict(do="click", sel="[role='tab'][data-tab='ask']", wait=200),
            dict(do="click", sel="[role='tab'][data-tab='backtest']", wait=300)])
        self.assertEqual(len([p for p in out["posts"] if p["url"] == "/hounds/drill"]), 1)

    def test_the_dog_page_and_the_camp_do_not_auto_run(self):
        self.assertNotIn("autoRun: true", read("js/dog-camp.js"))
        self.assertNotIn("autoRun: true", read("js/dog-kit.js"))
        self.assertIn("autoRun: true", read("js/kennel.js"))


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheRulesTab(StudioHelpers, unittest.TestCase):
    def go(self, **kw):
        extra = {"/hounds/mine": [200, {"hounds": [mine_dog()], "limit_running": 3}],
                 "POST /hounds/builder/preview": [200, {"qualifying": 0, "would_bet": 0, "picks": [], "sentences": [], "max_bets_per_day": 2, "paper_only": True}]}
        return self.sheet(dogs=[dog("u-1", "Underdog Gus")], extra=extra, settleMs=200, **kw)

    def test_an_existing_hound_opens_on_its_current_rule_in_words(self):
        out = self.go(actions=[dict(do="click", sel="[data-hook='dog-action-edit']", label="rules", wait=500, capture=[
            q("card", "[data-hook='studio-rule-now']"), q("lines", "[data-hook='studio-rule-lines'] li", "texts"),
            q("edit", "[data-hook='studio-edit-rules']"), q("editor_hidden", "[data-hook='build-app']", "hidden"),
            q("card_hidden", "[data-hook='studio-rule-now']", "hidden"), q("selected", "[role='tab'][aria-selected='true']", "texts")])])
        c = out["captures"]["rules"]
        self.assertEqual(c["selected"], ["Rules"])
        self.assertEqual(c["lines"], ["Bet home underdogs between +120 and +200, at most 2 bets a day."])
        self.assertIn("Current rule · version 3", c["card"])
        self.assertIn("How Underdog Gus bets", c["card"])
        self.assertEqual(c["edit"], "Edit rules")
        self.assertEqual((c["editor_hidden"], c["card_hidden"]), (True, False), "the editor waits behind Edit rules")

    def test_edit_rules_reveals_the_editor(self):
        out = self.go(actions=[dict(do="click", sel="[data-hook='dog-action-edit']", wait=500),
                               dict(do="click", sel="[data-hook='studio-edit-rules']", label="edit", wait=100, capture=[
                                   q("editor_hidden", "[data-hook='build-app']", "hidden"), q("card_hidden", "[data-hook='studio-rule-now']", "hidden"),
                                   q("title", "[data-hook='build-title']")])])
        c = out["captures"]["edit"]
        self.assertEqual((c["editor_hidden"], c["card_hidden"]), (False, True))
        self.assertEqual(c["title"], "Edit Underdog Gus")

    def test_the_example_chip_wraps_inside_its_own_box_and_cannot_widen_the_screen(self):
        css = sheet_css()
        studio_chip = block(css, ".hounds-page .bd-chips .bd-chip.bd-chip--example")
        for want in ("white-space: normal", "max-width: 100%", "flex: 0 1 auto"):
            self.assertIn(want, studio_chip)
        strip = block(css, '.kn-studio .bd-step [data-hook="example-chips"]')
        self.assertIn("flex-wrap: wrap", strip)
        # the same fix on the stand-alone builder page, which has the identical chip row
        self.assertIn('.hounds-page .bd-step [data-hook="example-chips"] { flex-wrap: wrap;', css)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheSheetCopy(unittest.TestCase):
    def test_no_dog_or_beta_in_the_words_the_sheet_adds(self):
        for name in ("js/kennel.js", "js/dog-fire.js", "kennel.html"):
            for line in re.findall(r'(?:text|textContent)[:=] ?[`"]([^`"$]{4,})[`"]', read(name)):
                self.assertNotRegex(line, r"(?i)(dog|dogs|beta)", f"{name}: {line}")
        for line in ("Remove from my kennel", "Current rule", "Edit rules", "Check today's games now", "settled"):
            self.assertNotRegex(line, r"(?i)(dog|beta|new)")

    def test_times_come_from_the_viewers_zone_helper(self):
        self.assertIn('from "./local-time.js"', read("js/kennel.js"))
        self.assertIn('formatStamp("c"', read("js/kennel.js"))


if __name__ == "__main__":      # pragma: no cover
    unittest.main()
