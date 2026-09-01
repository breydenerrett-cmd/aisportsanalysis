# Onboarding & Support Playbook (private alpha)

Working brand: Linehound (temporary, pending trademark/domain clearance —
Brey 2026-09-01).

Operational reference for Brey, the one person running support and
onboarding for this product. Backing code: `src/appstate/support.py`,
`api/support.py`, `src/appstate/onboarding.py`, `api/onboarding.py`.

## 1. Invite-to-active flow

1. **Brey mints the invite.** `POST /admin/invites` (`api/auth.py`, gated by
   `APP_ADMIN_TOKEN`) with the person's email. This creates the user
   (status `invited`) if they don't exist yet, and returns a **raw** bearer
   token — the one and only time it is ever visible (only its sha256 hash
   is stored; see `src/appstate/users.py`'s module docstring). Token
   expires in 14 days if unused.
2. **Brey sends the invite email by hand** (no automated invite-email
   sender exists yet — that is a real gap, not an oversight). Body copy:
   `docs/CONTENT_LANDING.md` section 6 ("Beta invite email — DRAFT") has
   the approved product framing (no win-probability claim, the tested-and-
   published-losers pitch, the beta disclaimer) — use that copy as-is for
   everything except the access mechanism itself.

   **Gap between that draft and how access actually works today:** the
   content draft's "[Get started button → app link]" assumes a link-based
   flow; the real mechanism is the raw bearer token from step 1, pasted
   into the app's token field (`web/index.html`'s token-entry form). Until
   the content draft is updated for that (or Clerk, docs/LAUNCH_DECISIONS.md
   Decision 1, replaces invite tokens entirely), replace that one line with
   the token itself:

   > Your access token: `<TOKEN>`
   >
   > Paste it into the app when it asks for your access token. It's good
   > for 14 days if you haven't used it yet — after that, just reply here
   > and I'll send a new one.

   The email must still carry: the raw token, what the product is, and a
   support contact (see section 3) — the content draft covers the second
   two.
3. **User redeems the token.** First authenticated request
   (`api.auth.get_current_user`) marks `first_used_at` and fires
   `events.INVITE_REDEEMED` exactly once — this is `onboarding_state`'s
   `token_redeemed` step (`src/appstate/onboarding.py`).
4. **User works through the first-session checklist** (section 2).
5. **Brey watches `GET /admin/overview`** for invite backlog and event
   counts, and `GET /onboarding` (once a UI exists) per-user for where
   someone is stuck.

## 1b. Self-serve signup flow (paying beta customers)

Section 1 covers the admin-minted invite path (personal invites, closed
beta). Paid beta also has a second, self-serve entry point that does not
go through Brey at all until something breaks: `POST /signup` and `GET
/signup/complete` (`api/signup.py`, `src/appstate/customers.py`). This is
the path `docs/FIRST_CUSTOMER_PLAYBOOK.md` §1's Day-0 dry run walks and the
one a real stranger uses, end to end:

1. **Landing → signup.** User submits their email (`POST /signup`, public,
   rate-limited 10/hour/IP). A first-time email either gets a Stripe
   Checkout URL back (`status: "redirect"`, `checkout_url`) if billing is
   configured, or a waitlisted/`not_configured` response if it isn't yet.
   Repeat signups for a `pending_payment`/`waitlisted` email re-check
   today's billing config rather than erroring (`api/signup.py`'s own
   docstring, "IDEMPOTENT PER EMAIL") — an `active`, `suspended`, or admin-
   `invited` account is left alone; signup never re-litigates a state a
   human process already set.
2. **Checkout.** Stripe-hosted, $19.99/mo Founding Access (or the $239/yr
   annual) — `design/linehound-v1/HANDOFF_README.md`'s frozen commercial
   facts. A real card at this step is the actual moment of "did a stranger
   pay," not the dry-run test card.
