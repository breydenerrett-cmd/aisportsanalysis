# deploy/Dockerfile -- runs the api/ FastAPI app under uvicorn.
#
# NOT a hosting decision. This image runs the same on a laptop, a Hetzner
# VM, or a PaaS -- which host it lands on is Decision 3 in
# docs/LAUNCH_DECISIONS.md, and building it early is exactly what that
# doc's "WHAT WE CAN PREPARE WITHOUT ANY ACCOUNT TODAY" line calls for:
# a Dockerfile requires no account, no domain, and no secret to exist.
#
# WHY python:3.12-slim, NOT a full python image
# ------------------------------------------------
# api/requirements.txt pins fastapi/uvicorn/pydantic, all pure-Python or
# shipping manylinux wheels -- nothing here needs a compiler toolchain, so
# the slim base (no build-essential, no dev headers) is enough and keeps
# the image small and its attack surface smaller.
#
# WHY A NON-ROOT USER
# --------------------
# The container's only job is running api/app.py under uvicorn; it has no
# business writing anywhere but APP_DB_PATH's directory. Running as root
# inside the container buys nothing here and is the default every container
# security scanner flags first.
#
# WHY src/ IS COPIED TOO
# ------------------------
# api/app.py imports from src/ (src.pipeline, src.providers, src.analysis,
# ...) -- see api/app.py's own docstring on the api/<->src/ boundary. The
# image has to carry both trees; src/ is never installed as a package here,
# just copied alongside api/ the same way `python3 -m uvicorn` on a
# developer's machine runs both from one checkout.
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first so this layer is cached across code-only
# rebuilds -- api/requirements.txt changes far less often than api/ or src/.
COPY api/requirements.txt api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

# curl is the healthcheck's only new dependency; everything else the image
# needs is already covered by api/requirements.txt.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

COPY api/ api/
COPY src/ src/
# WHY config/ IS COPIED (2026-10-03). Request-time code reads settings from it
# (config/example_accounts.json for the "If you had followed every pick"
# section, src/appstate/example_accounts.py). The image had no config/ at all,
# so that section answered "settings could not be read" on staging while every
# local test passed against the repo copy. Small, public, no secrets: the repo
# is public and nothing secret may ever be committed under config/.
COPY config/ config/
# WHY web/ IS COPIED TOO
# ------------------------
# api/web.py serves the browser client off disk from REPO_ROOT/"web"
# (its WEB_DIR). Without this line the image has an api/web.py router
# mounted at /web whose directory does not exist, so every asset 404s
# with "no such asset: 'index.html'" -- the whole UI is missing while
# /health still reports ok, because health never touches web/. That is
# also the page Stripe's checkout success_url redirects a PAYING customer
# to (src/appstate/billing.py), so the 404 lands on exactly the person who
# just paid.
COPY web/ web/
COPY data/processed/ data/processed/
COPY data/watch/ data/watch/
COPY data/app/.gitkeep data/app/.gitkeep
# PAPER / RESEARCH PERFORMANCE (2026-09-07): the product reads the engine
# ledgers (evidence/*.jsonl, hash-chained, git-tracked) and the per-system
# paper-account ledgers READ-ONLY for the Performance and Opportunities
# surfaces. ~10 MB together. Nothing in api/ ever writes to either tree.
COPY evidence/ evidence/
COPY data/paper_accounts/ data/paper_accounts/
# THE RESEARCH REGISTRY (2026-09-12): every customer surface states how
# many hypotheses were pre-registered and read, from this one file via
# GET /meta. It was never in the image, so staging told every visitor
# "0 pre-registered research ideas". ~100 KB, git-tracked, read-only here.
COPY data/research/alpha_registry.jsonl data/research/alpha_registry.jsonl
# EARLIER POSTSEASONS, DISPLAY ONLY (2026-10-03): the game page's Situation
# block reads 2015-2025 postseason games and records from this store
# (src/situation/postseason_history.py) for the long-memory facts, such as a
# club's October record. ~440 KB, git-tracked, read-only here, and never a
# training population. Without it the block silently falls back to 2023 on.
COPY data/research/postseason_history/ data/research/postseason_history/
# F-2 (2026-09-07): team records, starter form, bullpen workload, posted
# lineups and handedness for the matchup page. .dockerignore admits exactly
# five files here; the deploy workflow restores them from the daily-loop
# cache first. On a cache miss the directory holds only .gitkeep, the COPY
# still succeeds, and api/games._enrichment_inputs treats every absent
# store as a stated gap -- the page degrades, it does not break.
COPY data/historical/ data/historical/
# THE UFC DATA LAYER (2026-10-03): the fight-night page (api/ufc_fights.py) and
# the data API (api/datasvc.py) read the normalised UFC files from
# src/datasvc/ufc/store.py's DEFAULT_DIR. ~14 MB, git-tracked, kept current by
# the daily loop (`python -m src.datasvc.cli ufc update`). Without this line the
# store loads empty and the UFC page says no card is booked. The raw fetch cache
# beside it (data/datasvc/raw/, git-ignored) stays out of the build context.
COPY data/datasvc/ufc/ data/datasvc/ufc/
# THE NFL DATA LAYER (2026-10-03): the normalised nflverse files /data/v1/nfl
# reads (src/datasvc/nfl/store.py). ~22 MB, git-tracked, kept current by the
# daily loop (`python -m src.datasvc.cli nfl update`). Loaded only when an NFL
# data route is first asked for.
COPY data/datasvc/nfl/ data/datasvc/nfl/

