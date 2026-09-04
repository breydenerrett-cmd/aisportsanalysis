"""Turning a fired signal into a sentence a person can argue with.

WHY THIS EXISTS
----------------
Until now a published evolab pick carried the thesis

    "evolab genome 606be696ff199952: (('top_minus_bottom', 1),)"

which is a machine identifier and a tuple index, not an explanation. The
owner directive (2026-09-04) is explicit: a pick has to read "I'm picking
this because xyz". The plumbing was never the problem --
`DecisionRecord.thesis` has existed since the record was frozen -- the
CONTENT was. This module is the content.

WHAT AN HONEST THESIS MAY AND MAY NOT SAY
-------------------------------------------
May: the actual feature values that fired, with their units; the threshold
they cleared and which rung of the three-rung ladder that is; the sample the
ladder was derived over; the pre-registered mechanism prose (verbatim from
`src.evolab.registry`, never re-worded here -- re-wording a hypothesis
after the fact quietly relaunders its date); which side the frozen
direction therefore points to.

May NOT: any claim of an edge, a probability advantage, expected profit, or
that the price is wrong. No proven edge exists in this project -- 24
registered hypotheses have died (docs/PREREG_CALIBRATED_PROBABILITY.md,
docs/VALIDATION_GATE.md) -- and a genome's `score` is explicitly not a
probability (`src.evolab.decide.Decision`). Every thesis this module writes
therefore ENDS by saying so plainly, and `claims_edge` below is the
machine-checkable form of the rule (tests/test_decision_explanations.py
runs it over every registered system and over the whole published ledger).

NOTHING IS INVENTED
--------------------
Every number in a sentence built here comes from an argument: the value
from `PriceBlindSnapshot.features`, the threshold and the mechanism from
the frozen registry spec, the sample size from that spec's own
`provenance` string. A feature whose value is absent is REPORTED as absent
-- "value unavailable" -- never defaulted, interpolated or rounded up from
nothing, matching `src.engine.features`'s own none-over-guess rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.evolab.registry import DEFAULT_REGISTRY, LADDER_PERCENTILES

# --- Units -----------------------------------------------------------------
# How a feature's raw float is spoken. The raw floats are shares (0..1),
# wOBA-scale rates, and miles per hour; printing all three with the same
# format would make a 0.061 wOBA gap and a 0.061 share gap read identically
# when they are not remotely the same size of claim.
SHARE = "share"
WOBA = "woba"
MPH = "mph"

_UNIT_GAP_NOUN = {
    SHARE: "percentage points",
    WOBA: "wOBA",
    MPH: "mph",
}


def format_value(value: float | None, unit: str) -> str:
    """One feature value in its own units, or the honest "unavailable"."""
    if value is None:
        return "unavailable"
    if unit == SHARE:
        return f"{value * 100:.1f}%"
    if unit == WOBA:
        return f"{value:.3f} wOBA"
    if unit == MPH:
        return f"{value:.2f} mph"
    return f"{value:g}"


def format_gap(gap: float | None, unit: str) -> str:
    """A DIFFERENCE between two values, which for a share is spoken in
    percentage POINTS, not percent -- the distinction people actually get
    wrong when reading a share gap out loud."""
    if gap is None:
        return "unavailable"
    if unit == SHARE:
        return f"{abs(gap) * 100:.1f} percentage points"
    if unit == WOBA:
        return f"{abs(gap):.3f} wOBA"
    if unit == MPH:
        return f"{abs(gap):.2f} mph"
    return f"{abs(gap):g}"


@dataclass(frozen=True, slots=True)
class FeatureNarrative:
    """The English name and unit of one feature. Prose only: no threshold,
    no direction, no sample -- those live in the frozen registry spec and
    are read from there, so this table can never disagree with the thing
    the genome actually decided on."""

    feature: str
    quantity: str  # a noun phrase for what one side's value IS
    unit: str


# One entry per `src.engine.features.REPRODUCIBLE_FEATURES` column, so a
# feature that ever reaches a thesis has a sentence waiting for it.
# `starter_platoon_gap` is present for completeness even though
# `src.evolab.registry` deliberately leaves it unregistered (no honest
# standalone sign), so it can never actually fire a genome signal today.
FEATURE_NARRATIVES: dict[str, FeatureNarrative] = {
    n.feature: n for n in (
        FeatureNarrative(
            feature="lineup_platoon_share",
            quantity="the share of the posted lineup holding the platoon "
                     "advantage over the starter it faces",
            unit=SHARE),
        FeatureNarrative(
            feature="starter_platoon_gap",
            quantity="the signed platoon split of the starter this lineup "
                     "faces (wOBA allowed to left-handers minus to "
                     "right-handers)",
            unit=WOBA),
        FeatureNarrative(
            feature="lineup_vs_primary_pitch",
            quantity="this lineup's measured production against the primary "
                     "pitch of the starter it faces",
            unit=WOBA),
        FeatureNarrative(
            feature="primary_pitch_share",
            quantity="the share of pitches the opposing starter throws with "
                     "his single most-used offering",
            unit=SHARE),
        FeatureNarrative(
            feature="top_minus_bottom",
            quantity="this lineup's top-of-order minus bottom-of-order "
                     "strength",
            unit=WOBA),
        FeatureNarrative(
            feature="starter_velocity_gap",
            quantity="how far the opposing starter's fastball sits above "
                     "league pace",
            unit=MPH),
        FeatureNarrative(
            feature="starter_groundball_share",
            quantity="the opposing starter's career ground-ball share",
            unit=SHARE),
    )
}

# The convention every per-side feature value obeys, stated once here
# because a reader who does not know it will read every away/home pair
# backwards (`src.evolab.registry`'s SIGN CONVENTION section owns the rule;
# this is its one-line reader-facing form).
SIDE_CONVENTION = ("each side's number describes the matchup that side's "
                   "own lineup faces")

DIRECTION_PHRASE = {
    1: "the side holding more of it is the side the mechanism favours",
    -1: "the side holding more of it is the side the mechanism harms",
}

_ORDINAL = {50.0: "50th", 75.0: "75th", 90.0: "90th"}


def _percentile_phrase(index: int) -> str:
    """Which rung of the fixed three-rung dose ladder this is, in words."""
    if not 0 <= index < len(LADDER_PERCENTILES):
        return f"rung {index + 1}"
    pct = LADDER_PERCENTILES[index]
    name = _ORDINAL.get(pct, f"{pct:g}th")
    return (f"rung {index + 1} of {len(LADDER_PERCENTILES)}, the {name} "
            "percentile")


def _sample_phrase(provenance: str) -> str:
    """The ladder's own derivation sample, quoted from the registry spec's
    `provenance` string rather than restated -- the counts belong to that
    frozen record, and a number retyped here is a number that can drift
    away from the thing it describes."""
    tail = provenance.split(";")[-1].strip()
    return tail or provenance.strip()


def explain_signal(feature: str, threshold_index: int, side: str,
                    features: dict, *, registry=DEFAULT_REGISTRY) -> str:
    """One fired signal as one sentence-group: the two side values, the gap,
    the rung it cleared, the sample behind the rung, and the frozen
    mechanism that says why any of it should matter.

    `side` is the side the signal fired FOR (`decide()`'s own answer), not
    re-derived here: two code paths that must agree about which side a
    signal points to are two code paths that will eventually disagree.
    """
    spec = registry.get(feature)
    narrative = FEATURE_NARRATIVES.get(feature)
    unit = narrative.unit if narrative is not None else ""
    quantity = (narrative.quantity if narrative is not None
                else f"the {feature} value")

    away = features.get("away_" + feature)
    home = features.get("home_" + feature)
    gap = None if (away is None or home is None) else away - home
    threshold = spec.threshold(threshold_index)

    return (
        f"{feature} -- {quantity} ({SIDE_CONVENTION}): away "
        f"{format_value(away, unit)}, home {format_value(home, unit)}; a gap "
        f"of {format_gap(gap, unit)}, clearing the threshold of "
        f"{format_gap(threshold, unit)} ({_percentile_phrase(threshold_index)} "
        f"of that gap over the ladder's derivation sample, "
        f"{_sample_phrase(spec.provenance)}, 2023-24). This mechanism's "
        f"direction was frozen before any search ran at "
        f"{spec.direction:+d} ({DIRECTION_PHRASE.get(spec.direction, '')}), "
        f"so the signal points to the {side} side. Pre-registered reason it "
        f"should matter: {spec.mechanism}."
    )


# The closing sentence on every evolab thesis. It is not decoration: a
# genome's score is a weighted count of fired signals in the genome's own
# units, with no interpretation as probability or advantage
# (`src.evolab.decide.Decision`), and a reader who is not told that will
# supply the missing interpretation themselves.
NO_EDGE_CLAIM = (
    "This is a signal count, not a forecast: the genome publishes no "
    "calibrated probability, so p_model is null and edge_bps is null by "
    "construction. Nothing here says the market's price is mistaken, and "
    "no claim of value is attached to it -- no such claim has been earned "
    "(docs/PREREG_CALIBRATED_PROBABILITY.md)."
)


def evolab_thesis(strategy_id: str, market_key: str, side: str,
                   signals_fired, features: dict, *,
                   registry=DEFAULT_REGISTRY) -> str:
    """The full thesis for one evolab genome decision.

    `strategy_id` is named as the genome's id ONLY at the end, as
    attribution -- never as the explanation. The pick has to be readable by
    someone who will never look up that id, which is exactly what the
    previous "evolab genome <hash>: (('top_minus_bottom', 1),)" thesis
    made impossible.
    """
    fired = tuple(signals_fired or ())
    if not fired:
        # decide() cannot return a Decision with zero fired signals, so this
        # is a defensive branch: say what is known rather than manufacture a
        # reason that did not exist.
        body = ("no signal detail was carried out of the decision, so no "
                "feature-level reason can be stated here")
    else:
        parts = [explain_signal(feature, index, side, features,
                                registry=registry)
                 for feature, index in fired]
        body = " ".join(f"({i}) {p}" for i, p in enumerate(parts, start=1))

    count = len(fired)
    plural = "signal" if count == 1 else "signals"
    return (
        f"Backing the {side} side of {market_key} because {count} "
        f"pre-registered {plural} fired: {body} {NO_EDGE_CLAIM} "
        f"(Strategy: evolab genome {strategy_id}.)"
    )


# --- The machine-checkable honesty rule -------------------------------------
#
# "The word 'edge' must not appear in a thesis unless edge_bps is non-None"
# is the owner's rule; stated that literally it would also forbid the
# market-derived thesis from DENYING an edge, which is the one place the
# word is genuinely load-bearing. So the check strips explicit denials
# first and only then looks for a value claim. A new denial phrasing that
# is not in this list fails closed (reads as a claim) -- the safe direction.

EDGE_DENIALS = (
    "edge_bps is null by construction",
    "edge_bps is structurally none",
    "edge_bps is null",
    "no edge_bps can ever be computed",
    "no edge is claimed",
    "no edge",
    "not an edge",
    "never an edge",
    "no calibrated probability",
    "carries no edge",
    "by construction carries the market's own probability and no edge",
)

# Words that assert value. `edge` is the obvious one; the others are how an
# edge claim gets smuggled past a grep for "edge".
EDGE_CLAIM_WORDS = (
    "edge", "+ev", "expected value", "expected profit", "profitable",
    "overpriced", "underpriced", "mispriced", "value bet", "beat the market",
    "probability advantage",
)


def claims_edge(thesis: str | None) -> bool:
    """True when `thesis` asserts an edge/value claim of any kind.

    Denials are removed before the scan, so "edge_bps is null by
    construction" is not an edge claim while "a 3% edge on this line" is.
    Case-insensitive; punctuation-insensitive enough for prose.
    """
    if not thesis:
        return False
    text = thesis.lower()
    for denial in EDGE_DENIALS:
        text = text.replace(denial, " ")
    # `(?<![a-z])` rather than `\b`: "+ev" starts with a non-word character,
    # for which `\b` matches in the wrong place and silently never fires.
    return any(re.search(r"(?<![a-z])" + re.escape(word), text)
               for word in EDGE_CLAIM_WORDS)
