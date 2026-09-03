# Subsystem map — master plan and gates

Read 2026-09-03, branch `claude/sports-betting-analysis-review-g1o0co`, HEAD
against `docs/MASTER_PLAN.md` (973 lines, dated 2026-09-02),
`docs/LAUNCH_DECISIONS.md` (164 lines), `docs/ROADMAP.md` (413 lines),
`docs/ORCHESTRATION_DAY_2026-09-02.md` (283 lines),
`docs/RESEARCH_V6_CANDIDATES.md` (492 lines), `docs/MULTISPORT_AUDIT.md`
(338 lines), `docs/COMMAND_CENTER.md` (276 lines). Code checked against these
claims where cheap to verify; docstrings are not treated as evidence that
code runs.

Read-only. Nothing in `src/`, `data/`, or `docs/` other than this file was
touched.

---

## 1. What the master plan ALREADY commits to that matches the owner vision

These are places where the plan, on paper, already states the vision's shape
— whether or not the underlying capability is built yet is scored separately
in §2-3.

- **Units ledger / public record design** — MASTER_PLAN.md Appendix A
  (lines 758-798) specifies flat 1.00u risk, hash-chained append-only entries,
  five permanently separate series (backtest/OOS/sealed/forward/official),
  fixed display windows, "losers shown exactly like winners." This is a
  complete, owner-vision-aligned DESIGN. Nothing in `src/` implements the
  hash chain or the public pages (see §3).
- **Promotion standard (§27, lines 616-646)** — multi-dimensional: calibration,
  forward predictive performance vs the market's own price, realized returns
  at captured entry price, stability, drawdown, sample strength, and
  entry-vs-close demoted to "advisory, never sufficient alone" per Brey's own
  correction recorded in Appendix C's revision note (lines 839-842). This
  directly matches the vision's instruction that selection is never by
  bankroll alone and never by CLV alone.
- **Phase 1 packet (Appendix C, lines 837-973)** — a concretely scoped,
  owner-approvable build list (registry, calibration harness, ledger schema,
  capture expansion, Evolab v2 fitness, learnability audit) that is explicitly
  research-plane-only and customer-invisible, which matches the vision's
  "capture now, research later" principle and its instruction that the
  Ranker/Engine 2 stays gated.
- **Entry-vs-close as an early filter, not the definition of skill (§1 claim
  2, lines 30-51)** — this is the plan correctly refusing to let CLV become
  the promotion criterion, consistent with the vision's demand for a
  multi-dimensional bet rating (probability AND price) rather than a
  single-metric filter.
- **Multi-sport gate (§25, lines 566-591)** — an explicit 8-condition
  readiness gate before NBA, and MULTISPORT_AUDIT.md (a full module-by-module
  STRUCTURAL/PARAMETRIC/INCIDENTAL classification of `src/`, verified present
  and substantive at 338 lines) already does the architecture homework the
  vision asks for ("architecture reusable for other sports"). This is a real,
  non-trivial existing artifact, not aspiration — confirmed by reading it in
  full.
- **Whole-board search as an explicit failure mode named in the plan** — §12
  (Market-Selection Research Program) commits to ranking MULTIPLE markets
  (h2h, F5 h2h, totals, F5 totals, run line, props as capture accrues) by
  learnability, which is the mechanism the vision's "search the entire board"
  would need. But the audit itself (the Learnability Audit v1) has NOT been
  run — confirmed: `find docs -iname "*LEARNAB*"` returns nothing, and
  `grep -rl learnability src/` returns nothing but this planning doc and
  MASTER_PLAN.md itself (see §3).
