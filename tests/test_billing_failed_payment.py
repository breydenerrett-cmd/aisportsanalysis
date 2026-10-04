"""A failed payment must end access when the PAID period ends.

The known flaw (config/business.json, 2026-10-01): when a renewal charge
fails, Stripe moves the subscription to `past_due` and the event carries the
NEW `current_period_end`. The webhook handler stored that new end next to the
collapsed status "canceled", and has_paid_access reads "canceled + a future
period end" as a cancelled customer still inside what they paid for -- so a
card that never paid kept a whole extra period of access.

These tests drive the same signed-webhook entry point as
tests/test_billing_acceptance_path.py, with events shaped as Stripe sends
them, and pin the money rule: access runs to the end of the period that was
actually paid for (or the trial that was actually free), never past it
because a charge was attempted and declined.

Billing stays off in production; nothing here can reach Stripe.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone

try:
    from fastapi import HTTPException
except ImportError:  # pragma: no cover
    HTTPException = Exception  # the base class is skipped without FastAPI

from src.appstate import customers, reqlog
from tests import test_billing_acceptance_path as acceptance

CUSTOMER = acceptance.CUSTOMER
SUBSCRIPTION = acceptance.SUBSCRIPTION


def _epoch(moment: datetime) -> int:
    return int(moment.timestamp())


class _FailedPaymentCase(acceptance._Case):
    def setUp(self):
        super().setUp()
        self.now = datetime.now(timezone.utc)

    def iso(self, moment: datetime) -> str:
        return datetime.fromtimestamp(_epoch(moment), tz=timezone.utc).isoformat()

    def invoice_failed(self, event_id="evt_invoice_failed", attempt=1):
        return {"id": event_id, "type": "invoice.payment_failed",
                "data": {"object": {"id": "in_1", "customer": CUSTOMER,
                                    "subscription": SUBSCRIPTION,
                                    "attempt_count": attempt, "paid": False}}}

    def sub_event(self, kind, status, period_end, *, cancel_at=None, event_id=None):
        event = self.subscription_event(kind, status, period_end=_epoch(period_end),
                                        cancel_at=_epoch(cancel_at) if cancel_at else None)
        if event_id:
            event["id"] = event_id
        return event

    def start(self, status, period_end, email="payer@example.com"):
        """signup -> checkout completed -> the first subscription event, with
        the period end Stripe would have reported at that moment."""
        started = self.signup(email)
        user_id = started["user_id"]
        self.webhook(self.completed_event(user_id))
        self.webhook(self.sub_event("created", status, period_end))
        return user_id, self.collect_token()["token"]

    def assert_refused(self, token):
        with self.assertRaises(HTTPException) as refused:
            self.open_paid_page(token)
        self.assertEqual(refused.exception.status_code, 402)

    def end_of(self, user_id):
        return customers.get_subscription_record(user_id)["current_period_end"]


class FirstChargeFailsAfterTheTrial(_FailedPaymentCase):
    """(a) A card trial ends, the first real charge is declined."""

    def setUp(self):
        super().setUp()
        self.trial_end = self.now - timedelta(hours=1)
        self.new_end = self.now + timedelta(days=30)
        self.user_id, self.token = self.start("trialing", self.trial_end)

    def fail_the_charge(self):
        self.assertEqual(self.webhook(self.invoice_failed()), {"received": True})
        self.webhook(self.sub_event("updated", "past_due", self.new_end))

    def test_access_ends_at_the_trials_end_not_the_new_periods_end(self):
        self.fail_the_charge()
        self.assertEqual(self.end_of(self.user_id), self.iso(self.trial_end))
        self.assertFalse(customers.has_paid_access(self.user_id))
        self.assert_refused(self.token)

    def test_the_trial_the_buyer_really_had_is_still_honoured_inside_it(self):
        self.fail_the_charge()
        inside = self.trial_end - timedelta(minutes=5)
        self.assertTrue(customers.has_paid_access(self.user_id, now=inside))
        self.assertFalse(customers.has_paid_access(
            self.user_id, now=self.trial_end + timedelta(seconds=1)))

    def test_the_failed_invoice_alone_changes_nothing_and_is_logged(self):
        before = customers.get_subscription_record(self.user_id)
        captured = io.StringIO()
        with redirect_stderr(captured):
            self.assertEqual(self.webhook(self.invoice_failed()), {"received": True})
        after = customers.get_subscription_record(self.user_id)
        self.assertEqual(
            {k: v for k, v in after.items() if k != "updated_at"},
            {k: v for k, v in before.items() if k != "updated_at"})
        line = captured.getvalue()
        self.assertIn("invoice.payment_failed", line)
        # The same hashed reference the request log prints, never the raw id.
        self.assertIn(f"user={reqlog.user_ref(self.user_id)}", line)
        self.assertNotIn(f"user={self.user_id} ", line)
        self.assertNotIn("whsec", line)

    def test_a_second_decline_changes_nothing(self):
        self.fail_the_charge()
        self.webhook(self.invoice_failed("evt_invoice_failed_2", attempt=2))
        self.webhook(self.sub_event("updated", "past_due", self.new_end,
                                    event_id="evt_second_past_due"))
        self.assertEqual(self.end_of(self.user_id), self.iso(self.trial_end))
        self.assert_refused(self.token)


class RenewalFailsAfterAPaidMonth(_FailedPaymentCase):
    """(b) A paid month, then the renewal charge is declined."""

    def setUp(self):
        super().setUp()
        self.paid_end = self.now - timedelta(hours=1)
        self.new_end = self.now + timedelta(days=30)
        self.user_id, self.token = self.start("active", self.paid_end)

    def test_access_ends_at_the_end_of_the_paid_period(self):
        self.webhook(self.invoice_failed())
        self.webhook(self.sub_event("updated", "past_due", self.new_end))
        self.assertEqual(self.end_of(self.user_id), self.iso(self.paid_end))
        self.assertFalse(customers.has_paid_access(self.user_id))
        self.assert_refused(self.token)

    def test_every_failure_status_stops_at_the_paid_end(self):
        for status in ("past_due", "unpaid", "incomplete", "incomplete_expired"):
            with self.subTest(status=status):
                self.webhook(self.sub_event("updated", status, self.new_end,
                                            event_id=f"evt_{status}"))
                self.assertEqual(self.end_of(self.user_id), self.iso(self.paid_end))
                self.assertFalse(customers.has_paid_access(self.user_id))


class TheRetrySucceeds(_FailedPaymentCase):
    """(c) After a decline, the card is fixed and Stripe's retry pays."""

    def test_access_runs_through_the_new_period_after_either_failure(self):
        for first_status, label in (("trialing", "trial"), ("active", "paid month")):
            with self.subTest(after=label):
                self.setUp()
                old_end = self.now - timedelta(hours=1)
                new_end = self.now + timedelta(days=30)
                user_id, token = self.start(first_status, old_end)
                self.webhook(self.invoice_failed())
                self.webhook(self.sub_event("updated", "past_due", new_end))
                self.assert_refused(token)
                self.webhook(self.sub_event("updated", "active", new_end,
                                            event_id="evt_retry_paid"))
                self.assertEqual(self.open_paid_page(token).id, user_id)
                self.assertEqual(self.end_of(user_id), self.iso(new_end))
                self.assertTrue(customers.has_paid_access(
                    user_id, now=new_end - timedelta(days=1)))


