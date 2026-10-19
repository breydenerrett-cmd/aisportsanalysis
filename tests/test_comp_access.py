"""Free ("comp") members: full access, no card, no end date, granted by hand.

Owner ask (2026-10-19): a person signed up for early access, was waitlisted, and
the owner wanted him in -- free, forever. The only grant that existed was a
7-day tester token (one of 20 slots). These tests pin the comp that replaces the
workaround, and the parts that are easy to get quietly wrong:

  * a grant works for a NEW email, a WAITLISTED signup, an EXPIRED tester and an
    existing user, and sets the account `active`;
  * it is refused (409, nothing written) for a suspended account, a live
    subscriber and an open checkout, and a lapsed subscriber is NOT refused;
  * exactly ONE token afterwards, far-future (10 years), every older token
    revoked in the same transaction, raw token returned once and nowhere else;
  * customers.has_paid_access is True for a comp and False the moment it is
    revoked, for a suspended comp, and the subscription-only question
    (has_subscription_access) is untouched -- including a former subscriber whose
    lapsed record would otherwise be a 402, through the REAL app;
  * the audit event carries no token, no email and no reason, and is written in
    the grant's own transaction (a failed audit leaves nothing behind);
  * the support re-issue handles a comp (new token, same far-future end);
  * the admin routes are admin-only (404 unconfigured, 401 wrong token);
  * GET /billing/status reports `plan: comp, renews: false`, and checkout, cancel
    and reactivate never reach a provider for a free member;
  * every door that decides entitlement goes through customers.has_paid_access.

The store half needs no FastAPI (src/ is stdlib only). The route half calls the
route functions directly, as tests/test_tester_access.py does, and the door half
drives the REAL app over ASGI, so both are skipped where FastAPI is absent (the
Linux CI image).
"""

from __future__ import annotations

import asyncio
import contextlib
import io
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

from src.appstate import comps
from src.appstate import customers
from src.appstate import events
from src.appstate import testers
from src.appstate import users as users_store

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
ADMIN = "admin-token-for-the-comp-test"


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "app.db"

    def grant(self, email="jacob@example.com", reason="early-access signup", **kw):
        kw.setdefault("now", NOW)
        return comps.grant_comp(email=email, reason=reason, db=self.db, **kw)

    def refusal(self, **kw):
        with self.assertRaises(comps.CompRefused) as ctx:
            comps.grant_comp(db=self.db, now=NOW, **kw)
        return ctx.exception

    def counts(self):
        """Row counts straight from the file, by a connection that shares no code
        with the module under test. A table never created has 0 rows."""
        with closing(sqlite3.connect(str(self.db))) as conn:
            have = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            return {t: (conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                        if t in have else 0)
                    for t in ("users", "tokens", "comps", "analytics_events", "testers")}

    def tokens_of(self, user_id):
        with closing(sqlite3.connect(str(self.db))) as conn:
            return conn.execute(
                "SELECT created_at, expires_at, revoked_at FROM tokens WHERE user_id = ?",
                (user_id,)).fetchall()

    def lapsed_subscriber(self, email="lapsed@example.com", status="active"):
        user = users_store.create_user(email, status=status, plan="beta", db=self.db)
        customers.upsert_customer(user.id, f"cus_{user.id}", db=self.db)
        customers.upsert_subscription(
            user.id, f"sub_{user.id}", "canceled",
            current_period_end=(NOW - timedelta(days=30)).isoformat(), db=self.db)
        return user

    def paying_subscriber(self, email="paid@example.com", status="active",
                          paid_through=None, sub_status="active"):
        user = users_store.create_user(email, status="active", plan="beta", db=self.db)
        customers.upsert_customer(user.id, f"cus_{user.id}", db=self.db)
        end = paid_through if paid_through is not None else (
            datetime.now(timezone.utc) + timedelta(days=20)).isoformat()
        customers.upsert_subscription(user.id, f"sub_{user.id}", sub_status,
                                      current_period_end=end, db=self.db)
        return user


# ---------------------------------------------------------------------------
# Who can be made a free member
# ---------------------------------------------------------------------------

