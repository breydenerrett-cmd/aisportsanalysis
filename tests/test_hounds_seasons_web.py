"""Seasons on the web pages, run for real under node (the pages' own scripts against a fake DOM built from their HTML).

Owner decision 2026-10-19: Season 2 is the default view everywhere, Season 1 and All-time are one click away, the
choice is kept in the URL and in localStorage, and a model needs 10 settled bets in the view to be ranked.

What this file holds the pages to:
  LEADERBOARD  the switcher (Season 2 since Oct 18 | Season 1 | All-time), the line under it, the request each
               choice makes, the URL (?season=) beating localStorage beating the default, blocked storage not
               breaking anything, a ranked table that holds only models with 10 settled bets, a "Warming up (N)"
               group that shows the record so far, and NO sort key lifting a warming model above a ranked one;
  MODEL PAGE   the KPI strip's season toggle (re-asks the server, keeps the choice) and the ticket tables' own
               season chip, which defaults to every season;
  LANDING      Season 2's top five RANKED models; with fewer than five, the ones that qualified plus a line saying
               how young the season is and that more hounds qualify at 10 bets;
  PURE HELPERS the ranking bar, the labels, the age line.
"""

# Copy updated per owner ruling 2026-10-20, complete-product positioning (no beta / early-access / paused hedging; invite wording).
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from datetime import datetime, timezone

from src.hounds import bankroll as bk, seasons
from tests import hounds_web_fixtures as F
from tests.hounds_web_runner import HAS_NODE, run_js, run_page

STORE_KEY = "linehound.hounds.season"


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


def money(bets, units, wins):
    """The bankroll block the real code would work out for these figures: ``units`` spread evenly over ``bets`` settled
    bets (all long ago, so no 24h / 7d window holds any), results in the win / loss counts."""
    when = datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc)
    each = units / bets if bets else 0.0
    evts = [bk.Event(settle=when, units=each, flat=each, stake=1.0, result="win" if k < wins else "loss",
                     order=("2026-10-01", f"{k:04d}")) for k in range(bets)]
    return bk.block(evts, datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc), "average_price")


def mk(hid, name, bets=12, units=0.0, wins=None, **extra):
    wins = bets // 2 if wins is None else wins
    h = {"id": hid, "name": name, "kind": "house", "category": "stats", "style": "x", "status": "running", "tagline": "t",
         "sports": ["mlb"], "markets": ["h2h"],
         "verdict": {"label": "TOO EARLY", "sentence": "s", "n": 3},
         "record": {"bets": bets, "wins": wins, "losses": bets - wins, "pushes": 0, "voids": 0,
                    "units_recorded_price": units, "units_average_price": units},
         "bankroll": money(bets, units, wins),
         "clv": None, "spark": [0, units], "verified": True, "open_bets": 0,
         "form": {"last10": ["W" if i < wins else "L" for i in range(min(bets, 10))], "avg_price": 105,
                  "streak": {"kind": "W", "length": 1}}}
    h.update(extra)
    return h


def board(hounds, season="s2"):
    return [200, {"hounds": hounds, "as_of": "2026-10-24", "season": seasons.meta(season), "paper_only": True}]


def routes(**over):
    r = {k: list(v) for k, v in F.routes().items()}
    r["/hounds/series"] = [200, F.series([h["id"] for h in F.hounds()], True)]
    r.update(over)
    return r


KEY = lambda season: f"/hounds?season={season}"          # noqa: E731 -- a route keyed by the FULL url answers one season


