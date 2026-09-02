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

## ADDENDUM 2 — 2026-09-02 — CORRECTION AFTER ADVERSARIAL REVIEW

An adversarial methodology review of ADDENDUM 1 (above) returned FAIL on
nine required findings. This addendum corrects all nine, states the
recommended fixes taken, and republishes the read. **ADDENDUM 1 is not
edited** — every number, claim and caveat above stands as originally
written and is superseded, line by line, by what follows. Nothing in the
frozen section (everything above ADDENDUM 1) changes.

**Headline, corrected:** the frozen `il_roster_move` class — properly
scoped to transactions that plausibly affect a club's active roster for a
game it is playing, per the class's own frozen definition — has **not yet
reached its 30-event read floor** (19 of 30). **No primary result is read.**
The confident-looking ADDENDUM 1 read (S(0)=1.000, CI [1.000, 1.000], "p =
0.000") was computed on a broader, wrongly-scoped class — every transaction
id first seen, most of which the frozen definition never intended to
count — and cannot stand as the class's primary finding. The
unfiltered/all-transactions numbers are retained below as a disclosed,
non-promoted SECONDARY/exploratory reading: they are, on this correction's
own re-pull of the join data, directionally consistent with "breadth of
repricing is slow and incomplete" (median diff well above the floor, 15 of
16 clusters on the H1 side, ~83% of events censored at first pitch) — but
that is now explicitly a secondary observation about a class this document
never registered, not a finding about `il_roster_move`. **This is a
"zero survivors" outcome for the pre-registered primary, and it is reported
as exactly that, not manufactured into one.**

### Pinning the read (Finding 8)

Every read below ran inside this worktree, never the main checkout, against:

- **Base commit:** `745117d600caf221c54e5b1ea0c76b59acb790f9`
  (`git rev-parse HEAD`, this worktree).
- **`data/watch/transactions_watch.jsonl`** — sha256
  `8571b90308f2eef9a91010cda43a661cb83dd8ca2429a542d3914058086a44bb`,
  309 lines (143 poll markers, 166 data rows).
- **`data/watch/lineups_watch.jsonl`** — sha256
  `c0317de5b19415751c7d5e7dafa4fc95cd5475d94f41f65ed88ee07afc95ccee`,
  208 lines.
- **`data/watch/probables_watch.jsonl`** — sha256
  `427c23b3568fb8f21cfee4c58ad2a098cfc14d4489aa549203af40695a01625b`,
  192 lines.
- **`data/watch/umpires_watch.jsonl`** — sha256
  `c5689bf9af25db9aa52ce2a1e8bd9482c30c675003d96c9b1a98fe55cb2d43ba`,
  16 lines.
- **`data/processed/odds_multibook.jsonl`** — sha256
  `bcd216b358da2392a77fa1bcd057da4b6e3d52441173d4ccc52b8f9088c2011a`,
  15,774 lines.
- **`data/processed/odds_snapshots.jsonl`** — sha256
  `08ef8b73cb735a047ce169ae150c1b1ef37bca0b168f544fb89c91b9ec771312`,
  5,929 lines.