class WhatMustKeepWorking(_FailedPaymentCase):
    """(d) The paths the fix must not disturb."""

    def test_a_normal_renewal_still_extends_access(self):
        user_id, token = self.start("active", self.now + timedelta(days=2))
        later = self.now + timedelta(days=32)
        self.webhook(self.sub_event("updated", "active", later, event_id="evt_renewal"))
        self.assertEqual(self.end_of(user_id), self.iso(later))
        self.assertEqual(self.open_paid_page(token).id, user_id)

    def test_cancel_at_period_end_keeps_what_was_paid_for(self):
        end = self.now + timedelta(days=10)
        user_id, token = self.start("active", end)
        self.webhook(self.sub_event("updated", "active", end, cancel_at=end,
                                    event_id="evt_cancel_scheduled"))
        self.assertEqual(self.open_paid_page(token).id, user_id)
        self.assertTrue(customers.has_paid_access(user_id, now=end - timedelta(hours=1)))
        self.assertFalse(customers.has_paid_access(user_id, now=end + timedelta(hours=1)))

    def test_a_redelivered_completed_event_does_not_revive_a_failed_payment(self):
        user_id, token = self.start("active", self.now - timedelta(hours=1))
        self.webhook(self.sub_event("updated", "past_due", self.now + timedelta(days=30)))
        for _ in range(2):
            self.webhook(self.completed_event(user_id))
        self.assert_refused(token)

    def test_a_past_due_event_delivered_twice_extends_nothing(self):
        paid_end = self.now - timedelta(hours=1)
        user_id, token = self.start("active", paid_end)
        event = self.sub_event("updated", "past_due", self.now + timedelta(days=30))
        for _ in range(3):
            self.webhook(event)
        self.assertEqual(self.end_of(user_id), self.iso(paid_end))
        self.assertEqual(len(customers.list_subscription_rows()), 1)
        self.assert_refused(token)

    def test_a_stale_active_event_arriving_after_the_failure_grants_nothing(self):
        """Stripe does not order or de-duplicate: the pre-failure `active`
        event, delivered again after `past_due`, must not undo it."""
        paid_end = self.now - timedelta(hours=1)
        user_id, token = self.start("active", paid_end)
        self.webhook(self.sub_event("updated", "past_due", self.now + timedelta(days=30)))
        self.webhook(self.sub_event("created", "active", paid_end, event_id="evt_stale"))
        self.assertFalse(customers.has_paid_access(user_id))
        self.assert_refused(token)

    def test_a_failure_event_for_an_unknown_customer_is_acknowledged(self):
        # Nothing is recorded, nothing raises: Stripe must see a 200.
        self.assertEqual(self.webhook(self.invoice_failed()), {"received": True})
        self.assertEqual(customers.list_subscription_rows(), [])

    def test_a_failure_with_no_prior_period_end_grants_nothing(self):
        """A past_due event that is the first the app hears of the
        subscription has no paid period on record to honour; absent data is
        absent, so it must not hand out the period end it carries."""
        started = self.signup("lonely@example.com")
        customers.upsert_customer(started["user_id"], CUSTOMER)
        self.webhook(self.sub_event("updated", "past_due", self.now + timedelta(days=30)))
        self.assertFalse(customers.has_paid_access(started["user_id"]))


if __name__ == "__main__":
    unittest.main()
