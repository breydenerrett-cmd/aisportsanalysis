# Pre-registration — a calibrated probability, wired without an edge

**Frozen before anything is fitted, measured or wired.** No number below is a result;
every figure quoted is read from a named file. Today `src/engine/glue.py:637` carries `p_model: float = 0.52`, and
`src/engine/analyze.py:233-234` computes `raw_edge = proposal.p_model -
consensus.fair_probability`, then `edge_bps = int(round(raw_edge * 10_000)) -
config.friction_bps`. Every `edge_bps` in `docs/eod/2026-08-31.md` (−1431 to +996) is
therefore a placeholder minus a price, not a belief about a game. Replacing 0.52 with a
*better* number under the same formula replaces one artifact with a subtler one; this
document exists to make that structurally impossible first.

## 1. The central distinction

**A calibrated probability is not an edge.**

*Calibrated* means: of the games where we said 60%, about 60% happened — a forecast
scored against outcomes (`src/core/calibration.py`). *Edge* means: our probability
differs from the de-vigged market's, in our favour, by more than friction — a forecast
scored against a price.

The de-vigged closing consensus is already a well-calibrated forecast:
`docs/EVOLAB_PHASE2A_BASELINE.md` §9.2 measures it out-of-sample on 2,234 games of 2024
at log-loss **0.67275**, Brier **0.23999**. Adopting it as `p_model` therefore buys
honest prediction confidence and, **by construction, exactly zero betting value** —
forecast and benchmark are the same object, so their difference is definitionally zero.
That is the intended and sufficient outcome, and it is Owner Decision 6
(`docs/ARCHITECTURE_BETTING_ENGINE.md` §9.1): "Prediction quality and betting value are
separate... the product may expose prediction confidence separately."

### 1.1 Probability provenance classes (pre-registered)

Every probability the engine carries declares exactly one class — a new required field
on `Proposal` (`src/engine/analyze.py:28-40`), with no default.

| class | definition | invariant |
|---|---|---|
| `MARKET_DERIVED` | `p_model` is a deterministic function of the same board's own de-vigged consensus for the same selection | `edge_bps` MUST be `None`; the candidate MUST NOT be staked on value grounds; it may be published as prediction confidence |
| `MODEL_DERIVED` | `p_model` is computed from the price-blind snapshot only, with no price input anywhere in its derivation | `edge_bps` MAY be computed; must pass a price-scramble check like `docs/EVOLAB_PHASE2A_BASELINE.md` §9.4.3's |
| `NONE` | no probability | `p_model is None`, `edge_bps is None`, `rating is None` — the structural absence `analyze.py:279-285` already implements |

`MODEL_DERIVED` is the only class from which a value claim can be made, and today no
such system exists in production.

## 2. The manufactured-edge trap, and the enforced rule

Phase 2A's M1 is `logit(p_mkt) + b0` with **b0 = −0.038951**
(`docs/EVOLAB_PHASE2A_BASELINE.md` §9.1) — a *recalibration*, exactly what an
implementer reaches for when asked for a "calibrated" probability. Under the current
formula it is a constant one-sided fake edge on the home side of every game: at a market
home probability of 0.40 / 0.50 / 0.60 it shifts `raw_edge` by **−93.11 / −97.37 /
−93.84 bps** — a systematic tilt toward the away side of every board, forever, from a
constant Phase 2A measured as worth **nothing** (M1 − M0 = −0.0000506, p = **0.896**).

**Rule (enforced, not conventional): a `MARKET_DERIVED` probability may never enter an
edge computation.**

- **Where:** `src/engine/analyze.py`, PROJECT phase, lines 233-234. The `edge_bps`
  branch is additionally gated on `proposal.provenance == MODEL_DERIVED`.
- **What a violating call must do:** raise `ValueError` and refuse the whole
  `analyze()` call — not return `None`, not warn, not skip the candidate. A proposal
  declaring `MARKET_DERIVED` that reaches PROJECT with a non-`None` edge, or carrying no
  provenance at all, is a programming error and must fail at write time, as the
  `game_pk` mismatch at `analyze.py:187-192` does.
- **Consequence in RANK:** `_rank_key` (`analyze.py:296-298`) already sorts `edge_bps
  is None` to the bottom via `-(10**9)`, so a market-derived candidate can never
  outrank anything on value. Correct: it has none.
