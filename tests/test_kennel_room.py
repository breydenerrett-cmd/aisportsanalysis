"""The Kennel Room: real hound state -> a character state (web/js/room-adapter.js), and the room drawn from it (room-scene.js, room.html, the fold
on kennel.html). docs/design/KENNEL_ROOM.md is the state table; every row of it has a fixture here.

  ADAPTER   fixtures -> expected states under node (the pure module, no DOM): pending / live, just won, just lost, scouting, naps, overnight, buried,
            retired, training, the crown, the Trained badge, the -200 rule, the recent-window edges, the estimated settle time.
  RENDER    room.html and the kennel fold, run for real in the node harness's fake DOM: one hound element per hound, the state on each, the text escaped,
            no "undefined" / "NaN" / "null" anywhere, every tap target pointing where the brief says, polling paused while the tab is hidden.
  STATIC    footer compliance once, no inline script, no Bet Check, no profit or edge wording, every animation inside prefers-reduced-motion.

Skipped without node where a page is run; the static checks need none.
"""

from __future__ import annotations

import json
import re
import unittest

from tests.hounds_web_runner import HAS_NODE, WEB, run_js, run_page

NOW = "2026-10-20T20:00:00Z"          # 4:00 PM US Eastern
NOW_MS = 1792526400000                 # Date.parse(NOW)
BAD_TEXT = re.compile(r"undefined|NaN|\bnull\b|\[object|Infinity")
SIGNED = dict(stored={"aisportsanalysis.invite_token": "tok"})


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


_BASE = [None]          # None = NOW above; the real-browser check points it at the real clock


def iso(minutes: float) -> str:
    """An instant `minutes` from NOW (or from the real clock inside `live_clock()`), as the API writes it."""
    import datetime as dt
    base = _BASE[0] or dt.datetime(2026, 10, 20, 20, 0, 0, tzinfo=dt.timezone.utc)
    return (base + dt.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


class live_clock:
    def __enter__(self):
        import datetime as dt
        _BASE[0] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)

    def __exit__(self, *exc):
        _BASE[0] = None


def hound(hid="a", name="Alpha", wins=0, losses=0, units=None, open_bets=0, **over):
    out = {"id": hid, "name": name, "kind": "house", "status": "running", "sports": ["mlb"], "tagline": "", "rule_text": "",
           "record": {"bets": wins + losses, "wins": wins, "losses": losses, "pushes": 0, "units_average_price": units},
           "open_bets": open_bets, "settled": wins + losses, "retired": None}
    out.update(over)
    return out


def open_bet(hid="a", selection="Celtics to win", price=130, start=90, market="h2h", **over):
    out = {"hound_id": hid, "status": "OPEN", "result": None, "segment": "forward", "selection": selection, "market": market, "price": price,
           "start_utc": iso(start), "date": "2026-10-20"}
    out.update(over)
    return out


def graded_bet(hid="a", result="win", units=1.3, ago=30, stamped=True, **over):
    out = {"hound_id": hid, "status": "GRADED", "result": result, "units": units, "segment": "forward", "selection": "Yankees to win", "market": "h2h",
           "price": 120, "start_utc": iso(-ago - 180), "date": "2026-10-20"}
    if stamped:
        out["graded_utc"] = iso(-ago)
    out.update(over)
    return out


def room(hounds, bets=None, board=None, hour=15, headstones=0, scope="house", **opts):
    """The adapter's output for one scenario, from node."""
    payload = {"input": {"scope": scope, "hounds": hounds, "bets": bets or [], "board": board, "headstones": headstones},
               "opts": dict({"now": NOW_MS, "localHour": hour}, **opts)}
    src = ('import { build } from "./room-adapter.js";\n'
           f"const p = {json.dumps(payload)};\n"
           "const m = build(p.input, p.opts);\n"
           "for (const c of m.characters) delete c.hound;\n"
           "console.log(JSON.stringify(m));\n")
    return run_js(src)


def one(out, hid="a"):
    return next(c for c in out["characters"] if c["id"] == hid)


MLB = {"counts": {"MLB": 4}, "total": 4}


