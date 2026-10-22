"""Starting-soon and live-update bet alerts (src/notify/alert_live.py and the pieces it plugs into).

The owner's ask (2026-10-22): members should see their hounds' bets "live or upcoming". Two new opt-in kinds sit beside
placed and settled: a batched "tips off in 15 min" and four live moments (went live, halftime, a late lead change that flips
the ticket, final), capped at three per ticket. What is pinned here, and why each matters:

  * the starting timer: once per ticket, only inside the 15-minute window, never after the tip, and tickets that start
    together batch into ONE message;
  * a live update fires only on the four defined moments, never more than three per ticket (the final always keeps a slot),
    and the whole kind is OFF by default;
  * a lead change is a flip only from winning to losing or back: a tie or a push in between is not a position;
  * a replay / rehearsal / preview row never alerts, on any kind;
  * channel routing per kind: email carries placed and settled only, text and push carry all four; quiet hours hold and a
    held starting-soon is dropped once it is stale; live updates cannot eat the hour's send cap that "settled" needs;
  * a text stays inside one 160-character segment where the wording allows, and keeps STOP and the paper mark;
  * the scan rides the grading loop's pass: it adds no request, runs before the settle step, and a failure in it cannot
    stop a grade.

Every send goes through an injected fake transport; every path is a temp path.
"""

from __future__ import annotations

import json
import os
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.appstate import users as users_store
from src.hounds import live_scores as ls
from src.hounds import live_settle as lv
from src.hounds import unit_size, user_settle, user_store
from src.notify import alert_channels as ch
from src.notify import alert_dispatch as dispatch
from src.notify import alert_live
from src.notify import alert_render as render
from src.notify import alerts
from tests._hounds_user_fixtures import spec_dict
from tests.test_bet_alerts import ADDRESS, ENV, FREE, PAID, TWILIO, Base, FakeHttp, at
from tests.test_live_settle_loop import EVENT, NBA_URL, TIP, Fake, LiveCase, espn_event, user_bet, utc

START = datetime(2026, 10, 21, 23, 30, tzinfo=timezone.utc)       # the tip
GAME = "g-hawks-celtics"


def put_game(conn, key=GAME, *, state=ls.UPCOMING, start=START, home="Boston Celtics", away="Atlanta Hawks",
             home_score=None, away_score=None, progress=None, updated=None, final=None, sport="NBA") -> None:
    """One cache row, written the way the grading loop's ``_store_answer`` leaves it."""
    stamp = ls.iso(updated or start)
    conn.execute(
        "INSERT OR REPLACE INTO live_games (game_key, sport, league, home_team, away_team, start_utc, supported, state,"
        " home_score, away_score, detail, updated_utc, final_utc, progress, first_seen_utc)"
        " VALUES (?,?,?,?,?,?,1,?,?,?,?,?,?,?,?)",
        (key, sport, "basketball_nba", home, away, ls.iso(start), state, home_score, away_score,
         (progress or {}).get("label"), stamp, ls.iso(final) if final else None,
         json.dumps(progress) if progress else None, stamp))


def prog(period=4, clock="8:00", name="STATUS_IN_PROGRESS", label="8:00 - 4th"):
    return {"period": period, "clock": clock, "name": name, "label": label}


class LiveAlertBase(Base):
    def setUp(self):
        super().setUp()
        self.cache = lv.connect(self.dir / "live_settle.db")
        self.addCleanup(self.cache.close)

    def ticket(self, hound, n=1, **over):
        row = {"event_id": GAME, "bet_id": f"t-{n}", "hound_id": hound["id"], "sport": "NBA", "market": "moneyline",
               "side": "away", "line": None, "selection": "Atlanta Hawks to win", "price": 110, "units": 2.0,
               "stake_units": 2.0, "away_team": "Atlanta Hawks", "home_team": "Boston Celtics",
               "start": ls.iso(START), "segment": "forward", "provenance": "live", "role": None,
               "league": "basketball_nba"}
        row.update(over)
        return row

    def scan(self, now, tickets):
        return alert_live.scan(self.cache, now, {}, tickets=tickets)

    def kinds(self, user):
        return [(e["kind"], e["payload"].get("moment")) for e in reversed(alerts.events_for(user.id, limit=100))]

    def sms_member(self, **prefs):
        """A paid member with email and text on (the two channels whose routing differs)."""
        user, hound = self.member(channels={"email": True}, **prefs)
        alerts.sms_opt_in(user.id, "(555) 234-5678", now=at(-60))
        alerts.update_prefs(user.id, {"channels": {"sms": True}})
        return user, hound

    def texts(self):
        out = []
        for call in self.http.calls:
            if "twilio" in call["url"]:
                out.append(urllib.parse.parse_qs(call["body"].decode())["Body"][0])
        return out


# ---------------------------------------------------------------------------
# the starting-soon timer and its batching
# ---------------------------------------------------------------------------

class StartingSoon(LiveAlertBase):
    def test_it_fires_inside_the_fifteen_minute_window_once_and_never_after_the_tip(self):
        user, hound = self.member()
        put_game(self.cache)
        t = [self.ticket(hound)]
        self.assertEqual(self.scan(START - timedelta(minutes=40), t)["starting"], 0)        # too early
        self.assertEqual(self.scan(START - timedelta(minutes=16), t)["starting"], 0)        # 16 min out: not yet
        self.assertEqual(self.scan(START - timedelta(minutes=14), t)["starting"], 1)
        self.assertEqual(self.scan(START - timedelta(minutes=9), t)["starting"], 0)         # the same ticket, once
        self.assertEqual(self.scan(START - timedelta(minutes=1), t)["starting"], 0)
        events = alerts.events_for(user.id)
        self.assertEqual([e["kind"] for e in events], ["starting"])
        self.assertEqual(events[0]["payload"]["minutes_out"], 14)

    def test_a_game_already_started_or_postponed_gets_no_starting_alert(self):
        user, hound = self.member()
        put_game(self.cache, state=ls.LIVE, home_score=0, away_score=0, progress=prog(1), updated=START)
        self.assertEqual(self.scan(START - timedelta(minutes=5), [self.ticket(hound)])["starting"], 0)   # the feed says live
        put_game(self.cache, state=ls.POSTPONED)
        self.assertEqual(self.scan(START - timedelta(minutes=10), [self.ticket(hound)])["starting"], 0)
        put_game(self.cache)
        self.assertEqual(self.scan(START + timedelta(minutes=2), [self.ticket(hound)])["starting"], 0)   # past the tip

    def test_tickets_that_start_together_go_out_as_one_message(self):
        user, hound = self.sms_member()
        put_game(self.cache)
        tickets = [self.ticket(hound, 1), self.ticket(hound, 2, market="total", side="over", line=221.5,
                                                      selection="Over 221.5", price=-105)]
        self.assertEqual(self.scan(START - timedelta(minutes=14), tickets)["starting"], 2)
        self.drain(START - timedelta(minutes=14) + timedelta(seconds=30), env={**ENV, **TWILIO})
        texts = self.texts()
        self.assertEqual(len(texts), 1, "two tickets, one text")
        self.assertIn("tips off in 14 min", texts[0])
        self.assertEqual(self.http.emails(), [], "starting-soon never goes to email")
        with alerts.connect() as conn:
            self.assertEqual(conn.execute("SELECT n_events FROM alert_sends").fetchone()[0], 2)

    def test_the_message_names_the_hound_the_pick_the_minutes_and_the_stake_in_dollars(self):
        user, hound = self.member()
        alerts.update_prefs(user.id, {"event_toggles": {"starting": True}})
        event = {"id": 1, "kind": "starting", "created_utc": "2026-10-21T23:15:00Z", "payload": {
            "hound_name": "DRAKEO", "hound_id": "u-abc", "sport": "NBA", "market": "moneyline",
            "selection": "Atlanta Hawks to win", "price": 110, "stake_units": 2.0, "minutes_out": 15,
            "away_team": "Atlanta Hawks", "home_team": "Boston Celtics"}}
        line = render.event_line(event, unit_size.Sizing("fixed", 25, None, 2500))
        self.assertEqual(line, "DRAKEO's Atlanta Hawks ML +110 tips off in 15 min · stake $50")
        self.assertEqual(render.subject([event]), "DRAKEO's Atlanta Hawks ML +110 tips off in 15 min")
        mlb = {**event, "payload": {**event["payload"], "sport": "MLB"}}
        self.assertIn("has first pitch in 15 min", render.event_line(mlb, unit_size.fixed(10)))

    def test_it_is_a_toggle_and_off_means_nothing_is_written(self):
        user, hound = self.member(event_toggles={"starting": False})
        put_game(self.cache)
        self.assertEqual(self.scan(START - timedelta(minutes=14), [self.ticket(hound)])["starting"], 0)
        self.assertEqual(alerts.events_for(user.id), [])

    def test_a_member_who_never_opened_alerts_costs_nothing(self):
        user, hound = self.member(opened=False)
        put_game(self.cache)
        report = self.scan(START - timedelta(minutes=14), [self.ticket(hound)])
        self.assertEqual((report["tickets"], report["starting"]), (0, 0))


