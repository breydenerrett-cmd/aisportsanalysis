# Persistent roadmap

**The standing instruction:** on "continue autonomous work", find the current
stage below, take its highest-value unfinished item, and go. Update this file as
stages move. `docs/OVERNIGHT_RUN.md` is the running log; this is the map.

**Stage states:** OPEN / IN PROGRESS / DONE / BLOCKED / RETIRED. A permanently
BLOCKED item is moved to RETIRED with its reason rather than left to clog
execution.

**Evidence-integrity rule (permanent):** every major evaluation writes an
immutable evidence package — code commit, detector-family version, policy
version, input hashes, recommendation-price definition, comparison/close-price
definition, exact selection set, exclusions, sample sizes, results, confidence
intervals, FDR output, robustness output, evaluation timestamp. An evaluation
that cannot be reproduced from its package is incomplete.

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
**Status: DONE** — 2.74M pitches, all four inputs rebuilt point-in-time; live endpoints remain LEAKY by design. Audit module enforces; 7 clean /
4 leaky.
**Remaining:** pitch-level Statcast ingest (~600 chunked requests, free, slow)
to rebuild splits, arsenals, matchup history forward; then flip those inputs to
CLEAN and re-audit.
**Exit:** leaky list empty, or every remaining leak has a documented dead end.
**Autonomous:** yes, fully.

## Stage 2 — Complete 2023–24 discovery rerun — **DONE** (docs/RESULTS_STAGE2.md; zero survivors)
**Objective:** the FULL pre-registered family evaluated on 2023–24, with the
four newly point-in-time-safe detectors included; losers reported.
**Note:** the first pass (docs/RESULTS_2023_24.md, 7 clean detectors) does not
satisfy this stage — it ran before Stage 1's rebuild.
**Exit:** every registered hypothesis evaluated or formally excluded, full
statistics per detector (n, effect, ROI, late_move, clustered CI, raw p, FDR,
per-season, side balance, fav/dog, team concentration, price bands, book count,
mechanism, dose-response), evidence package written.
**Autonomous:** yes.

## Stage 3B — Falsification of any survivors — **DONE (trivially: no survivors)**
**Objective:** kill false signals. Every candidate that survives Stage 2 gets
the full robustness battery (the one that killed bullpen_exposure — see
docs/VALIDATION_PACKAGE_1.md): season dependence, team concentration, side
bias, fav/dog, price bands, book artifacts, thin markets, doubleheaders,
data-coverage effects, selection-construction sensitivity, extreme
observations, dose-response, plausible mechanism. No rescue by threshold
change. Nothing surviving is an acceptable result.
**History:** the original Stage 3 killed bullpen_exposure (first-pass family).
**Exit:** every survivor either killed-and-documented or standing with stated
caveats; falsification results archived.
**Autonomous:** yes.

## Stage 4 — 2025 tuning — **GATE SATISFIED, BUT EMPTY: no candidate exists to tune. V1 concluded null; see Stage 8.**
**Objective:** final thresholds and policy parameters, chosen once, on 2025
only. Constrained, documented tuning budget — no re-optimising until ROI looks
attractive. Every 2025 number is TUNING EVIDENCE forever.
**Gate (explicit):** does NOT open merely because the first-pass candidate was
killed. Requires: Stage 1 finished or formally exhausted; Stage 2 rerun of the
complete family; Stage 3B on every survivor; the updated 2023–24 package
archived (detector definitions, family, full results incl. losers,
falsification output, code hash, data hashes, selection sets).
**Autonomous:** yes, once the gate is satisfied.

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
**Objective:** graded forward selections; true CLV primary. ≥300 is a FLOOR,
not automatic proof — if intervals stay wide, keep collecting. Keep the five
price concepts separate: recommendation price / best-available at
recommendation / consensus at recommendation / late_move snapshot / true close.
late_move is never called CLV. Historical true-close credits are spent only on
candidates that survive free discovery + robustness.
**Status: LIVE** since 2026-08-28. Daily loop records + settles.
**Remaining:** true-close capture forward (snapshot near first pitch), CLV
grading report, monthly summaries.
**Exit:** the pre-registered criteria in docs/VALIDATION_CRITERIA.md.
**Autonomous:** yes.

## Stage 8 — RESEARCH FAMILY V2: market structure — **OPEN** (docs/RESEARCH_V2.md)
**Reframe (2026-08-29):** V1 asked "do we read baseball better than the market?"
and answered no, consistent with the literature (1,547 MLB moneyline strategies
tested externally; 0.45% profitable at the 1% level, i.e. the chance rate).
V2 asks a different question — "does the market misprice itself?" — over five
pre-registered market-structure hypotheses (M1 overreaction, M2 weekend
day-game staleness, M3 cross-book dispersion, M4 F5-vs-full-game bullpen gap,
M5 de-vig methodology divergence). All five are testable on data already on
disk at zero credit cost. Jacob's decomposition idea moves to V3, reframed as a
conditional market-timing filter rather than a standalone knowledge signal.

## Stage 8 (original scope) — Detector expansion
**Objective:** the ~47-item catalogue (docs/ALPHA_ROADMAP.md), as a SEPARATE
pre-registered family. V1 must never be contaminated midstream: V2 opens only
after V1 completes discovery → falsification → tuning → policy freeze, keeps
its evidence fully separated, and a V2 discovery enters the frozen V1 policy
only by starting a new validation cycle.
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
