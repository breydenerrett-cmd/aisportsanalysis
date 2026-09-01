# Retention email templates — DRAFT

Working brand: Linehound (temporary, pending trademark/domain clearance —
Brey 2026-09-01).

Text only, no HTML/visual design — same split `docs/CONTENT_LANDING.md`
makes (a separate Claude Design session owns aesthetics). The product has
not cleared a final legal/trademark name; every mention uses **LINEHOUND**
as the working brand per Brey's 2026-09-01 decision (supersedes the open
finalist list in `docs/COMPETITIVE_INTELLIGENCE/NAMING.md`/`CHECKPOINT.md`).
Every merge
field is bracketed and listed under each template. Every quantitative claim
is cited inline as `<!-- source: FILE -->`, same convention as
`CONTENT_LANDING.md`.

Vocabulary rules from `tests/test_customer_language.py` and
`tests/test_content_language.py` apply absolutely, in the same words
`docs/CONTENT_LANDING.md` states them: no plus-sign EV framing, no claim of
a "true" price, no guaranteed outcome, no invented win probability, no
claim that betting is risk-free or that any pick is a certain winner. Price
improvement is described only as line-shopping value — never as an edge,
never as a wagering-expectancy number. No countdown timers, no manufactured
scarcity, no "are you sure?" retention loop beyond the one honest save-
attempt email below — that boundary is `docs/PRICING_OFFER_VALIDATION.md`
§1's "no dark patterns" rule, applied to email copy specifically.

**Every template below is marked DRAFT and none is wired to send anything.**

---

## SENDER INFRASTRUCTURE: NOT BUILT (Brey decision)