# ---------------------------------------------------------------------------
# live updates: only the defined moments, capped, off by default
# ---------------------------------------------------------------------------

class LiveUpdates(LiveAlertBase):
    def test_a_new_member_has_live_updates_off_and_the_other_three_on(self):
        user, hound = self.member()
        self.assertEqual(alerts.get_prefs(user.id)["event_toggles"],
                         {"placed": True, "starting": True, "live": False, "settled": True})

    def test_nothing_is_written_while_live_updates_are_off_however_the_game_goes(self):
        user, hound = self.member()
        t = [self.ticket(hound)]
        put_game(self.cache, state=ls.LIVE, home_score=2, away_score=0, progress=prog(1, "10:00", label="10:00 - 1st"),
                 updated=START + timedelta(minutes=5))
        self.scan(START + timedelta(minutes=5), t)
        put_game(self.cache, state=ls.FINAL, home_score=100, away_score=90, progress=None,
                 updated=START + timedelta(hours=2), final=START + timedelta(hours=2))
        self.scan(START + timedelta(hours=2), t)
        self.assertEqual([k for k in self.kinds(user) if k[0] == "live"], [])

    def test_the_four_moments_and_no_others(self):
        user, hound = self.member(event_toggles={"live": True})
        t = [self.ticket(hound)]                                           # the Hawks to win; away side
        now = START + timedelta(minutes=4)
        put_game(self.cache, state=ls.LIVE, home_score=2, away_score=0, progress=prog(1, "10:00", label="10:00 - 1st"),
                 updated=now)
        self.scan(now, t)                                                  # went live
        now += timedelta(minutes=5)
        put_game(self.cache, state=ls.LIVE, home_score=9, away_score=4, progress=prog(1, "5:00", label="5:00 - 1st"),
                 updated=now)
        self.scan(now, t)                                                  # an ordinary five minutes: nothing
        self.assertEqual(self.kinds(user), [("live", "start")])
        now += timedelta(minutes=70)
        put_game(self.cache, state=ls.LIVE, home_score=58, away_score=54,
                 progress=prog(2, "0:00", "STATUS_HALFTIME", "Halftime"), updated=now)
        self.scan(now, t)                                                  # halftime
        self.scan(now + timedelta(minutes=5), t)                           # still halftime, same ticket: once
        put_game(self.cache, state=ls.FINAL, home_score=110, away_score=104, updated=now + timedelta(minutes=70),
                 final=now + timedelta(minutes=70))
        self.scan(now + timedelta(minutes=71), t)                          # final
        self.assertEqual(self.kinds(user), [("live", "start"), ("live", "half"), ("live", "final")])

    def test_a_game_first_seen_long_after_the_tip_is_not_going_live(self):
        user, hound = self.member(event_toggles={"live": True})
        now = START + timedelta(minutes=50)
        put_game(self.cache, state=ls.LIVE, home_score=30, away_score=28, progress=prog(2, "3:00", label="3:00 - 2nd"),
                 updated=now)
        self.scan(now, [self.ticket(hound)])
        self.assertEqual(self.kinds(user), [])

    def test_a_stale_live_answer_is_not_a_score_now(self):
        user, hound = self.member(event_toggles={"live": True})
        put_game(self.cache, state=ls.LIVE, home_score=2, away_score=0, progress=prog(1), updated=START)
        self.scan(START + timedelta(minutes=40), [self.ticket(hound)])
        self.assertEqual(self.kinds(user), [])

    def test_a_final_long_after_the_feed_said_so_is_left_to_the_settled_alert(self):
        user, hound = self.member(event_toggles={"live": True})
        put_game(self.cache, state=ls.FINAL, home_score=100, away_score=90, updated=START + timedelta(hours=3),
                 final=START + timedelta(hours=3))
        self.scan(START + timedelta(hours=4), [self.ticket(hound)])
        self.assertEqual(self.kinds(user), [])

    def test_a_ticket_gets_at_most_three_and_the_final_keeps_the_last_slot(self):
        user, hound = self.member(event_toggles={"live": True})
        t = [self.ticket(hound)]
        now = START + timedelta(minutes=3)
        put_game(self.cache, state=ls.LIVE, home_score=0, away_score=2, progress=prog(1, "11:00", label="11:00 - 1st"),
                 updated=now)
        self.scan(now, t)                                                                   # 1: start (winning)
        now += timedelta(minutes=70)
        put_game(self.cache, state=ls.LIVE, home_score=55, away_score=50,
                 progress=prog(2, "0:00", "STATUS_HALFTIME", "Halftime"), updated=now)
        self.scan(now, t)                                                                   # 2: halftime (losing)
        # Late swings now: the two earlier moments already used the ticket's first two slots, so no flip alert.
        for home, away in ((90, 95), (99, 96), (101, 104), (108, 106)):
            now += timedelta(minutes=5)
            put_game(self.cache, state=ls.LIVE, home_score=home, away_score=away, progress=prog(4, "2:00"), updated=now)
            self.scan(now, t)
        self.assertEqual(self.kinds(user), [("live", "start"), ("live", "half")])
        put_game(self.cache, state=ls.FINAL, home_score=111, away_score=106, updated=now, final=now)
        self.scan(now + timedelta(minutes=2), t)                                            # 3: final
        self.scan(now + timedelta(minutes=7), t)
        self.assertEqual([m for k, m in self.kinds(user)], ["start", "half", "final"])
        self.assertEqual(alerts.live_count(user.id, "t-1"), alerts.LIVE_CAP_PER_TICKET)
        # Even if a fourth event were attempted by hand, the unique key and the cap check hold at three.
        self.assertFalse(alerts.emit_live(self.ticket(hound) | {"kind": "hound_user_bet", "commence_time": ls.iso(START)},
                                          "final", {}, now=now))

    def test_flips_alone_stop_at_the_cap_too(self):
        user, hound = self.member(event_toggles={"live": True})
        t = [self.ticket(hound)]
        now = START + timedelta(hours=2)                                                    # past the went-live window
        sides = ((100, 95), (101, 105), (110, 106), (112, 116), (120, 118))                 # win, lose, win, lose, win
        for home, away in sides:
            now += timedelta(minutes=5)
            put_game(self.cache, state=ls.LIVE, home_score=home, away_score=away, progress=prog(4, "5:00"), updated=now)
            self.scan(now, t)
        moments = [m for _, m in self.kinds(user)]
        self.assertEqual(len(moments), 2, "two flips use the two non-final slots")
        self.assertTrue(all(m.startswith("flip") for m in moments))
        put_game(self.cache, state=ls.FINAL, home_score=121, away_score=118, updated=now, final=now)
        self.scan(now + timedelta(minutes=2), t)
        self.assertEqual(len(self.kinds(user)), 3)

    def test_each_ticket_has_its_own_cap(self):
        user, hound = self.member(event_toggles={"live": True})
        put_game(self.cache, state=ls.FINAL, home_score=100, away_score=90, updated=START + timedelta(hours=2),
                 final=START + timedelta(hours=2))
        self.scan(START + timedelta(hours=2, minutes=1), [self.ticket(hound, 1), self.ticket(hound, 2)])
        self.assertEqual(len(self.kinds(user)), 2)


