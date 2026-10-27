"""An ended tester who only ever had the access code (no password) continues as a
FREE member: POST /auth/continue-free trades the ended code for a free session
(owner ruling 2026-10-27), keeping the kennel, never reaching the paid board.

Real app over ASGI, temp database, time injected by backdating the tester grant
(the same way tests/test_api_passwords.py does). Skipped without FastAPI.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from src.appstate import access, customers, events, passwords, testers
from src.appstate import users as users_store
from tests.test_api_passwords import HAS_FASTAPI, _Base, _detail

NOW = datetime.now(timezone.utc)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class ContinueFree(_Base):
    def ended_tester(self, email="old@example.com", days_ago=30):
        """A tester granted `days_ago` days back (window ended days_ago-7 ago);
        returns (user, the ORIGINAL access code), with no password set."""
        user = users_store.create_user(email, status="invited", plan="none")
        raw = testers.grant_tester(user_id=user.id, now=NOW - timedelta(days=days_ago))
        return users_store.get_user(user.id), raw.token

    def cont(self, token, **kw):
        return self.post("/auth/continue-free", token=token, **kw)

    def test_an_ended_code_is_traded_for_a_free_session(self):
        user, code = self.ended_tester()
        self.assertIsNone(users_store.authenticate(code))          # dead today
        resp = self.cont(code)
        self.assertEqual(resp["status"], 200, resp["json"])
        self.assertEqual((resp["json"]["kind"], resp["json"]["access_active"]), ("free", True))
        new = resp["json"]["token"]
        self.assertNotEqual(new, code)
        self.assertEqual(self.get("/auth/password", token=new)["status"], 200)   # member route
        paid = self.get("/digest", token=new)
        self.assertEqual(paid["status"], 403, paid)                # never the paid board
        self.assertEqual(_detail(paid)["error"], "paid_access_required")
        self.assertEqual(access.access_level(users_store.get_user(user.id)), access.LEVEL_MEMBER)

    def test_the_old_code_is_dead_after_the_exchange_and_cannot_be_reused(self):
        _user, code = self.ended_tester()
        self.assertEqual(self.cont(code)["status"], 200)
        again = self.cont(code)
        self.assertEqual(again["status"], 401)
        self.assertEqual(_detail(again)["error"], "continue_unavailable")
        self.assertEqual(self.get("/auth/password", token=code)["status"], 401)

    def test_the_event_names_no_token_or_email(self):
        user, code = self.ended_tester()
        new = self.cont(code)["json"]["token"]
        dump = repr([(e.user_hash, e.kind, e.properties) for e in self.all_events()])
        for secret in (code, new, user.email):
            self.assertNotIn(secret, dump)
        self.assertIn("continue_free", dump)

    def test_a_tester_with_an_open_window_cannot_trade(self):
        user = users_store.create_user("open@example.com", status="invited", plan="none")
        code = testers.grant_tester(user_id=user.id, now=NOW)
        code = code.token
        self.assertEqual(self.cont(code)["status"], 401)
        self.assertIsNotNone(users_store.authenticate(code))        # and it still works as itself

    def test_a_revoked_code_is_refused(self):
        _user, code = self.ended_tester()
        users_store.revoke_token(code)
        self.assertEqual(self.cont(code)["status"], 401)

    def test_a_suspended_account_is_refused(self):
        user, code = self.ended_tester()
        users_store.set_user_status(user.id, "suspended")
        self.assertEqual(self.cont(code)["status"], 401)

    def test_a_lapsed_subscriber_is_refused(self):
        user, code = self.ended_tester()
        customers.upsert_customer(user.id, "cus_x")
        customers.upsert_subscription(user.id, "sub_x", "canceled", current_period_end=None)
        self.assertEqual(self.cont(code)["status"], 401)

    def test_a_code_expired_longer_than_the_bound_is_refused(self):
        _user, code = self.ended_tester(days_ago=7 + 91)
        self.assertEqual(self.cont(code)["status"], 401)
        _user2, code2 = self.ended_tester("fresh@example.com", days_ago=7 + 89)
        self.assertEqual(self.cont(code2)["status"], 200)

    def test_a_random_or_missing_code_is_the_same_401(self):
        for token in ("x" * 43, None):
            resp = self.cont(token)
            self.assertEqual(resp["status"], 401)
            self.assertEqual(_detail(resp)["error"], "continue_unavailable")

    def test_a_support_revoked_older_code_is_refused_but_the_reissued_one_is_already_free(self):
        user, code = self.ended_tester()
        reissued = self.admin_post("/admin/users/reissue",
                                   {"user_id": user.id, "reason": "verified from mailbox, ticket 7"})
        self.assertEqual(reissued["status"], 200, reissued["json"])
        self.assertEqual(reissued["json"]["kind"], "free")
        self.assertEqual(self.cont(code)["status"], 401)           # revoked by the re-issue
        token = reissued["json"]["token"]
        self.assertEqual(self.get("/auth/password", token=token)["status"], 200)
        self.assertEqual(self.get("/digest", token=token)["status"], 403)

    def test_repeated_wrong_codes_are_rate_limited(self):
        codes = [self.cont("y" * 43, client=("10.7.7.7", 1))["status"] for _ in range(12)]
        self.assertEqual(codes[:10], [401] * 10)
        self.assertEqual(codes[-1], 429)


if __name__ == "__main__":
    unittest.main()
