# Getting a locked-out customer back in: support recovery, not self-service

Written 2026-10-05 (W02/W03). There is no email sender, so the access token
cannot be mailed automatically. A customer who has lost it is recovered **by
hand, by you**, and the customer is told so. Never describe this as "reset my
password".

## The six cases

| # | Case | What the customer sees | What happens next |
|---|------|------------------------|-------------------|
| 1 | Same browser, token still stored | `#/signup/complete` (or any page) asks the server about the stored token: "You're signed in." with the link to tonight's card. | Nothing for support. |
| 2 | Paid, closed the tab before the token was shown | The Stripe return link (it carries `session_id`) still hands the token over for 72 hours after payment, and starts a 10-minute re-read window on first read. Without that link, `#/signup/complete` says "You're not signed in here. Your purchase or trial is not lost." with Sign in and Get help. | Link inside 72 h: the customer does it alone. Otherwise support re-issue. |
| 3 | Back after the 10-minute re-read window | The session id is dead (the server wiped the token). A device that already holds a token is checked and signed in; a device without one gets the signed-out state above. | Support re-issue for the device without one. |
| 4 | Another device or browser | The sign-in page wants the token shown once on the success page ("save this"). If it was not saved there is nothing to paste. | Support re-issue. |
| 5 | Tester whose week ended, converting | "Your early access ended on <date>." and, when checkout is on, the sign-in page's button (it needs the stored token); checkout off: "Reply to Brey". | Token lost: support re-issue (the new token ends at the old window end, so it opens nothing but still starts the conversion). Do NOT use "Extend 7 days": that gives a free week and needs feedback. |
| 6 | Revoked or unknown token (after a re-issue, a suspension, a typo) | The server answers 401, the page removes the saved token and shows the signed-out state: not lost, Sign in, Get help. If the server cannot be reached the token is kept and the page offers "Try again". | Only if they ask: support re-issue. |

## The procedure (every step is mandatory)

1. **Ownership is the mailbox.** The request counts only if it arrives from the
   address on the account (the Get help form, or a reply in a thread you
   started). Knowing an email address, a Stripe checkout id, a name or a
   screenshot proves nothing. A request in chat or DM gets one answer: "write
   to us from the email on the account".
2. **Re-issue.** `POST /admin/users/reissue` with `X-Admin-Token` and
   `{"email": "<account address>", "reason": "<what you verified, ticket id>"}`.
   The reason is required, is logged, and must not contain a token.
3. **One refusal.** `409 reissue_refused` covers no account, a waitlisted
   signup, a lapsed subscriber, a suspended user and anything else that is not
   a live subscriber or tester. Do not say which; do not work around it.
4. **Send the new token to the account address only**, by replying to the
   mailbox that asked. Never show it in chat, DM, a ticket or a log. It is
   returned once and stored only as a hash.
5. **The replaced token stops working** in the same transaction (every earlier
   token of that user, including an unread activation token). The tester window
   and `paid_through` are not touched; a re-issue never extends anything.
6. **Audit.** Each issue is one `support_token_reissued` row in the events
   table (`properties`: `reason`, `kind`, `revoked_tokens`; the user is a hash,
   there is no token or email). It is written first: if the log cannot be
   written (503) nothing is issued.

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
