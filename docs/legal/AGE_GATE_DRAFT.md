# DRAFT — NOT LEGAL ADVICE — REQUIRES COUNSEL REVIEW

Prepared 2026-09-01. **Current live-copy gap**: as of this pass, neither
`web/landing.html`, `api/signup.py`, nor `src/analysis/disclaimers.py`'s
`BETA_DISCLAIMER` presents an actual age-gate checkbox or blocking control
— the beta disclaimer text mentions "21+ in most U.S. states" descriptively,
but nothing on the signup path requires the user to affirm their age before
proceeding. This is the single clearest immediate gap found in this task
(see report-back).

## Why 21+, not 18+
Some states permit sports wagering at 18+; 21+ is the conservative,
uniform floor used across most legal-wagering states and by most licensed
operators. Using a single uniform 21+ gate avoids building and maintaining
a state-by-state age matrix before the product has any location
verification at all. **[COUNSEL: confirm 21+ uniform is the right call
versus a jurisdiction-aware minimum, and whether a stated-age checkbox
(no ID verification) is sufficient for an information-only, non-wagering
product, or whether a higher bar is advisable given the subject matter.]**

## Age-gate copy (draft)

**Signup / checkout — blocking, must be affirmatively checked, not
pre-checked:**
> [ ] I confirm I am 21 years of age or older and located where accessing
> sports-betting information services is lawful.

**Landing page footer — persistent, non-blocking:**
> Linehound is intended for users 21+ located where sports-wagering
> information services are lawfully accessible. Sports wagering itself is
> not legal in every U.S. state — see [state availability].

## Where it must appear
1. **Signup form** (`api/signup.py` / its future UI) — a required,
   affirmatively-checked checkbox before the POST that creates the account
   or starts Stripe Checkout. Currently absent — no age field exists in the
   signup payload today.
2. **Landing page footer** (`web/landing.html`) — persistent text, every
   page load, not just signup. Currently absent — the landing page's
   footer (`site-footer`, line ~492) has no age statement.
3. **Checkout page itself**, adjacent to the recurring-billing disclosure
   (see `PAYMENT_DISCLOSURE_DRAFT.md`), since this is the point of actual
   payment.

## Implementation note (not this task's boundary to fix)
`docs/LEGAL_COMPLIANCE_RESEARCH.md` §5 item 2 flags that nothing in
`src/appstate/` verifies state of residence today — a checkbox is a stated
eligibility condition, not location verification. Whether that's sufficient
or geofencing is expected is an open counsel question, not resolved here.

## Vocabulary/consistency check
No banned vocabulary risk in this copy (no EV/edge/guarantee claims). Keep
identical wording between the ToS eligibility clause (§3 of
`TERMS_OF_SERVICE_DRAFT.md`) and this checkbox text so they don't drift.