class LeadChange(LiveAlertBase):
    runs = 0

    def flip_run(self, scores, *, period=4, clock="5:00", **ticket):
        """Scan a sequence of (home, away) scores late in the game; the moments raised."""
        type(self).runs += 1
        user, hound = self.member(email=f"flip{self.runs}@sample-mail.net", name=f"Flipper {self.runs}", event_toggles={"live": True})
        t = [self.ticket(hound, 100 + self.runs, **ticket)]
        now = START + timedelta(hours=2)
        for home, away in scores:
            now += timedelta(minutes=5)
            put_game(self.cache, state=ls.LIVE, home_score=home, away_score=away, progress=prog(period, clock), updated=now)
            self.scan(now, t)
        return [m for _, m in self.kinds(user)]

    def test_winning_to_losing_and_back_each_raise_one_update(self):
        moments = self.flip_run([(100, 105), (108, 106), (110, 111)])            # away ticket: win, lose, win
        self.assertEqual(len(moments), 2)

    def test_a_lead_that_never_changes_hands_raises_nothing(self):
        self.assertEqual(self.flip_run([(100, 105), (102, 109), (104, 112)]), [])

    def test_winning_then_tied_then_winning_is_not_a_flip(self):
        self.assertEqual(self.flip_run([(100, 105), (108, 108), (108, 111)]), [])

    def test_winning_then_tied_then_losing_is_a_flip(self):
        self.assertEqual(len(self.flip_run([(100, 105), (108, 108), (111, 108)])), 1)

    def test_a_push_on_a_spread_is_not_a_position(self):
        # Hawks +3 (away): down 2 is winning, down exactly 3 is a push, down 4 is losing.
        moments = self.flip_run([(100, 98), (103, 100), (103, 101)], market="spread", side="away", line=3.0,
                                selection="Atlanta Hawks +3", price=-110)
        self.assertEqual(moments, [], "winning by the cushion, a push on the number, winning again: no flip")
        moments = self.flip_run([(100, 98), (103, 100), (106, 100)], market="spread", side="away", line=3.0,
                                selection="Atlanta Hawks +3", price=-110)
        self.assertEqual(len(moments), 1, "winning, push, then losing is a real flip")

    def test_a_flip_early_in_the_game_is_not_late(self):
        self.assertEqual(self.flip_run([(20, 25), (30, 28), (35, 31)], period=2, clock="6:00"), [])

    def test_a_prop_has_no_position_and_so_no_flip(self):
        self.assertEqual(self.flip_run([(100, 105), (108, 106), (110, 111)], market="player_points",
                                       selection="Over 24.5 points", side="over", line=24.5), [])

    def test_the_status_arithmetic_matches_the_settlers(self):
        ml = {"market": "moneyline", "side": "home", "sport": "NBA"}
        self.assertEqual(alert_live.ticket_status(ml, 10, 8), "winning")
        self.assertEqual(alert_live.ticket_status(ml, 8, 10), "losing")
        self.assertEqual(alert_live.ticket_status(ml, 8, 8), "push")                       # a basketball tie is a tie
        self.assertEqual(alert_live.ticket_status({**ml, "sport": "SOCCER"}, 1, 1), "losing")  # a team moneyline loses a draw
        sp = {"market": "spread", "side": "home", "line": -3.0}
        self.assertEqual(alert_live.ticket_status(sp, 13, 10), "push")
        self.assertEqual(alert_live.ticket_status(sp, 14, 10), "winning")
        tot = {"market": "total", "side": "under", "line": 8.5}
        self.assertEqual(alert_live.ticket_status(tot, 4, 4), "winning")
        self.assertEqual(alert_live.ticket_status({**tot, "line": 8.0}, 4, 4), "push")
        self.assertIsNone(alert_live.ticket_status({"market": "player_points", "side": "over", "line": 20}, 4, 4))
        self.assertIsNone(alert_live.ticket_status(ml, None, 4))

    def test_late_is_per_sport(self):
        self.assertTrue(alert_live.late("NBA", {"period": 4}))
        self.assertFalse(alert_live.late("NBA", {"period": 3}))
        self.assertTrue(alert_live.late("NHL", {"period": 3}))
        self.assertFalse(alert_live.late("MLB", {"period": 6}))
        self.assertTrue(alert_live.late("MLB", {"period": 7}))
        self.assertTrue(alert_live.late("NCAAB", {"period": 2, "clock": "8:30"}))
        self.assertFalse(alert_live.late("NCAAB", {"period": 2, "clock": "15:30"}))
        self.assertTrue(alert_live.late("SOCCER", {"period": 2, "clock": "78'"}))
        self.assertFalse(alert_live.late("SOCCER", {"period": 2, "clock": "52'"}))
        self.assertFalse(alert_live.late("NBA", None))

    def test_the_break_is_halftime_the_nhl_second_intermission_or_the_middle_of_a_baseball_game(self):
        self.assertTrue(alert_live.at_break("NBA", {"period": 2, "name": "STATUS_HALFTIME"}))
        self.assertFalse(alert_live.at_break("NBA", {"period": 1, "name": "STATUS_END_PERIOD"}))
        self.assertTrue(alert_live.at_break("NHL", {"period": 2, "name": "STATUS_END_PERIOD"}))
        self.assertFalse(alert_live.at_break("NHL", {"period": 1, "name": "STATUS_END_PERIOD"}))
        self.assertTrue(alert_live.at_break("MLB", {"period": 5, "name": "MIDDLE"}))
        self.assertTrue(alert_live.at_break("MLB", {"period": 6, "name": "TOP"}))
        self.assertFalse(alert_live.at_break("MLB", {"period": 4, "name": "MIDDLE"}))


class LiveWording(LiveAlertBase):
    def event(self, moment, **over):
        payload = {"hound_name": "DRAKEO", "hound_id": "u-abc", "sport": "NBA", "market": "moneyline",
                   "selection": "Atlanta Hawks to win", "price": 110, "stake_units": 2.0, "moment": moment,
                   "away_team": "Atlanta Hawks", "home_team": "Boston Celtics", "home_score": 50, "away_score": 54,
                   "status": "winning", "label": "Halftime"}
        payload.update(over)
        return {"id": 1, "kind": "live", "created_utc": "2026-10-21T23:15:00Z", "payload": payload}

    def test_three_sample_messages(self):
        sizing = unit_size.Sizing("fixed", 25, None, 2500)
        start = render.event_line(self.event("start", home_score=0, away_score=0, label="12:00 - 1st"), sizing)
        half = render.event_line(self.event("half"), sizing)
        flip = render.event_line(self.event("flip1", status="losing", home_score=104, away_score=102, label="1:12 - 4th"),
                                 sizing)
        final = render.event_line(self.event("final", home_score=110, away_score=112, label="Final"), sizing)
        self.assertEqual(start, "DRAKEO's Atlanta Hawks ML +110 is live: Celtics 0, Hawks 0, winning")
        self.assertEqual(half, "Halftime: Hawks 54, Celtics 50. DRAKEO's Atlanta Hawks ML +110 is winning.")
        self.assertEqual(flip, "Lead change: DRAKEO's Atlanta Hawks ML +110 is now losing. Celtics 104, Hawks 102 (1:12 - 4th)")
        self.assertEqual(final, "Final: Hawks 112, Celtics 110. DRAKEO's Atlanta Hawks ML +110 is winning; grading next.")

    def test_no_wording_promises_a_result_or_a_profit(self):
        for moment in ("start", "half", "flip1", "final"):
            text = render.event_line(self.event(moment), None).lower()
            for banned in ("will win", "lock", "guarantee", "profit", "bet check", "cash"):
                self.assertNotIn(banned, text)

    def test_a_tied_moneyline_says_tied_and_a_push_on_a_number_says_so(self):
        self.assertIn("is tied", render.event_line(self.event("half", status="push"), None))
        self.assertIn("on the number", render.event_line(self.event("half", status="push", market="spread"), None))

    def test_a_prop_with_no_position_still_reads_cleanly(self):
        text = render.event_line(self.event("final", status=None), None)
        self.assertEqual(text, "Final: Hawks 54, Celtics 50. Grading next.")

    def test_short_team_names_keep_two_word_nicknames(self):
        self.assertEqual(render.short_team("Boston Red Sox"), "Red Sox")
        self.assertEqual(render.short_team("Portland Trail Blazers"), "Trail Blazers")
        self.assertEqual(render.short_team("Atlanta Hawks"), "Hawks")
        self.assertEqual(render.short_team("Arsenal"), "Arsenal")


# ---------------------------------------------------------------------------
# no alert for a row that is not on the record
# ---------------------------------------------------------------------------

class NotOnTheRecord(LiveAlertBase):
    def test_replay_rehearsal_and_preview_rows_never_alert_on_any_kind(self):
        user, hound = self.member(event_toggles={"live": True})
        put_game(self.cache, state=ls.FINAL, home_score=100, away_score=90, updated=START + timedelta(hours=2),
                 final=START + timedelta(hours=2))
        for n, over in enumerate(({"segment": "replay"}, {"provenance": "replay"}, {"segment": "rehearsal"},
                                  {"provenance": "preview"}, {"role": "challenger"}), start=1):
            self.assertEqual(self.scan(START - timedelta(minutes=10), [self.ticket(hound, n, **over)])["starting"], 0, over)
            self.scan(START + timedelta(hours=2, minutes=1), [self.ticket(hound, n, **over)])
        self.assertEqual(alerts.events_for(user.id), [])

    def test_the_emitters_refuse_those_rows_directly(self):
        user, hound = self.member(event_toggles={"live": True})
        row = {**self.ticket(hound), "kind": "hound_user_bet", "commence_time": ls.iso(START), "segment": "replay"}
        self.assertFalse(alerts.emit_starting(row, minutes_out=14, now=at(0)))
        self.assertFalse(alerts.emit_live(row, "final", {}, now=at(0)))
        self.assertEqual(alerts.events_for(user.id), [])

    def test_the_scan_reads_only_the_member_ledgers_so_a_scratch_replay_ledger_is_never_seen(self):
        user, hound = self.member(event_toggles={"live": True})
        seen = []
        with mock.patch.object(lv, "open_tickets_in", side_effect=lambda path, label: seen.append((path, label)) or []):
            alert_live.scan(self.cache, START, {"user": "u.jsonl", "manual": "m.jsonl", "ai": "a.jsonl", "house": "h.jsonl"})
        self.assertEqual(seen, [("u.jsonl", "user"), ("m.jsonl", "manual")])


# ---------------------------------------------------------------------------
# channel routing per kind
# ---------------------------------------------------------------------------

