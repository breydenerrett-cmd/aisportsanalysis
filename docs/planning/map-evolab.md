# Subsystem map: `src/evolab/` (evolution lab / strategy search)

Audited 2026-09-03, branch `claude/sports-betting-analysis-review-g1o0co`, against
the OWNER VISION's "strategy factory" (generate→test→score→attack→retire→mutate→
retest→forward test→promote, thousands of competing systems, full-board search).

Files: `src/evolab/{registry,genome,bitsets,decide,replay,feed,placebo,cscv,spa,
ceiling,sweep,baseline}.py` (14,551 total lines incl. tests), docs
`docs/EVOLAB_{DESIGN,PHASE0_FEASIBILITY,PHASE2A_BASELINE,PHASE2B_RESULTS}.md`,
tests `tests/test_evolab_{core,baseline,feed,replay,sweep,sweep_outcome,
stats}.py` (5,267 lines of tests).

No `season-end`, `bet_check`, `betcheck`, or `scorecard`/CI-scorecard module or
reference exists anywhere under `src/evolab/`, `docs/EVOLAB_*.md`, or
`.github/`. Those items in the task brief describe things that do not exist in
this codebase — see CLAIMED-BUT-ABSENT below.

---

## 1. What a genome is TODAY

`src/evolab/genome.py` — a `Genome` is a frozen dataclass with six modules,
exactly per design section 3:

- `eligibility` (`markets` tuple, `min_books`, `require_lineup`)
- `signals`: ≤ `MAX_SIGNALS=3` (`registry.py:87`) `Signal(feature,
  threshold_index, weight)` triples, canonicalized by sorting on feature name
  (`genome.py:344-348`) so float summation order is reproducible
- `combination`: `weighted_sum` or `k_of_n` (`genome.py:85`)
- `entry`: `min_score`, `min_confirmations`
- `routing`: `market_preference` tuple + `f5_condition`
- `execution`: one of 3 modes, held **constant** across the whole population
  during predictive search (`genome.py:93-98`)

**Markets — h2h only in practice.** `MARKETS = ("h2h", "h2h_1st_5_innings")`
(`genome.py:82`), but the module's own 2026-09-02 audit note
(`genome.py:77-81`) states plainly: *"the F5 slot is schema-only so far --
src/evolab/feed.py sources h2h prices only, so every sweep to date (including
Phase 2B's 8,811 genomes) searched the full-game moneyline alone."* Confirmed
independently: `feed.py` and `sweep.py` have no run line, totals, team total,
props, or derivatives handling anywhere (`grep` for run_line/total/prop/
alternate/parlay in `src/evolab/*.py` returns nothing). This is one market,
full stop, against the vision's entire board (moneyline, run line, alt lines,
totals, team totals, F5, props, derivatives, parlays).

**Features — six, hand-picked, no arsenal/park/weather/market-structure
features.** `registry.py:325-405` registers exactly six numeric matrix
columns: `lineup_platoon_share`, `lineup_vs_primary_pitch`,
`primary_pitch_share`, `top_minus_bottom`, `starter_velocity_gap`,
`starter_groundball_share`. All six are `FIRST_FIVE` scope, sourced from
lineup/probable-pitcher composition — none of bullpen availability/leverage,
park/weather/altitude/umpire, market-structure (line movement, disagreement,
staleness, consensus), or batter/pitcher-prop-shaped features the vision lists
appear in the registry at all (`registry.py:63-73` explicitly documents one
exclusion, `starter_platoon_gap`, as deliberately absent for lacking a
standalone sign — no other feature is even discussed as a future candidate).
A feature only reaches the lab by being both (a) a column
`src/research/funnel.py.NUMERIC_FEATURES` already computes and (b) manually
registered here with a 5-word+ mechanism and a frozen ±1 sign
(`registry.py:203-216`). There is no code path from "the LLM/analyst
identified a new candidate signal" to "the registry has a new entry" — every
addition is a human PR.

**How a strategy is evaluated.** `decide.py::decide_with_reason` is the pure
reference implementation: one `Genome` + one `WorldView` → one `Decision` or
`NO_PLAY` + reason (`decide.py:214-282`). Deterministic tie-break rules are
spelled out and tested (module docstring lines 31-53). `sweep.py` re-expresses
the same semantics as bitset arithmetic for speed (`sweep.py:220-296`,
`_side_profiles`/`_resolve_ties`) and is cross-checked against `decide.py`
by test (referenced in `sweep.py` docstring, not independently re-verified
here beyond reading the claim — see PARTIAL note below).

