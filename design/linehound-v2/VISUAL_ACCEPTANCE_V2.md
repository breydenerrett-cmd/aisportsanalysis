# V2 visual acceptance record

Per IMPLEMENTATION_PLAN.md "Visual-acceptance protocol": the orchestrator
places the implementer's screenshot beside the frozen artboard and records
an explicit VISUAL PASS or VISUAL FAIL. No screen is marked complete in any
status doc without a row here. Screenshots referenced live in the session
scratchpad and are not committed; the grade and its reasons are the record.

| Artboard | Screen / module | Viewport | Grade | Date | Notes |
|---|---|---|---|---|---|
| V2-02 | Odds, three board variants (`web/js/odds.js`) | 1440 | PASS (second pass) | 2026-09-02 | First pass had four deviations: full-weight stale-row prices, ~60px rows vs the artboard's 54px (base.css 44px button min-height inflating cells), non-verbatim thin-board headline, no mobile truncation. All four fixed and re-captured. Consensus panel is per side (`consensus.{away,home}`), which is contract-faithful; the artboard's single de-vigged number is a design simplification. SAVE THIS BET / GAP LEDGER omitted: no card-level save target in the contract. |
| V2-23 | Odds mobile | 390 | PASS (second pass) | 2026-09-02 | Five-row truncation with "N MORE BOOKS · TAP ANY PRICE TO CHECK IT" expand line matches the artboard. Real book labels via labels.js. |
| V2-27 | Loading skeleton (`web/js/states.js`) | 1440 / 390 | PASS | 2026-09-02 | No partial "N of 11 books in" counter: the manifest lists it under fields_NOT_available. |
| V2-28 | Empty slate | 1440 / 390 | PASS | 2026-09-02 | "NEXT SLATE: TOMORROW" tile omitted: no backing field. |
| V2-29 | Capture unavailable | 1440 / 390 | PASS | 2026-09-02 | Last-good-capture block and retry/back actions present. |
| V2-30 | Write failed | 1440 / 390 | PASS | 2026-09-02 | Support reference quoted; "nothing was written" stated. |
| V2-32 (block 01 primitive) | Featured Bet card (`web/js/featuredbet.js`) | 1440 / 390 | PASS with two accepted deviations | 2026-09-02 | (1) No "X OF 5 SEGMENTS MET" bar: the artboard's own example dims a segment that carries real data, which makes "met" a favourability judgment, i.e. a rating the boundary forbids; each segment shows its value or NOT AVAILABLE. (2) FLAGGED uses the shipped verdict colour convention (cyan), not the artboard's hot red, which the codebase reserves for a better price or the one primary action. Price-standing rank and verdict render honest absence when the caller cannot supply them (POST /betcheck carries neither). Design lane: propagate both corrections to V2-32/33/34. |
| V2-04 / V2-24 / V2-25 / V2-26 / V2-32 | Bet Check (`web/js/betcheck.js`) | 1440 / 390 | PASS | 2026-09-02 | Ten-block order and connector labels match; block 01 is the shared Featured Bet primitive (price-standing rank and verdict render honest absence, POST /betcheck carries neither); 05/06/08/09 amber NOT YET AVAILABLE; 402 wall amber with one hot CTA reading live `detail.remaining/limit`; free-check meter reads `free_check.remaining/limit`. Deviations accepted: V1 STRONGEST/WEAKEST blocks dropped per the artboard; KEEP USING THE BOARD links to signup (the board needs an account). Re-verify on staging: the mobile capture shows the fixed tab bar mid-page, a full-page-screenshot artifact of nav.css. Fixture note: the counterargument text contradicted the beats-consensus flag in the hand-built fixture; code was contract-faithful. |

Pending grades: V2-01/01a/01b/01c/22/33 (Gameday), V2-03/13/14/15/31/34 (Game) — Wave 1 lanes dispatched 2026-09-02.
Not started: Wave 2 (My Bets, Signup & Billing, Access, Landing). V2-35 stays
Tier B, contract-gated.
