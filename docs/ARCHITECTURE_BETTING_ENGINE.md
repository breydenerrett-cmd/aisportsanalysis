# LINEHOUND — The Betting Analysis Engine: authoritative architecture and implementation plan

Date: 2026-09-03. Author: the orchestrator (Fable tier), adjudicating the
reconciliation run of 2026-09-03: nine evidence-cited subsystem maps
(`docs/planning/map-*.md`), three independent architectures
(`docs/planning/design-*.md`), the judge's synthesis
(`docs/planning/synthesis-judge.md`) and the adversarial attack
(`docs/planning/attack.md`). Those documents are the evidence and the detail.
This document is the decision. Where it disagrees with any of them, this
document governs.

Status: PLAN, awaiting owner review. No code was written for it. Nothing here
relaxes a standing constraint: point-in-time integrity sacred; 2025 tuning-only;
sealed 2026 untouched for research reads; losers published; no real-money
placement; never fabricate; price improvement is never EV or edge; the Ranker
publishes nothing while `ENGINE2 is None` until the unlock gates clear and the
owner signs off.

---

## 1. The verdict in one page

**The vision is buildable and it is the right destination.** The repository
already contains the honest core of it: a point-in-time feature rebuild with
refusals rather than warnings, a pre-registration funnel with a versioned
falsification battery, an enumerated-search lab with placebo/CSCV/SPA ceilings,
a forward capture that now records prices, lineups, transactions, umpires and
weather with timestamps, an append-only ledger with closes threaded back in, and
a product that says "no play" out loud on 93% of nights. What it does not
contain is the thing the vision is actually about: **one decision function that
sees a whole board and is run identically live and in replay.** Today there are
two decision paths that do not know about each other, a price record with
exactly two fields (`home_price`/`away_price`) baked into eight modules, a
ledger that structurally cannot record a second verdict when a lineup posts,
and a strategy lab whose "strategies" are six features over one market.

**The architecture, in order of construction:** a universal record underneath
(data-first: selection, line, price, book, three clocks, a knowability grade),
one pure `analyze(snapshot, systems, adversaries)` in the middle (engine-first:
price-blind proposals projected onto every priced selection, adversaries,
rating net of friction, deterministic ranking), and a Strategy Factory on top
(factory-first: registered populations, placebo ceilings, a scorecard that
structurally cannot read a bankroll, promotion by gates not by a weighted sum).
The attack's corrections are adopted in full (section 4); two of them are
preconditions for any number this project ever publishes again.

**Three findings change the vision's emphasis, and the owner should adopt them
rather than resist them:**

1. **Scale the substrate, not the population.** The binding constraint is
   independent evidence, not decisions. Ten thousand systems over six features
   is a better overfitting machine; forty registered features over six gradeable
   market families with two honest decision-point classes is where the
   information is.
2. **Historical replay is degraded-information replay, and it must say so.**
   2023–24 has six-hour median board spacing, zero lineup-post timestamps and a
   probable-pitcher field that is 99.9% the actual starter. Discovery can happen
   there; promotion can only happen forward. The 2026 season is the first that
   can be replayed at the granularity the vision wants, which is why capture
   outranks analysis for the next 60 days.
3. **The forward record is currently not the shape the gate can count.** The
   ledger holds zero selections with a book, a price, a rating and a system id.
   Even a real edge found tomorrow could not satisfy the unlock condition with
   today's ledger. Ledger v2 starts the clock; it is the most urgent engine item.

**The most likely failure is not finding nothing. It is finding something that
is an artifact** (a board-width ceiling clear, a model-contaminated strategy, a
single bankroll curve) and publishing it. Section 4 is the set of mechanical
guards that make that failure impossible rather than unlikely.

---

## 2. The owner's fourteen questions, answered

Evidence for every line is in the maps; file:line citations live there.

**(1) Reconciliation.** Of the vision's capabilities, roughly a third exist
(PIT feature rebuild, pre-registration funnel + battery, enumerated lab with
ceilings, forward capture, ledger with closes, alpha registry, Analyzer with
verdicts, price engine, gate-enforced Ranker), a third are partial (replay
engine h2h-only; Bet Check without a verdict; My Bets; V2 screens; timing
family; umpire and weather capture just started), and a third are missing
(universal record, whole-board search, engine identity between live and
replay, decision records with book/price/rating/system, self-review, factory
lifecycle, settlement adapters for any market beyond h2h/F5, parlays,
LOCK, bankroll accounts).

