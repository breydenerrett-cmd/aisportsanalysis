# LINEHOUND — Engine-First Architecture

**Angle:** start from the decision engine contract. One pure function takes a
point-in-time WorldView for a game plus the market board at that instant and
returns zero or more scored candidates with evidence and counterarguments.
Live and replay call *that identical function*. Everything else — the strategy
factory, the ledger, ratings, Picks, LOCK, the self-review — is derived from
that contract rather than invented beside it.

Author: independent architect pass, 2026-09-03.
Sources: nine evidence-cited subsystem maps in `docs/planning/map-*.md`, plus
direct reads of `src/evolab/`, `src/research/`, `src/pipeline/`, `src/analysis/`,
`src/detect/`, `src/core/`, `src/providers/odds.py`.
Status: design. Nothing here is evidence. No claim in this document has been
measured except where it cites a file, a line, or a store.

---

## 0. Why engine-first, and what it forces

The vision has two halves that people usually build separately and then fail to
reconcile: a live analyst that recommends bets tonight, and a backtester that
replays seasons. Built separately they diverge — not dramatically, but in the
hundred small ways that make a backtest optimistic: the live path sees a lineup
the replay path assumes, the replay path uses a price the live path could not
have taken, the live path has a bug fix the replay path predates.

Engine-first removes the possibility structurally. There is exactly **one**
decision function. It is pure: no I/O, no clock, no randomness, no global
mutation. It cannot know whether it is being called at 6pm tonight or on a
replay of 2023-04-11, because the only thing it can see is its arguments. The
two halves of the system differ only in *who assembles the WorldView*, and the
assemblers are held to byte-equality by a conformance test.

This is not a new idea in this repository — it is the idea `src/evolab/decide.py`
already implements correctly for a six-feature, one-market slice. The whole of
this design is: take that waist, widen it to the full vision, and hang every
other subsystem off it.

Three consequences fall out immediately, and each answers one of the owner's
questions before it is asked:

1. **"Search the entire board" becomes a loop, not a heuristic** — because the
   engine, not the strategy, holds the board.
2. **"Which market best expresses the informational advantage" becomes a
   calculation** — because the engine prices a probability against every
   selection on the board and ranks them, while the strategy that produced the
   probability never saw a price.
3. **"Backtest the analyzer" becomes trivially true by construction** — because
   there is nothing else to backtest.

---

## 1. Reconciliation: the vision against what is actually on disk

Read from the engine's vantage: for each thing the engine needs, what exists.

### 1.1 The engine waist

| The vision needs | On disk today | Verdict |
|---|---|---|
| One pure decision function | `src/evolab/decide.py::decide_with_reason` — pure, deterministic, explicit 4-rule tie-break, refuses on conflict rather than coin-flipping | **EXISTS**, scoped to genome-shaped strategies over one market |
| A WorldView that cannot see the future | `decide.py:112-178` — `__slots__` + `__getattr__` raising for 24 outcome/close names, checked at construction | **EXISTS**, and it is the single best piece of architecture in the repo. Two gaps: the construction check is **shallow** (only top-level `features` keys, `decide.py:135`), and the board is a two-level dict keyed by market, not a general selection board |
| Live and replay calling the same function | Replay does (`replay.py::world_view` → `decide`). **Live does not.** The live path is `mismatch.scan_game` → `route_market` → `briefing.build_slate` → `ledger.record_slate`, a completely separate code path with hard-coded two-market routing (`mismatch.py:157-158, 364`) | **ABSENT — the central gap.** Two decision engines exist and neither knows about the other |
| 0..N candidates per game | Both paths emit at most one verdict per game | **ABSENT** |
| Evidence on every candidate | `src/detect/base.py::Finding` — claim, value, baseline, sample, surprise, evidence-ladder status, and a refusal to emit a signal without a baseline | **EXISTS** and is the right shape; not attached to anything engine-shaped |
| Counterarguments | Zero references anywhere in `src/` | **ABSENT** |
| Bet Rating | Zero. `src/core/staking.py` has Kelly, `src/core/calibration.py` has Brier/log-loss/reliability, but nothing composes probability + price + track record into a rating | **ABSENT**, though both halves of the arithmetic exist |

### 1.2 The substrate the engine reads

| Section the vision names | On disk | Verdict |
|---|---|---|
| Starters: ERA/WHIP/FIP-ish, K%/BB%, arsenal, velocity, recent outings, workload, TTO, rest | `src/pipeline/rebuilt.py` rebuilds splits/arsenals/matchup from 2.7M Statcast pitch rows with cutoff filtering, tested CLEAN. `pitcher_logs.jsonl` 42,960 rows | **PARTIAL — strong.** The hard problem (point-in-time accumulation from pitch level) is solved. TTO is explicitly "approximated" not measured (RESEARCH_V6_CANDIDATES C5) |
| Starter *identity* at T | `*_probable_id` marked CLEAN by `pointintime.py`, but `docs/AUDIT_PROBABLE_PITCHER_PIT.md` proves 99.90%/99.92% agreement with the actual first-pitch thrower — 12-41× too clean versus a plausible scratch rate | **BELIEVED-BUT-ABSENT.** The registry's CLEAN means "cutoff-respecting accumulation", not "was knowable at T". Nine downstream features inherit this |
| Bullpen: availability, workload, leverage, closer, handedness | `bullpen_log.jsonl` 64,898 per-appearance rows, CLEAN. No closer/setup/leverage designation, no rest-based availability feature | **PARTIAL — raw only** |
| Offense: splits vs LHP/RHP, form, confirmed lineup, platoon, K/power/contact | `lineups.jsonl` 4,892 rows; 7 numeric lineup/starter features in `matrix.py:228-297` | **PARTIAL** |
| Lineup *posting time* | Zero games for 2023-24 have one. Forward capture correct since 2026-08 (`rosterwatch.py`) | **ABSENT historically, EXISTS forward** — unrepairable |
| Injuries / transactions | `transactions.jsonl` 27,053 rows spanning 2022-04..2026-09, including 1,768 IL placements and 2,554 activations across 2023-24 — **wired into nothing.** Grep shows only `coverage.py`, `news.py`, `rosterwatch.py` reference it | **EXISTS AND UNUSED.** Highest-ROI single wiring job in the repo |
| Environment: park, roof, temp, wind, humidity, precip, altitude | Static park data CLEAN. Weather provider exists; `fetch_archive` (Open-Meteo, free, keyless) **is never called for the past** — no historical weather store exists. `orientation_deg` is `None` for all 30 parks by design, so wind cannot be classified in/out/cross | **MISSING but cheap** — two free fixes turn a whole section on, retroactively |
| Umpire | Forward capture live since 2026-09-02, with bracketed reveal timing verified 3.6-4.6h pre-pitch. Nothing historical | **EXISTS forward only** |
| Market: book, price, open, movement, disagreement, depth, stale books, implied probability, consensus, close | `odds_multibook.jsonl` 19,487 rows across 11 books; `pricepath.py`; per-market close identification for h2h/spreads/totals/F5 | **EXISTS for h2h.** `normalize_event` builds `all_books` for **six** market keys (`odds.py:612-629`) and `snapshots.multibook_rows` persists **only `h2h`** (`snapshots.py:177`) — five markets of multi-book depth computed and thrown away on every single capture, at zero credit cost |

### 1.3 The board

| Market family | Historical (2023-24) | Forward (2026) | Notes |
|---|---|---|---|
| Moneyline (h2h) | 600 records/season, 3-4 instants/game, min gap 177 min | live, 11 books | the only fully wired family |
| Totals | captured historically | live, all_books discarded | gradeable from `mlb_results.csv` |
| Run line / spreads | **never polled**, not purchasable | live, all_books discarded | historical replay of this family is permanently impossible |
| F5 moneyline | 1 snapshot/game, 185/133/172 games with any book | live, 317 rows | `genome.py:82` supports it; `feed.py` never sources it — every one of Phase 2B's 8,811 genomes that preferred F5 fell through |
| F5 spreads/totals | never | **parsed by `normalize_event`, never requested** | free-ish: ~2 credits/event on the pass that already runs |
| Alt lines, team totals, margin, first-inning | never | never (one 24-credit manual probe, recorded in prose only) | |
| Pitcher props | never | `pitcher_strikeouts` listing (446 rows) + prices (29 rows) since 2026-09-02, 18 cr/day cap | one market key of a large family |
| Batter props | never | never | the largest untouched surface |
| Derivatives, parlays/SGP | never | never | zero code anywhere in `src/` |

### 1.4 The machinery around the engine

**EXISTS and is genuinely good — do not rebuild any of this:**

- Pre-registration funnel with structural enforcement, screen(2023) → replication(2024) → battery → BH-FDR (`funnel.py:437-675`).
- Falsification battery, versioned and fingerprinted, `RULES_VERSION 2.0.0`, five fatal rules, 1,517 lines of validation tests — and a documented case of it *originally passing a known false positive*, being adjudicated, and being fixed as general rules (`docs/VALIDATION_GATE.md:26-156`). That is a machine that has been caught being wrong and repaired. It is the most valuable asset here.
- Append-only cross-family alpha registry, 81 rows, working `total_searched()` (`alpha_registry.py`).
- Placebo/CSCV/SPA/ceiling pipeline that produced a real published negative verdict: BELOW_PLACEBO_CEILING, 0/3 generators cleared, pooled percentile 13.3, PBO 0.6111 (`docs/EVOLAB_PHASE2B_RESULTS.md`).
- Bitset engine: per-(feature,rung,side) bigint masks, selection by 2-3 bitwise ops (`bitsets.py:142-221`).
- Replay leak-proofing: `iter_instants_through` **breaks** rather than skips at T (`replay.py:577`); sealed-2026 refused by name at every entry point (`replay.py:415-439`).
- Point-in-time input registry that **refuses rather than warns** (`pointintime.py`).
- Forward ledger with `information_time` distinct from write time, append-only, settlement never mutating the recommendation (`ledger.py:104-109`).
- Engine-2 gate, test-pinned: `ranker.py:33 ENGINE2 = None`, with a test that fails if the page contains a pick, a unit size, or edge language.

