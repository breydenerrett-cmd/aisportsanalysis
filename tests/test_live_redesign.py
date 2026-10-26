"""The Live page redesign (docs/BACKLOG.md, LOW "Live page redesign"): web/live.html + web/js/live-board.js + web/js/livestate.js.

  the now strip      the games in play, one card each, with the clock, the score and the state; it follows the sport chip and hides
                     when nothing is in play. A score comes from the grader's cache (GET /hounds/live) while that is fresh, else from
                     the /sports/now row, else it is left out (eventLiveModel in web/js/livestate.js).
  the groups         one group per sport with a sticky header and its count; the live games first inside it.
  hounds on a game   the viewer's own hounds with an open ticket (avatar + the side they took), the house pack as a compact avatar row
                     and "+N more". Only OPEN tickets, only forward ones, only hounds the pack list names. A read that fails leaves
                     the card as it was.
  quieter send       "Send a hound" is a small text button, not a .btn.
  every width        no sideways scroll at 375, 390 and 1440 with the strip and the hound rows on the page.
The page script runs under node against the fake DOM of tests/hounds_web_harness.mjs; the fixture is tests/fixtures/sports_now.json.
"""
from __future__ import annotations

import http.server
import json
import re
import subprocess
import threading
import unittest

from tests.hounds_web_runner import HAS_NODE, WEB, run_js
from tests.test_live_board import FIXTURE, TOKEN_KEY, board, hook, q, strip_comments

CSS = (WEB / "css" / "live.css").read_text(encoding="utf-8")
JS = (WEB / "js" / "live-board.js").read_text(encoding="utf-8")
HTML = (WEB / "live.html").read_text(encoding="utf-8")


def ticket(hound_id, name, event, side, status="OPEN", segment="forward", market="moneyline"):
    return {"hound_id": hound_id, "hound_name": name, "event_id": event, "selection": side, "market": market, "status": status,
            "segment": segment, "result": None if status == "OPEN" else "won", "verdict": "play", "refused": False}


def member(i, name, open_bets=1, **over):
    return dict({"id": i, "name": name, "status": "running", "open_bets": open_bets, "sports": ["soccer", "tennis"]}, **over)


def pack(n):
    return [{"id": f"h-{i}", "name": f"Pack Hound {i}", "kind": "house"} for i in range(n)]


def routes(mine=None, mine_bets=None, house=None, stream=None):
    r = {}
    if mine is not None:
        r["/hounds/camp/mine"] = [200, {"dogs": mine, "count": len(mine)}]
    for hid, items in (mine_bets or {}).items():
        r[f"/hounds/{hid}/bets"] = [200, {"items": items, "page": 1, "pages": 1, "total": len(items)}]
    if house is not None:
        r["/hounds"] = [200, {"hounds": house}]
    if stream is not None:
        r["/hounds/stream"] = [200, {"items": stream, "page": 1, "pages": 1, "total": len(stream)}]
    return r


