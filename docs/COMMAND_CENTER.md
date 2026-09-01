# COMMAND CENTER

Operational snapshot. Updated by the orchestrator at every integration point.
Last update: 2026-08-31 22:30Z. Suite: 2,201 green. Credits: ~52,990.

## PAID BETA LAUNCH SCOREBOARD (day 0 = 2026-08-31)
TARGET: private alpha ~4-7d · invited alpha ~7-12d · PAID BETA ~10-18d · public V1 ~3-5wk
EARLIEST PLAUSIBLE paid beta: 2026-09-10 · CURRENT BEST ESTIMATE: 2026-09-12..14
SLIP RISKS (ranked): 1) design-cycle latency (Brey approval is one gate -- kept
to a single decision item); 2) external accounts (hosting, Stripe, auth
provider are Brey-owned purchases -- decision packet in flight); 3) FastAPI
dependency install through the egress proxy (unverified -- foundation worker
probes it today, stdlib fallback documented).

### PAID_BETA_CRITICAL_PATH (canonical; nothing enters casually)
DONE: A capability reconciliation · pricing-calculator review (calculator
respecified honestly) · extraction (renderer derives nothing) · Bet Check
domain skeleton.
DONE 22:30Z: B contracts LOCKED (Milestone 1) · C implementation plan ·
api/ foundation (FastAPI CONFIRMED through proxy -- slip risk 3 RETIRED) ·
LAUNCH_DECISIONS.md packet ready for Brey · Y banned-language tripwire live
(caught three wordings on day one, all fixed).
IN PROGRESS: D /design first artboard pass (three Graphite Terminal
directions) -- THE CRITICAL PATH IS NOW THE DESIGN GATE. Phase 2B real sweep
computing (watcher armed).
GATED ON DESIGN: D /design three directions -> E Brey approval -> F design
system -> G-M customer screens.
THEN: N auth · O user state · P billing · Q one-click cancel · R deploy ·
S monitoring · T mobile · U stale/partial UX · V security review ·
W accessibility · X billing QA · Z release check.
NOT ON THE PATH (deferred to V1+): props UI, other sports, native app,
community, sportsbook sync, Evolution Lab UI, public forward ledger, deep
personalization, full alerts, SEO/content build.

### NEXT 24H LAUNCH TASKS
1. Contracts locked (Milestone 1) -- exit: six contracts + evidence
   translation + market-semantics separation, all as code with tests.
2. Implementation plan reconciled from architecture + handoff + capability
   table.
3. api/ foundation: package boundary, dependency probe, TODAY served as
   JSON from real briefing entries (no visual work).
4. Auth/billing/deploy decision packet to Brey (accounts and spend are his).
5. /design mission brief prepared so the first artboard pass starts the
   moment contracts lock.

## PHASE LOG

- 2026-09-01 ~04:30: LAUNCH LANE STEADY STATE. Everything buildable
  without credentials is BUILT, TESTED, PUSHED: full paid funnel proven
  by 14-step funnel_smoke (in ci.sh), admin dashboard, first-customer
  playbook, brand screen (no KILL; 3 CAUTIONs for clearance), deploy one
  command from staging. Suite 2,882; ci.sh green incl. both smokes;
  evolab determinism green on clean tree. WAITING ON BREY ONLY:
  (1) Fly deploy token, (2) Stripe test key + $19.99 Price + webhook
  secret, (3) price/cohort sign-off in PRICING_OFFER_VALIDATION,
  (4) email provider (optional pre-first-customer), (5) design handback,
  (6) trademark clearance before domain. Research/capture autonomous on
  triggers; V3 accumulating below floor.

- 2026-09-01 ~03:45: Wave 5 + branding COMPLETE. Full funnel built and
  ci.sh-green: landing -> signup -> Stripe TEST checkout -> one-time
  activation token -> app -> bet check -> saved bet -> digest, every
  step instrumented, /admin/funnel reports conversions. LINEHOUND
  applied as working brand (legal copy name-neutral pending clearance;
  nothing registered). Integration caught 2 client/server contract
  mismatches + a Free-label-vs-paid-checkout inconsistency - fixed.
  LAUNCH STATE: code-complete to the credential line. Running: full-
  funnel local smoke (fake-transport, guard-locked to synthetic keys).
  BLOCKERS = BREY ONLY: Fly deploy token; Stripe test key + $19.99
  Price (display name 'Linehound (beta)') + webhook secret; email
  provider; domain/Cloudflare post-clearance. Suite 2,869.

- 2026-09-01 ~03:00: FIRST-PAID-CUSTOMER push (Brey). Approved visual
  direction: sports-broadcast (Madden/2K-familiar, no protected assets);
  design finishing separately, web/ stays the structural attach point.
  Wave 5 ACTIVE (4 + in-play investigation + capture): self-serve
  signup->Stripe TEST checkout->activation->cancellation; landing page +
  pricing route + full funnel instrumentation + /admin/funnel; deploy
  boundary (fly staging/prod tomls, runbook, Cloudflare readiness,
  backups/monitoring scripts, remote smoke); retention digest + emails +
  founding-user acquisition assets. FUNNEL: landing -> CTA -> signup ->
  plan -> checkout -> account -> onboarding -> gameday -> bet check ->
  saved bet -> digest return trigger, each step instrumented.
  BREY CREDENTIAL ASKS (only blockers): (1) Fly.io deploy token,
  (2) Stripe TEST secret key + webhook secret, (3) transactional email
  provider choice+key (digest/invite sending), (4) domain+Cloudflare
  when named. Clerk can follow later - invite/signup tokens carry beta.

