# Expired tester to paying subscriber, on the same account (2026-10-03)

Owner's target: expired tester sees a clear upgrade state, can start checkout, pays, the
paid entitlement replaces the expired trial, the history and the account are preserved, no
duplicate account, no permanent "invited" dead end. Stripe test mode only; production billing
stays off.

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
`src/appstate/tester_upgrade.py` decides two things from existing tables, no schema change:

- `upgrade_state(user)`: a tester who has no current subscription entitlement
  (`customers.has_paid_access` false) may start checkout from the signup form, on the same
  user id. Suspended accounts and currently paying users are excluded. A tester whose
  subscription lapsed qualifies again (the come-back path).
- `expired_token_window(token)`: whether a bearer token is an expired tester token, and when
  that person's access ended (the newest window end, so an extended tester gets the right date).

### `POST /signup` for an existing email

| Who | Billing on | Billing off |
|---|---|---|
| Tester, window ended, not paying | `{"user_id", "checkout": {"status": "redirect", "checkout_url"}}`; `invited` becomes `pending_payment` | `{"user_id", "status": "tester_expired", "expires_at"}` |
| Tester, inside the window, not paying | same checkout (pay early) | `{"user_id", "status": "tester_active", "expires_at"}` |
| Tester who is currently paying | `{"user_id", "status": "active"}` (no second checkout) | same |
| Comped `invited`, not a tester | `{"user_id", "status": "invited"}` (unchanged) | unchanged |
| `active` non-tester, `suspended` | unchanged | unchanged |
| Billing on but unable to take a payment | the `error` answer a new buyer gets; status untouched | n/a |

For a new email, and for `pending_payment` / `waitlisted` non-testers, nothing changed
(`checkout`, `waitlisted`, `error`). Tester statuses are never rewritten by the off-state
answer (a tester parked at `pending_payment` is no longer waitlisted).

### Sign-in

Presenting an expired tester token to any authed route gives `401` with
`{"error": "tester_access_expired", "message": "...", "expires_at": "<iso>"}`. Every other
failing token (unknown, malformed, revoked, expired invite of a non-tester, a tester still
holding a newer extension token, a suspended user, a user who is currently paying) keeps the
generic `401 {"error": "unauthorized", ...}`. No email is involved, so it does not become a way
to ask whether an address is a tester.

### After payment

`checkout.session.completed` on a former tester's user id: one user row, `active` (an
`invited` tester is now moved to `active` by `_activate_signup`; an `invited` non-tester is
not), the subscription recorded, a 366 day token minted and read through
`GET /signup/complete` exactly as for a new buyer. The `testers` row, the old token, saved bets
and events are untouched. `require_paid_access` never looks at the tester window: a user with a
subscription record is gated by `customers.has_paid_access` alone.

### Pages

- `web/js/signin.js`: with a stored token it asks `GET /billing/status`. On
  `tester_access_expired` it shows "Your early access ended on <date>." and, checkout on, a
  button (label `upgradeLabel`, which is the signup form's own label) to `#/signup`, whose email
  step starts the checkout for that account; checkout off, "Paid plans are not open yet. Reply
  to Brey if you want to keep going." and no button.
- `web/js/signup.js`: `tester_expired` / `tester_active` render the same sentence plus the same
  next step.
- All wording and the label are in `web/js/checkout.js`.

## What was not changed

- Production billing: nothing is switched on. Behaviour with billing off is identical except the
  two new signup statuses and the sign-in message.
- No schema change, no deleted rows, no change to `grant_tester`, `extend_tester`, the admin
  routes, `require_paid_access`, the Stripe provider or the webhook signature check.
- The Stripe trial: a former tester gets the same checkout as a new buyer, including
  `STRIPE_TRIAL_DAYS` (default 7). Whether a person who already had a free week should get
  another is an owner decision; `STRIPE_TRIAL_DAYS=0` removes it for everyone.
- The shared sign-in gate in `web/js/dom.js` (shown when an expired token hits a board page) is
  unchanged: it still says "Sign in to continue" and links to sign-in, where the ended state is
  shown. The 401 detail is visible in its technical-detail disclosure.
- `card_v2.py`, `best_bets_card.py`, `card_ledger.py`, `ufc_card.py`, `.github/`, the admin
  testers page and events.

## Tests

`tests/test_expired_tester_paid_path.py` (new), plus one updated assertion in
`tests/test_tester_access.py` (an expired tester token is still a 401, now with
`tester_access_expired`; a wrong token still gets `unauthorized`).
