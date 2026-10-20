"""Self-serve FREE accounts: POST /auth/signup and the member level behind it.

Owner decision "yes open signups" (2026-10-19). A visitor gives an email and a
password and is IN: an active member whose plan is "free", a password, a 30-day
session token. What these tests pin, and why each is easy to get quietly wrong:

  * the account, its password, its token and its event are ONE transaction, the
    token authenticates and ends in 30 days, and the event carries no email;
  * a repeat email creates nothing, touches nothing, and answers in the SAME shape
    as a new one (token null is the only difference, and it cannot be removed);
  * the rate limits are in the database (5 an hour per address, 30 an hour and 100
    a day overall), count every attempt that passes the cheap checks and none that
    do not, and refuse without recording;
  * THE ACCESS SPLIT, which is the point: a free account has no subscription record,
    so the old paid gate (a no-op for any user with no record) would have let it
    straight onto the paid board. Every route that depends on require_paid_access
    refuses it with a 403, GET /digest refuses it, every dog route lets it in, and a
    tester, a comp, a subscriber and an admin-invited beta user are exactly as they
    were;
  * a free account that is later comped, or given a tester week, gets the paid board,
    and loses it again when that ends.

The store half needs no FastAPI (src/ is stdlib only). The route half drives the REAL
app over ASGI, so it is skipped where FastAPI is absent (the Linux CI image).
"""

from __future__ import annotations

import inspect
import json
import os
import re
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

try:
    from fastapi import HTTPException
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.appstate import access
from src.appstate import comps
from src.appstate import customers
from src.appstate import events
from src.appstate import free_members
from src.appstate import passwords
from src.appstate import testers
from src.appstate import users as users_store
from tests.test_comp_access import _asgi, _walk

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
ADMIN = "admin-token-for-the-free-signup-test"
GOOD_PASSWORD = "river-bank-lantern-42"


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "app.db"
        # access.* and customers.* read the app database by default; without this a test that
        # forgets `db=` reads (and creates) the machine's real one and passes or fails by machine
        patch = mock.patch.object(users_store, "db_path", lambda: self.db)
        patch.start()
        self.addCleanup(patch.stop)
        # the default store is the product's own (member_profile); tests choose their own and put it back
        self.addCleanup(free_members.register_kennel_name_store, free_members._kennel_name_store)
        free_members.register_kennel_name_store(None)

    def member(self, email="free@example.com", now=NOW):
        made = free_members.create_free_member(
            email, passwords.hash_password(GOOD_PASSWORD), now=now, db=self.db)
        self.assertIsNotNone(made)
        return made

    def counts(self):
        """Row counts straight from the file, by a connection that shares no code with
        the module under test."""
        with closing(sqlite3.connect(str(self.db))) as conn:
            have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            return {t: (conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] if t in have else 0)
                    for t in ("users", "tokens", "user_passwords", "analytics_events",
                              "login_attempts", "comps", "testers")}

    def paying_subscriber(self, email="paid@example.com"):
        user = users_store.create_user(email, status="active", plan="beta", db=self.db)
        customers.upsert_customer(user.id, f"cus_{user.id}", db=self.db)
        customers.upsert_subscription(
            user.id, f"sub_{user.id}", "active",
            current_period_end=(datetime.now(timezone.utc) + timedelta(days=20)).isoformat(),
            db=self.db)
        return user


# ---------------------------------------------------------------------------
# The account (store, no FastAPI)
# ---------------------------------------------------------------------------

