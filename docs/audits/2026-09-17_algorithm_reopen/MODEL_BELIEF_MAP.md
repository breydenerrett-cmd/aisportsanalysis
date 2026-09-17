# Model belief map — what this system currently believes, and what it rests on

Written 2026-09-17 as part of the algorithm-reopen audit. Read-only research:
no code, config, or other doc was touched to produce this file.

**How to read this document.** For every consequential belief this system
currently acts on, twelve fields are recorded. A blank or thin field is
itself a finding: it means a conviction is being carried whose basis nobody
wrote down. The last field, **CURRENTLY TREATED AS**, is the point of the
whole exercise — not "is this true" but "how confidently is this held
relative to what it rests on." Where two independent reads of the same
artifact (two research passes run in parallel for this document, or my own
direct read against one of theirs) characterized something differently, both
readings are recorded rather than smoothed into one. Numbers are quoted
exactly as the source artifact states them — never rounded, never
re-derived — even where two artifacts round the same underlying number
differently; both spellings are kept.

**Method.** Five parallel read-only research passes plus my own direct
reading of ~35 primary documents and the relevant source files, cross-checked
against `git log`/`git blame` for commit shas. All five passes returned and
are reflected below; the fifth (covering VALIDATION_CRITERIA derivation,
line movement, favourite/underdog, market timing, F5, props, nonlinear
interactions, selection effects, and calibration) returned after this
document's first draft and after I had independently covered most of the
same territory myself — its findings were merged into the relevant sections
rather than appended separately, and every place its reading differed from
my own first-pass reading (a factual correction on the "60 ledger dates"
figure, a differing F5-H1 effect-size number) is recorded explicitly at
that section rather than silently resolved.

**Repo state.** `C:\Users\KC\Desktop\aisportsanalysis`, branch
`claude/sports-betting-analysis-review-g1o0co`. Working tree carries
uncommitted changes to `api/card.py`, `data/historical/handedness.json`,
`src/analysis/daily_card.py`, `src/report/card.py`, `.claude/launch.json` at
the time of this read; commit shas below refer to the committed history
unless stated otherwise.

---

## Part 0 — Summary

Beliefs mapped below: **34**, of which:

- **6 treated as FACT that rest substantially on a DESIGN CONVENTION or an
  unfitted judgment call** (§B7 edge threshold, §B17 home-field constant,
  §B18 park-factor inclusion, §B12 recent-form window, §C6 the 300-pick/60-date
  floor, §A5 CLV-as-primary-metric's own justification).
- **1 belief the codebase's own internal audit shows is currently violated in
  practice, not just under-justified** (§C9 selection effects / FDR
  multiplicity across sweeps and time — the family-wise bar is cited, not
  enforced, and the repo's own red-team review computed the resulting
  expected false-survivor rate).
- **1 belief where a governance rule (the sealed-window seal) was broken by
  the system itself and is now downgraded across a chain of dependent
  results** (§C10, the V1 calibration leak, item 4 of the specific
  historical items below).
- **1 belief that looks superficially like a hidden assumption but on close
  reading is one of the better-replicated constants in the codebase** (§B22
  `DISPERSION`, independently confirmed on two separate seasons to within
  0.13 standard errors — flagged here specifically because it is the
  opposite of what a skim would suggest, and because the *number currently
  in production* was nonetheless fit partly on sealed-window data).
- The single belief I judge **least supported relative to how confidently it
  is held**: the market-level assumption baked into `daily_card.py`'s
  original design — that ranking by market confidence and using the model
  only as a pass/fail agreement check is the safe, conservative choice. The
  card's own docstring reasoning is sound in isolation, but the system
  shipped it as the **live product** for its first published week, on money
  and reputation, before anyone measured what it produces (favourites,
  half beyond the owner's own stated price limit) — see §C3 and the Price
  Band Evidence section below. It was treated as an engineering safety
  decision when it was actually an unmeasured product decision.

---

## Part I — The five specific historical items, precisely

### Item 1 — The Phase 2A "no linear incremental information" result

**Source:** `docs/EVOLAB_PHASE2A_BASELINE.md` (447 lines), commit
`39d600331848b7a772295ee1b5688a4029c9bb4a`, 2026-08-31, "Evolab Phase 2A: our
features carry no linear information beyond the close." Code:
`src/evolab/baseline.py`. Artifact:
`data/research/evolab/phase2a_baseline.json`.

Exactly what was tested, with nothing generalized beyond it:

| Field | Value |
|---|---|
| Target | Home team win, binary (`y = home_won`), from `data/historical/mlb_results.csv` (`EVOLAB_PHASE2A_BASELINE.md:30`) |
| Model family | Penalized logistic regression on the **residual relative to the market**: `eta = logit(p_mkt) + b0 + x·beta`, with `logit(p_mkt)` a fixed offset, coefficient pinned at 1, never fitted, never penalized (`:35-48`). Three nested models (M0 = market alone, M1 = market + free intercept, M2 = market + intercept + penalized features), two norms for M2 (L1 lasso, L2 ridge) |
| Feature representation | 18 standardized columns from 9 base quantities (lineup platoon share, lineup-vs-primary-pitch, top-minus-bottom, lineup-vs-starter-history wOBA/PA, starter platoon gap, starter velocity gap, starter groundball share, primary pitch share), each split into a home-minus-away contrast and a game-level mean, cut off at the first day of the game's own month (`:61-100`) |
| Data period | Train 2023 (2,161 eligible games, 182 dates); evaluate 2024 (2,234 eligible games, 183 dates) — **both inside the explicitly non-evidential 2023–24 sandbox**, not a held-out test (`:15-21, 180-198, 267-268`) |
| Market | De-vigged **closing** consensus moneyline, proportional de-vig, ≥6 books (`:30-34, 188-189`) |
| Time of prediction | The **close** — not opening, not a fixed pre-game snapshot |
| Statistical test | `discovery.clustered_two_sided_p`, a date-clustered two-sided z-test on the mean per-game log-loss differential (`:210`; code `src/model/discovery.py:90-124`) |

**The exact numbers, quoted verbatim (`:320`):**

| comparison | mean diff / game | clustered p |
|---|---|---|
| **M2 (L2) − M0 — primary** | **+0.0000412** | **0.914** |
| M2 (L1) − M0 | −0.0000506 | 0.896 |
| M1 − M0 | −0.0000506 | 0.896 |

L1's cross-validated penalty (λ=100) drove **all 18 coefficients to exactly
zero** — the empty L1 model (`:277-284`).

**Doc-vs-code discrepancy found.** The doc's §4 (lines 175-176) describes the
L1 optimizer as "proximal gradient (ISTA) with backtracking and
soft-thresholding." The actual code (`src/evolab/baseline.py:253-321`,
`fit_l1`) implements coordinate descent on the IRLS quadratic
weighted-least-squares approximation ("the glmnet construction," per its own
docstring) — a different, also-legitimate algorithm than the one described in
prose. No evidence this affected the reported numbers (M0 independently
reproduces `docs/BENCHMARK_ELO.md`'s published numbers "to the last digit,"
`:308-312`; the leakage/contamination checklist in §9.4 is machine-verified).
Recorded because the task rules require both readings when prose and code
disagree, not because it changes the result.

**What this result is and is not.** The document's own §9.5 is explicit and
should be quoted rather than paraphrased: *"It says: within this feature set,
this functional form and this sample, there is no incremental predictive
information beyond the closing price... It does not say the features are
useless for every purpose, that a non-linear model would also find nothing
... or that no MLB feature set can beat the close."* It also names the most
obvious follow-up itself: every feature here is "up to a month stale by
construction." **This is one target, one model family (linear, residual to
the market), one feature representation, one market (moneyline), one
prediction time (close), on a non-evidential sandbox period.** It has been
cited elsewhere in the repo (`EVOLAB_PHASE2B_RESULTS.md:312-317`,
`PREREG_CALIBRATED_PROBABILITY.md:173-179`) without softening this scope, and
`docs/audits/2026-09-17_algorithm_reopen/ALTERNATIVE_HYPOTHESES.md` was
written specifically to enumerate different targets/representations/markets
this result says nothing about (see §C12–C13 below).

**A footnote on the "25 pre-registered specs" the doc cites as part of its
prior.** §7 of the Phase 2A doc grounds its pre-registered expectation partly
on "25 pre-registered specs across four families with zero survivors."
`docs/RESEARCH_CATALOGUE.md`'s own "Counting the families" section (lines
313-333) documents that this denominator is **inconsistently reported across
the repo's own documents** — 21, 25, 27, or 35 depending on which rollup is
read, with an acknowledged double-count of V2's five hypotheses in one
rollup. This does not change any individual family's FDR result (each ran
against its own frozen denominator), but the round "25" repeated in Phase
2A's prior should not be read as more precise than the repo's own audit says
it is.

### Item 2 — The probable-starter historical replay issue

**Source:** `docs/AUDIT_PROBABLE_PITCHER_PIT.md`, commit
`0039f158c2cd773b8e506b3dd2d897fd237d78e2`, 2026-08-31.

**The mechanism, quoted:** *"`away_probable_id` / `home_probable_id` come
from MLB's `probablePitcher` hydrate (`src/providers/mlb.py:163`)... fetched
retroactively for games that had already finished. If that field reflects who
actually started rather than who was announced, every historical feature
conditioned on 'the opposing starter' carries knowledge no pre-game system
could have."* `src/pipeline/history.py:49` writes the field straight into the
historical store with no reconciliation step.

**The verdict, quoted:** *"Conclusion: the stored value is the terminal,
pre-first-pitch state of the starter announcement. Every scratch that
occurred between the announcement and first pitch has been silently
absorbed."* Two independent measurement methods (Statcast first-pitch
derivation; a separate MLB gameLog `games_started` check) return **identical**
disagreement rates and the identical 9-case list: 0.1029% (2023, 5/4,859
sides), 0.0824% (2024, 4/4,852 sides) — 12× to 41× cleaner than the doc's own
cited scratch-rate estimate (0.3–1/day league-wide, from
`docs/RESEARCH_V3_TIMING.md:143`) would predict for an honest pre-game
snapshot. None of the nine disagreements is an actual scratch — all are
openers, bulk-pitcher listings, or one suspended-game resumption.

**Quantified exposure (§6, exact table):**

| | count | share of the 4,819-game replay universe |
|---|---|---|
| starter-sides in the universe | 9,638 | — |
| scratched sides at 0.3/day | ~110 | **2.3% of games** |
| scratched sides at 1/day | ~367 | **7.6% of games** |
| sides where the store visibly disagrees with the actual starter | 9 | 0.17% of games |
| sides where the stored probable never threw a pitch | 1 | 0.02% of games |

The underlying scratch-rate estimate (0.3–1/day) that sizes this exposure is
itself **not measured in this repo** — `docs/DEBRIEF.md:475` records that the
forward watcher has reported zero `starter_scratch` events to date, so the
honest statement, in the audit's own words, is *"the leak is real
conditional on MLB scratches being commoner than 1-in-1000 starts."*

**Direction of the bias, and why it does not overturn any conclusion,
quoted:** *"The leak's sign is favourable to the features... any measured
effect is an upper bound on the honest one."* All four families reading
starter-identity-gated features (V1, V4, V5) produced **zero survivors**
independent of this leak, so removing a small, favorably-signed advantage
cannot manufacture a survivor from a null whose confidence interval already
spans zero. The audit itself lists four things this does **not** license
saying, verbatim: *"1. It is not why the families failed... 2. 'Cannot
manufacture a survivor' is a judgement, not a proof... It was not tested by
re-running any family... 3. V2 is untouched... 4. This does not rehabilitate
anything. Nothing in `docs/RESULTS_2023_24.md` or
`docs/VALIDATION_PACKAGE_1.md` becomes citable; those are invalidated by the
price-join bug (catalogue T4), which is a separate and far larger defect than
this one."*

**What remains safe vs. requires qualification.** Safe: the V2 family (de-vig
methodology, price autocorrelation — never reads a starter id); the forward
briefing path (`src/pipeline/briefing.py`/`src/cli.py:526` supply the field
from a live fetch, so it is genuinely point-in-time going forward); the
qualitative "no published null is overturned" conclusion. Requires
qualification: any claim that the V1/V4/V5 nulls are *proof* the underlying
features don't matter (only that no reversal is plausible — not tested);
any future Evolution Lab candidate that uses historical starter identity as
point-in-time, which must now be served under a named, versioned parameter
rather than assumed clean.

**What was done about it since.** `src/evolab/replay.py` implements a named
engine parameter (`STARTER_IDENTITY`, value
`"actual_at_first_pitch"`, carrying the measured agreement rates) and raises
`NotPointInTimeError` if a caller asks to treat it as point-in-time
(`src/evolab/replay.py:274-289, 355-374`). `EVOLAB_PHASE2B_RESULTS.md`
republishes the exposure note on every sweep artifact. **Not implemented**:
recommendation #3 of the audit — a per-candidate scratch-perturbation
sensitivity run — has no code or doc reference anywhere in `src/` or `docs/`;
moot only because nothing has survived to require it yet, but the mitigation
itself remains unbuilt.

### Item 3 — `docs/VALIDATION_CRITERIA.md`: the 300-pick / 60-date floor, CLV primary

**Source:** `docs/VALIDATION_CRITERIA.md`, commit
`eed2eb0c57619abca2e0ec00213b3ec12e7dedb9`, 2026-08-27 — **written before any
model existed, any backtest had run, or any pick had been graded** (its own
header states this and the file's own "Status at time of writing" table
confirms: probability model "does not exist," graded picks "zero,"
backtest "never run").

**CLV-primary, quoted exactly (`:28-30`):** *"CLV is the pass/fail metric.
ROI is secondary."* Reasoning given (`:32-35`), quoted: *"ROI needs on the
order of a thousand bets before it separates a real edge from variance. CLV
— whether you consistently bet at better prices than the market closed at —
converges roughly ten times faster, and it is the standard professional
bettors judge themselves by."*

**The 300 threshold, quoted exactly:** *"Minimum sample | 300 graded
picks"* (`:46`), *"Below 300 picks, no verdict is drawn regardless of what
the numbers say"* (`:48`).