# ---------------------------------------------------------------------------------------------------
# the pure helpers
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class ThePureHelpers(unittest.TestCase):
    def js(self, body):
        return run_js('import * as S from "./hounds-season.js";\nimport * as B from "./hounds-board.js";\n' + body)

    def test_ten_settled_bets_rank_a_model_and_the_pushes_count_but_voids_do_not(self):
        rec = lambda w, l, p=0, v=0: {"record": {"bets": w + l + p + v, "wins": w, "losses": l, "pushes": p, "voids": v}}  # noqa: E731
        cases = [rec(5, 4), rec(5, 5), rec(5, 4, 1), rec(5, 4, 0, 3), rec(1, 0), {}]
        out = self.js(f"console.log(JSON.stringify({json.dumps(cases)}.map(h => [B.settledOf(h), B.isRanked(h)])));")
        self.assertEqual(out, [[9, False], [10, True], [10, True], [9, False], [1, False], [0, False]])

    def test_the_bar_can_be_moved_by_the_payload_not_only_by_the_default(self):
        out = self.js('const h = {record: {bets: 6, wins: 3, losses: 3}};'
                      'console.log(JSON.stringify([B.isRanked(h), B.isRanked(h, 5), S.minRanked({min_ranked_bets: 5}), S.minRanked(null)]));')
        self.assertEqual(out, [False, True, 5, 10])

    def test_ranked_models_are_the_table_and_the_rest_wait_most_settled_first(self):
        hs = [mk("a", "A", bets=12), mk("w1", "W One", bets=3), mk("w2", "W Two", bets=9), mk("w3", "W Three", bets=9)]
        out = self.js(f"const r = B.splitRanked({json.dumps(hs)}); console.log(JSON.stringify([r.active.map(h => h.id), r.warming.map(h => h.id)]));")
        self.assertEqual(out, [["a"], ["w3", "w2", "w1"]])        # 9 settled twice: by name (Three before Two)

    def test_the_qualifying_round_orders_by_units_then_record_and_leaves_out_empty_models(self):
        hs = [mk("b", "B", bets=4, units=1.0, wins=3), mk("a", "A", bets=2, units=1.0, wins=2), mk("t", "T", bets=6, units=2.5, wins=4),
              mk("n", "N", bets=0, units=0.0, wins=0), mk("o", "O", bets=0, units=0.0, wins=0, open_bets=2)]
        out = self.js(f"console.log(JSON.stringify(B.qualifyingRows({json.dumps(hs)}).map(h => h.id)));")
        self.assertEqual(out, ["t", "a", "b", "o"])

    def test_progress_text_is_settled_over_the_bar_and_never_past_it(self):
        out = self.js("const m = (w, l) => ({record: {bets: w + l, wins: w, losses: l}});"
                      "console.log(JSON.stringify([B.progressText(m(2, 1)), B.progressText(m(0, 0)), B.progressText(m(8, 4)), B.progressText(m(2, 1), 5)]));")
        self.assertEqual(out, ["3/10 bets", "0/10 bets", "10/10 bets", "3/5 bets"])

    def test_the_round_starts_below_three_ranked(self):
        out = self.js("console.log(JSON.stringify([0, 1, 2, 3, 4].map(n => B.inQualifyingRound(n))));")
        self.assertEqual(out, [True, True, True, False, False])

    def test_the_switcher_labels(self):
        out = self.js("console.log(JSON.stringify([S.seasonOptions(null).map(o => o.text), S.seasonOptions(null).map(o => o.id)]));")
        self.assertEqual(out, [["Season 2 (since Oct 18)", "Season 1", "All-time"], ["s2", "s1", "all"]])

    def test_the_line_under_the_switcher(self):
        out = self.js("console.log(JSON.stringify(['s2', 's1', 'all'].map(id => S.seasonLine(null, id))));")
        self.assertEqual(out[0], "Season 2 started Oct 18. Every model starts at zero.")
        self.assertEqual(out[1], "Season 1 ran Aug 31 to Oct 17. Models are measured on that window only.")
        self.assertTrue(out[2].startswith("All-time: every forward bet since Aug 31."), out[2])

    def test_the_season_age_line_counts_the_start_day_as_day_one(self):
        meta = json.dumps(seasons.meta("s2"))
        out = self.js(f"const m = {meta}; console.log(JSON.stringify([S.seasonAgeText(m, '2026-10-18'), S.seasonAgeText(m, '2026-10-19'), "
                      f"S.seasonAgeText(m, '2026-11-01'), S.seasonAgeText(m, '2026-10-17'), S.seasonAgeText({json.dumps(seasons.meta('all'))}, '2026-10-19')]));")
        self.assertEqual(out, ["Season 2 is 1 day old", "Season 2 is 2 days old", "Season 2 is 15 days old", "", ""])

    def test_pacific_today_is_a_calendar_date(self):
        out = self.js("console.log(JSON.stringify([S.pacificToday(new Date('2026-10-19T03:30:00Z')), S.pacificToday(new Date('2026-10-19T20:00:00Z'))]));")
        self.assertEqual(out, ["2026-10-18", "2026-10-19"])        # 03:30 UTC is still the evening of the 18th on the west coast

    def test_nothing_chosen_in_node_means_the_default(self):
        self.assertEqual(self.js("console.log(JSON.stringify(S.chooseSeason(null)));"), "s2")


