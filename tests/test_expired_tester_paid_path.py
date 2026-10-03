"""An early tester whose week ran out can become a paying subscriber, on the
SAME account.

Owner's words (2026-10-03): "expired tester -> sees clear upgrade state -> can
start checkout -> successful payment -> paid entitlement replaces expired trial
-> previous history/account preserved. No duplicate account. No permanent
'invited' dead end. Test entirely in Stripe test mode first. Do NOT enable
production billing yet."

The defect: testers.grant_tester leaves a person `invited`, and POST /signup
answered `invited` for any `invited` email and never started a checkout. A
tester whose seven day token had ended could not pay, and the sign-in page
could not even tell them their access had ended.

Everything here runs through the real route functions and the real store
against the in-process Stripe stand-in the funnel smoke test and the billing
acceptance path use (billing._fake_stripe_transport: synthetic key only, never a
real request, no network). Time passes by stamping grants in the past and by
signed webhooks that carry past period ends, never by sleeping. The JS half runs
the real web/js modules under node against a small fake DOM (the pattern of
tests/test_early_access_copy.py) and is skipped where node is not installed.

Most tests import `src.appstate.tester_upgrade` only inside the test that needs
it, so that run against the pre-change tree each one fails on its own rather
than the whole module failing to import.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

try:
    from fastapi import HTTPException
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.appstate import billing
from src.appstate import customers
from src.appstate import events
from src.appstate import savedbets
from src.appstate import testers
from src.appstate import users as users_store
from tests import test_billing_acceptance_path as acceptance

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "js"

OFF_ENV = {"APP_ADMIN_TOKEN": acceptance.ADMIN_TOKEN}


class _Base(acceptance._Case):
    """The acceptance path's fixture (temp db, billing env, signed webhooks,
    the success-page token read) plus a tester and a few direct reads of the
    database file. APP_DB_PATH is pointed at the same file so saved bets and
    analytics events land in it too, not in the repo's default database."""

    def setUp(self):
        super().setUp()
        os.environ["APP_DB_PATH"] = str(self.db)

    # -- fixtures -----------------------------------------------------------

    def grant_for(self, email="tester@example.com", age_days=8):
        """A tester granted `age_days` ago: 8 means the week ended yesterday."""
        stamp = datetime.now(timezone.utc) - timedelta(days=age_days)
        return testers.grant_tester(email=email, now=stamp)

    def rows(self, sql, *args):
        with closing(sqlite3.connect(self.db)) as conn:
            return conn.execute(sql, args).fetchall()

    def user_count(self):
        return self.rows("SELECT COUNT(*) FROM users")[0][0]

    def history_row(self, user_id):
        return self.rows("SELECT user_id, granted_at, expires_at FROM testers "
                         "WHERE user_id = ?", user_id)

    def status_of(self, user_id):
        return users_store.get_user(user_id).status

    def pay(self, user_id):
        """The two webhooks Stripe sends for a completed trial checkout."""
        self.webhook(self.completed_event(user_id))
        self.webhook(self.subscription_event("created", "trialing"))
        return self.collect_token()["token"]

    def sign_in_with(self, token):
        from api.auth import get_current_user
        return get_current_user(authorization=f"Bearer {token}", request=None)

    def refused_detail(self, token):
        with self.assertRaises(HTTPException) as ctx:
            self.sign_in_with(token)
        self.assertEqual(ctx.exception.status_code, 401)
        return ctx.exception.detail


class _BillingOn(_Base):
    ENV = acceptance.SELLING_ENV


class _BillingOff(_Base):
    ENV = OFF_ENV


# ===========================================================================
# 1. Signup, billing ON: a tester gets the normal checkout, on the same user.
# ===========================================================================

class SignupWithBillingOn(_BillingOn):
    def test_an_expired_tester_is_sent_to_checkout_on_their_own_account(self):
        grant = self.grant_for(age_days=8)
        result = self.signup("tester@example.com")
        self.assertEqual(result["user_id"], grant.user_id)
        self.assertEqual(result["checkout"]["status"], "redirect", result)
        self.assertEqual(result["checkout"]["checkout_url"], billing.FAKE_TRANSPORT_CHECKOUT_URL)
        self.assertEqual(self.user_count(), 1, "a second account was created")
        # Status moves the way a new buyer's does.
        self.assertEqual(self.status_of(grant.user_id), "pending_payment")

    def test_the_email_may_be_written_in_any_case_and_still_finds_the_account(self):
        grant = self.grant_for(age_days=9)
        result = self.signup("  Tester@Example.COM ")
        self.assertEqual(result["user_id"], grant.user_id)
        self.assertEqual(result["checkout"]["status"], "redirect", result)
        self.assertEqual(self.user_count(), 1)

    def test_a_tester_still_inside_the_week_can_pay_early(self):
        grant = self.grant_for(age_days=2)
        result = self.signup("tester@example.com")
        self.assertEqual(result["user_id"], grant.user_id)
        self.assertEqual(result["checkout"]["status"], "redirect", result)
        self.assertEqual(self.user_count(), 1)
        # Their tester token is untouched by starting a checkout.
        self.assertEqual(self.sign_in_with(grant.token).id, grant.user_id)

    def test_a_second_attempt_before_paying_is_the_same_user_and_a_checkout_again(self):
        grant = self.grant_for()
        first = self.signup("tester@example.com")
        second = self.signup("tester@example.com")
        self.assertEqual(first["user_id"], second["user_id"], grant.user_id)
        self.assertEqual(second["checkout"]["status"], "redirect")
        self.assertEqual(self.user_count(), 1)

    def test_it_records_checkout_started_and_no_second_account_created_event(self):
        self.grant_for()
        self.signup("tester@example.com")
        kinds = [e.kind for e in events.list_events()]
        self.assertIn(events.CHECKOUT_STARTED, kinds)
        self.assertNotIn(events.ACCOUNT_CREATED, kinds)

    def test_a_suspended_tester_is_left_alone(self):
        grant = self.grant_for()
        users_store.set_user_status(grant.user_id, "suspended")
        result = self.signup("tester@example.com")
        self.assertEqual(result, {"user_id": grant.user_id, "status": "suspended"})

    def test_a_comped_invite_that_is_not_a_tester_keeps_todays_answer(self):
        invited = users_store.create_user("comped@example.com", status="invited", plan="none")
        result = self.signup("comped@example.com")
        self.assertEqual(result, {"user_id": invited.id, "status": "invited"})
        self.assertEqual(self.status_of(invited.id), "invited")

    def test_an_active_customer_who_was_never_a_tester_keeps_todays_answer(self):
        paying = users_store.create_user("customer@example.com", status="active", plan="beta")
        result = self.signup("customer@example.com")
        self.assertEqual(result, {"user_id": paying.id, "status": "active"})

    def test_billing_on_but_unable_to_take_a_payment_is_the_error_a_new_buyer_gets(self):
        grant = self.grant_for()
        os.environ.pop(billing.ENV_STRIPE_WEBHOOK_SECRET)
        result = self.signup("tester@example.com")
        self.assertEqual(result["status"], "error", result)
        self.assertIn("nothing has been charged", result["message"])
        self.assertNotIn("checkout", result)
        # Not waitlisted, not moved: nothing happened to their account.
        self.assertEqual(self.status_of(grant.user_id), "invited")


