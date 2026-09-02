# Orchestration day — 2026-09-02 — end-of-day synthesis

Orchestrator: Fable 5.1 tier (architecture, adjudication, integration,
visual grading). Workers: Sonnet implementation lanes in isolated
worktrees; two Opus methodology reviews; deterministic scripts for
capture and tests. Day opened 18:20Z with a nine-auditor read-only
intelligence pass plus an Opus critic; execution ran as ASSESS →
PRIORITIZE → DELEGATE → REVIEW → INTEGRATE → VERIFY → REPRIORITIZE.

Lanes are numbered L0–L24. "Merged" means merged into the working branch
`claude/sports-betting-analysis-review-g1o0co`, pushed, covered by the
targeted test modules at integration and by the full parallel suite on
the merged head (3,186 tests at 20:10Z, 0 failures, before Wave 1). After
Wave 1 the container restarted four times between 21:04Z and 22:00Z and
killed every full-suite attempt on main; the closing evidence is the fast
tier on the final head (2,981 tests, 0 failures at 21:47Z), the targeted
web/contract modules at each merge, and each lane's own full-suite run in
its worktree (3,231–3,294 tests, 0 failures). A full run on main is the
first item for the build loop.

## WHAT CHANGED TODAY

Morning state (from the audit): a research machine with zero survivors
across 35 registered hypotheses and an 8,811-genome sweep; a forward
capture that had raced itself into four stranded commits in 30 hours; a
settlement ledger whose closing-line join silently returned null for 73
of 73 rows; the paid historical odds purchase living only on an ephemeral
disk; a 20-minute test suite; a V2 design of 38 artboards with no screen
implemented; zero paying customers on Stripe TEST; docs one to three days
stale; 17.5 engineering hours idle before the day began.

Evening state: capture runs under one shared lock with rebase-before-push
and honest ESCALATE lines (23 hourly runs today; none stranded since the
fix); every settled ledger row carries a captured close for h2h, spreads
and totals where one exists (70 of 73 each, append-only, the three gaps
named by reason); the historical purchase is archived in git with
checksums; the suite runs in ~9 minutes full in the main checkout (27 s
in a fresh worktree) and 6 s for the fast tier; all four V2 customer
screens (Odds, Bet Check, Game, Gameday) plus the Wave 0 primitives are
implemented, visually accepted on fixtures, and deployed to staging by
the push workflow; SQLite is WAL with a busy timeout and /odds is cached;
a cross-family alpha registry exists and is seeded; the V3 timing family
gained a fifth admitted class captured live; weather, credit balance and
(env-gated) pitcher-K prop prices are captured hourly; and the V3 first
read was made, failed adversarial review, was corrected the same day, and
passed a second review as an honest "below floor under the registered
definition, no result read".

## BUILT (merged)

- L0 Historical odds archive: `scripts/archive_historical.sh` /
  `restore_historical.sh`, `data/archive/historical/**` (7.5 MB gz,
  SHA256SUMS), un-ignore block, test.
- L1 Capture self-commit hardening: shared `flock` on
  `/tmp/linehound_git.lock` across `forward_capture.sh` and
  `daily_loop.sh`, fetch + `pull --rebase --autostash` before push,
  explicit staged paths, `ESCALATE:` lines for every git failure.
- L2 Closing-line join fix: `snapshots.game_key()` canonicalizes club
  names; `closing-audit` CLI; regression test.
- L3 Parallel test runner: `scripts/test_parallel.py` (module sharding,
  LPT balance, per-worker `APP_DB_PATH`, forward-store fingerprint),
  `scripts/test_fast.sh`, `tests/slow_modules.txt`.
- L4 Capture extras: weather (open-meteo, 0 credits), credit-balance log,
  pitcher-K prop prices (PROP_PRICES=1, hard daily cap),
  `scripts/capture_extras.sh`, `credits` CLI, COLLECTION_POLICY amendment.
- L5 V3 primary test (`src/research/timingtest.py`, `timing --test`),
  ADDENDUM 1. Superseded the same day (RESEARCH RESULTS).
- L6 Labels: `web/js/labels.js` + `src/data/labels.py`, parity test.
- L7 V2 implementation manifest (38 artboards → files, endpoints, fields,
  tiers) + test.
- L8 V2 Odds screen: three board variants, slate summary, mobile
  five-row truncation. VISUAL PASS on second pass.
- L9 Backend hardening: WAL + busy_timeout on six stores (two latent
  races found and fixed), `/odds` input cache, single-writer invariant.
- L10 Docs truth pass; dead `bullpen_grade` module retired.
- L11 Umpire capture (`umpirewatch.py`), fifth V3 class by dated
  amendment, wired into the hourly capture (first admissible reveals
  20:15Z).
- L12 My Bets closing price + digest price alert + backfill CLI.
- L13 Alpha registry: `src/research/alpha_registry.py`, migration,
  `data/research/alpha_registry.jsonl` (40 hypotheses, 1 sweep, 1 audit,
  38 verdicts + 1 withdrawal), migration report.
