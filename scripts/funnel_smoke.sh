#!/usr/bin/env bash
# scripts/funnel_smoke.sh -- prove the ENTIRE paid funnel end to end against
# a real local uvicorn, with Stripe faked at the transport boundary, so the
# day Brey's real STRIPE_API_KEY/STRIPE_BETA_PRICE_ID/STRIPE_WEBHOOK_SECRET
# land, this whole path is already known to work -- not just unit-tested in
# isolation.
#
# WHY A SEPARATE SCRIPT FROM scripts/smoke_api.sh
# ---------------------------------------------------
# smoke_api.sh runs with BILLING_PROVIDER unset (NullBillingProvider) --
# by design, since it is the script Brey runs before every deploy and must
# never depend on a Stripe credential existing yet. This script is the
# opposite bet: BILLING_PROVIDER=stripe, a real StripeBillingProvider, and
# the one hook that lets it run against a real uvicorn process with no real
# Stripe account -- src.appstate.billing's STRIPE_FAKE_TRANSPORT env var
# (see that module's "FUNNEL-SMOKE FAKE TRANSPORT" section). The server
# process itself can't have a `transport` callable injected into it the way
# every unit test does; STRIPE_FAKE_TRANSPORT is the only way to reach the
# same effect across a process boundary, and it is guarded (see below) so
# it can never fire against anything that looks like a real key.
#
# THE GUARD, RESTATED HERE FOR WHOEVER RUNS THIS SCRIPT
# ----------------------------------------------------------
# STRIPE_API_KEY below MUST start with "sk_test_synthetic" -- that prefix
# is the ONLY thing billing._maybe_fake_transport will ever activate under,
# and no real Stripe key (test or live) can ever start with it. If this
# script is ever pointed at a real key, the fake silently declines and
# every checkout/webhook call below would hit the real Stripe API and
# fail loudly (no network, or a real 401) -- never a fabricated success.
# tests/test_appstate_billing.py's FakeTransportGuardTests pins the same
# refusal directly against the module.
#
# WHAT THIS SCRIPT ASSERTS, END TO END
# ------------------------------------------
# landing_view beacon -> POST /signup (gets a checkout URL from the fake) ->
# a hand-signed checkout.session.completed webhook matching the fake's own
# session/customer ids -> POST /billing/webhook -> GET /signup/complete
# (one-time token, second retrieval refused) -> the token exercises the
# authed core loop (today/onboarding/betcheck/my-bets/digest) -> billing
# status flips active -> cancel -> status reflects canceled -> GET
# /admin/funnel shows the funnel counts actually moved. Same offline-
# tolerant rules as scripts/smoke_api.sh (a 502 from the live MLB schedule
# fetch is a pass, not a failure) -- and the one rule stricter than that
# script: literally nothing here may ever answer 500.
set -uo pipefail
cd "$(dirname "$0")/.."

PORT="${FUNNEL_SMOKE_PORT:-8933}"
BASE="http://127.0.0.1:${PORT}"
TMP_DB_DIR="$(mktemp -d)"
LOG_FILE="${TMP_DB_DIR}/uvicorn.log"

export APP_DB_PATH="${TMP_DB_DIR}/app.db"
export APP_ADMIN_TOKEN="funnel-smoke-$(openssl rand -hex 16 2>/dev/null || echo fallback$$)"

# Synthetic Stripe config -- see module docstring above. sk_test_synthetic*
# is the exact, and only, prefix billing._maybe_fake_transport activates
# under; anything else here would make this whole script hit a real (or
# nonexistent) Stripe API instead of the in-process fake.
export BILLING_PROVIDER="stripe"
export STRIPE_API_KEY="sk_test_synthetic_funnelsmoke"
export STRIPE_BETA_PRICE_ID="price_synthetic"
export STRIPE_WEBHOOK_SECRET="whsec_synthetic"
export STRIPE_FAKE_TRANSPORT="1"

# Mirrors of src.appstate.billing's own FAKE_TRANSPORT_* constants -- kept
# as plain shell strings (not read out of the running process) so this
# script has no way to silently drift onto whatever ids a real Stripe
# response would carry; if billing.py's constants ever change, this
# script's webhook stops matching the fake's session/customer ids and the
# GET /billing/webhook step below fails loudly rather than quietly passing
# against the wrong ids.
FAKE_CUSTOMER_ID="cus_funnelsmoke_synthetic"
FAKE_SESSION_ID="cs_funnelsmoke_synthetic"
FAKE_SUBSCRIPTION_ID="sub_funnelsmoke_synthetic"

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

