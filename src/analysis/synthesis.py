"""Synthesis: the three-to-five things that actually matter about one game.

WHY THIS EXISTS
---------------
The Analyzer now emits a lot per game: detector findings, matchup depth (four
pictures per side), starter rates, splits, lineups, batter-vs-pitcher history,
price improvement, roster news, park and weather. Every one of those sections
earned its place, and together they drown the reader. A page that contains the
answer but does not say it is not a briefing, it is a filing cabinet.

This module is the sharp-friend summary that belongs at the top of a game
card: out of everything the system knows about tonight's game, here are the
three to five things worth saying out loud, ranked, with the samples attached.

WHAT IT DOES NOT DO
-------------------
It does not compute anything new. Every item is a restatement of a number some
other module already derived, against a baseline that module already stated.
If a section has no baseline for a number, that number does not become an item
-- it is recorded as suppressed with the reason, never promoted with an
invented reference point. The same rule that governs the dossier governs this:
absence over guess.

It also does not produce a recommendation. Twenty-seven pre-registered
hypotheses across V1-V5 have been measured against outcomes and none cleared
the bar, so nothing here reads as an edge. Price improvement in particular is
line-shopping value -- a better execution price -- and is labelled as such,
never as expected value. "Interesting matchup, but no demonstrated betting
edge" is the expected headline, not a failure of the module.

HOW THE RANKING WORKS
---------------------
Each candidate is scored on five terms, each normalised to 0..1, then
multiplied by a factor for the strength of its evidence:

  magnitude   how big the effect is, in units of a stated scale for its kind
              (a wOBA gap and a fastball gap are not comparable raw, so each
              kind carries the size at which it would be worth a sentence);
  sample      how much play sits behind it, log-scaled, halved when the value
              rests below the floor its own section publishes;
  tonight     whether it depends on tonight's posted lineup and starter, or is
              a standing team-level fact that was true last week too;
  market      whether it bears on a price at all;
  novelty     whether a knowledgeable fan already has it in his head. "Their
              ace is better than their fifth starter" is true and worthless;
              "the four-seamer he throws 58% of the time is the pitch this
              lineup has hit best" is the same category of fact and is not.

The scales and weights below are presentation judgements about what deserves a
reader's attention. They are not measured effect sizes and no number produced
here is a probability or a confidence.

DEDUPLICATION
-------------
The same underlying fact reaches this module twice on purpose: the platoon
detector and the matchup-depth handedness picture are both reading the same
starter's split. Candidates therefore carry a fact key, and only the
highest-scoring candidate per key survives; the loser is recorded in
`suppressed` with the key it duplicated, so a reader can see that the page
chose between two statements rather than losing one.
"""

from __future__ import annotations

import math
import re

from src.detect import base as detect

# ---------------------------------------------------------------------------
# Presentation constants. Judgements about attention, not measured effects.
# ---------------------------------------------------------------------------

# The size at which a difference of each kind is worth a sentence. A candidate
# at this magnitude scores 1.0 on the magnitude term; larger does not score
# higher, because past "worth saying" the ranking should turn on the other
# terms rather than on who has the biggest number.
SCALES = {
    "platoon": 0.100,        # wOBA gap between a starter's two platoon sides
    "concentration": 0.100,  # wOBA gap between lineup slots 1-4 and 5-9
    "pitch_mix": 0.080,      # wOBA gap vs one pitch type against overall
    "velocity": 2.0,         # mph against the league average at the cutoff
    "price": 2.0,            # percent of return over the de-vigged consensus
    "detector": 3.0,         # a detector's own surprise, in units of normal
}

WEIGHTS = {
    "magnitude": 0.35,
    "sample": 0.20,
    "tonight": 0.15,
    "market": 0.10,
    "novelty": 0.20,
}

# Below this a candidate is not worth the reader's top block. It still renders
# in its own section further down the card -- nothing is deleted here, only
# left out of the summary.
#
# Chosen against the real distribution rather than picked round: scored across
# the 2024-09-01 slate, candidates run from about 0.30 to 0.56, and this bar
# admits one to four items per game with a posted lineup. It admits none at all
# on a game with no posted lineup and a vigged board, which is the correct
# answer for such a game and not a bug.
MIN_SCORE = 0.42

