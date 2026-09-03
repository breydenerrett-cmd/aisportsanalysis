# E — Autonomy: what survives 7 days with no interactive Claude session

## 1. GitHub Actions forward-capture: built, not yet running

`.github/workflows/forward-capture.yml` exists: `cron: "*/15 * * * *"` +
`workflow_dispatch`, runs `scripts/capture_slot.sh` with `ODDS_API_KEY`
from `secrets.ODDS_API_KEY`, commits/pushes, then conditionally dispatches
`deploy-staging.yml`.

Two blockers, both stated in `docs/CAPTURE_EXTERNALIZATION.md`:

- **Scheduled workflows only run from the repo's default branch.** This
  repo's default branch (`claude/cowork-session-migration-tn3sx2`) is an
  orphan sharing no history with the working line
  (`claude/sports-betting-analysis-review-g1o0co`) where the workflow file
  lives. Doc section "Default-branch constraint": until the owner either
  repoints the default branch or pushes the workflow file to it, the
  schedule never fires (`workflow_dispatch` only works from a branch that
  carries the file).
- **No `ODDS_API_KEY` repository secret.** Doc's "OWNER DECISIONS" section:
  "no tool available here can create a repository secret." Without it the
  workflow — even once scheduled — runs but `dense`/`prop_listing`/`prop_prices`
  all report "not configured" and no-op (per the workflow file's own header
  comment).

**Has any Actions run ever succeeded?** Unknown / blocked — this task has
no GitHub API access and the doc says the same under "What was not
verified": "Live behavior of the `workflow_dispatch` API call ... untested
against a real GitHub Actions run — the workflow could not be executed
from this worktree." No claim of a successful run exists anywhere in the
docs inspected.

## 2. In-session Routines: Claude-routine dependent, confirmed

`docs/RUNBOOK.md` "What runs on its own" table (its own heading is
aspirational, not accurate as built):

| cadence | what | how |
|---|---|---|
| hourly | watch + dense odds + F5 close | "trigger runs `bash scripts/forward_capture.sh`" |
| daily 10:00 UTC | snapshot/ingest/brief/settle/grade | "trigger runs `bash scripts/daily_loop.sh`" |
| 4-hourly | autonomous build loop (roadmap) | "model session, works docs/ROADMAP.md" |

"trigger" here is a Claude Code Remote Routine bound to a model session —
not an OS cron, not a Fly process. `scripts/forward_capture.sh` itself
does no scheduling; it is a single-pass script invoked once per call
(`set -uo pipefail`, runs watch → umpires → dense → prop listing → extras
→ commit, then returns). Nothing in the script re-arms itself or sleeps
until next hour — the hourly cadence is entirely the external Routine
calling it, confirmed by `docs/CAPTURE_EXTERNALIZATION.md` fact 4's
description of "the orchestrator's scheduled Routine calling
`forward_capture.sh`." `docs/COMMAND_CENTER.md:72` separately references an
"hourly health monitor" Routine. All of these stop the moment the
interactive session (and the Routines bound to it) is gone for 7 days —
there is no independent process executing them.

## 3. Fly.io: web app only, no scheduled process

- `deploy/Dockerfile`: `CMD ["uvicorn", "api.app:app", ...]` — one process,
  the FastAPI web app. `data/processed/` and `data/watch/` are `COPY`'d
  into the image at **build time** (baked snapshot), not mounted or
  refreshed at runtime; `[mounts]` in both `deploy/fly.staging.toml` and
  `deploy/fly.production.toml` is only `app_data` → `APP_DB_PATH` (the
  sqlite user/auth store), never `data/`.
- `[http_service] max_machines_running = 1` in both fly.toml files (comment:
  sqlite is not built for concurrent writers, so this is a correctness
  constraint, not a sizing one) — reinforces there is exactly one process,
  the web server.
- No Fly "process groups," no `[processes]` block, no cron/scheduler
  section in either fly.toml.
