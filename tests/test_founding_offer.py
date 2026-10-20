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
import time
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


def expired_event(user_id, choice, created=NOW):
    """The checkout.session.expired Stripe sends for the session opened with `choice`: it echoes the
    metadata the session was created with, which is how the event finds its own reservation."""
    return {"type": "checkout.session.expired", "created": created,
            "data": {"object": {"client_reference_id": str(user_id),
                                "metadata": dict(choice.kwargs["metadata"])}}}


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
        after = held.holds_until + founding.HOLD_GRACE_SECONDS + 1     # the grace is part of the hold
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
        held = founding.try_reserve(5001, now=NOW, db=self.db)
        self.assertTrue(founding.release_reservation(5001, reserved_at=held.reserved_at, now=NOW + 5, db=self.db))
        self.assertEqual(founding.seat_counts(now=NOW + 6, db=self.db)["reserved"], 0)   # not even the grace tail
        self.assertIsNotNone(founding.try_reserve(5002, now=NOW + 6, db=self.db))

    def test_release_never_touches_an_active_seat(self):
        self.take(1, start=1)
        self.assertFalse(founding.release_reservation(1, reserved_at=NOW, now=NOW, db=self.db))
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
        self.assertEqual(choice.kwargs["metadata"],
                         {"plan_tier": "founding", "founding_reservation": str(choice.created_reservation)})
        self.assertEqual(choice.created_reservation, NOW)
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
        choice = billing.choose_checkout_price(5001, now=NOW, db=self.db)
        billing.apply_stripe_webhook_event(expired_event(5001, choice), db=self.db)
        self.assertEqual(founding.seat_counts(now=NOW + 1, db=self.db)["reserved"], 0)


class PastDueKeepsTheSeat(_Db):
    """A card that fails is not a subscription that ended. Stripe keeps retrying, the same subscription
    (the same locked price) comes back when the card is fixed, and the member is still entitled to what
    they paid for. The seat used to be freed on the first failed charge and sold to someone else: 51 taken."""

    def sub_event(self, kind, status, sub="sub_f", created=NOW):
        return {"type": kind, "created": created,
                "data": {"object": {"id": sub, "customer": "cus_f", "status": status,
                                    "metadata": {"plan_tier": "founding"}}}}

    def test_past_due_does_not_free_the_seat_and_the_51st_buyer_is_refused(self):
        self.take(49)
        founding.record_subscription(7, "sub_7", "active", NOW, now=NOW, db=self.db)         # seat 50
        founding.record_subscription(7, "sub_7", "past_due", NOW + 100, now=NOW + 100, db=self.db)
        self.assertEqual(founding.seat_counts(now=NOW + 200, db=self.db), {"taken": 50, "reserved": 0})
        self.assertIsNone(founding.try_reserve(999, now=NOW + 200, db=self.db))
        self.assertEqual(billing.choose_checkout_price(999, now=NOW + 200, db=self.db).tier, "standard")
        founding.record_subscription(7, "sub_7", "active", NOW + 400, now=NOW + 400, db=self.db)  # card fixed
        self.assertTrue(founding.is_member(7, db=self.db))
        self.assertEqual(founding.seat_counts(now=NOW + 500, db=self.db)["taken"], 50)

    def test_the_webhook_path_keeps_the_seat_on_past_due_but_access_still_reads_canceled(self):
        customers.upsert_customer(42, "cus_f", db=self.db)
        billing.apply_stripe_webhook_event(self.sub_event("customer.subscription.created", "active"), db=self.db)
        billing.apply_stripe_webhook_event(
            self.sub_event("customer.subscription.updated", "past_due", created=NOW + 10), db=self.db)
        self.assertTrue(founding.is_member(42, db=self.db), "past_due freed the founding seat")
        # The ACCESS side is deliberately unchanged: a failed payment is recorded as `canceled` there, so it
        # grants no renewal grace (src.appstate.customers.carry_grace_block / RENEWAL_GRACE_SECONDS).
        self.assertEqual(customers.get_subscription_record(42, db=self.db)["status"], "canceled")

    def test_only_a_finished_subscription_frees_the_seat(self):
        cases = {"canceled": False, "unpaid": False, "incomplete_expired": False,
                 "past_due": True, "incomplete": True, "paused": True, "something_new": True, None: True}
        for user, (status, keeps) in enumerate(cases.items(), start=500):
            with self.subTest(status=status):
                founding.record_subscription(user, f"sub_{user}", "active", NOW, now=NOW, db=self.db)
                founding.record_subscription(user, f"sub_{user}", status, NOW + 10, now=NOW + 10, db=self.db)
                self.assertEqual(founding.is_member(user, db=self.db), keeps)

    def test_a_deleted_event_ends_the_seat_whatever_status_its_body_carries(self):
        customers.upsert_customer(42, "cus_f", db=self.db)
        billing.apply_stripe_webhook_event(self.sub_event("customer.subscription.created", "active"), db=self.db)
        billing.apply_stripe_webhook_event(
            self.sub_event("customer.subscription.deleted", "past_due", created=NOW + 10), db=self.db)
        self.assertFalse(founding.is_member(42, db=self.db))

    def test_a_no_op_status_does_not_block_a_later_real_ending(self):
        founding.record_subscription(5, "sub_5", "active", NOW, now=NOW, db=self.db)
        founding.record_subscription(5, "sub_5", "past_due", NOW + 500, now=NOW + 500, db=self.db)
        founding.record_subscription(5, "sub_5", "canceled", NOW + 100, now=NOW + 600, db=self.db)   # late delivery
        self.assertFalse(founding.is_member(5, db=self.db))


