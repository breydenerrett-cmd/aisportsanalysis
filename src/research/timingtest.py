"""The V3 primary test: is reaction to an event slower than our own resolution?

WHAT IS BEING TESTED
---------------------
docs/RESEARCH_V3_TIMING.md lines 102-105 (frozen): each admitted class
contributes ONE primary hypothesis -- "median time to 50%-of-books reaction
exceeds the capture-spacing floor (i.e., latency is measurable at our
resolution, not instantaneous)". Lines 163-166 make the floor itself
per-event, not a single class-wide constant: "the reaction ladder's
resolution floor is therefore the poll spacing in force at each event, and
the primary hypothesis is stated against exactly that floor" -- the LITERAL
spacing between the two polls that bracket the event (`event_interval`,
threaded through by timingreport.report()), never inferred from an event's
distance to first pitch. An adversarial review (docs/RESEARCH_V3_TIMING.md
ADDENDUM 2) found the first read had done exactly the inference this module
now refuses: a >180-minutes-to-first-pitch heuristic assigned a 60-minute
floor to 20 events whose actually-recorded bracket was 14-18 minutes wide.

Because the floor varies event by event, this module tests the PAIRED
per-event formulation the doc's own wording already commits to: for each
event, diff = (minutes to 50%-of-books reaction) - (that event's own
capture-spacing floor); H1 is median(diff) > 0.

THE PRIMARY STATISTIC, AFTER ADVERSARIAL REVIEW (ADDENDUM 2)
--------------------------------------------------------------
The first read bootstrapped S_hat(0) (the survival function of diff,
evaluated at 0) instead of the KM median itself, because a percentile
bootstrap of a "not reached" median has no obvious interval. That produced a
DEGENERATE result -- point estimate 1.000, 95% CI [1.000, 1.000] -- because
every observed diff in that sample was comfortably positive, so no resample
could produce a counterexample; the boundary looked like certainty and read
like one. The corrected primary statistic is the thing the pre-registration
actually names, `km_median(diff)`, bootstrapped directly, with "not
reached" resamples coded as +infinity rather than dropped -- a resample
whose median is not reached is not evidence the true median is small, it is
evidence it is AT LEAST the resample's longest follow-up, and infinity is
the honest encoding of "at least this large, no further bound available"
for a percentile interval. S(0) is retained only as a supporting boundary
note (median(diff) > 0 iff S(0) > 0.5, so the two can never disagree in
sign) and is never reported with an interval or p-value when its own
bootstrap is degenerate (every resample identical) -- a `degenerate: true`
flag replaces those fields, per ADDENDUM 2's explicit instruction not to let
a boundary artifact masquerade as a confidence interval.

THE P-VALUE, AFTER ADVERSARIAL REVIEW (ADDENDUM 2)
-----------------------------------------------------
"p = 0.000" from the S(0) bootstrap was a resampling artifact, not a formal
test: with every observed value on one side of zero, no percentile
resample can cross it, so the reported tail probability is a property of
the bootstrap's inability to extrapolate, not of the null. The corrected
p-value is `cluster_sign_test`: exactly one vote per cluster (game_pk), an
exact one-sided binomial tail under the null that a cluster is equally
likely to land on either side of the floor. When every classifiable
cluster lands on the H1 side, this is `0.5 ** n` -- small, but honestly
small, not a bootstrap artifact. When zero clusters land on the H1 side,
the sign test alone says only "not significant" (p=1.0); a rule-of-three
bound is reported alongside it as the more informative statement available
from a true zero count.

THE RELEVANCE RULE (ADDENDUM 2, FIX FOR THE CLASS MISMATCH)
---------------------------------------------------------------
The frozen `il_roster_move` class (RESEARCH_V3_TIMING.md:43) is "IL
placement/activation, trade, recall ... affecting the game" -- not every
transaction id first seen. `src.pipeline.rosterwatch` captures every
transaction id (56 tested at first read spanned everything from IL
placements to Triple-A options), which is a different, broader class than
what was frozen. `game_relevant()` restates the frozen definition as a
filter over the feed's own move-type vocabulary
(`src.providers.mlb_news.classify`), decided from the vocabulary alone --
before this module ever looked at a single reaction time -- and is the
PRIMARY reading's gate for `transaction_first_seen`; the unfiltered
all-transactions reading is retained and reported as SECONDARY/exploratory,
never promoted. Every other class carries no "category" field at all (only
the transaction feed has one) and is therefore always relevant here -- this
rule can only ever narrow `transaction_first_seen`.

CENSORING, HANDLED HONESTLY
----------------------------
An event whose 50%-of-books quorum never moves before first pitch has no
observed reaction time -- eventstudy.measure() already returns
ladder_minutes["50%"] = None for exactly this case, because its own quote
series is truncated at the mapped game's start before the ladder is built.
That is a right-censored observation, not a missing one: the true diff is
at least (minutes from event to first pitch) - floor, and treating it as
absent (the "complete-case" convention) drops precisely the slowest
events, biasing any complete-case median DOWNWARD -- toward LESS measured
latency, the conservative direction for this hypothesis. This module
reports the complete-case medians (labelled with that bias) AND a
Kaplan-Meier estimator that folds the censored events back in properly.

THE READING RULE, ENFORCED HERE TOO
-------------------------------------
`test_class` refuses to look inside a class's measured events at all when
that class's MEASURABLE count is below `leadlag.MIN_EVENTS` (30) -- the
same floor leadlag.response_table already enforces, restated here because
this module reads the same underlying list independently. Below the floor
it returns counts only, exactly as timingreport.report() does; there is no
argument to see the numbers early. For a class with a relevance rule, the
SAME floor applies a second time to the relevant subset alone -- clearing
the floor on the unfiltered count does not entitle a primary read on the
narrower one, and a relevant subset short of 30 is reported as exactly
that (not silently backfilled from the exploratory reading).

THE FDR DENOMINATOR (ADDENDUM 2, FIX FOR THE DISAGREEING DENOMINATORS)
--------------------------------------------------------------------------
`FAMILY_ADMITTED_CLASSES` is the single place this number is read from.
The rule (stated identically in docs/RESEARCH_V3_TIMING.md ADDENDUM 2 and
docs/RESEARCH_V3_UMPIRE_CLASS.md): the denominator is MONOTONE
NON-DECREASING -- classes may be admitted, never removed -- and the
correction applied at any read time uses the denominator IN FORCE AT THAT
READ. A class admitted after an earlier read re-corrects the whole family,
already-read p-values included, the next time the family correction is
computed. At freeze (2026-08-31) the family held 4 classes; the umpire
amendment (2026-09-02, docs/RESEARCH_V3_UMPIRE_CLASS.md) admitted a 5th;
this constant is 5 from that point forward.
"""

