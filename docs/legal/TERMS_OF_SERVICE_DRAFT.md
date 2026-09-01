# DRAFT — NOT LEGAL ADVICE — REQUIRES COUNSEL REVIEW

Prepared 2026-09-01, builds on `docs/LEGAL_COMPLIANCE_RESEARCH.md` §4.1.
Placeholders in [BRACKETS] are unresolved and must not ship unfilled.
Product facts: Linehound (working brand), $19.99/mo subscription, MLB
sports-betting information/analysis only — never places bets, never holds
wagering stakes, never handles gambling funds; Stripe processes payment for
the information product.

---

## TERMS OF SERVICE (DRAFT)

**Last updated:** [DATE] · **Effective:** [DATE]

### 1. What this is
[Product name] ("we," "us," "Linehound") provides sports-betting
information and research for MLB — publicly observed odds comparisons,
evidence-labeled analysis, and price-improvement data. We do not place
bets, hold wagering stakes, offer odds ourselves, or facilitate any wager.
We are not a sportsbook, bookmaker, or gambling operator.

### 2. Not advice, no fiduciary relationship
Nothing on this service is financial, legal, or betting advice. We are not
your agent, fiduciary, or advisor. All wagering decisions — including
whether to wager at all — are yours alone.

### 3. Eligibility
You must be [21] years or older and located where sports-wagering
information services are lawfully accessible to you. [COUNSEL: confirm the
exact age/eligibility language and whether geofencing/location
verification is required, or a stated eligibility condition is sufficient
— the product does not verify state of residence today. See
`AGE_GATE_DRAFT.md` and `STATE_AVAILABILITY_DRAFT.md`.]

### 4. Data accuracy limits
Odds, prices, schedules, and other third-party data are sourced from
public feeds and may be delayed, incomplete, or incorrect. We do not
warrant the accuracy, completeness, or timeliness of any information. Every
displayed rate or historical-support figure is shown with its sample size;
where data is unavailable we say so rather than estimate it.

### 5. Subscriptions and billing
Paid plans are billed via Stripe, our payment processor. We never see or
store your card number, CVV, or other payment-instrument data — Stripe's
hosted systems hold all of that. You may cancel at any time through the
self-serve Stripe Customer Portal (or your account page). **Cancellation
policy:** cancelling stops future renewal; you keep access through the end
of the billing period you already paid for. You will not be charged again
after cancelling. Refund posture: see `REFUND_CANCELLATION_DRAFT.md` — a
BREY DECISION, not resolved here. See `PAYMENT_DISCLOSURE_DRAFT.md` for
what the checkout page itself must show before you're charged.

### 6. Acceptable use
You agree not to: scrape or reverse-engineer the service beyond the
permitted API/UI use; resell or redistribute our data or analysis without
written permission; attempt to circumvent rate limits or access controls;
use the service for any unlawful purpose, including to facilitate wagering
in a jurisdiction where it is not legal. [COUNSEL: standard acceptable-use
boilerplate, tailored to venue.]

### 7. Intellectual property / DMCA
[Standard DMCA safe-harbor language. A designated agent (name, address,
email) must be registered with the U.S. Copyright Office before this
clause has legal effect — not yet done; see the Matrix, item 7.]

### 8. Disclaimers and limitation of liability
THE SERVICE IS PROVIDED "AS IS" AND "AS AVAILABLE." WE DISCLAIM ALL
WARRANTIES, EXPRESS OR IMPLIED, INCLUDING MERCHANTABILITY, FITNESS FOR A
PARTICULAR PURPOSE, AND NON-INFRINGEMENT. TO THE MAXIMUM EXTENT PERMITTED
BY LAW, WE ARE NOT LIABLE FOR ANY WAGERING LOSSES, OR ANY DECISION MADE IN
RELIANCE ON THE SERVICE, OR FOR INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES. [COUNSEL: set a liability cap (e.g., fees paid in the prior 12
months) and confirm enforceability by state.]

### 9. Dispute resolution / arbitration — TBD, FLAGGED FOR COUNSEL
No arbitration clause, class-action waiver, or venue/governing-law choice
is drafted here. This is a business decision with real legal tradeoffs for
Brey and counsel to make together, not a default to fill in.

### 10. Changes to these terms
[Standard: notice mechanism (email + in-app banner), effective-date-on-
change language, and how continued use constitutes acceptance.]

### 11. Contact
[Support/legal contact email — does not exist as a public address yet;
must be created before this ToS is published.]

---

### Notes for counsel (not part of the published ToS)
- The product's own beta disclaimer (`src/analysis/disclaimers.py`,
  `id="beta-v1"`, `requires_final_legal_review=True`) is a separate,
  narrower, temporary notice — this ToS is meant to supersede it at paid
  public launch, not duplicate it forever.
- Vocabulary constraint carried over from the codebase's own tests
  (`tests/test_customer_language.py`): "guarantee," "edge," "sure thing,"
  "can't lose" may appear only negated, never affirmed, anywhere this ToS
  is quoted in customer-facing surfaces.
