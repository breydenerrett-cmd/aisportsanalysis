# Evolution Lab — implementation design package

Approved by Brey 2026-08-31 with two decisions settled: 2023–24 is one
explicitly exploratory, non-evidential sandbox (the forward stream is the first
independent arbiter), and the prop-listing feasibility audit is permitted under
a policy amendment separating FEASIBILITY MEASUREMENT from RESEARCH COLLECTION.

**The lab's first scientific purpose is to measure how much apparent edge our
own search process manufactures from noise.** Crowning a historical winner is
not the goal and never becomes evidence.

Phase 0's feasibility audit (`docs/EVOLAB_PHASE0_FEASIBILITY.md`) is running
and can invalidate parts of this design — specifically §5 execution and any
timing-sensitive strategy class. Numbers below marked *(pending Phase 0)*
depend on it.

---

## 1. Reuse — what already exists

The foundation is largely built. New code should be thin glue over these.

| need | existing module | note |
|---|---|---|
| per-game PIT features | `src/research/matrix.py` | 2,430 + 2,429 posted-lineup games, built in 7–11s/season |
| PIT accumulation primitive | `src/providers/statcast_pitches.py` `iter_rows(before=)` | the leak-proof gate every feature reads through |
| historical price path | `src/research/pricepath.py` | built for V2; the replay's market source |
| de-vig, fair price, pairing | `src/model/selections.py` `_fair`, `index_price_pairs` | already the basis of the Elo benchmark's scoring |
| single-instant board | `src/analysis/prices.py` `boards_by_matchup`, `latest_instant` | prevents stale-best-vs-fresh-consensus; exactly the simultaneity discipline the replay needs |
| game identity | `src/pipeline/snapshots.py` `game_key`, `official_date` | Eastern official date — do not re-derive |
| spec freezing, direction-before-results | `src/research/funnel.py` `register_family`, `validate_spec` | the genome's direction rule is this rule |
| falsification | `src/research/battery.py` RULES_VERSION 2.0.0, fingerprint `ac74c7a7f715f9ec` | **frozen — the lab consumes it, never modifies it** |
| coverage reporting | `src/research/coverage.py` | feature availability tables |
| event measurement | `src/research/eventstudy.py` | for microstructure strategies later |
| forward arbitration | `src/pipeline/ledger.py` | append-only; the only independent holdout |

New code lives in `src/evolab/` and writes only to `data/research/evolab/`.

**Environment constraint discovered: no numpy, no scipy — stdlib only.** This
drives §12 and is not a blocker; see the bitset design there.

---

## 2. Replay event/state schema

A replay is a chronological stream of **decision points**. A decision point is
one `(game, timestamp T)` pair at which a strategy may act.

```
DecisionPoint = {game_id, official_date, commence_time, T, point_class}
```
`point_class` ∈ {`T_MINUS_24H`, `T_MINUS_6H`, `LINEUP_POSTED`, `T_MINUS_30M`} —
a fixed, pre-registered ladder so no strategy can invent a bespoke timing.

> **AMENDED BY PHASE 0 (measured, 2026-08-31).** The historical store is
> **3 snapshots per day** (16:50 / 22:50 / 01:50 UTC). **No two observations
> anywhere in 2023–24 are closer than 177 minutes; the median gap is 6 hours.**
> Consequences, which narrow this design rather than caveat it:
> - The ladder collapses to **two usable classes**: an early board and a late
>   board. `T_MINUS_30M` exists for only **1,269 of 4,819 games (26%)** and
>   `LINEUP_POSTED` cannot be dated at all (below).
> - **Steam, lead/lag, news-reaction, lineup-post-reaction and any intraday
>   execution-timing gene are UNBACKTESTABLE** on 2023–24 and are excluded
>   from the genome outright. They are forward-only questions — which is
>   precisely what the V3 lane is for.
> - What remains testable is **coarse multi-hour drift**, and the "close" is a
>   median 85 minutes before first pitch, not a true close.
> - **No lineup or probable-pitcher posting timestamps exist for 2023–24**, so
>   any lineup- or starter-conditioned feature has an unprovable
>   earliest-available time and can only be served under a declared
>   assumption. Assuming a nominal T-180 post time drops the executable
>   universe to 3,624 games AND selects survivors by first-pitch time, which
>   correlates with coast and day of week — a bias that must be reported, never
>   silently accepted.
> - Replay universe: **4,819 games** (2,408 in 2023, 2,411 in 2024). The
>   measurement reproduces the published V1 "4,395 priced" figure exactly,
>   which is what makes it trustworthy.
> - The historical store has **no spreads at all** (h2h and totals only), and
>   F5 is ~290 games at exactly one observation each — so historical F5
>   research is infeasible and PATH B depends entirely on forward capture.