# ---------------------------------------------------------------------------------------------------
# the leaderboard
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class TheSwitcherOnTheLeaderboard(unittest.TestCase):
    BAR = "[data-hook='hounds-season'] .hd-seg"

    def page(self, **kw):
        kw.setdefault("routes", routes())
        return run_page("hounds", **kw)

    def test_season_2_is_the_default_and_the_three_choices_are_there(self):
        out = self.page(queries=[q("texts", self.BAR, "texts"), q("pressed", self.BAR, "attrs", attr="aria-pressed"),
                                 q("line", "[data-hook='season-line']")])
        self.assertEqual(out["gets"][0], "/hounds?season=s2")
        self.assertEqual(out["final"]["texts"], ["Season 2 (since Oct 18)", "Season 1", "All-time"])
        self.assertEqual(out["final"]["pressed"], ["true", "false", "false"])
        self.assertEqual(out["final"]["line"], "Season 2 started Oct 18. Every model starts at zero.")
        self.assertEqual(out["replaced"], [])                     # opening the page writes nothing: only a pick is remembered
        self.assertEqual(out["storedAfter"], {})

    def test_the_url_beats_the_remembered_choice_which_beats_the_default(self):
        cases = [("?season=s1", {}, "s1"), ("?season=all", {}, "all"), ("", {STORE_KEY: "s1"}, "s1"),
                 ("?season=all", {STORE_KEY: "s1"}, "all"), ("?season=zzz", {STORE_KEY: "s1"}, "s1"),
                 ("?season=zzz", {STORE_KEY: "also-bad"}, "s2"), ("", {}, "s2")]
        for search, stored, want in cases:
            with self.subTest(search=search, stored=stored):
                out = self.page(search=search, stored=stored, routes=routes(**{KEY(want): board([mk("a", "A")], want)}))
                self.assertEqual(out["gets"][0], f"/hounds?season={want}")

    def test_picking_a_season_asks_the_server_and_is_kept_in_the_url_and_in_storage(self):
        r = routes(**{KEY("s1"): board([mk("old", "Old Timer", bets=110, units=12.0)], "s1")})
        out = self.page(routes=r, search="?utm=x", actions=[
            dict(do="click", sel="[data-season='s1']", label="s1", wait=120, capture=[
                q("ids", "[data-hook='hounds-list'] .hd-tr", "attrs", attr="data-hound"), q("pressed", self.BAR, "attrs", attr="aria-pressed"),
                q("line", "[data-hook='season-line']")])])
        self.assertIn("/hounds?season=s1", out["gets"])
        cap = out["captures"]["s1"]
        self.assertEqual(cap["ids"], ["old"])
        self.assertEqual(cap["pressed"], ["false", "true", "false"])
        self.assertEqual(cap["line"], "Season 1 ran Aug 31 to Oct 17. Models are measured on that window only.")
        self.assertEqual(out["storedAfter"][STORE_KEY], "s1")
        self.assertEqual(out["replaced"], ["/web/x.html?utm=x&season=s1"])        # the rest of the query is kept

    def test_all_time_and_back(self):
        r = routes(**{KEY("all"): board([mk("vet", "Veteran", bets=400, units=30.0)], "all")})
        out = self.page(routes=r, actions=[
            dict(do="click", sel="[data-season='all']", label="all", wait=120, capture=[q("ids", "[data-hook='hounds-list'] .hd-tr", "attrs", attr="data-hound"),
                                                                                    q("line", "[data-hook='season-line']")]),
            dict(do="click", sel="[data-season='s2']", label="s2", wait=120, capture=[q("n", "[data-hook='hounds-list'] .hd-tr", "count")])])
        self.assertEqual(out["captures"]["all"]["ids"], ["vet"])
        self.assertTrue(out["captures"]["all"]["line"].startswith("All-time:"))
        self.assertGreater(out["captures"]["s2"]["n"], 1)
        self.assertEqual(out["storedAfter"][STORE_KEY], "s2")
        self.assertEqual(out["replaced"], ["/web/x.html?season=all", "/web/x.html?season=s2"])

    def test_blocked_storage_leaves_the_switcher_working(self):
        for mode in ("methods", "accessor"):
            with self.subTest(mode=mode):
                r = routes(**{KEY("s1"): board([mk("old", "Old Timer")], "s1")})
                out = self.page(routes=r, storageThrows=mode, actions=[
                    dict(do="click", sel="[data-season='s1']", label="s1", wait=120, capture=[q("ids", "[data-hook='hounds-list'] .hd-tr", "attrs", attr="data-hound")])])
                self.assertEqual(out["captures"]["s1"]["ids"], ["old"])
                self.assertEqual(out["replaced"], ["/web/x.html?season=s1"])        # the URL still carries the choice

    def test_a_late_answer_for_a_season_no_longer_shown_is_dropped(self):
        r = routes(**{KEY("s1"): board([mk("old", "Old Timer")], "s1"), KEY("all"): board([mk("vet", "Veteran")], "all")})
        out = self.page(routes=r, actions=[dict(do="click", sel="[data-season='s1']", label="a", wait=0),
                                           dict(do="click", sel="[data-season='all']", label="b", wait=150, capture=[
                                               q("ids", "[data-hook='hounds-list'] .hd-tr", "attrs", attr="data-hound")])])
        self.assertEqual(out["captures"]["b"]["ids"], ["vet"])

    def test_the_status_column_says_it_is_all_time(self):
        out = self.page(queries=[q("head", "th.hd-col-status", "attr", attr="title"), q("tip", "[data-hook='status']", "attr", attr="title")])
        self.assertIn("All-time", out["final"]["head"])
        self.assertIn("all-time verdict", out["final"]["tip"])

    def test_the_status_count_under_too_early_is_the_all_time_one_not_the_seasons(self):
        hs = [mk("a", "A", bets=12, clv={"n": 2, "mean_pts": 0.3}, verdict={"label": "TOO EARLY", "sentence": "s", "n": 93})]
        out = self.page(routes=routes(**{"/hounds": board(hs)}), queries=[q("st", "[data-hook='status']")])
        self.assertEqual(out["final"]["st"], "Verdict at 150 bets (93/150)")

    def test_the_drawer_asks_for_the_tickets_of_the_season_on_screen(self):
        r = routes(**{"/hounds": board([mk("a", "A")])})
        out = self.page(routes=r, actions=[dict(do="click", sel=".hd-tr[data-hound='a'] [data-hook='expand']", wait=150)])
        self.assertIn("/hounds/a/bets?page=1&page_size=10&segment=forward&season=s2", out["gets"])
        r = routes(**{"/hounds": board([mk("a", "A")], "all")})
        out = self.page(routes=r, search="?season=all", actions=[dict(do="click", sel=".hd-tr[data-hound='a'] [data-hook='expand']", wait=150)])
        self.assertIn("/hounds/a/bets?page=1&page_size=10&segment=forward", out["gets"])      # all-time: no season filter


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheRankedTableAndTheWarmingGroup(unittest.TestCase):
    """From three ranked models on: the ranked table leads and the rest wait in the collapsed "Warming up (N)" group."""
    ROW = "[data-hook='hounds-list'] .hd-tr"

    def hot_start_world(self):
        """A 1-0 model with +94% ROI, a perfect last ten and the most units per bet, beside three real samples."""
        return routes(**{"/hounds": board([
            mk("steady", "Steady", bets=40, units=3.0, wins=22),
            mk("slump", "Slump", bets=25, units=-4.0, wins=10),
            mk("middle", "Middle", bets=15, units=0.5, wins=8),
            mk("hotstart", "Hot Start", bets=1, units=0.94, wins=1, open_bets=2),
            mk("nine", "Nine Bets", bets=9, units=6.0, wins=7)])})

    def test_a_one_and_oh_model_is_not_ranked_however_good_it_looks(self):
        out = run_page("hounds", routes=self.hot_start_world(), captureInitial=[
            q("ids", self.ROW, "attrs", attr="data-hound"), q("ranks", f"{self.ROW} .hd-col-rank", "texts"),
            q("warm", "[data-hook='warming-toggle']"), q("count", "[data-hook='hounds-count']"),
            q("qual", "[data-hook='qualifying']", "count")])
        f = out["captures"]["initial"]
        self.assertEqual(f["ids"], ["steady", "middle", "slump"])
        self.assertEqual(f["ranks"], ["1", "2", "3"])
        self.assertTrue(f["warm"].startswith("Warming up (2)"), f["warm"])
        self.assertEqual(f["count"], "5 models, 3 ranked")
        self.assertEqual(f["qual"], 0)                                    # three ranked: no qualifying round

    def test_the_warming_group_shows_the_record_so_far_how_far_from_a_rank_and_open_tickets_but_no_roi(self):
        out = run_page("hounds", routes=self.hot_start_world(), actions=[
            dict(do="click", sel="[data-hook='warming-toggle']", label="open", capture=[
                q("names", ".hd-tr--warm .hd-modelname", "texts"), q("notes", ".hd-warm__note", "texts"), q("rows", ".hd-tr--warm", "text")])])
        cap = out["captures"]["open"]
        self.assertEqual(cap["names"], ["Nine Bets", "Hot Start"])
        self.assertEqual(cap["notes"][0], "7-2 so far \u00b7 9 of 10 settled bets")
        self.assertEqual(cap["notes"][1], "1-0 so far \u00b7 1 of 10 settled bets \u00b7 2 open tickets")
        self.assertNotIn("%", cap["rows"])                                # no return for a model that has not earned a rank
        self.assertNotIn("+94", cap["rows"])

    def test_no_sort_key_lifts_a_warming_model_above_a_ranked_one(self):
        keys = ["model", "type", "record", "bankroll", "return", "d7", "h24", "units", "bets", "price", "clv", "last10", "status"]
        actions = []
        for key in keys + keys:                                           # twice: descending, then ascending
            actions.append(dict(do="click", sel=f"[data-sort='{key}']", label=f"{key}{len(actions)}",
                                capture=[q("ids", self.ROW, "attrs", attr="data-hound"), q("ranks", f"{self.ROW} .hd-col-rank", "texts")]))
        out = run_page("hounds", routes=self.hot_start_world(), actions=actions)
        self.assertEqual(len(out["captures"]), 26)
        for label, cap in out["captures"].items():
            with self.subTest(sort=label):
                self.assertEqual(sorted(cap["ids"]), ["middle", "slump", "steady"])   # only the ranked three are ever a row
                self.assertEqual(cap["ranks"], ["1", "2", "3"])

    def test_no_sort_key_lifts_a_qualifying_model_either(self):
        keys = ["model", "record", "bankroll", "return", "units", "bets", "last10"]
        actions = [dict(do="click", sel=f"[data-sort='{k}']", label=f"{k}{i}", capture=[q("ids", self.ROW, "attrs", attr="data-hound")])
                   for i, k in enumerate(keys + keys)]
        out = run_page("hounds", routes=QualifyingBase.two_ranked_world(), actions=actions)
        for label, cap in out["captures"].items():
            with self.subTest(sort=label):
                self.assertEqual(sorted(cap["ids"]), ["r1", "r2"])

    def test_the_default_order_is_units_high_to_low_among_the_ranked(self):
        out = run_page("hounds", routes=routes(**{"/hounds": board([
            mk("c", "C", bets=30, units=-2.0), mk("a", "A", bets=15, units=5.0), mk("b", "B", bets=20, units=1.5),
            mk("z", "Z", bets=2, units=9.0)])}), queries=[q("ids", self.ROW, "attrs", attr="data-hound")])
        self.assertEqual(out["final"]["ids"], ["a", "b", "c"])


