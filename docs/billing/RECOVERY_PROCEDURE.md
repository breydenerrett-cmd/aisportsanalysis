# Getting a locked-out customer back in: support recovery, not self-service

Written 2026-10-05 (W02/W03). There is no email sender, so the access token
cannot be mailed automatically. A customer who has lost it is recovered **by
hand, by you**, and the customer is told so. Never describe this as "reset my
password". Every "support re-issue" in the table below means the procedure
under it, and its first step is a confirming reply from the account's mailbox:
nothing is revoked or issued before that.

## The six cases

| # | Case | What the customer sees | What happens next |
|---|------|------------------------|-------------------|
| 1 | Same browser, token still stored | `#/signup/complete` (or any page) asks the server about the stored token: "You're signed in." with the link to tonight's card. | Nothing for support. |
| 2 | Paid, closed the tab before the token was shown | The Stripe return link (it carries `session_id`) still hands the token over for 72 hours after payment, and starts a 10-minute re-read window on first read. Without that link, `#/signup/complete` says "You're not signed in here. Your purchase or trial is not lost." with Sign in and Get help. | Link inside 72 h: the customer does it alone. Otherwise support re-issue. |
| 3 | Back after the 10-minute re-read window | The session id is dead (the server wiped the token). A device that already holds a token is checked and signed in; a device without one gets the signed-out state above. | Support re-issue (after the confirming reply) for the device without one. |
| 4 | Another device or browser | The sign-in page wants the token shown once on the success page ("save this"). If it was not saved there is nothing to paste. | Support re-issue. |
| 5 | Tester whose week ended, converting | "Your early access ended on <date>." and, when checkout is on, the sign-in page's button (it needs the stored token); checkout off: "Reply to Brey". | Token lost: support re-issue (the new token ends at the old window end, so it opens nothing but still starts the conversion). Do NOT use "Extend 7 days": that gives a free week and needs feedback. |
| 6 | Revoked or unknown token (after a re-issue, a suspension, a typo) | The server answers 401, the page removes the saved token and shows the signed-out state: not lost, Sign in, Get help. If the server cannot be reached the token is kept and the page offers "Try again". | Only if they ask: support re-issue. |

## The procedure (every step is mandatory)

1. **Ownership is proven by a reply FROM the mailbox on the account, and
   nothing before it.** The Get help form proves nothing: its email field is
   typed and unverified (web/js/support.js), so anyone can type a victim's
   address and send "Locked out". A request, from the form, a chat, a DM, an
   email that merely names the address, a checkout id, a name or a screenshot,
   is only a request. On ANY request, first write to the address on the account
   (look it up yourself; do not use an address the requester gives you) asking
   them to confirm by replying. **Do not re-issue and do not revoke anything
   until a reply arrives from that mailbox confirming the request.** No reply:
   nothing happens and the customer's current token keeps working, so a stranger
   cannot lock a paying customer out. A request in chat or DM gets one answer:
   "write to us with the form, we will email the address on the account to
   confirm". The customer is told this on the support page (confirmation email,
   reply from the account's address).
2. **Re-issue, only after the confirming reply.** `POST /admin/users/reissue` with `X-Admin-Token` and
   `{"email": "<account address>", "reason": "<what you verified, ticket id>"}`.
   The reason is required (say what was verified: "reply from the account
   mailbox 2026-10-05, ticket 41"), is logged, and is refused if it looks like it
   contains a token or a checkout session id. An id that is not an account
   (out of range, not a number) gets the same 409 as an unknown one.
3. **One refusal.** `409 reissue_refused` covers no account, a waitlisted
   signup, a lapsed subscriber, a suspended user and anything else that is not
   a live subscriber or tester. Do not say which; do not work around it.
4. **Send the new token to the account address only**, as a reply in the thread
   the mailbox confirmed in. Never show it in chat, DM, a ticket or a log. It is
   returned once and stored only as a hash.
5. **The replaced token stops working** in the same transaction (every earlier
   token of that user). The raw checkout activation token is wiped in the same
   transaction and `GET /signup/complete` also refuses any token that no longer
   authenticates, so the Stripe return link cannot hand back the old one. The tester window
   and `paid_through` are not touched; a re-issue never extends anything.
6. **Audit.** Each issue is one `support_token_reissued` row in the events
   table (`properties`: `reason`, `kind`, `revoked_tokens`; the user is a hash,
   there is no token or email), written in the same transaction as the revoke
   and the new token: if either fails (503) neither stays, and no `reissue` row
   exists for a re-issue that did not happen. A failed attempt is recorded as
   `action: reissue_failed`.

## Open decisions for the owner

* **A lapsed subscriber who lost the token is refused** (same stance as the
  older `/admin/users/token`), so they cannot reach Billing to renew. Allowing a
  token that opens only `/billing/*` for them is a one-line eligibility change
  in `api/admin.py` `_reissue_plan`; it is your call.
* **Self-service on another device needs an email sender.** Proposal, not
  built: a transactional email provider (the free tiers of the common ones
  cover a few thousand messages a month; budget under about $15 a month as an
  upper bound, to be confirmed with the provider) plus SPF/DKIM on the sending
  domain, and one route that mails a single-use, 15-minute sign-in link to the
  address on the account (the answer is always "if that address has an account
  we sent a link", so it reveals nothing). That makes the mailbox the proof
  without a person in the loop, and removes steps 1 to 4 above. It is worth
  building when recoveries pass a few a week, or the first paying customer
  writes in from a second device.