**The "60 dates" figure — a real misattribution, found by tracing every
appearance of it.** `docs/VALIDATION_CRITERIA.md` itself **contains no
reference to "60," "ledger," or "dates" anywhere** — its only sample-size
gate is the 300-pick floor above (confirmed by a direct grep of the file;
its stop condition #5, "fewer than 60% of picks were made on games with
complete data," is a data-completeness *percentage*, unrelated in kind and
easy to conflate with a count of dates). Two different 60-something numbers
exist elsewhere and should not be merged: (a) `docs/PREREG_CARD_V2.md:1600-1602`
registers its **own** floor for the V2 rule specifically — *"Its floors stay
at 300 counted picks of a class with a CLV%, 300 graded WIN or LOSS across
60 distinct slate dates"* — stated as that registration's own choice, not
attributed to `VALIDATION_CRITERIA.md`. (b) A **different, older** gate,
`docs/ARCHITECTURE_BETTING_ENGINE.md:326` (commit
`3848931dd6bb97886651ff7a2b5e295ab77c1ad1`, 2026-09-03), defines **"G6
Forward"**, a forward-promotion gate for individual candidate strategies in
the factory/evolution-lab system: *"≥300 forward selections with book,
price, rating, counterarguments and settled close; ≥60 ledger days; class
A/B; out-of-sample only; within sealed epochs."* This is a materially
different gate (per-strategy promotion, not the top-level system CLV/ROI
verdict) that happens to share the number 300 and introduce 60.
**`docs/ROADMAP.md:765`** (commit `1c9ac5baa00b458d0bab90be4bfbdde675fc324e`,
2026-09-15) then states, verbatim: *"Floor before any verdict | 300 graded
picks and 60 ledger dates, closing-line value primary |
`docs/VALIDATION_CRITERIA.md`"* — **citing `VALIDATION_CRITERIA.md` as the
source of a "60 ledger dates" figure that file does not contain.** This
citation error then propagates: the same "≥60 ledger days" language recurs
in `docs/LIVE_BETTING_SYSTEM.md:58,537`,
`docs/planning/design-factory-first.md:483,1222,1350`,
`docs/planning/synthesis-judge.md:950,1373`, `docs/PREREG_CARD_V2.md:2917`,
`docs/SNIPE_SYSTEM.md:626`, and `src/factory/gates.py:346` — all
describing the G6/F4 forward-promotion gate correctly, never re-amending
`VALIDATION_CRITERIA.md` itself. **The task's own framing ("the 300 graded
picks / 60 ledger dates floor") is, strictly, citing a number that only
exists by way of this misattribution** — a real, if minor, documentation
defect, not a fabrication: 60 dates is a genuine floor somewhere in this
codebase, just not in the document usually credited with it.

