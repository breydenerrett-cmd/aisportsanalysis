# A. What `analyze()` actually consumes today

All line refs are against HEAD in `/home/user/aisportsanalysis`, evidence is either a `file:line` or a command run in this session with real output pasted below it.

## Q1. Trace of `analyze()`'s real inputs

`analyze(snapshot, board, *, systems, adversaries, config)` (`src/engine/analyze.py:138`) takes exactly two data objects: `PriceBlindSnapshot` and `PricedBoard` (`src/engine/analyze.py:17`). Everything a `system.propose()` can see is `PriceBlindSnapshot`'s field list — nothing else, by construction (`__getattr__` raises for any of `FORBIDDEN_PRICE_NAMES`, `src/engine/snapshot.py:98-108`).

`PriceBlindSnapshot` fields (`src/engine/snapshot.py:87-96`): `game_pk, t, point_class, features (dict), available_markets, books_by_market, point_meta, lineup_posted, assumption_exposure, fingerprint`. That's it. No pitcher id, no bullpen, no park, no weather, no odds/book/line field exists on this type at all (forbidden names list, `src/engine/snapshot.py:42-46`, includes `board/quotes/price/prices/price_american/odds/book/books/consensus/consensus_fair/friction/priced_board/quote/best/line_price`).

`PriceBlindSnapshot.from_asof` (`src/engine/snapshot.py:126-161`) folds an `src.core.asof.Snapshot`'s per-field provenance into `assumption_exposure` (a count of `{grade}:{field}` keys) — it does **not** copy the as-of `Snapshot`'s actual field *values* (lineup names, umpire name, weather numbers) into `features` or anywhere else on `PriceBlindSnapshot`. Only `features` (an arbitrary `Mapping[str, float]` the caller supplies) carries numeric signal, and `glue.build_snapshot` (below) shows what actually populates it in practice: nothing, on today's real captures.

### `src/engine/glue.py` — the seam from disk to the waist

