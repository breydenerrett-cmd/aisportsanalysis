"""Billing under duplicate, delayed and reordered Stripe events.

Owner ruling, 2026-10-04: Stripe does not guarantee webhook order, so billing
must be correct however the events arrive. "A billing-period update alone
must not grant an unpaid renewal. Verified payment must grant the correct
access, and an older failure must not undo a later successful payment. Keep
trials, existing paid-through access and cancellation policy explicit."

The model these tests pin:

  * Access runs to the PAID-THROUGH instant (`paid_through`), which only
    EVIDENCE moves: a paid invoice (its line period end), or a trial
    (`trial_end`), or the first period of a brand-new subscription
    (`customer.subscription.created` reporting `active`). A
    `customer.subscription.updated` that only announces a new
    `current_period_end` is not evidence and grants nothing.
  * Evidence only ever extends paid-through, so no order of arrival can take
    access away from a customer who paid, and none can hand it to one who
    did not.
  * Every status decision compares the event's own timestamp with what is
    stored, so an older event never overwrites a newer state.

Every test drives the same signed-webhook entry point as
tests/test_billing_acceptance_path.py. Nothing here can reach Stripe and
billing stays off in production.
"""

from __future__ import annotations

import io
import itertools
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from fastapi import HTTPException
except ImportError:  # pragma: no cover
    HTTPException = Exception  # the FastAPI-backed cases are skipped without it

from src.appstate import billing, customers
from tests import test_billing_acceptance_path as acceptance

CUSTOMER = acceptance.CUSTOMER
SUBSCRIPTION = acceptance.SUBSCRIPTION
DAY = 86400
_CLOCK = datetime.fromtimestamp(int(datetime.now(timezone.utc).timestamp()), tz=timezone.utc)


def _epoch(moment: datetime) -> int:
    return int(moment.timestamp())


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