- 2026-09-01 ~01:50: Wave 4 landed (bounded provider fetches + one-retry
  policy, 50-concurrent load smoke zero-5xx, structural reference client
  at /web with traversal-guarded static router, live-verified). Suite
  2,682; ci.sh green. Consolidation lane running (API_CONTRACTS
  reconciliation incl. /today mismatch + odds rows, invite_redeemed
  first-use marker, db backup notes). BACKEND IS FEATURE-COMPLETE FOR
  PRIVATE ALPHA pending: Fly deploy token, Clerk org + JWT dep, Stripe
  test key, final legal copy, and the approved design system attaching
  to web/'s documented hooks.

- 2026-09-01 ~01:20: Wave 3 fully landed (billing persistence, analytics
  + admin ops, My Bets settlement, scripts/ci.sh) - ci.sh green end to
  end (suite 2,655 + boundary/vocab gates + live authed smoke). V3 still
  below the 30-event floor (0 measurable; accumulating). Wave 4 ACTIVE
  (2): provider timeout/retry + 50-concurrent load smoke; structural
  (zero-aesthetics) reference client in web/ with design-attachment
  contract. NEXT: invite_redeemed first-use marker; What Changed digest
  job; TestClient/httpx decision; backup policy for data/app db.

- 2026-09-01 ~00:45: Backend wave 2 fully landed and integrated (odds,
  caching/freshness, contract tests+analytics scaffold, Clerk seam +
  Stripe test-mode provider, disclaimer+staging prep, hardening batch,
  game surface AUTH-GATED for alpha; smoke green end-to-end incl. authed
  flow; suite ~2,569). Wave 3 ACTIVE (3): Stripe customer mapping +
  checkout wiring; analytics wiring + admin ops endpoints; My Bets
  settlement + scripts/ci.sh. Brey queue unchanged: Fly deploy token,
  Clerk org + JWT dep approval, Stripe test key, final legal copy.

- 2026-09-01 00:xx: Backend wave 1 all landed (Bet Check API, Games/What
  Changed API, auth+user-state, outcome ceiling; suite 2,335). ACTIVE (5):
  red-team of auth/API surface (opus), deploy+monitoring groundwork,
  Odds endpoint, caching/freshness layer, contract tests + analytics
  events. NEXT 5: integrate+push the five; wire analytics events into
  endpoints; rate limiting on authed routes; admin/ops view (invite mgmt,
  event aggregates, store health); settle/grade surfacing for My Bets
  (bet outcomes vs saved bet-check snapshots); mobile payload audit vs
  API_CONTRACTS.md. LOOKAHEAD adds: TestClient-based HTTP tests once
  httpx pinning decided; provider fetch timeout/retry policy; backup
  policy for data/app db; What Changed push/digest job; pricing copy
  quant re-check against contracts; support contact endpoint; CI script
  (scripts/ci.sh: suite + smoke + grep gates); legal disclaimer text
  needs Brey/counsel (queued); load smoke (50 concurrent) before invites.
  BREY QUEUE (blocking only their own items): auth provider, Stripe,
  hosting+domain+secrets, legal disclaimer sign-off. V3 still time-gated;
  capture on triggers.

- 2026-08-31 night: Brey archived the design exploration (moved to a Claude
  Design web session) and ordered full speed on paid-beta foundations. Lanes
  dispatched: Bet Check API, Today/Game API slice, auth/user-state
  scaffolding (provider-agnostic, no registrations), outcome-ceiling wiring.

- 2026-08-31 late: Phase 2B adjudicated + published (BELOW_PLACEBO_CEILING
  stands; SPA disagreement diagnosed as shared board drift, provenance in
  data/research/evolab/drift-measurement-20260831.json). Design review package
  restructured per Brey's correction: per-direction pages with seven full-size
  views each + Bet Check comparison page; republished to the same artifact.
Last update: 2026-08-31 21:20Z. Suite: 1,959 green. Credits: ~53,000.

## PROJECT PHASE CHANGE (21:35Z)
PRODUCT_DESIGN_HANDOFF.md has ARRIVED (docs/, 2,711 lines, browser-verified
competitor research, full page specs, capability labels). The SaaS pipeline is
now: capability reconciliation -> domain contracts -> /design artboards (three
Graphite Terminal directions) -> BREY VISUAL APPROVAL -> design system ->
Sonnet implementation -> QA -> paid beta. The /design gate blocks ONLY final
customer visual implementation; research and backend continue.

## ACTIVE NOW
| task | lane | model | state |
|---|---|---|---|
| Evolab Phase 1 replay engine (WorldView, leakage-proof) | C | Opus | in flight |
| Hourly capture + first F5 close night at cap 8 | G | script | running |
| Wave 2 (below) | multiple | Sonnet | launching |

