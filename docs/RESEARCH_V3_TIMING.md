# Research Family V3 — information timing (market microstructure)

**STATUS: FROZEN 2026-08-31.** The timestamp-quality audit (see the freeze
record) filled the event-class table; no event-response result existed
anywhere when this froze — the capture infrastructure it depends on was not
yet running. Nothing here changes because early results disappoint.

## What this family asks, and what it does not

V1, V2 and V4 asked: *can we predict baseball games better than the market?*
Twenty-four pre-registered hypotheses said no. V3 asks a different question
entirely:

**When genuinely new information enters the market, how quickly do
sportsbooks react, which books react first, how large is the adjustment,
and does an executable stale-price window exist?**

This is market MICROSTRUCTURE research. It does not require being smarter
than the market — only earlier than the slowest visible part of it. The two
questions stay completely separate: the predictive result (no demonstrated
edge) is settled evidence; the microstructure result is unknown. Nothing in
V3 claims a betting edge; a positive V3 finding would establish measurable
latency, which is a NECESSARY condition for a timing edge, never sufficient
on its own (executability, limits, and price-vs-fair remain separate
questions).

The primary initial question is: **does measurable information latency
exist?** Not: did the team win.

## Event classes

Narrow, timestamp-safe classes — never "all news" pooled. Admission of each
class is decided by the timestamp-quality audit and recorded here at
freeze; a class whose events cannot meet the quality gate is EXCLUDED, not
downgraded.

| class | definition | timestamp source | grade required |
|-------|------------|------------------|----------------|
| lineup_posted | first appearance of a confirmed lineup for a game | bracketed by our own capture times | A or B |
| starter_scratch | probable starting pitcher changes after first being listed | bracketed by successive probable listings we captured | A or B |
| hitter_scratch | a posted lineup loses a previously listed starter | bracketed by successive lineup captures | A or B |
| reliever_status | closer / high-leverage reliever ruled in or out | only if a source with A/B timestamps exists | A or B |
| il_roster_move | IL placement/activation, trade, recall affecting the game | MLB transactions feed | A or B only; DATE-only rows are grade C and inadmissible for timing claims |
| weather_roof | meaningful weather or roof change | only with provenance-backed timestamps | A or B |

Timestamp grades: **A** exact publication/event timestamp · **B** bounded
between two known instants with small uncertainty (both bracket times
recorded; the bound IS the event time, carried as an interval) · **C**
reconstructed or date-only · **D** unusable. **Only A and B events may
support any timing claim.** Grade C/D events are stored but excluded from
every V3 measurement. A transaction DATE is never treated as a TIME.

## Per-event record (preserved for every admitted event)

event type · event timestamp (or interval, for grade B) · source ·
timestamp grade · affected team · affected player · pre-event relevance
estimate (frozen rule, below) · game start · books quoted immediately
before the event · prices immediately before the event · all captured
post-event prices with their capture timestamps.

## Measurements (computed per event, definitions frozen)

- **Market move:** a book's de-vigged implied probability for the affected
  game changes by ≥ the minimum meaningful move (below) from its last
  pre-event quote, in any direction.
- **Minimum meaningful move:** 1.0 probability point (0.010) de-vigged —
  the same economic floor every family has used.
- **Consensus:** de-vigged mean across all books quoting at that instant
  (proportional method, as in `m5/m3`); consensus move = change in that
  mean from the last pre-event snapshot.
- **First mover:** the first book whose move crosses the floor, by capture
  timestamp; ties within one capture are ties, not ordered.
- **Reaction-time ladder:** time from event (or from the event interval's
  END, for grade B — conservative) until 25% / 50% / 75% / all observed
  books have moved.
- **Stale book:** a book still quoting within the minimum-move floor of its
  pre-event price after ≥ 50% of books have moved.
- **Stale window:** duration from the 50%-moved instant until the stale
  book moves or the game starts; a stale price counts as OBSERVED for its
  whole window, and is called "executable" only in the narrow sense that it
  remained publicly quoted — no claim about limits or acceptance is ever
  made from this data.
- **Direction agreement:** whether the first move and the consensus move
  agree in sign with the information's expected direction (frozen per event
  class; e.g. losing a listed starter weakens that side).
- **Confirm/reverse:** whether the close consensus confirms (same sign) or
  reverses the initial reaction.

## Quality gates (frozen)

- Minimum books quoting pre-event: 6 (the M3 line — consensus over fewer
  is not a consensus).
- Minimum admitted events per class before ANY class-level statement: 30.
- Grade B interval width cap: an event whose bracketing interval exceeds
  the median capture spacing of its window by more than 2× is excluded.
- Event exclusion rules: events within 10 minutes of another admitted
  event on the same game (contaminated window); events after first pitch;
  games without a pre-event snapshot inside 90 minutes.

## The family and the correction

