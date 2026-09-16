# Persistent roadmap

**The standing instruction:** on "continue autonomous work", find the current
stage below, take its highest-value unfinished item, and go. Update this file as
stages move. `docs/OVERNIGHT_RUN.md` is the running log; this is the map.

**CURRENT STAGE POINTER (updated 2026-09-15).** Stages 1–15 below are
history and context, kept for the audit trail, but NOT the active work
queue. Read `docs/PRODUCT_DOCTRINE.md` first (LOCKED, governs every product
decision), then resume at **Stage 17** at the bottom of this file: the week of
2026-09-16 to 2026-09-22, whose queue (ids `W-1` to `W-14`) an autonomous
run claims from. **Stage 16** above it stays live for everything dated
beyond this week and for its still-open owner decisions; Stage 17 takes
precedence where the two overlap. Stage 12's "ACTIVE" marker and Stage 9's "IN
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
| R16-33 | **Tue 9/15, first** | **BALLDONTLIE 48-hour ALL-ACCESS trial harvest** (owner, 2026-09-15: "run that completely down ... use that for all sports"). Trial started about 2026-09-15 05:30Z and ends about 2026-09-17 05:30Z. Build `src/providers/balldontlie.py` (one client: raw key in the Authorization header, cursor pagination, 600 requests a minute pacing, 429 back-off, never a key in a URL or message) and `scripts/balldontlie_harvest.py` (resumable, per-sport endpoint plan from each sport's OpenAPI spec, gzip per file, manifest with sha256 and row counts) and `.github/workflows/balldontlie-harvest.yml` (dispatch; uploads the files to a GitHub release `balldontlie-harvest-2026-09`; commits only `data/historical/balldontlie/MANIFEST.json`). Priority order: tennis ATP+WTA matches all seasons, rankings by week, players, opening odds, match stats; NFL games and lines all seasons, team and player stats, injuries; MLB, NBA, NHL games and odds history, stats for the last five seasons. Dispatch the moment the secret exists; watch the run; re-dispatch until every endpoint plan is complete or the trial ends | Release assets with manifest sha256s; row counts per sport and endpoint in the manifest; request rate never over the plan's limit; zero key material anywhere | RUNNING | built and pushed 379cfff6 (client, harvester, workflow, 30 tests); workflow registered on the default branch b62763fb; smoke dispatch 34997664779 ran checkout and Python, stopped at "BALLDONTLIE_API_KEY is not set", release and commit steps skipped as intended; dry run plans 849 jobs, about 5,800 requests before pagination is known (10 to 60 minutes at the plan's pace); **blocked on the secret until the owner adds it**; then dispatch `gh workflow run balldontlie-harvest.yml --ref claude/sports-betting-analysis-review-g1o0co`, read the manifest, and add per-date sweeps for any odds endpoint whose unfiltered pull returned only current prices **2026-09-15 19:35Z, secret is set and the harvest is live.** Run 35001607006 exposed the account serving ~5 req/min (free tier) against the 600 ALL-ACCESS should grant: every job took exactly 5 pages (per_page=100) then 429'd. Run 35002183724 (40 min, old client) still banked 17,736 rows / 77 release assets. Fix 79e28ccb (wait out 429s, newest-first, probe mode) was dispatched as run 35003755825 before anyone reviewed it; a 33-agent adversarial review then confirmed 14 findings, 5 critical, all reproduced by execution. Two were destroying the trial: (1) run_plan skipped any job with a recorded http_status, and the earlier failure had written http_status:429 onto 42 entries -- every ATP 2010-2026 and WTA 2016-2026 season -- so the live run was harvesting ZERO tennis; (2) a job exhausting its 900s 429 budget returned the same "partial" as a deadline hit and run_plan broke the whole run on it, capping every chained run at ~15 minutes of a 330-minute budget (measured: 383 of 849 jobs, then livelock on every subsequent run). Also fixed: chained runs never restored .jsonl.gz from the release so resumes rebuilt fresh files and --clobber overwrote longer assets; cursor persisted before the gzip flush; stale cursor replayed a final page; rankings probe resumed orphaned state and collapsed on an empty first probe; 429 loop bounded only seconds slept so a zero wait retried unboundedly. Fix pushed **fac6ef45** (40 regression tests, suite 7226 green); verified against the real manifest: 42 jobs re-enter (40 tennis), the two genuine 400s stay skipped. Follow-on run queued 19:35Z on the fixed code, behind run 35003755825 (ends ~23:47Z) via the concurrency group. **Standing instruction for every later run: while the trial is open (ends ~2026-09-17 05:30Z), if no balldontlie-harvest run is active, dispatch another one -- the harvest only completes by chaining.** **Open, and worth more than all of the above: the key is still served at 5 req/min. At 600 the whole plan finishes in ~20 minutes; at 5 it cannot finish at all. Owner to confirm the ALL-ACCESS trial is on the same account as the saved key and regenerate the key if so.** **2026-09-16 02:12Z:** the fixed run 35014512871 finished and the tennis blockage is gone. Manifest: 461 entries, 429 complete, **115,649 rows** (tennis 85,698, mlb 14,638, nfl 8,831, nba 6,482, nhl 0), 18 entries still at 429, 13 at HTTP 400, 1 partial. NHL returning 0 rows needs a look (offseason, or the wrong season parameter). No run was active, so run 35047119841 was dispatched at 02:12Z; the standing instruction to chain another whenever none is active still holds until the trial ends about 2026-09-17 05:30Z. |
| R16-34 | **Tue 9/15, first** | **Card V2, best bets not best favourites** (owner, 2026-09-15 10:00am PT, with screenshots of today's card: Phillies -210 and Padres -186 published as "Take" with STRONG while their own copy says our number is below break-even; "the 3-10 bets for the day are the best of the best ... not any lower than -150 or -160 ... high-confidence and the value is great"). Diagnose why V1 publishes negative-expectation favourites; design a pre-registered successor rule (price band, likelihood floor, a value test that does not rank by the weak model's own disagreements, 3 to 10 picks with honest fewer-pick days), measure it only on data the evidence rules allow, adversarially review it, then build it as a new rule version with its own record (V1's record kept, never rescued) | Pre-registration doc committed before any evaluation; diagnosis doc; tests; no published pick priced worse than the band; copy never says "Take" on a side our own number prices below break-even; staging card verified at phone width | BLOCKED_HUMAN | 2026-09-15 22:30Z: design phase done and committed. Five investigators, three designs, an Opus judge, synthesis, three adversarial reviews (51 findings, 13 high), a revision, an independent verifier (50 of 51 resolved, 6 new problems) and a fix pass (all closed; cross-document consistency script clean; 42 customer strings, 0 banned-word hits). Docs: `docs/CARD_V2_DIAGNOSIS_2026-09-15.md` (bad news first: V1's card calibration is refit nightly on every 2026 game from 04-15, 1,753 of 1,901 rows in the sealed window and 148 forward rows folded into tuning; DISPERSION and prop RHO were also fitted on sealed games; no recorded freeze or owner go), `docs/PREREG_CARD_V2.md` (**DRAFT, not registered**: rule `DAILY_CARD_BEST_BETS_V2`, price no shorter than -160, market and our number above 0.50, our number above the best price's break-even, our number within 10 points of the market's, no pick floor, ceiling 10, up to 3 close calls never called picks; on the 2026-09-15 board it would have published 0 picks as registered because the board was stale, or 2 with freshness set aside), `docs/CARD_V2_BUILD_PLAN.md` (about 19 to 21 sessions, including a free 2025 pitcher and bullpen backfill so the V2 fit uses 2025 only; at its pick rate the 300-pick verdict lands around August 2027). **Blocked on the owner's answers to PREREG section 15** (questions 1, 3 and 4 change what gets built) **and on a separate decision: whether V1's nightly calibration refit stops now.** No V2 code is built and nothing registers until then |
| R16-35 | Tue 9/15 | **Live betting system for MLB, NFL and tennis** (owner, same message: "we need to find out how to make a live bet system and incorporate it into our MLB, as well as the NFL and tennis"). Inventory the live pipeline v0 (rules, in-play odds under the 300/day cap, runner, ledger, page), design the full system per sport (state feeds, in-play price source, trigger rules, pre-registration, forward-test ledger, customer surface, latency and suspension handling), and the build order | `docs/LIVE_BETTING_SYSTEM.md` with per-sport data sources and costs, pre-registered rule families, what is built vs missing, and queue items for the build | DONE | 2026-09-15 22:30Z: `docs/LIVE_BETTING_SYSTEM.md` committed after adversarial review (18 findings applied), independent verification and a fix pass. Headline findings: the live pipeline has never run once (0 live-window runs, 0 `live_odds` credit rows) and the shipped code could not record a candidate even if it ran (section 2.3), so **R16-03's acceptance cannot pass as built; it is superseded by R16-L8**; no live rule has an observation; BALLDONTLIE is treated as unconfirmed at 5 requests a minute, NFL state defaults to The Odds API scores, MLB does not depend on BALLDONTLIE; the earliest a registered live rule could reach the full gate is 2028. The build queue R16-L1 to R16-L22 lives in that doc's build-order table (MLB fixes first, Wed 9/16 to Wed 9/23; NFL keys before Thursday's 5:15pm PT kickoff; tennis only after its feed decision passes); the hourly run works it from there. Owner questions in its section 8 (a 0.40 in-play likelihood floor; registering M2) default to no |
| R16-36 | Wed 9/16 | **Give `forward-capture.yml`'s chained "lineup-cadence" `engine slate` call its own Statcast bootstrap** (found by the hourly routine, 2026-09-15 19:30-19:57Z, diagnosing why `engine slate` refuses intermittently inside the forward-capture chain). Root cause: `forward-capture.yml`'s self-chaining dispatch (`scripts/capture_slot.sh`'s `chain_dispatch`, `CHAIN_BRANCH=claude/sports-betting-analysis-review-g1o0co`) re-invokes itself by `workflow_dispatch` against the working branch, and every such run's "Restore the daily loop's git-ignored inputs" cache step misses 100% of the time (`Cache not found for input keys: forward-capture-never-saved-<run>, daily-loop-data-`), even seconds after `daily-loop.yml`/`afternoon-slate.yml` saved that exact cache -- confirmed on runs 35012776181 (19:31Z) and its predecessors. Unlike `daily-loop.yml` and `afternoon-slate.yml`, `forward-capture.yml` has no `scripts/daily_bootstrap.sh` fallback step, so on every cache miss `src.engine.preflight` correctly refuses with "the matchup feature store (Statcast pitch backfill) has no coverage recorded at all" and the chained `engine slate` call silently no-ops (swallowed by forward-capture.yml's own `\|\| echo` and by `forward-capture.yml` having no ESCALATE-check step at all, so it never shows red). **Not touching**: the two real, customer-facing passes (`daily-loop.yml` 10:00Z, `afternoon-slate.yml` 15:40 UTC) run in a cache scope that does hit, are unaffected, and are what actually freezes and publishes picks -- confirmed by reading their own successful runs' logs (e.g. afternoon-slate run 35011990916, 19:10Z, exit 0). The only casualty is the newer *intraday* re-decisioning enrichment this chain was supposed to add on top (2026-09-14/15 work) -- it has likely never once succeeded since being wired in. Do **not** fix by pointing `CHAIN_BRANCH` at the default branch: diffed the two branches' copies of this workflow (`git diff origin/claude/cowork-session-migration-tn3sx2:.github/workflows/forward-capture.yml origin/claude/sports-betting-analysis-review-g1o0co:...`) and the default branch's copy predates the whole self-chaining/pace-job design -- dispatching there would run that stale copy and silently kill the 13-minute cadence. Do not add a bare `bash scripts/daily_bootstrap.sh` step either without first giving forward-capture its own same-branch-scoped cache to save the bootstrapped stores under: bootstrap's Statcast step alone is cheap (git-fetches the `data-seed/statcast` orphan branch), but the full script is measured at ~9-10 minutes on a cold miss, and this job's cache misses every single time today, so a naive add would make most of ~100 chained runs/day pay a 9-10 minute tax and likely back up or break the 13-minute cadence. Design and build: a working-branch-scoped cache (e.g. `forward-capture-historical-<run_id>` / restore-keys `forward-capture-historical-`) populated by a bootstrap step that only runs when the daily-loop-data restore already missed, saved forward so only the first chained run after a scope reset pays the cost; load-test the timing impact before trusting it in the live 13-minute chain | New cache/bootstrap step in `forward-capture.yml`; a chained run's "engine slate (lineup cadence)" step stops refusing on Statcast; measured added wall-clock per slot stays well under the 13-minute spacing; full suite green; the two core scheduled passes untouched | OPEN | diagnosed 2026-09-15T19:57Z by the hourly routine; see this date's `docs/OVERNIGHT_RUN.md` section for the full evidence trail (job logs, exact error text, cache-restore lines) |
| R16-02 | Tue 9/15 | **Owner:** add the `BALLDONTLIE_API_KEY` repository secret (Settings, Secrets and variables, Actions). Nothing here may enter the key for him. Then a run adds `python -m src.cli tennis results --date <yesterday>` (read-only) and verifies the feed on the runner | `gh secret list` shows the name; runner log shows result rows | RUNNING | owner set the secret 2026-09-15 17:28Z (`gh secret list` shows the name). Built `python -m src.cli tennis results --date` (37abe21f/9a366ed4, 5 new tests) as a thin wrapper on the already-tested `src/providers/tennis_results.py:results_for`; wired one read-only, never-escalating call of it into `scripts/daily_loop.sh` right after tennis discover (9a366ed4, 23 wiring tests); added a standalone `tennis-results-check.yml` for an on-demand check (727aff25) -- **not yet dispatchable**: GitHub only lists a workflow_dispatch target once the file exists on the default branch, and this routine may not touch that branch, so it needs the same one-line registration commit R16-33's harvest workflow got, from whoever has that access. Verified for real on a runner: dispatched `daily-loop.yml` (run 35022286676, 2026-09-15T20:55-21:05Z) and read its job log -- the new step ran and reported `ERROR: balldontlie API returned HTTP 429`, the same account-wide ~5 req/min throttle already tracked in R16-33, not a defect in this code (the command reached the vendor and reported the failure cleanly, no crash). So the literal "runner log shows result rows" half of acceptance stays open until R16-33's key/rate-limit question is resolved by the owner; everything within this item's own control is built, tested and confirmed reaching the real API. **Bonus finding from that same dispatch's log** (not part of this item, fixed in the same run since it was a live, repeating credit leak): `budget --probe tennis_h2h` was crashing on every real run (`AttributeError: 'list' object has no attribute 'get'`) because it fetches via `provider.fetch_odds()` (a LIST of events) but computed shape assuming a single-event dict -- crashing after a real credit was already logged and before `measured` could ever be set, so it would have silently re-spent a credit and crashed again every single day. Fixed in `_payload_shape` (a new `is_multi_event` aggregation branch) plus the test double that had been hiding this (its `fetch_odds` fake returned the wrong shape) -- f790ceef, 2 new tests, full suite 7237 green |
| R16-03 | Tue 9/15 | Switch live in-play odds on (pre-approved): repository variable `LIVE_ODDS=1`; verify tonight's MLB window | `data/live/odds_inplay.jsonl` rows tagged `in_play` with `state_snapshot_id`; `live_odds` band at most 300 for the day; run green; `#/live` shows the games | SUPERSEDED | `LIVE_ODDS=1` set 2026-09-15 16:35Z. Superseded 2026-09-15 22:30Z by R16-L8 in `docs/LIVE_BETTING_SYSTEM.md`: the live window has never run and the shipped code could not record a candidate even if it did (that doc, section 2.3), so tonight's window cannot meet this acceptance; R16-L2 to R16-L7 fix the pipeline first, and R16-L8 is the first verified MLB window |
| R16-04 | Tue 9/15 | Resume the site audit (`resumeFromRunId: wf_279c91fb-292`, 12 agents cached); apply the two challenges; save `docs/DESIGN_SYSTEM.md` and `docs/DESIGN_BUILD_PLAN.json` | Both committed; every high-severity finding maps to a build group; no file in two groups | DONE | 2026-09-15 17:20Z: 13 groups (shell split into foundation and chrome, gameday into card and page, per both challenges); independent check: no file in two owns lists, all 80 high findings closed by a real task id, depends_on consistent; two tests outside every group only mention web in a docstring or scan for Python imports (`test_market_from_the_board`, `test_ranker`), so redesign work cannot break them. **Overlap with R16-34:** group `copy-truth-sweep` rewrites `daily_card.CARD_BASIS` and `CARD_DISCLAIMER`; the card V2 build owns `src/analysis/daily_card.py`, so those two strings move into the V2 build and `copy-truth-sweep` keeps only `grade.legend()` and `daily_record` |
| R16-05 | Tue 9/15 | Redesign group 1, shell and shared: tokens, top strip with red "NFL · COMING SOON" and "TENNIS · COMING SOON" top right (sport switcher removed), dismissible news banner (four true items), sport level plus per-sport sub menu (MLB: GAMEDAY · MATCHUPS · PROPS · RESULTS; CHECK out of main nav; fixed check bar removed; Live out of public chrome), coming-soon page template at `#/nfl`, `#/tennis`, `#/nba`, `#/nhl`, shared header/section/button/state components | Structural tests updated deliberately; language and structure tests green; staging captures at 1440, 390, 360; old NFL and tennis links land on coming soon; `#/live` works by URL | DONE | 2026-09-15 21:15Z: commit 846218b0 (23 files), CI green, staging deployed. An independent checker found 1 high (a status-line observer loop that could lock the tab) and 5 medium (header status blanked, red labels not at the far right, rail sub-lines cut off, no gutter on coming-soon pages, skip link re-routing to Gameday); all fixed and re-checked. Browser evidence: local API at 1440 and 390; staging at 390 (strip shows only the wordmark and "NFL · COMING SOON", "TENNIS · COMING SOON"; tab bar GAMEDAY MATCHUPS PROPS RESULTS; news banner 1 of 4; footer summary as specified; no horizontal scroll; zero #/live links; `#/tennis/board` shows "Tennis is coming soon." with no numbers; `#/live` renders by typed URL). Three route tests that pinned the removed SECTION_LABELS table now pin its removal. Open for later groups: the fixed "Check a bet" band on Gameday (gameday-page); low findings (news link and footer disclosure under 44px, stale-status caution colour, game-hours-aware stale threshold, 48px primary button, tab bar still shown on #/live); NBA and NHL pages exist but nothing links to them (decision 4 names only NFL and tennis). Observed, not caused by this change: staging `GET /today` took about 17 seconds on one request, so Gameday sits on its loading panel meanwhile; two `/live` 502s during the post-deploy restart |
| R16-06 | Tue 9/15 | Clear the two standing daily-loop escalations without weakening anything: (a) wire `src/research/battery.run` into `src/engine/settle_slate.py` `build_scorecard` (Stage 13 item 1; 14 systems qualify); (b) acknowledged-escalations ledger `docs/ESCALATIONS.md` so the daily job fails only on NEW escalations; STRONG-tier drift stays open pending the tier-ladder pre-registration (needs 20 dates, has 5) | Next daily loop: scorecards carry battery verdicts; job green with the two known escalations acknowledged; a new escalation still fails (test) | RUNNING | (b) done 502368c1: `docs/ESCALATIONS.md`, `scripts/escalations.py`, workflow verdict step; scheduled copy on the default branch synced b0d73d8f (it had also fallen behind on cache paths and the intraday lineup restore); (a) battery wired into settlement 45aa0dad (123 tests); readiness audit made behavioural cba4ce88 (it escalates only while a ready system's newest scorecard still says NOT_RUN; still fires for all 14 today because the newest scorecards predate the wiring); **remaining acceptance: the next daily loop writes scorecards with real battery verdicts and the readiness line turns INFO, then mark the ledger row fixed and this item DONE**. **2026-09-15 ~21:50Z, hourly routine, diagnosis (no code change needed -- confirmed working as designed, not a bug):** dispatched `daily-loop.yml` (run 35022286676, 20:55-21:05Z, i.e. after 45aa0dad landed at 16:50Z) settled `--date 2026-09-14` again and every system printed `settled 0 new (N already settled)`. `src/engine/settle_slate.py`'s `run_settle` only calls `append_scorecard` "when this run actually settled something new", by design (idempotency), so an already-fully-settled window never gets a fresh row even after the battery wiring changes what that row would contain. Confirmed directly: `evidence/scorecards_v2.jsonl`'s last commit touching it is still `2f5e1d71` ("Daily loop 2026-09-15", 10:15:48Z, BEFORE the wiring), and the newest `window` on file for the top 5 ready systems (e5ff00d4b3899ccc, e7f41ed66082c279, 999a7baa84ce385c, e64c85130b4664cc, 8974e1cb85d58bcb) is still 2026-09-14 with `battery_verdict: NOT_RUN`. `daily_loop.sh` settles yesterday's date, so 2026-09-14 (closed before the wiring landed) can never get a new row; the first window settled for the first time after the wiring is 2026-09-15, which only becomes "yesterday" on the next calendar day's run (~2026-09-16 10:00Z). **No fix needed or possible today -- this is a one-calendar-day wait, not a defect.** Next run on or after 2026-09-16: re-check `research-readiness` in that day's `daily-loop` job log; if it reads INFO, mark this ledger row fixed in `docs/ESCALATIONS.md` and this item DONE. |
| R16-07 | Tue 9/15 | Create the hourly cloud routine (model claude-sonnet-5, prompt from `docs/ROUTINE_PROMPT.md`), smoke-test that it can pull, test, commit and push; record the routine link here | A routine run's commit on the working branch; its OVERNIGHT_RUN section; fallback recorded if push fails | DONE | routine created 2026-09-15 16:38Z: https://claude.ai/code/routines/trig_019zcK3KBNGsGasmTto1RPBw (the service pinned the schedule to minute 38 of every hour UTC). First fire 17:38Z smoke-tested clean: pulled the working branch, checked `gh`-less GitHub state via the MCP Actions tools (no NEW `ESCALATE:` beyond `docs/ESCALATIONS.md`'s two acknowledged rows -- confirmed against daily-loop run 34982129696's job log), claimed and completed R16-08, ran the full suite (7186 tests green) and `scripts/publication_audit.py` (clean), committed to the working branch (417cc92e, then this row), rebased on a concurrent push with no conflict, and pushed. Routine's pull/test/commit/push cycle works end to end. |
| R16-08 | Tue 9/15 | Hygiene: delete the 12 stray root `test_*.py` files, `test_output.txt`, `%SystemDrive%` and the one stray root file whose name begins `C` followed by a mangled scratchpad path and ends `money_usage.txt` (a worker wrote its scratch output to a bad path; all untracked, none referenced anywhere; a Linux run can delete them, the Windows session is denied deletes); the old `wt-default` worktree registration can be pruned with `git worktree prune`; held daily-loop repair stash stays held | Runner `git status` clean of strays | DONE | 2026-09-15T17:41Z (first live fire of the hourly cloud routine, R16-07): this runner's checkout is a fresh clone, so it never carried the described stray root files, `wt-default` worktree, or held stash in the first place -- `git status --porcelain` empty, `git worktree list` shows only the current worktree, `git stash list` empty. Nothing to delete here; the strays live only on whatever earlier local/interactive session's persistent disk created them, which this ephemeral container does not share. Every future hourly run starts from the same clean clone, so this class of stray never recurs through this routine. Full suite green (7186 tests, `python -m unittest discover -s tests -t .`), `scripts/publication_audit.py` clean. |
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
| R16-37 | Tue 9/15 | **`live_window.should_dispatch`'s "already running" check is cross-runner-blind, spamming a cancelled dispatch every ~13min for the life of every real live window** (found by the hourly routine, 2026-09-15 23:44Z, investigating why `live-window.yml` run history showed 7 dispatches in one hour, all conclusion `cancelled` with 0 jobs, right after R16-35/R16-03 turned live capture on). The real MLB window (run `35029678164`, dispatched 22:11Z by `capture_slot.sh`'s per-cycle check) is genuinely running fine -- confirmed via its job log, on step "Run live window" continuously since 22:12Z -- and is in no danger: `live-window.yml`'s `concurrency: {group: live-window-${sport}, cancel-in-progress: false}` protects an in-progress run from ever being cancelled by a new dispatch to the same group; only the newer, not-yet-started dispatch is what GitHub cancels. So this is not blocking tonight's window. The bug: `should_dispatch`'s default "is a window already running" check (`src/pipeline/live_window.py:501-514`) reads a local marker file (`data/live/<sport>/window.lock`) that the live-window job itself writes on ITS OWN ephemeral runner -- a file that can never exist on a *different* job's fresh checkout, such as the `forward-capture` chain's runner calling `--should-dispatch` every ~13 minutes. So the check always reports "not running" once a real window is active elsewhere, and `capture_slot.sh` (`scripts/capture_slot.sh:560-587`) dispatches a doomed duplicate every single cycle for as long as the real window runs (up to 330 minutes) -- 7 wasted dispatches and counting tonight, each immediately cancelled by the next. No credits spent, no billable runner time (`duration_ms: 0` on every cancelled run's job), and the real window is unaffected, but it is needless GitHub API traffic every cycle, permanent noise in Actions run history that could mislead a future audit into re-diagnosing this exact thing (as this run just did), and the same blind spot will misfire across sports once NFL live windows run too (R16-14 week). Fix: give the workflow a sport-bearing `run-name` (`live-window-${{ inputs.sport }}`) and make the default "running" check *also* ask `gh run list --workflow live-window.yml --json status,displayTitle` for any `queued`/`in_progress`/`waiting`/`pending`/`requested` run whose title matches this sport's prefix -- fails open (reports "not running") on any `gh`/network error, same as today's behaviour, so a check outage only costs one more harmlessly-cancelled dispatch, never a stuck HOLD | `should_dispatch`'s default check no longer relies solely on the single-runner-local marker file; new tests cover the gh-list check (match found, no match, wrong sport, non-active status, and `gh` failure all fail open); full suite green; `live-window.yml` run-name change does not alter its trigger, inputs, or concurrency semantics | DONE | Fixed `df85df78`: `run-name: live-window-${{ inputs.sport }}` added; `should_dispatch`'s default check now ORs the local marker with a new `_gh_run_active` (shells out to `gh run list --workflow live-window.yml --json status,displayTitle`, matches this sport's run-name prefix against any active-status run, fails open to "not running" on any error). 9 new tests (`TestGhRunActive` x7, `TestLocalWindowMarkerActive` x3, a `should_dispatch` default-wiring regression test); full suite 7279 green; `publication_audit.py` clean (one pre-existing, unrelated card-freshness WARN). Not verified live end-to-end against a real second dispatch (would mean waiting out a ~13-minute forward-capture cycle and reading its job log); next run should confirm the next `live-window.yml` dispatch for the still-active MLB window (run `35029678164` or its successor) prints `HOLD window already running` instead of spawning another cancelled run |

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

---

# Stage 17 — The week of 2026-09-16 to 2026-09-22: forward testing in three sports, and the strategy lab at its honest size

**Owner, 2026-09-16 (~05:20Z):** "plan for the weeka tnmous load, NFL, MLB,
Tennis forward testing all of it , 10.000s of stregies and analysis types etc
etc etc". Earlier the same night, after the home-underdog screen was killed:
"home undersog is a BEYOND IDIOTIC STRATEGY with no research behind it ... our
systems and analysis take into cosideration metrics and reccent histroy and
stats and mathcup and bullpen analysis and bench analysis and all the things a
backtest coudnt do so that makes sense."

He is right about the first half and half right about the second. Backing a
price band is not a strategy. A backtest **can** use matchup, bullpen, bench
and form, but only where a point-in-time value was stored, and for 2023 and
2024 this repo does not have one for starter and bullpen mechanics. That is a
data gap, not a law of nature, and closing it is free (item W-12).

## What "tens of thousands of strategies" actually means here

Measured 2026-09-16, not estimated:

| Fact | Number | Source |
|---|---|---|
| Genome space enumerated, MLB h2h, 6 registered features, max 3 signals | **11,088 candidates in 1.58 s**, 10.3 MB peak | `evolab.genome.enumerate_genomes` run live |
| The one registered sweep's declared candidates | 8,811 | `data/research/alpha_registry.jsonl` |
| Registry today | 47 hypotheses, 1 sweep, 2 audits, 42 verdicts read, **0 survivors** | same file |
| Newest research artifact other than the registry | 2026-09-06, ten days stale | `data/research/evolab/` |
| Floor before any verdict | 300 graded picks and 60 ledger dates, closing-line value primary | `docs/VALIDATION_CRITERIA.md` |

So enumerating tens of thousands of strategies is cheap and real: it is seconds
of CPU, and the placebo ceiling then ranks them against a scrambled-data noise
floor. **Reaching a verdict is the expensive part.** At 300 graded picks and 60
dates per surviving candidate, MLB and tennis can settle low single digits to
low tens of distinct strategies in a season, and NFL essentially none this
season without historical odds (272 games a season against a ~18,000-bet
requirement to see a 3-point effect). Enumeration count is not evidence, and
this file never presents it as evidence. What the lab produces weekly is: a
declared sweep, a placebo-ceiling ranking, published nulls, and a small number
of survivors entering forward testing with paper accounts.

**Theatre, named so nobody drifts into it:** quoting the 11,088 or the 8,811 as
"strategies tested"; drawing any return or closing-line verdict on fewer than
300 graded picks; or opening a $1,000 paper page as if it were evidence of an
edge. The paper pages show what betting a rule would have felt like, including
going broke. They never feed the promotion gate.

## Standing state this week (verified 2026-09-16 04:00 to 05:30Z)

- **Credits:** 20,059 remaining, floor 5,000, envelope about 900 a day, live
  in-play cap 300 a day. About 15,000 spendable this week without touching the
  floor; the binding limit is the daily envelope, not the balance.
- **Green unattended:** forward capture (self-chaining ~13 min), staging
  deploys, the hourly cloud routine, CI.
- **Red or blind:** the daily loop fails on its schedule and has succeeded only
  when dispatched by hand (W-1); the afternoon slate failed every run overnight
  on a date-basis bug (W-2, fix in flight); the live pipeline has never
  recorded a candidate row and cannot yet (W-5); `evidence/live_candidates_v1.jsonl`
  does not exist.
- **BALLDONTLIE trial ends about 2026-09-17 05:30Z.** 115,649 rows banked
  before the odds sweeps landed; the account is served at about 5 requests a
  minute, so only a fraction of the plan will finish (W-10).
- **Owner questions open:** card V2 questions 12, 13, 14; the live floor
  question; the seven pricing decisions. Defaults hold until answered, and no
  build that depends on an answer starts without it.

## The week, by day (Pacific)

| Id | When | Item | Acceptance |
|---|---|---|---|
| W-1 | Tue 9/16, first | **Make the daily loop green on its own schedule.** It settles picks, grades the record and writes the day's evidence; it has been failing on schedule since at least 9/13 and succeeding only on manual dispatch. Diagnose from the scheduled runs' logs, fix the cause, and prove it on a scheduled run, not a dispatch | Two consecutive scheduled runs green, with the escalation ledger showing only acknowledged lines | RUNNING | 2026-09-16 05:00Z: diagnosed. The last scheduled failure (34982129696, 09-15 14:30Z) escalated on exactly the two acknowledged lines and predates the ledger check, which landed at 502368c1 and was synced to the default branch at b0d73d8f. Verified locally: the two standing lines give exit 0 and a third, unknown line gives exit 1; the default-branch workflow's verdict step is `python3 scripts/escalations.py --check`. **Trap for the next run: a plain `git fetch origin <branch>` does not move the local `origin/<branch>` pointer, so reading the default-branch workflow through that ref shows a stale file. Read it from the sha `git ls-remote` reports, or fetch with an explicit refspec.** Proof outstanding: the 10:00Z scheduled run, then one more |
| W-2 | Tue 9/16 | **Afternoon slate date basis** (in flight): it asks for the UTC date while captures are keyed to the Eastern slate date, so every run between 8pm and midnight Eastern refuses on a day with no prices and fails the job. Fix the date, keep the freshness guard, and make "too early" an INFO line rather than an alarm | `bash -n` clean; new tests pin the Eastern date and both branches; the next overnight dispatches stop failing | DONE | 2026-09-16 04:55Z, commit 67d967a1: the slate date is now the America/New_York day in both `scripts/afternoon_slate.sh` and `scripts/capture_slot.sh`, the freshness guard is untouched, and a too-early state prints INFO and exits clean only when the store has no rows for that Eastern date and first pitch has not arrived. The chain carried the same defect in its lineup-cadence block, which ran every 13 minutes all night asking about tomorrow while publishing the card under today; that is fixed in the same commit. Six new tests |
| W-3 | Tue 9/16 | **Card V2 build starts** on the parts that need no owner answer: T1 pre-build checks, T2 the pure rule module, T3 the V2 ledger, T4 closing-line measurement, T2v the variant runner, T3v per-variant ledgers. Registration (T0) waits on questions 12 to 14 | Each task's named tests green; nothing registered; no customer surface changed |
| W-4 | Tue 9/16 | **Free 2023 and 2024 feature backfill** (starters, box scores, bullpen usage, confirmed lineups) through the repo's own StatsAPI path, the same way the results backfill landed. This is what turns the 2023-24 matchup matrix from mostly null into usable, and it is the only honest answer to "a backtest could not do that" | Matrix nulls for starter and bullpen mechanics fall materially; row counts and coverage published; no odds credits spent | **DONE, with its premise corrected** | 2026-09-16 06:00Z, commits dd94c4ca, fb475f40, b607014b. Ingested free from StatsAPI, no odds credits: results 2,430 (2023) and 2,427 (2024); pitcher logs 8,888 and 7,837; bullpen logs 20,723 and 20,720; lineups 2,440 and 2,434; box scores complete for 2023, 2024 and 2025 against every game in the results store, archived at 6.5 MB compressed rather than 78 MB raw. Every 2025 and 2026 row byte-identical to its restore point. **The acceptance criterion was wrong and is recorded as such:** `src/research/matrix.py` never reads the pitcher or bullpen logs, so its starter-mechanics nulls (platoon gap 51 per cent, velocity gap 33 per cent, groundball share 30 per cent in 2023) are gated by the Statcast pitch store, which is not even present on this machine, not by anything this item fetched. What the backfill did buy: lineup-shape and lineup-versus-starter-history features are now near zero nulls for both seasons, and the pitcher and bullpen logs feed the dossier, briefing, selections and mismatch paths. So the owner's matchup and bullpen analysis is now partly backtestable; the remaining gap is a separate Statcast fetch, filed as W-15 |
| W-5 | Wed 9/17 | **Live pipeline able to record** (R16-L2 to R16-L7): pre-game context and keys, in-play credit accounting from the response headers, the push path, rule-gated capture with freshness, ledger rows, settlement from authoritative finals | A real MLB window writes candidate rows with their in-play prices, inside the 300-credit cap, verified by a separate checker |
| W-6 | **Thu 9/17, kickoff 5:15pm PT** | **NFL forward testing begins**: Thursday card published and locked before kickoff, live window during the game under the cap, settled Friday morning. NFL stays internal and coming-soon on the site | Card row frozen before kickoff; live rows or an honest "no trigger fired"; settlement Friday; nothing published to customers |
| W-7 | Fri 9/18 | **Tennis forward testing**: results grading proven on the runner against yesterday's completed matches, the retirement rule recorded before any tennis pick is graded, and the board reads from the feed where the odds board has no price | Runner log shows graded rows; rule recorded; tennis still research-only |
| W-8a | Thu 9/17 | **Wire the sweep to the real stores.** `scripts/evolab_sweep.py` says in its own docstring that it is fixture-only and "NOT A REAL-STORE RUNNER YET"; the single real sweep on disk (8,811 candidates, 2026-09-06) was bridged by hand and left no repeatable path. Until this is a command anyone can run, there is no weekly lab. Wire it through `src/evolab/replay.py`'s point-in-time engine, with the sealed window refused by name as it already is, and have it write its artifacts and its registry row itself | One command reproduces the 2026-09-06 sweep's candidate count from the real stores; the replay engine still refuses the sealed window; an adversarial review of the wiring before any new result is read |
| W-8 | Fri 9/18 | **The lab's first repeatable sweep, declared before it runs**: one MLB sweep against the placebo ceiling with its alpha spend registered, the enumeration count published beside the verdict count so the two are never confused, and every null published. If W-8a is not finished, this becomes a null-result note rather than a rushed run | Registry shows the sweep row with its candidates; results doc lists survivors and nulls; no survivor skips the gate |
| W-9 | Sat 9/19 | **Build the $1,000 path engine and open paper accounts** for every registered system in all three sports. The engine does not exist yet: `src/accounts/paper.py` holds live paper wagers, but the path engine `docs/STRATEGY_LAB_PLAN.md` section 2 describes is unbuilt. Build it to that section exactly: $1,000 start, three stake fractions shown side by side, real calendar start points played forward in true order with no shuffling and no resampling, busts marked and carried at minus 100 per cent into every later window, and the count of genuinely non-overlapping windows printed beside every band, with bands under 5 windows hidden. The repo's own refutation doc names the trap: a wrapped bootstrap is a calendar that never happened | Pages render on staging labelled as paper, carrying the line that they are not evidence of an edge and cannot feed the gate; a test proves a busted path stays in the denominator |
| W-10 | Tue 9/16 to Thu 9/17 05:30Z | **Drain what is left of the BALLDONTLIE trial**: chain a harvest whenever none is active, newest seasons first, odds sweeps ahead of deep history | Manifest rows and release assets grow each run; a final row-count by sport recorded when the trial ends |
| W-11 | Sun 9/20 | **NFL Sunday cards and live windows**, MLB as usual, and the first cross-sport day the system runs unattended end to end | Every sport's cards frozen before their own kickoffs; credits within envelope; no manual intervention recorded |
| W-12 | Mon 9/21 | **The week's report**: what was forward tested in each sport, what the lab enumerated and what it settled, credits spent, every null, and what the evidence does and does not license | `docs/WEEK_2026-09-22_REPORT.md`, no edge claimed anywhere |
| W-13 | through the week | **Redesign groups 2 onward** (copy-truth sweep, gameday card, gameday page, landing, matchups, props and odds, tools, results, account), one group per session, in dependency order from `docs/DESIGN_BUILD_PLAN.json` | Per-group acceptance met; staging verified at three widths; language and structure tests green |
| W-14 | through the week | **Per-sport plans, part 1, no charges** (R16-12), built behind its tests with Stripe prices unset | Pricing plan tests 1 to 10 pass; checkout returns not-configured; nothing charges |
| W-15 | Wed 9/16 | **Statcast pitch store for 2023 and 2024**, the gap W-4 exposed: the matchup matrix's starter-mechanics nulls are gated by `data/historical/statcast`, which is absent on this machine and holds nothing for those seasons. Fetch it the repo's own way (find the builder, free source, point in time), then rebuild the two matrices and publish the before-and-after null rate per field | Matrix starter-mechanics null rates fall and are published per field; no odds credits spent; rebuild is deterministic and does not touch the sealed window | OPEN | |
| W-16 | Tue 9/16 | **The private in-play watcher** (`docs/SNIPE_SYSTEM.md`, committed 6b11a750): owner wants it watching tennis and NBA, paper only, on his always-on Windows desktop, alerting by push with a session page. Build order is that document's section 7, and its first two items are deliberately cheap kill switches: fix the live plumbing (W-5), then measure for a week whether our feed sees a state change before the books move | One real match watched end to end, one paper ticket written or an honest no-trigger, the ledger chain valid, one alert delivered, and nothing claimed about whether the bet was good | BLOCKED_ON W-5 | 2026-09-16: design committed; three owner decisions open in its section 0 (API-Tennis trial, price floor -150 versus -200, conviction label versus a shadow staked account) |
| W-17 | Tue 9/16 | **API-Tennis: decide before the trial key expires on 2026-09-18.** First pass measured (`docs/API_TENNIS_TRIAL_RESULTS.md`, commit a9b7477b): set betting quoted on 8 of 19 live matches against an 80 per cent threshold, the suspension flag wrong on 104 of 638 moments and always in the direction of showing a price while suspended, price latency median 23.6 seconds against a 10 second threshold, point log clean over 30 sets. Three checks need a longer run than one pass, so run the poller across a full day, then record a dated decision | `docs/API_TENNIS_TRIAL_RESULTS.md` carries a full-day sample for checks 7, 9 and 10 and a dated buy or skip; if skip, `docs/SNIPE_SYSTEM.md`'s tennis rule is narrowed to match winner on the face of the rule | OPEN | |

## What the hourly runner does with this

Same loop as Stage 16: pull, read this stage, claim the highest-value item that
is OPEN and whose day has arrived, set it RUNNING with a UTC stamp, do it,
verify against the acceptance column, commit by path, update the row, append to
`docs/OVERNIGHT_RUN.md` and rewrite `docs/DEBRIEF_LATEST.md`. A NEW escalation
outranks the queue. W-1 and W-2 outrank everything else until they are green,
because an alarm that fires every night is an alarm nobody reads.

## The honest limits of this week

1. Nothing published to customers gets a new claim. NFL and tennis stay
   coming-soon; the card keeps V1's rule until V2 registers, which needs the
   owner's answers.
2. No verdict will be drawn this week on any strategy, in any sport. The
   earliest honest read on the card's own plus-money class is months away, and
   the variant family's separation date is later still.
3. The lab's output this week is a declared sweep, a ranking against noise, and
   published nulls. That is the whole of it, and it is worth doing because it
   is what makes a later survivor believable.
