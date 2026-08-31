# Commercial readiness ladder (2026-08-31)

Five stages from today's static generator to a public paid product:
PRIVATE ALPHA → FRIEND/TESTER ALPHA → CLOSED BETA → PAID BETA → PUBLIC V1.
This is the checklist the SaaS build is measured against. It is specific to
this project's actual state — read alongside `docs/PRODUCT_ARCHITECTURE_AUDIT.md`
(nothing deployable exists today), `docs/SAAS_APPLICATION_ARCHITECTURE.md` (the
planned `api/` layer and contracts), and
`docs/COMPETITIVE_INTELLIGENCE/{CHECKPOINT,PRICING}.md` (billing conduct is the
loudest complaint in the category; transparency is unearned until it ships in
the product, not `docs/`).

---

## Standing rules — true at every stage, not stage-specific

These are not requirements of any one rung. They hold from PRIVATE ALPHA
through PUBLIC V1 and do not relax as the ladder climbs.

1. **The Ranker never publishes picks while Engine 2 is gated.** `ENGINE2 =
   None` today (`src/report/ranker.py`); `tests/test_ranker.py` pins that the
   rendered page contains no recommendation, no pick, no unit size, no "edge"
   language. This holds through every stage below, including PUBLIC V1 and
   including under commercial pressure to produce picks. The gate changes by a
   reviewed code diff that fails a test until the evidence exists — never a
   config value, environment variable, database row, or admin toggle
   (`SAAS_APPLICATION_ARCHITECTURE.md` §8.1).
2. **Price improvement is never sold as EV.** `prices.LABEL` rides on every
   returned price object; forbidden field/word list: `ev`, `expected_value`,
   `edge`, `roi`, bare `value`, "expected value" outside a negation. Applies to
   field names, UI copy, marketing copy, and support scripts alike.
3. **Evidence labels and sample sizes reach the customer from the FIRST
   alpha.** The competitive checkpoint's core finding is that transparency
   unshipped is transparency nonexistent — "our honesty lives in a static HTML
   page and a pile of markdown... today our honesty lives in a static HTML
   page and a pile of markdown. That gap is the work" (`CHECKPOINT.md`). PRIVATE
   ALPHA is not exempt from this: even the single tester sees the evidence
   ladder and sample sizes, not a promise that they'll appear later.
4. **Billing conduct is a feature.** Billing/cancellation complaints are "the
   loudest complaint in the corpus and it is not about product quality at
   all" (`CHECKPOINT.md`). Trivial cancellation (one click, no retention
   flow, no phone call, no "are you sure" loop that hides the button), no
   dark patterns, a visible refund stance — required wherever billing exists
   (PAID BETA onward), and the *policy* should be written and shown to users
   before then.
5. **No real-money bet placement capability, ever, at any stage.** No
   "place bet" button, no sportsbook API integration that executes a wager,
   no staking calculator behind auth (`src/core/staking.py` stays
   internal-only per the architecture doc §6). This is permanent, not a
   later-stage feature.
6. **A demonstrated predictive edge is not a prerequisite for charging.**
   Brey's explicit position: current research status is zero demonstrated
   predictive edges (25+ pre-registered hypotheses, all published, all null
   or debunked — `COMMAND_CENTER.md`), and that is not a blocker to PAID BETA
   or PUBLIC V1. The product being sold is honest decision support (evidence
   labels, sample-size discipline, price improvement, contradicting evidence,
   published methodology) — not a promise of profit. **What remains gated
   regardless of pricing: any claim ABOUT an edge.** No marketing copy, in-app
   copy, or support response may assert or imply a demonstrated edge exists
   until the research rules (`ROADMAP.md` Stages 4-7, the hard approval
   gates) actually clear it. Charging money is fine; claiming an edge to
   justify the charge is not.

---

## Stage 1 — PRIVATE ALPHA

**Population:** Brey only, or Brey plus one or two people he personally
invites and personally onboards (no self-serve signup exists or is needed).

**Entry criteria (what must exist and be true before this stage opens):**
- A running `api/` service per `SAAS_APPLICATION_ARCHITECTURE.md` §5 serving
  at minimum `get_slate`, `get_game`, `get_evidence_labels`, exposed on a URL
  reachable outside the container — even a bare VM with no domain is
  sufficient. The static-file `file://` product does not satisfy this stage;
  "reachable by a person who is not sitting at this container's filesystem"
  (`PRODUCT_ARCHITECTURE_AUDIT.md`) is the bar.
