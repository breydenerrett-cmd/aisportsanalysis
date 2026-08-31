# /design mission brief — first artboard pass

Prepared ahead of Milestone 1 so the design pass launches the moment the
contracts lock. Fable reviews the contracts into this brief at integration;
until then the contracts row is marked PENDING.

## What Design is being asked to do

Visualise decisions that are already made. The product strategy, information
architecture, page inventory, vocabulary and honesty rules were settled by
`docs/PRODUCT_DESIGN_HANDOFF.md` and are NOT open for redesign. Design's job
is to make those decisions into an excellent visual product. A design that
violates evidence integrity, data reality, or the vocabulary rules is wrong
regardless of how it looks.

## Inputs (give Design all of these)

| input | where | status |
|---|---|---|
| Product decisions, page specs, personas, UX rules | docs/PRODUCT_DESIGN_HANDOFF.md | final |
| Capability truth table (what is real TODAY) | docs/CAPABILITY_RECONCILIATION.md | final; re-check Bet Check rows at brief time |
| Domain contracts (field-level shapes) | src/analysis/contracts.py | PENDING — attach at launch |
| Honest pricing-calculator spec | docs/PRICING_CALCULATOR_REVIEW.md | final (calculator redesigned; two-branch + breakeven only) |
| Representative REAL data | a generated briefing payload for a real slate date (12-game night), plus one quiet-slate date | generate at launch; never lorem ipsum, never fabricated odds |
| NEGATIVE reference | artifacts/demo_latest.html and a current briefing.html | final — this is what NOT to look like |

## Visual direction — Graphite Terminal family, three executions

A. **EDITORIAL / SPACIOUS** — broadsheet influence, most readable, most restrained.
B. **TERMINAL / PRECISION** — professional market-intelligence feel, dense only where useful.
C. **SPORTS / WARM** — more sports-native warmth, still analytical and premium.

All three obey: warm graphite (not navy); humanist sans for prose; monospace
for prices/figures only; ice cyan = information; restrained amber = price /
opportunity; minimal red; generous whitespace; mobile-first; no purple/magenta
casino gradients, no AI glow, no sportsbook promo styling, no condensed
all-caps dominance. These are comparisons of EXECUTION — do not vary the
information architecture between them.

## Screens (coherent system, not isolated shots)

A. TODAY · B. GAME quick view · C. GAME quick+advanced expanded · D. BET
CHECK · E. ODDS · F. WHAT CHANGED band/state · G. app shell + nav (TODAY /
GAMES / BET CHECK / ODDS / MY BETS; Research in the account menu) · H. 375px
mobile versions of TODAY, GAME, BET CHECK (designed, not "made responsive").

Plus the interactive loop where supported: open TODAY → what changed → open
game → quick view → expand one factor → full advanced → run Bet Check → see
support AND counterargument → find better price → save.

## Non-negotiable content rules for the artboards

- Every quantitative claim shows its sample. Evidence labels are
  DIFFERENTIAL — most ordinary observations carry no badge.
- Counterargument has equal visual legitimacy with support, and renders even
  when empty ("No significant counterarguments found.").
- MARKET-IMPLIED CONSENSUS, never "true" anything. Price improvement is
  line-shopping value, never EV/edge/value. No win probability anywhere.
- Quiet night reads as completed work ("We checked all 15 games. Nothing
  clears the bar tonight."), never as an empty state or a wall of zeros.
- Staleness is visible ("Odds updated 3 minutes ago"); a missing source says
  so and dates its last success.
- No fake precision, no confidence scores, no invented freshness.

## Bet Check gets the deepest attention

The fixed skeleton (YOUR BET → support → counterargument → best available →
market-implied consensus → your price → strongest reason → weakest reason →
what changed → sample quality → evidence status → bottom line) must be
immediately legible to a normal bettor with the deeper evidence one
interaction away — without badge spam or fake confidence.

## Decision packaging for Brey

One compact item when the three directions are ready: links, the 2–3
meaningful differences, any usability tradeoff, and the Design/Fable
recommendation. One decision cycle; refinement happens visually afterward.
