"""The "your full access is ending" warning: who gets it, when, in what words, and the reminder emails.

Time is injected everywhere and every store is a temp database (users.db_path is patched, as the other store
tests do), so nothing here reads the real disk or the clock. The route tests skip without FastAPI (Linux CI); the
copy tests run the real web/js/access-ending-copy.js under node (skipped without node).
"""

from __future__ import annotations

import dataclasses
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

try:
    from fastapi import HTTPException, Response
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.appstate import access_ending as ending
from src.appstate import customers, testers
from src.appstate import users as users_store
from src.notify import email as mail
from src.notify import email_jobs as jobs
from tests.hounds_web_runner import HAS_NODE

REPO = Path(__file__).resolve().parent.parent
UTC = timezone.utc
GRANTED = datetime(2026, 10, 24, 17, 0, tzinfo=UTC)          # 7 days later: Saturday 2026-10-31 17:00Z = 10:00 PDT
ENDS = GRANTED + timedelta(days=7)
ENV = {"RESEND_API_KEY": "test-key-not-real"}
BANNED = re.compile(r"\bbeta\b|\bnew\b|\bdogs?\b|bet check|betcheck|nothing cleared|early access", re.I)


def at(day, hour=17):
    return datetime(2026, 10, day, hour, 0, tzinfo=UTC)


