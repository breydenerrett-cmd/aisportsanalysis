"""The one-line live state on the Live board's game cards and strip, and on open member tickets (web/js/livestate.js,
web/js/live-board.js, web/js/ticket-live.js).

The page scripts run under node against the fake DOM of tests/hounds_web_harness.mjs (tests/hounds_web_runner.py), with the
network faked: the server's wording ("2nd · 8:14 · SOG 18-11 · PP WSH", "Set 2 · 3-2 · Joint serving · up a break") is printed
VERBATIM, a game whose score the board marks delayed shows no line, and a game with no line is drawn exactly as before.
"""
from __future__ import annotations

import copy
import json
import re
import unittest

from tests.hounds_web_runner import HAS_NODE, WEB, run_js, run_page
from tests.test_live_board import FIXTURE, board, hook, q
from tests.test_ticket_live_web import OPEN_QUERIES, game, scenario

NHL_LINE = "2nd · 8:14 · SOG 18-11 · PP WSH"
TENNIS_LINE = "Set 2 · 3-2 · Joint serving · up a break"
LIVE_STATE = lambda line, sport: {"line": line, "sport": sport, "as_of": "2026-10-19T23:29:40Z"}


def payload(delayed=False):
    """The fixture board with an NHL game in play (score + live_state) and the first live tennis game carrying a line."""
    data = copy.deepcopy(FIXTURE)
    hockey = next(f for f in data["families"] if f["code"] == "hockey")
    hockey["live"] = [{"event_id": "nhl-1", "league_title": "NHL", "home": "New York Rangers", "away": "Washington Capitals",
                       "start_utc": "2026-10-19T22:00:00Z", "in_play": True, "best_price_home": -120, "best_price_away": 105,
                       "observed_utc": "2026-10-19T23:28:00Z",
                       "score": {"home": 2, "away": 1, "detail": "8:14 - 2nd", "period": 2, "clock": "8:14", "completed": False,
                                 "delayed": delayed, "as_of": "2026-10-19T23:29:40Z", "source": "espn"},
                       "live_state": LIVE_STATE(NHL_LINE, "NHL")}]
    if delayed:                                           # what the board really sends when ESPN has gone quiet (allsports_view._apply_feed)
        hockey["live"][0]["score"] = {"home": None, "away": None, "detail": "Score delayed", "completed": False, "delayed": True,
                                      "as_of": None, "source": "espn"}
    tennis = next(f for f in data["families"] if f["code"] == "tennis")
    tennis["live"][0]["live_state"] = LIVE_STATE(TENNIS_LINE, "TENNIS")
    tennis["live"][0]["event_id"] = "ten-line"
    return data


