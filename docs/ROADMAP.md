# Persistent roadmap

**The standing instruction:** on "continue autonomous work", find the current
stage below, take its highest-value unfinished item, and go. Update this file as
stages move. `docs/OVERNIGHT_RUN.md` is the running log; this is the map.

**CURRENT STAGE POINTER (updated 2026-09-15).** Stages 1–15 below are
history and context, kept for the audit trail, but NOT the active work
queue. Read `docs/PRODUCT_DOCTRINE.md` first (LOCKED, governs every product
decision), then resume at **Stage 16** at the bottom of this file: the
owner-approved roadmap for 2026-09-15 to 2026-10-15, with the queue an
autonomous run claims from. Stage 12's "ACTIVE" marker and Stage 9's "IN
PROGRESS" marker are stale; Stage 16 supersedes both.

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

### CURRENT TASK (2026-09-01)
PAID-BETA LAUNCH is the active program. Staging is LIVE at
https://linehound-staging.fly.dev (GitHub Actions deploy; hourly health
monitor; auto-redeploys on code + capture commits). LINEHOUND Launch Ops
(separate session) owns Stripe/webhook/Fly-secrets and the checkout dry
run; the visual design system is being finished in a separate Claude
Design session; both hand back here. This session: engineering/research
that does not collide with those — commerce/auth hardening (done, all
review findings fixed pre-Stripe), monitoring, tests, and research on
triggers. One gate recorded for Launch Ops: staging must be on a build
>= 6489bfa before BILLING_PROVIDER=stripe (docs/LAUNCH_OPS_SECURITY_
HANDOFF.md). The forward-evidence repair below is COMPLETE (kept as the
standing lesson); the two-tools work order is COMPLETE. V3 still below
its 30-event measurement floor, accumulating on the hourly captures.

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
NOTE 2026-09-03 18:30Z: owner said GO on the checkpoint's vertical slice
(docs/CHECKPOINT_PHASE0_2026-09-03.md §5). The slice is the only build work
until it is proven end to end on a real slate: S1 game_pk join, S2 shared
feature builder, S3 replay through analyze(), S5 slate runner, S6 settle +
fitness, S7 EOD self-review, S8 daily-loop wiring. Four markets only
(moneyline, run line, game totals, F5 moneyline) -- no new market families,
no factory population growth, no product surfaces until the loop works and
is demonstrated on one historical slate, one current slate, one paper
account and one EOD review. Capture keeps running but does not consume the
roadmap.
NOTE 2026-09-03 09:00Z: proof-of-function checkpoint posted
(docs/CHECKPOINT_PHASE0_2026-09-03.md, evidence under
docs/planning/checkpoint-2026-09-03/): ~30% of the end-to-end milestone;
six blocking bugs on the engine decision path confirmed by review. The
standing loop's next items are those bug fixes (lanes dispatched 09:00Z),
then nothing from the checkpoint's §5 vertical slice until the owner says
go. No new market families, no factory work, no product work meanwhile.
NOTE 2026-09-03 02:30Z: the betting-engine plan
(docs/ARCHITECTURE_BETTING_ENGINE.md) is APPROVED WITH AMENDMENTS (section
9.1 there). Phase 0 has started: P0-A/B/C/D/E/H lanes dispatched. The
standing loop may work Phase 0 packets from the plan's section 8 in the
stated order (W1, W13-forward, W7, W5, W2, W3, then W4, W10, W6). Capture
completeness still outranks every other item, but engine/factory work
proceeds in parallel; infrastructure must not consume the roadmap. Credit
spend follows the ~900/day envelope with the P0-C guards; no new tier
switches on without its measured probe.
NOTE 2026-09-02 (closed 22:10Z): the orchestration day is over; the
end-of-day synthesis is docs/ORCHESTRATION_DAY_2026-09-02.md and the
standing loop resumes from this queue. First item for the loop: a full
`python3 scripts/test_parallel.py` on main (the last full run on main
was 3,186 tests green at 20:10Z before Wave 1; the fast tier is green on
the final head). Then the synthesis's TOP 5: staging browser
verification of the four V2 screens (blocked from this environment by
the proxy), the nightly entry-vs-close diagnostic over the backfilled
ledger, the store-completeness helper + pinned-read template, and V3
accumulation (relevant transactions ~2-3/day; lineup_posted at 29/30).
1. Protect/run due forward capture (standing, lane A — always first).
2. V3 first class-floor analysis — PRECONDITION MET 2026-09-02:
   transaction_first_seen is at 56 measurable events (floor 30); the
   pre-registered primary test is being coded and run as an orchestrated
   lane today (docs/RESEARCH_V3_TIMING.md addendum will carry the read).
   lineup_posted is at 29/30 — do not read it early.
