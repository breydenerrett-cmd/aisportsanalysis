# DRAFT — NOT LEGAL ADVICE — REQUIRES COUNSEL REVIEW

Prepared 2026-09-01. Purpose: one table so Brey knows exactly what to buy
review for before PAID PUBLIC launch, and what can wait behind the
temporary beta disclaimer (`src/analysis/disclaimers.py`, `id="beta-v1"`,
`requires_final_legal_review=True`). "PAID PUBLIC launch" = the point this
stops being a small, disclosed beta and becomes a generally-marketed paid
product (`docs/COMMERCIAL_READINESS.md` Stage 5 / Public V1).

| # | Item | Draft location | Safe as beta placeholder now? | Must have counsel before PAID PUBLIC launch? | Accountant / tax question? |
|---|---|---|---|---|---|
| 1 | Terms of Service | `TERMS_OF_SERVICE_DRAFT.md` | Partial — the existing `BETA_DISCLAIMER` covers no-guarantee/no-edge/user-responsibility today; a full ToS (liability cap, arbitration, DMCA) is not yet published anywhere and isn't required for closed/free beta | **Yes** — liability limitation, arbitration/venue decision, and DMCA agent registration all need counsel sign-off before real money and real users both exist at scale | No |
| 2 | Privacy Policy | `PRIVACY_POLICY_DRAFT.md` | Yes for closed beta (small, known cohort) — but retention periods must be decided before any *paid* user's data accumulates indefinitely | **Yes** — state privacy statute applicability (CCPA/CPRA and others) and a defined retention/deletion policy before nationwide paid marketing | No |
| 3 | Responsible-gambling disclosure | `RESPONSIBLE_GAMBLING_DISCLOSURE_DRAFT.md` | Yes, once the correct helpline number is confirmed (currently unresolved — do not hard-code 1-800-GAMBLER without checking) | No statute found requiring this of a non-operator information service, but confirm nothing state-specific applies before nationwide marketing | No |
| 4 | 21+ age-gate wording + placement | `AGE_GATE_DRAFT.md` | **No** — this is the clearest live gap found (see report-back): no age checkbox exists on signup today, and the landing page footer has no age statement | **Yes** — confirm 21+ vs. jurisdiction-aware minimum, and whether a checkbox is sufficient without location verification | No |
| 5 | State-availability wording | `STATE_AVAILABILITY_DRAFT.md` | Yes as a beta placeholder, but the 11-state "no legal wagering" list is search-synthesis only and must be verified against a primary tracker before it's published anywhere | **Yes** — verify the state list directly, and confirm no distinct exposure from selling the information product into a no-legal-wagering state | No |
| 6 | Refund/cancellation language | `REFUND_CANCELLATION_DRAFT.md` | Cancellation half (period-end access, no retention flow) is settled and safe now; **refund posture is an open BREY DECISION**, not a counsel question, but must be decided before the first real Stripe charge | Counsel should sanity-check the chosen option's wording, not choose it | **Yes** — refund liability/revenue recognition treatment (especially if option (c), pro-rated refunds, is chosen) is an accountant question, not a legal one |
| 7 | Payment disclosure (checkout requirements) | `PAYMENT_DISCLOSURE_DRAFT.md` | **No** — a transactional confirmation email is required by card-network rules and doesn't exist yet (`api/signup.py`: no email sender wired in); this is a launch blocker, not a placeholder-acceptable gap, once real charges start | **Yes** — ROSCA/card-network compliance must be counsel-reviewed before the first real (non-test) Stripe charge, and the FTC's reopened negative-option rulemaking (March 2026) should be tracked | Possibly — confirm Stripe fee/tax handling (see #8) |
| 8 | Sales tax / digital-goods tax on the subscription | Not drafted — outside this task's legal-doc scope, flagged here because it surfaced in review | N/A | N/A | **Yes — unaddressed.** Whether a $19.99/mo SaaS-style information subscription owes sales/use tax in any state (several states tax digital subscriptions; rules vary widely) has not been researched in this pass at all. Flag as a standalone accountant task before PAID PUBLIC launch. |
| 9 | DMCA designated-agent registration | `TERMS_OF_SERVICE_DRAFT.md` §7 | Yes, beta placeholder fine — the DMCA clause has no legal effect until an agent is registered, so it's just inert text until then | **Yes** — must be registered with the U.S. Copyright Office before that ToS clause is meaningful | No |
| 10 | Business entity / classification as "information service, not gambling operator" | `docs/LEGAL_COMPLIANCE_RESEARCH.md` §1 | Yes to continue operating as-is at small beta scale — no capability exists today that crosses into wagering/prize/stake handling | **Yes — the single highest-priority item.** No primary statute or case law confirming an "information service" carve-out was found in this research pass; this is the foundational classification everything else assumes | Possibly — entity structure/liability-shield choice (LLC vs. other) is worth an accountant's input alongside counsel's |

## Net read (≤10 lines, for the report-back)
Ten items; three are genuine gaps in the *live* product today (age gate
missing entirely, no confirmed RG helpline number, no transactional email
for the required billing confirmations) and should be treated as launch
blockers, not counsel-review items, since they're implementation gaps, not
judgment calls. Two items are pure BREY decisions (refund posture,
arbitration clause) that counsel should review but not originate. One item
(sales tax on the subscription) was not researched at all in this pass and
needs a standalone accountant engagement. The single highest-priority
counsel question remains the foundational one from
`docs/LEGAL_COMPLIANCE_RESEARCH.md`: no primary source confirms the
"information service, not gambling operator" classification holds in every
state — everything else in this matrix assumes it does.