- **`data/processed/f5_close.jsonl`** — sha256
  `f383d389ea58882dcffa383ffd854958747d20f0c9340045e021427eda430271`,
  264 lines (not consumed by V3; hashed for completeness since it is in
  this worktree's frozen set).

All seven hashes were verified unchanged before and after every test run
and the final `python3 -m src.cli timing --test` invocation below.

**`data/historical/mlb_results.csv` is NOT part of the above frozen set** —
it is gitignored (reproducible from the free MLB schedule endpoint, not
forward-capture evidence) and this worktree's copy of it was empty
(`.gitkeep` only). It is required infrastructure for the game join
(`timingreport._games_by_pk`) and was not frozen at any point, including
for ADDENDUM 1's own read — this is exactly the class of drift Finding 8
warned about ("the reviewer got 168/167 vs the addendum's 166/165 because
capture appended mid-read"), one level up: the JOIN TABLE, not the watch
store, drifted between ADDENDUM 1's read and this one. For this read, a
snapshot was copied read-only from the main checkout (never written to
from there; no git operation touched it) into this worktree at the
identical relative path the code already expects, and hashed exactly like
the other stores: sha256
`683974d6870531b861e2ecd956bc7683617ebb163d95b254a1fce4924eadc744`, 9,365
rows, results settled through **2026-09-01** (today is 2026-09-02; no
sealed-2026 date is touched).

**Exact counts, this read** (`python3 -m src.cli timing --test`, this
worktree): `transaction_first_seen` — 166 events, 165 admissible, **42
measurable** (ADDENDUM 1 reported 56 measurable off the same 166/165 —
the watch store is identical byte-for-byte, so the 56→42 difference is
entirely the join-table snapshot, not a capture or code difference).
`lineup_posted` — 69/69/29 (unchanged from ADDENDUM 1: 1 event short of
its own floor). `hitter_scratch` — 3/3/3. `starter_scratch` — 2/2/0.
`umpire_crew_revealed` — 10 events, 0 admissible (still all first
sightings). As a partial cross-check: recomputing ADDENDUM 1's own (flawed)
distance-based floor logic on this read's 42-event sample reproduces its
exact reported number, **164.87 min**, before this addendum's floor fix is
applied — noted as a data point, not treated as proof the two reads share
identical composition (they do not; the samples differ by 14 events).

### Finding 1 — the class mismatch, and the relevance rule (decided blind)

The frozen `il_roster_move` definition (line 43): *"IL placement/activation,
trade, recall affecting the game."* `rosterwatch._transaction_events`
correctly captures every transaction id first seen (that is its job — grade
-B bracketing does not depend on relevance), but ADDENDUM 1 read that
broader, as-captured stream as if it were the frozen class. It is not: of
the 42 measurable events in this read, only 19 are IL placements,
activations, recalls, or trades.

**The rule** (`src/research/timingtest.py`: `game_relevant`,
`GAME_RELEVANT_TRANSACTION_CATEGORIES`, `NON_RELEVANT_TRANSACTION_CATEGORIES`
— decided from the transaction-type vocabulary alone, before this pass
computed a single reaction time):

| relevant (primary class) | not relevant (secondary only) |
|---|---|
| `il_placement`, `il_activation`, `recalled`, `traded` | `optioned`, `designated` (DFA), `rehab`, `signed`, `il_transfer`, `other` |

Rationale: an IL placement/activation and a recall change who is available
for tonight's game; a trade is the frozen list's own explicit third
category. An option to the minors and a rehab assignment do not touch
tonight's active roster (the player is already off it, or headed there); a
DFA is frequently paperwork trailing a player already out of the picture,
not an in-game roster change; a signing in this feed is overwhelmingly a
minor-league/non-roster move; an IL-to-IL transfer (10-day↔60-day) changes
no availability, since the player was unavailable both before and after.
`other` is the classifier's catch-all — a live spot-check of MLB's raw
`typeDesc` vocabulary found "Assigned", "Selected" and "Released" folding
into it, and a raw "Selected" (e.g., a Rule-5 addition to the active
roster) plausibly belongs on the relevant side by the same logic as
"recalled" — but the stored vocabulary (`data/watch/transactions_watch
.jsonl`'s own `category` field, the only per-event type information this
pinned store carries) cannot separate it from "Released" or misc
paperwork, so `other` and the unrecorded-category rows are both excluded
conservatively rather than guessed into relevance. **This is implemented
additively** — `rosterwatch._transaction_events` now copies the already-
captured `category` field onto the ephemeral event object (never rewriting
a stored row), and `timingtest.game_relevant` reads it; every other class's
events carry no `category` key at all and are therefore always relevant
(the rule can only ever narrow `transaction_first_seen`).

**Resulting counts, this read** (of the 42 measurable transactions):

| category | count | relevant? |
|---|---:|:---:|
| recalled | 8 | yes |
| il_activation | 7 | yes |
| other | 8 | no |
| rehab | 5 | no |
| signed | 4 | no |
| optioned | 3 | no |
| traded | 2 | yes |
| il_placement | 2 | yes |
| il_transfer | 2 | no |
| designated | 1 | no |

**n = 19 relevant, 23 not relevant.** 19 is below the class's own 30-event
floor. The relevant subset was **not** reclassified after seeing this
count — the rule above was fixed before it was ever applied, and it is
reported below-floor precisely because relaxing it now (e.g., folding in
`other` or `signed` to reach 30) would be exactly the outcome-directed
rule-writing pre-registration exists to prevent. The 19-event subset spans
2 calendar dates (2026-08-31, 2026-09-01), 10 distinct `game_pk` clusters,
and 7 matchups, with 5 observed reactions and 14 censored — descriptive
facts only; no test is run on it below the floor, per the family's own
reading rule.

### Finding 2 — the floor (literal bracket width, not distance-to-first-pitch)

ADDENDUM 1 inferred the floor from `minutes_to_start <= 180` (a 15-minute
floor inside that window, 60 minutes outside it) — an inference, not a
reading of the actual poll spacing. `event["interval"]`, threaded through
by `rosterwatch`/`umpirewatch` and now carried onto every measured event as
`event_interval` (`timingreport.report`), already records "the poll
spacing in force at each event" literally (line 165's own words).
`timingtest._floor_from_interval` now reads `interval[1] - interval[0]`
directly; the old distance-based constants and branch are removed.

**Effect, measured on this read's 42-event sample:** every single one of
the 42 events' literal brackets is 14.28–17.56 minutes wide — the dense
capture cadence, uniformly — yet the old distance heuristic assigned the
60-minute hourly floor to 14 of them (28 got 15 minutes, 14 got 60), a
disagreement on 15 of the 42 events (~36%) by more than a minute. ADDENDUM
1's headline sentence ("36 under 15-min / 20 under 60-min", n=56) used the
same flawed method on a different sample and is retracted along with it —
**every measured event's floor in this family, so far, is the dense ~15
-minute cadence, not the hourly 60-minute one.** Recomputed on this read's
sample: the old (wrong) floor logic gives a KM median diff of **164.87
min**; the corrected literal-interval floor gives **209.82 min** — same
direction of correction the reviewer's own recomputation reported (they
found 164.87 → 209.87 on their 56-event sample; this read's 42-event
sample independently lands at 164.87 → 209.82, materially the same
correction).

### Finding 3 & 9 — the primary statistic, and the two KM quantities kept separate

**Two distinct KM quantities, never fused:** `km_median_reaction_minutes`
(time to 50%-of-books reaction, uncorrected for the floor) and
`km_median_diff_minutes` (reaction minus that event's own floor — the
pre-registered quantity, H1: `median(diff) > 0`). ADDENDUM 1's closing
sentence ("measurable ~2.75–3.75 hour median latency") fused the two
(164.87 min diff and 224.87 min reaction) into a fabricated interval that
was never a real confidence interval for anything. That sentence is
retracted; see "Honest interpretation, corrected" below.

**Primary statistic demoted/promoted:** `km_median(diff)` — the thing the
pre-registration actually names — is now bootstrapped directly (clustered
by `game_pk`, 2,000 resamples, seed 20260901), with a resample whose
median is "not reached" coded as **+infinity**, never dropped: it is
evidence the true median is at least that resample's longest follow-up,
which +infinity encodes honestly in a percentile interval (it can only
push the upper bound out). `S(0)` (`median(diff) > 0 ⟺ S(0) > 0.5`) is
retained only as a **supporting note**, flagged `degenerate: true`
whenever its own bootstrap has zero variance (as it did throughout ADDENDUM
1 — every observed diff sat comfortably on one side of the floor, so no
percentile resample could produce a counterexample) — when degenerate,
`timingtest._run` omits `bootstrap_ci95`/`bootstrap_p_one_sided` entirely
rather than emit them as if they meant something.

**This read's secondary (exploratory, all-transactions, n=42) primary
statistic:** `km_median_diff_minutes = 209.82`, bootstrap 95% CI **[180.67,
not reached]** (979 of 2,000 resamples "not reached" — the true median
could not be pinned above ~181 minutes with this sample). `supporting_s0`:
point estimate 1.0, **degenerate: true**, no interval/p-value reported.
(The pre-registered PRIMARY, the 19-event relevant subset, is below its
floor — see Finding 1 — so none of this is computed for it; nothing below
the floor is read.)

### Finding 4 — the p-value (cluster-level exact sign test + rule of three)

"p = 0.000" was a property of the S(0) bootstrap's inability to
extrapolate past its own sample, not a formal test. `timingtest
.cluster_sign_test` replaces it: one vote per `game_pk` cluster (never one
per event — a cluster contributing many events cannot inflate the test's n,
which is exactly the concentration problem Finding 6 documents), classified
"+"/"−"/tied-and-dropped by the sign of every event's diff (or, censored,
its lower bound) in that cluster; an exact one-sided binomial tail, `P(X >=
clusters_plus)` under `Binomial(n, 0.5)`. When the count on one side is
zero, a rule-of-three bound (`~3/n`) is reported alongside the otherwise
uninformative p=1.0.

