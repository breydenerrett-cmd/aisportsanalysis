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

---

## FINAL SPECIFICATION (post-review, 2026-09-04) — the text register_family freezes

Self-contained. Amendments govern over §0-5 wherever they differ. No outcome
data read to produce this section.

### Family denominator

Exactly two members, run against the frozen 3,682-game gradeable universe
(`data/research/f5/universe_frozen.json`, identity hash
`c67508603b14af2c494e13fadeb2a2f039f52df996ab6e12ff6164585e33cd1c`; a second
price-payload hash is required before run, see Preconditions):

| id | name |
|---|---|
| F5-H1 | Home-team calibration bias in the F5 moneyline |
| F5-H2 | Favorite/longshot calibration bias in the F5 moneyline |

B3 (bullpen gap) is **permanently excluded** from this family — not deferred,
not scheduled inside it. A matched full-game T-2h acquisition, if the owner
authorizes it separately, is registered as its own family with its own FDR
correction; it is never folded into `{F5-H1, F5-H2}`. **Union re-run rule:**
if any third F5-moneyline hypothesis is ever registered against this same
frozen universe, the FDR correction is re-run over the union of every F5
hypothesis ever registered against it — never over the new family alone.

### F5-H1 — exact definition

- **Feature:** `p_home` = de-vigged home implied probability from the F5
  `h2h_1st_5_innings` market at the T-2h snapshot, primary convention
  `method="proportional"` (`src.core.odds.devig_two_way`), averaged across
  the game's book_count (≥5, median 12) de-vigged per-book probabilities.
  Sensitivity: multiplicative/odds-ratio and Shin conventions are also
  computed and **reported**, not gating (home/away split is close to
  symmetric across price range, so convention effect largely cancels).
- **Side:** home.
- **Outcome:** `home_win` ∈ {0,1}, ties excluded by construction of the
  gradeable set.
- **Direction (fixed):** `mean(home_win) − mean(p_home) > 0`.
- **Effect floor:** 2.0 percentage points.
- **PIT anchor:** `scheduled_first_pitch` (`start_time_utc`), never
  `actual_first_pitch`.

### F5-H2 — exact definition

- **Feature:** `p_fav` = de-vigged implied probability of the favorite
  (`p_fav ≥ 0.5` by construction), same T-2h snapshot, primary convention
  proportional.
- **Bucketing (binding, tercile, not quintile):** terciles of `p_fav`, edges
  = 33.3/66.7 percentiles **fit on the 2023 discovery set only**, frozen
  before any 2024 row or outcome is touched, then applied unchanged to 2024.
  **Bucket floor: each 2024 bucket must carry n ≥ 300**, or F5-H2's
  replication leg is reported as blocked-coverage (a missing measurement),
  not as a loser.
- **Direction (fixed):** calibration error `mean(fav_win) − mean(p_fav)` is
  positive in the top (strongest-favorite) tercile and negative in the
  bottom (most longshot-like) tercile.
- **Effect floor:** 4.0 percentage points per extreme tercile (raised from
  the draft's 3.0pp, which the review found below the per-bucket MDE at
  either leg; corrected MDEs: terciles 4.25pp (2023) / 3.72pp (2024) at
  p=0.5, 4.05/3.55pp at p=0.65).
- **De-vig sign-survival pass criterion (binding, not a diagnostic):** the
  extreme-bucket effect must keep its sign under all three conventions —
  proportional (primary), multiplicative/odds-ratio, and Shin. A sign that
  does not survive all three kills F5-H2 (the sign would be a property of
  the de-vig convention, not of the market).
- **Population-shift kill (numeric):** chi-square test of 2024 bucket
  occupancy against the 2023-fit expected thirds, **fatal at p < 0.01**,
  computed on feature-side bucket counts only, before any 2024 outcome is
  read.
- F5-H2 is stated a priori as **underpowered on its discovery leg at any
  granularity this universe supports** — an honest "cannot tell" is a
  complete, acceptable outcome, not a design failure.

### Discovery/replication split

- Discovery: 2023-05-10..2023-12-31, all gradeable F5 moneylines in the
  frozen universe, n = 1,597.
- Replication: 2024-01-01..2024-10-07, all gradeable F5 moneylines in the
  frozen universe, n = 2,085.
- Split key: `season` (`str(date)[:4]`) as already carried on every row of
  `universe_frozen.json`; not re-derived.
- F5-H2's tercile edges are fit on the 2023 half only (feature-side, no
  outcome), then applied frozen to 2024.

### Screen-leg pass rule (2023, binding amendment)

The 2023 screen passes on **sign + point estimate ≥ floor only**. No CI and
no FDR requirement on the screen leg. (The draft's original "both legs must
clear a two-sided 95% CI" was rejected: at n=1,597 the MDE is 2.45pp against
a 2.0pp floor, making the screen a coin-flip filter that would discard true
effects for being measured on half the data.) All inferential rigor is
carried by the 2024 leg.

### Replication pass rule (2024, binding)

