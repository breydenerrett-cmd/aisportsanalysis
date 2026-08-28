"""Which detector inputs can honestly be reconstructed as of a past date.

WHY THIS IS A MODULE AND NOT A CONVENTION
-----------------------------------------
A season-to-date statistic applied to a game earlier in that season tells you
how the player went on to perform. It is the single most effective way to build
a backtest that looks brilliant and loses money, and it is invisible: the
numbers are real, the code is correct, and the result is a lie.

Conventions do not survive a long autonomous run. So the audit is data: each
input declares whether it is reconstructible at a past date and why, the
detectors inherit the worst status of their inputs, and the discovery harness
refuses to evaluate a detector that is not clean rather than quietly producing
a flattering number.

THE FINDING THAT FORCED THIS
----------------------------
The MLB splits endpoint accepts startDate and endDate and SILENTLY IGNORES THEM.
Verified directly: requesting April only, April-through-August, and August only
for the same pitcher returns byte-identical numbers -- 113 batters faced versus
left-handers at a .756 OPS in all three. There is no parameter that makes it
answer "as of" anything.

That is not a limitation to work around with care. It means platoon splits and
pitch arsenals, as currently sourced, cannot be used in any historical
evaluation at all. Pitch-level data would rebuild both correctly and is the
named unblocking task; until then those detectors are historically unevaluable
and are reported as such rather than excluded quietly.
"""

from __future__ import annotations

# An input either accumulates forward from per-event records, in which case a
# cutoff is a filter, or it is a snapshot of a whole season, in which case no
# cutoff exists.
CLEAN = "clean"          # reconstructible as of any past date
LEAKY = "leaky"          # season-to-date; cannot be made point-in-time
UNKNOWN = "unknown"      # not yet audited

STATUS_ORDER = (CLEAN, UNKNOWN, LEAKY)


INPUTS = {
    "team_features": {
        "status": CLEAN,
        "why": ("accumulated from the results store by games_before, which "
                "filters strictly before the cutoff and is season-scoped"),
    },
    "starters": {
        "status": CLEAN,
        "why": ("built from per-appearance pitcher game logs; a cutoff is a "
                "filter on appearances, not a re-request"),
    },
    "bullpen": {
        "status": CLEAN,
        "why": ("built from per-game boxscore appearances; workload as of a "
                "date is a window over rows that already exist"),
    },
    "travel": {
        "status": CLEAN,
        "why": ("derived from the schedule and stored park coordinates; only "
                "games strictly before the cutoff are read"),
    },
    "park": {
        "status": CLEAN,
        "why": "static reference data",
    },
    "weather": {
        "status": CLEAN,
        "why": ("Open-Meteo serves an archive by date, so a past reading is the "
                "reading, not a projection backwards"),
    },
    "market": {
        "status": CLEAN,
        "why": ("historical odds are snapshots at a named instant, and the "
                "closing match refuses any snapshot at or after first pitch"),
    },
    "lineups": {
        "status": CLEAN,
        "why": ("the schedule feed returns the lineup that was actually posted "
                "for that game"),
    },
    "splits": {
        "status": LEAKY,
        "why": ("the MLB statSplits endpoint IGNORES startDate and endDate -- "
                "verified by requesting three different ranges for one pitcher "
                "and receiving byte-identical numbers. It always returns the "
                "whole season to date, so applying it to an earlier game leaks "
                "results that had not happened yet"),
        "unblocked_by": ("pitch-level Statcast, which carries batter handedness "
                         "per pitch and can be accumulated forward"),
    },
    "arsenals": {
        "status": LEAKY,
        "why": ("Savant's arsenal leaderboards are season-to-date aggregates "
                "with no as-of parameter, so pitch usage and wOBA-against for a "
                "game in June include pitches thrown in August"),
        "unblocked_by": ("pitch-level Statcast, which carries pitch type per "
                         "pitch and can be accumulated forward"),
    },
    "matchup_history": {
        "status": LEAKY,
        "why": ("the vsPlayer endpoint returns career totals to today with no "
                "as-of parameter, so a matchup line for a 2023 game includes "
                "plate appearances from 2024 and 2025"),
        "unblocked_by": ("pitch-level Statcast, or accumulating per-game "
                         "matchup rows forward from boxscores"),
    },
}


# Which dossier sections each detector actually reads. Declared rather than
# inferred: a detector that quietly starts reading a leaky section must show up
# as a change here, in a diff, rather than as a slightly better number.
DETECTOR_INPUTS = {
    "starter_mismatch": ("starters",),
    "bullpen_exposure": ("starters",),
    "bullpen_workload": ("bullpen",),
    "implied_bullpen_disagreement": ("market", "bullpen"),
    "stale_book": ("market",),
    "travel_load": ("travel",),
    "park_and_weather": ("park", "weather"),
    "platoon_mismatch": ("lineups", "splits"),
    "pitch_mix_mismatch": ("lineups", "arsenals"),
    "thin_matchup_history": ("matchup_history",),
    "lineup_vs_starter": ("matchup_history",),
}


class PointInTimeError(RuntimeError):
    """Raised when a leaky detector is used for a historical evaluation."""


def input_status(name) -> dict:
    return INPUTS.get(name, {"status": UNKNOWN,
                             "why": f"input {name!r} has not been audited"})


def detector_status(name) -> dict:
    """A detector is only as clean as its dirtiest input."""
    inputs = DETECTOR_INPUTS.get(name)
    if inputs is None:
        return {"detector": name, "status": UNKNOWN, "inputs": [],
                "why": f"detector {name!r} has not declared its inputs"}

    worst, reasons = CLEAN, []
    for input_name in inputs:
        entry = input_status(input_name)
        if STATUS_ORDER.index(entry["status"]) > STATUS_ORDER.index(worst):
            worst = entry["status"]
        if entry["status"] != CLEAN:
            reasons.append(f"{input_name}: {entry['why']}")
    return {
        "detector": name,
        "status": worst,
        "inputs": list(inputs),
        "why": "; ".join(reasons) or "every input accumulates forward",
        "unblocked_by": sorted({
            input_status(i).get("unblocked_by") for i in inputs
            if input_status(i).get("unblocked_by")}),
    }


def audit(detector_names) -> dict:
    """Split a family into what can and cannot be evaluated historically."""
    rows = [detector_status(name) for name in sorted(detector_names)]
    return {
        "clean": [r for r in rows if r["status"] == CLEAN],
        "leaky": [r for r in rows if r["status"] == LEAKY],
        "unknown": [r for r in rows if r["status"] == UNKNOWN],
        "all": rows,
    }


def require_clean(name) -> dict:
    """Refuse a historical evaluation of a detector that is not point-in-time.

    Raises rather than warning. A warning in a batch job is a line nobody reads,
    and the number it accompanies is the one that gets quoted.
    """
    entry = detector_status(name)
    if entry["status"] != CLEAN:
        unblock = ("; unblocked by " + ", ".join(entry["unblocked_by"])
                   if entry.get("unblocked_by") else "")
        raise PointInTimeError(
            f"{name} cannot be evaluated historically -- {entry['why']}{unblock}")
    return entry
