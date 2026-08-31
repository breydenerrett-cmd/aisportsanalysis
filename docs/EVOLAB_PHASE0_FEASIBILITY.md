# Evolution Lab — PHASE 0 feasibility and data-availability audit

What a deterministic point-in-time replay engine can HONESTLY serve at an
arbitrary historical timestamp T, and what it cannot. Measurement only: no
engine was built, no code changed, no store written, no credit spent, no
network call made. The only new file in the tree is this document.

Measured 2026-08-31 against the stores as they stand. Every number below was
computed by reading the stores through the project's own readers
(`backfill.read_season`, `pricepath.build`, `matrix.read`,
`backfill.price_pair`, `selections.index_price_pairs`) or by direct JSONL scan.

**Evidence boundaries observed.** 2026-01-01..2026-08-27 is SEALED and was not
read — the forward stores (`data/processed/odds_multibook.jsonl`,
`data/processed/odds_snapshots.jsonl`, `data/watch/*`) were listed but never
opened. 2025 is tuning-only: its coverage is reported in §1 and §4 as a
capacity fact and is analysed nowhere.

**Cross-check that the measurement is right.** Reconstructing the funnel's own
priced universe from the stores independently returns **4,395** games —
identical to the figure published in `docs/RESEARCH_CATALOGUE.md` for Family
V1. The instrument reproduces a known number before it reports new ones.

---

## The five answers, up front

| question | answer |
|---|---|
| Replay universe (matrix row AND usable odds, 2023–24) | **4,819 games** |
| Odds granularity | **Not one observation per game — median 4 (2023) / 3 (2024) distinct pre-game instants. But the finest spacing anywhere in the store is 177 minutes.** |
| Best-price execution defensible? | **Yes at the instant level** — quotes are a genuine simultaneous cross-section, not a stitch. But *which book* is best is a coin-flip in 63–79% of instants (ties). |
| Defensible close | Only for a minority: last observation is inside T-30 for **27.4% / 25.2%** of games, inside T-60 for **40.8% / 40.8%**. |
| Biggest limitation | **No lineup or probable-pitcher posting timestamps exist for 2023–24.** Every lineup-conditioned feature has an unknown earliest-available time. |

---

## 1. Historical odds granularity, 2023–24

**Store.** `data/historical/odds_history/mlb_{season}.jsonl`. One JSON record
per API snapshot: `{requested_at, snapshot_at, markets, events[]}`, each event
carrying `bookmakers[] -> markets[] -> outcomes[]`. **600 records per season**
= 200 dates × the three requested UTC times in `backfill.DEFAULT_SNAPSHOT_TIMES`
(16:50, 22:50, 01:50). That grid is the ceiling on everything in this section.

The API serves the nearest stored snapshot to the requested instant, so
`requested_at` and `snapshot_at` differ: median lag **4.3 min**. In 2023, 28
records were served by a snapshot far outside the requested window (max 27.7
days — pre-season requests before the API had any MLB board), collapsing 600
records onto **572 distinct served instants**. 2024 and 2025 have 600 distinct
instants each. `snapshot_at`, never `requested_at`, is the replay clock.

### Observations per game (pre-game h2h only)

| | 2023 | 2024 | 2025 (coverage only) |
|---|---|---|---|
| events in store | 2,491 | 2,486 | 2,500 |
| events with ANY pre-game h2h observation | **2,475 (99.4%)** | **2,472 (99.4%)** | 2,492 (99.7%) |
| events with **≥2 distinct instants** | **2,263** | **2,320** | 2,404 |
| distinct instants per event: min / p25 / median / p75 / p90 / max | 1 / 3 / **4** / 5 / 5 / 11 | 1 / 3 / **3** / 4 / 4 / 23 | 1 / 3 / 3 / 4 / 4 / 24 |
| price rows per event (book × instant): p25 / median / p75 / max | 37 / **46** / 58 / 159 | 25 / **33** / 40 / 205 | 26 / 30 / 38 / 190 |

