> **AUDITED AT SHA `3dca767`. NOT CURRENT-PRODUCTION TRUTH.**
> Branch HEAD at push time was `cfe6bcb` (5 commits later, incl. a canvas-first frontend
> rebuild). Parent must reconcile against current HEAD before treating findings as
> authoritative. Two findings are already confirmed superseded — see
> `RECONCILIATION_REQUIRED.md`. No finding has been weakened or removed.

# Codex V2 — benchmark notes (principles only, no identity copied)

Inspected live 2026-09-01: Gameday, matchup carousel, Game Center, Advanced expansion,
Bet Check, mobile (390). Codex identity — lime/cyan palette, BETCHECK wordmark, outlined
ghost display word, hexagon VS, its exact geometry and wording — is NOT adopted.

## P1 — Gameday is a CAROUSEL of team-color environments, not a grid
WHAT: one matchup owns a full-bleed band; prev/next chevrons in chamfered side gutters;
a numbered LIVE SLATE strip below acts as the index, active tile elevated with a
team-gradient underline. The entire band recolors per matchup (blue/green → rust/teal).
WHY IT WORKS: choosing a game becomes an event. Eye lands on the team environment first,
then the center time/VS column, then the price.
TRANSLATE: yes — LINEHOUND already owns diagonal team seams. Ours becomes an angled seam
(not vertical), warm-graphite ground, team colour as environment light, red reserved.

## P2 — Center "scorebug" column stacked on the seam
WHAT: NEXT UP chip → time in a dark bug → VS → venue chip → dot on the seam line.
WHY: gives the seam a job; anchors the two halves; reads as broadcast.
TRANSLATE: yes, as a vertical HUD stack on our diagonal seam.

## P3 — Price bug fused to the team side, with the action attached
WHAT: "CHI MONEYLINE +141" panel with a "BUILD BET ›" tab welded to its edge, mirrored on
the other side. Price and its action are ONE object, living inside that team's environment.
WHY: the price belongs to a team, not to a table. Removes the "which side is this?" question.
TRANSLATE: yes — strongest single import. Ours: chamfered price bug + attached CHECK tab.

## P4 — Head-to-head COMPARISON table with a LEAN column  ★ best pattern in the demo
WHAT: rows of "CHI value | ‹/› | SEA value", winning side highlighted, header CHI | LEAN | SEA.
WHY: converts a stat dump into a duel. Eye scans the arrow column and instantly reads who
wins what. Honest — it compares measured values, asserts no outcome.
TRANSLATE: yes, for Game Advanced. Ours uses cyan for the leaning side (analytical), never red.

## P5 — Numbered narrative with connector labels between sections
WHAT: Bet Check runs 01 MY BET → 02 CURRENT MARKET → … → 06 BOTTOM LINE, with interstitial
labels: "COMPARE AGAINST THE MARKET ⌄", "CHECK THE LATEST CONTEXT ⌄", "SYNTHESIZE, DON'T PREDICT ⌄".
WHY: the page narrates its own argument; you know what the next section will do before you
reach it. Scroll becomes a guided sequence rather than a stack of cards.
TRANSLATE: yes — this is exactly the required Bet Check story. Ours uses our own connector copy.

## P6 — Evidence as icon + label + big value + one sentence, in a 3-up rack
WHAT: QUICK READ columns: coloured chamfer icon, small label ("Starter form"), large value
("PARK · 3 ER / 18 IP"), one sentence, giant ghost index numeral, coloured bottom rule.
WHY: scannable at a glance, readable in depth, and the ghost numeral gives rhythm.
TRANSLATE: yes.

## P7 — Honest unavailability sits INSIDE the evidence grid
WHAT: column 02 reads "Roof decision — PENDING — No verified total-market impact is available."
Lineups card reads "PROJECTED — Final batting orders are not available."
WHY: absence is presented as a finding with equal visual weight, not an error.
TRANSLATE: yes — matches our NOT YET AVAILABLE rule. Ours: amber/neutral, never red.

## P8 — Active nav tab as a SHAPE that breaks the header rule
WHAT: the selected tab is a chamfered slab that juts up through the header line.
WHY: unmistakable selected state, game-menu feel, zero ambiguity.
TRANSLATE: yes, expressed with our angled geometry on the rail/top strip.

## P9 — Three-way control hierarchy in one row
WHAT: [secondary ghost] [tertiary expand w/ chevron] [primary solid] — CHECK CHI / EXPAND
ADVANCED / CHECK SEA. Expand is visually distinct from both choices.
TRANSLATE: yes.

## P10 — Disclaimer welded under the action
WHAT: "Comparison only. No probability, EV, confidence, or recommendation." directly beneath
the RUN BET CHECK control, not in a footer.
TRANSLATE: already our rule; keep.

## P11 — Mobile: bottom tab bar with lit top-edge on active; comparison table survives
WHAT: SLATE / GAME / CHECK, active tab raised + lit bar. LEAN table keeps all three columns
at 390. Book rack becomes 2×2.
TRANSLATE: yes.

## WHAT CODEX DOES WORSE THAN US (do not regress to it)
- Fictional teams/leagues (EMPIRE, TIDES, FOUNDRY) — we use real MLB and must stay honest.
- Only 4 games and 4 books; no date rail; no staleness per quote; no My Bets, no auth,
  no signup, no compliance footer, no 21+/1-800-GAMBLER.
- Lime-on-black is high-energy but generic dev-demo; our warm graphite + reserved red is
  a stronger, more ownable identity.
- No sample-size discipline, no evidence ladder, no counterargument as a required field.
