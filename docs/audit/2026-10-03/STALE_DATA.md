# Stale inputs on the live site: findings, design, what shipped

2026-10-03. Owner: "This has to automatically update every day by itself. I
shouldn't have to log into Claude."

## TL;DR

The pages read files baked into the container image. Capture commits odds and
cards every hour; **nothing commits the stores the computed pages read**, and
the one job that refreshes them (the daily loop) writes to an Actions cache the
deploy never restores. So the image carried copies that stopped between Sept 6
and Sept 23, and no surface said so.

Fixed with no workflow edit and no person: every image build now catches those
stores up from MLB's free API (bounded, fails soft to the committed copy), a
guard inside the running container does the same hourly if anything has gone
stale, `/health` reports how current each store is, and the pages print the
date a store covers when it is too old for the game on screen. One real
training contamination found on the way (131 postseason games in every
training table) is fixed. One optional YAML patch for the owner is in
`docs/decisions/` (nothing depends on it).

## 1. The map

### What the pages read at request time, and how old each copy is in the repo

Ages measured 2026-10-03 against "yesterday, Eastern" = 2026-10-02
(`store_freshness.report`, reproduced by `tests/test_store_freshness.py`).

| Store (all under `data/historical/`) | Newest date in the repo | Behind | Read at request time by |
|---|---|---|---|
| `mlb_results.csv` + `.manifest.json` | 2026-09-23 | 9 d | `api/games.py:168` (team records, form, travel), `api/today.py:152`, `api/card.py:331,373` via `_build_entries`, `api/opportunities.py:31`, `api/betcheck.py:179`, `api/digest.py:64`, `api/postseason.py:232` + `src/report/postseason_page.py:1492-1508` (`_load_default`), card grading (`src/engine/settle_slate.py:72`) |
| `pitcher_logs.jsonl` | 2026-09-07 (last refresh marker 09-07) | 25 d | `src/pipeline/enrichment.py:104` -> game pages (starter lines, **days rest**), postseason page (`postseason_page.py:1799`) |
| `bullpen_log.jsonl` | 2026-09-06 | 26 d | `enrichment.py:109` -> game pages (bullpen workload, **"no relief appearances in the last 7 days"**), postseason page (`postseason_page.py:1801`) |
| `standings.jsonl` | 2026-09-08 | 24 d | `enrichment.py:170` -> league position on game pages; postseason field (`postseason_page.py:1744`) |
| `pitcher_splits.json` | 2026-09-08 | 24 d | `enrichment.py:217` |
| `arsenals/{pitcher,batter}_2026.json` | 2026-09-08 | 24 d | `enrichment.py:268-271` |
| `transactions.jsonl` | 2026-09-08 | 24 d | `enrichment.py:249` (roster news) |
| `handedness.json` | no dates (1,642 players) | n/a | `enrichment.py:140`; capture adds players on its runner and never commits them |
| `lineups.jsonl`, `matchup_history.jsonl`, `matchup_pairs.json` | 2026-10-03 | 0 | `enrichment.py:132,201` -- **fresh**: `scripts/append_only_stores.txt` makes capture commit them |

`enrichment.py` is the one loader for both the web pages and the card
publish path (`api/games.py:146`), so one stale input is stale everywhere.

### Which job refreshes each on the runner, and why that never reaches the image

| Store | Refreshed by (on the runner) | Where it lands |
|---|---|---|
| results | `scripts/daily_loop.sh:46-48` (`ingest 14 days ago..today --game-types decisive`) | runner checkout, saved to Actions cache `daily-loop-data-*` (`daily-loop.yml:81-94`, `165-`) |
| bullpen | `src/cli.py` `do_pen` (`bullpen.build_log(yesterday, yesterday)`, one day only, never heals a gap) and `scripts/daily_bootstrap.sh` | same cache |
| pitcher logs | `src/cli.py` `do_pitchers` (`refresh=True`) | same cache |
| standings | `scripts/daily_loop.sh:100-104` (`standings.catchup`) | same cache |
| splits, arsenals, news | `daily_loop.sh` splits / arsenal steps; `cmd_brief` | same cache |