class _OrderCase(acceptance._Case):
    """One buyer, a clock of event times, and builders for the events Stripe
    sends. `at(n)` is the Stripe-side `created` of the n-th minute of the
    story; events built with a larger n happened later, whatever order they
    are delivered in."""

    def setUp(self):
        super().setUp()
        # One clock for the whole test run, so a test that calls setUp again
        # to start a second buyer sees the same instants.
        self.now = _CLOCK
        self.base = _epoch(self.now) - 3 * DAY
        self.p1 = _epoch(self.now + timedelta(days=10))    # paid through
        self.p2 = _epoch(self.now + timedelta(days=40))    # next period
        self.p3 = _epoch(self.now + timedelta(days=70))

    # -- builders -----------------------------------------------------------

    def at(self, minutes: int) -> int:
        return self.base + minutes * 60

    def sub_event(self, kind, status, minute, *, period_end, trial_end=None,
                  cancel_at=None, sub=SUBSCRIPTION, sub_created_minute=0):
        obj = {"id": sub, "customer": CUSTOMER, "status": status,
               "current_period_end": period_end, "cancel_at": cancel_at,
               "created": self.at(sub_created_minute)}
        if trial_end is not None:
            obj["trial_end"] = trial_end
        return {"id": f"evt_{kind}_{sub}_{status}_{minute}_{period_end}",
                "type": f"customer.subscription.{kind}", "created": self.at(minute),
                "data": {"object": obj}}

    def invoice_event(self, minute, *, period_end, paid=True, sub=SUBSCRIPTION,
                      reason="subscription_cycle", kind="invoice.paid"):
        obj = {"id": f"in_{sub}_{period_end}", "object": "invoice",
               "customer": CUSTOMER, "subscription": sub,
               "status": "paid" if paid else "open", "paid": paid,
               "billing_reason": reason, "created": self.at(minute),
               "amount_paid": 1999 if paid else 0,
               "lines": {"data": [{
                   "period": {"start": period_end - 30 * DAY, "end": period_end},
                   "subscription": sub}]}}
        return {"id": f"evt_{kind}_{sub}_{period_end}", "type": kind,
                "created": self.at(minute), "data": {"object": obj}}

    def failed_event(self, minute, *, period_end, sub=SUBSCRIPTION):
        event = self.invoice_event(minute, period_end=period_end, paid=False, sub=sub,
                                   kind="invoice.payment_failed")
        event["data"]["object"]["attempt_count"] = 1
        return event

    def session_event(self, user_id, *, payment_status="paid", sub=SUBSCRIPTION, minute=0):
        event = self.completed_event(user_id)
        event["created"] = self.at(minute)
        obj = event["data"]["object"]
        obj["payment_status"] = payment_status
        obj["subscription"] = sub
        obj["created"] = self.at(minute)
        return event

    # -- stories ------------------------------------------------------------

    def buy_paid(self, end=None, email="payer@example.com"):
        """signup -> checkout completed -> the new subscription (first
        period) -> the first paid invoice, with the paid-through at `end`
        (default p1). Returns (user_id, access token)."""
        end = end or self.p1
        started = self.signup(email)
        user_id = started["user_id"]
        self.webhook(self.session_event(user_id))
        self.webhook(self.sub_event("created", "active", 1, period_end=end))
        self.webhook(self.invoice_event(2, period_end=end, reason="subscription_create"))
        return user_id, self.collect_token()["token"]

    def seed_paid(self, user_id=1):
        """A customer paid through p1, without the signup machinery: the
        permutation tests build hundreds of these. Reuses the database and
        clears the subscription row, which is what a fresh customer is."""
        customers.upsert_customer(user_id, CUSTOMER)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("DELETE FROM billing_subscriptions")
        self.webhook(self.sub_event("created", "active", 1, period_end=self.p1))
        self.webhook(self.invoice_event(2, period_end=self.p1, reason="subscription_create"))
        return user_id

    def buy_trial(self, trial_end, email="trial@example.com"):
        started = self.signup(email)
        user_id = started["user_id"]
        self.webhook(self.session_event(user_id, payment_status="no_payment_required"))
        self.webhook(self.sub_event("created", "trialing", 1, period_end=trial_end,
                                    trial_end=trial_end))
        return user_id, self.collect_token()["token"]

    # -- reads --------------------------------------------------------------

    def record(self, user_id):
        return customers.get_subscription_record(user_id)

    def paid_through(self, user_id):
        return (self.record(user_id) or {}).get("paid_through")

    def has_access(self, user_id, when):
        return customers.has_paid_access(
            user_id, now=datetime.fromtimestamp(when, tz=timezone.utc))

    def stable(self, user_id):
        """The record minus the write time: what 'changes nothing' compares."""
        record = dict(self.record(user_id))
        record.pop("updated_at", None)
        return record

    def assert_refused(self, token):
        with self.assertRaises(HTTPException) as refused:
            self.open_paid_page(token)
        self.assertEqual(refused.exception.status_code, 402)

    def assert_covers(self, user_id, end):
        """Access up to `end`, none after it."""
        self.assertTrue(self.has_access(user_id, end - 3600), "access ended early")
        self.assertFalse(self.has_access(user_id, end + 3600), "access ran late")


class APeriodAnnouncementAloneGrantsNothing(_OrderCase):
    def test_an_active_update_announcing_the_next_period_does_not_extend_access(self):
        user_id, token = self.buy_paid()
        self.webhook(self.sub_event("updated", "active", 20, period_end=self.p2))
        self.assertEqual(self.paid_through(user_id), _iso(self.p1))
        self.assert_covers(user_id, self.p1)
        self.assertEqual(self.open_paid_page(token).id, user_id)   # still inside p1

    def test_with_no_payment_evidence_an_update_grants_no_access_at_all(self):
        started = self.signup("nobody@example.com")
        user_id = started["user_id"]
        self.webhook(self.session_event(user_id))
        self.webhook(self.sub_event("updated", "active", 5, period_end=self.p2))
        self.assertFalse(customers.has_paid_access(user_id))
        self.assertIsNone(self.paid_through(user_id))

    def test_a_completed_session_alone_grants_nothing_the_first_invoice_does(self):
        started = self.signup("first@example.com")
        user_id = started["user_id"]
        self.webhook(self.session_event(user_id, payment_status="paid"))
        self.assertFalse(customers.has_paid_access(user_id))
        token = self.collect_token()["token"]
        self.assert_refused(token)
        self.webhook(self.invoice_event(2, period_end=self.p1, reason="subscription_create"))
        self.assert_covers(user_id, self.p1)
        self.assertEqual(self.open_paid_page(token).id, user_id)

    def test_an_unpaid_invoice_is_not_evidence(self):
        started = self.signup("open@example.com")
        user_id = started["user_id"]
        self.webhook(self.session_event(user_id))
        self.webhook(self.invoice_event(2, period_end=self.p1, paid=False,
                                        reason="subscription_create"))
        self.assertFalse(customers.has_paid_access(user_id))

    def test_a_new_subscription_reporting_active_grants_its_first_period(self):
        """`.created` + active is Stripe saying the first invoice was paid:
        a subscription is born `incomplete` until it is."""
        started = self.signup("born@example.com")
        user_id = started["user_id"]
        self.webhook(self.session_event(user_id))
        self.webhook(self.sub_event("created", "active", 1, period_end=self.p1))
        self.assert_covers(user_id, self.p1)


