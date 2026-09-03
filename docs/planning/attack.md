# LINEHOUND — Adversarial Attack on the Synthesized Architecture

Hostile read of `docs/planning/synthesis-judge.md` (2026-09-03) and the three
designs and nine maps it cites. Written from three seats: a **hostile
statistician** who wants to prove the edge is noise, a **hostile sportsbook**
that wants the backtest to be unrealizable, and a **hostile engineer** who wants
the machinery to break silently.

Rules of this document: nothing here is evidence; every finding names a fix;
every fix is mechanical (a field, a test, a gate, a registered spec) rather than
a caution. Findings are graded **FATAL** (invalidates results or the product if
unaddressed), **SERIOUS** (materially degrades a claim), **MINOR** (correctness
hygiene). Section 5 is pushback on the owner's own description.

The synthesis is good. It is the best of the four documents and most of what
follows is an attack on its *strongest* claims, because those are the ones that
will be quoted. Two of the findings below (F1, F2) would, if unaddressed, make
every number the factory ever publishes uninterpretable.

---

## 1. Hostile statistician

### F1 — FATAL. The document defines the independence unit three different ways, and the three differ by ~two orders of magnitude.

`§4.7` says "roughly **4,860 independent units**" (game-days) and builds the
whole scale argument on it. The same paragraph then says outcomes "within a day
share weather, umpire pools and market regime" — which denies that game-days are
independent. `§4.2`'s `Scorecard` requires
`n_independent_clusters  # game-day blocks >= 7 days`. Two seasons of 7-day
blocks is roughly **52 clusters**, not 4,860.

Every clustered bootstrap CI, every `spa_p`, every "CI excluding zero" in the
promotion gates scales as 1/sqrt(clusters). A result that is significant at
n=4,860 and null at n=52 is the *median* case, not the corner case. Whichever
number is chosen silently by whoever writes `score.py` first becomes the
project's effective significance threshold forever.

**Fix.** Register one clustering spec, once, before Phase 2:
`CLUSTER_SPEC = {unit, block_length_days, metric, version}` in
`config/` and hashed into every `Scorecard`. Choose `block_length_days`
empirically: measure the autocorrelation of daily residuals (market-relative)
on 2023-24 and set the block at the first lag where it is indistinguishable
from zero, with the measurement published. Report `n_decisions`,
`n_game_days` and `n_independent_clusters` as three separate required fields on
every scorecard and every published verdict; a claim that quotes only one is
invalid. Strike "4,860 independent units" from `§4.7` and replace it with the
measured cluster count.

### F2 — FATAL. The placebo ceiling is computed against a null that does not contain the board-wide argmax, so board expansion mechanically manufactures ceiling clears.

`§3.1` rules that one thesis projected onto forty selections is **one test**,
provided the acting rule ("highest rating net of friction") is pre-registered.
Pre-registration stops *shopping*. It does not remove the selection effect: the
statistic actually scored is `max` over up to forty correlated per-selection
statistics, and the max of forty has an expectation strictly above any one of
them. The synthesis charges `total_searched()` one and moves on.

This is fatal because the placebo ceiling is the project's primary defence and,
as specified in `§4.4 step 04`, the placebo worlds are run through the same
sweep as the real world. If the sweep in a placebo world scores one
pre-declared market while the real world argmaxes over forty, the ceiling is
computed from a lower-variance statistic than the one being tested. Widening the
board from h2h to h2h+totals+alternates+props then *raises* the real maximum
without raising the ceiling, and the project's headline safety mechanism starts
producing clears as a direct function of board width. That is precisely the
outcome the owner's whole-board ambition would generate, and it would look like
success.

**Fix.** The null must run the full decision function. Placebo worlds execute
`analyze()` end to end — propose → project over the same board → friction →
argmax — so the ceiling absorbs the max-over-selections effect. Make this a
property test: for a genome with a deliberately zero-signal proposal, the real
world's maximum must sit inside the placebo distribution at every board width
{1, 2, 10, 40 selections}; if the percentile rises with board width, the ceiling
is mis-specified and the sweep refuses to write a verdict. Additionally record
`n_selections_projected` on every `DecisionRecord` and `Scorecard`, and report
the ceiling stratified by it.

### F3 — FATAL. Fifty placebo worlds cannot support the percentile the ceiling language implies.

`§4.4` specifies "real world + 50 placebo + P7". With 50 draws the finest
resolvable quantile is 1/51 ≈ 0.02, the 99th percentile is not estimable at all,
and the standard error of an extreme empirical quantile at n=50 is large enough
that the same population re-run would move the verdict. Phase 2B's published
pooled percentile of 13.3 was comfortably in the body of the distribution so the
resolution never mattered; the first result that lands in the tail is the one
where it matters most, and it is the one that will be published.

**Fix.** Set the number of placebo worlds from the pre-registered ceiling
percentile by power analysis before the sweep, and refuse the sweep if
`n_worlds < ceil(20 / (1 - percentile))` (≥ 400 worlds for a 95th-percentile
ceiling, ≥ 2,000 for a 99th). Report the ceiling as a value **with a one-sided
bootstrap CI**, and let the kill criterion compare against the conservative
bound, not the point estimate. If 400+ worlds is not affordable, the honest move
is to lower the declared percentile — not to keep 50 worlds and speak as though
a tail were being measured. `ceiling.py` must raise, not warn.

### F4 — FATAL. The forward window is the factory's tuning set. "Forward testing" as specified is a slow in-sample search.

