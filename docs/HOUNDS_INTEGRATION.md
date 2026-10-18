# Hounds: putting the halves together (2026-10-18)

The race was built in parallel: the core and read API (H1: `src/hounds/contract.py`, `verdict.py`, `ledgers.py`,
`boards.py`, `stats.py`, `house.py`, `api/hounds.py`), the user hounds and coach door (H3: `user_*.py`,
`api/hounds_create.py`), the pages (H2: `web/hounds.html`, `hound.html`, `build-a-hound.html`,
`web/js/hounds-*.js`), the house pack (H4) and the AI desk. Each half was right about its own code and guessed
at the others. This note is what was found when they met, what was changed, and what a person has to do.

PAPER ONLY. Nothing here places, sizes or routes a bet, and nothing claims an edge or a profit.

**The contract file, `src/hounds/contract.py`, is the single source of truth for shapes.** Where two halves
disagreed, the half that was not the contract changed.

## The seven things that did not line up

| # | Found | Fixed by |
|---|---|---|
| 1 | The pages guessed the shapes of `POST /hounds`, `GET /hounds/{id}/spec`, the menu, `series`, `stream`, `graveyard`, the bets list, and where forward and replay sit. | Pages read the real shapes (below). Fixtures are now built by the contract's own builders, and a test feeds the pages the real app's JSON and posts the build page's JSON to the real request model. |
| 2 | H3 computed its own CLV and verdict, and named its prices `price` / `best_price`; H1's reader looks for `price_average` / `price_best`. | The user ledger carries the contract's names; every public number comes from `stats` + `verdict.py`. |
| 3 | `GET /hounds/{id}` swallows `/hounds/menu` and `/hounds/mine` unless the create router is mounted first. | Pinned by a test against the real app, with a negative control. |
| 4 | The capture slot (GitHub Actions) has no app database; the user hounds live in it. | The engine runs inside the API process: `src/hounds/user_runner.py`. |
| 5 | A cold `/hounds` build streams about a million odds rows (7 s here). | First request answers `warming_up` in under a second; one background build under the shared gate. |
| 6 | Nobody had run create -> engine -> settle -> pages on one machine. | Below, "End to end". |
| 7 | (Found by running the reader on the real pack ledger.) Three disagreements, fixed on the reader side. | Below, "The house pack". |

### 1. The shapes the pages now read

| Page call | Real shape (source) |
|---|---|
| `POST /hounds` | body `{spec: {name, tagline, sports, markets, side_rule, price_min, price_max, min_books, max_bets_per_day, lock_minutes}, copied_from?}`; answer `{hound: HoundSummary}` (`api/hounds_create.py`) |
| `GET /hounds/{id}/spec` | `{spec, copied_from, rule_text}`, the spec carrying a free suggested name |
| `GET /hounds/menu` | `name{min,max}`, `tagline{max}`, `sports[{value,label}]`, `side_rules[{value,label,markets}]`, `price_min{presets,lowest}`, `price_max{presets,highest}`, `min_books`, `max_bets_per_day`, `lock_minutes{choices}`, `max_running_per_account` (`user_spec.menu()`) |
| `GET /hounds/mine` | `{hounds: [HoundSummary], limit_running}` |
| `GET /hounds/series` | `{series: {id: [SeriesPoint]}}`, FORWARD only, a zero point first |
| `GET /hounds/stream` | page object of `StreamItem`: a refusal has `refused: true` and its reason |
| `GET /hounds/graveyard` | `HoundSummary` with `status: "retired"` and `retired: {date, cause}` |
| `GET /hounds/{id}` | `HoundSummary` + `series` + `bets` as a page object `{items, page, page_size, total, pages}` |
| forward vs replay | `record`, `clv`, `verdict` are forward; `replay` is its own block `{bets, wins, ..., units_recorded_price, note}`. There is no replay series. |

What changed on the pages as a result: the chart is forward-only (the Forward/Replay toggle is gone: the
contract has no replay series, and replay is a record on each row, never drawn with forward lines); the build
form is generated from the real menu and switches off side rules that do not fit the chosen markets; its preview
says "average price across the books", which is what the engine does (it used to say "best price"); a copy is
posted with `copied_from`; the detail page pages bets with the server (and can narrow to forward or replay); a
`warming_up` answer shows a message and asks again.

