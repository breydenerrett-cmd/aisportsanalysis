#!/usr/bin/env bash
# DATA PLANE: a SECOND slate pass, late enough in the day that lineups exist.
#
# WHY THIS EXISTS (finding F-1, docs/DEMO_SHIP_CHECKLIST.md, 2026-09-07)
# ---------------------------------------------------------------------
# All sixteen evolab genome systems set `require_lineup=True`, and
# `decide_with_reason` checks that FIRST. The 10:00Z daily loop freezes the
# slate about seven to twelve hours before lineups post -- on the real
# 2026-09-05 slate every one of the fifteen games posted its lineup between
# 17:16Z and 22:39Z -- so every genome refused NO_LINEUP on every game, every
# day, from 2026-09-05 onward. The only systems still deciding were the null
# baselines and the market references, neither of which is a pick to follow.
#
# This is not a new scheme: it restores how the system ran until 09-05. Every
# genome decision in the ledger through 09-03 carries a `decision_utc`
# between 16:25Z and 01:51Z, several per date, because the old cloud session
# invoked the loop repeatedly through the day. Multiple frozen sets per date
# is a shape this ledger already contains.
#
# WHAT THIS DOES AND DELIBERATELY DOES NOT DO
# --------------------------------------------
# Runs `engine slate` for TODAY and nothing else. No settle, no eod, no
# odds-API spend: settlement and the end-of-day review stay the 10:00Z loop's
# job (they read yesterday, and running them twice would rewrite a day's
# report), and this pass buys no prices -- it decides against the board the
# forward capture has already paid for.
#
# TWO FROZEN SETS FOR ONE DATE IS EXPECTED HERE, NOT A BUG. `engine slate`
# dedups on (event_id, system_id, market_key, selection_id, decision_utc), so
# this pass appends its own decisions at its own instant beside the morning's
# rather than overwriting them. That is the point: the morning pass records
# what was knowable at 10:00Z, this one what was knowable once lineups
# posted, and both stay frozen. Anything reading the ledger must keep
# treating `decision_utc` as part of a decision's identity.
#
# The first-pitch guard inside `run_slate` skips any game already under way,
# so a game that started before this pass runs is simply not decided again.
set -uo pipefail
cd "$(dirname "$0")/.."

[ -f "$(dirname "$0")/foundry_beat.sh" ] && . "$(dirname "$0")/foundry_beat.sh" || true
type foundry_beat >/dev/null 2>&1 && foundry_beat afternoon_slate start ok || true

TODAY=$(date -u +%Y-%m-%d)
RUN_NOTE=docs/OVERNIGHT_RUN.md

echo "== engine slate (afternoon pass, $TODAY) =="
SLATE_OUT=$(python3 -m src.cli engine slate --date "$TODAY" 2>&1)
SLATE_STATUS=$?
echo "$SLATE_OUT" | sed 's/^/  /'
if [ "$SLATE_STATUS" -ne 0 ]; then
    echo "ESCALATE: afternoon engine slate refused or failed for $TODAY (exit $SLATE_STATUS) -- see output above; the pre-slate freshness guard (src/engine/preflight.py) refuses loudly rather than staking on stale inputs"
    type foundry_beat >/dev/null 2>&1 && foundry_beat afternoon_slate escalate escalate "" "afternoon engine slate refused or failed" || true
fi
echo "- $(date -u +%Y-%m-%dT%H:%MZ) afternoon_slate: engine slate --date $TODAY exit=$SLATE_STATUS" >> "$RUN_NOTE"

# How many genomes actually played, printed so the run log answers the
# question this whole pass exists to answer, without anyone reading the
# ledger by hand.
python3 - "$TODAY" <<'PYEOF' 2>&1 | sed 's/^/  /'
import collections, json, sys
from src.report.engine_bridge import system_class
date = sys.argv[1]
counts = collections.Counter()
try:
    with open("evidence/decisions_v2.jsonl", encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (row.get("decision_utc") or "")[:10] != date:
                continue
            counts[system_class(row.get("system_id"))] += 1
except OSError as exc:
    print(f"could not read the decision ledger: {exc}")
else:
    print(f"decisions recorded for {date} by class: {dict(counts) or 'none'}")
    if not counts.get("FORWARD_TEST"):
        print("note: still no FORWARD_TEST decisions for this date -- the "
              "genomes refused again (most likely NO_LINEUP; the adapter logs "
              "its reason per game above)")
PYEOF

# One shared lock across every data-plane commit, exactly as
# scripts/daily_loop.sh and scripts/capture_slot.sh use: both trip on their
# own schedule and neither may be mid-commit while another is.
GIT_LOCK=/tmp/linehound_git.lock
exec 9>"$GIT_LOCK"
GIT_FAILED=0
if ! flock -w 300 9; then
    echo "ESCALATE: git lock not acquired"
    type foundry_beat >/dev/null 2>&1 && foundry_beat afternoon_slate escalate escalate "" "git lock not acquired" || true
    exit 1
fi

# Explicit paths, never bare `data`: data/app (customer/auth state) and
# data/raw must never be staged by an automated pass. This pass writes
# decisions and paper wagers, and refreshes the stores `engine slate` itself
# rebuilds on the way in.
git add data/processed evidence data/paper_accounts docs/OVERNIGHT_RUN.md 2>/dev/null || true
if ! git diff --cached --quiet; then
    BRANCH=$(git rev-parse --abbrev-ref HEAD)
    if ! git commit -q -m "Afternoon slate $TODAY"; then
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
    echo "== nothing to commit (no new decisions this pass) =="
fi

type foundry_beat >/dev/null 2>&1 && foundry_beat afternoon_slate done ok || true
exit "$GIT_FAILED"