class Routing(LiveAlertBase):
    def row(self, hound):
        return {**self.ticket(hound), "kind": "hound_user_bet", "commence_time": ls.iso(START)}

    def test_email_gets_placed_and_settled_only_and_text_gets_all_four(self):
        self.assertEqual(alerts.CHANNEL_KINDS["email"], ("placed", "settled"))
        for kind in alerts.KINDS:
            self.assertIn(kind, alerts.CHANNEL_KINDS["sms"])
            self.assertIn(kind, alerts.CHANNEL_KINDS["push"])

    def test_one_batch_of_every_kind_splits_by_channel(self):
        user, hound = self.sms_member(event_toggles={"live": True})
        row = self.row(hound)
        alerts.emit_placed(row, now=at(0))
        alerts.emit_starting(row, minutes_out=14, now=at(1))
        alerts.emit_live(row, "start", {"home_score": 0, "away_score": 0, "status": "winning", "label": "12:00 - 1st"}, now=at(2))
        alerts.emit_settled(row, {"result": "win", "profit_units": 2.2}, now=at(3))
        self.drain(at(30), env={**ENV, **TWILIO})
        with alerts.connect() as conn:
            got = {(r["kind"], r["channel"], r["status"]) for r in conn.execute(
                "SELECT e.kind, d.channel, d.status FROM alert_events e JOIN alert_deliveries d ON d.event_id = e.id")}
        self.assertEqual(got, {("placed", "email", "sent"), ("settled", "email", "sent"),
                               ("placed", "sms", "sent"), ("starting", "sms", "sent"), ("live", "sms", "sent"),
                               ("settled", "sms", "sent")})
        mail_text = json.dumps(self.http.emails())
        self.assertNotIn("tips off", mail_text)
        self.assertNotIn("is live", mail_text)
        self.assertIn("won", mail_text)
        self.assertEqual(len(self.texts()), 1, "four events in one window are one text")

    def test_a_kind_the_member_switched_off_is_not_sent_on_any_channel(self):
        user, hound = self.sms_member()
        row = self.row(hound)
        alerts.emit_starting(row, minutes_out=14, now=at(0))
        alerts.emit_settled(row, {"result": "loss", "profit_units": -2.0}, now=at(1))
        alerts.update_prefs(user.id, {"event_toggles": {"starting": False}})       # turned off after it was queued
        self.drain(at(30), env={**ENV, **TWILIO})
        self.assertEqual(len(self.texts()), 1)
        self.assertNotIn("tips off", self.texts()[0])
        self.assertEqual(len(self.http.emails()), 1)

    def test_text_stays_paid_only_for_the_new_kinds_too(self):
        user, hound = self.sms_member()
        alerts.emit_starting(self.row(hound), minutes_out=14, now=at(0))
        self.drain(at(30), env={**ENV, **TWILIO}, paid_check=FREE)
        self.assertEqual(self.texts(), [])
        self.assertEqual(self.deliveries("sms")[0]["status"], "skipped")

    def test_live_updates_cannot_use_the_hours_last_sends(self):
        user, hound = self.sms_member(event_toggles={"live": True})
        row = self.row(hound)
        with alerts.connect() as conn:
            for i in range(dispatch.RATE_CAP_PER_HOUR["sms"] - 1):          # five of the six sends are gone
                conn.execute("INSERT INTO alert_sends (user_id, channel, batch_key, n_events, sent_utc) VALUES (?,?,?,?,?)",
                             (user.id, "sms", f"k{i}", 1, alerts.iso(at(-60 * (i + 1)))))
        alerts.emit_live(row, "start", {"home_score": 0, "away_score": 0, "status": "winning"}, now=at(0))
        counts = self.drain(at(30), env={**ENV, **TWILIO})
        self.assertEqual(counts.get("held_rate_cap"), 1)
        self.assertEqual(self.texts(), [])
        alerts.emit_settled(row, {"result": "win", "profit_units": 2.2}, now=at(40))
        self.drain(at(100), env={**ENV, **TWILIO})
        self.assertEqual(len(self.texts()), 1, "the settled alert still had its send")

    def test_the_hour_cap_still_applies_to_the_new_kinds(self):
        user, hound = self.sms_member()
        with alerts.connect() as conn:
            for i in range(dispatch.RATE_CAP_PER_HOUR["sms"]):
                conn.execute("INSERT INTO alert_sends (user_id, channel, batch_key, n_events, sent_utc) VALUES (?,?,?,?,?)",
                             (user.id, "sms", f"k{i}", 1, alerts.iso(at(-60 * (i + 1)))))
        alerts.emit_starting(self.row(hound), minutes_out=14, now=at(0))
        self.assertEqual(self.drain(at(30), env={**ENV, **TWILIO}).get("held_rate_cap"), 1)

    def test_the_dedupe_holds_across_drains(self):
        user, hound = self.sms_member()
        alerts.emit_starting(self.row(hound), minutes_out=14, now=at(0))
        alerts.emit_starting(self.row(hound), minutes_out=13, now=at(60))   # a second scan of the same ticket
        self.drain(at(30), env={**ENV, **TWILIO})
        self.drain(at(90), env={**ENV, **TWILIO})
        self.assertEqual(len(self.texts()), 1)


# ---------------------------------------------------------------------------
# quiet hours
# ---------------------------------------------------------------------------

class QuietHours(LiveAlertBase):
    def starting(self, hound, tip):
        return {**self.ticket(hound), "kind": "hound_user_bet", "commence_time": ls.iso(tip)}

    def test_a_starting_alert_is_held_in_quiet_hours_and_dropped_once_the_game_has_started(self):
        user, hound = self.sms_member(quiet_start=22, quiet_end=8)
        tip = datetime(2026, 10, 21, 3, 14, tzinfo=timezone.utc)            # 23:14 Eastern
        alerts.emit_starting(self.starting(hound, tip), minutes_out=14, now=tip - timedelta(minutes=14))
        self.assertEqual(self.drain(tip - timedelta(minutes=9), env={**ENV, **TWILIO}).get("held_quiet"), 1)
        self.drain(datetime(2026, 10, 21, 13, 0, tzinfo=timezone.utc), env={**ENV, **TWILIO})   # 09:00 Eastern, next day
        self.assertEqual(self.texts(), [], "a 'tips off in 14 min' that is ten hours old is never sent")

    def test_the_same_alert_goes_out_when_quiet_hours_end_before_the_tip(self):
        user, hound = self.sms_member(quiet_start=22, quiet_end=8)
        tip = datetime(2026, 10, 21, 12, 10, tzinfo=timezone.utc)           # 08:10 Eastern
        made = tip - timedelta(minutes=14)                                  # 07:56, inside quiet hours
        alerts.emit_starting(self.starting(hound, tip), minutes_out=14, now=made)
        self.assertEqual(self.drain(made + timedelta(minutes=2), env={**ENV, **TWILIO}).get("held_quiet"), 1)
        self.drain(datetime(2026, 10, 21, 12, 1, tzinfo=timezone.utc), env={**ENV, **TWILIO})   # 08:01, 9 min before the tip
        self.assertEqual(len(self.texts()), 1)

    def test_a_live_update_is_dropped_when_it_waited_past_its_useful_life(self):
        user, hound = self.sms_member(quiet_start=22, quiet_end=8, event_toggles={"live": True})
        night = datetime(2026, 10, 21, 3, 0, tzinfo=timezone.utc)
        alerts.emit_live({**self.starting(hound, night), "commence_time": ls.iso(night)}, "half",
                         {"home_score": 50, "away_score": 54, "status": "winning", "label": "Halftime"}, now=night)
        self.drain(datetime(2026, 10, 21, 13, 0, tzinfo=timezone.utc), env={**ENV, **TWILIO})
        self.assertEqual(self.texts(), [])


# ---------------------------------------------------------------------------
# SMS length
# ---------------------------------------------------------------------------

class SmsLength(LiveAlertBase):
    def event(self, kind="starting", n=1, **over):
        payload = {"hound_name": "DRAKEO", "hound_id": "u-abc", "sport": "NBA", "market": "moneyline",
                   "selection": "Atlanta Hawks to win", "price": 110, "stake_units": 2.0, "minutes_out": 14,
                   "away_team": "Atlanta Hawks", "home_team": "Boston Celtics", "start_utc": "2026-10-21T23:30:00Z"}
        payload.update(over)
        return {"id": n, "kind": kind, "created_utc": "2026-10-21T23:15:00Z", "payload": payload}

    def assertTextOk(self, text, limit):
        self.assertLessEqual(len(text), limit, text)
        self.assertTrue(text.endswith("Reply STOP to end."), text)
        self.assertTrue(text.startswith("LINEHOUND (paper): "), text)
        self.assertTrue(text.isascii(), "a non-GSM character turns a text into 70-character segments: " + text)

    def test_one_starting_soon_is_a_single_segment(self):
        text = render.sms_text([self.event()], unit_size.Sizing("fixed", 25, None, 2500), "America/New_York", ENV)
        self.assertTextOk(text, 160)
        self.assertIn("tips off in 14 min", text)
        self.assertIn("stake $50", text)

    def test_two_tickets_fit_one_segment_by_dropping_the_link_first(self):
        text = render.sms_text([self.event(n=1), self.event(n=2, selection="Over 221.5", market="total")],
                               unit_size.fixed(25), "America/New_York", ENV)
        self.assertTextOk(text, 160)
        self.assertNotIn("http", text)

    def test_a_long_burst_is_summarised_inside_a_single_segment(self):
        text = render.sms_text([self.event(n=i) for i in range(1, 8)], unit_size.fixed(25), "America/New_York", ENV)
        self.assertTextOk(text, 160)
        self.assertIn("+6 more", text)

    def test_a_very_long_name_is_clipped_not_overflowed(self):
        long_name = "Q" * 90
        text = render.sms_text([self.event(hound_name=long_name)], unit_size.fixed(25), "America/New_York", ENV)
        self.assertTextOk(text, 160)

    def test_every_live_moment_fits_one_segment(self):
        for moment, over in (("start", {"home_score": 0, "away_score": 0, "status": "winning", "label": "12:00 - 1st"}),
                             ("half", {"home_score": 58, "away_score": 54, "status": "losing", "label": "Halftime"}),
                             ("flip3", {"home_score": 104, "away_score": 102, "status": "losing", "label": "1:12 - 4th"}),
                             ("final", {"home_score": 110, "away_score": 112, "status": "winning", "label": "Final"})):
            text = render.sms_text([self.event("live", moment=moment, **over)], unit_size.fixed(25), "America/New_York", ENV)
            self.assertTextOk(text, 160)

    def test_the_older_shapes_still_hold_the_old_ceiling(self):
        text = render.sms_text([self.event("placed", n=i) for i in range(1, 10)], unit_size.fixed(25),
                               "America/New_York", ENV)
        self.assertLessEqual(len(text), render.SMS_MAX)
        self.assertTrue(text.endswith("Reply STOP to end."))

    def test_the_push_payload_carries_its_own_tag_per_short_lived_kind(self):
        starting = render.push_payload([self.event()], None, "America/New_York", ENV)
        placed = render.push_payload([self.event("placed")], None, "America/New_York", ENV)
        self.assertEqual((starting["tag"], placed["tag"]), ("bet-alert-starting", "bet-alert"))
        self.assertTrue(starting["paper"])


