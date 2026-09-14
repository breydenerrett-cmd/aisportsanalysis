# Forward-capture externalization (L25)

Five interactive-session container restarts on 2026-09-02 killed
`scripts/forward_capture.sh` mid-`dense` run each time. This document
answers whether forward capture can run independent of the interactive
Claude session/container, using infrastructure already in place.

## Facts

1. **`deploy-staging.yml` `paths:` filter includes `data/processed/**` and
   `data/watch/**`** (`.github/workflows/deploy-staging.yml:24-25`), so a
   data-only push from the interactive session already redeploys staging
   today. The comment at lines 21-23 confirms this is deliberate: staging's
   data is **baked into the image at deploy** (`flyctl deploy` in the same
   workflow, line 45) via a plain `COPY` in `deploy/Dockerfile`, not pulled
   at runtime and not on a volume — `[mounts]` in `deploy/fly.staging.toml`
   (lines 43-48) is only `app_data` → `APP_DB_PATH` (customer/auth sqlite),
   never `data/`.
2. The Fly app's secrets are exactly `APP_ADMIN_TOKEN`, `BILLING_PROVIDER`,
   `STRIPE_API_KEY`, `STRIPE_BETA_PRICE_ID`, `STRIPE_WEBHOOK_SECRET` (no
   odds-provider key). The odds key's env var name is `ODDS_API_KEY`
   (`src/providers/odds.py:45`, `ENV_KEY = "ODDS_API_KEY"`; also declared
   in `.env.example`). Nothing under `api/` reads it or calls
   `src/providers/odds.py` (`grep` of `api/` turns up only
   `ENV_ADMIN_TOKEN`/Stripe env reads) — **the web app never calls the odds
   provider**, so a Fly-side capture process would need this key added as a
   *new* Fly secret; it is not already there.
3. `python3 -m src.cli dense` already supports single-slot: `--captures 1
   --interval 0` (`src/cli.py:1927-1930`, wired straight into
   `dense.run(captures=args.captures, interval_minutes=args.interval, ...)`
   at `src/cli.py:1553`). `dense.run` (`src/pipeline/dense.py:279-361`) owns
   the loop internally, sleeping between captures only `if index <
   captures - 1 and sleep:` — with `captures=1` that branch never runs, so
   there is no in-process sleep at all; the call returns after exactly one
   capture. If the process is killed mid-loop and restarted, nothing is
   re-capture-aware by slot index: each `snapshots.capture()` call appends
   one row keyed by wall-clock `moment`, so a restart just resumes spending
   at the current time — no duplicate detection needed, no re-capture of
   "slots already on disk," and no silent skip; a genuinely missed window
   is reported via `MISSED_WINDOW_MINUTES` (`dense.py:129`,
   `_missed_windows`, `dense.py:688-719`), never fabricated.
4. `scripts/daily_loop.sh` (`python3 -m src.cli daily`) and
   `scripts/forward_capture.sh` both append to files under `data/watch` and
   `data/processed` and both commit under the same `/tmp/linehound_git.lock`
   (`daily_loop.sh:1-40`, `forward_capture.sh` tail) — JSONL appends,
   `git add` on directories (not full-file rewrites), fetch + `pull
   --rebase --autostash` before push. This is why four prior stranded
   commits happened before the shared lock existed (comment in both
   scripts) and why any second concurrent writer — a second machine, not
   just a second script — must use the *same* lock file and the *same*
   rebase-before-push discipline or reintroduce that race. `daily` needs
   nothing from gitignored `data/historical` that the capture path also
   touches (`daily_loop.sh` calls only `src.cli daily` and
   `src.pipeline.ledger`).