Each admitted event class contributes ONE primary hypothesis: *median time
to 50%-of-books reaction exceeds the capture-spacing floor* (i.e., latency
is measurable at our resolution, not instantaneous). The family is the set
of admitted classes; BH-FDR at q = 0.10 across the full family, early
deaths at p = 1.0, denominator = admitted class count recorded at freeze.
Secondary measurements (lead/lag tables, stale-window distributions,
magnitudes) are DESCRIPTIVE — reported with intervals, never promoted to
"findings" without their own future pre-registration.

## Replication and falsification

- Split by calendar: classes accumulate forward; a class-level result
  computed on the first half of its admitted events must hold direction
  and at least half its magnitude on the second half before it is called
  replicated. No result is read until a class reaches its 30-event floor.
- Falsification battery (RULES_VERSION 2.0.0) applies wherever a selection
  -shaped claim emerges (any future "bet the stale price" hypothesis would
  be its own family with the full funnel; V3 itself makes no such claim).
- Concentration checks adapted descriptively: a latency result carried by
  one book, one team, or one week is reported as exactly that.

## What V3 cannot do (frozen)

No 2025 contact. No sealed-2026 contact. No bet recommendations. No
"edge" language: the deliverable is a measured latency structure —
sportsbook response table, reaction ladders, stale-window distributions —
published in full whatever it shows. **If V3 is null (no measurable
latency at our resolution), that is the result**; the archive states what
resolution would be needed and what it would cost, and the program moves
to the next family.

## Freeze record

Frozen 2026-08-31, from the timestamp-quality audit of every event source
in the repo (docs/OVERNIGHT_RUN.md, same date):

**Admitted classes (the family, denominator 4):**

| class | grade at freeze | mechanism to reach B | est. events/day |
|-------|-----------------|----------------------|-----------------|
| lineup_posted | B (forward) | bracketed between successive rosterwatch polls with fetched_utc | ~27 team-lineups |
| starter_scratch | B (forward) | probable-pitcher change between polls | 0.3–1 |
| hitter_scratch | B (forward) | posted lineup loses a listed player between polls | 1–2 |
| il_roster_move | B (forward) | transaction id first seen between polls (the MLB feed itself is day-only, so A is unreachable) | ~20 game-relevant |

**Excluded, with reasons:** reliever_status (no announcement source exists
in the repo; post-game bullpen usage supports only day-level C inference) ·
weather_roof (roof state has no feed at all; weather is a single unstamped
reading) · **all historical replay, 2023–24** (every class is grade C/D:
transactions day-only, lineups date-only, no probables history, and the
historical odds store samples 3×/day so any bracket is 6–15 hours wide).
V3 is a forward study, entirely.

**Response variable at freeze:** forward capture carries grade-A quote
timestamps (observed_utc to the microsecond, per-book last_update to the
second) but stored only one book per event until the multi-book store
shipped; V3's clock starts on the first day the multi-book store and
rosterwatch are BOTH running. First-sighting lineup rows (no prior poll to
bracket against) are grade C and inadmissible, per the rosterwatch
derivation.

**Capture resolution at freeze:** hourly poll baseline (60-minute
brackets), 15-minute brackets inside dense windows; the reaction ladder's
resolution floor is therefore the poll spacing in force at each event, and
the primary hypothesis is stated against exactly that floor.

## ADDENDUM 2026-09-02 — FIRST CLASS READ — transaction_first_seen

The primary hypothesis test (`src/research/timingtest.py`, wired as
`python3 -m src.cli timing --test`) ran for the first time. One class has
crossed the read floor; the other three have not, and were not read.

**Naming note:** the freeze record above names this admitted class
`il_roster_move`; the capture code (`src/pipeline/rosterwatch.py`) and
every report below name the identical class `transaction_first_seen` (its
mechanism: "transaction id first seen between polls"). Same class, two
names — nothing else in the family denominator changes.

### Floor status of all four admitted classes (measurable-event count)

| class | measurable | floor | read? |
|-------|-----------:|------:|-------|
| transaction_first_seen (il_roster_move) | 56 | 30 | **yes — this addendum** |
| lineup_posted | 29 | 30 | no — 1 event short |
| hitter_scratch | 3 | 30 | no |
| starter_scratch | 0 | 30 | no |

### What was tested

Per-event paired formulation (lines 102-105 state the hypothesis per
class; lines 163-166 make the floor itself per-event, which is why the
paired form — not a pooled median-vs-median — is what was run): for each
usable event, `diff = (minutes to 50%-of-books reaction) - (that event's
own capture-spacing floor)`. H1: `median(diff) > 0`. This is exactly
equivalent to `S(0) > 0.5`, where S is diff's survival function
(S(t) = P(true diff > t)) — a non-increasing step function crosses below
0.5 at a positive time iff its value at 0 already exceeds 0.5 — so the
test bootstraps `S_hat(0)` directly rather than a KM median that can come
back "not reached." Reaction time is the Kaplan-Meier reaction-time ladder
value already computed by `eventstudy.measure()` (`ladder_minutes["50%"]`);
an event where that is `None` — under 50% of books ever moved before its
mapped game's first pitch — is right-censored at
`(minutes from event to first pitch) - floor`, never dropped and never
imputed. Floor is 15 minutes when the event falls inside the dense
capture window (`src/pipeline/dense.py`, 180 minutes before first pitch),
60 minutes (the hourly baseline loop) otherwise. Clustering, for the
bootstrap and the family's own correlation structure, is by the event's
own mapped `game_pk` — 2,000 resamples, seed 20260901.

