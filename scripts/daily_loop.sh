#!/usr/bin/env bash
# DATA PLANE: the daily operational pass, deterministic end to end.
# Snapshot, ingest, briefing, settlement, grading -- then commit whatever
# changed. Like forward_capture.sh, the invoking model session does one tool
# call and reacts only to ESCALATE lines.
#
# This file may be mid-execution on a shared checkout when a merge lands a
# new version of it. Deploy that change with a rename into place (`git
# checkout` does this), never with an in-place edit -- bash reads a running
# script incrementally off disk, so an in-place edit can hand a running
# process half of the old body and half of the new one.
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

# S8 (docs/CHECKPOINT_PHASE0_2026-09-03.md): slate -> settle -> eod, in that
# order, on the existing 10:00 UTC daily cadence -- well before the earliest
# MLB first pitch (~16:00Z), so `engine slate` sees the bulk of today's slate
# still pre-game (its own first-pitch guard skips any game already
# commenced; docs/RUNBOOK.md). Settle runs on YESTERDAY so a game has had a
# full day to post a result, and eod runs on yesterday only after settle so
# the self-review never reads a partially-settled day. Each step is guarded
# the same way as every other step in this script: its exit status is
# captured explicitly (this script has no `-e`, so a failure here already
# cannot abort the loop on its own, but a guard that never SAYS SO is not a
# guard) and turned into one ESCALATE line rather than allowed to pass
# silently; the loop always continues to the next step and to the commit
# below regardless. Output goes to this script's own log (stdout, same as
# every step above) and to docs/OVERNIGHT_RUN.md (the run note) as a short
# one-line entry per step, so a step's outcome survives past the ephemeral
# session transcript that ran this script.
TODAY=$(date -u +%Y-%m-%d)
YESTERDAY=$(date -u -d 'yesterday' +%Y-%m-%d)
RUN_NOTE=docs/OVERNIGHT_RUN.md

echo "== engine slate (today, $TODAY) =="
SLATE_OUT=$(python3 -m src.cli engine slate --date "$TODAY" 2>&1)
SLATE_STATUS=$?
echo "$SLATE_OUT" | sed 's/^/  /'
if [ "$SLATE_STATUS" -ne 0 ]; then
    echo "ESCALATE: engine slate refused or failed for $TODAY (exit $SLATE_STATUS) -- see output above; the pre-slate freshness guard (src/engine/preflight.py) refuses loudly rather than staking on stale inputs"
fi
echo "- $(date -u +%Y-%m-%dT%H:%MZ) daily_loop: engine slate --date $TODAY exit=$SLATE_STATUS" >> "$RUN_NOTE"

echo "== engine settle (yesterday, $YESTERDAY) =="
SETTLE_OUT=$(python3 -m src.cli engine settle --date "$YESTERDAY" 2>&1)
SETTLE_STATUS=$?
echo "$SETTLE_OUT" | sed 's/^/  /'
if [ "$SETTLE_STATUS" -ne 0 ]; then
    echo "ESCALATE: engine settle failed for $YESTERDAY (exit $SETTLE_STATUS) -- see output above"
fi
echo "- $(date -u +%Y-%m-%dT%H:%MZ) daily_loop: engine settle --date $YESTERDAY exit=$SETTLE_STATUS" >> "$RUN_NOTE"

echo "== eod (yesterday, $YESTERDAY) =="
EOD_OUT=$(python3 -m src.cli eod --date "$YESTERDAY" 2>&1)
EOD_STATUS=$?
echo "$EOD_OUT" | sed 's/^/  /'
if [ "$EOD_STATUS" -ne 0 ]; then
    echo "ESCALATE: eod self-review failed or refused for $YESTERDAY (exit $EOD_STATUS) -- see output above; eod refuses rather than writing an empty report when a date has no recorded decisions"
fi
echo "- $(date -u +%Y-%m-%dT%H:%MZ) daily_loop: eod --date $YESTERDAY exit=$EOD_STATUS" >> "$RUN_NOTE"

# Concurrent runs of this script and forward_capture.sh on the same shared
# checkout raced each other into stranded/mismerged commits four times in
# 30h (87312f2, de8a582, b258fc1, 9d30526): both scripts trip on their own
# schedule, and neither ever checked whether the other was mid-commit. One
# shared lock file serializes every data-plane commit-and-push across both
# scripts so only one is ever in flight; flock releases automatically when
# this script's fd 9 closes, so there is nothing to unlock explicitly.
GIT_LOCK=/tmp/linehound_git.lock
exec 9>"$GIT_LOCK"
GIT_FAILED=0
if ! flock -w 300 9; then
    echo "ESCALATE: git lock not acquired"
    exit 1
fi

# Explicit paths, not bare `data` -- data/app (customer/auth state) and
# data/raw (reproducible provider pulls, deliberately gitignored) must never
# be staged by an automated loop. Anything unbackfillable this pass writes
# lives under one of the paths named here. data/paper_accounts (one ledger
# per registered system, S5/S6a) and docs/eod (the S7 self-review, one file
# per date) were added for S8.
git add data/processed data/watch data/research data/raw/oddsapi evidence data/paper_accounts docs/eod docs/OVERNIGHT_RUN.md artifacts 2>/dev/null || true
git reset -q artifacts/demo_latest.html 2>/dev/null || true
if ! git diff --cached --quiet; then
    BRANCH=$(git rev-parse --abbrev-ref HEAD)
    if ! git commit -q -m "Daily loop $(date -u +%Y-%m-%d)"; then
        echo "ESCALATE: git commit failed"
        GIT_FAILED=1
    elif ! git fetch -q origin "$BRANCH"; then
        echo "ESCALATE: git fetch failed -- commit is local only"
        GIT_FAILED=1
    elif ! git pull -q --rebase --autostash origin "$BRANCH"; then
        # Our own just-made commit is what we're rebasing onto origin --
        # abort rather than leave the working tree mid-rebase for the next
        # run to trip over.
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
if echo "$DAILY_OUT" | grep -q "skipped: credit floor"; then
    echo "ESCALATE: credit floor reached -- stop spending, tell Brey"
fi
if echo "$DAILY_OUT" | grep -qi "traceback"; then
    echo "ESCALATE: daily pass raised -- investigate before next run"
fi
if echo "$STATUS_OUT" | grep -q "unsettled_past_dates: \[.\+\]"; then
    echo "ESCALATE: settlement gap -- past dates remain unsettled"
fi

# Exit non-zero on a git failure, but only after every escalation above has
# had its chance to print -- a lock timeout or failed push must never mask
# a credit-floor or settlement-gap escalation from the passes that already ran.
if [ "$GIT_FAILED" -eq 1 ]; then
    exit 1
fi
