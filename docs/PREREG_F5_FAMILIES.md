# F5-moneyline hypothesis families — pre-registration

**DRAFT — PENDING METHODOLOGY REVIEW.** Nothing in this document has been
evaluated. No win rate, ROI, or outcome-derived effect has been computed for
any hypothesis below. `register_family()` has NOT been called. This is a
methodology freeze, written before the denominator is locked, so that
whatever discovery pass eventually runs is over a family fixed in advance —
not a survivor subset chosen after looking at results.

Denominator this document locks against: `data/research/f5/universe_frozen.json`
(hash `c67508603b14af2c494e13fadeb2a2f039f52df996ab6e12ff6164585e33cd1c`),
3,682 gradeable (decided) F5 moneylines, 2023 n=1,597 / 2024 n=2,085, MDE
1.62pp. See `docs/F5_UNIVERSE_FROZEN.md`.

---

## 0. What died already, and why it constrains what is proposed here

- **B3 (M4 — F5-vs-full-game bullpen gap, `docs/RESEARCH_CATALOGUE.md`)**
  died of *sample size*, not evidence: 270 decided games, MDE 8.52pp, F5
  price found "well calibrated" (+1.25pp home vs implied, p=0.67, CI
  [−4.56, +7.12]) — a genuine null-power result, not a null-evidence one. A
  monotone-looking gradient at the halfway point (n=217) *dissolved* on the
  full sample — the canonical example of reading a partial run as
  encouraging.
- **B3's own hypothesis (the bullpen GAP: full-game price minus F5 price)
  requires a full-game moneyline priced at the SAME T-2h instant as the F5
  price, for the same games.** That data does not exist yet. The
  `f5_tminus2_v1` acquisition bought F5 moneyline only
  (`docs/PREREG_F5_SNAPSHOT_RULE.md` §6, `docs/F5_BACKFILL_REPORT.md` §4);
  the only full-game odds store for this window
  (`data/historical/odds_history/`) was captured under the *old*
  fixed-wall-clock rule (`16:50:00Z` / `22:50:00Z`), not T-2h. Pairing them
  would silently reintroduce the exact timing-mismatch defect
  `PREREG_F5_SNAPSHOT_RULE.md` was written to close (comparing two prices
  from different, uncontrolled lead times and calling the difference a
  "gap").
  **B3 is therefore NOT part of this family. It is explicitly out of
  scope until a matched full-game T-2h acquisition is proposed and costed
  separately** — its own purchase authorization, its own release gate,
  exactly like the F5 leg was. Do not fold it into this family later by
  reusing the existing full-game store; that would be silently re-admitting
  a discredited timing confound. **(Flag for reviewer: confirm this
  exclusion is correct rather than something this pass should instead
  schedule.)**