from __future__ import annotations

import datetime as dt
import math
import random

from src.research import leadlag, timingreport

# Same floor leadlag.response_table already enforces on the identical
# "measurable" (excluded is None) count. Restated as its own name here
# because this module's gate is independent of leadlag's -- if leadlag's
# floor ever changed without this module changing too, silently reading
# early is exactly the failure mode the doc warns against.
CLASS_FLOOR = leadlag.MIN_EVENTS

# Bootstrap: resamples CLUSTERS (one game/day per event, per the task's
# "cluster by game/day"), with replacement. Same resample count and the same
# "sort cluster keys for reproducibility" discipline as
# src/model/discovery.clustered_bootstrap, whose docstring explains why an
# unsorted cluster order makes the same data produce a different interval.
# Written locally, not delegated to that function, because a KM quantity
# bootstrapped here can come back `None` ("not reached") on a resample --
# discovery.clustered_bootstrap silently drops `None` draws and never
# reports how often that happened, which this module needs to report (and,
# per ADDENDUM 2, needs to CODE as +infinity rather than drop).
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20260901

# The pre-registered family (docs/RESEARCH_V3_TIMING.md freeze record: 4
# classes; docs/RESEARCH_V3_UMPIRE_CLASS.md amendment, 2026-09-02: a 5th).
# See the module docstring's "THE FDR DENOMINATOR" section -- this is the
# single place the number is read from; both docs must read the same value.
FAMILY_ADMITTED_CLASSES = 5
FDR_Q = 0.10

# ---------------------------------------------------------------------------
# The relevance rule (ADDENDUM 2) -- decided from the transaction-type
# vocabulary alone, blind to every reaction time in the sample.
# ---------------------------------------------------------------------------

# `src.providers.mlb_news.classify()`'s own vocabulary is the only per-event
# type information the captured stores carry (data/watch/transactions_watch
# .jsonl's "category" field, copied onto the event by
# src.pipeline.rosterwatch._transaction_events -- see that function's
# comment for why this is additive, not a rewrite of any stored row).
# RELEVANT: the transaction plausibly changes who is available for THIS
# game, on the day it is filed -- an IL placement or activation, a recall to
# the active roster, or a trade (RESEARCH_V3_TIMING.md:43's own list).
GAME_RELEVANT_TRANSACTION_CATEGORIES = frozenset({
    "il_placement", "il_activation", "recalled", "traded",
})

# NOT RELEVANT, decided the same way: an option to the minors and a rehab
# assignment do not touch the active roster for tonight's game (the player
# was already off it, or is going to be); a DFA is a paperwork step that
# frequently follows a player already out of the picture, not an in-game
# roster change; a signing is overwhelmingly a minor-league or non-roster
# deal in this feed; an IL-to-IL transfer (10-day <-> 60-day) changes no
# availability, since the player was unavailable on both sides of it.
# "other" is the classifier's catch-all -- it folds in raw MLB move types
# this repo has never named individually (its own audit found "Assigned",
# "Selected", "Released" among them) -- and a raw "Selected" (added to the
# 40-man/active roster, e.g. a Rule 5 pick) plausibly SHOULD be relevant by
# the same logic as "recalled", but the stored vocabulary cannot separate it
# from "Released" or misc paperwork. Rather than guess, "other" and the
# missing-category rows (the oldest transactions, predating the field) are
# both treated as NOT relevant -- the conservative direction, since folding
# an unclassifiable event into the primary reading risks manufacturing an
# apparent effect from noise, while excluding a truly relevant one only
# costs sample size. This granularity limit is a known, stated gap, not a
# guess dressed as a fact.
NON_RELEVANT_TRANSACTION_CATEGORIES = frozenset({
    "optioned", "designated", "rehab", "signed", "il_transfer", "other",
})