Units, labelled the same everywhere: **average price** is the headline (`units_average_price`: the same bets
settled at the mean price across the books at the lock; may be null), **best price** is the small print
(`units_recorded_price`: settled at the single best quote recorded at the lock).

### 2. One referee

`user_settle.records_by_hound` / `verdict_for` / `clv_summary` still exist (nothing was deleted) but no public
payload reads them. `api/hounds_create.hound_summary` returns `HoundSummary` from `src/hounds/user_view.py`,
i.e. from `stats.build` (CLV by `src.report.clv`, label by `verdict.py`, docs/PREREG_HOUND_VERDICT.md): the
cached book when it has the hound, else the same `summarize` over that hound's own ledger rows (a real record,
no CLV, so the referee says TOO EARLY with n = 0, and a background build is started). The scorecard's record, CLV
and verdict, and the coach's "top 3 by verdict", come the same way. A test shows an absurd value in the engine's
`clv_pts` column changes nothing public.

Ledger names (`user_engine.contract_fields`, `user_settle`): `price_average` (= `price`, the board average),
`price_best` (= `best_price`), `book`, `book_count`, `start_utc`, `segment` (`forward` live, `replay` for a
backfill), `who_decided: "rule"`, `reason`, `date`; graded rows add `units` (= units at the best price),
`units_best_price`, `units_average_price`. The reader also understands rows written before the new names.

**Owner decision flagged, not changed:** the pre-registered CLV (`docs/PREREG_HOUND_VERDICT.md` section 1) is
measured on "the price the hound took", which for the pack and user ledgers is the recorded BEST quote
(`price_best`), while the headline units are at the AVERAGE price. Under the owner's grading ruling a reader
could expect CLV at the average price too. The prereg is frozen; changing it is a new dated section, and the
choice is yours.

### 3. Route order

`api/app.py` mounts `hounds_create_router` before `hounds_router`. `tests/test_hounds_integration.py::RouteOrder`
resolves `/hounds/menu`, `/mine`, `/stream`, `/series`, `/graveyard`, `/{id}`, `/{id}/bets`, `/{id}/spec`,
`/{id}/scorecard`, `/{id}/desk` against the real app, serves the literal ones over HTTP, and shows that mounting
the other way round reads `menu` and `mine` as hound ids.

### 4. Where user hounds run

Decision (2026-10-18, reversible): **inside the API process, on the machine that owns the app database.**

* `src/hounds/user_runner.py`, started by `api/app.py`'s startup hook, **only when `HOUNDS_ENGINE=on`** (default
  off; nothing starts otherwise). `HOUNDS_ENGINE_INTERVAL_SECONDS` (default 900, floor 30).
* One daemon thread, one pass at a time. A pass: running hounds from the app database (none: stop, the odds store
  is never opened); `user_engine.run` for today's Eastern slate (and tomorrow's after 20:00 Eastern); `user_settle`
  for the last 14 days; if a row was written, one background rebuild of the stats.
* Serialised with the app's other cache builds: the pass takes `src.appstate.freshness`'s one-build-at-a-time gate
  (so `/health` `builds.max_running` stays 1), and the loop waits for the first cache warm-up pass.
* The ledger is written beside the app database (`data/app/` locally, the Fly volume `/app/data/app` in
  production), not `evidence/` (baked into the image). `user_engine.ledger_path()` is the one place the engine,
  the settler and the public stats resolve it from; `HOUNDS_USER_LEDGER` overrides it.
* `GET /health` -> `hounds_engine` reports `enabled`, `passes`, `last_pass_utc`, `last_report`, `last_error`.

**Memory.** The engine used to list every row of its date window. It now streams (`iter_rows`), keeps only the
slate's games (`build_games(near_date=...)`) and only the eleven fields it reads. Measured with tracemalloc on
this machine against the real local odds store, one pass over a 15-game regular-season slate (2026-09-20):
**peak 28.8 MB** (25.3 MB on the single-game postseason slate), 7 to 10 s, independent of how many bets are
written. Budget 150 MB; `SchedulerMemoryOnTheRealStore` pins it. The public stats build is separate (the
existing streaming pass in `boards.scan`, whose own peak H1 bounds in `tests/test_hounds_live.py`).