# Price improvement smaller than this is board noise, not something to lead a
# card with. In percent of return over the consensus.
MIN_PRICE_IMPROVEMENT_PCT = 1.0

# Sample floors published by the sections these items come from, repeated here
# only to mark a below-floor value; the sections remain the authority.
FLOORS = {
    "platoon": 120,        # 60 batters faced per side (rebuilt.MIN_BF_PER_SIDE)
    "concentration": 120,  # 60 PA per lineup half (matchup.MIN_HALF_PA)
    "pitch_mix": 60,       # matchup.MIN_LINEUP_PA_VS_PITCH
    "velocity": 100,       # rebuilt.MIN_FASTBALLS_FOR_VELOCITY
    "price": 6,            # prices.MIN_BOOKS
}

# How much of this a knowledgeable fan already carries. Lower means more
# familiar, and familiar facts lose to unfamiliar ones of the same size.
NOVELTY = {
    "starter_mismatch": 0.45,
    "travel_load": 0.40,
    "park_and_weather": 0.40,
    "bullpen_workload": 0.60,
    "bullpen_exposure": 0.70,
    "lineup_vs_starter": 0.70,
    "platoon_mismatch": 0.75,
    "pitch_mix_mismatch": 0.80,
    "implied_bullpen_disagreement": 0.90,
    "stale_book": 0.85,
    "thin_matchup_history": 0.95,
}
DEFAULT_NOVELTY = 0.70

# Detectors whose reading depends on tonight's posted lineup or starter rather
# than on a standing team-level fact.
TONIGHT_DETECTORS = frozenset({
    "platoon_mismatch", "pitch_mix_mismatch", "lineup_vs_starter",
    "starter_mismatch", "thin_matchup_history", "stale_book",
    "implied_bullpen_disagreement",
})

# Strength of evidence as a multiplier. A refuted claim keeps its place on the
# page but must never outrank an open question of the same size.
EVIDENCE_FACTOR = {
    detect.BLOCKED: 0.30,
    detect.TESTED_NULL: 0.60,
    detect.UNPROVEN: 0.80,
    detect.HISTORICAL_CANDIDATE: 0.85,
    detect.TUNING_EVIDENCE: 0.90,
    detect.PROVISIONAL: 0.95,
    detect.FORWARD_TESTING: 1.00,
    detect.PROVEN: 1.00,
}

# An observed price is not a hypothesis about outcomes at all, so it does not
# belong anywhere on the detector evidence ladder. It gets its own status.
OBSERVED = "observed"
# Sits at the same multiplier as an untested hypothesis on purpose: the price
# itself is certain, what it is worth is not, and the summary must not let a
# well-observed number outrank a well-evidenced one.
EVIDENCE_FACTOR[OBSERVED] = 0.80

EVIDENCE_LABELS = {
    detect.PROVEN: ("Proven", "Held up on data it was not built from"),
    detect.FORWARD_TESTING: ("Forward testing",
                             "Logged before the games; still accumulating"),
    detect.PROVISIONAL: ("Provisional",
                         "One-shot backtest; weaker than forward proof"),
    detect.TUNING_EVIDENCE: ("Tuning evidence",
                             "Thresholds were fitted on this; optimistic"),
    detect.HISTORICAL_CANDIDATE: ("Candidate",
                                  "Looks real in discovery data; untested"),
    detect.UNPROVEN: ("Unproven", "A written-down guess. Never tested."),
    detect.TESTED_NULL: ("Tested — no edge",
                         "Measured against outcomes and it did not predict them"),
    detect.BLOCKED: ("Blocked", "Cannot be computed with the data we have"),
    OBSERVED: ("Observed",
               "A price actually quoted on the board — line-shopping value, "
               "not expected value and not a prediction"),
}

NO_EDGE_HEADLINE = ("Interesting matchup, but no demonstrated betting edge.")