### Exact numbers

- 166 events observed, 165 admissible, **56 measurable** (matches
  `python3 -m src.cli timing` and `leadlag.response_table`'s own ladder,
  `50%` rung 178.85 min).
- All 56 measurable events produced a usable row (0 excluded for
  unparseable or missing game-start times).
- Floor regime: 36 events under the 15-minute dense floor, 20 under the
  60-minute hourly floor (median floor across the sample: 15 min).
- **39 of 56 (69.6%) censored** — under 50% of books had moved by first
  pitch. 17 observed.
- Complete-case (censored events dropped; biased **downward**, toward
  *less* measured latency — the conservative direction for this
  hypothesis) median reaction: **178.85 min**; median diff: **118.85 min**.
- Kaplan-Meier (censoring-aware) median reaction: **224.87 min** (~3h45m);
  median diff: **164.87 min** (~2h45m). Both above their complete-case
  counterparts, as the downward-bias direction predicts.
- **Point estimate S_hat(0) = 1.000** (every one of the 17 observed
  reactions, and every one of the 39 censored lower bounds, is consistent
  with diff > 0 — see caveat below). **95% bootstrap CI [1.000, 1.000].
  One-sided bootstrap p = 0.000** (2,000/2,000 resamples, clustered by
  `game_pk`, 20 clusters).
- **Split-half replication: REPLICATED.** First half (n=28) S(0) = 1.000;
  second half (n=28) S(0) = 1.000 — same direction, magnitude fully held.

### FDR denominator, and what has NOT been decided

The family denominator recorded at freeze is **4** admitted classes
(`lineup_posted`, `starter_scratch`, `hitter_scratch`,
`transaction_first_seen`/`il_roster_move`). BH-FDR at q = 0.10 is a
correction over the full family's p-values, with an early-death p = 1.0
for any class that never reaches its floor — it cannot be computed
honestly from one p-value out of four. **No promotion decision is made
here.** `lineup_posted` is one event from its own floor and is the
natural next read; `hitter_scratch` and `starter_scratch` remain far
below it. `src/research/timingtest.bh_fdr` is written and unit-tested for
when all four have a p-value (or a frozen early-death 1.0).

### Honest interpretation

If it holds up under the family correction and the other three classes'
reads, this is a **measurable ~2.75-3.75 hour median latency** (KM
estimate) between an MLB transaction becoming visible in our feed and
half the quoting sportsbooks repricing its next-affected game by at least
one de-vigged probability point. Per this family's own frozen scope, that
is a **latency structure finding, not an edge claim**: necessary, never
sufficient, for any timing edge — executability, limits, and price-vs-fair
are separate questions this data does not address, and none is claimed.

### For methodology review — where to look hardest

1. **S(0) = 1.000 / CI [1.000, 1.000] is a boundary result, not a
   certainty claim.** It holds because the smallest *observed* diff in
   the whole sample is +59.4 minutes (well clear of both the 15- and
   60-minute floors) — a percentile bootstrap can only redraw from the
   clusters actually observed, so it structurally cannot produce a value
   below the sample's own minimum. Zero of 56 events showed reaction at
   or faster than their own floor; with a larger sample the true
   population S(0) could plausibly sit measurably below 1. Read "p =
   0.000" as "no counterexample anywhere in this sample, in any
   resampling of it" — not as a formal probability of a false positive
   under an alternative.
2. **69.6% censoring** means most of the evidence is lower-bound-only.
   One censored event has a *negative* lower bound (`censor_time - floor
   = -6.9 min`, an event captured very close to its mapped game's first
   pitch) — legitimate (it simply leaves the KM risk set before time 0
   and asserts nothing), but worth an independent eyeball.
3. **20 distinct `game_pk` clusters carry 56 events** — some clusters
   contribute multiple transactions for the same game. The effective
   cluster count for the bootstrap is 20, not 56; this is the number that
   should be compared against any intuition about statistical power here.
4. **The replication check also saturates at the S(0) boundary in both
   halves** (1.000 and 1.000), so "replicated" is correct by the
   pre-registered rule but is not a discriminating check in this
   instance — it could not have shown a magnitude shortfall even if the
   true effect were smaller in the second half, only a sign flip.
5. **The "next game" join for a transaction event** (a transaction names
   no game; it is mapped to the affected club's next stored game after
   the event) means an event's censoring time can span from minutes to
   over a day (observed lower bounds ranged up to ~1,404 minutes before
   subtracting the floor) — a transaction about a team that does not play
   again for a while gets a very long observation window, which the KM
   estimator uses correctly but is worth confirming reads as intended for
   a "reaction to THIS game" claim rather than "reaction, eventually."
