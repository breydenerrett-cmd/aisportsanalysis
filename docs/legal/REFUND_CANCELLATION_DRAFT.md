# DRAFT — NOT LEGAL ADVICE — REQUIRES COUNSEL REVIEW

Prepared 2026-09-01, matching the period-end cancellation policy already
adopted in `docs/PRICING_OFFER_VALIDATION.md` §1 and
`docs/COMMERCIAL_READINESS.md` standing rule 4 (one-click cancellation, no
retention flow, no dark pattern).

## Customer-facing copy (cancellation half — not a BREY decision, already set)

> **Cancel anytime, no retention flow.** Cancel from your account page in
> one click — no phone call, no "are you sure" loop, no email required.
> Your access continues through the end of the billing period you already
> paid for; you will not be charged again.
>
> **Price changes.** If we raise the price, subscribers already on a lower
> price keep it as long as their subscription stays active (founding-member
> terms, if applicable). We'll email you at least 30 days before any price
> change that affects you.
>
> **What happens to your data if you cancel.** Your saved bets and account
> data are kept for [30 days — TBD, see Privacy Policy §4] after
> cancellation in case you resubscribe, then deleted. You can request
> deletion sooner from your account page.

## BREY DECISION BOX — refund posture (not resolved by this draft)

The cancellation policy above (period-end access, no retention dark
pattern) is settled. **The refund policy is not** — it is a business
decision with billing-trust and revenue tradeoffs, laid out as three
standard options:

| Option | What it means | Tradeoff |
|---|---|---|
| **(a) No refunds, ever** — cancellation stops future billing only | Simplest to implement and explain; matches many SaaS subscriptions | Riskiest for trust/chargebacks if a user is charged after forgetting to cancel; `docs/PRICING_OFFER_VALIDATION.md`'s own research found billing/cancellation-deception complaints are the single most-repeated churn driver across competitors reviewed |
| **(b) Short-window full refund, no-questions-asked (e.g., 7 days from charge), once per customer per plan** | `docs/PRICING_OFFER_VALIDATION.md`'s existing recommendation — catches "forgot to cancel during a founding-price trial" and billing-error cases without becoming a standing return policy | Requires a manual/webhook-triggered refund step in Stripe (not automatic); needs an abuse rule (once per customer) to prevent repeat-refund abuse |
| **(c) Pro-rated refund for unused time on any cancellation** | Most generous to the customer | Most complex to implement correctly with Stripe proration; least common in this product category (`docs/PRICING_OFFER_VALIDATION.md`'s competitive research doesn't show this as a norm) — likely more generosity than the market expects, at a real revenue cost for a single-tier $19.99/mo product |

`docs/PRICING_OFFER_VALIDATION.md` already recommends **(b)**, but frames it
as part of its own BREY DECISION BLOCK on pricing generally — treat the
refund choice as still open until Brey confirms it explicitly, separate
from the pricing number itself.

## Stripe implementation notes (from existing research, unchanged)
- Stripe Billing Customer Portal natively supports self-serve, one-click
  cancel — the portal's optional cancellation survey/downsell screen must
  be *configured off* to satisfy "no retention dark pattern," since it
  ships enabled by default.
- A short-window refund (option b) is a manual/webhook-triggered full
  refund via the Stripe API, not automatic.
- Price-lock for existing subscribers when the price rises is native to
  Stripe (existing Subscription objects keep their Price ID unless
  explicitly migrated).

## Where this must appear (per `PAYMENT_DISCLOSURE_DRAFT.md`)
Prominently on the pricing/checkout page before the user enters payment
information — not buried in a ToS link only — per card-network and ROSCA
disclosure norms (see that draft).
