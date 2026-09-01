# Secrets: generation, required env, rotation

Scope: everything this repo's own process reads from the environment.
Hosting-provider account credentials (Fly/Railway tokens, a future
Clerk/Stripe live key) are Brey's to hold in whatever secrets store the
chosen host provides -- see `deploy/STAGING.md`'s credential ask and
`docs/LAUNCH_DECISIONS.md`'s "Return-to-Brey triggers." This file does not
generate or store any of those; it covers only what runs `api/app.py`.

## NEVER-COMMIT RULE

No secret value -- test or real -- is ever committed. `.gitignore` already
blocks `.env`, `.env.*` (except `.env.example`, which holds only blank
placeholders), `*.key`, `*.pem`, and `credentials.json`. This rule has no
exceptions for "just for staging" or "it's only a test key" -- the
repository is public, and a committed secret is compromised the moment it
lands in history, rotation or not.

`tests/test_deploy_secrets_hygiene.py` enforces the machine-checkable half
of this: no `.env` tracked in git, and no string matching a live/test
Stripe secret-key shape (`sk_live_`/`sk_test_`) anywhere in the tracked
tree outside `docs/` (where this packet's own prose needs to be able to
say the words without tripping the scan).

## Generating `APP_ADMIN_TOKEN`

```bash
openssl rand -base64 32
```

32 random bytes, base64-encoded -- enough entropy that guessing it is not
a realistic attack, short enough to paste into a host's secrets UI or a
`fly secrets set` command without error-prone truncation. `secrets.py`'s
own `token_urlsafe(32)` (already documented in `deploy/README.md`) is
equally acceptable; `openssl rand` is offered here because it needs
nothing beyond a shell, useful when generating a value from a host's own
console rather than a checkout with Python available.

Do not reuse a token across environments (local / staging / eventual
production) -- generate a fresh one each time. A leaked staging token
should never be the same value protecting anything real.

## Required environment variables

| Variable | Required | Where it's set | Notes |
|----------|----------|-----------------|-------|
| `APP_ADMIN_TOKEN` | No (endpoint is 404 if unset) | Host secrets store (`fly secrets set`, Railway variables UI) -- never `.env` on a shared host | Generate per the command above. Gates `POST /admin/invites` (`api/auth.py`). |
| `APP_DB_PATH` | No (defaults per `src/paths.py`) | Deploy config (`fly.toml` env, or the host's env panel) | Must point at the mounted persistent volume's path in any environment where the container/machine can be replaced -- see `deploy/STAGING.md`'s persistent-volume section. |
| `AISPORTS_DATA_DIR` | No | Same as above, only if odds/lineup/schedule data lives outside the checkout | See `deploy/README.md`. |
| `ODDS_API_KEY` | Only for live odds fetches | `.env` locally; host secrets store remotely | From https://the-odds-api.com; free tier is sufficient at this scale (see `.env.example`). |
| `DEFAULT_BOOK`, `ODDS_API_REGION`, `ODDS_API_MARKETS`, `ODDS_API_ODDS_FORMAT` | No | Same as `ODDS_API_KEY` | Non-secret config, but listed here because they travel with the odds key in `.env`/`.env.example`. |

Auth (Clerk) and billing (Stripe) env vars are not listed here: per
`docs/LAUNCH_DECISIONS.md`'s Decisions 1-2, both stay behind their
provider seams (`AuthProvider`, `BillingProvider`) in dev/test mode with
no live keys until Brey connects the real accounts -- that moment gets
its own env-var line in this table, not before.

## Rotation

Rotate `APP_ADMIN_TOKEN` immediately if it is ever exposed (committed by
accident despite the rule above, pasted somewhere it shouldn't be, or a
teammate/contractor's access ends): generate a new value with the command
above and update it in the host's secrets store. Because the admin invite
endpoint reads `APP_ADMIN_TOKEN` from the environment on every request
(no caching -- see `api/auth.py`), rotation takes effect on the next
request with no code deploy needed, though most hosts still require a
restart for a changed env var to reach the running process -- confirm
that against whichever host is actually in use (Fly and Railway both
restart the app on a `secrets set`/variable change).

There is no rotation schedule beyond "immediately on suspected exposure"
at this project's current scale -- a fixed calendar rotation is a beta+
concern once there are real paying users and a real on-call process.
