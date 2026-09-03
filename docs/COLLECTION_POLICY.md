# Targeted collection policy

Goal: maximize future research options per API credit. Floor 5,000,
absolute; approved envelope ~132 credits/day (superseded below). Actual
spend has run far below the envelope (dense no-ops on quiet hours), which is
headroom this policy uses deliberately — total daily spend stays inside the
already-approved figure, enforced in code order: if a day would exceed it,
added markets are skipped first, then the grid thins. Nothing here changes
the floor rule: "skipped: credit floor" stops everything and reports.

## Corrected 2026-09-03 (packet W7, owner decision 2; docs/planning/attack.md
F13/S17): balance semantics, the ~900/day envelope, the drop order

**The "53,083 credits (2026-08-31)" figure above, and its predecessor
"~99,621 ... measured balance", were both wrong in kind, not just out of
date.** `PRICING_TIERS` in `src/providers/odds.py:237-243` shows the account
is on the "100K" tier: **100,000 credits/month, $59/mo, resetting every
billing cycle**. `credits_remaining` from `quota()` is a MONTHLY QUOTA on a
FLOW that refills at each reset, never a bank balance that only ever runs
down. Reading it as a balance with "headroom" understates how much room
there is (a reset restores it to 100,000 regardless of what stood the day
before) and, worse, invites a plan that silently assumes a multi-week
purchase can spend against a number that resets mid-plan. See
`src/capture/budget.py` for the corrected model: `MONTHLY_ALLOTMENT`,
`quota_reset_utc()` (assumed first-of-UTC-month; the account's real billing
anchor day is not knowable from anything this repo can read), `spent_today()`
and `remaining_today()` (both computed read-only from
`data/processed/credit_log.jsonl`).

**The envelope is now ~900 credits/day, APPROVED (owner decision 2, packet
W7)**, provided it stays inside the existing paid monthly allotment and
carries hard spend guards — both true here: `DAILY_ENVELOPE = round(100,000
x 0.27 / 30) = 900`, well inside one month's 100,000-credit allotment even
run flat out every day (900 x 30 = 27,000, 27% of the allotment), and
`src/capture/budget.can_spend()` enforces the floor and the envelope in code,
not by policy alone. This supersedes the "~132/day" figure above, which was
priced only against dense's baseline layer before F13 required every family
to carry a measured per-event cost before entering the envelope.