class CreatingAFreeMember(_Base):
    def test_one_transaction_makes_an_active_free_user_a_password_a_token_and_an_event(self):
        made = self.member("Free@Example.com".lower())
        self.assertEqual((made.user.status, made.user.plan), ("active", "free"))
        self.assertEqual(self.counts()["users"], 1)
        self.assertEqual(self.counts()["user_passwords"], 1)
        self.assertEqual(self.counts()["tokens"], 1)
        self.assertEqual(self.counts()["analytics_events"], 1)
        self.assertTrue(passwords.verify_user_password(made.user.id, GOOD_PASSWORD, db=self.db))
        self.assertFalse(passwords.verify_user_password(made.user.id, "something else entirely", db=self.db))

    def test_the_token_authenticates_and_ends_in_thirty_days_not_before_and_not_after(self):
        made = self.member()
        self.assertEqual(made.expires_at, NOW + timedelta(days=30))
        self.assertEqual(access.FREE_TOKEN_TTL, timedelta(days=30))
        self.assertEqual(users_store.authenticate(made.token, db=self.db,
                                                  now=NOW + timedelta(days=29)).id, made.user.id)
        self.assertIsNone(users_store.authenticate(made.token, db=self.db,
                                                   now=NOW + timedelta(days=31)))

    def test_the_event_has_the_member_hashed_and_no_email_password_or_token(self):
        made = self.member("someone.private@example.com")
        with closing(sqlite3.connect(str(self.db))) as conn:
            rows = conn.execute("SELECT user_hash, kind, properties_json FROM analytics_events").fetchall()
        self.assertEqual([r[1] for r in rows], ["signup_free_created"])
        self.assertEqual(rows[0][0], events.hash_user_id(made.user.id))
        blob = json.dumps(rows)
        for secret in ("someone.private", "example.com", GOOD_PASSWORD, made.token):
            self.assertNotIn(secret, blob)
        self.assertEqual(json.loads(rows[0][2]), {"has_kennel_name": False})

    def test_no_table_holds_the_raw_token_or_the_raw_password(self):
        made = self.member()
        with closing(sqlite3.connect(str(self.db))) as conn:
            dump = "\n".join(str(row) for (table,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")
                for row in conn.execute(f"SELECT * FROM {table}"))
        self.assertNotIn(made.token, dump)
        self.assertNotIn(GOOD_PASSWORD, dump)

    def test_the_object_never_prints_the_token(self):
        made = self.member()
        self.assertNotIn(made.token, repr(made))
        self.assertNotIn(made.token, str(made))

    def test_an_existing_email_of_any_kind_creates_nothing_and_changes_nothing(self):
        waitlisted = users_store.create_user("wait@example.com", status="waitlisted", db=self.db)
        invited = users_store.create_user("invited@example.com", status="invited", db=self.db)
        tester = testers.grant_tester(email="tester@example.com", db=self.db)
        comp = comps.grant_comp(email="comp@example.com", reason="friend", db=self.db)
        sub = self.paying_subscriber()
        free = self.member("free2@example.com")
        suspended = users_store.create_user("sus@example.com", status="suspended", db=self.db)
        before = self.counts()
        for email in (waitlisted.email, invited.email, "tester@example.com", "comp@example.com",
                      sub.email, free.user.email, suspended.email):
            with self.subTest(email=email):
                self.assertIsNone(free_members.create_free_member(
                    email, passwords.hash_password(GOOD_PASSWORD), now=NOW, db=self.db))
        self.assertEqual(self.counts(), before)
        # nobody's status or plan moved
        self.assertEqual(users_store.get_user(waitlisted.id, db=self.db).status, "waitlisted")
        self.assertEqual(users_store.get_user(sub.id, db=self.db).plan, "beta")
        self.assertEqual(users_store.get_user(invited.id, db=self.db).plan, "none")
        self.assertIsNotNone(tester.token)
        self.assertIsNotNone(comp.token)


class TheKennelName(unittest.TestCase):
    def setUp(self):
        self.addCleanup(free_members.register_kennel_name_store, free_members._kennel_name_store)
        free_members.register_kennel_name_store(None)

    def test_a_name_is_trimmed_collapsed_and_bounded(self):
        self.assertEqual(free_members.clean_kennel_name("  Back   Forty  "), "Back Forty")
        self.assertIsNone(free_members.clean_kennel_name(None))
        self.assertIsNone(free_members.clean_kennel_name("   "))
        self.assertEqual(len(free_members.clean_kennel_name("x" * 40)), 40)
        with self.assertRaises(free_members.KennelNameRejected):
            free_members.clean_kennel_name("x" * 41)

    def test_control_characters_and_non_text_are_refused(self):
        for bad in ("a\x00b", "a‮b", "a\nb\x07", 5, ["x"], {"a": 1}):
            with self.subTest(bad=bad):
                with self.assertRaises(free_members.KennelNameRejected):
                    free_members.clean_kennel_name(bad)

    def test_with_no_store_registered_the_name_is_dropped(self):
        self.assertFalse(free_members.keep_kennel_name(1, "Back Forty"))

    def test_a_registered_store_gets_the_name_and_a_broken_one_never_fails_a_signup(self):
        seen = []
        free_members.register_kennel_name_store(lambda uid, name: seen.append((uid, name)))
        self.assertTrue(free_members.keep_kennel_name(7, "Back Forty"))
        self.assertEqual(seen, [(7, "Back Forty")])
        self.assertFalse(free_members.keep_kennel_name(7, None))

        def boom(uid, name):
            raise RuntimeError("store is down")
        free_members.register_kennel_name_store(boom)
        with mock.patch("sys.stderr"):
            self.assertFalse(free_members.keep_kennel_name(7, "Back Forty"))


# ---------------------------------------------------------------------------
# The rate limits (store, no FastAPI)
# ---------------------------------------------------------------------------

class RateLimits(_Base):
    T0 = 1_800_000_000.0

    def attempt(self, ip="203.0.113.5", at=0.0):
        return free_members.check_and_record_signup(ip, now=self.T0 + at, db=self.db)

    def test_five_an_hour_per_address_then_a_retry_after_and_nothing_recorded(self):
        for i in range(5):
            self.assertIsNone(self.attempt(at=i), i)
        recorded = self.counts()["login_attempts"]
        retry = self.attempt(at=10)
        self.assertIsNotNone(retry)
        self.assertGreater(retry, 3000)
        self.assertLessEqual(retry, 3600)
        self.assertEqual(self.counts()["login_attempts"], recorded,
                         "a refused attempt must not lengthen its own lockout")

    def test_the_hour_rolls_over(self):
        for i in range(5):
            self.attempt(at=i)
        self.assertIsNotNone(self.attempt(at=3000))
        self.assertIsNone(self.attempt(at=3700))

    def test_another_address_has_its_own_five(self):
        for i in range(5):
            self.attempt(ip="198.51.100.1", at=i)
        self.assertIsNotNone(self.attempt(ip="198.51.100.1", at=6))
        self.assertIsNone(self.attempt(ip="198.51.100.2", at=6))

    def test_thirty_an_hour_across_everyone(self):
        for i in range(30):
            self.assertIsNone(self.attempt(ip=f"10.0.0.{i}", at=i), i)
        self.assertIsNotNone(self.attempt(ip="10.0.9.9", at=31))

    def test_a_hundred_a_day_across_everyone(self):
        # spread over the day so the hourly ceiling never binds: 25 an hour for four hours
        n = 0
        for hour in range(4):
            for k in range(25):
                self.assertIsNone(self.attempt(ip=f"10.{hour}.{k}.1", at=hour * 3700 + k), (hour, k))
                n += 1
        self.assertEqual(n, 100)
        self.assertIsNotNone(self.attempt(ip="10.9.9.9", at=4 * 3700 + 1))
        # a day later it is open again
        self.assertIsNone(self.attempt(ip="10.9.9.9", at=86400 + 4 * 3700 + 10))

    def test_the_address_is_hashed_in_the_table(self):
        self.attempt(ip="203.0.113.77")
        with closing(sqlite3.connect(str(self.db))) as conn:
            dump = str(conn.execute("SELECT * FROM login_attempts").fetchall())
        self.assertNotIn("203.0.113.77", dump)

    def test_signups_and_logins_do_not_spend_each_others_allowance(self):
        for i in range(5):
            self.attempt(ip="203.0.113.5", at=i)
        self.assertIsNone(passwords.check_and_record_attempt(
            [(passwords.SCOPE_IP, "203.0.113.5")], now=self.T0 + 6, db=self.db))


# ---------------------------------------------------------------------------
# The two levels (store, no FastAPI)
# ---------------------------------------------------------------------------

class TheTwoLevels(_Base):
    def level(self, user, now=NOW):
        return access.access_level(users_store.get_user(user.id, db=self.db), now=now)

    def test_a_free_account_is_a_member_and_gets_a_free_thirty_day_token_on_login(self):
        made = self.member()
        self.assertEqual(self.level(made.user), "member")
        kind, ends = access.access_token_end(made.user, now=NOW)
        self.assertEqual((kind, ends), ("free", NOW + timedelta(days=30)))

    def test_a_suspended_free_account_has_no_level_and_no_token(self):
        made = self.member()
        users_store.set_user_status(made.user.id, "suspended", db=self.db)
        user = users_store.get_user(made.user.id, db=self.db)
        self.assertIsNone(access.access_level(user))
        self.assertIsNone(access.access_token_end(user, now=NOW))

    def test_a_free_plan_that_is_not_active_gets_no_session(self):
        user = users_store.create_user("w@example.com", status="waitlisted", plan="free", db=self.db)
        self.assertIsNone(access.access_token_end(user, now=NOW))

    def test_everyone_else_with_a_session_is_paid_exactly_as_before(self):
        invited = users_store.create_user("i@example.com", status="invited", db=self.db)
        tester = testers.grant_tester(email="t@example.com", now=NOW, db=self.db)
        comp = comps.grant_comp(email="c@example.com", reason="friend", now=NOW, db=self.db)
        sub = self.paying_subscriber()
        for who in (invited.id, tester.user_id, comp.user_id, sub.id):
            self.assertEqual(self.level(users_store.get_user(who, db=self.db)), "paid", who)

    def test_a_free_account_with_a_comp_is_paid_and_a_revoke_makes_it_a_member_again(self):
        made = self.member()
        comps.grant_comp(user_id=made.user.id, reason="liked it", now=NOW, db=self.db)
        self.assertEqual(self.level(made.user), "paid")
        comps.revoke_comp(made.user.id, "done", db=self.db)
        self.assertEqual(self.level(made.user), "member")

    def test_a_free_account_inside_a_tester_week_is_paid_and_after_it_a_member(self):
        made = self.member()
        grant = testers.grant_tester(user_id=made.user.id, now=NOW, db=self.db)
        self.assertEqual(self.level(made.user, now=NOW + timedelta(days=3)), "paid")
        self.assertEqual(self.level(made.user, now=NOW + timedelta(days=8)), "member")
        self.assertIsNotNone(grant.token)

    def test_a_free_account_that_subscribes_is_paid_while_paid_through(self):
        made = self.member()
        customers.upsert_customer(made.user.id, "cus_x", db=self.db)
        customers.upsert_subscription(
            made.user.id, "sub_x", "active",
            current_period_end=(datetime.now(timezone.utc) + timedelta(days=20)).isoformat(),
            db=self.db)
        self.assertEqual(self.level(made.user, now=datetime.now(timezone.utc)), "paid")

    def test_a_non_free_plan_returns_before_any_database_read(self):
        user = users_store.User(id=1, email="x@example.com", created_at="", status="active", plan="beta")
        with mock.patch.object(customers, "has_paid_access",
                               side_effect=AssertionError("read the database")):
            self.assertFalse(access.is_free_only(user))

    def test_the_free_source_is_registered_and_fails_closed_if_it_raises(self):
        made = self.member()
        user = users_store.get_user(made.user.id, db=self.db)
        saved = dict(access._SOURCES)
        self.addCleanup(lambda: (access._SOURCES.clear(), access._SOURCES.update(saved)))
        self.assertIn("free", access._SOURCES)

        def broken(u, now):
            raise RuntimeError("boom")
        access.register_access_source("free", broken)
        with mock.patch("sys.stderr"):
            self.assertIsNone(access.access_token_end(user, now=NOW))


# ---------------------------------------------------------------------------
# The REAL app, over ASGI
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class _App(_Base):
    @classmethod
    def setUpClass(cls):
        from api.app import app
        from api import auth
        cls.app, cls.auth = app, auth

    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {"APP_DB_PATH": str(self.db), "APP_ADMIN_TOKEN": ADMIN})
        env.start()
        self.addCleanup(env.stop)

    def call(self, method, path, *, token=None, admin=False, body=None):
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if admin:
            headers["X-Admin-Token"] = ADMIN
        return _asgi(self.app, method, path, headers=headers, body=body)

    def signup(self, email="new@example.com", password=GOOD_PASSWORD, **extra):
        return self.call("POST", "/auth/signup", body=dict({"email": email, "password": password}, **extra))


