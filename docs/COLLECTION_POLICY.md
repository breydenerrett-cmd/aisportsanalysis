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
from knowing the cost, not from hoarding rows. The one exception is the
listing-feasibility measurement below, which collects no prices at all and
is therefore not the thing this clause forbids.

## Feasibility measurement vs research collection

Amended 2026-08-31. **Brey approved this distinction, narrowly, on
2026-08-31**, and it is written down because the clause above would
otherwise read as forbidding a question that costs almost nothing to ask.

The clause above forbids collecting a market's PRICES ahead of a registered
hypothesis, and it is right to. It was never meant to forbid finding out
whether a market is carried at all. Those are different acts with different
costs and different risks:

**FEASIBILITY MEASUREMENT** asks whether an instrument exists and whether we
could read it — is the market listed, by which books, from when, and what do
the API's own `last_update` timestamps say. It produces coverage and timing
facts. It cannot produce a bet, and its result is as useful when it is
negative: "no book lists it" kills a candidate for the price of a few credits
and no registration.

**RESEARCH COLLECTION** asks what the market SAYS — prices, points, movement
— and is the input to a claim about profit. It stays behind a registered
hypothesis, always, for the reason the roadmap gives: numbers gathered before
the question is fixed get searched until they answer it.

What a feasibility measurement MAY collect: whether the market is listed,
which books list it, when it first appears, the market `last_update` per book,
and coverage/availability. What it MAY NOT do, in any form: test price
strategies, optimise thresholds, infer an edge, or run outcome analysis.
Nothing produced under this heading is ever described as EV or edge, because
it is not: it is a statement about what is on the board, not about what the
board is worth.

Two conditions hold for every measurement taken under this amendment. Its
artifact is **frozen and timestamped** when the measurement ends. And any
later pre-registered hypothesis that touches the same market must **explicitly
acknowledge that this coverage information was already known** when the
hypothesis was written — a registration that pretends to be blind to evidence
already in hand is not a registration.

**PROP LISTING PROBE (bounded, time-limited):** `pitcher_strikeouts` listing
state only, 3 games/day × 6 slots = 18 credits/day, hard cap 400 credits,
abort criteria in `docs/PROBE_PROP_LISTING.md`. No prices stored. Lowest
priority layer; skipped first when a day approaches the envelope, and skipped
outright below a 5,200 balance. Expires at the cap or at any abort trigger,
whichever comes first; `scripts/forward_capture.sh` holds the switch that
turns it off. Nothing here authorizes a historical prop pull — that remains a
hard approval gate.

**HISTORICAL PURCHASES:** none without a registered hypothesis naming the
window. The 5-minute historical grid (10 credits/event/snapshot) makes a
targeted lead/lag study buyable — e.g. 100 event-windows × 12 snapshots ≈
12,000 credits — which is exactly why it waits for a pre-registration and
Brey's sign-off per the roadmap's hard gates (large historical purchases).

## Standing order of protection

Forward evidence first: live odds snapshots, lineup/news timestamps,
recommendation state, close capture, settlement, ledger integrity.
Historical and research work yield to these, always.

## F5 close cap raised 6 -> 8 (Brey approved, 2026-08-31)

`F5_CLOSE_MAX_EVENTS` governs how many first-five closing prices one dense run
may buy. It was 6 and was EXACTLY saturated on an ordinary card: MLB clusters
its starts, and 2026-09-01 has four games at 22:40 plus two at 22:45, all in
one run's span. A seventh simultaneous start was dropped permanently -- the
budget and seen-set are per-run, the next run begins after first pitch, and an
F5 close cannot be refetched at any price the next morning.

Raised to 8. This is a CEILING, not a spend: measured nightly use is ~1 credit
per game (15-16 on a 15-game card), and the ceiling only binds when starts
cluster. Theoretical worst case 32/night remains inside the 15-40/day band
this policy already approves for the layer, so the change needed sign-off but
not new budget. Drops are now reported by game rather than silently absorbed.