class TrialsGrantThroughTheTrialEndOnly(_OrderCase):
    def setUp(self):
        super().setUp()
        self.trial_end = _epoch(self.now + timedelta(days=7))

    def test_a_trial_grants_through_trial_end_even_if_the_period_says_more(self):
        started = self.signup("t1@example.com")
        user_id = started["user_id"]
        self.webhook(self.session_event(user_id, payment_status="no_payment_required"))
        self.webhook(self.sub_event("created", "trialing", 1, period_end=self.p2,
                                    trial_end=self.trial_end))
        self.assert_covers(user_id, self.trial_end)
        self.assertEqual(self.paid_through(user_id), _iso(self.trial_end))

    def test_trial_then_the_first_charge_pays(self):
        user_id, _ = self.buy_trial(self.trial_end)
        self.webhook(self.sub_event("updated", "active", 30, period_end=self.p2))
        self.webhook(self.invoice_event(31, period_end=self.p2, reason="subscription_cycle"))
        self.assert_covers(user_id, self.p2)
        self.assertEqual(self.record(user_id)["status"], "active")

    def test_trial_then_the_first_charge_fails_access_ends_at_trial_end(self):
        user_id, token = self.buy_trial(self.trial_end)
        self.webhook(self.failed_event(30, period_end=self.p2))
        self.webhook(self.sub_event("updated", "past_due", 30, period_end=self.p2))
        self.assertEqual(self.paid_through(user_id), _iso(self.trial_end))
        self.assert_covers(user_id, self.trial_end)
        self.assertEqual(self.open_paid_page(token).id, user_id)   # trial still running

    def test_trial_then_an_active_announcement_without_a_payment_grants_nothing_new(self):
        user_id, _ = self.buy_trial(self.trial_end)
        self.webhook(self.sub_event("updated", "active", 30, period_end=self.p2))
        self.assert_covers(user_id, self.trial_end)


class UpdateAndPaymentInEitherOrder(_OrderCase):
    def _final(self, user_id):
        record = self.record(user_id)
        return (record["status"], record["paid_through"], record["cancel_at"])

    def test_update_then_paid_and_paid_then_update_end_the_same(self):
        outcomes = []
        for label, order in (("update first", (0, 1)), ("paid first", (1, 0))):
            with self.subTest(order=label):
                self.setUp()
                user_id, _ = self.buy_paid()
                events = [self.sub_event("updated", "active", 20, period_end=self.p2),
                          self.invoice_event(21, period_end=self.p2)]
                for index in order:
                    self.webhook(events[index])
                self.assert_covers(user_id, self.p2)
                outcomes.append(self._final(user_id))
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(outcomes[0][:2], ("active", _iso(self.p2)))

    def test_the_gap_between_update_and_payment_has_no_access_for_the_new_period(self):
        user_id, _ = self.buy_paid()
        self.webhook(self.sub_event("updated", "active", 20, period_end=self.p2))
        self.assertFalse(self.has_access(user_id, self.p1 + 3600))
        self.webhook(self.invoice_event(21, period_end=self.p2))
        self.assertTrue(self.has_access(user_id, self.p1 + 3600))

    def test_invoice_payment_succeeded_is_evidence_too(self):
        user_id, _ = self.buy_paid()
        self.webhook(self.invoice_event(21, period_end=self.p2,
                                        kind="invoice.payment_succeeded"))
        self.assert_covers(user_id, self.p2)


