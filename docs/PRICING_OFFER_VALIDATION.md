# Pricing / Offer Validation Package

Date: 2026-09-01. Analysis + drafts only — nothing here is customer-facing
until Brey approves it. Inputs: `COMPETITIVE_INTELLIGENCE/{PRICING,
COMPETITOR_MATRIX.csv, CUSTOMER_PAIN, PERSONAS}.md`, `PRICING_CALCULATOR_REVIEW.md`
(two-branch + breakeven framing only — respected throughout), `COMMERCIAL_READINESS.md`.
No `CONTENT_LANDING.md` exists in the repo; not used. No new web research was
needed — the competitive matrix (verified 2026-08-31, cited with URLs in
`SOURCES.md`) already covers current competitor price points; where a number
below is not in that matrix it is marked ASSUMPTION, not invented.

Vocabulary rules from `COMMERCIAL_READINESS.md` standing rule 2 apply
absolutely in every draft below: never "EV," "edge," "ROI," bare "value,"
"expected value," "pays for itself," or an implied guarantee.

---

## 1. Offer structure recommendation

**Recommendation: one tier, one price, no feature ladder, for PAID BETA.**
`COMMERCIAL_READINESS.md` gates PAID BETA to MLB-only, single-sport, no
professional tier, no multi-sport. There is nothing to segment by yet — a
tiered ladder (à la Rithmm Core/Pro/Premium or BetQL's 1/2/3/all-sport)
requires either multiple sports or a feature genuinely worth gating, and we
have neither at this stage. Building tiers now would be manufacturing
complexity to imitate competitors' ladders, not serving a real product
difference. Recommend against tiers until multi-sport ships (`ROADMAP.md`
Stage 11, separately gated).

**Beta price:** $19.99/mo, single tier, all current MLB features included
(evidence ladder, price-improvement board, What Changed, Bet Check, saved
bets). Rationale in §2.

**Post-beta (Stage 5 / Public V1) monthly:** $29.99/mo — the number
`COMMERCIAL_READINESS.md`'s own BREY DECISION ITEMS row and `PRICING.md`
already anchor to (Rithmm Core / BetQL Pro-VIP / Outlier Premium+ neighbor
price, $20–35/mo band).

**Annual:** $239/yr at the $19.99/mo beta price (effective $19.92/mo — this
is a *founding* annual, priced at the monthly rate, not discounted twice —
see founding-member framing below); $239/yr at post-beta $29.99/mo pricing
would be a ~33% discount, matching Rithmm Core's confirmed ~33% (the richest
discount in the market norm's ~17–34% range per `PRICING.md`). Discount math,
shown honestly:
- 12 × $29.99 = $359.88/yr at monthly rate.
- $239/yr ÷ 12 = $19.92/mo effective → (359.88 − 239) / 359.88 ≈ 33.6% discount.
State the discount as "2 months free at this rate" or the exact percentage —
never "$X/mo value" framing, which reintroduces the calculator's banned
persuasive-arithmetic problem into a different part of the page.

**Founding-member framing (first cohort only):** the first N paid-beta
subscribers get **$19.99/mo (or $239/yr) locked for as long as they stay
subscribed, even after the public price moves to $29.99/mo**. This is
honest, concrete, and checkable — a real price lock, not a vague "founding
member" badge. State N explicitly once decided (see §3 decision rule) and
state the lock condition plainly: "locked while your subscription stays
active; if you cancel and resubscribe later, current pricing applies." No
countdown timer, no "only 3 spots left" urgency copy — those are exactly the
billing-trust-eroding patterns `CUSTOMER_PAIN.md` documents competitors
using.

**Tiers / what's included:** none. One plan, full feature set. This directly
avoids two competitor failure modes found in the research: (1) BetQL's
sport-count tier ladder is "the segment's messiest" pricing (`PRICING.md`)
and (2) feature-gating a small, honesty-differentiated product would bury
the actual differentiator (evidence labels, sample-size display) behind a
paywall tier — undermining `COMMERCIAL_READINESS.md` standing rule 3 that
evidence labels reach the customer from the first alpha, paid or not.

**Refund/cancel policy draft (customer-friendly, Stripe-implementable):**

> **Cancel anytime, no retention flow.** Cancel from your account page in
> one click — no phone call, no "are you sure" loop, no email required.
> Your access continues through the end of the billing period you already
> paid for; you will not be charged again.
>
> **Refunds.** If you're charged and didn't mean to be — you forgot to
> cancel during a trial, or you were billed in error — email support within
> 7 days of the charge and we'll refund it in full, no questions asked. This
> applies once per customer per plan; we reserve the right to review
> repeated refund requests on the same account.
>
> **Price changes.** If we raise the price, subscribers already on a lower
> price keep it as long as their subscription stays active (see
> founding-member terms above). We'll always email you at least 30 days
> before any price change that affects you.
>
> **What happens to your data if you cancel.** Your saved bets and account
> data are kept for 30 days after cancellation in case you resubscribe,
> then deleted. You can request deletion sooner from the account page.

Stripe implementation notes: Stripe Billing Customer Portal natively
supports self-serve cancel (no retention flow needed in code — it must be
*configured* off, since Stripe's portal ships an optional cancellation
survey/downsell screen that should be disabled to meet the "no retention
dark pattern" standing rule); the 7-day refund window is a manual/webhook-
triggered full refund via the Stripe API, not automatic; price-lock-on-
existing-subscribers is native (existing Subscription objects keep their
Price ID unless explicitly migrated).

---

## 2. Price-point rationale anchored to the competitive matrix

**Where we sit:** $19.99/mo for beta undercuts the $20–35/mo band that
`PRICING.md` identifies as "the thickest band in the market" and where our
direct neighbors (Rithmm Core $29.99, BetQL Pro/VIP $24.99–29.99, Outlier
Premium+ $29.99) already compete on feature depth we don't yet have
(Rithmm's model builder and Scout AI-chat, BetQL's Sharp Picks/public-bet%).
$19.99/mo instead lands beside Props.Cash ($19.99/mo) and Outlier Premium
($19.99/mo) — single-purpose research/tracking tools, not AI-prediction
products with feature depth. This is a **deliberate beta discount below the
$20–35 band we intend to occupy at Public V1**, not a permanent competitive
position: `PRICING.md` explicitly warns "the bands are crowded; there is no
room to win on price" as a long-term strategy, but a below-band beta price
is a different thing — it is priced for an unproven, single-sport,
zero-demonstrated-edge product being asked of real strangers for the first
time, and the founding-member lock rewards early trust rather than
permanently discounting the product.

**Why honesty positioning does not yet permit a premium.** The Rithmm-Pro/
BetQL-Sharp/PropsBot.ai/PlayerProps.ai neighbors at $49.99–59.99/mo all
bundle a feature we do not have (AI chat, sharp-money signal, an audited-
style dashboard, community/education) — `PRICING.md` is explicit that "a
prospect at $49.99/mo can already get an AI-chat assistant or a sharp-money
signal for the same money." Our differentiation (sample-size transparency,
published nulls, no coin-flip-worthy overclaiming) is real per the evidence
but is a *trust* differentiator, not a *feature* differentiator, and trust
differentiators are proven over time in a product, not asserted on a
pricing page on day one. Charging a premium for unproven trust before any
beta user has experienced it would be the same "confident, less honest"
failure mode `PRODUCT_ARCHITECTURE_AUDIT.md`/`COMMERCIAL_READINESS.md`
flag repeatedly. **Discount to below-band for beta; premium is earned later,
if retention and willingness-to-pay signals from this beta support it
(§3).**

**Willingness-to-pay evidence, quoted directly from our own research
(`PERSONAS.md`):**

- Persona 1 (casual serious bettor), our primary beta target: "**Willingness
  to pay [EVIDENCE, anchored]**: $20–35/mo band — matches Rithmm Core
  ($29.99), BetQL Pro/VIP ($24.99–29.99), Outlier Premium+ ($29.99), the
  thickest band in the market." This persona's stated most valuable feature
  is consolidation — "it would take me 1-2 hours and now it takes 2
  seconds" (quoted from `CUSTOMER_PAIN.md`'s Rithmm review) — a value
  proposition our product can make honestly once it exists as a real
  product, independent of prediction accuracy.
- Persona 3 (prop-heavy bettor): "**Willingness to pay [EVIDENCE, anchored]**:
  $10–35/mo — Props.Cash and LineMate sit at the low end ($10–20)... this
  persona spans a wider band than most," and is explicitly named as the
  persona our sample-size-transparency positioning is evidenced *against*
  ("positioned specifically against the sample-size-transparency gap").
  This persona's price ceiling comfortably covers a $19.99 beta price.
- Persona 4 (data nerd): ceiling is $35–100/mo, mapped to a future
  all-sport tier, not the beta MLB single-sport plan — do not price the
  beta MLB plan to this persona's ceiling; they are not the beta's primary
  target.
- Cross-persona churn evidence (`CUSTOMER_PAIN.md` cross-product synthesis):
  "picks/projections perceived as no better than random" and "price
  relative to perceived value" are named cancellation drivers **ahead of
  raw price sensitivity** in some products, but always **behind** billing/
  cancellation-deception complaints, which is the single most-repeated theme
  across all nine products studied. This is direct evidence that clean
  billing conduct (§1's refund/cancel draft) matters more to retention than
  shaving another few dollars off the beta price.

---

## 3. Validation plan for the beta cohort

### 3a. The 5–7 questions to ask beta users

Timed to land after a user has had at least 2 weeks of access and at least
one billing cycle if they've converted from closed beta to paid, delivered
as a short in-product or emailed survey (not a phone call — keep the ask
proportional to a $19.99/mo product):

1. **Worth-it threshold:** "In the last two weeks, did checking [product]
   before a bet feel worth the time it took, more often than not?"
   (yes/no/unsure) — a behavioral worth-it read, not a satisfaction score.
2. **Comparison anchor:** "Before this beta, what did you use instead —
   another app, a website, or nothing in particular?" (open text) — directly
   tests the "10-tab problem" / ESPN-comparison hypothesis from
   `CUSTOMER_PAIN.md` against our actual beta users, not competitors' users.
3. **Price anchor, asked honestly:** "If this cost $19.99/mo after the beta
   ends, would you keep it, or is that too much / not enough to seem
   credible?" — offered as three options (keep / too much / suspiciously
   cheap for what it claims), not a slider or a willingness-to-pay auction
   mechanism, to avoid over-engineering a 5-question survey.
4. **Cancel-trigger, asked prospectively:** "What would make you cancel a
   subscription like this?" (open text) — designed to surface billing
   friction, perceived-accuracy disappointment, or feature gaps *before*
   they cause silent churn, matching the cross-product churn taxonomy in
   `CUSTOMER_PAIN.md` §2.
5. **Trust-framing comprehension check** (required per
   `COMMERCIAL_READINESS.md` Stage 2/3 exit criteria — usability of the
   honesty framing, not just pricing): "In your own words, what does this
   product promise about whether its predictions are accurate?" (open text)
   — success = the answer does not describe a guarantee or an edge; if it
   does, that's a product-copy bug, not a pricing signal, and should be
   routed back to the copy audit, not treated as a pricing input.
6. **Feature that earned its keep:** "Which single feature, if any, made you
   come back?" (open text, optional) — feeds the "what's included" decision
   for any future tier, without pre-supposing tiers exist yet.
7. **(Optional, only for cohort members who saw closed beta free and now
   pay) Conversion friction:** "Was there anything about the switch from
   free to paid that almost stopped you?" — direct billing-conduct signal.

Keep to 5 required (1–5) + 2 optional (6–7); do not lengthen this survey —
low-effort surveys get honest, higher-response answers from a beta cohort
this small.

### 3b. Instrumenting willingness signals without creepy tracking

The analytics scaffold already in `src/appstate/events.py` is the only
willingness-signal source to use — it already enforces the right privacy
boundary (hashed `user_id`, no raw ids, no PII, no bet amounts/stakes ever
written to `properties_json`) and should not be extended beyond its
documented four event kinds for this purpose:

- **`bet_check_run` frequency per user per week** — a directly-recorded,
  already-wired signal (`api/betcheck.py`, only on successful checks). Rising
  or steady per-user weekly frequency across a billing cycle is a stronger
  willingness signal than a survey answer, because it's revealed behavior,
  not stated preference. Aggregate only — report "median weekly
  `bet_check_run` count, cohort-wide" and "% of paying users with ≥1
  `bet_check_run` in the last 7 days," never a per-user leaderboard or
  anything that could re-identify a person from the aggregate.
- **`bet_saved` as a stickiness proxy** — a user who saves bets is building
  a reason to return; track cohort-wide % of paying users with ≥1 saved bet,
  same aggregation rule.
- **Retention** — cohort-level, computed from `INVITE_REDEEMED` (signup) and
  `PAGE_VIEW`/`BET_CHECK_RUN` timestamps already stored: week-over-week
  active-user retention curve for the beta cohort. This is the standard,
  privacy-safe SaaS retention metric and needs no new instrumentation.
- **What NOT to add:** no session-replay, no click-heatmaps, no time-on-page
  tracking beyond what `PAGE_VIEW` already records, no cross-device
  fingerprinting, no reading of `properties_json` for anything but the
  documented safe-to-aggregate fields it already carries (e.g. `{"market":
  "h2h"}` on a bet_check_run — never a stake or an identity). This keeps the
  willingness-signal pipeline inside the privacy contract `events.py`
  already documents, rather than building a second, looser one for pricing
  research specifically.
- **Combine, don't replace:** treat `bet_check_run` frequency + retention as
  the *behavioral* signal and the survey (§3a) as the *stated* signal;
  disagreement between them (e.g., high usage but survey says "too
  expensive") is itself informative and should be reported, not resolved by
  picking one.

### 3c. Decision rule for setting the launch price

Set launch price (the price Public V1 opens at, distinct from the founding-
member locked price) after **N = 50 paying beta users** or **M = 8 weeks**
from the first paid-beta charge, whichever comes first — both numbers are
ASSUMPTIONS, not evidenced minimums (`COMMERCIAL_READINESS.md` itself flags
that "exact minimum tester/beta-cohort sizes... are stated as qualitative...
since no user-volume or unit-economics model exists yet" — this doc does not
manufacture false precision there; Brey should adjust N/M if a real
acquisition-rate estimate exists that this research doesn't have).

At that checkpoint, apply this decision rule:

| Signal combination | Decision |
|---|---|
| Retention curve flat-to-rising **and** ≥60% of survey respondents say "keep" at $19.99 **and** zero unresolved billing-dark-pattern complaints | Raise to $29.99/mo at Public V1 as planned (§1); founding cohort keeps $19.99 lock. |
| Retention curve falling **or** <40% say "keep" at $19.99 | Do not raise price; treat as a product-value problem, not a pricing problem — re-examine question 6 (what feature earned its keep) and question 4 (cancel triggers) before touching the number again. Zero survivors on willingness-to-pay is a valid result here, not evidence to explain away. |
| Mixed signal (retention holds, survey ambivalent, or vice versa) | Hold at $19.99/mo for one more monthly cycle and re-survey; do not decide on a single ambiguous read. |
| Any billing-dark-pattern complaint surfaces at all | Fix the billing issue first, full stop, before any price decision — per `COMMERCIAL_READINESS.md` standing rule 4, this is stop-ship severity, not a input to average into the pricing decision. |

This rule intentionally does not use `bet_check_run` volume alone to justify
a price increase — usage without stated willingness is exactly the
"confident, less honest" risk pattern this project's own docs warn against;
both signals must point the same direction before the price moves.

---

## 4. Breakeven presentation spec (customer-facing pricing page)

Per `PRICING_CALCULATOR_REVIEW.md`, the only approved framing is the
two-branch payout statement plus the breakeven-win-rate line, both computed
from user-entered odds pairs, never from an assumed win probability or the
de-vigged consensus. The pricing page inherits the same hard constraints —
this section states what the *pricing page specifically* may and may not
claim; it does not re-derive the calculator's math (see that doc for the
full spec).

**The pricing page MAY:**
- Show the plan price plainly ($19.99/mo, $239/yr) with the annual-discount
  percentage stated honestly (§1's math), labelled as a discount on list
  price, never as "savings" phrased to imply money earned back.
- Link to or embed the approved two-branch/breakeven calculator
  (`PRICING_CALCULATOR_REVIEW.md` §3) as a demonstration of what "price
  improvement" means mechanically — both branches (win/lose) rendered in the
  same visual block, same font size, exactly as that spec requires.
- State the breakeven win-rate arithmetic ("at −110 you need 52.4% to break
  even; at −105 you need 51.2%") as pure price arithmetic.
- Describe what the subscription includes (evidence labels, price-
  improvement board, What Changed, Bet Check) as features, factually.
- State the refund/cancel policy from §1 in full, prominently, before
  checkout — not buried in a ToS link.
- State plainly that there is no demonstrated predictive edge yet, if any
  language on the page could otherwise be read as implying one — this is
  required, not merely permitted, per `COMMERCIAL_READINESS.md` standing
  rules 3 and 6.

**The pricing page MAY NOT** (explicit list, no implementer discretion):
- "Pays for itself" or any phrase implying the subscription cost is
  recovered by using the product.
- "EV," "expected value," "edge," "ROI," bare "value" as a benefit noun, or
  any single unconditional dollars-per-month figure derived from an assumed
  win probability.
- Any comparison of the calculator's `delta_per_month` output to the plan
  price ("covers your subscription N times over") — banned explicitly in
  `PRICING_CALCULATOR_REVIEW.md` §3 hard constraint #6, and it applies with
  identical force here.
- Guaranteed savings, guaranteed better prices, or any language implying an
  execution guarantee at a named book (tie rate 63–79% per that review;
  never name the book holding the best price).
- Any accuracy, win-rate, or "beats the coin flip" claim tied to the
  product's own predictions — no competitor-comparison accuracy claim of any
  kind until the forward ledger clears its 300-selection floor
  (`ROADMAP.md` Stage 7) and Brey separately approves publication
  (`COMMERCIAL_READINESS.md` BREY DECISION ITEMS, track-record row).
- Urgency/scarcity pricing copy ("only N founding spots left," countdown
  timers) — not explicitly banned by the calculator review, but excluded
  here because it is the same category of persuasive-arithmetic-adjacent
  dishonesty this project has already rejected once, and because
  `CUSTOMER_PAIN.md` ties manufactured urgency to the billing-deception
  complaint cluster in spirit even where not literally documented for this
  product.

---

## BREY DECISION BLOCK

**DECISION:** What price to charge at PAID BETA launch, and what the
founding-member cohort size (N) should be.

**WHY:** `COMMERCIAL_READINESS.md`'s own Stage 3→4 exit criteria requires
pricing locked before the first real charge; changing price on existing
subscribers mid-beta is itself a billing-trust risk. This is a one-way door
for the first paying cohort's expectations.

**OPTIONS:**
- (a) **$19.99/mo, $239/yr, founding-member price locked for life-of-
  subscription** — this doc's recommendation. Below-band vs. the $20–35/mo
  competitive cluster, priced for an unproven single-sport product; earns
  trust before asking for a premium.
- (b) **$29.99/mo, $299/yr now** — matches the number `PRICING.md` and
  `COMMERCIAL_READINESS.md`'s existing BREY DECISION ITEMS row already
  anchor to for *post-beta* pricing; charging it at beta launch instead
  means competing head-on with Rithmm Core/BetQL Pro/Outlier Premium+ on
  their exact price before we have their feature depth (model builder, AI
  chat, sharp-money signal).
- (c) **Free closed beta continues indefinitely; skip a discounted paid-beta
  step entirely and go straight to $29.99/mo at Public V1** — avoids ever
  training a cohort to expect a lower price, at the cost of never observing
  real willingness-to-pay before the public number is locked.

**RECOMMENDATION:** Option (a). It generates a genuine willingness-to-pay
signal at a price low enough that a "no" is informative (not just "too
expensive for what it is yet") while still being a real charge, not a token
one — and the founding-member lock converts the early discount into a
retention asset rather than a permanent price concession.

**WHAT CONTINUES WITHOUT THIS DECISION:** Closed beta (free, per
`COMMERCIAL_READINESS.md` Stage 3) proceeds unaffected regardless of which
option is chosen — this decision only gates the Stage 3→4 transition to
PAID BETA, not anything before it.

**DEADLINE:** Before Stripe integration begins (Stage 4 entry criteria,
`COMMERCIAL_READINESS.md`) — recommend deciding alongside the payment-
processor and refund-policy-publication decisions already pending in that
doc's BREY DECISION ITEMS table, since all three block the same milestone.
