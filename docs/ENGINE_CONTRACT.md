# The Engine Contract — `src/engine/analyze.py`, the waist

Status: implemented per packet W8+W9. Frozen per
`docs/planning/synthesis-judge.md` §4.2 and
`docs/ARCHITECTURE_BETTING_ENGINE.md` §3–4. Where this document and either of
those disagree, treat the disagreement as a bug in this document, not
license to reinterpret the frozen contract.

## 1. What the waist is

One pure function:

```python
analyze(snapshot: PriceBlindSnapshot, board: PricedBoard, *,
        systems: Iterable[AnalysisSystem],
        adversaries: Iterable[Adversary] = DEFAULT_ADVERSARIES,
        config: EngineConfig = DEFAULT_CONFIG,
        registry_fingerprint: str = "",
        frame_fingerprint: str | None = None) -> Analysis
```

`Analysis.records` is a tuple of zero or more `DecisionRecord`s
(`src/ledger/records.py`), one per (system, selection) pair that survived
ATTACK, in RANK order. **Empty is a normal answer** — a board where every
proposal was vetoed, or where no system proposed anything, is not an error.

Live capture and offline replay call this function and nothing else. There
is no second decision path; a caller that reimplements PROJECT, ATTACK or
RATE outside `analyze()` is building a second waist, which is exactly the
failure `docs/ARCHITECTURE_BETTING_ENGINE.md` §1 diagnoses in the
pre-existing two-path system.

## 2. Purity

`analyze()` performs no I/O, reads no clock, draws no randomness, and
touches no global mutable state. Its only inputs are its own arguments; the
same `(snapshot, board, systems, adversaries, config)` produces a
byte-identical `Analysis` on every call, on every machine, forever. It
cannot tell whether it is running live tonight or replaying a game from
2023-04-11 — nothing in its body can distinguish the two.

`tests/test_engine_analyze.py::TestPurity` enforces this two ways: an AST
walk over the function's own source refuses `open`, `input`,
`random`/`time`/`datetime.now`-shaped calls, and a determinism test asserts
two calls with the same arguments produce identical `DecisionRecord.to_dict()`
output.

## 3. The price-blindness rule

`PriceBlindSnapshot` (`src/engine/snapshot.py`) is what a system's
`propose()` is handed. It is **structurally**, not procedurally, blind to
price: the dataclass declares no `board`, `quotes`, `price`, `consensus`, or
`friction` field at all — not `None`, absent — and `__getattr__` additionally
raises a named `AttributeError` for every name in `FORBIDDEN_PRICE_NAMES`,
so a system that tries a dynamic lookup (`getattr(view, "board", None)`)
gets a loud refusal, not a silent `None` it could branch on.

`tests/test_engine_snapshot.py::TestPriceBlindSnapshotStructural` proves
this by walking `dataclasses.fields(PriceBlindSnapshot)` (no forbidden name
is declared) and by reflecting over every live attribute name PROPOSE-side
code could think to ask for (none resolves to a `PriceObservation` or a
price-shaped payload).

`PriceBlindSnapshot` DOES carry two non-price, board-shaped facts a system
may legitimately need: `available_markets` (which markets exist) and
`books_by_market` (how many books quote each one). A book **count** is not
a price — it cannot be de-vigged, converted to a probability, or staked
against. These fields exist because the pre-existing evolab decision path
(`src/evolab/decide.py`) already gates eligibility and market routing on
exactly these two facts, and the equivalence obligation (§6) requires that
gate to keep working unchanged inside the waist.

`PricedBoard` is the other half — the `PriceObservation` rows for the same
game at the same instant. It is handed **only** to PROJECT, inside
`analyze()`'s own body; no `AnalysisSystem.propose()` ever receives it.

## 4. The five phases

1. **PROPOSE** — each `system.propose(snapshot.price_blind_view)` returns
   zero or more `Proposal`s: `(system_id, system_version, market_key, side,
   subject_kind?, subject_id?, line?, p_model?, thesis, evidence)`. A
   `Proposal` never carries a price field.

