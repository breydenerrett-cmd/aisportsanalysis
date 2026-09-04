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
