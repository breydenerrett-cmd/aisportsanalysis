#!/usr/bin/env bash
# DATA PLANE: the three extra capture streams added under CAPTURE NOW,
# RESEARCH LATER (docs/MASTER_PLAN.md Sec.1 claim 3, Appendix C.1 item 6):
# weather forecasts, the credit-balance log, and (env-gated) prop prices.
#
# Called from scripts/forward_capture.sh after the prop-listing pass; also
# runnable by hand. Deterministic end to end like forward_capture.sh is.
set -uo pipefail
cd "$(dirname "$0")/.."

# THE SWITCH for the prop-PRICE layer (docs/COLLECTION_POLICY.md, amendment
# 2026-09-02). Off by default. Flip to "1" to turn it on; anything else, or
# leaving it unset, keeps it off with no code change.
export PROP_PRICES="${PROP_PRICES:-}"

echo "== weather forecast (0 credits) =="
python3 -m src.pipeline.weather_capture 2>&1 | sed 's/^/  /'

# Credit-log rows are written as a side effect of dense/prop_listing/prop_prices
# reading the odds quota, not by a pass of their own -- this line only shows
# the latest one so an operator watching this script's output can see the
# balance without a separate command.
echo "== credit log (latest) =="
python3 -m src.pipeline.creditlog 2>&1 | sed 's/^/  /'

echo "== prop prices (bounded, PROP_PRICES=1 required) =="
PROP_OUT=$(python3 -m src.pipeline.prop_prices 2>&1)
echo "$PROP_OUT" | sed 's/^/  /'

# No git here on purpose. The stores this writes live under data/processed,
# which forward_capture.sh already stages and commits under the shared
# /tmp/linehound_git.lock; a second commit-and-push path would reintroduce
# the concurrent-writer races that lock exists to prevent.

# Escalation markers: the ONLY lines a model needs to react to. Passed
# through verbatim, same convention as forward_capture.sh, so the shell and a
# human reading the log react to the same text the module wrote.
echo "$PROP_OUT" | grep "^ESCALATE:" || true
if echo "$PROP_OUT" | grep -q "skipped: credit floor"; then
    echo "ESCALATE: credit floor reached -- stop spending, tell Brey"
fi