`§4.4`'s cycle runs `01 generate → … → 05 score → … → 08 transition` **daily**,
and `§4.4`'s lifecycle has `FORWARD_TESTING → PROMOTED`. Generation mutates
"only within unlocked cells" but nothing forbids the generator, the dedupe step,
the graveyard, or the human/model reading the artifacts from conditioning on
forward scorecards. Over 60+ days of daily cycles, a population that is culled
and re-seeded against forward results is being fit to the forward window one
day at a time. At that point G6's "≥300 forward selections" measures a
search that consumed the forward window, and the standing constraint "sealed
2026 untouched" is satisfied on the letter (nobody read a sealed directory)
while being violated in substance.

**Fix.** Split the forward window into **generation-sealed epochs**. A cohort of
systems is registered and frozen at epoch start; during the epoch the factory
may score and report but the generator, the mutation operators, the graveyard
dedupe and any model-authored proposal may not read any scorecard whose window
overlaps the open epoch. Enforce it the same way the store is sealed: forward
scorecards live under `evidence/factory/forward/<epoch>/` and `src/factory/generate.py`
carries a path-allowlist that cannot open it, with a test that tries. Epoch
length is declared in advance (e.g. 45 days). Promotion evaluates a cohort at
epoch close. A system whose cohort is broken by any mid-epoch regeneration
restarts its forward clock, and the restart is a published graveyard-style row.

### F5 — FATAL. Model-proposed strategies are contaminated by pretraining knowledge of the discovery seasons, and no control in the design touches it.

`§4.8` gives Sonnet "bulk generation of schema-valid strategy specs with
mechanism strings"; `§2` item 13 registers H-PROP-1 (proposed strategies do not
beat enumerated ones per unit of `total_searched()`). H-PROP-1 measures
*efficiency*, not *contamination*. A model trained past 2025 has seen 2023-2025
MLB results, public handicapping folklore, and any published edge in this space.
Its proposals are a posterior conditioned on the outcomes of the exact seasons
used for discovery. `alpha_registry.total_searched()` counts the searches this
repository performed; it cannot count the ones the pretraining performed, and
the pretrained search space is enormous and unbounded.

Worse, this contamination is invisible to every control in `§4.5`. It is not a
timestamp leak, so `as_of` cannot catch it. It is not a forbidden field, so the
recursive name check cannot catch it. It survives P7 unchanged, because shifting
T by two hours does not change what the model memorized.

**Fix, four parts.**
1. Model-origin systems are **barred from scoring on 2023-2025**. Their only
   admissible evidence window is the forward epoch (F4), where the outcomes did
   not exist at training time. Enforce in `lifecycle.py`: `origin == "model"`
   ⇒ `SCREENED`/`REPLICATED` transitions raise.
2. Every model-origin proposal records `model_id`, `prompt_hash`,
   `training_cutoff` and the full prompt text; a proposal whose prompt names a
   season, a team, a player or a result is rejected by a validator before
   registration.
3. Run a **memorization probe** and publish it: ask the proposer, with no
   features and no data, to predict outcomes for a held-out 2024 sample. If it
   beats the market-implied base rate at all, the contamination is measurable
   and the bar in (1) is not conservative, it is required. Register the probe as
   a hypothesis with its own verdict row.
4. Model-origin proposals carry a **separate multiplicity charge and a separate
   ceiling**. Their prior is not exchangeable with the enumerator's, so pooling
   them into one `total_searched()` understates the burden on the model arm and
   overstates it on the enumerated arm.

### F6 — FATAL. G4, the week-2 exit gate, tests the wrong hypothesis. It detects divergence between two paths; it cannot detect a leak both paths share.

`§2` item 18 and `§4.5` item 8 call the live/replay fingerprint conformance test
"the single most valuable test any of the three proposes, and it is the only one
that would catch a leak both paths share." That is exactly inverted. The test
asserts `live_fingerprint == rebuilt_fingerprint`. If the live assembler and
`as_of` both read a `probable_pitcher` whose `known_at` was authored rather than
observed, both produce the same bytes and the test is green. Making the two
paths one function — the synthesis's central and correct move — *removes* the
only mechanism by which the conformance test could ever have caught a shared
leak. The design's strongest control is strongest against the failure mode the
design has already eliminated.

**Fix.** Keep G4 (it is a real non-regression gate) but rename what it proves —
"the store is a faithful record of what the live path saw" — and add the two
tests that actually attack leakage:
1. **Truncation differential.** Build the Snapshot for `(game, T)` from a store
   physically truncated at T, and again from the full store. Byte-equality is
   required. Any inequality is a late read. This is cheap, runs on history, and
   catches every ordinary leak. Make *this* the CI-blocking gate.
2. **Per-field provenance assertion.** Every field in a Snapshot carries the
   `capture_id` and `observed_utc` of the L0 row it came from; `as_of` asserts
   `observed_utc <= T` per field at construction and raises naming the field.
   A grade is a label; a provenance assertion is a proof.

### F7 — FATAL. The end-of-day review is an outcome-conditioned hypothesis generator, and its output is uncounted multiplicity over the same window it was derived from.

