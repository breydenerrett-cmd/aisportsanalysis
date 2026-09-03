# Subsystem map: forward-stores-ledger

Scope: `data/watch/**`, `data/processed/**`, `evidence/forward_ledger.jsonl`,
`src/pipeline/{grading,ledger,rosterwatch,umpirewatch,weather_capture}.py`,
`docs/OVERNIGHT_RUN.md`, `docs/CAPTURE_EXTERNALIZATION.md`. Read-only pass,
2026-09-03, against the branch `claude/sports-betting-analysis-review-g1o0co`.
All numbers below are counts taken directly from the files on disk at time of
writing; they will have grown by the time this is read again.

## 1. What exists today, on disk, right now

| Store | Rows | Content shape | Evidence |
|---|---|---|---|
| `data/watch/lineups_watch.jsonl` | 252 | 148 poll markers, 80 lineup-content rows (`away_lineup`/`home_lineup` as arrays of MLB player IDs, `game_pk`, `fetched_utc`), 24 bare poll markers with no `game_date` | sampled directly, counted with a `Counter` over key-tuples |
| `data/watch/probables_watch.jsonl` | 222 | 148 poll markers, 50 probable-starter rows (`away_probable_id`/`home_probable_id`, `game_pk`, `fetched_utc`), 24 bare markers | same |
| `data/watch/transactions_watch.jsonl` | 354 | 161 transaction rows (`category`, `date`, `player`, `player_id`, `team`, `transaction_id`, `first_seen_utc`), 148 poll markers, 24 bare markers, 21 minimal `{first_seen_utc, transaction_id}` rows | same |
| `data/watch/umpires_watch.jsonl` | 37 | 22 poll markers, 15 crew-reveal rows (`crew`: 4-official array with names/positions, `home_plate_umpire`, `observed_utc`, `prev_poll_utc`, `revealed`, `game_state`) | same |
| `data/processed/odds_multibook.jsonl` | 19,487 | one row per (event, book, market snapshot): `observed_utc`, `event_id`, `commence_time`, `home_team`/`away_team`, `book`, `book_last_update`, `home_price`/`away_price` — h2h only in the sampled row | head -1 + wc -l |
| `data/processed/odds_snapshots.jsonl` | 7,324 | legacy single-book-per-event snapshot store (see §4 defect: "keeps ONE book per event, 96% fanduel", `docs/OVERNIGHT_RUN.md:284`) | same, cross-referenced against OVERNIGHT_RUN |
| `data/processed/f5_close.jsonl` | 317 | first-five closing price rows, one market (`h2h_1st_5_innings`) | head -1 |
| `data/processed/prop_listing.jsonl` | 446 | availability-audit rows only: `event_ids` sampled per slate (earliest/median/latest), `slate_size`, `schedule_version` — no actual prop odds | head -1; `src/pipeline/prop_listing.py:8-26,64` |
| `data/processed/prop_prices.jsonl` | 29 | same audit shape, for the same single market | head -1; `src/pipeline/prop_prices.py:64` |
| `data/processed/weather_forecast.jsonl` | 23 | one row per game per capture tick: `park`, `venue`, `roof`, `temp_f`, `wind_mph`, `wind_from_deg`, `humidity_pct`, `precip_probability_pct`, `pressure_hpa`, `hours_to_first_pitch`, `observed_utc` | head -1; `src/pipeline/weather_capture.py:1-40` |
| `data/processed/training_table.csv` | 2,277 rows | team-level only: win%, runs scored/allowed per game, last-5/last-10 form, home/away split win%, rest days, streak — **no starter, bullpen, arsenal, or environment columns at all** | header line inspected directly |
| `data/processed/model.json` | — | a flat linear-weights vector matching `training_table.csv`'s columns | head -c 500 |
| `data/processed/credit_log.jsonl` | 14 | API-credit accounting only | head -1 |
| `evidence/forward_ledger.jsonl` | 427 | 144 `recommendation`, 73 `settlement`, 210 `closing_backfill` | `Counter` over `kind` |

**`MARKET = "pitcher_strikeouts"`** is hard-coded as the *only* prop market
either prop store ever touches (`src/pipeline/prop_listing.py:64`,
`src/pipeline/prop_prices.py:64`), and even that market is only *audited for
listing/pricing availability* — it is never pulled into a recommendation or
the ledger. Grep of `src/pipeline/` for prop integration into `briefing.py`
or `ledger.py` finds none.

