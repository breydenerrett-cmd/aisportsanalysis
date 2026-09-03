# LINEHOUND — FACTORY-FIRST ARCHITECTURE

**Author:** independent architect pass, 2026-09-03
**Angle:** the Strategy Factory is the primary long-lived system. The MLB
intelligence engine, the market universe, the daily loop and the customer
product are all *consumers* of what the factory has promoted.
**Status:** design. Nothing here is implemented. Read-only pass over the
codebase plus the nine subsystem maps in `docs/planning/map-*.md`.

Standing constraints are load-bearing throughout and are never relaxed:
point-in-time integrity is sacred; 2025 is tuning-only; sealed 2026 is
untouched for reading; losers are published; no real-money bet placement;
never fabricate; price improvement is never EV or edge; the Ranker publishes
nothing while `ENGINE2 is None` until the unlock gates and owner sign-off.

---

## 0. THE ONE-PARAGRAPH ARCHITECTURE

There is exactly one decision function in this system. It takes an immutable
`Strategy` and an immutable `BoardView` — everything legitimately knowable at
a timestamp `T`, features plus the full priced board — and returns a
`Decision` or a refusal with a named reason. Live operation calls it. Historical
replay calls it. Placebo worlds call it. Nothing else may decide anything. Every
other component in the system is either (a) a *supplier* that builds `BoardView`s
honestly, (b) an *evaluator* that scores what the function did across thousands
of strategies and millions of decisions deterministically, (c) a *governor* that
decides which strategies are allowed to exist and which may be shown to a
customer, or (d) a *renderer* that displays what the governor has already
approved. The Strategy Factory is (a)+(b)+(c) running continuously as a standing
research department. The product is (d).

Everything below is the consequence of taking that seriously.

---

## 1. RECONCILIATION — the vision versus what is actually here

The owner's description and the codebase disagree in eight places. Each
disagreement is resolved here in a specific direction, with the reason.

### 1.1 "An AI-powered analysis engine" vs. eleven threshold detectors

The Analyzer today is `src/detect/detectors.py` (934 lines, 11 registered
detectors), each an independent threshold rule producing a `Finding` with a
baseline, a sample size, and a market-relevance flag. `src/pipeline/mismatch.py`
routes two markets through hardcoded logic. That is not a reconstruction engine
and it is not a probabilistic synthesis.

**Resolution: the detectors are not a decision engine, they are a feature
library, and they should be reclassified as such.** A `Finding` with a baseline,
a surprise measured in baseline units, and a sample count is an excellent
*feature extractor*. It is a poor *decider*, because eleven independent
thresholds cannot be combined into a probability and their multiplicity is
uncontrolled. Factory-first says: promote the detector output into the signal
registry as measurable quantities, delete the routing layer's authority to
decide, and let exactly one decision function consume them. The detectors keep
their product role — they are what the Analyzer *shows a reader* — but they stop
being a parallel, ungoverned decision path.

### 1.2 "Simulated daily bankroll accounts" vs. §13's rejection of bankroll fitness

The owner asks for 1,000-unit day-by-day bankroll accounts across whole seasons.
`docs/MASTER_PLAN.md` §13 correctly rejects bankroll tournaments as a *selection*
mechanism, and `docs/EVOLAB_DESIGN.md:199-201` excludes staking and drawdown from
fitness by design.

**Resolution — the Two-Ledger Rule.** Both are right about different objects, and
the system needs both:

- **The Objective Ledger** decides what survives. It contains calibration,
  price-vs-close, robustness across splits, and nothing else. It is structurally
  incapable of reading bankroll fields (enforced the same way `genome.py` refuses
  sign keys — see §6.4).
- **The Account Ledger** is a *reporting* artifact. It simulates 1,000 units,
  day by day, whole seasons, holdouts, and forward paper, exactly as the owner
  describes. It is published. It is how a human sees what a strategy would have
  felt like. It is never an input to survival.

The arithmetic that forces this: at -110, one unit flat, the per-bet SD is ≈0.995
units. Over n=300 bets, the SD of total profit is ≈17.2 units, i.e. ROI SD ≈5.7
percentage points. A true 2% edge is a third of one standard deviation. Rank
1,000 zero-edge strategies by season bankroll and the winner will show roughly
+2.5σ ≈ +14% ROI with near-certainty. Selecting on bankroll at population scale
is not a weak method, it is a machine for manufacturing false champions. The
account ledger is honest as a *description* and catastrophic as an *objective*.

### 1.3 "Thousands of competing systems" vs. multiplicity control

The owner treats population size as an asset. The alpha registry
(`src/research/alpha_registry.py`, 81 rows today) treats every registered
hypothesis as a multiplicity cost and already counts the Phase 2B sweep as one
entry with an internal count.

**Resolution: population size is a cost, not an asset, and must be priced.**
The factory's product is *kills*, not candidates. Every generated strategy
increments `total_searched()`. The correct figure of merit is **evidence per unit
of search**, and a factory that generates 100,000 strategies and promotes one has
a harder statistical burden than one that generates 200 and promotes one. This
does not shrink the vision — run the thousands — it means the FDR accounting must
span the whole population and every artifact must cite `total_searched()` at the
time it was produced. Phase 2B already did this correctly (percentile of the real
maximum against a placebo ceiling, not a p-value on the winner).

### 1.4 "Search the entire board" vs. multiplicity explosion — the biggest correction

See §14.1. Short form: searching forty market families independently for
thresholds multiplies the search space by forty and the evidence by nothing. The
correct architecture is **one belief, many projections**: form a single
probabilistic belief about the game, then *project* it onto every market's payoff
function arithmetically. Board search becomes pricing, not searching.

### 1.5 "Backtest at the correct decision timestamp" vs. what the store can support

The historical odds store has a median of 6 hours between snapshots, a minimum
gap of 177 minutes anywhere, and **zero** games with a recorded lineup-posting
time. `src/evolab/replay.py` already collapsed a designed 4-rung decision ladder
to two classes (`EARLY_BOARD`, `LATE_BOARD`) for exactly this reason.

**Resolution: decision-point class is a first-class dimension of every scorecard,
and scores are never compared across classes.** Historically the finest honest
class is `LATE_BOARD`. Forward from 2026 the 15-minute dense grid supports a real
`T_MINUS_30M` class and, once lineup-post brackets accumulate, a
`POST_LINEUP` class. A strategy discovered at `LATE_BOARD` on 2023-24 and forward
tested at `POST_LINEUP` in 2026 has not been forward tested; it has been tested on
a different instrument. This is stated, stamped, and enforced.

### 1.6 "Reconstruct everything legitimately knowable" vs. the probable-pitcher leak

`docs/AUDIT_PROBABLE_PITCHER_PIT.md` found the stored probable pitcher agrees
with the actual first-pitch thrower 99.90%/99.92% — 12-41× too clean versus a
plausible scratch rate. `replay.assert_point_in_time` consequently raises for all
six registered features. As written, this blocks the entire program.

**Resolution: convert a binary blocker into a graded, stamped exposure.**
Introduce `AvailabilityClass`:

- **A** — the source itself carries the wall-clock moment the fact became
  public (forward `rosterwatch` `fetched_utc` brackets).
- **B** — bracketed by our own observation (we saw it absent at t0 and present
  at t1; truth is in between).
- **C** — date-only or reconstructed; the value is right but the *knowability
  time* is asserted by convention, not recorded (2023-24 probable pitcher,
  archive weather reanalysis).
- **D** — unknown or known-contaminated.

Every feature declares one. Every `Decision` stamps the worst class it consumed.
Every scorecard partitions by class. **Promotion requires the forward window to be
class A/B even when discovery used class C.** That is the honest position: class-C
history is legitimate for *generating* hypotheses and illegitimate for *earning*
promotion. `assert_point_in_time` stops being a hard raise at decision time and
becomes a hard raise at *promotion* time, which is where it actually belongs.

### 1.7 "The live season is precious" vs. "sealed 2026 untouched"

These are not in tension once you separate write from read.

**Resolution — the Write-Only Season.** 2026 is written at maximum fidelity and
is structurally unreadable by anything in `src/factory/` or `src/research/`.
`replay.refuse_sealed` already does this by date. Extend it: the capture layer
(`src/pipeline/snapshots.py`, `dense.py`, `rosterwatch.py`, `umpirewatch.py`,
`weather_capture.py`, prop capture) writes into the sealed window; the factory
cannot open a 2026 store file at all — enforced by a path guard in the store
reader, not by convention.

### 1.8 "Fable orchestrating, Sonnet implementing, Opus reviewing" vs. six Opus files

`.claude/agents/` contains six role files, all `model: opus`, including the
hypothesis worker. No Sonnet role. No Fable role. No dispatcher. Every
"orchestration" event on record is a session narrating manual delegation.

**Resolution:** assign roles by *cost of being wrong*, not by prestige. §11 below.

---

## 2. WHAT EXISTS — the factory's actual assets

Consolidated from the nine maps, ranked by how much of the factory is already
built. These are the load-bearing assets. They are good and most of them should
not be touched except to generalize.