class GrantingAFreeMembership(_Base):
    def test_a_new_email_becomes_an_active_user_with_one_ten_year_token(self):
        grant = self.grant("  New.Person@Example.COM ")
        user = users_store.get_user_by_email("new.person@example.com", db=self.db)
        self.assertEqual((user.status, user.plan), ("active", "none"))
        self.assertEqual((grant.user_id, grant.email, grant.kind), (user.id, user.email, "new_email"))
        self.assertEqual(grant.revoked_tokens, 0)
        self.assertEqual(grant.expires_at, (NOW + timedelta(days=3650)).isoformat())
        self.assertEqual(users_store.authenticate(grant.token, db=self.db, now=NOW).id, user.id)
        self.assertTrue(customers.has_paid_access(user.id, NOW, db=self.db))

    def test_the_token_is_still_good_in_nine_years_and_dead_in_eleven(self):
        grant = self.grant()
        nine = NOW + timedelta(days=365 * 9)
        eleven = NOW + timedelta(days=365 * 11)
        self.assertIsNotNone(users_store.authenticate(grant.token, db=self.db, now=nine))
        self.assertIsNone(users_store.authenticate(grant.token, db=self.db, now=eleven))

    def test_a_waitlisted_signup_keeps_their_row_and_becomes_active(self):
        waiting = users_store.create_user("wait@example.com", status="waitlisted", db=self.db)
        grant = comps.grant_comp(user_id=waiting.id, reason="approved from the waitlist",
                                 now=NOW, db=self.db)
        self.assertEqual((grant.user_id, grant.kind), (waiting.id, "waitlisted"))
        self.assertEqual(users_store.get_user(waiting.id, db=self.db).status, "active")
        self.assertEqual(self.counts()["users"], 1)

    def test_a_waitlisted_signup_can_also_be_granted_by_email(self):
        users_store.create_user("wait@example.com", status="waitlisted", db=self.db)
        grant = self.grant("WAIT@example.com")
        self.assertEqual(grant.kind, "waitlisted")
        self.assertEqual(self.counts()["users"], 1)

    def test_an_expired_tester_gets_a_working_token_and_keeps_the_tester_history(self):
        old = testers.grant_tester(email="t@example.com", now=NOW - timedelta(days=20), db=self.db)
        self.assertIsNone(users_store.authenticate(old.token, db=self.db, now=NOW))
        grant = comps.grant_comp(user_id=old.user_id, reason="liked the card", now=NOW, db=self.db)
        self.assertEqual((grant.user_id, grant.kind), (old.user_id, "tester"))
        self.assertEqual(users_store.authenticate(grant.token, db=self.db, now=NOW).id, old.user_id)
        self.assertEqual(testers.count_granted(db=self.db), 1)      # no second slot, row kept
        self.assertEqual(users_store.get_user(old.user_id, db=self.db).status, "active")

    def test_an_existing_user_loses_every_older_token_and_ends_with_exactly_one(self):
        user = users_store.create_user("have@example.com", status="invited", db=self.db)
        first = users_store.issue_invite_token(user.id, db=self.db)
        second = users_store.issue_invite_token(user.id, db=self.db)
        grant = comps.grant_comp(user_id=user.id, reason="friend of the project",
                                 now=NOW, db=self.db)
        self.assertEqual((grant.kind, grant.revoked_tokens), ("existing", 2))
        self.assertIsNone(users_store.authenticate(first, db=self.db))
        self.assertIsNone(users_store.authenticate(second, db=self.db))
        live = [t for t in self.tokens_of(user.id) if t[2] is None]
        self.assertEqual(len(live), 1)
        self.assertEqual(users_store.authenticate(grant.token, db=self.db, now=NOW).id, user.id)

    def test_the_unhashed_checkout_copy_of_an_older_token_is_wiped_too(self):
        user = users_store.create_user("buyer@example.com", status="active", db=self.db)
        raw = users_store.issue_invite_token(user.id, db=self.db)
        customers.record_activation_token("cs_test_abc12345", user.id, raw, db=self.db)
        comps.grant_comp(user_id=user.id, reason="comped instead", now=NOW, db=self.db)
        with closing(sqlite3.connect(str(self.db))) as conn:
            self.assertIsNone(conn.execute(
                "SELECT raw_token FROM signup_activation_tokens").fetchone()[0])

    def test_a_lapsed_subscriber_can_be_made_a_free_member(self):
        user = self.lapsed_subscriber()
        grant = comps.grant_comp(user_id=user.id, reason="came back as a friend",
                                 now=NOW, db=self.db)
        self.assertEqual(grant.user_id, user.id)
        self.assertTrue(customers.has_paid_access(user.id, NOW, db=self.db))
        self.assertFalse(customers.has_subscription_access(user.id, NOW, db=self.db))

    def test_exactly_one_of_email_or_user_id(self):
        for kwargs in ({}, {"email": "a@example.com", "user_id": 1}):
            with self.assertRaises(ValueError):
                comps.grant_comp(reason="x", db=self.db, **kwargs)

    def test_a_bad_email_and_an_unknown_user_id_are_refused_with_nothing_written(self):
        for kwargs, code, status in (({"email": "not-an-email"}, "invalid_email", 400),
                                     ({"email": ""}, "invalid_email", 400),
                                     ({"user_id": 4242}, "no_such_user", 404)):
            exc = self.refusal(reason="why", **kwargs)
            self.assertEqual((exc.code, exc.status), (code, status))
        self.assertEqual(sum(self.counts().values()), 0)

    def test_the_grant_object_never_prints_the_token(self):
        grant = self.grant()
        self.assertNotIn(grant.token, repr(grant))
        self.assertNotIn(grant.token, str(grant))