- `build_board(game, t, ...)` (`glue.py:194-209`): reads `data/processed/l1_observations.jsonl` price rows, truncates to `observed_utc <= t`, returns a `PricedBoard`. Price-only.
- `build_snapshot(game, t, ...)` (`glue.py:226-254`): calls `src.core.asof.as_of(ref.asof_key, t, ...)` **only if `ref.asof_key` (the MLB numeric `game_pk`) is not None** (`glue.py:244-246`). `features` defaults to `{}` unless the caller explicitly passes a `features=` dict (`glue.py:228, 251`) — `build_snapshot` itself never computes a single feature from any store.
- The module's own docstring (`glue.py:14-37`) states the reason as fact, not hedge: L1 price rows are keyed on the odds provider's opaque `event_id`, `game_pk: null` on **all 56,680 rows** it audited, and no store in this worktree joins `event_id` → `game_pk` for a game before its final boxscore exists. So for any in-progress/future slate, `ref.game_pk` is `None`, `as_of_key` is `None`, the `as_of` read is skipped entirely, and `features={}` unless a caller manufactures features from elsewhere (nothing in this codebase's live CLI path does — see Q6).
- `board_facts()` (`glue.py:212-223`) derives `available_markets`/`books_by_market` from the board's own quotes — the only non-price-shaped facts that flow from price data into the snapshot.

### `src/core/asof.py` — what the forward-store reader knows about, if it runs at all

`_default_stores()` (`asof.py:167-265`) wires exactly seven store specs, each producing named fields:
- `umpires_watch.jsonl` → `home_plate_umpire`, `umpire_crew`
- `lineups_watch.jsonl` → `home_lineup`, `away_lineup` (full lineup blobs, not features)
- `probables_watch.jsonl` → `home_probable_id`, `away_probable_id` (**IDs only** — no ERA/WHIP/handedness/velocity anywhere in this reader)
- `transactions_watch.jsonl` → never matches (`game_key_of=lambda r: None`, `asof.py:202`); transactions reach `information_events.jsonl` instead
- `information_events.jsonl` → 7 named event-kind fields (transaction/lineup/probable/umpire/weather/boxscore events as raw payload blobs)
- `weather_forecast.jsonl` → `temp_f, wind_mph, wind_from_deg, precip_probability_pct, roof`
- `boxscores_2026.jsonl` → `boxscore_rows` (post-game only)

There is **no bullpen field, no starter ERA/WHIP/velocity/handedness field, no park factor field, no recent-form field, no player-prop field** anywhere in `asof.py`'s store list. Even where a field exists (lineup, probable), `as_of` only returns *whether/when* it was knowable — the value itself is an opaque blob (`home_lineup`) or a bare MLB player id (`home_probable_id`), never a computed pitcher/bullpen/matchup number. Those numbers live in `src/research/matrix.py` and the evolab feature registry (`src/evolab/registry.py`), which are fed from `data/research/matchup_matrix_{2023,2024}.jsonl` — files `asof.py` never reads (confirmed: `grep` for `matchup_matrix` inside `src/core/asof.py` returns nothing).

`information_grade()` (`asof.py:374-398`) is the label authority: any of `DEGRADED_SENTINEL_FIELDS` (`home_lineup, away_lineup, home_probable_id, away_probable_id, home_plate_umpire`, `asof.py:365-371`) absent or non-grade-A marks the snapshot `DEGRADED_INFORMATION`. `season_replay_label()` (`asof.py:409-435`) states flatly that **every 2023-24 season is DEGRADED_INFORMATION by construction** because the watch/poll stores did not exist yet.

### `src/engine/adapters/evolab_system.py` — the only non-trivial system wired to `analyze()`

`EvolabGenomeSystem.propose()` (`evolab_system.py:88-111`) rebuilds a `WorldView` from the price-blind snapshot and calls the real `src.evolab.decide.decide_with_reason` (not a re-implementation — the adapter's own docstring says this is deliberate, `evolab_system.py:1-12`). Critically: **`p_model` is always `None`** on every `Proposal` this adapter emits (`evolab_system.py:96-101`, comment: "a genome's `score` is explicitly NOT a probability... this adapter reports p_model=None"). That means every candidate `analyze()` builds off a real evolab genome has `edge_bps = None` forever (see `analyze.py:204-207`: edge_bps only computes when `proposal.p_model is not None`), and `_rank_key` (`analyze.py:257-259`) sorts those to the bottom (`-10**9`).

### Was the current real run just a trivial always-home system? Yes — proven, not inferred

`src/engine/glue.py:378-415` defines `TrivialAlwaysHomeSystem`, whose own docstring states the reason directly: `EvolabGenomeSystem` "decides off signal features (`era_diff`, `whip_diff`, ...) that this project's point-in-time feature pipeline has never populated for an odds-provider `event_id`", so it would always see `features={}` and never propose. `src/cli.py:2001-2028` (`cmd_engine`, the `engine truncation` subcommand — the **only** CLI command that calls `analyze()`/`truncation_differential()` against real data) hard-codes:

```python
systems = (glue_module.TrivialAlwaysHomeSystem(),)
```
(`src/cli.py:2047`)

There is no CLI flag to substitute `EvolabGenomeSystem` here. The trivial system (`glue.py:406-415`) proposes a fixed `p_model=0.52` on `market_key="h2h", side="home"` whenever `"h2h"` is in `available_markets`, unconditionally — it reads no feature at all.

## Four lists

### BUILT + WIRED into `analyze()` today
- `PriceBlindSnapshot` / `PricedBoard` construction end to end (`src/engine/snapshot.py`, `src/engine/glue.py:build_board/build_snapshot`)
- The PROPOSE → PROJECT → ATTACK → RATE → RANK pipeline itself (`src/engine/analyze.py:138-272`)
- De-vig consensus, friction (vig/book_count/staleness/dispersion) computed from real L1 price rows (`src/engine/snapshot.py:227-283`)
- `DEFAULT_ADVERSARIES`: `StaleBook`, `ThinBoard`, `PriceMovedAgainst`, `DegradedInformation` (`src/engine/adversaries.py:153-155`)
- `TrivialAlwaysHomeSystem` (`glue.py:378-415`) — the system actually exercised by the only real-data CLI path (`cmd_engine truncation`, `src/cli.py:2021-2087`)
- `EvolabGenomeSystem` adapter (`src/engine/adapters/evolab_system.py`) — wired and importable, calls the real `decide_with_reason`, but **not invoked by any CLI command against real captures** (only `cmd_engine conform` exercises it, against synthetic conformance snapshots — `src/cli.py:2003-2013`)
- `src.core.asof.as_of` for lineups/probables (IDs)/umpires/weather/boxscores/transactions-via-events, **conditional on a `game_pk` being known** — for the odds-provider event-keyed captures on disk today, this is skipped (see Q6)

### BUILT BUT NOT WIRED into `analyze()`
- `src/detectors`, `src/features` — **do not exist** in this repo (`find src/detectors src/features` returns nothing); whatever detection logic exists lives in `src/detect/` (`base.py, dossier.py, detectors.py`) and is used only by the legacy `src.pipeline`/`src.model` stack (`cmd_predict`, `cmd_scan`, `cmd_brief`, `cmd_daily` in `src/cli.py`), never by `src.engine`
- `src/research/matrix.py` — the matchup matrix that produces every feature the evolab genome registry (`src/evolab/registry.py`) actually knows how to score (starter velocity gap, platoon share, groundball share, top-vs-bottom, primary-pitch share, etc.). Confirmed unimported by `src/engine/*.py` (grep for `src\.research\|src\.pipeline\|src\.model\|src\.analysis` inside `src/engine/*.py` and `src/engine/adapters/*.py`: zero hits)
- `src/report/dashboard.py`, `src/report/ranker.py`, `src/report/archive.py` — used only by `cmd_brief`/`cmd_archive`/`cmd_daily` in `src/cli.py`, never by `analyze()`
- The entire legacy `src/pipeline/` (30 files: bullpen, briefing, mismatch, features, predict, pitchers, lineups, news, rosterwatch, weather_capture, ...), `src/model/` (dataset, discovery, pointintime, logistic, selections, rebuilt_sections, seal), `src/analysis/` (matchup, synthesis, relevance, prices, disclaimers, betcheck) and `src/detect/` packages: real, substantial code, importing real bullpen/pitcher/handedness/statcast/arsenal stores, but reachable only from `src.evolab.baseline`/`src.evolab.replay` (for backtesting) and the pre-engine CLI commands (`cmd_predict`, `cmd_scan`, `cmd_daily`, `cmd_brief`) — **none of these are called from `src/engine/analyze.py`, `src/engine/glue.py`, or `src/engine/adapters/*.py`** (verified by grep, above)
- `src.evolab.replay` (`world_view`, `execution_quote`, `load_universe`, `decision_points`) — a fully working, real-data historical replay path (see Q5) that is architecturally parallel to, and never called by, `src.engine.analyze.analyze()`

### CAPTURED BUT NOT USED (no engine path — `analyze()`, `glue.py`, or `asof.py` — reads them)
- `data/historical/bullpen_log.jsonl` (14.9 MB), `pitcher_logs.jsonl` (9.2 MB), `pitcher_splits.json`, `handedness.json`, `data/historical/statcast/`, `data/historical/statcast_pre_bbtype/`, `data/historical/arsenals/` — read only by `src.pipeline`/`src.model`/`src.detect`/`src.research`, never by `src.core.asof` or `src.engine.glue`
- `data/historical/mlb_results.csv`, `data/historical/odds_history/`, `data/historical/odds_first_five/`, `data/historical/first_five_results.jsonl`, `data/historical/transactions.jsonl` — read by `src.evolab.replay`/`src.research.pricepath`/`src.research.matrix` for backtesting, never by the live `analyze()` seam (`glue.py`)
- `data/research/matchup_matrix_2023.jsonl`, `matchup_matrix_2024.jsonl` — read by `src.evolab.replay.load_universe` and `src.research.matrix`, never by `glue.build_snapshot`
- `data/processed/batter_props.jsonl`, `prop_listing.jsonl`, `prop_prices.jsonl` — no reference from `src/engine/*` at all (their consumers are `src/pipeline/prop_prices.py`, `batter_props.py`, `prop_listing.py`)
- `data/watch/transactions_watch.jsonl` — `asof.py`'s own `transactions_watch` `StoreSpec` has `game_key_of=lambda r: None` (`asof.py:202`), i.e. it **never matches any game**, by explicit design; the file is captured but that store spec is a structural no-op

### PLANNED / MISSING
- No engine-side feature builder exists that turns `data/research/matchup_matrix_*.jsonl` (or `data/historical/pitcher_logs.jsonl`/`bullpen_log.jsonl`/`handedness.json`) into `PriceBlindSnapshot.features` for a live/future slate — `glue.build_snapshot`'s `features` parameter has no default source at all (`glue.py:228`)
- No `event_id → game_pk` join for in-progress/future games exists on disk (`glue.py:14-37` documents this as a known, unaddressed gap, not a bug)
- No CLI path passes `EvolabGenomeSystem` (or any feature-bearing system) to `analyze()` against real captured L1 data — `cmd_engine truncation` is hard-wired to `TrivialAlwaysHomeSystem` (`src/cli.py:2047`)
- Starting-pitcher identity, bullpen state, park factor, weather values, offense/lineup composition, handedness splits, recent form, and player-specific data are all captured somewhere in `data/`, but none reach `analyze()` for a live decision today; only lineup IDs / umpire name / weather values / boxscore rows are even *reachable* through `asof.py`, and only when a `game_pk` is known

## Q6. Current-slate run through the real code path

Command run (driver script built on `glue.build_board`/`build_snapshot` + `analyze`, `TrivialAlwaysHomeSystem`, `DEFAULT_ADVERSARIES`):

```
$ PYTHONPATH=. python3 run_current.py
```
Script logic: `games = glue_module.games_captured_on("2026-09-02")` → 39 games; picked `games[0]`; `t = glue_module.latest_capture_time(game, date_str)`; `board = build_board(game, t)`; `snapshot = build_snapshot(game, t, board=board)`; `analyze(snapshot, board, systems=(TrivialAlwaysHomeSystem(),), adversaries=DEFAULT_ADVERSARIES)`.

Actual stderr output:
```
games captured on 2026-09-02 : 39
game= 0b0373954f04c35c2aaee9aed8171c17 t= 2026-09-02T22:19:22.122559+00:00
snapshot.available_markets= ('h2h', 'h2h_1st_5_innings', 'spreads', 'totals')
snapshot.books_by_market= {'h2h': 11, 'h2h_1st_5_innings': 9, 'spreads': 1, 'totals': 1}
snapshot.features= {}
snapshot.assumption_exposure= {}
snapshot.lineup_posted= False
board.selections()= ('00a391565795eb45', '024f6e20e371417b', '06878ae9309be6a6', ...)
n records: 1
```

Only **one** `DecisionRecord` was produced (the task asked for the first two, truncated — there is only one, because the trivial system emits exactly one `Proposal` for `market_key="h2h", side="home"`, and only one board selection matches that market+side). Verbatim record:

```json
{
  "engine_version": "engine-1",
  "system_id": "trivial_always_home",
  "system_version": "trivial-1",
  "registry_fingerprint": "",
  "frame_fingerprint": null,
  "snapshot_fingerprint": "442c79c17420d66d2a242e0bd3c8886796691967665adbdb1b50442a926cb493",
  "game_pk": null,
  "event_id": "0b0373954f04c35c2aaee9aed8171c17",
  "decision_utc": "2026-09-02T22:19:22.122559+00:00",
  "point_class": "LATE_BOARD",
  "information_time": "2026-09-02T22:19:22.122559+00:00",
  "recorded_utc": "2026-09-02T22:19:22.122559+00:00",
  "verdict": "play",
  "selection_id": "9e8d61f45a38abf0",
  "market_key": "h2h",
  "line": null,
  "book": "fanduel",
  "price_american": 3500,
  "consensus_fair": 0.2220654117946723,
  "books_at_decision": 11,
  "friction": {"vig": 0.04089387634150596, "book_count": 575, "staleness_seconds": 0, "dispersion": 0.6443533697632058},
  "p_model": 0.52,
  "p_model_interval": null,
  "edge_bps": 2979,
  "price_improvement_bps": null,
  "rating": {"probability_quality": 0.040000000000000036, "price_quality": 0.19428763401689453},
  "thesis": "trivial fallback: always proposes home at a fixed, never price/clock-derived p_model -- src.engine.glue",
  "evidence": ["trivial_fallback"],
  "counterarguments": [
    {"adversary_id": "degraded_information", "cause": "degraded_information:replay_label_degraded_information", "severity": "MAJOR",
     "detail": "DEGRADED_INFORMATION: away_lineup: not present in assumption_exposure; away_probable_id: not present in assumption_exposure; home_lineup: not present in assumption_exposure; home_plate_umpire: not present in assumption_exposure; home_probable_id: not present in assumption_exposure"}
  ],
  "supporting_systems": ["trivial_always_home"],
  "refusal_reason": null,
  "assumption_exposure": {},
  "stake_units": 0.0,
  "known_at_grade": "A",
  "prev_hash": "", "row_hash": ""
}
```

**Fields null/absent and why:**
- `game_pk`: null — the L1 store's `event_id` (`0b0373954f...`, an opaque odds-provider hash) has no known mapping to an MLB numeric `game_pk` in this worktree for an unfinished game (`glue.py:14-37`)
- `snapshot.features`, `snapshot.assumption_exposure`: both `{}` — because `ref.asof_key` (`= game_pk`) is `None`, `build_snapshot` never calls `as_of` at all (`glue.py:244-246`); every counterargument reason in the record ("not present in assumption_exposure") is therefore reporting an absence caused by the `game_pk` gap, not by an actual missing capture
- `line`: null — this selection's row carries no line (h2h market)
- `p_model_interval`: null — never populated anywhere in `analyze.py`; no system in this codebase emits an interval
- `price_improvement_bps`: null — never computed anywhere in `analyze.py`
- `refusal_reason`: null — only set on a `no_play`/refused verdict path (this record's verdict is `"play"`)
- `frame_fingerprint`: null — caller (`run_current.py`) never passed one; `analyze()`'s default is `None` (`analyze.py:141-142`)
- `registry_fingerprint`: empty string — same, caller default
- `stake_units`: 0.0 — never sized; `analyze.py` hard-codes `stake_units=0.0` on every record (`analyze.py:369` in `_to_decision_record`)
- `lineup_posted`: `False` — same `game_pk` gap; never checked from any store
- `known_at_grade`: `"A"` — computed by `_to_decision_record`'s grade logic (`analyze.py:308-318`), which defaults to `"A"` when `assumption_exposure` is *empty* (not when it is populated with real D-grade fields) — i.e. an artifact of the empty-exposure case, not a genuine A-grade claim; the `DegradedInformation` adversary's counterargument on this same record is the honest signal, contradicting the `known_at_grade` field

Note the internal tension this run exposes: `known_at_grade="A"` and a `MAJOR` `DegradedInformation` counterargument coexist on the same record — both are individually correct given their inputs, but the `known_at_grade` computation (`analyze.py:308-318`, "empty exposure → grade A") does not distinguish "no degraded fields" from "no as-of read happened at all."

## Q5. Historical replay (2023 game, real data, closest real stop-at-T path)

`analyze()` itself was never run on 2023 data (no code path connects `glue.build_snapshot`/`build_board` to `data/research/matchup_matrix_2023.jsonl` or `data/historical/odds_history/`). The closest real stop-at-T path is `src.evolab.replay` (`world_view`, `board_at`, `execution_quote`) + `src.evolab.decide.decide_with_reason` — the same decision function `EvolabGenomeSystem` calls, run directly against real 2023 data instead of through the (unpopulated, for 2023) `PriceBlindSnapshot` seam.

Command run:
```
$ PYTHONPATH=. python3 run_replay.py
```
`u = replay.load_universe(seasons=(2023,))` → **2,406 games** loaded from real `matchup_matrix_2023.jsonl` + `pricepath.build(2023)` (real `odds_history`/`odds_first_five`), with manifest exclusion counters printed:
```
{'duplicate_quotes_conflicting': 0, 'duplicate_quotes_identical': 0, 'matrix_rows': 2430, 'multi_event_games': 5,
 'no_first_pitch': 0, 'no_price_path': 22, 'no_usable_instant': 2, 'official_date_disagreements': 1,
 'quotes_at_or_after_first_pitch': 24, 'quotes_unusable': 0}
```

Game chosen: `718781`, SF @ NYY, 2023-03-30, Yankee Stadium (real `mlb_results.csv` row). Decision instant `T` = the game's last pre-commence captured instant, `2023-03-30T16:45:39+00:00` (19 books quoting).

**Information available at decision time** (`replay.world_view(g, T)`):
```
point_class: LATE_BOARD
available markets: ('h2h',)
lineup_posted: True
features (non-null): away_lineup_platoon_share=0.667, home_lineup_platoon_share=0.222
```
(every other registered feature — starter velocity gap, groundball share, primary-pitch share, top-vs-bottom — was null for this game/instant; the matrix row simply didn't have them populated for this early-2023 game.)

**Prices available** (`replay.board_at(g, T)`, real `odds_history` quotes, 19 books) — e.g. `fanduel: away +150 / home -178`, `bovada: away +141 / home -170`, full 19-book set printed by the script.

**Candidate generation / decision**: genome = one signal on `lineup_platoon_share`, threshold_index 0 (registry ladder `(0.222, 0.334, 0.445)`, `src/evolab/registry.py`), `min_score=1.0`. Differential = `away(0.667) - home(0.222) = 0.445` ≥ rung 2 (0.334) but the fired rung is index 0 (score 1.0 already clears `min_score`):
```
DECISION: Decision(market='h2h', side='away', score=1.0, signals_fired=(('lineup_platoon_share', 0),), execution_mode='CONSENSUS_EXECUTION')
```

**Ranking / frozen record (execution)**:
```
EXECUTION QUOTE: ExecutionQuote(mode='CONSENSUS_EXECUTION', market='h2h', side='away',
  observed_utc='2023-03-30T16:45:39+00:00', books=19, price=None, book=None,
  tied_books=(), consensus_probability=0.386250013580343, refused='')
```
`price=None` is by design in `CONSENSUS_EXECUTION` mode — a de-vigged consensus probability across 19 books is not any single book's quotable price (`replay.py:1133-1136`).

**Information grade** (`src.core.asof.information_grade`, run against this same real `game_pk="718781"` at this same `T`):
```
INFO GRADE: ReplayLabel.DEGRADED_INFORMATION
  ['away_lineup: no observation before t', 'away_probable_id: no observation before t',
   'home_lineup: no observation before t', 'home_plate_umpire: no observation before t',
   'home_probable_id: no observation before t']
```
Confirms `asof.py`'s own rule (`asof.py:409-435`): every 2023-24 game is `DEGRADED_INFORMATION` by construction because the `data/watch/*.jsonl` poll stores did not exist yet. **This replay is labeled degraded-information per `src.core.asof`.**

**Result and settlement** (`data/historical/mlb_results.csv`, real row):
```
away_team=SF, home_team=NYY, away_score=0, home_score=5, winner=NYY, home_won=1
```
The genome decided AWAY (SF); the actual winner was NYY (home). **The decision would have lost.** No CLV/closing-line comparison was run (out of scope for this driver; `src.evolab.baseline`/`sweep` have that machinery but were not invoked here to stay within the zero-odds-API-credit / read-only constraint — no external calls were made, everything above ran off files already on disk).

**What remains to unify Q6's path (via `src.engine.glue`/`analyze()`) with Q5's path (via `src.evolab.replay`/`decide_with_reason`)**: `EvolabGenomeSystem.propose()` (`evolab_system.py:88-111`) already calls the identical `decide_with_reason` function Q5 used — the adapter exists. What's missing is a `glue.build_snapshot`-callable feature source: today `build_snapshot`'s `features` argument has no wiring to `src.research.matrix`/`data/research/matchup_matrix_*.jsonl` the way `replay.world_view`/`_features_for` (`replay.py:697-717`) does, and no `event_id → game_pk` join exists for in-progress games (`glue.py:14-37`) — until both exist, `EvolabGenomeSystem` run through `glue.build_snapshot` on a live/current slate will always see `features={}` and never propose (exactly as `TrivialAlwaysHomeSystem`'s own docstring states, `glue.py:386-395`). The functions that would need to be written: a `glue`-side feature builder analogous to `replay._features_for`, and a `game_pk`-from-`event_id` resolver for pre-boxscore games (`src.board.events` currently only joins on `(team_name, date)` against finished boxscores, `glue.py:24-26`).

## Capability table

| capability | status | evidence |
|---|---|---|
| PROPOSE→PROJECT→ATTACK→RATE→RANK pipeline | WORKING | `src/engine/analyze.py:138-272`; Q6 run produced a real, structurally valid `DecisionRecord` |
| De-vig consensus / friction from real prices | WORKING | `src/engine/snapshot.py:227-283`; Q6 record shows real `consensus_fair=0.222`, `friction.vig=0.041` off `fanduel`+10 other books |
| Adversary vetoes (StaleBook/ThinBoard/PriceMovedAgainst/DegradedInformation) | WORKING | `src/engine/adversaries.py:153-155`; Q6 record carries a live `DegradedInformation` MAJOR counterargument |
| `TrivialAlwaysHomeSystem` on real current-slate L1 data | WORKING | `src/cli.py:2047`; Q6 output above |
| `EvolabGenomeSystem` adapter calling real `decide_with_reason` | WORKING (adapter code), NOT WIRED to live slates | `evolab_system.py:88-111`; only exercised via `cmd_engine conform` on synthetic snapshots (`src/cli.py:2003-2013`), never on real current-slate data because `features={}` there |
| Feature pipeline (pitcher/bullpen/park/weather/handedness/matchup) feeding `analyze()` for a live/current game | NOT BUILT | `glue.py:228,251` — `features` has no default source; `glue.py:14-37` documents the `event_id`↔`game_pk` gap as the blocking cause |
| `src.core.asof` forward-store read (lineup/probable-id/umpire/weather/boxscore) for a live game | PARTIAL — code works, but conditional and narrow | `asof.py:167-265` (7 stores, IDs/blobs only, no bullpen/ERA/park); gated on `game_pk` being known (`glue.py:244-246`), which fails for current in-progress captures (Q6: `assumption_exposure={}`) |
| Detectors / features / matrix / report packages | SCAFFOLD ONLY (relative to `analyze()`) | `src/research/matrix.py`, `src/report/*`, `src/pipeline/*`, `src/model/*`, `src/detect/*` all real and substantial, but zero imports from `src/engine/*.py` (grep confirmed) |
| Historical replay via `src.evolab.replay` on real 2023-24 data | WORKING, but structurally separate from `analyze()` | Q5 run: 2,406-game 2023 universe loaded, real decision + execution quote + settlement produced for game 718781 |
| Unified `analyze()` path for historical replay | NOT BUILT | no code calls `glue.build_snapshot`/`build_board` against 2023-24 stores; would need a matrix-backed feature builder + event_id/game_pk join, named above |
| Degraded-information labeling | WORKING | `asof.py:374-435`; both Q6 (empty exposure, live) and Q5 (2023, explicitly `DEGRADED_INFORMATION`) demonstrated with real output |
| Starting pitcher / bullpen / handedness / park / weather / recent-form / player-specific data reaching a live decision | NOT BUILT | none of these fields exist on `PriceBlindSnapshot` or reach it through any wired path; captured in `data/historical/*` and `data/research/matchup_matrix_*` but unread by `src.engine.*` |