def game_relevant(measured_event) -> bool:
    """True unless this is a `transaction_first_seen` event whose recorded
    move-type category is judged not game-affecting (see module docstring
    and the constants above). Every other class's measured events carry no
    "category" key at all (only the transaction feed has a move-type
    vocabulary) and are always relevant here -- this function can only ever
    narrow `transaction_first_seen`, never any other class.
    """
    if "category" not in measured_event:
        return True
    return measured_event.get("category") in GAME_RELEVANT_TRANSACTION_CATEGORIES


UNPARSEABLE_TIMES = "event time or game start unparseable"
NO_GAME_START = "game start time missing; floor and censoring time cannot be computed"
NO_INTERVAL = ("event's own bracket (event_interval) missing or unparseable; "
               "the literal capture-spacing floor cannot be computed")
AT_OR_AFTER_FIRST_PITCH = ("event time at/after its mapped game's start "
                            "(should already be excluded upstream)")


class TimingTestError(RuntimeError):
    """Raised when the test cannot be run honestly."""


def _parse(ts):
    if ts is None:
        return None
    if isinstance(ts, dt.datetime):
        return ts
    try:
        return dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def _count(counter, reason) -> None:
    counter[reason] = counter.get(reason, 0) + 1


def _median(values):
    ordered = sorted(values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _floor_from_interval(interval):
    """The literal poll spacing in force at one event: interval[1] -
    interval[0], in minutes -- RESEARCH_V3_TIMING.md lines 163-166's own
    wording, restated exactly rather than inferred from distance to first
    pitch (ADDENDUM 2's fix; the first read's >180-minutes-to-first-pitch
    heuristic assigned a 60-minute floor to 20 events whose actual recorded
    bracket was 14-18 minutes wide). None when the bracket is missing or
    unparseable -- never a guessed or defaulted number.
    """
    if not interval or len(interval) != 2:
        return None
    start, end = _parse(interval[0]), _parse(interval[1])
    if start is None or end is None:
        return None
    minutes = (end - start).total_seconds() / 60.0
    return minutes if minutes >= 0 else None


# ---------------------------------------------------------------------------
# Per-event rows: floor, reaction, censoring
# ---------------------------------------------------------------------------

def _rows_for_class(usable_measured) -> tuple:
    """One row per usable (excluded is None) measured event, plus an
    exclusion count for anything this stage itself cannot place honestly.

    `usable_measured` must already be filtered to excluded is None (leadlag's
    own convention, restated by the caller) and must carry the game_pk /
    game_start_utc / event_interval fields timingreport.report() now attaches
    to every measured event.
    """
    rows, excluded = [], {}
    for m in usable_measured:
        event_time = _parse(m.get("event_time"))
        game_start = _parse(m.get("game_start_utc"))
        if event_time is None or (m.get("game_start_utc") is not None
                                   and game_start is None):
            _count(excluded, UNPARSEABLE_TIMES)
            continue
        if game_start is None:
            _count(excluded, NO_GAME_START)
            continue
        minutes_to_start = (game_start - event_time).total_seconds() / 60.0
        if minutes_to_start < 0:
            _count(excluded, AT_OR_AFTER_FIRST_PITCH)
            continue
        floor_minutes = _floor_from_interval(m.get("event_interval"))
        if floor_minutes is None:
            _count(excluded, NO_INTERVAL)
            continue
        reaction_minutes = (m.get("ladder_minutes") or {}).get("50%")
        cluster = str(m.get("game_pk") or "unknown")
        row = {"cluster": cluster, "event_time": event_time,
               "floor_minutes": floor_minutes,
               "matchup": m.get("matchup")}
        if reaction_minutes is None:
            row.update(censored=True, reaction_minutes=None, diff_minutes=None,
                       censor_time_minutes=minutes_to_start)
        else:
            row.update(censored=False, reaction_minutes=reaction_minutes,
                       diff_minutes=reaction_minutes - floor_minutes,
                       censor_time_minutes=None)
        rows.append(row)
    rows.sort(key=lambda r: r["event_time"])
    return rows, excluded


# ---------------------------------------------------------------------------
# Kaplan-Meier: survival function, S(t), and the median it implies
# ---------------------------------------------------------------------------

def _km_pairs_diff(rows):
    """(value, censored) for diff = reaction - floor; censored rows carry
    their lower bound (censor_time - floor), since the true diff is at least
    that -- the event was still un-reacted when observation stopped."""
    out = []
    for r in rows:
        if r["censored"]:
            out.append((r["censor_time_minutes"] - r["floor_minutes"], True))
        else:
            out.append((r["diff_minutes"], False))
    return out


def _km_pairs_reaction(rows):
    """(value, censored) for the raw reaction time, uncorrected for floor --
    reported descriptively alongside the diff-based KM estimate."""
    out = []
    for r in rows:
        if r["censored"]:
            out.append((r["censor_time_minutes"], True))
        else:
            out.append((r["reaction_minutes"], False))
    return out


def km_survival_steps(pairs):
    """The Kaplan-Meier step function as [(t, S(t)), ...] at each distinct
    UNCENSORED time, ascending. S(t) = P(true value > t); right-continuous.

    Standard product-limit estimator: at each uncensored time t_i, the risk
    set is every subject (censored or not) whose value is >= t_i -- a
    censored subject's true value could be anything at or beyond its own
    censoring time, so it stays at risk through t_i. d_i is the count of
    uncensored subjects exactly at t_i.
    """
    if not pairs:
        return []
    ordered = sorted(pairs, key=lambda p: p[0])
    n = len(ordered)
    distinct = sorted({t for t, censored in ordered if not censored})
    steps = []
    survival = 1.0
    idx = 0
    for t in distinct:
        while idx < n and ordered[idx][0] < t:
            idx += 1
        at_risk = n - idx
        if at_risk <= 0:
            break
        deaths = sum(1 for tt, censored in ordered if tt == t and not censored)
        survival *= (1 - deaths / at_risk)
        steps.append((t, survival))
    return steps


def km_survival_at(pairs, t):
    """S_hat(t): the KM curve is 1.0 before the first uncensored time and
    holds its last value at or before t thereafter (right-continuous)."""
    survival = 1.0
    for time, value in km_survival_steps(pairs):
        if time <= t:
            survival = value
        else:
            break
    return survival


def km_median(pairs):
    """The smallest t where S_hat(t) <= 0.5, or None when the curve never
    gets there -- "not reached": more than half the (censoring-adjusted)
    mass survived past the longest follow-up in this sample. That is not a
    failure to compute; it is itself an answer (the true median is at least
    that large), and callers must report it as such rather than coercing it
    into a number.
    """
    for t, survival in km_survival_steps(pairs):
        if survival <= 0.5:
            return t
    return None


# ---------------------------------------------------------------------------
# Clustered bootstrap of S(0) -- retained as a SUPPORTING boundary note only
# (ADDENDUM 2: demoted from primary; see module docstring).
# ---------------------------------------------------------------------------

def _bootstrap(rows, statistic, resamples=BOOTSTRAP_RESAMPLES,
               seed=BOOTSTRAP_SEED) -> dict:
    """Resample clusters with replacement; `statistic(sample)` may return
    None (an undefined KM quantity on that resample), tracked explicitly
    rather than silently dropped.
    """
    by_cluster = {}
    for row in rows:
        by_cluster.setdefault(row["cluster"], []).append(row)
    clusters = sorted(by_cluster)
    if len(clusters) < 2:
        return {"draws": [], "undefined": 0, "clusters": len(clusters),
                "reason": "fewer than two clusters to resample"}
    rng = random.Random(seed)
    draws, undefined = [], 0
    for _ in range(resamples):
        sample = []
        for _ in range(len(clusters)):
            sample.extend(by_cluster[clusters[rng.randrange(len(clusters))]])
        value = statistic(sample)
        if value is None:
            undefined += 1
        else:
            draws.append(value)
    return {"draws": draws, "undefined": undefined, "clusters": len(clusters),
            "reason": None}


def _percentile_ci(draws) -> dict:
    if not draws:
        return {"low": None, "high": None}
    ordered = sorted(draws)
    return {"low": round(ordered[int(0.025 * len(ordered))], 5),
            "high": round(ordered[min(len(ordered) - 1,
                                       int(0.975 * len(ordered)))], 5)}


# ---------------------------------------------------------------------------
# Clustered bootstrap of km_median(diff) -- THE PRIMARY STATISTIC (ADDENDUM 2)
# ---------------------------------------------------------------------------

def _median_bootstrap(rows, resamples=BOOTSTRAP_RESAMPLES,
                      seed=BOOTSTRAP_SEED) -> dict:
    """Bootstrap km_median(diff) directly, coding a "not reached" resample as
    +infinity rather than dropping it (discovery.clustered_bootstrap's
    convention, which this module deliberately does not use -- see the
    module docstring's "THE PRIMARY STATISTIC" section). A resample whose
    median is not reached is evidence the true median is AT LEAST that
    resample's longest follow-up, which +infinity encodes honestly for a
    percentile interval: it can only push the upper bound out, never in.
    """
    by_cluster = {}
    for row in rows:
        by_cluster.setdefault(row["cluster"], []).append(row)
    clusters = sorted(by_cluster)
    if len(clusters) < 2:
        return {"draws": [], "not_reached": 0, "clusters": len(clusters),
                "reason": "fewer than two clusters to resample"}
    rng = random.Random(seed)
    draws, not_reached = [], 0
    for _ in range(resamples):
        sample = []
        for _ in range(len(clusters)):
            sample.extend(by_cluster[clusters[rng.randrange(len(clusters))]])
        value = km_median(_km_pairs_diff(sample))
        if value is None:
            not_reached += 1
            draws.append(float("inf"))
        else:
            draws.append(value)
    return {"draws": draws, "not_reached": not_reached, "clusters": len(clusters),
            "reason": None}


def _percentile_ci_with_inf(draws) -> dict:
    """A percentile CI over draws that may include +infinity ("not
    reached"). `high` is reported as the string "not reached" (never a
    fabricated number) when the 97.5th percentile draw is itself infinite;
    `low` the same way in the (degenerate) case every draw is infinite.
    """
    if not draws:
        return {"low": None, "high": None, "high_not_reached": False,
                "low_not_reached": False}
    ordered = sorted(draws)
    low = ordered[int(0.025 * len(ordered))]
    high = ordered[min(len(ordered) - 1, int(0.975 * len(ordered)))]
    low_inf, high_inf = math.isinf(low), math.isinf(high)
    return {"low": "not reached" if low_inf else round(low, 2),
            "high": "not reached" if high_inf else round(high, 2),
            "low_not_reached": low_inf, "high_not_reached": high_inf}


# ---------------------------------------------------------------------------
# Cluster-level exact sign test + rule-of-three bound (ADDENDUM 2, replaces
# "p = 0.000")
# ---------------------------------------------------------------------------

def _binom_sf(k, n, p=0.5) -> float:
    """Exact P(X >= k) for X ~ Binomial(n, p)."""
    return sum(math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i))
               for i in range(k, n + 1))


