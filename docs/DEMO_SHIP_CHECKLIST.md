# DEMO SHIP CHECKLIST — hosted demo sprint, 2026-09-07 (local Parent)

Owner directive (2026-09-07 ~00:20Z): a complete, hosted, clickable, honest
demo TODAY, 3–4 hours, smallest complete vertical slice. This file is the
frozen scope and the running ledger for that sprint. Supersedes nothing in
`docs/AUTONOMOUS_PRODUCT_QUEUE.md`; it just picks the items that ship today
(P1-2 partial, P1-3, P1-6, part of P1-5) and records what was cut.

Sprint clock: T+0 = 00:20Z. Deadline T+240 = 04:20Z.

## Recovered state (verified by command, 00:21–00:35Z)

- Checkout `C:\Users\KC\Desktop\aisportsanalysis`, branch
  `claude/sports-betting-analysis-review-g1o0co`, fast-forwarded to 4cf4e03
  (handoff commit). Tree clean before this sprint's edits.
- Default branch `claude/cowork-session-migration-tn3sx2` (orphan; carries the
  three workflow files). Unchanged.
- Actions: forward-capture dispatch 34066005061 green; `schedule` runs still
  0 for every workflow (P0-1 SCHEDULER_INCIDENT stands). daily-loop dispatch
  34068303330 wrote 560f900 then failed honestly on the settle gate.
  deploy-staging green on every push. Secrets present by name:
  `ODDS_API_KEY`, `FLY_API_TOKEN`.
- Staging `https://linehound-staging.fly.dev`: `/health` 200; the app renders
  at `/web/` behind the invite-token wall.
- Latest board in the tracked store: 2026-09-07T00:03Z (daily-loop snapshot).
  Engine froze 96 decisions / 48 paper wagers for 2026-09-07 at 00:03Z.
- Paper accounts settled through 2026-09-05 (283 settlements across 23
  systems: 142 W / 131 L / 10 P). 2026-09-06 and 09-07 wagers pending.

## Showstoppers found before any feature work

| # | Finding | Fix | Status |
|---|---|---|---|
| S1 | `/app` redirects to `/web` (no slash); index.html's relative css/js resolve to `/css/...` and 404 → blank page with only the wordmark on staging | `/app` → `/web/`; `/web` → 307 `/web/`; test updated + new test | DONE (local) |
| S2 | `.dockerignore` excludes `evidence/`, and `data/paper_accounts/` is not copied → the image has no ledgers, so no performance data can ever reach the product | Dockerfile `COPY evidence/` + `COPY data/paper_accounts/`; dockerignore negation | DONE (local) |
| S3 | Whole game surface needs an invite token; `APP_ADMIN_TOKEN` on staging unknown, no way to mint a token for Brey without a Fly login | `APP_PUBLIC_DEMO=1` env flag (default OFF): read-only game surface + Bet Check served without a token; personal routes stay authed; `/meta.public_demo` tells the client | DONE (local); set in `deploy/fly.staging.toml` at deploy |
| S4 | `src/core/timing.py` imports POSIX `resource`; the app cannot start on the Windows dev box | guarded import, `peak_rss_mb` = 0.0 on Windows | DONE |
| S5 | No capture scheduler was firing (cron never fired; cloud routines being paused) → board goes stale during the demo | dispatched `forward-capture` by hand at 00:36Z; hourly watchdog in this session. RESOLVED 01:00:46Z: the first genuine GitHub `schedule` run (34071611931) fired and committed 0bc53ca; the cloud Parent switched its routine to fallback-only at 01:04Z (17fd31b). The watchdog now only dispatches if the cron stops again | RESOLVED |
| S7 | `web/css/screens.css` had TWO unclosed `@media (max-width: 899px)` blocks (after the Bet Check V2 mobile rules, and after the Game Advanced V2 mobile rules). Everything below each one -- Game Quick V2, Game Advanced V2, Gameday V2, Odds V2 -- only applied at phone widths; on a desktop browser the Gameday and Game screens rendered as bare text. The sessions that shipped it only ever saw a narrow viewport | two closing braces; brace count now balanced (947/947) | DONE (local) |
| S8 | Entrance animation hides content until an IntersectionObserver callback arrives; in an embedded/emulated viewport the callback never came for below-the-fold panels (Game view: price, spotlight, teams stayed at opacity 0 even after scrolling) | `web/js/motion.js` fail-safe: any armed element still hidden after 1.5 s is revealed | DONE (local) |
| S9 | Engine-decision join keyed on raw abbreviations: the odds feed's "Athletics" resolves to OAK, the schedule says ATH, so TOR@ATH (the one LEAN on the board) came back with no engine decisions while every other game joined | `engine_bridge.game_key()` canonicalises via `parks.canonical_team` on both sides (same lesson as `prices.matchup_key`); regression test | DONE (local) |
| S6 | REAL REGRESSION since 2026-09-03 10:07Z: the multibook store gained spreads/totals/first-five rows (they carry a `market` key; moneyline rows do not) and the board readers took "newest row per book" across all of them, so a book's totals row (null prices) or first-five row (wrong prices) replaced its moneyline. Every game on `/odds`, every card and every consensus read "9 books, no prices, no consensus" — the product has shown no consensus on any board for four days | `snapshots.moneyline_rows()` filter in `prices.boards_by_matchup` and `snapshots.multibook_quotes`; 2 regression tests; verified live: 8 of 11 boards on 09-07 now price with 6–9 books | DONE (local) |