- L14 h2h closing backfill: 70 append-only rows, idempotent.
- L15 V2 Wave 0: `web/js/states.js`, `web/js/featuredbet.js`. VISUAL
  PASS with two accepted deviations.
- L16 V3 correction: relevance rule (frozen line-43 list transcribed,
  decided blind), floor from recorded poll bracket, KM median(diff)
  primary with clustered interval, cluster sign test, rule-of-three,
  concentration check, denominator 5 with the monotone rule, pinned read
  (commit + nine store hashes incl. both git-ignored stores). ADDENDUM 2.
- L17 Per-market close identification (h2h, spreads, totals, first_five).
- L18 Spreads/totals backfill: 140 append-only rows; CLV null with reason
  for line markets (no fair-price model; the point itself moves).
- L19 V2 Gameday (`today.js`), L20 V2 Bet Check (`betcheck.js`), L21 V2
  Game (`games.js`): all four V2 screens now replace V1 in place, each
  with a bannered CSS section and a structural test module.
- L22 V3 second-review follow-ups: CLI framing carries the relevance
  count; censored negative lower bounds are uninformative, not "minus";
  registry withdrawal row; post-review code note.
- L23 featuredbet.js side fallback never invents a side; Game spotlight
  keeps its matchup header.
- Orchestrator: capture wiring via atomic rename while the old script was
  mid-run; `docs/REVIEW_V3_FIRST_READ_2026-09-02.md` (both reviews);
  `design/linehound-v2/VISUAL_ACCEPTANCE_V2.md` (every grade and accepted
  deviation).

## LEARNED

- The closing-line null was a pure join bug, not a capture gap. Spreads
  and totals were being captured all along.
- The 20-minute suite was 20 minutes only in checkouts with
  `data/historical/odds_history`; sharding by module with per-worker DB
  paths is enough.
- WAL exposed two latent races the rollback journal had masked.
- Worktree workers silently miss git-ignored stores. Two lanes produced
  wrong counts for exactly this reason (42 vs 56 measurable, twice, via
  two different stores). Rule: research lanes copy the stores they read
  read-only into the worktree and hash them in the addendum.
- Pinned reads are not optional: the same CLI command returned 166/165
  and 168/167 to two readers because capture appended between them.
- `git pull --rebase` over unpushed merge commits flattens them; the
  capture script's own rebase did this to one merge (L20) during a
  restart. Content survived, the merge commit did not. Push merges at
  once.
- The container restarted twice in twenty minutes when the full suite
  (4 workers), a dense capture and two Playwright lanes overlapped, and
  each restart dropped scheduled-trigger messages and untracked files.
  Heavy jobs run sequentially; drafts live in the scratchpad or in git.

## FALSIFIED

- "The V3 transaction class crossed its floor and reads positive." Under
  the registered definition the relevant subset is 19 of 30. The
  S(0)=1.000 / CI [1,1] / p=0.000 read was a boundary artefact of a
  statistic substituted for the pre-registered median, on a class broader
  than the one registered. Recorded in full, never deleted.
- "Every observed and lower-bounded diff exceeds its floor": one censored
  lower bound is −6.9 min. Corrected.
- "Capture spacing was 60 min for 20 of 56 events": every recorded poll
  bracket was 14–18 min. The floor now comes from the bracket.
- "Prop-listing spend is near its cap": 34 credits of 400.
- "Credits are scarce": the credit log reads 99,680 remaining at 21:00Z.

## MORE IMPORTANT THAN WE THOUGHT

- Entry-vs-close is now measurable on every settled row across three
  markets at zero credit cost: the cheap early filter the master plan
  wanted before any promotion standard.
- Store completeness and pinned reads in worker environments.
- The umpire feed: free, timestamped, pre-pitch, with a known mechanism.
- Adversarial review as a standing gate: it caught a manufactured
  positive within four hours of its creation.

## LESS IMPORTANT THAN WE THOUGHT

- The DuckDB mirror (nothing today needed it).
- The NBA spike (nothing argued for it back).
- The 4-vs-5 denominator argument: a stated monotone rule settles it.

## RESEARCH RESULTS

- V3 `transaction_first_seen` (= frozen `il_roster_move`): first read
  FAILED adversarial review on nine required findings; corrected as
  ADDENDUM 2; second review PASS. Outcome: relevant subset 19 of 30, NO
  PRIMARY RESULT READ. Disclosed secondary (all 56 transactions, not the
  registered class): KM median diff 209.8 min, clustered CI [163.8, not
  reached] (445/2000 draws not reached), cluster sign test 19 plus / 0
  minus / 1 mixed dropped, p = 1.9e-6; 39/56 censored, of which 92 of 148
  exclusions are the six-book gate selecting near-first-pitch games; two
  calendar days, 20 clusters, 6 carrying all 17 observed reactions,
  DET@MIN 8 events. Honest headline for the secondary: breadth of
  repricing is slow and incomplete. Not a finding about the class, not
  an edge.
- Other V3 classes: lineup_posted 29/30, hitter_scratch 3, starter_scratch
  0, umpire_crew_revealed 0 admissible (admissible reveals began 20:15Z).