# ===========================================================================
# 2. Signup, billing OFF (production today): a truthful state, no checkout.
# ===========================================================================

class SignupWithBillingOff(_BillingOff):
    def test_an_expired_tester_is_told_their_access_ended(self):
        grant = self.grant_for(age_days=8)
        result = self.signup("tester@example.com")
        self.assertEqual(result, {"user_id": grant.user_id, "status": "tester_expired",
                                  "expires_at": grant.expires_at})
        self.assertNotIn("checkout", result)

    def test_an_active_tester_is_told_when_their_access_ends(self):
        grant = self.grant_for(age_days=2)
        result = self.signup("tester@example.com")
        self.assertEqual(result, {"user_id": grant.user_id, "status": "tester_active",
                                  "expires_at": grant.expires_at})

    def test_nothing_is_corrupted_by_asking_again_and_again(self):
        grant = self.grant_for(age_days=8)
        for _ in range(3):
            self.assertEqual(self.signup("tester@example.com")["status"], "tester_expired")
        self.assertEqual(self.user_count(), 1)
        self.assertEqual(self.status_of(grant.user_id), "invited")
        self.assertEqual(self.history_row(grant.user_id),
                         [(grant.user_id, grant.granted_at, grant.expires_at)])
        self.assertIsNone(customers.get_subscription_record(grant.user_id))
        self.assertEqual(self.rows("SELECT COUNT(*) FROM tokens")[0][0], 1)

    def test_it_opens_no_checkout_and_records_no_checkout_event(self):
        self.grant_for()
        calls = []
        real = billing._fake_stripe_transport

        def spy(method, url, headers, data):
            calls.append(url)
            return real(method, url, headers, data)

        with mock.patch.object(billing, "_fake_stripe_transport", spy):
            result = self.signup("tester@example.com")
        self.assertEqual(result["status"], "tester_expired")
        self.assertEqual(calls, [])
        self.assertNotIn(events.CHECKOUT_STARTED, [e.kind for e in events.list_events()])

    def test_a_tester_parked_at_pending_payment_is_not_waitlisted(self):
        # Billing was on for a moment, a checkout was started and abandoned,
        # then billing went off. Pre-change this email would have been moved to
        # `waitlisted`: a person already let in, filed under "not yet picked".
        grant = self.grant_for()
        users_store.set_user_status(grant.user_id, "pending_payment")
        result = self.signup("tester@example.com")
        self.assertEqual(result["status"], "tester_expired", result)
        self.assertEqual(self.status_of(grant.user_id), "pending_payment")

    def test_a_comped_invite_that_is_not_a_tester_keeps_todays_answer(self):
        invited = users_store.create_user("comped@example.com", status="invited", plan="none")
        self.assertEqual(self.signup("comped@example.com"),
                         {"user_id": invited.id, "status": "invited"})

    def test_a_stranger_is_still_waitlisted_and_a_waitlisted_email_stays_waitlisted(self):
        first = self.signup("stranger@example.com")
        self.assertEqual(first["status"], "waitlisted")
        self.assertEqual(self.signup("stranger@example.com")["status"], "waitlisted")

    def test_an_extended_tester_is_told_the_end_of_the_extended_window(self):
        stamp = datetime.now(timezone.utc)
        first = testers.grant_tester(email="tester@example.com", now=stamp - timedelta(days=20))
        extended = testers.extend_tester(first.user_id, "three specific problems found",
                                         now=stamp - timedelta(days=10))
        result = self.signup("tester@example.com")
        self.assertEqual(result["status"], "tester_expired")
        self.assertEqual(result["expires_at"], extended.expires_at)
        self.assertNotEqual(result["expires_at"], first.expires_at)


# ===========================================================================
# 3. Paying: one user, active, history kept, access from the subscription.
# ===========================================================================

