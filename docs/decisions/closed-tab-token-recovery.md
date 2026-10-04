# Closed-tab token recovery (decision for the owner)

Status: PROPOSED, not applied. Review finding 2026-10-04. The patch is
`docs/decisions/closed-tab-token-recovery.patch` (web/js/signup.js only).

## Behaviour today

- Stripe sends the buyer to `index.html#/signup/complete?session_id=...`.
- `web/js/signup.js` polls `GET /signup/complete` (`pollSignupToken`, ~303),
  stores the token with `setToken`, then calls `history.replaceState` to drop
  the session id from the address (~408-413).
- Server: `api/signup.py` ~489-507 passes `ACTIVATION_REREAD_WINDOW` to
  `customers.take_activation_token` (`src/appstate/customers.py` 670, 716-780).
  The first read stamps `retrieved_at`; the same session id returns the same
  token for 10 minutes from that FIRST read (re-reads never extend it), then
  the raw token is wiped and every answer is 404. The only check is the
  session id: no cookie, no IP binding. 30 reads/min/IP rate limit.
- Gap: a buyer who closes the tab and reopens it from history lands on the
  scrubbed URL, hits the "No token was included" screen (~455-460), and the
  10-minute window is unreachable. The device is already signed in via
  `setToken`, but only if they reopen on the same browser profile; any other
  device gets support recovery (`POST /admin/users/token`).

## Option A: keep as is

- Buyer: closes the tab early, sees "Check your link", contacts support. A
  same-device buyer is still signed in and can open tonight's card directly.
- Security: the session id and token never sit in browser history. The URL
  is clean the moment the token is on screen.
- Cost: support load; the support path is manual and has no email sender.

## Option B: keep the session id until the window ends, then drop it

Patch: the session id stays in the address for `SIGNUP_SESSION_ID_LIFETIME_MS`
(10 min, mirrors the server) via `setTimeout`; it is also dropped immediately
on the "already signed in" and server-refusal screens.
- Buyer: reopening from history inside 10 minutes shows the token again and
  signs the device in. After 10 minutes: "already signed in" (same device) or
  "Almost there" with the API error (other device), as the reload case today.
- Security: during up to 10 minutes after first read, anyone who can see the
  session id (history entry or open tab on a shared computer, screen share,
  copied URL) can call `GET /signup/complete?session_id=...` and read the raw
  token, which is a 366-day subscriber login. The server cannot tell them apart
  from the buyer. After the window the server wipes the token, so a session id
  left in history is dead. LIMITATION: if the tab is closed before the timer
  fires, the history entry keeps the session id forever (harmless once the
  server window closes, but it is in history). Exposure is the same 10-minute
  window the server already grants to anyone holding the id; B just makes the
  id easier to find on that device.

## Recommendation

B, but only if the owner accepts the shared-computer exposure above; buyers
here are on phones and personal laptops and the cost of A is a paying customer
locked out with no email fallback. If the owner prefers zero history exposure,
stay on A and put the recovery step into the support runbook.

## Tests with the change applied

With the patch applied: 274 tests, OK (test_checkout_to_card_web,
test_signup_complete_polling, test_api_signup, test_checkout_copy_states,
test_web_structure, test_web_register_sweep, test_expired_tester_paid_path,
test_billing_acceptance_path). Lesson: a bare 10-minute `setTimeout` kept the
node harnesses in test_checkout_copy_states alive until their 60 s timeout
(4 errors); the patch `unref`s the timer when it exists (Node only). One test pins the current
behaviour only loosely: `tests/test_checkout_to_card_web.py`
`test_the_session_id_is_removed_from_the_address_bar_after_use` asserts the
string `replaceState` exists (still true under B). No test asserts the URL is
scrubbed immediately. Adopting B should add a test for the timer and the two
immediate drops.
