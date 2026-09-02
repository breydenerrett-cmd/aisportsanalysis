#!/usr/bin/env bash
# DATA PLANE: the hourly forward-capture pass, deterministic end to end.
# Runs the free roster/lineup/transaction poll, then the credit-gated dense
# odds grid (with its close pass), then commits any changed data. Designed
# so the model session that invokes it does one tool call and reads one
# short transcript -- all logic lives here, not in model reasoning.
#
# This file may be mid-execution on a shared checkout when a merge lands a
# new version of it. Deploy that change with a rename into place (`git
# checkout` does this), never with an in-place edit -- bash reads a running
# script incrementally off disk, so an in-place edit can hand a running
# process half of the old body and half of the new one.
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
# Home-plate umpire reveals (free MLB Stats API, hydrate=officials): the fifth
# admitted V3 timing class (docs/RESEARCH_V3_UMPIRE_CLASS.md). Writes
# data/watch/umpires_watch.jsonl, staged with the rest of data/watch below.
echo "== umpires =="
python3 -m src.pipeline.umpirewatch 2>&1 | sed 's/^/  /'
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

# Extras: weather forecast (0 credits), credit-log echo, and pitcher-K prop
# PRICES behind PROP_PRICES=1 (docs/COLLECTION_POLICY.md amendment 2026-09-02;
# the module enforces its own hard daily credit cap). The script does no git
# of its own -- its stores live under data/processed and are staged below.
# ESCALATE lines are held back here and re-emitted unindented further down.
echo "== capture extras =="
EXTRAS_OUT=$(PROP_PRICES=1 bash scripts/capture_extras.sh 2>&1)
echo "$EXTRAS_OUT" | grep -v "^ESCALATE:" | sed 's/^/  /'

# Concurrent runs of this script and daily_loop.sh on the same shared
# checkout raced each other into stranded/mismerged commits four times in
# 30h (87312f2, de8a582, b258fc1, 9d30526): both scripts trip hourly, and
# neither ever checked whether the other was mid-commit. One shared lock
# file serializes every data-plane commit-and-push across both scripts so
# only one is ever in flight; flock releases automatically when this
# script's fd 9 closes, so there is nothing to unlock explicitly.
GIT_LOCK=/tmp/linehound_git.lock
exec 9>"$GIT_LOCK"
GIT_FAILED=0
if ! flock -w 300 9; then
    echo "ESCALATE: git lock not acquired"
    exit 1
fi

git add data/watch data/processed docs/OVERNIGHT_RUN.md 2>/dev/null || true
if ! git diff --cached --quiet; then
    BRANCH=$(git rev-parse --abbrev-ref HEAD)
    if ! git commit -q -m "Forward capture $(date -u +%H:%MZ)"; then
        echo "ESCALATE: git commit failed"
        GIT_FAILED=1
    elif ! git fetch -q origin "$BRANCH"; then
        echo "ESCALATE: git fetch failed -- commit is local only"
        GIT_FAILED=1
    elif ! git pull -q --rebase --autostash origin "$BRANCH"; then
        # Our own just-made commit is what we're rebasing onto origin --
        # abort rather than leave the working tree mid-rebase for the next
        # hourly run to trip over.
        git rebase --abort 2>/dev/null || true
        echo "ESCALATE: rebase onto origin/$BRANCH failed -- commit is local only, needs manual resolution"
        GIT_FAILED=1
    else
        PUSH_OK=0
        for delay in 0 2 4; do
            [ "$delay" -gt 0 ] && sleep "$delay"
            if git push -q origin "$BRANCH"; then
                PUSH_OK=1
                break
            fi
        done
        if [ "$PUSH_OK" -eq 1 ]; then
            echo "== committed =="
        else
            echo "ESCALATE: push failed after retries -- commit is local only, needs manual push"
            GIT_FAILED=1
        fi
    fi
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
echo "$EXTRAS_OUT" | grep "^ESCALATE:" || true
if echo "$PROP_OUT" | grep -q "skipped: credit floor"; then
    echo "ESCALATE: credit floor reached -- stop spending, tell Brey"
fi

# Exit non-zero on a git failure, but only after every escalation above has
# had its chance to print -- a lock timeout or failed push must never mask
# a credit-floor or missed-window escalation from the passes that already ran.
if [ "$GIT_FAILED" -eq 1 ]; then
    exit 1
fi