## WAVE 2 — LAUNCHING NOW
1. Evolab Phase 2B sweep driver (script + module; runs when replay lands) — C
2. Dashboard business-logic extraction into domain layer (pre-API, per
   SAAS_APPLICATION_ARCHITECTURE §2) — B/P
3. Bet Check domain logic (parse bet string, partition evidence for/against;
   engine only, no UI) — A/B
4. Season-end / off-season capture posture design (late September is close) — G/N
5. CI: honest competitor scorecard (us vs them) + customer personas — I/L

## NEXT 5 (promoted as slots free)
6. API contract structures as stdlib dataclasses in the domain layer — P
7. Evolab autopsy/death-taxonomy reporting over fitness tables — C
8. Multi-sport hardcoding audit (what assumes MLB, docs only) — M
9. Commercial-readiness ladder doc (alpha → beta → paid, requirements per
   stage) — Q
10. Reddit + screenshot research re-run when an unblocked environment exists — I

## READY QUEUE / LOOKAHEAD (10–20)
11. Phase 2B real sweep + 50 placebo worlds + PBO report (after 1+ land) — C
12. Evolab result adjudication vs the stated prior (Fable-level) — C
13. Bet Debunker domain logic (challenge a stated stat's sample/meaning) — A
14. "Why did this line move" assembly (event timeline vs book responses;
    uses eventstudy + relevance) — A/D
15. F5 forward-series review (~2 weeks of closes required; first rows land
    tonight) — E
16. V3 first class-floor analysis (lineup_posted at 18/30 and mapping as
    games settle) — D
17. Prop-listing audit steady state → C1 registration decision packet for
    Brey when listing-time data suffices — F
18. SaaS implementation plan (BLOCKED: needs PRODUCT_DESIGN_HANDOFF.md) — A/P
19. Auth/subscription groundwork per architecture doc (after 18) — R
20. Performance profile of brief/analyze paths under API load shapes — O

## TIME-GATED
- V3 floors (30/class; lineup_posted 18, transactions 20-but-legacy) — days-weeks
- F5 series review — ~2 weeks of closes
- Season end — late September
- Forward ledger 300+ selections — months

## NEEDS BREY (decision queue)
| decision | options | recommendation | continues without it |
|---|---|---|---|
| none currently open | — | — | everything |
(Cleared today: 2024 sandbox ✓, prop audit ✓, F5 cap 8 ✓, news-speed rejection ✓.)

## SHIPPED TODAY (2026-08-31)
Forward-evidence rescue (gitignored odds stores; tracked now) · F5 close pass
0→15/15 with identity-matched miss detection, cap 8 · V3 mappability repair ·
health-monitor truth · results-store holes · bootstrap determinism (M4 errata) ·
probable-pitcher PIT audit · Evolab: Phase 0 audit, Phase 2A (features carry no
linear info beyond the close), core (11,088 genomes/51ms), stats (validated
both directions; P4 reclassified) · prop-listing audit live (7 books, 4 credits)
· competitive intelligence: 17 products, matrix, pricing, pain, naming,
X-feasibility, checkpoint · product architecture audit + SaaS boundary plan ·
evidence-vocabulary unification · V2 + V4 reproducibility audits exact.

## BIGGEST BOTTLENECK
**No deployable product.** The analysis, honesty machinery and evidence all
exist and are tested; nothing makes them reachable by a customer. Design
handoff is being produced in a separate session; engine-side preparation
(extractions, contracts, Bet Check domain logic) proceeds now so the build
phase starts fast.

## CURRENT PRODUCT STATUS
Static generator, test-enforced honest, no server/auth/payments yet.
Architecture plan ready (FastAPI + Pydantic, api/ package, src/ stays stdlib).
VISUAL DESIGN MOVED TO A SEPARATE CLAUDE DESIGN SESSION (Brey, 2026-08-31):
design/directions-v1 and the A/B/C review deck are ARCHIVED EXPLORATION, not
an approved direction. No further mockups/exports/art direction here. Brey
returns with the approved visual system. Frontend stays structurally ready
(contracts -> JSON payloads -> template slots) with NO aesthetic decisions.
Full speed on: contracts, API/backend, auth, billing, deployment, user state,
Bet Check logic, Today/Game/Odds/What Changed functionality, tests,
monitoring, research.

## CURRENT RESEARCH STATUS
Zero demonstrated predictive edges (25+ prereg hypotheses, all published).
Phase 2A: no linear information beyond the close. Phase 2B REAL RUN COMPLETE:
BELOW_PLACEBO_CEILING (prior held) — per the kill rule, evolution does not get
built; replay engine + noise-ceiling harness are permanent instruments
(docs/EVOLAB_PHASE2B_RESULTS.md). Research capacity shifts to F5, props
feasibility, V3 timing, forward evidence. Live lanes: V3 timing (accumulating), F5 depth (first
closes tonight), prop listing (feasibility). Sealed 2026 untouched; 2025
tuning-only.
