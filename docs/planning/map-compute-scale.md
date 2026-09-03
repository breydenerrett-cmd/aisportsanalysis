# Subsystem map: compute-scale

Read-only audit, 2026-09-03, branch `claude/sports-betting-analysis-review-g1o0co`.
Scope: what a "decision" costs today in CPU, what the current design's
throughput ceiling is, what data-layout changes would move it toward millions
of decisions/hour, and which computations are deterministic vs. model-bound.
All claims cite file:line or a command actually run in this session.

---

## 1. The one number that matters, and its actual provenance

`docs/EVOLAB_DESIGN.md:384` and `:474`: **"11,088 genomes sweep in 51 ms."**
This is the design doc's headline throughput claim and it is the number the
owner-facing "compute is never the bottleneck" argument rests on
(`EVOLAB_DESIGN.md:474`: *"There is no scenario where the compute is the
reason not to look."*).

I checked whether this number is instrumented anywhere and it is not:
- `grep -n "elapsed\|time.perf_counter\|wall_seconds\|duration" src/evolab/sweep.py src/evolab/replay.py src/evolab/registry.py` — **zero hits**. No wall-clock is measured or recorded by the sweep code itself.
- The Phase 2B artifact `data/research/evolab/sweep-0014914df78666b9-REAL.json` (1.66 MB, the actual REAL run that produced the published `BELOW_PLACEBO_CEILING` verdict) has no timing field anywhere in its schema (checked every key recursively for `time|second|duration|elapsed|wall|runtime|ms` — the only hit is an unrelated `lineup_posting.measured.posting_timestamp_available` boolean).
- `docs/EVOLAB_PHASE2A_BASELINE.md:265` records "44 seconds wall-clock" for the **Phase 2A** logistic-regression baseline run — a real, dated, artifact-adjacent number — but that is a different computation (an sklearn-style fit), not the bitset sweep.

**CLAIMED-BUT-ABSENT**: the "51 ms for 11,088 genomes" and "one world sweep:
seconds / 51 worlds: minutes / end-to-end: well under an hour"
(`EVOLAB_DESIGN.md:393-398`) are *design-time estimates asserted before Phase
2B ran*, restated in `docs/planning/map-evolab.md:172` with the same caveat
("I did not re-time a run in this audit"). Nobody has instrumented and
recorded the actual wall-clock of the actual 8,811-genome, 51-world Phase 2B
run that shipped. The estimate is plausible (bitset arithmetic on ~4,800-bit
integers is genuinely fast in CPython) but it is an estimate, not a
measurement, and the codebase does nothing to stop that number silently
degrading unnoticed. This is the single highest-value, lowest-cost capture
for this subsystem: add one `time.perf_counter()` bracket around
`sweep.py`'s driver and persist `wall_seconds` into every `SweepReport`
(`sweep.py:475-575` builds that JSON already — one more field).

## 2. What a "decision" costs today — the actual architecture

### 2a. The enumeration engine (bitsets) — the part that IS fast, and IS deterministic

`src/evolab/bitsets.py` (221 lines) is the genuinely well-engineered piece:
- Per-(feature, rung, side) predicates are precomputed **once per world** as
  Python arbitrary-precision integers (`bitsets.py:1-45` docstring,
  `build_signal_mask_table`, `bitsets.py:202-221`). With the registry's 6
  ladder features x 3 rungs x 2 sides that is 36 masks per world
  (`bitsets.py:36`), each ~4,800 bits — one CPython bigint each.
- A genome's selection collapses to 2-3 integer `&`/`|` ops
  (`bitsets.py:12-14`), and `sum_over_mask` walks only the **set** bits via
  `mask & -mask` isolation (`bitsets.py:142-156`), so cost scales with
  selections made (~500/genome per the docstring), not with universe size
  (~4,800 games) — a real, load-bearing optimization, not a claim: the code
  literally cannot iterate the full universe per genome, by construction.
- The docstring's own stated alternative — "evaluating ~5,000 genomes against
  ~4,800 games one decision at a time: 24 million Python-level decisions per
  world, times 51 worlds" (`bitsets.py:16-20`) — is the honest baseline this
  design avoids. That baseline is what "cost per decision" would mean without
  the bitset trick; the trick's entire value is not needing to pay it.
- 100% deterministic: no randomness, no model call, everything is CPython
  integer arithmetic and stdlib `itertools.combinations` (`combine_k_of_n`,
  `bitsets.py:121-139`, bounded to C(3,2)=3 terms by `MAX_SIGNALS = 3`,
  `registry.py:87`).

This part **is EXISTS**, verified by reading the actual arithmetic, not just
the docstring's claim about it.

### 2b. What is NOT bitset-fast: everything upstream of the sweep

The bitsets operate on precomputed differential vectors. Building those
vectors, and building the `WorldView`/`ReplayGame` objects the differentials
come from, is ordinary per-game Python object construction, once per game per
season, and it is where the real per-decision cost lives:

- `src/research/matrix.py:89-170` (`build()`) loops `for game in games` and
  calls `row_for_game()` (`matrix.py:193`) per game — a plain Python function
  building a dict from several nested feature lookups (handedness, lineup
  platoon share, starter velocity gap, pooled wOBA, etc., `matrix.py:236-353`).
  This is the function `docs/EVOLAB_DESIGN.md:25` times at **"2,430 + 2,429
  posted-lineup games, built in 7-11s/season"** — call it ~3-4.5 ms/game of
  single-threaded Python, and this figure (unlike §1's sweep number) is a
  measured, cited claim tied to a specific script, not a design estimate.
- `src/evolab/replay.py`'s `ReplayUniverse.get(game_pk)` (`replay.py:731-735`)
  is a **linear scan** over `self.games` (`for game in self.games: if
  game.game_pk == str(game_pk): return game`) despite a `by_id()` method
  existing right above it (`replay.py:728-729`) that builds a fresh dict on
  every call and is never used by `get()`. At today's ~4,800-game universe
  this is invisible (worst case ~4,800 comparisons, microseconds), but it is
  an O(n) lookup sitting unused next to an O(1) one, and `grep` confirms nothing
  in `src/evolab/*.py` or `scripts/*.py` currently calls `.get()` in a
  per-game loop — so it is a **latent** O(n^2) trap, not a live bottleneck,
  but exactly the kind of thing that silently becomes one the moment someone
  writes a loop that calls it per game (e.g. a future cross-universe join).
- Stores themselves are line-delimited JSON, parsed with `json.loads` per
  line, no index, no schema enforcement beyond what the reading code checks:
  `data/historical/pitcher_logs.jsonl` (42,960 lines), `transactions.jsonl`
  (27,053 lines), `odds_history/manifest.json` (9,003 lines) — measured by
  `wc -l` in this session. Every `build()` pass re-reads and re-parses the
  full JSONL from scratch; nothing caches a parsed, typed, indexed
  in-memory (or on-disk columnar) form between runs.

**Net picture**: the sweep itself (§2a) is not the cost center. The cost
center is the once-per-season feature-matrix build (§2b), which is ordinary
row-at-a-time Python over JSONL, and it is *currently* fast enough (7-11s) to
be a non-issue only because the universe is ~4,800 games. That number does
not stay small if the vision's full per-game reconstruction (starters,
bullpen, offense splits, park/weather, full market board across ~15+ market
types) is built the same way, at MLB's ~2,430 games/season x multiple sports
x the owner's stated goal of "millions of decisions per hour."

## 3. Container / memory footprint

Measured in this session (this is the compute-scale container, same class as
the app's production container per `docs/ORCHESTRATION_DAY_2026-09-02.md:227`
citing "0.6 GB of 16 GB in use"):

- `free -h`: **15 GiB total RAM, 4 CPUs** (`os.cpu_count()` = 4), 707 MiB used
  at time of audit, 0 swap.
- `du -sh data/`: **286 MB total** (`data/historical` 262 MB, `processed` 8.7
  MB, `archive` 7.5 MB, `research` 6.7 MB, `app` 516 KB). This matches
  `docs/MASTER_PLAN.md:846-851`'s cited "≈284MB total (`du -sh data/`,
  2026-09-02)" almost exactly (1 day earlier, 2 MB drift — consistent with
  ongoing forward capture).
