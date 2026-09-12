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
EXTRAS_OUT=$(PROP_PRICES=1 BATTER_PROPS=1 DERIVATIVES=1 bash scripts/capture_extras.sh 2>&1)
echo "$EXTRAS_OUT" | grep -v "^ESCALATE:" | sed 's/^/  /'

# ---------------------------------------------------------------------------
# THE LINEUP CADENCE GATE
#
# WHY IT LIVES HERE AND NOT IN forward_capture.sh. This script is what the
# schedule actually runs: the DEFAULT branch's forward-capture.yml checks out
# the working branch and invokes `scripts/capture_slot.sh`. forward_capture.sh
# is the standalone looping variant and is NOT called by CI, so a gate placed
# there runs nowhere. Neither does an edit to the working branch's copy of
# forward-capture.yml -- cron reads the default branch's copy. Putting the gate
# in this script is the only one of the three that deploys.
#
# WHAT IT FIXES. Measured 2026-09-08: forward-test systems froze decisions a
# median 9.9 minutes before first pitch while the null baselines, which need no
# lineup, decided ~8 hours out. Nothing was waiting on data -- only two slate
# passes were scheduled (10:00Z and 21:10Z), and at 10:00Z no lineup has posted
# so every genome refuses NO_LINEUP. A complete posted lineup is available a
# median 160 minutes before first pitch; the median decision was frozen 137
# minutes after its own gating input was already visible.
#
# `slate_due` is the gate (see its docstring): due only when a COMPLETE posted
# lineup is newer than the last frozen decision set. Without it a capture
# cadence would append hundreds of null-baseline rows every slot all day,
# carrying no new information.
#
# ENRICHMENT, NEVER A BLOCKER -- the same contract daily_loop.sh states for
# weather and standings. Its own guard, prints a reason either way, never
# raises out, never an ESCALATE: a refusal here costs one optional pass, and
# the scheduled passes are unaffected.
#
# NO ODDS-API SPEND. `engine slate` reads L1 off disk; the prices this pass
# reasons about were already bought by the dense capture above.

