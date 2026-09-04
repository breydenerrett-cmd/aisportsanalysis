# Strategy-factory scale design

Owner directive, 2026-09-04. This is infrastructure so that scaling the
strategy population is *meaningful*, not a plan to generate six figures of
strategies by trivial threshold perturbation. `src/evolab/genome.py` already
caps genome complexity (`MAX_SIGNALS`, a fixed three-rung threshold ladder,
no direction field); nothing here loosens that cap. The problem this
document solves is different: once the population is large, most of its
"strategies" are the same handful of underlying wagers wearing different
genome labels, and reporting on the population without accounting for that
is reporting noise as if it were sample size.

## 0. What already exists, and what is missing

The ~11,088-genome historical sweep (`src/evolab/sweep.py`,
`data/research/evolab/sweep-*.json`) computes, per world, per strategy: a
selection count, per-block and overall mean movement/ROI. The masks that
record *which games* a strategy selected (`WorldFitness.masks`, a
`(away_bitmask, home_bitmask)` pair per strategy) are real, in-memory
`_side_profiles`/`_resolve_ties` output — but `SweepReport.to_dict()` never
serializes them. The on-disk artifact is aggregate statistics only; it has
no persisted decision-level record, so today there is no way to ask "how
many of these 11,088 strategies actually made the same bet on game X" from
the artifact alone. That is the gap sections 1-3 close.

## 1. Data model

### 1.1 Canonical wager

A **wager** is one side's bet on one market for one game at one decision
instant. Two strategies that fire on the same side of the same market of the
same game at (effectively) the same price are not two pieces of evidence —
they are one bet counted twice. The canonical wager id is:

```
wager_id = sha256(json.dumps({
    "game_pk": <int>,
    "market": <str>,       # e.g. "h2h", "f5_h2h", "total"
    "side": <str>,         # "home" | "away" | "over" | "under"
    "line": <float|None>,  # None for moneyline; the posted line for spread/total
}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
```

**What is in the key, and why:**

- `game_pk` — the game is the irreducible unit; two strategies betting the
  same side of the same game are the same real-world exposure regardless of
  what feature triggered them.
- `market` — `h2h` and `f5_h2h` are different bets on the same game (they
  can even disagree), so they are different wagers by construction.
- `side` — the actual position taken. This is what correlates PnL, not the
  signal that produced it.
- `line` — required for spread/total markets, where "home -1.5" and
  "home -2.5" are different exposures at different break-evens even though
  `side` matches. `None` for moneyline, where there is no line to key on.

**What is deliberately NOT in the key:**

- **Price.** Price moves continuously and two strategies rarely see the
  exact same tick even when they fire on the identical game/market/side —
  keying on price would silently manufacture near-duplicate wager ids for
  what is obviously the same bet, defeating the entire point of dedup. Price
  is stored as a *field on the wager*, not part of its identity. If price
  dispersion across strategies claiming the same wager ever becomes large
  enough to matter (e.g. two strategies fire hours apart), that is a
  timing/decision-instant question for `replay.py`'s `WorldView`, not a
  reason to fragment the wager key.
  - A price-bucket key was considered and rejected: any bucket width is an
    arbitrary tuning knob on the dedup statistic itself (narrow buckets
    approach "no dedup at all"; wide buckets hide real distinct decisions).
    A bucketed key would let a bad-faith actor pick the bucket width that
    makes the population *look* more independent than it is — exactly the
    kind of threshold a gate must not be tunable through after the fact.
  - Decision instant is likewise excluded from the key for the same reason
    CONSENSUS_EXECUTION is defined as one resolved price per game per world
    in `sweep.py`: within one world, every genome sees the same instant.
    Cross-world/live timing granularity is a `replay.py` concern.
- **Strategy identity.** By definition — that is the many-to-one relation
  this table exists to expose.

### 1.2 Wager table (canonical, append-only)

One row per unique `wager_id`, written once, never mutated (only appended —
see `src/evolab/wagers.py`):

