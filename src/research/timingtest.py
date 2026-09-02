"""The V3 primary test: is reaction to an event slower than our own resolution?

WHAT IS BEING TESTED
---------------------
docs/RESEARCH_V3_TIMING.md lines 102-105 (frozen): each admitted class
contributes ONE primary hypothesis -- "median time to 50%-of-books reaction
exceeds the capture-spacing floor (i.e., latency is measurable at our
resolution, not instantaneous)". Lines 163-166 make the floor itself
per-event, not a single class-wide constant: "the reaction ladder's
resolution floor is therefore the poll spacing in force at each event, and
the primary hypothesis is stated against exactly that floor" -- 15 minutes
inside the dense capture window that opens `dense.WINDOW_MINUTES` before
first pitch, 60 minutes (the hourly baseline loop) otherwise.

Because the floor varies event by event, this module tests the PAIRED
per-event formulation the doc's own wording already commits to: for each
event, diff = (minutes to 50%-of-books reaction) - (that event's own
capture-spacing floor); H1 is median(diff) > 0. A pooled "median(all
reactions) vs median(all floors)" would average away exactly the
distinction line 163-166 draws, so the paired form is the more faithful
reading, not a substitution for it.

median(diff) > 0 is exactly equivalent to S(0) > 0.5, where S is the
survival function of diff (S(t) = P(true diff > t)): a step function is
non-increasing, so its first crossing below 0.5 is at a positive time iff
its value at 0 is still above 0.5. This module therefore tests and
bootstraps S_hat(0) directly rather than the median itself -- S_hat(0) is
always a defined number in [0, 1], where the KM median can come back
"not reached" whenever more than half a resample's censored mass survives
past the last observed time. Every number this module reports is
descriptive of CAPTURED prices; nothing here is a bet recommendation or an
"edge" (docs/RESEARCH_V3_TIMING.md, "What V3 cannot do").

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
argument to see the numbers early.
"""

from __future__ import annotations

import datetime as dt
import random

from src.pipeline import dense
from src.research import leadlag, timingreport

# Same floor leadlag.response_table already enforces on the identical
# "measurable" (excluded is None) count. Restated as its own name here
# because this module's gate is independent of leadlag's -- if leadlag's
# floor ever changed without this module changing too, silently reading
# early is exactly the failure mode the doc warns against.
CLASS_FLOOR = leadlag.MIN_EVENTS

# The capture-spacing floor in force at one event (docs/RESEARCH_V3_TIMING.md
# lines 163-166): 15-minute brackets inside the dense window that opens
# `dense.WINDOW_MINUTES` before first pitch (src/pipeline/dense.py), 60
# minutes -- the hourly baseline loop (docs/OVERNIGHT_RUN.md line 12: "hourly
# via the renamed Forward ...") -- otherwise.
DENSE_WINDOW_MINUTES = dense.WINDOW_MINUTES
DENSE_FLOOR_MINUTES = float(dense.INTERVAL_MINUTES)
HOURLY_FLOOR_MINUTES = 60.0

# Bootstrap: resamples CLUSTERS (one game/day per event, per the task's
# "cluster by game/day"), with replacement. Same resample count and the same
# "sort cluster keys for reproducibility" discipline as
# src/model/discovery.clustered_bootstrap, whose docstring explains why an
# unsorted cluster order makes the same data produce a different interval.
# Written locally, not delegated to that function, because the statistic
# bootstrapped here (a Kaplan-Meier quantity) can come back `None` on a
# resample -- discovery.clustered_bootstrap silently drops `None` draws and
# never reports how often that happened, which this module needs to report.
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20260901

# The pre-registered family (docs/RESEARCH_V3_TIMING.md, freeze record:
# "Admitted classes (the family, denominator 4)"). Stated here so every
# result this module emits carries the correction context it will eventually
# be judged against, without pretending that correction has already been
# applied -- BH-FDR needs a p-value (or the frozen early-death p=1.0) for
# EVERY admitted class, and only one class has reached its floor so far.
ADMITTED_CLASSES_AT_FREEZE = 4
FDR_Q = 0.10

UNPARSEABLE_TIMES = "event time or game start unparseable"
NO_GAME_START = "game start time missing; floor and censoring time cannot be computed"
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


# ---------------------------------------------------------------------------
# Per-event rows: floor, reaction, censoring
# ---------------------------------------------------------------------------

def _rows_for_class(usable_measured) -> tuple:
    """One row per usable (excluded is None) measured event, plus an
    exclusion count for anything this stage itself cannot place honestly.

    `usable_measured` must already be filtered to excluded is None (leadlag's
    own convention, restated by the caller) and must carry the game_pk /
    game_start_utc fields timingreport.report() now attaches to every
    measured event.
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
        floor_minutes = (DENSE_FLOOR_MINUTES
                         if minutes_to_start <= DENSE_WINDOW_MINUTES
                         else HOURLY_FLOOR_MINUTES)
        reaction_minutes = (m.get("ladder_minutes") or {}).get("50%")
        cluster = str(m.get("game_pk") or "unknown")
        row = {"cluster": cluster, "event_time": event_time,
               "floor_minutes": floor_minutes}
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
# Clustered bootstrap
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
# Split-half replication (docs/RESEARCH_V3_TIMING.md lines 112-116)
# ---------------------------------------------------------------------------

def _replication(rows) -> dict:
    """First half must hold direction, second half must hold direction and
    at least half the first half's magnitude, both measured on S_hat(0) - 0.5
    (the same statistic the primary test bootstraps) so replication and the
    primary result can never silently disagree about what "the effect" is.
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
        "note": ("direction and >= half magnitude of S(0)-0.5, first half "
                 "vs second half, docs/RESEARCH_V3_TIMING.md lines 112-116"),
    }


