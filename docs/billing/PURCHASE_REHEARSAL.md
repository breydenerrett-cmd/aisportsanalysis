# Purchase rehearsal: one PASS/FAIL table

Production billing stays OFF until every critical row below reads PASS in
both columns. This file is the single record.

Two columns, because they prove different things:

- **In process**: the real application code run end to end against a
  stand-in for Stripe (signed webhooks, no network). Proves our logic.
  Automated; the test name is given so anyone can re-run it.
- **Staging**: a person clicking through `linehound-staging.fly.dev` with
  Stripe in test mode and Stripe's test card. Proves the wiring: real Stripe
  pages, real webhook delivery, real redirects. Only the owner can do this
  (it needs a card form filled in on a live host).

| # | Path | Critical | In process | Staging (Stripe test mode) |
|---|---|---|---|---|
| 1 | New customer: signup, checkout, webhook, entitlement, paid card opens | yes | PASS `test_billing_acceptance_path.BuyAndComeBack.test_purchase_persists_and_access_survives_closing_the_page` | NOT RUN |
| 2 | Close the success page, come back later, still have access | yes | PASS same test, plus `test_a_reload_inside_the_window_gets_the_same_token` | NOT RUN |
| 3 | Closed the tab before the token appeared: can still get in | yes | PASS `BuyAndComeBack.test_the_buyer_who_closed_the_tab_before_the_token_arrived_can_come_back` | NOT RUN |
| 4 | Lost the token entirely: support re-issues one, the old one dies | yes | PASS `RecoveryWithoutTheTab.test_support_can_reissue_and_the_old_token_dies` | NOT RUN |
| 5 | The same webhook delivered twice grants nothing twice | yes | PASS `DuplicateWebhook.test_a_redelivered_payment_grants_nothing_twice` | NOT RUN |
| 5a | A payment webhook redelivered after the subscription ended does not bring it back | yes | PASS `test_expired_tester_review.test_completed_redelivered_after_deleted_keeps_the_subscription_ended` | not practical to stage |
| 6 | A forged or unsigned webhook changes nothing | yes | PASS `DuplicateWebhook.test_a_forged_or_unsigned_webhook_changes_nothing` | not applicable (cannot be forged from the Stripe dashboard) |
| 7 | Cancel: renewal stops, access continues to the end of the paid period | yes | PASS `CancelAndExpiry.test_cancel_stops_renewal_and_keeps_what_was_paid_for` | NOT RUN |
| 8 | After the paid period: access refused, with a reason, billing page still reachable | yes | PASS `CancelAndExpiry.test_after_the_paid_period_access_is_refused_with_a_reason` | NOT RUN (needs the period end moved; see step 8 below) |
| 9 | Reactivate before the period ends: renewal resumes, no gap | no | PASS `test_billing_cancellation_policy.ReactivationTests.test_reactivate_before_expiration_resumes_renewal_with_no_gap` | NOT RUN |
| 10 | After expiry: a new checkout works on the same account | yes | PASS `test_expired_tester_paid_path.AccessIsGovernedByTheSubscription.test_cancel_keeps_access_to_period_end_then_blocks_then_a_new_checkout_works` | NOT RUN |
| 11 | Expired tester: clear ended state, checkout on the same account started with their own token, paid access replaces the week, history kept, no second account | yes | PASS `test_expired_tester_paid_path` and `test_expired_tester_review` | NOT RUN |
| 11a | A stranger who knows only a tester's email gets no checkout and changes nothing | yes | PASS `test_expired_tester_review` (`test_a_stranger_cannot_read_an_expired_testers_saved_bets` and three more) | NOT RUN |
| 12 | Billing switched on but misconfigured: an honest error, never a silent waitlist | yes | PASS `BrokenBillingFailsOutLoud`, `test_checkout_delivery.SilentWaitlistTests` | not applicable |
| 13 | Billing off (production today): no checkout, no promise of a payment | yes | PASS `BillingSwitchedOff.test_off_says_so_and_never_promises_a_payment`, `test_expired_tester_paid_path.SignupWithBillingOff` | verified on production 2026-10-02 (`/health` checkout off) |

"PASS" in the first column means the named tests passed in the full suite
run recorded at the bottom of this file. It does not mean a human has seen
it work with Stripe.