- **U1** ("first F5 research family... designed from forward-captured
  closes") is superseded here for the *historical* discovery/replication
  question — forward capture cannot supply a 2023 screen. The families
  below are U1's historical realization: same market, first real 2023/2024
  split instead of one undersized pool.
- **T4/T8** (`docs/RESEARCH_CATALOGUE.md`): the join and the denominator
  must be frozen and auditable before any p-value is computed, and no
  threshold here may be tuned after seeing a result. Every threshold below
  states its source.

## 1. Candidates considered and deliberately NOT registered

Recorded so the denominator cannot later be padded with something that
looks like it was "always planned":

| candidate | why excluded now |
|---|---|
| Bullpen gap (B3/M4) | needs matched full-game T-2h prices; not acquired (see §0) |
| Line movement / staleness within F5 | this store is one snapshot per game (T-2h only); no second timestamp per game exists to measure movement against |
| Doubleheader / short-rest F5 pricing | plausible mechanism, but no prior-art-grounded threshold for "short rest" was identified without looking at this data's own rest-day distribution first, which would make the threshold outcome-adjacent; deferred |
| Park/weather F5 totals bias | F5 *totals* are out of scope entirely — excluded from `F5_TMINUS2_PRIMARY` and from this denominator by standing rule (`PREREG_F5_SNAPSHOT_RULE.md` §6) |

## 2. The complete strategy denominator

**Two hypotheses. Both F5 moneyline (`h2h_1st_5_innings`), both against the
same frozen 3,682-game gradeable set. No third member may be added after
this document is filed without a visible diff and a re-run of every
correction that depends on the family size.**

| id | name |
|---|---|
| F5-H1 | Home-team calibration bias in the F5 moneyline |
| F5-H2 | Favorite/longshot calibration bias in the F5 moneyline |

Both are **market-calibration** questions (is the F5 price itself an
unbiased forecast, sliced two different pre-specified ways), not a
directional edge invented after inspecting these prices. Both use only data
already in hand: `f5_tminus2_primary.jsonl` (T-2h de-vigged book prices) and
`first_five_results.jsonl` (F5 winner). No provider call, no odds credit,
required for either.

---

### F5-H1 — Home-team calibration bias

**Rationale/mechanism.** Sports-betting literature and this project's own
prior measurement (B3, n=270: actual home win rate 54.4% vs. implied 53.2%,
+1.25pp, same sign, statistically silent at that n) both point toward a
small home-side underpricing — bettors' documented preference to back
favorites/home sides can push the *line*, not necessarily the true
probability, giving the home side positive expected calibration error. This
re-tests B3's own directional finding at ~13.6x the sample size and with
the corrected T-2h timing, rather than proposing a new mechanism.

**Exact feature.** Per gradeable game: `p_home` = de-vigged home implied
probability from the F5 h2h market at the T-2h snapshot
(`src.core.odds.devig_two_way`, `method="proportional"` — the project's
existing default, not chosen for this test), averaged across the game's
`book_count` (≥5, median 12) books' individual de-vigged probabilities
before comparing to outcome. Outcome: `home_win` ∈ {0,1} (ties already
excluded from the gradeable set by construction).

**Direction (fixed in advance).** `mean(home_win) − mean(p_home) > 0`
(home side underpriced) — same sign as B3's point estimate. A negative
result is a clean failure of this specific direction, not grounds to flip
and test the opposite sign post hoc.

**Market.** F5 moneyline, T-2h snapshot, `F5_TMINUS2_PRIMARY` only.

**Sample gate.** Discovery: 2023, n=1,597. Replication: 2024, n=2,085.
Both legs must individually clear a two-sided 95% CI test in the
pre-registered direction; the family-wide MDE is 1.62pp on the full 3,682,
so each half alone is somewhat less powered (2023 alone ≈ 2.46pp MDE, 2024
alone ≈ 2.15pp MDE at p≈0.5) — stated up front, not discovered as an excuse
afterward.

**Effect floor.** **2.0 percentage points**, chosen from two feature-side
anchors, not from this data's own outcome: (a) documented home-bias
magnitudes in the sports-market microstructure literature typically cluster
in the 1–3pp range; (b) it clears this study's own measurement floor (MDE
1.62pp) with margin, so a result at the floor is actually distinguishable
from zero rather than living inside the noise band. **Flag for reviewer:**
the project's blanket `min_effect = 0.01` (1.0pp, `src/model/family.py`)
is *below* this family's own MDE (1.62pp) — using the blanket floor here
would let a "floor-clearing" result be statistically indistinguishable from
zero. This document uses 2.0pp instead; confirm that override is the
correct call rather than accepting the project default.

**Replication criterion.** 2024 point estimate has the same sign as 2023,
clears the 2.0pp floor, and its 95% CI excludes 0 after the FDR correction
in §4. A 2023 screen that does not itself clear the floor is reported as a
loser and 2024 is not searched for rescue.

**Falsification criteria (battery, `src/research/battery.py`, frozen
`RULES_VERSION 2.0.0`, applied verbatim — no bespoke rule for this
hypothesis).** Concretely: effect must not concentrate in a small subset of
seasons/price-bands/favorite-underdog split beyond the battery's frozen
concentration thresholds; must survive leave-one-season-out; must not
depend on a handful of extreme-price games (`_extreme_removal`); must show
no discontinuous, un-physical spike at one threshold
(`_threshold_sensitivity`, `_spike_signature`). Killed outright if the
automated battery flags any fatal rule.

**PIT coverage status.** CLEAN. The T-2h anchor is `scheduled_first_pitch`
(`start_time_utc`), never `actual_first_pitch`; postponement/suspension
handling already verified in `PREREG_F5_SNAPSHOT_RULE.md` §3. No leakage
path identified.

---

### F5-H2 — Favorite/longshot calibration bias

**Rationale/mechanism.** The favorite-longshot bias (bettors overpay for
longshots, systematically underpay for favorites relative to true
probability) is one of the most replicated findings in sports-betting
market microstructure, observed across racing and multiple team-sports
markets. It predicts a *monotonic* miscalibration by probability level,
independent of home/away identity — a different axis than F5-H1.

**Exact feature.** Per gradeable game, the **favorite's** de-vigged implied
probability `p_fav` (whichever side is priced <50% vig-adjusted... i.e.
priced as favorite, `p_fav ≥ 0.5` by construction of picking the shorter
side) from the same T-2h snapshot. Bucketed into **quintiles of `p_fav`
computed from the 2023 discovery set only** (feature-side thresholds, frozen
before any 2024 row or any outcome is touched) — the bucket edges are then
applied unchanged to 2024.

