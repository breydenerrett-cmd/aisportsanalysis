# Send to training: where the time goes (measured 2026-10-29)

Harness: `scripts/train_timing.py` (stdlib only, no network, no model, no key read). Re-run: `python3 scripts/train_timing.py`
(`--list`, `--only a,b`, `--fixture even|weak`, `--runs N`, `--json out`). Nothing was optimized; this is measurement only.

## Method and limits (read before trusting a number)

- Fixture: HOCKEYCHIEF, a v2 hound with 4 rules over NHL (x2), TENNIS, MLB; 25 settled bets as ledger rows (`weak` fixture: TENNIS 2-11, a real
  non-core weak spot, so the proposal has 2 changes to count; the `even` fixture, where the proposal is "keep going", timed the same within 0.1 s).
  Temp app DB and ledger, as in `tests/_hounds_rites_fixtures.py`. "Now" is 2026-10-29 21:30Z (the checked-in odds store has 27 games on its slate that day).
- Functions are called directly, as `api/hounds_interact.py` does. The model is a fake that answers instantly and counts calls. **No wall number below
  includes model time.**
- Real stores read from this checkout (an open() wrapper recorded them): `data/processed/odds_multibook.jsonl` 28.3 MB / 74k rows, 15 gz archive segments
  18.0 MB, `boxscores_2026.jsonl` 5.1 MB, `data/historical/mlb_results.csv` 1.3 MB, `event_game_map.jsonl` 1.1 MB (the rebuild also reads
  `allsports_scores.jsonl`, `data/datasvc/nfl/games.jsonl`).
