#!/usr/bin/env bash
# DATA PLANE: one forward-capture SLOT, meant to be invoked repeatedly by an
# external scheduler (docs/CAPTURE_EXTERNALIZATION.md, Option A) rather than
# looping internally the way scripts/forward_capture.sh does. Each invocation
# does watch/umpire polls, exactly ONE dense odds capture (--captures 1
# --interval 0, so there is no in-process sleep), the prop-listing pass, the
# extras pass, and commits+pushes whatever changed -- then exits. Running
# this every 15 minutes from a fresh checkout reproduces the same four-a-
# hour dense cadence forward_capture.sh's internal loop used, but as four
# independent processes instead of one 45-minute one: a restart between
# invocations loses at most one slot's capture, never the whole run, and
# nothing here depends on a container surviving 45 minutes.
#
# forward_capture.sh itself is left unchanged and still works standalone
# (e.g. run by hand, or as a rollback path) -- this script only reuses its
# per-pass commands and its git-lock/commit/escalation conventions.
set -uo pipefail
cd "$(dirname "$0")/.."

export PROP_LISTING_AUDIT="on"

echo "== watch =="
python3 -m src.cli watch 2>&1 | sed 's/^/  /'
echo "== umpires =="
python3 -m src.pipeline.umpirewatch 2>&1 | sed 's/^/  /'

echo "== dense (one slot) =="
F5_STORE=data/processed/f5_close.jsonl
f5_rows() { if [ -f "$F5_STORE" ]; then wc -l < "$F5_STORE" | tr -d ' '; else echo 0; fi; }
F5_BEFORE=$(f5_rows)

DENSE_OUT=$(python3 -m src.cli dense --captures 1 --interval 0 2>&1)
echo "$DENSE_OUT" | sed 's/^/  /'

F5_AFTER=$(f5_rows)
echo "== f5 closes: ${F5_AFTER} row(s) total, +$((F5_AFTER - F5_BEFORE)) this run =="

echo "== prop listing =="
PROP_OUT=$(python3 -m src.pipeline.prop_listing 2>&1)
echo "$PROP_OUT" | sed 's/^/  /'

echo "== capture extras =="
EXTRAS_OUT=$(PROP_PRICES=1 BATTER_PROPS=1 bash scripts/capture_extras.sh 2>&1)
echo "$EXTRAS_OUT" | grep -v "^ESCALATE:" | sed 's/^/  /'

GIT_LOCK=/tmp/linehound_git.lock
exec 9>"$GIT_LOCK"
GIT_FAILED=0
if ! flock -w 300 9; then
    echo "ESCALATE: git lock not acquired"
    exit 1
fi

git add data/watch data/processed data/raw/oddsapi docs/OVERNIGHT_RUN.md 2>/dev/null || true
if ! git diff --cached --quiet; then
    BRANCH=$(git rev-parse --abbrev-ref HEAD)
    if ! git commit -q -m "Forward capture slot $(date -u +%H:%MZ) (external)"; then
        echo "ESCALATE: git commit failed"
        GIT_FAILED=1
    elif ! git fetch -q origin "$BRANCH"; then
        echo "ESCALATE: git fetch failed -- commit is local only"
        GIT_FAILED=1
    elif ! git pull -q --rebase --autostash origin "$BRANCH"; then
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

if echo "$DENSE_OUT" | grep -q "skipped: credit floor"; then
    echo "ESCALATE: credit floor reached -- stop spending, tell Brey"
fi
if echo "$DENSE_OUT" | grep -q "MISSED WINDOW"; then
    echo "ESCALATE: missed capture window -- log in docs/OVERNIGHT_RUN.md"
fi
if [ "$F5_AFTER" -eq 0 ] && echo "$DENSE_OUT" | grep -qE "^[1-9][0-9]* capture"; then
    echo "ESCALATE: dense captured but no F5 close has ever been written -- the market-depth lane is collecting nothing"
fi
echo "$PROP_OUT" | grep "^ESCALATE:" || true
echo "$EXTRAS_OUT" | grep "^ESCALATE:" || true
if echo "$PROP_OUT" | grep -q "skipped: credit floor"; then
    echo "ESCALATE: credit floor reached -- stop spending, tell Brey"
fi

if [ "$GIT_FAILED" -eq 1 ]; then
    exit 1
fi