- **Strategy factory shape (§13, Evolab)** — genome population, generation via
  grammar/mutation/LLM proposers, fitness NOT bankroll, global alpha registry,
  retirement with cause, all match the vision's GENERATE→TEST→SCORE→ATTACK→
  RETIRE→MUTATE→RETEST→PROMOTE loop conceptually. Evolab v1 (Phase 2B, 8,811
  genomes) is a REAL, EXECUTED instance of this loop — confirmed:
  `src/evolab/` exists with `decide.py`, `placebo.py`, `cscv.py`, `spa.py`,
  `bitsets.py`, `ceiling.py`, `genome.py`, `baseline.py`, `registry.py`,
  `replay.py` (1462 lines) all present per MULTISPORT_AUDIT.md's own read of
  them, confirmed by direct `wc`/`grep` above (`src/evolab/genome.py`
  present). It ran once, on one market (h2h), one fitness (movement), and
  returned `BELOW_PLACEBO_CEILING` — a genuine falsifiable result, not a
  stub.

## 2. Where the plan contradicts or under-scopes the vision

- **Static rules vs analyzer-backtest.** The vision explicitly rejects
  "a tester of static rules." The actual research program to date (V1, V2,
  V4, V5, the 8,811-genome Evolab sweep) is EXACTLY a tester of static,
  pre-registered detector-style rules against one market (full-game h2h
  moneyline) — confirmed in code: `src/detect/detectors.py:86-928` registers
  ten `Detector` subclasses (`ImpliedBullpenDisagreement`, `BullpenWorkload`,
  `StaleBook`, `StarterMismatch`, `PlatoonMismatch`, `ThinMatchupHistory`,
  `LineupVsStarter`, `TravelLoad`, `ParkAndWeather`, `BullpenExposure`,
  `PitchMixMismatch`), each a fixed threshold/comparison rule, not a learned
  or reconstructive model of "everything legitimately knowable." The plan's
  own §1 claim 1 (lines 16-28) narrates this honestly as a graveyard, but the
  PLAN DOES NOT PROPOSE building the vision's actual analyzer-as-decision-
  engine (a model or ensemble that ingests the full reconstructed context and
  outputs a probability) until "Model Advantage (M)" in §16, which is
  labeled REQUIRES RESEARCH+VALIDATION and has NO scheduled build item in
  Phase 1 (Appendix C.1's eight items are registry/calibration-plumbing/
  capture — none is "build a matchup probability model"). This is a real
  under-scoping relative to the vision: the vision wants the analyzer ITSELF
  backtested at decision time; the plan's nearest analogue (Evolab genome
  replay) tests hand-authored/generated FEATURE RULES, not a synthesized
  whole-matchup judgment.
- **Single market vs whole board.** Confirmed in code: `src/pipeline/
  mismatch.py:157-158,364-387` (`route_market`) chooses between exactly two
  markets, `MARKET_F5` and `MARKET_FULL` — the production scan path picks ONE
  market per game, not "search the entire board." `src/providers/odds.py:52,
  72,86` shows `SUPPORTED_MARKETS` = h2h/spreads/totals (full game) +
  h2h/spreads/totals (F5) + `pitcher_strikeouts` (listing only, per
  MASTER_PLAN.md line 157 "prop PRICES not captured — listing only"). There
  is no alt-lines, team-total, race-to-X, first-to-score, or derivatives
  market anywhere in the odds provider or the scan path. The vision's list
  (moneyline/RL/alt RL/totals/alt totals/team totals/margin/F5/first inning/
  pitcher props/batter props/derivatives/parlays) is roughly 15+ market
  families; the code touches 2 fully + 1 (props) at listing-only depth. The
  plan's own §12/§19 rank props (C1) and F5 (C2) as the priorities, which is
  directionally right, but nothing in Phase 1 actually adds market breadth
  beyond weather/listing-time/prop-price metadata capture — the "search the
  whole board" capability is not on any near-term build list.