## Frozen scope — the vertical slice

Rule for every surface: real data first; STALE / UNAVAILABLE / INSUFFICIENT
DATA when not; never a fabricated probability, rank or edge. "Model
probability" renders as the MARKET-DERIVED REFERENCE with its provenance
word, or NO INDEPENDENT MODEL YET. `edge_bps` stays null. Value is
price-vs-consensus only (Engine 1, `src/analysis/prices.py`).

### The verdict rule (documented here, tested in `tests/test_price_verdict.py`)

Inputs: de-vigged consensus probability `p_fair` for the side (≥6 books,
one capture instant), the stated/best price's implied probability `p_price`
(vig included), board depth, board age. `value_points = (p_fair − p_price) × 100`.

| Word | Condition |
|---|---|
| INSUFFICIENT DATA | no consensus (no board, or < 6 books), or no price |
| STRONG VALUE | value_points ≥ +3.0 |
| VALUE | +1.5 ≤ value_points < +3.0 |
| LEAN | +0.5 ≤ value_points < +1.5 |
| FAIR PRICE | −1.0 ≤ value_points < +0.5 (at or near the de-vigged fair price) |
| PASS | −2.5 ≤ value_points < −1.0 (a normal vigged quote; nothing to see) |
| OVERPRICED | −4.5 ≤ value_points < −2.5 |
| FADE ALERT | value_points < −4.5 |

Evidence tier (separate from the word, shown beside it): HIGH = ≥9 books and
board ≤30 min old; MEDIUM = ≥6 books and ≤2 h; LOW = ≥6 books but older than
2 h. A LOW tier caps the word: STRONG VALUE→VALUE, FADE ALERT→OVERPRICED.
A stale board can never carry the strongest words.

### Pages

1. TODAY / SLATE — exists (`#/today`, `#/games`). Add: slate date shown
   prominently (the API's "today" is the UTC date, i.e. the Labor Day slate
   after 00:00Z), TOP OPPORTUNITIES section, verdict chips on tiles where a
   consensus exists.
2. TOP OPPORTUNITIES — new `GET /opportunities/{date}`: every game/side with
   a ≥6-book consensus ranked by Engine 1 `improvement_points` of the best
   available price; verdict word from the rule above; market probability;
   market-derived reference + NO INDEPENDENT MODEL YET; evidence tier;
   reasons (best price/book, board depth, capture age, thesis_support
   claims); risks (counterargument claims, staleness, engine
   counterarguments); the engine's frozen decisions for the game (system
   class + verdict + provenance, evolab theses verbatim, tagged FORWARD
   TEST · UNPROVEN, never as support); freshness. Empty → `NO QUALIFYING
   BEST BETS RIGHT NOW` plus the honest ranked table.
3. GAME DETAIL — exists (`#/game/…`). Add one panel: MODEL vs MARKET
   (market-derived reference per side; NO INDEPENDENT MODEL YET; engine
   decisions for this game with provenance and counterarguments; warnings).
4. BET CHECK — exists. Add server-computed `price_verdict` block on the
   contract (word, fair price, implied vs consensus probability, value
   points, evidence tier, reasons, risks) and a new numbered block in the UI
   with a probability-vs-value meter. Block 01 stays verdict-free (test-locked).
5. PERFORMANCE — new `GET /performance` + `#/performance` destination.
   Recent settled picks (date, matchup, market, side, price, W/L/P, units),
   per-system standing (class: CONTROL / MARKET REFERENCE / FORWARD-TEST
   SYSTEM; bankroll, units, ROI, hit rate, drawdown, N), overall for the
   forward-test class and for all systems, BET WON vs REASONING CORRECT
   split from `ReviewRecord.thesis_outcome`, pending wagers count, "settled
   through <date>" freshness. Labelled PAPER / RESEARCH PERFORMANCE on every
   surface.