class FailureAndPaymentInEitherOrder(_OrderCase):
    def test_failed_then_paid_retry_restores_active(self):
        user_id, _ = self.buy_paid()
        self.webhook(self.failed_event(20, period_end=self.p2))
        self.webhook(self.sub_event("updated", "past_due", 20, period_end=self.p2))
        self.assertEqual(self.record(user_id)["status"], "canceled")
        self.assert_covers(user_id, self.p1)
        self.webhook(self.invoice_event(30, period_end=self.p2))
        self.webhook(self.sub_event("updated", "active", 30, period_end=self.p2))
        self.assertEqual(self.record(user_id)["status"], "active")
        self.assert_covers(user_id, self.p2)

    def test_an_older_failure_arriving_after_the_payment_changes_nothing(self):
        user_id, _ = self.buy_paid()
        self.webhook(self.invoice_event(30, period_end=self.p2))
        self.webhook(self.sub_event("updated", "active", 30, period_end=self.p2))
        before = self.stable(user_id)
        self.webhook(self.failed_event(20, period_end=self.p2))
        self.webhook(self.sub_event("updated", "past_due", 20, period_end=self.p2))
        self.webhook(self.sub_event("updated", "unpaid", 21, period_end=self.p2))
        self.assertEqual(self.stable(user_id), before)
        self.assertEqual(self.record(user_id)["status"], "active")
        self.assert_covers(user_id, self.p2)

    def test_a_failure_newer_than_the_payment_still_counts(self):
        user_id, _ = self.buy_paid()
        self.webhook(self.invoice_event(30, period_end=self.p2))
        self.webhook(self.sub_event("updated", "past_due", 50, period_end=self.p3))
        self.assertEqual(self.record(user_id)["status"], "canceled")
        self.assert_covers(user_id, self.p2)   # what was paid for, no more

    def test_a_delayed_payment_after_a_newer_failure_extends_access_not_status(self):
        user_id, _ = self.buy_paid()
        self.webhook(self.sub_event("updated", "past_due", 50, period_end=self.p3))
        self.webhook(self.invoice_event(30, period_end=self.p2))   # late, but real money
        self.assert_covers(user_id, self.p2)
        self.assertEqual(self.record(user_id)["status"], "canceled")


class DuplicatesAndDelays(_OrderCase):
    def _renewal(self):
        return [self.sub_event("updated", "active", 20, period_end=self.p2),
                self.invoice_event(21, period_end=self.p2),
                self.invoice_event(21, period_end=self.p2, kind="invoice.payment_succeeded")]

    def test_every_event_delivered_twice_changes_nothing_further(self):
        user_id, _ = self.buy_paid()
        events = self._renewal()
        for event in events:
            self.webhook(event)
        once = self.stable(user_id)
        for event in events:
            self.webhook(event)
            self.webhook(event)
        self.assertEqual(self.stable(user_id), once)
        self.assertEqual(len(customers.list_subscription_rows()), 1)

    def test_a_duplicate_does_not_even_rewrite_the_row(self):
        user_id, _ = self.buy_paid()
        for event in self._renewal():
            self.webhook(event)
        written = self.record(user_id)["updated_at"]
        for event in self._renewal():
            self.webhook(event)
        self.assertEqual(self.record(user_id)["updated_at"], written)

    def test_the_whole_purchase_delivered_twice(self):
        started = self.signup("twice@example.com")
        user_id = started["user_id"]
        story = [self.session_event(user_id),
                 self.sub_event("created", "active", 1, period_end=self.p1),
                 self.invoice_event(2, period_end=self.p1, reason="subscription_create")]
        for event in story:
            self.webhook(event)
        once = self.stable(user_id)
        for event in story + story:
            self.webhook(event)
        self.assertEqual(self.stable(user_id), once)
        self.assert_covers(user_id, self.p1)

    def test_a_delayed_paid_event_for_a_period_already_recorded_changes_nothing(self):
        user_id, _ = self.buy_paid()
        self.webhook(self.invoice_event(21, period_end=self.p2))
        self.webhook(self.sub_event("updated", "active", 22, period_end=self.p2))
        before = self.stable(user_id)
        # The first period's invoice, delivered again a month late.
        self.webhook(self.invoice_event(2, period_end=self.p1, reason="subscription_create"))
        self.webhook(self.sub_event("created", "active", 1, period_end=self.p1))
        self.assertEqual(self.stable(user_id), before)
        self.assert_covers(user_id, self.p2)