Why none of it reaches an image:

1. **`scripts/daily_loop.sh:670-686` does not `git add data/historical`, on
   purpose.** The runner's copy is the cache's copy, and a blind add would
   make git converge on the cache by deleting rows only git holds (the
   2023-25 postseason backfill). The comment there says a union is needed
   first. That is correct, and it is why nothing commits these stores.
2. **The cache is branch-scoped and written from the orphan default branch.**
   A run on the working branch sees zero of it (`deploy-staging.yml:104-170`
   documents exactly this).
3. **`deploy-prod.yml` does not even try to restore it** (no cache step;
   checks out `claude/sports-betting-analysis-review-g1o0co`, line 59) and
   `deploy/Dockerfile:78` does `COPY data/historical/` of whatever the
   checkout holds. Staging restores, always misses, and warns.
4. Capture (`capture_slot.sh`, `forward_capture.sh`) commits only the stores
   named in `append_only_stores.txt` (lineups, matchup_history). The stores
   above are not on that list, correctly: they are not append-only.

Net: the image's copy of each store is whatever was last committed by a human
or an agent session. That is the "log into Claude" dependency.

### What the page said, and why it was wrong rather than just old

- `src/report/postseason_page.py:255-271` already printed the true "run
  through" dates ("Pitcher numbers on file run through Sept 27") -- accurate.
- The **game pages did not**. `bullpen.team_workload` returns zero relievers
  for a window the log does not cover and the page rendered that as a fact
  ("No relief appearances recorded in the last 7 days", `web/js/gamestory.js`);
  days rest counted from the last row in the log (14, when the starter threw
  on Sept 27); team records carried a game count and no date.
