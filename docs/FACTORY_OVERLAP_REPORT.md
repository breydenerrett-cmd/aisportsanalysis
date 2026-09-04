# Factory overlap report

Generated 2026-09-04 22:54 UTC. Counts and overlap only -- no returns/ROI -- see `docs/FACTORY_SCALE_DESIGN.md` for the method and its limits.

Found 1 sweep artifact(s).

| artifact | world | n_strategies | n_games | real_champion |
|---|---|---|---|---|
| `data/research/evolab/sweep-0014914df78666b9-REAL.json` | REAL | 8811 | 4188 | 4f1b92d3a4cf55ba |

## `data/research/evolab/sweep-0014914df78666b9-REAL.json`

Decision-level overlap computed (backfilled from `data/research/evolab/masks-0014914df78666b9.index.json` + `data/research/evolab/masks-0014914df78666b9.bin` (see `scripts/factory_masks_from_sweep.py`)).

- unique wagers: **6,050**
- total decisions: **9,859,245** (across 8,811 strategies)
- dedup ratio (unique / total): **0.0006**
- families at Jaccard >= 0.8 (single-linkage, `overlap.FAMILY_THRESHOLD`): **1,062**
- N_effective_families: **1,062**
- N_effective_credit (heuristic, NOT calibrated -- design section 3): **2452.46**

Largest 15 of 1,062 families (by member count):

| rank | family size | example strategy_id |
|---|---|---|
| 1 | 4,019 | `0022400bb549de16` |
| 2 | 132 | `0206cd4f78442869` |
| 3 | 107 | `001339b751b94c83` |
| 4 | 105 | `023f7f4985f5fa46` |
| 5 | 98 | `028772d7355307ee` |
| 6 | 94 | `001038d0f3c31b75` |
| 7 | 92 | `0665f560ceb36fd8` |
| 8 | 90 | `008c9b008176ed56` |
| 9 | 85 | `00243481fefc2039` |
| 10 | 79 | `00a6e5ac86a24a66` |
| 11 | 67 | `0722a59087c6adc5` |
| 12 | 61 | `02a824d000993b8e` |
| 13 | 50 | `007b2dfd85467220` |
| 14 | 50 | `0ad15cdc39d87214` |
| 15 | 43 | `09d7343509aa95ce` |

N_effective_credit is a diminishing-returns heuristic (`1 + log2(family_size)` summed over families), not a calibrated effective-sample-size estimator -- see design section 3. Family count is the primary, assumption-free statistic. Neither number is a CSCV/SPA substitute or a promotion gate.