3. F5 forward-series review once ~2 weeks of F5 closes exist in
   data/processed/f5_close.jsonl (lane F: measure coverage/books before
   designing any F5 family; historical F5 backfill is a HARD GATE item).
   Close pass CONFIRMED writing rows (structural audit 2026-09-01: 94 rows,
   11 games over 2 days, 8-9 books/game, no duplicates, all pregame,
   correct market; daily cap behaving as designed). Now purely
   time-gated on ~2 weeks of accumulation — first review window ~09-14.
4. Season-end handling (late September): daily loop and capture behavior
   when the MLB slate empties; plan the off-season posture (lane E).
   PLANNED (docs/SEASON_END_PLAN.md). Credit-gate fix DONE 2026-09-01: the
   daily/standalone snapshot now skips the paid capture on a confirmed-empty
   slate (dense.any_game_scheduled). REMAINING: the postseason/spring-training
   V3+F5+prop admissibility decisions (§3.1) are Brey's, needed before
   2026-09-29 (first Wild Card) or the code's silent-admit default takes over.
5. Forward prop-listing audit -- RUNNING since 2026-08-31 (approved
   narrowly; scripts/forward_capture.sh PROP_LISTING_AUDIT=on; 418 rows,
   34 fetches ≈ 34 credits of the 400 hard cap as of 2026-09-02). A
   bounded prop PRICE layer (≤18 credits/day, hard cap, env-gated) is
   being added 2026-09-02 under the owner-approved master-plan
   capture-now principle (docs/COLLECTION_POLICY.md amendment); the
   historical prop purchase remains a HARD APPROVAL GATE.

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
Referral loop (post-beta, first post-launch iteration — full spec frozen
in docs/REFERRAL_LOOP_SPEC.md; +7d/+7d after referred customer's clean
first paid month; do NOT build before launch blockers are green) ·
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

---

# THE ACTIVE PLAN (Stage 12+, started 2026-09-08)

Everything below is real, dated, and checkable — no item is aspirational
copy. Each stage names what's DONE, what's NEXT (autonomous, no gate), and
what NEEDS BREY (an account, a purchase, a judgment call only he can make).
Horizon tags (TODAY / THIS WEEK / THIS MONTH) are Brey's own asked-for
framing, layered onto the stage structure this file already uses.

## Stage 12 — Doctrine-locked product build-out — **ACTIVE**

**Objective:** the product doctrine (`docs/PRODUCT_DOCTRINE.md`, 9 amendments)
implemented end to end: real picks, ranked on case strength not price, with
an honest evidence-tier read, actually reaching the page.

**DONE (2026-09-08 → 09-09), verified live, not just tested:**
- Doctrine locked. Picks are the product; provability is the trust layer,
  not a substitute for it.
- `src/analysis/families.py` — family-aware agreement (amendment 9).
  Measured on the real ledger: 52 registered genomes collapse to a real,
  changing family count (30 as of 09-09) — raw system count would have
  overstated agreement by up to 2x on real selections.
- `src/engine/slip.py` — the published, ranked, evidence-tiered slip.
  Ranks on family agreement → signal depth → price standing LAST (price
  standing alone is what the old day-rank rule used, and `slate.py`'s own
  comment calls that "emphatically NOT an edge").
- Evidence tier (green/yellow/orange/red) — real inputs only (family count,
  signal-ladder rung), never a win probability. GREEN is deliberately rare
  by construction (the ledger's all-time ceiling is 3 families).
- Lineup cadence fixed. Three separate deploy-path bugs found and fixed
  before it actually ran in production (gate in a script CI doesn't
  execute → gate in the wrong branch's workflow file → missing cache
  restore). Forward-test decisions now freeze near when lineups post,
  not hours later.
- `REGISTERED_GENOME_COUNT` 12→40, `REGISTERED_F5_GENOME_COUNT` 4→12 (owner
  directive: too many empty nights). Not a lowered bar — same floors, more
  independent shots at them.
- Stand-down telemetry — why a game has no pick (`NO_LINEUP` vs
  `NO_SIGNAL`, a clock vs a verdict), on the page, not buried in a CI log.
- `engine slip` wired into all three production scripts. It had been built,
  tested, and had NEVER ONCE RUN in production before this was caught.
- **TONIGHT'S PICKS on the Today page.** Doctrine's own list of
  misalignments named "the picks are not on the page" as the single most
  damaging thing on the site. Closed.

**NEXT (autonomous, no gate — take the highest-value one):**
1. **Verify the cadence appends a slip AUTONOMOUSLY**, unwatched, overnight.
   As of 09-09 evening only one slip has ever been appended, and it was a
   manual `engine slip` run — the automated gate has correctly gone SKIP
   every slot since (no newer lineup than that manual run), which is
   plausibly correct behavior but has not yet been proven hands-off.
   Acceptance: `git log -- evidence/slips_v1.jsonl` shows a commit whose
   author is the forward-capture bot, not a manual run.
2. ~~CLV hardening~~ — **DONE (2026-09-09), committed `596ecae`.** Replay
   rows, unstamped rows and closing-board staleness are all excluded from
   the published rollup; `by_cohort` reads the real `evidence/slips_v1.jsonl`.
   Independent re-verification while committing found one more live
   violation nobody had caught: `is_publishable()` never checked system
   class at all, so 938 MARKET_REFERENCE + 469 CONTROL rows outnumbered 196
   genuine FORWARD_TEST rows 7-to-1 in what the code called "the published
   cut" — fixed, proven load-bearing (reverted, watched the test go red,
   restored). Published CLV is now 196 rows, 100% FORWARD_TEST. The honest
   read at that sample size is still "no signal yet" — the fix is about the
   number being trustworthy, not about it being good.