| Asset | Where | Why it matters to the factory |
|---|---|---|
| Structural sign-refusal in genome validation | `src/evolab/genome.py:69-72,202-216` | The single best idea in the repo. A strategy cannot express "I'll figure out the direction from the data." Generalizes verbatim to any forbidden concept — including bankroll in the objective. |
| Frozen per-feature sign in the registry, set once at `register()` | `src/evolab/registry.py:116-244` | Kills the V4/V5 sign-flip failure mode structurally rather than by review. |
| Pure decision function with explicit tie-break and refusal-on-conflict | `src/evolab/decide.py:214-282` | This is already the one engine. It just needs to see more of the world. |
| `WorldView` leak-proofing via `__slots__` + raising `__getattr__` | `src/evolab/decide.py:112-178` | Leakage prevented by construction, not by discipline. The most important pattern to preserve when the board widens. |
| Replay boundary: stop-at-T, refuse-sealed, refuse-non-allowed-seasons | `src/evolab/replay.py:577,188,415-439` | Named refusals before reading anything. |
| Bitset evaluation engine | `src/evolab/bitsets.py` | Sub-linear in selections. This is the reason "millions of decisions" is affordable at all (§10). |
| Six placebo generators + ceiling + CSCV + SPA, with a published negative verdict | `src/evolab/{placebo,ceiling,cscv,spa}.py`, `docs/EVOLAB_PHASE2B_RESULTS.md` | The factory's immune system, already proven to reject its own results (BELOW_PLACEBO_CEILING, pooled percentile 13.3, PBO 0.6111). |
| Two self-caught methodological corrections mid-project | `docs/EVOLAB_DESIGN.md:213-249` | Evidence the machinery actually corrects itself. |
| Pre-registration funnel with structural enforcement, screen→replication→battery→BH-FDR | `src/research/funnel.py:437-679` | The promotion pipeline already exists in miniature. |
| Versioned, fingerprinted falsification battery (5 fatal rules, `RULES_VERSION 2.0.0`) | `src/research/battery.py:34-78,452-465` | Adversarially validated: it originally *passed* the known false positive M3 and was fixed as general rules. |
| Append-only cross-family alpha registry with `total_searched()` | `src/research/alpha_registry.py` | Population-scale multiplicity accounting already exists. 81 rows verified. |
| Point-in-time input registry that refuses rather than warns | `src/model/pointintime.py:1-217` | Data-not-convention. The place `AvailabilityClass` belongs. |
| Rebuilt PIT splits/arsenals from pitch-level Statcast | `src/pipeline/rebuilt.py` | The hard PIT accumulation problem is solved and tested. |
| Grade-B bracketed forward capture (lineups, probables, transactions, umpires) | `src/pipeline/{rosterwatch,umpirewatch}.py` | The only source of class-A/B evidence that will ever exist. Running now. |
| Append-only ledger with `information_time` distinct from write time | `src/pipeline/ledger.py:104-109` | The correct spine for paper recommendations. |
| Credit floor as a hard, tested stop | `src/pipeline/dense.py:62` | Cost control that cannot be argued with. |
| Multi-book board with `observed_utc` + `book_last_update` | `data/processed/odds_multibook.jsonl` (19,487 rows) | Execution realism and staleness research both need this and nothing else provides it. |
| Test-pinned Engine 2 gate | `src/report/ranker.py:33` + `tests/test_ranker.py` | A gate that cannot be removed by accident, only by a failing diff. |

**The honest summary:** roughly 60% of a strategy factory's *hard parts* already
exist — purity, leak-proofing, multiplicity accounting, placebo ceilings, and a
falsification battery that has drawn blood. What is missing is breadth (one
market), the population lifecycle, and the loop that runs it.

---

## 3. PARTIAL — built but inert, or built and narrower than it looks

| Thing | State | Consequence for the factory |
|---|---|---|
| F5 market | Genome schema, routing and `F5_CONDITIONS` fully support it; `feed.py` never sources F5 prices | Every Phase 2B genome that preferred F5 silently fell through. A whole arm of the search space was inert and the results do not say so on their face. |
| Spreads/totals capture | Fetched on every run, persisted raw, **all-books boards built in memory and discarded** (`odds.py:609-629` builds, `snapshots.py:177` persists h2h only) | The single highest-leverage fix in the entire repo. Zero marginal credits. See §12.1. |
| F5 spreads/totals | Keys exist in `EVENT_MARKETS`, parser handles them, `dense._f5_close_pass` never requests them | Fetchable at zero extra code cost, never scheduled. |
| Prop capture | Listing audit live (446 rows, one market key); prices switched on 2026-09-02 (29 rows) | One prop family of ~30. The rest of the live season's prop board is being lost daily. |
| Decision-point granularity | Designed 4-rung, collapsed to 2 | Honest degradation, permanently, for 2023-24. |
| Evolab as "evolution" | Deterministic full enumeration of a fixed space | Correct behaviour given the gate, but the name misleads and the map found it stated as fact in several places. |
| Calibration harness | `src/core/calibration.py` math exists and is tested on synthetic data | Correctly sequenced (no production model to score) but inert. It becomes the promotion gate's arithmetic the moment a strategy emits probabilities. |
| Adversarial review as a gate | One real precedent (V3 `transaction_first_seen` failed on 9 findings, corrected, passed) + `opus-validator.md` | Enforced by orchestrator memory, not by code. |
| Forward capture automation | `forward-capture.yml` merged with `*/15` cron | Cannot fire: the repo's default branch is still the orphan `claude/cowork-session-migration-tn3sx2`. Zero bot-authored commits exist. The hourly cadence still depends on an interactive session — the exact single point of failure the externalization was written to remove. |
| Ledger's closing value | `settlement.closing` is null in every sampled row; the real value lives in 210 separate `closing_backfill` rows joined at read time | Price-vs-close is a promotion dimension. It cannot be computed reliably from a field that is always null. |
| Transactions/injuries | 27,053 rows on disk covering the full 2023-24 window | Wired into nothing. Highest-ROI already-paid-for asset found anywhere. |

---

## 4. BELIEVED BUT ABSENT — the corrections that must land before anything is built on top

These are stated as fact somewhere in the repo and are not true. Each needs a
correction commit, not a workaround.

1. **"Evolab" is not evolutionary.** No mutation, crossover, generational
   population, elite pool, islands, or immigrants exist anywhere in
   `src/evolab/*.py`. It is a deterministic enumerator over a fixed space
   (`genome.py:466-567`). The absence is *correct* — operators are gated on
   clearing a placebo ceiling that Phase 2B did not clear — but the name and
   several prose references imply otherwise.
2. **"11,088 genomes sweep in 51 ms"** (`EVOLAB_DESIGN.md:384`) and **"well under
   an hour end to end"** (`:398`) were never measured. No timing field exists in
   `sweep.py`, `replay.py` or `registry.py`, and the Phase 2B REAL artifact
   (1,660,782 bytes) records no wall clock at all. The project's most important
   run has never had its runtime measured — which also means the DuckDB
   deferral's own stated exit criterion ("only if wall-clock becomes the
   bottleneck") is currently unmeasurable.
3. **The hash-chained recommendation ledger** is present-tense design language in
   `MASTER_PLAN.md:770`. No hash chain exists in code. `ledger.py` is append-only
   JSONL, which is a different and weaker property.
4. **`docs/RUNBOOK.md`'s "what runs on its own" table** lists hourly capture, a
   daily 10:00 UTC loop, and a 4-hourly build loop as live unattended
   automation. Only hourly capture has any workflow code, and it has never fired.
   The daily loop and build loop have no scheduled trigger of any kind.
5. **Fable and Sonnet roles do not exist.** Six Opus role files, no dispatcher.
   Every reference to "Fable orchestrating" is a session narrating its own day.
6. **`COLLECTION_POLICY.md` prices its entire envelope off 53,083 credits
   (2026-08-31).** `credit_log.jsonl` shows ~99,634 remaining at 2026-09-03. The
   policy document is stale by ~46,551 credits, i.e. the constraint everyone is
   reasoning under is roughly half of the real one.
7. **"Alternate spreads/totals: 7 books at 1 credit"** reads as an established
   capability. It is a one-off 24-credit manual probe recorded in prose. No
   market key exists in `SUPPORTED_MARKETS`.
8. **"Pitcher strikeouts: 3-4 books"** in the policy doc was superseded five days
   later by the project's own better measurement of 7 books
   (`PROBE_PROP_LISTING.md:344-350`). The policy doc was never corrected.
9. **`settlement.closing`** exists in the schema and is null everywhere.
10. **Bet Check integration, a season-end module, and a CI scorecard for evolab**
    have zero code footprint despite being referenced as evolab concerns.
11. **The Phase-1 gate "a research read is valid only if pinned and reviewed"** is
    described in `ORCHESTRATION_DAY_2026-09-02.md` as having been added to the
    master plan. Nothing enforces or checks it; the same document later concedes
    this.
12. **`pointintime.py` marks starter-related inputs CLEAN**, which the registry
    only defines as cutoff-respecting accumulation — a strictly weaker claim than
    "the pitcher's identity was knowable at T". The audit flags the distinction;
    the registry does not encode it. `AvailabilityClass` (§1.6) is the encoding.

**Rule going forward:** any artifact that states a performance number must carry
the measurement that produced it, in the same file, or the number is deleted. §12
makes this mechanical.

---

## 5. BOOST VS REPLACE

The default is BOOST. This codebase is unusually disciplined and its abstractions
mostly generalize. Six things genuinely need replacing, and they are all
*narrowness*, not *wrongness*.

### REPLACE (six, precisely scoped)