class PayingAsAFormerTester(_BillingOn):
    def setUp(self):
        super().setUp()
        self.grant = self.grant_for("former@example.com", age_days=8)
        self.uid = self.grant.user_id
        self.bet = savedbets.save_bet(self.uid, "MLB-2026-09-30-NYY-BOS", "NYY", price=-110.0,
                                      snapshot_digest="digest-1")
        self.tester_before = self.history_row(self.uid)
        self.started = self.signup("former@example.com")
        # The whole flow begins at the signup form: if an expired tester cannot
        # start a checkout there, nothing below can happen.
        self.assertEqual(self.started["checkout"]["status"], "redirect", self.started)
        self.token = self.pay(self.uid)

    def test_one_user_active_with_the_subscription(self):
        self.assertEqual(self.started["user_id"], self.uid)
        self.assertEqual(self.user_count(), 1)
        user = users_store.get_user(self.uid)
        self.assertEqual(user.email, "former@example.com")
        self.assertEqual(user.status, "active")
        record = customers.get_subscription_record(self.uid)
        self.assertEqual(record["status"], "trialing")
        self.assertEqual(record["stripe_subscription_id"], acceptance.SUBSCRIPTION)
        self.assertTrue(customers.has_paid_access(self.uid))

    def test_the_tester_row_is_history_and_is_untouched(self):
        self.assertEqual(self.history_row(self.uid), self.tester_before)
        self.assertEqual(testers.count_granted(), 1, "paying must not free or burn a slot")
        listed = testers.list_testers()["testers"]
        self.assertEqual([t["user_id"] for t in listed], [self.uid])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM tester_extensions")[0][0], 0)

    def test_saved_bets_and_other_per_user_data_are_still_attached(self):
        bets = savedbets.list_bets(self.uid, include_deleted=True)
        self.assertEqual([(b.id, b.game, b.side, b.price, b.snapshot_digest) for b in bets],
                         [(self.bet.id, "MLB-2026-09-30-NYY-BOS", "NYY", -110.0, "digest-1")])
        # The old tester token is still a row (history), the new one was added.
        self.assertEqual(self.rows("SELECT COUNT(*) FROM tokens WHERE user_id = ?", self.uid)[0][0], 2)

    def test_the_buyer_holds_a_working_token_through_the_success_page_path(self):
        # `self.token` came from GET /signup/complete, the path a new buyer uses.
        self.assertEqual(self.sign_in_with(self.token).id, self.uid)
        self.assertEqual(self.open_paid_page(self.token).id, self.uid)
        # ...and it is a subscriber token, not another week.
        row = self.rows("SELECT created_at, expires_at FROM tokens WHERE token_hash = ?",
                        users_store._hash_token(self.token))[0]
        lifetime = datetime.fromisoformat(row[1]) - datetime.fromisoformat(row[0])
        self.assertEqual(lifetime, billing.SUBSCRIBER_TOKEN_TTL)

    def test_the_expired_week_token_still_opens_nothing_and_says_plain_unauthorized(self):
        # Paid, so "your early access ended, subscribe" would be the wrong thing
        # to tell them: the generic refusal is right.
        detail = self.refused_detail(self.grant.token)
        self.assertEqual(detail["error"], "unauthorized")

    def test_a_paying_former_tester_who_asks_again_is_not_sent_to_a_second_checkout(self):
        again = self.signup("former@example.com")
        self.assertEqual(again, {"user_id": self.uid, "status": "active"})
        self.assertEqual(len(customers.list_subscription_rows()), 1)

    def test_a_duplicate_webhook_delivery_changes_nothing(self):
        def snapshot():
            return {
                "users": self.rows("SELECT * FROM users"),
                "tokens": self.rows("SELECT token_hash, user_id, expires_at FROM tokens ORDER BY 1"),
                "activation": self.rows("SELECT stripe_session_id, user_id FROM signup_activation_tokens"),
                "subs": self.rows("SELECT user_id, stripe_subscription_id, status FROM billing_subscriptions"),
                "testers": self.history_row(self.uid),
                "bets": [b.id for b in savedbets.list_bets(self.uid, include_deleted=True)],
            }
        before = snapshot()
        for _ in range(3):
            self.webhook(self.completed_event(self.uid))
            self.webhook(self.subscription_event("created", "trialing"))
        self.assertEqual(snapshot(), before)
        self.assertEqual(self.collect_token()["token"], self.token)

    def test_the_paid_checkout_event_is_recorded_once(self):
        kinds = [e.kind for e in events.list_events()]
        self.assertEqual(kinds.count(events.CHECKOUT_COMPLETED), 1)
        self.assertEqual(kinds.count(events.CHECKOUT_STARTED), 1)
        self.assertNotIn(events.ACCOUNT_CREATED, kinds)


class PayingFromInsideTheWeekThroughTheBillingPage(_BillingOn):
    """A tester with a valid token can also pay from the authed billing route,
    which (unlike the signup form) does not park them at pending_payment first.
    The webhook must still make them `active`: they paid."""

    def test_an_invited_tester_who_pays_becomes_active(self):
        from api.billing import CheckoutRequest, create_checkout
        grant = self.grant_for(age_days=2)
        user = users_store.get_user(grant.user_id)
        started = create_checkout(CheckoutRequest(plan_id="beta"), current_user=user,
                                  _rate_limit=None)
        self.assertEqual(started["status"], "redirect", started)
        self.assertEqual(self.status_of(grant.user_id), "invited")
        token = self.pay(grant.user_id)
        self.assertEqual(self.status_of(grant.user_id), "active")
        self.assertEqual(self.user_count(), 1)
        self.assertEqual(self.open_paid_page(token).id, grant.user_id)

    def test_a_comped_invite_who_is_not_a_tester_keeps_their_invited_status_when_paying(self):
        from api.billing import CheckoutRequest, create_checkout
        comped = users_store.create_user("comped@example.com", status="invited", plan="none")
        create_checkout(CheckoutRequest(plan_id="beta"), current_user=comped, _rate_limit=None)
        self.pay(comped.id)
        self.assertEqual(self.status_of(comped.id), "invited",
                         "only a tester's status is moved by this change")