3. ~~The record strip pooled CONTROL/MARKET_REFERENCE into the headline~~
   — **PARTIALLY DONE (2026-09-09), committed `a1d2866`.** The strip's
   TODAY/LAST 7/LAST 30 windows are now FORWARD_TEST-only; the pooled view
   survives as `all_classes` for diagnostics, never the customer default.
   Corrected live number: LAST 7 DAYS 34-28-0 +1.06u (+1.7%), LAST 30 DAYS
   70-44-3 +19.71u (+17.3%) — against the pooled strip's -21.79u / -4.91u a
   customer was actually seeing. **Read this correctly:** a small,
   non-independent sample turning positive is not evidence of an edge —
   the same-day CLV check on 196 published rows found no signal. **STILL
   OPEN:** doctrine's actual design is an ALL-TIME, COHORT-based record
   (Top 3 / Top 5 / Published / Research, never a time window) — deferred
   because cohort tags only exist since `engine slip` went live today, so
   an all-time Top-3 query would return almost nothing. Revisit once a
   real week of cohort-tagged history exists.
4. **`opportunities.js`'s "TOP PLAY" still ranks on `price_standing_bps`**
   (execution quality) instead of the slip's case-strength ranking. Now
   that the slip is live, this component is redundant with — and
   contradicts — `TONIGHT'S PICKS`. Fold it into the slip or demote it to
   a clearly-labelled price board, never call it a pick.
5. The overlap-report generator has destroyed the 8,811→1,062-family
   result TWICE by overwriting it with "not yet computable" when a
   regenerable cache was merely cold. Make it refuse instead of downgrade.
   (`scripts/factory_masks_from_sweep.py` itself also still fails —
   `PlaceboError: a world needs at least one game` — despite intact
   inputs; diagnose before touching the generator.)
6. Homepage hardcodes "27 hypotheses pre-registered … zero surviving" as a
   literal string; `data/research/alpha_registry.jsonl` says 42. Derive it.
7. `#/billing` renders a raw JSON dump; `#/mybets` is an unstyled form that
   doesn't join to anything Bet Check produces. Both customer-reachable.

## Stage 13 — Turn on the learning loop

**Objective:** doctrine amendment 7 — "learn from post-game reasoning
failures" — stops being aspirational. This is the single highest-leverage
dormant asset in the codebase: fully built, never run.

**NEXT (autonomous):**
1. Evaluate `mechanism_predicates` post-settlement so a loss classifies
   `REFUTED` (the reasoning was wrong) vs `VARIANCE` (the reasoning was
   fine, unlucky). Measured 09-08: **0 of 624 reviews classified** — every
   settled bet in this project's history still reads `UNTESTED`.
   `src/review/postmortem.py` already runs its classifier over wins too
   (deliberately, to avoid a losses-only bias) — the wiring gap is at
   settlement, not a missing capability.
2. Run an actual falsification battery on the (now 52, previously 16) live
   genomes. Every scorecard on the ledger reads `battery_verdict: NOT_RUN`.
   "Forward test" currently means "staking and watching" — weaker than
   what the machinery already supports.
