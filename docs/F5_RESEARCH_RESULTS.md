# F5_MONEYLINE_CALIBRATION_2026H1 — results

**Status: zero survivors.** All three registered members failed their
pre-registered gates. This is a valid, complete, published result — not a
step toward a retry.

Family: `F5_MONEYLINE_CALIBRATION_2026H1`. Frozen record:
`data/research/f5/family_frozen.json`. Results:
`data/research/f5/results_F5_MONEYLINE_CALIBRATION_2026H1.json` (the sole
source of every number below — transcribed, not recomputed).

## 1. Hypotheses tested (exact definitions)

**F5-H1 — Home-team calibration bias in the F5 moneyline.**
Feature: de-vigged home implied probability `p_home` (primary convention
`proportional`) at the F5 `h2h_1st_5_innings` T-2h snapshot, averaged across
book_count (≥5, median 12). Side: home. Outcome: `home_win` (ties excluded
by construction). Direction (fixed): `mean(home_win) − mean(p_home) > 0`.
Effect floor: 2.0pp. PIT anchor: `scheduled_first_pitch`.

**F5-H2 — Favorite/longshot calibration bias in the F5 moneyline.**
Feature: de-vigged favorite implied probability `p_fav` (≥0.5 by
construction), proportional primary convention, same snapshot. Bucketing:
terciles of `p_fav`, edges fit on the 2023 discovery set only, frozen and
applied unchanged to 2024. Bucket floor: each 2024 bucket ≥300. Direction
(fixed): calibration error `mean(fav_win) − mean(p_fav)` positive in the top
tercile, negative in the bottom tercile. Effect floor: 4.0pp per extreme
tercile. Two binding kill criteria beyond the floor/CI/FDR structure: (a)
de-vig sign-survival across proportional/multiplicative/Shin, (b) chi-square
population-shift test on 2024 bucket occupancy vs. 2023-fit expected thirds,
fatal at p<0.01.

## 2. Denominator: 3 members, m=3, why