NOTE = ("Ranked by size, sample, how much it depends on tonight, and how "
        "little of it a knowledgeable fan already carries. Nothing here is a "
        "prediction or an edge: 27 pre-registered hypotheses across V1–V5 "
        "have been measured against outcomes and none cleared the bar.")

NOTHING_CLEARED_NOTE = (
    "Everything the system found about this game is either too small, too "
    "thinly sampled, or too obvious to lead with. The sections below still "
    "hold the full picture.")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def top_findings(dossier=None, depth=None, price_improvement=None,
                 findings=None, limit=5) -> list:
    """The ranked, deduplicated items for one game. Possibly empty.

    Every argument is optional and None is a normal value throughout: a game
    with no posted lineup, no multi-book board and no detector output yields
    an empty list, never a fabricated item.

    `depth` and `price_improvement` default to the dossier's own sections, so
    the ordinary caller passes only the dossier and the detector findings.
    """
    sections = getattr(dossier, "sections", None) or {}
    if depth is None:
        depth = sections.get("matchup_depth")
    if price_improvement is None:
        price_improvement = sections.get("price_improvement")

    candidates, _ = _candidates(dossier, depth, price_improvement, findings)
    kept, _ = _resolve(candidates)
    return kept[:limit] if limit is not None else kept


def synthesize(dossier=None, findings=None, depth=None,
               price_improvement=None, limit=5) -> dict:
    """`top_findings` plus the headline and the audit trail of what was cut.

    Returns a plain dict so the dashboard can render it and `_plain` can
    serialise it without knowing anything about this module.
    """
    sections = getattr(dossier, "sections", None) or {}
    if depth is None:
        depth = sections.get("matchup_depth")
    if price_improvement is None:
        price_improvement = sections.get("price_improvement")

    candidates, skipped = _candidates(dossier, depth, price_improvement,
                                      findings)
    kept, suppressed = _resolve(candidates)
    if limit is not None:
        for item in kept[limit:]:
            suppressed.append({"statement": item["statement"],
                               "reason": f"outside the top {limit}"})
        kept = kept[:limit]
    return {
        "items": kept,
        "cleared": bool(kept),
        "headline": kept[0]["statement"] if kept else NO_EDGE_HEADLINE,
        "note": NOTE if kept else NOTHING_CLEARED_NOTE,
        "suppressed": skipped + suppressed,
    }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _magnitude_term(magnitude, kind) -> float:
    scale = SCALES.get(kind)
    if magnitude is None or not scale:
        return 0.0
    return min(1.0, abs(magnitude) / scale)


def _sample_term(sample_n, kind) -> tuple:
    """Support from the sample, and whether it sits below its own floor.

    Log-scaled: a thousand plate appearances is meaningfully better than a
    hundred, and a hundred thousand is not meaningfully better than ten
    thousand. A value under the floor its section publishes keeps its place
    but is halved, because the section already prints a small-sample warning
    next to it and the summary must not out-shout that warning.
    """
    if not sample_n or sample_n <= 0:
        # Unparseable or absent: conservative, never zero, never invented.
        return 0.40, False
    support = min(1.0, math.log10(sample_n) / 3.0)
    floor = FLOORS.get(kind)
    if floor and sample_n < floor:
        return round(support * 0.5, 4), True
    return round(support, 4), False


def _score(candidate) -> dict:
    sample_term, below_floor = _sample_term(candidate.get("sample_n"),
                                            candidate["kind"])
    terms = {
        "magnitude": _magnitude_term(candidate.get("magnitude"),
                                     candidate["kind"]),
        "sample": sample_term,
        "tonight": candidate.get("tonight", 0.5),
        "market": candidate.get("market", 0.5),
        "novelty": candidate.get("novelty", DEFAULT_NOVELTY),
    }
    raw = sum(WEIGHTS[name] * value for name, value in terms.items())
    factor = EVIDENCE_FACTOR.get(candidate.get("evidence"), 0.80)
    label, meaning = EVIDENCE_LABELS.get(candidate.get("evidence"),
                                         (candidate.get("evidence") or "", ""))
    return {
        "statement": candidate["statement"],
        "category": candidate["category"],
        "magnitude": candidate.get("magnitude"),
        "magnitude_units": candidate.get("units"),
        "sample": candidate["sample"],
        "sample_n": candidate.get("sample_n"),
        "below_floor": below_floor,
        "evidence": candidate.get("evidence"),
        "evidence_label": label,
        "evidence_meaning": meaning,
        "source": candidate["source"],
        "fact_key": candidate["fact_key"],
        "side": candidate.get("side"),
        "score": round(raw * factor, 4),
        "terms": {name: round(value, 4) for name, value in terms.items()},
    }