**(2) Exists.** `src/features/pointintime.py` refuses rather than warns;
`src/research/battery.py` is versioned and fingerprinted; `src/research/funnel.py`
enforces screen/replication/FDR; `src/evolab/*` enumerates 8,811 genomes with
bitset evaluation and placebo/CSCV/SPA ceilings; `src/research/alpha_registry.py`
records searched-so-far; forward stores capture prices hourly plus dense
15-minute slots near first pitch, lineups, probables, transactions, umpires,
weather, credit balance, pitcher-K prop prices; `evidence/forward_ledger.jsonl`
with settlement and append-only closing backfills across h2h/spreads/totals;
`src/report/ranker.py` with `ENGINE2 = None` and a test that fails on the word
"edge"; four V2 screens deployed to staging.

**(3) Partial.** Replay serves h2h only while 302,271 totals rows sit unread on
disk; F5 in the genome is schema-only; the Analyzer decides through hard-coded
two-market routing; the ledger writes one priced row per game ever; Bet Check
carries no verdict; the timing family has one class read (below floor under
the registered definition); weather and umpires have days, not seasons, of
capture; the credit policy doc is priced off a balance 46,000 credits stale.

**(4) Believed but absent.** "Evolab" has no mutation, crossover or
population (by its own rule, gated on a ceiling clear that did not happen);
no Bet Check integration, season-end module or CI scorecard exists in it; the
ledger is described as hash-chained in the master plan and is not; "11,088
genomes in 51 ms" was never measured; the runbook names three unattended jobs
of which one has code and none has ever fired unattended; `transactions.jsonl`
(27,053 rows, 1,768 IL placements) is complete on disk and wired to nothing;
alternates/team totals are "priced" in the policy doc from a one-off manual
probe, not collected.

**(5) Boost vs replace.** BOOST: pointintime, battery, funnel, alpha registry,
bitset evaluation, replay's stop-at-T scan, rosterwatch/umpirewatch/weather
capture, ledger settlement and closing machinery, the detectors as an evidence
library, the V2 screens. REPLACE: the two-field price record (with the
universal record, by dual-write never migration), `mismatch.route_market`
(with whole-board projection), the one-row-per-game ledger rule (with
idempotency on the full key), the divergent live and replay decision paths
(with one `analyze()`), the all-Opus worker roster (with Sonnet implementers
and a real dispatcher).

**(6) Evolab → Strategy Factory.** Keep the bitsets, the registry's
outcome-blind ladders and the ceiling machinery; add a lifecycle with
registered causes (PROPOSED → REGISTERED → SCREENED(2023) → REPLICATED(2024) →
ATTACKED → CEILING_TESTED → tune-on-2025 → FORWARD_TESTING → PROMOTED, with
RETIRED/GRAVEYARD off any stage), population-level registration in the alpha
registry, per-cell evolutionary unlocking with cells pre-registered and charged
as multiplicity, generation-sealed forward epochs, a scorecard with the
Two-Ledger Rule, and a daily cycle that contains no model call. Detail:
synthesis §4.4 and attack F4/F5/F8/F9/S14.

**(7) Market universe.** A `MARKET_CATALOGUE` where a line is part of the
selection identity and a subject (pitcher, batter, team) is a first-class
field, so alternates, team totals and props are catalogue entries rather than
code; every family gated on grading (a settlement rule, a fetchable result
source, ten graded examples) before a credit is spent; a measured per-family
credit probe before it enters the envelope; tiers A (featured grid, 3 credits
flat per slate), B (F5 trio, alternates, team totals at named moments), C
(pitcher and batter props at two moments), about 900 credits/day against a
100K monthly allotment; a drop order ranked by irrecoverability with a
non-droppable thin batter-prop floor. Detail: synthesis §4.6, attack F12/F13/S17.