The engine serves a **WorldView**: everything visible at T and nothing else.

```
WorldView = {
  game:       {away, home, park, commence_time},
  features:   {name: value | None},        # None = not yet computable at T
  board:      {market: {book: prices}},    # latest observation <= T
  board_meta: {observed_utc, books, simultaneous: bool, staleness_seconds},
  available:  [market, ...],
}
```

**Leakage is prevented structurally, not by filtering.** The WorldView is built
by generators that never read a row dated after T, so future data is *absent*
rather than *hidden*. Outcome and closing price have no attribute on the object
at all — reaching for them raises, and a test asserts it. This mirrors how
`iter_rows(before=)` already works and is the single most important correctness
property in the lab.

---

## 3. Strategy genome schema

Modular, per Brey's §9 — crossover can later swap whole modules.

```
Genome = {
  eligibility: {markets: [...], min_books: int, require_lineup: bool},
  signals:     [{feature, threshold_index, weight}],   # <= MAX_SIGNALS
  combination: {rule: "weighted_sum"|"k_of_n", k: int},
  entry:       {min_score: float, min_confirmations: int},
  routing:     {market_preference, f5_condition},
  execution:   EXECUTION_MODE,        # held CONSTANT during predictive search
}
```

Three structural rules, each removing noise-fitting capacity that killed V4/V5:

1. **Directions are frozen by mechanism and absent from the genome.** Each
   feature has a registry entry carrying a written mechanism and a fixed sign.
   Evolution tunes magnitudes, thresholds, combinations and routing; it can
   never flip a sign. Screen-then-flip is how V4 and V5 died — this makes the
   move unavailable rather than merely penalised.
2. **Complexity is capped, not penalised.** `MAX_SIGNALS` (3), a fixed
   threshold ladder per feature (3 values), no nested conditions. A penalty can
   be outrun by a large enough apparent effect; a cap cannot.
3. **No feature without a mechanism.** The registry is the gate.

---

## 4. Deterministic decision API

```
decide(genome, worldview) -> Decision | NO_PLAY
Decision = {market, side, score, signals_fired, execution_mode}
```

A pure function: no I/O, no clock, no randomness, no global state. Same genome
plus same WorldView yields a byte-identical decision, always. Determinism
hazards enumerated by Phase 0 (dict ordering, float accumulation, price ties)
are each closed explicitly — ties broken by a stated deterministic rule, not by
whichever book sorted first.

---

## 5. Execution model *(pending Phase 0 §2)*

Three explicit scenarios; never a silent assumption.

- **`CONSENSUS_EXECUTION`** — de-vigged consensus of books on the board at T.
  **The primary mode, held identical across the entire population during
  predictive search**, so no strategy can win by execution while claiming
  prediction.
- **`SPECIFIC_BOOK_EXECUTION`** — one named book's price at T, or no bet if
  that book is absent. The realistic single-account case.
- **`BEST_OBSERVED_EXECUTION`** — best price among books observed at the same
  instant. **Phase 0 PERMITS this**: every book for a game arrives in one API
  response at one `snapshot_at`, not stitched, with book staleness a median of
  0.6 minutes (max 14.8). The best price was genuinely on the board at once.
  Still reported as an upper bound, and with one measured caveat that must be
  handled rather than ignored: **62.7% (2023) and 78.6% (2024) of instants have
  two or more books TIED at the best price**, resolved today by iteration
  order. The tie-break must therefore be an explicit, stated, deterministic
  rule — and because the identity of the "best book" is not recoverable,
  `SPECIFIC_BOOK_EXECUTION` results must never be read as "this book was
  reliably best". Whether the price was takeable at stake is not measurable
  from anything we hold, and no design choice can fix that.

Never: closing price, retroactive book choice, unavailable markets, assumed
fills, or unlimited limits. Any strategy whose apparent performance changes
materially between modes is labelled `EXECUTION_ADVANTAGE`, not predictive.

---

## 6. Fitness model

**Primary search fitness: market-relative movement.** De-vigged consensus
movement from the decision price to the true close, in the direction of the
selection. Chosen for sample efficiency — outcomes are near-binary and swamp
realistic effects at our sample sizes.

Per Brey's correction, the optimistic ~144-selection illustration is **not** a
threshold. Uncertainty is computed from *observed* variance with dependence
respected: **clustered by date and by team, with a stationary block bootstrap
over game-days**, never an independence assumption. Overlapping selections
across strategies are handled at the multiplicity layer (§8), not here.

