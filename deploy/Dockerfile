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

# APP_DB_PATH defaults to data/app/app.db (src/appstate/users.py) when the
# env var is unset -- fine for a quick local run, but on a real host this
# should point at a mounted volume so the user/token store survives a
# container replacement. APP_ADMIN_TOKEN has NO default: the admin invite
# endpoint (api/auth.py) stays disabled (404) until an operator sets one
# explicitly, by that module's own design.
ENV APP_DB_PATH=/app/data/app/app.db
ENV APP_ADMIN_TOKEN=
ENV PYTHONUNBUFFERED=1

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
