"""Adversarial review of 40a9974c (expired tester -> paying subscriber).

Each test here pins a defect the review confirmed in that commit's design (or a
pre-existing one on the same path), as the property that SHOULD hold. They are
marked `expectedFailure` so the suite stays green while the defect exists; once
a fix lands the test passes, unittest reports an "unexpected success" (which
fails the run), and the decorator must be removed. Do not delete one to make
the run green: fix the code, then drop the decorator.

One plain test at the end records a behaviour the review checked and found
correct (an abandoned tester checkout is not a dead end).

Reuses the fixtures of tests/test_expired_tester_paid_path.py: temp database,
the in-process Stripe stand-in (never a real request), signed webhooks.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from fastapi import HTTPException
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.appstate import customers
from src.appstate import savedbets
from src.appstate import testers
from src.appstate import users as users_store
from tests import test_billing_acceptance_path as acceptance
from tests.test_expired_tester_paid_path import HARNESS, JS, _BillingOff, _BillingOn


def _past(hours=1):
    return acceptance._epoch(datetime.now(timezone.utc) - timedelta(hours=hours))


# ===========================================================================
# D1. Billing ON: knowing a tester's EMAIL is enough to get a bearer token for
#     their existing account (saved bets included). Before 40a9974c the signup
#     form answered {"status": "invited"} / {"status": "active"} for these
#     accounts and never opened a checkout bound to them.
# ===========================================================================

class EmailAloneMustNotOpenAnExistingTestersAccount(_BillingOn):
    """Exact request sequence, no credential at any step:

        POST /signup {"email": "<victim>"}            -> checkout_url bound to victim's user_id
        (stranger completes the hosted Stripe checkout with their own card; the
         7-day trial means nothing is charged)
        checkout.session.completed / subscription.created webhooks (Stripe's own)
        GET /signup/complete?session_id=<from the stranger's own redirect>
                                                      -> 366-day token for victim's account
        GET /my-bets with that token                  -> the victim's saved bets
    """

    def _stranger_buys(self, email, uid, session_id):
        started = self.signup(email)                    # only the email is known
        if "checkout" not in started:
            return None                                 # fixed: no email-only checkout
        self.assertEqual(started["user_id"], uid)
        self.webhook({"id": f"evt_{session_id}", "type": "checkout.session.completed",
                      "data": {"object": {"id": session_id, "client_reference_id": str(uid),
                                          "customer": acceptance.CUSTOMER,
                                          "subscription": f"sub_{session_id}",
                                          "payment_status": "no_payment_required"}}})
        try:
            return self.collect_token(session_id)["token"]
        except HTTPException:
            return None                                 # fixed: no token handed out

    def _victims_bets_visible_to(self, token):
        from api.mybets import list_my_bets
        return list_my_bets(current_user=self.sign_in_with(token))["bets"]

    @unittest.expectedFailure
    def test_a_stranger_cannot_read_an_expired_testers_saved_bets(self):
        grant = self.grant_for("victim@example.com", age_days=8)
        savedbets.save_bet(grant.user_id, "MLB-2026-09-30-NYY-BOS", "NYY", price=-110.0)
        token = self._stranger_buys("victim@example.com", grant.user_id, "cs_stranger_1")
        if token is not None:
            self.assertEqual(self._victims_bets_visible_to(token), [],
                             "a token minted for an email-only checkout reads the "
                             "tester's existing saved bets")

    @unittest.expectedFailure
    def test_a_stranger_cannot_read_an_active_testers_saved_bets(self):
        grant = self.grant_for("victim@example.com", age_days=2)    # still inside the week
        savedbets.save_bet(grant.user_id, "MLB-2026-09-30-NYY-BOS", "NYY", price=-110.0)
        token = self._stranger_buys("victim@example.com", grant.user_id, "cs_stranger_2")
        if token is not None:
            self.assertEqual(self._victims_bets_visible_to(token), [])

    @unittest.expectedFailure
    def test_a_stranger_cannot_take_over_a_lapsed_former_tester_subscriber(self):
        # The keep_status branch: an `active` former tester whose subscription
        # ended. Pre-change, signup answered {"status": "active"} for them.
        grant = self.grant_for("victim@example.com", age_days=40)
        uid = grant.user_id
        self.signup("victim@example.com")
        self.pay(uid)                                    # the victim's own purchase
        savedbets.save_bet(uid, "MLB-2026-09-30-NYY-BOS", "NYY", price=-110.0)
        self.webhook(self.subscription_event("deleted", "canceled", period_end=_past()))
        self.assertEqual(users_store.get_user(uid).status, "active")
        token = self._stranger_buys("victim@example.com", uid, "cs_stranger_3")
        if token is not None:
            self.assertEqual(self._victims_bets_visible_to(token), [])

    @unittest.expectedFailure
    def test_a_stranger_cannot_change_a_testers_account_state(self):
        # Short of paying: one unauthenticated POST moves the tester from
        # `invited` to `pending_payment` and creates a Stripe customer for them.
        grant = self.grant_for("victim@example.com", age_days=2)
        self.signup("victim@example.com")
        self.assertEqual(users_store.get_user(grant.user_id).status, "invited")
        self.assertIsNone(customers.get_customer_ref(grant.user_id))


# ===========================================================================
# D3 (pre-existing, same path). A redelivered checkout.session.completed that
#     arrives after customer.subscription.deleted rewrites the record to
#     "active" with no cancel_at: has_paid_access is then True forever.
# ===========================================================================

class RedeliveredCompletedMustNotResurrectAccess(_BillingOn):
    @unittest.expectedFailure
    def test_completed_redelivered_after_deleted_keeps_the_subscription_ended(self):
        grant = self.grant_for("former@example.com", age_days=8)
        uid = grant.user_id
        self.signup("former@example.com")
        token = self.pay(uid)
        self.webhook(self.subscription_event("deleted", "canceled", period_end=_past()))
        self.assertFalse(customers.has_paid_access(uid))
        # Stripe delivers at least once and retries for days; event order is not
        # guaranteed. The same completed event again:
        self.webhook(self.completed_event(uid))
        self.assertFalse(customers.has_paid_access(uid),
                         customers.get_subscription_record(uid))
        with self.assertRaises(HTTPException):
            self.open_paid_page(token)


# ===========================================================================
# D4 (owner decision on WHICH fix; the silent no-op is the defect). The admin
#     extends a tester whose paid subscription lapsed: extend_tester succeeds
#     and hands back a fresh 7-day token, and that token gets 402 on every paid
#     page, because a subscription record exists and the tester window is
#     never consulted. Either refuse (as grant_tester refuses has_subscription)
#     or let the extension actually open the board.
# ===========================================================================

class ExtendingALapsedPayingTesterIsNotASilentNoOp(_BillingOn):
    @unittest.expectedFailure
    def test_extend_either_refuses_or_opens_the_board(self):
        grant = self.grant_for("former@example.com", age_days=8)
        uid = grant.user_id
        self.signup("former@example.com")
        self.pay(uid)
        self.webhook(self.subscription_event("deleted", "canceled", period_end=_past()))
        try:
            extended = testers.extend_tester(uid, "sent three useful bug reports")
        except testers.TesterRefused:
            return
        self.assertEqual(self.open_paid_page(extended.token).id, uid)


# ===========================================================================
# Checked and correct: an abandoned tester checkout is not a dead end.
# ===========================================================================

class AnAbandonedTesterCheckoutIsNotADeadEnd(_BillingOn):
    def test_admin_can_still_extend_and_the_person_can_retry(self):
        grant = self.grant_for("tester@example.com", age_days=8)
        uid = grant.user_id
        self.assertIn("checkout", self.signup("tester@example.com"))
        self.assertEqual(users_store.get_user(uid).status, "pending_payment")
        # Abandoned. The admin extends: allowed, and the new token opens the board.
        extended = testers.extend_tester(uid, "asked for more time")
        self.assertEqual(self.open_paid_page(extended.token).id, uid)
        # They come back to pay: a checkout again, same account.
        again = self.signup("tester@example.com")
        self.assertEqual((again["user_id"], again["checkout"]["status"]), (uid, "redirect"))
        self.assertEqual(self.user_count(), 1)
        # grant_tester refuses (checkout_open before already_a_tester), nothing written.
        with self.assertRaises(testers.TesterRefused) as refused:
            testers.grant_tester(email="tester@example.com")
        self.assertEqual(refused.exception.code, "checkout_open")
        self.assertEqual(testers.count_granted(), 1)


# ===========================================================================
# D5. web/js/signin.js: showExpiredTester has no guard against overlapping
#     calls (render-time check + Save, or a double-click on Save), so a slower
#     answer overwrites a newer one.
# ===========================================================================

RACE = HARNESS.split("const out = { calls };")[0] + r"""
const out = { calls };
// Token-dependent /billing/status: "old-expired" is an ended tester token,
// anything else is a good token.
const baseFetch = globalThis.fetch;
globalThis.fetch = async (url, init) => {
  if (String(url) === "/billing/status") {
    const auth = (init && init.headers && init.headers.Authorization) || null;
    calls.push({ url: "/billing/status", method: "GET", auth });
    const expired = auth === "Bearer old-expired";
    const body = expired
      ? { detail: { error: "tester_access_expired", expires_at: "2026-10-03T12:00:00+00:00" } }
      : { status: "not_configured" };
    return { ok: !expired, status: expired ? 401 : 200, text: async () => JSON.stringify(body) };
  }
  return baseFetch(url, init);
};
const { renderSignin } = await import("./signin.js");
await renderSignin(main, {});           // the render-time check is now in flight
const input = main.querySelector("[data-hook='invite-token-input']");
const submit = main.querySelector("[data-hook='signin-form']").listeners.submit[0];
input.value = scenario.submit;
const presses = [];
for (let i = 0; i < scenario.presses; i++) presses.push(submit({ preventDefault() {} }));
await Promise.all(presses);
await settle();
out.ended = main.querySelectorAll("[data-hook='tester-ended-line']").length;
out.buttons = main.querySelectorAll("[data-hook='tester-upgrade']").length;
out.notOpen = main.querySelectorAll("[data-hook='tester-not-open']").length;
console.log("@@" + JSON.stringify(out));
"""

ON7 = {"billing": {"checkout": "on", "trial_days": 7, "price_cents": 1999}}


@unittest.skipUnless(shutil.which("node"), "node not installed")
class SigninDoesNotRaceItself(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        for path in JS.glob("*.js"):
            shutil.copy(path, cls._tmp.name)
        Path(cls._tmp.name, "package.json").write_text('{"type": "module"}', encoding="utf-8")
        Path(cls._tmp.name, "race.mjs").write_text(RACE, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_race(self, **scenario):
        proc = subprocess.run(["node", "race.mjs"], cwd=self._tmp.name,
                              env=dict(os.environ, SCENARIO=json.dumps(scenario)),
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        return json.loads(line[2:])

    @unittest.expectedFailure
    def test_saving_an_ended_token_twice_shows_the_ended_state_once(self):
        out = self.run_race(meta=ON7, token="old-expired", submit="old-expired", presses=2)
        self.assertEqual((out["ended"], out["buttons"]), (1, 1), out)

    @unittest.expectedFailure
    def test_a_good_token_saved_over_an_ended_one_shows_no_ended_state(self):
        out = self.run_race(meta=ON7, token="old-expired", submit="new-good", presses=1)
        self.assertEqual((out["ended"], out["buttons"]), (0, 0), out)


if __name__ == "__main__":
    unittest.main()
