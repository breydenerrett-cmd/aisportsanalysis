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

THE DOOR IS THE TOKEN, NOT THE EMAIL (review of 40a9974c, finding D1). The first
fix opened the checkout from the unauthenticated signup form, bound to the
tester's existing user id, so anyone who typed a tester's email could complete
that checkout and be handed a token for the tester's account. Now POST /signup
answers a tester's email with a status word and nothing else, with billing on or
off, and the tester pays through POST /billing/tester-checkout, which accepts
their own (possibly expired) token. These tests drive both: the stranger who has
only the email gets nothing and changes nothing; the person holding the token
pays on the same account.

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

import contextlib
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

    def checkout_by_token(self, token):
        """POST /billing/tester-checkout the way FastAPI runs it: the route's own
        dependency turns the bearer token into the tester (or raises the 401),
        then the route function runs. The rate limit is bypassed here (the real
        app, limiter included, is TheTokenRouteOverASGI below)."""
        from api.auth import get_tester_checkout_user
        from api.signup import tester_checkout
        user = get_tester_checkout_user(authorization=f"Bearer {token}", request=None)
        return tester_checkout(current_user=user, _rate_limit=None)

    def refused_checkout(self, authorization):
        """The 401 body of POST /billing/tester-checkout for this Authorization
        header (None for no header at all)."""
        from api.auth import get_tester_checkout_user
        with self.assertRaises(HTTPException) as ctx:
            get_tester_checkout_user(authorization=authorization, request=None)
        self.assertEqual(ctx.exception.status_code, 401)
        return ctx.exception.detail

    @contextlib.contextmanager
    def stripe_calls(self):
        """Every request the Stripe stand-in receives, as (method, path). The
        stand-in is the only thing that can answer (a synthetic key), so an empty
        list means no Stripe object was created or read."""
        import urllib.parse
        calls = []
        real = billing._fake_stripe_transport

        def spy(method, url, headers, data):
            calls.append((method, urllib.parse.urlparse(url).path))
            return real(method, url, headers, data)

        with mock.patch.object(billing, "_fake_stripe_transport", spy):
            yield calls

    def world(self):
        """Everything a checkout attempt could touch, as comparable values: users,
        tokens, tester rows, Stripe customer and subscription rows, activation
        tokens, idempotency keys and analytics events."""
        customers.get_subscription_record(0)        # the tables exist before they are read
        testers.count_granted()
        return {
            "users": self.rows("SELECT * FROM users ORDER BY id"),
            "tokens": self.rows("SELECT token_hash, user_id, expires_at, revoked_at, "
                                "first_used_at FROM tokens ORDER BY 1"),
            "testers": self.rows("SELECT * FROM testers ORDER BY user_id"),
            "extensions": self.rows("SELECT * FROM tester_extensions"),
            "customers": self.rows("SELECT * FROM billing_customers"),
            "subs": self.rows("SELECT user_id, stripe_subscription_id, status, cancel_at, "
                              "current_period_end FROM billing_subscriptions"),
            "activation": self.rows("SELECT stripe_session_id, user_id FROM "
                                    "signup_activation_tokens"),
            "idempotency": self.rows("SELECT * FROM billing_checkout_idempotency"),
            "attribution": self.rows("SELECT * FROM signup_attribution"),
            "events": [(e.kind, e.user_hash) for e in events.list_events()],
        }


class _BillingOn(_Base):
    ENV = acceptance.SELLING_ENV


class _BillingOff(_Base):
    ENV = OFF_ENV


# ===========================================================================
# 1. POST /signup with a tester's EMAIL, billing ON: a status word, nothing else.
#    An email address is not a credential, so the form can start nothing for a
#    tester's account (review D1). Every test here is a stranger who knows only
#    the email.
# ===========================================================================

