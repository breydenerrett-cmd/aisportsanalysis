# Assumption autopsy — where a conclusion outran its evidence

Written 2026-09-17, read-only pass. Repo head at time of writing:
`0d3640b5` (2026-09-17 15:19:59 -0700; `git log -1`). Zero odds-API spend, no
file touched other than this one.

**Method.** For every claim: what the cited artifact actually measured, what
it did not, what sits one step away and untested, and what would have to be
true to falsify the broader (not the narrow) reading. I read
`ALTERNATIVE_HYPOTHESES.md` and `CONTRADICTION_LEDGER.md` first, as
instructed, and treat C1–C6 there as already established rather than
re-litigating them. Where a cited number traces to a `scratchpad/` path, I
say so and stop — `scratchpad/` has never existed in this repository
(`git log --all --diff-filter=A -- "scratchpad/*"` → empty, reconfirmed this
pass).

I autopsied **9 claims**: the 7 assigned, plus two I judged consequential
enough to add (A, B below) because they are the load-bearing generalisations
sitting *underneath* two of the assigned ones. Report at the end names which
is worst and which are genuinely closed.

---

## CLAIM 1 — The Phase 2A null

> "Empty L1; L2 about +0.0000412 log-loss/game worse, p≈0.914."

Artifact: `docs/EVOLAB_PHASE2A_BASELINE.md`, §9, run 2026-08-31, code
`src/evolab/baseline.py`, data `data/research/evolab/phase2a_baseline.json`,
commit `39d60033` ("Evolab Phase 2A: our features carry no linear information
beyond the close"). This is one of the best-documented artifacts in the
repo — its own §9.5 already states most of the scope limits below, in
writing, before anyone else has to.

**EVIDENCE ACTUALLY SUPPORTS:** For the **home-win target**, on **2,234
2024 games** (train 2023, 2,161 games), a **penalised logistic regression**
(L1 and L2, 12-point penalty grid, 5-fold date-grouped CV inside 2023 only)
fit on **18 point-in-time features** — nine base quantities crossed into
home/away contrast (`d_q`) and level (`m_q`) pairs, each accumulated up to
the **first day of the game's own month** (`matrix._cutoff_for`) — **added
no incremental information beyond the de-vigged closing moneyline
consensus**, evaluated by **log-loss** on the **full-game moneyline market**,
at a **fixed prediction time of market close**. L1 selected the empty model
outright; L2's surviving coefficients summed to 0.0278 in absolute value on
standardised columns. The market's own closing consensus needed no
recalibration intercept either (M1 − M0 ≈ −0.00005, p = 0.896).

**EVIDENCE DOES NOT ESTABLISH:**
- That **non-linear** combinations of the same 18 features carry nothing —
  §9.5 says this explicitly ("It does not say... a non-linear model would
  also find nothing"), and Phase 2B (Claim 2) tests exactly this, on the
  **same feature set**, not a different one (`docs/EVOLAB_DESIGN.md:456`:
  "the strategy space Phase 2B enumerates is built from **those same
  features**"). A null on the linear form and a null on a 3-signal
  threshold/k-of-n form are two different, if related, findings — but they
  share one representation of the underlying variables, not two.
- That **fresher** cutoffs (day-of, hour-of) carry nothing. §9.5 calls this
  "the single most obvious limitation and the most obvious follow-up," in
  its own words, and it is untested.
- That **other targets** (run line margin, totals, F5, any prop) carry
  nothing — only home win (moneyline) was scored.
- That **other seasons/regimes** would replicate — 2023→2024 only, and both
  are the explicitly non-evidential "exploratory sandbox" (§0), never the
  forward-sealed window.
- That a **fully independent feature set** (bullpen fatigue/H5, arsenal ×
  lineup interaction/H3, umpire/H9, wind vector/H10 — none of which appear
  among the 9 base quantities) would carry nothing. The 9 base quantities
  are lineup platoon/pitch-matchup/history and starter platoon/velocity/
  groundball/pitch-share — a specific slice of "team and pitcher state," not
  the whole space `ALTERNATIVE_HYPOTHESES.md` enumerates.

**UNTESTED NEIGHBOURING HYPOTHESES:** H3 (arsenal × lineup interaction,
explicitly a non-linear form over related-but-not-identical inputs), H5
(bullpen availability — a feature never in the 18), H7 (dynamic/latent
state vs. this static monthly-cutoff snapshot), H9/H10 (umpire, wind vector
— absent features), and the entire prop/F5 axis (H2, H4).

**WHAT WOULD FALSIFY THE BROADER CLAIM** ("our features/our data carry
nothing beyond the close"): any of — a non-linear model on the same 18
features clearing a placebo ceiling (this is precisely what Phase 2B was
built to check, and did — see Claim 2); a fresher-cutoff rebuild of the same
features showing calibrated signal; a genuinely new feature (bullpen usage,
umpire, arsenal interaction) clearing the same bar this document set for
itself. None of these has been run to a registered conclusion as of this
audit — Claim 2 addresses the closest one.

---

## CLAIM 2 — Evolab Phase 2B's `BELOW_PLACEBO_CEILING`, PBO 0.61

Artifact: `docs/EVOLAB_PHASE2B_RESULTS.md`, artifact file
`data/research/evolab/sweep-0014914df78666b9-REAL.json`, commits `67719f41`
(publication) and `eb58fc73` (scope footnote, added after the fact,
2026-09-02). This is explicitly called "the strongest null this project has
produced" in its own first paragraph, and the self-scrutiny in it (the SPA
disagreement, §2; the three specification bugs caught and fixed before
publication, §4) is real, not decorative.

**EVIDENCE ACTUALLY SUPPORTS:** Over **8,811 eligible strategies**, each a
genome of **≤3 signals** (weighted-sum or k-of-n) with **fixed-sign,
mechanism-tagged features** and a **3-value threshold ladder**, drawn from
**the same 18 features Phase 2A scored** (`EVOLAB_DESIGN.md:456`), evaluated
on **4,188 games** (2023–24) by a **market-movement fitness** (EARLY_BOARD →
LATE_BOARD, decision gap median 534 min, movement-endpoint gap median 84
min — **not the close**), the real maximum (0.004882) sat **below the
median** of three independent placebo-world families (P2 team-identity
permutation, P3 feature-date shift, P6 within-date movement-pair
permutation), corroborated by PBO = 0.6111 over 252 CSCV splits and by every
resampled-real-world (P4) maximum exceeding the real one. Scope: **full-game
h2h only** — `EVOLAB_PHASE2B_RESULTS.md`'s own 2026-09-02 footnote states the
genome schema names `h2h_1st_5_innings` but `src/evolab/feed.py` never
sourced an F5 price, so "no F5 price ever reached a Phase 2B genome."

**EVIDENCE DOES NOT ESTABLISH:**
- Anything about **F5, totals, or props** — the footnote says this in the
  document itself, and the registry confirms it independently: of 92 rows in
  `data/research/alpha_registry.jsonl`, **32 are `h2h`, 7 `h2h_1st_5_innings`,
  5 totals variants, and exactly 1 is a prop (`batter_hits`)** (counted
  directly this pass; matches `docs/audits/.../PROJECT_STATE.md`'s
  independent 92-row/42-verdict count). "Zero survivors" is a fact about a
  search that is **overwhelmingly moneyline/side-market**, not about markets
  in general.
- Anything about a **fitness function based on outcome-ROI rather than
  market movement** — the design doc is explicit that P1/P5 (which permute
  outcomes, not movement) are "structurally uninformative for the primary
  fitness" and are reclassified as valid nulls only for a *different*,
  outcome-based confirmation fitness, which this run did not report a
  headline verdict for.
- That the underlying **market-movement drift** finding (+0.00154, t=+6.57,
  §3) is nothing — the document itself declines to call it a null, an edge,
  or anything at all: "No claim is registered here." Treating Phase 2B as
  having "closed" the drift observation would be broader than what the
  document claims for itself.
- **Non-genome forms.** The genome caps signals at 3 and forbids nested
  conditions and sign flips (`EVOLAB_DESIGN.md` §3, rules 1–2) specifically
  to remove noise-fitting capacity. That is a defensible design choice, but
  it means the search space is narrower than "every rule-based strategy over
  these 18 features" — it is "every ≤3-signal, non-nested, fixed-sign rule."

**One correction to a common paraphrase, not a criticism:** "the registry
has 92 rows and zero survivors" is used in several places
(`src/report/ranker.py:33` docstring; `docs/ROADMAP.md`) as shorthand for
"the search space is exhausted." It is not fully exhausted — two rows carry
`result: "candidate"`, not `null`: `V6:lineup_surprise_direction:h2h`
(n=149, held for forward replication per `docs/LINEUP_DIRECTION_RESULT.md`,
discussed under Claim 4 below) and `V3:transaction_first_seen`. "Zero rows
carry `result: "survivor"`" (the literal string this project uses) is true
and precisely stated in `PROJECT_STATE.md`; "zero survivors" read as "nothing
outstanding" is not — two items are still open.

**UNTESTED NEIGHBOURING HYPOTHESES:** F5 genomes (schema exists, feed does
not — this is a wiring gap, not a tested-and-failed hypothesis), an
outcome-ROI-fitness sweep over the same genome space, any genome built from
features outside the Phase 2A 18 (bullpen usage, umpire, wind vector, arsenal
interaction).

**WHAT WOULD FALSIFY THE BROADER CLAIM** ("this feature/policy space has no
edge, full stop"): an F5-wired rerun of the identical harness clearing its
own placebo ceiling; an outcome-ROI-fitness sweep over the same genomes
clearing PBO and SPA jointly; a genome built from a feature outside the 18
clearing the ceiling. None of these disproves Phase 2B — they would each
extend a boundary Phase 2B already drew around itself.

---

## CLAIM 3 — "The model beats the base rate by only 0.0012 nats" (`docs/THE_CARD.md:57-60`)

**The number is contaminated, not merely narrow — this is different from
Claims 1/2, where the artifacts are clean and only their scope is
overclaimed.** `CONTRADICTION_LEDGER.md` C2 already establishes this; the
autopsy below is of both the number and the two-step conclusion drawn from
it, which the ledger flags but does not fully trace.

**EVIDENCE ACTUALLY SUPPORTS:** `docs/CARD_V2_DIAGNOSIS_2026-09-15.md:38-39`
names the exact contamination: "the walk-forward '0.0012 nats over 1,896
games' ... is an evaluation over **2026-04-15 to 2026-09-06**"
(`docs/THE_CARD.md:197-199`), and the card's calibration parameter `b` was
**refit nightly on that same window** by
`scripts/fit_card_calibration.py` from 2026-04-15 through 2026-09-15
(same doc, lines 23-32: three different `b` values committed 09-13/09-14
alone). Per the same diagnosis (line 51-54): "the seal's one evaluation
cannot confirm any rule built on this run model, its calibration or the prop
model: their parameters were chosen on the window and the model was
evaluated on it repeatedly." So the 0.0012 (and the sibling 0.00089 at
`THE_CARD.md:207`) is an **in-sample-adjacent number presented as an
out-of-sample walk-forward result.**

**THE TWO-STEP CONCLUSION, autopsied separately from the number:**
1. Number → "the model is weak" (directionally very likely still true: a
   contaminated fit would be expected to **flatter**, not deflate, the
   model's apparent edge over the base rate — `CONTRADICTION_LEDGER.md` C2
   says this too: "the contamination would, if anything, flatter the model").
2. "The model is weak" → "the model must never rank by its own
   disagreements" (`THE_CARD.md:60-66`, and re-cited as settled fact at
   `docs/EDGE_SEARCH_2026-09-10.md:449-452` and
   `docs/PREREG_RUN_DISPERSION.md:186-188`).

Step 2 is the **broader** claim, and it is conservative in direction
(if the model is even weaker than 0.0012 nats suggests, demoting on
disagreement is still correct) — but it is now doing load-bearing work in
at least two other documents while resting on a number its own sibling
document says cannot be quoted. **A conservative conclusion built on a
contaminated number is not automatically a safe conclusion** — it is only
safe if the *direction* of the contamination is known, and here it is
argued rather than measured (the flattering-direction claim is itself
"interpretation, not a measurement," `CARD_V2_DIAGNOSIS_2026-09-15.md:49`).

**EVIDENCE DOES NOT ESTABLISH:** The actual magnitude of the model's edge
(or lack of it) over the base rate on any clean window — that number does
not currently exist in the repo. It also does not establish that the model
would fail a **clean** re-run by more or less than 0.0012 nats; both C2 and
this autopsy can state the direction of the bias (flattering) with more
confidence than the magnitude.

**UNTESTED NEIGHBOURING HYPOTHESES:** A re-run of the identical walk-forward
procedure restricted to games strictly after 2026-09-15 (the freeze date),
once enough of them have accumulated, would be a clean version of exactly
this measurement and does not require new data collection — only time.

**WHAT WOULD FALSIFY THE BROADER CLAIM** ("the model may never be ranked by
disagreement"): a clean-window walk-forward showing the model within, say,
an order of magnitude of the market's own edge over the base rate — at which
point ranking by disagreement would need to be reconsidered on its own
merits, not on this contaminated number. Landing T11 (mark the evidence
section as produced under the leak, per the ledger's own "what happens now")
is necessary but does not by itself answer whether the *conclusion* survives
a clean measurement — only that the citation would stop being misleading.

---

## CLAIM 4 — 92 registry rows, 42 verdicts, ZERO survivors

Verified directly this pass (`data/research/alpha_registry.jsonl`, parsed,
not taken from any document's word): **92 rows total** — 47 `kind:
"hypothesis"`, 1 `sweep`, 2 `audit`, and 42 `kind: "verdict"`. Verdict
breakdown: **35 `null`, 2 `false_positive`, 2 `candidate`, 2 `audit`, 1
`withdrawn`**. This matches `PROJECT_STATE.md`'s independent count exactly
— two independent re-derivations now agree, which is itself worth noting as
a rare thing this project has actually done right (see "opposite error"
section).

**EVIDENCE ACTUALLY SUPPORTS:** Within the families actually registered —
overwhelmingly full-game moneyline and its F5 sibling, with a thin slice of
totals and one single prop test — **every registered, evaluated hypothesis
has failed its own pre-registered bar.** That is a real, hard-won fact about
this specific set of 42 tested ideas.

**EVIDENCE DOES NOT ESTABLISH:** "The market is efficient" or "there is no
edge in MLB," as a general statement. The **market breakdown of what was
actually searched**, counted directly from the file:

| market | rows |
|---|---|
| `h2h` | 32 |
| `h2h_1st_5_innings` | 7 |
| `totals_1st_5_innings` | 3 |
| `totals` | 2 |
| `batter_hits` | 1 |
| no market field / N/A (hypotheses not yet resolved, audits, the sweep) | 47 |

A **narrow search space with a clean null** and **an efficient market** are
observationally similar from inside this table and are not distinguished by
it. A single prop market (`batter_hits`, 1 row) is not "props were tested
and failed" — `docs/ROADMAP.md:962` states the prop *record* (23-15,
60.5% hit rate, −9.1% ROI) as the project's own worst live result, which is
a **pricing/execution** finding on a live ledger, not a registry hypothesis
verdict at all, and the two should not be merged in prose even though they
point the same direction.

**Also:** "zero survivors" needs the qualifier from Claim 2 restated here —
two rows are `candidate`, not `null`. One,
`V6:lineup_surprise_direction:h2h` (`docs/LINEUP_DIRECTION_RESULT.md`), is a
mechanism-bearing, five-reviewer-attacked, still-open forward test (n=149,
hit rate 0.584, clears its own pre-registered α=0.05 but not the
registry-implied family-wise α=0.05/41; explicitly "NOT PROMOTED," held for
forward replication with a floor of 150 postings). Citing "92 rows, zero
survivors" without noting this one open item overstates how settled the
registry actually is.

**UNTESTED NEIGHBOURING HYPOTHESES:** Every market/prop combination outside
h2h and its thin F5/totals slice: alternate lines (H4), pitcher strikeout/
outs/walks props at any volume (H2 — one prop hypothesis exists in the
entire registry), team totals, run-line-specific strategies not reducible to
a moneyline signal, anything player-level beyond the single `batter_hits`
row.

**WHAT WOULD FALSIFY THE BROADER CLAIM** ("the search space was narrow, not
the market efficient"): registering and running a comparably sized battery
of prop/F5/totals hypotheses (the owner's own 2026-09-17 directive,
`ROADMAP.md:920-927`, points exactly here) and observing the same zero-null
pattern. If props also go to zero at a similar rate, "narrow search space"
stops being a live alternative to "efficient market" for this project's
purposes — but that battery has not been run yet.

---

## CLAIM 5 — SR1 home-underdog's death

Artifact: `docs/SR1_RESULT_2026-09-16.md`, verified independently by a
second implementation (§8), registry rows `SR:home_underdog_price_band:h2h`
(+ amendment). This is, unusually for this repo, a document that has
**already autopsied itself** — §9 is titled "read this before reading
anything above as 'no effect,'" and its UNDERPOWERED_NULL framing is more
careful than most academic write-ups of a similar result.

**EVIDENCE ACTUALLY SUPPORTS:** For exactly the registered rule — home team
priced **+100 to +150** (Band A) or **+151 to +250** (Band B) at a
**360-minute-before-first-pitch, ≥6-book, proportionally de-vigged**
snapshot, backing the **moneyline**, on **2023 (screen) and 2024
(replication)** — Band A failed its own 2023 sign gate (−3.51pp) and Band B
failed 2024 replication after a promising 2023 read (+7.77pp → −2.14pp, a
sign flip). Both are correctly KILLED **on their own registered terms**:
freeze-hash verified, join-loss under the kill line, independently
reproduced to the published decimal.

**EVIDENCE DOES NOT ESTABLISH — and the document says so itself, at
length:** §9 states the realised sample can only rule out effects **above
about 6pp (Band A) or 11-12pp (Band B)** at 80% power, against a registered
floor of **+1pp** — detecting a real 1pp effect would need "roughly 19,000
to 54,000 selections per season," two orders of magnitude more than the
528/138/116 actually graded. The document's own words: "A null here is
therefore an UNDERPOWERED_NULL and is **never** a statement that no effect
exists."

**Where this gets generalised beyond what the document licenses:**
`docs/ROADMAP.md:929-933` — "He is right, and the SR1 home-underdog family
is the exhibit. It was one number... with no mechanism behind it. It died
on a sign flip between 2023 and 2024, **which is what a strategy with no
mechanism does**. Testing more strategies of that shape faster produces
nothing except more confident noise." This is doing real, useful
methodological work (mechanism-first is a good rule), but the causal claim
embedded in it — that the sign flip is diagnostic of "no mechanism" — is not
supported by SR1's own power analysis. **A real +1-3pp mechanism-bearing
effect at this exact sample size (116-528) would also be expected to
sign-flip across two seasons purely from sampling noise** — §9's own MDE
bars say so. The sign flip is consistent with "no effect," "an effect too
small for this sample to see," and "an effect that exists but moves with
something SR1 didn't measure" (e.g., the 2023→2024 book-count contraction
documented in the same section, 16.4 → 11.2 books). ROADMAP's reading picks
the first of three explanations SR1's own document says it cannot
distinguish.

**UNTESTED NEIGHBOURING HYPOTHESES:** A mechanism-bearing version of the
same price-band idea (e.g., gated on a stated reason a home dog might be
undervalued — bullpen availability, a specific park effect) at the same
sample size would face the identical power problem and would be just as
likely to sign-flip on a real small effect. SR1's death says nothing about
whether *that* strategy would also flip for the same reason or for a
different one.

**WHAT WOULD FALSIFY THE BROADER CLAIM** ("strategies of this shape produce
nothing but noise"): a mechanism-stated, adequately powered (per SR1's own
MDE table, tens of thousands of selections, i.e., several seasons or a
wider net) price-band test producing a stable-sign, floor-clearing effect.
The document itself points at exactly this as the honest next step (§10,
"cite the power finding when designing any future price-band family").

---

## CLAIM 6 — "CLV is the pass/fail metric, ROI secondary" (`docs/VALIDATION_CRITERIA.md:30`)

**EVIDENCE ACTUALLY SUPPORTS:** The document states a **reason**, not a
derivation: "ROI needs on the order of a thousand bets before it separates a
real edge from variance. CLV... converges roughly ten times faster"
(`VALIDATION_CRITERIA.md:32-34`). This is a defensible piece of betting-
industry folk statistics (CLV is a lower-variance, faster-converging proxy
because it doesn't require the bet to resolve), and it is stated and
committed **before any model existed, any backtest ran, or any pick was
graded** (`VALIDATION_CRITERIA.md:1-24`), which is the right procedural
discipline regardless of whether the number is derived.

**EVIDENCE DOES NOT ESTABLISH:** That "ten times faster" is a computed
figure. No effect size, variance estimate, or power formula appears anywhere
in this document — I searched for "power," "MDE," "sample size" within it
and found nothing resembling a calculation; the 300-pick floor two sections
down (line 46) is likewise asserted, not derived (see Claim 7). **This is a
chosen threshold, dressed in the language of a derived one** — "converges
roughly ten times faster" is a plausible order-of-magnitude claim, not a
citation or a computation reproducible from this file.

The document also embeds an unstated assumption **CLAIM 6 depends on
entirely**: that the project can reliably **obtain the closing price** to
compare against. Nothing in `VALIDATION_CRITERIA.md` addresses execution
risk — whether a recorded "pick" price is actually the price a bet would
have cleared at, whether the closing snapshot used for CLV is itself
point-in-time-correct, or what happens if the book used for the pick differs
from the book(s) used to compute the close. `ALTERNATIVE_HYPOTHESES.md`'s H6
(cross-book dispersion / best-price capture) and H11 (finest capture gap
177 minutes) both bear directly on this and are not reconciled with
`VALIDATION_CRITERIA.md`'s implicit assumption of a clean, obtainable close.

**UNTESTED NEIGHBOURING HYPOTHESES:** Whether the CLV metric as actually
computed in this codebase (`src/pipeline/snapshots.py:844`,
per `CONTRADICTION_LEDGER.md` C5) uses a close that is itself
capture-cadence-limited (177-minute finest gap per H11) in a way that could
bias CLV in either direction relative to the "true" close a faster capture
cadence would see.

**WHAT WOULD FALSIFY THE BROADER CLAIM** ("CLV should lead"): if a
comparison of realised CLV against realised ROI on the live ledger (once it
exists in adequate volume) showed CLV and ROI **disagreeing in sign** over a
sustained period — which `VALIDATION_CRITERIA.md:56-58` itself flags as the
one scenario that would force a re-examination ("a strongly positive CLV
alongside a deeply negative ROI means something is wrong with execution or
grading"). That check is written into the document; it has not yet had
enough graded volume to run.

---

## CLAIM 7 — The 300-pick floor

**Attribution check first, per the task's explicit instruction.** The "≥300
forward selections... ≥60 ledger days" pairing in `ROADMAP.md`-adjacent
prose comes from **one gate**, `docs/ARCHITECTURE_BETTING_ENGINE.md:326`:

> **G6 Forward** | ≥300 forward selections with book, price, rating,
> counterarguments and settled close; ≥60 ledger days; class A/B;
> out-of-sample only; within sealed epochs.

`docs/VALIDATION_CRITERIA.md` has its **own, separate** 300 figure at line
46 ("Minimum sample | 300 graded picks | < 300 | —") and line 48
("Below 300 picks, no verdict is drawn regardless of what the numbers say"),
with **no 60-day component anywhere in that file** — I grepped the whole
document for "60" in a days/ledger context and found none. These are **two
different 300s, in two different documents, for two different purposes**
(a CLV/ROI verdict threshold vs. a LOCK-promotion forward-evidence gate),
and conflating them — treating "the 300-pick floor" as one number with one
derivation shared across both documents — would itself be exactly the kind
of scope-widening this audit is hunting for. They are not shown to be the
same 300 by any document that mentions both.

**EVIDENCE ACTUALLY SUPPORTS:** Both 300s are **picked**, not derived from a
power calculation, as far as any committed document shows. `ARCHITECTURE_
BETTING_ENGINE.md:325` (G5, the sentence immediately above G6) explicitly
ties **its own** world-count to "power analysis" for the *ceiling* mechanism
— a genuinely different, computed quantity — and `docs/planning/attack.md:91`
and `synthesis-judge.md:333,1209` all describe **`N_LOCK`**, a *different*
named quantity from LOCK's gate, as coming from "a power analysis" that
several planning docs promise but none of the documents I read actually
shows worked out with an effect size and alpha/beta. `docs/SGP_PARLAY_
CAPTURE.md:80` says outright, about a similar figure elsewhere in the
project: "a planning-order-of-magnitude statement, not a computed power
analysis" — which is an honest admission this project has made about
itself before, just not attached to either of the two 300s here.

**EVIDENCE DOES NOT ESTABLISH:** That 300 (either one) is the number a
formal power calculation would produce for CLV's or ROI's actual observed
variance in this project's own data. `VALIDATION_CRITERIA.md`'s own
reasoning ("CLV converges roughly ten times faster" than ROI's "on the order
of a thousand bets") would, taken literally, suggest **~100**, not 300 — 300
looks like a rounder, more conservative number chosen *near* that
back-of-envelope range rather than computed from it. That is not
necessarily wrong, but it is not what "derived from a power calculation"
would mean.

**UNTESTED NEIGHBOURING HYPOTHESES:** An actual power calculation, using the
realised variance of CLV in the live ledger once it exists, would very
plausibly produce a different number for either gate — possibly lower for
CLV (since CLV's cross-sectional variance may be smaller than assumed) or
higher for the LOCK/G6 gate (given LOCK's much stricter compound conditions:
ECE bounds, two-system agreement, worst-book survival, 25% shrink toward
market).

**WHAT WOULD FALSIFY THE BROADER CLAIM** ("300 is a defensible statistical
floor"): computing the actual minimum detectable effect at n=300 given the
CLV metric's realised standard deviation in this project's own ledger, and
finding it materially wider than the "≥55% share / ≥+1.5% mean CLV" pass
bar the same document sets (`VALIDATION_CRITERIA.md:44`) — i.e., if 300
picks cannot actually distinguish "≥55%" from "50%" at reasonable power
given the true bet-level variance, the floor is under-powered for its own
stated pass criterion, the same failure mode SR1 (Claim 5) already
demonstrated at a different sample size.

---

## CLAIM A (added) — "The suite's own reliability was falsified... filed, not fixed" generalised to "the test suite is unreliable"

Source: `PROJECT_STATE.md` TESTED section, citing `docs/ROADMAP.md` Stage 18
H7 / commit `e6166a1c`: pass/fail counts on the same tree swung 18–43 across
runs, root-caused to (a) tests reading stores a live capture job mutates
mid-run and (b) load-sensitive assertions.

**EVIDENCE ACTUALLY SUPPORTS:** At least some fraction of the 381-file suite
is flaky under concurrent capture-job load, and at least one incident
(three `live_window --settle` assertions) was misread as "known noise" while
red for hours.

**EVIDENCE DOES NOT ESTABLISH:** That any specific *other* red/green result
in this project's history is suspect — H7 identifies a mechanism and one
confirmed instance, not a census of which tests are affected. Treating "the
suite is unreliable" as a blanket discount on every past green result would
be broader than H7 itself claims; `PROJECT_STATE.md` is careful about this
("H7 remains open... whether the same reflex has silently absorbed other
real failures since is not something this audit checked") and this autopsy
should not blur that carefulness by citing H7 more broadly than its author
did.

**WHAT WOULD FALSIFY THE BROADER CLAIM:** Running the suite serially,
isolated from any live capture job, several times, and finding the same
18-43 swing — that would show the flakiness is not solely load/concurrency
-caused and would widen, not narrow, what H7 covers. This audit did not run
the suite (read-only mandate; the task instructions direct fixes to
`scripts/test_fast.sh` / `scripts/test_parallel.py`, not this document).

---

## CLAIM B (added) — "No independent model probability exists" vs. a model that reads no price

This is `CONTRADICTION_LEDGER.md` C3, restated here because it is exactly
the shape of inference jump this task is hunting (a code comment's
blanket claim vs. a specific traced code path), and because the ledger
flags it as unresolved rather than autopsying which side is overgeneralised.

**EVIDENCE ACTUALLY SUPPORTS:** `src/analysis/strength.py`'s `run_means()`
and `market_probabilities()`, as traced in the ledger, build a probability
from team runs scored/allowed, shrunk toward league rate — no price is read
at that stage. `src/ledger/records.py:92-122` gates non-null `edge_bps`
strictly to `model_derived` provenance.

**EVIDENCE DOES NOT ESTABLISH:** That `src/analysis/families.py:22`'s flat
assertion ("No independent model probability exists anywhere in this
project") is simply wrong everywhere it might apply — it may be scoped to a
different subsystem (the ledger's own framing: "either families.py's flat
assertion is stale/scoped-to-the-engine-track... or the card's probability
is not what it appears"). A blanket comment and a specific trace can both be
locally correct about different parts of the codebase; neither this audit
nor the ledger has traced `families.py`'s own call sites to know which.

**WHAT WOULD FALSIFY EITHER READING:** Tracing every caller of
`families.py`'s assertion to see whether any of them route through
`strength.py`'s price-free path — a half-day, mechanical trace the ledger
already recommends and this audit did not have scope to duplicate.

---

## The opposite error — where flexible search could manufacture a discovery, and whether the caution around it was earned

The task asks this explicitly: a sufficiently flexible model or search
manufactures fake discoveries, and conservatism must be checked for being
**earned** rather than merely reflexive.

**One clear, documented case of the project catching itself doing the
aggressive thing, and correcting it — this is earned, not merely cautious:**
`docs/LINEUP_DIRECTION_RESULT.md` (V6). The pre-registration used α=0.05 "on
the grounds that this is one primary hypothesis." Adversarial review pointed
out the registry already held 40 prior null hypotheses against the same
market, and re-scored the same result at the registry's implied family-wise
α (0.05/41), which moved the verdict from CONFIRMED to UNDETERMINED — the
interval widened from [0.535, 0.636] to [0.500, 0.664], crossing 0.500 in
practice. **This is exactly the failure mode the "opposite error" warns
about — a flexible-enough search finds a first "yes" after forty "no"s and
the naive threshold treats it as clean — and this project's own machinery
caught it before publication**, per the document's own framing: "The first
'yes' after forty 'no's is exactly the result that needs the harsher bar,
not the kinder one." Worth citing by name as an earned instance, not a
hypothetical one.

**Evolab Phase 2B's instrument disagreement (§2 of that document) is the
same kind of self-correction at larger scale:** SPA rejected its null while
the placebo ceiling did not, and rather than quoting whichever number was
more flattering, the sweep driver's own cross-check refused to publish
either until the disagreement was diagnosed (board-wide drift, not a
strategy-specific signal). That the diagnosis took real work and was
published in full, including the fact that the resolution favoured the
**less exciting** reading, is evidence this conservatism is earned rather
than performed.

**Where the caution reads as merely asserted rather than earned:** the two
300-pick floors (Claim 7) and the "CLV converges ten times faster" heuristic
(Claim 6). Neither is wrong, and both are stated as pre-registered
commitments before any result existed — which is the right procedural
discipline — but neither carries a worked derivation the way the Evolab
placebo-ceiling world counts do ("world count from power analysis,"
`ARCHITECTURE_BETTING_ENGINE.md:325`, actually cross-referenced to real
computed replicate counts in `EVOLAB_PHASE2B_RESULTS.md`). A reader cannot
currently distinguish "we computed this" from "this felt like the right
order of magnitude" for either 300.

**Not found in this pass, and worth stating plainly rather than implying:**
no case where the project's flexible machinery (Evolab's genome search, the
alpha registry's hypothesis intake) actually **published** an
insufficiently-scrutinised positive as if it were real. Both near-misses
found (V6, the SPA/ceiling disagreement) were caught before publication.
That is a genuinely good sign about the machinery, not a gap in this audit.

---

## What this autopsy judges genuinely closed

Not everything is open, and saying so is part of the brief.

1. **SR1, as literally registered** (Band A [100,150] and Band B [151,250],
   2023 screen / 2024 replication, moneyline, this exact rule) — dead, on
   its own terms, verified independently. Reopening it would require a new
   registration, not a re-read of this data (the document says so itself
   and this audit agrees).
2. **Phase 2A, as literally specified** (18 named features, monthly cutoff,
   linear-plus-offset logistic regression, home win, 2023-train/2024-eval,
   full-game moneyline) — closed. The arithmetic reproduces
   `BENCHMARK_ELO.md`'s numbers to the last digit through an independent
   join, the leakage checklist is machine-computed and stored, and the
   result is symmetric (L1 finds nothing, L2 finds nothing, the constant
   recalibration finds nothing).
3. **Evolab Phase 2B, as literally specified** (≤3-signal genomes over the
   same 18 features, movement fitness, full-game h2h, 2023-24) — closed,
   and unusually well corroborated (ceiling + PBO + P4 dispersion all point
   the same way, and the one instrument that disagreed, SPA, was diagnosed
   rather than cherry-picked).
4. **The STRONG/LEAN/SPLIT card labels** — correctly and permanently
   retired on a named owner complaint, not a statistical finding; nothing
   to reopen.
5. **V1's forward-graded record through 2026-09-15** — correctly
   unusable for any verdict, per the project's own "changing the model
   restarts the sample" rule, now that the nightly-refit contamination is
   understood. Not a null result to defend; a known-bad sample to discard
   and restart counting from the freeze date.

What is **not** closed, restated for contrast: whether MLB carries any
tradeable edge anywhere outside full-game moneyline (props, F5, alternates,
timing/microstructure) — the registry has barely searched there (1 prop row
out of 92), and the owner's own 2026-09-17 directive
(`ROADMAP.md:920-927`) is explicitly a request to go do that search, not a
claim it has already failed.