3. **Webhook → activation token.** Stripe's webhook confirms payment;
   `src/appstate/billing.apply_stripe_webhook_event` mints a **one-time**
   activation token server-side. The browser lands back on `GET
   /signup/complete?session_id=<stripe session id>` (the success-page
   redirect), which hands that token back exactly once — a second call for
   the same session returns nothing new (`src/appstate/customers.py`'s
   `take_activation_token` docstring: "already used," "unknown," and
   "never completed payment" are deliberately indistinguishable from
   outside, for the same reason a login form doesn't say which part was
   wrong).
4. **Token → app.** Same paste-into-token-field mechanic as the invite
   path (`web/index.html`'s token-entry form). From here the flow rejoins
   section 2's first-session checklist exactly — `token_redeemed` fires the
   same way regardless of which door the user came through.

**Where this can fail, and what to say:**

| Failure point | What the user sees / reports | What to say |
|---|---|---|
| Signup submitted, no checkout link | `status: "not_configured"` or `"waitlisted"` response | "Billing isn't live for your signup yet — I'll follow up personally the moment it is." (Should not happen once Stripe is configured for real; if it does post-launch, that's P0 — see section 4.) |
| Paid, closed the success tab before copying the token | User has a Stripe receipt but no token | `GET /signup/complete?session_id=...` is safe to hit again from the *same* browser tab/session if they haven't left it — if they have, there is no automated resend (no email sender exists yet, `docs/RETENTION_EMAILS.md`'s flagged gap). Brey looks up the session in Stripe, confirms payment, and mints a fresh admin invite (`POST /admin/invites`) by hand as the practical fallback, same as any lost-token case in section 5's canned response. |
| Paid twice / signed up twice with the same email | Confusion about which token is live | `POST /signup`'s idempotency means a second signup for an already-`active` email is a no-op on the account, not a second charge — check `GET /admin/users` and Stripe directly if a duplicate charge is reported (that's P1 billing, section 3). |
| Token pasted, app doesn't load Today | `first_today_view` never completes | Confirm `token_redeemed` fired (`GET /onboarding` for that user) before assuming the token itself is bad — a redeemed-but-stuck user is a product bug, not an access problem; escalate per section 4. |