**There is no email-sending capability anywhere in this codebase.** No
transactional email provider (Postmark/SendGrid/SES/Resend/etc.) is
integrated, no API key is configured, and no code path in `src/` or `api/`
sends an email to anyone. `docs/ONBOARDING_SUPPORT_PLAYBOOK.md` §1 already
states this for the beta invite email specifically ("Brey sends the invite
email by hand — no automated invite-email sender exists yet"); the same gap
applies to every template in this document.

**Why this is a decision for Brey, not something this task should
silently work around:** adding a transactional email provider means a new
external credential (an API key with send-as-this-domain authority) and a
new paid vendor relationship — the same category of one-way-door decision
`docs/COMMERCIAL_READINESS.md` and `docs/LAUNCH_DECISIONS.md` already flag
for auth (Clerk) and billing (Stripe). This task does not pick a vendor,
does not request an API key, and does not wire a send path — it produces
the templates a future sender would use, once Brey decides which provider
to grant credentials for. Domain sending also needs SPF/DKIM/DMARC records
on whatever domain sends these, which is a DNS/deliverability decision
bundled into the same "pick a provider" choice, not a separate one.

**What exists today, and what does not:**
- Exists: the templates below; the data this codebase can already compute
  to fill their merge fields (`src/analysis/digest.py`'s
  `build_user_digest`, `src/appstate/savedbets.py`, `src/appstate/events.py`).
- Does not exist: a scheduler that decides when to send one, a provider
  integration that actually delivers it, a suppression-list/unsubscribe
  mechanism, or bounce/complaint handling. All of that is downstream of
  the provider decision above.

**Until that decision is made,** every template here is either sent by
Brey by hand (the same interim step the invite email already uses) or not
sent at all.

---

## 1. Daily digest email

**Purpose:** the email wrapper around `GET /digest`
(`src/analysis/digest.py`, `api/digest.py`) — the retention trigger this
task pairs with the email templates. Sent (once a sender exists) once a day
to a user with at least one saved bet or at least one prior product
session, never to someone who has never used the product.

**Trigger condition:** `GET /digest`'s own payload is non-trivial for this
user — at minimum one of: `settled_bets` is non-empty, `what_changed.quiet`
is `False`, or `price_improvement` is not `None`. A digest with nothing in
any of those three sections should not be sent at all (see "What this
email will not do," below) — the trigger is a real content gate, not a
fixed daily cron regardless of content.
<!-- source: src/analysis/digest.py (build_user_digest's three content
sections; "quiet" fields exist specifically so a caller can detect an
empty digest rather than send one) -->

**Merge fields:**
- `[FIRST_NAME]`
- `[SETTLED_BETS_SECTION]` — rendered from `digest.settled_bets`; omitted
  entirely (not shown as "you have no settled bets") when that list is
  empty.
- `[SLATE_HEADLINE]` — `digest.slate.headline`, verbatim.
- `[WHAT_CHANGED_SECTION]` — rendered from `digest.what_changed.highlights`
  when `digest.what_changed.quiet` is `False`; omitted entirely otherwise.
- `[PRICE_IMPROVEMENT_SECTION]` — rendered from `digest.price_improvement`
  when it is not `None`; omitted entirely otherwise.
- `[APP_LINK]`

**Subject:** Your LINEHOUND digest — [SLATE_HEADLINE]

Hi [FIRST_NAME],

Here's what's new since your last digest.

[SETTLED_BETS_SECTION]
<!-- e.g.: "Your BOS@NYY save settled: won. Your LAD@SF save settled:
lost." — one line per digest.settled_bets item, using
settlement_status/settlement_reason exactly as src/appstate/settlement.py
recorded them. Never a payout figure -- no bet-placement or bankroll
feature exists in this codebase (src/appstate/settlement.py's own module
docstring: "grade_bet... never computes a payout in dollars"). -->

**Tonight:** [SLATE_HEADLINE]

[WHAT_CHANGED_SECTION]
<!-- e.g.: "2 notable changes since our last look: [headline], [headline]."
— straight from digest.what_changed.highlights; never more than the 5-item
cap src/analysis/digest.py enforces (MAX_CHANGED_HIGHLIGHTS). -->

[PRICE_IMPROVEMENT_SECTION]
<!-- e.g.: "One thing worth a look: [away]@[home] [side] — the best price
on the board beat the market-implied consensus. If it wins, it pays more;
if it loses, both cost the same." Two-branch framing required per
docs/CONTENT_LANDING.md §4 / docs/PRICING_CALCULATOR_REVIEW.md — never a
single unconditional dollar figure. -->

[Open LINEHOUND → APP_LINK]

— The LINEHOUND team

**What this email will not do:**
- Send on a day with nothing in any of the three sections — a digest that
  would be entirely empty is not sent, not sent with "nothing changed
  today" filler. (Contrast with `GET /digest` itself, which always returns
  a quiet-but-honest payload when called — the API and the email trigger
  are allowed to differ here because an email is an interruption a quiet
  API response is not.)
- State a payout, a win rate, or a recommendation. `digest.settled_bets`
  reports outcome only (won/lost/push/void-unmatchable); no dollar amount
  is computed anywhere in this codebase from a saved bet's price.
<!-- source: src/appstate/savedbets.py (SETTLEMENT_STATUSES); src/appstate/
settlement.py ("no bet-placement or bankroll feature") -->

---

## 2. Day-3 check-in

**Purpose:** a single, honest touch three days after signup for a user who
has not yet run a Bet Check or saved a bet — surfacing the product's actual
capability, not manufacturing urgency to convert them.

**Trigger condition:** `onboarding_state`'s `first_bet_check` and
`first_saved_bet` steps are both still incomplete 3 days after
`token_redeemed` (`src/appstate/onboarding.py`,
`docs/ONBOARDING_SUPPORT_PLAYBOOK.md` §2). Sent once, never repeated for
the same user regardless of what they do afterward.

**Merge fields:**
- `[FIRST_NAME]`
- `[APP_LINK]`

**Subject:** Anything confusing about LINEHOUND so far?

Hi [FIRST_NAME],

You joined a few days ago — just checking in, no pressure.

If you haven't tried it yet: open today's slate, pick a game, and run a
Bet Check on any side you're considering. You'll see the best price
currently quoted, the market-implied consensus separately, and the
supporting case and honest counterargument for that side — including a
line that says plainly when we found no significant counterargument.
<!-- source: docs/CONTENT_LANDING.md §2 ("Bet Check") -->

If something was confusing, missing, or you didn't trust a number you
saw — reply to this email directly. It goes to a real person (there's no
support team here yet, just Brey), and it shapes what gets built next.
<!-- source: docs/ONBOARDING_SUPPORT_PLAYBOOK.md §3 ("No ticketing system...
Brey reads GET /admin/support and works the queue") -->

[Open LINEHOUND → APP_LINK]

— LINEHOUND

**What this email will not do:** push a feature tour, offer a discount, or
imply the free trial/beta access is at risk of ending — none of those are
true today (`docs/COMMERCIAL_READINESS.md`: closed beta is free, Stage 3),
and stating a false urgency here would be exactly the billing-trust
erosion `docs/PRICING_OFFER_VALIDATION.md` §1 documents competitors using.

---

## 3. Pre-cancellation save attempt

**Purpose:** the one and only retention touch that fires when a user
initiates cancellation — honest, no dark pattern, matching
`docs/PRICING_OFFER_VALIDATION.md` §1's refund/cancel draft exactly:
"Cancel anytime, no retention flow... no phone call, no 'are you sure'
loop." This email does not block, delay, or complicate the cancellation
itself — Stripe's own self-serve cancel flow completes regardless of
whether this email is ever read or replied to.
<!-- source: docs/PRICING_OFFER_VALIDATION.md §1 (refund/cancel policy
draft; Stripe implementation notes: "must be *configured* off... the
portal ships an optional cancellation survey/downsell screen that should
be disabled") -->

**Trigger condition:** fires AFTER a Stripe cancellation is confirmed
(`events.SUBSCRIPTION_CANCELLED`), never before or during — this is
explicitly a **post-cancellation** message, not an interstitial the
cancel button routes through. The distinction matters: an email sent after
the fact cannot function as a retention dark pattern in the way a
pre-cancellation survey/downsell screen can, because it does not stand
between the user and the cancellation they already completed.

**Merge fields:**
- `[FIRST_NAME]`
- `[CANCEL_EFFECTIVE_DATE]` — end of the already-paid billing period, per
  the refund/cancel policy ("Your access continues through the end of the
  billing period you already paid for").
- `[FEEDBACK_LINK_OR_EMAIL]`

**Subject:** You've cancelled — one honest question, no pressure

Hi [FIRST_NAME],

Your LINEHOUND subscription is cancelled. Your access continues
through [CANCEL_EFFECTIVE_DATE]; you won't be charged again after that.
<!-- source: docs/PRICING_OFFER_VALIDATION.md §1 (refund/cancel policy
draft, verbatim terms) -->

If you're open to it: what made you cancel? There's no offer attached to
this question — we're not going to counter with a discount or a "wait,
before you go" screen. We just want to know if it was the price, the
picks, something broken, or something else entirely, because that's
exactly the signal `docs/PRICING_OFFER_VALIDATION.md`'s beta pricing
decision is waiting on.
<!-- source: docs/PRICING_OFFER_VALIDATION.md §3a, question 4 ("Cancel-
trigger, asked prospectively") -->

[Reply to this email, or FEEDBACK_LINK_OR_EMAIL]

Your saved bets and account data are kept for 30 days in case you want to
come back, then deleted. You can request deletion sooner by replying here.
<!-- source: docs/PRICING_OFFER_VALIDATION.md §1 ("What happens to your
data if you cancel") -->

— LINEHOUND

**What this email will not do (explicit, no implementer discretion):**
- Offer a discount, an extended trial, a downgrade, or any other retention
  incentive — none of the honest-cancellation research this project has
  done supports offering one, and doing so here would be the exact
  downsell pattern `docs/PRICING_OFFER_VALIDATION.md` §1 requires disabled
  in Stripe's own portal.
- Ask the cancellation question more than once, or follow up if unanswered
  — one honest ask, no chase.
- Delay, gate, or reference the cancellation as reversible in a way that
  implies the user should reconsider before it "really" takes effect — the
  cancellation already happened; this email reports it, it does not
  re-litigate it.

---

## 4. Win-back after cancel

**Purpose:** a single later touch for a cancelled user, only if the
product itself has changed in a way worth telling them about — never a
bare "come back" nudge with nothing new to say.

**Trigger condition:** sent no sooner than 30 days after
`events.SUBSCRIPTION_CANCELLED`, and ONLY when there is a real, checkable
reason to reach out — e.g. a new research finding published
(`docs/RESEARCH_CATALOGUE.md` gaining an entry), the founding-member price
lock (`docs/PRICING_OFFER_VALIDATION.md` §1) being about to close to new
subscribers, or a genuinely new feature. If none of those is true 30 days
out, no win-back email is sent — a content-free "we miss you" email is
exactly the kind of engagement-for-its-own-sake pattern this product's own
honesty positioning argues against.
<!-- source: docs/CONTENT_LANDING.md ("positioning is evidential
transparency... not a promise of winning"); the same standard applied to
retention email content, not just product copy -->

**Merge fields:**
- `[FIRST_NAME]`
- `[WHATS_NEW_SECTION]` — the specific, real, dated reason for this email;
  required, not optional (see trigger condition).
- `[PRICE]` — the founding-member locked price, if the win-back reason is
  the price-lock deadline; the number itself is pending Brey's decision
  (`docs/PRICING_OFFER_VALIDATION.md`'s BREY DECISION BLOCK recommends
  $19.99/mo, not yet approved) — this template names it only as a merge
  field, never a hardcoded number, so it cannot ship stale if the decision
  lands on a different figure.
- `[APP_LINK]`

**Subject:** What's changed at LINEHOUND since you left

Hi [FIRST_NAME],

You cancelled a while back — no hard feelings, and nothing below requires
you to come back. Just thought you'd want to know:

[WHATS_NEW_SECTION]
<!-- e.g.: "We published research family #5 — [N] more ideas tested,
[M] survived falsification testing" (cite the real number from
docs/RESEARCH_CATALOGUE.md at send time; do not restate "zero" if the
research record has changed by then), or "Founding-member pricing
([PRICE]/mo, locked for as long as you stay subscribed) closes to new
subscribers on [DATE]." -->

If you want back in: [Open LINEHOUND → APP_LINK]. Same account,
same saved history if it's still within the 30-day retention window.

— LINEHOUND

**What this email will not do:**
- Manufacture a reason to send if none of the trigger conditions above are
  true — see trigger condition.
- Use urgency/scarcity copy beyond a real, dated fact already true
  elsewhere (e.g. an actual founding-member cohort closing date, if one is
  set) — no invented countdown, no "only N spots left" framing not backed
  by a real, Brey-approved number.
<!-- source: docs/PRICING_OFFER_VALIDATION.md §1 ("No countdown timer, no
'only 3 spots left' urgency copy — those are exactly the billing-trust-
eroding patterns CUSTOMER_PAIN.md documents competitors using") -->
- Reference why they cancelled (the pre-cancellation email's answer, if
  they gave one) in a way that could read as guilt or pressure — a
  win-back leads with what's new, never with what they said on the way out.

---

## Open items for Brey (not resolved by this doc)

- **Sender/provider decision** (see the section above) — nothing sends
  until this is chosen; the templates are ready either way.
- Product name unresolved (three finalists, none cleared) — every
  `LINEHOUND` placeholder needs a global find/replace once locked,
  same open item `CONTENT_LANDING.md` already carries.
- `[PRICE]` in the win-back template is deliberately left unfilled pending
  `docs/PRICING_OFFER_VALIDATION.md`'s BREY DECISION BLOCK (price + N for
  the founding cohort).
- No unsubscribe/suppression-list mechanism exists yet — required before
  any of these actually send, and bundled into the sender-provider decision
  above (most providers handle this natively once integrated, but it is
  not automatic and must be verified, not assumed).
- Send cadence/scheduling (a daily cron for the digest, an event-driven
  trigger for the other three) is not implemented — these are content
  templates only, per this task's stated boundary (no sender code).