**Confirmation fitness: outcome ROI**, flat unit stakes, same clustered
uncertainty. A strategy positive on movement but negative on outcomes is a
microstructure candidate, not a predictive one — and is labelled that way.

Guards are **gates, not additive terms** (a weighted sum lets a big number buy
its way past a red flag): minimum selections, concentration limits by team and
book, temporal stability across folds, complexity cap. Failing a gate is a
death, not a deduction.

**Never in fitness:** staking, bankroll paths, Kelly, drawdown-adjusted
returns. Those are presentation, evaluated afterward, and can never promote.

---

## 7. Placebo-world generators

Five generators, deliberately preserving real structure while breaking the
claimed relationship. The weakness to avoid is a null world that is *easier*
than reality, which would understate the ceiling.

| id | generator | preserves | breaks |
|---|---|---|---|
| P1 | within-date outcome permutation | daily slate structure, market prices | feature → outcome |
| P2 | team-identity permutation (consistent within season) | team strength distribution | feature → team attribution |
| P3 | signal date-shift (features shifted k days) | feature autocorrelation | feature ↔ game alignment |
| P4 | stationary block bootstrap over game-days | temporal dependence, streaks | ~~long-range structure~~ **nothing — see below** |
| **P5** | **market-truth resampling** — outcomes redrawn from the de-vigged market probability | market calibration exactly, all prices | any edge beyond the market |

> **P4 IS NOT A NULL. My specification was wrong, and it is corrected here
> rather than quietly patched (decided 2026-08-31).**
>
> P4 copies whole game-days with features, prices AND outcomes still attached
> to each other, so a real edge is carried into the "null" world intact. This
> was measured, not argued: with a planted edge, P4's maxima centred at 0.230
> against a real maximum of 0.235 — P4 was the one generator the planted edge
> failed to clear, and its inflated maxima dragged the POOLED verdict to BELOW
> while 4 of 5 per-generator verdicts cleared.
>
> A generator that a genuine edge cannot clear does not measure the noise
> ceiling. It measures how much the search maximum wobbles under resampling —
> a useful quantity with a different name.
>
> **Decision: P4 is reclassified as a DISPERSION DIAGNOSTIC and excluded from
> the ceiling and the kill criterion.** It is not repaired into a null, because
> P1, P3 and P5 already break the feature-outcome link three different ways and
> a fourth variant would add redundancy rather than coverage. The kill criterion
> reads PER-GENERATOR precisely so one mis-specified world cannot poison the
> verdict — that property was designed in for hypothetical reasons and earned
> its keep on the first real run.
>
> Related measured caveat: **P1 detaches outcome from PRICE, not only from
> features.** Price/outcome alignment collapses from 0.0295 to 0.0105, and
> against a price-tracking rule P1's maxima run 22× the real maximum. That is
> conservative for a ceiling but useless as a null for price-sensitive rules,
> so P1 carries an optional band-preserving mode that restores alignment to
> 100.5% of real.

**P5 is the sharpest null and the one I weight most** — and it now has the
measurement to back that claim. On worlds containing no edge, search maxima
were: real null worlds +0.0298, **P5 +0.0285 (ratio 0.96 — it neither flatters
nor understates)**, P3 +0.028, P2 +0.034, P1 +0.057, P4 +0.062. P5 is also the
only generator that provably erases a planted edge: P5 worlds built from an
edge-free world and from an identical world *with* an edge come out
byte-identical. It asserts exactly one
thing — the market's implied probability is correct — and preserves everything
else. Apparent edge found there is definitionally search artifact.

**The whole machine runs on every world**: enumeration, fitness, gates,
selection, stopping rules, complexity caps, hyperparameters, and later mutation,
crossover and meta-learning. The ceiling must represent the adaptivity of the
entire process, not of one scoring function.

10 replicates per generator (50 placebo worlds) as the default; more is cheap
under §12.

---

## 8. PBO / CSCV design

Combinatorially symmetric cross-validation (Bailey & López de Prado):

1. Split the replay universe into **S = 10 chronological blocks**.
2. For each of the C(10,5) = 252 balanced splits, take half as in-sample.
3. Select the best strategy by in-sample fitness; record its **out-of-sample
   rank** among all strategies.
4. **PBO** = the fraction of splits where that rank falls below median.

PBO ≈ 0.5 means selection carries no out-of-sample information — the honest
expectation on a barren space.

