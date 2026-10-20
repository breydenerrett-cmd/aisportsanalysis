"""The founding-member offer (owner decision 2026-10-20): $14.99/mo for the first 50, $19.99 after.

Covers the seat counter (src/appstate/founding.py), price selection (billing.choose_checkout_price),
the public offer body (billing.founding_offer and GET /billing/offer) and the webhook path that makes a
seat real. The src-level tests need no FastAPI (CI is Python 3.10 without it); the endpoint tests skip
without it.
"""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.appstate import billing, customers, founding
from src.appstate import users as users_store

NOW = 1_800_000_000
FOUNDING_PRICE = "price_founding_test"
STANDARD_PRICE = "price_standard_test"


class _Db(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        patcher = mock.patch.object(users_store, "db_path", lambda: self.db)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {
            billing.ENV_STRIPE_BETA_PRICE_ID: STANDARD_PRICE,
            billing.ENV_STRIPE_FOUNDING_PRICE_ID: FOUNDING_PRICE}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self._tmp.cleanup)

    def take(self, n, start=1000):
        """n live founding subscriptions, as the webhooks would have recorded them."""
        for i in range(n):
            founding.record_subscription(start + i, f"sub_{start + i}", "active", NOW, now=NOW, db=self.db)


class SeatCounting(_Db):
    def test_only_live_founding_subscriptions_are_taken(self):
        founding.record_subscription(1, "sub_1", "active", NOW, now=NOW, db=self.db)
        founding.record_subscription(2, "sub_2", "trialing", NOW, now=NOW, db=self.db)
        founding.record_subscription(3, "sub_3", "canceled", NOW, now=NOW, db=self.db)
        self.assertEqual(founding.seat_counts(now=NOW, db=self.db), {"taken": 2, "reserved": 0})

    def test_a_pending_checkout_reserves_but_is_never_counted_as_taken(self):
        self.assertIsNotNone(founding.try_reserve(7, now=NOW, db=self.db))
        self.assertEqual(founding.seat_counts(now=NOW, db=self.db), {"taken": 0, "reserved": 1})

    def test_seat_fifty_cannot_be_sold_twice(self):
        self.take(49)
        first = founding.try_reserve(5001, now=NOW, db=self.db)
        second = founding.try_reserve(5002, now=NOW + 1, db=self.db)
        self.assertIsNotNone(first)
        self.assertIsNone(second, "the 50th seat was offered to two people")

    def test_the_race_at_seat_fifty_through_real_threads(self):
        self.take(49)
        results = []

        def go(uid):
            results.append(founding.try_reserve(uid, now=NOW, db=self.db))

        threads = [threading.Thread(target=go, args=(9000 + i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(1 for r in results if r is not None), 1)

    def test_a_reservation_expires_on_its_own_and_frees_the_seat(self):
        self.take(49)
        held = founding.try_reserve(5001, now=NOW, db=self.db)
        self.assertIsNone(founding.try_reserve(5002, now=NOW + 60, db=self.db))
        after = held.holds_until + 1
        self.assertIsNotNone(founding.try_reserve(5002, now=after, db=self.db))
        self.assertEqual(founding.seat_counts(now=after, db=self.db)["reserved"], 1)

    def test_the_reservation_window_is_thirty_minutes_and_the_session_cannot_outlive_it(self):
        res = founding.try_reserve(7, now=NOW, db=self.db)
        self.assertEqual(founding.RESERVATION_MINUTES, 30)
        self.assertGreaterEqual(res.holds_until - NOW, 30 * 60)       # Stripe's minimum session life
        self.assertEqual(res.session_expires_at, res.holds_until)

    def test_a_second_click_returns_the_same_reservation(self):
        a = founding.try_reserve(7, now=NOW, db=self.db)
        b = founding.try_reserve(7, now=NOW + 10, db=self.db)
        self.assertEqual((a.reserved_at, a.holds_until), (b.reserved_at, b.holds_until))
        self.assertEqual(founding.seat_counts(now=NOW, db=self.db)["reserved"], 1)

    def test_releasing_a_reservation_frees_the_seat_at_once(self):
        self.take(49)
        founding.try_reserve(5001, now=NOW, db=self.db)
        founding.release_reservation(5001, now=NOW + 5, db=self.db)
        self.assertIsNotNone(founding.try_reserve(5002, now=NOW + 6, db=self.db))

    def test_release_never_touches_an_active_seat(self):
        self.take(1, start=1)
        founding.release_reservation(1, now=NOW, db=self.db)
        self.assertTrue(founding.is_member(1, db=self.db))

    def test_an_ended_subscription_frees_the_seat_and_an_old_event_cannot_revive_it(self):
        founding.record_subscription(1, "sub_1", "active", NOW, now=NOW, db=self.db)
        founding.record_subscription(1, "sub_1", "canceled", NOW + 100, now=NOW, db=self.db)
        self.assertEqual(founding.seat_counts(now=NOW, db=self.db)["taken"], 0)
        founding.record_subscription(1, "sub_1", "active", NOW + 50, now=NOW, db=self.db)   # older: ignored
        self.assertEqual(founding.seat_counts(now=NOW, db=self.db)["taken"], 0)

    def test_the_count_is_never_padded_by_ended_or_pending_rows(self):
        self.take(3)
        founding.record_subscription(50, "sub_50", "canceled", NOW, now=NOW, db=self.db)
        founding.try_reserve(60, now=NOW, db=self.db)
        offer = billing.founding_offer(now=NOW, db=self.db)["founding"]
        self.assertEqual((offer["taken"], offer["left"]), (3, 47))


class PriceSelection(_Db):
    def test_a_seat_means_the_founding_price_with_a_session_that_expires_with_the_hold(self):
        choice = billing.choose_checkout_price(7, now=NOW, db=self.db)
        self.assertEqual((choice.tier, choice.price_id), ("founding", FOUNDING_PRICE))
        self.assertEqual(choice.kwargs["metadata"], {"plan_tier": "founding"})
        self.assertGreaterEqual(choice.kwargs["expires_at"] - NOW, 30 * 60)
        self.assertIn("idempotency_key", choice.kwargs)

    def test_sold_out_means_the_standard_price_with_no_extra_arguments(self):
        self.take(50)
        choice = billing.choose_checkout_price(7, now=NOW, db=self.db)
        self.assertEqual((choice.tier, choice.price_id, choice.kwargs), ("standard", STANDARD_PRICE, {}))

    def test_seats_held_by_other_checkouts_count_against_the_last_seat(self):
        self.take(49)
        billing.choose_checkout_price(1, now=NOW, db=self.db)
        self.assertEqual(billing.choose_checkout_price(2, now=NOW, db=self.db).tier, "standard")

    def test_unset_founding_env_falls_back_to_standard_and_reserves_nothing(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(billing.ENV_STRIPE_FOUNDING_PRICE_ID)
            choice = billing.choose_checkout_price(7, now=NOW, db=self.db)
        self.assertEqual((choice.tier, choice.price_id), ("standard", STANDARD_PRICE))
        self.assertEqual(founding.seat_counts(now=NOW, db=self.db)["reserved"], 0)

    def test_blank_founding_env_is_unset(self):
        with mock.patch.dict(os.environ, {billing.ENV_STRIPE_FOUNDING_PRICE_ID: "   "}):
            self.assertEqual(billing.choose_checkout_price(7, now=NOW, db=self.db).tier, "standard")

    def test_no_standard_price_is_still_not_configured(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(billing.ENV_STRIPE_BETA_PRICE_ID)
            self.assertIsNone(billing.choose_checkout_price(7, now=NOW, db=self.db))

    def test_the_prices_are_the_owners_numbers(self):
        self.assertEqual((billing.FOUNDING_PLAN_PRICE_CENTS, billing.BETA_PLAN_PRICE_CENTS,
                          billing.FOUNDING_SEAT_CAP), (1499, 1999, 50))


class OfferBody(_Db):
    def test_shape_with_seats_left(self):
        self.take(12)
        body = billing.founding_offer(now=NOW, db=self.db)
        self.assertEqual(body["standard"], {"price_cents": 1999})
        f = body["founding"]
        self.assertEqual((f["price_cents"], f["cap"], f["taken"], f["left"], f["available"]),
                         (1499, 50, 12, 38, True))

    def test_sold_out_is_not_available(self):
        self.take(50)
        f = billing.founding_offer(now=NOW, db=self.db)["founding"]
        self.assertEqual((f["taken"], f["left"], f["available"]), (50, 0, False))

    def test_last_seat_held_by_a_checkout_is_not_offered_but_not_counted_as_taken(self):
        self.take(49)
        founding.try_reserve(77, now=NOW, db=self.db)
        f = billing.founding_offer(now=NOW, db=self.db)["founding"]
        self.assertEqual((f["taken"], f["left"], f["reserved"], f["available"]), (49, 1, 1, False))

    def test_unset_founding_price_reports_no_founding_offer(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(billing.ENV_STRIPE_FOUNDING_PRICE_ID)
            body = billing.founding_offer(now=NOW, db=self.db)
        self.assertEqual(body, {"founding": None, "standard": {"price_cents": 1999}})


class WebhookMakesTheSeat(_Db):
    def sub_event(self, kind, status, sub="sub_f", created=NOW, tier=True):
        obj = {"id": sub, "customer": "cus_f", "status": status,
               "metadata": {"plan_tier": "founding"} if tier else {}}
        return {"type": kind, "created": created, "data": {"object": obj}}

    def test_subscription_events_for_a_founding_price_take_and_release_the_seat(self):
        customers.upsert_customer(42, "cus_f", db=self.db)
        billing.apply_stripe_webhook_event(self.sub_event("customer.subscription.created", "trialing"), db=self.db)
        self.assertTrue(founding.is_member(42, db=self.db))
        billing.apply_stripe_webhook_event(
            self.sub_event("customer.subscription.deleted", "canceled", created=NOW + 5), db=self.db)
        self.assertFalse(founding.is_member(42, db=self.db))

    def test_a_standard_subscription_never_takes_a_founding_seat(self):
        customers.upsert_customer(42, "cus_f", db=self.db)
        billing.apply_stripe_webhook_event(
            self.sub_event("customer.subscription.created", "active", tier=False), db=self.db)
        self.assertEqual(founding.active_user_ids(db=self.db), [])

    def test_a_line_item_at_the_founding_price_id_counts_without_metadata(self):
        customers.upsert_customer(42, "cus_f", db=self.db)
        event = self.sub_event("customer.subscription.created", "active", tier=False)
        event["data"]["object"]["items"] = {"data": [{"price": {"id": FOUNDING_PRICE}}]}
        billing.apply_stripe_webhook_event(event, db=self.db)
        self.assertTrue(founding.is_member(42, db=self.db))

    def test_checkout_completed_paid_takes_the_seat_and_an_unpaid_one_does_not(self):
        def completed(user, sub, pay):
            return {"type": "checkout.session.completed", "created": NOW,
                    "data": {"object": {"client_reference_id": str(user), "customer": f"cus_{user}",
                                        "subscription": sub, "payment_status": pay,
                                        "metadata": {"plan_tier": "founding"}}}}
        billing.apply_stripe_webhook_event(completed(1, "sub_1", "paid"), db=self.db)
        billing.apply_stripe_webhook_event(completed(2, "sub_2", "unpaid"), db=self.db)
        self.assertEqual(founding.active_user_ids(db=self.db), [1])

    def test_an_expired_founding_session_releases_the_hold(self):
        self.take(49)
        founding.try_reserve(5001, now=NOW, db=self.db)
        billing.apply_stripe_webhook_event(
            {"type": "checkout.session.expired", "created": NOW,
             "data": {"object": {"client_reference_id": "5001", "metadata": {"plan_tier": "founding"}}}},
            db=self.db)
        self.assertEqual(founding.seat_counts(now=NOW + 1, db=self.db)["reserved"], 0)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class OfferEndpointAndCheckout(_Db):
    def setUp(self):
        super().setUp()
        import api.billing as api_billing
        self.api = api_billing
        self.api._offer_cache.update({"at": None, "body": None})
        self.user = users_store.create_user("founder@example.com", status="active", db=self.db)

    def test_offer_endpoint_returns_the_documented_shape_and_a_cache_header(self):
        from fastapi import Response
        self.take(2)
        response = Response()
        body = self.api.billing_offer(response, None)
        self.assertEqual(body["standard"], {"price_cents": 1999})
        self.assertEqual({k: body["founding"][k] for k in ("price_cents", "cap", "taken", "left", "available")},
                         {"price_cents": 1499, "cap": 50, "taken": 2, "left": 48, "available": True})
        self.assertEqual(response.headers["cache-control"], "public, max-age=30")

    def test_offer_is_cached_for_about_thirty_seconds_then_refreshed(self):
        from fastapi import Response
        clock = [100.0]
        with mock.patch.object(self.api, "_offer_clock", lambda: clock[0]):
            first = self.api.billing_offer(Response(), None)["founding"]["taken"]
            self.take(1)
            clock[0] += 10
            self.assertEqual(self.api.billing_offer(Response(), None)["founding"]["taken"], first)
            clock[0] += 25
            self.assertEqual(self.api.billing_offer(Response(), None)["founding"]["taken"], first + 1)

    def test_a_broken_seat_table_is_no_founding_offer_not_a_500(self):
        from fastapi import Response
        with mock.patch.object(billing, "founding_offer", side_effect=RuntimeError("db down")):
            body = self.api.billing_offer(Response(), None)
        self.assertEqual(body, {"founding": None, "standard": {"price_cents": 1999}})

    def test_checkout_opens_at_the_founding_price_and_a_failed_open_gives_the_seat_back(self):
        stub = mock.Mock()
        stub.create_checkout.return_value = "https://checkout.stripe.com/x"
        with mock.patch.object(billing, "get_billing_provider", return_value=stub):
            out = self.api.create_checkout(self.api.CheckoutRequest(plan_id="beta"), current_user=self.user)
        self.assertEqual((out["status"], out["tier"]), ("redirect", "founding"))
        self.assertEqual(stub.create_checkout.call_args.args[1], FOUNDING_PRICE)
        self.assertEqual(founding.seat_counts(db=self.db)["reserved"], 1)

        other = users_store.create_user("other@example.com", status="active", db=self.db)
        failing = mock.Mock()
        failing.create_checkout.side_effect = RuntimeError("stripe 500")
        with mock.patch.object(billing, "get_billing_provider", return_value=failing):
            out = self.api.create_checkout(self.api.CheckoutRequest(plan_id="beta"), current_user=other)
        self.assertNotEqual(out["status"], "redirect")
        self.assertEqual(founding.seat_counts(db=self.db)["reserved"], 1)    # only the first user's hold

    def test_sold_out_checkout_uses_the_standard_price_id(self):
        self.take(50)
        stub = mock.Mock()
        stub.create_checkout.return_value = "https://checkout.stripe.com/y"
        with mock.patch.object(billing, "get_billing_provider", return_value=stub):
            out = self.api.create_checkout(self.api.CheckoutRequest(plan_id="beta"), current_user=self.user)
        self.assertEqual(out["tier"], "standard")
        self.assertEqual(stub.create_checkout.call_args.args[1], STANDARD_PRICE)


if __name__ == "__main__":
    unittest.main()