class FakeHttp:
    def __init__(self):
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append(json.loads(body.decode("utf-8")))
        return 200, json.dumps({"id": f"em_{len(self.calls)}"}).encode("utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.db = self.dir / "app.db"
        p = mock.patch.object(users_store, "db_path", lambda: self.db)
        p.start()
        self.addCleanup(p.stop)

    def make_tester(self, email="tess@gmail.com"):
        testers.grant_tester(email=email, now=GRANTED, db=self.db)
        return users_store.get_user_by_email(email, db=self.db)


class TheDecision(Base):
    def test_a_tester_is_warned_inside_three_days_with_the_day_count_and_date(self):
        user = self.make_tester()
        three = ending.ending_notice(user, now=at(28))
        self.assertEqual((three["show_warning"], three["days_left"], three["kind"]), (True, 3, "tester"))
        self.assertEqual(three["ends_on"], "Saturday, October 31")
        two = ending.ending_notice(user, now=at(29))
        self.assertEqual((two["show_warning"], two["days_left"]), (True, 2))
        self.assertFalse(two["ends_today"])

    def test_more_than_three_days_out_shows_nothing(self):
        notice = ending.ending_notice(self.make_tester(), now=at(27))
        self.assertFalse(notice["show_warning"])
        self.assertEqual(notice["days_left"], 4)

    def test_the_last_day_says_today_and_after_the_end_nothing(self):
        user = self.make_tester()
        last = ending.ending_notice(user, now=at(31, 15))          # 08:00 PDT, two hours before the end
        self.assertEqual((last["show_warning"], last["days_left"], last["ends_today"]), (True, 0, True))
        self.assertFalse(ending.ending_notice(user, now=at(31, 18))["show_warning"])   # ended 10:00 PDT
        self.assertFalse(ending.ending_notice(user, now=at(31, 18)).get("ends_today", False))

    def test_the_count_is_pacific_calendar_days_not_24_hour_spans(self):
        # 05:00Z on the 31st is still the 30th in Pacific (22:00 PDT): the end is 1 calendar day away, though only 36h.
        self.assertEqual(ending.days_until(ENDS, datetime(2026, 10, 31, 5, 0, tzinfo=UTC)), 1)
        self.assertEqual(ending.days_until(ENDS, datetime(2026, 10, 31, 16, 0, tzinfo=UTC)), 0)
        self.assertIsNone(ending.days_until(ENDS, ENDS))
        # standard time: the 8-hour offset after daylight time ends on 2026-11-01
        self.assertEqual(ending.to_pacific(datetime(2026, 11, 2, 7, 30, tzinfo=UTC)).day, 1)
        self.assertEqual(ending.to_pacific(datetime(2026, 11, 2, 8, 30, tzinfo=UTC)).day, 2)

    def test_accounts_without_an_end_date_are_never_warned(self):
        free = users_store.create_user("free@gmail.com", status="active", plan="free", db=self.db)
        beta = users_store.create_user("beta@gmail.com", status="active", plan="beta", db=self.db)
        renewing = users_store.create_user("pay@gmail.com", status="active", plan="beta", db=self.db)
        customers.upsert_subscription(renewing.id, "sub_1", "active", paid_through=at(29).isoformat(),
                                      current_period_end=at(29).isoformat(), db=self.db)
        for user in (free, beta, renewing, None):
            self.assertEqual(ending.ending_notice(user, now=at(29)), {"show_warning": False, "kind": None})

    def test_a_cancelled_trial_is_warned_and_a_renewing_one_is_not(self):
        user = users_store.create_user("trial@gmail.com", status="active", plan="beta", db=self.db)
        customers.upsert_subscription(user.id, "sub_t", "trialing", cancel_at=at(31).isoformat(),
                                      current_period_end=at(31).isoformat(), paid_through=at(31).isoformat(), db=self.db)
        notice = ending.ending_notice(user, now=at(29))
        self.assertEqual((notice["show_warning"], notice["kind"], notice["days_left"]), (True, "trial", 2))
        customers.upsert_subscription(user.id, "sub_t", "trialing", cancel_at=None,
                                      current_period_end=at(31).isoformat(), paid_through=at(31).isoformat(), db=self.db)
        self.assertFalse(ending.ending_notice(user, now=at(29))["show_warning"])

    def test_a_suspended_tester_is_not_warned(self):
        user = dataclasses.replace(self.make_tester(), status="suspended")
        self.assertFalse(ending.ending_notice(user, now=at(29))["show_warning"])


@unittest.skipUnless(HAS_FASTAPI, "FastAPI not installed")
class TheRoute(Base):
    def test_no_token_is_a_401_and_the_route_depends_on_it(self):
        from api import auth, me_access
        with self.assertRaises(HTTPException) as cm:
            auth.get_current_user(authorization=None)
        self.assertEqual(cm.exception.status_code, 401)
        deps = [d.call for d in me_access.router.routes[0].dependant.dependencies]
        self.assertIn(auth.get_current_user, deps)

    def test_the_body_has_the_dates_and_price_and_no_secrets(self):
        from api import me_access
        user = self.make_tester()
        offer = {"founding": {"price_cents": 1499, "cap": 50, "taken": 10, "left": 40, "reserved": 0, "available": True},
                 "standard": {"price_cents": 1999}}
        with mock.patch.object(ending, "datetime", wraps=datetime) as fake, \
                mock.patch("api.me_access.billing.founding_offer", return_value=offer):
            fake.now.return_value = at(29)
            body = me_access.my_access(Response(), user, None)
        self.assertEqual((body["show_warning"], body["days_left"]), (True, 2))
        self.assertEqual(body["founding"], {"price_cents": 1499, "left": 40, "cap": 50})
        self.assertEqual(body["standard_price_cents"], 1999)
        blob = json.dumps(body).lower()
        self.assertNotIn("tess@gmail.com", blob)
        self.assertNotIn("token", blob)

    def test_sold_out_gives_only_the_standard_price(self):
        from api import me_access
        offer = {"founding": {"price_cents": 1499, "cap": 50, "taken": 50, "left": 0, "reserved": 0, "available": False},
                 "standard": {"price_cents": 1999}}
        with mock.patch("api.me_access.billing.founding_offer", return_value=offer):
            self.assertEqual(me_access.offer_for_banner(), {"founding": None, "standard_price_cents": 1999})

    def test_the_router_is_mounted_on_the_app(self):
        self.assertIn("app.include_router(me_access_router)", (REPO / "api" / "app.py").read_text(encoding="utf-8"))


class ThePages(unittest.TestCase):
    def test_the_nav_boots_the_banner_and_the_member_pages_load_the_nav(self):
        nav = (REPO / "web" / "js" / "nav.js").read_text(encoding="utf-8")
        self.assertIn("startAccessEnding()", nav)
        for page in ("kennel.html", "tonight.html"):
            self.assertIn('src="js/nav.js"', (REPO / "web" / page).read_text(encoding="utf-8"), page)

    def test_the_new_files_ship_in_the_image(self):
        docker = (REPO / "deploy" / "Dockerfile").read_text(encoding="utf-8")
        for line in ("COPY web/ web/", "COPY api/ api/", "COPY src/ src/"):
            self.assertIn(line, docker)
        ignore = (REPO / ".dockerignore").read_text(encoding="utf-8")
        for path in ("web/js/access-ending.js", "api/me_access.py"):
            for pattern in (ln.strip() for ln in ignore.splitlines() if ln.strip() and not ln.startswith(("#", "!"))):
                self.assertNotEqual(pattern.rstrip("/"), path, pattern)


def _copy(notice):
    node = shutil.which("node")
    script = ("import * as c from %s; const n = JSON.parse(process.argv[1]); "
              "console.log(JSON.stringify({copy: c.bannerCopy(n), show: c.shouldShow(n, process.argv[2] || null, 'D')}));"
              % json.dumps((REPO / "web" / "js" / "access-ending-copy.js").as_uri()))
    out = subprocess.run([node, "--input-type=module", "-e", script, json.dumps(notice), "D" if notice.get("_dismissed") else ""],
                         capture_output=True, text=True, encoding="utf-8", timeout=60, check=True)
    return json.loads(out.stdout)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheWords(unittest.TestCase):
    FOUNDING = {"price_cents": 1499, "left": 12, "cap": 50}

    def test_days_and_date_and_what_stays_and_goes(self):
        out = _copy({"show_warning": True, "days_left": 2, "ends_on": "Saturday, October 31", "ends_today": False,
                     "founding": self.FOUNDING, "standard_price_cents": 1999})
        c = out["copy"]
        self.assertEqual(c["title"], "Your full access ends in 2 days (on Saturday, October 31).")
        self.assertEqual(c["keep"], ending.KEEP_LINE)
        self.assertEqual(c["lose"], ending.LOSE_LINE)
        self.assertEqual(c["button"], "Keep full access at $14.99/mo")
        self.assertIn("12 of 50", c["seats"])
        self.assertIn("1-800-GAMBLER", c["fine"])
        self.assertIn("21+", c["fine"])

    def test_one_day_today_and_the_standard_price_when_sold_out(self):
        one = _copy({"show_warning": True, "days_left": 1, "ends_on": "Saturday, October 31", "founding": None,
                     "standard_price_cents": 1999})["copy"]
        self.assertTrue(one["title"].startswith("Your full access ends in 1 day "))
        self.assertEqual((one["button"], one["seats"]), ("Keep full access at $19.99/mo", ""))
        today = _copy({"show_warning": True, "days_left": 0, "ends_today": True, "founding": None,
                       "standard_price_cents": 1999})["copy"]
        self.assertEqual(today["title"], "Your full access ends today.")

    def test_shown_only_when_the_server_says_and_not_after_a_dismissal_today(self):
        base = {"days_left": 2, "ends_on": "x", "standard_price_cents": 1999}
        self.assertTrue(_copy({**base, "show_warning": True})["show"])
        self.assertFalse(_copy({**base, "show_warning": False})["show"])
        self.assertFalse(_copy({**base, "show_warning": True, "_dismissed": True})["show"])

    def test_no_banned_words_anywhere_in_the_words(self):
        for notice in ({"days_left": 2, "ends_on": "Saturday, October 31", "founding": self.FOUNDING},
                       {"days_left": 0, "ends_today": True, "founding": None}):
            lines = " ".join(v for v in _copy({"show_warning": True, "standard_price_cents": 1999, **notice})["copy"].values())
            self.assertIsNone(BANNED.search(lines), lines)
        src = (REPO / "web" / "js" / "access-ending-copy.js").read_text(encoding="utf-8")
        self.assertIn(ending.KEEP_LINE, src)
        self.assertIn(ending.LOSE_LINE, src)


class TheEmails(Base):
    def setUp(self):
        super().setUp()
        self.http = FakeHttp()
        self.log = mail.SendLog(self.dir / "send_log.jsonl")
        mail.reset_disabled_notice()

    def ctx(self, now):
        return jobs.Ctx(now=now, db=self.db, http=self.http, log=self.log, env=dict(ENV), sleep=lambda s: None,
                        address="1 Example Way", secret=b"s" * 32)

    def test_one_at_two_days_and_one_on_the_last_day_and_never_twice(self):
        self.make_tester()
        self.assertEqual(jobs.run_ending(self.ctx(at(28, 14)))["sent"], 0)        # 3 days out: nothing
        self.assertEqual(jobs.run_ending(self.ctx(at(29, 14)))["sent"], 1)        # 2 days out
        self.assertEqual(jobs.run_ending(self.ctx(at(29, 15)))["sent"], 0)        # same day again: once
        self.assertEqual(jobs.run_ending(self.ctx(at(30, 14)))["sent"], 0)        # 1 day out: nothing
        self.assertEqual(jobs.run_ending(self.ctx(at(31, 14)))["sent"], 1)        # the last day, before the end
        self.assertEqual(len(self.http.calls), 2)
        self.assertIn("ends in 2 days", self.http.calls[0]["subject"])
        self.assertEqual(self.http.calls[1]["subject"], "Your full access ends today")

    def test_after_the_end_and_for_a_paused_address_nothing_is_sent(self):
        user = self.make_tester()
        self.assertEqual(jobs.run_ending(self.ctx(at(31, 19)))["sent"], 0)
        from src.notify import email_prefs
        email_prefs.set_unsubscribed(user.id, True, db=self.db)
        self.assertEqual(jobs.run_ending(self.ctx(at(29, 14)))["sent"], 0)
        self.assertEqual(self.http.calls, [])

    def test_the_email_follows_the_copy_rules_and_the_job_is_scheduled(self):
        self.make_tester()
        jobs.run_ending(self.ctx(at(29, 14)))
        sent = self.http.calls[0]
        text = sent["subject"] + sent["text"] + sent["html"]
        self.assertIsNone(BANNED.search(sent["subject"] + sent["text"]), sent["text"])
        self.assertIn(ending.KEEP_LINE, sent["text"])
        self.assertIn(ending.LOSE_LINE, sent["text"])
        self.assertIn("1-800-GAMBLER", text)
        self.assertIn(jobs.JOB_ENDING, jobs.due_jobs(datetime(2026, 10, 29, 14, 0, tzinfo=UTC)))
        self.assertNotIn(jobs.JOB_ENDING, jobs.due_jobs(datetime(2026, 10, 29, 20, 0, tzinfo=UTC)))


if __name__ == "__main__":
    unittest.main()