# ---------------------------------------------------------------------------
# preferences
# ---------------------------------------------------------------------------

class TogglePrefs(LiveAlertBase):
    def test_partial_updates_merge_and_the_legacy_events_field_still_maps(self):
        user, _ = self.member()
        got = alerts.update_prefs(user.id, {"event_toggles": {"live": True}})
        self.assertEqual(got["event_toggles"], {"placed": True, "starting": True, "live": True, "settled": True})
        got = alerts.update_prefs(user.id, {"events": "settled"})
        self.assertEqual(got["event_toggles"], {"placed": False, "starting": True, "live": True, "settled": True})
        self.assertEqual(got["events"], "settled")
        got = alerts.update_prefs(user.id, {"event_toggles": {"placed": False, "settled": False}})
        self.assertEqual(got["events"], "none")

    def test_a_member_from_before_the_toggles_keeps_their_old_choice(self):
        user, _ = self.member(events="placed")
        with alerts.connect() as conn:
            conn.execute("UPDATE alert_prefs SET event_toggles = NULL WHERE user_id = ?", (user.id,))
        self.assertEqual(alerts.get_prefs(user.id)["event_toggles"],
                         {"placed": True, "starting": True, "live": False, "settled": False})

    def test_unknown_types_and_non_booleans_are_refused(self):
        user, _ = self.member()
        for bad in ({"nope": True}, {"live": "yes"}, {"live": 1}):
            with self.assertRaises(alerts.AlertError) as ctx:
                alerts.update_prefs(user.id, {"event_toggles": bad})
            self.assertEqual(ctx.exception.code, "toggles_invalid")
        with self.assertRaises(alerts.AlertError):
            alerts.update_prefs(user.id, {"events": "everything"})


try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


@unittest.skipUnless(HAS_FASTAPI, "needs FastAPI")
class AccountAlertsRoute(LiveAlertBase):
    def setUp(self):
        super().setUp()
        from api import alerts_routes
        self.api = alerts_routes

    def put(self, user, **body):
        from fastapi import Response
        return self.api.put_alerts(self.api.AlertsRequest(**body), Response(), current_user=user, _rl=None)

    def test_the_status_lists_the_four_toggles_with_their_defaults_and_which_channels_carry_each(self):
        user, _ = self.member()
        out = self.api._payload(user)
        self.assertEqual(out["event_toggles"], {"placed": True, "starting": True, "live": False, "settled": True})
        self.assertEqual(out["event_channels"]["starting"], ["push", "sms"])
        self.assertEqual(out["event_channels"]["live"], ["push", "sms"])
        self.assertEqual(out["event_channels"]["placed"], ["email", "push", "sms"])
        self.assertEqual(out["events"], "both")

    def test_a_put_flips_one_toggle_and_leaves_the_rest(self):
        user, _ = self.member()
        out = self.put(user, event_toggles={"live": True})
        self.assertEqual(out["event_toggles"], {"placed": True, "starting": True, "live": True, "settled": True})
        out = self.put(user, event_toggles={"starting": False})
        self.assertEqual(out["event_toggles"], {"placed": True, "starting": False, "live": True, "settled": True})

    def test_a_bad_toggle_is_a_422_with_a_code(self):
        from fastapi import HTTPException
        user, _ = self.member()
        with self.assertRaises(HTTPException) as ctx:
            self.put(user, event_toggles={"live": "on"})
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail["error"]), (422, "toggles_invalid"))

    def test_the_old_events_field_still_works(self):
        user, _ = self.member()
        out = self.put(user, events="placed")
        self.assertEqual(out["event_toggles"]["settled"], False)

    def test_the_private_feed_words_a_starting_alert(self):
        user, hound = self.member()
        alerts.emit_starting({**self.ticket(hound), "kind": "hound_user_bet", "commence_time": ls.iso(START)},
                             minutes_out=14, now=at(0))
        body = self.api.feed(alerts.get_prefs(user.id)["feed_token"], _rl=None).body.decode()
        self.assertIn("tips off in 14 min", body)


# ---------------------------------------------------------------------------
# the feeds carry the progress; the scan rides the grading pass
# ---------------------------------------------------------------------------

class ProgressFromTheFeeds(unittest.TestCase):
    def test_an_espn_answer_carries_period_clock_status_and_label(self):
        event = espn_event("401", "Brooklyn Nets", "Charlotte Hornets", state="in", name="STATUS_HALFTIME",
                           completed=False, hs=58, as_=54, detail="Halftime")
        event["competitions"][0]["status"].update({"period": 2, "displayClock": "0.0"})
        board = {"events": [event]}
        wanted = [{"key": "k", "home_team": "Brooklyn Nets", "away_team": "Charlotte Hornets",
                   "start": utc("2026-10-21T23:30:00Z")}]
        got = ls.espn_answers(board, "nba", wanted, "2026-10-21T01:00:00Z")["k"]
        self.assertEqual(got["progress"], {"period": 2, "clock": "0.0", "name": "STATUS_HALFTIME", "label": "Halftime"})
        self.assertEqual(got["state"], ls.LIVE)

    def test_an_mlb_answer_names_the_inning_when_the_linescore_is_in_the_request(self):
        instances = [{"state": "live", "detailed_state": "In Progress", "home_score": 3, "away_score": 2,
                      "current_inning": 8, "inning_state": "Top", "start_time_utc": "2026-10-21T23:10:00Z"}]
        got = ls.mlb_answer(1, lambda pk: instances)
        self.assertEqual(got["progress"], {"period": 8, "clock": None, "name": "TOP", "label": "Top 8th"})
        self.assertIsNone(ls.mlb_answer(1, lambda pk: [{**instances[0], "detailed_state": "Scheduled"}])["progress"])

    def test_the_default_mlb_request_is_unchanged_for_every_other_caller(self):
        from src.providers import mlb
        payload = {"dates": [{"games": [{"gamePk": 5, "gameDate": "2026-10-21T23:10:00Z", "status": {"detailedState": "In Progress",
                   "abstractGameState": "Live"}, "linescore": {"currentInning": 6, "inningState": "Middle"}, "teams": {}}]}]}
        with mock.patch.object(mlb, "_get_json", return_value=payload):
            plain = mlb.fetch_game_instances(5)[0]
            extra = mlb.fetch_game_instances(5, with_progress=True)[0]
        self.assertNotIn("current_inning", plain)
        self.assertEqual((extra["current_inning"], extra["inning_state"]), (6, "Middle"))