class Renewals(_OrderCase):
    def test_a_renewal_that_pays_extends_access_by_the_invoice_period(self):
        user_id, token = self.buy_paid()
        self.webhook(self.sub_event("updated", "active", 20, period_end=self.p2))
        self.webhook(self.invoice_event(21, period_end=self.p2))
        self.assertEqual(self.paid_through(user_id), _iso(self.p2))
        self.assertTrue(self.has_access(user_id, self.p1 + 3600))
        self.assertEqual(self.open_paid_page(token).id, user_id)

    def test_a_renewal_that_fails_then_retries_and_pays(self):
        user_id, _ = self.buy_paid()
        self.webhook(self.sub_event("updated", "past_due", 20, period_end=self.p2))
        self.webhook(self.failed_event(20, period_end=self.p2))
        self.assert_covers(user_id, self.p1)
        self.webhook(self.failed_event(25, period_end=self.p2))        # a second decline
        self.assert_covers(user_id, self.p1)
        self.webhook(self.invoice_event(30, period_end=self.p2))
        self.assert_covers(user_id, self.p2)

    def test_a_renewal_that_never_pays_ends_where_the_paid_period_ended(self):
        user_id, token = self.buy_paid()
        self.webhook(self.sub_event("updated", "active", 20, period_end=self.p2))
        self.webhook(self.sub_event("updated", "past_due", 21, period_end=self.p2))
        self.webhook(self.sub_event("updated", "unpaid", 90, period_end=self.p2))
        self.assert_covers(user_id, self.p1)


class CancellationPolicy(_OrderCase):
    def test_cancel_at_period_end_keeps_what_was_paid_for(self):
        user_id, token = self.buy_paid()
        self.webhook(self.sub_event("updated", "active", 10, period_end=self.p1,
                                    cancel_at=self.p1))
        self.assertEqual(self.record(user_id)["cancel_at"], _iso(self.p1))
        self.assert_covers(user_id, self.p1)
        self.assertEqual(self.open_paid_page(token).id, user_id)

    def test_a_late_paid_event_for_the_already_covered_period_changes_nothing(self):
        user_id, _ = self.buy_paid()
        self.webhook(self.sub_event("updated", "active", 10, period_end=self.p1,
                                    cancel_at=self.p1))
        before = self.stable(user_id)
        self.webhook(self.invoice_event(2, period_end=self.p1, reason="subscription_create"))
        for key in ("status", "cancel_at", "paid_through"):
            self.assertEqual(self.record(user_id)[key], before[key], key)
        self.assert_covers(user_id, self.p1)

    def test_deleted_ends_access_at_the_paid_through_instant(self):
        user_id, token = self.buy_paid()
        self.webhook(self.sub_event("deleted", "canceled", 40, period_end=self.p1))
        self.assertEqual(self.record(user_id)["status"], "canceled")
        self.assert_covers(user_id, self.p1)            # not earlier, not later
        self.assertEqual(self.open_paid_page(token).id, user_id)

    def test_deleted_announcing_a_later_end_does_not_extend_access(self):
        user_id, _ = self.buy_paid()
        self.webhook(self.sub_event("deleted", "canceled", 40, period_end=self.p2))
        self.assert_covers(user_id, self.p1)

    def test_deleted_after_the_period_has_run_out_refuses(self):
        long_ago = _epoch(self.now - timedelta(hours=1))
        user_id, token = self.buy_paid(end=long_ago)
        self.webhook(self.sub_event("deleted", "canceled", 40, period_end=long_ago))
        self.assert_refused(token)

    def test_an_older_update_after_deleted_does_not_resurrect_the_subscription(self):
        user_id, _ = self.buy_paid()
        self.webhook(self.sub_event("deleted", "canceled", 40, period_end=self.p1))
        self.webhook(self.sub_event("updated", "active", 30, period_end=self.p2))
        self.assertEqual(self.record(user_id)["status"], "canceled")
        self.assert_covers(user_id, self.p1)


