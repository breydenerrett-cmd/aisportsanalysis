# Evolution Lab — scientific and engineering assessment

Brey proposed a TradingView-style historical replay driving a population of
evolving virtual betting strategies. This is my assessment, written before any
implementation, as he asked. Short version: **the replay engine is excellent
and we should build it. The evolutionary search, as specified, would be a
machine for manufacturing false discoveries — but a specific, smaller version
of it is the most valuable scientific instrument we could build, because it
measures how much luck our own search process invents.**

---

## 1. The central problem: the GA dilemma

Evolutionary search is only NEEDED when the strategy space is too large to
enumerate. But our discovery data is 2023–24: **4,859 games**. A strategy that
bets selectively takes maybe 10–20% of them — 500 to 1,000 selections.

The sample arithmetic is brutal and worth stating exactly. Moneyline bet
outcomes have a standard deviation of roughly one unit per bet. To distinguish
a +2% ROI strategy from a 0% strategy at two standard errors:

    0.02 · n / √n ≥ 2   →   √n ≥ 100   →   n ≥ 10,000 selections

We have 500–1,000. **We are ten to twenty times short of the sample needed to
validate a single realistic edge by ROI** — before any multiplicity correction,
and before searching thousands of strategies.

So the dilemma:

- If the strategy space is small enough that 4,859 games can discriminate
  within it, it is small enough to **enumerate exhaustively** — and then we get
  exact multiplicity control and no GA is needed.
- If the space is large enough to need a GA, it has more than enough capacity
  to fit noise perfectly, and the winner is indistinguishable from an artifact
  using data we possess.

The escape is not a better GA. It is three things: shrink the space with
mechanism constraints until it is enumerable, use a **far higher-information
fitness signal than ROI**, and **measure the noise ceiling directly**.

The external evidence agrees. The published test of 1,547 simple MLB strategies
found ~0.45% profitable at strict significance — the rate pure chance produces.
Our own record is 25 pre-registered specs across four families, zero survivors,
and a closing line that beats a public-methodology Elo (constants chosen a priori, never tuned on our data) by 0.008 log-loss per game
(p = 0.0003). Evolution applied naively to this substrate will find spectacular
backtests. It will find them whether or not any edge exists. That is the
definition of an instrument that cannot inform us.

---

## 2. The reframe that makes it worth building

**Make the lab's primary product the noise ceiling, not the champion.**

Run the identical search — same genome space, same fitness, same selection
intensity, same number of generations — over **placebo worlds**: outcomes
shuffled within date, team identities permuted, signals date-shifted. These
worlds contain zero edge by construction.

The distribution of "best strategy found" across placebo worlds is the answer
to the only question that matters:

> How good does a backtest have to look before it beats what our own search
> manufactures from noise?

This is White's Reality Check and Hansen's SPA implemented by brute force
rather than analytically — and brute force is *better* here, because our search
is adaptive and path-dependent in ways the analytic tests do not model.

It inverts the value proposition. If the real-data champion sits inside the
placebo distribution, we learn that the space is barren — rigorously,
quantitatively, and far more convincingly than 25 individual nulls did. If it
exceeds the placebo ceiling, that is a stronger signal than any p-value we
have ever produced, because the null it beats is the *real* null: our own
search on data known to contain nothing.

Everything else in the design serves this.

---

## 3. Five structural changes to the proposal

### 3.1 Fitness must be CLV-primary, outcome-secondary

The sample math above kills ROI as a screening fitness. Closing-line value is
measured against a continuous price rather than a binary outcome, so its
variance is roughly two orders of magnitude cheaper:

    detect +0.5pp mean move, SD ≈ 3pp:  n ≥ (2 · 3 / 0.5)² ≈ 144 selections

**144 versus 10,000.** This is the difference between a question our data can
answer and one it cannot. Our own Elo benchmark already used this principle —
it scored log-loss against the de-vigged close, not profit.

Two disciplines attach. First, our standing rule: a decision-time-to-close move
is **not** to be called "CLV" loosely, and never called EV. It is movement of
the de-vigged consensus toward the selection, measured only where a defensible
true close exists. Second, selecting on price movement selects for
*microstructure* skill — predicting the market's own revision — not for
predicting baseball. That is a legitimate and interesting target (it is exactly
the V3 lane), but a CLV-positive strategy is a **candidate**, not an edge,
until outcomes confirm it. So: CLV screens, outcomes confirm, forward data
arbitrates.