class SignupForATestersEmailWithBillingOn(_BillingOn):
    def _no_date(self, result, grant):
        body = json.dumps(result)
        self.assertNotIn("expires_at", result)
        self.assertNotIn(grant.expires_at[:10], body)       # no date of any kind
        self.assertNotIn(grant.granted_at[:10], body)

    def test_an_expired_testers_email_gets_a_status_word_and_no_checkout(self):
        grant = self.grant_for(age_days=8)
        with self.stripe_calls() as stripe:
            result = self.signup("tester@example.com")
        self.assertEqual(result, {"user_id": grant.user_id, "status": "tester_expired"})
        self.assertNotIn("checkout", result)
        self._no_date(result, grant)
        self.assertEqual(stripe, [], "a Stripe request was made for an email-only caller")
        self.assertEqual(self.user_count(), 1, "a second account was created")

    def test_an_active_testers_email_gets_tester_active_and_no_date(self):
        grant = self.grant_for(age_days=2)
        with self.stripe_calls() as stripe:
            result = self.signup("tester@example.com")
        self.assertEqual(result, {"user_id": grant.user_id, "status": "tester_active"})
        self._no_date(result, grant)
        self.assertEqual(stripe, [])
        # Their own token is untouched.
        self.assertEqual(self.sign_in_with(grant.token).id, grant.user_id)

    def test_nothing_about_the_account_changes_however_often_it_is_asked(self):
        for age_days in (2, 8):
            with self.subTest(age_days=age_days):
                self.setUp()
                grant = self.grant_for(age_days=age_days)
                before = self.world()
                with self.stripe_calls() as stripe:
                    for _ in range(3):
                        self.signup("tester@example.com")
                self.assertEqual(self.world(), before)
                self.assertEqual(stripe, [])
                self.assertEqual(self.status_of(grant.user_id), "invited")
                self.assertIsNone(customers.get_customer_ref(grant.user_id))
                self.assertNotIn(events.CHECKOUT_STARTED, [e.kind for e in events.list_events()])

    def test_the_email_may_be_written_in_any_case_and_still_finds_the_account(self):
        grant = self.grant_for(age_days=9)
        result = self.signup("  Tester@Example.COM ")
        self.assertEqual(result, {"user_id": grant.user_id, "status": "tester_expired"})
        self.assertEqual(self.user_count(), 1)

    def test_attribution_a_stranger_sends_is_not_written_to_a_testers_account(self):
        # The activation report leaves out testers whose stored attribution is
        # internal and splits the rest by channel, so an unauthenticated POST
        # must not be able to fill in a tester's first touch.
        from api.signup import SignupRequest, signup
        grant = self.grant_for(age_days=8)
        before = self.world()
        result = signup(SignupRequest(email="tester@example.com", attribution={
            "utm_source": "internal", "utm_campaign": "planted"}), _rate_limit=None)
        self.assertEqual(result, {"user_id": grant.user_id, "status": "tester_expired"})
        self.assertEqual(customers.get_signup_attribution(grant.user_id), {})
        self.assertEqual(self.world(), before)
        # A non-tester's returning signup still fills in a missing first touch.
        other = users_store.create_user("pending@example.com", status="pending_payment", plan="none")
        signup(SignupRequest(email="pending@example.com",
                             attribution={"utm_source": "newsletter"}), _rate_limit=None)
        self.assertEqual(customers.get_signup_attribution(other.id).get("utm_source"), "newsletter")

    def test_a_tester_parked_at_pending_payment_still_gets_only_a_status_word(self):
        # Their own (token) checkout was started and abandoned. The email form
        # must neither reopen it nor waitlist them.
        grant = self.grant_for()
        self.checkout_by_token(grant.token)
        self.assertEqual(self.status_of(grant.user_id), "pending_payment")
        before = self.world()
        with self.stripe_calls() as stripe:
            result = self.signup("tester@example.com")
        self.assertEqual(result, {"user_id": grant.user_id, "status": "tester_expired"})
        self.assertEqual((self.world(), stripe), (before, []))

    def test_billing_on_but_unable_to_take_a_payment_is_still_just_a_status_word(self):
        grant = self.grant_for()
        os.environ.pop(billing.ENV_STRIPE_WEBHOOK_SECRET)
        result = self.signup("tester@example.com")
        self.assertEqual(result, {"user_id": grant.user_id, "status": "tester_expired"})
        self.assertEqual(self.status_of(grant.user_id), "invited")

    def test_a_suspended_tester_is_left_alone(self):
        grant = self.grant_for()
        users_store.set_user_status(grant.user_id, "suspended")
        result = self.signup("tester@example.com")
        self.assertEqual(result, {"user_id": grant.user_id, "status": "suspended"})

    def test_a_lapsed_former_tester_subscriber_is_not_offered_a_checkout_by_email(self):
        # The keep_status case: an `active` former tester whose subscription ended.
        grant = self.grant_for("former@example.com", age_days=40)
        self.checkout_by_token(grant.token)
        self.pay(grant.user_id)
        # The paid period runs out: time passing moves the paid-through instant
        # into the past. (These tests used to let the `deleted`/cancel event's
        # own period end do that; an event announcing an end never shortens what
        # a trial or invoice paid for, and the fixture's trial runs to 2099.)
        self.age_rows("billing_subscriptions", "paid_through", timedelta(hours=1))
        self.webhook(self.subscription_event("deleted", "canceled",
                                             period_end=acceptance._epoch(
                                                 datetime.now(timezone.utc) - timedelta(hours=1))))
        self.assertEqual(self.status_of(grant.user_id), "active")
        before = self.world()
        with self.stripe_calls() as stripe:
            result = self.signup("former@example.com")
        self.assertEqual(result, {"user_id": grant.user_id, "status": "tester_expired"})
        self.assertEqual((self.world(), stripe), (before, []))

    def test_a_paying_former_tester_who_asks_again_is_told_active(self):
        grant = self.grant_for("former@example.com", age_days=8)
        self.checkout_by_token(grant.token)
        self.pay(grant.user_id)
        before = self.world()
        with self.stripe_calls() as stripe:
            again = self.signup("former@example.com")
        self.assertEqual(again, {"user_id": grant.user_id, "status": "active"})
        self.assertEqual((self.world(), stripe), (before, []))

    def test_an_entitled_tester_the_webhook_has_not_yet_activated_is_told_active(self):
        # Paid, subscription recorded, status not yet moved off pending_payment.
        grant = self.grant_for("former@example.com", age_days=8)
        self.checkout_by_token(grant.token)
        customers.upsert_customer(grant.user_id, acceptance.CUSTOMER)
        customers.upsert_subscription(grant.user_id, acceptance.SUBSCRIPTION, "trialing",
                                      current_period_end="2099-01-01T00:00:00+00:00")
        self.assertEqual(self.status_of(grant.user_id), "pending_payment")
        self.assertEqual(self.signup("former@example.com"),
                         {"user_id": grant.user_id, "status": "active"})

    def test_a_comped_invite_that_is_not_a_tester_keeps_todays_answer(self):
        invited = users_store.create_user("comped@example.com", status="invited", plan="none")
        result = self.signup("comped@example.com")
        self.assertEqual(result, {"user_id": invited.id, "status": "invited"})
        self.assertEqual(self.status_of(invited.id), "invited")

    def test_an_active_customer_who_was_never_a_tester_keeps_todays_answer(self):
        paying = users_store.create_user("customer@example.com", status="active", plan="beta")
        result = self.signup("customer@example.com")
        self.assertEqual(result, {"user_id": paying.id, "status": "active"})

    def test_a_new_buyer_still_gets_the_checkout_a_new_buyer_always_got(self):
        result = self.signup("brand-new@example.com")
        self.assertEqual(result["checkout"]["status"], "redirect", result)
        self.assertEqual(result["checkout"]["checkout_url"], billing.FAKE_TRANSPORT_CHECKOUT_URL)
        self.assertEqual(self.status_of(result["user_id"]), "pending_payment")
        # ...and so does a pending non-tester asking again.
        self.assertEqual(self.signup("brand-new@example.com")["checkout"]["status"], "redirect")

    def test_a_waitlisted_non_tester_asking_again_still_gets_a_checkout(self):
        waitlisted = users_store.create_user("wait@example.com", status="waitlisted", plan="none")
        result = self.signup("wait@example.com")
        self.assertEqual((result["user_id"], result["checkout"]["status"]),
                         (waitlisted.id, "redirect"))
        self.assertEqual(self.status_of(waitlisted.id), "pending_payment")


