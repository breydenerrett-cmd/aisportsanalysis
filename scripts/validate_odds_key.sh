#!/usr/bin/env bash
# scripts/validate_odds_key.sh -- one-shot check for a freshly-created
# ODDS_API_KEY: is it valid, how much quota is left, and is MLB in season.
#
# WHY THIS EXISTS
# ----------------
# ODDS_API_KEY is the last data credential before private beta. The moment
# Brey creates one at the-odds-api.com, we want a single command that proves
# it works before it gets wired into staging -- no fumbling, no guessing at
# what a 401 vs a 429 means, and no risk of accidentally spending credits on
# an expensive call while "just testing".
#
# WHY THE "sports" ENDPOINT
# --------------------------
# src/providers/odds.py's own quota() docstring is explicit: "Credits
# remaining, read from the sports list, which is not itself metered" -- the
# featured-odds and per-event endpoints all cost credits, but GET /v4/sports
# does not (the-odds-api.com's own docs confirm the sports list is free).
# That is also the exact call quota() in the provider module makes, so this
# script mirrors it via a raw curl instead of importing the provider, to stay
# a standalone smoke test with no repo import path or venv dependency.
#
# NEVER PRINTS THE KEY
# ----------------------
# The key is read from the environment, sent only in the request query
# string over HTTPS, and never echoed, logged, or included in any message
# this script prints -- including error paths, which report the HTTP status
# only.
set -uo pipefail

API_HOST="https://api.the-odds-api.com/v4"
SPORT="baseball_mlb"

if [ -z "${ODDS_API_KEY:-}" ]; then
    echo "FAIL: ODDS_API_KEY is not set in the environment." >&2
    echo "      copy .env.example to .env, add a key from the-odds-api.com," >&2
    echo "      export it (e.g. 'export \$(grep ODDS_API_KEY .env)'), and retry." >&2
    exit 1
fi

TMP_HEADERS="$(mktemp)"
trap 'rm -f "$TMP_HEADERS"' EXIT

# The one call this script makes. /v4/sports costs 0 credits (see
# src/providers/odds.py:quota and :list_events) -- it is the cheapest live
# call the provider module documents, and the only one that both proves the
# key works and reports quota without spending any of it.
HTTP_CODE=$(curl -sS -o /tmp/odds_sports_response.$$ -D "$TMP_HEADERS" \
    -w '%{http_code}' \
    "${API_HOST}/sports/?apiKey=${ODDS_API_KEY}")
CURL_STATUS=$?
BODY_FILE="/tmp/odds_sports_response.$$"
trap 'rm -f "$TMP_HEADERS" "$BODY_FILE"' EXIT

if [ "$CURL_STATUS" -ne 0 ]; then
    echo "FAIL: could not reach ${API_HOST} (curl exit ${CURL_STATUS})." >&2
    echo "      check network connectivity and try again." >&2
    exit 1
fi

case "$HTTP_CODE" in
    200) ;;
    401)
        echo "FAIL: odds API rejected the key (HTTP 401)." >&2
        echo "      the key is wrong, revoked, or not yet active -- verify it" >&2
        echo "      was copied in full from the-odds-api.com's dashboard." >&2
        exit 1
        ;;
    429)
        echo "FAIL: odds API says quota is exhausted (HTTP 429)." >&2
        echo "      this should not happen on a fresh key -- check the account" >&2
        echo "      dashboard at the-odds-api.com." >&2
        exit 1
        ;;
    *)
        echo "FAIL: odds API returned unexpected HTTP ${HTTP_CODE}." >&2
        exit 1
        ;;
esac

# Response headers are case-insensitive and curl -D preserves whatever casing
# the server sent, so match case-insensitively.
REMAINING=$(grep -i '^x-requests-remaining:' "$TMP_HEADERS" | tr -d '\r' | cut -d: -f2 | tr -d ' ')
USED=$(grep -i '^x-requests-used:' "$TMP_HEADERS" | tr -d '\r' | cut -d: -f2 | tr -d ' ')

echo "OK: key is valid (HTTP 200 from /v4/sports)."
echo "    credits remaining: ${REMAINING:-unknown}"
echo "    credits used so far this period: ${USED:-unknown}"
echo "    this call cost 0 credits (the sports list is free)."

