# What runs on the runners without a chat (evidence, 2026-10-05 23:30Z)

Read-only. Sources: `gh run list`, `gh run view <id> --log` for the last three
completed daily-loop runs (line numbers below are lines of that `--log`
output), the commits those runs pushed, `scripts/daily_loop.sh`,
`src/pipeline/store_persist.py`, `src/pipeline/display_refresh.py`. Nothing was
cancelled, pushed or edited outside `docs/audit/2026-10-06/` and the test runner.

## Step by step

| Step | Runs without a chat? | Evidence |
|---|---|---|
| Collection (daily loop: results, pitcher logs, bullpen, display refresh, NFL/UFC) | Yes. `daily-loop.yml` has `cron: "0 10 * * *"` and `workflow_dispatch`. Observed: the 10:10Z runs are `workflow_dispatch` and the `schedule` runs started at 15:00Z (10-04) and 18:53Z (10-05), hours after the 10:00Z cron, so GitHub's schedule is late and the dispatch is what lands on time. | Run 37359392088 (schedule, 2026-10-05 18:53Z, success): `[2/9] ingest results` line 225, `[3/9] ... 400 pitcher(s) fetched ... 82 deferred by budget` line 229, `display refresh: 5 request(s) made, 4 reused` line 903, `== committed ==` line 920, `Cache saved` line 951. Runs 37294855477 and 37211391954 also success. |
| Capture (odds snapshots) | Yes. `forward-capture.yml` has `cron: "*/15 * * * *"` and chains itself by `workflow_dispatch`. | 37385969413 success 23:00Z; 37387236829 and 37388496855 in progress at 23:26Z (event `workflow_dispatch`). Daily loop's own snapshot: run 37359392088 line 223 "captured 12 observations across 4 events". Branch history shows "Forward capture slot 23:05Z (external)" commits. `live-window.yml` is dispatch-only; run 37371255359 has been in progress since 20:41Z. |
| Grading | Yes, inside the daily loop. | Run 37359392088: `[6/9] settle` line 245, `[7/9] grade` line 248, `engine settle` line 540, `card settle` lines 663-673, `ufc autograde + settle` line 722, `live settle` line 739. Analyst grade lines 676-679 (see table below). |
| Brief writing (analyst "today's analysis") | NO. It needs a live session or `ANTHROPIC_API_KEY`. The runner does not have the key. | All three runs print `analyst: ANTHROPIC_API_KEY is not set; today's analysis was not run (docs/decisions/AI_ANALYST_ENABLE.md)`: run 37359392088 line 680, 37294855477 line 701, 37211391954 line 699. Grading of earlier briefs still runs. |
| Deploy to staging | Yes, no chat. `deploy-staging.yml` triggers on `push:` (line 13) and `workflow_dispatch` (line 52); forward-capture dispatches it hourly. | Runs 37386503456 (23:05Z), 37381118434 (22:14Z), 37379702078 (22:01Z), 37361437831 (19:10Z): all success, event `workflow_dispatch`. |
| Deploy to prod | Dispatched without a chat: `forward-capture.yml:369-395` posts to `deploy-prod.yml/dispatches` on the first slot of the hour when the latest CI run passed. It does not finish reliably (next section). | See stuck-deploy section. Last good prod deploy finished 21:12Z; `prod_watch.py` at 23:27Z: "same process since 2026-10-05T21:10:06". |

## The last three completed daily-loop runs