# ---------------------------------------------------------------------------
# THE POSTED-LINEUP STORE, TOPPED UP HERE -- IN THE SCRIPT THAT RUNS.
#
# This block was added to forward_capture.sh on 2026-09-11 ("the capture
# rebuilt the lineup store every 15 minutes and threw it away") together with
# the `git add` of the store. forward_capture.sh is not what the schedule
# runs; this script is (see the gate's comment above). So for two days the
# fix ran nowhere: the store on the branch stayed at 2026-09-09 while the
# watch poller logged "lineups: games=2, written=2" every slot -- a different
# store (data/watch). Found 2026-09-12 by watching the 14:55Z run's commit
# leave data/historical/lineups.jsonl untouched.
#
# It runs BEFORE the gate, deliberately: `slate_due` asks whether a complete
# posted lineup is newer than the last frozen decision set, and the store it
# reads has to be current for that question to mean anything. Same
# enrichment contract: own try/except, prints a reason, never raises out.
# MLB Stats API only; no odds-API spend.
TODAY=$(date -u +%Y-%m-%d)
YESTERDAY=$(date -u -d 'yesterday' +%Y-%m-%d)
echo "== posted lineups + matchup history ($TODAY top-up) =="
LINEUP_OUT=$(python3 -c "
from src.pipeline import lineup_store, matchup_history

try:
    report = lineup_store.build(['$YESTERDAY', '$TODAY'],
                                refresh=['$YESTERDAY', '$TODAY'])
    print('lineups: %d date(s) fetched, %d game(s) written, %d topped up on a '
          'date already covered, %d failed'
          % (report['dates'], report['games'], report['topped_up'],
             report['failed']))
except Exception as exc:
    print('(lineups unavailable:', exc, ')')

# TODAY ONLY: the vsPlayer endpoint matchup_history reads returns CAREER
# totals with no as-of parameter (src/model/pointintime.py marks it LEAKY),
# so a played game must never be asked about. A posted lineup is a fixed
# fact once posted and may be refreshed as often as we like.
try:
    report = matchup_history.build('$TODAY')
    if report.get('error'):
        print('matchup_history $TODAY: schedule unavailable:', report['error'])
    else:
        print('matchup_history $TODAY: %d game(s) on slate, %d written, '
              '%d already stored, %d no lineup yet'
              % (report['games'], report['written'],
                 report['skipped_stored'], report['skipped_no_lineup']))
except Exception as exc:
    print('(matchup_history unavailable:', exc, ')')
" 2>&1) || LINEUP_OUT="(lineup top-up raised)"
echo "$LINEUP_OUT" | sed 's/^/  /'

echo "== lineup cadence gate =="
GATE_OUT=$(python3 -c "
from src.pipeline import lineup_store
try:
    g = lineup_store.slate_due()
    print('RUN' if g['due'] else 'SKIP', g['reason'])
except Exception as exc:
    print('SKIP gate unavailable:', exc)
" 2>&1) || GATE_OUT="SKIP gate raised"
echo "  $GATE_OUT"
if [ "${GATE_OUT%% *}" = "RUN" ]; then
    echo "== engine slate (lineup cadence) =="
    python3 -m src.cli engine slate --date "$(date -u +%Y-%m-%d)" 2>&1 \
        | sed 's/^/  /' || echo "  (slate pass failed; scheduled passes unaffected)"
    # engine slip RANKS what engine slate just froze -- see src/engine/slip.py.
    # Without this call nothing ever appends to evidence/slips_v1.jsonl, which
    # is the gap that made the whole ranked-picks/evidence-tier surface
    # (2026-09-09) invisible in production even though every piece of it
    # worked in a dry run: engine slate was the only command any script here
    # ever called. Same optional-pass contract as the gate above -- a failure
    # here costs one ranking, never the frozen decisions or staked wagers
    # engine slate already committed.
    echo "== engine slip (lineup cadence) =="
    python3 -m src.cli engine slip --date "$(date -u +%Y-%m-%d)" 2>&1 \
        | sed 's/^/  /' || echo "  (slip pass failed; decisions already frozen are unaffected)"
fi

# Deliberately OUTSIDE the lineup-cadence gate above. Everything else in this
# script asks "did this pass do its job?". This asks "is what the site is
# showing right now still TRUE?" -- and the way a slip goes false is by the
# clock running past first pitch, which happens BETWEEN passes, not during
# one. Gating it behind RUN would leave the site unaudited for exactly the
# hours the 2026-09-09 incident lived in.
#
# Never fails the slot: findings exit 1 by design, and a stale-slip warning
# must not eat the capture that follows it.
echo "== publication audit =="
AUDIT_OUT=$(python3 scripts/publication_audit.py 2>&1) || true
echo "$AUDIT_OUT" | sed 's/^/  /'
# Re-echoed unindented so the heartbeat's `^ESCALATE:` grep still matches --
# same convention as PROP_OUT/EXTRAS_OUT below.
echo "$AUDIT_OUT" | grep "^ESCALATE:" || true

GIT_LOCK=/tmp/linehound_git.lock
exec 9>"$GIT_LOCK"
GIT_FAILED=0
if ! flock -w 300 9; then
    echo "ESCALATE: git lock not acquired"
    exit 1
fi

# evidence/ and data/paper_accounts are staged because the gated slate pass
# above now writes those ledgers. Without them a pass would freeze decisions
# locally and hand the next `pull --rebase --autostash` an uncommitted ledger.
# The three historical stores the top-up above writes are named one by one,
# never `data/historical` wholesale: that directory also holds the results
# CSV and the arsenals tree, multi-megabyte churn that does not belong in a
# commit made ninety-six times a day.
git add data/watch data/processed data/raw/oddsapi docs/OVERNIGHT_RUN.md \
        evidence data/paper_accounts 2>/dev/null || true
git add data/historical/lineups.jsonl data/historical/matchup_history.jsonl data/historical/matchup_pairs.json 2>/dev/null || true
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
