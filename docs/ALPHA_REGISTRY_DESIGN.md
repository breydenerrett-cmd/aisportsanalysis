# Alpha registry — design note (orchestrator decision record)

2026-09-02. Design only; implementation is a Sonnet packet after this is
reviewed. Named `src/research/alpha_registry.py` to avoid collision with
`src/evolab/registry.py`, which is a per-feature SIGN pre-registration
store (prevents screen-then-flip gaming) — a different object.

## Why this exists

Per-family BH-FDR (V1 21, V2 5, V4 6, V5 3) and per-sweep SPA/CSCV/placebo
ceilings (Evolab Phase 2B, 8,811 genomes) each control error WITHIN their
own scope. Nothing accumulates search effort ACROSS families and sweeps
over calendar time. At the master plan's 100x scale that gap is the
belief-manufacturing risk: a nightly cycle can re-spend the same evidence.
The registry is the one ledger that answers "how hard have we already
searched, on what data, against what outcome" — and it must answer it
honestly on day one, which is why the denominator decision below is
recorded before any migration script runs.

## Decision 1 — the denominator

docs/RESEARCH_CATALOGUE.md ("Counting the families") documents four
inconsistent counts: 13 (a double count), 25 (detector/spec level), 35
(registered-hypothesis level), 21 for V1 alone. Ruling:

- **Canonical unit = the registered hypothesis** as frozen in each
  family's registration file (`evidence/hypothesis_family.json` for V1 =
  21; V2 = 5; V4 = 6; V5 = 3 → **35**). This is the level at which
  pre-registration and FDR were actually declared, so it is the only
  level at which "spend" is well-defined.
- The detector/spec level (25) is recorded as a secondary grouping key
  (`spec_id`) on each entry, never as the denominator.
- The "13"/"27" roll-ups are marked erroneous in the migration report.
- Evolab Phase 2B is ONE registry entry of kind `sweep` with
  `candidates_evaluated = 8811`, carrying its SPA p-value, CSCV/PBO, and
  placebo-percentile outputs as the within-sweep correction. A sweep's
  8,811 genomes are NOT 8,811 hypotheses for cross-family purposes — the
  within-sweep machinery already paid for them; the registry charges the
  sweep as one pre-registered search with a recorded internal multiplicity.

Rationale for the last point: charging each genome at the family level
would double-count (SPA already controls the family-wise error of the
sweep), while charging nothing would hide the search. Recording the sweep
with its internal multiplicity and its ceiling verdict is the honest
middle: any later reader can see exactly how much of the h2h board was
searched and that it came back below noise.

## Decision 2 — what a row is

Append-only JSONL, `data/research/alpha_registry.jsonl`, git-tracked
(evidence). One row per registered unit, written at REGISTRATION, then
one `verdict` row appended when the unit is read. Never edited.

```
{kind: "hypothesis" | "sweep" | "audit",
 id, family, spec_id (secondary), market, sport: "mlb",
 registered_utc, data_window: {discovery, replication, sealed_untouched: true},
 direction, feature_expr_hash (semantic hash v0 — see D3),
 alpha_declared (family q or sweep threshold), status: "registered",
 source_doc, code_hash}
{kind: "verdict", id, read_utc, result: "null" | "false_positive" |
 "candidate" | "survivor" | "audit", p, effect, ci, battery_version,
 within_sweep: {spa_p, pbo, placebo_pct} (sweeps only),
 forward_window: {start, n, pending: true|false}}
```

Migration seeds: the 35 registered hypotheses (from the four registration
files), the Phase 2B sweep, the M1–M5 market-structure tests (five
`hypothesis` rows under family V2 — already counted in the 5), the Elo
benchmark (kind `audit`, not a hypothesis), and V3's admitted classes
(each class = one hypothesis, 4 rows, family V3; two are below floor →
status registered, no verdict).

## Decision 3 — similarity hashing v0

Exact `spec_hash` (already in src/evolab/genome.py) catches duplicates
only. v0 semantic hash = sha256 of the SORTED set of (feature, operator,
market, direction) atoms with numeric thresholds bucketed to the
family's declared grid. Two units with the same v0 hash are the same
search and share one alpha charge. Correlation between DIFFERENT hashes
(the genuinely hard problem, Appendix B) is deferred: the registry
records the hash so the accounting can be tightened later without
rewriting history. This is explicitly a floor on honesty, not a ceiling.

## Decision 4 — how the registry is consumed

- The battery's priors and every new family's registration read
  `alpha_registry.total_searched(market, data_window)` and must cite it
  in the pre-registration doc ("searched before this family: N units,
  K sweeps, on these windows").
- The learnability audit reports per-market searched-so-far alongside
  its structure metrics, so allocation sees both signal and prior spend.
- Evolab v2's nightly cycle may not register a genome whose v0 hash is
  already in the registry with a verdict on the same data window.

## What this does NOT do

It does not change any past verdict. It does not compute a global
q-value across families (families used different outcome definitions and
windows; a pooled FDR would be a false precision). It records spend so
that humans and the battery can weigh it. Zero survivors stays a valid
result under it.

## Acceptance for the implementation packet

- Migration script produces exactly 35 + 1 + 4 + 1 rows (+ M-tests if not
  already inside V2's 5) with a reconciliation report naming any doc
  count it disagrees with.
- Round-trip test: register → verdict → total_searched.
- Semantic-hash test: same atoms in different order → same hash; a
  threshold outside the grid → different hash.
- docs/RESEARCH_CATALOGUE.md gains a pointer, not a rewrite.
