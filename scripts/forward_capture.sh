#!/usr/bin/env bash
# DATA PLANE: the hourly forward-capture pass, deterministic end to end.
# Runs the free roster/lineup/transaction poll, then the credit-gated dense
# odds grid (with its close pass), then commits any changed data. Designed
# so the model session that invokes it does one tool call and reads one
# short transcript -- all logic lives here, not in model reasoning.
set -uo pipefail
cd "$(dirname "$0")/.."

echo "== watch =="
python3 -m src.cli watch 2>&1 | sed 's/^/  /'
echo "== dense =="
DENSE_OUT=$(python3 -m src.cli dense 2>&1)
echo "$DENSE_OUT" | sed 's/^/  /'

git add data/watch data/processed docs/OVERNIGHT_RUN.md 2>/dev/null || true
if ! git diff --cached --quiet; then
    git commit -q -m "Forward capture $(date -u +%H:%MZ)"
    git push -q || { sleep 2; git push -q; } || { sleep 4; git push -q; }
    echo "== committed =="
else
    echo "== no data changes =="
fi

# Escalation markers: the ONLY lines a model needs to react to.
if echo "$DENSE_OUT" | grep -q "skipped: credit floor"; then
    echo "ESCALATE: credit floor reached -- stop spending, tell Brey"
fi
if echo "$DENSE_OUT" | grep -q "MISSED WINDOW"; then
    echo "ESCALATE: missed capture window -- log in docs/OVERNIGHT_RUN.md"
fi
