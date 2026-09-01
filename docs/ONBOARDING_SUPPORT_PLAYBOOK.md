# Onboarding & Support Playbook (private alpha)

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

## 6. Known v1 scope cut — users cannot read their own support messages

`POST /support` is the only user-facing route; there is no `GET
/my-support` or equivalent. A user who files a ticket gets the created
message back in that one response and never again through the API — their
only record of the exchange is the email reply. This is deliberate for
v1 (see `api/support.py`'s and `tests/test_api_support.py`'s own
docstrings): a one-person support desk over email doesn't need an in-app
inbox yet, and building one now would be scope the alpha doesn't need.
Revisit if support volume or user feedback makes this a real complaint.
