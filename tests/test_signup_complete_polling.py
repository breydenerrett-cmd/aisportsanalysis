"""After Stripe Checkout the buyer lands on #/signup/complete?session_id=... and
the page polls GET /signup/complete until the webhook has minted their token.

The contract this file pins, server side (the page's side is pinned as source
text in tests/test_checkout_to_card_web.py):

  * 404 until the webhook lands, then 200 with the token  (the page polls).
  * A second successful read inside the re-read window returns the SAME token
    (a reload, a lost response, the poll itself) -- a payer is never locked out.
  * The window is measured from the FIRST read and is not extended by re-reads.
  * After the window the session id is dead: 404, and the raw token is wiped
    from the table, so a session id lifted from a log is worth nothing later.
  * The default for take_activation_token (no window) stays strictly one-shot.
  * The webhook's idempotency (has_activation_token) survives the wipe.
  * A paying customer's token outlives the 14-day invite default.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

try:
    from fastapi import HTTPException
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.appstate import billing
from src.appstate import customers
from src.appstate import users as users_store

SESSION = "cs_poll_1"


def _age_first_read(db: Path, session_id: str, minutes: float) -> None:
    stamp = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    with contextlib.closing(sqlite3.connect(str(db))) as conn, conn:
        conn.execute("UPDATE signup_activation_tokens SET retrieved_at = ? "
                     "WHERE stripe_session_id = ?", (stamp, session_id))


def _raw_token_in_table(db: Path, session_id: str):
    with contextlib.closing(sqlite3.connect(str(db))) as conn:
        row = conn.execute("SELECT raw_token FROM signup_activation_tokens "
                           "WHERE stripe_session_id = ?", (session_id,)).fetchone()
    return None if row is None else row[0]


class _DbCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "app.db"
        patcher = mock.patch.object(users_store, "db_path", lambda: self.db)
        patcher.start()
        self.addCleanup(patcher.stop)


class RereadWindowTests(_DbCase):
    def _mint(self, session=SESSION, token="tok_secret_abc"):
        user = users_store.create_user("window@example.com", status="pending_payment")
        customers.record_activation_token(session, user.id, token, db=self.db)
        return user

    def test_default_is_still_strictly_one_shot(self):
        self._mint()
        first = customers.take_activation_token(SESSION, db=self.db)
        self.assertEqual(first["raw_token"], "tok_secret_abc")
        self.assertIsNone(customers.take_activation_token(SESSION, db=self.db))
        self.assertIsNone(_raw_token_in_table(self.db, SESSION))

    def test_second_read_inside_the_window_returns_the_same_token(self):
        user = self._mint()
        window = customers.ACTIVATION_REREAD_WINDOW
        first = customers.take_activation_token(SESSION, reread_window=window, db=self.db)
        again = customers.take_activation_token(SESSION, reread_window=window, db=self.db)
        third = customers.take_activation_token(SESSION, reread_window=window, db=self.db)
        self.assertEqual(first["raw_token"], "tok_secret_abc")
        self.assertEqual(again, first)
        self.assertEqual(third, first)
        self.assertEqual(first["user_id"], user.id)

    def test_window_is_ten_minutes(self):
        self.assertEqual(customers.ACTIVATION_REREAD_WINDOW, timedelta(minutes=10))

    def test_read_after_the_window_is_refused_and_the_token_wiped(self):
        self._mint()
        window = customers.ACTIVATION_REREAD_WINDOW
        customers.take_activation_token(SESSION, reread_window=window, db=self.db)
        _age_first_read(self.db, SESSION, minutes=11)
        self.assertIsNone(
            customers.take_activation_token(SESSION, reread_window=window, db=self.db))
        self.assertIsNone(_raw_token_in_table(self.db, SESSION),
                          "the raw token must not outlive its window in the table")

    def test_just_inside_the_window_still_reads(self):
        self._mint()
        window = customers.ACTIVATION_REREAD_WINDOW
        customers.take_activation_token(SESSION, reread_window=window, db=self.db)
        _age_first_read(self.db, SESSION, minutes=9)
        self.assertIsNotNone(
            customers.take_activation_token(SESSION, reread_window=window, db=self.db))

    def test_rereads_do_not_extend_the_window(self):
        self._mint()
        window = customers.ACTIVATION_REREAD_WINDOW
        customers.take_activation_token(SESSION, reread_window=window, db=self.db)
        _age_first_read(self.db, SESSION, minutes=9)
        customers.take_activation_token(SESSION, reread_window=window, db=self.db)
        # The stamp is still the first read's, so two more minutes closes it.
        _age_first_read(self.db, SESSION, minutes=11)
        self.assertIsNone(
            customers.take_activation_token(SESSION, reread_window=window, db=self.db))

    def test_stale_tokens_are_wiped_by_any_later_activity_not_only_their_own(self):
        """Nobody has to ask again for the secret to be erased: the next
        webhook idempotency check (or any other session's read) sweeps it."""
        self._mint()
        window = customers.ACTIVATION_REREAD_WINDOW
        customers.take_activation_token(SESSION, reread_window=window, db=self.db)
        _age_first_read(self.db, SESSION, minutes=30)
        customers.has_activation_token("cs_somebody_else", db=self.db)
        self.assertIsNone(_raw_token_in_table(self.db, SESSION))

    def test_a_caller_cannot_ask_for_a_longer_window_than_the_constant(self):
        self._mint()
        huge = timedelta(days=30)
        customers.take_activation_token(SESSION, reread_window=huge, db=self.db)
        _age_first_read(self.db, SESSION, minutes=11)
        self.assertIsNone(
            customers.take_activation_token(SESSION, reread_window=huge, db=self.db))

    def test_unknown_and_never_paid_sessions_are_none(self):
        self.assertIsNone(customers.take_activation_token(
            "cs_never", reread_window=customers.ACTIVATION_REREAD_WINDOW, db=self.db))

    def test_the_row_survives_the_wipe_so_a_redelivered_webhook_mints_nothing(self):
        self._mint()
        window = customers.ACTIVATION_REREAD_WINDOW
        customers.take_activation_token(SESSION, reread_window=window, db=self.db)
        _age_first_read(self.db, SESSION, minutes=11)
        customers.take_activation_token(SESSION, reread_window=window, db=self.db)
        self.assertTrue(customers.has_activation_token(SESSION, db=self.db))

    def test_two_racing_first_reads_still_have_one_claimant(self):
        """The atomic claim is unchanged: exactly one call stamps
        retrieved_at; the other is a re-read of it, not a second 'first'."""
        self._mint()
        window = customers.ACTIVATION_REREAD_WINDOW
        customers.take_activation_token(SESSION, reread_window=window, db=self.db)
        with contextlib.closing(sqlite3.connect(str(self.db))) as conn:
            stamp_before = conn.execute(
                "SELECT retrieved_at FROM signup_activation_tokens").fetchone()[0]
        customers.take_activation_token(SESSION, reread_window=window, db=self.db)
        with contextlib.closing(sqlite3.connect(str(self.db))) as conn:
            stamp_after = conn.execute(
                "SELECT retrieved_at FROM signup_activation_tokens").fetchone()[0]
        self.assertEqual(stamp_before, stamp_after)


WEBHOOK_SECRET = "whsec_synthetic_polling_secret"


def _signed(event: dict):
    from tests.test_api_billing import _FakeRequest
    payload = json.dumps(event).encode("utf-8")
    ts = int(datetime.now(timezone.utc).timestamp())
    sig = hmac.new(WEBHOOK_SECRET.encode(), f"{ts}.".encode() + payload,
                   hashlib.sha256).hexdigest()
    return _FakeRequest(payload, {"stripe-signature": f"t={ts},v1={sig}"})


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class EndpointPollingContractTests(_DbCase):
    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {billing.ENV_STRIPE_WEBHOOK_SECRET: WEBHOOK_SECRET})
        env.start()
        self.addCleanup(env.stop)
        self.user = users_store.create_user("poll@example.com", status="pending_payment")

    def _webhook(self):
        import asyncio
        from api.billing import stripe_webhook
        asyncio.run(stripe_webhook(_signed({
            "type": "checkout.session.completed",
            "data": {"object": {"id": SESSION, "client_reference_id": str(self.user.id),
                                "customer": "cus_poll", "subscription": "sub_poll"}},
        })))

    def test_404_until_the_webhook_lands_then_the_token(self):
        from api.signup import signup_complete
        for _ in range(3):       # the page polling while it waits
            with self.assertRaises(HTTPException) as ctx:
                signup_complete(session_id=SESSION)
            self.assertEqual(ctx.exception.status_code, 404)
        self._webhook()
        result = signup_complete(session_id=SESSION)
        self.assertEqual(result["user_id"], self.user.id)
        self.assertTrue(result["token"])

    def test_the_token_works_and_a_reload_gets_the_same_one(self):
        from api.auth import get_current_user
        from api.signup import signup_complete
        self._webhook()
        first = signup_complete(session_id=SESSION)
        reload = signup_complete(session_id=SESSION)
        self.assertEqual(first["token"], reload["token"])
        self.assertEqual(
            get_current_user(authorization=f"Bearer {first['token']}").id, self.user.id)

    def test_replay_after_the_window_is_refused(self):
        from api.signup import signup_complete
        self._webhook()
        signup_complete(session_id=SESSION)
        _age_first_read(self.db, SESSION, minutes=11)
        with self.assertRaises(HTTPException) as ctx:
            signup_complete(session_id=SESSION)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_a_forged_session_id_is_the_same_404(self):
        from api.signup import signup_complete
        self._webhook()
        with self.assertRaises(HTTPException) as ctx:
            signup_complete(session_id="cs_forged_guess")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_a_redelivered_webhook_after_the_wipe_mints_no_second_token(self):
        from api.signup import signup_complete
        self._webhook()
        signup_complete(session_id=SESSION)
        _age_first_read(self.db, SESSION, minutes=11)
        with self.assertRaises(HTTPException):
            signup_complete(session_id=SESSION)
        self._webhook()           # Stripe redelivers
        with self.assertRaises(HTTPException):
            signup_complete(session_id=SESSION)

    def test_subscriber_token_outlives_the_fourteen_day_invite_default(self):
        """A paying customer's token is their login for as long as they pay;
        the 14-day invite TTL locked every subscriber out on day 15 with no
        email sender and no recovery path."""
        from api.signup import signup_complete
        self._webhook()
        token = signup_complete(session_id=SESSION)["token"]
        later = datetime.now(timezone.utc) + timedelta(days=60)
        self.assertIsNotNone(users_store.authenticate(token, now=later))
        way_later = datetime.now(timezone.utc) + timedelta(days=400)
        self.assertIsNone(users_store.authenticate(token, now=way_later))
        self.assertGreater(billing.SUBSCRIBER_TOKEN_TTL, users_store.DEFAULT_TOKEN_TTL)


