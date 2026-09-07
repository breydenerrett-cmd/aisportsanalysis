# LOCAL PARENT TAKEOVER — handoff from the cloud Parent

Written 2026-09-07 00:1xZ by the cloud Parent on Brey's "EMERGENCY LOCAL TAKEOVER
HANDOFF" directive. Everything below was verified by command at write time;
re-verify the git facts first (they change every 15 minutes when capture works).

## NEXT ACTION FOR LOCAL PARENT

Start the 3–4 hour hosted-demo sprint from `claude/sports-betting-analysis-review-g1o0co`
at HEAD 560f900 (or later bot commits), using `docs/BETA_GAP_ASSESSMENT.md` §"biggest gap"
as the build list: bridge `evidence/decisions_v2.jsonl` / paper wagers / settlements into
`api/today.py` + `web/index.html` so slate → opportunities → game detail → Bet Check →
paper performance render from real data; treat the P0-1 scheduler incident (§6) only as
a background check, not a blocker.

## 1–5. Repository facts (verified 2026-09-07 00:07Z)

| Fact | Value |
|---|---|
| Repository | `breydenerrett-cmd/aisportsanalysis` (`git remote -v`: origin https://github.com/breydenerrett-cmd/aisportsanalysis, fetch+push) |
| Active working branch | `claude/sports-betting-analysis-review-g1o0co` (`git branch --show-current`) |
| Default branch | `claude/cowork-session-migration-tn3sx2` (orphan: README, docs, and the three workflow files only; shares no history with the working line) |
| HEAD | `560f900 Daily loop 2026-09-07` (author `daily-loop-bot`, written by Actions run 34068303330) |
| Tree | clean (`git status --short` empty) at 00:07Z. The full test suite was still running in the cloud container; when it finishes it rewrites `docs/FACTORY_OVERLAP_REPORT.md` (timestamp only). That diff is noise: never commit it. See §11. |
| Worktrees | none besides the main checkout (`git worktree list` = 1 entry). Two worker worktrees were removed after their commits were cherry-picked. |
| Data seed branch | `data-seed/statcast` @ 7063c7b (orphan; 184 files, ~45 MB: `data/historical/statcast/` manifest + gz windows). Used by `scripts/daily_bootstrap.sh` on a cold runner. Never merge it. |

## 6. Recent commits on the working line (newest first) and what each did

| SHA | Author | What |
|---|---|---|
| 560f900 | daily-loop-bot | First Actions-run daily loop (dispatched, 00:04Z): odds snapshot, boxscores, `docs/eod/2026-09-06.md`, 96 decisions + 48 paper wagers for 2026-09-07, forward ledger rows. Committed and pushed by the runner. |
| 98a31ed | Claude | `daily_bootstrap.sh` restores the Statcast store from `data-seed/statcast` before escalating; 4 hermetic tests; doc note. |
| 2a0fdeb | Claude | Queue/progress docs: P0-2 VERIFYING. |
| 73d37dc | Claude (Sonnet worker) | P0-2: `scripts/daily_bootstrap.sh`, `.github/workflows/daily-loop.yml` (cron 10:00Z + dispatch, shared `forward-capture` concurrency group, actions/cache), 17 tests. |
| 101a90f | Brey | Merge PR #2 (foundry heartbeats: `scripts/foundry_beat.sh`, `.foundry/events.jsonl`). |
| 16a2b97 | forward-capture-bot | First external capture slot commit (dispatched run 34066005061, 23:08Z): 38 rows, 0 credits. |
| 76140d5 / 18f9344 | Claude | Sunday daily-loop fixes: gamekey refresh before slate, settle resolves `game_pk` from the map; data refresh. |
| e20f751 | Claude | P0-4 + P1-1 (BETA_ACCEPTANCE_CRITERIA, gap assessment). |

Default branch commits: 25816b8 (forward-capture.yml registered), 2b63f0d (daily-loop.yml registered).

## 7–8. GitHub Actions workflows and runs

| Workflow | id | State | Trigger | Notes |
|---|---|---|---|---|
| forward-capture | 351854301 | active | cron `*/15 * * * *` + dispatch | Registered on the default branch 23:07Z. Runs `scripts/capture_slot.sh` on the working line; commits as `forward-capture-bot`. |
| daily-loop | 351871548 | active | cron `0 10 * * *` + dispatch | Registered 23:5xZ. Bootstrap (seed restore + free rebuilds, ~6 min) then `scripts/daily_loop.sh`; commits as `daily-loop-bot`; any `ESCALATE:` line fails the job. |
| deploy-staging | 347146949 | active | push on data/watch paths + dispatch | `flyctl deploy -c deploy/fly.staging.toml -a linehound-staging`. Needs `FLY_API_TOKEN`. |
| tests | 343677549 | active | push | unittest matrix (3.10/3.11/3.12). |

| Run | Workflow | Event | Result | Meaning |
|---|---|---|---|---|
| 34066005061 | forward-capture | workflow_dispatch | SUCCESS 23:07–23:08Z | Secret consumed (shows `***`), commit 16a2b97, balance 24,889 before/after, no ESCALATE. |
| **none** | forward-capture | **schedule** | **0 runs by the 00:08Z deadline** (slots 23:15…00:00 all missed) | **P0-1 = SCHEDULER_INCIDENT.** Verified: workflow `state=active`, file on the default branch with the cron, Actions enabled (push-triggered `tests` runs fire), repo not archived, `GET /actions/runs?event=schedule` = 0 for every workflow. Not verifiable from the cloud: the repo Actions settings page (proxy blocks `/actions/permissions`). Next checks for the local Parent: (a) open Settings → Actions → General and look for a "scheduled workflows disabled" notice; (b) look again at 01:00Z — GitHub often takes up to an hour to enqueue a freshly registered cron and delays `*/15` heavily under load; (c) if still zero, fallback options are an external pinger calling `workflow_dispatch` with a fine-grained PAT (Brey decision: new credential) or keeping the in-session capture routine as the primary. Until proven, in-session capture stays the fallback (see §9). |
| 34068303330 | daily-loop | workflow_dispatch | FAILURE 23:57–00:04Z (by design) | Bootstrap SUCCESS on a cold runner: seed restored, results/pitcher/bullpen rebuilt from free endpoints (6 min). Daily loop ran and **committed/pushed 560f900**. Then the ESCALATE gate failed the job honestly: `engine settle` refused 2026-09-06 because two games (game_pk 823903, 824552) had no final result at 00:04Z (West-coast games in progress) — correct refusal at that hour, not a bug. At the real 10:00Z slot this does not apply. Failure path proven; cache saved under key `daily-loop-data-34068303330`. |
| 34068256960 | tests (push of 98a31ed) | push | FAILURE on the 3.10 job only | `tests/test_v2_manifest` "fields_used with no substring match" (37 of 106). The commit touched only bootstrap files; the same test passed on the 3.11/3.12 jobs and on every earlier push tonight. Unclassified — candidate NON-HERMETIC (version-dependent ordering) or STALE EXPECTATION. Do not call it pre-existing without checking. |

## 9. Capture state (forward capture)

- External path works when dispatched (run 34066005061). Cron unproven (§8).
- Last capture heartbeat commits: `16a2b97 Forward capture slot 23:08Z (external)`, `655f82d Forward capture 22:32Z` (in-session). Helper: the capture-health check keys on the latest commit matching `^Forward capture`.
- In-session fallback rule (owner's cutover rule, still in force): before any in-session capture spend, check (1) a newly arrived `schedule` run, (2) a `forward-capture-bot` commit in the last 45 min, (3) the git lock `/tmp/linehound_git.lock`. Only launch `scripts/forward_capture.sh` as a harness-tracked background task, never `nohup … &`. Never let a late cron create a duplicate purchase.
- Cloud-session routines that still fire into the OLD cloud session (Brey may want to pause them once the local Parent owns capture): hourly forward-capture at :15, staging monitor at :48, weekend cycle at :35, daily loop 10:00Z. List with `list_triggers` from that session or the Routines UI.
- Credits: balance 24,889 at 23:08Z (`data/processed/credit_log.jsonl`). Observation: the `daily` snapshot inside `daily_loop.sh` does NOT append to credit_log (only dense/props/derivative capture do), so the 560f900 snapshot spend is not in the log — read the authoritative balance from the provider header before paid work.
- Duplicate-writer risk to keep in mind: `engine slate` dedups on `(event_id, system_id, market_key, selection_id, decision_utc)`; a second slate run for the same date at a different time writes a second set of frozen decisions/wagers. With both the Actions cron (10:00Z) and the in-session 10:00Z routine alive, only ONE should run `daily_loop.sh` per day. Tonight's dispatched run already wrote 2026-09-07 decisions at 00:04Z; the 10:00Z run will add another set on a fresher board. Decide which scheduler owns the daily loop before 10:00Z, or accept the double set for one day and note it in `docs/OVERNIGHT_RUN.md`.

## 10. Daily-loop state

- Implementation landed (73d37dc, 98a31ed); workflow registered on the default branch (2b63f0d); one dispatched run proved bootstrap on a fresh runner, real output, bot commit/push, and the failure path (ESCALATE → red job). NOT yet proven: a genuine `schedule` run at 10:00Z, and a green run (needs the 10:00Z hour so settlement inputs exist). Queue status: P0-2 VERIFYING.
- `docs/AUTONOMOUS_PRODUCT_QUEUE.md` and `docs/AUTONOMOUS_PRODUCT_PROGRESS.md` are the running ledgers; update them, do not restart them.

## 11. Test baseline (5 failures, classification status)

- Full suite (`python3 -m unittest discover -s tests -q`, 4,563 tests, ~30 min in the cloud container) reported `FAILED (failures=5, skipped=2)` at 23:3xZ, with the failure details lost (stderr not captured). A rerun with output captured was still running at handoff time (started 23:42Z, log at the cloud scratchpad `suite.log`; not reachable locally). **Classification not done** — see the bottom of this file for a late addendum if the rerun finished before the cloud session stopped.
- Known suite impurity: `tests/test_factory_overlap_report.py` regenerates `docs/FACTORY_OVERLAP_REPORT.md` (timestamp) and dirties the tree. Owner ruling: fix the test to write to a temp/ignored path or make it deterministic; acceptance is a clean `git status` after two identical full-suite runs. Not yet done. Until then: `git checkout -- docs/FACTORY_OVERLAP_REPORT.md` after a run, never commit it.
- CI: `tests` on Python 3.10 failed on 98a31ed in `test_v2_manifest` (§8) while 3.11/3.12 passed.

## 12–14. Worktrees, uncommitted files, blocked/unfinished tasks

- Worktrees: none extra. Uncommitted files: none at 00:07Z (see §5 for the factory-report noise that appears after a suite run).
- BLOCKED_HUMAN: W4 full-game ML T-2h comparator purchase (~4–5k credits) — needs Brey's spend approval.
- SCHEDULER_INCIDENT: P0-1 cron proof (§8).
- VERIFYING: P0-2 (needs one scheduled 10:00Z green run).
- READY, not started (do not start from the cloud): P0-3 ops status/reliability, P1-2 slate experience / engine-decisions-to-product bridge, P1-3 Bet Check verdicts, P1-4 signal registry, P1-5 evidence tiers, P1-6 performance area, P1-7 demo mode, P1-8 staging verification; P2-1/P2-2 DEFERRED. Test-purity cleanup (§11) is a bounded task waiting on the failure classification.

## 15–17. Deployment, paths, routes

- Staging URL: https://linehound-staging.fly.dev (Fly app `linehound-staging`, config `deploy/fly.staging.toml`; `/health` returned 200 at 23:48Z). Production config exists (`deploy/fly.production.toml`) but is not the demo target.
- Backend: `api/app.py` (FastAPI) with routers in `api/today.py`, `api/games.py`, `api/odds.py`, `api/betcheck.py`, `api/mybets.py`, `api/digest.py`, `api/billing.py`, `api/signup.py`, `api/onboarding.py`, `api/admin.py`, `api/support.py`, `api/funnel.py`, `api/health.py`, `api/meta.py`, `api/web.py`. Analysis payloads: `src/analysis/*payload*.py`, price engine `src/analysis/prices.py`. Engine ledgers: `evidence/decisions_v2.jsonl`, `evidence/paper_wagers_v2.jsonl`, `evidence/eod_reviews_v2.jsonl`, `docs/eod/<date>.md`.
- Frontend: `web/` (`index.html` app, `landing.html`, `admin.html`, `css/`, `js/`), served by the API at `/web/…`, `/app`, `/`.
- Container: `deploy/Dockerfile` (`uvicorn api.app:app --host 0.0.0.0 --port 8000`, `APP_DB_PATH=/app/data/app/app.db`).
- Routes (verified by grep): `GET / /app /web /web/{path} /today /games/{date} /game/{date}/{away}/{home} /odds/{date} /odds/{date}/{away}/{home} /changed/{date} /digest /my-bets /meta /health /onboarding /billing/status /signup/complete /admin/overview /admin/users /admin/funnel /admin/support`; `POST /betcheck /betcheck/free /my-bets /signup /support /funnel/event /billing/checkout /billing/cancel /billing/reactivate /billing/webhook /admin/invites /admin/support/{id}/status`; `DELETE /my-bets/{bet_id}`.
- Biggest product gap (from `docs/BETA_GAP_ASSESSMENT.md`): engine decisions / paper wagers / reviews / scorecards never reach the product API; no performance view; no ranking/filter; no demo-mode labelling. Honesty invariant: no live system is `model_derived`, so "model probability" must render as the market-derived calibration reference or "NO INDEPENDENT MODEL YET", and `edge_bps` stays null; value is only price-vs-consensus (Engine 1).

## 18–19. Commands

Run locally (Windows PowerShell; Python 3.11+):
```
git clone https://github.com/breydenerrett-cmd/aisportsanalysis
cd aisportsanalysis
git checkout claude/sports-betting-analysis-review-g1o0co
python -m pip install -r api/requirements.txt -r requirements.txt
python -m uvicorn api.app:app --host 127.0.0.1 --port 8000 --reload
# open http://127.0.0.1:8000/app   (health: /health, slate: /today)
```
Tests: `python -m unittest discover -s tests -q` (full, ~30 min) or targeted modules, e.g. `python -m unittest tests.test_daily_bootstrap tests.test_engine_slate -q`. `scripts/ci.sh` runs the smoke tests against a real uvicorn.

Deploy staging: push to the working line touching `data/watch/**` (auto), or dispatch `deploy-staging` in the Actions tab, or locally `flyctl deploy -c deploy/fly.staging.toml -a linehound-staging --remote-only --yes` with `FLY_API_TOKEN` set. Runbook: `deploy/DEPLOY_RUNBOOK.md`, `deploy/STAGING.md`.

## 20. Secrets required (names only — never values)

- GitHub Actions repository secrets: `ODDS_API_KEY` (installed; consumed by forward-capture and daily-loop), `FLY_API_TOKEN` (deploy-staging).
- Process environment (see `deploy/secrets.md`, `.env.example`): `ODDS_API_KEY`, `ODDS_API_REGION`, `ODDS_API_MARKETS`, `ODDS_API_ODDS_FORMAT`, `DEFAULT_BOOK`, `APP_DB_PATH`, `APP_ADMIN_TOKEN`, `AISPORTS_DATA_DIR` (optional), `AISPORTS_STATCAST_SEED_REF` (optional), Stripe keys as named in `deploy/secrets.md` for billing (not needed for the demo).
- Local `.env` on the PC must be created by Brey; nothing in the repo holds a value.

## Addendum 00:16Z — suite rerun finished (4,563 tests, `FAILED (failures=2, errors=2, skipped=2)`)

The first run's 5 failures were never captured (stderr lost) and cannot be reconstructed; the rerun is the authoritative list. Classification, with the evidence:

| Test | Result | Category | Evidence |
|---|---|---|---|
| `test_zz_forward_store_guard … (store='odds_snapshots.jsonl')` | FAIL | NON-HERMETIC TEST (external write during the run) | The guard hashes forward stores at suite start and end. Mid-run the cloud Parent pulled bot commit 560f900, which appended 30 rows to `odds_snapshots.jsonl` (+30 lines in the assertion) and 224 rows to `odds_multibook.jsonl`. Not a code regression. Re-run with no pulls during the suite to confirm. |
| `test_zz_forward_store_guard … (store='odds_multibook.jsonl')` | FAIL | NON-HERMETIC TEST | Same cause as above. |
| `test_daily_bootstrap.DailyBootstrapRefusesOnMissingStatcastManifestTest.test_refuses_with_escalate_and_nonzero_exit` | ERROR (`subprocess.TimeoutExpired`) | NON-HERMETIC TEST (candidate) — timing under full-suite load, or the test file changing mid-run | These two tests passed standalone at 23:55Z (`52 tests OK`) after 98a31ed pointed them at a nonexistent seed ref. The full suite started at 23:42Z, before that commit was cherry-picked, so discovery may have imported the older test against the newer script (which fetches the real seed branch and then hangs on the MLB rebuild in the sandbox). Re-run the module alone locally; if it passes, the category stands. |
| `… test_refuses_before_touching_any_other_store` | ERROR (`TimeoutExpired`) | Same as above | Same. |

No REAL REGRESSION was identified, but "suite green" is NOT yet a beta baseline: the local Parent should run the full suite once with no concurrent git pulls, confirm zero failures, and only then apply the FACTORY_OVERLAP_REPORT purity fix (§11).

## Addendum 01:0xZ — P0-1 cron PROVEN; cloud capture routine is FALLBACK-ONLY
- Scheduled run 34071611931 succeeded at 01:00:46Z → bot commit 0bc53ca. §8's SCHEDULER_INCIDENT is withdrawn: first-slot enqueue delay was ~1h50m.
- The cloud session's hourly capture routine (trig_016uRqogxtFdQZSs67DJRada) now only launches when no bot commit / successful run exists in the last 45 min. The 00:15Z fallback overlapped the 01:00Z slot once (≈20 credits); rows union-merged in 4fc98fc.
- Remaining P0-1 evidence to collect: a second consecutive scheduled run (01:15Z), and one observed overlap where the `forward-capture` concurrency group queues a run.