Distribution of distinct-instant counts:

- 2023 — 1: 212, 2: 245, 3: 296, **4: 965**, 5: 687, 6: 54, 7+: 16
- 2024 — 1: 152, 2: 176, **3: 973**, **4: 1,004**, 5: 126, 6+: 29

### Books per observation

| | 2023 | 2024 | 2025 |
|---|---|---|---|
| distinct books in season | 19 | 14 | 11 |
| books per instant: p25 / median / p90 / max | 8 / **16** / 19 / 19 | 8 / **10** / 14 / 14 | 7 / 10 / 11 / 11 |
| books at the LAST pre-game instant (median) | 17 | 12 | 11 |
| instants meeting the 6-book consensus floor (`prices.MIN_BOOKS`) † | 7,389 / 9,180 (80.5%) | 7,337 / 8,376 (87.6%) | — |

† The book-count quartiles above are over every pre-game instant in the store
(n = 9,357 / 8,585 / 8,845). The 6-book-floor row and every window count in
this document are over instants belonging to *joined* odds events (n = 9,180 /
8,376), i.e. the replay universe of §5. Those counts are per odds **event**;
six events across the two seasons share a `game_pk` with another event (hazard
H5), so event counts run 0.2% above distinct-game counts.

Book rosters change across seasons (foxbet, sugarhouse, circasports, barstool,
twinspires present in 2023 and gone by 2025; fanatics appears in 2025). A
strategy gene naming a specific book is season-confounded by construction.

### Spacing between consecutive observations — THE binding constraint

Minutes between consecutive pre-game instants for the same game:

| | n | min | p25 | median | p75 | max |
|---|---|---|---|---|---|---|
| 2023 | 6,767 | **177.1** | 180.0 | 360.0 | 900.0 | 2,880 |
| 2024 | 5,964 | **179.9** | 180.0 | 360.0 | 900.0 | 1,080 |

**There is no pair of observations anywhere in 2023–24 closer together than
2 hours 57 minutes.** The median gap is six hours.

### Is there a defensible close?

Time from the last pre-game observation to first pitch, over the replay
universe (§5):

| | min | p25 | median | p75 | p90 | max |
|---|---|---|---|---|---|---|
| 2023 | 4.3 | 29.3 | **84.3** | 179.4 | 349.4 | 1,794 |
| 2024 | 0.4 | 29.4 | **85.4** | 199.4 | 354.3 | 919 |

Fraction of the universe whose last observation falls inside a window before
first pitch (the ≥6-book column is within one game of the any-books column
throughout, so the close is never thin when it exists):

| window | 2023 | 2024 |
|---|---|---|
| T-30 | 660 (27.4%) | 609 (25.2%) |
| T-60 | 984 (40.8%) | 983 (40.8%) |
| T-120 | 1,466 (60.8%) | 1,450 (60.1%) |
| T-240 | 2,093 (86.7%) | 2,089 (86.6%) |
| T-480 | 2,360 (97.8%) | 2,371 (98.3%) |

`backfill.closing_prices` already carries `closing_gap_minutes` per game and
`docs/COLLECTION_POLICY.md` already calls this an approximation. It is: a
"close" at a median of 85 minutes out, and worse than T-2h for four games in
ten.

### VERDICT

**It is NOT one observation per game.** 91% (2023) and 94% (2024) of priced
games carry two or more observations at different times, so the kill condition
in `docs/EVOLUTION_LAB_ASSESSMENT.md` §PHASE 0 does **not** fire and the lab is
not reduced to static features.

**But the granularity is coarse and the practical conclusion is nearly as
restrictive.** Concretely, for 2023–24:

- **TESTABLE:** slow, multi-hour drift. "Was the price at T-12h different from
  the price at T-2h, and does that difference predict anything." The median
  game supports three to four such reads.
