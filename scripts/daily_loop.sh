#!/usr/bin/env bash
# DATA PLANE: the daily operational pass, deterministic end to end.
# Snapshot, ingest, briefing, settlement, grading -- then commit whatever
# changed. Like forward_capture.sh, the invoking model session does one tool
# call and reacts only to ESCALATE lines.
set -uo pipefail
cd "$(dirname "$0")/.."

echo "== daily =="
DAILY_OUT=$(python3 -m src.cli daily 2>&1)
echo "$DAILY_OUT" | sed 's/^/  /'

echo "== ledger status =="
STATUS_OUT=$(python3 -c "
from src.pipeline import ledger
status = ledger.status()
print('games_recorded:', status.get('games_recorded'),
      'pending:', status.get('pending'), 'settled:', status.get('settled'))
print('unsettled_past_dates:', status.get('unsettled_past_dates'))
" 2>&1)
echo "$STATUS_OUT" | sed 's/^/  /'

git add data docs/OVERNIGHT_RUN.md artifacts 2>/dev/null || true
git reset -q artifacts/demo_latest.html 2>/dev/null || true
if ! git diff --cached --quiet; then
    git commit -q -m "Daily loop $(date -u +%Y-%m-%d)"
    git push -q || { sleep 2; git push -q; } || { sleep 4; git push -q; }
    echo "== committed =="
else
    echo "== no data changes =="
fi

# Escalation markers: the ONLY lines a model needs to react to.
if echo "$DAILY_OUT" | grep -q "skipped: credit floor"; then
    echo "ESCALATE: credit floor reached -- stop spending, tell Brey"
fi
if echo "$DAILY_OUT" | grep -qi "traceback"; then
    echo "ESCALATE: daily pass raised -- investigate before next run"
fi
if echo "$STATUS_OUT" | grep -q "unsettled_past_dates: \[.\+\]"; then
    echo "ESCALATE: settlement gap -- past dates remain unsettled"
fi