2. **PROJECT** — every proposal is priced against **every selection on the
   board its thesis covers** (matching `market_key`/`side`, and
   `subject_id`/`line` when the proposal names them). For each match, the
   engine reads `board.consensus(selection_id)` (the de-vigged average fair
   probability across every book quoting both sides), `board.best(...)` (the
   most favorable observed price) and `board.friction(...)` (vig, book
   count, staleness, dispersion). `edge_bps` is
   `round((p_model - consensus_fair) * 10_000) - friction_bps`
   — a **PROJECT-phase field on `DecisionRecord`**, distinct in name and
   meaning from `price_improvement_bps`, and never surfaced in a
   user-facing string as "edge" (`ARCHITECTURE_BETTING_ENGINE.md`: "price
   improvement is never EV or edge"; win probabilities are never
   published). `board.consensus()` returns `None` — consensus-undefined,
   never a silently assumed 0.5 — when fewer than `config.min_books` books
   quote both sides (guard M7).

3. **ATTACK** — every surviving candidate is passed to every registered
   `Adversary.attack(candidate, snapshot, board)`, which returns zero or
   more `Counterargument(adversary_id, cause, severity)`. A `FATAL`
   severity removes the candidate before RATE/RANK; the counterargument is
   still recorded (on the candidate, before removal — nothing is silently
   dropped). `MAJOR`/`MINOR` counterarguments survive onto the final
   `DecisionRecord.counterarguments`.

4. **RATE** — Bet Rating is **two separate numbers**, never blended into
   one scalar: `probability_quality` (how far the system's own stated
   `p_model` sits from a coin flip — never touches price) and
   `price_quality` (how much of the board's own de-vigged spread the quote
   captures — never touches the system's confidence). This is the
   Two-Ledger rule (`src/ledger/records.py`'s `ObjectiveView` /
   `FORBIDDEN_OBJECTIVE_FIELDS`) extended into RATE: a system's calibration
   quality must never be laundered together with the price it happened to
   get. Neither number, nor any label the engine emits, is ever called
   "edge" — `tests/test_engine_analyze.py::TestTwoLedger` enforces this on
   the rating dict's own keys.

5. **RANK** — a deterministic total order: `(-edge_bps, selection_id,
   system_id)`, ascending. No tie is broken by chance, dict order, or
   file-read order.

## 5. What a "system" and an "adversary" are

An `AnalysisSystem` (`Protocol` in `src/engine/analyze.py`) is anything with
an `id`, `version`, `spec_hash`, `declared_markets`, `declared_inputs`,
`min_grade`, `expected_selection_rate`, and a `propose(view) -> tuple`
method that reads only the `PriceBlindSnapshot` it is handed. A genome, a
hand-written rule, or a future model-origin system (barred from discovery
seasons per guard 5) are all systems as long as they satisfy this shape;
`src/engine/adapters/evolab_system.py`'s `EvolabGenomeSystem` is the
reference adapter.

An `Adversary` is anything with an `id` and an
`attack(candidate, snapshot, board) -> tuple[Counterargument, ...]` method.
Adversaries run in ATTACK, after PROJECT — they see the priced candidate
(including its consensus/friction) because vetoing "this book is stale" or
"this board is too thin" is inherently a price-shaped judgment; PROPOSE-side
systems never get this view. `docs/ARCHITECTURE_BETTING_ENGINE.md` names
the intended roster (StaleBook, ThinBoard, NonSimultaneous, Grade,
CorrelatedEvidence, MarketDisagreement, Sample, Regime, Friction).
`analyze()`'s own `DEFAULT_ADVERSARIES` stays `()` — the waist itself never
hardcodes an opinion about which adversaries a caller runs — but packet W11
registers the roster's first four in `src/engine/adversaries.py`, each with
its own registered `CAUSE` string, per the guard that a cause must be
registered, not invented ad hoc at veto time:

- **StaleBook** (`FATAL`) — the candidate's `friction.staleness_seconds`
  exceeds `max_staleness_seconds`: a quote this old is not a live tradeable
  price.
- **ThinBoard** (`FATAL`) — `books_at_decision` is below `min_books`: a
  consensus that formed off too few books is untrustworthy even though
  `board.consensus()` did not return `None` outright (guard M7).
- **PriceMovedAgainst** (`MAJOR`) — the candidate's price is worse (lower
  decimal payout) than a caller-supplied `reference_prices[selection_id]`;
  no I/O, no clock — the reference is data handed in by the caller, never
  fetched.