def _resolve(candidates) -> tuple:
    """Score, drop the below-bar, dedupe by fact key, sort. Returns (kept, cut)."""
    scored = [_score(c) for c in candidates]
    cut = []
    above = []
    for item in scored:
        if item["score"] < MIN_SCORE:
            cut.append({"statement": item["statement"],
                        "reason": (f"scored {item['score']:.3f}, below the "
                                   f"{MIN_SCORE:.2f} bar for the summary")})
        else:
            above.append(item)

    # Deterministic ordering before dedup, so which of two equal-scoring
    # duplicates survives never depends on dict iteration order.
    above.sort(key=lambda i: (-i["score"], i["category"], i["statement"]))
    kept, seen = [], {}
    for item in above:
        winner = seen.get(item["fact_key"])
        if winner is not None:
            cut.append({
                "statement": item["statement"],
                "reason": ("restates the same fact as another item "
                           f"({winner}); the higher-scoring statement was "
                           "kept")})
            continue
        seen[item["fact_key"]] = item["source"]
        kept.append(item)
    return kept, cut


# ---------------------------------------------------------------------------
# Candidate extraction
# ---------------------------------------------------------------------------

def _candidates(dossier, depth, price_improvement, findings) -> tuple:
    candidates, skipped = [], []
    _from_depth(depth, candidates, skipped)
    _from_price(dossier, price_improvement, candidates, skipped)
    _from_findings(dossier, findings, candidates, skipped)
    return candidates, skipped


# -- matchup depth ----------------------------------------------------------

def _from_depth(depth, candidates, skipped) -> None:
    if not isinstance(depth, dict):
        return
    if depth.get("reason"):
        skipped.append({"statement": "matchup depth",
                        "reason": depth["reason"]})
        return
    for side in ("away", "home"):
        entry = depth.get(side)
        if not isinstance(entry, dict):
            continue
        if entry.get("reason"):
            skipped.append({"statement": f"{side} matchup depth",
                            "reason": entry["reason"]})
            continue
        team = entry.get("team") or side
        _depth_platoon(side, team, entry, candidates)
        _depth_pitch_mix(side, team, entry, candidates, skipped)
        _depth_concentration(side, team, entry, candidates)
        _depth_velocity(side, team, entry, candidates)
        _depth_groundball(entry, skipped)


def _depth_platoon(side, team, entry, candidates) -> None:
    picture = entry.get("handedness") or {}
    starter = picture.get("starter")
    if not starter or starter.get("gap") is None:
        return
    left, right = starter.get("vs_left_faced"), starter.get("vs_right_faced")
    if left is None or right is None:
        return
    weaker = "left-handed" if starter.get("weaker_against") == "L" else "right-handed"
    statement = (
        f"The starter {team} face has allowed "
        f"{starter['vs_left_woba']:.3f} wOBA to left-handed hitters and "
        f"{starter['vs_right_woba']:.3f} to right-handed before the cutoff — "
        f"a {abs(starter['gap']):.3f} gap, and he is worse against "
        f"{weaker} bats.")
    lineup = picture.get("lineup")
    if lineup and lineup.get("advantaged") is not None:
        statement += (f" Tonight {team} post {lineup['advantaged']} of "
                      f"{lineup['known']} known bat sides with the platoon "
                      f"advantage.")
    candidates.append({
        "kind": "platoon",
        "category": "starter platoon split",
        "statement": statement,
        "magnitude": abs(starter["gap"]),
        "units": "wOBA",
        "sample": f"{left} batters faced left-handed, {right} right-handed",
        "sample_n": left + right,
        "tonight": 1.0,
        "market": 0.6,
        "novelty": 0.85,
        # The platoon family was part of the thirteen Stage-2 hypotheses
        # measured against 2023-24 outcomes; none predicted.
        "evidence": detect.TESTED_NULL,
        "source": "matchup depth (handedness)",
        "fact_key": f"platoon:{side}",
        "side": side,
    })