echo "== starting uvicorn on :${PORT} (APP_DB_PATH=${APP_DB_PATH}, BILLING_PROVIDER=stripe, STRIPE_FAKE_TRANSPORT=1) =="
python3 -m uvicorn api.app:app --host 127.0.0.1 --port "$PORT" \
    >"$LOG_FILE" 2>&1 &
SERVER_PID=$!

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
    echo "== funnel_smoke.sh: ${FAILURES} failure(s) =="
    exit 1
fi

EMAIL="funnelsmoke+$$@example.com"

echo "== step 1: POST /funnel/event landing_view (anonymous beacon) =="
LANDING_STATUS="$(curl -s -o /tmp/funnel_landing_body -w '%{http_code}' \
    -X POST "${BASE}/funnel/event" -H 'Content-Type: application/json' \
    -d '{"kind": "landing_view"}')"
if [ "$LANDING_STATUS" = "200" ]; then
    pass "POST /funnel/event landing_view returned 200"
else
    fail "POST /funnel/event landing_view returned ${LANDING_STATUS}, expected 200"
fi

echo "== step 2: POST /signup (expect a checkout URL from the fake transport) =="
SIGNUP_BODY="$(curl -s -X POST "${BASE}/signup" -H 'Content-Type: application/json' \
    -d "{\"email\": \"${EMAIL}\"}")"
USER_ID="$(echo "$SIGNUP_BODY" | python3 -c "import json,sys; print(json.load(sys.stdin)['user_id'])" 2>/dev/null)"
CHECKOUT_URL="$(echo "$SIGNUP_BODY" | python3 -c "
import json, sys
data = json.load(sys.stdin)
print((data.get('checkout') or {}).get('checkout_url', ''))
" 2>/dev/null)"
if [ -n "$USER_ID" ] && [ -n "$CHECKOUT_URL" ]; then
    pass "POST /signup returned user_id=${USER_ID} and a checkout URL"
else
    fail "POST /signup did not return both a user_id and a checkout_url: ${SIGNUP_BODY}"
fi
# The fake transport is constructed lazily inside get_billing_provider(),
# on the first request that actually needs a StripeBillingProvider (the
# signup checkout call above) -- not at server startup. This is the first
# point it can have logged; confirming it here (rather than right after
# boot) is what makes this check meaningful instead of a guaranteed miss.
if grep -q "STRIPE FAKE TRANSPORT ACTIVE" "$LOG_FILE"; then
    pass "server log confirms the fake transport activated for this run (synthetic key)"
else
    fail "server log never confirmed the fake transport activated -- refusing to trust the rest of this run"
fi

echo "== step 3: craft + sign a checkout.session.completed webhook matching the fake's ids =="
WEBHOOK_BODY_FILE="${TMP_DB_DIR}/webhook_body.json"
python3 -c "
import json
print(json.dumps({
    'id': 'evt_funnelsmoke_synthetic',
    'type': 'checkout.session.completed',
    'data': {'object': {
        'id': '${FAKE_SESSION_ID}',
        'client_reference_id': '${USER_ID}',
        'customer': '${FAKE_CUSTOMER_ID}',
        'subscription': '${FAKE_SUBSCRIPTION_ID}',
    }},
}))
" > "$WEBHOOK_BODY_FILE"

# Signs EXACTLY per src.appstate.billing.verify_stripe_webhook_signature's
# documented scheme: Stripe-Signature: t=<unix ts>,v1=<hex hmac-sha256 of
# f"{t}.{raw body}" using STRIPE_WEBHOOK_SECRET>. Read from the same file
# curl -d @file sends (byte-exact -- the scheme signs the literal body
# bytes, not a re-serialized copy).
STRIPE_SIGNATURE="$(python3 -c "
import hashlib, hmac, time
with open('${WEBHOOK_BODY_FILE}', 'rb') as f:
    payload = f.read()
ts = int(time.time())
signed = f'{ts}.'.encode('utf-8') + payload
sig = hmac.new('${STRIPE_WEBHOOK_SECRET}'.encode('utf-8'), signed, hashlib.sha256).hexdigest()
print(f't={ts},v1={sig}')
")"

echo "== step 4: POST /billing/webhook =="
WEBHOOK_STATUS="$(curl -s -o /tmp/funnel_webhook_body -w '%{http_code}' \
    -X POST "${BASE}/billing/webhook" \
    -H 'Content-Type: application/json' \
    -H "Stripe-Signature: ${STRIPE_SIGNATURE}" \
    --data-binary "@${WEBHOOK_BODY_FILE}")"
if [ "$WEBHOOK_STATUS" = "200" ]; then
    pass "POST /billing/webhook accepted the signed checkout.session.completed event"
else
    fail "POST /billing/webhook returned ${WEBHOOK_STATUS}, expected 200: $(cat /tmp/funnel_webhook_body)"