# ===========================================================================
# 2. POST /signup with a tester's email, billing OFF (production today): the
#    same status word, status untouched.
# ===========================================================================

class SignupForATestersEmailWithBillingOff(_BillingOff):
    def test_an_expired_tester_is_told_their_access_ended_and_no_date(self):
        grant = self.grant_for(age_days=8)
        result = self.signup("tester@example.com")
        self.assertEqual(result, {"user_id": grant.user_id, "status": "tester_expired"})
        self.assertNotIn("checkout", result)

    def test_an_active_tester_is_told_so_and_no_date(self):
        grant = self.grant_for(age_days=2)
        self.assertEqual(self.signup("tester@example.com"),
                         {"user_id": grant.user_id, "status": "tester_active"})

    def test_nothing_is_corrupted_by_asking_again_and_again(self):
        grant = self.grant_for(age_days=8)
        before = self.world()
        for _ in range(3):
            self.assertEqual(self.signup("tester@example.com")["status"], "tester_expired")
        self.assertEqual(self.world(), before)
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

    def test_an_extended_tester_gets_the_same_two_keys_and_no_extended_date(self):
        stamp = datetime.now(timezone.utc)
        first = testers.grant_tester(email="tester@example.com", now=stamp - timedelta(days=20))
        extended = testers.extend_tester(first.user_id, "three specific problems found",
                                         now=stamp - timedelta(days=10))
        result = self.signup("tester@example.com")
        self.assertEqual(result, {"user_id": first.user_id, "status": "tester_expired"})
        self.assertNotIn(extended.expires_at[:10], json.dumps(result))


# ===========================================================================
# 2b. POST /billing/tester-checkout: the tester's own token is the proof.
# ===========================================================================

GENERIC_401 = {"error": "unauthorized",
               "message": "missing, invalid, expired, or revoked token"}


class TesterCheckoutWithBillingOn(_BillingOn):
    def test_an_expired_tester_token_starts_the_checkout_on_their_own_account(self):
        grant = self.grant_for(age_days=8)
        result = self.checkout_by_token(grant.token)
        self.assertEqual(result, {"user_id": grant.user_id, "checkout": {
            "status": "redirect", "checkout_url": billing.FAKE_TRANSPORT_CHECKOUT_URL}})
        self.assertEqual(self.user_count(), 1, "a second account was created")
        # Status moves the way a new buyer's does.
        self.assertEqual(self.status_of(grant.user_id), "pending_payment")
        self.assertEqual(customers.get_customer_ref(grant.user_id), acceptance.CUSTOMER)

    def test_it_is_the_same_answer_a_new_buyer_gets(self):
        new_buyer = self.signup("brand-new@example.com")
        self.setUp()    # a fresh database: the Stripe stand-in has one customer id
        tester = self.checkout_by_token(self.grant_for(age_days=8).token)
        self.assertEqual(sorted(tester), sorted(new_buyer))
        self.assertEqual(tester["checkout"], new_buyer["checkout"])

    def test_a_tester_still_inside_the_week_can_pay_early(self):
        grant = self.grant_for(age_days=2)
        result = self.checkout_by_token(grant.token)
        self.assertEqual((result["user_id"], result["checkout"]["status"]),
                         (grant.user_id, "redirect"))
        self.assertEqual(self.user_count(), 1)
        # Their tester token is untouched by starting a checkout.
        self.assertEqual(self.sign_in_with(grant.token).id, grant.user_id)

    def test_a_second_attempt_before_paying_is_the_same_user_and_a_checkout_again(self):
        grant = self.grant_for()
        first = self.checkout_by_token(grant.token)
        second = self.checkout_by_token(grant.token)
        self.assertEqual(first["user_id"], second["user_id"], grant.user_id)
        self.assertEqual(second["checkout"]["status"], "redirect")
        self.assertEqual(self.user_count(), 1)
        self.assertEqual(self.status_of(grant.user_id), "pending_payment")

    def test_it_records_checkout_started_and_no_second_account_created_event(self):
        self.checkout_by_token(self.grant_for().token)
        kinds = [e.kind for e in events.list_events()]
        self.assertEqual(kinds.count(events.CHECKOUT_STARTED), 1)
        self.assertNotIn(events.ACCOUNT_CREATED, kinds)

    def test_it_does_not_mark_the_ended_token_as_used_and_it_opens_nothing_else(self):
        # The one route that accepts an ended token widens nothing: the same
        # token is still refused by every ordinary route, with the same body.
        grant = self.grant_for(age_days=8)
        self.checkout_by_token(grant.token)
        self.assertIsNone(self.rows("SELECT first_used_at FROM tokens")[0][0])
        detail = self.refused_detail(grant.token)
        self.assertEqual(detail["error"], "tester_access_expired")
        self.assertEqual(detail["expires_at"], grant.expires_at)
        with self.assertRaises(HTTPException) as ctx:
            self.open_paid_page(grant.token)
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIsNone(users_store.authenticate(grant.token))

    def test_a_lapsed_former_subscriber_may_start_again_and_keeps_their_status(self):
        grant = self.grant_for("former@example.com", age_days=40)
        self.checkout_by_token(grant.token)
        self.pay(grant.user_id)
        # The paid period runs out: time passing moves the paid-through instant
        # into the past. (These tests used to let the `deleted`/cancel event's
        # own period end do that; an event announcing an end never shortens what
        # a trial or invoice paid for, and the fixture's trial runs to 2099.)
        self.age_rows("billing_subscriptions", "paid_through", timedelta(hours=1))
        self.webhook(self.subscription_event(
            "deleted", "canceled",
            period_end=acceptance._epoch(datetime.now(timezone.utc) - timedelta(hours=1))))
        again = self.checkout_by_token(grant.token)
        self.assertEqual(again["checkout"]["status"], "redirect")
        self.assertEqual(self.status_of(grant.user_id), "active")

    def test_billing_on_but_unable_to_take_a_payment_is_the_error_a_new_buyer_gets(self):
        grant = self.grant_for()
        os.environ.pop(billing.ENV_STRIPE_WEBHOOK_SECRET)
        new_buyer = self.signup("brand-new@example.com")
        result = self.checkout_by_token(grant.token)
        self.assertEqual(result["status"], "error", result)
        self.assertIn("nothing has been charged", result["message"])
        self.assertNotIn("checkout", result)
        self.assertEqual((result["status"], result["message"]),
                         (new_buyer["status"], new_buyer["message"]))
        # Not waitlisted, not moved: nothing happened to their account.
        self.assertEqual(self.status_of(grant.user_id), "invited")
        self.assertIsNone(customers.get_customer_ref(grant.user_id))

    def test_a_stripe_failure_is_the_generic_error_and_never_the_raw_body(self):
        grant = self.grant_for()
        raw = 'Stripe said: {"error": "secret account detail"}'
        with mock.patch.object(billing.StripeBillingProvider, "create_checkout",
                               side_effect=RuntimeError(raw)):
            result = self.checkout_by_token(grant.token)
        self.assertEqual(result, {"user_id": grant.user_id, "status": "error",
                                  "message": "checkout could not be started; try again shortly"})
        self.assertNotIn("secret", json.dumps(result))
        self.assertEqual(self.status_of(grant.user_id), "invited")


