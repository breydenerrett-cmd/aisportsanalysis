"""Early-access testers: the first 20, seven days each, no card, chosen by hand.

Owner policy (2026-10-02): the owner grants access from the admin page; the cap
is 20 DISTINCT users EVER granted (expiry does not give a slot back); a tester
is not a subscriber; the access is temporary. These tests pin the parts that
are easy to get quietly wrong:

  * the cap holds at 20, is not reduced by expiry, survives a restart, and
    holds when two grants race for the last slot (BEGIN IMMEDIATE);
  * a refusal writes NOTHING (no half-created user, no slot burned);
  * a tester's token works like an invite token on the paid routes until it
    expires -- day 6 in, day 8 out -- with the clock injected, never slept;
  * an extension adds a token and a reason, revokes nothing, uses no slot;
  * the raw token exists in exactly one response and in no event or repr.

The store half needs no FastAPI (src/ is stdlib only). The API half calls the
route functions directly, as tests/test_api_admin.py does, and the access half
drives the REAL app over ASGI, so it is skipped where FastAPI is absent (the
Linux CI image).
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

try:
    from fastapi import HTTPException
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.appstate import activation
from src.appstate import customers
from src.appstate import events
from src.appstate import testers
from src.appstate import users as users_store

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "app.db"

    def grant(self, i, *, now=NOW):
        return testers.grant_tester(email=f"tester{i}@example.com", now=now, db=self.db)

    def grant_many(self, n, *, now=NOW):
        return [self.grant(i, now=now) for i in range(n)]

    def table_counts(self):
        """Row counts straight from the file, by a connection that shares no
        code with the module under test. A table that was never created has
        0 rows: a refusal that fires before anything is written may be the
        first call ever made against a fresh database."""
        with closing(sqlite3.connect(str(self.db))) as conn:
            have = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            return {t: (conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                        if t in have else 0)
                    for t in ("users", "tokens", "testers", "tester_extensions")}


class TheTwoNumbersLiveInOnePlace(unittest.TestCase):
    def test_the_limit_and_the_window_are_the_owners_numbers(self):
        self.assertEqual(testers.TESTER_LIMIT, 20)
        self.assertEqual(testers.TESTER_ACCESS_TTL, timedelta(days=7))


class GrantingAccess(_Base):
    def test_a_new_email_becomes_an_invited_user_with_a_seven_day_token(self):
        grant = self.grant(1)
        user = users_store.get_user_by_email("tester1@example.com", db=self.db)
        self.assertEqual((user.status, user.plan), ("invited", "none"))
        self.assertEqual(grant.user_id, user.id)
        self.assertEqual(grant.testers_granted, 1)
        self.assertEqual(grant.expires_at, (NOW + timedelta(days=7)).isoformat())
        self.assertEqual(users_store.authenticate(grant.token, db=self.db, now=NOW).id, user.id)

    def test_the_email_is_normalised_and_the_same_person_is_found_again(self):
        first = testers.grant_tester(email="  Mixed.Case@Example.COM ", now=NOW, db=self.db)
        self.assertEqual(first.email, "mixed.case@example.com")
        with self.assertRaises(testers.TesterRefused) as ctx:
            testers.grant_tester(email="MIXED.case@example.com", now=NOW, db=self.db)
        self.assertEqual(ctx.exception.code, "already_a_tester")

    def test_a_waitlisted_user_becomes_invited_and_keeps_their_row(self):
        waiting = users_store.create_user("wait@example.com", status="waitlisted", db=self.db)
        grant = testers.grant_tester(user_id=waiting.id, now=NOW, db=self.db)
        self.assertEqual(grant.user_id, waiting.id)
        self.assertEqual(users_store.get_user(waiting.id, db=self.db).status, "invited")
        self.assertEqual(self.table_counts()["users"], 1)

    def test_an_invited_or_active_user_keeps_their_status_and_plan(self):
        for status, plan in (("invited", "none"), ("active", "beta")):
            with self.subTest(status=status):
                user = users_store.create_user(f"{status}@example.com", status=status,
                                               plan=plan, db=self.db)
                testers.grant_tester(user_id=user.id, now=NOW, db=self.db)
                kept = users_store.get_user(user.id, db=self.db)
                self.assertEqual((kept.status, kept.plan), (status, plan))

    def test_exactly_one_of_email_or_user_id(self):
        for kwargs in ({}, {"email": "a@example.com", "user_id": 1}):
            with self.assertRaises(ValueError):
                testers.grant_tester(db=self.db, **kwargs)

    def test_a_bad_email_and_an_unknown_user_id_are_refused_with_nothing_written(self):
        for kwargs, code, status in (({"email": "not-an-email"}, "invalid_email", 400),
                                     ({"email": ""}, "invalid_email", 400),
                                     ({"user_id": 4242}, "no_such_user", 404)):
            with self.assertRaises(testers.TesterRefused) as ctx:
                testers.grant_tester(now=NOW, db=self.db, **kwargs)
            self.assertEqual((ctx.exception.code, ctx.exception.status), (code, status))
        self.assertEqual(sum(self.table_counts().values()), 0)

    def test_the_grant_object_never_prints_the_token(self):
        grant = self.grant(1)
        self.assertNotIn(grant.token, repr(grant))
        self.assertNotIn(grant.token, str(grant))


class WhoIsRefused(_Base):
    def test_a_suspended_user_is_refused_and_stays_suspended(self):
        user = users_store.create_user("susp@example.com", status="suspended", db=self.db)
        with self.assertRaises(testers.TesterRefused) as ctx:
            testers.grant_tester(user_id=user.id, now=NOW, db=self.db)
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("user_suspended", 409))
        self.assertEqual(self.table_counts()["testers"], 0)
        self.assertEqual(self.table_counts()["tokens"], 0)

    def test_a_pending_payment_user_is_refused_with_a_message_about_the_open_checkout(self):
        user = users_store.create_user("paying@example.com", status="pending_payment",
                                       db=self.db)
        with self.assertRaises(testers.TesterRefused) as ctx:
            testers.grant_tester(email="paying@example.com", now=NOW, db=self.db)
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("checkout_open", 409))
        self.assertIn("checkout is open", ctx.exception.message)
        self.assertEqual(users_store.get_user(user.id, db=self.db).status, "pending_payment")
        self.assertEqual(self.table_counts()["testers"], 0)

    def test_anyone_with_a_subscription_record_is_refused_whatever_its_status(self):
        for i, status in enumerate(("active", "trialing", "canceled")):
            with self.subTest(status=status):
                user = users_store.create_user(f"cust{i}@example.com", status="active",
                                               plan="beta", db=self.db)
                customers.upsert_customer(user.id, f"cus_{i}", db=self.db)
                customers.upsert_subscription(user.id, f"sub_{i}", status, db=self.db)
                for kwargs in ({"user_id": user.id}, {"email": user.email}):
                    with self.assertRaises(testers.TesterRefused) as ctx:
                        testers.grant_tester(now=NOW, db=self.db, **kwargs)
                    self.assertEqual((ctx.exception.code, ctx.exception.status),
                                     ("has_subscription", 409))
        self.assertEqual(self.table_counts()["testers"], 0)
        self.assertEqual(self.table_counts()["tokens"], 0)

    def test_a_second_grant_to_the_same_person_is_refused_and_takes_no_slot(self):
        first = self.grant(1)
        with self.assertRaises(testers.TesterRefused) as ctx:
            testers.grant_tester(user_id=first.user_id, now=NOW, db=self.db)
        self.assertEqual(ctx.exception.code, "already_a_tester")
        self.assertIn("Extend", ctx.exception.message)
        self.assertEqual(testers.count_granted(db=self.db), 1)
        self.assertEqual(self.table_counts()["tokens"], 1)


class TheCapOfTwenty(_Base):
    def test_twenty_are_granted_and_the_twenty_first_is_refused_with_nothing_written(self):
        self.grant_many(testers.TESTER_LIMIT)
        before = self.table_counts()
        with self.assertRaises(testers.TesterRefused) as ctx:
            testers.grant_tester(email="late@example.com", now=NOW, db=self.db)
        refusal = ctx.exception
        self.assertEqual((refusal.code, refusal.status), ("tester_limit_reached", 409))
        self.assertEqual(refusal.extra, {"testers_granted": 20, "testers_limit": 20})
        self.assertEqual(self.table_counts(), before, "a refused grant wrote something")
        self.assertIsNone(users_store.get_user_by_email("late@example.com", db=self.db),
                          "the refused email must not become a user")

    def test_the_cap_also_refuses_a_waitlisted_user_and_leaves_them_waitlisted(self):
        self.grant_many(testers.TESTER_LIMIT)
        waiting = users_store.create_user("wait@example.com", status="waitlisted", db=self.db)
        with self.assertRaises(testers.TesterRefused) as ctx:
            testers.grant_tester(user_id=waiting.id, now=NOW, db=self.db)
        self.assertEqual(ctx.exception.code, "tester_limit_reached")
        self.assertEqual(users_store.get_user(waiting.id, db=self.db).status, "waitlisted")

    def test_expiry_never_gives_a_slot_back(self):
        long_ago = NOW - timedelta(days=60)
        granted = self.grant_many(testers.TESTER_LIMIT, now=long_ago)
        for g in granted:
            self.assertIsNone(users_store.authenticate(g.token, db=self.db, now=NOW),
                              "every token should have expired by now")
        self.assertEqual(testers.count_granted(db=self.db), 20)
        with self.assertRaises(testers.TesterRefused) as ctx:
            testers.grant_tester(email="late@example.com", now=NOW, db=self.db)
        self.assertEqual(ctx.exception.code, "tester_limit_reached")

    def test_the_count_is_people_not_tokens(self):
        first = self.grant(1)
        users_store.issue_invite_token(first.user_id, db=self.db)
        users_store.issue_invite_token(first.user_id, db=self.db)
        testers.extend_tester(first.user_id, "reported a bug", now=NOW, db=self.db)
        self.assertEqual(testers.count_granted(db=self.db), 1)
        self.assertEqual(testers.list_testers(db=self.db)["remaining"], 19)

    def test_the_count_survives_a_restart(self):
        """A restart is a new process opening the same file: nothing but the
        database holds the count. Read it with a connection that shares no code
        with the module under test, then through the module again."""
        self.grant_many(7)
        with closing(sqlite3.connect(str(self.db))) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM testers").fetchone()[0], 7)
        self.assertEqual(testers.count_granted(db=self.db), 7)
        listing = testers.list_testers(db=self.db)
        self.assertEqual((listing["granted"], listing["limit"], listing["remaining"]),
                         (7, 20, 13))

    def test_two_grants_racing_for_the_last_slot_give_exactly_one_winner(self):
        self.grant_many(testers.TESTER_LIMIT - 1)
        self._race(2, expect_winners=1)
        self.assertEqual(testers.count_granted(db=self.db), 20)

    def test_a_crowd_racing_for_three_slots_gets_exactly_three(self):
        self.grant_many(testers.TESTER_LIMIT - 3)
        self._race(8, expect_winners=3)
        self.assertEqual(testers.count_granted(db=self.db), 20)
        self.assertEqual(self.table_counts()["testers"], 20)
        self.assertEqual(self.table_counts()["tokens"], 20)

    def _race(self, n, *, expect_winners):
        outcomes = []
        gate = threading.Barrier(n)

        def attempt(i):
            gate.wait()
            try:
                testers.grant_tester(email=f"racer{i}@example.com", now=NOW, db=self.db)
                outcomes.append("granted")
            except testers.TesterRefused as exc:
                outcomes.append(exc.code)
            except Exception as exc:  # noqa: BLE001 -- a lock error is a failure
                outcomes.append(f"error: {exc!r}")

        threads = [threading.Thread(target=attempt, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        self.assertEqual(sorted(outcomes),
                         sorted(["granted"] * expect_winners
                                + ["tester_limit_reached"] * (n - expect_winners)), outcomes)


class TheAccessWindow(_Base):
    def test_the_token_works_on_day_six_and_not_on_day_eight(self):
        grant = self.grant(1)
        day = lambda n: users_store.authenticate(
            grant.token, db=self.db, now=NOW + timedelta(days=n))
        self.assertIsNotNone(day(0))
        self.assertIsNotNone(day(6))
        self.assertIsNotNone(users_store.authenticate(
            grant.token, db=self.db, now=NOW + timedelta(days=7, seconds=-1)))
        self.assertIsNone(users_store.authenticate(
            grant.token, db=self.db, now=NOW + timedelta(days=7)))
        self.assertIsNone(day(8))

    def test_a_token_is_a_plain_invite_token_row_hashed_at_rest(self):
        grant = self.grant(1)
        with closing(sqlite3.connect(str(self.db))) as conn:
            hashes = [r[0] for r in conn.execute("SELECT token_hash FROM tokens")]
            dump = "\n".join(str(r) for t in ("users", "tokens", "testers")
                             for r in conn.execute(f"SELECT * FROM {t}"))
        self.assertEqual(hashes, [users_store._hash_token(grant.token)])
        self.assertNotIn(grant.token, dump)


class Extending(_Base):
    def test_an_extension_adds_a_fresh_week_and_leaves_the_old_token_alone(self):
        first = self.grant(1)
        later = NOW + timedelta(days=5)
        ext = testers.extend_tester(first.user_id, "  filed three specific bugs  ",
                                    now=later, db=self.db)
        self.assertNotEqual(ext.token, first.token)
        self.assertEqual(ext.expires_at, (later + timedelta(days=7)).isoformat())
        self.assertEqual(ext.extension_number, 1)
        at = lambda tok, n: users_store.authenticate(tok, db=self.db, now=NOW + timedelta(days=n))
        self.assertIsNotNone(at(first.token, 6), "the old token keeps its own expiry")
        self.assertIsNone(at(first.token, 8), "and is not lengthened by the extension")
        self.assertIsNotNone(at(ext.token, 11))
        self.assertIsNone(at(ext.token, 13))

    def test_it_uses_no_slot_and_records_the_reason_and_the_new_expiry(self):
        first = self.grant(1)
        later = NOW + timedelta(days=5)
        testers.extend_tester(first.user_id, "filed three specific bugs", now=later, db=self.db)
        testers.extend_tester(first.user_id, "sent a screen recording", now=later, db=self.db)
        listing = testers.list_testers(db=self.db)
        self.assertEqual(listing["granted"], 1)
        row = listing["testers"][0]
        self.assertEqual([e["reason"] for e in row["extensions"]],
                         ["filed three specific bugs", "sent a screen recording"])
        self.assertEqual(row["expires_at"], (later + timedelta(days=7)).isoformat())
        self.assertEqual(row["granted_at"], NOW.isoformat())

    def test_no_token_is_ever_revoked_by_an_extension(self):
        first = self.grant(1)
        testers.extend_tester(first.user_id, "reason", now=NOW, db=self.db)
        with closing(sqlite3.connect(str(self.db))) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM tokens WHERE revoked_at IS NOT NULL")
                .fetchone()[0], 0)

    def test_it_is_refused_for_a_non_tester_a_stranger_and_a_missing_reason(self):
        plain = users_store.create_user("plain@example.com", status="invited", db=self.db)
        tester = self.grant(1)
        cases = (
            (plain.id, "x", "not_a_tester", 409),
            (4242, "x", "no_such_user", 404),
            (tester.user_id, "", "reason_required", 400),
            (tester.user_id, "   ", "reason_required", 400),
            (tester.user_id, "x" * (testers.MAX_REASON_LENGTH + 1), "reason_too_long", 400),
        )
        before = self.table_counts()
        for user_id, reason, code, status in cases:
            with self.assertRaises(testers.TesterRefused) as ctx:
                testers.extend_tester(user_id, reason, now=NOW, db=self.db)
            self.assertEqual((ctx.exception.code, ctx.exception.status), (code, status), code)
        self.assertEqual(self.table_counts(), before, "a refused extension wrote something")

    def test_a_suspended_tester_is_not_extended(self):
        tester = self.grant(1)
        users_store.set_user_status(tester.user_id, "suspended", db=self.db)
        with self.assertRaises(testers.TesterRefused) as ctx:
            testers.extend_tester(tester.user_id, "reason", now=NOW, db=self.db)
        self.assertEqual(ctx.exception.code, "user_suspended")


class TheListing(_Base):
    def test_signing_in_is_recorded_but_is_not_activation(self):
        """first_used_at is a sign-in. `activated` now means a value action
        (src/appstate/activation.py), so redeeming a token alone is not it."""
        a, b = self.grant(1), self.grant(2)
        users_store.mark_token_first_used(a.token, at="2026-10-06T08:00:00+00:00", db=self.db)
        rows = {r["user_id"]: r for r in testers.list_testers(db=self.db)["testers"]}
        self.assertEqual(rows[a.user_id]["first_used_at"], "2026-10-06T08:00:00+00:00")
        self.assertEqual(rows[a.user_id]["first_signin_at"], "2026-10-06T08:00:00+00:00")
        self.assertFalse(rows[a.user_id]["activated"])
        self.assertIsNone(rows[a.user_id]["activated_at"])
        self.assertIsNone(rows[b.user_id]["first_used_at"])
        self.assertFalse(rows[b.user_id]["activated"])

    def test_activated_means_a_value_action_not_a_token_use(self):
        a, b = self.grant(1), self.grant(2)
        activation.record_value_action(a.user_id, "card", route="card", date="2026-10-06",
                                       at="2026-10-06T09:00:00+00:00", db=self.db)
        rows = {r["user_id"]: r for r in testers.list_testers(db=self.db)["testers"]}
        self.assertTrue(rows[a.user_id]["activated"])
        self.assertEqual(rows[a.user_id]["activated_at"], "2026-10-06T09:00:00+00:00")
        self.assertIsNone(rows[a.user_id]["first_used_at"],
                          "no sign-in was recorded, and none is implied")
        self.assertFalse(rows[b.user_id]["activated"])

    def test_the_listing_carries_the_counts_and_never_a_token(self):
        grant = self.grant(1)
        listing = testers.list_testers(db=self.db)
        self.assertEqual((listing["granted"], listing["limit"], listing["remaining"]),
                         (1, 20, 19))
        self.assertEqual(listing["ttl_days"], 7)
        self.assertNotIn(grant.token, json.dumps(listing))
        self.assertEqual(set(listing["testers"][0]),
                         {"user_id", "email", "status", "granted_at", "expires_at",
                          "first_used_at", "extensions",
                          "account_created_at", "tester_granted_at", "first_signin_at",
                          "activated", "activated_at", "hours_signup_to_activation",
                          "last_active_at", "active_days", "returning", "features"})

    def test_an_empty_database_lists_nothing_and_reports_twenty_remaining(self):
        listing = testers.list_testers(db=self.db)
        self.assertEqual((listing["testers"], listing["granted"], listing["remaining"]),
                         ([], 0, 20))


# ---------------------------------------------------------------------------
# The admin API
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheAdminRoutes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "app.db"
        self.events_db = Path(self._tmp.name) / "events.db"
        for patcher in (mock.patch.object(users_store, "db_path", lambda: self.db),
                        mock.patch.object(events, "db_path", lambda: self.events_db)):
            patcher.start()
            self.addCleanup(patcher.stop)
        from api import admin
        self.admin = admin

    def grant(self, **body):
        return self.admin.grant_tester_access(self.admin.TesterGrantRequest(**body), _admin=None)

    def extend(self, **body):
        return self.admin.extend_tester_access(self.admin.TesterExtendRequest(**body), _admin=None)

    def refusal(self, call, **body):
        with self.assertRaises(HTTPException) as ctx:
            call(**body)
        return ctx.exception

    def test_all_three_routes_sit_behind_the_one_admin_gate(self):
        import inspect
        routes = {(r.path, tuple(sorted(r.methods))): r.endpoint for r in self.admin.router.routes}
        for key, fn in ((("/admin/testers", ("POST",)), self.admin.grant_tester_access),
                        (("/admin/testers/extend", ("POST",)), self.admin.extend_tester_access),
                        (("/admin/testers", ("GET",)), self.admin.get_testers)):
            self.assertIs(routes[key], fn, key)
            default = inspect.signature(fn).parameters["_admin"].default
            self.assertIs(default.dependency, self.admin._require_admin, key)

    def test_the_gate_is_404_unconfigured_and_401_wrong(self):
        for configured, sent, status in ((None, "x", 404), ("right", "wrong", 401)):
            env = {} if configured is None else {"APP_ADMIN_TOKEN": configured}
            with mock.patch.dict(os.environ, env, clear=False):
                if configured is None:
                    os.environ.pop("APP_ADMIN_TOKEN", None)
                with self.assertRaises(HTTPException) as ctx:
                    self.admin._require_admin(x_admin_token=sent)
                self.assertEqual(ctx.exception.status_code, status)

    def test_a_grant_returns_the_shape_with_the_raw_token_once(self):
        result = self.grant(email="New.Person@Example.com")
        self.assertEqual(set(result), {"user_id", "email", "token", "expires_at",
                                       "testers_granted", "testers_limit"})
        self.assertEqual(result["email"], "new.person@example.com")
        self.assertEqual((result["testers_granted"], result["testers_limit"]), (1, 20))
        self.assertTrue(users_store.authenticate(result["token"]))
        listing = self.admin.get_testers(_admin=None)
        self.assertNotIn(result["token"], json.dumps(listing))
        self.assertNotIn(result["token"], json.dumps(self.admin.get_users(_admin=None)))

    def test_by_user_id_works_too(self):
        user = users_store.create_user("wait@example.com", status="waitlisted")
        self.assertEqual(self.grant(user_id=user.id)["user_id"], user.id)

    def test_exactly_one_of_email_or_user_id_is_a_400(self):
        for body in ({}, {"email": "a@example.com", "user_id": 1}):
            self.assertEqual(self.refusal(self.grant, **body).status_code, 400)
        self.assertEqual(self.refusal(self.extend, reason="x").status_code, 400)

    def test_a_refusal_is_a_structured_409_and_writes_nothing(self):
        for i in range(testers.TESTER_LIMIT):
            self.grant(email=f"t{i}@example.com")
        users_before = len(users_store.list_users())
        exc = self.refusal(self.grant, email="late@example.com")
        self.assertEqual(exc.status_code, 409)
        self.assertEqual(exc.detail["error"], "tester_limit_reached")
        self.assertEqual((exc.detail["testers_granted"], exc.detail["testers_limit"]), (20, 20))
        self.assertIn("message", exc.detail)
        self.assertEqual(len(users_store.list_users()), users_before)
        self.assertEqual(testers.count_granted(), 20)

    def test_each_refusal_reason_keeps_its_own_code(self):
        susp = users_store.create_user("susp@example.com", status="suspended")
        pend = users_store.create_user("pend@example.com", status="pending_payment")
        paid = users_store.create_user("paid@example.com", status="active", plan="beta")
        customers.upsert_subscription(paid.id, "sub_1", "active")
        for user, code in ((susp, "user_suspended"), (pend, "checkout_open"),
                           (paid, "has_subscription")):
            exc = self.refusal(self.grant, user_id=user.id)
            self.assertEqual((exc.status_code, exc.detail["error"]), (409, code))
        self.assertEqual(self.refusal(self.grant, user_id=999).status_code, 404)
        self.assertEqual(self.refusal(self.grant, email="nonsense").status_code, 400)

    def test_the_grant_event_carries_attribution_and_never_the_token_or_email(self):
        user = users_store.create_user("tagged@example.com", status="waitlisted")
        customers.record_signup_attribution(
            user.id, {"utm_source": "discord_unit_circle", "referrer_host": "discord.com"})
        result = self.grant(user_id=user.id)
        recorded = [e for e in events.list_events() if e.kind == events.TESTER_ACCESS_GRANTED]
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0].user_hash, events.hash_user_id(user.id))
        self.assertEqual(recorded[0].properties,
                         {"utm_source": "discord_unit_circle", "referrer_host": "discord.com"})
        blob = json.dumps(recorded[0].properties) + str(recorded[0])
        self.assertNotIn(result["token"], blob)
        self.assertNotIn("tagged@example.com", blob)

    def test_a_grant_with_no_attribution_still_records_the_event(self):
        self.grant(email="direct@example.com")
        recorded = [e for e in events.list_events() if e.kind == events.TESTER_ACCESS_GRANTED]
        self.assertEqual([e.properties for e in recorded], [{}])

    def test_a_refused_grant_records_no_event(self):
        susp = users_store.create_user("susp@example.com", status="suspended")
        self.refusal(self.grant, user_id=susp.id)
        self.assertEqual(events.list_events(), [])

    def test_an_extension_returns_a_new_token_and_records_its_event_without_the_reason(self):
        first = self.grant(email="a@example.com")
        result = self.extend(user_id=first["user_id"], reason="very specific private note")
        self.assertNotEqual(result["token"], first["token"])
        self.assertEqual(result["testers_granted"], 1)
        self.assertEqual(result["extension_number"], 1)
        recorded = [e for e in events.list_events() if e.kind == events.TESTER_ACCESS_EXTENDED]
        self.assertEqual(len(recorded), 1)
        blob = str(recorded[0]) + json.dumps(recorded[0].properties)
        for secret in (result["token"], "very specific private note", "a@example.com"):
            self.assertNotIn(secret, blob)
        self.assertTrue(users_store.authenticate(first["token"]), "old token still works")

    def test_extension_refusals_are_structured(self):
        plain = users_store.create_user("plain@example.com", status="invited")
        exc = self.refusal(self.extend, user_id=plain.id, reason="x")
        self.assertEqual((exc.status_code, exc.detail["error"]), (409, "not_a_tester"))
        first = self.grant(email="a@example.com")
        exc = self.refusal(self.extend, user_id=first["user_id"], reason="  ")
        self.assertEqual((exc.status_code, exc.detail["error"]), (400, "reason_required"))
        self.assertEqual(events.list_events()[-1].kind, events.TESTER_ACCESS_GRANTED,
                         "a refused extension records no event")

    def test_the_users_listing_marks_testers(self):
        tester = self.grant(email="t@example.com")
        users_store.create_user("plain@example.com", status="invited")
        rows = {r["email"]: r for r in self.admin.get_users(_admin=None)["users"]}
        self.assertTrue(rows["t@example.com"]["tester"])
        self.assertEqual(rows["t@example.com"]["tester_expires_at"], tester["expires_at"])
        self.assertTrue(rows["t@example.com"]["tester_granted_at"])
        self.assertFalse(rows["plain@example.com"]["tester"])
        self.assertIsNone(rows["plain@example.com"]["tester_expires_at"])

    def test_the_listing_route_is_the_store_listing(self):
        self.grant(email="t@example.com")
        listing = self.admin.get_testers(_admin=None)
        self.assertEqual((listing["granted"], listing["limit"], listing["remaining"]), (1, 20, 19))
        self.assertEqual(listing["testers"][0]["email"], "t@example.com")

    def test_the_token_is_never_printed(self):
        import contextlib
        import io
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            token = self.grant(email="quiet@example.com")["token"]
        self.assertNotIn(token, out.getvalue() + err.getvalue())

    def test_a_failed_attribution_read_does_not_lose_the_token(self):
        with mock.patch.object(customers, "get_signup_attribution",
                               side_effect=sqlite3.OperationalError("disk I/O error")):
            result = self.grant(email="keep@example.com")
        self.assertTrue(users_store.authenticate(result["token"]))
        self.assertEqual(testers.count_granted(), 1)


# ---------------------------------------------------------------------------
# The REAL app, over ASGI: does a tester token actually open a paid page?
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class ATesterTokenOpensThePaidPagesUntilItExpires(unittest.TestCase):
    """Day 6 in, day 8 out. The grant is stamped in the past (the store takes
    `now`), the request is made at the real clock: nothing sleeps and nothing
    patches the clock inside the auth path."""

    @classmethod
    def setUpClass(cls):
        from api.app import app
        cls.app = app

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        db = str(Path(self._tmp.name) / "app.db")
        env = mock.patch.dict(os.environ, {"APP_DB_PATH": db})
        env.start()
        self.addCleanup(env.stop)

    def _get(self, path, token):
        from tests.test_api_surface_auth import _request
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return _request(self.app, "GET", path, headers)

    def _tester(self, age_days):
        real_now = datetime.now(timezone.utc)
        return testers.grant_tester(email=f"day{age_days}@example.com",
                                    now=real_now - timedelta(days=age_days))

    def test_the_card_opens_on_day_six(self):
        status, _ = self._get("/card", self._tester(6).token)
        self.assertNotIn(status, (401, 402, 403))

    def test_the_card_is_refused_on_day_eight_with_a_401_that_says_the_access_ended(self):
        # CHANGED 2026-10-03 (expired tester -> paying subscriber): still a 401,
        # but no longer the generic body -- the page has to be able to tell "your
        # early access ended" from "that token is wrong". A wrong token keeps
        # the generic body (tests/test_expired_tester_paid_path.py).
        grant = self._tester(8)
        status, body = self._get("/card", grant.token)
        self.assertEqual(status, 401)
        self.assertEqual(body["detail"]["error"], "tester_access_expired")
        self.assertEqual(body["detail"]["expires_at"], grant.expires_at)

    def test_a_wrong_token_is_still_the_generic_401(self):
        status, body = self._get("/card", "not-a-token-anyone-was-given")
        self.assertEqual(status, 401)
        self.assertEqual(body["detail"]["error"], "unauthorized")

    def test_no_token_at_all_is_still_a_401(self):
        self.assertEqual(self._get("/card", None)[0], 401)

    def test_a_subscriber_is_still_gated_by_their_subscription_not_by_this(self):
        """require_paid_access is untouched: a user WITH a subscription record
        that has lapsed is a 402, whatever tokens they hold."""
        from api import auth
        user = users_store.create_user("lapsed@example.com", status="active", plan="beta")
        customers.upsert_customer(user.id, "cus_1")
        customers.upsert_subscription(user.id, "sub_1", "canceled")
        with self.assertRaises(HTTPException) as ctx:
            auth.require_paid_access(current_user=user)
        self.assertEqual(ctx.exception.status_code, 402)


if __name__ == "__main__":
    unittest.main()
