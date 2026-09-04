"""Measuring, from the game's own record, whether a frozen mechanism held.

WHERE THIS SITS
----------------
SETTLEMENT SIDE, always. Every function here reads play-by-play
(`src.pipeline.gameflow`), which describes things that happened DURING the
game and therefore cannot be admitted anywhere near a decision.
tests/test_gameflow_pit.py holds the line: the decision-path import graph
must never reach this module or the store it reads. The predicates
themselves -- the claims being checked -- live on the other side of that
line, in `src.engine.mechanism_predicates`, and are frozen onto
`DecisionRecord.mechanism_predicates` before the first pitch.

WHAT IT MAY AND MAY NOT DO
----------------------------
May: read the frozen predicate rows off a decision, measure the named
quantity over the named subject, and return a PASS/FAIL/UNDETERMINED
verdict by the rule the row itself carries.

May NOT: invent a predicate for a decision that carries none (silence is
the honest report that the pick made no checkable claim); consult the bet's
outcome; or resolve an under-sampled measurement by picking a side.
UNDETERMINED is a first-class answer here and is expected to be common --
a starter pulled in the third leaves fewer plate appearances than any
honest rate can be read off.

THE ONE RULE THAT MATTERS MOST
--------------------------------
A check is scored on THE MECHANISM, never on whether the bet won. Nothing
in this module takes the settled outcome as an argument, at any depth. The
strongest evidence the post-mortem lane produced was a winning pick and a
losing pick receiving identical verdicts on identical reasoning, and
tests/test_review_postmortem.py pins that property through this code.

SUBJECT RESOLUTION
-------------------
A predicate names a ROLE ("the starter the backed lineup faced"), and this
module resolves it against the game's own record: the pitcher who threw the
first pitch of the half-inning that side batted -- the same rule
`src.pipeline.gameflow._starter_id` already uses, and the only honest
answer after a late scratch. A game whose store has no play for the
relevant half resolves to None and every predicate on it is UNDETERMINED.
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

from src.engine.mechanism_predicates import (
    COMPARE_GT_ZERO,
    COMPARE_GTE,
    COMPARE_LT,
    MEASURE_GROUND_BALL_OUT_SHARE,
    MEASURE_REACHED_BASE_RATE,
    MEASURE_TOP_MINUS_BOTTOM_REACHED_BASE_RATE,
    SUBJECT_BACKED_LINEUP_VS_OPPOSING_STARTER,
    SUBJECT_BACKED_STARTER_BATTED_BALLS,
    SUBJECT_BACKED_STARTER_VS_OPPOSING_LINEUP,
)

VERDICT_CONFIRMED = "confirmed"
VERDICT_REFUTED = "refuted"
VERDICT_UNDETERMINED = "undetermined"

# --- The plate-appearance vocabulary, pre-registered -------------------------
#
# Named event_types rather than a catch-all, because a rate whose denominator
# silently absorbs an event type nobody classified is a rate nobody can
# reproduce. Anything NOT in `PA_EVENT_TYPES` (pure baserunning rows -- a
# caught stealing, a pickoff) is ignored by every measure here: it is not a
# plate appearance and counting it as an out would flatter every pitcher.

REACHED_BASE_EVENT_TYPES = frozenset({
    "single", "double", "triple", "home_run",
    "walk", "intent_walk", "hit_by_pitch",
})

# Reaching on an error is NOT reaching base, matching on-base convention: the
# defence gave the base away, the lineup did not take it.
_OUT_EVENT_TYPES = frozenset({
    "strikeout", "strikeout_double_play", "field_out", "force_out",
    "grounded_into_double_play", "double_play", "triple_play",
    "sac_fly", "sac_fly_double_play", "sac_bunt", "sac_bunt_double_play",
    "fielders_choice", "fielders_choice_out", "field_error", "other_out",
    "batter_interference", "catcher_interf",
})

PA_EVENT_TYPES = REACHED_BASE_EVENT_TYPES | _OUT_EVENT_TYPES

# --- The batted-ball vocabulary, pre-registered ------------------------------
#
# By the play's own `event` string, which is where MLB records the batted-ball
# type. Forceouts and fielder's choices appear in NEITHER set on purpose: the
# record does not say what was hit, and assigning them would be inventing the
# exact quantity the ground-ball predicate measures.
GROUND_BALL_OUT_EVENTS = frozenset({
    "Groundout", "Bunt Groundout", "Grounded Into DP",
})
AIR_OUT_EVENTS = frozenset({
    "Flyout", "Lineout", "Pop Out", "Sac Fly", "Bunt Pop Out",
    "Flyout Double Play", "Lineout Double Play",
})

# Which half-inning a side bats in. The away side bats the top; a play's
# `half` therefore names the BATTING side, and the pitcher on it belongs to
# the other one.
_BATTING_HALF = {"away": "top", "home": "bottom"}


def _other(side: str) -> str:
    return "home" if side == "away" else "away"


def _plays_batting(plays: Sequence[Mapping], side: str) -> list:
    return [p for p in plays if p.get("half") == _BATTING_HALF.get(side)]


def starter_faced_by(plays: Sequence[Mapping], side: str):
    """The pitcher who threw the first pitch of the half `side` batted.

    The game's own answer to "who took the ball", which is the only honest
    one after a late scratch -- a probable is a pre-game claim. None when the
    store holds no play for that half.
    """
    for play in _plays_batting(plays, side):
        pitcher = play.get("pitcher_id")
        if pitcher is not None:
            return pitcher
    return None


def _pa_rows(plays: Sequence[Mapping], side: str, pitcher_id) -> list:
    """Every completed plate appearance `side` took against `pitcher_id`."""
    if pitcher_id is None:
        return []
    return [p for p in _plays_batting(plays, side)
            if p.get("pitcher_id") == pitcher_id
            and p.get("event_type") in PA_EVENT_TYPES]


def reached_base_rate(plays: Sequence[Mapping], side: str, pitcher_id) -> tuple:
    """`(rate, plate_appearances)` for `side` against `pitcher_id`.

    `(None, 0)` when there is nothing to measure -- never 0.0, which would
    read as "they were retired every time".
    """
    rows = _pa_rows(plays, side, pitcher_id)
    if not rows:
        return None, 0
    reached = sum(1 for p in rows
                  if p.get("event_type") in REACHED_BASE_EVENT_TYPES)
    return reached / len(rows), len(rows)


def batting_order(plays: Sequence[Mapping], side: str) -> Optional[list]:
    """`side`'s batting order as nine batter ids, read off the game itself.

    The first nine batters to come to the plate ARE the order, in order --
    the play record carries no slot number, and this is the one reading of it
    that needs no outside store. Returns None (never a partial order) when
    the first nine plate appearances are not nine distinct batters, which is
    what a pinch-hit or an incomplete store looks like from here.
    """
    seen = []
    for play in _plays_batting(plays, side):
        if play.get("event_type") not in PA_EVENT_TYPES:
            continue
        batter = play.get("batter_id")
        if batter is None:
            return None
        seen.append(batter)
        if len(seen) == 9:
            break
    if len(seen) < 9 or len(set(seen)) != 9:
        return None
    return seen


def top_minus_bottom_reached_base(plays: Sequence[Mapping], side: str,
                                   pitcher_id) -> tuple:
    """`(top_rate - bottom_rate, min(top_pa, bottom_pa))` for `side` against
    `pitcher_id`, splitting the order 1-4 against 5-9.

    `(None, 0)` when the order cannot be read, or when either half took no
    plate appearance against him. The returned sample is the SMALLER of the
    two halves on purpose: a difference is only as well-measured as its
    thinner side, and reporting the larger one would let four plate
    appearances hide behind fourteen.
    """
    order = batting_order(plays, side)
    if order is None:
        return None, 0
    top, bottom = set(order[:4]), set(order[4:])
    rows = _pa_rows(plays, side, pitcher_id)
    top_rows = [p for p in rows if p.get("batter_id") in top]
    bottom_rows = [p for p in rows if p.get("batter_id") in bottom]
    if not top_rows or not bottom_rows:
        return None, 0
    def _rate(group):
        return sum(1 for p in group
                   if p.get("event_type") in REACHED_BASE_EVENT_TYPES) / len(group)
    return _rate(top_rows) - _rate(bottom_rows), min(len(top_rows),
                                                      len(bottom_rows))


def ground_ball_out_share(plays: Sequence[Mapping], pitcher_id) -> tuple:
    """`(share, unambiguous_batted_ball_outs)` for `pitcher_id`, over the
    whole game he pitched in. `(None, 0)` when he recorded none."""
    if pitcher_id is None:
        return None, 0
    ground = air = 0
    for play in plays:
        if play.get("pitcher_id") != pitcher_id:
            continue
        event = play.get("event")
        if event in GROUND_BALL_OUT_EVENTS:
            ground += 1
        elif event in AIR_OUT_EVENTS:
            air += 1
    total = ground + air
    if total == 0:
        return None, 0
    return ground / total, total


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def _measure(predicate: Mapping, plays: Sequence[Mapping]) -> tuple:
    """`(value, sample, subject_note)` for one frozen predicate row."""
    side = predicate.get("side")
    if side not in ("away", "home"):
        return None, 0, "the frozen predicate names no side"

    subject = predicate.get("subject")
    if subject == SUBJECT_BACKED_LINEUP_VS_OPPOSING_STARTER:
        pitcher = starter_faced_by(plays, side)
        note = f"the {_other(side)} starter (id {pitcher})"
        if predicate.get("measure") == MEASURE_TOP_MINUS_BOTTOM_REACHED_BASE_RATE:
            value, sample = top_minus_bottom_reached_base(plays, side, pitcher)
            return value, sample, note + ", by order half"
        value, sample = reached_base_rate(plays, side, pitcher)
        return value, sample, note
    if subject == SUBJECT_BACKED_STARTER_VS_OPPOSING_LINEUP:
        pitcher = starter_faced_by(plays, _other(side))
        value, sample = reached_base_rate(plays, _other(side), pitcher)
        return value, sample, f"the {side} starter (id {pitcher})"
    if subject == SUBJECT_BACKED_STARTER_BATTED_BALLS:
        pitcher = starter_faced_by(plays, _other(side))
        value, sample = ground_ball_out_share(plays, pitcher)
        return value, sample, f"the {side} starter (id {pitcher})"
    return None, 0, f"unknown subject {subject!r}"


def _verdict(predicate: Mapping, value, sample) -> str:
    """PASS/FAIL/UNDETERMINED by the rule the frozen row carries.

    The rule is read off `predicate`, not off the current contents of
    `src.engine.mechanism_predicates`: an edit to that module must not be
    able to re-score a pick that was frozen under the old rule.
    """
    if value is None:
        return VERDICT_UNDETERMINED
    try:
        min_sample = int(predicate.get("min_sample"))
    except (TypeError, ValueError):
        return VERDICT_UNDETERMINED
    if sample < min_sample:
        return VERDICT_UNDETERMINED
    comparison = predicate.get("comparison")
    if comparison == COMPARE_GT_ZERO:
        # Exactly zero is not a pass and not a fail: at a dead tie neither
        # half of the order out-produced the other, so the claim is untested.
        if value == 0:
            return VERDICT_UNDETERMINED
        return VERDICT_CONFIRMED if value > 0 else VERDICT_REFUTED
    threshold = predicate.get("threshold")
    if threshold is None:
        return VERDICT_UNDETERMINED
    if comparison == COMPARE_GTE:
        return VERDICT_CONFIRMED if value >= threshold else VERDICT_REFUTED
    if comparison == COMPARE_LT:
        return VERDICT_CONFIRMED if value < threshold else VERDICT_REFUTED
    return VERDICT_UNDETERMINED


def _format(value, measure: str) -> str:
    if value is None:
        return "unmeasurable"
    if measure == MEASURE_TOP_MINUS_BOTTOM_REACHED_BASE_RATE:
        return f"{value:+.3f}"
    if measure in (MEASURE_REACHED_BASE_RATE, MEASURE_GROUND_BALL_OUT_SHARE):
        return f"{value:.3f}"
    return f"{value:g}"


def evaluate(predicates: Sequence[Mapping], flow: Optional[Mapping]) -> tuple:
    """`mechanism_checks` for one settled decision.

    `predicates` is `DecisionRecord.mechanism_predicates` verbatim; `flow` is
    `src.pipeline.gameflow.load_game(...)` for that game, or None when the
    store holds no play-by-play for it.

    Returns one `{name, expected, observed, verdict, ...}` mapping per frozen
    predicate -- the shape `src.ledger.records.compute_thesis_outcome` reads,
    with the measurement detail carried alongside so a post-mortem can print
    the promise and the measurement together. A decision that froze NO
    predicate returns `()`: settlement never writes a check the pick did not
    promise.

    No flow at all still returns one row per predicate, every one
    UNDETERMINED. That is the honest report -- the claim exists and we could
    not check it -- and it is materially different from `()`, which says the
    claim was never made.
    """
    rows = tuple(predicates or ())
    if not rows:
        return ()
    plays = list((flow or {}).get("plays") or ())
    out = []
    for predicate in rows:
        if not isinstance(predicate, Mapping):
            continue
        if not plays:
            value, sample, note = None, 0, "no play-by-play stored"
        else:
            value, sample, note = _measure(predicate, plays)
        verdict = _verdict(predicate, value, sample)
        measure = predicate.get("measure", "")
        observed = (f"{_format(value, measure)} over {sample} observation(s) "
                    f"of {note}")
        if verdict == VERDICT_UNDETERMINED:
            observed += " -- below the frozen sample floor or unmeasurable"
        out.append({
            "name": predicate.get("predicate_id") or predicate.get("feature"),
            "expected": predicate.get("expected") or "",
            "observed": observed,
            "verdict": verdict,
            "measure": measure,
            "value": value,
            "sample": sample,
            "claim": predicate.get("claim") or "",
        })
    return tuple(out)