def cluster_sign_test(rows) -> dict:
    """Cluster-level exact one-sided sign test for H1: diff > 0.

    Each cluster (game_pk) casts exactly ONE vote, not one per event --
    otherwise a cluster contributing many events (docs/RESEARCH_V3_TIMING.md
    ADDENDUM 2's concentration finding: a handful of clusters carry most of
    the observed reactions) would inflate the test's effective n by
    counting the same game's correlated events as independent evidence. A
    cluster is "+" if every one of its events' values (the observed diff,
    or a censored event's lower bound) is on the H1 side (> 0); "-" if every
    one is <= 0; a cluster whose events disagree in sign is a TIE and
    dropped -- neither classification would be honest.

    Under the null that a classifiable cluster is equally likely to land on
    either side, the number of "+" clusters is Binomial(n, 0.5); the
    one-sided p-value is the exact upper tail P(X >= plus). When plus == 0,
    a rule-of-three bound (~3/n) is reported alongside the (uninformative,
    p=1.0) sign test as the more useful statement available from a true
    zero count.
    """
    by_cluster = {}
    for row in rows:
        by_cluster.setdefault(row["cluster"], []).append(row)
    plus = minus = ties = 0
    for crows in by_cluster.values():
        values = [(r["censor_time_minutes"] - r["floor_minutes"])
                  if r["censored"] else r["diff_minutes"] for r in crows]
        positive = sum(1 for v in values if v > 0)
        negative = sum(1 for v in values if v <= 0)
        if positive and negative:
            ties += 1
        elif positive:
            plus += 1
        elif negative:
            minus += 1
    n = plus + minus
    result = {"unit": "game_pk cluster (one vote per cluster, never per event)",
              "clusters_plus": plus, "clusters_minus": minus,
              "clusters_mixed_sign_dropped": ties, "n": n}
    if n == 0:
        result["p_one_sided"] = None
        result["note"] = ("every cluster mixed sign, or no cluster was "
                          "classifiable; the sign test is undefined")
        return result
    result["hypothesis"] = ("H1: more clusters favor diff > 0 than chance "
                            "-- exact one-sided binomial tail, P(X >= "
                            "clusters_plus) under Binomial(n, 0.5)")
    result["p_one_sided"] = round(_binom_sf(plus, n, 0.5), 10)
    if plus == 0:
        bound = 3.0 / n
        result["rule_of_three_bound"] = round(bound, 4)
        result["rule_of_three_note"] = (
            f"0 of {n} clusters favored H1; the sign test alone is "
            "uninformative beyond p=1.0. Rule-of-three upper bound on the "
            f"true H1-favoring cluster rate: ~{bound:.4f}")
    return result


