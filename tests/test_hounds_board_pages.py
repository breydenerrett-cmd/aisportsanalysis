"""The model leaderboard (web/hounds.html) and the model page (web/hound.html?id=), run for real under node.

Owner, 2026-10-19: the kennel looked like "a kids playground, not a professional gambling AI website". The pages
are now a sportsbook-style product: a sortable leaderboard table, a live ticket feed, and per-model pages with open
and graded ticket tables. This file holds them to:

  LEADERBOARD   the columns, sorting, the sport / type / "My models" filters, the "Warming up (N)" group that keeps
                0-bet models out of the table, the inline drawer of a model's last tickets, the "Latest tickets"
                feed rendered from stream fixtures (refusals are not tickets), the retired-models table, the
                "Data as of" line and its amber "Updating" note, and every honest empty / missing / down state;
  MODEL PAGE    the header (initials badge, status, one italic catchphrase and nothing else from the persona),
                the KPI strip, open and graded ticket tables (server-filtered, paged), the rule, the retired and
                idle notes, the chart states;
  BOTH          one disclosure per page, no emoji in the chrome, no cartoon avatar drawing anywhere.

Skipped when node is not installed. Fixtures: tests/hounds_web_fixtures.py (built by the real contract code).
"""

# Copy updated per owner ruling 2026-10-20, complete-product positioning (no beta / early-access / paused hedging; invite wording).
from __future__ import annotations

import copy
import json
import re
import unittest

from tests import hounds_web_fixtures as F
from tests.hounds_web_runner import HAS_NODE, run_js, run_page

FOLLOW_KEY = "linehound.followed_dogs"
RANK_MIN = 10                      # settled bets a model needs to be ranked in a view (src/hounds/seasons.py)
RANKED_N = len([h for h in F.hounds() if h["record"]["bets"] >= RANK_MIN and h["status"] != "retired"])
# every pictograph / emoji block a UI string could use (the text glyphs the tables use, like an arrow, are not in here)
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-⛿✀-➿⭐✅❌]")


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


def routes(**over):
    r = {k: list(v) for k, v in F.routes().items()}
    ids = [h["id"] for h in F.hounds()]
    r["/hounds/series"] = [200, F.series(ids, True)]
    r.update(over)
    return r


def mk(hid, name, verdict="TOO EARLY", bets=10, units=0.0, **extra):
    h = {"id": hid, "name": name, "kind": "house", "category": "stats", "style": "x", "status": "running", "tagline": "t",
         "sports": ["mlb"], "markets": ["h2h"],
         "verdict": {"label": verdict, "sentence": f"{verdict.lower()} sentence"},
         "record": {"bets": bets, "wins": bets // 2, "losses": bets - bets // 2, "pushes": 0, "voids": 0,
                    "units_recorded_price": units, "units_average_price": units},
         "clv": None, "spark": [0, units], "verified": True, "open_bets": 0}
    h.update(extra)
    return h


def ticket_routes(hid="closer", n=45):
    """The exact URLs the model page asks for, answered from the fixture rows."""
    base = f"/hounds/{hid}/bets"
    return {
        f"{base}?status=open&segment=forward&page=1&page_size=50": [200, F.bets_payload(hid, n, 1, 50, "forward", "open")],
        f"{base}?status=graded&segment=forward&page=1&page_size=20": [200, F.bets_payload(hid, n, 1, 20, "forward", "graded")],
        f"{base}?status=graded&segment=forward&page=2&page_size=20": [200, F.bets_payload(hid, n, 2, 20, "forward", "graded")],
        f"{base}?status=graded&segment=forward&page=3&page_size=20": [200, F.bets_payload(hid, n, 3, 20, "forward", "graded")],
        f"{base}?status=graded&segment=replay&page=1&page_size=20": [200, F.bets_payload(hid, n, 1, 20, "replay", "graded")],
        f"{base}?page=1&page_size=10&segment=forward&season=s2": [200, F.bets_payload(hid, n, 1, 10, "forward")],
    }


# ---------------------------------------------------------------------------------------------------
# the pure helpers
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class ThePureHelpers(unittest.TestCase):
    def js(self, body):
        return run_js('import * as B from "./hounds-board.js";\nimport * as C from "./hounds-core.js";\n' + body)

    def test_roi_is_units_per_bet_as_a_percent_and_null_without_a_graded_bet(self):
        out = self.js('console.log(JSON.stringify([B.roiOf({record:{bets:50,units_average_price:5}}),'
                      'B.roiOf({record:{bets:0}}), B.roiOf({record:{bets:20,units_average_price:null,units_recorded_price:-2}}),'
                      'B.fmtRoi(10), B.fmtRoi(-0.04), B.fmtRoi(null)]));')
        self.assertEqual(out, [10, None, -10, "+10.0%", "0.0%", "n/a"])

    def test_status_is_the_referees_label_in_plain_words_and_never_a_function_of_units(self):
        cases = [("BEATING THE CLOSE", 10, "Beating the close"), ("NO DIFFERENT FROM THE MARKET", 200, "Market"),
                 ("PAYING THE VIG", 300, "Paying the vig"), ("TOO EARLY", 93, "Verdict at 150 bets (93/150)"),
                 ("", 0, "Not graded vs close")]
        for label, n, want in cases:
            with self.subTest(label=label):
                hound = {"verdict": {"label": label}, "clv": {"n": n}, "record": {"bets": 5, "units_average_price": 99}}
                self.assertEqual(self.js(f"console.log(JSON.stringify(B.statusOf({json.dumps(hound)}).text));"), want)
        # a huge units total changes nothing
        a = self.js('console.log(JSON.stringify(B.statusOf({verdict:{label:"PAYING THE VIG"},record:{bets:9,units_average_price:900}}).key));')
        self.assertEqual(a, "vig")
        self.assertEqual(self.js('console.log(JSON.stringify(B.statusOf({status:"retired",verdict:{label:"BEATING THE CLOSE"}}).text));'), "Retired")

    def test_clv_needs_a_measurable_bet_and_says_how_many(self):
        none = self.js('console.log(JSON.stringify(B.clvOf({clv:null})));')
        self.assertIsNone(none)
        some = self.js('console.log(JSON.stringify(B.clvOf({clv:{n:93,mean_pts:-0.9},form:{clv_beat:{n:93,beat:40,pct:0.43}}})));')
        self.assertEqual((some["n"], some["mean"], round(some["beatPct"])), (93, -0.9, 43))

    def test_last_ten_keeps_only_results_and_at_most_ten(self):
        out = self.js('console.log(JSON.stringify([B.last10Of({form:{last10:["W","L","x","P"]}}), B.last10Of({}),'
                      'B.last10Of({form:{last10:Array(14).fill("W")}}).length]));')
        self.assertEqual(out, [["W", "L", "P"], [], 10])

    def test_sorting_puts_a_model_with_no_value_last_either_way_and_breaks_ties_by_name(self):
        hs = [mk("a", "Alpha", bets=10, units=5), mk("b", "Bravo", bets=30, units=-3), mk("c", "Charlie", bets=10, units=5),
              mk("d", "Delta", bets=0, units=0)]
        for h in hs:
            if h["record"]["bets"] == 0:
                h["record"] = {"bets": 0}
        for key, direction, want in (("units", "desc", ["a", "c", "b", "d"]), ("units", "asc", ["b", "a", "c", "d"]),
                                     ("bets", "desc", ["b", "a", "c", "d"]), ("model", "asc", ["a", "b", "c", "d"])):
            with self.subTest(key=key, direction=direction):
                got = self.js(f"console.log(JSON.stringify(B.sortHounds({json.dumps(hs)}, '{key}', '{direction}').map(h => h.id)));")
                self.assertEqual(got, want)

    def test_zero_graded_models_are_split_off_as_warming_up(self):
        hs = [mk("a", "A", bets=3), mk("b", "B", bets=0), mk("c", "C", bets=1)]
        hs[1]["record"] = {"bets": 0}
        out = self.js(f"const r = B.splitWarming({json.dumps(hs)}); console.log(JSON.stringify([r.active.map(h=>h.id), r.warming.map(h=>h.id)]));")
        self.assertEqual(out, [["a", "c"], ["b"]])

    def test_freshness_is_amber_only_after_six_hours_or_for_a_saved_copy(self):
        def f(payload, now):
            return self.js(f"console.log(JSON.stringify(B.freshness({json.dumps(payload)}, {now})));")
        noon = "Date.parse('2026-10-19T12:00:00Z')"
        self.assertFalse(f({"as_of": "2026-10-19T08:00:00Z"}, noon)["stale"])          # 4 hours
        self.assertTrue(f({"as_of": "2026-10-19T05:59:00Z"}, noon)["stale"])           # just over 6 hours
        self.assertFalse(f({"as_of": "2026-10-19"}, noon)["stale"])                    # a day is read as the end of that day
        self.assertTrue(f({"as_of": "2026-10-18"}, noon)["stale"])
        self.assertTrue(f({"as_of": "2026-10-19T11:59:00Z", "stale": True}, noon)["stale"])
        none = f({}, noon)
        self.assertEqual((none["label"], none["stale"]), ("", False))
        self.assertEqual(f({"as_of": "2026-10-18"}, noon)["label"], "Oct 18")

    def test_initials_are_two_letters(self):
        out = self.js('console.log(JSON.stringify(["Steamy Setter","Pointer","Coin-Flip Collie","The Desk","",null,"X"].map(C.initialsOf)));')
        self.assertEqual(out, ["SS", "PO", "CF", "TD", "?", "?", "X"])

    def test_a_ticket_status_and_its_recorded_line(self):
        out = self.js('console.log(JSON.stringify(["win","loss","push","void",null,"weird"].map(B.ticketStatus)));')
        self.assertEqual(out, ["won", "lost", "push", "void", "pending", "pending"])
        rec = self.js('console.log(JSON.stringify([B.recordedText({recorded_utc:"2026-10-24T22:41:00Z",start_utc:"2026-10-24T23:10:00Z"}),'
                      'B.recordedText({recorded_utc:"2026-10-24T20:00:00Z",start_utc:"2026-10-24T23:10:00Z"}),'
                      'B.recordedText({recorded_utc:"2026-10-24T23:30:00Z",start_utc:"2026-10-24T23:10:00Z"}),'
                      'B.recordedText({recorded_utc:"2026-10-24T23:30:00Z"}), B.recordedText({})]));')
        self.assertEqual([r["kind"] for r in rec], ["before", "before", "after", "recorded", "none"])
        self.assertEqual(rec[0]["text"], "Oct 24 22:41 UTC, 29m before the start")
        self.assertEqual(rec[1]["text"], "Oct 24 20:00 UTC, 3h 10m before the start")
        self.assertIn("after the start", rec[2]["text"])
        self.assertEqual(rec[4]["text"], "n/a")

    def test_refusals_are_not_tickets(self):
        out = self.js('console.log(JSON.stringify(B.onlyTickets([{refused:false,verdict:"play"},{refused:true,verdict:"refused_thin"},null]).length));')
        self.assertEqual(out, 1)