## 2. The forward decision record today (one `recommendation` row)

Fields present, read directly off a sampled row (`away_team`, `home_team`,
`commence_time`, `date`, `game_pk`, `recorded_at`, `information_time`,
`verdict`, `side`, `market`, `summary`, `prices`, `books`,
`implied_bullpen_shift`, `lineup_status`, `findings[]`, `sections_present[]`,
`gaps{}`):

- **Recommendation** — EXISTS, but degenerate: `verdict` is one of
  `no_play` (134/144), `market_unavailable` (7/144), `flagged` (3/144) — no
  `play`/`bet` state ever appears in this 144-row sample. `side` and
  `market` (only ever `null` or `"first_five"` across the whole file, per
  `Counter`) are the closest things to "recommendation."
- **Why** — PARTIAL. `findings[]` is a real, structured why: each entry
  carries `detector`, `claim` (plain-language), `baseline`, `value`,
  `surprise`, `sample`, `side`, `evidence` (e.g. `"unproven"`,
  `"tested_null"`, `"historical_candidate"`). This is genuine mechanism, not
  a placeholder. But it is *detector output*, not a decision rationale —
  there is no field that says "here is the synthesis that produced the
  verdict," only a one-line `summary` string.
- **Price** — EXISTS for the one book snapshotted at write time (`prices`
  keyed by market: `h2h`, `h2h_1st_5_innings`, `spreads`, `totals`,
  `totals_1st_5_innings`, each with `away_fair`/`home_fair`/`hold_pct`) plus
  **every book on the board** for h2h/first-five in `books{}` — this part
  does exceed a single-book pick.
  quote (multi-book board captured for h2h, per `docs/OVERNIGHT_RUN.md:283-284`'s
  fix).
- **Book** — EXISTS at quote level (`books.<market>[].book`), MISSING as a
  chosen-execution-book field on the recommendation itself (no `chosen_book`
  key observed).
- **Rating** — MISSING. No `rating`, `confidence`, `tier`, `stars`, or
  `units`/`stake` field anywhere in a `recommendation` row. `surprise` inside
  a `findings[]` entry is a per-signal z-score-like number, not a bet rating.
- **Evidence** — PARTIAL: `findings[].evidence` is a per-signal string label
  (`unproven`/`tested_null`/`historical_candidate`), not a graded evidence
  class tied to backtested performance.
- **Counterarguments** — MISSING. No field or nested structure holding an
  opposing case; `findings[]` are all one-directional claims.
- **Supporting systems** — MISSING. The vision's "many competing analysis
  systems" (a strategy factory) has no representation in this ledger: there
  is exactly one producing pipeline (`briefing.py` → `ledger.record_slate`),
  one row per game, no `system_id`/`strategy_id`/`variant` field.