| Run id | Started (UTC) | Display stores committed (commit) | Deferred? | Analyst grade step | Upstream requests by the display refresh |
|---|---|---|---|---|---|
| 37359392088 | 10-05 18:53 | 4 of 10: `arsenals/batter_2026.json` (+1/-1), `arsenals/pitcher_2026.json` (+1/-1), `pitcher_logs.jsonl` (+10 rows), `transactions.jsonl` (+9/-7). Commit 5761d9767; log line 917 "staging 4 MLB display store(s)", line 920 "== committed ==". The other six printed `unchanged`. | No. No `DISPLAY STORE NOT PERSISTED`, no `rebase conflicted`, no `ESCALATE: push`/`rebase` line. | Ran. `grade 2026-10-04: published=0 graded=0`; `[pilot] published=2 graded=0 complete=2`; `2026-10-03` both zero (lines 676-679). Today's analysis not run (line 680). | 5 made, 4 reused, 0 failed, 0 empty (line 903). |
| 37294855477 | 10-05 10:10 | 10 of 10, first persist: `bullpen_log.jsonl` +2605, `handedness.json` +45, `mlb_results.csv` (+9819/-9748, a whole-file rewrite), `mlb_results.manifest.json` +192, `pitcher_logs.jsonl` +2314/-266, `pitcher_splits.json` +7237/-866, `standings.jsonl` +570, `transactions.jsonl` +660, `arsenals/*` (+1/-1 each). Commit 6c7215107; log line 938 "staging 10", line 941 "== committed ==". | No. | Ran. `[pilot] published=2 graded=2 complete=2` (line 698); others zero; today's analysis not run (line 701). | 326 made, 4 reused, 0 failed, 2 empty (line 924). |
| 37211391954 | 10-04 15:00 | None. The run predates `store_persist` (commits bb85fb5cd..e7fdd2357 landed 08:39-11:05 PT on 10-04, after this run's 15:11Z commit); commit 66f22c45f touches no `data/historical` file. Line 906 "== committed ==". | Not applicable (no persist step existed). | Ran: grade 2026-10-03 and 2026-10-02, both zero published (lines 697-698). Today's analysis not run (line 699). | No display-refresh step in the log. |

`data/watch/display_store_deferred.jsonl` does not exist on the branch: no
deferral has ever been recorded, so there was nothing for a later run to
reconcile. "nothing to commit" never printed in these three runs (every one
committed). The two ESCALATE lines in run 37359392088 (lines 850-867) are the
known STRONG-tier and falsification-battery items; `escalations.py` reports
`known=2 new=0` (line 927).

One thing not investigated: `mlb_results.csv` in the 10-05 10:10 commit rewrote
9,748 lines to 9,819 rather than appending. It is the first persist, so it is
likely a one-time column or line-ending normalisation, but I did not diff it.

## If a deferral happens, where does the payload live?

Answer: only in the runner's temporary workspace. It is lost when the runner
shuts down. It is not committed and it is not in the Actions cache.

Code path (all in `scripts/daily_loop.sh`, function
`pull_rebase_dropping_display_conflicts`):

- Line 856-859: `git reset --soft HEAD~1`, then each conflicting
  `data/historical/*` store is unstaged, so it is left out of the commit.
- Line 869-871: `store_persist record --deferred ...` writes the ledger line.
- Line 886-889: the dropped store is copied to
  **`/tmp/display_store_conflict/<basename>`** (line 887), then restored to the
  committed copy (`git checkout -- "$f"`, line 888). `/tmp` on a hosted runner
  disappears with the VM.
- What the ledger keeps is counts only: `src/pipeline/store_persist.py:489-504`
  (`_count_deferred`: `rows_on_disk`, `rows_in_remote`, `rows_only_ours`) and the
  row written at line 528. It never stores the rows. This matches the owner
  ruling quoted in `daily_loop.sh:807-815` ("a small committed record").
- Not in the cache either: the cache-save step runs after the loop and saves the
  working-tree files (`data/historical/pitcher_logs.jsonl`, `...` list shown in
  run 37359392088 lines 929-940). After the drop the working tree holds the
  remote's copy (line 888 plus the rebase at 894), so the cache carries the
  version that won, not ours.

Is it data loss? Not proven, so no test or fix was written (the brief allowed
edits to `store_persist.py` / `daily_loop.sh` only if loss is proven):

- The stores are reproducible. `display_refresh.py:22-35` documents that each
  step refills what is missing from the free MLB API (results since the store's
  last covered date, bullpen missing dates within a 75-day window anchored on
  the log's own coverage, every missing standings snapshot, transactions since
  the newest stored). The union keeps every row git holds, so sealed-window
  rows (2026-01-01..2026-08-27) are never at risk.
- The owner chose counts-only on 2026-10-04; carrying the payload would reverse
  that ruling.
- No deferral has happened on the runner in the last three runs, so there is no
  live case.

Residual risk, stated plainly: if a deferred store held rows the API can no
longer return (or rows older than a refresh window), they would be gone. I did
not replay a deferral to test that. If the owner wants the payload kept, the
smallest change is to commit the delta rows (`rows_only_ours`) as a uniquely
named file under `data/watch/display_store_deferred/` in the same commit (a new
path cannot conflict on rebase); that edits `daily_loop.sh` and reverses the
ruling, so it is a decision, not something I applied.

## Reads through `DataClient` (measured locally)

`DataClient(mlb=MlbService(fetch_games=<counting wrapper around the real
provider>)).schedule("mlb", date="2026-10-04")`, 50 reads in a row:

| Measure | Result |
|---|---|
| Upstream requests (wrapper count and `counters["schedule_requests"]`) | **1** (the cold read, 1.45 s) |
| The other 49 reads, total | 0.03 s, 0 requests, `item_builds` 0 |
| Same 50 reads spread over 588 s with a fake provider and a fake clock | 5 requests (one per 120 s TTL, `service.py:59`) |

So fifty unchanged reads inside the TTL cost one upstream request; a steady
reader costs at most one per 120 s per date.

## The stuck production deploy (run 37379705528, not cancelled)

- State at 23:27Z: `in_progress`, started 22:01:02Z, 86 minutes.
- The job's steps 1 to 5 (secret guard, app guard, checkout, setup-flyctl) all
  succeeded by 22:01:38Z. **Step 6, "Deploy"
  (`flyctl deploy -c deploy/fly.production.toml -a linehound-prod --remote-only --yes`,
  `deploy-prod.yml:61-64`), has been in progress since 22:01:38Z.** Health check
  (step 7) and container logs (step 8) are pending.
- The log is not readable while the run is in progress: `gh run view --log` says
  "logs will be available when it is complete" and the job-log API answers 404
  `BlobNotFound`. So I cannot name the line; the step is the evidence.
- Same signature as `docs/audit/2026-10-03/PROD_DEPLOY_HANG.md`: a stalled
  `fly deploy`, no `timeout-minutes` on the job (`deploy-prod.yml:34-37` has none,
  and `cancel-in-progress: false` at line 32), so later dispatches queue behind it.
  `docs/decisions/deploy-timeout.patch` is still not applied.
- It is not a one-off today. Prod deploy runs on 10-05: 37329482693 started
  15:01Z and ended 21:03Z as `cancelled` (six hours, GitHub's job limit);
  37361442396 started 19:10Z and succeeded only at 21:12Z (2 h 02 min);
  37381121913 (22:14Z) was cancelled at 23:05Z by the next dispatch;
  37386506276 (23:05Z) is `pending` behind the stuck run. Production's newest
  odds were 2.8 h old at 23:27Z.
- `scripts/prod_watch.py` worked: "BREACH production deploy: a run has been
  unfinished for 86 min (normal is about 4); later deploys wait behind it". No
  defect found, so it was not edited.

## Not done

- No deferral replay; no fix to `store_persist.py` or `daily_loop.sh`.
- Run logs were saved to the session scratchpad, not the repo.
- The stuck deploy was not cancelled and its log could not be read.