Post-adversarial amendment (B2, `docs/PREREG_F5_FAMILIES.md` "Post-adversarial
amendments — 2026-09-04") moved the frozen record from the draft's m=2 to
**m=3**: F5-H2's two extreme terciles are tested as two separate detectors,
`F5-H2-bottom` and `F5-H2-top`, alongside `F5-H1`. `family_frozen.json`:
`"members": ["F5-H1", "F5-H2-bottom", "F5-H2-top"]`, `"fdr_m": 3`,
`"fdr_q": 0.1`. B3 (bullpen gap) is permanently excluded from this family —
never folded in.

## 3. Universe + MDE

| quantity | value |
|---|---|
| eligible universe (all statuses) | 4,315 |
| gradeable (OK ∧ decided) | 3,682 |
| discovery (2023-05-10..2023-12-31) | 1,597 |
| replication (2024-01-01..2024-10-07) | 2,085 |
| family-wide MDE (two-sided 95%, p≈0.5, n=3,682) | 1.62pp |
| universe identity hash (sha256) | `c67508603b14af2c494e13fadeb2a2f039f52df996ab6e12ff6164585e33cd1c` |
| price-payload hash (sha256) | `f2ff7b748b1b76f1702cfe2b29750f684e554ffe2c773887a04f132bf2275ec7` |

Both hashes re-verified at run time (`hashes.verified: true` in the results
file) before any statistic was computed.

## 4. Discovery (2023 screen) outcomes per member

Screen-leg pass rule: sign + point estimate ≥ floor only, no CI/FDR
requirement on this leg (`docs/PREREG_F5_FAMILIES.md`, "Screen-leg pass
rule").

| member | 2023 effect | n | floor | sign vs. required | passes screen? |
|---|---|---|---|---|---|
| F5-H1 | −0.577pp | 1,597 | 2.0pp | required positive, observed negative | **fail** |
| F5-H2-bottom | +4.055pp | 531 | 4.0pp | required negative, observed positive | **fail** (wrong sign) |
| F5-H2-top | −1.663pp | 534 | 4.0pp | required positive, observed negative | **fail** (wrong sign, below floor) |

F5-H1 fails the screen on both sign and floor. Both F5-H2 extreme buckets
fail the screen on sign alone — each measured the *opposite* direction from
its pre-registered calibration-error sign in 2023.

## 5. Replication (2024) outcomes

Date-clustered, two-sided 95% CI. Hit rate is the observed win rate; mean
implied is the de-vigged mean price.

| member | effect | p | 95% CI (clustered) | n | hit rate | mean implied |
|---|---|---|---|---|---|---|
| F5-H1 | −0.884pp | 0.412609 | [−2.964pp, +1.318pp] | 2,085 | 0.5209 | 0.5297 |
| F5-H2-bottom | −3.976pp | 0.020763 | [−7.232pp, −0.643pp] | 768 | 0.4805 | 0.5202 |
| F5-H2-top | +1.772pp | 0.334257 | [−1.684pp, +5.401pp] | 649 | 0.6518 | 0.6340 |

Both F5-H2 buckets clear the n≥300 floor (768 and 649). F5-H1's CI includes
zero (fails replication on CI alone, independent of FDR). F5-H2-bottom is
the only member whose 2024 CI excludes zero — but see §7 and §9.

## 6. Population-shift test (pre-registered, feature-side only)

Chi-square on 2024 tercile occupancy vs. 2023-fit expected thirds, computed
and determined **before any 2024 outcome was read** (feature-side bucket
counts only), fatal at p<0.01:

- chi-square = 12.4029 (task brief cites 12.403), p = 0.002026
- observed 2024 counts: bottom 768, mid 668, top 649
- expected under 2023-fit thirds: 693.26 / 694.56 / 697.18
- **result: FATAL.** p (0.002026) < 0.01. Both `F5-H2-bottom` and
  `F5-H2-top` are killed by this test alone, regardless of any later CI or
  FDR outcome.

## 7. FDR (BH, q=0.10, m=3)

| rank | member | p | BH threshold | survives FDR? |
|---|---|---|---|---|
| 1 | F5-H2-bottom | 0.020763 | 0.033333 | **true** |
| 2 | F5-H2-top | 0.334257 | 0.066667 | false |
| 3 | F5-H1 | 0.412609 | 0.100000 | false |

F5-H2-bottom's raw 2024 p (0.0208) is below its BH threshold (0.0333) and
survives FDR **in isolation**. This does not rescue the member. F5-H2-bottom
is dead on three earlier, independent grounds, any one of which is fatal on
its own:

1. **Sign flip across the screen boundary** — 2023 screen effect +4.06pp,
   2024 replication effect −3.98pp. The 2024 leg replicates the opposite
   calibration error from what the 2023 screen (itself already failing on
   sign) pointed to.
2. **Screen ordering** — the 2023 screen must pass on sign + floor *before*
   the 2024 leg is even eligible for inference; F5-H2-bottom failed that
   screen (§4).
3. **Pre-registered population-shift kill** — determined before any outcome
   was read (§6), fatal at p<0.01, and unconditional on any downstream
   statistic.

FDR survival of one leg's raw p-value does not and cannot rescue a member
that already failed an earlier, pre-registered gate. The gates apply in
order; FDR is the last of several hurdles, not a substitute for the ones
before it.

## 8. De-vig sensitivity (proportional / multiplicative / Shin)

F5-H2's de-vig sign-survival is a **binding pass criterion** (not
diagnostic): the extreme-bucket effect must keep its sign under all three
conventions.

| convention | bottom effect | bottom p | bottom CI | top effect | top p | top CI |
|---|---|---|---|---|---|---|
| proportional (primary) | −0.03976 | 0.020763 | [−0.07232, −0.00643] | +0.01772 | 0.334257 | [−0.01684, +0.05401] |
| multiplicative | −0.03953 | 0.020790 | [−0.07185, −0.00620] | +0.01136 | 0.539411 | [−0.02484, +0.04757] |
| shin | −0.03958 | 0.021040 | [−0.07210, −0.00636] | +0.01578 | 0.393380 | [−0.01938, +0.05230] |

Sign survives all three conventions in both buckets
(`devig_sign_survives: true` in both `h2/bottom` and `h2/top`). This
criterion passes for both — it is the population-shift kill (§6), not the
de-vig criterion, that ultimately kills both F5-H2 members.

## 9. Falsification battery (rules version 2.0.0)

Fingerprint: `ac74c7a7f715f9ec`.

| member | fatal rules fired | `survives` |
|---|---|---|
| F5-H1 | `extreme_removal` | **false** |
| F5-H2-bottom | none | true |
| F5-H2-top | `extreme_removal` | **false** |

F5-H1's baseline effect (−0.884pp) flips sign to +0.707pp once the 10
highest-contributing dates are dropped (n 2,085→1,960) — fatal
`extreme_removal`. F5-H2-top's baseline (+1.772pp) flips to −0.654pp under
the same removal (n 649→607) — also fatal. F5-H2-bottom's battery-only
removal effect stays negative (−1.522pp, n 715) and is not fatal on its
own, but the member is already dead on §4/§6/§7.

Recorded-skipped checks, with reasons (same for all three members):

- **`book_concentration`** — skipped, "no 'book' key present" (both
  hypotheses grade one consensus row per game; rule 3 has no per-row book
  to act on, per spec).
- **`season_split`** — skipped, "single-season leg (2024): season_split
  cannot fire; leave-one-season-out is not evaluable on the replication leg
  by design (B1)".
- **`team_concentration`** — skipped, "no 'team' key present".
- **`dose_response`** — skipped, "no dose_key configured".
- **`threshold_sensitivity`** — skipped, "no dose_key configured".

`favorite_underdog` and `home_away` and `price_bands` splits ran as
report-only (not fatal by design) on all three members; see the results
JSON for the full per-split breakdown.

## 10. Per-book H1 sign replication (all 15 books)

Report-only diagnostic (battery rule-3 substitute), F5-H1's effect
per-book, own de-vigged price:

| book | effect | p | n | sign |
|---|---|---|---|---|
| barstool | −0.00418 | 0.716191 | 1,443 | − |
| betmgm | −0.00714 | 0.361223 | 3,609 | − |
| betonlineag | −0.00643 | 0.399467 | 3,654 | − |
| betrivers | −0.00765 | 0.319104 | 3,657 | − |
| betus | −0.01022 | 0.241464 | 2,988 | − |
| bovada | −0.00696 | 0.368363 | 3,677 | − |
| draftkings | −0.00720 | 0.353460 | 3,583 | − |
| fanduel | −0.01155 | 0.155890 | 3,240 | − |
| lowvig | −0.01098 | 0.209141 | 2,912 | − |
| mybookieag | −0.00587 | 0.475846 | 3,044 | − |
| pointsbetus | −0.00756 | 0.428936 | 2,048 | − |
| superbook | +0.01134 | 0.469399 | 999 | **+** |
| unibet_us | −0.00749 | 0.406379 | 2,335 | − |
| williamhill_us | −0.00665 | 0.392722 | 3,584 | − |
| wynnbet | +0.00136 | 0.920779 | 1,155 | **+** |

13 of 15 books show the same (negative) sign as the pooled F5-H1 effect;
`superbook` and `wynnbet` (the two thinnest books by n) show the opposite
sign. **None of the 15 books is individually significant** at p<0.05. This
is consistent with a small, non-significant pooled effect and normal
per-book noise at these sample sizes — not evidence of book-driven
concentration.

## 11. Exclusions

17 `PRIMARY_SNAPSHOT_UNAVAILABLE` rows are retained in the eligible universe
(4,315) but cannot be graded — they are excluded from the 3,682-row
gradeable set by construction, not silently dropped from the denominator
narrative (`docs/F5_UNIVERSE_FROZEN.md`). No re-bucketing or narrowing was
applied to compensate.

## 12. Final verdicts

| member | verdict |
|---|---|
| F5-H1 | **SCREEN_FAIL** — fails the 2023 screen (wrong sign, below floor); 2024 CI also includes zero; battery fatal on `extreme_removal`. |
| F5-H2-bottom | **POPULATION_SHIFT_FAIL** — fails the 2023 screen (wrong sign); pre-registered population-shift chi-square fatal (p=0.002026); FDR survival in isolation does not override either prior gate. |
| F5-H2-top | **POPULATION_SHIFT_FAIL** — fails the 2023 screen (wrong sign, below floor); pre-registered population-shift chi-square fatal; battery fatal on `extreme_removal`; fails FDR. |

`survives_fdr: false` for F5-H1 and F5-H2-top; `true` in isolation for
F5-H2-bottom, superseded by the verdicts above. **Zero members survive the
full pre-registered gate.**

## 13. Null findings (first-class)

- The F5 T-2h moneyline price shows no home-team calibration bias
  detectable at this universe's 1.62pp resolution (F5-H1: −0.88pp, 95% CI
  [−2.96pp, +1.32pp], n=2,085).