- With the stale repo copy and **no network top-up**, `postseason_page.build`
  returns `available: False` ("The final regular-season standings are not in
  yet"). The live page only works because `api/postseason.py` patches results,
  standings and logs in memory per build; every other page has no such top-up.

## 2. Design chosen

Option (a), as asked: **refresh at image build and at container start, by code
in the repo, bounded, failing soft to the committed copy.** No YAML needed.
Option (b) (committing the stores) is deliberately not done; see section 6.

```
 repo checkout --COPY--> image data/historical/ (stale)
                              |
        RUN python -m src.pipeline.display_refresh      <- deploy/Dockerfile, after the last COPY
                              |      (catch up to the Eastern baseball date; <= ~4.5 min)
                              v
                 image carries data current to that build
                              |
   container: api/app.py startup -> display_refresh.start_background_guard
        every hour: store_freshness.report() ; if a core store is stale
                    -> child process `display_refresh` (700 MB cap, 240 s)
                              |
                   /health -> data_freshness   (outside visibility)
```

Why this shape:

- **Every hourly deploy is covered with no human.** The Dockerfile step sits
  after the last COPY, so its layer is rebuilt whenever capture committed
  anything (every hour). The `DATA_REFRESH_STAMP` build-arg busts the cache for
  a redeploy of an unchanged commit when the owner adds it (optional patch);
  without it the guard closes the gap within minutes of start.
- **The guard is the second line, not the first.** It runs only if
  `DISPLAY_REFRESH_GUARD_INTERVAL_SECONDS > 0` (the Dockerfile sets 3600;
  tests and laptops never start one), waits for the first cache warm-up pass,
  and refreshes in a **child process**, so its memory is its own and capped
  (`RLIMIT_AS`), and a hang is killed.
- **1 GB machine:** measured peak working set of the whole refresh from a
  4-week-stale copy: **134 MB** (pagefile 122 MB), against a warm-up peak of
  540 MB. Stores are processed one at a time; nothing is held across steps.
- **Never a worse store than the one it started with.** Every step works on a
  copy in `data/.refresh_work/`. A copy is promoted over the original with an
  atomic `os.replace` only if it parses and has not shrunk (pitcher logs may
  shrink by at most 2%); otherwise the committed copy stays. A deadline hit
  mid-step promotes the progress made, which resumes next run. *(Second pass:
  "has not shrunk" is now checked key by key, not by total; section 9, item 3.)*
- **An unreachable API costs one 8-second probe.** Fetch timeout 10 s.
- **Zero odds credits.** MLB Stats API and Baseball Savant only. It never
  opens `data/watch`, `data/processed`, `evidence`, any card file or any odds
  store (sentinel-checked in `tests/test_display_refresh.py`). It adds only
  dates after each store's own newest date, plus a 14-day results lookback --
  today that is 2026-09-09 onward, nowhere near the sealed 2026-01-01..08-27
  window -- and it never rewrites an existing outcome (results merge by
  `game_pk`, and a copy with fewer rows is refused). *(Second pass: that claim
  was true of the results and not of the bullpen, whose 75-day window reached
  back to 07-20. No step may now request a sealed date; section 9, item 5.)*
- **Bounded:** default budget 270 s split across eight steps by weight with
  unused time rolling forward; the Dockerfile adds `timeout 330` and `||
  echo`, so the build cannot fail or hang on it. Measured live, 2026-10-03,
  from the stale repo copy: **115-145 s cold**; steady state is shorter.

What each step does (all resumable from the store's own coverage record):

| Step | Catches up | Notes |
|---|---|---|
| results | every date since the manifest's newest, min 14-day lookback | `DECISIVE_GAME_TYPES` (postseason stored); scope-aware resume re-fetches an R-only date once |
| bullpen | missing dates from the log's own newest date (never less than a 75-day window); **yesterday re-fetched whole** | `build_log` skips a date once any row exists, so a game in progress at the last fetch was lost for good. *Second pass: anchored on the log's coverage end, not on today; section 9, item 4* |
| pitchers | starters whose log is behind a start the results show (from each one's own coverage end) + the next 3 days' announced probables | refresh mode (12 h), postseason starts included, each tagged `game_type`. *Second pass: was "starters of the last 21 days"; section 9, item 4* |
| standings | each missing daily snapshot; yesterday re-taken if captured before that day ended | stops at the last regular-season date (the API returns an empty table for a postseason date) |
| splits / handedness / arsenals / transactions | today's+tomorrow's probables / batters in recent lineups / both Savant leaderboards / moves since the newest stored | best effort |

Found and fixed during live runs (they would have shipped otherwise):
`P` as a game-log gameType **duplicates every postseason appearance** (the API's
aggregate type; each Wild Card start came back as an `F` row and a `P` row), so
the fetcher never asks for it alongside the specific codes; promotion
originally moved the work file and starved the next step of the freshly
ingested results.

## 3. In-season vs postseason: the game-type rule

`ingest`'s default `--game-types training` (regular season only) exists so that
the **shared** results store never feeds a postseason game to a model as a
training row: the best teams, aces starting, no regular-season fatigue is a
different, selected population. The postseason page and card grading cannot
work without those games, so display ingest stores `DECISIVE_GAME_TYPES`.
The daily loop has done so since 2026-09-23 and so does the refresh.

**What was missing, and is now fixed:** the protection was meant to be at
ingest, but the store is shared, so it has to be at the READER. It was not.

- `features.build_training_table` took every stored game. Measured today: the
  store holds 131 postseason games from 2023-25 (backfilled 2026-09-23), and
  **all 131 were labelled training rows** (9,130 rows instead of 8,999). That
  table feeds `train`, the card calibration fit, `fit_card_v2_frozen_params`,
  `calibration_drift_audit` and every backtest/probe script. The 2026
  postseason, now landing daily, would have added more.
- Fix: `build_training_table(..., game_types=TRAINING_GAME_TYPES)` by default
  (a row with no `game_type` is regular season); `game_types=None` opts in to
  everything. Counted in `skipped["not_training_game_type"]`.
- Postseason pitcher starts are stored with a `game_type`, and
  `pitchers.league_fip_constant` (a calibration constant) skips non-regular
  rows. Rows without the key are regular season, i.e. every row written before.
- Not touched: sealed 2026-01-01..08-27 outcomes, fingerprinted card files,
  published records. The change restores what those were fit on (regular season
  only) rather than altering them; the frozen-parameter files are not re-fit.

Not fixed, flagged: `src/engine/features.py:639` (`_build_replay`) and
`settle_slate.load_mlb_results` read the store by `game_pk` for
event grading; postseason events can now grade where they used to void. That is
intended for the live card; whether any 2023-24 replay evaluation should
exclude postseason events is a research-gate decision, not a plumbing one.

## 4. What is implemented (branch `worktree-agent-ac5bbaf8330ffbaba`)

| File | What |
|---|---|
| `src/pipeline/store_freshness.py` (new) | `report(root, now)`: per store `through` (coverage, not newest game), `newest_row`, `rows`, `lag_days`, `stale`, `reason`, `reads`; `core_stale`; Eastern baseball date; standings horizon; memoised on (size, mtime) so `/health` re-reads nothing unchanged |
| `src/pipeline/display_refresh.py` (new) | `refresh()` (the catch-up), `main()` CLI (`--root --max-seconds --only --max-memory-mb --json --check`), `guard_tick` / `start_background_guard` / `guard_status` |
| `deploy/Dockerfile` | the build-time `RUN`, `ARG DATA_REFRESH_STAMP`, `ENV DISPLAY_REFRESH_GUARD_INTERVAL_SECONDS=3600` |
| `api/app.py` | startup hook for the guard (off unless the env var is set) |
| `src/appstate/apphealth.py` | `data_freshness` in `/health` (informational; never changes `status`, because a 503 takes the whole site out of rotation) |
| ~~`src/detect/dossier.py`, `src/pipeline/enrichment.py`~~ | **Superseded, see section 9.** The labels first lived in the dossier sections (`teams.results_through/results_stale`, `starters.logs_through/logs_stale`, per-club `bullpen.log_through/log_stale`). They are now a display fact: `store_freshness.coverage_for_game`, attached by `api/games.py` as `advanced.data_coverage`. The dossier sections are exactly what the feature builders return again |
| `web/js/gamestory.js`, `web/js/games.js` | the pages say it: "BULLPEN LOG ENDS SEPT 6", "PITCHER LOG ENDS SEPT 7", "days rest ... (counted from the log, which ends ...)", "N games - results end Sept 23". Only shown when the store ends before the game; a past game is not called stale because the store moved on. Read from `advanced.data_coverage` (section 9) |
| `src/providers/mlb.py`, `src/pipeline/pitchers.py` | `game_types` option (default: byte-identical request and rows) |
| `src/pipeline/features.py` | the training-table game-type filter |

`GET /health` after this deploys carries, for example:

```
"data_freshness": {"baseball_date": "2026-10-03", "expected_through": "2026-10-02",
  "core_stale": [], "stale": [], "oldest_core_through": "2026-09-27",
  "stores": {"mlb_results": {"through": "2026-10-02", "lag_days": 0, "stale": false, ...},
             "pitcher_logs": {...}, "bullpen_log": {...}, "standings": {...}, ...},
  "guard": {"enabled": true, "interval_s": 3600.0, "runs": 0, "last_result": "core stores current", ...}}
```

Verified live against the real Stats API (copy of the repo's stores, not the
repo): all four core stores went from stale to current; results through
2026-10-02 (today's game pending, correctly not counted), pitchers through
10-03, bullpen through 10-02, standings through 09-27 (season end).
`postseason_page.build` on disk data only: stale copy -> `available: False`;
refreshed copy -> `available: True`, `inputs_through` pitcher 10-03 / bullpen
10-02.

## 5. Tests

New (no network; the fake Stats API is installed at the single seam
`mlb._get_json`, so the real parsers run): `tests/test_display_refresh.py` (24),
`tests/test_store_freshness.py` (18), `tests/test_stale_data_surfaces.py` (13),
helper `tests/_fake_statsapi.py`. They pin: stale -> current incl. postseason;
postseason stored but never a training row; API down leaves every byte alone
and costs one call; a step that raises keeps its copy while others run; a
shrunk copy is refused; yesterday's bullpen replaced not duplicated; no
standings request after the regular season; no `P` aggregate request; work dir
never survives; watch/processed sentinels untouched; deadline promotes
progress and a second run finishes; guard off by default, runs only when
stale, respects a 30-minute gap, child is memory/time capped; `/health` field
informational; the Eastern rule equals the postseason page's over a year.

Run: those three plus ~53 neighbouring modules, 1,270 tests in all (history,
pitchers, bullpen, standings, features, postseason page, api
games/today/card/health/warmup, apphealth, card publish, engine, drift audit,
boundary, forward-store guard, web render) -- all green, forward-store
fingerprint check OK, except one failure
outside this work: `tests.test_f5_eval ...never_targets_the_real_frozen_family_path`
asserts a forward-slash path suffix and fails on Windows (backslashes); it does
not touch anything here.

## 6. What needs the owner

Nothing is blocking. The site converges on its own after the next deploy.

**Optional, one patch, `docs/decisions/deploy-prod-data-freshness.patch`**
(`git apply` verified clean against `deploy-prod.yml`):

1. Passes `--build-arg DATA_REFRESH_STAMP=$(date -u +%Y%m%d%H)` to `flyctl deploy`,
   so a redeploy of an unchanged commit cannot reuse the previous build's data layer.
2. After the app is up, reads `/health` and prints a `::warning::` when
   `data_freshness.core_stale` is not empty (a warning, never a failed deploy).
3. Without it nothing breaks: capture changes the build context hourly, and the
   in-container guard repairs any gap within minutes of start.
4. It does not touch the deploy timeout; `docs/decisions/deploy-timeout.patch`
   (15 min) is still the owner's, and a deploy now takes ~4 min + up to ~4.5
   min of refresh, well inside it.
5. The same two lines would apply to `deploy-staging.yml` if wanted.

**Decisions I did not take (they touch capture or the daily loop):**

- **Option (b), committing the refreshed stores**, would make the repo copy
  advance and builds incremental (today every build redoes the gap since the
  repo copy: ~3 s per game day of bullpen, 115-145 s now, growing until the
  World Series ends and then shrinking because off days are cheap). Doing it
  safely means running `display_refresh` inside a capture slot or the daily
  loop and staging the stores by name, with `lib_shrink_guard`. That is the
  capture critical path and the reason `daily_loop.sh` refuses to stage these
  files; I left it. If the build-time cost ever matters, that is the lever.
- Whether `daily_loop.sh:46` should keep `--game-types decisive` (it should;
  the reader-side filter is now what protects training).

## 7. How to verify from outside (no login)

```
curl -s https://linehound.app/health | python -c "import sys,json; d=json.load(sys.stdin)['data_freshness']; print(d['core_stale'], d['oldest_core_through']); [print(k, v['through'], v['stale']) for k,v in d['stores'].items()]"
```

Expect `core_stale == []`, `mlb_results` through yesterday (Eastern),
`pitcher_logs` through today, `bullpen_log` through yesterday, `standings`
through 2026-09-27 (the last regular-season day; a postseason date has no
table), and `guard.enabled == true`. A restart shows as a new
`runtime.started_utc`; `guard.runs` counts container refreshes.

On a game page for a game after a store's end the page now says so
("BULLPEN LOG ENDS ...", "PITCHER LOG ENDS ..."); on a game the stores do
cover there is no banner. `/postseason`'s "Pitcher numbers on file run through
..." line should read within a day of today.

## 8. Residual risks, stated plainly

- **Not exercised on Fly.** The Dockerfile step was run as its module, not as a
  `docker build`; I cannot reach the builder from here. Egress from Fly's
  builder to `statsapi.mlb.com` is assumed (pip already needs egress); if it is
  blocked the step prints a line and the image keeps the committed stores, and
  the guard tries again from the running container.
- **First request after a refresh** reads a file that was swapped in; readers
  open per call, and `os.replace` makes the swap atomic, but the TTL caches in
  `api/games.py` serve their last build until it expires (minutes).
- **Standings in the postseason** have no snapshots (the API gives none), so a
  postseason game page says "no standings snapshot for this date" -- true, and
  unchanged by this work.
- **MLB load:** ~250 pitcher-log requests per build, hourly, plus one schedule
  call per date. Free, unauthenticated, and all fail soft; reduce
  `PITCHER_ACTIVE_DAYS` in `display_refresh.py` if it is ever rate-limited.
  *(Second pass: the whole build is about 600 to 700 requests, most of them
  bullpen boxscores, and it repeats every hour because the committed copy never
  advances; that is the one remaining owner decision, section 9.)*

## 9. Second pass: what changed after the review, and the one owner decision left

The reviewed change (sections 1 to 8) and the reviewer's four fixes were brought
onto the then-current integration branch (`bfca21a8`) and the seven things the
review still found were closed. The cherry-picks applied with no textual
conflict. Three files auto-merged and were read for semantic overlap rather
than trusted: `api/app.py` (the analyst and live-state router mounts and the
guard's startup hook sit side by side), `deploy/Dockerfile` (`COPY config/` and
the refresh `RUN` step and `ENV`), `web/js/games.js` (the written read, live
strip, line prices and analyst section alongside `gamesSample`). Both sides'
behaviour is present in each.

Every item has a test that fails on the commit before its fix (counts below are
tests in the new or rewritten module that fail there).

| # | Review finding | Fix | Tests |
|---|---|---|---|
| 1 | Postseason pitcher starts, now stored and tagged, would flow into starter features for the live card preview, the analyst and `/postseason` pricing | `pitchers.regular_season_logs` applied AT each consumer (`enrichment_inputs`, `postseason_page.build`, the four `cli.py` loads); never inside `read_logs` | `tests/test_model_inputs_regular_season.py`, 19 (13 fail before; one walks the real refresh into the real loader) |
| 2 | "results end ..." was read off the newest game, so the day after a league-wide off day every page showed a false stale label | coverage from `store_freshness`, attached to the `/game` payload as `advanced.data_coverage`; the page reads it; the dossier is untouched | `tests/test_stale_data_surfaces.py` 25, `tests/test_game_page_coverage_web.py` 15 (28 fail before, with the review's moved test) |
| 3 | "Has not shrunk" compared totals; an empty answer for one pitcher replaced his season while the store grew | per-key promotion with a union for any key that would lose a record | `tests/test_display_refresh_keys.py`, 20 (16 fail before) |
| 4 | The 21-day and 75-day windows were relative to today, so the gap since the committed copy stopped being fetched | each window starts at the store's own coverage end minus an overlap | `tests/test_display_refresh_windows.py`, 17 (10 fail before, items 4 and 5) |
| 5 | The bullpen window reached back to 2026-07-20, inside the sealed window | every requested range starts no earlier than 2026-08-28; stored rows there are left as they are | same module |
| 6 | If memory truly runs out the kernel might kill the web server | the refresh child raises its own `oom_score_adj` to 1000 (Linux; no-op elsewhere) | `tests/test_display_refresh_guard.py`, 22 (21 fail before, items 6 and 7) |
| 7 | The guard waited for the first warm-up pass only, but the warm-up repeats every 600 s | a busy tick is skipped, not blocked on, and asked again in 60 s | same module |

### 1. Model inputs stay exactly as before: regular season only

The pitcher-log file now holds postseason starts, each tagged `game_type`. The
same file is read by every consumer that turns it into a model input, and one
Wild Card start moved a synthetic starter's ERA from 3.00 to 6.39 and changed
the card's pick for the game. `pitchers.regular_season_logs(logs)` is a pure
copy that drops tagged non-regular rows (markers survive, so a refresh still
reads as coverage; a pitcher left with nothing is absent, as in a store that
never held him). It is applied at the consumer, never inside `read_logs`:
`build_log_store` rewrites the whole file from `read_logs`, so a filter there
deletes October on the next refresh (pinned by a refresh round-trip test).

Consumers changed: `enrichment.enrichment_inputs` (the game pages, the live card
preview, the analyst), `postseason_page.build` (stored logs and any rows a
fresh-log fetcher returns; `api/postseason.py`'s fetcher asks for the regular
season only and needed no change), and the four `src/cli.py` loads. The
postseason page's "run through" date and currency rule now describe the rows the
model used, so no postseason start is shown unlabelled.

Separating display from model inputs was not small and clean (the dossier's
starters section is both the page's starter panel and the card's and the scan's
feature source), so the postseason starts are excluded from display too. The
cost, stated plainly: **a starter who threw in an earlier round shows days rest
counted from his last regular-season start** (6 days where he really has 2).
The page still says the log is current because coverage counts the refresh. It
is what the regular-season-only store gave before this work, and a display fix
would have to read the raw log for the date only and label it.

Proof the inputs did not move, on a store holding both kinds of row: the
enrichment inputs, the starters and teams sections, the card's features, the
published card payload (byte for byte) and the whole postseason page payload all
equal what the regular-season-only store gives.

### 2. Store-age labels are a display fact

Two defects. The labels were read off the newest GAME in a store, so a league-
wide off day made a current store look stale. And they lived in dossier sections,
which are model and ledger inputs: `card._flatten` merges `teams` and `starters`
into the card's features and the analyst freezes whole sections into its hashed
packet (`analyst_packet_v1`). **Measured against the starting HEAD, the labels
changed what the analyst freezes** (the `teams`, `starters` and `bullpen`
sections all hashed differently) while the card payload did not move. The review
did not name this; it is the reason the fix is a restoration and not only a
relocation.

`store_freshness.coverage_for_game(date)` reads what each store COVERS (the
results manifest, the pitcher refresh markers, the bullpen log's empty-day
markers) against one game's date; `api/games.get_game` attaches it as
`advanced.data_coverage` (a failure costs the labels, never the page);
`games.js` and `gamestory.js` read it. `dossier.build` and `enrichment_inputs`
are exactly what the feature builders return again.

**Proof that nothing a ledger reads moved** (hermetic, the real code path, the
starting HEAD against this branch, same synthetic stores):

```
                                         card payload      dossier sections
starting HEAD,   regular-season store    1d73e3af272f2543  28231e04540b4bc4
this branch,     regular-season store    1d73e3af272f2543  28231e04540b4bc4
this branch,     store holding both      1d73e3af272f2543  28231e04540b4bc4
the cherry-picks alone                   1d73e3af272f2543  820c401dd319a160   <- the analyst's input moved
starting HEAD,   store holding both      41ab88a4aee2dfff  979cb3393a3739a9   <- the leak item 1 closes
```

### 3. No key may lose a record when a copy is promoted

A key is whatever the store divides into: a pitcher-season, a date, a game, a
player. A key LOSES a record when the committed copy holds one under it that the
refreshed copy does not. Such a key keeps the UNION of the two (so a pitcher
whose answer is missing one old start still gets his new ones). Bookkeeping is
not a record: an empty-day marker never sits beside real rows, and an answer
that carried nothing never replaces a committed coverage marker, so the next
run asks again and a pitcher is not marked freshly checked on an empty answer.
The repair is made on the work copy, the committed file is only read, and what
was kept is in `report["restored"]` and the log. A copy that cannot be checked is
not promoted. Covered: pitcher logs, bullpen log, standings, transactions, the
results CSV and manifest, the splits and handedness caches. The two Savant
arsenal files keep the committed rows for a player who lost one instead of a
union (their rows are shares of one snapshot; a union double-counts). The totals
rule stays as the backstop. Cost on the repo's real stores: bullpen log 3.6 s and
about 100 MB peak, pitcher log 3.4 s and about 40 MB, after the step has freed
its own memory.

Two reviewed tests pinned the old consequence and were changed, not deleted: a
season survives an empty answer (it used to refuse the whole copy), and the
in-progress-game test now names the same game before and after (it used a
game the feed no longer listed, whose row is now kept).

### 4. The windows are anchored on coverage, not the clock

Bullpen: start at the earlier of the 75-day window and the log's newest date
minus 2 days, never before the log's first date (dates already held cost no
request). Pitchers: a starter is refreshed when the results show a start of his
on or after HIS OWN log's coverage end minus 2 days (his refresh marker, in
Eastern time, or his newest start); one never checked this season only if he
started in the last 21 days (a full-season backfill is `daily_bootstrap.sh`'s
job). One store-wide anchor would not work: a marker written for tonight's
starter would hide every other starter's gap, which is the failure being fixed.

### 5. The sealed window is never requested

`_unsealed_start` clips every range a step requests (results, bullpen,
standings, transactions) to start on 2026-08-28. Rows already stored in the
window are left exactly as they are, nothing is purged. The one answer not asked
for by date is a pitcher's game log (the feed returns a whole season), so the
committed sealed-window starts are put back over whatever the feed now says for
them; an appearance the store does not hold is left as the feed gave it. A
store whose coverage ends inside the window therefore has a hole before 08-28
that this refresh will not fill (none of the repo's stores do).

### 6 and 7. A 1 GB machine

The child sets `/proc/self/oom_score_adj` to 1000 (the maximum; raising your own
score needs no privilege) so that if memory truly runs out the kernel kills the
refresh, never the server. The write is injectable and a no-op off Linux, and a
failed write is a printed note. For the overlap, `guard_tick(busy=...)` returns
"skipped this cycle" at once when a warm-up pass or a page-cache rebuild is
running (`api/app.py` passes the warm-up's own status and
`src.appstate.freshness.build_stats()`, the existing one-build-at-a-time
counter), and the loop asks again in 60 s, not an hour later. The minimum-gap
rule is decided first; current stores never ask.

### Not fixed, stated

- **Days rest for a starter who threw in an earlier round** (item 1), above.
- **`read_context`** still reads the raw pitcher-log file for the written read's
  "our pitcher logs end ..." date, so that date can be a postseason start. It is
  a coverage claim, not a model input.
- **Research scripts** keep calling `pitchers.read_logs()`. Their training
  tables are regular-season games, their features are point-in-time and
  season-scoped and the FIP constant skips non-regular rows. **Any new consumer
  that prices a live game must call `regular_season_logs`.**
- **`bullpen.build_log`** writes an empty-day marker when every boxscore of a
  date fails, and resume then never retries that date. The refresh re-fetches
  yesterday only. Not touched (the daily loop shares that function).
- **A record the feed legitimately removes** now stays in the store until the
  committed copy advances (conservative by design).
- **Not exercised on Fly**, as in section 8: the oom write and the busy check
  were tested through injected seams, not in a container.

### The one remaining owner decision

An hourly rebuild re-fetches about 600 to 700 MLB Stats API requests every time
(about 300 bullpen boxscores, about 250 pitcher logs, the rest schedule and
standings calls, from the committed copy as it stands today), because nothing
advances the committed copy: every build repeats the whole gap since it, and the
gap grows each day until the postseason ends. The fix is to PERSIST the refreshed
stores, and it is the owner's because it touches infrastructure and capture:

1. a Fly volume for `data/historical` (the image's copy would have to be seeded
   into it and merged by union on each deploy), or
2. committing the refreshed stores from a capture slot or the daily loop with a
   union (`daily_loop.sh` refuses to `git add` them today, on purpose: a blind
   add deletes git-only rows), staged by name behind `lib_shrink_guard`.

Not implemented here. Until then the site is correct and current and each
build pays the catch-up; the per-key promotion and the coverage anchors above
are what make a persisted store safe to adopt.

### Verify

```
python3 -m unittest tests.test_display_refresh tests.test_display_refresh_review \
  tests.test_display_refresh_keys tests.test_display_refresh_windows \
  tests.test_display_refresh_guard tests.test_store_freshness \
  tests.test_stale_data_surfaces tests.test_model_inputs_regular_season \
  tests.test_game_page_coverage_web
```