# ---------------------------------------------------------------------------
# Concentration check (RESEARCH_V3_TIMING.md lines 120-121; required by the
# pre-registration, never run before ADDENDUM 2)
# ---------------------------------------------------------------------------

def _concentration(rows) -> dict:
    """How many calendar dates, clusters, and matchups carry this read --
    "a latency result carried by one book, one team, or one week is reported
    as exactly that" (RESEARCH_V3_TIMING.md line 121).
    """
    calendar_dates = sorted({r["event_time"].date().isoformat() for r in rows})
    by_cluster = {}
    for r in rows:
        by_cluster.setdefault(r["cluster"], []).append(r)
    observed_by_cluster = {k: sum(1 for r in v if not r["censored"])
                           for k, v in by_cluster.items()}
    n_observed_total = sum(observed_by_cluster.values())
    ranked = sorted(((cnt, k) for k, cnt in observed_by_cluster.items()
                     if cnt > 0), reverse=True)
    top3_sum = sum(cnt for cnt, _ in ranked[:3])

    matchup_counts = {}
    for r in rows:
        matchup = r.get("matchup")
        if matchup:
            matchup_counts[matchup] = matchup_counts.get(matchup, 0) + 1
    top_matchup = (max(matchup_counts.items(), key=lambda kv: kv[1])
                  if matchup_counts else (None, 0))

    middle = len(rows) // 2
    first_clusters = {r["cluster"] for r in rows[:middle]}
    second_clusters = {r["cluster"] for r in rows[middle:]}
    shared = sorted(first_clusters & second_clusters)

    return {
        "n_calendar_dates": len(calendar_dates),
        "calendar_dates": calendar_dates,
        "n_clusters": len(by_cluster),
        "n_matchups": len(matchup_counts),
        "top_matchup": {"matchup": top_matchup[0], "events": top_matchup[1]},
        "n_observed_total": n_observed_total,
        "clusters_with_any_observed_reaction": len(ranked),
        "top3_clusters_by_observed": [{"cluster": k, "observed": cnt}
                                      for cnt, k in ranked[:3]],
        "share_of_observed_in_top3_clusters": (
            round(top3_sum / n_observed_total, 4) if n_observed_total else None),
        "split_half_shared_clusters": shared,
        "note": ("required by docs/RESEARCH_V3_TIMING.md lines 120-121; "
                 "never run before this correction. A latency result "
                 "carried by one book, team, matchup, or narrow date range "
                 "is reported as exactly that, never as a general finding."),
    }


