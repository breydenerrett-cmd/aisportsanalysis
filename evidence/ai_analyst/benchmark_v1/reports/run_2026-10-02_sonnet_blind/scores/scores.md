| case | verifier | facts | sources | unsupported | flags | action | recalc ok | invented number |
|---|---|---|---|---|---|---|---|---|
| case_01_clean_plus_moneyline | FAIL: fact[0] market:HOU-ATH-2026-09-25-1:home#data.best_price,fac | no | yes | 17 | n/a +2 false alarm | NO_ADJUSTMENT (ok) | yes | no |
| case_02_clean_run_line | FAIL: fact[0] market:CLE-KC-2026-09-25-1:home#data.best_price,fact | no | no | 19 | n/a | NO_ADJUSTMENT (ok) | yes | yes |
| case_03_stale_pitcher_log | FAIL: fact[0] pitcher_log:WSH-DET-2026-09-23-1:away_sp#data.log_th | no | yes | 18 | 1/1 | REQUEST_SCENARIO (want NO_ADJUSTMENT) | yes | no |
| case_04_wrong_starter | FAIL: fact[0] model_input:TB-NYY-2026-09-23-1:away_sp_known#data.a | no | no | 8 | 1/1 | CORRECT_INPUT (ok) | yes | no |
| case_05_conflicting_sources | FAIL: fact[0] market:CLE-KC-2026-09-25-1:home#data.best_price,fact | no | yes | 18 | 1/1 | REQUEST_SCENARIO (want NO_ADJUSTMENT) | yes | no |
| case_06_market_alternative | FAIL: fact[0] market:MIN-SF-2026-09-23-1:home#data.best_price,fact | no | no | 24 | n/a | COMPARE_MARKET (ok) | yes | no |
| case_07_missing_information | FAIL: fact[0] market:HOU-SEA-2026-09-23-1:away#data.best_price,fac | no | yes | 7 | 1/1 | NO_ADJUSTMENT (ok) | yes | no |
| case_08_original_failure_trap | FAIL: fact[0] model_input:NYM-WSH-2026-09-25-1:home_sp_known#data. | no | yes | 12 | 1/1 | REQUEST_SCENARIO (want NO_ADJUSTMENT) | yes | no |