**BELIEVED-BUT-ABSENT — claims the codebase or docs make that the code does not support:**

1. **"Evolab" is not evolutionary.** No mutation, crossover, population, elites or islands anywhere in `src/evolab/*.py`. It is deterministic enumeration of a fixed space. This is *correct* — the operators are pre-registered as gated on clearing the placebo ceiling, which Phase 2B did not — but the name misleads every reader.
2. **"11,088 genomes sweep in 51 ms" and "Phase 2 end-to-end well under an hour"** (`EVOLAB_DESIGN.md:384,398`) are design-time estimates stated as fact. No timing field exists in `sweep.py`, `replay.py` or `registry.py`; the Phase 2B artifact records no wall clock at all. The project's single most important run has never had its runtime measured — and the DuckDB deferral's own stated exit criterion ("only if wall-clock becomes the bottleneck") is therefore unmeasurable.
3. **The forward ledger cannot satisfy its own unlock condition.** Condition 3 is "300+ forward selections" (`PLAN_TWO_TOOLS.md:259`). The ledger holds 144 recommendation rows: 134 no_play, 7 market_unavailable, 3 flagged, **0 selections**. It has no rating field, no chosen book, no execution price, no system id, and a one-row-per-game-*ever* dedup rule (`ledger.py:62-79`) that structurally forbids recording a changed verdict after a lineup posts. Every day it runs unfixed is a day of forward evidence in a shape the gate cannot count.
4. **`settlement.closing` is null in every sampled row.** The real closing value lives in a separate `closing_backfill` row joined back at read time (`grading.py:727`). The schema advertises a field the writer never fills.
5. **The hourly forward capture has never been observed to run.** The GitHub Actions schedule is merged but cannot fire: the default branch is still the orphan `claude/cowork-session-migration-tn3sx2`, and `git log` shows zero forward-capture-bot commits. `docs/RUNBOOK.md`'s "what runs on its own" table lists three unattended jobs; one has code and it is unproven, two have none.
6. **The role split is inverted from the vision.** Six `.claude/agents/*.md` files, all `model: opus`, all execution workers including the hypothesis worker. No Sonnet role, no Fable role, no dispatcher. "Fable orchestrating" is a session narrating its own day in a status document.
7. **The credit policy is priced off a stale balance.** `COLLECTION_POLICY.md` reasons from 53,083 credits; `credit_log.jsonl` reads ~99,634 at 2026-09-03T00:15Z. The account appears to have moved tiers and nothing reconciled the policy.
8. **`MASTER_PLAN.md:770` describes the ledger as hash-chained** in present tense. No hash chain exists anywhere in `src/`.
9. **"Bet Check integration", a "season-end module", and a "CI scorecard" for evolab** are named in planning prose; grep finds zero references in `src/evolab/**` or `docs/EVOLAB_*.md`.

**MISSING outright:** any decision-*policy* object (market + book + price + timing + sizing + rating) that the research machinery can grade; the whole-board scanner; ratings; LOCK; counterarguments; bankroll simulation tied to the ledger; the factory loop; parlay/SGP anything; a structured end-of-day review; population-scale correlation tracking.

### 1.5 The one-sentence reconciliation

**The engine's *guardrails* are built to an unusually high standard and its *substrate* is one-fifteenth the size the vision needs.** The scarce resource is not discipline — this project has more of that than most — it is registered features, priced markets, and a live path that shares code with the replay path. Almost everything in this design is widening a waist that already exists, not inventing one.

---

## 2. The engine contract

New package `src/engine/`. Sport-neutral: `analyze.py` and everything it imports
must never contain the words inning, lineup, pitcher, or `game_pk` semantics.
Baseball lives in the assemblers, the sections, and the market universe. This
costs nothing now and is expensive to retrofit; `docs/MULTISPORT_AUDIT.md` did
the hard thinking already and this is how it is cashed in.

```
src/engine/
  markets.py     MarketRef, Selection, Quote, MarketBoard, MarketUniverse, MarketFamily
  worldview.py   WorldView, PriceBlindWorldView, Section, Grade, forbidden-name refusal
  candidate.py   Proposal, Candidate, Evidence, Counterargument, BetRating, AnalysisResult
  systems.py     AnalysisSystem protocol, SystemSet, Adversary protocol, fingerprinting
  pricing.py     consensus, de-vig, best/worst price, staleness, dispersion  (wraps src/core/odds)
  rating.py      rate() -> BetRating; LOCK criteria; confidence classes
  refusal.py     the refusal vocabulary (extends decide.py's death labels)
  analyze.py     analyze()  <-- THE WAIST
  daily.py       morning_analysis / price_and_rate / lock  (live orchestration)
  review.py      end_of_day  (deterministic self-review)
  adapters/
    live.py      LiveAssembler   — forward stores -> WorldView
    replay.py    ReplayAssembler — historical PIT stores -> WorldView
    conformance.py  the live/replay digest-equality test harness
```

### 2.1 Universal market vocabulary

The owner named the universals: MARKET / SELECTION / LINE / PRICE / BOOK /
TIMESTAMP. Encode exactly those.

```python
@dataclass(frozen=True, slots=True)
class MarketRef:
    family: str          # "moneyline" | "run_line" | "total" | "team_total" | "pitcher_ks" | ...
    scope: str           # "full_game" | "first_5" | "first_1" | "first_3"
    subject: str | None  # None for game markets; team code or player id otherwise
    line: float | None   # -1.5, 8.5, 5.5; None for two-way no-line markets

    @property
    def key(self) -> str: ...   # canonical, stable, hashable; the join key everywhere

@dataclass(frozen=True, slots=True)
class Selection:
    market: MarketRef
    side: str            # "away"|"home"|"over"|"under"|"yes"|"no"
    @property
    def key(self) -> str: ...

@dataclass(frozen=True, slots=True)
class Quote:
    book: str
    selection: Selection
    price_american: int
    observed_utc: str            # when WE saw it   (ours)
    book_last_update: str | None # when the BOOK last moved  (theirs)
    limit: float | None = None

@dataclass(frozen=True, slots=True)
class MarketBoard:
    quotes: tuple[Quote, ...]
    meta: BoardMeta              # observed_utc, books, simultaneous, staleness_seconds
    def selections(self) -> tuple[Selection, ...]: ...
    def for_selection(self, sel) -> tuple[Quote, ...]: ...
    def books_for(self, market: MarketRef) -> int: ...
```

The board is **a set of quotes**, not a nested per-market dict. That single
change is what makes "search the entire board" a `for sel in board.selections()`
loop instead of a routing table, and it makes board coverage measurable: which
selections were quoted at T, and which the engine wanted and could not find.

`MarketFamily` is the declared catalogue entry, and its most load-bearing field
is the one nobody has built:

```python
@dataclass(frozen=True)
class MarketFamily:
    key: str
    provider_key: str        # the-odds-api market key
    scope: str
    subject_kind: str        # "game" | "team" | "player"
    sides: tuple
    has_line: bool
    devig: str               # "two_way" | "n_way"
    capture_tier: str        # "featured" | "per_event" | "prop"
    credits_per_event: int
    status: str              # "LIVE" | "PROBE" | "DECLARED" | "BLOCKED"
    evidence_window: tuple   # ("2023-01-01","2024-12-31") or ("2026-09-03", None)
    settle: Callable         # (selection, boxscore) -> "win"|"loss"|"push"|"void"
```

**You cannot backtest a market you cannot grade.** `settle` is the gate on every
market family, and it is why §6's expansion order is driven by grading
feasibility before it is driven by credits.

### 2.2 WorldView

Generalize `decide.py`'s WorldView; keep every property that makes it good.

```python
GRADES = ("A", "B", "C", "D")
# A: observed with a timestamp at or before T
# B: bracketed — known to have become true between two polls
# C: known to the calendar day only
# D: reconstructed or assumed by a NAMED EngineParameter

@dataclass(frozen=True, slots=True)
class Section:
    name: str                # "starters"|"bullpen"|"offense"|"players"|"environment"|"market"
    values: Mapping[str, Any]
    grade: str
    provenance: str          # store + build rule, one line
    parameters: tuple        # EngineParameter names this section's grade depends on

@dataclass(frozen=True, slots=True)
class WorldView:
    game_id: str
    official_date: str
    commence_time: str
    T: str
    point_class: str
    game: Mapping
    sections: Mapping[str, Section]
    features: Mapping[str, float]     # flat away_/home_ scalars; the bitset substrate
    board: MarketBoard
    available: tuple                  # MarketRef keys actually quoted at T
    lineup_posted: bool

    def differential(self, feature) -> float | None: ...
    def grade_floor(self, sections=None) -> str: ...
    def digest(self) -> str:          # canonical JSON -> sha256
```

Three changes to what exists, each with a reason:

1. **Recursive forbidden-name refusal.** Today `__post_init__` (`decide.py:135`)
   walks only top-level `features` keys. Once sections are nested, a
   `{"starter": {"result": ...}}` slips straight through. `genome.py:202`
   already has the correct recursive walker (`_reject_forbidden_keys`); reuse
   it against the whole WorldView payload. This is a real live defect the
   moment sections land, not a hypothetical.
2. **Grades are first-class.** `replay.py:311,340` already has
   `availability_class()` and `assert_point_in_time()`. Promote that idea:
   every section carries a grade, the engine config declares a minimum grade
   per section, and a system that conditions on a D-grade field carries the
   exposure on every candidate it emits. This is how the probable-pitcher
   audit stops being a footnote and becomes an enforced, printed parameter.
3. **`PriceBlindWorldView`.** Identical, minus `board`/`available`, with
   `__getattr__` raising for those names the same way it raises for `outcome`.

```python
@dataclass(frozen=True, slots=True)
class PriceBlindWorldView:
    """A WorldView with the market structurally absent, not filtered.
    Systems form probabilities against this. They never see a price."""
```