class TesterCheckoutRefusals(_BillingOn):
    """Everything that is not a real, unrevoked, unsuspended, not-currently-paid
    tester's token is the SAME 401 body every bad token gets, and the attempt
    writes nothing and calls Stripe not at all."""

    def _all_refused(self, authorizations):
        before = self.world()
        with self.stripe_calls() as stripe:
            for header in authorizations:
                with self.subTest(header=header):
                    self.assertEqual(self.refused_checkout(header), GENERIC_401)
        self.assertEqual((self.world(), stripe), (before, []))

    def test_a_made_up_token_and_every_malformed_header(self):
        self.grant_for()
        self._all_refused([None, "", "Bearer", "Bearer ", "Bearer not-a-token-anyone-was-given",
                           "Basic abc", "garbage", "bearer ",
                           "Bearer " + "a" * 5000])

    def test_a_revoked_tester_token(self):
        grant = self.grant_for(age_days=8)
        users_store.revoke_all_tokens(grant.user_id)
        self._all_refused([f"Bearer {grant.token}"])
        # An active one, revoked, is no different.
        fresh = self.grant_for("fresh@example.com", age_days=1)
        users_store.revoke_all_tokens(fresh.user_id)
        self._all_refused([f"Bearer {fresh.token}"])

    def test_the_old_token_of_a_tester_whose_support_reissue_revoked_it(self):
        grant = self.grant_for(age_days=8)
        users_store.revoke_all_tokens(grant.user_id)
        reissued = users_store.issue_invite_token(grant.user_id)
        self._all_refused([f"Bearer {grant.token}"])
        # The new token is a real token of a tester: accepted.
        self.assertEqual(self.checkout_by_token(reissued)["checkout"]["status"], "redirect")

    def test_an_expired_invite_token_of_someone_who_was_never_a_tester(self):
        user = users_store.create_user("invitee@example.com", status="invited", plan="none")
        raw = users_store.issue_invite_token(user.id, ttl=timedelta(seconds=-5))
        self._all_refused([f"Bearer {raw}"])

    def test_a_good_invite_token_of_someone_who_was_never_a_tester(self):
        # Not a tester, so not this route's business; /billing/checkout is theirs.
        user = users_store.create_user("invitee@example.com", status="invited", plan="none")
        raw = users_store.issue_invite_token(user.id)
        self._all_refused([f"Bearer {raw}"])

    def test_a_suspended_testers_token_expired_or_not(self):
        ended = self.grant_for("ended@example.com", age_days=8)
        live = self.grant_for("live@example.com", age_days=1)
        users_store.set_user_status(ended.user_id, "suspended")
        users_store.set_user_status(live.user_id, "suspended")
        self._all_refused([f"Bearer {ended.token}", f"Bearer {live.token}"])

    def test_a_currently_paying_tester_by_any_token(self):
        grant = self.grant_for("payer@example.com", age_days=8)
        subscriber_token = self.pay_directly(grant.user_id)
        self._all_refused([f"Bearer {grant.token}", f"Bearer {subscriber_token}"])
        self.assertEqual(len(customers.list_subscription_rows()), 1)

    def test_a_token_lookup_that_fails_is_a_401_not_a_500_and_not_a_pass(self):
        from src.appstate import tester_upgrade
        grant = self.grant_for(age_days=8)
        with mock.patch.object(tester_upgrade, "tester_for_token",
                               side_effect=RuntimeError("db is locked")):
            self.assertEqual(self.refused_checkout(f"Bearer {grant.token}"), GENERIC_401)

    def test_the_refusal_says_nothing_about_who_holds_the_token(self):
        grant = self.grant_for("secret-tester@example.com", age_days=8)
        users_store.set_user_status(grant.user_id, "suspended")
        body = json.dumps(self.refused_checkout(f"Bearer {grant.token}"))
        for secret in ("secret-tester", grant.token, "expires_at", "suspended", "tester"):
            self.assertNotIn(secret, body)

    def pay_directly(self, user_id):
        """A paid subscription for user_id with no tester-checkout step, for
        tests that need an entitled tester without going through the route."""
        self.webhook(self.completed_event(user_id))
        self.webhook(self.subscription_event("created", "trialing"))
        return self.collect_token()["token"]


