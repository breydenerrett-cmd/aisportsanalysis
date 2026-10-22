"""web/js/ticket-live.js: every ticket shows where its game stands, with the network faked (2026-10-22).

Upcoming (starts in X) · Live (the score) · Final, grading… · WON +$X / LOST -$X / PUSH at the viewer's unit size, plus the
"Last graded" stamp and the "Grading" pill. The real hound page script runs under node against its real HTML
(tests/hounds_web_runner.py); /hounds/live and /hounds/live/status are answered by the scenario, never a server.
"""
from __future__ import annotations

import dataclasses
import json
import unittest

from src.hounds import contract
from tests import hounds_web_fixtures as F
from tests.hounds_web_runner import HAS_NODE, run_js, run_page
from tests.test_hounds_board_pages import ticket_routes
from tests.test_hounds_web_pages import q, routes

NOW = "2026-10-24T20:00:00Z"
OPEN_URL = "/hounds/closer/bets?status=open&segment=forward&page=1&page_size=50"
GRADED_URL = "/hounds/closer/bets?status=graded&segment=forward&page=1&page_size=20"
STATUS = "/hounds/live/status"
LIVE = "/hounds/live"


def open_rows(*specs):
    """BetRows for open tickets: (event id, start iso) per ticket."""
    base = F.bet_rows("closer", 12)
    out = []
    for i, (event, start) in enumerate(specs):
        out.append(dataclasses.replace(base[i], result=None, units=None, clv_pts=None, event_id=event, start_utc=start,
                                       sport="NBA", game=f"Away{i} at Home{i}"))
    return out


def payload(rows, status):
    return json.loads(json.dumps(contract.bets_payload("closer", {"items": rows, "page": 1, "page_size": 50,
                                                                  "total": len(rows), "pages": 1}, "2026-10-24"), default=str))


def graded_rows():
    base = F.bet_rows("closer", 12)
    wins = dataclasses.replace(base[3], result="win", units=0.9, event_id="g1", sport="NBA")
    loss = dataclasses.replace(base[4], result="loss", units=-1.0, event_id="g2", sport="NBA")
    push = dataclasses.replace(base[5], result="push", units=0.0, event_id="g3", sport="NBA")
    return [wins, loss, push]


def scenario(open_specs, live_games, status=None, **extra):
    r = routes()
    r.update(ticket_routes("closer"))
    r[OPEN_URL] = [200, payload(open_rows(*open_specs), "open")]
    r[GRADED_URL] = [200, payload(graded_rows(), "graded")]
    r[LIVE] = [200, {"games": live_games}]
    r[STATUS] = [200, status or {"enabled": True, "last_graded_utc": None, "awaiting_final": 0, "final_ungraded": 0}]
    # a generous settle: the page chains several fake fetches, and the suite runs beside other heavy processes
    extra.setdefault("settleMs", 500)
    return dict(routes=r, search="?id=closer", now=NOW, **extra)


def game(state, start="2026-10-24T19:30:00Z", **kw):
    return dict({"state": state, "start_utc": start, "home_score": None, "away_score": None, "detail": None,
                 "supported": True}, **kw)


OPEN_QUERIES = [
    q("chips", "[data-hook='open-table-cards'] [data-hook='card-status']", "texts"),
    q("live", "[data-hook='open-table-cards'] [data-hook='ticket-live']", "texts"),
    q("live_hidden", "[data-hook='open-table-cards'] [data-hook='ticket-live']", "attrs", attr="hidden"),
    q("rows", "[data-hook='open-table'] tbody tr", "count"),
    q("row_chips", "[data-hook='open-table'] tbody [data-hook='ticket-status']", "texts"),
]