### Cut today (documented, not built)

- Demo/replay mode (P1-7): not needed, the live 2026-09-07 slate exists.
- Spreads/totals/props on the odds board (store is h2h only).
- Signal registry (P1-4), full evidence-tier system (P1-5): only the thin
  tier above ships.
- Rebranding, animation, Tauri, onboarding copy, feedback capture, B3, any
  research. Test-purity fix for `docs/FACTORY_OVERLAP_REPORT.md` (deferred,
  §11 of the takeover doc).
- Filter/sort controls on the slate (ranking lives in Top Opportunities).
- Refactor `paper_performance._load_settled` to delegate to
  `settle_slate._reconstruct_settled_bets` (B3 verifier must-fix, maintainability
  only; numbers reconcile exactly today; divergence documented in the docstring).

## Build order (one implementation stream, verifier after each)

| Step | Owner | Done-check |
|---|---|---|
| B1 price verdict rule: `src/analysis/pricverdict.py` + `PriceVerdict` on `BetCheckContract` | Sonnet | unit tests over every boundary; betcheck test modules green |
| B2 `src/report/engine_bridge.py` + `api/opportunities.py` | Sonnet | GET /opportunities/2026-09-07 returns ranked rows from the real store; tests |
| B3 `src/report/paper_performance.py` + `api/performance.py` | Sonnet | numbers reconcile with `data/paper_accounts` and the latest scorecards; tests |
| F1 front end: Performance screen + nav, Top Opportunities on Today, Bet Check verdict block, game MODEL vs MARKET panel, public-demo sign-in bypass, slate-date label | Sonnet | local Chrome walk-through, no console errors, tests green |
| D1 deploy: `fly.staging.toml` env, push → deploy-staging, health | Fable | live URL renders all five pages |
| Q1 Chrome QA on staging (14-point list in the directive), mobile width | Fable | showstoppers fixed, limitations listed |

## Ledger (append as steps finish)

- 00:35Z S1–S4 patched locally; api deps installed (fastapi 0.141.1,
  uvicorn 0.52.4) on Python 3.14; local server up on :8000 in public-demo
  mode.
- 00:36Z forward-capture dispatched by hand (run 34070311873, green, commit
  2b2337b, 249 rows at 00:36Z).
- 00:44Z 57d5ef8 pushed (S1–S4); deploy-staging 34070786458 green in 50 s;
  staging `/app` → `/web/` renders `/today` 200 with no token; CI tests
  34070786455 green (5m16s).
- 00:45Z recon: B1–F1 implementation stream launched (Sonnet, verifier
  after each step).
- 00:50Z S6 found and fixed (board regression); 170 price/snapshot/contract
  tests green. First real read of the 09-07 board: 8 priced games, one side
  above fair (ATH +189 vs TOR, +0.59 pts → LEAN), everything else FAIR
  PRICE/PASS as a vigged board normally is. NYM@MIA books disagree by 211
  cents on the away side.
- 00:51Z 93c4306 pushed (S6); deploy 34071119375 green; staging `/odds/2026-09-07`
  now prices 7 of 11 games (LAA@BOS has 5 books, honestly below the floor).
- 00:53Z hourly capture heartbeat scheduled in this session (dispatches
  forward-capture when the newest run is >45 min old; stops if a genuine
  `schedule` run ever appears).
- 00:55Z B1 (price verdict) implemented and PASSED adversarial verification:
  `src/analysis/priceverdict.py`, `PriceVerdict` on the Bet Check contract,
  44 new tests, 265 tests green across the 11 named modules. B2 started.
- 00:57Z S7 found (two unclosed media queries) and fixed; 8c70cab pushed;
  deploy 34071425456 green. Local desktop parse: 775 rules (was 567).
- 01:00Z B1 committed as 37b47ce; deploy 34071588717 green. Real-data check
  on the local server: ATH +189 → LEAN (+0.59 pts, HIGH, 9 books); PHI −175
  → OVERPRICED (−3.48 pts). First genuine `schedule` capture run fired at
  01:00:46Z (S5 resolved).
- 01:06Z S8 (reveal fail-safe) + asset `Cache-Control: no-cache` pushed as
  8bed0d5 after rebasing over the cloud Parent's 4fc98fc/17fd31b. Game view
  verified end to end locally at 1280px (starters, verdict, price panel).
- 01:12Z B2 implementer done (99 tests green). S9 (ATH/OAK join) found by
  checking the real payload and fixed. The dev server's --reload had gone
  stale (served old code silently); restarted. In-process check: TOR@ATH
  joins 12 decisions (9 staked, 3 FATAL counterarguments).
