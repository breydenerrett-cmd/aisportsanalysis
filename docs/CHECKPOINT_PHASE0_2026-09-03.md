# Phase 0 proof-of-function checkpoint (2026-09-03, HEAD after the W6/W11 merges)

Owner request: prove what the engine, paper accounts and Strategy Factory can
really do on the merged head; do not confuse scaffolding with functionality.

Evidence: five reader reports with pasted command output and file:line cites
under `docs/planning/checkpoint-2026-09-03/` (A engine, B markets + accounts,
C factory + fitness, D matchup matrix, E autonomy) and the adversarial review
`F_review.md` in the same directory. The demo scripts that produced the
outputs are beside them. This file is the synthesis; where it and a report
disagree, the report's pasted output wins.

Honest headline: the machine is roughly a third of the owner's end-to-end
milestone. The measurement, capture and settlement substrate is real. The
decision engine runs on real prices but reads no matchup features on a live
slate. The paper account works but nothing feeds it. There is no Strategy
Factory loop: enumeration exists, mutation, retirement and replacement do not.

---

## 1. WHAT WORKS NOW (real code, exercised on real data in this checkpoint)

- Engine pipeline `analyze()`: PROPOSE → PROJECT → ATTACK → RATE → RANK
  produces structurally valid DecisionRecords on real captured prices with a
  real de-vigged consensus and friction; the four adversaries fire (A §Q6).
- Price surface for four markets: full-game moneyline, run line, game totals
  and F5 moneyline are captured live, projected into L1 (56,680 observations),
  settled by tested rules, and paper-bettable (B matrix).
- Paper account loop steps 1–10: bankroll, several wagers from real rows with
  book/market/selection/line/price/timestamp preserved, settlement from real
  results, bankroll/units/ROI/drawdown, hash-chained immutability with a
  hand-tamper caught at the exact line (B §Q3 demo output).
- Historical replay on the 2023 universe through `src.evolab.replay` +
  `decide_with_reason`: real features, 19 books of prices, a real decision, a
  real settlement (a loss), labelled DEGRADED_INFORMATION (A §Q5).
- Truncation differential gate G4 on 8 real 2026-09-02 games: every price
  change between t−2h and t attributed to a provenance arrival; PASS.
- Research machinery: FDR (Benjamini–Hochberg), CSCV, SPA, the versioned
  falsification battery, CLV kept distinct from late_move (C §Q8).
- Capture substrate: hourly odds/watch/umpire/weather, batter props (5
  credits/event measured pre-game), derivative probes measured (team totals
  1, alternates 2, F5 trio 3), raw L0 files, budget guards, cadence SLO.
- Gates/fitness/accounts as pure, tested functions: `gate_ladder`, pinned
  LOCK criteria, `promotion_verdict` refusing bankroll-only positives (tests
  pass; C).

## 2. WHAT IS PARTIAL

- `analyze()` on a live slate sees NO matchup features: `PriceBlindSnapshot.
  features == {}` because there is no event_id → game_pk join for unfinished
  games, so `as_of` is skipped (A truths 2, 4; glue.py). The only production
  system wired is `TrivialAlwaysHomeSystem` (fixed p_model 0.52). The evolab
  adapter always reports p_model None, so evolab candidates rank last.
- `known_at_grade="A"` is emitted when no as_of read happened at all, and the
  live demo decided on an in-play board because nothing checks first pitch
  (§7 bugs 1 and 3). Both are correctness bugs on the decision path.
- Historical replay and live use DIFFERENT paths: replay calls
  `decide_with_reason` on matrix rows; live calls `analyze()` on L1 rows with
  an empty snapshot. Same decision primitive underneath, not the same engine.
- Markets: alternates, team totals, F5 run line and F5 totals have capture
  code, measured costs and settlement rules but zero captured rows yet
  (switched on this morning; first slot 16:35Z). Props: batter hits, total
  bases, home runs, RBIs, H+R+RBI have rows (12–202 each); pitcher
  strikeouts have rows; batter runs returned no rows on the probe event.
- Prop settlement is broken end to end: `settle.settle()` calls the
  registered prop rules with the wrong signature and raises TypeError (B
  truth 2). Rules exist and pass their own tests; the dispatcher does not.
- Paper loop steps 11–12: ReviewRecord (second verdict after new
  information) is constructed only in tests; price-vs-close comparison
  exists in code (`closing_observation`, CLV in grading.py) and a 2026 F5
  close store exists, but no live game carries a game_pk, so every forward
  ledger row's closing field is null (B truth 9, corrected by F).
