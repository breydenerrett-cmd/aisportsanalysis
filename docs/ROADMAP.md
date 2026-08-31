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

## AUTONOMOUS CONTROL (permanent operating model, set 2026-08-31)

This project is a CONTINUOUS autonomous engineering + research program. A
completed milestone — a family run, a report, a green suite, a shipped
feature — is a CHECKPOINT, never an end condition. The standing loop:

ASSESS → SELECT HIGHEST-VALUE UNBLOCKED TASK → EXECUTE → VERIFY → TEST →
COMMIT/PUSH → UPDATE ROADMAP/STATE → SELECT NEXT TASK → CONTINUE.

Never end a session with "recommended next move: X" — execute X. Checkpoint
reports are given WHILE working, not instead of working. "Continue
autonomous work" means: run this loop.

**The only hard stops:** (1) a stage explicitly gated on Brey's approval;
(2) anything touching sealed 2026-01-01→08-27; (3) irreversible/destructive
decisions; (4) spend beyond the authorized budget (floor 5,000 credits;
~132/day dense grid approved; probes small and deliberate); (5) all
meaningful work genuinely blocked; (6) the session physically cannot
continue. Everything else: decide and continue. A blocked task is
documented, marked, and routed around.

**Priority principle:** information gain × project value ÷ wall-clock ÷ API
cost. Not lines of code, detector count, commit count, or document volume.
Attack the current largest bottleneck (data, market coverage, event
timestamps, power, cost, automation, UX, idea quality) — not the most
familiar subsystem. Forward data overrides reconstructible work, always.

**Lanes** (parallelize when useful; never idle waiting on I/O):
A live/forward evidence · B research · C data acquisition · D
Analyzer/product · E reliability/testing · F next-family preparation.

**Done standard:** production-path integrated, tested, edge cases and
failures handled, point-in-time correct, docs updated, honest terminology,
regression-protected, committed and pushed. Fewer polished units over piles
of 80% experiments.

**Research families** run the tested machine: coverage audit → mechanism →
pre-register → freeze → batch run → replication → FDR → automatic
falsification (battery RULES_VERSION 2.0.0, frozen) → publish all results →
archive → next family. Zero survivors is a result, not a stop condition.

### RESOURCE ARCHITECTURE (Max-capacity model, Brey 2026-08-31 evening)
FABLE 5 orchestrates: state, priorities, worker packets, model selection,
review, integration, adjudication, evidence standards, the Brey decision
queue. SONNET 5 is the DEFAULT execution workforce (coding, tests, research,
docs, product, data plumbing). OPUS 5 is the senior/high-risk worker
(methodology, PIT/leakage integrity, difficult architecture, adversarial
validation, repeated Sonnet failure). SCRIPTS are the compute cluster
(capture, settlement, replay, enumeration, placebo sweeps, bootstraps).
Fable implements directly only when tiny, integrative, or evidence-urgent.
Aggressive PRODUCTIVE parallelism approved; never fake parallelism, duplicate
agents, or expensive models on deterministic work. The live operational
snapshot (active wave, next 5, lookahead, decision queue, bottleneck) is
docs/COMMAND_CENTER.md -- this file holds the durable model, that one holds
the moving state. Priority shift: the project advances simultaneously toward
SELLABLE PRODUCT and REAL RESEARCH ADVANTAGE; research perfection must not
indefinitely delay commercialization. UI implementation waits only for
PRODUCT_DESIGN_HANDOFF.md (separate session) + SAAS_APPLICATION_ARCHITECTURE
review; engine-side preparation proceeds now.

### RESOURCE ARCHITECTURE (superseded earlier same day, kept for history)
Fable 5 orchestrates: decisions, task decomposition, verification standards,
Brey communication. Opus 5 workers execute: implementation, research,
red-teaming — persistent definitions in `.claude/agents/` (opus-research,
opus-data, opus-builder, opus-product, opus-validator, opus-redteam); tasks
handed over as OBJECTIVE/WHY/INPUTS/BOUNDARIES/DELIVERABLE/ACCEPTANCE/
EVIDENCE RULES; high-impact work gets a second worker attacking the first's
deliverable. Deterministic scripts own routine collection: hourly
`scripts/forward_capture.sh`, daily `scripts/daily_loop.sh` — a model reads
only their ESCALATE lines; a no-op capture must not consume model reasoning.
Concurrency 2–4 workers normally; near a usage limit, checkpoint, update
docs/RESUME.md, commit and push before stopping.

### FOUR HORIZONS

**TODAY:** forward capture protected (scripts own it) · resource
architecture live (agents + scripts + trigger prompts) · Analyzer synthesis
layer ("3–5 most important things" per matchup) · slate health monitor ·
research catalogue classification · collection red-team round.

