# Expired tester to paying subscriber, on the same account (2026-10-03)

Owner's target: expired tester sees a clear upgrade state, can start checkout, pays, the
paid entitlement replaces the expired trial, the history and the account are preserved, no
duplicate account, no permanent "invited" dead end. Stripe test mode only; production billing
stays off.

This note describes the FINAL behaviour. The first version (commit 40a9974c) opened the
checkout from the unauthenticated signup form; an adversarial review (finding D1) showed that
was an account takeover, and it was replaced by the token route below.

## What it was

- `testers.grant_tester` leaves a person `invited` with a 7 day token and a row in `testers`.
- When the token expired, `POST /signup` for that email hit the `invited` line in
  `api/signup.py::_respond_for` and returned `{"status": "invited"}`. No checkout was ever
  started, from any billing state. The page said "That email already has an account".
- The expired token got the same 401 (`error: "unauthorized"`) as a mistyped one, so the
  sign-in page could not tell the person their access had ended.
- A tester who paid through the billing page (valid token, `POST /billing/checkout`) stayed
  `invited` after the webhook, because `_activate_signup` only moved `pending_payment` to
  `active`.

## What it is now

A tester is a user with a row in `src/appstate/testers.py`'s `testers` table (never deleted).
`src/appstate/tester_upgrade.py` answers three questions from existing tables, no schema change:

- `upgrade_state(user)`: the label the signup form may show for a tester's email,
  `tester_expired` or `tester_active`. It is a label, not a permission.
- `tester_for_token(token)`: may this bearer token start a checkout for a tester's own
  account? A real, unrevoked token of a non-suspended tester with no current subscription
  entitlement, expired or not. The lookup is by the token's hash (the same join
  `expired_token_window` uses; one helper, `_tester_token_row`).
- `expired_token_window(token)`: whether a bearer token is an expired tester token, and when
  that person's access ended (the newest window end, so an extended tester gets the right date).

### Why the email cannot start a checkout (review D1)

`POST /signup` has no credential. A checkout is bound to a user id, and whoever completes it is
handed a long-lived token for that account by `GET /signup/complete?session_id=...`. With the
first version, a stranger who knew only a tester's email (or a lapsed subscriber's) could start
that checkout, complete it on a free trial that charges nothing, and receive a 366 day token for
the tester's account: saved bets readable and deletable. One unauthenticated POST also moved the
tester to `pending_payment` and created a Stripe customer for them. So an email address may
label a tester and nothing else; the proof of who is paying is holding the token.

### `POST /signup` for an existing email

For an email that belongs to a tester (a row in `testers`: expired or not, lapsed subscriber or
not) the answer is the same with billing on and with billing off, and nothing is started or
changed: no checkout, no Stripe customer, no status write, no event, and no first-touch
attribution stored from the request (the activation report excludes testers whose attribution is
`internal`, so a stranger must not be able to fill that in).

| Who | Answer |
|---|---|
| Tester, window ended, not currently paying | `{"user_id", "status": "tester_expired"}` |
| Tester, inside the window, not currently paying | `{"user_id", "status": "tester_active"}` |
| Lapsed former-tester subscriber | `{"user_id", "status": "tester_expired"}` (status untouched, usually `active`) |
| Tester who is currently paying | `{"user_id", "status": "active"}` |
| Suspended tester | `{"user_id", "status": "suspended"}` |
| Comped `invited`, not a tester | `{"user_id", "status": "invited"}` (unchanged) |
| `active` non-tester, `suspended` non-tester | unchanged |

There is no `expires_at` and no other date in these answers: an end date next to an email
address tells anyone who types that address when that person's access ends. `user_id` is kept
because every other existing-account answer carries it (the page does not read it). For a new
email, and for `pending_payment` / `waitlisted` non-testers, nothing changed (`checkout`,
`waitlisted`, `error`).

### `POST /billing/tester-checkout` (the only door to a tester's checkout)

`Authorization: Bearer <tester token>`, no body. The token may be expired (the week ended) or
still inside its window (paying early). Dependency: `api/auth.py::get_tester_checkout_user`,
which uses `tester_upgrade.tester_for_token`. It does not touch `get_current_user`: every
ordinary route still refuses an expired token, with the same 401 as before, and this route does
not mark a token as used.

| Case | Response |
|---|---|
| Billing on | `200 {"user_id", "checkout": {"status": "redirect", "checkout_url"}}`, exactly a new buyer's answer. `invited` becomes `pending_payment` (an `active` lapsed subscriber keeps `active`); `checkout_started` is recorded. |
| Billing on, unable to take a payment | `200 {"user_id", "status": "error", "message": "payments are not available right now; nothing has been charged"}`; nothing moved. |
| Billing on, Stripe call failed | `200 {"user_id", "status": "error", "message": "checkout could not be started; try again shortly"}`; the raw Stripe body never reaches the caller. |
| Billing off | `200 {"status": "not_configured", "message": "paid plans are not open yet; nothing has been changed"}`; no status change, no Stripe call, no event. |
| Unknown, malformed or missing token; revoked token; a non-tester's token (expired or not); a suspended tester's token; a tester a subscription currently entitles | `401 {"detail": {"error": "unauthorized", "message": "missing, invalid, expired, or revoked token"}}`, the one body every bad token gets. Nothing is written and Stripe is not called. |
| More than 10 in an hour for one tester | `429 {"detail": {"error": "rate_limited", "retry_after"}}` |