LIVE_COUNT = sum(len(f["live"]) for f in FIXTURE["families"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheNowStrip(unittest.TestCase):
    def test_every_game_in_play_has_a_card_with_its_state(self):
        out = board(queries=[q("cards", hook("live-now-card"), "count"), q("hidden", hook("live-now"), "hidden"), q("n", hook("live-now-count")),
                             q("states", hook("live-now-state"), "texts"), q("card", "[data-hook='live-now-card'][data-event='soc-1']"),
                             q("href", "[data-hook='live-now-card'][data-event='soc-1']", "attr", attr="href")])
        f = out["final"]
        self.assertFalse(f["hidden"])
        self.assertEqual((f["cards"], f["n"]), (LIVE_COUNT, str(LIVE_COUNT)))
        self.assertEqual(set(f["states"]), {"Live"})
        for part in ("Soccer", "Fulham", "0", "Brighton and Hove Albion", "1", "62'"):
            self.assertIn(part, f["card"])
        self.assertEqual(f["href"], "#lv-ev-soc-1")                                       # a card jumps to its game

    def test_the_grader_cache_beats_the_row_score_and_a_quiet_feed_is_ignored(self):
        live = {"soc-1": {"state": "live", "home_score": 2, "away_score": 1, "detail": "70'"},
                "soc-3": {"state": "unknown", "home_score": 9, "away_score": 9, "detail": "stale"}}
        out = board({"/hounds/live": [200, {"games": live}]}, queries=[
            q("fresh", "[data-hook='live-now-card'][data-event='soc-1']"), q("quiet", "[data-hook='live-now-card'][data-event='soc-3']")])
        self.assertIn("70'", out["final"]["fresh"])
        self.assertNotIn("stale", out["final"]["quiet"])
        self.assertNotIn("9", out["final"]["quiet"].replace("Soccer", ""))
        self.assertEqual([g for g in out["gets"] if "/hounds/live" in g][0].split("?ids=")[1].split(",")[0], "soc-1")

    def test_a_final_game_says_final_and_a_failed_read_keeps_the_strip(self):
        out = board({"/hounds/live": [200, {"games": {"soc-1": {"state": "final", "home_score": 3, "away_score": 1, "detail": "FT"}}}]},
                    queries=[q("state", "[data-hook='live-now-card'][data-event='soc-1'] [data-hook='live-now-state']")])
        self.assertEqual(out["final"]["state"], "Final")
        out = board({"/hounds/live": [503, {}]}, queries=[q("cards", hook("live-now-card"), "count")])
        self.assertEqual(out["final"]["cards"], LIVE_COUNT)                               # the /sports/now rows carry it alone

    def test_it_follows_the_sport_chip_and_hides_when_nothing_is_in_play(self):
        out = board(actions=[dict(do="click", sel="[data-hook='live-chip'][data-family='tennis']", label="t", wait=60)],
                    queries=[q("cards", hook("live-now-card"), "count")])
        self.assertEqual(out["final"]["cards"], 4)
        out = board(actions=[dict(do="click", sel="[data-hook='live-chip'][data-family='baseball']", label="b", wait=60)],
                    queries=[q("hidden", hook("live-now"), "hidden"), q("cards", hook("live-now-card"), "count")])
        self.assertTrue(out["final"]["hidden"])
        self.assertEqual(out["final"]["cards"], 0)

    def test_the_clock_and_score_model(self):
        got = run_js('''
import { eventLiveModel } from "./livestate.js";
const ev = { event_id: "e", home: "H", away: "A", score: { home: 1, away: 0, detail: "Live" } };
console.log(JSON.stringify([
  eventLiveModel(ev, null),
  eventLiveModel(ev, { state: "live", home_score: 4, away_score: 2, detail: "Q3 4:12" }),
  eventLiveModel(ev, { state: "unknown", home_score: 4, away_score: 2, detail: "x" }),
  eventLiveModel({ event_id: "e", home: "H", away: "A", score: "0-0, 31'" }, null),
  eventLiveModel({ event_id: "e", home: "H", away: "A" }, null),
  eventLiveModel(ev, { state: "postponed" }),
  eventLiveModel(null, null)]));''')
        row, cache, quiet, text, bare, off, none = got
        self.assertEqual((row["away"]["score"], row["home"]["score"], row["detail"], row["label"]), (0, 1, "", "LIVE"))     # a bare "Live" is not a clock
        self.assertEqual((cache["away"]["score"], cache["home"]["score"], cache["detail"]), (2, 4, "Q3 4:12"))
        self.assertEqual((quiet["away"]["score"], quiet["home"]["score"]), (0, 1))                                          # stale cache says nothing
        self.assertEqual((text["away"]["score"], text["detail"]), (None, "0-0, 31'"))
        self.assertEqual((bare["away"]["score"], bare["home"]["score"], bare["detail"]), (None, None, ""))               # never invented
        self.assertEqual((off["kind"], off["label"]), ("off", "POSTPONED"))
        self.assertIsNone(none)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheSportGroups(unittest.TestCase):
    def test_each_group_has_a_header_and_the_header_is_sticky(self):
        out = board(queries=[q("heads", hook("live-sport-head"), "count"), q("groups", hook("live-sport"), "count"),
                             q("lists", hook("live-sport-list"), "count")])
        self.assertEqual(out["final"]["heads"], out["final"]["groups"])
        self.assertEqual(out["final"]["lists"], out["final"]["groups"])
        rule = re.search(r"\.lv-sport__head \{([^}]*)\}", CSS).group(1)
        self.assertIn("position: sticky", rule)
        self.assertIn("var(--lv-bar-h)", rule)                                              # it sticks under the chip bar, not behind it

    def test_the_all_view_caps_a_group_and_the_live_games_are_never_hidden(self):
        data = json.loads(json.dumps(FIXTURE))
        tennis = next(f for f in data["families"] if f["code"] == "tennis")
        tennis["upcoming_24h"] = [dict(tennis["upcoming_24h"][0], event_id=f"t-{i}", start_utc=f"2026-10-20T{i + 1:02d}:00:00Z") for i in range(12)]
        out = board({"/sports/now": [200, data]}, queries=[
            q("rows", "[data-hook='live-sport'][data-family='tennis'] [data-hook='live-row']", "count"),
            q("live", "[data-hook='live-sport'][data-family='tennis'] [data-hook='live-row'][data-live='true']", "count"),
            q("more", "[data-hook='live-sport-more'][data-family='tennis']"), q("head", "[data-hook='live-sport'][data-family='tennis'] [data-hook='live-sport-count']")])
        f = out["final"]
        self.assertEqual((f["rows"], f["live"]), (8, 4))
        self.assertEqual(f["more"], "Show 8 more Tennis")
        self.assertEqual(f["head"], "16 games · 4 live")
        out = board({"/sports/now": [200, data]}, actions=[dict(do="click", sel="[data-hook='live-sport-more'][data-family='tennis']", label="m", wait=60)],
                    queries=[q("rows", "[data-hook='live-sport'][data-family='tennis'] [data-hook='live-row']", "count")])
        self.assertEqual(out["final"]["rows"], 16)

    def test_a_card_has_a_quiet_send_button_not_a_big_one(self):
        out = board(queries=[q("cls", "[data-event='soc-4'] [data-hook='live-send']", "attr", attr="class"), q("text", "[data-event='soc-4'] [data-hook='live-send']")])
        self.assertEqual(out["final"]["cls"], "lv-send")                                    # no .btn: it is a small text button
        self.assertEqual(out["final"]["text"], "Send a hound")
        rule = re.search(r"\n\.lv-send \{([^}]*)\}", CSS).group(1)
        self.assertIn("background: transparent", rule)

    def test_the_headline_copy_has_no_banned_words(self):
        out = board()
        self.assertNotRegex(out["text"], r"(?i)\bdogs?\b|\bbeta\b")
        body = re.sub(r"\$\{[^}]*\}", "", strip_comments(JS + HTML))       # a ${variable} is not words
        self.assertNotRegex(body, r"""(?i)(text|title|aria-label)[:=]\s*[`"'][^`"']*\b(dogs?|beta)\b""")
        self.assertIn("21+", HTML)


@unittest.skipUnless(HAS_NODE, "node not installed")
class HoundsOnAGame(unittest.TestCase):
    MINE = [member("u-1", "Plus Money Pete", 2), member("u-2", "Chalk Charlie"), member("u-3", "Idle Ida", 0), member("u-4", "Old Rex", 1, status="retired")]

    def member_board(self, **kw):
        mine_bets = {"u-1": [ticket("u-1", "Plus Money Pete", "soc-4", "Seattle Sounders FC"), ticket("u-1", "Plus Money Pete", "soc-4", "Over 2.5", market="totals"),
                             ticket("u-1", "Plus Money Pete", "soc-1", "Fulham", status="GRADED")],
                     "u-2": [ticket("u-2", "Chalk Charlie", "soc-1", "Brighton and Hove Albion"), ticket("u-2", "Chalk Charlie", "soc-4", "Old board", segment="replay")]}
        r = routes(mine=self.MINE, mine_bets=mine_bets, house=[], stream=[])
        r.update(kw)
        return board(r, stored={TOKEN_KEY: "tok"}, queries=[
            q("mine4", "[data-event='soc-4'] [data-hook='live-mine']", "attrs", attr="aria-label"), q("mine1", "[data-event='soc-1'] [data-hook='live-mine']", "attrs", attr="aria-label"),
            q("row4", "[data-event='soc-4'][data-hook='live-row'] [data-hook='live-mine-row']"),
            q("faces", "[data-event='soc-4'] [data-hook='live-mine'] svg", "count"), q("other", "[data-event='soc-2'] [data-hook='live-hounds']", "count"),
            q("asked", hook("live-hounds"), "count")])

    def test_my_hound_shows_with_its_avatar_and_its_side_only_for_open_forward_tickets(self):
        f = self.member_board()["final"]
        self.assertEqual(f["mine4"], ["Plus Money Pete backs Seattle Sounders FC · Over 2.5"])   # one chip per hound, its sides joined
        self.assertEqual(f["mine1"], ["Chalk Charlie backs Brighton and Hove Albion"])                # the graded Fulham ticket and the replay row are left out
        self.assertIn("Seattle Sounders FC", f["row4"])
        self.assertGreaterEqual(f["faces"], 1)                                                         # the avatar is the hound's drawn face
        self.assertEqual(f["other"], 0)                                                                # a game nobody is on has no row

    def test_only_hounds_that_say_they_have_open_tickets_are_asked_and_a_retired_one_is_not(self):
        out = self.member_board()
        asked = sorted(g.split("/")[2] for g in out["gets"] if g.endswith("&status=open") or "status=open" in g)
        self.assertEqual(asked, ["u-1", "u-2"])

    def test_the_house_pack_is_a_compact_avatar_row_with_a_more_count(self):
        stream = [ticket(f"h-{i}", f"Pack Hound {i}", "soc-4", "Seattle Sounders FC") for i in range(7)]
        stream += [ticket("h-0", "Pack Hound 0", "soc-1", "Fulham", status="GRADED"), ticket("m-9", "Somebody's Hound", "soc-4", "Portland Timbers"),
                   ticket("h-1", "Pack Hound 1", "soc-2", "Club America", segment="replay")]
        out = board(routes(house=pack(7), stream=stream), queries=[
            q("faces", "[data-event='soc-4'] [data-hook='live-pack-face']", "count"), q("svgs", "[data-event='soc-4'] [data-hook='live-pack-face'] svg", "count"),
            q("more", "[data-event='soc-4'] [data-hook='live-pack-more']"), q("label", "[data-event='soc-4'] [data-hook='live-pack']", "attr", attr="aria-label"),
            q("none1", "[data-event='soc-1'] [data-hook='live-pack']", "count"), q("none2", "[data-event='soc-2'] [data-hook='live-pack']", "count"),
            q("mine", hook("live-mine"), "count")])
        f = out["final"]
        self.assertEqual(f["faces"], 4)
        self.assertEqual(f["svgs"], 4)
        self.assertEqual(f["more"], "+3 more")
        self.assertIn("Pack Hound 0, Pack Hound 1, Pack Hound 2, Pack Hound 3 and 3 more", f["label"])
        self.assertEqual((f["none1"], f["none2"]), (0, 0))        # a graded ticket and a replay row are not "on the game"
        self.assertEqual(f["mine"], 0)                            # a visitor has no hounds of their own
        self.assertFalse([g for g in out["gets"] if "/hounds/camp/mine" in g])

    def test_a_pack_that_cannot_be_listed_or_a_stream_that_fails_draws_nothing(self):
        stream = [ticket("h-0", "Pack Hound 0", "soc-4", "Seattle Sounders FC")]
        for r in (routes(stream=stream), routes(house=pack(1))):                                   # no pack list / no stream: 404
            out = board(r, queries=[q("n", hook("live-hounds"), "count"), q("rows", hook("live-row"), "count")])
            self.assertEqual(out["final"]["n"], 0)
            self.assertGreater(out["final"]["rows"], 10)                                           # the board itself is untouched

    def test_mine_and_pack_sit_together_and_a_refresh_keeps_them(self):
        stream = [ticket("h-0", "Pack Hound 0", "soc-4", "Seattle Sounders FC")]
        out2 = board(dict(routes(mine=self.MINE, mine_bets={"u-1": [ticket("u-1", "Plus Money Pete", "soc-4", "Seattle Sounders FC")]}, house=pack(1), stream=stream)),
                     stored={TOKEN_KEY: "tok"}, actions=[dict(do="fire_timers", label="tick", wait=150)], queries=[
                         q("mine", "[data-event='soc-4'] [data-hook='live-mine']", "count"), q("pack", "[data-event='soc-4'] [data-hook='live-pack-face']", "count")])
        self.assertEqual((out2["final"]["mine"], out2["final"]["pack"]), (1, 1))

    def test_a_mine_row_beyond_three_says_how_many_more(self):
        dogs = [member(f"u-{i}", f"Hound {i}") for i in range(5)]
        bets = {d["id"]: [ticket(d["id"], d["name"], "soc-4", "Seattle Sounders FC")] for d in dogs}
        out = board(routes(mine=dogs, mine_bets=bets, house=[], stream=[]), stored={TOKEN_KEY: "tok"}, queries=[
            q("chips", "[data-event='soc-4'] [data-hook='live-mine']", "count"), q("more", "[data-event='soc-4'] [data-hook='live-mine-more']")])
        self.assertEqual((out["final"]["chips"], out["final"]["more"]), (3, "+2 more"))


try:
    from tests.test_no_horizontal_overflow import CHROME, HERE, make_handler
except Exception:                                      # pragma: no cover
    CHROME = None


@unittest.skipUnless(HAS_NODE and CHROME, "node and a Chrome/Chromium binary are needed")
class TheLivePageFitsEveryWidth(unittest.TestCase):
    WIDTHS = (375, 390, 1440)

    @classmethod
    def setUpClass(cls):
        from tests import hounds_web_fixtures as F
        api = {k: (s, b) for k, (s, b) in F.routes().items()}
        api["/sports/now"] = (200, FIXTURE)
        long = "The Extraordinarily Long-Named Hound Of Somewhere Far Away"
        mine = [member("u-1", long, 2)]
        events = [ev["event_id"] for f in FIXTURE["families"] for ev in f["live"] + f["upcoming_24h"]]
        api["/hounds/camp/mine"] = (200, {"dogs": mine, "count": 1})
        api["/hounds/u-1/bets"] = (200, {"items": [ticket("u-1", long, e, "The Extraordinarily Long-Named Side To Win Outright") for e in events[:6]]})
        api["/hounds"] = (200, {"hounds": pack(9)})
        api["/hounds/stream"] = (200, {"items": [ticket(f"h-{i}", f"Pack Hound {i}", e, "Side") for i in range(9) for e in events[:8]]})
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_handler(api))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.pages = ["/web/live.html#signed", "/web/live.html?sport=soccer#signed"]
        proc = subprocess.run(["node", str(HERE / "overflow_widths.mjs"), CHROME, base, ",".join(str(w) for w in cls.WIDTHS)] + cls.pages,
                              capture_output=True, text=True, encoding="utf-8", timeout=300)
        lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("[")]
        if proc.returncode != 0 or not lines:
            raise AssertionError(f"overflow script failed ({proc.returncode}): {proc.stderr[-1500:]}")
        cls.results = json.loads(lines[-1])

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_nothing_scrolls_sideways_at_375_390_and_1440(self):
        self.assertEqual(len(self.results), len(self.WIDTHS) * len(self.pages))
        self.assertEqual({r["iw"] for r in self.results}, set(self.WIDTHS))
        for r in self.results:
            self.assertGreater(r["h"], 600, f"{r['path']} rendered almost nothing")
        bad = [r for r in self.results if r["sw"] > r["iw"] + 1]
        self.assertEqual(bad, [], "wider than the screen: " + json.dumps(bad, indent=1))


if __name__ == "__main__":
    unittest.main()