Both of the following, jointly, on the 2024 leg, for the pre-registered
sign/floor:

1. Two-sided 95% CI, **date-clustered** (`src/model/discovery.py`), excludes
   0.
2. Passes BH-FDR at **q = 0.10 over the full 2-member family (m=2)**
   (`src.model.family.FDR_Q`, `benjamini_hochberg`, `register`) —
   BH-FDR retained; Bonferroni rejected as a bespoke per-family stringency
   choice. Note: F5-H1 and F5-H2 are two slices of the same 3,682 prices and
   are positively dependent, so m=2 understates rather than overstates true
   multiplicity — not a license to relax the floor, CI, or battery.

All p-values and intervals, both legs, both hypotheses, are **date-clustered**
— same-slate games share weather, schedule position, market conditions;
row-independent inference here is anticonservative.

### Falsification battery (RULES_VERSION 2.0.0, verbatim, applied to both hypotheses)

Frozen `src/research/battery.py`, no bespoke rule for either hypothesis:
concentration in a season/price-band/favorite-underdog split beyond frozen
thresholds; leave-one-season-out instability; extreme-game dependence
(`_extreme_removal`); discontinuous/un-physical threshold spike
(`_threshold_sensitivity`, `_spike_signature`); `_favorite_underdog` run
per-tercile and on the full split for F5-H2. Any fatal flag kills the
hypothesis outright.

- **Rule 3 (book concentration) is structurally unarmed** — both hypotheses
  grade one consensus row per game, so rule 3 has no per-row `book` to act
  on. It is **recorded as `{"skipped": ...}` with the reason**, never left
  as a silently inert fatal check.
- **Per-book sign diagnostic (report-only):** the run additionally reports
  each book's own de-vigged-price replication of the effect's sign,
  separately, as a concentration diagnostic — book composition is known to
  churn across the window.

### Preconditions (must all be true before any evaluation runs)

1. **A1 tie/two-way audit passing.** Enumerate the distinct outcome-name
   sets present under `h2h_1st_5_innings` across every book in
   `f5_tminus2_primary.jsonl`; confirm all are two-way. Any three-way book
   found is excluded from the consensus and the ≥5-book gate is re-checked
   after exclusion. If this cannot be satisfied, the family does not run.
2. **Price-payload content hash recorded and verified.** A second sha256
   hash — over `game_pk` → `snapshot_at` and each book's key + both prices,
   canonically ordered — is computed and recorded in
   `docs/F5_UNIVERSE_FROZEN.md` before the first evaluation, and
   re-verified at run time; the run aborts on mismatch. (The existing
   identity hash `c675086…cd1c` covers game-set identity only, not prices.)
3. **Validation items 1-6 (evaluation-path §(b)) green:** (1) synthetic
   injected-effect recovery test, sign+magnitude, with date clustering
   intact; (2) PIT test rejecting `actual_first_pitch`/settlement
   timestamps/any 2025 or 2026-dated row, including a negative test on a
   deliberately injected out-of-window row; (3) denominator test — row
   count exactly 3,682, split 1,597/2,085 by season, both hashes verify;
   (4) de-vig test — all three conventions implemented, agreeing on a
   hand-checked two-way example, plus the A1 two-way audit passing on every
   book; (5) battery-wiring test — frozen rules invoked, no bespoke rule, and
   every skipped-for-want-of-key rule named in the run report; (6)
   `bash scripts/test_fast.sh` green while building,
   `python3 scripts/test_parallel.py` green before the first evaluation run.

Evaluation path: a **standalone module**, not `src/research/funnel.py` (the
funnel is a feature-threshold selection instrument requiring a
`NUMERIC_FEATURES` feature, `back_advantaged` side rule, and `threshold > 0`
— wrong shape for a whole-population/frozen-partition calibration grade).
The standalone path reuses without reimplementing: `src/model/discovery.py`
(date-clustered effects/p-values/intervals), `src/research/battery.py`
(frozen RULES_VERSION 2.0.0, verbatim), `src/model/family.py` (`FDR_Q`,
`benjamini_hochberg`, `register`). Its only new code is row construction:
`{date, won, implied, season, side, price}` per game, `implied` = cross-book
mean de-vigged probability of the graded side, `won` = that side's F5
result. Only after preconditions 1-3 pass may `register_family()` /
`family.register` be called to freeze `{F5-H1, F5-H2}`; only after that may
any outcome be read.

### Power / MDE statement

- Family-wide (full 3,682, both legs pooled): MDE **1.62pp**.
- Per-leg, family-wide feature: 2023 alone ≈ 2.46pp MDE; 2024 alone ≈ 2.15pp
  MDE, at p≈0.5.
- Per-tercile (F5-H2), at p=0.5: 2023 ≈ 4.25pp, 2024 ≈ 3.72pp. At a realistic
  top-bucket p≈0.65: 2023 ≈ 4.05pp, 2024 ≈ 3.55pp.
- **F5-H2 is stated a priori as underpowered on its discovery leg** at any
  granularity this universe supports (its 4.0pp floor sits just at, not
  comfortably above, the 2023-leg MDE) — recorded before any result exists,
  not discovered afterward as an excuse.

