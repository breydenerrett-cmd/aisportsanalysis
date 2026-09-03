# Map: research-machinery subsystem

Scope: `src/research/**`, `docs/VALIDATION_GATE.md`, `docs/RESEARCH_CATALOGUE.md`,
`docs/RESEARCH_V*.md`, `docs/ALPHA_REGISTRY_DESIGN.md`, `docs/MASTER_PLAN.md`
promotion sections. Read 2026-09-03, branch
`claude/sports-betting-analysis-review-g1o0co`. Every claim below is cited to
file:line or a command actually run; nothing is taken from docstring prose
alone unless labeled as a doc claim.

## What exists, end to end

`src/research/` is a single-market (MLB h2h moneyline), single-mechanism
research pipeline: turn a named feature + threshold into a graded betting
record, screen it, replicate it, run it through an automated falsification
battery, and correct for the whole family with BH-FDR. It is real,
exercised, and its one serious self-inflicted wound (the battery originally
passing the known false positive M3) was found and fixed with a documented,
versioned, adversarially-adjudicated process. It is not, today, a machine
that can search the betting board (props, alternates, F5, parlays) or score
a decision policy that also carries a price/book/timing dimension — it
scores single point-in-time features against the h2h close.

### 1. The spec → funnel → verdict pipeline (`src/research/funnel.py`, 716 lines)

- A "spec" is `{name, market, feature, side_rule, threshold, min_sample,
  effect_floor, mechanism, direction}`, hard-validated in `validate_spec`
  (`funnel.py:148-217`). `market` is constrained to `MARKETS = ("h2h",)`
  (`funnel.py:111`) — **the funnel can only ever register an h2h moneyline
  hypothesis**, never a run line, total, F5, or prop.
- `feature` must be one of `NUMERIC_FEATURES` (`funnel.py:85-93`, 7 columns:
  `lineup_platoon_share`, `starter_platoon_gap`, `lineup_vs_primary_pitch`,
  `primary_pitch_share`, `top_minus_bottom`, `starter_velocity_gap`,
  `starter_groundball_share`) or a product of two of them joined by `*`
  (an "interaction", `funnel.py:107,171-182`). These are lineup/starter
  matchup features only — no bullpen, no park/weather, no market-structure
  feature (those live in the separate V1/V2/V3 modules below, outside the
  funnel's spec language).
- `register_family()` (`funnel.py:231-270`) freezes a spec list to a JSON
  file before any result exists, and refuses silently changing it — it
  either matches byte-for-byte or raises naming the diff. `run()`
  (`funnel.py:437-520`) enforces at run time that the specs handed to it
  equal the frozen family (`funnel.py:466-479`) — pre-registration is
  structurally enforced, not just a ceremony.
- Per spec, `_run_spec` (`funnel.py:523-640`) runs four gated levels:
  0. feasibility via `coverage.expected_n` (blocks before any join runs);
  1. a 2023 screen (must clear `0.4 * min_sample` selections and a positive
     effect, `funnel.py:573-584`);
  2. a 2024 replication (must clear half the effect floor in direction,
     `funnel.py:594-601`, and a sign flip is death by construction);
  3. the falsification battery on the pooled sample, with a wider
     sub-threshold "dose" sample built by `_selections_for(..., fraction=0.5)`
     specifically so the battery's dose-response check has a below-threshold
     band to test against (`funnel.py:133-137, 608-620`).
  `_apply_fdr` (`funnel.py:643-675`) then runs Benjamini-Hochberg over the
  FULL registered family (every spec, including ones dead at level 0, enter
  at p=1.0 — `funnel.py:651-652`), so the multiple-comparison correction
  cannot be gamed by only counting survivors.
- Selections are priced through `src.model.selections` (imported, not
  reimplemented — `funnel.py:51-59`), graded against the CLOSE deliberately
  (median 84 min out) rather than an earlier price, to avoid crediting a
  lineup-built selection with information the price hadn't seen
  (`funnel.py:352-361`).
- **This module cannot express a decision policy.** A spec is "feature X
  crosses threshold T, back the advantaged side" — it has no book selection,
  no price-improvement logic, no bet sizing, no multi-market comparison. It
  answers "is this feature mispriced", not "which of the N ways to express
  this edge is best," which is the owner's explicit ask ("search the entire
  board ... ask which market best expresses the informational advantage").

### 2. The falsification battery (`src/research/battery.py`, 524 lines)

- Operates on graded rows: `{date, won, implied}` plus optional `season`,
  `side`, `team`, `book`, `price`, dose. `_measure` computes
  `mean(won - implied)` with `discovery.clustered_two_sided_p`
  (`battery.py:163-171`) — always date-clustered.
- Five FATAL pre-registered rules (`battery.py:135-136, 34-78`):
  `season_split`, `team_concentration`, `book_concentration`,
  `extreme_removal`, `dose_response` — each documented with its exact
  trigger condition and the reasoning. Four more checks (`baseline`,
  `home_away`, `favorite_underdog`, `price_bands`, `threshold_sensitivity`)
  are report-only.
- `RULES_VERSION = "2.0.0"` and `rules_fingerprint()`
  (`battery.py:452-465`) hash the fatal-rule source + constants into every
  verdict, so a verdict can never be silently compared across rule changes.
- `survives=True` is explicitly documented as "not falsified, never
  confirmed" (`battery.py:83-88`), and a battery that never ran (sample
  under `MIN_N=30`) reports `ran=False` alongside `survives=True` — the
  funnel checks `ran` and marks such a candidate `"underpowered"`, never
  `"candidate"` (`funnel.py:626-634`).