- Each timed run starts with the coach cache, the 60 s slate cache and the 30 min drill cache cleared (the owner's first click is the one that matters). 3 un-profiled runs per stage,
  median reported; one extra cProfile run per stage for hot spots (cProfile inflates wall ~2.5x, so hot-spot seconds are shares, not wall).
- This is a Windows dev box. Production is 2 shared vCPU / 1 GB (`deploy/fly.production.toml:132-135`), one machine. Expect it to be slower. The size of that factor was not measured.
- **Not measured, and could be the rest of the owner's wait:** `ask_eval.default_slate` (ask_eval.py:96) and `drill` take the process-wide build gate
  (`src/appstate/freshness.py:148`, a blocking RLock that every background cache rebuild also holds). A propose that arrives while one runs waits for it; this harness has no background builds.
- The fixture's event ids are fake, so the closing-odds scan matched no rows; real ids match ~7k rows (measured with 25 real ids), which adds a little downstream work. Not included.
- Model latency is assumed at 3 s per Haiku call (the brief's number). The rebuild asks for adaptive thinking at effort "high" with a 12,000-token cap
  (`rebuild_ai.py:53-54`), so 3 s is a floor for rebuild calls, not an estimate.

## Table (median of 3, seconds; model time excluded from the middle column)

| Stage (route) | Median s, no model | Model calls | Serial? | Est. total with model (3 s/call) |
|---|---|---|---|---|
| diagnose (`train/diagnose`) | **2.90** | 0 | n/a | 2.9 |
| assess, diagnosis cached (`train/assess`, normal page order) | 0.01 | 1 (Haiku, `coach_ai.assess`) | yes | 3.0 |
| assess, cache miss (diagnose + assess) | 2.87 | 1 | model after the 2.9 s scan | 5.9 |
| **propose** (`train/propose`, diagnosis+read cached, slate cold) | **3.09** | 0 | n/a | 3.1 |
| propose, 2nd click inside 60 s (slate warm) | 0.30 | 0 | n/a | 0.3 |
| propose, everything cold (diagnose/assess skipped or cache gone) | 5.99 | 1 | model after the scans | 9.0 |
| propose with a Tweak (round 1) | 3.62 | 1 (`retune.map_chat`) | after 25 board evals | 6.6 |
| rebuild, rehearsals faked | 0.05 (first run 0.5: one-time read of box scores) | 8 (6 angle + analyst + explainer) | depth 3 (angles concurrent) | 9.1 |
| **rebuild, real rehearsals** (`train/rebuild`, async job) | **97.4** | 8 (up to 14 with angle retries) | depth 3, measured | 106 (floor) |

First-time owner path, server time only: diagnose 2.9 + assess ~3 (model) + propose 3.1 = about 9 s, behind a page that stages its own
17 s of "scanning" lines (`web/js/dog-diagnose.js:36`, `TIMING.rowTarget`). "Preparing the proposal..." (`web/js/dog-rites.js:372`) is the propose call alone: **3.1 s here, no model in it.**

Serial depth was measured, not read: giving every fake model call 0.25 s added 0.75 s to the rebuild (3 calls deep: the 6 angles run in a
`ThreadPoolExecutor`, `rebuild_ai.py:534`; the analyst and the explainer follow one after another). An angle that is refused retries once, serially (`ANGLE_RETRIES`), which adds a fourth step.

## What the premise got wrong

The brief expected the propose wait to be many `retune.whatif` replays of the board. It is one. `propose` made 4 board evaluations (base, 2 changes, new rule); the
first took 2.8 s and the other three took 0.05 s together. A Tweak makes 25 evaluations: 2.83 s for the first, 0.5 s for the other 24. The cost is **building the
slate once**, then the 60 s cache (`ask_eval.py:39`) makes every variant nearly free. The model is not in the propose path at all unless the coach cache missed.

## Hot spots (profiled runs; shares of cProfile time)

1. **Propose: slate build, 2.8 of 3.1 s.** `retune.py:523 board_counts` -> `ask_eval.py:356 earlier_user` -> `ask_eval.py:84 default_slate`, which at **`ask_eval.py:100`** calls
   `V2.build_slate(date, user_spec.SPORTS, ...)`: it builds the slate for **all 17 sports** for a hound that bets 3. -> `user_engine_v2.py:561` -> `user_engine.py:485 iter_rows` ->
   `snapshots.py:746 iter_multibook_multi` (248k rows through `json.loads` at `snapshots.py:770`; 5.8 of 8.0 profiled s) -> `user_engine.py:410 build_games`. First call is called from
   `training.py:964` (`retune.whatif(spec, [], board_fn)`), so the cost is paid before any change is even considered.
2. **Diagnose: closing-odds scan, 2.8 of 2.9 s.** `diagnosis_live.py:51 board_moves` -> `boards.py:112 scan`. `boards.py:152 keep()` runs only after
   `snapshots.py:717 json.loads` has parsed every row: **664,180 rows parsed to keep ~7k**, because `since` = the hound's oldest bet date (here 2026-10-01), which pulls in 6 archive segments plus the whole
   hot file. It grows with hound age. It runs on a thread with `CLOSE_BUDGET_S = 12` (`diagnosis_live.py:35`): on a slower box the factor can silently turn into "not checked (took too long)".
3. **Rebuild: the 8 rehearsals are 96.5 of 97.2 s (99%) in run 1.** Base + 6 angle candidates + the analyst's merge, 11.7-12.6 s each, run one after another
   (`training_plans.py:628`, `:678`, `:698`), each a full `drill.drill` (`drill.py:416`). One drill profiles at 88% in `drill.py:146 _window_rows`: it re-reads the store once per sport per
   8-day chunk (`CHUNK_DAYS`, `drill.py:143`, called at `:241`), 12 passes over ~7.9M lines for 3 sports x 4 chunks. The engine itself (`user_engine.run`) is 7% (2.7 of 36 profiled s).
   The batch entry point already exists (`drill.drill_many`, `drill.py:488`; `default_replay_many`, `training_plans.py:134`) but `full_rebuild` uses it only for Gematria hounds (`training_plans.py:667-672`).
4. Everything else is noise at this scale: the diagnosis maths 0.02 s, assess with a cached table 0.01 s, the rebuild's own Python 0.05 s. Propose with a warm slate is 0.30 s, mostly menu validation (`retune.py:365 loosening_menu` -> `user_spec.validate_spec`, 167 calls).

## Fix candidates, ranked by expected seconds saved (not implemented)

| # | Change | Where | Evidence | Expected saving |
|---|---|---|---|---|
| A | Rehearse ordinary hounds with one batched pass: base + survivors through `default_replay_many` (and start the base rehearsal beside the angle calls, since it needs none of them). The analyst's merge still needs its own pass. | `training_plans.py:628, 674-680` | Measured: 8 specs through `drill_many` 18.9 s vs 8 single drills 95.9 s | **~65-70 s of 97** (rebuild to ~30 s: ~17 s for the batch of 7 + ~12 s for the merge). Caveat: memory on the 1 GB box with 7 rule sets in one pass was not tested. |
| B | Pre-warm the slate: start `default_slate(today, ...)` on a background thread when `diagnose` (or `assess`) begins. The page's staged diagnosis runs ~25 s before it calls propose (even with Skip, diagnose + assess are ~6 s), and the slate lives 60 s. | `training.py:837 read_step`, `ask_eval.py:84` | Measured: warm-slate propose 0.30 s vs 3.09 s | **~2.8 s of the 3.1 s** owner-visible "Preparing the proposal" wait. Same CPU, moved off the click. Needs the TTL to outlive the show (60 s is close). |
| C | Build the slate for the hound's sports only (key the cache on the sport set): `ask_eval.py:100` passes `user_spec.SPORTS`. | `ask_eval.py:100` | Measured: `build_slate` 2.78 s (all 17) vs 0.60 s (NHL, TENNIS, MLB); the all-sports slate also opens 5 archive segments | **~2.2 s of propose** (3.1 -> ~0.9 s); stacks with B (the pre-warm gets cheaper). |
| D | Pre-check the event id as text before `json.loads` in the closing-odds scan (`line.find('"event_id":"')`, set membership), as `_text_sport` already does for sport. | `boards.py:152` and `snapshots.py:717-730` | Measured loop: 2.80 s -> 0.41 s, same 6,952 rows kept. A regex alternation of 25 ids was **slower** (5.05 s): do not use one. | **~2.4 s of diagnose** (2.9 -> ~0.5 s) and it pulls the scan well under the 12 s budget on slower hardware. |

A single drill is also improvable (one multi-sport pass in `_window_rows` instead of one pass per sport: up to ~3x on its 12 s), but that is unmeasured and A makes it matter less.
B and C overlap; A is a different request (the async rebuild job) from B-D (the review card).

## What to check next (not done)

- Time `propose` on the production machine under a real background build (the gate wait) before saying the 3 s here is the owner's wait.
- Re-run with a hound whose bets carry real event ids from the current store.
