# Referral loop — post-beta growth/retention feature (SPEC ONLY)

Recorded 2026-09-01 from Brey's directive. **Do NOT build before the
private-beta launch blockers are green.** First post-launch iteration.

## Concept

Every active paid user receives a unique referral link/code.

A referral QUALIFIES only after the referred customer:
1. creates a legitimate account,
2. becomes a paid subscriber,
3. completes their first paid month without refund/chargeback.

## Reward

- Referrer: +7 days of paid access.
- Referred customer: +7 days of paid access.
- Applied only after qualification. No cash payouts initially.

## Safeguards (initial set, all required at launch of the feature)

- No self-referrals.
- Prevent obvious duplicate-account/payment-method abuse (e.g. same
  Stripe payment fingerprint / same customer email family).
- No reward on refunded or charged-back subscriptions; a qualification
  that later reverses does not claw back time already granted unless
  fraud (Brey call at build time).
- Idempotent reward issuance (webhook retries must not double-grant).
- Annual reward cap, configurable.
- Referral attribution stored AT SIGNUP (a code seen at signup is the
  attribution of record; no retroactive attribution).
- Analytics across the chain: invite sent → signup → checkout →
  qualified referral → retention.

## Implementation notes for the eventual build

- Attribution wants a column on the signup/user record plus a
  referrals table (referrer_user_id, referred_user_id, code,
  attributed_at, qualified_at, reward_granted_at) — append-style, one
  row per referral, reward_granted_at as the idempotency marker.
- "+7 days of paid access" composes with the period-end entitlement
  model (see the entitlement work of 2026-09-01): extend the local
  entitlement horizon rather than touching the Stripe billing period,
  so Stripe invoices stay untouched and the grant is purely our
  entitlement math.
- Qualification check is driven by billing webhooks + a 30-day timer,
  not polling Stripe.
- Legal/ToS: incentive programs have platform and state wrinkles —
  include in the counsel review batch (docs/legal/COUNSEL_ACCOUNTANT_
  MATRIX.md) before enabling. docs/FIRST_CUSTOMER_GROWTH_PACKAGE.md's
  referral concept section is superseded by this spec where they differ.

## Customer-facing tone

Bettor-native, e.g.: "Put the group chat on. They stick around for a
month, you both get a week on us."
