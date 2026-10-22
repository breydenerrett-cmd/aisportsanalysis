"""Bet alerts (src/notify/alerts.py, alert_dispatch.py, alert_channels.py, alert_render.py, webpush.py, api/alerts_routes.py).

Every send goes through an injected fake transport and every path is a temp path (the app database, the ledger and the
email send log live in one temp directory); nothing reaches the network or reads the machine's real data/app. What is
pinned, and why:

  * the outbox write can NEVER break a bet write or a grade (a failure is injected into the alert store);
  * an event is emitted once per (member, kind, bet), only for a member hound whose owner opened Alerts, never in replay;
  * the dispatcher batches a burst into one message, never sends an event twice on a channel, honours the per-hour cap
    without dropping alerts, honours the member's channel / event / quiet-hour choices, and retries with backoff;
  * the email says the right things at the member's unit size, escapes everything, carries the 21+/paper/1-800-GAMBLER
    line and no claim of profit and no Bet Check;
  * push is OFF without the VAPID key, SMS is OFF without the Twilio names, SMS is paid-only and opt-in only, and STOP
    is respected; the push payload really decrypts as an RFC 8291 message;
  * the RSS feed answers only to the member's secret token.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.appstate import users as users_store
from src.hounds import unit_size, user_engine, user_settle, user_store
from src.notify import alert_channels as ch
from src.notify import alert_dispatch as dispatch
from src.notify import alert_render as render
from src.notify import alerts
from src.notify import email as mail
from src.notify import webpush
from tests._hounds_user_fixtures import DATE, EVENT, result_row, spec_dict, standard_rows, utc

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

HAS_CRYPTO = webpush._crypto() is not None

KEY = "re_TESTKEY_do_not_leak_0123456789"
ENV = {mail.ENV_KEY: KEY, "PUBLIC_BASE_URL": "https://linehound.app"}
ADDRESS = "alert.tester@sample-mail.net"
T0 = datetime(2026, 10, 21, 18, 0, 0, tzinfo=timezone.utc)
PAID = lambda user: True          # noqa: E731
FREE = lambda user: False         # noqa: E731


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


class FakeHttp:
    """The injected transport: records every request, answers from a queue, then 200."""

    def __init__(self, *answers):
        self.calls, self.answers = [], list(answers)

    def __call__(self, url, headers, body, timeout):
        self.calls.append({"url": url, "headers": dict(headers), "body": body})
        if self.answers:
            return self.answers.pop(0)
        return 200, json.dumps({"id": f"em_{len(self.calls)}"}).encode()

    def emails(self):
        return [json.loads(c["body"]) for c in self.calls if "resend" in c["url"]]


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.db = self.dir / "app.db"
        patch = mock.patch.object(users_store, "db_path", lambda: self.db)
        patch.start()
        self.addCleanup(patch.stop)
        mail._LOGS.clear()
        mail.reset_disabled_notice()
        self.ledger = str(self.dir / "hounds.jsonl")
        self.http = FakeHttp()
        self._n = 0

    def member(self, email=ADDRESS, name="Drakeo", opened=True, channels=None, **prefs):
        user = users_store.create_user(email, status="active", plan="free")
        hound = user_store.create_hound(user.id, spec_dict(name=name))
        if opened:
            alerts.ensure_prefs(user.id, now=at(-3600))
            patch = dict(prefs)
            patch["channels"] = channels if channels is not None else {"email": True}
            alerts.update_prefs(user.id, patch)
        return user, hound

    def bet_row(self, hound, *, price=110, bet_id=None, stake=2.0):
        self._n += 1
        return {"kind": user_engine.KIND_BET, "bet_id": bet_id or f"b-{self._n:04d}", "hound_id": hound["id"],
                "sport": "MLB", "market": "moneyline", "side": "away", "price": price, "line": None,
                "selection": "Boston Red Sox to win", "away_team": "Boston Red Sox", "home_team": "Seattle Mariners",
                "commence_time": "2026-10-21T23:10:00Z", "slate_date": "2026-10-21", "units": stake,
                "stake_units": stake}

    def drain(self, now, **kw):
        kw.setdefault("http", self.http)
        kw.setdefault("env", ENV)
        kw.setdefault("paid_check", PAID)
        return dispatch.drain(now=now, **kw)

    def deliveries(self, channel="email"):
        with alerts.connect() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM alert_deliveries WHERE channel = ? ORDER BY event_id", (channel,)).fetchall()]

    def sizing(self, usd):
        unit_size.save(usd[0], {"mode": "fixed", "unit_usd": usd[1]})


# ---------------------------------------------------------------------------
# the outbox write never breaks a bet
# ---------------------------------------------------------------------------

class EmitsFromTheEngine(Base):
    def run_engine(self, hound, **kw):
        runner = dict(hound, created_at="2026-01-01T00:00:00Z")
        return user_engine.run(DATE, [runner], standard_rows(), ledger=self.ledger, now=utc("2026-10-20T21:10:00Z"),
                               game_pk_index={EVENT: {"game_pk": "900001"}}, **kw)

    def test_a_bet_the_engine_writes_queues_one_placed_event_for_its_owner(self):
        user, hound = self.member()
        out = self.run_engine(hound)
        self.assertEqual(out["bets_written"], 1)
        events = alerts.events_for(user.id)
        self.assertEqual([e["kind"] for e in events], ["placed"])
        self.assertEqual(events[0]["payload"]["hound_id"], hound["id"])
        self.assertEqual(events[0]["payload"]["price"], 120)

    def test_a_failing_alert_store_never_breaks_the_bet_write(self):
        user, hound = self.member()
        with mock.patch.object(alerts, "connect", side_effect=RuntimeError("database is locked")):
            with self.assertLogs("linehound.notify.alerts", level="ERROR"):
                out = self.run_engine(hound)
        self.assertEqual(out["bets_written"], 1)
        bets = [r for r in user_engine.read_ledger(self.ledger) if r["kind"] == user_engine.KIND_BET]
        self.assertEqual(len(bets), 1)
        self.assertEqual(alerts.events_for(user.id), [])         # nothing queued, nothing lost from the ledger

    def test_a_failing_alert_store_never_breaks_a_grade(self):
        user, hound = self.member()
        self.run_engine(hound)
        index = {EVENT: {"game_pk": "900001"}}
        with mock.patch.object(alerts, "connect", side_effect=RuntimeError("disk full")):
            with self.assertLogs("linehound.notify.alerts", level="ERROR"):
                report = user_settle.settle(ledger=self.ledger, now=utc("2026-10-21T12:00:00Z"),
                                            mlb_results={"900001": result_row("900001", DATE, "BOS", "SEA", 5, 3)},
                                            game_pk_index=index, close_fn=lambda bet: None)
        self.assertEqual(report["graded"], 1)

    def test_a_grade_queues_a_settled_event_with_the_stake_weighted_pnl(self):
        user, hound = self.member()
        self.run_engine(hound)
        user_settle.settle(ledger=self.ledger, now=utc("2026-10-21T12:00:00Z"),
                           mlb_results={"900001": result_row("900001", DATE, "BOS", "SEA", 5, 3)},
                           game_pk_index={EVENT: {"game_pk": "900001"}}, close_fn=lambda bet: None)
        kinds = {e["kind"]: e for e in alerts.events_for(user.id)}
        self.assertEqual(set(kinds), {"placed", "settled"})
        self.assertEqual(kinds["settled"]["payload"]["result"], "win")
        self.assertAlmostEqual(kinds["settled"]["payload"]["profit_units"], 1.2)

    def test_a_hound_whose_owner_never_opened_alerts_queues_nothing(self):
        user, hound = self.member(opened=False)
        self.run_engine(hound)
        self.assertEqual(alerts.events_for(user.id), [])

    def test_a_replay_never_alerts(self):
        user, hound = self.member()
        self.run_engine(hound, mode="replay")
        self.assertEqual(alerts.events_for(user.id), [])

    def test_the_same_bet_is_emitted_once(self):
        user, hound = self.member()
        row = self.bet_row(hound)
        self.assertTrue(alerts.emit_placed(row, now=at(0)))
        self.assertFalse(alerts.emit_placed(row, now=at(5)))
        self.assertEqual(len(alerts.events_for(user.id)), 1)

    def test_a_void_or_a_minus_200_price_is_not_announced(self):
        user, hound = self.member()
        self.assertFalse(alerts.emit_settled(self.bet_row(hound), {"result": "void"}, now=at(0)))
        self.assertFalse(alerts.emit_placed(self.bet_row(hound, price=-210), now=at(0)))

    def test_the_house_pack_and_unknown_hounds_queue_nothing(self):
        self.member()
        row = self.bet_row({"id": "pack-house-1"})
        self.assertFalse(alerts.emit_placed(row, now=at(0)))


# ---------------------------------------------------------------------------
# the dispatcher
# ---------------------------------------------------------------------------

class Dispatch(Base):
    def test_a_burst_inside_a_minute_is_one_message_after_it_goes_quiet(self):
        user, hound = self.member()
        for s in (0, 20, 40):
            alerts.emit_placed(self.bet_row(hound), now=at(s))
        self.assertEqual(self.drain(at(45)).get("held_settling"), 1)       # still arriving: nothing sent yet
        self.assertEqual(self.http.emails(), [])
        self.drain(at(55))
        sent = self.http.emails()
        self.assertEqual(len(sent), 1)
        self.assertIn("3 new bet updates", sent[0]["subject"])
        self.assertEqual(sent[0]["text"].count("Boston Red Sox ML +110"), 3)

    def test_a_single_bet_goes_out_as_soon_as_the_settle_gap_passes(self):
        user, hound = self.member()
        alerts.emit_placed(self.bet_row(hound), now=at(0))
        self.drain(at(dispatch.SETTLE_S + 1))
        self.assertEqual(self.http.emails()[0]["subject"], f"{hound['name']} just bet: Boston Red Sox ML +110")

    def test_bets_more_than_a_window_apart_are_separate_messages(self):
        user, hound = self.member()
        alerts.emit_placed(self.bet_row(hound), now=at(0))
        alerts.emit_placed(self.bet_row(hound), now=at(100))
        self.drain(at(200))
        self.drain(at(210))
        self.assertEqual(len(self.http.emails()), 2)

    def test_the_same_alert_is_never_sent_twice(self):
        user, hound = self.member()
        alerts.emit_placed(self.bet_row(hound), now=at(0))
        for s in (15, 30, 600):
            self.drain(at(s))
        self.assertEqual(len(self.http.emails()), 1)
        self.assertEqual([d["status"] for d in self.deliveries()], ["sent"])

    def test_two_passes_racing_for_one_event_send_it_once(self):
        user, hound = self.member()
        alerts.emit_placed(self.bet_row(hound), now=at(0))
        with alerts.connect() as conn:
            group = dispatch._candidates(conn, user.id, "email", alerts.KINDS, at(30))
            first = dispatch._claim(conn, "email", group, at(30))
            second = dispatch._claim(conn, "email", group, at(30))
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])

    def test_the_hourly_cap_defers_alerts_and_sends_the_backlog_as_one_message(self):
        user, hound = self.member()
        with mock.patch.dict(dispatch.RATE_CAP_PER_HOUR, {"email": 1}):
            alerts.emit_placed(self.bet_row(hound), now=at(0))
            self.drain(at(15))
            alerts.emit_placed(self.bet_row(hound), now=at(100))
            alerts.emit_placed(self.bet_row(hound), now=at(110))
            self.assertEqual(self.drain(at(130)).get("held_rate_cap"), 1)
            self.assertEqual(len(self.http.emails()), 1)
            self.drain(at(3700))
        sent = self.http.emails()
        self.assertEqual(len(sent), 2)
        self.assertIn("2 new bet updates", sent[1]["subject"])

    def test_channel_off_means_nothing_is_sent(self):
        user, hound = self.member(channels={"email": False})
        alerts.emit_placed(self.bet_row(hound), now=at(0))
        self.drain(at(60))
        self.assertEqual(self.http.calls, [])

    def test_the_event_choice_is_honoured(self):
        user, hound = self.member(events="settled")
        row = self.bet_row(hound)
        alerts.emit_placed(row, now=at(0))
        alerts.emit_settled(row, {"result": "loss", "profit_units": -2.0}, now=at(5))
        self.drain(at(60))
        sent = self.http.emails()
        self.assertEqual(len(sent), 1)
        self.assertIn("lost", sent[0]["subject"])

    def test_quiet_hours_hold_alerts_and_release_them_after(self):
        user, hound = self.member(quiet_start=22, quiet_end=8)
        night = datetime(2026, 10, 21, 3, 0, tzinfo=timezone.utc)         # 23:00 Eastern
        alerts.emit_placed(self.bet_row(hound), now=night)
        self.assertEqual(self.drain(night + timedelta(minutes=5)).get("held_quiet"), 1)
        self.assertEqual(self.http.calls, [])
        self.drain(datetime(2026, 10, 21, 13, 0, tzinfo=timezone.utc))    # 09:00 Eastern
        self.assertEqual(len(self.http.emails()), 1)

    def test_a_transient_failure_retries_with_backoff_then_succeeds(self):
        user, hound = self.member()
        alerts.emit_placed(self.bet_row(hound), now=at(0))
        self.http = FakeHttp((500, b"{}"), (500, b"{}"))
        self.drain(at(15))
        self.assertEqual(self.deliveries()[0]["status"], "retry")
        calls = len(self.http.calls)
        self.drain(at(25))                                                # not due yet (30s backoff)
        self.assertEqual(len(self.http.calls), calls)
        self.drain(at(60))
        self.assertEqual(self.deliveries()[0]["status"], "sent")

    def test_a_provider_that_keeps_failing_ends_dead_after_the_attempt_limit(self):
        user, hound = self.member()
        alerts.emit_placed(self.bet_row(hound), now=at(0))
        self.http = FakeHttp(*[(500, b"{}")] * 20)
        for s in (15, 100, 400, 2000, 4000):
            self.drain(at(s))
        self.assertEqual(self.deliveries()[0]["status"], "dead")

    def test_one_channel_crashing_does_not_stop_the_others(self):
        user, hound = self.member(channels={"email": True, "push": True})
        alerts.emit_placed(self.bet_row(hound), now=at(0))
        with mock.patch.object(ch.WebPushChannel, "availability", return_value={"available": True, "reason": ""}), \
                mock.patch.object(ch.WebPushChannel, "has_target", side_effect=RuntimeError("boom")):
            self.drain(at(30))
        self.assertEqual(len(self.http.emails()), 1)


# ---------------------------------------------------------------------------
# what the messages say
# ---------------------------------------------------------------------------

class Rendering(Base):
    def event(self, kind="placed", **over):
        payload = {"hound_name": "DRAKEO", "hound_id": "u-abc", "sport": "MLB", "market": "moneyline",
                   "selection": "Atlanta Hawks to win", "price": 110, "stake_units": 2.0,
                   "away_team": "Atlanta Hawks", "home_team": "Boston Celtics", "start_utc": "2026-10-21T23:10:00Z"}
        payload.update(over)
        return {"id": 1, "kind": kind, "created_utc": "2026-10-21T18:00:00Z", "payload": payload}

    def test_the_email_is_priced_at_the_members_unit_size(self):
        user, hound = self.member()
        unit_size.save(user.id, {"mode": "fixed", "unit_usd": 50})
        alerts.emit_placed(self.bet_row(hound, stake=2.0), now=at(0))
        self.drain(at(30))
        mail_out = self.http.emails()[0]
        self.assertIn("stake $100", mail_out["text"])
        self.assertIn(f"{hound['name']} just bet: Boston Red Sox ML +110", mail_out["subject"])
        self.assertIn("starts Wed 7:10 PM EDT", mail_out["text"])
        self.assertIn(f"/web/hound.html?id={hound['id']}", mail_out["text"])

    def test_a_settled_alert_shows_the_pnl_at_the_members_sizing(self):
        sizing = unit_size.Sizing("fixed", 25, None, 2500)
        line = render.event_line(self.event("settled", result="win", profit_units=2.2), sizing)
        self.assertIn("won (+$55)", line)
        loss = render.event_line(self.event("settled", result="loss", profit_units=-2.0), sizing)
        self.assertIn("lost (-$50)", loss)

    def test_a_percent_sizing_is_marked_approximate(self):
        sizing = unit_size.Sizing("percent", None, 2.0, 5000)
        self.assertEqual(render.dollars(1.0, sizing), "~$100")
        self.assertIn("starting bankroll", render.sizing_words(sizing))

    def test_the_email_carries_the_disclosure_and_makes_no_claims(self):
        msg = render.email_message(to=ADDRESS, events=[self.event()], sizing=unit_size.fixed(25), tz="America/New_York",
                                   off_url="https://linehound.app/alerts/off?t=x", settings_url="https://x/s",
                                   env=ENV)
        for text in (msg["html"], msg["text"]):
            self.assertIn("21+", text)
            self.assertIn("1-800-GAMBLER", text)
            low = text.lower()
            for banned in ("bet check", "betcheck", "guaranteed", "profit", "edge", "winning"):
                self.assertNotIn(banned, low)
        self.assertIn("tel:+18004262537", msg["html"])
        self.assertIn("List-Unsubscribe", msg["headers"])

    def test_every_interpolated_value_is_escaped(self):
        evil = self.event(hound_name="<script>alert(1)</script>", selection='"><img src=x onerror=1>')
        msg = render.email_message(to=ADDRESS, events=[evil], sizing=unit_size.fixed(25), tz="America/New_York",
                                   off_url="https://l/o", settings_url="https://l/s", env=ENV)
        self.assertNotIn("<script>", msg["html"])
        self.assertNotIn("<img", msg["html"])
        self.assertIn("&lt;script&gt;", msg["html"])

    def test_a_price_of_minus_200_is_never_printed(self):
        self.assertEqual(render.pick_text(self.event(price=-205)["payload"]), "Atlanta Hawks ML")

    def test_sms_text_is_short_and_ends_with_stop(self):
        text = render.sms_text([self.event()] * 9, unit_size.fixed(25), "America/New_York", ENV)
        self.assertLessEqual(len(text), render.SMS_MAX)
        self.assertTrue(text.endswith("Reply STOP to end."))


# ---------------------------------------------------------------------------
# push
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAS_CRYPTO, "needs the cryptography package")
class Push(Base):
    def keys(self):
        from cryptography.hazmat.primitives.asymmetric import ec
        ua = ec.generate_private_key(ec.SECP256R1())
        raw = ua.public_key().public_bytes(webpush._crypto()["serialization"].Encoding.X962,
                                           webpush._crypto()["serialization"].PublicFormat.UncompressedPoint)
        auth = webpush.b64u(os.urandom(16))
        return ua, {"endpoint": "https://fcm.googleapis.com/fcm/send/abc123", "p256dh": webpush.b64u(raw), "auth": auth}

    def test_push_is_disabled_without_the_key(self):
        self.assertFalse(webpush.status({})["available"])
        self.assertIsNone(webpush.public_key({}))
        self.assertEqual(webpush.send({"endpoint": "https://p/x", "p256dh": "a", "auth": "b"}, {"title": "t"},
                                      http=self.http, env={}), webpush.R_DISABLED)
        self.assertEqual(self.http.calls, [])
        self.assertFalse(ch.CHANNELS["push"].availability({})["available"])

    def test_a_garbage_key_is_disabled_not_a_crash_and_is_never_echoed(self):
        env = {webpush.ENV_PRIVATE: "not-a-key"}
        self.assertFalse(webpush.status(env)["available"])
        self.assertNotIn("not-a-key", json.dumps(webpush.status(env)))

    def test_the_dispatcher_skips_push_while_the_key_is_missing(self):
        user, hound = self.member(channels={"push": True})
        alerts.emit_placed(self.bet_row(hound), now=at(0))
        self.drain(at(30), env={})
        self.assertEqual(self.http.calls, [])

    def test_the_payload_decrypts_as_an_rfc_8291_message_and_carries_a_vapid_header(self):
        private = webpush.generate_private_key()
        env = {webpush.ENV_PRIVATE: private}
        ua, sub = self.keys()
        out = webpush.send(sub, {"title": "DRAKEO just bet", "body": "x"}, http=self.http, env=env)
        self.assertEqual(out, webpush.R_SENT)
        call = self.http.calls[0]
        self.assertEqual(call["headers"]["Content-Encoding"], "aes128gcm")
        self.assertTrue(call["headers"]["Authorization"].startswith("vapid t="))
        self.assertIn(f"k={webpush.public_key(env)}", call["headers"]["Authorization"])
        self.assertEqual(json.loads(webpush.decrypt(call["body"], ua, sub["auth"])), {"title": "DRAKEO just bet", "body": "x"})

    def test_a_dead_subscription_is_removed_and_a_live_one_is_pushed(self):
        private = webpush.generate_private_key()
        env = {**ENV, webpush.ENV_PRIVATE: private}
        user, hound = self.member(channels={"push": True})
        _ua, sub = self.keys()
        alerts.add_push_subscription(user.id, sub["endpoint"], sub["p256dh"], sub["auth"])
        alerts.emit_placed(self.bet_row(hound), now=at(0))
        self.http = FakeHttp((410, b""))
        self.drain(at(30), env=env)
        self.assertEqual(alerts.push_subscriptions(user.id), [])
        self.assertEqual(self.deliveries("push")[0]["status"], "skipped")

    def test_the_test_button_reports_no_target_before_a_browser_subscribes(self):
        user, _ = self.member()
        env = {**ENV, webpush.ENV_PRIVATE: webpush.generate_private_key()}
        out = dispatch.send_test(user, "push", http=self.http, env=env)
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], "no_target")


# ---------------------------------------------------------------------------
# SMS
# ---------------------------------------------------------------------------

TWILIO = {ch.ENV_SID: "ACtest", ch.ENV_TOKEN: "tok_test_secret", ch.ENV_FROM: "+15550001111"}


class Sms(Base):
    def opted_in(self):
        user, hound = self.member(channels={"email": False})
        alerts.sms_opt_in(user.id, "(555) 234-5678", now=at(-60))
        alerts.update_prefs(user.id, {"channels": {"sms": True}})
        return user, hound

    def test_sms_is_off_unless_all_three_twilio_names_are_set(self):
        self.assertFalse(ch.CHANNELS["sms"].availability({})["available"])
        for missing in TWILIO:
            env = {k: v for k, v in TWILIO.items() if k != missing}
            self.assertFalse(ch.CHANNELS["sms"].availability(env)["available"])
        self.assertTrue(ch.CHANNELS["sms"].availability(TWILIO)["available"])

    def test_nothing_is_sent_while_sms_is_unconfigured(self):
        user, hound = self.opted_in()
        alerts.emit_placed(self.bet_row(hound), now=at(0))
        self.drain(at(30), env=ENV)
        self.assertEqual(self.http.calls, [])

    def test_a_number_is_stored_only_on_opt_in_and_sms_cannot_be_switched_on_without_one(self):
        user, _ = self.member(channels={"email": True})
        self.assertIsNone(alerts.get_prefs(user.id)["phone"])
        with self.assertRaises(alerts.AlertError) as ctx:
            alerts.update_prefs(user.id, {"channels": {"sms": True}})
        self.assertEqual(ctx.exception.code, "sms_needs_opt_in")
        with self.assertRaises(alerts.AlertError):
            alerts.sms_opt_in(user.id, "12345")
        self.assertEqual(alerts.sms_opt_in(user.id, "555-234-5678")["phone"], "+15552345678")

    def test_a_paid_member_gets_a_text_through_twilio_with_basic_auth(self):
        user, hound = self.opted_in()
        alerts.emit_placed(self.bet_row(hound), now=at(0))
        self.drain(at(30), env={**ENV, **TWILIO})
        call = [c for c in self.http.calls if "twilio" in c["url"]][0]
        self.assertIn("/Accounts/ACtest/Messages.json", call["url"])
        self.assertTrue(call["headers"]["Authorization"].startswith("Basic "))
        self.assertIn(b"To=%2B15552345678", call["body"])
        self.assertIn(b"STOP", call["body"])

    def test_a_free_account_never_gets_a_text(self):
        user, hound = self.opted_in()
        alerts.emit_placed(self.bet_row(hound), now=at(0))
        self.drain(at(30), env={**ENV, **TWILIO}, paid_check=FREE)
        self.assertEqual(self.http.calls, [])
        self.assertEqual(self.deliveries("sms")[0]["status"], "skipped")
        self.assertEqual(dispatch.send_test(user, "sms", http=self.http, env={**ENV, **TWILIO},
                                            paid_check=FREE)["status"], "paid_only")

    def test_nobody_is_paid_until_the_api_layer_registers_the_check(self):
        user, _ = self.member()
        self.assertFalse(dispatch.default_paid_check(user))
        dispatch.set_paid_check(lambda u: True)
        self.addCleanup(dispatch.set_paid_check, lambda u: False)
        self.assertTrue(dispatch.default_paid_check(user))

    def test_stop_switches_the_number_off_until_the_member_opts_in_again(self):
        user, hound = self.opted_in()
        self.assertEqual(alerts.sms_stop("+1 555 234 5678"), 1)
        prefs = alerts.get_prefs(user.id)
        self.assertTrue(prefs["sms_stopped"])
        self.assertFalse(prefs["channels"]["sms"])
        with self.assertRaises(alerts.AlertError):
            alerts.update_prefs(user.id, {"channels": {"sms": True}})
        alerts.sms_opt_in(user.id, "5552345678")
        self.assertFalse(alerts.get_prefs(user.id)["sms_stopped"])

    def test_twilios_own_stop_refusal_marks_the_member_stopped(self):
        user, hound = self.opted_in()
        alerts.emit_placed(self.bet_row(hound), now=at(0))
        self.http = FakeHttp((400, b'{"code": 21610, "message": "unsubscribed recipient"}'))
        self.drain(at(30), env={**ENV, **TWILIO})
        self.assertTrue(alerts.get_prefs(user.id)["sms_stopped"])

    def test_no_secret_or_number_reaches_a_log_line(self):
        user, hound = self.opted_in()
        alerts.emit_placed(self.bet_row(hound), now=at(0))
        self.http = FakeHttp((500, b"{}"))
        with self.assertLogs(level="DEBUG") as logs:
            logging.getLogger("linehound.test").debug("anchor")
            self.drain(at(30), env={**ENV, **TWILIO})
        joined = "\n".join(logs.output)
        for secret in ("tok_test_secret", "5552345678", KEY, ADDRESS):
            self.assertNotIn(secret, joined)


# ---------------------------------------------------------------------------
# the native stub and the device table
# ---------------------------------------------------------------------------

class NativeStub(Base):
    def test_native_is_unavailable_and_the_device_table_works(self):
        user, _ = self.member()
        self.assertFalse(ch.CHANNELS["native"].availability()["available"])
        alerts.register_device(user.id, "ios", "apns-token-1", "1.0.0")
        alerts.register_device(user.id, "ios", "apns-token-1", "1.0.1")           # same token: one row
        self.assertEqual([d["app_version"] for d in alerts.active_devices(user.id)], ["1.0.1"])
        with self.assertRaises(alerts.AlertError):
            alerts.register_device(user.id, "windows", "t")


# ---------------------------------------------------------------------------
# the API: RSS token auth, the off link, the Twilio webhook, the paid gate
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAS_FASTAPI, "needs FastAPI")
class Api(Base):
    def setUp(self):
        super().setUp()
        from api import alerts_routes
        self.api = alerts_routes

    def test_the_feed_answers_only_to_the_members_secret_token(self):
        from fastapi import HTTPException, Response
        user, hound = self.member()
        other, _ = self.member(email="other.person@sample-mail.net", name="Rival")
        alerts.emit_placed(self.bet_row(hound), now=at(0))
        token = alerts.get_prefs(user.id)["feed_token"]
        body = self.api.feed(token, _rl=None).body.decode()
        self.assertIn("<rss", body)
        self.assertIn("just bet: Boston Red Sox ML +110", body)
        self.assertIn("<guid isPermaLink=\"false\">alert-", body)
        self.assertNotIn(f"alert-{user.id}-", body)          # the item id is opaque: no member id, no global counter
        for bad in ("", "short", "x" * 32, alerts.get_prefs(other.id)["feed_token"][:-1] + "A"):
            with self.assertRaises(HTTPException) as ctx:
                self.api.feed(bad, _rl=None)
            self.assertEqual(ctx.exception.status_code, 404)
        other_body = self.api.feed(alerts.get_prefs(other.id)["feed_token"], _rl=None).body.decode()
        self.assertNotIn("Boston Red Sox", other_body)

    def test_rotating_the_token_revokes_the_old_address(self):
        from fastapi import HTTPException, Response
        user, _ = self.member()
        old = alerts.get_prefs(user.id)["feed_token"]
        new = alerts.rotate_feed_token(user.id)
        self.assertNotEqual(old, new)
        with self.assertRaises(HTTPException):
            self.api.feed(old, _rl=None)
        self.api.feed(new, _rl=None)

    def test_the_one_click_off_link_turns_email_off_and_a_forged_one_does_nothing(self):
        from src.notify import email_prefs
        user, _ = self.member()
        self.assertEqual(self.api.alerts_off("forged.token").status_code, 400)
        self.assertTrue(alerts.get_prefs(user.id)["channels"]["email"])
        token = email_prefs.token(user.id)
        self.assertEqual(self.api.alerts_off(token).status_code, 200)
        self.assertFalse(alerts.get_prefs(user.id)["channels"]["email"])

    def test_the_twilio_webhook_checks_the_signature_before_honouring_stop(self):
        from fastapi import HTTPException, Response
        user, _ = self.member()
        alerts.sms_opt_in(user.id, "5552345678")
        params = {"From": "+15552345678", "Body": "STOP"}

        class Req:
            def __init__(self, sig):
                self.headers = {"X-Twilio-Signature": sig}

                class U:
                    path = "/alerts/sms/inbound"
                self.url = U()

            async def body(self):
                return b"From=%2B15552345678&Body=STOP"

        with mock.patch.dict(os.environ, {ch.ENV_TOKEN: "tok_test_secret", "PUBLIC_BASE_URL": "https://linehound.app"}):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(self.api.sms_inbound(Req("bad"), _rl=None))
            self.assertEqual(ctx.exception.status_code, 403)
            self.assertFalse(alerts.get_prefs(user.id)["sms_stopped"])
            good = self.api.twilio_signature("tok_test_secret", "https://linehound.app/alerts/sms/inbound", params)
            asyncio.run(self.api.sms_inbound(Req(good), _rl=None))
        self.assertTrue(alerts.get_prefs(user.id)["sms_stopped"])

    def test_the_twilio_webhook_does_not_exist_without_a_token(self):
        from fastapi import HTTPException, Response
        env = {k: v for k, v in os.environ.items() if k != ch.ENV_TOKEN}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(self.api.sms_inbound(mock.Mock(), _rl=None))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_the_status_says_why_a_channel_is_off_and_never_leaks_the_phone(self):
        user, _ = self.member()
        with mock.patch.object(self.api, "_is_paid", return_value=True):
            alerts.sms_opt_in(user.id, "5552345678")
            out = self.api._payload(user)
        by = {c["name"]: c for c in out["channels"]}
        self.assertFalse(by["sms"]["available"])
        self.assertTrue(by["sms"]["reason"])
        self.assertEqual(by["sms"]["phone"], "***-***-5678")
        self.assertNotIn("5552345678", json.dumps(out))
        self.assertIn("Home Screen", out["ios_note"])

    def test_a_free_account_cannot_switch_sms_on_or_opt_in(self):
        from fastapi import HTTPException, Response
        user, _ = self.member()
        with mock.patch.object(self.api, "_is_paid", return_value=False):
            with self.assertRaises(HTTPException) as c1:
                self.api.sms_opt_in(self.api.SmsRequest(phone="5552345678", consent=True), Response(),
                                    current_user=user, _rl=None)
            with self.assertRaises(HTTPException) as c2:
                self.api.put_alerts(self.api.AlertsRequest(channels={"sms": True}), Response(),
                                    current_user=user, _rl=None)
        self.assertEqual((c1.exception.status_code, c2.exception.status_code), (402, 402))
        self.assertIsNone(alerts.get_prefs(user.id)["phone"])

    def test_opt_in_needs_the_consent_box(self):
        from fastapi import HTTPException, Response
        user, _ = self.member()
        with mock.patch.object(self.api, "_is_paid", return_value=True):
            with self.assertRaises(HTTPException) as ctx:
                self.api.sms_opt_in(self.api.SmsRequest(phone="5552345678", consent=False), Response(),
                                    current_user=user, _rl=None)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIsNone(alerts.get_prefs(user.id)["phone"])


class Settings(Base):
    def test_quiet_hours_and_events_are_validated(self):
        user, _ = self.member()
        with self.assertRaises(alerts.AlertError):
            alerts.update_prefs(user.id, {"quiet_start": 25, "quiet_end": 3})
        with self.assertRaises(alerts.AlertError):
            alerts.update_prefs(user.id, {"quiet_start": 22, "quiet_end": None})
        with self.assertRaises(alerts.AlertError):
            alerts.update_prefs(user.id, {"events": "everything"})
        with self.assertRaises(alerts.AlertError):
            alerts.update_prefs(user.id, {"tz": "Mars/Base"})
        out = alerts.update_prefs(user.id, {"events": "placed", "quiet_start": 23, "quiet_end": 7})
        self.assertEqual((out["events"], out["quiet_start"], out["quiet_end"]), ("placed", 23, 7))

    def test_a_member_who_never_opened_alerts_has_no_row(self):
        user, _ = self.member(opened=False)
        self.assertIsNone(alerts.get_prefs(user.id))

    def test_email_test_button_sends_a_sample_and_no_bet_is_involved(self):
        user, _ = self.member()
        out = dispatch.send_test(user, "email", http=self.http, env=ENV)
        self.assertTrue(out["ok"])
        self.assertEqual(self.http.emails()[0]["subject"], "Test alert from LINEHOUND")


# ---------------------------------------------------------------------------
# checker round (2026-10-22): replay never alerts, the phone is verified, push endpoints are allow-listed, START/HELP
# ---------------------------------------------------------------------------

class CheckerRound(Base):
    def run_engine(self, hound, **kw):
        runner = dict(hound, created_at="2026-01-01T00:00:00Z")
        return user_engine.run(DATE, [runner], standard_rows(), ledger=self.ledger, now=utc("2026-10-20T21:10:00Z"),
                               game_pk_index={EVENT: {"game_pk": "900001"}}, **kw)

    def test_a_replay_bet_graded_in_a_scratch_ledger_never_alerts(self):
        # the "Before you unleashed" list and the backtest replay a slate into a scratch ledger and grade it with
        # the same settler; the member's record is not involved, so no "your hound won" text may go out
        user, hound = self.member()
        self.run_engine(hound, mode="replay")
        user_settle.settle(ledger=self.ledger, now=utc("2026-10-21T12:00:00Z"),
                           mlb_results={"900001": result_row("900001", DATE, "BOS", "SEA", 5, 3)},
                           game_pk_index={EVENT: {"game_pk": "900001"}}, close_fn=lambda bet: None)
        self.assertEqual(alerts.events_for(user.id), [])

    def test_a_locked_database_does_not_stop_the_bet(self):
        import sqlite3
        user, hound = self.member()
        lock = sqlite3.connect(str(self.db), isolation_level=None)
        lock.execute("BEGIN IMMEDIATE")
        try:
            with mock.patch.object(alerts, "_insert_event", side_effect=sqlite3.OperationalError("database is locked")):
                with self.assertLogs("linehound.notify.alerts", level="ERROR"):
                    out = self.run_engine(hound)
        finally:
            lock.execute("ROLLBACK")
            lock.close()
        self.assertEqual(out["bets_written"], 1)

    # -- phone verification ------------------------------------------------------------------------------------------
    def test_a_number_is_stored_only_after_the_code_is_typed_back(self):
        user, _ = self.member()
        number, code = alerts.sms_begin(user.id, "(555) 234-5678", now=at(0))
        self.assertIsNone(alerts.get_prefs(user.id)["phone"])
        self.assertEqual(alerts.sms_pending_phone(user.id, now=at(1)), "+15552345678")
        with self.assertRaises(alerts.AlertError) as wrong:
            alerts.sms_confirm(user.id, "000000" if code != "000000" else "111111", now=at(5))
        self.assertEqual(wrong.exception.code, "sms_code_wrong")
        self.assertIsNone(alerts.get_prefs(user.id)["phone"])
        prefs = alerts.sms_confirm(user.id, code, now=at(10))
        self.assertEqual(prefs["phone"], "+15552345678")
        self.assertEqual(prefs["sms_consent_utc"], alerts.iso(at(0)))      # the consent time, not the verify time
        self.assertIsNone(alerts.sms_pending_phone(user.id, now=at(11)))

    def test_the_code_expires_and_five_wrong_tries_burn_it(self):
        user, _ = self.member()
        _, code = alerts.sms_begin(user.id, "5552345678", now=at(0))
        for _i in range(alerts.SMS_CODE_TRIES):
            with self.assertRaises(alerts.AlertError):
                alerts.sms_confirm(user.id, "12345x", now=at(5))
        with self.assertRaises(alerts.AlertError) as burnt:           # the right code no longer works
            alerts.sms_confirm(user.id, code, now=at(6))
        self.assertEqual(burnt.exception.code, "sms_code_expired")
        _, code = alerts.sms_begin(user.id, "5552345678", now=at(120))
        with self.assertRaises(alerts.AlertError) as late:
            alerts.sms_confirm(user.id, code, now=at(120 + alerts.SMS_CODE_TTL_S + 1))
        self.assertEqual(late.exception.code, "sms_code_expired")
        self.assertIsNone(alerts.get_prefs(user.id)["phone"])

    def test_codes_are_rate_limited_per_member_and_per_number(self):
        user, _ = self.member()
        other, _ = self.member(email="second.person@sample-mail.net", name="Rival")
        alerts.sms_begin(user.id, "5552345678", now=at(0))
        with self.assertRaises(alerts.AlertError) as soon:
            alerts.sms_begin(user.id, "5552345678", now=at(10))
        self.assertEqual(soon.exception.status, 429)
        with self.assertRaises(alerts.AlertError) as busy:           # a second member cannot aim a code at the same number
            alerts.sms_begin(other.id, "5552345678", now=at(20))
        self.assertEqual(busy.exception.code, "sms_number_busy")
        for k in range(1, alerts.SMS_CODE_PER_HOUR):
            alerts.sms_begin(user.id, "5552345678", now=at(100 * k))
        with self.assertRaises(alerts.AlertError) as capped:
            alerts.sms_begin(user.id, "5552345678", now=at(100 * alerts.SMS_CODE_PER_HOUR))
        self.assertEqual(capped.exception.code, "sms_code_limit")

    @unittest.skipUnless(HAS_FASTAPI, "needs FastAPI")
    def test_the_opt_in_route_texts_a_code_and_the_verify_route_stores_the_number(self):
        import urllib.parse
        from fastapi import HTTPException, Response
        from api import alerts_routes as api
        user, _ = self.member()
        http = FakeHttp()
        sent = []

        def twilio(url, headers, body, timeout):
            sent.append(body.decode())
            return http(url, headers, body, timeout)
        with mock.patch.dict(os.environ, TWILIO), mock.patch.object(api, "_is_paid", return_value=True), \
                mock.patch.object(api, "_http", return_value=twilio):
            api.sms_opt_in(api.SmsRequest(phone="5552345678", consent=True), Response(), current_user=user, _rl=None)
            self.assertIsNone(alerts.get_prefs(user.id)["phone"])                 # not stored by the opt-in
            self.assertEqual(len(sent), 1)
            form = urllib.parse.parse_qs(sent[0])
            self.assertEqual(form["To"], ["+15552345678"])
            code = [w.rstrip(".") for w in form["Body"][0].split() if w.rstrip(".").isdigit() and len(w.rstrip(".")) == 6][0]
            with self.assertRaises(HTTPException) as bad:
                api.sms_verify(api.VerifyRequest(code="000000" if code != "000000" else "111111"), Response(),
                               current_user=user, _rl=None)
            self.assertEqual(bad.exception.status_code, 422)
            api.sms_verify(api.VerifyRequest(code=code), Response(), current_user=user, _rl=None)
        self.assertEqual(alerts.get_prefs(user.id)["phone"], "+15552345678")
        self.assertTrue(alerts.get_prefs(user.id)["sms_consent_utc"])

    @unittest.skipUnless(HAS_FASTAPI, "needs FastAPI")
    def test_nothing_is_texted_when_the_text_provider_is_off_or_the_member_is_free(self):
        from fastapi import HTTPException, Response
        from api import alerts_routes as api
        user, _ = self.member()
        env = {k: v for k, v in os.environ.items() if k not in TWILIO}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(api, "_is_paid", return_value=True):
            with self.assertRaises(HTTPException) as off:
                api.sms_opt_in(api.SmsRequest(phone="5552345678", consent=True), Response(), current_user=user, _rl=None)
        self.assertEqual(off.exception.status_code, 503)
        with mock.patch.object(api, "_is_paid", return_value=False):
            with self.assertRaises(HTTPException) as free:
                api.sms_verify(api.VerifyRequest(code="123456"), Response(), current_user=user, _rl=None)
        self.assertEqual(free.exception.status_code, 402)
        self.assertIsNone(alerts.sms_pending_phone(user.id))

    # -- START / HELP ------------------------------------------------------------------------------------------------
    @unittest.skipUnless(HAS_FASTAPI, "needs FastAPI")
    def test_start_switches_a_stopped_verified_number_back_on_and_help_answers(self):
        from api import alerts_routes as api
        user, _ = self.member()
        alerts.sms_opt_in(user.id, "5552345678", now=at(-60))
        alerts.update_prefs(user.id, {"channels": {"sms": True}})
        alerts.sms_stop("+15552345678")
        self.assertTrue(alerts.get_prefs(user.id)["sms_stopped"])

        def post(word):
            params = {"From": "+15552345678", "Body": word}
            sig = api.twilio_signature("tok_test_secret", "https://linehound.app/alerts/sms/inbound", params)

            class Req:
                headers = {"X-Twilio-Signature": sig}

                class url:
                    path = "/alerts/sms/inbound"

                async def body(self):
                    return f"From=%2B15552345678&Body={word}".encode()
            return asyncio.run(api.sms_inbound(Req(), _rl=None)).body.decode()
        with mock.patch.dict(os.environ, {ch.ENV_TOKEN: "tok_test_secret", "PUBLIC_BASE_URL": "https://linehound.app"}):
            self.assertIn("STOP", post("HELP"))
            self.assertTrue(alerts.get_prefs(user.id)["sms_stopped"])        # HELP changes nothing
            self.assertIn("back on", post("start"))
        prefs = alerts.get_prefs(user.id)
        self.assertFalse(prefs["sms_stopped"])
        self.assertTrue(prefs["channels"]["sms"])
        self.assertEqual(alerts.sms_start("+15559990000"), 0)                # an unverified number is untouched

    # -- push endpoints ----------------------------------------------------------------------------------------------
    def test_only_real_push_services_are_accepted_as_endpoints(self):
        user, _ = self.member()
        key, auth = webpush.b64u(b"\x04" + b"k" * 64), webpush.b64u(b"a" * 16)
        for good in ("https://fcm.googleapis.com/fcm/send/x", "https://updates.push.services.mozilla.com/wpush/v2/x",
                     "https://web.push.apple.com/x", "https://wns2-par02p.notify.windows.com/w/?token=x"):
            alerts.add_push_subscription(user.id, good, key, auth)
        for bad in ("https://169.254.169.254/latest", "https://internal.example.local/admin", "http://fcm.googleapis.com/x",
                    "https://fcm.googleapis.com.evil.net/x", "https://fcm.googleapis.com:8443/x",
                    "https://user:pw@fcm.googleapis.com/x", "https://evilfcm.googleapis.com.attacker.io/x"):
            with self.assertRaises(alerts.AlertError, msg=bad):
                alerts.add_push_subscription(user.id, bad, key, auth)
        with self.assertRaises(alerts.AlertError):                       # keys that are not a P-256 point and a 16-byte secret
            alerts.add_push_subscription(user.id, "https://fcm.googleapis.com/x2", "short", auth)
        with self.assertRaises(alerts.AlertError):
            alerts.add_push_subscription(user.id, "https://fcm.googleapis.com/x3", key, "short")

    def test_a_member_cannot_store_unlimited_subscriptions(self):
        user, _ = self.member()
        key, auth = webpush.b64u(b"\x04" + b"k" * 64), webpush.b64u(b"a" * 16)
        for n in range(alerts.MAX_PUSH_SUBSCRIPTIONS):
            alerts.add_push_subscription(user.id, f"https://fcm.googleapis.com/fcm/send/{n}", key, auth)
        with self.assertRaises(alerts.AlertError) as over:
            alerts.add_push_subscription(user.id, "https://fcm.googleapis.com/fcm/send/extra", key, auth)
        self.assertEqual(over.exception.code, "subscription_limit")
        alerts.add_push_subscription(user.id, "https://fcm.googleapis.com/fcm/send/0", key, auth)   # a re-save is fine

    # -- the secret feed ---------------------------------------------------------------------------------------------
    def test_the_feed_token_is_looked_up_by_hash_and_an_old_row_is_migrated(self):
        user, _ = self.member()
        token = alerts.get_prefs(user.id)["feed_token"]
        self.assertEqual(alerts.user_for_feed_token(token), user.id)
        with alerts.connect() as conn:                       # the plain token is not what the lookup index holds
            self.assertNotEqual(conn.execute("SELECT feed_hash FROM alert_prefs WHERE user_id = ?", (user.id,)).fetchone()[0], token)
            conn.execute("UPDATE alert_prefs SET feed_hash = NULL")      # a row written before the column existed
        self.assertEqual(alerts.user_for_feed_token(token), user.id)     # the next connect backfills it
        self.assertIsNone(alerts.user_for_feed_token(token[:-1] + ("A" if token[-1] != "A" else "B")))

    @unittest.skipUnless(HAS_FASTAPI, "needs FastAPI")
    def test_the_access_log_never_shows_the_feed_token(self):
        import logging
        from api import alerts_routes as api  # noqa: F401 -- importing it installs the filter
        user, _ = self.member()
        token = alerts.get_prefs(user.id)["feed_token"]
        record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                                   ("1.2.3.4:5", "GET", f"/alerts/feed/{token}.xml", "1.1", 200), None)
        for f in logging.getLogger("uvicorn.access").filters:
            f.filter(record)
        self.assertNotIn(token, record.getMessage())
        self.assertIn("/alerts/feed/REDACTED.xml", record.getMessage())


if __name__ == "__main__":
    unittest.main()