def _age_created(db: Path, session_id: str, hours: float) -> None:
    stamp = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with contextlib.closing(sqlite3.connect(str(db))) as conn, conn:
        conn.execute("UPDATE signup_activation_tokens SET created_at = ? "
                     "WHERE stripe_session_id = ?", (stamp, session_id))


class UnreadTokensDoNotSitInTheClearTests(_DbCase):
    """A buyer who pays and never opens the completion page used to leave a live
    366-day subscriber token in cleartext indefinitely: the sweep only wiped rows
    that had been READ, and the per-row scrub only ran for the id being asked
    about."""

    def _mint(self, session, token):
        user = users_store.create_user(f"{session}@example.com", status="active")
        customers.record_activation_token(session, user.id, token, db=self.db)
        return user

    def test_the_ttl_is_seventy_two_hours(self):
        self.assertEqual(customers.UNREAD_ACTIVATION_TTL, timedelta(hours=72))

    def test_an_unread_row_older_than_the_ttl_is_wiped_by_an_unrelated_webhook_check(self):
        self._mint("cs_unread", "tok_unread_secret")
        _age_created(self.db, "cs_unread", hours=73)
        customers.has_activation_token("cs_some_other_session", db=self.db)
        self.assertIsNone(_raw_token_in_table(self.db, "cs_unread"))

    def test_an_unread_row_older_than_the_ttl_is_wiped_by_an_unrelated_token_read(self):
        self._mint("cs_unread2", "tok_unread_secret2")
        _age_created(self.db, "cs_unread2", hours=73)
        customers.take_activation_token("cs_other", reread_window=customers.ACTIVATION_REREAD_WINDOW,
                                        db=self.db)
        self.assertIsNone(_raw_token_in_table(self.db, "cs_unread2"))

    def test_an_unread_row_inside_the_ttl_is_kept_and_still_readable(self):
        self._mint("cs_young", "tok_young")
        _age_created(self.db, "cs_young", hours=71)
        customers.has_activation_token("cs_other", db=self.db)
        self.assertEqual(_raw_token_in_table(self.db, "cs_young"), "tok_young")
        got = customers.take_activation_token(
            "cs_young", reread_window=customers.ACTIVATION_REREAD_WINDOW, db=self.db)
        self.assertEqual(got["raw_token"], "tok_young")

    def test_a_wiped_unread_row_reads_as_none_never_as_a_none_token(self):
        self._mint("cs_dead", "tok_dead")
        _age_created(self.db, "cs_dead", hours=100)
        customers.has_activation_token("cs_other", db=self.db)
        self.assertIsNone(customers.take_activation_token(
            "cs_dead", reread_window=customers.ACTIVATION_REREAD_WINDOW, db=self.db))
        self.assertIsNone(customers.take_activation_token("cs_dead", db=self.db))

    def test_the_row_survives_so_a_redelivered_webhook_mints_nothing_new(self):
        self._mint("cs_keep", "tok_keep")
        _age_created(self.db, "cs_keep", hours=100)
        self.assertTrue(customers.has_activation_token("cs_keep", db=self.db))

    def test_the_hashed_token_keeps_working_after_the_raw_copy_is_wiped(self):
        user = users_store.create_user("hashed@example.com", status="active")
        raw = users_store.issue_invite_token(user.id, ttl=billing.SUBSCRIBER_TOKEN_TTL)
        customers.record_activation_token("cs_hashed", user.id, raw, db=self.db)
        _age_created(self.db, "cs_hashed", hours=100)
        customers.has_activation_token("cs_other", db=self.db)
        self.assertIsNone(_raw_token_in_table(self.db, "cs_hashed"))
        self.assertEqual(users_store.authenticate(raw).id, user.id)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class SignupCompleteIsRateLimitedTests(_DbCase):
    class _Req:
        def __init__(self, ip):
            self.client = type("C", (), {"host": "10.0.0.1"})()
            self.headers = {"fly-client-ip": ip}

    def setUp(self):
        super().setUp()
        from api import signup
        self.signup = signup
        signup._complete_limiter._windows.clear()
        self.addCleanup(signup._complete_limiter._windows.clear)

    def test_the_limit_is_thirty_per_minute(self):
        self.assertEqual(self.signup._complete_limiter.limit, 30)
        self.assertEqual(self.signup._complete_limiter.window_s, 60.0)

    def test_one_honest_buyers_whole_poll_loop_is_never_refused(self):
        req = self._Req("203.0.113.9")
        for _ in range(30):      # 60 s / 2 s
            self.signup._rate_limit_signup_complete(req)

    def test_the_thirty_first_call_in_a_minute_is_a_429_and_another_ip_is_unaffected(self):
        req = self._Req("203.0.113.9")
        for _ in range(30):
            self.signup._rate_limit_signup_complete(req)
        with self.assertRaises(HTTPException) as ctx:
            self.signup._rate_limit_signup_complete(req)
        self.assertEqual(ctx.exception.status_code, 429)
        self.signup._rate_limit_signup_complete(self._Req("203.0.113.10"))

    def test_the_route_actually_depends_on_the_limiter(self):
        import inspect
        default = inspect.signature(self.signup.signup_complete).parameters["_rate_limit"].default
        self.assertIs(default.dependency, self.signup._rate_limit_signup_complete)

    def test_the_page_retries_on_a_429(self):
        source = (Path(__file__).resolve().parent.parent / "web" / "js" / "signup.js").read_text(
            encoding="utf-8")
        self.assertIn("err.status === 429", source)
        self.assertIn("if (!(notYet || flaky || throttled)) return { error: err };", source)


if __name__ == "__main__":
    unittest.main()