def _depth_pitch_mix(side, team, entry, candidates, skipped) -> None:
    """This lineup against the pitch it will see most, against its own norm.

    The baseline is the same hitters' pooled wOBA against everything, taken
    from the concentration picture. That is a real reference point derived
    from the same store and the same cutoff; when it is missing there is no
    honest baseline to state, so nothing is minted.
    """
    picture = entry.get("pitch_mix") or {}
    primary = picture.get("primary")
    line = picture.get("lineup_vs_primary")
    if not primary or not line or line.get("woba") is None:
        return
    overall = _pooled_overall(entry)
    if overall is None:
        skipped.append({
            "statement": f"{team} vs the {primary['pitch_type']}",
            "reason": ("no pooled line for the same hitters against all "
                       "pitch types, so there is no baseline to state the "
                       "gap against")})
        return
    gap = round(line["woba"] - overall["woba"], 4)
    direction = "better" if gap > 0 else "worse"
    statement = (
        f"{team} have run {line['woba']:.3f} wOBA against the "
        f"{primary['pitch_type']} — the pitch the starter they face throws "
        f"{primary['usage_pct']:.0f}% of the time — against "
        f"{overall['woba']:.3f} for the same hitters against everything, "
        f"{abs(gap):.3f} {direction}.")
    candidates.append({
        "kind": "pitch_mix",
        "category": "lineup vs primary pitch",
        "statement": statement,
        "magnitude": abs(gap),
        "units": "wOBA",
        "sample": (f"{line['pa']} PA against the pitch, {overall['pa']} PA "
                   f"overall, {line['batters_measured']} hitters measured"),
        "sample_n": line["pa"],
        "tonight": 1.0,
        "market": 0.6,
        "novelty": 0.90,
        "evidence": detect.TESTED_NULL,
        "source": "matchup depth (pitch mix)",
        "fact_key": f"pitch_mix:{side}",
        "side": side,
    })


def _pooled_overall(entry):
    """Slots 1-4 and 5-9 pooled back together, with the PA total kept."""
    concentration = entry.get("concentration") or {}
    top, bottom = concentration.get("top"), concentration.get("bottom")
    value, denom = 0.0, 0
    for half in (top, bottom):
        if half and half.get("pa"):
            value += half["woba"] * half["pa"]
            denom += half["pa"]
    if not denom:
        return None
    return {"woba": round(value / denom, 4), "pa": denom}


def _depth_concentration(side, team, entry, candidates) -> None:
    picture = entry.get("concentration") or {}
    gap, top, bottom = picture.get("gap"), picture.get("top"), picture.get("bottom")
    if gap is None or not top or not bottom:
        return
    # A top four better than the bottom five is what everyone already assumes,
    # so the ordinary direction is barely worth a line. The inversion is not.
    inverted = gap < 0
    if inverted:
        statement = (
            f"{team}'s bottom of the order has out-hit its top: slots 5-9 have "
            f"run {bottom['woba']:.3f} wOBA against {top['woba']:.3f} from "
            f"slots 1-4 before the cutoff.")
    else:
        statement = (
            f"{team}'s lineup is top-heavy: slots 1-4 have run "
            f"{top['woba']:.3f} wOBA against {bottom['woba']:.3f} from slots "
            f"5-9 before the cutoff, a {gap:.3f} gap.")
    candidates.append({
        "kind": "concentration",
        "category": "lineup concentration",
        "statement": statement,
        "magnitude": abs(gap),
        "units": "wOBA",
        "sample": f"{top['pa']} PA in slots 1-4, {bottom['pa']} PA in 5-9",
        "sample_n": top["pa"] + bottom["pa"],
        "tonight": 1.0,
        "market": 0.4,
        "novelty": 0.95 if inverted else 0.45,
        "evidence": detect.TESTED_NULL,
        "source": "matchup depth (concentration)",
        "fact_key": f"concentration:{side}",
        "side": side,
    })