**Efficiency insight:** because we enumerate, per-strategy per-block fitness is
computed **once**; all 252 splits are then cheap arithmetic over that table. The
statistics cost nothing next to the replay.

Analytic cross-check: **Hansen's SPA** on the same strategy set. It and the
placebo ceiling should broadly agree; disagreement means a bug in one of them,
and that is exactly why both are run. Deflated Sharpe is skipped — designed for
return series and adds nothing the ceiling does not already give.

**Validate the validator:** on synthetic data with a planted edge, PBO must be
low; on pure noise, PBO ≈ 0.5. Until those two tests pass, no PBO number is
reported.

---

## 9. Autopsy and taxonomies

Every strategy that survives gates or dies interestingly gets a **research
autopsy** answering Brey's questions: what it did, where returns came from,
whether price movement agreed, concentration by team and book, dose–response,
temporal generalisation, ablation results, and how it compares with placebo
winners of equal apparent quality.

Ablation is straight component removal — remove one signal, re-run, measure —
not an attribution approximation. For rule-based genomes it is both more honest
and more interpretable, and it directly answers "did this component contribute
or is it decoration".

**Death reasons** (first-class labels): `NO_SIGNAL`, `NEGATIVE_EXPECTATION`,
`OVERFIT`, `SEASON_INSTABILITY`, `TEAM_CONCENTRATION`, `BOOK_CONCENTRATION`,
`PRICE_BAND_ARTIFACT`, `LOW_SAMPLE`, `HIGH_DRAWDOWN`, `NEGATIVE_MOVEMENT`,
`NO_DOSE_RESPONSE`, `INVERTED_DOSE_RESPONSE`, `MARKET_UNAVAILABLE`,
`FEATURE_REDUNDANCY`, `EXCESS_COMPLEXITY`, `DATA_QUALITY`, `LIKELY_LUCK`,
`BELOW_PLACEBO_CEILING`.

Most of these already exist as battery rules — the taxonomy is largely a
reporting layer over frozen machinery, which is why it is cheap.

**Edge taxonomy** (also first-class, never conflated): `PREDICTIVE_EDGE`,
`MICROSTRUCTURE_EDGE`, `EXECUTION_ADVANTAGE`, `MARKET_SELECTION_ADVANTAGE`,
`LUCK`, `OVERFIT`, `DATA_ARTIFACT`, `STAKING_ARTIFACT`.

---

## 10. Lineage schema

Defined now, populated trivially in Phase 2 (every enumerated strategy is its
own founder) so Phase B needs no migration.

```
Lineage = {strategy_id, generation, parents: [...], operators: [...],
           diff_from_parent: {...}, world_id, seed}
```

---

## 11. Evidence namespace

- Code: `src/evolab/` · Data: `data/research/evolab/` · Docs: `docs/EVOLAB_*.md`
- **Nothing produced here is evidence.** It cannot write to `data/research/`
  root, cannot alter or re-run frozen families, cannot append to the research
  scoreboard, and cannot promote anything.
- Every artifact records: world id, generator, seed, code commit, battery
  fingerprint, enumeration spec hash.
- 2025 keeps its tuning-only role. **Sealed 2026-01-01→08-27 is untouched.**

---

## 12. Compute, storage, wall-clock

The key move, forced by having no numpy and enabled by enumeration:
**represent selections as Python integer bitsets.**

- Precompute, once per world: for each (feature, threshold) pair, the bitset of
  games where it fires. With ~20 features × 3 thresholds that is **60 bitsets**,
  each one integer of ~4,800 bits.
- A strategy's selection is then 2–3 integer `&`/`|` operations. Enumerating
  5,000 strategies costs ~15,000 integer ops — **milliseconds**, not minutes.
- Fitness sums iterate only the set bits (~500 per strategy).

Estimates *(replay universe pending Phase 0 §5; assuming ~4,800 games)*:

| quantity | estimate |
|---|---|
| strategies enumerated | 10³–10⁴ |
| decision evaluations | ~5,000 × 4,800 ≈ 24M, collapsed to ~60 mask builds + cheap combinations |
| one world sweep | seconds |
| 51 worlds (1 real + 50 placebo) | minutes |
| CSCV over 252 splits | seconds (table arithmetic) |
| storage: fitness tables | 5,000 × 10 blocks × few floats ≈ single-digit MB |
| storage: selection masks | ~3 MB per world |
| wall-clock, Phase 2 end to end | well under an hour per full run |

This runs as a **script on the data plane**. No model reasoning is spent per
simulated decision — that is a hard rule, not an optimisation.

---

## 13. Build assignment