def card_queries():
    return [q("nhl_line", "[data-event='nhl-1'][data-hook='live-row'] [data-hook='live-state-line']"),
            q("nhl_period", "[data-event='nhl-1'][data-hook='live-row'] [data-hook='live-period']", "count"),
            q("nhl_lines", "[data-event='nhl-1'][data-hook='live-row'] [data-hook='live-state-line']", "count"),
            q("ten_line", "[data-event='ten-line'][data-hook='live-row'] [data-hook='live-state-line']"),
            q("lines_total", hook("live-state-line"), "count"),
            q("nhl_strip", "[data-hook='live-now-card'][data-event='nhl-1'] [data-hook='live-now-detail']"),
            q("ten_strip", "[data-hook='live-now-card'][data-event='ten-line'] [data-hook='live-now-detail']"),
            q("nhl_card", "[data-event='nhl-1'][data-hook='live-row']")]


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheGameCards(unittest.TestCase):
    def test_an_nhl_card_and_a_tennis_card_print_the_servers_line_verbatim(self):
        out = board({"/sports/now": [200, payload()]}, queries=card_queries())["final"]
        self.assertEqual(out["nhl_line"], NHL_LINE)
        self.assertEqual(out["ten_line"], TENNIS_LINE)
        self.assertIn("Washington Capitals", out["nhl_card"])
        self.assertIn("New York Rangers", out["nhl_card"])

    def test_the_line_replaces_the_feeds_period_and_clock_it_does_not_repeat_them(self):
        out = board({"/sports/now": [200, payload()]}, queries=card_queries())["final"]
        self.assertEqual(out["nhl_period"], 0)                    # no second "8:14 - 2nd" beside the line
        self.assertEqual(out["nhl_lines"], 1)
        self.assertNotIn("8:14 - 2nd", out["nhl_card"])

    def test_the_now_strip_shows_the_same_line(self):
        out = board({"/sports/now": [200, payload()]}, queries=card_queries())["final"]
        self.assertEqual(out["nhl_strip"], NHL_LINE)
        self.assertEqual(out["ten_strip"], TENNIS_LINE)

    def test_a_score_marked_delayed_shows_no_line_beside_score_delayed(self):
        out = board({"/sports/now": [200, payload(delayed=True)]}, queries=card_queries() + [
            q("delayed", "[data-event='nhl-1'][data-hook='live-row'] [data-hook='live-score-delayed']")])["final"]
        self.assertEqual(out["nhl_lines"], 0)
        self.assertEqual(out["delayed"], "Score delayed")

    def test_a_game_with_no_line_is_drawn_exactly_as_before(self):
        data = payload()
        for fam in data["families"]:
            for ev in fam["live"]:
                ev.pop("live_state", None)
        out = board({"/sports/now": [200, data]}, queries=card_queries())["final"]
        self.assertEqual(out["lines_total"], 0)
        self.assertEqual(out["nhl_period"], 1)                    # the feed's own "8:14 - 2nd" is back
        before = board({"/sports/now": [200, FIXTURE]}, queries=[q("n", hook("live-state-line"), "count")])["final"]
        self.assertEqual(before["n"], 0)                           # the stock fixture has none: no new element anywhere

    def test_a_line_that_is_blank_or_not_text_is_ignored(self):
        data = payload()
        data["families"][0]["live"][0]["live_state"] = {"line": "   "}
        next(f for f in data["families"] if f["code"] == "hockey")["live"][0]["live_state"] = {"line": 7}
        out = board({"/sports/now": [200, data]}, queries=card_queries())["final"]
        self.assertEqual(out["nhl_lines"], 0)
        self.assertEqual(out["nhl_period"], 1)

    def test_the_line_never_uses_the_banned_wording(self):
        for text in (NHL_LINE, TENNIS_LINE):
            self.assertIsNone(re.search(r"(?i)\b(edge|lock|beta|new|bet|wager)\b", text), text)