def _depth_velocity(side, team, entry, candidates) -> None:
    picture = entry.get("starter_stuff") or {}
    velocity = picture.get("velocity")
    if not velocity or velocity.get("gap") is None:
        return
    gap = velocity["gap"]
    direction = "below" if gap < 0 else "above"
    statement = (
        f"The starter {team} face has averaged {velocity['avg']:.1f} mph on "
        f"the fastball over his last {velocity['games']} measured "
        f"appearances, {abs(gap):.1f} mph {direction} the league average of "
        f"{velocity['league_avg']:.1f} at the same cutoff.")
    candidates.append({
        "kind": "velocity",
        "category": "starter stuff",
        "statement": statement,
        "magnitude": abs(gap),
        "units": "mph",
        "sample": (f"{velocity['fastballs']} fastballs over "
                   f"{velocity['games']} appearances"),
        "sample_n": velocity["fastballs"],
        "tonight": 1.0,
        "market": 0.6,
        "novelty": 0.80,
        # V5 tested velocity and ground-ball share against the market and
        # found nothing (docs/RESEARCH_V5_STUFF.md).
        "evidence": detect.TESTED_NULL,
        "source": "matchup depth (starter stuff)",
        "fact_key": f"velocity:{side}",
        "side": side,
    })


def _depth_groundball(entry, skipped) -> None:
    """Ground-ball share is measured but has no league baseline at the cutoff.

    A share on its own is a description, not a finding, and inventing a league
    figure to subtract from it would be exactly the fabrication this module
    exists to avoid. It stays in its own section and is recorded here as cut.
    """
    picture = entry.get("starter_stuff") or {}
    if picture.get("groundball"):
        skipped.append({
            "statement": "starter ground-ball share",
            "reason": ("no league ground-ball baseline is computed at the "
                       "same cutoff, so the share cannot be stated as a gap")})


# -- price improvement ------------------------------------------------------

def _from_price(dossier, price_improvement, candidates, skipped) -> None:
    if not isinstance(price_improvement, dict):
        return
    if price_improvement.get("skipped"):
        skipped.append({"statement": "price improvement",
                        "reason": price_improvement["skipped"]})
        return
    books = (price_improvement.get("dispersion") or {}).get("books")
    best_side, best = None, None
    for side in ("away", "home"):
        detail = (price_improvement.get("sides") or {}).get(side) or {}
        pct = detail.get("improvement_return_pct")
        if detail.get("skipped") or pct is None:
            continue
        if best is None or pct > best["improvement_return_pct"]:
            best_side, best = side, detail
    if best is None:
        return
    pct = best["improvement_return_pct"]
    if pct < MIN_PRICE_IMPROVEMENT_PCT:
        skipped.append({
            "statement": "price improvement",
            "reason": (f"the best price improves on the consensus by "
                       f"{pct:+.2f}% of return, below the "
                       f"{MIN_PRICE_IMPROVEMENT_PCT:.1f}% floor for the "
                       "summary")})
        return
    team = _team_for_side(dossier, best_side) or best_side
    price = best.get("best_price")
    price_text = (f"+{price}" if isinstance(price, int) and price > 0
                  else str(price))
    statement = (
        f"The best number on {team} is {price_text} at "
        f"{best.get('best_book') or 'an unnamed book'}, {pct:+.2f}% better in "
        f"return than the de-vigged consensus of {books} books. That is "
        f"line-shopping value — a better execution price — not expected "
        f"value and not a prediction.")
    candidates.append({
        "kind": "price",
        "category": "price improvement",
        "statement": statement,
        "magnitude": pct,
        "units": "% of return",
        "sample": f"{books} books at one capture instant",
        "sample_n": books,
        "tonight": 1.0,
        "market": 1.0,
        "novelty": 0.80,
        "evidence": OBSERVED,
        "source": "price improvement",
        "fact_key": f"price:{best_side}",
        "side": best_side,
    })