| Target | Why replace | Replacement |
|---|---|---|
| `src/pipeline/mismatch.py::route_market` / `scan_game` | Hardcoded two-market, two-signal routing is structurally the opposite of "search the whole board" | `board.project(belief, board_view) -> [MarketCandidate]` — deterministic projection, no per-market search |
| `src/pipeline/ledger.py` one-row-per-game-ever dedup (`:62-79`) | Blocks representing line movement, lineup-driven verdict changes, and multiple competing strategies on the same game — all three are core to the vision | Identity becomes `(game_pk, strategy_id, decision_instant)`. Append-only and settlement-separate are kept unchanged. |
| `src/pipeline/grading.py` settle-time closing computation | Produces null closings and needs a 210-row repair table | Thread real closing from `odds_multibook.jsonl` into `settlement.closing` at settle time; keep `closing_backfill` as an explicitly-labelled stopgap for the historical rows |
| `src/research/scoreboard.py` | Its unit of account (hypotheses screened/killed/survivors) has no room for calibration, CLV, bankroll or rating | New adjacent `src/factory/score.py`. `scoreboard.py` stays for what it does well. |
| `src/research/funnel.py::MARKETS = ('h2h',)` | A single hardcoded market string is the one place in the research machinery that is shaped wrong rather than merely narrow | A real market dimension carrying per-family pricing and settlement adapters (§7) |
| `src/model/selections.py::_fair()` two-way-only | Cannot express a total, a line, or a prop | Per-family fair-price adapters. Its PIT and clean-detector guardrails are untouched. |

### BOOST (everything else) — the highest-value five

1. **`src/evolab/registry.py` + `genome.py`** — the sign-freeze and forbidden-key
   architecture is the best thing in the repo. Add features and markets; do not
   restructure. Six modules, 3-rung ladders, `MAX_SIGNALS=3` all scale.
2. **`src/evolab/decide.py` + `bitsets.py`** — pure, fast, proven at 8,811
   genomes. Extend the mask table for new markets; do not rewrite.
3. **`src/research/battery.py`** — versioned, fingerprinted, adversarially
   validated. Its row schema already accepts optional book/price keys, so
   policy-grading checks are additive.
4. **`src/research/alpha_registry.py`** — append-only ledger plus
   `total_searched()` is exactly right for factory scale. Add a similarity/cluster
   field; do not redesign. (`semantic_hash_v0` only catches exact atom-set
   duplicates — that is a known, documented gap, not a bug.)
5. **`src/pipeline/{rosterwatch,umpirewatch,weather_capture}.py`** — bracketing
   design is correct and tested. Extend to more event classes (reliever
   availability, roof state when a feed appears).

---

## 6. EVOLAB → STRATEGY FACTORY

### 6.1 Target package layout

```
src/board/                      NEW — the market universe
  identity.py                   MarketKey, Selection, Quote, canonical keys
  catalog.py                    MARKET_CATALOG + per-family status/gates
  adapters.py                   per-family de-vig, fair price, settlement
  frame.py                      BoardFrame: all markets x books x instants, per season
  view.py                       BoardView: the leak-proof slice at T

src/factory/                    NEW — the standing research department
  strategy.py                   Strategy (generalized evolab.genome.Genome)
  registry.py                   signal/feature registry (from evolab.registry)
  decide.py                     THE decision function (from evolab.decide)
  generate.py                   enumerate | mutate | crossover | ingest proposals
  proposer.py                   LLM proposal ingestion — schema only, never code
  evaluate.py                   deterministic mass evaluation (from evolab.bitsets/sweep)
  score.py                      Scorecard: the Objective Ledger
  account.py                    bankroll simulation: the Account Ledger
  attack.py                     per-strategy adversarial battery (wraps research.battery)
  lifecycle.py                  states, transitions, promotion/retirement gates
  population.py                 the standing population store + graveyard
  cycle.py                      the nightly GENERATE->...->PROMOTE orchestrator
  timing.py                     required wall-clock instrumentation

src/evolab/                     BOOSTED IN PLACE then migrated by equivalence test
src/research/                   unchanged; the statistics library the factory calls
```

`src/evolab/` is not deleted. The migration is: build `src/factory/decide.py` as a
generalization, then prove `factory.decide(strategy, view) == evolab.decide(genome,
worldview)` byte-identically on the full 8,811-genome Phase 2B corpus, then
re-point `evolab` to the factory implementation and keep its public names as
aliases. A rewrite that cannot reproduce Phase 2B exactly is a rewrite that has
silently changed the science.

### 6.2 The Strategy contract

```python
@dataclass(frozen=True)
class Strategy:
    """An immutable, versioned decision policy. Content-addressed."""
    strategy_id: str            # sha256 of canonical_json(spec); stable forever
    spec_version: str           # grammar version this was validated against
    lineage: tuple[str, ...]    # parent strategy_ids; () for enumerated/proposed
    origin: str                 # ENUMERATED | MUTATED | CROSSED | PROPOSED_LLM | HAND
    eligibility: Eligibility    # scope, season, decision-point class, coverage floors
    signals: tuple[Signal, ...] # <= MAX_SIGNALS, each (feature, rung); sign from registry
    combination: Combination    # weighted_sum | k_of_n
    entry: Entry                # score floor, min confirmations
    routing: Routing            # ordered MarketKey preferences + execution mode
    sizing_class: str           # FLAT_1U only, until a sizing study is registered
    rating_class: str           # which rating decomposition this strategy emits
    availability_floor: str     # minimum AvailabilityClass this strategy will act on
```

Preserved verbatim from `genome.py`: `FORBIDDEN_KEYS` refusal at any depth, the
requirement that weights be strictly positive, the fact that direction lives only
in the frozen registry, and `strategy_id` as a content hash so two identical
strategies from different origins are literally the same object.

Added: `lineage` and `origin` (needed for operators and for proposer measurement),
`sizing_class` and `rating_class` (product surfaces), `availability_floor` (§1.6).

### 6.3 The decision contract — the one engine

```python
def decide(strategy: Strategy, view: BoardView, *,
           registry: SignalRegistry = DEFAULT_REGISTRY) -> Decision | NoPlay: ...

def decide_with_reason(strategy, view, *, registry=DEFAULT_REGISTRY
                       ) -> tuple[Decision | NoPlay, str]: ...

@dataclass(frozen=True)
class Decision:
    strategy_id: str
    engine_version: str          # bumped on ANY change to decide() semantics
    decision_utc: str            # == view.T; never the wall clock of the run
    point_class: str             # EARLY_BOARD | LATE_BOARD | T_MINUS_30M | POST_LINEUP
    selection: Selection         # market family, scope, subject, side, line
    execution: ExecutionQuote    # book, price, mode, quote timestamp, gap minutes
    score: float                 # the combination's output, not a probability
    fired: tuple[str, ...]       # feature@rung identifiers that fired
    availability_class: str      # WORST class consumed — A/B/C/D
    worldview_digest: str        # sha256 of the canonicalized view
    decision_digest: str         # sha256 of this record minus itself
```

Refusal reasons are named constants and are recorded, never swallowed:
`NO_LINEUP`, `MARKET_UNAVAILABLE`, `INSUFFICIENT_BOOKS`, `NOT_SIMULTANEOUS`,
`NO_SIGNAL`, `BELOW_ENTRY`, `CONFLICTING_SIGNALS` (all exist today), plus
`BELOW_AVAILABILITY_FLOOR`, `UNSETTLEABLE_MARKET`, `STALE_QUOTE`.

**"0..N opportunities per day, never force quantity" is a property of this
function, not a post-filter.** A day on which every strategy refuses is a valid
day and is published with the refusal histogram. The *no-play rate* is a monitored
statistic per strategy: a strategy whose no-play rate collapses is drifting and
gets flagged before its returns do.

### 6.4 The Objective Ledger and the forbidden-field trick

```python
@dataclass(frozen=True)
class Scorecard:
    strategy_id: str
    window: str                  # DISCOVERY | REPLICATION | TUNING_2025 | FORWARD
    point_class: str
    market_key: str
    n_decisions: int
    n_independent_clusters: int  # game-days, not decisions — see §10.4

    # --- objective dimensions ---
    logloss_vs_market: float     # calibrated log-loss improvement vs the price
    brier_vs_market: float
    calibration_bins: tuple      # reliability curve, per band
    price_vs_close_cents: float  # advisory, never sufficient alone
    price_vs_close_probpoints: float
    realized_return: float
    realized_return_ci: tuple    # clustered bootstrap, block >= 7 days
    stability: dict              # per-season / per-book / per-month / per-regime splits
    dependence_on_top5: float    # fraction of profit from the 5 largest wins
    price_sensitivity: dict      # effect at threshold x0.8 and x1.25
    placebo_percentile: float    # where the real value sits in the null distribution
    battery: dict                # per-rule pass/fail, rules_fingerprint
    cscv_pbo: float
    spa_p: float
    total_searched_at_read: int  # alpha_registry.total_searched() when scored

    # --- ACCOUNT LEDGER: reported, never optimized ---
    account: AccountSummary      # units, bankroll path, max drawdown, vol

FORBIDDEN_OBJECTIVE_FIELDS = frozenset({
    "account", "bankroll", "units", "drawdown", "roi_units", "profit_units",
})

def objective(card: Scorecard) -> float:
    """The single scalar the factory ranks on. Structurally cannot read money."""
```

`objective()` is validated by the same mechanism `genome.py` uses for sign keys: a
test walks the AST of `src/factory/score.py::objective` and fails if any
`FORBIDDEN_OBJECTIVE_FIELDS` name appears. The Two-Ledger Rule stops being a
policy anyone has to remember.