5. Runtime deps: a static-import scan of every module under `src/` finds
   **zero third-party imports** reachable from the capture path (`fastapi`
   only shows up in `api/`, which capture never imports) — stdlib only
   (`urllib`, not `requests`). Python 3.12 (`deploy/Dockerfile: FROM
   python:3.12-slim`, and GitHub's `ubuntu-latest` runners ship 3.12). A
   checkout without `data/historical` (which is itself only 4.0K and
   gitignored, so a fresh clone never has it) is ~50M total, 598 tracked
   files.
6. **The repository is public** (confirmed via the GitHub API by the
   orchestrator) — GitHub Actions minutes are unmetered for public repos,
   so both the existing hourly-loop shape (~45 min/run) and a 15-minute
   single-slot shape (~1-2 min/run) cost **$0** in Actions minutes either
   way. The only schedule caveat: GitHub disables a public repo's scheduled
   workflow after 60 days with zero repository activity — irrelevant here
   given `deploy-staging.yml` alone has run 80+ times today, but worth
   knowing if `data/watch` growth ever silently stops.
7. `GITHUB_TOKEN` pushes do not trigger other `on: push` workflows
   (GitHub's built-in loop-prevention rule) — so a capture workflow pushing
   with the default token would **not** re-trigger `deploy-staging.yml`
   even though its `paths:` filter matches. No PAT is required to work
   around this: an authenticated `workflow_dispatch` API call (needs only
   `actions: write` on the same default token, not a new credential) can
   explicitly re-fire the deploy job after a data-changing commit, which is
   what the implemented workflow does.

## Options

| | A. GitHub Actions cron (recommended) | B. Fly `capture` process group | C. Sidecar in web machine | D. In-session, commit-per-slot |
|---|---|---|---|---|
| **Reliability** | Independent of any interactive container; fresh checkout every run; a bad run doesn't affect the next. Fails only if GitHub Actions itself is down, or the 60-day-idle scheduler guard trips (not currently a risk). | Killed by every `fly deploy` restart to any process group in the app unless data pushes are excluded from the deploy trigger; single small machine is itself a single point of failure with no independent restart history yet. | Same restart exposure as B, plus a capture crash can take the customer-facing process down with it — couples data plane to product plane. | Still fully coupled to the interactive session/container — exactly the failure this task exists to remove. Reduces blast radius to one slot, doesn't remove the cause. |
| **Cost** | $0 — public repo, Actions minutes unmetered. | New spend: a small Fly machine (~$2-5/month) plus flyctl/API calls to run it. | $0 new machine, but couples data-plane crashes to the paid always-on web machine's uptime. | $0, but doesn't solve the problem. |
| **Credential safety** | `ODDS_API_KEY` as one repo Actions secret; GitHub's own `GITHUB_TOKEN` (scoped to `contents: write`, `actions: write` for this repo only, auto-revoked at job end) handles the push — no new long-lived credential to mint or store. Actions secrets are never printed in logs by default; `dense`/`creditlog` output was checked and prints only remaining-credit counts, never the key. | Needs the odds key as a **new Fly secret** *and* a separate GitHub push credential (fine-grained PAT or deploy key) that only the owner can mint — two new secrets, in two systems, with two different blast radii and two different revocation paths. | Same two-secret problem as B, but the git-push credential now lives on the same machine that serves customer HTTP traffic — larger blast radius if that machine is compromised. | No new secret, but also solves nothing. |
| **Data integrity** | Same JSONL append + shared-lock + rebase-before-push discipline as today (reused verbatim in `scripts/capture_slot.sh`); single external writer, `daily_loop.sh` stays the second writer it always was — no new conflict class introduced. Runs are serialized by the workflow's own `concurrency: group: forward-capture`. | Must reuse the same lock file across two machines (Fly machine + wherever `daily_loop.sh` runs) — flock is process/host-local, not distributed, so cross-host serialization would need a different mechanism than today's `/tmp/linehound_git.lock`, which is a real gap this option would have to solve, not just declare solved. | Same distributed-lock gap as B. | No new integrity concerns — nothing about the writer topology changes. |
| **Owner action needed** | Add `ODDS_API_KEY` as a **repository** Actions secret (Settings → Secrets and variables → Actions). Nothing else — the workflow is ready to run the moment the secret exists. | Owner must mint a fine-grained PAT (or deploy key), add it as a Fly secret, add `ODDS_API_KEY` as a Fly secret, approve ~$2-5/month new spend, and define a distributed-lock solution before this is safe to run alongside `daily_loop.sh`. | Same owner burden as B, plus rewriting the web entrypoint. | None — but this option is a mitigation, not the externalization the directive asked for. |

Option D is included only to name why it doesn't satisfy the directive: it
still terminates the moment the interactive container restarts. It's worth
keeping forward_capture.sh's own commit-per-slot behavior in mind as a
*complement*, but is not evaluated further as a standalone answer.

## Recommendation: Option A

GitHub Actions, scheduled every 15 minutes, running one capture slot per
invocation from a fresh checkout, pushing with the workflow's own
`GITHUB_TOKEN`. It needs no new spend (public repo), no new long-lived
credential (the only new secret is the same `ODDS_API_KEY` the capture
already needs, held by GitHub instead of a session's `.env`), and it
reuses today's JSONL-append + shared-lock + rebase discipline unchanged —
it is a second *instance* of the same writer pattern, not a new one.

Options B and C need real new spend and a real new credential (a PAT the
orchestrator cannot mint), and neither actually solves the distributed-lock
gap they'd introduce alongside `daily_loop.sh` — they're the right answer
only if the owner specifically wants the capture running on Fly for other
reasons, not because Actions can't do the job.

### Implementation (this worktree)

- `scripts/capture_slot.sh` — one forward-capture slot: watch poll, umpire
  poll, `python3 -m src.cli dense --captures 1 --interval 0` (one capture,
  no sleep), prop listing, `capture_extras.sh`, then the same
  lock/commit/fetch/rebase/push/escalate sequence `forward_capture.sh`
  already uses. `forward_capture.sh` itself is untouched and still usable
  by hand or as a rollback path.
- `.github/workflows/forward-capture.yml` — `cron: "*/15 * * * *"` +
  `workflow_dispatch`, `concurrency: group: forward-capture` (never
  overlaps itself), `permissions: contents: write, actions: write`, reads
  `secrets.ODDS_API_KEY` into the environment, runs `capture_slot.sh`, then
  dispatches `deploy-staging.yml` via the Actions API only when this run
  actually committed (fact 7's workaround).
- `tests/test_dense.py`: added
  `test_a_single_slot_run_captures_once_and_never_sleeps` — proves
  `captures=1, interval_minutes=0` does exactly one capture and never
  calls `sleep`.
- `tests/test_deploy_scripts.py`: added `scripts/capture_slot.sh` to
  `SHELL_SCRIPTS` (bash -n) and to `DATA_PLANE_SCRIPTS` (shared lock,
  rebase-before-push, escalate-on-push-failure checks) — it inherits the
  same invariant coverage `forward_capture.sh`/`daily_loop.sh` already have.
- `tests/test_deploy_single_writer_invariant.py`: **not changed.** That
  test protects `max_machines_running=1` on the *web* app because
  `src/appstate/ratelimit.py` and `src/appstate/freshness.py` hold
  in-process state per HTTP worker. A GitHub Actions capture run is not a
  Fly machine, not an HTTP worker, and never touches either in-process
  store — it has no bearing on that invariant, so touching this test would
  be scope creep, not a fix.

### Cutover sequence

1. Owner adds `ODDS_API_KEY` as a repository secret (Settings → Secrets
   and variables → Actions → New repository secret; same value currently
   in the main checkout's `.env`).
2. Merge/push this branch's changes (`scripts/capture_slot.sh`,
   `.github/workflows/forward-capture.yml`).
3. Manually fire the workflow once (`workflow_dispatch`, from the Actions
   tab or `gh workflow run forward-capture.yml`) and confirm one successful
   commit lands on the branch with new rows in `data/watch`/`data/processed`.
4. Only after step 3's commit is confirmed: disable the in-session hourly
   forward-capture trigger (the orchestrator's scheduled Routine calling
   `forward_capture.sh`) so there are not two writers spending odds credits
   against the same slot.
5. Leave `daily_loop.sh` in-session for now — it writes disjoint,
   once-a-day data (ledger/settlement), was never the thing failing, and
   moving it isn't asked for by the failure this task addresses. Revisit
   only if it starts missing runs the same way capture did.

### Rollback

Disable (not delete) `.github/workflows/forward-capture.yml` via
`workflow_dispatch`'s sibling — set `on.schedule` aside or disable the
workflow from the Actions tab — and re-enable the in-session hourly
Routine calling `forward_capture.sh`. `scripts/forward_capture.sh` was
never modified, so this is a same-day, zero-code-change rollback.

## OWNER DECISIONS / NEW SPEND REQUIRED

- **Add `ODDS_API_KEY` as a GitHub repository Actions secret.** This is
  the one action required either way (Option A or B) and no tool available
  here can create a repository secret. No dollar cost — same key already
  in use, just held by GitHub instead of a session's `.env`.
- No new spend: the repository is public, so Actions minutes for either
  the 15-minute single-slot cadence recommended here or the original
  45-minute hourly-loop cadence cost $0.
- If the owner would rather run capture on Fly (Option B) instead of
  Actions — e.g. to keep it on infrastructure already billed — that
  requires minting a fine-grained PAT (no tool here can do this) and
  approving ~$2-5/month for a small always-on machine, plus a real
  distributed-lock design before it's safe next to `daily_loop.sh`. Not
  recommended unless there's a reason beyond "get capture off the
  interactive session" to prefer it.

## What was not verified

- The exact GitHub plan tier beyond "public repo → Actions minutes
  unmetered," which came from the orchestrator's out-of-band API check,
  not from a document or workflow-run artifact inspected directly in this
  worktree.
- Whether the 60-day scheduled-workflow-disable guard has ever tripped on
  this repo (no evidence either way; noted as a caveat since it would look
  like a silent capture outage).
- Live behavior of the `workflow_dispatch` API call in
  `forward-capture.yml` (untested against a real GitHub Actions run — the
  workflow could not be executed from this worktree).


## Default-branch constraint (added at orchestrator review)

GitHub runs `schedule:` workflows only from the repository's DEFAULT
branch, and this repository's default branch is
`claude/cowork-session-migration-tn3sx2`, an orphan import that shares no
history with the working line `claude/sports-betting-analysis-review-g1o0co`
(GitHub also refuses a pull request between them for that reason). So the
workflow file merged into the working line will not be scheduled until one
of these happens:

1. **Recommended:** the owner repoints the repository's default branch to
   `claude/sports-betting-analysis-review-g1o0co` (Settings → General →
   Default branch). This also unblocks pull requests and the Claude
   Approvals surface. Nothing else changes.
2. Alternative: the workflow file (only) is pushed to the current default
   branch. The job already checks out the working line explicitly
   (`ref:` in `actions/checkout`) and dispatches deploys for it, so it
   works from either branch. Pushing to that branch needs the owner's
   go-ahead; the orchestrator does not push to branches other than the
   working line without it.

Until one of the two is done, `workflow_dispatch` runs are also only
available from a branch that carries the file; after (1) they are
available from the working line directly.

## Known follow-up: the daily loop as a second writer

`scripts/daily_loop.sh` still runs in the interactive session and appends
to the same JSONL stores. Two writers appending to the same file end can
produce a rebase conflict on whichever side pushes second; the daily loop
already fetches and rebases before pushing and prints `ESCALATE:` on a
conflict rather than corrupting anything, and the window is a few minutes
once a day. Moving the daily loop to a 10:00Z Actions job is the next
step once the capture job has run for a day; it needs the results ingest
(free MLB endpoint) to rebuild its git-ignored inputs in a fresh checkout.

## Daily loop externalization (P0-2)

The daily loop's turn: `scripts/daily_loop.sh` (`src.cli daily`, ledger
status, `statcast --catchup`, `gamekey`, `engine slate`, `engine settle`,
`eod`, then the same lock/commit/rebase/push discipline as
`capture_slot.sh`) now runs from GitHub Actions too
(`.github/workflows/daily-loop.yml`, `cron: "0 10 * * *"` +
`workflow_dispatch`), preceded by a new bootstrap step
(`scripts/daily_bootstrap.sh`) that makes a fresh, cache-restored checkout
usable without an interactive session ever having touched it.

### Why a bootstrap step, unlike forward capture

Forward capture's inputs are all TRACKED (the `!`-negated stores in
`.gitignore`: `data/processed/odds_snapshots.jsonl` and its siblings), so
`capture_slot.sh` needed nothing beyond a checkout. The daily loop's
inputs are mostly the opposite: `data/historical/*` is bulk-ignored, and a
fresh clone starts with none of it. Two of those inputs cannot be treated
the same way:

- **The Statcast pitch store** (`data/historical/statcast/`, ~45MB) has no
  cheap incremental path from nothing -- `catchup()` only ever extends an
  existing manifest, and the alternative, a full `build()`, is a ~45-window
  season backfill against Baseball Savant that this loop must never
  trigger on its own (see `scripts/daily_bootstrap.sh`'s own header and
  `src/providers/statcast_pitches.catchup`'s docstring). A missing manifest
  is therefore a **hard refusal** (`ESCALATE:`, exit 1), not a rebuild.
- **The season-scoped results/pitcher/bullpen stores** ARE cheaply
  rebuildable from MLB's free, keyless Stats API, and bootstrap does so on
  a genuine cache miss.

### Inputs table

| Input | Path | Source on a cache MISS | Measured cost | On a cache HIT |
|---|---|---|---|---|
| Statcast pitch store + manifest | `data/historical/statcast/` | none -- **hard refusal**, `ESCALATE:`, exit 1 | n/a | `statcast --catchup` (inside `daily_loop.sh`) extends it, ~1 free HTTP call/day |
| Season results | `data/historical/mlb_results.csv` + manifest | `src.pipeline.history.ingest_range(season_start, yesterday)`, free MLB endpoint | 0.31s/date measured locally -> ~51s for a ~165-day season | `daily_loop.sh`'s own ingest step adds just yesterday |
| Pitcher logs | `data/historical/pitcher_logs.jsonl` | `src.pipeline.pitchers.build_log_store` over every probable pitcher in the rebuilt results store, free MLB endpoint, one call/pitcher | 236 pitchers fetched in well under a minute (measured, 2026 season to date) | `daily_loop.sh` refreshes just today's probables |
| Bullpen log | `data/historical/bullpen_log.jsonl` | `src.pipeline.bullpen.build_log(season_start, yesterday)`, free MLB endpoint, one schedule + one boxscore call/game | 2.86s/date measured locally -> ~8 minutes for a ~165-day season (the slowest rebuild step) | `daily_loop.sh` refreshes just yesterday |
| Lineups / handedness cache | `data/historical/lineups.jsonl`, `data/historical/handedness.json` | not pre-populated -- `cmd_brief` (inside `daily`) fetches today's lineups/handedness live and self-heals on a cold cache | a few extra free calls on the first post-miss run only | `daily_loop.sh`'s brief step keeps it warm |
| `data/processed/l1_observations.jsonl` | tracked-store reprojection | not touched by bootstrap -- `engine slate`'s own `refresh_l1_if_stale` rebuilds it from the tracked odds stores immediately before reading it, every invocation | n/a | same |
| `data/processed/matchup_matrix.jsonl` | research store | not read by the daily loop at all (grepped: only `src/research/matrix.py`, `src/engine/features.py` docstrings, `src/evolab/*`) | n/a | n/a |
| `data/historical/odds_history/`, `odds_first_five/` | paid historical archive | not read by the daily loop at all (grepped: only backfill/replay/research call sites); the one near-exception, `first_five_results.jsonl`, is a frozen store settle already falls back away from for any season past 2024 | n/a | n/a |

### Cache key strategy

`.github/workflows/daily-loop.yml` uses `actions/cache` with:

- `path`: the six rebuildable/restorable git-ignored stores above
  (Statcast store, results CSV + manifest, pitcher logs, bullpen log,
  lineups, handedness).
- `key: daily-loop-data-${{ github.run_id }}` -- unique per run, so the
  save step never collides with (and therefore never silently no-ops
  against) a prior run's cache, since `actions/cache` keys are immutable.
- `restore-keys: daily-loop-data-` -- a prefix match, so restore always
  pulls the MOST RECENT prior run's save regardless of its exact run id.
- A separate `actions/cache/save@v4` step, run `if: always()`, saves
  forward under the same run-id key even if a later step (the loop itself,
  or the ESCALATE check) fails -- a bootstrap that ran a real rebuild this
  run should not be repeated tomorrow just because something unrelated
  failed after it.

Measured size: the Statcast store alone runs ~45MB; the CSV/JSONL logs
this task actually produces (results, pitcher logs, one season of
bullpen) are small text files, well under 50MB combined even at a full
season. Total cache payload stays far under the 1GB stop condition named
in the task that added this workflow.

### Statcast seed branch (`data-seed/statcast`)

An `actions/cache` MISS on a truly cold repo (first run ever, or a cache
eviction) used to leave `scripts/daily_bootstrap.sh` no option but the hard
refusal above -- there was nothing else to restore from. There is now a
second, git-native fallback: an orphan branch on origin,
`data-seed/statcast` (ref name overridable via
`AISPORTS_STATCAST_SEED_REF`), whose only content is a snapshot of
`data/historical/statcast/` (manifest + `pitches_*.jsonl.gz` windows) plus
a short README. When the manifest is missing, bootstrap now fetches this
branch and materializes the store from it (`git fetch origin
data-seed/statcast` + `git archive` into a temp dir, moved into place --
never a `git checkout` against the working tree) before falling through to
the same `ESCALATE`/exit 1 if that also fails. A successful restore prints
`STATCAST_SEED=restored from <ref> (<n> windows, last window <date>)`.

This branch is a **manual, out-of-band artifact** -- nothing in the daily
loop, or any other workflow, ever pushes to it. To refresh it (e.g. once it
has drifted far enough behind that a post-restore `statcast --catchup`
would be catching up too many days in one run): from a checkout with a
current `data/historical/statcast/`, in a separate temporary worktree,
redo the same orphan-branch steps (`checkout --orphan data-seed/statcast`,
remove everything, copy in the current store, commit) and force-push:
`git push -u origin data-seed/statcast --force`. See the branch's own
`README.md` for the full steps.

### Cold-start behaviour

On the very first run (or after a cache eviction that drops the Statcast
manifest specifically), `daily-loop.yml` fails fast at the bootstrap step
with an `ESCALATE:` line rather than attempting a season-long Savant
backfill unattended. Recovering from that state requires an operator (or
a one-time manual `python3 -m src.cli statcast --build <season>` run, then
letting the cache save it forward) -- this is a deliberate, documented gap,
not an oversight: unattended infrastructure should not be the thing that
decides to spend ~45 windows of Savant's free-but-rate-limited export on
its own initiative.

A cache eviction that drops only the results/pitcher/bullpen stores (the
Statcast manifest survives) self-heals in one run: bootstrap rebuilds all
three from free endpoints in on the order of 9-10 minutes total (dominated
by the bullpen rebuild), well inside the job's 30-minute timeout, and the
save step persists the rebuilt stores for every subsequent day.

### What still cannot run in CI, and why

Nothing in the daily loop's own step list is CI-incapable -- every step
(`daily`, `ledger status`, `statcast --catchup`, `gamekey`, `engine
slate`, `engine settle`, `eod`) already ran successfully from an
interactive session's ephemeral container, which has no more filesystem
persistence across restarts than a fresh Actions runner does. The one
genuine CI limitation is the Statcast **initial** backfill described
above: a multi-minute, rate-limited, resumable-but-not-designed-for-
unattended-retry season fetch. It is not automated here on purpose, the
same way `capture_slot.sh` deliberately never mints a new `ODDS_API_KEY`
on its own -- both are "an operator does this once, infrastructure keeps
it fresh forever after" boundaries, not gaps this task left unfinished.

## Self-chaining cadence (2026-09-14)

### Observation

`gh run list --workflow forward-capture.yml` on 2026-09-13/14: the
`*/15 * * * *` cron produced runs at 01:17Z, 06:32Z, 12:17Z, 16:32Z, 18:57Z,
21:19Z, 23:19Z, 01:21Z, 06:44Z, 13:23Z -- every 2-5 hours, not every 15
minutes. Slots near a 15-minute spacing existed only while the
orchestrator's session dispatched them by hand. A slot takes about two
minutes (run 34863237749: 15:36:09Z -> 15:38:04Z).

### Revision after review (same day)

The first build slept INSIDE the shared `forward-capture` concurrency group
(workflow-level group; spacing wait as the job's first step), dispatched at
the end of the slot, and stopped chaining whenever a rival was waiting. A
review walked three defects out of that:

1. **CI red.** `tests/test_capture_stages_what_it_writes.py` treats the one
   `run:` line naming `scripts/capture_slot.sh` as THE slot; the mode calls
   made it three.
2. **The chain died at every rival.** A rival queued while the chain slept ->
   the chain yielded and did not dispatch -> the rival ran -> nothing
   re-dispatched (afternoon-slate.yml and daily-loop.yml have no chain step).
   Only the cron copy (2-5 hours) restarted it -- a gap that can cover every
   first pitch on a night slate.
3. **More cancellation exposure, not less.** A chain sleeping in the group
   holds it ~13 minutes of every 13, so a rival that used to start at once
   now went pending nearly every day, where any forward-capture that queued
   after it without checking (the default branch's cron copy; a hand
   dispatch) cancelled it. The sleep's one-minute poll did not cover the
   capture / lineup / slate steps.

All three are fixed by the design below rather than by patches: the wait no
longer holds the group.

### Design

`forward-capture.yml` has two jobs and NO workflow-level concurrency:

    pace     (no group)   1. --space-only  sleep until prev_slot_start + spacing
                          2. --chain-only  dispatch the next run   (if: always())
                          3. --gate-only   wait until no rival waits in the group (LAST)
    capture  (job-level group forward-capture; needs: pace;
              if: !cancelled() && needs.pace.outputs.yielded == 'false')
                          the slot, unchanged

The dispatch is:

    gh workflow run forward-capture.yml --ref claude/sports-betting-analysis-review-g1o0co \
        -f capture_now=0 -f prev_slot_start=<this slot's start epoch> -f spacing_minutes=<13|60>

`workflow_dispatch` events created with `GITHUB_TOKEN` do start runs
(GitHub's loop-prevention rule exempts `workflow_dispatch` and
`repository_dispatch`); the workflow already had `actions: write`. The
logic lives in `scripts/capture_slot.sh` (`--space-only`, `--chain-only`,
`--gate-only`, and an exit trap), so the workflow, the cron copy and any
future caller share one tested implementation
(`tests/test_capture_no_set_time.py`, which runs the real script against a
fake `gh` and a fake `sleep`).

Job-level and workflow-level concurrency groups share one namespace per
repository (GitHub docs, "Using concurrency": "a single job or workflow
using the same concurrency group"), so the capture job still serialises
against afternoon-slate and the default branch's cron copy, both of which
use a workflow-level `forward-capture` group. Docs-level (tier-1) evidence;
not yet observed on this repo.

### The constraints, and how each is met

**(a) Never cancel a waiting daily-loop or afternoon-slate.** GitHub keeps
one running and one pending entry per group, and a newer pending entry
cancels the older. Two rules make a chained or hand-dispatched slot of this
branch unable to do that:

- The dispatch cannot cancel anything: the run it creates holds no group
  until its capture job, which queues only after `--gate-only`, at least 13
  minutes later. So `--chain-only` no longer checks rivals at all.
- `--gate-only`, the last step before the capture job queues, reads the
  newest 50 runs and waits (one read a minute, outside the group, blocking
  nobody) while a `daily-loop` or `afternoon-slate` run on any branch is
  `queued`, `pending`, `waiting` or `requested`. `pending` is what a
  group-held run reports. When nothing waits it outputs `yielded=false` and
  the capture job queues. A rival still waiting after 30 minutes costs THIS
  slot (`yielded=true`), never the rival; an unreadable queue for 30 minutes
  also skips the slot and turns the step red (`gate: BROKEN`).

daily-loop stays on the rival list although this branch's `daily-loop.yml`
moved to its own `daily-loop` group on 2026-09-14 (another track,
docs/DAILY_LOOP_REPAIR_2026-09-14.md): cron runs the DEFAULT branch's copy,
whose group this branch cannot see or change.

Residual exposure, stated:

- **The gate race**: seconds between the gate's last read and the capture
  job queuing (the gate is the last step of `pace` to keep it that short).
- **The default branch's cron copy** queues into the group without passing
  any gate (its YAML cannot be edited from here). It can cancel a rival that
  is pending. That was true before the chain too; what the chain changes is
  how often a rival is pending. With the wait outside the group, the group
  is held only while a slot actually runs (about 2 minutes, longer when a
  lineup triggers a slate pass), so a rival at 15:40Z goes pending only if it
  lands inside a running slot, and is then cancelled only if a cron-copy
  firing (every 2-5 hours) lands inside the remaining minutes of that slot.
  Estimate, not measured: low single-digit percent of days at most.
- **A hand dispatch of the default branch's copy** (`gh workflow run
  forward-capture.yml` WITHOUT `--ref`) behaves like the cron copy. Always
  pass `--ref claude/sports-betting-analysis-review-g1o0co`; that copy goes
  through the gate and is safe while a rival waits.
- A chained capture job pending behind something can be replaced by a newer
  pending entry (a later chained slot, a cron-copy run, a rival queuing).
  That loses one slot, never the chain -- the dispatch already happened.

**(b) Spacing.** `--space-only` sleeps until `prev_slot_start +
spacing_minutes` (13 on game days). Bounded both ways: spacing is clamped to
13-60 minutes, and the wait never exceeds one spacing interval even for a
start epoch in the future. 13 rather than 15 because a dispatch takes tens
of seconds to become a running job and `capture_slot.sh` widens the dense
window on the first slot of each hour (minute < 15): every gap has to stay
under 15 minutes for no hour to miss that widening. The sleep never reads
the queue and never skips the slot -- it holds no group, so a rival is
irrelevant to it. The capture job starts after the wait, so its checkout is
current (the old "catch the checkout up" step is gone). The `pace` job's
timeout is 100 minutes (60 spacing + 30 gate + margin).

**(c) Hand vs chain.** A chained dispatch is also a `workflow_dispatch`
event, so `github.event_name` no longer tells them apart. Input
`capture_now` (default `'1'`); the chain sends `0`; the capture step sets
`CAPTURE_NOW: ${{ github.event_name == 'workflow_dispatch' && inputs.capture_now == '1' && '1' || '' }}`.
The comparison is spelled out because the string `'0'` is truthy in an
Actions expression. `gh workflow run forward-capture.yml --ref <branch>` with
no `-f` still means CAPTURE_NOW=1, with no spacing wait (it still passes the
gate).

**(d) Chains cannot multiply.** The group no longer bounds chains (the
waiting part is outside it), so the dispatch does: `--chain-only` does not
dispatch when a NEWER live (`queued`/`pending`/`waiting`/`requested`/
`in_progress`) forward-capture run of this branch exists
(`CHAIN_SELF_RUN_ID` = `github.run_id`). Every run is live while it
dispatches, so of two live chains the older sees the newer and stands down
and the newer dispatches: they collapse to one at the first dispatch point.
Example: a hand dispatch H lands while chained run R sleeps. H dispatches
H2; R wakes, sees H2 (newer) and does not dispatch. Each run dispatches at
most once (the capture step sets `CHAIN_BY_WORKFLOW_STEP=1` so the script's
exit trap stays out of it). The slots themselves stay bounded by the group:
one running, one pending. `cancel-in-progress` stays `false` on the capture
job and in afternoon-slate.yml. If the run queue cannot be read at dispatch
time, the chain dispatches anyway: blind, it risks a duplicate chain that
the next readable check collapses, while not dispatching would leave no
slots until cron, hours later.

**(e) A failed slot does not end the chain.** The dispatch runs in `pace`,
BEFORE the slot, as `if: always() && vars.CAPTURE_CHAIN != 'off'`. A failed,
skipped or cancelled slot cannot touch it. A rival waiting in the group no
longer ends the chain either (review defect 2): the run waits at the gate
and the chain carries on, so afternoon-slate.yml and daily-loop.yml need no
chain step. A dispatch that cannot happen (no gh, no token, API refusal)
exits 1 and prints `chain: BROKEN`, so the run is red rather than the
cadence quietly stopping, and the capture job still runs (`!cancelled()`).
Because `always()` also runs after a cancellation, cancelling a run does
NOT stop the chain. Kill switches: repository variable `CAPTURE_CHAIN=off`;
a committed `.github/CAPTURE_CHAIN_OFF` file (the only one that reaches the
cron copy); or disabling the workflow in the Actions tab.

**(f) Quiet hours.** Before dispatching, the chain reads the MLB schedule
(free, keyless) for yesterday, today and tomorrow by UTC date -- a superset
of today's and tomorrow's slate that covers every first pitch inside 26
hours. No game starting within the next 26 hours -> `spacing_minutes=60`. An
unreadable schedule keeps 13: a missed slot on a game day costs more than a
few extra slots on an off day. In-season, a day with any game tomorrow is
never quiet; this bites on off days, the All-Star break and the offseason.

### The default-branch problem, and what it means for the backstop

`schedule:` runs the DEFAULT branch's copy of `forward-capture.yml`
(`claude/cowork-session-migration-tn3sx2`), which this branch cannot change,
which has no chain step and no gate, and which passes no token to the
script. A `--ref <working branch>` dispatch runs THIS branch's copy.
Consequences:

1. **Cron's YAML cannot restart a dead chain.** It does run this branch's
   `scripts/capture_slot.sh`, so the script chains from an EXIT trap
   whenever `GITHUB_WORKFLOW_REF` names a `forward-capture.yml` from a
   branch other than the working branch, as a RESTARTER
   (`CHAIN_RESTARTER=1`): it dispatches only when NO live run of this
   branch's forward-capture exists. The token comes from the checkout's
   persisted credential (`actions/checkout@v4` stores the job's
   `GITHUB_TOKEN` as `http.https://github.com/.extraheader`); never printed.
   **Unverified on a real runner.** If the credential is not there, the
   script prints `chain: BROKEN -- no token` and the cron slot captures
   without chaining.
2. So the backstop is: the chain dies (runner failure inside `pace`, a
   refused dispatch, an Actions outage), and the next cron firing -- 2 to 5
   hours later on the evidence above -- captures a slot and restarts it.
   The worst-case gap is the cron's real interval, never worse than before.
   Rivals no longer kill the chain, so that gap is no longer a daily event.
3. The cron copy itself stays ungated (see (a), residual exposure).
4. If the owner repoints the default branch to the working line, cron runs
   this file, the script's trap stands down (the workflow ref is the working
   branch), and cron runs go through `pace` like any other run.

### For the orchestrator while hand dispatches continue

- Hand dispatches of THIS branch's copy (`--ref claude/sports-betting-analysis-review-g1o0co`)
  pass the gate and are safe while a rival waits. Never dispatch without
  `--ref`.
- A hand dispatch while the chain runs costs nothing extra: the chains
  collapse at the next dispatch point (d).
- To stop hand-dispatching: confirm two consecutive `workflow_dispatch` runs
  whose `pace` log shows `chain: dispatched the next slot` -- that is the
  chain surviving past its first hop.

### Costs, stated

- ~4.4 slots an hour instead of ~0.3. Dense is still gated by its 180-minute
  window (1440 on the first slot of each hour), its credit floor and budget
  guard; props by their own phase windows. Schedule and queue reads are free
  (gate: one read a minute only while a rival waits).
- Two staging redeploys in one hour become possible (slots at :01 and :14
  both pass the workflow's `minute < 15` check).
- Actions minutes: $0 (public repo). A `pace` job is an idle runner for up
  to 13 minutes (60 in quiet hours); at most a couple are alive at once.

### Not verified

No workflow was dispatched from here. Unverified until a live run: that a
job-level group and a workflow-level group with the same name serialise
against each other (documented); that `gh run list` reports group-held runs
as `pending` (the gate checks `queued`, `pending`, `waiting` and
`requested`); that the job-level `if` sees `needs.pace.outputs.yielded` as
the string `'false'`; the checkout credential in the cron copy; and that a
dispatch made by a dispatched run keeps chaining past the first hop.