- Fitness: units, ROI, bankroll, drawdown, hit counts exist in
  `accounts/paper.py`; CLV, calibration, FDR, battery survival exist in other
  modules; NOTHING assembles them into a `Fitness` object, so
  `promotion_verdict` has never been called outside tests (C §Q8).
- Autonomy: every cadence is a Claude Routine calling a one-shot script; the
  GitHub Actions capture workflow cannot fire until the owner adds the
  secret and repoints the default branch (E).

## 3. WHAT DOES NOT EXIST

- Mutation, crossover, retirement, replacement, scheduled retest:
  `enumerate_genomes` is exhaustive enumeration; grep finds mutation only in
  comments about a future phase (C stage table). The Strategy Factory loop
  GENERATE→…→RETEST is: GENERATE working (enumeration), ANALYZE SLATE working
  as a batch sweep, SELECT BETS not built as a stage, PAPER WAGER scaffold
  with zero callers, SETTLE working in a separate pipeline, SCORE scaffold,
  RETIRE / MUTATE / CREATE REPLACEMENTS not built, RETEST partial (ad hoc).
- Feature pipeline into the engine: starting pitcher metrics, bullpen,
  offense, handedness, park, weather, recent form, player data reach the
  Analyzer (brief) and the research matrix, never `analyze()` (A, D).
- Markets with no code at all: F5 team totals, race-to-X, generic parlays,
  prediction-market contracts. Same-game parlay is BLOCKED by design.
- Stake sizing, p_model intervals, price-improvement bps in the engine are
  hard-coded null/0.0 (A truth 10). Volatility, average odds, season/month
  stability, market stability metrics: no code anywhere.
- End-of-day self-review and daily slate analysis through the engine: the
  daily loop never touches src/engine, src/factory or src/accounts.
- Any process that would keep running for seven days without Claude: none
  except the already-deployed web app on Fly (E).

## 4. DEMONSTRATED END-TO-END PATH (what actually ran)

Current slate (A §Q6): L1 rows for one 2026-09-02 game → `glue.build_board`
→ empty `PriceBlindSnapshot` → `TrivialAlwaysHomeSystem` proposal → projection
onto h2h selections with real consensus/friction → adversaries (ThinBoard,
DegradedInformation vetoes/counterarguments) → one DecisionRecord with
p_model 0.52, stake null, price improvement 0.0.

Historical (A §Q5): 2023 game 718781 from the sealed replay universe →
matrix features (lineup platoon signal) → `decide_with_reason` picks SF →
real 2-book prices → result NYY 5-0 → loss settled → labelled
DEGRADED_INFORMATION.

Paper loop (B §Q3): PaperAccount(1000) → wagers from real h2h/totals rows →
settled from real results → bankroll/ROI/drawdown → chain verified → tamper
detected by line number. Stops at step 11 (no ReviewRecord producer) and
step 12 (close comparison unreachable without a game_pk on live rows).

None of the three is one shared engine yet. The seam is exactly:
`glue.build_snapshot` needs a matrix-backed feature builder plus an
event_id ↔ game_pk join; the replay path needs to call `analyze()` through the
adapter instead of `decide_with_reason` directly; and nothing routes
DecisionRecords into `PaperAccount`.

## 5. THE NEXT VERTICAL-SLICE BUILD (shortest path, ordered)

Milestone: one slate → the same engine analyzes every matchup, inspects every
supported market, selects candidates, places them into simulated accounts,
freezes recommendations, settles later, updates fitness, writes an EOD
self-review. Four supported markets are enough (h2h, spreads, totals, F5
h2h); props join when the dispatcher is fixed.

1. Event ↔ game join (S1). Persist `game_pk` on every PriceObservation using
   the schedule provider (teams + commence_time), backfill L1. Unblocks
   `as_of` on live games. Test: zero null game_pk on a captured slate.
2. Feature builder (S2). `glue.build_snapshot` reads the same matchup-matrix
   feature functions (`src/research/matrix.py`) for a live game through
   `as_of`, and the replay path builds its snapshot through the same
   function. Test: for a 2023 game, snapshot features equal the matrix row.
3. One path (S3). Replay calls `analyze()` via `EvolabGenomeSystem` and the
   equivalence script asserts identical decisions to `decide_with_reason`.
   Live and replay then differ only in the store `as_of` reads.
4. Engine correctness (S4). Fix §7 bugs 1–6: grade fails closed, first-pitch
   guard on t, book_count/dispersion/best computed across books AT t, prop
   dispatcher signature with a test that goes through `settle.settle()`,
   event component in selection_id.