- Alpha registry: h2h 23, first-five h2h 7, totals 2, first-five totals 3,
  V3 (market null) 5 registered hypotheses; one sweep of 8,811 candidates;
  one audit; V3's first-read verdict withdrawn. Zero survivors remains the
  honest board.
- Per-market close coverage over 73 settled games: h2h 70, spreads 70,
  totals 70, first_five 26 (47 not captured; store too young).

## PRODUCT PROGRESS

- V2 Odds, Wave 0 primitives, Bet Check, Game, Gameday: implemented and
  graded (VISUAL_ACCEPTANCE_V2.md). Gameday mobile failed its first pass
  (desktop reflow) and passed the second (V2-22 date strip, stat chips,
  compact matchup poster).
- Every push deployed staging automatically (80+ green runs). Staging
  re-verification (protocol step 5) is BLOCKED BY THE ENVIRONMENT: the
  deployed head is confirmed by served-JS markers, but headless Chromium
  cannot reach staging through the session's agent proxy (connection
  reset after the CONNECT tunnel opens) while curl succeeds. The capture
  script is ready in the scratchpad; an owner-side browser pass, or
  browser egress in the environment, closes it.
- My Bets closing price and digest price alert; WAL; /odds cache;
  staging health monitor green all day.
- Tier A/B intact: nothing computes a rating, probability, rank or edge;
  the Ranker gate holds; V2-35 stays Tier B.

## DATA CAPTURED

- 23 hourly forward captures; the last under the new lock and wiring
  (umpires, weather, credit log, prop prices: 18 price rows / 2 credits
  on the first run). F5 closes 281 rows (+17 in one run).
- Umpire crew reveals: 2 admissible at 20:15Z.
- Weather forecasts 23+ rows; credit log started; prop prices started.
- Ledger 427 rows incl. 210 append-only closing backfill rows.

## NEW SYSTEMS

Shared git lock; parallel runner + fast tier; capture extras; umpire
watch; alpha registry; per-market close identification and backfill; V2
shared primitives and four V2 screens; visual acceptance record;
pinned-read convention; adversarial-review record.

## STILL BLOCKED (owner-only)

1. Default branch is an orphan (`claude/cowork-session-migration-tn3sx2`
   shares no history with the working line): GitHub refuses a pull
   request. Repoint the default branch or accept the branch as the record.
2. Live Stripe billing (still TEST; zero paying customers).
3. Prop PRICE capture is on under the capture-now principle (2 credits
   per hour); say stop if the policy line should have been signed first.
   Historical prop purchase remains a hard approval gate.
4. Environment stability: four container restarts in an hour with 0.6 GB
   of 16 GB in use, each dropping trigger messages, background jobs and
   untracked files. Not load; needs the platform or a different
   environment. Browser egress to staging is also blocked by the proxy.

## NEXT (queued, not started)

- Full parallel suite on main (build loop, first thing).
- Staging re-verification of the four V2 screens from a browser-capable
  network; fix whatever it finds; then Wave 2 (My Bets, Signup &
  Billing, Access, Landing).
- Nightly entry-vs-close diagnostic over the backfilled ledger across
  the three markets (free), with sample sizes, in the digest.
- First_five close backfill decision (26/73).
- Store-completeness helper for research worktrees; addendum template
  with the pin section.
- V3 accumulation: relevant transactions ~2–3/day (floor ~a week away);
  lineup_posted needs one event; umpire class now admissible.

## MASTER PLAN CHANGES

- Appendix C.1 item 2 (entry-vs-close extension) DONE for h2h, spreads,
  totals; F5 partial.
- Phase 1 gate added: a research read is valid only if pinned (commit +
  hashes of every store it reads, git-ignored ones included) and only
  after an adversarial review passes.
- Worker discipline: research lanes copy git-ignored stores read-only
  into their worktree; heavy jobs are sequential.
- Alpha registry implemented; the battery's citation rule (Decision 4)
  can be enforced in code.
- V3: transaction class is "accumulating (relevant subset)", not "at
  floor"; the umpire class is admitted and capturing.

## NOT THINKING BIG ENOUGH

- Three-market close coverage means every future pick can be scored
  against the close the night it settles, for free, in public. Wire it
  the moment a pick exists; it is the public-picks record's backbone.
- Capture-now should extend to every free, timestamped feed with a
  plausible mechanism (umpires and weather today; next: bullpen
  availability notes, official scratches, roof state).
- The review loop should be a standing gate on every addendum, not an
  orchestrator decision.

## TOP 5 MOVES FOR THE NEXT SESSION

1. Run the full suite on main, then get the four V2 screens verified on
   staging from a real browser; fix real defects; start Wave 2 with the
   same lane discipline.
2. Build the nightly entry-vs-close diagnostic over the backfilled
   ledger (three markets) and publish it in the digest with sample sizes.
3. Ship the store-completeness helper and the pinned-read addendum
   template; make adversarial review a required step before any addendum
   is called a read.
4. Decide the owner items: default branch, live Stripe, prop-price
   policy line, environment size.
5. Keep V3 accumulating and read lineup_posted the day it crosses 30,
   under the corrected procedure.