- The point estimate's sign is slightly *negative* — home sides are, if
  anything, marginally **overpriced**, not underpriced. This is the
  opposite sign from B3's n=270 finding referenced in the mission; here it
  is not significant and does not survive the battery, but the direction of
  the (non-significant) point estimate reverses.
- The favorite/longshot calibration signal reverses sign between the 2023
  screen and the 2024 replication in both extreme terciles
  (bottom: +4.06pp → −3.98pp; top: −1.66pp → +1.77pp), and the underlying
  favorite/dog population mix itself shifted materially between years
  (chi-square p=0.002). Whatever signal existed in one season is not the
  same population being measured in the next.

## 14. What was learned

The F5 T-2h price is well calibrated on both axes tested, at the
resolution this universe (n=3,682, MDE 1.62pp) can measure. No member
cleared its full pre-registered gate. Home side is slightly *over*priced
in the 2024 point estimate (not underpriced, and not significant) —
reversing the sign of B3's earlier n=270 observation. The favorite-longshot
signal is unstable in sign across seasons and its population composition
is not stationary year to year; a screen-then-replicate design is doing
exactly what it is for here, catching an unstable discovery-leg finding
before it is mistaken for a real edge.

## 15. What should NOT be pursued

- No re-bucketing of F5-H2 (quintiles, different tercile edges, different
  floors) to chase a fit. The screen already tried terciles with edges
  fixed a priori; different bucketing after seeing 2024 outcomes is exactly
  the rescue-by-threshold-change this program forbids (T8).