def read(name):
    return (WEB / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------------------------------
# the state table
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class StateTable(unittest.TestCase):
    def test_an_open_pick_puts_the_hound_at_its_desk_with_the_pick_in_a_bubble(self):
        c = one(room([hound(open_bets=1)], [open_bet()], MLB))
        self.assertEqual((c["state"], c["zone"], c["pose"], c["label"]), ("pending", "desk", "thinking", "At its desk"))
        self.assertEqual(c["bubble"]["text"], "Celtics ML +130 · 1u")
        self.assertIn("first starts in 1h 30m", c["detail"])
        self.assertFalse(c["live"])

    def test_a_game_that_has_started_is_live_and_says_so(self):
        c = one(room([hound(open_bets=1)], [open_bet(start=-20)], MLB))
        self.assertEqual((c["state"], c["label"], c["live"]), ("pending", "Game live", True))
        self.assertIn("a game is live", c["detail"])

    def test_the_bubble_names_the_soonest_pick_and_counts_the_rest(self):
        bets = [open_bet(selection="Over 8.5", market="total", price=-105, start=240), open_bet(selection="Red Sox to win", price=115, start=60),
                open_bet(selection="Rays to win", price=-110, start=300)]
        c = one(room([hound(open_bets=3)], bets, MLB))
        self.assertEqual(c["bubble"]["text"], "Red Sox ML +115 · 1u · +2 more")
        self.assertEqual(c["openCount"], 3)

    def test_a_stake_of_two_units_shows_two_units(self):
        c = one(room([hound(open_bets=1)], [open_bet(stake=2)], MLB))
        self.assertEqual(c["bubble"]["text"], "Celtics ML +130 · 2u")

    def test_the_open_count_alone_is_enough_when_the_ticket_rows_were_not_read(self):
        c = one(room([hound(open_bets=2)], [], MLB))
        self.assertEqual((c["state"], c["bubble"]["text"]), ("pending", "2 open tickets"))

    def test_a_pick_priced_minus_200_or_worse_is_never_put_in_a_bubble(self):
        for price in (-200, -250):
            c = one(room([hound(open_bets=1)], [open_bet(price=price)], MLB))
            self.assertEqual((c["state"], c["bubble"]["text"], c["bubble"]["suppressed"]), ("pending", "Open ticket", True), price)
        c = one(room([hound(open_bets=1)], [open_bet(price=-199)], MLB))
        self.assertEqual(c["bubble"]["text"], "Celtics ML -199 · 1u")
        c = one(room([hound(open_bets=1)], [open_bet(price=-180, beyond_cap=True)], MLB))          # the server's own "-200 or worse" flag
        self.assertTrue(c["bubble"]["suppressed"])

    def test_a_replay_or_refused_row_is_not_an_open_pick(self):
        bets = [open_bet(segment="replay"), open_bet(refused=True)]
        self.assertEqual(one(room([hound()], bets, MLB))["state"], "scouting")

    def test_just_won_jumps_with_the_net_units_floating_up(self):
        c = one(room([hound(wins=3, units=2.0)], [graded_bet(units=1.3, ago=30)], MLB))
        self.assertEqual((c["state"], c["zone"], c["pose"], c["burst"]), ("won", "desk", "celebrate", "+1.3u"))
        self.assertEqual(c["lastSettle"]["wins"], 1)

    def test_just_lost_gets_the_rain_cloud_and_walks_to_the_water_bowl(self):
        c = one(room([hound(losses=2, units=-2.0)], [graded_bet(result="loss", units=-1, ago=45)], MLB))
        self.assertEqual((c["state"], c["zone"], c["pose"], c["burst"]), ("lost", "bowl", "sad", "-1u"))

    def test_two_results_in_the_window_net_out(self):
        bets = [graded_bet(units=1.3, ago=60), graded_bet(result="loss", units=-1, ago=20)]
        c = one(room([hound(wins=1, losses=1, units=0.3)], bets, MLB))
        self.assertEqual((c["state"], c["burst"]), ("won", "+0.3u"))
        self.assertEqual((c["lastSettle"]["wins"], c["lastSettle"]["losses"]), (1, 1))
        flat = [graded_bet(units=1, ago=60), graded_bet(result="loss", units=-1, ago=20)]
        self.assertNotIn(one(room([hound()], flat, MLB))["state"], ("won", "lost"))

    def test_the_recent_window_has_edges(self):
        inside = one(room([hound(wins=1)], [graded_bet(ago=239)], MLB))
        outside = one(room([hound(wins=1)], [graded_bet(ago=241)], MLB))
        self.assertEqual(inside["state"], "won")
        self.assertEqual(outside["state"], "scouting")
        self.assertEqual(one(room([hound(wins=1)], [graded_bet(ago=100)], MLB, recentHours=1))["state"], "scouting")

    def test_a_ticket_with_no_graded_stamp_is_dated_by_its_first_pitch_and_says_so(self):
        # first pitch 3h30m ago: the game ended about 30 minutes ago
        c = one(room([hound(wins=1)], [graded_bet(ago=30, stamped=False)], MLB))
        self.assertEqual(c["state"], "won")
        self.assertTrue(c["lastSettle"]["estimated"])
        # a ticket with neither a stamp nor a start time is never dated
        bare = graded_bet(stamped=False)
        del bare["start_utc"]
        self.assertEqual(one(room([hound(wins=1)], [bare], MLB))["state"], "scouting")

    def test_a_push_or_void_is_not_a_celebration(self):
        c = one(room([hound()], [graded_bet(result="push", units=0, ago=20), graded_bet(result="void", units=0, ago=20)], MLB))
        self.assertEqual(c["state"], "scouting")

    def test_an_open_pick_beats_a_recent_result_and_the_result_stays_on_the_card(self):
        c = one(room([hound(open_bets=1, wins=1)], [open_bet(), graded_bet(ago=20)], MLB))
        self.assertEqual(c["state"], "pending")
        self.assertEqual(c["lastSettle"]["net"], 1.3)

    def test_games_on_the_board_in_its_sports_and_no_pick_means_scouting(self):
        c = one(room([hound()], [], MLB))
        self.assertEqual((c["state"], c["zone"], c["label"]), ("scouting", "floor", "Scanning the board"))
        self.assertEqual(c["games"], 4)
        self.assertIn("4 games left on today's board", c["detail"])

    def test_scouting_needs_a_game_in_the_hounds_own_sports(self):
        nba = hound("n", "Nova", sports=["nba"])
        out = room([nba, hound("m", "Mel", sports=["mlb"])], [], MLB)
        self.assertEqual(one(out, "n")["state"], "nap")
        self.assertEqual(one(out, "n")["label"], "No games left")
        self.assertEqual(one(out, "m")["state"], "scouting")

    def test_a_hound_that_bets_every_sport_scans_the_whole_board(self):
        for sports in (["dog_menu"], ["any"], []):
            c = one(room([hound(sports=sports)], [], {"counts": {"NBA": 2, "NHL": 1}, "total": 3}))
            self.assertEqual((c["state"], c["games"]), ("scouting", 3), sports)

    def test_no_games_left_naps_in_the_bed(self):
        c = one(room([hound()], [], {"counts": {"MLB": 0}, "total": 0}))
        self.assertEqual((c["state"], c["zone"], c["label"]), ("nap", "bed", "No games left"))

    def test_done_for_today_when_it_bet_today_and_the_board_is_empty(self):
        c = one(room([hound(wins=1)], [graded_bet(ago=600, date="2026-10-20")], {"counts": {"MLB": 0}, "total": 0}))
        self.assertEqual((c["state"], c["label"]), ("nap", "Done for today"))

    def test_an_unread_board_never_claims_scouting(self):
        c = one(room([hound()], [], None))
        self.assertEqual((c["state"], c["label"]), ("nap", "No open pick"))

    def test_overnight_the_idle_hounds_are_asleep_in_the_viewers_local_night(self):
        for hour in (23, 0, 3, 5):
            out = room([hound("a"), hound("b", sports=["nba"])], [], MLB, hour=hour)
            self.assertEqual({one(out, i)["state"] for i in "ab"}, {"asleep"}, hour)
        for hour in (6, 12, 22):
            self.assertEqual(one(room([hound()], [], MLB, hour=hour))["state"], "scouting", hour)

    def test_a_pick_still_open_after_midnight_keeps_its_hound_at_the_desk(self):
        c = one(room([hound(open_bets=1)], [open_bet()], MLB, hour=1))
        self.assertEqual(c["state"], "pending")

    def test_idle_not_started_and_resting_hounds_nap_with_their_own_words(self):
        out = room([hound("a", status="benched"), hound("b", status="not_started"), hound("c", status="paused")], [], MLB)
        self.assertEqual([(one(out, i)["state"], one(out, i)["label"]) for i in "abc"], [("nap", "Idle"), ("nap", "Not started"), ("nap", "Resting")])

    def test_a_buried_hound_is_not_in_the_room_and_leaves_a_headstone(self):
        out = room([hound("a"), hound("z", name="Zed", status="buried")], [], MLB, headstones=2)
        self.assertEqual([c["id"] for c in out["characters"]], ["a"])
        self.assertEqual(out["headstones"], 2)
        self.assertEqual(room([hound("z", status="buried")], [], MLB)["headstones"], 1)       # a buried row alone is still one stone

    def test_the_graveyard_list_may_arrive_as_headstone_rows(self):
        out = room([hound("a")], [], MLB, headstones=[{"id": "x"}, {"id": "y"}, {"id": "w"}])
        self.assertEqual(out["headstones"], 3)

    def test_a_retired_model_has_left_the_room(self):
        out = room([hound("a"), hound("r", status="retired"), hound("s", retired={"reason": "stopped by its rule"}), hound("t", retired=True)], [], MLB)
        self.assertEqual([c["id"] for c in out["characters"]], ["a"])

    def test_training_is_the_gym_with_a_whistle(self):
        out = room([hound("a", trained_times=1, coached_from="a-v1", status="running"), hound("b", status="training"), hound("c", trained_times=1, coached_from="c-v1")],
                   [open_bet("c")], MLB)
        self.assertEqual((one(out, "a")["state"], one(out, "a")["zone"], one(out, "a")["label"]), ("training", "gym", "At the gym"))
        self.assertEqual(one(out, "b")["state"], "training")
        self.assertEqual(one(out, "c")["state"], "pending")            # it has bet since: no longer fresh from training
        self.assertIn("record starts now", one(out, "a")["detail"])

    def test_a_trained_hound_with_settled_bets_is_not_at_the_gym(self):
        c = one(room([hound(wins=2, trained_times=2, coached_from="x")], [], MLB))
        self.assertEqual(c["state"], "scouting")
        self.assertEqual(c["trained"], 2)

    def test_the_crown_goes_to_the_units_leader_with_enough_settled_bets(self):
        hs = [hound("a", "Alpha", wins=8, losses=6, units=2.5), hound("b", "Bravo", wins=9, losses=5, units=4.1),
              hound("c", "Cleo", wins=2, losses=0, units=9.9), hound("d", "Dune", wins=5, losses=9, units=-3)]
        out = room(hs, [], MLB)
        self.assertEqual(out["leaderId"], "b")
        self.assertEqual([c["id"] for c in out["characters"] if c["crown"]], ["b"])
        self.assertEqual([r["id"] for r in out["whiteboard"]], ["b", "a"])           # Cleo has 2 settled: not ranked, not on the board

    def test_no_crown_when_the_leader_is_not_above_zero_or_nobody_is_ranked(self):
        self.assertIsNone(room([hound("a", wins=4, losses=8, units=-1.5)], [], MLB)["leaderId"])
        self.assertIsNone(room([hound("a", wins=3, losses=1, units=5)], [], MLB)["leaderId"])
        self.assertEqual(room([hound("a", wins=3, losses=1, units=5)], [], MLB, minRanked=4)["leaderId"], "a")

    def test_the_trained_badge_count_comes_through(self):
        c = one(room([hound(wins=3, trained_times=3)], [], MLB))
        self.assertEqual(c["trained"], 3)

    def test_the_ticker_counts_real_tickets_and_games(self):
        out = room([hound("a", open_bets=2), hound("b", open_bets=1)], [open_bet("a", start=-5), open_bet("a", start=200), open_bet("b")], MLB)
        self.assertEqual(out["ticker"], {"open": 3, "live": 1, "games": 4, "hounds": 2})
        self.assertEqual(room([hound()], [], None)["ticker"]["games"], None)

    def test_a_kennel_scope_marks_every_hound_as_mine_and_links_its_page(self):
        out = room([hound("u-1", kind="user")], [], MLB, scope="kennel")
        c = one(out, "u-1")
        self.assertTrue(c["mine"])
        self.assertEqual(c["href"], "hound.html?id=u-1")
        self.assertFalse(room([hound("a")], [], MLB)["characters"][0]["mine"])

    def test_the_flat_bet_list_and_the_two_maps_are_the_same_input(self):
        flat = room([hound(open_bets=1)], [open_bet()], MLB)
        payload = {"input": {"scope": "house", "hounds": [hound(open_bets=1)], "openBets": {"a": [open_bet()]}, "board": MLB},
                   "opts": {"now": NOW_MS, "localHour": 15}}
        src = ('import { build } from "./room-adapter.js";\n' f"const p = {json.dumps(payload)};\n"
               "const m = build(p.input, p.opts); for (const c of m.characters) delete c.hound; console.log(JSON.stringify(m));\n")
        self.assertEqual(run_js(src), flat)

    def test_garbage_in_is_handled_without_a_crash_or_a_made_up_state(self):
        src = ('import { build } from "./room-adapter.js";\n'
               "const out = [build(null), build({}), build({hounds: [null, 3, {}, {id: 'x'}, {id: 'x'}]}), build({hounds: [{id: 'y', name: 7, record: 'x', sports: 'mlb', open_bets: 'two'}], board: {counts: 5}})];\n"
               "console.log(JSON.stringify(out.map(m => m.characters.map(c => [c.id, c.state, c.name]))));\n")
        out = run_js(src)
        self.assertEqual(out[0], [])
        self.assertEqual(out[2], [["x", "nap", "x"]])
        self.assertEqual(out[3][0][:2], ["y", "nap"])
        self.assertNotRegex(json.dumps(out), r"NaN|undefined")

    def test_formatters(self):
        src = ('import { fmtUnits, fmtPrice, fmtStake, inText, shortPick } from "./room-adapter.js";\n'
               "console.log(JSON.stringify([fmtUnits(1.3), fmtUnits(-1), fmtUnits(0.83), fmtUnits(0), fmtUnits(NaN), fmtPrice(130), fmtPrice(-115), fmtPrice(50), fmtPrice(null),"
               " fmtStake(1), fmtStake(0.5), fmtStake(null), inText(5400000), inText(2100000), inText(-5),"
               " shortPick({selection: 'Yankees to win', market: 'h2h'}), shortPick({selection: 'Over 8.5', market: 'total'}), shortPick({selection: 'Celtics', market: 'moneyline'}),"
               " shortPick({selection: 'Red Sox', market: 'spread', line: -1.5}), shortPick({})]));\n")
        self.assertEqual(run_js(src), ["+1.3u", "-1u", "+0.83u", "0u", "", "+130", "-115", "", "", "1u", "0.5u", "1u", "1h 30m", "35m", "now",
                                       "Yankees ML", "Over 8.5", "Celtics ML", "Red Sox -1.5", ""])


# ---------------------------------------------------------------------------------------------------
# the room, rendered (the node harness's fake DOM)
# ---------------------------------------------------------------------------------------------------

def routes_house(extra=None):
    hounds = [hound("closer", "Closer", wins=17, losses=14, units=2.69, open_bets=2, trained_times=0),
              hound("steamer", "Steamer", wins=3, losses=1, units=1.3),
              hound("almanac", "Almanac", wins=1, losses=5, units=-3),
              hound("sleeper", "Sleeper"),
              hound("<img src=x onerror=alert(1)>", "<img src=x onerror=alert(1)>", wins=0, losses=0),
              hound("rusty", "Rusty", kind="user", wins=1, units=1)]
    stream = [dict(open_bet("closer", "Yankees to win", price=135, start=90), hound_name="Closer"),
              dict(open_bet("closer", "Over 8.5", market="total", price=-105, start=200), hound_name="Closer"),
              dict(graded_bet("steamer", "win", 1.3, ago=25), hound_name="Steamer"),
              dict(graded_bet("almanac", "loss", -1, ago=50), hound_name="Almanac")]
    out = {"/hounds": [200, {"as_of": "2026-10-20", "hounds": hounds, "season": {"id": "s2", "min_ranked_bets": 10}}],
           "/hounds/stream": [200, {"items": stream, "page": 1, "total": len(stream)}],
           "/hounds/graveyard": [200, {"hounds": [], "headstones": [{"id": "x"}, {"id": "y"}]}],
           "/sports/now": [200, {"generated_utc": NOW, "families": [{"code": "MLB", "label": "MLB", "live": [{"event_id": "e1"}], "upcoming_24h": [
               {"event_id": "e2", "start_utc": iso(120)}, {"event_id": "e3", "start_utc": iso(60 * 20)}]}]}]}
    out.update(extra or {})
    return out


@unittest.skipUnless(HAS_NODE, "node not installed")
class PublicRoomRenders(unittest.TestCase):
    QS = [q("hounds", "[data-hook='room-hound']", "count"), q("states", "[data-hook='room-hound']", "attrs", attr="data-state"),
          q("ids", "[data-hook='room-hound']", "attrs", attr="data-id"), q("names", "[data-hook='room-name']", "texts"),
          q("bubbles", "[data-hook='room-bubble']", "texts"), q("bursts", "[data-hook='room-burst']", "texts"),
          q("crowns", "[data-hook='room-crown']", "attrs", attr="hidden"), q("status", "[data-hook='room-status']"),
          q("board", "[data-hook='room-board']", "attr", attr="href"), q("tv", "[data-hook='room-tv']", "attr", attr="href"),
          q("door", "[data-hook='room-door']", "attr", attr="href"), q("stone", "[data-hook='room-stone']", "attr", attr="href"),
          q("bulletin", "[data-hook='room-bulletin']", "count"), q("bulletin_href", "[data-hook='room-bulletin']", "attr", attr="href"),
          q("roster", "[data-hook='room-roster-btn']", "count"), q("images", "img", "count")]

    def page(self, routes=None, **kw):
        kw.setdefault("now", NOW)
        return run_page("room", routes=routes or routes_house(), tz="UTC", settleMs=250, **kw)

    def test_the_house_room_shows_the_house_pack_only_and_each_hounds_real_state(self):
        out = self.page(queries=self.QS)
        f = out["final"]
        self.assertEqual(f["hounds"], 5, "the member's hound is not in the house kennel")
        by = dict(zip(f["ids"], f["states"]))
        self.assertEqual(by["closer"], "pending")
        self.assertEqual(by["steamer"], "won")
        self.assertEqual(by["almanac"], "lost")
        self.assertNotIn("rusty", f["ids"])
        self.assertIn("Yankees ML +135 · 1u · +1 more", f["bubbles"])
        self.assertIn("+1.3u", f["bursts"])
        self.assertIn("-1u", f["bursts"])

    def test_the_props_open_the_places_the_brief_names(self):
        f = self.page(queries=self.QS)["final"]
        self.assertEqual((f["board"], f["tv"], f["door"], f["stone"]), ("hounds.html", "live.html", "kennel.html", "graveyard.html"))
        self.assertEqual(f["bulletin"], 1)
        self.assertIsNone(f["bulletin_href"], "the bulletin board is a placeholder: no link")

    def test_the_text_of_a_hound_is_escaped(self):
        out = self.page(queries=self.QS)
        self.assertEqual(out["final"]["images"], 0, "a hound named like markup became an element")
        self.assertIn("<img src=x on", " ".join(out["final"]["names"]), "the name is shown as text (clipped to fit the name tag)")

    def test_no_undefined_nan_or_null_anywhere_on_the_page(self):
        out = self.page(queries=self.QS)
        self.assertNotRegex(out["text"], BAD_TEXT)
        # and in the attributes the scene wrote
        for w in (390, 1440):
            o = self.page(queries=self.QS, width=w, actions=[{"do": "click", "sel": "[data-hook='room-hound-btn']", "index": 0, "capture": [q("card", "[data-hook='room-sheet-body']")]}])
            self.assertNotRegex(o["text"], BAD_TEXT, w)
            self.assertNotRegex(o["captures"]["0"]["card"], BAD_TEXT, w)

    def test_a_tap_on_a_hound_opens_its_card_with_the_link_to_its_page(self):
        out = self.page(queries=self.QS, actions=[{"do": "click", "sel": "[data-hook='room-hound-btn']", "index": 0, "capture": [
            q("name", ".rm-sheet__name"), q("state", "[data-hook='room-card-state']"), q("pick", "[data-hook='room-card-pick']"),
            q("open", "[data-hook='room-card-open']", "attr", attr="href"), q("studio", "[data-hook='room-card-studio']", "count"),
            q("record", "[data-hook='room-card-record']"), q("hidden", "[data-hook='room-sheet']", "hidden")]}])
        c = out["captures"]["0"]
        self.assertEqual((c["name"], c["state"], c["hidden"]), ("Closer", "At its desk", False))
        self.assertEqual(c["open"], "hound.html?id=closer")
        self.assertEqual(c["studio"], 0, "a visitor gets no studio actions on a house hound")
        self.assertIn("17-14", c["record"])
        self.assertIn("31 settled", c["record"])

    def test_the_card_of_a_small_sample_says_so(self):
        out = self.page(queries=self.QS, actions=[{"do": "click", "sel": "[data-hook='room-roster-btn']", "index": 1, "capture": [q("small", "[data-hook='room-card-small']"), q("name", ".rm-sheet__name")]}])
        self.assertEqual(out["captures"]["0"]["name"], "Steamer")
        self.assertIn("Small sample: 4 settled", out["captures"]["0"]["small"])

    def test_the_crown_is_on_the_units_leader_only(self):
        out = self.page(queries=self.QS)
        f = out["final"]
        shown = [i for i, hid in zip(f["crowns"], f["ids"]) if i is None]
        self.assertEqual(len(shown), 1)
        self.assertEqual([hid for hid, hidden in zip(f["ids"], f["crowns"]) if hidden is None], ["closer"])

    def test_the_stone_in_the_corner_counts_the_graveyard(self):
        f = self.page(queries=self.QS + [q("n", "[data-hook='room-stone']", "attr", attr="data-count")])["final"]
        self.assertEqual(f["n"], "2")
        r = routes_house({"/hounds/graveyard": [200, {"hounds": [], "headstones": []}]})
        self.assertEqual(self.page(r, queries=[q("n", "[data-hook='room-stone']", "count")])["final"]["n"], 0)

    def test_a_visitor_does_not_ask_for_the_board_and_the_idle_hounds_do_not_scout(self):
        out = self.page(queries=self.QS)
        self.assertNotIn("/sports/now", [g.split("?")[0] for g in out["gets"]])
        by = dict(zip(out["final"]["ids"], out["final"]["states"]))
        self.assertEqual(by["sleeper"], "nap")                          # the board was not read: no scouting is claimed

    def test_a_signed_in_viewer_gets_the_board_and_the_scouts_pace(self):
        out = self.page(queries=self.QS, **SIGNED)
        by = dict(zip(out["final"]["ids"], out["final"]["states"]))
        self.assertEqual(by["sleeper"], "scouting")                     # MLB: one live + one still to start today (the 20h-away game is tomorrow)
        self.assertIn("/sports/now", [g.split("?")[0] for g in out["gets"]])
        tv = self.page(queries=[q("t", "[data-hook='room-tv']", "attr", attr="aria-label")], **SIGNED)["final"]["t"]
        self.assertIn("2 games left on today's board", tv)

    def test_overnight_in_the_viewers_night_the_idle_hounds_sleep(self):
        out = self.page(queries=self.QS, now="2026-10-21T03:30:00Z", **SIGNED)       # 03:30 in the harness's UTC
        by = dict(zip(out["final"]["ids"], out["final"]["states"]))
        self.assertEqual(by["sleeper"], "asleep")

    def test_the_server_warming_up_or_down_is_said_plainly(self):
        out = self.page({"/hounds": [200, {"warming_up": True, "retry_after_seconds": 5, "hounds": []}]}, queries=[q("msg", "[data-hook='room-message']"), q("n", "[data-hook='room-hound']", "count")])
        self.assertIn("warming up", out["final"]["msg"])
        self.assertEqual(out["final"]["n"], 0)
        down = run_page("room", routes={}, down=["/hounds"], tz="UTC", settleMs=250, queries=[q("msg", "[data-hook='room-message']"), q("retry", "[data-hook='room-retry']", "count")])
        self.assertIn("could not load", down["final"]["msg"])
        self.assertEqual(down["final"]["retry"], 1)

    def test_it_polls_every_45_seconds_and_stops_while_the_tab_is_hidden(self):
        out = self.page(queries=[q("hounds", "[data-hook='room-hound']", "count")], actions=[
            {"do": "visibility", "state": "hidden", "label": "hid"},
            {"do": "visibility", "state": "visible", "label": "back"}])
        self.assertEqual(out["intervals"], [45000])
        hidden = self.page(queries=[], actions=[{"do": "visibility", "state": "hidden"}])
        self.assertEqual(hidden["intervals"], [], "a hidden tab holds no poll timer")

    def test_a_poll_redraws_from_a_changed_record_without_remounting_the_hounds(self):
        r = routes_house()
        after_hounds = json.loads(json.dumps(r["/hounds"][1]))
        after_hounds["hounds"][0]["open_bets"] = 0            # both of its tickets have since been graded
        after_stream = [200, {"items": [dict(graded_bet("closer", "win", 2, ago=5), hound_name="Closer")], "page": 1, "total": 1}]
        out = self.page(r, queries=self.QS, switchAfter={"/hounds/stream": [1, after_stream], "/hounds": [1, [200, after_hounds]]},
                        actions=[{"do": "fire_timers", "wait": 250, "capture": [q("states", "[data-hook='room-hound']", "attrs", attr="data-state"), q("ids", "[data-hook='room-hound']", "attrs", attr="data-id"), q("n", "[data-hook='room-hound']", "count")]}])
        c = out["captures"]["0"]
        self.assertEqual(c["n"], 5)
        self.assertEqual(dict(zip(c["ids"], c["states"]))["closer"], "won")

    def test_the_sound_is_off_until_it_is_asked_for(self):
        out = self.page(queries=[q("btn", "[data-hook='room-sound']"), q("pressed", "[data-hook='room-sound']", "attr", attr="aria-pressed")])
        self.assertEqual((out["final"]["btn"], out["final"]["pressed"]), ("Sound off", "false"))

    def test_the_paper_note_is_one_short_line_and_the_footer_carries_the_compliance_once(self):
        out = self.page(queries=[q("note", "[data-hook='room-note']"), q("legal", "[data-hook='footer-legal']")])
        self.assertEqual(out["final"]["note"], "Paper bets only. Units are the scoreboard, not money.")
        self.assertEqual(out["text"].count("1-800-GAMBLER"), 1)


@unittest.skipUnless(HAS_NODE, "node not installed")
class MyKennelFold(unittest.TestCase):
    def dogs(self):
        gus = {"id": "u-1", "name": "Underdog Gus", "tagline": "Barks at the books", "status": "running", "version_no": 1, "look": None, "sports": ["mlb"],
               "record": {"bets": 4, "wins": 3, "losses": 1, "pushes": 0, "units_average_price": 1.8}, "settled": 4, "open_bets": 1, "new": False,
               "last_pick": None, "page_href": "hound.html?id=u-1", "retired": False, "trained_times": 1, "coached_from": "u-0"}
        tina = dict(gus, id="u-2", name="Totals Tina", open_bets=0, new=True, settled=0, record={"bets": 0, "wins": 0, "losses": 0, "pushes": 0, "units_average_price": None},
                    coached_from="u-0b", trained_times=1)
        gone = dict(gus, id="u-3", name="Retired Rex", retired=True)
        return [gus, tina, gone]

    def routes(self, dogs=None, graveyard=None):
        data = {"handle": "handler-21e8", "display": "Handler 21E8", "kennel_name": "Gus & Co", "dog_count": 2, "dogs": self.dogs() if dogs is None else dogs,
                "season": {"id": "s2"}, "paper_only": True, "needs_name_prompt": False, "name_limits": {"min": 2, "max": 30}, "graveyard": graveyard or [], "combined": None}
        return {"/hounds/kennels/mine": [200, data], "/hounds/mine": [200, {"hounds": [], "plan": "paid"}],
                "/hounds/u-1/bets": [200, {"items": [open_bet("u-1", "Red Sox to win", price=135)], "total": 1}],
                "/sports/now": [200, {"families": [{"code": "MLB", "live": [], "upcoming_24h": [{"start_utc": iso(120)}]}]}]}

    QS = [q("fold", "[data-hook='kennel-room-fold']", "count"), q("open", "[data-hook='kennel-room-fold']", "attr", attr="open"),
          q("title", "[data-hook='kennel-room-summary']"), q("hounds", "[data-hook='room-hound']", "attrs", attr="data-id"),
          q("states", "[data-hook='room-hound']", "attrs", attr="data-state"), q("bubbles", "[data-hook='room-bubble']", "texts"),
          q("note", "[data-hook='room-note']", "count"), q("cards", "[data-hook='kennel-dog']", "count"),
          q("trained", "[data-hook='room-trained']", "texts")]

    def go(self, routes=None, **kw):
        kw.setdefault("now", NOW)
        stored = dict(SIGNED["stored"], **kw.pop("stored", {}))
        return run_page("kennel", routes=routes or self.routes(), tz="UTC", settleMs=350, stored=stored, **kw)

    def test_the_fold_sits_above_the_cards_with_the_members_active_hounds(self):
        out = self.go(queries=self.QS)
        html = read("kennel.html")
        self.assertLess(html.index('data-hook="kennel-room"'), html.index('data-hook="kennel-grid"'))
        f = out["final"]
        self.assertEqual(f["title"], "Your kennel room")
        self.assertEqual(f["hounds"], ["u-1", "u-2"], "the retired hound has left the room")
        self.assertEqual(dict(zip(f["hounds"], f["states"])), {"u-1": "pending", "u-2": "training"})
        self.assertEqual(f["bubbles"][0], "Red Sox ML +135 · 1u")
        self.assertEqual(f["cards"], 3)                 # two active cards and the retired one in its fold
        self.assertEqual(f["note"], 0, "the page already carries its own paper line")
        self.assertEqual(f["trained"], ["×1", "×1"])

    def test_a_wide_screen_opens_the_fold_and_a_stored_choice_wins(self):
        self.assertIsNotNone(self.go(queries=self.QS)["final"]["open"])
        shut = self.go(queries=self.QS, stored={"linehound.kennel-room.open": "0"})
        self.assertIsNone(shut["final"]["open"])
        self.assertEqual(shut["final"]["hounds"], [], "a folded room draws nothing and polls nothing")
        self.assertEqual(shut["intervals"], [])

    def test_a_member_gets_the_studio_actions_on_their_own_hound(self):
        out = self.go(queries=self.QS, actions=[{"do": "click", "sel": "[data-hook='room-hound-btn']", "index": 0, "capture": [
            q("studio", "[data-hook='room-card-studio']", "attr", attr="href"), q("fire", "[data-hook='room-card-unleash']", "attr", attr="href"),
            q("edit", "[data-hook='room-card-edit']", "attr", attr="href"), q("open", "[data-hook='room-card-open']", "attr", attr="href")]}])
        c = out["captures"]["0"]
        self.assertEqual(c["open"], "hound.html?id=u-1")
        self.assertEqual(c["studio"], "kennel.html?dog=u-1&tab=look")
        self.assertEqual(c["fire"], "kennel.html?dog=u-1&tab=fire")
        self.assertEqual(c["edit"], "kennel.html?dog=u-1&tab=rules")

    def test_the_studio_action_opens_the_drawer_in_place_instead_of_reloading_the_page(self):
        out = self.go(queries=self.QS, actions=[
            {"do": "click", "sel": "[data-hook='room-hound-btn']", "index": 0},
            {"do": "click", "sel": "[data-hook='room-card-unleash']", "wait": 150, "capture": [
                q("studio_hidden", "[data-hook='studio']", "hidden"), q("card_hidden", "[data-hook='room-sheet']", "hidden")]}])
        c = out["captures"]["1"]
        self.assertEqual((c["studio_hidden"], c["card_hidden"]), (False, True))
        self.assertEqual(out["navigations"], [])

    def test_a_poll_does_not_rebuild_the_list_or_pull_focus_when_nothing_changed(self):
        out = self.go(queries=self.QS, actions=[
            {"do": "fire_timers", "wait": 200, "capture": [q("roster", "[data-hook='room-roster-btn']", "count"), q("states", "[data-hook='room-hound']", "attrs", attr="data-state")]}])
        self.assertEqual(out["captures"]["0"]["roster"], 2)
        self.assertEqual(out["captures"]["0"]["states"], ["pending", "training"])

    def test_a_member_with_no_hound_has_no_room(self):
        out = self.go(self.routes(dogs=[]), queries=self.QS)
        self.assertEqual(out["final"]["fold"], 0)

    def test_a_public_kennel_has_no_room(self):
        out = run_page("kennel", search="?u=handler-21e8", tz="UTC", routes={"/hounds/kennels/handler-21e8": [200, dict(self.routes()["/hounds/kennels/mine"][1], best=None)]}, queries=self.QS)
        self.assertEqual(out["final"]["fold"], 0)

    def test_the_buried_hounds_headstone_is_in_the_corner_and_not_in_the_room(self):
        out = self.go(self.routes(graveyard=[{"id": "u-9", "name": "Buried Bo"}]), queries=self.QS + [q("n", "[data-hook='room-stone']", "attr", attr="data-count")])
        self.assertEqual(out["final"]["n"], "1")
        self.assertEqual(out["final"]["hounds"], ["u-1", "u-2"])


# ---------------------------------------------------------------------------------------------------
# the render check in a real browser, at a phone and at a desktop width
# ---------------------------------------------------------------------------------------------------

def _chrome_available():
    from tests.test_no_horizontal_overflow import CHROME
    return bool(HAS_NODE and CHROME)


@unittest.skipUnless(_chrome_available(), "node and a Chrome/Chromium binary are needed")
class RenderedInChrome(unittest.TestCase):
    """room.html and the My Kennel fold, loaded for real at 390 and 1440 px: nothing a person can read (or any attribute) says undefined / NaN / null,
    nothing scrolls sideways, every hound stands inside the stage, and a tap opens the card inside the screen."""

    @classmethod
    def setUpClass(cls):
        import http.server
        import subprocess
        import threading
        from pathlib import Path
        from tests.test_no_horizontal_overflow import CHROME, make_handler
        with live_clock():
            api = {k: tuple(v) for k, v in routes_house().items()}
            kennel = MyKennelFold()
            api.update({k: tuple(v) for k, v in kennel.routes().items()})
            both = [open_bet("u-1", "Red Sox to win", price=135, start=70), graded_bet("u-1", "win", 1.35, ago=45)]
            api["/hounds/u-1/bets"] = (200, {"items": both, "total": 2})
            api["/sports/now"] = (200, {"families": [{"code": "MLB", "live": [{"event_id": "a"}], "upcoming_24h": [{"start_utc": iso(120)}]}]})
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_handler(api))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        script = str(Path(__file__).resolve().parent / "room_render_check.mjs")
        proc = subprocess.run(["node", script, CHROME, base, "/web/room.html", "/web/kennel.html", "/web/kennel.html?pref=open"], capture_output=True, text=True, encoding="utf-8", timeout=420)
        lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("[")]
        if proc.returncode != 0 or not lines:
            raise AssertionError(f"render check failed ({proc.returncode}): {proc.stderr[-1500:]}")
        cls.results = json.loads(lines[-1])

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def rows(self, path):
        return [r for r in self.results if r["path"] == path]

    def test_both_widths_and_the_pages_were_rendered(self):
        self.assertEqual(sorted((r["path"], r["width"]) for r in self.results),
                         [("/web/kennel.html", 390), ("/web/kennel.html", 1440), ("/web/kennel.html?pref=open", 390), ("/web/kennel.html?pref=open", 1440),
                          ("/web/room.html", 390), ("/web/room.html", 1440)])
        for r in self.results:
            self.assertEqual(r["errors"], [], r)

    def drawn(self):
        """The renders that have a room on screen: the public page, and My Kennel unless it starts folded (a phone, with no stored choice)."""
        return [r for r in self.results if r["hounds"]]

    def test_no_undefined_nan_or_null_in_text_svg_text_attributes_or_the_card(self):
        self.assertEqual(len(self.drawn()), 5)
        for r in self.results:
            with self.subTest(path=r["path"], width=r["width"]):
                self.assertIsNone(r["visibleBad"], r["visibleBad"])
                self.assertIsNone(r["svgBad"], r["svgBad"])
                self.assertEqual(r["attrBad"], [])
                self.assertIsNone(r["sheetBad"], r["sheetBad"])
        for r in self.drawn():
            self.assertTrue(r["sheetText"], f"the first hound's card did not open: {r['path']} {r['width']}")

    def test_the_page_never_scrolls_sideways_and_the_room_pans_inside_its_frame(self):
        for r in self.results:
            with self.subTest(path=r["path"], width=r["width"]):
                self.assertLessEqual(r["sw"], r["iw"] + 1)
        for r in self.drawn():
            if r["width"] == 390:
                self.assertTrue(r["frameScrolls"], "on a phone the stage is wider than its frame and pans")
                self.assertGreaterEqual(r["stageW"], 860)
            elif r["path"] == "/web/room.html":
                self.assertFalse(r["frameScrolls"], "on a desktop the whole room fits")

    def test_my_kennel_starts_folded_on_a_phone_and_open_on_a_desktop_until_the_member_chooses(self):
        by = {(r["path"], r["width"]): r for r in self.results}
        self.assertFalse(by[("/web/kennel.html", 390)]["foldOpen"])
        self.assertEqual(by[("/web/kennel.html", 390)]["hounds"], 0, "a folded room draws nothing")
        self.assertTrue(by[("/web/kennel.html", 1440)]["foldOpen"])
        self.assertTrue(by[("/web/kennel.html?pref=open", 390)]["foldOpen"])

    def test_every_hound_stands_inside_the_stage_and_the_states_are_the_real_ones(self):
        for r in self.rows("/web/room.html"):
            self.assertEqual(r["hounds"], 5)
            self.assertEqual(r["outside"], 0)
            for state in ("pending", "won", "lost"):
                self.assertGreaterEqual(r["states"].get(state, 0), 1, (state, r["states"]))
        for r in self.drawn():
            self.assertEqual(r["outside"], 0, r)
            if r["path"].startswith("/web/kennel.html"):
                self.assertEqual(r["hounds"], 2)

    def test_the_card_opens_inside_the_screen(self):
        for r in self.drawn():
            self.assertTrue(r["sheetInView"], r)

    def test_the_whiteboard_text_is_real_numbers(self):
        for r in self.rows("/web/room.html"):
            self.assertRegex(r["svgText"], r"LEADERBOARD")
            self.assertRegex(r["svgText"], r"[+-]\d+(\.\d+)?u")