# ---------------------------------------------------------------------------------------------------
# the leaderboard
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class TheLeaderboardTable(unittest.TestCase):
    ROW = "[data-hook='hounds-list'] .hd-tr"

    def page(self, r=None, **kw):
        return run_page("hounds", routes=routes() if r is None else r, **kw)

    def graded(self):
        """The ranked models: at least 10 settled bets in the view (the others wait in "Warming up")."""
        return [h for h in F.hounds() if h["record"]["bets"] >= RANK_MIN and h["status"] != "retired"]

    def test_the_columns_are_the_ones_a_bettor_reads(self):
        out = self.page(queries=[q("sorts", "[data-hook='leaderboard-table'] thead [data-sort]", "attrs", attr="data-sort"),
                                 q("heads", "[data-hook='leaderboard-table'] thead th", "texts"),
                                 q("aria", "[data-hook='leaderboard-table'] thead th", "attrs", attr="aria-sort")])
        self.assertEqual(out["final"]["sorts"], ["model", "type", "record", "bankroll", "return", "d7", "h24", "units", "bets",
                                                 "price", "clv", "last10", "status"])
        heads = [re.sub(r"\s*[▲▼]", "", t) for t in out["final"]["heads"]]
        self.assertEqual(heads, ["#", "Hound", "Type", "Record", "Bankroll", "Return", "7d", "24h", "Units", "Bets", "Avg price",
                                 "CLV", "Last 10", "Status"])
        # the default sort is the bankroll, high to low, and the header says so; there is no ROI column any more
        self.assertNotIn("ROI", heads)
        self.assertEqual(out["final"]["aria"][4], "descending")
        self.assertEqual([a for i, a in enumerate(out["final"]["aria"]) if i != 4], [None] + ["none"] * 12)

    def test_rows_default_to_bankroll_high_to_low_and_show_record_money_units_bets_price(self):
        out = self.page(queries=[
            q("ids", self.ROW, "attrs", attr="data-hound"), q("units", f"{self.ROW} [data-hook='row-units']", "texts"),
            q("bank", f"{self.ROW} [data-hook='row-bankroll']", "texts"), q("ret", f"{self.ROW} [data-hook='row-return']", "texts"),
            q("d7", f"{self.ROW} [data-hook='row-d7']", "texts"), q("h24", f"{self.ROW} [data-hook='row-h24']", "texts"),
            q("bets", f"{self.ROW} [data-hook='row-bets']", "texts"),
            q("price", f"{self.ROW} [data-hook='row-price']", "texts"), q("record", f"{self.ROW} [data-hook='row-record']", "texts")])
        f = out["final"]
        want = sorted(self.graded(), key=lambda h: (-h["bankroll"]["current"], -h["record"]["bets"], h["name"]))
        self.assertEqual(f["ids"], [h["id"] for h in want])
        self.assertEqual(f["units"], [f"{h['bankroll']['units_total']:+.2f}" for h in want])
        self.assertEqual(f["bets"], [str(h["record"]["bets"]) for h in want])
        for h, bank, ret in zip(want, f["bank"], f["ret"]):
            self.assertTrue(bank.startswith(f"${h['bankroll']['current']:,.0f}"), bank)
            self.assertEqual(ret, f"{h['bankroll']['return_pct']:+.1f}%")
            # the owner's complaint: units and % must agree. One unit is $10 of the $1,000, so 1u = 1.0%.
            self.assertAlmostEqual(h["bankroll"]["return_pct"], h["bankroll"]["units_total"], delta=0.01)
        for h, w7 in zip(want, f["d7"]):
            self.assertEqual(w7, f"{h['bankroll']['windows']['d7']['return_pct']:+.1f}%")
        for h, price in zip(want, f["price"]):
            self.assertEqual(price, f"{h['form']['avg_price']}")                    # an American price, as the server sent it
        for h, rec in zip(want, f["record"]):
            self.assertTrue(rec.startswith(f"{h['record']['wins']}-{h['record']['losses']}"), rec)

    def test_clicking_a_column_sorts_it_and_clicking_again_reverses_it(self):
        out = self.page(actions=[
            dict(do="click", sel="[data-sort='bets']", label="bets", capture=[
                q("ids", self.ROW, "attrs", attr="data-hound"), q("aria", "[data-hook='leaderboard-table'] thead th", "attrs", attr="aria-sort")]),
            dict(do="click", sel="[data-sort='bets']", label="bets_again", capture=[q("ids", self.ROW, "attrs", attr="data-hound")]),
            dict(do="click", sel="[data-sort='model']", label="model", capture=[q("ids", self.ROW, "attrs", attr="data-hound"),
                                                                                  q("aria", "[data-hook='leaderboard-table'] thead th", "attrs", attr="aria-sort")])])
        by = {h["id"]: h for h in self.graded()}
        desc = out["captures"]["bets"]["ids"]
        bets = [by[i]["record"]["bets"] for i in desc]
        self.assertEqual(bets, sorted(bets, reverse=True))
        self.assertEqual(out["captures"]["bets"]["aria"][9], "descending")
        asc = [by[i]["record"]["bets"] for i in out["captures"]["bets_again"]["ids"]]
        self.assertEqual(asc, sorted(asc))
        names = [by[i]["name"].lower() for i in out["captures"]["model"]["ids"]]
        self.assertEqual(names, sorted(names))                                   # a name sorts A to Z first
        self.assertEqual(out["captures"]["model"]["aria"][1], "ascending")

    def test_models_below_the_rank_bar_are_one_collapsed_group_not_rows_of_0_0(self):
        out = self.page(captureInitial=[
            q("rows", self.ROW, "count"), q("toggle", "[data-hook='warming-toggle']"),
            q("expanded", "[data-hook='warming-toggle']", "attr", attr="aria-expanded"),
            q("warm_rows", ".hd-tr--warm", "count"), q("table", "[data-hook='leaderboard-table']")],
            actions=[dict(do="click", sel="[data-hook='warming-toggle']", label="open", capture=[
                q("warm_rows", ".hd-tr--warm", "count"), q("expanded", "[data-hook='warming-toggle']", "attr", attr="aria-expanded"),
                q("notes", ".hd-warm__note", "texts"), q("names", ".hd-tr--warm .hd-modelname", "texts")])])
        f = out["captures"]["initial"]
        self.assertEqual(f["rows"], len(self.graded()))
        self.assertEqual(f["toggle"], "Warming up (7) ranked at 10 settled bets · 5 open tickets")
        self.assertEqual((f["expanded"], f["warm_rows"]), ("false", 0))
        self.assertNotIn("0-0", f["table"])                                     # never 28 rows of 0-0
        opened = out["captures"]["open"]
        self.assertEqual((opened["expanded"], opened["warm_rows"]), ("true", 7))
        # the most-settled first, then the most open tickets, then by name
        self.assertEqual(opened["names"], ["Home Field", "Blend", "Almanac", "Vibes", "Rusty's Revenge", "Night Owl", "Quiet One"])
        self.assertIn("0 of 10 settled bets · 3 open tickets", opened["notes"])
        self.assertIn("0 of 10 settled bets · 2 open tickets", opened["notes"])
        self.assertIn("0 of 10 settled bets · not started", opened["notes"])
        self.assertTrue(opened["notes"][0].endswith("9 of 10 settled bets"), opened["notes"][0])
        self.assertIn(" so far · 9 of 10", opened["notes"][0])                  # the record so far, not units or ROI
        self.assertNotRegex(" ".join(opened["notes"]), r"%|u")

    def test_every_graded_model_shows_its_last_ten_as_dots_with_a_spoken_label(self):
        out = self.page(queries=[q("dots", f"{self.ROW}[data-hound='closer'] .hd-dot", "count"),
                                 q("label", f"{self.ROW}[data-hound='closer'] [data-hook='last10']", "attr", attr="aria-label"),
                                 q("kinds", f"{self.ROW}[data-hound='closer'] .hd-dot", "attrs", attr="class")])
        want = F.hounds()[0]["form"]["last10"]
        self.assertEqual(out["final"]["dots"], 10)
        self.assertEqual([k.rsplit("--", 1)[1] for k in out["final"]["kinds"]], want)
        self.assertTrue(out["final"]["label"].startswith("Last 10, oldest first: "))

    def test_a_missing_figure_reads_n_a_never_zero(self):
        hs = [mk("x", "X", bets=12, units=2.0)]                        # no form block, no clv: the old payload shape
        out = self.page(routes(**{"/hounds": [200, {"hounds": hs, "as_of": "2026-10-24"}]}), queries=[
            q("price", "[data-hook='row-price']"), q("clv", "[data-hook='clv']"), q("last", "td.hd-col-last10")])
        self.assertEqual((out["final"]["price"], out["final"]["clv"], out["final"]["last"]), ("n/a", "n/a", "n/a"))

    def test_each_status_is_a_plain_word_with_the_sample_size_when_it_is_too_early(self):
        hs = [mk("a", "A", "BEATING THE CLOSE", bets=200, units=9, clv={"n": 160, "mean_pts": 1.2}),
              mk("b", "B", "PAYING THE VIG", bets=300, units=4, clv={"n": 300, "mean_pts": -1.2}),
              mk("c", "C", "NO DIFFERENT FROM THE MARKET", bets=180, units=2, clv={"n": 160, "mean_pts": 0.0}),
              mk("d", "D", "TOO EARLY", bets=40, units=1, clv={"n": 37, "mean_pts": 0.3})]
        out = self.page(routes(**{"/hounds": [200, {"hounds": hs, "as_of": "2026-10-24"}]}),
                        queries=[q("st", "[data-hook='status']", "texts"), q("keys", "[data-hook='status']", "attrs", attr="data-status")])
        self.assertEqual(out["final"]["st"], ["Beating the close", "Paying the vig", "Market", "Verdict at 150 bets (37/150)"])
        self.assertEqual(out["final"]["keys"], ["beating", "vig", "market", "early"])

    def test_clv_shows_the_share_that_beat_the_close_the_average_and_the_sample(self):
        out = self.page(queries=[q("clv", f"{self.ROW}[data-hound='closer'] [data-hook='clv']")])
        h = F.hounds()[0]
        self.assertIn(f"{round(h['form']['clv_beat']['pct'] * 100)}% beat", out["final"]["clv"])
        self.assertIn(f"n={h['clv']['n']}", out["final"]["clv"])
        self.assertRegex(out["final"]["clv"], r"[+-]\d\.\d pts")

    def test_a_retired_model_is_not_in_the_table(self):
        hs = [mk("a", "A", bets=10, units=1), mk("gone", "Gone", bets=90, units=-31, status="retired")]
        out = self.page(routes(**{"/hounds": [200, {"hounds": hs, "as_of": "2026-10-24"}]}),
                        queries=[q("ids", self.ROW, "attrs", attr="data-hound")])
        self.assertEqual(out["final"]["ids"], ["a"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheLeaderboardFilters(unittest.TestCase):
    ROW = "[data-hook='hounds-list'] .hd-tr"

    def test_the_scope_filter_counts_and_narrows(self):
        out = run_page("hounds", routes=routes(), captureInitial=[q("scope", "[data-hook='hounds-filter'] .hd-seg", "texts")],
                       actions=[dict(do="click", sel="[data-filter='user']", label="user", capture=[
                           q("rows", self.ROW, "count"), q("qual", "[data-hook='qualifying-list'] .hd-tr", "attrs", attr="data-hound"),
                           q("empty", "[data-hook='board-empty']", "count")])])
        self.assertEqual(out["captures"]["initial"]["scope"], ["All hounds (15)", "Following (0)", "LINEHOUND kennel (14)", "Members' kennels (1)"])  # owner ruling 2026-10-20 kennel-first
        user = out["captures"]["user"]
        self.assertEqual(user["rows"], 0)
        # fewer than three ranked, so the qualifying round (not the collapsed group) holds the only builder model:
        self.assertEqual(user["qual"], ["rusty"])                                        # it has 3 open tickets and nothing graded

    def test_the_sport_and_type_filters_come_from_the_models_present(self):
        hs = [mk("a", "A", bets=15, units=1), mk("b", "B", bets=16, units=2, sports=["nfl"], category="market")]
        out = run_page("hounds", routes=routes(**{"/hounds": [200, {"hounds": hs, "as_of": "2026-10-24"}]}),
                       captureInitial=[q("sports", "[data-hook='hounds-sports'] .hd-seg", "texts"),
                                q("types", "[data-hook='hounds-categories'] .hd-seg", "texts")],
                       actions=[dict(do="click", sel="[data-sport='nfl']", label="nfl", capture=[q("ids", self.ROW, "attrs", attr="data-hound")]),
                                dict(do="click", sel="[data-category='market']", label="none", capture=[
                                    q("ids", self.ROW, "count"), q("sports", "[data-hook='hounds-sports'] .hd-seg", "texts")])])
        self.assertEqual(out["captures"]["initial"]["sports"], ["All sports", "MLB (1)", "NFL (1)"])
        self.assertEqual(out["captures"]["initial"]["types"], ["All types", "Stats (1)", "Market (1)"])
        self.assertEqual(out["captures"]["nfl"]["ids"], ["b"])

    def test_my_models_shows_only_the_ones_this_browser_follows(self):
        out = run_page("hounds", routes=routes(), stored={FOLLOW_KEY: json.dumps(["closer", "rusty"])},
                       captureInitial=[q("scope", "[data-hook='hounds-filter'] .hd-seg", "texts"),
                                q("tag", f"{self.ROW}[data-hound='closer'] [data-hook='row-follow']")],
                       actions=[dict(do="click", sel="[data-filter='mine']", label="mine", capture=[
                           q("ids", self.ROW, "attrs", attr="data-hound"),
                           q("qual", "[data-hook='qualifying-list'] .hd-tr", "attrs", attr="data-hound")])])
        self.assertEqual(out["captures"]["initial"]["scope"][1], "Following (2)")  # owner ruling 2026-10-20 kennel-first
        self.assertEqual(out["captures"]["initial"]["tag"], "Following")
        self.assertEqual(out["captures"]["mine"]["ids"], ["closer"])
        self.assertEqual(out["captures"]["mine"]["qual"], ["rusty"])           # one ranked: the round lists the other, by its open tickets

    def test_nobody_followed_says_how_to_follow(self):
        out = run_page("hounds", routes=routes(), actions=[dict(do="click", sel="[data-filter='mine']", label="mine", capture=[
            q("empty", "[data-hook='board-empty']"), q("cta", "[data-hook='board-empty'] a", "attr", attr="href")])])
        self.assertIn("You are not following any hounds yet. Open a hound and press Follow.", out["captures"]["mine"]["empty"])  # owner ruling 2026-10-20 kennel-first

    def test_storage_that_throws_leaves_the_leaderboard_working(self):
        for mode in ("methods", "accessor"):
            with self.subTest(mode=mode):
                out = run_page("hounds", routes=routes(), storageThrows=mode, queries=[q("rows", self.ROW, "count")])
                self.assertEqual(out["final"]["rows"], RANKED_N)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheDrawer(unittest.TestCase):
    def test_a_models_row_opens_its_last_ten_tickets_and_a_link_to_its_page(self):
        r = routes(**ticket_routes("closer"))
        out = run_page("hounds", routes=r, actions=[dict(do="click", sel=".hd-tr[data-hound='closer'] [data-hook='expand']", label="open", wait=250, capture=[
            q("rows", ".hd-drawer .hd-ticket", "count"), q("exp", ".hd-tr[data-hound='closer'] [data-hook='expand']", "attr", attr="aria-expanded"),
            q("link", "[data-hook='drawer-link']", "attr", attr="href"), q("title", ".hd-drawer__title"),
            q("status", ".hd-drawer [data-hook='ticket-status']", "texts")]),
            dict(do="click", sel=".hd-tr[data-hound='closer'] [data-hook='expand']", label="close", capture=[q("rows", ".hd-drawer", "count")])])
        opened = out["captures"]["open"]
        self.assertEqual(opened["rows"], 10)
        self.assertEqual(opened["exp"], "true")
        self.assertEqual(opened["link"], "hound.html?id=closer")
        self.assertEqual(opened["title"], "Last 10 tickets")
        self.assertIn("PENDING", opened["status"])                      # the model's newest tickets are still open
        self.assertIn("/hounds/closer/bets?page=1&page_size=10&segment=forward&season=s2", out["gets"])
        self.assertEqual(out["captures"]["close"]["rows"], 0)

    def test_a_failed_drawer_says_so_and_offers_a_retry_and_the_table_stays(self):
        out = run_page("hounds", routes=routes(**{"/hounds/closer/bets": [500, {}]}), actions=[dict(do="click", sel=".hd-tr[data-hound='closer'] [data-hook='expand']", label="open", wait=250, capture=[
            q("state", ".hd-drawer [data-hook='section-state']"), q("rows", "[data-hook='hounds-list'] .hd-tr", "count")])])
        self.assertIn("this hound's tickets", out["captures"]["open"]["state"].lower())  # owner ruling 2026-10-20 kennel-first
        self.assertEqual(out["captures"]["open"]["rows"], RANKED_N)

    def test_clicking_a_row_anywhere_toggles_it_too(self):
        r = routes(**ticket_routes("steamer"))
        out = run_page("hounds", routes=r, actions=[dict(do="click", sel=".hd-tr[data-hound='steamer']", label="row", wait=250, capture=[
            q("drawers", ".hd-drawer", "count")])])
        self.assertEqual(out["captures"]["row"]["drawers"], 1)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheLatestTicketsFeed(unittest.TestCase):
    ITEMS = "[data-hook='stream-list'] .hd-ticket"

    def page(self, r=None, **kw):
        return run_page("hounds", routes=routes() if r is None else r, **kw)

    def test_the_feed_renders_each_bet_as_a_ticket_and_leaves_the_refusal_out(self):
        out = self.page(queries=[
            q("n", self.ITEMS, "count"), q("models", ".hd-ticket__model", "texts"), q("games", ".hd-ticket__game", "texts"),
            q("picks", ".hd-ticket__pick strong", "texts"), q("mkts", ".hd-ticket__mkt", "texts"),
            q("status", "[data-hook='ticket-status']", "texts"), q("units", ".hd-ticket__res .hd-num", "texts"),
            q("price", ".hd-ticket__price", "texts"), q("rec", "[data-hook='ticket-recorded']", "texts"),
            q("links", "a.hd-ticket__model", "attrs", attr="href")])
        f = out["final"]
        self.assertEqual(f["n"], 2)                                              # the fixture's refusal is not a ticket
        self.assertEqual(f["models"], ["Closer", "Coin Flip"])
        self.assertEqual(f["games"], ["Yankees at Red Sox", "Padres at Dodgers"])
        self.assertEqual(f["picks"], ["Yankees to win", "Over 8.5"])
        self.assertEqual(f["mkts"], ["Moneyline", "Total"])
        self.assertEqual(f["status"], ["PENDING", "LOST"])
        self.assertEqual(f["units"], ["-1.00u"])                                 # only a graded ticket moves units
        # the headline price is the average price; the best quote and its book, and the book count, are small print
        self.assertIn("-120", f["price"][0])
        self.assertIn("best -115", f["price"][0])
        self.assertIn("bookB", f["price"][0])
        self.assertIn("5 books", f["price"][0])
        self.assertIn("7 books", f["price"][1])
        self.assertEqual(f["rec"][0], "Oct 24 22:41 UTC, 29m before the start")
        self.assertEqual(f["links"], ["hound.html?id=closer", "hound.html?id=coin-flip"])

    def test_the_feed_is_paged_by_the_server(self):
        items = [json.loads(json.dumps(i)) for i in F.stream()["items"] if not i["refused"]]
        payload = {"items": items, "page": 1, "page_size": 15, "total": 31, "pages": 3, "as_of": F.AS_OF}
        page2 = dict(payload, page=2)
        r = routes(**{"/hounds/stream": [200, payload], "/hounds/stream?page=1&page_size=15": [200, payload],
                      "/hounds/stream?page=2&page_size=15": [200, page2]})
        out = self.page(r, captureInitial=[q("page", "[data-hook='stream-page']"), q("prev", "[data-hook='stream-prev']", "disabled")],
                        actions=[dict(do="click", sel="[data-hook='stream-next']", label="p2", capture=[
                            q("page", "[data-hook='stream-page']"), q("prev", "[data-hook='stream-prev']", "disabled")])])
        self.assertEqual(out["captures"]["initial"]["page"], "Page 1 of 3 (31 tickets)")
        self.assertTrue(out["captures"]["initial"]["prev"])
        self.assertEqual(out["captures"]["p2"]["page"], "Page 2 of 3 (31 tickets)")
        self.assertFalse(out["captures"]["p2"]["prev"])
        self.assertIn("/hounds/stream?page=2&page_size=15", out["gets"])

    def test_the_feed_says_so_when_there_are_no_tickets_and_when_it_is_missing_or_down(self):
        empty = self.page(routes(**{"/hounds/stream": [200, {"items": []}]}), queries=[q("e", "[data-hook='stream-empty']")])
        self.assertIn("No tickets recorded yet", empty["final"]["e"])
        gone = self.page(routes(**{"/hounds/stream": [404, {}]}), queries=[q("s", "[data-hook='hounds-stream'] [data-hook='section-state']", "attrs", attr="data-kind")])
        self.assertEqual(gone["final"]["s"], ["missing"])
        down = self.page(down=["/hounds/stream"], queries=[q("s", "[data-hook='hounds-stream'] [data-hook='section-state']", "attrs", attr="data-kind"),
                                                          q("rows", "[data-hook='hounds-list'] .hd-tr", "count")])
        self.assertEqual(down["final"]["s"], ["down"])
        self.assertEqual(down["final"]["rows"], RANKED_N)                              # the table does not depend on the feed

    def test_one_sixty_second_timer_refreshes_page_one_only(self):
        out = self.page(actions=[dict(do="fire_timers"), dict(do="fire_timers")])
        self.assertEqual(out["intervals"], [60000])
        self.assertEqual(len([g for g in out["gets"] if g.startswith("/hounds/stream")]), 3)

    def test_hidden_stops_it_and_a_hidden_page_arms_no_timer(self):
        out = self.page(actions=[dict(do="visibility", state="hidden"), dict(do="fire_timers"), dict(do="fire_timers"),
                                 dict(do="visibility", state="visible")])
        self.assertEqual(len([g for g in out["gets"] if g.startswith("/hounds/stream")]), 2)
        self.assertEqual(self.page(visibility="hidden")["intervals"], [])

    def test_a_failed_refresh_keeps_the_previous_list_and_says_so(self):
        out = self.page(failAfter={"/hounds/stream": 1}, actions=[dict(do="fire_timers")], queries=[
            q("n", self.ITEMS, "count"), q("stale", "[data-hook='stream-stale']"),
            q("states", "[data-hook='hounds-stream'] [data-hook='section-state']", "count")])
        self.assertEqual(out["final"]["n"], 2)
        self.assertIn("Could not refresh just now; this is the previous list.", out["final"]["stale"])
        self.assertEqual(out["final"]["states"], 0)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheRetiredTable(unittest.TestCase):
    def test_a_retired_model_is_a_row_with_its_final_record_units_reason_and_date(self):
        out = run_page("hounds", routes=routes(), queries=[
            q("names", "[data-hook='grave-list'] .hd-modelname", "texts"),
            q("rec", "[data-hook='grave-list'] tbody tr", "texts"), q("cause", "[data-hook='grave-cause']", "texts"),
            q("heads", "[data-hook='grave-list'] thead th", "texts")])
        self.assertEqual(out["final"]["heads"], ["Hound", "Final record", "Final bankroll", "Reason", "Date"])  # owner ruling 2026-10-20 kennel-first
        self.assertEqual(out["final"]["names"], ["Old Faithful", "Slowpoke"])
        self.assertEqual(out["final"]["cause"], ["Retired by the owner.", "Went more than 25 units under."])
        self.assertIn("205-263 (468 bets)", out["final"]["rec"][1])
        self.assertIn("$638 (-36.2%)", out["final"]["rec"][1])
        self.assertIn("Oct 14", out["final"]["rec"][1])
        # no tombstones, no epitaphs, no R.I.P.
        for word in ("R.I.P.", "Cause of death", "epitaph", "tomb"):
            self.assertNotIn(word.lower(), (out["text"]).lower())

    def test_nobody_retired_says_so(self):
        out = run_page("hounds", routes=routes(**{"/hounds/graveyard": [200, {"hounds": []}]}), queries=[q("e", "[data-hook='grave-empty']")])
        self.assertEqual(out["final"]["e"], "No hound has been retired.")  # owner ruling 2026-10-20 kennel-first


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheDataFreshnessLine(unittest.TestCase):
    def test_the_table_says_what_day_the_data_is_as_of(self):
        out = run_page("hounds", routes=routes(), queries=[q("asof", "[data-hook='data-as-of']")])
        self.assertEqual(out["final"]["asof"], "Data as of Oct 24")

    def test_old_data_wears_a_quiet_amber_updating_note_and_the_numbers_stay(self):
        old = dict(F.leaderboard(), as_of="2026-10-01")
        out = run_page("hounds", routes=routes(**{"/hounds": [200, old]}), queries=[
            q("note", "[data-hook='updating-note']"), q("asof", "[data-hook='data-as-of']"),
            q("rows", "[data-hook='hounds-list'] .hd-tr", "count")])
        self.assertIn("Updating", out["final"]["note"])
        self.assertEqual(out["final"]["asof"], "Data as of Oct 1")
        self.assertEqual(out["final"]["rows"], RANKED_N)

    def test_a_saved_copy_says_updating_and_asks_again(self):
        saved = dict(F.leaderboard(), stale=True, as_of="2026-10-24T20:00:00Z", data_as_of="2026-10-24")
        out = run_page("hounds", routes=routes(**{"/hounds": [200, saved]}), queries=[q("note", "[data-hook='updating-note']")])
        self.assertIn("Updating", out["final"]["note"])
        self.assertTrue(out["intervals"], "a saved copy re-asks on the server's cadence")

    def test_fresh_data_shows_no_note(self):
        out = run_page("hounds", routes=routes(), queries=[q("note", "[data-hook='updating-note']", "count")])
        self.assertEqual(out["final"]["note"], 0)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheLeaderboardIsHonestWhenThereIsNothingOrNothingAnswers(unittest.TestCase):
    def test_empty_state_has_a_message_and_the_build_call_to_action(self):
        r = {"/hounds": [200, {"hounds": [], "paper_only": True}], "/hounds/stream": [200, {"items": []}],
             "/hounds/graveyard": [200, {"hounds": []}]}
        out = run_page("hounds", routes=r, queries=[q("empty", "[data-hook='board-empty']"),
                                                    q("cta", "[data-hook='board-empty'] a", "attr", attr="href")])
        self.assertIn("No hounds are running yet", out["final"]["empty"])
        self.assertEqual(out["final"]["cta"], "quiz.html")  # owner ruling 2026-10-20 kennel-first

    def test_missing_endpoints_say_not_switched_on_in_each_section_and_the_page_still_stands(self):
        out = run_page("hounds", routes={}, queries=[
            q("kinds", "[data-hook='section-state']", "attrs", attr="data-kind"), q("board", "[data-hook='hounds-table']"),
            q("stream", "[data-hook='hounds-stream']"), q("grave", "[data-hook='hounds-graveyard']"),
            q("paper", "[data-hook='footer-legal']"), q("cta", "[data-hook='build-cta']", "attr", attr="href")])
        self.assertEqual(out["final"]["kinds"], ["missing", "missing", "missing"])
        for key in ("board", "stream", "grave"):
            self.assertIn("not switched on yet", out["final"][key], key)
        self.assertIn("Paper bets only, not advice", out["final"]["paper"])      # compliance once, in the footer (owner ruling 2026-10-20 kennel-first)
        self.assertEqual(out["final"]["cta"], "quiz.html")
        self.assertNotIn("0.00", out["text"])                                      # nothing was drawn from nothing

    def test_a_down_server_is_not_reported_as_an_empty_leaderboard_and_offers_a_retry(self):
        out = run_page("hounds", routes=routes(), down=["/hounds", "/hounds/stream", "/hounds/graveyard"], queries=[
            q("kinds", "[data-hook='section-state']", "attrs", attr="data-kind"), q("board", "[data-hook='hounds-table']"),
            q("retry", "[data-hook='hounds-table'] button", "count"), q("empty", "[data-hook='board-empty']", "count")])
        self.assertEqual(out["final"]["kinds"], ["down", "down", "down"])
        self.assertIn("does not mean there is nothing to show", out["final"]["board"])
        self.assertEqual(out["final"]["retry"], 1)
        self.assertEqual(out["final"]["empty"], 0)

    def test_the_first_visit_while_the_server_warms_up_says_so_then_fills_in(self):
        warming = contract_warming()
        out = run_page("hounds", routes=routes(**{"/hounds": [200, warming], "/hounds/stream": [200, dict(warming, items=[])]}),
                       switchAfter={"/hounds": [1, [200, F.leaderboard()]]}, queries=[q("w", "[data-hook='section-state']", "attrs", attr="data-kind")],
                       actions=[dict(do="fire_timers", label="again", capture=[
                           q("rows", "[data-hook='hounds-list'] .hd-tr", "count"), q("w", "[data-hook='hounds-table'] [data-kind='warming']", "count")])])
        self.assertIn("warming", out["final"]["w"])
        self.assertEqual(out["captures"]["again"]["rows"], RANKED_N)
        self.assertEqual(out["captures"]["again"]["w"], 0)


def contract_warming():
    from src.hounds import contract
    return contract.warming_payload({"hounds": []})


# ---------------------------------------------------------------------------------------------------
# both pages: one disclosure, no emoji, no cartoon
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class TheChromeIsProfessional(unittest.TestCase):
    def pages(self):
        r = routes(**ticket_routes("closer"))
        yield "hounds", run_page("hounds", routes=r, stored={FOLLOW_KEY: json.dumps(["closer"])},
                                 actions=[dict(do="click", sel="[data-hook='warming-toggle']"),
                                          dict(do="click", sel=".hd-tr[data-hound='closer'] [data-hook='expand']")])
        yield "hound", run_page("hound", routes=r, search="?id=closer")
        yield "hound-retired", run_page("hound", routes=dict(r, **{"/hounds/closer": [200, dict(F.detail("closer"), status="retired",
                                        retired={"date": "2026-10-20", "cause": "retired: down more than 25 units"})]}), search="?id=closer")

    def test_the_rendered_pages_carry_the_disclosure_once(self):
        for name, out in self.pages():
            with self.subTest(page=name):
                self.assertEqual(len(re.findall(r"(?i)paper bets only", out["text"])), 1, out["text"][:400])
                self.assertEqual(len(re.findall(r"21\+", out["text"])), 1)
                self.assertEqual(len(re.findall(r"Gamble responsibly\.", out["text"])), 1)
                self.assertIn("1-800-GAMBLER", out["text"])

    def test_no_emoji_anywhere_in_what_the_pages_write(self):
        for name, out in self.pages():
            with self.subTest(page=name):
                found = EMOJI.findall(out["text"])
                self.assertEqual(found, [], f"{name}: {found}")
                self.assertEqual(EMOJI.findall(out["title"]), [])

    def test_no_old_cartoon_avatar_and_every_model_is_a_rig_dog_not_an_initials_tile(self):
        for name, out in self.pages():
            with self.subTest(page=name):
                self.assertNotIn("hd-avatar", json.dumps(out["hooks"]))
        # Design system v2 (2026-10-19): the initials tile is replaced by the character rig (web/js/dog-rig.js). The old cartoon
        # class stays gone, no model is drawn twice in a row, and the retired rows wear a (sad) dog too.
        out = run_page("hounds", routes=routes(), queries=[q("svgs", "svg.hd-avatar", "count"), q("mono", ".hd-mono", "texts"),
                                                           q("rowdogs", ".hd-modelcell svg.dk-badge", "count"),
                                                           q("breeds", ".hd-modelcell svg.dk-badge", "attrs", attr="data-breed"),
                                                           q("podium", "[data-hook='podium'] svg.dk-badge", "count"),
                                                           q("ids", ".hd-tr", "attrs", attr="data-hound")])
        self.assertEqual(out["final"]["svgs"], 0)
        self.assertEqual(out["final"]["mono"], [], "no initials tile is left on the leaderboard page")
        self.assertEqual(out["final"]["rowdogs"], RANKED_N + 0 + 2)                     # the table rows plus the two retired rows
        from tests.test_dog_rig import ALL_BREEDS     # the 25 breed drawings of round 2 (2026-10-19)
        self.assertTrue(set(out["final"]["breeds"]) <= set(ALL_BREEDS))
        self.assertLessEqual(out["final"]["podium"], 3)

    def test_the_voice_that_was_pulled_is_not_on_the_pages(self):
        # "graveyard" came back with the owner's 2026-10-20 ruling (a dog taken out back is buried, with a headstone, in a public
        # Graveyard); "put down", "tombstone" and "r.i.p" stay out
        banned = ["houndmaster", "doghouse", "put down", "tombstone", "r.i.p", "good dog", "roast", "brag",
                  "hot dog", "ice cold", "on tilt", "tail it", "fade it", "bark", "woof"]
        for name, out in self.pages():
            lowered = out["text"].lower()
            for word in banned:
                with self.subTest(page=name, word=word):
                    self.assertNotIn(word, lowered)


# ---------------------------------------------------------------------------------------------------
# the model page
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class TheModelPage(unittest.TestCase):
    def page(self, hid="closer", **kw):
        r = routes(**ticket_routes(hid))
        r.update(kw.pop("routes", {}))
        return run_page("hound", routes=r, search=f"?id={hid}", **kw)

    def test_the_header_is_the_model_its_status_type_and_one_italic_line_and_nothing_else_from_the_persona(self):
        out = self.page(queries=[
            q("name", "[data-hook='hound-name']"), q("mono", ".hd-modelhead .hd-mono"), q("dog", ".hd-modelhead svg.dk-badge", "count"),
            q("status", "[data-hook='hound-status']"),
            q("chips", ".hd-chips"), q("catch", "[data-hook='catchphrase']"), q("bio", "[data-hook='bio']", "count"),
            q("order", "h2", "texts"), q("kennel", "[data-hook='hound-kennel']")])
        f = out["final"]
        # the header wears the model's dog (the rig), not an initials tile (design system v2, 2026-10-19)
        self.assertEqual((f["name"], f["mono"], f["dog"]), ("Closer", None, 1))
        self.assertEqual(f["status"], "Beating the close")
        self.assertIn("Stats", f["chips"])
        self.assertIn("MLB", f["chips"])
        self.assertEqual(f["kennel"], "LINEHOUND kennel")                       # whose kennel it lives in (the "House model" chip is gone)
        self.assertEqual(f["catch"], "I was here first.")                       # no quotation marks, no bio, no vibe tag
        self.assertEqual(f["bio"], 0)
        for line in ("Grabs the price before it moves", "Closer roast", "Closer brag", "grabbed the early number"):
            self.assertNotIn(line, out["text"])
        # the kit's panels sit above the tabs (hidden until the server's kit says so): a buried dog's headstone, the owner's
        # hound menu ("Your hound") and "Unleash"; then Overview: numbers, bankroll, status
        self.assertEqual(f["order"][:7], ["Headstone", "Your hound", "Unleash", "Paper bankroll", "Its rule", "Key numbers", "Status"])
        self.assertIn("Open tickets", f["order"])
        self.assertIn("Its rule", f["order"])
        self.assertEqual(out["title"], "Closer — LINEHOUND")

    def test_a_model_with_no_persona_has_no_catchphrase_line(self):
        out = self.page("steamer", queries=[q("catch", "[data-hook='catchphrase']", "count"), q("name", "[data-hook='hound-name']")])
        self.assertEqual(out["final"]["catch"], 0)
        self.assertEqual(out["final"]["name"], "Steamer")

    def test_the_kpi_strip_is_bankroll_return_units_record_drawdown_yield_bets_clv_streak(self):
        out = self.page(queries=[q("slots", "[data-hook='scoreboard-tiles'] .hd-kpi", "attrs", attr="data-slot"),
                                 q("units", ".hd-kpi[data-slot='units']"), q("bank", ".hd-kpi[data-slot='bankroll']"),
                                 q("yield", ".hd-kpi[data-slot='yield']"), q("dd", ".hd-kpi[data-slot='drawdown']"),
                                 q("ret", ".hd-kpi[data-slot='return'] [data-hook='return-big']"),
                                 q("record", ".hd-kpi[data-slot='record']"), q("bets", ".hd-kpi[data-slot='bets']"),
                                 q("clv", ".hd-kpi[data-slot='clv']"), q("streak", ".hd-kpi[data-slot='streak']")])
        f = out["final"]
        h = F.hounds()[0]
        self.assertEqual(f["slots"], ["bankroll", "return", "units", "record", "drawdown", "yield", "bets", "clv", "streak"])
        b = h["bankroll"]
        self.assertRegex(f["units"], r"Units [+-]?\d+\.\d\d 1 unit = \$10")
        self.assertIn(f"${b['current']:,.2f}", f["bank"])
        self.assertIn("from $1,000", f["bank"])
        self.assertEqual(f["ret"], f"{b['return_pct']:+.1f}%")                    # the season tab is the default
        # the yield tile is the old ROI, labelled for what it is
        self.assertIn(f"{b['yield_pct']:+.1f}%", f["yield"])
        self.assertIn("profit per $ bet", f["yield"])
        self.assertIn(f"${b['max_drawdown_usd']:,.2f}", f["dd"])
        self.assertRegex(f["record"], r"Record \d+-\d+-1 wins-losses-pushes")
        self.assertIn("Bets 43 2 open, 41 settled", f["bets"])
        self.assertIn("% beat", f["clv"])
        self.assertIn("measurable bets", f["clv"])
        self.assertRegex(f["streak"], r"Streak [WL]\d (wins|losses) in a row")

    def test_a_model_with_no_graded_bets_shows_n_a_in_the_strip_not_zeroes(self):
        out = run_page("hound", routes=routes(**ticket_routes("night-owl")), search="?id=night-owl", queries=[
            q("units", ".hd-kpi[data-slot='units'] .hd-kpi__big"), q("roi", ".hd-kpi[data-slot='yield'] .hd-kpi__big"),
            q("ret", ".hd-kpi[data-slot='return'] .hd-kpi__big"), q("dd", ".hd-kpi[data-slot='drawdown'] .hd-kpi__big"),
            q("clv", ".hd-kpi[data-slot='clv'] .hd-kpi__big"), q("streak", ".hd-kpi[data-slot='streak'] .hd-kpi__big"),
            q("record", ".hd-kpi[data-slot='record'] .hd-kpi__big")])
        f = out["final"]
        self.assertEqual((f["units"], f["roi"], f["clv"], f["streak"]), ("n/a", "n/a", "n/a", "n/a"))
        self.assertEqual((f["ret"], f["dd"]), ("n/a", "n/a"))
        self.assertEqual(f["record"], "0-0")

    def test_open_and_graded_tickets_are_two_server_filtered_tables(self):
        out = self.page(queries=[
            q("open_rows", "[data-hook='open-table'] tbody tr", "count"), q("open_status", "[data-hook='open-table'] [data-hook='ticket-status']", "texts"),
            q("open_heads", "[data-hook='open-table'] thead th", "texts"),
            q("graded_rows", "[data-hook='bets-table'] tbody tr", "count"), q("graded_heads", "[data-hook='bets-table'] thead th", "texts"),
            q("graded_status", "[data-hook='bets-table'] [data-hook='ticket-status']", "texts"),
            q("why", "[data-hook='bets-table'] [data-hook='bet-why']", "texts"), q("stamp", "[data-hook='bets-table'] [data-hook='bet-stamp']", "texts"),
            q("clv", "[data-hook='ticket-clv']", "texts"), q("units", "[data-hook='bets-table'] [data-hook='ticket-units']", "texts"),
            q("page", "[data-hook='bets-page']")])
        f = out["final"]
        self.assertEqual(f["open_rows"], 2)
        self.assertEqual(f["open_status"], ["PENDING", "PENDING"])
        self.assertEqual(f["open_heads"], ["Date", "Game", "Pick", "Price", "Status", "Rule reason", "Recorded"])
        self.assertEqual(f["graded_rows"], 20)
        self.assertEqual(f["graded_heads"], ["Date", "Game", "Pick", "Price", "CLV pts", "Status", "Units", "Rule reason", "Recorded"])
        self.assertNotIn("PENDING", f["graded_status"])
        self.assertTrue(all(re.fullmatch(r"WON|LOST|PUSH|VOID", s) for s in f["graded_status"]), f["graded_status"])
        self.assertTrue(all(w.startswith("Inside the price band") for w in f["why"]))
        self.assertTrue(all("before the start" in s for s in f["stamp"]), f["stamp"][:2])
        self.assertTrue(all(re.fullmatch(r"[+-]\d\.\d|n/a", c) for c in f["clv"]), f["clv"])
        self.assertTrue(all(re.fullmatch(r"[+-]?\d+\.\d\du|n/a", u) for u in f["units"]), f["units"])
        self.assertEqual(f["page"], "Page 1 of 3 (43 tickets)")
        urls = out["gets"]
        self.assertIn("/hounds/closer/bets?status=open&segment=forward&page=1&page_size=50", urls)
        self.assertIn("/hounds/closer/bets?status=graded&segment=forward&page=1&page_size=20", urls)

    def test_graded_tickets_page_and_the_status_words_come_with_units_that_add_up(self):
        out = self.page(captureInitial=[q("u", "[data-hook='bets-table'] [data-hook='ticket-units']", "texts")],
                        actions=[dict(do="click", sel="[data-hook='bets-next']", label="p2", capture=[
                            q("page", "[data-hook='bets-page']"), q("next", "[data-hook='bets-next']", "disabled"),
                            q("prev", "[data-hook='bets-prev']", "disabled"), q("rows", "[data-hook='bets-table'] tbody tr", "count")])])
        p2 = out["captures"]["p2"]
        self.assertEqual(p2["page"], "Page 2 of 3 (43 tickets)")
        self.assertEqual(p2["rows"], 20)
        self.assertFalse(p2["next"])
        self.assertFalse(p2["prev"])

    def test_the_rehearsal_segment_is_labelled_never_counted_and_has_no_recorded_before_claim(self):
        out = self.page("rusty", forward=False, routes={
            "/hounds/rusty/bets?status=graded&segment=forward&page=1&page_size=20": [200, F.bets_payload("rusty", 45, 1, 20, "forward", "graded")],
            "/hounds/rusty/bets?status=graded&segment=replay&page=1&page_size=20": [200, F.bets_payload("rusty", 45, 1, 20, "replay", "graded")]},
            captureInitial=[q("seg", "[data-hook='bets-segment'] .hd-seg", "texts"), q("empty", "[data-hook='bets-empty']")],
            actions=[dict(do="click", sel="[data-segment='replay']", label="replay", capture=[
                q("rows", "[data-hook='bets-table'] tbody tr", "count"), q("stamp", "[data-hook='bet-stamp']", "texts"),
                q("tags", "[data-hook='bets-table'] tbody tr", "attrs", attr="data-segment")])])
        self.assertEqual(out["captures"]["initial"]["seg"], ["Live", "Rehearsal (not counted)"])
        self.assertIn("No graded tickets yet", out["captures"]["initial"]["empty"])
        replay = out["captures"]["replay"]
        self.assertEqual(set(replay["tags"]), {"replay"})
        self.assertTrue(all("never counted" in s for s in replay["stamp"]))
        self.assertFalse(any("before the start" in s for s in replay["stamp"]))

    def test_a_ticket_with_no_close_or_stamp_says_n_a(self):
        rows = F.bet_rows("closer", 3)
        rows[2].clv_pts = None
        rows[2].recorded_utc = None
        graded = {"items": [json.loads(json.dumps(__import__("src.hounds.contract", fromlist=["x"]).to_json(b))) for b in rows if b.result],
                  "page": 1, "page_size": 20, "total": 1, "pages": 1}
        r = ticket_routes("closer")
        r["/hounds/closer/bets?status=graded&segment=forward&page=1&page_size=20"] = [200, graded]
        out = run_page("hound", routes=routes(**r), search="?id=closer", queries=[
            q("stamp", "[data-hook='bets-table'] [data-hook='bet-stamp']", "texts"), q("clv", "[data-hook='ticket-clv']", "texts")])
        self.assertIn("n/a", out["final"]["stamp"] + out["final"]["clv"])

    def test_no_open_tickets_says_when_the_model_bets(self):
        r = ticket_routes("closer")
        r["/hounds/closer/bets?status=open&segment=forward&page=1&page_size=50"] = [200, {"items": [], "page": 1, "page_size": 50, "total": 0, "pages": 1}]
        out = run_page("hound", routes=routes(**r), search="?id=closer", queries=[q("e", "[data-hook='open-empty']")])
        self.assertIn("No open tickets.", out["final"]["e"])

    def test_open_tickets_refresh_every_minute_while_the_model_runs_and_not_when_retired(self):
        out = self.page(actions=[dict(do="fire_timers")])
        self.assertEqual(out["intervals"], [60000])
        self.assertEqual(len([g for g in out["gets"] if "status=open" in g]), 2)
        d = dict(F.detail("closer"), status="retired", retired={"date": "2026-10-20", "cause": "retired by the owner"})
        gone = self.page(routes={"/hounds/closer": [200, d]})
        self.assertEqual(gone["intervals"], [])

    def test_the_rule_is_the_exact_text_with_a_copy_button(self):
        rule = F.hounds()[0]["rule_text"]
        out = self.page(actions=[dict(do="click", sel="[data-hook='copy-rule']", label="copy", capture=[q("status", "[data-hook='copy-status']")])],
                        queries=[q("rule", "[data-hook='rule-text']"), q("btn", "[data-hook='copy-rule']"),
                                 q("from", "[data-hook='build-from']", "attr", attr="href"), q("tail", "[data-hook='copy-tail']", "count")])
        self.assertEqual(out["final"]["rule"], rule)
        self.assertEqual(out["final"]["btn"], "Copy rule")
        self.assertEqual(out["clipboard"], [rule])
        self.assertEqual(out["captures"]["copy"]["status"], "Copied the rule.")
        self.assertEqual(out["final"]["from"], "build-a-hound.html?from=closer")
        self.assertEqual(out["final"]["tail"], 0)                                # no tail / fade buttons

    def test_a_blocked_clipboard_says_so_and_does_not_claim_it_copied(self):
        out = self.page(clipboardFails=True, actions=[dict(do="click", sel="[data-hook='copy-rule']", label="copy",
                                                           capture=[q("status", "[data-hook='copy-status']")])])
        self.assertIn("Could not copy", out["captures"]["copy"]["status"])
        self.assertEqual(out["clipboard"], [])

    def test_the_status_section_is_the_referees_sentence_in_plain_words_with_the_sample_size_in_the_strip(self):
        out = self.page(queries=[q("badge", "[data-hook='hound-verdict'] [data-hook='badge']"),
                                 q("explain", "[data-hook='badge-explain']"), q("meaning", "[data-hook='verdict-meaning']"),
                                 q("sentence", "[data-hook='verdict-sentence']"), q("facts", "[data-hook='forward-facts']")])
        self.assertEqual(out["final"]["badge"], "Beating the close")
        self.assertIn("not a promise of wins", out["final"]["explain"])
        self.assertIn("not a tip", out["final"]["meaning"])
        self.assertIn("beat the closing market", out["final"]["sentence"])
        self.assertIn("Units, two ways", out["final"]["facts"])
        self.assertIn("This is the referee's all-time verdict. Season 2: 41 graded live bets.", out["text"])

    def test_a_retired_model_shows_its_reason_and_an_idle_one_says_why(self):
        d = F.detail("closer")
        d.update(status="retired", retired={"date": "2026-10-20", "cause": "retired: down more than 25 units"})
        out = self.page(routes={"/hounds/closer": [200, d]}, queries=[q("cause", "[data-hook='hound-cause']"),
                                                                    q("hidden", "[data-hook='hound-cause']", "hidden"),
                                                                    q("status", "[data-hook='hound-status']")])
        self.assertFalse(out["final"]["hidden"])
        self.assertIn("Retired. Went more than 25 units under.", out["final"]["cause"])
        self.assertEqual(out["final"]["status"], "Retired")
        idle = F.detail("blend")
        out = self.page("blend", queries=[q("cause", "[data-hook='hound-cause']")])
        self.assertIn("Idle.", out["final"]["cause"])
        self.assertTrue(idle)
        quiet = self.page(queries=[q("hidden", "[data-hook='hound-cause']", "hidden")])
        self.assertTrue(quiet["final"]["hidden"])

    def test_follow_share_and_download_are_plain_buttons(self):
        out = self.page(queries=[q("btns", "[data-hook='hound-actions'] button", "texts")])
        self.assertEqual(out["final"]["btns"], ["Follow", "Share", "Download card"])

    def test_unknown_model_missing_id_and_down_server(self):
        gone = run_page("hound", routes=routes(), search="?id=nope", queries=[q("t", "[data-hook='hound-header']"),
                                                                              q("v", "[data-hook='hound-verdict-section']", "hidden")])
        self.assertIn("There is no hound with this id", gone["final"]["t"])  # owner ruling 2026-10-20 kennel-first
        self.assertTrue(gone["final"]["v"])
        noid = run_page("hound", routes=routes(), search="", queries=[q("t", "[data-hook='hound-header']")])
        self.assertIn("No hound was chosen", noid["final"]["t"])
        down = run_page("hound", routes=routes(), search="?id=closer", down=["/hounds/closer"], queries=[q("t", "[data-hook='hound-header']")])
        self.assertIn("Could not reach this hound", down["final"]["t"])

    def test_a_failed_ticket_call_says_why_and_the_rest_of_the_page_stays(self):
        r = ticket_routes("closer")
        for key in list(r):
            if "status=graded" in key:
                r.pop(key)
        r["/hounds/closer/bets"] = [404, {}]
        out = run_page("hound", routes=routes(**r), search="?id=closer", queries=[
            q("s", "[data-hook='hound-bets'] [data-hook='section-state']"), q("rule", "[data-hook='rule-text']", "texts"),
            q("open", "[data-hook='open-table'] tbody tr", "count")])
        self.assertIn("not switched on yet", out["final"]["s"])
        self.assertTrue(out["final"]["rule"])
        self.assertEqual(out["final"]["open"], 2)

    def test_the_chart_is_the_bankroll_in_dollars_and_a_clv_panel_each_with_a_zero_line(self):
        out = self.page(queries=[
            q("units_zero", "[data-hook='hound-units-chart'] [data-hook='chart-zero']", "count"),
            q("clv_zero", "[data-hook='hound-clv-chart'] [data-hook='chart-zero']", "count"),
            q("units_lines", "[data-hook='hound-units-chart'] .hd-line", "attrs", attr="data-line"),
            q("clv_lines", "[data-hook='hound-clv-chart'] .hd-line", "attrs", attr="data-line"),
            q("clv_label", "[data-hook='hound-clv-chart'] .hd-chart__svg", "attr", attr="aria-label")])
        self.assertEqual((out["final"]["units_zero"], out["final"]["clv_zero"]), (1, 1))
        self.assertEqual(out["final"]["units_lines"], ["bankroll"])
        self.assertEqual(out["final"]["clv_lines"], ["clv"])
        self.assertIn("closing price", out["final"]["clv_label"])
        self.assertFalse([g for g in out["gets"] if g.startswith("/hounds/series")])

    def test_a_model_with_only_a_rehearsal_draws_nothing_and_says_so(self):
        out = self.page("rusty", forward=False, queries=[q("title", "[data-hook='hound-chart-title']"),
                                                         q("empty", "[data-hook='hound-units-chart'] [data-hook='chart-empty']"),
                                                         q("rep", "[data-hook='replay-line']")], routes={
            "/hounds/rusty/bets?status=open&segment=forward&page=1&page_size=50": [200, {"items": [], "page": 1, "page_size": 50, "total": 0, "pages": 1}],
            "/hounds/rusty/bets?status=graded&segment=forward&page=1&page_size=20": [200, {"items": [], "page": 1, "page_size": 20, "total": 0, "pages": 1}]})
        self.assertIn("No graded live bets yet", out["final"]["title"])
        self.assertIn("A rehearsal result is never drawn here", out["final"]["title"])
        self.assertTrue(out["final"]["rep"].startswith("old-board rehearsal"))

    def test_warming_up_says_so_and_invents_nothing(self):
        warming = contract_warming()
        out = run_page("hound", routes=routes(**{"/hounds/closer": [200, dict(warming, id="closer")]}), search="?id=closer",
                       queries=[q("w", "[data-hook='hound-header'] [data-kind='warming']", "count"),
                                q("kpi", "[data-hook='hound-scoreboard-section']", "hidden")])
        self.assertEqual(out["final"]["w"], 1)
        self.assertTrue(out["final"]["kpi"])


if __name__ == "__main__":
    unittest.main()
