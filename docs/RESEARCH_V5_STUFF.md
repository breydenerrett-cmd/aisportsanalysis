# Research Family V5 — stuff decline and contact shape (pre-registration)

Written before any outcome is read; `funnel.register_family` freezes these
specs byte-for-byte and the run refuses anything that differs. Battery
RULES_VERSION 2.0.0, frozen at the validation gate.

## The premise, and why this is not V4 again

V4's interactions combined features the market almost certainly already
prices (platoon composition, pitch-mix familiarity). V5 tests NEW
INFORMATION the store only just gained: the opposing starter's measured
fastball velocity against the league as-of the same cutoff (a leading
indicator of decline that season-long results lag), and his career
ground-ball share (the contact shape that decides what a power-
concentrated lineup can do). Both features passed byte-level point-in-time
injection tests before this document existed, and their coverage was
measured before any threshold was chosen: velocity 55%/75% both-sides by
season, ground-ball share 60%/85%.

The family is three hypotheses. Small on purpose: two new features support
three defensible mechanisms, and padding the denominator with weak
variants helps nobody.

## The frozen family (denominator 3)

Common: market h2h, side_rule back_advantaged, min_sample 200,
effect_floor 0.01, 2023 screen / 2024 replication / BH-FDR q=0.10 over all
three / battery on survivors / every loser published. Thresholds are the
pooled 2023+2024 p70 of |signal| — the same fire-on-the-top-30% rule V4
froze, chosen from feature distributions only.

| # | name | feature | direction | threshold | mechanism |
|---|------|---------|-----------|-----------|-----------|
| 1 | facing_soft_stuff | starter_velocity_gap | negative | 3.0167 | a starter whose fastball sits below league pace is measurably losing stuff before his results show it; the market prices the season line, velocity leads it — back the side FACING the softer stuff |
| 2 | stacked_top_vs_groundballer | top_minus_bottom*starter_groundball_share | negative | 0.0137 | a quality-concentrated lineup lives on balls in the air; a career ground-ball starter takes exactly that away, and club-level pricing averages the collision out — back the side whose stars do NOT meet the groundballer |
| 3 | fastball_leaning_decliner | primary_pitch_share*starter_velocity_gap | negative | 1.2380 | a starter who leans hardest on one pitch while his velocity sits below league is exploitable through that one pitch; the lean and the decline compound — back the side facing him |

Direction note, spelled out once: each side's value describes what that
side FACES tonight (the matrix cross-joins), so a large positive value is
bad news for that side and every spec backs the OTHER side — direction
"negative" throughout, fixed by mechanism, no both-ways variants.

## What was rejected at ranking

Velocity × platoon, ground-ball × handedness, and every other pairing of
the new features with V4's: no stated mechanism survived being written
down, and V4 just showed what mechanism-free products earn. Hitter-side
velocity-band and contact/power profiles: not in the matrix yet — V6
candidates, not smuggled in. Both-direction variants: denominator
inflation.

## Results

One batch, 2026-08-31 07:54 UTC, against the frozen family. Full rows in
`data/research/results_v5_run.json`.

**Three hypotheses. Zero survivors — all three died at 2024 replication.**

| name | 2023 screen | 2024 replication | verdict |
|------|-------------|------------------|---------|
| facing_soft_stuff | +0.27pp (n=374) | +0.46pp, wrong side of the half-floor | no_replication |
| stacked_top_vs_groundballer | +1.96pp (n=481) | −3.39pp — a sign flip | no_replication |
| fastball_leaning_decliner | +1.60pp (n=371) | −0.33pp — a sign flip | no_replication |

No spec reached the battery or the correction; nothing advances.

### Reading

The most instructive death is stacked_top_vs_groundballer: +1.96pp on 481
screen selections looks like exactly the story this family was built to
find, and the held-out season flipped its sign outright — the same
screen-then-flip shape as V4's survivors-that-weren't. Velocity decline,
the strongest a-priori mechanism of the three, showed nothing in either
season worth the name. Fourth family, twenty-seven pre-registered
hypotheses total, zero survivors: new features alone are not new EDGE, and
the h2h close keeps absorbing whatever the pitch store measures. The
forward-looking information lanes (V3 timing, softer markets) remain the
live research directions; another season-level feature family needs a
mechanism the market plausibly CANNOT price, not merely one it might not.
