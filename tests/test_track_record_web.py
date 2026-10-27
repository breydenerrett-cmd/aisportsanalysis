"""The track record page (web/record.html, web/js/track-record.js), run for real under node against payloads built by the real Python builder
(src/hounds/track_record.py), so a drift between the two fails here.

  HEADER      record, units, ROI, the streak and the last ten; closing-line value only when the data has it; "only N settled bets".
  CUTS        the five breakdowns with the server's one-line read; a thin cut says "only N bets".
  OPEN        open tickets in their own section, never in the settled list or the counts.
  TICKETS     the filters (sport, result, market), each ticket's "why", the -200 tag, times in the viewer's zone.
  CALENDAR    one grid per month, win and loss days.
  COMPARE     the pack and the leaderboard, or the plain "nothing to compare" line.
  NEXT STEPS  three buttons that go to real pages, the owner's differently from a visitor's.
  LINKS       "See full record" on the hound sheet's Record tab and on the public hound page.
  STATIC      no banned word, no script tag beyond the modules, the footer says paper only.
"""

from __future__ import annotations

import re
import unittest

from src.hounds import track_record as tr
from tests.hounds_web_runner import HAS_NODE, WEB, run_js, run_page
from tests.test_hound_sheet import StudioHelpers
from tests.test_hound_sheet import q as sq
from tests.test_kennel_page import dog
from tests.test_track_record import NOW, bet, data_of, defn, lots

BAD_TEXT = re.compile(r"undefined|NaN|\bnull\b|\[object|Infinity")
BANNED = re.compile(r"(?<![-_A-Za-z])dogs?(?![-_A-Za-z])|\bbeta\b|\bnew\b|nothing cleared the bar|\bedge\b|\bprofit|guarantee", re.I)
TOKEN_KEY = "aisportsanalysis.invite_token"
SIGNED = dict(stored={TOKEN_KEY: "tok"})


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


def read(name):
    return (WEB / name).read_text(encoding="utf-8")


def payload(bets=None, compare="auto", **kw):
    p = tr.build(data_of(bets if bets is not None else lots()).view("all"), as_of="2026-10-19", now=NOW, **kw)
    p["hound"]["id"] = "u-1"
    p["season"] = {"id": "all", "label": "All-time", "available": [{"id": "s2", "label": "Season 2"}, {"id": "all", "label": "All-time"}]}
    if compare == "auto":
        p["compare"] = {"period": "All-time", "mine": {"n": 24, "roi_pct": p["header"]["roi_pct"], "win_pct": 50.0, "clv": None},
                        "house_pack": {"hounds": 3, "bets": 80, "roi_pct": 1.5, "win_pct": 51.0, "clv": 0.4},
                        "leaderboard": {"hounds": 9, "bets": 200, "roi_pct": -2.0, "win_pct": 49.0, "clv": None}, "note": "Each average is across hounds."}
    else:
        p["compare"] = compare
    return p


def page(body, id="u-1", routes=None, **kw):
    r = {f"/hounds/{id}/record": [200, body]}
    r.update(routes or {})
    return run_page("record", search=f"?id={id}", routes=r, tz="UTC", settleMs=200, **kw)


