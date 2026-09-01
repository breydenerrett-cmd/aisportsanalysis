# DRAFT — NOT LEGAL ADVICE — REQUIRES COUNSEL REVIEW

Prepared 2026-09-01. This product is not a licensed wagering operator, so no
statute reviewed in `docs/LEGAL_COMPLIANCE_RESEARCH.md` §2.3 was found to
*require* responsible-gambling messaging from an information service — we
include it anyway as a credibility differentiator consistent with the
product's sample-size-honesty positioning, and as a reasonable precaution
given the subject matter.

## IMPORTANT — helpline number is unresolved, do not hard-code yet
`docs/LEGAL_COMPLIANCE_RESEARCH.md` §2.3 found the National Council on
Problem Gambling's own 2025 statement describing "1-800-GAMBLER" as under
threat/transition, with operations reportedly moving toward
"1-800-MY-RESET" ([NCPG statement](https://www.ncpgambling.org/news/ncpg-statement-on-national-access-to-1-800-gambler/),
accessed 2026-09-01). **Confirm the current correct number directly with
NCPG or counsel before this disclosure ships anywhere** — this draft uses a
placeholder, not the answer.

---

## RESPONSIBLE GAMBLING DISCLOSURE (DRAFT)

> Linehound is an analysis tool, not a sportsbook and not gambling advice.
> We show you public odds, price comparisons, and evidence-labeled
> context — nothing here decides for you, and nothing here guarantees an
> outcome or a profit. Bet only what you can afford to lose.
>
> If gambling is causing you or someone you know problems, help is
> available:
> - **National Problem Gambling Helpline:** [1-800-GAMBLER — CONFIRM
>   CURRENT NUMBER, see note above] · [ncpgambling.org](https://www.ncpgambling.org)
> - Text or chat support and state-specific resources are listed at the
>   National Council on Problem Gambling's site.
>
> You must be [21+] to use this service. Sports wagering is not legal in
> every state — see our [state availability notice] before assuming
> wagering itself is legal where you are.

### Placement
- Site-wide footer (every page, not just the landing page).
- Signup / checkout flow, adjacent to the age-gate checkbox
  (`AGE_GATE_DRAFT.md`).
- Alongside any "Before you fire" / Bet Check output — the moment closest
  to an actual wagering decision is the highest-value placement for this
  message, not just a footer afterthought.

### Vocabulary check (must hold in every surface this appears)
Consistent with `tests/test_customer_language.py`'s rules already enforced
elsewhere in this codebase: "guarantee" appears only negated ("does not
guarantee..."), no "edge," no "lock," no implied win probability. This
disclosure should read as an honesty signal, not boilerplate bolted on
after the fact.

### Open item for counsel
Confirm whether any state where the product will be marketed imposes
*additional* required RG-disclosure wording on non-operator information
services specifically (not found in this research pass — see
`docs/LEGAL_COMPLIANCE_RESEARCH.md` §1.2 general note).