- 01:17Z B2 + S9 pushed as c273055; B2 PASSED adversarial verification
  (no must-fix). Deploy 34072432948 green; staging `/opportunities/2026-09-07`:
  11 checked, 7 priced, qualifying = TOR@ATH home +189 LEAN (+0.61), words
  {FAIR PRICE 7, PASS 6, LEAN 1}; TOR@ATH engine join 12 decisions / 9 staked.
  B3 started.
- ~01:20Z the Claude Code process exited mid-B3 (workflow + monitors died;
  no result journaled). 01:35Z resumed: B3's files were complete on disk;
  33 tests green; in-process `/performance` returns real numbers (settled
  through 2026-09-05; 283 settlements; FORWARD_TEST 41-20-3 +19.18u,
  CONTROL 47-58-2 −14.06u, MARKET_REFERENCE 54-53-5 +4.19u, ALL +9.30u;
  138 wagers pending 09-06/09-07; reasoning split all UNTESTED by design).
  Committed B3; adversarial verifier + F1 front-end stream launched as
  Agents (workflow not resumed -- it would have re-run B3 from scratch).
- 01:37Z B3 pushed as 56831a6; deploy 34073572879 green; staging
  `/performance` serves the real ledgers (label, disclaimer, 283 settled,
  138 pending, 23 systems, 5-point series). Capture cron skipped the 01:15Z
  and 01:30Z slots (GitHub */15 is best-effort); watchdog re-armed at :23/:53.
- 01:46Z B3 PASSED adversarial verification: 49 tests; standings, class
  rollups and reasoning-split counts reconciled EXACTLY against the raw
  account ledgers and the latest scorecards_v2 rows for one system per
  class; pending/settled boundary exact for all 421 wagers; 0 unresolved
  matchups; limit validation and missing-file tolerance confirmed. One
  must-fix (maintainability): `_load_settled` re-implements row -> SettledBet
  instead of delegating to `settle_slate._reconstruct_settled_bets`;
  documented as a deliberate divergence in the docstring (tolerant of
  malformed rows, injectable directory) and listed under "Cut today".
- 01:58Z F1 (front end) delivered by the single Sonnet stream: 130 web /
  language / auth tests green; braces balanced 1098/1098; pushed c3fbc95;
  deploy green. Local QA at desktop: Today (slate banner, TOP OPPORTUNITIES
  card + ranked table + unpriced list), Performance (tiles, class tables,
  recent picks, reasoning 2x2, sparkline), Game (MODEL vs MARKET + ENGINE
  DECISIONS), Bet Check (PRICE VERDICT block: ATH +189 LEAN, PHI −175
  OVERPRICED). No console errors.
- S10 found in QA: with no token the client used /betcheck/free (three
  checks for life) -- the ticket read "2 OF 3 LEFT". Fixed: public_demo flag
  shared via api.js; Bet Check uses the open /betcheck route in demo mode.
  Pushed 1af1ef2; deploy green.
- 02:00Z Mobile (375px) sanity locally: Today and Performance render, no
  horizontal overflow, tab bar carries RESULTS.
