"""Adversarial review of the billing event-order change (62a784962..b531a1c11).

Each class below is one finding. A class that pins a DEFECT carries
`@unittest.expectedFailure` on the test that tells the story: the suite stays
green today, and the day the fix lands that test starts "passing unexpectedly",
which is the signal to delete the decorator. Tests WITHOUT the decorator are
guard rails that pass today and must keep passing after the fix (what the fix
must not give away, and sequences that came out clean).

Same harness as tests/test_billing_event_order.py: every case drives the signed
webhook route and the real routes against a temp database; nothing reaches
Stripe.
"""

from __future__ import annotations

import itertools
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.appstate import billing, customers
from src.appstate import testers
from src.appstate import users as users_store
from tests import test_billing_acceptance_path as acceptance
from tests.test_billing_event_order import (CUSTOMER, DAY, SUBSCRIPTION, HTTPException,
                                            _OrderCase, _epoch, _iso)


def _user(user_id):
    return users_store.get_user(user_id)


# ---------------------------------------------------------------------------
# 1. PAYING CUSTOMER REFUSED: the hour Stripe waits before it charges a renewal
# ---------------------------------------------------------------------------
class ARenewingCustomerIsNotRefusedWhileStripeWaitsToChargeTheRenewal(_OrderCase):
    """Stripe creates the renewal invoice AT the period boundary and finalizes
    and charges it about an hour later (the hour it gives a webhook endpoint to
    adjust a draft invoice). Access ends at exactly paid-through, so every
    renewing customer is refused from the boundary until `invoice.paid`
    arrives: an hour (more when the first attempt is retried) out of every
    paid month, with 402 "your paid access ended" for someone whose card is
    about to be charged successfully.

    Observed: has_paid_access is False at paid_through + 30 minutes for a
    customer whose subscription is `active`, not scheduled to cancel and not
    failing. Expected: a bounded grace (longer than Stripe's hour, a few
    hours) for exactly that state, and none for a scheduled cancel or a
    failed charge (guards below). NOTE for the fix: the existing
    `assert_covers` helper in tests/test_billing_event_order.py asserts there
    is NO access at paid_through + 1 hour, so a grace window needs those
    pins moved with it."""

    HALF_HOUR = 1800

    @unittest.expectedFailure
    def test_an_active_renewing_customer_still_has_access_half_an_hour_after_the_boundary(self):
        user_id, token = self.buy_paid()
        # The renewal invoice exists (draft) but is not charged yet: the only
        # events so far are the ones Stripe sent before the boundary.
        self.assertTrue(self.has_access(user_id, self.p1 - 60))
        self.assertTrue(self.has_access(user_id, self.p1 + self.HALF_HOUR),
                        "a paying, renewing customer was refused during Stripe's "
                        "pre-charge wait at every renewal")

    def test_guard_a_scheduled_cancel_gets_no_grace_past_paid_through(self):
        user_id, _ = self.buy_paid()
        self.webhook(self.sub_event("updated", "active", 10, period_end=self.p1,
                                    cancel_at=self.p1))
        self.assertFalse(self.has_access(user_id, self.p1 + self.HALF_HOUR))

    def test_guard_a_failed_renewal_gets_no_grace_past_paid_through(self):
        user_id, _ = self.buy_paid()
        self.webhook(self.sub_event("updated", "past_due", 20, period_end=self.p2))
        self.assertFalse(self.has_access(user_id, self.p1 + self.HALF_HOUR))

    def test_guard_a_deleted_subscription_gets_no_grace_past_paid_through(self):
        user_id, _ = self.buy_paid()
        self.webhook(self.sub_event("deleted", "canceled", 20, period_end=self.p1))
        self.assertFalse(self.has_access(user_id, self.p1 + self.HALF_HOUR))