class WhoIsRefused(_Base):
    def test_a_suspended_user_is_refused_and_stays_suspended(self):
        user = users_store.create_user("susp@example.com", status="suspended", db=self.db)
        exc = self.refusal(user_id=user.id, reason="why")
        self.assertEqual((exc.code, exc.status), ("user_suspended", 409))
        self.assertEqual(users_store.get_user(user.id, db=self.db).status, "suspended")
        self.assertEqual(self.counts()["comps"], 0)
        self.assertEqual(self.counts()["tokens"], 0)

    def test_every_kind_of_live_subscription_is_refused_and_nothing_is_written(self):
        # (status, paid_through) pairs: paid through the future, trialing, and an
        # active row with nothing paid through yet (a checkout paying this minute).
        future = (datetime.now(timezone.utc) + timedelta(days=20)).isoformat()
        for i, (status, paid) in enumerate((("active", future), ("trialing", future))):
            with self.subTest(status=status):
                user = self.paying_subscriber(f"p{i}@example.com", sub_status=status,
                                              paid_through=paid)
                before = self.counts()
                exc = self.refusal(user_id=user.id, reason="why")
                self.assertEqual((exc.code, exc.status), ("has_subscription", 409))
                self.assertEqual(self.counts(), before)
        user = users_store.create_user("inflight@example.com", status="active", db=self.db)
        customers.upsert_subscription(user.id, "sub_x", "active", paid_through=None, db=self.db)
        self.assertEqual(self.refusal(user_id=user.id, reason="why").code, "has_subscription")

    def test_a_subscriber_scheduled_to_cancel_but_still_paid_through_is_refused(self):
        user = users_store.create_user("leaving@example.com", status="active", db=self.db)
        end = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        customers.upsert_subscription(user.id, "sub_c", "active", cancel_at=end,
                                      current_period_end=end, db=self.db)
        self.assertEqual(self.refusal(user_id=user.id, reason="why").code, "has_subscription")

    def test_an_open_checkout_is_refused(self):
        user = users_store.create_user("mid@example.com", status="pending_payment", db=self.db)
        exc = self.refusal(user_id=user.id, reason="why")
        self.assertEqual((exc.code, exc.status), ("checkout_open", 409))
        self.assertEqual(users_store.get_user(user.id, db=self.db).status, "pending_payment")

    def test_a_current_free_member_is_refused_a_second_grant_and_keeps_their_token(self):
        first = self.grant()
        exc = self.refusal(email="jacob@example.com", reason="again")
        self.assertEqual((exc.code, exc.status), ("already_comp", 409))
        self.assertEqual(users_store.authenticate(first.token, db=self.db, now=NOW).id, first.user_id)
        self.assertEqual(self.counts()["comps"], 1)

    def test_the_reason_is_required_bounded_and_never_a_credential(self):
        secrets_ = ("A" * 40, "sk-live-" + "b" * 40, "Bearer abcdefgh1234", "token=abc",
                    "session_id=cs_test_a1b2c3d4e5f6", "see x-admin-token header",
                    "cs_live_abcdef123456")
        for reason, code in ((None, "reason_required"), ("   ", "reason_required"),
                             ("x" * 501, "reason_too_long"),
                             *((s, "reason_looks_like_a_secret") for s in secrets_)):
            with self.subTest(reason=(reason or "")[:20]):
                exc = self.refusal(email="a@example.com", reason=reason)
                self.assertEqual((exc.code, exc.status), (code, 400))
        self.assertEqual(sum(self.counts().values()), 0)
        self.assertEqual(self.grant(reason="plain note: lost bearer token").user_id, 1)

    def test_the_reason_check_is_the_one_the_support_reissue_uses(self):
        text = (ROOT / "api" / "admin.py").read_text(encoding="utf-8")
        self.assertIn("_LOOKS_LIKE_A_TOKEN = comps.LOOKS_LIKE_A_TOKEN", text)
        self.assertIn("_SECRET_HINTS = comps.SECRET_HINTS", text)


# ---------------------------------------------------------------------------
# Access: the one entitlement check
# ---------------------------------------------------------------------------

class TheAccessCheck(_Base):
    def test_true_for_a_free_member_false_after_the_revoke(self):
        grant = self.grant()
        self.assertTrue(customers.has_paid_access(grant.user_id, NOW, db=self.db))
        self.assertTrue(customers.has_active_comp(grant.user_id, db=self.db))
        comps.revoke_comp(grant.user_id, "no longer needed", now=NOW, db=self.db)
        self.assertFalse(customers.has_paid_access(grant.user_id, NOW, db=self.db))
        self.assertFalse(customers.has_active_comp(grant.user_id, db=self.db))

    def test_false_for_a_stranger_and_for_a_user_who_never_had_one(self):
        user = users_store.create_user("plain@example.com", status="active", db=self.db)
        self.assertFalse(customers.has_paid_access(user.id, NOW, db=self.db))
        self.assertFalse(customers.has_paid_access(987654, NOW, db=self.db))

    def test_a_suspended_free_member_is_not_let_in(self):
        grant = self.grant()
        users_store.set_user_status(grant.user_id, "suspended", db=self.db)
        self.assertFalse(customers.has_paid_access(grant.user_id, NOW, db=self.db))
        users_store.set_user_status(grant.user_id, "active", db=self.db)
        self.assertTrue(customers.has_paid_access(grant.user_id, NOW, db=self.db))

    def test_the_subscription_question_does_not_count_a_comp(self):
        grant = self.grant()
        self.assertFalse(customers.has_subscription_access(grant.user_id, NOW, db=self.db))

    def test_a_database_only_the_billing_module_has_opened_has_no_comps_and_no_error(self):
        # customers makes the comps table, users.py makes users: a bare billing
        # database must answer False, not raise.
        bare = Path(self._tmp.name) / "bare.db"
        self.assertFalse(customers.has_paid_access(1, NOW, db=bare))
        self.assertIsNone(customers.get_active_comp(1, db=bare))

    def test_an_old_database_without_the_table_gains_it_and_keeps_every_row(self):
        old = Path(self._tmp.name) / "old.db"
        with closing(sqlite3.connect(str(old))) as conn:
            conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                         "email TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, "
                         "status TEXT NOT NULL, plan TEXT NOT NULL)")
            conn.execute("CREATE TABLE tokens (token_hash TEXT PRIMARY KEY, user_id INTEGER "
                         "NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, "
                         "revoked_at TEXT)")
            conn.execute("INSERT INTO users VALUES (1, 'old@example.com', '2026-09-01', "
                         "'active', 'beta')")
            conn.execute("INSERT INTO tokens VALUES ('h', 1, '2026-09-01', '2027-01-01', NULL)")
            conn.commit()
        self.assertEqual(comps.list_comps(db=old)["comps"], [])
        grant = comps.grant_comp(email="new@example.com", reason="why", now=NOW, db=old)
        self.assertEqual(grant.user_id, 2)
        with closing(sqlite3.connect(str(old))) as conn:
            self.assertEqual(conn.execute("SELECT email FROM users WHERE id = 1").fetchone()[0],
                             "old@example.com")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM comps").fetchone()[0], 1)
            self.assertEqual(conn.execute(
                "SELECT revoked_at FROM tokens WHERE token_hash = 'h'").fetchone()[0], None)