# MLB in-season check: /v4/sports lists baseball_mlb only while it has games
# on the board (active=true). This is read from the same free response, no
# extra call.
if grep -q "\"key\":\"${SPORT}\"" "$BODY_FILE" 2>/dev/null || \
   grep -q "\"key\": *\"${SPORT}\"" "$BODY_FILE" 2>/dev/null; then
    if command -v python3 >/dev/null 2>&1; then
        MLB_ACTIVE=$(python3 -c "
import json, sys
try:
    data = json.load(open('${BODY_FILE}'))
except Exception:
    print('unknown'); sys.exit()
for sport in data:
    if sport.get('key') == '${SPORT}':
        print('yes' if sport.get('active') else 'no')
        sys.exit()
print('missing')
")
    else
        MLB_ACTIVE="present (install python3 to confirm active=true)"
    fi
else
    MLB_ACTIVE="missing"
fi

case "$MLB_ACTIVE" in
    yes) echo "    MLB (baseball_mlb): in season and available." ;;
    no) echo "    MLB (baseball_mlb): listed but NOT currently active (off-season or no games scheduled)." ;;
    missing) echo "    MLB (baseball_mlb): NOT in the sports list at all -- unexpected, investigate." ;;
    *) echo "    MLB (baseball_mlb): ${MLB_ACTIVE}" ;;
esac

echo ""
echo "Key validated. Safe to set ODDS_API_KEY in staging/production env."
exit 0

# ---------------------------------------------------------------------------
# DAILY CREDIT CONSUMPTION ESTIMATE -- staging capture cadence
# ---------------------------------------------------------------------------
# Numbers below are taken directly from the repo, not guessed:
#
# 1) DENSE CAPTURE (scripts/forward_capture.sh -> src.cli dense ->
#    src/pipeline/dense.py):
#      - 3 markets (h2h, spreads, totals) x 1 region (us) = 3 credits/capture
#        (src/providers/odds.py DEFAULT_MARKETS, DEFAULT_REGION)
#      - CAPTURES_PER_RUN = 4, INTERVAL_MINUTES = 15 (dense.py:52-56)
#      - forward_capture.sh is documented as "the hourly forward-capture
#        pass" -> intended to run once per hour
#      - dense.py's own header states the approved number directly:
#        "Four captures an hour across an eleven-hour slate is 132 credits
#        a day." (dense.py:26-31)
#      => DENSE: ~132 credits/day during MLB season.
#
# 2) F5 CLOSE PASS (rides the same dense.py capture moments, per-event
#    h2h_1st_5_innings market):
#      - dense.py:84-86 states measured spend is "about one credit per game
#        per night" against a docs/COLLECTION_POLICY.md-approved band of
#        15-40 credits/day for this layer.
#      - F5_CLOSE_MAX_EVENTS = 8 per run is a ceiling, not typical spend;
#        theoretical worst case is noted in-file as up to 32/night.
#      => F5 CLOSE: ~15-16 credits/day typical, up to ~32/day worst case.
#
# 3) PROP-LISTING AUDIT (src/pipeline/prop_listing.py, wired into
#    forward_capture.sh via PROP_LISTING_AUDIT="on"):
#      - CREDIT_FLOOR = 5000 (a floor guard, not a spend figure)
#      - explicitly a BOUNDED, TIME-LIMITED audit (docs/PROBE_PROP_LISTING.md,
#        approved 2026-08-31) with its own 400-credit total cap across its
#        whole life, not a recurring daily cost -- excluded from the
#        steady-state daily estimate below, but note it can add up to 400
#        credits one-time while it is switched "on".
#
# 4) FREE CALLS (do not count against quota): src.cli watch (roster/lineup/
#    transaction poll), list_events (/events), and this script's own
#    /v4/sports quota check.
#
# STEADY-STATE DAILY TOTAL (typical): ~132 + ~16 = ~148 credits/day
# STEADY-STATE DAILY TOTAL (worst case, clustered starts): ~132 + ~32 = ~164 credits/day
#
# MONTHLY (30 days):
#   typical:    148 * 30 = ~4,440 credits/month
#   worst case: 164 * 30 = ~4,920 credits/month
#   (plus up to a one-time 400 credits while the prop-listing audit runs)
#
# FREE TIER (500 credits/month) is NOT sufficient -- it would be exhausted in
# roughly 500 / 148 =~ 3.4 days at the typical rate (dense.py's own comment
# makes the same point about a naive 15-min poll: "overruns a 500-credit
# monthly free tier in under two days" for the 3-market/15-min case, which is
# the same per-call cost this cadence uses just run less densely across a
# whole day).
#
# RECOMMENDED TIER: "20K" ($30/mo, 20,000 credits) from PRICING_TIERS in
# src/providers/odds.py. ~4,440-4,920 credits/month of steady staging use
# fits inside 20,000 with wide headroom (roughly 4x), leaving room for the
# CREDIT_FLOOR=5000 reserve dense.py already refuses to dip below, manual
# testing via this script (free), occasional historical/backfill work
# (billed separately per estimate_backfill_credits), and the one-time
# prop-listing audit spend. The next tier up ("100K", $59/mo) is not needed
# unless the region list, market list, or capture cadence changes.