- **This is a feature-vs-outcome battery, not a strategy/backtest engine.**
  It never touches price *shopping* (best book at decision time vs. the
  book actually used), never simulates a bankroll, never grades a
  time-varying decision policy — it grades one fixed selection rule's
  fixed historical selections.

### 3. The validation gate (`docs/VALIDATION_GATE.md`, `battery.py`, six test files)

Confirmed exercised, not just narrated:
- `tests/test_validation_planted.py` (346 lines), `test_validation_pit.py`
  (177), `test_validation_equivalence.py` (250),
  `test_validation_immutability.py` (260), `test_validation_m3.py` (127),
  `test_battery_generality.py` (357) — all present, substantial, matching
  the seven checks the doc claims (`docs/VALIDATION_GATE.md:16-24`).
- The one FAILED-then-fixed check (check 4, M3) is documented with the
  exact rule gaps found (dose rule's judgeable-upper-tail rescue; the
  concentration rule's effect-only fatal leg) and the two general
  amendments made, plus a "generality matrix" test and a 15-comparison
  old-vs-new shadow run recorded in the doc (`docs/VALIDATION_GATE.md:26-119`).
  This is a genuinely rare thing to find in a research codebase: a
  documented case of a testing tool passing a known false positive, caught,
  and fixed with a general (non-M3-specific) rule, source-checked for the
  absence of an M3 identifier (`docs/VALIDATION_GATE.md:79-80`).
- Adjudication is dated and named as independent (`docs/VALIDATION_GATE.md:129`)
  with two disclosed, non-blocking concerns rather than a clean bill of health
  — this is evidence discipline, not a docstring claim.

### 4. Matrix (`src/research/matrix.py`, 465 lines)

- One structured JSONL row per lineup-carrying game, `ALLOWED_SEASONS =
  (2023, 2024)` enforced structurally in both `build()` and `read()`
  (`matrix.py:78, 103-105, 177-179`) — 2025/26 cannot be reached through
  this module by any argument.
- Monthly-cutoff snapshots (`_cutoff_for`, `matrix.py:383-390`) so a game
  only ever reads a snapshot strictly behind its own month; opening-week
  games get honest Nones rather than the next snapshot's leak
  (`matrix.py:26-34`).
- Every feature is `None` over guess with a `gaps` list explaining why
  (`matrix.py:45-50, 217-297`); this is verified structurally sound by
  `test_validation_pit.py`'s byte-identical injection test
  (`docs/VALIDATION_GATE.md:22`).
- Only 7 numeric features + 2 non-numeric (`primary_pitch`,
  `lineup_vs_starter_history`) are computed — no bullpen, no park/weather,
  no market/price feature lives in the matrix. It is purely a lineup/starter
  matchup cache, not the "reconstruct everything legitimately knowable"
  object the vision describes (that would need bullpen availability/
  leverage, park/weather, market state joined in — none of which the
  matrix carries).

### 5. Coverage / scoreboard (`coverage.py` 348 lines, `scoreboard.py` 97 lines)

- `coverage.expected_n` (`coverage.py:56-81`) turns feature-coverage-pct x
  price-match-pct x fire-rate into a rough usable-n forecast so a hypothesis
  can die before code is written — used by the funnel's level 0
  (`funnel.py:548-549`).
- `scoreboard.record`/`read`/`format_latest` (`scoreboard.py:42-97`) append
  one JSON line per run: hypotheses screened/killed/replicated, survivors,
  credits spent. Never invents `started`/`finished` timestamps
  (`scoreboard.py:12-19`) — caller-supplied only. This is descriptive
  run-bookkeeping, not the "daily bankroll accounts" or "end-of-day
  self-review" object the vision describes; there is no bankroll
  simulation, no CLV field, no rating field anywhere in this module.

### 6. Alpha registry (`src/research/alpha_registry.py`, 471 lines) and design doc

- Append-only JSONL ledger of every registered hypothesis/sweep/audit
  across V1-V5 + Evolab Phase 2B + the Elo benchmark, with a separate
  `verdict` row shape and a narrow, single-use `"withdrawn"` escape hatch
  (`alpha_registry.py:296-372`) for a verdict that should never have been
  recorded (not a numeric correction, which must be a new id instead,
  `alpha_registry.py:59-65`).
- `AppendOnlyError` is enforced in code, not just policy
  (`alpha_registry.py:191, 312-320, 355-369`) — verified by running the
  actual data file:
  ```
  total rows 81: {hypothesis: 40, verdict: 39, sweep: 1, audit: 1}
  by family: V1=21, V4=6, V2=5, V3=5, V5=3, EVOLAB_PHASE2B=1, ELO_BENCHMARK=1
  ```
  — matches `docs/RESEARCH_CATALOGUE.md`'s stated 40-hypothesis /
  8,811-candidate-sweep / 1-audit total exactly
  (`docs/RESEARCH_CATALOGUE.md:344-348`).
- `semantic_hash_v0` (`alpha_registry.py:242-259`) is an explicit floor, not
  a ceiling, on cross-family duplicate detection: exact-atom-set match only,
  no correlation/similarity detection between differently-shaped hypotheses
  — the module docstring says this outright (`alpha_registry.py:106-108`)
  and MASTER_PLAN's own self-critique flags the same gap for genome-scale
  search ("thousands of genomes on shared features are NOT independent...
  the registry must track genome similarity", grep hit in
  `docs/MASTER_PLAN.md` Appendix B) — **this is CLAIMED-BUT-ABSENT at the
  scale the vision needs**: nothing here can track correlated survivors
  across a "potentially thousands" strategy-factory population; it only
  catches literal atom-set duplicates.
- `total_searched()` (`alpha_registry.py:393-449`) is the one query surface
  a new family's pre-registration doc is meant to cite. It is read-only
  accounting; it has no notion of a decision policy's price/book/timing
  dimension either.

### 7. Timing/microstructure family (V3): `eventstudy.py` (256),
`leadlag.py` (160), `timingtest.py` (968), `timingreport.py` (399),
`pricepath.py` (300), `m3_dispersion.py` (181), `m2_staleness.py` (184),
`m1_overreaction.py` (206), `m4_bullpen_gap.py` (232), `m5_devig.py` (192),
`f5_store.py` (90), `elobench.py` (184)

- These are one-off, pre-registered measurement modules for specific V1-V5
  hypotheses (dispersion, staleness, overreaction, bullpen gap, de-vig
  choice, F5 store, Elo benchmark) plus the V3 timing-latency stack
  (`eventstudy` measures one event, `leadlag` aggregates many into a
  response table, `timingtest` runs the frozen KM-median/cluster-sign-test
  primary hypothesis, `timingreport` assembles per-class reads). Each is
  explicitly scoped as descriptive/measurement, never an edge claim
  (`eventstudy.py:12-16`, `leadlag.py:10-18`, `m3_dispersion.py:11-19`).
- `timingtest.py` is the largest single research module (968 lines) and
  documents its own correction history in-line (ADDENDUM 2's fix for a
  degenerate bootstrap and a class-scope mismatch) — again, real evidenced
  correction, not narrated-only.
- None of these modules score a MARKET beyond h2h/F5-moneyline-adjacent
  quantities; none score a prop, alternate line, or parlay. F5 is the
  furthest the machinery reaches toward "another market" and it is
  data-collection/measurement only (`f5_store.py`), not yet a registered
  hypothesis family (confirmed in `docs/RESEARCH_CATALOGUE.md` U1: "no F5
  family is registered").

## Owner-vision capability classification

**EXISTS**
- A pre-registered hypothesis family that runs screen → replication → FDR
  and is structurally prevented from being evaluated off-registration
  (`funnel.py:437-479`).
- An automated, versioned, fingerprinted falsification battery with five
  fatal rules, applied uniformly to every candidate (`battery.py` entire).
- A documented, adversarially-adjudicated case of the battery itself being
  wrong and then fixed as a general rule (`docs/VALIDATION_GATE.md` check 4).
- Byte-level point-in-time integrity testing of the shared matchup matrix
  (`matrix.py` + `test_validation_pit.py`).
- An append-only cross-family search-spend ledger with a working
  `total_searched()` query surface (`alpha_registry.py`), matching the
  data file exactly (81 rows verified above).
- A public, skeptical catalogue of every hypothesis ever run, classified,
  with "zero survivors across V1/V2/V4/V5" stated plainly
  (`docs/RESEARCH_CATALOGUE.md`).

**PARTIAL**
- "Reconstruct everything legitimately knowable" — the matrix reconstructs
  lineup/starter matchup state only (7 numeric features); bullpen,
  park/weather, and market state are measured in separate one-off modules
  (m4_bullpen_gap, park data outside src/research, m3/m5 for market) but are
  never joined into one point-in-time object a strategy could condition on
  jointly. Evidence: `matrix.py:228-297` feature list vs. the vision's
  bullpen/park/market lists.
- "Search the entire board" — the funnel supports exactly one market
  (`MARKETS = ("h2h",)`, `funnel.py:111`); F5 is collected
  (`f5_store.py`) but not yet a registered family; no run-line, totals,
  props, or parlay support exists anywhere in `src/research`.
- "Backtest the analyzer... at what price, at which book, with what rating"
  — the battery grades a fixed selection rule against one closing price; it
  has no book-selection/price-improvement dimension and no "rating" concept
  (that lives, if anywhere, in the Ranker outside this subsystem).
- "Many competing analysis systems... continuously
  generate→test→attack→retire→mutate" — the strategy-factory machinery
  (Evolab: `src/evolab/*.py` — sweep, ceiling, cscv, spa, placebo, decide,
  genome, replay) is a **separate subsystem outside this scope** that does
  something closer to this, but `src/research`'s battery and funnel are
  built for single hand-written specs, not genome populations; the alpha
  registry treats an entire Evolab sweep as one entry with an internal
  multiplicity count (`alpha_registry.py:51-54`) rather than scoring
  individual genomes through the battery.

**MISSING**
- Any notion of a decision POLICY (a strategy that also picks a market,
  a book, a bet size, a timing rule) being scored by this machinery. Every
  spec is "feature crosses threshold, back the advantaged side at the
  close" — never "here is a full recommendation with price/book/rating,
  grade it."
- Prop markets, alternates, derivatives, parlays — no code path in
  `src/research` touches any of them.
- Daily bankroll simulation / unit-based backtesting — `scoreboard.py`
  counts hypotheses, not units won/lost or bankroll trajectories.
- A rating/confidence-class system ("BET RATING", "LOCKS") — not present
  anywhere in this subsystem.
- Cross-strategy correlation tracking at scale (flagged as a gap by
  `MASTER_PLAN.md` itself, and `semantic_hash_v0` explicitly does not do
  it — `alpha_registry.py:106-108`).

**CLAIMED-BUT-ABSENT**
- None found where a doc/docstring asserts something the code does not do.
  The docs in this subsystem are unusually careful about this — e.g.
  `battery.py:83-88` explicitly disclaims "survives means not falsified,
  never confirmed" rather than overclaiming, and `docs/RESEARCH_CATALOGUE.md`
  documents its own denominator inconsistencies rather than picking a
  flattering one (`docs/RESEARCH_CATALOGUE.md:313-335`). The one place
  something IS claimed and then found not to hold is self-corrected in the
  same document set: V3's `transaction_first_seen` first read was
  discovered to have measured the wrong class and was withdrawn via the
  registry's own append-only mechanism (`docs/RESEARCH_CATALOGUE.md` L1
  entry, `alpha_registry.py:67-94`) — this is the machinery catching its
  own overclaim, which counts as the system working as designed, not as an
  absent capability.

## BOOST vs REPLACE, per component

- **funnel.py — BOOST.** The screen/replication/battery/FDR discipline is
  sound and load-bearing (proven by killing 4 families for zero survivors).
  Extending it to more markets means widening `MARKETS` and
  `NUMERIC_FEATURES`, and — the real work — building the price/selection
  join for each new market the way `selections.py` already does for h2h.
  The core discipline (pre-registration enforcement, wider dose sample,
  CLOSE-based grading) should not be rebuilt.
- **battery.py — BOOST.** Versioned, fingerprinted, adversarially validated.
  Extending it to grade a decision POLICY (adding book/price-improvement
  dimensions) is additive: the row schema already accepts optional `book`,
  `price` keys; a policy-grading mode could reuse `_measure`,
  `_concentration`, `_extreme_removal` unchanged and add new checks for
  price-shopping-specific failure modes (e.g. "the improvement evaporates
  once execution slippage is modeled").
- **matrix.py — BOOST, but the join needs a bullpen/park/market sibling.**
  Rather than replace, add parallel cached objects (a bullpen-state matrix,
  a park/weather matrix, a market-state matrix) built the same
  cutoff-disciplined way, and let funnel specs name features across all of
  them — the interaction-feature mechanism (`INTERACTION_SEPARATOR`) already
  generalizes to cross-matrix products if the join keys line up.
- **alpha_registry.py — BOOST.** The append-only ledger and
  `total_searched()` surface are exactly right for the strategy-factory
  scale the vision describes; what is missing (genome/strategy correlation
  tracking) is a new capability layered on top (a similarity/cluster field
  per hypothesis id), not a redesign of the append-only core.
- **coverage.py/scoreboard.py — BOOST for coverage, REPLACE-or-extend
  scoreboard.** `coverage.expected_n` generalizes fine to new markets.
  `scoreboard.py`'s schema (hypotheses screened/killed/survivors) has no
  room for the vision's daily-bankroll/CLV/rating concepts — that needs a
  new, adjacent ledger (a "daily run" object with bankroll state), not a
  patch to this one, because scoreboard's whole contract is "epistemic
  progress on hypotheses," a different unit of account than "P&L on a
  trading day."
- **V3 timing stack (eventstudy/leadlag/timingtest/timingreport) — BOOST.**
  Mature, self-correcting, explicitly scoped to avoid overclaiming an edge.
  Reusable as-is for any other event-timing question (other event classes,
  other sports) with no structural change needed.
- **Funnel's single-market constraint (`MARKETS = ("h2h",)`) — this is the
  one piece that most needs a REPLACE-shaped change**, not because the
  mechanism is wrong but because the type is too narrow: `market` needs to
  become a real dimension the funnel prices through (a market-specific
  selection/grading adapter), not a single hardcoded string.

## Data that becomes unrecoverable if not captured now

- **F5 (first-five) closes** — collection is live now (`docs/RESEARCH_CATALOGUE.md`
  L2) but historical F5 depth is a spend-gated backfill (B3); every day that
  passes without capturing today's F5 closes is F5 history that cannot be
  reconstructed later at any price for that date.
- **V3 event timestamps (lineup post, starter scratch, transaction, umpire
  crew reveal)** — grade A/B timing only exists forward; `docs/RESEARCH_CATALOGUE.md`
  B5 states historical V3 replay is permanently blocked ("every event class
  is grade C/D historically... V3 is a forward study, entirely"). Every
  live-season event not captured with a real timestamp today is gone as
  V3-quality evidence forever.
- **Dense pre-game snapshot grid** (the 15-minute forward sampling inside
  the last three hours, feeding B2/weekend-staleness and M1/momentum
  questions) — described as "forward sampling... is now running"
  (`docs/RESEARCH_CATALOGUE.md` B2); this resolution cannot be
  reconstructed retroactively from the historical 3x/day odds store.
- **Alpha registry rows for anything run outside the registry's discipline**
  — any ad hoc hypothesis test run without calling `register()`/
  `record_verdict()` is permanently invisible to `total_searched()`, i.e. a
  future family's pre-registration would understate how much search has
  already happened against this data. This is a process risk, not a data
  risk, but it degrades the FDR-across-time guarantee silently.
- **Bookmaker/price-path granularity for any event not yet in
  `pricepath.py`'s capture** — path modules keep American, un-de-vigged
  quotes deliberately so future de-vig-method questions stay open
  (`pricepath.py:14-16`); once a game's window has passed uncaptured, no
  later purchase recovers that specific game's live path.

## Key numbers (verified by direct read/count, not quoted from docs alone)

- `src/research/*.py`: 8,475 total lines across 21 files (wc -l, this
  session).
- `data/research/alpha_registry.jsonl`: 81 rows — 40 hypothesis, 39
  verdict, 1 sweep, 1 audit; by family V1=21, V4=6, V2=5, V3=5, V5=3,
  EVOLAB_PHASE2B=1, ELO_BENCHMARK=1 (python3 count, this session) — matches
  `docs/RESEARCH_CATALOGUE.md`'s stated totals exactly.
- `data/research/family_v4_exploratory.json` count=6;
  `data/research/family_v5_stuff.json` count=3;
  `evidence/hypothesis_family.json` count=21 (python3 read, this session)
  — matches the catalogue's stated per-family denominators.
- Battery: `MIN_N=30`, `LOO_P_CEILING=0.10`, `FULL_P_LINE=0.05`,
  `LOO_SHRINKAGE=0.75`, `SPIKE_SUPPORT_FRACTION=0.5`,
  `EXTREME_DATE_FRACTION=0.05`, `CONCENTRATION_TOP=5`
  (`battery.py:100-123`) — all pre-registered constants, unchanged since
  RULES_VERSION 2.0.0.
- Six validation-gate test files total 1,517 lines
  (`tests/test_validation_*.py` + `test_battery_generality.py`, wc -l this
  session) — this is a large, real test investment behind the gate's
  claims, not a thin wrapper.
- Funnel `MARKETS` has exactly one entry: `"h2h"` (`funnel.py:111`).
- `NUMERIC_FEATURES` has exactly 7 entries (`funnel.py:85-93`).

## Answering the assigned questions directly

**What is a pre-registered family and how does it run?** A JSON-frozen list
of specs (`register_family`, `funnel.py:231-270`), each a
feature+threshold+direction+mechanism, run through `funnel.run()` which
enforces the frozen list byte-for-byte (`funnel.py:466-479`), screens on
2023, replicates on 2024, batteries the pooled sample, then BH-corrects
across the WHOLE registered family including specs that died before
producing a p-value (`funnel.py:643-675`).

**What are the battery's rules, and RULES_VERSION?** Five fatal rules
(season_split, team/book concentration, extreme_removal, dose_response),
`RULES_VERSION = "2.0.0"` (`battery.py:452`), fingerprinted per-verdict via
`rules_fingerprint()` (`battery.py:455-465`) hashing rule source +
constants together.

**How many hypotheses exist and their verdicts?** 40 hypothesis rows in the
alpha registry (verified count above) across V1(21)/V2(5)/V3(5)/V4(6)/V5(3),
plus 1 sweep (Evolab Phase 2B, 8,811 internal candidates) and 1 audit (Elo
benchmark). Per `docs/RESEARCH_CATALOGUE.md`: zero survivors across
V1/V2/V4/V5 (all TESTED_NULL or TESTED_FALSE_POSITIVE); V3 is OPEN_LIVE,
forward-only, below its class floor on the properly-scoped read.

**What does the promotion standard/unlock gates say?** `docs/MASTER_PLAN.md`
§27: pre-registration → discovery significance + effect floor → replication
→ battery + placebo ceiling + adversarial critique → ≥300-entry forward
paper window on a multi-dimensional standard (calibration, forward
predictive performance vs. market price, realized returns with CI excluding
zero, stability, drawdown, sample strength, entry-vs-close as advisory
filter) → Brey freeze sign-off, with pre-declared automatic demotion
criteria. This standard is written for the whole system (Ranker/Engine 2),
not specific to `src/research`, but `src/research`'s funnel+battery is the
component that would have to feed the "discovery significance... replication
... battery" legs of it for any h2h candidate.

**Can the machinery score STRATEGIES (decision policies with prices) rather
than features vs outcomes?** No. Confirmed by code: a funnel spec has no
book/price-improvement/timing/sizing field, only feature+threshold+direction
(`funnel.py:148-217`); the battery's row schema optionally carries `book`/
`price` but every check operates on `mean(won - implied)` against one fixed
selection, never a policy's price-execution outcome. Scoring an actual
decision policy (which market, which book, at what price, with what rating)
is architecturally a different, currently-absent layer — the closest
existing machinery is Evolab (`src/evolab/*`, out of this subsystem's
scope), which is genome/strategy-shaped but is treated by the alpha registry
as one opaque sweep entry, not run through this battery's per-candidate
falsification discipline.