# BRING THE REQUEST-TIME STORES CURRENT (2026-10-03). The COPY above is the
# repo's committed copy of results, pitcher logs, bullpen log, standings,
# splits, arsenals and transactions -- and nothing commits those, so on
# 2026-10-03 they ended between Sept 6 and Sept 23 while the pages read them
# as if they were today's. This step catches them up from MLB's free keyless
# Stats API, regular season and postseason, in at most ~4.5 minutes, and does
# it for every deploy: it sits AFTER the last COPY, so this layer is rebuilt
# whenever capture has committed anything (it commits every hour).
#
# It can NEVER make the build or the data worse: it works on copies, promotes
# a copy only if it parses and has not shrunk, and exits 0 on every soft
# failure (`|| true` and `timeout` are belt and braces for a crash or a hang).
# An unreachable API costs one 8-second probe and leaves the committed copy.
# Zero odds credits; touches nothing under data/watch, data/processed,
# evidence or any card file. What it does, and why it is safe for the
# training stores: src/pipeline/display_refresh.py's module docstring.
#
# Runs as root (before the USER switch below); the chown after it covers the
# files it writes.
#
# DATA_REFRESH_STAMP is a cache-buster only: Docker reuses this layer when
# nothing above it changed, and a redeploy of an unchanged commit would
# otherwise ship the previous build's data. Pass
# `--build-arg DATA_REFRESH_STAMP=$(date -u +%Y%m%d%H)` to force a fresh pull
# (docs/decisions/deploy-prod-data-freshness.patch does, for production).
# Unset it is harmless: the container's guard (api/app.py) catches the gap.
ARG DATA_REFRESH_STAMP=unset
RUN echo "data refresh stamp: ${DATA_REFRESH_STAMP}" \
    && (timeout 330 python -m src.pipeline.display_refresh --max-seconds 270 \
        || echo "display refresh did not complete; image keeps the committed stores")

# APP_DB_PATH defaults to data/app/app.db (src/appstate/users.py) when the
# env var is unset -- fine for a quick local run, but on a real host this
# should point at a mounted volume so the user/token store survives a
# container replacement. APP_ADMIN_TOKEN has NO default: the admin invite
# endpoint (api/auth.py) stays disabled (404) until an operator sets one
# explicitly, by that module's own design.
ENV APP_DB_PATH=/app/data/app/app.db
ENV APP_ADMIN_TOKEN=
ENV PYTHONUNBUFFERED=1
# The container's own data guard (api/app.py -> src/pipeline/display_refresh.py):
# hourly, re-check the request-time stores and refresh in a memory-capped child
# process only if a core store has gone stale. 0 disables it; unset (tests, a
# laptop) it is off.
ENV DISPLAY_REFRESH_GUARD_INTERVAL_SECONDS=3600

RUN useradd --create-home --uid 10001 apiuser \
    && mkdir -p /app/data/app \
    && chown -R apiuser:apiuser /app
USER apiuser

EXPOSE 8000

# GET /health (api/health.py) needs no auth and no secrets, which is
# exactly what makes it safe to use as the container healthcheck itself.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl --fail http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
