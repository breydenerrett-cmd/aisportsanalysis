"""Forgot password: POST /auth/password/forgot, POST /auth/password/reset and the admin fallback link.

Story pinned here (owner ask 2026-10-29): a member who forgot a password, or whose account was made by the admin
with none (a comp or tester), gets a single-use 30 minute link; the answer never reveals whether an account exists;
only a sha256 of the token is stored; with no email provider the owner can make the link from People instead.

The stdlib half (src/appstate/password_reset.py) runs without FastAPI; the HTTP half skips when it is missing.
"""

from __future__ import annotations

import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.appstate import password_reset
from src.appstate import passwords
from src.appstate import users as users_store

try:
    from tests.test_api_passwords import _Base, GOOD, NEW, ADMIN, _asgi
    HAS_HTTP = True
except ImportError:      # no FastAPI on this image
    HAS_HTTP = False

NEUTRAL = "If that email has an account, a reset link is on its way."


class TokenStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "app.db"
        self.user = users_store.create_user("a@example.com", db=self.db)

    def test_only_the_hash_is_stored(self):
        raw, _ = password_reset.create_token(self.user.id, db=self.db)
        with users_store._connect(self.db) as conn:
            rows = conn.execute("SELECT * FROM password_reset_tokens").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertNotIn(raw, "|".join(str(v) for v in tuple(rows[0])))
        self.assertEqual(rows[0]["token_hash"], password_reset.hash_token(raw))

    def test_single_use(self):
        raw, _ = password_reset.create_token(self.user.id, db=self.db)
        self.assertEqual(password_reset.consume_token(raw, db=self.db), self.user.id)
        self.assertIsNone(password_reset.consume_token(raw, db=self.db))

    def test_expires_after_thirty_minutes(self):
        now = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
        raw, ends = password_reset.create_token(self.user.id, now=now, db=self.db)
        self.assertEqual(ends - now, timedelta(minutes=30))
        self.assertIsNone(password_reset.consume_token(raw, now=now + timedelta(minutes=30), db=self.db))
        raw2, _ = password_reset.create_token(self.user.id, now=now, db=self.db)
        self.assertEqual(password_reset.consume_token(raw2, now=now + timedelta(minutes=29), db=self.db),
                         self.user.id)

    def test_a_new_request_replaces_the_old_link(self):
        first, _ = password_reset.create_token(self.user.id, db=self.db)
        second, _ = password_reset.create_token(self.user.id, db=self.db)
        self.assertIsNone(password_reset.live_owner(first, db=self.db))
        self.assertEqual(password_reset.live_owner(second, db=self.db), self.user.id)

    def test_garbage_is_not_a_token(self):
        for bad in (None, "", 5, "x" * 500, ["a"]):
            self.assertIsNone(password_reset.consume_token(bad, db=self.db))


