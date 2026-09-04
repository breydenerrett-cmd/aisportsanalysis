# Pre-registered F5 snapshot timing rule

**Written 2026-09-04, BEFORE the paid re-fetch that closes the timing and
join gaps documented in `docs/F5_BACKFILL_REPORT.md`.** No hypothesis has
been evaluated against this data. This document freezes acquisition
methodology only: which instant a price is drawn from, what counts as valid,
and how the two-layer store is shaped. Nothing here ranks a system, computes
an edge, or looks at a settled outcome.

## 1. Why a rule is needed at all

The first backfill used a fixed wall-clock pair
(`SNAPSHOT_INSTANTS = ("16:50:00Z", "22:50:00Z")`) chosen for slate coverage,
not for a consistent lead time to first pitch. The result, measured on the
2,814 priced + 1,199 zero-book rows already bought:

| lead time to first pitch | n | p10 | p25 | median | p75 | p90 |
|---|---|---|---|---|---|---|
| priced rows | 2,814 | 0.32h | 0.82h | **2.87h** | 21.32h | 24.41h |
| zero-book rows | 1,199 | −2.59h | 18.82h | **23.91h** | 24.57h | 25.92h |

Book depth by lead-time bucket:

| bucket (before first pitch) | mean books | % zero-book |
|---|---|---|
| T−0h .. T−3h | 11.3 | 0.0% |
| T−17h .. T−21h | ~1.2 | ~30% |
| T−24h .. T−27h | ~0.7 | 55–66% |
| after first pitch | 0.01 | 99.5% |

Against a "T−6h..T−30m and ≥5 books" standard, only 987 of 4,013 rows
(24.6%) comply. 1,827 are priced but mistimed (mean 4.5 books — thin, not
zero, but not the standard). 1,199 are zero-book. **The lead time to first
pitch, not the provider, is what determined whether a game had a usable
price.** A fixed wall-clock instant samples a moving target — games start at
different local hours — so it lands anywhere from T−27h to after first
pitch depending on the day's slate. That is the defect this rule closes.

## 2. The frozen rule

**Primary target: T−2:00 before the game's own scheduled first pitch.**

1. Resolve the game's scheduled first pitch (§3) before querying anything.
2. Query the provider's historical snapshot grid (5-minute resolution) for
   the instant nearest `scheduled_first_pitch − 2:00:00`. Snap to the
   nearest grid point; do not round to a convenient wall-clock time.
3. The returned snapshot must be:
   - **Genuinely pregame** — its `commence_time` (or the game's scheduled
     first pitch) must be strictly after the snapshot instant.
   - Carrying **≥5 valid books** for the relevant market (`h2h_1st_5_innings`
     for the F5-moneyline universe).
4. If both hold, the observation enters `F5_TMINUS2_PRIMARY` as a valid row.
5. If either fails at the grid point nearest T−2h, the game is marked
   **`PRIMARY_SNAPSHOT_UNAVAILABLE`** and the rule stops there. It is
   **not** re-queried at T−5h, T−45m, or any other instant to manufacture a
   passing row.
6. "Within provider-grid tolerance" means: the actual instant queried may
   differ from the exact T−2:00:00 mark only by up to one grid step (5
   minutes) on either side, to land on a real snapshot the grid actually
   serves. That is data-availability slack, not a license to slide the
   target hour. A game whose nearest usable snapshot is meaningfully
   earlier or later than T−2h (because the grid has a gap) is
   `PRIMARY_SNAPSHOT_UNAVAILABLE`, not silently re-anchored.

**Sensitivity cohorts are out of scope here.** T−90m and T−60m variants
are legitimate future research questions, but each is its own
pre-registration with its own store and its own multiple-testing ledger.
They must never be merged into `F5_TMINUS2_PRIMARY` or used to backfill a
`PRIMARY_SNAPSHOT_UNAVAILABLE` game under a different name.

## 3. Which timestamp is "scheduled first pitch"

**Anchor field:** `start_time_utc` from `data/historical/mlb_results.csv`,
joined by `game_pk` — the same field `src/board/l1_historical.py` already
treats as canonical for this project (`schedule_commence_time`). This is
MLB StatsAPI's own scheduled time for that specific `game_pk`, captured from
the schedule endpoint, not derived from the final boxscore.