fi

echo "== step 5: GET /signup/complete mints the one-time activation token =="
COMPLETE_BODY="$(curl -s "${BASE}/signup/complete?session_id=${FAKE_SESSION_ID}")"
TOKEN="$(echo "$COMPLETE_BODY" | python3 -c "import json,sys; print(json.load(sys.stdin).get('token',''))" 2>/dev/null)"
if [ -n "$TOKEN" ]; then
    pass "GET /signup/complete returned a bearer token"
else
    fail "GET /signup/complete did not return a token: ${COMPLETE_BODY}"
fi

echo "== step 6: a second GET /signup/complete for the same session refuses (one-time only) =="
SECOND_COMPLETE_STATUS="$(curl -s -o /dev/null -w '%{http_code}' \
    "${BASE}/signup/complete?session_id=${FAKE_SESSION_ID}")"
if [ "$SECOND_COMPLETE_STATUS" = "404" ]; then
    pass "second /signup/complete retrieval returned 404 (token already taken)"
else
    fail "second /signup/complete retrieval returned ${SECOND_COMPLETE_STATUS}, expected 404"
fi

RECENT_DATE="$(python3 -c "from datetime import date, timedelta; print((date.today()-timedelta(days=2)).isoformat())")"
AUTH_HEADER=(-H "Authorization: Bearer ${TOKEN}")

echo "== step 7: authed core loop with the activated token =="
TODAY_STATUS="$(curl -s -o /dev/null -w '%{http_code}' "${AUTH_HEADER[@]}" "${BASE}/today")"
if [ "$TODAY_STATUS" = "200" ] || [ "$TODAY_STATUS" = "502" ]; then
    pass "GET /today (authed) responded ${TODAY_STATUS}"
else
    fail "GET /today (authed) returned unexpected status ${TODAY_STATUS}"
fi

ONBOARDING_STATUS="$(curl -s -o /dev/null -w '%{http_code}' "${AUTH_HEADER[@]}" "${BASE}/onboarding")"
if [ "$ONBOARDING_STATUS" = "200" ]; then
    pass "GET /onboarding (authed) responded 200"
else
    fail "GET /onboarding (authed) returned ${ONBOARDING_STATUS}, expected 200"
fi

echo "== step 8: POST /betcheck for an unknown matchup (clean 404/502, never a fabricated game) =="
BETCHECK_STATUS="$(curl -s -o /dev/null -w '%{http_code}' \
    -X POST "${BASE}/betcheck" "${AUTH_HEADER[@]}" \
    -H 'Content-Type: application/json' \
    -d "{\"date\": \"${RECENT_DATE}\", \"away\": \"ZZZ\", \"home\": \"YYY\", \"side\": \"home\", \"american_price\": -110}")"
if [ "$BETCHECK_STATUS" = "404" ] || [ "$BETCHECK_STATUS" = "502" ]; then
    pass "POST /betcheck for an unknown matchup returned a clean ${BETCHECK_STATUS}"
else
    fail "POST /betcheck for an unknown matchup returned ${BETCHECK_STATUS}, expected 404 or 502"
fi

echo "== step 9: POST /my-bets + GET /my-bets (settlement fields present, unresolved) =="
SAVE_BODY="$(curl -s -X POST "${BASE}/my-bets" "${AUTH_HEADER[@]}" \
    -H 'Content-Type: application/json' \
    -d "{\"game\": \"${RECENT_DATE} ZZZ @ YYY\", \"side\": \"home\", \"price\": -110}")"
SAVED_ID="$(echo "$SAVE_BODY" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)"
if [ -n "$SAVED_ID" ]; then
    pass "POST /my-bets saved a bet (id=${SAVED_ID})"
else
    fail "POST /my-bets did not return a saved bet id: ${SAVE_BODY}"
fi

MYBETS_STATUS="$(curl -s -o /tmp/funnel_mybets_body -w '%{http_code}' "${AUTH_HEADER[@]}" "${BASE}/my-bets")"
if [ "$MYBETS_STATUS" = "200" ] && python3 -c "
import json
with open('/tmp/funnel_mybets_body') as f:
    data = json.load(f)
bets = data['bets']
assert any(b['id'] == ${SAVED_ID:-0} for b in bets), 'saved bet missing from GET /my-bets'
match = next(b for b in bets if b['id'] == ${SAVED_ID:-0})
for field in ('settlement_status', 'settlement_reason', 'settled_at'):
    assert field in match, f'{field} missing from saved bet'
" 2>/tmp/funnel_mybets_err; then
    pass "GET /my-bets includes the saved bet with settlement fields present"
