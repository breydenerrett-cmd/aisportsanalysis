# Temporary staging / preview deploy

This is Decision 3's "prepare a temporary preview/staging deploy" line
(`docs/LAUNCH_DECISIONS.md`, DECIDED BY BREY 2026-09-01, item 3) -- a
short-lived URL for alpha testers, separate from Decision 3's own
long-term recommendation (a Hetzner-class VM + Cloudflare, see
`deploy/README.md`). The two are not the same call: a temporary preview
optimizes for "up in one command, today, before naming/domain/VM
provisioning happen," not for long-term cost or ops control.

Nothing in this file creates an account, spends money, or stores a
credential. It stops exactly at the point a hosting token is required --
that point is called out below.

## Recommended host: Fly.io

**Why Fly, not the VM path, for THIS purpose:** this app is one Docker
container (`deploy/Dockerfile`) with one stateful thing to persist (the
sqlite store at `APP_DB_PATH`, see `src/appstate/users.py`). Fly's
`fly launch` + `fly volumes create` + `fly deploy` gets exactly that --
one machine, one attached volume, a public HTTPS URL, TLS handled for
you -- in three commands with no DNS, no reverse proxy, and no OS patching
to own. That is the simplest reliable path to a reachable URL for a
five-day alpha window. The VM + Cloudflare architecture in
`docs/LAUNCH_DECISIONS.md` Decision 3 remains the right call for the real
beta launch, once ops control and long-run cost matter more than
time-to-URL; standing that up is real infra work, not a today task.

**Alternative: Railway.** Comparable "one container + one volume" shape,
comparable simplicity. Fly is recommended over Railway here only because
Fly's volume + fly.toml model maps onto this app's one-container/
one-volume shape slightly more directly (a named volume mounted at a
fixed path, no extra service wiring), and its free allowance covers a
short alpha window without spend. If Brey already has a Railway account
and no Fly account, Railway is not a worse choice -- swap the commands
below for Railway's equivalent (`railway init`, `railway volume create`,
`railway up`) and everything else in this doc still applies.

## Commands (run from this repo's root, once a Fly account/token exists)

```bash
# One-time: creates the app config (fly.toml) by inspecting
# deploy/Dockerfile. Answer "no" to Postgres/Redis prompts -- this app
# needs neither.
fly launch --dockerfile deploy/Dockerfile --no-deploy

# One-time: the persistent volume APP_DB_PATH needs. Size is generous for
# a sqlite user/token store at alpha/beta scale; cheap to resize later.
fly volumes create app_data --size 1 --region <region-matching-fly.toml>

# Mount the volume and set the one required secret. --detach so this
# doesn't block on the machine coming up; check status separately.
fly secrets set APP_ADMIN_TOKEN=<value from deploy/secrets.md's
    generation command>

# Ship it. Repeatable -- this is also the redeploy command for every
# subsequent code change during the alpha window.
fly deploy
```

`fly.toml` needs one addition beyond what `fly launch` generates -- a
`[mounts]` block pointing the `app_data` volume at the same path
`APP_DB_PATH` uses inside the container (`/app/data/app`, per
`deploy/Dockerfile`'s `ENV APP_DB_PATH`). Without that block the volume
exists but nothing writes to it, and a machine replacement silently loses
the user/token store the same way an unmounted `-v` would locally (see
`deploy/README.md`'s Docker section for the same failure mode explained
for a laptop run).

## The persistent-volume requirement, explicitly

`APP_DB_PATH` (default `data/app/app.db`, see `src/paths.py`) is the ONLY
state this process keeps on disk that a redeploy or machine replacement
would otherwise destroy. Every Fly deploy replaces the running machine;
without a volume mounted at that path, every `fly deploy` during the
alpha window would silently reset every invite token and saved bet to
empty -- the exact failure `deploy/README.md`'s `-v` mount exists to
prevent locally. This is not optional for anything beyond a single
smoke-test run.

## The exact credential ask for Brey

**What:** a Fly.io API deploy token (`fly tokens create deploy`, or the
token issued by `fly auth login` against Brey's own Fly account).
**From where:** Brey's own Fly.io account -- this task does not, and
cannot, create that account; account creation is explicitly out of
bounds for this work.
**Scoped how:** deploy-only, scoped to the one app this creates (not an
org-wide token) -- `fly tokens create deploy -a <app-name>` produces
exactly that. That is the narrowest token Fly's CLI offers for "let CI
or an agent deploy this one app," and it cannot read billing, create
other apps, or touch other apps on the account.

Until that token exists, this doc's commands are ready to run but nobody
has run them -- there is no live staging URL yet. The token is the
trigger to come back to Brey (see `docs/LAUNCH_DECISIONS.md`'s
"Return-to-Brey triggers" line); this file is what makes that a five
minute job once it lands, not a research task.

## Backing up the staging volume

`deploy/README.md`'s "Backing up the app db" section covers a plain file
copy or `.backup`, run against `APP_DB_PATH` -- on this staging deploy
that path lives on the `app_data` Fly volume, not on any machine this
task has direct filesystem access to. Two ways to get a backup off it:

- **Run the CLI backup on the volume itself**: `fly ssh console -a
  <app-name>`, then run `deploy/README.md`'s `.backup` command inside
  that shell against the in-container path (`/app/data/app/app.db`) --
  no downtime, works while the app is serving traffic.
- **Whole-volume snapshot**: `fly volumes snapshots create <volume-id>`
  takes a point-in-time snapshot of the entire `app_data` volume at the
  block level (everything under `APP_DB_PATH`, not just the one file);
  `fly volumes snapshots list <volume-id>` lists what exists to restore
  from. This is the lower-effort option when the goal is "a restore point
  before a risky deploy," not "a portable file to inspect locally" -- for
  the latter, the CLI `.backup` above produces an actual `.db` file that
  can be copied off the machine.

Same credential boundary as the rest of this file: both commands need the
Fly deploy token already covered above, and neither is run by anything in
this repo automatically -- a backup here is a deliberate, manual action
before a deploy Brey (or whoever holds the token) judges risky enough to
want a restore point for.

## What this does NOT cover

- Real domain / custom DNS (Decision 4 -- waits on naming; Fly's own
  `*.fly.dev` subdomain is what alpha testers hit in the meantime).
- Clerk/Stripe production credentials (Decisions 1-2) -- both run in
  test/dev mode against this staging deploy exactly as they do locally;
  see `docs/LAUNCH_DECISIONS.md`.
- Any change to the long-term Decision 3 architecture (VM + Cloudflare) --
  this is a parallel, temporary path, not a replacement for it.
