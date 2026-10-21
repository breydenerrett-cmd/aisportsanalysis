"""The unit-size lens on the pages, run for real under node against the fake DOM (web/js/unitsize.js, unitchip.js).

Owner ask 2026-10-21: a viewer chooses what a unit is worth (default $25), or a percent of a bankroll that compounds,
and EVERY dollar on the site follows, while units, grades and ranks do not move. What this file holds the pages to:
  * with nothing stored the page is a $25-unit page ($2,500 start) for everyone, signed in or not;
  * choose $50 and no page prints a figure of the old $10 / $1,000 account (the render check), and the start is $5,000;
  * the leaderboard order is the same at every unit size AND in percent mode (it sorts on the unit-based reference);
  * the chip sits beside the money (leaderboard, hound page, My Kennel), opens the settings and saves a valid choice;
  * the builder's stake picker reads "2u · $50" (fixed) or "2u · 2% of bankroll" (percent);
  * percent mode labels its return "at your sizing".
The runner pins the OTHER page tests to a $10 viewer on purpose (tests/hounds_web_runner.py PIN_REFERENCE).
"""

from __future__ import annotations

import json
import re
import unittest

from tests import hounds_web_fixtures as F
from tests.hounds_web_runner import HAS_NODE, SIZING_KEY, run_page
from tests.test_hounds_board_pages import routes, ticket_routes

TOKEN_KEY = "aisportsanalysis.invite_token"


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


def fixed(unit):
    return {"mode": "fixed", "unit_usd": unit, "pct": None, "start_usd": unit * 100}


PERCENT = {"mode": "percent", "unit_usd": None, "pct": 2, "start_usd": 5000}

#: phrases that only the reference ($1,000 start, $10 unit) account says. At $50 none may appear anywhere on a page.
REFERENCE_FIGURES = ("$1,000", "1 unit = $10", "1u = $10", "$10 unit", "($10")


def page_text(page, viewer, **kw):
    out = run_page(page, viewer=viewer, queries=[q("body", "main")] + kw.pop("queries", []), **kw)
    return out["final"]["body"], out


def kennel_routes():
    board = json.loads(json.dumps(F.leaderboard()))
    dogs = []
    for h in board["hounds"][:3]:
        d = dict(h)
        d.update({"settled": (h["record"].get("wins") or 0) + (h["record"].get("losses") or 0), "open_bets": 0, "new": False,
                  "last_pick": None, "page_href": f"hound.html?id={h['id']}", "retired": False,
                  "builder_href": f"build-a-hound.html?from={h['id']}"})
        dogs.append(d)
    mine = {"handle": "handler-21e8", "display": "Handler 21E8", "kennel_name": "Gus & Co", "dog_count": len(dogs), "dogs": dogs,
            "season": {"id": "s2", "label": "Season 2"}, "paper_only": True, "needs_name_prompt": False, "graveyard": []}
    return {"/hounds/kennels/mine": [200, mine], "/hounds/mine": [200, {"hounds": [], "limit_running": 3, "paper_only": True}]}


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheDefaultIsA25DollarUnit(unittest.TestCase):
    def test_a_visitor_with_nothing_stored_reads_a_2500_dollar_start_on_the_leaderboard(self):
        text, out = page_text("hounds", None, routes=routes(), queries=[q("chip", "[data-hook='unit-chip-label']")])
        self.assertEqual(out["final"]["chip"], "1u = $25")
        self.assertIn("$2,500", text)
        for old in REFERENCE_FIGURES:
            self.assertNotIn(old, text, old)

    def test_the_hound_page_is_a_2500_dollar_account_too(self):
        r = routes(**ticket_routes("closer"))
        text, out = page_text("hound", None, routes=r, search="?id=closer", queries=[q("hero", "[data-hook='hero-bankroll']")])
        ref = F.detail("closer")["bankroll"]
        want = 2500 + sum(e[2] for e in ref["events"]) * 25           # the same units, each worth $25
        self.assertEqual(out["final"]["hero"], f"${want:,.2f}")
        self.assertIn("1u = $25", text)

    def test_storage_that_throws_still_gives_the_default(self):
        for mode in ("methods", "accessor"):
            with self.subTest(storage=mode):
                text, out = page_text("hounds", None, routes=routes(), storageThrows=mode)
                self.assertIn("$2,500", text)