### 3.2 Split the genome — prediction, execution, staking — and freeze execution during predictive search

Brey's DNA conflates three things our product architecture already separates:

| layer | question | our existing name |
|---|---|---|
| prediction | do we know something the market does not? | Ranker Engine 2 (gated, empty) |
| execution | can we take a better price than consensus? | Engine 1 / price improvement |
| staking | how much? | never part of fitness |

Evolution will absolutely discover execution and dress it as prediction. A rule
that fires when one book sits 8 cents off consensus shows positive backtest ROI
and contains **no forecast whatsoever**. That is line shopping, and calling it
an edge is the exact error our terminology rules forbid.

So: during predictive search, **every strategy in the population executes
identically** — at the de-vigged consensus. Execution genes are held constant.
Execution is then evaluated on its own axis, separately, and can never
contribute to a predictive-edge claim. Staking never enters fitness at all;
flat unit stakes only, with Kelly and friends evaluated afterward for
presentation and never for selection.

### 3.3 Mechanism directions are frozen; evolution may not flip a sign

This is the highest-leverage constraint available, and it comes straight from
how V4 and V5 actually died: **screen-then-flip**. Specs looked strong in 2023
and reversed sign in 2024. Sign-flipping is the single most powerful
noise-fitting move in the space.

Every signal enters the genome with a direction fixed by a written mechanism,
exactly as `funnel.register_family` already enforces. Evolution may tune
magnitudes, thresholds, combinations, confirmations and routing. It may **not**
flip the sign of a mechanism, and it may not introduce a signal without a
mechanism. This removes an enormous share of the noise-fitting capacity while
leaving the genuinely interesting search intact.

### 3.4 Do not spend 2024 as a walk-forward holdout

Nested walk-forward inside 2023–24 buys four to six windows. Evolution consumes
them in a handful of generations: once survivors have been *selected* using the
2024 window, 2024 is contaminated for everything downstream. Finance gets away
with walk-forward because it has decades. We have two seasons and they are the
last clean historical data this project will ever have.

My recommendation is to treat **all of 2023–24 as one search substrate whose
results are explicitly non-evidential**, and let the **forward stream be the
only true holdout** — it accrues at ~15 games/day, it cannot be contaminated,
and it is already instrumented by the ledger. The lab proposes; forward data
disposes. This is slower and it is the only design I can defend.

This is a decision that belongs to Brey, because it is irreversible in one
direction — see §7.

### 3.5 Meta-learning must be placebo-calibrated too, or it is just hidden adaptivity

Brey's idea of penalising genotype families that repeatedly die is
statistically dangerous in its naive form: it uses outcome data to reshape the
hypothesis space, so every later "discovery" is conditioned on it. That is
still adaptive search; it has only moved the adaptivity into the prior where it
is harder to see.

The honest version is elegant: **run the meta-learner inside the placebo
harness as well.** If the meta-learning loop manufactures confident "knowledge"
about which signal families are productive in worlds that contain nothing, we
have measured exactly how much of its output is self-deception. Meta-knowledge
that survives that test may steer engineering priorities. It still never
promotes a strategy.

---

## 4. What I would keep from the proposal, largely unchanged

- **The replay engine.** Deterministic, point-in-time, same-DNA-same-decisions.
  This is infrastructure we want regardless of whether evolution ever runs; it
  is the natural generalisation of the funnel and it makes every future
  strategy evaluation reproducible by construction. Highest-value component in
  the proposal.
- **Execution realism.** No betting prices that were not on the board, no
  retroactive book selection, no knowing the close, no lineup before it posted.
  Building this forces us to confront whether historical "best price" was ever
  actually takeable — which is directly load-bearing for the price-improvement
  product.
- **Death-reason taxonomy and attribution.** This is our falsification battery
  applied per strategy and automated. The battery already does season splits,
  book and team concentration, dose–response and extreme-removal; the taxonomy
  is mostly a reporting layer over machinery that exists and is frozen at
  RULES_VERSION 2.0.0.
- **Lineage.** Cheap to store, and it is what converts a pile of winners into
  knowledge about *which change* mattered.
- **Complexity penalty.** Keep it, but implement it structurally — cap genome
  size — rather than only as a fitness term. A penalty can be outrun by a large
  enough apparent effect; a cap cannot.