def _descriptive_extra(usable) -> dict:
    """Countervailing descriptives (docs/RESEARCH_V3_TIMING.md ADDENDUM 2,
    recommended item): the fastest first moves and least-reacted events in
    the sample, so the corrected read cannot be read as "every event was
    slow" by omission.
    """
    first_moves = [m.get("first_move_minutes") for m in usable
                  if m.get("first_move_minutes") is not None]
    ladder_25 = [(m.get("ladder_minutes") or {}).get("25%") for m in usable]
    ladder_25 = [v for v in ladder_25 if v is not None]
    zero_movers = sum(1 for m in usable if (m.get("books_moved") or 0) == 0)
    one_mover = sum(1 for m in usable if (m.get("books_moved") or 0) == 1)
    return {
        "n": len(usable),
        "first_move_minutes_min": (round(min(first_moves), 2)
                                   if first_moves else None),
        "events_with_first_move_le_15min": sum(1 for v in first_moves
                                               if v <= 15.0),
        "pct25_rung_min_minutes": (round(min(ladder_25), 2)
                                   if ladder_25 else None),
        "events_with_zero_movers": zero_movers,
        "events_with_one_mover": one_mover,
    }


# ---------------------------------------------------------------------------
# Split-half replication (docs/RESEARCH_V3_TIMING.md lines 112-116)
# ---------------------------------------------------------------------------

def _replication(rows) -> dict:
    """First half must hold direction, second half must hold direction and
    at least half the first half's magnitude, both measured on S_hat(0) - 0.5
    -- the boundary statistic the primary test now reports only as a
    supporting note (ADDENDUM 2), kept here because it is well-defined even
    when a half's KM median is "not reached" and the two checks can never
    silently disagree about direction.
    """
    half_floor = CLASS_FLOOR // 2
    middle = len(rows) // 2
    first, second = rows[:middle], rows[middle:]
    if len(first) < half_floor or len(second) < half_floor:
        return {"first_half_n": len(first), "second_half_n": len(second),
                "verdict": "undetermined: one half is under the "
                           f"{half_floor}-event half-floor"}
    first_s0 = km_survival_at(_km_pairs_diff(first), 0.0)
    second_s0 = km_survival_at(_km_pairs_diff(second), 0.0)
    first_mag, second_mag = first_s0 - 0.5, second_s0 - 0.5
    if abs(first_mag) < 1e-9:
        return {"first_half_n": len(first), "second_half_n": len(second),
                "first_half_s0": round(first_s0, 5),
                "second_half_s0": round(second_s0, 5),
                "verdict": "undetermined: first half shows exactly no "
                           "latency signal (S(0) == 0.5)"}
    same_direction = (first_mag > 0) == (second_mag > 0)
    holds_magnitude = abs(second_mag) >= 0.5 * abs(first_mag)
    replicated = same_direction and holds_magnitude
    return {
        "first_half_n": len(first), "second_half_n": len(second),
        "first_half_s0": round(first_s0, 5),
        "second_half_s0": round(second_s0, 5),
        "direction_holds": same_direction,
        "magnitude_holds": holds_magnitude,
        "verdict": "replicated" if replicated else "not replicated",
        "note": ("direction and >= half magnitude of S(0)-0.5 (a supporting "
                 "boundary statistic, not the primary one), first half vs "
                 "second half, docs/RESEARCH_V3_TIMING.md lines 112-116"),
    }


# ---------------------------------------------------------------------------
# One reading (a class's relevant subset, or its unfiltered/exploratory set)
# ---------------------------------------------------------------------------