class HoldGraceAfterTheWindow(_Db):
    """A buyer who pays in the last second of the session is seated by a webhook that lands later. The hold
    used to lapse at `holds_until`, so a second buyer was offered the same seat in the gap."""

    def test_a_hold_keeps_counting_for_the_grace_then_stops(self):
        self.take(49)
        held = founding.try_reserve(60, now=NOW, db=self.db)
        edge = held.holds_until
        self.assertEqual(founding.HOLD_GRACE_SECONDS, 15 * 60)
        self.assertIsNone(founding.try_reserve(61, now=edge + 1, db=self.db))
        self.assertIsNone(founding.try_reserve(61, now=edge + founding.HOLD_GRACE_SECONDS - 1, db=self.db))
        self.assertEqual(founding.seat_counts(now=edge + 1, db=self.db), {"taken": 49, "reserved": 1})
        self.assertFalse(billing.founding_offer(now=edge + 1, db=self.db)["founding"]["available"])
        self.assertIsNotNone(founding.try_reserve(61, now=edge + founding.HOLD_GRACE_SECONDS + 1, db=self.db))

    def test_the_last_second_payment_keeps_the_seat_while_the_webhook_is_late(self):
        """The verifier's race: 49 taken, 60 holds seat 50 and pays one second before Stripe's expiry, 61
        asks for a seat after the window and before 60's webhook lands."""
        self.take(49)
        held = founding.try_reserve(60, now=NOW, db=self.db)
        late_click = held.holds_until + 1
        self.assertEqual(billing.choose_checkout_price(61, now=late_click, db=self.db).tier, "standard")
        founding.record_checkout_paid(60, "s60", held.holds_until - 1, now=held.holds_until + 5, db=self.db)
        self.assertEqual(founding.seat_counts(now=held.holds_until + 100, db=self.db),
                         {"taken": 50, "reserved": 0})
        self.assertTrue(founding.is_member(60, db=self.db))

    def test_the_grace_does_not_extend_the_owners_own_session(self):
        """After the window the old session can no longer be paid, so a new click opens a NEW session."""
        self.take(49)
        first = founding.try_reserve(60, now=NOW, db=self.db)
        again = founding.try_reserve(60, now=first.holds_until + 1, db=self.db)
        self.assertTrue(again.created)
        self.assertGreater(again.reserved_at, first.reserved_at)
        self.assertEqual(founding.seat_counts(now=first.holds_until + 2, db=self.db)["reserved"], 1)