**Founder-side checklist per new paying customer** (this is the same
personal-touch checklist `docs/FIRST_CUSTOMER_PLAYBOOK.md` §6 defines —
referenced here, not restated twice, so the two docs cannot drift):
watch `GET /onboarding` for the four steps below over the next few days;
send the day-3 email by hand if `first_bet_check`/`first_saved_bet` are
still incomplete (`docs/RETENTION_EMAILS.md` §2's exact trigger); do not
manually nudge before day 3 unless they reach out first.

## 2. First-session checklist

The four steps `GET /onboarding` reports, in the order a new user
naturally walks through them:

| Step | What it means | How it's proven |
|---|---|---|
| `token_redeemed` | Signed in with their invite token at least once | `events.INVITE_REDEEMED` |
| `first_today_view` | Loaded the Today slate | `events.PAGE_VIEW` with `route == "/today"` |
| `first_bet_check` | Ran a Bet Check on a real game | `events.BET_CHECK_RUN` |
| `first_saved_bet` | Saved a bet to My Bets | `events.BET_SAVED` |

Each step is complete **only if the underlying event actually exists** —
no assumed completion for old users, no partial credit. If a user reports
"I did X but it doesn't show as done," that is either a genuine bug
(escalate — see section 4) or a sign they did something adjacent (e.g.
viewed `/games` but never `/today`) rather than the exact step tracked.

A future UI can render this as a literal checklist; today it is JSON only.

## 3. Support triage SLAs (one-person company)

No ticketing system, no team to route to — Brey reads `GET /admin/support`
and works the queue. Realistic SLAs for a single operator running a
private alpha:

| Priority | Examples | Target first response |
|---|---|---|
| **P0 — data is wrong** | A price shown doesn't match the sportsbook; a game result / settlement looks incorrect; Bet Check shows something contradictory | Same day, ideally within a few hours |
| **P1 — billing** | Can't check out; charged wrong; wants a refund; subscription state looks off | Same day |
| **P0/P1 — account access** | Invite token expired/lost; can't sign in | Same day (this blocks the whole product for that person) |
| **P2 — everything else** | Feature requests, "how do I...", general feedback | Within 2 business days |

**Why data-wrong and billing jump the queue ahead of subject line or
sender:** a subscriber paying for a product that tells them something
false is the single fastest way to lose trust in a betting-analysis tool
— see `docs/PRODUCT_DESIGN_HANDOFF.md`'s trust-mechanism framing for why
the whole product is built around never fabricating a claim. Billing
issues are money already changed hands on a promise not yet kept — those
don't wait for the general queue either.

**Triage mechanics:**
1. `GET /admin/support?status=open` — the open queue, newest first.
2. Read `subject`/`body` for anything matching the P0/P1 examples above and
   handle those first, regardless of arrival order.
3. Reply by email (using whatever contact the sender left — `user_id`
   means look up their email via `GET /admin/users`; `email` on the
   message itself for an anonymous sender).
4. `POST /admin/support/{id}/status` with `{"status": "answered"}` once
   replied, `{"status": "closed"}` once resolved and confirmed (or once
   it's clear no further reply is coming).

## 4. Escalation rules

- **Any "data is wrong" report is P0 and feeds the health monitor.**
  Concretely: before replying, cross-check `GET /health`
  (`src/appstate/apphealth.py`) and, if the report is about odds or a
  specific game, the relevant forward-evidence/results store for that
  date. A data-wrong report that turns out to be a real bug (not user
  confusion) should also prompt a look at whether `apphealth.report()`
  would have caught it — if not, that's a gap worth a follow-up task, not
  something to paper over in the support reply alone.
- **Billing issues escalate to whichever billing provider is active**
  (`src/appstate/billing.py` — `NullBillingProvider` in dev,
  `StripeBillingProvider` once configured). A refund or chargeback dispute
  goes through Stripe's dashboard directly; this playbook does not cover
  Stripe's own process.
- **A P0 that can't be resolved same day** (a real bug needing a code fix)
  gets an interim reply acknowledging the issue and an honest timeline —
  never a guess dressed up as a fix, and never silence.
- **Security-shaped reports** (someone else's data visible, a token that
  shouldn't work, anything suggesting an auth bypass) skip this playbook
  entirely and go straight to a fix — treat as P0 regardless of how it's
  worded.

## 5. Canned responses (vocabulary-safe)

These are answers, not marketing — copy verbatim or adapt in tone, but
never claim something the product doesn't do. In particular: **never say
"recommendation," "we recommend," or "our pick"** — Ranker Engine 2 (bet
recommendations) stays gated; nothing in this product picks a side for the
user, and support copy must not imply otherwise (see `web/README.md`'s
"No client-composed claims" section and `PRODUCT_DESIGN_HANDOFF.md`'s
fixed-skeleton trust framing for why).

**Invite token expired / lost:**
> Sorry about that — invites expire after 14 days if unused. I've sent you
> a fresh one, should work right away.

**"Bet Check disagrees with what I see on my sportsbook":**
> Thanks for flagging — Bet Check prices from the books we pull at the
> time you ran it, so a real line move between then and now can look like
> a mismatch even when both numbers were correct at the moment they were
> shown. Can you tell me roughly when you ran it and which book you're
> comparing against? I'll check the snapshot on our end.

**Data genuinely looks wrong (after checking, it is):**
> You're right, that's off — thank you for catching it. [describe the fix
> or timeline]. I've made a note to look at why our check didn't catch
> this on its own.

**Billing question / can't check out:**
> Let me look into that on the Stripe side — can you confirm the email you
> used to sign up? I'll get back to you today.

**General "how do I..." / feature request:**
> Good question / good idea — [answer, or: "not built yet, but noted — I'm
> keeping a running list and this is a real vote for it"].

**Someone asks "what should I bet":**
> This tool doesn't make picks or recommendations — it's built to show you
> the support and the counterargument for a bet you're already looking at,
> so you can decide with the full picture. The decision's always yours.

## 7. Bug-report intake

There is no separate bug-report form — a bug report **is** a support
message (`POST /support`), triaged the same way as any other ticket. The
only thing this section adds is what to ask for so a report is actionable.

**Minimal template** — paste this into the reply if a report is missing
the essentials (do not block the report on it; ask once, in the reply):

> - **What happened** (what you expected vs. what you saw)
> - **Where** (which page/screen — Today, a specific game's Bet Check,
>   Odds, My Bets — and if it's about a specific game, which one and which
>   date)
> - **When** (roughly what time you saw it — helps line it up with a
>   specific price snapshot or a specific server response)
> - **Screenshot**, if it's a visual/data issue (a described mismatch
>   without one is much slower to confirm)

**Where reports land:** `POST /support` (authed or anonymous-with-email,
`api/support.py`) → `GET /admin/support?status=open`, the same queue every
other support message lands in. A bug report is not a separate table or a
separate inbox — this is deliberate for a queue this small (section 9's
own "no ticketing system" framing applies equally here).

**Triage into fixes:**
1. Classify by section 3's P0/P1/P2 table first — most bug reports that
   involve a wrong price, wrong result, or wrong verdict are P0 by that
   table's own definition, not because they're "bugs" but because they're
   data-wrong.
2. Reproduce against `GET /health` and, for a specific game, that game's
   own advanced/odds payload before replying — section 4's escalation
   rule.
3. If it's confirmed and fixable same-day: fix it, reply per the "Data
   genuinely looks wrong" canned response (section 5), and note the fix in
   the commit/PR that closes it — no separate bug-tracker doc exists for a
   team this size, and inventing one now would be process the queue
   doesn't need yet.
4. If it's confirmed but NOT fixable same-day: reply with the honest
   "P0 that can't be resolved same day" framing (section 4) and add one
   line to **Known open issues** below so it isn't lost between sessions.
5. If it's not reproducible or turns out to be user confusion rather than
   a real bug: say so plainly in the reply (never a silent close) and mark
   `answered`/`closed` per section 3's mechanics.

**Known open issues** (Brey appends here; delete a line once shipped —
this list exists so a confirmed-but-not-yet-fixed bug survives between
sessions, not as a public changelog):

- *(none logged yet)*

## 8. Escalation quick-reference — immediate vs. batched

Full reasoning is section 4; this is the fast-scan version for triage.

| Escalates to Brey **immediately** (same session, before anything else) | Handled in the normal queue (batched, per section 3's SLA table) |
|---|---|
| Billing error: wrong charge, charged after cancel, checkout broken for a paying attempt | Feature requests / "how do I..." (P2) |
| Wrong data shown: a price, result, or verdict that is actually incorrect (not just stale) | A stale-but-honest freshness gap (`age_seconds`, `has_market: false`) already surfaced correctly by the product |
| Security-shaped report: someone else's data visible, a token that shouldn't work, anything suggesting an auth bypass | A lost/expired invite token (P0/P1 but routine — section 5's canned response resolves it without escalation) |
| Anything that could be, or could look like, a guaranteed-outcome or edge claim reaching a customer (support script, canned response, or product copy) | General product feedback / survey responses (§8 loop below) |

"Immediately" means: stop and handle it (or get Brey directly) before
working anything else in the queue — these are exactly the categories
section 3 already ranks ahead of arrival order, restated here as a
yes/no gate rather than a priority label.

## 9. Known v1 scope cut — users cannot read their own support messages

`POST /support` is the only user-facing route; there is no `GET
/my-support` or equivalent. A user who files a ticket gets the created
message back in that one response and never again through the API — their
only record of the exchange is the email reply. This is deliberate for
v1 (see `api/support.py`'s and `tests/test_api_support.py`'s own
docstrings): a one-person support desk over email doesn't need an in-app
inbox yet, and building one now would be scope the alpha doesn't need.
Revisit if support volume or user feedback makes this a real complaint.