- **No recalibrated market probability is wired.** Not M1, not a Platt or isotonic
  refit. The wired market-derived probability is the identity on the de-vigged
  consensus, zero fitted parameters — a deliberate departure from "use the best-fitting
  calibrator", because a zero-parameter map is the only one for which "differs from the
  market by a constant" cannot arise.

## 3. Fit protocol

Because §2 wires the identity map, **there is nothing to fit for the market-derived
probability** — this protocol's main content and main protection. The rest governs any
future `MODEL_DERIVED` candidate.

- **Fittable:** 2023 (train) and 2024 (evaluate) only, as the non-evidential sandbox
  `docs/EVOLAB_PHASE2A_BASELINE.md` §0 defines — diagnostic, never evidence. **2025 is
  tuning-only**: it may inform engineering choices; no 2025 number is published as a
  validation result. **2026-01-01 .. 2026-08-27 is SEALED**: not read, not summarised,
  not peeked at for coverage counts.
- **Refit cadence: none.** The wired probability is a frozen function of the board; a
  scheduled recalibration is precisely what §2 forbids.
- **A refit is invalid if** it (a) reads sealed data, (b) uses information timestamped
  at or after the decision instant of any record it will score, (c) selects parameters
  using forward ledger outcomes it will then be scored on, or (d) changes the probability
  without a pre-registration committed first.
- **Reused from Phase 2A's frozen recipe**, for any future model-derived fit:
  date-grouped 5-fold CV inside the training season only (`baseline.date_folds`,
  `cross_validate`), train-season-only imputation and standardisation constants,
  unpenalised intercept, §8's leakage checklist run unconditionally. **Departures:** no
  market offset and no fitted intercept for the wired probability (there is no fit),
  plus §4's reliability diagnostic, which Phase 2A did not report.

## 4. What "calibrated" will be measured by

- **Reliability diagnostic — two schemes, both published.** (a) fixed-width,
  `src/core/calibration.reliability_curve(preds, obs, bins=10)`, empty bins retained;
  (b) equal-count deciles over the observed predictions. MLB moneyline consensus
  concentrates in roughly 0.30–0.70, so fixed-width bins leave most of the range empty
  while equal-count bins move their edges with the sample. Both are reported, and so is
  any disagreement.
- **Losses:** log-loss and Brier (`src/core/calibration.py`), plus ECE and max-CE from
  the fixed-width curve.
- **Baselines, always three:** (1) the de-vigged consensus on the same games — for a
  market-derived probability the same forecast, so the delta is zero and is published as
  zero, never omitted; (2) `baseline_base_rate(outcomes)`; (3) the frozen 2024 reference
  points 0.67275 / 0.23999, as context only, never a live cross-sample comparison.
- **Minimum sample before any calibration claim is published:** ≥ 500 decision/review
  pairs carrying both a `p_model` and a WIN/LOSS settlement (`scorecard._calibration`),
  AND ≥ 9 independent clusters of 7 game-days (`DEFAULT_SPA_BLOCK_LENGTH = 7.0`,
  `DEFAULT_REQUIRED_CLUSTERS = 9`, `src/factory/scorecard.py:77-93`). Below either, the
  report says "not enough data to assess calibration" and prints the counts; bins may
  be shown only labelled `PROVISIONAL`, with n per bin.
- **Wording that MAY be used:** "prediction confidence", "market-derived probability",
  "the market's own de-vigged probability, republished", "calibration consistent with
  the market's, as expected by construction".
- **Wording that MAY NOT be used, at any sample size:** "edge", "value", "our model
  estimates", "beats the market", "+X bps", or any phrasing making a market-derived
  number the subject of a verb implying independent knowledge.

## 5. What this unlocks, and what stays absent

Becomes genuinely computable:
- `Scorecard.reliability_bins` — today `AbsentComponent("reliability_bins", "no
  calibration-bin implementation exists")` (`scorecard.py:648-649`). It does exist:
  `calibration.reliability_curve`, with §4 fixing the bin scheme.
- `Scorecard.brier` and `EconomicComponent.logloss_vs_market` stop being the
  `NEUTRAL_BRIER = 0.25` / `NEUTRAL_LOGLOSS = ln 2 = 0.6931471805599453` placeholders
  (`scorecard.py:64-71`) and become measured numbers; `_probability_quality`
  (`analyze.py:353-359`) stops being `abs(0.52-0.5)*2`.

Stays absent, unchanged: `robustness`, `price_resilience`, `falsification`,
`multiplicity`, `forward_survival.out_of_sample/within_sealed_epochs`,
`realized_return_ci`, `stability.season_month_stability` — none a calibration question.