- No floor changes to either hypothesis to manufacture a numeric pass.
- No promotion or trading claim from F5-H2-bottom's isolated FDR survival —
  it is dead on the screen and the population-shift kill, both of which
  were determined before FDR was computed.
- No claim of an F5 home-team or favorite/longshot edge of any kind from
  this family. There is none.

## 16. What remains open

The B3 bullpen-gap comparator is explicitly excluded from this family (not
deferred inside it) per the frozen spec, and requires a separate,
owner-authorized full-game T-2h acquisition before it can be registered as
its own family with its own FDR correction. It is blocked on owner
authorization, not on any finding here.

## Audit trail

- Freeze commit: `4b39609` — "Register the F5 calibration family: frozen
  record F5_MONEYLINE_CALIBRATION_2026H1"
- Results commit: `72c0c76` — "F5 family discovery/replication run:
  results (all three members fail preregistered gates)"
- Adjacent commits: `5dc74e8` (season_split-skip + spec-hash binding),
  `1977927` (weekend queue note recording zero survivors)
- `run_at`: 2026-09-04T22:27:19.797301+00:00
- `frozen_at`: 2026-09-04T22:26:46.825662+00:00
- Universe identity hash: `c67508603b14af2c494e13fadeb2a2f039f52df996ab6e12ff6164585e33cd1c`
- Price-payload hash: `f2ff7b748b1b76f1702cfe2b29750f684e554ffe2c773887a04f132bf2275ec7`
- Spec hash: `f637dd176266fa066d9a0cb8429a5c67f2bb6d31568e2b84df4d22e518ebca8b`
- Battery rules version: `2.0.0`, fingerprint `ac74c7a7f715f9ec`
- `hashes.verified: true` in the results file (both hashes re-checked at
  run time before any statistic was computed)