class RidesTheGradingPass(LiveCase):
    """The real loop: a ticket on a real ledger, a fake scoreboard, the alert outbox read back."""

    def setUp(self):
        super().setUp()
        import tempfile
        self._app = tempfile.TemporaryDirectory()
        self.addCleanup(self._app.cleanup)
        patch = mock.patch.object(users_store, "db_path", lambda: Path(self._app.name) / "app.db")
        patch.start()
        self.addCleanup(patch.stop)
        self.user = users_store.create_user(ADDRESS, status="active", plan="free")
        self.hound = user_store.create_hound(self.user.id, spec_dict(name="Drakeo", sports=["NBA"]))
        alerts.ensure_prefs(self.user.id)
        alerts.update_prefs(self.user.id, {"channels": {"email": True}, "event_toggles": {"live": True}})

    def board(self, *events):
        return {"events": list(events)}

    def pass_at(self, when, feed, **kw):
        return self.run_pass(utc(when), feed, **kw)

    def moments(self):
        return [(e["kind"], e["payload"].get("moment")) for e in reversed(alerts.events_for(self.user.id, limit=100))]

    def test_starting_then_live_then_final_before_the_grade_then_settled(self):
        self.write(user_bet(1, hound=self.hound["id"], side="home"))
        pre = self.pass_at("2026-10-21T23:17:00Z", Fake({}))
        self.assertEqual(pre["alerts"]["starting"], 1)
        self.assertEqual(pre["fetch"], None, "before the tip the loop asks nobody, and the alert scan asked nobody either")
        live = espn_event("401", "Brooklyn Nets", "Charlotte Hornets", state="in", name="STATUS_IN_PROGRESS",
                          completed=False, hs=2, as_=0, date="2026-10-21T23:30Z", detail="11:30 - 1st")
        live["competitions"][0]["status"].update({"period": 1, "displayClock": "11:30"})
        feed = Fake({NBA_URL: self.board(live)})
        self.pass_at("2026-10-21T23:33:00Z", feed)
        self.assertEqual(len(feed.urls), 1, "one scoreboard request served the grade loop AND the alert scan")
        final = Fake({NBA_URL: self.board(espn_event("401", "Brooklyn Nets", "Charlotte Hornets"))})
        done = self.pass_at("2026-10-22T02:05:00Z", final)
        self.assertEqual(done["graded"], 1)
        self.assertEqual(len(final.urls), 1)
        self.assertEqual(self.moments(), [("starting", None), ("live", "start"), ("live", "final"), ("settled", None)])

    def test_a_failing_scan_never_stops_a_grade(self):
        self.write(user_bet(1, hound=self.hound["id"], side="home"))
        final = Fake({NBA_URL: self.board(espn_event("401", "Brooklyn Nets", "Charlotte Hornets"))})
        with mock.patch.object(alert_live, "scan", side_effect=RuntimeError("alert store locked")):
            with self.assertLogs("linehound.hounds.live_settle", level="ERROR"):
                done = self.pass_at("2026-10-22T02:05:00Z", final)
        self.assertEqual(done["graded"], 1)
        self.assertIsNone(done["alerts"])

    def test_the_pass_makes_no_request_for_the_alerts(self):
        self.write(user_bet(1, hound=self.hound["id"], side="home"))
        feed = Fake({})
        self.pass_at("2026-10-21T23:17:00Z", feed)          # starting-soon needs only the cache row, never the feed
        self.assertEqual(feed.urls, [])


# ---------------------------------------------------------------------------
# verification, 2026-10-22: the scan is bounded, cross-machine safe, and survives the odd cases
# ---------------------------------------------------------------------------

class _NoLock:
    """Stands in for alerts._lock: a second MACHINE does not share this process's threading lock."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ScanIsBounded(LiveAlertBase):
    def live_tickets(self, hound, n):
        put_game(self.cache, state=ls.LIVE, home_score=50, away_score=48, progress=prog(3, "5:00"),
                 updated=START + timedelta(minutes=5))
        return [self.ticket(hound, i) for i in range(1, n + 1)]

    def test_a_locked_alert_store_ends_the_scan_in_milliseconds_not_seconds(self):
        import sqlite3
        import time as _time
        user, hound = self.member(event_toggles={"live": True})
        tickets = self.live_tickets(hound, 30)
        holder = sqlite3.connect(str(self.db), timeout=0)
        holder.execute("BEGIN IMMEDIATE")                        # another process is mid-write on app.db
        try:
            t0 = _time.perf_counter()
            report = self.scan(START + timedelta(minutes=6), tickets)
            took = _time.perf_counter() - t0
        finally:
            holder.rollback()
            holder.close()
        self.assertTrue(report.get("busy"), report)
        self.assertLess(took, 2.0, "a locked store must cost a pass well under the store's 5 s wait")
        self.assertEqual(self.scan(START + timedelta(minutes=7), tickets)["live"], 30, "the next pass catches up")

    def test_the_scan_stops_at_its_budget_and_takes_finals_first(self):
        user, hound = self.member(event_toggles={"live": True})
        put_game(self.cache, state=ls.LIVE, home_score=50, away_score=48, progress=prog(3), updated=START + timedelta(minutes=5))
        put_game(self.cache, key="g-final", state=ls.FINAL, home_score=101, away_score=99, updated=START + timedelta(hours=2),
                 final=START + timedelta(hours=2))
        tickets = [self.ticket(hound, i) for i in range(1, 6)] + [self.ticket(hound, 99, event_id="g-final")]
        ticks = iter([0.0] + [0.0] * 2 + [10.0] * 100)          # the deadline passes after the first ticket
        report = alert_live.scan(self.cache, START + timedelta(hours=2, minutes=5), {}, tickets=tickets,
                                 clock=lambda: next(ticks))
        self.assertTrue(report.get("out_of_time"))
        self.assertEqual(self.kinds(user), [("live", "final")], "the final (graded next) went first")

    def test_one_bad_ticket_is_skipped_and_the_rest_still_alert(self):
        user, hound = self.member(event_toggles={"live": True})
        tickets = self.live_tickets(hound, 3)
        real = alerts.emit_live

        def flaky(row, *a, **k):
            if row["bet_id"] == "t-2":
                raise ValueError("bad row")
            return real(row, *a, **k)

        with mock.patch.object(alerts, "emit_live", side_effect=flaky):
            with self.assertLogs("linehound.notify.alert_live", level="ERROR") as logs:
                report = self.scan(START + timedelta(minutes=6), tickets)
        self.assertEqual((report["live"], report["errors"]), (2, 1))
        self.assertNotIn("bad row", " ".join(logs.output), "the log names the error type, never its content")

    def test_a_steady_pass_does_no_write_and_opens_two_reads_per_member(self):
        user, hound = self.member(event_toggles={"live": True})
        tickets = self.live_tickets(hound, 40)
        self.scan(START + timedelta(minutes=6), tickets)
        with mock.patch.object(alerts, "emit_live") as emit, mock.patch.object(alerts, "set_live_side") as side, \
                mock.patch.object(alerts, "starting_sent", wraps=alerts.starting_sent) as reads:
            self.scan(START + timedelta(minutes=11), tickets)
        emit.assert_not_called()
        side.assert_not_called()
        self.assertEqual(reads.call_count, 1, "one read per member, not one per ticket")


class PassTiming(LiveCase):
    """The real pass with 200 open tickets: the alert scan must not hold up the grade."""

    def setUp(self):
        super().setUp()
        import tempfile
        self._app = tempfile.TemporaryDirectory()
        self.addCleanup(self._app.cleanup)
        self.app_db = Path(self._app.name) / "app.db"
        patch = mock.patch.object(users_store, "db_path", lambda: self.app_db)
        patch.start()
        self.addCleanup(patch.stop)
        names = ["Alphadog", "Bravodog", "Charlie", "Deltadog", "Echodog"]
        self.hounds = []
        for i, name in enumerate(names):
            user = users_store.create_user(f"m{i}@sample-mail.net", status="active", plan="free")
            self.hounds.append(user_store.create_hound(user.id, spec_dict(name=name, sports=["NBA"])))
            alerts.ensure_prefs(user.id)
            alerts.update_prefs(user.id, {"channels": {"push": True}, "event_toggles": {"live": True}})
        events, bets = [], []
        for g in range(20):
            home, away = f"Home Team{g}", f"Away Team{g}"
            ev = espn_event(f"40{g}", home, away, state="in", name="STATUS_IN_PROGRESS", completed=False, hs=50, as_=48,
                            date="2026-10-21T23:30Z", detail="5:00 - 3rd")
            ev["competitions"][0]["status"].update({"period": 3, "displayClock": "5:00"})
            events.append(ev)
        for n in range(200):
            g = n % 20
            bets.append(user_bet(n, event=f"evt{g}", home=f"Home Team{g}", away=f"Away Team{g}",
                                 hound=self.hounds[n % 5]["id"], side="home" if n % 2 else "away"))
        self.write(*bets)
        self.boards = {NBA_URL: {"events": events}}

    def timed_passes(self, n=3):
        import time as _time
        out = []
        for i in range(n):
            feed = Fake(self.boards)
            t0 = _time.perf_counter()
            report = self.run_pass(utc("2026-10-21T23:40:00Z") + timedelta(minutes=5 * i), feed)
            out.append((_time.perf_counter() - t0, list(feed.urls), report))
        return out

    def test_two_hundred_tickets_same_requests_and_a_bounded_scan(self):
        with mock.patch.object(lv, "alerts_scan", lambda *a, **k: None):
            before = self.timed_passes()
        with alerts.connect() as conn:
            conn.execute("DELETE FROM alert_events")
        lv._OPEN_CACHE.clear()
        self.conn.execute("DELETE FROM live_games")
        after = self.timed_passes()
        self.assertEqual([b[1] for b in before], [a[1] for a in after], "the alerts add no request")
        first = after[0][2]["alerts"]
        self.assertTrue(first["live"] > 0)
        burst_limit = alert_live.SCAN_BUDGET_S + 1.5
        self.assertLess(after[0][0], burst_limit, "a burst of new events is cut off at the scan's budget")
        steady = after[-1][0] - before[-1][0]
        self.assertLess(steady, 1.0, f"a pass with nothing new to say costs well under a second more (got {steady:.3f}s)")


class TwoMachines(LiveAlertBase):
    """Two servers on one app.db: neither machine's threading lock covers the other, the database must."""

    def setUp(self):
        super().setUp()
        patch = mock.patch.object(alerts, "_lock", _NoLock())
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_stale_book_on_the_second_machine_cannot_spend_the_finals_slot(self):
        user, hound = self.member(event_toggles={"live": True})
        t = [self.ticket(hound)]
        stale = alerts.live_book(user.id)                          # machine B read its book before A wrote
        put_game(self.cache, state=ls.LIVE, home_score=50, away_score=54, progress=prog(2, "0:00", "STATUS_HALFTIME", "Halftime"),
                 updated=START + timedelta(minutes=5))
        self.scan(START + timedelta(minutes=6), t)                 # machine A: start + half
        self.assertEqual(alerts.live_count(user.id, "t-1"), 2)
        late_now = START + timedelta(hours=2)
        put_game(self.cache, state=ls.LIVE, home_score=100, away_score=98, progress=prog(4), updated=late_now)
        with mock.patch.object(alerts, "live_book", return_value=(dict(stale[0]), {"t-1": "winning"}, set(stale[2]))):
            self.scan(late_now, t)                                 # machine B: thinks 0 raised and sees a late flip
        self.assertEqual(alerts.live_count(user.id, "t-1"), 2, "the cap held in the insert itself")
        put_game(self.cache, state=ls.FINAL, home_score=100, away_score=98, updated=late_now, final=late_now)
        self.scan(late_now + timedelta(minutes=5), t)
        self.assertEqual([m for _, m in self.kinds(user)], ["start", "half", "final"])

    def test_concurrent_scans_write_each_event_once(self):
        import threading
        user, hound = self.member(event_toggles={"live": True})
        tickets = [self.ticket(hound, i) for i in range(1, 9)]
        put_game(self.cache)
        path = self.dir / "live_settle.db"
        barrier = threading.Barrier(4)
        errors = []

        def machine(now):
            try:
                cache = lv.connect(path)
                barrier.wait()
                alert_live.scan(cache, now, {}, tickets=tickets)
                cache.close()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        runs = [threading.Thread(target=machine, args=(START - timedelta(minutes=14),)) for _ in range(4)]
        for r in runs:
            r.start()
        for r in runs:
            r.join()
        self.assertEqual(errors, [])
        with alerts.connect() as conn:
            got = conn.execute("SELECT kind, COUNT(*), COUNT(DISTINCT bet_id) FROM alert_events GROUP BY kind").fetchall()
        self.assertEqual([tuple(r) for r in got], [("starting", 8, 8)])

    def test_concurrent_live_scans_never_pass_three_per_ticket(self):
        import threading
        user, hound = self.member(event_toggles={"live": True})
        tickets = [self.ticket(hound, i) for i in range(1, 6)]
        path = self.dir / "live_settle.db"
        moments = [
            (START + timedelta(minutes=4), dict(state=ls.LIVE, home_score=2, away_score=0, progress=prog(1, "11:00"))),
            (START + timedelta(minutes=70), dict(state=ls.LIVE, home_score=50, away_score=54,
                                                 progress=prog(2, "0:00", "STATUS_HALFTIME", "Halftime"))),
            (START + timedelta(minutes=140), dict(state=ls.LIVE, home_score=100, away_score=98, progress=prog(4, "4:00"))),
            (START + timedelta(minutes=145), dict(state=ls.LIVE, home_score=100, away_score=104, progress=prog(4, "2:00"))),
        ]
        for now, game in moments + [(START + timedelta(minutes=160), dict(state=ls.FINAL, home_score=110, away_score=112))]:
            put_game(self.cache, updated=now, final=now if game["state"] == ls.FINAL else None, **game)
            barrier = threading.Barrier(3)

            def machine():
                cache = lv.connect(path)
                barrier.wait()
                alert_live.scan(cache, now, {}, tickets=tickets)
                cache.close()

            runs = [threading.Thread(target=machine) for _ in range(3)]
            for r in runs:
                r.start()
            for r in runs:
                r.join()
        for i in range(1, 6):
            self.assertLessEqual(alerts.live_count(user.id, f"t-{i}"), 3)
            with alerts.connect() as conn:
                keys = [r[0] for r in conn.execute("SELECT bet_id FROM alert_events WHERE user_id = ? AND kind = 'live' "
                                                   "AND bet_id LIKE ?", (user.id, f"t-{i}#%")).fetchall()]
            self.assertIn(alerts.live_key(f"t-{i}", "final"), keys, "the final kept its slot")