**A market-derived probability can never satisfy the economic component of
`promotion_verdict`** — structurally, not by good intentions. `economically_meaningful`
requires `n_edge > 0 and edge_return > 0.0 and n_calibration > 0 and logloss_mean <
NEUTRAL_LOGLOSS` (`scorecard.py:414-417`). The trap: 0.67275 < 0.693, so the log-loss
half of that conjunction *passes* on the market's own forecast. What holds it shut is
`n_edge`, counting `verdict == "play"` decisions carrying `edge_bps`; §2 forces
`edge_bps is None` for every market-derived decision, so `n_edge == 0` and
`economically_meaningful` is `False`. That chain is the guarantee and must carry a named
regression test.

## 6. Falsification conditions

These observations, on the §4 minimum sample, would show it is not calibrated:

1. ECE > 0.03, or max-CE > 0.10 on any bin holding ≥ 50 predictions.
2. Signed gaps of one sign in ≥ 8 of 10 populated bins — a monotone tilt, the b0
   pathology of §2 arriving by another door.
3. Log-loss worse than `baseline_base_rate` on the same games.
4. `mean_predicted` and `observed_rate` differing by more than 0.02 overall.
5. Any non-zero measured difference between the wired probability and the board's own
   de-vigged consensus on the same selection — not a calibration failure but a
   **wiring** failure, and the likeliest of these to fire.

**On observation:** demote the provenance to `NONE` for that market — publish no
probability rather than a wrong one — record the triggering statistic in the ledger, and
print it in the EOD report as a failed check. It must **not** apply a corrective offset;
that reintroduces §2's constant by the back door. Any change requires a new
pre-registration.

## 7. The separate, gated question — not opened here

"Is there a probability that beats the close?" is a different question, already
answered for the current feature set. Given all eighteen columns built from the seven
numeric matrix features (`src/engine/features.py`), a free unpenalised intercept and
date-grouped cross-validation, the primary out-of-sample differential was **+0.0000412**
log-loss per game — the model *worse* — at clustered p = **0.914**, and the L1 fit
selected **the empty set** (`docs/EVOLAB_PHASE2A_BASELINE.md` §9.1-9.3). Phase 2B
searched 8,811 strategies over the same space and returned `BELOW_PLACEBO_CEILING`, 0 of
3 generators cleared, pooled percentile 13.3 (`docs/EVOLAB_PHASE2B_RESULTS.md` §1).

Reopening it requires **new information, not new fitting**: an input class the closing
price plausibly does not contain — a materially fresher cutoff than the current
month-granular one (§9.5's own named limitation), or a market thin enough that no
efficient close exists. Another functional form over the same monthly-stale seven
features is not new information. **This document does not propose reopening it.**

## 8. Adversarial guards — how this breaks, and what blocks it

| failure mode | guard |
|---|---|
| Wires M1 (b0 = −0.038951) "because it fit better" | §2: no fitted recalibration of the consensus is wired at all; identity only |
| Adds provenance as an optional field defaulting to `MODEL_DERIVED` | §1.1: required field, no default; missing provenance raises in PROJECT |
| Makes the violating call return `None` edge instead of raising | §2: a violation must raise `ValueError` and fail the `analyze()` call |
| De-vigs with a different method than the board's consensus, so p and benchmark drift apart by a small non-zero amount that reads as edge | §6.5: any non-zero measured difference from the board's own consensus is a wiring failure that demotes to `NONE` |
| Subtracts `friction_bps` from a market-derived candidate and calls the negative number "our edge" | §2: no edge is computed at all for that class, so there is nothing to subtract from |
| Publishes "our model has a 0.673 log-loss, better than a coin flip" | §4 wording list; §5 names ln 2 as a placeholder, not an achievement |
| Lets `economically_meaningful` pass because log-loss beats ln 2 | §5: `n_edge == 0` forces it `False`; named regression test required |
| Applies a corrective offset when a §6 check fires | §6: demote to `NONE`; correction requires a new pre-registration |
| Reports reliability bins on 40 games | §4 minimum sample; below it, `PROVISIONAL` label with per-bin n or nothing |
| Refits quietly each month "to stay current" | §3: refit cadence is none; an unregistered refit is invalid by definition |
| Treats a 2025 tuning number as a validation result | §3: 2025 is tuning-only and never published as validation |
