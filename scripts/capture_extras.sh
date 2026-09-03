#!/usr/bin/env bash
# DATA PLANE: the extra capture streams added under CAPTURE NOW, RESEARCH
# LATER (docs/MASTER_PLAN.md Sec.1 claim 3, Appendix C.1 item 6): weather
# forecasts, the credit-balance log, and (env-gated) prop prices and batter
# props.
#
# Called from scripts/forward_capture.sh after the prop-listing pass; also
# runnable by hand. Deterministic end to end like forward_capture.sh is.
set -uo pipefail
cd "$(dirname "$0")/.."

# THE SWITCH for the prop-PRICE layer (docs/COLLECTION_POLICY.md, amendment
# 2026-09-02). Off by default. Flip to "1" to turn it on; anything else, or
# leaving it unset, keeps it off with no code change.
export PROP_PRICES="${PROP_PRICES:-}"

# THE SWITCH for the batter-prop layer (owner decision 3, 2026-09-03). Off
# by default. Flip to "1" to turn it on; anything else, or leaving it unset,
# keeps it off with no code change.
export BATTER_PROPS="${BATTER_PROPS:-}"

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

echo "== batter props (bounded, BATTER_PROPS=1 required) =="
BATTER_OUT=$(python3 -m src.pipeline.batter_props 2>&1)
echo "$BATTER_OUT" | sed 's/^/  /'
# A PROBE_REQUIRED status is a single informational line, never a capture
# failure -- printed once here (ESCALATE-free) so an operator sees it
# without the shell's ESCALATE grep below reacting to it.
echo "$BATTER_OUT" | grep "^batter props: PROBE_REQUIRED" || true

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
echo "$BATTER_OUT" | grep -E "^ESCALATE:|^batter_props: .* stopped" || true
if echo "$BATTER_OUT" | grep -q "skipped: credit floor"; then
    echo "ESCALATE: credit floor reached -- stop spending, tell Brey"
fi
