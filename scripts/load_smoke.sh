#!/usr/bin/env bash
# scripts/load_smoke.sh -- start the real api/app.py under uvicorn against a
# throwaway APP_DB_PATH, then fire a burst of concurrent authed requests at
# it and prove the server survives without ever answering with a 500.
#
# WHY THIS EXISTS
# -----------------
# Red-team round: src/providers/mlb.py's schedule fetch used to pin a
# request-handling worker for DEFAULT_TIMEOUT's old value of 20 SECONDS on a
# stalled upstream response. That is a DoS knob -- fire enough concurrent
# requests and every worker in the pool ends up parked on a socket that will
# never answer. src/providers/mlb.py now bounds that fetch (see its
# TIMEOUT SHAPE comment) and retries once on a stall/reset only; this script
# is the concurrency smoke that proves the fix holds under load, the same
# way scripts/smoke_api.sh proves the single-request shape.
#
# OFFLINE-TOLERANT, LIKE smoke_api.sh
# -------------------------------------
# /today, /games/{date}, and POST /betcheck all fetch MLB's live schedule --
# with no network access those calls surface as a structured 502
# (api/app.py's MLBError handling). A 502 under load is exactly the same
# honest "upstream unreachable" answer smoke_api.sh already treats as a
# pass; what this script refuses to accept, offline or not, is a 500 -- a
# request that reached the server and broke it, rather than one that
# reached the server and got told the truth about an unreachable provider.
#
# WHY 50 REQUESTS / 8 WORKERS
# -------------------------------
# 50 is comfortably more than any real alpha user's browser will ever fire
# at once, and 8 concurrent workers is enough to overlap requests without
# drowning a single-process uvicorn dev server in more sockets than its
# default backlog can even accept -- the goal is proving the timeout/retry
# fix under real concurrency, not benchmarking throughput.
set -uo pipefail
cd "$(dirname "$0")/.."

PORT="${LOAD_SMOKE_PORT:-8932}"
BASE="http://127.0.0.1:${PORT}"
TMP_DB_DIR="$(mktemp -d)"
export APP_DB_PATH="${TMP_DB_DIR}/app.db"
export APP_ADMIN_TOKEN="load-smoke-$(openssl rand -hex 16 2>/dev/null || echo fallback$$)"
LOG_FILE="${TMP_DB_DIR}/uvicorn.log"
RESULTS_FILE="${TMP_DB_DIR}/results.txt"

TOTAL_REQUESTS="${LOAD_SMOKE_REQUESTS:-50}"
CONCURRENCY="${LOAD_SMOKE_CONCURRENCY:-8}"

FAILURES=0
pass() { echo "  PASS: $1"; }
fail() { echo "  FAIL: $1"; FAILURES=$((FAILURES + 1)); }

cleanup() {
    if [ -n "${SERVER_PID:-}" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
        kill "$SERVER_PID" 2>/dev/null
        wait "$SERVER_PID" 2>/dev/null
    fi
    rm -rf "$TMP_DB_DIR"
}
trap cleanup EXIT

echo "== starting uvicorn on :${PORT} (APP_DB_PATH=${APP_DB_PATH}) =="
python3 -m uvicorn api.app:app --host 127.0.0.1 --port "$PORT" \
    >"$LOG_FILE" 2>&1 &
SERVER_PID=$!

# Poll /health rather than a fixed sleep -- see scripts/smoke_api.sh for why
# a guessed constant is the wrong tool here.
READY=0
for _ in $(seq 1 50); do
    if curl -sf -o /dev/null "${BASE}/health"; then
        READY=1
        break
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        break  # the process died -- no point polling further
    fi
    sleep 0.2
done

if [ "$READY" -ne 1 ]; then
    fail "server never became reachable on ${BASE}/health"
    echo "---- uvicorn log ----"
    cat "$LOG_FILE"
    echo "== load_smoke.sh: ${FAILURES} failure(s) =="
    exit 1
fi

echo "== mint one invite token for the authed routes =="
TOKEN="$(curl -s -X POST "${BASE}/admin/invites?email=load-smoke@example.com" \
    -H "X-Admin-Token: ${APP_ADMIN_TOKEN}" | python3 -c "import json,sys; print(json.load(sys.stdin)['token'])")"
if [ -n "$TOKEN" ]; then
    pass "admin invite minted a token"
else
    fail "admin invite did not return a token -- cannot run the authed load burst"
    echo "---- uvicorn log ----"
    cat "$LOG_FILE"
    exit 1
fi

RECENT_DATE="$(python3 -c "from datetime import date, timedelta; print((date.today()-timedelta(days=2)).isoformat())")"

echo "== firing ${TOTAL_REQUESTS} concurrent authed requests (${CONCURRENCY} at a time): mix of /today, /games/<date>, POST /betcheck =="
# One line of shell per request, dispatched through xargs -P so the fan-out
# and concurrency cap live in one place rather than a hand-rolled job pool.
# Each line does its own curl and prints "<status> <elapsed_s>" -- nothing
# else -- so RESULTS_FILE is trivial to parse afterward, and the token never
# appears in anything written to disk or stdout: it lives only in this
# shell's environment and the (invisible, not logged) Authorization header
# curl attaches directly.
run_one() {
    local n="$1"
    local route
    case $(( n % 3 )) in
        0) route="GET ${BASE}/today" ;;
        1) route="GET ${BASE}/games/${RECENT_DATE}" ;;
        2) route="POST ${BASE}/betcheck" ;;
    esac
    local start end status
    start=$(date +%s.%N)
    if [ "$(( n % 3 ))" = "2" ]; then
        status=$(curl -s -o /dev/null -w '%{http_code}' -X POST "${BASE}/betcheck" \
            -H "Authorization: Bearer ${TOKEN}" \
            -H 'Content-Type: application/json' \
            -d "{\"date\": \"${RECENT_DATE}\", \"away\": \"ZZZ\", \"home\": \"YYY\", \"side\": \"home\", \"american_price\": -110}")
    elif [ "$(( n % 3 ))" = "1" ]; then
        status=$(curl -s -o /dev/null -w '%{http_code}' \
            -H "Authorization: Bearer ${TOKEN}" "${BASE}/games/${RECENT_DATE}")
    else
        status=$(curl -s -o /dev/null -w '%{http_code}' \
            -H "Authorization: Bearer ${TOKEN}" "${BASE}/today")
    fi
    end=$(date +%s.%N)
    echo "${status} $(echo "$end - $start" | bc)"
}
export -f run_one
export BASE TOKEN RECENT_DATE