def hook(h, **kw):
    return q(h, f"[data-hook='{h}']", **kw)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheHeader(unittest.TestCase):
    def test_the_numbers_the_streak_and_the_title(self):
        p = payload()
        out = page(p, queries=[hook("record-title"), hook("record-sub"), hook("stat-record"), hook("stat-units"), hook("stat-roi"), hook("stat-streak"),
                               hook("stat-clv", mode="count"), q("pips", ".rc-pip", "count"), hook("record-sample", mode="hidden"),
                               hook("record-body", mode="hidden"), hook("record-state", mode="hidden"), hook("record-back", mode="attr", attr="href")])
        f = out["final"]
        self.assertEqual(f["record-title"], "Dee: track record")
        self.assertIn("House hound", f["record-sub"])
        self.assertIn("12-12", f["stat-record"])
        self.assertIn("24 bets settled", f["stat-record"])
        h = p["header"]
        self.assertIn(f"{h['units']:+.1f}u", f["stat-units"])
        self.assertIn("at the average price", f["stat-units"])
        self.assertIn(f"{h['roi_pct']:+.1f}%", f["stat-roi"])
        self.assertRegex(f["stat-streak"], r"[WL]\d+")
        self.assertEqual(f["stat-clv"], 0, "no closing-line value in the data: the tile is left out, not shown as zero")
        self.assertEqual(f["pips"], 10)
        self.assertTrue(f["record-sample"])                         # 24 settled bets: not a small sample, the note is hidden
        self.assertFalse(f["record-body"])
        self.assertTrue(f["record-state"])
        self.assertEqual(f["record-back"], "hound.html?id=u-1")
        self.assertNotRegex(out["text"], BAD_TEXT)

    def test_closing_line_value_shows_when_the_data_has_it(self):
        p = payload()
        p["header"]["clv"] = {"n": 31, "mean_pts": 0.8}
        out = page(p, queries=[hook("stat-clv")])
        self.assertIn("+0.80 pts", out["final"]["stat-clv"])
        self.assertIn("31 bets we could check", out["final"]["stat-clv"])

    def test_a_small_sample_says_only_n_settled_bets(self):
        out = page(payload([bet(i, "win" if i % 2 else "loss") for i in range(6)]), queries=[hook("record-sample"), q("shut", "[data-hook='record-sample']", "hidden")])
        self.assertIn("Only 6 bets settled so far", out["final"]["record-sample"])
        self.assertFalse(out["final"]["shut"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheCuts(unittest.TestCase):
    def test_five_cards_each_with_the_servers_line(self):
        p = payload()
        out = page(p, queries=[q("cards", ".rc-cutcard", "count"), q("lines", "[data-hook='cut-line']", "texts"),
                               q("rows", "[data-hook='cut-row']", "count")])
        self.assertEqual(out["final"]["cards"], 5)
        self.assertEqual(out["final"]["lines"], [g["line"] for g in p["breakdowns"]])
        self.assertEqual(out["final"]["rows"], sum(len(g["rows"]) for g in p["breakdowns"]))

    def test_a_thin_cut_is_marked_only_n_bets(self):
        bets = [bet(i, "win") for i in range(10)] + [bet(50 + i, "loss", sport="nba", side="away", game="Celtics at Lakers", selection="Celtics moneyline")
                                                    for i in range(3)]
        out = page(payload(bets), queries=[q("rows", ".rc-cut--thin .rc-cut__n", "texts"), q("lines", "[data-hook='cut-line']", "texts")])
        self.assertIn("only 3 bets", out["final"]["rows"])
        self.assertIn("NBA bets (only 3 bets)", out["final"]["lines"][0])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheTickets(unittest.TestCase):
    def test_open_tickets_are_apart_and_the_settled_list_has_only_settled_ones(self):
        p = payload()
        out = page(p, queries=[q("open", "[data-hook='open-ticket']", "count"), q("settled", "[data-hook='ticket']", "count"),
                               hook("record-open-section", mode="hidden"), q("title", "[data-hook='record-open-section'] h2"),
                               q("waiting", "[data-hook='waiting-list'] li", "count"), hook("ticket-count") if False else hook("record-ticket-count")])
        f = out["final"]
        self.assertEqual((f["open"], f["waiting"], f["settled"]), (2, 1, 24), "the open one and the stale one share the open-style card; neither is settled")
        self.assertFalse(f["record-open-section"])
        self.assertEqual(f["title"], "Open ticket")
        self.assertEqual(f["record-ticket-count"], "Showing 24 of 24 settled tickets.")

    def test_a_hound_with_no_open_ticket_hides_the_section(self):
        out = page(payload([bet(i, "win") for i in range(6)]), queries=[hook("record-open-section", mode="hidden")])
        self.assertTrue(out["final"]["record-open-section"])

    def test_the_filters_narrow_the_list_without_asking_the_server_again(self):
        actions = [dict(do="set", sel="[data-hook='filter-sport']", value="NBA", label="sport", wait=60, capture=[q("n", "[data-hook='ticket']", "count"),
                                                                                                                 hook("record-ticket-count")]),
                   dict(do="set", sel="[data-hook='filter-result']", value="win", label="won", wait=60, capture=[q("n", "[data-hook='ticket']", "count"),
                                                                                                                 hook("record-ticket-count")]),
                   dict(do="set", sel="[data-hook='filter-market']", value="Total", label="none", wait=60, capture=[q("n", "[data-hook='ticket']", "count"),
                                                                                                                    hook("tickets-none")])]
        out = page(payload(), actions=actions)
        c = out["captures"]
        self.assertEqual(c["sport"]["n"], 12)
        self.assertEqual(c["won"]["n"], 3)                       # three NBA wins (i % 4 == 0)
        self.assertEqual(c["won"]["record-ticket-count"], "Showing 3 of 24 settled tickets.")
        self.assertEqual(c["none"]["n"], 0)
        self.assertIn("No settled ticket matches", c["none"]["tickets-none"])
        self.assertEqual(len([g for g in out["gets"] if "/record" in g]), 1)

    def test_the_why_is_shown_when_stored_and_absent_when_not(self):
        out = page(payload(), queries=[q("why", "[data-hook='ticket-why']", "texts")])
        self.assertEqual(len(out["final"]["why"]), 12)
        self.assertTrue(all(t == "Why: fits the rule" for t in out["final"]["why"]))

    def test_times_are_in_the_viewers_zone(self):
        out = run_page("record", search="?id=u-1", routes={"/hounds/u-1/record": [200, payload()]}, tz="America/Los_Angeles", settleMs=200,
                       now="2026-10-20T20:00:00Z", queries=[q("when", ".rc-ticket__when", "texts")])
        text = " ".join(out["final"]["when"])
        self.assertRegex(text, r"Recorded Oct \d+ at 11:00 AM PT")
        self.assertRegex(text, r"Starts \w{3} 4:30 PM PT")            # the open ticket's 23:30Z start

    def test_a_ticket_at_minus_200_is_tagged_and_the_list_is_honest_about_the_cap(self):
        p = payload([bet(1, "win", price=-250, avg=-250), bet(2, "loss")])
        p["tickets_total"] = 400
        out = page(p, queries=[q("tag", ".rc-ticket__tag", "texts"), hook("record-ticket-count")])
        self.assertEqual(out["final"]["tag"], ["-200 or worse (old rule)"])
        self.assertIn("the latest 2 of 400", out["final"]["record-ticket-count"])

    def test_no_settled_tickets_says_what_to_expect(self):
        out = page(payload([]), queries=[hook("tickets-empty"), hook("record-filters", mode="hidden"), hook("curve-empty")])
        self.assertIn("No settled tickets yet", out["final"]["tickets-empty"])
        self.assertTrue(out["final"]["record-filters"])
        self.assertIn("No settled bets yet", out["final"]["curve-empty"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheCurveAndTheCalendar(unittest.TestCase):
    def test_the_curve_is_drawn_at_the_viewers_sizing_and_says_what_it_is(self):
        out = page(payload(), queries=[q("svg", "[data-hook='curve-figure'] svg", "count"), q("cap", "[data-hook='curve-figure'] figcaption")])
        self.assertEqual(out["final"]["svg"], 1)
        self.assertRegex(out["final"]["cap"], r"after each of its 24 settled bets, now [+-]\$\d+ from the start")

    def test_too_few_bets_for_a_curve_say_so_instead_of_drawing_one(self):
        p = payload([bet(1, "win")])
        out = page(p, queries=[q("svg", "[data-hook='curve-figure']", "count"), hook("curve-empty")])
        self.assertEqual(out["final"]["svg"], 0)
        self.assertIn("Only 1 bet settled", out["final"]["curve-empty"])

    def test_the_calendar_has_a_grid_per_month_and_colours_win_and_loss_days(self):
        p = payload()
        out = page(p, queries=[q("months", "[data-hook='cal-month'] h3", "texts"), q("win", ".rc-day--win", "count"), q("loss", ".rc-day--loss", "count"),
                               q("labels", ".rc-day--win", "attrs", attr="aria-label")])
        self.assertEqual(out["final"]["months"], ["October 2026"])
        wins = sum(1 for d in p["calendar"] if d["result"] == "win")
        losses = sum(1 for d in p["calendar"] if d["result"] == "loss")
        self.assertEqual((out["final"]["win"], out["final"]["loss"]), (wins, losses))
        self.assertTrue(all(re.match(r"Oct \d+: \d+-\d+, [+-]\d", t) for t in out["final"]["labels"]), out["final"]["labels"])

    def test_the_month_grid_math(self):
        out = run_js('import { monthGrids } from "./track-record.js";\n'
                     'const g = monthGrids([{date:"2026-10-03"},{date:"2026-09-30"},{date:"2026-07-01"},{date:"2026-08-15"}], 3);\n'
                     'console.log(JSON.stringify(g.map(m => [m.ym, m.cells.filter(c => c === null).length, m.cells.filter(c => c).length])));\n')
        self.assertEqual(out, [["2026-10", 4, 31], ["2026-09", 2, 30], ["2026-08", 6, 31]])      # Oct 1 2026 is a Thursday; Sep 1 a Tuesday; Aug 1 a Saturday


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheCompare(unittest.TestCase):
    def test_the_table_has_three_rows_and_a_plain_sentence(self):
        out = page(payload(), queries=[q("rows", "[data-hook='compare-table'] tbody tr", "count"), hook("cmp-pack"), hook("cmp-board"), hook("compare-line")])
        f = out["final"]
        self.assertEqual(f["rows"], 3)
        self.assertIn("+1.5%", f["cmp-pack"])
        self.assertIn("3 hounds, 80 bets", f["cmp-pack"])
        self.assertIn("-2.0%", f["cmp-board"])
        self.assertIn("points", f["compare-line"])
        self.assertIn("Over the same period (All-time)", f["compare-line"])

    def test_no_other_hound_means_no_table_and_a_plain_line(self):
        out = page(payload(compare=None), queries=[hook("compare-none"), q("table", "[data-hook='compare-table']", "count")])
        self.assertIn("nothing to compare against yet", out["final"]["compare-none"])
        self.assertEqual(out["final"]["table"], 0)

    def test_a_thin_sample_says_the_gap_says_little(self):
        p = payload()
        p["compare"]["mine"]["n"] = 7
        out = page(p, queries=[hook("compare-line")])
        self.assertIn("Only 7 bets so far, so this gap says little.", out["final"]["compare-line"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheNextSteps(unittest.TestCase):
    def test_a_visitor_copies_or_asks_and_the_backtest_goes_through_a_copy(self):
        out = page(payload(), queries=[hook("next-backtest", mode="attr", attr="href"), hook("next-copy", mode="attr", attr="href"),
                                       hook("next-ask", mode="attr", attr="href"), q("labels", ".rc-next__btn", "texts")])
        f = out["final"]
        self.assertEqual(f["labels"], ["Backtest a tweak", "Copy this hound", "Ask why it lost"])
        self.assertEqual(f["next-backtest"], "build-a-hound.html?from=u-1")
        self.assertEqual(f["next-copy"], "build-a-hound.html?from=u-1")
        self.assertEqual(f["next-ask"], "hound.html?id=u-1&tab=ask")

    def test_the_owners_backtest_opens_their_own_rules_tab(self):
        kit = {"dog_id": "u-1", "is_owner": True, "signed_in": True}
        out = page(payload(), routes={"/hounds/u-1/kit": [200, kit]}, **SIGNED, queries=[hook("next-backtest", mode="attr", attr="href"),
                                                                                         hook("next-copy", mode="attr", attr="href")])
        self.assertEqual(out["final"]["next-backtest"], "kennel.html?dog=u-1&tab=rules")
        self.assertEqual(out["final"]["next-copy"], "build-a-hound.html?from=u-1")

    def test_every_target_is_a_page_that_exists_and_reads_the_parameter_it_is_given(self):
        for name, param in (("build-a-hound.html", "from"), ("kennel.html", "dog"), ("hound.html", "id")):
            self.assertTrue((WEB / name).exists(), name)
        self.assertIn('params.get("from")', read("js/hounds-build.js"))
        self.assertIn('params.get("dog")', read("js/kennel.js"))
        self.assertIn('params.get("id")', read("js/hounds-detail.js"))
        self.assertIn('data-tab="ask"', read("hound.html"))
        self.assertIn('data-tab="rules"', read("kennel.html"))


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheStates(unittest.TestCase):
    def test_no_id_a_missing_hound_and_a_down_server_each_say_so(self):
        out = run_page("record", routes={}, queries=[hook("record-state")])
        self.assertIn("No hound was chosen", out["final"]["record-state"])
        out = run_page("record", search="?id=ghost", routes={}, settleMs=200, queries=[hook("record-state")])
        self.assertIn("There is no hound with this id", out["final"]["record-state"])
        out = run_page("record", search="?id=u-1", routes={}, down=["/hounds/u-1/record"], settleMs=200, queries=[hook("record-state"),
                                                                                                         q("retry", "[data-hook='record-state'] button", "count")])
        self.assertEqual(out["final"]["retry"], 1)

    def test_warming_up_says_so_and_asks_again_on_a_timer(self):
        warm = {"warming_up": True, "retry_after_seconds": 2, "message": "The numbers are being worked out."}
        out = page(warm, queries=[hook("record-state"), hook("record-body", mode="hidden")])
        self.assertIn("being worked out", out["final"]["record-state"])
        self.assertTrue(out["final"]["record-body"])
        self.assertTrue(out["intervals"])

    def test_the_season_buttons_ask_for_that_season(self):
        p = payload()
        s2 = dict(p, season=dict(p["season"], id="s2", label="Season 2"))
        out = page(p, routes={"/hounds/u-1/record?season=s2": [200, s2]},
                   actions=[dict(do="click", sel="[data-season='s2']", label="s2", wait=150, capture=[hook("record-sub")])])
        self.assertTrue(any("season=s2" in g for g in out["gets"]), out["gets"])
        self.assertIn("Season 2", out["captures"]["s2"]["record-sub"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheLinks(StudioHelpers, unittest.TestCase):
    def test_the_hound_sheets_record_tab_links_to_the_full_record(self):
        out = self.sheet(actions=[dict(do="click", sel="[data-hook='dog-avatar']", wait=200, label="open", capture=[
            sq("href", "[data-hook='studio-full-record']", "attr", attr="href"), sq("label", "[data-hook='studio-full-record']")])])
        self.assertEqual(out["captures"]["open"]["href"], "record.html?id=u-1")
        self.assertEqual(out["captures"]["open"]["label"], "See full record")

    def test_the_public_hound_page_links_to_it_too(self):
        html = read("hound.html")
        self.assertIn('data-hook="hound-full-record"', html)
        self.assertIn("See full record", html)
        self.assertIn("record.html?id=", read("js/hounds-detail.js"))


class TheStaticPage(unittest.TestCase):
    def test_the_page_says_paper_only_loads_modules_and_has_no_banned_word(self):
        html = read("record.html")
        self.assertIn("Paper bets only, not advice", html)
        self.assertEqual(len(re.findall(r"<script", html)), len(re.findall(r'<script type="module" src="js/[a-z-]+\.js"></script>', html)))
        visible = re.sub(r"<!--.*?-->", "", html, flags=re.S)
        visible = re.sub(r"<(script|style)[\s\S]*?</\1>", "", visible)
        text = re.sub(r"<[^>]+>", " ", visible)
        self.assertIsNone(BANNED.search(text), BANNED.search(text))
        js = read("js/track-record.js")
        strings = " ".join(re.findall(r'"([^"\n]{4,})"', js) + re.findall(r"`([^`\n]{4,})`", js))
        strings = strings.replace("kennel.html?dog=", "kennel.html?")         # the sheet's own existing deep-link parameter, not copy
        self.assertIsNone(BANNED.search(strings), BANNED.search(strings))

    def test_the_css_never_lets_the_page_scroll_sideways(self):
        css = read("css/record.css")
        self.assertIn("overflow-x: clip", css)
        self.assertIn(".rc-tablewrap { overflow-x: auto; }", css)
        self.assertIn("minmax(0, 1fr)", css)
        for line in re.findall(r"^[^/\n{}]*\{", css, flags=re.M):
            sel = line.strip().rstrip("{").strip()
            if sel and not sel.startswith("@") and not sel.startswith("*"):
                self.assertRegex(sel, r"\.rc-|\.hounds-page \.rc-wrap", f"unscoped selector {sel!r}")


if __name__ == "__main__":
    unittest.main()