**This read's secondary reading:** 15 of 16 clusters classifiable (1
mixed-sign, dropped); **15 of 15 favor the H1 side** → exact one-sided
`p = 3.05176e-05` (`0.5**15`, rounded) — small because the evidence really
is that lopsided across independent clusters, not because a bootstrap
could not extrapolate. (The reviewer's own recomputation, on a 20-cluster
sample, reported `p = 9.5e-7`; this read's smaller, differently-composed
cluster set is a materially similar order of magnitude and the same
qualitative result — every classifiable cluster on the H1 side.) The
rule-of-three branch is implemented and unit-tested
(`tests/test_timingtest.py::ClusterSignTestTests`) but not exercised by
this particular read, since no reading here has zero clusters on the H1
side; it activates automatically whenever one does.

### Finding 5 — the false claim in the catalogue

`docs/RESEARCH_CATALOGUE.md`'s L1 row said "every observed and
lower-bounded diff exceeds its floor" — false; ADDENDUM 1 itself already
disclosed one censored lower bound of −6.9 minutes (methodology-review
item 2, still true). The catalogue is corrected in this same change to
restore "consistent with" wording and to reflect this addendum's numbers;
see that file directly.

### Finding 6 — the concentration check (required, never run before now)

`docs/RESEARCH_V3_TIMING.md` lines 120–121 require this and it was never
computed before this correction. Computed here, on this read's own data
(not copied from the reviewer's numbers), via `timingtest._concentration`:

**Secondary/exploratory reading (n=42, the only reading with enough rows
to compute this):** 2 calendar dates (2026-08-31, 2026-09-01); 16 distinct
`game_pk` clusters; 12 distinct matchups, with **DET@MIN alone contributing
8 of the 42 events** (19%); of the 7 *observed* (non-censored) reactions,
only **3 clusters carry any observed reaction at all**, and those 3
clusters carry **100% of the 7 observed reactions** (cluster 823984: 4,
825040: 2, 823908: 1) — the observed (non-censored) half of this reading's
evidence is carried entirely by 3 of 16 clusters. The split-half check
shares 3 clusters (823661, 823908, 825038) across both halves, meaning the
"first half"/"second half" split is not a clean partition by game. **This
is reported as exactly what it is: a result, where one exists at all,
carried by a handful of games and one recurring matchup — not a general
finding**, per line 121's own instruction.

### Finding 7 — the FDR denominator, unified

The three documents disagreed (`timingtest.py`: 4; `RESEARCH_V3_TIMING.md`
line 238: 4; `RESEARCH_CATALOGUE.md`: 4; `RESEARCH_V3_UMPIRE_CLASS.md`:
5). **The rule, stated once and referenced everywhere:** the family
denominator is **monotone non-decreasing** — classes may be admitted, never
removed — and any BH-FDR correction applies the denominator **in force at
the time of that correction**; a class admitted after an earlier read
re-corrects the whole family, already-read p-values included, the next
time the correction is actually computed. At freeze (2026-08-31) the
denominator was 4; the umpire amendment (2026-09-02,
`docs/RESEARCH_V3_UMPIRE_CLASS.md`) admitted a 5th class, so the
denominator has been **5** since that date. `src/research/timingtest
.FAMILY_ADMITTED_CLASSES = 5` is now the single place this number is read
from in code; this document and `RESEARCH_V3_UMPIRE_CLASS.md` both state 5
and cite this rule. No BH-FDR correction is actually computed anywhere in
this addendum — the pre-registered primary class has no p-value to correct
(it is below its own floor; Finding 1) — so this is a consistency fix, not
a promotion.

### Recommended fixes taken

- **(10)** The "pre-event relevance estimate (frozen rule, below)" named
  in the per-event record (line 56) was never defined anywhere and no
  event carries it. Stated here as an acknowledged gap, not silently
  dropped; `docs/RESEARCH_V3_UMPIRE_CLASS.md` line 87's "(frozen rule,
  unchanged)" — which pointed at the same undefined thing — is corrected
  in that file.
