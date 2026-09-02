# Research Family V3 — AMENDMENT: umpire-crew-reveal class

**Written and pre-registered 2026-09-02, BEFORE any event has been read from
`data/watch/umpires_watch.jsonl`.** This is an AMENDMENT to the frozen family
document `docs/RESEARCH_V3_TIMING.md` (frozen 2026-08-31), adding a 5th event
class on the same terms as the four admitted at freeze. Nothing in
`docs/RESEARCH_V3_TIMING.md` itself is edited by this document — the
denominator change it causes is stated here and is expected to be reflected
there, and in `docs/RESEARCH_CATALOGUE.md`'s L1 row, as pointer updates by
whichever pass owns those files next.

## Why this amendment exists, and why now

`docs/RESEARCH_CATALOGUE.md` (B10) and `docs/RESEARCH_V6_CANDIDATES.md` (C7)
both block umpire-related work on **"source not verified."** That blocker is
now false. Verified live against `https://statsapi.mlb.com/api/v1/schedule`
(the same host `src.providers.mlb` already calls for every game) on
**2026-09-02**:

- `GET /api/v1/schedule?sportId=1&date=<d>&hydrate=officials` returns the
  4-person umpire crew, keyed by `officialType` (`Home Plate`, `First Base`,
  `Second Base`, `Third Base`).
- The `officials` array is **empty** while a game's `status.detailedState`
  is `Scheduled`, and becomes populated by `Pre-Game`/`Warmup` — observed
  3.6–4.6 hours before first pitch on 2026-09-02's slate.
- Reconfirmed independently in this pass with a second live pull
  (2026-09-02, ~19:21 UTC) against that same date: of the day's `Scheduled`
  games every one carried `officials: []` (e.g. game 823660, DET @ MIN,
  first pitch 23:40Z), while every game already at `Pre-Game`, `Warmup`,
  `Delayed` or `In Progress` carried a full 4-person crew (e.g. game
  824717, `Pre-Game`, first pitch 20:10Z). The categorical split — empty
  before reveal, populated after — is confirmed; the precise 3.6–4.6 hour
  lead time is the orchestrator's own timed measurement and is not
  re-derived from this single cross-sectional pull (a lead time needs two
  polls bracketing the transition, which is exactly what forward capture
  now provides going forward, not a snapshot).
- Historically available back to 2015, per the same audit (not exercised by
  this amendment — see "What this class does not claim," below).

This is the exact CAPTURE-NOW situation `docs/MASTER_PLAN.md` §1 claim 3
describes: **the reveal TIME is unrecoverable if not observed forward.** MLB
does not publish when a crew was assigned, only that the field now shows
one. Every day this goes uncaptured is a day of that evidence gone for good.
The capture side, `src.pipeline.umpirewatch`, ships in this same change so
the clock starts today rather than after a further round of designing.

## The class

Added to `docs/RESEARCH_V3_TIMING.md`'s event-class table, on identical
terms to the other four:

| class | definition | timestamp source | grade required |
|-------|------------|------------------|----------------|
| `umpire_crew_revealed` | first appearance of a non-empty 4-person umpire crew for a game (via MLB Stats API's `officials` hydrate) | bracketed by our own capture times (`src.pipeline.umpirewatch`) | A or B |

**Timestamp grade at pre-registration: B (forward).** Bracketed between the
last `umpirewatch` poll that still saw an empty `officials` array for that
game and the first poll that saw a full one — exactly rosterwatch's
`lineup_posted` convention, and using the identical grade-B bracket
semantics `docs/RESEARCH_V3_TIMING.md` already defines: "bounded between two
known instants with small uncertainty (both bracket times recorded; the
bound IS the event time, carried as an interval)." A crew observed already
populated on a game's very FIRST poll (no prior look to bracket against —
e.g. a doubleheader added to the slate late) is grade C, stored, and
excluded from every measurement, per `src.pipeline.umpirewatch.events`'s
`inadmissible: True`.

**Mechanism to reach grade B:** `src.pipeline.umpirewatch.poll`, polling
today's and tomorrow's slate on the existing forward-capture cadence,
storing to `data/watch/umpires_watch.jsonl` (git-tracked forward evidence,
append-only, same protection as the three rosterwatch stores). Estimated
events/day: one per game whose crew is captured transitioning from empty to
full — up to the day's full slate (~15 games at peak), though many games
will already show `Pre-Game` at their first poll of the day if the poll
cadence is coarser than the reveal-to-first-pitch window, which is exactly
why `umpirewatch` also polls **tomorrow's** slate: it plants the marker that
makes tomorrow's eventual reveal admissible once tomorrow becomes today,
rather than every morning's first look already being a first sighting.

