# Persistent roadmap

**The standing instruction:** on "continue autonomous work", find the current
stage below, take its highest-value unfinished item, and go. Update this file as
stages move. `docs/OVERNIGHT_RUN.md` is the running log; this is the map.

**The split, non-negotiable:** 2023–24 discovery · 2025 tuning only ·
2026-01-01→08-27 sealed one-shot confirmation · 2026-08-28→ forward proof.

**Hard rules that never relax:** no real-money betting or bet-capable code; no
fabricated values; no leaky feature in historical evaluation (do not weaken to
raise detector count); never touch sealed 2026 without explicit instruction;
losers always reported; credits (53K) spent only deliberately, probe first.

---

## Stage 1 — Historical data integrity / point-in-time reconstruction
**Objective:** every detector input reconstructible as of a past date, or
formally excluded.
**Status: DONE for exclusion; rebuild OPEN.** Audit module enforces; 7 clean /
4 leaky.
**Remaining:** pitch-level Statcast ingest (~600 chunked requests, free, slow)
to rebuild splits, arsenals, matchup history forward; then flip those inputs to
CLEAN and re-audit.
**Exit:** leaky list empty, or every remaining leak has a documented dead end.
**Autonomous:** yes, fully.

## Stage 2 — Discovery validation
**Objective:** trustworthy 2023–24 numbers for every clean detector, losers
included.
**Status: DONE first pass** (docs/RESULTS_2023_24.md). Label bug found and
regression-tested.
**Remaining:** re-run after Stage 1 unlocks the 4 leaky detectors.
**Exit:** every registered detector evaluated or formally excluded.
**Autonomous:** yes.

## Stage 3 — Candidate falsification  ← **CURRENT**
**Objective:** try to kill bullpen_exposure before believing it.
**Work:** rename CLV proxy honestly; probe for a true closing snapshot
(credit-safe probe first); robustness battery — season / team concentration /
side / fav-dog / price bands / book count / short-start pitchers /
doubleheaders / price-construction sensitivity (best-book vs consensus);
mechanistic story or distrust it.
**Exit:** a validation package (see milestone) with the candidate either dead
or still standing with stated caveats.
**Autonomous:** yes.

## Stage 4 — 2025 tuning
**Objective:** final thresholds, chosen once, on 2025 only.
**Prerequisites:** Stage 3 done; archives written (detector defs, family, full
2023–24 table, code+data hashes) BEFORE first 2025 read.
**Exit:** thresholds frozen with rationale; 2025 numbers labelled
tuning-evidence forever.
**Autonomous:** yes, after archives exist.

## Stage 5 — Complete decision-policy freeze
**Objective:** the whole recommendation policy frozen, not just thresholds:
eligible markets, ML/RL/total/F5 handling, which book counts as available,
consensus + de-vig method, min books, min edge/confidence, stale-price
tolerance, scratch/postponement/lineup-change handling, correlated-signal
handling, price floors/ceilings, no-play and market-unavailable definitions.
**Exit:** policy file in evidence/, hash-pinned, tested, diff-visible.
**Autonomous:** draft yes; **freeze needs your sign-off**.

## Stage 6 — One-shot sealed 2026 confirmation
**Objective:** single evaluation of the frozen policy on 2026-01-01→08-27.
**Prerequisites:** Stage 5 signed off. Seal increments; provisional label
permanent; reported honestly either way.
**Autonomous: NO — requires your explicit go.**

## Stage 7 — Forward proof (runs continuously under everything)
**Objective:** ≥300 graded selections; CLV primary.
**Status: LIVE** since 2026-08-28. Daily loop records + settles.
**Remaining:** true-close capture forward (snapshot near first pitch), CLV
grading report, monthly summaries.
**Exit:** the pre-registered criteria in docs/VALIDATION_CRITERIA.md.
**Autonomous:** yes.

## Stage 8 — Detector expansion
**Objective:** work through the ~47-item catalogue (docs/ALPHA_ROADMAP.md).
**Gate:** BLOCKED until Stages 3–5 conclude — new detectors change the
hypothesis family, which invalidates corrections mid-flight. Re-register the
family explicitly when opened.
**Autonomous:** yes once unblocked.

## Stage 9 — Dashboard / product refinement
**Objective:** improvements that serve analysis/validation (validation package
rendering, robustness views, ledger status on page).
**Gate:** only when it directly supports validation, per standing instruction.
**Autonomous:** yes within that gate.

## Stage 10 — Automation / reliability
**Objective:** the daily loop runs without a human: scheduling, retry coverage,
credit monitoring, morning ledger summary.
**Autonomous:** yes, except anything that spends credits on a schedule —
cadence needs your approval once.

## Stage 11 — Multi-sport expansion (KBO/NPB/NBA/NFL)
**Gate:** BLOCKED until MLB has a validated forward result. Explicitly deferred
by you ("stay on MLB").
**Requires:** your go + probably a fresh odds-subscription month.