### 6.5 Lifecycle — GENERATE → TEST → SCORE → ATTACK → RETIRE → MUTATE → RETEST → FORWARD → PROMOTE

```
PROPOSED ──register()──► REGISTERED ──screen(2023)──► SCREENED
                              │                          │
                         (fails)                    replicate(2024)
                              ▼                          ▼
                          GRAVEYARD ◄──attack()──── REPLICATED
                              ▲                          │
                              │                     battery + placebo ceiling
                              │                     + CSCV + SPA + adversarial
                              │                          ▼
                              │                    CEILING_CLEARED
                              │                          │
                              │                     tune params on 2025 only
                              │                          ▼
                              └──demote()──────── FORWARD_TESTING ──(>=300 decisions,
                                                       │             >=60 ledger days,
                                                       │             class A/B, gates §27)
                                                       ▼
                                                   PROMOTED ──drift──► DEMOTED
```

Every transition is a row in `population.jsonl`, append-only, with cause. The
graveyard records **cause of death** and — this is the part that compounds —
**dead branches are pruned from the generation grammar** so the factory stops
re-proposing them. Pruning is itself a registered act: pruning the grammar changes
`total_searched()` semantics and must be recorded.

### 6.6 Generation operators — and the gate correction

Operators (`mutate`, `crossover`, elite pool, islands, immigrants) do not exist
today because Phase 2B did not clear the placebo ceiling, and the project's rule
is that they should not exist until it does. That rule is right and stays.

**But the gate is scoped wrong.** Phase 2B tested *movement fitness* on *h2h
moneyline* with *six lineup-composition features*. It failed. The current gate
treats that as a global prohibition on evolutionary search forever. It should be
per-`(market family, fitness dimension, feature class)`:

> Evolutionary operators unlock within a cell of (market family × fitness
> dimension) when *any* enumerated strategy in that cell clears its placebo
> ceiling at the pre-registered percentile. A failure in
> (h2h, movement, lineup-composition) does not gate (F5 totals, calibration,
> bullpen-workload).

This is not a loosening. It is the same rule applied at the granularity the
evidence actually has. A blanket gate derived from one cell is over-generalizing
from a single negative result — exactly the error the battery exists to catch.

### 6.7 The proposer, and the null it must beat

`src/factory/proposer.py` accepts LLM-generated **schema-valid strategy specs
with mechanism strings**. It never accepts code, never accepts free-form claims,
and never writes to any store — it emits candidates that `strategy.validate()`
either accepts or rejects, and `population.register()` appends.

The proposer is itself a registered experiment with a stated null:

> **H-PROP-1 (pre-registered):** strategies proposed by an LLM that has read the
> graveyard do not outperform grammar-enumerated strategies, per unit of
> `total_searched()`, on `objective()` over the discovery window.

If the null holds, the proposer is retired and enumeration is cheaper. The
`origin` field on `Strategy` is what makes this measurable at all, which is why
it is in the contract from day one.

---

## 7. MARKET-UNIVERSE EXPANSION

### 7.1 Identity — the universal concepts, made concrete

```python
@dataclass(frozen=True)
class MarketKey:
    family: str    # MONEYLINE RUN_LINE TOTAL TEAM_TOTAL MARGIN
                   # PITCHER_KS PITCHER_OUTS PITCHER_ER BATTER_HITS BATTER_TB
                   # BATTER_HR BATTER_RBI BATTER_RUNS BATTER_BB BATTER_KS BATTER_SB
                   # H_R_RBI RACE_TO_X FIRST_TO_SCORE
    scope: str     # FULL_GAME FIRST_FIVE FIRST_INNING INNING_N
    subject: str   # "GAME" | "TEAM:AWAY" | "TEAM:HOME" | "PLAYER:<mlbam_id>"
    variant: str   # MAIN | ALT
    def canonical(self) -> str: ...   # "TOTAL/FIRST_FIVE/GAME/MAIN"

@dataclass(frozen=True)
class Selection:
    key: MarketKey
    side: str            # AWAY HOME OVER UNDER YES NO
    line: float | None   # -1.5, 8.5, 5.5 Ks; None for two-way ML

@dataclass(frozen=True)
class Quote:
    selection: Selection
    book: str
    price_american: int
    observed_utc: str
    book_last_update: str | None
    source: str          # featured | per_event | props
```

### 7.2 The catalog and its gate

```python
@dataclass(frozen=True)
class MarketFamilySpec:
    family: str
    status: str           # PRICED_LIVE | FEASIBILITY_PROBED | NAMED_ONLY | UNAVAILABLE
    endpoint: str         # featured | per_event
    credit_shape: str     # "3/slate" | "1/market/event" | ...
    books_observed: int | None
    devig: str            # method id — a registered parameter, not a default
    settle: str           # settlement adapter id
    correlation_group: str  # for parlay/SGP dependence
    probe_row: str | None   # citation for the feasibility measurement
```

**Promotion gate for a market family** — a family may not become `PRICED_LIVE`
without all four:
1. a feasibility probe row on disk (not prose) recording books and credit cost;
2. a settlement adapter with tests against at least 50 known historical games;
3. a de-vig method named and registered (a total does not de-vig like a
   moneyline; a prop with a single book does not de-vig at all);
4. a credit line item inside the declared daily envelope.

This is what stops the board expansion from becoming forty half-wired markets.
The two families that have been through something like this already (F5 h2h,
pitcher strikeouts listing) are the template.

### 7.3 The state of the board today, and the order to open it

| Family | Status now | Credits | Order |
|---|---|---|---|
| MONEYLINE/FULL_GAME | PRICED_LIVE, all books | in the 3/slate | — |
| RUN_LINE, TOTAL /FULL_GAME | fetched, **all-books discarded** | 0 marginal | **1st — free** |
| MONEYLINE/FIRST_FIVE | PRICED_LIVE, 5 books | ~1/event/moment | — |
| RUN_LINE, TOTAL /FIRST_FIVE | keys exist, never requested | ~1/market/event/moment | 2nd |
| ALT RUN_LINE, ALT TOTAL | probed once manually (7 books, 130-160 rows/event, 1 credit) — best measured information-per-credit on the board | ~1/event/moment | 3rd |
| TEAM_TOTAL | never probed, not even named | unknown | 4th (probe first) |
| PITCHER_KS | listing live, prices live since 2026-09-02 | 18/day capped | — |
| PITCHER_OUTS/IP/H/ER/BB | not named | ~1/market/event | 5th |
| BATTER_* (9 families) | not named anywhere | ~1/market/event — the expensive tier | 6th |
| MARGIN, RACE_TO_X, FIRST_TO_SCORE, INNING_N | zero references in repo | unknown | 7th (probe) |
| PARLAY / SGP | zero code | unknown | **capture only** — research blocked (§14.1) |

### 7.4 Credit budget

Measured facts: balance ~99,634 (2026-09-03, `credit_log.jsonl`); floor 5,000
hard-coded and tested; approved envelope ~132/day; featured endpoint 3 credits
flat per slate; per-event billing is markets × regions × events. Full-board
estimate from the odds map: ~7,000-7,600/day (~210-228k/month), which needs the 5M
tier (~$119/mo).

Proposed envelope ladder, each rung an owner decision:

| Rung | Content | Credits/day | Months of runway at 99.6k |
|---|---|---|---|
| E0 (today) | baseline + F5 h2h | ~132 | ~25 |
| **E1** | + all-books persistence for spreads/totals/F5 | ~132 (unchanged — it is free) | ~25 |
| **E2** | + F5 spreads/totals + alternates on dense moments only | ~250-350 | ~10 |
| E3 | + team totals + pitcher props beyond Ks | ~700-900 | ~4 |
| E4 | + batter props (9 families × 15 games × 3 moments ≈ 405/day alone) | ~1,500-2,000 | ~2 → **tier upgrade required** |
| E5 | full board, hourly + dense | ~7,500 | weeks → **5M tier** |

E1 is free and should ship this week. E2 is the recommendation for the next two
weeks and is comfortably inside the *real* balance even though it exceeds the
*stale* documented envelope — which is precisely why §12.11 (reconcile the balance)
is a capture-now item.

---

## 8. THE DAILY LOOP

One loop, running all day, calling one engine, writing one ledger. Times are
relative to first pitch of each game, not to the clock.

```
T-8h    slate open        pipeline.slate            free
                          board.frame.build()       — assemble BoardFrame from stores
                          rosterwatch tick          free
T-8h..T-25m  every 15m    dense capture             1-3 cr/moment (existing grid)
                          rosterwatch + umpirewatch + weather tick   free
        ON EVERY CAPTURE MOMENT:
                          view = board.view.at(game, T)          # leak-proof slice
                          for s in population.active():
                              d = factory.decide(s, view)
                              ledger.record(d or refusal)        # one row per (game,strategy,T)
T-25m   close pass        dense._close_pass          existing
T-0     first pitch       ledger freezes; no row may carry decision_utc >= commence
final   settlement        board.settle(selection, boxscore) -> WIN|LOSS|PUSH|VOID
                          ledger.settle(...)  + real closing threaded in
+1h     self-review       pipeline.review.run(date) -> ReviewRow per decision
nightly factory cycle     factory.cycle.run()        deterministic, no models
```

### 8.1 Why multiple rows per game is the whole point