- Phase 0 + Phase 1 extractions from `SAAS_APPLICATION_ARCHITECTURE.md` §9
  done: evidence-label vocabulary unified, synthesis always populated by the
  domain (not the renderer), the standing disclaimer sourced from one place.
  Shipping the API before this is done risks the exact failure the audit
  names as the biggest risk in the whole transition — "a more confident, less
  honest product than the static page it replaces."
- The evidence ladder, sample-size-with-every-claim rule, and the
  never-called-EV price label are enforced in the API response shape itself
  (Pydantic models per §4), not left to a renderer's discretion.
- No auth needed yet — a shared unlisted URL or IP allowlist is fine.

**What is measured:** whether the API-served product (not the static HTML)
actually carries every honesty guarantee the static generator had. Success =
Brey can find no claim in the served product that lacks its sample size or
evidence label. Failure = any numeric claim rendered bare.

**Deliberately absent:** accounts, payments, subscriptions, onboarding flow,
mobile layout, support channel (Brey is the only user and the only support
path), retention loop, any marketing surface.

**Reliability bar:** breaks acceptably — the service can go down, a stale
slate can render, a job can fail silently as long as Brey notices (this is
also where the manifest/freshness table from §5.5 gets its first real test).
Not acceptable: the honesty rules failing silently (a claim rendering without
its label) — that is a correctness bug, not a reliability one, and blocks
promotion regardless of uptime.

**Data-coverage bar:** whatever the engine covers today (MLB only, one
sport). No expansion required.

**Support model:** none — Brey debugs it himself.

**Exit criteria to Stage 2:** the API has run for long enough (days, not
hours) that a full slate cycle (precomputed slate → price board → what-changed
→ archive) has been observed to serve correctly at least once without a human
regenerating anything by hand. The import-graph test (`api/` cannot reach
`src.evolab`, `src.research`, `src.model`, `src.pipeline.health`, etc.) is
green. The Engine-2/no-recommendation schema test exists and is green.

---

## Stage 2 — FRIEND/TESTER ALPHA

**Population:** a small, personally-invited group (roughly 5-20) — friends,
acquaintances, people Brey trusts to give honest usability feedback, not
found through any public channel. No open signup; invitation is a code or a
personal link Brey sends.

**Entry criteria:**
- Everything from Stage 1, stable.
- Basic auth (even a single shared invite-code gate, or simple
  email+magic-link — does not need to be production-grade) so multiple named
  people can access without sharing one raw URL. Per-user state is not
  required yet, but the system must be able to tell testers apart in logs and
  feedback so a bug report can be traced.
