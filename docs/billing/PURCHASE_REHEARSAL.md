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

| 14 | A failed payment (trial ends and the first charge fails, or a renewal fails) ends access at the end of the PAID period, not the new one; a successful retry restores it | yes | PASS `test_billing_failed_payment` (all 14 tests; the first two classes failed before the fix) | NOT RUN (step 13) |

"PASS" in the first column means the named tests passed in the test run
recorded at the bottom of this file. It does not mean a human has seen it
work with Stripe.

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
13. **Failed payment.** Buy with a fourth email
    (`rehearsal-4@linehound.app`) using Stripe's test card
    `4000 0000 0000 0341` (it is accepted at checkout and declined on the
    first real charge). On the Billing page write down the date it shows;
    that is the trial's end, about 7 days out. In the Stripe dashboard, test
    mode: Subscriptions, that subscription, Actions, End trial now. Stripe
    tries the charge, it is declined, and the subscription goes `past_due`.
    Reload the Billing page. **Pass:** the date has NOT moved (it is still
    the trial's end, not a month out); the status reads "canceled" (this
    app shows every non-paying Stripe status that way). **Fail:** the date
    is about a month away. Then look for the `invoice.payment_failed` line
    in the Roadmap table below. Ending the trial early does not shorten what
    was promised, so the card will still open until the original trial end;
    to see it refused I will give you the same one command as step 8.
    *(row 14)* In the Stripe webhook settings for staging, make sure the
    endpoint is also sent `invoice.payment_failed` (it is only logged, but
    it is the line that proves the decline arrived). The retry-succeeds
    case is covered in process only: Stripe's test dashboard cannot make a
    declining card start working.

Tell me each step's result ("3 ok", "6 showed two subscriptions") and I will
fill the table. I can check `/health` and the public pages from outside; I
cannot see the admin page or fill in a card.

## Roadmap cases: what to look for on staging

Each case below has the in-process test that proves our logic, the staging
step that proves the wiring, and the exact line to find in the staging log
(`fly logs -a linehound-staging`). Only the owner types the test card.

**The request-log line** is written by the middleware in `api/app.py` through
`src/appstate/reqlog.py`, one per request, to stderr:

```
method=GET path=/ufc/fight-night status=401 latency_ms=29.2 user=-
```

Fields, in order: `method`, `path` (the route TEMPLATE, for example
`/signup/complete`, never the raw URL), `status`, `latency_ms`, `user`.
`user` is `-` for an anonymous request. For a signed-in request it is NOT the
account id: it is the first 16 hex characters of the sha256 of the id, so
lines from one account match each other and never name it. Bearer tokens,
emails and bodies are never logged. A webhook request is anonymous
(`user=-`), because Stripe is not signed in. Do not expect to read an email
or id in any line; match accounts by the `user=` value being the same across
your own requests.

The one non-request line this work adds is written by the webhook handler,
also to stderr:

```
billing: invoice.payment_failed user=<16 hex> subscription=sub_... attempt=1
```

| Case | In-process test | Staging step | Log lines to find |
|---|---|---|---|
| Closed success tab | `BuyAndComeBack.test_purchase_persists_and_access_survives_closing_the_page`, `test_the_buyer_who_closed_the_tab_before_the_token_arrived_can_come_back` | 3 and 4 | `method=POST path=/billing/webhook status=200 ... user=-` for the payment, then later `method=GET path=/signup/complete status=200 ... user=-` if the page is reopened, or `status=404` once the link has expired (the support re-issue path, step 5); the first signed-in request after returning shows `status=200` with a `user=` value |
| The same event delivered twice | `DuplicateWebhook.test_a_redelivered_payment_grants_nothing_twice` | 6 (Resend) | two identical `method=POST path=/billing/webhook status=200` lines (the resend answers 200 like the first delivery); the admin page still shows one user and one subscription |
| An active tester converting | `test_expired_tester_paid_path.PayingFromInsideTheWeekThroughTheBillingPage.test_an_invited_tester_who_pays_becomes_active`, `TesterCheckoutWithBillingOn.test_a_tester_still_inside_the_week_can_pay_early` | 11, done while the week is still running | `method=POST path=/billing/tester-checkout status=200 ... user=<hash>` (or `/billing/checkout` if started from the Billing page), then `method=POST path=/billing/webhook status=200 ... user=-` |
| An expired tester converting | `test_expired_tester_paid_path.PayingAsAFormerTester.test_one_user_active_with_the_subscription`, `TesterCheckoutWithBillingOn.test_an_expired_tester_token_starts_the_checkout_on_their_own_account` | 11 and 12 | `method=POST path=/billing/tester-checkout status=200 ... user=<hash>` (the token proves who they are, so the hash is present), the webhook line, and afterwards `method=GET path=/ufc/fight-night status=200 ... user=<same hash>`; the old week token still gets `status=401` |
| Cancellation | `CancelAndExpiry.test_cancel_stops_renewal_and_keeps_what_was_paid_for` | 7 | `method=POST path=/billing/cancel status=200 ... user=<hash>`; a following `method=GET path=/ufc/fight-night status=200 ... user=<same hash>` shows access continued; a `customer.subscription.updated` webhook line follows if Stripe sends one |
| Expiry | `CancelAndExpiry.test_after_the_paid_period_access_is_refused_with_a_reason` | 8 (simulated; the period end is moved by the one command) | `method=GET path=/ufc/fight-night status=402 ... user=<same hash>`, and `method=GET path=/billing/status status=200 ... user=<same hash>` (the billing page must still open) |
| Failed payment | `test_billing_failed_payment` (trial then first charge, renewal, retry succeeds, redelivery, stale events) | 13 | `billing: invoice.payment_failed user=<hash> subscription=sub_... attempt=1`, then `method=POST path=/billing/webhook status=200 ... user=-` for it and for the `customer.subscription.updated` that follows; the Billing page date must not move |

