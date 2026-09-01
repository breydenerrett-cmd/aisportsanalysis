# DRAFT — NOT LEGAL ADVICE — REQUIRES COUNSEL REVIEW

Prepared 2026-09-01, builds on `docs/LEGAL_COMPLIANCE_RESEARCH.md` §4.2.
Data inventory below is read directly from the modules named, not assumed.

## What we actually collect today (verified by reading the code)

- **Email** — `api/signup.py` + `src/appstate/users.py`: `users(id, email,
  created_at, status, plan)`. Stored in plaintext (it is the account
  identifier). Signup is rate-limited (10/hour/IP); no other personal field
  is collected at signup — no name, no phone, no address.
- **Billing identifiers** — `src/appstate/customers.py`: a local mapping of
  `user_id` to a Stripe customer/subscription ID and status string only.
  **No card data** — per `src/appstate/billing.py`'s own docstring, this
  app "only ever sees a checkout URL, a subscription id, and a status
  string." Stripe's hosted Checkout/Customer Portal handles all
  payment-instrument data.
- **Product-usage analytics** — `src/appstate/events.py`: events keyed on
  `sha256(user_id)`, never the raw ID; documented to exclude email, raw
  auth tokens, and bet amounts/stakes from any event's payload.
- **Saved bets** — `src/appstate/savedbets.py`: append-only, soft-delete
  records of what a user chose to save, including an evidence-snapshot
  fingerprint. No stake/wager amount is stored.
- **Server request logs** — `src/appstate/reqlog.py`: technical metadata
  (route, timing, status) keyed to a hashed identifier; never email,
  bearer token, or request/response body content.
- **Rate-limit counters** — `src/appstate/ratelimit.py`: fixed-window
  counters. [Verify the key shape — hashed user id vs. IP — before
  publishing.]

## What we do not collect (today)
- No payment card data of any kind (Stripe holds it).
- No wager-execution or stake data — the product never places or executes
  a bet, so none exists to collect.
- No affiliate-link tracking (no affiliate program runs today).

---

## PRIVACY POLICY (DRAFT)

**Last updated:** [DATE]

### 1. What we collect
- Your account email address, at signup.
- Bets you choose to save ("My Bets"): the pick, price, and evidence
  snapshot at the time you saved it. Kept even after you delete them from
  your view (soft-delete) for [retention period — TBD, see §5].
- Billing: a Stripe customer ID and subscription status only. We never see
  or store your card number, CVV, or other payment details.
- Product-usage analytics: page views and feature-usage events, keyed to a
  one-way hashed version of your account ID.
- Server request logs: technical request metadata, keyed the same way.

### 2. How we use it
To operate the service, respond to support requests, improve the product
using aggregated/hashed analytics, and comply with law. [COUNSEL: standard
purposes list.]

### 3. Third parties
- **Stripe** (payment processing) — see Stripe's own privacy policy.
- [Hosting/infrastructure provider — TBD, pending an infra decision.]
- [Auth provider — TBD, pending an auth-integration decision.]
We do not sell your personal information.

### 4. Data retention
- Saved bets: retained after user-facing deletion (soft-delete) — [COUNSEL/
  BREY: state an actual retention/purge period; none is specified in code
  today, which stores rows indefinitely by default].
- Analytics and request-log data: [retention period — TBD, not currently
  specified in code].

### 5. Your rights / deletion requests
You may request deletion of your account and associated data by contacting
[support email — TBD]. [COUNSEL: confirm which state privacy statutes
apply (CCPA/CPRA and any others) given a US-nationwide subscriber base, and
what specific rights language (access, deletion, opt-out of sale — though
none occurs, correction) each requires.] We do not sell personal
information, so no "opt-out of sale" mechanism is currently required, but
counsel should confirm this holds under every applicable state law.

### 6. Children
This service is not directed to children and is not knowingly used by
anyone under [18/21 — align with the ToS eligibility age].

### 7. Security
[Standard: reasonable technical/organizational measures language —
counsel/eng to align wording with what's actually implemented, not
boilerplate that overclaims.]

### 8. Changes to this policy
[Standard notice-of-change language.]

### 9. Contact
[Privacy contact email — does not exist publicly yet; must be created
before this policy is published.]

---

### Open items for counsel (from `docs/LEGAL_COMPLIANCE_RESEARCH.md` §5)
- Data retention periods are currently undefined in code and must be set
  before publication.
- Which state privacy statutes actually apply given anticipated subscriber
  geography.