Today `ledger.py:62-79` enforces one row per game ever. That single rule makes it
impossible to represent (a) line movement, (b) a lineup posting changing the
verdict, (c) two strategies disagreeing, (d) the same strategy firing early and
refusing late. All four are explicitly in the vision. The identity becomes
`(game_pk, strategy_id, decision_instant)`. Append-only and
settlement-never-mutates-recommendation are unchanged — they are the good parts.

### 8.2 The recommendation record (extended, additively)

Existing fields stay (`kind`, `recorded_at`, `information_time`, `date`,
`game_pk`, teams, `commence_time`, `verdict`, `side`, `market`, `summary`,
`books`, `prices`, `lineup_status`, `findings`, `sections_present`, `gaps`).
Added:

```python
    "strategy_id": str,
    "engine_version": str,
    "decision_instant": str,       # == information_time; the T the engine saw
    "point_class": str,
    "selection": {...},            # full MarketKey + side + line
    "execution": {"book", "price_american", "mode", "quote_utc", "gap_minutes"},
    "rating": {"P": float|None, "E": float|None, "M": None, "U": None,
               "composite": None, "band": str|None},
    "counterarguments": [{"claim", "evidence_label", "sample_n"}],
    "supporting_systems": [strategy_id, ...],   # other strategies agreeing
    "availability_class": "A"|"B"|"C"|"D",
    "refusal_reason": str|None,
    "worldview_digest": str,
    "decision_digest": str,
```

`rating.M` is `None` until a promoted strategy exists. That is not a placeholder,
it is the honest state, and the product renders its absence (§13).

### 8.3 End-of-day self-review — structured, not narrated

```python
@dataclass(frozen=True)
class ReviewRow:
    kind: str                      # "review"
    date: str
    game_pk: int
    strategy_id: str
    decision_digest: str
    thesis: str                    # the mechanism string, copied from the strategy
    thesis_outcome: str            # CONFIRMED | REFUTED | UNTESTED | VARIANCE
    mechanism_checks: tuple        # [{name, expected, observed, verdict}]
    market_path: dict              # entry, close, move_toward_us_cents, clv_prob_points
    information_delta: tuple       # [{event, first_seen_utc, after_decision: bool}]
    lineup_delta: dict             # confirmed vs assumed at decision time
    bullpen_delta: dict            # availability that changed after decision
    counterargument_realized: tuple
    population_action: dict        # {action: NONE|WATCH|DEMOTE|RETIRE, reason}
    new_hypothesis: dict | None    # {registered_id} if one was registered
```

**The discipline that makes this worth doing:** `thesis_outcome` is *computed*
from `mechanism_checks`, not written. Prose is a rendering of the structured
fields, never a substitute. A self-review that lets a model write "the thesis was
correct, variance beat us" in free text is a machine for laundering losses into
confidence. `VARIANCE` is only assignable when the mechanism checks confirmed and
the outcome disagreed — which makes it a measurable rate rather than an excuse.

This also answers "market moved toward or away from us": `market_path` is
computed from the multibook store, in probability points after de-vig, and is
advisory only — price-vs-close is never sufficient for promotion (§27) and price
improvement is never EV.

---

## 9. REPLAY: THE EXACT SAME ENGINE, NO FUTURE LEAKAGE

### 9.1 The identity requirement, made testable

The vision says replay must run the *exact same decision engine*. That is
unfalsifiable unless it is a test. It becomes one:

> **The Replay Identity Test** (`tests/test_engine_identity.py`, CI-blocking).
> Take a frozen corpus of real forward ledger rows. For each, rebuild the
> `BoardView` from the stores using only the recorded `information_time`.
> Re-run `factory.decide()`. Assert `decision_digest` equality, byte for byte.
> Any divergence is either a leak or a code fork, and both are failures.

The corpus is checked in as a fixture with store fingerprints. When
`engine_version` legitimately changes, the corpus is regenerated in the same
commit and the diff is visible. This is the single most valuable test the project
can own, and it is cheap: `worldview_digest` and `decision_digest` already exist
in `replay.py:1051,1067`.

### 9.2 Seven layers of leak control

| # | Layer | Mechanism | Status |
|---|---|---|---|
| L1 | **Structural blindness** | `BoardView.__slots__` + `__getattr__` raising on forbidden names, checked at construction. Forbidden set extended from outcomes to *any* post-decision price field: `close`, `closing`, `final`, `settled`, `result`, `settlement` | exists for outcomes (`decide.py:112-178`); extend |
| L2 | **Temporal filter at the store boundary** | Every read goes through `as_of(store, T)` which filters on the store's own `information_time`/`observed_utc` and **raises if the store has no such field**. No store without a time column may be read by the factory | new |
| L3 | **Availability class** | Every feature declares A/B/C/D; the decision stamps the worst class consumed; promotion requires forward class A/B (§1.6) | new; replaces the current hard raise |
| L4 | **Sealed-window refusal** | `refuse_sealed` by date, plus a path guard: the factory's store reader cannot open a file whose season is 2026 | date guard exists (`replay.py:415-439`); add path guard |
| L5 | **Stop-not-skip iteration** | `iter_instants_through(game, T)` *stops* at T rather than filtering — a filter can be bypassed by a later `.get()`, a stop cannot | exists (`replay.py:577`) |
| L6 | **Negative controls** | Six placebo generators + ceiling/CSCV/SPA. **Add P7, the time-shift placebo:** re-run the engine with T advanced by +2h. If `objective()` improves materially, a leak is the leading hypothesis | 6 exist; P7 new |
| L7 | **Provenance stamping** | Every artifact carries git commit, store fingerprints, engine_version, spec hash, seed, `total_searched()` at read | exists (`replay.store_fingerprints`, `ReplayManifest`) |

L6/P7 is worth spelling out because it is the only *empirical* leak detector on
the list. Every other layer prevents a leak we thought of. P7 detects leaks we
did not, by exploiting the fact that a genuine edge should degrade — not improve —
when you hand the engine two extra hours of information it should not be able to
use. It is cheap: it is one more world in an already-parallel sweep.

### 9.3 What replay honestly cannot do, and the consequence

- **2023-24 decision timestamps are class C.** Probable pitcher agreement is
  99.90%/99.92% against the actual first-pitch thrower — 12-41× too clean.
  Lineup-posting time exists for **zero** games. The finest honest historical
  decision point is `LATE_BOARD`.
- **Therefore:** 2023-24 replay generates hypotheses and kills them. It cannot
  promote anything. Promotion requires the forward class A/B window. This is a
  hard rule in `lifecycle.py`, not a caution in a doc.
- **2025 is tuning-only** and is the right place for exactly three decisions that
  should not be made on discovery data: the de-vig method, the decision-point
  class boundaries, and the execution-realism parameters. Using it for anything
  else contaminates it.

---

## 10. SCALING TO MILLIONS OF DECISIONS, CHEAPLY

### 10.1 The arithmetic that makes this tractable

Naive: 20,000 strategies × 4,860 games × 12 market expressions × 51 worlds ≈
59.5 billion decision evaluations. That is not what gets computed.

The bitset engine (`src/evolab/bitsets.py`) precomputes, **per world**, one
integer bitmask per `(feature, rung, side)` — today 36 masks (6 features × 3 rungs
× 2 sides) over a 4,860-game universe, i.e. 608-byte Python ints. A strategy's
selection set is 2-3 `&`/`|` operations on those ints. Evaluation is then a sum
over set bits only.

So the real cost is:

```
per world:  mask_build   = O(games x features x rungs)            ~ 10^5 ops
            strategies   = 20,000 x 12 markets x ~3 bigint ops    ~ 7.2 x 10^5 bigint ops
                           on 608-byte ints                        ~ seconds
            settlement   = O(total selected decisions)             ~ the actual cost centre
total:      51 worlds  x  the above
```

The cost is **linear in worlds and sub-linear in strategies**. That inversion is
the reason "thousands of systems" is affordable and "fifty-one placebo worlds" is
the budget line. Widening the board multiplies mask count by market families;
widening the population is nearly free.

### 10.2 Six concrete moves

1. **Instrument first.** `Timings` becomes a *required* field on every
   `SweepReport` and replay artifact, with per-stage wall clock. This retires the
   never-measured "51 ms" claim (§4.2) and, more importantly, makes the DuckDB
   deferral's own exit criterion measurable for the first time.
2. **Persisted board frames.** `BoardFrame` is built once per
   `(season, store_fingerprint)` and memoized to disk keyed by that hash. Today
   `matrix.py` re-parses full JSONL every invocation at 7-11s/season and pays it
   again on every sweep. Pay once per data change.
3. **Parallel worlds.** 4 CPUs, `multiprocessing` (stdlib), LPT balancing — the
   exact pattern `scripts/test_parallel.py:135-157` already demonstrates for
   test sharding. Expect ~3.5×. Determinism preserved because each world is
   independently seeded and results are reassembled in canonical order.
4. **`ReplayUniverse.get()` one-line fix.** It is an O(n) linear scan
   (`replay.py:731-735`) sitting next to an unused O(1) `by_id()` dict
   (`:728-729`). Harmless at 4,800 games, an O(n²) trap at multi-season
   multi-sport scale.
5. **Market masks.** Extend the mask table with `market_available_mask` and
   `books_ge_k_mask` per market family so "is this market priced with enough books
   at this instant" is a bit test, not a dict lookup per decision.
