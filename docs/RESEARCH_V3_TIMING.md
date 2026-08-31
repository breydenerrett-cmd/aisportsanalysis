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