class StaleAndSchedule(LiveAlertBase):
    def row(self, hound, tip):
        return {**self.ticket(hound), "kind": "hound_user_bet", "commence_time": ls.iso(tip)}

    def test_starting_dropped_after_twenty_minutes_and_live_after_thirty(self):
        cases = (("starting", 19, 1), ("starting", 21, 0), ("live", 29, 1), ("live", 31, 0))
        for i, (kind, wait, sent) in enumerate(cases):
            with self.subTest(kind=kind, wait=wait):
                self.http = FakeHttp()
                user, hound = self.member(email=f"stale{i}@sample-mail.net", name=f"Stale Dog{i}", channels={"push": False},
                                          event_toggles={"live": True})
                alerts.sms_opt_in(user.id, "(555) 234-5678", now=at(-60))
                alerts.update_prefs(user.id, {"channels": {"sms": True}})
                made = at(0)
                row = self.row(hound, made + timedelta(hours=3))           # the tip is far off: only the age decides
                if kind == "starting":
                    alerts.emit_starting(row, minutes_out=14, now=made)
                else:
                    alerts.emit_live(row, "half", {"home_score": 1, "away_score": 2, "status": "winning"}, now=made)
                self.drain(made + timedelta(minutes=wait), env={**ENV, **TWILIO})
                self.assertEqual(len(self.texts()), sent)

    def test_starting_soon_follows_the_scoreboards_start_not_the_odds_feeds(self):
        user, hound = self.member()
        real_tip = START + timedelta(minutes=85)                       # the odds feed is 85 minutes early
        put_game(self.cache)
        self.cache.execute("UPDATE live_games SET sched_utc=? WHERE game_key=?", (ls.iso(real_tip), GAME))
        t = [self.ticket(hound)]
        self.assertEqual(self.scan(START - timedelta(minutes=14), t)["starting"], 0, "not off the odds feed's time")
        self.assertEqual(self.scan(real_tip - timedelta(minutes=13), t)["starting"], 1)
        event = alerts.events_for(user.id)[0]
        self.assertEqual((event["payload"]["minutes_out"], event["payload"]["start_utc"]), (13, ls.iso(real_tip)))

    def test_a_scoreboard_time_a_day_away_is_not_trusted(self):
        user, hound = self.member()
        put_game(self.cache)
        self.cache.execute("UPDATE live_games SET sched_utc=? WHERE game_key=?", (ls.iso(START + timedelta(days=1)), GAME))
        self.assertEqual(self.scan(START - timedelta(minutes=14), [self.ticket(hound)])["starting"], 1)

    def test_a_held_starting_alert_is_not_dropped_by_the_odds_feeds_earlier_time(self):
        user, hound = self.sms_member()
        real_tip = START + timedelta(minutes=85)
        put_game(self.cache)
        self.cache.execute("UPDATE live_games SET sched_utc=? WHERE game_key=?", (ls.iso(real_tip), GAME))
        made = real_tip - timedelta(minutes=13)
        self.scan(made, [self.ticket(hound)])
        self.drain(made + timedelta(seconds=30), env={**ENV, **TWILIO})
        self.assertEqual(len(self.texts()), 1, "the payload carries the real start, so the dispatcher keeps it")

    def test_postponed_and_cancelled_games_send_nothing_with_every_toggle_on(self):
        user, hound = self.member(event_toggles={"live": True})
        t = [self.ticket(hound)]
        for state in (ls.POSTPONED, ls.CANCELLED):
            put_game(self.cache, state=state, updated=START + timedelta(minutes=5))
            for minutes in (-14, -5, 5, 30, 120):
                self.scan(START + timedelta(minutes=minutes), t)
        self.assertEqual(alerts.events_for(user.id), [])


class PositionFromTheTicket(unittest.TestCase):
    def test_a_favourite_leading_by_less_than_the_spread_is_losing_the_ticket(self):
        home_fav = {"market": "spread", "side": "home", "line": -6.5}
        self.assertEqual(alert_live.ticket_status(home_fav, 70, 66), "losing")          # up 4, laying 6.5
        self.assertEqual(alert_live.ticket_status(home_fav, 74, 66), "winning")
        away_dog = {"market": "spread", "side": "away", "line": 6.5}
        self.assertEqual(alert_live.ticket_status(away_dog, 70, 66), "winning", "the other side of the same score")
        self.assertEqual(alert_live.ticket_status({"market": "spread", "side": "away", "line": -1.5}, 3, 4), "losing")

    def test_totals_read_against_the_running_total(self):
        over = {"market": "total", "side": "over", "line": 220.5}
        self.assertEqual(alert_live.ticket_status(over, 100, 100), "losing")
        self.assertEqual(alert_live.ticket_status(over, 111, 110), "winning")
        self.assertEqual(alert_live.ticket_status({**over, "side": "under"}, 111, 110), "losing")
        self.assertEqual(alert_live.ticket_status({**over, "line": 221.0}, 111, 110), "push")

    def test_moneyline_follows_the_side(self):
        self.assertEqual(alert_live.ticket_status({"market": "moneyline", "side": "away", "sport": "MLB"}, 3, 5), "winning")
        self.assertEqual(alert_live.ticket_status({"market": "moneyline", "side": "home", "sport": "MLB"}, 3, 5), "losing")