- A minimal usable UI exists — per `SAAS_APPLICATION_ARCHITECTURE.md` Layer
  3, consuming the API only. It does not need final visual design (name/brand
  are explicitly unresolved per `ROADMAP.md` — "no product UI implementation
  until PRODUCT_DESIGN_HANDOFF.md... can be reviewed"), but it must render the
  evidence ladder, sample sizes, and the standing disclaimer visibly, not just
  correctly in the JSON.
- A feedback channel exists (a form, a shared doc, a Slack channel — anything
  Brey can read without asking each tester individually).

**What is measured:** usability and comprehension, not conversion. Do testers
understand what "Tested — no edge" means without being told? Do they
understand the price-improvement column is not a prediction? Does the "no
demonstrated betting edge" headline read as honest or as a bug? Success =
testers can explain back, in their own words, what the product does and does
not claim. Failure = testers think they're being sold picks, or think the
evidence labels are marketing decoration.

**Deliberately absent:** payments, public signup, mobile-optimized layout
(a testable but not polished mobile experience is fine), retention/lifecycle
emails, a support team (Brey or one delegate handles all tester contact
directly).

**Reliability bar:** downtime is tolerable if communicated; testers are
told this is pre-release. Data gaps (a game with no lineup posted yet) must
render as an honest gap, not an error page — this is the first stage where a
stranger (relatively) is looking at the product, so an unhandled exception
reads as unprofessional in a way it didn't when only Brey was looking.

**Data-coverage bar:** one sport (MLB) is sufficient; testers should be told
this explicitly rather than discovering it.

**Support model:** Brey (or one delegate) responds personally to every
tester's feedback. No ticketing system needed.

**Exit criteria to Stage 3:** a defined minimum bar of usability feedback
collected (e.g., every tester has used it across at least one real slate) with
no unresolved confusion about what is and is not a proven claim. Any UI
confusion around the anti-EV framing or the evidence ladder must be fixed
before closed beta — this is the cheapest point in the ladder to catch a
misreading, because the audience is small and personally reachable.

---

## Stage 3 — CLOSED BETA

**Population:** a larger invited group (dozens to low hundreds), likely
recruited via a waitlist or targeted outreach rather than personal invites
one by one. Still not open to the public — access requires an invite code or
approval, even if self-requested.

**Entry criteria:**
- Final product name and brand locked (see BREY DECISION ITEMS — this stage
  cannot proceed on "Ledgerline / Quiet Signal / Coverage Grid" as
  simultaneous finalists; a domain, a public-facing name, and basic brand
  assets must exist because this is the first stage with a URL people
  discover rather than receive personally).
- Onboarding flow exists: a new user can sign up (even invite-gated),
  understand what the product is and isn't within the first screen, and
  reach a slate or an analysis without being walked through it by Brey.
  The "nothing here is a proven edge" disclaimer and the evidence-label
  legend should appear during onboarding, not be something a user has to
  find.
- Real per-user state: accounts, saved preferences at minimum. Saved
  bets/watchlists (`SAAS_APPLICATION_ARCHITECTURE.md` §5.5, §7 Layer 2) are
  good candidates here if not shipped already, but not mandatory for entry.
- Basic mobile-usable layout (does not need to be a native app or pixel
  perfect, but the product must be usable on a phone, since that's how most
  bettors check lines).
- A real (if small) support surface: a documented way to reach support that
  isn't "email Brey personally," even if Brey is still the one answering it.
- Monitoring/alerting on the scheduled jobs (`ESCALATE:` lines wired to a
  real alert channel per §5.6) — closed beta is the first stage where a
  silent data-pipeline failure (the exact failure class the 2026-08-31
  forward-evidence audit found: "a monitor that reports health is not the
  same as health") would be discovered by a customer instead of Brey.

**What is measured:** product usefulness and retention signal — do invited
users come back for more than one slate? Which surfaces (Bet Check, What
Changed, price board) get used unprompted? Usability at a larger, less
personally-coached population. Reliability under real if modest concurrent
load. Trust signal: do users bring up the evidence labels / honesty framing
unprompted as a positive, per the competitive whitespace identified in
`CHECKPOINT.md` ("sample-size skepticism... which the two leading prop tools
do not do at all")?

**Deliberately absent:** payments — closed beta remains free. No claim of a
demonstrated edge in any onboarding or marketing copy (research status is
still zero demonstrated edges; see standing rule 6). No professional/B2B
tier. No multi-sport (`ROADMAP.md` Stage 11 explicitly gated on a validated
MLB forward result).

**Reliability bar:** the product should not lose user data (accounts,
watchlists) even if a data pipeline job fails. An outage under a few hours is
tolerable with a status message; silent wrong data (a stale slate presented
as fresh, a mismatched price board) is not — the manifest/freshness field
(§5.5) must be visible to the user as a "data as of" timestamp by this stage,
not just internal.

**Data-coverage bar:** MLB only is acceptable but must be stated plainly on
the marketing/landing surface — "one sport, done honestly" is a legitimate
positioning per the pricing research (`PRICING.md`: "our one-sport plan needs
to win on something Rithmm doesn't have at that price," namely transparency,
not breadth).

**Support model:** a documented process (even a single-person one) with a
defined response-time expectation communicated to users, and a visible
cancellation/deletion path even though there's no billing yet (data
deletion requests should already work — this normalizes the billing-conduct
standard before money is involved).

**Exit criteria to Stage 4:** demonstrated retention signal (users return
across multiple slates without prompting), no open critical reliability bugs,
onboarding comprehension confirmed at this larger scale (not just the alpha
testers), and — the hard gate for this transition — **pricing locked and a
payment processor selected and integrated in test mode** before real charging
begins (see BREY DECISION ITEMS).

---

## Stage 4 — PAID BETA

**Population:** open beyond personal invites — could be the closed-beta
cohort converted, plus new signups, still likely gated by a waitlist or
limited capacity rather than fully open marketing, but real strangers can
now find and pay for the product.

**Entry criteria:**
- Payments live: a real payment processor integrated (Stripe is the
  default assumption pending Brey's decision — see BREY DECISION ITEMS),
  subscription billing working end to end including proration, plan changes,
  and — non-negotiably per standing rule 4 — **one-click cancellation with no
  retention dark pattern**, tested by someone who is not the person who built
  it.
- A written, visible refund/cancellation policy, published before the first
  real charge, not drafted after the first complaint.
- Pricing locked (see BREY DECISION ITEMS) at whatever band Brey chooses —
  the competitive research recommends $29.99/mo one-sport or $49.99-59.99/mo
  all-sport (`PRICING.md`), explicitly **not** discounted below the category
  band, since "the bands are crowded; there is no room to win on price."
- A visible, honest "here's what you get for the price" page that leads with
  the evidence/methodology framing, not with an implied edge — this is where
  standing rule 6 gets tested for real: the pricing page must never claim a
  proven edge to justify the charge.
- Billing support process defined and staffed (even part-time) — this is the
  stage where billing complaints, per the checkpoint, become an active risk
  rather than a theoretical one.
- A real (if simple) receipt/invoice and account-management page — users
  need to see what they're being charged and be able to cancel from inside
  the product without contacting support.

**What is measured:** willingness to pay, churn, and — critically, given the
competitive finding — the *absence* of billing complaints. A single
"charged after cancelling" report should be treated as a stop-ship-severity
bug, not a support ticket, given how loud that complaint is across every
competitor studied. Conversion from closed-beta free users. Customer value
signal: do paying users report the product replacing other tools/tabs (the
"10-tab problem" quoted in `CHECKPOINT.md`)?

**Deliberately absent:** aggressive growth marketing, affiliate/referral
programs, a professional/B2B tier (the evidence for that tier's requirements
doesn't exist yet — `PRICING.md` §"Professional tier (possible)" says so
directly), multi-sport expansion.

**Reliability bar:** this is the first stage where downtime has a direct
dollar cost to a paying customer. An outage during a live slate window
(pre-game, when users are checking lines) is now a real complaint, not a
beta inconvenience. A defined SLA is not required, but a defined internal
incident process is.

**Data-coverage bar:** unchanged from closed beta (MLB), but coverage gaps
(a game with no lineup, no odds from enough books) must be visibly and
honestly flagged on a page the customer is paying to see — this is exactly
what `Dossier.gaps` already does structurally; it must not regress under
commercial pressure to "always show something."

**Support model:** a real support inbox/ticketing with a stated response-time
target, and a documented escalation path for billing disputes specifically
(given the standing rule that billing conduct is a differentiator, a fast,
generous refund posture is a deliberate choice, not an afterthought).

**Exit criteria to Stage 5:** a stable, positive-retention paying cohort over
enough billing cycles to see churn honestly (at minimum two full monthly
cycles), zero unresolved billing-dark-pattern complaints, reliability
holding under real paid load, and — the gate specific to this transition —
**no open claim-of-edge violations found in a full audit of marketing copy,
onboarding copy, and support scripts** before opening to the public.

---

## Stage 5 — PUBLIC V1

**Population:** open signup, publicly marketed, no invite or waitlist gate
required (though a waitlist/soft-launch ramp is a legitimate operational
choice, not a requirement of this stage).

**Entry criteria:**
- Everything from PAID BETA proven stable across a real paying cohort.
- Public marketing surfaces (landing page, App Store/Play Store listing if
  mobile-native, any paid acquisition channel) reviewed against the same
  anti-EV, anti-edge-claim, evidence-label rules as the in-product copy —
  marketing is the most likely place for the gated claims to leak in, because
  it is written by a different process (or person) than the product copy.
- Mobile UX genuinely solid, not just usable — competitors are mobile-first
  and most of the reviewed complaint corpus comes from App Store reviews.
- A real, if lightweight, published track record or the explicit choice not
  to publish one yet, stated honestly — per `CHECKPOINT.md`, no competitor
  has a third-party-audited record; publishing even a self-graded,
  timestamped one (in the spirit of PropsBot.ai, "still self-graded" but the
  most honest found) is the differentiator this project can actually claim,
  but only once the forward ledger has enough graded selections to be
  meaningful (`ROADMAP.md` Stage 7: 300 selections is a floor).
- Scaled support (ticketing, a real response-time SLA, staffing appropriate
  to expected volume).

**What is measured:** growth, CAC/LTV, churn at scale, support load per
customer, and the public reputation signal specifically around trust/honesty
— since that is the intended differentiator, it should be tracked
deliberately (App Store review sentiment, mentions of the evidence labels,
whether "coin flip" — the standardized negative framing found across four
competitors — shows up in reviews of this product).

**Deliberately absent:** nothing structurally — this is the full product.
Multi-sport expansion remains separately gated (`ROADMAP.md` Stage 11: "BLOCKED
until MLB has a validated forward result... stay on MLB"), and a
professional/B2B tier remains a later, separately-evidenced decision.

**Reliability bar:** production-grade — the bar every SaaS is held to:
defined uptime target, incident postmortems, no data loss, tested backups.

**Data-coverage bar:** MLB, comprehensively — coverage gaps should now be rare
and clearly the exception, not routine.

**Support model:** full support operation appropriate to the paying
customer base size, with the billing-conduct standard from Stage 4 now a
publicly stated policy (visible on the pricing/cancellation page, not just
followed internally).

**Exit criteria:** none — this is the terminus of the ladder. Beyond this
point the roadmap's own stages (multi-sport, professional tier, Ranker
unlock if Engine 2 ever clears its four conditions) govern, each with its own
gate.

---

## Axis summary across the ladder

| axis | Alpha (1) | Tester Alpha (2) | Closed Beta (3) | Paid Beta (4) | Public V1 (5) |
|---|---|---|---|---|---|
| product usefulness | proven internally | tested by strangers | validated by retention | validated by willingness-to-pay | validated at scale |
| usability | Brey-only | first outside feedback | onboarding must work unaided | must convert cold | must convert at scale |
| reliability | best-effort | must not crash on strangers | data must not be silently stale | outage = real cost | production SLA |
| data coverage | MLB, whatever exists | MLB, stated plainly | MLB, gaps shown honestly | MLB, gaps shown honestly | MLB, comprehensive |
| mobile UX | none required | testable, not polished | basic usable | must be solid | must be excellent |
| subscriptions | none | none | none (pricing locked, not charged) | live, one-click cancel | live, publicly stated policy |
| onboarding | none (personal walkthrough) | minimal | must work unaided | must convert | must convert at scale |
| retention loop | n/a | first signal | must show real signal | must hold across cycles | sustained |
| customer value | n/a (no customers) | qualitative feedback | "10-tab problem" signal sought | willingness-to-pay proven | scaled |
| supportability | Brey debugs directly | Brey personal contact | documented, single-person OK | real inbox, billing SLA | full ops |
| performance | irrelevant | must not embarrass | must handle beta load | must handle paid load | must handle scale |
| trust | internal only | first outside read of honesty framing | must read as honest at size | billing conduct proven | public reputation tracked |

---

## BREY DECISION ITEMS

| decision | why it matters | options | recommendation | what continues without it |
|---|---|---|---|---|
| **Final product name/brand** before CLOSED BETA | Closed beta is the first stage with a public-facing URL and discoverable identity; you cannot onboard strangers under three simultaneous "finalists." Domain, trademark, and App Store collision checks all depend on picking one. | Ledgerline / Quiet Signal / Coverage Grid (current finalists, none cleared per `CHECKPOINT.md`), or a new candidate | No recommendation offered here — this needs the deferred domain/trademark/App-Store/consumer-testing pass `CHECKPOINT.md` flags as unfinished, not a guess made in this doc | Stage 1 and Stage 2 (private/friend alpha) proceed unaffected — they need no public name at all |
| **Pricing lock** before PAID BETA | Charging requires a fixed number; changing price on existing subscribers mid-beta is itself a billing-trust risk given standing rule 4. | (a) $29.99/mo one-sport, $299/yr; (b) $49.99-59.99/mo all-sport (n/a until multi-sport), $499/yr; (c) something else | Lock the one-sport price at $29.99/mo per the competitive analysis, but reconsider the $299/yr annual discount (~17%, below the ~20-30% market norm) — a steeper annual (~$239-259/yr) would read as more competitive per `PRICING.md`'s own analysis. Do not launch any price while billing complaints remain the loudest category-wide signal without first publishing the cancellation/refund policy. | Closed beta continues free/unpriced; Stage 3 exit criteria explicitly requires this decision before Stage 4 opens |
| **Payment processor** before PAID BETA | Determines the entire billing integration, dispute process, and how trivially cancellation can actually be made — the standing rule (trivial cancellation, no dark patterns) has to be implementable in whatever processor is chosen. | Stripe (assumed default, strong subscription tooling, self-serve cancel support), Paddle (merchant-of-record, handles tax/VAT), or a sportsbook-adjacent payment provider (none identified/needed here) | Stripe, unless a specific tax/compliance reason favors Paddle — Stripe's native customer portal makes one-click self-serve cancellation close to free to implement correctly, which directly serves the billing-conduct standing rule | Closed beta and everything before it proceeds with no payment integration at all |
| **Hosting / domain purchase** before CLOSED BETA | A public URL, TLS, and email-sending domain (for magic links, receipts) are needed the moment invited users outnumber people Brey can hand a raw IP to. | A single small VM/managed container per `SAAS_APPLICATION_ARCHITECTURE.md` §5.6 (recommended architecture), any major cloud host, or a PaaS (Render/Fly/Railway) | A managed single-container host (Render/Fly-class) over a raw VM for Stage 1-3, to avoid ops burden before there's a team to carry it; revisit self-hosting only if cost or the file-store/git-backed-data model (§5.5) needs it | Stage 1 (private alpha) can run on an unlisted URL with no domain purchase at all |
| **Whether to publish a track record, and when** | Publishing the forward ledger (even self-graded) is the single differentiator no competitor has claimed, but publishing before it's statistically meaningful undercuts the same honesty positioning. | (a) publish at PUBLIC V1 once the forward ledger passes the 300-selection floor (`ROADMAP.md` Stage 7); (b) publish earlier, labelled explicitly as too-small-to-be-meaningful; (c) don't publish until sample is large and confident | (a) — publishing early with an honestly-labelled tiny sample risks looking like every competitor's unaudited claim; waiting for the pre-registered floor is consistent with the project's own evidence-integrity rule | Stages 1-4 proceed with the evidence-label/sample-size machinery already shipping per standing rule 3, which is the more important near-term commitment |

---

## Findings — the hardest gate on the ladder, and why

**The hardest gate is the CLOSED BETA → PAID BETA transition, specifically
the requirement that pricing, payment processor, and a written
cancellation/refund policy all lock *before* the first real charge, combined
with the standing rule that no marketing or onboarding copy may claim a
demonstrated edge.**

This is harder than every other transition because it is the first point
where two things that must never be conflated get physically close together
on the same screen: a price, and a page describing what the product does.
Every competitor studied gets this wrong in one of two ways — either the
pricing page implies an edge it cannot support (the CHECKPOINT's core
finding: "every competitor's marketing promises more — edge, sharpness,
accuracy, profit"), or the billing mechanics themselves become the source of
customer harm (the single loudest complaint in the corpus, unrelated to
product quality). This project has to clear both simultaneously, on a
product whose honest research status is *zero demonstrated predictive
edges*, while asking someone to pay money for it. There is no engineering
fix for this gate — it is a discipline gate, enforced by the schema tests
(§8.2's grep-style test for "edge"/"expected value") and by a manual copy
audit before every transition, not by anything that ships once and stays
fixed.

## Risks

- **Engine 2 pressure compounds exactly at PAID BETA**, per
  `SAAS_APPLICATION_ARCHITECTURE.md` §10: "a subscription product creates
  commercial pressure to produce picks." This ladder's paid stages are
  precisely where that pressure will be highest and the gate must hold hardest.
- **Marketing copy is written by a different process than product copy** and
  is the most likely leak point for a claim-of-edge violation; it needs its
  own audit step at every stage transition from Closed Beta onward, not a
  one-time review.
- **Billing conduct is easy to get right in a demo and wrong in production**
  — a "one-click cancel" button that still routes through a retention screen
  in the actual Stripe/Paddle configuration is a realistic failure mode that
  looks fine in a design review.
- **The name/brand decision is currently unresourced** (per `ROADMAP.md`, the
  domain/trademark/App-Store checks are explicitly not done) and sits on the
  Closed Beta critical path; if it slips, Closed Beta slips with it.

## Unresolved questions

- Whether Stage 3 (Closed Beta) truly needs the name/brand locked, or whether
  a beta could run under a working title with the real name landing only at
  Paid Beta — this doc assumes the stricter reading (public URL = needs a real
  name) but Brey may prefer to defer the brand decision further.
- Whether the track-record publication decision (BREY DECISION ITEMS, last
  row) should itself gate Public V1, or remain a post-launch enhancement —
  this doc treats it as optional-but-recommended-timed, not a hard gate.
- Exact minimum tester/beta-cohort sizes and cycle counts are stated as
  qualitative ("enough billing cycles to see churn honestly") rather than
  fixed numbers, since no user-volume or unit-economics model exists yet in
  the docs reviewed; a follow-up could pin these down once acquisition
  assumptions exist.
