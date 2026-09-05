# TOTALS_FULLGAME_2026H1 — Research Results (Post-Mortem)

Family ID `TOTALS_FULLGAME_2026H1`. Pre-registration: `docs/PREREG_TOTALS_FAMILIES.md`
(FINAL SPECIFICATION + "Post-adversarial amendments — 2026-09-05"). Methodology
decisions: `docs/TOTALS_METHODOLOGY.md`. Population/coverage audits:
`docs/TOTALS_POPULATION_AUDIT.md`, `docs/TOTALS_UNJOINED_AUDIT.md`,
`docs/TOTALS_M2_COVERAGE.md`.

## Verdict (headline)

**M1 (confirmatory): POPULATION_SHIFT_FAIL.** No survivor. Zero survivors is
a valid result and is reported as such — nothing here is promoted, traded,
or carried forward as an edge.

**M2 (exploratory, pre-determined): POPULATION_SHIFT_FAIL**, as registered
before any outcome was read (gate D3).

## Hypotheses

- **TOTALS-M1** (confirmatory) — "Full-population Over/Under closing-line
  calibration." Half-point-primary population, ≥3-book floor. Direction
  fixed by the 2023 screen leg's own sign (D2/amendment). Screen leg 2023,
  replication leg 2024. `disclosed_prior_exposure`: V7 2.3 proxy (Under
  54.6–56.9%, Over 40.4–42.5%) — even a survivor would be a disclosed-exposure
  calibration measurement, not a fresh discovery (D5 HC3).
- **TOTALS-M2** (exploratory, pre-determined, non-confirmatory) —
  `combined_starter_groundball_share` tercile partition, edges fit on 2023
  only. Per gate D3, its `POPULATION_SHIFT_FAIL` verdict was fixed at
  freeze time from feature-side counts alone (χ²=18.34 pre-freeze estimate,
  final χ²=18.9076), before any outcome was read. It was excluded from the
  confirmatory BH-FDR family for that reason, not evaluated and then cut.

## Denominator and exclusion ledger

Regular-season universe (`universe_frozen.json`, `content_hash`
`2f4f7fcf...` truncated, see Audit Trail):

| Season | Joint (floor ∧ half-point) n |
|---|---|
| 2023 (screen) | 1,296 |
| 2024 (replication) | 1,288 |

