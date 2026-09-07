# Autonomous product progress (append-only)

## 2026-09-06 23:1xZ — P0-1 first external capture run (Fable, bash; no workers)
- Default branch `claude/cowork-session-migration-tn3sx2` is an orphan (README + docs only), so `schedule`/`workflow_dispatch` could not see `.github/workflows/forward-capture.yml` (dispatch returned 404). Added the file verbatim there (25816b8; Option 2 of docs/CAPTURE_EXTERNALIZATION.md). The job still checks out and pushes only the working line.
- Dispatched run 34066005061: SUCCESS, 23:07:55–23:08:36Z, capture step 30s. Commit 16a2b97 by `forward-capture-bot`: 38 rows across data/watch (lineups, probables, transactions, umpires), weather_forecast, information_events, credit_log. Dense: 0 captures (no game inside the 180-min window at 23:08Z, correct), balance 24,889 before and after, band `live_capture`, no ESCALATE. Secret appears only as `***`. Staging redeploy dispatched (minute 08).
- Tests: none changed. Deployment: staging redeploy dispatched by the job. Blocker: none. Next: wait for the first `schedule`-event run (cron */15) with no interactive command; then in-session capture becomes fallback-only (launch only when the external heartbeat is older than 45 min).

## 2026-09-06 23:4xZ — P0-2 daily loop externalized to Actions (Sonnet worker, Fable verify)
- Landed 73d37dc from the worker's worktree: `scripts/daily_bootstrap.sh` (exit 1 + ESCALATE when the Statcast manifest is missing so `statcast --catchup` can never fetch a season on a runner; rebuilds mlb_results/pitcher_logs/bullpen_log from free MLB endpoints on a miss, ~9–10 min cold), `.github/workflows/daily-loop.yml` (cron 10:00Z + dispatch, checkout of the working line, same `forward-capture` concurrency group as capture slots so the two writers serialize at the Actions level, actions/cache for the git-ignored stores, ESCALATE lines fail the job, only secret `ODDS_API_KEY`), 17 new tests. Verified independently: 48 tests OK (`test_daily_loop_wiring`, `test_daily_bootstrap`, `test_deploy_scripts`). Worker worktree removed.
- Not yet: workflow file on the default branch (will follow once the cold-runner seed path exists); Statcast seed on a cold cache — a second Sonnet worker is building an orphan `data-seed/statcast` branch and a bootstrap fallback that restores from it before escalating.
- Full suite baseline (4,563 tests) reported 5 failures with details lost to stderr; re-running with output captured to identify them before the next push carrying code.
- P0-1 still waiting for the first `schedule`-event run: none by 23:42Z (slots 23:15/23:30 not fired — treated as first-registration delay per the cutover rule). In-session tracked capture stays available as fallback.

## 2026-09-07 00:1xZ — cloud Parent handoff to the local Parent (owner directive)
- P0-1: no `schedule` run by the 00:08Z deadline → SCHEDULER_INCIDENT (deterministic checks recorded in docs/LOCAL_PARENT_TAKEOVER.md §8). In-session capture stays fallback-only with the no-duplicate-spend checks.
- P0-2: 98a31ed seed fallback landed; daily-loop.yml registered on the default branch (2b63f0d); dispatched run 34068303330 proved cold-runner bootstrap, real output, bot commit 560f900, and the ESCALATE failure path. Scheduled proof pending.
- Suite rerun classified (2 NON-HERMETIC guard failures caused by a mid-run git pull; 2 bootstrap-test timeouts, candidate NON-HERMETIC, pass standalone). No regression identified; baseline not yet green-verified.
- No new workers dispatched. Handoff file: docs/LOCAL_PARENT_TAKEOVER.md.

## 2026-09-07 01:0xZ — P0-1 cron proven; cutover to FALLBACK-ONLY
- Genuine `schedule` run 34071611931 green (01:00:46Z, bot commit 0bc53ca). The cron simply took ~1h50m after registration to enqueue its first slot; the SCHEDULER_INCIDENT classification is withdrawn.
- Cloud hourly capture routine rewritten to fallback-only (skip when a bot commit or successful run exists within 45 min). One duplicated window (01:00Z) from the pre-cutover fallback is recorded in docs/OVERNIGHT_RUN.md; the fallback's rows were union-merged and pushed (4fc98fc).
- Local Parent (Brey's PC) is active on the working line (demo sprint commits 57d5ef8…37b47ce). No product work from the cloud session.