class QualifyingBase:
    """Worlds for the qualifying round (fewer than three ranked models)."""

    @staticmethod
    def world(hounds):
        return routes(**{"/hounds": board(hounds)})

    @staticmethod
    def zero_ranked_world():
        return QualifyingBase.world([
            mk("tie_b", "Tie B", bets=4, units=1.0, wins=3),                  # same units as Tie A, worse record
            mk("tie_a", "Tie A", bets=2, units=1.0, wins=2),                  # ... better record: first of the two
            mk("top", "Top Dog", bets=6, units=2.5, wins=4),
            mk("down", "Down", bets=9, units=-3.0, wins=3),
            mk("open_only", "Open Only", bets=0, units=0.0, wins=0, open_bets=3),
            mk("quiet1", "Quiet One", bets=0, units=0.0, wins=0),
            mk("quiet2", "Quiet Two", bets=0, units=0.0, wins=0)])

    @staticmethod
    def two_ranked_world():
        return QualifyingBase.world([
            mk("r1", "Ranked One", bets=30, units=4.0, wins=17), mk("r2", "Ranked Two", bets=12, units=-1.0, wins=5),
            mk("q1", "Qual One", bets=8, units=5.0, wins=6), mk("q2", "Qual Two", bets=1, units=0.94, wins=1)])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheQualifyingRound(unittest.TestCase):
    """Fewer than three ranked models in the season: the models short of the bar are NOT hidden in a collapsed group
    (a day-two board would look dead). They lead, expanded, as the qualifying round, with progress pills."""
    QROW = "[data-hook='qualifying-list'] .hd-tr"
    ROW = "[data-hook='hounds-list'] .hd-tr"

    def page(self, r, **kw):
        return run_page("hounds", routes=r, **kw)

    def test_with_nobody_ranked_the_qualifying_round_leads_expanded_with_its_heading(self):
        out = self.page(QualifyingBase.zero_ranked_world(), queries=[
            q("title", "[data-hook='qualifying-title']"), q("qrows", self.QROW, "count"), q("ranked_rows", self.ROW, "count"),
            q("toggle", "[data-hook='warming-toggle']", "count"), q("warm_rows", ".hd-tr--warm", "count"),
            q("ranked_title", "[data-hook='ranked-title']", "count"), q("none", "[data-hook='no-graded']"),
            q("ranked_table", "[data-hook='leaderboard-table']", "count"), q("count", "[data-hook='hounds-count']")])
        f = out["final"]
        self.assertEqual(f["title"], "Season 2 qualifying: a model needs 10 settled bets to be ranked")
        self.assertEqual(f["qrows"], 5)                                   # everyone with a settled bet or an open ticket
        self.assertEqual((f["ranked_rows"], f["toggle"], f["warm_rows"]), (0, 0, 0))    # no collapsed group in this state
        # round 2 (2026-10-19): an empty "Ranked (0)" table under the round said nothing twice, so it is not drawn; the one line stays
        self.assertEqual((f["ranked_title"], f["ranked_table"]), (0, 0))
        self.assertEqual(f["none"], "No model has 10 settled bets in this view yet, so none is ranked. The qualifying round above shows who is closest.")
        self.assertEqual(f["count"], "7 models, 0 ranked")
        hooks = out["hooks"]
        self.assertNotIn("leaderboard-table", hooks)                                      # and there is no ranked table below it

    def test_the_round_has_the_same_columns_sorted_by_units_then_record(self):
        out = self.page(QualifyingBase.zero_ranked_world(), queries=[
            q("ids", self.QROW, "attrs", attr="data-hound"), q("units", f"{self.QROW} [data-hook='row-units']", "texts"),
            q("ranks", f"{self.QROW} .hd-col-rank", "texts"),
            q("heads", "[data-hook='qualifying-table'] thead th", "texts"),
            q("ranked_heads", "[data-hook='leaderboard-table'] thead th", "texts")])
        f = out["final"]
        self.assertEqual(f["ids"][:3], ["top", "tie_a", "tie_b"])        # 2.5 units, then the 1.0-unit tie broken by record
        self.assertEqual(f["ids"][3:], ["down", "open_only"])            # a loss-making model before one with no settled bet
        self.assertEqual(f["units"][:3], ["+2.50", "+1.00", "+1.00"])
        self.assertEqual(set(f["ranks"]), {"-"})                         # nothing here is numbered
        strip = lambda ts: [t.replace(" ▼", "").replace(" ▲", "") for t in ts]  # noqa: E731
        # round 2 (2026-10-19): with nobody ranked there is no empty "Ranked (0)" table to compare with; the round has every column
        self.assertEqual(f["ranked_heads"], [])
        self.assertEqual(strip(f["heads"])[:5], ["#", "Model", "Type", "Record", "Bankroll"])
        self.assertEqual(len(f["heads"]), 14)

    def test_each_row_has_a_progress_pill_in_the_status_column_and_greyed_money(self):
        out = self.page(QualifyingBase.zero_ranked_world(), queries=[
            q("pills", f"{self.QROW} [data-hook='progress']", "texts"),
            q("in_status", f"{self.QROW} td.hd-col-status [data-hook='progress']", "count"),
            q("roi_titles", f"{self.QROW} [data-hook='row-return']", "attrs", attr="title"),
            q("roi_class", f"{self.QROW} [data-hook='row-return']", "attrs", attr="class"),
            q("pill_title", f"{self.QROW} [data-hook='progress']", "attrs", attr="title")])
        f = out["final"]
        self.assertEqual(f["pills"], ["6/10 bets", "2/10 bets", "4/10 bets", "9/10 bets", "0/10 bets"])
        self.assertEqual(f["in_status"], 5)
        self.assertTrue(all(t.startswith("Ranked in full at") for t in f["roi_titles"]), f["roi_titles"])
        self.assertTrue(all("hd-roi--small" in c for c in f["roi_class"]), f["roi_class"])
        self.assertTrue(all(t.startswith("Needs 10 settled bets to be ranked") for t in f["pill_title"]))

    def test_models_with_nothing_yet_are_one_line_not_rows(self):
        out = self.page(QualifyingBase.zero_ranked_world(), queries=[q("rest", "[data-hook='qualifying-rest']")])
        self.assertEqual(out["final"]["rest"], "2 more models have no settled bet yet.")

    def test_two_ranked_is_still_the_round_with_the_two_in_the_ranked_table_below(self):
        out = self.page(QualifyingBase.two_ranked_world(), queries=[
            q("qids", self.QROW, "attrs", attr="data-hound"), q("rids", self.ROW, "attrs", attr="data-hound"),
            q("ranks", f"{self.ROW} .hd-col-rank", "texts"), q("toggle", "[data-hook='warming-toggle']", "count"),
            q("ranked_title", "[data-hook='ranked-title']")])
        f = out["final"]
        self.assertEqual(f["qids"], ["q1", "q2"])
        self.assertEqual(f["rids"], ["r1", "r2"])
        self.assertEqual(f["ranks"], ["1", "2"])
        self.assertEqual((f["toggle"], f["ranked_title"]), (0, "Ranked (2)"))

    def test_three_ranked_reverts_to_the_ranked_table_first_and_a_collapsed_group(self):
        world = QualifyingBase.world([mk("r1", "R1", bets=30, units=4.0, wins=17), mk("r2", "R2", bets=12, units=-1.0, wins=5),
                                      mk("r3", "R3", bets=10, units=0.5, wins=5), mk("q1", "Q1", bets=8, units=5.0, wins=6)])
        out = self.page(world, queries=[
            q("qual", "[data-hook='qualifying']", "count"), q("rids", self.ROW, "attrs", attr="data-hound"),
            q("toggle", "[data-hook='warming-toggle']"), q("expanded", "[data-hook='warming-toggle']", "attr", attr="aria-expanded"),
            q("warm_rows", ".hd-tr--warm", "count"), q("pills", "[data-hook='progress']", "count")])
        f = out["final"]
        self.assertEqual(f["qual"], 0)
        self.assertEqual(f["rids"], ["r1", "r3", "r2"])
        self.assertTrue(f["toggle"].startswith("Warming up (1)"), f["toggle"])
        self.assertEqual((f["expanded"], f["warm_rows"], f["pills"]), ("false", 0, 0))

    def test_a_model_that_reaches_ten_leaves_the_round_for_the_table(self):
        nine = QualifyingBase.world([mk("a", "A", bets=9, units=2.0, wins=6)])
        ten = QualifyingBase.world([mk("a", "A", bets=10, units=2.0, wins=6)])
        self.assertEqual(self.page(nine, queries=[q("n", self.QROW, "count"), q("r", self.ROW, "count")])["final"], {"n": 1, "r": 0})
        self.assertEqual(self.page(ten, queries=[q("n", self.QROW, "count"), q("r", self.ROW, "count")])["final"], {"n": 0, "r": 1})

    def test_the_round_names_the_season_it_is_showing(self):
        r = routes(**{KEY("s1"): board([mk("a", "A", bets=4, units=1.0, wins=3)], "s1")})
        out = self.page(r, search="?season=s1", queries=[q("title", "[data-hook='qualifying-title']")])
        self.assertEqual(out["final"]["title"], "Season 1 qualifying: a model needs 10 settled bets to be ranked")

    def test_no_model_has_anything_at_all_says_so_without_an_empty_round(self):
        out = self.page(QualifyingBase.world([mk("a", "A", bets=0, units=0.0, wins=0)]), queries=[
            q("rows", self.QROW, "count"), q("rest", "[data-hook='qualifying-rest']"), q("none", "[data-hook='no-graded']")])
        self.assertEqual(out["final"]["rows"], 0)
        self.assertEqual(out["final"]["rest"], "1 more model has no settled bet yet.")


