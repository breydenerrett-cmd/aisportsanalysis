#!/usr/bin/env bash
# DATA PLANE: the hourly forward-capture pass, deterministic end to end.
# Runs the free roster/lineup/transaction poll, then the credit-gated dense
# odds grid (with its close pass), then commits any changed data. Designed
# so the model session that invokes it does one tool call and reads one
# short transcript -- all logic lives here, not in model reasoning.
set -uo pipefail
cd "$(dirname "$0")/.."

# THE SWITCH for the prop-listing feasibility audit. Set it to anything other
# than "on" to stop that pass: one edit, no code change, nothing else affected.
# The audit is bounded and time-limited (docs/PROBE_PROP_LISTING.md, approved
# 2026-08-31) and expires at its 400-credit cap or at any of its abort criteria,
# whichever comes first. When it expires, this is the line to flip.
export PROP_LISTING_AUDIT="on"

echo "== watch =="
python3 -m src.cli watch 2>&1 | sed 's/^/  /'
echo "== dense =="
F5_STORE=data/processed/f5_close.jsonl
f5_rows() { if [ -f "$F5_STORE" ]; then wc -l < "$F5_STORE" | tr -d ' '; else echo 0; fi; }
F5_BEFORE=$(f5_rows)

DENSE_OUT=$(python3 -m src.cli dense 2>&1)
echo "$DENSE_OUT" | sed 's/^/  /'

# The F5 close store is the whole evidence base of the market-depth lane and
# PATH B, and its failure mode is silence: the pass no-ops, the run reads as
# healthy, and the absence is only noticed by someone going looking for a file
# that was never written. It went a night that way. State the count on every
# run so the silence is in the transcript instead of in nobody's hands.
F5_AFTER=$(f5_rows)
echo "== f5 closes: ${F5_AFTER} row(s) total, +$((F5_AFTER - F5_BEFORE)) this run =="

# LOWEST priority layer in the policy's order of protection, and it runs LAST
# for exactly that reason: baseline and close capture have already taken their
# credits before this pass asks for one, and it re-reads the floor itself before
# spending anything. It picks its own slots off each sampled game's first pitch,
# so the hourly cadence is all the scheduling it needs.
echo "== prop listing =="
PROP_OUT=$(python3 -m src.pipeline.prop_listing 2>&1)
echo "$PROP_OUT" | sed 's/^/  /'

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
if [ "$F5_AFTER" -eq 0 ] && echo "$DENSE_OUT" | grep -qE "^[1-9][0-9]* capture"; then
    echo "ESCALATE: dense captured but no F5 close has ever been written -- the market-depth lane is collecting nothing"
fi
# The audit prints its own ESCALATE lines (budget cap, day cap, per-run ceiling)
# and they are passed through verbatim rather than re-worded, so the shell and a
# human reading the log react to the same text the module wrote.
echo "$PROP_OUT" | grep "^ESCALATE:" || true
if echo "$PROP_OUT" | grep -q "skipped: credit floor"; then
    echo "ESCALATE: credit floor reached -- stop spending, tell Brey"
fi