class GradedOrVoidedBeforeTheStart(RidesTheGradingPass):
    def test_a_ticket_graded_or_voided_before_its_start_raises_nothing(self):
        self.write(user_bet(1, hound=self.hound["id"], side="home"), user_bet(2, hound=self.hound["id"], side="away"))
        self.write({"kind": user_settle.KIND_GRADED, "bet_id": "bet1", "result": "VOID", "hound_id": self.hound["id"]},
                   {"kind": user_settle.KIND_GRADED, "bet_id": "bet2", "result": "LOSS", "hound_id": self.hound["id"]})
        pre = self.pass_at("2026-10-21T23:17:00Z", Fake({}))
        self.assertEqual(pre["alerts"]["starting"], 0)
        self.assertEqual(self.moments(), [])

    def test_the_pass_stores_the_scoreboards_own_start_for_the_next_pass(self):
        self.write(user_bet(1, hound=self.hound["id"], side="home"))
        late_tip = espn_event("401", "Brooklyn Nets", "Charlotte Hornets", state="pre", name="STATUS_SCHEDULED",
                              completed=False, hs=0, as_=0, date="2026-10-22T00:55Z", detail="8:55 PM ET")
        self.pass_at("2026-10-21T23:31:00Z", Fake({NBA_URL: self.board(late_tip)}))
        row = self.conn.execute("SELECT state, sched_utc FROM live_games").fetchone()
        self.assertEqual((row["state"], row["sched_utc"]), (ls.UPCOMING, "2026-10-22T00:55:00Z"))
        nxt = self.pass_at("2026-10-22T00:42:00Z", Fake({NBA_URL: self.board(late_tip)}))
        self.assertEqual(nxt["alerts"]["starting"], 1)


class OddCases(LiveAlertBase):
    def test_a_live_row_with_no_score_still_reads_cleanly_and_a_scoreless_final_is_skipped(self):
        user, hound = self.member(event_toggles={"live": True})
        put_game(self.cache, state=ls.LIVE, progress=prog(1, "11:00", label="11:00 - 1st"), updated=START + timedelta(minutes=2))
        self.scan(START + timedelta(minutes=3), [self.ticket(hound)])
        event = alerts.events_for(user.id)[0]
        line = render.event_line(event, None)
        self.assertNotIn("None", line)
        self.assertNotIn("?", line)
        put_game(self.cache, state=ls.FINAL, updated=START + timedelta(hours=2), final=START + timedelta(hours=2))
        self.scan(START + timedelta(hours=2, minutes=1), [self.ticket(hound)])
        self.assertEqual([m for _, m in self.kinds(user)], ["start"])

    def test_a_hound_deleted_mid_pass_is_skipped_and_the_others_still_alert(self):
        user, hound = self.member()
        other_user, other = self.member(email="second@sample-mail.net", name="Second Dog")
        put_game(self.cache)
        tickets = [self.ticket(hound, 1), self.ticket(other, 2)]
        real = user_store.get_hound
        with mock.patch.object(user_store, "get_hound", lambda hid, **k: None if hid == hound["id"] else real(hid, **k)):
            report = self.scan(START - timedelta(minutes=14), tickets)
        self.assertEqual((report["starting"], report["errors"]), (1, 0))
        self.assertEqual(alerts.events_for(user.id), [])
        with mock.patch.object(user_store, "get_hound", side_effect=RuntimeError("row gone")):
            with self.assertLogs("linehound.notify.alert_live", level="ERROR"):
                report = self.scan(START - timedelta(minutes=13), tickets)
        self.assertEqual(report["errors"], 2)

    def test_a_score_stamped_by_a_machine_whose_clock_runs_ahead_is_still_fresh(self):
        user, hound = self.member(event_toggles={"live": True})
        now = START + timedelta(minutes=4)
        put_game(self.cache, state=ls.LIVE, home_score=0, away_score=2, progress=prog(1), updated=now + timedelta(minutes=3))
        self.assertEqual(self.scan(now, [self.ticket(hound)])["live"], 1)

    def test_a_game_that_starts_after_midnight_utc(self):
        user, hound = self.member()
        tip = datetime(2026, 10, 22, 0, 5, tzinfo=timezone.utc)
        put_game(self.cache, start=tip)
        report = self.scan(datetime(2026, 10, 21, 23, 52, tzinfo=timezone.utc), [self.ticket(hound, start=ls.iso(tip))])
        self.assertEqual(report["starting"], 1)
        self.assertEqual(alerts.events_for(user.id)[0]["payload"]["minutes_out"], 13)

    def test_quiet_hours_follow_the_clock_change(self):
        prefs = {"quiet_start": 22, "quiet_end": 8, "tz": "America/New_York"}
        # 2026-11-01: Eastern goes from EDT (-4) to EST (-5) at 06:00Z. 12:30Z is 07:30 EST: still quiet.
        self.assertTrue(dispatch.in_quiet_hours(prefs, datetime(2026, 11, 1, 12, 30, tzinfo=timezone.utc)))
        self.assertFalse(dispatch.in_quiet_hours(prefs, datetime(2026, 11, 1, 13, 5, tzinfo=timezone.utc)))
        self.assertFalse(dispatch.in_quiet_hours(prefs, datetime(2026, 10, 31, 12, 30, tzinfo=timezone.utc)))  # 08:30 EDT

    def test_a_unicode_team_name_keeps_the_text_to_one_plain_segment(self):
        event = {"id": 1, "kind": "live", "created_utc": "2026-10-21T23:15:00Z", "payload": {
            "hound_name": "DRAKEO", "hound_id": "u-abc", "sport": "SOCCER", "market": "moneyline",
            "selection": "Beşiktaş to win", "price": 150, "stake_units": 2.0, "moment": "flip2",
            "away_team": "ŁKS Łódź", "home_team": "Beşiktaş", "home_score": 2, "away_score": 1,
            "status": "winning", "label": "78'", "start_utc": "2026-10-21T23:30:00Z"}}
        text = render.sms_text([event], unit_size.fixed(25), "America/New_York", ENV)
        self.assertTrue(text.isascii(), text)
        self.assertLessEqual(len(text), 160)
        self.assertIn("Besiktas", text)
        self.assertTrue(text.endswith("Reply STOP to end."))
        many = render.sms_text([dict(event, id=i) for i in range(5)], unit_size.fixed(25), "America/New_York", ENV)
        self.assertTrue(many.isascii() and len(many) <= 160, many)


class ChannelsAndPayloads(LiveAlertBase):
    def test_all_channels_off_sends_nothing(self):
        user, hound = self.member(channels={"email": False, "push": False, "sms": False, "native": False},
                                  event_toggles={"live": True})
        row = {**self.ticket(hound), "kind": "hound_user_bet", "commence_time": ls.iso(START)}
        alerts.emit_placed(row, now=at(0))
        alerts.emit_starting(row, minutes_out=14, now=at(1))
        alerts.emit_live(row, "start", {"home_score": 0, "away_score": 0, "status": "winning"}, now=at(2))
        alerts.emit_settled(row, {"result": "win", "profit_units": 2.2}, now=at(3))
        self.drain(at(60), env={**ENV, **TWILIO})
        self.assertEqual(self.http.calls, [])

    def test_the_push_payload_carries_the_bet_and_nothing_about_the_member(self):
        user, hound = self.sms_member(event_toggles={"live": True})
        row = {**self.ticket(hound), "kind": "hound_user_bet", "commence_time": ls.iso(START)}
        alerts.emit_live(row, "half", {"home_score": 50, "away_score": 54, "status": "winning", "label": "Halftime"}, now=at(0))
        event = alerts.events_for(user.id)[0]
        payload = render.push_payload([event], unit_size.fixed(25), "America/New_York", ENV)
        self.assertEqual(set(payload), {"title", "body", "url", "tag", "paper"})
        blob = json.dumps(payload)
        for secret in (ADDRESS, "234-5678", "2345678", str(user.id) + "&", "user_id"):
            self.assertNotIn(secret, blob)
        self.assertIn(hound["id"], payload["url"])

    def test_defaults_are_placed_starting_settled_on_and_live_off(self):
        self.assertEqual(alerts.DEFAULT_TOGGLES, {"placed": True, "starting": True, "live": False, "settled": True})
        user, _ = self.member()
        self.assertEqual(alerts.get_prefs(user.id)["event_toggles"], alerts.DEFAULT_TOGGLES)


if __name__ == "__main__":
    unittest.main()
