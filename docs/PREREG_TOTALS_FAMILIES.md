# Totals family — pre-registration (DRAFT — PENDING METHODOLOGY REVIEW)

Self-contained draft. Binding inputs: `docs/TOTALS_METHODOLOGY.md` Revision 2
+ re-review (B1-B6), `docs/RESEARCH_V7_TOTALS.md`, `docs/TOTALS_POPULATION_AUDIT.md`,
`docs/TOTALS_RESCHEDULE_AUDIT.md`, `docs/PREREG_F5_FAMILIES.md` FINAL
SPECIFICATION (structural template), `src/research/totals_eval.py` (what the
evaluation path can currently run). No outcome (`total_runs`, `won`, or any
settlement field) is read anywhere in this document or its inputs. Not
registered — `funnel.register_family`/`totals_eval.freeze_family` with real
members has not been called.

## Family denominator

Per B2 (decided on paper, pre-outcome): **exactly two members.**
`combined_primary_pitch_share` is CUT (two-hop mechanism, no added
warrant); bullpen-combined-workload is DEFERRED (unbuilt, unmeasured) —
neither is in this family.

Candidate universe: half-point-primary, per-line ≥3-book-floor population,
"joint (floor AND half-point)" row of `docs/TOTALS_POPULATION_AUDIT.md`
§1-4, **counts as read from `universe_frozen.json` at registration** (this
draft cites the population-audit counts as the best available estimate;
the manifest's own joined figure is authoritative and may differ slightly
after the identity/settlement join):

| leg | season | candidate denominator (joint, half-point) |
|---|---|---|
| screen | 2023 | 1,316 |
| replication | 2024 | 1,313 |

Closing-line definition: latest snapshot in `[commence_time − 6h,
commence_time)`, `commence_time` from that snapshot's own record (R5/A7c),
6h bound frozen per B5 (derived from the timing distribution alone, no
outcome read — `TOTALS_POPULATION_AUDIT.md` §5). Consensus: per-line fair
probability, ≥3-book floor (R2), modal line diagnostic-only. Settlement:
Over/Under/VOID per §2.1, pushes excluded from numerator and denominator
(R3; applies only to the separate integer-line stratum, see M1).

| id | name |
|---|---|
| TOTALS-M1 | Full-population Over/Under closing-line calibration |
| TOTALS-M2 | Combined-starter-groundball-share run-environment partition |

## TOTALS-M1 — full-population OVER calibration (disclosed partially-read member)

Per R6/A10/A11: this is a settlement read on the full graded population
against its own price, identical in kind to F5-H1. It is registered as
**already partially read**, not a fresh test.

- **Disclosed prior exposure:** `docs/RESEARCH_V7_TOTALS.md` §2.3's crude
  ~6h-stale-proxy measurement — **Under 54.6-56.9% / Over 40.4-42.5%**
  across 2023-2025 (R8's reconciled figure; state both sides with their
  percentages, never a bare "X/Y"). This is the proxy measurement, not the
  frozen R5 definition; the frozen definition has not been run.
- **Direction (pre-stated, per A11: not chosen toward the observed split):**
  the family tests calibration of the **OVER** side specifically because
  `totals_eval.py`'s wired path (`TOTALS-OVER-*`) already computes
  `mean(over_win) − mean(p_over)`; stating OVER as the tested side is a
  code-availability choice, not a direction pick made in the direction of
  the disclosed split. The disclosed prior exposure is UNDER-favouring —
  i.e., prior signal points to `mean(over_win) − mean(p_over) < 0`. Per
  A11, this pre-registration does **not** fix a signed pass direction from
  that prior exposure; the pass rule below is sign-agnostic on which side
  of zero, gated instead on CI-excludes-zero + FDR + battery + de-vig
  sign-survival, so no threshold or side was tuned toward the known split.
- **Feature/price:** per-line de-vigged Over probability (R2, ≥3-book
  floor), half-point lines only (primary population).
- **Effect floor:** to be justified from MDE, not asserted — see MDE
  section. Proposed floor **1.5 percentage points**, chosen to sit
  meaningfully above the ~2.7pp per-leg MDE at p≈0.5 is NOT possible at
  this n (see below); the reviewer must set this floor knowing the MDE
  computed here, not a floor invented independently of it.
- **PIT anchor:** the closing snapshot's own `commence_time` (R5/A7c),
  never a post-hoc schedule field.