# ===========================================================================
# 4. Entitlement: the subscription decides, never the expired tester window.
# ===========================================================================

class AccessIsGovernedByTheSubscription(_BillingOn):
    def test_a_paid_former_tester_passes_and_a_cancelled_and_expired_one_does_not(self):
        grant = self.grant_for("former@example.com", age_days=30)   # window ended long ago
        self.signup("former@example.com")
        token = self.pay(grant.user_id)
        self.assertEqual(self.open_paid_page(token).id, grant.user_id)

        ended = acceptance._epoch(datetime.now(timezone.utc) - timedelta(hours=1))
        self.webhook(self.subscription_event("updated", "active", period_end=ended, cancel_at=ended))
        with self.assertRaises(HTTPException) as lapsed:
            self.open_paid_page(token)
        self.assertEqual(lapsed.exception.status_code, 402)
        self.assertEqual(lapsed.exception.detail["error"], "subscription_expired")

    def test_a_tester_who_pays_early_is_governed_by_the_subscription_not_their_week(self):
        grant = self.grant_for("early@example.com", age_days=1)     # six days of week left
        self.signup("early@example.com")
        self.pay(grant.user_id)
        ended = acceptance._epoch(datetime.now(timezone.utc) - timedelta(hours=1))
        self.webhook(self.subscription_event("deleted", "canceled", period_end=ended))
        user = self.sign_in_with(grant.token)           # the week token still authenticates
        with self.assertRaises(HTTPException) as lapsed:
            self.open_paid_page(grant.token)
        self.assertEqual(user.id, grant.user_id)
        self.assertEqual(lapsed.exception.status_code, 402)

    def test_cancel_keeps_access_to_period_end_then_blocks_then_a_new_checkout_works(self):
        from api.billing import CheckoutRequest, billing_status, cancel_subscription, create_checkout
        grant = self.grant_for("former@example.com", age_days=8)
        uid = grant.user_id
        self.signup("former@example.com")
        token = self.pay(uid)

        # Cancel: renewal stops, the period already paid for is still theirs.
        cancelled = cancel_subscription(current_user=users_store.get_user(uid), _rate_limit=None)
        self.assertTrue(cancelled["cancel_at_period_end"], cancelled)
        self.assertIsNotNone(billing_status(current_user=users_store.get_user(uid))["cancel_at"])
        self.assertEqual(self.open_paid_page(token).id, uid)

        # The period runs out.
        ended = acceptance._epoch(datetime.now(timezone.utc) - timedelta(hours=1))
        self.webhook(self.subscription_event("updated", "active", period_end=ended, cancel_at=ended))
        self.webhook(self.subscription_event("deleted", "canceled", period_end=ended))
        with self.assertRaises(HTTPException) as blocked:
            self.open_paid_page(token)
        self.assertEqual(blocked.exception.status_code, 402)
        self.assertFalse(customers.has_paid_access(uid))

        # Door one: the signup form, by email, with no token at all.
        again = self.signup("former@example.com")
        self.assertEqual(again["user_id"], uid)
        self.assertEqual(again["checkout"]["status"], "redirect", again)
        self.assertEqual(self.user_count(), 1)
        self.assertEqual(self.status_of(uid), "active", "a lapsed customer's status is not churned")
        # Door two: the billing route, with the token they still hold.
        via_token = create_checkout(CheckoutRequest(plan_id="beta"),
                                    current_user=users_store.get_user(uid), _rate_limit=None)
        self.assertEqual(via_token["status"], "redirect")

        # They pay again (a NEW Stripe session and subscription).
        self.webhook({"id": "evt_completed_2", "type": "checkout.session.completed",
                      "data": {"object": {"id": "cs_second_purchase", "client_reference_id": str(uid),
                                          "customer": acceptance.CUSTOMER,
                                          "subscription": "sub_second_purchase",
                                          "payment_status": "paid"}}})
        self.webhook({"id": "evt_created_2", "type": "customer.subscription.created",
                      "data": {"object": {"id": "sub_second_purchase", "customer": acceptance.CUSTOMER,
                                          "status": "active",
                                          "current_period_end": acceptance.FAR_FUTURE}}})
        fresh = self.collect_token("cs_second_purchase")
        self.assertEqual(fresh["user_id"], uid)
        self.assertEqual(self.open_paid_page(fresh["token"]).id, uid)
        record = customers.get_subscription_record(uid)
        self.assertEqual(record["stripe_subscription_id"], "sub_second_purchase")
        self.assertEqual(self.user_count(), 1)
        self.assertEqual(testers.count_granted(), 1)


# ===========================================================================
# 5. Sign-in: an expired tester token is distinguishable from a wrong token.
# ===========================================================================