class Revoking(_Base):
    def test_revoking_ends_the_comp_and_every_token_and_keeps_the_row(self):
        grant = self.grant()
        extra = users_store.issue_invite_token(grant.user_id, db=self.db)
        out = comps.revoke_comp(grant.user_id, "asked to be removed", now=NOW, db=self.db)
        self.assertEqual((out["user_id"], out["revoked_tokens"]), (grant.user_id, 2))
        self.assertIsNone(users_store.authenticate(grant.token, db=self.db, now=NOW))
        self.assertIsNone(users_store.authenticate(extra, db=self.db, now=NOW))
        row = comps.list_comps(db=self.db)["comps"][0]
        self.assertEqual((row["active"], row["revoked_reason"]), (False, "asked to be removed"))
        self.assertEqual(row["revoked_at"], NOW.isoformat())
        self.assertEqual(self.counts()["comps"], 1)

    def test_revoking_needs_a_reason_and_a_current_free_member(self):
        grant = self.grant()
        with self.assertRaises(comps.CompRefused) as ctx:
            comps.revoke_comp(grant.user_id, "", db=self.db)
        self.assertEqual(ctx.exception.code, "reason_required")
        with self.assertRaises(comps.CompRefused) as ctx:
            comps.revoke_comp(999, "why", db=self.db)
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("no_such_user", 404))
        plain = users_store.create_user("plain@example.com", status="active", db=self.db)
        with self.assertRaises(comps.CompRefused) as ctx:
            comps.revoke_comp(plain.id, "why", db=self.db)
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("not_a_comp", 409))
        comps.revoke_comp(grant.user_id, "done", db=self.db)
        with self.assertRaises(comps.CompRefused) as ctx:
            comps.revoke_comp(grant.user_id, "done again", db=self.db)
        self.assertEqual(ctx.exception.code, "not_a_comp")

    def test_a_revoked_member_can_be_granted_again_on_the_same_row(self):
        grant = self.grant(reason="first reason")
        comps.revoke_comp(grant.user_id, "paused", now=NOW, db=self.db)
        again = comps.grant_comp(user_id=grant.user_id, reason="second reason",
                                 now=NOW + timedelta(days=1), db=self.db)
        self.assertEqual(again.user_id, grant.user_id)
        self.assertEqual(self.counts()["comps"], 1)
        row = comps.list_comps(db=self.db)["comps"][0]
        self.assertEqual((row["active"], row["reason"], row["revoked_at"]),
                         (True, "second reason", None))
        self.assertTrue(customers.has_paid_access(grant.user_id, NOW, db=self.db))


# ---------------------------------------------------------------------------
# The audit trail, and what must never be in it
# ---------------------------------------------------------------------------

class TheAuditTrail(_Base):
    def _events(self):
        return events.list_events(db=self.db)

    def test_a_grant_and_a_revoke_each_write_one_event_with_no_secrets(self):
        email = "jacob.private@example.com"
        reason = "friend of the project, met at the meetup"
        grant = self.grant(email, reason=reason)
        comps.revoke_comp(grant.user_id, "changed my mind about it", now=NOW, db=self.db)
        rows = self._events()
        self.assertEqual([e.kind for e in rows],
                         [events.COMP_ACCESS_GRANTED, events.COMP_ACCESS_REVOKED])
        self.assertEqual(rows[0].properties,
                         {"action": "grant", "kind": "new_email", "revoked_tokens": 0,
                          "had_password": False})
        self.assertEqual(rows[1].properties, {"action": "revoke", "revoked_tokens": 1,
                          "had_password": False})
        self.assertEqual({e.user_hash for e in rows}, {events.hash_user_id(grant.user_id)})
        blob = json.dumps([[e.user_hash, e.kind, e.properties, e.at] for e in rows])
        for secret in (grant.token, email, "jacob.private", "meetup", "changed my mind"):
            self.assertNotIn(secret, blob)

    def test_no_table_holds_the_raw_token(self):
        grant = self.grant()
        with closing(sqlite3.connect(str(self.db))) as conn:
            dump = "\n".join(conn.iterdump())
        self.assertNotIn(grant.token, dump)
        self.assertIn(users_store._hash_token(grant.token), dump)

    def test_the_listing_never_carries_a_token(self):
        grant = self.grant()
        listing = comps.list_comps(db=self.db)
        self.assertNotIn(grant.token, json.dumps(listing))
        self.assertEqual(listing["active"], 1)
        self.assertEqual(listing["comps"][0]["email"], "jacob@example.com")
        self.assertEqual(listing["comps"][0]["granted_by"], "admin")

    def test_a_failed_audit_write_rolls_the_whole_grant_back(self):
        with mock.patch.object(comps, "_audit", side_effect=sqlite3.OperationalError("disk I/O error")):
            with self.assertRaises(sqlite3.OperationalError):
                self.grant()
        self.assertEqual(self.counts()["users"], 0)
        self.assertEqual(self.counts()["comps"], 0)
        self.assertEqual(self.counts()["tokens"], 0)

    def test_a_failed_audit_write_leaves_a_revoke_undone(self):
        grant = self.grant()
        with mock.patch.object(comps, "_audit", side_effect=sqlite3.OperationalError("disk I/O error")):
            with self.assertRaises(sqlite3.OperationalError):
                comps.revoke_comp(grant.user_id, "why", now=NOW, db=self.db)
        self.assertTrue(customers.has_paid_access(grant.user_id, NOW, db=self.db))
        self.assertIsNotNone(users_store.authenticate(grant.token, db=self.db, now=NOW))

    def test_a_refusal_writes_nothing_not_even_an_event(self):
        user = users_store.create_user("susp@example.com", status="suspended", db=self.db)
        before = self.counts()
        self.refusal(user_id=user.id, reason="why")
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.counts()["analytics_events"], 0)


