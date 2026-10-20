"""LINEHOUND's transactional email (src/notify/*, api/email_routes.py).

Every send goes through an injected fake transport: no test here reaches the network, and every path is a
temp path (the app database, the hounds ledger, the send log and the signing secret all live in one temp
directory, and nothing reads the machine's real data/app). The things worth pinning, and why:

  * the client is a NO-OP without RESEND_API_KEY and never raises, and neither the key nor a full address nor a
    message body ever reaches a log line or the send log;
  * a (user, kind, date) is sent at most once, even after a crash between the request and its record;
  * the nightly sends only for tickets graded and not yet reported, so a quiet day sends nothing, a rerun sends
    nothing, and a ticket is in exactly one email; wins and losses are written the same way;
  * an unsubscribed account gets neither the nightly nor the Sunday email, the link is signed and can do
    nothing else;
  * the hard lines hold in every message: no claim of profit, edge or winning, no Bet Check, no -200 ticket,
    the disclosure footer with a tel: link, a one-click unsubscribe, and no invented postal address.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.appstate import users as users_store
from src.hounds import user_engine, user_settle, user_store
from src.ledger.chain import HashChainLedger
from src.notify import email as mail
from src.notify import email_jobs as jobs
from src.notify import email_prefs as prefs
from src.notify import email_render as render
from tests._hounds_user_fixtures import spec_dict

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

KEY = "re_TESTKEY_do_not_leak_0123456789"
SECRET = b"test-signing-secret"
NOW = datetime(2026, 10, 21, 13, 10, tzinfo=timezone.utc)            # Wednesday 09:10 Eastern (EDT)
SUNDAY = datetime(2026, 10, 25, 14, 5, tzinfo=timezone.utc)          # Sunday 10:05 Eastern
ENV = {mail.ENV_KEY: KEY, "PUBLIC_BASE_URL": "https://linehound.app"}
ADDRESS = "brey.tester@sample-mail.net"


class FakeHttp:
    """The injected transport. Records every request; answers from a queue, then 200."""

    def __init__(self, *answers):
        self.calls = []
        self.answers = list(answers)

    def __call__(self, url, headers, body, timeout):
        self.calls.append({"url": url, "headers": dict(headers), "body": json.loads(body.decode("utf-8")),
                           "timeout": timeout})
        if self.answers:
            return self.answers.pop(0)
        return 200, json.dumps({"id": f"em_{len(self.calls)}"}).encode("utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.db = self.dir / "app.db"
        patch = mock.patch.object(users_store, "db_path", lambda: self.db)
        patch.start()
        self.addCleanup(patch.stop)
        self.ledger = str(self.dir / "hounds.jsonl")
        self.log = mail.SendLog(self.dir / "send_log.jsonl")
        self.http = FakeHttp()
        mail.reset_disabled_notice()
        jobs.STATUS.update({"enabled": False, "ticks": 0, "last_tick_utc": None, "last_error": None,
                            "last_runs": {}})
        self._n = 0

    def ctx(self, now=NOW, env=ENV, **over):
        base = dict(now=now, db=self.db, ledger=self.ledger, http=self.http, log=self.log, env=dict(env),
                    sleep=lambda s: None, house_top=lambda: None, settle_gate=lambda n: True,
                    address="", secret=SECRET)
        base.update(over)
        return jobs.Ctx(**base)

    # -- fixtures ---------------------------------------------------------
    def user(self, email=ADDRESS, status="active", plan="free"):
        return users_store.create_user(email, status=status, plan=plan, db=self.db)

    def dog(self, user, name="Rex"):
        return user_store.create_hound(user.id, spec_dict(name=name), db=self.db)

    def settled(self, hound, result, *, price=120, at="2026-10-21T08:30:00Z", market="moneyline",
                selection=None, segment="forward", stake=None):
        """One bet row and its graded row, straight into the hash-chained ledger."""
        self._n += 1
        bet_id = f"b-{self._n:04d}"
        store = HashChainLedger(self.ledger)
        store.append({"kind": user_engine.KIND_BET, "bet_id": bet_id, "hound_id": hound["id"],
                      "sport": "MLB", "market": market, "side": "away", "price": price,
                      "selection": selection or "Boston Red Sox to win", "line": None,
                      "away_team": "Boston Red Sox", "home_team": "Seattle Mariners",
                      "slate_date": "2026-10-20"})
        units = {"WIN": round(price / 100.0, 4) if price > 0 else round(100.0 / -price, 4),
                 "LOSS": -1.0, "PUSH": 0.0, "VOID": 0.0}[result]
        row = {"kind": user_settle.KIND_GRADED, "bet_id": bet_id, "hound_id": hound["id"], "result": result,
               "profit_units": units, "graded_utc": at, "segment": segment, "slate_date": "2026-10-20"}
        if stake is not None:
            row["profit_stake_units"] = round(units * stake, 4)
        store.append(row)
        return bet_id

    def sent_bodies(self):
        return [c["body"] for c in self.http.calls]


# ---------------------------------------------------------------------------
# the client
# ---------------------------------------------------------------------------

def message(**over):
    base = {"to": ADDRESS, "subject": "Rex went 2-1 last night", "html": "<p>SECRET-BODY-TEXT</p>",
            "text": "SECRET-BODY-TEXT"}
    base.update(over)
    return base


class TheClient(Base):
    def send(self, **over):
        kw = dict(user_id=7, kind="nightly", date="2026-10-21", http=self.http, log=self.log, env=ENV,
                  sleep=lambda s: None, now=NOW)
        kw.update(over)
        return mail.send(message(), **kw)

    def test_without_a_key_it_is_a_silent_no_op_that_logs_once_and_writes_nothing(self):
        with self.assertLogs("linehound.notify.email", level="INFO") as logs:
            for _ in range(3):
                self.assertEqual(self.send(env={})["status"], "disabled")
        self.assertEqual(len([l for l in logs.output if "email disabled" in l]), 1)
        self.assertEqual(self.http.calls, [])
        self.assertFalse(self.log.path.exists())

    def test_it_never_raises_even_when_the_transport_does(self):
        def boom(*a, **k):
            raise RuntimeError(f"explode {KEY} for {ADDRESS}")
        with self.assertLogs("linehound.notify.email", level="ERROR") as logs:
            out = self.send(http=boom)
        self.assertEqual(out["status"], "failed")
        joined = "\n".join(logs.output)
        self.assertNotIn(KEY, joined)
        self.assertNotIn(ADDRESS, joined)

    def test_a_send_posts_to_resend_with_the_key_the_sender_and_an_idempotency_key(self):
        out = self.send()
        self.assertEqual(out["status"], "sent")
        call = self.http.calls[0]
        self.assertEqual(call["url"], "https://api.resend.com/emails")
        self.assertEqual(call["headers"]["Authorization"], f"Bearer {KEY}")
        self.assertEqual(call["headers"]["Idempotency-Key"], "linehound-nightly-7-2026-10-21")
        self.assertEqual(call["body"]["from"], "LINEHOUND <hounds@linehound.app>")
        self.assertEqual(call["body"]["to"], [ADDRESS])
        self.assertEqual(call["timeout"], mail.TIMEOUT_S)
        self.assertEqual(out["id"], "em_1")

    def test_email_from_overrides_the_sender(self):
        self.send(env={**ENV, "EMAIL_FROM": "Hounds <x@linehound.app>"})
        self.assertEqual(self.http.calls[0]["body"]["from"], "Hounds <x@linehound.app>")

    def test_a_user_kind_date_is_sent_at_most_once(self):
        self.assertEqual(self.send()["status"], "sent")
        self.assertEqual(self.send()["status"], "duplicate")
        self.assertEqual(len(self.http.calls), 1)
        self.assertEqual(self.send(date="2026-10-22")["status"], "sent")
        self.assertEqual(self.send(kind="sunday")["status"], "sent")
        self.assertEqual(self.send(user_id=8)["status"], "sent")

    def test_a_crash_between_the_request_and_its_record_cannot_cause_a_second_email(self):
        self.log.append({"ts": "2026-10-21T13:10:00Z", "user_id": 7, "kind": "nightly",
                         "date": "2026-10-21", "status": "sending", "to": "b***@s***.net"})
        fresh = mail.SendLog(self.log.path)                       # a restarted process reads the file
        self.assertEqual(self.send(log=fresh)["status"], "duplicate")
        self.assertEqual(self.http.calls, [])

    def test_a_429_and_a_5xx_and_a_timeout_are_retried_once(self):
        for first in (429, 503, 0):
            with self.subTest(first=first):
                http = FakeHttp((first, b"{}"))
                slept = []
                out = self.send(http=http, date=f"d{first}", sleep=slept.append)
                self.assertEqual(out["status"], "sent")
                self.assertEqual(len(http.calls), 2)
                self.assertEqual(slept, [mail.RETRY_DELAY_S])

    def test_a_second_failure_is_final_for_the_attempt_but_not_for_the_day(self):
        http = FakeHttp((500, b"{}"), (500, b"{}"))
        out = self.send(http=http)
        self.assertEqual((out["status"], out["http"], len(http.calls)), ("failed", 500, 2))
        self.assertEqual(self.send(http=http)["status"], "sent")        # the next tick may try again

    def test_a_4xx_is_a_refusal_and_is_not_retried(self):
        http = FakeHttp((403, json.dumps({"message": f"domain not verified for {ADDRESS}"}).encode()))
        out = self.send(http=http)
        self.assertEqual((out["status"], len(http.calls)), ("failed", 1))

    def test_it_gives_up_after_the_attempt_limit(self):
        http = FakeHttp(*[(400, b"{}")] * mail.MAX_ATTEMPTS)
        for _ in range(mail.MAX_ATTEMPTS):
            self.assertEqual(self.send(http=http)["status"], "failed")
        self.assertEqual(self.send(http=http)["status"], "gave_up")
        self.assertEqual(len(http.calls), mail.MAX_ATTEMPTS)

    def test_neither_the_key_nor_an_address_nor_a_body_reaches_a_log_line_or_the_send_log(self):
        http = FakeHttp((422, json.dumps({"name": "validation_error",
                                          "message": f"{KEY} rejected {ADDRESS}"}).encode()))
        with self.assertLogs("linehound.notify.email", level="DEBUG") as logs:
            self.send(http=http)
            self.send(date="d2")
        on_disk = self.log.path.read_text(encoding="utf-8")
        for haystack in ("\n".join(logs.output), on_disk):
            self.assertNotIn(KEY, haystack)
            self.assertNotIn(ADDRESS, haystack)
            self.assertNotIn("SECRET-BODY-TEXT", haystack)
        self.assertIn("b***@s***.net", on_disk)

    def test_masking(self):
        self.assertEqual(mail.mask_email("brey@gmail.com"), "b***@g***.com")
        self.assertEqual(mail.mask_email("nonsense"), "***")
        self.assertEqual(mail.mask_email(None), "***")

    def test_the_default_log_sits_beside_the_app_database(self):
        self.assertEqual(mail.log_path(), self.db.parent / "email_send_log.jsonl")


# ---------------------------------------------------------------------------
# the flag and the link
# ---------------------------------------------------------------------------

class TheUnsubscribeFlag(Base):
    def test_the_flag_flips_and_is_idempotent(self):
        u = self.user()
        self.assertFalse(prefs.is_unsubscribed(u.id, db=self.db))
        prefs.set_unsubscribed(u.id, db=self.db)
        prefs.set_unsubscribed(u.id, db=self.db)
        self.assertTrue(prefs.is_unsubscribed(u.id, db=self.db))
        self.assertEqual(prefs.unsubscribed_ids(db=self.db), {u.id})
        prefs.set_unsubscribed(u.id, False, db=self.db)
        self.assertFalse(prefs.is_unsubscribed(u.id, db=self.db))

    def test_a_token_names_one_user_and_cannot_be_forged_or_moved(self):
        t = prefs.token(5, secret=SECRET)
        self.assertEqual(prefs.verify(t, secret=SECRET), 5)
        self.assertIsNone(prefs.verify(t.replace("5.", "6.", 1), secret=SECRET))
        self.assertIsNone(prefs.verify(t[:-1] + ("0" if t[-1] != "0" else "1"), secret=SECRET))
        self.assertIsNone(prefs.verify(t, secret=b"another secret"))
        for junk in (None, "", "5", "5.", ".abc", "x.y", "5." + "a" * 200, 5):
            self.assertIsNone(prefs.verify(junk, secret=SECRET))

    def test_the_secret_is_made_once_beside_the_database_and_reused(self):
        first = prefs.signing_secret({})
        self.assertTrue((self.dir / "email_signing.key").exists())
        self.assertEqual(prefs.signing_secret({}), first)
        self.assertEqual(prefs.signing_secret({prefs.ENV_SECRET: "from-env"}), b"from-env")

    def test_the_unsubscribe_url_points_at_the_public_host(self):
        url = prefs.unsubscribe_url(9, env={"PUBLIC_BASE_URL": "https://linehound.app/"}, secret=SECRET)
        self.assertTrue(url.startswith("https://linehound.app/email/unsubscribe?t=9."))

    def test_the_postal_address_comes_from_config_or_is_absent_never_invented(self):
        path = self.dir / "business.json"
        self.assertIsNone(prefs.postal_address(path))                       # no file
        path.write_text(json.dumps({"deadline": "2026-10-31"}))
        self.assertIsNone(prefs.postal_address(path))                       # no key
        path.write_text(json.dumps({"postal_address": "1 Main St, Springfield, IL 62701"}))
        self.assertEqual(prefs.postal_address(path), "1 Main St, Springfield, IL 62701")
        path.write_text(json.dumps({"postal_address": {"street": "1 Main St", "city": "Springfield",
                                                       "region": "IL", "postal_code": "62701"}}))
        self.assertEqual(prefs.postal_address(path), "1 Main St, Springfield, IL, 62701")


# ---------------------------------------------------------------------------
# (a) the Keep confirmation
# ---------------------------------------------------------------------------

class TheKeepConfirmation(Base):
    def test_it_names_the_dog_links_its_page_and_says_what_happens_tonight(self):
        u = self.user()
        d = self.dog(u, "Rex")
        out = jobs.send_keep_confirmation(u, d, ctx=self.ctx())
        self.assertEqual(out["status"], "sent")
        body = self.sent_bodies()[0]
        self.assertEqual(body["subject"], "Rex is in.")
        self.assertIn(f"https://linehound.app/web/hound.html?id={d['id']}", body["html"])
        self.assertIn(f"https://linehound.app/web/hound.html?id={d['id']}", body["text"])
        self.assertIn("What happens tonight", body["text"])
        self.assertIn("List-Unsubscribe", body["headers"])

    def test_it_is_sent_once_per_user_ever_even_for_a_second_dog_on_another_day(self):
        u = self.user()
        a, b = self.dog(u, "Rex"), self.dog(u, "Milo")
        self.assertEqual(jobs.send_keep_confirmation(u, a, ctx=self.ctx())["status"], "sent")
        self.assertEqual(jobs.send_keep_confirmation(u, a, ctx=self.ctx())["status"], "duplicate")
        later = self.ctx(now=NOW + timedelta(days=3))
        self.assertEqual(jobs.send_keep_confirmation(u, b, ctx=later)["status"], "duplicate")
        self.assertEqual(len(self.http.calls), 1)

    def test_the_public_hook_in_email_py_is_the_same_function_and_takes_plain_mappings(self):
        out = mail.send_keep_confirmation({"id": 3, "email": ADDRESS}, {"id": "u-abc", "name": "Rex"},
                                          ctx=self.ctx())
        self.assertEqual(out["status"], "sent")

    def test_without_a_key_it_is_a_no_op(self):
        u = self.user()
        d = self.dog(u)
        self.assertEqual(jobs.send_keep_confirmation(u, d, ctx=self.ctx(env={}))["status"], "disabled")
        self.assertEqual(self.http.calls, [])
        self.assertIsNone(jobs.send_keep_confirmation_async(u, d, ctx=self.ctx(env={})))

    def test_an_unsendable_address_or_missing_dog_is_skipped_without_raising(self):
        self.assertEqual(jobs.send_keep_confirmation({"id": 1, "email": "a@example.com"},
                                                     {"id": "u-1", "name": "Rex"}, ctx=self.ctx())["status"],
                         "skipped")
        self.assertEqual(jobs.send_keep_confirmation({"id": 1, "email": ADDRESS}, None,
                                                     ctx=self.ctx())["status"], "skipped")
        self.assertEqual(self.http.calls, [])


# ---------------------------------------------------------------------------
# (b) the nightly result
# ---------------------------------------------------------------------------

class TheNightlyResult(Base):
    def win_night(self):
        u = self.user()
        d = self.dog(u, "Rex")
        self.settled(d, "WIN", price=120)
        self.settled(d, "WIN", price=120, selection="Over 8.5", market="total")
        self.settled(d, "LOSS", price=120)
        return u, d

    def test_a_night_with_graded_tickets_sends_one_email_with_each_ticket_and_the_bankroll(self):
        u, d = self.win_night()
        report = jobs.run_nightly(self.ctx())
        self.assertEqual((report["sent"], report["no_bets"]), (1, 0))
        body = self.sent_bodies()[0]
        self.assertEqual(body["subject"], "Rex went 2-1 last night")
        for needle in ("Boston Red Sox to win", "Over 8.5", "WON", "LOST", "+1.20u", "-1.00u", "+120"):
            self.assertIn(needle, body["html"])
        self.assertIn("Record 2-1 over 3 bets.", body["text"])
        self.assertIn("Bankroll $1,014 paper (started at $1,000).", body["text"])
        self.assertIn(f"https://linehound.app/web/hound.html?id={d['id']}", body["html"])
        self.assertEqual(self.http.calls[0]["headers"]["Idempotency-Key"], f"linehound-nightly-{u.id}-2026-10-21")

    def test_a_losing_night_is_written_exactly_like_a_winning_one(self):
        u = self.user()
        d = self.dog(u, "Rex")
        self.settled(d, "LOSS")
        self.settled(d, "LOSS")
        jobs.run_nightly(self.ctx())
        body = self.sent_bodies()[0]
        self.assertEqual(body["subject"], "Rex went 0-2 last night")
        self.assertEqual(body["subject"].replace("0-2", "2-0"), "Rex went 2-0 last night")
        self.assertIn("Bankroll $980 paper (started at $1,000).", body["text"])
        self.assertIn("LOST", body["html"])
        for section in ("See every ticket", "Pause these emails", "1-800-GAMBLER"):
            self.assertIn(section, body["html"])

    def test_a_day_with_no_graded_tickets_sends_nothing(self):
        self.user()
        u = self.user("second.tester@sample-mail.net")
        self.dog(u, "Rex")
        report = jobs.run_nightly(self.ctx())
        self.assertEqual(self.http.calls, [])
        self.assertEqual(report["sent"], 0)
        self.assertEqual(report["no_bets"], 1)

    def test_tickets_graded_before_the_lookback_are_not_replayed(self):
        u = self.user()
        d = self.dog(u)
        self.settled(d, "WIN", at=(NOW - timedelta(hours=jobs.LOOKBACK_HOURS + 1)).strftime("%Y-%m-%dT%H:%M:%SZ"))
        jobs.run_nightly(self.ctx())
        self.assertEqual(self.http.calls, [])

    def test_a_rerun_and_a_late_second_run_never_repeat_a_ticket(self):
        u, d = self.win_night()
        jobs.run_nightly(self.ctx())
        self.assertEqual(jobs.run_nightly(self.ctx())["sent"], 0)                  # same day: duplicate/no_bets
        self.assertEqual(len(self.http.calls), 1)
        later = self.ctx(now=NOW + timedelta(days=1))                              # next morning, same tickets
        report = jobs.run_nightly(later)
        self.assertEqual((report["sent"], report["no_bets"]), (0, 1))
        self.settled(d, "WIN", price=150, at="2026-10-22T09:00:00Z", selection="Chicago Cubs to win")
        report = jobs.run_nightly(later)
        self.assertEqual(report["sent"], 1)
        text = self.sent_bodies()[1]["text"]
        self.assertIn("Chicago Cubs to win", text)
        self.assertNotIn("Over 8.5", text)                                         # yesterday's tickets are not back
        self.assertIn("Record 3-1 over 4 bets.", text)

    def test_an_unsubscribed_account_gets_nothing(self):
        u, d = self.win_night()
        prefs.set_unsubscribed(u.id, db=self.db)
        report = jobs.run_nightly(self.ctx())
        self.assertEqual(self.http.calls, [])
        self.assertEqual(report["unsubscribed"], 1)

    def test_without_a_key_the_job_sends_nothing_and_leaves_no_trace(self):
        self.win_night()
        report = jobs.run_nightly(self.ctx(env={}))
        self.assertEqual(self.http.calls, [])
        self.assertEqual(report["disabled"], 1)
        self.assertFalse(self.log.path.exists())

    def test_one_email_per_user_covers_every_hound_that_settled(self):
        u = self.user()
        a, b = self.dog(u, "Rex"), self.dog(u, "Milo")
        self.settled(a, "WIN")
        self.settled(b, "LOSS")
        self.settled(b, "WIN")
        jobs.run_nightly(self.ctx())
        self.assertEqual(len(self.http.calls), 1)
        body = self.sent_bodies()[0]
        self.assertEqual(body["subject"], "Your hounds went 2-1 last night")
        self.assertIn("Rex went 1-0 last night.", body["text"])
        self.assertIn("Milo went 1-1 last night.", body["text"])

    def test_a_ticket_priced_minus_200_or_worse_is_never_shown(self):
        u = self.user()
        d = self.dog(u)
        self.settled(d, "WIN", price=-210, selection="Heavy Favourite to win")
        jobs.run_nightly(self.ctx())
        self.assertEqual(self.http.calls, [])                                     # nothing else to report
        self.settled(d, "WIN", price=-150, selection="Fine Favourite to win")
        self.settled(d, "WIN", price=-200, selection="Edge Of The Cap to win")
        jobs.run_nightly(self.ctx())
        text = self.sent_bodies()[0]["text"]
        self.assertIn("Fine Favourite to win", text)
        self.assertNotIn("Heavy Favourite", text)
        self.assertNotIn("Edge Of The Cap", text)

    def test_voids_alone_send_nothing_and_a_replay_row_is_not_a_ticket(self):
        u = self.user()
        d = self.dog(u)
        self.settled(d, "VOID")
        self.settled(d, "WIN", segment="replay")
        jobs.run_nightly(self.ctx())
        self.assertEqual(self.http.calls, [])

    def test_a_removed_hound_is_not_reported_and_a_suspended_account_is_skipped(self):
        u = self.user()
        d = self.dog(u, "Gone")
        self.settled(d, "WIN")
        user_store.retire_hound(d["id"], by=f"owner:{u.id}", reason=user_store.OWNER_REMOVED_REASON, db=self.db)
        s = self.user("suspended.tester@sample-mail.net")
        e = self.dog(s, "Held")
        self.settled(e, "WIN")
        users_store.set_user_status(s.id, "suspended", db=self.db)
        jobs.run_nightly(self.ctx())
        self.assertEqual(self.http.calls, [])

    def test_reserved_and_example_addresses_are_never_mailed(self):
        u = self.user("someone@example.com")
        self.settled(self.dog(u), "WIN")
        report = jobs.run_nightly(self.ctx())
        self.assertEqual((self.http.calls, report["undeliverable"]), ([], 1))

    def test_the_stake_the_owner_chose_scales_the_units_and_the_bankroll(self):
        u = self.user()
        d = self.dog(u)
        self.settled(d, "WIN", price=100, stake=2.0)
        jobs.run_nightly(self.ctx())
        text = self.sent_bodies()[0]["text"]
        self.assertIn("+2.00u", text)
        self.assertIn("Bankroll $1,020 paper", text)

    def test_a_failed_send_is_retried_on_the_next_run_and_reports_the_ticket_once(self):
        self.win_night()
        self.http.answers = [(500, b"{}"), (500, b"{}")]
        self.assertEqual(jobs.run_nightly(self.ctx())["failed"], 1)
        self.assertEqual(jobs.run_nightly(self.ctx())["sent"], 1)


# ---------------------------------------------------------------------------
# (c) the Sunday pack
# ---------------------------------------------------------------------------

LEADERBOARD = {"hounds": [
    {"id": "h1", "name": "Setter", "kind": "house", "status": "running",
     "record": {"wins": 12, "losses": 9, "pushes": 1}, "bankroll": {"current": 1042.0, "settled": 22, "small_sample_min": 20}},
    {"id": "h2", "name": "Pointer", "kind": "house", "status": "running",
     "record": {"wins": 30, "losses": 25, "pushes": 0}, "bankroll": {"current": 1110.5, "settled": 55, "small_sample_min": 20}},
    {"id": "h3", "name": "Rookie", "kind": "house", "status": "running",
     "record": {"wins": 3, "losses": 0, "pushes": 0}, "bankroll": {"current": 1031.0, "settled": 3, "small_sample_min": 20}},
    {"id": "h4", "name": "Steamy", "kind": "house", "status": "running",
     "record": {"wins": 10, "losses": 10, "pushes": 0}, "bankroll": {"current": 995.0, "settled": 20, "small_sample_min": 20}},
    {"id": "h5", "name": "Fourth", "kind": "house", "status": "running",
     "record": {"wins": 8, "losses": 8, "pushes": 0}, "bankroll": {"current": 980.0, "settled": 22, "small_sample_min": 20}},
    {"id": "u1", "name": "Somebody's", "kind": "user", "status": "running",
     "record": {"wins": 50, "losses": 1, "pushes": 0}, "bankroll": {"current": 1500.0, "settled": 51, "small_sample_min": 20}},
    {"id": "h6", "name": "Old", "kind": "house", "status": "retired",
     "record": {"wins": 50, "losses": 1, "pushes": 0}, "bankroll": {"current": 1400.0, "settled": 51, "small_sample_min": 20}},
]}


class TheSundayPack(Base):
    def test_the_house_top_three_is_house_only_ranked_and_by_bankroll(self):
        top = jobs.house_top_three(LEADERBOARD)
        self.assertEqual([r["name"] for r in top], ["Pointer", "Setter", "Steamy"])
        self.assertEqual(top[0]["bankroll"], 1110.5)
        self.assertIsNone(jobs.house_top_three(None))
        self.assertEqual(jobs.house_top_three({"hounds": []}), [])

    def test_it_reports_the_week_per_hound_and_the_top_three(self):
        u = self.user()
        a, b = self.dog(u, "Rex"), self.dog(u, "Milo")
        self.settled(a, "WIN", at="2026-10-22T20:00:00Z")
        self.settled(a, "LOSS", at="2026-10-23T20:00:00Z")
        self.settled(a, "WIN", at="2026-10-10T20:00:00Z")                          # older than the week
        report = jobs.run_sunday(self.ctx(now=SUNDAY, house_top=lambda: jobs.house_top_three(LEADERBOARD)))
        self.assertEqual(report["sent"], 1)
        body = self.sent_bodies()[0]
        self.assertEqual(body["subject"], "Your hounds' week: 1-1")
        self.assertIn("Rex: 1-1 this week over 2 bets", body["text"])
        self.assertIn("Milo: no tickets settled this week.", body["text"])
        self.assertIn("Record 2-1 over 3 bets.", body["text"])                     # Rex's season, not just the week
        self.assertIn("1. Pointer", body["text"])
        self.assertIn("2. Setter", body["text"])
        self.assertIn("3. Steamy", body["text"])
        self.assertNotIn("Rookie", body["text"])
        self.assertNotIn("Somebody", body["text"])
        self.assertIn("at least 20 settled bets", body["text"])

    def test_a_quiet_week_still_goes_out_and_the_pack_section_is_left_out_when_there_is_no_board(self):
        u = self.user()
        self.dog(u, "Rex")
        jobs.run_sunday(self.ctx(now=SUNDAY, house_top=lambda: None))
        body = self.sent_bodies()[0]
        self.assertEqual(body["subject"], "Sunday pack: no tickets settled this week")
        self.assertNotIn("House pack", body["text"])

    def test_it_is_sent_once_a_day_and_respects_the_unsubscribe(self):
        u = self.user()
        self.dog(u)
        v = self.user("second.tester@sample-mail.net")
        self.dog(v, "Milo")
        prefs.set_unsubscribed(v.id, db=self.db)
        jobs.run_sunday(self.ctx(now=SUNDAY))
        report = jobs.run_sunday(self.ctx(now=SUNDAY))
        self.assertEqual(len(self.http.calls), 1)
        self.assertEqual((report["duplicate"], report["unsubscribed"]), (1, 1))

    def test_an_account_with_no_hound_gets_no_pack(self):
        self.user()
        jobs.run_sunday(self.ctx(now=SUNDAY))
        self.assertEqual(self.http.calls, [])


# ---------------------------------------------------------------------------
# the schedule
# ---------------------------------------------------------------------------

class TheSchedule(Base):
    def due(self, text):
        return jobs.due_jobs(datetime.fromisoformat(text))

    def test_the_windows_are_in_eastern_time_through_a_change_of_clocks(self):
        self.assertEqual(self.due("2026-10-21T12:59:00+00:00"), [])                # Wed 08:59 EDT
        self.assertEqual(self.due("2026-10-21T13:00:00+00:00"), ["nightly"])       # 09:00 EDT
        self.assertEqual(self.due("2026-10-21T14:59:00+00:00"), ["nightly"])
        self.assertEqual(self.due("2026-10-21T15:00:00+00:00"), [])                # 11:00 EDT: window closed
        self.assertEqual(self.due("2026-10-25T14:00:00+00:00"), ["nightly", "sunday"])      # Sun 10:00 EDT
        # Sunday 2026-11-01 is the day the clocks go back: 10:00 is EST, 15:00Z
        self.assertEqual(self.due("2026-11-01T14:00:00+00:00"), ["nightly"])       # 09:00 EST
        self.assertEqual(self.due("2026-11-01T15:00:00+00:00"), ["nightly", "sunday"])
        self.assertEqual(self.due("2026-10-24T14:00:00+00:00"), ["nightly"])       # Saturday: no pack

    def test_a_tick_waits_for_settlement_then_runs_once_and_remembers(self):
        u = self.user()
        self.settled(self.dog(u), "WIN")
        self.assertEqual(jobs.tick(self.ctx(settle_gate=lambda n: False)), {"nightly": "waiting for settlement"})
        self.assertEqual(self.http.calls, [])
        first = jobs.tick(self.ctx())
        self.assertEqual(first["nightly"]["sent"], 1)
        self.assertEqual(jobs.tick(self.ctx()), {"nightly": "done"})
        self.assertEqual(len(self.http.calls), 1)

    def test_a_run_with_a_failure_is_not_marked_done_so_the_next_tick_retries(self):
        u = self.user()
        self.settled(self.dog(u), "WIN")
        self.http.answers = [(500, b"{}"), (500, b"{}")]
        self.assertEqual(jobs.tick(self.ctx())["nightly"]["failed"], 1)
        self.assertEqual(jobs.tick(self.ctx())["nightly"]["sent"], 1)
        self.assertEqual(jobs.tick(self.ctx()), {"nightly": "done"})

    def test_the_sunday_pack_is_off_by_default_even_with_a_key(self):
        # Owner 2026-10-20: transactional only until there is a postal address. A Sunday tick with the key set
        # must not send the pack unless EMAIL_SUNDAY=on AND a postal address exists.
        u = self.user()
        self.dog(u)
        sunday = lambda **kw: jobs.tick(self.ctx(now=SUNDAY, **kw)).get("sunday")
        self.assertEqual(sunday(), "off")
        self.assertEqual(sunday(env={**ENV, jobs.ENV_SUNDAY: "on"}), "off")                  # no postal address
        self.assertEqual(sunday(address="1 Main St, Town"), "off")                            # not opted in
        self.assertFalse([c for c in self.http.calls if "week" in c["body"]["subject"].lower()
                          or "sunday" in c["body"]["subject"].lower()])
        report = sunday(env={**ENV, jobs.ENV_SUNDAY: "on"}, address="1 Main St, Town")
        self.assertEqual(report["sent"], 1)

    def test_nothing_runs_outside_the_window(self):
        u = self.user()
        self.settled(self.dog(u), "WIN")
        self.assertEqual(jobs.tick(self.ctx(now=NOW + timedelta(hours=8))), {})
        self.assertEqual(self.http.calls, [])

    def test_the_default_settle_gate_follows_the_engine_when_one_runs_here(self):
        from src.hounds import user_runner
        with mock.patch.dict(user_runner.STATUS, {"enabled": False}):
            self.assertTrue(jobs.default_settle_gate(NOW))
        with mock.patch.dict(user_runner.STATUS, {"enabled": True, "running": False,
                                                  "last_pass_utc": "2026-10-21T12:50:00Z"}):
            self.assertFalse(jobs.default_settle_gate(NOW))                       # pass was before 09:00 EDT
        with mock.patch.dict(user_runner.STATUS, {"enabled": True, "running": False,
                                                  "last_pass_utc": "2026-10-21T13:05:00Z"}):
            self.assertTrue(jobs.default_settle_gate(NOW))
        with mock.patch.dict(user_runner.STATUS, {"enabled": True, "running": True,
                                                  "last_pass_utc": "2026-10-21T13:05:00Z"}):
            self.assertFalse(jobs.default_settle_gate(NOW))

    def test_the_loop_does_not_start_without_a_key_or_when_switched_off(self):
        self.assertIsNone(jobs.start_loop(env={}))
        self.assertIsNone(jobs.start_loop(env={mail.ENV_KEY: KEY, "EMAIL_JOBS": "off"}))
        self.assertFalse(jobs.STATUS["enabled"])

    def test_the_loop_ticks_on_one_daemon_thread_and_stops(self):
        ran, stop = threading.Event(), threading.Event()
        thread = jobs.start_loop(env=ENV, ready=lambda: True, stop_event=stop, tick_s=0.01,
                                 do_tick=ran.set)
        try:
            self.assertTrue(thread.daemon)
            self.assertTrue(ran.wait(2.0))
        finally:
            stop.set()
            thread.join(2.0)
        self.assertFalse(thread.is_alive())

    def test_status_counts_what_was_sent_and_never_shows_an_address_or_the_key(self):
        u = self.user()
        self.settled(self.dog(u), "WIN")
        jobs.run_nightly(self.ctx())
        status = jobs.status_report(self.ctx())
        self.assertTrue(status["enabled"])
        self.assertEqual(status["sent_last_7_days"], {"nightly": 1})
        self.assertEqual(status["last_runs"][-1]["counts"]["sent"], 1)
        blob = json.dumps(status)
        self.assertNotIn(KEY, blob)
        self.assertNotIn(ADDRESS, blob)
        self.assertFalse(jobs.status_report(self.ctx(env={}))["enabled"])


# ---------------------------------------------------------------------------
# the hard lines, over every message the product can send
# ---------------------------------------------------------------------------

BANNED = re.compile(r"profit|edge\b|guarantee|winning|winner|bet ?check|\block\b|sure thing|free money|beat the|"
                    r"streak|on fire|\bROI\b|!", re.I)


class TheHardLines(Base):
    def all_messages(self):
        u = self.user()
        d = self.dog(u, "Rex")
        self.settled(d, "WIN")
        self.settled(d, "LOSS")
        unsub = prefs.unsubscribe_url(u.id, secret=SECRET)
        top = jobs.house_top_three(LEADERBOARD)
        dog = {"id": d["id"], "name": "Rex", "url": "https://linehound.app/web/hound.html?id=x",
               "tickets": [{"selection": "Boston Red Sox to win", "market": "moneyline", "sport": "MLB",
                            "game": "Boston Red Sox at Seattle Mariners", "price": 120, "result": "WIN",
                            "units": 1.2}],
               "season": {"w": 1, "l": 0, "p": 0}, "bankroll": 1012.0}
        week = {"id": d["id"], "name": "Rex", "url": "https://linehound.app/web/hound.html?id=x",
                "week": {"w": 1, "l": 0, "p": 0, "units": 1.2}, "season": {"w": 1, "l": 0, "p": 0}, "bankroll": 1012.0}
        return [render.keep_confirmation(to=ADDRESS, dog_name="Rex", dog_url="https://linehound.app/web/hound.html?id=x",
                                         unsubscribe_url=unsub),
                render.nightly_result(to=ADDRESS, dogs=[dog], unsubscribe_url=unsub, kennel_url="https://linehound.app/web/kennel.html"),
                render.sunday_pack(to=ADDRESS, dogs=[week], house_top=top, unsubscribe_url=unsub,
                                   leaderboard_url="https://linehound.app/web/hounds.html"),
                render.admin_test_message(to=ADDRESS, unsubscribe_url=unsub)]

    def test_no_message_claims_profit_an_edge_or_winning_or_mentions_bet_check(self):
        for msg in self.all_messages():
            for part in ("subject", "html", "text"):
                plain = re.sub(r"<[^>]+>", " ", msg[part]) if part == "html" else msg[part]
                self.assertIsNone(BANNED.search(plain), f"{msg['subject']!r} {part}: {BANNED.search(plain)}")

    def test_every_message_carries_the_disclosure_a_tel_link_and_a_one_click_unsubscribe(self):
        for msg in self.all_messages():
            self.assertIn(render.DISCLOSURE, msg["text"])
            self.assertIn("21+ · Paper bets only, not advice ·", msg["html"])
            self.assertIn('href="tel:+18004262537"', msg["html"])
            self.assertIn("/email/unsubscribe?t=", msg["html"])
            self.assertIn("Pause these emails", msg["html"])
            self.assertEqual(msg["headers"]["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
            self.assertRegex(msg["headers"]["List-Unsubscribe"], r"^<https://linehound\.app/email/unsubscribe\?t=\d+\.[0-9a-f]{32}>$")

    def test_no_emoji_and_no_non_ascii_beyond_the_middle_dot(self):
        for msg in self.all_messages():
            for part in ("subject", "html", "text"):
                stripped = msg[part].replace("·", "")
                self.assertTrue(stripped.isascii(), f"{part}: {[c for c in stripped if not c.isascii()]}")

    def test_the_postal_address_is_shown_only_when_one_is_configured(self):
        without = render.keep_confirmation(to=ADDRESS, dog_name="Rex", dog_url="https://x/y", unsubscribe_url="https://x/u")
        with_ = render.keep_confirmation(to=ADDRESS, dog_name="Rex", dog_url="https://x/y", unsubscribe_url="https://x/u",
                                         address="1 Main St, Springfield, IL 62701")
        self.assertNotIn("Main St", without["html"] + without["text"])
        self.assertIn("1 Main St, Springfield, IL 62701", with_["html"])
        self.assertIn("1 Main St, Springfield, IL 62701", with_["text"])

    def test_names_are_escaped_in_html(self):
        msg = render.keep_confirmation(to=ADDRESS, dog_name="<b>Rex</b>", dog_url="https://x/y?a=1&b=2",
                                       unsubscribe_url="https://x/u")
        self.assertNotIn("<b>Rex</b>", msg["html"])
        self.assertIn("&lt;b&gt;Rex&lt;/b&gt;", msg["html"])

    def test_prices_worse_than_the_cap_are_not_shown(self):
        self.assertFalse(render.price_shown(-200))
        self.assertFalse(render.price_shown(-250))
        self.assertFalse(render.price_shown(None))
        self.assertTrue(render.price_shown(-199))
        self.assertTrue(render.price_shown(150))

    def test_the_footer_text_is_the_one_the_owner_asked_for(self):
        self.assertEqual(render.DISCLOSURE, "21+ · Paper bets only, not advice · 1-800-GAMBLER")


# ---------------------------------------------------------------------------
# the routes (needs FastAPI; skipped on the Linux CI image that has none)
# ---------------------------------------------------------------------------

def _asgi(app, method, path, *, query=b"", headers=None, body=None):
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    payload = b"" if body is None else json.dumps(body).encode()
    if body is not None:
        raw.append((b"content-type", b"application/json"))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
             "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": query,
             "headers": raw, "client": ("127.0.0.1", 33333), "server": ("testserver", 80)}
    captured, parts = {}, []

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            captured["status"] = message["status"]
        elif message["type"] == "http.response.body":
            parts.append(message.get("body", b""))

    asyncio.new_event_loop().run_until_complete(app(scope, receive, send))
    text = b"".join(parts)
    try:
        return captured["status"], json.loads(text)
    except ValueError:
        return captured["status"], text.decode("utf-8", "replace")


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheRoutes(Base):
    ADMIN = {"X-Admin-Token": "admin-token-for-email-tests"}

    def setUp(self):
        super().setUp()
        env = mock.patch.dict("os.environ", {"APP_ADMIN_TOKEN": "admin-token-for-email-tests",
                                              "EMAIL_SIGNING_SECRET": SECRET.decode()}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        import os
        os.environ.pop(mail.ENV_KEY, None)
        from api.app import app
        self.app = app

    def test_the_unsubscribe_link_flips_the_flag_and_is_idempotent(self):
        u = self.user()
        q = ("t=" + prefs.token(u.id)).encode()
        status, page = _asgi(self.app, "GET", "/email/unsubscribe", query=q)
        self.assertEqual(status, 200)
        self.assertIn("Emails paused", page)
        self.assertTrue(prefs.is_unsubscribed(u.id, db=self.db))
        self.assertEqual(_asgi(self.app, "GET", "/email/unsubscribe", query=q)[0], 200)

    def test_a_bad_or_missing_token_is_a_400_and_changes_nothing(self):
        u = self.user()
        for q in (b"", b"t=junk", ("t=" + prefs.token(u.id)[:-2]).encode(), f"t={u.id}.{'0' * 32}".encode()):
            self.assertEqual(_asgi(self.app, "GET", "/email/unsubscribe", query=q)[0], 400)
        self.assertFalse(prefs.is_unsubscribed(u.id, db=self.db))

    def test_a_valid_token_for_an_unknown_account_reads_the_same_and_writes_nothing(self):
        status, _ = _asgi(self.app, "GET", "/email/unsubscribe", query=("t=" + prefs.token(999)).encode())
        self.assertEqual(status, 200)
        self.assertEqual(prefs.unsubscribed_ids(db=self.db), set())

    def test_the_mail_clients_one_click_post_works(self):
        u = self.user()
        status, text = _asgi(self.app, "POST", "/email/unsubscribe", query=("t=" + prefs.token(u.id)).encode())
        self.assertEqual((status, text), (200, "ok"))
        self.assertTrue(prefs.is_unsubscribed(u.id, db=self.db))

    def test_the_admin_routes_need_the_admin_token(self):
        self.assertEqual(_asgi(self.app, "GET", "/admin/email/status")[0], 401)
        self.assertEqual(_asgi(self.app, "POST", "/admin/email/test", body={"to": ADDRESS})[0], 401)

    def test_status_says_disabled_without_a_key(self):
        status, body = _asgi(self.app, "GET", "/admin/email/status", headers=self.ADMIN)
        self.assertEqual(status, 200)
        self.assertFalse(body["enabled"])
        self.assertEqual(body["sent_last_7_days"], {})

    def test_the_admin_test_email_says_so_when_there_is_no_key_and_sends_nothing(self):
        status, body = _asgi(self.app, "POST", "/admin/email/test", headers=self.ADMIN, body={"to": ADDRESS})
        self.assertEqual((status, body["sent"], body["status"]), (200, False, "disabled"))

    def test_the_admin_test_email_sends_through_the_transport_when_a_key_is_set(self):
        with mock.patch.dict("os.environ", {mail.ENV_KEY: KEY}), \
                mock.patch.object(mail, "urllib_sender", self.http), \
                mock.patch.object(mail, "default_log", lambda: self.log):
            status, body = _asgi(self.app, "POST", "/admin/email/test", headers=self.ADMIN, body={"to": ADDRESS})
            self.assertEqual((status, body["sent"]), (200, True))
            self.assertEqual(body["to"], "b***@s***.net")
            self.assertNotIn(ADDRESS, json.dumps(body))
            self.assertEqual(self.http.calls[0]["body"]["to"], [ADDRESS])
            self.assertEqual(self.http.calls[0]["body"]["subject"], "LINEHOUND test email")
            status, body = _asgi(self.app, "POST", "/admin/email/test", headers=self.ADMIN, body={"to": "nope"})
            self.assertEqual(status, 400)
            status, st = _asgi(self.app, "GET", "/admin/email/status", headers=self.ADMIN)
            self.assertTrue(st["enabled"])
            self.assertEqual(st["sent_last_7_days"], {"test": 1})
            self.assertNotIn(KEY, json.dumps(st))

    def test_the_app_starts_no_email_thread_without_a_key(self):
        import api.app as app_module
        import os
        os.environ.pop(mail.ENV_KEY, None)
        before = {t.name for t in threading.enumerate()}
        app_module._start_email_jobs()
        self.assertEqual({t.name for t in threading.enumerate()} - before, set())

    def test_signup_sends_the_keep_email_only_for_a_hound_the_new_account_owns(self):
        from api import free_signup
        owner = self.user()
        mine = self.dog(owner, "Rex")
        other = self.user("second.tester@sample-mail.net")
        theirs = self.dog(other, "Milo")
        with mock.patch("src.notify.email_jobs.send_keep_confirmation_async") as hook:
            free_signup._send_keep_email(owner, mine["id"])
            hook.assert_called_once()
            hook.reset_mock()
            free_signup._send_keep_email(owner, theirs["id"])           # someone else's dog
            free_signup._send_keep_email(owner, "u-nonexistent")
            free_signup._send_keep_email(owner, None)
            free_signup._send_keep_email(owner, {"a": 1})
            hook.assert_not_called()


if __name__ == "__main__":
    unittest.main()