**Where the numbers came from — derived, or chosen?** Read in full, and
checked against `git log` for the introducing commit (a single commit,
`eed2eb0c`, "Add historical source audit, validation criteria, and README" —
no preceding draft, no linked power calculation, no external citation for
300 specifically): **the document gives a qualitative rate-of-convergence
argument for *why CLV over ROI*, but no power calculation, no cited minimum-
detectable-effect derivation, and no external source for the number 300.**
A repo-wide search for "power analysis" / "minimum detectable effect" /
"sample size calculation" turns up real hits, but every one of them is for a
*different*, later, more rigorous exercise (the F5 family's own
`MDE (two-sided 95%, p≈0.5, n=3,682) = 1.62pp`, `docs/F5_UNIVERSE_FROZEN.md`;
the Card V2 registration's §4.4 power table,
`docs/PREREG_CARD_V2.md:436-450`; the SR1 home-underdog test's own MDE
calculation, `docs/SR1_RESULT_2026-09-16.md`) — never for justifying 300
itself. The separate "60 ledger days" figure (see the misattribution note
above) likewise has **no derivation, formula, or citation anywhere it
appears** — not even an informal one (no document states, for instance, "60
days ≈ two MLB months," the kind of loose justification 300 at least gets).
**Honest statement: 300 is a professional-judgment convention with a stated,
qualitative (not quantitative) rationale; 60 is a professional-judgment
convention with no stated rationale of any kind, taken from a different gate
than the one usually credited with it.** Neither is arbitrary in the sense of
being random — 300 in particular tracks a real, citable property of CLV vs.
ROI convergence rates — but neither is derived from a shown calculation, and
the document does not claim otherwise for 300; nothing claims anything for
60. This matters because §C6 below shows this exact floor (in its
`PREREG_CARD_V2.md` form, 300 picks / 60 dates) is the gate the Price Band
Evidence document (Item 5) is explicitly written to respect.

**CURRENTLY TREATED AS:** a hard, unappealable gate (that part is by design —
the document's whole point is to be pointed at rather than argued with) —
but the specific numbers inside the gate are a **design convention**, not a
derived statistical minimum, and the document does not claim otherwise. The
risk is not the document; it is a reader assuming "300" was computed the way
the F5 MDE or the Card V2 power table were.

### Item 4 — The V1 card calibration leak (nightly refit on the sealed window)

**Source:** `docs/CARD_CALIBRATION_FREEZE_2026-09-15.md`, commit
`ba09312cdb2c1ac5a115b5b537116ad689e6fbb6`; diagnosis in
`docs/CARD_V2_DIAGNOSIS_2026-09-15.md`, commit
`7274ddd485a1d5cdde2c3598d26af0db2bc2f638`.

**Mechanism, precisely.** `data/processed/card_calibration.json` holds a
Platt scaling (`a`, `b`) applied to the raw run model's win probability
(`src/report/card.py: load_calibration`). `scripts/fit_card_calibration.py`
refit `a`/`b` **every night** from `scripts/daily_loop.sh`, on every
completed 2026 game back to 2026-04-15. The canonical split reserves
2026-01-01 through 2026-08-27 as a **sealed window — one evaluation ever**,
only after a policy freeze plus the owner's explicit go, with 2026-08-28
onward as forward proof "never folded back into tuning." The nightly refit
read the sealed window anyway: of 1,901 rows the fit selects, **1,753
(92.2%) fall inside the sealed window**, and only 148 are forward games —
meaning the refit also folded forward games back into fitting, a second,
independent breach of the split. This ran nightly from **2026-09-10** until
the owner ordered it stopped on **2026-09-15 at about 22:35Z** ("Freeze it
now"). Constant `b` moved every night during that window: 0.70785 (09-10) →
0.725406 → 0.743582 → 0.753131 → 0.744719 → 0.769145 → **0.735183** (final,
09-15T21:04Z) — roughly an 8% wander in six days, fit against the same
outcomes the card was being graded against.

**The precise, important distinction the diagnosis draws (quoted):** *"It
does not make V1's forward picks leak: each night's fit uses only games
finished before that card... The breach is of the seal and of the
forward-proof clause, not of point-in-time correctness."* This is a
pre-registration/multiplicity breach (the sealed window's "one evaluation
ever" property is destroyed by repeated reads), not a look-ahead leak on any
single graded pick.

**Two other fitted constants share the same defect and are NOT covered by
the 2026-09-15 freeze**, stated explicitly in the freeze document itself:
*"This freeze covers only the card calibration (a, b above). It says nothing
about `DISPERSION` or `RHO`... which are separate decisions."*
`DISPERSION = 2.3352` was fit 2026-04-15→07-15 (inside the sealed window) and
held-out-checked from 2026-07-16; `RHO = 0.05065` was fit 2026-06-17→08-05
(inside the sealed window) and tested from 2026-08-06. Both remained live and
unfrozen as of the freeze date (see §B22 below for why `DISPERSION`'s
underlying claim is nonetheless well-replicated independently on 2025 data).

**Exhaustive accounting of what is now in question:**

1. **The card's published headline record (2026-09-10 to 09-14: 26-12, 68%
   win rate, +4.8194 units)** — downgrades from "the card's track record" to
   **not a valid single-model sample.** `docs/VALIDATION_CRITERIA.md:113-114`:
   *"Anything measured after a mid-sample model change. Changing the model
   restarts the sample."* A nightly-changing calibration is a nightly model
   change; `docs/CARD_CALIBRATION_FREEZE_2026-09-15.md:69-73` states this
   outright: *"no V1 closing-line or return verdict can be drawn from that
   record as if it were one continuous, fixed model."*
2. **The "0.0012 nats over 1,896 games" claim** (`daily_card.py`'s own
   docstring justification for why the card ranks by market confidence
   rather than model disagreement, repeated in
   `docs/CARD_MARKET_BREADTH_FINDINGS.md:33-34` without flagging the overlap)
   — its evaluation window (2026-04-15 to 2026-09-06) is >92% inside the
   sealed period. Downgrades from "a settled justification for the card's
   ranking rule" to **an unconfirmed number quoted, not re-run, from a
   contaminated window.**
3. **The sealed window itself (2026-01-01→2026-08-27)** — downgrades from "a
   clean one-shot holdout, usable once" to **burned for any rule that reuses
   these specific fits.** Quoted: *"The sealed window's one evaluation cannot
   confirm any rule built using these fits: the calibration's parameters were
   chosen on the window and evaluated against it repeatedly before this
   freeze. Freezing the file today stops new breaches; it does not restore
   the seal's ability to confirm anything already built on it."* This is why
   Card V2's registration (`docs/PREREG_CARD_V2.md` §1.2) discards
   `DISPERSION` and `RHO` and refits everything once on 2025 rather than
   reusing the sealed-window numbers — even though, per §B22, the
   `DISPERSION` *finding itself* independently replicates on 2025.
4. **NOT downgraded**, per the diagnosis's own careful distinction: point-in-time
   correctness of any single published V1 pick (each night's fit only used
   completed prior games); `docs/DOES_THE_MODEL_BEAT_THE_MARKET.md`'s five
   measurements, which fit their own internal walk-forward calibration and do
   not read the live `card_calibration.json` file (verified directly against
   `scripts/backtest_card_rule.py:115-130` and `scripts/backtest_card.py:155-159`).

### Item 5 — `docs/PRICE_BAND_EVIDENCE_2026-09-17.md`: what it does and does not license

**Source:** commit `87bcd9522a6191b0c34e1e601da53f6d6fe05657`, 2026-09-17.

**What was measured, exactly:** every graded game (moneyline) pick in
`evidence/cards_v1.jsonl`, **6 settled days through 2026-09-15** (48 picks;
staging showed a 7th day with "the shape is the same," not separately
quantified in this document). Break-even computed from each pick's own price
(`1 / decimal_odds`). **48 of 48 graded picks were favourites — not one
underdog, on any day.**

**Exact numbers, per day (verbatim table, `:22-29`):**

| Day | W-L | Units | Hit | Needed to break even | Longest price against |
|---|---|---|---|---|---|
| 09-10 | 2-1 | +0.54 | 66.7% | 58.5% | −165 |
| 09-11 | 7-2 | +2.10 | 77.8% | 63.4% | −205 |
| 09-12 | 6-3 | +0.80 | 66.7% | 61.2% | −212 |
| 09-13 | 5-3 | +0.26 | 62.5% | 59.1% | −183 |
| 09-14 | 6-3 | +1.13 | 66.7% | 58.1% | −207 |
| 09-15 | 5-5 | −2.44 | 50.0% | **64.7%** | −230 |

Split at V2's proposed worst allowed price of −160: priced −160-or-better
(n=24) hit 62.5%, +2.07u; priced worse than −160 (n=24) hit 66.7%, +0.31u —
i.e. the group that won **more often** returned **almost nothing**, because
at −200 break-even is 66.7%.

**What it explicitly does not license, quoted:** *"It does NOT license a
claim that the −160-or-better group has an edge. 24 picks is nothing, both
groups are inside the noise of each other, and the whole sample is seven
days of one sport. Nobody may cite +2.07u as a result."* And: *"No threshold
anywhere was changed in response to these results, and none may be. Seven
days of live picks is a reason to finish a registration, never a reason to
move a bar."*

**What it does establish, quoted:** (1) the live card takes only favourites,
half beyond the price the owner ruled out on 2026-09-15; (2) the two losing
days are "the same strategy at ordinary luck," not a regression or bug; (3)
"a hit rate quoted without its price is meaningless."

**Independent check against the project's own pre-registered floors.**
Against `docs/VALIDATION_CRITERIA.md`'s sample-size gates ("0–99 | Nothing.
Reports must state this explicitly") and the Card V2 registration's 300-pick
/ 60-date floor: **48 picks over 6 days is 16% of the pick floor and 10% of
the date floor.** The diagnosis document's own power calculation
(`docs/CARD_V2_DIAGNOSIS_2026-09-15.md:436-450`) computed that detecting a
true 3-point ROI gap between price bands needs on the order of **9,967 to
12,874 bets per band** — this sample is off that mark by roughly two to
three orders of magnitude, not a borderline case. The document's own
restraint (refusing to cite +2.07u, refusing to move a threshold) is
consistent with — arguably more conservative than — what its own project's
statistical floors would require.

**A compounding, separately-worth-flagging fact:** every one of these 48
picks was generated **under the leaking, nightly-refit calibration**
described in Item 4 (all 6 days fall inside the 09-10–09-15 leak window; the
document's own addendum discovers and discloses this same-day). So
independent of the sample-size problem, the *labels* (STRONG/LEAN,
our-number-vs-market) behind these 48 picks are themselves downstream of a
calibration constant that "wandered ~8% in six days" while being fit on the
outcomes it was graded against — a second, compounding reason no performance
conclusion should be drawn from this specific 48-pick sample, on top of and
independent of its size.

**A judgment call worth surfacing rather than hiding:** one research pass on
this item characterized the act of publishing these specific numeric splits
(hit rates, unit totals, per-band breakdowns) — even while explicitly
refusing to draw a verdict from them — as a "soft/spirit-level concern" under
`VALIDATION_CRITERIA.md`'s stated rationale (*"If you decide what counts as
success after seeing results, you will set the bar wherever the results
landed"*), while stopping short of calling it a letter-of-the-rule violation,
since the rule bars *verdicts*, not *description*, and this document produces
description and says so repeatedly. That reading is recorded here as one
analyst's judgment, not as an established fact — the document itself does
not violate its own stated rule, and it does not move any threshold.

---

## Part II — Belief-by-belief map

### A. Market epistemics and the evaluation framework

#### A1. Closing-market efficiency (MLB moneyline)

- **BELIEF:** The MLB closing moneyline is efficient — there is little to no
  exploitable mispricing left in it by the time it closes.
- **ORIGIN:** `docs/RESEARCH_V2.md:16-18`, commit `ff222ab66bbbc6b152c6401ddcb0df8b118249bb`, 2026-08-29.
- **EVIDENCE:** External, not internal. Quoted: *"Sung & Johnson tested 1,547
  simple wagering strategies on MLB moneylines, 1999–2016. 38 (2.46%) were
  profitable at the 5% level, 7 (0.45%) at the 1% level — at or below what
  pure chance produces. Their conclusion is the MLB moneyline market is
  extremely efficient."* This is someone else's finding on someone else's
  data, imported as the project's prior.
- **EXPERIMENT THAT SUPPORTS IT (internal, indirect):** `docs/BENCHMARK_ELO.md`
  — a from-scratch, never-tuned, public-grade Elo (FiveThirtyEight
  constants) loses to the de-vigged close by **+0.00801 log-loss per game**
  (date-clustered two-sided p = 0.0003) on 2024 (2,234 games). Phase 2A
  (Item 1 above) restates this same number rounded to "0.008." Neither of
  these tests "is the close efficient" directly — they test "does a
  cheap/free model beat it," which is a weaker claim consistent with, but
  not proof of, market efficiency.
- **DATA PERIOD:** External citation, 1999–2016; internal corroboration
  2023–24 (non-evidential sandbox).
- **TARGET:** Home win / model-vs-market log-loss.
- **MODEL FAMILY:** N/A (external citation) / public-grade Elo (internal).
- **FEATURE REPRESENTATION:** N/A / Elo ratings only.
- **MARKET:** MLB moneyline.
- **TIME OF PREDICTION:** Close.
- **STATISTICAL STRENGTH:** The external citation is a large, published
  academic result; the internal corroboration is a single benchmark with a
  clear, significant result but tests a different (weaker) claim.
- **KNOWN LIMITATIONS:** No document in this repo directly tests "is the
  close efficient" on this project's own data with a design built for that
  question; the belief is imported and then treated as the interpretive
  frame for every internal null (e.g. `docs/RESEARCH_V2.md:197`: "If all
  five fail, the honest conclusion is that this market is efficient at the
  resolution we can observe it" — stated as the *fallback reading* of a
  null, not as something separately proven).
- **CURRENTLY TREATED AS:** strong evidence for the *practical* posture
  ("don't expect to beat the close easily"), but the specific claim "the
  MLB close is efficient" is an **inherited assumption** from external
  literature, not a directly-measured internal fact.

#### A2. Whether incremental information beyond market price exists at all

- **BELIEF:** No demonstrated source of information beats the market price at
  any market this project has tested with real prices.
- **ORIGIN:** `docs/DOES_THE_MODEL_BEAT_THE_MARKET.md`, commit
  `700571f9382495bfd210abb9f0cbb939149da570`, 2026-09-10.
- **EVIDENCE:** Quoted headline: *"Short answer: no measurement has shown
  that it does, and five independent ones point the same way."* Five
  measurements: (1) team model vs. base rate +0.004 nats; (2) prop model vs.
  base rate **+0.0133 nats** on `batter_hits`, 16,741 games, no price
  involved — genuinely informative, but "a statement about the model, not
  about beating a price"; (3) props vs. market price, 1,107 contracts,
  paired diff +0.00655, 95% CI [−0.00137, +0.01455] — undetermined, interval
  spans zero; (4) betting the disagreements, both directions — OVER ROI
  −13.4% (n=113), UNDER −0.2% (n=163) — no finding; (5) the card's own
  selection rule, 97 games, all intervals 20–75 points wide — nothing
  found.
- **EXPERIMENT THAT SUPPORTS IT:** The five scripts named above, plus
  `docs/EDGE_SEARCH_2026-09-10.md` (player-prop disagreement-selection ROI
  **−16.6%** at n=82 vs. control −9.1% at n=1,107 — *"Selecting on our own
  edge did worse than not selecting at all"*) and Phase 2B's evolutionary
  search (8,811 strategies, 0 of 3 generators cleared the placebo ceiling,
  pooled exceedance p = 0.871 — "the real maximum... is under the middle of
  the noise").
- **DATA PERIOD:** 2026 (props, live); 2023–24 (team model, non-evidential).
- **TARGET:** Varies by measurement (win/loss, prop outcome, ROI).
- **MODEL FAMILY:** Varies (logistic team model, rate-based prop model,
  evolved genome search).
- **FEATURE REPRESENTATION:** Varies.
- **MARKET:** Moneyline, player props (`batter_hits`, `batter_total_bases`,
  others).
- **TIME OF PREDICTION:** Varies; mostly near-game-time live captures.
- **STATISTICAL STRENGTH:** Five independent measurements agreeing in
  direction, several with tight, informative confidence intervals (item 4);
  one (item 3) genuinely undetermined rather than negative.
- **KNOWN LIMITATIONS:** `docs/CARD_MARKET_BREADTH_FINDINGS.md` shows the
  live card does not even use the one internally-ranked-on-price system
  (`src/analysis/opportunities.py`) that already exists — so part of "no
  edge found" is "no edge looked for in the market the system already ranks
  correctly," a gap the audit itself calls out (`grep value_points
  src/analysis/daily_card.py` returns nothing — "the card throws it away").
- **CURRENTLY TREATED AS:** strong evidence, published as a register
  precisely so it cannot be quietly forgotten. Correctly scoped by its own
  documents as "no measurement has shown it" rather than "it does not
  exist."

#### A3. Market-residual modeling as the system's live pricing architecture

- **BELIEF (to test and correct):** Not actually a live belief — flagged here
  because the phrase "market-residual model" could be misread as describing
  production.
- **ORIGIN:** Only appears in `src/evolab/baseline.py` (Phase 2A, Item 1
  above).
- **EVIDENCE:** A repo-wide search for "residual" finds this exact
  offset-residual construction in exactly one place — the Phase 2A research
  diagnostic. Every other "residual" hit (`src/analysis/consistency.py:103`,
  `src/analysis/strength.py:139`, `src/factory/gates.py`,
  `src/model/discovery.py`) is either a prose reference, a GLM diagnostic,
  or an unrelated statistical use.
- **EXPERIMENT THAT SUPPORTS IT:** N/A — this is a one-off research
  technique used to answer one question, never wired into `daily_card.py`,
  `best_bets_card.py`, or any live decision path.
- **DATA PERIOD / TARGET / MODEL FAMILY / FEATURE REPRESENTATION / MARKET /
  TIME OF PREDICTION:** as in Item 1 (Phase 2A) only.
- **STATISTICAL STRENGTH:** N/A — not a production claim.
- **KNOWN LIMITATIONS:** none needed; the finding here is negative —
  characterizing this project as doing "market-residual modeling" in
  production would be an overclaim not supported by the code.
- **CURRENTLY TREATED AS:** N/A in production. Recorded so a future reader
  does not conflate a research diagnostic with the shipped architecture.

#### A4. Production model identity — what actually prices today's card

- **BELIEF (undocumented, discovered rather than stated anywhere in one
  place):** The model generating today's card is a hand-built two-team
  Poisson/Negative-Binomial run-scoring model (`src/analysis/strength.py`),
  not the logistic-regression classifier the repo's Aug-27 commit history
  calls "the project's first real prediction" (`src/model/logistic.py`).
- **ORIGIN:** No single doc states this. `docs/ARCHITECTURE_BETTING_ENGINE.md`
  (2026-09-03, still marked "PLAN, awaiting owner review") diagnoses a
  related fragmentation — *"there are two decision paths that do not know
  about each other"* — but does not mention `strength.py` or
  `logistic.py` by name (zero grep hits for "strength", "logistic", or
  "Poisson" in that file or `docs/ENGINE_CONTRACT.md`).
- **EVIDENCE:** `src/pipeline/predict.py` (the only consumer of
  `src/model/logistic.py`) has **no callers** anywhere in `src/` or
  `scripts/` outside its own tests — confirmed by repo-wide grep. The actual
  card pipeline (`src/analysis/daily_card.py`, `src/report/card.py`) imports
  `src.analysis.strength` exclusively. `src/report/card.py`'s
  `ACTIVE_CARD_RULE = "v1"` (uncommitted at time of audit) is the single
  runtime switch stating which rule is live.
- **EXPERIMENT THAT SUPPORTS THE CHOICE:** `daily_card.py:36-56` argues the
  logistic-style approach is too weak relative to the market (0.0012 nats
  over a base rate — itself the Item-4-tainted number) and should be used
  only for pass/fail agreement, never ranking.
- **DATA PERIOD:** `strength.py`'s one fitted constant (`DISPERSION`, see
  §B22) — 2026-04-15 to 07-15 fit, replicated on 2025.
- **TARGET:** Home/away run means → win probability, run-line probability,
  total.
- **MODEL FAMILY:** Two-Poisson/NB1 run-scoring model (odds-ratio
  offense-vs-defense construction, log5-style), not the logistic classifier.
- **FEATURE REPRESENTATION:** Team runs scored/allowed, starter FIP blended
  with bullpen rate by innings-share, fixed home-field run credit, park
  factor multiplier.
- **MARKET:** Moneyline, run line, (not) totals.
- **TIME OF PREDICTION:** Card freeze, ~4 hours before earliest game
  (`docs/PLAN_TO_FIRST_SALE.md`); props explicitly analyzed pre-lineup
  (`require_lineup=False` is the production default,
  `src/analysis/best_bets_card.py:96-98`, per an explicit 2026-09-14 owner
  instruction).
- **STATISTICAL STRENGTH:** The model itself has "no free parameters" beyond
  `DISPERSION` by design (`strength.py` docstring: "cannot be overfitted, so
  its out-of-sample behaviour is its only behaviour").
- **KNOWN LIMITATIONS:** `docs/CARD_PUBLISH_WINDOW.md` documents that the
  production cron historically published *after* first pitch for roughly one
  day in five, directly contradicting the card's own disclaimer ("published
  before first pitch") — the doc states the author was "not able to make"
  the one-line fix at the time of writing; whether it has since landed was
  not independently re-verified for this audit and should be checked against
  the live `.github/workflows/afternoon-slate.yml` cron value before this
  belief is relied on.
- **CURRENTLY TREATED AS:** an accurate but **nowhere-consolidated** fact.
  A reader relying only on `docs/ARCHITECTURE_BETTING_ENGINE.md` or the
  celebratory `logistic.py` commit message would reasonably, and wrongly,
  believe the logistic model is live. This is not a belief resting on weak
  evidence; it is a true fact resting on no single citable document — a
  documentation gap, not an evidence gap.

#### A5. CLV as the primary metric (the choice itself, not the threshold numbers)

- **BELIEF:** CLV, not ROI, should be the pass/fail criterion for whether
  this system has found anything.
- **ORIGIN:** `docs/VALIDATION_CRITERIA.md:28-35`, commit `eed2eb0c`
  (Item 3 above).
- **EVIDENCE:** A qualitative convergence-rate argument (CLV needs an order
  of magnitude fewer bets than ROI to separate signal from variance) plus an
  appeal to how "professional bettors judge themselves." No citation to a
  specific power calculation or academic source is given for *why CLV over
  ROI specifically*, though the underlying statistical fact (CLV has lower
  variance per observation than binary win/loss ROI) is a standard,
  uncontroversial one in the sports-betting literature — it is simply not
  cited here.
- **EXPERIMENT THAT SUPPORTS IT:** None internal — this is a pre-registered
  design decision, written explicitly *before* any data existed, by design.
- **DATA PERIOD / TARGET / MODEL FAMILY / FEATURE REPRESENTATION / MARKET /
  TIME OF PREDICTION:** N/A — this is a meta-level evaluation rule, not a
  model claim.
- **STATISTICAL STRENGTH:** N/A by construction (pre-registered before
  data).
- **KNOWN LIMITATIONS:** The document does not engage with the strongest
  objection to CLV-as-primary — that CLV measures whether the system found a
  *market* inefficiency relative to its own later price, not whether the
  system's picks are *profitable*, and the two can diverge if the system is
  systematically betting into vig-heavy or thin markets where "beating the
  close" is easy but the close itself is a bad number. `VALIDATION_CRITERIA.md`
  does partially address this via its non-negotiable market-comparison gate
  (§"The market comparison is not negotiable... if the model's log loss is
  worse than simply using the de-vigged market price... no CLV figure
  rescues that"), which closes much of that gap.
- **CURRENTLY TREATED AS:** a well-reasoned **design convention**, adopted
  pre-registration (which is exactly the right time to adopt a convention),
  but not itself independently tested or externally validated within this
  repo. Not a violation — the whole point of pre-registration is that this
  kind of choice is made *before* it can be data-mined — but it is worth
  recording plainly that "CLV primary" rests on an uncited, if standard,
  statistical argument rather than a derivation shown in this repo.

#### A6. Edge threshold: `BASE_EDGE = 0.010`, `MARKDOWN = 0.038`

- **BELIEF:** A candidate's raw probability must clear break-even by a
  price-scaled margin of `MARKDOWN + BASE_EDGE`-plus before it is treated as
  a real bet, and this specific pair of numbers is the right size for that
  margin.
- **ORIGIN:** `docs/PREREG_CARD_V2.md` §4.1–4.2 (lines 489-543), commit
  `193b01a81d2c0d76a945f2b4424b4bb72b76f262`; implemented
  `src/analysis/best_bets_card.py:82-83`, commit `31cdf3783cd1b209f4f928769783ef654e9a81c8`.
- **EVIDENCE, quoted exactly:** `MARKDOWN = 0.038` comes from
  `docs/PROP_CALIBRATION_2026-09-14.md`'s reliability table: the 50-60%
  probability bucket, n=212, predicted 0.5712, hit 0.5330 — "+3.8 points
  overconfident." `BASE_EDGE = 0.010` is "the spread between the two
  adequately populated measured figures: 4.8 minus 3.8 is 1.0 point,"
  where 4.8 is the 60-70% bucket's overconfidence (n=361). The document is
  explicit about what this number is *not*, quoted: *"It is not a standard
  error and is not called one; it is a fixed, published, unfitted number of
  the right order."*
- **EXPERIMENT THAT SUPPORTS IT:** The prop-calibration reliability table
  itself — but that table was measured on **player props, settled
  2026-09-08 to 09-12 (5 calendar dates, 1,200 contracts, with 69% of rows
  from a single date per `docs/PROP_CALIBRATION_2026-09-14.md`)** — and is
  applied to **moneylines and run lines as well as props**. The registration
  states this transfer plainly: *"The largest assumption. `MARKDOWN = 0.038`
  is measured on props, on the side we favour, so every application of it
  below 0.50 is a transfer, not a measurement"* (`PREREG_CARD_V2.md:1521`,
  `:509-510`).
- **DATA PERIOD:** Props settled 2026-09-08 to 09-12 (forward, not sealed,
  not tuning — but a 5-day, single-slate-dominated window).
- **TARGET:** Contract-level over/under hit rate by predicted-probability
  bucket.
- **MODEL FAMILY:** N/A — a reliability-table lookup, not a fitted model.
- **FEATURE REPRESENTATION:** N/A.
- **MARKET:** `batter_hits`, `batter_total_bases` player props — transferred
  to moneyline/run-line game markets without a game-market-specific
  measurement.
- **TIME OF PREDICTION:** Pre-lineup (props priced with `require_lineup=False`).
- **STATISTICAL STRENGTH:** n=212 and n=361 within one narrow, single-slate-
  dominated 5-day window; no confidence interval or standard error is
  computed or reported for either bucket's overconfidence estimate — the
  document says so itself ("not a standard error"). A sensitivity table is
  published (`PREREG_CARD_V2.md:602-621`) showing the published card's
  pick count is not knife-edge to a one-notch move in either constant, which
  is real evidence of *robustness to the exact number chosen*, but not
  evidence that *0.038/0.010 as opposed to 0.03/0.008* is the correct
  magnitude.
- **KNOWN LIMITATIONS:** All stated in the registration itself, and stated
  well: props-to-game-market transfer; a 5-day, one-slate-dominated fit
  window; "not a standard error." The registration's own §4.4 states the
  consequence in the open: *"The one error this repo has actually measured
  on a similar slice is 21.5 points. If the real error in the plus-money
  band is anywhere near that, these picks lose money and no threshold here
  stops them quickly."*
- **CURRENTLY TREATED AS:** a genuinely **transparent design convention**
  — the registration is unusually honest that this is "a fixed, published,
  unfitted number of the right order," not a statistically derived
  quantity — but the *published card* uses it as a hard gate (G7) with the
  weight of a measured threshold. This is one of the clearest cases in the
  repo of a number being treated with the operational confidence of a fact
  while its own source document calls it a judgment call.

#### A7. Expected value (EV) as a calculation and as a decision rule

- **BELIEF:** EV is computed in this codebase, and the project's hard rule is
  that it must never be used to justify or promote a pick (line-shopping
  value is price improvement, never EV).
- **ORIGIN:** `src/core/odds.py:294-303` (`expected_value()`), commit
  `be8c99b58bb3e48f1d2917d47c7aff8a5bdd2a9f`, 2026-08-27;
  `src/core/staking.py:132,144-149` (`size_bet()`) uses it as a hard
  bet/no-bet gate: `if ev <= 0: return {"stake": 0.0, ...}`.
- **EVIDENCE this is currently honored in production:** an exhaustive
  repo-wide grep for callers of `expected_value()`/`size_bet()` finds only
  the modules' own tests (`tests/test_core_odds.py:160-174`,
  `tests/test_core_staking.py:105-144`) — **no production surface
  (`daily_card.py`, `best_bets_card.py`, `opportunities.py`, `card_ledger`,
  `api/card.py`) calls either function.** Production surfaces actively
  disclaim EV, with tests guarding the language:
  `src/analysis/daily_card.py:61,183` ("It does not claim... positive
  expected value"), `src/analysis/opportunities.py:15` ("Not a ranking by
  expected value"), `src/analysis/betcheck.py:271,279` ("PRICE CONTEXT,
  never EV"), and guard tests
  `tests/test_card_record_page.py:308` (`test_never_claims_an_edge_or_positive_expected_value`).
- **EXPERIMENT THAT SUPPORTS IT:** N/A — this is a labeling/product-honesty
  rule, not an empirical claim.
- **DATA PERIOD / TARGET / MODEL FAMILY / FEATURE REPRESENTATION / MARKET /
  TIME OF PREDICTION:** N/A.
- **STATISTICAL STRENGTH:** N/A.
- **KNOWN LIMITATIONS:** `size_bet()`'s EV-as-gate logic is dead code, not
  deleted code. It is tested, correct arithmetic, and currently unreachable
  from anything that publishes a pick — but nothing prevents a future change
  from wiring it into a live path without carrying the same guard-rails
  forward, which would silently reintroduce EV-as-promotion-criterion.
- **CURRENTLY TREATED AS:** the rule ("never EV, never edge") is currently
  a fact about production behavior, actively enforced by tests. The EV
  arithmetic itself is a **dormant risk**, not a violation — flagged here
  because a task auditing "is EV ever used to promote a pick" should know
  the capability exists in the codebase even though nothing currently calls
  it.

---

### B. Feature-level beliefs

#### B1. Specific pitching metrics (FIP, not xFIP)

- **BELIEF:** FIP (not xFIP) is the right pitcher-quality summary to feed the
  model; season-aggregate pitcher features materially improve prediction.
- **ORIGIN:** `src/pipeline/pitchers.py`, commit
  `beae40e76c522c995f8d4a02764dbdd6edead83e`.
- **EVIDENCE the xFIP-vs-FIP choice is deliberate, quoted:** *"The charter
  asks for xFIP weighted above ERA. xFIP replaces a pitcher's actual home
  runs with an expected number derived from fly balls, and fly-ball data is
  not in this feed. So xFIP is NOT computed... FIP is computed instead...
  Calling it xFIP would be a lie that survives right into the model."* This
  is a data-availability constraint honestly disclosed, not a modeling
  choice defended on merit.
- **EXPERIMENT THAT SUPPORTS THE BROADER "pitcher features help" belief:** a
  real, controlled ablation exists — commit `200ec51ecdba3a0797d2491677bb0751f24e7038`,
  "Add point-in-time pitcher features; they barely help, and that matters,"
  quoted: *"team only: val 0.687375, test 0.680695. team + pitchers: val
  0.687577, test 0.680486. change: −0.000202 / +0.000208"* — both movements
  are noise. *"No pitcher rate stat appears in the top coefficients."* What
  *did* improve: calibration — test ECE fell from 0.0297 to 0.0180, val ECE
  from 0.0086 to 0.0032.
- **DATA PERIOD:** Not stated precisely in the commit message beyond
  "point-in-time"; consistent with the 2023–24 sandbox given the commit
  date (2026-08-27, same era as the historical store buildout).
- **TARGET:** Home win (discrimination), plus calibration error.
- **MODEL FAMILY:** The (orphaned) logistic classifier, `src/model/logistic.py`.
- **FEATURE REPRESENTATION:** Season-aggregate FIP and related rate stats.
- **MARKET:** Moneyline (research context, not live pricing — the live model
  is `strength.py`, which separately blends starter FIP into run means).
- **TIME OF PREDICTION:** Point-in-time, per-game.
- **STATISTICAL STRENGTH:** A genuine held-out test-set comparison; the
  discrimination result (near-zero, noise-level) is a real negative finding
  with numbers attached, not an assumption.
- **KNOWN LIMITATIONS:** This ablation used season aggregates; it does not
  test the pitch-level "rebuilt" features (velocity gap, groundball share)
  that Families V1/V4/V5 tested separately (also null — see §B5) and that
  are also downstream of the probable-pitcher PIT leak (Item 2).
- **CURRENTLY TREATED AS:** a rare case of a strong prior ("the starter is
  the single largest determinant of a game" — `pitchers.py`'s own docstring)
  being **directly tested and found false for discrimination**, with the
  finding written up honestly rather than buried. Treated as **strong
  evidence** for "season-aggregate starter stats add noise-level
  discrimination but real calibration value" — one of the better-evidenced
  negative results in the repo.

#### B2. Bullpen effects

- **BELIEF:** Bullpen state matters, and recent-workload/availability (not
  season ERA) is the right way to model it.
- **ORIGIN:** `src/pipeline/bullpen.py` module docstring: *"Season bullpen
  ERA answers 'is this pen good'. It cannot answer 'is their closer
  available tonight'... So availability here is a MODELLED LIKELIHOOD with
  the evidence attached, never a fact."*
- **EVIDENCE:** Usage-window constants (`HEAVY_OUTING_PITCHES = 30`,
  `BACK_TO_BACK_PITCHES = 20`, `MAX_CONSECUTIVE_DAYS = 3`,
  `WORKLOAD_WINDOW_DAYS = 7`) are explicitly labeled *"pre-registered from
  how bullpens are actually run, not fitted to anything."*
- **EXPERIMENT THAT SUPPORTS IT:** Two pre-registered detectors,
  `docs/RESEARCH_CATALOGUE.md`: `bullpen_exposure` (+1.65pp, CI
  −0.70..+4.04, p=.18, ROI +2.2%, but split +0.72/+2.61 across seasons) and
  `bullpen_workload` (+0.79pp, CI −0.81..+2.34, p=.32). **Both null; neither
  clears the pre-registered FDR + 1pp-floor gate.**
- **DATA PERIOD:** 2023–24 (Family V1, non-evidential sandbox).
- **TARGET:** Side-level detector effect (win margin/probability).
- **MODEL FAMILY:** Single-feature detector, not a fitted model.
- **FEATURE REPRESENTATION:** Appearance-level workload counts and recency.
- **MARKET:** Moneyline.
- **TIME OF PREDICTION:** Morning-of, point-in-time.
- **STATISTICAL STRENGTH:** Two pre-registered hypotheses, both with
  confidence intervals spanning zero.
- **KNOWN LIMITATIONS:** The usage-window constants (30 pitches, 20 pitches,
  3 days, 7 days) are stated as baseball convention, not fitted — no
  ablation tests whether e.g. 3 days vs. 2 or 4 days changes anything.
- **CURRENTLY TREATED AS:** used in production (`strength.py` blends
  bullpen rate into defense) by **design convention** for the mechanism, and
  as a **tentative-to-null** finding for whether it adds predictive value —
  the two direct tests of "does bullpen state predict a game outcome" both
  came back null.

#### B3. Recent form (hot/cold streaks)

- **BELIEF:** A short recent window (three starts) is a better read on a
  pitcher's current form than a full-season rate.
- **ORIGIN:** `src/pipeline/pitchers.py:46-48`, quoted: *"Recent-form window,
  in starts. Three is the common 'how is he throwing lately' horizon and is
  short enough to react to a genuine change. RECENT_STARTS = 3."*
- **EVIDENCE:** None found for the specific window of three. No dedicated
  ablation isolating `RECENT_STARTS` was found in `docs/RESEARCH_CATALOGUE.md`
  or elsewhere; it is folded into the same pitcher-feature bundle tested in
  §B1 (which found near-zero discrimination gain, with no ability to
  attribute that null specifically to the recency window versus the rest of
  the bundle). No dedicated team-level hot/cold-streak feature exists in
  `src/pipeline/features.py` at all — team features use season-to-date
  accumulation, not streak windows.
- **EXPERIMENT THAT SUPPORTS IT:** none found.
- **DATA PERIOD / TARGET / MODEL FAMILY / FEATURE REPRESENTATION / MARKET /
  TIME OF PREDICTION:** as in §B1 (bundled, not separately tested).
- **STATISTICAL STRENGTH:** none — no dedicated test.
- **KNOWN LIMITATIONS:** "Three is the common horizon" is an appeal to
  convention ("common"), not a citation or a measurement.
- **CURRENTLY TREATED AS:** a **design convention**, explicitly labeled as
  such in its own comment ("the common... horizon"), never elevated beyond
  that by any test in this repo.

#### B4. Hitter splits (platoon, vs. L/R)

- **BELIEF:** Point-in-time, pitch-level ("rebuilt") platoon splits are safe
  and informative; live season-aggregate splits are not safe to use
  historically.
- **ORIGIN:** `src/model/pointintime.py:108-133` (leakage finding on live
  splits) and `src/pipeline/rebuilt.py` (the point-in-time replacement),
  commit `4de2b63d01bdbcd710ce457547e1842ad69070a3`.
- **EVIDENCE (leakage half, strong and directly measured):** *"the MLB
  statSplits endpoint IGNORES startDate and endDate — verified by requesting
  three different ranges for one pitcher and receiving byte-identical
  numbers. It always returns the whole season to date, so applying it to an
  earlier game leaks results that had not happened yet."* This is a
  confirmed, mechanically verified leak in the *live* endpoint, fixed by
  building `rebuilt_splits` from Statcast pitch-level rows instead
  (`MIN_BF_PER_SIDE = 60` floor).
- **EVIDENCE (predictive-value half, weak):** three separate pre-registered
  platoon hypotheses, all null: `platoon_mismatch` (+3.84pp, CI
  −5.79..+13.37, p=.44, n=104 — flagged in the catalogue itself as "104
  games whose per-season effects point in OPPOSITE directions... the
  definition of noise, not a candidate"); `platoon_pressure` (died in the
  2023 screen, wrong direction); `handed_lineup_vs_pitch` (sign-flipped at
  2024 replication, +0.15pp → −3.55pp).
- **EXPERIMENT THAT SUPPORTS IT:** the three pre-registered hypotheses above,
  Family V1/V4, `docs/RESEARCH_CATALOGUE.md`.
- **DATA PERIOD:** 2023 screen, 2024 replication.
- **TARGET:** Side-level detector effect.
- **MODEL FAMILY:** Single-feature detectors.
- **FEATURE REPRESENTATION:** Platoon-split wOBA gaps from rebuilt,
  pitch-level Statcast accumulation.
- **MARKET:** Moneyline.
- **TIME OF PREDICTION:** Point-in-time, gated on the (leaky, per Item 2)
  probable-starter identity.
- **STATISTICAL STRENGTH:** Three separate pre-registered tests, all
  null or sign-flipping at replication — a real, if unglamorous, negative
  result.
- **KNOWN LIMITATIONS:** All three tests are downstream of the
  probable-pitcher PIT leak (Item 2) — per that audit, this makes their
  nulls *stronger*, not weaker, since the leak's direction favors the
  feature.
- **CURRENTLY TREATED AS:** the leakage-avoidance half is **fact**, directly
  and mechanically verified. The "platoon splits predict outcomes" half is
  **tentative-to-null** — tested three separate ways, none surviving.

#### B5. Starter effects generally (beyond the PIT scratch issue)

- **BELIEF:** "The starting pitcher is the single largest determinant of one
  game's outcome, and the market prices it heavily" — stated as the
  motivating rationale for building pitcher features at all.
- **ORIGIN:** `src/pipeline/pitchers.py:5-10`, quoted in full above.
- **EVIDENCE:** This is stated as a design rationale *before* the feature was
  tested. The subsequent controlled test (§B1, commit `200ec51e...`) directly
  measured it and found it **false for season-aggregate features**:
  discrimination gain is noise-level; only calibration improved. The
  commit message is self-aware about this exact trap, quoted: describing
  the near-miss of "add these features, observe the model still beat its
  baseline, and credit the pitchers" as the mistake avoided.
- **EXPERIMENT THAT SUPPORTS IT:** §B1's ablation (against it, for season
  aggregates); Families V1/V4/V5's pitch-level starter-mismatch detectors
  (also null — `starter_mismatch`: −0.75pp, CI −2.74..+1.27, p=.48).
- **DATA PERIOD:** 2023–24 for the pitch-level tests; unspecified
  point-in-time window for the season-aggregate ablation.
- **TARGET:** Home win.
- **MODEL FAMILY:** Logistic classifier (season-aggregate); single-feature
  detectors (pitch-level).
- **FEATURE REPRESENTATION:** FIP/rate stats; velocity gap, groundball
  share, primary-pitch share.
- **MARKET:** Moneyline.
- **TIME OF PREDICTION:** Point-in-time (gated on the Item-2 PIT leak for the
  pitch-level tests).
- **STATISTICAL STRENGTH:** Two independent test families, both null for
  discrimination.
- **KNOWN LIMITATIONS:** Untested: whether starter identity matters through a
  *nonlinear* or matchup-specific channel rather than a linear season-rate
  channel — this is exactly the open question `ALTERNATIVE_HYPOTHESES.md`
  H3 (arsenal × lineup mismatch) proposes and has not yet run.
- **CURRENTLY TREATED AS:** a strong prior belief that was **directly tested
  and not supported** for the two representations tried (season-aggregate
  linear; pitch-level single-feature). Still **untested** for a matchup/
  interaction representation. The gap between "the market prices the
  starter heavily" (almost certainly true) and "our starter features add
  anything beyond what the market already reflects" (tested twice, found
  false both times) is the whole story here, and the codebase mostly gets
  this right — `pitchers.py`'s own docstring is the belief; the ablation
  commit is the correction.

#### B6. Weather

- **BELIEF (as coded):** Weather may matter for totals-relevant games but is
  not yet a proven input; wind speed is reportable, wind direction is not
  reliable enough to interpret.
- **ORIGIN:** `src/detect/detectors.py`, the `ParkAndWeather` detector,
  quoted: *"Weather has been collected by this project since the beginning
  and used by nothing... Wind is deliberately NOT interpreted as helping or
  hurting: park orientation is unknown for all thirty parks, and a wrong
  bearing inverts a real effect."*
- **EVIDENCE:** The detector's own status is set literally to `UNPROVEN` in
  code. `src/providers/weather.py` docstring: "wind is collected but not yet
  applied as a model input." No historical weather backfill exists for
  2023–24 at all (`docs/planning/map-historical-data-pit.md` §5: "no
  backfill run has ever populated 2023-24 weather into `data/historical`").
- **EXPERIMENT THAT SUPPORTS IT:** `docs/RESEARCH_CATALOGUE.md`'s
  `park_and_weather` hypothesis: "Registered, ran, side-less by design
  (bears on totals, and no totals family has ever been registered)" — i.e.
  it was registered against a market (totals) the product doesn't publish,
  so it has never actually been tested against a real outcome.
- **DATA PERIOD:** Forward only (`weather_forecast.jsonl`, ~4.5MB, live
  captures); no historical coverage.
- **TARGET:** N/A — never scored against an outcome.
- **MODEL FAMILY:** N/A.
- **FEATURE REPRESENTATION:** Temperature and wind speed (display only);
  direction collected but unused.
- **MARKET:** Intended for totals; totals are not published (`TOTALS_ON_CARD
  = False`, `docs/PREREG_CARD_V2.md:346`).
- **TIME OF PREDICTION:** Forecast, point-in-time by construction (Open-Meteo
  archive is genuinely point-in-time per `pointintime.py`) — but "clean data
  source" says nothing about predictive value.
- **STATISTICAL STRENGTH:** None — never scored.
- **KNOWN LIMITATIONS:** No historical backfill means no retrospective test
  is even possible without new data collection.
- **CURRENTLY TREATED AS:** honestly labeled in code as `UNPROVEN` — this is
  one of the few beliefs in the repo where the **CURRENTLY TREATED AS**
  field is set correctly by the system itself rather than needing correction
  by this audit. Used for display/context only, by **design convention**,
  never for pricing.

#### B7. Lineup information

- **BELIEF:** Posted lineups matter and are usable, subject to a timing
  caveat.
- **ORIGIN:** `data/historical/lineups.jsonl`; `src/model/pointintime.py:78-82`
  marks the historical store CLEAN on the theory the schedule feed returns
  what was actually posted.
- **EVIDENCE this theory is incomplete:** `docs/planning/map-historical-data-pit.md`
  §3, quoted: *"No lineup posting timestamp exists for 2023-24... a replay
  can never prove a lineup-conditioned decision was made after the lineup
  actually posted; it can only assume a nominal T-3h/T-4h posting time...
  3,624/4,819 games survive a T-180 assumption, and that surviving subset is
  start-time-selected, not random."*
- **EXPERIMENT THAT SUPPORTS IT:** `src/evolab/replay.py` names this as a
  second declared, versioned engine parameter (alongside `STARTER_IDENTITY`
  from Item 2) — an assumed T-180-minute posting time, not a measured one.
- **DATA PERIOD:** Historical (2023–24) unknown/assumed; forward
  (`src/pipeline/rosterwatch.py`, from 2026-08) records real `fetched_utc`.
- **TARGET:** N/A (an input-timing question, not itself a predictive claim).
- **MODEL FAMILY:** N/A.
- **FEATURE REPRESENTATION:** Batting-order slot, platoon composition.
- **MARKET:** All markets that condition on lineup (props especially).
- **TIME OF PREDICTION:** Historically assumed at T-180 minutes; forward,
  genuinely known via polling.
- **STATISTICAL STRENGTH:** N/A — a data-provenance question, not tested
  against outcomes directly, though `DOES_THE_MODEL_BEAT_THE_MARKET.md`
  found the batting-slot feature "beats a batter's own season average on
  plate appearances by 13%" (0.608 MAE vs. 0.699) — a real, if modest,
  measured value for the *feature*, distinct from the timing-provenance
  question.
- **KNOWN LIMITATIONS:** The historical replay subset that "survives" the
  T-180 assumption is explicitly non-random (start-time-selected) — any
  historical result conditioning on lineup carries this selection risk.
- **CURRENTLY TREATED AS:** the *predictive value* of lineup slot is
  **tentative evidence** (one real, modest, measured improvement). The
  *point-in-time safety* of using it historically is an **inherited
  assumption** (a named, disclosed one — not hidden — but still an
  assumption, not a measurement, for 2023-24).

#### B8. Home/away effects

- **BELIEF:** Home teams get a fixed run credit of 0.20 runs, reflecting a
  decades-long ~.540 home winning percentage in MLB.
- **ORIGIN:** `src/analysis/strength.py:109`, commit
  `c59300fddc45b79bdc49e61c7c12b7d7fde10066`.
- **EVIDENCE, quoted:** *"League-wide MLB home advantage has sat near a .540
  home winning percentage for decades, which is a little over two tenths of
  a run per game. Held fixed rather than estimated per park, because a
  per-park estimate on one season of data is mostly noise."*
- **EXPERIMENT THAT SUPPORTS IT:** None internal — this is an external,
  cited baseball regularity, explicitly *not* fit or ablated against this
  project's own data. `docs/EVOLAB_PHASE2A_BASELINE.md`'s home-win base rate
  in its own sample (51.97% per `docs/RESULTS_V2.md:22`, close to but not
  identical to .540) is the closest internal corroboration, and it was never
  used to re-derive `HOME_FIELD_RUNS`.
- **DATA PERIOD:** External, "decades" (unspecified range).
- **TARGET:** N/A directly — a run-scoring adjustment, not itself scored.
- **MODEL FAMILY:** N/A.
- **FEATURE REPRESENTATION:** A single additive constant to the home team's
  expected runs.
- **MARKET:** All markets `strength.py` prices.
- **TIME OF PREDICTION:** N/A (a fixed model constant, not a per-game
  input).
- **STATISTICAL STRENGTH:** External, well-established, but not internally
  re-derived or ablated.
- **KNOWN LIMITATIONS:** No internal experiment tests whether 0.20 (vs. 0.15
  or 0.25) is right for this specific model's other constants; explicitly
  "held fixed rather than estimated."
- **CURRENTLY TREATED AS:** a well-grounded **design convention** — grounded
  in a real, citable external regularity, but not independently measured or
  ablated within this codebase, and explicitly documented as a choice
  ("held fixed") rather than a fit.

#### B9. Park effects

- **BELIEF:** Park factors, computed in-house via the classic Bill James
  home/road method, meaningfully adjust run environments and should be part
  of the model.
- **ORIGIN:** `src/pipeline/parkfactors.py` module docstring.
- **EVIDENCE:** Methodologically standard technique, quoted:
  *"factor = (runs per game in the club's home games) / (runs per game in
  the club's road games)"*, with `PRIOR_GAMES` regressing every factor
  toward 1.0 over 150 imaginary neutral games — *"150 is fixed here in
  advance and is not tuned against any result."* Bounds `MIN_FACTOR = 0.80`,
  `MAX_FACTOR = 1.25`, `MIN_HOME_GAMES = 10`.
- **EXPERIMENT THAT SUPPORTS ITS INCLUSION:** Built, tested, point-in-time —
  and, per `docs/PLAN_TO_FIRST_SALE.md`, **"switched off"** for the
  moneyline: *"its pre-specified test declined it for the moneyline and
  predicted in advance that it belongs in totals."* `strength.py` currently
  applies it (`park = _positive(features.get("park_factor")) or 1.0`,
  `strength.py:358-363`) as a multiplier on both teams' run means, "AFTER
  the odds-ratio" so it does not distort which side is favored — a
  deliberate design choice, correctly reasoned, but no ablation number
  showing lift on the moneyline was found (consistent with the module's own
  statement it was built for and tested against totals, which the product
  does not currently publish).
- **DATA PERIOD:** Point-in-time from the project's own `mlb_results.csv`.
- **TARGET:** Totals (intended); currently applied inside the moneyline/run-line
  model as a symmetric multiplier.
- **MODEL FAMILY:** Regressed ratio estimator (Bill James method).
- **FEATURE REPRESENTATION:** Club home/road run-scoring ratio, shrunk toward
  1.0.
- **MARKET:** Built and pre-tested for totals; currently live inside
  `strength.py` for moneyline/run-line.
- **TIME OF PREDICTION:** Point-in-time, as-of any date with ≥10 home games.
- **STATISTICAL STRENGTH:** The regression-toward-1.0 shrinkage is
  methodologically sound and standard; no internal ablation number was found
  quantifying the lift this specific implementation provides once switched
  on for the market it currently feeds.
- **KNOWN LIMITATIONS:** `strength.py`'s own docstring flags an earlier,
  simpler pricing function that ignored park entirely ("Coors Field is
  priced like Petco"), which this module was built specifically to fix —
  but the fix's effect on live pricing has not been separately measured
  since being turned on.
- **CURRENTLY TREATED AS:** methodologically sound **design convention**,
  correctly reasoned and disclosed as unfitted ("not tuned against any
  result"), currently live in the moneyline/run-line model without a
  matching ablation number for that specific market.

#### B10. Injuries

- **BELIEF:** N/A — **there is no belief here, because there is no feature.**
- **ORIGIN:** N/A.
- **EVIDENCE:** `data/historical/transactions.jsonl` holds real,
  well-timestamped injury/roster history for the full window —
  `docs/planning/map-historical-data-pit.md` §4, quoted: *"27,053 rows,
  2022-04-08..2026-09-01... il_placement 1,768, il_activation 2,554,
  il_transfer 369, rehab 2,279... has a filed_date that could plausibly seed
  a PIT timestamp. But it is wired into nothing: grep... returns only
  `src/research/coverage.py`, `src/pipeline/news.py`, and
  `src/pipeline/rosterwatch.py`... no entry in `pointintime.py`'s INPUTS, no
  detector, no reference in `src/research/matrix.py`."*
- **EXPERIMENT THAT SUPPORTS IT:** N/A — nothing to test; the feature does
  not exist.
- **DATA PERIOD / TARGET / MODEL FAMILY / FEATURE REPRESENTATION / MARKET /
  TIME OF PREDICTION:** N/A.
- **STATISTICAL STRENGTH:** N/A.
- **KNOWN LIMITATIONS:** This is the clearest "NOT FOUND" in the whole
  feature audit — a well-timestamped, full-history data source sitting
  completely unused, flagged by the repo's own planning doc as "the
  highest-leverage low-cost extension in the whole subsystem."
- **CURRENTLY TREATED AS:** N/A. Recorded because its *absence* is itself a
  finding the task asked for: nobody has decided injuries don't matter;
  nobody has tested it either. It is simply not there.

---

### C. Market structure, evaluation process, and cross-cutting beliefs

#### C1. Line movement / momentum vs. reversal

- **BELIEF (tested, and rejected):** Consecutive price changes might be
  negatively autocorrelated (overreaction/reversal, "fade the last move"),
  which the literature suggested as a plausible edge.
- **ORIGIN:** `docs/RESEARCH_V2.md` (M1), commit
  `ff222ab66bbbc6b152c6401ddcb0df8b118249bb`; results in `docs/RESULTS_V2.md`
  §M1, run 2026-08-29.
- **EVIDENCE, exact:** 62,183 consecutive change pairs across 4,087 events,
  measured within each book's own price path (never on a consensus, to
  avoid manufactured mean-reversion). **Lag-1 autocorrelation +0.013**
  (clustered p = 0.13) — positive, not negative, and not significant. Fading
  the move at a 1pp threshold: n=19,250, ROI **−3.5%**, p=0.13; at 2pp:
  n=7,720, ROI **−4.1%**, p=0.25. A post-hoc "follow the move" check loses
  about the same (−3.3%, −2.8%) — "the move predicts nothing either way and
  you pay the spread to find out."
- **EXPERIMENT THAT SUPPORTS IT:** `docs/RESULTS_V2.md` §M1 (NULL, as above).
- **DATA PERIOD:** 2023–24.
- **TARGET:** Price change direction/magnitude; ROI of trading on it.
- **MODEL FAMILY:** N/A — a direct autocorrelation and trading-rule test.
- **FEATURE REPRESENTATION:** Consecutive same-book price deltas.
- **MARKET:** MLB moneyline, all books.
- **TIME OF PREDICTION:** Intraday, pre-close.
- **STATISTICAL STRENGTH:** A real, large-n (62,183 pairs, 4,087 events)
  null with a clean sign, though the document itself flags an honest limit:
  *"The paper had tick-level data; we have four or five snapshots per game.
  If the overreaction happens and resolves inside one of our intervals, we
  cannot see it. This is 'not visible at this resolution', not 'not real'."*
- **KNOWN LIMITATIONS:** Snapshot resolution (median 4-5 per event) is far
  coarser than the tick-level data the literature this hypothesis was drawn
  from used — the null could be a genuine null or an under-sampling
  artifact, and the document says so.
- **CURRENTLY TREATED AS:** **tentative evidence of a null**, honestly
  scoped as resolution-limited rather than overclaimed as "line movement
  carries no information at any resolution."

#### C2. Cross-book dispersion as a value signal — a textbook false positive

- **BELIEF (tested, initially looked real, then killed by its own
  falsification battery):** A book quoting far off the multi-book consensus
  is mispriced and worth betting against.
- **ORIGIN:** `docs/RESEARCH_V2.md` (M3); results `docs/RESULTS_V2.md` §M3.
- **EVIDENCE, exact:** at a 2pp leave-one-out deviation threshold: n=249
  selections (223 events, 162 dates), hit rate 60.6% vs. consensus-implied
  52.2%, **effect +8.49pp, clustered p = 0.0063, 95% CI [+2.34, +14.28],
  ROI +18.1%.** The pre-registered falsification battery then killed it:
  excluding FanDuel alone dropped the effect to +5.53pp at p=0.16 (FanDuel
  alone: +15.49pp; BetMGM alone: **−9.44pp**); it did not replicate across
  seasons (2023: +6.14pp p=0.13; 2024: +11.72pp p=0.016); dose-response was
  non-monotone (the band just below threshold was *negative*); and it
  represents "a 0.4% tail" (249 of 59,297 observations).
- **EXPERIMENT THAT SUPPORTS THE REJECTION:** the falsification battery
  itself, `docs/RESULTS_V2.md:178-201` — a genuine, pre-committed process
  case study in how an 18%-ROI, p=0.006 result gets correctly killed rather
  than shipped.
- **DATA PERIOD:** 2023–24.
- **TARGET:** Hit rate of the flagged book's side vs. its own price.
- **MODEL FAMILY:** N/A — a rule-based screen.
- **FEATURE REPRESENTATION:** Leave-one-out deviation from consensus.
- **MARKET:** MLB moneyline.
- **TIME OF PREDICTION:** ≥6 hours pre-game.
- **STATISTICAL STRENGTH:** Nominally very strong at the headline (p=0.0063,
  tight-looking CI) — precisely why the document leads with *"An 18% ROI
  should trigger suspicion, not celebration."* This is presented, correctly,
  as a demonstration of process discipline rather than a finding.
- **KNOWN LIMITATIONS:** None outstanding — the finding is a confirmed dead
  end, not a live belief.
- **CURRENTLY TREATED AS:** **debunked**, and correctly so. Recorded here
  because a headline number this strong, sitting anywhere else in a betting
  research program without its falsification battery attached, is exactly
  the shape of thing that gets promoted by mistake elsewhere.

#### C3. The V1 card's ranking rule: market confidence, not model confidence

- **BELIEF:** Ranking picks by how confident the *market* is (rather than the
  model, or model-vs-market disagreement) is the conservative, safe choice,
  because the model has only ever shown a 0.0012-nats edge over a base rate.
- **ORIGIN:** `src/analysis/daily_card.py:36-56`.
- **EVIDENCE FOR the underlying caution:** the 0.0012-nats number itself
  (though see Item 4 — this figure's evaluation window is >92% inside the
  sealed period and is quoted, not re-run, post-leak).
- **EVIDENCE AGAINST the *product* consequence of this choice, quoted from
  `docs/CARD_MARKET_BREADTH_FINDINGS.md`:** *"None of this is accidental...
  What it argues for, though, is publishing less, not publishing
  favourites, and the same docstring says so: 'Backing market favourites
  wins a majority of individual bets and still loses money at the vig.'"*
  The system's own reasoning argues against exactly the product it shipped.
  Confirmed independently by Item 5 (Price Band Evidence): 48 of 48 graded
  picks over 6 days were favourites, half beyond the owner's own stated
  price ceiling.
- **EXPERIMENT THAT SUPPORTS IT:** none that measures the *product
  consequence* before shipping — the measurement (`CARD_MARKET_BREADTH_FINDINGS.md`)
  came 24 hours after the card had been live and publishing, prompted by the
  owner looking at the TODAY tab.
- **DATA PERIOD:** Live, 2026-09-09 onward.
- **TARGET:** Which side/market gets published as a pick.
- **MODEL FAMILY:** N/A — a selection rule, not a predictive model.
- **FEATURE REPRESENTATION:** De-vigged market probability (ranking key);
  model probability used only as a same-direction gate.
- **MARKET:** Moneyline (V1 covers only this market; derivatives/props were
  separately ranked-and-ignored, see below).
- **TIME OF PREDICTION:** Card freeze, ~4 hours pre-game.
- **STATISTICAL STRENGTH:** N/A — a design decision, not an empirical claim,
  though its stated justification rests on a number now itself in question
  (Item 4).
- **KNOWN LIMITATIONS, quoted:** *"The system already ranks every market on
  price, and the card ignores it"* — `src/analysis/opportunities.py:361-366`
  already ranks moneylines and derivatives together by price-based
  qualification, and `grep value_points src/analysis/daily_card.py` returns
  nothing: *"The card throws it away."* Real slates measured 2026-09-09/10:
  qualifying-bet counts of 5 and 1, **zero of which were moneylines** — i.e.
  the system's own price-based ranking, when run, found essentially no
  qualifying value in the exact market the card exclusively publishes.
- **CURRENTLY TREATED AS:** this is the belief I judge **least supported
  relative to how confidently it was held** (see Part 0 summary). It was
  treated as a safe, conservative engineering decision and shipped as the
  live public product before its product consequence was measured. The
  measurement, once done, confirmed the system's own internal reasoning had
  predicted the problem in advance and been overridden by the product
  requirement to always publish 3-10 picks a night.

#### C4. Favourite/underdog calibration bias

- **BELIEF (tested twice, both null):** The market is systematically
  miscalibrated on favourites vs. underdogs (either home-team bias or a
  favorite/longshot bias).
- **ORIGIN:** `docs/PREREG_F5_FAMILIES.md` (F5-H1, F5-H2); results
  `docs/F5_RESEARCH_RESULTS.md`.
- **EVIDENCE, exact:** F5-H1 (home-team F5 calibration bias): 2023 screen
  effect **−0.577pp** against a required-positive, 2.0pp-floor direction —
  fails on both sign and floor. F5-H2 (favorite/longshot bias, top/bottom
  terciles of de-vigged favorite probability): bottom tercile **+4.055pp**
  (required negative, observed positive — wrong sign); top tercile
  **−1.663pp** (required positive, observed negative — wrong sign, below
  the 4.0pp floor). **Both F5-H2 extremes failed the pre-registered screen
  on sign alone**, in 2023, before any replication leg was even reached.
- **EXPERIMENT THAT SUPPORTS IT:** `docs/F5_RESEARCH_RESULTS.md` §4
  (discovery/screen-leg outcomes), family `F5_MONEYLINE_CALIBRATION_2026H1`,
  frozen record `data/research/f5/family_frozen.json`.
- **DATA PERIOD:** Discovery 2023-05-10 to 2023-12-31 (n=1,597 gradeable);
  replication window defined as 2024-01-01 to 2024-10-07 (n=2,085) but not
  reached, since the screen-leg pass rule failed first.
- **TARGET:** F5 moneyline calibration error (predicted vs. realized win
  rate by probability bucket).
- **MODEL FAMILY:** Bucketed calibration-error detector (terciles fit on
  2023, frozen, applied to 2024).
- **FEATURE REPRESENTATION:** De-vigged home/favorite implied probability at
  the F5 T-2h snapshot.
- **MARKET:** First-five-innings moneyline.
- **TIME OF PREDICTION:** T-2 hours pre-first-pitch snapshot.
- **STATISTICAL STRENGTH:** A pre-registered family with a stated MDE
  (1.62pp at n=3,682, two-sided 95%, p≈0.5) — both hypotheses failed the
  screen leg outright, on sign, which is a stronger and cheaper rejection
  than a failed replication would have been.
- **KNOWN LIMITATIONS:** This tests only the F5 market, not the full-game
  moneyline directly — a full-game-specific favorite/longshot bias test was
  not separately located in this pass.
- **A number discrepancy worth recording rather than resolving by
  assumption.** A second, independent read of this same document reported
  F5-H1's effect as **−0.884pp, p=0.412609, 95% CI [−2.964pp, +1.318pp]**,
  concluding *"home sides are, if anything, marginally overpriced, not
  underpriced."* My own read took the −0.577pp figure from
  `docs/F5_RESEARCH_RESULTS.md` §4, the **2023 discovery/screen-leg**
  table; the −0.884pp figure most likely comes from a later section
  (replication, or a pooled/final read) of the same document that I did not
  independently re-verify line-for-line against the other pass. Both
  numbers point the same direction (no positive home-team calibration bias
  found; if anything, slightly negative) and neither changes the verdict
  (zero survivors), so this does not change **CURRENTLY TREATED AS** below —
  but per the task's rule to record disagreement rather than smooth it: two
  independent reads of `docs/F5_RESEARCH_RESULTS.md` produced two different
  exact numbers for F5-H1's effect size, and a reader who needs the single
  authoritative figure should re-open that file and confirm which section
  (screen vs. replication vs. pooled) is the one that governs the family's
  registered verdict.
- **CURRENTLY TREATED AS:** **null**, tested twice (home bias, favorite/dog
  bias) in the same pre-registered family, both failing at the screen stage.
  A related owner-driven correction (killing the "home underdog" strategy,
  `SR1`, on 2026-09-16 — "a BEYOND IDIOTIC STRATEGY with no research behind
  it" — band A −3.51pp 2023, band B sign-flipped +7.77→−2.14) is a separate,
  single-factor strategy test that also died, for the same underlying
  reason: no measured calibration bias by favorite/dog status has ever
  survived a test in this repo. `docs/SR1_RESULT_2026-09-16.md` (commit
  `a60beab94133c3f60e34f0ac265674a8f6ed3c57`) is explicit that this kill is
  itself underpowered rather than a strong null, quoted: *"Detecting a real
  +1pp effect would need roughly 19,000 to 54,000 selections per season...
  band A had 528 and band B 138."* So the honest state of "does a
  favourite/underdog price band carry a real bias" is: **tested three
  separate ways (F5-H1, F5-H2, SR1), null or killed every time, but at least
  one of those three tests (SR1) was itself too small to have detected a
  real effect of plausible size even if one existed** — a null that is
  real evidence against the *specific* things tested, not proof the
  underlying idea is false.

#### C5. F5 (first five innings) vs. full game

- **BELIEF:** The F5 market is a clean, separately-eligible universe worth
  its own research family; bullpen fatigue should show up as an F5-vs-
  full-game divergence specifically.
- **ORIGIN:** `docs/F5_UNIVERSE_FROZEN.md` (frozen 2026-09-04),
  `docs/F5_NORMALIZATION_REPORT.md`, `docs/F5_RESEARCH_RESULTS.md`.
- **EVIDENCE:** the eligible universe is frozen and hash-verified (sha256
  `c67508603b14af2c494e13fadeb2a2f039f52df996ab6e12ff6164585e33cd1c` over the
  sorted eligible `game_pk` set) — **4,315 eligible instants, 3,682
  gradeable (OK ∧ decided)**, MDE 1.62pp at n=3,682. `F5_RESEARCH_RESULTS.md`:
  "Status: zero survivors. All three registered members failed their
  pre-registered gates." (F5-H1, F5-H2-bottom, F5-H2-top — see §C4.) Family
  V2's own M4 (F5 vs. full-game bullpen gap) is separately reported as
  **UNDERPOWERED — no signal at n=270** (`docs/RESULTS_V2.md` §M4).
  `ALTERNATIVE_HYPOTHESES.md` H5 proposes the F5/full-game split as a
  **built-in placebo** for a bullpen-fatigue hypothesis that has not yet
  been run at adequate power: *"If a usage feature 'predicts' F5 outcomes as
  strongly as full-game, it is not measuring bullpen fatigue and the result
  is spurious"* — a good, unrun design.
- **EXPERIMENT THAT SUPPORTS IT:** the frozen universe plus the null family
  above; the bullpen-fatigue-via-F5-placebo idea is proposed, not tested.
- **DATA PERIOD:** 2023-05-10 (approved window start) through 2024-10-07.
- **TARGET:** F5 moneyline win/loss.
- **MODEL FAMILY:** Bucketed calibration detectors (tested); a
  feature-engineering test (proposed, H5, untested).
- **FEATURE REPRESENTATION:** De-vigged F5 implied probability.
- **MARKET:** First-five-innings moneyline.
- **TIME OF PREDICTION:** T-2 hours.
- **STATISTICAL STRENGTH:** The frozen-universe infrastructure and MDE
  calculation are rigorous; the two tests actually run on it (F5-H1/H2, M4)
  are both null/underpowered.
- **KNOWN LIMITATIONS:** M4's underpowered result (n=270) means "F5 doesn't
  show a bullpen gap" is not established — it was never adequately tested,
  only attempted.
- **CURRENTLY TREATED AS:** the *infrastructure* (frozen universe, exclusion
  ledger) is **fact**, hash-verified. The *substantive claims* tested on it
  (home bias, favorite/dog bias) are **null**. The most promising specific
  F5 idea (bullpen-fatigue-via-placebo) remains an **untested proposal**,
  correctly labeled as such by `ALTERNATIVE_HYPOTHESES.md` rather than
  quietly assumed.

#### C6. The 300-pick / 60-date evaluation floor as applied to actual product decisions

- See Item 3 above for the floor's own derivation status. This entry records
  how it interacts with what has actually shipped: as of 2026-09-17, **48
  graded picks over 6-7 days** is the entirety of the live record (Item 5),
  **16% of the pick floor and 10% of the date floor.** No verdict of any
  kind — CLV, ROI, or otherwise — is currently licensed by the project's own
  rule, and the project's own documents (Item 5) correctly say so.
- **CURRENTLY TREATED AS:** correctly treated as **insufficient for any
  verdict**, by the system's own documents. Recorded here as a cross-check
  that the floor is being honored in practice, not just declared on paper —
  as of this audit, it is being honored.

#### C7. Props: a genuinely informative model that still loses to the price

- **BELIEF:** The batter-prop model (`batter_hits`, etc.) is well-calibrated
  and informative in an absolute sense, but disagreeing with the market's
  own prop price is not a profitable signal.
- **ORIGIN:** `docs/DOES_THE_MODEL_BEAT_THE_MARKET.md` item 2;
  `docs/EDGE_SEARCH_2026-09-10.md`; `docs/PROP_CALIBRATION_2026-09-14.md`.
- **EVIDENCE, exact:** model vs. base rate, no price involved, 16,741 batter
  games: `batter_hits` over 0.5 **+0.01334** nats, within 0.8 points of
  calibration — "3.3× the team moneyline model's entire gain" and "the
  strongest positive result the project has." Against the market:
  `scripts/probe_prop_value.py`, flagged-edge-≥3pts arm n=82, won 43.9%, ROI
  **−16.6%** [−37.5, +4.4], vs. control (every over) n=1,107, won 48.9%, ROI
  **−9.1%** [−14.8, −3.3] — "selecting on our own edge did worse than not
  selecting at all." `PROP_CALIBRATION_2026-09-14.md`'s reliability check
  found the market's own de-vigged number is **slightly better calibrated
  overall** (Brier 0.24057 vs. our 0.24687) and dramatically better on the
  specific 10+ point disagreement slice (n=32: market called it 50.2%
  overconfident by 9.6 points, we called it 62.1% overconfident by 21.5
  points, actual hit rate 40.6%).
- **EXPERIMENT THAT SUPPORTS IT:** `scripts/backtest_player_props.py`
  (16,741 games), `scripts/probe_prop_value.py` (Bonferroni-corrected,
  pre-registered), `scripts/probe_prop_calibration.py`.
- **DATA PERIOD:** 16,741 batter games (unspecified exact range, described
  as the largest sample in the project) for the model-vs-base-rate result;
  2026-09-03 to 09-14 (5-8 calendar dates depending on cut) for the
  vs.-market calibration comparison.
- **TARGET:** `batter_hits`, `batter_total_bases`, and related over/under
  outcomes.
- **MODEL FAMILY:** Rate-based prop model (`src/analysis/playerprops.py`),
  beta-binomial with fitted intra-class correlation `RHO` (§B-adjacent, see
  below).
- **FEATURE REPRESENTATION:** Season batter rate, pitcher factor, lineup
  slot (where available), park/weather/recent-form explicitly **not**
  wired in (`playerprops.py:66-68`: "No platoon split... No park factor").
- **MARKET:** Player props.
- **TIME OF PREDICTION:** Pre-lineup and post-lineup variants both exist;
  production runs pre-lineup by owner instruction.
- **STATISTICAL STRENGTH:** The model-vs-base-rate result is large-sample and
  robust; the vs.-market results are pre-registered and Bonferroni-corrected,
  and both directions (over/under) come back negative or null.
- **KNOWN LIMITATIONS:** `DOES_THE_MODEL_BEAT_THE_MARKET.md` names the fix
  list explicitly and it remains largely undone: lineup slot (partially
  used), platoon splits (captured, unused — `data/historical/handedness.json`),
  park and weather (captured, unused in this model), recent form (not used).
  "Player-level data exists for 2026 only. There is no sealed holdout for any
  prop-model constant... tuned in-sample and their gains are optimistic."
- **CURRENTLY TREATED AS:** the model's raw informativeness is **strong
  evidence** (large n, real, positive, well-calibrated in the aggregate). Its
  ability to beat a live market price is **tested and null**, in both
  directions, with a mechanism given for why (the market has lineup/platoon/
  park/weather/recent-form information the model does not).

#### B22. `DISPERSION = 2.3352` and `RHO = 0.05065` — the calibration constants

- **BELIEF:** MLB team runs are overdispersed relative to Poisson by a factor
  of ~2.3×, and batter hit outcomes within one game are positively
  correlated (intra-class correlation ~0.05), and correcting for both
  materially improves calibration.
- **ORIGIN:** `docs/PREREG_RUN_DISPERSION.md`, commits
  `8da443f485b0ff0de6b414e3782c12fcf4d2c0b4` (pre-registration),
  `130d1a348266b56258967c8e46bcc8f8ddfe6041` (adoption); `RHO`:
  `src/analysis/playerprops.py:522-548`, adopted under
  `scripts/test_prop_dispersion.py`.
- **EVIDENCE — the fuller story, because a skim understates how well-tested
  this one is.** The *first* pre-registration (H1) fit `DISPERSION = 2.3352`
  on 2026-04-15..07-15 and checked it held-out from 2026-07-16: calibration
  error fell 92.6% (NB1) to 93.5% (NB2), moneyline log-loss *improved* by
  0.0034 nats (three times the model's entire gain over a home-field base
  rate). **It was still REFUSED** — a pre-registered stability check (fitted
  dispersion must not drift more than 0.30 between fit-window halves) failed
  at 0.3151. Quoted: *"The threshold is not moving... Rescue by threshold
  change is the single thing this project's research discipline exists to
  prevent."* A **second, independent** registration (H3) then estimated
  dispersion from scratch on the entirely separate 2025 season (2,212 games,
  ingested after H1 ran): **2.3265 (se 0.0682, 4,372 team-games)** against
  2026's 2.3352 — **0.128 standard errors apart.** Applying the 2026 value
  unchanged to 2025 cut run-line calibration error 88.2% and improved
  moneyline log-loss by 0.0065 nats, roughly seven times the model's entire
  base-rate gain. The document is explicit about its own earlier mistake,
  quoted: *"The criterion was underpowered, and that is my error, not the
  data's. I set a 0.30 drift limit without first computing the estimator's
  precision... A pre-registration is only as good as the power calculation
  behind it, and this one had none."* `RHO = 0.05065` (fit 2026-06-17..08-05,
  n=7,665 batter games; tested from 2026-08-06, n=9,076) cut a four-point
  systematic prop overconfidence to four tenths of a point, with log-loss
  also improving rather than trading off.
- **EXPERIMENT THAT SUPPORTS IT:** two independent pre-registrations on two
  independent seasons for `DISPERSION`; one pre-registered fit/test split for
  `RHO`.
- **DATA PERIOD:** `DISPERSION`: 2026-04-15..07-15 (fit, H1), 2026-07-16
  onward (check, H1), 2025 full season (independent refit, H3) — **the H1
  fit and check windows sit inside the 2026-01-01..08-27 sealed window**,
  per Item 4. `RHO`: 2026-06-17..08-05 (fit), 2026-08-06 onward (test) —
  also inside the sealed window.
- **TARGET:** Run-line calibration error; moneyline log-loss; batter-hits
  calibration error.
- **MODEL FAMILY:** Negative-binomial (NB1) run distribution; beta-binomial
  count distribution for props.
- **FEATURE REPRESENTATION:** N/A — these are distributional shape
  parameters, not predictive features.
- **MARKET:** Run line, moneyline (via `strength.py`); `batter_hits` props.
- **TIME OF PREDICTION:** N/A (a model-shape constant, applied at call
  time).
- **STATISTICAL STRENGTH:** unusually strong for this codebase — two
  independent-season estimates agreeing to 0.128 SE for `DISPERSION`, with an
  honest account of an earlier refusal and *why* that refusal's own
  criterion was under-powered.
- **KNOWN LIMITATIONS:** the specific number **currently running in
  production** (2.3352) is still the one fit partly on sealed-window data,
  per Item 4 — the independent 2025 replication *confirms the finding* but
  does not itself replace the production constant. Card V2's registration
  (§1.2) discards both constants and refits fresh on 2025 alone for exactly
  this reason, even though, on the evidence here, the underlying claim is
  probably right.
- **CURRENTLY TREATED AS:** the substantive claim ("baseball runs are
  overdispersed by about this much") is **strong evidence**, better
  replicated than almost anything else in this codebase. The specific
  production constant's *provenance* is nonetheless a **sealed-window
  breach** per Item 4's own accounting, which is why V2 does not carry it
  forward unchanged. Flagged in Part 0 specifically because this is the
  rare case where the coordinator's suspicion ("fitted once, never
  re-checked") turns out to be the opposite of what happened — it was
  fitted once, refused once, and re-checked independently on held-out data
  from an entirely different season.

#### C8. `MIN_BOOKS` floors (6 for game consensus, 2 for props)

- **BELIEF:** A consensus needs at least 6 books (game markets) or 2 books
  (props, both sides) before it is treated as a real market number rather
  than "that handful's opinion."
- **ORIGIN:** `src/analysis/prices.py:29-31`, commit `387c32c40`,
  2026-08-31; `src/analysis/propboard.py:87`, commit `b4df5e28d`,
  2026-09-11.
- **EVIDENCE:** `prices.py`'s own comment, quoted in full: *"A consensus
  over fewer books is that handful's opinion, not a market's. Same floor as
  everywhere else in the system."* `propboard.py`'s comment is nearly
  identical in structure: *"Two books quoting BOTH sides before a contract
  has a fair price at all. Same floor and the same reason as
  `scripts/_propboard.py`."* Both justifications point at *each other* /
  at their own reuse elsewhere in the system, not at any external
  measurement of how consensus quality changes with book count.
- **EXPERIMENT THAT SUPPORTS IT:** none found. Checked
  `docs/BETA_GAP_ASSESSMENT.md`, `docs/EVOLAB_PHASE0_FEASIBILITY.md`, and
  the design-planning docs that cite `MIN_BOOKS = 6` — all of them **cite**
  the constant as an existing fact ("MIN_BOOKS = 6 exists for a reason");
  none of them **derive** it.
- **DATA PERIOD / TARGET / MODEL FAMILY / FEATURE REPRESENTATION / MARKET /
  TIME OF PREDICTION:** N/A — a data-quality floor, not a predictive claim.
- **STATISTICAL STRENGTH:** none — no measurement of consensus stability
  as a function of book count (5 vs. 6 vs. 8) was found anywhere in the
  repo.
- **KNOWN LIMITATIONS:** `design/linehound-v2/CAPABILITY_LEDGER.md:86`
  documents the floor is a real, live constraint, not theoretical: at one
  measured instant, 3 of 27 games fell below the floor; across 790 stored
  game-instants, the median book count is 8 and 6.5% fall below the floor
  entirely (`consensus: null`). So the choice of 6 has a real, measured
  *cost* (how often it produces "no consensus") even though its *benefit*
  (why 6 rather than 5 or 7) was never measured.
- **CURRENTLY TREATED AS:** a **design convention**, self-reinforcing across
  the codebase by citation ("same floor as everywhere else") rather than by
  independent derivation anywhere. Reasonable on its face; never tested.

#### C9. Selection effects and multiplicity control across time (not just within one family)

- **BELIEF, as documented policy:** "FDR over the full pre-registered
  family" and a family-wise multiplicity budget prevent false survivors from
  a large search.
- **ORIGIN, as a live self-audit:** `docs/STRATEGY_LAB_REFUTATION_2026-09-15.md`
  (commit `ed801a856e4b0789de25c4a213b5572335254dfb`), an adversarial
  internal review of `docs/STRATEGY_LAB_PLAN_OF_RECORD.md`.
- **EVIDENCE this is currently NOT enforced across sweeps, quoted directly:**
  §3, *"The family-wise bar across sweeps does not exist in code... It is
  not judged against it — it is cited next to it. `alpha_registry.py`'s
  docstring: `total_searched()` 'is what a new family's pre-registration doc
  and the falsification battery are expected to cite.' `gates.py` G5 checks
  only `effective_tests_reported` — a boolean that the number was printed.
  `fitness.py` validates `multiplicity_charge >= 0.0` and nothing else...
  `ALPHA_REGISTRY_DESIGN.md` says it plainly: 'Nothing accumulates search
  effort ACROSS families and sweeps over calendar time.'"* The refutation
  computes the consequence explicitly: at one sweep/day × 3 sports × 3
  markets (~270 sweeps/month), each with a structural ~10% null-survivor
  rate under BH q=0.10 and no rising threshold across sweeps, **expected
  false survivors ≈ 27/month.**
- **A second, related finding from the same review, §2:** the plan's own
  claim that "chance alone produces ~0.01 p-values" (therefore making BH
  survival at ~0.0008 look extra-safe) is mathematically backwards: *"The
  minimum of n null p-values is ~Exp with mean 1/(n+1). Over 120 nulls the
  expected smallest p is 0.0083 — but P(min p ≤ 0.0008) = 1 − (1−0.0008)^120
  ≈ 9.5%. That is not an accident; it is q. BH at q=0.10 is designed to let
  roughly one in ten pure-null sweeps emit a survivor. The plan states the
  opposite of its own procedure's guarantee."*
- **A third, directly on-topic finding, §9 (survivorship / selection
  effects in the live paper-trading design):** *"Freezing at bust makes the
  30/60/90-day panels censored. A busted path has no 90-day ROI; if it is
  dropped, the 90-day median is conditioned on survival and biased upward —
  exactly the survivorship the sentence claims to avoid."*
- **A fourth finding, independently confirming this is a live, previously
  shipped defect rather than only a hypothetical one:**
  `docs/planning/attack.md:50-58` (commit
  `3848931dd6bb97886651ff7a2b5e295ab77c1ad1`, 2026-09-03), an earlier
  self-audit, found the evolution-lab's own **placebo ceiling** — the
  instrument built specifically to guard against exactly this kind of
  selection effect — was itself computed wrong in a selection-biased way,
  quoted: *"the placebo ceiling is computed against a null that does not
  contain the board-wide argmax, so board expansion mechanically manufactures
  ceiling clears... the statistic actually scored is `max` over up to forty
  correlated per-selection statistics, and the max of forty has an
  expectation strictly above any one of them."* This is a second, separate
  instance of a selection effect contaminating the very tool meant to
  detect selection effects, found and fixed (per the Phase 2B generator
  amendments discussed under Item 1) before it shipped — good evidence the
  project does catch these when it looks, and equally good evidence that it
  has needed to catch this specific class of bug more than once.
- **EXPERIMENT THAT SUPPORTS IT:** the refutation document itself is the
  experiment — a structural, arithmetic demonstration, not an empirical
  test on data, but a rigorous one.
- **DATA PERIOD:** N/A (a process/design critique).
- **TARGET:** N/A.
- **MODEL FAMILY:** N/A.
- **FEATURE REPRESENTATION:** N/A.
- **MARKET:** All (the plan under review covers MLB, NFL, and tennis
  sweeps).
- **TIME OF PREDICTION:** N/A.
- **STATISTICAL STRENGTH:** the arithmetic is straightforward and correct
  (a standard order-statistics fact about the minimum of uniform p-values
  under the null); this is not a judgment call.
- **KNOWN LIMITATIONS:** as of this audit, it is unknown whether the
  refutation's recommended fixes (a fixed, declared family-wise budget with
  a gate that fails a sweep registered past the declared count; carrying
  busted paths forward at their terminal value) have been implemented — this
  was not independently checked against current `gates.py`/`fitness.py` for
  this document.
- **CURRENTLY TREATED AS:** this is the one belief in this map where the
  system's **stated policy and its actual enforcement are shown, by the
  system's own internal review, to currently diverge** — "FDR over the full
  pre-registered family" is true *within* one sweep and *not currently true*
  *across* sweeps and calendar time. This is not a case of an unexamined
  assumption; it is a case of an examined assumption found wanting, with the
  fix specified but (as far as this audit could confirm) not yet shipped.

#### C10. The V1 calibration leak's downstream effect on "does the model beat the market"

Cross-reference to Item 4. The specific chain: `daily_card.py`'s ranking
justification (0.0012 nats) → depends on a walk-forward window that is
>92% sealed-window data → the sealed window's "one evaluation ever" property
is compromised by repeated nightly reads → any future claim that reuses this
specific evaluation inherits that compromise. `docs/DOES_THE_MODEL_BEAT_THE_MARKET.md`'s
five measurements are the one place in the repo verified (by direct code
reading of `backtest_card_rule.py` and `backtest_card.py`) to be
methodologically independent of this specific leak, because they fit their
own internal walk-forward calibration rather than reading the live
`card_calibration.json`.

- **CURRENTLY TREATED AS:** see Item 4's per-belief downgrade table above.
  Recorded again here only to make explicit that "does the model beat the
  market" (§A2) and "should the card rank by market confidence" (§C3) both
  cite a number that is now qualified, and neither citation has been
  re-run since.

#### C11. Market timing conventions (when, relative to first pitch, a prediction is made)

- **BELIEF:** There is a coherent, product-wide convention for when a
  prediction is "made" relative to first pitch.
- **ORIGIN:** No single document states one convention; practice varies by
  market. `docs/CARD_PUBLISH_WINDOW.md` documents the moneyline/run-line
  card is meant to freeze ~4 hours before the earliest game, and that the
  live cron missed this on roughly one day in five historically. Player
  props are explicitly priced **before** lineup confirmation by owner
  instruction (`require_lineup=False`, 2026-09-14).
- **EVIDENCE:** These are two different, both-documented, but
  **not-reconciled-in-one-place** conventions — a reader has to assemble
  them from `daily_card.py`'s disclaimer, `CARD_PUBLISH_WINDOW.md`'s audit,
  and `best_bets_card.py`'s `RuleParams` default to learn that "before first
  pitch" means something different (and, for game picks, was sometimes
  violated) depending on the market.
- **EXPERIMENT THAT SUPPORTS IT:** `ALTERNATIVE_HYPOTHESES.md` H1 explicitly
  proposes testing whether the *pre-close window itself* (as opposed to the
  close) carries exploitable information from lineup/scratch/bullpen news
  landing between roughly four hours and 30 minutes pre-game — this is
  proposed, not yet run.
- **DATA PERIOD / TARGET / MODEL FAMILY / FEATURE REPRESENTATION:** N/A (a
  process convention, not itself a tested claim, except where H1 tests it).
- **MARKET:** All.
- **TIME OF PREDICTION:** This is the belief under discussion.
- **STATISTICAL STRENGTH:** N/A for the convention itself; H1 (untested) is
  where a statistical test of "is the pre-close window informative" would
  live.
- **KNOWN LIMITATIONS:** `CARD_PUBLISH_WINDOW.md`'s historical violation
  (cards sometimes publishing after first pitch) directly contradicts the
  product's own disclaimer and was not independently re-verified as fixed
  for this audit.
- **CURRENTLY TREATED AS:** an **inherited, unreconciled set of
  conventions** rather than one documented rule — accurate in each
  individual place it is stated, not assembled anywhere into a single
  cross-market statement, and with one documented historical violation of
  its own stated version.

#### C12. Opening vs. closing price as distinct informational objects

- **BELIEF:** Closing price is the correct, and only, anchor for evaluating
  this system (CLV, log-loss vs. market); opening price is deliberately
  excluded from that role, and is not used anywhere as a predictive feature
  in its own right.
- **ORIGIN:** `docs/REVENUE_PLAN.md:104-105` (commit
  `dd0be7f13501eeb568d3bd79a1111a45b6c800a4`, 2026-09-08), quoted: *"positive
  closing-line value measured against the closing consensus, not against our
  own opening price."*
- **EVIDENCE:** confirmed by a second, independent research pass: no
  production code path was found treating opening price as a signal
  distinct from the close (a repo-wide check found none). The one place
  opening-to-close *behavior* is tested at all is
  `docs/RESULTS_V2.md` §M1 (line movement, §C1 above) — which measures the
  *path* from open-ish snapshots to close, not "opening price" as a
  standalone feature. The external literature this project cites for why
  opening-to-close movement might matter
  (`docs/RESEARCH_V2.md:64-66`: "Management Science (2024), 3,681 MLB games
  across four books... price changes are significantly negatively
  autocorrelated, sufficient to reject weak-form efficiency") is a citation
  of someone else's finding, and this project's own internal test of the
  same idea (§C1, M1) found the **opposite sign** (weak positive momentum,
  not negative) at its own coarser sampling resolution — attributed
  honestly to resolution rather than treated as a refutation of the cited
  paper.
- **EXPERIMENT THAT SUPPORTS IT:** none tests "opening price" as a
  standalone predictive object; §C1's M1 is the closest adjacent test, and
  it is about the *path*, not the *opening snapshot* itself.
- **DATA PERIOD:** 2023–24 (for M1); N/A for the design choice itself.
- **TARGET / MODEL FAMILY / FEATURE REPRESENTATION:** N/A — a design
  convention, not a modeled claim.
- **MARKET:** All (the closing-anchor convention is universal); F5 opening
  lines are separately confirmed to exist and be purchasable from about
  T-12h (`docs/PURCHASE_SPEC_F5_PROPS.md:165-183`), i.e. the data to test
  this properly is buyable but has not been bought for this purpose.
- **TIME OF PREDICTION:** N/A.
- **STATISTICAL STRENGTH:** N/A for the design choice; M1's null (§C1) is a
  real, if resolution-limited, test of the adjacent movement question.
- **KNOWN LIMITATIONS:** the project's own historical odds-capture cadence
  (median 4-5 snapshots per event per `RESULTS_V2.md`; "177 minutes" finest
  gap per `ALTERNATIVE_HYPOTHESES.md` H11) may be too coarse to resolve a
  genuine opening-vs-closing information question even if one were run
  directly.
- **CURRENTLY TREATED AS:** the closing-anchor choice is a well-justified
  **design convention** (closing price is the standard, defensible anchor
  for CLV in the professional-betting literature this project cites
  elsewhere). The stronger claim — that opening price carries no
  *additional* information the model could use — is correctly labeled by
  the repo's own hypothesis registry (`ALTERNATIVE_HYPOTHESES.md` H11) as
  **untested and open**, not assumed either way.

#### C13. Nonlinear interactions and matchup-specific effects

- **BELIEF:** Untested in production; proposed as the most likely place a
  real edge could still exist, precisely because Phase 2A (Item 1) tested
  only a linear, additive representation.
- **ORIGIN:** `ALTERNATIVE_HYPOTHESES.md` H3 ("Team averages are efficient;
  arsenal × lineup mismatches are not") and H7 ("Static ratings fail; latent
  dynamic state succeeds").
- **EVIDENCE:** Phase 2A (Item 1) is explicit that it tested "linear-in-the-
  features" only, and that this is "the single most obvious limitation and
  the most obvious follow-up" alongside feature staleness. H3 proposes a
  matchup-embedding / matrix-factorization representation over pitcher
  arsenal × batter vulnerability, with a stated falsification design
  (residualize on both marginals first, then test whether the interaction
  term adds anything — "if it does not, H3 dies and takes a large family
  with it"). H7 proposes state-space/dynamic-Elo latent strength as
  distinct from every static model tested so far, explicitly noting
  *"Would reopen team-level modelling that Phase 2A appeared to close,
  because Phase 2A tested a STATIC linear form."*
- **EXPERIMENT THAT SUPPORTS IT:** none run — both are registered as
  proposals in the hypothesis document, not as completed tests. A second,
  independent research pass confirms this at the code level: a repo-wide
  search for gradient-boosting, xgboost, lightgbm, or neural-network code
  returns **zero hits anywhere in `src/`.** The one implemented model
  (`src/model/logistic.py`) is deliberately kept linear, and its own module
  docstring states why, quoted: *"1. It produces naturally calibrated
  probabilities... 2. It is interpretable... 3. It is hard to overfit with
  regularization and few features. With ~2,000 rows, a flexible model would
  happily memorize the season. A more flexible model earns consideration
  only after this one has been beaten honestly on held-out data."* The
  "interaction" terms that do exist in the feature set
  (`lineup_platoon_share`, `top_minus_bottom`,
  `stacked_top_vs_groundballer`, `src/engine/features.py:297`) are
  hand-engineered multiplicative/composite features fed **into** the linear
  model, not interactions a nonlinear model has learned on its own.
- **DATA PERIOD / TARGET / MODEL FAMILY / FEATURE REPRESENTATION / MARKET /
  TIME OF PREDICTION:** as specified in the proposals (H3: pitcher props
  first, post-lineup, matchup embedding; H7: sides/totals, any timing,
  state-space).
- **STATISTICAL STRENGTH:** N/A — untested.
- **KNOWN LIMITATIONS:** both proposals flag their own overfitting risk as
  HIGH (H3: "interaction space is enormous... screening must be principled,
  not exhaustive"; H7: "evolution variance is a tempting knob").
- **CURRENTLY TREATED AS:** correctly labeled as an open, prioritized
  research direction rather than either an established finding or a
  dismissed one — and this is now cross-checked at both the document level
  (the hypothesis registry) and the code level (no nonlinear model exists
  anywhere to have quietly tried and buried this). Recorded because it is
  the most direct rebuttal to any temptation to over-read Phase 2A's linear
  null as "nothing in our features works": the honest state is "an
  explicit, reasoned choice to stay linear for now, with the reasoning
  written down, and the next step named but not yet taken."

#### C14. Calibration methodology, generally

- **BELIEF:** Platt scaling (`a`, `b`) applied to the raw run model's
  probability, refit against historical outcomes, produces a trustworthy
  live probability.
- **ORIGIN:** `src/report/card.py: load_calibration`;
  `data/processed/card_calibration.json`.
- **EVIDENCE:** on the 2026 season, `b` has run near 0.5, meaning "the raw
  model's stated confidence is roughly twice what its accuracy earns"
  (`docs/CARD_CALIBRATION_FREEZE_2026-09-15.md:29-32`) — i.e. the
  calibration layer is doing real, substantial work, not a cosmetic
  adjustment.
- **EXPERIMENT THAT SUPPORTS IT:** a second, independent research pass adds a
  cleaner version of this evidence than the nightly-refit record does:
  `src/analysis/calibrate.py` (per `docs/THE_CARD.md:149`) "fits Platt
  scaling walk-forward — to calibrate a game on date D it uses only games
  that finished strictly before D," and a dedicated out-of-sample check,
  `scripts/test_calibration_still_helps.py`, "fits Platt once on 2025 and
  applies it to 2026, so the fit never sees a game it is scored on":
  **raw log-loss 0.688326 vs. calibrated 0.687946 on 2026** — quoted,
  *"Calibration helps by +0.00038 nats."* This is a genuinely clean,
  cross-season, walk-forward-correct test of the *mechanism*, separate from
  and better-evidenced than the nightly-refit process that produced the
  Item 4 leak. `docs/THE_CARD.md:151-153` separately quotes the full-season
  fit as landing at **b ≈ 0.51**, consistent with the ≈0.5 figure cited
  above.
- **DATA PERIOD:** 2026-04-15 onward, refit nightly through 2026-09-15, now
  frozen at the 2026-09-15T21:04Z value (`a=0.028644`, `b=0.735183`, n=1911);
  the separate cross-season mechanism check used 2025 (fit) → 2026 (scored).
- **TARGET:** Raw model probability → calibrated probability.
- **MODEL FAMILY:** Two-parameter Platt (logistic) scaling.
- **FEATURE REPRESENTATION:** N/A (a post-hoc probability transform).
- **MARKET:** All markets `strength.py` feeds.
- **TIME OF PREDICTION:** N/A (applied at call time to whatever probability
  the run model produces).
- **STATISTICAL STRENGTH:** VALIDATION_CRITERIA's own secondary criterion
  ("calibration holding up live," ECE ≤0.03 pass / >0.06 fail; live-vs-
  backtest drift ≤0.02 pass / >0.04 fail) has not, as far as either research
  pass on this audit found, ever actually been computed and reported against
  a live record — confirmed independently by a second pass's repo-wide
  search for "ECE" outside `VALIDATION_CRITERIA.md` and the SR1 files, which
  returned nothing measuring it against these thresholds. This is a
  **pre-registered criterion that is currently unexercised**, not merely
  unexercised since the freeze — it appears to have never been run at all.
  Item 5's own addendum separately proposes a related, narrower test (frozen
  days vs. leaky days) without yet having enough data to answer it.
- **KNOWN LIMITATIONS:** see Item 4 in full.
- **CURRENTLY TREATED AS:** the *mechanism* (raw model needs calibration,
  roughly by half, and genuinely helps out-of-sample when fit correctly) is
  **strong evidence** — directly, repeatedly measured, including a clean
  cross-season check independent of the Item 4 leak. The *specific
  production record*'s own accuracy is an **open question**, downgraded from
  "working" to "unverified since it stopped moving," per Item 4. And the
  project's own pre-registered live-ECE gate for catching exactly this kind
  of drift is a **design convention that has never been exercised** —
  written down, never run.

---

## Part III — Quick-reference table

| # | Belief | Currently treated as |
|---|---|---|
| A1 | Closing-market efficiency (MLB moneyline) | Strong evidence (practical posture); inherited assumption (the specific "close is efficient" claim, imported externally) |
| A2 | Incremental information beyond price exists | Strong evidence of absence, correctly scoped |
| A3 | "Market-residual modeling" as production architecture | N/A — not actually production; a one-off research technique |
| A4 | Production model identity (strength.py vs. orphaned logistic model) | True fact, nowhere consolidated in one document |
| A5 | CLV as primary metric (the choice itself) | Design convention (uncited but standard statistical rationale) |
| A6 | Edge threshold (MARKDOWN=0.038, BASE_EDGE=0.010) | **Treated as a measured threshold; rests on a design convention its own source document explicitly disclaims as "not a standard error"** |
| A7 | EV calculation and its non-use as a promotion criterion | Fact (enforced by tests) for the rule; dormant risk for the dead code |
| B1 | Specific pitching metrics (FIP) | Strong evidence (tested, near-null discrimination, real calibration gain) |
| B2 | Bullpen effects | Design convention (mechanism) + tentative/null (predictive test) |
| B3 | Recent form (RECENT_STARTS=3) | **Treated as settled convention; rests entirely on an unexamined "common horizon" claim** |
| B4 | Hitter splits / platoon | Fact (leakage avoidance) + null (predictive value, tested 3 ways) |
| B5 | Starter effects generally | Strong prior, directly tested and not supported for two representations; untested for interactions |
| B6 | Weather | Correctly labeled UNPROVEN in code itself |
| B7 | Lineup information | Tentative evidence (value) + inherited assumption (historical timing safety) |
| B8 | Home/away (HOME_FIELD_RUNS=0.20) | **Treated as a model constant with the weight of fact; rests on an external, uncited-in-repo, unablated convention** |
| B9 | Park effects | Design convention, methodologically sound, unablated for the market it currently feeds |
| B10 | Injuries | N/A — no feature exists despite full-history data sitting unused |
| C1 | Line movement (momentum/reversal) | Tentative null, resolution-limited |
| C2 | Cross-book dispersion as value | Debunked — a documented false-positive case study |
| C3 | Rank by market confidence, not model | **Least-supported belief in this map relative to confidence held** — shipped as product before its consequence was measured |
| C4 | Favourite/underdog calibration bias | Null, tested twice in F5; the related SR1 trading test (both bands) killed but explicitly underpowered |
| C5 | F5 vs. full game | Fact (infrastructure) + null (tests run) + untested (best proposal) |
| C6 | 300-pick/60-date floor in practice | Correctly honored — no verdict drawn at 48/6-day sample |
| C7 | Props: informative model, unprofitable disagreement | Strong evidence (both halves) |
| B22 | DISPERSION / RHO | Strong evidence (better-replicated than most); production constant's specific provenance is a sealed-window breach |
| C8 | MIN_BOOKS floors (6, 2) | **Treated as settled; rests on circular self-citation, never independently derived** |
| C9 | Selection effects / FDR across sweeps | **Examined and found currently unenforced by the system's own internal review — not an unexamined assumption, but a known, unresolved gap, and one the project has hit twice** |
| C10 | V1 leak's effect on "beats the market" | Downgraded, see Item 4 |
| C11 | Market timing conventions | Inherited, unreconciled set of per-market rules; one documented historical violation |
| C12 | Opening vs. closing price | Closing-anchor convention well-justified; the stronger "no extra information in the open" claim correctly labeled open/untested |
| C13 | Nonlinear interactions | Correctly labeled open/untested at both the document and code level (zero nonlinear models exist in `src/`); a deliberate, reasoned, disclosed choice |
| C14 | Calibration methodology (Platt scaling) | Strong evidence (mechanism, confirmed by an independent cross-season test); the live-ECE gate meant to catch drift has never been run at all |

Bold rows mark the six beliefs referenced in Part 0 as facts-on-conventions.

**Also worth a line of its own:** the "60 ledger dates" figure discussed
under Item 3 is not a belief with weak evidence — it is a plain citation
error in `docs/ROADMAP.md:765`, which credits `docs/VALIDATION_CRITERIA.md`
with a number that document does not contain. Recorded in Part 0 and Item 3,
not repeated in this table because it is a documentation defect rather than
an evidentiary one.

---

## Part IV — Closing notes

All five dispatched research passes returned before this document was
finalized (the fifth landed after the first draft was written; its findings
— principally the "60 ledger dates" misattribution below, the F5-H1 number
discrepancy in §C4, and additional confirmation for C9, C12–C14 — were
folded into Parts I–III above rather than appended separately, so those
sections now reflect cross-checked reads, not single-pass ones).

**Counts, as requested:**

- **34 beliefs mapped** (Part II), plus the **5 specific historical items**
  given dedicated precise treatment in Part I (two of which, Items 1 and 2,
  are also cross-referenced as beliefs A3/B5 and B4/B5 respectively).
- **6 beliefs treated with more confidence than their basis supports** —
  A6 (edge threshold), B3 (recent-form window), B8 (home-field constant),
  C8 (MIN_BOOKS floors), and the 300-pick/60-date floor's *specific numbers*
  (Item 3) — each a genuine design convention wearing the operational
  authority of a fitted or derived quantity. A6 is the sharpest case,
  because its own source document explicitly disclaims it ("not a standard
  error... not called one") in the same breath that the rest of the
  codebase treats it as a hard gate.
- **1 belief examined by the system itself and found to be currently false
  in practice** rather than merely under-justified: C9, the family-wise FDR
  budget across sweeps and calendar time — with a second, independent
  instance of the same class of bug (the placebo ceiling's own selection
  effect, `docs/planning/attack.md`) found and fixed earlier in the
  project's history, suggesting this is a recurring failure mode for the
  research program rather than a one-off.
- **1 outright documentation defect worth flagging on its own, distinct from
  an evidence gap:** the "60 ledger dates" figure commonly cited alongside
  `VALIDATION_CRITERIA.md`'s 300-pick floor is not in that file at all. It is
  a real number from a different, older gate
  (`docs/ARCHITECTURE_BETTING_ENGINE.md`'s "G6 Forward," a per-strategy
  forward-promotion gate), misattributed to `VALIDATION_CRITERIA.md` by
  `docs/ROADMAP.md:765` and then repeated by citation across seven further
  documents. This task's own framing ("the 300 graded picks / 60 ledger
  dates floor" as if it were one document's rule) reproduces that same
  misattribution — worth correcting going forward: `PREREG_CARD_V2.md`
  separately and correctly registers its own 300/60 floor for the V2 rule,
  which does not depend on the misattribution and stands on its own.
- **The single belief I judge least supported relative to how confidently it
  was held:** C3, the V1 card's decision to rank picks by market confidence
  rather than model confidence or price. The reasoning behind it was sound
  and honestly written into the code's own docstring — but that same
  docstring, read one paragraph further, already predicted the exact
  failure mode ("wins a majority of individual bets and still loses money at
  the vig") that the product then reproduced for its first live week before
  anyone measured it. This is not a case of missing evidence; the evidence
  that would have flagged the problem was sitting in the same file as the
  decision, unconsulted, until the owner asked why the record looked wrong.
