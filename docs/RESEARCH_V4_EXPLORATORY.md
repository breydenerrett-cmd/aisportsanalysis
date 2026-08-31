# Research Family V4 — exploratory interactions (pre-registration)

Written BEFORE any outcome is read. This document is the frozen hypothesis
family; `funnel.register_family` freezes the same specs byte-for-byte and
`funnel.run` refuses anything that differs. Registration happened only after
the machinery validation gate (docs/VALIDATION_GATE.md) was adjudicated open,
under battery RULES_VERSION 2.0.0.

## The premise

V1 tested isolated single-feature ideas: thirteen hypotheses, zero
survivors. V2 tested market-structure ideas: five more, zero survivors. V4
tests the one construction neither round could express: a UNIT meeting a
SPECIFIC WEAKNESS — this lineup times what it faces tonight — which is what
the matchup matrix and the spec compiler were built for. The matrix already
cross-joins every per-side feature (away_* features describe the away lineup
against the HOME starter), so an interaction is a per-side product and the
funnel's `a*b` feature syntax expresses it directly.

The family is deliberately compact. The compiler making hypotheses cheap to
run is not permission to inflate the family: six interactions with real
mechanisms beat twenty mediocre ones, and the FDR denominator is the full
six regardless of how any one dies.

## How candidates were ranked (before results)

Ranked using ONLY feature-side data: both-sides coverage in each season,
signal-distribution spread, expected graded n (coverage × fire rate ×
games × the measured 76% price-join rate), mechanism quality, direction
definable a priori, and novelty against the refuted V1/V2 singles. No
outcome column was read. Thresholds are the pooled 2023+2024 70th
percentile of |signal| — a fire-on-the-top-30% rule chosen from the signal
distribution alone, one rule for every spec so no threshold can be tuned to
a result.

Candidates REJECTED at ranking, and why:

- Anything built on `lineup_vs_starter_history` (batter-vs-pitcher wOBA):
  both-sides coverage 14%/51%, median history 9 PA — structurally
  underpowered, and 18-at-bat storylines are the exact noise the Analyzer
  warns readers about.
- Starter velocity profile × hitter velocity-band performance, batted-ball
  profile × lineup contact/power × park, expected starter innings × bullpen
  quality/rest, bullpen handedness × late-inning hitters, top-of-order
  concentration × F5 market (F5 odds coverage is 9.3%), lineup-scratch
  severity × market movement: each needs a feature or market the matrix
  does not yet carry point-in-time. They are the V5 shortlist, gated on the
  same PIT validation the current features passed — not smuggled in here.
- Both-direction variants of each interaction: the mechanism fixes the
  direction; registering "or the opposite" doubles the family with
  hypotheses nobody believes.

## The frozen family (six specs)

Common to all: market h2h, side_rule back_advantaged, direction positive
(the advantaged side beats its implied), min_sample 200, effect_floor 0.01
(one probability point, the vig line), 2023 = screen, 2024 = replication,
FDR (Benjamini–Hochberg, q = 0.10) across all six, falsification battery
RULES_VERSION 2.0.0 on survivors, every loser published.

| # | name | feature | threshold | mechanism |
|---|------|---------|-----------|-----------|
| 1 | pitch_lean_vulnerability | primary_pitch_share*lineup_vs_primary_pitch | 0.0600 | a starter who leans on one pitch, against a lineup that hits that pitch, has nowhere to hide for eighteen outs; the market prices his season line, not tonight's specific collision |
| 2 | stacked_top_platoon | top_minus_bottom*lineup_platoon_share | 0.0234 | a top-heavy order with the platoon advantage concentrates its best bats where the extra plate appearances go; club-level pricing averages that concentration away |
| 3 | platoon_pressure | lineup_platoon_share*starter_platoon_gap | 0.0478 | the classic exploitation: a one-handed lineup built against a starter with a genuine platoon split; V1 tested each half alone and found nothing — the claim here is the product, not either part |
| 4 | stacked_top_vs_pitch | top_minus_bottom*lineup_vs_primary_pitch | 0.0117 | the concentrated top of the order specifically hits the opposing starter's primary pitch |
| 5 | handed_lineup_vs_pitch | lineup_platoon_share*lineup_vs_primary_pitch | 0.1134 | a lineup one-handed on purpose AND good against the starter's main offering — two independent reads of "built for this starter" agreeing |
| 6 | stacked_top_weak_starter | top_minus_bottom*starter_platoon_gap | 0.0028 | the best bats, concentrated, against a starter with a real measured weakness |

Ranking order above IS the priority order: 1–2 carry the best joint
coverage in both seasons (75–100%) and pooled expected n of roughly
900–1,100 graded selections; 3 and 6 carry the cleanest mechanisms but
starter_platoon_gap answers on only 34% of 2023 games (70% of 2024), so
their screens are the thinnest — expected pooled n ≈ 570.

## What counts as what (frozen)

- **Screen pass (2023):** at least half of min_sample selections and an
  effect in the positive direction.
- **Replication pass (2024):** effect at least half the effect floor in the
  same direction; a sign flip is death.
- **Family correction:** BH at q = 0.10 with denominator 6 — early deaths
  fill in at p = 1.0; the denominator never shrinks.
- **Falsification battery:** RULES_VERSION 2.0.0, frozen before this
  registration; season split, team/book concentration (both legs), extreme
  date removal, dose response with the spec threshold as a band edge and
  the half-threshold graded sample arming the below-band.
- **Survivor:** clears all of the above — and is then still only a
  HISTORICAL CANDIDATE, eligible for the forward ledger, never labelled
  proven by this family. Zero survivors is a valid and expected result.
- 2025 is tuning-only, forever. The sealed 2026 set is not touched.

## Results

_(appended after the one batch run; losers included)_
