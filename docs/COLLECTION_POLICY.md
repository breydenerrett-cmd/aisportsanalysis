# Targeted collection policy

Goal: maximize future research options per API credit. Balance 53,083
credits (2026-08-31); floor 5,000, absolute; approved envelope ~132
credits/day. Actual spend has run far below the envelope (dense no-ops on
quiet hours), which is headroom this policy uses deliberately — total
daily spend stays inside the already-approved 132, enforced in code order:
if a day would exceed it, added markets are skipped first, then the grid
thins. Nothing here changes the floor rule: "skipped: credit floor" stops
everything and reports.

## What the probe established (24 credits, 2026-08-31)

- First-five h2h: 5 books forward at 1 credit/event/snapshot; historically
  12 books on a 5-MINUTE snapshot grid at 10 credits/event/snapshot.
- F5 spreads/totals: 3 books — thin but priced the same.
- Alternate spreads/totals: 7 books, 130–160 outcome rows per event at 1
  credit — the best information-per-credit on the board.
- Pitcher strikeouts: 3–4 books, listing-dependent; prop history from
  ~May 2023.
- The per-event markets endpoint is a 1-credit coverage scanner.

## The three-layer policy

**BASELINE (existing, unchanged):** the daily loop's slate snapshots and
the hourly dense trigger — h2h, all books now persisted per capture
(multi-book store). This is the V3 response variable and is never
sacrificed to anything below it.

**EVENT (free):** rosterwatch polls the free MLB feeds every trigger
firing and every dense inter-capture gap — lineups, probables,
transactions with fetched_utc. Zero credits; this layer produces the
grade-B events themselves.

**CLOSE (existing calls):** dense's T-25 close pass; a game reaching first
pitch without a capture in its last 30 minutes is reported as a missed
window, never papered over.

**SOFTER MARKETS (new, bounded):** piggybacked on dense capture moments
only — when dense fires on approaching games, each capture adds
`h2h_1st_5_innings` (+1 credit/event/moment). Expected +15–40 credits/day,
inside the envelope given measured baseline usage. Alternates and props
are NOT collected yet: they are options, priced and documented here, to be
switched on when a registered hypothesis needs them — option value comes
from knowing the cost, not from hoarding rows.

**HISTORICAL PURCHASES:** none without a registered hypothesis naming the
window. The 5-minute historical grid (10 credits/event/snapshot) makes a
targeted lead/lag study buyable — e.g. 100 event-windows × 12 snapshots ≈
12,000 credits — which is exactly why it waits for a pre-registration and
Brey's sign-off per the roadmap's hard gates (large historical purchases).

## Standing order of protection

Forward evidence first: live odds snapshots, lineup/news timestamps,
recommendation state, close capture, settlement, ledger integrity.
Historical and research work yield to these, always.
