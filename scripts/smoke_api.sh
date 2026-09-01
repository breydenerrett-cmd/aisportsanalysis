#!/usr/bin/env bash
# scripts/smoke_api.sh -- start the real api/app.py under uvicorn against a
# throwaway APP_DB_PATH, hit a handful of routes, and report pass/fail.
#
# WHY THIS EXISTS
# -----------------
# Every existing api/ test (tests/test_api_*.py) calls route functions
# directly -- this repo's starlette build has no TestClient-compatible HTTP
# client installed (see tests/test_api_auth.py's module docstring), so the
# unit suite has never once exercised a REAL request over a REAL socket
# through the REAL middleware stack. This script is the one place that
# gap gets closed: a real `curl` against a real `uvicorn` process, run by a
# human (or CI) before a deploy, not by `python3 -m unittest`.
#
# OFFLINE-TOLERANT BY DESIGN
# -----------------------------
# GET /today and GET /games/{date} fetch MLB's live schedule
# (src.providers.mlb) -- with no network access that call fails, and
# api/app.py turns it into a structured 502 (see api/app.py's `get_today`).
# That 502 is this script's PASS case for those routes: the point is
# proving the server is up, routed, and mistake-tolerant, not that a
# specific game exists today. Assert response SHAPE (a JSON body with a
# `detail` on failure, or a games array on success), never specific DATA.
set -uo pipefail
cd "$(dirname "$0")/.."

PORT="${SMOKE_API_PORT:-8931}"
BASE="http://127.0.0.1:${PORT}"
TMP_DB_DIR="$(mktemp -d)"
export APP_DB_PATH="${TMP_DB_DIR}/app.db"
# throwaway admin token so the smoke run can mint its own invite
export APP_ADMIN_TOKEN="smoke-$(openssl rand -hex 16 2>/dev/null || echo fallback$$)"
LOG_FILE="${TMP_DB_DIR}/uvicorn.log"

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

# Poll /health rather than a fixed sleep -- the server's actual readiness
# time varies with import cost (src.pipeline, src.providers) far more than
# any guessed constant would tolerate.
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
    echo "== smoke_api.sh: ${FAILURES} failure(s) =="
    exit 1
fi

echo "== GET /health =="
HEALTH_BODY="$(curl -s "${BASE}/health")"
HEALTH_STATUS="$(curl -s -o /dev/null -w '%{http_code}' "${BASE}/health")"
if [ "$HEALTH_STATUS" = "200" ] || [ "$HEALTH_STATUS" = "503" ]; then
    pass "/health responded ${HEALTH_STATUS} with a body"
else
    fail "/health returned unexpected status ${HEALTH_STATUS}"
fi
if echo "$HEALTH_BODY" | python3 -c "
import json, sys
data = json.load(sys.stdin)
assert 'status' in data, 'missing status field'
assert 'app_db' in data, 'missing app_db section'
assert 'odds' in data, 'missing odds section'
assert 'forward_captures' in data, 'missing forward_captures section'
" 2>/tmp/health_shape_err; then
    pass "/health body has the expected shape"
else
    fail "/health body shape check failed: $(cat /tmp/health_shape_err)"
fi

echo "== game surface is auth-gated (private alpha): unauthenticated -> 401 =="
RECENT_DATE="$(python3 -c "from datetime import date, timedelta; print((date.today()-timedelta(days=2)).isoformat())")"
UNAUTH_STATUS="$(curl -s -o /dev/null -w '%{http_code}' "${BASE}/games/${RECENT_DATE}")"
if [ "$UNAUTH_STATUS" = "401" ]; then
    pass "/games without a token returned 401"
else
    fail "/games without a token returned ${UNAUTH_STATUS}, expected 401"
fi

echo "== mint an invite token via the admin endpoint, then GET /games authed =="
TOKEN="$(curl -s -X POST "${BASE}/admin/invites?email=smoke@example.com" \
    -H "X-Admin-Token: ${APP_ADMIN_TOKEN}" | python3 -c "import json,sys; print(json.load(sys.stdin)['token'])")"
if [ -n "$TOKEN" ]; then
    pass "admin invite minted a token"
else
    fail "admin invite did not return a token"
fi
TODAY_STATUS="$(curl -s -o /tmp/today_body -w '%{http_code}' \
    -H "Authorization: Bearer ${TOKEN}" "${BASE}/games/${RECENT_DATE}")"
if [ "$TODAY_STATUS" = "200" ] || [ "$TODAY_STATUS" = "502" ]; then
    pass "/games/${RECENT_DATE} (authed) responded ${TODAY_STATUS}"
else
    fail "/games/${RECENT_DATE} (authed) returned unexpected status ${TODAY_STATUS}"
fi
if python3 -c "
import json
with open('/tmp/today_body') as f:
    data = json.load(f)
assert isinstance(data, dict), 'body is not a JSON object'
" 2>/tmp/today_shape_err; then
    pass "/games/${RECENT_DATE} body is valid JSON"
else
    fail "/games/${RECENT_DATE} body shape check failed: $(cat /tmp/today_shape_err)"
fi

echo "== GET /my-bets with no Authorization header -> 401 =="
MYBETS_STATUS="$(curl -s -o /tmp/mybets_body -w '%{http_code}' "${BASE}/my-bets")"
if [ "$MYBETS_STATUS" = "401" ]; then
    pass "/my-bets with no token returned 401"
else
    fail "/my-bets with no token returned ${MYBETS_STATUS}, expected 401"
fi

echo "== POST /betcheck happy-or-clean-404 =="
BETCHECK_STATUS="$(curl -s -o /tmp/betcheck_body -w '%{http_code}' \
    -X POST "${BASE}/betcheck" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H 'Content-Type: application/json' \
    -d "{\"date\": \"${RECENT_DATE}\", \"away\": \"ZZZ\", \"home\": \"YYY\", \"side\": \"home\", \"american_price\": -110}")"
# ZZZ@YYY is not a real matchup on any date -- the honest outcomes are a
# clean 404 (schedule reachable, no such game) or a 502 (schedule
# unreachable, e.g. no network). A 200 here would mean the server invented
# a game, which is the one outcome that should never happen.
if [ "$BETCHECK_STATUS" = "404" ] || [ "$BETCHECK_STATUS" = "502" ]; then
    pass "/betcheck for an unknown matchup returned a clean ${BETCHECK_STATUS}"
else
    fail "/betcheck for an unknown matchup returned ${BETCHECK_STATUS}, expected 404 or 502"
fi

echo "== stderr carries a structured request log line, with no secrets =="
if grep -q "method=GET path=/health" "$LOG_FILE"; then
    pass "request log line for /health is present in uvicorn's stderr"
else
    fail "no request log line found for /health in uvicorn's stderr"
fi
if grep -qi "bearer \|authorization:" "$LOG_FILE"; then
    fail "a bearer token or Authorization header value leaked into the log"
else
    pass "no bearer token or Authorization header value in the log"
fi

echo
if [ "$FAILURES" -eq 0 ]; then
    echo "== smoke_api.sh: all checks passed =="
    exit 0
else
    echo "== smoke_api.sh: ${FAILURES} failure(s) =="
    echo "---- uvicorn log ----"
    cat "$LOG_FILE"
    exit 1
fi