`§4.2`'s `ReviewRecord` carries `missed_information` and `new_hypothesis`, and
`§4.3` runs `review.run(date)` after settlement. A human or a model reads
settled outcomes, notices what would have worked, and queues a hypothesis. That
hypothesis is then tested on data that includes the days that generated it.
`total_searched()` never increments, because nothing registered a search. This
is the single most productive false-positive machine the architecture contains,
and it is the one the owner explicitly asked for ("missed info? new
hypothesis?").

**Fix.** `new_hypothesis` is a *registered* object at the moment it is written:
`origin: "review"`, plus `derived_from_window: (first_date, last_date)`
covering every settled day the reviewer could have seen. `funnel.register_family`
and the factory's `register` step both refuse to evaluate a review-origin
hypothesis on any window overlapping `derived_from_window`. The count of
review-origin hypotheses is charged to `total_searched()` at registration,
whether or not any of them is ever run — because they were searched.

### F8 — FATAL. In-sample and out-of-sample decisions are pooled because nothing records when a system's parameters were frozen.

`AnalysisSystem` carries `id`, `version`, `spec_hash` — no freeze instant. A
genome enumerated over the 2023-24 matrix (which is how Phase 2B ran) is
selected using the same games it then scores. The lifecycle's
`SCREENED(2023) → REPLICATED(2024)` ordering helps only for systems that respect
it; nothing enforces it, and `objective()` receives a single pooled Scorecard.

**Fix.** Add `parameters_frozen_at: str` to the system contract, required, and a
`sample_class` field on every `DecisionRecord` computed as `IN_SAMPLE` when
`decision_utc < parameters_frozen_at` else `OUT_OF_SAMPLE`. `Scorecard` reports
`n` and every metric separately per `sample_class` and **refuses to emit a
pooled figure**. `promotion_gates.json` floors read only the out-of-sample
columns. Run it against Phase 2B's best genome as an acceptance test alongside
the `promote() == REFUSED` test already specified in W12.

### F9 — FATAL. The Two-Ledger AST test blocks six names, not the quantity. It is circumventable from fields the objective is allowed to read.

`FORBIDDEN_OBJECTIVE_FIELDS = {account, bankroll, units, drawdown, roi_units,
profit_units}`. `Scorecard` also exposes `realized_return`, `avg_odds_decimal`,
`n_decisions`, `top5_win_share` and `stability`. A bankroll path is a
deterministic function of realized returns, odds and ordering; an objective that
reads `realized_return * n_decisions` and penalises `top5_win_share` is a
bankroll-shaped objective that passes the AST test cleanly. The synthesis is
right that "a rule that is a column cannot be forgotten in a refactor" — but a
rule that is a *name blocklist* can be reimplemented in a refactor by anyone
under deadline, in good faith.

**Fix.** Make the boundary a type, not a lint. `objective()` takes
`ObjectiveView`, a frozen projection of `Scorecard` that structurally does not
contain `account`, and whose construction is the only way to obtain one. Keep
the AST test as a second line, and extend its blocklist to the derived path:
fail if `realized_return` appears anywhere in the same expression as
`n_decisions` or a cumulative/`sum`/`cumprod` call. Add one adversarial test
that *tries* to smuggle a bankroll in from allowed fields and asserts the guard
catches it — a guard nobody has attacked is a guard nobody has tested.

### F10 — FATAL. Every grade-A/B claim in the 2026 corpus is downstream of a scheduler whose observed unattended success rate is zero.

`§7` P0 item 3 and `§10`'s last bullet both record it: zero `forward-capture-bot`
commits exist, `*/15` cron cannot fire from an orphan default branch, and four
container restarts in an hour were observed (platform-driven). The synthesis
then specifies Tier A as a 15-minute grid over 18 hours — **72 successful
unattended firings a day, every day** — and makes `known_at_grade` B contingent
on the poll bracketing an event. Grade B is an *assertion about cadence*. If the
cadence has a six-hour hole, every fact bracketed across that hole is a grade-C
fact wearing a grade-B label, and the difference-in-kind that "the live season is
precious" is supposed to purchase does not exist.

**Fix.** Grade is **computed, never asserted**. `known_at_grade` is derived from
the measured gap between the last poll that did not contain the fact and the
first that did: `gap <= 20min ⇒ B`, `<= 2h ⇒ C`, else `D`. Publish a daily
cadence SLO — attempted, succeeded, longest gap, p95 gap — as a store-health
artifact, and make **7 days of measured cadence** a precondition of W14 (any
paid tier switch-on) and of any claim that 2026 is a grade-A/B season. The
existing `assumption_exposure` field then reports something measured rather than
something hoped.

### F11 — FATAL. A single published 1,000-unit bankroll curve is the most persuasive misleading artifact this project could ship.

`§3.6` keeps the account simulation "in full" and publishes it, correctly
excluded from selection. But one curve over one season is one draw from a
distribution whose SD `§9.3` itself computes as ≈ 5.7 ROI points at n=300. A
reader — including the owner — will read a rising curve as performance. The
Two-Ledger Rule protects the *machine* from the bankroll; it does nothing to
protect the *reader*.

**Fix.** No account curve is publishable alone. Every published curve ships with
(a) a fan chart of ≥1,000 day-clustered bootstrap resamples of that system's own
settled decisions, (b) the same system's curve under a zero-edge null at the
same odds, dates and n, and (c) the exact probability of the observed terminal
bankroll under that null. Pin it with a test on the artifact validator: an
account artifact without `null_terminal_percentile` fails to write.

### S1 — SERIOUS. Unlocking 302,271 totals rows doubles the board and adds approximately zero independent evidence, while doubling the multiplicity.

`§2` item 2 calls it "the most valuable discovery in the entire twelve-document
set" and says it "roughly doubles the historically replayable board". True for
markets. But a full-game total and a full-game moneyline on the same game are
driven by the same run environment, the same starters and the same weather;
their residuals against a de-vigged market will be strongly correlated. The
independent-cluster count does not move. What does move is `total_searched()` —
a second family over the same games.

**Fix.** State it in the language of `§4.7`: "doubles the board, adds ~0
independent game-days, and doubles the multiplicity charge." Measure the
h2h/totals residual correlation on the backfilled rows as the first thing W3
produces, and publish it beside the row counts so nobody reads 302,271 as
302,271 new observations.

### S2 — SERIOUS. `effective_tests` is a researcher degree of freedom that divides the multiplicity charge, and nothing registers how it is computed.

`§3.9` requires reporting "the effective number of tests (clusters from the
selection-overlap matrix) alongside the raw count". Whoever picks the similarity
metric, the linkage and the cut threshold picks the effective count, and the
effective count is the denominator of the FDR burden. This is threshold shopping
one level up, in the exact place nobody will look.