class MoreThanOneSubscriptionId(_OrderCase):
    SECOND = "sub_second_synthetic"

    def test_a_second_subscription_while_the_first_is_paid_keeps_the_paid_time(self):
        user_id, _ = self.buy_paid()
        self.webhook(self.sub_event("created", "incomplete", 100, period_end=self.p2,
                                    sub=self.SECOND, sub_created_minute=100))
        self.assert_covers(user_id, self.p1)
        self.assertEqual(self.record(user_id)["stripe_subscription_id"], self.SECOND)

    def test_the_second_subscription_when_paid_extends_and_becomes_the_record(self):
        user_id, _ = self.buy_paid()
        self.webhook(self.sub_event("created", "active", 100, period_end=self.p2,
                                    sub=self.SECOND, sub_created_minute=100))
        self.webhook(self.invoice_event(101, period_end=self.p2, sub=self.SECOND,
                                        reason="subscription_create"))
        record = self.record(user_id)
        self.assertEqual(record["stripe_subscription_id"], self.SECOND)
        self.assertEqual(record["status"], "active")
        self.assert_covers(user_id, self.p2)

    def test_events_for_an_old_subscription_never_touch_the_newer_record(self):
        user_id, _ = self.buy_paid()
        self.webhook(self.sub_event("created", "active", 100, period_end=self.p2,
                                    sub=self.SECOND, sub_created_minute=100))
        self.webhook(self.invoice_event(101, period_end=self.p2, sub=self.SECOND,
                                        reason="subscription_create"))
        before = self.stable(user_id)
        for late in (
                self.sub_event("updated", "past_due", 120, period_end=self.p3),
                self.sub_event("updated", "unpaid", 121, period_end=self.p3),
                self.sub_event("deleted", "canceled", 122, period_end=self.p1),
                self.sub_event("updated", "active", 123, period_end=self.p3,
                               cancel_at=self.p1),
                self.failed_event(124, period_end=self.p3),
                self.session_event(user_id, minute=0)):
            self.assertEqual(self.webhook(late), {"received": True})
            self.assertEqual(self.stable(user_id), before, late["type"])
        self.assert_covers(user_id, self.p2)

    def test_an_old_subscription_with_no_timestamps_cannot_overwrite_a_paid_record(self):
        user_id, _ = self.buy_paid()
        late = self.sub_event("deleted", "canceled", 5, period_end=self.p1, sub="sub_old")
        del late["created"]
        del late["data"]["object"]["created"]
        before = self.stable(user_id)
        self.webhook(late)
        self.assertEqual(self.stable(user_id), before)


class EveryOrderEndsTheSame(_OrderCase):
    """One realistic renewal's whole event set, delivered in every possible
    order. The final access has to be the same in all of them."""

    def _run_all_orders(self, make_events, expected_status, expected_end):
        seen = set()
        count = 0
        for order in itertools.permutations(range(len(make_events()))):
            count += 1
            user_id = self.seed_paid()
            events = make_events()
            for index in order:
                self.assertEqual(self.webhook(events[index]), {"received": True})
            record = self.record(user_id)
            outcome = (record["status"], record["paid_through"], record["cancel_at"],
                       self.has_access(user_id, expected_end - 3600),
                       self.has_access(user_id, expected_end + 3600))
            seen.add(outcome)
        self.assertEqual(len(seen), 1, f"orders disagreed: {sorted(map(str, seen))}")
        status, end, _, inside, after = seen.pop()
        self.assertEqual((status, end, inside, after),
                         (expected_status, _iso(expected_end), True, False))
        self.assertGreater(count, 1)

    def test_a_renewal_that_pays(self):
        self._run_all_orders(lambda: [
            self.sub_event("updated", "active", 20, period_end=self.p2),
            self.invoice_event(21, period_end=self.p2),
            self.invoice_event(21, period_end=self.p2, kind="invoice.payment_succeeded"),
            self.sub_event("updated", "active", 22, period_end=self.p2, cancel_at=None),
        ], "active", self.p2)

    def test_a_renewal_that_fails_then_pays_on_retry(self):
        self._run_all_orders(lambda: [
            self.sub_event("updated", "past_due", 20, period_end=self.p2),
            self.failed_event(20, period_end=self.p2),
            self.invoice_event(30, period_end=self.p2),
            self.sub_event("updated", "active", 30, period_end=self.p2),
        ], "active", self.p2)

    def test_a_renewal_that_fails_and_never_pays(self):
        count = 0
        outcomes = set()
        for order in itertools.permutations(range(3)):
            count += 1
            user_id = self.seed_paid()
            events = [self.sub_event("updated", "active", 19, period_end=self.p2),
                      self.sub_event("updated", "past_due", 20, period_end=self.p2),
                      self.failed_event(20, period_end=self.p2)]
            for index in order:
                self.webhook(events[index])
            record = self.record(user_id)
            outcomes.add((record["paid_through"], self.has_access(user_id, self.p1 - 3600),
                          self.has_access(user_id, self.p1 + 3600)))
        self.assertEqual(outcomes, {(_iso(self.p1), True, False)})