# ---------------------------------------------------------------------------
# One class
# ---------------------------------------------------------------------------

def _run(name, measured) -> dict:
    usable = [m for m in measured if m and m.get("excluded") is None]
    rows, excluded_before_test = _rows_for_class(usable)
    n_measurable = len(usable)
    n_used = len(rows)

    if n_used < CLASS_FLOOR:
        return {"class": name, "status": "below floor after join exclusions",
                "measurable_events": n_measurable, "used_for_test": n_used,
                "floor": CLASS_FLOOR,
                "excluded_before_test": excluded_before_test,
                "note": "measurable count cleared the floor but too many "
                        "events lacked a usable game start; no result read"}

    n_censored = sum(1 for r in rows if r["censored"])
    n_observed = n_used - n_censored
    floor_counts = {"15min_dense": sum(1 for r in rows
                                       if r["floor_minutes"] == DENSE_FLOOR_MINUTES),
                    "60min_hourly": sum(1 for r in rows
                                        if r["floor_minutes"] == HOURLY_FLOOR_MINUTES)}

    reactions_cc = [r["reaction_minutes"] for r in rows if not r["censored"]]
    diffs_cc = [r["diff_minutes"] for r in rows if not r["censored"]]
    diff_pairs = _km_pairs_diff(rows)
    reaction_pairs = _km_pairs_reaction(rows)

    s0 = km_survival_at(diff_pairs, 0.0)
    boot = _bootstrap(rows, lambda sample: km_survival_at(
        _km_pairs_diff(sample), 0.0))
    draws = boot["draws"]
    ci = _percentile_ci(draws)
    p_one_sided = (round(sum(1 for d in draws if d <= 0.5) / len(draws), 6)
                  if draws else None)

    replication = _replication(rows)

    return {
        "class": name,
        "status": "tested",
        "floor": CLASS_FLOOR,
        "measurable_events": n_measurable,
        "used_for_test": n_used,
        "excluded_before_test": excluded_before_test,
        "observed": n_observed,
        "censored": n_censored,
        "censored_fraction": round(n_censored / n_used, 4),
        "floor_regime_counts": floor_counts,
        "descriptive": {
            "median_floor_minutes": _median([r["floor_minutes"] for r in rows]),
            "complete_case_median_reaction_minutes": (
                round(_median(reactions_cc), 2) if reactions_cc else None),
            "complete_case_median_diff_minutes": (
                round(_median(diffs_cc), 2) if diffs_cc else None),
            "km_median_reaction_minutes": km_median(reaction_pairs),
            "km_median_diff_minutes": km_median(diff_pairs),
            "bias_note": ("complete-case medians drop every censored "
                          "(never-reacted-before-first-pitch) event and are "
                          "biased DOWNWARD -- toward LESS measured latency, "
                          "the conservative direction for this hypothesis; "
                          "the KM figures fold censoring back in and read "
                          "'not reached' (None) when more than half the "
                          "censoring-adjusted mass survives past the "
                          "longest follow-up in this sample"),
        },
        "test": {
            "hypothesis": ("H1: median(minutes-to-50%-books-reacted minus "
                          "that event's own capture-spacing floor) > 0, "
                          "equivalently S(0) > 0.5 for that per-event "
                          "difference -- docs/RESEARCH_V3_TIMING.md lines "
                          "102-105 (primary hypothesis) and 163-166 (the "
                          "floor is per-event)"),
            "point_estimate_s0": round(s0, 5),
            "ci95_s0": ci,
            "p_one_sided": p_one_sided,
            "bootstrap": {"clusters": boot["clusters"],
                         "resamples_requested": BOOTSTRAP_RESAMPLES,
                         "resamples_used": len(draws),
                         "resamples_undefined": boot["undefined"],
                         "seed": BOOTSTRAP_SEED,
                         "cluster_unit": "game_pk (the event's own mapped game)"},
            "promotion": ("not decided here -- docs/RESEARCH_V3_TIMING.md "
                         f"requires BH-FDR at q={FDR_Q} across the full "
                         f"{ADMITTED_CLASSES_AT_FREEZE}-class family before "
                         "any class is promoted; only this one class has "
                         "reached its floor so far"),
        },
        "replication": replication,
    }


def test_class(name, *, report_result=None, **report_kwargs) -> dict:
    """Run the V3 primary test for one class, refusing anything below the
    floor. `report_result` lets a caller (the CLI, or a test) pass an
    already-computed timingreport.report() output instead of recomputing
    the whole join; `report_kwargs` are forwarded to timingreport.report()
    when it must be computed here.
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
    return _run(name, entry.get("measured") or [])


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
    p=1.0, denominator = the admitted class count recorded at freeze. This
    function does not know or enforce that denominator -- it corrects
    whatever family `pvalues_by_class` hands it, so a caller MUST supply an
    entry (p=1.0 for a class that has died early, or any of the doc's other
    conventions) for every admitted class before the result means what the
    pre-registration says it means. Calling this with fewer entries than the
    admitted family is answering a different, uncorrected question.
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