- **(11)** Countervailing descriptives, this read's secondary reading
  (n=42): fastest first move **0.02 minutes**; **2** events had a first
  move at or under 15 minutes; the 25%-of-books rung's fastest instance
  was **30.12 minutes**; **3** events had zero books ever move, **15** had
  exactly one. (The reviewer's own recomputation, on their 56-event
  sample, reported 0.0 min / 2 events ≤15 min / 3 zero-mover events / 15
  one-mover events — three of those four numbers match this read's
  42-event sample exactly despite the different join-table snapshot,
  which is a reassuring cross-check on the underlying pipeline; only the
  25% rung's minimum differs, consistent with the two samples' differing
  composition.)
- **(12)** 83.3% of this reading's 42 events are censored (35 of 42, up
  from ADDENDUM 1's 69.6% on its larger sample — both readings show most
  of the evidence is lower-bound-only). Partly explained by the
  ≥6-books-in-90-minutes gate: of the 128 transaction events that mapped
  to a game in this read, 86 (67.2%) were excluded here for too few
  quoting books, which mechanically selects toward games with the
  thinnest, often latest-forming boards — plausibly correlated with games
  closer to first pitch.
- **(13)** `tests/test_timingtest.py` no longer enshrines `p == 0.0` /
  `ci == {1,1}`; `PlantedEffectTests` now asserts the `degenerate` flag and
  the cluster sign test's exact values instead (see that file).