6. **Columnar mirror stays deferred, with a trigger.** The repo is stdlib-only
   and CI enforces it (`tests.yml` fails if `requirements.txt` exists). `data/` is
   286 MB against 15 GiB RAM. The deferral is correct. The trigger is now
   nameable: **if any nightly cycle's instrumented wall clock exceeds 2 hours, or
   parse time exceeds 40% of a run, the DuckDB/numpy question goes to the owner
   with the measurement attached.** Until then, a stdlib binary frame
   (`array` + `struct`) is sufficient and preserves the guard.

### 10.3 The nightly cycle budget

```
factory.cycle.run(date):
  01  generate    enumerate new cells + mutate/cross within unlocked cells
  02  dedupe      semantic hash vs population + graveyard; prune pruned branches
  03  register    alpha_registry.register() every survivor of dedupe
  04  evaluate    bitset sweep, real world + 50 placebo, parallel across 4 CPUs
  05  score       Scorecard per (strategy, window, point_class, market)
  06  attack      research.battery per candidate above the effect floor
  07  ceiling     placebo percentile + CSCV PBO + SPA
  08  transition  lifecycle state changes; graveyard writes with cause
  09  account     bankroll simulation for REPORTING only
  10  artifact    write with Timings, fingerprints, total_searched()
```

Target: under 2 hours on 4 CPUs. Steps 01-08 are deterministic and contain no
model call — enforced by a test that greps `src/factory/` and `src/board/` for
`anthropic|openai|api_key|urllib.request` and fails on a hit.

### 10.4 The correction that matters more than the compute

"Millions of decisions" is achievable and is *not* the binding constraint.
**Independent evidence is.** There are ~2,430 MLB games per season. Two discovery
seasons give ~4,860 games. Forty market expressions per game produce ~194,400
decisions and roughly **4,860 independent units** — the outcomes within a game
are massively dependent, and outcomes within a day share weather, umpire pools,
and market regime.

Every confidence interval in the system is therefore a **clustered bootstrap with
game-day blocks of at least 7 days** (`DEFAULT_SPA_BLOCK_LENGTH = 7.0` already).
`Scorecard.n_independent_clusters` is a required field precisely so nobody can
quote `n_decisions` as if it were sample size. Scaling compute without scaling the
dependence accounting produces confident nonsense faster.

---

## 11. DETERMINISTIC vs SONNET vs OPUS vs FABLE

Roles assigned by **cost of being wrong**, not by capability tier.

### Deterministic code — everything that decides, evaluates or governs

`decide()`, `evaluate()`, `score()`, `objective()`, `settle()`, the battery,
placebo/ceiling/CSCV/SPA, the bankroll account, promotion-gate arithmetic, the
alpha registry, all capture. **No model reasoning inside any of these paths, ever.**
Enforced by the import grep test in §10.3 and by `EVOLAB_DESIGN.md:399-400`'s
existing rule, extended to `src/factory/` and `src/board/`.

Rationale: a model in the decision path makes the Replay Identity Test
impossible, because the same inputs no longer produce the same output. Determinism
is not a performance choice here; it is what makes replay meaningful.

### Sonnet — volume implementation under written contract

Writes modules from the contracts in this document. Writes tests. Wires data.
Drafts candidate strategies as **schema-valid specs with mechanism strings**
(never code, never free-form claims) for `proposer.py`. Writes market settlement
adapters. Writes docs. Every output passes through deterministic validation
before it touches a store.

Failure cost: low and caught by tests. High volume. Right tier.

### Opus — methodology and adversarial review

Designs falsification rules. Red-teams every promotion candidate before it moves
state. Audits leakage. Adjudicates battery rule changes (`RULES_VERSION` bumps).
Writes the pre-registration for each family. Reviews any change to `decide()`,
`objective()`, or a gate.

Failure cost: catastrophic and *not* caught by tests — a bad methodology produces
green tests and false champions. The existing precedent is exactly right: the V3
`transaction_first_seen` read failed adversarial review on 9 findings and was
corrected. Make it a standing gate with a mechanical trip-wire: a
`validator_verdict` field that must be present and `PASS` before a research read
counts as final, checked by the registry's own append path.

### Fable — orchestration and gate-holding

Sequences packets. Holds the Two-Ledger Rule. Decides what gets registered and
when. Owns the owner interface and the decision queue. Runs the cycle. Does not
write research conclusions and does not decide bets.

### The meta-rule

**No model writes to `data/`, `evidence/`, or the alpha registry directly.**
Models emit proposals; deterministic code validates and appends. This is already
how `alpha_registry.register()` works and it should become universal.

### The missing artifacts

Create `.claude/agents/sonnet-implementer.md` and `.claude/agents/fable-orchestrator.md`
using the existing OBJECTIVE/WHY/INPUTS/BOUNDARIES/DELIVERABLE/ACCEPTANCE
template, and re-tag `opus-builder.md` and `opus-data.md` to Sonnet — they are
implementation roles wearing an Opus label, which is both expensive and a
misallocation of the review budget.

---

## 12. CAPTURE NOW

Ranked by (irrecoverability × value). Items 1-6 are things that stop existing if
not done during the live season.

1. **Persist `all_books` for spreads, totals and F5.** `odds.py:609-629` already
   *builds* these boards in memory on every capture; `snapshots.py:177` persists
   only `all_books.h2h` and discards the rest. **Zero marginal API cost.** This is
   the single highest-leverage fix in the repository and it is roughly a
   ten-line diff.
2. **Alternate run lines and alternate totals.** Measured at 7 books and 130-160
   outcome rows per event for 1 credit — the best information-per-credit on the
   board by the project's own probe. Never wired.
3. **F5 spreads/totals actually requested.** Keys exist, parser handles them,
   `dense._f5_close_pass` only ever asks for `h2h_1st_5_innings`.
4. **Batter props and pitcher props beyond strikeouts.** Nine batter families and
   five pitcher families have zero market keys anywhere. The live 2026 prop board
   is being lost every day and cannot be honestly purchased back.
5. **SGP / parlay price snapshots.** Books' correlation pricing for this season is
   unreconstructable after the fact. Capture now even though parlay *research* is
   blocked (§14.1) — the capture decision and the research decision are separate,
   and only one of them expires.
6. **Denser F5 close coverage.** 26 of 73 games today. Also: the T-30m prop
   repricing slot (S6) that answers "does the book move after the lineup posts"
   is narrower than the hourly cadence and roughly half of it is never observed by
   construction. That evidence is leaking today.
7. **Protect what is already running:** rosterwatch lineup/probable/transaction
   brackets, umpire-crew reveal bracketing (verified 3.6-4.6h pre-pitch), per-tick
   non-deduped weather. These are the only class-A/B evidence that will ever
   exist. A day the loop does not run is a permanently missing day — and the
   automation to make that not depend on an interactive session is merged but
   cannot fire (§13.4 / owner decision 2).
8. **2023-24 historical weather via Open-Meteo's free keyless archive.**
   `fetch_archive` exists and is unused for the past. No expiry, but no reason to
   wait. Turns MISSING into EXISTS for a whole environment feature family, at
   class C, honestly labelled as reanalysis.
9. **Park `orientation_deg`.** `None` for every park by design, which makes wind
   direction unclassifiable in/out/cross for all of history. A one-time static
   data fill that retroactively unlocks every wind feature.
10. **Wire `transactions.jsonl`.** 27,053 rows covering the full 2023-24 window,
    including 1,768 IL placements and 2,554 activations, already on disk,
    referenced by no feature and no `pointintime.INPUTS` entry. Highest-ROI
    already-paid-for asset in the repo.
11. **Reconcile the credit balance and tier.** `COLLECTION_POLICY.md` reasons from
    53,083 credits; the actual balance is ~99,634. The account's billing history
    can explain this *today* and will not be reconstructable from this repo after
    a few more cycles.
12. **Timing instrumentation, from now on.** The Phase 2B run's wall clock is
    permanently unrecoverable. Every future artifact carries `Timings` or is not
    written.
13. **The container-restart baseline** (four restarts in an hour at 0.6 GB of
    16 GB in use, 2026-09-02) is a dated first-party measurement that a future
    load-driven regime shift must be detected *against*. Preserve it as a named
    reference point rather than prose.

---

## 13. PRODUCT INTEGRATION — V2, Bet Rating, Picks, LOCK

### 13.1 The factory-first inversion

The product does not compute anything about whether a bet is good. It asks:

```python
factory.production.active(market_key: MarketKey, as_of: str) -> tuple[Strategy, ...]
factory.production.decisions(date: str) -> tuple[Decision, ...]
```

If the tuple is empty — which it is today and will be for some time — the product
renders the Analyzer, the Best Price Board, and nothing else. The product's
correctness reduces to "does it render what the governor approved", which is
testable, rather than "is this a good bet", which is not.

### 13.2 Bet Rating — the four components, honestly

Per `MASTER_PLAN.md` §16, unchanged in structure, sharpened in sourcing:

- **P — Price Quality.** Live today. `src/analysis/prices.py` best-vs-consensus,
  improvement points, book dispersion, `MIN_BOOKS = 6`. **Mandatorily labelled
  non-EV** and that label is not removable.
- **E — Evidence Quality.** Live today. The Analyzer's case: findings, samples,
  gaps, counterarguments, on the existing Observation→Validated ladder.
- **M — Model Advantage.** **Factory-first change: M is not a model owned by the
  product. M is a promoted strategy's calibrated probability.** It is `None` until
  `factory.production.active()` is non-empty. This makes the gate structural
  rather than editorial.