# ---------------------------------------------------------------------------
# 2. PAYING CUSTOMER LOSES A RENEWAL: POST /billing/cancel overwrites paid_through
# ---------------------------------------------------------------------------
class CancelCannotEraseARenewalThatLandsWhileItIsInFlight(_OrderCase):
    """api.billing._persist reads the recorded paid-through, then writes it
    back through customers.upsert_subscription: a plain read followed by a
    plain write, not one transaction. A renewal's `invoice.paid` that commits
    in between is overwritten with the stale value, and the customer who just
    pressed Cancel (and who paid for the next month a moment ago) loses that
    month. The webhook path is safe (mutate_subscription holds BEGIN
    IMMEDIATE); this route is the one writer that is not.

    The interleaving is forced by delivering the webhook inside the window
    (wrapping upsert_subscription); the window itself is narrow in production,
    but the loss is silent and permanent: nothing re-sends that invoice.

    Fix: have _persist go through customers.mutate_subscription and read
    paid_through (and the ordering stamps) inside the lock."""

    @unittest.expectedFailure
    def test_a_renewal_paid_during_cancel_keeps_its_paid_through(self):
        from api.billing import cancel_subscription
        user_id, _ = self.buy_paid()
        real = customers.upsert_subscription

        def renewal_lands_first(*args, **kwargs):
            self.webhook(self.invoice_event(30, period_end=self.p2))
            return real(*args, **kwargs)

        with mock.patch.object(customers, "upsert_subscription", renewal_lands_first):
            cancel_subscription(current_user=_user(user_id), _rate_limit=None)
        self.assertEqual(self.paid_through(user_id), _iso(self.p2),
                         "cancel wrote back the paid-through it read before the "
                         "renewal landed")


# ---------------------------------------------------------------------------
# 3. TESTERS: a mid-week tester who completes checkout is refused until the
#    next event
# ---------------------------------------------------------------------------
class ATesterInsideTheirWeekIsNotLockedOutByStartingToPay(_OrderCase):
    """A tester (no card, no subscription row) is never gated: no row, no
    check (api/auth.require_paid_access). `checkout.session.completed` now
    creates the row at once but grants nothing, so from that event until
    `customer.subscription.created` / `invoice.paid` is processed (Stripe does
    not order them; retries can be minutes) the tester gets 402
    "subscription_expired" -- inside a week they were given free and had a
    valid token for. Before this change the row read `active` and nothing
    changed for them.

    Fix (smallest): in require_paid_access, a row that has never held any
    paid-through evidence (paid_through is NULL) does not gate a user whose
    tester window is still open."""

    def _tester(self, email):
        grant = testers.grant_tester(email=email)
        return users_store.get_user_by_email(email).id, grant.token

    def test_guard_before_any_checkout_the_tester_is_open(self):
        user_id, token = self._tester("guard@example.com")
        self.assertEqual(self.open_paid_page(token).id, user_id)

    @unittest.expectedFailure
    def test_after_only_the_completed_session_the_tester_is_still_open(self):
        user_id, token = self._tester("midweek@example.com")
        self.webhook(self.session_event(user_id, payment_status="no_payment_required"))
        self.assertEqual(self.open_paid_page(token).id, user_id)

    def test_once_the_trial_is_reported_the_tester_is_open(self):
        user_id, token = self._tester("trialed@example.com")
        trial_end = _epoch(self.now + timedelta(days=7))
        self.webhook(self.session_event(user_id, payment_status="no_payment_required"))
        self.webhook(self.sub_event("created", "trialing", 1, period_end=trial_end,
                                    trial_end=trial_end))
        self.assertEqual(self.open_paid_page(token).id, user_id)


# ---------------------------------------------------------------------------
# 4. ADMIN REVENUE VIEW counts people who are not entitled as paying
# ---------------------------------------------------------------------------
class TheRevenueViewCountsEntitlementNotJustTheStatusWord(_OrderCase):
    """api/admin.get_revenue counts `status == "active"` as paying and charges
    them to MRR whatever their paid-through is. Two states now make that
    wrong, and the second hides exactly the failure the rehearsal doc tells the
    owner to look for (customers losing access a period after they bought):

      * checkout.session.completed alone leaves a row `active` with NO
        paid-through (the session grants nothing): counted as paying, $19.99
        of MRR, while has_paid_access is False;
      * an `active` row whose paid-through has passed (renewal never paid, or
        invoice events not subscribed) still counts as paying and as MRR.

    Fix: count a row as paying / trialing only while paid_through is in the
    future (an `active` row without it is `pending`/`lapsed`, not revenue)."""

    def _revenue(self):
        from api.admin import get_revenue
        return get_revenue(_admin=None)

    @unittest.expectedFailure
    def test_a_completed_session_with_no_payment_yet_is_not_mrr(self):
        started = self.signup("pending@example.com")
        user_id = started["user_id"]
        self.webhook(self.session_event(user_id))
        self.assertFalse(customers.has_paid_access(user_id))
        revenue = self._revenue()
        self.assertEqual((revenue["paying"], revenue["mrr_cents"]), (0, 0))

    @unittest.expectedFailure
    def test_an_active_row_past_its_paid_through_is_not_mrr(self):
        user_id, _ = self.buy_paid(end=_epoch(self.now - timedelta(days=5)))
        self.assertFalse(customers.has_paid_access(user_id))
        self.assertEqual(self.record(user_id)["status"], "active")
        revenue = self._revenue()
        self.assertEqual((revenue["paying"], revenue["mrr_cents"]), (0, 0))

    def test_guard_a_paid_active_customer_is_counted(self):
        self.buy_paid()
        revenue = self._revenue()
        self.assertEqual((revenue["paying"], revenue["mrr_cents"]), (1, 1999))