@unittest.skipUnless(HAS_NODE, "node not installed")
class NoPageShowsAHardCodedTenDollarFigureAt50(unittest.TestCase):
    """The render check: every page that prints money, run as a viewer who chose a $50 unit."""

    def check(self, text, where):
        for old in REFERENCE_FIGURES:
            self.assertNotIn(old, text, f"{where}: {old!r} is the reference account, not the viewer's")
        self.assertRegex(text, r"\$5,000", f"{where}: the viewer's start is $5,000")

    def test_the_leaderboard(self):
        text, _ = page_text("hounds", fixed(50), routes=routes())
        self.check(text, "hounds.html")
        self.assertIn("1u = $50", text)

    def test_the_hound_page(self):
        text, _ = page_text("hound", fixed(50), routes=routes(**ticket_routes("closer")), search="?id=closer")
        self.check(text, "hound.html")

    def test_my_kennel(self):
        r = routes()
        r.update(kennel_routes())
        text, _ = page_text("kennel", fixed(50), routes=r, stored={TOKEN_KEY: "tok"})
        self.assertNotIn("$1,000", text)
        self.assertNotIn("1 unit = $10", text)
        self.assertRegex(text, r"Bankroll \$[45],\d{3}")             # a dog card: the $5,000 start plus its profit
        self.assertIn("1u = $50", text)

    def test_the_landing_board(self):
        text, _ = page_text("landing_board", fixed(50), routes=routes())
        self.check(text, "desk.html")

    def test_the_builder_stake_line_and_picker(self):
        from tests.test_hounds_builder_web import CLICK_BLANK, build
        out = build(actions=[CLICK_BLANK], queries=[q("line", "[data-hook='g-stake-line']"), q("options", "[data-hook='g-stake'] option", "texts")],
                    viewer=fixed(50))
        self.assertEqual(out["final"]["line"], "1 unit = $50 of your $5,000; this dog bets 1 unit ($50 a bet).")
        self.assertIn("1u · $50", out["final"]["options"])
        self.assertIn("3u · $150", out["final"]["options"])
        self.assertIn("5u · $250", out["final"]["options"])
        self.assertIsNone(re.search(r"\$10", " ".join(out["final"]["options"])))


@unittest.skipUnless(HAS_NODE, "node not installed")
class UnitsAndRanksNeverMove(unittest.TestCase):
    def order(self, viewer):
        row = "[data-hook='hounds-list'] .hd-tr"
        out = run_page("hounds", viewer=viewer, routes=routes(),
                       queries=[q("ids", row, "attrs", attr="data-hound"), q("units", f"{row} [data-hook='row-units']", "texts")])
        return out["final"]["ids"], out["final"]["units"]

    def test_the_leaderboard_order_and_units_are_the_same_at_every_sizing(self):
        base_names, base_units = self.order(fixed(10))
        self.assertTrue(base_names and base_units)
        for viewer in (None, fixed(25), fixed(100), fixed(3), PERCENT):
            with self.subTest(viewer=viewer):
                names, units = self.order(viewer)
                self.assertEqual(names, base_names)
                self.assertEqual(units, base_units)           # "+2.4u" figures are the record


