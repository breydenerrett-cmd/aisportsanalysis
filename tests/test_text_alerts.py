"""Text alerts (owner, 2026-10-28): the MORNING lineup and the private RSS bridge to Zapier.

What is pinned, and why:
  * the lineup is made once per member per LOCAL day, never before the morning hour, never when no hound has a game, and only
    for a member who has the "Morning lineup" switch on (a missing value counts as on);
  * it is worded per hound ("Chalk: watching 4 MLB games (moneyline). Decides by 2:10 PM PT.") and rides the existing outbox,
    so email, push and (paid) text all carry it and the send log dedupes it;
  * the private feed is looked up by the SHA-256 of a secret shown once; a wrong, replaced, reset or free member's secret is
    a plain 404; each item is the text the SMS channel would send; nothing in it identifies the member beyond hound names.
Every clock is injected; every path is a temp path; every channel is a fake transport.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from src.hounds import unit_size
from src.notify import alert_channels as ch
from src.notify import alert_dispatch as dispatch
from src.notify import alert_morning as morning
from src.notify import alert_render as render
from src.notify import alerts
from src.notify.pacific_fallback import PACIFIC_FALLBACK
from tests._hounds_user_fixtures import spec_dict
from tests.test_bet_alerts import ADDRESS, ENV, PAID, TWILIO, Base, at

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

PACIFIC = "America/Los_Angeles"
EASTERN = "America/New_York"
NINE_PT = datetime(2026, 10, 28, 16, 0, 0, tzinfo=timezone.utc)        # 9:00 PDT, 12:00 EDT
FIRST_PITCH = datetime(2026, 10, 28, 23, 10, 0, tzinfo=timezone.utc)   # 4:10 PM PDT; lock 120 min earlier = 2:10 PM PT


def slate(mlb=4, nba=0, start=FIRST_PITCH):
    families = []
    for code, n in (("MLB", mlb), ("NBA", nba)):
        if n:
            families.append({"code": code, "label": code, "live": [], "upcoming_24h": [
                {"event_id": f"{code}-{i}", "start_utc": alerts.iso(start + timedelta(minutes=30 * i))} for i in range(n)]})
    return {"families": families}


class MorningBase(Base):
    def member(self, email=ADDRESS, name="Chalk Chihuahua", sports=("MLB",), tz=PACIFIC, channels=None, **prefs):
        from src.appstate import users as users_store
        from src.hounds import user_store
        user = users_store.create_user(email, status="active", plan="free")
        hound = user_store.create_hound(user.id, spec_dict(name=name, sports=list(sports)))
        alerts.ensure_prefs(user.id, now=at(-3600))
        alerts.update_prefs(user.id, {**prefs, "tz": tz, "channels": channels if channels is not None else {"email": True}})
        return user, hound

    def run_at(self, when, families=None, **kw):
        data = families if families is not None else slate()
        return morning.run(when, slate=lambda: data, **kw)

    def events(self, user, kind="morning"):
        return [e for e in alerts.events_for(user.id) if e["kind"] == kind]


class MorningLineup(MorningBase):
    def test_nothing_before_the_morning_hour_and_one_event_at_it(self):
        user, hound = self.member()
        self.assertEqual(self.run_at(NINE_PT - timedelta(minutes=1)), 0)
        self.assertEqual(self.events(user), [])
        self.assertEqual(self.run_at(NINE_PT), 1)
        (event,) = self.events(user)
        self.assertEqual(event["payload"]["lines"],
                         ["Chalk Chihuahua: watching 4 MLB games (moneyline). Decides by 2:10 PM PT."])

    def test_once_per_local_day_then_again_tomorrow(self):
        user, _ = self.member()
        self.assertEqual(self.run_at(NINE_PT), 1)
        self.assertEqual(self.run_at(NINE_PT + timedelta(minutes=10)), 0)
        self.assertEqual(self.run_at(NINE_PT + timedelta(hours=2)), 0)
        tomorrow = NINE_PT + timedelta(days=1)
        self.assertEqual(self.run_at(tomorrow, families=slate(start=tomorrow + timedelta(hours=7))), 1)
        self.assertEqual(len(self.events(user)), 2)

    def test_a_late_server_does_not_text_this_morning_in_the_afternoon(self):
        user, _ = self.member()
        self.assertEqual(self.run_at(NINE_PT + timedelta(hours=4)), 0)       # 1 PM Pacific
        self.assertEqual(self.events(user), [])

    def test_no_games_means_no_message_and_a_quiet_hound_is_left_out(self):
        user, _ = self.member()
        self.assertEqual(self.run_at(NINE_PT, families={"families": []}), 0)
        self.assertEqual(self.events(user), [])
        from src.hounds import user_store
        user_store.create_hound(user.id, spec_dict(name="Court Jester", sports=["NBA"]))      # no NBA game today
        self.assertEqual(self.run_at(NINE_PT), 1)
        (event,) = self.events(user)
        self.assertEqual(len(event["payload"]["lines"]), 1)
        self.assertNotIn("Court Jester", render.event_line(event, None))

    def test_a_game_that_already_started_or_is_after_tonights_end_is_not_listed(self):
        user, _ = self.member()
        started = slate(mlb=1, start=NINE_PT - timedelta(hours=1))
        self.assertEqual(self.run_at(NINE_PT, families=started), 0)
        tomorrow_night = slate(mlb=1, start=NINE_PT + timedelta(hours=30))          # 3 PM tomorrow: not tonight
        self.assertEqual(self.run_at(NINE_PT, families=tomorrow_night), 0)

    def test_two_hounds_two_sentences_and_the_decided_count(self):
        from src.hounds import user_store
        user, hound = self.member()
        user_store.create_hound(user.id, spec_dict(name="Court Jester", sports=["NBA", "MLB"], markets=["moneyline", "spread"]),
                                 now=datetime.now(timezone.utc) + timedelta(minutes=5))      # made later: it is the second sentence
        alerts.emit_placed(self.bet_row(hound), now=NINE_PT - timedelta(hours=1))      # decided before the lineup
        self.assertEqual(self.run_at(NINE_PT, families=slate(mlb=4, nba=2)), 1)
        (event,) = self.events(user)
        first, second = event["payload"]["lines"]
        self.assertEqual(first, "Chalk Chihuahua: watching 4 MLB games (moneyline). Decides by 2:10 PM PT. 1 already decided today.")
        self.assertEqual(second, "Court Jester: watching 4 MLB games, 2 NBA games (moneyline/spread). Decides by 2:10 PM PT.")
        self.assertEqual(event["payload"]["hound_name"], "Your hounds")

    def test_the_switch_turns_it_off_and_a_missing_value_means_on(self):
        user, _ = self.member()
        self.assertTrue(alerts.get_prefs(user.id)["morning_lineup"])
        alerts.update_prefs(user.id, {"morning_lineup": False})
        self.assertEqual(self.run_at(NINE_PT), 0)
        alerts.update_prefs(user.id, {"morning_lineup": True})
        self.assertEqual(self.run_at(NINE_PT), 1)
        with alerts.connect() as conn:
            conn.execute("UPDATE alert_prefs SET morning_lineup = NULL")           # a member from before the switch existed
        self.assertTrue(alerts.get_prefs(user.id)["morning_lineup"])
        with self.assertRaises(alerts.AlertError):
            alerts.update_prefs(user.id, {"morning_lineup": "yes"})

    def test_a_member_with_every_channel_off_and_no_feed_gets_no_event(self):
        user, _ = self.member(channels={"email": False})
        self.assertEqual(self.run_at(NINE_PT), 0)
        alerts.rotate_feed_token(user.id)                       # a feed to read it from is reason enough
        self.assertEqual(self.run_at(NINE_PT), 1)

    def test_it_follows_the_members_own_zone(self):
        east, _ = self.member(tz=EASTERN)
        self.assertEqual(self.run_at(NINE_PT), 0)                        # 12:00 EDT: past the 9-to-noon window
        six_pt = NINE_PT - timedelta(hours=3)                            # 13:00Z = 9:00 EDT = 6:00 PDT
        self.assertEqual(self.run_at(six_pt - timedelta(minutes=1)), 0)  # 8:59 EDT
        self.assertEqual(self.run_at(six_pt), 1)
        (event,) = self.events(east)
        self.assertIn(" ET.", event["payload"]["lines"][0])              # worded in Eastern, not Pacific
        self.assertNotIn(" PT.", event["payload"]["lines"][0])
        pacific, _ = self.member(email="west.owner@sample-mail.net", name="Westie")
        self.assertEqual(self.run_at(six_pt), 0)                         # 6 AM Pacific: not yet her morning

    def test_an_unknown_zone_falls_back_to_pacific(self):
        zone = morning.member_zone({"tz": "Mars/Olympus"})
        self.assertEqual(NINE_PT.astimezone(zone).hour, 9)

    def test_the_pacific_fallback_matches_the_database_where_there_is_one(self):
        try:
            from zoneinfo import ZoneInfo
            real = ZoneInfo(PACIFIC)
        except Exception:  # noqa: BLE001
            self.skipTest("no tz database on this machine")
        start = datetime(2026, 3, 1, tzinfo=timezone.utc)
        for hours in range(0, 24 * 300, 5):
            moment = start + timedelta(hours=hours)
            self.assertEqual(moment.astimezone(PACIFIC_FALLBACK).replace(tzinfo=None),
                             moment.astimezone(real).replace(tzinfo=None), moment)

    def test_a_failure_for_one_member_does_not_stop_the_next(self):
        bad, _ = self.member()
        good, _ = self.member(email="second.owner@sample-mail.net", name="Second Hound")
        real = morning.lines_for

        def flaky(uid, *a, **k):
            if uid == bad.id:
                raise RuntimeError("boom")
            return real(uid, *a, **k)

        with mock.patch.object(morning, "lines_for", flaky):
            self.assertEqual(self.run_at(NINE_PT), 1)
        self.assertEqual(self.events(bad), [])
        self.assertEqual(len(self.events(good)), 1)


class MorningDelivery(MorningBase):
    def drain_at(self, when, families=None, **kw):
        with mock.patch("src.sports.allsports_view.cached_sports_now", lambda: families or slate()):
            return self.drain(when, **kw)

    def test_the_drain_makes_the_lineup_and_sends_it_once_by_email(self):
        user, _ = self.member()
        self.drain_at(NINE_PT - timedelta(minutes=5))
        self.assertEqual(self.http.emails(), [])
        self.drain_at(NINE_PT)
        self.drain_at(NINE_PT + timedelta(seconds=30))
        self.drain_at(NINE_PT + timedelta(minutes=20))
        (mail_out,) = self.http.emails()
        self.assertIn("What your hound is watching today", mail_out["subject"])
        self.assertIn("Chalk Chihuahua: watching 4 MLB games (moneyline). Decides by 2:10 PM PT.", mail_out["text"])
        self.assertIn("1-800-GAMBLER", mail_out["text"])
        for banned in ("beta", "Bet Check", "profit", "nothing cleared"):
            self.assertNotIn(banned.lower(), (mail_out["subject"] + mail_out["text"]).lower())

    def test_text_carries_it_for_a_paid_member_and_a_free_one_gets_none(self):
        user, _ = self.member()
        alerts.sms_opt_in(user.id, "(555) 234-5678", now=at(-60))
        alerts.update_prefs(user.id, {"channels": {"sms": True}})
        env = {**ENV, **TWILIO}
        self.drain_at(NINE_PT, env=env)
        self.drain_at(NINE_PT + timedelta(seconds=30), env=env)       # the settle window: a burst becomes one message
        texts = [c for c in self.http.calls if "twilio" in c["url"]]
        self.assertEqual(len(texts), 1)
        import urllib.parse
        body = urllib.parse.parse_qs(texts[0]["body"].decode())["Body"][0]
        self.assertTrue(body.startswith("LINEHOUND (paper): Chalk Chihuahua: watching 4 MLB games (moneyline)."), body)
        self.assertIn("Reply STOP", body)
        # a free member: the text channel refuses, the email still goes
        free, _ = self.member(email="free.owner@sample-mail.net", name="Freebie")
        alerts.sms_opt_in(free.id, "(555) 234-9999", now=at(-60))
        alerts.update_prefs(free.id, {"channels": {"sms": True}})
        self.http.calls.clear()
        tomorrow = NINE_PT + timedelta(days=1)
        fams = slate(start=tomorrow + timedelta(hours=7))
        self.drain_at(tomorrow, families=fams, env=env, paid_check=lambda u: u.id != free.id)
        self.drain_at(tomorrow + timedelta(seconds=30), families=fams, env=env, paid_check=lambda u: u.id != free.id)
        sent_to = [urllib.parse.parse_qs(c["body"].decode())["To"][0] for c in self.http.calls if "twilio" in c["url"]]
        self.assertEqual(sent_to, ["+15552345678"])

    def test_quiet_hours_hold_it(self):
        user, _ = self.member(quiet_start=22, quiet_end=10)
        self.drain_at(NINE_PT)
        self.assertEqual(self.http.emails(), [])
        self.assertEqual(len(self.events(user)), 1)              # queued, waiting for the window to open

    def test_a_held_lineup_is_dropped_after_three_hours(self):
        user, _ = self.member(quiet_start=22, quiet_end=14)
        self.drain_at(NINE_PT)
        self.drain_at(NINE_PT + timedelta(hours=4))              # quiet window over at 2 PM PT, lineup is stale by then
        self.assertEqual(self.http.emails(), [])

    def test_the_switch_off_sends_nothing_even_if_the_event_exists(self):
        user, _ = self.member()
        morning.run(NINE_PT, slate=lambda: slate())
        alerts.update_prefs(user.id, {"morning_lineup": False})
        self.drain_at(NINE_PT)
        self.assertEqual(self.http.emails(), [])


@unittest.skipUnless(HAS_FASTAPI, "needs FastAPI")
class PrivateFeed(MorningBase):
    def setUp(self):
        super().setUp()
        from api import alerts_routes
        self.api = alerts_routes
        self.paid = {"on": True}
        patch = mock.patch.object(alerts_routes, "_is_paid", lambda user: self.paid["on"])
        patch.start()
        self.addCleanup(patch.stop)

    def get(self, secret):
        return self.api.feed(secret, _rl=None).body.decode()

    def status(self, secret):
        from fastapi import HTTPException
        try:
            self.api.feed(secret, _rl=None)
        except HTTPException as exc:
            return exc.status_code
        return 200

    def rotate(self, user):
        from fastapi import Response
        return self.api.rotate_feed(Response(), current_user=user, _rl=None)

    def test_only_the_current_secret_opens_it_and_the_rest_are_404(self):
        user, _ = self.member()
        other, _ = self.member(email="other.person@sample-mail.net", name="Rival")
        first = alerts.rotate_feed_token(user.id)
        self.assertEqual(self.status(first), 200)
        second = alerts.rotate_feed_token(user.id)                # a reset revokes the old link
        self.assertEqual((self.status(first), self.status(second)), (404, 200))
        for bad in ("", "short", "x" * 32, "x" * 200, second[:-1] + ("A" if second[-1] != "A" else "B"), str(user.id), ADDRESS):
            self.assertEqual(self.status(bad), 404, bad)
        self.assertEqual(self.status(alerts.rotate_feed_token(other.id)), 200)

    def test_the_link_is_shown_once_and_only_its_hash_is_stored(self):
        user, _ = self.member()
        out = self.rotate(user)
        url = out["feed_url_once"]
        self.assertTrue(url.startswith("https://") and "/alerts/feed/" in url and url.endswith(".xml"))
        secret = url.rsplit("/", 1)[1][: -len(".xml")]
        self.assertNotIn(secret, repr(self.api._payload(user)))   # a later status never carries it
        self.assertEqual(self.api._payload(user)["feed"], {"allowed": True, "set": True})
        with alerts.connect() as conn:
            row = conn.execute("SELECT * FROM alert_prefs WHERE user_id = ?", (user.id,)).fetchone()
        self.assertNotIn(secret, [str(v) for v in tuple(row)])
        self.assertEqual(row["feed_hash"], alerts._hash_token(secret))
        self.assertNotIn(ADDRESS, url)

    def test_a_free_member_cannot_make_or_read_a_feed(self):
        from fastapi import HTTPException
        user, _ = self.member()
        secret = alerts.rotate_feed_token(user.id)                # made while paid
        self.paid["on"] = False
        self.assertEqual(self.status(secret), 404)
        with self.assertRaises(HTTPException) as ctx:
            self.rotate(user)
        self.assertEqual(ctx.exception.status_code, 402)
        self.assertEqual(self.api._payload(user)["feed"]["allowed"], False)

    def test_the_morning_lineup_and_a_decided_bet_are_in_it_worded_like_the_text(self):
        user, hound = self.member()
        secret = alerts.rotate_feed_token(user.id)
        self.run_at(NINE_PT)
        alerts.emit_placed(self.bet_row(hound), now=NINE_PT + timedelta(hours=1))
        body = self.get(secret)
        events = alerts.events_for(user.id)
        self.assertEqual({e["kind"] for e in events}, {"morning", "placed"})
        for event in events:
            expected = render.sms_text([event], unit_size.get(user.id), PACIFIC).removesuffix(render.SMS_STOP).rstrip()
            from html import escape
            self.assertIn(escape(expected, quote=False), body)
        self.assertIn("Chalk Chihuahua: watching 4 MLB games (moneyline). Decides by 2:10 PM PT.", body)
        self.assertIn("Chalk Chihuahua bet Boston Red Sox ML +110", body)
        self.assertNotIn("Reply STOP", body)                       # Zapier's SMS cannot honour STOP
        self.assertEqual(body.count("<item>"), 2)

    def test_the_feed_holds_no_member_identity(self):
        user, hound = self.member()
        secret = alerts.rotate_feed_token(user.id)
        self.run_at(NINE_PT)
        alerts.emit_placed(self.bet_row(hound), now=NINE_PT)
        body = self.get(secret)
        for leak in (ADDRESS, "sample-mail.net", str(user.id) + ":", "feed_hash", "+1555", "alert_prefs"):
            self.assertNotIn(leak, body)
        self.assertNotIn(secret[:10], body.replace(f"/alerts/feed/{secret}.xml", ""))      # the secret appears only in the self link

    def test_a_suspended_members_feed_is_404(self):
        from src.appstate import users as users_store
        user, _ = self.member()
        secret = alerts.rotate_feed_token(user.id)
        with mock.patch.object(users_store, "get_user", lambda uid: type("U", (), {"id": uid, "status": "suspended"})()):
            self.assertEqual(self.status(secret), 404)

    def test_the_feed_is_rate_limited_per_client(self):
        self.assertTrue(self.api._feed_limiter.limit <= 60)
        self.assertIs(self.api._rl_feed is not self.api._rl_public, True)

    def test_the_status_and_put_carry_the_morning_switch(self):
        from fastapi import HTTPException, Response
        user, _ = self.member()
        self.assertEqual(self.api._payload(user)["morning_lineup"], True)
        out = self.api.put_alerts(self.api.AlertsRequest(morning_lineup=False), Response(), current_user=user, _rl=None)
        self.assertEqual(out["morning_lineup"], False)
        with self.assertRaises(HTTPException) as ctx:
            self.api.put_alerts(self.api.AlertsRequest(morning_lineup="no"), Response(), current_user=user, _rl=None)
        self.assertEqual(ctx.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