### 5. Warming up

Routes ask `stats.get_book_nowait()`: a fresh cached book, or a stale one while ONE background rebuild runs, or
`(None, "warming")` with ONE build started. A cold start answers HTTP 200 with the route's own shape empty plus
`warming_up: true`, `retry_after_seconds`, a message, `Cache-Control: no-store`, in well under a second (local
measure: 0.07 s). The build takes the shared gate. It is not added to startup, so it never stands beside the
cache warm-up on a cold machine. A failed first build is a 503, retried after 30 s. A just-created user hound's
page works at once (`user_view.detail`) instead of 404-ing until the rebuild lands.

## End to end, on this machine

127.0.0.1 only, a temporary app database, no network, real stores read-only. Driver kept out of the repo; every
step below is a line of its output.

1. App started with `HOUNDS_ENGINE=on`, `HOUNDS_ENGINE_INTERVAL_SECONDS=30`. Cold `GET /hounds`: **200 in 0.07 s,
   `warming_up: true`, `no-store`**; the same call a few seconds later: 28 hounds, `public, max-age=60`.
2. A test account the way the existing tests make one (`users_store.create_user` + `issue_invite_token`).
3. `web/js/hounds-build.js` driven under node (name "Line Mover", MLB, all three markets, "the side the market
   moved toward", -199 to +1000, 3 a day) produced this body, which was then posted **unchanged** to `POST /hounds`:
   `{"spec": {"name": "Line Mover", "tagline": "Follows the money", "sports": ["MLB"], "markets": ["moneyline",
   "spread", "total"], "side_rule": "market_moved_toward", "price_min": -199, "price_max": 1000, "min_books": 1,
   "max_bets_per_day": 3, "lock_minutes": 60}}`. Answer 200, `status: running`, `verdict: TOO EARLY`; the
   hound's page answered at once.
4. **What is faked, and why.** The stored boards end on 2026-10-18 06:07Z and no game was locked "now". The
   hound's `created_at` was backdated to 2026-10-10 **in the temp database** (a hound made now cannot have bet on a
   game that locked days ago, and the engine correctly refuses to back-fill), and the first pass ran with the
   clock fixed at 2026-10-15 23:30Z (after the 23:00Z lock of Milwaukee at Los Angeles, before its start). Later
   passes used the real clock. Nothing else was altered.
5. First pass: 3 games on the slate seen, **3 bets written** (moneyline, run line, total). Second pass (real
   clock): **3 graded**, 0 pending; the chain verifies (`ok=True`, 6 rows). A bet row, with both prices: board
   average **+129** across 11 books, best **+135** at williamhill_us, `segment: forward`, `who_decided: rule`. A
   graded row: `WIN`, `units_average_price` 0.813, `units_best_price` = `units` 0.8475.
