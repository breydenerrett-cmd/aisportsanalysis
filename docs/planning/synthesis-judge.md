# LINEHOUND — Synthesis and Judgment

Judge pass over `design-engine-first.md`, `design-factory-first.md`,
`design-data-first.md` and the nine `map-*.md` subsystem maps.
Written 2026-09-03. Read-only over `src/`, `data/`, `evidence/`; the only file
created is this one. Nothing here is evidence. Every number is either cited to a
file/store or labelled an estimate.

Standing constraints are load-bearing throughout and are never relaxed:
point-in-time integrity sacred; 2025 tuning-only; sealed 2026 untouched for
research reads; losers published; no real-money placement; never fabricate;
price improvement is never EV or edge; the Ranker publishes nothing while
`ENGINE2 is None` until the unlock gates clear **and** the owner signs off.

---

## 0. The architecture in one paragraph

Capture writes the provider's bytes verbatim to an immutable raw layer, then
projects them into one universal record — **selection, line, price, book,
observed-at, known-at, grade** — plus a parallel record for everything that is
not a price. One reader, `as_of(T)`, assembles a **Snapshot** that stops at T
rather than filtering, refuses sealed windows by name, and cannot open a
directory containing a close, a result or a settlement. One pure function,
`analyze(snapshot, systems, adversaries)`, turns that Snapshot into 0..N scored
candidates: systems form probabilities against a **price-blind** view, the
engine projects each probability onto every priced selection on the board,
adversaries attack, and a rating is computed from probability, price, friction
and the producing system's own forward track record. Live and replay call that
identical function and are held to byte-equal snapshot fingerprints by a
conformance test. A Strategy Factory generates, screens, replicates, attacks,
scores, retires and forward-tests populations of systems against that same
function under identical frame hashes, selecting on a multi-dimensional
scorecard that is structurally incapable of reading a bankroll field. The
product renders only what the governor has already promoted, and today that is
nothing, which the product says out loud.

---

## 1. Scores and the verdict

Scored on fidelity to the owner's vision, leakage safety, buildability from what
exists on disk, scale, and honesty about difficulty.

| Design | Fidelity | Leakage | Buildability | Scale | Honesty |
|---|---|---|---|---|---|
| **engine-first** | 9 | 9 | 9 | 8 | 8 |
| **factory-first** | 8 | 8 | 8 | 8 | 10 |
| **data-first** | 8 | 10 | 7 | 10 | 10 |

**engine-first — 9/9/9/8/8.** The only design that turns "which market best
expresses the informational advantage" into a *mechanism* rather than a
procedure: `PriceBlindWorldView` makes price-blindness a property of the type
system, so a system physically cannot route itself to whichever line looks
softest. Its live-vs-replay digest conformance test is the single most valuable
test any of the three proposes, and it is the only one that would catch a leak
both paths share. Packets are the most immediately executable. Marked down on
scale (it costs the 9.8 TB decision-storage problem no thought) and on honesty
(it is confident about board expansion in places the bytes do not support).

**factory-first — 8/8/8/8/10.** Owns the statistics. The -110 arithmetic — per-bet
SD ≈ 0.995u, so at n=300 the best of 1,000 zero-edge strategies shows ≈ +2.5σ
≈ +14% ROI with near-certainty — is the strongest single argument anywhere in
the three documents, and it forces the Two-Ledger Rule. Its P7 time-shift
placebo (re-run with T advanced two hours; if the objective *improves*, a leak
is the leading hypothesis) is the only *empirical* leak detector proposed by
anyone; every other control catches a leak someone already thought of. Its
per-cell evolutionary gating correctly identifies that a blanket prohibition
derived from one negative cell over-generalizes from a single result. Marked
down on fidelity because its "one belief, many projections" correction, while
right, defers the whole-board search until a calibrated `Belief` exists — which
may be years — and on leakage because moving `assert_point_in_time` from a
decision-time raise to a promotion-time raise makes leaky reads silent by
default.

**data-first — 8/10/7/10/10.** Found the root cause nobody else found: the price
record has exactly two fields, `home_price`/`away_price`, baked into eight
modules, and that — not credits, not code difficulty — is why this is a
one-market system. It measured the consequence: **302,271 totals market rows
across 2023/2024/2025 already on disk, already paid for, read by nothing**,
because `replay.MARKETS_SERVED = ("h2h",)`. That single finding roughly doubles
the historically replayable board for zero credits and is the most valuable
discovery in the entire twelve-document set. Its `known_at` grade ladder in the
schema, its physical seal (a reader that *cannot open* a `prices_close/` or
`results/` path, with a test that tries), its content-addressed frames as a
leakage control rather than a cache, and its "determinism is the compression
algorithm" answer to the 9.8 TB problem are each best-in-set. Marked down only on
buildability: fourteen packets in two weeks, on top of a four-layer store
migration, is more than the fortnight holds.

### Winner

**engine-first wins, narrowly, as the spine — and it wins only because
data-first's universal record is grafted in underneath it as a hard
prerequisite.**

The reason is structural rather than aesthetic. This repository already has
*two* decision paths that do not know about each other: the live path
(`mismatch.scan_game` → `route_market` → `briefing.build_slate` →
`ledger.record_slate`, with hard-coded two-market routing at
`mismatch.py:157-158,364`) and the replay path (`replay.world_view` →
`decide`). They will keep diverging in the hundred small ways that make a
backtest optimistic, and no store design fixes that. Engine-first is the only
design whose *first move* is to collapse them into one function and then prove
the collapse with a test. Data-first is right that the engine cannot be built on
a two-field price record — so the record lands first, in week 1, as the engine's
input type rather than as its own program. Factory-first is right about
everything statistical, and its contributions are governance layered on top of
the waist, not an alternative to it.

Put plainly: **data-first is the prerequisite, engine-first is the spine,
factory-first is the immune system.** Building factory-first first would scale a
population over a six-feature substrate, which mostly buys better overfitting.
Building data-first first alone would produce an excellent store feeding two
divergent engines.

---

## 2. What each design contributed that the winner did not have

Grafted into the synthesis, with attribution.

**From data-first (the largest set of grafts):**

1. **The universal record.** `PriceObservation` with `selection_id`, `line` as a
   decimal *string*, no `home_price`/`away_price` anywhere, three distinct
   clocks (`observed_utc`, `book_last_update`, `known_at`). A two-way market is
   two rows. A line is part of the selection identity, not a modifier — which
   collapses "alt run lines, alt totals, alternates" from three build items to
   zero, and "team totals, pitcher props, batter props" to a `subject` field.
2. **The 302,271 unread totals rows**, and the L1 backfill that makes them
   replayable. This changes the roadmap: the honest historical board becomes two
   families, not one, at zero credits.
3. **`known_at` + the A/B/C/D grade ladder in the schema**, with grade C/D
   excluded by default, opt-in explicit, and `assumption_exposure` stamped on
   every artifact. Grades may be lowered by audit, never raised, in an
   append-only `grade_audit.jsonl`.
4. **The physical seal.** Closes, results and settlements live under directories
   the reader's path allowlist cannot open; `src/engine/**` and `src/factory/**`
   may not import the store directly, only `as_of`. Enforced by an import-guard
   test in the same style as the existing stdlib-only and network-block CI
   guards.
5. **"Determinism is the compression algorithm."** 5,000 systems × 4,819 games ×
   2 point classes × ~40 selections × 51 worlds ≈ 9.8 × 10^10 decisions ≈ 9.8 TB
   if stored. Store the *recipe* and the aggregate scorecard; reproduce any
   single decision on demand from six strings; prove it with a CI job that
   reproduces 1,000 sampled decisions byte-identically.
6. **`Friction` as a first-class stored field**, and ranking on *edge net of
   friction*. This is the correction that stops cross-market ranking from
   systematically selecting the widest, thinnest, stalest market on the board —
   a failure mode that looks like success in a backtest. Neither sibling names it.
7. **Hash-chained ledgers** with `verify_chain()` in CI. `MASTER_PLAN.md:770`
   already describes the ledger as hash-chained in the present tense; no chain
   exists anywhere in `src/`.
8. **The write-order rule** and the separation of `edge_bps` from
   `price_improvement_bps` as two columns with a test that fails if any path sums
   them or assigns one to the other. A rule that is a column cannot be forgotten
   in a refactor.
9. **Prediction markets need a `venue_kind` and a fee model**, or every consensus
   and de-vig calculation quietly mixes two different kinds of price.

**From factory-first:**

10. **The Two-Ledger Rule**, enforced by an AST test over `objective()` that
    fails if any of `{account, bankroll, units, drawdown, roi_units,
    profit_units}` appears — the same mechanism `genome.py` already uses to make
    sign keys unsearchable. The bankroll simulation the owner asked for is kept
    in full and demoted from objective to report.
11. **P7, the time-shift placebo.** One extra world in an already-parallel sweep.
12. **Per-cell evolutionary gating**: operators unlock within a
    (market family × fitness dimension) cell when an enumerated strategy in that
    cell clears its placebo ceiling. A failure in (h2h, movement,
    lineup-composition) does not gate (F5 totals, calibration, bullpen-workload).