def _team_for_side(dossier, side):
    game = getattr(dossier, "game", None) or {}
    return game.get(f"{side}_team")


# -- detector findings ------------------------------------------------------

# Units that denote a countable amount of play. A number in a detector's
# sample string only counts as a sample size when it is followed by one of
# these -- "3 day(s) ago" and "7-day window" name an elapsed time, not an
# amount of evidence, and reading them as denominators would rank a detector
# by how recently something happened.
SAMPLE_UNITS = frozenset({
    "bf", "pa", "ab", "ip", "innings", "plate", "appearances",
    "book", "books", "hitter", "hitters", "batter", "batters", "batted",
    "reliever", "relievers", "start", "starts", "pitch", "pitches",
    "fastball", "fastballs", "game", "games", "outing", "outings",
})

_COUNT = re.compile(r"(\d+(?:\.\d+)?)\s*([A-Za-z][A-Za-z()/\-]*)")


def _sample_size(sample):
    """The largest countable amount of play named in a sample string, or None.

    Detectors write their samples for humans ("8 hitters, 340 plate
    appearances", "120 BF vs L, 90 vs R"). The largest recognised count is the
    denominator the claim actually rests on; the smaller ones count hitters or
    the thinner side. A string that names no countable unit returns None, and
    the sample term then falls back to its conservative default rather than to
    a number that happened to be lying in the sentence.
    """
    if sample is None:
        return None
    found = []
    for number, unit in _COUNT.findall(str(sample)):
        token = "".join(ch for ch in unit if ch.isalpha()).lower()
        if token in SAMPLE_UNITS:
            found.append(int(float(number)))
    return max(found) if found else None


def _batting_side(claim, dossier):
    """Which lineup a detector claim is about, from the claim's own subject.

    A detector's `side` field says which team the finding POINTS TO, which for
    the pitch-mix detector flips with the direction of the read -- so it is
    not the identity of the fact and cannot be used to recognise a duplicate.
    Both starter-subject detectors open with "<pitcher's team>'s starter", so
    the lineup involved is the other one. Anything that does not match that
    shape gets no cross-source key and simply never dedupes against depth.
    """
    away, home = (getattr(dossier, "teams", (None, None))
                  if dossier is not None else (None, None))
    text = str(claim or "")
    if away and text.startswith(f"{away}'s starter"):
        return "home"
    if home and text.startswith(f"{home}'s starter"):
        return "away"
    return None


_CROSS_SOURCE_KEYS = {
    "platoon_mismatch": "platoon",
    "pitch_mix_mismatch": "pitch_mix",
}


def _fact_key(finding, dossier) -> str:
    family = _CROSS_SOURCE_KEYS.get(finding.detector)
    if family:
        side = _batting_side(finding.claim, dossier)
        if side:
            return f"{family}:{side}"
    return f"detector:{finding.detector}:{finding.side}"


def _from_findings(dossier, findings, candidates, skipped) -> None:
    for finding in findings or []:
        if getattr(finding, "kind", None) == detect.CONTEXT:
            continue
        if finding.surprise is None:
            skipped.append({
                "statement": finding.claim,
                "reason": ("the detector could not express its surprise on a "
                           "comparable scale, so it cannot be ranked against "
                           "the others")})
            continue
        if finding.sample is None:
            skipped.append({
                "statement": finding.claim,
                "reason": ("no sample size attached, and no claim reaches the "
                           "summary without one")})
            continue
        candidates.append({
            "kind": "detector",
            "category": finding.detector,
            "statement": finding.claim,
            "magnitude": finding.surprise,
            "units": "standard units from normal",
            "sample": str(finding.sample),
            "sample_n": _sample_size(finding.sample),
            "tonight": 1.0 if finding.detector in TONIGHT_DETECTORS else 0.6,
            "market": 1.0 if finding.market_relevance else 0.6,
            "novelty": NOVELTY.get(finding.detector, DEFAULT_NOVELTY),
            "evidence": finding.evidence,
            "source": f"detector: {finding.detector}",
            "fact_key": _fact_key(finding, dossier),
            "side": finding.side,
        })
