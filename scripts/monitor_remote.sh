#!/usr/bin/env bash
# scripts/monitor_remote.sh -- curl a deployed BASE's /health, exit
# nonzero with a one-line status on anything but a clean 200.
#
# WHY THIS IS SEPARATE FROM scripts/smoke_api.sh
# ---------------------------------------------------
# smoke_api.sh starts its OWN local uvicorn process and runs a battery of
# route checks against it -- that is a pre-deploy correctness gate
# (scripts/ci.sh's step 4), not something to run every few minutes
# against a live deploy. This script does the one thing a recurring
# uptime check needs: hit an already-running remote process's /health and
# report up/down/degraded, nothing else. Keeping them separate means a
# scheduler firing this every few minutes never spins up a uvicorn
# process or touches a database, and smoke_api.sh's much heavier battery
# stays a deploy-time gate, not a monitoring loop.
#
# USABLE FROM ANY SCHEDULER
# -----------------------------
# No dependency beyond curl and python3 (already required everywhere else
# in this repo). Exit code is the only contract a generic scheduler
# needs: 0 means healthy, nonzero means "alert" -- the one-line stdout
# message is for a human reading a log, cron's own mail-on-nonzero-output
# behavior, or a scheduler that captures stdout into an alert body.
#
# WIRING TO THE EXISTING HOURLY TRIGGER
# ------------------------------------------
# Once a staging URL exists (deploy/DEPLOY_RUNBOOK.md Step 1), point this
# session's own hourly scheduling mechanism (or any cron-capable
# scheduler already pointed at this repo) at:
#     bash scripts/monitor_remote.sh https://<real-app-name>.fly.dev
# and treat a nonzero exit as the alert condition. This is not wired
# automatically here because no staging URL exists yet to monitor --
# deploy/DEPLOY_RUNBOOK.md's Step 3 is the exact command once one does.
set -uo pipefail

BASE="${1:?usage: monitor_remote.sh <base-url> (e.g. https://app.fly.dev)}"
# Trim a trailing slash so "https://x.fly.dev/" and "https://x.fly.dev"
# both produce the same request path.
BASE="${BASE%/}"

TIMEOUT="${MONITOR_REMOTE_TIMEOUT:-10}"

HTTP_STATUS="$(curl -s -o /tmp/monitor_remote_body.$$ -w '%{http_code}' \
    --max-time "$TIMEOUT" "${BASE}/health" 2>/tmp/monitor_remote_err.$$)"
CURL_EXIT=$?
BODY_FILE="/tmp/monitor_remote_body.$$"
ERR_FILE="/tmp/monitor_remote_err.$$"
cleanup() { rm -f "$BODY_FILE" "$ERR_FILE"; }
trap cleanup EXIT

if [ "$CURL_EXIT" -ne 0 ]; then
    echo "DEGRADED: ${BASE}/health unreachable (curl exit ${CURL_EXIT}, timeout ${TIMEOUT}s): $(cat "$ERR_FILE" 2>/dev/null)"
    exit 1
fi

if [ "$HTTP_STATUS" = "200" ]; then
    echo "OK: ${BASE}/health returned 200"
    exit 0
fi

if [ "$HTTP_STATUS" = "503" ]; then
    # /health's own contract (src/appstate/apphealth.py, api/health.py):
    # 503 means the process is up and answering but at least one check
    # failed -- report the reasons list rather than just the status code,
    # since "degraded" with no detail is not actionable for whoever reads
    # this on an alert.
    REASONS="$(python3 -c "
import json
try:
    with open('${BODY_FILE}') as f:
        data = json.load(f)
    reasons = data.get('reasons', [])
    print(', '.join(reasons) if reasons else 'no reasons reported')
except Exception as exc:
    print(f'body unparseable: {exc}')
" 2>/dev/null)"
    echo "DEGRADED: ${BASE}/health returned 503 -- ${REASONS}"
    exit 1
fi

echo "DEGRADED: ${BASE}/health returned unexpected status ${HTTP_STATUS}"
exit 1