13. **The registered null for the LLM proposer** (H-PROP-1: proposed strategies
    do not beat enumerated ones per unit of `total_searched()`), and the `origin`
    field that makes it measurable.
14. **`n_independent_clusters` as a required field**, so `n_decisions` can never
    be quoted as sample size.
15. **Decision-point class is never compared across classes.** A strategy
    discovered at `LATE_BOARD` on 2023-24 and forward-tested at `POST_LINEUP` in
    2026 has not been forward-tested; it has been tested on a different
    instrument.
16. **A settlement adapter tested against ≥50 known games before a market family
    may be priced.** A wrong settlement produces a confident, plausible, wrong
    backtest that no statistical test will catch.

**From engine-first (the spine's own best parts, kept):**

17. `PriceBlindWorldView` as a type, not a convention.
18. The live/replay fingerprint conformance test as the week-2 exit gate.
19. Adversaries and `Counterargument` as deterministic code with severity, where
    FATAL removes a candidate but records the refusal.
20. The **no-new-information refusal**: if the snapshot fingerprint is unchanged
    since the last row for this game, write nothing. Without it, repeated capture
    ticks inflate the forward selection count toward the 300-gate without adding
    evidence — a quiet way to reach the gate dishonestly.
21. `expected_selection_rate` pre-registered per system, with a trip-wire on the
    realized rate. This is the mechanical counterpart to "never force quantity".
22. **MLB StatsAPI / GUMBO per-game batter and pitcher box lines** — free,
    keyless, backfillable to 2023 — as the grading substrate for the largest
    market surface in the vision. It appears on no other capture-now list.
23. Sport-neutral engine contract from day one; baseball lives in the assemblers,
    the sections and the market catalogue.
24. **The gate itself as a shippable surface**: a live readout of each unlock
    condition and its current value ("forward selections: 41 of 300"), which is
    honest, satisfies losers-published ahead of time, and is the one thing no
    competitor will show.

---

## 3. Where the designs disagree — twelve adjudications

### 3.1 Price-blind proposal vs. one-belief-many-projections

engine-first makes price-blindness structural and loops over the board.
factory-first argues that literal per-market threshold search multiplies the
search space by forty and the evidence by zero, and that the right object is one
`Belief` projected arithmetically onto every payoff function.

**Both, and they are compatible.** A `Belief` is simply a `Proposal` that
returns a distribution instead of a point probability. Adopt the price-blind
type *now* (it costs nothing and is expensive to retrofit) and reserve the
distribution-valued proposal slot in the contract from day one. `propose()` may
return either `p_model` per selection or a distribution the engine projects.
Projection is engine-side arithmetic in both cases; the system never sees a
price in either case.

**The decision factory-first implies but does not state, and that this synthesis
makes explicit: the unit of multiplicity is the *proposal*, not the selection.**
One system's one thesis projected onto forty selections is one test, not forty —
*provided* the rule that picks which selection to act on is pre-registered
(highest rating net of friction), not chosen after seeing which backtested best.
`alpha_registry.total_searched()` increments per (system, cell). Getting this
wrong in either direction is fatal: count forty and the FDR burden is
unpayable; count one while shopping the board after the fact and the whole
protocol is theatre.

### 3.2 `assert_point_in_time`: hard raise, promotion-time raise, or graded opt-in

Today it raises for all six registered features, which blocks the program.
factory-first moves the raise to promotion time. data-first excludes grade C/D by
default, requires an explicit `allow_grades` opt-in, and stamps
`assumption_exposure` on every artifact.

**data-first's version, plus factory-first's promotion rule.** Moving the raise
to promotion time alone makes leaky reads *silent by default*, which is the
opposite of this project's culture. The default read is A/B; C/D requires
naming; the exposure is printed on every artifact; and promotion additionally
requires a forward A/B window even when discovery used C. This changes a
standing refusal and therefore needs the owner's signature (§8).

### 3.3 Ledger identity

Three proposals: `(game_pk, T, system_id, selection.key)` (engine-first),
`(game_pk, strategy_id, decision_instant)` (factory-first),
`(engine_version, system_id, game_pk, point_class)` (data-first).

**Take all four contributions:
`(engine_version, system_id, game_pk, point_class, selection_id)`, with
idempotency on `snapshot_fingerprint`.** `engine_version` because a semantics
change must not silently rewrite history. `point_class` because scores are never
compared across classes (§3.1 of factory-first). `selection_id` because one
system emits multiple candidates per game. The fingerprint refusal because
without it the 300-gate is reachable by duplicate ticks.

The rule this replaces — `ledger.py`'s one-priced-row-per-game-ever
(`ledger.py:62-79`) — was written to fix a real incident (five identical
recommendation sets on 08-30). The correct fix is idempotency on the full key,
not one row per game.

### 3.4 Primary fitness

Unanimous that line movement should not be primary, for a sharp reason: a system
can beat the close systematically by betting into stale books, which is
execution quality, not prediction, and is exactly what `prices.py`'s mandatory
non-EV label exists to keep separate.

**Primary: calibrated log-loss against outcome, benchmarked against the
de-vigged market price** (`src/core/calibration.py::compare` already computes
exactly this and is wired only to synthetic data). **Second: realized return at
the captured entry price, with a day-clustered bootstrap CI excluding zero.
Third, advisory only: CLV.**

Two conditions on the switch. It requires a *fresh registration* — it changes
what "Phase 2B" means. And Phase 2B's published verdict
(BELOW_PLACEBO_CEILING, pooled percentile 13.3, PBO 0.6111, 0/3 generators
cleared) **stands unamended**; the fitness change is a plausible partial
explanation for the null and that belongs in the re-run's write-up, not in a
retroactive reinterpretation of a published result.

### 3.5 Evolutionary gating: global or per-cell

engine-first and data-first keep the blanket gate. factory-first argues per-cell.

**Per-cell, with a correction neither makes.** Phase 2B tested one market × one
fitness × one feature class; treating that as a permanent global prohibition
over-generalizes from a single negative result — precisely the error the battery
exists to catch. But per-cell gating invites cell-shopping. So: **cells are
pre-registered before the sweep that tests them, and the number of cells is
itself a multiplicity charge in `total_searched()`.** Unlocking operators in a
cell requires that cell's enumerated search to clear its ceiling at the
pre-registered percentile, with effective-tests reported alongside raw.

### 3.6 Bankroll

**Two-Ledger Rule, adopted whole,** with the AST test. The Objective Ledger
decides survival and cannot name a money field. The Account Ledger simulates
1,000 units day by day over whole seasons, holdouts and forward paper, exactly
as the owner describes, is published, and never enters selection. Stake rules are
named, versioned and declared *before* the forward record starts
(`FLAT_1U`, `FLAT_2U`, `KELLY_QUARTER_CAPPED_2U`) — never chosen after seeing a
curve.

### 3.7 LOCK

Three definitions offered. **Take the conjunction of all three**, because each
catches something the others do not, and add auto-withdrawal:

A candidate is a LOCK only if **all** hold: (1) it comes from a PROMOTED system;
(2) the system has `band_n ≥ 200` forward settled decisions in that probability
band with `band_ece ≤ 0.02`; (3) the band's forward monotonicity has been
demonstrated — the top band beats the next band down on both realized outcome
and price-vs-close, with clustered CIs; (4) the edge survives at the **worst**
book on the board and survives shrinking `p_model` 25% toward the market; (5) at
least two systems with **disjoint `declared_inputs`** agree on the selection;
(6) no counterargument at MAJOR or above; (7) the market family has ≥90 days of
forward evidence.

The LOCK **base rate is published as a headline number**; a rate above ~2% of
candidates is a defect to investigate, not a good day. The label is **withdrawn
automatically** the first time band monotonicity or the calibration band fails at
the stated review cadence, and the withdrawal is published. `N_LOCK` is set by
power analysis before any LOCK is ever shown.

Consequence the owner should hear now: this definition mathematically produces
**zero LOCKs until a system has been promoted and has accumulated ≥200 forward
decisions in one band** — realistically not this season, probably not next. A
product that says "no locks tonight" four nights in five is more credible than
one that never does; a threshold-shaped LOCK would guarantee LOCKs exist every
day whether or not any are deserved.

### 3.8 Parlays

engine-first frames them as a pricing-efficiency problem (measure
`book_implied_correlation` against your own). factory-first blocks the research
and opens the capture. data-first insists the *source decision* comes first — can
SGP prices even be read from the API, for which books, at what cost?

**All three, sequenced: source decision → co-occurrence store → capture of
declared leg sets → no recommender until a joint distribution exists.** The
co-occurrence store (a bitset AND and a popcount over machinery that already
exists) is not parlay-specific: it is also the instrument for population
correlation and the effective-number-of-tests count in §3.9, so it earns its keep
twice.

Say the arithmetic to the owner plainly: for uncorrelated cross-game legs the
book multiplies and the vig compounds, so a two-leg parlay needs roughly **twice
the per-leg edge** to match two singles. Most parlays are a strictly worse
product and the design should say so up front rather than searching for an
exception. The exception worth hunting is the book's *correlation error*, which is
a falsifiable research program with a defined instrument.

### 3.9 Multiplicity at factory scale

`alpha_registry.total_searched()` is the right primitive and it exists, but
`semantic_hash_v0` catches only exact atom-set duplicates
(`alpha_registry.py:106-108`) and BH-FDR against a raw count is close to vacuous
when systems are massively correlated: 8,811 genomes over 6 features are not
8,811 independent tests, they are perhaps a few dozen.

**Report the effective number of tests (clusters from the selection-overlap
matrix) alongside the raw count, always both, never one alone.** And the
strategic consequence, which all three designs reach independently and which is
the single most important implication of the Phase 2B result: **scale the
substrate before scaling the population.** Ten times the population over six
features mostly buys better overfitting; ten times the features and markets is
where the information is.

### 3.10 Store layering

data-first's L0/L1/L2/L3 is right, but a big-bang migration is the main way this
fortnight fails.

**Adopt L0 (raw verbatim, written before projecting) and L1 (canonical) by
dual-write, never by migration in place.** Legacy stores keep emitting
byte-identical rows — that is data-first's own P1 acceptance criterion and it is
the right one. L2 frames are deferred until the timing instrumentation says
otherwise. `sqlite3` (stdlib, no CI change) is a *derived index*, never a source
of truth. The DuckDB question gets a nameable trigger — parse+build time >30% of
a cycle's measured wall clock, or a cycle >2 hours on four CPUs — which is
unaskable today because nothing measures anything.

### 3.11 The detectors

factory-first and data-first say reclassify them as a feature/evidence library
and strip their decision authority. engine-first wraps them as `DetectorSystem`.

**Both.** `mismatch.route_market` retires — hard-coded two-market, two-signal
routing is structurally the opposite of "search the whole board". The eleven
detectors keep their product role as the Analyzer's evidence surface, and their
`Finding` shape (which already refuses to emit a signal without a baseline) maps
onto `Evidence` almost field for field. As `DetectorSystem` proposals they go
through the same battery, ceiling and promotion gates as anything else. What they
lose is the parallel, ungoverned authority to decide.

### 3.12 Credit envelope

engine-first tiers to ~7,000/day at full board. factory-first recommends E2 at
~250-350/day. data-first proposes ~978/day on a Tier A/B/C grid.

**data-first's tier *shape* with a corrected Tier A cadence.** The shape is the
sharpest insight: the featured endpoint bills **3 credits flat for the whole
slate at any size**, so slate width is free and the all-day 15-minute grid is the
response variable for every timing and movement question. But 96 calls a day
includes an overnight window that buys little.

Recommended: Tier A at 15-minute cadence over an 18-hour window ≈ **216/day**;
Tier B (F5 trio, alternates, team totals) at three moments ≈ **270/day**; Tier C
(5 pitcher keys, 9 batter keys) at two moments ≈ **420/day** — about **900/day,
~27k/month against a measured ~99,621 balance** (`credit_log.jsonl`,
2026-09-03T01:01:38Z). That is a 6.8× increase over the ~132/day envelope and
still leaves ~70% headroom. **Reject the ~7,000/day full-board hourly plan**: it
requires the 5M tier and buys mostly redundant instants on markets that move
slowly, when the same money buys breadth that expires.

Two governance fixes, adopted from all three: a hard-coded `DAILY_ENVELOPE`
constant with the same shape as `CREDIT_FLOOR = 5000`, with a *coded* drop order
(Tier C batter → Tier C pitcher → Tier B alternates → Tier B team totals → Tier B
F5 → thin the Tier A grid; Tier A last, always); and reconcile the
53,083-vs-99,621 discrepancy against the vendor's billing history now, while it
is still explainable.

---

## 4. The synthesized architecture

### 4.1 Layers

```
L0  RAW          data/raw/<source>/<yyyy>/<mm>/<dd>/<capture_id>.jsonl[.gz]
                 verbatim provider payloads, one file per API call, never edited.
                 The only layer that must be backed up.

L1  CANONICAL    data/board/prices/<sport>/<season>/<date>.jsonl     PriceObservation
                 data/board/prices_close/...  (SEALED — as_of cannot open)
                 data/knowledge/events/...                           InformationEvent
                 data/knowledge/results/...   (SEALED)
                 deterministic projection of L0; rebuildable byte-identically.

L2  FRAMES       data/frames/<fingerprint>/{header.json,cols.bin,masks.bin,prices.bin}
                 content-addressed by (L1 digests, registry fp, engine version,
                 t_policy, allow_grades). DEFERRED until timing justifies it.

L3  LEDGERS      evidence/decisions/<yyyy-mm>.jsonl    hash-chained
                 evidence/settlements/<yyyy-mm>.jsonl  hash-chained, SEALED
                 evidence/reviews/<yyyy-mm>.jsonl
                 evidence/factory/{population,graveyard,scorecards,accounts}.jsonl
```

Packages: `src/board/` (identity, record, catalogue, settlement rules),
`src/knowledge/` (events, `as_of`, grades), `src/capture/` (budget, tiers, plan),
`src/engine/` (worldview, analyze, rating, adversaries, review),
`src/factory/` (population, generate, score, attack, lifecycle, cycle),
`src/evolab/` boosted in place then re-pointed behind an equivalence proof.

### 4.2 Contracts

Market identity — a line is part of the selection, a subject is first-class:

```python
# src/board/ids.py
MARKET_CATALOGUE: dict[str, tuple[str, str, str]]   # key -> (scope, shape, settlement_rule)

def selection_id(*, sport: str, market_key: str, side: str,
                 subject: tuple[str, str] | None = None,
                 line: str | None = None) -> str: ...   # sha256 of canonical tuple, 16 hex

@dataclass(frozen=True, slots=True)
class PriceObservation:
    sport: str; event_id: str; game_pk: int | None
    market_key: str; selection_id: str; side: str
    subject_kind: str | None; subject_id: str | None
    line: str | None                     # DECIMAL STRING — never a float
    book: str; price_american: int       # American only; decimal/implied are derived
    observed_utc: str                    # when WE saw it
    book_last_update: str | None         # when the BOOK moved
    known_at: str; known_at_grade: str   # "A"|"B"|"C"|"D"
    capture_id: str; source: str; region: str; provider_market_key: str
    venue_kind: str = "sportsbook"       # "sportsbook" | "exchange"  (fees differ)
    is_close: bool = False               # is_close rows live in the sealed partition

@dataclass(frozen=True, slots=True)
class InformationEvent:
    sport: str; scope: str; scope_id: str
    kind: str                            # probable_pitcher | lineup_posted | il_placement
                                         # | weather_forecast | umpire_crew | boxscore_final ...
    payload: Mapping
    happened_utc: str | None; known_at: str; known_at_grade: str
    observed_utc: str; source: str; capture_id: str

@dataclass(frozen=True)
class MarketFamilySpec:
    key: str; provider_key: str; scope: str; subject_kind: str
    sides: tuple; has_line: bool; devig: str          # registered method id, not a default
    capture_tier: str; credits_per_event: int
    status: str                                        # LIVE|PROBE|DECLARED|BLOCKED
    evidence_window: tuple                             # per family; h2h/totals differ from props
    settle: str                                        # SETTLEMENT_RULES key — REQUIRED
    correlation_group: str
```

The one reader:

```python
# src/knowledge/asof.py — the ONLY read path any decision may use
def as_of(*, sport: str, game_pk: int, t: str,
          allow_grades: frozenset = frozenset("AB"),
          root: Path = BOARD_ROOT) -> Snapshot:
    """Everything legitimately knowable about one game at instant t.

    STOPS at t on an ascending day-partitioned scan; never filters late.
    Raises SealedWindowError by name before opening anything.
    Cannot open any path outside `root`; `root` never contains
    prices_close/, results/ or settlements/ — and a test tries.
    """

@dataclass(frozen=True, slots=True)
class Snapshot:
    t: str; point_class: str
    game: GameContext
    sections: Mapping[str, Section]      # starters|bullpen|offense|players|environment|market
    features: Mapping[str, float]        # flat away_/home_ scalars — the bitset substrate
    board: Board
    grades: Mapping[str, str]
    assumption_exposure: Mapping[str, int]   # {"D:probable_pitcher": 4188, ...}
    fingerprint: str                     # sha256 of canonical bytes — the conformance unit
    def price_blind(self) -> "PriceBlindSnapshot": ...

@dataclass(frozen=True, slots=True)
class PriceBlindSnapshot:
    """Identical, minus board. __getattr__ raises for 'board'/'quotes'/'price'
    exactly the way it raises for 'outcome'. Systems form views against THIS."""

@dataclass(frozen=True, slots=True)
class Board:
    quotes: tuple                              # canonically ordered by selection_id
    def selections(self) -> tuple: ...
    def best(self, selection_id) -> Quote | None: ...
    def consensus(self, selection_id, min_books: int = 6) -> Consensus | None: ...
    def friction(self, selection_id) -> Friction: ...   # vig, book count, staleness, dispersion
```

The waist:

```python
# src/engine/analyze.py
def analyze(snapshot: Snapshot, *, systems: SystemSet,
            adversaries: tuple = DEFAULT_ADVERSARIES,
            config: EngineConfig = DEFAULT_CONFIG) -> Analysis:
    """0..N scored candidates for one game at one instant. Empty is a normal answer.

    PURE: no I/O, no clock, no randomness, no globals, NO MODEL CALL.
    Cannot tell whether it is running tonight or replaying 2023-04-11.

    1 PROPOSE  each system sees snapshot.price_blind(); returns Proposals
               (a point p_model per selection, or a distribution to project)
    2 PROJECT  the engine prices every proposal against EVERY selection on the
               board its thesis covers; de-vigs; computes edge NET OF FRICTION
    3 ATTACK   adversaries emit Counterarguments; FATAL removes (and records)
    4 RATE     BetRating from (p_model, entry price, friction, the system's own
               forward record in this family and probability band)
    5 RANK     deterministic total order; no tie resolved by chance
    """

class AnalysisSystem(Protocol):
    id: str; version: str; spec_hash: str
    declared_markets: tuple; declared_inputs: tuple
    min_grade: str; expected_selection_rate: float
    def propose(self, view: PriceBlindSnapshot) -> tuple[Proposal, ...]: ...

class Adversary(Protocol):
    id: str
    def attack(self, cand: Candidate, snapshot: Snapshot) -> tuple[Counterargument, ...]: ...
    # StaleBook, ThinBoard, NonSimultaneous, Grade, CorrelatedEvidence,
    # MarketDisagreement, Sample, Regime, Friction
```

Records written:

```python
@dataclass(frozen=True, slots=True)
class DecisionRecord:
    engine_version: str; system_id: str; system_version: str
    registry_fingerprint: str; frame_fingerprint: str | None
    snapshot_fingerprint: str
    game_pk: int | None; event_id: str
    decision_utc: str; point_class: str; information_time: str; recorded_utc: str
    verdict: str                    # play|no_play|market_unavailable|refused_*
    selection_id: str | None; market_key: str | None; line: str | None
    book: str | None; price_american: int | None      # REQUIRED on a play
    consensus_fair: float | None; books_at_decision: int | None
    friction: dict | None
    p_model: float | None; p_model_interval: tuple | None
    edge_bps: int | None                              # (p_model - fair), NEVER improvement
    price_improvement_bps: int | None                 # separate column, separate meaning
    rating: dict | None                               # None until a calibrated model exists
    thesis: str | None
    evidence: list; counterarguments: list            # non-empty REQUIRED on a play
    supporting_systems: list
    refusal_reason: str | None
    assumption_exposure: dict
    stake_units: float                                # 0.0 while the gate is closed
    prev_hash: str; row_hash: str
    # Task additions layered onto this frozen shape since it was written,
    # kept here rather than silently drifting the doc from the code
    # (src/ledger/records.py's own comment on each explains why):
    #   known_at_grade: str            -- knowability grade alongside the
    #                                      PriceObservation identity fields
    #   value_basis: str | None        -- REQUIRED-in-spirit whenever
    #                                      p_model is None: names what a
    #                                      price-standing-only candidate's
    #                                      selection rested on instead of a
    #                                      calibrated probability
    #   selection_rule: str | None     -- the slate runner's own named,
    #                                      pre-registered rule for how this
    #                                      record became (or did not
    #                                      become) a paper wager

@dataclass(frozen=True, slots=True)
class ReviewRecord:
    decision_key: tuple; review_utc: str
    settled: str                    # win|loss|push|void|unsettled
    thesis_outcome: str             # CONFIRMED|REFUTED|UNTESTED|VARIANCE  — COMPUTED
    mechanism_checks: tuple         # [{name, expected, observed, verdict}]
    market_path: dict               # entry, close, movement in prob points (advisory)
    late_information: tuple; missed_information: tuple
    lineup_delta: dict; bullpen_delta: dict
    counterargument_realized: tuple
    variance_flag: bool             # thesis HELD and outcome disagreed
    system_action: str              # none|watch|demote|retire — from pre-declared trip-wires
    new_hypothesis: str | None      # queued for registration, never auto-run
```

`thesis_outcome` is **computed from `mechanism_checks`, never written**. A
free-text "the thesis was right, variance beat us" is a machine for laundering
losses into confidence. `VARIANCE` is assignable only when the mechanism checks
confirmed and the outcome disagreed, which makes it a measurable rate rather than
an excuse. A system that claimed "this starter collapses third time through" and
won because a reliever gave up five in the eighth did not have its thesis
confirmed — it got paid for being wrong, which is the most dangerous unlabelled
outcome a research system can have.

Scoring:

```python
@dataclass(frozen=True, slots=True)
class Scorecard:
    system_id: str; world: str; window: str; point_class: str; market_key: str
    n_decisions: int; n_independent_clusters: int     # game-day blocks >= 7 days, REQUIRED
    logloss_vs_market: float; brier: float; reliability_bins: tuple
    realized_return: float; realized_return_ci: tuple  # clustered bootstrap
    avg_odds_decimal: float; clv_bps_mean: float       # advisory only
    stability: dict                                    # season|book|market|month|regime
    price_sensitivity: dict                            # entry, -10c, consensus, WORST book
    top5_win_share: float
    placebo_percentile: float; cscv_pbo: float; spa_p: float
    battery_verdict: str; battery_rules_version: str
    effective_tests: int; raw_tests: int
    total_searched_at_verdict: int
    account: AccountSummary                            # REPORTED, never optimized

FORBIDDEN_OBJECTIVE_FIELDS = frozenset({
    "account","bankroll","units","drawdown","roi_units","profit_units"})

def objective(card: Scorecard) -> float:
    """The single scalar the factory ranks on. Structurally cannot read money —
    an AST test over this function fails if any forbidden name appears."""
```

Promotion is **not** a weighted sum. Each named dimension has its own declared
floor in versioned `config/promotion_gates.json`, and **all** must clear. A
weighted sum lets a spectacular ROI outrun a calibration failure, which is
exactly the failure the owner ruled out. `promote()` returns `PROMOTED` or
`REFUSED` with the unmet gates and their current values — a machine verdict.
Its first acceptance test: run it against Phase 2B's best genome and confirm it
returns REFUSED naming the specific failures.

### 4.3 The daily loop

```
all day   capture.plan_day(slate, balance, spent_today) -> PlannedCall[]
          Tier A 15-min featured grid (flat 3 cr/slate) ; Tier B/C at named moments
          L0 verbatim FIRST, then project to L1. Free polls: rosterwatch,
          umpirewatch, weather — every tick, never deduped.

T-6h      loop.morning(date)
            for each game: snap = as_of(t) ; proposals = systems.propose(snap.price_blind())
          -> DecisionRecord[] @ T_MINUS_6H, including no_play with a named reason

T-3h      knowledge.await_lineup() -> InformationEvent (grade B bracket)
          loop.post_lineup(date) — re-run as_of + analyze for games whose lineup posted
          -> DecisionRecord[] @ POST_LINEUP   (the row today's ledger CANNOT write)

T-30m     loop.late(date) — final board, final analyze; RATINGS ARE COMPUTED HERE
          -> DecisionRecord[] @ T_MINUS_30M
          Appends only when snapshot_fingerprint changed (no-new-information refusal)

T-0       capture.close_pass() -> PriceObservation(is_close=True) into the SEALED partition
          Ledger freezes: no row may carry decision_utc >= commence_time

post      settle.run(date)  -> Settlement[] with closing threaded from the sealed partition
          account.run(date) -> BankrollDay[]  (1,000 units, day by day — REPORTING ONLY)
          review.run(date)  -> ReviewRecord[] (computed, not narrated)
          factory.cycle(date)
```

Two properties today's pipeline lacks and this loop requires: **every game gets a
row at every point class**, including declines with named reasons — a system
whose whole point is declining is undescribable without its declines; and
**ratings are computed at the last decision point, not the first** — a rating
that has aged six hours through a lineup change is not a rating.

### 4.4 The factory loop

```
factory.cycle.run(date):
  01 generate    enumerate new cells ; mutate/cross ONLY within unlocked cells
  02 dedupe      semantic hash + overlap cluster vs population AND graveyard;
                 pruned branches are not re-proposed (pruning is itself registered)
  03 register    alpha_registry.register() every survivor — BEFORE evaluation
  04 evaluate    bitset sweep: real world + 50 placebo + P7 time-shift, 4 CPUs
  05 score       Scorecard per (system, world, window, point_class, market)
  06 attack      research.battery per candidate above the effect floor
  07 ceiling     placebo percentile + CSCV PBO + SPA + effective-tests
  08 transition  lifecycle changes; graveyard rows with a PRE-DECLARED cause
  09 account     bankroll simulation — reporting only
  10 artifact    write with timings, fingerprints, total_searched(), exposure
```

Lifecycle:
`PROPOSED → REGISTERED → SCREENED(2023) → REPLICATED(2024) → ATTACKED →
CEILING_TESTED → (tune on 2025 only) → FORWARD_TESTING → PROMOTED`, with
`RETIRED`/`GRAVEYARD` as edges off any stage and `DEMOTED` off `PROMOTED`.
Every transition is an append-only row with a cause drawn from the reasons
declared at registration — a system retirable for any reason after the fact was
never really tested. **The graveyard is published**; that is "losers published"
made mechanical rather than remembered.

Steps 01-10 contain **no model call**, enforced by a grep test over
`src/engine/`, `src/board/`, `src/knowledge/`, `src/factory/` for
`anthropic|openai|api_key|urllib.request|requests|datetime.now|random\.`.

**2023-24 discovery can generate and kill; it can never promote.** Promotion
requires a forward class A/B window. That is a hard rule in `lifecycle.py`, not
a caution in a document.

### 4.5 Replay guarantees

Twelve controls, layered from structural to empirical:

1. `as_of()` **stops** at T on an ascending scan; it never filters. A filter is a
   habit; a stop is a guarantee (`replay.py:577` already does this — generalize
   it to every store).
2. Forbidden outcome/close names absent from the type, refused **recursively** at
   construction. Today's check walks only top-level `features` keys
   (`decide.py:135`); `genome.py:202` already has the correct recursive walker.
3. Grade C/D excluded by default; opt-in explicit; `assumption_exposure` stamped
   on every artifact, which is invalid without it.
4. Closes, results and settlements in physically separate directories the
   reader's path allowlist **cannot open** — and a test tries.
5. `src/engine/**` and `src/factory/**` may not import the store; only `as_of`.
   Import-guard test.
6. Sealed seasons refused **by name at the store layer**, before any file opens —
   not only inside replay as today.
7. Frame fingerprints are content addresses over exact input bytes. A frame built
   including post-T rows is a different frame and cannot be silently reused.
8. **The conformance test.** For a sampled set of live `(game, point_class)`,
   rebuild the Snapshot from the store afterwards and assert
   `snapshot.fingerprint` equality against the value recorded on the live
   `DecisionRecord`. A mismatch means either the live path saw something the
   store did not keep, or the store gained something the live path could not have
   seen. Both are silent today. **This is the week-2 exit gate.**
9. **P7 time-shift placebo.** Re-run with T advanced +2h. A genuine edge should
   *degrade*, not improve, when handed two extra hours it should not have. One
   more world in an already-parallel sweep, and the only control that catches a
   leak nobody thought of.
10. Hash-chained decision and settlement ledgers with `verify_chain()` in CI.
    Append-only is a convention; a chain is a proof.
11. Write-order rule: a Settlement may not be written for a decision whose
    `decision_utc` is later than the game start. Trivially true today;
    catastrophic and invisible the first time a backfill script is careless.
12. Grades may be lowered by audit, never raised, in an append-only
    `grade_audit.jsonl` with a reason and a commit.

**The honest limits, stated rather than engineered around.** 2023-24 board
spacing is min 177 minutes, median 6 hours; `T_MINUS_30M` exists for 1,269 of
4,819 games; lineup-posting timestamps exist for **zero** games; the stored
probable pitcher agrees with the actual first-pitch thrower 99.90%/99.92%,
12-41× too clean for a real scratch rate. So the finest honest historical
decision point is `LATE_BOARD`, the starter identity is grade D, and every
historical result prints that exposure. The ladder is defined in full *now* and
captured densely forward so 2026+ replays at the granularity the vision wants.

### 4.6 Market universe: tiers, gates, credits

**The gate on every family is grading, not credits.** You cannot backtest,
settle or self-review a market you cannot grade. G3 is absolute: a family may not
be switched on for paid collection until its settlement rule exists, its result
source is fetchable, and a test grades ten historical examples correctly.

| Family | Gradeable from | Historical | Order |
|---|---|---|---|
| Moneyline, totals (full game) | `mlb_results.csv`, 9,364 games | **replayable** (h2h wired; totals 302,271 rows unread) | T0, free |
| Run line / spreads | same | **never polled — permanently impossible** | forward only |
| F5 ML/RL/total/team total | `first_five_results.jsonl` + Statcast innings | thin (1 snapshot/game) | T1 |
| Team totals, alternates | Statcast / results | never polled | T2 |
| Pitcher props (K, outs, IP, H, ER, BB) | GUMBO boxscore + `pitcher_logs.jsonl` | never polled | T3 |
| Batter props (9 families) | **GUMBO boxscore — free, keyless, backfillable** | never polled | T3 |
| First inning, race-to-X, first-to-score | GUMBO linescore / play-by-play | never polled | T4 |
| Parlays / SGP | product of leg settlements | never | capture only |

| Tier | Content | Credits/day | Gate |
|---|---|---|---|
| **T0** | Persist `all_books` for the 5 discarded keys; L0/L1 dual-write; L1 backfill 2023-25; GUMBO box lines; Open-Meteo archive; park orientations; transactions wiring | **0** | none — do it this week |
| **A** | Featured grid every 15 min over 18h (3 cr flat/slate) | ~216 | envelope constant exists |
| **B** | F5 trio + alternates + team totals, 3 moments | ~270 | G3 per family |
| **C** | 5 pitcher keys + 9 batter keys, 2 moments | ~420 | G3 + owner sign-off |
| — | **~900/day, ~27k/month against ~99,621 measured** | | |

Rejected: the ~7,000-7,600/day full-board hourly plan (~210-228k/month, needs the
5M tier). It buys redundant instants on slow markets with money that could buy
breadth that expires.

### 4.7 Scale plan

The compute is not the constraint and never was; **independent evidence is.**
~2,430 games/season, two discovery seasons ≈ 4,860 games, ~40 selections each ≈
194,000 decisions and roughly **4,860 independent units** — outcomes within a game
are massively dependent and outcomes within a day share weather, umpire pools and
market regime. Ten million decisions over 4,860 games is not ten million
observations; it is 4,860 observations examined ten million ways, which is the
textbook setup for finding something that is not there.

1. **Instrument before optimizing.** `src/core/timing.py` writing
   `{stage, wall_s, cpu_s, rows, decisions, decisions_per_s, peak_rss_mb}`;
   `timings` **required** on every artifact or it is not written. The headline
   "11,088 genomes in 51 ms" (`EVOLAB_DESIGN.md:384`) was never measured — no
   timing field exists in `sweep.py`, `replay.py` or `registry.py`, and the
   1,660,782-byte Phase 2B artifact records no wall clock at all. That run's time
   is permanently unrecoverable; the next one need not be.
2. **Bitsets stay.** Signal firing is a property of the world, not of the system:
   one bigint mask per (feature, rung, side) per world, reused by every system;
   selection is 2-3 bitwise ops and a popcount. Cost is `masks × worlds`, not
   decisions. Add `market_available_mask[family][point_class]` and
   `books_ge_k_mask[selection][k]` or board widening pushes the cost back into
   Python loops and undoes the design.
3. **Do not store decisions — store the recipe.** A decision is a pure function
   of `(engine_version, system_id, registry_fingerprint, frame_fingerprint,
   point_class, game_id)`. Persist one Scorecard per
   (system, world, window, point_class, market) ≈ 3 GB, plus full detail only for
   the published tier. `replay_decision(recipe) -> DecisionRecord` rebuilds any
   one in milliseconds, and a CI job reproduces 1,000 sampled decisions
   byte-identically.
4. **Parallelize worlds** across 4 CPUs with stdlib `multiprocessing` and LPT
   balancing — `scripts/test_parallel.py:135-157` already demonstrates the exact
   pattern. Expect ~3.5×. Each world independently seeded, reassembled in
   canonical order.
5. **Persist frames**; `matrix.py` re-parses full JSONL at 7-11 s/season on every
   invocation. Pay once per data change.
6. **Fix `ReplayUniverse.get()`** — an O(n) linear scan (`replay.py:731-735`)
   beside an unused O(1) `by_id()` dict (`:728-729`).
7. **SQLite** (stdlib) as a derived index for anything that is a query rather than
   a sweep. **DuckDB/numpy only** when instrumented parse+build exceeds 30% of a
   cycle or a cycle exceeds 2 hours on 4 CPUs — with the stdlib-only CI invariant
   explicitly on the table as a cost.

Container baseline, dated and preserved: 15 GiB RAM (707 MiB used), 4 CPUs, no
swap, `data/` 286 MB. Four container restarts in an hour at 0.6 GB of 16 GB in
use — **platform-driven, not load-driven**. Keep that as a named reference so a
future load-driven regime change is detectable rather than re-argued.

### 4.8 Roles

Assigned by cost of being wrong, not by capability tier.

- **Deterministic code — everything that decides, evaluates, grades or governs.**
  `analyze()` and all five phases, every `propose()`, every adversary, pricing,
  de-vig, friction, ratings, LOCK evaluation, staking, settlement, review
  records, calibration, battery, placebo/CSCV/SPA/ceiling, promotion gates, the
  alpha registry, all capture. A model call inside the decision path destroys
  replay equality and with it every guarantee in this document.
- **Sonnet — volume implementation under written contract.** Modules from these
  contracts; tests; per-family settlement adapters; backfills and migrations;
  store audits; the thirty park orientations; **bulk generation of schema-valid
  strategy specs with mechanism strings** for the proposer (never code, never
  free-form claims); narrative summaries *derived from* deterministic
  ReviewRecords.
- **Opus — methodology and adversarial review.** Fitness definitions, placebo
  generator design, promotion floors, the multiplicity policy, LOCK criteria,
  grade downgrades, schema review before a record type is frozen, and
  **adversarial review of any research read before it counts**. Failure here is
  catastrophic and *not* caught by tests: bad methodology produces green tests
  and false champions. The precedent is exactly right — the V3
  `transaction_first_seen` read failed review on nine findings, was corrected,
  and passed a second review. Make it mechanical: a `validator_verdict` field
  that a verdict row cannot be written without, checked at the registry's append
  path.
- **Fable — orchestration and gate-holding.** Drives a real dispatcher
  (`data/factory/queue.jsonl`) so dispatch is a record, not a memory; refuses to
  advance a system whose gate evidence is missing; enforces `DAILY_ENVELOPE` and
  a new `LLM_BUDGET_PER_CYCLE` with the same hard-stop shape as `CREDIT_FLOOR`;
  owns the owner-decision queue. Fable is the only role allowed to be interrupted
  and resumed, which is exactly why the capture cadence must not depend on it.
- **The meta-rule: no model writes to `data/`, `evidence/` or the registry.**
  Models emit proposals; deterministic code validates and appends. Anything a
  model authored that lands in a store carries `provenance: "model"`, `model_id`
  and `prompt_hash`, and is excluded from every evidence path by default.

Today's roster is the exact inversion: six `.claude/agents/*.md`, all
`model: opus`, all execution workers including the hypothesis worker; no Sonnet
role, no Fable role, no dispatcher. Add `sonnet-implementer.md`,
`sonnet-proposer.md` and `fable-orchestrator.md` on the existing
OBJECTIVE/WHY/INPUTS/BOUNDARIES/DELIVERABLE/ACCEPTANCE template; retag
`opus-builder.md` and `opus-data.md` to Sonnet — they are implementation roles
wearing an Opus label, which is both expensive and a misallocation of the review
budget.

---

## 5. Phases and gates

| Gate | Condition |
|---|---|
| **G0 Record conformance** | For 7 days of overlap, the L1 projection reproduces the legacy h2h store row for row |
| **G1 Grade audit** | Every registered input carries a `known_at_grade`; every artifact prints `assumption_exposure` |
| **G2 Budget** | `DAILY_ENVELOPE` is a constant, the drop order is coded, tier/balance reconciled and dated |
| **G3 Settlement-before-collection** | A family has a settlement rule, a fetchable result source, and ten graded examples |
| **G4 Replay equality** | Live `snapshot.fingerprint` reproduces byte-identically from the store afterwards, 7 consecutive days |
| **G5 Ceiling** | A pre-registered cell clears its placebo ceiling at the pre-registered percentile, with effective-tests reported |
| **G6 Forward** | ≥300 forward *selections* carrying book, price, rating, counterarguments and settled CLV; ≥60 ledger days; class A/B |
| **G7 Owner sign-off** | Explicit, dated, after G6 |

| Phase | Weeks | Content | Exit |
|---|---|---|---|
| **0 — Record + waist** | 1-2 | §6 packets | G0 + G1 + G2, and **G4 green 7 consecutive days** |
| **1 — Board** | 3-6 | Families switched on in §4.6 order behind G3; totals replayed end to end; substrate grows from 6 features toward ~40 (bullpen availability at T, transactions, environment, market structure) | ≥6 families LIVE each with a settlement adapter tested on ≥50 games; every new feature registered with mechanism, frozen sign, ladder provenance and grade |
| **2 — The honest re-run** | 6-10 | Re-run the **identical** Phase 2B protocol on the expanded substrate with outcome-calibration as primary fitness | Verdict published **either way**, in the alpha registry, effective-tests beside raw |
| **3 — Factory** | 10-16 | `src/factory/**`, adversaries, co-occurrence store, dispatch, retirement, P7, LLM proposer against H-PROP-1; operators only in unlocked cells | G5 in some cell, **or** the factory publishes that none cleared — both are successes |
| **4 — Forward** | continuous from week 2 | Paper selections toward 300; bankroll accounts; daily self-review | G6 |
| **5 — Product** | after G6 | `ENGINE2` populated, Bet Rating with M+U, LOCK if band monotonicity holds | G7 |
| **6 — Breadth** | continuous from week 1 | Batter props, derivatives, SGP capture — each on its own forward evidence clock | Per family: G3 + registered hypothesis + cost cap before a credit is spent |

Phase 3's exit gate has two acceptable outcomes and that is deliberate. "No cell
cleared its ceiling" is a publishable result, consistent with zero survivors
across four families and the Phase 2B verdict, and it is a *success* of the
machinery. A plan whose only acceptable outcome is an edge is a plan that will
manufacture one.

---

## 6. The first two weeks, as worker packets

Each packet names its owner, inputs, outputs and a mechanical acceptance test.
Drop order if the fortnight runs short: W14 → W13 → W6 slip first. **W1, W4, W10
and W11 never slip** — they are the ones that stop irreversible loss or make the
record countable.

### Week 1 — stop the bleeding, fix the record

**W1 — Stop the discard, write raw first.** *(Sonnet, 1d, 0 credits)*
In: `src/pipeline/snapshots.py:168-192`, `src/providers/odds.py:609-629`.
Out: `multibook_rows` persists `all_books` for all six computed keys; every
capture writes the verbatim payload to `data/raw/oddsapi/...` **before**
projecting.
Accept: a capture writes L0 + legacy + new families; legacy h2h rows
byte-identical to before; **measured zero credit delta** in `credit_log.jsonl`.

**W2 — The universal record.** *(Sonnet, 1.5d)*
Out: `src/board/ids.py` (catalogue, `selection_id`), `record.py`
(`PriceObservation`, `InformationEvent`), `settle.py` (`SETTLEMENT_RULES` table),
`docs/MARKET_CATALOGUE.md`.
Accept: property tests on identity stability (line as string, order-independence,
no float in any id); every catalogue entry has a settlement rule or is explicitly
`collection_blocked`; every existing h2h/spreads/totals/F5 row round-trips with
no loss.

**W3 — Backfill L1 and unlock totals.** *(Sonnet, 1d, 0 credits)*
In: `data/historical/odds_history/*.jsonl` (2023-25).
Out: `src/board/rebuild.py`; L1 rows for h2h **and totals**.
Accept: reconciliation matches the measured counts (2023: 133,330 h2h /
123,224 totals; 2024: 93,724 / 90,534; 2025: 90,458 / 88,513); a deterministic
re-run is byte-identical; a coverage report shows totals instants per game.
**Gate G0.**

**W4 — Knowability.** *(Opus design + Sonnet build, 1.5d)*
Out: `src/knowledge/event.py`, `asof.py`, grade assignment for every registered
input, `grade_audit.jsonl`, path-allowlist and import-guard tests;
`transactions.jsonl` (27,053 rows) added to `pointintime.INPUTS` and projected
into `InformationEvent`.
Accept: probable-pitcher identity is grade **D** and the T-180 lineup assumption
is grade **D**, both printed as exposure counts; `as_of()` cannot open a sealed
path and a test proves it; existing PIT tests still pass. **Gate G1. Owner
decision 3.**

**W5 — Instrument.** *(Sonnet, 0.5d)*
Out: `src/core/timing.py`; `timings` required on every artifact.
Accept: an artifact without `timings` fails validation; a reduced sweep records
per-stage wall clock, CPU and peak RSS; the "51 ms" claim is either confirmed
with a measurement or struck from `EVOLAB_DESIGN.md` with a correction note.

**W6 — The free environment.** *(Sonnet, 1d, Opus reviews the orientation source, 0 credits)*
Out: Open-Meteo `fetch_archive` backfill for 2023-25; `orientation_deg` for all
30 parks with cited sources.
Accept: historical weather coverage report by season; wind resolvable to
in/out/cross for ≥95% of games; new `pointintime.INPUTS` entries with grades
(reanalysis is labelled grade C, honestly).

**W7 — Governance and cadence.** *(Fable + owner, 0.5d)*
Out: `src/capture/budget.py` with `DAILY_ENVELOPE` and the coded drop order;
credit tier/balance reconciled and written into `COLLECTION_POLICY.md` as a dated
fact; the stale "3-4 books" prop figure corrected to the measured 7;
`sonnet-implementer.md`, `sonnet-proposer.md`, `fable-orchestrator.md` added and
the two implementation-shaped Opus roles retagged; **owner repoints the default
branch and adds the `ODDS_API_KEY` repo secret**.
Accept: a simulated over-envelope day drops in the written order and never
touches Tier A; one `forward-capture-bot`-authored commit exists in `git log`.
**Gate G2. Owner decisions 1 and 2.**

### Week 2 — the waist, and a record the gate can count

**W8 — Snapshot and price-blindness.** *(Sonnet, 2d)*
Out: `src/engine/worldview.py` — `Snapshot`, `Section`, grades, `Board`, `Quote`,
`Friction`, `PriceBlindSnapshot`; **recursive** forbidden-name refusal reusing
`genome.py:202`'s walker.
Accept: a nested `{"starter": {"result": ...}}` injection raises; accessing
`.board` on a `PriceBlindSnapshot` raises; all existing evolab tests pass through
an adapter; `Friction` computed for every quoted selection.

**W9 — The waist, with an equivalence proof.** *(Opus contract + Sonnet impl, 2d)*
Out: `docs/ENGINE_CONTRACT.md` (frozen signatures, five purity rules, the
conformance spec); `src/engine/analyze.py`; `GenomeSystem` over `evolab.decide`;
the first four adversaries.
Accept: for all 8,811 Phase 2B genomes on a sampled 200 decision points,
`analyze()` selections equal `decide()` selections **exactly**; determinism holds
under shuffled dict order; the import guard fails on `urllib`, `open`,
`datetime.now`, `random`, `anthropic`, `openai`. **No re-point of `evolab` until
equivalence is green.**

**W10 — Ledger v2.** *(Sonnet, 2d)*
Out: `src/ledger/{decision,settle,review}.py`; identity
`(engine_version, system_id, game_pk, point_class, selection_id)`; required
`book`, `price_american` and non-empty `counterarguments` on any play;
`edge_bps` and `price_improvement_bps` as separate columns with a test that fails
if any path sums them; hash chain with `verify_chain()` in CI; closing threaded
from the sealed partition; `closing_backfill` demoted to a migration-only kind;
the 427 existing rows migrated forward without mutation.
Accept: three decision rows for one game across three point classes; a repeated
tick with an unchanged fingerprint writes nothing; `verify_chain()` green;
`status()` reports forward-selection count against the 300 gate.
**This starts the ≥60-day and ≥300-selection clocks.**

**W11 — The conformance harness.** *(Sonnet, 1d)*
Out: `src/engine/adapters/conformance.py` + a CI-blocking test over a frozen
corpus of real forward rows.
Accept: for ≥50 real `(game, point_class)` rows, the Snapshot rebuilt from the
store afterwards has a fingerprint byte-equal to the one recorded live.
**Gate G4 — and this is the week-2 exit gate: it must run green for 7
consecutive days. If it does not, one of the two assemblers is wrong and nothing
downstream is trustworthy — that is the finding, and it is worth more than any
research result the same fortnight could produce.**

**W12 — Gates and the Two-Ledger Rule.** *(Opus design + Sonnet impl, 1d)*
Out: `config/promotion_gates.json`; `src/factory/{score,promote}.py`;
`objective()` with the AST forbidden-field test; `src/factory/account.py`
simulating 1,000 units day by day.
Accept: the AST test fails when a bankroll field is deliberately introduced; run
against Phase 2B's best genome, `promote()` returns **REFUSED** naming the
specific unmet gates and their current values. **Owner decisions 5 and 6.**

**W13 — Settlement sources.** *(Sonnet, 1.5d, 0 credits)*
Out: MLB StatsAPI/GUMBO readers for boxscore, linescore-by-inning and
play-by-play; forward daily capture plus a 2023-24 backfill of per-game batter
and pitcher box lines.
Accept: a pitcher-K prop **and** a batter-TB prop settle end to end from stored
bytes; ten graded examples per family intended for switch-on. **Gate G3 for the
named families.** This is the grading substrate for the largest market surface in
the vision and it appears on no prior capture list.

**W14 — Switch on Tier B.** *(Sonnet, 1d, ~+270 credits/day)*
Out: F5 trio, alternates and team totals on dense moments only, behind env
switches in the proven `PROP_LISTING_AUDIT`/`PROP_PRICES` pattern, each with its
own narrow registration.
Accept: L1 rows on disk carrying catalogue keys; measured spend within ±15% of
`est_credits`; the floor check runs before every call.
**Gated on W7 (envelope) and W13 (G3).**

**Deliberately not in the two weeks:** no new detectors; no mutation operators
(G5 unmet); no rating (no calibrated model exists, and saying so is the honest
state); no product surface beyond the gate readout; no parlay code; no Tier C
switch-on.

---

## 7. Capture now

Organizing rule: **every price is irrecoverable; every fact about a game is
usually recoverable; every timestamp of when something became knowable is
irrecoverable.** Rank by that, then by cost.

**P0 — free, today**
1. Persist `all_books` for spreads, totals and the three F5 keys. Six families
   computed in memory on every capture (`odds.py:609-629`), one persisted
   (`snapshots.py:177`). Five families of book depth destroyed hourly at **zero**
   marginal credit cost. Highest-leverage single fix in the repository.
2. Write L0 verbatim before projecting. The 2026 season is the only one that will
   ever be captured in the right shape; a projection bug becomes a re-run, a
   capture that projects before it writes becomes a permanent hole.
3. Repoint the default branch and add the `ODDS_API_KEY` repo secret. Zero
   `forward-capture-bot` commits exist; `*/15` cron cannot fire from an orphan
   default branch. Every hour until then rides on an interactive session — the
   exact single point of failure the externalization was written to remove.
4. Keep rosterwatch / umpirewatch / per-tick weather running. Grade A/B brackets
   are the only above-C evidence this project will ever have for lineups,
   probables, transactions and umpires; a missed window is never backfilled.
5. Timing instrumentation on every run.
6. Reconcile the credit balance and tier (53,083 documented vs ~99,621 measured).
   Explainable from vendor billing today; not reconstructable from this repo
   after two more cycles.

**P0 — free, this week**
7. L1 backfill of `odds_history` 2023-25 — **302,271 totals rows become
   replayable.** Largest single increase in usable evidence available at any
   price.
8. **MLB GUMBO per-game batter and pitcher box lines**, forward plus 2023-24
   backfill. Free, keyless. Without it no batter prop can ever be settled,
   backtested or self-reviewed.
9. Open-Meteo `fetch_archive` for 2023-25. Implemented, never called for the
   past. No expiry — but it has been "fetchable later" for a year already.
10. Park `orientation_deg` for 30 parks. Thirty static numbers turn every wind
    observation, past and future, from a speed into in/out/cross.
11. Wire `transactions.jsonl` — 27,053 rows including 1,768 IL placements and
    2,554 activations across 2023-24, complete on disk, referenced by no feature.
    Highest-ROI already-paid-for asset in the repo. Do it before the factory
    searches, or it becomes a re-audit of the probable-pitcher kind.
12. Ledger v2 schema. Every day the current schema runs is a day of forward
    evidence in a shape the 300-selection gate cannot count.

**P1 — cheap, this month**
13. F5 spreads and totals on the named-event pass that already runs; the parser
    exists and has never been asked for them.
14. Denser F5 close coverage — 26 of 73 games today.
15. Alternates and team totals at dense moments — 7 books, 130-160 outcome rows
    per event at 1 credit, the best measured information-per-credit on the board.
16. The T-30m prop repricing slot, roughly half of which is unobserved by
    construction under the current cadence. That evidence is leaking today.

**P2 — budgeted, owner sign-off**
17. Batter props, 9 keys, 2 moments (~270/day). The largest surface with zero
    history, never purchasable retroactively.
18. Pitcher props beyond strikeouts (~150/day).
19. **The SGP source decision, recorded as a dated fact** — can SGP prices be read,
    for which books, at what cost? If not: "not available, checked 2026-09-XX,
    here is the evidence" is a real deliverable. Then prices for *declared leg
    sets* only.

**P3 — operational, free, perishable**
20. The first real firing of `forward-capture.yml` — whether it collides with a
    still-live in-session Routine is a one-time-observable race with no
    cross-host lock.
21. The L16 pinned-read addendum (commit + nine store hashes) — the only worked
    example of a correct pinned read.
22. `OVERNIGHT_RUN.md`'s missed-capture-window log — the sole surviving record of
    when and why capture gaps happened.
23. The container-restart baseline as a named dated measurement.

---

## 8. Owner decisions

1. **Credit envelope.** Raise `DAILY_ENVELOPE` from ~132 to ~900/day (~27k/month
   against ~99,621 measured). This determines how much of the 2026 board exists
   in 2027. Recommend yes; recommend **against** the ~7,000/day full-board plan.
2. **Default branch + repo secret.** This gates more of the vision than any code
   in this document, and every day it waits is a permanently missing day.
3. **Grade C/D policy.** `assert_point_in_time` moves from a decision-time hard
   raise to: excluded by default, explicit opt-in, exposure printed on every
   artifact, promotion still requiring forward A/B. This changes a standing
   refusal and needs your signature.
4. **Primary fitness.** Switching from movement to outcome-calibrated log-loss
   changes what "Phase 2B" means and requires a fresh registration. Phase 2B's
   published verdict stands unamended either way.
5. **Per-cell evolutionary gating**, with cells pre-registered before the sweep
   and cell count charged to `total_searched()`.
6. **The Two-Ledger Rule** — bankroll simulated and published in full,
   structurally excluded from `objective()`.
7. **Stake rule for the paper account**, declared *before* the forward record
   starts: `FLAT_1U`, `FLAT_2U`, or `KELLY_QUARTER_CAPPED_2U`.
8. **The LOCK definition** (§3.7), including that it is falsifiable, that
   `N_LOCK` comes from a power analysis, and that it is withdrawn and published
   the first time band monotonicity fails. Expect zero LOCKs for at least a season.
9. **Batter props** (~270/day). The largest irrecoverable surface; declining is
   not reversible in hindsight.
10. **Backtest scope, stated publicly.** Historical replay covers h2h and totals
    (and thin F5) at two decision points. Everything else is forward-only with a
    2027 first honest verdict. Accepting this in public is what stops a future
    reader expecting a prop backtest that can never exist.
11. **SGP capture** now while parlay research stays blocked. Capture expires;
    research does not.
12. **Prop history purchase** — the vendor sells prop history from ~May 2023 and a
    5-minute historical grid, both priced and gated. Register a hypothesis now or
    accept the permanent gap.
13. **Role roster** — add Sonnet and Fable role files, retag the two
    implementation-shaped Opus workers, add a real dispatcher.
14. **Sport-neutral engine contract from day one.** Near-zero cost now, expensive
    once the factory holds thousands of MLB-shaped systems.
15. **Correction commits** for the believed-but-absent list (the "51 ms" claim,
    the hash chain described in present tense, the RUNBOOK's three unattended
    jobs of which one has code and none has fired, the stale credit balance, the
    "3-4 books" prop figure) — before anything is built on top of them.

---

## 9. Challenges to the owner's description

None of these reduce the vision. Several are the only way it survives contact
with the evidence.

**9.1 "Search the entire board" is only honest with two mechanisms, not one.**
Price-blindness must be structural or "which market best expresses the advantage"
degenerates into "which line looks softest" — which backtests beautifully and is
worth nothing. And ranking must be on **edge net of friction**: prop and
alternate markets carry much wider vig, thinner book counts, staler quotes and
lower limits, so a naive cross-market ranker maximizes measurement error and will
reliably select the widest, thinnest market on the board. Board width without a
friction model is not an opportunity surface; it is a noise amplifier.

**9.2 Most of the board can never be backtested, and pretending otherwise is the
main way this project could fool itself.** Run lines were never polled. Neither
were alternates, team totals, margin, first-inning markets, derivatives, or any
prop. F5 has one snapshot per game (185/133/172 games with any book), which
cannot answer a timing question. What *is* replayable: h2h and — once W3 lands —
totals, at **two** decision-point classes, not four. The right response is not a
synthetic backfill and not silence: the engine is identical everywhere, the
`evidence_window` is declared per family and published, and the forward clock
starts for every family today.

**9.3 Simulated bankroll accounts must be reported, never selected on.** At -110
flat, per-bet SD ≈ 0.995 units; over n=300 the SD of total profit ≈ 17.2 units,
i.e. ROI SD ≈ 5.7 percentage points. A true 2% edge is a third of one standard
deviation. Rank 1,000 zero-edge strategies by season bankroll and the winner
shows ≈ +2.5σ ≈ +14% ROI with near-certainty. Selecting on bankroll at population
scale is not a weak method; it is a machine for manufacturing false champions.
Keep the 1,000-unit day-by-day accounts in full — they are how a human reads
whether a system is livable — and make them structurally unreadable by
`objective()`.

**9.4 "Thousands of competing systems" is a cost, not an asset.** The binding
constraint is ~4,860 independent game-days, not decision count. 8,811 genomes
over six features are not 8,811 independent tests; they are perhaps a few dozen.
Report the effective number of tests from selection overlap alongside the raw
count, always both. And scale the substrate before the population: ten times the
population over the same six features mostly buys better overfitting.

**9.5 "AI-powered" must mean models propose, never decide.** A model call in the
decision path is not reproducible at a past timestamp, which makes "backtest the
analyzer with the exact same decision engine" a sentence that cannot be true.
State the invariant in the product language: models generate hypotheses, write
code, review methodology and draft explanations; deterministic code reads the
store, decides, grades and publishes.

**9.6 A new tension neither design addresses: thousands of systems versus "0..N,
never force quantity."** Those two requirements collide at the population level.
A thousand promoted systems each firing at a pre-registered 4% rate produce
roughly 600 candidates on a 15-game slate, most of them the same handful of
underlying theses re-expressed. "0..N, never forced" is a property of one
system's decision function, not of the daily surface. **The daily surface needs
its own correlation-aware aggregation rule, pre-registered**: candidates are
clustered by selection overlap and evidence lineage, one representative is
published per cluster with its supporting systems listed, and the count of
clusters — not of candidates — is what "N opportunities today" means. Without
that rule, "never force quantity" survives at the system level and dies at the
product level.

**9.7 Parlays are mostly a strictly worse product, and the capture question is
separate from the research question.** For uncorrelated cross-game legs a two-leg
parlay needs roughly twice the per-leg edge to match two singles. The one
falsifiable object is the book's *correlation error* —
`book_implied_correlation` recovered from the SGP price against the product of
the leg prices, compared with your own estimate. That requires a joint
distribution you do not have and may not have for years. Capture now; do not
build a parlay recommender on thresholded legs, ever.

**9.8 LOCK must include price and must be retirable, and it will be empty for a
long time.** Confidence uncorrelated with price is exactly how a
confident-sounding losing product gets built. A threshold-shaped LOCK guarantees
LOCKs exist every day whether or not any are deserved. Publish the base rate;
treat >2% as a defect.

**9.9 "Reconstruct everything legitimately knowable" is not a historical
quantity.** For 2023-24 the starter identity is effectively the actual
first-pitch thrower (99.90%/99.92% agreement, 12-41× too clean) and lineup
posting times exist for **zero** games. So the honest reframe is: the engine
reconstructs what was *recorded as knowable*, and the grade ladder is the
difference between that and the ideal. The 2026 season is grade A/B for the
classes rosterwatch and umpirewatch cover, and that difference in kind is exactly
what "the live season is precious" purchases. Make it measurable — "% of
decision-relevant facts at grade A or B" is a daily store-health metric, ~0% for
2023-24 and should exceed 90% for 2026.

**9.10 "Identical point-in-time conditions" is only literally true under a shared
frame hash.** Two systems evaluated against two different builds of the same
season have not competed. The factory's inputs are a frame fingerprint and a
registry fingerprint, or the claim is approximate.

**9.11 The forward ledger cannot satisfy its own unlock condition, and that
outranks every research task.** Condition 3 is 300+ forward selections. The
ledger holds 144 recommendation rows: 134 no_play, 7 market_unavailable, 3
flagged, **zero selections** — with no rating, no chosen book, no execution
price, no system id, and a one-row-per-game-ever rule that structurally forbids
recording a changed verdict when a lineup posts. Even if an edge appeared
tomorrow, the record being accumulated is not the shape the gate requires.

**9.12 The live season is precious for capture, not for picks.** The marginal
value of a better analyzer this month is small — it will be evaluated on a sample
that cannot reach significance this season. The marginal value of a complete
point-in-time board this month is large and strictly decaying. **For the next 60
days, capture completeness outranks analysis sophistication in every
prioritization conflict.** That is an explicit inversion of the natural instinct.

**9.13 One thing the description gets exactly right, worth protecting.**
"Point-in-time integrity sacred, losers published, price improvement is never EV,
the Ranker publishes nothing until the gates clear." Every one of those is
already load-bearing in code — `ENGINE2 = None` with a test that fails on the
word "edge", `prices.py`'s mandatory label, `pointintime.py` refusing rather than
warning, `replay.py` refusing sealed 2026 by name. Nothing in this synthesis
weakens any of them, and the board expansion must never become a reason to. One
clarification: the gate is a **publication** boundary, not an **engine**
boundary. The engine must always compute the rating and record it, because that
is how the forward record accumulates the evidence the gate requires. Gating the
computation would make the gate unopenable.

---

## 10. What is hard, stated rather than softened

- **Settlement adapters are the silent killer.** A run line, a team total, a
  strikeout prop and a race-to-3 all settle differently, and a wrong settlement
  produces a plausible, confident, wrong backtest that no statistical test
  catches. This is why G3 gates a family on ten graded examples before a credit is
  spent.
- **Prop settlement is a real data-engineering job** — per-player, per-game
  outcomes joined to per-book selections across name/id mismatches, thousands of
  selections a night. Tractable, not small, and required *before* the prices are
  worth collecting.
- **A calibrated probability may never arrive.** Four pre-registered families,
  zero survivors; Phase 2B below the placebo ceiling at pooled percentile 13.3;
  the market's close beats public Elo by 0.008 log-loss at p=0.0003. The
  architecture must be as good at publishing "nothing cleared" as at publishing a
  winner.
- **2023-24 can never earn a promotion.** Grade-C/D knowability, 6-hour median
  snapshot gaps, zero lineup-post timestamps. Discovery there, promotion only
  forward. That is a multi-season timeline no engineering shortens.
- **The forward window is slow by construction.** ≥300 selections and ≥60 ledger
  days per system, across a population, at ~15 games a day, from a system that has
  produced zero selections in 144 rows. Widening the board is the only honest way
  to accelerate it — which is why capture outranks engine work for 60 days.
- **Thin markets may be unanalyzable.** Seven books on a good day for strikeouts,
  three for F5 spreads. De-vig on a two-book market is barely meaningful and
  `MIN_BOOKS = 6` exists for a reason. Several families may turn out not to
  support analysis at all, and that is a finding, not a failure.
- **Multiplicity at factory scale is the real adversary.** Clustering
  near-duplicate systems is an open problem, and it determines whether
  `total_searched()` means anything.
- **Grade-B bracketing is only as good as the polling cadence**, and the cadence
  currently depends on infrastructure that has never been observed to fire on its
  own. A bracket with a six-hour gap is a grade-C fact wearing a grade-B label.

---

*Nothing in this document is evidence. Where a number was found to be unmeasured
— the "51 ms", the "well under an hour", the 53,083 credits, the hash chain, the
three unattended jobs — this document says so rather than repeating it.*