**(8) The daily loop.** Capture all day (raw bytes first, then projection);
`morning` at T−6h, `post_lineup` at T−3h, `late` at T−30m where ratings are
computed, a sealed close pass at T−0, then settle → account (reporting only)
→ review (computed, never narrated) → factory cycle. Every game gets a row at
every point class including declines with named reasons; a tick with an
unchanged snapshot fingerprint writes to the capture log, never the ledger.
Every stage idempotent and resumable from its own ledger, because restarts are
observed. Detail: synthesis §4.3, attack M3/S21.

**(9) Replay without leakage.** One reader, `as_of(game, t)`, that stops at t
on an ascending scan, refuses sealed windows by name, cannot open the
directories that hold closes, results and settlements, and asserts per-field
provenance (`observed_utc <= t`, named on failure); grade C/D inputs excluded
by default and printed as exposure when opted in; the truncation differential
(snapshot from a store physically truncated at t must equal the snapshot from
the full store) as the CI-blocking gate; the live/store conformance test kept
but renamed to what it proves; P7 (+2h and −2h time shift, with a NOT_RUN
verdict when fingerprints do not change) and P8 (aggregation placebo:
features rebuilt from data truncated at game start must equal features from
the full season). Detail: synthesis §4.5, attack F6/S3.

**(10) Scale.** Compute was never the constraint. Bitsets stay; masks are per
(feature, rung, side) per world, with new market-availability and
books-at-least-k masks so board widening does not fall back into Python loops;
worlds parallelized across four CPUs with the LPT pattern the test runner
already uses; frames persisted and content-addressed; decisions not stored but
recomputed from a recipe, with full detail retained for anything that entered a
verdict, a forward selection or a LOCK, and a nightly reproducibility sample
across every prior epoch; instrumentation required on every artifact before any
optimization. DuckDB only on a measured trigger. Detail: synthesis §4.7, attack S19.

**(11) Roles.** Deterministic code: everything that decides, evaluates, grades,
prices, settles, reviews or governs, and all capture. Sonnet: implementation
under written contract, settlement adapters, backfills, schema-valid strategy
specs with mechanism strings, narratives derived from computed records. Opus:
methodology, placebo design, promotion floors, multiplicity policy, LOCK
criteria, schema review, and adversarial review of every research read before
it counts (made mechanical: a verdict row cannot be appended without a
`validator_verdict`). Fable: orchestration, gate-holding, the dispatcher, the
budget constants, the owner-decision queue. Meta-rule: no model writes to
`data/`, `evidence/` or the registry; model-authored content carries provenance
and is excluded from evidence paths by default. Detail: synthesis §4.8.

**(12) Capture now.** Section 6.

**(13) V2 / Bet Rating / Picks / LOCK.** The gate is a publication boundary,
not an engine boundary: ratings are computed and recorded from day one so the
forward record accumulates, and a path guard keeps every gated field
(`rating`, `p_model`, `edge_bps`, `stake_units`, `supporting_systems`) out of
`src/report/**`, `api/**` and `web/**` while `ENGINE2 is None`. The Featured
Bet primitive's selection rule while gated must be a published non-analytic
rule (e.g. largest measured price dispersion), stated inline, with
`price_improvement` never the first or largest segment. The gate readout ships
as counts and conditions only. Bet Rating ships as `null` until a calibrated
probability with forward evidence exists. LOCK criteria are pre-registered now
(section 5) and expected to produce zero for at least a season. Detail:
synthesis §3.7, attack F14/S22/S23.

**(14) Where the description should change.** Section 7.

---

## 3. The architecture

Adopted from synthesis §4 with the amendments in section 4. Summary only; the
contracts (dataclasses and signatures for `PriceObservation`,
`InformationEvent`, `MarketFamilySpec`, `as_of`, `Snapshot`,
`PriceBlindSnapshot`, `Board`, `analyze`, `AnalysisSystem`, `Adversary`,
`DecisionRecord`, `ReviewRecord`, `Scorecard`, `objective`) are frozen as
written in synthesis §4.2 plus the field additions listed in section 4 below,
and become `docs/ENGINE_CONTRACT.md` in packet W9.

