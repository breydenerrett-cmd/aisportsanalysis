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
# WHY FAILURE CLASSES, ADDED 2026-09-01
# ------------------------------------------
# Staging was down ~5 hours on 2026-09-01 because Fly suspended the app
# for a missing billing card -- the edge still accepted the TCP
# connection but reset the TLS handshake. Before this change every
# unreachable case printed the same generic "unreachable" line with
# curl's raw exit code, so a human (or an agent) reading the alert had to
# already know that curl exit 35/56 means "TLS reset" and that THAT
# specific signature means "Fly suspended the app," as opposed to exit 6
# (DNS -- the app name/domain itself is gone) or exit 28 (timeout -- the
# edge is unreachable/network partition, a different failure entirely).
# classify_curl_failure() below turns curl's own exit code into the one
# label a human needs to pick the right branch of
# docs/OPERATIONS_RUNBOOK.md's decision tree without first decoding a
# curl manpage under pressure. See that runbook's "Decision tree by
# failure class" section for what each class below implies and the exact
# recovery command for it.
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
#
# THE STATE FILE AND THE ESCALATION LADDER
# ----------------------------------------------
# docs/OPERATIONS_RUNBOOK.md's escalation ladder says: one failure is a
# blip (recheck, don't wake anyone), two consecutive failures is the
# point a human should be told (with the failure class, so they know
# which branch of the decision tree to start on), and a recovery after
# any alerted failure deserves exactly one confirmation line so the
# person who got paged knows it is over. That ladder needs to remember
# what happened on the PREVIOUS run, which a stateless script cannot do
# on its own -- hence STATE_FILE. It is deliberately plain "key=value"
# text (no python3/jq dependency to read it back) so the state carries
# across invocations of a dependency-free bash script with nothing more
# than `source` or a `grep`.
set -uo pipefail

BASE="${1:?usage: monitor_remote.sh <base-url> (e.g. https://app.fly.dev)}"
# Trim a trailing slash so "https://x.fly.dev/" and "https://x.fly.dev"
# both produce the same request path.
BASE="${BASE%/}"

TIMEOUT="${MONITOR_REMOTE_TIMEOUT:-10}"

# State lives outside the repo by default (ephemeral operational state,
# not data worth committing or reviewing in a diff) -- override for a
# host where /tmp is not persistent across the scheduler's own restarts,
# or to point two monitors (e.g. staging and production) at separate
# directories explicitly rather than relying on the BASE-derived filename
# below to keep them apart.
STATE_DIR="${MONITOR_REMOTE_STATE_DIR:-/tmp/linehound_monitor}"
mkdir -p "$STATE_DIR" 2>/dev/null || true
# Sanitize BASE into a filename-safe key (strip scheme, replace non-alnum
# with underscore) so one state directory can track multiple monitored
# URLs (e.g. staging and production) without collisions.
STATE_KEY="$(echo "$BASE" | sed -E 's#^[a-zA-Z]+://##; s#[^a-zA-Z0-9]+#_#g')"
STATE_FILE="${STATE_DIR}/${STATE_KEY}.state"

BODY_FILE="/tmp/monitor_remote_body.$$"
ERR_FILE="/tmp/monitor_remote_err.$$"
cleanup() { rm -f "$BODY_FILE" "$ERR_FILE"; }
trap cleanup EXIT

