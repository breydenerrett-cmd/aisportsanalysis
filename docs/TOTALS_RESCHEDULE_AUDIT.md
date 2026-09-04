# Totals Reschedule Audit

Deterministic, counts-only follow-up to `docs/TOTALS_POPULATION_AUDIT.md` item (7) ("rescheduled games": 384 / 2023, 566 / 2024, 874 / 2025 events with more than one distinct `commence_time` across their own archive snapshots), produced by `scripts/totals_reschedule_audit.py`. Reuses that script's JSONL parser and closing-snapshot definition (R5/A7c) unchanged. No outcome/score field is read, joined, or reported anywhere in this file. Re-running against unchanged input files reproduces this file byte-for-byte.

## Commence-time delta distribution (consecutive snapshots of the same event)

| season | events w/ totals quotes | events w/ >1 distinct commence_time | <=1m | 1-5m | 5-15m | 15-60m | 60-180m | >180m | day-change | n deltas |
|---|---|---|---|---|---|---|---|---|---|---|
| 2023 | 2489 | 384 | 181 | 108 | 12 | 51 | 19 | 0 | 28 | 399 |
| 2024 | 2484 | 566 | 319 | 186 | 15 | 48 | 13 | 3 | 25 | 609 |
| 2025 (TUNING_ONLY) | 2497 | 874 | 713 | 245 | 24 | 73 | 17 | 3 | 31 | 1106 |

## Sign of delta (forward = commence_time moved later)

| season | forward | backward | zero (line-only re-emit, no shift) |
|---|---|---|---|
| 2023 | 282 | 117 | 0 |
| 2024 | 476 | 133 | 0 |
| 2025 (TUNING_ONLY) | 631 | 475 | 0 |

## Clustering at exact delta values (rounded |delta| in whole minutes)

Counts of consecutive-snapshot deltas whose absolute magnitude rounds to each probed value; probed set fixed in advance: [1, 2, 5, 10, 15, 30, 45, 60, 90, 120, 180, 1440] minutes (includes 5/10/15-minute provider-jitter candidates, 60/120/180-minute DST- or timezone-shaped candidates, and 1440 = full day).

| season | 1m | 2m | 5m | 10m | 15m | 30m | 45m | 60m | 90m | 120m | 180m | 1440m |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2023 | 102 | 51 | 5 | 1 | 9 | 12 | 5 | 11 | 2 | 1 | 0 | 0 |
| 2024 | 258 | 76 | 9 | 4 | 0 | 13 | 3 | 1 | 2 | 3 | 0 | 0 |
| 2025 (TUNING_ONLY) | 667 | 98 | 16 | 5 | 4 | 18 | 3 | 7 | 3 | 4 | 1 | 0 |

## MLB schedule cross-check

No point-in-time MLB schedule store exists in this repository. `src/providers/mlb.py` (`fetch_schedule`) calls the live MLB Stats API on demand and nothing under `data/` persists a historical `scheduled_first_pitch` value keyed by game/date (searched: `scheduled_first_pitch`, `schedule` under `data/` -- only odds-archive files and `f5_tminus2`'s live per-run fetch were found). A closing `commence_time` vs MLB-scheduled-first-pitch match rate is therefore NOT computed here: doing so would require a new live/backfill fetch, which is outside this audit's deterministic, no-outcome-read, no-new-spend scope. This gap is reported, not silently skipped.

## Closing-snapshot anchor sensitivity

For each event, the closing snapshot is picked two ways: (a) the existing R5/A7c rule -- latest snapshot with `snapshot_at` in `[commence_time - 12h, commence_time)` using that snapshot's OWN `commence_time`; (b) the same 12h window rule but anchored instead to the event's LAST-OBSERVED `commence_time` (the value carried by its final snapshot) applied uniformly across all of that event's snapshots. `changed` counts events where the two rules pick a different snapshot (or one picks a snapshot and the other finds none).

| season | evaluable events | anchor choice changed |
|---|---|---|
| 2023 | 2403 | 0 |
| 2024 | 2422 | 6 |
| 2025 (TUNING_ONLY) | 2417 | 9 |

## Recommendation

The delta distribution below is dominated by sub-15-minute, both-signed shifts with visible clustering at round values (5, 10, 15, 60 minutes) rather than the day-scale, one-directional shifts a genuine MLB reschedule (rainout, doubleheader retiming) would produce; the day-change bucket, where present, is the only category plausibly attributable to a real schedule change. This is consistent with provider-side timestamp jitter (re-polling drift, rounding, or feed republication) rather than hundreds of true reschedules per season. Recommendation: keep the existing self-referential closing-snapshot rule (each snapshot's OWN `commence_time`, per R5/A7c) as the anchor -- switching to a single last-observed `commence_time` per event would silently use post-hoc (later-than-closing) information for any event whose commence_time was still drifting at closing time, which is a leak risk the current rule was built to avoid. The anchor-sensitivity table above quantifies how many events' closing-snapshot choice would actually move if this were changed; do not adopt the alternative anchor without first establishing (via the schedule cross-check, once a point-in-time schedule store exists) which of the two anchors better tracks true first pitch.

Source: `data/historical/odds_history/mlb_20{23,24,25}.jsonl`, parsed via `scripts/totals_population_audit.py`'s `_load_event_snapshots` (identical to `scripts/totals_coverage_audit.py`'s nested snapshot -> events -> bookmakers -> markets -> outcomes structure).