class ExpiredTokenIsDistinguishable(_BillingOff):
    def test_an_expired_tester_token_is_a_401_that_says_the_access_ended(self):
        grant = self.grant_for("tester@example.com", age_days=8)
        detail = self.refused_detail(grant.token)
        self.assertEqual(detail["error"], "tester_access_expired")
        self.assertEqual(detail["expires_at"], grant.expires_at)
        # Nothing about the person leaks into the body.
        body = json.dumps(detail)
        for secret in ("tester@example.com", grant.token, str(grant.user_id) + '"'):
            self.assertNotIn(secret, body)
        self.assertEqual(sorted(detail), ["error", "expires_at", "message"])

    def test_a_wrong_token_keeps_the_generic_401_with_the_same_status(self):
        self.grant_for("tester@example.com", age_days=8)
        for header in (None, "Bearer ", "Bearer not-a-token-anyone-was-given", "Basic abc", "garbage"):
            with self.subTest(header=header):
                from api.auth import get_current_user
                with self.assertRaises(HTTPException) as ctx:
                    get_current_user(authorization=header, request=None)
                self.assertEqual(ctx.exception.status_code, 401)
                self.assertEqual(ctx.exception.detail["error"], "unauthorized")
                self.assertNotIn("expires_at", ctx.exception.detail)

    def test_a_token_inside_the_week_still_signs_in(self):
        grant = self.grant_for("tester@example.com", age_days=6)
        self.assertEqual(self.sign_in_with(grant.token).id, grant.user_id)

    def test_an_expired_invite_token_of_someone_who_was_never_a_tester_is_generic(self):
        user = users_store.create_user("invitee@example.com", status="invited", plan="none")
        raw = users_store.issue_invite_token(user.id, ttl=timedelta(seconds=-5))
        self.assertEqual(self.refused_detail(raw)["error"], "unauthorized")

    def test_a_revoked_tester_token_is_generic(self):
        grant = self.grant_for("tester@example.com", age_days=8)
        users_store.revoke_all_tokens(grant.user_id)
        self.assertEqual(self.refused_detail(grant.token)["error"], "unauthorized")

    def test_a_suspended_testers_expired_token_is_generic(self):
        grant = self.grant_for("tester@example.com", age_days=8)
        users_store.set_user_status(grant.user_id, "suspended")
        self.assertEqual(self.refused_detail(grant.token)["error"], "unauthorized")

    def test_an_old_token_of_a_tester_who_was_extended_is_generic_while_the_new_one_works(self):
        stamp = datetime.now(timezone.utc)
        first = testers.grant_tester(email="tester@example.com", now=stamp - timedelta(days=10))
        extended = testers.extend_tester(first.user_id, "useful feedback", now=stamp)
        self.assertEqual(self.refused_detail(first.token)["error"], "unauthorized")
        self.assertEqual(self.sign_in_with(extended.token).id, first.user_id)

    def test_when_every_token_of_an_extended_tester_has_ended_the_date_is_the_last_one(self):
        stamp = datetime.now(timezone.utc)
        first = testers.grant_tester(email="tester@example.com", now=stamp - timedelta(days=20))
        extended = testers.extend_tester(first.user_id, "useful feedback",
                                         now=stamp - timedelta(days=10))
        for token in (first.token, extended.token):
            detail = self.refused_detail(token)
            self.assertEqual(detail["error"], "tester_access_expired")
            self.assertEqual(detail["expires_at"], extended.expires_at)

    def test_a_tester_with_a_lapsed_subscription_is_still_told_their_access_ended(self):
        grant = self.grant_for("tester@example.com", age_days=8)
        customers.upsert_customer(grant.user_id, "cus_lapsed")
        customers.upsert_subscription(grant.user_id, "sub_lapsed", "canceled")
        self.assertEqual(self.refused_detail(grant.token)["error"], "tester_access_expired")

    def test_the_lookup_failing_leaves_the_ordinary_401(self):
        grant = self.grant_for("tester@example.com", age_days=8)
        from src.appstate import tester_upgrade
        with mock.patch.object(tester_upgrade, "expired_token_window",
                               side_effect=RuntimeError("db is locked")):
            self.assertEqual(self.refused_detail(grant.token)["error"], "unauthorized")

    def test_the_admin_token_comparison_is_still_constant_time(self):
        import inspect
        from api import auth
        self.assertIn("secrets.compare_digest", inspect.getsource(auth._require_admin))


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheRealAppAnswersTheSameWay(_BillingOff):
    """The page asks GET /billing/status with whatever token it holds; this is
    what comes back over ASGI, headers and all."""

    @classmethod
    def setUpClass(cls):
        from api.app import app
        cls.app = app

    def _status(self, token):
        from tests.test_api_surface_auth import _request
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return _request(self.app, "GET", "/billing/status", headers)

    def test_expired_wrong_and_good_tokens_are_three_different_answers(self):
        expired = self.grant_for("old@example.com", age_days=8)
        good = self.grant_for("new@example.com", age_days=1)
        status, body = self._status(expired.token)
        self.assertEqual(status, 401)
        self.assertEqual(body["detail"]["error"], "tester_access_expired")
        self.assertEqual(body["detail"]["expires_at"], expired.expires_at)
        status, body = self._status("not-a-token")
        self.assertEqual((status, body["detail"]["error"]), (401, "unauthorized"))
        status, body = self._status(good.token)
        self.assertEqual(status, 200)
        self.assertEqual(body, {"status": "not_configured"})


# ===========================================================================
# 6. The state module itself.
# ===========================================================================

class TheUpgradeStateRules(_BillingOff):
    def _state(self, user_id, now=None):
        from src.appstate import tester_upgrade
        return tester_upgrade.upgrade_state(users_store.get_user(user_id), now=now)

    def test_expiry_is_the_same_instant_the_token_itself_stops_working(self):
        stamp = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
        grant = testers.grant_tester(email="tester@example.com", now=stamp)
        ends = stamp + testers.TESTER_ACCESS_TTL
        self.assertEqual(self._state(grant.user_id, ends - timedelta(seconds=1))["state"],
                         "tester_active")
        self.assertEqual(self._state(grant.user_id, ends)["state"], "tester_expired")
        self.assertIsNotNone(users_store.authenticate(grant.token, now=ends - timedelta(seconds=1)))
        self.assertIsNone(users_store.authenticate(grant.token, now=ends))

    def test_nobody_but_a_tester_qualifies(self):
        for status in ("invited", "active", "waitlisted", "pending_payment", "suspended"):
            user = users_store.create_user(f"{status}@example.com", status=status, plan="none")
            self.assertIsNone(self._state(user.id), status)

    def test_a_currently_paid_tester_does_not_qualify_but_a_lapsed_one_does(self):
        grant = self.grant_for(age_days=8)
        customers.upsert_customer(grant.user_id, "cus_1")
        customers.upsert_subscription(grant.user_id, "sub_1", "active")
        self.assertIsNone(self._state(grant.user_id))
        customers.upsert_subscription(grant.user_id, "sub_1", "canceled")
        self.assertEqual(self._state(grant.user_id)["state"], "tester_expired")

    def test_an_unreadable_window_reads_as_ended_never_as_time_left(self):
        grant = self.grant_for(age_days=2)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE testers SET expires_at = 'not a date' WHERE user_id = ?",
                         (grant.user_id,))
        self.assertEqual(self._state(grant.user_id)["state"], "tester_expired")