@unittest.skipUnless(HAS_NODE, "node not installed")
class MemberDogsAreAlwaysListed(unittest.TestCase):
    """2026-10-19: a member's two dogs (0 settled bets, no open ticket) could not be found, because the qualifying round
    left out every model with nothing yet ("2 more models have no settled bet yet"). A dog a member built is ALWAYS
    listed: in the qualifying round (flagged New), under Builders', and in the Builders' count."""
    QROW = "[data-hook='qualifying-list'] .hd-tr"

    @staticmethod
    def world(extra=()):
        member = lambda hid, name: mk(hid, name, bets=0, units=0.0, wins=0, kind="user", owner_display="Handler 21E8")  # noqa: E731
        return QualifyingBase.world([
            mk("top", "Top Dog", bets=6, units=2.5, wins=4),
            member("u-d151fe52c7", "Jsmooth"), member("u-fcc8e8c168", "Jsmooth27"),
            mk("quiet", "Quiet House", bets=0, units=0.0, wins=0)] + list(extra))

    def test_a_zero_bet_member_dog_leads_nowhere_but_is_a_row_with_a_new_pill(self):
        out = run_page("hounds", routes=self.world(), queries=[
            q("ids", self.QROW, "attrs", attr="data-hound"),
            q("pills", f"{self.QROW} [data-hook='progress']", "texts"),
            q("rest", "[data-hook='qualifying-rest']")])
        f = out["final"]
        self.assertEqual(f["ids"], ["top", "u-d151fe52c7", "u-fcc8e8c168"])      # the two member dogs are rows, after the one with a bet
        self.assertEqual(f["pills"], ["6/10 bets", "New: no bets yet", "New: no bets yet"])
        self.assertEqual(f["rest"], "1 more model has no settled bet yet.")           # only the HOUSE model is counted in the line

    def test_the_builders_count_is_the_number_of_member_dogs_the_page_shows(self):
        out = run_page("hounds", routes=self.world(), actions=[
            dict(do="click", sel="[data-filter='user']", label="builders", capture=[
                q("ids", f"{self.QROW}", "attrs", attr="data-hound"), q("count", "[data-hook='hounds-count']")])],
            queries=[q("filters", "[data-hook='hounds-filter'] .hd-seg", "texts")])
        self.assertIn("Builders' (2)", out["final"]["filters"])
        cap = out["captures"]["builders"]
        self.assertEqual(cap["ids"], ["u-d151fe52c7", "u-fcc8e8c168"])
        self.assertEqual(cap["count"], "2 models, 0 ranked")

    def test_a_member_dog_links_to_its_owners_kennel(self):
        out = run_page("hounds", routes=self.world(), queries=[
            q("hrefs", f"{self.QROW} [data-hook='row-kennel']", "attrs", attr="href"),
            q("texts", f"{self.QROW} [data-hook='row-kennel']", "texts")])
        self.assertEqual(out["final"]["hrefs"], ["kennel.html?u=handler-21e8"] * 2)
        self.assertEqual(out["final"]["texts"], ["Handler 21E8's kennel"] * 2)

    def test_with_three_ranked_the_builders_tab_still_shows_them_expanded(self):
        ranked = [mk(f"r{i}", f"R{i}", bets=12, units=1.0 + i, wins=6, kind="user", owner_display="Handler 0001") for i in range(3)]
        out = run_page("hounds", routes=self.world(ranked), actions=[
            dict(do="click", sel="[data-filter='user']", label="builders", capture=[
                q("warm", ".hd-tr--warm", "attrs", attr="data-hound"), q("notes", "[data-hook='warming-note']", "texts")])])
        cap = out["captures"]["builders"]
        self.assertEqual(cap["warm"], ["u-d151fe52c7", "u-fcc8e8c168"])
        self.assertEqual(cap["notes"], ["New: no bets yet"] * 2)

    def test_pure_helpers_flag_only_a_member_dog_with_nothing_yet(self):
        out = run_js('import * as B from "./hounds-board.js";'
                     'const u = {kind: "user", record: {bets: 0}}, hs = {kind: "house", record: {bets: 0}}, ub = {kind: "user", record: {bets: 2, wins: 1, losses: 1}};'
                     'console.log(JSON.stringify([B.isNewDog(u), B.isNewDog(hs), B.isNewDog(ub), B.progressText(u), B.progressText(ub),'
                     'B.qualifyingRows([u, hs, ub]).length]));')
        self.assertEqual(out, [True, False, False, "New: no bets yet", "2/10 bets", 2])