**Per-family measured-cost probe rule (F13's fix):** no family may enter the
envelope's arithmetic on an assumed cost. `config/capture_families.json`
carries `measured: true|false` per family; `can_spend()` returns
`PROBE_REQUIRED` for anything still `false`, and the only way a family
becomes `true` is a real, explicit, 1-credit measured probe
(`python3 -m src.cli budget --probe <family>`; never run as a side effect of
anything else). As of this writing, measured: `featured` (3 credits/event,
flat, unchanged from the original probe), `alternates` (1 credit/event, 7
books, 130–160 outcome rows), `prop_listing_feasibility` (1 credit/event/slot,
unchanged), `weather` (0, free by construction). Unmeasured, PROBE_REQUIRED:
`f5_trio` (the full h2h+spreads+totals first-five bundle — note this is
DIFFERENT from the already-measured f5 h2h-only figure below), `team_totals`,
`pitcher_props`, `batter_props`, `parlay_sgp` (endpoint existence not even
confirmed).

**Drop order corrected (S17's fix):** the prior coded order dropped batter
props first — the largest surface with zero history and no retroactive
purchase path (owner decision 9) — which destroys the most perishable
evidence first under any squeeze. `src/capture/budget.DROP_ORDER` (versioned,
v1) reorders by irrecoverability x marginal information, first-dropped to
last-dropped: `parlay_sgp` → `prop_listing_feasibility` → `team_totals` →
`alternates` → `pitcher_props` → `f5_trio` → `batter_props_extra` →
`featured` (Tier A, last, always — flat 3 credits/event, the response
variable itself, never the thing that breaks a budget). A **non-droppable
floor**, `batter_props_floor` — full batter props on 2 games/night, chosen
deterministically per night by `budget.rotated_floor_games()` — never appears
in the drop order and is never touched by any allocator, so the surface is
never zero for a whole month regardless of how hard a day is squeezed.

**Cadence SLO (F10's fix):** `known_at_grade` is computed from the measured
gap between polls, never asserted from a schedule — `grade_from_gap(seconds)`
in `src/capture/cadence.py` returns B (≤20min), C (≤2h), or D (otherwise).
`python3 -m src.cli cadence --date YYYY-MM-DD` computes attempted/succeeded/
longest-gap/p95-gap per source (odds_multibook capture instants, rosterwatch
lineup-watch poll markers, umpirewatch poll markers) and appends one row per
source per day to `data/processed/cadence_slo.jsonl` (tracked, append-only).
A schedule that claims 15-minute cadence but leaves a six-hour hole grades D
on that hole, not B on the schedule's own claim.

**The stale "3–4 books, listing-dependent" pitcher-strikeouts figure below
(from the original 24-credit probe) is corrected: the running
`prop_listing.py` audit's own store (`data/processed/prop_listing.jsonl`, 454
markers as of this writing) measures `books_listing` at 7 on 20 of the 38
markers that saw any coverage at all (mode 7; the rest are 6, one 4, one 2) —
7 books, not 3–4, is the figure to use going forward. See
`docs/PROBE_PROP_LISTING.md` for the audit design; the "3–4 books" line
further down this document is the earlier, superseded reading, left in place
below only as the dated record of what the original probe first reported.

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

## What odds_multibook.jsonl actually contains (2026-09-01)

`data/processed/odds_multibook.jsonl` is a log of WHAT THE FEED SAID AT EACH
CAPTURE MOMENT. It is not a pre-game-only store, and it never was: a capture is
one bulk call for the whole board, the feed keeps listing a game after first
pitch, and so every capture moment past a start appends that game's IN-PLAY
prices. Measured on the store as it stood 2026-09-01: **592 of 5,803 rows
(10 of 26 events) carry an observed_utc after their own commence_time**, from
12 seconds to 2h50m late, 104 of them at |price| > 1000 (e.g. Padres/Reds,
first pitch 22:41Z, observed 23:47Z, -10000/+900).

This is a side effect of the bulk call, not a purchase: those rows cost zero
extra credits, and `dense.games_in_window` already refuses to let an in-play
game trigger a capture ("its price is in-play, which is a different product").
Capture is therefore left exactly as it is. The rows are append-only forward
evidence -- a real record of how a book prices a game it has moved on from,
which is the raw material for any later staleness or suspension work -- and
deleting or filtering them at write time would destroy evidence to fix a
reading error.

**The reading rule.** A pre-game claim filters explicitly, at read:

- `snapshots.is_pregame` / `snapshots.pregame_rows` is the ONE definition, and
  it reads the same `CLOSING_GRACE_SECONDS` as `closing_observation`, so "is
  this the pre-game market" cannot be answered two ways.
- Every price BOARD goes through `analysis/prices.boards_by_matchup` or
  `for_game`, which filter there. A started game's board is its last pre-game
  instant -- the same instant the close comes from -- not a missing board.
- `snapshots.multibook_quotes` stays raw by default (`pregame_only=False`):
  the V3 timing work measures against the whole series and caps post-start
  quotes itself with the game's start time (`eventstudy.measure(game_start=)`).
- Liveness and coverage checks in `pipeline/health.py` read the store WHOLE on
  purpose: "when did we last see the market" is a question about captures, not
  about pre-game prices.

## Amendment 2026-09-02: prop PRICES switched on (capture-now), bounded

Three capture streams were added under the owner-approved master-plan
principle **CAPTURE NOW, RESEARCH LATER** (docs/MASTER_PLAN.md Sec.1 claim 3,
Appendix C.1 item 6: timestamped forward data cannot be bought retroactively).
Two are free and unconditional: weather forecasts for today's and tomorrow's
slate (`src/pipeline/weather_capture.py`, 0 credits, Open-Meteo), and a
credit-balance log written wherever the odds provider's quota is already read
for free (`src/pipeline/creditlog.py`, 0 credits).

The third is the one that needed this amendment. `src/pipeline/prop_prices.py`
is the RESEARCH COLLECTION layer that the feasibility measurement above was
explicitly kept separate from: it stores PRICE and POINT, not just listing
coverage, for `pitcher_strikeouts` per book per pitcher.

It is switched on now, bounded exactly as follows, and no more broadly than
that:

- Same shape as the listing audit: 3 games/day x 6 slots = 18 credits/day,
  sampled and slotted by the SAME grid `prop_listing.py` uses (imported, not
  re-derived), so the two layers observe the same games at the same instants.
- Hard daily cap enforced from `prop_prices.jsonl`'s own marker rows, never
  from an in-memory counter -- the same self-auditing pattern `prop_listing.py`
  uses, for the same reason: a killed run must not lose track of its own
  spend.
- The absolute 5,000-credit floor and the 5,200 probe reserve apply
  unchanged. This layer is skipped FIRST when a day approaches the ~132/day
  envelope, below even the listing audit in priority, because it is the
  newest and least-validated of the three softer-market layers.
- Off unless `PROP_PRICES=1`. The switch lives in the environment, not in
  this module, so turning it off is one edit and no code change -- the same
  reasoning `PROP_LISTING_AUDIT` already uses.

**This does not touch the hard approval gate.** A HISTORICAL prop purchase --
buying past prop prices from the archive -- remains exactly what it was:
forbidden without a registered hypothesis naming the window and Brey's
explicit sign-off, per the roadmap's hard gates. This amendment authorizes
FORWARD capture only, at the bounded rate above, starting from whenever the
switch is turned on.