3. Feed REFUTED-classified genomes back into retirement
   (`lifecycle.py`'s `RETIRED` state), so `admit()`'s family-dedup gate
   keeps the live population honestly distinct over time instead of
   accumulating dead weight.

## Stage 14 — As-of family clustering (design pass)

**Objective:** amendment 9's discount, made time-consistent. Family
structure is measurably time-varying (23 families as-of 09-04 → 19 as-of
09-08 → 30 as-of 09-09, as the registered population and its forward
history both grew). Re-scoring an already-*frozen* pick with *today's*
clustering would be re-ranking history — amendment 8 forbids exactly that.
**Contained today:** each slip freezes its own `agreement` block including
`families_by_id`, so a published pick is reproducible from its own
artifact regardless of how the live population changes later. Needs a real
design pass before implementation, not a quick patch — this is a THIS
MONTH item, not a THIS WEEK one.

## Stage 15 — Distribution & commerce

**Objective:** a subscriber can actually pay, without an app-store
gatekeeper standing between the product and revenue.

**Autonomous (I can build these without you):**
1. PWA — manifest, service worker, icons. Installs to a home screen from
   Safari/Chrome, launches fullscreen, supports web push on iOS 16.4+. No
   store, no review, no commission. Roughly a day or two of real work
   against the existing no-build ES-module app.
2. Harden the signup → billing path already in the repo
   (`src/appstate/billing.py`, `pricing.js`) against the production domain
   once it exists.

**NEEDS BREY (an account or a purchase only you can make):**
1. A real domain + DNS, off `fly.dev` staging.
2. Stripe account live mode (currently the founding-beta price/plan code
   exists but has never taken a real card).
3. The go/no-go on a native App Store / Google Play wrapper. My
   recommendation stands from the earlier app-store discussion: web + PWA
   first, native only after the record is long enough to market on —
   shipping to review with 72 settled bets and no confirmed edge invites
   scrutiny of the claims, not just the binary.

---

## Horizon summary (Brey's own framing, mapped onto the stages above)

**TODAY / TONIGHT:** Stage 12 item 1 (prove the cadence is hands-off) is
pure monitoring — check back rather than re-running anything manually.
Items 5–6 (overlap-report bug, hardcoded hypothesis count) are small,
bounded, and safe to take right now if item 1 is just waiting on the
clock.

**THIS WEEK:** Stage 12 items 2–4 (CLV hardening + commit, cohort-split
record strip, retire the price-ranked "TOP PLAY") are the real priority —
they are what makes the record honestly *publishable*, which is the
product's whole claim to being different from every other tout. Stage 12
item 7 (the two undesigned routes) if time remains.

**THIS MONTH:** Stage 13 (turn on the learning loop — predicate evaluation,
a real falsification battery, retirement feeding back into the population)
is the highest-value research work available and has been fully built and
sitting idle. Stage 14 (as-of clustering design) follows once 13 is moving.
Stage 15's autonomous half (PWA) can run in parallel any time; its "needs
Brey" half is a standing ask, not a blocker on anything else.

---

## Stage 16 — Owner-approved roadmap, 2026-09-15 to 2026-10-15 — **ACTIVE**

Owner, 2026-09-15: "/plan for the rest of the night, the next day, the next
week and month and commit to roadmap that follows me for autonomous work."
Approved the same morning with these answers: **hourly scheduled runs**;
**pre-approved spend** = tennis odds history (~16k credits) and NFL odds
history (~8k) after the credit reset, and live in-play odds switched on
(300 credits a day hard cap); **per-sport subscriptions built this week,
charging nothing yet**; **NBA and NHL added as coming soon**.

Context docs: `docs/SITE_REDESIGN_2026-09-15.md` (redesign decisions),
`docs/STRATEGY_LAB_PLAN.md` (the $1,000 paper agents and sweeps),
`docs/PER_SPORT_PRICING_PLAN.md`, `docs/MANAGED_BETTING_AND_POOL_ASSESSMENT.md`,
`docs/TENNIS_FEED_DECISION_2026-09-15.md`, `docs/MULTI_SPORT_2026-09-14.md`,
`docs/PREREG_MULTI_SPORT_2026-09-14.md`.

### How a run works (the standing loop for Stage 16)

1. Pull. Read this stage, then the last two sections of
   `docs/OVERNIGHT_RUN.md` and `docs/DEBRIEF_LATEST.md`. If the capture chain
   or the daily loop escalated since the last run, that outranks the queue:
   diagnose, fix inside the rules, or record BLOCKED_HUMAN with the exact
   question.
2. Claim: pick the highest-value item that is OPEN and unblocked, set it to
   RUNNING with the date-time in Evidence, commit and push that first. A
   RUNNING item older than two hours with no newer evidence is reclaimable.
   Two runs never work one item.
3. Execute with the model rule: Haiku subagents for mechanical work, Sonnet
   for implementation, Opus only when a task fails twice or needs a design
   call.
4. Verify: named tests, then `python -m unittest discover -s tests -t .`
   (stdlib-only CI on 3.10 to 3.12); `tests/test_customer_language.py` and
   `tests/test_web_structure.py` for any page change; `scripts/publication_audit.py`
   before any "it is live" claim; open the staging page after a web change.
5. Commit by path (never `git add -A`; never `data/app`, never `data/raw`),
   rebase onto the chain's commits, push. Record evidence (commit, run id,
   numbers) in the item's row; set DONE or the blocker.
