"""src/appstate/customers.py: user<->Stripe customer/subscription
persistence and per-(user, plan) checkout idempotency-key reuse.

Every test uses a temp db file passed explicitly via `db=` -- never the
real data/app/app.db -- the same isolation pattern
tests/test_appstate_users.py uses.
"""

from __future__ import annotations

import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.appstate import customers
from src.appstate import users as users_store


class CustomerMappingTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_mapping_is_none(self):
        self.assertIsNone(customers.get_customer_ref(1, db=self.db))

    def test_upsert_then_lookup_round_trips(self):
        customers.upsert_customer(1, "cus_abc", db=self.db)
        self.assertEqual(customers.get_customer_ref(1, db=self.db), "cus_abc")

    def test_upsert_is_idempotent_and_reuses_not_duplicates(self):
        customers.upsert_customer(1, "cus_abc", db=self.db)
        customers.upsert_customer(1, "cus_abc", db=self.db)
        with customers._connect(self.db) as conn:
            rows = conn.execute("SELECT COUNT(*) AS n FROM billing_customers").fetchone()
        self.assertEqual(rows["n"], 1)

    def test_upsert_overwrites_stripe_id_for_same_user(self):
        customers.upsert_customer(1, "cus_old", db=self.db)
        customers.upsert_customer(1, "cus_new", db=self.db)
        self.assertEqual(customers.get_customer_ref(1, db=self.db), "cus_new")

    def test_reverse_lookup_by_customer_ref(self):
        customers.upsert_customer(9, "cus_xyz", db=self.db)
        self.assertEqual(customers.get_user_id_by_customer_ref("cus_xyz", db=self.db), 9)

    def test_reverse_lookup_unknown_customer_is_none(self):
        self.assertIsNone(customers.get_user_id_by_customer_ref("cus_unknown", db=self.db))

    def test_mappings_are_per_user(self):
        customers.upsert_customer(1, "cus_1", db=self.db)
        customers.upsert_customer(2, "cus_2", db=self.db)
        self.assertEqual(customers.get_customer_ref(1, db=self.db), "cus_1")
        self.assertEqual(customers.get_customer_ref(2, db=self.db), "cus_2")


class SubscriptionRecordTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_record_is_none(self):
        self.assertIsNone(customers.get_subscription_record(1, db=self.db))

    def test_upsert_then_get_round_trips(self):
        customers.upsert_subscription(1, "sub_1", "active", db=self.db)
        record = customers.get_subscription_record(1, db=self.db)
        self.assertEqual(record["stripe_subscription_id"], "sub_1")
        self.assertEqual(record["status"], "active")
        self.assertIsNotNone(record["updated_at"])

    def test_upsert_transitions_status_in_place(self):
        customers.upsert_subscription(1, "sub_1", "active", db=self.db)
        customers.upsert_subscription(1, "sub_1", "canceled", db=self.db)
        record = customers.get_subscription_record(1, db=self.db)
        self.assertEqual(record["status"], "canceled")
        with customers._connect(self.db) as conn:
            rows = conn.execute("SELECT COUNT(*) AS n FROM billing_subscriptions").fetchone()
        self.assertEqual(rows["n"], 1)


class IdempotencyKeyTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._calls = 0

    def tearDown(self):
        self._tmp.cleanup()

    def _generator(self):
        self._calls += 1
        return f"generated-{self._calls}"

    def test_first_call_mints_and_stores_a_key(self):
        key = customers.get_or_create_idempotency_key(1, "beta", self._generator, db=self.db)
        self.assertEqual(key, "generated-1")
        self.assertEqual(self._calls, 1)

    def test_retry_reuses_the_stored_key_without_regenerating(self):
        first = customers.get_or_create_idempotency_key(1, "beta", self._generator, db=self.db)
        second = customers.get_or_create_idempotency_key(1, "beta", self._generator, db=self.db)
        self.assertEqual(first, second)
        self.assertEqual(self._calls, 1, "a reused key must not call the generator again")

    def test_different_plan_for_same_user_gets_its_own_key(self):
        beta_key = customers.get_or_create_idempotency_key(1, "beta", self._generator, db=self.db)
        pro_key = customers.get_or_create_idempotency_key(1, "pro", self._generator, db=self.db)
        self.assertNotEqual(beta_key, pro_key)

    def test_different_user_for_same_plan_gets_its_own_key(self):
        user1_key = customers.get_or_create_idempotency_key(1, "beta", self._generator, db=self.db)
        user2_key = customers.get_or_create_idempotency_key(2, "beta", self._generator, db=self.db)
        self.assertNotEqual(user1_key, user2_key)


