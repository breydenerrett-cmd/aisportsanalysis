# Operations runbook — uptime, recovery, backups, deploy failures

Written after the 2026-09-01 staging outage (~13:35-18:30 UTC): Fly
suspended `linehound-staging` for a missing billing card on the account,
so the edge accepted TCP but reset TLS on every request. The hourly
monitor caught it (or would have, under this file's hardened version of
it) but the cloud session running the monitor had no Fly credentials to
recover the app itself — recovery needed a human with `fly auth login`
access. This file exists so the NEXT outage, of whatever class, has an
exact decision tree instead of another multi-hour scramble.

**Scope note:** this document is for Launch Ops / Brey to execute. No
agent session in this program holds Fly credentials by design (see
`deploy/DEPLOY_RUNBOOK.md` Step 0's scoped-token rationale) — every
`fly` command below is something to run from a human's authenticated
shell, never something an agent should attempt on its own.

## 1. Decision tree by failure class

`scripts/monitor_remote.sh` (hardened 2026-09-01) now prints a failure
class in brackets, e.g. `DEGRADED[TLS_RESET]`. Use that class to jump
straight to a branch below instead of guessing from a raw curl exit
code.

| Class | curl exit | What it means | First move |
|---|---|---|---|
| `TLS_RESET` | 35 | TCP connects, TLS handshake fails/resets. **This is the exact signature of a Fly-suspended app** (2026-09-01's cause) — the edge still answers the port but the app behind it never gets a chance to terminate TLS. | §2a: check Fly account/app status first. |
| `RECV_RESET` | 56 | Connection drops mid-transfer — same family as `TLS_RESET` (often the identical underlying reset, classified differently by curl depending on exactly when the reset lands) and a mid-request crash/OOM kill are both possible. | §2a, then §2b if account/billing checks out. |
| `CONN_REFUSED` | 7 | Nothing is listening on the port at all — the machine is fully stopped, not suspended-but-listening. | §2b: check machine state, then redeploy/restart. |
| `DNS` | 6 | The hostname itself doesn't resolve — app deleted, DNS misconfigured, or a typo in the monitored URL. | Confirm the URL first (`grep app deploy/fly.staging.toml`); if the app is genuinely gone, this is a rebuild-from-Step-1 situation, not a restart. |
| `TIMEOUT` | 28 | Connects (or tries to) but never completes within `MONITOR_REMOTE_TIMEOUT` (10s default). Could be Fly-side network trouble or the app hung processing a request. | §2b: check machine + recent logs for a hang, not a crash. |
| `EMPTY_REPLY` | 52 | Server accepted the connection and sent nothing back. | Usually a process that died between accept() and response — check logs for a crash right at that timestamp. |
| `HTTP_503` | n/a | The app is UP and its own `/health` reported a real failure — see the printed reasons (from `api/health.py`'s `reasons` list: forward-store issues, odds provider, etc). | This is an application-level degradation, not an infra outage — do NOT restart/redeploy reflexively; read the reasons first (§3). |
| `HTTP_5XX` (other than 503) | n/a | The app is up but erroring on `/health` itself in an unexpected way. | Check `fly logs` for a stack trace before doing anything else. |
| `HTTP_4XX` | n/a | Unexpected — `/health` is not authenticated and should never 4xx. Possibly a routing/proxy misconfiguration change. | Check `deploy/fly.staging.toml`'s `[http_service]` and any recent deploy diff. |

### 2a. Billing/suspension check (the 2026-09-01 cause)

```bash
# From a human's own `fly auth login` session (never an agent's):
fly auth whoami
fly apps list                      # does linehound-staging still appear?
fly status --app linehound-staging # machine state: started/stopped/suspended?
```

If the Fly dashboard shows a billing/payment banner or the app's machines
show as stopped with no crash in the logs, this is billing suspension —
fix the card on Fly's dashboard, then:

```bash
fly apps restart linehound-staging
# or, if restart doesn't bring it back:
fly machine start <machine-id> --app linehound-staging
```

Re-run `bash scripts/monitor_remote.sh https://linehound-staging.fly.dev`
immediately after — do not consider it resolved on a dashboard status
alone; the monitor script is the same one that will confirm to
`docs/OVERNIGHT_RUN.md`'s eventual log entry that it is actually serving
again.

### 2b. Machine/process-level recovery

```bash
fly status --app linehound-staging       # machine state
fly logs --app linehound-staging         # last lines before the outage started
fly machine restart <machine-id> --app linehound-staging
```

If logs show a crash loop (the process starts, dies, Fly restarts it,
repeat) — **do not** just keep restarting it. A crash loop means the
code or config is broken, and a restart only buys a few seconds before
it crashes again. Go to §2c (redeploy from a known-good commit) or
escalate to whoever owns the code path in the crash trace; restarting a
crash loop repeatedly hides the real signal (a service that is "up" 30%
of the time between crashes still reads as OK to a monitor whose only
check is "did /health answer once").

### 2c. Token-less fallback: GitHub Actions redeploy

`agents in a cloud session with no Fly token` (this session's own
situation on 2026-09-01) have exactly one recovery lever that needs no
Fly credential at all: the `deploy-staging` GitHub Actions workflow
(`.github/workflows/deploy-staging.yml`) already holds `FLY_API_TOKEN`
as a repository secret and can be fired by hand:

- **Web UI path:** GitHub repo → Actions tab → "deploy-staging" workflow
  → "Run workflow" button (this is what `workflow_dispatch: {}` in that
  file enables) → Run workflow on the launch branch.
- **From a Claude session with the GitHub MCP tools attached:**
  `mcp__github__actions_run_trigger` against the `deploy-staging.yml`
  workflow (a `workflow_dispatch` trigger) — no `gh` CLI needed, and no
  Fly token ever touches the agent session; the token lives only in the
  GitHub Actions runner's environment.

This redeploys the current launch-branch commit — it is a restart-by-
redeploy, not a code fix. **When this is safe:**

- The app was healthy before the outage and nothing in the failing class
  points at a code regression (i.e. `TLS_RESET`/`RECV_RESET`/
  `CONN_REFUSED`/`DNS`/`TIMEOUT` — all infra-shaped failures where the
  last known-good code is presumably still fine).
- No crash loop is visible in `fly logs` (§2b) — a crash loop redeployed
  from the SAME broken commit just crash-loops again.

**When this is NOT safe / masks a real problem:**

- `HTTP_503`/`HTTP_5XX` from `/health` itself, where the reasons point at
  a genuine application fault (a bad forward store, a broken odds
  provider integration) — redeploying does not fix broken code or bad
  data, it just restarts the same bug.
- A crash loop — redeploying the identical broken artifact restarts the
  identical crash. Fix forward (revert the bad commit, or push a fix)
  before redeploying, never redeploy-and-hope.
- Any outage where the LAST deploy is suspect (i.e. the outage started
  right after a push) — redeploying the same bad commit does nothing;
  the fix is `deploy/DEPLOY_RUNBOOK.md`'s rollback procedure
  (`fly deploy rollback --app linehound-staging --version <N>`, a Fly-
  authenticated command, not the token-less path) or reverting the
  commit and letting Actions redeploy the revert.

After ANY redeploy or restart, verify per §6 before considering it
resolved — a redeploy that "probably worked" is not confirmed.

## 2d. Fly's own health-check / auto-restart options (PROPOSED — not applied)

`deploy/fly.staging.toml`'s `[[http_service.checks]]` block already
gates whether Fly's proxy routes traffic to the machine, but it does not
by itself restart a machine that fails its check repeatedly — that is a
separate Fly feature this repo has not opted into. The diff below is a
**proposal for Launch Ops to review and apply**, not something this task
edited directly (`deploy/fly.staging.toml` changes what gets deployed,
which is outside this task's boundary — see the task's own scope note).

```toml
# Proposed addition to deploy/fly.staging.toml's [[http_service.checks]]
# block -- restart_limit tells Fly to actually restart a machine that
# fails its own health check N times in a row, rather than only routing
# traffic away from it. Today the check gates ROUTING but nothing in this
# file tells Fly to act on repeated failures beyond that. Fly's own docs
# name this field `[checks.restart_limit]` under the machine-level
# [[vm]] / [checks] config, distinct from the [http_service.checks]
# proxy-routing check already present -- confirm the exact TOML key
# against Fly's current docs before applying, since this surface has
# changed between Fly platform versions and this repo's own
# fly.staging.toml predates any use of it.
[[checks]]
  type = "http"
  path = "/health"
  interval = "15s"
  timeout = "5s"
  grace_period = "10s"
  # Restart the machine after this many consecutive failures rather than
  # only routing traffic away from it forever. A conservative threshold
  # (not 1) avoids restarting on a single transient blip the way
  # monitor_remote.sh's own "1 failure = recheck, don't act" rule (see
  # the escalation ladder below) already does for the human-facing alert
  # path -- the two should agree on what counts as "real," not one
  # twitchier than the other.
  restart_limit = 3
```

**Why this is proposed, not proven to have prevented 2026-09-01:** a
billing suspension stops the MACHINE at the account level — Fly's own
auto-restart-on-failed-health-check would not have helped here, since
Fly itself is the one that stopped the machine on purpose. This option
is worth having for a genuine in-process hang/crash-loop case, which is
a real and distinct failure mode from what actually happened today; it
is not a substitute for §2a's billing check.

## 3. Health-check escalation ladder

Encoded in `scripts/monitor_remote.sh` itself (state file under
`/tmp/linehound_monitor/<url-key>.state` by default, override with
`MONITOR_REMOTE_STATE_DIR`) so the hourly trigger doesn't need any
external memory of what happened last run:

1. **1st consecutive failure** → the script prints `(1st failure --
   recheck next cycle before alerting a human)` and exits 1. The
   scheduler should log this but NOT wake Brey — a single miss is
   frequently a transient network blip on the checking side, not the
   app.
2. **2nd+ consecutive failure (same or different class)** → the script
   prints `ESCALATE: N consecutive failures, class=<CLASS>`. This is the
   line to tell Brey once, with the class attached, so he starts at the
   right row of §1's table instead of "it's down, IDK why."
3. **Recovery after any alerted failure** → the script prints
   `RECOVERED: ... after N consecutive failure(s) (last class: ...)`
   exactly once, on the first OK after a run of failures — send this as
   the one confirmation that closes the loop, then stop repeating it
   (the state resets to `count=0` so the next OK run stays silent).
4. **Do not re-alert on every single failed run** once already escalated
   — the ladder's whole point is "tell a human once per incident," not
   once per hourly tick for a five-hour outage. The state file's `count`
   field is available if a scheduler wants to periodically remind (e.g.
   every 6th consecutive failure) on a long outage, but that policy is
   the scheduler's choice, not this script's.
5. **A different failure class while already escalated** (e.g. `TLS_RESET`
   flips to `CONN_REFUSED` mid-outage) resets the consecutive count to 1
   under the new class and re-escalates on the 2nd occurrence of THAT
   class — a class change mid-incident is itself informative (e.g. "Fly
   suspended it, then someone stopped the machine entirely") and
   shouldn't be silently folded into the running count of the old class.

## 4. Backup verification

`scripts/backup_app_db.sh <source-db> <backup-dir>` (hardened
2026-09-01):

- Takes an online, page-consistent copy via sqlite's own `.backup` API
  (already the case before this task — see the script's own header for
  why not a plain `cp`).
- **New:** runs `PRAGMA integrity_check` against the freshly written
  copy on a fresh connection (not the same handle `.backup` used) before
  trusting it. A failed check deletes the bad copy and exits nonzero —
  the intended contract for any scheduler already treating nonzero exit
  as "alert" (same convention as `scripts/monitor_remote.sh`).
- Prunes anything older than `BACKUP_RETENTION_DAYS` (default 14) on
  every run — unchanged.

**Cadence:** daily is the documented default (`deploy/DEPLOY_RUNBOOK.md`'s
"Backups: recurring schedule" section) for a sqlite store this small at
alpha scale. Nothing currently fires it on Fly — it still needs wiring
per that section (`fly ssh console ... -C 'bash scripts/backup_app_db.sh
...'` on a recurring trigger) once a scheduler has Fly access to the
staging app.

**Where backups land:** on the Fly machine itself, under the same
mounted volume as `APP_DB_PATH` (e.g. `/app/data/app/backups/`) unless
pointed elsewhere — meaning a backup living only on that volume is not
independent of the machine/volume it protects against. Pulling a copy
off-machine periodically (`fly sftp get` or a scheduled `fly ssh console`
+ local save) is worth doing before this matters for real money; flagged
here as a gap, not solved by this task (needs Fly access this task does
not have).

**Restore procedure:**

```bash
# 1. Stop the app so nothing writes to APP_DB_PATH mid-restore.
fly apps stop --app linehound-staging   # 'fly scale count 0' also works

# 2. Pull the chosen backup down (or restore it in place if already on
#    the volume via `fly ssh console`), then copy it over the live path:
fly ssh console --app linehound-staging \
    -C "cp /app/data/app/backups/app-<TIMESTAMP>.db /app/data/app/app.db"

# 3. Confirm the restored copy passes its own integrity check before
#    bringing the app back up -- restoring a bad backup is worse than no
#    restore, since it looks fine until someone hits the corrupted row.
fly ssh console --app linehound-staging \
    -C "python3 -c \"import sqlite3; c=sqlite3.connect('/app/data/app/app.db'); print(c.execute('PRAGMA integrity_check').fetchall())\""

# 4. Restart.
fly apps start --app linehound-staging
```

Then re-run §6's post-deploy verification before considering the restore
complete.

## 5. Stripe / provider failure visibility

How a Stripe outage or a webhook-delivery failure shows up in THIS
system today (per `docs/LAUNCH_OPS_SECURITY_HANDOFF.md`'s already-
documented config checks — this section is the "how do I even notice"
companion to that file's "what to configure" checks):

| Symptom | What's actually wrong | Diagnose with |
|---|---|---|
| `POST /signup` returns 500 | A real Stripe error (bad `STRIPE_BETA_PRICE_ID`, a transient Stripe 5xx, key issue) reached the checkout-creation call. Fails closed by design — no user is half-activated — but it is the visible symptom of a Stripe-side problem. | `fly logs --app linehound-staging \| grep -i stripe` around the timestamp; confirm `STRIPE_API_KEY`/`STRIPE_BETA_PRICE_ID` secrets are still set and match the dashboard. |
| `GET /billing/status` never advances past `pending_payment` after a real checkout | The webhook never arrived, or arrived and was rejected. `STRIPE_WEBHOOK_SECRET` mismatch is the single most common cause (`/billing/webhook` returns 501 while unset, per the security handoff doc). | Stripe dashboard → Webhooks → the endpoint pointed at `https://linehound-staging.fly.dev/billing/webhook` → recent delivery attempts and their response codes. A 501/400 there confirms a config mismatch, not a Stripe outage. |
| Signup/billing routes intermittently 5xx during a real Stripe status incident | Stripe itself is degraded (check status.stripe.com) — this system fails closed rather than fabricating success, per the security handoff doc's "watch during first live checkout" section. | `status.stripe.com`; cross-reference timestamps against the 500s in `fly logs`. |
| No webhook activity at all, ever, even for a known-good test event | `STRIPE_FAKE_TRANSPORT` accidentally left set, or `STRIPE_WEBHOOK_SECRET` unset (501). | `fly logs --app linehound-staging \| grep "STRIPE FAKE TRANSPORT ACTIVE"` — that banner printing in staging/live is itself the bug (security handoff doc item 4); its absence plus a 501 on webhook POSTs points at the unset-secret case instead. |
| `GET /meta`'s billing-related fields look stale for everyone at once | Not a per-user issue — check whether the whole app itself is degraded first (§1's table) before assuming it's Stripe-specific. | `bash scripts/monitor_remote.sh https://linehound-staging.fly.dev` first, to rule out "the app is down" before chasing a billing-specific theory. |

## 6. Deploy failure alerting (GitHub Actions)

`deploy-staging.yml` can fail silently if nobody is watching the Actions
tab — it has no notification wired beyond GitHub's own default (email to
whoever's commit triggered it, if their notification settings allow it).

**Check the latest run:**

- **Web UI:** repo → Actions tab → "deploy-staging" workflow → latest run;
  red X means it failed (check which step — the "Guard - secret present"
  step failing means `FLY_API_TOKEN` is missing/expired from repo
  secrets, not a code problem).
- **From a Claude session with GitHub MCP tools:** `mcp__github__actions_list`
  (list recent runs and their conclusions for this repo) — `gh` CLI is
  not available in a cloud session, this MCP tool is the equivalent.
  Follow up with `mcp__github__get_job_logs` on a failed run's job to see
  exactly which step and why.

**After any push that should deploy, verify the build actually landed —
add this step every time:**

```bash
# /health alone doesn't prove a NEW build deployed (an old, still-healthy
# machine also answers 200) -- /meta's "version" field (api/meta.py,
# `git describe --tags --always --dirty` at build time, or the literal
# string "dev" in a container with no .git dir) is what actually proves
# the new commit is what's running. Compare the version string in the
# response against the commit/tag that was just pushed.
curl -s https://linehound-staging.fly.dev/health | python3 -m json.tool
curl -s https://linehound-staging.fly.dev/meta | python3 -m json.tool
```

Note `deploy/Dockerfile` `COPY`s source rather than cloning a `.git` dir
into the built image (per `api/meta.py`'s own docstring) — if `/meta`'s
`version` ever reads back as the literal `"dev"` fallback in staging,
that means the built image has no git metadata to read at all, which is
itself worth flagging to whoever owns `deploy/Dockerfile`, since it
silently defeats this exact verification step.

## 7. Customer-facing degraded states — handoff for Lane A (frontend)

Read-only review of `web/js/api.js`'s error path (the shared fetch
wrapper every view module uses) turned up the following gaps. **This
task did not and should not edit anything under `web/`** — the list
below is a handoff for whichever agent/session owns that lane.

- **A network failure and a TLS-reset outage are indistinguishable to
  the browser and to the user.** `apiFetch()` in `web/js/api.js` catches
  every `fetch()` failure into the same `ApiError(null, "network request
  failed: " + err.message)` — a real outage (like 2026-09-01's TLS
  reset), a DNS failure, a dropped wifi connection, and an ad-blocker
  eating the request all produce the exact same generic message on
  screen. A customer during an actual outage has no way to tell "the
  service is down, try later" from "check your own connection."
- **No retry or backoff anywhere in the fetch wrapper.** A single
  transient blip (the same kind `monitor_remote.sh`'s "1st failure,
  recheck" rule tolerates server-side) immediately surfaces as a hard
  error to the user with no automatic second attempt.
- **No stale-data or "last known good" indicator surfaced from the
  wrapper layer.** `api/app.py`'s own caching layer already supports a
  stale-served-with-flag pattern server-side (per
  `docs/OVERNIGHT_RUN.md`'s 2026-09-01 build-loop entry, "caching/
  freshness (stale-served-with-flag)") — worth confirming each view that
  reads odds/today data actually surfaces that flag to the user rather
  than only the wrapper silently accepting whatever the server marks
  fresh-or-stale.
- **No app-level status/banner for a known outage.** If Launch Ops knows
  staging is down (e.g. mid-recovery per this runbook), there is
  currently no mechanism for the frontend to show a "we know, we're on
  it" banner instead of every view independently rendering its own raw
  `ApiError` message.
- **`web/js/admin.js` duplicates the exact same fetch-wrapper pattern**
  (its own `AdminApiError`, its own `catch` producing the same generic
  network-failure string) — any fix to the customer-facing wrapper
  should consider whether the admin surface needs the same fix, since
  today they would drift independently.

None of the above was touched — it's for Lane A to prioritize and
implement in `web/`.

## Related files

- `deploy/DEPLOY_RUNBOOK.md` — first deploy, rollback, staging→production
  promotion checklist. This file assumes that one already ran.
- `docs/LAUNCH_OPS_SECURITY_HANDOFF.md` — Stripe/webhook config checks
  Launch Ops owns; §5 above is the "how it shows up" companion to that
  file's "what to configure."
- `docs/RUNBOOK.md` — the DATA PIPELINE operator runbook (hourly/daily
  capture jobs, credit floor, forward stores). Different system, similar
  name — that file is not this one.
- `scripts/monitor_remote.sh`, `scripts/backup_app_db.sh` — the two
  scripts this runbook documents the hardened behavior of.