- `api/` never imports `src/providers/odds.py` — confirmed in
  `docs/CAPTURE_EXTERNALIZATION.md` fact 2 ("grep of `api/` turns up only
  `ENV_ADMIN_TOKEN`/Stripe env reads") — so the deployed web app cannot
  itself capture odds even if left running for years.
- `docs/SAAS_APPLICATION_ARCHITECTURE.md`'s systemd-timer / worker /
  scheduler diagram (lines ~950-990, "aisports-capture.timer",
  "aisports-daily.timer") is an explicitly future, VM-hosted proposal
  ("The existing scripts **become** scheduled jobs") — not built, and not
  what's on Fly. **Conclusion: only the web app runs on Fly; no scheduled
  capture or settlement process exists there.**

## 4. Per-item classification

| Item | Class | File (or "none") |
|---|---|---|
| Odds capture (dense grid) | CLAUDE ROUTINE DEPENDENT (workflow built, not scheduled — see §1) | `scripts/forward_capture.sh` → `src/pipeline/dense.py`; `.github/workflows/forward-capture.yml` (not yet live) |
| Prop capture (listing/prices) | CLAUDE ROUTINE DEPENDENT (same gate) | `src/pipeline/prop_listing.py`, called from `forward_capture.sh` |
| Weather | CLAUDE ROUTINE DEPENDENT | "capture extras" step in `scripts/forward_capture.sh` (free, 0 credits, but still only runs when the script is invoked) |
| Lineup/roster/transaction timing | CLAUDE ROUTINE DEPENDENT | `python3 -m src.cli watch`, called from `forward_capture.sh` |
| Umpire capture | CLAUDE ROUTINE DEPENDENT | `src/pipeline/umpirewatch.py`, called from `forward_capture.sh` |
| Settlement/grading | CLAUDE ROUTINE DEPENDENT | `scripts/daily_loop.sh` → `python3 -m src.cli ledger` (daily Routine); `src.board.settle_props.settle` exists but "not wired into the CLI or the daily loop yet" per `docs/RUNBOOK.md` |
| Daily slate analysis / briefing | CLAUDE ROUTINE DEPENDENT | `scripts/daily_loop.sh` (`src.cli brief`) |
| Strategy generation | MANUAL | `python3 -m src.cli analyze` (RUNBOOK "Common operations" — invoked by hand) |
| Strategy simulation/sweeps | MANUAL | referenced via `scripts/time_tests.py`/sweep scripts run by hand; no scheduled trigger found |
| Paper betting | NOT BUILT (as automated) / MANUAL | `src.board.settle_props` exists but unwired (see settlement row); no autonomous paper-bet placement loop found |
| EOD review | CLAUDE ROUTINE DEPENDENT | folded into `scripts/daily_loop.sh` (settle/grade steps) |
| Website deployment | TRULY EXTERNAL / PERSISTENT (once deployed) | `.github/workflows/deploy-staging.yml` (GitHub Actions, `paths:` filter on `data/processed/**`, `data/watch/**`) → `flyctl deploy`; Fly machine then serves independent of any Claude session |
| Health monitoring | CLAUDE ROUTINE DEPENDENT | "hourly health monitor" Routine (`docs/COMMAND_CENTER.md:72`); `python3 -m src.cli health` run manually/by Routine, not by an external cron |
| Research sweeps | MANUAL | ad hoc `python3 -m src.cli` invocations per `docs/RUNBOOK.md`; no scheduled trigger found |
| 4-hourly build loop (roadmap) | CLAUDE ROUTINE DEPENDENT | Routine described in `docs/RUNBOOK.md` line 9; works `docs/ROADMAP.md`, no script/workflow backs it |

Note: `deploy-staging.yml` itself is TRULY EXTERNAL only for the *deploy*
step — it is triggered by a data push, and today those data pushes come
from the interactive session's Routine-driven `forward_capture.sh`/
`daily_loop.sh` commits, not from anything independent. So even the "web
app stays up" fact is currently downstream of the Claude Routines for
*fresh* data; the already-deployed image itself will keep serving stale
baked-in data for 7 days regardless.

## 5. Blocking owner action and what remains Claude-dependent after it

Single blocking action per `docs/CAPTURE_EXTERNALIZATION.md`'s
"OWNER DECISIONS / NEW SPEND REQUIRED" and Option-comparison table:

> **Add `ODDS_API_KEY` as a repository Actions secret** (Settings → Secrets
> and variables → Actions). "This is the one action required either way
> (Option A or B) and no tool available here can create a repository
> secret."

Plus the separately documented **default-branch fix** (repoint default
branch, or push the workflow file to the current default branch) — without
either, the schedule never fires regardless of the secret.

Even after both are done, per the doc's own scope note ("Known follow-up:
the daily loop as a second writer" and step 5 of the cutover sequence),
these stay Claude-routine dependent:

- **Daily loop** (`scripts/daily_loop.sh`: ingest, briefing, settle, grade)
  — doc: "Leave `daily_loop.sh` in-session for now ... Revisit only if it
  starts missing runs the same way capture did." No Actions workflow for
  it exists.
- **Settlement** — folds into the daily loop above; `settle_props.settle`
  remains unwired regardless of capture's status.
- **Sweeps / strategy simulation** — never mentioned as a candidate for
  externalization anywhere in the doc; no workflow targets it.
- **4-hourly build loop and health-monitor Routines** — out of scope for
  `CAPTURE_EXTERNALIZATION.md` entirely (it addresses only forward
  capture).

So the one owner action only externalizes odds/prop/weather/lineup/umpire
**capture**. The daily loop, settlement, and all sweeps remain fully
Claude-Routine dependent even after it.