# ---------------------------------------------------------------------------
# 5. MIGRATION: rows the old rule kept open and the new one shuts
# ---------------------------------------------------------------------------
def _legacy_db(path: Path, rows):
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("CREATE TABLE billing_customers (user_id INTEGER PRIMARY KEY, "
                     "stripe_customer_id TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL)")
        conn.execute("CREATE TABLE billing_subscriptions (user_id INTEGER PRIMARY KEY, "
                     "stripe_subscription_id TEXT NOT NULL, status TEXT NOT NULL, "
                     "updated_at TEXT NOT NULL, cancel_at TEXT, current_period_end TEXT)")
        for row in rows:
            conn.execute("INSERT INTO billing_subscriptions VALUES (?,?,?,?,?,?)", row)


class DeployDoesNotStrandOrImmortaliseExistingRows(unittest.TestCase):
    """The old rule: status active/trialing with no cancel scheduled was
    entitled FOREVER, whatever `current_period_end` said (even NULL); only a
    canceled row ran to its end. The migration copies current_period_end to
    paid_through, so:

      * an `active` row with NO period end (a checkout recorded, the
        subscription event not yet processed) had access yesterday and has
        none today, until the next event;
      * an `active` row whose recorded end is already past (a missed
        `updated`) likewise.

    Nobody is made permanent (clean), and a row with a future end keeps
    exactly that end (clean, pinned below). Billing is off in production so
    the population may be empty; if it is not, the owner should decide whether
    these rows get a bounded backfill. The test pins the proposal: a row that
    was open yesterday is open on deploy for no more than one period."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "legacy.db"
        self.now = datetime.now(timezone.utc)

    def _iso(self, days):
        return (self.now + timedelta(days=days)).isoformat()

    def test_guard_a_row_with_a_future_end_keeps_exactly_that_end(self):
        _legacy_db(self.db, [(1, "s1", "active", "x", None, self._iso(10)),
                             (2, "s2", "trialing", "x", None, self._iso(3)),
                             (3, "s3", "canceled", "x", None, self._iso(5))])
        for user_id, days in ((1, 10), (2, 3), (3, 5)):
            self.assertEqual(customers.get_subscription_record(user_id, db=self.db)[
                "paid_through"], self._iso(days))
            self.assertTrue(customers.has_paid_access(user_id, db=self.db))
            self.assertFalse(customers.has_paid_access(
                user_id, self.now + timedelta(days=days + 1), db=self.db))

    def test_guard_nothing_is_made_permanent(self):
        _legacy_db(self.db, [(1, "s1", "active", "x", None, None),
                             (2, "s2", "active", "x", None, self._iso(-40))])
        for user_id in (1, 2):
            self.assertFalse(customers.has_paid_access(
                user_id, self.now + timedelta(days=400), db=self.db))

    @unittest.expectedFailure
    def test_an_active_row_with_no_end_is_open_on_deploy_for_at_most_one_period(self):
        _legacy_db(self.db, [(1, "s1", "active", "x", None, None)])
        self.assertTrue(customers.has_paid_access(1, db=self.db),
                        "an active customer the old rule served is locked out by "
                        "the migration")
        self.assertFalse(customers.has_paid_access(
            1, self.now + timedelta(days=40), db=self.db))

    def test_guard_twelve_connections_opening_a_legacy_file_at_once_migrate_it_once(self):
        _legacy_db(self.db, [(i, "s", "active", "x", None, self._iso(10))
                             for i in range(1, 30)])
        errors = []

        def open_it():
            try:
                customers.list_subscription_rows(db=self.db)
            except Exception as exc:    # pragma: no cover - failure path
                errors.append(repr(exc))

        threads = [threading.Thread(target=open_it) for _ in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        rows = customers.list_subscription_rows(db=self.db)
        self.assertEqual(len(rows), 29)
        self.assertTrue(all(row["paid_through"] == self._iso(10) for row in rows))


# ---------------------------------------------------------------------------
# 6. ROBUSTNESS: signed but odd payloads must still be answered 200
# ---------------------------------------------------------------------------
class OddButSignedPayloadsAreAnsweredNotRaised(_OrderCase):
    """The webhook promises "any other shape is silently ignored: a 500 looks
    like an outage and Stripe retries it for three days". Several shapes raise
    out of apply_stripe_webhook_event instead (AttributeError on a non-object
    `data.object`, sqlite ProgrammingError binding a non-string id, TypeError
    on an unhashable status, OverflowError on an out-of-range `created`).
    Stripe does not send these today; a signed body is only proof of origin.

    Fix: coerce at the boundary (isinstance(dict) for event/data/object,
    str-only for ids and status, int range for times) and return."""

    ODD = {
        "event is a list": [],
        "object is a string": {"type": "customer.subscription.created",
                               "data": {"object": "x"}},
        "subscription id is an object": {
            "type": "customer.subscription.created", "created": 1,
            "data": {"object": {"id": {"a": 1}, "customer": CUSTOMER, "status": "active"}}},
        "customer is an object": {
            "type": "customer.subscription.created", "created": 1,
            "data": {"object": {"id": "sub_x", "customer": {"id": CUSTOMER},
                                "status": "active"}}},
        "status is a list": {
            "type": "customer.subscription.created", "created": 1,
            "data": {"object": {"id": "sub_x", "customer": CUSTOMER, "status": ["a"]}}},
        "created is out of range": {
            "type": "customer.subscription.created", "created": 10 ** 30,
            "data": {"object": {"id": "sub_x", "customer": CUSTOMER, "status": "active"}}},
    }

    @unittest.expectedFailure
    def test_every_odd_shape_gets_a_200(self):
        customers.upsert_customer(1, CUSTOMER)
        failures = []
        for name, event in self.ODD.items():
            try:
                self.assertEqual(self.webhook(event), {"received": True})
            except Exception as exc:
                failures.append(f"{name}: {type(exc).__name__}")
        self.assertEqual(failures, [])


# ---------------------------------------------------------------------------
# 7. FREE ACCESS: an absurd period end in a paid invoice line
# ---------------------------------------------------------------------------
class APaidInvoiceCannotGrantDecades(_OrderCase):
    """_invoice_paid_through trusts the largest line period end. A paid invoice
    whose line ends in 2100 (a hand-made invoice item with a custom period, a
    typo in the dashboard) records paid-through 2100: permanent access, and
    nothing ever lowers it (paid-through only grows). On Linux an end up to
    year 9999 is accepted; Windows rejects it, so the test uses 2100.

    Fix: clamp the evidence to event time + a ceiling a bit above the longest
    plan (400 days) and treat anything beyond as 'no evidence'."""

    @unittest.expectedFailure
    def test_a_line_ending_in_2100_does_not_make_access_permanent(self):
        user_id = self.seed_paid()
        far = _epoch(datetime(2100, 1, 1, tzinfo=timezone.utc))
        self.webhook(self.invoice_event(30, period_end=far))
        self.assertFalse(self.has_access(user_id, _epoch(self.now + timedelta(days=800))))


# ---------------------------------------------------------------------------
# Sequences that came out clean (pinned so the fixes above cannot break them)
# ---------------------------------------------------------------------------
class CleanSequences(_OrderCase):
    def _fresh(self):
        customers.upsert_customer(1, CUSTOMER)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("DELETE FROM billing_subscriptions")

    def _check_all_orders(self, events, *, expect_end, expect_status="active"):
        for order in itertools.permutations(range(len(events))):
            self._fresh()
            for index in order:
                self.webhook(events[index])
            record = self.record(1)
            with self.subTest(order=order):
                self.assertEqual(record["paid_through"], _iso(expect_end))
                self.assertEqual(record["status"], expect_status)
                self.assertTrue(self.has_access(1, expect_end - 3600))

    def test_first_purchase_in_every_order_of_its_four_events(self):
        end = self.p1
        self._check_all_orders(
            [self.session_event(1),
             self.sub_event("created", "active", 1, period_end=end),
             self.invoice_event(2, period_end=end, reason="subscription_create"),
             self.sub_event("updated", "active", 3, period_end=end)],
            expect_end=end)

    def test_first_purchase_with_the_new_api_shape_in_every_order(self):
        """Stripe API 2025-03-31+: no top-level subscription / period end on
        the invoice or subscription; they live in parent / items."""
        end = self.p1
        sub = {"id": "evt_new_sub", "type": "customer.subscription.created",
               "created": self.at(1),
               "data": {"object": {"id": SUBSCRIPTION, "customer": CUSTOMER,
                                   "status": "active", "created": self.at(0),
                                   "items": {"data": [{"current_period_end": end}]}}}}
        invoice = {"id": "evt_new_inv", "type": "invoice.paid", "created": self.at(2),
                   "data": {"object": {
                       "id": "in_new", "customer": CUSTOMER, "status": "paid",
                       "parent": {"subscription_details": {"subscription": SUBSCRIPTION}},
                       "lines": {"data": [{
                           "period": {"start": end - 30 * DAY, "end": end},
                           "parent": {"subscription_item_details": {
                               "subscription": SUBSCRIPTION}}}]}}}}
        self._check_all_orders([self.session_event(1), sub, invoice], expect_end=end)

    def test_trial_then_conversion_in_every_order_of_its_four_events(self):
        trial_end = _epoch(self.now + timedelta(days=7))
        end = self.p2
        free = self.invoice_event(1, period_end=trial_end, reason="subscription_create")
        free["data"]["object"]["amount_paid"] = 0
        free["data"]["object"]["lines"]["data"][0]["period"]["start"] = self.at(0)
        self._check_all_orders(
            [self.sub_event("created", "trialing", 1, period_end=trial_end,
                            trial_end=trial_end),
             free,
             self.sub_event("updated", "active", 30, period_end=end),
             self.invoice_event(31, period_end=end, reason="subscription_cycle")],
            expect_end=end)

    def test_a_zero_dollar_trial_invoice_grants_no_more_than_the_trial(self):
        """The invoice Stripe sends at trial start is `paid`, $0, and its one
        line runs from now to trial_end: it must leave paid-through at the
        trial end in either order against the subscription event."""
        trial_end = _epoch(self.now + timedelta(days=7))
        free = self.invoice_event(1, period_end=trial_end, reason="subscription_create")
        free["data"]["object"]["amount_paid"] = 0
        created = self.sub_event("created", "trialing", 1, period_end=trial_end,
                                 trial_end=trial_end)
        for order in ((created, free), (free, created)):
            self._fresh()
            for event in order:
                self.webhook(event)
            self.assertEqual(self.paid_through(1), _iso(trial_end))

    def test_resubscribing_with_a_new_subscription_id_after_cancel(self):
        user_id, _ = self.buy_paid(end=_epoch(self.now - timedelta(days=2)))
        self.webhook(self.sub_event("deleted", "canceled", 5, period_end=self.p1))
        newer = "sub_resubscribed"
        self.webhook(self.session_event(user_id, sub=newer, minute=100))
        self.webhook(self.invoice_event(101, period_end=self.p2, sub=newer))
        self.webhook(self.sub_event("created", "active", 102, period_end=self.p2, sub=newer,
                                    sub_created_minute=100))
        self.assertEqual(self.record(user_id)["stripe_subscription_id"], newer)
        self.assert_covers(user_id, self.p2)
        # the dead subscription's late deletion changes nothing
        before = self.stable(user_id)
        self.webhook(self.sub_event("deleted", "canceled", 5, period_end=self.p1))
        self.assertEqual(self.stable(user_id), before)

    def test_a_late_invoice_for_a_different_customer_grants_this_one_nothing(self):
        user_id = self.seed_paid()
        before = self.stable(user_id)
        stranger = self.invoice_event(40, period_end=self.p3)
        stranger["data"]["object"]["customer"] = "cus_somebody_else"
        self.webhook(stranger)
        self.assertEqual(self.stable(user_id), before)

    def test_cancel_and_reactivate_cannot_extend_paid_through(self):
        from api.billing import cancel_subscription, reactivate_subscription
        user_id, _ = self.buy_paid()
        cancel_subscription(current_user=_user(user_id), _rate_limit=None)
        reactivate_subscription(current_user=_user(user_id), _rate_limit=None)
        self.assertEqual(self.paid_through(user_id), _iso(self.p1))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