6. Append a dated section to `docs/OVERNIGHT_RUN.md`, write
   `docs/DEBRIEF_LATEST.md` (under 200 words, plain English, bad news
   first), commit, push.

**Hard stops, never done by a run:** production deploy; live Stripe charges
or price creation; access-control changes on production; doctrine edits;
spend beyond the pre-approved list and the envelopes (900/day capture,
300/day in-play, 5,000 floor); unsealing 2026-01-01 to 08-27; deleting data
or destructive git; secrets (Actions secret names only, never values);
purchases; anything marked BLOCKED_HUMAN. Evidence rules never relax:
pre-registration before evaluation, losers published, no promotion without
the full gate, no rescue by threshold change, point-in-time data.

### Queue (statuses: OPEN / RUNNING / DONE / BLOCKED_HUMAN / DEFERRED)

| Id | When | Item | Acceptance | Status | Evidence |
|---|---|---|---|---|---|
| R16-01 | Tue 9/15 | Commit this roadmap: Stage 16 here, pointer moved, `docs/ROUTINE_PROMPT.md`, `docs/DEBRIEF_LATEST.md`; `docs/AUTONOMOUS_PRODUCT_QUEUE.md` marked superseded | Committed, pushed, CI green | DONE | 2026-09-15 |
| R16-33 | **Tue 9/15, first** | **BALLDONTLIE 48-hour ALL-ACCESS trial harvest** (owner, 2026-09-15: "run that completely down ... use that for all sports"). Trial started about 2026-09-15 05:30Z and ends about 2026-09-17 05:30Z. Build `src/providers/balldontlie.py` (one client: raw key in the Authorization header, cursor pagination, 600 requests a minute pacing, 429 back-off, never a key in a URL or message) and `scripts/balldontlie_harvest.py` (resumable, per-sport endpoint plan from each sport's OpenAPI spec, gzip per file, manifest with sha256 and row counts) and `.github/workflows/balldontlie-harvest.yml` (dispatch; uploads the files to a GitHub release `balldontlie-harvest-2026-09`; commits only `data/historical/balldontlie/MANIFEST.json`). Priority order: tennis ATP+WTA matches all seasons, rankings by week, players, opening odds, match stats; NFL games and lines all seasons, team and player stats, injuries; MLB, NBA, NHL games and odds history, stats for the last five seasons. Dispatch the moment the secret exists; watch the run; re-dispatch until every endpoint plan is complete or the trial ends | Release assets with manifest sha256s; row counts per sport and endpoint in the manifest; request rate never over the plan's limit; zero key material anywhere | RUNNING | built and pushed 379cfff6 (client, harvester, workflow, 30 tests); workflow registered on the default branch b62763fb; smoke dispatch 34997664779 ran checkout and Python, stopped at "BALLDONTLIE_API_KEY is not set", release and commit steps skipped as intended; dry run plans 849 jobs, about 5,800 requests before pagination is known (10 to 60 minutes at the plan's pace); **blocked on the secret until the owner adds it**; then dispatch `gh workflow run balldontlie-harvest.yml --ref claude/sports-betting-analysis-review-g1o0co`, read the manifest, and add per-date sweeps for any odds endpoint whose unfiltered pull returned only current prices |
| R16-34 | **Tue 9/15, first** | **Card V2, best bets not best favourites** (owner, 2026-09-15 10:00am PT, with screenshots of today's card: Phillies -210 and Padres -186 published as "Take" with STRONG while their own copy says our number is below break-even; "the 3-10 bets for the day are the best of the best ... not any lower than -150 or -160 ... high-confidence and the value is great"). Diagnose why V1 publishes negative-expectation favourites; design a pre-registered successor rule (price band, likelihood floor, a value test that does not rank by the weak model's own disagreements, 3 to 10 picks with honest fewer-pick days), measure it only on data the evidence rules allow, adversarially review it, then build it as a new rule version with its own record (V1's record kept, never rescued) | Pre-registration doc committed before any evaluation; diagnosis doc; tests; no published pick priced worse than the band; copy never says "Take" on a side our own number prices below break-even; staging card verified at phone width | RUNNING | local session 2026-09-15 17:05Z (workflow: understand, design panel, adversarial review) |
| R16-35 | Tue 9/15 | **Live betting system for MLB, NFL and tennis** (owner, same message: "we need to find out how to make a live bet system and incorporate it into our MLB, as well as the NFL and tennis"). Inventory the live pipeline v0 (rules, in-play odds under the 300/day cap, runner, ledger, page), design the full system per sport (state feeds, in-play price source, trigger rules, pre-registration, forward-test ledger, customer surface, latency and suspension handling), and the build order | `docs/LIVE_BETTING_SYSTEM.md` with per-sport data sources and costs, pre-registered rule families, what is built vs missing, and queue items for the build | RUNNING | local session 2026-09-15 17:05Z (same workflow) |
| R16-02 | Tue 9/15 | **Owner:** add the `BALLDONTLIE_API_KEY` repository secret (Settings, Secrets and variables, Actions). Nothing here may enter the key for him. Then a run adds `python -m src.cli tennis results --date <yesterday>` (read-only) and verifies the feed on the runner | `gh secret list` shows the name; runner log shows result rows | BLOCKED_HUMAN | secret not set as of 2026-09-15 16:40Z |
| R16-03 | Tue 9/15 | Switch live in-play odds on (pre-approved): repository variable `LIVE_ODDS=1`; verify tonight's MLB window | `data/live/odds_inplay.jsonl` rows tagged `in_play` with `state_snapshot_id`; `live_odds` band at most 300 for the day; run green; `#/live` shows the games | RUNNING | `LIVE_ODDS=1` set 2026-09-15 16:35Z; verify after tonight's window |
| R16-04 | Tue 9/15 | Resume the site audit (`resumeFromRunId: wf_279c91fb-292`, 12 agents cached); apply the two challenges; save `docs/DESIGN_SYSTEM.md` and `docs/DESIGN_BUILD_PLAN.json` | Both committed; every high-severity finding maps to a build group; no file in two groups | DONE | 2026-09-15 17:20Z: 13 groups (shell split into foundation and chrome, gameday into card and page, per both challenges); independent check: no file in two owns lists, all 80 high findings closed by a real task id, depends_on consistent; two tests outside every group only mention web in a docstring or scan for Python imports (`test_market_from_the_board`, `test_ranker`), so redesign work cannot break them. **Overlap with R16-34:** group `copy-truth-sweep` rewrites `daily_card.CARD_BASIS` and `CARD_DISCLAIMER`; the card V2 build owns `src/analysis/daily_card.py`, so those two strings move into the V2 build and `copy-truth-sweep` keeps only `grade.legend()` and `daily_record` |
| R16-05 | Tue 9/15 | Redesign group 1, shell and shared: tokens, top strip with red "NFL · COMING SOON" and "TENNIS · COMING SOON" top right (sport switcher removed), dismissible news banner (four true items), sport level plus per-sport sub menu (MLB: GAMEDAY · MATCHUPS · PROPS · RESULTS; CHECK out of main nav; fixed check bar removed; Live out of public chrome), coming-soon page template at `#/nfl`, `#/tennis`, `#/nba`, `#/nhl`, shared header/section/button/state components | Structural tests updated deliberately; language and structure tests green; staging captures at 1440, 390, 360; old NFL and tennis links land on coming soon; `#/live` works by URL | RUNNING | build workflow wf_2100ea73-fd9 started 2026-09-15 17:25Z (foundation F-1..F-6, chrome CHR-1..CHR-9, integrate, independent check, fix); NBA and NHL registered as coming soon too; the "only the tab bar is fixed" check waits for gameday-page, which owns the fixed check band |
| R16-06 | Tue 9/15 | Clear the two standing daily-loop escalations without weakening anything: (a) wire `src/research/battery.run` into `src/engine/settle_slate.py` `build_scorecard` (Stage 13 item 1; 14 systems qualify); (b) acknowledged-escalations ledger `docs/ESCALATIONS.md` so the daily job fails only on NEW escalations; STRONG-tier drift stays open pending the tier-ladder pre-registration (needs 20 dates, has 5) | Next daily loop: scorecards carry battery verdicts; job green with the two known escalations acknowledged; a new escalation still fails (test) | RUNNING | (b) done 502368c1: `docs/ESCALATIONS.md`, `scripts/escalations.py`, workflow verdict step; scheduled copy on the default branch synced b0d73d8f (it had also fallen behind on cache paths and the intraday lineup restore); (a) battery wired into settlement 45aa0dad (123 tests); readiness audit made behavioural cba4ce88 (it escalates only while a ready system's newest scorecard still says NOT_RUN; still fires for all 14 today because the newest scorecards predate the wiring); **remaining acceptance: the next daily loop writes scorecards with real battery verdicts and the readiness line turns INFO, then mark the ledger row fixed and this item DONE** |
| R16-07 | Tue 9/15 | Create the hourly cloud routine (model claude-sonnet-5, prompt from `docs/ROUTINE_PROMPT.md`), smoke-test that it can pull, test, commit and push; record the routine link here | A routine run's commit on the working branch; its OVERNIGHT_RUN section; fallback recorded if push fails | RUNNING | routine created 2026-09-15 16:38Z: https://claude.ai/code/routines/trig_019zcK3KBNGsGasmTto1RPBw (the service pinned the schedule to minute 38 of every hour UTC; first fire 17:38Z is the smoke test; connectors removed so the run has repository access only) |
| R16-08 | Tue 9/15 | Hygiene: delete the 12 stray root `test_*.py` files, `test_output.txt`, `%SystemDrive%` and the one stray root file whose name begins `C` followed by a mangled scratchpad path and ends `money_usage.txt` (a worker wrote its scratch output to a bad path; all untracked, none referenced anywhere; a Linux run can delete them, the Windows session is denied deletes); the old `wt-default` worktree registration can be pruned with `git worktree prune`; held daily-loop repair stash stays held | Runner `git status` clean of strays | OPEN | |
| R16-09 | Wed 9/16 | Redesign page groups in parallel per `docs/DESIGN_BUILD_PLAN.json` (landing; gameday with the simplified compact card and "View breakdown"; matchups and results copy-truth only; props and odds; tools; account); re-capture every page at three widths; full suite; push | Every high finding closed or deferred with a reason; captures under `docs/design_audit/2026-09-16/`; publication audit clean | OPEN | |
| R16-10 | Wed 9/16 | Tennis on BALLDONTLIE: board matches from the feed where the odds board has none; grading path proven on the runner; retirement rule recorded in the pre-registration doc before any tennis pick is graded | Result rows for yesterday's matches in the runner log; rule recorded; no tennis pick published | OPEN | needs R16-02 |
| R16-11 | Wed 9/16 | Phase 0 data audits, tennis and NFL (`docs/PHASE0_TENNIS.md`, `docs/PHASE0_NFL.md`): field-by-field point-in-time check, outcome isolation on; backtest-safe vs forward-only fields named. No enumeration before this clears | Both docs committed with pass/fail per field | OPEN | |
| R16-12 | Wed 9/16 | Per-sport plans part 1, no charges: `src/appstate/plans.py`, entitlements keyed by Stripe subscription id, `LEGACY_INVITE_GRANTS`, per-route sport checks (`/today` and every MLB-only route fixed to mlb), public `/card/record` and `/card/history`, 402 body keeps `error`, `scripts/price_review.py` proposes only; Stripe price env vars unset | Pricing-plan tests 1 to 10 pass (shown failing first); `/ultra-review` or `/code-review` high on the diff before merge; staging unchanged for the public demo; owner told | OPEN | |
| R16-13 | Wed 9/16 | NFL: T-24h board for Thursday; `#/nfl` coming-soon text truthful; NFL card preview builds | Chain log shows t24h capture, 3 credits; `card publish --sport nfl --date 2026-09-17` prints a preview | OPEN | |
| R16-14 | Thu 9/17 | First NFL card published and locked (DET@BUF 5:15pm PT, lock 1:15pm PT); NFL live window under the cap; settle Fri; NFL record page internal only | Ledger row locked before kickoff; settle row Fri; credits within cap | OPEN | |
| R16-15 | Fri 9/18 | `src/research/matrix_tennis.py` (surface, H2H, serve from stored results) and `matrix_nfl.py` (closing lines; injuries forward-only) with first-seen stamps | Tests; Phase 0 verdicts respected | OPEN | |
| R16-16 | Fri 9/18 | `src/research/bankroll_paths.py`: the $1,000 paper agent per `docs/STRATEGY_LAB_PLAN.md` section 2 (real forward paths, busts carried at minus 100%, one headline window per sport, three stake fractions, non-overlapping window count, hidden under 5), quarantined from the gate | Tests; never imported by fitness, gates or battery | OPEN | |
| R16-17 | Fri 9/18 | Declare the month's sweep budget in the alpha registry (number of sweeps, family-wise budget) | Registry row | OPEN | |
| R16-18 | Sat 9/19 | Tennis pre-match sweep pre-registered with its minimum detectable effect, enumerated, placebo ceiling (CPU only); NFL recorded as forward-only this cycle (underpowered); weekend NFL boards | Registry row dated before the run; verdict doc | OPEN | |
| R16-19 | Sun 9/20 | NFL Sunday card published and locked per kickoff cluster; NFL live window 10am to 9pm PT under the cap; MLB live as usual | Ledger and live rows; credits | OPEN | |
| R16-20 | Sun 9/20 | Forward paper accounts open at $1,000 for every registered system in all three sports, decisions frozen before results | Paper account rows | OPEN | |
| R16-21 | Mon 9/21 | Settlements; sweep results published, losers included; $1,000 pages on staging, backtest-labelled, language-checked; `docs/MULTI_SPORT_WEEK1_REPORT.md` | Report committed; pages verified | OPEN | |
| R16-22 | Mon 9/21 | API-Tennis Business 14-day trial: start only if live tennis rules are wanted in October (owner); decide by day 12; NHL wiring begins | Owner call recorded | BLOCKED_HUMAN | default: skip unless the owner says start |
| R16-23 | ~Oct 1 | Credit reset check in the credit log before any historical purchase | Reset row; date in `docs/RESOURCE_POLICY.md` | OPEN | |
| R16-24 | Oct | NFL historical odds (pre-approved ~8k): one 30-credit call first; then 5 snapshots a week, 3 markets, 2023 to 2025; outcome isolation on; pre-registered families with MDE; publish losers | `docs/PREREG_NFL_SWEEP.md`; results doc; credits within estimate | OPEN | after R16-23 |
| R16-25 | Oct | Tennis historical odds (pre-approved ~16k): two snapshots a day, Slams and 1000s, 2021 to 2026; backtests; publish | Same pattern | OPEN | after R16-23 |
| R16-26 | Oct | NHL (opens ~Oct 7): BALLDONTLIE NHL provider, `icehockey_nhl` capture via the registry, coming-soon page, `NHL_CARD_V1` pre-registered, private forward test. NBA (~Oct 21): same with `basketball_nba` | Registry rows before first observation; capture rows with `sport`; truthful pages | OPEN | |
| R16-27 | Oct | Live tennis rules only if the API-Tennis trial passed every check and the licence is a written yes; else unsupported | New family with its own alpha budget, pre-registered | OPEN | after R16-22 |
| R16-28 | Oct | Per-sport pricing live only after the owner answers the 7 decisions in `docs/PER_SPORT_PRICING_PLAN.md` and creates the Stripe Prices | Owner action | BLOCKED_HUMAN | |
| R16-29 | Oct | Stage 13 continues: battery verdicts feed the population; retire failed systems; tier ladder recalibrated the day it is answerable (20 dates). Known gap found while wiring the battery (2026-09-15): the persisted scorecard now carries the battery verdict, but the in-memory promotion verdict (`settle_slate._fitness_for` via `build_fitness`) is still built without `research`, so it keeps reading NOT_RUN; close that gap here, with a test that the two agree | Scorecards with verdicts; promotion verdict and scorecard agree on the battery; ladder adopted or refused per its pre-registration | OPEN | |
| R16-30 | Oct | Stale-doc cleanup: `.claude/agents/*.md` (132/day, `.env`), `docs/RUNBOOK.md`, this file's Stage 1 grid figure, `docs/AUTONOMOUS_PLAN.md` "no spending" reconciled with `docs/RESOURCE_POLICY.md` | Grep finds no stale figures | OPEN | |
| R16-31 | Oct | Stage 15 autonomous half: PWA manifest and service worker. Production deploy, domain, live Stripe stay owner-only | Installable on staging | OPEN | |
| R16-32 | by Oct 15 | Monthly research report: every sweep, every null, credits spent, what is forward-testing; no edge claimed unless the full gate passed | `docs/RESEARCH_REPORT_2026-10.md` | OPEN | |

### Owner decisions still open (defaults in force until answered)

1. `BALLDONTLIE_API_KEY` secret (R16-02): nothing tennis-graded until set.
2. Pricing decisions 1 to 7 in `docs/PER_SPORT_PRICING_PLAN.md`: build proceeds
   with $19.99 floors and prices unset; nothing charges.
3. NFL pick floor: default none (max 5).
4. Doctrine amendment for multi-sport (`docs/MULTI_SPORT_2026-09-14.md`
   section 6): proposed, not applied.
5. API-Tennis Business trial ($80/month after 14 days): default skip unless
   live tennis rules are wanted in October.
6. Held daily-loop repair stash: stays held.
7. Production deploy, domain, live Stripe: owner-only.
8. Odds API plan tier and reset date: assumed monthly reset near the 1st.