@unittest.skipUnless(HAS_NODE, "node not installed")
class ThePureHelpers(unittest.TestCase):
    def js(self, body):
        return run_js('import * as L from "./ticket-live.js";\n' + body)

    def test_starts_in(self):
        out = self.js('const n=Date.parse("2026-10-24T20:00:00Z");console.log(JSON.stringify(['
                      'L.startsIn(n+30000,n),L.startsIn(n+35*60000,n),L.startsIn(n+190*60000,n),L.startsIn(n+120*60000,n),'
                      'L.startsIn(n+72*3600000,n)]));')
        self.assertEqual(out, ["under a minute", "35m", "3h 10m", "2h", "3d"])

    def test_each_state_reads_in_plain_words_and_an_unknown_game_reads_as_nothing(self):
        cases = {
            "final": ({"state": "final", "away_score": 108, "home_score": 112}, "GRADING", "Final 108-112, grading…"),
            "live": ({"state": "live", "away_score": 66, "home_score": 61, "detail": "Q3 4:12"}, "LIVE", "Live 66-61 · Q3 4:12"),
            "postponed": ({"state": "postponed"}, "POSTPONED", "Postponed, waits for the makeup"),
            "cancelled": ({"state": "cancelled"}, "CANCELLED", "Cancelled, voids by rule"),
            "upcoming": ({"state": "upcoming", "start_utc": "2026-10-24T22:10:00Z"}, "UPCOMING", "Starts in 2h 10m"),
        }
        for name, (info, chip, text) in cases.items():
            with self.subTest(name):
                got = self.js(f'console.log(JSON.stringify(L.liveView({json.dumps(info)}, null, Date.parse("{NOW}"))));')
                self.assertEqual((got["chip"], got["text"]), (chip, text))
        for info in (None, {"state": "unknown"}, {"state": "live", "supported": False}, {}):
            with self.subTest(info=info):
                self.assertIsNone(self.js(f'console.log(JSON.stringify(L.liveView({json.dumps(info)}, null, 0)));'))

    def test_a_live_row_without_a_readable_score_shows_no_score(self):
        got = self.js('console.log(JSON.stringify(L.liveView({state:"live",away_score:null,home_score:null},null,0)));')
        self.assertEqual(got["text"], "Live")

    def test_dollars_follow_the_viewers_fixed_unit_and_percent_sizing_prints_none(self):
        out = self.js('const f=(u)=>({mode:"fixed",unit_usd:u,pct:null,start_usd:u*100});'
                      'console.log(JSON.stringify([L.dollarsText(0.9,f(25)),L.dollarsText(-1,f(25)),L.dollarsText(0,f(25)),'
                      'L.dollarsText(2.5,f(10)),L.dollarsText(0.91,f(25)),L.dollarsText(0.9,{mode:"percent",pct:1,start_usd:2500}),'
                      'L.dollarsText(null,f(25))]));')
        self.assertEqual(out, ["+$22.50", "-$25", "$0", "+$25", "+$22.75", None, None])   # cents show; never silently rounded to whole dollars

    def test_the_badge_words(self):
        got = self.js('console.log(JSON.stringify([L.badgeView({awaiting_final:2,final_ungraded:1}),L.badgeView({}),'
                      'L.badgeView({awaiting_final:1})]));')
        self.assertEqual(got[0]["grading"], "Grading 3 games…")
        self.assertEqual(got[1]["grading"], "")
        self.assertEqual(got[2]["grading"], "Grading 1 game…")


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheHoundPage(unittest.TestCase):
    SPECS = [("ev-upcoming", "2026-10-24T22:10:00Z"), ("ev-live", "2026-10-24T19:30:00Z"),
             ("ev-final", "2026-10-24T17:00:00Z"), ("ev-post", "2026-10-24T18:00:00Z"), ("ev-unknown", "2026-10-24T18:30:00Z")]

    def games(self):
        return {"ev-upcoming": game("upcoming", "2026-10-24T22:10:00Z"),
                "ev-live": game("live", away_score=66, home_score=61, detail="Q3 4:12"),
                "ev-final": game("final", "2026-10-24T17:00:00Z", away_score=108, home_score=112),
                "ev-post": game("postponed", "2026-10-24T18:00:00Z")}

    def test_every_pending_ticket_shows_its_state_and_an_unknown_game_is_left_as_pending(self):
        out = run_page("hound", **scenario(self.SPECS, self.games(), queries=OPEN_QUERIES))["final"]
        self.assertEqual(out["chips"], ["UPCOMING", "LIVE", "GRADING", "POSTPONED", "PENDING"])
        self.assertEqual([t for t in out["live"] if t], ["Starts in 2h 10m", "Live 66-61 · Q3 4:12", "Final 108-112, grading…",
                                                        "Postponed, waits for the makeup"])
        self.assertEqual(out["row_chips"], ["UPCOMING", "LIVE", "GRADING", "POSTPONED", "PENDING"], "the table rows follow")
        self.assertEqual(out["live_hidden"].count(None), 4, "four tickets have something true to say; the unknown one stays hidden")

    def test_the_page_asks_for_only_the_pending_tickets_games_in_one_request(self):
        run = run_page("hound", **scenario(self.SPECS, self.games(), queries=OPEN_QUERIES))
        asks = [u for u in run["gets"] if u.startswith(LIVE + "?")]
        self.assertEqual(len(asks), 1, asks)
        ids = asks[0].split("ids=")[1].split(",")
        self.assertEqual(sorted(ids), sorted(e for e, _ in self.SPECS))

    def test_graded_tickets_show_dollars_at_the_viewers_unit_and_not_in_percent_mode(self):
        queries = [q("live", "[data-hook='bets-table-cards'] [data-hook='ticket-live']", "texts"),
                   q("chips", "[data-hook='bets-table-cards'] [data-hook='card-status']", "texts")]
        fixed = run_page("hound", viewer={"mode": "fixed", "unit_usd": 25, "pct": None, "start_usd": 2500},
                         **scenario(self.SPECS, self.games(), queries=queries))["final"]
        self.assertEqual(fixed["chips"], ["WON", "LOST", "PUSH"])
        self.assertEqual([t for t in fixed["live"] if t], ["+$22.50", "-$25", "Push, $0"])
        pct = run_page("hound", viewer={"mode": "percent", "unit_usd": None, "pct": 1, "start_usd": 2500},
                       **scenario(self.SPECS, self.games(), queries=queries))["final"]
        self.assertEqual([t for t in pct["live"] if t], [])

    def test_a_game_that_goes_final_between_polls_flips_the_ticket_without_a_reload(self):
        specs = [("ev-live", "2026-10-24T19:30:00Z")]
        sc = scenario(specs, {"ev-live": game("live", away_score=90, home_score=88, detail="Q4 1:02")}, queries=OPEN_QUERIES)
        sc["switchAfter"] = {LIVE: [1, [200, {"games": {"ev-live": game("final", away_score=92, home_score=88)}}]]}
        sc["actions"] = [{"do": "fire_timers", "wait": 500, "capture": [q("live", "[data-hook='open-table-cards'] [data-hook='ticket-live']", "texts"),
                                                                        q("chip", "[data-hook='open-table-cards'] [data-hook='card-status']", "texts")]}]
        run = run_page("hound", **sc)
        self.assertEqual(run["final"]["live"], ["Final 92-88, grading…"])
        self.assertEqual(run["final"]["chips"], ["GRADING"])

    def test_the_feed_being_down_leaves_every_ticket_exactly_as_it_was(self):
        sc = scenario(self.SPECS, self.games(), queries=OPEN_QUERIES, down=[LIVE])
        out = run_page("hound", **sc)["final"]
        self.assertEqual(set(out["chips"]), {"PENDING"})
        self.assertEqual(len([t for t in out["live"] if t]), 0)

    def test_a_server_without_the_endpoint_does_not_break_the_page(self):
        sc = scenario(self.SPECS, {}, queries=OPEN_QUERIES)
        del sc["routes"][LIVE]
        out = run_page("hound", **sc)["final"]
        self.assertEqual(set(out["chips"]), {"PENDING"})


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheGradingBadge(unittest.TestCase):
    BADGE = [q("badge_hidden", "[data-hook='grading-badge']", "attrs", attr="hidden"),
             q("last", "[data-hook='last-graded']"), q("pill", "[data-hook='grading-indicator']"),
             q("pill_hidden", "[data-hook='grading-indicator']", "attrs", attr="hidden")]

    def test_it_shows_last_graded_and_a_grading_pill_while_games_wait_on_a_final(self):
        status = {"enabled": True, "last_graded_utc": "2026-10-24T19:14:00Z", "awaiting_final": 2, "final_ungraded": 0}
        out = run_page("hound", tz="UTC", **scenario(OPEN_SPECS_ONE, {}, status=status, queries=self.BADGE))["final"]
        self.assertEqual(out["badge_hidden"], [None], "the badge is shown")
        self.assertEqual(out["last"], "Last graded 19:14")
        self.assertEqual(out["pill"], "Grading 2 games…")
        self.assertEqual(out["pill_hidden"], [None], "the pill is shown")

    def test_nothing_waiting_hides_the_pill_and_a_silent_server_hides_the_badge(self):
        quiet = {"enabled": True, "last_graded_utc": "2026-10-24T19:14:00Z", "awaiting_final": 0, "final_ungraded": 0}
        out = run_page("hound", tz="UTC", **scenario(OPEN_SPECS_ONE, {}, status=quiet, queries=self.BADGE))["final"]
        self.assertEqual((out["pill"], out["pill_hidden"]), ("", [""]))
        self.assertEqual(out["last"], "Last graded 19:14")
        sc = scenario(OPEN_SPECS_ONE, {}, queries=self.BADGE, down=[STATUS])
        out = run_page("hound", tz="UTC", **sc)["final"]
        self.assertEqual((out["last"], out["pill"]), ("", ""))

    def test_a_newer_grade_reloads_the_record_and_lists_at_once(self):
        first = {"enabled": True, "last_graded_utc": "2026-10-24T19:14:00Z", "awaiting_final": 1, "final_ungraded": 0}
        second = dict(first, last_graded_utc="2026-10-24T19:41:00Z", awaiting_final=0)
        sc = scenario(OPEN_SPECS_ONE, {}, status=first, queries=self.BADGE)
        sc["switchAfter"] = {STATUS: [1, [200, second]]}
        sc["actions"] = [{"do": "fire_timers", "wait": 600}]
        run = run_page("hound", tz="UTC", **sc)
        self.assertEqual(run["final"]["last"], "Last graded 19:41")
        hound_loads = [u for u in run["gets"] if u.startswith("/hounds/closer?")]
        self.assertGreaterEqual(len(hound_loads), 2, "the model summary was fetched again after the grade")
        graded_loads = [u for u in run["gets"] if "status=graded" in u and "segment=forward" in u and "page=1" in u]
        self.assertGreaterEqual(len(graded_loads), 2, "the graded list reloaded too")


OPEN_SPECS_ONE = [("ev-1", "2026-10-24T19:30:00Z")]


class TheCssAndMarkup(unittest.TestCase):
    def test_the_new_classes_are_styled_and_hidden_means_hidden(self):
        from pathlib import Path
        css = (Path(__file__).resolve().parent.parent / "web" / "css" / "hounds.css").read_text(encoding="utf-8")
        for needle in (".hd-live", ".hd-live[hidden]", ".hd-graded__pill", '.hd-res[data-live="grading"]'):
            self.assertIn(needle, css)


if __name__ == "__main__":
    unittest.main()
