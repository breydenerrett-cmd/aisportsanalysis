# Launch Decisions Packet — Auth / Billing / Deployment / Domain

Prepared 2026-08-31. Scoreboard: private alpha ~2026-09-04..07, paid beta ~2026-09-10..14.
Pricing below is date-stamped from web research done today; verify at signup since several providers (Hetzner, Stripe) changed pricing mid-2026.

---

## DECISION 1 — AUTH: hosted provider vs self-managed

**WHY IT BLOCKS LAUNCH:** Alpha needs real user accounts by 2026-09-04. Auth is on the critical path for every other feature (billing needs a user identity to attach to).

**OPTIONS**
- **Clerk (hosted).** Free tier: 50,000 monthly retained users (raised from 10k in 2026). Pro $100/mo (~$85/mo annual) includes 50k MRU, $0.02/extra MRU. At alpha/beta scale (likely <1k users) this is **free**. Drop-in FastAPI-compatible via JWT verification (Clerk issues sessions, backend just verifies). Lock-in: moderate — user records live in Clerk, migration means re-authing all users.
- **Auth0 (hosted).** Free tier 25,000 MAU. Essentials (B2C) $35/mo for up to 500 MAU — so a paid tier likely kicks in near beta scale. Overage jumped 300% in 2026 to $0.07/MAU. More enterprise-y, heavier SDK, historically more integration friction than Clerk for a solo dev.
- **fastapi-users (self-managed, library on our own Postgres).** $0 direct cost — it's a library, not a service. Full control, no vendor lock-in, no per-user fees ever. Cost is Brey's time: session/JWT handling, password reset emails (needs an email-sending setup), social login (if wanted) is manual OAuth wiring. Slowest to ship of the three for a first-timer to the library.

**RECOMMENDATION:** **Clerk.** Free at this scale, least integration time before 2026-09-04, customer-portal-grade UX (MFA, social login, session mgmt) out of the box, and Auth0's overage pricing got worse this year while Clerk's free tier got better. Self-managed is the right call later if MRU costs become material or lock-in becomes a real problem — not before launch.

**WHAT HAPPENS IF NO ANSWER:** Alpha slips — no other option unblocks account creation, and building fastapi-users from scratch under time pressure risks a worse security posture than any hosted option.

**LATEST USEFUL DECISION TIME:** 2026-09-01 (need ~2-3 days to integrate + test before alpha).

---

## DECISION 2 — BILLING: Stripe (presumptive default)

**WHY IT BLOCKS LAUNCH:** Paid beta (2026-09-10..14) requires working subscriptions and a self-serve cancellation path. One-click cancellation is a named launch requirement — the sports-betting-tools category's loudest recurring complaint is billing conduct (hard-to-cancel subscriptions), so this is also a trust/positioning feature, not just plumbing.