**Direction (fixed in advance).** Calibration error `mean(fav_win) −
mean(p_fav)` is **positive in the top (strongest-favorite) quintile** and
**negative in the bottom (weakest-favorite / most longshot-like) quintile**
— i.e. favorites underpriced, longshots overpriced, matching the
literature's documented sign, not a sign chosen from this dataset.

**Market / sample gate.** Same as F5-H1: F5 moneyline, T-2h,
2023-discovery (n=1,597) / 2024-replication (n=2,085), same MDE caveats.
Per-quintile n is smaller (~320 discovery / ~417 replication per bucket) —
**flag for reviewer:** per-bucket MDE at that n is materially worse than
the family-wide 1.62pp (roughly 3.5–4pp per quintile at p≈0.5); confirm
quintiles (5 buckets) vs. terciles (3 buckets, more power per bucket, less
resolution on the tails where the literature's effect is strongest) is the
right granularity before this is run.

**Effect floor.** **3.0 percentage points per extreme quintile**,
set from the per-bucket MDE estimate above (roughly the same "floor should
clear the study's own measurement resolution" logic as F5-H1, scaled to the
smaller per-bucket n) — not from any observed bucket value.

**Replication criterion.** The extreme-quintile sign pattern (positive top,
negative bottom) reproduces in 2024 with both extreme quintiles clearing
the 3.0pp floor and excluding 0 post-FDR. A monotone *gradient* across all
five buckets is reported as a secondary, descriptive observation only —
never itself the promotion criterion, precisely because B3 already recorded
a monotone-looking gradient (+8.3, +7.2, −5.3, −0.8, −0.6) that dissolved at
full sample. Gradient shape informs interpretation; it does not pass or
fail the hypothesis.

**Falsification criteria.** Same frozen battery as F5-H1, run per-quintile
and on the full favorite/underdog split (`_favorite_underdog` is already a
named battery check). Additionally: killed if the bucket boundaries fit on
2023 do not carry a similar favorite/dog mix in 2024 (a shifted price
distribution between seasons would mean the frozen 2023 edges are testing a
different population in 2024, not replication).

**PIT coverage status.** CLEAN — same anchor and reasoning as F5-H1.

---

## 3. Discovery/replication split

**2023 screens, 2024 replicates. Stated exactly, no other split is used for
either hypothesis:**

- Discovery: all gradeable F5 moneylines dated `2023-05-10..2023-12-31`
  within the frozen universe → **n = 1,597**.
- Replication: all gradeable F5 moneylines dated `2024-01-01..2024-10-07`
  within the frozen universe → **n = 2,085**.
- The split key is `season` as already carried on every row of
  `universe_frozen.json` (`str(date)[:4]`), not re-derived.
- F5-H2's quintile *boundaries* are fit on the 2023 half only and then
  applied, frozen, to 2024 — the boundaries themselves are discovery-set
  output, but they are a feature-side partition (based on `p_fav`, not on
  outcome), so this does not leak outcome information across the split.

## 4. Multiple-testing procedure

**Benjamini-Hochberg FDR at q = 0.10**, over the full **2-member** family
above — the project standard (`src.model.family.FDR_Q = 0.10`,
`src.research.timingtest.FDR_Q`, reused rather than a bespoke value chosen
for F5). The correction is applied to the **replication-leg p-values**
(2024), since the 2023 leg is a screen, not itself the inferential claim —
consistent with how the discovery/replication split is used elsewhere in
this project. `register_family()` (not yet called) will freeze
`{F5-H1, F5-H2}` as the exact 2-entry family the correction runs over — no
hypothesis may be added or dropped from that call afterward without a
visible diff.

**Flag for reviewer:** with only 2 members, BH-FDR at q=0.10 is close to
uncorrected (q=0.10 with m=2 is barely a correction at all vs. m=13-21
elsewhere in this project). Confirm whether that is acceptable given how
narrow this family deliberately is, or whether a fixed, more conservative
alpha (e.g. Bonferroni at 0.05/2) should be used instead precisely because
the family is small enough that FDR's power advantage doesn't matter here.

## 5. Failure criteria — written before any result exists

**F5-H1 fails (is a published loser, not searched further) if ANY of:**
- 2023 screen point estimate is ≤0 or does not clear the 2.0pp floor.
- 2024 replication sign disagrees with 2023, or its CI includes 0 post-FDR.
- The frozen falsification battery flags a fatal rule (concentration,
  leave-one-out instability, extreme-game dependence, threshold spike).
- Any of the above is true — the hypothesis is not "close," it is dead;
  no threshold, bucket, or subgroup redefinition is tried afterward to
  rescue it (T8).

**F5-H2 fails under the identical structure, applied to the two extreme
quintiles**, plus: fails if the 2023-fit quintile edges land on a
materially different favorite/dog mix in 2024 (stated in §2 above) — that
is a population-shift failure, not a replication of the effect.

**Both hypotheses fail together, and the family is reported as a two-loser
family, if:** the frozen universe's own MDE (1.62pp) turns out on inspection
of *feature-side quantities only* (never outcome) to be insufficient for
either floor once real per-bucket/per-season n is confirmed — i.e., an
honest "we cannot tell" verdict (B3's own precedent) is preferred over
forcing a floor low enough to guarantee a numeric pass.

**Zero survivors is a valid, complete result for this family.** Nothing
here is written to guarantee a promotion.

---

## Every hard methodological call for the Opus reviewer to settle

1. **B3/bullpen-gap exclusion (§0).** Confirm it should stay out of this
   family rather than be scheduled now as a separate matched full-game
   T-2h acquisition proposal.
2. **Effect floors chosen above project default (§F5-H1, F5-H2).** The
   project's blanket `min_effect = 0.01` sits below this family's own MDE.
   Confirm the 2.0pp / 3.0pp floors used here (justified from literature +
   "must clear own MDE with margin") are the right override, and the right
   magnitude, rather than something the reviewer would set differently.
3. **F5-H2 bucket granularity** — quintiles (5, thin per-bucket power) vs.
   terciles (3, coarser resolution) — pick one before this ever runs.
4. **FDR at m=2 (§4)** — BH-FDR vs. a fixed Bonferroni-style alpha when the
   family is this narrow.
5. **Discovery-leg role** — this document treats 2023 as a screen (must
   itself clear the floor) and applies the multiple-testing correction only
   to the 2024 replication p-values. Confirm that is the intended
   discovery/replication semantics for F5, consistent with how other
   registered families in this project have used the split, before it is
   locked by `register_family()`.
6. **Whether 2 hypotheses is too thin a family** — i.e., whether any of the
   §1 "not registered" candidates should instead be developed now (at the
   cost of a real acquisition or design effort) so the family denominator
   isn't defined by what happened to be cheaply available, rather than by
   what F5 pricing actually deserves to be tested.

---

## Methodology review — 2026-09-04

Adversarial methodology review of the draft above. **The draft text is
unchanged.** Everything here is an amendment: where an amendment and the
draft disagree, the amendment governs, and the disagreement stays visible.
No outcome data was read to produce this section — every check required
below is computable from prices, dates and universe metadata alone
(`first_five_results.jsonl` is used only for the already-frozen
decided/tie flag that defines gradeability).

### Family-scope decision (A/B/C)

Asked ahead of the hard calls, on research-design merit only; sunk cost on
the F5 acquisition is not an argument for or against anything below.

**First, the factual question: can a timing-matched full-game comparator be
derived from data already owned? Measured answer: NO, and not close.** The
existing archive (`data/historical/odds_history/mlb_2023.jsonl`,
`mlb_2024.jsonl`) holds 1,172 distinct snapshot instants across the window,
taken on the retired fixed wall-clock schedule. For each of the 3,682
gradeable F5 games I took its own `start_time_utc` from
`data/historical/mlb_results.csv`, computed its T-2h target, and found the
nearest archive snapshot instant. Result: **0 games within the ±5-minute
snapshot-rule tolerance, 302 (8.2%) within ±30 minutes, 3,380 (91.8%)
further out; median deviation 81.4 minutes, and even the best-matched decile
is 35.6 minutes off.** (Feature-side only: scheduled start times and snapshot
timestamps; no price and no outcome was read.) A derived comparator is
therefore impossible at the pre-registered tolerance, and the 8.2% that come
within half an hour would reconstitute B3's exact failure — n≈302 (versus
B3's 270), a mismatched and *game-varying* lead time, and an MDE around 8pp.
Deriving it would not be a cheap version of B; it would be the discredited
version.

**DECISION: A — register F5-H1 and F5-H2 now, as amended below — and,
separately and in parallel, recommend the owner authorize the comparator
acquisition (B) as its own purchase, its own pre-registration and its own
release gate.** These are not competing options and the framing that makes
them compete is the error: A costs zero credits and reads only data already
in hand, so nothing about doing A consumes anything B would need. C is
rejected outright — 3,682 games at MDE 1.62pp is the best-powered F5 sample
this project has ever assembled, roughly 13.6x B3's, and neither the market
nor the question is broken; retiring it would discard a clean, paid-for
measurement surface for no design reason.

**Why A is not merely the cheap option but the correct *first* one.**
F5-H1/H2 ask whether the F5 price is itself an unbiased forecast. The B3 gap
statistic is `full_game_p − f5_p`, which *inherits* whatever calibration
error the F5 leg carries: if the F5 price is systematically home-biased or
favourite-biased, a gap finding is confounded by that bias and cannot be
attributed to bullpen information at all. Running the calibration baseline
first is a genuine methodological prerequisite for interpreting B3, not a
consolation prize — and it is the kind of prerequisite that is worth much
more before the comparator is bought than after, because a discovered F5
calibration bias changes how the comparator family should be specified.

**Why B deserves separate authorization on merit.** The acquisition is
outcome-blind (keyed on `game_pk` and scheduled start only), so it carries no
leakage risk and cannot be tuned toward a result. At roughly 1 credit per
game-snapshot over the same ~4,315-game scope it is ~4-5k of the 25,555
credits remaining this cycle — a real fraction, and it should be weighed as
such, but it sits inside the historical_backfill band, credits expire
worthless at reset, and it converts a question currently answerable only at
MDE ~8.5pp into one answerable at MDE ~1.6pp. That is the largest power gain
per credit currently identified anywhere in the F5 programme, and unlike a
tuning purchase it buys a *new comparison axis* rather than more of an axis
already owned. It is nonetheless the owner's spending decision, not this
review's, and it must not become a precondition for A.

**Binding conditions on B if authorized.** It is acquired under the same
frozen T-2h rule as `PREREG_F5_SNAPSHOT_RULE.md` §2 (±5-minute tolerance,
≥5 books, no re-query at another instant to manufacture a passing row, misses
recorded as explicit `PRIMARY_SNAPSHOT_UNAVAILABLE` rows); it gets its own
frozen universe document and its own content hash; B3 is registered as its
own family with its own FDR correction; and the existing wall-clock full-game
archive is never used to backfill a comparator gap, at any coverage level,
including the 302 near-misses measured above.

### Hard call 1 — B3 / bullpen-gap exclusion

**DECISION: exclusion from THIS FAMILY confirmed. Separate authorization of
a comparator acquisition is RECOMMENDED — see the family-scope decision
above, which supersedes the draft's "not scheduled" framing.** The draft's reasoning is correct and is the stronger form of the
argument: the defect is not "we lack data," it is that the only full-game
store covering this window was captured under the retired fixed-wall-clock
rule, so any gap computed against it is a difference of two prices taken at
uncontrolled and *differing* lead times. That difference is dominated by
timing, not by bullpen information, and it is precisely the confound
`PREREG_F5_SNAPSHOT_RULE.md` was written to close; admitting it would
retroactively invalidate the snapshot rule rather than merely weaken B3.
Scheduling a matched full-game T-2h acquisition inside this review would
also couple a paid acquisition decision to a methodology sign-off, which is
the wrong instrument — the F5 leg got its own purchase authorization and
its own release gate, and the full-game leg must too. B3 therefore remains
out of this family's denominator permanently: if a matched T-2h full-game
store is later acquired, B3 is registered as its own family with its own
correction, never folded into `{F5-H1, F5-H2}` after the fact.

### Hard call 2 — effect floors above the project default

**DECISION: the override is CORRECT in principle. F5-H1 floor stays at
2.0pp. F5-H2's 3.0pp floor is REJECTED as internally incoherent and is
RAISED to 4.0pp (with the granularity change in hard call 3).**

A floor below the study's own MDE is not a floor: it admits results that
cannot be distinguished from zero, which is exactly the failure the blanket
`MIN_EFFECT = 0.010` would produce here (1.0pp against a 1.62pp family MDE).
The draft is right to override it, and right that the override must be
justified feature-side — literature magnitude plus own-measurement
resolution — rather than from anything this data's outcomes say. 2.0pp on
the full 3,682 clears 1.62pp with real margin and sits inside the 1-3pp band
the microstructure literature reports, so F5-H1 needs no change.

F5-H2's floor fails its own test. **The draft's per-quintile MDE figure
("roughly 3.5-4pp") is arithmetically wrong and optimistic.** At n=319
(2023) / n=417 (2024) per quintile, the two-sided 95% MDE is **5.49pp /
4.80pp** at p=0.5, and 5.23pp / 4.58pp at p=0.65 (a realistic top-bucket
favourite probability). A 3.0pp floor is therefore *below* the per-bucket
measurement resolution at either leg — the identical defect the draft
correctly refuses to accept from the project default. Under terciles (hard
call 3) the per-bucket MDE is 4.25pp (2023) / 3.72pp (2024) at p=0.5 and
4.05 / 3.55pp at p=0.65. **The floor is set at 4.0pp**, which clears the
replication leg's own resolution and sits just at the discovery leg's. This
raises the bar; it never lowers it, and no result may be rescued by moving
it back down. It follows that **F5-H2 is a priori underpowered on its
discovery leg at any granularity this universe supports.** That is stated
here in advance, not discovered later as an excuse, and per §5 an honest
"we cannot tell" is a complete and acceptable outcome for F5-H2.

### Hard call 3 — F5-H2 bucket granularity

**DECISION: TERCILES. Quintiles are rejected.** The choice is between
resolution on the tails and the ability to measure anything at all, and at
this n the quintile version cannot measure anything at all: its per-bucket
MDE (4.8-5.5pp) exceeds any effect size the favourite-longshot literature
would predict for a liquid, ≥5-book, de-vigged major-league sub-market, so
a quintile design is pre-committed to a null it cannot distinguish from
absence of power. Terciles recover roughly a fifth of the MDE and keep the
top/bottom contrast the hypothesis is actually about; the loss is tail
resolution, which the draft has already demoted to descriptive anyway by
refusing to treat the gradient as a promotion criterion. Edges are the
33.3/66.7 percentiles of `p_fav` **fit on 2023 only and frozen before any
2024 row is touched**, exactly as the draft specifies for quintiles.
Additional pre-registered requirement: each 2024 bucket must carry **n ≥
300** or F5-H2's replication leg is reported as blocked-coverage, not as a
loser — an under-populated bucket is a missing measurement, not evidence.

### Hard call 4 — FDR at m=2

**DECISION: KEEP BH-FDR at q = 0.10 over the 2-member family. Bonferroni is
rejected.** The draft's own observation is correct — at m=2 this is barely a
correction — but that is a reason to be clear-eyed about what protects this
family, not a reason to swap in a stricter alpha. Switching to Bonferroni
0.05/2 would be a bespoke, F5-specific stringency chosen by this reviewer
for this family, which is structurally the same act as loosening one: a
correction whose value is picked per-family stops being a pre-registered
standard. `FDR_Q = 0.10` is the project standard (`src/model/family.py`,
`src/research/timingtest.py`) and is reused here unchanged for that reason.
What actually protects this family is the conjunction the draft already
requires — correct pre-registered sign, an effect floor above the study's
own MDE, independent-season replication, and the frozen battery — every one
of which is stricter than the multiplicity correction. Two amendments make
that explicit: (i) the 2024 leg must additionally clear a **two-sided 95%
CI excluding zero**, stated as a standing requirement rather than left
implicit in "post-FDR"; (ii) all p-values and intervals on both legs are
**clustered by date** (`src/model/discovery.py`), never row-independent —
same-slate games share weather, schedule position and market conditions, and
unclustered inference here is the anticonservative n that manufactures
significance. Note also that F5-H1 and F5-H2 are two slices of the *same*
3,682 prices and are positively dependent; m=2 understates the true
multiplicity rather than overstating it, so the small family is not a
license to relax anything else.

### Hard call 5 — discovery-leg role

**DECISION: CONFIRMED, with one amendment.** 2023 as a screen and the
correction applied only to the 2024 replication p-values is the correct and
project-consistent semantics: the screen exists to stop a hypothesis, the
replication carries the inferential claim, and correcting the screen too
would double-penalise a design that already pays for its discovery pass by
discarding half its data. **Amendment: the 2023 screen passes on sign plus
point estimate ≥ floor only — no CI or FDR requirement is imposed on the
screen leg.** As drafted ("both legs must individually clear a two-sided 95%
CI test"), the screen demands a 2.0pp effect to be significant at n=1,597,
where the MDE is 2.45pp; that gate is not conservative, it is a coin-flip
filter that discards true effects for the crime of being measured on half
the data, and it would make a two-loser family a near-foregone conclusion
for reasons of arithmetic rather than of market efficiency. The rigour lives
where it belongs: on 2024, at full floor, CI-excluding-zero, post-FDR, past
the battery.

### Hard call 6 — is a 2-hypothesis family too thin

**DECISION: NO. Register two. Do not develop a third for this family.** A
family's size is not a virtue metric, and padding it would be actively
harmful in both directions the project already guards against: the §1
doubleheader/short-rest candidate is honestly described as needing a
threshold that could only come from inspecting this data's own rest-day
distribution, which makes it outcome-adjacent by construction; line-movement
is impossible on a one-snapshot-per-game store; F5 totals are excluded by
standing rule; and B3 needs an acquisition. Adding any of them now would
either enlarge the denominator with a hypothesis that cannot be tested
(costing power in the correction for nothing) or import a tuned threshold.
Two well-motivated, mechanism-backed, literature-anchored calibration tests
against a frozen 3,682-game universe is a complete family. **Binding
condition: if any third F5-moneyline hypothesis is ever registered against
this same frozen universe, the FDR correction is re-run over the union of
all F5 hypotheses ever registered against it, not over the new family
alone** — otherwise "one family at a time" becomes an unlimited-tries budget.

---

### (a) Additional flaws found in the draft

**A1 — the tie-settlement convention is never stated, and 14.3% of OK rows
are ties. This is the most serious unresolved defect.** The gradeable set
drops 614 ties from 4,298 OK rows and then compares outcomes against a
**two-way** de-vigged `p_home`. That is only valid if every book's F5
moneyline is genuinely a two-way, void-on-tie market — in which case the
book's own price *is* a conditional-on-decided probability and dropping ties
is exactly right. If any book in the ≥5-book consensus quotes a **three-way**
F5 line (home / away / draw), its two-outcome de-vig silently renormalises
away a real draw price, inflating both sides' implied probabilities, and the
resulting calibration error is a measurement artefact of the de-vig, not of
the market. Required before running, feature-side: enumerate the distinct
outcome-name sets present under `h2h_1st_5_innings` across every book in
`f5_tminus2_primary.jsonl` and confirm all are two-way. **Any three-way book
found is excluded from the consensus (and the book-count ≥5 gate re-checked
after exclusion), or the family does not run.**

**A2 — `method="proportional"` de-vig has a favourite-longshot signature of
its own, which directly confounds F5-H2.** Proportional de-vig distributes
the overround in proportion to implied probability, which is known to
overstate longshot probabilities relative to Shin or multiplicative
conventions — i.e. the de-vig convention itself produces a bias with the
same sign and in the same buckets as the effect F5-H2 is trying to detect,
and the disagreement between conventions in extreme buckets can exceed the
4.0pp floor. Using the project default is the right *primary* choice (it was
not selected for this test), but it cannot stand alone here. **Amendment: a
de-vig sensitivity is now part of F5-H2's pre-registered pass criteria, not
a diagnostic. The extreme-bucket effect must keep its sign under all three
of proportional (primary), multiplicative/odds-ratio, and Shin. A sign that
does not survive all three is a property of the de-vig, not of the market,
and kills F5-H2.** For F5-H1 the same three conventions are computed and
**reported**, but do not gate: a home/away split is close to symmetric
across the price range, so the convention's differential effect largely
cancels.

**A3 — the frozen hash covers game identity only, not prices.** The
`c675086…cd1c` hash is explicitly "sha256 over the sorted eligible `game_pk`
set … identity of the set only (which games), not any downstream
classification." A re-fetch, repair, or normalisation change could alter
every book price in `f5_tminus2_primary.jsonl` without moving that hash by a
bit. **Amendment: a second content hash over the priced payload (per
`game_pk`: `snapshot_at`, and each book's key + both prices, canonically
ordered) must be computed and recorded in `docs/F5_UNIVERSE_FROZEN.md`
before the first evaluation runs, and re-verified at run time.** Without it
this family is pre-registered against a denominator it cannot prove did not
move.

**A4 — the battery's book-concentration rule will be silently unarmed.**
`battery.py` rule 3 needs a per-row `book`; both hypotheses grade one
consensus row per game, so rule 3 reports `{"skipped": …}` and can never be
fatal. That is the battery behaving correctly, but a fatal rule that is
quietly inert is exactly the kind of unremembered kill-test the battery
exists to prevent. **Amendment: the run must record explicitly that rule 3
was skipped and why, and must additionally report the per-book replication
of the effect's sign (each book's own de-vigged prices, graded separately)
as a report-only concentration diagnostic.** Book composition is known to
churn across this window, so a sign that exists only in the books present in
one season is information a reader needs.

**A5 — the "population shift" kill in F5-H2 has no number.** "Do not carry a
similar favorite/dog mix" is a discretionary judgment made after seeing 2024,
which is a rescue lever in both directions. **Amendment: the kill is a
chi-square test of 2024 bucket occupancy against the 2023-fit expected
thirds, fatal at p < 0.01**, decided on feature-side counts before any 2024
outcome is read.

**A6 — no denominator padding, no floor set to guarantee a pass, and no
leakage path found beyond the above.** Positively: the universe reconciles
exactly (4,315 + 8 = 4,323; 614 + 2 + 3,682 = 4,298), the eligible set
deliberately retains 17 `PRIMARY_SNAPSHOT_UNAVAILABLE` rows rather than
narrowing to games that happened to price, the T-2h anchor is
`scheduled_first_pitch` and never `actual_first_pitch`, and the grid-floor
offset is uniform (−1.37 to −4.38 min, all early, inside tolerance) so it
introduces no relative bias between games. The floors here are set *above*
the study's own resolution, i.e. against the authors' interest, which is the
correct direction. The 17 unavailable rows should nonetheless be reported
alongside any result, since missingness is plausibly correlated with market
thinness.

### (b) Required evaluation path, and its validation

**STANDALONE MEASUREMENT PATH. `src/research/funnel.py` must NOT be used,
and must NOT be widened to accommodate this family.** The funnel is a
feature-threshold *selection* instrument: `validate_spec` requires a
`feature` drawn from the engine matrix's `NUMERIC_FEATURES`, a
`side_rule` of `back_advantaged`, and a `threshold > 0` that fires a side.
F5-H1 and F5-H2 select nothing — they grade the entire population (or a
frozen feature-side partition of it) against its own price. Forcing them
through the funnel would require inventing a fake feature and a fake
threshold purely to satisfy validation, which corrupts the registered spec
into something that does not describe the hypothesis. This is a different
situation from `RESEARCH_V7_TOTALS.md` hard call 1, where a totals family
genuinely needs the funnel's selection machinery rebuilt; here the funnel is
the wrong shape, not a missing one. The required path is a small standalone
module that **reuses, and does not reimplement**: `src/model/discovery.py`
for date-clustered effects, p-values and intervals; `src/research/battery.py`
at frozen `RULES_VERSION 2.0.0` applied verbatim; `src/model/family.py`
(`FDR_Q`, `benjamini_hochberg`, `register`) for the family freeze and
correction. Its only new code is row construction: `{date, won, implied,
season, side, price}` per game, where `implied` is the cross-book mean
de-vigged probability of the graded side and `won` is that side's F5 result.

**Validation this path must pass before it is run on real data — all of it
feature-side or synthetic, none of it requiring an outcome read:**

1. A synthetic-injection test in the house style (cf.
   `tests/test_engine_features.py`): construct rows with a known injected
   calibration error and assert the path recovers it, sign and magnitude,
   with date clustering intact.
2. A PIT test asserting the path never reads `actual_first_pitch`, any
   settlement timestamp, or any 2025/2026-dated row — including a negative
   test that a deliberately injected 2025 or 2026 row is rejected, not
   silently filtered.
3. A denominator test: the path's row count equals exactly 3,682, splits
   1,597 / 2,085 by `season`, and both the identity hash (A3, existing) and
   the new price-payload hash (A3, to be added) verify at run time — the run
   aborts on mismatch rather than proceeding on a moved universe.
4. A de-vig test: all three conventions (proportional, multiplicative, Shin)
   implemented and agreeing on a hand-checked two-way example, and the
   two-way outcome-set audit of A1 passing on every book.
5. A battery-wiring test: the battery is invoked with the frozen rules, no
   bespoke rule is passed, and the run's report names every rule that was
   skipped for want of a key (A4) rather than letting a skip pass unnoticed.
6. `bash scripts/test_fast.sh` while building, `python3 scripts/test_parallel.py`
   green before the first evaluation run.

Only after 1-6 pass may `register_family()` / `family.register` be called to
freeze `{F5-H1, F5-H2}`, and only after that may any outcome be read.

### Summary of amendments (binding)

1. F5-H2 granularity: quintiles → **terciles**; 2024 bucket floor n ≥ 300.
2. F5-H2 effect floor: 3.0pp → **4.0pp** (per extreme tercile). F5-H1 floor
   unchanged at 2.0pp. The draft's per-quintile MDE figure was understated;
   corrected figures recorded above.
3. F5-H2 population-shift kill made numeric: chi-square on bucket occupancy,
   fatal at p < 0.01.
4. Screen leg (2023) passes on **sign + point estimate ≥ floor only**; no CI
   or FDR gate on the screen. Full inferential burden on 2024.
5. 2024 leg must clear a two-sided 95% CI excluding zero **and** BH-FDR
   q=0.10; BH-FDR retained, Bonferroni rejected.
6. All inference **date-clustered**, both legs, both hypotheses.
7. Three-way-book audit (A1) is a **precondition**; any three-way book is
   excluded and the ≥5-book gate re-checked.
8. De-vig sensitivity across proportional / multiplicative / Shin is a
   **pass criterion for F5-H2** (sign must survive all three) and
   report-only for F5-H1.
9. A **price-payload content hash** is added to `F5_UNIVERSE_FROZEN.md` and
   verified at run time; the run aborts on mismatch.
10. Battery rule 3 (book concentration) is recorded as skipped-and-why, with
    a per-book sign replication reported as a diagnostic.
11. Evaluation runs on a **standalone path**, not the funnel; validation
    items (b)1-6 must pass before registration.
12. B3 permanently out of THIS family; family stays at two members; any
    future third F5 hypothesis re-runs the correction over the union.
13. Family-scope decision: **A** (register H1/H2 now) — with the comparator
    acquisition (B) recommended for separate owner authorization, and the
    measured finding that no comparator is derivable from owned data
    (0 / 3,682 games within tolerance; median 81.4 min off T-2h).

**VERDICT: READY TO REGISTER AS AMENDED**