- **NOT TESTABLE, at all:** anything with a resolution finer than ~3 hours.
  Steam moves, minute-scale lead/lag between books, reaction to a news event,
  reaction to a lineup posting, opening-line-to-first-move, or any
  closing-line-value measure that needs a true close. The store has no
  observation pair closer than 177 minutes and cannot be made to have one
  without buying the 5-minute historical grid (priced in
  `docs/COLLECTION_POLICY.md` at 10 credits/event/snapshot).
- **NOT TESTABLE:** intraday execution timing genes ("bet at T-90 rather than
  T-30"). 24.6% (2023) / 25.2% (2024) of the universe has no observation at all
  between T-180 and first pitch, and 43.6% / 45.1% has none inside T-90; the
  engine cannot serve a price the strategy asks for and would have to fabricate
  one.

So: timing-sensitive strategies are backtestable only in the coarse sense, and
the timing gene's alphabet is at most {T-24h-ish, T-12h-ish, T-6h-ish,
last-available}, unevenly populated per game. Any finer gene is unbacktestable
and must not be admitted to the genome.

---

## 2. Simultaneity of quotes — is "best available price" real?

**Structurally, yes: the quotes are not stitched.** Every book quoting a game
at one instant arrives inside a single API response with a single
`snapshot_at`. There is no assembly step in which one book's 16:45 price is
compared against another's 22:45 price. `pricepath.snapshots()` regroups by
`snapshot_at` and returns exactly that cross-section, and `prices.snapshot()`'s
docstring already forbids mixing instants.

**Empirically, the quotes are also fresh.** Each bookmaker carries its own
`last_update`. Measured over every pre-game h2h quote:

| | n | median | p75 | p90 | max |
|---|---|---|---|---|---|
| staleness (`snapshot_at` − book `last_update`), min — 2023 | 114,601 | 0.6 | 0.9 | 1.8 | 14.8 |
| staleness, min — 2024 | 81,199 | 0.6 | 1.0 | 1.6 | 15.0 |
| spread of `last_update` ACROSS books at one instant, min — 2023 | 8,059 | 1.9 | 3.5 | 4.8 | 14.7 |
| spread across books at one instant, min — 2024 | 8,184 | 1.1 | 2.1 | 4.6 | 14.0 |

No quote anywhere is more than 15 minutes stale relative to its own snapshot.
Half the boards have every book refreshed inside a 2-minute window.

**Conclusion: a "best price across the board at instant S" is a defensible
statement about 2023–24.** It describes prices that were simultaneously on the
board, within a few minutes of each other, at a single named instant. This is
the one execution-realism question that comes back clean, and it is the
foundation the price-improvement product needs.

**Three limits that must be stated with it.**

1. **The best price is usually tied, so the *book* is arbitrary.** In
   **62.7%** of 2023 instants and **78.6%** of 2024 instants, at least two
   books share the best price on at least one side. Any strategy or report
   naming "the book that had the best number" is naming an artifact of
   iteration order in the majority of cases (see hazard H3). The best *price*
   is real; the best *book* usually is not.
2. **Takeability at stake is not measured and cannot be.** The store has no
   limits, no bet-acceptance record, and no account state. "On the board" is
   the strongest claim available; "takeable at size" is not measurable from any
   data we hold or could buy.
3. **12–20% of instants are below the 6-book consensus floor** and a consensus
   computed there is a handful's opinion, per `prices.MIN_BOOKS`.

Not measured: latency between a book's own price change and the API observing
it. That would need a second independent feed and is not obtainable
retrospectively.

---

## 3. Feature availability at T

**The point-in-time audit is `src/model/pointintime.py`** — the audit is data,
not a convention: each input declares `clean`/`leaky` with a reason, detectors
inherit the worst status of their inputs, and `selections.clean_detectors`
refuses anything not clean. The three rebuilt inputs the matrix uses
(`rebuilt_splits`, `rebuilt_arsenals`, `rebuilt_matchup`) plus `lineups` and
`market` are all `CLEAN`; the three live-fetch endpoints (`splits`,
`arsenals`, `matchup_history`) are `LEAKY` and the matrix does not touch them.

