# Totals Population Audit (B6)

Deterministic, counts-only output of `scripts/totals_population_audit.py`, produced for `docs/TOTALS_METHODOLOGY.md` "## Methodology re-review -- 2026-09-05" item B6, ahead of any totals family registration. No outcome (`total_runs`, `won`, or any settlement field) is read, joined, or reported anywhere in this file. Re-running this script against unchanged input files reproduces this file byte-for-byte.

Closing-snapshot definition: latest snapshot with `snapshot_at` in `[commence_time - 6h, commence_time)`, using `commence_time` from that same snapshot's own event record (never a post-hoc schedule field), per R5/A7c. Per-line floor: >= 3 distinct books quoting the exact point value, per R2. Half-point vs integer determined on the book-count-weighted modal line (tiebreak toward 8.5, then closest to 8.5, then smaller value), per R3/sec 2.2 Decision A. 2025 is TUNING_ONLY per CLAUDE.md and reported separately; 2026 is SEALED and not read.

## 1-4. Population counts

| season | (1) any totals quote | (2) floor met (>=3 books, per-line, at closing) | (3) half-point consensus | (4) joint (floor AND half-point) -- candidate denominator | excluded: no closing snapshot in window | (7) rescheduled games |
|---|---|---|---|---|---|---|
| 2023 | 2489 | 2393 | 1317 | 1316 | 95 | 384 |
| 2024 | 2484 | 2410 | 1313 | 1313 | 74 | 566 |
| 2025 (TUNING_ONLY) | 2497 | 2402 | 1273 | 1272 | 94 | 874 |

## 5. Closing-line gap distribution (minutes, snapshot -> commence_time)

| season | n (games with a closing snapshot) | p50 | p90 | p99 | max | proposed max-staleness bound (h) |
|---|---|---|---|---|---|---|
| 2023 | 2394 | 84.3 | 324.3 | 354.4 | 359.3 | 6 |
| 2024 | 2410 | 84.4 | 349.4 | 355.4 | 359.4 | 6 |
| 2025 (TUNING_ONLY) | 2403 | 84.3 | 323.2 | 359.4 | 359.4 | 6 |

Proposed bound per B5: smallest whole-hour bound covering >= 95% of events with a closing snapshot, floored at 6h and capped at 24h -- derived purely from this timing distribution (no outcome field read), stated here as a quantile per B5's required order (measure gap distribution first, freeze bound second, before any push/split re-measurement).

## 6. Bucket-occupancy tables (population-shift chi-square inputs, R1/B1)

Occupancy of the closing modal line and the per-line max book count, 2023 vs 2024 (the coverage-asymmetry seasons named in A2); 2025 shown separately as TUNING_ONLY, not part of the 2023-vs-2024 chi-square. Bucket edges fixed in advance: line buckets [5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5]; book-count buckets exact 1-5, 6+.

### Line buckets (by closing modal line)

| bucket | 2023 | 2024 | 2025 (TUNING_ONLY) |
|---|---|---|---|
| <6.5 | 0 | 2 | 3 |
| <7.5 | 70 | 178 | 168 |
| <8.5 | 642 | 991 | 805 |
| <9.5 | 1133 | 992 | 1060 |
| <10.5 | 391 | 162 | 264 |
| <11.5 | 90 | 67 | 66 |
| >=11.5 | 68 | 18 | 37 |

### Book-count buckets (by per-line max book count at closing)

| bucket | 2023 | 2024 | 2025 (TUNING_ONLY) |
|---|---|---|---|
| 1 | 0 | 0 | 1 |
| 2 | 1 | 0 | 0 |
| 3 | 0 | 1 | 0 |
| 4 | 1 | 1 | 3 |
| 5 | 2 | 48 | 20 |
| 6+ | 2390 | 2360 | 2379 |

Source: `data/historical/odds_history/mlb_20{23,24,25}.jsonl`, parsed via the same nested snapshot -> events -> bookmakers -> markets -> outcomes structure as `scripts/totals_coverage_audit.py`.