- **Islands and diversity measurement.** Genuinely reduce premature
  convergence, and behavioural clustering (do these ten strategies pick the
  same games?) is the correct diversity metric — genetic distance is not, since
  different DNA can express identical selections.

---

## 5. Is there a better architecture? Yes, partly

Brey asked to be challenged. My honest view:

**A genetic algorithm is the wrong tool for the prediction question and the
right tool for the policy question.**

Predicting outcomes better than the market is a smooth statistical estimation
problem. The correct instrument is a strongly regularised model — penalised
logistic regression or a heavily constrained gradient-boosted model — fit
against the market's implied probability, with proper cross-validation. One
model is one hypothesis, with known generalisation behaviour and a tiny
multiplicity burden. A GA doing statistics is a GA doing it badly.

Worth noting: `python3 -m src.cli status` still reports
`probability: UNCALIBRATED -- no fitted model yet`. We benchmarked a
*pitcher-free Elo* against the close and lost decisively. We have never fit a
proper regularised model on the full point-in-time matrix and measured it
against the close. **That test is cheaper than the entire Evolution Lab, uses
data we already have, and answers the prediction question more directly.** It
should come first.

Where a GA genuinely earns its place is the discrete, non-differentiable,
combinatorial layer: market routing, F5 versus full game, book and timing
choice, confirmation counts, no-play rules, threshold structure. That is
decision policy, not estimation — and it maps exactly onto the genome split in
§3.2.

And for small structured spaces, Bayesian optimisation or a coarse exhaustive
grid beats a GA on sample efficiency *and* gives exact multiplicity control.
Given §1, our space should be small. So the GA may turn out to be unnecessary —
which is a good outcome, not a disappointing one.

---

## 6. Statistical safeguards required

Ordinary BH-FDR — which our funnel applies over frozen families — is **not
sufficient here**, because it assumes a fixed pre-specified family and our
search is adaptive. Required additions, in order of value:

1. **Placebo-world calibration** (§2). The primary safeguard. Empirical null
   for the maximum, under our exact search procedure.
2. **Probability of Backtest Overfitting** via combinatorially symmetric
   cross-validation (Bailey & López de Prado). Directly designed for this
   failure mode; reports the probability that the selected strategy's
   out-of-sample rank falls below median. Implementable and honest.
3. **Hansen's SPA / White's Reality Check** as the analytic cross-check on the
   placebo result — they should agree; if they disagree, we have a bug.
4. **Deflated Sharpe** is adaptable but designed for return series; with our
   sample sizes it adds little the placebo ceiling does not already give.
5. **The existing frozen falsification battery** on every champion candidate,
   unchanged, at its frozen fingerprint.

Discard the buzzwords that do not fit: nothing here needs SHAP. Straight
**ablation** — remove one component, re-run, measure — is more honest and more
interpretable for rule-based genomes than any attribution approximation.

---

## 7. Decisions — BOTH SETTLED BY BREY, 2026-08-31

Recorded here for the history; the live design is `docs/EVOLAB_DESIGN.md`.

**Decision 1 — RESOLVED.** 2023–24 is one explicitly exploratory,
non-evidential sandbox. 2024 is NOT treated as a pristine holdout: we have
already learned from it through V1–V5, feature development and architecture
choices, and pretending otherwise would overstate independence. Chronological
folds inside 2023–24 remain available as *internal anti-overfit tools*
(walk-forward diagnostics, stability, PBO/CSCV, placebo calibration) but never
become clean external evidence. The forward stream is the first independent
arbiter. 2025 stays tuning-only; sealed 2026 untouched.

**Decision 2 — RESOLVED.** The prop-listing feasibility audit is approved
narrowly, under a policy amendment separating FEASIBILITY MEASUREMENT from
RESEARCH COLLECTION. It may record whether pitcher-K markets are listed, which
books list them, when they first appear, `last_update` stamps and coverage. It
may not test price strategies, tune thresholds, infer an edge, or run outcome
analysis. The artifact is frozen and timestamped, and any later pre-registered
prop hypothesis must state that this coverage information was already known.

**Brey's correction, accepted:** the ~144-selection figure below is an
optimistic power illustration, not an evidence threshold. Real uncertainty must
use observed variance with clustering by date, team and book, and resampling
that respects dependence.