- **U — Uncertainty.** Ships with M: interval width, strategy agreement across the
  promoted population, regime flags, `n_independent_clusters`.

The composite exists only when M is populated *and* the composite passes the
calibration harness: forward rating-band monotonicity (the 80s must beat the 70s
on both outcomes and price-vs-close), reliability curves, per-market calibration.
An evidence score is never a win probability. A strong case at a terrible price
scores low. A model edge with wide U is capped.

### 13.3 Picks — the ladder, and the one rung available now

- **Stage 0 (live):** Best Price Board. Earned.
- **Stage 1 (internal, available immediately):** every candidate strategy emits
  paper decisions into the ledger. Nobody sees them but us. **This is shippable in
  week 2 and costs nothing** — it is the direct product of the daily loop in §8,
  and it starts the ≥60-day ledger clock and the ≥300-forward-decision clock that
  every later gate depends on. It is the highest-value non-obvious move available.
- **Stage 2 (subscriber-visible, labelled "FORWARD TESTING — not a
  recommendation"):** live CLV and calibration stats for people who want to watch
  the science. Optional, honest, differentiating.
- **Stage 3 (official picks):** §27 gates pass, owner signs off, picks ship with
  rating, reasoning, price at publication, model version, and enter the public
  record irrevocably.

Add a second test-pinned gate constant beside `ENGINE2`:

```python
PICKS_STAGE = 0   # 0,1,2,3 — moving this is a visible diff that fails a test
```

### 13.4 LOCK — defined, and honestly falsifiable

The owner says LOCK is the highest evidence/confidence class, criteria to be
researched, not prohibited. Agreed on all three counts. The definition:

> A decision is a **LOCK** when *all* hold: (1) it comes from a PROMOTED strategy;
> (2) its rating band is the top band of a decomposition whose **band monotonicity
> has been demonstrated forward** — the top band beats the next band down on both
> realized outcome and price-vs-close, with clustered CIs; (3) it sits in the top
> decile of calibrated edge within that band; (4) the band has ≥100 forward
> decisions of its own; (5) at least two independently-promoted strategies agree
> on the selection.

Two things this definition buys. First, LOCK cannot be reached by confidence
alone — the owner's phrasing is confidence-shaped and confidence uncorrelated
with price is how bad products are built. Second, **it is falsifiable**: condition
(2) is a research question with a real chance of coming back NO. If the top band
does not outperform, LOCK is retired as a concept and that retirement is
published. That is the honest version of "criteria to be researched".

### 13.5 The Ranker gate is untouched

`ENGINE2 = None`. `tests/test_ranker.py` pins that the page contains no
recommendation, no pick, no unit size and no "edge" language while it holds. The
four unlock conditions stand and now have a fifth structural companion: the
factory must have something PROMOTED for the product to have anything to render.

---

## 14. CHALLENGING THE VISION

Not reductions. Each of these makes the described system *more* capable.

### 14.1 "Search the whole board for a signal" should be "one belief, many projections"

**This is the most important correction in this document.**

The vision says: analyze the matchup, then search moneyline, run line, alt run
lines, totals, alt totals, team totals, margin, F5 variants, first inning, pitcher
props, batter props, derivatives and parlays, and ask which market best expresses
the advantage. Read literally, that is forty-odd independent searches for
thresholds. Two things go wrong:

1. **Multiplicity explodes and evidence does not.** Forty market families × two
   sides × alternate lines is hundreds of expressions per game, all drawing on the
   same ~4,860 independent units (§10.4). The search space grows 40×; the evidence
   grows 0×. The FDR burden becomes crushing and the winner is selected by noise.
2. **It cannot price a parlay.** Two independently-thresholded signals have no
   joint distribution, so their product is not a probability. A parlay recommender
   built that way is astrology, which `MASTER_PLAN.md` §18 already says.

The better architecture: the engine forms **one belief** — a probabilistic object
over game states — and every market is a **deterministic projection** of that
belief onto the market's payoff function.

```python
@dataclass(frozen=True)
class Belief:
    """The engine's probabilistic view of the game. One object, many uses."""
    p_home_win: float
    run_dist_home: tuple      # P(runs = k), k = 0..N
    run_dist_away: tuple
    f5_run_dist_home: tuple
    f5_run_dist_away: tuple
    joint: object | None      # correlation structure; None until earned
    per_player: dict          # {mlbam_id: {"ks": dist, "hits": dist, "tb": dist}}
    calibration_version: str
    availability_class: str

def project(belief: Belief, selection: Selection) -> float:
    """P(selection wins). Pure arithmetic. No search, no threshold, no fitting."""

def edge(belief: Belief, quote: Quote) -> float:
    """project() minus the de-vigged implied probability. Not price improvement."""
```

Then "which market best expresses the advantage" becomes: compute `edge()` for
every priced selection on the board and rank. That is **arithmetic over one
hypothesis**, not forty hypotheses. Multiplicity collapses from
"forty searched market families" to "one belief, tested once". Board width becomes
free rather than expensive — which is exactly what the owner wants and the
opposite of what per-market search delivers. And parlay pricing falls directly
out of `Belief.joint` instead of needing a separate program.

**The honest part.** We do not have a calibrated `Belief` and will not for a long
time — that is `MASTER_PLAN.md` §16's "M — empty until earned", and four
pre-registered families have produced zero survivors. So the interim is:

- The factory continues searching **conditional signals per market family**, as
  today, because that is what the evidence base supports.
- The `Belief` slot is reserved in the architecture from day one, so the search
  results have somewhere to become a model rather than staying a pile of rules.
- **Parlays stay blocked as research and open as capture.** Capture SGP prices now
  (§12.5); do not build a parlay recommender on thresholded legs, ever.

### 14.2 Bankroll tournaments select luck — the Two-Ledger Rule

Covered in §1.2 with the arithmetic. The vision's "simulated daily bankroll
accounts, 1,000 units, day by day, whole seasons" is *kept in full* and *demoted
from objective to report*. Rank 1,000 zero-edge strategies by season bankroll and
the winner shows ≈+14% ROI with near-certainty.

### 14.3 Population size is a cost, not an asset

Covered in §1.3. "Potentially thousands of systems" is correct as a capability and
dangerous as a goal. The figure of merit is evidence per unit of `total_searched()`.
The factory's output is *kills*.

### 14.4 Millions of decisions is not the constraint; independent evidence is

Covered in §10.4. Compute scaling without dependence accounting produces confident
nonsense faster. `n_independent_clusters` is a required field for this reason.

### 14.5 "Everything legitimately knowable" was not recorded, so grade it

Covered in §1.6. The `AvailabilityClass` reframe converts a program-stopping
blocker (`assert_point_in_time` raises for all six features) into a graded,
stamped exposure with the gate moved to promotion time — which is both more honest
and strictly more capable than the current binary.

### 14.6 The evolutionary gate is over-generalized from one negative cell

Covered in §6.6. Phase 2B tested one market × one fitness × one feature class and
failed. Gating all evolutionary search on that forever is over-generalizing from a
single negative result. Gate per `(market family × fitness dimension)`.

### 14.7 "LOCK = highest confidence" needs price in the definition

Covered in §13.4. Confidence uncorrelated with price is exactly how a
confident-sounding losing product is built. LOCK must be a joint class and must be
retirable if band monotonicity fails.

### 14.8 The end-of-day self-review must be computed, not written

Covered in §8.3. A free-text "the thesis was right, variance beat us" is a
loss-laundering machine. `thesis_outcome` is derived from structured mechanism
checks; `VARIANCE` becomes a measurable rate rather than an excuse.

### 14.9 The daily loop's automation is the quiet single point of failure

`forward-capture.yml` is merged with a `*/15` cron and **has never fired** because
the default branch is an orphan. `daily_loop.sh`, `monitor_remote.sh` and
`backup_app_db.sh` have no scheduled trigger at all, while `docs/RUNBOOK.md`
presents three of them as live unattended automation. Every day the loop does not
run is a permanently missing day of class-A/B evidence and a day that cannot count
toward the ≥300-decision and ≥60-day clocks. This is an owner decision (repoint
the branch, add the secret) that gates more of the vision than any code in this
document.

### 14.10 The Analyzer's detectors are features, not a second engine

Covered in §1.1. Two ungoverned decision paths is one too many, and the threshold
rules are the one that cannot be calibrated.

---

## 15. PHASED PLAN

| Phase | Weeks | Content | Exit gate |
|---|---|---|---|
| **F0 Foundations** | 1-2 | Free capture wins, market identity, availability classes, timing instrumentation, evidence wiring | Packets P1-P12 accepted; §4 corrections committed |
| **F1 Board** | 3-6 | Market catalog with settlement adapters + de-vig per family; E2 credit envelope; F5 and alternates live; BoardFrame + persisted cache | ≥6 families `PRICED_LIVE`, each with a settlement adapter tested on ≥50 known games |
| **F2 Factory core** | 5-10 | `src/factory/` with strategy/decide/score/attack/lifecycle/population; evolab equivalence proof; Replay Identity Test in CI; Stage 1 paper picks flowing | Byte-identical reproduction of Phase 2B; Replay Identity Test green; ledger accumulating multi-strategy rows daily |
| **F3 Scale + operators** | 9-16 | Parallel worlds, market masks, P7 time-shift placebo, LLM proposer with its registered null; mutation/crossover **within unlocked cells only** | A cell clears its placebo ceiling at the pre-registered percentile, *or* the factory publishes that none did |
| **F4 Forward** | rolling | ≥300 forward decisions per candidate, ≥60 ledger days, class A/B, §27 multi-dimensional standard | Gates pass; Opus adversarial review `PASS`; owner freeze sign-off |
| **F5 Product unlock** | after F4 | `ENGINE2` populated, `PICKS_STAGE` advanced, Bet Rating M+U, LOCK if band monotonicity holds | Owner sign-off; public record pages live |

**F3's exit gate has two acceptable outcomes and that is deliberate.** "No cell
cleared its ceiling" is a publishable result, consistent with zero survivors across
four families and the Phase 2B verdict, and it is a *success* of the machinery.
A plan whose only acceptable outcome is an edge is a plan that will manufacture one.

### The first two weeks, as packets

Each packet: owner role, duration, acceptance test, gate.

**Week 1 — free wins and the corrections**

- **P1 — persist all-books for spreads/totals/F5** (Sonnet, 1d).
  `snapshots.multibook_rows` currently persists `all_books.h2h` only
  (`snapshots.py:177`) while `odds.py:609-629` builds every market's board.
  *Accept:* a synthetic capture writes rows for 4 market families; existing h2h
  row shape byte-identical (backward compatible); credit log shows zero change.
  *Gate:* none — free.
- **P2 — `src/board/identity.py` + `catalog.py`** (Sonnet, 1d). `MarketKey`,
  `Selection`, `Quote`, canonical key strings, `MarketFamilySpec` with status.
  *Accept:* every existing h2h/spreads/totals/F5 row round-trips through identity
  with no loss; frozen dataclasses; canonical-key property test.
- **P3 — timing instrumentation** (Sonnet, 1d). `Timings` required on
  `SweepReport` and replay artifacts. *Accept:* a reduced-size sweep writes
  per-stage wall clock; a test fails if the field is absent. *Gate:* retires the
  "51 ms" claim (§4.2) with a correction commit to `EVOLAB_DESIGN.md`.
- **P4 — `AvailabilityClass`** (Opus design + Sonnet build, 1d). Add to
  `replay.EngineParameter` and `pointintime.INPUTS`; stamp on every decision.
  *Accept:* all six registered features report class C citing
  `AUDIT_PROBABLE_PITCHER_PIT.md`; `assert_point_in_time` moves from
  decision-time raise to promotion-time raise; existing PIT tests still pass.
  *Gate:* **owner decision 4** — this changes a standing refusal.
- **P5 — historical weather + park orientation** (Sonnet, 1d). Open-Meteo
  `fetch_archive` for 2023-24; fill `orientation_deg` for all 30 parks.
  *Accept:* `data/historical/weather/{season}.jsonl` on disk, labelled class C
  reanalysis; wind in/out/cross computable for ≥95% of games. Free, keyless.
- **P6 — wire transactions** (Sonnet, 0.5d). `transactions.jsonl` into
  `pointintime.INPUTS` plus one registered injury feature with an
  outcome-blind pre-registered ladder. *Accept:* coverage report; ladder
  derivation provenance recorded in the registry entry like `registry.py:337`.

**Week 2 — the factory skeleton and the paper-pick clock**

- **P7 — `src/factory/` skeleton with the equivalence proof** (Opus + Sonnet, 2d).
  `strategy.py`, `board/view.py`, `decide.py`, `population.py`. *Accept:*
  `factory.decide` reproduces `evolab.decide` byte-identically across all 8,811
  Phase 2B genomes on a sampled game set; `strategy_id` stable.
  *Gate:* no re-point of `evolab` until equivalence is green.
- **P8 — the Replay Identity Test** (Sonnet, 1d). Frozen corpus of forward ledger
  rows; rebuild `BoardView` from `information_time`; assert digest equality.
  *Accept:* CI-blocking test passes on ≥50 real rows.
- **P9 — `score.py` and the Two-Ledger Rule** (Opus, 1d). `Scorecard`,
  `AccountSummary`, `objective()`, and the AST test that `objective()` cannot
  name a forbidden money field. *Accept:* the AST test fails when a bankroll field
  is deliberately introduced. *Gate:* **owner decision 6.**
- **P10 — daily loop v2** (Sonnet, 1d). Ledger identity →
  `(game_pk, strategy_id, decision_instant)`; multiple rows per game; real closing
  threaded into `settlement.closing`; `src/pipeline/review.py` emitting structured
  `ReviewRow`s. *Accept:* one live date produces N decisions per game across
  instants; every settlement carries a non-null closing; review rows computed, not
  written. **This starts the ≥60-day and ≥300-decision clocks.**
- **P11 — credit reconciliation and probes** (Fable + owner, 0.5d, ~10-24
  credits). Reconcile 53,083 vs 99,634 against billing history; rewrite
  `COLLECTION_POLICY.md` with the measured balance and a per-family credit line;
  run 1-credit feasibility probes for team totals and one batter prop family under
  the existing feasibility-vs-collection distinction. *Gate:* **owner decision 1.**
- **P12 — alternates + F5 spreads/totals capture** (Sonnet, 1d). Behind env
  switches in the `PROP_LISTING_AUDIT`/`PROP_PRICES` pattern, on dense moments
  only, inside the E2 envelope. *Accept:* rows on disk carrying `MarketKey`s;
  credit log confirms spend inside the declared envelope; the floor check runs
  before every call. *Gate:* P11 (envelope approved) and P2 (identity exists).

---

## 16. OWNER DECISION QUEUE

1. **Credit envelope.** Raise 132/day → ~350/day (rung E2) now. Decide the 5M tier
   (~$119/mo) before the batter-prop tier (E4). The current policy reasons from a
   balance that is roughly half the real one.
2. **Repoint the default branch and add the `ODDS_API_KEY` secret**, so
   `forward-capture.yml` can actually fire. This gates more of the vision than any
   code in this document, and every day it waits is a permanently missing day.
3. **stdlib-only.** Keep the guard through F2. Revisit DuckDB/numpy only when
   instrumented wall clock exceeds 2 hours per nightly cycle or parse time exceeds
   40% of a run — a trigger that becomes measurable for the first time with P3.
4. **`AvailabilityClass` reframe** (§1.6): `assert_point_in_time` moves from a
   decision-time hard raise to a stamped exposure with a promotion-time raise.
   This unblocks the program without weakening the claim.
5. **Per-cell evolutionary gating** (§6.6): unlock operators per
   `(market family × fitness dimension)` rather than one global gate derived from
   the single Phase 2B cell.
6. **The Two-Ledger Rule** (§1.2): bankroll accounts simulated and published in
   full, structurally excluded from `objective()`.
7. **The LOCK definition** (§13.4), including that it is falsifiable and will be
   retired and published if forward band monotonicity fails.
8. **LLM proposer**: approve a per-cycle budget cap and the pre-registered null
   H-PROP-1 ("proposed strategies do not beat enumerated ones per unit of search").
9. **Parlays**: approve SGP price capture now while parlay research stays blocked
   until a joint `Belief` exists. Capture expires; research does not.
10. **Namespace migration** `src/evolab/` → `src/factory/` as a
    equivalence-tested generalization with aliases retained, not a rewrite.
11. **Agent roles**: create `sonnet-implementer.md` and `fable-orchestrator.md`;
    re-tag `opus-builder.md` and `opus-data.md` to Sonnet.
12. **Correction commits** for the eleven believed-but-absent items in §4, before
    anything is built on top of them.

---

## 17. WHAT IS HARD, AND WHY

Stated plainly so nothing here reads as easier than it is.

- **Settlement adapters are the silent killer.** A run line, a team total, a
  strikeout prop and a race-to-3 all settle differently, and a wrong settlement
  produces a plausible, confident, wrong backtest that no statistical test will
  catch. This is why §7.2 gates a market family on a settlement adapter tested
  against ≥50 known games before it may be priced.
- **A calibrated `Belief` may never arrive.** Four pre-registered families, zero
  survivors. Phase 2B: below the placebo ceiling, pooled percentile 13.3. The
  market's close beats public Elo by 0.008 log-loss at p=0.0003 — it is a strong
  opponent. The architecture must be as good at publishing "nothing cleared" as at
  publishing a winner, and §15's F3 gate is written so that outcome is a success.
- **2023-24 can never earn a promotion.** Class-C knowability, 6-hour median
  snapshot gaps, zero lineup-post timestamps. Discovery there, promotion only
  forward. That is a multi-season timeline and no amount of engineering shortens it.
- **The forward window is slow by construction.** ≥300 decisions per strategy and
  ≥60 ledger days, across a population, at ~15 MLB games a day. This is why P10
  (start the clock) is a week-2 packet and not a phase-4 one.
- **Prop and alternate markets are thin and book-dependent.** 7 books on a good
  day for strikeouts, 3 for F5 spreads. De-vig on a two-book market is barely
  meaningful, and `MIN_BOOKS = 6` exists for a reason. Several families in §7.3
  may turn out to be unanalyzable and that is a finding, not a failure.
- **Correlation is genuinely unsolved.** SGP dependence needs a joint player-level
  simulation, which needs calibrated marginals, which do not exist. The only
  non-expiring decision available today is to capture the prices.

---

*Every number in this document is cited to a file, a line, or a measurement in the
nine subsystem maps. Where a number was found to be unmeasured — the "51 ms", the
"under an hour", the 53,083 credits — this document says so rather than repeating
it.*