Exclusion ledger (from the same freeze, applied before either leg's n above):

| Reason | Count |
|---|---|
| not_joint (fails book-floor/half-point/settlement join) | 2,175 |
| no_closing_snapshot | 169 |
| postponed | 30 |
| postseason | 14 |
| all_star | 1 |
| not_joined_to_settlement (post-join settlement gap) | 45 |

`joint_total` (both seasons before per-season split) = 2,584.

`fdr_m = 1` (M1 alone; M2 excluded from FDR per D3). BH-FDR at q=0.10 with
m=1 reduces to p ≤ 0.10, strictly weaker than the binding two-sided 95%
date-clustered CI gate — **the FDR step does no work in this family**, and
no multiplicity credit is claimed from it. `fdr_m1_only` in
`m1_family_frozen.json`: p=0.616662, `survives_fdr: false`.

## Universe / freeze hashes

- `universe_frozen.json` → `content_hash` `2f4f7fcf58654db1e2f18bcb49242cb9d0a95d971d78acb8649adc15d532e7d9`
- `m1_family_frozen.json` → `price_payload_hash` `b2e6dbf9b12952bb8b29129a19d5a0475af9de37b7f8703797c83196ca6d8df2`, `verified: true`

## M1 screen leg (2023, n=1,296)

Effect (proportional de-vig, primary): **−1.14pp** (screen `effect: -0.01138`,
also reported as −0.01141 multiplicative / −0.01140 shin — see de-vig table
below). Sign is **UNDER-favouring**, consistent with the disclosed V7 proxy
direction (Under-favoured). `expected_sign: -1` per the pre-registered
`direction: fixed_by_2023_screen_leg_own_sign` rule.

Screen gate (D2, sign-and-point-estimate-only, no CI required at this n):
effect floor is **3.0 percentage points** (raised from the draft's 1.5pp
per D2, because 1.5pp did not clear the ~2.7pp per-leg MDE). −1.14pp is
below the 3.0pp floor → **SCREEN_FAIL on point estimate.** `screen.
passes_screen: false`, `screen.cannot_tell: true` in `m1_family_frozen.json`.

## M1 replication leg (2024, n=1,288)

Effect: **+0.72pp** (`effect: 0.00722`), p=0.616662, date-clustered 95% CI
`[−2.04pp, +3.50pp]` (`ci.low: -0.02043`, `ci.high: 0.03495`, 182 clusters,
2,000 resamples). Hit rate 50.62% vs mean implied probability 49.90%.

This is a **sign flip** relative to the screen leg (−1.14pp → +0.72pp) and
falls inside the pre-registered CANNOT_TELL band (0.0–3.0pp,
`cannot_tell_band_pp` in `m1_family_frozen.json` freeze). Replication gate
fields: `sign_agrees: false`, `floor_ok: false`, `ci_excludes_zero: false`,
`cannot_tell: false` (the replication-gate `cannot_tell` flag reflects the
gate mechanics, not a separate judgment call — see verdict precedence below).
`economically_meaningful.passes: false` (a sub-1pp edge is smaller than the
vig on a single bet and is not tradeable regardless of significance).

## Population-shift gate (fatal, decides the verdict by precedence)

Pre-registered kill (`population_shift_kill`, D-B1/B-A2 in
`PREREG_TOTALS_FAMILIES.md`): fatal when either bucketing's replication-leg
occupancy differs from the screen-leg-fit expected distribution at p<0.01.

| Bucketing | χ² | df | p | Fatal |
|---|---|---|---|---|
| Line bucket | 281.66842 | 5 | ≈0.0 | yes |
| Book-count bucket | 367.66684 | 1 | ≈0.0 | yes |

Both bucketings fire. Per the pre-registered precedence, a fatal
population-shift result **overrides** the (already-failing) screen and
replication readings: **verdict = POPULATION_SHIFT_FAIL.** This is why the
top-level `m1_family_frozen.json` verdict is `POPULATION_SHIFT_FAIL` rather
than `SCREEN_FAIL` — the population-shift gate is checked and, when fatal,
takes precedence over the sign/floor/CI verdicts, which are still reported
above for completeness.

## De-vig sensitivity

All three de-vig methods agree in sign and magnitude on both legs (M1's
`devig_sign_survives: false`):

| Method | Screen (2023) effect | Screen p | Replication (2024) effect | Replication p |
|---|---|---|---|---|
| Proportional (primary) | −0.01138 | 0.392598 | +0.00722 | 0.616662 |
| Multiplicative | −0.01141 | 0.390962 | +0.00728 | 0.613375 |
| Shin | −0.01140 | 0.391511 | +0.00726 | 0.614481 |

`economically_meaningful.passes` is `true` on the screen leg only (−1.14pp
crosses the 1pp economic-meaningfulness bar mechanically) and `false` on
the replication leg; this does not rescue the screen result, which still
fails the 3.0pp confirmatory floor.

## Falsification battery (v2.0.0, fingerprint `ac74c7a7f715f9ec`)

Run on the replication leg. `survives: false`.

- **`extreme_removal` — FATAL.** Dropping the 10 dates contributing most to
  the effect flips the sign again (effect −0.01582, p=0.236971, n=1,204),
  crossing zero from the already-positive replication effect. Dropped dates:
  2024-03-28, 03-30, 06-05, 06-09, 06-25, 07-09, 07-27, 07-29, 08-11, 08-30.
- `book_concentration` — skipped (no `book` key present).
- `dose_response` / `threshold_sensitivity` — skipped (no dose_key configured).
- `team_concentration` — skipped (no `team` key present).
- `season_split` — skipped by design: this is a single-season replication
  leg, so leave-one-season-out is not evaluable (B1/D2).
- `favorite_underdog`, `home_away`, `price_bands` — report-only, not fatal.
  `home_away` splits are both n=0 (below the 30-row floor, reported never
  judged — anchoring likely absent for this population). `favorite_underdog`:
  favorite effect −0.00002 (n=625, p=0.999401), underdog effect +0.01403
  (n=663, p=0.488866), neither judged fatal by the battery.

The battery result (already-fatal on `extreme_removal` alone) is consistent
with, and independently sufficient to fail, the family.

## Integer-line stratum (report-only, never a rescue)

D6(i) lever: P(over | no push) on the adjacent integer-line population,
report-only forever, cannot substitute for or promote over the half-point
primary.

| Season | n (no push) | Overs | P(over\|no push) |
|---|---|---|---|
| 2023 | 980 | 504 | 0.5143 |
| 2024 | 986 | 483 | 0.4899 |

Both are near 0.50 in opposite directions from each other; reported and set
aside per the pre-registered rule.

## M2 (exploratory, pre-determined POPULATION_SHIFT_FAIL)

Feature: `combined_starter_groundball_share`, tercile edges fit on 2023 only.
Coverage (both-sides-present join rate): 2023 = 61.1%, 2024 = 84.9%
(Δ=23.8pp). Occupancy χ²=18.9076, df=2, p=0.0001 < 0.01 → fatal, matching
the pre-freeze estimate that triggered D3. Per D3, M2 was registered with
its verdict **pre-set** before any outcome was read, excluded from the
confirmatory BH-FDR family (`excluded_from_fdr: true`, m stays 1), and is
reported exploratory-only, non-confirmatory, non-promotable. Result:
`verdict: POPULATION_SHIFT_FAIL`, as pre-registered — not a discovery, a
registration outcome landing where it was expected to land.

## Final verdict table

| Member | Role | Verdict | Reason (precedence) |
|---|---|---|---|
| TOTALS-M1 | Confirmatory (m=1) | **POPULATION_SHIFT_FAIL** | Fatal on both population-shift bucketings (line χ²=281.7 p≈0; book-count χ²=367.7 p≈0), which override the already-failing screen (SCREEN_FAIL, −1.14pp < 3.0pp floor) and CANNOT_TELL replication (+0.72pp, CI crosses zero, sign flip) |
| TOTALS-M2 | Exploratory, pre-determined, excluded from FDR | **POPULATION_SHIFT_FAIL** | Pre-registered per D3 from feature-coverage-shift occupancy test before outcome was read |

**Zero survivors.** This is a valid, published-loser result.

## What was learned

1. **No over/under edge is claimed at the close.** Both legs disagree in
   sign, the replication CI spans zero, and the extreme-removal battery leg
   flips sign on its own — three independent reasons the family would have
   failed even absent the population-shift gate.
2. **Methodological lesson about the gate itself, to carry into the NEXT
   pre-registration, not to re-litigate this one.** The line-bucket
   population-shift gate, as written, tests replication-leg occupancy
   against the screen-leg-fit distribution. For a full-population
   calibration hypothesis (M1), that occupancy is driven mechanically by
   the league-wide run-scoring/line environment, which moved materially
   between 2023 and 2024 (2024 closing lines were shifted lower). The gate
   as constructed therefore measures **league scoring drift between
   seasons**, not sample comparability failure of the kind it was designed
   to catch (e.g. a partition feature whose coverage mechanism changed, as
   with M2). Similarly, the book-count gate fired on a 5-book-closing share
   moving from 0.15% to 2.3% of the population — a real but small
   compositional change, amplified to χ²=367.7 by the large n.
3. **This is a finding about gate design, not grounds for action here.**
   Stated plainly per task instruction: this does **not** license
   re-bucketing the line or book-count buckets, changing the 3.0pp floor,
   or treating either season individually as a rescue for the family. The
   pre-registered gate fired exactly as written and the verdict stands as
   POPULATION_SHIFT_FAIL. The lesson is scoped to the next pre-registration
   design, where a shift test could instead target comparability-relevant
   axes (e.g. is the *relationship* between line-implied probability and
   outcome stable, rather than raw occupancy of arbitrary line buckets) —
   decided before results, in a future family's pre-registration.

## What should not be pursued

- No re-bucketing of line or book-count buckets to pass the existing gate.
- No change to the 3.0pp effect floor.
- No single-season rescue (using only 2023 or only 2024 as if the other
  leg didn't exist).
- No claim of an Over or Under edge at the close from this family, in any
  form, forward or retrospective.

## What remains open

A future family may pre-register a population/occupancy-shift test built
on comparability-relevant axes (e.g. relationship stability rather than raw
bucket occupancy), with that design decided before any results are read —
not as a patch to this family, but as a distinct pre-registration.

## Audit trail

```
$ git log --oneline -8 -- data/research/totals/
25c4f3d Totals family evaluation run: results (M1 POPULATION_SHIFT_FAIL, M2 pre-determined POPULATION_SHIFT_FAIL)
b2caa72 Register the confirmatory totals family: frozen record TOTALS_FULLGAME_2026H1
01efa5f Freeze the totals research universe manifest (regular season, 1,296/1,288); queue W24 adversarial review
```

- `run_at` (results): `2026-09-05T00:31:26.870661+00:00`
- `frozen_at` (M1 family freeze): `2026-09-05T00:30:49.605179+00:00`
- `universe_frozen.json` content_hash: `2f4f7fcf58654db1e2f18bcb49242cb9d0a95d971d78acb8649adc15d532e7d9`
- `m1_family_frozen.json` price_payload_hash: `b2e6dbf9b12952bb8b29129a19d5a0475af9de37b7f8703797c83196ca6d8df2` (`verified: true`)