Enforcement is tested, not asserted: `tests/test_validation_pit.py` —
`test_data_dated_after_the_game_cannot_move_the_row`,
`test_data_dated_on_game_day_cannot_move_the_row`,
`test_repeated_builds_are_byte_identical`,
`test_sealed_seasons_are_refused_before_any_data_is_read`; and
`tests/test_matrix_v5_features.py` — `test_pitches_after_game_day_cannot_move_
the_row`, `test_pitches_between_cutoff_and_game_cannot_move_the_row`,
`test_build_is_deterministic`. Family V4's whole published run reproduced
bit-for-bit (`docs/REPRODUCIBILITY_AUDIT_V4.md`).

**The cutoff structure.** `matrix._cutoff_for` anchors every game to the first
day of its own month. Measured cutoff-to-game-date lag: min 0, **median 15**,
max 30 days, both seasons. So every accumulator-derived feature is
under-informed by up to a month and over-informed by nothing.

### Feature vs earliest-available-time class

Coverage is **both sides answer** (half a differential is not a differential),
over 2,430 matrix rows in 2023 and 2,429 in 2024.

| feature | inputs | earliest available at | timestamp in store? | 2023 | 2024 |
|---|---|---|---|---|---|
| `game_pk`, `date`, `away/home_team`, `start_time_utc` | results CSV (schedule) | **A. Schedule publication** — months ahead | yes (`start_time_utc`, 0 rows missing) | 100% | 100% |
| `starter_platoon_gap` | rebuilt splits × opposing probable | **C. max(month cutoff, probable announcement)** | cutoff: yes. announcement: **NO** | 33.7% | 70.5% |
| `starter_velocity_gap` | rebuilt fastballs × opposing probable | **C** | same | 54.6% | 75.1% |
| `starter_groundball_share` | rebuilt batted balls × opposing probable | **C** | same | 60.1% | 84.6% |
| `primary_pitch`, `primary_pitch_share` | rebuilt pitch mix × opposing probable | **C** | same | 75.1% | 92.0% |
| `top_minus_bottom` | posted lineup × rebuilt batter wOBA | **D. Lineup posting** (~T-3h to T-4h) | **NO** | 99.1% | 100.0% |
| `lineup_platoon_share` | posted lineup × handedness × opposing probable hand | **D** (needs C too) | **NO** | 100.0% | 99.9% |
| `lineup_vs_primary_pitch` | posted lineup × rebuilt arsenal × opposing probable | **D** (needs C too) | **NO** | 75.0% | 91.6% |
| `lineup_vs_starter_history` | posted lineup × rebuilt matchup × opposing probable | **D** (needs C too) | **NO** | 13.7% | 50.7% |
| h2h price / de-vigged consensus | odds store | **B. Named snapshot instant** — exact | **yes**, `snapshot_at` | see §1 | see §1 |

Class **B** is the only class with an exact, store-recorded availability time.
Class **A** is safe by inspection. Classes **C** and **D** are the problem.

**The two gaps, stated plainly.**

- **No lineup posting timestamp exists for 2023–24.** `data/historical/lineups.jsonl`
  rows are `{date, game_pk, away[], home[]}` — the lineup that was posted, with
  no record of *when*. `lineup_store` fetched them per date, retroactively. A
  replay can therefore never prove a lineup-conditioned decision was made after
  the lineup existed; it can only assume a nominal posting time. The forward
  `rosterwatch` store does carry `fetched_utc`, but only from 2026-08 onward —
  it cannot repair 2023–24.
- **No probable-pitcher announcement timestamp exists either, and the stored
  value is the actual starter.** `away_probable_id` / `home_probable_id` come
  from the MLB schedule's `probablePitcher` hydrate
  (`src/providers/mlb.py:163`), fetched retroactively for completed games. For
  a finished game that field reflects who actually started. A late scratch is
  therefore invisible, and every class-C feature silently assumes the announced
  probable equalled the actual starter. Magnitude not measured — it would take
  an archived probables feed with fetch timestamps for 2023–24, which does not
  exist and cannot be bought.

