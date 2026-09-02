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