**Why this is safe against leakage from delays and postponements:**

- A **rain delay that pushes the actual first pitch back but does not
  postpone the game** keeps the same `game_pk` and the same scheduled
  `start_time_utc`. The T−2h target is computed from the announced
  schedule, exactly as it was knowable to anyone querying the odds market
  two hours before the advertised time — never from the actual (later) first
  pitch, which was not yet known at query time.
- A **suspended-and-resumed game under the same `game_pk`** keeps its
  original scheduled `start_time_utc` as the anchor for the original start.
  This project's F5 settlement (`src/research/f5_store.py`) already only
  locks a result once StatsAPI marks the game final, so a suspension does
  not corrupt this either.
- A **postponement that is replayed as a separate contest** gets its own
  `game_pk` in StatsAPI (and therefore its own row in `mlb_results.csv`),
  with its own `start_time_utc` for the makeup date. Because this project's
  join key is `game_pk`, not the originally-scheduled date, the makeup
  game's T−2h anchor is its own announced schedule for the makeup date —
  never the original, cancelled date. A true doubleheader created by a
  postponement (two games, same day, same team pair) is handled by the
  `game_pk`-keyed join fixed in §5 below, exactly like any other
  doubleheader.
- **Never use `commence_time` from the odds feed's event payload as the
  anchor for deciding whether T−2h passed.** It is preserved (§4) because it
  is useful corroboration and is itself a form of "scheduled time as known
  by the provider at query time," but the project's own schedule
  (`mlb_results.csv` / StatsAPI) is the system of record for grading and
  must be the one used to compute the T−2h target, so that the target is
  identical regardless of which provider is later queried for price.
- **Never use an "actual first pitch" timestamp (from a boxscore or
  play-by-play feed) to decide whether a snapshot is pregame or to compute
  lead time.** That number is not knowable at the time the snapshot would
  have been taken and using it would leak future information into a
  quantity ("was this snapshot 2 hours before first pitch") that must be
  computable from data available at query time alone.

## 4. What is preserved on every observation (never collapsed)

Every row in both stores carries all of:

- `game_pk` (join key to `mlb_results.csv` and to settlement)
- `scheduled_first_pitch` — `start_time_utc`, resolved per §3
- `actual_first_pitch` — if available from settlement data, kept purely as
  informational/audit metadata, never used to gate validity or compute lead
  time
- `commence_time` — the odds feed event's own stated commence time, kept as
  provider corroboration only (§3)
- `query_instant` — the wall-clock instant this run asked the provider for
  (the T−2h target before grid-snapping)
- `snapshot_at` — the provider's own timestamp for the returned historical
  snapshot (post grid-snap; this is what "T−2h" actually resolved to)
- `lead_time_hours` — computed as `scheduled_first_pitch − snapshot_at`,
  derived, never stored as the sole timing fact
- per-book `last_update` and per-market `last_update` timestamps, exactly as
  the provider returns them inside `data.bookmakers[].markets[].last_update`
  — never flattened or averaged away
- `book_count` at that snapshot, computed, not asserted
- `status` — `OK` or `PRIMARY_SNAPSHOT_UNAVAILABLE` (§2.5), plus a `reason`
  string for the latter (`no_grid_point_within_tolerance`,
  `fewer_than_5_books`, `not_pregame`, `game_pk_missing_from_schedule`, etc.)

Timing metadata is **never** collapsed into a single "closing line" or
averaged across books. Every book's own timestamp rides with its own price.

## 5. Two-layer storage

### `F5_RAW_HISTORY` — immutable, append-only

Every observation ever acquired for F5, at whatever instant it was queried,
under whatever rule was in force at the time. This includes:

- The existing 4,034 rows already in `data/historical/odds_first_five/` from
  the first backfill's fixed wall-clock instants (2,814 priced, 1,199
  zero-book, in the 2023-05-10..2024-10-07 window plus the pre-window rows
  already held) — **not overwritten, not deleted, not re-labeled**. They
  remain genuine data: a record of what price (or absence of one) existed at
  a *different*, non-T−2h lead time, which is itself a legitimate
  microstructure research asset (how fast books post, how depth builds
  toward first pitch) once its own pre-registration is written.
- Every new T−2h-targeted observation acquired under the paid repair,
  appended alongside, keyed so it is distinguishable from the earlier rows
  (the acquisition rule/version travels with the record, not just the
  timestamp).