def _run(name, usable, *, reading) -> dict:
    rows, excluded_before_test = _rows_for_class(usable)
    n_measurable = len(usable)
    n_used = len(rows)

    if n_used < CLASS_FLOOR:
        return {"class": name, "reading": reading,
                "status": "below floor after join exclusions",
                "measurable_events": n_measurable, "used_for_test": n_used,
                "floor": CLASS_FLOOR,
                "excluded_before_test": excluded_before_test,
                "note": "measurable count cleared the floor but too many "
                        "events lacked a usable game start or bracket; no "
                        "result read"}

    n_censored = sum(1 for r in rows if r["censored"])
    n_observed = n_used - n_censored

    reactions_cc = [r["reaction_minutes"] for r in rows if not r["censored"]]
    diffs_cc = [r["diff_minutes"] for r in rows if not r["censored"]]
    diff_pairs = _km_pairs_diff(rows)
    reaction_pairs = _km_pairs_reaction(rows)

    km_diff_point = km_median(diff_pairs)
    km_reaction_point = km_median(reaction_pairs)

    median_boot = _median_bootstrap(rows)
    median_ci = _percentile_ci_with_inf(median_boot["draws"])

    sign_test = cluster_sign_test(rows)

    s0 = km_survival_at(diff_pairs, 0.0)
    s0_boot = _bootstrap(rows, lambda sample: km_survival_at(
        _km_pairs_diff(sample), 0.0))
    s0_draws = s0_boot["draws"]
    s0_degenerate = (not s0_draws) or (max(s0_draws) - min(s0_draws) < 1e-9)
    supporting_s0 = {
        "point_estimate": round(s0, 5),
        "bootstrap_clusters": s0_boot["clusters"],
        "bootstrap_resamples_used": len(s0_draws),
        "degenerate": s0_degenerate,
        "note": ("S(0) is a supporting boundary statistic -- median(diff) > "
                 "0 iff S(0) > 0.5 -- demoted from primary per "
                 "docs/RESEARCH_V3_TIMING.md ADDENDUM 2. When degenerate "
                 "(every bootstrap resample lands on the same value, "
                 "typically because every observed diff sits comfortably "
                 "on one side of the floor), no interval or p-value is "
                 "reported here; see km_median_diff_minutes and sign_test "
                 "for the primary read."),
    }
    if not s0_degenerate:
        supporting_s0["bootstrap_ci95"] = _percentile_ci(s0_draws)
        supporting_s0["bootstrap_p_one_sided"] = round(
            sum(1 for d in s0_draws if d <= 0.5) / len(s0_draws), 6)

    concentration = _concentration(rows)
    replication = _replication(rows)
    response_table = leadlag.response_table(usable)
    leadership = leadlag.leadership_stability(usable)

    return {
        "class": name,
        "reading": reading,
        "status": "tested",
        "floor": CLASS_FLOOR,
        "measurable_events": n_measurable,
        "used_for_test": n_used,
        "excluded_before_test": excluded_before_test,
        "observed": n_observed,
        "censored": n_censored,
        "censored_fraction": round(n_censored / n_used, 4),
        "descriptive": {
            "median_floor_minutes": _median([r["floor_minutes"] for r in rows]),
            "min_floor_minutes": min(r["floor_minutes"] for r in rows),
            "max_floor_minutes": max(r["floor_minutes"] for r in rows),
            "complete_case_median_reaction_minutes": (
                round(_median(reactions_cc), 2) if reactions_cc else None),
            "complete_case_median_diff_minutes": (
                round(_median(diffs_cc), 2) if diffs_cc else None),
            "km_median_reaction_minutes": km_reaction_point,
            "bias_note": ("complete-case medians drop every censored "
                          "(never-reacted-before-first-pitch) event and are "
                          "biased DOWNWARD -- toward LESS measured latency, "
                          "the conservative direction for this hypothesis; "
                          "the KM figures fold censoring back in and read "
                          "'not reached' (None) when more than half the "
                          "censoring-adjusted mass survives past the "
                          "longest follow-up in this sample"),
            **_descriptive_extra(usable),
        },
        "test": {
            "hypothesis": ("H1: median(minutes-to-50%-books-reacted minus "
                          "that event's own capture-spacing floor) > 0 -- "
                          "docs/RESEARCH_V3_TIMING.md lines 102-105 "
                          "(primary hypothesis) and 163-166 (the floor is "
                          "per-event, read as the literal recorded bracket "
                          "width, ADDENDUM 2)"),
            "primary_statistic": "km_median_diff_minutes",
            "km_median_diff_minutes": ("not reached" if km_diff_point is None
                                       else km_diff_point),
            "km_median_diff_bootstrap_ci95": median_ci,
            "km_median_diff_bootstrap": {
                "clusters": median_boot["clusters"],
                "resamples_requested": BOOTSTRAP_RESAMPLES,
                "resamples_used": len(median_boot["draws"]),
                "resamples_not_reached": median_boot["not_reached"],
                "seed": BOOTSTRAP_SEED,
                "cluster_unit": "game_pk (the event's own mapped game)",
                "note": ("a 'not reached' resample is coded as +infinity, "
                         "never dropped -- it is evidence the true median "
                         "is at least that resample's longest follow-up"),
            },
            "sign_test": sign_test,
            "supporting_s0": supporting_s0,
            "promotion": ("not decided here -- docs/RESEARCH_V3_TIMING.md "
                         f"requires BH-FDR at q={FDR_Q} across the full "
                         f"{FAMILY_ADMITTED_CLASSES}-class family before "
                         "any class is promoted; only one class has "
                         "reached its floor so far, and no promotion "
                         "decision is made by this module"),
        },
        "concentration": concentration,
        "replication": replication,
        "response_table": response_table,
        "leadership_stability": leadership,
    }


# ---------------------------------------------------------------------------
# One class (relevance-aware for transaction_first_seen; unchanged shape for
# every other class)
# ---------------------------------------------------------------------------

