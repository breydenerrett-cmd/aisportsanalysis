# Totals Coverage Audit

Deterministic, counts-only output of `scripts/totals_coverage_audit.py`. No outcome is joined to any price anywhere in this file -- every number below is a row count, a distinct-value count, or a date range. Generated as an input to `docs/TOTALS_METHODOLOGY.md`.

## Archive: `data/historical/odds_history/mlb_20{23,24,25}.jsonl`

| season | totals outcome rows | events | date range | books | distinct lines |
|---|---|---|---|---|---|
| 2023 | 246448 | 2489 | 2023-02-27 .. 2023-10-08 | 19 | 53 |
| 2024 | 181068 | 2484 | 2024-03-20 .. 2024-10-07 | 14 | 45 |
| 2025 | 177026 | 2497 | 2025-03-19 .. 2025-10-07 | 11 | 48 |

Source file(s): `data/historical/odds_history/mlb_2023.jsonl`, `data/historical/odds_history/mlb_2024.jsonl`, `data/historical/odds_history/mlb_2025.jsonl`.

## Forward capture: `data/processed/odds_multibook.jsonl`

| market tag | rows |
|---|---|
| untagged | 27932 |
| totals | 7555 |
| spreads | 7045 |

Source: `data/processed/odds_multibook.jsonl`.

## Forward capture: `data/processed/l1_observations.jsonl` (counts only -- includes rows inside the sealed 2026 window; no date breakdown or outcome given, structural counts only)

Total rows: 586922

| market_key | rows |
|---|---|
| h2h | 316438 |
| totals | 255530 |
| spreads | 9130 |
| h2h_1st_5_innings | 3440 |
| totals_1st_5_innings | 2384 |

`totals` rows with a non-null `line` field: 255530. Distinct books quoting `totals`: 20.

Source: `data/processed/l1_observations.jsonl`.

This file establishes forward capture depth only. The 2023-2025 discovery/replication window used by any totals family is the archive table above -- l1_observations rows dated in the sealed window (2026-01-01 onward) must never be read for content beyond this structural count.

