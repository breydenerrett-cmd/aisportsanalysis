"""Eligibility boundary for F5_RAW_HISTORY -> the research universe.

WHY THIS FILE EXISTS, AND WHY IT IS NOT A REWRITE OF THE RAW STORE
--------------------------------------------------------------------
A sanity tranche (docs/PREREG_F5_SNAPSHOT_RULE.md) bought 21 games under the
T-2h rule while `src/pipeline/f5_tminus2.py` acquisition was live. 8 of them
landed outside the approved 2023-05-10..2024-10-07 discovery window: six in
2025 (2025-04-28, 2025-05-09, 2025-05-16, 2025-08-13, 2025-08-19,
2025-09-22) and two pre-window in 2023 (2023-03-30, 2023-05-06). All eight
are real, paid, valid observations. The owner's standing rule is that 2025
is TUNING-ONLY FOREVER and 2026 is SEALED -- neither may ever seed
discovery, replication, the primary F5 denominator, threshold selection, or
ranking/promotion. But "do not delete paid valid historical observations
merely to enforce a boundary that belongs in the eligibility layer" --
deletion is forbidden, so the boundary lives here, as a read-time predicate
over the observation's own `date` field, not as a mutation of any row.

This also matters mechanically: `src/pipeline/f5_tminus2.py`'s acquisition
`run()` is a live paid writer appending to
`data/historical/odds_first_five/mlb_*.jsonl` while this eligibility layer
is being built. Rewriting rows in place to stamp a `TUNING_ONLY` flag onto
disk would mean racing that writer for the same files -- reading a
half-written line, or overwriting a row the acquisition just appended after
this process last read the file. A rule keyed on `date` needs no such race:
it is computed the same way whether the row was written a year ago or one
second ago, and it never opens a raw-history file for anything but reading
(`annotate` and `read_raw_history_with_eligibility` below only ever read).
`TUNING_ONLY` is therefore a *derived*, additive field -- present on every
value this module hands back, never written into the JSONL itself.

WHERE THE BOUNDARY IS ENFORCED
-------------------------------
`is_eligible` / `eligibility` are the single predicate. They are consumed by
`src.pipeline.f5_tminus2.build_primary_view` -- the only function that
assembles `F5_TMINUS2_PRIMARY`, itself documented (PREREG_F5_SNAPSHOT_RULE.md
section 5) as "the only store the primary F5-moneyline research universe
reads from." An ineligible row is filtered out there, before it is ever
turned into a primary-view record, so it cannot reach discovery, replication,
the primary denominator, threshold selection, or ranking/promotion through
that path -- by construction, not by a convention a future caller could
forget. There is currently no second path that reads F5_RAW_HISTORY into a
research universe (grepped: only `build_primary_view`, the acquisition path
itself, and tests touch the raw season files); if one is ever added, it must
call through this predicate too, exactly as `build_primary_view` does.
"""

from __future__ import annotations

# The approved discovery/replication window, frozen in
# docs/PREREG_F5_SNAPSHOT_RULE.md ("the existing 4,034 rows ... in the
# 2023-05-10..2024-10-07 window plus the pre-window rows already held").
# Inclusive on both ends -- an observation dated exactly on either boundary
# is in-window.
APPROVED_WINDOW_START = "2023-05-10"
APPROVED_WINDOW_END = "2024-10-07"

# Owner standing rule (2026-09-04): 2025 is tuning-only forever, regardless
# of how much of it eventually falls inside some future approved window --
# this is a project-wide rule about the calendar year itself, not just the
# current window's endpoints. 2026 is sealed outright (out-of-sample,
# untouched until the project says otherwise).
TUNING_ONLY_YEARS = frozenset({"2025"})
SEALED_YEARS = frozenset({"2026"})


def eligibility(date_str) -> dict:
    """Classify one observation's `date` (YYYY-MM-DD, as stored on every
    F5_RAW_HISTORY row) for entry into the eligible research universe.

    Returns {"eligible": bool, "TUNING_ONLY": bool, "reason": str | None}.
    `reason` is None exactly when `eligible` is True. `TUNING_ONLY` is a
    distinct axis from `eligible` -- a tuning-only row is never eligible,
    but the flag survives independently so a caller can positively confirm
    *why* an ineligible row is what it is (matching the owner's request for
    a literal `TUNING_ONLY: true` marker) rather than inferring it from a
    generic exclusion.
    """
    if not date_str:
        return {"eligible": False, "TUNING_ONLY": False, "reason": "date_missing"}

    year = str(date_str)[:4]

    if year in TUNING_ONLY_YEARS:
        return {"eligible": False, "TUNING_ONLY": True, "reason": "tuning_only_2025"}

    if year in SEALED_YEARS:
        return {"eligible": False, "TUNING_ONLY": False, "reason": "sealed_2026"}

    if not (APPROVED_WINDOW_START <= str(date_str) <= APPROVED_WINDOW_END):
        # ISO YYYY-MM-DD strings compare lexicographically the same as
        # chronologically, so this catches both the pre-window 2023 rows
        # (2023-03-30, 2023-05-06) and any future out-of-window date that
        # is not already caught by a year-level rule above.
        return {"eligible": False, "TUNING_ONLY": False, "reason": "outside_approved_window"}

    return {"eligible": True, "TUNING_ONLY": False, "reason": None}


def is_eligible(date_str) -> bool:
    """Convenience boolean wrapper around `eligibility` for filter callsites."""
    return eligibility(date_str)["eligible"]


def annotate(row: dict) -> dict:
    """Return a NEW dict: `row` plus the derived eligibility fields.

    Additive only -- every existing key and value from `row` is passed
    through untouched; nothing here can rewrite or drop a field the
    acquisition wrote. `row` itself is never mutated (callers holding onto
    the original still see it exactly as read).
    """
    verdict = eligibility(row.get("date"))
    out = dict(row)
    out["TUNING_ONLY"] = verdict["TUNING_ONLY"]
    out["eligible_for_research"] = verdict["eligible"]
    out["ineligibility_reason"] = verdict["reason"]
    return out


def read_raw_history_with_eligibility(seasons, store) -> list:
    """Read F5_RAW_HISTORY season files (unchanged, read-only) and return
    every row annotated per `annotate` -- i.e. every 2025/2026/pre-window
    row explicitly carries `TUNING_ONLY`/`eligible_for_research` without a
    single byte of the underlying JSONL ever being touched.

    Local import of `src.pipeline.f5_tminus2` to avoid a module-load-time
    circular import (that module reaches back into this one, lazily, from
    inside `build_primary_view`).
    """
    from src.pipeline import f5_tminus2

    out = []
    for season in seasons:
        for row in f5_tminus2.read_raw_season(season, store):
            out.append(annotate(row))
    return out