- **DegradedInformation** (`MAJOR`) — the snapshot's own
  `assumption_exposure` shows one of `src.core.asof.DEGRADED_SENTINEL_FIELDS`
  missing or below grade A, restating `src.core.asof.information_grade`'s
  rule against the coarser exposure counts ATTACK has to work with; the
  veto detail names the `ReplayLabel.DEGRADED_INFORMATION` it corresponds
  to.

`adversaries.DEFAULT_ADVERSARIES` is the tuple of all four with their
default thresholds. As of packet W11, `analyze()`'s own `adversaries`
parameter defaults to it: a call that omits `adversaries` entirely runs the
registered roster, resolved via a lazy import inside `analyze()`'s body
(`adversaries.py` imports FROM `analyze.py` for `FATAL`/`MAJOR`/
`Counterargument`, so importing the roster back at `analyze.py` module scope
would be circular). `analyze.py`'s own module-level `DEFAULT_ADVERSARIES`
constant is unchanged and stays `()` — it is the value used only when a
caller passes `adversaries=()` explicitly to run with none. This supersedes
this section's earlier statement that "`analyze()`'s own `DEFAULT_ADVERSARIES`
stays `()`" in the sense of the waist's *default behavior*; the constant's
own value is exactly as frozen. The explicit-argument path is unaffected:
`analyze(..., adversaries=custom_tuple)` or `adversaries=()` always wins over
the roster. NonSimultaneous, Grade, CorrelatedEvidence, MarketDisagreement,
Sample, Regime and Friction remain unimplemented — left to the packet that
registers each one's specific cause.

## 6. The equivalence obligation

The waist must answer identically to `src.evolab.decide.decide_with_reason`
on the same genome and the same real decision point — this is the frozen
requirement (`ARCHITECTURE_BETTING_ENGINE.md` §3: "Live and replay call this
function and nothing else", extended here to mean the new waist and the
pre-existing evolab path must never silently diverge in the window where
both exist).

`scripts/engine_equivalence.py` proves this by wrapping the exact same
`Genome` objects `enumerate_genomes()` produces in
`EvolabGenomeSystem` (which calls `decide_with_reason` directly — it does
not re-derive the genome's rules), running both `analyze()` and
`decide_with_reason()` over the same real 2023 replay decision points, and
asserting the selected `(market_key, selection_id)` agree whenever
`decide()` plays. **Any divergence found is, by construction, a bug in the
adapter or in `analyze()`'s PROJECT/RANK logic — never a bug in `evolab`**,
because the adapter calls evolab's own function rather than a parallel copy
of its rules.

See the run report in the packet's commit message / task report for the
scale actually executed and its result.

## 7. Provenance

`PriceBlindSnapshot.assumption_exposure` (built by `.from_asof()` from a
`src.core.asof.Snapshot`'s per-field `known_at_grade`) and
`PricedBoard`'s friction/consensus numbers all flow through to the
`DecisionRecord`'s `assumption_exposure` and `friction` fields unchanged —
`analyze()` never recomputes or discards a provenance fact it was handed.
`known_at_grade` on the record is the coarsest grade among the snapshot's
exposed fields (worse grade wins), never silently rounded up to A.