@unittest.skipUnless(HAS_HTTP, "fastapi not installed")
class ForgotRouteTests(_Base if HAS_HTTP else unittest.TestCase):
    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {"PUBLIC_BASE_URL": "https://example.test"})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("RESEND_API_KEY", None)

    def forgot(self, email, **kw):
        return self.post("/auth/password/forgot", {"email": email}, **kw)

    def reset_rows(self):
        with users_store._connect() as conn:
            password_reset.ensure_schema(conn)
            return conn.execute("SELECT * FROM password_reset_tokens").fetchall()

    def capture_email(self):
        sent = []

        def fake_send(message, **kw):
            sent.append(message)
            return {"status": "sent", "http": 200, "id": "x", "to": "m***@e***.com"}
        patcher = mock.patch("api.passwords.mail.send", fake_send)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {"RESEND_API_KEY": "re_test_key"})
        env.start()
        self.addCleanup(env.stop)
        return sent

    @staticmethod
    def token_in(message):
        found = re.search(r"/web/#/reset\?token=([\w-]+)", message["text"])
        return found.group(1)

    # -- neutral answer ---------------------------------------------------
    def test_the_answer_is_identical_for_every_kind_of_address(self):
        self.make_member("has@example.com")
        self.make_member("nopw@example.com", password=None)
        answers = []
        for address in ("has@example.com", "nopw@example.com", "nobody@example.com", "not an email", ""):
            resp = self.forgot(address)
            answers.append((resp["status"], resp["json"]))
        self.assertEqual(len(set(map(repr, answers))), 1, answers)
        self.assertEqual(answers[0], (200, {"ok": True, "message": NEUTRAL}))
        self.assertEqual(self.forgot(None)["json"]["message"], NEUTRAL)

    def test_unknown_address_makes_no_token(self):
        self.forgot("nobody@example.com")
        self.assertEqual(self.reset_rows(), [])

    # -- rate limits ------------------------------------------------------
    def test_rate_limited_per_email(self):
        for _ in range(3):
            self.assertEqual(self.forgot("a@example.com")["status"], 200)
        resp = self.forgot("a@example.com")
        self.assertEqual(resp["status"], 429)
        # another address from the same client is still fine
        self.assertEqual(self.forgot("b@example.com")["status"], 200)

    def test_rate_limited_per_ip(self):
        for i in range(10):
            self.assertEqual(self.forgot(f"u{i}@example.com")["status"], 200)
        self.assertEqual(self.forgot("u99@example.com")["status"], 429)
        other = self.forgot("u99@example.com", client=("10.9.9.9", 1))
        self.assertEqual(other["status"], 200)

    # -- email path -------------------------------------------------------
    def test_with_a_provider_the_link_is_emailed_and_only_a_hash_is_kept(self):
        user = self.make_member("m@example.com")
        sent = self.capture_email()
        self.forgot("M@Example.com")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["to"], "m@example.com")
        raw = self.token_in(sent[0])
        self.assertIn("https://example.test/web/#/reset?token=" + raw, sent[0]["html"])
        rows = self.reset_rows()
        self.assertEqual([r["user_id"] for r in rows], [user.id])
        self.assertNotIn(raw, "|".join(str(v) for v in tuple(rows[0])))

    def test_without_a_provider_it_logs_a_safe_line_and_makes_nothing_leak(self):
        self.make_member("m@example.com")
        with self.assertLogs("linehound.password_reset", level="WARNING") as logs:
            resp = self.forgot("m@example.com")
        self.assertEqual(resp["json"]["message"], NEUTRAL)
        text = " ".join(logs.output)
        self.assertIn("no email provider", text)
        self.assertNotIn("m@example.com", text)
        for row in self.reset_rows():
            self.assertNotIn(row["token_hash"][:12], text)

    # -- reset ------------------------------------------------------------
    def link_for(self, email):
        sent = self.capture_email()
        self.forgot(email)
        return self.token_in(sent[-1])

    def test_reset_sets_the_password_and_ends_other_sessions(self):
        user = self.make_tester("m@example.com")
        old = users_store.issue_invite_token(user.id)
        raw = self.link_for("m@example.com")
        resp = self.post("/auth/password/reset", {"token": raw, "new_password": NEW})
        self.assertEqual(resp["status"], 200, resp["json"])
        self.assertTrue(resp["json"]["has_password"])
        self.assertIsNone(users_store.authenticate(old))
        self.assertEqual(self.login("m@example.com", NEW)["status"], 200)
        self.assertEqual(self.login("m@example.com", GOOD)["status"], 401)

    def test_the_link_works_once(self):
        self.make_member("m@example.com")
        raw = self.link_for("m@example.com")
        self.assertEqual(self.post("/auth/password/reset", {"token": raw, "new_password": NEW})["status"], 200)
        again = self.post("/auth/password/reset", {"token": raw, "new_password": "yet another phrase 77"})
        self.assertEqual(again["status"], 400)
        self.assertEqual(_detail(again)["error"], "reset_link_invalid")

    def test_a_weak_password_does_not_burn_the_link(self):
        self.make_member("m@example.com")
        raw = self.link_for("m@example.com")
        weak = self.post("/auth/password/reset", {"token": raw, "new_password": "short"})
        self.assertEqual((weak["status"], _detail(weak)["error"]), (400, "password_rejected"))
        common = self.post("/auth/password/reset", {"token": raw, "new_password": "password1234"})
        self.assertEqual(_detail(common)["error"], "password_rejected")
        self.assertEqual(self.post("/auth/password/reset", {"token": raw, "new_password": NEW})["status"], 200)

    def test_an_expired_or_made_up_link_is_refused(self):
        user = self.make_member("m@example.com")
        raw, _ = password_reset.create_token(user.id, now=datetime.now(timezone.utc) - timedelta(minutes=31))
        for token in (raw, "made-up", None, 7):
            resp = self.post("/auth/password/reset", {"token": token, "new_password": NEW})
            self.assertEqual((resp["status"], _detail(resp)["error"]), (400, "reset_link_invalid"))

    def test_an_account_with_no_password_can_set_its_first_one(self):
        """The musicbybrey story: an admin-made account has no password, so sign-in says 'do not match'."""
        user = self.make_member("music@example.com", password=None, status="active")
        self.assertEqual(self.login("music@example.com", NEW)["status"], 401)
        raw = self.link_for("music@example.com")
        self.assertEqual(self.post("/auth/password/reset", {"token": raw, "new_password": NEW})["status"], 200)
        self.assertTrue(passwords.has_password(user.id))

    def test_a_comp_keeps_access_and_lands_signed_in(self):
        from src.appstate import comps
        user = self.make_member("comp@example.com", password=None, status="active")
        comps.grant_comp_direct(email="comp@example.com", reason="friend of the house")
        raw = self.link_for("comp@example.com")
        resp = self.post("/auth/password/reset", {"token": raw, "new_password": NEW})
        self.assertEqual(resp["status"], 200, resp["json"])
        self.assertTrue(resp["json"]["access_active"])
        self.assertEqual(self.get("/auth/password", token=resp["json"]["token"])["json"], {"has_password": True})
        self.assertEqual(self.login("comp@example.com", NEW)["status"], 200)

    # -- admin fallback ---------------------------------------------------
    def test_admin_link_needs_the_admin_token(self):
        user = self.make_member("m@example.com")
        resp = _asgi(self.app, "POST", "/admin/users/password-reset-link",
                     body={"user_id": user.id, "reason": "verified"})
        self.assertIn(resp["status"], (401, 403))

    def test_admin_link_is_shown_once_and_works(self):
        user = self.make_member("m@example.com")
        resp = self.admin_post("/admin/users/password-reset-link", {"user_id": user.id, "reason": "ticket 12"})
        self.assertEqual(resp["status"], 200, resp["json"])
        link = resp["json"]["link"]
        self.assertTrue(link.startswith("https://example.test/web/#/reset?token="))
        raw = link.split("token=", 1)[1]
        for row in self.reset_rows():
            self.assertNotIn(raw, "|".join(str(v) for v in tuple(row)))
        audit = [e for e in self.all_events() if "reset_link" in str(e)]
        self.assertTrue(audit)
        self.assertNotIn(raw, str(self.all_events()))
        self.assertEqual(self.post("/auth/password/reset", {"token": raw, "new_password": NEW})["status"], 200)

    def test_admin_link_refuses_unknown_accounts_and_missing_reasons(self):
        self.assertEqual(self.admin_post("/admin/users/password-reset-link",
                                         {"email": "ghost@example.com", "reason": "x"})["status"], 409)
        user = self.make_member("m@example.com")
        self.assertEqual(self.admin_post("/admin/users/password-reset-link",
                                         {"user_id": user.id, "reason": " "})["status"], 400)


def _detail(resp):
    return (resp["json"] or {}).get("detail")


if __name__ == "__main__":
    unittest.main()