class TheSignupRoute(_App):
    def test_a_new_visitor_is_signed_in_at_once_with_a_working_free_token(self):
        status, out = self.signup("new@example.com", kennel_name="Back Forty")
        self.assertEqual(status, 200, out)
        self.assertTrue(out["token"])
        self.assertEqual((out["kind"], out["access_active"], out["has_password"]), ("free", True, True))
        user = users_store.get_user_by_email("new@example.com", db=self.db)
        self.assertEqual((user.status, user.plan), ("active", "free"))
        for path in ("/hounds/mine", "/hounds/kennels/mine", "/auth/password", "/billing/status"):
            with self.subTest(path=path):
                self.assertEqual(self.call("GET", path, token=out["token"])[0], 200, path)
        self.assertEqual(self.call("GET", "/auth/password", token=out["token"])[1], {"has_password": True})

    def test_the_session_ends_in_about_thirty_days(self):
        _, out = self.signup()
        ends = datetime.fromisoformat(out["expires_at"])
        self.assertAlmostEqual((ends - datetime.now(timezone.utc)).total_seconds(),
                               30 * 86400, delta=60)

    def test_the_new_member_can_sign_in_with_the_password_and_gets_a_fresh_free_token(self):
        _, first = self.signup("Mixed.Case@Example.com")
        status, out = self.call("POST", "/auth/login",
                                body={"email": "mixed.case@example.com", "password": GOOD_PASSWORD})
        self.assertEqual(status, 200, out)
        self.assertEqual((out["kind"], out["access_active"]), ("free", True))
        self.assertNotEqual(out["token"], first["token"])
        self.assertAlmostEqual((datetime.fromisoformat(out["expires_at"])
                                - datetime.now(timezone.utc)).total_seconds(), 30 * 86400, delta=60)

    def test_the_email_is_lower_cased_and_trimmed_before_it_is_stored(self):
        self.signup("  Loud@Example.COM  ")
        self.assertEqual([u.email for u in users_store.list_users(db=self.db)], ["loud@example.com"])

    def test_a_repeat_email_in_any_case_creates_nothing_and_answers_in_the_same_shape(self):
        _, first = self.signup("dup@example.com")
        before = self.counts()
        status, again = self.signup("DUP@example.com", password="another-long-password-7")
        self.assertEqual(status, 200)
        self.assertEqual(set(again), set(first))
        self.assertEqual(again["message"], first["message"])
        self.assertIsNone(again["token"])
        self.assertEqual(self.counts()["users"], before["users"])
        self.assertEqual(self.counts()["tokens"], before["tokens"])
        self.assertEqual(self.counts()["analytics_events"], before["analytics_events"])
        # the repeat did not change the first person's password
        self.assertEqual(self.call("POST", "/auth/login", body={
            "email": "dup@example.com", "password": GOOD_PASSWORD})[0], 200)
        self.assertEqual(self.call("POST", "/auth/login", body={
            "email": "dup@example.com", "password": "another-long-password-7"})[0], 401)

    def test_an_existing_account_of_another_kind_is_never_touched_by_a_signup(self):
        users_store.create_user("wait@example.com", status="waitlisted", plan="none", db=self.db)
        tester = testers.grant_tester(email="tester@example.com", db=self.db)
        for email in ("wait@example.com", "tester@example.com"):
            status, out = self.signup(email)
            self.assertEqual((status, out["token"]), (200, None), email)
        self.assertEqual(users_store.get_user_by_email("wait@example.com", db=self.db).status, "waitlisted")
        self.assertEqual(users_store.get_user_by_email("wait@example.com", db=self.db).plan, "none")
        self.assertFalse(passwords.has_password(
            users_store.get_user_by_email("wait@example.com", db=self.db).id, db=self.db))
        self.assertEqual(self.call("GET", "/card", token=tester.token)[0] in (401, 402, 403), False)

    def test_neither_answer_carries_the_email_the_password_or_a_hash(self):
        _, a = self.signup("carry@example.com")
        _, b = self.signup("carry@example.com")
        for out in (a, b):
            blob = json.dumps(out)
            for secret in ("carry@example.com", GOOD_PASSWORD, "scrypt"):
                self.assertNotIn(secret, blob)

    def test_bad_input_is_a_plain_400_that_never_echoes_the_password(self):
        secret_pw = "short"
        cases = [({"email": "not-an-email", "password": GOOD_PASSWORD}, "invalid_email"),
                 ({"email": "", "password": GOOD_PASSWORD}, "invalid_email"),
                 ({"email": "a@b", "password": GOOD_PASSWORD}, "invalid_email"),
                 ({"email": "x" * 300 + "@example.com", "password": GOOD_PASSWORD}, "invalid_email"),
                 ({"email": 5, "password": GOOD_PASSWORD}, "invalid_email"),
                 ({"email": "ok@example.com", "password": secret_pw}, "password_rejected"),
                 ({"email": "ok@example.com", "password": "password1234"}, "password_rejected"),
                 ({"email": "ok@example.com", "password": "ok@example.com"}, "password_rejected"),
                 ({"email": "ok@example.com", "password": None}, "password_rejected"),
                 ({"email": "ok@example.com", "password": ["a"]}, "password_rejected"),
                 ({"email": "ok@example.com", "password": GOOD_PASSWORD, "kennel_name": "x" * 41},
                  "kennel_name_rejected")]
        for body, code in cases:
            with self.subTest(code=code, body=str(body)[:60]):
                status, out = self.call("POST", "/auth/signup", body=body)
                self.assertEqual((status, out["detail"]["error"]), (400, code))
                self.assertNotIn(secret_pw + '"', json.dumps(out))
        self.assertEqual(self.counts()["users"], 0)
        self.assertEqual(self.counts()["login_attempts"], 0, "a refused-early request is not counted")

    def test_the_password_rules_are_the_existing_modules_not_a_copy(self):
        source = inspect.getsource(__import__("api.free_signup", fromlist=["x"]))
        self.assertIn("passwords.check_password_rules", source)
        self.assertNotIn("MIN_PASSWORD_LENGTH =", source)

    def test_the_honeypot_creates_nothing_costs_no_allowance_and_answers_like_a_repeat(self):
        _, repeat_shape = self.signup("seed@example.com")
        users_before = self.counts()["users"]
        for _ in range(8):
            status, out = self.signup("bot@example.com", website="http://spam.example")
            self.assertEqual((status, out["token"]), (200, None))
            self.assertEqual(set(out), set(repeat_shape))
        self.assertEqual(self.counts()["users"], users_before)
        self.assertIsNone(users_store.get_user_by_email("bot@example.com", db=self.db))
        # eight honeypot hits spent none of the five: a real signup still works
        self.assertEqual(self.signup("real@example.com")[0], 200)

    def test_an_empty_honeypot_is_not_a_honeypot(self):
        status, out = self.signup("quiet@example.com", website="")
        self.assertEqual((status, bool(out["token"])), (200, True))

    def test_six_signups_from_one_address_in_an_hour_are_a_429_with_retry_after(self):
        for i in range(5):
            self.assertEqual(self.signup(f"u{i}@example.com")[0], 200, i)
        status, out = self.signup("u9@example.com")
        self.assertEqual((status, out["detail"]["error"]), (429, "rate_limited"))
        self.assertGreater(out["detail"]["retry_after"], 3000)
        self.assertIsNone(users_store.get_user_by_email("u9@example.com", db=self.db))

    def test_a_repeat_email_counts_against_the_limit_so_probing_is_bounded(self):
        for _ in range(5):
            self.signup("same@example.com")
        self.assertEqual(self.signup("same@example.com")[0], 429)

    def test_the_global_daily_ceiling_refuses_everyone(self):
        now = datetime.now(timezone.utc).timestamp()
        with passwords._connect(self.db) as conn:
            key = passwords._key_hash(free_members.SCOPE_SIGNUP_ALL, "all")
            conn.executemany("INSERT INTO login_attempts (scope, key_hash, at) VALUES (?, ?, ?)",
                             [(free_members.SCOPE_SIGNUP_ALL, key, now - 4000 - i) for i in range(100)])
        status, out = self.signup("late@example.com")
        self.assertEqual((status, out["detail"]["error"]), (429, "rate_limited"))

    def test_a_limiter_that_cannot_be_read_refuses_the_signup(self):
        with mock.patch.object(free_members, "check_and_record_signup", side_effect=sqlite3.Error("locked")):
            with mock.patch("sys.stderr"):
                status, out = self.signup("x@example.com")
        self.assertEqual((status, out["detail"]["error"]), (503, "signup_unavailable"))
        self.assertIsNone(users_store.get_user_by_email("x@example.com", db=self.db))

    def test_a_failed_create_is_a_503_and_leaves_nothing(self):
        with mock.patch.object(free_members, "create_free_member", side_effect=sqlite3.Error("disk")):
            with mock.patch("sys.stderr"):
                status, out = self.signup("x@example.com")
        self.assertEqual((status, out["detail"]["error"]), (503, "signup_unavailable"))

    def test_the_event_is_recorded_once_with_no_email(self):
        self.signup("evt@example.com", kennel_name="Back Forty")
        with closing(sqlite3.connect(str(self.db))) as conn:
            rows = conn.execute("SELECT kind, properties_json FROM analytics_events").fetchall()
        self.assertEqual([r[0] for r in rows], ["signup_free_created"])
        self.assertEqual(json.loads(rows[0][1]), {"has_kennel_name": True})
        self.assertNotIn("evt@example.com", json.dumps(rows))
        self.assertNotIn("Back Forty", json.dumps(rows))

    def test_the_kennel_name_reaches_a_registered_store_and_is_ignored_without_one(self):
        self.assertEqual(self.signup("a@example.com", kennel_name="Back Forty")[0], 200)
        seen = []
        free_members.register_kennel_name_store(lambda uid, name: seen.append(name))
        self.assertEqual(self.signup("b@example.com", kennel_name="  Front   Porch ")[0], 200)
        self.assertEqual(self.signup("c@example.com")[0], 200)
        self.assertEqual(seen, ["Front Porch"])

    def test_the_default_store_is_the_products_kennel_name_and_a_refused_name_is_just_not_kept(self):
        from src.hounds import member_profile
        free_members.register_kennel_name_store(free_members._member_profile_store)
        self.assertEqual(self.signup("named@example.com", kennel_name="Back Forty")[0], 200)
        user = users_store.get_user_by_email("named@example.com", db=self.db)
        self.assertEqual(member_profile.get(user.id)["kennel_name"], "Back Forty")
        # taken, too short, a claim: the signup still works, the name is not kept
        for i, name in enumerate(("Back Forty", "a", "Guaranteed Winners")):
            status, out = self.signup(f"other{i}@example.com", kennel_name=name)
            self.assertEqual((status, bool(out["token"])), (200, True), name)
            other = users_store.get_user_by_email(f"other{i}@example.com", db=self.db)
            self.assertIsNone(member_profile.get(other.id)["kennel_name"], name)

    def test_no_cookie_and_a_form_post_is_refused(self):
        raw = [(b"content-type", b"application/x-www-form-urlencoded")]
        import asyncio
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
                 "scheme": "http", "path": "/auth/signup", "raw_path": b"/auth/signup",
                 "query_string": b"", "headers": raw, "client": ("127.0.0.1", 1), "server": ("t", 80)}
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"email=a%40example.com&password=x", "more_body": False}

        async def send(message):
            sent.append(message)

        asyncio.new_event_loop().run_until_complete(self.app(scope, receive, send))
        self.assertEqual(sent[0]["status"], 422)
        self.assertNotIn(b"set-cookie", [k for k, _ in sent[0]["headers"]])
        self.assertIsNone(users_store.get_user_by_email("a@example.com", db=self.db))

    def test_the_admin_people_list_shows_plan_free(self):
        self.signup("listed@example.com")
        status, out = self.call("GET", "/admin/users", admin=True)
        self.assertEqual(status, 200)
        mine = [u for u in out["users"] if u["email"] == "listed@example.com"]
        self.assertEqual((mine[0]["plan"], mine[0]["status"], mine[0]["comp"], mine[0]["tester"]),
                         ("free", "active", False, False))

    def test_the_old_waitlist_signup_is_untouched(self):
        status, out = self.call("POST", "/signup", body={"email": "waitlist@example.com"})
        self.assertEqual(status, 200)
        self.assertEqual(out["status"], "waitlisted")
        self.assertEqual(users_store.get_user_by_email("waitlist@example.com", db=self.db).plan, "none")