- **LOCK concept.** The vision says "LOCKS = highest evidence/confidence
  class, criteria to be researched, not prohibited." MASTER_PLAN.md contains
  NO mention of "lock" as a rating tier anywhere (`grep -in "lock" docs/
  MASTER_PLAN.md` returns only "unlock conditions" for the Ranker gate and
  "lock-in" in LAUNCH_DECISIONS.md re: vendor choice — zero hits for a
  bet-confidence LOCK tier). §16's Bet Rating architecture (P/E/M/U
  components) has room for a LOCK tier to be defined later, but it is not
  named, scoped, or scheduled anywhere in the plan. This is a genuine gap:
  the plan neither builds nor explicitly defers-with-a-plan the LOCK concept
  — it is simply absent.
- **Parlays as their own scientific problem.** §18 (lines 458-472) is four
  sentences of sequencing logic ("single-leg models are prerequisites... then
  cross-game 2-leg... then SGP...") labeled LONG-TERM R&D with "the design
  decision now is only to capture what future parlay research cannot
  backfill" — i.e., no capture, no schema, no code. Confirmed in code:
  `grep -rl "parlay\|SGP\|sgp" src/` returns ZERO files. This is CLAIMED (a
  named section exists) but ABSENT (nothing built, nothing scheduled to be
  built, no data even flagged for immediate capture) — the vision treats
  parlays as needing joint-probability/correlation/SGP-dependence research
  NOW as a standing program; the plan defers it entirely past the 1000x
  horizon with no capture hook.
- **The whole-board opportunity scanner (Mode B).** §17 describes a staged
  ladder (Stage 0 Best Price Board LIVE → Stage 1 internal paper picks →
  Stage 2 labeled forward-testing → Stage 3 official). Stage 0 is confirmed
  real (`src/analysis/prices.py`, price-improvement board, per
  MULTISPORT_AUDIT.md's read: "fully sport-agnostic... carries over
  unchanged"). Stages 1-3 require a model (M component) that does not exist
  yet — so the scanner-sweeps-every-market vision (Mode B) is currently
  IMPLEMENTED ONLY as a price-comparison board on 2-3 markets, not as an
  opportunity-ranking system across the full market list. The plan is
  honest about this ordering but the READER of the vision document would
  expect "search the whole board... ask which market best expresses the
  advantage" to appear as a Phase-1-adjacent build item; it appears only as
  a Phase-2/3 consequence of the Learnability Audit + Evolab v2, both of
  which are themselves not yet run.

## 3. EXISTS / PARTIAL / MISSING / CLAIMED-BUT-ABSENT classification

### EXISTS (verified in code, not just docs)

- Point-in-time detector/matrix machinery, BH-FDR, clustered bootstrap,
  falsification battery (RULES_VERSION 2.0.0, frozen) — `src/research/
  battery.py` (524 lines, 0 baseball-specific hits per MULTISPORT_AUDIT.md),
  cited in MASTER_PLAN.md lines 128-133 and confirmed structurally present.
- Sealed 2026 holdout discipline and 2025-tuning-only rule — stated
  repeatedly in ROADMAP.md lines 17-24, 311-321 as a "Stage" gate; the
  gate's existence as an enforced convention (not code-enforced access
  control) is the honest characterization — it is a discipline, not a lock.
- Evolab chassis: `src/evolab/{decide,placebo,cscv,spa,bitsets,ceiling,
  genome,baseline,registry,replay}.py` all present (replay.py 1462 lines);
  ran a real 8,811-genome sweep (Phase 2B) with a placebo ceiling and
  produced `BELOW_PLACEBO_CEILING` — a genuine falsifiable result recorded
  in COMMAND_CENTER.md lines 171-176, 268-276.
- Global hypothesis registry — `src/research/alpha_registry.py` confirmed
  present, 471 lines, 23,596 bytes (verified via `ls`/`wc` above), matching
  MASTER_PLAN.md Appendix C.1 item 3's claim it exists ("migration of the
  four families, Phase 2B's 8,811 genomes, and the catalogue's 73 entries").
  This is a real Phase-1 item already landed, ahead of the packet's own
  framing of it as forthcoming — ORCHESTRATION_DAY_2026-09-02.md line 80-82
  confirms it shipped same-day (L13) with 40 hypotheses migrated.
- Per-market close identification for h2h/spreads/totals/F5 — confirmed via
  ORCHESTRATION_DAY_2026-09-02.md L17 (line 91) and MASTER_PLAN.md line
  846-859 (Appendix C.1 item 2), consistent between the plan and the
  orchestration log.
- Calibration MATH primitives — `src/core/calibration.py` (282 lines):
  `brier_score`, `log_loss`, `expected_calibration_error`,
  `max_calibration_error`, `reliability_curve`, `compare`, `score_all` all
  present and callable (confirmed via `grep -n "def "`). Wired into a CLI
  demo (`cmd_calibration_demo`, `src/cli.py` line ~1750) that runs on
  SYNTHETIC data only — `grep -rl "core.calibration" src/ scripts/` finds no
  caller against real predictions/paper picks. This is the harness's
  mathematical core, not yet a harness running against production output
  (there is no production-tier model to calibrate yet, which the plan itself
  states in §16: "Empty until earned").
- Multi-sport structural audit — MULTISPORT_AUDIT.md itself, 338 lines,
  module-by-module classification, read in full above; this is a complete,
  non-trivial deliverable that already exists and materially de-risks §25.
- Market list actually captured: h2h, spreads, totals (full game and F5) —
  `src/providers/odds.py` lines 48-95 confirm `DEFAULT_MARKETS = ("h2h",
  "spreads", "totals")`, `EVENT_MARKETS` = the F5 trio, plus
  `PROP_MARKETS = ("pitcher_strikeouts",)` present in `SUPPORTED_MARKETS`
  but per MASTER_PLAN.md line 157 captured as LISTING only, not price, under
  a policy gate.

### PARTIAL

- **Entry-vs-close spine** — built for h2h, spreads, totals, F5 per
  ORCHESTRATION_DAY_2026-09-02.md (L17, L18: "140 append-only rows" for
  spreads/totals backfill; F5 close coverage only 26/73 games — "not
  captured (listing only — policy-gated)" language does not apply here but
  coverage is explicitly "too young"). The MASTER_PLAN's Appendix C.4 gate
  requires per-market close-coverage-rate reporting, which the orchestration
  log's own numbers (h2h 70/73, spreads 70/73, totals 70/73, F5 26/73)
  satisfy in form but the F5 number is thin — PARTIAL, not EXISTS, for the
  full multi-market claim.
- **Prop-market coverage** — listing audit running (293-418 rows per
  MASTER_PLAN.md/ORCHESTRATION log), 7 books list pitcher Ks, but PRICE
  capture is env-gated/bounded (~18 credits/day, hard cap) and only just
  turned on 2026-09-02 (ORCHESTRATION_DAY line 223-225: "2 credits per
  hour... say stop if the policy line should have been signed first" — i.e.
  turned on ahead of formal sign-off, a process gap the log itself flags).
  This is a live but very young, single-prop-type (Ks only) capture — far
  short of the vision's full pitcher/batter prop list (outs, IP, hits, ER,
  walks, TB, HR, RBI, SB, H+R+RBI, alternates).