**Fix.** `CLUSTER_SPEC` (metric, linkage, threshold, version) is registered in
`alpha_registry` before the sweep and hashed into every verdict, exactly the way
`battery.RULES_VERSION` and `rules_fingerprint()` already work. Report
`effective_tests` under three pre-declared thresholds (tight/medium/loose) and
use the **most conservative** for the verdict. A verdict whose sign flips across
the three thresholds is reported as indeterminate, not as a clear.

### S3 — SERIOUS. P7 is one-sided, is a no-op on most historical games, and is blind to the leak class that matters most.

`§4.5` item 9: advance T by +2h; if the objective improves, suspect a leak. Three
problems. (1) On 2023-24 the median board spacing is six hours, so +2h leaves the
snapshot fingerprint **unchanged** for a large fraction of games — the test
silently does not run. (2) It is one-sided; a real edge should also degrade under
−2h, and the asymmetry is informative. (3) It cannot see a *non-temporal* leak:
a season-aggregate feature computed over the whole season leaks the future
identically at T and T+2h, so P7 is exactly blind to the leak class that
`matrix.py`'s monthly-cutoff discipline exists to prevent.

**Fix.** (a) Report `frac_games_fingerprint_unchanged` for the P7 world; if it
exceeds a declared bound the P7 verdict is `NOT_RUN`, not `PASS`. (b) Add the
−2h arm and require monotone degradation in both directions. (c) Add **P8, the
aggregation placebo**: rebuild every derived feature twice — once from data
truncated at game start, once from the full season — and require byte-equality.
Any inequality names a lookahead in the feature builder. This is a cheap,
deterministic, one-time test that catches the class P7 cannot.

### S4 — SERIOUS. `assumption_exposure` reports grade-C/D dependence but no gate floors it, so a grade-D field can be the dominant driver of every survivor.

`§3.2` settles on exclude-by-default plus opt-in plus printed exposure. But
`§4.5`'s honest-limits paragraph records that the stored probable pitcher agrees
with the actual first-pitch thrower 99.90%/99.92% — "12-41× too clean for a real
scratch rate", i.e. the field is functionally a partial read of the outcome. A
system that opts into grade D and leans on it will look excellent and will be
publishable, with a number printed next to it.

**Fix.** Add `share_of_selections_driven_by_grade_CD` to `Scorecard`, computed by
re-running the system with each C/D input ablated and measuring selection
churn. Add a promotion gate flooring it at 0 for any PROMOTED system. Grade-D
inputs are then legal for exploration and structurally incapable of reaching
promotion, which is the behaviour `§3.2` describes but does not enforce.

### S5 — SERIOUS. Historical price age is unrecorded, and the resulting bias is not signed.

With median 6-hour board spacing, "the price at T" is "the last price seen up to
six hours before T". A thesis correlated with *when the book moves* is scored
against a price that either already embeds the move or has not yet seen it, and
which of those it is depends on the thesis. The bias is therefore not
conservative and cannot be waved through.

**Fix.** `DecisionRecord` carries `price_age_seconds` and a derived
`price_staleness_grade`; `Scorecard` reports every metric stratified by
price-age bucket; a result that exists only in the `>2h` bucket is void by
rule, not by judgment.

### S6 — SERIOUS. The 2023-25 L1 backfill has no L0 and can never be verified against provider bytes.

`§4.1` makes L0 "the only layer that must be backed up" and L1 "rebuildable
byte-identically" from it. For 2023-25 there is no L0: `odds_history/*.jsonl` is
already a projection made by code that, per `§7` P0 item 1, was discarding five
of six computed market families. The backfill will faithfully reproduce whatever
the original projection kept and can never recover what it dropped.

**Fix.** Stamp every backfilled row `l0_available: false` and give it a distinct
provenance grade. G0's acceptance ("reproduces the legacy store row for row")
proves non-regression against the legacy projection, not fidelity to the
provider — say so in the gate's own wording, and never quote L1 2023-25 as
byte-reproducible from source.

### S7 — SERIOUS. Selection overlap and outcome correlation are different objects, and the co-occurrence store is being asked to be both.

`§3.8` says the co-occurrence store "is not parlay-specific: it is also the
instrument for population correlation and the effective-number-of-tests count in
§3.9, so it earns its keep twice." A bitset AND plus popcount measures how often
two systems *pick the same selection*. Parlay pricing needs how often two
*outcomes* co-occur. Two systems can have zero selection overlap and perfectly
correlated legs; two legs can have identical selection patterns and independent
outcomes. Conflating them will put a selection-overlap number into a joint
probability and produce confidently wrong parlay prices.

**Fix.** Two named instruments, two stores, two tests: `selection_overlap`
(inputs to `effective_tests`) and `outcome_covariance` (settled outcomes,
clustered SEs, its own sample-size gate). Neither is permitted to be passed to
the other's consumer — enforce with distinct types.

### S8 — SERIOUS. The SGP correlation instrument is not identified from one price.

`§3.8` and `§9.7` propose recovering `book_implied_correlation` from the SGP
price against the product of leg prices. That single number confounds at least
three things: the book's correlation estimate, its correlation *surcharge* (a
margin applied precisely because correlated parlays are where books get hurt),
and any leg-price adjustment inside the SGP builder. One equation, three
unknowns.

**Fix.** State the identification problem in the research registration. Require
either (a) ≥2 SGP quotes over the same leg set at different lines, or (b) the
same leg set at ≥2 books, to separate margin from correlation — and if neither
is obtainable, publish "the instrument is unidentified with available data" as
the finding. That is a real deliverable and it is much likelier than an edge.

### S9 — SERIOUS. LOCK condition (5) — "two systems with disjoint `declared_inputs`" — measures declaration, not independence.

