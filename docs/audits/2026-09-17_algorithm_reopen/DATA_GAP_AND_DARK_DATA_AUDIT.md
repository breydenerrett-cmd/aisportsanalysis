# Data Gap and Dark Data Audit — 2026-09-17

Read-only audit. No odds-API calls were made; every number below was measured
directly from files already on disk (`wc -l`, gzip line counts, `json.load`,
git history/`git ls-files`, and direct greps of `src/`). `data/historical/lineups.jsonl`,
`data/historical/statcast/`, and `data/tennis_trial/` were read but never
modified. Row/date/null counts are exact counts from a one-off Python pass
over each file, not estimates.

---

## PART A — Inventory of what actually exists

### Odds — moneyline / totals / spreads, multi-book (`data/processed/odds_multibook.jsonl`)

- **SOURCE**: The Odds API, `src/pipeline/snapshots.py` (`multibook_rows`).
- **YEARS**: 2026 only.
- **COVERAGE**: 184,877 rows, 26 distinct dates, 2026-08-31 → 2026-09-29 (forward capture window; nothing pre-08-27 at this density).
- **MISSINGNESS**: `home_price`/`away_price` present on 128,462/184,877 rows (69%); `market` label present on only 108,601/184,877 (59%) even though `home_price`/`away_price` are present on more rows than that — 76,276 rows have moneyline prices but no `market` tag, i.e. "h2h" is implicit rather than stated. `total`/`over_price`/`under_price` on 56,415 rows (30%); `home_line`/`away_line` on 52,186 (28%).
- **BOOKS** (11, matches the 11-book claim): fanduel 21,005 · draftkings 19,584 · williamhill_us 19,181 · bovada 18,980 · betmgm 18,513 · fanatics 17,084 · lowvig 15,299 · betonlineag 15,288 · betrivers 13,924 · mybookieag 13,885 · betus 12,134.
- **POINT-IN-TIME SAFETY**: every row carries `observed_utc` (capture time) and `book_last_update` (book's own quote timestamp) — sound.
- **HISTORICAL AVAILABILITY**: none at this density before 2026-08-27; see the archived `odds_history` backfill below for 2023-2025.
- **UPDATE FREQUENCY**: many snapshots/day per event (thousands of rows/day across the slate).
- **CURRENT USE**: consensus/de-vig pricing (`src/analysis/prices.py`, `MIN_BOOKS = 6`), best-price/line-shopping, board display (Odds tab).
- **POTENTIAL USE**: cross-book dispersion as a standalone predictive signal — see Part B.
- **KNOWN BUGS**: implicit-market rows (above) require special-case handling ("no market field + price present ⇒ h2h") that not every consumer necessarily applies correctly.

### Odds — narrow/legacy snapshots (`data/processed/odds_snapshots.jsonl`)

- 26,606 rows, 30 dates, 2026-08-27 → 2026-09-29. Nested `prices` object (different shape from `odds_multibook`'s flat columns).
- **Book concentration**: fanduel 20,119 + draftkings 6,233 = 95% of all rows; the other 5 books that do appear (fanatics 114, betmgm 71, mybookieag 47, bovada 12, williamhill_us 10) are noise-level. This is effectively a 2-book capture path running in parallel with the 11-book `odds_multibook`, covering the same date range with two different on-disk shapes of "the same" quote and no documented single source of truth between them.

### F5 (first 5 innings) closing lines (`data/processed/f5_close.jsonl`)

- 1,327 rows, 16 dates (2026-08-31 → 2026-09-15), market `h2h_1st_5_innings`, 9 books (~130-152 rows/book) — a closing-snapshot-only capture, not a full intraday series.

### Derivative markets — team totals etc. (`data/processed/derivative_markets.jsonl` + `_raw`)

- 129,092 priced rows + 918 poll-metadata rows, 13 dates (2026-09-03 → 2026-09-15), 10 books.
- `team` field null on 113,945/129,092 rows (88%) and `line` null on 4,798 (4%) — the flat `team` column is largely unpopulated even though the `selection` field ("Tampa Bay Rays:Over") carries the same information; another place the same fact exists in two representations, one of them mostly empty.

### Props — batter (`data/processed/batter_props.jsonl` + `_raw`)

- 66,720 priced rows + 202 poll rows, 15 dates (2026-09-03 → 2026-09-17), 8 books (draftkings 16,164 down to fanatics 1,194).

### Props — pitcher / listing (`data/processed/prop_listing.jsonl`, `prop_prices.jsonl`)

- 2,571 + 3,360 rows, 14-17 dates, 8 books; includes `pitcher_strikeouts` market and schedule-sampling metadata (`selected_at_slot`: "T-6h"/"T-2h", `rule`: "earliest, median, latest by commence_time") — a deliberately sparse sampling design, not a miss.

### L1 observations — normalized quote ledger (`data/processed/l1_observations.jsonl`)

- 16,570 rows. Schema: `book`, `known_at`, `known_at_grade` (A/B/C timing-confidence tier), `is_close`, `l0_available`, `limit_observed`, `line`, `price_american`, `subject_id`, `subject_kind`, `venue_kind`, etc.
- **100% null across all 16,570 rows**: `limit_observed`, `subject_id`, `subject_kind` — three schema columns that have never once been populated. `limit_observed` (a sportsbook bet-limit reading — a classic sharp-money proxy) can't be filled from The Odds API at all; it needs a different provider entirely. `subject_id`/`subject_kind` look like they were meant to generalize this store beyond game-lines (e.g. to player props) but nothing writes them yet.
- `line` null on 5,584/16,570 (34%) — expected, since h2h rows carry no line.

### Lineup-posting time vs. lineup content

- **Content**: `data/historical/lineups.jsonl` (read-only, not modified) — verified **5,003 rows**, one row per game with `home`/`away` batting orders (name, person_id, position, order) and a single `observed_utc` for when the *whole* lineup was captured.
- **Posting time as its own event**: `data/processed/information_events.jsonl` — 2,493 rows, `event_kind: "lineup_posted"`, one row per side per posting, each carrying its own `observed_utc` and a `known_at_grade`. This is a genuinely separate, finer-grained record of *when* a lineup went up than the single timestamp on `lineups.jsonl`.

### Event/game identity resolution (`data/processed/event_game_map.jsonl`)

- 2,754 rows, 211 distinct dates, 2023-02-27 → 2026-09-17 — maps odds-API `event_id` to MLB `game_pk`, with `ambiguous`/`candidates`/`reason` fields for imperfect matches (17 rows have no resolved `game_pk`).

### Box scores (`data/processed/boxscores_{2023,2024,2025,2026}.jsonl`)

- 2023: 73,878 rows / 183 dates (2023-03-30 → 2023-10-01). 2024: 73,773 / 183 dates (2024-03-28 → 2024-09-30). 2025: 74,189 / 183 dates (2025-03-27 → 2025-09-28). 2026 (partial season, in progress): 7,235 rows / 17 dates (2026-08-30 → 2026-09-15).
- Per-player batting and pitching lines (IP, pitches, batters_faced, AB/H/HR/RBI, etc.); 2026 rows additionally carry `first_inning_scored`/`first_team_to_score` on 227 games — an F5-specific derived field only present for the current season.
- Full-season coverage for 2023-2025; **this is the closest thing to a complete historical outcome table** alongside `mlb_results.csv`.

### Play-by-play / win probability (`data/processed/gameflow_2026.jsonl`)

- 84,716 rows, 83 distinct dates, **2026-06-17 → 2026-09-09 only** — starts mid-season (not opening day), and there is no 2023-2025 equivalent anywhere in the repo. Per-play `home_win_prob`/`away_win_prob`/`leverage_index`/`home_win_prob_added`. `leverage_index` is null exactly once per game (the game-header row, which has no leverage by construction) — not a data-quality problem.

### Bullpen appearance log (`data/historical/bullpen_log.jsonl`, `_2025`)

- `bullpen_log.jsonl`: 59,808 rows, 538 distinct dates, 2023-03-30 → 2026-09-06. `bullpen_log_2025.jsonl`: 27,483 rows, 365 calendar dates (full 2025 season, including 122 explicit `{"date": ..., "empty": true}` placeholder off-days — correctly recorded, not missing).
- Per-appearance: `pitches`, `innings`, `batters_faced`, `started` (bool), `earned_runs`, `strikeouts`, `walks` — exactly the "who threw, how many pitches, started or relieved" granularity the task asked about.

### Pitcher game logs (`data/historical/pitcher_logs.jsonl`, `_2025`)

- 25,023 rows (531 dates, 2023-03-30 → 2026-09-07) + 8,830 rows (184 dates, full 2025 season). Person-day pitching lines. No pre-computed "days rest since last appearance" field — that has to be derived downstream from date deltas per `person_id`; nothing in the repo currently does this join (see Part B).

### Batter-vs-pitcher matchup history

- `data/historical/matchup_pairs.json`: 954 career-aggregate pairs (`"batter_id:pitcher_id"` → lifetime AB/H/HR/OPS, no year or game breakdown — a 2019 at-bat and last week's at-bat count identically).
- `data/historical/matchup_history.jsonl`: 71 rows, only 6 distinct dates (2026-09-08 → 2026-09-16) — a newer, dated, per-game version of the same fact with a `usable` flag gated at a 60-PA sample floor; most sampled rows are `usable: false`. This is a brand-new, barely-populated feature, not yet at season scale.

### Pitcher splits (`data/historical/pitcher_splits.json`)

- Only **29** `person_id:season` entries (Home/Away/vs L/vs R splits) — a small, evidently on-demand subset (probable starters for upcoming games), not full-league coverage.

### Pitch arsenal (`data/historical/arsenals/{pitcher,batter}_2026.json`)

- `pitcher_2026.json`: `{as_of, min_pitches: 50, season: "2026", source: "baseballsavant pitch-arsenal-stats", rows: [...]}` — **1,142 rows**, one row per (pitcher, pitch_type) for the 2026 season only, each row already a season-long average (`pitch_usage`, `whiff_percent`, `hard_hit_percent`, `k_percent`, `woba`, `est_woba`, `ba`, `slg`). This is Baseball Savant's own aggregated arsenal endpoint — pre-collapsed at the source, before it ever reaches this repo. No 2023-2025 arsenal file exists.

### Raw pitch-level Statcast (`data/historical/statcast/*.jsonl.gz`, read-only, not modified)

- Verified **94 data files** (the task's "95" includes `manifest.json`, which is not a data file) totaling **1,432,440 pitches** — matches the task's ~1.43M estimate. Date range: **2023-03-30 → 2024-09-30 only** (2023 and 2024 seasons; no 2025, no 2026). Per-pitch fields: `pitch_type`, `release_speed`, `stand`, `p_throws`, `events`, `description`, `woba_value`, `bb_type`, etc. — genuinely raw, not aggregated.
- **Temporal gap**: this is the only granular pitch-level source in the repo, and its 2023-2024 range does not overlap the 2026 arsenal rollups, the 2026 gameflow/win-probability data, or the sealed evaluation window (2026-01-01 → 2026-08-27) at all. Nothing in the repo currently joins raw pitch detail to the actual backtest period.

### Handedness reference (`data/historical/handedness.json`)

- 1,643 players, `{bats, throws, name}` — static reference table, fine as-is.

### Standings (`data/historical/standings.jsonl`)

- **Exactly one snapshot ever**: 2026-09-08, 30 rows (one per team). Not a time series — there is no standings/games-back/wildcard-race history anywhere in the repo, before or after that date. Any "team fighting for a playoff spot" leverage signal cannot be backtested at all.

### Transactions / injuries (`data/historical/transactions.jsonl`)

- 586 rows, only **16 distinct dates**, 2026-08-23 → 2026-09-08. The sealed evaluation window is 2026-01-01 → 2026-08-27; injury/IL/roster-move history exists for only the last 4 days of that ~240-day window. Any injury-aware signal is untestable against nearly the entire sealed period for lack of the underlying data, not for lack of a model.

### Forward-only watch logs (`data/watch/*`, read-only, not modified)

- `lineups_watch.jsonl` 1,134 rows · `probables_watch.jsonl` 1,033 · `transactions_watch.jsonl` 1,322 · `umpires_watch.jsonl` 927. Umpire assignment capture exists (not explicitly named in the task's list) but is forward-only from whenever capture started; no historical umpire data exists.

### Ground-truth results table (`data/historical/mlb_results.csv`)

- 9,443 games, 2023-03-30 → 2026-09-10, with probable pitchers (name + id), scores, `total_runs`, `run_differential`, doubleheader flags. No field tracks how often or how late a listed probable pitcher changed before first pitch (see Part B).

### Raw API captures — retention

- `data/raw/oddsapi/`: 2,337 files, **all under `2026/09`** — raw un-processed API responses are only retained for the current month; nothing before September 2026 survives at the raw-response level (only the processed/derived stores above do).
- `data/archive/historical/odds_history/mlb_{2023,2024,2025}.jsonl.gz`: exactly **600 snapshot-documents per season**, taken at a fixed ~3x/day cadence (~01:50Z / 16:50Z / 22:50Z), `h2h`+`totals` only. This is drastically sparser than the 2026 live capture (thousands of book-market rows/day): the repo's own research modules (`src/research/m1_overreaction.py`, `m2_staleness.py`) explicitly document working from "a median of four or five snapshots per game" on this historical grid, which this count confirms rather than merely asserts.

### BALLDONTLIE ALL-ACCESS — wired vs. discussed

Bought 2026-09-15 as a 48-hour trial (per `src/providers/balldontlie.py`'s own docstring) covering MLB/NBA/NFL/NHL/tennis at a higher rate ceiling than the tennis-only ALL-STAR tier already in production use.

- **`data/historical/balldontlie/MANIFEST.json`** lists 461 harvest-job entries across mlb (7)/nba (7)/nfl (364)/nhl (7)/tennis (76), many marked `"complete": true` with byte counts, row counts, and sha256 hashes — e.g. `mlb/mlb_games_2022.jsonl.gz`: 2,793 rows, sha256 `c37207d...`, harvested 2026-09-16T00:08:28Z.
- **These files do not exist.** `Glob` over `data/historical/balldontlie/**/*` and `git ls-files` both confirm the only files that actually exist (on disk or in git history) are `MANIFEST.json` itself and 35 `.jsonl.gz.cursor` retry-state sidecars — 2 for NFL (the two 429-rate-limited seasons, correctly marked `"complete": false`) and 33 for tennis. **Every MLB, NBA, and completed-NFL `.jsonl.gz` payload the manifest claims to have harvested and hashed is gone** — never committed (the harvest-bot commits, `38f83f64`/`38608b94`/`8a8c7008`, touch only `MANIFEST.json` and cursor files) and not present locally. **This is a known bug**: the manifest is a false record of successfully captured, checksummed data. Anyone trusting the manifest without checking the filesystem would believe MLB/NBA/NFL/NHL BALLDONTLIE data exists when it does not.
- **What's actually wired**: `grep` for `balldontlie`/`BallDontLie` across `src/` hits only `src/providers/balldontlie.py`, `src/providers/api_tennis.py`, `src/providers/tennis_results.py`, and their tests — **zero hits** in `src/analysis`, `src/model`, `src/engine`, `src/board`, `src/report`, or `src/pipeline`. Only the tennis path (`tennis_results.BallDontLieFeed`, used for live results grading) is read by anything beyond the harvester and its tests. MLB/NBA/NFL/NHL data from this vendor is not read by any model or pipeline code, and per the point above, mostly doesn't exist to be read anyway.
- All `*_odds*.jsonl.gz` entries for every sport show `http_status: 400` or `429` and `"complete": false` — BALLDONTLIE's odds endpoints are not usable on this account regardless of sport.

### Public betting / handle percentages

- Searched for `public_betting`, `ticket_pct`, `bet_percentage`, `handle_pct`, `consensus_pct`, `money_pct` across the entire repo: **zero matches, anywhere.** This category is a total gap — no provider is wired for it and no field exists to hold it.

---

## PART B — Dark data (captured, underused)

**1. Cross-book price disagreement — display-only, never a model feature.**
`src/analysis/oddspayload.py` computes `spread_cents` ("the plain arithmetic gap between the best and worst quoted American price on one side of the board") and a `favorite_disagreement` flag from the same 11-book `odds_multibook` store already on disk. Grepping for `spread_cents`/`favorite_disagreement` across the repo shows it is consumed only by `web/js/odds.js`, `docs/API_CONTRACTS.md`, and tests — **never** by `src/model`, `src/engine/features.py`, or `src/detect/detectors.py`. Direct answer to the task's concrete prompt: cross-book disagreement is used for the Odds-tab display and, separately, folded into the ≥6-book de-vig consensus for best-price selection (`src/analysis/prices.py`, `MIN_BOOKS = 6`) — it is never tested as a standalone predictive signal (e.g. "spread widens before news breaks" or "wide spread ⇒ thin/stale liquidity").
*Lowest-cost experiment*: purely offline — from `odds_multibook.jsonl` alone (already on disk), compute per-event max−min book spread over time and correlate against subsequent CLV/outcome in `mlb_results.csv`. Zero API spend.

**2. Wind vector — captured, computed, then deliberately not used.**
Every one of 9,481 `weather_forecast.jsonl` rows carries `wind_from_deg` (meteorological bearing), and `src/data/parks.py` already implements `classify_wind()`/`wind_effect()` using park orientation + wind bearing to classify in/out/crosswind. But `orientation_deg` is hard-coded `None` for **all 30 parks** (confirmed by direct read of `parks.py`), so `ParkAndWeather` (`src/detect/detectors.py`) deliberately reports wind speed only, tagging the finding `evidence=BLOCKED` with the comment "park orientation is unknown for all thirty parks... a wrong bearing would invert the effect." This is a disclosed, reasoned exclusion, not neglect — but it is also the cheapest fix in this whole audit.
*Lowest-cost experiment*: hand-enter the 30 real, public home-plate-to-center-field bearings into `parks.py`. Zero API cost; the wiring to consume it already exists and would activate immediately.

**3. Lineup-posting TIME, as distinct from content, is captured but not obviously scored.**
`information_events.jsonl`'s 2,493 `lineup_posted` events carry their own `observed_utc`/`known_at_grade`, separate from the single timestamp on `lineups.jsonl`. `synthesis.py`'s `TONIGHT_DETECTORS` gate only on *whether* a lineup exists, not *how early* it posted (a common proxy for how settled/uncertain a lineup is). The timing signal exists and is unexploited as its own feature.
*Lowest-cost experiment*: join `lineup_posted` timestamps against CLV/outcomes in the existing forward-capture window — offline, no new capture.

**4. `limit_observed` / `subject_id` / `subject_kind` — dead schema, not dark data in the usual sense.**
100% null across all 16,570 `l1_observations.jsonl` rows. `limit_observed` (a bet-limit / sharp-money proxy) can't be populated from The Odds API at all — it would need a different, likely paid, provider. `subject_id`/`subject_kind` look like unfinished plumbing for extending this store beyond game lines. Flagged here so it isn't mistaken for a "model ignores it" case — it's a "nothing can write it yet" case.

**5. Matchup history collapsed to lifetime aggregates.**
`matchup_pairs.json`'s 954 pairs hold only career AB/H/HR/OPS with no year or recency weighting — an at-bat from 2019 counts the same as one from last week. The newer `matchup_history.jsonl` (71 rows, 6 dates) is dated and per-game but too new to have replaced the frozen aggregate as an input anywhere.

**6. Bullpen appearance detail — used, and honestly found not (yet) predictive.**
Distinguishing from the items above: `bullpen_log.jsonl`/`_2025` (87,291 combined rows of pitches/IP/BF per appearance) *is* read by `BullpenWorkload` and `BullpenExposure` detectors — but both carry `status = UNPROVEN` and largely `evidence = TESTED_NULL` per the pre-registered hypothesis ledger in `src/detect/detectors.py`. This is a checked box, not an overlooked one; worth naming so it isn't re-proposed as a "new" idea.

**7. Probable-starter change history is not instrumented at all.**
`mlb_results.csv` records the probable pitcher as of the results pull, but nothing tracks how often or how late a probable starter changed before first pitch (a market-moving event on its own). Only the 2026-09-onward `probables_watch.jsonl` forward log (1,033 rows) could support this, and only going forward from whenever it started.

---

## PART C — Abstraction traps

**1. One quote, three on-disk shapes.**
Raw API response → flattened by `src/pipeline/snapshots.py`/`prices.py` into per-book rows → then re-flattened *differently* three times: `odds_multibook.jsonl` (wide columns, market often implicit), `odds_snapshots.jsonl` (nested `prices` dict, 95% of rows are 2 of 11 books), and `l1_observations.jsonl` (normalized ledger with `known_at_grade`). No single documented source of truth among the three; a consumer has to know which store is authoritative for which purpose. The market-implicit-when-price-present pattern in `odds_multibook` (76,276 rows) is the concrete, measurable symptom.

**2. Pitch arsenal pre-aggregated before it reaches the repo.**
Baseball Savant's arsenal endpoint returns one row per (pitcher, pitch_type) per season with usage%/whiff%/hard-hit%/woba already averaged (`arsenals/pitcher_2026.json`, 1,142 rows). Pitch sequencing, count-dependent usage, and within-season trend are gone before the file is ever written. The one place per-pitch granularity survives — 1,432,440 raw Statcast pitches — covers 2023-2024 only, so raw and aggregate never overlap in time and nothing joins them to the actual 2026 evaluation window.

**3. `src/analysis/synthesis.py` — a disclosed, hand-set, never-fit weighted formula.**
`WEIGHTS = {"magnitude": 0.35, "sample": 0.20, "tonight": 0.15, "market": 0.10, "novelty": 0.20}` combines five different kinds of evidence (a wOBA-gap magnitude, a log-scaled sample size, a boolean "depends on tonight's lineup," a market-relevance flag, and a hand-assigned 0-1 "novelty" rating per detector name) into one composite ranking score, thresholded at `MIN_SCORE = 0.42`. The module's own docstring states plainly: *"The scales and weights below are presentation judgements about what deserves a reader's attention. They are not measured effect sizes."* **These weights were never fit or backtested** — this is exactly the hand-authored weighted-category formula the task asked to look for, and it is honestly labeled as such rather than presented as a model. Loss is intentional and disclosed; items below the threshold are not deleted, only demoted to a lower section of the card.
*Contrast*: `data/processed/card_v2_frozen_params.json` and `card_calibration.json` **are** properly fit — logistic-style `(a, b, base_rate)` coefficients fit on 2025 data (n = 1,911 to 8,108 observations per component), with the sealed 2026 window explicitly excluded in the file's own `_header.fitted_not_on` field. The codebase does both (fit and hand-set); the difference is visible in each file's own header rather than hidden.

**4. Wind vector dropped at the detector, not at capture** (see Part B #2) — the raw vector and the orientation-aware transform both exist; the loss happens one step later, at the point where the detector chooses not to trust an unfilled `orientation_deg` table. Intentional, disclosed, and (per the audit) the single cheapest thing in the repo to reverse.

**5. Full trace of a published number — the game total / win probability.**
raw team & pitcher season stats (`mlb_results.csv`, `pitcher_logs*.jsonl`, `boxscores_*.jsonl`) → `run_expectancy_poisson_v1` computes an expected-runs figure using **one league-wide constant** `league_runs_per_game = 4.3967` (same value for all 30 parks, all weather, all matchups) and a fixed `slot_plate_appearances` table (lineup-slot-average PA, same for every team, fit on 2025 with `slot_sample_sizes` of 5,389-6,311 PA per slot) → an `nb1`-family overdispersion correction (`DISPERSION = 2.3615`, fit on 4,054 team-games) → `moneyline_calibration` logistic squash (`a = 0.071234, b = 0.685153`, n = 2,027 games) → the published probability. Along this path: park altitude/dimensions are *not* a term inside the run-expectancy step (they only appear separately as descriptive `ParkAndWeather` card text); wind is dropped for the orientation reason above; arsenal/pitch-mix detail never enters the number either, only the surrounding card narrative. Net effect: almost everything else this audit found — arsenal, wind, matchup history, bullpen detail, cross-book disagreement — lives in the descriptive text *around* the published number, not inside the number itself. That may be the right design (the codebase is explicit that 27 pre-registered hypotheses have not cleared the bar), but it means "the model" and "the page" currently draw on very different amounts of the data this repo stores.

---

## Report back

**Three most valuable pieces of dark data:**
1. Cross-book price disagreement (`spread_cents`/`favorite_disagreement`) — fully captured across 11 books and 184,877 rows, used only for display and best-price selection, never tested as a predictive signal. Zero-cost offline experiment available today.
2. Wind vector (`wind_from_deg`) plus an already-built `wind_effect()`/`classify_wind()` transform — inert only because `orientation_deg` is `None` for all 30 parks. A ~30-value, zero-cost, public-data fix turns on code that already exists.
3. Lineup-posting time (`information_events.jsonl`, `lineup_posted`, 2,493 rows) as a signal distinct from lineup content — captured, timestamped, graded, and not scored on its own.

**Worst abstraction trap:** the run-expectancy/calibration chain behind the published win probability leans on one league-wide runs-per-game constant and a fixed lineup-slot PA table, with park, wind, and pitch-arsenal detail dropped before the number is computed and pushed instead into descriptive card text around it — while, separately, `odds_multibook.jsonl` carries an implicit (unlabeled) market on 76,276 of its 184,877 rows, an actual correctness risk for any consumer that doesn't special-case it.

**One data gap to close first:** the BALLDONTLIE MANIFEST.json falsely claims (with byte counts and sha256 hashes) that MLB/NBA/NFL/NHL game files were harvested and complete on 2026-09-15/16 — they do not exist on disk or in git. Before spending any more credits or trusting this vendor for anything beyond the already-wired tennis path, either re-harvest (if the trial/entitlement still allows it) and verify the files land and are committed, or correct the manifest to reflect that nothing survived. Second in line, and free: fill in the 30 park `orientation_deg` values to unlock the existing wind-vector code.
