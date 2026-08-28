> **INVALIDATED — 2026-08-28, superseded by the Stage 2 rerun.**
> An adversarial audit found the historical price join was assigning games the
> NEXT game's odds in consecutive-day series (55% of matched 2023 selections;
> 1,966 "recommendation-time" prices captured after the graded game had
> finished), silently dropping every Diamondbacks game, and feeding the FDR
> gate an unclustered p. Every number below — the positives, the nulls, and the
> bullpen_exposure falsification — was computed through those defects and none
> can be cited. Kept for the record of what was believed and why.

# Validation package 1 — 2023–24

**Scope:** first legitimate discovery results plus the falsification of the one
surviving candidate. Split preserved throughout: 2023–24 discovery · 2025
untouched · 2026→08-27 sealed · 2026-08-28→ forward.

## Metric definitions

**Late-market movement (CLV proxy) — deliberately not called closing line
value.** The historical store's last pre-game snapshot sits a **median 84
minutes** before first pitch. A real close is the final broadly available price
before lock, and a line can move plenty in the last hour. The metric is renamed
in code (`late_move`) and everywhere it is reported.

**A true close IS purchasable.** Probe (30 credits): the historical archive
serves 5-minute snapshots ~14 minutes before any first pitch, 8–18 books.
Matching must be by team pair — the Odds API's commence times drift to actual
first pitch. Full true-close coverage of the bullpen_exposure selections was
costed at 10,570 credits and **deliberately not spent**, because the free
falsification battery below killed the candidate first.

**True CLV going forward** (the definition the ledger will grade against):
- recommendation = dossier `information_time`, consensus de-vig (proportional)
  across all books quoting, best book recorded separately, min 5 books
- close = last snapshot before first pitch, same consensus construction,
  gap-to-pitch recorded per game
- pitcher scratch after recommendation = entry stands, flagged `scratched`
- postponement = void, never a loss; stale quote (>45 min old at snapshot) dropped

## Full 2023–24 family, losers included

Effects in points vs the de-vigged consensus the market already implied;
clustered-by-date 95% CIs. FDR = Benjamini-Hochberg q=0.10 + 1pp effect floor.

| Detector | n | Effect | 95% CI | p | FDR | Late move | ROI | 2023/2024 |
|---|---|---|---|---|---|---|---|---|
| bullpen_exposure | 1322 | +4.08 | +1.26..+6.54 | .0027 | pass | −0.008 | +7.8% | +3.25/+4.92 |
| stale_book | 2655 | −0.77 | −2.27..+0.68 | .42 | fail | +0.008 | −2.2% | −1.12/−0.25 |
| starter_mismatch | 2018 | +0.52 | −1.68..+2.77 | .64 | fail | +0.116 | +0.8% | +0.93/+0.11 |
| travel_load | 526 | −0.86 | −4.59..+3.17 | .69 | fail | −0.036 | −2.1% | +2.05/−3.88 |
| bullpen_workload | 899 | +0.64 | −2.01..+3.40 | .70 | fail | +0.058 | −0.6% | +0.64 (2024 only) |

Excluded before evaluation as **not point-in-time reconstructible** (the MLB
splits endpoint ignores its date parameters — proven byte-identical across three
ranges): platoon_mismatch, pitch_mix_mismatch, thin_matchup_history,
lineup_vs_starter. No side-bearing selections by design:
implied_bullpen_disagreement (context), park_and_weather (totals).

Separately graded: the implied-bullpen hypothesis itself (n=308, simultaneous
full-game/F5 prices, 0.0-min separation): **null** (p=0.90); the apparent
directional hit was a two-sided volatility artifact.

## bullpen_exposure: falsified

It passed FDR, the side control (+3.41pp), and season stability. The robustness
battery — pre-declared cuts, no new hypotheses — killed it:

| Test | n | Effect | Zero in CI? |
|---|---|---|---|
| Full sample | 1322 | +4.07 | no |
| Excluding top-5 contributing teams | 1055 | +2.07 | **yes** (p=.18) |
| Excluding longshot band (implied<.40) | 1192 | +2.92 | no (p=.04) |
| Books ≥10 | 1093 | +4.53 | no |
| **All cuts at once** | **793** | **+1.12** | **yes (p=.52)** |

- **Concentration:** half the edge lives in 5 teams (SD +26.7pp on 34 games is
  luck-sized). 
- **Dose-response inverted:** surprise 1.0–1.5 → +5.4pp; 1.5–2.5 → +1.6; ≥2.5 →
  +1.7. A real mispricing of bullpen exposure should grow with the exposure gap.
  It shrinks.
- **Thin books:** 1–4-book games run −11pp — the "consensus" there is noise.
- **No mechanism survives:** "the market underrates innings-eaters" predicts the
  dose-response we did not get, and a two-season-wide blind spot with **zero**
  late-market movement toward our side has no plausible carrier.

**Verdict: the +4.08pp is a mixture of team-level luck, a hot longshot band, and
thin-book price noise. Not promoted. The 10,570-credit true-close pull is not
spent on it.** It remains on the live page as UNPROVEN context and continues to
be graded forward by the ledger at zero marginal cost.

## What appears promising / what failed

Nothing currently survives falsification. That is the honest state of the
project and it is the correct output of the process — the alternative was
believing a fake +9.6pp (label bug) or a fake +4.1pp (this candidate).

The most promising open directions, in order: (1) the four excluded detectors,
unblocked by the pitch-level Statcast rebuild — these are the matchup-
decomposition ideas the product is actually about; (2) forward evidence, already
accumulating; (3) F5/totals markets, never yet evaluated as bet targets.

## Archives (written before any 2025 read)

`evidence/archive_2026-08-28/`: detector definitions, hypothesis family, full
result JSON, selection set, code commit hash. 2025 remains unread.