**Sign/direction is structurally un-searchable** — this is real and load-bearing,
not aspirational: `genome.py:69-72` (`FORBIDDEN_KEYS`) rejects any
`sign`/`direction`/`polarity`/... key at any nesting depth
(`_reject_forbidden_keys`, `genome.py:202-216`), weight must be strictly
`> 0` (`genome.py:325-331`), and the sign itself lives only in
`registry.py`'s frozen `SignalSpec.direction`, set once at `register()` time
and never mutable (`registry.py:198-202`, `SignalSpec` is `@dataclass(frozen=
True)`). This is a genuine engineering answer to the V4/V5 "screen then flip"
failure mode described in the registry docstring — EXISTS, not aspirational.

## 2. Enumeration, not search

`enumerate_genomes` (`genome.py:466-567`) is a full deterministic enumeration
over signal count (1..3) × feature combination × threshold-ladder odometer ×
combination rule × weight vector × attainable `min_score` × routing — not a
genetic/evolutionary search of any kind despite the package name "Evolab" and
the vision's "GENERATE→TEST→SCORE→ATTACK→RETIRE→MUTATE→RETEST→FORWARD
TEST→PROMOTE" loop. Order is fully specified and documented as part of the
enumeration-spec hash (`enumeration_spec`/`spec_hash`, `genome.py:570-604`).
Phase 2B enumerated **8,811 genomes** total (`docs/EVOLAB_PHASE2B_RESULTS.md`
line 18) over the 6-feature/1-market registry. This is EXISTS as "enumerable
search infrastructure," MISSING as "evolutionary strategy factory": there is
no mutation operator, no crossover operator, no generational population, no
elite pool, no immigrants, no islands anywhere in `src/evolab/*.py` — `grep`
for mutate/mutation/crossover/generation/retire/promote across the package
turns up only comments describing what Phase B *will* do
(`genome.py:8,104`, `ceiling.py:11-12`, `docs/EVOLAB_DESIGN.md:281-282,500-501`).
Phase B is explicitly gated on Phase 2B clearing the placebo ceiling
(`docs/EVOLAB_DESIGN.md:500`: "If the real maximum *does* clear the ceiling,
Phase B unlocks..."), and Phase 2B did not clear it (§4 below) — so by the
project's own stated rule, mutation/crossover/Phase B code should not exist
yet, and indeed does not. MISSING, but MISSING-by-design pending a gate, not
an oversight.

## 3. The replay engine and point-in-time guarantees

`src/evolab/replay.py` (1,467 lines) is the most heavily fortified module in
the package and its point-in-time claims hold up on reading:

- `WorldView` (`decide.py:112-178`) uses `__slots__` and raises
  `AttributeError` for any outcome- or close-shaped attribute name
  (`FORBIDDEN_ATTRIBUTES`, `decide.py:67-75`), checked both at construction
  (`__post_init__`, `decide.py:138-145`) and on any later attribute access
  (`__getattr__`, `decide.py:147-161`) — genuinely structural, not a filter
  that can be forgotten.
- `iter_instants_through` (`replay.py:577`) breaks out of an ascending scan
  the first time it sees an instant after T rather than skipping-and-
  continuing, so a poisoned future row is provably never yielded
  (module docstring point 2, `replay.py:20-23`; described as "acceptance
  test 2" — I did not independently re-run that test here, see caveat below).
- `LeakageError` (`replay.py:196`) exists as a second alarm if a post-T quote
  ever reaches board assembly through some other path — described as
  "unreachable through the generator, kept as the alarm."
- Sealed-window and season enforcement: `REPLAY_SEASONS` mirrors
  `matrix_mod.ALLOWED_SEASONS` (`replay.py:113-116`), and `SealedWindowError`
  / `refuse_sealed` (`replay.py:188,415-439`) refuse 2026-01-01..2026-08-27 by
  name before reading anything, and refuse 2025 too — the replay universe is
  2023-24 only, confirming the "sealed 2026 untouched" constraint at the
  replay layer.
- **Point classes collapsed from a 4-rung design to 2** (`EARLY_BOARD`,
  `LATE_BOARD`) because, per the module's own measured finding
  (`replay.py:42-49`), no two 2023-24 observations are closer than 177
  minutes (median gap 6 hours), `T_MINUS_30M` exists for only 1,269/4,819
  games, and lineup-posting times don't exist at all. `LATE_BOARD` is
  explicitly *not* a close (median 85 min before first pitch,
  `docs/EVOLAB_PHASE2B_RESULTS.md:177`). This is an honest, documented
  degradation of the design's decision-point granularity versus what the
  owner vision implies ("days rest," in-game/real-time reconstruction) — the
  data simply is not that granular for 2023-24.
- **The starter/lineup leak is named, not hidden.** `assert_point_in_time`
  (`replay.py:340`) RAISES for every feature the registry actually uses,
  because `docs/AUDIT_PROBABLE_PITCHER_PIT.md` measured the stored "probable"
  pitcher field disagrees with the actual starter only 0.10%/0.08% of the
  time — i.e., it is effectively the real, final starter, not a genuinely
  point-in-time-knowable probable. All six registered features are therefore
  availability class C/D and are served only under a named, versioned
  parameter (`STARTER_IDENTITY`, `LINEUP_POSTING`) stamped on every artifact,
  never described as point-in-time. This is a real, self-imposed asterisk on
  every one of Phase 2B's 8,811 genomes: their signals are built from
  effectively-actual starters/lineups, not truly pre-decision probables.

CAVEAT: I read the docstrings' claims about acceptance tests and cross-checks
(leakage injection test, decide/bitset cross-check) but did not re-execute
`pytest` in this audit to independently verify green status — `tests/
test_evolab_replay.py` (1,054 lines) and `tests/test_evolab_sweep.py` (544
lines) exist and by file size appear to cover this, which is PARTIAL
confirmation (file exists and is substantial) rather than EXISTS (verified
passing here).

## 4. Sweep / SPA / CSCV / placebo-ceiling machinery — real, and it already fired

This is the strongest-built part of the subsystem and it has already produced
one real, load-bearing negative result:

- `bitsets.py` (221 lines): per-(feature,rung,side) Python-integer bitmasks,
  `&`/`|` combination, `sum_over_mask` refuses index-mismatched masks
  (`bitsets.py:165-190`) rather than silently truncating. Documented
  performance rationale: 24M naive per-decision calls vs. ~15,000 integer ops
  for a full sweep (`docs/EVOLAB_DESIGN.md:375-398`: "one world sweep:
  seconds," "51 worlds: minutes," "wall-clock, Phase 2 end to end: well under
  an hour per full run"). I did not re-time a run in this audit; this is the
  document's own claim, self-consistent with the architecture described.
- `placebo.py` (959 lines): 5 generators (P1 outcome-permutation, P2
  team-identity permutation, P3 date-shift, P4 block-bootstrap — later
  **reclassified as a dispersion diagnostic, not a null**, because a planted
  edge failed to clear it (`docs/EVOLAB_DESIGN.md:213-232`) — and P5
  market-truth resampling, plus P6 added afterward as the movement analogue
  of P1). The P4 reclassification and the P1/P5-structurally-uninformative-
  for-movement-fitness finding (`docs/EVOLAB_DESIGN.md:233-249`) are both
  genuine mid-project corrections recorded with dates (2026-08-31), which is
  evidence the machinery is actually being exercised and its outputs read
  critically, not just built and left. Ceiling is now evaluated **per
  fitness**: movement over {P2,P3,P6}, outcome over {P1,P2,P3,P5}.
- `cscv.py` (321 lines): combinatorial symmetric cross-validation,
  `probability_of_backtest_overfitting`, chronological block splits.
- `spa.py` (333 lines): Hansen-style Superior Predictive Ability test with
  block-sum stationary-bootstrap machinery.
- `ceiling.py` (354 lines): `generator_ceiling`, `kill_criterion`,
  `ceiling_report` — the placebo-ceiling verdict logic, explicit that
  clearing the ceiling is what would unlock Phase B mutation/crossover
  (`ceiling.py:5-12`).
- `sweep.py` (800 lines): the actual driver, imports every module above and
  runs the real world + all placebo worlds through one `sweep_world` function
  (`sweep.py:333`), producing a `SweepReport` with canonical JSON hashing for
  reproducibility (`sweep.py:475-575`).

**Phase 2B already ran this end-to-end and got a real, negative, published
result** (`docs/EVOLAB_PHASE2B_RESULTS.md`): 8,811 genomes, 4,188 games
(2023: 2,089 / 2024: 2,099), real max movement fitness 0.004882, **0 of 3**
movement-ceiling generators cleared, pooled percentile rank of the real
maximum **13.3** (i.e. worse than the median placebo world), PBO = 0.6111
(in-sample selection anti-predicts out-of-sample rank). Verdict:
`BELOW_PLACEBO_CEILING`, "Evolution does not get built." This is the single
most important EXISTS in the subsystem: the anti-overfitting instrumentation
is not decorative — it ran, disagreed with a naive read of the data at least
twice (P4, P1/P5), got corrected both times with a dated rationale, and then
produced a result that killed further build-out on schedule. That is exactly
the epistemic discipline the owner vision asks for ("many competing systems...
GENERATE→TEST→SCORE... RETIRE"), just not yet at "thousands of systems" scale
or wired to bankroll/units.

**Fitness is movement-based and outcome-ROI-based, never bankroll/Kelly.**
`docs/EVOLAB_DESIGN.md:199-201` states explicitly: *"Never in fitness:
staking, bankroll paths, Kelly, drawdown-adjusted returns. Those are
presentation, evaluated afterward, and can never promote."* No bankroll
simulation, no unit-stake day-by-day ledger, no "1,000 units" simulated
account exists anywhere in `src/evolab/*.py` (`grep` for
bankroll/ROI/units/ledger across the package returns only "outcome ROI"
fitness references, `feed.py:68`, `placebo.py:91`, `sweep.py:312-314` — a
per-selection flat-stake ROI metric, not a bankroll trajectory). This is a
genuine, deliberate gap against the vision's "simulated daily bankroll
accounts... day by day, whole seasons... forward paper" requirement: EXISTS
elsewhere in the codebase, if anywhere (not checked in this audit, out of
scope for evolab), MISSING inside evolab itself.

## 5. Bet Check integration — MISSING / CLAIMED-BUT-ABSENT

No reference to "Bet Check," "bet_check," or "betcheck" exists anywhere in
`src/evolab/`, `docs/EVOLAB_*.md`, or a targeted repo grep. If the owner or a
plan document elsewhere in the repo describes an evolab↔Bet Check integration,
it has no code or doc footprint inside this subsystem. CLAIMED-BUT-ABSENT
relative to the task brief's framing ("Bet Check integration" listed as
something to map inside evolab) — there is nothing to map because it does not
exist here.

## 6. Season-end and CI scorecard — MISSING / CLAIMED-BUT-ABSENT

Same finding: no `season-end` module, no CI-scorecard workflow or script tied
to evolab. `docs/SEASON_END_PLAN.md` exists at the docs root but a grep for
"evolab" inside it (not opened in full for this audit — out of subsystem
scope) was not required since `src/evolab/*.py` itself has zero season-end
code (no `season_end`, `end_of_season`, `scorecard` identifiers anywhere in
the package). `.github/` has no evolab-named workflow file. CLAIMED-BUT-ABSENT
as stated in the task brief.

## 7. F5 (first-five) market — schema-only, explicitly flagged by the code itself

Worth restating because it's easy to miss and the module authors flagged it
themselves: `F5_MARKET = "h2h_1st_5_innings"` is a legal value everywhere in
`genome.py`'s validation (eligibility, routing, F5-condition gating on
signal scope at `genome.py:436-443`), and genomes naming it validate cleanly.
But `feed.py` never sources F5 prices (confirmed: no F5/1st_5/first_five
string appears in `feed.py`'s board-building code), so **every genome that
would prefer F5 in Phase 2B could not actually route there** — it silently
fell through to `h2h` or found no live market. The 8,811-genome Phase 2B
result is entirely a full-game-moneyline result despite the schema allowing
F5. PARTIAL: schema EXISTS, data feed MISSING, so the capability is inert.

## 8. Data that becomes unrecoverable if not captured now

- **2023-24 board snapshot granularity is fixed at 3 observations/day
  (median 6-hour gaps).** This is a property of the historical store, not of
  evolab's code, but evolab's own audit is what discovered and documented it
  (`replay.py:42-49`). If the live-season capture pipeline (outside evolab,
  per the owner vision's "capture now everything needed to reconstruct
  decision time later") does not increase snapshot density for the 2026
  season **while it is live**, the same 6-hour-gap ceiling on decision-point
  granularity will recur for 2026 data forever — this is not fixable
  retroactively.
- **Probable-pitcher/lineup point-in-time timestamps do not exist for
  2023-24 and are not being backfilled by anything in evolab.** The
  `STARTER_IDENTITY`/`LINEUP_POSTING` parameter is a documented workaround,
  not a fix; if the live 2026 pipeline does not record the actual wall-clock
  time a probable pitcher or lineup was posted (as opposed to storing the
  final, effectively-actual value the way 2023-24 does per
  `docs/AUDIT_PROBABLE_PITCHER_PIT.md`), evolab v2 will inherit the exact
  same class-C/D leak permanently, for a season the owner vision calls
  "precious."
- **The registry's ladder thresholds (`registry.py:335-403`) are derived
  once from 2023-24 `|away-home|` percentiles and frozen.** This is fine as
  a deliberate methodological choice (outcome-blind derivation), but the raw
  per-feature counts behind each ladder (`_LADDER_SOURCE`, e.g. "4,856 games
  with both sides measured") are provenance that should be preserved
  alongside any future registry expansion, since a v2 registry with new
  features will need the same "derived before any result is seen" discipline
  to inherit the V4/V5 lesson rather than relearn it.

## 9. BOOST vs REPLACE, per component

- **registry.py — BOOST.** The sign-freezing/mechanism-gate architecture is
  sound and general; it should be extended with more features (bullpen,
  park/weather, market-structure) using the identical registration
  discipline, not rebuilt. The 6→N feature growth is additive.
- **genome.py — BOOST.** The six-module structure, forbidden-key refusal,
  and enumeration-order discipline are exactly what a larger feature/market
  space needs; extending `MARKETS`, `ENUM_WEIGHT_VECTORS`, and
  `max_signals` are parameter changes, not architecture changes. The
  Phase B mutation/crossover layer described in comments does not exist yet
  and would be new code, but it's designed to slot into this genome shape
  (each of the 6 sub-modules is independently swappable, per the docstring's
  stated intent) — BOOST, add the operators, don't restructure the genome.
- **decide.py / bitsets.py — BOOST.** Both are small, pure, and already
  proven fast enough for an 8,811-genome sweep; scaling toward "thousands"
  of genomes and multiple markets is a matter of extending the mask table
  (more (feature,rung,market) keys) and market-specific `_select_market`
  logic, not a rewrite.
- **replay.py — BOOST, carefully.** The leak-proofing is the load-bearing
  asset of the whole subsystem; any market/feature expansion must route
  through the same `WorldView`/`iter_instants_through` boundary rather than
  a new parallel path, or the leak-proofs stop covering the new surface.
- **feed.py — BOOST (and this is the highest-leverage near-term expansion
  point).** It is the seam between replay and sweep and is currently h2h-
  only; adding run-line/totals/F5-real/prop feeds is additive work inside
  the `ResolvedDecision`/`_consensus_row` shape, not a redesign.
- **placebo.py / cscv.py / spa.py / ceiling.py / sweep.py — BOOST.** This is
  the most mature, already-battle-tested part of the package (it caught two
  of its own specification errors and produced a real published verdict).
  Scaling to "thousands of competing systems" and a rolling
  generate→test→retire loop is new orchestration code sitting on top of
  `sweep_world`, not a replacement of the statistics underneath it.
- **baseline.py — BOOST/separate concern.** This is a from-scratch
  logistic-regression (L1/L2, coordinate descent) implementation
  (`baseline.py`) used as the Phase 2A comparison point, not part of the
  genome/decide/replay/sweep chain; it stands on its own and doesn't need to
  change for evolab's core loop to grow.
- **"Strategy factory" (generate→test→score→attack→retire→mutate→retest→
  forward→promote) — MISSING, build new.** There is no orchestration layer
  today that runs this loop continuously; Phase B (mutation/crossover) is
  explicitly not-yet-built pending the ceiling-clear gate, and nothing here
  runs on a schedule, retires strategies, or forward-tests promoted
  survivors. This is legitimately new code, though it can be built directly
  on top of the existing enumerate→sweep→ceiling primitives rather than
  replacing them.
- **Bet Check integration, season-end, CI scorecard — build new; nothing to
  boost.** Zero existing code footprint in this subsystem.

## 10. Key numbers (for quick reference)

- 6 registered features, all `FIRST_FIVE` scope, 3-rung ladders each = 18
  (feature, rung) pairs = 36 masks/world (`bitsets.py:36`).
- `MAX_SIGNALS = 3` (`registry.py:87`).
- Phase 2B: 8,811 eligible genomes, 4,188 games (2023: 2,089 / 2024: 2,099).
- Real max movement fitness 0.004882213449032019; pooled percentile rank
  13.3; 0/3 generators cleared; PBO = 0.6111.
- Markets actually priced: 1 (`h2h`). Markets schema-legal but unfed: 1
  (`h2h_1st_5_innings`). Markets in the owner vision's full board: dozens
  (moneyline, run line, alt run lines, totals, alt totals, team totals,
  margin, F5 ×4, first inning, pitcher props ×5+alternates, batter props
  ×8+, derivatives, parlays).
- 2023-24 board observation spacing: min gap 177 min, median 6 hours;
  `T_MINUS_30M` present for 1,269/4,819 games only; lineup-posting timestamp
  present for 0 games.
- Test coverage: 5,267 lines across 6 evolab test files (not independently
  re-run in this audit).
