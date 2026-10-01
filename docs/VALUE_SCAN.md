# Value scan

Generated: 2026-10-01T22:07:42Z

Settled entries from 2026-09-10 to 2026-09-30 (all settled dates).
Regenerate with `python scripts/value_scan.py`. Read-only on every ledger; the script changes no rule, gate, threshold or published record.

## How to read this

**Verdict rule (fixed, identical for every row).** `TOO FEW` when n staked < 30. `CANDIDATE` only when n staked >= 100 AND mean closing-line value > 0 AND the lower end of its 95% interval (mean - 1.96 se) > 0 AND z vs the market > 2. Everything else is `NO EVIDENCE`. A row whose closing-line value cannot be measured (every prop) can never reach `CANDIDATE`.

**Multiplicity.** This table has 43 rows, each a different population. With about that many looks, one or two will look good by chance alone, and a z above 2 in one row is what chance produces. No row here is a reason to change a rule. Changing a rule needs a pre-registered test on forward data (`docs/PREREG_CARD_V2.md`). A `CANDIDATE` would only be a hypothesis to pre-register.

**Verdicts this run:** TOO FEW: 37, NO EVIDENCE: 6, CANDIDATE: 0.

Units are flat 1u per entry at the frozen price (pushes, voids, unresolved and withdrawn entries are never staked). ROI = units / n staked. Rows are never pooled across rule, market, entry class or season scope; postseason entries (the project's calendar rule, `effective_record._ledger_postseason_pks`) are their own rows, and fills never enter a pick row. z = (actual wins - market-expected wins) / sqrt(sum p(1-p)) using the de-vigged market probability frozen on each entry. Pu/Vo/Un = pushes / voids / unresolved (never staked). Where a column carries `(k/n)`, only k of the n staked entries record that number.

## Ledgers read

| Ledger | Status | Rows | Settled dates | First | Last | Corrections folded |
|---|---|---|---|---|---|---|
| V1 public | read | 518 | 13 | 2026-09-10 | 2026-09-22 | 0 |
| V1 shadow | read | 604 | 7 | 2026-09-23 | 2026-09-30 | 0 |
| V2 public | read | 83 | 8 | 2026-09-22 | 2026-09-30 | 0 |
| V2 shadow A | read | 116 | 8 | 2026-09-22 | 2026-09-30 | 0 |
| V2 shadow C | read | 79 | 8 | 2026-09-22 | 2026-09-30 | 0 |
| V2 shadow E | read | 58 | 8 | 2026-09-22 | 2026-09-30 | 0 |
| NFL | read | 17 | 4 | 2026-09-17 | 2026-09-27 | 0 |

Our-probability field read per rule: V1 public = game/total: model_probability; prop: probability; V1 shadow = game/total: model_probability; prop: probability; V2 public = our_probability_used (after the 0.038 markdown); V2 shadow A = our_probability_used (after the 0.038 markdown); V2 shadow C = our_probability_used (after the 0.038 markdown); V2 shadow E = our_probability_used (after the 0.038 markdown); NFL V1 = model_probability (frozen null on every NFL pick); NFL V2 = model_probability (frozen null on every NFL pick).

Integrity check: 0 staked entries whose flat-stake units recomputed from price and result differ from the ledger's own profit_units by more than rounding.

## Population table (record against the market)

| Row | Rule | Market | Class | Scope | n staked | W-L | Pu/Vo/Un | Units | ROI | Mean break-even | Mean market p | Mean our p | Exp. units if market right | z vs market | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R01 | V1 public | moneyline | pick | regular | 104 | 69-35 | 0/0/0 | +9.71 | +9.3% | 0.607 | 0.593 | 0.553 | -2.33 | +1.47 | NO EVIDENCE |
| R02 | V1 public | moneyline | fill | regular | 8 | 3-5 | 0/0/0 | -2.77 | -34.6% | 0.553 | 0.542 | 0.478 | -0.15 | -0.95 | TOO FEW |
| R03 | V1 public | run line | pick | regular | 1 | 1-0 | 0/0/0 | +0.67 | +67.1% | 0.598 | 0.579 | 0.545 | -0.03 | +0.85 | TOO FEW |
| R04 | V1 public | hits prop | pick | regular | 71 | 45-26 | 0/0/0 | -5.84 | -8.2% | 0.692 | 0.655 | 0.728 | -3.79 | -0.38 | NO EVIDENCE |
| R05 | V1 public | total-bases prop | pick | regular | 46 | 33-13 | 0/1/0 | +6.21 | +13.5% | 0.630 | 0.597 | 0.653 | -2.44 | +1.67 | NO EVIDENCE |
| R06 | V1 shadow | moneyline | pick | regular | 38 | 24-14 | 0/0/0 | +0.56 | +1.5% | 0.625 | 0.611 | 0.568 | -0.82 | +0.26 | NO EVIDENCE |
| R07 | V1 shadow | moneyline | pick | postseason | 5 | 5-0 | 0/0/0 | +3.72 | +74.3% | 0.576 | 0.566 | 0.543 | -0.09 | +1.96 | TOO FEW |
| R08 | V1 shadow | moneyline | fill | regular | 3 | 2-1 | 0/0/0 | +0.48 | +15.9% | 0.557 | 0.548 | 0.467 | -0.05 | +0.42 | TOO FEW |
| R09 | V1 shadow | moneyline | fill | postseason | 3 | 1-2 | 0/0/0 | -1.17 | -39.1% | 0.563 | 0.549 | 0.487 | -0.07 | -0.75 | TOO FEW |
| R10 | V1 shadow | hits prop | pick | regular | 63 | 40-23 | 0/1/0 | -4.03 | -6.4% | 0.679 | 0.644 | 0.710 | -3.27 | -0.15 | NO EVIDENCE |
| R11 | V1 shadow | hits prop | pick | postseason | 3 | 2-1 | 0/0/0 | -0.02 | -0.7% | 0.666 | 0.631 | 0.675 | -0.16 | +0.13 | TOO FEW |
| R12 | V1 shadow | total-bases prop | pick | regular | 26 | 15-11 | 0/1/0 | -2.78 | -10.7% | 0.641 | 0.604 | 0.666 | -1.49 | -0.28 | TOO FEW |
| R13 | V2 public | moneyline | pick | regular | 3 | 2-1 | 0/0/0 | +0.69 | +23.2% | 0.549 | 0.543 | 0.570 | -0.03 | +0.43 | TOO FEW |
| R14 | V2 public | moneyline | fill | regular | 13 | 9-4 | 0/1/0 | +3.03 | +23.3% | 0.565 | 0.554 | 0.515 | -0.25 | +1.00 | TOO FEW |
| R15 | V2 public | moneyline | fill | postseason | 3 | 3-0 | 0/0/0 | +2.19 | +72.9% | 0.579 | 0.566 | 0.518 | -0.07 | +1.52 | TOO FEW |
| R16 | V2 public | hits prop | pick | regular | 15 | 7-8 | 0/1/0 | -2.85 | -19.0% | 0.576 | 0.554 | 0.598 | -0.58 | -0.68 | TOO FEW |
| R17 | V2 public | hits prop | fill | regular | 1 | 1-0 | 0/1/0 | +0.70 | +70.4% | 0.587 | 0.558 | 0.613 | -0.05 | +0.89 | TOO FEW |
| R18 | V2 public | hits prop | fill | postseason | 2 | 0-2 | 0/0/0 | -2.00 | -100.0% | 0.554 | 0.524 | 0.557 | -0.11 | -1.48 | TOO FEW |
| R19 | V2 public | total-bases prop | pick | regular | 15 | 7-8 | 0/1/0 | -2.89 | -19.3% | 0.575 | 0.545 | 0.595 | -0.79 | -0.61 | TOO FEW |
| R20 | V2 public | total-bases prop | fill | regular | 15 | 11-4 | 0/0/0 | +3.94 | +26.3% | 0.586 | 0.554 | 0.594 | -0.81 | +1.40 | TOO FEW |
| R21 | V2 public | total-bases prop | fill | postseason | 1 | 1-0 | 0/0/0 | +0.65 | +64.5% | 0.608 | 0.573 | 0.611 | -0.06 | +0.86 | TOO FEW |
| R22 | V2 shadow A | moneyline | pick | regular | 16 | 11-5 | 0/1/0 | +4.14 | +25.9% | 0.550 | 0.540 | 0.507 | -0.29 | +1.19 | TOO FEW |
| R23 | V2 shadow A | moneyline | pick | postseason | 3 | 2-1 | 0/0/0 | +0.62 | +20.7% | 0.566 | 0.554 | 0.465 | -0.07 | +0.39 | TOO FEW |
| R24 | V2 shadow A | hits prop | pick | regular | 13 | 9-4 | 0/3/0 | +2.87 | +22.1% | 0.559 | 0.537 | 0.583 | -0.52 | +1.13 | TOO FEW |
| R25 | V2 shadow A | hits prop | fill | regular | 1 | 0-1 | 0/0/0 | -1.00 | -100.0% | 0.488 | 0.465 | 0.561 | -0.05 | -0.93 | TOO FEW |
| R26 | V2 shadow A | total-bases prop | pick | regular | 64 | 40-24 | 0/4/0 | +5.53 | +8.6% | 0.576 | 0.544 | 0.603 | -3.50 | +1.30 | NO EVIDENCE |
| R27 | V2 shadow A | total-bases prop | pick | postseason | 7 | 5-2 | 0/0/0 | +1.72 | +24.6% | 0.570 | 0.539 | 0.568 | -0.38 | +0.93 | TOO FEW |
| R28 | V2 shadow C | moneyline | pick | regular | 2 | 1-1 | 0/0/0 | -0.15 | -7.6% | 0.553 | 0.549 | 0.578 | -0.02 | -0.14 | TOO FEW |
| R29 | V2 shadow C | moneyline | fill | regular | 15 | 11-4 | 0/1/0 | +4.64 | +30.9% | 0.558 | 0.547 | 0.518 | -0.28 | +1.45 | TOO FEW |
| R30 | V2 shadow C | moneyline | fill | postseason | 3 | 3-0 | 0/0/0 | +2.19 | +72.9% | 0.579 | 0.566 | 0.518 | -0.07 | +1.52 | TOO FEW |
| R31 | V2 shadow C | hits prop | pick | regular | 12 | 6-6 | 0/0/0 | -1.50 | -12.5% | 0.573 | 0.551 | 0.593 | -0.47 | -0.36 | TOO FEW |
| R32 | V2 shadow C | hits prop | fill | regular | 2 | 2-0 | 0/2/0 | +1.37 | +68.5% | 0.593 | 0.566 | 0.603 | -0.09 | +1.24 | TOO FEW |
| R33 | V2 shadow C | hits prop | fill | postseason | 2 | 0-2 | 0/0/0 | -2.00 | -100.0% | 0.554 | 0.524 | 0.557 | -0.11 | -1.48 | TOO FEW |
| R34 | V2 shadow C | total-bases prop | pick | regular | 12 | 6-6 | 0/0/0 | -1.53 | -12.7% | 0.572 | 0.540 | 0.590 | -0.66 | -0.28 | TOO FEW |
| R35 | V2 shadow C | total-bases prop | fill | regular | 16 | 12-4 | 0/0/0 | +4.76 | +29.7% | 0.582 | 0.551 | 0.588 | -0.85 | +1.60 | TOO FEW |
| R36 | V2 shadow C | total-bases prop | fill | postseason | 1 | 1-0 | 0/0/0 | +0.83 | +82.6% | 0.548 | 0.515 | 0.550 | -0.06 | +0.97 | TOO FEW |
| R37 | V2 shadow E | moneyline | fill | regular | 2 | 1-1 | 0/0/0 | -0.38 | -18.8% | 0.615 | 0.600 | 0.570 | -0.05 | -0.29 | TOO FEW |
| R38 | V2 shadow E | hits prop | pick | regular | 5 | 2-3 | 0/0/0 | -1.75 | -35.0% | 0.615 | 0.588 | 0.639 | -0.22 | -0.85 | TOO FEW |
| R39 | V2 shadow E | hits prop | fill | regular | 8 | 6-2 | 0/3/0 | +3.17 | +39.7% | 0.533 | 0.509 | 0.547 | -0.36 | +1.37 | TOO FEW |
| R40 | V2 shadow E | total-bases prop | pick | regular | 12 | 7-5 | 0/0/0 | -0.62 | -5.2% | 0.615 | 0.583 | 0.649 | -0.63 | +0.00 | TOO FEW |
| R41 | V2 shadow E | total-bases prop | fill | regular | 7 | 6-1 | 0/1/0 | +2.75 | +39.3% | 0.615 | 0.585 | 0.601 | -0.35 | +1.46 | TOO FEW |
| R42 | NFL V1 | moneyline | pick | regular | 10 | 7-3 | 0/0/0 | -0.26 | -2.6% | 0.745 | 0.723 | not recorded | -0.29 | -0.16 | TOO FEW |
| R43 | NFL V2 | moneyline | pick | regular | 1 | 1-0 | 0/0/0 | +0.93 | +92.6% | 0.519 | 0.583 | not recorded | +0.12 | +0.85 | TOO FEW |

`*` expected units and z use only the staked entries that carry a market probability.

## Population table (calibration and closing line)

Brier score: ours and the market's on the same staked entries that carry both; difference = ours minus market (positive = ours worse), with the paired per-entry standard error. Closing-line value is `card_clv.measure_pick` unchanged: de-vigged close minus the break-even of the frozen price, in probability points; it refuses props always, and refuses a stale, thin or decision-board close, which is shown as a refusal.

| Row | n w/ market p | Brier n | Brier ours | Brier market | Diff +/- se | CLV n | Mean CLV (pts) +/- se | CLV 95% low | Beat close | CLV refused (reason x n) |
|---|---|---|---|---|---|---|---|---|---|---|
| R01 | 104 | 104 | 0.2308 | 0.2235 | +0.0073 +/- 0.0052 | 51 | -1.21 +/- 0.18 | -1.56 | 14% | CLOSE_STALE x51, CLOSING_BOARD_THIN x1, NO_EVENT x1 |
| R02 | 8 | 8 | 0.2367 | 0.2478 | -0.0111 +/- 0.0253 | 8 | -0.96 +/- 0.50 | -1.94 | 25% | - |
| R03 | 1 | 1 | 0.2072 | 0.1771 | +0.0300 | 0 | - | - | - | CLOSING_BOARD_THIN x1 |
| R04 | 71 | 71 | 0.2461 | 0.2329 | +0.0132 +/- 0.0091 | 0 | - | - | - | PROP_NOT_MEASURED x71 |
| R05 | 46 | 46 | 0.2062 | 0.2131 | -0.0069 +/- 0.0083 | 0 | - | - | - | PROP_NOT_MEASURED x46 |
| R06 | 38 | 38 | 0.2380 | 0.2320 | +0.0059 +/- 0.0094 | 31 | -1.21 +/- 0.16 | -1.52 | 3% | CLOSE_STALE x7 |
| R07 | 5 | 5 | 0.2097 | 0.1898 | +0.0198 +/- 0.0143 | 1 | -1.82 | - | 0% | CLOSE_STALE x3, NO_EVENT x1 |
| R08 | 3 | 3 | 0.2634 | 0.2139 | +0.0495 +/- 0.0519 | 2 | -0.70 +/- 0.01 | -0.72 | 0% | CLOSING_BOARD_IS_DECISION_BOARD x1 |
| R09 | 3 | 3 | 0.2452 | 0.2784 | -0.0331 +/- 0.0419 | 0 | - | - | - | CLOSE_STALE x3 |
| R10 | 63 | 63 | 0.2392 | 0.2317 | +0.0075 +/- 0.0086 | 0 | - | - | - | PROP_NOT_MEASURED x63 |
| R11 | 3 | 3 | 0.2127 | 0.2126 | +0.0001 +/- 0.0290 | 0 | - | - | - | PROP_NOT_MEASURED x3 |
| R12 | 26 | 26 | 0.2457 | 0.2394 | +0.0064 +/- 0.0128 | 0 | - | - | - | PROP_NOT_MEASURED x26 |
| R13 | 3 | 3 | 0.2364 | 0.2475 | -0.0111 +/- 0.0171 | 2 | -2.40 +/- 2.47 | -7.25 | 50% | NO_EVENT x1 |
| R14 | 13 | 13 | 0.2458 | 0.2344 | +0.0115 +/- 0.0136 | 10 | -0.83 +/- 0.50 | -1.81 | 20% | CLOSE_STALE x3 |
| R15 | 3 | 3 | 0.2329 | 0.1886 | +0.0443 +/- 0.0136 | 1 | -0.75 | - | 0% | CLOSE_STALE x1, NO_EVENT x1 |
| R16 | 15 | 15 | 0.2647 | 0.2535 | +0.0112 +/- 0.0121 | 0 | - | - | - | PROP_NOT_MEASURED x15 |
| R17 | 1 | 1 | 0.1495 | 0.1956 | -0.0462 | 0 | - | - | - | PROP_NOT_MEASURED x1 |
| R18 | 2 | 2 | 0.3107 | 0.2745 | +0.0363 +/- 0.0028 | 0 | - | - | - | PROP_NOT_MEASURED x2 |
| R19 | 15 | 15 | 0.2653 | 0.2518 | +0.0135 +/- 0.0135 | 0 | - | - | - | PROP_NOT_MEASURED x15 |
| R20 | 15 | 15 | 0.2170 | 0.2336 | -0.0166 +/- 0.0097 | 0 | - | - | - | PROP_NOT_MEASURED x15 |
| R21 | 1 | 1 | 0.1511 | 0.1821 | -0.0310 | 0 | - | - | - | PROP_NOT_MEASURED x1 |
| R22 | 16 | 16 | 0.2526 | 0.2402 | +0.0124 +/- 0.0127 | 14 | -0.44 +/- 0.32 | -1.06 | 29% | CLOSE_STALE x1, CLOSING_BOARD_IS_DECISION_BOARD x1 |
| R23 | 3 | 3 | 0.2615 | 0.2511 | +0.0104 +/- 0.0651 | 1 | -1.12 | - | 0% | CLOSE_STALE x2 |
| R24 | 13 | 13 | 0.2090 | 0.2227 | -0.0137 +/- 0.0150 | 0 | - | - | - | PROP_NOT_MEASURED x13 |
| R25 | 1 | 1 | 0.3145 | 0.2161 | +0.0984 | 0 | - | - | - | PROP_NOT_MEASURED x1 |
| R26 | 64 | 64 | 0.2380 | 0.2401 | -0.0022 +/- 0.0089 | 0 | - | - | - | PROP_NOT_MEASURED x64 |
| R27 | 7 | 7 | 0.2385 | 0.2256 | +0.0129 +/- 0.0175 | 0 | - | - | - | PROP_NOT_MEASURED x7 |
| R28 | 2 | 2 | 0.2560 | 0.2618 | -0.0058 +/- 0.0281 | 1 | -4.88 | - | 0% | NO_EVENT x1 |
| R29 | 15 | 15 | 0.2427 | 0.2247 | +0.0180 +/- 0.0092 | 11 | -0.39 +/- 0.55 | -1.48 | 27% | CLOSE_STALE x4 |
| R30 | 3 | 3 | 0.2329 | 0.1886 | +0.0443 +/- 0.0136 | 1 | -0.75 | - | 0% | CLOSE_STALE x1, NO_EVENT x1 |
| R31 | 12 | 12 | 0.2561 | 0.2515 | +0.0047 +/- 0.0130 | 0 | - | - | - | PROP_NOT_MEASURED x12 |
| R32 | 2 | 2 | 0.1576 | 0.1884 | -0.0308 +/- 0.0154 | 0 | - | - | - | PROP_NOT_MEASURED x2 |
| R33 | 2 | 2 | 0.3107 | 0.2745 | +0.0363 +/- 0.0028 | 0 | - | - | - | PROP_NOT_MEASURED x2 |
| R34 | 12 | 12 | 0.2582 | 0.2496 | +0.0087 +/- 0.0151 | 0 | - | - | - | PROP_NOT_MEASURED x12 |
| R35 | 16 | 16 | 0.2127 | 0.2319 | -0.0192 +/- 0.0082 | 0 | - | - | - | PROP_NOT_MEASURED x16 |
| R36 | 1 | 1 | 0.2028 | 0.2348 | -0.0321 | 0 | - | - | - | PROP_NOT_MEASURED x1 |
| R37 | 2 | 2 | 0.2648 | 0.2585 | +0.0063 +/- 0.0285 | 2 | -0.02 +/- 0.00 | -0.02 | 0% | - |
| R38 | 5 | 5 | 0.3110 | 0.2783 | +0.0327 +/- 0.0265 | 0 | - | - | - | PROP_NOT_MEASURED x5 |
| R39 | 8 | 8 | 0.2220 | 0.2306 | -0.0085 +/- 0.0197 | 0 | - | - | - | PROP_NOT_MEASURED x8 |
| R40 | 12 | 12 | 0.2421 | 0.2447 | -0.0026 +/- 0.0190 | 0 | - | - | - | PROP_NOT_MEASURED x12 |
| R41 | 7 | 7 | 0.1919 | 0.1955 | -0.0037 +/- 0.0100 | 0 | - | - | - | PROP_NOT_MEASURED x7 |
| R42 | 10 | not recorded | not recorded | not recorded | not recorded | 3 | -2.32 +/- 0.75 | -3.79 | 0% | CLOSE_STALE x7 |
| R43 | 1 | not recorded | not recorded | not recorded | not recorded | 0 | - | - | - | CLOSE_STALE x1 |

## Entries never staked

Withdrawn entries and populations with no WIN or LOSS. Counted, never staked. The results shown for withdrawn entries are what they would have been; no unit is attributed to them.

| Rule | Market | Class | Scope | Entries | Void | Push | Unresolved | Withdrawn (result if shown) |
|---|---|---|---|---|---|---|---|---|
| V2 public | hits prop | withdrawn | regular | 2 | 0 | 0 | 0 | WIN x2 |
| V2 public | total-bases prop | withdrawn | regular | 3 | 0 | 0 | 0 | LOSS x1, VOID x1, WIN x1 |
| V2 public | other | pick | regular | 3 | 3 | 0 | 0 | - |
| V2 public | other | fill | regular | 1 | 1 | 0 | 0 | - |
| V2 shadow A | moneyline | withdrawn | postseason | 4 | 0 | 0 | 0 | LOSS x1, WIN x3 |
| V2 shadow A | other | pick | regular | 6 | 6 | 0 | 0 | - |
| V2 shadow C | moneyline | withdrawn | regular | 1 | 0 | 0 | 0 | WIN x1 |
| V2 shadow C | hits prop | withdrawn | regular | 2 | 0 | 0 | 0 | WIN x2 |
| V2 shadow C | total-bases prop | withdrawn | regular | 1 | 0 | 0 | 0 | LOSS x1 |
| V2 shadow C | other | pick | regular | 3 | 3 | 0 | 0 | - |
| V2 shadow C | other | fill | regular | 2 | 2 | 0 | 0 | - |
| V2 shadow E | total-bases prop | withdrawn | regular | 2 | 0 | 0 | 0 | VOID x2 |
| V2 shadow E | other | pick | regular | 6 | 6 | 0 | 0 | - |
| V2 shadow E | other | fill | regular | 1 | 1 | 0 | 0 | - |

## V2 value gate

Descriptive only. The value test is `our_probability_used >= value_need`, both frozen on the entry (G7). Within each rule, staked entries are split by whether they passed it and compared on win minus market probability (1 for a win, 0 for a loss, minus the frozen de-vigged market probability). Difference = passed minus failed; the standard error is Welch's. A negative difference means entries that passed did worse against the market than entries that failed. This is a question for a pre-registered forward test, not a reason to move the gate.

| Population | Group | n | W-L | Units | ROI | Win - market p |
|---|---|---|---|---|---|---|
| V2 shadow A, regular season | passed value test | 54 | 32-22 | +2.78 | +5.1% | +0.058 |
| V2 shadow A, regular season | failed value test | 40 | 28-12 | +8.76 | +21.9% | +0.150 |
| V2 shadow A, regular season | difference (passed - failed) | | | | | -0.092 +/- 0.099, z -0.93 |
| V2 shadow A, regular + postseason | passed value test | 56 | 32-24 | +0.78 | +1.4% | +0.037 |
| V2 shadow A, regular + postseason | failed value test | 48 | 35-13 | +13.10 | +27.3% | +0.179 |
| V2 shadow A, regular + postseason | difference (passed - failed) | | | | | -0.142 +/- 0.093, z -1.53 |
| V2 shadow A, picks only, regular + postseason | passed value test | 55 | 32-23 | +1.78 | +3.2% | +0.046 |
| V2 shadow A, picks only, regular + postseason | failed value test | 48 | 35-13 | +13.10 | +27.3% | +0.179 |
| V2 shadow A, picks only, regular + postseason | difference (passed - failed) | | | | | -0.133 +/- 0.093, z -1.43 |
| V2 public, regular season | passed value test | 41 | 23-18 | -0.89 | -2.2% | +0.012 |
| V2 public, regular season | failed value test | 21 | 14-7 | +3.52 | +16.8% | +0.110 |
| V2 public, regular season | difference (passed - failed) | | | | | -0.098 +/- 0.132, z -0.74 |
| V2 public, regular + postseason | passed value test | 41 | 23-18 | -0.89 | -2.2% | +0.012 |
| V2 public, regular + postseason | failed value test | 27 | 18-9 | +4.35 | +16.1% | +0.111 |
| V2 public, regular + postseason | difference (passed - failed) | | | | | -0.099 +/- 0.121, z -0.82 |

Check: on the stores that freeze a G7_VALUE flag (V2 public, shadows C and E), the two-number comparison disagrees with the frozen flag on 0 of 205 entries. Shadow A freezes no failed_gates (it is the band-only superset), so the comparison of the two frozen numbers is its only mark.

## What cannot be measured and why

Current counts from the ledgers, so it is visible when one becomes measurable.

- **NFL model probability not frozen.** 0 of 11 NFL entries carry our probability (staked: 0 of 11). Our NFL calibration cannot be tested until this is nonzero.
- **NFL observed time not frozen.** 0 of 11 NFL entries carry observed_utc (staked: 0 of 11). Without it the closing-line comparison cannot rule out a decision board that is the closing board.
- **UFC ungraded.** 7 picks published, 0 settled rows. There is no UFC result to measure.
- **Prop closes absent.** 420 staked prop entries, 0 measurable against a close (card_clv refuses every prop: PROP_NOT_MEASURED). By market: hits prop 198, total-bases prop 222.
- **Game closes refused.** 233 staked game entries, 139 measured, refused: CLOSE_STALE x84, CLOSING_BOARD_IS_DECISION_BOARD x2, CLOSING_BOARD_THIN x2, NO_EVENT x6.

Per rule: staked entries recording no probability of ours, no market probability, and VOID or UNRESOLVED entries (never staked).

| Rule | Staked | No our p | No market p | VOID | UNRESOLVED | Withdrawn |
|---|---|---|---|---|---|---|
| V1 public | 230 | 0 | 0 | 1 | 0 | 0 |
| V1 shadow | 141 | 0 | 0 | 2 | 0 | 0 |
| V2 public | 68 | 0 | 0 | 8 | 0 | 5 |
| V2 shadow A | 104 | 0 | 0 | 14 | 0 | 4 |
| V2 shadow C | 65 | 0 | 0 | 8 | 0 | 4 |
| V2 shadow E | 34 | 0 | 0 | 11 | 0 | 2 |
| NFL V1 | 10 | 10 | 0 | 0 | 0 | 0 |
| NFL V2 | 1 | 1 | 0 | 0 | 0 | 0 |

VOID entries by reason (never staked):

| Rule | Market | Reason | n |
|---|---|---|---|
| V1 public | batter_total_bases | no box score found for this player in this game | 1 |
| V1 shadow | batter_hits | no box score found for this player in this game | 1 |
| V1 shadow | batter_total_bases | no box score found for this player in this game | 1 |
| V2 public | batter_hits | no box score found for this player in this game | 2 |
| V2 public | batter_runs_scored | no settlement rule for market 'batter_runs_scored' | 4 |
| V2 public | batter_total_bases | no box score found for this player in this game | 1 |
| V2 public | moneyline | no final score stored for this game | 1 |
| V2 shadow A | batter_hits | no box score found for this player in this game | 3 |
| V2 shadow A | batter_runs_scored | no settlement rule for market 'batter_runs_scored' | 6 |
| V2 shadow A | batter_total_bases | no box score found for this player in this game | 4 |
| V2 shadow A | moneyline | no final score stored for this game | 1 |
| V2 shadow C | batter_hits | no box score found for this player in this game | 2 |
| V2 shadow C | batter_runs_scored | no settlement rule for market 'batter_runs_scored' | 5 |
| V2 shadow C | moneyline | no final score stored for this game | 1 |
| V2 shadow E | batter_hits | no box score found for this player in this game | 3 |
| V2 shadow E | batter_runs_scored | no settlement rule for market 'batter_runs_scored' | 7 |
| V2 shadow E | batter_total_bases | no box score found for this player in this game | 1 |