**THIS WEEK:** V3 accumulation watch (`python3 -m src.cli timing`; floors 30,
no early reads) · product red-team of the Analyzer output · pre-event news
relevance characterization (PRE-RESPONSE data only) · reproducibility audit
of one archived family · reliability fixes with regression tests.

**THIS MONTH:** first V3 class-floor analyses as floors are hit · F5
forward-series review (~2 weeks of closes) · season-end handling (slate
empties late September; define off-season capture posture) · lead/lag
leadership stability read once event counts justify it.

**EVOLUTION LAB (proposed 2026-08-31, assessed, NOT started).**
Brey proposed a historical replay engine driving an evolving population of
virtual strategies. Assessment in docs/EVOLUTION_LAB_ASSESSMENT.md: the
replay engine is worth building; naive evolutionary search over 4,859
discovery games would manufacture false discoveries faster than we could
refute them. Reframed so the lab's primary product is the NOISE CEILING —
the same search run over placebo worlds — with CLV-primary fitness,
execution frozen during predictive search, and mechanism directions that
evolution may not flip. Phases 0–3 (feasibility, replay engine, enumerable
space + placebo harness, regularised model vs the close) come first;
evolution is built only if the real maximum beats the placebo ceiling.
AWAITING BREY on the 2024 holdout question before Phase 2.

**NEXT 90 DAYS — evidence branches:**
- PATH A (V3 shows a timing edge): falsification battery on it → forward
  shadow ledger ≥300 selections → the four Ranker unlock conditions →
  Brey sign-off gate.
- PATH B (V3 null, F5/depth promising): design the first F5 family from
  forward-captured closes; consider a costed historical F5 backfill
  proposal for Brey (HARD GATE).
- PATH C (all markets null): Analyzer becomes the product; off-season =
  reliability, KBO/NPB feasibility, 2027 capture architecture.
- PATH D (any real edge survives everything): decision-policy freeze →
  sealed-2026 one-shot request to Brey (HARD GATE, one evaluation, ever).

### CURRENT TASK
Repairing forward evidence. The 2026-08-31 resume audit found the capture
lane quietly broken in three places at once (see FORWARD EVIDENCE AUDIT
below): the F5 close store had never been written, every accumulated V3
event was unmappable, and the odds captures were gitignored. Nothing about
"accumulating nicely" was true. Repair before any new research direction.

### FORWARD EVIDENCE AUDIT (2026-08-31, the lesson)
A monitor that reports health is not the same as health. Three failures ran
concurrently for days and every routine check passed:
1. `data/processed/*` was gitignored, so five days of h2h snapshots and
   every multi-book board lived only on one ephemeral container's disk —
   one recycle from total loss. Fixed 56b8ccf: forward captures are now
   tracked as evidence, for the reason `evidence/` already states.
2. `f5_close.jsonl` never existed. The market-depth lane believed it was
   accumulating and was accumulating nothing.
3. V3 held 33 admissible events and 0 measurable ones — transactions with
   no team recorded, lineup events with no game to map to.
STANDING RULE ADDED: a store that should be growing must be checked for
ROWS, not for the absence of errors. Silence is not success.

### PRODUCT CONCLUSIONS RECORDED (Brey, 2026-08-31)

**1. News speed is NOT a core promise.** Beating books to breaking news is not
viable at our scale -- books suspend within seconds to low minutes, and X's
realistic tier prices broad streaming out of reach
(docs/COMPETITIVE_INTELLIGENCE/X_NEWS_FEASIBILITY.md). The viable product is
the ORGANISED version: public news / lineup / roster change -> explain the
baseball relevance -> show the affected matchup or bet -> show market state
before and after -> tell the user whether the market appears to have reacted
already. That is a shipping description of what "What changed" plus the
price board plus V3's measurement already do.

**2. EVIDENTIAL TRANSPARENCY is a positioning HYPOTHESIS, not settled copy.**
Across 18 audited competitors none has a third-party-audited record and none
makes publishing its own losses the headline promise; all sell more
confidence, edge or picks. Candidate territory: sample-size skepticism,
published losses, evidence states, opposing evidence, explicit uncertainty,
price improvement held distinct from predictive EV, visible methodology.
Do NOT harden this into branding copy here -- the local design/brand research
validates how customers actually understand it first.

**3. Name finalists are FINALISTS ONLY.** Ledgerline, Quiet Signal and
Coverage Grid are not selected. Each requires a domain recheck (several
returned 503), an obvious-collision and trademark search, App Store and
product collision checks, pronunciation and memorability, multi-sport fit,
and consumer testing against the wider candidate set. No name is chosen.

**4. No product UI implementation** until PRODUCT_DESIGN_HANDOFF.md (being
written elsewhere) and docs/SAAS_APPLICATION_ARCHITECTURE.md can be reviewed
together.

