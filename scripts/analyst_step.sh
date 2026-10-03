#!/usr/bin/env bash
# DATA PLANE: the AI analyst's daily step (src/analyst/, docs/AI_ANALYST.md).
#
#   usage: bash scripts/analyst_step.sh TODAY YESTERDAY
#
# 1. GRADE yesterday and the day before from the results the cards use. Needs no
#    key and spends nothing, so it always runs; with an empty ledger it is a
#    no-op.
# 2. RUN today's analysis, ONLY when ANTHROPIC_API_KEY is set. Without it the
#    step says so and moves on: the key is the owner's switch (see
#    docs/decisions/AI_ANALYST_ENABLE.md), and a missing key is not a failure.
#
# THIS STEP CAN NEVER FAIL THE DAILY LOOP. It always exits 0 and never prints an
# ESCALATE line: the analyst is a separate, unproven record, and a bad day for it
# (a spend-cap stop, a rejected answer, an API outage) must not fail the data
# collection that runs beside it. Everything it does prints under "analyst:" in
# the loop's log, and `python3 -m src.cli analyst record` is where its health is
# read.
#
# THE HARD SPEND CAP lives in config/analyst.json; a run that reaches it stops
# and says STOPPED. A run is idempotent per game: a game already published is
# frozen and never paid for twice.
set -uo pipefail
cd "$(dirname "$0")/.."

TODAY="${1:?usage: analyst_step.sh TODAY YESTERDAY}"
YESTERDAY="${2:?usage: analyst_step.sh TODAY YESTERDAY}"
DAY_BEFORE=$(date -u -d "$YESTERDAY - 1 day" +%Y-%m-%d 2>/dev/null || true)

echo "== analyst grade ($YESTERDAY, $DAY_BEFORE) =="
for d in "$YESTERDAY" $DAY_BEFORE; do
    python3 -m src.cli analyst grade --date "$d" 2>&1 | sed 's/^/  analyst: /' || true
done

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "  analyst: ANTHROPIC_API_KEY is not set; today's analysis was not run (docs/decisions/AI_ANALYST_ENABLE.md)"
    exit 0
fi

echo "== analyst run ($TODAY) =="
python3 -m src.cli analyst run --date "$TODAY" 2>&1 | sed 's/^/  analyst: /' || true
exit 0
