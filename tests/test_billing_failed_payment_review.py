"""Red-team review of the failed-payment fix (commits 9f54a046..5d6d4b39).

Each test tells one story where the new rules hurt a customer who paid, or
break the webhook's "always answer 200" promise. They fail against
src/appstate/billing.py as of 5d6d4b39; the smallest fix for each is in its
docstring.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr
from datetime import timedelta

from src.appstate import customers
from tests.test_billing_failed_payment import (
    CUSTOMER, SUBSCRIPTION, _FailedPaymentCase)


class RecoveryWithTheSamePeriodEnd(_FailedPaymentCase):
    """A decline that does not move the period end (a mid-period plan change
    or proration invoice that fails, then the card is fixed) recovers with
    `active` and the SAME end. The stale-drop rule (`incoming_end <=
    recorded_end`) discards that genuine recovery, leaving a paying customer
    recorded as "canceled" with a hard expiry at the period end.

    Smallest fix: in the stale-drop branch only drop when the recorded end is
    already in the past (`recorded_end <= now`). With time still on the
    record the customer has access either way, so applying an equal-end paid
    event is harmless and restores the honest status.
    """

    def test_midperiod_decline_then_fixed_card_returns_to_active(self):
        end = self.now + timedelta(days=20)
        user_id, _ = self.start("active", end)
        self.webhook(self.sub_event("updated", "past_due", end, event_id="evt_blip"))
        self.webhook(self.sub_event("updated", "active", end, event_id="evt_fixed"))
        record = customers.get_subscription_record(user_id)
        self.assertEqual(record["status"], "active", record)
        # A paying customer is not on a hard clock that a late renewal
        # webhook can trip: an active record never expires by itself.
        self.assertTrue(customers.has_paid_access(
            user_id, now=end + timedelta(hours=1)))

    def test_a_late_decline_after_recovery_is_repaired_by_the_redelivered_recovery(self):
        """past_due(N) -> active(N) -> a LATE past_due(N) -> Stripe redelivers
        active(N). The customer paid; the end state must be active."""
        paid_end = self.now - timedelta(hours=1)
        new_end = self.now + timedelta(days=30)
        user_id, _ = self.start("active", paid_end)
        self.webhook(self.sub_event("updated", "past_due", new_end, event_id="pd1"))
        self.webhook(self.sub_event("updated", "active", new_end, event_id="ok1"))
        self.webhook(self.sub_event("updated", "past_due", new_end, event_id="pd1_late"))
        self.webhook(self.sub_event("updated", "active", new_end, event_id="ok1_retry"))
        self.assertEqual(customers.get_subscription_record(user_id)["status"], "active")


class ANewSubscriptionInAFailedStateDoesNotWipePaidTime(_FailedPaymentCase):
    """A customer with paid time left on subscription A starts a new
    subscription B that is `incomplete` (3-D Secure pending). With no record
    for B the handler writes B/canceled/no end over A's row, and the paid
    remainder of A is gone at once.

    Smallest fix: in the failed-status branch, when the subscription id
    differs from the recorded one and the recorded row still has access
    (`customers.has_paid_access(user_id)`), return without writing; B's own
    `active` event overwrites normally when it is actually paid.
    """

    def test_incomplete_second_subscription_leaves_the_paid_remainder(self):
        end = self.now + timedelta(days=10)
        user_id, token = self.start("active", end, email="again@example.com")
        event = self.sub_event("created", "incomplete", end, event_id="evt_b")
        event["data"]["object"]["id"] = "sub_second"
        self.webhook(event)
        self.assertTrue(customers.has_paid_access(user_id))
        self.assertEqual(self.open_paid_page(token).id, user_id)


class TheNewLogLineAndTheWebhookStayWellBehaved(_FailedPaymentCase):
    """invoice.payment_failed used to be ignored (always 200). Now it reads
    fields from the payload. Stripe signs the body, so these shapes are
    unlikely, but the endpoint's contract is that nothing raises.

    Smallest fix: look the user up only when `customer` is a str, and print
    the free-text fields through `repr()` of a length-capped str so a
    newline cannot start a second log line.
    """

    def test_a_non_string_customer_is_acknowledged(self):
        event = self.invoice_failed()
        event["data"]["object"]["customer"] = {"id": CUSTOMER}   # an expanded object
        self.assertEqual(self.webhook(event), {"received": True})

    def test_a_newline_in_a_field_cannot_forge_a_second_log_line(self):
        event = self.invoice_failed()
        event["data"]["object"]["subscription"] = (
            "sub_x\nbilling: invoice.payment_failed user=deadbeef subscription=fake attempt=9")
        captured = io.StringIO()
        with redirect_stderr(captured):
            self.webhook(event)
        lines = [l for l in captured.getvalue().splitlines()
                 if "invoice.payment_failed" in l]
        self.assertEqual(len(lines), 1, lines)


if __name__ == "__main__":
    unittest.main()