class TesterCheckoutWithBillingOff(_BillingOff):
    NOT_OPEN = {"status": "not_configured",
                "message": "paid plans are not open yet; nothing has been changed"}

    def test_an_expired_tester_gets_the_honest_answer_and_nothing_changes(self):
        grant = self.grant_for(age_days=8)
        before = self.world()
        with self.stripe_calls() as stripe:
            result = self.checkout_by_token(grant.token)
        self.assertEqual(result, self.NOT_OPEN)
        self.assertEqual((self.world(), stripe), (before, []))
        self.assertEqual(self.status_of(grant.user_id), "invited")
        self.assertNotIn(events.CHECKOUT_STARTED, [e.kind for e in events.list_events()])

    def test_an_active_tester_gets_the_same_answer(self):
        grant = self.grant_for(age_days=2)
        before = self.world()
        self.assertEqual(self.checkout_by_token(grant.token), self.NOT_OPEN)
        self.assertEqual(self.world(), before)
        self.assertEqual(self.sign_in_with(grant.token).id, grant.user_id)

    def test_a_tester_parked_at_pending_payment_stays_there(self):
        grant = self.grant_for()
        users_store.set_user_status(grant.user_id, "pending_payment")
        self.assertEqual(self.checkout_by_token(grant.token), self.NOT_OPEN)
        self.assertEqual(self.status_of(grant.user_id), "pending_payment")

    def test_billing_off_does_not_loosen_who_may_ask(self):
        self.grant_for(age_days=8)
        for header in (None, "Bearer made-up-token"):
            self.assertEqual(self.refused_checkout(header), GENERIC_401)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheTokenRouteOverASGI(_BillingOn):
    """The real app: routing, the route's own dependencies, the rate limiter and
    the 401 bodies as a browser sees them."""

    @classmethod
    def setUpClass(cls):
        from api.app import app
        cls.app = app

    def setUp(self):
        super().setUp()
        from api import signup as signup_api
        # Every test database numbers its first user 1, so a limiter that
        # outlives a test would carry one test's count into the next.
        signup_api._tester_checkout_limiter._windows.clear()
        self.addCleanup(signup_api._tester_checkout_limiter._windows.clear)

    def post(self, token=None, path="/billing/tester-checkout", method="POST"):
        from tests.test_api_surface_auth import _request
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return _request(self.app, method, path, headers)

    def test_an_expired_token_gets_the_redirect_over_http(self):
        grant = self.grant_for(age_days=8)
        status, body = self.post(grant.token)
        self.assertEqual(status, 200, body)
        self.assertEqual(body, {"user_id": grant.user_id, "checkout": {
            "status": "redirect", "checkout_url": billing.FAKE_TRANSPORT_CHECKOUT_URL}})

    def test_bad_tokens_get_the_401_every_ordinary_route_gives(self):
        self.grant_for(age_days=8)
        status, body = self.post("not-a-token")
        self.assertEqual((status, body["detail"]), (401, GENERIC_401))
        status_none, body_none = self.post(None)
        self.assertEqual((status_none, body_none["detail"]), (401, GENERIC_401))
        # ...and it is the same body an ordinary route gives the same token.
        status_ord, body_ord = self.post("not-a-token", path="/billing/status", method="GET")
        self.assertEqual((status_ord, body_ord["detail"]), (401, GENERIC_401))

    def test_it_is_a_post_only_route(self):
        grant = self.grant_for(age_days=8)
        status, _ = self.post(grant.token, method="GET")
        self.assertEqual(status, 405)

    def test_ordinary_routes_still_refuse_the_ended_token_after_it_started_a_checkout(self):
        grant = self.grant_for(age_days=8)
        self.assertEqual(self.post(grant.token)[0], 200)
        for method, path in (("GET", "/billing/status"), ("GET", "/my-bets"),
                             ("POST", "/billing/checkout")):
            with self.subTest(path=path):
                status, body = self.post(grant.token, path=path, method=method)
                self.assertEqual(status, 401, body)
                self.assertEqual(body["detail"]["error"], "tester_access_expired")

    def test_a_tester_is_limited_to_ten_checkouts_an_hour_and_the_eleventh_is_a_429(self):
        from api.signup import TESTER_CHECKOUT_RATE_LIMIT_PER_HOUR
        self.assertEqual(TESTER_CHECKOUT_RATE_LIMIT_PER_HOUR, 10)
        grant = self.grant_for(age_days=8)
        with self.stripe_calls() as stripe:
            codes = [self.post(grant.token)[0] for _ in range(10)]
            status, body = self.post(grant.token)
        self.assertEqual(codes, [200] * 10)
        self.assertEqual(status, 429)
        self.assertEqual(body["detail"]["error"], "rate_limited")
        self.assertGreater(body["detail"]["retry_after"], 0)
        # One tester, one Stripe customer: ten checkouts created one customer.
        self.assertEqual(stripe.count(("POST", "/v1/customers")), 1)
        self.assertEqual(len(self.rows("SELECT * FROM billing_customers")), 1)

    def test_the_limit_is_per_tester_and_made_up_tokens_never_spend_it(self):
        one = self.grant_for("one@example.com", age_days=8)
        two = self.grant_for("two@example.com", age_days=8)
        # The Stripe stand-in hands every new customer the same id, so give the
        # second tester an existing one (as a returning customer would have).
        customers.upsert_customer(two.user_id, "cus_second_tester")
        with self.stripe_calls() as stripe:
            for _ in range(25):
                self.assertEqual(self.post("made-up-token")[0], 401)
            self.assertEqual(stripe, [], "a made-up token reached Stripe")
            for _ in range(10):
                self.assertEqual(self.post(one.token)[0], 200)
            self.assertEqual(self.post(one.token)[0], 429)
            # Someone else's quota is their own.
            self.assertEqual(self.post(two.token)[0], 200)

    def test_a_refused_token_is_not_counted_against_the_limit_either(self):
        grant = self.grant_for(age_days=8)
        revoked = self.grant_for("revoked@example.com", age_days=8)
        users_store.revoke_all_tokens(revoked.user_id)
        for _ in range(12):
            self.assertEqual(self.post(revoked.token)[0], 401)
        self.assertEqual(self.post(grant.token)[0], 200)


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
        # The whole flow begins at the sign-in page, where the person's own ended
        # token starts the checkout: if an expired tester cannot start one there,
        # nothing below can happen.
        self.started = self.checkout_by_token(self.grant.token)
        self.assertEqual(self.started["checkout"]["status"], "redirect", self.started)
        self.assertEqual(self.started["checkout"]["checkout_url"],
                         billing.FAKE_TRANSPORT_CHECKOUT_URL)
        self.assertEqual(self.status_of(self.uid), "pending_payment")
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
        # By email: a status word. By either token they hold (the ended week
        # token, or the subscriber token they were just given): a 401, because
        # they are already paid and a second checkout would be a second
        # subscription on one account.
        before = self.world()
        with self.stripe_calls() as stripe:
            again = self.signup("former@example.com")
            for token in (self.grant.token, self.token):
                detail = self.refused_checkout(f"Bearer {token}")
                self.assertEqual(detail["error"], "unauthorized")
        self.assertEqual(again, {"user_id": self.uid, "status": "active"})
        self.assertEqual(len(customers.list_subscription_rows()), 1)
        self.assertEqual((self.world(), stripe), (before, []))

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
    which (unlike the tester-checkout route) does not park them at
    pending_payment first. The webhook must still make them `active`: they
    paid."""

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
        self.checkout_by_token(grant.token)
        token = self.pay(grant.user_id)
        self.assertEqual(self.open_paid_page(token).id, grant.user_id)

        ended = acceptance._epoch(datetime.now(timezone.utc) - timedelta(hours=1))
        # The paid period runs out: time passing moves the paid-through instant
        # into the past. (These tests used to let the `deleted`/cancel event's
        # own period end do that; an event announcing an end never shortens what
        # a trial or invoice paid for, and the fixture's trial runs to 2099.)
        self.age_rows("billing_subscriptions", "paid_through", timedelta(hours=1))
        self.webhook(self.subscription_event("updated", "active", period_end=ended, cancel_at=ended))
        with self.assertRaises(HTTPException) as lapsed:
            self.open_paid_page(token)
        self.assertEqual(lapsed.exception.status_code, 402)
        self.assertEqual(lapsed.exception.detail["error"], "subscription_expired")

    def test_a_tester_who_pays_early_is_governed_by_the_subscription_not_their_week(self):
        grant = self.grant_for("early@example.com", age_days=1)     # six days of week left
        self.checkout_by_token(grant.token)
        self.pay(grant.user_id)
        ended = acceptance._epoch(datetime.now(timezone.utc) - timedelta(hours=1))
        # The paid period runs out: time passing moves the paid-through instant
        # into the past. (These tests used to let the `deleted`/cancel event's
        # own period end do that; an event announcing an end never shortens what
        # a trial or invoice paid for, and the fixture's trial runs to 2099.)
        self.age_rows("billing_subscriptions", "paid_through", timedelta(hours=1))
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
        self.checkout_by_token(grant.token)
        token = self.pay(uid)

        # Cancel: renewal stops, the period already paid for is still theirs.
        cancelled = cancel_subscription(current_user=users_store.get_user(uid), _rate_limit=None)
        self.assertTrue(cancelled["cancel_at_period_end"], cancelled)
        self.assertIsNotNone(billing_status(current_user=users_store.get_user(uid))["cancel_at"])
        self.assertEqual(self.open_paid_page(token).id, uid)

        # The period runs out.
        ended = acceptance._epoch(datetime.now(timezone.utc) - timedelta(hours=1))
        # The paid period runs out: time passing moves the paid-through instant
        # into the past. (These tests used to let the `deleted`/cancel event's
        # own period end do that; an event announcing an end never shortens what
        # a trial or invoice paid for, and the fixture's trial runs to 2099.)
        self.age_rows("billing_subscriptions", "paid_through", timedelta(hours=1))
        self.webhook(self.subscription_event("updated", "active", period_end=ended, cancel_at=ended))
        self.webhook(self.subscription_event("deleted", "canceled", period_end=ended))
        with self.assertRaises(HTTPException) as blocked:
            self.open_paid_page(token)
        self.assertEqual(blocked.exception.status_code, 402)
        self.assertFalse(customers.has_paid_access(uid))

        # Door one: the tester-checkout route, with the ended week token they
        # still hold (or the subscriber token: either proves who they are).
        for held in (grant.token, token):
            again = self.checkout_by_token(held)
            self.assertEqual(again["user_id"], uid)
            self.assertEqual(again["checkout"]["status"], "redirect", again)
        self.assertEqual(self.user_count(), 1)
        self.assertEqual(self.status_of(uid), "active", "a lapsed customer's status is not churned")
        # By email alone there is no door: a status word, no checkout.
        self.assertEqual(self.signup("former@example.com"),
                         {"user_id": uid, "status": "tester_expired"})
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
        customers.upsert_subscription(
            grant.user_id, "sub_1", "active",
            current_period_end=(datetime.now(timezone.utc) + timedelta(days=5)).isoformat())
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
const assigned = [];          // every URL the page navigated to (window.location.assign)
globalThis.window = {
  localStorage: {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  },
  location: { search: "", host: "linehound.test", pathname: "/", hash: "",
              assign(url) { assigned.push(String(url)); } },
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
  if (url === "/billing/tester-checkout") {
    const r = scenario.checkout || { code: 200, body: { user_id: 4, checkout: {
      status: "redirect", checkout_url: "https://pay.example/session" } } };
    if (r.network) throw new Error("offline");
    return json(r.code, r.body);
  }
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
  if (scenario.click) {
    // Presses of the checkout button, back to back (no await between them).
    const button = main.querySelector("[data-hook='tester-upgrade']");
    const presses = [];
    for (let i = 0; i < scenario.click; i++) presses.push(button.listeners.click[0]());
    await Promise.all(presses);
    await settle();
  }
  const upgrade = main.querySelector("[data-hook='tester-upgrade']");
  out.ended = pick("tester-ended-line");
  out.notOpen = pick("tester-not-open");
  out.upgrade = upgrade ? upgrade.textContent : null;
  out.upgradeTag = upgrade ? upgrade.tagName : null;
  out.upgradeHasHref = upgrade ? "href" in upgrade.attrs : null;
  out.upgradeDisabled = upgrade ? !!upgrade.disabled : null;
  out.upgradeError = pick("tester-upgrade-error");
  out.assigned = assigned;
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
  const link = main.querySelector("[data-hook='signup-tester-signin-link']");
  out.signinHref = link ? link.attrs.href : null;
  out.checkoutLink = pick("signup-checkout-link");
  out.hooks = hooks(main);
  out.page = text(main);
} else if (scenario.kind === "helpers") {
  const c = await import("./checkout.js");
  const state = c.checkoutState(scenario.meta);
  out.notOpen = c.TESTER_NOT_OPEN;
  out.reply = c.TESTER_REPLY;
  out.ended = c.testerEndedLine(scenario.iso);
  out.noticeExpired = c.testerSignupNotice("tester_expired");
  out.noticeActive = c.testerSignupNotice("tester_active");
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
REPLY_ONLY = "Reply to Brey if you want to keep going."
# What the signup form says for a tester's email (no date, no offer wording), and
# the link that follows it.
NOTICE_EXPIRED = ("That email already has early access, and it has ended. The sign-in page "
                  "is where to continue: use your access token there. If you lost the token, "
                  "reply to Brey.")
NOTICE_ACTIVE = ("That email already has early access. Sign in with the access token Brey "
                 "sent you. If you lost the token, reply to Brey.")
SIGNIN_LINK_TEXT = "Open the sign-in page"

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
        for name, meta in (("off", OFF), ("unavailable", UNAVAILABLE)):
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

    def test_when_meta_cannot_be_read_the_page_states_only_what_it_knows(self):
        # "Paid plans are not open yet" is a fact about the server. A page that
        # could not reach /meta (or got an answer with no billing block) does not
        # know it, so it says the access ended and to reply to Brey, nothing more.
        for name, meta in (("unreachable", None), ("no billing block", {}),
                           ("malformed billing block", {"billing": "on"})):
            with self.subTest(state=name):
                out = self.run_scenario(kind="signin", meta=meta, token="old-tester-token",
                                        status=EXPIRED_401)
                self.assertEqual(out["ended"], ENDED)
                self.assertEqual(out["notOpen"], REPLY_ONLY)
                self.assertIsNone(out["upgrade"])
                self.assertNotIn("not open", out["page"])
                self.assertIsNone(FORBIDDEN_WORDS.search(out["notOpen"]), out["notOpen"])

    def test_signin_with_an_ended_token_and_billing_on_offers_a_button_not_a_link(self):
        out = self.run_scenario(kind="signin", meta=ON7, token="old-tester-token", status=EXPIRED_401)
        self.assertEqual(out["ended"], ENDED)
        self.assertEqual(out["upgrade"], "Start your 7-day free trial")
        # A button that sends the token, not a link to a form that asks for an email.
        self.assertEqual((out["upgradeTag"], out["upgradeHasHref"]), ("BUTTON", False))
        self.assertIsNone(out["notOpen"])
        self.assertEqual([c for c in out["calls"] if c["url"] == "/billing/tester-checkout"], [],
                         "drawing the page must not start a checkout")
        out = self.run_scenario(kind="signin", meta=ON0, token="old-tester-token", status=EXPIRED_401)
        self.assertEqual(out["upgrade"], "Start your subscription")

    def test_pressing_the_button_sends_the_stored_token_and_follows_the_redirect(self):
        out = self.run_scenario(kind="signin", meta=ON7, token="old-tester-token",
                                status=EXPIRED_401, click=1)
        posts = [c for c in out["calls"] if c["url"] == "/billing/tester-checkout"]
        self.assertEqual(posts, [{"url": "/billing/tester-checkout", "method": "POST",
                                  "auth": "Bearer old-tester-token"}])
        self.assertEqual(out["assigned"], ["https://pay.example/session"])
        # The signup form (and its email field) is not part of this path.
        self.assertEqual([c for c in out["calls"] if c["url"] == "/signup"], [])

    def test_a_double_press_makes_one_request(self):
        out = self.run_scenario(kind="signin", meta=ON7, token="old-tester-token",
                                status=EXPIRED_401, click=2)
        posts = [c for c in out["calls"] if c["url"] == "/billing/tester-checkout"]
        self.assertEqual(len(posts), 1, posts)
        self.assertEqual(out["assigned"], ["https://pay.example/session"])

    def test_a_refused_or_failed_press_says_so_plainly_and_goes_nowhere(self):
        server_error = {"code": 200, "body": {
            "user_id": 4, "status": "error",
            "message": "payments are not available right now; nothing has been charged"}}
        cases = (
            ("refused", {"code": 401, "body": PLAIN_401["body"]},
             "Checkout could not be started. Nothing has been charged. " + REPLY_ONLY),
            ("rate limited", {"code": 429, "body": {"detail": {"error": "rate_limited",
                                                               "retry_after": 60.0}}},
             "Too many tries. Wait a little and press the button again. " + REPLY_ONLY),
            ("network", {"network": True},
             "Checkout could not be started. Nothing has been charged. " + REPLY_ONLY),
            ("server's own words", server_error,
             "payments are not available right now; nothing has been charged"),
            ("server says off", {"code": 200, "body": {
                "status": "not_configured", "message": "paid plans are not open yet"}}, NOT_OPEN),
            ("unrecognised answer", {"code": 200, "body": {}},
             "Checkout did not start. Nothing has been charged. " + REPLY_ONLY),
        )
        for name, checkout, expected in cases:
            with self.subTest(case=name):
                out = self.run_scenario(kind="signin", meta=ON7, token="old-tester-token",
                                        status=EXPIRED_401, checkout=checkout, click=1)
                self.assertEqual(out["upgradeError"], expected)
                self.assertEqual(out["assigned"], [])
                self.assertFalse(out["upgradeDisabled"], "the person must be able to try again")
                self.assertIsNone(FORBIDDEN_WORDS.search(out["upgradeError"]), out["upgradeError"])

    def test_the_button_label_is_the_one_checkout_js_decides(self):
        for meta in (ON7, ON0, _meta_on(14)):
            with self.subTest(meta=meta):
                helpers = self.run_scenario(kind="helpers", meta=meta, iso="x")
                page = self.run_scenario(kind="signin", meta=meta, token="t", status=EXPIRED_401)
                self.assertEqual(page["upgrade"], helpers["label"])
                self.assertEqual(helpers["label"], helpers["cta"])
        off = self.run_scenario(kind="helpers", meta=OFF, iso="x")
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

    def test_signup_tells_an_expired_testers_email_to_continue_with_the_token(self):
        # The same words with checkout on or off: the server sends a status word
        # either way, and never a checkout link for a tester's email.
        for name, meta in (("billing off", OFF), ("billing on", ON7)):
            with self.subTest(state=name):
                out = self.run_scenario(kind="signup", meta=meta, signup={
                    "user_id": 4, "status": "tester_expired"})
                self.assertEqual(out["expired"], NOTICE_EXPIRED + " " + SIGNIN_LINK_TEXT + ".")
                self.assertIsNone(out["active"])
                self.assertEqual(out["signinHref"], "#/signin")
                self.assertIsNone(out["checkoutLink"])
                for hook in ("signup-existing-account", "signup-unrecognized-response",
                             "signup-checkout-link"):
                    self.assertNotIn(hook, out["hooks"])
                self.assertIsNone(FORBIDDEN_WORDS.search(out["expired"]), out["expired"])

    def test_signup_tells_an_active_testers_email_to_sign_in_with_the_token(self):
        for name, meta in (("billing off", OFF), ("billing on", ON7)):
            with self.subTest(state=name):
                out = self.run_scenario(kind="signup", meta=meta, signup={
                    "user_id": 4, "status": "tester_active"})
                self.assertEqual(out["active"], NOTICE_ACTIVE + " " + SIGNIN_LINK_TEXT + ".")
                self.assertIsNone(out["expired"])
                self.assertEqual(out["signinHref"], "#/signin")
                self.assertIsNone(FORBIDDEN_WORDS.search(out["active"]), out["active"])

    def test_the_signup_page_shows_no_date_even_if_one_were_sent(self):
        for status in ("tester_expired", "tester_active"):
            with self.subTest(status=status):
                out = self.run_scenario(kind="signup", meta=OFF, signup={
                    "user_id": 4, "status": status, "expires_at": "2026-10-03T12:00:00+00:00"})
                shown = out["expired"] or out["active"]
                self.assertIsNone(re.search(r"20\d\d|October|\bUTC\b", shown), shown)

    def test_signup_with_a_checkout_link_is_unchanged_for_a_new_buyer(self):
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

    def test_the_tester_strings_make_no_forbidden_claim_in_any_billing_state(self):
        for name, meta in (("off", OFF), ("unavailable", UNAVAILABLE), ("unreachable", None)):
            helpers = self.run_scenario(kind="helpers", meta=meta, iso="2026-10-03T12:00:00+00:00")
            for key in ("notOpen", "reply", "ended", "noticeExpired", "noticeActive"):
                with self.subTest(state=name, string=key):
                    self.assertIsNone(FORBIDDEN_WORDS.search(helpers[key]), helpers[key])
            self.assertEqual(helpers["notOpen"], NOT_OPEN)
            self.assertEqual(helpers["reply"], REPLY_ONLY)
            self.assertEqual(helpers["ended"], ENDED)
            self.assertEqual(helpers["noticeExpired"], NOTICE_EXPIRED)
            self.assertEqual(helpers["noticeActive"], NOTICE_ACTIVE)
            # The signup notices carry no date and name no offer.
            for key in ("noticeExpired", "noticeActive"):
                self.assertIsNone(re.search(r"\d", helpers[key]), helpers[key])

    def test_no_page_hard_codes_the_wording_that_checkout_js_decides(self):
        checkout = (JS / "checkout.js").read_text(encoding="utf-8")
        self.assertIn('export const TESTER_NOT_OPEN = "' + NOT_OPEN + '";', checkout)
        self.assertIn('export const TESTER_REPLY = "' + REPLY_ONLY + '";', checkout)
        for name in ("signin.js", "signup.js", "dom.js", "landing.js", "cardrecord.js"):
            source = (JS / name).read_text(encoding="utf-8")
            for literal in ("Paid plans are not open yet", "Your early access ended",
                            "Your early access runs until", "already has early access",
                            "if you want to keep going", "Start your"):
                self.assertNotIn(literal, source, f"{name}: {literal!r}")
        signin = (JS / "signin.js").read_text(encoding="utf-8")
        for needed in ("upgradeLabel", "TESTER_NOT_OPEN", "TESTER_REPLY",
                       '"tester_access_expired"', "/billing/tester-checkout"):
            self.assertIn(needed, signin)

    def test_the_signup_page_never_reads_a_date_from_the_tester_answer(self):
        signup = (JS / "signup.js").read_text(encoding="utf-8")
        code = "\n".join(line for line in signup.splitlines()
                         if not line.lstrip().startswith(("*", "//", "/*")))
        for name in ("expires_at", "endDateLabel", "testerEndedLine", "testerActiveLine"):
            self.assertNotIn(name, code, name)

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