- `docs/ORCHESTRATION_DAY_2026-09-02.md:225-229`: **"four container restarts
  in an hour with 0.6 GB of 16 GB in use, each dropping trigger messages,
  background jobs and untracked files. Not load; needs the platform or a
  different environment."** This is an explicit, dated, first-party
  admission that the container instability observed is **not caused by
  memory or CPU pressure** — 0.6/16 GB is nowhere near a limit — but by
  something platform-level (restart cadence unrelated to workload). Anyone
  reading "16 GB RAM, restarts" as evidence of a memory-driven scaling wall
  would be **wrong**: the restarts are an infrastructure reliability problem,
  not a compute-scale one, and conflating the two would misdirect engineering
  effort.
- Given 286 MB of data and 15 GB of RAM, **the entire historical corpus fits
  in memory roughly 50x over**. There is no memory-pressure case for a
  columnar mirror at current data volume; `docs/MASTER_PLAN.md:846-851`
  reaches the same conclusion explicitly and defers the DuckDB/Parquet mirror
  "past Phase 1... Revisit only if a future sweep's wall-clock time actually
  becomes the bottleneck" — and per §1 above, nobody has yet measured that
  wall-clock to know whether it has.

## 4. DuckDB mirror — deferred, and the deferral reasoning is visible and current