## The staging run (owner, about 20 minutes, nothing is charged)

Before starting, open `https://linehound-staging.fly.dev/health` and check
it says `checkout.mode: test`. If it says `live`, stop.

1. **Buy.** `https://linehound-staging.fly.dev/web/landing.html`, press the
   main button, enter an email you can recognise (for example
   `rehearsal-1@linehound.app`). On Stripe's page use card
   `4242 4242 4242 4242`, any future date, any CVC. You land on the
   completion page and see an access token. Copy it. *(rows 1)*
2. **Use it.** Open tonight's card with that token. *(row 1)*
3. **Close everything.** Close the tab. Open the site again, go to Sign in,
   paste the token. The card opens. *(row 2)*
4. **Lose the tab.** Buy again with a second email
   (`rehearsal-2@linehound.app`) and close the tab the moment Stripe sends
   you back, before the token shows. Reopen the link from your browser
   history. The token is shown. *(row 3)*
5. **Lose the token.** On the staging admin page, re-issue a token for the
   first email. The new one works and the old one does not. *(row 4)*
6. **Duplicate webhook.** In the Stripe dashboard, test mode: Developers,
   Events, the `checkout.session.completed` event for the first purchase,
   Resend. The admin page still shows one user and one subscription.
   *(row 5)*
7. **Cancel.** In the app, Billing, Cancel. The page says access continues
   until a date. The card still opens. *(row 7)*
8. **Expiry.** There is no way to wait out a period in a rehearsal. I will
   give you one command that moves the stored period end into the past on
   staging only; after it, the card is refused with a reason and the Billing
   page still opens. This row will be marked "simulated". *(row 8)*
9. **Buy again after expiry.** From the Billing page, start a new checkout
   with the same account and the test card. Access returns; still one user.
   *(row 10)*
10. **Reactivate.** With the second account: cancel, then Reactivate before
    the period ends. Renewal is back on. *(row 9)*
11. **Expired tester.** On the staging admin page grant tester access to
    `rehearsal-3@linehound.app`. I will give you one command that ends that
    tester's week on staging. Sign in with the tester token: the page says
    the early access ended and offers the button. Press it (no email to
    retype; the token proves who you are), pay with the test card. One
    user, active, saved bets intact. *(row 11)*
12. **Stranger with the email.** In a private window, enter
    `rehearsal-3@linehound.app` on the signup form before step 11's payment.
    The page says the email already has early access and to sign in with
    the token. No Stripe page opens. *(row 11a)*

Tell me each step's result ("3 ok", "6 showed two subscriptions") and I will
fill the table. I can check `/health` and the public pages from outside; I
cannot see the admin page or fill in a card.

## Found in review and fixed (2026-10-03)

The first version of the expired-tester fix let anyone who typed a tester's
email start a checkout on that tester's account and walk away with its
token. An independent review caught it before it was pushed. A tester's
checkout now starts only from their own access token
(`POST /billing/tester-checkout`); the signup form answers with a status and
nothing else. The same review found an older fault (row 5a) and it is fixed
too. Detail: `docs/audit/2026-10-03/EXPIRED_TESTER_PAID_PATH.md`.

## Open decisions before production billing

- **A second free week.** Checkout gives every new buyer a 7-day Stripe
  trial. A former tester who upgrades would get that too: a second free
  week. Recommendation: no trial for anyone who has already had tester
  access. It needs a code change before billing opens (the trial length
  has to become part of the checkout's idempotency key, and the button
  label must stop promising a trial to someone who will not get one).
- **An old payment event after a newer subscription.** The subscription
  table holds one row per person. A payment event for an old subscription,
  redelivered after the same person has bought again, can still overwrite
  the newer record. Rare; needs a guard before billing opens.
- **A deep review before the switch.** This path touches sign-in and
  payments. Before production billing is turned on, run the cloud review
  (`/code-review ultra`) on the branch; it is yours to launch.

## Suite run behind the "In process" column

2026-10-03, local Windows run of every test module on the state that was
pushed: 9,969 tests, no failure outside the eight known Windows-only
identities (`docs/audit/2026-09-28/full_suite_integrated_1169b2d6_failures.txt`).
Linux CI result: see `docs/audit/2026-10-03/RELEASE.md`.