| column | type | notes |
|---|---|---|
| `wager_id` | str (hex64) | primary key |
| `game_pk` | int | |
| `market` | str | |
| `side` | str | |
| `line` | float \| None | |
| `price` | float \| None | American odds observed when first recorded; informational, not identity |
| `world_id` | str \| None | which replay/sweep world first recorded this wager (audit trail) |
| `first_seen_at` | str (ISO8601) | append time, not a market timestamp |
| `source` | str | e.g. `"sweep:<enumeration_spec_hash>"`, `"forward_ledger"` |

Append-only because a wager, once it happened, does not change; a second
strategy claiming the same `wager_id` is a reference, not a rewrite (`set`
would silently let a later writer overwrite the first observation's price
and provenance — `wagers.py`'s store rejects any conflicting re-write of an
existing id and raises rather than picking a winner silently, matching
"no rescue by threshold change / no silent overwrite" elsewhere in this
codebase).

### 1.3 Strategy → wager reference table

One row per (strategy, wager) pair actually selected:

| column | type | notes |
|---|---|---|
| `strategy_id` | str | genome hash, `Genome.strategy_id` |
| `wager_id` | str | FK into the wager table |
| `world_id` | str | which world/sweep this selection came from |
| `enumeration_spec_hash` | str | which population this strategy belongs to |

This is the join table that makes "unique wagers vs. total strategy
decisions" a `COUNT(DISTINCT wager_id)` vs `COUNT(*)` query, and makes
family/correlation clustering (section 2) a self-join on `wager_id`.

### 1.4 Decision dedup statistic

For a strategy set `S` in one world:

```
total_decisions   = sum(len(selections(s)) for s in S)
unique_wagers     = len({wager_id for s in S for wager_id in selections(s)})
dedup_ratio       = unique_wagers / total_decisions   # 1.0 = no overlap at all
```

`unique_wagers` is the honest denominator for "how much independent
evidence does this population contain" — `total_decisions` alone conflates
population size with information content, which is exactly the six-figures-
of-trivial-perturbation failure mode this task exists to prevent.

## 2. Family / correlation clustering

**Method: Jaccard similarity on decision sets, not correlation of returns.**
`overlap.py` implements this.

- `J(A, B) = |wagers(A) ∩ wagers(B)| / |wagers(A) ∪ wagers(B)|` where
  `wagers(s)` is the set of `wager_id`s strategy `s` selected in a world.
- **Why Jaccard over return correlation:** two strategies that select
  *different* games can still have correlated returns by chance (shared
  market regime, correlated placebo noise — exactly what `cscv.py`/`spa.py`
  already exist to catch at the population level). Jaccard measures the
  mechanical fact this document is actually about — do two strategies make
  the *same bets* — which is prior to and independent of whether those bets
  happened to win together. Return correlation is a downstream consequence
  of decision overlap (two strategies with `J=1` have identical returns by
  construction) plus market-wide correlation this project's placebo suite
  already isolates; computing it again here would duplicate `cscv`/`spa`
  machinery under a different name rather than adding information.
- **Clustering:** single-linkage over pairwise Jaccard with a fixed
  threshold (`FAMILY_THRESHOLD = 0.8`, named and justified in code, not a
  free parameter tuned per report) — two strategies join a family if
  `J >= 0.8`, i.e. at most 1 in 5 of their combined decisions differ. A
  family is a connected component of that graph. `0.8` is deliberately
  conservative (a high bar for "this is the same trade"); a lower threshold
  is a knob that could be tuned to manufacture apparent diversity, so it is
  fixed and stated here rather than swept.
- **Limits, stated plainly:** Jaccard on a single world says nothing about
  whether the overlap generalizes out-of-sample; it is a description of
  *this population's mechanical redundancy*, not a promotion criterion.
  Two strategies with `J=0` can still be economically identical (e.g.
  betting opposite sides of a market that always disagrees), which Jaccard
  cannot see — it measures decision-set overlap, not economic
  substitutability. Pairwise Jaccard is also `O(n^2)` in the number of
  strategies; §5's storage plan keeps `n` per computed cluster batch bounded
  (see "storage estimate").

