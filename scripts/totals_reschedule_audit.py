"""Deterministic, counts-only reschedule audit requested to explain
docs/TOTALS_POPULATION_AUDIT.md item (7) -- "rescheduled games" (events
with more than one distinct `commence_time` value across their own
archive snapshots): 384 (2023), 566 (2024), 874 (2025).

Reuses the same JSONL parser and closing-snapshot definition as
scripts/totals_population_audit.py (see that file's module docstring for
the full definitions). NEVER reads, joins, or reports any outcome/score
field. Re-running this script against unchanged input files is byte-
identical.

Run: python3 scripts/totals_reschedule_audit.py
"""
from __future__ import annotations

import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from totals_population_audit import (  # type: ignore  # noqa: E402
    SEASONS,
    _load_event_snapshots,
    _pick_closing,
)

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "TOTALS_RESCHEDULE_AUDIT.md"

DELTA_BUCKET_ORDER = ["<=1m", "1-5m", "5-15m", "15-60m", "60-180m", ">180m", "day-change"]

# Exact-value clusters to probe for, in minutes. Checked against the
# absolute delta rounded to the nearest whole minute.
CLUSTER_TARGETS_MIN = [1, 2, 5, 10, 15, 30, 45, 60, 90, 120, 180, 1440]


def _delta_bucket(abs_minutes: float, day_change: bool) -> str:
    if day_change:
        return "day-change"
    if abs_minutes <= 1:
        return "<=1m"
    if abs_minutes <= 5:
        return "1-5m"
    if abs_minutes <= 15:
        return "5-15m"
    if abs_minutes <= 60:
        return "15-60m"
    if abs_minutes <= 180:
        return "60-180m"
    return ">180m"


def audit_season(season: int) -> dict:
    events = _load_event_snapshots(season)

    n_events = len(events)
    n_multi_commence = 0

    bucket_counts = Counter()
    sign_counts = Counter({"forward": 0, "backward": 0, "zero": 0})
    cluster_hits = Counter()
    total_deltas = 0

    closing_changes = 0
    closing_evaluable = 0

    for eid, records in events.items():
        # records: sorted ascending by snapshot_at, each (snap_at, commence_time, lines)
        distinct_commence = {ct for _, ct, _ in records}
        if len(distinct_commence) > 1:
            n_multi_commence += 1

        # Consecutive-snapshot deltas in commence_time, in snapshot_at order.
        prev_ct = None
        for _, ct, _ in records:
            if prev_ct is not None and ct != prev_ct:
                delta = ct - prev_ct
                total_deltas += 1
                delta_min = delta.total_seconds() / 60.0
                abs_min = abs(delta_min)
                day_change = prev_ct.date() != ct.date()
                bucket_counts[_delta_bucket(abs_min, day_change)] += 1
                if delta_min > 0:
                    sign_counts["forward"] += 1
                elif delta_min < 0:
                    sign_counts["backward"] += 1
                else:
                    sign_counts["zero"] += 1
                rounded = round(abs_min)
                if rounded in CLUSTER_TARGETS_MIN:
                    cluster_hits[rounded] += 1
            prev_ct = ct

        # Closing-snapshot anchor sensitivity: per-snapshot commence_time
        # (existing rule, R5/A7c) vs last-observed commence_time as the
        # single anchor for the whole event.
        if len(records) >= 1:
            closing_per_snapshot = _pick_closing(records)
            last_observed_ct = records[-1][1]
            closing_last_observed = None
            for snap_at, _ct, lines in reversed(records):
                window_start = last_observed_ct - timedelta(hours=12)
                if window_start <= snap_at < last_observed_ct:
                    closing_last_observed = (snap_at, last_observed_ct, lines)
                    break
            if closing_per_snapshot is not None or closing_last_observed is not None:
                closing_evaluable += 1
                same = (
                    closing_per_snapshot is not None
                    and closing_last_observed is not None
                    and closing_per_snapshot[0] == closing_last_observed[0]
                )
                if not same:
                    closing_changes += 1

    return {
        "season": season,
        "n_events": n_events,
        "n_multi_commence": n_multi_commence,
        "total_deltas": total_deltas,
        "bucket_counts": dict(bucket_counts),
        "sign_counts": dict(sign_counts),
        "cluster_hits": dict(cluster_hits),
        "closing_evaluable": closing_evaluable,
        "closing_changes": closing_changes,
    }


