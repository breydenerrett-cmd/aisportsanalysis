"""What each pre-registered mechanism PROMISES the game will show.

WHY THIS EXISTS
----------------
`src.engine.explain` made a pick readable: "this lineup's measured
production against the primary pitch of the starter it faces: away 0.272
wOBA, home 0.331 wOBA ... a starter who leans on one pitch, against a
lineup that has measurably hit that pitch, has nowhere to hide for eighteen
outs." That sentence is falsifiable -- the sixth inning can refute it -- but
until this module nothing in the system ever checked. Every ReviewRecord
this project has written carries `mechanism_checks=()`, so
`src.review.postmortem`'s classifier returned VARIANCE /
`no_falsifiable_mechanism` for every joinable settled decision in our
history: not one loss COULD have been classed REASONING_WRONG by any game
ever played.

This module closes that by attaching, to every fired signal, a
machine-checkable POST-GAME PREDICATE: a named subject, a named measure, a
comparison, a threshold, and a minimum sample below which the honest answer
is UNDETERMINED. The predicates are written out in full in
docs/PREREG_MECHANISM_CHECKS.md, which was written BEFORE any of them was
evaluated against a single settled bet.

FROZEN AT DECISION TIME, NEVER AFTER
--------------------------------------
`predicates_for` runs in PROPOSE, from decision-time data only, and its
output rides on `DecisionRecord.mechanism_predicates` -- frozen into the
hash chain with the pick itself. A predicate authored, widened, or
re-thresholded after the outcome is known is worth exactly nothing, and the
only structural defence against that is for the predicate to be older than
the result. Settlement (`src.review.mechanism_eval`) may EVALUATE what it
finds on the record; it may never invent a predicate for a record that
carries none.

THIS MODULE IS ON THE DECISION PATH, SO IT TOUCHES NO POST-GAME DATA
----------------------------------------------------------------------
It imports the registry and nothing else: no gameflow, no boxscore, no
result. tests/test_gameflow_pit.py lists this file on its decision-path
import graph for exactly that reason. The measurement functions that DO
read play-by-play live on the settlement side, in
`src.review.mechanism_eval`, and are never imported from here.

WHY THE SUBJECT IS A ROLE AND NOT A PERSON
--------------------------------------------
A predicate names "the starter the backed lineup faced", not a pitcher id.
Two reasons, both structural. The price-blind snapshot a PROPOSE-phase
system sees carries feature floats and nothing else -- no probable id is on
it, and widening it to carry one would expand what the decision path may
read for no gain. And the late-scratch case is already the post-mortem's
own R1 (INFORMATION_MISSING pre-empts REASONING_WRONG,
`src.review.postmortem._verdict_for`): if the probable we assumed never
took the ball, the verdict never reaches the mechanism check at all. The
role resolves, post-game, to whoever actually threw the first pitch of that
half-inning -- the game's own record of who took the ball.

NOT A FEEDBACK LOOP
--------------------
Nothing here or downstream of it returns a parameter. A mechanism check is
DESCRIPTION: it says whether the thing the pick claimed would happen did
happen. It does not enter fitness, promotion, staking or threshold
selection, and docs/RESEARCH_CATALOGUE.md T8 ("no rescue by threshold
change") governs any temptation to revise a predicate because its results
disappointed.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.evolab.registry import DEFAULT_REGISTRY

# Bumped only when a predicate's MEANING changes. A frozen record carries the
# version its predicates were written under, so a later revision can never be
# read back onto an older pick as though it had been promised there.
PREDICATE_VERSION = "mechanism-predicate-v1"

# --- Subjects: whose performance the claim is about ------------------------
# "backed" is the side the signal fired FOR (`decide()`'s own answer, carried
# through `explain_signal`). "opposing" is the other side. A mechanism about
# a lineup and a mechanism about a pitcher are different claims and must not
# collapse into one subject name.
SUBJECT_BACKED_LINEUP_VS_OPPOSING_STARTER = "backed_lineup_vs_opposing_starter"
SUBJECT_BACKED_STARTER_VS_OPPOSING_LINEUP = "backed_starter_vs_opposing_lineup"
SUBJECT_BACKED_STARTER_BATTED_BALLS = "backed_starter_batted_balls"

# --- Measures: what is counted; defined in prose in the prereg doc ---------
MEASURE_REACHED_BASE_RATE = "reached_base_rate"
MEASURE_GROUND_BALL_OUT_SHARE = "ground_ball_out_share"
MEASURE_TOP_MINUS_BOTTOM_REACHED_BASE_RATE = "top_minus_bottom_reached_base_rate"

# --- Comparisons -----------------------------------------------------------
# `gte`/`lt` compare the measured value to `threshold`; `gt_zero` compares a
# signed difference (top-of-order minus bottom-of-order) to zero, which is
# why it carries no threshold at all -- the mechanism's own claim is that one
# half of the order out-produces the other, not that it clears any level.
COMPARE_GTE = "gte"
COMPARE_LT = "lt"
COMPARE_GT_ZERO = "gt_zero"

# --- Pre-registered constants ----------------------------------------------
#
# THE TWO BASELINES ARE DERIVED, NOT CHOSEN, and derived on games this
# project has never bet: `scripts/derive_mechanism_baselines.py` walks the
# play-by-play store over a HELD-OUT date window carrying no wager of ours
# and reports the two league-wide rates below. Same posture as
# `src.evolab.registry`'s threshold ladder: a marginal distribution, with no
# outcome of ours, no price and no bet anywhere in it. The window, the game
# count and the sample sizes are recorded in
# docs/PREREG_MECHANISM_CHECKS.md and reproducible by re-running that script.
#
# They are frozen here as literals rather than recomputed at settlement time
# on purpose: a threshold that moves as the store grows is a threshold that
# quietly re-scores every pick already settled under the old one.

BASELINE_PROVENANCE = (
    "league-wide over data/processed/gameflow_2026.jsonl for "
    "2026-08-15..2026-08-27, a held-out window carrying no wager of this "
    "project's; see docs/PREREG_MECHANISM_CHECKS.md and "
    "scripts/derive_mechanism_baselines.py"
)

# Share of plate appearances against a STARTING pitcher that end with the
# batter reaching base (hit, walk, intentional walk, hit by pitch; reaching
# on an error is not reaching, matching on-base convention).
# 2,420 of 7,458 plate appearances against starters over 172 held-out games.
LEAGUE_REACHED_BASE_RATE_VS_STARTERS = 0.3245

# Share of a starter's UNAMBIGUOUS batted-ball outs that were on the ground.
# Forceouts and fielder's choices are excluded from both halves of the ratio:
# the play record does not say which of them were ground balls, and guessing
# would be inventing the very quantity being measured.
# 1,384 of 3,234 unambiguous batted-ball outs by starters, same 172 games.
LEAGUE_GROUND_BALL_OUT_SHARE = 0.4280

# Minimum plate appearances before a rate is allowed to decide anything. Nine
# is one full turn through the order: below that a single swing moves the
# measured rate by more than the entire gap the mechanism claims, so the
# honest verdict is UNDETERMINED, not a coin flip dressed as evidence.
MIN_PLATE_APPEARANCES = 9

# The same floor applied to EACH HALF of the batting order separately, for
# the one predicate that splits it. Six, not nine: four slots and five slots
# against one starter cannot each reach nine in a normal start, and a floor
# no start can clear would make the predicate unfalsifiable by construction
# -- the opposite of the point.
MIN_PLATE_APPEARANCES_PER_ORDER_HALF = 6

# Minimum unambiguous batted-ball outs before a ground-ball share may decide.
MIN_BATTED_BALL_OUTS = 6


class PredicateError(ValueError):
    """A predicate could not be built honestly."""


@dataclass(frozen=True, slots=True)
class MechanismPredicate:
    """One mechanism's post-game promise, in machine-checkable form.

    `claim` is the English sentence the PASS/FAIL rule is the arithmetic of;
    it is carried onto the frozen record and rendered in the post-mortem, so
    a reader sees the promise and the verdict side by side.
    """

    feature: str
    subject: str
    measure: str
    comparison: str
    threshold: float | None
    min_sample: int
    claim: str

    def expected_phrase(self) -> str:
        """The PASS condition as one line -- what goes in a check's
        `expected` field, so a stored check reads without this module."""
        if self.comparison == COMPARE_GT_ZERO:
            return (f"{self.measure} > 0, over at least {self.min_sample} "
                    "plate appearances per order half")
        sign = ">=" if self.comparison == COMPARE_GTE else "<"
        return (f"{self.measure} {sign} {self.threshold}, over at least "
                f"{self.min_sample} observations")


# One predicate per REGISTERED feature (`src.evolab.registry`'s six).
# `starter_platoon_gap` is deliberately absent: the registry refuses to give
# it a standalone direction, so no genome can fire it and no predicate can
# honestly be written for it.
PREDICATES: dict[str, MechanismPredicate] = {
    p.feature: p for p in (
        MechanismPredicate(
            feature="lineup_platoon_share",
            subject=SUBJECT_BACKED_LINEUP_VS_OPPOSING_STARTER,
            measure=MEASURE_REACHED_BASE_RATE,
            comparison=COMPARE_GTE,
            threshold=LEAGUE_REACHED_BASE_RATE_VS_STARTERS,
            min_sample=MIN_PLATE_APPEARANCES,
            claim=("the platoon-advantaged lineup reaches base against the "
                   "starter it was posted against at or above the league "
                   "rate starters allow")),
        MechanismPredicate(
            feature="lineup_vs_primary_pitch",
            subject=SUBJECT_BACKED_LINEUP_VS_OPPOSING_STARTER,
            measure=MEASURE_REACHED_BASE_RATE,
            comparison=COMPARE_GTE,
            threshold=LEAGUE_REACHED_BASE_RATE_VS_STARTERS,
            min_sample=MIN_PLATE_APPEARANCES,
            claim=("the lineup that has measurably hit this starter's primary "
                   "pitch reaches base against him at or above the league "
                   "rate starters allow -- 'nowhere to hide for eighteen "
                   "outs', measured over the outs he actually got")),
        MechanismPredicate(
            feature="primary_pitch_share",
            subject=SUBJECT_BACKED_LINEUP_VS_OPPOSING_STARTER,
            measure=MEASURE_REACHED_BASE_RATE,
            comparison=COMPARE_GTE,
            threshold=LEAGUE_REACHED_BASE_RATE_VS_STARTERS,
            min_sample=MIN_PLATE_APPEARANCES,
            claim=("the lineup facing the one-pitch-heavy starter reaches "
                   "base against him at or above the league rate starters "
                   "allow -- predictability showing up as production")),
        MechanismPredicate(
            feature="top_minus_bottom",
            subject=SUBJECT_BACKED_LINEUP_VS_OPPOSING_STARTER,
            measure=MEASURE_TOP_MINUS_BOTTOM_REACHED_BASE_RATE,
            comparison=COMPARE_GT_ZERO,
            threshold=None,
            min_sample=MIN_PLATE_APPEARANCES_PER_ORDER_HALF,
            claim=("the top-heavy order's first four slots out-reach its own "
                   "bottom five against the starter they faced -- the "
                   "concentration the mechanism claims, in the innings it "
                   "claims it for")),
        MechanismPredicate(
            feature="starter_velocity_gap",
            subject=SUBJECT_BACKED_STARTER_VS_OPPOSING_LINEUP,
            measure=MEASURE_REACHED_BASE_RATE,
            comparison=COMPARE_LT,
            threshold=LEAGUE_REACHED_BASE_RATE_VS_STARTERS,
            min_sample=MIN_PLATE_APPEARANCES,
            claim=("the harder-throwing starter -- the one this side is "
                   "backed BECAUSE its opponent has to face him -- holds "
                   "that opposing lineup below the league rate starters "
                   "allow")),
        MechanismPredicate(
            feature="starter_groundball_share",
            subject=SUBJECT_BACKED_STARTER_BATTED_BALLS,
            measure=MEASURE_GROUND_BALL_OUT_SHARE,
            comparison=COMPARE_GTE,
            threshold=LEAGUE_GROUND_BALL_OUT_SHARE,
            min_sample=MIN_BATTED_BALL_OUTS,
            claim=("the ground-ball starter this side is backed behind "
                   "actually pitched to the ground, at or above the league "
                   "share of unambiguous batted-ball outs")),
    )
}


def predicate_id(feature: str, threshold_index: int) -> str:
    """A stable name for one fired signal's predicate.

    Carries the rung as well as the feature: the same mechanism fired at the
    90th percentile and at the median is the same claim, but a reader
    comparing two checks needs to see which dose was actually taken.
    """
    return f"{feature}@rung{threshold_index}"


def predicates_for(signals_fired, side: str, features: dict, *,
                    registry=DEFAULT_REGISTRY, samples: dict | None = None
                    ) -> tuple:
    """The frozen predicate rows for one decision -- JSON-safe, ordered.

    One row per fired signal, in the order the genome fired them, each
    carrying everything settlement needs to evaluate it WITHOUT re-consulting
    this module's tables: subject, measure, comparison, threshold and sample
    floor are all copied onto the row. That is deliberate duplication. A
    record whose meaning depends on the current contents of a Python dict is
    a record whose meaning changes when someone edits that dict; a record
    that carries its own rule cannot be re-scored by a later edit.

    The decision-time feature values are frozen alongside (`away_value` /
    `home_value`, verbatim, `None` when absent -- never defaulted), so a
    post-mortem can print the claim the pick actually made next to what the
    game did.

    A feature with no registered predicate yields NO row rather than a
    placeholder: silence is the honest report of "this mechanism has no
    machine-checkable consequence written for it yet", and a placeholder row
    would be a check that could never fail.
    """
    if side not in ("away", "home"):
        raise PredicateError(
            f"side={side!r} must be 'away' or 'home' -- a predicate whose "
            "subject is undefined cannot be checked")
    rows = []
    for feature, threshold_index in tuple(signals_fired or ()):
        predicate = PREDICATES.get(feature)
        if predicate is None:
            continue
        try:
            signal_threshold = registry.get(feature).threshold(threshold_index)
        except Exception:  # noqa: BLE001
            # An unregistered feature or an out-of-range rung is a decision
            # that should never have been produced. Record the predicate
            # without the rung value rather than crash a slate over it.
            signal_threshold = None
        rows.append({
            "predicate_id": predicate_id(feature, threshold_index),
            "version": PREDICATE_VERSION,
            "feature": feature,
            "threshold_index": int(threshold_index),
            "signal_threshold": signal_threshold,
            "side": side,
            "subject": predicate.subject,
            "measure": predicate.measure,
            "comparison": predicate.comparison,
            "threshold": predicate.threshold,
            "min_sample": predicate.min_sample,
            "claim": predicate.claim,
            "expected": predicate.expected_phrase(),
            "away_value": features.get("away_" + feature),
            "home_value": features.get("home_" + feature),
            # How much each of those two values rested on at decision time
            # (`src.engine.features.FeatureValue.sample`). Frozen here so a
            # post-mortem can say the claim was made on 214 plate appearances
            # or on 11 -- absent, never zero, when the primitive had no count.
            "away_sample": (samples or {}).get("away_" + feature),
            "home_sample": (samples or {}).get("home_" + feature),
        })
    return tuple(rows)
