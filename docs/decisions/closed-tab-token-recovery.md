# Closed-tab token recovery (decision for the owner)
Status: PROPOSED, not applied (review 2026-10-04). Patch:
`closed-tab-token-recovery.patch` (web/js/signup.js only).

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
- Gap: reopening from history lands on the scrubbed URL and the "No token
  was included" screen (~455-460); the 10-minute window is unreachable. The
  same browser profile is already signed in via `setToken`; any other device
  needs support (`POST /admin/users/token`).
## Option A: keep as is

- Buyer: closes the tab early, sees "Check your link", contacts support (no
  email sender exists). A same-device buyer is already signed in.
- Security: the session id and token never sit in browser history. The URL
  is clean the moment the token is on screen.

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
  left in history is dead. LIMITATION: if the tab closes before the timer
  fires, the history entry keeps the session id (inert after the window).
  B adds no server exposure; it makes the id easier to find on that device.
## Recommendation

B, if the owner accepts the shared-computer exposure above: buyers are on
phones and personal laptops, and A locks a paying customer out with no email
fallback. For zero history exposure, stay on A and add the recovery step to
the support runbook.
## Tests with the change applied

274 tests OK (checkout_to_card_web, signup_complete_polling, api_signup,
checkout_copy_states, web_structure, web_register_sweep,
expired_tester_paid_path, billing_acceptance_path). A bare `setTimeout` hung
the node harnesses (60 s timeouts); the patch `unref`s the timer (Node only).
Loosest pin: `test_checkout_to_card_web.py::test_the_session_id_is_removed_from_the_address_bar_after_use`
only asserts `replaceState` exists (true under B). B needs new tests for the
timer and the two immediate drops.