else
    fail "GET /my-bets check failed: $(cat /tmp/funnel_mybets_err 2>/dev/null)"
fi

echo "== step 10: GET /digest =="
DIGEST_STATUS="$(curl -s -o /dev/null -w '%{http_code}' "${AUTH_HEADER[@]}" "${BASE}/digest")"
if [ "$DIGEST_STATUS" = "200" ]; then
    pass "GET /digest (authed) responded 200"
else
    fail "GET /digest (authed) returned ${DIGEST_STATUS}, expected 200"
fi

echo "== step 11: GET /billing/status reflects the activated subscription =="
STATUS_BODY="$(curl -s "${AUTH_HEADER[@]}" "${BASE}/billing/status")"
STATUS_VALUE="$(echo "$STATUS_BODY" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)"
if [ "$STATUS_VALUE" = "active" ]; then
    pass "GET /billing/status reports active"
else
    fail "GET /billing/status reported ${STATUS_VALUE:-<none>}, expected active: ${STATUS_BODY}"
fi

echo "== step 12: POST /billing/cancel, then GET /billing/status reflects canceled =="
CANCEL_BODY="$(curl -s -X POST "${BASE}/billing/cancel" "${AUTH_HEADER[@]}")"
CANCEL_STATUS_VALUE="$(echo "$CANCEL_BODY" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)"
if [ "$CANCEL_STATUS_VALUE" = "canceled" ]; then
    pass "POST /billing/cancel reports canceled"
else
    fail "POST /billing/cancel reported ${CANCEL_STATUS_VALUE:-<none>}, expected canceled: ${CANCEL_BODY}"
fi
POST_CANCEL_STATUS_BODY="$(curl -s "${AUTH_HEADER[@]}" "${BASE}/billing/status")"
POST_CANCEL_STATUS_VALUE="$(echo "$POST_CANCEL_STATUS_BODY" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)"
if [ "$POST_CANCEL_STATUS_VALUE" = "canceled" ]; then
    pass "GET /billing/status reflects canceled after cancel"
else
    fail "GET /billing/status reported ${POST_CANCEL_STATUS_VALUE:-<none>} after cancel, expected canceled"
fi

echo "== step 13: GET /admin/funnel shows the funnel counts actually moved =="
curl -s -H "X-Admin-Token: ${APP_ADMIN_TOKEN}" "${BASE}/admin/funnel" > /tmp/funnel_admin_body
if python3 -c "
import json
with open('/tmp/funnel_admin_body') as f:
    data = json.load(f)
counts = {step['kind']: step['count'] for step in data['steps']}
assert counts.get('landing_view', 0) >= 1, f\"landing_view={counts.get('landing_view')}\"
assert counts.get('signup_started', 0) >= 1, f\"signup_started={counts.get('signup_started')}\"
assert counts.get('checkout_completed', 0) >= 1, f\"checkout_completed={counts.get('checkout_completed')}\"
" 2>/tmp/funnel_admin_err; then
    pass "GET /admin/funnel shows landing_view/signup_started/checkout_completed all >= 1"
else
    fail "GET /admin/funnel counts check failed: $(cat /tmp/funnel_admin_err 2>/dev/null) -- body: $(cat /tmp/funnel_admin_body)"
fi

echo "== step 14: zero 500s anywhere, and no token/secret leaked into the server log =="
if grep -q "status=5[0-9][0-9]" "$LOG_FILE"; then
    fail "a 5xx response appeared in the server log: $(grep 'status=5[0-9][0-9]' "$LOG_FILE" | head -5)"
else
    pass "no 5xx response appeared in the server log"
fi
if grep -qi "bearer \|authorization:" "$LOG_FILE"; then
    fail "a bearer token or Authorization header value leaked into the log"
else
    pass "no bearer token or Authorization header value in the log"
fi
if grep -F "$TOKEN" "$LOG_FILE" >/dev/null 2>&1; then
    fail "the activation token itself leaked into the server log"
else
    pass "the activation token never appears in the server log"
fi
if grep -F "$STRIPE_API_KEY" "$LOG_FILE" >/dev/null 2>&1 || grep -F "$STRIPE_WEBHOOK_SECRET" "$LOG_FILE" >/dev/null 2>&1; then
    fail "the synthetic Stripe key or webhook secret leaked into the server log"
else
    pass "no Stripe key/secret leaked into the server log"
fi

echo
if [ "$FAILURES" -eq 0 ]; then
    echo "== funnel_smoke.sh: all checks passed =="
    exit 0
else
    echo "== funnel_smoke.sh: ${FAILURES} failure(s) =="
    echo "---- uvicorn log (tail) ----"
    tail -n 150 "$LOG_FILE"
    exit 1
fi