### READY QUEUE (refill to ≥3 whenever an item completes)
1. Protect/run due forward capture (standing, lane A — always first).
2. V3 first class-floor analysis when any class reaches 30 admitted
   events AND those events are measurable (lane B; run
   `python3 -m src.cli timing`; do not read early). Mappability is now a
   precondition, not an assumption.
3. F5 forward-series review once ~2 weeks of F5 closes exist in
   data/processed/f5_close.jsonl (lane F: measure coverage/books before
   designing any F5 family; historical F5 backfill is a HARD GATE item).
   BLOCKED until the close pass is confirmed writing rows.
4. Season-end handling (late September): daily loop and capture behavior
   when the MLB slate empties; plan the off-season posture (lane E).
5. Forward prop-listing audit -- DESIGNED, AWAITING BREY
   (docs/PROBE_PROP_LISTING.md: 18 credits/day, ~340 total, hard cap 400).
   COLLECTION_POLICY.md forbids prop collection without a registered
   hypothesis; C1 is deliberately unregistered, so starting the probe
   needs Brey's one-line policy amendment (draft in the doc's section 6).
   Do NOT start it autonomously.

DONE this cycle: timestamp audit · V3 freeze · market probe · collection
policy · lead/lag + eventstudy cores · multibook store · rosterwatch ·
F5 close pass · settle closing fix · Analyzer matchup depth · price-
improvement library + Analyzer wiring · Ranker shell (gated by test) ·
Elo benchmark (close wins, p=0.0003) · V4 (zero survivors) · validation
gate (adjudicated open) · V5 stuff family (zero survivors) · resource
architecture (scripts own collection; Opus workers execute) · research
catalogue (73 ideas classified) · slate health monitor + health CLI ·
Analyzer synthesis layer · collection red-team (6 reproduced bugs fixed) · product red-team
(13 honesty fixes) · closing staleness + marker dates · market-board
unification · relevance layer + What-changed section · V4 reproducibility
audit (exact) · permalinks + season archive.

### FUTURE BACKLOG
V3 falsification battery pass · F5 / F5-totals research families · player-
prop feasibility · pitcher-K market research · public projection benchmark
· any-matchup mode · automated research summaries · event relevance scoring
· market availability forecasting · true-close infrastructure · line-
shopping engine (price improvement ONLY — never sold as EV) · V5/V6 family
design · literature microstructure hypotheses · automation/reliability ·
data-quality audits · performance · docs/handoff · product polish after
function. Discover something higher-value? Add it here yourself.

### HARD APPROVAL GATES
Sealed 2026 evaluation · Ranker Engine 2 activation (all four unlock
conditions + Brey sign-off) · real-money anything (never) · large
historical data purchases · any spend program beyond the approved dense
grid and small probes.

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

## Stage 8 — RESEARCH FAMILY V2: market structure — **DONE** (docs/RESULTS_V2.md; zero survivors)
**Result (2026-08-29):** all five hypotheses evaluated on 2023-24 at zero credit
cost. M5 null (de-vig choice does not matter; proportional stands). M2
inconclusive (snapshot grid too sparse to run the published test). M1 null
(autocorrelation +0.013, not negative; fading loses 3.5%, following loses 3.3%
-- both sides pay the vig). M3 DEBUNK (+8.49pp at p=0.0063 on the baseline,
killed by dose-response, book concentration and season split). M4 underpowered
(270 decided games, nothing significant).

**Next, in priority order:** (1) denser forward snapshot grid inside the last
three hours -- M1 and M2 both died on sampling resolution, and forward
collection is free; (2) the lineup-release window, which needs (1) first;
(3) decision support, which is the part with demonstrated value. A fuller F5
backfill would make M4 answerable but costs credits and awaits Brey's call.

## Stage 8 (pre-registration) — RESEARCH FAMILY V2: market structure (docs/RESEARCH_V2.md)
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

## Stage 9 — Dashboard / product refinement — **IN PROGRESS**
**Direction set 2026-08-29:** with both hypothesis families null, the product's
value is honest decision support, not edge-finding. Work so far:
- `TESTED_NULL` evidence state, ranked weaker than `UNPROVEN`, rendered as
  "Tested — no edge". The eight Stage 2 detectors retagged; `stale_book` had
  been claiming HISTORICAL_CANDIDATE after coming back +0.03pp at p=0.97.
- `rank()` sorts by evidence before surprise, so a refuted claim with a big
  number no longer leads the page over an open question.
- A standing statement in the page header: nothing here is a proven edge,
  thirteen hypotheses tested, none cleared the bar.
- Sample-size guards: `bullpen_exposure` needs five starts and otherwise emits
  a debunk naming the problem; `travel_load` no longer announces a "dense
  stretch" that matches the baseline.

## Stage 9 (original scope) — Dashboard / product refinement
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
