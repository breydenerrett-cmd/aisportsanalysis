# DRAFT — NOT LEGAL ADVICE — REQUIRES COUNSEL REVIEW

Prepared 2026-09-01. The product sells **information/analysis**, sold and
accessible nationwide — it is not itself a wagering product and does not
require the recipient's state to have legal sports wagering to be lawful to
use. The risk this page manages is different: copy that reads as *implying*
wagering is legal everywhere, or that nudges a user in a no-legal-wagering
state toward illegal activity. This draft's purpose is to give Brey/counsel
wording that avoids that implication.

## States currently without legal, operating sports wagering
Per web search conducted 2026-09-01 (secondary sources, not a state-by-state
primary-statute read — verify before publishing, since this changes almost
every legislative session):

Alabama, Alaska, California, Georgia, Hawaii, Idaho, Minnesota, Oklahoma,
South Carolina, Texas, Utah.

Sources: [FOX Sports — "Sports Betting States Where It's Legal in the US
2026"](https://www.foxsports.com/stories/betting/where-is-sports-betting-legal);
[LegalSportsReport — "Sports Betting States: Latest US Legislation & Bill
Tracker"](https://www.legalsportsreport.com/sports-betting/states/) — both
accessed 2026-09-01 via search-tool synthesis, not independently opened and
read line-by-line. Georgia, Minnesota, Texas, and South Carolina reportedly
have active legislative discussion (per the same sources) and could change
status; Utah and Hawaii are described as the most durable holdouts.
**[COUNSEL: verify this list directly against a primary tracker (e.g., AGA
or a state-gaming-commission source) immediately before any publication —
an eleven-state list from search synthesis is a starting point, not a
citable fact for a live product.]**

## Copy that avoids implying wagering is legal everywhere

**Landing page / marketing, general framing:**
> Linehound provides sports-betting information and analysis. It is
> available nationwide as an information product. Sports wagering itself
> is legal in most, but not all, U.S. states — check your state's current
> law before wagering anywhere. Using Linehound does not require that
> wagering be legal in your state; wagering itself might not be.

**What NOT to write** (each of these implies something false or nudges
illegal activity):
- "Available in all 50 states" *without* the information/wagering
  distinction stated in the same breath — technically true for the
  product, misleading about wagering.
- Any state-availability map or badge styled like a sportsbook's licensed-
  states map — implies a wagering-license framing this product does not
  have and should not imply.
- Any copy suggesting a workaround for wagering from a no-legal-wagering
  state (VPNs, offshore books, etc.) — never write this, even in FAQ or
  support-macro form.

## Where this matters in the current product
The landing page (`web/landing.html`) and beta disclaimer
(`src/analysis/disclaimers.py`) currently say the product is "intended for
users of legal wagering age in their jurisdiction (21+ in most U.S.
states)" but neither states the *separate* fact that wagering itself isn't
legal everywhere. Recommend adding a short state-availability line
alongside the age-gate footer text (`AGE_GATE_DRAFT.md`) rather than a new
standalone page, so the two travel together.

## Open item for counsel
Confirm whether selling the *information* product (not wagering) to a
resident of a no-legal-wagering state carries any distinct legal exposure
beyond ordinary consumer-protection/advertising law — `docs/
LEGAL_COMPLIANCE_RESEARCH.md` §1 found no primary source resolving this for
an information-only product.