## 7b. The original framing of those decisions

**Decision 1 — the 2024 question.** Do we (A) treat all of 2023–24 as one
non-evidential search substrate and let forward data be the only holdout — my
recommendation, slower, defensible; or (B) spend 2024 as a walk-forward
validation window, faster and irreversibly contaminating our last clean
historical season? Once 2024 has been used to *select*, it cannot be restored.

**Decision 2 — the prop-listing audit** (carried over, unrelated to this).
Design is at `docs/PROBE_PROP_LISTING.md`: 18 credits/day, ~340 total, inside
the daily envelope, but `docs/COLLECTION_POLICY.md` forbids prop collection
without a registered hypothesis. Options in §9 below.

Everything else in this document I consider mine to decide, and I have.

---

## 8. Recommended plan

Phases are sequenced so that **each one can kill the next**, which is the point.

### PHASE 0 — feasibility audit (worker; ~half a day)
Establish what the replay can honestly serve at each historical timestamp:
odds granularity in 2023–24 (how many observations per game, is there a
defensible close), which matrix features are point-in-time clean (already
audited), whether "best available price" was ever simultaneously takeable.
**Acceptance:** a written table of what the replay may and may not reveal.
**Kill condition:** if 2023–24 odds granularity is one observation per game,
timing-sensitive strategies are unbacktestable and the lab shrinks to
static-feature strategies only.

### PHASE 1 — deterministic replay engine (worker; 1–2 days)
Point-in-time clock, reveal-only-what-existed, same-DNA-same-decisions.
Reuses: matrix, funnel/compiler, pricepath, odds stores, selections/de-vig.
**Acceptance:** byte-level determinism across runs; an injection test proving a
fact dated after T never reaches a decision at T; replay of a known V1 spec
reproduces its published numbers exactly.

### PHASE 2 — enumerable strategy space + placebo harness (worker; 2–3 days)
A small, mechanism-constrained, direction-frozen genome — target a space of
10³–10⁴ that is **exhaustively enumerable**. CLV-primary fitness. Then the same
exhaustive sweep over N placebo worlds.
**Acceptance:** real-vs-placebo distribution of the maximum, with PBO reported.
**This phase is the actual experiment.** If the real maximum sits inside the
placebo distribution, we have learned the space is barren — publish it, and
evolution never gets built. That is a success, not a failure.

### PHASE 3 — regularised model versus the close (worker; 1 day, parallel)
The cheap direct test of the prediction question that we have never run.
Independent of the lab; informs whether prediction deserves any further
compute at all.

### PHASE 4+ — evolution, islands, meta-learning, champion ladder, UI
**Conditional on Phase 2 showing real signal above the placebo ceiling.** If it
does not, these phases are not built, and the correct conclusion is that the
strategy space reachable from our feature set is empty — a far stronger
statement than we can make today.

Everything in the lab lives in its own evidence namespace
(`data/research/evolab/`, `docs/EVOLAB_*`), is versioned separately, and
**nothing leaving it is evidence**. It cannot touch V1–V5 artifacts, cannot
alter frozen families, and cannot promote anything. Sealed 2026 is untouched;
2025 keeps its tuning-only role.

---

## 9. The prop-listing decision, stated compactly

**OPTION A — allow the limited listing/coverage audit now.**
Collects: which books list pitcher-strikeout markets for an event, when they
first appear, and their `last_update` stamps. Records no analysis of prices and
runs no inference. Contamination risk is low but not zero: knowing coverage and
listing times *before* registering a family lets those facts shape the
hypothesis — which is why it must be recorded as a feasibility artifact and
explicitly cited in any later pre-registration as prior knowledge.

**OPTION B — keep it parked until a family is pre-registered.**
Costs: every day unmeasured is a day of listing-time data that cannot be
recovered, and C1 cannot be registered without knowing whether the market is
even listed early enough for its mechanism to exist. This is a genuine
chicken-and-egg: the prerequisite for registration is the thing policy forbids
collecting before registration.

**My recommendation: Option A, narrowly** — listing times and coverage only,
no prices, no analysis, results recorded as a feasibility artifact rather than
a finding, and the policy amended in one line to permit *feasibility
measurement* (as distinct from *research collection*) without a registered
hypothesis. That distinction is the actual gap in the policy.

Brey decides. Nothing starts without his word.