Park factors and umpire tendencies are disjoint declarations and the same
underlying run-environment signal. Two systems built on correlated proxies agree
almost always, and the condition converts near-certain agreement into a
confidence upgrade. This is the exact failure mode `§3.9` identifies at
population level, reappearing inside the LOCK definition.

**Fix.** Replace declaration-disjointness with a measured criterion: the two
systems' historical selection agreement rate must be **below** a pre-registered
threshold, and their residuals against the de-vigged market must be uncorrelated
at a pre-registered level with clustered CIs. Both are computable from the
`selection_overlap` store the design already builds.

### S10 — SERIOUS. LOCK condition (2) — band ECE ≤ 0.02 at band_n ≥ 200 — will be crossed by noise, and the auto-withdrawal makes the label flicker.

At n=200 in a single probability band the sampling SE of ECE is on the order of
0.03. A hard 0.02 threshold with automatic withdrawal on first failure produces
a label that appears and disappears at random, and every appearance and
withdrawal is published. That is worse for credibility than never shipping LOCK.

**Fix.** Require the **upper** bound of a bootstrap CI on ECE to sit under the
threshold, require k consecutive review cadences (k declared in advance), and
set `band_n` from the same power analysis `§3.7` already promises for `N_LOCK`.
Publish the CI, not the point estimate.

### S11 — SERIOUS. Publishing a LOCK moves the price, and nothing accounts for own-impact.

LOCK condition (4) tests survival at the worst book *before* publication. After
publication the price the reader gets is not the price the engine saw. Without
recording that, the LOCK's realized edge is systematically overstated by an
unmeasured amount.

**Fix.** Record `post_publication_price_drift` for every published LOCK
(price at publication vs. best available at +15/+60 minutes) and make sustained
adverse drift a declared demotion trigger. It is also the only honest way to
answer "should we publish LOCKs at all".

### S12 — SERIOUS. "A LOCK base rate above ~2% is a defect" creates a one-sided incentive.

`§3.7` and `§9.8` publish the rate and treat >2% as a defect. Under-labelling is
then costless and looks like rigour, so the equilibrium is a system that never
LOCKs anything and is never criticised for it.

**Fix.** Publish both tails: the LOCK rate **and** the count of candidates that
missed LOCK on exactly one condition, with which condition. Silence then has to
justify itself the same way a label does.

### S13 — SERIOUS. `KELLY_QUARTER_CAPPED_2U` cannot be declared before a calibrated probability exists.

`§3.6` and owner decision 7 ask for a stake rule declared before the forward
record starts, offering a Kelly variant. `§10` says a calibrated probability may
never arrive. Declaring a stake rule whose only input does not exist is a rule
that will be silently re-specified later, which is exactly what pre-declaration
is meant to prevent.

**Fix.** Forward paper starts on `FLAT_1U` only. Register the Kelly variant now
as **disabled**, with a named unlock condition (a calibration gate with a stated
ECE and band_n). A stake-rule change forks a new account with a new id; the old
curve is never rewritten, and both are published side by side.

### S14 — SERIOUS. The alpha registry has no representation for a population, so `total_searched()` breaks in both directions at factory scale.