- **(14)** `leadlag.response_table`'s `ladder_medians_minutes` now ships
  alongside `ladder_ns` (`{rung: n}`) — each rung's median comes from a
  different, shrinking subset of events that actually reached that rung,
  which is what produced this read's own impossible-looking ordering
  (100% rung 134.1 min off n=3, faster than the 50% rung's 224.87 min off
  n=7) legible rather than mysterious.
- **(15)** `docs/RESEARCH_V3_UMPIRE_CLASS.md` is corrected to say plainly
  that `umpire_crew_revealed` measures the reveal of the full 4-person
  crew via MLB's `officials` hydrate, not specifically the home-plate
  umpire (which is recorded per event as `home_plate_umpire` but is not
  itself the registered class or mechanism).
- **(16)** The stale-window block, this read's secondary reading: 16.7% of
  events (7 of 42) show a stale book after the 50% quorum moved, median
  stale window 51.54 minutes, median 3 observations while stale
  (`response_table.stale`, printed in full by `timing --test`).

### Honest interpretation, corrected

**The pre-registered primary — `il_roster_move`, correctly scoped to
game-relevant transactions — has 19 of its required 30 events. No result
is read. This is not a null finding and not a positive one; it is
"accumulating," exactly the state `docs/RESEARCH_V3_TIMING.md`'s own
reading rule requires reporting it as.** The secondary/exploratory
reading (every transaction id first seen, n=42, never promoted, never the
frozen class) is, on this read, directionally consistent with **breadth of
repricing being slow and incomplete** — median diff well above the poll
floor, 15 of 15 classifiable clusters on the slow side, most of the
sample censored at first pitch — but it measures a class this family never
registered, is carried disproportionately by 3 of 16 clusters (Finding 6),
and establishes nothing about `il_roster_move` specifically. **What this
correction does NOT establish:** it does not show `il_roster_move` is
slow (too few events to read); it does not show the broader
all-transactions class is slow in general (the result concentrates in a
handful of games); it does not establish a timing edge (no V3 reading ever
could, by the family's own frozen scope); and it does not resolve whether
ADDENDUM 1's confident boundary numbers would have looked different on a
correctly-scoped, floor-clearing sample — that requires more forward
capture, not a re-analysis of what exists today. No promotion decision is
made here, on either reading.