- 02:06Z FINAL STAGING SMOKE (https://linehound-staging.fly.dev/app):
  lands on /web/ with no token; MON SEP 7 · NEXT SLATE; TOP OPPORTUNITIES
  with the ATH +189 LEAN card and the 14-row ranked table; nav TODAY /
  GAMES / CHECK / ODDS / RESULTS (BETS hidden); RESULTS renders the ledgers
  (settled through 09-05, 138 pending, 77 table rows, 2x2, sparkline);
  GAME TOR@ATH shows starters, MODEL vs MARKET (PASS / LEAN), 12 decisions ·
  9 played · 9 staked, every panel revealed; Bet Check prefilled from the
  query posts to /betcheck (not the capped free route) and renders PRICE
  VERDICT LEAN, fair +184, tier MEDIUM · 9 books · captured 65 min ago;
  no console errors on any page; /health and /meta carry no secret words;
  deployed motion.js has the reveal fail-safe. Capture dispatched by hand
  at 02:04Z (run 34075074865) because the cron skipped every slot after
  01:00Z and the session watchdog cannot fire mid-turn.
- SHIPPED. Handoff: docs/DEMO_HANDOFF.md.

## PHASE 2 — from demo to a usable product (owner directive 02:10Z)

Goal: a living record of what the analyzer thought BEFORE each game and what
happened AFTER. Same honesty discipline; nothing post-hoc. One implementation
stream at a time, orchestrator integrates, commits and deploys each step.

Facts established before starting (verified 02:11–02:20Z, so no one re-derives them):
- The engine ALREADY freezes decisions for every market: on 2026-09-07 it wrote
  24 moneyline, 39 run-line and 33 totals decisions (`evidence/decisions_v2.jsonl`,
  each with its price, `consensus_fair`, `books_at_decision` and `decision_utc`).
  A "best bets per matchup across markets" surface is a READ of that, not new
  analysis. Stakes are flat 1 unit by policy.
- The multi-book store now carries all three markets per capture (02:05Z instant:
  87 moneyline, 84 run-line, 87 totals rows over 10 games). Spreads rows carry
  `away_line`/`home_line`/`away_price`/`home_price`; totals rows carry
  `total`/`over_price`/`under_price`. Books mostly agree on the line (e.g. 11 of 11
  at total 8.5), but NOT always (NYM@MIA split 6 at 7.5 / 3 at 8.0) — so a
  consensus must be computed per (market, line) group with the ≥6-book floor
  applied inside the group, and the line always printed. Never de-vig across
  different lines: they are different bets.
- Final scores are available: `data/processed/boxscores_2026.jsonl` holds
  `type: "linescore"` rows with per-inning `away_runs`/`home_runs` per `game_pk`
  (15 of 15 games on 09-05, 13 on 09-06). Today's schedule also carries
  `away_score`/`home_score`/`state` on `dossier.game` in the `/today` payload.
- `/today`'s `dossier.game` already carries `away_probable`/`home_probable`,
  venue, first pitch and state, so a per-matchup grid with starters needs no
  new endpoint. `/games/{date}` rows do NOT carry probables or scores.

| Step | Scope | Status |
|---|---|---|
| C1 | `src/report/daily_record.py` + `GET /daily`, `/daily/{date}`, `/record`: frozen pregame recommendations per game, settlement joined by bet_id, per-day rollups, day index for the gallery, today/7-day/30-day record strip | DONE (da57414) |
| F2 | Today = every matchup (starters, time, odds, freshness, analyzer status) with its frozen positions and GREEN/RED/GRAY settled states; system record strip; daily recap gallery + per-day audit trail reading `/daily` | DONE (345f287) |
| C3 | Performance cuts: by market, by odds range, by decision grade, by class, rolling 7/30, thin-sample flags | DONE (a041e19) |
| F3 | Public-demo entry on the landing page, one honest explanation for the empty game screen, last-night link on Today | DONE (8b8da3b) |
| C2 | Multi-market live board: extend `oddspayload.MARKETS` to run line and total with per-line consensus grouping, so matchup detail shows live best bets beyond moneyline | AFTER F2 |
| F3 | Matchup detail story (pitchers, offence, bullpen, warnings, reasoning), performance cuts by market / tier / odds range, polish | AFTER C2 |

### FINDING F-1 (02:25Z): the forward-test systems stopped deciding on 09-05

Evidence, in order:
- Decisions by class over the whole ledger: CONTROL 305, MARKET_REFERENCE 466,
  FORWARD_TEST 64. Last decision date per class: CONTROL 2026-09-07,
  MARKET_REFERENCE 2026-09-07, **FORWARD_TEST 2026-09-03**.
- Per-date mix: 09-02 and 09-03 carry 21 and 19 forward-test decisions; 09-05,
  09-06 and 09-07 carry ZERO while the baselines carry 213, 198 and 96.
- The 16 genome systems are still registered
  (`evolab_system.REGISTERED_SYSTEMS` = 27: 3 CONTROL, 8 MARKET_REFERENCE,
  16 FORWARD_TEST) and the daily loop still dispatches every one of them --
  the Actions run log for 34068303330 shows `engine slate --systems` listing
  all 27 ids, then "decisions written: 96 new", none of them from a genome.
- So the genomes are invoked and silently propose nothing for every game; the
  baselines in the same run do write rows (including `refused_thin` ones).
- ROOT CAUSE, PROVEN (diagnostic 02:35Z, full evidence in
  `docs/FINDING_F1_DIAGNOSIS.md`). It is NOT a missing data store -- that
  hypothesis was tested and disproved (book depth 5-11 vs the genomes'
  `min_books=3`; every event resolved to a `game_pk`; the lineup watch files
  are growing every 15 minutes). The genomes all set `require_lineup=True`,
  and `decide_with_reason` checks that FIRST. The daily loop's cron is
  `0 10 * * *`, deliberately "well before the earliest first pitch", and
  `decision_time_for_game` pins the decision instant to the capture that
  exists when the slate runs -- about 10:06Z. On the real 09-05 slate all 15
  games posted their lineups between 17:16Z and 22:39Z, seven to twelve hours
  LATER. So every genome refuses `NO_LINEUP` on every game, every day, since
  the migration. Confirms itself in the history too: every genome decision
  through 09-03 has a `decision_utc` between 16:25Z and 01:51Z, because the
  old cloud session invoked the loop repeatedly through the day rather than
  once in the morning.
- Controlled proof (read-only, empty temp data dir, no writer called): real
  genome `4a7700d36b3855ab`, 11 books, generous features, varying one input --
  `lineup_posted=False` -> `(NO_PLAY, 'NO_LINEUP')` -> `propose()` returns `()`;
  `lineup_posted=True` -> a real `Decision` -> `propose()` returns a proposal.
- TWO SEPARATE DEFECTS. (a) The schedule genuinely excludes every
  lineup-dependent system from playing. That is an owner decision, not a bug
  to fix at 2am: moving or adding a slate run changes what "frozen pregame"
  means and risks a second set of frozen decisions for the same date (the
  duplicate-writer hazard in `docs/LOCAL_PARENT_TAKEOVER.md` section 9).
  LEFT FOR BREY -- see the handoff. (b) The silence was a defect on its own
  terms: `decide_with_reason` returns a NAMED refusal and the adapter threw
  it away, so sixteen systems stood down for four days without one line
  anywhere saying why. FIXED tonight: the adapter now logs
  `[evolab] <id> stood down: reason=... game_pk=... t=...` to stderr, so the
  next 10:00Z run says plainly what it did. Not an ESCALATE, because standing
  down is correct behaviour; it just must never again be invisible.

Why it matters for the product: the genomes are the only systems with a
directional thesis. Their 64 settled bets are what the Performance page shows
as +19.18 units. Since 09-05 the daily slate has frozen only null baselines and
market references, which the product must never present as picks to follow. So
"what does the system like today" is honestly "nothing with a thesis" until
this is fixed. Every surface built tonight states that rather than dressing a
baseline up as a recommendation.

DECISION FOR BREY (defect (a), deliberately not taken tonight): the systems
with a thesis only play once lineups are posted, and the slate currently
freezes at 10:00Z when no lineup exists. Options, in increasing order of
consequence: (1) leave it -- the genomes never play, and the product says so;
(2) add a SECOND slate run in the afternoon (say 21:30Z) that decides only the
games whose lineups have posted, which means one date can carry two frozen
decision sets and the ledger/settlement path must be checked for that;
(3) move the single run later, which trades pre-game lead time for lineup
coverage and changes every decision's point-in-time meaning.

Evidence that makes option (2) LESS radical than it first looks, gathered
after the options were written: every genome decision in the ledger through
09-03 carries a `decision_utc` between 16:25Z and 01:51Z, and dates carry
several distinct decision instants. The old cloud session invoked the loop
repeatedly through the day, so multiple frozen sets per date is the
behaviour this ledger already contains, not a new idea -- option (2) largely
restores how the system ran until 09-05 rather than inventing a scheme.

It is still not a change to make unattended at four in the morning: these
rows are the audit trail the product now puts on screen, and writing a
second set for a date under a scheduler nobody is watching is exactly the
kind of thing that should be done with an owner awake. Hence: written up,
not executed.

### FINDING F-2 (03:10Z): the matchup story cannot be told from the container

`GET /game/{date}/{away}/{home}` on staging returns THREE dossier sections
(park, price_improvement, multibook_board) and TWELVE gaps: teams, starters,
weather, news, lineups, matchup_depth, bullpen, arsenals, travel, splits,
matchup_history, market. That is why the game screen shows a column of
NOT YET AVAILABLE panels and why the directive's "tell the story of the
matchup" (pitchers, offence, bullpen, handedness) cannot be built tonight.

Two compounding causes, both structural, neither a bug in the UI:
1. `api/games._build_entries` calls `briefing.build_slate(games, store)` with
   NO feature inputs, while the CLI's `cmd_brief` (src/cli.py:1194) passes
   pitcher_logs, bullpen, lineups, handedness, splits, matchups, arsenals,
   weather, travel and news. The API was written as a thin read of the
   domain path and never grew the assembly step.
2. Even if it did, the inputs are not in the image: `data/historical/*` is
   gitignored (deliberately -- these are large derived stores), so the
   container has no results store, no pitcher logs and no bullpen log. The
   Actions daily-loop rebuilds them on the runner every morning and throws
   them away with the runner.

Note the starter NAMES are fine -- they ride on the MLB schedule
(`dossier.game.away_probable`) and the matchup grid already shows them. What
is missing is every analytical layer beneath them.

To fix, in order of size: (a) have the daily loop publish the rebuilt
results/pitcher/bullpen stores the way `data-seed/statcast` already
publishes the pitch store, and have `deploy/Dockerfile` copy them; then
(b) thread those inputs through `_build_entries` the way `cmd_brief` does.
(a) is a repo-size and data-policy decision (the same class of call as F-1's
schedule question) and is left for Brey; (b) is a couple of hours once (a)
exists. Until then the honest thing on screen is one sentence explaining
that this deployment ships without the feature stores, rather than twelve
unexplained NOT YET AVAILABLE panels.

Ledger continues below.

- 02:35Z F-1 diagnosed (see the corrected finding above) and its silent half
  fixed; 270 engine/evolab tests green; b88b48b.
- 03:0xZ C1 delivered and committed as da57414. Orchestrator caught one
  honesty defect on delivery before it shipped: the value comparison ignored
  the six-book floor, so two-book run lines carried value points of +14.01
  and `strongest_pregame` crowned one as the day's best-supported play. Now
  suppressed with a stated reason below the floor (120 of 213 comparisons on
  09-05), and the strongest pick moved to an eleven-book moneyline. Three
  regression tests added. Real data verified end to end: 09-05 shows 15
  games, all 15 final scores joined, 45-52-2 and -7.90 units; 09-07 shows 8
  games with every position pending and no result claimed.
- 03:02Z F2 delivered (148 web tests, braces 1223/1223, node --check clean)
  and deployed as 345f287. Browser-verified on staging and locally at 1280px:
  the record strip reads "0-0-0 · 48 pending, nothing settled yet" for today
  and "101-99-9 · +2.83u · +1.4%" for the last seven days; the matchup grid
  carries starters, prices with book count and capture age, the live price
  read, and the frozen positions, each labelled "fixed-direction null
  baseline, not a pick" or "republishes the board's own consensus, a
  calibration reference, not a pick", under the line "No system with a
  directional thesis played this game". The recap gallery and the
  #/day/2026-09-05 audit trail render the full frozen slate with WIN/LOSS
  chips and the settled units. No console errors on any screen.
- 03:04Z capture note: the 02:46Z run committed watch data but no odds rows.
  With no game near first pitch the slot spends no credits, so the board
  holds at the 02:05Z instant and the UI says "59 MIN AGO". Expected
  behaviour, not a failure; captures resume as first pitch approaches.
- 03:05Z performance cuts (C3) started.
- 03:10Z F-2 recorded (the matchup story cannot be told from the container).
- 03:20Z C3 delivered (154 tests) and committed as a041e19. Orchestrator
  rewrote the note under the cuts before shipping: these buckets are sliced
  from settled results AFTER the fact, which is the post-hoc move the
  project's own discipline exists to resist, so the page now says they are
  descriptive rather than findings, that a few dozen bets cannot establish a
  return, and that every pre-registered family closed null. Without that, the
  +34.2% pick'em/slight-dog bucket reads as a discovery.
- 03:22Z capture behaviour understood and documented: the dense odds pass
  only buys prices within three hours of a first pitch (WINDOW_MINUTES=180),
  so the 02:46Z slot logged "0 capture(s), 0 observations" and the board
  correctly holds overnight, resuming about 14:05Z before the 17:05Z first
  pitch. A morning board reading ten hours old is the design, not a failure.
- 03:25Z a session watchdog is set for 10:27Z to dispatch the daily loop only
  if GitHub's 10:00Z cron produced no run for that date -- never if one
  exists, because a second run would write a duplicate set of frozen
  decisions and wagers (takeover doc section 9). Session-bound: if this
  session is gone, the watchdog is gone with it.
- 03:35Z F3 delivered (176 web tests) and committed as 8b8da3b. Verified on
  staging: the landing page shows OPEN THE LIVE DEMO above the fold on a
  900px viewport; the Game advanced view leads with one NOT IN THIS BUILD
  panel and collapses "12 SECTIONS NOT IN THIS BUILD -- SHOW REASONS"; Today
  offers LAST NIGHT'S RESULTS pointing at #/day/2026-09-06 while it is
  showing the NEXT SLATE.
- 03:37Z d9364ff: Today now explains an old board rather than leaving it to
  be read as a dead feed -- one sentence, shown only when the board is older
  than the three-hour capture window AND no game is inside it. Verified
  against the served module across all four branches. 179 web tests.

- 03:40Z capture watchdog: newest forward-capture WORKFLOW run was 54 min old,
  which normally means dispatch. Did NOT dispatch, on purpose. The old cloud
  session's in-session fallback had just captured at 03:38Z (commit 928022c:
  weather, lineups, probables, transactions, umpires) -- the cutover rule
  exists to stop two paths capturing the same slot -- and the odds pass would
  in any case return "0 capture(s), 0 observations" until about 14:05Z,
  three hours before the 17:05Z first pitch. Dispatching would have burned a
  runner to write nothing. The scheduled-run count stands at 1 (the 01:00Z
  run, already recorded).