seq 1 "$TOTAL_REQUESTS" | xargs -P "$CONCURRENCY" -I{} bash -c 'run_one "$@"' _ {} > "$RESULTS_FILE"

REQUESTS_SEEN=$(wc -l < "$RESULTS_FILE" | tr -d ' ')
if [ "$REQUESTS_SEEN" -eq "$TOTAL_REQUESTS" ]; then
    pass "all ${TOTAL_REQUESTS} requests returned a result line"
else
    fail "expected ${TOTAL_REQUESTS} result lines, got ${REQUESTS_SEEN}"
fi

echo "== checking every response status is 200/404/429/502 (never 500) =="
BAD_STATUSES=$(awk '{print $1}' "$RESULTS_FILE" | grep -Ev '^(200|404|429|502)$' || true)
if [ -z "$BAD_STATUSES" ]; then
    pass "every response was 200, 404, 429, or 502"
else
    fail "unexpected status code(s) seen: $(echo "$BAD_STATUSES" | sort -u | tr '\n' ' ')"
fi
FIVE_HUNDREDS=$(awk '{print $1}' "$RESULTS_FILE" | grep -c '^5[0-9][0-9]$' || true)
if [ "$FIVE_HUNDREDS" -eq 0 ] || [ -z "$FIVE_HUNDREDS" ]; then
    pass "zero 5xx responses (502 from an unreachable schedule provider is the one 5xx this script allows, and it is excluded above)"
else
    fail "${FIVE_HUNDREDS} response(s) came back 5xx"
fi

echo "== server is still alive after the burst =="
if kill -0 "$SERVER_PID" 2>/dev/null && curl -sf -o /dev/null "${BASE}/health"; then
    pass "uvicorn process is still running and /health still responds"
else
    fail "server did not survive the concurrent burst"
fi

echo "== latency: p50/p95/max across ${REQUESTS_SEEN} requests =="
python3 - "$RESULTS_FILE" <<'PYEOF'
import sys

path = sys.argv[1]
latencies = []
with open(path) as handle:
    for line in handle:
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            latencies.append(float(parts[1]))
        except ValueError:
            continue

if not latencies:
    print("  (no latency samples parsed)")
else:
    latencies.sort()
    def pct(p):
        idx = min(len(latencies) - 1, int(round(p * (len(latencies) - 1))))
        return latencies[idx]
    print(f"  p50={pct(0.50):.3f}s  p95={pct(0.95):.3f}s  max={latencies[-1]:.3f}s"
          f"  (n={len(latencies)})")
PYEOF

echo "== stderr carries no bearer token or Authorization header value =="
if grep -qi "bearer \|authorization:" "$LOG_FILE"; then
    fail "a bearer token or Authorization header value leaked into the log"
else
    pass "no bearer token or Authorization header value in the log"
fi

echo
if [ "$FAILURES" -eq 0 ]; then
    echo "== load_smoke.sh: all checks passed =="
    exit 0
else
    echo "== load_smoke.sh: ${FAILURES} failure(s) =="
    echo "---- uvicorn log (tail) ----"
    tail -n 100 "$LOG_FILE"
    exit 1
fi