# ---------------------------------------------------------------------------
# The admin routes, called directly
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheAdminRoutes(_Base):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(users_store, "db_path", lambda: self.db)
        patcher.start()
        self.addCleanup(patcher.stop)
        events_patch = mock.patch.object(events, "db_path", lambda: self.db)
        events_patch.start()
        self.addCleanup(events_patch.stop)
        from api import admin
        self.admin = admin

    def post(self, **body):
        return self.admin.grant_comp_access(self.admin.CompGrantRequest(**body), _admin=None)

    def revoke(self, **body):
        return self.admin.revoke_comp_access(self.admin.CompRevokeRequest(**body), _admin=None)

    def refused(self, call, **body):
        with self.assertRaises(HTTPException) as ctx:
            call(**body)
        return ctx.exception

    def test_the_three_routes_sit_behind_the_one_admin_gate(self):
        import inspect
        routes = {(r.path, tuple(sorted(r.methods))): r.endpoint for r in self.admin.router.routes}
        for key, fn in ((("/admin/comps", ("POST",)), self.admin.grant_comp_access),
                        (("/admin/comps/revoke", ("POST",)), self.admin.revoke_comp_access),
                        (("/admin/comps", ("GET",)), self.admin.get_comps)):
            self.assertIs(routes[key], fn, key)
            default = inspect.signature(fn).parameters["_admin"].default
            self.assertIs(default.dependency, self.admin._require_admin, key)

    def test_a_grant_returns_the_raw_token_once_and_the_listing_never_does(self):
        result = self.post(email="New.Person@Example.com", reason="early-access signup")
        self.assertEqual(set(result), {"user_id", "email", "token", "expires_at", "kind",
                                       "revoked_tokens"})
        self.assertEqual((result["email"], result["kind"]), ("new.person@example.com", "new_email"))
        self.assertTrue(users_store.authenticate(result["token"]))
        for payload in (self.admin.get_comps(_admin=None), self.admin.get_users(_admin=None),
                        self.admin.get_testers(_admin=None), self.admin.get_overview(_admin=None)):
            self.assertNotIn(result["token"], json.dumps(payload, default=str))

    def test_the_users_listing_marks_free_members_and_former_ones(self):
        grant = self.post(email="a@example.com", reason="why")
        self.post(email="b@example.com", reason="why")
        self.revoke(user_id=grant["user_id"], reason="done")
        rows = {u["email"]: u for u in self.admin.get_users(_admin=None)["users"]}
        self.assertEqual((rows["a@example.com"]["comp"], rows["a@example.com"]["comp_revoked"]),
                         (False, True))
        self.assertEqual((rows["b@example.com"]["comp"], rows["b@example.com"]["comp_revoked"]),
                         (True, False))

    def test_by_user_id_works_for_a_waitlisted_signup(self):
        user = users_store.create_user("wait@example.com", status="waitlisted")
        self.assertEqual(self.post(user_id=user.id, reason="approved")["kind"], "waitlisted")

    def test_exactly_one_of_email_or_user_id_is_a_400(self):
        for body in ({"reason": "x"}, {"email": "a@example.com", "user_id": 1, "reason": "x"}):
            self.assertEqual(self.refused(self.post, **body).status_code, 400)

    def test_every_refusal_is_a_structured_error_and_writes_nothing(self):
        suspended = users_store.create_user("susp@example.com", status="suspended")
        paid = self.paying_subscriber()
        cases = ((dict(user_id=suspended.id, reason="why"), 409, "user_suspended"),
                 (dict(user_id=paid.id, reason="why"), 409, "has_subscription"),
                 (dict(email="x@example.com"), 400, "reason_required"),
                 (dict(email="x@example.com", reason="y" * 600), 400, "reason_too_long"),
                 (dict(email="x@example.com", reason="Q" * 50), 400, "reason_looks_like_a_secret"),
                 (dict(email="nope", reason="why"), 400, "invalid_email"),
                 (dict(user_id=4242, reason="why"), 404, "no_such_user"))
        before = self.counts()
        for body, status, code in cases:
            with self.subTest(code=code):
                exc = self.refused(self.post, **body)
                self.assertEqual((exc.status_code, exc.detail["error"]), (status, code))
                self.assertTrue(exc.detail["message"])
        self.assertEqual(self.counts(), before)

    def test_a_user_id_that_is_not_an_account_id_is_the_unknown_account_answer(self):
        for bad in ("1", 1.5, [1], 2 ** 70, 0, -3, True):
            with self.subTest(bad=bad):
                exc = self.refused(self.post, user_id=bad, reason="why")
                self.assertEqual((exc.status_code, exc.detail["error"]), (404, "no_such_user"))
                exc = self.refused(self.revoke, user_id=bad, reason="why")
                self.assertEqual((exc.status_code, exc.detail["error"]), (404, "no_such_user"))

    def test_a_write_that_fails_is_a_503_and_changes_nothing(self):
        with mock.patch.object(comps, "_audit", side_effect=sqlite3.OperationalError("disk")):
            with contextlib.redirect_stderr(io.StringIO()):
                exc = self.refused(self.post, email="a@example.com", reason="why")
        self.assertEqual((exc.status_code, exc.detail["error"]), (503, "comp_grant_failed"))
        self.assertEqual(self.counts()["comps"], 0)

    def test_revoke_route_ends_access_and_a_second_revoke_is_a_409(self):
        result = self.post(email="a@example.com", reason="why")
        out = self.revoke(user_id=result["user_id"], reason="done")
        self.assertEqual(out["revoked_tokens"], 1)
        self.assertIsNone(users_store.authenticate(result["token"]))
        exc = self.refused(self.revoke, user_id=result["user_id"], reason="again")
        self.assertEqual((exc.status_code, exc.detail["error"]), (409, "not_a_comp"))

    def test_the_token_is_never_printed(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            token = self.post(email="quiet@example.com", reason="why")["token"]
        self.assertNotIn(token, out.getvalue() + err.getvalue())

    def test_the_gate_is_404_unconfigured_and_401_wrong(self):
        for configured, sent, status in ((None, "x", 404), ("right", "wrong", 401)):
            env = {} if configured is None else {"APP_ADMIN_TOKEN": configured}
            with mock.patch.dict(os.environ, env, clear=False):
                if configured is None:
                    os.environ.pop("APP_ADMIN_TOKEN", None)
                with self.assertRaises(HTTPException) as ctx:
                    self.admin._require_admin(x_admin_token=sent)
                self.assertEqual(ctx.exception.status_code, status)

    # -- the support re-issue --------------------------------------------------

    def reissue(self, **body):
        return self.admin.reissue_access_token(
            self.admin.ReissueAccessRequest(**body), _admin=None)

    def test_reissue_gives_a_free_member_a_new_far_future_token(self):
        grant = self.post(email="a@example.com", reason="why")
        result = self.reissue(email="a@example.com", reason="lost it, verified by reply")
        self.assertEqual((result["kind"], result["revoked_tokens"]), ("comp", 1))
        ends = datetime.fromisoformat(result["expires_at"])
        self.assertAlmostEqual((ends - datetime.now(timezone.utc)).total_seconds(),
                               3650 * 86400, delta=120)
        self.assertIsNone(users_store.authenticate(grant["token"]))
        self.assertEqual(users_store.authenticate(result["token"]).id, grant["user_id"])
        live = [t for t in self.tokens_of(grant["user_id"]) if t[2] is None]
        self.assertEqual(len(live), 1)

    def test_reissue_audit_for_a_comp_has_no_token_and_no_email(self):
        grant = self.post(email="private.person@example.com", reason="why")
        result = self.reissue(user_id=grant["user_id"], reason="lost it, ticket 7")
        rows = [e for e in events.list_events(db=self.db)
                if e.kind == events.SUPPORT_TOKEN_REISSUED]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].properties["kind"], "comp")
        blob = json.dumps(rows[0].properties) + rows[0].user_hash
        for secret in (result["token"], grant["token"], "private.person"):
            self.assertNotIn(secret, blob)

    def test_reissue_works_for_a_comp_who_also_has_a_lapsed_subscription_record(self):
        user = self.lapsed_subscriber()
        self.post(user_id=user.id, reason="friend")
        self.assertEqual(self.reissue(user_id=user.id, reason="lost it")["kind"], "comp")

    def test_reissue_is_refused_once_the_comp_is_revoked(self):
        grant = self.post(email="a@example.com", reason="why")
        self.revoke(user_id=grant["user_id"], reason="done")
        exc = self.refused(self.reissue, user_id=grant["user_id"], reason="lost it")
        self.assertEqual((exc.status_code, exc.detail["error"]), (409, "reissue_refused"))

    def test_the_old_subscriber_reissue_route_does_not_serve_a_free_member(self):
        grant = self.post(email="a@example.com", reason="why")
        exc = self.refused(self.admin.reissue_subscriber_token,
                           body=self.admin.ReissueTokenRequest(user_id=grant["user_id"]),
                           _admin=None)
        self.assertEqual(exc.status_code, 409)