@unittest.skipUnless(HAS_NODE, "node not installed")
class ThePureHelpers(unittest.TestCase):
    def js(self, body):
        return run_js('import * as L from "./livestate.js";\nimport * as T from "./ticket-live.js";\n' + body)

    def test_the_line_is_shown_only_for_a_live_game_with_a_readable_line(self):
        got = self.js('''
const ev = (extra) => Object.assign({ event_id: "e", home: "H", away: "A", live_state: { line: "2nd · 8:14" } }, extra);
console.log(JSON.stringify([
  L.liveStateLine(ev({})),
  L.liveStateLine(ev({ score: { delayed: true } })),
  L.liveStateLine(ev({ score: { completed: true } })),
  L.liveStateLine(ev({ live_state: { line: "" } })),
  L.liveStateLine(ev({ live_state: null })),
  L.liveStateLine(ev({ live_state: { line: 5 } })),
  L.liveStateLine(null),
  L.liveStateLine({ event_id: "e" }),
]));''')
        self.assertEqual(got, ["2nd · 8:14", "", "", "", "", "", "", ""])

    def test_the_strip_model_uses_the_line_for_a_live_game_only(self):
        got = self.js('''
const ev = { event_id: "e", home: "H", away: "A", score: { home: 1, away: 0, detail: "8:14 - 2nd", source: "espn" }, live_state: { line: "2nd · 8:14 · SOG 3-2" } };
const final = L.eventLiveModel(ev, { state: "final", home_score: 2, away_score: 1, detail: "Final" });
console.log(JSON.stringify([L.eventLiveModel(ev, null).detail, final.kind, final.detail,
  L.eventLiveModel(Object.assign({}, ev, { live_state: undefined }), null).detail]));''')
        self.assertEqual(got, ["2nd · 8:14 · SOG 3-2", "final", "8:14 - 2nd", "8:14 - 2nd"])      # a final game never takes the in-play line

    def test_an_open_ticket_reads_live_with_the_line_and_the_score(self):
        got = self.js('''
const now = Date.parse("2026-10-24T20:00:00Z");
const info = (extra) => Object.assign({ state: "live", away_score: 1, home_score: 0, detail: "P2", supported: true,
  live_state: { line: "2nd · 8:14 · SOG 18-11 · PP WSH", sport: "NHL" } }, extra);
console.log(JSON.stringify([T.liveView(info({}), null, now),
  T.liveView(info({ away_score: null, home_score: null }), null, now),
  T.liveView(info({ state: "upcoming", away_score: null, home_score: null, start_utc: "2026-10-24T18:00:00Z", live_state: { line: "Set 2 · 3-2 · Joint serving · up a break" } }), null, now),
  T.liveView(info({ state: "final" }), null, now),
  T.liveView(info({ state: "postponed" }), null, now),
  T.liveView(info({ state: "cancelled" }), null, now),
  T.liveView(info({ live_state: { line: "  " } }), null, now),
  T.liveView(info({ live_state: undefined }), null, now)]));''')
        self.assertEqual((got[0]["chip"], got[0]["text"]), ("LIVE", "Live 1-0 · 2nd · 8:14 · SOG 18-11 · PP WSH"))
        self.assertEqual(got[1]["text"], "Live · 2nd · 8:14 · SOG 18-11 · PP WSH")                       # no score: no invented number
        self.assertEqual((got[2]["key"], got[2]["text"]), ("live", "Live · Set 2 · 3-2 · Joint serving · up a break"))   # tennis: grader still says upcoming
        self.assertEqual(got[3]["key"], "grading")                                                         # a final game keeps its word
        self.assertEqual(got[4]["key"], "postponed")
        self.assertEqual(got[5]["key"], "cancelled")
        self.assertEqual(got[6]["text"], "Live 1-0 · P2")                                                 # a blank line changes nothing
        self.assertEqual(got[7]["text"], "Live 1-0 · P2")


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheOpenTicket(unittest.TestCase):
    SPECS = [("ev-nhl", "2026-10-24T19:30:00Z"), ("ev-plain", "2026-10-24T19:30:00Z")]

    def games(self):
        live = game("live", away_score=1, home_score=2, detail="P2 8:14")
        live["live_state"] = LIVE_STATE(NHL_LINE, "NHL")
        return {"ev-nhl": live, "ev-plain": game("live", away_score=66, home_score=61, detail="Q3 4:12")}

    def test_an_open_ticket_for_an_nhl_game_in_play_shows_the_line_and_another_sport_is_unchanged(self):
        out = run_page("hound", **scenario(self.SPECS, self.games(), queries=OPEN_QUERIES))["final"]
        self.assertEqual([t for t in out["live"] if t], [f"Live 1-2 · {NHL_LINE}", "Live 66-61 · Q3 4:12"])
        self.assertEqual(out["chips"], ["LIVE", "LIVE"])

    def test_the_payload_without_a_line_reads_exactly_as_it_did(self):
        games = self.games()
        del games["ev-nhl"]["live_state"]
        out = run_page("hound", **scenario(self.SPECS, games, queries=OPEN_QUERIES))["final"]
        self.assertEqual([t for t in out["live"] if t], ["Live 1-2 · P2 8:14", "Live 66-61 · Q3 4:12"])


class TheScripts(unittest.TestCase):
    def test_no_banned_wording_in_the_changed_scripts_code(self):
        for name in ("livestate.js", "live-board.js", "ticket-live.js"):
            text = (WEB / "js" / name).read_text(encoding="utf-8")
            text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
            text = re.sub(r"(?m)^\s*//.*$|\s//\s.*$", "", text)
            self.assertNotRegex(text, r"(?i)\bbeta\b|\bnew\b badge|\block\b", name)


if __name__ == "__main__":
    unittest.main()