5. Slate runner (S5). `python3 -m src.cli engine slate --date D` runs
   `analyze()` for every game and every captured market, writes frozen
   DecisionRecords to the v2 chain, and places FLAT_1U paper wagers into one
   PaperAccount per registered system (start: the trivial system as a null
   control plus a handful of enumerated genomes). No Bet Rating, no
   probability published where p_model is None.
6. Settle + score (S6). `engine settle --date D` settles the day's paper
   wagers from results/boxscores, writes ReviewRecords (including a second
   verdict when a lineup-posted InformationEvent arrived after the first
   record), assembles a real `Fitness` from paper.py, grading.py CLV,
   battery and FDR outputs, calls `promotion_verdict`, appends a Scorecard.
7. EOD self-review (S7). A deterministic report: decisions, vetoes,
   settlements, CLV where a close exists, fitness deltas, what the engine
   did not know (assumption exposure), written to docs/eod/ and the chain.
8. Wire into the daily loop (S8) so S5–S7 run unattended on the existing
   Routine, and into the external capture path once the owner unblocks it.

Not in the slice: mutation/retirement (the population is the enumerated set
until a cell clears G5), props beyond the dispatcher fix, Bet Rating, LOCK.

## 6. WHICH COMPONENTS THEN BECOME PERMANENT AUTONOMOUS LOOPS

- External (GitHub Actions, once the two owner actions land): hourly capture
  of odds, props, derivatives, weather, lineups, umpires, information events.
- Daily unattended (S8, same trigger as the capture path): slate analysis →
  paper wagers → settlement → fitness → EOD self-review → chain verify.
- Weekly unattended: forward-epoch scoring of every registered system, gate
  ladder evaluation, publication of losers; sweeps and retests of the
  enumerated population against placebo worlds.
- Still Claude/owner: registering new systems, changing frozen contracts,
  promotions past G5, LOCK, anything that spends beyond the envelope.

## 7. Bugs confirmed by the adversarial review (F_review.md; fix before S5)

Blocking, all on the engine's own decision path:
1. `src/engine/analyze.py:309-319`: empty assumption exposure → grade "A".
   Fails open exactly when no as_of read occurred.
2. `src/board/settle.py:292` vs `settle_props.py:150`: dispatcher calls
   `fn(side, line, result)`, every prop rule is `rule(row, selection)` →
   TypeError. The wiring test bypasses the dispatcher, so it never caught it.
3. `src/engine/glue.py`: no first-pitch guard. `t` is the day's latest
   capture, so the "current slate" demo in A decided on an IN-PLAY board
   (BOS/SEA, first pitch 20:11Z, decision 22:19Z, home ML +3500, "edge" 2,979
   bps). A did not report this. The G4 run this morning has the same flaw.
4. `src/engine/snapshot.py:281`: `book_count` counts quote rows, not books
   (575 beside 11 real books).
5. `src/engine/snapshot.py:270-272`: dispersion mixes 26 hours of history,
   not books at t.
6. `src/engine/snapshot.py:194-205`: `best()` returns the best price ever
   seen through t, not the price available at t.
Non-blocking: `selection_id` has no event component and collides across
games (`ids.py:251-271`); `stake_units` hard-coded 0.0; `EvolabGenomeSystem`
p_model always None.

Corrections to the reader reports: a 2026 closing store does exist
(`data/processed/f5_close.jsonl`, 335 rows, plus 7,626 2026 snapshot rows and
the wired `closing_observation`/CLV code); the paper demo missed it because
`backfill.closing_prices` defaults to the historical store. Under-claim by
the readers: `evidence/forward_ledger.jsonl` already pairs game_pk (217 of
427 rows) with live pre-game prices and runs a real freeze→settle loop (144
recommendations, 73 settlements, 3 flagged F5 plays: won, pushed, won). Its
closing fields are null on all 73 ("no snapshots recorded"), so CLV there is
0-for-73. The L1/engine path has no game_pk at all; a resolver is a small
job since `src/providers/mlb.py:231 fetch_schedule` already returns teams and
first pitch. The GitHub Actions capture workflow is
not registered with GitHub at all (API 404): it has never run once.

## 8. Completion estimate

Against the milestone in §5, counting only code exercised on real data:
capture and settlement substrate largely done; decision engine about half
(pipeline yes, features no); accounts one third (ledger yes, feed no);
factory under one fifth (enumeration and tests only); autonomy near zero
until the owner's two actions and S8. Overall roughly one third. The Opus
review's independent estimate is ~30%, weighting the eight milestone clauses
evenly (every matchup ~40%, every market ~15%, select ~35%, accounts ~10%,
freeze/settle ~70%, fitness ~5%, EOD review ~10%).