```
L0 raw        verbatim provider bytes, one file per call, written BEFORE projection
L1 canonical  PriceObservation / InformationEvent partitions; closes, results and
              settlements in SEALED directories the reader cannot open
L2 frames     content-addressed, deferred until timing justifies
L3 ledgers    decisions, settlements (sealed), reviews, factory population /
              graveyard / scorecards / accounts — hash-chained per month
```

```
src/board/      identity, record, catalogue, settlement rules
src/knowledge/  events, as_of, grades, provenance
src/capture/    budget, tiers, plan, cadence SLO
src/engine/     worldview, analyze, rating, adversaries, review
src/factory/    population, generate, score, attack, lifecycle, cycle, epochs
src/evolab/     boosted in place, re-pointed behind an equivalence proof
```

The waist: `analyze(snapshot, systems, adversaries, config) -> Analysis`, pure
(no I/O, clock, randomness, globals, model call), five phases PROPOSE (each
system sees only `snapshot.price_blind()`), PROJECT (every proposal priced
against every selection its thesis covers, de-vigged, edge net of friction),
ATTACK (deterministic counterarguments; FATAL removes and records), RATE (from
p_model, entry price, friction and the system's own forward record), RANK
(deterministic total order). Live and replay call this function and nothing
else.

---

## 4. Guards adopted from the attack (mandatory, not advisory)

Each is a mechanism, not a caution. The first eight are the ranked order of
work the attack recommends and this plan adopts verbatim.

1. **Cadence is measured, grade is computed** (F10). `known_at_grade` derives
   from the measured poll gap around each fact (≤20 min B, ≤2 h C, else D). A
   daily cadence SLO artifact (attempted, succeeded, longest gap, p95 gap) is
   published; seven consecutive green days are a precondition of any paid tier
   switch-on and of calling 2026 a grade-A/B season.
2. **Generation-sealed forward epochs** (F4). Cohorts are frozen at epoch start
   (45 days declared); the generator, mutation, graveyard dedupe and any model
   proposer cannot open forward scorecards for an open epoch (path allowlist,
   with a test that tries); promotion evaluates cohorts at epoch close; any
   mid-epoch regeneration restarts the clock with a published row.
3. **One registered clustering spec** (F1, S2). `CLUSTER_SPEC` (unit, block
   length chosen from measured residual autocorrelation, metric, linkage,
   thresholds, version) registered before Phase 2 and hashed into every
   scorecard; `n_decisions`, `n_game_days`, `n_independent_clusters` are three
   required fields; `effective_tests` reported under tight/medium/loose with
   the most conservative used for verdicts and sign flips reported as
   indeterminate. The "4,860 independent units" figure is struck.
4. **Placebo worlds run the full decision function** (F2, F3). The null
   executes `analyze()` end to end including the board-wide argmax; a property
   test requires a zero-signal genome's real-world maximum to sit inside the
   placebo distribution at board widths 1, 2, 10 and 40 or the sweep refuses to
   write a verdict; `n_selections_projected` on every record; world count set by
   power analysis from the declared percentile (≥400 for a 95th-percentile
   ceiling) with the ceiling reported as a bound, not a point.
5. **Model-origin systems are barred from the discovery seasons** (F5). Their
   only admissible window is the forward epoch; `model_id`, `prompt_hash`,
   `training_cutoff` and prompt text recorded; a memorization probe registered
   and published; a separate multiplicity charge and ceiling for the model arm.
6. **Truncation differential and per-field provenance** (F6). The CI-blocking
   leakage gate is store-truncated-at-t equality, not live/store equality;
   `as_of` asserts `observed_utc <= t` per field and raises naming the field.
7. **The objective boundary is a type** (F9). `objective()` takes an
   `ObjectiveView` that structurally lacks money fields; the AST test stays as
   a second line and extends to derived paths; one adversarial test tries to
   smuggle a bankroll in.
8. **Product data-path guard** (F14, S22, S23). Gated fields cannot reach any
   product contract while `ENGINE2 is None`; the Featured Bet selection rule is
   non-analytic and published; the gate readout is counts only.

Also adopted: sample-class separation with `parameters_frozen_at` and no pooled
metrics (F8); review-origin hypotheses registered with `derived_from_window`
and charged at registration (F7); account curves never published without a
bootstrap fan, a zero-edge null and the null terminal percentile (F11);
`limit_observed` / `assumed_max_stake_units` and accounts reported at declared
limits and unconstrained (F12); measured per-family credit probes and a
reset-aware `MONTHLY_ALLOTMENT` (F13); drop order by irrecoverability with a
non-droppable thin batter-prop floor (S17); `price_age_seconds` stratification
with results that exist only in the >2h bucket void by rule (S5); backfilled
2023–25 rows stamped `l0_available: false` (S6); `selection_overlap` and
`outcome_covariance` as distinct typed instruments (S7); SGP identification
stated up front (S8); LOCK independence measured, not declared, with ECE bounds
and consecutive cadences (S9, S10, S11, S12); `FLAT_1U` only, Kelly registered
disabled (S13); population-level registration returning `(raw, effective)`
(S14); execution ledger scored on CLV only, never in `objective()`, never
published as edge (S16); resumable loop stages with a chaos test (S21);
forward-selection counting independent of `engine_version` with clock restarts
on semantic bumps (S20); segmented hash chains (M5); documented change paths
for every CI guard (M6); consensus-undefined as an explicit friction state (M7);
registered seeds on every bootstrap (M8); tick rows in the capture log (M3).

---

## 5. Gates

| Gate | Condition |
|---|---|
| **G-cadence** | Seven consecutive days of measured capture cadence green (attempted, succeeded, longest gap, p95) from the unattended external job. Precedes every paid tier switch-on and every analysis packet in Phase 1. |
| **G0 Record conformance** | L1 projection reproduces the legacy h2h store row for row over seven days of overlap; 2023–25 backfill rows stamped `l0_available: false` and never quoted as byte-reproducible from source. |
| **G1 Grade audit** | Every registered input carries a computed `known_at_grade`; every artifact prints `assumption_exposure`; `share_of_selections_driven_by_grade_CD` on every scorecard. |
| **G2 Budget** | `MONTHLY_ALLOTMENT` and derived `DAILY_ENVELOPE` as constants; measured probe per family; coded drop order; tier and balance reconciled and dated. |
| **G3 Settlement before collection** | A family has a settlement rule, a fetchable result source, and ten graded examples (fifty before it may be priced by a system). |
| **G4 Store fidelity + truncation differential** | Live snapshot fingerprints reproduce from the store for 7 days AND the truncated-store differential is byte-equal on a sampled corpus. |
| **G5 Ceiling** | A pre-registered cell clears its ceiling with placebo worlds run through the full argmax, world count from power analysis, effective tests reported. |
| **G6 Forward** | ≥300 forward selections with book, price, rating, counterarguments and settled close; ≥60 ledger days; class A/B; out-of-sample only; within sealed epochs. |
| **G7 Owner sign-off** | Explicit, dated, after G6. |

LOCK (pre-registered now, expected to yield zero for at least a season): a
candidate from a PROMOTED system; band_n from a published power analysis with
the upper bootstrap bound of band ECE under the threshold for k consecutive
review cadences; forward band monotonicity with clustered CIs; edge survives
at the worst book and under a 25% shrink of p_model toward the market; two
systems whose measured selection-agreement and residual correlation are below
pre-registered thresholds; no MAJOR counterargument; ≥90 days of forward
evidence in the family; post-publication price drift recorded with sustained
adverse drift a demotion trigger; base rate published with both tails (LOCK
rate and near-misses by condition); withdrawal published automatically.

---

## 6. Capture now (the live season outranks analysis for 60 days)

Rule: every price is irrecoverable, most facts are recoverable, every
timestamp of when something became knowable is irrecoverable.

**P0, free, immediately.** (1) Persist `all_books` for spreads, totals and
the three F5 keys — computed in memory on every capture and discarded; five
families of book depth destroyed hourly at zero cost. (2) Write L0 verbatim
before projecting. (3) Get the unattended capture job firing: default branch
repoint plus the `ODDS_API_KEY` repository secret (already requested).
(4) Keep rosterwatch, umpirewatch and weather on every tick. (5) Timing on
every run. (6) Reconcile the credit tier and balance (53,083 documented vs
~99,600 measured; a monthly allotment, not a stock).

**P0, free, this week.** (7) L1 backfill of 2023–25 odds history — totals
become replayable; publish the h2h/totals residual correlation beside the row
counts so nobody reads 302,271 rows as new evidence. (8) MLB GUMBO per-game
batter and pitcher box lines, forward today and 2023–24 backfill — the grading
substrate for every prop. (9) Open-Meteo archive 2023–25. (10) Park
orientations for 30 parks. (11) Wire `transactions.jsonl` into point-in-time
inputs. (12) Ledger v2 so the forward clock starts.

**P1, cheap, this month.** F5 spreads and totals on the pass that already
runs; denser F5 closes; alternates and team totals at dense moments; the T−30m
prop repricing slot that is currently half-unobserved.

**P2, budgeted, owner sign-off.** Batter props (largest irrecoverable
surface); pitcher props beyond strikeouts; the SGP source decision recorded as
a dated fact, then declared leg sets only; the vendor's prop history and
5-minute historical grid (register a hypothesis or accept the permanent gap).

---

## 7. Amendments to the vision (adopted unless the owner objects)

1. **Substrate before population.** Ask for forty registered features across
   bullpen availability, transactions, environment and market structure, six
   gradeable families and two honest decision-point classes; not for thousands
   of systems. Effective tests, not raw, are the number that matters.
2. **Degraded-information replay, said in public.** 2023–24 replays at
   `LATE_BOARD` with grade-D starters and zero lineup timestamps; the honest
   deliverable is the 2026-forward corpus with a grade ladder. Backtest scope
   (h2h, totals, thin F5; two point classes) is stated publicly with the
   forward-only families and their first honest verdict date.
3. **LOCK criteria pre-registered now, with a LOCK-free period.** Researching
   criteria after seeing which candidates would have qualified is threshold
   shopping. The credibility of the first LOCK is the length of time the
   machine ran without producing one.
4. **CLV is a monthly review dimension, never a daily score.** The daily
   self-review is the computed thesis outcome and mechanism checks.
5. **Bet Rating ships as `null` until a calibrated forward-tested probability
   exists**, with the gate readout beside it. A rating-shaped placeholder is the
   likeliest way the product breaks its own constraints.
6. **Prediction versus money, on the record.** Predictive edges may take
   seasons and may not exist (four families, zero survivors; Phase 2B below
   the ceiling; the close beats public Elo). Execution edges (stale books, line
   shopping) are findable in months and are deliberately excluded from
   `objective()`. Recommendation: keep the research rule, and run a
   clearly-labelled execution ledger scored on CLV only, never published as
   edge, so the road not taken is measured rather than re-argued. The owner
   should say which goal governs when they conflict.
7. **Parlays: capture now, expect a negative result.** A two-leg cross-game
   parlay needs about twice the per-leg edge to match two singles; the only
   falsifiable object is the book's correlation error, and it is probably
   unidentified from obtainable prices. Fund the capture anyway because capture
   expires.
8. **The daily surface needs a correlation-aware aggregation rule.** "0..N,
   never forced" is a property of one system; at population scale it dies
   unless candidates are clustered by selection overlap and evidence lineage and
   "N opportunities" counts clusters.
9. **"AI-powered" means models propose, never decide.** A model call in the
   decision path makes "the exact same engine in replay" a sentence that cannot
   be true.
10. **Strengthened, not challenged:** the live season is precious. No analysis
    packet is scheduled until the cadence SLO has been green for seven days.

---

## 8. Sequenced plan

**Phase 0 (weeks 1–4): cadence, record, ledger, waist.** Week 1: W1 persist
`all_books` + L0-first (0 credits); W13-forward GUMBO capture (0 credits, starts
a clock); W7 governance (budget constants, cadence SLO, role files, owner items
1–2); W5 instrumentation; W2 universal record; W3 L1 backfill (G0). Week 2:
W4 knowability and grades (G1, owner decision 3); W10 ledger v2 (starts the
forward clock); W6 free environment. Weeks 3–4: W8 snapshot and
price-blindness; W9 the waist with an equivalence proof against `evolab.decide`
on 8,811 genomes × 200 decision points; W11 conformance and truncation
differential (G4 at end of week 4, not week 2); W12 gates, Two-Ledger type and
accounts. Drop order if short: W14 → W6 → W13-backfill. W1, W4, W10, W11 never slip.

**Phase 1 (weeks 3–8): board.** Families switched on in the order of synthesis
§4.6 behind G3 and a measured credit probe; totals replayed end to end; the
substrate grows from 6 features toward ~40, each registered with mechanism,
frozen sign, ladder provenance and grade. Exit: ≥6 LIVE families with
settlement adapters tested on ≥50 games.

**Phase 2 (weeks 6–10): the honest re-run.** The identical Phase 2B protocol
on the expanded substrate with outcome-calibrated log-loss as primary fitness
(fresh registration; the published Phase 2B verdict stands). Verdict published
either way, with effective tests beside raw.

**Phase 3 (weeks 10–16): factory.** `src/factory/**`, adversaries, epochs,
co-occurrence stores, dispatcher, retirement, P7/P8, the LLM proposer against
its registered null. Exit: G5 in some cell, or a published "no cell cleared"
— both are successes.

**Phase 4 (continuous from week 2): forward.** Paper selections toward 300
under `FLAT_1U`; accounts published with fans and nulls; daily computed review.

**Phase 5 (after G6): product.** `ENGINE2` populated; Bet Rating; LOCK if the
pre-registered criteria are met; Picks with the cluster rule.

**Phase 6 (continuous): breadth.** Batter props, derivatives, SGP capture,
each on its own forward evidence clock, each behind G3 and a cost cap.

Deliberately not scheduled: new detectors; mutation operators before a cell
clears; a rating before a calibrated model; any product surface beyond the gate
readout; parlay recommendation code; Tier C without owner sign-off.

---

## 9. Owner decisions (the only ones that are genuinely the owner's)

1. Default branch repoint and the `ODDS_API_KEY` repository secret (already
   requested; gates unattended capture and therefore everything else).
2. Credit envelope: raise the daily envelope from ~132 to ~900 credits/day
   inside the existing 100K monthly allotment, tiers switched on only behind
   measured probes and G3. Recommend yes. Recommend against the ~7,000/day
   full-board plan.
3. Grade C/D policy: `assert_point_in_time` moves from a decision-time hard
   raise to exclude-by-default, explicit opt-in, exposure printed, promotion
   still requiring forward A/B and zero grade-C/D-driven selections. This
   changes a standing refusal.
4. Primary fitness for the re-run: outcome-calibrated log-loss against the
   de-vigged market, fresh registration, Phase 2B verdict unamended.
5. The LOCK definition in section 5, pre-registered now, expected empty for a
   season.
6. Prediction versus money when they conflict (amendment 6), and whether the
   labelled execution ledger runs alongside.
7. Batter props at ~270 credits/day (irrecoverable; declining is not
   reversible), and the SGP capture question.
8. The vendor's prop history and 5-minute historical grid purchase: register a
   hypothesis or accept the permanent gap.
9. Public statement of backtest scope (amendment 2).
10. Correction commits for the believed-but-absent items before anything is
    built on them (the "51 ms" claim, the hash chain, the runbook's unattended
    jobs, the stale credit balance, the "3–4 books" prop figure).

Decided by the orchestrator without owner action: the Two-Ledger Rule;
`FLAT_1U` with Kelly registered disabled; per-cell gating with cells charged as
multiplicity; sport-neutral engine contract from day one; role roster
correction (Sonnet implementers, Fable orchestrator file, dispatcher); the
sequencing above.

---

## 10. What is hard, stated plainly

Settlement adapters are the silent killer: a wrong settlement produces a
confident, plausible, wrong backtest no statistic catches. Prop settlement is a
real data-engineering job that precedes prop prices being worth collecting. A
calibrated probability may never arrive, and the architecture must publish
"nothing cleared" as readily as a winner. 2023–24 can never earn a promotion.
The forward window is slow by construction, and widening the board is the only
honest way to accelerate it, which is why capture wins every prioritization
conflict for 60 days. Thin markets may be unanalyzable. Multiplicity at factory
scale is the real adversary. And every grade-A/B claim about 2026 rests on a
scheduler that, as of this writing, has never fired unattended.