**This is the most important design decision in this document.** If a system
sees prices while forming a view, "which market best expresses the advantage"
degenerates into picking whichever line looks softest — MARKET_SELECTION_ADVANTAGE
(`EVOLAB_DESIGN.md` §9) dressed as prediction. It backtests beautifully and is
worth nothing. `decide.py::_select_market` already enforces this narrowly
("nothing here consults price, so a genome cannot route itself to whichever
market happened to offer the better number"). Promote it from a property of one
function to a property of the type system.

### 2.3 Systems and adversaries

```python
class AnalysisSystem(Protocol):
    id: str
    version: str
    declared_markets: tuple[MarketRef, ...]  # everything it may EVER propose
    declared_inputs: tuple[str, ...]         # WorldView paths it reads
    min_grade: str
    spec_hash: str

    def propose(self, view: PriceBlindWorldView) -> tuple[Proposal, ...]: ...

@dataclass(frozen=True, slots=True)
class Proposal:
    selection: Selection
    p_model: float | None    # the system's probability for this selection
    score: float | None      # or an uncalibrated score, if it has no probability
    thesis: str              # one sentence, the mechanism being claimed
    evidence: tuple[Evidence, ...]
    system_id: str
    system_version: str

class Adversary(Protocol):
    id: str
    def attack(self, cand: "Candidate", view: WorldView) -> tuple[Counterargument, ...]: ...

@dataclass(frozen=True, slots=True)
class Counterargument:
    source: str
    severity: str            # "NOTE" | "MINOR" | "MAJOR" | "FATAL"
    claim: str
    evidence: Evidence | None
```

Three system kinds exist or nearly exist today:

- `GenomeSystem` — wraps `evolab.decide`. Pure and bitset-accelerated already.
- `DetectorSystem` — wraps the 11 detectors in `src/detect/detectors.py`. Their
  `Finding` maps onto `Evidence` almost field-for-field, including the
  evidence-ladder status and the refusal to emit a signal without a baseline.
- `ModelSystem` — a calibrated probability model. Does not exist; `src/core/calibration.py`
  is the scoring half of it and is correctly described in `MASTER_PLAN.md` §16
  as "empty until earned".

Adversaries are **deterministic code**; Opus designs the methodology, the
adversary itself never calls a model. Starting set, all implementable from data
already captured:

| Adversary | Fires when |
|---|---|
| `StaleBookAdversary` | the best price comes from a book whose `book_last_update` predates the consensus move |
| `ThinBoardAdversary` | fewer than `MIN_BOOKS` (6, `prices.py:31`) quote this selection |
| `NonSimultaneousAdversary` | `board_meta.simultaneous` is False and execution mode is BEST_OBSERVED |
| `GradeAdversary` | the candidate's thesis leans on a section below the declared grade floor |
| `CorrelatedEvidenceAdversary` | every Evidence item traces to one underlying measurement |
| `MarketDisagreementAdversary` | the F5 and full-game boards imply contradictory team strength |
| `SampleAdversary` | the system's forward record in this market family and probability band is below its declared minimum n |
| `RegimeAdversary` | the system's realized selection rate this month exceeds its pre-registered expected rate |

A FATAL counterargument removes the candidate — recorded as a refusal, still
written to the ledger, never silently dropped.

### 2.4 The waist

```python
def analyze(view: WorldView,
            *,
            systems: SystemSet,
            adversaries: tuple[Adversary, ...] = DEFAULT_ADVERSARIES,
            config: EngineConfig = DEFAULT_CONFIG) -> AnalysisResult:
    """Zero or more scored candidates for one game at one instant.

    PURE. No I/O, no clock, no randomness, no global mutation. The same
    (view, systems, adversaries, config) produces a byte-identical result
    forever, which is the only reason live and replay can be the same code.

    Phase 1  propose   : each system sees view.price_blind(); returns Proposals
    Phase 2  price     : engine prices every Proposal against EVERY selection
                         on the board that the proposal's thesis covers
    Phase 3  attack    : adversaries produce Counterarguments; FATAL removes
    Phase 4  rate      : BetRating from (p_model, entry price, track record)
    Phase 5  rank      : deterministic total order; no ties resolved by chance
    """
```

```python
@dataclass(frozen=True, slots=True)
class Candidate:
    candidate_id: str            # sha256 of (worldview_digest, system_id, selection.key)
    selection: Selection
    entry: ExecutionQuote        # book, price, observed_utc, execution_mode
    system_id: str
    system_version: str
    thesis: str
    p_model: float | None
    p_market_devig: float
    rating: BetRating
    evidence: tuple[Evidence, ...]
    counterarguments: tuple[Counterargument, ...]
    grade_floor: str
    parameters: tuple            # EngineParameters the result depends on
    worldview_digest: str

@dataclass(frozen=True, slots=True)
class AnalysisResult:
    game_id: str
    T: str
    point_class: str
    candidates: tuple[Candidate, ...]        # 0..N — empty is a normal answer
    board_coverage: BoardCoverage            # quoted / wanted-and-absent / thin
    refusals: Mapping[str, tuple[str, ...]]  # system_id -> refusal reasons
    engine_version: str
    systems_fingerprint: str
    worldview_digest: str
    def digest(self) -> str: ...
```

**Phase 2 is where "which market best expresses the advantage" is answered.**
A system says: *this starter's arsenal suppresses first-five run scoring against
this lineup; P(F5 under 4.5) = 0.58, P(away F5 ML) = 0.55, P(away full ML) = 0.53.*
The engine takes each of those to the board, de-vigs the consensus for each
selection, computes the rating for each, and ranks. The F5 total wins not
because anyone decided F5 totals are good, but because 0.58 against a de-vigged
0.52 at -110 clears the floor and the moneylines do not. The system never saw
a price. That is the mechanism the vision asks for, and it is enforced by types.

### 2.5 Bet Rating and LOCK

```python
@dataclass(frozen=True, slots=True)
class BetRating:
    stars: int                 # 0..5, discrete, the published number
    confidence: str            # "SPECULATIVE"|"STANDARD"|"STRONG"|"LOCK"
    p_model: float
    p_market_devig: float
    edge_pp: float             # (p_model - p_market) in probability POINTS
    ev_per_unit: float         # at the entry price
    kelly_fraction: float      # full Kelly (src/core/staking.py); staking applies the divisor
    calibration_band: str      # which reliability bin p_model lands in
    band_n: int                # forward selections this system has in that band
    band_ece: float | None     # its realized calibration error there
    caveats: tuple[str, ...]
    gated: bool                # True while the publication gate is closed
```

Rating is a **pure function of probability, price, and the system's own forward
track record in that market family and probability band.** Not a vibe, not a
free parameter. A system with no forward record in a band cannot exceed
STANDARD, whatever its edge looks like — which means a brand-new system
mathematically cannot produce a LOCK, and that is intended.

**LOCK is a conjunction, not a threshold.** The owner said the criteria are to
be researched, not prohibited. The proposed research target:

1. `band_n >= 200` and `band_ece <= 0.02` — the system has been right about
   *this probability* this often before.
2. The edge survives at the **worst** book on the board, not just the best.
3. The edge survives shrinking `p_model` 25% toward the market.
4. At least two systems with **disjoint `declared_inputs`** agree on the selection.
5. No counterargument at MAJOR or above.
6. The market family has a forward evidence window of at least 90 days.

Publish the LOCK **base rate** as a headline number. A LOCK rate above ~2% of
candidates is a red flag to be investigated, not a good day. A threshold-shaped
LOCK guarantees LOCKs exist every day whether or not any are deserved; a
conjunction-shaped LOCK produces mostly zero, which is the honest answer most
nights.

### 2.6 Purity, enforced

Four mechanisms, in increasing order of what they catch:

1. **Import guard.** A test walks the import graph of `src/engine/analyze.py`
   and fails on any module that touches `urllib`, `open`, `datetime.now`,
   `random`, or `anthropic`/`openai`. `tests.yml` already runs a stdlib-only
   guard and a network-block guard; this is the same pattern.
2. **Determinism test.** Call `analyze` twice on the same inputs; assert
   `result.digest()` equality. Extend to a shuffled-dict-order variant to catch
   iteration-order leaks.
3. **Cross-path equivalence.** For every system expressible as ladder
   thresholds, the bitset fast path and the general `analyze` path must select
   identically on a sampled 1% of decisions each run, with the sample count
   recorded in the artifact. `sweep.py` claims such a test today; make it
   required, sampled, and *counted*.
4. **The conformance test — the one that matters.** Every live `AnalysisResult`
   stores its `worldview_digest`. Thirty days later, the replay assembler
   rebuilds the WorldView for that same (game, T) from the historical stores
   and must produce **the same digest**. A mismatch means either the live
   capture recorded something the historical stores do not contain, or the
   replay assembler is reconstructing something that was not knowable. This is
   the only test that can catch a leak both paths share, and nothing in the
   repository does it today.

---

## 3. Boost vs replace

The default is BOOST. This codebase's guardrails are better than its substrate,
and the failure mode to avoid is throwing away a proven refusal in order to add
a feature.

### BOOST — extend, do not restructure

| Module | Why, and what changes |
|---|---|
| `src/evolab/registry.py` | Sign-freeze at registration + mechanism gate + provenance is the correct architecture. It has 6 features. Add features; change nothing else. Every new one keeps the ladder-derivation provenance pattern (`registry.py:337`, "4,856 games with both sides measured") |
| `src/evolab/genome.py` | Six-module structure, structural sign refusal, deterministic enumeration with a hashable order — all scale to more markets and features unchanged. `MARKETS` becomes a view over `MarketUniverse` |
| `src/evolab/decide.py` | Becomes `GenomeSystem.propose()` behind the engine. The WorldView type moves to `src/engine/worldview.py` and generalizes; `decide` itself is untouched |
| `src/evolab/bitsets.py` | Correct and already sub-linear in the right dimension. Extend the mask table to new markets. Needs a timing harness around it, not a rewrite |
| `src/evolab/replay.py` | The leak-proof boundary. Route **every** new market and feature through `iter_instants_through` and `world_view`, or the proofs stop covering them. Becomes `adapters/replay.py` |
| `src/evolab/placebo.py`, `cscv.py`, `spa.py`, `ceiling.py`, `sweep.py` | The most mature code here; it caught two of its own spec errors mid-project and shipped a real negative verdict. Add timing instrumentation and CPU parallelism; touch no math |
| `src/research/funnel.py` | Pre-registration → screen → replicate → FDR is sound and has killed four families. Extend `NUMERIC_FEATURES`; the single hard-coded `MARKETS = ('h2h',)` is the one REPLACE-shaped edit (see below) |
| `src/research/battery.py` | Versioned, fingerprinted, adversarially validated. Row schema already accepts optional book/price keys, so policy-grading checks are purely additive |
| `src/research/alpha_registry.py` | Append-only ledger + `total_searched()` is exactly right for factory scale. Add a cluster-id field per row; do not redesign the core |
| `src/research/matrix.py` | Keep the cutoff-disciplined per-game derivation. Add sibling matrices (bullpen, environment, market-structure) built the same way, and a persisted cache so the 7-11s/season build is paid per data change, not per invocation |
| `src/research/` V3 timing stack | Mature and reusable as-is for new event classes and other sports |
| `src/model/pointintime.py` | "Data not convention, refuse not warn" is correct and tested. Add `transactions` and a `starter_identity` entry, and a new axis distinguishing *cutoff-clean* from *known-availability-time* |
| `src/pipeline/rebuilt.py` | The hard problem is solved. Extend with more rate stats (K%, BB%, TTO, rest) |
| `src/pipeline/rosterwatch.py`, `umpirewatch.py`, `weather_capture.py` | Bracketing and per-tick non-dedup are the correct shapes. Extend to more event classes |
| `src/providers/odds.py` | Transport, error handling and the featured-vs-per-event billing split are correct and well tested. Extend the allow-lists per registered market |
| `src/pipeline/dense.py` | The capture-moment / lookahead / budget / seen-set machinery generalizes to any per-event market. `F5_CLOSE_MARKET` becomes a market list |
| `src/pipeline/prop_listing.py`, `prop_prices.py` | The absence-proof marker row + shared slot grid is a genuinely good pattern, proven twice. Reuse it per new market family — with its own narrow registration each time, not by widening these two modules' scope |
| `src/analysis/prices.py` | De-vig / best-price / dispersion math generalizes directly to every two-way market. The mandatory non-EV label stays and travels onto every new market |
| `src/analysis/contracts.py` | Add frozen dataclasses beside the existing six, same enforcement pattern |
| `src/analysis/betcheck.py` | Parse-and-refuse is right. Drive `SUPPORTED_MARKETS` off `MarketUniverse` LIVE entries so the refusal list maintains itself |
| `src/detect/detectors.py` | Finding/evidence-ladder shape is sound. Detectors become `DetectorSystem` proposals |
| `src/report/ranker.py` | BOOST the shell only. Do not weaken the Engine-2 gate to ship a Picks surface |

### REPLACE — specific rules, not whole modules

1. **`ledger.py`'s one-row-per-game-ever dedup rule** (`ledger.py:62-79`). Keep
   append-only, keep settlement-separate, keep `information_time`. Replace the
   identity with `(game_pk, T, system_id, selection.key)` plus a
   **no-new-information refusal**: if the WorldView digest is unchanged since
   the last row for this game, write nothing. Without the first change the
   ledger cannot record that the engine changed its mind when a lineup posted;
   without the second, repeated capture ticks inflate the forward selection
   count without adding evidence, which is a quiet way to reach 300 dishonestly.
2. **`mismatch.py::route_market`** (`mismatch.py:364`). Hard-coded two-market,
   two-signal routing is the structural opposite of "search the whole board".
   It is superseded by `analyze()` Phase 2. Keep `mismatch.py`'s signal
   functions as a `DetectorSystem`; retire the router.
3. **`grading.py`'s settle-time closing computation.** Thread the real closing
   price onto the settlement row from the multibook store. Keep
   `closing_backfill` as a stopgap repair tool, labelled as one.
4. **`funnel.MARKETS = ('h2h',)`** → a real market dimension with per-family
   pricing and settlement adapters.
5. **`scoreboard.py`'s schema.** It counts hypotheses screened/killed/survivors.
   Units, bankroll, calibration and ratings are a different unit of account;
   they need an adjacent ledger, not a widened one.
6. **`sweep.py`'s default primary fitness** (see §5.4). Movement fitness stays
   available as a diagnostic; it stops being primary.
7. **`ReplayUniverse.get()`** (`replay.py:731`) — a one-line fix from an O(n)
   linear scan to the `by_id()` dict that already sits unused beside it. Latent
   O(n²) at multi-season and multi-sport scale.

### NEW BUILD — nothing exists to extend

`src/engine/**` (the waist), adversaries and counterarguments, `BetRating` and
LOCK, `src/factory/**` (the loop), the structured end-of-day review, bankroll
simulation joined to the ledger, population correlation and effective-number-of-tests,
parlay/SGP anything, per-family `settle` functions, the publication-gate readout
page, and Sonnet/Fable agent roles plus a dispatcher.

---

## 4. Live and replay: the same engine

### 4.1 The two assemblers

```python
class WorldViewAssembler(Protocol):
    def decision_points(self, scope) -> Iterator[DecisionPoint]: ...
    def assemble(self, game_id: str, T: str) -> WorldView: ...
```

`adapters/live.py` reads the forward stores (`odds_multibook.jsonl`,
`data/watch/*`, `weather_forecast.jsonl`, `umpires_watch.jsonl`, the rebuilt
splits/arsenals) filtered to `<= T`. `adapters/replay.py` is today's
`replay.py::world_view` generalized, and keeps every refusal it already has:
sealed-2026 by name, non-2023/24 seasons by name, `break`-not-`skip` at T, no
interpolation between observed instants, and a `LeakageError` if a board
stamped after T ever reaches assembly.

Both are held to the same contract by `adapters/conformance.py`, which is where
the digest-equality test of §2.6(4) lives.

### 4.2 Leak-proofing, in five layers

| Layer | Mechanism | Catches |
|---|---|---|
| L1 structural | Outcome and close names absent from the type, recursively refused at construction | A feature dict carrying a result |
| L2 read-time | One `PointInTimeReader` protocol: `iter_through(key, T)` **breaks**, never skips. Statcast already does this (`iter_rows(before=)`); generalize it to every store | A future row influencing a decision through a bug |
| L3 declarative | `pointintime.INPUTS` extended with an `availability_time` axis separate from `cutoff_clean`; every gap is a named `EngineParameter` (`replay.py:249`) printed on every artifact | A stored value that is cutoff-clean but was not knowable at T — the probable-pitcher class |
| L4 differential | The conformance test: live digest vs replay-rederived digest, 30 days later | A leak both paths share |
| L5 statistical | The existing placebo / CSCV / SPA ceiling on the engine's output | An edge that is search artefact rather than signal |

L4 is new and it is the layer that would have caught the probable-pitcher
problem before an audit had to. The forward path *bracketed* a probable-pitcher
announcement; the historical store has only the effectively-actual value. Their
digests would differ, loudly, on day one.

### 4.3 The honest limits, stated plainly

Three things the vision asks for that the data will not give, and what to do
instead:

1. **Decision-point granularity collapsed from four rungs to two.** 2023-24
   board spacing is min 177 minutes, median 6 hours; `T_MINUS_30M` exists for
   1,269 of 4,819 games; lineup-posting timestamps exist for **zero**. The
   ladder is honestly degraded to EARLY_BOARD / LATE_BOARD (`replay.py:130`).
   *Response:* keep two rungs for 2023-24, define the full ladder now, and
   capture densely forward so 2026+ replays at the granularity the vision
   wants. If the live capture does not snapshot densely while the season runs,
   this ceiling recurs permanently.
2. **Most of the board has no history and cannot be bought.** Run lines,
   alternates, team totals, props beyond one K listing, derivatives and parlays
   were never polled in 2023-24. *Response:* per-family evidence windows, and
   start the forward clock for every family today (§6).
3. **`lineup_posted` in replay is a parameter's output, not a fact.** It is
   already stamped as one on every artifact. Keep doing that, and never let a
   downstream reader see the flag without the parameter.

---

## 5. Evolab → Strategy Factory

### 5.1 What Phase 2B actually established

8,811 genomes over 4,188 games returned BELOW_PLACEBO_CEILING: real max
movement fitness 0.00488, pooled percentile rank 13.3 (below the placebo
median), 0 of 3 movement-ceiling generators cleared, PBO 0.6111. That is a
correct, well-executed negative result and it should stay published.

It is also a result over a *very small substrate*: 6 features (all
lineup/starter composition), 1 priced market, 2 decision-point rungs, and a
fitness that measured line movement rather than outcomes. A search that small
over a market that efficient failing to beat placebo is close to the prior
expectation. The result falsifies the *substrate*, not the *method*.

So the factory's first job is **not evolution**. Evolab's own pre-registered
rule — operators unlock only on a genuine ceiling clear — should not be
softened, and this design does not soften it. The order is:

1. Expand the WorldView substrate (§1.2's gaps; bullpen, environment,
   injuries, market structure).
2. Expand the market universe (§6).
3. Re-run **the identical Phase 2B protocol**, with outcome-calibration as
   primary fitness (§5.4), on the expanded substrate. Publish either way.
4. Only on a genuine clear do mutation, crossover, elites and islands unlock.

### 5.2 The loop

```
src/factory/
  proposer.py     GENERATE — three sources: enumerate | mutate/cross | LLM-propose
  scheduler.py    the cycle; refuses to advance a system whose gate evidence is missing
  population.py   the live population: status, lineage, retirement
  attack.py       ATTACK — per-candidate adversarial battery (wraps research/battery.py)
  correlation.py  population-scale: are these 400 systems actually one system?
  promote.py      PROMOTE — mechanically evaluates config/promotion_gates.json
  dispatch.py     the work queue Fable drives (data/factory/queue.jsonl)
```

Cycle: `GENERATE → SCREEN(2023) → REPLICATE(2024) → BATTERY → CEILING → FORWARD → PROMOTE`,
with `RETIRE` and `MUTATE → RETEST` as edges off any failing stage.

`data/factory/population.jsonl`, append-only, one row per status transition:

```python
{
  "system_id": "...", "version": "...",
  "lineage": {"parent": "...", "operator": "enumerate|mutate|crossover|llm", "cycle": 41},
  "spec": {...},
  "spec_hash": "...", "semantic_hash": "...", "registry_fingerprint": "...",
  "declared_markets": [...], "declared_inputs": [...], "min_grade": "B",
  "expected_selection_rate": 0.04,        # pre-registered; a trip-wire, see §5.5
  "alpha_registry_row_id": "...",
  "status": "proposed|screening|replicating|battery|ceiling|forward|promoted|retired|withdrawn",
  "results": {"screen": {...}, "replication": {...}, "battery": {...},
              "ceiling": {...}, "forward": {...}},
  "retirement": {"at": "...", "reason": "...", "evidence": "..."},   # reasons pre-declared
  "proposer": {"model": "...", "cycle": 41, "cost_usd": 0.031}       # for LLM-sourced only
}
```

`retirement.reason` must be one of the reasons **declared at registration**
(`MASTER_PLAN.md` §27 demotion). A system that can be retired for any reason
after the fact was never really tested.

### 5.3 Selection is never by bankroll alone

Promotion evaluates a `Scorecard` with **named dimensions, each with its own
declared floor, and requires ALL of them.** Not a weighted sum: a weighted sum
lets a spectacular ROI outrun a calibration failure, which is exactly the
failure mode the owner ruled out.

```python
@dataclass(frozen=True)
class Scorecard:
    n_selections: int          profit_units: float        roi: float
    avg_odds: float            max_drawdown_units: float  daily_volatility: float
    clv_bps: float             # advisory ONLY — never sufficient alone
    calibration_ece: float     calibration_bins: tuple
    oos_roi: float             forward_roi: float
    stability: dict            # per season / per book / per market family / per month
    price_sensitivity: dict    # ROI at entry, at -10 cents, at consensus, at WORST book
    top5_profit_share: float   # dependence on a few big wins
    bootstrap_ci: tuple        # clustered by DAY, not by bet
    placebo_percentile: float  spa_pvalue: float  bh_q: float
    effective_tests: int       raw_tests: int     # see 5.6
    falsification: dict        # battery verdict + rules_fingerprint
    seasonal_break: dict       # regime-shift flags
```

Floors live in versioned `config/promotion_gates.json`. `promote.py` returns
`PROMOTED` or `REFUSED` with the list of unmet gates and their current values —
a machine verdict, not a judgement call. Its first acceptance test: run it
against Phase 2B's best genome and confirm it returns REFUSED naming the
specific failures.

### 5.4 Fitness: movement is not primary

Phase 2B optimized toward line movement. `MASTER_PLAN.md` §27 already says
closing-line behaviour is advisory and never sufficient, and it is right for a
sharp reason: **a system can beat the close systematically by betting into
stale books.** That is execution quality, not prediction, and it is precisely
the thing `prices.py`'s mandatory label exists to keep separate from EV.

Proposed primary fitness, in order:
1. **Calibrated log-loss against outcome**, versus the de-vigged market price
   as the benchmark. `src/core/calibration.py::compare` already computes
   exactly this and is wired only to synthetic data today.
2. **Realized return at the captured entry price**, with a day-clustered
   bootstrap CI excluding zero.
3. **CLV as an early filter and decay diagnostic only** — useful because it is
   available before outcomes accumulate, never sufficient.

Making this switch is a change to `sweep.py`'s `PRIMARY_FITNESS` default. It is
also a plausible partial explanation for why Phase 2B found nothing, and that
should be stated when the re-run is published rather than discovered later.

### 5.5 Never force quantity — mechanically

"Output 0..N opportunities per day; never force quantity" needs a counterpart
or it erodes silently. Each system pre-registers an `expected_selection_rate`
at promotion. `RegimeAdversary` fires when the realized rate over a rolling
window exceeds it by a declared factor. A system that suddenly fires on 40% of
games has changed; the change is far more likely a bug or a data shift than an
opportunity, and it should be caught by the engine rather than by a good month
followed by a bad quarter.

### 5.6 The genuinely hard part: multiplicity at factory scale

This is the deepest problem in the vision and it deserves to be named as such
rather than assumed away.

Thousands of correlated systems, over one market, with ~4,800 games and a house
edge near 4.5%, will produce spectacular-looking winners **by construction**.
`alpha_registry.total_searched()` is the right primitive and it exists, but
`semantic_hash_v0` catches only exact-atom-set duplicates
(`alpha_registry.py:106-108`), and BH-FDR against a raw count of "systems
searched" is close to vacuous when the systems are massively correlated: 8,811
genomes over 6 features are not 8,811 independent tests, they are perhaps a few
dozen.

The honest treatment:

- Compute the **selection-overlap matrix** across systems on a common universe.
  This is cheap in the existing representation: overlap is a popcount of an AND
  between two selection bitsets.
- Cluster on that overlap. Report the **effective number of tests** = number of
  clusters, alongside the raw count. Both numbers get published, always
  together.
- Never claim the raw count is the denominator; never pretend clusters are
  independent either. Report both and say what each means.
- **Scale the substrate before scaling the population.** A bigger population
  over a small substrate mostly buys better overfitting. This is the single
  most important strategic implication of the Phase 2B result.

---

## 6. Market-universe expansion

### 6.1 The gate on every family is grading, not credits

You cannot backtest, settle, or self-review a market you cannot grade. Ranking
by grading feasibility first changes the order materially:

| Family | Gradeable from | Status |
|---|---|---|
| Moneyline, totals, run line (full game) | `mlb_results.csv` (9,364 games) | ready |
| F5 ML / RL / total / team total | Statcast pitch rows (2.7M) → inning-by-inning runs | ready, needs a `settle` |
| First inning | same | ready, needs a `settle` |
| Team totals | same | ready, needs a `settle` |
| Pitcher props (K, outs, IP, H, ER, BB) | `pitcher_logs.jsonl` (42,960) + `bullpen_log.jsonl` (64,898) | mostly ready |
| **Batter props (H, TB, HR, RBI, R, BB, K, SB, H+R+RBI)** | **nothing on disk** | **BLOCKED on a free, keyless capture nobody has run** |
| Derivatives (race-to-X, first to score, inning markets) | Statcast play-level | ready, needs careful `settle` |
| Parlays / SGP | product of leg settlements | ready once legs are |

**Per-game batter and pitcher box lines from MLB StatsAPI are free, keyless,
backfillable to 2023, and are the missing grading substrate for the single
largest market surface in the vision.** They appear on no existing capture-now
list across all nine maps. This is the highest-value item this design found.

### 6.2 Expansion order and credit budget

Measured facts, not estimates: featured endpoint bills **3 credits flat** for
h2h+spreads+totals at any slate size; per-event bills markets × regions **per
event**; balance ~99,634 at 2026-09-03T00:15Z (`credit_log.jsonl`); floor 5,000
(`dense.py:62`); current envelope ~132/day.

| Tier | What | Credits/day | Gate |
|---|---|---|---|
| **T0** | Persist `all_books` for spreads/totals/F5 — already computed in memory (`odds.py:612-629`) and discarded (`snapshots.py:177`) | **0** | none; do it this week |
| **T0** | MLB StatsAPI box lines, forward + 2023-24 backfill | 0 | none |
| **T0** | Open-Meteo `fetch_archive` for 2023-24 weather; park `orientation_deg` for 30 parks | 0 | Opus reviews the orientation source |
| **T1** | F5 spreads/totals on the existing named-event pass (parser already exists) | +~30 | registered hypothesis |
| **T2** | Team totals + alternate lines, dense window only | +~1,000 | hypothesis + cost cap + PIT plan |
| **T3** | Batter props: 3 slots/day × 15 games × ~6 markets | +~3,000 | owner sign-off; the largest irrecoverable surface |
| **T4** | Full board hourly + dense near first pitch | ~7,000-7,600/day (~225k/mo) | requires the 5M / $119-per-month tier |

Two governance fixes the maps found and this design adopts:

- **A hard-coded `DAILY_ENVELOPE` constant** with the same shape as
  `CREDIT_FLOOR = 5000`. Today the floor is enforced in code and the ceiling is
  narrative prose. A ceiling that lives only in a document is not a ceiling.
- **Reconcile the balance/tier against `COLLECTION_POLICY.md`** (53,083 vs
  ~99,634) *now*, while the vendor's billing history still explains it. After a
  few more cycles it will not be reconstructable from this repo.

### 6.3 The asymmetry nobody can fix

Historical breadth cannot be bought. 2023-24 has moneyline and totals, one F5
snapshot per game, and nothing else — the run line was never polled, and the
maps confirm it by direct scan of `odds_history/*.jsonl`.

Therefore **each market family carries its own `evidence_window`**, and the
factory runs two clocks:

- Families with 2023-24 depth (h2h, totals, partial F5) run the full
  screen → replicate → battery → ceiling protocol *now*.
- Every other family can only run **forward paper from the day capture starts**.

This is the single largest gap between the vision as described and what is
achievable, and §11 argues it should change how the plan is sequenced rather
than being buried in a caveat. The practical consequence is simple and urgent:
**day 1 of a forward record is the cheapest it will ever be**, so start the
clock on every family the budget allows, immediately, even before a hypothesis
names them — that is what "the live season is precious" means in credits.

---

## 7. The daily loop

All times UTC; the MLB slate drives the offsets.

```
T-24h..T-5m   CAPTURE       GH Actions */15  →  forward stores
                            (built: capture_slot.sh + forward-capture.yml;
                             BLOCKED on the default branch — see §10)

09:00         MORNING       engine.daily.morning_analysis(date)
                              for each game:
                                view = LiveAssembler.assemble(game, T=now)
                                proposals = systems.propose(view.price_blind())
                              → data/daily/<date>/proposals.jsonl
                            Systems form probabilities having seen NO prices.

T-3h..T-5m    BOARD SWEEP   engine.daily.price_and_rate(game, T)   per capture tick
                              view   = LiveAssembler.assemble(game, T)
                              result = engine.analyze(view, systems, adversaries)
                              ledger.record_analysis(result)
                            Appends only when the WorldView digest changed.
                            0..N candidates per game per tick, each with entry
                            book + price + rating + evidence + counterarguments.

T-5m          LOCK          the final AnalysisResult per game is the graded one;
                            frozen, digested, never rewritten.

post-game     SETTLE        grading.settle_selection(candidate_id, boxscore, closing)
                            per SELECTION, not per game. Closing threaded onto
                            the settlement row from the multibook store.
                            Bankroll ledger advances one day: 1,000 units start,
                            declared staking rule, day-by-day equity curve.

23:00         SELF-REVIEW   engine.review.end_of_day(date)  — deterministic
                            → ReviewRecord per candidate + per system
                            → new-hypothesis queue for the factory
```

### 7.1 The ledger schema that can actually satisfy the gate

```python
{
  "kind": "analysis",
  "recorded_at": "...", "information_time": "...",     # keep both; ledger.py:104-109
  "date": "...", "game_pk": "...", "T": "...", "point_class": "LATE_BOARD",
  "worldview_digest": "...", "engine_version": "...", "systems_fingerprint": "...",
  "candidates": [{
     "candidate_id": "...", "system_id": "...", "system_version": "...",
     "market": {"family": "total", "scope": "first_5", "subject": null, "line": 4.5},
     "side": "under",
     "entry": {"book": "draftkings", "price_american": -108,
               "observed_utc": "...", "book_last_update": "...",
               "execution_mode": "CONSENSUS_EXECUTION"},
     "p_model": 0.58, "p_market_devig": 0.521,
     "rating": {"stars": 3, "confidence": "STANDARD", "edge_pp": 5.9,
                "ev_per_unit": 0.113, "kelly_fraction": 0.108,
                "calibration_band": "0.55-0.60", "band_n": 0, "band_ece": null,
                "caveats": [...], "gated": true},
     "thesis": "...",
     "evidence": [...], "counterarguments": [...],
     "grade_floor": "B", "parameters": ["LINEUP_ASSUMED_POST_MINUTES=180"],
     "stake_units": 0.0                                  # 0 while the gate is closed
  }],
  "board_coverage": {"quoted": [...], "wanted_absent": [...], "thin": [...]},
  "refusals": {"sys_0031": ["BELOW_ENTRY"], "sys_0044": ["INSUFFICIENT_BOOKS"]}
}
```

Settlement stays a separate append-only row keyed by `candidate_id`, never
touching the analysis row.

Three properties this buys that today's ledger cannot provide: a countable
forward *selection* (the 300-gate unit), a per-selection settlement, and a
record of the engine changing its mind when a lineup posted. Today's schema
provides none of the three, which is why fixing it outranks every research task
in §12's sequencing.

### 7.2 Self-review, beyond win/loss

```python
{
  "kind": "review", "date": "...", "candidate_id": "...", "system_id": "...",
  "result": "win|loss|push|void",
  "thesis": "...", "thesis_held": "yes|no|unknowable",
  "mechanism_check": {...},        # did the claimed mechanism OCCUR in the box score
  "price_entry": -108, "price_close": -124, "clv_bps": 61,
  "market_moved": "toward|away|flat",
  "post_T_changes": [{"kind": "lineup", "at": "...", "detail": "..."}],
  "counterarguments_vindicated": ["StaleBookAdversary"],
  "variance_flag": true,           # outcome contradicted a thesis that HELD
  "calibration_update": {"band": "0.55-0.60", "n": 41, "ece": 0.031},
  "system_action": "none|watch|demote|promote_candidate",
  "new_hypothesis": "..."
}
```

The discipline that makes this worth the code: **`thesis_held` is judged from
the box score, never from the P&L.** A system that claimed "this starter
collapses third time through" and won because a reliever gave up five in the
eighth did not have its thesis confirmed — it got paid for being wrong, which
is the most dangerous outcome a research system can experience unlabelled. The
`variance_flag` cross-tab (thesis held × result) is the actual learning signal,
and it is the thing "beyond win/loss" means concretely.

`system_action` is computed from pre-declared trip-wires, not judged. Sonnet may
write the narrative summary *from* these rows; it must never produce the rows.

---

## 8. Scale: millions of decisions, cheaply

### 8.1 The arithmetic, made concrete

A decision is `(system × game × T × selection)`. Target scale:

```
 5,000 systems × 4,819 games × 2 decision points × 6 market families
   ≈ 289,000,000 decisions per full sweep world
   × 51 worlds (1 real + 50 placebo) ≈ 1.5 × 10^10
```

At a naive 20 µs per decision in Python this is ~1,900 CPU-hours per sweep. It
is not affordable and it does not need to be.

### 8.2 Why it is actually cheap

The insight already in `bitsets.py`: **signal firing is a property of the
world, not of the system.** Per (feature, rung, side) you compute one bigint
mask over all games *once*; every system that references that signal reuses it.
A system's selection set is then 2-3 bitwise ops and a popcount — no Python
loop over games at all.

So the real cost is `masks × worlds`, not `decisions`. With 40 features × 3
rungs × 2 sides × 6 markets that is ~1,440 masks per world, and per-system
evaluation is ~5,000 × 6 = 30,000 combine-and-popcount operations. That is
seconds per world, which is the right order of magnitude, and Phase 2B already
demonstrated the pattern at 8,811 genomes.

### 8.3 The plan

1. **Instrument before optimizing.** `src/core/timing.py`: a context manager
   writing `{stage, wall_s, cpu_s, decisions, decisions_per_s, peak_rss_mb}`
   into `SweepReport` and every artifact. The compute map's sharpest finding is
   that the DuckDB deferral's own exit criterion is unmeasurable because
   nothing measures anything; the headline "11,088 genomes in 51 ms" was never
   checked against the one real run it describes. An afternoon's work unblocks
   every subsequent scale decision.
2. **DecisionFrame.** A columnar, immutable, memory-resident per-season frame:
   game features as float arrays, per-(feature,rung,side) bitsets, a
   per-selection price matrix. Built once, cached to disk keyed by (store
   fingerprints, registry fingerprint, engine version). Kills the repeated
   7-11s/season matrix rebuild paid on every invocation today.
3. **Two-tier evaluation.**
   - *Search tier* — the bitset path, for every system expressible as ladder
     thresholds. Used for the full population sweep.
   - *Verification tier* — the general `analyze()` path. Used for the promoted
     population, for the forward loop, and for a sampled 1% cross-check against
     the search tier every run, with the sample count recorded in the artifact.
4. **Parallelize placebo worlds across the 4 CPUs.** 51 worlds is embarrassingly
   parallel and `scripts/test_parallel.py:135-157` already demonstrates the
   exact LPT-balancing pattern for a different job. Near-4× for free.
5. **Fix `ReplayUniverse.get()`** — the unused `by_id()` dict is right there.
6. **Only then** consider columnar storage, and **declare the trigger now**:
   JSONL parse cost exceeds 30% of a full run's measured wall clock, or a full
   run exceeds 30 minutes. `data/` is 286 MB in a 15 GiB container; replacing
   the format today would be acting on an unmeasured effect, which is exactly
   what `MASTER_PLAN.md:846-851` correctly declined to do.

### 8.4 The container reality

15 GiB RAM (707 MiB used), 4 CPUs, no swap. Four container restarts in an hour
occurred with 0.6 GB of 16 GB in use, so restarts are platform-driven, not
load-driven. That dated first-party measurement is worth preserving as a named
baseline: if parallel sweeps later push memory hard, a regime change should be
detectable against it rather than re-argued from scratch.

---

## 9. What is deterministic, and who does what

### 9.1 The hard rule

**No model call ever appears inside the decision path.** `analyze()` and
everything it imports are deterministic. A model call inside the engine
destroys replay equality — the same WorldView would not produce the same
result — and with it every guarantee in this document.
`EVOLAB_DESIGN.md:399-400` already states this for the sweep loop; extend it to
the whole engine and enforce it with the import guard of §2.6(1).

### 9.2 Deterministic (no model, ever)

`analyze()` and all five phases; every system's `propose()`; every adversary;
pricing, de-vig, ratings, LOCK evaluation, staking; settlement and grading; the
review records; calibration; the battery, placebo, CSCV, SPA, ceiling; the
promotion gates; the alpha registry; all capture.

### 9.3 Sonnet — high volume, cheap, mechanically checkable

- Implementing modules against a written contract (most of §12's packets).
- **Generating hypothesis and genome specs in bulk** as structured JSON
  conforming to `funnel.validate_spec` / `genome.validate`. A bad proposal
  costs a population slot, not correctness, because it goes through the
  identical pre-registration, battery and ceiling as an enumerated one.
- Writing per-family `settle` functions and grading adapters from the rulebook.
- Drafting mechanism prose for registry entries (the `MIN_MECHANISM_WORDS`
  gate), for Opus or the owner to approve.
- Narrative end-of-day summaries **derived from** deterministic ReviewRecords.

### 9.4 Opus — low volume, high stakes, judgement

- Methodology: fitness definitions, placebo generator design, promotion floors,
  the multiplicity policy of §5.6, LOCK criteria research.
- **Adversarial review of any research read before it counts.** The ops map
  found this gate exists as prose and one real precedent (V3
  `transaction_first_seen` failed review on nine findings, was corrected, and
  passed a second review) with no code enforcing it.
- Designing new adversaries — the idea is Opus, the adversary is deterministic code.
- Judging whether a claimed ceiling clear is real.
- Post-mortems on promoted-then-demoted systems.

### 9.5 Fable — orchestration

- Drives `src/factory/dispatch.py` and `data/factory/queue.jsonl` so dispatch is
  a **record**, not a memory. Today every lane is a session narrating manual
  delegation; there is no dispatcher.
- Enforces gates: refuses to advance a system whose gate evidence is missing.
- Budget enforcement: credits against `DAILY_ENVELOPE`, LLM spend against a new
  `LLM_BUDGET_PER_CYCLE` constant with the same hard-stop shape as
  `CREDIT_FLOOR`.
- Cross-lane reconciliation and the pinned-read discipline.

### 9.6 The role files that need to exist

Six `.claude/agents/*.md` exist, all `model: opus`, all execution workers —
the exact inversion of the vision. Add `sonnet-implementer.md`,
`sonnet-proposer.md`, `fable-orchestrator.md` using the existing
OBJECTIVE/WHY/INPUTS/BOUNDARIES/DELIVERABLE/ACCEPTANCE template, and add a
machine-checkable `validator_verdict` field that a research read must carry
before it counts as final. Every LLM-proposed spec carries
`proposer: {model, cycle, cost_usd}`, which turns the plan's own open question
— *do agent-proposed genomes outperform grammar-enumerated ones per unit cost?*
— from rhetoric into a measurement.

---

## 10. Capture now

The organizing rule, which subsumes every capture-now list across the nine maps:

> **Every PRICE is irrecoverable. Every FACT about a game is usually
> recoverable. Every TIMESTAMP of when something became knowable is
> irrecoverable.** Rank by that, then by cost.

### P0 — free, this week

1. **Persist `all_books` for spreads, totals and F5.** `normalize_event` builds
   them for six market keys on every capture (`odds.py:612-629`);
   `multibook_rows` keeps only `h2h` (`snapshots.py:177`). Five markets of
   multi-book depth are computed and discarded every run at **zero** marginal
   credit cost. Highest-leverage single fix in the entire map set.
2. **MLB StatsAPI per-game batter and pitcher box lines**, forward daily plus a
   2023-24 backfill. Free, keyless. Without it no batter prop can ever be
   settled, backtested, or self-reviewed — it is the grading substrate for the
   largest market surface in the vision, and it is on no existing list.
3. **2023-24 historical weather via Open-Meteo `fetch_archive`.** The capability
   exists in the codebase and has simply never been called for the past. Free,
   keyless, no expiry — but run it now rather than assuming it stays available.
4. **Park `orientation_deg` for all 30 parks.** `None` for every park by design
   today, which makes wind direction unclassifiable in/out/cross. A one-time
   static research task that unlocks a whole environment feature family both
   forward *and retroactively*, once (3) lands.
5. **Wire `transactions.jsonl` into `pointintime.INPUTS` and the WorldView.**
   27,053 rows spanning the full 2023-24 window, including 1,768 IL placements
   and 2,554 activations, sitting complete and referenced by no feature. Doing
   this before the factory searches avoids a later re-audit of the
   probable-pitcher kind.
6. **Record engine timing on every run.** The Phase 2B run's wall clock is
   permanently unrecoverable; the next one need not be.
7. **Reconcile the credit balance and tier** against `COLLECTION_POLICY.md`
   (53,083 vs ~99,634). Explainable from the vendor's billing history today;
   not reconstructable from this repo after a few more cycles.
8. **Ledger schema v2** (§7.1). Every day the current schema runs is a day of
   forward evidence in a shape the 300-selection gate cannot count.

### P1 — cheap, this month

9. **F5 spreads and totals** on the named-event pass that already runs; the
   parser exists and has never been asked for them.
10. **Denser F5 close coverage** — 26 of 73 games today.
11. **Protect the forward timestamp captures**: `rosterwatch` lineup/probable
    brackets, `umpirewatch` crew reveal (verified 3.6-4.6h pre-pitch), per-tick
    weather. 2023-24 has *zero* lineup-posting timestamps; a missed forward day
    is permanently lost, and `RUNBOOK.md` already states missed windows are
    never backfilled.
12. **The dense 15-minute pre-game snapshot grid inside the last three hours.**
    This is what makes fine-grained decision points possible for 2026+; without
    it the two-rung ladder that 2023-24 forced becomes permanent.
13. **Prop repricing evidence in the T-30m slot** — roughly half of it is never
    observed by construction under the current cadence. This evidence is
    leaking today, not hypothetically.

### P2 — budgeted, owner sign-off

14. **Batter prop listings and prices** — the largest irrecoverable market
    surface. Every day is a day of point-in-time prop board that cannot be
    bought back honestly later.
15. **Team totals and alternate lines** listing + repricing timestamps.
16. **SGP and parlay prices for declared leg sets** — the only way the book's
    correlation model can ever be measured against your own (§11.6).

### P3 — operational evidence, free but perishable

17. **The first real firing of `forward-capture.yml`** once the default branch
    is repointed: whether it collides with a still-live in-session Routine is a
    one-time-observable race.
18. **The L16 pinned-read addendum** (commit + nine store hashes) — the only
    worked example of a correct pinned read; without it the next lane has only
    the prose rule.
19. **`OVERNIGHT_RUN.md`'s missed-capture-window log** — the sole surviving
    record of when and why capture gaps happened.

---

## 11. Where the vision can be made better

Ten arguments. Each is a place where following the description literally would
produce a worse system than following its intent.

### 11.1 "Search the entire board" is only honest as a two-phase engine

If a system sees prices while forming a view, "which market best expresses the
advantage" collapses into "which line looks softest". That backtests
beautifully and is worth nothing — it is MARKET_SELECTION_ADVANTAGE, which this
project has already named and refused in one narrow place
(`decide.py::_select_market`). **Make the price-blind proposal phase structural**
(a `PriceBlindWorldView` with no board attribute), not a convention. This is the
single change that converts the owner's most ambitious requirement from a
heuristic into a mechanism.

### 11.2 Most of the board cannot be backtested, and pretending otherwise is the main way this project could fool itself

2023-24 holds moneyline and totals and one F5 snapshot per game. Run lines,
alternates, team totals, props, derivatives and parlays were **never polled**
and are **not purchasable**. So "replay whole seasons with the same engine" is
achievable for roughly 2 of 15+ market families and structurally impossible for
the rest.

The right response is not a synthetic backfill and not silence. It is: the
*engine* is identical everywhere, the *evidence window* is declared per market
family and published, and the forward clock starts for every family today. That
reframes the roadmap — **capture breadth is more urgent than research depth**,
because research on h2h can be done in 2028 and 2026's prop board cannot.

### 11.3 "Thousands of competing systems" is a multiplicity problem before it is a compute problem

Compute is nearly free in the bitset representation (§8.2). Statistical validity
is not. Thousands of correlated systems over ~4,800 games against a 4.5% house
edge will manufacture spectacular winners by construction, and a BH-FDR
correction against a raw count of systems searched is close to vacuous when the
systems are correlated. Report the **effective number of tests** from selection
overlap alongside the raw count, always both.

And the strategic implication: **scale the substrate before scaling the
population.** Phase 2B searched 8,811 systems over 6 features and 1 market and
found nothing, which is roughly what should have been expected. Ten times the
population over the same substrate would mostly buy better overfitting; ten
times the features and markets is where the information actually is.

### 11.4 Movement fitness should not be primary

A system can beat the close systematically by betting into stale books. That is
execution quality, not prediction, and it is exactly what `prices.py`'s
mandatory non-EV label exists to keep separate. Primary fitness should be
calibrated log-loss against outcome versus the de-vigged market, with realized
return at the entry price as the second axis and CLV as a decay diagnostic only
— which is what `MASTER_PLAN.md` §27 already says and what `sweep.py`'s default
does not do. This may be part of why Phase 2B found nothing, and that belongs in
the re-run's write-up.

### 11.5 LOCK must be a conjunction with a published base rate, not a top rating tier

A threshold-shaped LOCK guarantees LOCKs exist every day regardless of whether
any are deserved — the top of today's list is always the top of today's list.
Define it as the conjunction in §2.5, publish the base rate, and treat a LOCK
rate above ~2% of candidates as a defect to investigate. Most nights should
have zero. A product that says "no locks tonight" four days out of five is more
credible than one that never does, and it is the only version that survives
contact with the losers-published constraint.

### 11.6 Parlays are a pricing-efficiency problem, not a joint-probability problem

Your joint estimate matters only relative to the book's. For uncorrelated
cross-game legs the book multiplies and the vig compounds, so a two-leg parlay
needs roughly twice the per-leg edge to match two singles — mostly a strictly
worse product, and the design should say so up front rather than searching for
an exception.

The real opportunity is where the book's **correlation model** is wrong: SGP
legs priced as independent that are not, or as correlated that are not. So the
measurable object is `book_implied_correlation` versus `your_estimated_correlation`,
recoverable from the SGP price against the product of the leg prices. That makes
parlays a falsifiable research program with a defined instrument, rather than an
open-ended search over an exponentially large space — and it names the capture
requirement precisely: SGP prices for **declared leg sets**, not for everything.

### 11.7 The forward ledger currently cannot satisfy its own unlock condition — fix it before any research

Unlock condition 3 is "300+ forward selections". The ledger has 144
recommendation rows, **zero of them selections**, no rating, no chosen book, no
execution price, no system id, and a one-row-per-game-ever rule that forbids
recording a changed verdict when a lineup posts. Even if an edge appeared
tomorrow, the record being accumulated is not the shape the gate requires. This
outranks every research task in priority, and it is a two-day job.

### 11.8 "Never force quantity" needs a mechanical counterpart

Pre-register an `expected_selection_rate` per system at promotion and trip-wire
on the realized rate. Without it, "0..N, never forced" is a good intention that
a bug or a data shift silently violates for a month before anyone notices.

### 11.9 The engine should be sport-neutral at the contract from day one

`docs/MULTISPORT_AUDIT.md` did the hard analysis; this is how it is cashed in.
`src/engine/analyze.py` must never import anything baseball — no innings, no
lineups, no `game_pk` semantics. Baseball lives in the assemblers, the sections,
and the market universe. It costs almost nothing now and is very expensive to
retrofit after the factory has thousands of systems referencing MLB-shaped
fields.

### 11.10 Add a "no new information" refusal

Between two capture ticks where nothing changed but the clock, the engine should
return the previous result by reference rather than re-deciding. Otherwise the
ledger fills with duplicate candidates and the forward selection count inflates
without new evidence — a quiet path to 300 that would not survive scrutiny.
Identity is the WorldView digest, which already exists
(`replay.py::worldview_digest`).

### 11.11 One thing the description gets exactly right, worth protecting

"Point-in-time integrity sacred, losers published, price improvement is never
EV, the Ranker publishes nothing until the gates clear." Every one of those is
already load-bearing in code — `ENGINE2 = None` with a test that fails on the
word "edge", `prices.py`'s mandatory label, `pointintime.py` refusing rather
than warning, `replay.py` refusing sealed 2026 by name. **No part of this design
weakens any of them, and the expansions in §6 must not be allowed to become a
reason to.** The one clarification: the gate is a *publication* boundary, not an
*engine* boundary. The engine must always compute the rating and record it,
because that is how the forward record accumulates the evidence the gate
requires. Gating the computation would make the gate unopenable.

---

## 12. The first two weeks, in packets

Ten packets. Each names its owner (deterministic / Sonnet / Opus / Fable), its
gate, and a mechanical acceptance test.

### Week 1 — make the waist exist, stop the free bleeding

| # | Packet | Owner | Days | Acceptance |
|---|---|---|---|---|
| **P1** | `src/engine/markets.py` — `MarketRef`, `Selection`, `Quote`, `MarketBoard`, `MarketFamily`, `MarketUniverse` | Sonnet | 1 | Round-trips every market key in `odds.py`; canonical `key` is stable across runs and process restarts; golden-file test |
| **P2** | Persist `all_books` for spreads/totals/F5 in `snapshots.multibook_rows` | Sonnet | 1 | A live capture writes >1 market key; **measured zero credit delta** against `credit_log.jsonl` before/after |
| **P3** | `src/engine/worldview.py` — generalize the WorldView; **recursive** forbidden-name refusal; `Section` + grades; `PriceBlindWorldView` | Sonnet | 2 | All existing evolab tests pass through an adapter; a nested `{"starter":{"result":...}}` injection raises `WorldViewError`; accessing `.board` on a `PriceBlindWorldView` raises |
| **P4** | `docs/ENGINE_CONTRACT.md` — frozen signatures, the five purity rules, the conformance-test spec | Opus | 1 | Reviewed; defines the live/replay digest-equality test precisely enough to implement without further decisions |
| **P5** | `src/engine/analyze.py` waist + `GenomeSystem` adapter over `evolab.decide` | Sonnet | 2 | For all 8,811 Phase 2B genomes on a sampled 200 decision points, `analyze()` selections equal `decide()` selections **exactly**; determinism test passes under shuffled dict order |

### Week 2 — make the record countable and the loop real

| # | Packet | Owner | Days | Acceptance |
|---|---|---|---|---|
| **P6** | Ledger schema v2 — identity `(game_pk, T, system_id, selection.key)`, rating, entry book+price, counterarguments, system id, no-new-information refusal | Sonnet | 2 | Existing 427 rows migrate into v2 with nothing lost (old file untouched); `status()` reports forward-selection count against the 300 gate; a repeated tick with an unchanged digest writes nothing |
| **P7** | `src/core/timing.py` + timing block on `SweepReport` and every artifact | Sonnet | 1 | A small re-run records wall clock, CPU, decisions/sec and peak RSS per stage into the artifact |
| **P8** | MLB StatsAPI per-game batter/pitcher box lines: forward capture + 2023-24 backfill | Sonnet | 1 | 2023-24 backfilled; a pitcher-K prop **and** a batter-TB prop settle end-to-end from it |
| **P9** | Open-Meteo `fetch_archive` for 2023-24; park `orientation_deg` for 30 parks | Sonnet (Opus reviews the orientation source) | 1 | Wind classifiable in/out/cross for every 2023-24 game; `pointintime.INPUTS` entries added with grades |
| **P10** | `config/promotion_gates.json` + `src/factory/promote.py` evaluating it mechanically | Opus (design) + Sonnet (impl) + Fable (wiring) | 1 | Run against Phase 2B's best genome, it returns **REFUSED** naming the specific unmet gates and their current values |

**Parallel, owner-blocked, not a packet:** repoint the default branch and add
the `ODDS_API_KEY` repo secret so `forward-capture.yml` can fire. Until then the
hourly cadence still depends on an interactive session — the exact single point
of failure the externalization work was written to remove.

### Week-2 exit gate

The conformance test (live WorldView digest == replay-rederived digest) runs
green for **7 consecutive days**. If it does not, one of the two assemblers is
wrong and nothing downstream is trustworthy — that is the finding, and it is
worth more than any research result the same fortnight could produce.

---

## 13. Phases and gates beyond week two

| Phase | Weeks | Content | Gate to exit |
|---|---|---|---|
| **A — The waist** | 1-2 | §12 | Conformance green 7 consecutive days |
| **B — Substrate** | 3-6 | Bullpen, environment, injury and market-structure sections; F5 spreads/totals live; team-totals probe; registry grows from 6 features toward ~40 | Every new feature registered with mechanism, frozen sign, provenance, ladder derivation and grade; `assert_point_in_time` passes or the exposure is a **named** `EngineParameter` printed on every artifact |
| **C — The honest re-run** | 6-10 | Re-run the **identical** Phase 2B protocol on the expanded substrate, with outcome-calibration as primary fitness | Verdict published **either way**, in the alpha registry, with effective-tests alongside raw. Evolutionary operators unlock **only** on a genuine ceiling clear — evolab's own pre-registered rule, unsoftened |
| **D — The factory** | 10-16 | `src/factory/**`, adversaries, population correlation, dispatch, retirement | `promote.py` runs mechanically; effective-number-of-tests reported on every cycle; retirement reasons pre-declared |
| **E — Forward accumulation** | continuous from week 2 | Paper selections toward 300; bankroll simulation from 1,000 units; daily self-review | All four unlock conditions + owner sign-off. The Ranker publishes **nothing** until then |
| **F — Board breadth** | continuous from week 1 | Batter props, derivatives, parlays/SGP — each on its own forward evidence clock | Per-family: registered hypothesis, cost cap, PIT-honesty plan, and a working `settle` before a single credit is spent |

---

## 14. Product integration: V2, Bet Rating, Picks, LOCK

### 14.1 New contracts

Added to `src/analysis/contracts.py` beside the existing six, same frozen
dataclass + `field_capabilities` enforcement:

- `MarketCandidateContract` — one candidate as a customer sees it: selection,
  book, price, rating, evidence, counterarguments, the system's record. Gated.
- `PicksContract` — today's ranked candidates. Gated on `ENGINE2`.
- `SystemRecordContract` — the public record page for one system, **including
  losers**, its calibration curve, its n, its drawdown, its retirement history.
- `GateReadoutContract` — **not gated** (see below).

### 14.2 The gate as a shippable surface

`ranker.ENGINE2 is None` stays exactly as it is, test-pinned. Add:

```python
def publication_gate(surface: str) -> Gate:
    """PUBLISH or WITHHOLD, with the machine-readable reason.
    Lists each unlock condition and its CURRENT VALUE."""
```

The Picks page then renders **the gate itself**: a live, honest readout —
*"pre-registered discovery pass: not cleared. Falsification battery: not
reached. Forward selections: 41 of 300. Owner sign-off: not given."* — instead
of being absent.

This is shippable today, it is not misleading, it satisfies losers-published
ahead of time, and it makes the unlock **legible** rather than a promise. It is
also the surface most likely to build trust with a first customer, because it is
the one thing no competitor will ever show.

### 14.3 Bet Rating on a customer surface

A rating never appears alone. It appears with: the producing system's forward
calibration curve, its n in that probability band, its full record including
losers, and the counterarguments that were raised and not sustained. A star with
no record behind it is precisely the thing this project has spent a year not
doing, and the rating schema (§2.5) carries `band_n` and `band_ece` so the
surface cannot render one without the other.

### 14.4 Bet Check and the Analyzer

`betcheck.SUPPORTED_MARKETS` becomes a view over `MarketUniverse` entries with
status LIVE, so the refusal list maintains itself instead of drifting from the
price engine. The Analyzer's market section gains one block per LIVE family,
each carrying the same mandatory non-EV label that `prices.py` enforces today.

### 14.5 What stays refused

No real-money placement. No fabricated numbers. No price improvement described
as EV or edge, on any surface, for any market family — the label travels with
the arithmetic. Nothing from the sealed 2026 window. 2025 is tuning-only. The
Ranker publishes nothing while `ENGINE2 is None`, and changing that requires
the four conditions **and** the owner's signature, as a visible diff that fails
a test until the evidence exists.

---

## 15. Open questions for the owner

1. **Credit tier.** Full-board hourly capture is ~7,000-7,600 credits/day
   (~225k/month) and needs the 5M / $119-per-month tier. The forward prop and
   alt-line board is being lost daily at the current envelope. Approve the tier,
   or approve a narrower P2 list and accept which surfaces are permanently gone.
2. **Default branch.** `forward-capture.yml` cannot fire until the default
   branch moves off `claude/cowork-session-migration-tn3sx2`. Every hour until
   then depends on an interactive session.
3. **Primary fitness.** Switching `sweep.py` from movement to outcome-calibrated
   log-loss changes what "Phase 2B" means and requires a fresh registration.
   Confirm before Phase C.
4. **LOCK criteria.** §2.5 proposes a six-way conjunction with a published base
   rate. Approve, amend, or send it to Opus as a research question.
5. **Staking rule for the paper bankroll.** 1,000 units, day by day —
   quarter-Kelly (`staking.DEFAULT_KELLY_FRACTION = 0.25`) capped, or flat?
   This must be declared *before* the forward record starts, not chosen after
   seeing a curve.
6. **Batter props.** The largest irrecoverable surface. Starting capture costs
   ~3,000 credits/day and is not reversible in hindsight if declined.
7. **Sport neutrality now or later.** §11.9 argues now, at near-zero cost.
   Confirm, because retrofitting after the factory exists is expensive.

---

*Nothing in this document is evidence. Every capability claim cites a file, a
line, or a store; every number is measured or labelled as an estimate. The
design does not reduce the vision — it names the two places the data cannot
support it (historical board breadth, and decision-point granularity before
2026) and proposes forward capture rather than synthesis as the answer.*