# ---------------------------------------------------------------------------------------------------
# the model page
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class TheModelPageSeasons(unittest.TestCase):
    def season_detail(self, season, bets):
        d = F.detail("closer")
        d = json.loads(json.dumps(d))
        d["record"].update(bets=bets, wins=bets // 2, losses=bets - bets // 2, pushes=0, units_average_price=1.5, units_recorded_price=1.0)
        d["bankroll"] = dict(d["bankroll"], bets=bets, settled=bets, units_total=1.5, pnl_usd=15.0, current=1015.0,
                             return_pct=1.5, yield_pct=round(1.5 / bets * 100, 2))
        d["season"] = seasons.meta(season)
        return [200, d]

    def page(self, extra=None, **kw):
        r = routes(**(extra or {}))
        return run_page("hound", routes=r, search=kw.pop("search", "?id=closer"), **kw)

    def test_the_kpi_strip_opens_on_season_2_with_a_toggle(self):
        out = self.page(queries=[q("texts", "[data-hook='hound-season'] .hd-seg", "texts"),
                                 q("pressed", "[data-hook='hound-season'] .hd-seg", "attrs", attr="aria-pressed"),
                                 q("line", "[data-hook='hound-season-line']")])
        self.assertIn("/hounds/closer?season=s2", out["gets"])
        self.assertEqual(out["final"]["texts"], ["Season 2 (since Oct 18)", "Season 1", "All-time"])
        self.assertEqual(out["final"]["pressed"], ["true", "false", "false"])
        self.assertEqual(out["final"]["line"], "The numbers below cover Season 2 only. The status is the referee's all-time verdict.")

    def test_toggling_re_asks_the_server_for_that_seasons_numbers_and_keeps_the_choice(self):
        extra = {"/hounds/closer?season=s1": self.season_detail("s1", 7)}
        out = self.page(extra, actions=[dict(do="click", sel="[data-hook='hound-season'] [data-season='s1']", label="s1", wait=150, capture=[
            q("bets", ".hd-kpi[data-slot='bets']"), q("roi", ".hd-kpi[data-slot='yield'] .hd-kpi__big"),
            q("bank", ".hd-kpi[data-slot='bankroll']"),
            q("pressed", "[data-hook='hound-season'] .hd-seg", "attrs", attr="aria-pressed"), q("line", "[data-hook='hound-season-line']"),
            q("live", "[data-hook='forward-facts']")])])
        self.assertIn("/hounds/closer?season=s1", out["gets"])
        cap = out["captures"]["s1"]
        self.assertIn("Bets 7", cap["bets"])
        self.assertEqual(cap["roi"], f"{1.5 / 7 * 100:+.1f}%")                       # the yield tile, "profit per $ bet"
        self.assertIn("$1,015.00", cap["bank"])                                      # the season's own account
        self.assertEqual(cap["pressed"], ["false", "true", "false"])
        self.assertIn("Season 1 only", cap["line"])
        self.assertIn("Live record, Season 1", cap["live"])
        self.assertEqual(out["storedAfter"][STORE_KEY], "s1")
        self.assertEqual(out["replaced"], ["/web/x.html?id=closer&season=s1"])          # the model id stays in the URL

    def test_the_url_choice_is_honoured_on_arrival(self):
        out = self.page({"/hounds/closer?season=all": self.season_detail("all", 41)}, search="?id=closer&season=all")
        self.assertIn("/hounds/closer?season=all", out["gets"])

    def test_the_ticket_tables_default_to_every_season_and_have_their_own_chip(self):
        out = self.page(queries=[q("texts", "[data-hook='bets-season'] .hd-seg", "texts"),
                                 q("pressed", "[data-hook='bets-season'] .hd-seg", "attrs", attr="aria-pressed")])
        graded = [g for g in out["gets"] if "status=graded" in g]
        self.assertTrue(graded)
        self.assertTrue(all("season=" not in g for g in graded), graded)               # no season: the whole record
        self.assertEqual(out["final"]["texts"][0], "All seasons")
        self.assertEqual(out["final"]["pressed"][0], "true")

    def test_the_ticket_chip_filters_the_graded_list_without_touching_the_kpi_season(self):
        out = self.page(actions=[dict(do="click", sel="[data-bets-season='s2']", label="chip", wait=150, capture=[
            q("chips", "[data-hook='bets-season'] .hd-seg", "attrs", attr="aria-pressed"),
            q("kpi", "[data-hook='hound-season'] .hd-seg", "attrs", attr="aria-pressed")])])
        self.assertTrue(any("status=graded" in g and g.endswith("&season=s2") for g in out["gets"]), out["gets"])
        self.assertEqual(out["captures"]["chip"]["chips"], ["false", "true", "false"])
        self.assertEqual(out["captures"]["chip"]["kpi"], ["true", "false", "false"])
        self.assertEqual(out["storedAfter"], {})                                       # a ticket filter is not a remembered choice

    def test_the_status_says_it_is_all_time_and_the_sample_is_the_seasons(self):
        out = self.page(queries=[q("sample", "[data-hook='verdict-sample']")])
        self.assertEqual(out["final"]["sample"], "This is the referee's all-time verdict. Season 2: 41 graded live bets.")


# ---------------------------------------------------------------------------------------------------
# the landing page
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class TheLandingBoardSeasons(unittest.TestCase):
    def page(self, hounds, season="s2", **kw):
        r = {k: list(v) for k, v in F.routes().items()}
        r["/hounds"] = board(hounds, season)
        return run_page("landing_board", routes=r, queries=[
            q("ids", "[data-hook='lb-board'] .lbrow", "attrs", attr="data-hound"), q("empty", "[data-hook='lb-empty']"),
            q("ranks", "[data-hook='lb-board'] .lbrank", "texts"), q("bets", "[data-hook='lb-bets']", "texts"),
            q("pills", "[data-hook='lb-progress']", "texts"), q("roi_titles", ".lbrow--qual .lbtone--small", "attrs", attr="title"),
            q("note", "[data-hook='lb-season-note']"), q("hidden", "[data-hook='lb-season-note']", "hidden"),
            q("tag", "[data-hook='lb-season']"), q("tickets", "[data-hook='lb-ticket']", "count")], **kw)

    def ranked(self, n):
        return [mk(f"m{i}", f"Model {i}", bets=12 + i, units=float(10 - i)) for i in range(n)]

    def test_fewer_than_five_ranked_shows_those_then_the_best_of_the_qualifying_round_with_progress(self):
        hs = self.ranked(2) + [mk("hot", "Hot Start", bets=1, units=0.94, wins=1), mk("nine", "Nine", bets=9, units=7.0, wins=6)]
        f = self.page(hs)["final"]
        self.assertEqual(f["ids"], ["m0", "m1", "nine", "hot"])                      # ranked first, then the round by units
        self.assertEqual(f["ranks"], ["1", "2", "-", "-"])
        self.assertEqual(len(f["bets"]), 2)                                          # a ranked row shows its bets
        self.assertEqual(f["pills"], ["9/10 bets", "1/10 bets"])                     # a round row shows its progress
        self.assertEqual(len(f["roi_titles"]), 4)                                    # a round row greys its balance and its return
        self.assertTrue(all(t.startswith("Ranked in full at") for t in f["roi_titles"]), f["roi_titles"])
        self.assertRegex(f["note"], r"^Season 2 is \d+ days? old: more hounds qualify at 10 bets\.$")
        self.assertIs(f["hidden"], False)
        self.assertEqual(f["tag"], "\u00b7 Season 2")
        self.assertEqual(f["tickets"], 2)                                            # the latest tickets still show beside it

    def test_nobody_ranked_shows_the_top_five_of_the_round_not_an_empty_board(self):
        hs = [mk(f"q{i}", f"Qual {i}", bets=i + 1, units=float(i), wins=i + 1) for i in range(7)]
        f = self.page(hs)["final"]
        self.assertEqual(f["ids"], ["q6", "q5", "q4", "q3", "q2"])                   # top five by units
        self.assertEqual(f["pills"], ["7/10 bets", "6/10 bets", "5/10 bets", "4/10 bets", "3/10 bets"])
        self.assertEqual(set(f["ranks"]), {"-"})
        self.assertEqual(f["empty"], None)
        self.assertRegex(f["note"], r"Season 2 is \d+ days? old: more hounds qualify at 10 bets\.")
        self.assertEqual(f["tickets"], 2)

    def test_the_round_tops_the_board_up_to_five_and_no_more(self):
        hs = self.ranked(1) + [mk(f"q{i}", f"Qual {i}", bets=i + 1, units=float(i), wins=i + 1) for i in range(6)]
        f = self.page(hs)["final"]
        self.assertEqual(len(f["ids"]), 5)
        self.assertEqual(f["ids"][0], "m0")
        self.assertEqual(len(f["pills"]), 4)

    def test_baselines_models_with_no_settled_bet_and_retired_ones_are_not_in_the_round(self):
        hs = [mk("base", "Base", bets=6, units=9.0, wins=5, category="baseline"), mk("none", "None", bets=0, units=0.0, wins=0),
              mk("gone", "Gone", bets=6, units=8.0, wins=5, status="retired"), mk("ok", "Okay", bets=3, units=1.0, wins=2)]
        self.assertEqual(self.page(hs)["final"]["ids"], ["ok"])

    def test_with_no_model_holding_a_settled_bet_the_board_says_so(self):
        f = self.page([mk("none", "None", bets=0, units=0.0, wins=0)])["final"]
        self.assertEqual(f["ids"], [])
        self.assertEqual(f["empty"], "No hound has 10 settled bets in Season 2 yet. The board fills as the slate settles.")

    def test_five_ranked_fill_the_board_with_no_pills_and_the_young_season_line_goes_away(self):
        f = self.page(self.ranked(7))["final"]
        self.assertEqual(f["ids"], ["m0", "m1", "m2", "m3", "m4"])
        self.assertEqual(f["pills"], [])
        self.assertIs(f["hidden"], True)
        self.assertEqual(f["note"], "")

    def test_the_landing_page_asks_for_the_default_season_by_not_naming_one(self):
        out = self.page(self.ranked(5))
        self.assertIn("/hounds", [g.split("?")[0] for g in out["gets"]])

    def test_an_all_time_payload_never_gets_a_young_season_line(self):
        f = self.page(self.ranked(2), season="all")["final"]
        self.assertIs(f["hidden"], True)


class TheMarkupIsStatic(unittest.TestCase):
    """No node needed: the skeleton the scripts fill is in the HTML."""

    def test_the_leaderboard_page_has_the_switcher_and_the_season_line_with_scripts_off(self):
        html = (Path(__file__).resolve().parent.parent / "web" / "hounds.html").read_text(encoding="utf-8")
        self.assertIn('data-hook="hounds-season"', html)
        self.assertRegex(html, r'data-hook="season-line"[^>]*>Season 2 started Oct 18\. Every model starts at zero\.</p>')

    def test_the_model_and_landing_pages_have_their_slots(self):
        root = Path(__file__).resolve().parent.parent / "web"
        hound = (root / "hound.html").read_text(encoding="utf-8")
        for hook in ("hound-season", "hound-season-line", "bets-season"):
            self.assertIn(f'data-hook="{hook}"', hound)
        landing = (root / "landing.html").read_text(encoding="utf-8")
        for hook in ("lb-season", "lb-season-note"):
            self.assertIn(f'data-hook="{hook}"', landing)

    def test_no_season_script_loads_anything_from_outside_or_uses_a_script_tag_on_the_pages(self):
        root = Path(__file__).resolve().parent.parent / "web"
        src = (root / "js" / "hounds-season.js").read_text(encoding="utf-8")
        self.assertNotRegex(src, r"https?://")
        html = (root / "hounds.html").read_text(encoding="utf-8")
        # only external module scripts (the page, the kennels view, tabs, motion, the shared nav): never an inline script or a CDN
        for name in ("hounds-page", "kennels-index", "tabs", "fx", "nav"):
            html = html.replace(f'<script type="module" src="js/{name}.js"></script>', "")
        self.assertIsNone(re.search(r"<script", html))


if __name__ == "__main__":
    unittest.main()
