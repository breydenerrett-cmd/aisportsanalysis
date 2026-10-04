# The owner's part: about 15 minutes

Everything that can be proven without a human has been (see "What is proven
and how" below). What is left is one thing only you can do: **type Stripe's
TEST card into Stripe's own page on staging.** Nothing is charged (test mode).
The parent watches the staging log while you click and tells you what it
saw; you do not read logs.

**Before you start (parent, not you):** the new `billing: webhook ...` log line
must be deployed to staging (commit "Log one non-secret line per processed
Stripe webhook event"); without it the watcher cannot tell
`checkout.session.completed` from `invoice.paid` (every webhook is the same
request line). The parent starts the watcher before your first click, because
`fly logs` keeps only about the last 100 lines:

```
fly logs -a linehound-staging | python scripts/rehearsal_watch.py --since <UTC time you start>
```

Staging note (observed 2026-10-04 18:52Z): the staging machine was OOM-killed
and restarted once while this was prepared (`fly status` showed one critical
health check). If a step below hangs, wait a minute and retry it; Stripe also
retries a webhook that arrives while the machine is down. Say so if it happens.

## The one sequence

Use a normal browser window. Tell the parent "go" before step 1 and the number
of each step as you finish it.

| # | You do (exact) | The parent looks for |
|---|---|---|
| 1 | Open the Stripe dashboard and switch the **Test mode** toggle ON (the page must say Test mode / show the orange test banner). Go to **Developers, Webhooks** (newer dashboards: **Developers, Workbench, Webhooks**), open the endpoint whose URL is `https://linehound-staging.fly.dev/billing/webhook`, choose **Edit** (Update destination), and tick **`invoice.paid`** and **`invoice.payment_failed`** in addition to the four already ticked (`checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`). Save. Labels differ a little between dashboard versions; the events are what matter. | Nothing in the log yet. It shows up as step 4's `invoice.paid` line. If that line never comes, this step did not save. |
| 2 | Open `https://linehound-staging.fly.dev/health`. It must contain `"checkout"` with `"mode": "test"`. If it says `live`, stop and tell the parent. | Parent already read this anonymously at 2026-10-04 18:54Z: `provider: stripe`, `mode: test`. |
| 3 | Open `https://linehound-staging.fly.dev/web/landing.html`, press the main button, type the email `rehearsal-1@linehound.app`, submit. You are sent to a Stripe-hosted page. | `method=POST path=/signup status=200` (weak: it is also 200 when billing says "not configured"; the Stripe page opening is the real proof, so tell the parent if it did not open). |
| 4 | **On Stripe's page type the test card yourself:** number `4242 4242 4242 4242`, any future expiry (for example `12/34`), any 3-digit CVC, any name and postcode. Press the pay/start-trial button. The success page opens and shows an access token. Copy the token into a notepad. **Do not close the tab yet.** | `billing: webhook type='checkout.session.completed' ... paid_through=-` then `type='customer.subscription.created' ... paid_through='<date>'` and `type='invoice.paid' ...`. Then `GET /signup/complete status=200`. Expected, not yet observed: the paid-through date is the trial's end (about 7 days out), and Stripe sends `invoice.paid` for the $0 trial invoice. If `invoice.paid` is absent but `customer.subscription.created` shows a date, access still opens; tell the parent, it is a finding. |
| 5 | **Close the tab.** Within 10 minutes, reopen the same success page from your browser history (History, the most recent Stripe return, or Ctrl+Shift+T). The token is shown again. | A **second** `GET /signup/complete status=200` after the payment: "return after closing the success page". After 10 minutes the page 404s by design (token re-read window); then use step 6's token. |
| 6 | Open `https://linehound-staging.fly.dev/web/index.html#/signin`, paste the token, sign in. Then open `https://linehound-staging.fly.dev/web/index.html#/ufc` (the one page on staging that is always behind the paid gate) and then `...index.html#/billing`. The Billing page shows a status and an "access until" date. Tell the parent the date. | `GET /ufc/fight-night status=200` (or `503`, which also means the gate opened; staging may hold no UFC data) with a `user=<16 hex>` value; `GET /billing/status status=200` with the same `user=`. |
| 7 | On the Billing page press **Cancel renewal**. The page says access continues until a date. Reload `#/ufc`: it still opens. | `POST /billing/cancel status=200` with the same `user=`, then another `/ufc/fight-night 200/503`. |
| 8 | **Decline case.** Sign out (or use a private window) and repeat steps 3 to 4 with the email `rehearsal-4@linehound.app` and the card `4000 0000 0000 0341` (Stripe's card that is accepted at checkout and refused on the first real charge). On the Billing page write down the date. In the Stripe dashboard (Test mode): **Subscriptions**, that subscription, **Actions**, **End trial now**. Stripe tries the charge and it is declined. Reload the Billing page. **Pass:** the date has not moved to a month out and the status reads "canceled" (this app shows every non-paying status that way). | `billing: invoice.payment_failed user=<16 hex> subscription='sub_...' attempt='1'`, then a `type='customer.subscription.updated'` line whose `paid_through` is unchanged. If `invoice.payment_failed` does not appear, step 1 did not save. |
| 9 | Optional, 1 minute, no card needed: in a private window, start a signup with `rehearsal-5@linehound.app`, and on Stripe's page use card `4000 0000 0000 0002` (declined on the spot). Stripe shows "card declined" and you stay on Stripe's page. | No `checkout.session.completed` for that signup and `/signup/complete` never answers 200. Nothing is granted. |

What you tell the parent after each step: "done", and for steps 4, 6 and 8 the
date the Billing page shows. The parent answers with the watcher's PASS or
NOT SEEN lines and fills in the REAL column below. The older run's other
steps (Resend a duplicate event, expiry, re-buy, reactivate, expired tester)
are deliberately not in this short run; they stay in "The staging run" further
down, and expiry needs a command to move the stored period end that is not
written yet.

## What is proven and how (updated 2026-10-04)

Three labels, kept apart:

- **MOCKED**: the real application code, in process, against a stand-in for
  Stripe with hand-signed webhooks. Proves our logic.
- **LOCAL**: a real uvicorn process on 127.0.0.1 (`scripts/rehearsal_local.py`),
  Stripe stand-in, hand-signed webhooks, its own log read by the watcher.
  Proves the log lines the watcher matches are the ones the server writes.
- **REAL**: observed on staging or in Stripe. Only what is listed as observed.

| Claim | MOCKED | LOCAL | REAL (staging / Stripe) |
|---|---|---|---|
| Duplicate event grants nothing twice | PASS `DuplicateWebhook` (2), `WebhookIdempotencyTests` (3), `DuplicatesAndDelays` (4), `RedeliveredCompletedMustNotResurrectAccess` (4) | not run | NOT RUN (step 6 of the detailed run: Resend) |
| Delayed / reordered events end the same | PASS `EveryOrderEndsTheSame` (3), `UpdateAndPaymentInEitherOrder` (3), `FailureAndPaymentInEitherOrder` (4), `APeriodAnnouncementAloneGrantsNothing` (5) | not run | NOT RUN |
| Failed payment never extends access | PASS `test_billing_failed_payment` (14), `..._review` (5) | invoice.payment_failed accepted and logged, 200 | NOT RUN (owner step 8) |
| Close the success page, come back | PASS `BuyAndComeBack` (4), `RecoveryWithoutTheTab` (4) | PASS second `/signup/complete` 200 after the payment | NOT RUN (owner step 5) |
| Expired tester converts on the same account | PASS `test_expired_tester_paid_path` (102), `test_expired_tester_review` (15), `test_tester_journey_e2e` (29) | not run | NOT RUN |
| Cancel keeps access to period end | PASS `CancelAndExpiry` (4), `CancelKeepsAccessUntilPeriodEndTests` (3) | PASS cancel 200 | NOT RUN (owner step 7) |
| Forged / unsigned webhook changes nothing | PASS `DuplicateWebhook.test_a_forged_or_unsigned_webhook_changes_nothing` | not run | not applicable; a POST to staging is not allowed from this work. A GET to `/billing/webhook` answers 405 (REAL, 2026-10-04) |
| Staging is in Stripe test mode | n/a | n/a | PASS `/health` says `checkout: provider stripe, mode test` (REAL, 2026-10-04 18:54Z) |
| Checkout and paid routes refuse anonymous callers | PASS `test_api_billing` | n/a | PASS anonymous `GET /ufc/fight-night` 401 and `GET /billing/status` 401 (REAL, 2026-10-04). `POST /billing/checkout` not probed (POST) |
| Staging has the right secrets set | n/a | n/a | PASS by name only: `BILLING_PROVIDER`, `STRIPE_API_KEY`, `STRIPE_BETA_PRICE_ID`, `STRIPE_WEBHOOK_SECRET`, `APP_ADMIN_TOKEN`, `ODDS_API_KEY` all Deployed (`fly secrets list`). Values never read |
| Which webhook event types have ever arrived on staging | n/a | n/a | UNKNOWN: `fly logs` keeps about 100 lines (from 18:48Z on 2026-10-04) and none were billing lines; the Stripe dashboard's Events list for the endpoint is the only history |
| The whole funnel script `scripts/funnel_smoke.sh` | n/a | BLOCKED on this Windows host: it hands `/tmp/...` paths to native Windows Python, so its signing and parsing steps cannot open their files (14 failures, all at that boundary, none in the app). `rehearsal_local.py` is the replacement here | n/a |
| The watcher reads the real log format | PASS `test_rehearsal_watch` (14) | PASS all 8 required steps against a real server's log | PASS for the parse only: 35 of 35 request-log lines in a live `fly logs --no-tail` capture (2026-10-04) were read; none were billing lines, so every step read NOT SEEN, correctly |

## What the watcher can and cannot see

Matched from lines the code emits today (`scripts/rehearsal_watch.py`):

| Step | Log line | Emitted today? |
|---|---|---|
| checkout requested | `method=POST path=/signup\|/billing/checkout\|/billing/tester-checkout status=200` | request line only. **No line says a Stripe session was created**, and the request is 200 even when billing answers "not configured" or "error" (the failure case logs `billing: checkout provider call failed`, which the watcher prints as a WARN). Weak by nature; `checkout.session.completed` is the proof |
| `checkout.session.completed` | `billing: webhook type='checkout.session.completed' event=... user=... paid_through=- status=...` | **added in this work** (before it, no line named the event) |
| `invoice.paid` | `billing: webhook type='invoice.paid' ...` | added in this work |
| access granted / paid_through set | the same webhook line with `paid_through='<date>'`, on `invoice.paid`, `customer.subscription.created` or `.updated` | added in this work. The date is a date, not a secret |
| paid gate opened | `method=GET path=/ufc/fight-night status=200 (or 503) ... user=<16 hex>` | yes, request log |
| return after closing the success page | second `method=GET path=/signup/complete status=200` after the payment | yes, request log |
| cancel | `method=POST path=/billing/cancel status=200 ... user=<16 hex>` | yes, request log |
| `invoice.payment_failed` | `billing: invoice.payment_failed user=... subscription=... attempt=...` | yes, existing line |
| paid gate refused after expiry (optional) | `method=GET path=/ufc/fight-night status=402 ... user=<16 hex>` | yes, request log |

Not visible in any log, so not claimed: the Stripe page itself, the card form,
which card was typed, and any event Stripe sent that the endpoint was not
subscribed to.

Warnings the watcher adds: the webhook answering 400 (signature) or 501
(`STRIPE_WEBHOOK_SECRET` unset), any 5xx on a `/billing` route, and any
`billing: ... provider call failed` line.

Dry run before the owner starts, no network beyond localhost:

```
python scripts/rehearsal_local.py
```

It prints PASS for each required step when the watcher and the server agree.

## Results (REAL = what a person or Stripe has actually been observed doing)

| Step | MOCKED | LOCAL | REAL |
|---|---|---|---|
| Webhook endpoint subscribed to `invoice.paid` and `invoice.payment_failed` | n/a | n/a | NOT RUN (owner step 1) |
| Sign-up on staging opens Stripe's page | PASS | PASS (signup 200) | NOT RUN (step 3) |
| Test card accepted; `checkout.session.completed` and `invoice.paid` arrive | PASS | PASS | NOT RUN (step 4) |
| Access granted (paid-through set) | PASS | PASS | NOT RUN (steps 4, 6) |
| Close success page, return | PASS | PASS | NOT RUN (step 5) |
| Paid gate opens for the token | PASS | PASS | NOT RUN (step 6) |
| Cancel keeps access | PASS | PASS | NOT RUN (step 7) |
| Decline: `invoice.payment_failed`, date unmoved | PASS | PASS (log line) | NOT RUN (step 8) |
| Staging in test mode | n/a | n/a | PASS (anonymous `/health`, 2026-10-04) |

Known gaps this work did not close: the two `expectedFailure` tests in
`test_tester_journey_e2e` (re-sending a lost tester token hands out another
week and does not revoke the lost one; admin extend, not billing) and the
`DeployDoesNotStrandOrImmortaliseExistingRows` owner decision below are still
open; billing is off in production, so neither blocks the staging run.

---

## Purchase rehearsal: one PASS/FAIL table (the detailed record)

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

| 14 | A failed payment (trial ends and the first charge fails, or a renewal fails) ends access at the end of the PAID period, not the new one; a successful retry restores it | yes | PASS `test_billing_failed_payment`, `test_billing_failed_payment_review`, and `test_billing_event_order` (every order of one renewal's events, duplicates, delays; see "Failed payment and event order") | NOT RUN (step 13) |
| 14a | A period announcement alone never grants an unpaid renewal; a paid invoice grants the period it bought; an older failure never undoes a later payment | yes | PASS `test_billing_event_order` (`APeriodAnnouncementAloneGrantsNothing`, `EveryOrderEndsTheSame`, `FailureAndPaymentInEitherOrder`) | NOT RUN (step 13; needs the two invoice events subscribed, see "Required setup") |

"PASS" in the first column means the named tests passed in the test run
recorded at the bottom of this file. It does not mean a human has seen it
work with Stripe.

## Required setup: the Stripe test webhook endpoint (owner, once)

Access now follows payment, and payment arrives as an invoice event. In the
Stripe dashboard, test mode, Developers, Webhooks, the staging endpoint
(`https://linehound-staging.fly.dev/billing/webhook`): the endpoint must be
sent **all six** of these events, not the four it was first set up with.

- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.paid` (required)
- `invoice.payment_failed` (required)

`invoice.payment_succeeded` is also understood if it is ticked; it says the
same as `invoice.paid`.

**If `invoice.paid` is not subscribed, the handler grants no renewal.** That is
the safe failure: nothing is given away. A first purchase still opens
(Stripe's `customer.subscription.created` for a new subscription reports
`active` only once its first invoice is paid, or `trialing` for a trial), and
then access simply ends at the end of that first period, because no paid
renewal ever arrives. **How you would see it:** on staging, the Billing page
date never moves past the first period and the card is refused once that date
passes (402, `subscription_expired`), even though Stripe shows the renewal
paid; in the Stripe webhook screen the endpoint's recent deliveries show no
`invoice.paid` rows. Fix: tick the event, then Resend the missed
`invoice.paid` events (Developers, Events, Resend); a resent event is safe,
it only ever extends access to the period it paid for.

**If `invoice.payment_failed` is not subscribed**, nothing about access
changes (a decline never changed access), but the
`billing: invoice.payment_failed` log line in step 13 never appears, which is
how you would see it.

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
    declining card start working. **Also record the order of events**, as a
    check on the assumptions the code now makes (it no longer depends on
    any particular order; see "Failed payment and event order"). From the
    Stripe test dashboard's event list, note the order and time of
    `customer.subscription.updated` (and the status and
    `current_period_end` it carries), `invoice.created`,
    `invoice.payment_failed` and `invoice.paid` for a renewal. The faithful
    run is a renewal under a Stripe test clock (create the customer under a
    test clock in the dashboard, subscribe it, advance the clock past the
    period): with a card that works, the Billing page date must move to the
    new period only after `invoice.paid`; with the declining card it must
    not move at all. Ending a trial early only approximates a renewal. Send
    me that list.

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
billing: invoice.payment_failed user=<16 hex> subscription='sub_...' attempt='1'
```

A second webhook line (added 2026-10-04) is written for every other processed
event, so the log names which event arrived. `paid_through` is the stored
date access runs to (`-` when none), `status` the stored status:

```
billing: webhook type='invoice.paid' event='evt_...' user=<16 hex or -> paid_through='2026-11-04T19:00:00+00:00' status='active'
```

| Case | In-process test | Staging step | Log lines to find |
|---|---|---|---|
| Closed success tab | `BuyAndComeBack.test_purchase_persists_and_access_survives_closing_the_page`, `test_the_buyer_who_closed_the_tab_before_the_token_arrived_can_come_back` | 3 and 4 | `method=POST path=/billing/webhook status=200 ... user=-` for the payment, then later `method=GET path=/signup/complete status=200 ... user=-` if the page is reopened, or `status=404` once the link has expired (the support re-issue path, step 5); the first signed-in request after returning shows `status=200` with a `user=` value |
| The same event delivered twice | `DuplicateWebhook.test_a_redelivered_payment_grants_nothing_twice` | 6 (Resend) | two identical `method=POST path=/billing/webhook status=200` lines (the resend answers 200 like the first delivery); the admin page still shows one user and one subscription |
| An active tester converting | `test_expired_tester_paid_path.PayingFromInsideTheWeekThroughTheBillingPage.test_an_invited_tester_who_pays_becomes_active`, `TesterCheckoutWithBillingOn.test_a_tester_still_inside_the_week_can_pay_early` | 11, done while the week is still running | `method=POST path=/billing/tester-checkout status=200 ... user=<hash>` (or `/billing/checkout` if started from the Billing page), then `method=POST path=/billing/webhook status=200 ... user=-` |
| An expired tester converting | `test_expired_tester_paid_path.PayingAsAFormerTester.test_one_user_active_with_the_subscription`, `TesterCheckoutWithBillingOn.test_an_expired_tester_token_starts_the_checkout_on_their_own_account` | 11 and 12 | `method=POST path=/billing/tester-checkout status=200 ... user=<hash>` (the token proves who they are, so the hash is present), the webhook line, and afterwards `method=GET path=/ufc/fight-night status=200 ... user=<same hash>`; the old week token still gets `status=401` |
| Cancellation | `CancelAndExpiry.test_cancel_stops_renewal_and_keeps_what_was_paid_for` | 7 | `method=POST path=/billing/cancel status=200 ... user=<hash>`; a following `method=GET path=/ufc/fight-night status=200 ... user=<same hash>` shows access continued; a `customer.subscription.updated` webhook line follows if Stripe sends one |
| Expiry | `CancelAndExpiry.test_after_the_paid_period_access_is_refused_with_a_reason` | 8 (simulated; the period end is moved by the one command) | `method=GET path=/ufc/fight-night status=402 ... user=<same hash>`, and `method=GET path=/billing/status status=200 ... user=<same hash>` (the billing page must still open) |
| Failed payment | `test_billing_failed_payment` (trial then first charge, renewal, retry succeeds, redelivery, stale events) | 13 | `billing: invoice.payment_failed user=<hash> subscription='sub_...' attempt='1'`, then `method=POST path=/billing/webhook status=200 ... user=-` for it and for the `customer.subscription.updated` that follows; the Billing page date must not move |
| Renewal paid / events out of order | `test_billing_event_order` (`EveryOrderEndsTheSame`, `UpdateAndPaymentInEitherOrder`, `DuplicatesAndDelays`) | 13 (test clock) | `method=POST path=/billing/webhook status=200 ... user=-` for each of `customer.subscription.updated` and `invoice.paid`; the Billing page date moves to the new period only once the `invoice.paid` line has appeared, whichever of the two arrived first |

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

## Failed payment and event order: what is true now

Stripe does not send events in order and sends some twice. The reviewer's
suspicion in the earlier version of this file (a renewal's new period end
arriving on an `active` update before the charge is attempted, so a decline
still yields a free period) was right to worry about, and the fix is no
longer a guard on that order: access now follows **payment**, whatever order
the events come in. Owner ruling, 2026-10-04. The rules, in plain words (the
same list is the "ACCESS POLICY" in `src/appstate/billing.py`):

1. **Access runs to one stored date, the paid-through date,** and to nothing
   else. After it the customer is not let in until a paid renewal arrives. The
   one exception is a short, bounded renewal grace (below).
2. **Only proof moves that date, and only later.** A paid invoice moves it to
   the end of the period that invoice bought. A free trial moves it to the
   trial's end and no further. A brand new subscription that Stripe reports
   as `active` is its first paid period (Stripe holds a new subscription as
   `incomplete` until the first invoice is paid).
3. **A new period that Stripe merely announces grants nothing.** The
   `customer.subscription.updated` that moves the period end forward at a
   renewal is only an announcement. A completed checkout page on its own also
   grants nothing: it carries no period, so the paid first invoice (a second
   later) is what opens access.
4. **A failed charge moves nothing in either direction.** What was paid for
   stays theirs to the paid-through date; the period Stripe tried to bill is
   never given.
5. **An older event never undoes a newer one.** Each event is compared with
   what is stored using its own Stripe timestamp: an older decline arriving
   after a later payment changes nothing; a duplicate changes nothing (it does
   not even rewrite the stored row); a late "paid" for a period already
   recorded changes nothing; events for an old subscription never touch a
   newer subscription's record. Where Stripe sent no timestamp the app falls
   back to arrival order for that comparison. Because proof only ever moves the
   date later, no arrival order can take away access a customer paid for or
   give access they did not.
6. **Cancellation is unchanged and now written down.** Cancelling stops
   renewal and keeps what was paid for. When Stripe says the subscription is
   deleted, access ends at the paid-through date, not earlier and not later.
7. **Nobody loses access on deploy.** A customer already recorded with a
   period end keeps that end as their paid-through date.

The Billing page and the cancel/reactivate answers now show the paid-through
date as "access until", not the period Stripe announced.

**Renewal grace (bounded, the owner can set it to 0).** Stripe creates a
renewal invoice at the period boundary and charges it about an hour later, so
with no grace every renewing customer would be refused for that hour each
month. `RENEWAL_GRACE_SECONDS` in `src/appstate/customers.py` is 6 hours (set
it to 0 for none). It applies only to a subscription that is still `active`
or `trialing`, is not scheduled to cancel, and has no failed payment or
deletion on record since the last payment: it keeps access that long past the
paid-through date and is not payment (the stored date does not move). A
scheduled cancel, `past_due`, `unpaid`, `incomplete` and a deleted subscription
get none, and a bare `active` event after a failure does not give it back;
only a new payment does. The worst a renewal that is never paid costs is six
hours.

**Other behaviour worth knowing.**

- A tester whose week is still open and who has started paying is not locked
  out in the moments between the checkout completing and the paid invoice (or
  trial event) being processed.
- The admin revenue page counts a row as paying or trialing only while it is
  actually entitled (paid through a future instant, plus the grace). Anything
  else that Stripe calls `active` is shown as `unpaid`, not as revenue.
- Payment evidence is clamped to 400 days past the event's own time, so an
  odd paid invoice line cannot make access permanent.
- A signed webhook body of an odd shape (not an object, ids that are objects,
  a time far out of range) is ignored and answered 200, never a 500.
- Cancel (`POST /billing/cancel`) reads the paid-through inside the same
  database lock it writes under, so a renewal that lands while Cancel is in
  flight is kept.

**Not covered:** a payment for a subscription this app has no customer record
for (it is dropped, as before, and Stripe is told 200); events that arrive
before the customer is linked to Stripe cannot happen on this path (the link
is made when checkout is opened).

## Found in review and fixed (2026-10-03)

The first version of the expired-tester fix let anyone who typed a tester's
email start a checkout on that tester's account and walk away with its
token. An independent review caught it before it was pushed. A tester's
checkout now starts only from their own access token
(`POST /billing/tester-checkout`); the signup form answers with a status and
nothing else. The same review found an older fault (row 5a) and it is fixed
too. Detail: `docs/audit/2026-10-03/EXPIRED_TESTER_PAID_PATH.md`.

## Open decisions before production billing

### Owner decisions: event-order review, left as they are

Both were found by the 2026-10-04 adversarial review and need your call, not a
code change:

- **Existing `active` rows with no recorded period end.** Before this change an
  `active` or `trialing` row with no cancel scheduled was entitled for ever,
  even with no period end at all. The migration gives such a row nothing
  (absent stays absent), so a customer in that state, if any exists, is
  refused until their next payment event. Billing is off in production, so
  the population may be empty. If it is not, you decide whether those rows get
  a bounded backfill (the review proposes: open on deploy for at most one
  period). Pinned as an expected failure in
  `tests/test_billing_event_order_review.py`
  (`test_an_active_row_with_no_end_is_open_on_deploy_for_at_most_one_period`).
- **Repeatable free trials.** Every checkout gets the 7-day trial, and a
  trial grants access through its end. A person who lets a subscription end
  and checks out again with a new subscription gets a new free trial each
  time; nothing here limits it. Related to the second free week for tester
  upgrades below. It needs a rule from you (one trial per person or per card)
  and a code change at checkout, not in the webhook. No test pins it yet.

### Other open decisions

- **A second free week.** Checkout gives every new buyer a 7-day Stripe
  trial. A former tester who upgrades would get that too: a second free
  week. Recommendation: no trial for anyone who has already had tester
  access. It needs a code change before billing opens (the trial length
  has to become part of the checkout's idempotency key, and the button
  label must stop promising a trial to someone who will not get one).
- **Two subscriptions for one person.** The table holds one row per
  person. An event for an old subscription no longer overwrites the newer
  record (2026-10-04), but only the newer subscription's own state is shown;
  a person who somehow ends up paying for two is not told. Rare; billing
  support would see it in Stripe.
- **A deep review before the switch.** This path touches sign-in and
  payments. Before production billing is turned on, run the cloud review
  (`/code-review ultra`) on the branch; it is yours to launch.

## Suite run behind the "In process" column

2026-10-03, local Windows run of every test module on the state that was
pushed: 9,969 tests, no failure outside the eight known Windows-only
identities (`docs/audit/2026-09-28/full_suite_integrated_1169b2d6_failures.txt`).
Linux CI result: see `docs/audit/2026-10-03/RELEASE.md`.

Row 14 (failed payment) was added after that run. It was checked with the
billing test modules only (365 tests, no failure): `test_billing_failed_payment`,
`test_billing_failed_payment_review`,
`test_billing_acceptance_path`, `test_billing_cancellation_policy`,
`test_appstate_billing`, `test_appstate_customers`,
`test_expired_tester_paid_path`, `test_expired_tester_review`,
`test_api_billing`, `test_api_signup`, `test_checkout_copy_states`,
`test_checkout_delivery`, `test_api_boundary`. The full suite has not been
re-run on the change.

Rows 14 and 14a (event order) were checked with those modules plus
`test_billing_event_order` and `test_appstate_sqlite_pragmas` on 2026-10-04.
The same change turned up fixtures elsewhere that treated an `active` row with
no payment on record as entitled for ever; they are named in the commit that
changed the rule.