- `docs/MASTER_PLAN.md:226-227` (§7, "the 10x system"): scoped as
  "**Research mirror**: DuckDB/Parquet mirror of all stores + a decision-time
  index... Millions-row joins in seconds on one box."
- `docs/MASTER_PLAN.md:514`: "single node + scripts + SQLite (app) —
  sufficient through 10x with the DuckDB mirror" — i.e. the mirror was scoped
  as the unlock for the *next* order of magnitude, not needed at current
  scale.
- `docs/MASTER_PLAN.md:710`: listed in the "top 10 highest-leverage moves" as
  item 4, "unlocks scale."
- `docs/MASTER_PLAN.md:846-851` (§C.1 item 1, the exact-scope appendix) is
  the operative, most recent decision: **"DEFERRED past Phase 1... not
  justified yet: `data/` is ≈284MB total... and Phase 2B's 8,811-genome sweep
  ran directly against the JSONL stores with no performance complaint."**
- `docs/ORCHESTRATION_DAY_2026-09-02.md:156`: "The DuckDB mirror (nothing
  today needed it)" — same-day confirmation nothing has yet forced the issue.

This is a coherent, deliberately-revisited (not merely inherited) decision:
PARTIAL / correctly-deferred rather than MISSING-by-neglect. The gap is that
the trigger condition for revisiting it ("a future sweep's wall-clock time
actually becomes the bottleneck") cannot fire because nothing measures that
wall-clock (§1) — the deferral's own exit criterion is currently
unmeasurable.

## 5. Phase 2B sweep, sized precisely

From `docs/EVOLAB_PHASE2B_RESULTS.md:1-41` and the artifact
`sweep-0014914df78666b9-REAL.json` (`n_strategies_real`, `n_games_real`,
`placebo_world_ids` fields read directly):

| quantity | value | source |
|---|---|---|
| eligible strategies (genomes) searched | 8,811 | artifact `n_strategies_real` / `EVOLAB_PHASE2B_RESULTS.md:21` |
| games in the real world | 4,188 (2023: 2,089 / 2024: 2,099) | `EVOLAB_PHASE2B_RESULTS.md:22` |
| worlds run | 31 total for movement-ceiling generators (P2/P3/P6, 10 replicates each = 30) + the real world | `EVOLAB_PHASE2B_RESULTS.md:23`; design doc's general case is 51 (1 real + 50 placebo, `EVOLAB_DESIGN.md:394`) — this run used fewer placebo replicates per generator than the general design figure |
| CSCV splits | C(10,5) = 252 | `EVOLAB_PHASE2B_RESULTS.md:52` |
| artifact size on disk | 1,660,782 bytes (1.66 MB) | `ls -la` this session |
| wall-clock actually measured | **not recorded anywhere** | see §1 |
| games/season the matrix builds from | 2,430 (2023) / 2,429 (2024) | `EVOLAB_DESIGN.md:25`, `AUDIT_PROBABLE_PITCHER_PIT.md:84` |
| matrix build time | 7-11 s/season | `EVOLAB_DESIGN.md:25` |
| replay universe (matrix row AND usable odds) | 4,819 games | `EVOLAB_PHASE0_FEASIBILITY.md:353` (4,859 matrix rows narrows to 4,819 after odds-join and pre-first-pitch filtering) |

Note the 4,188 (Phase 2B real-world games) vs 4,819 (full replay universe)
discrepancy is real and undocumented in EVOLAB_PHASE2B_RESULTS.md itself —
I did not find, within this subsystem's docs, an explicit reconciliation of
why the movement-fitness sweep used 4,188 rather than the full 4,819-game
universe (plausibly a movement-fitness-specific filter, e.g. requiring both a
decision-time and close observation, which would drop more rows than the
matrix-row-and-odds join alone). Flagging as PARTIAL/unexplained rather than
asserting a cause I did not verify.

## 6. Deterministic vs. model-bound computation — a hard, explicit line exists

`docs/EVOLAB_DESIGN.md:399-400`: **"This runs as a script on the data plane.
No model reasoning is spent per simulated decision — that is a hard rule, not
an optimisation."** This is EXISTS, not aspirational: every module read in
this audit (`bitsets.py`, `registry.py`, `sweep.py`, `cscv.py`, `spa.py`,
`ceiling.py`, `placebo.py`) is pure stdlib Python with no LLM/API call
anywhere (`grep` for `anthropic\|openai\|client\.\|api_key` inside
`src/evolab/` — none found in the modules read). The vision's own build-role
table (`EVOLAB_DESIGN.md:407-421`, §13) assigns Opus/Sonnet to **building and
reviewing the code that runs the sweep**, never to running inside the sweep
loop itself — methodology and adversarial review are human-build-time model
uses, not per-decision runtime ones. This matches the owner vision's
"deterministic infrastructure evaluating millions of decisions" clause
directly: the infrastructure that exists today is architected to keep model
calls off the hot path entirely, which is the right shape for scaling to
millions of decisions/hour — the question is not "do we need to get models
out of the loop" (already true) but "does the deterministic loop itself scale
past ~10^4 genomes x ~10^3 games" (open, per §1's missing instrumentation).

Where a model call WOULD legitimately sit, per the owner vision (hypothesis
generation, methodology review, "agent-proposed genomes" vs.
grammar-enumerated ones) is explicitly named as an **unmeasured experiment**,
not yet built: `docs/MASTER_PLAN.md` (§20 area, "the hypothesis-proposer's
value is measured (do agent-proposed genomes outperform grammar-enumerated
ones per unit cost? — itself an experiment)"). MISSING today inside
`src/evolab/`: no LLM-proposer code exists in the package (confirmed by the
same grep above returning nothing).

## 7. What would take this toward millions of decisions/hour

Given the evidence above, the concrete throughput levers, in the order the
evidence suggests they'd pay off:

1. **Instrument the sweep's own wall-clock first** (§1). Nothing here can be
   sized or defended without turning "51 ms" from a design estimate into a
   measured, artifact-persisted number across the real Phase 2B-scale run.
   This is a same-day, near-zero-cost change (`sweep.py`'s `SweepReport`
   builder already exists at `sweep.py:475-575`).
2. **Cache the parsed feature matrix, not just the JSONL.** `matrix.py`'s 7-11
   s/season is Python object construction over re-parsed JSON; a
   precomputed, on-disk columnar frame (even a plain `pickle`/`.npy`-free
   stdlib `array`/`struct` layout, given "no numpy" is a stated environment
   constraint per `bitsets.py:8`) keyed by game_pk would turn that into a
   sub-second load, and is exactly the "precomputed per-game feature frames"
   the task brief names. This is the highest-leverage columnar-store move
   given the no-numpy constraint is real (verified: no `import numpy` found
   anywhere in `src/evolab/` or `src/research/matrix.py`).
3. **Cache market boards analogously** — `feed.py` (645 lines, not fully read
   in this audit) is the board-builder; the same re-parse-every-run pattern
   likely applies there (its F5 market gap is already documented in
   `docs/planning/map-evolab.md` §7 as schema-only/inert) and was out of this
   subsystem's specific brief to re-verify line-by-line, but the JSONL-per-run
   pattern observed in `matrix.py` and confirmed by the raw store sizes (§2b)
   makes it the most likely twin of the same cost.
4. **Fix the `ReplayUniverse.get()` linear scan to use the existing unused
   `by_id()` dict** (§2b) — cheap, currently harmless, but exactly the kind
   of thing that turns into O(n^2) the moment a cross-game join is added at
   10x the universe size (multi-sport, multi-season).
5. **The bitset engine itself (§2a) does not need replacing** to reach higher
   genome counts — it is already sub-linear in the right dimension (set bits,
   not universe size) and its ceiling is Python bigint arithmetic on
   ~4,800-1,000,000-bit integers depending on universe growth, which stays
   fast well past MLB-scale. The ceiling on "millions of decisions/hour" is
   not the bitset arithmetic; it is (a) how fast the per-world differential
   vectors can be assembled (items 2-3 above) and (b) how many *worlds*
   (placebo replicates) are run per cycle, which is an experiment-design
   choice (`EVOLAB_DESIGN.md:394`'s "51 worlds," this run's 31 — §5) rather
   than a hard compute wall.
6. **Container/CPU is not the constraint** (§3): 4 CPUs, 15 GB RAM, 286 MB of
   data. `scripts/test_parallel.py` (315 lines) already demonstrates
   the pattern for using all 4 cores via `ProcessPoolExecutor`-style sharding
   (it shards unittest modules, not sweep worlds, but the same LPT-balancing
   approach at `test_parallel.py:135-157` is directly reusable to
   parallelize placebo worlds across cores if a future sweep's wall-clock
   ever does become the bottleneck per §4's revisit trigger).

## 8. BOOST vs. REPLACE

- **`src/evolab/bitsets.py` — BOOST.** The core arithmetic is correct,
  documented, and already the right shape (sub-linear in the right
  dimension). Nothing here needs replacing; it needs a wall-clock harness
  around its callers (§1) so its performance claim stops being an
  unverified docstring.
- **`src/research/matrix.py`'s build path — BOOST, with a caching layer
  added, not rewritten.** The per-game row logic (feature derivation,
  point-in-time gap tracking) is the real analytical content and should not
  be thrown away; what is missing is a persisted, indexed intermediate
  form so the 7-11s/season cost is paid once per data change, not once per
  sweep invocation.
- **`src/evolab/replay.py`'s `ReplayUniverse.get()` — BOOST (one-line fix).**
  Route it through `by_id()` (cached once, not rebuilt per call) instead of
  a linear scan. Trivial, currently harmless, worth doing before any
  universe-scale-up makes it not-harmless.
- **The JSONL store format itself (`data/historical/*.jsonl`) — hold at
  BOOST for now, revisit at REPLACE only if §1's instrumentation shows the
  parse cost actually dominates a real run.** `docs/MASTER_PLAN.md:846-851`'s
  own deferral reasoning is sound at 286 MB; replacing the store format
  (DuckDB/Parquet) before the bottleneck is measured would be solving an
  unmeasured problem, which is the same discipline the placebo-ceiling
  machinery already enforces on genome selection (don't act on an unmeasured
  effect) and should be enforced on infrastructure spend too.
- **LLM-proposer / model-in-the-loop generation — nothing to BOOST or
  REPLACE; it does not exist yet inside `src/evolab/`** and is correctly
  scoped in `docs/MASTER_PLAN.md` as an unstarted, to-be-measured
  experiment, not a regression.

## 9. Data that becomes unrecoverable if not captured now (compute-scale angle)

- **The Phase 2B run's actual wall-clock and per-stage timing breakdown is
  gone.** The run already happened (2026-08-31, artifact timestamped) and
  produced the project's most important published result; without the
  timing instrumentation proposed in §1 having existed *at the time*, there
  is no way to retroactively recover how long that specific 8,811-genome,
  31-world run actually took, on what hardware profile, so the "51 ms"
  design estimate can never be checked against the run that matters most.
  Every future re-run can be instrumented going forward, but this one
  specific data point is lost permanently.
- **Container restart telemetry** (`docs/ORCHESTRATION_DAY_2026-09-02.md:225-229`'s
  "four restarts in an hour with 0.6/16 GB in use") is a dated, first-party
  observation that the restarts are platform-driven, not load-driven. If a
  future compute-scale push (more worlds, larger universes, parallelized
  sweeps per §7 item 6) starts pushing memory or CPU into a regime where
  restarts *do* correlate with load, having this "not load" baseline on
  record is exactly what would let that shift be detected rather than
  re-litigated from scratch — worth preserving as a named baseline
  measurement, not just a one-off orchestration log line.
