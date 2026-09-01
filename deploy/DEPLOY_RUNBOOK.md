# Deploy runbook: staging first deploy, rollback, production promotion

This is the ordered, exact-command version of `deploy/STAGING.md`'s plan,
using the checked-in `deploy/fly.staging.toml` and
`deploy/fly.production.toml`. Nothing here runs until Brey provides the
one credential named in Step 0 -- everything before that point is just
this file being ready.

## Step 0: the credential ask (blocks everything below)

**What:** a Fly.io API deploy token, scoped to one app --
`fly tokens create deploy -a aisportsanalysis-staging` (run from Brey's own
`fly auth login` session), or the app-scoped token Fly's dashboard issues
per-app.
**From where:** Brey's own Fly.io account. This task does not create that
account.
**Why scoped, not org-wide:** an app-scoped deploy token can deploy that
one app and nothing else on the account -- it cannot read billing, list
other apps, or delete anything. That is the correct blast radius for a
token that might end up in an agent's hands or a CI secret store.

Until this token exists, stop reading here and go do something else --
every command below fails without it, by design.

## Step 1: first staging deploy

```bash
cd /path/to/aisportsanalysis   # repo root -- fly.toml paths below are
                                # relative to it

# 1a. Authenticate this shell with the token from Step 0. Fly reads
# FLY_API_TOKEN from the environment for every subsequent `fly` command --
# no `fly auth login` browser flow needed for a token-based session.
export FLY_API_TOKEN="<token from Step 0>"

# 1b. Rename the placeholder app name in deploy/fly.staging.toml first --
# Fly app names are globally unique and "CHANGE-ME-..." will not create.
#   sed -i 's/CHANGE-ME-aisportsanalysis-staging/<real-app-name>/' \
#       deploy/fly.staging.toml

# 1c. Create the Fly app itself (does not deploy code yet).
fly apps create <real-app-name>

# 1d. Create the persistent volume APP_DB_PATH needs. Region MUST match
# fly.staging.toml's primary_region or the volume and the machine end up
# unable to attach to each other.
fly volumes create app_data --app <real-app-name> --region iad --size 1

# 1e. Set the secrets this process actually reads (deploy/secrets.md).
# APP_ADMIN_TOKEN is required for the admin invite endpoint to work at
# all; STRIPE_API_KEY/STRIPE_WEBHOOK_SECRET are optional -- omit both and
# the app runs with NullBillingProvider (dev/test-safe,
# src/appstate/billing.py) exactly as it does locally with no .env.
fly secrets set --app <real-app-name> \
    APP_ADMIN_TOKEN="$(openssl rand -base64 32)"
# Only if Brey has Stripe *test-mode* keys ready for staging -- never a
# live key here (deploy/secrets.md's NEVER-COMMIT rule is about git, but
# the same "test key only in staging" boundary applies to secrets stores):
#   fly secrets set --app <real-app-name> \
#       STRIPE_API_KEY="sk_test_..." \
#       STRIPE_WEBHOOK_SECRET="whsec_..."

# 1f. Ship it.
fly deploy --app <real-app-name> --config deploy/fly.staging.toml

# 1g. Get the machine's public URL.
fly status --app <real-app-name>   # look for the *.fly.dev hostname
```

## Step 2: smoke-test the live staging URL

