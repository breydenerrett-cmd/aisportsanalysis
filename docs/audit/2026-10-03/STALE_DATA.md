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
  mid-step promotes the progress made, which resumes next run.
- **An unreachable API costs one 8-second probe.** Fetch timeout 10 s.
- **Zero odds credits.** MLB Stats API and Baseball Savant only. It never
  opens `data/watch`, `data/processed`, `evidence`, any card file or any odds
  store (sentinel-checked in `tests/test_display_refresh.py`). It adds only
  dates after each store's own newest date, plus a 14-day results lookback --
  today that is 2026-09-09 onward, nowhere near the sealed 2026-01-01..08-27
  window -- and it never rewrites an existing outcome (results merge by
  `game_pk`, and a copy with fewer rows is refused).
- **Bounded:** default budget 270 s split across eight steps by weight with
  unused time rolling forward; the Dockerfile adds `timeout 330` and `||
  echo`, so the build cannot fail or hang on it. Measured live, 2026-10-03,
  from the stale repo copy: **115-145 s cold**; steady state is shorter.

What each step does (all resumable from the store's own coverage record):

| Step | Catches up | Notes |
|---|---|---|
| results | every date since the manifest's newest, min 14-day lookback | `DECISIVE_GAME_TYPES` (postseason stored); scope-aware resume re-fetches an R-only date once |
| bullpen | missing dates in a 75-day window; **yesterday re-fetched whole** | `build_log` skips a date once any row exists, so a game in progress at the last fetch was lost for good |
| pitchers | starters of the last 21 days + the next 3 days' announced probables | refresh mode (12 h), postseason starts included, each tagged `game_type` |
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
| `src/detect/dossier.py`, `src/pipeline/enrichment.py` | `teams.results_through/results_stale`, `starters.logs_through/logs_stale`, per-club `bullpen.log_through/log_stale` |
| `web/js/gamestory.js`, `web/js/games.js` | the pages say it: "BULLPEN LOG ENDS SEPT 6", "PITCHER LOG ENDS SEPT 7", "days rest ... (counted from the log, which ends ...)", "N games - results end Sept 23". Only shown when the store ends before the game; a past game is not called stale because the store moved on |
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
