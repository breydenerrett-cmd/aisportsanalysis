# Stage 2 — full-family 2023–24 discovery, on fixed code

**This supersedes docs/RESULTS_2023_24.md entirely.** Evidence package:
`evidence/stage2_2026-08-28/` (reproducible from runner.py + hashes).

4,859 games; 4,395 priced (join fixes recovered every AZ game and all
consecutive-day series). All 11 pre-registered detectors ran point-in-time:
the four once-excluded ones via the 2.74M-pitch rebuilt store plus 4,892
posted lineups. 26,932 findings; 13,608 side-less (context/debunk/totals) by
design. Effects vs de-vigged consensus; date-clustered statistics throughout.

| Detector | n | Effect | Clustered 95% CI | p | late_move | ROI | 2023 / 2024 |
|---|---|---|---|---|---|---|---|
| bullpen_exposure | 1508 | +1.65 | −0.70..+4.04 | .18 | +0.001 | +2.2% | +0.72 / +2.61 |
| bullpen_workload | 2499 | +0.79 | −0.81..+2.34 | .32 | −0.000 | +0.1% | +0.61 / +0.97 |
| pitch_mix_mismatch | 3339 | +0.60 | −0.74..+2.07 | .40 | +0.000 | +0.0% | +1.15 / +0.05 |
| platoon_mismatch | 104 | +3.84 | −5.79..+13.37 | .44 | +0.001 | +10.5% | **−15.5 / +17.5** |
| starter_mismatch | 2295 | −0.75 | −2.74..+1.27 | .48 | +0.002 | −2.9% | +0.10 / −1.64 |
| travel_load | 604 | +0.38 | −3.40..+4.24 | .85 | +0.000 | −0.4% | +4.28 / −3.60 |
| stale_book | 2949 | +0.03 | −1.35..+1.48 | .97 | +0.000 | −1.0% | +0.51 / −0.69 |
| lineup_vs_starter | 26 | — | — | — | — | — | below the 30-selection floor |

No selections by design: implied_bullpen_disagreement (context),
park_and_weather (totals), thin_matchup_history (debunks carry no side).

**FDR (BH q=0.10, 1pp floor): ZERO of 8 clear both gates.** Every interval
includes zero. Stage 3B is complete trivially — there is nothing to falsify.

Notable honest details:
- bullpen_exposure, the previous +4.08pp "candidate", is **+1.65pp (p=.18)** on
  correct joins. The prior signal was substantially the join bug.
- platoon_mismatch's +10.5% ROI is 104 games whose per-season effects point in
  OPPOSITE directions (−15.5 vs +17.5). That is the definition of noise.
- late-market movement is ~zero for every detector, consistent with the nulls.

**Conclusion: Research Family V1, evaluated correctly, contains no detector
that beats the market's own price on 2023–24.** The pre-registered thresholds
were reasonable baseball; the market prices all of it.
