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
| S5 | No capture scheduler is firing (cron never registered; cloud routines being paused) → board goes stale during the demo | dispatch `forward-capture` by hand ~hourly during the sprint; note in handoff | ONGOING |
| S7 | `web/css/screens.css` had TWO unclosed `@media (max-width: 899px)` blocks (after the Bet Check V2 mobile rules, and after the Game Advanced V2 mobile rules). Everything below each one -- Game Quick V2, Game Advanced V2, Gameday V2, Odds V2 -- only applied at phone widths; on a desktop browser the Gameday and Game screens rendered as bare text. The sessions that shipped it only ever saw a narrow viewport | two closing braces; brace count now balanced (947/947) | DONE (local) |
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