**Consequence for the replay engine.** A replay at time T can serve class A and
class B honestly and exactly. It CANNOT honestly serve class C or D at a stated
T; it can only serve them under a declared assumption ("lineups assumed posted
at T-3h", "probables assumed correct"). That assumption must be a named,
versioned parameter of the engine and must appear on every result the lab
produces. It must never be silent.

**And the assumption collides with §1.** If lineups are assumed to post at
T-3h, a lineup-conditioned strategy needs a price observation inside T-180.
Measured over the replay universe:

| observation exists inside | 2023 | 2024 |
|---|---|---|
| T-240 | 2,093 (86.7%) | 2,089 (86.6%) |
| T-180 | 1,820 (75.4%) | 1,804 (74.8%) |
| T-150 | 1,562 (64.7%) | 1,532 (63.5%) |
| T-120 | 1,466 (60.8%) | 1,450 (60.1%) |
| T-90 | 1,361 (56.4%) | 1,323 (54.9%) |

So a strategy that conditions on the posted lineup and executes after it posts
has an executable universe of roughly **3,600 games** (T-180 assumption), not
4,819 — and the surviving subset is not random: it is the games whose first
pitch happened to fall shortly after 16:50, 22:50 or 01:50 UTC. That is a
start-time-selected sample, and start time correlates with day-of-week, coast,
and getaway games. **This selection must be reported with any lineup-conditioned
result.** It is not measured here how much that biases anything; measuring it
would mean comparing the T-180-served subset against the full universe on
outcome and price, which is a Phase 1 diagnostic.

---

## 4. Market availability

**Historical h2h/totals store.** All 1,800 records across the three seasons
were requested with `markets=['h2h','totals']`. Nothing else is in the file.

| market | 2023 | 2024 | 2025 |
|---|---|---|---|
| `h2h` — events with a pre-game quote | 2,475 / 2,491 (99.4%) | 2,472 / 2,486 (99.4%) | 2,492 / 2,500 |
| `totals` — events with a pre-game quote | 2,473 (99.3%) | 2,470 (99.4%) | 2,489 |
| `spreads` (run line) | **absent** | **absent** | **absent** |

Totals carry a `point` on every single outcome (0 missing, all seasons); 53
distinct lines in 2023, 45 in 2024, most mass on 8.5 / 8.0 / 9.0 / 7.5.

**First-five store** — `data/historical/odds_first_five/`, a probe, not a
backfill:

| | 2023 | 2024 | 2025 |
|---|---|---|---|
| game records | 265 | 189 | 207 |
| records with any book | **185** | **133** | 172 |
| snapshots per game | **1** (always) | **1** | **1** |
| games with a PRE-GAME snapshot carrying books | **167** | **123** | 163 |
| markets | `h2h_1st_5_innings`, `totals_1st_5_innings` | same | same |

Manifest: 674 entries, 16 marked `unavailable_at_date`.

### What this bounds

- A replayed strategy may route to **h2h** (full universe) and **totals** (full
  universe, with a line).
- It may **not** route to spreads/run line — no such data was ever bought.
- It may route to **F5 h2h / F5 totals only on ~290 games across 2023–24, at
  exactly one observation each.** That is static-feature-only territory: no
  timing, no movement, no close, and a sample far below anything that could
  discriminate. The V1 idea N9 (full-game minus F5 price gap as the market's
  bullpen opinion) is therefore backtestable on at most ~290 games at one
  instant, which the §1 arithmetic in `docs/EVOLUTION_LAB_ASSESSMENT.md` says
  is not enough for an ROI verdict.
- Props, alternate lines and any 5-minute grid: never purchased, priced in
  `docs/COLLECTION_POLICY.md`, and forbidden without a registered hypothesis.

---

## 5. Game coverage join — the replay universe

| | 2023 | 2024 | total |
|---|---|---|---|
| matrix rows (games with a posted lineup) | 2,430 | 2,429 | **4,859** |
| odds events joined to a played game (`pricepath.build_report`) | 2,413 | 2,412 | 4,825 |
| — distinct `game_pk` behind those events | 2,408 | 2,411 | 4,819 |
| — odds events that could NOT be joined | 62 | 60 | 122 |
| — quotes dropped for being at/after first pitch | 1,792 | 1,699 | 3,491 |
| **matrix row AND usable odds** | **2,408** | **2,411** | **4,819** |

# THE REPLAY UNIVERSE IS 4,819 GAMES.

That is the denominator for every power calculation the lab makes. It is 99.2%
of the 4,859 matrix games — the odds join is not the binding constraint on
sample size; the two-season window is.

Nested subsets, which are the real denominators for anything conditional:

| subset | 2023 | 2024 | total |
|---|---|---|---|
| replay universe | 2,408 | 2,411 | **4,819** |
| …with ≥2 distinct pre-game instants (any timing question) | 2,211 | 2,271 | **4,482** |
| …with a distinct T-360 / close pair (what the funnel uses today) | 2,161 | 2,234 | **4,395** |
| …with a ≥6-book board inside T-180 (lineup-conditioned execution) | 1,820 | 1,804 | **3,624** |
| …with a ≥6-book board inside T-30 (defensible close) | 660 | 609 | **1,269** |

The 4,395 figure reproduces the published Family V1 priced count exactly.

The last row is the one to keep in view. A CLV-primary fitness, as
`docs/EVOLUTION_LAB_ASSESSMENT.md` §3.1 specifies, needs a defensible true
close. Against a T-30 definition that is **1,269 games**, not 4,819 — and §3.1's
own arithmetic asks for ~144 selections at a +0.5pp effect, so a strategy firing
on 10–20% of games would take 127–254 selections out of 1,269. That is at or
just past the edge. Against a looser T-60 close it is 1,967 games, and against
T-120 it is 2,916. **The close definition is a power decision, not a
formatting one, and it should be fixed and written down before Phase 2 runs.**

---

## 6. Determinism hazards

Each is a bug the engine must design around. Numbered for citation.

**H1 — `discovery.clustered_bootstrap` depends on ROW ORDER, not just row
content.** `dates = list(by_date)` takes dict-insertion order, and
`rng.randrange(len(dates))` indexes into that list. The seed is fixed but the
list it indexes is not. Demonstrated on identical data, reordered:
CI `-0.03137 .. 0.08461` vs `-0.03251 .. 0.08817`. This is the most dangerous
hazard here because it is silent and it lands directly on the published
interval. Fix: `dates = sorted(by_date)`.

**H2 — floating-point accumulation order.** `clustered_two_sided_p` sums over
`clusters = list(by_date.values())`; `funnel._measure` sums `_diff` over row
order; `selections._fair` and `prices.snapshot` average de-vigged probabilities
over quote order. Demonstrated: p = `0.36053292380330726` vs
`0.36053292380330704` on identical data reordered. Small, but "byte-level
determinism across runs" (Phase 1 acceptance) fails on it. Fix: sort before
reducing, or use `math.fsum`.

**H3 — ties in best-price selection, in 63–79% of instants.**
`prices.snapshot` keeps the first book at the best decimal (strict `>`), and
`prices.latest_instant` returns `list(by_book.values())` in store-row order, so
the winner is decided by file order. Measured: 5,755 / 9,180 instants (62.7%)
in 2023 and 6,583 / 8,376 (78.6%) in 2024 have a tie on at least one side. Fix:
deterministic tie-break (lowest book key), and never let a genome condition on
book identity at the best price.

**H4 — duplicate served snapshot instants.** The API can serve the same
snapshot for two different requested times. Measured duplicate
(event, `snapshot_at`) pairs: 28 across 3 events (2023), 2 across 2 events
(2024), 4 across 4 events (2025). Every duplicate is byte-identical on h2h
today, so no price conflict exists — but `pricepath._build` appends both, so
that instant's board holds a book twice and any consensus mean weights it
double. Fix: dedupe on (event_id, snapshot_at, book) at read time.

**H5 — one game, several odds events.** 5 `game_pk`s in 2023 and 1 in 2024
have more than one odds event resolving to them. `_resolve` picks the nearest
`commence_time` with no tie-break; equal gaps would resolve by iteration order.
Fix: explicit tie-break on `event_id`.

**H6 — file-order tie-break in the price selectors.** `backfill.price_pair`
and `backfill.closing_prices` both use strict `gap < current_gap`, so among
records with an equal gap the first one READ wins. The store is append-only and
built resumably, so read order is a property of how the backfill was run, not
of the data. Fix: tie-break on `snapshot_at` then `event_id`.

**H7 — resumable-build state can mark a date "done" while incomplete.**
`matrix._covered_dates` treats any date appearing in the file as built.
`matrix.build` flushes once per date, so a crash mid-date can leave a partial
date permanently marked covered, and a truncated final line raises
`MatrixError` (fail-loud, at least). Row order in the file follows build order
and therefore feeds H1/H2 — `funnel.run` consumes `list(matrix.read(s).values())`.
Verified today: both matrix files are date-monotone (182 and 185 date blocks,
each date contiguous and in order), so the current artifacts are fine. Fix: the
engine sorts rows by (date, game_pk) on read and does not trust file order.

**H8 — undated and marker rows.** Checked: 0 matrix rows missing `date`, 0
missing `start_time_utc`, in both seasons. `{"date":…, "empty":true}` coverage
markers exist and `matrix.read` skips them correctly. `pricepath` drops events
with an unparseable `commence_time` silently. Fix: the engine counts drops in a
manifest rather than dropping quietly.

**H9 — wall-clock reads.** Every one of these calls `datetime.now`:
`snapshots._timestamp`, `funnel.register_family`, `model/family.py:91`,
`model/seal.py:96,142`, `pipeline/ledger.py:220`, `pipeline/grading.py:385`,
`pipeline/scanlog.py:327`, `pipeline/dense.py:142,184,533`,
`pipeline/rosterwatch.py:109,565`, `pipeline/briefing.py:301`,
`pipeline/health.py:706`, `detect/dossier.py:39`, `report/dashboard.py:91`,
`report/archive.py:252`, `cli.py:749,1244,1588,1626`, plus
`providers/odds.py:695`, `providers/weather.py:183,219`,
`providers/statcast.py:125`. All but the three provider calls accept an
injected `now`/clock. Fix: the replay injects a clock everywhere and calls no
provider — a network read inside a replay is both a wall-clock leak and a
credit leak.

**H10 — BH rank ties.** `family.benjamini_hochberg` sorts by p with Python's
stable sort, so among tied p-values the rank follows input (spec) order. Dead
specs all enter at p = 1.0, so ties are common. They never survive, so nothing
is wrong today — but a genome enumeration that produces genuinely tied p-values
at the cutoff rank would resolve by enumeration order. Fix: sort by (p, name).

**H11 — set iteration.** Audited `matrix.py`, `funnel.py`, `pricepath.py`,
`selections.py`, `prices.py`, `snapshots.py`: no unsorted set iteration reaches
an output. `matrix.build` uses `sorted({cutoffs})`; `pricepath` sorts quotes by
(`snapshot_at`, `book`) and paths by (`commence_time`, `event_id`);
`selections.clean_detectors` uses `sorted(registry.items())`. Clean, and the
engine should keep the property under test rather than by habit.

**H12 — American-odds comparison.** `selections._fair` takes
`max()` over raw American integers for the best price. That is monotone in
payout across the sign boundary, so it is correct — except that ±100 are the
same decimal and `max` prefers +100. Fix: compare decimals in the engine, as
`prices.snapshot` already does.

**H13 — the two assumption parameters from §3** (nominal lineup post time,
probable = actual starter) are not non-determinism, but they are the same class
of hazard: an unstated input that silently changes results. They must be
engine parameters with defaults recorded in every artifact.

---

## 7. What the replay may and may not reveal — the acceptance table

| the replay MAY | the replay MAY NOT |
|---|---|
| Serve the exact multi-book board at any of the ~600 named instants per season | Serve a price at an arbitrary T; there is nothing between instants and interpolating one would be fabrication |
| Report a best available price at an instant as simultaneously on the board | Report *which book* held it as meaningful (63–79% ties) |
| Serve class A (schedule) and class B (market) facts with exact availability times | Serve class C (probable-dependent) or class D (lineup-dependent) features at a *proved* availability time — only under a declared assumption |
| Test coarse multi-hour price drift on 4,482 games | Test anything with resolution finer than 177 minutes: steam, lead/lag, news reaction, lineup-post reaction |
| Route to h2h and totals across the full universe | Route to spreads (never bought), or to F5 beyond ~290 games at one observation each |
| Measure movement to a T-30 close on 1,269 games | Call a T-85 median observation "the close" without the gap attached |
| Reproduce Family V1's 4,395-game priced universe exactly | Claim byte-level determinism until H1–H3 and H6 are fixed |
| Describe price improvement as line-shopping value | Describe it as EV or edge (`docs/PLAN_TWO_TOOLS.md`) |

---

## 8. Not measured, and what it would take

- **Lineup posting times, 2023–24.** Not in any store. Would need an archived
  lineup feed with fetch timestamps for those seasons. None exists; forward
  `rosterwatch` starts 2026-08.
- **Probable-pitcher announcement times and late-scratch rate, 2023–24.** Same
  problem, same non-availability.
- **Takeability at stake.** No limits or acceptance data anywhere; not
  purchasable.
- **API-observation latency** (book changes price → API records it). Would need
  a second independent feed; not obtainable retrospectively.
- **How much the T-180-served subset (§3) differs from the full universe.** A
  Phase 1 diagnostic: compare outcome rate, consensus probability and book
  count between the served and unserved subsets. Cheap, local, no credits.
- **Sub-3-hour granularity.** Only purchasable: the 5-minute historical grid at
  10 credits/event/snapshot, gated behind a registered hypothesis and Brey's
  sign-off per `docs/COLLECTION_POLICY.md`.
- **2025 and forward-store granularity.** 2025 coverage is reported in §1/§4 as
  capacity only and was not analysed; the forward stores were not opened at all
  (sealed window).

---

## 9. Recommendations into Phase 1

1. **Fix H1 before anything else.** A seeded bootstrap whose interval moves
   with row order will quietly falsify the placebo calibration, which is the
   lab's entire product.
2. **Fix the replay clock's alphabet to the served `snapshot_at` values.** The
   engine's decision times should BE observations, never interpolations. A
   strategy asking for a price at an instant with no observation gets refused,
   not served.
3. **Make the lineup-post assumption an explicit, versioned engine parameter**
   and stamp it on every artifact. Default T-180, since that is where the
   coverage cliff sits.
4. **Fix the close definition now, in writing, with its denominator.** T-30 →
   1,269 games; T-60 → 1,967; T-120 → 2,916. This choice sets the lab's power
   before a single strategy exists.
5. **Bar book identity from the genome.** Between the 63–79% tie rate and
   season-to-season roster churn (19 → 14 → 11 books), any book gene fits
   noise and confounds season.
6. **Carry the 4,819 / 4,482 / 4,395 / 3,624 / 1,269 ladder into every power
   calculation** rather than the headline 4,859.

---

*Read-only audit. No store, test or source file was modified. Full test suite
run after the audit: 1,684 tests, OK.*