Per Brey's model policy — Sonnet is the default workforce; escalate for
PIT/evidence correctness, subtle methodology and high cost of error.

| component | built by | reviewed by |
|---|---|---|
| WorldView assembly, leakage guarantees | **Opus** | Fable adjudicates |
| decision API, genome schema, enumeration | Sonnet | Opus validator |
| bitset engine, fitness computation | Sonnet | Opus (clustering correctness) |
| execution models | Sonnet | **Opus** (defensibility of best-price) |
| placebo generators | **Opus** (P5 especially) | Fable |
| CSCV/PBO + SPA, and their validation tests | **Opus** | Fable |
| autopsy reporting, taxonomies, lineage | Sonnet | Opus |
| docs, run scripts, CLI | Sonnet | — |

---

## 14. Acceptance tests

Non-negotiable; each is a committed test.

1. **Determinism** — same genome, world and seed produce a byte-identical
   decision log across two runs.
2. **Structural leakage** — a fact dated T+1s injected into every store leaves
   every decision at T byte-identical.
3. **Absent futures** — `WorldView` exposes no outcome and no closing price;
   attribute access raises.
4. **Reproduction** — replaying a published V1/V4 spec reproduces its recorded
   numbers exactly (the V4 package already reproduces to the digit).
5. **Execution honesty** — `BEST_OBSERVED_EXECUTION` refuses to score when the
   board's quotes are not simultaneous.
6. **Placebo sanity** — in P5, a random strategy has expected movement 0 and
   expected ROI ≈ −vig.
7. **Validator validation** — planted-edge synthetic gives low PBO; pure noise
   gives PBO ≈ 0.5.
8. **Namespace isolation** — the lab cannot write outside `data/research/evolab/`
   (enforced by test, not by convention).

---

## 14b. Stated prior before Phase 2B runs (2026-08-31)

Recorded now, before the enumerable sweep, so that whatever happens we cannot
later claim we expected something else.

**Phase 2A has already answered the linear version of the lab's question, and
the answer was no.** With the market's log-odds as a fixed offset, penalised
logistic regression on the full point-in-time feature set finished
+0.0000412 log-loss/game *worse* than the close (date-clustered p = 0.914),
and the L1 fit selected the empty model — all 18 coefficients exactly zero.
The strategy space Phase 2B enumerates is built from **those same features**.

So the honest prior is: **the enumerable space will most likely land
BELOW_PLACEBO_CEILING**, and the lab's expected output is a strong,
quantified null rather than a champion.

Phase 2B is still worth running, for three reasons that are not
rationalisations of a sunk plan:

1. A linear offset model cannot see **threshold and interaction structure** —
   "fire only in the top decile of this signal, and only when a second
   confirms" is not a linear function of the inputs. That is precisely the
   shape the genome expresses and precisely what Phase 2A could not test.
2. The **noise ceiling is the deliverable regardless of the answer.** Knowing
   how much apparent edge our search manufactures from nothing is a permanent
   instrument that every future family gets measured against, whatever it says
   about this one.
3. It is nearly free. 11,088 genomes sweep in 51 ms; fifty placebo worlds cost
   minutes. There is no scenario where the compute is the reason not to look.

**What would change my mind mid-flight:** if the real sweep's maximum sits far
inside the placebo distribution AND the per-block fitness table shows no
structure at all, there is no case for building evolution to search harder —
searching harder in a space with nothing in it only manufactures better-looking
artifacts. That is the kill criterion below, and Phase 2A makes it the likely
outcome rather than the pessimistic one.

## 15. Kill criteria

**If the real search maximum lies inside the placebo maximum distribution — no
better than its 95th percentile — across the majority of the five generators,
evolution is not built.** We publish:

> Within this feature and policy space, our search cannot distinguish apparent
> winners from winners generated by worlds known to contain zero edge.

That is a strong, publishable result and the honest end of the line for this
space. Consistent with every rule this project runs on: zero survivors is a
result, not a failure.

**The replay engine survives that verdict regardless.** It remains foundational
for F5, totals, props, microstructure, execution-policy research, future
feature families, other sports, and forward replay and reproduction.

If the real maximum *does* clear the ceiling, Phase B unlocks: elites, parent
pools, mutation, crossover, immigrants, behavioural diversity, islands,
lineage, ablation, death taxonomy, and placebo-calibrated meta-learning — all
inside the sandbox, none of it evidence by virtue of having evolved.

---

## 16. Open questions for Brey

None currently. Both prior decisions are settled and recorded. New ones will be
raised here as they arise rather than resolved silently.
