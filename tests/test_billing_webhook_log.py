"""The one `billing: webhook ...` log line per processed Stripe event.

Why it exists: the request log says only `POST /billing/webhook status=200
user=-` for every webhook, so during the purchase rehearsal nobody reading the
staging log could tell `checkout.session.completed` from `invoice.paid`
(docs/billing/PURCHASE_REHEARSAL.md). The line names the event type, the event
id, the hashed user reference, and the stored paid-through DATE and status.

It must be non-secret (no email, no raw account id, no token, no secret), must
never change what Stripe is answered or what is stored, and `invoice.payment_failed`
keeps its own existing line instead of getting a second one.
"""

from __future__ import annotations

import io
import re
import unittest
from contextlib import redirect_stderr
from datetime import timedelta
from unittest import mock

from src.appstate import billing, customers, reqlog
from tests import test_billing_acceptance_path as acceptance
from tests import test_billing_failed_payment as failed

LINE = re.compile(
    r"billing: webhook type='([^']*)' event='([^']*)' user=(-|[0-9a-f]{16}) "
    r"paid_through=(-|'[^']*') status=(-|'[^']*')")


@unittest.skipUnless(acceptance.HAS_FASTAPI, "FastAPI is not installed")
class WebhookLogLine(failed._FailedPaymentCase):
    def run_events(self, *events):
        captured = io.StringIO()
        with redirect_stderr(captured):
            for event in events:
                self.assertEqual(self.webhook(event), {"received": True})
        return captured.getvalue()

    def webhook_lines(self, text):
        return [m.groups() for m in LINE.finditer(text)]

    def test_each_processed_event_writes_one_line_naming_its_type(self):
        user_id = self.signup("private-person@example.com")["user_id"]
        end = self.now + timedelta(days=30)
        text = self.run_events(
            self.completed_event(user_id),
            self.sub_event("created", "active", end, event_id="evt_sub_created"),
            self.invoice_paid(end, event_id="evt_paid"))
        lines = self.webhook_lines(text)
        self.assertEqual([line[0] for line in lines],
                         ["checkout.session.completed", "customer.subscription.created",
                          "invoice.paid"])
        self.assertEqual(lines[2][1], "evt_paid")
        mine = reqlog.user_ref(user_id)
        self.assertEqual({line[2] for line in lines}, {mine})

    def test_the_paid_through_is_not_set_by_the_checkout_page_alone_but_is_by_the_invoice(self):
        user_id = self.signup()["user_id"]
        end = self.now + timedelta(days=30)
        completed = self.webhook_lines(self.run_events(self.completed_event(user_id)))
        self.assertEqual(completed[0][3], "-")
        paid = self.webhook_lines(self.run_events(self.invoice_paid(end)))
        self.assertEqual(paid[0][3], repr(customers.get_subscription_record(user_id)["paid_through"]))
        self.assertNotEqual(paid[0][3], "-")

    def test_a_duplicate_delivery_writes_a_line_each_time_and_changes_nothing(self):
        user_id = self.signup()["user_id"]
        end = self.now + timedelta(days=30)
        self.run_events(self.completed_event(user_id), self.invoice_paid(end))
        before = customers.get_subscription_record(user_id)
        text = self.run_events(self.invoice_paid(end), self.invoice_paid(end))
        self.assertEqual(len(self.webhook_lines(text)), 2)
        self.assertEqual(customers.get_subscription_record(user_id), before)

    def test_payment_failed_keeps_its_own_line_and_gets_no_second_one(self):
        user_id = self.signup()["user_id"]
        self.run_events(self.completed_event(user_id))
        text = self.run_events(self.invoice_failed())
        self.assertIn("billing: invoice.payment_failed", text)
        self.assertEqual(self.webhook_lines(text), [])

    def test_the_line_names_no_email_raw_id_token_or_secret(self):
        user_id = self.signup("private-person@example.com")["user_id"]
        end = self.now + timedelta(days=30)
        text = self.run_events(self.completed_event(user_id),
                               self.invoice_paid(end), self.invoice_failed())
        self.assertNotIn("private-person@example.com", text)
        self.assertNotIn("whsec", text)
        self.assertNotIn(acceptance.WEBHOOK_SECRET, text)
        self.assertNotIn(f"user={user_id} ", text)
        self.assertNotIn(f"user_id={user_id}", text)
        for line in text.splitlines():
            self.assertFalse(reqlog.contains_forbidden_content(line), line)

    def test_odd_events_still_answer_200_and_only_a_well_formed_one_is_logged(self):
        text = self.run_events(
            {"id": "evt_odd", "type": "invoice.finalized", "data": {"object": {}}},
            {"id": "evt_empty", "type": "invoice.paid"},
            {"id": "evt_bad_obj", "type": "invoice.paid", "data": {"object": "x"}},
            {"id": "evt_nontext_type", "type": {"a": 1}, "data": {"object": {}}})
        self.assertEqual(self.webhook_lines(text), [
            ("invoice.finalized", "evt_odd", "-", "-", "-")])

    def test_a_customer_with_no_record_logs_a_dash_user(self):
        text = self.run_events(self.invoice_paid(self.now + timedelta(days=30)))
        self.assertEqual(self.webhook_lines(text), [("invoice.paid", "evt_invoice_paid",
                                                     "-", "-", "-")])

    def test_a_failing_log_writer_never_turns_a_processed_event_into_an_error(self):
        user_id = self.signup()["user_id"]
        end = self.now + timedelta(days=30)
        self.webhook(self.completed_event(user_id))
        with mock.patch.object(billing, "_log_webhook_processed",
                               side_effect=RuntimeError("log sink down")):
            self.assertEqual(self.webhook(self.invoice_paid(end)), {"received": True})
        self.assertIsNotNone(customers.get_subscription_record(user_id)["paid_through"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
