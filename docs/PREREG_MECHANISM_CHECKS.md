# Pre-registered mechanism checks

**Written 2026-09-04, BEFORE any predicate below was evaluated against a
single settled bet.** That ordering is the whole value of this document. A
predicate authored, widened, or re-thresholded after its results are known
is worth nothing, and `docs/RESEARCH_CATALOGUE.md` T8 ("no rescue by
threshold change") applies here with full force: if a predicate below
produces a distribution somebody dislikes, the answer is to report the
distribution, not to move the line.

## Why this document exists

`src/engine/explain.py` made a published pick argue for itself:

> this lineup's measured production against the primary pitch of the starter
> it faces: away 0.272 wOBA, home 0.331 wOBA, a gap of 0.058 clearing the
> threshold of 0.053 ... Pre-registered reason it should matter: a starter
> who leans on one pitch, against a lineup that has measurably hit that
> pitch, has nowhere to hide for eighteen outs.

That sentence is falsifiable. The sixth inning can refute it. But nothing in
the system checked: `src/engine/settle_slate.py`'s `build_review_for` wrote
`mechanism_checks=()` for every bet we ever settled, so
`src/review/postmortem.py` returned `VARIANCE` /
`no_falsifiable_mechanism` for every joinable settled decision in our
history. Not one loss COULD have been classified `REASONING_WRONG` by any
game ever played. The classifier separated nothing, and the report said so.

This document is the fix's honest half: the claims, written down first.

## The rules of the layer

1. **Frozen at decision time.** Predicates are emitted in PROPOSE by
   `src.engine.mechanism_predicates.predicates_for` and ride on
   `DecisionRecord.mechanism_predicates`, inside the hash chain, alongside
   the pick. Settlement evaluates what it finds and may never invent a
   predicate for a record that carries none.
2. **UNDETERMINED is a real answer.** A starter pulled in the third leaves
   fewer plate appearances than any honest rate can be read off; a game with
   no play-by-play stored leaves none at all. Neither is coerced to PASS or
   FAIL, and `src/review/postmortem.py` carries a distinct verdict
   qualifier (`mechanism_undetermined`) so it cannot hide inside
   "the mechanism held".
3. **Scored on the mechanism, never on the bet.** No function in
   `src.review.mechanism_eval` takes the settled outcome as an argument at
   any depth. A winning pick and a losing pick on identical reasoning and an
   identical game receive identical checks and an identical verdict —
   pinned by `tests/test_review_postmortem.py`.
4. **Description, never feedback.** Nothing here returns a parameter. These
   checks do not enter fitness, promotion, staking, strategy selection or
   threshold derivation. They say whether the thing the pick claimed would
   happen did happen, and stop.
5. **Post-game data stays post-game.** The predicates live on the decision
   path and import the registry and nothing else; the measurement functions
   live on the settlement side and read `src/pipeline/gameflow.py`.
   `tests/test_gameflow_pit.py` holds the boundary by import graph.

## The measurement vocabulary

Defined once, here, in prose; implemented in
`src/review/mechanism_eval.py`; read off MLB's own play-by-play rows.

**Plate appearance.** A play whose `event_type` is one of: `single`,
`double`, `triple`, `home_run`, `walk`, `intent_walk`, `hit_by_pitch`,
`strikeout`, `strikeout_double_play`, `field_out`, `force_out`,
`grounded_into_double_play`, `double_play`, `triple_play`, `sac_fly`,
`sac_fly_double_play`, `sac_bunt`, `sac_bunt_double_play`,
`fielders_choice`, `fielders_choice_out`, `field_error`, `other_out`,
`batter_interference`, `catcher_interf`. Anything else in the store (a
pickoff, a caught stealing) is a baserunning row, not a plate appearance,
and is ignored by every measure — counting it as an out would flatter every
pitcher.

**reached_base_rate.** Of those plate appearances, the share ending in
`single`, `double`, `triple`, `home_run`, `walk`, `intent_walk` or
`hit_by_pitch`. Reaching on an error is **not** reaching base: the defence
gave the base away, the lineup did not take it. Matches on-base convention.

**ground_ball_out_share.** Of a pitcher's *unambiguous* batted-ball outs,
the share on the ground. Ground: `Groundout`, `Bunt Groundout`,
`Grounded Into DP`. Air: `Flyout`, `Lineout`, `Pop Out`, `Sac Fly`,
`Bunt Pop Out`, `Flyout Double Play`, `Lineout Double Play`. Forceouts and
fielder's choices appear in **neither** set: the record does not say what
was hit, and assigning them would be inventing the exact quantity being
measured.

**top_minus_bottom_reached_base_rate.** The batting order is read off the
game itself — the first nine batters to come to the plate, in order. If
those nine plate appearances are not nine distinct batters, the order is
unreadable and the measure is `None` (never a partial order). Slots 1–4 are
the top, 5–9 the bottom; the measure is the top's `reached_base_rate` minus
the bottom's, over their plate appearances against the same starter. The
reported sample is the **smaller** of the two halves: a difference is only
as well-measured as its thinner side.

**Subject roles.** A predicate names a role, never a person. "The starter
the backed lineup faced" resolves, post-game, to whoever threw the first
pitch of that half-inning — the game's own record of who took the ball, and
the only honest answer after a late scratch. (A late scratch is already
pre-empted upstream: `src/review/postmortem.py`'s R1 returns
`INFORMATION_MISSING` before any mechanism check is consulted.)

## The two league baselines

Derived, not chosen, and derived on games this project has never bet.
`scripts/derive_mechanism_baselines.py` walks the play-by-play store over a
**held-out window carrying no wager of ours** — this project's settled
wagers fall on 2023-04-18, 2026-08-31, 2026-09-02 and 2026-09-03, none of
them inside it.

| | value | window | sample |
| --- | --- | --- | --- |
| `LEAGUE_REACHED_BASE_RATE_VS_STARTERS` | **0.3245** | 2026-08-15..2026-08-27, 172 games | 2,420 of 7,458 plate appearances against starters |
| `LEAGUE_GROUND_BALL_OUT_SHARE` | **0.4280** | same 172 games | 1,384 of 3,234 unambiguous batted-ball outs by starters |

Same posture as `src/evolab/registry.py`'s threshold ladder: a marginal
distribution, with no outcome of ours, no price and no bet anywhere in it.
Frozen as literals in `src/engine/mechanism_predicates.py` rather than
recomputed at settlement time, because a threshold that moves as the store
grows is a threshold that quietly re-scores every pick already settled under
the old one.

**A baseline derived near the median is expected to produce a roughly even
PASS/FAIL split, by construction.** That is a property of the baseline, not
a finding about the mechanisms, and no reading of the resulting distribution
may treat it as one.

## Sample floors

| floor | value | why |
| --- | --- | --- |
| `MIN_PLATE_APPEARANCES` | 9 | One full turn through the order. Below it a single swing moves the measured rate by more than the entire gap the mechanism claims. |
| `MIN_PLATE_APPEARANCES_PER_ORDER_HALF` | 6 | Applied to each half of the order separately. Four slots and five slots against one starter cannot each reach nine in a normal start, and a floor no start can clear would make the predicate unfalsifiable by construction — the opposite of the point. |
| `MIN_BATTED_BALL_OUTS` | 6 | Same reasoning, for the ground-ball share. |

Below the floor, the verdict is `UNDETERMINED`. Always.

## The predicates

One per **registered** feature (`src/evolab/registry.py`'s six).
`starter_platoon_gap` has none: the registry refuses it a standalone
direction, so no genome can fire it and no honest predicate exists for it.

### 1. `lineup_vs_primary_pitch` (direction +1, FIRST_FIVE)

> a starter who leans on one pitch, against a lineup that has measurably hit
> that pitch, has nowhere to hide for eighteen outs

**Subject:** the backed lineup, against the opposing starter.
**Measure:** `reached_base_rate`.
**PASS** when ≥ 0.3245. **FAIL** when < 0.3245. **UNDETERMINED** when fewer
than 9 plate appearances against that starter, or no play-by-play stored.

### 2. `primary_pitch_share` (direction +1, FIRST_FIVE)

> concentration in one pitch is predictability: the more of a starter's
> arsenal is a single offering, the more of the lineup's preparation
> transfers

**Subject / measure / rule:** identical to (1) — predictability, if it is
real, shows up as production against the man throwing the predictable
pitch. Two mechanisms sharing one observable consequence is not a
duplication to be hidden: they claim the same thing happens, for different
reasons, and the game answers both at once.

### 3. `lineup_platoon_share` (direction +1, FIRST_FIVE)

> a lineup posted one-handed against a starter it holds the platoon
> advantage over gets more of its plate appearances in the favourable split

**Subject / measure / rule:** identical to (1). The favourable split, if it
is worth what the mechanism says, appears as the advantaged lineup reaching
base against that starter at or above the rate starters allow league-wide.

### 4. `top_minus_bottom` (direction +1, FIRST_FIVE)

> a top-heavy order concentrates its best bats where the extra plate
> appearances go

**Subject:** the backed lineup, split 1–4 against 5–9, both against the
opposing starter.
**Measure:** `top_minus_bottom_reached_base_rate`.
**PASS** when > 0. **FAIL** when < 0. **UNDETERMINED** when exactly 0 (at a
dead tie neither half out-produced the other), when either half took fewer
than 6 plate appearances against that starter, or when the order cannot be
read off the game.

### 5. `starter_velocity_gap` (direction −1, FIRST_FIVE)

> a starter whose fastball sits above league pace is holding stuff the
> season line has not caught up to, so the lineup facing the harder thrower
> is the disadvantaged side

The fired side is backed **because its opponent has to face the harder
thrower** — that harder thrower is the backed side's own starter.
**Subject:** the backed side's own starter, against the opposing lineup.
**Measure:** `reached_base_rate` allowed.
**PASS** when < 0.3245 (he suppressed them). **FAIL** when ≥ 0.3245.
**UNDETERMINED** below 9 plate appearances, or with no play-by-play.

### 6. `starter_groundball_share` (direction −1, FIRST_FIVE)

> a career ground-ball starter takes the air out of an offence that lives on
> balls in the air

Same reading of the sign: the backed side's own starter is the ground-ball
one.
**Subject:** the backed side's own starter's batted balls.
**Measure:** `ground_ball_out_share`.
**PASS** when ≥ 0.4280. **FAIL** when < 0.4280. **UNDETERMINED** below 6
unambiguous batted-ball outs, or with no play-by-play.

## What a check does to the verdict

`src/ledger/records.py`'s `compute_thesis_outcome` is unchanged and still
computes `thesis_outcome` from the checks, never from an opinion:

- no checks → `UNTESTED`
- any check `refuted` → `REFUTED`
- not all checks `confirmed` (i.e. some `undetermined`) → `UNTESTED`
- all `confirmed` + win → `CONFIRMED`; + loss/push → `VARIANCE`

`src/review/postmortem.py` then classifies, in its existing fixed order:
`INFORMATION_MISSING` first (if the board we decided on was wrong we are not
entitled to any other claim), then `REASONING_WRONG` on a refuted check or a
realized counterargument, then `VARIANCE` with one of three qualifiers —
`mechanism_confirmed`, `mechanism_undetermined`, or
`no_falsifiable_mechanism`.

## What this does not fix

Every DecisionRecord already published carries no predicates and never can:
the ledger is a hash chain and its rows are frozen. Re-running the
post-mortem over our existing settled history therefore still returns
`no_falsifiable_mechanism` for those rows, and it should — they genuinely
made no checkable claim. The separation this document buys begins with the
first slate decided after it, and any demonstration over past games must say
plainly that it is a replay, not a pre-commitment.