# ===========================================================================
# 7. The pages, run for real under node.
# ===========================================================================

HARNESS = r"""
class TextNode {
  constructor(t) { this.nodeType = 3; this.textContent = String(t); this.parentNode = null; }
}
class Elem {
  constructor(tag) {
    this.nodeType = 1; this.tagName = String(tag).toUpperCase(); this.attrs = {};
    this.childNodes = []; this.parentNode = null; this.listeners = {}; this.isRoot = false;
    this.style = {}; this.value = "";
  }
  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }
  get firstChild() { return this.childNodes[0] || null; }
  appendChild(c) {
    if (c.parentNode) c.parentNode.removeChild(c);
    c.parentNode = this; this.childNodes.push(c); return c;
  }
  removeChild(c) {
    const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1);
    c.parentNode = null; return c;
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  hasAttribute(k) { return k in this.attrs; }
  set textContent(v) { const t = new TextNode(v); t.parentNode = this; this.childNodes = [t]; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  get isConnected() { let n = this; while (n) { if (n.isRoot) return true; n = n.parentNode; } return false; }
  closest() { return null; }
  _all(out) { for (const c of this.children) { out.push(c); c._all(out); } return out; }
  querySelectorAll(sel) {
    const m = sel.match(/^\[([\w-]+)(?:(\^?=)'([^']*)')?\]$/);
    if (!m) throw new Error("unsupported selector " + sel);
    const [, name, op, val] = m;
    return this._all([]).filter((n) => {
      if (!(name in n.attrs)) return false;
      if (!op) return true;
      return op === "=" ? n.attrs[name] === val : n.attrs[name].startsWith(val);
    });
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

const body = new Elem("body"); body.isRoot = true;
globalThis.document = {
  createElement: (t) => new Elem(t),
  createTextNode: (t) => new TextNode(t),
  body, referrer: "",
  addEventListener() {},
  querySelector: (s) => body.querySelector(s),
  querySelectorAll: (s) => body.querySelectorAll(s),
};
const store = new Map();
globalThis.window = {
  localStorage: {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  },
  location: { search: "", host: "linehound.test", pathname: "/", hash: "" },
  history: { replaceState() {} },
  addEventListener() {}, dispatchEvent() { return true; },
  crypto: globalThis.crypto,
};

const scenario = JSON.parse(process.env.SCENARIO);
if (scenario.token) store.set("aisportsanalysis.invite_token", scenario.token);
const realSetTimeout = globalThis.setTimeout;

const calls = [];
globalThis.fetch = async (url, init) => {
  url = String(url);
  const headers = (init && init.headers) || {};
  calls.push({ url, method: (init && init.method) || "GET", auth: headers.Authorization || null });
  const json = (status, bodyObj) => ({ ok: status < 400, status, text: async () => JSON.stringify(bodyObj) });
  if (url.startsWith("/meta")) {
    if (scenario.meta === null) throw new Error("offline");
    return json(200, scenario.meta);
  }
  if (url === "/billing/status") {
    const r = scenario.status || { code: 200, body: { status: "not_configured" } };
    if (r.network) throw new Error("offline");
    return json(r.code, r.body);
  }
  if (url === "/signup") return json(200, scenario.signup);
  return json(200, {});
};

const text = (n) => (n.nodeType === 3 ? n.textContent : n.childNodes.map(text).join("\n"));
const hooks = (n) => n._all([]).filter((x) => "data-hook" in x.attrs).map((x) => x.attrs["data-hook"]);
const settle = () => new Promise((r) => realSetTimeout(r, 30));
const main = document.createElement("main"); body.appendChild(main);
const pick = (hook) => { const n = main.querySelector(`[data-hook='${hook}']`); return n ? n.textContent : null; };

const out = { calls };
if (scenario.kind === "signin") {
  const { renderSignin } = await import("./signin.js");
  await renderSignin(main, {});
  await settle();
  if (scenario.submit) {
    main.querySelector("[data-hook='invite-token-input']").value = scenario.submit;
    await main.querySelector("[data-hook='signin-form']").listeners.submit[0]({ preventDefault() {} });
    await settle();
  }
  if (scenario.clear) {
    await main.querySelector("[data-hook='clear-token']").listeners.click[0]();
    await settle();
  }
  const upgrade = main.querySelector("[data-hook='tester-upgrade']");
  out.ended = pick("tester-ended-line");
  out.notOpen = pick("tester-not-open");
  out.upgrade = upgrade ? upgrade.textContent : null;
  out.upgradeHref = upgrade ? upgrade.attrs.href : null;
  out.status = pick("signin-status");
  out.hooks = hooks(main);
  out.page = text(main);
} else if (scenario.kind === "signup") {
  const { renderSignup } = await import("./signup.js");
  await renderSignup(main);
  main.querySelector("[data-hook='signup-email-input']").value = "someone@example.com";
  await main.querySelector("[data-hook='signup-form']").listeners.submit[0]({ preventDefault() {} });
  out.expired = pick("signup-tester-expired");
  out.active = pick("signup-tester-active");
  out.hooks = hooks(main);
  out.page = text(main);
} else if (scenario.kind === "helpers") {
  const c = await import("./checkout.js");
  const state = c.checkoutState(scenario.meta);
  out.notOpen = c.TESTER_NOT_OPEN;
  out.ended = c.testerEndedLine(scenario.iso);
  out.active = c.testerActiveLine(scenario.iso);
  out.notice = c.testerSignupNotice(scenario.status, scenario.iso);
  out.label = c.upgradeLabel(state);
  out.cta = c.ctaLabel(state);
}
console.log("@@" + JSON.stringify(out));
"""