**VERIFIED (2026)**
- Base card processing: 2.9% + $0.30 per charge (unchanged). +1.5% on cards issued outside your country. Disputes cost $15 flat, non-refundable, even if won.
- Stripe Billing (subscriptions) fee: 0.7% of subscription volume (this rose from a 0.5% promotional rate in mid-2025; confirm current rate at signup).
- **Customer Portal** (self-serve plan changes, payment method updates, and cancellation) is a built-in Stripe Billing feature — this is what delivers one-click cancellation. Free to use; a custom domain on the portal (e.g. billing.oursite.com instead of Stripe's own domain) costs +$10/mo.
- Test mode: full sandbox with test card numbers, test webhooks, and test Customer Portal — no live account needed to build and demo the entire flow.
- Account setup requires from Brey: business/individual details, bank account for payouts, ID verification (standard Stripe onboarding, usually same-day for individuals). This is the one step that needs Brey personally — API keys and integration work can happen before that's done, since Stripe issues test-mode keys instantly on signup.

**ALTERNATIVES CONSIDERED:** None materially beats Stripe for this shape (solo SaaS, subscriptions, need self-serve cancellation). Paddle/LemonSqueezy act as merchant-of-record (they handle sales tax) at a higher take rate — worth a look only if sales-tax compliance becomes a real burden later, not a launch blocker now.

**RECOMMENDATION:** Stripe. Verify the exact current Billing fee % at signup (0.7% as of this research) since it changed once already in 2026.

**WHAT HAPPENS IF NO ANSWER:** No live billing account can be created (needs Brey's identity/bank info), which blocks charging real customers — but does NOT block alpha, since Stripe test mode needs no account decision to build against.

**LATEST USEFUL DECISION TIME:** 2026-09-05 (test-mode integration can start immediately; live account activation needs a few business days before 2026-09-10 beta open).

---

## DECISION 3 — DEPLOYMENT ARCHITECTURE

**WHY IT BLOCKS LAUNCH:** The app needs to be reachable at a URL for alpha testers by 2026-09-04. Architecture doc specifies single VM + Postgres; need to confirm that still holds vs. a PaaS, and confirm Cloudflare's role.

**OPTIONS**
- **Small VM (Hetzner-class) + Cloudflare in front.** Hetzner CX-series shared vCPU starts ~€5.49-7.99/mo (price rose 1.3-3x across the board in 2026 — verify current tier price at signup). A CX with enough headroom for the engine + Postgres on the same box is realistically €15-25/mo at beta scale. Cloudflare in front (DNS, proxy/CDN, WAF, cache) is free at this scale on Cloudflare's free plan. Full control over the Python process and disk-based file storage the engine needs; most ops burden (patching, backups, monitoring) falls on Brey/us.
- **PaaS (Fly.io-class).** Fly moved off free tier in Oct 2024 — pure pay-as-you-go now. A minimal always-on app machine is ~$2-6/mo; Fly Managed Postgres starts at $38/mo (Basic, shared-2x CPU, 1GB) — a self-run Postgres on a Fly Machine instead is closer to ~$2-5/mo but loses managed backups/HA. Realistic beta-scale total: ~$10-45/mo depending on whether managed Postgres is used. Less ops burden than raw VM (deploys, TLS, scaling primitives built in); some platform lock-in via Fly-specific config (fly.toml, Machines API).
- **Cloudflare-native (Workers + D1/R2 etc).** Assessed honestly: our engine is Python doing file-based, stateful, disk-backed work. Cloudflare Workers Python runs via Pyodide/WASM, has a real standard-library subset, but the *filesystem is ephemeral per-request* — nothing written persists across requests, and heavy scientific-computing style workloads aren't a good fit. This is a poor match for the engine itself as currently built. Cloudflare's place in the architecture is the edge layer (DNS, proxy, WAF, maybe R2 for static assets or backups) in front of a VM/PaaS — not as the compute host for the engine.

**RECOMMENDATION:** **Small VM (Hetzner-class) + Cloudflare in front**, matching the existing architecture doc. It's the cheapest option at this scale, gives full control over the file-based engine (no ephemeral-filesystem mismatch), and Cloudflare's free tier covers DNS/proxy/WAF needs with zero incremental cost. Fly is a reasonable fallback if Brey wants less server-ops overhead and is willing to pay a bit more for it — flag as a live alternative, not a rejection.

**WHAT NEEDS A BREY-OWNED ACCOUNT:** Hetzner account + payment method (VM), Cloudflare account (DNS/proxy — free tier, just needs an account), a domain registrar account (blocked on Decision 4 below).

**WHAT WE CAN PREPARE WITHOUT ANY ACCOUNT TODAY:** deploy scripts, a Containerfile/Dockerfile for the engine + Postgres, systemd unit or docker-compose for the VM, env-var layout/template (`.env.example`), Cloudflare config as code (e.g. a Terraform/API-driven DNS+WAF setup ready to apply the moment an account exists), and a Postgres backup script. None of this requires credentials.

**WHAT HAPPENS IF NO ANSWER:** Nothing ships — there is no reachable URL for alpha testers. This is the single highest-priority decision of the four.

**LATEST USEFUL DECISION TIME:** 2026-09-02 (need 1-2 days to provision, deploy, and smoke-test before alpha opens 2026-09-04).

---

## DECISION 4 — DOMAIN

**WHY IT BLOCKS LAUNCH:** Waits on the product name decision (separate, not an infra question) — but the domain purchase and DNS wiring take real time and shouldn't start the moment the name lands.

**WHAT'S PRE-PREPARABLE WITHOUT A NAME:** Cloudflare account setup (registrar-agnostic, can be created and configured before a domain exists), DNS zone template ready to populate, TLS/cert automation (Cloudflare handles this automatically once a domain is added), and a checklist of subdomains needed (app, api, billing-portal-custom-domain if used, docs).

**WHAT HAPPENS IF NO ANSWER (on the name):** Alpha can run on a bare IP or a Cloudflare-provided/temporary subdomain if needed as a stopgap — not ideal, but not a hard blocker for the 2026-09-04..07 alpha window. It **does** block a clean, shareable beta launch by 2026-09-10, since a real domain matters more once paying customers are involved.

**LATEST USEFUL DECISION TIME:** 2026-09-06 (need a few days for DNS propagation + Cloudflare setup before beta).

---

## WHAT WE PREPARE WITHOUT WAITING (no accounts, no purchases, no credentials)

These proceed now regardless of Brey's answers above:

1. Containerfile/Dockerfile for the FastAPI engine + Postgres, sized for a small VM.
2. Deploy scripts (provision, deploy, rollback) written against Hetzner-class + Fly-class targets generically, so either Decision 3 outcome is a small config swap, not a rewrite.
3. `.env.example` covering auth (Clerk-style env vars), billing (Stripe test keys), DB connection, and Cloudflare-related vars — all placeholders, no real values.
4. Stripe test-mode integration (subscriptions + Customer Portal) built and tested against Stripe's sandbox — ships the moment a live account exists, no code changes needed.
5. Clerk integration built against Clerk's free-tier dev instance — same story, swaps to Brey's production Clerk org when created.
6. Cloudflare DNS/WAF config as code, ready to apply the moment both a Cloudflare account and a domain exist.
7. Postgres backup script.

None of this creates an account, spends money, or stores a credential.

---

## Sources

- [Clerk Pricing 2026 — costbench](https://costbench.com/software/developer-tools/clerk/)
- [Auth0 Pricing 2026 — costbench](https://costbench.com/software/identity-access-management/auth0/)
- [Auth0 hidden costs — costbench](https://costbench.com/software/identity-access-management/auth0/hidden-costs/)
- [Stripe pricing breakdown 2026 — Flexprice](https://flexprice.io/blog/stripe-pricing-breakdown-2026)
- [Stripe fees 2026 update — Host Merchant Services](https://hostmerchantservices.com/articles/stripe-fees-year-update-a-complete-pricing-guide-to-stripe/)
- [Hetzner Cloud price increases 2026 — Northflank](https://northflank.com/blog/hetzner-cloud-server-price-increases)
- [Hetzner pricing 2026 — cloudprice](https://cloudprice.app/providers/hetzner)
- [Fly.io pricing 2026 — costbench](https://costbench.com/software/developer-tools/flyio/)
- [Fly Managed Postgres docs](https://fly.io/docs/mpg/)
- [Cloudflare Python Workers stdlib docs](https://developers.cloudflare.com/workers/languages/python/stdlib/)
- [Cloudflare Python Workers advancements — Cloudflare Blog](https://blog.cloudflare.com/python-workers-advancements/)


## DECIDED BY BREY — 2026-09-01

1. AUTH: Clerk is the production direction. Invite-token auth stays as the
   temporary fallback/dev path. Implication: get_current_user goes behind an
   AuthProvider seam now; ClerkProvider lands key-less until credentials.
2. BILLING: Stripe. Everything built/tested in test mode behind the existing
   BillingProvider abstraction; Brey connects the account exactly when real
   credentials are required (that moment goes to the Brey queue).
3. HOSTING: do NOT wait on branding/domain. Prepare a temporary
   preview/staging deploy on the recommended architecture; the deploy itself
   still requires a hosting credential, which is the trigger to go back to
   Brey. Secure secret requirements for APP_ADMIN_TOKEN/APP_DB_PATH are to be
   generated/documented; secrets never committed. Real domain after naming.
4. LEGAL: temporary, clearly-labeled beta disclaimer now (information/
   research product, no outcome/profit guarantees, users responsible for
   their own wagering decisions). FINAL customer-facing legal copy is flagged
   for Brey/counsel review before paid/public launch.

Return-to-Brey triggers only: actual account credentials, spend,
irreversible decisions, final legal sign-off.

## Decision (2026-09-01, Brey, final): cancellation = stop future renewal

A customer who cancels KEEPS paid access through the end of the billing
period they already paid for. At `current_period_end`, paid entitlement is
revoked unless the subscription was renewed/reactivated. Cancel is never an
immediate lockout -- they paid for the month, they get the month.

Implementation notes for the engineering lane (Parent):
- Today `api/auth.py` checks only token validity -- a canceled subscriber
  keeps access FOREVER, not just to period end (verified live on staging
  2026-09-01: post-cancel `/billing/status` = canceled, `/today` still 200).
  The gap to close is the "after period end" half, and only that half.
- Stripe's `customer.subscription.updated`/`deleted` webhooks carry
  `current_period_end`; persist it on the local subscription record
  (src/appstate/customers.py) and gate paid routes on
  `status == active OR now < current_period_end`.
- Needs regression tests pinning BOTH halves: canceled-but-inside-period
  keeps access; canceled-and-past-period is refused with an honest
  "subscription ended" response, never a generic 401.

This removes the item from the decision queue -- it is now ordinary
engineering work.