# Turns curl's own exit code into the one label a human needs to jump
# straight to the right branch of docs/OPERATIONS_RUNBOOK.md's decision
# tree. Codes not called out explicitly fall through to a generic
# CURL_ERROR_<n> label rather than a guess -- an unrecognized code should
# read as "look this up," never as a silently wrong classification.
classify_curl_failure() {
    local curl_exit="$1"
    case "$curl_exit" in
        6)  echo "DNS" ;;              # couldn't resolve host
        7)  echo "CONN_REFUSED" ;;     # couldn't connect (TCP refused)
        28) echo "TIMEOUT" ;;          # operation timed out
        35) echo "TLS_RESET" ;;        # SSL connect error -- TCP accepted,
                                        # handshake failed/reset; this is
                                        # the exact signature 2026-09-01's
                                        # Fly-suspended-for-billing outage
                                        # produced.
        52) echo "EMPTY_REPLY" ;;      # server accepted then sent nothing
        56) echo "RECV_RESET" ;;       # failure receiving data -- also
                                        # commonly a mid-handshake or
                                        # mid-response TLS/TCP reset
        *)  echo "CURL_ERROR_${curl_exit}" ;;
    esac
}

# Reads the previous run's status (if any) and prints an escalation or
# recovery line per docs/OPERATIONS_RUNBOOK.md's ladder, then writes the
# new state. $1 = "OK" or the failure class (e.g. "TLS_RESET", "HTTP_5XX").
update_state_and_escalate() {
    local current_status="$1"
    local prev_status="" prev_count=0
    if [ -f "$STATE_FILE" ]; then
        # Deliberately not `source`d -- a state file is data, not code,
        # and grep+cut keeps it that way even if something odd ever ends
        # up in it.
        prev_status="$(grep '^status=' "$STATE_FILE" 2>/dev/null | cut -d= -f2-)"
        prev_count="$(grep '^count=' "$STATE_FILE" 2>/dev/null | cut -d= -f2-)"
        [ -z "$prev_count" ] && prev_count=0
    fi

    if [ "$current_status" = "OK" ]; then
        if [ "$prev_status" != "OK" ] && [ -n "$prev_status" ]; then
            echo "RECOVERED: ${BASE} is back to OK after ${prev_count} consecutive failure(s) (last class: ${prev_status})"
        fi
        {
            echo "status=OK"
            echo "count=0"
            echo "last_change=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        } > "$STATE_FILE"
        return
    fi

    local new_count=1
    if [ "$prev_status" = "$current_status" ]; then
        new_count=$((prev_count + 1))
    fi
    {
        echo "status=${current_status}"
        echo "count=${new_count}"
        echo "last_change=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    } > "$STATE_FILE"

    if [ "$new_count" -eq 1 ]; then
        echo "(1st failure -- recheck next cycle before alerting a human; see docs/OPERATIONS_RUNBOOK.md escalation ladder)"
    else
        echo "ESCALATE: ${new_count} consecutive failures, class=${current_status} -- notify per docs/OPERATIONS_RUNBOOK.md's escalation ladder"
    fi
}

HTTP_STATUS="$(curl -s -o "$BODY_FILE" -w '%{http_code}' \
    --max-time "$TIMEOUT" "${BASE}/health" 2>"$ERR_FILE")"
CURL_EXIT=$?

if [ "$CURL_EXIT" -ne 0 ]; then
    CLASS="$(classify_curl_failure "$CURL_EXIT")"
    echo "DEGRADED[${CLASS}]: ${BASE}/health unreachable (curl exit ${CURL_EXIT}, timeout ${TIMEOUT}s): $(cat "$ERR_FILE" 2>/dev/null)"
    update_state_and_escalate "$CLASS"
    exit 1
fi

if [ "$HTTP_STATUS" = "200" ]; then
    echo "OK: ${BASE}/health returned 200"
    update_state_and_escalate "OK"
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
    echo "DEGRADED[HTTP_503]: ${BASE}/health returned 503 -- ${REASONS}"
    update_state_and_escalate "HTTP_503"
    exit 1
fi

case "$HTTP_STATUS" in
    5*) CLASS="HTTP_5XX" ;;
    4*) CLASS="HTTP_4XX" ;;
    *)  CLASS="HTTP_UNEXPECTED_${HTTP_STATUS}" ;;
esac
echo "DEGRADED[${CLASS}]: ${BASE}/health returned unexpected status ${HTTP_STATUS}"
update_state_and_escalate "$CLASS"
exit 1