81 rows today. Registering 5,000 systems per cycle makes the file and the query
surface useless; registering a whole sweep as one row (Phase 2B's approach)
undercounts by ~8,811.

**Fix.** Two levels. `population_registration` is one row carrying the cell
spec, the generator, `n_enumerated`, the dedupe spec, `CLUSTER_SPEC`,
`n_effective` and the ceiling spec — registered before evaluation. Individual
system rows are written only for systems reaching `ATTACKED` or beyond.
`total_searched()` returns the pair `(raw, effective)` and raises if a caller
asks for a scalar.

### M1 — MINOR. `§4.4`'s "50 placebo + P7" makes 52 worlds, not the 51 used in the 9.8 TB arithmetic. Harmless now; fix the constant before it is quoted.

### M2 — MINOR. `semantic_hash_v0` catching only exact atom-set duplicates is documented as a floor; make it a *measured* floor by reporting, per cycle, the fraction of registered systems whose nearest neighbour exceeds the tight overlap threshold. A floor with no measurement is indistinguishable from a ceiling.

### M3 — MINOR. The `no-new-information` refusal makes cadence unauditable: "we re-evaluated and agreed" is indistinguishable from "we did not run". Write a `tick` row (fingerprint, t, unchanged) to the **capture** log, never the decision ledger, so the 300-gate stays honest and the cadence stays visible.

---

## 2. Hostile sportsbook

### F12 — FATAL. There is no limit or max-stake field anywhere, so "edge net of friction" is fiction on exactly the markets the board expansion is for.

`PriceObservation` records book, price, line, timestamps and `venue_kind`. It
does not record what you could actually get down. Alternates, team totals and
especially batter props are limited to small stakes, and a book that sees a
winner cuts the limit further. A whole-board ranker that maximises edge net of
vig, book count, staleness and dispersion will systematically select the
markets with the smallest realizable stake, and the account simulation will pay
out on wagers that could never have been placed at that size.

**Fix.** Add `limit_observed` / `max_stake` to `PriceObservation` if the provider
exposes it; if it does not, record the absence explicitly and add a
**declared per-family limit assumption** to `MarketFamilySpec`
(`assumed_max_stake_units`), printed in `assumption_exposure` and used to cap
`stake_units` in the account simulation. Report every account curve twice: at
declared limits, and unconstrained. The gap between the two is the honest size
of this problem.

### S15 — SERIOUS. Best-book shopping assumes accounts everywhere and an unlimited welcome. Books close winners.

`Board.best()` and the LOCK's "survives at the worst book" bracket the range,
but the account simulation as specified will silently assume you can take the
best of seven books every night indefinitely.

**Fix.** `AccountSummary` declares a `books_available` set. Publish three
scenarios per account: best-of-all, best-of-two (the realistic long-run state
for a winning bettor), and single-book. If the edge only exists in
best-of-all, say so in the headline.

### S16 — SERIOUS. The `StaleBook` adversary removes the one thing that reliably makes money, and the design does not tell the owner it is making that trade.

`§3.4` correctly separates beating the close via stale books (execution) from
prediction, and `§4.2` lists `StaleBook` among the adversaries that can remove a
candidate. That is the right *research* call and it is a very expensive
*commercial* call: execution-quality edges are real, findable and much faster to
demonstrate than predictive ones.

**Fix.** Do not soften the research rule. Instead make the trade explicit and
measurable: run a parallel, clearly-labelled **execution ledger** that records
what a stale-book strategy would have done, scored on CLV only, never entering
`objective()` and never published as EV or edge. It costs almost nothing (the
board is already captured), it is the honest measurement of the road not taken,
and it stops the question being re-litigated from memory every quarter.

### M4 — MINOR. Prediction markets need more than `venue_kind` and a fee model: exchange prices are post-fee-asymmetric and depth-limited in a different way. Record depth-at-price if the venue exposes it, or declare its absence.

---

## 3. Hostile engineer

### F13 — FATAL. The credit envelope is priced on unmeasured per-event costs, on top of a balance whose semantics are misread.

`§3.12` recommends ~900/day: Tier A 216 (measured — featured is 3 credits flat),
Tier B ~270 and Tier C ~420 (**both assumed**). `map-odds-provider-markets.md`
is explicit that alternates, team totals, batter props and first-inning markets
are "per-event (assumed)" and that only `pitcher_strikeouts` has any
measurement. Separately, `~99,621` is a **monthly quota remaining** on a
100K/$59 tier (`PRICING_TIERS`, `odds.py:237-243`), not a bank balance; calling
it a "measured balance" with "~70% headroom" reads as a stock when it is a flow
that resets. The arithmetic happens to survive (27k < 100k) but the reasoning
will not survive the first person who plans a multi-month backfill or crosses a
reset mid-run.

**Fix.** (1) G2 requires a **1-credit measured probe per family** before that
family enters the envelope arithmetic; a family with no measured cost cannot be
budgeted. (2) Apply W14's ±15% measured-vs-estimated acceptance test to *every*
family at switch-on, not just Tier B. (3) Express the constant as
`MONTHLY_ALLOTMENT` (tier fact) and derive `DAILY_ENVELOPE = allotment / 30 ×
utilization_target`; log `quota_reset_utc` in `credit_log.jsonl` and make the
floor check reset-aware.

### S17 — SERIOUS. The drop order destroys the most perishable surface first.

`§3.12`'s coded order is Tier C batter → Tier C pitcher → Tier B alternates →
Tier B team totals → Tier B F5 → thin Tier A; "Tier A last, always". Tier A is
3 credits flat and will never be the thing that breaks a budget. Batter props
are the largest surface with **zero history and no retroactive purchase path**
(owner decision 9), and they are dropped first. Under any sustained squeeze the
design systematically destroys the only data that expires.

**Fix.** Reorder against a stated `irrecoverability × marginal-information`
ranking, written down and versioned. Reserve a **non-droppable Tier C floor**
(e.g. full batter props on 2 games/night, rotated deterministically) so the
surface is never zero for a whole month — a thin continuous series is worth far
more than a dense series with a hole.

### S18 — SERIOUS. The fortnight is not deliverable, and the stated drop order drops the wrong packet second.

Fourteen packets totalling ~19 person-days of implementation plus Opus review,
in ten working days, while `§9.12` simultaneously declares that capture
completeness outranks everything for 60 days. The declared drop order is
W14 → W13 → W6. W6 (thirty park orientations, static geography) is permanently
recoverable. W13 (GUMBO readers) is the gate for the largest perishable surface
on the board — dropping it delays Tier C switch-on by exactly its own delay.

**Fix.** (1) Split W13: *forward* GUMBO capture (≈0.5d, do it in week 1, it is
free and it starts a clock) and the 2023-24 *backfill* (droppable — StatsAPI is
a permanent archive). (2) Re-order the drop list to W14 → W6 → W13-backfill.
(3) Accept that W8/W9/W11 is a three-week arc, not a one-week arc, and move the
G4 exit gate to end of week 4 — or shrink week 2 to W10 + W11 over the *existing*
assembler and defer the price-blind rewrite. Declaring an unreachable exit gate
is how gates start getting waived.

### S19 — SERIOUS. "Determinism is the compression algorithm" holds only until the first assembler bug fix, and the CI check as specified cannot detect the break.

`§4.7` stores the recipe, not the decision, and proves it with a CI job that
reproduces 1,000 sampled decisions byte-identically **at current HEAD**. That
proves today's code reproduces today's recipes. It says nothing about a
scorecard written three months and forty commits ago, and any legitimate fix to
an assembler silently invalidates every stored recipe that predates it — with no
error, because nothing re-checks old recipes.

**Fix.** A recipe records `engine_version` **and** a content hash of the
assembler source set. A nightly job samples recipes from *every* prior epoch and
marks any that no longer reproduce as `unreproducible_at_head`, with the count
published as a store-health metric. Retain **full decision detail** — not just
the recipe — for anything that ever entered a published verdict, a forward
selection, or a LOCK. Those are the rows that must survive a refactor, and there
are few enough of them that storage is not the constraint.

### S20 — SERIOUS. The ledger identity contains `engine_version`, so an engine bump either resets or inflates the 300-selection clock, and the design does not say which.

Identity is `(engine_version, system_id, game_pk, point_class, selection_id)`.
Bump `engine_version` and every past selection can be re-emitted as a new row.
`status()` counting rows against the 300-gate would then count them twice; a
counting rule that de-duplicates would silently keep credit for selections a
changed engine would no longer make.

**Fix.** Decide it now, in code: forward selections count once per
`(system_id, game_pk, point_class, selection_id)` regardless of
`engine_version`; and any `engine_version` bump that changes any historical
selection **restarts that system's forward clock**, declared and published as a
graveyard-style row at bump time. Add a test that bumps the version on a fixture
and asserts the count does not move.

### S21 — SERIOUS. The daily loop must be resumable, because mid-slate container restarts are observed behaviour, not a hypothetical.

Four restarts in an hour, platform-driven, is a recorded first-party
measurement. The loop as written (`morning → post_lineup → late → close → settle
→ account → review → factory.cycle`) has no stated resumption semantics, and a
restart between `late` and `close_pass` loses the close for that night
permanently.

**Fix.** Every loop stage is idempotent and resumable from its own ledger:
a stage records `stage_started`/`stage_completed` rows, re-entry skips completed
work by fingerprint, and `close_pass` in particular is retried on a bounded
schedule until the game is confirmed started. Add a chaos test that kills the
process mid-stage and asserts the day's artifacts are identical after resume.

### M5 — MINOR. `verify_chain()` over an append-only file in CI grows without bound, and W10's forward migration of 427 rows is itself a legitimate chain event. Segment the chain per month with a signed segment head; CI verifies the current month plus one random prior month.

### M6 — MINOR. Six CI-blocking guards are being added at once (stdlib-only, network block, import guard, path allowlist, AST objective, grep-for-model-call, hash chain). Every guard needs a documented legitimate-change path and a registry row when it changes, or the first person under deadline deletes one and nobody notices.

### M7 — MINOR. `Board.consensus(min_books=6)` and thin prop markets (7 books on a good day, 3 for F5 spreads) mean consensus is often undefined exactly where the board expansion is aimed. Make "consensus undefined" an explicit `Friction` state that the ranker must handle, not a `None` that a caller will eventually treat as zero.

### M8 — MINOR. `analyze()` is specified as pure with "no randomness", but the bootstrap machinery downstream is stochastic. Every bootstrap must take an explicit registered seed and record it on the artifact, or two runs of the same scorecard disagree and nobody can tell whether the disagreement is a bug.

---

## 4. Product surfaces, Tier A/B and the Ranker gate

### F14 — FATAL. The "Featured Bet" Tier A primitive is a selection surface, and selection is a recommendation regardless of what the segments say.

`design/linehound-v2/FEATURED_BET_REFERENCE_PRINCIPLES.md` and the V2 manifest
describe a Tier A primitive that gives **one wager per game a poster** — price
standing, `your_price_beats_consensus`, `price_improvement`, board depth,
thesis-support and counterargument counts. The manifest's own audit is careful
and correct about *language* (no rating, no probability, no edge, no picks). It
does not address the structural point: choosing one wager out of the board and
rendering it at poster size is the recommendation. Under the synthesized
architecture this gets worse, because `analyze()` ranks on edge net of friction
— the moment that ordering touches the Featured Bet's selection, the Ranker gate
has been walked around rather than through, while every text-level test stays
green.

**Fix, three parts.**
1. While `ENGINE2 is None`, the Featured Bet's selection rule must be a
   **published, non-analytic, non-opinion** rule — e.g. largest measured price
   dispersion across books, or greatest board depth — stated inline on the
   artifact in the same voice as My Bets' "NO RECORD · NO ROI · NO UNITS".
2. Add a **provenance test** symmetric to `test_ranker.py`: no field derived from
   `p_model`, `edge_bps`, `rating`, `Candidate` ordering or any system output may
   reach any product contract while the gate is closed. Test the data path, not
   the vocabulary — the current pins are all lexical.
3. `price_improvement` must never be the largest or first segment on the poster.
   `prices.py`'s mandatory non-EV label protects the *sentence*; visual
   prominence is the part users actually read, and it is currently unprotected.

### S22 — SERIOUS. `§9.13` correctly makes the gate a publication boundary rather than an engine boundary, and that creates a read path nothing seals.

Ratings will now be computed and written to `evidence/decisions/*` while the
gate is closed — which is required, because that is how the forward record
accumulates. But `evidence/` is already read by the dashboard and archive layers.
Nothing stops a product surface from reading a `rating` field that exists on
disk.

**Fix.** A second, symmetric path guard: `src/report/**`, `api/**` and `web/**`
may not read the gated field set (`rating`, `p_model`, `edge_bps`,
`stake_units`, `supporting_systems`) from any ledger while `ENGINE2 is None`.
Enforce with an import/field guard test in the style of the existing stdlib-only
and network-block CI guards, and make the guard's field list a single shared
constant so the gate and the guard cannot drift apart.

### S23 — SERIOUS. The gate readout is a good idea that becomes a picks surface the moment it shows *which* selections.

`§2` item 24 proposes shipping the unlock conditions live ("forward selections:
41 of 300"). Counts are honest and safe. Per-selection detail before a game
starts is a pick list with a progress bar on it.

**Fix.** The readout publishes **counts and gate conditions only**. Per-selection
detail publishes after settlement, on the losers-published cadence, never
pre-game. Pin it with a test.

---

## 5. Pushback on the owner's description

**V1. "Potentially thousands of competing systems" and "millions of decisions"
is a request for the wrong quantity, and granting it makes the product worse.**
The binding constraint is independent game-days, and — per F1 — the honest count
of those is far smaller than `§4.7` states. Ten thousand systems over six
features is a better overfitting machine, not a better analyst. Ask instead for
the thing that actually changes the answer: **40+ registered features across
bullpen availability, transactions, environment and market structure; 6+
gradeable market families; two honest decision-point classes.** Same ambition,
opposite direction. The synthesis reaches this in `§3.9` and `§9.4`; it should
be a stated amendment to the vision, not a paragraph inside an appendix.

**V2. "Backtest the analyzer with the EXACT SAME decision engine" is achievable
in code identity and not in information identity, and the amendment should be
made in public before any 2023-24 number is quoted.** Zero lineup-post
timestamps, 6-hour median board spacing, a probable-pitcher field that is
99.90% the actual starter. The honest name is a **degraded-information replay**,
and the real deliverable is a 2026-forward replay corpus with a grade ladder
attached. Owner decision 10 covers the market scope; it should also cover the
information scope, in the same public sentence.

**V3. "LOCKS = criteria to be researched" is the wrong sequencing.** Criteria
researched after seeing which candidates would have been LOCKs is threshold
shopping wearing a different hat. Ask for the inverse deliverable: the LOCK
criteria pre-registered **now** (`§3.7` is a good draft), a published
`N_LOCK` power analysis, and a deliberately LOCK-free period during which the
criteria are exercised and shown to produce zero. The credibility of the first
LOCK is entirely a function of how long the machine went without producing one.

**V4. The end-of-day self-review will become a CLV scoreboard unless CLV is
kept off it.** The owner's list includes "market moved toward/away". CLV settles
instantly and feels like feedback, so it will become the de facto daily score,
and a project scored daily on CLV optimizes execution rather than prediction —
the precise confusion `§3.4` and `prices.py`'s mandatory label exist to prevent.
Ask for CLV to be a **monthly** review dimension only, and for the daily review
to be the computed `thesis_outcome` and mechanism checks alone.

**V5. "A BET RATING that considers both outcome probability and price" is
currently unbuildable, and the honest first shipped rating is `None`.** No
calibrated probability exists; `§10` says one may never arrive. A rating shaped
like a rating with placeholder inputs is the single most likely way this project
breaks its own standing constraints, and it will be requested the first week the
product looks empty. Ask for explicit pre-agreement that the rating field ships
as `null` with the gate readout beside it, for as long as that is true.

**V6. Excluding execution edges is a real commercial cost and the owner has not
been asked to price it.** Stale-book and line-shopping edges are findable in
months; predictive edges may take seasons and may not exist (four families, zero
survivors; Phase 2B below the placebo ceiling; the market's close beating public
Elo by 0.008 log-loss at p=0.0003). The architecture is right to keep them
separate. The owner should be asked, explicitly and on the record, whether the
project's goal is *prediction* — in which case accept a multi-season timeline —
or *a product that makes money*, in which case a labelled execution ledger
(S16) is the fastest honest path and it looks nothing like the vision as
written.

**V7. "Parlays as their own scientific problem" should be amended to "parlays as
a capture problem now, and probably a negative result later."** `§9.7`'s
arithmetic is right and `§3.8`'s instrument is, per S8, likely unidentified.
Ask the owner to accept, in advance, that the most probable honest outcome of
the parlay program is a published "we could not identify the book's correlation
error with obtainable data" — and to fund the capture anyway, because capture
expires and research does not.

**V8. One thing in the vision should be strengthened rather than challenged.**
"The live season is precious: capture now everything needed to reconstruct
decision time later." `§9.12` is right that this outranks analysis for 60 days,
and F10 shows it is currently *not happening unattended at all*. The strongest
possible version of the owner's own instruction is: **no analysis work is
scheduled until the cadence SLO has been green for seven consecutive days.**
Every other item in this document is downstream of that one.

---

## 6. Verdict

The synthesis is the right architecture and its diagnosis is largely correct:
data-first as prerequisite, engine-first as spine, factory-first as immune
system. Nothing below changes that ordering.

But as written it would produce results that are not interpretable, for two
reasons that are independent of each other and both fatal. **F1**: the
independence unit is defined three ways in one document and every confidence
interval in the system depends on which one the implementer picks. **F2**: the
placebo ceiling is computed against a null that does not include the board-wide
argmax, so the owner's central ambition — search the entire board — mechanically
inflates the real maximum without inflating the ceiling, and board width starts
producing clears. Fix those two and the statistical machinery is sound. Leave
either and the factory becomes an expensive way to be confidently wrong.

Three further findings would invalidate the *program* rather than a number.
**F4**: as specified, the forward window is the factory's tuning set, which makes
"forward test" a slow in-sample search and hollows out G6. **F5**: model-authored
strategies are contaminated by pretraining knowledge of the discovery seasons,
and no control in the design touches it. **F10**: every grade-A/B claim about the
2026 corpus rests on a scheduler whose observed unattended success rate is zero,
which means the one asset the project is racing to acquire is not currently
being acquired.

And one finding would break the product's standing constraints without breaking
a single existing test. **F14**: the Featured Bet Tier A primitive selects one
wager per game and renders it at poster size. Every present pin is lexical; the
violation would be structural.

The ranked order of work, against this attack: fix the cadence and measure it
(F10) → seal the forward window into epochs (F4) → register the clustering spec
and re-derive the CIs (F1) → run placebos through the full argmax (F2) → bar
model-origin systems from the discovery seasons (F5) → add the truncation
differential and per-field provenance (F6) → make the objective boundary a type
(F9) → guard the product data path, not its vocabulary (F14). Everything else in
this document is worth doing and none of it is worth doing first.

The most likely way this project fails is not that it finds nothing. It is that
it finds something, and the something is F2 plus F5 plus a single bankroll curve
(F11), published together, in that order.

---

*Nothing in this document is evidence. Where it cites a number, the number is
either from `synthesis-judge.md`, one of the nine maps, or a file/line in this
repository, and is labelled as such.*