class ReleasesAreNarrow(_Db):
    """A release names the reservation it means. Two ways it used to free the wrong seat: a late
    checkout.session.expired for an OLD session freed the NEW session's hold, and a failed duplicate
    request freed the hold of the request that was still opening it."""

    def test_a_late_expiry_of_an_old_session_does_not_release_the_new_reservation(self):
        self.take(49)
        old = billing.choose_checkout_price(5001, now=NOW, db=self.db)
        later = NOW + founding.RESERVATION_SECONDS + founding.SESSION_SLACK_SECONDS + 5
        new = billing.choose_checkout_price(5001, now=later, db=self.db)              # the old window lapsed
        self.assertNotEqual(old.kwargs["metadata"], new.kwargs["metadata"])
        self.assertNotEqual(old.kwargs["idempotency_key"], new.kwargs["idempotency_key"])
        billing.apply_stripe_webhook_event(expired_event(5001, old, created=later + 1), db=self.db)   # arrives late
        self.assertEqual(founding.seat_counts(now=later + 2, db=self.db)["reserved"], 1)
        self.assertIsNone(founding.try_reserve(5002, now=later + 2, db=self.db), "the new hold was freed")
        billing.apply_stripe_webhook_event(expired_event(5001, new, created=later + 3), db=self.db)   # its own expiry
        self.assertEqual(founding.seat_counts(now=later + 4, db=self.db)["reserved"], 0)

    def test_an_expiry_that_carries_no_reference_releases_nothing(self):
        """A session opened before the reference was stamped: its hold simply times out."""
        self.take(49)
        billing.choose_checkout_price(5001, now=NOW, db=self.db)
        billing.apply_stripe_webhook_event(
            {"type": "checkout.session.expired", "created": NOW,
             "data": {"object": {"client_reference_id": "5001", "metadata": {"plan_tier": "founding"}}}},
            db=self.db)
        self.assertEqual(founding.seat_counts(now=NOW + 1, db=self.db)["reserved"], 1)

    def test_a_garbage_reference_is_ignored_not_a_500(self):
        self.take(49)
        billing.choose_checkout_price(5001, now=NOW, db=self.db)
        for junk in ("not-a-number", "9" * 40, "-5", "", None, {"x": 1}):
            with self.subTest(junk=junk):
                billing.apply_stripe_webhook_event(
                    {"type": "checkout.session.expired", "created": NOW, "data": {"object": {
                        "client_reference_id": "5001",
                        "metadata": {"plan_tier": "founding", "founding_reservation": junk}}}}, db=self.db)
        self.assertEqual(founding.seat_counts(now=NOW + 1, db=self.db)["reserved"], 1)

    def test_release_names_the_reservation_and_leaves_any_other_alone(self):
        held = founding.try_reserve(7, now=NOW, db=self.db)
        self.assertFalse(founding.release_reservation(7, reserved_at=held.reserved_at + 1, now=NOW + 1, db=self.db))
        self.assertFalse(founding.release_reservation(8, reserved_at=held.reserved_at, now=NOW + 1, db=self.db))
        self.assertEqual(founding.seat_counts(now=NOW + 2, db=self.db)["reserved"], 1)
        self.assertTrue(founding.release_reservation(7, reserved_at=held.reserved_at, now=NOW + 2, db=self.db))
        self.assertFalse(founding.release_reservation(7, reserved_at=held.reserved_at, now=NOW + 3, db=self.db))

    def test_a_hold_released_and_made_again_in_one_second_is_a_new_reference(self):
        first = founding.try_reserve(7, now=NOW, db=self.db)
        founding.release_reservation(7, reserved_at=first.reserved_at, now=NOW, db=self.db)
        second = founding.try_reserve(7, now=NOW, db=self.db)
        self.assertTrue(second.created)
        self.assertNotEqual(first.reserved_at, second.reserved_at)
        # ... so a late expiry of the FIRST session cannot free the second.
        self.assertFalse(founding.release_reservation(7, reserved_at=first.reserved_at, now=NOW + 1, db=self.db))

    def test_only_the_call_that_created_a_hold_owns_it(self):
        self.take(49)
        first = billing.choose_checkout_price(7, now=NOW, db=self.db)
        second = billing.choose_checkout_price(7, now=NOW + 2, db=self.db)           # the double click
        self.assertIsNotNone(first.created_reservation)
        self.assertIsNone(second.created_reservation)
        self.assertEqual(first.kwargs["idempotency_key"], second.kwargs["idempotency_key"])
        billing.release_founding_reservation(7, second, db=self.db)                  # the duplicate fails
        self.assertEqual(founding.seat_counts(now=NOW + 3, db=self.db)["reserved"], 1)
        billing.release_founding_reservation(7, first, db=self.db)                   # the owner fails
        self.assertEqual(founding.seat_counts(now=NOW + 4, db=self.db)["reserved"], 0)

    def test_a_standard_choice_has_nothing_to_release(self):
        self.take(50)
        choice = billing.choose_checkout_price(7, now=NOW, db=self.db)
        self.assertIsNone(choice.created_reservation)
        billing.release_founding_reservation(7, choice, db=self.db)                  # a no-op, not an error


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


    # ---- a subscriber who already pays never gets a second session ------------------------------------------

    def subscribe(self, user, *, status="active", tier=True, created=None, days=30, cancel_at=None):
        """The webhook trail of a real subscription for `user`: customer link, then subscription.created."""
        now = int(time.time()) if created is None else created
        customers.upsert_customer(user.id, f"cus_{user.id}", db=self.db)
        obj = {"id": f"sub_{user.id}", "customer": f"cus_{user.id}", "status": status, "created": now,
               "current_period_end": now + days * 86400, "cancel_at": cancel_at,
               "metadata": {"plan_tier": "founding"} if tier else {}}
        billing.apply_stripe_webhook_event(
            {"type": "customer.subscription.created", "created": now, "data": {"object": obj}}, db=self.db)

    def checkout(self, user=None, provider=None):
        stub = provider or mock.Mock()
        if provider is None:
            stub.create_checkout.return_value = "https://checkout.stripe.com/z"
        with mock.patch.object(billing, "get_billing_provider", return_value=stub):
            return self.api.create_checkout(self.api.CheckoutRequest(plan_id="beta"),
                                            current_user=user or self.user), stub

    def refused(self, user=None):
        from fastapi import HTTPException
        stub = mock.Mock()
        with mock.patch.object(billing, "get_billing_provider", return_value=stub):
            with self.assertRaises(HTTPException) as ctx:
                self.api.create_checkout(self.api.CheckoutRequest(plan_id="beta"), current_user=user or self.user)
        return ctx.exception, stub

    def test_an_active_founding_member_pressing_subscribe_again_gets_409_and_no_session(self):
        self.subscribe(self.user)
        self.assertTrue(founding.is_member(self.user.id, db=self.db))
        exc, stub = self.refused()
        self.assertEqual(exc.status_code, 409)
        self.assertEqual(exc.detail["error"], "already_subscribed")
        self.assertEqual(exc.detail["manage_url"], "/web/index.html#/billing")
        stub.create_checkout.assert_not_called()
        self.assertEqual(founding.seat_counts(db=self.db), {"taken": 1, "reserved": 0})   # and no seat was held

    def test_an_active_standard_member_gets_409_too(self):
        self.take(50)                                              # sold out, so this member is on the standard price
        self.subscribe(self.user, tier=False)
        exc, stub = self.refused()
        self.assertEqual((exc.status_code, exc.detail["error"]), (409, "already_subscribed"))
        stub.create_checkout.assert_not_called()

    def test_a_trialing_member_and_a_scheduled_cancel_inside_the_paid_period_get_409(self):
        self.subscribe(self.user, status="trialing")
        self.assertEqual(self.refused()[0].detail["error"], "already_subscribed")
        other = users_store.create_user("leaving@example.com", status="active", db=self.db)
        self.subscribe(other, cancel_at=int(time.time()) + 20 * 86400)
        exc, stub = self.refused(other)
        self.assertEqual(exc.detail["error"], "already_subscribed")      # they resume renewal on the billing page
        stub.create_checkout.assert_not_called()

    def test_a_lapsed_subscriber_and_a_new_visitor_can_still_check_out(self):
        long_ago = int(time.time()) - 90 * 86400
        self.subscribe(self.user, tier=False, created=long_ago)          # paid through 60 days ago
        out, stub = self.checkout()
        self.assertEqual(out["status"], "redirect")
        stub.create_checkout.assert_called_once()
        newcomer = users_store.create_user("new@example.com", status="active", db=self.db)
        self.assertEqual(self.checkout(newcomer)[0]["status"], "redirect")

    # ---- a failed request gives back only a hold it made ---------------------------------------------------

    def test_a_failed_duplicate_request_does_not_free_the_hold_the_first_request_is_still_opening(self):
        """Double click: request A has reserved the seat and is still talking to Stripe; request B is handed
        the same hold, Stripe answers its (identical) idempotency key with a 409, and B fails."""
        in_flight = billing.choose_checkout_price(self.user.id)                 # request A
        self.assertEqual(founding.seat_counts(db=self.db)["reserved"], 1)
        failing = mock.Mock()
        failing.create_checkout.side_effect = RuntimeError("stripe 409 idempotency_key_in_use")
        out, _ = self.checkout(provider=failing)                                # request B
        self.assertEqual(out["status"], "error")
        self.assertEqual(founding.seat_counts(db=self.db)["reserved"], 1, "B freed the seat A still holds")
        self.assertEqual(failing.create_checkout.call_args.kwargs["idempotency_key"],
                         in_flight.kwargs["idempotency_key"])
        billing.release_founding_reservation(self.user.id, in_flight)           # A fails too: now it is free
        self.assertEqual(founding.seat_counts(db=self.db)["reserved"], 0)

    def test_a_request_that_made_the_hold_and_blows_up_gives_it_back(self):
        boom = mock.Mock()
        boom.create_checkout.side_effect = ValueError("not a RuntimeError")
        with mock.patch.object(billing, "get_billing_provider", return_value=boom):
            with self.assertRaises(ValueError):
                self.api.create_checkout(self.api.CheckoutRequest(plan_id="beta"), current_user=self.user)
        self.assertEqual(founding.seat_counts(db=self.db)["reserved"], 0)

    def test_the_signup_path_follows_the_same_rule(self):
        import api.signup as signup
        in_flight = billing.choose_checkout_price(self.user.id)
        failing = mock.Mock()
        failing.create_checkout.side_effect = RuntimeError("stripe 409")
        with mock.patch.object(billing, "get_billing_provider", return_value=failing):
            with self.assertRaises(signup._CheckoutProviderError):
                signup._attempt_checkout(self.user.id)
        self.assertEqual(founding.seat_counts(db=self.db)["reserved"], 1, "a duplicate submit freed the first hold")
        billing.release_founding_reservation(self.user.id, in_flight)
        with mock.patch.object(billing, "get_billing_provider", return_value=failing):
            with self.assertRaises(signup._CheckoutProviderError):
                signup._attempt_checkout(self.user.id)                          # this call made the hold itself
        self.assertEqual(founding.seat_counts(db=self.db)["reserved"], 0)
        empty = mock.Mock()
        empty.create_checkout.return_value = ""                                 # "billing not ready": no URL
        with mock.patch.object(billing, "get_billing_provider", return_value=empty):
            self.assertIsNone(signup._attempt_checkout(self.user.id))
        self.assertEqual(founding.seat_counts(db=self.db)["reserved"], 0)


if __name__ == "__main__":
    unittest.main()