- Every `PRIMARY_SNAPSHOT_UNAVAILABLE` result, recorded as an explicit row
  with its `reason` — a miss is data, never silently dropped (mirrors the
  project-wide rule already in force for `unmatched`/`failed` games in
  `src/pipeline/backfill.py`).

Physically: the existing `data/historical/odds_first_five/mlb_*.jsonl` files
stay exactly as they are (append-only; this document does not touch a single
odds record in them). New T−2h acquisitions are appended to the same
game_pk-keyed store, distinguished by an explicit rule/version tag on each
record (e.g. `snapshot_rule: "tminus2_v1"` vs. the untagged/legacy rows,
which are implicitly the original fixed-instant rule) so a reader can always
tell which acquisition rule produced which row without inferring it from the
timestamp alone.

### `F5_TMINUS2_PRIMARY` — the standardized research view

Derived, not independently acquired: built by filtering `F5_RAW_HISTORY` to
rows tagged with the T−2h rule (§2) with `status: OK`. This is the only
store the primary F5-moneyline research universe reads from. Schema (one row
per `game_pk`):

```
game_pk, date, away_team, home_team,           # identity (canonical abbrevs)
scheduled_first_pitch, actual_first_pitch,      # §3 / §4
query_instant, snapshot_at, lead_time_hours,    # §4
book_count, books: [{key, last_update,          # §4, per book
                      h2h_1st_5_innings: {away_price, home_price, last_update}}],
status, reason,                                 # OK or PRIMARY_SNAPSHOT_UNAVAILABLE
snapshot_rule                                   # "tminus2_v1", pinned
```

A game that is `PRIMARY_SNAPSHOT_UNAVAILABLE` still gets a row here (with
null pricing fields) so the denominator for any later evaluation is the full
named universe, not just the games that happened to price — silent
survivorship in the denominator is exactly the failure mode T8 in
`docs/RESEARCH_CATALOGUE.md` exists to prevent.

This view is rebuildable at any time by re-running the filter over
`F5_RAW_HISTORY`; it is never hand-edited and never the place new data is
written.

## 6. Totals exclusion

The 1,886 `totals_1st_5_innings` rows that arrived free in the same
payloads (F5 moneyline was the only authorized market) are preserved in
`F5_RAW_HISTORY` exactly as fetched. They are:

- **Excluded from `F5_TMINUS2_PRIMARY`** — that view is moneyline-only by
  construction (§5's schema has no totals fields).
- **Excluded from the F5-moneyline research universe's multiple-testing
  denominator.** Nothing that tests or ranks systems against F5 moneyline
  may count a totals observation as part of "how many things were tried" or
  "how many games were available," in either direction.
- Available for their own future pre-registration if F5 totals scope is
  ever authorized. Until then they are inert: on disk, never read by any
  evaluation path.

## 7. What this document does not do

No game has been re-queried under this rule yet. No book depth, price, or
outcome from any T−2h observation has been looked at. The next step is
acquisition (the paid repair, a separate authorization) strictly following
§2–§5, then joining to settlement, then only after that — discovery.

---

# CLARIFICATION — 2026-09-04, appended after the sanity tranche

**The frozen rule above is unchanged.** This is a record of observed provider
behaviour, appended rather than edited, so the original pre-registration
stands exactly as written when it was frozen.

- The **intended target remains scheduled first pitch − 2h.**
- The **accepted tolerance remains ±5 minutes.**
- The provider serves a **five-minute historical grid.**
- Observed behaviour: the grid **floors to the preceding grid point.**
- Therefore returned observations **systematically land slightly earlier
  than exact T−2h.** Measured across the 20 priced tranche games: deviation
  min −4.38 min, median −4.35 min, max −1.37 min. Every observation early,
  none late, all inside the ±5-minute tolerance.
- This was discovered **during the pre-registered sanity tranche, before the
  full acquisition** — not after seeing any result.
- **No timing threshold, window, book-depth rule, or eligibility rule was
  changed in response.** The offset is uniform across games, so it introduces
  no relative bias between them; it is recorded here for accuracy, not
  accommodated.

A reader should therefore understand "T−2h ±5min" in this document as, in
practice, *the grid point at or before T−2h, within five minutes of it.*