def _relevance_summary(usable, relevant) -> dict:
    def _counts(events):
        counts = {}
        for m in events:
            _count(counts, m.get("category"))
        return counts
    return {
        "rule": ("game_relevant() -- RESEARCH_V3_TIMING.md ADDENDUM 2: the "
                "frozen il_roster_move definition (line 43) is IL "
                "placement/activation, trade, or recall affecting the "
                "game, not every transaction id first seen"),
        "relevant_categories": sorted(GAME_RELEVANT_TRANSACTION_CATEGORIES),
        "non_relevant_categories": sorted(NON_RELEVANT_TRANSACTION_CATEGORIES),
        "n_all_transactions": len(usable),
        "n_relevant": len(relevant),
        "category_counts_all_transactions": _counts(usable),
        "category_counts_relevant_subset": _counts(relevant),
    }


def test_class(name, *, report_result=None, **report_kwargs) -> dict:
    """Run the V3 primary test for one class, refusing anything below the
    floor. `report_result` lets a caller (the CLI, or a test) pass an
    already-computed timingreport.report() output instead of recomputing
    the whole join; `report_kwargs` are forwarded to timingreport.report()
    when it must be computed here.

    For a class with a relevance rule (today: only `transaction_first_seen`,
    the only class whose events carry a "category" field at all), this
    returns BOTH readings: `primary_relevant_subset` (the frozen class
    definition, gated by `game_relevant`) and
    `secondary_all_transactions_exploratory` (every transaction id first
    seen, disclosed but never promoted -- ADDENDUM 2's required fix for the
    class mismatch). Every other class returns the single `_run()` result
    directly, exactly as before.
    """
    result = (report_result if report_result is not None
              else timingreport.report(**report_kwargs))
    classes = result.get("classes") or {}
    if name not in classes:
        return {"class": name, "status": "unknown class: no events of this "
                                        "class have been observed"}
    entry = classes[name]
    if entry["measurable"] < CLASS_FLOOR:
        return {"class": name, "status": "below floor",
                "measurable_events": entry["measurable"], "floor": CLASS_FLOOR,
                "note": "the reading rule: no class-level result before the "
                        "floor; nothing below this line was read"}
    measured = entry.get("measured") or []
    usable = [m for m in measured if m and m.get("excluded") is None]
    has_relevance_rule = any("category" in m for m in usable)
    if not has_relevance_rule:
        return _run(name, usable, reading="primary")

    relevant = [m for m in usable if game_relevant(m)]
    primary = (_run(name, relevant, reading="primary_relevant_subset")
              if len(relevant) >= CLASS_FLOOR else
              {"class": name, "reading": "primary_relevant_subset",
               "status": "below floor after relevance filter",
               "n_relevant": len(relevant), "floor": CLASS_FLOOR,
               "note": ("the all-transactions count cleared the class "
                        "floor, but the game-relevant subset does not; no "
                        "primary result is read. See "
                        "secondary_all_transactions_exploratory for the "
                        "descriptive, non-promoted reading of everything "
                        "captured.")})
    secondary = _run(name, usable, reading="secondary_all_transactions_exploratory")
    return {
        "class": name,
        "status": primary.get("status", "tested"),
        "relevance": _relevance_summary(usable, relevant),
        "primary_relevant_subset": primary,
        "secondary_all_transactions_exploratory": secondary,
    }


def test_all(*, report_result=None, **report_kwargs) -> dict:
    """test_class for every class the report has seen; below-floor classes
    come back as the same refusal test_class would give, never touched."""
    result = (report_result if report_result is not None
              else timingreport.report(**report_kwargs))
    return {name: test_class(name, report_result=result)
            for name in sorted((result.get("classes") or {}))}


# ---------------------------------------------------------------------------
# Family-wide correction (for later use -- see module docstring)
# ---------------------------------------------------------------------------

def bh_fdr(pvalues_by_class, q=FDR_Q) -> dict:
    """Benjamini-Hochberg across the full pre-registered family.

    docs/RESEARCH_V3_TIMING.md lines 100-109: BH-FDR at q=0.10 across
    admitted classes, early deaths (a class that never reaches its floor) at
    p=1.0, denominator = the admitted class count IN FORCE AT THE READ (see
    module docstring's "THE FDR DENOMINATOR", and FAMILY_ADMITTED_CLASSES
    above -- monotone non-decreasing, never edited down). This function does
    not know or enforce that denominator -- it corrects whatever family
    `pvalues_by_class` hands it, so a caller MUST supply an entry (p=1.0 for
    a class that has died early, or any of the doc's other conventions) for
    every admitted class before the result means what the pre-registration
    says it means. Calling this with fewer entries than the admitted family
    is answering a different, uncorrected question.
    """
    items = sorted(pvalues_by_class.items(), key=lambda kv: kv[1])
    m = len(items)
    if m == 0:
        return {"q": q, "m": 0, "significant": [], "ranked": []}
    largest_i = 0
    for i, (_, p) in enumerate(items, start=1):
        if p <= (i / m) * q:
            largest_i = i
    ranked = [{"class": name, "p": p, "rank": i,
              "bh_critical": round((i / m) * q, 6)}
             for i, (name, p) in enumerate(items, start=1)]
    significant = sorted(name for name, _ in items[:largest_i])
    return {"q": q, "m": m, "significant": significant, "ranked": ranked}
