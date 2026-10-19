"""api/passwords.py over ASGI against the REAL app: email + password login,
password set/change, logout, and the admin password reset.

The real api.app is driven (not a per-test FastAPI) because the point of several
of these is what the whole stack does with a request: the response headers (no
cookie, no CORS), the request-log line the middleware prints, the 422 FastAPI
would have echoed. Same hand-rolled ASGI call tests/test_api_surface_auth.py
uses (this environment has no HTTP test client), with a body added.

Skipped when FastAPI is not importable, so the Linux CI harness that hides it
skips this module; tests/test_passwords.py is the stdlib half.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.appstate import access
from src.appstate import customers
from src.appstate import events
from src.appstate import passwords
from src.appstate import testers
from src.appstate import users as users_store

ADMIN = "admin-secret-for-tests"
GOOD = "correct horse battery"
NEW = "another long passphrase 42"


def _asgi(app, method, path, *, body=None, raw=None, content_type="application/json",
          headers=None, client=("127.0.0.1", 40000)):
    hdrs = {k.lower(): v for k, v in (headers or {}).items()}
    payload = b""
    if raw is not None:
        payload = raw if isinstance(raw, bytes) else raw.encode()
        hdrs["content-type"] = content_type
    elif body is not None:
        payload = json.dumps(body).encode()
        hdrs["content-type"] = content_type
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
        "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
        "headers": [(k.encode(), v.encode()) for k, v in hdrs.items()],
        "client": client, "server": ("testserver", 80),
    }
    out = {"headers": []}
    parts = []
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": payload, "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            out["status"] = message["status"]
            out["headers"] = [(k.decode().lower(), v.decode()) for k, v in message.get("headers", [])]
        elif message["type"] == "http.response.body":
            parts.append(message.get("body", b""))

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(app(scope, receive, send))
    finally:
        loop.close()
    raw_body = b"".join(parts)
    try:
        out["json"] = json.loads(raw_body)
    except ValueError:
        out["json"] = None
    out["raw"] = raw_body
    return out


def _detail(resp):
    return (resp["json"] or {}).get("detail")


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from api.app import app
        cls.app = app

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "app.db"
        for target, name in ((users_store, "db_path"), (events, "db_path")):
            patcher = mock.patch.object(target, name, lambda: self.db)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {"APP_ADMIN_TOKEN": ADMIN})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(access.unregister_access_source, "comp")
        # The app's middleware prints a log line per request; keep the test run quiet.
        quiet = mock.patch("sys.stderr", io.StringIO())
        quiet.start()
        self.addCleanup(quiet.stop)

    # -- fixtures ---------------------------------------------------------
    def make_member(self, email="member@example.com", password=GOOD, status="invited"):
        user = users_store.create_user(email, status=status, plan="none")
        if password:
            passwords.set_password(user.id, password, email=email)
        return user

    def make_tester(self, email="tester@example.com", password=GOOD, granted=None):
        user = self.make_member(email, password)
        testers.grant_tester(user_id=user.id,
                             now=granted or datetime.now(timezone.utc))
        return users_store.get_user(user.id)

    def make_subscriber(self, email="payer@example.com", password=GOOD):
        user = users_store.create_user(email, status="active", plan="beta")
        customers.upsert_customer(user.id, "cus_%d" % user.id)
        customers.upsert_subscription(
            user.id, "sub_%d" % user.id, "active",
            current_period_end=(datetime.now(timezone.utc) + timedelta(days=20)).isoformat())
        if password:
            passwords.set_password(user.id, password, email=email)
        return user

    # -- calls ------------------------------------------------------------
    def post(self, path, body=None, token=None, **kw):
        headers = dict(kw.pop("headers", {}))
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return _asgi(self.app, "POST", path, body=body, headers=headers, **kw)

    def get(self, path, token=None, headers=None):
        headers = dict(headers or {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return _asgi(self.app, "GET", path, headers=headers)

    def login(self, email, password, **kw):
        return self.post("/auth/login", {"email": email, "password": password}, **kw)

    def admin_post(self, path, body):
        return _asgi(self.app, "POST", path, body=body, headers={"X-Admin-Token": ADMIN})

    def token_rows(self, user_id):
        with users_store._connect() as conn:
            return conn.execute("SELECT * FROM tokens WHERE user_id = ?", (user_id,)).fetchall()

    def all_events(self):
        return events.list_events()


class LoginAccessTests(_Base):

    def test_a_tester_gets_a_token_that_ends_with_the_tester_window(self):
        user = self.make_tester()
        window_end = datetime.fromisoformat(self._window(user.id))
        resp = self.login("Tester@Example.com", GOOD)
        self.assertEqual(resp["status"], 200, resp["json"])
        body = resp["json"]
        self.assertEqual((body["kind"], body["access_active"], body["has_password"]),
                         ("tester", True, True))
        self.assertEqual(datetime.fromisoformat(body["expires_at"]), window_end)
        rows = self.token_rows(user.id)
        issued = [r for r in rows if r["expires_at"] == window_end.isoformat()]
        self.assertTrue(issued, [r["expires_at"] for r in rows])
        # ...and it is a real session: the authed read works with it.
        self.assertEqual(self.get("/auth/password", token=body["token"])["json"],
                         {"has_password": True})

    def _window(self, user_id):
        from src.appstate import tester_upgrade
        return tester_upgrade.tester_window(user_id)["expires_at"]

    def test_a_subscriber_gets_the_usual_subscriber_lifetime(self):
        from src.appstate import billing
        user = self.make_subscriber()
        before = datetime.now(timezone.utc)
        resp = self.login(user.email, GOOD)
        after = datetime.now(timezone.utc)
        self.assertEqual(resp["status"], 200, resp["json"])
        self.assertEqual(resp["json"]["kind"], "subscriber")
        ends = datetime.fromisoformat(resp["json"]["expires_at"])
        self.assertTrue(before + billing.SUBSCRIBER_TOKEN_TTL <= ends <= after + billing.SUBSCRIBER_TOKEN_TTL)
        stored = [r for r in self.token_rows(user.id)]
        self.assertEqual(datetime.fromisoformat(stored[-1]["expires_at"]), ends)

    def test_a_comp_source_registered_at_merge_time_is_honoured(self):
        user = self.make_member("comp@example.com")
        comp_end = datetime.now(timezone.utc) + timedelta(days=366)
        access.register_access_source("comp", lambda u, now: comp_end if u.id == user.id else None)
        resp = self.login(user.email, GOOD)
        self.assertEqual(resp["status"], 200, resp["json"])
        self.assertEqual(resp["json"]["kind"], "comp")
        self.assertEqual(datetime.fromisoformat(resp["json"]["expires_at"]), comp_end)

    def test_an_ended_tester_gets_a_token_that_opens_nothing_and_is_told_so(self):
        user = self.make_tester("old@example.com",
                           granted=datetime.now(timezone.utc) - timedelta(days=30))
        resp = self.login(user.email, GOOD)
        self.assertEqual(resp["status"], 200, resp["json"])
        self.assertFalse(resp["json"]["access_active"])
        self.assertEqual(resp["json"]["kind"], "tester")
        self.assertIsNone(users_store.authenticate(resp["json"]["token"]))
        self.assertEqual(self.get("/auth/password", token=resp["json"]["token"])["status"], 401)

    def test_waitlisted_suspended_lapsed_and_invited_get_a_plain_refusal_and_no_token(self):
        waitlisted = self.make_member("wait@example.com", status="waitlisted")
        pending = self.make_member("pend@example.com", status="pending_payment")
        invited = self.make_member("invited@example.com")
        suspended = self.make_subscriber("susp@example.com")
        users_store.set_user_status(suspended.id, "suspended")
        lapsed = users_store.create_user("lapsed@example.com", status="active", plan="beta")
        customers.upsert_customer(lapsed.id, "cus_l")
        customers.upsert_subscription(lapsed.id, "sub_l", "canceled", current_period_end=None)
        passwords.set_password(lapsed.id, GOOD, email=lapsed.email)
        for user in (waitlisted, pending, invited, suspended, lapsed):
            resp = self.login(user.email, GOOD)
            self.assertEqual(resp["status"], 403, (user.email, resp["json"]))
            self.assertEqual(_detail(resp)["error"], "no_access")
            self.assertNotIn("token", json.dumps(resp["json"]))
            self.assertEqual(len(self.token_rows(user.id)), 0, user.email)

    def test_the_stale_header_a_browser_sends_does_not_matter(self):
        user = self.make_tester()
        resp = self.login(user.email, GOOD, headers={"Authorization": "Bearer expired-or-garbage"})
        self.assertEqual(resp["status"], 200, resp["json"])

    def test_login_does_not_revoke_the_members_other_sessions(self):
        user = self.make_tester()
        first = self.login(user.email, GOOD)["json"]["token"]
        second = self.login(user.email, GOOD)["json"]["token"]
        self.assertNotEqual(first, second)
        self.assertIsNotNone(users_store.authenticate(first))
        self.assertIsNotNone(users_store.authenticate(second))


class NoEnumerationTests(_Base):

    def test_wrong_password_unknown_email_no_password_and_junk_are_one_response(self):
        self.make_tester("real@example.com")
        self.make_member("nopass@example.com", password=None)
        attempts = [
            ("real@example.com", "this is not it at all"),
            ("nobody@example.com", GOOD),
            ("nopass@example.com", GOOD),
            ("", ""), (None, None), (12345, ["x"]), ("not-an-email", GOOD),
        ]
        responses = []
        for i, (email, password) in enumerate(attempts):
            # A distinct client each time so the limiter never interferes.
            resp = self.post("/auth/login", {"email": email, "password": password},
                             client=(f"10.20.0.{i}", 5000))
            responses.append((resp["status"], resp["json"], resp["raw"]))
        self.assertEqual({r[0] for r in responses}, {401}, responses)
        self.assertEqual(len({r[2] for r in responses}), 1,
                         "the wrong-email and wrong-password bodies must be byte-identical")
        self.assertEqual(responses[0][1]["detail"]["error"], "login_failed")
        self.assertEqual(responses[0][1]["detail"]["message"], "That email and password do not match.")

    def test_a_missing_or_wrongly_typed_body_does_not_echo_the_input_back(self):
        resp = self.post("/auth/login", {"email": "a@b.co", "password": {"nested": "SECRET-ECHO-CHECK"}})
        self.assertEqual(resp["status"], 401)
        self.assertNotIn(b"SECRET-ECHO-CHECK", resp["raw"])
        user = self.make_tester()
        token = self.login(user.email, GOOD)["json"]["token"]
        resp = self.post("/auth/password", {"new_password": 1234567890123}, token=token)
        self.assertEqual(resp["status"], 400)
        self.assertEqual(_detail(resp)["error"], "password_rejected")
        self.assertNotIn(b"1234567890123", resp["raw"])

    def test_the_limiter_treats_a_real_and_an_unknown_address_the_same(self):
        self.make_tester("real@example.com")
        for email in ("real@example.com", "ghost@example.com"):
            codes = [self.post("/auth/login", {"email": email, "password": "wrong password"},
                               client=(f"10.30.{hash(email) % 100}.{i}", 5000))["status"]
                     for i in range(12)]
            self.assertEqual(codes, [401] * 10 + [429] * 2, email)


class RateLimitRouteTests(_Base):

    def test_eleventh_attempt_from_one_address_is_a_429_with_a_retry_header(self):
        self.make_tester()
        codes = []
        last = None
        for i in range(11):
            last = self.post("/auth/login", {"email": f"user{i}@example.com", "password": "nope nope nope"})
            codes.append(last["status"])
        self.assertEqual(codes, [401] * 10 + [429])
        self.assertEqual(_detail(last)["error"], "rate_limited")
        retry = dict(last["headers"]).get("retry-after")
        self.assertTrue(retry and 1 <= int(retry) <= 900, retry)
        # The right password from that blocked address is refused too: the gate is first.
        again = self.login("tester@example.com", GOOD)
        self.assertEqual(again["status"], 429)
        # Another address, same member: not blocked by the first one's count.
        self.assertEqual(self.login("tester@example.com", GOOD, client=("10.9.9.9", 1))["status"], 200)

    def test_one_email_from_many_addresses_is_limited_per_email(self):
        self.make_tester()
        codes = [self.login("tester@example.com", "wrong password!", client=(f"10.5.5.{i}", 1))["status"]
                 for i in range(11)]
        self.assertEqual(codes, [401] * 10 + [429])
        self.assertEqual(self.login("tester@example.com", GOOD, client=("10.5.5.200", 1))["status"], 429)

    def test_the_limit_survives_a_restart_because_it_lives_in_the_database(self):
        self.make_tester()
        for i in range(10):
            self.post("/auth/login", {"email": "x@example.com", "password": "wrong one here"})
        # A "redeploy": nothing in memory is carried over, only the file is.
        with mock.patch.object(passwords, "_dummy_record", None):
            self.assertEqual(self.post("/auth/login", {"email": "x@example.com",
                                                       "password": "wrong one here"})["status"], 429)

    def test_an_unreachable_limiter_refuses_rather_than_opens(self):
        user = self.make_tester()
        with mock.patch.object(passwords, "check_and_record_attempt",
                               side_effect=sqlite3.OperationalError("disk I/O error")), \
                contextlib.redirect_stderr(io.StringIO()):
            resp = self.login(user.email, GOOD)
        self.assertEqual(resp["status"], 503)
        self.assertNotIn("token", resp["json"]["detail"])

    def test_password_change_guesses_are_limited_per_account(self):
        user = self.make_tester()
        token = self.login(user.email, GOOD)["json"]["token"]
        codes = [self.post("/auth/password", {"new_password": NEW, "current_password": f"guess number {i}!"},
                           token=token)["status"] for i in range(11)]
        self.assertEqual(codes, [403] * 10 + [429])


class LogoutTests(_Base):

    def test_logout_revokes_the_token_that_made_the_request_and_only_that_one(self):
        user = self.make_tester()
        phone = self.login(user.email, GOOD)["json"]["token"]
        laptop = self.login(user.email, GOOD)["json"]["token"]
        resp = self.post("/auth/logout", token=phone)
        self.assertEqual((resp["status"], resp["json"]), (200, {"ok": True, "revoked": True}))
        self.assertEqual(self.get("/auth/password", token=phone)["status"], 401)
        self.assertEqual(self.get("/auth/password", token=laptop)["status"], 200)
        self.assertEqual(self.post("/auth/logout", token=phone)["status"], 401)

    def test_logout_needs_a_token(self):
        self.assertEqual(self.post("/auth/logout")["status"], 401)


class SetPasswordTests(_Base):

    def token_for(self, user):
        return users_store.issue_invite_token(user.id, ttl=timedelta(days=3))

    def test_a_token_is_enough_to_set_the_first_password_and_then_login_works(self):
        user = self.make_member(password=None)
        testers.grant_tester(user_id=user.id)
        token = self.token_for(user)
        self.assertEqual(self.get("/auth/password", token=token)["json"], {"has_password": False})
        resp = self.post("/auth/password", {"new_password": NEW}, token=token)
        self.assertEqual((resp["status"], resp["json"]),
                         (200, {"ok": True, "has_password": True, "changed": False}))
        self.assertEqual(self.get("/auth/password", token=token)["json"], {"has_password": True})
        self.assertEqual(self.login(user.email, NEW)["status"], 200)

    def test_changing_needs_the_current_password_and_wrong_is_403(self):
        user = self.make_tester()
        token = self.token_for(user)
        missing = self.post("/auth/password", {"new_password": NEW}, token=token)
        self.assertEqual((missing["status"], _detail(missing)["error"]), (400, "current_password_required"))
        wrong = self.post("/auth/password", {"new_password": NEW, "current_password": "not the one"}, token=token)
        self.assertEqual((wrong["status"], _detail(wrong)["error"]), (403, "current_password_wrong"))
        self.assertEqual(self.login(user.email, GOOD)["status"], 200, "unchanged by the failures")
        ok = self.post("/auth/password", {"new_password": NEW, "current_password": GOOD}, token=token)
        self.assertEqual((ok["status"], ok["json"]["changed"]), (200, True))
        self.assertEqual(self.login(user.email, GOOD, client=("10.2.2.2", 1))["status"], 401)
        self.assertEqual(self.login(user.email, NEW, client=("10.2.2.3", 1))["status"], 200)

    def test_the_rules_are_enforced_with_plain_messages(self):
        user = self.make_member(password=None)
        token = self.token_for(user)
        for password, fragment in (("short", "at least 10"), (user.email, "email"),
                                   ("password123", "too common"), (None, "Choose a password")):
            resp = self.post("/auth/password", {"new_password": password}, token=token)
            self.assertEqual(resp["status"], 400, password)
            self.assertEqual(_detail(resp)["error"], "password_rejected")
            self.assertIn(fragment, _detail(resp)["message"])
        self.assertFalse(passwords.has_password(user.id))

    def test_it_needs_a_valid_token(self):
        self.assertEqual(self.post("/auth/password", {"new_password": NEW})["status"], 401)
        self.assertEqual(self.get("/auth/password")["status"], 401)
        self.assertEqual(self.post("/auth/password", {"new_password": NEW}, token="nope")["status"], 401)


class AdminResetTests(_Base):

    def reset(self, **body):
        return self.admin_post("/admin/users/password-reset", body)

    def test_it_is_unreachable_without_the_admin_token(self):
        user = self.make_tester()
        no_header = _asgi(self.app, "POST", "/admin/users/password-reset",
                          body={"user_id": user.id, "reason": "ticket 1"})
        wrong = _asgi(self.app, "POST", "/admin/users/password-reset",
                      body={"user_id": user.id, "reason": "ticket 1"}, headers={"X-Admin-Token": "nope"})
        self.assertEqual((no_header["status"], wrong["status"]), (401, 401))
        self.assertTrue(passwords.has_password(user.id))
        with mock.patch.dict(os.environ, {"APP_ADMIN_TOKEN": ""}):
            off = _asgi(self.app, "POST", "/admin/users/password-reset",
                        body={"user_id": user.id, "reason": "ticket 1"}, headers={"X-Admin-Token": ADMIN})
        self.assertEqual(off["status"], 404)

    def test_it_clears_the_password_audits_it_and_returns_no_secret(self):
        user = self.make_tester()
        resp = self.reset(user_id=user.id, reason="verified by reply from the mailbox, ticket 41")
        self.assertEqual(resp["status"], 200, resp["json"])
        self.assertEqual(set(resp["json"]), {"user_id", "had_password", "cleared", "next_step"})
        self.assertTrue(resp["json"]["had_password"])
        self.assertFalse(passwords.has_password(user.id))
        blob = resp["raw"].decode().lower()
        for forbidden in (GOOD, "scrypt", "salt", "hash"):
            self.assertNotIn(forbidden, blob)
        rows = [e for e in self.all_events() if e.kind == events.SUPPORT_PASSWORD_RESET]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].user_hash, events.hash_user_id(user.id))
        self.assertEqual(rows[0].properties, {"action": "password_reset", "had_password": True,
                                              "reason": "verified by reply from the mailbox, ticket 41"})
        self.assertNotIn(user.email, json.dumps(rows[0].properties))
        # The old password no longer signs in.
        self.assertEqual(self.login(user.email, GOOD)["status"], 401)

    def test_the_recovery_path_end_to_end(self):
        user = self.make_tester()
        self.reset(email=user.email, reason="ticket 42, mailbox reply")
        reissued = self.admin_post("/admin/users/reissue", {"user_id": user.id, "reason": "ticket 42"})
        self.assertEqual(reissued["status"], 200, reissued["json"])
        token = reissued["json"]["token"]
        self.assertEqual(self.post("/auth/password", {"new_password": NEW}, token=token)["status"], 200)
        self.assertEqual(self.login(user.email, NEW)["status"], 200)

    def test_a_reset_for_a_member_with_no_password_still_succeeds_and_says_so(self):
        user = self.make_member(password=None)
        resp = self.reset(user_id=user.id, reason="ticket 43")
        self.assertEqual((resp["status"], resp["json"]["had_password"]), (200, False))

    def test_refusals(self):
        user = self.make_tester()
        self.assertEqual(self.reset(user_id=999, reason="ticket 1")["status"], 409)
        self.assertEqual(self.reset(user_id=2 ** 70, reason="ticket 1")["status"], 409)
        self.assertEqual(self.reset(email="ghost@example.com", reason="ticket 1")["status"], 409)
        self.assertEqual(self.reset(user_id=user.id)["status"], 400)
        self.assertEqual(self.reset(reason="ticket 1")["status"], 400)
        self.assertEqual(self.reset(user_id=user.id, email=user.email, reason="x")["status"], 400)
        for secret in ("password: hunter2hunter2", "token=abc", "A" * 40, "x" * 501):
            resp = self.reset(user_id=user.id, reason=secret)
            self.assertEqual(resp["status"], 400, secret)
        self.assertTrue(passwords.has_password(user.id), "no refusal may clear anything")

    def test_a_failed_audit_write_leaves_the_password_in_place(self):
        user = self.make_tester()
        with mock.patch("api.passwords._write_audit", side_effect=sqlite3.OperationalError("full")), \
                contextlib.redirect_stderr(io.StringIO()):
            resp = self.reset(user_id=user.id, reason="ticket 9")
        self.assertEqual(resp["status"], 503)
        self.assertTrue(passwords.has_password(user.id))


class NothingSecretIsLoggedTests(_Base):

    def test_no_password_hash_or_token_in_events_or_in_anything_printed(self):
        secret_a, secret_b = "violet-anchor-pinwheel-9931", "mossy-lantern-orbit-4420"
        out, err = io.StringIO(), io.StringIO()
        user = self.make_tester("logcheck@example.com", password=None)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            token = users_store.issue_invite_token(user.id, ttl=timedelta(days=3))
            self.post("/auth/password", {"new_password": secret_a}, token=token)
            self.post("/auth/password", {"new_password": secret_b, "current_password": secret_a}, token=token)
            self.login(user.email, "bad-guess-for-logs-77")
            self.login("nobody@example.com", "bad-guess-for-logs-78")
            session = self.login(user.email, secret_b, client=("10.4.4.4", 1))["json"]["token"]
            self.post("/auth/logout", token=session)
            self.admin_post("/admin/users/password-reset", {"user_id": user.id, "reason": "ticket 5"})
            # A server fault in the middle of a sign-in must not print the password either.
            with mock.patch.object(passwords, "authenticate_password",
                                   side_effect=RuntimeError("boom")):
                self.login(user.email, secret_b, client=("10.4.4.5", 1))
        printed = out.getvalue() + err.getvalue()
        with passwords._connect() as conn:
            conn.row_factory = sqlite3.Row
            dump = json.dumps([dict(r) for r in conn.execute("SELECT * FROM analytics_events")])
            dump += json.dumps([dict(r) for r in conn.execute("SELECT * FROM login_attempts")])
        record = passwords.hash_password(secret_a)  # a stand-in for "a hash": nothing like it is logged
        self.assertTrue(printed.strip(), "the request log lines should have been captured")
        for needle in (secret_a, secret_b, "bad-guess-for-logs-77", "bad-guess-for-logs-78",
                       token, session, user.email, "nobody@example.com"):
            self.assertNotIn(needle, printed, "printed output leaked a secret")
            self.assertNotIn(needle, dump, "the events or attempts table leaked a secret")
        self.assertNotIn(record.params, dump)
        with passwords._connect() as conn:
            stored = conn.execute("SELECT hash, salt FROM user_passwords").fetchall()
        # The reset deleted the row; nothing about a hash may have been kept in events either.
        self.assertEqual(stored, [])
        self.assertNotIn("scrypt", dump)

    def test_events_for_login_carry_no_email_and_failures_are_anonymous(self):
        user = self.make_tester()
        self.login(user.email, "wrong password!!")
        self.login("ghost@example.com", "wrong password!!", client=("10.6.6.6", 1))
        self.login(user.email, GOOD, client=("10.6.6.7", 1))
        kinds = [(e.kind, e.user_hash, e.properties) for e in self.all_events()
                 if e.kind in (events.LOGIN_FAILED, events.LOGIN_SUCCEEDED)]
        failed = [k for k in kinds if k[0] == events.LOGIN_FAILED]
        self.assertEqual(len(failed), 2)
        self.assertEqual({f[1] for f in failed}, {events.hash_user_id(events.LOGIN_ANONYMOUS_USER_ID)},
                         "a wrong password and an unknown address must leave identical traces")
        self.assertEqual(failed[0][2], failed[1][2])
        ok = [k for k in kinds if k[0] == events.LOGIN_SUCCEEDED]
        self.assertEqual(len(ok), 1)
        self.assertEqual(ok[0][1], events.hash_user_id(user.id))
        self.assertEqual(ok[0][2], {"method": "password", "kind": "tester"})
        self.assertNotIn("example.com", json.dumps(kinds))

    def test_the_new_kinds_are_not_open_to_the_public_beacon(self):
        from api import funnel
        for kind in (events.LOGIN_SUCCEEDED, events.LOGIN_FAILED, events.PASSWORD_SET,
                     events.SUPPORT_PASSWORD_RESET):
            self.assertIn(kind, events.EVENT_KINDS)
            self.assertNotIn(kind, funnel.PUBLIC_FUNNEL_KINDS)


class CsrfStanceTests(_Base):
    """api/passwords.py documents why there is no CSRF token. These pin the facts
    that reasoning stands on."""

    def test_no_response_from_any_of_these_routes_sets_a_cookie(self):
        user = self.make_tester()
        token = self.login(user.email, GOOD)["json"]["token"]
        responses = [
            self.login(user.email, GOOD, client=("10.8.8.1", 1)),
            self.login(user.email, "wrong password!", client=("10.8.8.2", 1)),
            self.get("/auth/password", token=token),
            self.post("/auth/password", {"new_password": NEW, "current_password": GOOD}, token=token),
            self.post("/auth/logout", token=token),
            self.admin_post("/admin/users/password-reset", {"user_id": user.id, "reason": "ticket 2"}),
        ]
        for resp in responses:
            self.assertNotIn("set-cookie", dict(resp["headers"]))

    def test_a_form_post_or_text_plain_post_cannot_log_anyone_in(self):
        user = self.make_tester()
        before = len(self.token_rows(user.id))
        form = self.post("/auth/login", raw=f"email={user.email}&password={GOOD}",
                         content_type="application/x-www-form-urlencoded")
        plain = self.post("/auth/login", raw=json.dumps({"email": user.email, "password": GOOD}),
                          content_type="text/plain")
        for resp in (form, plain):
            self.assertGreaterEqual(resp["status"], 400, resp["json"])
            self.assertNotIn(b'"token"', resp["raw"])
        self.assertEqual(len(self.token_rows(user.id)), before)

    def test_no_cors_headers_are_ever_sent_so_a_cross_origin_json_post_never_gets_a_preflight(self):
        user = self.make_tester()
        pre = _asgi(self.app, "OPTIONS", "/auth/login", headers={
            "Origin": "https://evil.example", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type"})
        resp = self.login(user.email, GOOD, headers={"Origin": "https://evil.example"})
        for r in (pre, resp):
            names = {k for k, _ in r["headers"]}
            self.assertFalse({n for n in names if n.startswith("access-control-")}, names)
        self.assertGreaterEqual(pre["status"], 400)

    def test_the_stance_is_written_down_where_the_next_reader_will_look(self):
        import api.passwords as module
        self.assertIn("CSRF STANCE", module.__doc__)
        self.assertIn("no cookie", module.__doc__.lower())


if __name__ == "__main__":
    unittest.main()