### FINDING F-3 (03:45Z, found by an independent peer QA session): one screen
### said the board both existed and did not

The Gameday matchup panel printed "No priced market for this game yet" four
lines under a Featured Bet quoting the same game at -196 across nine books,
same capture instant. Reproduced here and found to be true of EVERY game on
EVERY slate this API has served -- 11 of 11 on 2026-09-07 -- not one card.

Cause: `gamepayload._market_implied_consensus` and `api/today._odds_meta`
both asked the dossier's `market` section, which exists only when a caller
passes `prices_by_matchup` to `build_slate`. `src/cli.py`'s `cmd_brief`
passes it; `api/games._build_entries` never has (the same omission behind
F-2). The board section beside it, `price_improvement`, held the same
de-vigged consensus -- and that is what the odds board, the opportunities
table and the matchup grid read, which is why one screen contradicted itself.

Fixed: the consensus falls back to the board's own `consensus_probability`
and `has_market` answers the question its name asks. A fallback for the
SOURCE of one number, never a second definition of it -- checked by
reconciling against the other surface rather than by assertion: /games
ATL@PHI `away_fair` 0.3924 is byte-equal to /opportunities'
`market_implied_probability` for the same side, 9 of 11 games now report a
consensus, and the two genuinely unpriced games still report null. Two
regression tests pin the fallback and the honest-null case.