EXPIRED_401 = {"code": 401, "body": {"detail": {
    "error": "tester_access_expired", "message": "early access has ended for this token",
    "expires_at": "2026-10-03T12:00:00+00:00"}}}
PLAIN_401 = {"code": 401, "body": {"detail": {"error": "unauthorized",
                                              "message": "missing, invalid, expired, or revoked token"}}}
OFF = {"billing": {"checkout": "off", "trial_days": 7, "price_cents": 1999}}
UNAVAILABLE = {"billing": {"checkout": "unavailable", "trial_days": 7, "price_cents": 1999}}
ON7 = {"billing": {"checkout": "on", "trial_days": 7, "price_cents": 1999}}
ON0 = {"billing": {"checkout": "on", "trial_days": 0, "price_cents": 1999}}

ENDED = "Your early access ended on 3 October 2026."
NOT_OPEN = "Paid plans are not open yet. Reply to Brey if you want to keep going."

# What the owner never lets a page say about this offer, plus the trial wording
# tests/test_checkout_copy_states.py forbids while checkout is off.
FORBIDDEN_WORDS = re.compile(
    r"profit|\bedge\b|winning|guarantee|sharp|beat the book|trial|cancel anytime|7[- ]day|!|—|–",
    re.I)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class ThePagesUnderNode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        for path in JS.glob("*.js"):
            shutil.copy(path, cls._tmp.name)
        Path(cls._tmp.name, "package.json").write_text('{"type": "module"}', encoding="utf-8")
        Path(cls._tmp.name, "harness.mjs").write_text(HARNESS, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_scenario(self, **scenario):
        proc = subprocess.run(["node", "harness.mjs"], cwd=self._tmp.name,
                              env=dict(os.environ, SCENARIO=json.dumps(scenario)),
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        return json.loads(line[2:])

    # ---- sign-in -----------------------------------------------------------

    def test_signin_with_an_ended_token_and_billing_off_says_so_and_offers_no_button(self):
        for name, meta in (("off", OFF), ("unavailable", UNAVAILABLE), ("unreachable", None)):
            with self.subTest(state=name):
                out = self.run_scenario(kind="signin", meta=meta, token="old-tester-token",
                                        status=EXPIRED_401)
                self.assertEqual(out["ended"], ENDED)
                self.assertEqual(out["notOpen"], NOT_OPEN)
                self.assertIsNone(out["upgrade"])
                self.assertIn({"url": "/billing/status", "method": "GET",
                               "auth": "Bearer old-tester-token"}, out["calls"])
                blob = out["ended"] + " " + out["notOpen"]
                self.assertIsNone(FORBIDDEN_WORDS.search(blob), blob)

    def test_signin_with_an_ended_token_and_billing_on_offers_the_checkout_button(self):
        out = self.run_scenario(kind="signin", meta=ON7, token="old-tester-token", status=EXPIRED_401)
        self.assertEqual(out["ended"], ENDED)
        self.assertEqual(out["upgrade"], "Start your 7-day free trial")
        self.assertEqual(out["upgradeHref"], "#/signup")
        self.assertIsNone(out["notOpen"])
        out = self.run_scenario(kind="signin", meta=ON0, token="old-tester-token", status=EXPIRED_401)
        self.assertEqual(out["upgrade"], "Start your subscription")

    def test_the_button_label_is_the_one_checkout_js_decides(self):
        for meta in (ON7, ON0, _meta_on(14)):
            with self.subTest(meta=meta):
                helpers = self.run_scenario(kind="helpers", meta=meta, iso="x", status="tester_expired")
                page = self.run_scenario(kind="signin", meta=meta, token="t", status=EXPIRED_401)
                self.assertEqual(page["upgrade"], helpers["label"])
                self.assertEqual(helpers["label"], helpers["cta"])
        off = self.run_scenario(kind="helpers", meta=OFF, iso="x", status="tester_expired")
        self.assertIsNone(off["label"])

    def test_a_wrong_token_a_good_token_a_dead_network_and_no_token_show_nothing_new(self):
        cases = (("plain 401", dict(token="wrong", status=PLAIN_401)),
                 ("good token", dict(token="good", status={"code": 200, "body": {"status": "active"}})),
                 ("network down", dict(token="good", status={"network": True})),
                 ("server error", dict(token="good", status={"code": 500, "body": {"detail": "boom"}})),
                 ("payment required", dict(token="good", status={"code": 402, "body": {
                     "detail": {"error": "subscription_expired"}}})))
        for name, extra in cases:
            with self.subTest(case=name):
                out = self.run_scenario(kind="signin", meta=ON7, **extra)
                self.assertIsNone(out["ended"])
                self.assertIsNone(out["notOpen"])
                self.assertIsNone(out["upgrade"])
                self.assertNotIn("early access ended", out["page"])
        out = self.run_scenario(kind="signin", meta=ON7, status=EXPIRED_401)
        self.assertIsNone(out["ended"])
        self.assertEqual([c for c in out["calls"] if c["url"] == "/billing/status"], [],
                         "no stored token, nothing to ask about")

    def test_saving_an_ended_token_shows_the_ended_state_instead_of_open_today(self):
        out = self.run_scenario(kind="signin", meta=OFF, status=EXPIRED_401, submit="old-tester-token")
        self.assertEqual(out["ended"], ENDED)
        self.assertEqual(out["notOpen"], NOT_OPEN)
        self.assertEqual(out["status"], "Token saved.")
        self.assertIn({"url": "/billing/status", "method": "GET",
                       "auth": "Bearer old-tester-token"}, out["calls"])

    def test_saving_a_wrong_token_says_exactly_what_it_always_said(self):
        out = self.run_scenario(kind="signin", meta=OFF, status=PLAIN_401, submit="typo")
        self.assertEqual(out["status"], "Token saved. Open Today to load the board.")
        self.assertIsNone(out["ended"])

    def test_clearing_the_token_removes_the_ended_state(self):
        out = self.run_scenario(kind="signin", meta=OFF, token="old", status=EXPIRED_401, clear=True)
        self.assertIsNone(out["ended"])
        self.assertEqual(out["status"], "Token cleared.")

    def test_a_missing_date_still_reads_truthfully(self):
        no_date = {"code": 401, "body": {"detail": {"error": "tester_access_expired"}}}
        out = self.run_scenario(kind="signin", meta=OFF, token="old", status=no_date)
        self.assertEqual(out["ended"], "Your early access has ended.")

    # ---- signup ------------------------------------------------------------

    def test_signup_says_the_same_words_for_an_expired_tester(self):
        out = self.run_scenario(kind="signup", meta=OFF, signup={
            "user_id": 4, "status": "tester_expired", "expires_at": "2026-10-03T12:00:00+00:00"})
        self.assertEqual(out["expired"], ENDED + " " + NOT_OPEN)
        self.assertIsNone(out["active"])
        self.assertNotIn("signup-existing-account", out["hooks"])
        self.assertNotIn("signup-unrecognized-response", out["hooks"])
        self.assertIsNone(FORBIDDEN_WORDS.search(out["expired"]), out["expired"])

    def test_signup_says_when_an_active_testers_access_ends(self):
        out = self.run_scenario(kind="signup", meta=OFF, signup={
            "user_id": 4, "status": "tester_active", "expires_at": "2026-10-09T08:30:00+00:00"})
        self.assertEqual(out["active"],
                         "Your early access runs until 9 October 2026. " + NOT_OPEN)
        self.assertIsNone(out["expired"])
        self.assertIsNone(FORBIDDEN_WORDS.search(out["active"]), out["active"])

    def test_signup_with_a_checkout_link_is_unchanged_for_a_tester(self):
        out = self.run_scenario(kind="signup", meta=ON7, signup={
            "user_id": 4, "checkout": {"status": "redirect", "checkout_url": "https://pay.example/x"}})
        self.assertIn("signup-checkout-link", out["hooks"])
        self.assertNotIn("signup-tester-expired", out["hooks"])

    def test_the_old_statuses_still_say_what_they_said(self):
        for status in ("invited", "active", "suspended"):
            with self.subTest(status=status):
                out = self.run_scenario(kind="signup", meta=OFF, signup={"user_id": 4, "status": status})
                self.assertIn("signup-existing-account", out["hooks"])
                self.assertIsNone(out["expired"])

    # ---- the words -----------------------------------------------------------

    def test_the_new_strings_make_no_forbidden_claim_in_any_billing_state(self):
        for name, meta in (("off", OFF), ("unavailable", UNAVAILABLE), ("unreachable", None)):
            helpers = self.run_scenario(kind="helpers", meta=meta, iso="2026-10-03T12:00:00+00:00",
                                        status="tester_expired")
            for key in ("notOpen", "ended", "active", "notice"):
                with self.subTest(state=name, string=key):
                    self.assertIsNone(FORBIDDEN_WORDS.search(helpers[key]), helpers[key])
            self.assertEqual(helpers["notOpen"], NOT_OPEN)
            self.assertEqual(helpers["ended"], ENDED)

    def test_no_page_hard_codes_the_wording_that_checkout_js_decides(self):
        checkout = (JS / "checkout.js").read_text(encoding="utf-8")
        self.assertIn('export const TESTER_NOT_OPEN = "' + NOT_OPEN + '";', checkout)
        for name in ("signin.js", "signup.js", "dom.js", "landing.js", "cardrecord.js"):
            source = (JS / name).read_text(encoding="utf-8")
            for literal in ("Paid plans are not open yet", "Your early access ended",
                            "Your early access runs until", "Start your"):
                self.assertNotIn(literal, source, f"{name}: {literal!r}")
        signin = (JS / "signin.js").read_text(encoding="utf-8")
        self.assertIn("upgradeLabel", signin)
        self.assertIn("TESTER_NOT_OPEN", signin)
        self.assertIn('"tester_access_expired"', signin)

    def test_the_error_code_the_page_keys_on_is_the_one_the_server_sends(self):
        from src.appstate import tester_upgrade
        self.assertEqual(tester_upgrade.TESTER_ACCESS_EXPIRED_ERROR, "tester_access_expired")
        self.assertEqual((tester_upgrade.TESTER_EXPIRED, tester_upgrade.TESTER_ACTIVE),
                         ("tester_expired", "tester_active"))
        signup = (JS / "signup.js").read_text(encoding="utf-8")
        for status in (tester_upgrade.TESTER_EXPIRED, tester_upgrade.TESTER_ACTIVE):
            self.assertIn(f'"{status}"', signup)


def _meta_on(days):
    return {"billing": {"checkout": "on", "trial_days": days, "price_cents": 1999}}


if __name__ == "__main__":
    unittest.main()