- **De-vig sign-survival gate:** proportional/power/shin, effect must keep
  sign under all three (R2/A4) — confirmatory, not diagnostic.
- **Half-point vs. integer:** half-point is the primary population (R3/A5);
  integer-line games are a separate, named `P(over | no push)` stratum/
  sensitivity, reported, never pooled into the primary estimate.
- **Population-shift gate:** chi-square on bucket occupancy using the fixed
  edges already computed in `TOTALS_POPULATION_AUDIT.md` §6 (line buckets
  `[5.5,6.5,7.5,8.5,9.5,10.5,11.5]`, book-count buckets `1..5,6+`),
  2023-vs-2024, fatal at p<0.01, decided before any outcome (B1).

## TOTALS-M2 — combined-starter-groundball-share partition

- **Feature:** `combined_starter_groundball_share` = mean(`away_starter_groundball_share`,
  `home_starter_groundball_share`) from the frozen 2023/2024 matrix rows
  (`data/research/matchup_matrix_2023/2024.jsonl`), source module
  `src.research.matrix.row_for_game` / `src.engine.features`. Chosen over
  `combined_starter_velocity_gap` because it has the better PIT coverage in
  both legs (60.1%→84.6% vs 54.6%→75.1%, `RESEARCH_V7_TOTALS.md` §3.1) —
  coverage is the tie-break stated before any outcome is touched.
  `combined_primary_pitch_share` is excluded per B2.
