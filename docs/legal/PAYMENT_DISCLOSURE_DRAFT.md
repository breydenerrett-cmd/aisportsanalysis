# DRAFT — NOT LEGAL ADVICE — REQUIRES COUNSEL REVIEW

Prepared 2026-09-01. Covers what the checkout page must disclose before
charging a card, drawing on the federal ROSCA negative-option framework and
Visa/Mastercard card-network subscription rules. This is a compliance
checklist for what must appear, not a legal opinion that satisfying this
checklist is sufficient — counsel should confirm.

## Legal/regulatory basis (cited, dated 2026-09-01)

- **ROSCA (Restore Online Shoppers' Confidence Act)** — a marketer selling
  a negative-option (auto-renewing) subscription online must: (1) clearly
  and conspicuously disclose all material terms *before* obtaining billing
  information; (2) obtain the consumer's express informed consent before
  charging; and (3) provide a simple mechanism to stop recurring charges.
  Material terms that must stand out visually and sit immediately adjacent
  to the billing-information field include the recurring charge amount,
  billing frequency, and first-charge date.
  ([FTC ROSCA overview / Cooley summary](https://www.cooley.com/news/insight/2024/2024-04-11-ftc-enhances-scrutiny-of-subscriptions-and-negative-option-features-under-rosca), accessed 2026-09-01)
- **Note on rulemaking status**: the FTC's 2024 "Click-to-Cancel" Rule
  (which would have added stricter consent/cancellation-parity
  requirements on top of ROSCA's statutory core) was vacated by the Eighth
  Circuit and the FTC reopened rulemaking in March 2026
  ([Consumer Financial Services Law Monitor, "FTC Reopens 'Negative
  Option' Rulemaking After Eighth Circuit Vacates 2024 Amendments"](https://www.consumerfinancialserviceslawmonitor.com/2026/03/ftc-reopens-negative-option-rulemaking-after-eight-circuit-vacates-2024-amendments/), accessed 2026-09-01).
  **ROSCA's underlying statutory disclosure/consent/cancellation
  requirements are unaffected by that vacatur** — only the 2024 Rule's
  additional specifics are in flux. Counsel should track this rulemaking
  before finalizing checkout copy, since the compliance bar could tighten
  again.
- **Visa/Mastercard card-network rules** — separately from ROSCA, card
  networks require: subscription terms (price, frequency, trial length if
  any) disclosed at the point where card details are entered; a
  confirmation email at enrollment restating all subscription terms and
  cancellation instructions; and, for billing cycles less frequent than
  every 180 days, a reminder notice 7–30 days before each charge. Trial-
  to-paid conversions require an electronic reminder with a cancellation
  link at least 7 days before the first post-trial charge.
  ([Mastercard — "Revised Standards for Subscription/Recurring Payments and
  Negative Option Billing"](https://www.mastercard.us/content/dam/public/mastercardcom/na/global-site/documents/subscription_recurring-payments-and-negative-option-billing-merchants.pdf); [Chargebacks911 — "Visa Recurring Payments & Subscription
  Guidelines"](https://chargebacks911.com/visa-recurring-payments/) — accessed
  2026-09-01, both secondary/compliance-vendor summaries, not the primary
  network rulebooks; counsel/payments-ops should confirm against Visa's and
  Mastercard's current operating regulations directly, as these documents
  update periodically.)

## What the checkout page must show (checklist)

Before the card-details field, clearly and conspicuously (not in a footer
link, not in a scroll-past ToS block):
- [ ] The recurring charge amount ($19.99/mo, or $239/yr if annual).
- [ ] The billing frequency (monthly / annually).
- [ ] The date of first charge (today, if no trial; or the trial end date).
- [ ] Whether a free trial exists, and its exact length, if applicable
      (product currently offers 3 introductory Bet Checks total, not a
      time-boxed trial — confirm with Brey whether checkout copy needs to
      distinguish "free feature allotment" from "free trial period," since
      card-network trial-disclosure rules are specifically about
      time-boxed trials converting to paid).
- [ ] The cancellation mechanism and that it is self-serve / one-click
      (link to `REFUND_CANCELLATION_DRAFT.md`'s cancellation copy).
- [ ] The age/eligibility checkbox (`AGE_GATE_DRAFT.md`).
- [ ] A link to the full ToS and Privacy Policy (supplementary to, not a
      replacement for, the above inline disclosures).

At/after enrollment (not just at checkout):
- [ ] A confirmation email restating the plan, price, billing frequency,
      and how to cancel — sent automatically at signup. **Gap today**: per
      `api/signup.py`'s own docstring, no transactional email sender is
      wired into the app yet; this confirmation email cannot ship until
      one is. Flag as a launch blocker for PAID BETA, not a nice-to-have.
- [ ] If billing is less frequent than every 180 days (i.e., the annual
      plan), a reminder notice 7–30 days before each renewal charge —
      same email-sender dependency.

## Vocabulary check
No pricing-page claim may use "pays for itself," "EV," "value" as a benefit
noun, or compare the price-improvement calculator's output to the
subscription price — these are explicit hard bans already established in
`docs/PRICING_OFFER_VALIDATION.md` §4 and apply identically to any checkout
copy drafted from this document.

## Open items for counsel
1. Confirm current Visa/Mastercard rulebook text directly (the sources
   above are compliance-vendor summaries).
2. Track the FTC's reopened negative-option rulemaking (as of March 2026)
   for whether stricter click-to-cancel-style requirements re-emerge before
   paid public launch.
3. Confirm whether the "3 introductory Bet Checks" free allotment needs
   trial-specific disclosure treatment or is out of scope for that rule set.