- **Settlement** — EXISTS as a separate `kind: "settlement"` row keyed by
  `game_pk` (append-only, never edits the recommendation — by design, see
  `src/pipeline/ledger.py:14-19`), with `result.home_score`,
  `result.away_score`, `result.winner`, `result.first_five.*`, `settled_at`.
  But every sampled settlement row's `closing` field is **`null`**
  (confirmed both in the sample and in `docs/OVERNIGHT_RUN.md:283`: *"closing
  = null in every settlement (cli never threads it -> no CLV from the
  ledger)"*) — the settlement path does not compute CLV itself.
- **Closing (for grading)** — PARTIAL, and structurally awkward: a *third*
  row kind, `closing_backfill` (210 rows — the single largest kind in the
  ledger, more than recommendations), exists specifically to repair the gap
  above after the fact. A sampled row shows it does real work — `clv.cents`,
  `clv.prob_edge`, `clv.beat_close`, `closing_price`, `closing_source`,
  `reason: "abbreviation join bug 65f499a"` — but its own `reason` field is
  literally a bug-ticket string, i.e. this repair path exists because of a
  join bug, not by original design (`src/pipeline/grading.py:478-664`,
  `find_backfillable_closings`/`_ledger_closing`/`_ledger_clv`).
- **Self-review** — MISSING as a stored artifact. `docs/OVERNIGHT_RUN.md` is
  a prose changelog with narrative self-review ("First decided mismatch
  flag," "Bugs found and fixed this run") but it is a hand-written running
  log, not a structured per-game or per-day self-review record joined to the
  ledger by `game_pk`/`date`.

## 3. Timestamps actually captured, and what they bracket

- **Lineups/probables/transactions** (`rosterwatch.py`): grade-B interval
  bracketing by design — a poll marker row every ~10-15 min
  (`{"fetched_utc", "poll": true, "game_date"}`) plus a change row the moment
  content differs from the last stored value, so an event is bounded between
  "last poll that still saw the old state" and "first poll that saw the
  new state" (`src/pipeline/rosterwatch.py:11-40`). This is the one part of
  the subsystem built explicitly to answer "when did we/the market know this"
  rather than just "what is true now."
- **Umpires** (`umpirewatch.py`): same bracketing convention, one state
  transition per game (`unrevealed -> revealed`), `prev_poll_utc` embedded
  directly on the row rather than reconstructed later
  (`src/pipeline/umpirewatch.py:14-40`). Verified live: the crew hydrate is
  empty while `Scheduled` and populates 3.6-4.6h before first pitch
  (module docstring, same file).
- **Weather** (`weather_capture.py`): one row per game per capture tick,
  intentionally NOT deduped across ticks — each tick's forecast is a fact
  about that moment, and the store is designed to let a reader compare a
  6-hour-out forecast to a first-pitch forecast later
  (`src/pipeline/weather_capture.py:17-27`). No mechanism observed here or
  elsewhere that captures what the roof actually did (open vs closed) —
  explicitly disclaimed as not knowable from Open-Meteo, same file.
- **Prices**: `odds_multibook.jsonl` has `observed_utc` (our fetch instant)
  *and* `book_last_update` (the book's own last-move instant) per book per
  event — this is the correct pair for later distinguishing "stale book" from
  "fresh book," and does support first-mover/consensus/staleness measurement
  now that it is multi-book (fixed per `docs/OVERNIGHT_RUN.md:283-291`,
  V3 capture infra section).
- **Recommendation**: `information_time` is explicitly the moment inputs were
  gathered, distinct from `recorded_at` (write time) — `ledger.py:104-109`
  guards specifically against a multi-minute run claiming its own runtime as
  free hindsight. This is correct and deliberate.
- **One row per game, ever, once priced** (`ledger.py:62-79,88-97`): once a
  game has a priced recommendation row, `record_slate` will never append
  another for that `game_pk` even if the briefing reruns later with fresher
  inputs (closer to first pitch, a different market picture, a posted
  lineup). The only exception is a single "priced repair" for a game whose
  only prior row was price-less. **This means the ledger cannot represent
  line movement, a late lineup post, or a changed verdict within one game's
  pre-game window** — it captures one point-in-time snapshot per game, not a
  trajectory, even though several of the underlying stores (odds, weather)
  are explicitly built to capture trajectories.

## 4. Confirmed defects and self-documented gaps (not speculation — cited)

- **Single-book snapshot store, 96% one book**: `odds_snapshots.jsonl`
  (7,324 rows, still on disk, still read by `grading.py`'s closing-value path
  via `_index_snapshots`/`_find_series`) was, per
  `docs/OVERNIGHT_RUN.md:284`, found to "keep ONE book per event (96%
  fanduel) because `normalize()` collapses the payload — first-mover/
  consensus/stale measurements are impossible on it." The fix
  (`odds_multibook.jsonl`) is a *parallel* new store, not a rewrite of the
  old one; `grading.py`'s settlement/CLV path (§2) still reads the old
  single-book series (`_index_snapshots` takes `snapshot_rows`, and
  `daily_loop.sh`/CLI wiring was not traced further in this pass — flagged
  as a question, not resolved here).
- **`closing=null` in every settlement row, ledger-wide** — confirmed both by
  direct sampling and by the changelog (`docs/OVERNIGHT_RUN.md:283`). The
  `closing_backfill` kind (210 rows, the largest kind in the ledger) exists
  to patch this after the fact, and one sampled backfill's own `reason`
  field names a specific join bug (`"abbreviation join bug 65f499a"`) as the
  root cause — i.e., a structural gap turned into permanent extra ledger
  complexity rather than being fixed at the source.
- **Historical splits/arsenals are season-to-date** — `docs/OVERNIGHT_RUN.md:183-184`:
  "safe live and a leak historically. `assert_point_in_time` raises;
  game-log reconstruction needed." This means the *forward* capture of
  starter/hitter splits at decision time is not proven leak-free by
  construction, only by an assertion that raises when violated — i.e., a
  guard against a known failure mode, not evidence the failure mode cannot
  recur in a code path the guard doesn't cover.
- **`market_unavailable` is real and large in the underlying research**: a
  first-five-market screen study found 30% of flagged candidate games had
  *no first-five market at all* on the board (`docs/OVERNIGHT_RUN.md:190-207`),
  meaning `verdict: market_unavailable` (7/144 in the ledger sample) is not
  an edge case, it's a first-order outcome the ledger must and does
  represent as its own state — this part of the vision ("ask which market
  best expresses the advantage," "0..N opportunities, never force it") is
  structurally supported, just only across a two-market universe (h2h,
  first-five) today.
- **Wind direction unusable**: `orientation_deg` is `None` for all 30 parks
  by design, reported but never used as a signed effect
  (`docs/OVERNIGHT_RUN.md:169-171`).
- **Reverse line movement / steam** are explicitly blocked/unsupportable
  today: no public bet-percentage source, and (pre-multibook-fix) only 3
  snapshots/day historically (`docs/OVERNIGHT_RUN.md:171-173`).
- **Capture coupled to an interactive session container** until very
  recently: `docs/CAPTURE_EXTERNALIZATION.md` documents five container
  restarts on 2026-09-02 killing capture mid-run, and proposes (and per the
  doc, implements in-worktree) a GitHub Actions cron externalization
  (`scripts/capture_slot.sh`, `.github/workflows/forward-capture.yml`,
  15-minute cadence) — but the doc's own "Default-branch constraint" section
  says the *scheduled* trigger will not actually fire until the repo's
  default branch is repointed to the working line (owner action, not yet
  confirmed done as of this map's writing), so the externalization may still
  be sitting off, silently, with `daily_loop.sh` as the only writer left in
  the interactive session.
- **`daily_loop.sh` remains a second writer** in-session
  (`docs/CAPTURE_EXTERNALIZATION.md`, "Known follow-up" section) — a known,
  accepted, still-open risk of a rebase conflict against the externalized
  capture job, mitigated only by fetch/rebase/escalate discipline, not
  eliminated.

## 5. Classification against the owner's vision

### EXISTS
- Point-in-time information_time distinct from write time — `src/pipeline/ledger.py:104-109`.
- Append-only ledger with settlement as a separate, non-mutating row — `src/pipeline/ledger.py:14-19`, confirmed structurally in the 427-row file (144+73+210 = 427, no overlap in kind).
- Every game recorded, not just picks (no_play/market_unavailable are rows) — 134 no_play + 7 market_unavailable + 3 flagged = 144, `src/pipeline/ledger.py:31-34` states this as a design goal, matches the data.
- Bracketed (grade-B) point-in-time capture of lineups, probables, transactions, umpire-crew reveal — `src/pipeline/rosterwatch.py`, `src/pipeline/umpirewatch.py`, live examples in `data/watch/*.jsonl`.
- Multi-book price board per event (h2h) with per-book `book_last_update` alongside our own `observed_utc` — `data/processed/odds_multibook.jsonl` (19,487 rows).
- Weather forecast captured per tick with hours-to-first-pitch, not just one reading — `data/processed/weather_forecast.jsonl`, `src/pipeline/weather_capture.py:17-27`.
- Plain-language, mechanism-bearing findings per recommendation (`findings[].claim`) with a sample size and an evidence label — sampled `recommendation` rows.
- market_unavailable as a first-class verdict, matching a real, measured 30% first-five-market gap — `docs/OVERNIGHT_RUN.md:190-207`.

### PARTIAL
- "Why" — findings exist and are structured, but there is no synthesis/rationale field beyond a one-line `summary`; no field distinguishes the winning thesis from the findings that fed it.
- Price/book — multi-book board is captured for h2h and first-five prices; no `chosen_book`/execution-price field on the recommendation, and the moneyline snapshot's *closing-grade* path (`grading.py`) still appears to depend on the old single-book `odds_snapshots.jsonl` store per the confirmed 96%-fanduel defect.
- Closing for grading — exists via a bolted-on `closing_backfill` kind (210 rows) rather than being produced correctly at settlement time (`closing=null` in every sampled `settlement` row).
- Market search — real, but confined to two markets (`h2h`, `first_five`) plus their derivative price fields (`spreads`, `totals`, `totals_1st_5_innings` appear in `prices{}` but `market` (the *chosen* market) is only ever `null` or `"first_five"` in 144 sampled rows — spreads/totals are shown, never selected).
- Prop markets — a listing/pricing *availability audit* exists for exactly one market (`pitcher_strikeouts`), not wired into any recommendation.
- Splits/arsenals point-in-time integrity — guarded by an assertion that raises on violation, not proven leak-free by construction; explicitly flagged historically leaky by the project's own doc.

### MISSING
- Bet rating / confidence tier / stake sizing on any recommendation row.
- Counterarguments field or structure.
- Supporting-systems / strategy-id field (no representation of "which of potentially many competing analysis systems produced this").
- Structured end-of-day self-review joined to the ledger (thesis correct? variance? missed info? demotion/promotion?) — only a hand-written prose changelog exists.
- Any run-line, alt-line, team-total, F5-ML-team-total-beyond-h2h, batter prop, pitcher prop (beyond one K-market availability audit), derivative (race-to-X, first-to-score), or parlay/SGP representation anywhere in the ledger or its supporting stores.
- Multiple recommendation snapshots per game as odds/lineups move pre-game (one-row-per-game-ever design, `ledger.py:62-79`) — no trajectory, only one point-in-time cut.
- Bankroll/units simulation tied to ledger recommendations (not found in this subsystem's files; out of scope to confirm elsewhere, but no `units`/`bankroll` field appears on any ledger row here).
- Roof-actually-open/closed observation (explicitly disclaimed as unknowable from the current weather source).
- Reverse line movement / bet-percentage / steam detection (explicitly blocked, no data source).

### CLAIMED-BUT-ABSENT
- `closing` field on `settlement` rows exists in the schema (the key is present) but its value is `null` in every sampled row — a schema that promises a value the pipeline does not yet fill in; the real value lives in a separately-computed row (`closing_backfill`) that has to be joined back in by callers (`grading.py:727` `effective_closing`) rather than being present on the settlement itself.
- The forward-capture externalization doc describes a scheduled GitHub Actions workflow as the recommended, implemented fix, but its own "Default-branch constraint" section says the schedule will not fire until an owner action (repointing the default branch) happens — so "capture runs independent of the interactive session" is a design that exists in the worktree, not yet a confirmed-running fact.
- `sections_present` on a recommendation lists names like `"arsenals"`, `"splits"`, `"bullpen"` as present, but this subsystem's evidence only shows detector *claims* referencing these concepts in `findings[]` — this pass did not verify (out of scope: that lives in `briefing.py`/detector modules, not the ledger/store files) that every named section carries the full depth the vision describes (e.g. per-pitch arsenal usage vs. a single FIP number); treat "sections_present" as a coverage flag, not a depth guarantee.

## 6. BOOST vs REPLACE, per component

- **`rosterwatch.py` / `umpirewatch.py` (bracketed point-in-time capture)** —
  BOOST. The bracketing design is exactly what the vision needs for
  reconstructing decision time, is well-tested (module docstrings cite
  specific past incidents it fixes), and generalizes cleanly to more event
  classes (starter scratches, IL moves are already partially covered via
  `transactions_watch.jsonl`'s `category` field). Extend to reliever
  availability/leverage state and roof-open/closed the moment a real feed
  exists, rather than rebuilding the polling machinery.
- **`weather_capture.py`** — BOOST. Per-tick, non-deduped capture is the
  right shape; needs no structural change, only a roof-truth source when one
  becomes available.
- **`ledger.py`'s one-row-per-game-ever rule** — REPLACE (the specific
  dedup rule, not the whole module). The append-only, settlement-as-separate-row
  design is correct and should stay; the rule that blocks re-recording a
  game once priced actively prevents the ledger from ever representing line
  movement or a lineup-driven verdict change pre-game, which the vision
  requires ("capture everything needed to reconstruct decision time," and a
  decision late in the pre-game window is a different decision from one made
  at 10am). Needs a versioned-recommendation model: many timestamped
  recommendation rows per game, with a clear "latest before first pitch"
  selector for grading, instead of "first priced row wins forever."
- **`grading.py`'s closing-value path** — REPLACE the settlement-time closing
  computation; BOOST/keep the backfill machinery as a temporary repair tool.
  The correct fix is for `settle()` (or the daily loop) to thread the actual
  closing observation into the `settlement` row at settle-time, using the
  multi-book store, not the confirmed-degenerate single-book
  `odds_snapshots.jsonl`. Recommend investigating (outside this subsystem's
  file list, in the CLI wiring) why `closing` is never threaded, since
  `_closing_line_value`/`find_backfillable_closings` clearly know how to
  compute it.
- **Recommendation record schema itself** — BOOST via addition, not replace:
  the existing fields (`findings`, `sections_present`, `gaps`, `prices`,
  `books`) are real infrastructure worth keeping; the vision's missing
  fields (rating, counterarguments, supporting-system id, chosen
  book/execution price, self-review linkage) are additive columns on the
  same row shape, not a redesign.
- **Market coverage (prop_listing/prop_prices)** — BOOST from a narrow,
  working pattern: the availability-audit design (`books_listing: 0` as an
  absence proof, sampled earliest/median/latest by commence_time,
  credit-capped) is sound and reusable; it simply needs to be run across
  many more market keys (batter/pitcher props, alt lines, team totals) and,
  critically, actually wired into `briefing.py`/`ledger.py` so a
  recommendation can select from more than two markets.

## 7. Data that becomes unrecoverable if not captured now

- **Umpire-crew reveal timing** — MLB does not publish when a crew was
  assigned, only that the API now shows one; the *timing* of that reveal is
  only knowable by having polled through the transition (module docstring,
  `src/pipeline/umpirewatch.py:6-10`). Any day not polled is a permanently
  lost data point for the V3 timing study.
- **Lineup/probable/transaction state-change brackets** — same argument;
  historical replay is explicitly "unsupportable" because past sources are
  date-only (`docs/OVERNIGHT_RUN.md`, timestamp-audit section: "Historical
  replay is unsupportable (transaction dates are day-only, stored lineups
  are date-only...)"). Every day the poller does not run is a bracket that
  can never be reconstructed after the fact.
- **Per-tick weather forecasts** — Open-Meteo answers "what does the model
  say right now"; a forecast from six hours out cannot be re-fetched later
  once time has passed (`src/pipeline/weather_capture.py:6-10`).
- **Multi-book price boards** — `book_last_update` per book per event is the
  only way to later measure first-mover/consensus/stale-book behavior; the
  single-book legacy store already lost this for whatever window it was the
  only writer (its 96%-fanduel defect period).
- **Any live-game roof state** (open vs closed) — flagged as not capturable
  even now from the current source; if a future feed appears, only forward
  capture from that point on will ever have ground truth — no source
  retroactively reveals what the roof was doing on a past night.
- **Prop-market listing/pricing coverage** (which books listed which prop
  markets, at what price, at what audit timestamp) — `prop_listing.py`'s own
  docstring: "an audit that quietly accumulated a prop price history would
  be a research [asset]" (`src/pipeline/prop_listing.py:13`) — implying the
  project already recognizes this as a now-or-never capture, currently
  limited to one market key.

## 8. Key numbers (for quick reference)

- Ledger: 427 total rows = 144 recommendation + 73 settlement + 210 closing_backfill.
- Recommendation verdicts (n=144): 134 no_play, 7 market_unavailable, 3 flagged, 0 anything resembling a placed/graded "play."
- Recommendation markets chosen (n=144): 134 `null`, 10 `"first_five"` — h2h/spreads/totals never chosen as the market, only ever shown in `prices{}`.
- `data/watch/*`: 252 + 222 + 354 + 37 = 865 rows across the four watch stores; roughly 60-65% of lineups/probables/transactions rows are poll markers, not content.
- `odds_multibook.jsonl`: 19,487 rows vs. legacy `odds_snapshots.jsonl`: 7,324 rows (single-book-dominant, 96% fanduel per project's own audit).
- Prop stores: 446 + 29 = 475 rows, all for one market key (`pitcher_strikeouts`), zero rows for any other prop.
- `training_table.csv`: 2,277 rows, ~46 columns, zero starter/bullpen/arsenal/weather/market columns — team win-loss form only.