# ---------------------------------------------------------------------------
# The REAL app, over ASGI: every door
# ---------------------------------------------------------------------------

def _asgi(app, method, path, *, headers=None, body=None):
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    payload = b"" if body is None else json.dumps(body).encode()
    if body is not None:
        raw.append((b"content-type", b"application/json"))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
             "query_string": b"", "headers": raw, "client": ("127.0.0.1", 33333),
             "server": ("testserver", 80)}
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
class TheRealApp(_Base):
    @classmethod
    def setUpClass(cls):
        from api.app import app
        cls.app = app

    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {"APP_DB_PATH": str(self.db),
                                           "APP_ADMIN_TOKEN": ADMIN})
        env.start()
        self.addCleanup(env.stop)

    def call(self, method, path, *, token=None, admin=False, body=None):
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if admin:
            headers["X-Admin-Token"] = ADMIN
        return _asgi(self.app, method, path, headers=headers, body=body)

    def comp(self, email="jacob@example.com", reason="early-access signup"):
        status, body = self.call("POST", "/admin/comps", admin=True,
                                 body={"email": email, "reason": reason})
        self.assertEqual(status, 200, body)
        return body

    def test_the_admin_routes_need_the_admin_token_and_say_404_when_it_is_not_configured(self):
        for method, path, body in (("POST", "/admin/comps", {"email": "a@example.com", "reason": "x"}),
                                   ("POST", "/admin/comps/revoke", {"user_id": 1, "reason": "x"}),
                                   ("GET", "/admin/comps", None)):
            with self.subTest(path=path, method=method):
                self.assertEqual(self.call(method, path, body=body)[0], 401)
                bad = _asgi(self.app, method, path, headers={"X-Admin-Token": "wrong"}, body=body)
                self.assertEqual(bad[0], 401)
                with mock.patch.dict(os.environ):
                    os.environ.pop("APP_ADMIN_TOKEN")
                    self.assertEqual(
                        _asgi(self.app, method, path, headers={"X-Admin-Token": ADMIN},
                              body=body)[0], 404)
        self.assertEqual(self.counts()["comps"], 0)

    def test_a_granted_token_opens_the_paid_pages_and_billing_says_free_member(self):
        grant = self.comp()
        status, _ = self.call("GET", "/card", token=grant["token"])
        self.assertNotIn(status, (401, 402, 403))
        status, body = self.call("GET", "/billing/status", token=grant["token"])
        self.assertEqual(status, 200)
        self.assertEqual((body["status"], body["plan"], body["renews"], body["label"]),
                         ("comp", "comp", False, "Free member"))

    def test_a_free_member_never_reaches_checkout_cancel_or_reactivate(self):
        grant = self.comp()
        with mock.patch("src.appstate.billing.get_billing_provider",
                        side_effect=AssertionError("a free member reached a billing provider")):
            for path, body in (("/billing/checkout", {"plan_id": "beta"}),
                               ("/billing/cancel", None), ("/billing/reactivate", None)):
                with self.subTest(path=path):
                    status, answer = self.call("POST", path, token=grant["token"], body=body)
                    self.assertEqual((status, answer["plan"], answer["renews"]), (200, "comp", False))

    def test_a_former_subscriber_with_a_lapsed_record_is_a_402_until_made_a_free_member(self):
        user = self.lapsed_subscriber()
        token = users_store.issue_invite_token(user.id, db=self.db)
        self.assertEqual(self.call("GET", "/card", token=token)[0], 402)
        status, body = self.call("POST", "/admin/comps", admin=True,
                                 body={"user_id": user.id, "reason": "friend"})
        self.assertEqual(status, 200, body)
        self.assertEqual(self.call("GET", "/card", token=token)[0], 401)     # old token revoked
        status, _ = self.call("GET", "/card", token=body["token"])
        self.assertNotIn(status, (401, 402, 403))
        self.assertEqual(self.call("GET", "/billing/status", token=body["token"])[1]["plan"], "comp")

    def test_a_revoke_closes_every_door_at_once(self):
        grant = self.comp()
        status, body = self.call("POST", "/admin/comps/revoke", admin=True,
                                 body={"user_id": grant["user_id"], "reason": "done"})
        self.assertEqual((status, body["revoked_tokens"]), (200, 1))
        for path in ("/card", "/billing/status"):
            self.assertEqual(self.call("GET", path, token=grant["token"])[0], 401, path)
        self.assertEqual(self.call("GET", "/admin/comps", admin=True)[1]["active"], 0)

    def test_a_suspended_free_member_is_turned_away(self):
        grant = self.comp()
        users_store.set_user_status(grant["user_id"], "suspended", db=self.db)
        self.assertEqual(self.call("GET", "/card", token=grant["token"])[0], 401)

    def test_a_live_subscriber_gets_the_structured_409_through_the_app(self):
        user = self.paying_subscriber()
        status, body = self.call("POST", "/admin/comps", admin=True,
                                 body={"user_id": user.id, "reason": "why"})
        self.assertEqual((status, body["detail"]["error"]), (409, "has_subscription"))

    def test_a_lapsed_non_member_stays_a_402_so_the_gate_is_still_a_gate(self):
        user = self.lapsed_subscriber()
        token = users_store.issue_invite_token(user.id, db=self.db)
        from api import auth
        with self.assertRaises(HTTPException) as ctx:
            auth.require_paid_access(current_user=user)
        self.assertEqual(ctx.exception.status_code, 402)
        self.assertEqual(self.call("GET", "/card", token=token)[0], 402)
        comps.grant_comp(user_id=user.id, reason="friend", db=self.db)
        self.assertEqual(auth.require_paid_access(current_user=user).id, user.id)
        comps.revoke_comp(user.id, "done", db=self.db)
        with self.assertRaises(HTTPException) as ctx:
            auth.require_paid_access(current_user=user)
        self.assertEqual(ctx.exception.status_code, 402)