@unittest.skipUnless(HAS_NODE, "node not installed")
class PercentOfBankroll(unittest.TestCase):
    def test_the_return_is_labelled_at_your_sizing_and_fixed_is_not(self):
        r = routes(**ticket_routes("closer"))
        pct_text, out = page_text("hound", PERCENT, routes=r, search="?id=closer", queries=[q("label", "[data-slot='return'] .hd-kpi__label")])
        self.assertEqual(out["final"]["label"], "Return, at your sizing")
        self.assertIn("1u = 2% of bankroll", pct_text)
        self.assertIn("$5,000", pct_text)
        fixed_text, out = page_text("hound", fixed(25), routes=r, search="?id=closer", queries=[q("label", "[data-slot='return'] .hd-kpi__label")])
        self.assertEqual(out["final"]["label"], "Return")

    def test_the_hero_bankroll_is_the_compounded_balance(self):
        from src.hounds import unit_size as us
        r = routes(**ticket_routes("closer"))
        ref = F.detail("closer")["bankroll"]
        # the same events through Python's one definition
        from src.hounds import bankroll as bk
        events = [bk.Event(settle=None, units=e[2], flat=e[2], stake=e[3], result={"w": "win", "l": "loss", "p": "push"}.get(e[4], "void"),
                           order=(e[0], str(i))) for i, e in enumerate(ref["events"])]
        want = bk.block(events, None, sizing=us.validate(PERCENT))["current"]
        _, out = page_text("hound", PERCENT, routes=r, search="?id=closer", queries=[q("hero", "[data-hook='hero-bankroll']")])
        self.assertEqual(out["final"]["hero"], f"${want:,.2f}")

    def test_the_stake_picker_names_the_share_of_bankroll(self):
        from tests.test_hounds_builder_web import CLICK_BLANK, build
        out = build(actions=[CLICK_BLANK], queries=[q("options", "[data-hook='g-stake'] option", "texts"), q("line", "[data-hook='g-stake-line']")],
                    viewer=PERCENT)
        self.assertIn("2u · 4% of bankroll", out["final"]["options"])
        self.assertIn("1u · 2% of bankroll", out["final"]["options"])
        self.assertIn("2% of bankroll", out["final"]["line"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheChip(unittest.TestCase):
    def test_it_sits_beside_the_money_on_the_leaderboard_the_hound_page_and_my_kennel(self):
        for page, kw in (("hounds", dict(routes=routes())),
                         ("hound", dict(routes=routes(**ticket_routes("closer")), search="?id=closer")),
                         ("kennel", dict(routes={**routes(), **kennel_routes()}, stored={TOKEN_KEY: "tok"}))):
            with self.subTest(page=page):
                out = run_page(page, viewer=fixed(25), queries=[q("chip", "[data-hook='unit-chip']")], **kw)
                self.assertIn("1u = $25", out["final"]["chip"])

    def test_saving_a_custom_unit_stores_it_for_a_visitor_and_sends_nothing(self):
        out = run_page("hounds", viewer=None, routes=routes(), actions=[
            dict(do="click", sel="[data-hook='unit-chip']", wait=20),
            dict(do="set", sel="[data-hook='us-unit']", value="75", wait=10),
            dict(do="click", sel="[data-hook='us-save']", wait=80, label="saved", capture=[q("status", "[data-hook='us-status']")])],
            queries=[q("stored", "[data-hook='us-status']")])
        self.assertIn("Saved: 1u = $75", out["captures"]["saved"]["status"])
        self.assertEqual([p for p in out.get("posts", []) if "unit-size" in p["url"]], [])      # a visitor has no account to PUT to

    def test_a_refused_unit_says_why_and_stores_nothing(self):
        for bad in ("0", "1001", "12.5"):
            with self.subTest(unit=bad):
                out = run_page("hounds", viewer=None, routes=routes(), actions=[
                    dict(do="click", sel="[data-hook='unit-chip']", wait=20),
                    dict(do="set", sel="[data-hook='us-unit']", value=bad, wait=10),
                    dict(do="click", sel="[data-hook='us-save']", wait=40, label="refused", capture=[q("status", "[data-hook='us-status']")])])
                self.assertIn("whole number of dollars", out["captures"]["refused"]["status"])

    def test_a_signed_in_member_saves_to_the_account(self):
        out = run_page("hounds", viewer=None, routes={**routes(), "/me/unit-size": [200, {"sizing": fixed(25)}]}, stored={TOKEN_KEY: "tok"}, actions=[
            dict(do="click", sel="[data-hook='unit-chip']", wait=20),
            dict(do="click", sel="[data-hook='us-chip-100']", wait=10),
            dict(do="click", sel="[data-hook='us-save']", wait=120)])
        puts = [p for p in out.get("posts", []) if p["url"].endswith("/me/unit-size") and p["method"] == "PUT"]
        self.assertEqual(len(puts), 1)
        self.assertEqual((puts[0]["body"]["mode"], puts[0]["body"]["unit_usd"], puts[0]["body"]["start_usd"]), ("fixed", 100, 10000))


class TheStaticWords(unittest.TestCase):
    """Sentences in the HTML name the viewer's money through data-us, and ship the default ($25 / $2,500) for no-JS."""

    def test_every_data_us_key_has_a_sentence_and_the_html_ships_the_default(self):
        from tests.hounds_web_runner import WEB
        js = (WEB / "js" / "unitsize.js").read_text(encoding="utf-8")
        for page in ("hounds.html", "desk.html", "learning.html"):
            html = (WEB / page).read_text(encoding="utf-8")
            keys = re.findall(r'data-us="([a-z-]+)"', html)
            self.assertTrue(keys, page)
            for key in keys:
                self.assertIn(f'"{key}":', js, f"{page}: {key}")
            self.assertNotIn("$1,000", html, page)
            self.assertNotIn("$10 ", html.replace("$10,", ""), page)


if __name__ == "__main__":
    unittest.main()