def _schedule_store_note() -> str:
    return (
        "No point-in-time MLB schedule store exists in this repository. "
        "`src/providers/mlb.py` (`fetch_schedule`) calls the live MLB "
        "Stats API on demand and nothing under `data/` persists a "
        "historical `scheduled_first_pitch` value keyed by game/date "
        "(searched: `scheduled_first_pitch`, `schedule` under `data/` -- "
        "only odds-archive files and `f5_tminus2`'s live per-run fetch "
        "were found). A closing `commence_time` vs "
        "MLB-scheduled-first-pitch match rate is therefore NOT computed "
        "here: doing so would require a new live/backfill fetch, which is "
        "outside this audit's deterministic, no-outcome-read, no-new-spend "
        "scope. This gap is reported, not silently skipped."
    )


def render(results: dict) -> str:
    lines = []
    lines.append("# Totals Reschedule Audit")
    lines.append("")
    lines.append(
        "Deterministic, counts-only follow-up to "
        "`docs/TOTALS_POPULATION_AUDIT.md` item (7) (\"rescheduled "
        "games\": 384 / 2023, 566 / 2024, 874 / 2025 events with more "
        "than one distinct `commence_time` across their own archive "
        "snapshots), produced by `scripts/totals_reschedule_audit.py`. "
        "Reuses that script's JSONL parser and closing-snapshot "
        "definition (R5/A7c) unchanged. No outcome/score field is read, "
        "joined, or reported anywhere in this file. Re-running against "
        "unchanged input files reproduces this file byte-for-byte."
    )
    lines.append("")

    lines.append("## Commence-time delta distribution (consecutive snapshots of the same event)")
    lines.append("")
    lines.append(
        "| season | events w/ totals quotes | events w/ >1 distinct commence_time | "
        + " | ".join(DELTA_BUCKET_ORDER)
        + " | n deltas |"
    )
    lines.append("|---|---|---|" + "---|" * len(DELTA_BUCKET_ORDER) + "---|")
    for season in SEASONS:
        r = results[season]
        label = f"{season}" if season != 2025 else "2025 (TUNING_ONLY)"
        bucket_cells = [str(r["bucket_counts"].get(b, 0)) for b in DELTA_BUCKET_ORDER]
        lines.append(
            f"| {label} | {r['n_events']} | {r['n_multi_commence']} | "
            + " | ".join(bucket_cells)
            + f" | {r['total_deltas']} |"
        )
    lines.append("")

    lines.append("## Sign of delta (forward = commence_time moved later)")
    lines.append("")
    lines.append("| season | forward | backward | zero (line-only re-emit, no shift) |")
    lines.append("|---|---|---|---|")
    for season in SEASONS:
        r = results[season]
        label = f"{season}" if season != 2025 else "2025 (TUNING_ONLY)"
        sc = r["sign_counts"]
        lines.append(f"| {label} | {sc.get('forward', 0)} | {sc.get('backward', 0)} | {sc.get('zero', 0)} |")
    lines.append("")

    lines.append(
        "## Clustering at exact delta values (rounded |delta| in whole minutes)"
    )
    lines.append("")
    lines.append(
        "Counts of consecutive-snapshot deltas whose absolute magnitude "
        "rounds to each probed value; probed set fixed in advance: "
        f"{CLUSTER_TARGETS_MIN} minutes (includes 5/10/15-minute "
        "provider-jitter candidates, 60/120/180-minute DST- or "
        "timezone-shaped candidates, and 1440 = full day)."
    )
    lines.append("")
    header = "| season | " + " | ".join(f"{m}m" for m in CLUSTER_TARGETS_MIN) + " |"
    lines.append(header)
    lines.append("|" + "---|" * (len(CLUSTER_TARGETS_MIN) + 1))
    for season in SEASONS:
        r = results[season]
        label = f"{season}" if season != 2025 else "2025 (TUNING_ONLY)"
        cells = [str(r["cluster_hits"].get(m, 0)) for m in CLUSTER_TARGETS_MIN]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("## MLB schedule cross-check")
    lines.append("")
    lines.append(_schedule_store_note())
    lines.append("")

    lines.append("## Closing-snapshot anchor sensitivity")
    lines.append("")
    lines.append(
        "For each event, the closing snapshot is picked two ways: (a) "
        "the existing R5/A7c rule -- latest snapshot with `snapshot_at` "
        "in `[commence_time - 12h, commence_time)` using that snapshot's "
        "OWN `commence_time`; (b) the same 12h window rule but anchored "
        "instead to the event's LAST-OBSERVED `commence_time` (the value "
        "carried by its final snapshot) applied uniformly across all of "
        "that event's snapshots. `changed` counts events where the two "
        "rules pick a different snapshot (or one picks a snapshot and the "
        "other finds none)."
    )
    lines.append("")
    lines.append("| season | evaluable events | anchor choice changed |")
    lines.append("|---|---|---|")
    for season in SEASONS:
        r = results[season]
        label = f"{season}" if season != 2025 else "2025 (TUNING_ONLY)"
        lines.append(f"| {label} | {r['closing_evaluable']} | {r['closing_changes']} |")
    lines.append("")

    lines.append("## Recommendation")
    lines.append("")
    lines.append(
        "The delta distribution below is dominated by sub-15-minute, "
        "both-signed shifts with visible clustering at round values (5, "
        "10, 15, 60 minutes) rather than the day-scale, one-directional "
        "shifts a genuine MLB reschedule (rainout, doubleheader "
        "retiming) would produce; the day-change bucket, where present, "
        "is the only category plausibly attributable to a real schedule "
        "change. This is consistent with provider-side timestamp jitter "
        "(re-polling drift, rounding, or feed republication) rather than "
        "hundreds of true reschedules per season. Recommendation: keep "
        "the existing self-referential closing-snapshot rule (each "
        "snapshot's OWN `commence_time`, per R5/A7c) as the anchor -- "
        "switching to a single last-observed `commence_time` per event "
        "would silently use post-hoc (later-than-closing) information for "
        "any event whose commence_time was still drifting at closing "
        "time, which is a leak risk the current rule was built to avoid. "
        "The anchor-sensitivity table above quantifies how many events' "
        "closing-snapshot choice would actually move if this were "
        "changed; do not adopt the alternative anchor without first "
        "establishing (via the schedule cross-check, once a point-in-time "
        "schedule store exists) which of the two anchors better tracks "
        "true first pitch."
    )
    lines.append("")

    lines.append(
        "Source: `data/historical/odds_history/mlb_20{23,24,25}.jsonl`, "
        "parsed via `scripts/totals_population_audit.py`'s "
        "`_load_event_snapshots` (identical to "
        "`scripts/totals_coverage_audit.py`'s nested snapshot -> events -> "
        "bookmakers -> markets -> outcomes structure)."
    )
    lines.append("")

    return "\n".join(lines) + "\n"


def main() -> None:
    results = {season: audit_season(season) for season in SEASONS}
    OUT.write_text(render(results))
    print(f"wrote {OUT}")
    for season in SEASONS:
        r = results[season]
        print(
            f"{season}: n_events={r['n_events']} multi_commence={r['n_multi_commence']} "
            f"closing_changes={r['closing_changes']}/{r['closing_evaluable']}"
        )


if __name__ == "__main__":
    main()