Worth recording about the process: this was caught by a second session doing
a read-only pass, not by the tests or by my own QA, which had checked each
surface on its own terms and never asked whether two surfaces on one screen
agreed. Cross-surface contradiction is a class of defect a per-surface test
suite cannot see.

- 03:57Z F-3 fixed (d38876c) and deployed. Verified live: 9 of 11 games now
  carry a consensus and `has_market` is true for exactly those 9, the two
  genuinely unpriced still report null, and the Gameday panel renders
  "TOR 65.0% / ATH 35.0% -- MARKET-IMPLIED CONSENSUS, DE-VIGGED" where it
  used to claim no priced market. Checked for the same class of bug
  elsewhere: `data_quality.has_market` still reports the dossier section
  faithfully, and the only surface reading it is the market_unavailable hero,
  which reads `board_summary.has_board` -- always correct. No knock-on.
- 03:58Z the peer's second point (the grid reading as a hang) also fixed
  (ba0e4ae): it had awaited /today before starting /daily and /opportunities,
  two sequential round trips, and the /today it fetched was the one Gameday
  already held. Measured on staging after deploy: the grid is complete
  2.5 s after navigation, 11 cards, no console errors.

- 04:00Z watchdog dispatched forward-capture (newest run was 74 min old;
  run 34081534234). Dispatched this time, unlike at 03:40Z, because the
  cloud fallback's last capture was 22 minutes earlier rather than 2, and
  the watch passes -- lineups, probables, transactions, umpires, weather --
  do capture every slot and cannot be bought back later. The odds pass will
  still return nothing until about 14:05Z, and costs no credits to try.

## PHASE 2 SCORECARD against the owner's priority list

| # | Item | State |
|---|---|---|
| 1 | Finish what was in flight | done |
| 2 | Performance API / settlement surfaces | done (B3, C1, C3) |
| 3 | Today with every matchup | done (F2) |
| 4 | Best bets per matchup | done -- live price read per side, plus the frozen positions across moneyline, run line and totals |
| 5 | Frozen pregame recommendations | done (C1 + F2), never restated after the fact |
| 6 | Settled GREEN/RED/PUSH results | done, with final score and per-game W-L-P |
| 7 | Daily recap gallery | done, plus the #/day/<date> audit trail |
| 8 | System record strip | done (today / last 7 / last 30) |
| 9 | Performance page | done (C3 cuts by market, odds range, grade, class, rolling) |
| 10 | Matchup detail story | BLOCKED by F-2 -- the data is not in the container. Mitigated with one honest explanation instead of twelve unexplained gaps |
| 11 | Browser QA | done, desktop and 375px, no console errors |
| 12 | Deploy / verify staging | done, every step deployed and re-verified live |
| 13 | Polish | done (F3 + the freshness sentence) |