## Per-event record

Identical to `docs/RESEARCH_V3_TIMING.md`'s frozen per-event record, applied
to this class: event type (`umpire_crew_revealed`) · event timestamp
interval (grade B) · source (`src.pipeline.umpirewatch`) · timestamp grade ·
affected team · affected player (n/a for this class — an umpire crew has no
"affected player" in the sense the roster classes do; recorded as null, not
omitted) · pre-event relevance estimate (frozen rule, unchanged) · game
start · books quoted immediately before the event · prices immediately
before the event · all captured post-event prices with their capture
timestamps.

## Primary hypothesis (same wording as every other class)

*Median time to 50%-of-books reaction exceeds the capture-spacing floor* —
i.e., latency is measurable at `umpirewatch`'s poll resolution, not
instantaneous. Same one-hypothesis-per-class rule the family uses
everywhere else; no secondary claim is registered here.

## Quality gates and floor (inherited from the family, unchanged)

- Minimum books quoting pre-event: **6**.
- **Minimum admitted events before ANY class-level statement: 30**, exactly
  as every other V3 class. `src.research.timingreport` enforces this
  mechanically — see "Hook into timingreport," below — and today, with zero
  admitted events, this class reports **0/30, status accumulating**, and no
  result is read.
- Grade B interval width cap: an event whose bracketing interval exceeds
  the median capture spacing of its window by more than 2× is excluded —
  unchanged.
- Event exclusion rules: events within 10 minutes of another admitted event
  on the same game (contaminated window); events after first pitch; games
  without a pre-event snapshot inside 90 minutes — unchanged, applied
  identically to this class.

## The family and the correction

**The family's BH-FDR denominator becomes 5 admitted classes, effective
this amendment date (2026-09-02) forward.** Reason: the source-verification
blocker that excluded umpire data from V3 at the 2026-08-31 freeze (recorded
nowhere in `docs/RESEARCH_V3_TIMING.md` itself, since umpires were never
considered a candidate class before this) is resolved, on the same
methodological terms — a forward, grade-B, poll-bracketed capture — that
admitted `lineup_posted`, `starter_scratch`, `hitter_scratch`, and
`il_roster_move` at freeze. BH-FDR at q = 0.10 across the full family (now
5 classes) applies at read time, exactly as `docs/RESEARCH_V3_TIMING.md`
specifies; early deaths at p = 1.0; denominator recorded here at the moment
of admission, per that document's own rule ("denominator = admitted class
count recorded at freeze" — here, at amendment).

## The open question this class does NOT resolve

**This class measures reaction to the MLB-API reveal — not to whatever a
book may have learned earlier from a different, unverified source.**
Public umpire-schedule sites (e.g. crew-chief rotation trackers maintained
outside MLB) may publish assignments before MLB's own API populates
`officials`; if books consume one of those sites, a book's price could move
BEFORE this class's bracket even opens, and this class would read that as
"no reaction to our event" when the correct reading is "the market reacted
to an earlier, unobserved event." No such source is verified, integrated,
or even identified in this repo today — stating the gap plainly is the
honest alternative to quietly assuming MLB's API is the market's first
source, which `docs/RESEARCH_CATALOGUE.md`'s R9 standing rule ("no stated
mechanism survives being written down" unless it is checked) would not
allow anyway. If this class's reaction times come back systematically at or
below the capture-spacing floor (i.e., no measurable latency), one candidate
explanation — not the only one — is that the market already knew from a
faster source; that would be a DESCRIPTIVE note in the eventual writeup,
never promoted to a finding without its own pre-registration.

## What this class does not claim

Same limits `docs/RESEARCH_V3_TIMING.md` states for the whole family, plus
one specific to this class:

- No 2025 contact. No sealed-2026 contact. No bet recommendations. No "edge"
  language.
- **No historical replay.** The MLB API's stated 2015+ historical
  availability for `officials` is not exercised here; this amendment is
  forward-only, exactly like every other class in this family, and for the
  same reason — the historical odds store samples too coarsely for any
  bracket this data could produce to be better than grade C/D.
- **No claim that MLB's API reveal is the crew's true assignment time.**
  It is the time MLB chose to make the crew visible through this endpoint,
  which may lag the crew's actual assignment by an unknown, unmeasured
  amount. The class is named for exactly what it measures.

If this class is null (no measurable latency at `umpirewatch`'s
resolution), that is the result, reported in full, on the same terms the
frozen family document already commits to for the other four.
