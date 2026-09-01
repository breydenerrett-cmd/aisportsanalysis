# Running the api/ service

This covers running the FastAPI app (`api/app.py`) locally, by Docker or by
bare uvicorn. It does not choose, register, or configure any external
service -- host, domain, and secrets provider are Brey's calls, tracked in
`docs/LAUNCH_DECISIONS.md`. Everything here runs on a laptop with no
account anywhere, and the same image/command is what a real host would
eventually run.

## Run it with Docker

```bash
docker build -f deploy/Dockerfile -t aisportsanalysis-api .

docker run --rm -p 8000:8000 \
    -e APP_DB_PATH=/app/data/app/app.db \
    -v "$(pwd)/data/app:/app/data/app" \
    aisportsanalysis-api
```

The `-v` mount is what makes the user/token sqlite store survive a
container restart -- without it, `APP_DB_PATH`'s default location is
inside the container's writable layer and is gone the moment the
container is removed.

To enable the admin invite endpoint (`POST /admin/invites`, api/auth.py),
add `-e APP_ADMIN_TOKEN=<some long random value>`. Leaving it unset is the
correct default outside active invite-issuing: the endpoint answers 404,
not "open with no check" (api/auth.py's module docstring explains why that
distinction matters).

## Run it with bare uvicorn (no Docker)

```bash
pip install -r api/requirements.txt
APP_DB_PATH=./data/app/app.db uvicorn api.app:app --host 0.0.0.0 --port 8000
```

This is what `scripts/smoke_api.sh` does under the hood, against a
throwaway `APP_DB_PATH` in a temp directory.

## Environment variables

| Variable          | Required | Default (if unset)                     | Purpose |
|-------------------|----------|-----------------------------------------|---------|
| `APP_DB_PATH`     | No       | `data/app/app.db` (repo-root-anchored, see `src/paths.py`) | Where the sqlite user/token store lives. Set this to a mounted volume path in any environment where the container can be replaced. |
| `APP_ADMIN_TOKEN` | No       | unset -- `/admin/invites` returns 404   | Bearer value that must accompany `X-Admin-Token` to create an invite. Generate with e.g. `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`; never commit it. |
| `AISPORTS_DATA_DIR` | No     | `data/` (repo-root-anchored, see `src/paths.py`) | Overrides the root for the odds/lineup/schedule stores GET /health reads freshness from. Only needed if that data lives somewhere other than the checkout. |
| `ODDS_API_KEY`, `DEFAULT_BOOK`, `ODDS_API_*` | No (only for live odds fetches) | see `.env.example` | Consumed by `src/providers`, not by this container's own code -- listed here because the same process needs them to serve real odds data, not synthetic/offline responses. |

None of these are secrets this task is authorized to generate or store
anywhere but a `.env`-style local file (see `.gitignore`'s "Secrets" block
-- `.env` is never committed).

## Checking it's alive

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```

`GET /health` needs no auth and returns HTTP 200 when every check the
process can make came back clean, or HTTP 503 with `status: "degraded"`
and a `reasons` list naming exactly what failed (an unreachable db, or a
store that exists but could not be read -- see
`src/appstate/apphealth.py`'s module docstring for the honesty rule behind
that distinction). A store that is simply *missing* -- a fresh checkout
with no captures collected yet -- is reported by name but does not by
itself flip the top-level status; that is the expected shape of a brand
new environment, not a failure.

For an end-to-end local check (build nothing, just run + curl + tear down),
use `scripts/smoke_api.sh`:

```bash
bash scripts/smoke_api.sh
```

## What remains blocked on Brey

Nothing in this file requires a decision -- it is all runnable today with
no account anywhere. What it does NOT do, and cannot do without Brey's
sign-off (`docs/LAUNCH_DECISIONS.md`):

- **Host choice** (Decision 3): which machine this container actually runs
  on long-term (small VM vs. PaaS). The Dockerfile and this README are
  written to be host-agnostic on purpose, so whichever way that decision
  goes, nothing here needs to change.
- **Domain** (Decision 4, referenced in Decision 3's Cloudflare discussion):
  there is no DNS, TLS, or reverse-proxy config here -- this serves plain
  HTTP on a bare port, exactly as a host's own TLS-terminating proxy would
  expect to sit in front of.
- **Real secrets**: `APP_ADMIN_TOKEN` and any future auth-provider or
  billing keys (Decisions 1-2) must be generated and stored by whatever
  secrets mechanism the chosen host provides (e.g. Fly secrets, a VM's
  systemd `EnvironmentFile`, Hetzner + a vault) -- this repo only ever
  reads them from the environment, and `.env` stays local and gitignored.