# ---------------------------------------------------------------------------------------------------
# static
# ---------------------------------------------------------------------------------------------------

class StaticChecks(unittest.TestCase):
    def test_the_page_has_the_footer_once_and_no_inline_script(self):
        html = read("room.html")
        html = html[html.index("<body"):]                 # the meta description says 21+ too; the page body says it once
        self.assertEqual(html.count("1-800-GAMBLER"), 1)
        self.assertIn('<a href="tel:1-800-426-2537" data-hook="responsible-gambling-help">1-800-GAMBLER</a>', html)
        for needle in ("21+", "Paper bets only, not advice", "Bet at your own risk"):
            self.assertEqual(html.count(needle), 1, needle)
        scripts = re.findall(r"<script\b[^>]*>", html)
        self.assertTrue(scripts)
        for tag in scripts:
            self.assertRegex(tag, r'type="module" src="js/[\w-]+\.js"')
        self.assertNotRegex(html, r"<script[^>]*>[^<]+</script>")
        self.assertNotIn("<img", html)

    def test_no_forbidden_words_on_the_page_or_in_the_scenes_text(self):
        banned = re.compile(r"bet\s*check|guarantee|sure thing|lock|free money|profit|edge|EV|beta|early access|waitlist|put down|tombstone|R\.I\.P", re.I)
        for name in ("room.html", "js/room-scene.js", "js/room-adapter.js", "js/room-data.js", "js/room-page.js", "css/room.css"):
            src = read(name)
            # the comments say what the code must NOT claim; what a person can read is everything else
            src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
            src = re.sub(r"<!--.*?-->", "", src, flags=re.S)
            src = re.sub(r"(?m)^\s*//.*$|\s//\s.*$", "", src)
            hit = banned.search(src)
            self.assertIsNone(hit, f"{name}: {hit and hit.group(0)}")

    def test_no_emoji_in_the_room(self):
        for name in ("room.html", "js/room-scene.js", "js/room-adapter.js", "css/room.css"):
            for ch in read(name):
                self.assertFalse(0x1F300 <= ord(ch) <= 0x1FAFF or 0x2600 <= ord(ch) <= 0x27BF, f"{name}: emoji {ch!r}")

    def test_every_animation_and_transition_sits_inside_prefers_reduced_motion_no_preference(self):
        css = read("css/room.css")
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        block = re.search(r"@media \(prefers-reduced-motion: no-preference\) \{", css)
        self.assertIsNotNone(block)
        depth, i = 1, block.end()
        while depth and i < len(css):
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        outside = css[:block.start()] + css[i:]
        outside = re.sub(r"@keyframes [\w-]+ \{(?:[^{}]|\{[^{}]*\})*\}", "", outside)
        self.assertNotRegex(outside, r"(^|[;{\s])(animation|transition)\s*:", "a movement outside the no-preference block")

    def test_the_page_never_scrolls_sideways_by_construction(self):
        css = read("css/room.css")
        self.assertRegex(css, r"\.rm-frame \{[^}]*overflow-x: auto")
        self.assertRegex(css, r"\.rm-stage \{[^}]*width: max\(100%, 860px\)")

    def test_the_landing_page_links_the_room_from_betting_right_now(self):
        html = read("landing.html")
        strip = re.search(r'<section[^>]*data-hook="kh-strip".*?</section>', html, re.S).group(0)
        self.assertIn('href="room.html" data-hook="kh-strip-room"', strip)

    def test_my_kennel_mounts_the_room_with_one_hook_and_one_import(self):
        html, js = read("kennel.html"), read("js/kennel.js")
        self.assertEqual(html.count('data-hook="kennel-room"'), 1)
        self.assertIn('href="css/room.css"', html)
        self.assertIn('import { mountKennelRoom } from "./room-scene.js";', js)
        self.assertEqual(js.count("mountKennelRoom("), 1)

    def test_the_room_reuses_the_products_own_hound_art(self):
        scene = read("js/room-scene.js")
        self.assertIn('from "./dog-avatar.js"', scene)
        self.assertIn("dogFace(", scene)
        self.assertNotIn("innerHTML", re.sub(r"/\*.*?\*/", "", scene, flags=re.S))
        self.assertNotRegex(read("room.html"), r"\.(png|jpe?g|gif|webp)\b")


if __name__ == "__main__":
    unittest.main()