### Exclusion criteria

The eligible set retains **17 `PRIMARY_SNAPSHOT_UNAVAILABLE` rows** rather
than narrowing to games that happened to price. These 17 rows are **reported
alongside any result**, since missingness is plausibly correlated with
market thinness; they are not silently dropped from the denominator
narrative even though they cannot be graded.

### Confirmatory vs. exploratory hierarchy

**Confirmatory (subject to the full pre-registered gate above):** F5-H1,
F5-H2 (extreme-tercile pass criteria only; the mid-tercile and any full
5-point or 3-point gradient shape are descriptive, never a promotion
criterion).

**Exploratory / report-only (no pass/fail status, never promoted on their
own):**
- Per-book sign replication diagnostic (battery rule 3 substitute, both
  hypotheses).
- De-vig sensitivity for F5-H1 (multiplicative and Shin conventions,
  reported not gated — for F5-H2 the same sensitivity is confirmatory/gating,
  see above).
- Unavailable-row (`PRIMARY_SNAPSHOT_UNAVAILABLE`, n=17) analysis.
- Full monotone-gradient shape across all terciles for F5-H2.

### Stopping / failure rules

**F5-H1 fails (published loser, not searched further) if ANY of:**
- 2023 screen point estimate ≤0 or does not clear the 2.0pp floor.
- 2024 sign disagrees with 2023, or its date-clustered 95% CI includes 0, or
  it fails BH-FDR at q=0.10 (m=2).
- The frozen battery flags any fatal rule.
No threshold, bucket, or subgroup redefinition is tried afterward to rescue
a failed hypothesis (T8).

**F5-H2 fails under the identical structure** applied to the two extreme
terciles, plus fails if:
- Either 2024 extreme-tercile bucket has n < 300 (reported as
  blocked-coverage, not loser).
- The de-vig sign-survival criterion fails (sign does not hold under all
  three conventions in the extreme bucket).
- The chi-square population-shift test is significant at p < 0.01.

**Both hypotheses fail together, reported as a two-loser family, if:** the
frozen universe's MDE (1.62pp), on feature-side inspection only (never
outcome), proves insufficient for either floor once real per-bucket/
per-season n is confirmed — an honest "cannot tell" is preferred over a
floor lowered to guarantee a numeric pass.

**Zero survivors is a valid, complete result for this family.** Nothing in
this specification is written to guarantee a promotion.

### The family record `register_family()` freezes

Hashes are placeholders — populated from `docs/F5_UNIVERSE_FROZEN.md` at
registration time, never invented here.

```json
{
  "family_id": "F5_MONEYLINE_CALIBRATION_2026H1",
  "members": [
    {
      "id": "F5-H1",
      "name": "Home-team calibration bias in the F5 moneyline",
      "market": "h2h_1st_5_innings",
      "snapshot": "F5_TMINUS2_PRIMARY",
      "devig_primary": "proportional",
      "devig_sensitivity": ["multiplicative_odds_ratio", "shin"],
      "devig_sensitivity_gates": false,
      "direction": "mean(home_win) - mean(p_home) > 0",
      "effect_floor_pp": 2.0,
      "bucketing": null,
      "bucket_floor_n": null
    },
    {
      "id": "F5-H2",
      "name": "Favorite/longshot calibration bias in the F5 moneyline",
      "market": "h2h_1st_5_innings",
      "snapshot": "F5_TMINUS2_PRIMARY",
      "devig_primary": "proportional",
      "devig_sensitivity": ["multiplicative_odds_ratio", "shin"],
      "devig_sensitivity_gates": true,
      "direction": "top tercile positive, bottom tercile negative",
      "effect_floor_pp": 4.0,
      "bucketing": "tercile",
      "bucket_edges_fit_on": "2023_discovery_only",
      "bucket_floor_n": 300,
      "population_shift_kill": {"test": "chi_square", "fatal_p_lt": 0.01}
    }
  ],
  "discovery": {"date_range": ["2023-05-10", "2023-12-31"], "n": 1597},
  "replication": {"date_range": ["2024-01-01", "2024-10-07"], "n": 2085},
  "screen_pass_rule": "sign_and_point_estimate_ge_floor_only",
  "replication_pass_rule": "two_sided_95pct_CI_date_clustered_excludes_zero_AND_bh_fdr",
  "fdr_q": 0.10,
  "fdr_m": 2,
  "clustering": "date",
  "battery_rules_version": "2.0.0",
  "battery_rule3_status": "skipped_recorded_with_per_book_sign_diagnostic",
  "universe_identity_hash": "c67508603b14af2c494e13fadeb2a2f039f52df996ab6e12ff6164585e33cd1c",
  "universe_price_payload_hash": "PLACEHOLDER_FILL_FROM_MANIFEST_AT_REGISTRATION",
  "excluded_members_permanent": ["B3"],
  "union_rerun_on_future_member": true,
  "unavailable_rows_reported": 17
}
```