`scripts/smoke_api.sh` now accepts an optional `BASE` env var (see that
script's own header) so the exact same checks that run locally in CI
(`scripts/ci.sh`) also run against the deployed machine, with no local
uvicorn start:

```bash
BASE="https://<real-app-name>.fly.dev" APP_ADMIN_TOKEN="<the value set in 1e>" \
    bash scripts/smoke_api.sh
```

This exercises `/health`, the auth-gate on `/games/{date}`, minting an
invite via `/admin/invites`, and `/betcheck` against the real deployed
process -- exactly what `scripts/ci.sh` already verified locally, now
proving the same behavior survived the trip through Fly's proxy and TLS
termination. A red run here before announcing the URL to alpha testers is
the whole point of this step existing.

## Step 3: monitor it

```bash
bash scripts/monitor_remote.sh "https://<real-app-name>.fly.dev"
```

See that script's own header and `scripts/monitor_remote.sh`'s section
below for wiring this to a recurring check once the URL is live.

## Rollback procedure

Fly keeps prior releases; rolling back does not require a new `fly
deploy` from an older commit (though that also works and is the more
auditable option if time allows):

```bash
# List recent releases (each fly deploy creates one) to find the version
# to roll back to.
fly releases --app <real-app-name>

# Roll back to a specific prior version -- fastest path when the
# currently-running deploy is actively broken and every minute matters.
fly deploy rollback --app <real-app-name> --version <N>

# OR, the auditable path when there is time: redeploy from the last known
# good commit.
git checkout <last-good-commit-or-tag>
fly deploy --app <real-app-name> --config deploy/fly.staging.toml
```

After either path, re-run Step 2's smoke test against the same URL before
considering the rollback complete -- a rollback that has not been
smoke-tested is a guess, not a fix.

## Staging -> production promotion checklist

Do NOT treat "staging works" as "flip a flag to production." Each item
below is a deliberate, separate action:

- [ ] Tag the exact commit staging is currently running as a release
      (`git tag vX.Y.Z && git push --tags`) -- production deploys ONLY
      from a tag, never a branch tip (see `deploy/fly.production.toml`'s
      BOUNDARY 4 comment).
- [ ] Create a SEPARATE Fly app for production (`fly apps create
      <production-app-name>`) -- never reuse staging's app or rename it.
      `deploy/fly.production.toml`'s BOUNDARY 1.
- [ ] Create a SEPARATE volume for production (`fly volumes create
      app_data_production ...`) -- never point production's mount at
      staging's volume. BOUNDARY 2.
- [ ] Set SEPARATE production secrets (`fly secrets set --app
      <production-app-name> ...`) with a freshly generated
      `APP_ADMIN_TOKEN` (deploy/secrets.md: "do not reuse a token across
      environments") and, if billing is going live,
      Stripe's *live-mode* keys -- only after Brey has explicitly said the
      Stripe account is ready for real charges (docs/LAUNCH_DECISIONS.md
      Decisions 1-2 are Brey's call, not this task's). BOUNDARY 3.
- [ ] Deploy the tagged commit: `git checkout vX.Y.Z && fly deploy --app
      <production-app-name> --config deploy/fly.production.toml`.
- [ ] Run Step 2's smoke test against the production URL before
      announcing it anywhere.
- [ ] Point DNS at it once a domain exists (`deploy/CLOUDFLARE.md`) --
      production should not ship on a bare `*.fly.dev` URL the way
      staging does for a five-day alpha.
- [ ] Wire `scripts/monitor_remote.sh` against the production URL on its
      own recurring check, independent of staging's.
- [ ] Confirm final customer-facing legal copy is signed off
      (`docs/LAUNCH_DECISIONS.md`'s DECIDED BY BREY 2026-09-01 item 4) --
      `GET /meta`'s `requires_final_legal_review: true` flag should be
      addressed before real users see it, not carried into production
      unexamined.

## Backups: recurring schedule

`scripts/backup_app_db.sh` (see that script's own header) takes a
point-in-time copy of `APP_DB_PATH` while the server keeps running. On a
Fly machine, run it inside the machine via SSH so it reads the actual
mounted volume, not a local copy:

```bash
fly ssh console --app <real-app-name> \
    -C "python3 -c \"import sqlite3; sqlite3.connect('/app/data/app/app.db').execute('VACUUM INTO ?', ('/app/data/app/backup-manual.db',))\""
```

For a recurring schedule rather than a manual run, the simplest option
that needs no new infrastructure is the same hourly trigger mechanism
already used elsewhere in this program (see this session's own scheduling
tool, or any cron-capable scheduler Brey already has pointed at this
repo): wire it to run

```bash
fly ssh console --app <real-app-name> -C "bash -c '/app/deploy/../scripts/backup_app_db.sh /app/data/app/app.db /app/data/app/backups'"
```

on whatever cadence matches the alpha window's risk tolerance (daily is a
reasonable default for a sqlite store this small). `scripts/backup_app_db.sh`
already prunes anything older than 14 days on every run, so wiring it to
fire daily is sufficient without a separate cleanup job. This is
documented here rather than wired automatically because no scheduler
exists yet with access to the staging app -- the moment one does, this is
the one line it needs.