Rate limit: `TESTER_CHECKOUT_RATE_LIMIT_PER_HOUR = 10`, keyed on the authenticated tester and
counted only after the token has been verified, so a made-up token costs one hash lookup and no
Stripe call. It is built from the same `ratelimit.limiter_dependency` factory as the other
billing routes; `api/billing.py`'s own limiter does not fit because its dependency is
`get_current_user`, which refuses the expired token this route exists for. One tester has one
Stripe customer and one idempotent checkout session, so the route cannot create Stripe objects
for anyone but the token's own account.

The route lives in `api/signup.py` next to the checkout helper it shares (`_start_checkout`,
used by the signup form for non-testers and by this route).

### Sign-in

Presenting an expired tester token to any authed route gives `401` with
`{"error": "tester_access_expired", "message": "...", "expires_at": "<iso>"}`. The caller
holds the token, so the date is theirs to read. Every other failing token (unknown, malformed,
revoked, expired invite of a non-tester, a tester still holding a newer extension token, a
suspended user, a user who is currently paying) keeps the generic
`401 {"error": "unauthorized", ...}`. No email is involved, so it does not become a way to ask
whether an address is a tester.

### After payment

`checkout.session.completed` on a former tester's user id: one user row, `active` (an
`invited` tester is moved to `active` by `_activate_signup`; an `invited` non-tester is not),
the subscription recorded, a 366 day token minted and read through `GET /signup/complete`
exactly as for a new buyer. The `testers` row, the old token, saved bets and events are
untouched. `require_paid_access` never looks at the tester window: a user with a subscription
record is gated by `customers.has_paid_access` alone.

A redelivered `checkout.session.completed` for a subscription already recorded as ended
(`customer.subscription.deleted` applied first) no longer rewrites it to `active` (review D3):
Stripe retries for days and does not order events, and the rewrite had no `cancel_at`, so paid
access never ended. A genuinely new checkout is a new Stripe subscription id and activates
normally.

### Admin

`extend_tester` refuses a tester who has a subscription record, with the code `grant_tester`
uses (`has_subscription`, HTTP 409 from `POST /admin/testers/extend`, shown by the admin page),
before anything is written (review D4). Before this, the extension succeeded and the fresh
token then got 402 on every paid page because a subscription record exists.

### Pages

- `web/js/signin.js`: with a stored token it asks `GET /billing/status`. On
  `tester_access_expired` it shows "Your early access ended on <date>." and then, if `/meta`
  says checkout is on, a button (label `upgradeLabel`, the signup form's own label) that sends
  the stored token to `POST /billing/tester-checkout` and follows the redirect. If `/meta` says
  checkout is off or unavailable: "Paid plans are not open yet. Reply to Brey if you want to
  keep going." and no button. If `/meta` could not be read: only "Reply to Brey if you want to
  keep going." (the page does not know whether plans are open, so it does not say they are
  not). Overlapping checks (a double Save, a new token saved over an ended one, Clear) are
  ordered by a generation counter checked after each await (review D5).
- `web/js/signup.js`: `tester_expired` / `tester_active` say, in plain words, that the email
  already has early access, to sign in with the access token (for an ended one, that the
  sign-in page is where to continue), and to reply to Brey if the token is lost, with a link to
  `#/signin`. No date, no offer wording, checkout on or off.
- All wording and the label are in `web/js/checkout.js`.

## What was not changed

- Production billing: nothing is switched on. Behaviour with billing off is identical except the
  two signup statuses, the sign-in message and the new route's honest answer.
- No schema change, no deleted rows, no change to `grant_tester`, `require_paid_access`, the
  Stripe provider, the webhook signature check or `users_store.authenticate`.
- The Stripe trial: a former tester gets the same checkout as a new buyer, including
  `STRIPE_TRIAL_DAYS` (default 7). Whether a person who already had a free week should get
  another is an owner decision; `STRIPE_TRIAL_DAYS=0` removes it for everyone.
- The shared sign-in gate in `web/js/dom.js` (shown when an expired token hits a board page) is
  unchanged: it still says "Sign in to continue" and links to sign-in, where the ended state is
  shown. The 401 detail is visible in its technical-detail disclosure.
- `card_v2.py`, `best_bets_card.py`, `card_ledger.py`, `ufc_card.py`, `.github/`, the admin
  testers page and events.

## Known limits

- An expired tester token is now enough to start a checkout for that account, and whoever
  completes it receives a subscriber token. A token that leaked after it expired therefore
  still has that one use. Support's token re-issue revokes older tokens, which closes it.
- A `checkout.session.completed` event for an OLD subscription id redelivered after a NEWER
  subscription was recorded for the same user still overwrites the record (the table holds one
  row per user). Only the same-subscription case in D3 is guarded.
- A first-delivery `customer.subscription.created` with a non-paying status (Stripe
  `incomplete`, recorded as `canceled`) followed by `checkout.session.completed` leaves the
  record `canceled` until the next `customer.subscription.updated`, instead of `active`.
  Checkout only completes after payment, so this ordering is not expected.

## Tests

- `tests/test_expired_tester_paid_path.py`: the signup answers for a tester's email (billing on
  and off, nothing written, no Stripe call, no date); the token route (accepted, refused,
  billing off, misconfigured, Stripe failure, the 401 body, rate limit over ASGI); paying on the
  same account; entitlement; the pages under node.
- `tests/test_expired_tester_review.py`: the review's regression tests, now ordinary tests
  (D1 stranger, D3 redelivery, D4 extend, D5 sign-in race), plus the abandoned-checkout case.
- `tests/test_tester_access.py`: an expired tester token is still a 401, now with
  `tester_access_expired`; a wrong token still gets `unauthorized`.
