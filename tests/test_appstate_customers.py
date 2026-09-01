"""src/appstate/customers.py: user<->Stripe customer/subscription
persistence and per-(user, plan) checkout idempotency-key reuse.

Every test uses a temp db file passed explicitly via `db=` -- never the
real data/app/app.db -- the same isolation pattern
tests/test_appstate_users.py uses.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.appstate import customers


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


if __name__ == "__main__":
    unittest.main()