class TheWebhookAlwaysAnswersAndNeverLeaks(_OrderCase):
    def test_every_well_formed_event_gets_a_200(self):
        user_id, _ = self.buy_paid()
        odd = [
            self.invoice_event(5, period_end=self.p2, sub=None),                    # no subscription
            {"id": "evt_nolines", "type": "invoice.paid", "created": self.at(6),
             "data": {"object": {"customer": CUSTOMER, "subscription": SUBSCRIPTION,
                                 "status": "paid"}}},
            {"id": "evt_badlines", "type": "invoice.paid", "created": self.at(7),
             "data": {"object": {"customer": CUSTOMER, "subscription": SUBSCRIPTION,
                                 "status": "paid", "lines": {"data": [None, {"period": "x"},
                                                                      {"period": {"end": "soon"}}]}}}},
            {"id": "evt_stranger", "type": "invoice.paid", "created": self.at(8),
             "data": {"object": {"customer": "cus_nobody", "subscription": "sub_x",
                                 "status": "paid", "lines": {"data": [
                                     {"period": {"end": self.p3}}]}}}},
            {"id": "evt_notime", "type": "customer.subscription.updated",
             "data": {"object": {"id": SUBSCRIPTION, "customer": CUSTOMER, "status": "active",
                                 "created": "yesterday"}}},
            {"id": "evt_other", "type": "invoice.finalized", "created": self.at(9),
             "data": {"object": {}}},
            {"id": "evt_empty", "type": "invoice.paid"},
        ]
        before = self.paid_through(user_id)
        for event in odd:
            self.assertEqual(self.webhook(event), {"received": True}, event["id"])
        self.assertEqual(self.paid_through(user_id), before)
        self.assert_covers(user_id, self.p1)

    def test_nothing_in_the_log_names_the_account_the_email_or_a_secret(self):
        captured = io.StringIO()
        with redirect_stderr(captured):
            started = self.signup("private-person@example.com")
            user_id = started["user_id"]
            for event in (self.session_event(user_id),
                          self.sub_event("created", "active", 1, period_end=self.p1),
                          self.invoice_event(2, period_end=self.p1),
                          self.sub_event("updated", "past_due", 20, period_end=self.p2),
                          self.failed_event(20, period_end=self.p2),
                          self.invoice_event(30, period_end=self.p2)):
                self.webhook(event)
        logged = captured.getvalue()
        self.assertNotIn("private-person@example.com", logged)
        self.assertNotIn(acceptance.WEBHOOK_SECRET, logged)
        self.assertNotIn("whsec", logged)
        self.assertNotIn(f"user={user_id} ", logged)
        self.assertNotIn(f"user_id={user_id}", logged)


class TheBillingPageAndCancelNeverPromiseAnUnpaidPeriod(_OrderCase):
    """Two more doors a Stripe-announced period could walk through: the page's
    own status read, and POST /billing/cancel, which writes the provider's
    live answer (the in-process Stripe stand-in always reports an active
    subscription whose period ends in 2099) into the local table."""

    def _user(self, user_id):
        from src.appstate import users as users_store
        return users_store.get_user(user_id)

    def test_status_reports_the_paid_through_not_the_announced_end(self):
        from api.billing import billing_status
        user_id, _ = self.buy_paid()
        self.webhook(self.sub_event("updated", "active", 20, period_end=self.p2))
        shown = billing_status(current_user=self._user(user_id))
        self.assertEqual(shown["current_period_end"], _iso(self.p1))

    def test_cancel_does_not_turn_the_announced_period_into_access(self):
        from api.billing import cancel_subscription
        user_id, token = self.buy_paid()
        result = cancel_subscription(current_user=self._user(user_id), _rate_limit=None)
        self.assertTrue(result["cancel_at_period_end"], result)
        self.assertEqual(result["current_period_end"], _iso(self.p1))
        self.assertEqual(self.paid_through(user_id), _iso(self.p1))
        self.assert_covers(user_id, self.p1)

    def test_cancel_on_a_lapsed_customer_whose_renewal_failed_grants_nothing(self):
        from api.billing import cancel_subscription
        long_ago = _epoch(self.now - timedelta(days=2))
        user_id, token = self.buy_paid(end=long_ago)
        self.webhook(self.sub_event("updated", "past_due", 20, period_end=self.p2))
        cancel_subscription(current_user=self._user(user_id), _rate_limit=None)
        self.assert_refused(token)


class AnExpiredRenewalCanBeBoughtAgain(_OrderCase):
    def test_paying_again_after_a_lapse_restores_access_through_the_new_period(self):
        long_ago = _epoch(self.now - timedelta(days=2))
        user_id, token = self.buy_paid(end=long_ago)
        self.assert_refused(token)
        self.webhook(self.sub_event("updated", "active", 60, period_end=self.p2))
        self.assert_refused(token)                       # announcement alone: still nothing
        self.webhook(self.invoice_event(61, period_end=self.p2))
        self.assertEqual(self.open_paid_page(token).id, user_id)