class ActivationTokenOneTimeTests(unittest.TestCase):
    """The one-time-retrieval contract of the activation-token bridge --
    GET /signup/complete hands the raw bearer token back exactly once, even
    when two requests for the same (URL-visible) session id arrive at the
    same instant. Regression for the SELECT-then-UPDATE race that let two
    concurrent callers each come away with the same one-time token."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_sequential_retrieval_is_one_time(self):
        customers.record_activation_token("cs_seq", 7, "raw-secret", db=self.db)
        first = customers.take_activation_token("cs_seq", db=self.db)
        self.assertEqual(first, {"user_id": 7, "raw_token": "raw-secret"})
        self.assertIsNone(customers.take_activation_token("cs_seq", db=self.db))

    def test_concurrent_retrieval_yields_exactly_one_winner(self):
        # Two browsers/attempts racing for the same session id (which is
        # visible in the success-page URL) must never both receive the
        # token. Repeated across trials because a race that "usually" holds
        # is not a fix -- the buggy SELECT-then-UPDATE handed the token to
        # both callers in the large majority of trials.
        trials = 60
        workers = 2
        for t in range(trials):
            session_id = f"cs_race_{t}"
            customers.record_activation_token(session_id, 42, "raw-secret", db=self.db)
            barrier = threading.Barrier(workers)
            results: list = []
            lock = threading.Lock()

            def worker():
                barrier.wait()
                got = customers.take_activation_token(session_id, db=self.db)
                with lock:
                    results.append(got)

            threads = [threading.Thread(target=worker) for _ in range(workers)]
            for th in threads:
                th.start()
            for th in threads:
                th.join()

            winners = [r for r in results if r is not None]
            self.assertEqual(
                len(winners), 1,
                f"trial {t}: expected exactly one successful retrieval, "
                f"got {len(winners)} -- the one-time token leaked under a race")
            self.assertEqual(winners[0], {"user_id": 42, "raw_token": "raw-secret"})

    def test_raw_token_is_wiped_after_retrieval_but_row_kept(self):
        customers.record_activation_token("cs_wipe", 3, "raw-secret", db=self.db)
        customers.take_activation_token("cs_wipe", db=self.db)
        # has_activation_token stays True (row kept for webhook-redelivery
        # idempotency) but the raw secret is gone.
        self.assertTrue(customers.has_activation_token("cs_wipe", db=self.db))
        with customers._connect(self.db) as conn:
            row = conn.execute(
                "SELECT raw_token, retrieved_at FROM signup_activation_tokens "
                "WHERE stripe_session_id = ?", ("cs_wipe",)).fetchone()
        self.assertIsNone(row["raw_token"])
        self.assertIsNotNone(row["retrieved_at"])


class ActivationTokenTTLTests(unittest.TestCase):
    """F5: signup_activation_tokens.raw_token had no TTL scrub -- an
    unretrieved row could sit with a raw bearer token in the clear
    forever. Both call sites (has_activation_token, take_activation_token)
    scrub a row older than users_store.DEFAULT_TOKEN_TTL on next touch."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"

    def tearDown(self):
        self._tmp.cleanup()

    def _age_row(self, stripe_session_id: str, age: timedelta) -> None:
        stale_created_at = (datetime.now(timezone.utc) - age).isoformat()
        with customers._connect(self.db) as conn:
            conn.execute(
                "UPDATE signup_activation_tokens SET created_at = ? "
                "WHERE stripe_session_id = ?", (stale_created_at, stripe_session_id))

    def test_aged_unretrieved_token_returns_none_from_take(self):
        customers.record_activation_token("cs_old", 5, "raw-secret", db=self.db)
        self._age_row("cs_old", users_store.DEFAULT_TOKEN_TTL + timedelta(seconds=1))
        result = customers.take_activation_token("cs_old", db=self.db)
        self.assertIsNone(result)

    def test_aged_unretrieved_token_has_its_raw_token_nulled(self):
        customers.record_activation_token("cs_old2", 5, "raw-secret", db=self.db)
        self._age_row("cs_old2", users_store.DEFAULT_TOKEN_TTL + timedelta(seconds=1))
        customers.take_activation_token("cs_old2", db=self.db)
        with customers._connect(self.db) as conn:
            row = conn.execute(
                "SELECT raw_token FROM signup_activation_tokens "
                "WHERE stripe_session_id = ?", ("cs_old2",)).fetchone()
        self.assertIsNone(row["raw_token"])

    def test_expiry_is_also_scrubbed_on_has_activation_token(self):
        """The idempotency-check call site scrubs too, not only take --
        both are named in the fix (see module docstring's SCHEMA note)."""
        customers.record_activation_token("cs_old3", 5, "raw-secret", db=self.db)
        self._age_row("cs_old3", users_store.DEFAULT_TOKEN_TTL + timedelta(seconds=1))
        self.assertTrue(customers.has_activation_token("cs_old3", db=self.db))
        with customers._connect(self.db) as conn:
            row = conn.execute(
                "SELECT raw_token FROM signup_activation_tokens "
                "WHERE stripe_session_id = ?", ("cs_old3",)).fetchone()
        self.assertIsNone(row["raw_token"])

    def test_a_fresh_token_within_ttl_is_not_scrubbed(self):
        customers.record_activation_token("cs_fresh", 6, "raw-secret", db=self.db)
        result = customers.take_activation_token("cs_fresh", db=self.db)
        self.assertEqual(result, {"user_id": 6, "raw_token": "raw-secret"})

    def test_a_token_just_under_the_ttl_is_not_scrubbed(self):
        customers.record_activation_token("cs_edge", 7, "raw-secret", db=self.db)
        self._age_row("cs_edge", users_store.DEFAULT_TOKEN_TTL - timedelta(seconds=5))
        result = customers.take_activation_token("cs_edge", db=self.db)
        self.assertEqual(result, {"user_id": 7, "raw_token": "raw-secret"})

    def test_an_already_retrieved_row_is_left_alone_by_the_scrub(self):
        """The scrub only ever touches an UNRETRIEVED row (retrieved_at IS
        NULL) -- it must never re-stamp retrieved_at on a row a real
        retrieval already claimed, which would be a no-op in practice but
        is not what the scrub is for."""
        customers.record_activation_token("cs_done", 8, "raw-secret", db=self.db)
        customers.take_activation_token("cs_done", db=self.db)
        with customers._connect(self.db) as conn:
            before = conn.execute(
                "SELECT retrieved_at FROM signup_activation_tokens "
                "WHERE stripe_session_id = ?", ("cs_done",)).fetchone()["retrieved_at"]
        self._age_row("cs_done", users_store.DEFAULT_TOKEN_TTL + timedelta(days=1))
        self.assertTrue(customers.has_activation_token("cs_done", db=self.db))
        with customers._connect(self.db) as conn:
            after = conn.execute(
                "SELECT retrieved_at FROM signup_activation_tokens "
                "WHERE stripe_session_id = ?", ("cs_done",)).fetchone()["retrieved_at"]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