- **Mechanism (stated before results, per B1's requirement):** a start
  pairing where both pitchers keep the ball on the ground suppresses the
  extra-base/home-run contact that drives modern scoring; per-side pricing
  may reflect each pitcher's own run prevention but has no stated mechanism
  for pricing the COMBINATION (`RESEARCH_V7_TOTALS.md` §4.1).
- **Missingness rule (A1/R4, must be coded):** the combined feature is
  computed only when BOTH per-side primitives are present; one-sided values
  never stand in for the mean; absence yields `None`, excluded from the
  partition, never imputed.
- **Bucketing:** terciles of the combined feature, edges fit on the **2023
  screen leg only** (feature-side, no outcome), frozen and applied unchanged
  to 2024 (mirrors F5-H2's binding tercile rule).
- **Coverage (both-sides present, matrix rows, feature-side only):** 2023
  n=1,460 (60.1% of 2023 matrix rows); 2024 n=2,056 (84.6%). **This is NOT
  yet intersected with the totals price-gradeable population (M1's 1,316/
  1,313)** — no such join has been run; the true usable n for M2 is
  `min(feature-coverage n, gradeable-price n)` at best, and could be lower
  once both filters (feature presence AND ≥3-book half-point line) are
  applied jointly. Flagged as a hard call below — this must be computed,
  counts-only, before registration.
- **Direction (fixed in advance):** back **UNDER** (higher combined
  groundball share → fewer runs).
- **Effect floor:** to be set from the joint-n MDE once computed (see MDE
  section); provisionally 1pp of hit rate vs. de-vigged Under implied
  probability, matching V7 §4.1's convention, pending the joint-n check.
- **Population-shift gate:** identical structure to M1 — chi-square on
  bucket occupancy of the combined feature's own tercile partition, fit on
  2023, applied to 2024, fatal at p<0.01 (B1's corrected specification: the
  totals analogue conditions on the hypothesis's own feature partition, not
  park/month/division).
- **De-vig sign-survival gate:** proportional/power/shin, extreme-tercile
  effect keeps sign under all three (A4).

## MDE computation

Formula: two-sided 95%, `p≈0.5`, `MDE = 1.96 * sqrt(0.25 / n)` (matches
`PREREG_F5_FAMILIES.md`'s own reported values at n=1597/2085/3682, verified
by recomputation here).

**M1 (full population, per leg, using the population-audit joint counts):**

| leg | n | MDE (p≈0.5) |
|---|---|---|
| 2023 screen | 1,316 | 2.71pp |
| 2024 replication | 1,313 | 2.71pp |
| pooled | 2,629 | 1.92pp |

**M2 per-tercile (using matrix both-sides coverage n, NOT yet intersected
with the price-gradeable population — an upper bound on true n, see the
hard-call flag above):**

| leg | full-leg n | per-tercile n (÷3) | per-tercile MDE (p≈0.5) |
|---|---|---|---|
| 2023 screen | 1,460 | ≈487 | 4.44pp |
| 2024 replication | 2,056 | ≈685 | 3.75pp |

**Honest power statement:** M1's per-leg MDE (~2.7pp) is close to the
proposed 1.5pp starting-point floor stated above under TOTALS-M1 — that
floor as written does **not** clear the MDE and must be raised (to roughly
2.7-3.0pp) or the floor's rationale must change; this draft does not
resolve that tension and flags it for the reviewer rather than picking a
floor that merely produces a nominal pass. M2's per-tercile MDE (~3.75-
4.44pp) is comparable to F5-H2's (3.55-4.25pp) and, like F5-H2, should be
stated a priori as **plausibly underpowered on its extreme terciles at
either leg**, especially once M2's true (feature ∩ price-gradeable) n is
computed and is very likely smaller than the matrix-coverage n used above.
An honest "cannot tell" is an acceptable, complete outcome for M2, not a
design failure.

## Screen-leg pass rule (2023)

Sign + point estimate ≥ floor only, no CI, no FDR requirement on the screen
leg (mirrors F5's binding amendment — at this n a two-sided-CI screen gate
would be closer to a coin flip than a filter).

## Replication pass rule (2024)

Both, jointly, on the 2024 leg, for the pre-registered sign/floor:

1. Two-sided 95% CI, date-clustered (`src.model.discovery`), excludes 0.
2. Passes BH-FDR at q=0.10 over the full frozen family (m=2,
   `src.model.family.benjamini_hochberg`).

Both members additionally require, before being called survivors: the
population-shift chi-square (fatal p<0.01, feature-side, decided before
outcome) and the three-convention de-vig sign-survival gate. All p-values
and intervals are date-clustered (same-slate games share market conditions;
row-independent inference is anticonservative, per F5's identical rule).

## Falsification battery

Frozen `src.research.battery`, `RULES_VERSION 2.0.0`, verbatim, no bespoke
rule for either member: season/price-band/favorite-underdog-analogue
concentration, leave-one-season-out instability, extreme-game dependence,
threshold-sensitivity/spike-signature, dose-response by tercile for M2 and
on the full population for M1. Any fatal flag kills the member outright, no
threshold/bucket redefinition afterward to rescue it.

## Freeze record (fields to be populated at registration, hashes never invented here)

```json
{
  "family_id": "TOTALS_FULLGAME_2026H1",
  "members": [
    {
      "id": "TOTALS-M1",
      "name": "Full-population Over/Under closing-line calibration",
      "market": "totals",
      "line_stratum": "half_point_primary",
      "devig_primary": "per_line_proportional_ge_3books",
      "devig_sensitivity": ["power", "shin"],
      "devig_sensitivity_gates": true,
      "disclosed_prior_exposure": "V7_2.3_proxy: Under 54.6-56.9pct / Over 40.4-42.5pct",
      "direction": "TBD_by_reviewer_not_tuned_to_prior_exposure",
      "effect_floor_pp": "TBD_from_MDE_ge_2.7pp",
      "bucketing": null,
      "population_shift_kill": {"test": "chi_square", "fatal_p_lt": 0.01, "edges": "TOTALS_POPULATION_AUDIT_sec6"}
    },
    {
      "id": "TOTALS-M2",
      "name": "combined_starter_groundball_share partition",
      "market": "totals",
      "line_stratum": "half_point_primary",
      "devig_primary": "per_line_proportional_ge_3books",
      "devig_sensitivity": ["power", "shin"],
      "devig_sensitivity_gates": true,
      "direction": "back UNDER",
      "effect_floor_pp": "TBD_from_joint_n_MDE",
      "bucketing": "tercile",
      "bucket_edges_fit_on": "2023_discovery_only",
      "bucket_floor_n": "TBD_pending_joint_coverage_count",
      "population_shift_kill": {"test": "chi_square_on_own_partition_occupancy", "fatal_p_lt": 0.01}
    }
  ],
  "discovery": {"date_range": ["2023-season"], "n_M1": 1316},
  "replication": {"date_range": ["2024-season"], "n_M1": 1313},
  "screen_pass_rule": "sign_and_point_estimate_ge_floor_only",
  "replication_pass_rule": "two_sided_95pct_CI_date_clustered_excludes_zero_AND_bh_fdr",
  "fdr_q": 0.10,
  "fdr_m": 2,
  "clustering": "date",
  "battery_rules_version": "2.0.0",
  "staleness_bound_h": 6,
  "universe_identity_hash": "PLACEHOLDER_FILL_FROM_MANIFEST_AT_REGISTRATION",
  "universe_price_payload_hash": "PLACEHOLDER_FILL_FROM_MANIFEST_AT_REGISTRATION",
  "excluded_members_permanent": ["combined_primary_pitch_share (B2)"],
  "deferred_members": ["bullpen_combined_workload (B3)"]
}
```

## Exclusion criteria

Non-gradeable rows (no closing snapshot in the frozen `[−6h, commence)`
window, per `TOTALS_POPULATION_AUDIT.md` §1-4: 95/2023, 74/2024 excluded)
are reported as a diagnostic, never silently dropped from the narrative.
Integer-line games are excluded from the M1 primary population by design
(R3) and reported as a separate `P(over | no push)` stratum. The void rate
within the integer stratum is a banded diagnostic against V7's measured
~2.7-3.1%, never a re-filter (A6).

## Confirmatory vs. exploratory hierarchy

**Confirmatory:** TOTALS-M1 (full half-point population), TOTALS-M2
(extreme terciles only; middle tercile and full monotone-gradient shape
are descriptive).

**Exploratory / report-only:** integer-line `P(over|no push)` stratum for
M1; de-vig sensitivity conventions (reported alongside the gating check,
per F5's pattern); book-composition/modal-line diagnostic (R2/A3); per-book
sign replication (battery rule-3 substitute, structurally unarmed the same
way as F5's — one consensus row per game); staleness distribution by
season.

## Failure criteria (written before any result exists)

**TOTALS-M1 fails (published loser) if ANY of:** 2023 screen point
estimate does not clear the floor (once set) with the pre-stated sign;
2024 sign disagrees with 2023, or its CI includes 0, or it fails BH-FDR
(m=2); the de-vig sign-survival gate fails; the population-shift chi-square
is significant at p<0.01; the frozen battery flags any fatal rule.

**TOTALS-M2 fails under the identical structure**, plus fails if either
2024 extreme-tercile bucket falls below its floor (TBD once the joint
feature∩price n is computed) — reported as blocked-coverage, not a loser.

**Both fail together, reported as a two-loser family, if:** the frozen
universe's MDE, on feature-side inspection only, proves insufficient for
either floor once the true per-leg/per-tercile n is confirmed.

**Zero survivors is a valid, complete result for this family.** Nothing
here is written to guarantee a promotion.

## Hard calls for the Opus reviewer

1. **M1's proposed 1.5pp starting floor does not clear its own ~2.7pp
   per-leg MDE.** The floor must be raised (to ~2.7-3.0pp) or justified on
   a different basis (e.g. pooled-MDE 1.92pp with a floor just above it);
   this draft states the tension rather than resolving it, per instruction.
2. **M2's true usable n is unknown.** Matrix both-sides coverage (1,460/
   2,056) has never been intersected with the totals price-gradeable
   population (1,316/1,313) — no join exists yet. This must be computed
   (counts-only, no outcome) before registration; it will likely lower
   M2's per-tercile n and worsen its already-marginal MDE.
3. **M1's direction is deliberately left open** rather than set toward the
   disclosed V7 §2.3 prior exposure (Under-favouring), per A11. The
   reviewer must decide how to state a pre-registered direction for a
   member whose own prior read already points one way without that
   direction being "chosen in the direction of the observed split" —
   this draft's sign-agnostic CI+FDR gate is one way to satisfy A11 but is
   not the only possible resolution, and the reviewer may prefer an
   explicit coin-flip / orthogonal pre-commitment procedure instead.
4. **`src/research/totals_eval.py` only wires M1's OVER-calibration shape.**
   M2 (any feature-partition hypothesis) has no evaluation code today —
   `evaluate_screen`/`devig_sensitivity`/`run_battery` all assume the
   `{won, implied, price}` OVER row shape from `totals_rows.build_over_rows`,
   not a bucketed feature partition. Building M2's tercile-partition
   evaluation (bucket assignment, per-tercile discovery calls, population-
   shift chi-square on the feature's own occupancy) is real engineering not
   yet started, and must exist and pass validation before M2 can run.
5. **Push handling for the integer-line stratum is specified (R2.1/R3) but
   unimplemented** in `totals_eval.py` as far as this draft can tell from
   its docstring (module only names `build_over_rows`, half-point-shaped).
6. **Bucket-floor n for M2's extreme terciles** is left as `TBD` pending
   hard call 2 — propose n≥300 per extreme tercile (F5-H2's convention) but
   this has not been checked against the likely-smaller joint n.
7. **Whether TOTALS-M1 and a future TOTALS-M2-replacement should share one
   family_id or two**, given M2's mechanism/build gap is materially larger
   than M1's — the reviewer may prefer registering M1 alone first and
   deferring M2 to a follow-up family, mirroring how F5 handled B3.

## Methodology review — 2026-09-05

Adversarial methodology review of the DRAFT above. No outcome field
(`total_runs`, `won`, `winner`, any settlement value) was read, printed or
computed from in producing this section; every number below is either a
count, a timing quantile, a feature-side occupancy, or an MDE recomputed
from an n. Where this section disagrees with the draft above, **this
section governs.**

### D1 — Denominator scope: REGULAR SEASON ONLY, exclusions itemised

The denominator is the regular-season, half-point-primary, per-line
≥3-book-floor, closing-snapshot-in-`[−6h, commence)` population, and the
authoritative counts are the manifest's joined figures — **2023 n=1,296,
2024 n=1,288** — not the pre-join 1,316/1,313 of `TOTALS_POPULATION_AUDIT.md`
§1-4, which are superseded here as an estimate. Postseason is excluded not
as a judgment call but because `mlb_results.csv` is `game_type == "R"` only
(`TOTALS_UNJOINED_AUDIT.md` class (d)): the 14 Wild Card/Division Series
events cannot be graded at all, and silently leaving them in the stated
denominator while they are unjoinable would misstate power. The 2023
All-Star Game (class (e)) is an exhibition, not a club game, with a
different scoring process and a different market, and is excluded on
mechanism as well as on availability. The 30 postponed/replayed events
(class (a)) are excluded because the priced event was never played at the
priced commence_time — excluding them is a point-in-time correctness
requirement, not a filter. **Binding:** the exclusion ledger in the freeze
record must carry these four lines with their counts (30 postponed, 14
postseason, 5 doubleheader-nightcap join collisions now FIXED and therefore
INCLUDED, 1 All-Star), plus the 95/2023 and 74/2024 no-closing-snapshot
rows, and the run report must publish the ledger even when nothing surprising
is in it. No exclusion may be added after any outcome is read.

### D2 — M1 effect floor: 3.0pp, and the family is honestly underpowered below it

At the corrected n the per-leg MDE (two-sided 95%, p≈0.5) is **2.72pp
(2023, n=1,296)** and **2.73pp (2024, n=1,288)**; pooled 2,584 gives
1.93pp, but pooling is forbidden here — the two-leg design is load-bearing
(F5 B1 fix) and the replication CI is computed on the 2024 leg alone, so
the pooled figure is not the operative power. The draft's 1.5pp floor is
therefore not merely low, it is inside the noise band of the very leg that
must clear it, and a member that "passes" a floor below its own MDE is
passing on a statistic the design cannot distinguish from zero. **Binding:
M1's effect floor is 3.0 percentage points**, on both the 2023 screen
(point estimate ≥ floor with the screen-declared sign) and the 2024
replication (point estimate ≥ floor in addition to the CI-excludes-zero and
FDR gates), chosen as the smallest round value strictly above the larger
per-leg MDE. This is a real cost and must be stated in the results: **the
family cannot detect a true mispricing smaller than ~2.7pp at either leg,
and any true effect in the 0-3.0pp band will be reported as "cannot tell",
never as a PASS and never as a FAIL of the market's calibration.** A PASS
under this floor therefore means only "an effect at least as large as 3.0pp
was observed and survived every gate", not "no smaller effect exists". The
floor is frozen numerically at registration; it may not be lowered
afterward for any reason, including a near-miss.

### D3 — M2's fate: NOT a confirmatory member; registered as a pre-determined POPULATION_SHIFT_FAIL, exploratory only, m unchanged

M2's pre-registered fatal gate is already resolved against it on
feature-side counts that are legitimately readable now: 2024 tercile
occupancy under frozen 2023 edges gives χ²=18.34, df=2, **p=0.0001 < 0.01**
(`TOTALS_M2_COVERAGE.md`). The F5-H2 precedent permits registering a
determined `POPULATION_SHIFT_FAIL` and still evaluating it exploratorily —
but F5-H2's chi-square outcome was *unknown at freeze time*, which is why
it legitimately counted toward m=3. Here it is known before freeze, so
carrying M2 as a confirmatory FDR member would spend multiplicity budget on
a member that cannot possibly survive, weakening M1 for no informational
gain. **Binding: M2 is registered with `verdict` pre-set to
`POPULATION_SHIFT_FAIL`, excluded from the BH-FDR family, and evaluated
exploratory-only, its result labelled non-confirmatory and non-promotable
in every report.** Replacement was considered and rejected: the only other
LEGITIMATE_TOTALS_FEATURE with 2023-24 PIT coverage is
`combined_starter_velocity_gap`, whose coverage shift (54.6%→75.1%,
Δ=20.5pp) is *worse* than groundball share's and arises from the identical
Statcast-coverage selection mechanism, so it would fail the same gate for
the same reason; every other row of `TOTALS_METHODOLOGY.md` §1.2 is unbuilt,
not PIT-available, or rejected for thinness. **The confirmatory family is
therefore TOTALS-M1 alone, m=1.** Consequence, stated plainly: BH-FDR at
q=0.10 with m=1 reduces to p ≤ 0.10, which is strictly weaker than the
already-binding two-sided 95% date-clustered CI gate, so **the FDR step
does no work in this family and no multiplicity credit may be claimed from
it.** It is retained in the freeze record (`fdr_m: 1`) for mechanical
uniformity only, and the results must say this in those terms rather than
citing "survived FDR" as evidence.

### D4 — Admissibility of a family partitioning on a feature with a 24pp coverage shift

A partition feature whose *availability* moves from 61.2% to 84.9% between
the screen and replication legs is not a stable feature; the two legs
condition on different subpopulations selected by a mechanism (Statcast
pitch-store completeness) that is correlated with team, park and calendar,
and the resulting occupancy shift is exactly what the pre-registered gate
measures. **Binding rule, applying to this and every future totals family:
a feature partition is admissible as a CONFIRMATORY member only if, in a
counts-only pre-registration audit run before freeze, (a) the both-sides
join rate by season is published, (b) |Δ join rate| between screen and
replication legs is ≤ 10pp, and (c) the occupancy chi-square on
screen-fit-frozen edges applied to the replication leg is non-fatal
(p ≥ 0.01).** All three must be reported whether they pass or fail; failing
(b) or (c) demotes the member to exploratory and it does not enter m. M2
fails (b) at Δ=23.7pp and (c) at p=0.0001, which is precisely why D3
demotes it. Note also that M2's per-tercile MDE on the true joint n is
**5.3-6.0pp** (not the draft's 3.75-4.44pp, which used the un-intersected
matrix counts) — even absent the shift, M2 would be underpowered against
any plausible 1pp floor, and its draft "provisionally 1pp" floor is
withdrawn as unusable.

### D5 — Remaining hard calls

**HC1 (M1 floor)** resolved in D2 at 3.0pp. **HC2 (M2 joint n)** resolved:
the join has now been computed counts-only — 792/1,295 and 1,090/1,284 —
and it is worse than the draft feared; see D3/D4. **HC3 (M1 direction)**:
the sign-agnostic two-sided gate is accepted as the A11-compliant
resolution, with one amendment — **the tested sign is fixed by the 2023
screen leg's own point estimate and the 2024 leg must agree with it;** no
sign is imported from the V7 §2.3 proxy, and no coin-flip or orthogonal
procedure is needed because nothing in the pass rule is one-sided. But this
does not make M1 a fresh test: it is a disclosed partially-read member on a
population overlapping the proxy measurement, so **binding: even a full
SURVIVOR verdict for M1 is reported as a calibration MEASUREMENT with
disclosed prior exposure, is not a fresh confirmatory discovery, and may
not promote to any trading decision without an independent forward
out-of-sample leg** (forward capture; 2026-01-01..2026-08-27 remains
SEALED and is not that leg). **HC4/HC5 (code)** — see D7. **HC6 (M2 bucket
floor n)**: moot under D3, but recorded as n≥300 per extreme tercile for
the exploratory read; the observed terciles (263-345) mean the 2023 low/mid/
high and 2024 high buckets sit at or below that floor, a further reason M2
is not confirmatory. **HC7 (one family_id or two)**: **one family_id,
`TOTALS_FULLGAME_2026H1`, with M1 confirmatory (m=1) and M2 recorded inside
it as a pre-determined exploratory failure.** Splitting them would let the
M2 failure disappear from the family's published record; keeping them
together forces the loser to be published alongside the survivor, which is
the point.

### D6 — Outcome-adjacent choices and rescue levers found in the draft

Every `TBD` in the draft's freeze record is a rescue lever if it survives
into registration: `direction`, `effect_floor_pp` (both members),
`bucket_floor_n`. **Binding: no field of the freeze record may be `TBD`,
`PLACEHOLDER`, or reviewer-deferred at the moment `freeze_family` is
called; the hashes are computed from real inputs and the numeric gates are
literal numbers.** Four further levers are closed explicitly: (i) the
integer-line `P(over | no push)` stratum is a second look at the same
question on an adjacent population and is **report-only forever** — it can
never substitute for, rescue, or be promoted over a failed primary; (ii)
the void-rate band against V7's ~2.7-3.1% is a diagnostic and must never
become a re-filter of the denominator (A6); (iii) the 6h staleness bound is
frozen by B5 from the timing distribution alone and may not be re-derived,
widened or narrowed after any outcome is read; (iv) no re-bucketing,
re-tercile, quintile, alternative edge fit, or alternative de-vig
convention may be introduced after a result — the three conventions are
gates fixed in advance, not a menu. Two draft phrasings are also corrected
as outcome-adjacent: "reported as blocked-coverage, not a loser" must not
be used to keep a member alive in the narrative (a blocked member is a
published non-result, and it is *not* a partial pass), and the draft's
"could be lower once both filters are applied" hedge is now a measured
fact, not a hedge.

### D7 — Evaluation code that must exist and pass validation before registration

Required for M1 (confirmatory), all of it before `freeze_family` is called
with real members: (1) `totals_rows.build_universe` producing the D1
denominator with the exclusion ledger as a structured field, plus a test
asserting the four exclusion classes and their counts; (2) per-line
de-vigged Over probability at the ≥3-book floor under **all three**
conventions (proportional primary, power, shin) with the sign-survival
check mechanised as a boolean, not read off a table; (3) date-clustered CI
via `src.model.discovery` on the 2024 leg alone, with a regression test
that a row-independent CI is never what is returned; (4) the
population-shift chi-square on the fixed `TOTALS_POPULATION_AUDIT.md` §6
line and book-count edges, computed feature-side and before any outcome
call in the code path; (5) the frozen `src.research.battery` at
`RULES_VERSION 2.0.0` run on the 2024 leg; (6) a mechanised single
`verdict` field per member over the F5 B3 precedence
(`POPULATION_SHIFT_FAIL` → `SCREEN_FAIL` → `REPLICATION_FAIL` →
`DEVIG_SIGN_FAIL` → `BATTERY_FAIL` → `SURVIVOR`), **with one regression
test per gate that flips only that gate's input and asserts the verdict
changes**; (7) `freeze_family` writing an immutable record with `spec_sha256`
over this document, the universe identity and price-payload hashes, and
`FDR_M = 1` cross-checked at run time against the count of p-values handed
to `benjamini_hochberg`; (8) the B4/validation-item-9 `commence_time`
mutation-armed fixture, which must fail when the anchor is swapped for a
post-hoc schedule field; (9) push handling for the integer stratum
implemented, or the stratum dropped from the report entirely — an
unimplemented specified path is not permitted to appear as a reported
number. For M2 (exploratory), additionally: tercile assignment from
2023-fit frozen edges, the both-sides-or-`None` rule enforced in code with
a test that a one-sided value never stands in for the mean, a dedicated PIT
test for the MEAN recombination itself (`TOTALS_METHODOLOGY.md` §1.2 names
this gap), and per-tercile evaluation calls. **If M2's code is not built,
M2 is reported as `POPULATION_SHIFT_FAIL, not evaluated` — it is not
reported with partial or hand-computed numbers.**

VERDICT: READY FOR FINAL SPECIFICATION AS AMENDED
