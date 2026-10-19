"""The bankroll view on the pages (docs/BANKROLL.md), run for real under node against the fake DOM.

What this file holds the pages to (owner, 2026-10-19: "units up and ROI 71% do not make sense"):
  * the leaderboard says, in the server's own words, that every model starts with the same $1,000 paper bankroll and
    1 unit = $10; its columns are Bankroll, Return, 7d, 24h, Units (no ROI); the default sort is the balance; a small
    sample is greyed with the reason; a model settled at its recorded price says so;
  * the model page's strip leads with the account and a Return tile that switches between 24h / 7d / 30d / Season,
    and its chart is the account in dollars; the yield is kept there, labelled "profit per $ bet";
  * the landing board is the top five by bankroll with the return %;
  * a ticket at -200 or worse (old rule) carries a small tag in every ticket list;
  * the builder says what the stake is in dollars, live;
  * the kennel cards show the dog's bankroll and return.
"""

from __future__ import annotations

import json
import unittest

from tests import hounds_web_fixtures as F
from tests.hounds_web_runner import HAS_NODE, run_js, run_page
from tests.test_hounds_board_pages import routes, ticket_routes


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


LABEL = "Every model starts with the same $1,000 paper bankroll. 1 unit = $10."


@unittest.skipUnless(HAS_NODE, "node not installed")
class ThePureHelpers(unittest.TestCase):
    def js(self, body):
        return run_js('import * as B from "./hounds-board.js";\n' + body)

    def test_money_and_percent_words(self):
        out = self.js("console.log(JSON.stringify([B.fmtUsd(1021.4), B.fmtUsd(1021.4, true), B.fmtUsd(-5), B.fmtUsd(-0.2), "
                      "B.fmtUsd(null), B.fmtSignedUsd(14.2), B.fmtSignedUsd(-7), B.fmtSignedUsd(0.3), B.fmtPct(2.14), B.fmtPct(-0.04), B.fmtPct(null)]));")
        self.assertEqual(out, ["$1,021", "$1,021.40", "-$5", "$0", "n/a", "+$14", "-$7", "+$0", "+2.1%", "0.0%", "n/a"])

    def test_the_stake_line_says_what_the_stake_is_in_dollars(self):
        out = self.js("const r = {start_usd: 1000, unit_usd: 10};\nconsole.log(JSON.stringify([B.stakeLineText(2, r), B.stakeLineText(1, r), "
                      "B.stakeLineText(0.5, r), B.stakeLineText(3, null)]));")
        self.assertEqual(out, ["1 unit = $10 of your $1,000; this dog bets 2 units ($20 a bet).",
                               "1 unit = $10 of your $1,000; this dog bets 1 unit ($10 a bet).",
                               "1 unit = $10 of your $1,000; this dog bets 0.5 units ($5 a bet).",
                               "1 unit = $10 of your $1,000; this dog bets 3 units ($30 a bet)."])

    def test_rules_come_from_the_payload_with_a_fallback_for_an_old_saved_copy(self):
        out = self.js(f"console.log(JSON.stringify([B.bankrollRules({{bankroll_rules: {{start_usd: 500, unit_usd: 5, label: 'X'}}}}), B.bankrollRules({{}})]));")
        self.assertEqual(out[0], {"start": 500, "unit": 5, "label": "X"})
        self.assertEqual(out[1], {"start": 1000, "unit": 10, "label": LABEL})

    def test_windows_are_n_a_when_nothing_settled_in_them_not_a_flat_zero(self):
        out = self.js('const h = {bankroll: {current: 1010, start: 1000, bets: 3, return_pct: 1.0, windows: '
                      '{h24: {return_pct: 0, pnl_usd: 0, units: 0, bets: 0, settled: 0}, d7: {return_pct: 1.0, pnl_usd: 10, units: 1, bets: 3, settled: 3}}}};\n'
                      'console.log(JSON.stringify([B.windowPct(h, "h24"), B.windowPct(h, "d7"), B.windowPct(h, "d30"), B.windowPct({}, "d7")]));')
        self.assertEqual(out, [None, 1.0, None, None])

    def test_the_default_order_is_the_balance_and_units_are_stake_weighted(self):
        out = self.js('const m = (id, cur, units, bets=30) => ({id, name: id, record: {bets}, bankroll: {current: cur, start: 1000, bets, units_total: units}});\n'
                      'const hs = [m("a", 1020, 2), m("b", 1100, 10), m("c", 980, -2), m("none", 1000, 0, 0)];\n'
                      'console.log(JSON.stringify([B.sortByBankroll(hs).map(h => h.id), B.sortHounds(hs, "bankroll", "desc").map(h => h.id), '
                      'B.sortHounds(hs, "units", "desc").map(h => h.id), B.COLUMNS.map(c => c.key), B.DEFAULT_SORT]));')
        self.assertEqual(out[0], ["b", "a", "c", "none"])
        self.assertEqual(out[1], ["b", "a", "c", "none"])           # a model with nothing graded is last, not tied at $1,000
        self.assertEqual(out[2], ["b", "a", "c", "none"])
        self.assertNotIn("roi", out[3])
        self.assertEqual(out[4], "bankroll")

    def test_small_sample_follows_the_server_flag_then_the_count(self):
        out = self.js('console.log(JSON.stringify([B.isSmallSample({bankroll: {current: 1, start: 1, small_sample: true}, record: {wins: 30}}), '
                      'B.isSmallSample({bankroll: {current: 1, start: 1, small_sample: false}, record: {wins: 3}}), '
                      'B.isSmallSample({record: {wins: 5, losses: 4}}), B.isSmallSample({record: {wins: 15, losses: 10}})]));')
        self.assertEqual(out, [True, False, True, False])

    def test_the_old_rule_tag_follows_the_servers_flag_only(self):
        out = self.js("console.log(JSON.stringify([B.isOldRule({beyond_cap: true}), B.isOldRule({beyond_cap: false}), B.isOldRule({price: -250}), B.OLD_RULE_TAG]));")
        self.assertEqual(out, [True, False, False, "-200 or worse (old rule)"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheLeaderboard(unittest.TestCase):
    def board(self, edit=None):
        data = json.loads(json.dumps(F.leaderboard()))
        if edit:
            edit(data)
        return routes(**{"/hounds": [200, data]})

    def test_it_says_every_model_starts_with_the_same_thousand_dollars(self):
        out = run_page("hounds", routes=routes(), queries=[q("line", "[data-hook='bankroll-line']"), q("cap", "[data-hook='leaderboard-table'] caption")])
        self.assertEqual(out["final"]["line"], LABEL)
        self.assertIn("$1,000", out["final"]["cap"])

    def test_the_static_page_already_carries_the_line_for_a_visitor_with_scripts_off(self):
        html = (F.Path(__file__).resolve().parent.parent / "web" / "hounds.html").read_text(encoding="utf-8")
        self.assertIn(LABEL, html)

    def test_a_thin_sample_is_greyed_with_the_reason_in_its_tooltip(self):
        def edit(data):
            row = next(h for h in data["hounds"] if h["id"] == "closer")
            row["bankroll"]["small_sample"] = True
        out = run_page("hounds", routes=self.board(edit), queries=[
            q("grey", "[data-hound='closer'] [data-small='true']", "count"),
            q("title", "[data-hound='closer'] [data-hook='row-bankroll']", "attr", attr="title"),
            q("others", "[data-hound='steamer'] [data-small='true']", "count")])
        self.assertEqual(out["final"]["grey"], 5)          # balance, return, 7d, 24h, units
        self.assertTrue(out["final"]["title"].startswith("Small sample:"), out["final"]["title"])
        self.assertEqual(out["final"]["others"], 0)

    def test_a_model_settled_at_its_recorded_price_is_marked_and_the_others_are_not(self):
        def edit(data):
            row = next(h for h in data["hounds"] if h["id"] == "steamer")
            row["bankroll"]["basis"] = "recorded_price"
            row["record"]["units_average_price"] = None
        out = run_page("hounds", routes=self.board(edit), queries=[
            q("tags", "[data-hook='basis-tag']", "texts"),
            q("where", "[data-hook='basis-tag']", "attrs", attr="title"),
            q("owner", "[data-hook='basis-tag']", "count")])
        self.assertEqual(out["final"]["tags"], ["best price"])
        self.assertIn("average-price board is missing", out["final"]["where"][0])

    def test_the_windows_read_n_a_when_nothing_settled_in_them(self):
        def edit(data):
            row = next(h for h in data["hounds"] if h["id"] == "closer")
            row["bankroll"]["windows"]["h24"].update(bets=0, settled=0, return_pct=0.0, pnl_usd=0.0, units=0.0)
        out = run_page("hounds", routes=self.board(edit), queries=[q("h24", "[data-hound='closer'] [data-hook='row-h24']")])
        self.assertEqual(out["final"]["h24"], "n/a")

    def test_the_latest_tickets_tag_a_minus_200_ticket_and_only_that_one(self):
        stream = json.loads(json.dumps(F.stream()))
        stream["items"][0]["beyond_cap"] = True
        out = run_page("hounds", routes=routes(**{"/hounds/stream": [200, stream]}), queries=[
            q("tags", "[data-hook='hounds-stream'] [data-hook='old-rule']", "texts")])
        self.assertTrue(out["final"]["tags"])
        self.assertTrue(all(t == "-200 or worse (old rule)" for t in out["final"]["tags"]), out["final"]["tags"])
        out = run_page("hounds", routes=routes(), queries=[q("tags", "[data-hook='old-rule']", "count")])
        self.assertEqual(out["final"]["tags"], 0)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheModelPage(unittest.TestCase):
    def page(self, hid="closer", **kw):
        r = routes(**ticket_routes(hid))
        r.update(kw.pop("routes", {}))
        return run_page("hound", routes=r, search=f"?id={hid}", **kw)

    def test_the_return_tile_switches_between_the_four_windows(self):
        b = F.detail("closer")["bankroll"]
        def pct(key):
            w = b["windows"][key]
            return f"{w['return_pct']:+.1f}%" if w["bets"] else "n/a"
        out = self.page(queries=[q("tabs", "[data-hook='return-tabs'] button", "texts"),
                                 q("sel", "[data-hook='return-tabs'] button", "attrs", attr="aria-selected"),
                                 q("big", "[data-hook='return-big']")], actions=[
            dict(do="click", sel="[data-hook='return-tab-h24']", label="h24", capture=[q("big", "[data-hook='return-big']"), q("small", "[data-hook='return-small']")]),
            dict(do="click", sel="[data-hook='return-tab-d7']", label="d7", capture=[q("big", "[data-hook='return-big']")]),
            dict(do="click", sel="[data-hook='return-tab-d30']", label="d30", capture=[q("big", "[data-hook='return-big']")]),
            dict(do="click", sel="[data-hook='return-tab-season']", label="season", capture=[q("big", "[data-hook='return-big']")])])
        self.assertEqual(out["final"]["tabs"], ["24h", "7d", "30d", "Season"])
        self.assertEqual(out["final"]["sel"], ["false", "false", "false", "true"])        # opens on the season shown
        self.assertEqual(out["final"]["big"], pct("season"))
        for key in ("h24", "d7", "d30", "season"):
            self.assertEqual(out["captures"][key]["big"], pct(key), key)
        self.assertIn("settled in the last 24 hours", out["captures"]["h24"]["small"])

    def test_a_window_with_no_settled_bet_says_so_instead_of_zero(self):
        d = json.loads(json.dumps(F.detail("closer")))
        d["bankroll"]["windows"]["h24"].update(bets=0, settled=0, return_pct=0.0, pnl_usd=0.0, units=0.0)
        out = self.page(routes={"/hounds/closer?season=s2": [200, d], "/hounds/closer": [200, d]}, actions=[
            dict(do="click", sel="[data-hook='return-tab-h24']", label="h24", capture=[q("big", "[data-hook='return-big']"), q("small", "[data-hook='return-small']")])])
        self.assertEqual(out["captures"]["h24"]["big"], "n/a")
        self.assertIn("no bet settled in the last 24 hours", out["captures"]["h24"]["small"])

    def test_the_chart_is_the_account_in_dollars_from_the_thousand_dollar_start(self):
        out = self.page(queries=[
            q("ticks", "[data-hook='hound-units-chart'] .hd-chart__tick", "texts"),
            q("zero", "[data-hook='hound-units-chart'] .hd-chart__zero-label"),
            q("title", "[data-hook='hound-chart-title']"),
            q("label", "[data-hook='hound-units-chart'] .hd-chart__svg", "attr", attr="aria-label"),
            q("table", "[data-hook='hound-units-chart'] [data-hook='chart-data-table'] tbody td", "texts")])
        f = out["final"]
        self.assertIn("$1,000 start", f["zero"])
        self.assertTrue(any(t.startswith("$") for t in f["ticks"]), f["ticks"])
        self.assertIn("$1,000", f["title"])
        self.assertIn("dollars", f["label"].lower())
        self.assertTrue(all(c.startswith("$") for c in f["table"] if c != "-"), f["table"])

    def test_the_yield_stays_on_this_page_and_says_what_it_is(self):
        b = F.detail("closer")["bankroll"]
        out = self.page(queries=[q("y", ".hd-kpi[data-slot='yield']")])
        self.assertIn(f"{b['yield_pct']:+.1f}%", out["final"]["y"])
        self.assertIn("profit per $ bet", out["final"]["y"])

    def test_the_tiles_say_which_price_a_recorded_price_model_is_settled_at(self):
        d = json.loads(json.dumps(F.detail("closer")))
        d["bankroll"]["basis"] = "recorded_price"
        out = self.page(routes={"/hounds/closer?season=s2": [200, d], "/hounds/closer": [200, d]},
                        queries=[q("bank", ".hd-kpi[data-slot='bankroll']"), q("note", "[data-hook='chart-basis']")])
        self.assertIn("at the price it took", out["final"]["bank"])
        self.assertIn("missing for more than 10%", out["final"]["note"])
        out = self.page(queries=[q("bank", ".hd-kpi[data-slot='bankroll']"), q("note", "[data-hook='chart-basis']")])
        self.assertIn("at the average price across books", out["final"]["bank"])
        self.assertNotIn("missing for more than 10%", out["final"]["note"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheLandingBoard(unittest.TestCase):
    def test_a_minus_200_ticket_is_tagged_in_the_latest_five(self):
        stream = json.loads(json.dumps(F.stream()))
        stream["items"][0]["beyond_cap"] = True
        r = {k: list(v) for k, v in F.routes().items()}
        r["/hounds/stream"] = [200, stream]
        out = run_page("landing_board", routes=r, queries=[q("tags", "[data-hook='lb-old-rule']", "texts")])
        self.assertEqual(out["final"]["tags"], ["-200 or worse (old rule)"])

    def test_a_recorded_price_model_is_marked_on_the_landing_board_too(self):
        data = json.loads(json.dumps(F.leaderboard()))
        top = next(h for h in data["hounds"] if h["id"] == "closer")
        top["bankroll"]["basis"] = "recorded_price"
        r = {k: list(v) for k, v in F.routes().items()}
        r["/hounds"] = [200, data]
        out = run_page("landing_board", routes=r, queries=[q("tags", "[data-hook='lb-basis']", "texts")])
        self.assertEqual(out["final"]["tags"], ["best price"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheKennels(unittest.TestCase):
    def test_the_kennel_index_says_the_best_dogs_balance_and_return(self):
        out = run_page("kennels_index", routes={"/hounds/kennels": [200, {"kennels": [{
            "handle": "handler-1", "display": "Handler 1", "dog_count": 2, "new_dogs": 0, "href": "kennel.html?u=handler-1",
            "dogs": [], "best": {"id": "u-1", "name": "Gus", "settled": 12, "record": {"wins": 8, "losses": 4, "pushes": 0},
                                 "bankroll": {"current": 1032.5, "start": 1000, "return_pct": 3.25}}}], "count": 1,
            "season": {"id": "s2", "label": "Season 2"}, "paper_only": True}]},
            queries=[q("meta", ".kn-kcard__meta")])
        self.assertIn("Best: Gus, 8-4, $1,033 (+3.3%)", out["final"]["meta"])

    def test_a_kennel_without_a_bankroll_block_keeps_its_old_line(self):
        out = run_page("kennels_index", routes={"/hounds/kennels": [200, {"kennels": [{
            "handle": "handler-1", "display": "Handler 1", "dog_count": 1, "new_dogs": 0, "href": "kennel.html?u=handler-1",
            "dogs": [], "best": {"id": "u-1", "name": "Gus", "settled": 3, "record": {"wins": 2, "losses": 1, "pushes": 0}}}],
            "count": 1, "season": {"id": "s2", "label": "Season 2"}, "paper_only": True}]},
            queries=[q("meta", ".kn-kcard__meta")])
        self.assertIn("Best: Gus, 2-1", out["final"]["meta"])
        self.assertNotIn("$", out["final"]["meta"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheBuilder(unittest.TestCase):
    def test_the_stake_line_follows_the_picker(self):
        from tests.test_hounds_builder_web import CLICK_BLANK, build
        out = build(actions=[CLICK_BLANK, dict(do="set", sel="[data-hook='g-stake']", value="2", wait=40, label="two",
                                                capture=[q("line", "[data-hook='g-stake-line']")])],
                    queries=[q("line", "[data-hook='g-stake-line']")])
        self.assertEqual(out["final"]["line"], "1 unit = $10 of your $1,000; this dog bets 2 units ($20 a bet).")
        self.assertEqual(out["captures"]["two"]["line"], "1 unit = $10 of your $1,000; this dog bets 2 units ($20 a bet).")

    def test_the_default_stake_is_one_unit_of_ten_dollars(self):
        from tests.test_hounds_builder_web import CLICK_BLANK, build
        out = build(actions=[CLICK_BLANK], queries=[q("line", "[data-hook='g-stake-line']")])
        self.assertEqual(out["final"]["line"], "1 unit = $10 of your $1,000; this dog bets 1 unit ($10 a bet).")

    def test_the_menu_carries_the_numbers_the_line_reads(self):
        from src.hounds import user_spec
        menu = user_spec.builder_menu()
        self.assertEqual((menu["bankroll"]["start_usd"], menu["bankroll"]["unit_usd"]), (1000.0, 10.0))


if __name__ == "__main__":
    unittest.main()