### Open for adversarial review

- Whether `family_id: "F5_MONEYLINE_CALIBRATION_2026H1"` is the correct id
  string/convention for `family.register` (not specified anywhere in the
  draft or review; invented here for concreteness only — replace with the
  project's actual naming convention before registration).
- Whether the price-payload hash's exact canonical ordering (per `game_pk`:
  `snapshot_at`, then each book key + both prices) needs a fully specified
  serialization format (field order, separator, encoding) before two
  independent runs are guaranteed to produce the same hash — the review
  states the *inputs* to hash but not the exact serialization algorithm.
- Whether "each 2024 bucket must carry n ≥ 300" (hard call 3) applies only
  to the two extreme terciles gating F5-H2, or to the middle tercile too
  (the middle is descriptive-only, but an underpopulated middle bucket could
  still distort the frozen edges' population-shift chi-square test).

---

## Adversarial pre-registration review — 2026-09-04

Independent adversarial pass over the FINAL SPECIFICATION above and the code
that implements it (`src/research/f5_eval.py`, `src/research/f5_universe.py`,
`src/model/family.py`, `src/research/battery.py`). **No outcome value was
read**: every number below is feature-side (prices, dates, bucket
occupancies) or produced from synthetic rows built inside the test helpers.
`register_family()` was not called. No file under `src/` was modified —
divergences there are reported, not fixed.

Commands run: `python3 -m unittest tests.test_f5_eval tests.test_f5_universe -q`
(49 tests, OK); `f5_eval.run(dry_run=True)` against the real stores (both
hashes verify: identity `c675086…cd1c`, price payload `f2ff7b74…5ec7`;
3,682 rows; 1,597/2,085 split; 2024 tercile occupancy 768/668/649).

### BLOCKING

**B1 — F5-H1 is evaluated on the POOLED 2023+2024 universe, and no 2023
screen leg exists. REPRODUCED.** In `run_full_evaluation`, `evaluate_h1(h1_rows)`
and `run_battery(h1_rows, …)` are handed all 3,682 rows; the p-value that
then enters the FDR correction is a pooled-universe p, not the 2024
replication p the spec makes the sole inferential claim. There is no
2023-only evaluation anywhere in the module, so the binding screen-leg rule
("sign + point estimate ≥ floor, 2023 only") is unimplemented for both
hypotheses. Repro (synthetic outcomes, 400 rows per season: a 20pp home
bias injected in 2023 only, 2024 exactly calibrated):

```
pooled effect/p:    0.2000  p=0.000326      <- what the code reports for F5-H1
2024-only effect/p: 0.0000  p=1.0           <- what the spec requires
```

A discovery-only artefact therefore passes the replication gate. This alone
prevents registration: the discovery/replication split, the central control
in this family, is not in force for F5-H1. (F5-H2's extreme buckets *are*
correctly restricted to 2024.)

**B2 — the FDR correction runs over m=3, the frozen record says
`"fdr_m": 2`. REPRODUCED** (`fdr_input` = `F5-H1`, `F5-H2-bottom`,
`F5-H2-top`). Code and the text to be frozen disagree; one must move before
freeze. **Recommendation: amend the SPEC to m=3, not the code to m=2** —
F5-H2 genuinely contributes two tested extreme-bucket statistics, m=3 is the
more conservative and more honest count, and hard call 4's own reasoning
(positive dependence means a small m understates multiplicity) points the
same way. The JSON record's `fdr_m` and the "2-member family (m=2)" wording
in the replication pass rule must be updated in the same diff.

**B3 — no gate is mechanised; every binding threshold is left to human
judgement after the numbers exist.** `H1_EFFECT_FLOOR`/`H2_EFFECT_FLOOR` are
defined and never compared to any effect; `bottom/top_meets_2024_floor` are
reported as booleans and enforce nothing; `population_shift_test` returns
`fatal: True/False` and nothing consumes it; `devig_sensitivity` returns
three conventions' numbers with no sign-survival check. `run_full_evaluation`
returns a bag of statistics and no verdict. That is precisely the
discretionary surface T8 exists to remove — a rescue lever in every
direction. **Required before the first real run: a single `verdict()` that
applies floor, sign, clustered-CI, FDR, bucket-n, chi-square-fatal, de-vig
sign-survival and battery-fatal deterministically, with a regression test
per gate.**

### MUST-FIX-BEFORE-RUN

**M1 — `src.model.family.register` cannot freeze this family. REPRODUCED**
(signature): `register(detectors, path=…)` enumerates detector×market from
detector objects and writes `data/evidence/hypothesis_family.json`. It has
no `family_id`, no member records, and nothing that accepts the JSON block
above. The freeze mechanism named in the spec does not exist for a family of
this shape. Either a small addition to `family.py` (reported, not made) or
an explicitly named standalone freeze file is required; `benjamini_hochberg`
/ `FDR_Q` are reused unchanged either way.

**M2 — the A5 population-shift kill ALREADY FIRES, feature-side, before
registration. REPRODUCED, no outcome read.** 2023 tercile occupancy
531/532/534; 2024 occupancy under the frozen 2023 edges 768/668/649;
chi-square = 12.403 on 2 df, **p = 0.00203 < 0.01 → FATAL**. F5-H2's
replication leg is therefore a pre-determined kill: it cannot pass, and this
was knowable before any outcome existed. Registering F5-H2 anyway is
defensible and honest, but **the spec must state this now**, on the face of
the pre-registration — otherwise the same number, produced after the run,
reads as a discovered excuse rather than a pre-registered fact. The 2024
favourite mix is materially shifted (bottom tercile over-populated by 11%),
which is itself a reportable finding about the market, not a defect.

### NOTE

- **N1 — tercile edges are index quantiles, not exact 33.3/66.7
  percentiles.** `fit_terciles_2023` takes `values[n//3-1]` /
  `values[2n//3-1]` and `_assign_buckets` uses `< lo` / `>= hi`, giving
  531/532/534 rather than an exact split. Deliberate (matches
  `battery._quartile_edges`) and harmless, but the frozen text says
  "33.3/66.7 percentiles"; the code's convention should be the frozen
  wording.
- **N2** — `_verify_row_shape` is applied to H1 rows only, never to the H2
  rows (identical source today, so no live divergence).
- **N3** — `chi_square_p_df2` treats the 2023 proportions as known rather
  than estimated (df=2); mildly anticonservative, negligible at n=1,597, and
  it fires against F5-H2 rather than for it.
- **N4** — the A1 two-way audit is offline (`docs/F5_TIE_AUDIT.md`: zero
  three-way books across 4,298 OK games, ≥5-book gate intact) and is **not**
  re-checked at run time; the price-payload hash covers only `away_price`
  and `home_price`, so a later-added draw price would move neither hash.
  Satisfied today; the audit must be re-run if the store is ever re-fetched.
- **N5 — leakage and PIT: clean.** Tercile edges and bucket floors depend on
  `p_fav` only; `dry_run=True` sets `won=None` on every row and never calls
  `discovery.evaluate` or `battery.run` (asserted in-module and confirmed on
  the real stores). `winner` is read only to apply the already-frozen
  decided/tie gradeability definition. No `actual_first_pitch`, no
  settlement timestamp, no 2025/2026 row. Hash guards are real: both hashes
  are re-verified before rows are built and raise, never filter.
- **N6 — test quality: the PIT guards are genuinely armed.** Mutation check:
  neutering `_verify_window`'s loop produced 3 test failures; reverted. The
  `PoisonDict` helper makes an `actual_first_pitch` read an assertion
  failure. However, **there is no test for any of B1-B3** — nothing fails if
  the H1 leg is pooled, if the FDR m changes, or if a floor is ignored,
  because none of those behaviours is implemented to test.

### Decisions on the three open items

1. **`family_id`.** Keep `F5_MONEYLINE_CALIBRATION_2026H1`. A repo-wide
   search finds no competing convention — `family.py` has no family-id
   concept at all (M1). The string is adopted as the convention; the record
   is frozen at an explicitly named path, not by overloading
   `data/evidence/hypothesis_family.json`, which belongs to the detector
   family and must not be co-opted.
2. **Price-payload hash serialization.** RESOLVED and already normative in
   code: `src.research.f5_universe.price_payload_hash` — per row
   `{game_pk (str), snapshot_at, books: [{key, away_price, home_price}]}`,
   books sorted by `key` (`None` last), entries sorted by `int(game_pk)`,
   serialized `json.dumps(…, separators=(",", ":"), sort_keys=True)`,
   UTF-8, sha256. `last_update` deliberately excluded. That function, at its
   current revision, IS the specification; recorded value
   `f2ff7b748b1b76f1702cfe2b29750f684e554ffe2c773887a04f132bf2275ec7`.
3. **n ≥ 300 on the middle tercile.** It **applies to all three terciles**.
   The middle bucket is descriptive for the effect but is an *input* to the
   A5 chi-square, which consumes all three occupancies; an under-populated
   middle would distort the kill test. Consequence is unchanged in practice
   (2024: 768/668/649, all clear), and a middle-bucket shortfall is reported
   as blocked-coverage for F5-H2's replication leg, never as a loser.

ADVERSARIAL VERDICT: FAIL — B1 (F5-H1 evaluated on the pooled universe; no 2023 screen leg implemented), B2 (FDR m=3 in code vs. m=2 in the frozen record), B3 (no gate mechanised — floors, bucket-n, chi-square-fatal and de-vig sign-survival are all advisory), with M1 (no working freeze mechanism) and M2 (A5 already fatal, must be pre-registered as such) required in the same pass.

## Post-adversarial amendments — 2026-09-04

Fixes to the five reproduced findings above (B1, B2, B3, M1, M2) plus the
three NOTES items, made in `src/research/f5_eval.py` and its tests in the
same pass. This section amends the FINAL SPECIFICATION above; where the two
disagree, this section governs. Nothing here was written after any outcome
was read — the underlying fixes are structural (row selection, gate
mechanisation, a freeze file), not a threshold moved to rescue a result.

**B1 fix — the two-leg design is now load-bearing, not aspirational.**
`run_full_evaluation` builds `h1_rows`/`h2_rows` once, splits each by
`season`, and from there on treats the two halves as genuinely different
legs:
- **Screen leg (2023 only):** `evaluate_h1_screen` (H1) and
  `evaluate_h2_bucket_screen` (H2's two extreme terciles) check sign +
  point estimate ≥ floor only — no CI, no FDR, per the binding screen-leg
  rule above. Nothing from this leg ever enters the FDR correction.
- **Replication leg (2024 only):** `evaluate_h1`/`evaluate_h2_bucket` are
  now always called with 2024-only rows inside `run_full_evaluation` — the
  pooled 3,682-row call the review reproduced is gone. The p that enters
  BH-FDR, and the CI checked against zero, are both 2024-only.
- **Battery on the 2024 leg only:** `run_battery` is called with the
  2024-only rows for both hypotheses (H2 already did this; H1 did not).
- F5-H1 is never evaluated against the pooled universe for any inferential
  purpose again — pooled statistics are not computed for H1 at all in
  `run_full_evaluation`.

**B2 fix — the frozen record moves to m=3, not the code to m=2.** As the
review recommended: F5-H2 genuinely contributes two tested extreme-bucket
statistics (bottom and top), so the FDR family for this pre-registration is
`{F5-H1, F5-H2-bottom, F5-H2-top}`, m=3. The **replication pass rule** above
("`... over the full 2-member family (m=2)`") is superseded: read it as
m=3. The frozen JSON record's `fdr_m` field is likewise `3`, not `2`.
`src/research/f5_eval.py` defines `FDR_M = 3` and `run_full_evaluation`
raises `F5EvalError` if the p-values it hands to `benjamini_hochberg` ever
number something other than `FDR_M` — B2 cannot silently reappear as a
pooled/unpooled miscount. `freeze_family()`'s record and `FDR_M` are
cross-checked by `_verify_frozen_family` at run time and by a dedicated
regression test (`test_fdr_m_matches_frozen_record`).

**B3 fix — every gate is now a boolean computed by code, with a single
`verdict` field per hypothesis.** `run_full_evaluation` computes, per
hypothesis (F5-H1, F5-H2-bottom, F5-H2-top): `screen_passes`,
`bucket_n_ok` (H2 only), `replication_sign_agrees`,
`replication_ci_excludes_zero`, `survives_fdr`, `devig_sign_survives` (H2
only, `True` by construction for H1 since that sensitivity is report-only),
`population_shift_fatal` (H2 only, `False` by construction for H1), and
`battery_survives`. `compute_verdict()` combines them, in this fixed
precedence, into exactly one of:

1. `POPULATION_SHIFT_FAIL` — the A5 chi-square is fatal (H2 only; checked
   first because M2 pre-registers it as decided before any outcome).
2. `SCREEN_FAIL` — the 2023 screen leg fails sign/floor.
3. `REPLICATION_FAIL` — the 2024 bucket-n floor is unmet (H2,
   blocked-coverage), or the 2024 sign disagrees / CI includes 0 / FDR
   fails.
4. `DEVIG_SIGN_FAIL` — the extreme-bucket effect does not keep its sign
   under all three de-vig conventions (H2 only).
5. `BATTERY_FAIL` — the frozen battery flags a fatal rule.
6. `SURVIVOR` — every gate above cleared.

No reader ever infers a verdict from the raw statistics again; `verdict` is
the single field a downstream consumer reads. `tests/test_f5_eval.py`
carries one regression test per gate, each flipping only that gate's input
and asserting the verdict changes to the matching failure code (and back to
`SURVIVOR` when every gate is satisfied).

**M1 fix — a standalone freeze mechanism.** `src.model.family.register`
cannot hold this family's shape (M1, reproduced: it enumerates
detector×market and has no `family_id`/member-record concept, and its file
belongs to the detector family, not this one). `f5_eval.freeze_family(path)`
is the standalone mechanism named in the FINAL SPECIFICATION's "Preconditions"
section:
- Writes an immutable JSON record — `family_id`
  (`F5_MONEYLINE_CALIBRATION_2026H1`), the three FDR members, both effect
  floors, the discovery/replication split, `fdr_q`, `fdr_m` (3),
  `battery_rules_version` (frozen `RULES_VERSION`), the universe identity
  hash, the universe price-payload hash, `spec_sha256` (a sha256 over the
  FINAL SPECIFICATION section plus this amendments section, computed by
  `f5_eval.spec_sha256`), and a UTC timestamp — to
  `data/research/f5/family_frozen.json` (tracked in git, alongside
  `universe_frozen.json`; not gitignored under `data/`).
- **Refuses to overwrite** an existing record (raises `F5EvalError`);
  re-registering the family is a reviewed commit that deletes the old file
  first, exactly like `family.register`'s own refusal.
- `run_full_evaluation` calls `_verify_frozen_family` immediately after
  `verify_universe` and **refuses to run** (raises `F5EvalError`) unless
  the record exists, its universe hashes match the ones just re-verified,
  its `spec_sha256` matches this document's current FINAL SPECIFICATION +
  amendments text, and its `fdr_m` matches `FDR_M`. This module does not
  call `freeze_family()` against the real path itself — that is a
  deliberate, separate, reviewed act, not something an evaluation run
  performs on its own behalf.
- Tests cover: refuse-overwrite (freezing twice raises on the second call),
  refuse-run-without-record (`run_full_evaluation` raises when no record
  exists), and refuse-run-on-spec-drift (a frozen record whose
  `spec_sha256` no longer matches the current document raises).

**M2 — pre-registered: F5-H2's replication leg is a `POPULATION_SHIFT_FAIL`
before any outcome exists.** The A5 chi-square kill (2023 tercile
occupancy 531/532/534; 2024 occupancy under the frozen 2023 edges
768/668/649; χ²=12.403, df=2, p=0.00203 < 0.01) already fires, feature-side,
on today's frozen universe — this was true before this amendment was
written and remains true at registration. This is stated here, on the face
of the pre-registration, precisely so that the same number produced after
the run reads as a pre-registered fact and not a discovered excuse:
- F5-H2's confirmatory verdict is `POPULATION_SHIFT_FAIL` at registration,
  determined by `compute_verdict`'s first gate, before `screen_passes`,
  `replication_sign_agrees`, or any other 2024-outcome-dependent gate is
  even consulted for promotion purposes.
- The 2023 screen-leg and 2024 replication-leg statistics for F5-H2 (effect,
  p, CI, per-book diagnostics) are still computed in full and published —
  `run_full_evaluation` never skips computing them because the population
  shift already killed promotion. They are exploratory/report-only for
  F5-H2, exactly as the FINAL SPECIFICATION's confirmatory/exploratory
  hierarchy already allows for non-extreme-tercile shape statistics; the
  population-shift kill extends that same report-only status to the
  extreme-tercile statistics themselves once A5 has fired.
- **F5-H2-bottom and F5-H2-top still count in the FDR family, m=3,
  regardless.** The population-shift kill is a verdict override, not a
  reason to shrink the family — B2's m=3 stands whether or not either
  bucket can be promoted. Removing a doomed-but-pre-registered hypothesis
  from the denominator after learning it is doomed is exactly the kind of
  count-shrinking this family's FDR correction exists to forbid.

**NOTES fixes:**
- **N1 (exact quantile method).** `fit_terciles_2023` uses the nearest-rank
  method on the sorted 2023 `p_fav` values: for `n` values, the two interior
  edges are `values[floor(n/3) - 1]` and `values[floor(2n/3) - 1]` (0-indexed,
  clamped to `0`), i.e. the value at or below which the requested 33.3rd/
  66.7th percentile of the sample falls — matching `battery._quartile_edges`'s
  existing convention so a degenerate band collapses the same way whether it
  is quartile- or tercile-shaped. The wording "33.3/66.7 percentiles" in the
  FINAL SPECIFICATION above means this nearest-rank method specifically, not
  a linear-interpolation percentile — recorded here so two independent
  re-implementations agree on the exact split (531/532/534 on the real 2023
  discovery set).
- **N2 (H2 row-shape verification).** `run_full_evaluation` and `run(dry_run=True)`
  now call `_verify_row_shape` on `h2_rows` as well as `h1_rows` — both must
  independently prove the exact 3,682/1,597/2,085 denominator and window,
  not inherit it by construction from H1's already-verified rows.
- **N3 (df=2 approximation, documented).** `chi_square_p_df2` treats the
  2023 bucket proportions as known constants (fixed from the frozen 2023
  fit) rather than themselves estimated from a finite sample, so the test
  statistic is compared to an exact chi-square(df=2) reference distribution
  rather than to the technically-correct reference for a two-sample
  goodness-of-fit test with estimated expected proportions. This is
  mildly anticonservative (it understates the true p slightly), the
  understatement is negligible at the frozen universe's n=1,597 2023
  sample, and — because it fires *against* F5-H2 (as a fatal population
  shift), not for it — the anticonservative direction cannot manufacture a
  promotion; at worst it fires the kill slightly more readily than the
  fully-correct test would, which is the safe direction for a kill switch.

---

## Adversarial re-review — 2026-09-04

Re-attack of B1, B2, B3, M1, M2 and NOTES N1-N3 against commit `0646c0e`
(main checkout, not a worktree). No outcome value read; `freeze_family()`
never called against the real `data/research/f5/family_frozen.json` (which
does not exist); no `src/` edit kept — the two mutations below were reverted
immediately (`git diff src/` clean). `python3 -m unittest tests.test_f5_eval -q`
and `f5_eval.run(dry_run=True)` on the real store: 3,682 rows, 1,597/2,085,
2024 tercile occupancy 768/668/649, both hashes verify.

**B1 — FIXED.** `run_full_evaluation` now screens on 2023 (`evaluate_h1_screen`,
`evaluate_h2_bucket_screen`, sign+floor only) and replicates on 2024
(`evaluate_h1(h1_2024)`, CI + FDR); no pooled statistic is computed for
inference. **But the fix was unpinned:** mutating `evaluate_h1(h1_2024)` back
to `evaluate_h1(h1_rows)` — the exact reported defect — left all 63 tests
green, because the B1 tests exercise the helpers and nothing asserted the
wiring. Fixed here in tests only: `TestB1WiringInRunFullEvaluation` runs
`run_full_evaluation` end-to-end on a synthetic two-season set (60 rows 2023 /
90 rows 2024, data-shape and freeze guards patched out) and asserts the
replication leg graded exactly 90 rows, the screen leg exactly 60, and no
battery call ever received a 2023 row. Re-mutating both the H1 result and the
H1 battery back to pooled now fails that test; reverted.

**B2 — FIXED.** `FDR_M = 3`, `run_full_evaluation` raises if the p-list it
builds is any other length, `_verify_frozen_family` refuses to run when the
frozen record's `fdr_m` disagrees, and the amendment supersedes the m=2
wording in the replication pass rule. Verified by mutation of `FDR_M` (tests
fail) — the spec text and the code now agree.

**B3 — FIXED.** `compute_verdict()` returns exactly one of
`POPULATION_SHIFT_FAIL / SCREEN_FAIL / REPLICATION_FAIL / DEVIG_SIGN_FAIL /
BATTERY_FAIL / SURVIVOR`, with the population-shift kill checked first, and
one regression test per gate flipping only that gate's input. Floors, bucket-n,
de-vig sign-survival and the chi-square kill are all consumed by code; no
discretionary lever remains between the statistics and the verdict.

**M1 — FIXED.** `freeze_family()` writes an immutable record (family_id,
three members, floors, split, `fdr_q`/`fdr_m`, `battery_rules_version`, both
universe hashes, `spec_sha256`, timestamp), refuses to overwrite, and
`run_full_evaluation` aborts unless the record exists and still matches the
live universe hashes, `FDR_M`, and the spec text.

**M2 — FIXED.** The already-fatal chi-square (χ²=12.403, df=2, p=0.00203) is
now pre-registered as F5-H2's confirmatory verdict at registration, the
extreme-bucket statistics are still computed and published as report-only,
and both buckets still count in the m=3 family. Reproduced unchanged on the
current store.

**N1/N2/N3 — FIXED** (nearest-rank convention documented as normative, H2 rows
get `_verify_row_shape` in both entry points, df=2 approximation documented
with its direction of error).

### Remaining items — MUST-FIX-BEFORE-RUN (neither blocks registration)

**R1 — the B1 fix silently unarms a FATAL battery rule, and the skip is not
recorded. REPRODUCED.** The battery now runs on the 2024-only leg, so
`_season_split` (rule 1, in `battery.FATAL_CHECKS`, the leave-one-season-out
check the FINAL SPECIFICATION names) sees a single season and can never fire.
On 400 synthetic 2024 rows it reports
`{"seasons": {"2024": …}, "fatal": false}` — a full, passing report — and
does **not** appear in `run_battery`'s `skipped_checks`, so A4's own rule
("a fatal rule that is quietly inert is exactly the unremembered kill-test
the battery exists to prevent") is violated for rule 1 exactly as it was for
rule 3. Fix required in `src/` (not made here): record `season_split` as
structurally unarmed on a single-season leg, and report the pooled
two-season split as a named report-only diagnostic. An unarmed kill test can
only fail to kill, so this cannot manufacture a promotion — but it must be
recorded before the run, not discovered in it.

**R2 — `spec_sha256` hashes to end-of-file, so any later append changes the
registered spec. REPRODUCED.** `_extract_spec_text` takes everything after
`## Post-adversarial amendments` to EOF; appending this very section moved
the hash from `b65e0551…` to `b6d7adce…`. Nothing is frozen yet, so nothing
broke — but the freeze must happen *after* this commit, and the extraction
should be bounded by the next `## ` heading (or the frozen record should
carry its own copy of the spec text) so the family record cannot be
invalidated by unrelated appended review notes.

**R3 — NOTE.** `_replication_gate` does `ci.get("low", 0) > 0`, which raises
`TypeError` when `clustered_bootstrap` refuses (`low`/`high` are `None` with
fewer than two distinct dates). Unreachable on the real 2024 legs; it fails
loud rather than silently, so it is a robustness note only.

**PIT / leakage / hash guards: clean, unchanged.** `dry_run` still sets
`won=None` on every row and never calls `discovery.evaluate` or
`battery.run`; tercile edges and bucket floors remain feature-side; no
`actual_first_pitch`, settlement timestamp, or 2025/2026 row is read; the
window guard is still mutation-armed.

ADVERSARIAL VERDICT: PASS — register (with R1 and R2 fixed before the first evaluation run, and the freeze taken after this commit).