### Proving the paid gate on staging

Staging runs with `APP_PUBLIC_DEMO=1` (`deploy/fly.staging.toml`). That empties
the paid gate on most product routes (`/today`, `/games`, `/odds`,
`/betcheck` and the other routers in `api/app.py`'s `_authed_paid` group), so
**those routes answer 200 to anyone on staging and prove nothing about
payment.** Do not use them for this rehearsal.

`/ufc/fight-night` is always gated. `api/ufc_fights.py` builds its router with
`dependencies=[Depends(require_paid_access)]` itself, and `api/app.py` mounts
it with a bare `app.include_router(ufc_fights_router)`, outside
`_authed_paid`; `tests/test_api_ufc_fights.py::test_public_demo_mode_cannot_open_it`
pins that it answers 401 under demo mode. Use it, with
`curl -i https://linehound-staging.fly.dev/ufc/fight-night -H "Authorization: Bearer <token>"`
(leave the header off for the anonymous case):

| When | Request | Expected status | Log line |
|---|---|---|---|
| Before paying (a signed-up buyer has no token yet; an expired tester's token behaves the same) | no header, or the ended week token | **401** | `method=GET path=/ufc/fight-night status=401 ... user=-` |
| After paying | the token from the completion page | **200** (503 `UFC data is not readable right now` also means the gate opened; staging may not hold UFC data. The pass criterion is "not 401 and not 402") | `method=GET path=/ufc/fight-night status=200 ... user=<hash>` |
| After expiry (step 8 command, or after a declined first charge once the trial end has passed) | the same token | **402** with `"error": "subscription_expired"` | `method=GET path=/ufc/fight-night status=402 ... user=<same hash>` |

The same token must give 200 then 402, with the same `user=` value on both
lines. If it gives 402 before the period end, or 200 after it, the gate is
wrong; stop and tell me.

### Stripe test-dashboard actions the owner uses

Test mode only (confirm the toggle says "Test mode" first).

- **Resend an event** (rows 5, 6): Developers, Events, open the event,
  Resend (to the staging endpoint).
- **Cancel** (rows 7, 9): easiest from the app's own Billing, Cancel button,
  which schedules the cancel for period end. In the dashboard: Subscriptions,
  the subscription, Actions, Cancel subscription, then choose "At end of
  current billing period". Do not pick "Immediately" for the rehearsal
  unless the step says so: it ends access now, by design.
- **End a trial** (row 14): Subscriptions, the subscription, Actions, End
  trial now. Pair it with test card `4000 0000 0000 0341` for the failing
  charge.
- **Make a charge decline or succeed:** only the card number decides, and it
  is typed on Stripe's own checkout page by the owner. Nothing else in this
  file ever touches a card.

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

Row 14 (failed payment) was added after that run. It was checked with the
billing test modules only (360 tests, no failure): `test_billing_failed_payment`,
`test_billing_acceptance_path`, `test_billing_cancellation_policy`,
`test_appstate_billing`, `test_appstate_customers`,
`test_expired_tester_paid_path`, `test_expired_tester_review`,
`test_api_billing`, `test_api_signup`, `test_checkout_copy_states`,
`test_checkout_delivery`, `test_api_boundary`. The full suite has not been
re-run on the change.
