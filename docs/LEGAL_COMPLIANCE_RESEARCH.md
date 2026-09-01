> **DRAFT — NOT LEGAL ADVICE — FOR COUNSEL REVIEW.** Everything below is
> research and drafting work product, prepared by an AI research agent, not
> an attorney. Nothing in this document is final; final sign-off on any
> classification, disclosure, or contract language is Brey's and counsel's
> alone (recorded gate: `docs/LAUNCH_DECISIONS.md`). Where sources conflict
> or coverage is thin, that is stated explicitly rather than resolved by
> guessing.

# Legal / Compliance Research — Sports-Betting Information Product

Prepared 2026-09-01. Scope per task: classification analysis, ad/marketing
constraints, disclosure mapping, draft policy skeletons, open questions for
counsel. Product facts assumed throughout (per task INPUTS): information/
research only, no bet placement, no wager handling, no affiliate links today,
Stripe subscriptions, US/MLB focus, 21+ where wagering is legal (product
itself is not wagering).

---

## 1. Classification: information service vs. gambling operator

### 1.1 The factors that matter

No single federal test exists; gambling is regulated state-by-state (the
Wire Act/UIGEA operate federally but target wagering and payment
transmission, not information provision — see open questions). Across the
state statutes and secondary sources reviewed, the recurring elements of
"gambling" are **prize, chance, and consideration** — i.e., something of
value is staked on an uncertain outcome
([Washington State Gambling Commission, "Illegal gambling activities"](https://wsgc.wa.gov/rules-enforcement/illegal-gambling-activities), accessed 2026-09-01).
A service that never touches any of the three legs is not itself "gambling"
under that framework:

- **No stake handling** — the product never accepts, holds, or transmits
  money staked on an outcome (Stripe subscription payments are payment for
  *the information product*, not a wager; see §4.2 on why this distinction
  needs to stay legible in Stripe's own account-classification review too).
- **No odds offering** — the product does not itself set or offer odds a
  user can accept to create a bet; it reports odds already publicly posted
  by third-party licensed sportsbooks.
- **No facilitation of the bet** — no "place bet" button, no API call that
  executes a wager, no bet-slip hand-off to a sportsbook
  (`docs/COMMERCIAL_READINESS.md` standing rule 5: "No real-money bet
  placement capability, ever, at any stage").

This is consistent with how the sports-information/handicapping trade is
commonly described in secondary sources: "statistical information
providers," "analytical services," and "public handicappers" are treated as
a different category from parties who "promote, broker, arrange, or conduct"
wagering itself
([RotoWire, "Who are sports betting handicappers?"](https://www.rotowire.com/betting/faq/who-are-sports-betting-handicappers-33d21bc1), accessed 2026-09-01;
general "betting operator" definition aggregator, [LawInsider](https://lawinsider.com/dictionary/betting-operator), accessed 2026-09-01).
**Caveat:** these are secondary/aggregator sources, not primary statutory
text or case law construing an information-service exemption specifically —
treat as directional, not authoritative. No single, citable federal or
model-state statute was found in this pass that names an "information
service" carve-out in so many words; the classification argument above is
an inference from the prize/chance/consideration test plus how the industry
and its (thinly-sourced) trade commentary describe the boundary, not a
holding counsel can cite directly.

A separate, non-gambling-statute risk sits alongside the classification
question: **"tout"/handicapper regulation**. Several states have historically
regulated persons who sell sports picks for a fee (registration or
disclosure requirements have existed at various points, e.g., in some
horse-racing-adjacent statutory schemes) — this project does not sell picks
(`ENGINE2 = None`; the Ranker publishes no recommendation per
`docs/COMMERCIAL_READINESS.md` standing rule 1), which is a materially
different posture than a classic "tout" product, but counsel should confirm
whether "price comparison + evidence labels + no recommendation" clearly
falls outside any tout-registration statute still on the books, since this
research pass found only general secondary description of the tout
category ([sportshandle.com, "What Exactly Is a Sports Betting 'Tout'?"](https://sportshandle.com/what-exactly-is-a-sports-betting-tout/), accessed 2026-09-01), not a state-by-state list of tout-specific licensing statutes.

### 1.2 States worth flagging for counsel attention

- **Washington** — gambling is illegal by default unless specifically
  authorized, online gambling participation is charged as a felony, and the
  Gambling Commission has sworn law-enforcement agents doing enforcement
  ([WSGC, "Illegal gambling activities"](https://wsgc.wa.gov/rules-enforcement/illegal-gambling-activities), accessed 2026-09-01).
  A jurisdiction with this broad a default-prohibition posture, this
  motivated an enforcement arm, and (per the competitive-intelligence
  research already in this repo) *reported* regulatory attention toward
  sharp/+EV betting-adjacent tooling specifically
  (`docs/COMPETITIVE_INTELLIGENCE/SEGMENT_SHARP_ODDS.md`, citing UNVERIFIED-
  secondary Reddit/Substack commentary about "regulatory attention
  reportedly beginning in Massachusetts" — note this actually names
  **Massachusetts**, not Washington, and is itself unverified; flagging both
  states here because Washington's statutory posture is independently
  broad and Massachusetts appears by name in that secondary source) is
  worth a specific counsel look before any MLB-state-agnostic marketing.
- **Massachusetts** — named in the competitive-intelligence research as the
  subject of *reported* (unverified, secondary-sourced) regulatory attention
  toward sharp-odds/+EV tooling users; this project's own vocabulary
  discipline (no "+EV," no "edge" as a customer noun — §2.2) is partly a
  hedge against exactly this kind of scrutiny, but the underlying claim is
  unverified and should be independently checked, not relied on as-is.
- **General note, not state-specific**: every state with legal sports
  wagering has its own "unfair/deceptive practices" and consumer-protection
  statutes that reach *misleading claims* regardless of gambling
  classification (see §2). A product that is correctly classified as
  "information service, not gambling operator" is not thereby exempt from
  ordinary advertising/consumer-protection law — that is a second,
  independent test.

**Sources quality for §1**: primary-source-adjacent for Washington (the
state agency's own page); everything else is secondary/aggregator-level
(RotoWire, LawInsider, this repo's own prior unverified secondary research).
No state Attorney General guidance or case law specifically addressing an
"information-only sports product" was located in this pass — this is the
single largest gap in §1 and the top item for actual counsel research (see
§5).

---

## 2. Advertising / marketing constraints

### 2.1 Platform ad policies (as researched 2026-09-01)

| Platform | What was found | Source |
|---|---|---|
| **Google Ads** | Gambling and Games policy now requires *certification* for gambling-related ad categories; certification requirements were expanded through multiple 2026 updates (March, July, August, and a further expansion effective September 14, 2026). Google's own framing covers "online gambling," "offline gambling," and "online gambling-promoting content" as a single umbrella. **Unresolved**: whether a pure information/price-comparison product with no wagering facilitation and no affiliate links to sportsbooks falls under "gambling-promoting content" requiring certification, or outside the policy's scope entirely, was not conclusively determined this pass — the policy text as summarized does not draw that line explicitly. Recommend a direct read of the live policy page plus an actual test submission before running any Google ad. | [Google Ads Help — Gambling and games](https://support.google.com/adspolicy/answer/15132179?hl=en); [March 2026 update](https://support.google.com/adspolicy/answer/16786233?hl=en); [July 2026 update](https://support.google.com/adspolicy/answer/17199930?hl=en); [August 2026 update](https://support.google.com/adspolicy/answer/17258294?hl=en) — all accessed 2026-09-01 via search-tool synthesis, not independently opened and read in full; treat exact certification scope as unconfirmed until the primary page is read directly. |
| **Meta (Facebook/Instagram)** | Real-money gambling ads require Meta's "Permissions and Verifications" process (license documentation, jurisdiction compliance certification). Category explicitly includes sports betting. **Same open question as Google**: whether a no-wagering information product is swept into "real-money gaming" for ad-authorization purposes is not resolved by the summaries found — Meta's own scoping language wasn't independently read this pass. Ads may not target under-18 audiences in any case. | [Meta Transparency Center — Online Gambling and Games](https://transparency.meta.com/policies/ad-standards/restricted-goods-services/gambling-games/); [Meta Business Help — About Meta's Online Gambling and Games policy](https://www.facebook.com/business/help/345214789920228) — accessed 2026-09-01 via search-tool synthesis. |
| **X (Twitter)** | As of Feb 2026, X banned gambling products/services (explicitly including sports betting) from *paid partnerships* (influencer/affiliate/ambassador deals) entirely — relevant if any future affiliate or influencer program is considered (product has none today per task INPUTS). Standard paid gambling ads remain "Restricted Content" requiring preauthorization. | [igamingexpert.com — "X bans gambling from influencer and paid partnerships"](https://igamingexpert.com/news/affiliates/x-twitter-ban/); [business.x.com Ads Policy Update Log](https://business.x.com/en/help/ads-policies/ads-policy-update-log) — accessed 2026-09-01. |

**Practical read for counsel**: do not assume any platform treats "we don't
handle wagers" as self-evidently outside its gambling-ad policy. All three
platforms define scope broadly enough ("gambling-promoting content,"
"real-money gaming") that a pure information/comparison product plausibly
gets swept in for ad-review purposes even though it is not a gambling
operator under state law. Recommend treating every paid ad channel as
"gambling-adjacent, verify before spending" rather than assuming an
information-product exemption exists anywhere.

### 2.2 The specific claims that get info products in trouble

Cross-referenced against this repo's own competitive research
(`docs/COMPETITIVE_INTELLIGENCE/BRAND_RESEARCH.md`,
`docs/COMPETITIVE_INTELLIGENCE/SEGMENT_AI_PREDICTION.md`), which already
identified these patterns among named competitors:

- **Unqualified/implied profitability or "guaranteed" claims** — the single
  clearest legal/credibility risk category identified in the competitive
  research (e.g. "guaranteed profit," "Total Member Profit: €23M," "96% of
  members say they've become profitable"). This product already bans this
  vocabulary at the code level (`tests/test_customer_language.py`:
  `guaranteed` only permitted in a negation; `src/analysis/disclaimers.py`'s
  beta disclaimer states "does not guarantee outcomes or profits").
- **Headline accuracy/hit-rate percentages with no disclosed sample size**
  ("100% Hit Rates" on n=3) — this product's standing rules require sample
  size accompany every numeric claim from the first alpha
  (`docs/COMMERCIAL_READINESS.md` standing rule 3).
- **"Edge" / "+EV" used as a customer-facing claim of an advantage the
  customer has** — banned as an affirmed (non-negated) claim by
  `tests/test_customer_language.py`; price improvement is the only
  customer-facing framing, and it must never be relabeled as EV
  (`docs/COMMERCIAL_READINESS.md` standing rule 2).
- **Unverifiable authority/award claims** (e.g. competitors citing an
  uncheckable "accuracy contest" or unnamed methodology) — no equivalent
  claim exists in this product today; flagged here so none gets added later
  without a traceable source.
- **"AI-powered"/"ensemble of N models" framed as a credibility signal
  without disclosed validation** — same caution; this product's actual
  research status (zero demonstrated predictive edges as of
  `docs/COMMAND_CENTER.md`) makes any such framing not just a marketing risk
  but factually false if implied as a validated edge.

### 2.3 Responsible-gambling messaging norms

Legal wagering states commonly require licensed *operator* advertising to
carry problem-gambling resources and a helpline number
([search-tool synthesis, no single primary state statute independently
opened this pass] — accessed 2026-09-01). Note a live complication: the
long-standing "1-800-GAMBLER" number is described in a 2025 NCPG statement
as being under threat/transition, with the National Council on Problem
Gambling's operations reportedly moving toward "1-800-MY-RESET"
([NCPG, "Statement on the Urgent Threat to National Access to
1-800-GAMBLER"](https://www.ncpgambling.org/news/ncpg-statement-on-national-access-to-1-800-gambler/), accessed 2026-09-01).
**This is unresolved and should not be hard-coded**: confirm the current
correct helpline number with counsel/NCPG directly before publishing any
disclosure, rather than trusting either number as of this document's date.
This product is not a licensed wagering operator, so no statute reviewed
this pass *requires* it to carry this messaging — but including it anyway
is both a credibility differentiator (no competitor reviewed in
`docs/COMPETITIVE_INTELLIGENCE/` was found to lead with sample-size honesty
or RG messaging) and a reasonable precaution given the product's subject
matter and audience.

**Sources quality for §2**: platform-policy summaries came from search-tool
synthesis of secondary/blog-level sources describing Google/Meta/X policy
pages, not from directly fetching and reading the primary policy pages in
full — recommend an actual read-through of each live policy page (URLs
above) before any paid ad campaign launches, since certification/scoping
details change often (Google alone updated this policy three times in 2026
per the sources found).

---

## 3. Required/expected disclosures — mapping to current product state

| Disclosure | Expected content | Where it lives today | Status |
|---|---|---|---|
| Age statement (21+ where wagering is legal) | Explicit "21+" / "where legal" statement | Not found in `src/analysis/disclaimers.py`'s `BETA_DISCLAIMER` text, nor in `api/meta.py`'s `PRODUCT_ONE_LINER`. | **Gap.** Neither string currently states an age requirement. |
| No-outcome/profit-guarantee language | Plain statement the product does not guarantee outcomes or profits | `BETA_DISCLAIMER`: "It does not guarantee outcomes or profits, for any user or any bet." | **Present** (beta-labeled, flagged `requires_final_legal_review=True`). |
| User owns their own wagering decisions | Statement that the user, not the product, decides/owns the bet | `BETA_DISCLAIMER`: "You are solely responsible for your own wagering decisions, including whether to bet at all." | **Present.** |
| No-edge / no-locked-result framing | Explicit denial that any output is an "edge" or "lock" | `BETA_DISCLAIMER`: "Nothing here is a betting edge, a locked-in result, or a guarantee of any outcome." | **Present**, and reinforced structurally by `tests/test_customer_language.py`'s negation-only rule for "edge." |
| Responsible-gambling helpline resource | 1-800-GAMBLER (or current NCPG number — see §2.3 caveat) plus a "gambling problem? help is available" framing | Not found anywhere in `src/analysis/disclaimers.py` or `api/meta.py`. | **Gap.** No helpline reference exists in the product today. |
| Data-accuracy / "informational, not advice" limits | Explicit statement that content is not financial/legal/betting advice, and data may be delayed, incomplete, or wrong | Implied by the "information and research" framing in both `BETA_DISCLAIMER` and `PRODUCT_ONE_LINER`, but no explicit "this is not advice" or "we do not warrant accuracy" sentence exists in either. | **Partial gap** — present in spirit, not stated as an explicit accuracy-limitation/no-advice disclaimer. Addressed in the ToS draft (§4.1). |
| Not a gambling operator / no wager facilitation statement | Explicit statement that the product does not place bets, hold stakes, or offer odds | Not present in `BETA_DISCLAIMER` or `PRODUCT_ONE_LINER`; true in code (no such capability exists per `docs/COMMERCIAL_READINESS.md` standing rule 5) but not stated to the customer. | **Gap** — true in fact, absent in customer-facing text. |
| Subscription/billing disclosure (cancellation terms, refund stance) | Plain-language cancellation and refund policy, visible before purchase | Not present anywhere reviewed (`src/appstate/billing.py`, `api/meta.py`); `docs/COMMERCIAL_READINESS.md` standing rule 4 requires this be written and shown "before" billing exists, i.e., before PAID BETA, not yet due. | **Not yet due** per the product's own readiness ladder, but flagged since PAID BETA is scheduled 2026-09-10..14 per `docs/LAUNCH_DECISIONS.md`. |

**Net read**: the beta disclaimer covers the "no guarantee / no edge / your
decision" core well, but is missing the age gate, the responsible-gambling
resource, and an explicit "not a gambling operator" statement — none of
which are currently required by any statute confirmed in this research pass
(§1's biggest gap), but all three are cheap, defensible, differentiating
additions worth counsel's sign-off before paid launch. This document does
not propose editing `src/analysis/disclaimers.py` itself — that file is
explicitly Brey/counsel's to finalize, and this task's BOUNDARIES restrict
changes to `docs/` only.

---

## 4. Drafts — DRAFT, FOR COUNSEL REVIEW, NOT FOR PUBLICATION AS-IS

Every draft below repeats the top-of-document banner. These are skeletons
to accelerate counsel's drafting, not text to ship unreviewed.

### 4.1 Terms of Service — skeleton

> DRAFT — NOT LEGAL ADVICE — FOR COUNSEL REVIEW. Do not publish without
> counsel sign-off. Placeholders in [BRACKETS] are unresolved.

```
TERMS OF SERVICE (DRAFT)
Last updated: [DATE] — Effective date: [DATE]

1. WHO WE ARE / WHAT THIS IS
   [Product name] ("we," "us") provides sports-betting information and
   research for MLB: publicly available odds comparisons, evidence-labeled
   analysis, and price-improvement data. We do not place bets, hold
   wagering stakes, offer odds ourselves, or facilitate any wager. We are
   not a sportsbook, a bookmaker, or a gambling operator.

2. NOT ADVICE, NO FIDUCIARY RELATIONSHIP
   Nothing on this service is financial, legal, or betting advice. We do
   not act as your agent, fiduciary, or advisor. All wagering decisions,
   including whether to wager at all, are yours alone. See our Beta
   Disclaimer (referenced at /meta) for our current no-guarantee statement.

3. ELIGIBILITY
   You must be [21] years or older and located where sports wagering
   information services are lawfully accessible. [COUNSEL: confirm exact
   age/jurisdiction gating language and whether geofencing is required or
   merely a stated eligibility condition — this product does not itself
   verify state of residence today; flag as an open question, §5.]

4. DATA ACCURACY LIMITS
   Odds, prices, and other third-party data are sourced from public feeds
   and may be delayed, incomplete, or incorrect. We do not warrant the
   accuracy, completeness, or timeliness of any information. [Evidence-
   label / sample-size framework referenced here per
   docs/COMMERCIAL_READINESS.md standing rule 3.]

5. SUBSCRIPTIONS AND BILLING
   Paid plans are billed via Stripe, our payment processor. We do not
   store your card details — Stripe holds all payment-instrument data
   (see src/appstate/billing.py: "NO CARD DATA, EVER"). You may cancel at
   any time through [self-serve Stripe Customer Portal link], effective
   [at end of current billing period / immediately — COUNSEL/BREY: pick
   one; docs/COMMERCIAL_READINESS.md standing rule 4 requires one-click
   cancellation, no retention flow, no dark pattern]. Refund policy:
   [TBD — must be written and visible before PAID BETA per standing rule 4].

6. ACCEPTABLE USE
   [Standard: no scraping/reverse-engineering beyond permitted API use, no
   resale of our data without permission, no circumventing rate limits.]

7. INTELLECTUAL PROPERTY / DMCA
   [Standard DMCA safe-harbor designated-agent language — TBD: designated
   agent name/address/email must be registered with the U.S. Copyright
   Office before this clause is meaningful; TBD flag.]

8. DISCLAIMERS AND LIMITATION OF LIABILITY
   THE SERVICE IS PROVIDED "AS IS." WE DISCLAIM ALL WARRANTIES, EXPRESS OR
   IMPLIED. WE ARE NOT LIABLE FOR ANY WAGERING LOSSES OR DECISIONS MADE IN
   RELIANCE ON THE SERVICE. [COUNSEL: standard liability cap language,
   jurisdiction-appropriate.]

9. DISPUTE RESOLUTION / ARBITRATION — TBD, FLAGGED FOR COUNSEL
   [No arbitration clause drafted here. Whether to include mandatory
   arbitration, a class-action waiver, and a governing-law/venue choice is
   a decision for Brey and counsel together — not drafted by default.]

10. CHANGES TO THESE TERMS
    [Standard: notice mechanism, effective-date-on-change language.]

11. CONTACT
    [Support/legal contact email — TBD, does not exist as a public address
    yet per product state.]
```

### 4.2 Privacy Policy — skeleton (matched to `src/appstate/` actual collection)

> DRAFT — NOT LEGAL ADVICE — FOR COUNSEL REVIEW. Do not publish without
> counsel sign-off.

Data inventory this draft is built from (verified by reading the modules
directly, 2026-09-01):

- **Email** — `src/appstate/users.py`: `users(id, email, created_at,
  status, plan)`. Stored in plaintext (it is the account identifier, not a
  secret); invite tokens are hashed (`sha256`) at rest, never stored raw.
- **Saved bets** — `src/appstate/savedbets.py`: append-only, soft-delete
  records of "what a user saw and chose to keep," including a
  caller-supplied `snapshot_digest` fingerprint of the evidence shown at
  save time. No stake/wager amount is described as stored by this module.
- **Billing identifiers** — `src/appstate/customers.py`: local mapping of
  `user_id` to a Stripe customer/subscription ID and status string only.
  **No card data** — `src/appstate/billing.py`'s own docstring: "NO CARD
  DATA, EVER... this app only ever sees a checkout URL, a subscription id,
  and a status string." Stripe's hosted Checkout/Customer Portal handles
  all payment-instrument data.
- **Hashed analytics** — `src/appstate/events.py`: product-analytics events
  keyed on `sha256(user_id)`, never the raw id; explicitly excludes emails,
  raw auth tokens, bet amounts/stakes from any event's `properties_json` by
  documented contract (not type-enforced).
- **Request logs** — `src/appstate/reqlog.py`: structured per-request log
  lines that must never contain bearer tokens, emails, or request/response
  bodies; user correlation via a hashed `user_ref`, never a raw id or email.
- **Rate-limit counters** — `src/appstate/ratelimit.py`: fixed-window
  per-key counters (key shape not confirmed in this pass — verify before
  publishing whether the key is a hashed user id, an IP, or something else).

```
PRIVACY POLICY (DRAFT)
Last updated: [DATE]

1. WHAT WE COLLECT
   - Account email address, at signup.
   - Bets you choose to save ("My Bets"): the pick, price, and evidence
     snapshot at the time you saved it. These records are kept even if you
     delete them from your view (soft-delete) for [retention period — TBD].
   - Billing: a Stripe customer ID and subscription status. We never see or
     store your card number, CVV, or other payment-instrument data —
     Stripe's own hosted systems handle that entirely.
   - Product-usage analytics: page views and feature-usage events, keyed to
     a one-way hashed version of your account ID, not your raw ID or email.
   - Server request logs: technical request metadata (route, timing,
     status) keyed to the same hashed identifier; never your email, bearer
     token, or the content of what you sent or received.

2. WHAT WE DO NOT COLLECT (today)
   - No affiliate-link tracking (we do not currently run an affiliate
     program — see §4.3 template, held in reserve, unused).
   - No payment card data of any kind.
   - No wager-execution data (we do not place or execute bets, so none
     exists to collect).

3. HOW WE USE IT
   [Standard: operate the service, respond to support, improve the
   product via aggregated/hashed analytics, comply with law.]

4. THIRD PARTIES
   - Stripe (payment processing) — see Stripe's own privacy policy for how
     it handles your payment data.
   - [Hosting/infra provider — TBD, pending docs/LAUNCH_DECISIONS.md
     Decision 3 outcome.]
   - [Auth provider — TBD, pending Decision 1 outcome (Clerk direction
     decided, not yet integrated with real credentials).]

5. RETENTION
   - Saved bets: retained even after user-facing deletion (soft-delete) —
     [COUNSEL/BREY: state the actual retention/purge period; none is
     specified in src/appstate/savedbets.py today, which stores rows
     indefinitely by default].
   - Analytics/log data: [retention period — TBD, not found specified in
     src/appstate/events.py or reqlog.py].

6. YOUR RIGHTS
   [State-specific: CCPA/CPRA (California), and other state privacy laws
   as applicable — TBD, needs counsel to confirm which apply given a
   US-wide subscriber base.]

7. CHILDREN
   Not directed to children; not knowingly used by anyone under [18/21 —
   align with ToS eligibility, TBD].

8. CONTACT
   [Privacy contact — TBD.]
```

### 4.3 Affiliate-disclosure template — unused today, held in reserve

> DRAFT — NOT LEGAL ADVICE — FOR COUNSEL REVIEW. **Not currently applicable:
> the product runs no affiliate links or partnerships today** (task
> INPUTS). Kept here so a future affiliate program does not launch without
> disclosure ready, per FTC endorsement-guide norms (general awareness, not
> independently re-verified against the current FTC Endorsement Guides text
> in this pass — counsel should confirm the live FTC text before any
> affiliate program launches, since guide updates are common).

```
AFFILIATE DISCLOSURE (TEMPLATE — UNUSED)

Some links on this page may be affiliate links. If you sign up for a
sportsbook or service through one of these links, we may receive
compensation at no additional cost to you. This does not affect our
evidence labels, price-improvement calculations, or any other analysis —
[COUNSEL: confirm placement/prominence requirements (FTC "clear and
conspicuous," near the link itself, not buried in a footer) before this is
ever activated].
```

---

## 5. Open questions for counsel — prioritized

1. **[HIGH]** Is the "information service, not gambling operator"
   classification (§1.1) actually sound in every state where the product
   will be marketed/sold, or does any state's statute or AG guidance treat
   evidence-labeled price comparison + saved-bet tracking as something
   closer to regulated activity? No primary statutory or case-law source
   confirming an information-service carve-out was found in this pass —
   this is a real gap, not a formality.
2. **[HIGH]** Does the product need geofencing / state-of-residence
   verification given it doesn't itself facilitate wagering, or is a stated
   eligibility condition ("21+, where lawful") in the ToS sufficient?
   Nothing in `src/appstate/` verifies location today.
3. **[HIGH]** Confirm the current, correct responsible-gambling helpline
   number to cite (1-800-GAMBLER vs. a transitioned NCPG number) before any
   disclosure ships — §2.3 found this to be unresolved/in flux as of this
   research date.
4. **[MEDIUM]** Does Google/Meta/X's gambling-ad policy actually apply to a
   pure information/price-comparison product with no affiliate sportsbook
   links, or only to products that facilitate or promote wagering directly?
   Not resolved by the summaries found (§2.1) — needs a direct policy read
   or a test-ad submission.
5. **[MEDIUM]** Arbitration clause and class-action waiver: include or not?
   Flagged TBD in the ToS skeleton (§4.1 §9) — a business decision with
   legal tradeoffs, not drafted by default.
6. **[MEDIUM]** Data retention periods for saved bets, analytics, and logs
   are currently undefined in code (`src/appstate/savedbets.py`,
   `events.py`, `reqlog.py` all store indefinitely by default) — what
   retention/purge policy should the Privacy Policy commit to, and does any
   applicable state privacy law require a specific period or a
   deletion-on-request mechanism beyond the existing soft-delete?
7. **[MEDIUM]** Which state privacy statutes (CCPA/CPRA and any other
   state's consumer privacy law) actually apply given the anticipated
   subscriber geography, and what specific rights language does the
   Privacy Policy need as a result?
8. **[LOW]** DMCA designated-agent registration — needs to happen with the
   U.S. Copyright Office before the ToS's DMCA clause is meaningful; purely
   a to-do, not a judgment call.
9. **[LOW]** Tout/handicapper-specific licensing statutes: this pass found
   only secondary/general descriptions of the "tout" category (§1.1), not a
   state-by-state list of any tout-registration requirements still in
   force — worth a dedicated look given the product's evidence-labeled
   analysis (even though it publishes no picks/recommendations).

---

## Sources (full list, access date 2026-09-01)

- [Washington State Gambling Commission — Illegal gambling activities](https://wsgc.wa.gov/rules-enforcement/illegal-gambling-activities)
- [RotoWire — Who are sports betting handicappers?](https://www.rotowire.com/betting/faq/who-are-sports-betting-handicappers-33d21bc1)
- [sportshandle.com — What Exactly Is a Sports Betting "Tout"?](https://sportshandle.com/what-exactly-is-a-sports-betting-tout/)
- [LawInsider — betting operator definition](https://lawinsider.com/dictionary/betting-operator)
- [Google Ads Help — Gambling and games policy](https://support.google.com/adspolicy/answer/15132179?hl=en)
- [Google Ads Help — March 2026 certification update](https://support.google.com/adspolicy/answer/16786233?hl=en)
- [Google Ads Help — July 2026 certification update](https://support.google.com/adspolicy/answer/17199930?hl=en)
- [Google Ads Help — August 2026 global update](https://support.google.com/adspolicy/answer/17258294?hl=en)
- [Meta Transparency Center — Online Gambling and Games](https://transparency.meta.com/policies/ad-standards/restricted-goods-services/gambling-games/)
- [Meta Business Help — About Meta's Online Gambling and Games advertising policy](https://www.facebook.com/business/help/345214789920228)
- [igamingexpert.com — X bans gambling from influencer and paid partnerships](https://igamingexpert.com/news/affiliates/x-twitter-ban/)
- [business.x.com — Ads Policy Update Log](https://business.x.com/en/help/ads-policies/ads-policy-update-log)
- [National Council on Problem Gambling — Statement on the Urgent Threat to National Access to 1-800-GAMBLER](https://www.ncpgambling.org/news/ncpg-statement-on-national-access-to-1-800-gambler/)
- Internal: `src/analysis/disclaimers.py`, `api/meta.py`, `src/appstate/{users,savedbets,customers,billing,events,reqlog,ratelimit}.py`, `docs/COMMERCIAL_READINESS.md`, `docs/LAUNCH_DECISIONS.md`, `docs/COMPETITIVE_INTELLIGENCE/{BRAND_RESEARCH,SEGMENT_AI_PREDICTION,SEGMENT_SHARP_ODDS,SEGMENT_PROPS_TRACKING,NAMING}.md`, `tests/test_customer_language.py` (all read directly, not via search synthesis).

**General sources-quality note**: web sources in §1 and §2 are
predominantly secondary (blog/aggregator summaries and search-tool
synthesis of platform help pages), not primary statutory text, case law, or
directly-fetched-and-read policy pages. Every external claim above is
attributed to its actual source and flagged where confidence is low. This
is a starting point for counsel's own primary-source research, not a
substitute for it.