# ---------------------------------------------------------------------------
# The access split, through the real routes
# ---------------------------------------------------------------------------

def _fill(path):
    return re.sub(r"\{[^}]*\}", "x", path)


class TheAccessSplit(_App):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.routes = list(_walk(cls.app.routes))

    def free_token(self):
        status, out = self.signup("split@example.com")
        self.assertEqual(status, 200, out)
        return out["token"]

    def paid_routes(self):
        found = {}
        for route, deps in self.routes:
            if self.auth.require_paid_access in deps:
                for method in sorted(m for m in route.methods if m != "HEAD"):
                    found[(method, route.path)] = route
        return found

    def test_the_paid_board_is_a_substantial_known_set(self):
        paths = {path for _, path in self.paid_routes()}
        self.assertGreater(len(paths), 40)
        for must in ("/today", "/games/{date}", "/card", "/props", "/odds/{date}", "/betcheck",
                     "/ufc/fight-night", "/daily", "/data/v1/status", "/opportunities", "/live"):
            self.assertIn(must, paths)

    def test_every_paid_route_refuses_a_free_account_with_a_403(self):
        token = self.free_token()
        refused = []
        for (method, path), _ in sorted(self.paid_routes().items()):
            status, body = self.call(method, _fill(path), token=token,
                                     body={} if method in ("POST", "PUT", "PATCH") else None)
            refused.append((method, path, status))
            self.assertEqual(status, 403, (method, path, body))
            # the data service wraps every refusal in its own {"error": {"code", "message"}} envelope
            code = (body.get("detail") or {}).get("error") if "detail" in body else body["error"]["code"]
            self.assertEqual(code, "paid_access_required", (method, path, body))
        self.assertGreater(len(refused), 40)

    def test_every_paid_route_still_refuses_no_token_with_a_401(self):
        for (method, path), _ in sorted(self.paid_routes().items()):
            status, _ = self.call(method, _fill(path), body={} if method in ("POST", "PUT") else None)
            self.assertEqual(status, 401, (method, path))

    def test_the_digest_is_the_board_in_another_shape_and_is_refused_too(self):
        token = self.free_token()
        status, body = self.call("GET", "/digest", token=token)
        self.assertEqual((status, body["detail"]["error"]), (403, "paid_access_required"))
        self.assertEqual(self.call("GET", "/digest")[0], 401)

    def test_a_free_account_passes_the_personal_pages_that_never_were_paid(self):
        token = self.free_token()
        for path in ("/billing/status", "/my-bets", "/onboarding", "/hounds/mine"):
            self.assertEqual(self.call("GET", path, token=token)[0], 200, path)

    def test_the_paid_gate_is_a_403_for_a_free_account_and_a_pass_for_everyone_who_had_access(self):
        free = users_store.create_user("f@example.com", status="active", plan="free", db=self.db)
        invited = users_store.create_user("i@example.com", status="invited", plan="none", db=self.db)
        with self.assertRaises(HTTPException) as ctx:
            self.auth.require_paid_access(current_user=free)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(self.auth.require_paid_access(current_user=invited).id, invited.id)

    def test_testers_comps_subscribers_and_invited_beta_users_still_reach_the_paid_board(self):
        tester = testers.grant_tester(email="t@example.com", db=self.db)
        comp = comps.grant_comp(email="c@example.com", reason="friend", db=self.db)
        sub = self.paying_subscriber()
        invited = users_store.create_user("i@example.com", status="invited", plan="none", db=self.db)
        invited_token = users_store.issue_invite_token(invited.id, db=self.db)
        sub_token = users_store.issue_invite_token(sub.id, db=self.db)
        for name, token in (("tester", tester.token), ("comp", comp.token),
                            ("subscriber", sub_token), ("invited", invited_token)):
            with self.subTest(who=name):
                status, _ = self.call("GET", "/card", token=token)
                self.assertNotIn(status, (401, 402, 403))

    def test_an_expired_tester_is_still_the_expired_tester_401_not_a_free_member_403(self):
        old = testers.grant_tester(email="old@example.com", now=NOW - timedelta(days=20), db=self.db)
        status, body = self.call("GET", "/card", token=old.token)
        self.assertEqual((status, body["detail"]["error"]), (401, "tester_access_expired"))

    def test_a_free_account_that_is_comped_gets_the_board_and_loses_it_on_revoke(self):
        _, out = self.signup("upgrade@example.com")
        token = out["token"]
        user = users_store.get_user_by_email("upgrade@example.com", db=self.db)
        self.assertEqual(self.call("GET", "/card", token=token)[0], 403)
        grant = comps.grant_comp(user_id=user.id, reason="friend", db=self.db)
        status, _ = self.call("GET", "/card", token=grant.token)
        self.assertNotIn(status, (401, 402, 403))
        comps.revoke_comp(user.id, "done", db=self.db)
        # A comp grant revokes every older token AND clears the password (users.clear_password_on:
        # a re-issue says the old credential holder is not trusted), and a revoke does the same, so
        # the person is back at the support door. After support re-issues a token the account is a
        # member again, not a paid one.
        again = users_store.issue_invite_token(user.id, db=self.db)
        self.assertEqual(self.call("GET", "/card", token=again)[0], 403)
        self.assertEqual(self.call("GET", "/hounds/mine", token=again)[0], 200)

    def test_a_free_account_inside_a_tester_week_gets_the_board(self):
        _, out = self.signup("week@example.com")
        user = users_store.get_user_by_email("week@example.com", db=self.db)
        grant = testers.grant_tester(user_id=user.id, db=self.db)
        status, _ = self.call("GET", "/card", token=grant.token)
        self.assertNotIn(status, (401, 402, 403))

    # -- the dog surface needs a member and nothing more ---------------------------------

    # The routes that act for an ACCOUNT (build, edit, backtest, record a ticket, give feedback,
    # suggest a change, dress a dog, read my kennel): each needs a signed-in member.
    MEMBER_ROUTES = (("POST", "/hounds"), ("GET", "/hounds/mine"), ("GET", "/hounds/kennels/mine"),
                     ("POST", "/hounds/x/version"), ("POST", "/hounds/x/diff"), ("POST", "/hounds/drill"),
                     ("PUT", "/hounds/x/look"), ("POST", "/hounds/x/manual"),
                     ("POST", "/hounds/x/feedback"), ("POST", "/hounds/x/suggest"),
                     ("GET", "/hounds/camp/mine"))
    # Fire now, Ask, fan tips and the locker-room reads are OPEN to a visitor by design (a signed-in
    # token only personalises them), so a free member has them a fortiori. They must never be
    # held behind the paid gate.
    OPEN_DOG_ROUTES = (("POST", "/hounds/x/fire"), ("GET", "/hounds/x/ask"), ("POST", "/hounds/x/ask"),
                       ("POST", "/hounds/x/tips"), ("GET", "/hounds/looks"), ("GET", "/hounds/x/look"),
                       ("GET", "/hounds/x/kit"), ("GET", "/hounds/x/manual"))

    def test_every_member_route_refuses_a_visitor_with_no_token(self):
        for method, path in self.MEMBER_ROUTES:
            with self.subTest(route=f"{method} {path}"):
                status, _ = self.call(method, path, body={} if method in ("POST", "PUT") else None)
                self.assertEqual(status, 401)

    def test_a_free_member_gets_past_the_gate_on_every_dog_route(self):
        token = self.free_token()
        for method, path in self.MEMBER_ROUTES + self.OPEN_DOG_ROUTES:
            with self.subTest(route=f"{method} {path}"):
                status, body = self.call(method, path, token=token,
                                         body={} if method in ("POST", "PUT") else None)
                self.assertNotIn(status, (401, 402, 403), (method, path, body))

    def test_the_dog_routes_that_need_a_member_are_not_behind_the_paid_gate(self):
        guarded = {path for (_, path) in self.paid_routes()}
        for _, path in self.MEMBER_ROUTES + self.OPEN_DOG_ROUTES:
            self.assertFalse(any(path.split("/")[1:2] == ["hounds"] and g == path for g in guarded), path)
        self.assertFalse([p for p in guarded if p.startswith("/hounds")])

    def test_creating_a_dog_asks_for_a_member_and_a_lapsed_subscriber_is_still_a_402(self):
        free = users_store.create_user("f@example.com", status="active", plan="free", db=self.db)
        self.assertEqual(self.auth.require_member_access(current_user=free).id, free.id)
        lapsed = users_store.create_user("l@example.com", status="active", plan="beta", db=self.db)
        customers.upsert_customer(lapsed.id, "cus_l", db=self.db)
        customers.upsert_subscription(
            lapsed.id, "sub_l", "canceled",
            current_period_end=(datetime.now(timezone.utc) - timedelta(days=30)).isoformat(), db=self.db)
        with self.assertRaises(HTTPException) as ctx:
            self.auth.require_member_access(current_user=lapsed)
        self.assertEqual(ctx.exception.status_code, 402)

    def test_the_only_two_places_that_read_the_level_are_the_gates(self):
        pattern = re.compile(r"is_free_only|access_level|LEVEL_MEMBER")
        allowed = {"auth.py"}
        offenders = sorted(p.name for p in (ROOT / "api").glob("*.py")
                           if p.name not in allowed and pattern.search(p.read_text(encoding="utf-8")))
        self.assertEqual(offenders, [], "an api module decided the member/paid split itself")


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class AFreeMemberReallyBuildsADog(unittest.TestCase):
    """The existing dog-API fixtures (tests/test_hounds_user_api.py), with a free user:
    creating a dog is the one dog route that used to sit behind the paid gate. Fire,
    Ask, the locker room, edit and the backtest drill are covered by the route walk
    above (a free token gets past every gate on every one of them)."""

    def test_a_free_member_creates_a_dog_and_sees_it_in_their_kennel(self):
        from tests.test_hounds_user_api import ApiCase
        from src.hounds import user_store

        class Flow(ApiCase):
            def runTest(self):
                pass
        case = Flow()
        case.setUp()
        try:
            from api import auth
            free = users_store.create_user("builder@example.com", status="active", plan="free", db=case.db)
            self.assertEqual(auth.require_member_access(current_user=free).id, free.id)
            case.create(user=free, name="Free Dog")
            mine = case.api.my_hounds(current_user=free, _rl=None)
            self.assertEqual(len(mine["hounds"]), 1)
            self.assertEqual(len(user_store.list_for_owner(free.id)), 1)
            self.assertEqual(user_store.list_for_owner(case.user.id), [])
        finally:
            case.tearDown()


if __name__ == "__main__":
    unittest.main()