- **Calibration harness** — math exists (see EXISTS); the "harness" as a
  standing process that scores real model output on a cadence does not,
  because there is no production-tier model output to score yet. Correctly
  sequenced by the plan (§26: "no rating composite before calibration
  harness"), but the harness itself is inert until Phase 2/3.
- **Multi-sport readiness** — the AUDIT exists (structural homework done);
  none of the eight §25 gate conditions are met (no learnability audit
  running, no ≥60-day paper-pick ledger, no market having completed a full
  lifecycle). PARTIAL in the sense that the hardest planning artifact
  (the audit) is done, but zero of the eight gate conditions are satisfied.

### MISSING (vision capability with nothing in the code)

- Whole-board search / opportunity scanner across 15+ market families
  (moneyline, RL, alt RL, totals, alt totals, team totals, margin, F5
  variants, first inning, pitcher props beyond Ks, batter props,
  derivatives/race-to-X/first-to-score, parlays/SGP). Confirmed: `odds.py`
  supports 7 market keys total, 6 of which are h2h/spreads/totals ×
  full-game/F5, the 7th is Ks-listing-only.
  Product-side surfaces (Prop Finder, Parlay Lab per §2) are named in the
  vision-adjacent MASTER_PLAN §2 surface list but have zero corresponding
  code or even a design artboard reference found in this pass.
- Parlay/SGP anything — zero files matched `parlay|SGP|sgp` across `src/`.
- LOCK rating tier — not named anywhere in `docs/MASTER_PLAN.md`.
- Market Learnability Audit v1 — no `docs/LEARNABILITY_AUDIT_V1.md`, no code
  reference beyond the plan's own description of it as an upcoming Phase 1
  deliverable. Confirmed via `find`/`grep`, zero hits outside the two
  planning docs (this file and MASTER_PLAN.md).
- Recommendation ledger (product-grade: hash-chained, public-facing,
  versioned) — `src/pipeline/ledger.py` exists and is append-only with
  separate settlement fields (confirmed by reading its docstring/design,
  lines 1-33), but it is the RESEARCH-grade forward ledger the plan itself
  distinguishes from the product-grade descendant (§5: "the recommendation
  ledger... is its product-grade descendant. QUICKLY ADDABLE (schema now,
  used later)"). `grep -rl "hash_chain\|hash-chained\|prev_hash\|
  previous_hash" src/ docs/` returns ONLY `docs/MASTER_PLAN.md` — the hash
  chain is a design sentence, not a line of code, anywhere in the
  repository.
- A production-tier probability model (the "M" component of Bet Rating) —
  explicitly "REQUIRES RESEARCH+VALIDATION... Empty until earned" per §16;
  confirmed absent, and honestly labeled absent by the plan itself.
- DuckDB/columnar research mirror — explicitly DEFERRED past Phase 1 in
  Appendix C.1 item 1 (lines 846-852), with the plan's own justification
  (`data/` is 284MB, no bottleneck yet) — this is a documented, reasoned
  MISSING, not an oversight.
- Public performance/record pages — Appendix A design exists; no product
  surface, no public route, confirmed absent (COMMAND_CENTER.md's "NOT ON
  THE PATH" list line 36-38 explicitly excludes "public forward ledger"
  from the current critical path).

### CLAIMED-BUT-ABSENT (docs/plans/owner language implies exists but does not)

- "Hash-chained... ledger" (Appendix A, MASTER_PLAN.md line 770) reads as a
  present-tense design spec inside a document that elsewhere (Appendix C.1
  item 5) correctly labels the SAME thing as a Phase-1 schema-only build.
  A reader of Appendix A alone, out of context, would believe this exists
  today; it does not (see MISSING above). This is an internal-to-the-plan
  inconsistency in verb tense more than a fabrication, but worth flagging
  since the vision document treats "immutable public record" as a
  load-bearing near-term deliverable.
- "Analyze the matchup deeply... reconstruct everything legitimately
  knowable" (owner vision) vs. the actual Analyzer, which per
  MULTISPORT_AUDIT.md §1 (`analysis/matchup.py`, `detect/detectors.py`) is a
  fixed set of ~10 threshold-based detectors over a bounded feature set
  (bullpen workload, platoon, pitch mix, park/weather, thin history, stale
  book, travel) — real and useful, but materially narrower than "everything
  legitimately knowable" (no confirmed-lineup-vs-injury cross-check beyond
  what's listed, no TTO measurement in production — TTO is explicitly
  "approximated" and flagged in RESEARCH_V6_CANDIDATES.md C5 as not yet
  measured directly, no umpire tendency modeling — C7 rejected specifically
  because the umpire SOURCE is unverified, no catcher framing, no batted-ball
  aggregates in production — MASTER_PLAN.md §11 lists these as BUILD items
  #3/#4, not yet done).
- The vision's implication that this is already "an AI-powered... analysis
  engine" doing AI-driven reconstruction — the actual system is
  deterministic Python detectors + a frozen statistical battery + LLM
  agents used for ORCHESTRATION/PROPOSAL (§20), not for the per-game
  analysis itself. §20 (AI Agent Architecture) is itself aspirational: "the
  hypothesis-proposer's value is measured (do agent-proposed genomes
  outperform grammar-enumerated ones per unit cost? — itself an
  experiment)" — i.e., this has not been tried yet, only proposed as an
  experiment to try.

## 4. Owner constraints that are load-bearing (and confirmed still active)

- **Tier A/B rating gate** — confirmed live in COMMAND_CENTER.md line 198-199
  ("nothing computes a rating, probability, rank or edge; the Ranker gate
  holds; V2-35 stays Tier B") as of the most recent orchestration entry.
- **Ranker / Engine 2 gate** — confirmed in code: `src/report/ranker.py`
  line 35 `ENGINE2 = None`, line 103 asserts `ENGINE2 is None or
  _engine2_unlocked()`, and line 20 states a test pins this structurally.
  This is a code-enforced gate, not just a documentation promise — the
  strongest verified constraint in the whole audit.
- **2025 tuning-only / sealed 2026** — a documentary/procedural discipline
  (ROADMAP.md Stage 4-6), not a code-level access lock; its integrity today
  rests on the team not opening the sealed window, which the plan
  acknowledges is a HARD APPROVAL GATE requiring Brey's explicit go
  (ROADMAP.md line 335: "Autonomous: NO").
- **No real-money bet placement** — stated repeatedly (ROADMAP.md line 21-22,
  MASTER_PLAN.md throughout); no code path found that would place a bet
  (the whole `src/` is analysis/capture/research, no broker/book API
  integration).
- **Losers published** — the graveyard/catalogue convention (73 classified
  ideas, MASTER_PLAN.md line 146) and the Appendix A "losing categories
  render exactly like winning ones" design commitment are consistent with
  each other and with the vision's requirement; the PRODUCT-side rendering
  of this (a public page) does not exist yet (see MISSING above), so the
  discipline is real in research but not yet productized.

## 5. BOOST vs REPLACE per component

- **Detector/battery/falsification machinery** — BOOST. It is the single
  most valuable asset per the plan's own §4 and this audit's verification;
  extending it (more markets, more feature families) is strictly additive
  and the architecture (registry pattern, `Finding`/`Dossier` sport-neutral
  contracts per MULTISPORT_AUDIT.md §3) already supports it.
- **Evolab** — BOOST, but the fitness function must change (per §5/§13: away
  from bankroll-tournament, toward calibrated log-loss + price-vs-close +
  robustness), and market coverage must expand beyond h2h. The chassis
  (replay/registry/placebo-ceiling) is sound and proven; only the genome
  grammar and fitness need extension, not a rewrite.
- **Odds/market provider layer** — BOOST for h2h/spreads/totals (cheap to
  extend per-market per MULTISPORT_AUDIT.md's "PARAMETRIC — cheapest
  provider to port" verdict on `odds.py`); but the prop/parlay/derivatives
  layer is effectively a REPLACE-from-zero build, since `PROP_MARKETS` today
  is a single-tuple placeholder (`("pitcher_strikeouts",)`) with no schema
  for the dozen other prop types the vision names, and there is no
  SGP/parlay schema at all.
- **Analyzer (detectors.py, matchup.py)** — BOOST in the near term (it is
  real, tested, sport-neutral at the contract layer per MULTISPORT_AUDIT.md
  §3), but the vision's "AI-powered... reconstruct everything knowable" goal
  ultimately requires a REPLACE at the decision layer: today's detectors are
  independent threshold rules, not a unified probabilistic model that
  synthesizes all sections into one calibrated judgment. The plan already
  recognizes this distinction (§16's "M — Model Advantage" is explicitly not
  the same object as the Analyzer's evidence findings), so the REPLACE is
  planned, just not scheduled.
- **Recommendation ledger** — BOOST (schema extension of the existing
  research ledger, per §5's own framing: "QUICKLY ADDABLE (schema now, used
  later)"), not a rewrite — the append-only/settlement-separation design
  already matches what the product-grade version needs; hash-chaining and
  a public derivation pipeline are additive.
- **LOCK concept / parlay research** — REPLACE-from-nothing (net-new; no
  code or schema to extend).
- **Market Learnability Audit** — net-new (a document + measurement script),
  not a boost of anything existing, though it consumes existing capture
  data.

## 6. Data that becomes unrecoverable if not captured now

Per MASTER_PLAN.md §3/§19 (data roadmap) and confirmed by the orchestration
log as either already running or explicitly gated:

1. **Prop prices, forward** (pitcher Ks only today, listing+price both live
   at ~18cr/day cap) — every day not captured is a day of point-in-time prop
   pricing lost forever; historical purchase cannot substitute (PIT-honesty
   requirement). Currently PARTIALLY protected (Ks only, live since
   2026-09-02); the vision's full prop list (batter props, alternates, other
   pitcher props) is NOT being captured and each day of the live season
   without it is unrecoverable for those specific markets.
2. **Weather forecasts, forward** — confirmed live (open-meteo, $0,
   MULTISPORT_AUDIT.md/ORCHESTRATION_DAY L4) — protected.
3. **Listing/repricing timestamps across all markets** — partially wired
   (prop-listing audit running); not yet extended to every market the
   vision names (alt lines, team totals) — those markets' repricing history
   is being lost daily since they are not captured at all.
4. **Umpire assignments** — live since 2026-09-02 (L11), a genuinely
   time-sensitive free feed; protected.
5. **F5 closes** — accumulating (26/73 games has a captured close per the
   orchestration log; coverage still thin) — every day of live season without
   denser F5 capture is lost F5-specific point-in-time data, called out
   explicitly as a priority in the plan's own ready queue.
6. **Batter-side and full pitcher-prop-type prices** (TB, HR, RBI, hits,
   walks, Ks-alternates, SB, H+R+RBI) — NOT captured at all today; this is
   the largest unrecoverable gap relative to the vision's stated market list,
   and is not on the near-term (Phase 1) capture list beyond the single Ks
   line.
7. **Parlay/SGP prices** — not captured, not scheduled; per §18 this is
   explicitly deferred, meaning any SGP correlation research on the current
   live season's book behavior is permanently unrecoverable once this season
   passes, since SGP pricing behavior is not point-in-time reconstructible
   after the fact.

---

## Bottom line

The plan is honest, evidence-driven, and internally consistent about its own
narrow research history (four dead full-game-h2h families, one real
placebo-ceiling result). It correctly diagnoses that markets beyond h2h are
under-explored and prioritizes props/F5 accordingly. But relative to the
owner's full vision — an AI analysis engine that reconstructs everything
knowable and searches the ENTIRE board including 15+ market types and
parlays — the actual code and the actual Phase-1 plan cover: 3 market
families in real price depth (h2h/spreads/totals, full game + F5), 1 prop
type at listing-plus-thin-price depth, 0 parlay/SGP infrastructure, 0 LOCK
concept, and a "search the whole board" scanner that today is a two-market
router (`route_market`) rather than an exhaustive multi-market sweep. The
plan's own Phase 1 (Appendix C) does not close this gap — it builds
infrastructure (registry, calibration math, ledger schema, mirror-deferred)
that is a PREREQUISITE for eventually closing it, not the market-breadth
work itself. The single largest under-scoping relative to the vision is
market/prop/parlay breadth; the single largest already-matching strength is
the falsification/registry/promotion-gate discipline, which is exactly the
machinery the vision's "thousands of competing systems" ambition would need
and which already exists and has been exercised for real (Phase 2B).
