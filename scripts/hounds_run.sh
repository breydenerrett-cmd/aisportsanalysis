#!/usr/bin/env bash
# One command for the user-built hounds: write today's paper bets, grade recent ones, check the chain.
#
#   bash scripts/hounds_run.sh
#
# WHAT IT RUNS, IN ORDER
#   1. python -m src.hounds.user_engine run --date auto   bets for the Eastern dates "today" and
#      "tomorrow" whose lock time has arrived and whose game has not started
#   2. python -m src.hounds.user_settle run --recent 14   grade finished games (a postponed game is
#      "pending makeup", never an error)
#   3. python -m src.hounds.user_engine verify            walk the hash chain
#
# FAILURE POLICY: a failed step is printed and the script moves on, so this can sit in the capture
# slot without ever failing it. The one non-zero exit is a BROKEN CHAIN (step 3), which means the
# ledger was edited by hand and deserves a human, not a retry.
#
# NOT WIRED IN. scripts/capture_slot.sh and scripts/daily_loop.sh are untouched. The one line to add
# to the capture slot, after the multi-book capture and the game map (so the board and game_pk exist):
#
#     bash scripts/hounds_run.sh 2>&1 | sed 's/^/  /' || true
#
# WHERE IT MUST RUN: the running hounds live in the app database (data/app/app.db, APP_DB_PATH). A
# runner with no copy of that database sees no hounds and writes nothing. See docs/HOUNDS_USER.md,
# "Where the engine runs", before wiring this into a GitHub Actions slot.
#
# Environment: HOUNDS_PY (default python3), HOUNDS_LEDGER (default evidence/hounds_user_v1.jsonl).

set -u
cd "$(dirname "$0")/.."
PY="${HOUNDS_PY:-python3}"
LEDGER_ARGS=()
if [ -n "${HOUNDS_LEDGER:-}" ]; then
    LEDGER_ARGS=(--ledger "$HOUNDS_LEDGER")
fi

echo "hounds: engine"
"$PY" -m src.hounds.user_engine run --date auto ${LEDGER_ARGS[@]+"${LEDGER_ARGS[@]}"} \
    || echo "hounds: engine step failed (non-fatal)"

echo "hounds: settle"
"$PY" -m src.hounds.user_settle run --recent 14 ${LEDGER_ARGS[@]+"${LEDGER_ARGS[@]}"} \
    || echo "hounds: settle step failed (non-fatal)"

echo "hounds: verify"
"$PY" -m src.hounds.user_engine verify ${LEDGER_ARGS[@]+"${LEDGER_ARGS[@]}"}