class MigrationFromTheOldSchema(unittest.TestCase):
    """An app.db written by the code before this change: the table has no
    `paid_through` or ordering columns. Opening it must add them additively,
    keep every customer's access, and not do it twice."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "old_app.db"
        self.future = (datetime.now(timezone.utc) + timedelta(days=12)).isoformat()
        self.past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("""CREATE TABLE billing_customers (
                user_id INTEGER PRIMARY KEY, stripe_customer_id TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE billing_subscriptions (
                user_id INTEGER PRIMARY KEY, stripe_subscription_id TEXT NOT NULL,
                status TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            conn.execute("ALTER TABLE billing_subscriptions ADD COLUMN cancel_at TEXT")
            conn.execute("ALTER TABLE billing_subscriptions ADD COLUMN current_period_end TEXT")
            rows = [
                (1, "sub_active_with_end", "active", None, self.future),
                (2, "sub_canceled_with_time_left", "canceled", self.future, self.future),
                (3, "sub_active_no_end", "active", None, None),
                (4, "sub_canceled_lapsed", "canceled", None, self.past),
                (5, "sub_trialing", "trialing", None, self.future),
            ]
            for user_id, sub, status, cancel_at, end in rows:
                conn.execute(
                    "INSERT INTO billing_subscriptions (user_id, stripe_subscription_id, "
                    "status, cancel_at, current_period_end, updated_at) VALUES (?,?,?,?,?,?)",
                    (user_id, sub, status, cancel_at, end, "2026-09-01T00:00:00+00:00"))
                conn.execute("INSERT INTO billing_customers VALUES (?,?,?)",
                             (user_id, f"cus_{user_id}", "2026-09-01T00:00:00+00:00"))

    def columns(self):
        with closing(sqlite3.connect(self.db)) as conn:
            return {row[1] for row in conn.execute("PRAGMA table_info(billing_subscriptions)")}

    def test_opening_it_adds_the_columns_and_keeps_every_paid_customer_paid(self):
        self.assertNotIn("paid_through", self.columns())
        access = {uid: customers.has_paid_access(uid, db=self.db) for uid in range(1, 6)}
        self.assertTrue({"paid_through", "sub_created_at", "snapshot_at",
                         "paid_at"} <= self.columns())
        # Active-with-an-end and trialing keep that end; a canceled customer
        # with time left keeps it; a lapsed one stays lapsed; an active row
        # that never recorded any end has nothing to honour.
        self.assertEqual(access, {1: True, 2: True, 3: False, 4: False, 5: True})
        record = customers.get_subscription_record(1, db=self.db)
        self.assertEqual(record["paid_through"], self.future)
        self.assertEqual(record["current_period_end"], self.future)

    def test_it_is_idempotent_and_never_backfills_a_row_written_later(self):
        customers.has_paid_access(1, db=self.db)
        # A row the NEW code writes with an announced end and no payment
        # evidence: paid_through stays empty on every later open.
        customers.upsert_subscription(
            6, "sub_new", "active", current_period_end=self.future,
            paid_through=None, db=self.db)
        for _ in range(3):
            self.assertIsNone(customers.get_subscription_record(6, db=self.db)["paid_through"])
            self.assertFalse(customers.has_paid_access(6, db=self.db))
        self.assertTrue(customers.has_paid_access(1, db=self.db))

    def test_a_webhook_works_on_the_migrated_database(self):
        end = int((datetime.now(timezone.utc) + timedelta(days=45)).timestamp())
        event = {"id": "evt_inv", "type": "invoice.paid", "created": 1_790_000_000,
                 "data": {"object": {"customer": "cus_1", "subscription": "sub_active_with_end",
                                     "status": "paid", "lines": {"data": [
                                         {"period": {"end": end}}]}}}}
        billing.apply_stripe_webhook_event(event, db=self.db)
        record = customers.get_subscription_record(1, db=self.db)
        self.assertEqual(record["paid_through"], _iso(end))
        self.assertTrue(customers.has_paid_access(
            1, now=datetime.fromtimestamp(end - 3600, tz=timezone.utc), db=self.db))


if __name__ == "__main__":
    unittest.main()