# ---------------------------------------------------------------------------
# "All doors go through it" -- a walk of the real routes and sources
# ---------------------------------------------------------------------------

def _tree(dependant):
    """Every callable in a FastAPI dependant tree."""
    seen = []
    stack = [dependant]
    while stack:
        node = stack.pop()
        if node.call is not None:
            seen.append(node.call)
        stack.extend(node.dependencies)
    return seen


def _walk(routes, inherited=()):
    """(route, every dependency callable that guards it), through include_router.

    FastAPI 0.141 (pinned in api/requirements.txt) keeps an included router as a
    wrapper whose `include_context.dependencies` are the include-time ones
    (`dependencies=_authed_paid` in api/app.py); older versions fold those into
    each route's own dependant. Both are handled, so a FastAPI upgrade that
    changes the shape makes the walk find nothing and the size assertions below
    fail loudly rather than pass on an empty set."""
    for route in routes:
        context = getattr(route, "include_context", None)
        if context is not None:
            deps = list(inherited) + [d.dependency for d in context.dependencies]
            yield from _walk(context.included_router.routes, deps)
        elif hasattr(route, "dependant"):
            yield route, list(inherited) + _tree(route.dependant)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class EveryDoorGoesThroughTheOneCheck(unittest.TestCase):
    """The claim "a comp is honoured everywhere" is only as good as "there is one
    place that decides". These fail if a route is added that gates on the
    subscription its own way."""

    @classmethod
    def setUpClass(cls):
        from api.app import app
        from api import auth
        cls.app, cls.auth = app, auth
        cls.routes = list(_walk(app.routes))

    def test_the_paid_surface_is_gated_by_require_paid_access_and_nothing_else(self):
        gated = [route for route, deps in self.routes if self.auth.require_paid_access in deps]
        self.assertGreater(len(gated), 15, "the paid surface should be a substantial set of routes")
        paths = {r.path for r in gated}
        for must in ("/card", "/ufc/fight-night", "/today"):
            self.assertIn(must, paths)
        # And the gate is the ONLY thing between an authenticated user and the
        # subscription: no route is gated by some other callable that mentions it.
        for route, deps in self.routes:
            names = {getattr(d, "__name__", "") for d in deps
                     if d is not getattr(route, "endpoint", None)}
            self.assertFalse(
                {n for n in names if "paid" in n or "subscri" in n or "entitle" in n}
                - {"require_paid_access", "data_access"},
                route.path)

    def test_every_route_that_has_a_sign_in_door_is_one_the_free_member_passes_through(self):
        authed_only = {route.path for route, deps in self.routes
                       if self.auth.get_current_user in deps
                       and self.auth.require_paid_access not in deps}
        # personal pages: sign-in only, no entitlement, so nothing to be refused by
        for path in ("/billing/status", "/my-bets", "/onboarding"):
            self.assertIn(path, authed_only)

    def test_the_only_entitlement_logic_in_a_dependency_is_require_paid_access(self):
        import inspect
        source = inspect.getsource(self.auth.require_paid_access)
        self.assertIn("customers.has_paid_access(current_user.id)", source)
        self.assertNotIn("has_subscription_access", source)

    def test_no_api_module_decides_entitlement_outside_the_known_ones(self):
        """A module that reads the subscription itself would be a door that a
        free member could be turned away from. The three that may: auth.py (the
        gate), billing.py (the billing pages, which answer a free member first)
        and admin.py (support and revenue)."""
        allowed = {"auth.py", "billing.py", "admin.py"}
        pattern = re.compile(r"get_subscription_record|has_subscription_access|"
                             r"subscription_is_live|entitled_through|billing_subscriptions")
        offenders = sorted(p.name for p in (ROOT / "api").glob("*.py")
                           if p.name not in allowed and pattern.search(p.read_text(encoding="utf-8")))
        self.assertEqual(offenders, [], "route modules must use require_paid_access, not read "
                                        "the subscription themselves")

    def test_every_billing_route_answers_a_free_member_first(self):
        import inspect
        from api import billing
        for fn in (billing.billing_status, billing.create_checkout,
                   billing.cancel_subscription, billing.reactivate_subscription):
            head, _, rest = inspect.getsource(fn).partition('"""')
            source = head + rest.partition('"""')[2]           # the code, without the docstring
            first = source.index("_free_member_body(")
            for later in ("get_subscription_record", "get_billing_provider", "beta_plan_stripe_price_id"):
                if later in source:
                    self.assertLess(first, source.index(later), (fn.__name__, later))

    def test_tester_checkout_and_the_expired_tester_pages_treat_a_free_member_as_entitled(self):
        # They ask has_paid_access, which is now True for a comp, so an expired
        # tester who became a free member is not offered a checkout.
        import inspect
        from src.appstate import tester_upgrade
        for fn in (tester_upgrade.tester_for_token, tester_upgrade.expired_token_window,
                   tester_upgrade.upgrade_state):
            self.assertIn("customers.has_paid_access", inspect.getsource(fn), fn.__name__)


class AnExpiredTesterWhoBecomesAFreeMemberIsNotOfferedACheckout(_Base):
    def test_the_upgrade_paths_all_say_no_to_a_free_member(self):
        from src.appstate import tester_upgrade
        old = testers.grant_tester(email="t@example.com", now=NOW - timedelta(days=20), db=self.db)
        user = users_store.get_user(old.user_id, db=self.db)
        self.assertEqual(tester_upgrade.upgrade_state(user, now=NOW, db=self.db)["state"],
                         tester_upgrade.TESTER_EXPIRED)
        self.assertIsNotNone(tester_upgrade.tester_for_token(old.token, now=NOW, db=self.db))
        comps.grant_comp(user_id=old.user_id, reason="liked it", now=NOW, db=self.db)
        self.assertIsNone(tester_upgrade.upgrade_state(user, now=NOW, db=self.db))
        # the old token is revoked by the grant, so it identifies nobody either
        self.assertIsNone(tester_upgrade.tester_for_token(old.token, now=NOW, db=self.db))
        self.assertIsNone(tester_upgrade.expired_token_window(old.token, now=NOW, db=self.db))


if __name__ == "__main__":
    unittest.main()