6. The stats rebuilt on their own after the rows were written. `GET /hounds`: the user hound is
   3 bets (3-0), `units_average_price` **2.6912**, `units_recorded_price` **2.8036**, CLV n = 2, mean -1.6 pts with
   no interval yet, verdict **TOO EARLY** ("Only 2 of its bets have a measurable closing price. At least 150 are
   needed"), `verified: true`, `replay: null`, spark `[0.0, 2.691]` on the average price. `GET /hounds/{id}`,
   `/hounds/series` (29 hounds), `/hounds/stream`, `/hounds/graveyard`, `/hounds/mine` (signed in: that one
   hound, `limit_running: 3`) all 200.
7. Pages rendered by their own scripts under node from that JSON. Race page: 29 rows; the user row reads
   "Forward record 3 bets (3-0) ... CLV -1.6 pts (no interval yet, n=2) ... Running, verified ... Units, small
   print: +2.69u average price, +2.80u best price". Chart title "Forward results: paper bets placed after each rule
   was written." with lines drawn. Stream lines say "... at -111 average price, -107 best price at betus ..." and
   refusals begin "Passed in ...". Hound page and the copy form (`?from=`) load from the same JSON.

## The house pack (21 hounds), read from the real files

The pack's `config/house_pack.json` and `evidence/hounds_house_v1.jsonl` (913 bets, replay only) were read from
the main branch (not copied into this checkout). `GET /hounds` lists all 21 with their category and style, each
with `record.bets` 0 and its **replay block** apart. Three disagreements between H1's reader and the pack rows
were found and fixed **on the reader side** (`ledgers.py`, `contract.py`); no pack file was touched:

1. A graded row links to its bet by `bet_row_hash` and carries no `line`, so every spread and total bet was
   counted twice (126 "bets" for a hound that made 63). The reader now links by `bet_row_hash`; a bet regraded
   (the doubleheader fix) counts once, last grading wins.
2. `who_decided: "random"` (seeded coin and dart) was silently shown as "rule". The contract's set is
   code | model | rule, and a seeded draw is made by code.
3. The categories `intangibles` and `simple` were not in the contract, so four pack hounds were filed under
   "mixed". Added. (`ai-desk` and `persona` are added for the desk, below.)

The reader also reads the pack's `units_best_price` as recorded units and does not read `profit_units` (the user
ledger's average-price profit). **Status of a replay-only hound:** the referee's bench rule counts days since the
last FORWARD bet, so all 21 pack hounds read "Benched" until they bet forward. That is the pre-registered
behaviour, shown as it is.

## The AI desk and personas

`config/desk_hounds.json` and `evidence/hounds_desk_v1.jsonl` are registered as sources; the ledger need not
exist (empty), and the seven desk hounds read **"Not started"** with their rule text until the first publish (new
status `not_started`, only for definitions marked forward-only). Rows use the shared shape (`who_decided: model`,
`segment: forward`, `bet_id` shared with the graded row); the game-level `desk_game` row has no `hound_id` and is
ignored by the reader. Categories `ai-desk` and `persona` have a label and a colour on the pages.

`web/hound.html` shows, for a desk hound only, **"How the desk argued"**: the newest published game's analysts,
bull, bear and head from `transcript.json` (each stage's final attempt, its claims and evidence count, the
checker's counts, the head's takes with price, book, stated probability, what would change it, and what code or
the checker struck), with a game picker; for a persona, its own call and a **"Where they disagree"** table from
`disagreement.json` (a market per row, a hound per column, status split / agree / lone / none, unanswered shown as
"not answered", never as a pass). Empty states are written out: no game yet, a stage not in the transcript, an
answer that could not be read, a missing disagreement file, a transcript whose checksum no longer matches the
ledger. Model text is shown as plain text and labelled unproven.

Served by `GET /hounds/{id}/desk` and `/hounds/{id}/desk/{game}` (`src/hounds/desk_view.py`): the file names
come from the ledger's `desk_game` row for that game, never from the request, and must resolve inside
`evidence/hounds_desk/`. `evidence/` is in the image, so published desk games reach the site with a deploy.

## Owner steps

1. **Turn the engine on for staging** (a plain environment variable; no deploy config edit):

       fly secrets set HOUNDS_ENGINE=on --app linehound-staging

   This restarts the app. Watch `GET https://<staging host>/health` -> `hounds_engine` (`enabled: true`, passes
   counting up, `last_error: null`) and `builds.max_running` staying 1. Turn off with
   `fly secrets unset HOUNDS_ENGINE --app linehound-staging`. Production
   (`--app linehound-prod`) the same way, when you decide.
2. After the first user hound has bet and been graded on staging, run
   `python -m src.hounds.user_engine verify --ledger /app/data/app/hounds_user_v1.jsonl` on the machine
   (`fly ssh console`).
3. Decide the CLV price question in "2. One referee" above.
4. The desk's first publish writes `evidence/hounds_desk_v1.jsonl` and `evidence/hounds_desk/<game>/`; they reach
   the site with the next deploy.

## How to re-run the checks

    python3 -m unittest tests.test_hounds_integration            # this note's tests
    python3 -m unittest tests.test_hounds_web_pages tests.test_hounds_web_core
    HOUNDS_PACK_CFG=<path> HOUNDS_PACK_LEDGER=<path> python3 -m unittest tests.test_hounds_integration.TheRealHousePack

The pack test skips where the pack files are absent and runs where they exist. The whole hounds set also passes
with FastAPI hidden (Linux CI has none): the route, warm-up and page-against-the-API tests skip, everything else
runs.