## 3. Effective independent sample size

**Method: family count, not strategy count, is the primary effective-N
statistic**, with a documented, conservative fallback for within-family
credit:

```
N_effective_families = number of connected components (families) from §2
N_effective_credit    = sum over families of (1 + log2(family_size))
```

- **Why families-count is primary:** it requires no distributional
  assumption at all — it is a graph fact about the decision sets actually
  observed. It is deliberately the *most conservative honest floor*: a
  family of 500 near-identical strategies counts as one independent trial,
  which is correct if their shared decision set is what drives their shared
  result (the null this whole design exists to rule out).
- **Why the log2 credit term exists, and why it is secondary:** collapsing
  every family to exactly 1 regardless of size throws away real information
  when a family's members differ enough (below the `J=0.8` join threshold)
  to carry *some* independent signal even while sharing infrastructure. The
  `1 + log2(size)` form is a standard diminishing-returns discount (each
  doubling of a family's size buys one more "effective trial") chosen
  because it is monotonic, bounded in growth, and requires no fitted
  parameter — not because it is derived from a model of the actual
  dependence structure, which this project does not have. **State this
  plainly wherever `N_effective_credit` is reported: it is a heuristic
  discount, not a calibrated effective-sample-size estimator** (contrast
  with, e.g., a Newey-West-style autocorrelation-adjusted N, which would
  need a return-series model this design does not attempt). CSCV/SPA
  (`cscv.py`, `spa.py`) remain the actual multiplicity-correction gate for
  promotion; `N_effective_*` here is reporting context for humans reading a
  factory-scale report, not a new gate and not a substitute for CSCV/SPA.
- **Frozen denominator:** `N_effective_*` is computed once per
  `enumeration_spec_hash` (the population is enumerated deterministically,
  see `genome.py`'s enumeration-order contract) and stored alongside that
  hash. It is never recomputed against a shrunken or grown population after
  the fact — a report that wants a different N enumerates a new, separately
  hashed population and reports both numbers side by side, exactly as
  `docs/RESOURCE_POLICY.md`'s "no rescue by threshold change" already
  requires elsewhere in this program.

## 4. Retirement / mutation / replacement lifecycle

No stage below is bankroll-only — a strategy's price/ROI drifting is
necessary but never sufficient by itself; every transition also requires a
structural or statistical condition tied to the actual gates this program
already runs (CSCV/SPA/ceiling in `cscv.py`/`spa.py`/`ceiling.py`, the
funnel pre-registration in `src/research/funnel.py`).

| stage | trigger (ALL must hold) | evidence artifact |
|---|---|---|
| **retire** | (a) fails the CSCV/SPA gate on its most recent scheduled retest (§ below), AND (b) its family (§2) has at least one still-passing member covering the same decision set, so retiring it loses no unique wager coverage | retest `SweepReport` + family membership at retest time |
| **mutate** | passes eligibility/complexity checks but sits below `FAMILY_THRESHOLD` similarity to every current family AND its `n_selected` (design section 8's minimum) is below `DEFAULT_MIN_SELECTIONS`, i.e. it is under-sampled rather than falsified — mutation (widen threshold rung, add/drop one signal within `MAX_SIGNALS`) is proposed, never silently substituted | proposal record: parent `strategy_id`, mutation diff, reason code |
| **replace** | retired strategy's family lost its last passing member (a true coverage gap) AND a proposed mutation (above) or an existing un-tried genome from the same enumerated space closes that gap under a fresh CSCV/SPA run pre-registered *before* that run, per `funnel.py`'s existing direction-before-results discipline | fresh `SweepReport` for the candidate, referenced by the retirement record it replaces |

No stage is triggered by ROI or movement alone. A strategy with a bad recent
block but a still-passing CSCV/SPA gate is not retired — noisy is not the
same as falsified. Every transition is a row in an append-only lifecycle
log (`strategy_id`, `from_stage`, `to_stage`, `trigger`, `evidence_ref`,
`timestamp`) — the audit trail requirement — never an in-place status flip
with the prior state discarded.

## 5. Scheduled retest cadence

- Every strategy currently in `active` stage is re-run against the sweep
  machinery (`sweep_world`, unchanged) on a fixed cadence tied to the
  existing block structure already used for CSCV (`DEFAULT_N_BLOCKS`) — a
  retest fires when enough new game-days have accumulated to form one full
  new block (today's default block width), not on a wall-clock timer, so
  the retest cadence scales with actual new evidence rather than calendar
  time.
- A retest is a normal `run_sweep` invocation against the extended world; it
  produces a new content-addressed `SweepReport` and is compared against the
  strategy's prior CSCV/SPA verdict. It never edits the prior report — retest
  results accumulate, they do not overwrite.
- Retest results feed §4's retire/replace triggers directly; they are not a
  separate promotion path.

## 6. Storage estimate and hot/cold split

Per `docs/RESOURCE_POLICY.md`: storage is purchasable and must never be the
reason to cap the strategy population; normalize records and split hot from
cold instead. Concretely for this design:

- **Wager table is the hot, canonical store.** ~4,800 games/season x a
  handful of markets x 2 sides is on the order of 10^4-10^5 rows *total*,
  independent of strategy-population size — this is the entire point of
  wager-level dedup: the wager table does not grow when the strategy count
  grows, only the reference table does.
- **Strategy → wager reference table scales with total decisions, not with
  unique wagers** — at 11,088 strategies x up to a few thousand selections
  each, this is the table that actually grows with population size (10^7-10^8
  rows at six-figure population scale). It is a thin (4-column) table and
  compresses well (append-only, sorted by `wager_id`); this is the "cold"
  side of the split — queried in bulk for overlap/clustering jobs, never
  touched by live capture.
- **Per-world aggregate `SweepReport` JSON artifacts** (`data/research/evolab/
  sweep-*.json`) stay as-is — hundreds of KB each, one per world per
  enumeration, already namespaced under `data/research/evolab/` per
  `sweep.py`'s existing `ARTIFACT_ROOT` contract.
- **Migration plan:** nothing existing is deleted or rewritten. New tables
  are additive. A one-time backfill job (not built in this slice — flagged
  as follow-up work) would replay each existing `sweep-*.json`'s world
  through `sweep_world` again (deterministic, same masks) to populate the
  wager and reference tables retroactively; the existing JSON artifacts
  remain the audit-of-record for the aggregate statistics they already
  contain. This slice's `wagers.py`/`overlap.py` are built and tested
  standalone against synthetic input precisely so that backfill is a later,
  separate, reviewable step rather than something rushed into this change.

## 7. What this slice ships (implementation)

- `src/evolab/wagers.py` — canonical `wager_id` (§1.1), an append-only
  in-process/JSON-file store that rejects conflicting re-writes.
- `src/evolab/overlap.py` — unique-vs-total decision counts (§1.4) and
  pairwise Jaccard (§2) over a strategy set's decision sets.
- `scripts/factory_overlap_report.py` — deterministic report script: reads
  the existing sweep artifact(s) under `data/research/evolab/` if present,
  and writes `docs/FACTORY_OVERLAP_REPORT.md`. Because `SweepReport` does
  not currently persist per-strategy decision sets (see §0), the script
  reports what it *can* honestly compute from the artifact today (counts of
  strategies, worlds, and an explicit statement that decision-level overlap
  requires the masks that sweep.py computes but does not yet serialize) and
  exits 0 either way, never fabricating an overlap number it cannot support.
  This gap — `WorldFitness.masks` computed but not persisted — is the
  natural next slice once this data model lands, flagged here rather than
  patched into `sweep.py` under this task's stated boundary (no changes to
  live capture, ledger, or settlement code, and this task's scope is the
  new tables, not `sweep.py` internals).
