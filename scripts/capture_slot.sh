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

# ---------------------------------------------------------------------------
# THE SELF-CHAINING CADENCE (2026-09-14). docs/CAPTURE_EXTERNALIZATION.md,
# "Self-chaining cadence", has the full design; the short version:
#
# GitHub's `*/15` cron fired every 2-5 HOURS on this repo (gh run list,
# 09-13/09-14), so "a slot every 15 minutes" was only true while someone
# dispatched runs by hand. A run now dispatches the NEXT run of itself.
# workflow_dispatch events made with GITHUB_TOKEN do start runs (GitHub's
# loop-prevention rule exempts workflow_dispatch).
#
# REVISED THE SAME DAY after review: the first version slept INSIDE the
# shared `forward-capture` concurrency group and yielded (skipping its slot
# and NOT dispatching) when a rival queued. That held the group ~13 minutes
# of every 13, so afternoon-slate went pending almost every day and could be
# cancelled by any unchecked forward-capture that queued after it (the
# default branch's cron copy), and the chain died on every yield. Now the
# wait and the dispatch happen in a job OUTSIDE the group; only the slot
# itself joins it, and only after a check that nothing is waiting there.
#
# The pieces live here, not in YAML, so that every caller shares one tested
# implementation:
#   --space-only  chained runs: sleep until ~13 minutes after the previous
#                 slot started (hourly in quiet hours), bounded. Outside the
#                 group, so the sleep blocks nobody.
#   --chain-only  dispatch the next run, unless a NEWER run of this branch's
#                 forward-capture is already alive (it carries the chain).
#                 Cannot cancel anything: the dispatched run joins the group
#                 only through --gate-only, at least 13 minutes later.
#   --gate-only   the last thing before the slot joins the group: wait while a
#                 daily-loop or afternoon-slate run is WAITING in it (GitHub
#                 cancels a pending run when a newer one queues), bounded;
#                 give up the slot rather than cancel one.
#   (no flag)     the slot itself; on exit it chains ONLY when the workflow
#                 file running it has no chain step of its own -- i.e. the
#                 DEFAULT branch's forward-capture.yml, the copy cron runs.
#                 That is what lets the cron backstop RESTART a dead chain.
CHAIN_BRANCH="${CHAIN_BRANCH:-claude/sports-betting-analysis-review-g1o0co}"
CHAIN_PY="${CHAIN_PY:-python3}"
CHAIN_SLEEP="${CHAIN_SLEEP:-sleep}"
# 13, not 15: a dispatch takes tens of seconds to become a running job, and
# capture_slot.sh widens the dense window on the first slot of each hour
# (minute < 15) -- every gap must stay under 15 minutes for no hour to miss it.
CHAIN_MIN_SPACING_MINUTES=13
CHAIN_QUIET_SPACING_MINUTES=60
CHAIN_QUIET_HORIZON_HOURS=26
# How long the gate waits for a waiting rival to start before giving up this
# slot. A rival is only ever waiting behind something RUNNING in the group (a
# slot, a few minutes), so 30 minutes is generous; the next chained run tries
# again 13 minutes later either way.
CHAIN_GATE_MAX_MINUTES=30
SLOT_STARTED_EPOCH=$(date +%s)

_chain_out() {
    if [ -n "${GITHUB_OUTPUT:-}" ]; then echo "$1" >> "$GITHUB_OUTPUT"; fi
}

# The job's own GITHUB_TOKEN. A workflow step passes it as GH_TOKEN. The
# default branch's forward-capture.yml (which cron runs, and which this branch
# cannot edit) passes no token to this script -- but actions/checkout@v4
# persists that same token in the checkout's git config for its fetch/push,
# so it is read from there. Never printed.
_chain_token() {
    if [ -n "${GH_TOKEN:-}" ]; then return 0; fi
    local header cred
    header=$(git config --get 'http.https://github.com/.extraheader' 2>/dev/null) || return 1
    cred=$(printf '%s' "${header##* }" | base64 -d 2>/dev/null) || return 1
    case "$cred" in
        x-access-token:?*) GH_TOKEN="${cred#x-access-token:}"; export GH_TOKEN ;;
        *) return 1 ;;
    esac
}

_chain_repo() {
    if [ -z "${GH_REPO:-}" ] && [ -n "${GITHUB_REPOSITORY:-}" ]; then
        export GH_REPO="$GITHUB_REPOSITORY"
    fi
}

# One `gh run list` over the newest 50 runs, classified by a mode:
#   blockers   a daily-loop or afternoon-slate run (any branch) WAITING --
#              queued/pending/waiting/requested. `pending` is what a run held
#              by a concurrency group reports; a `queued` check alone misses
#              exactly the run that gets cancelled. daily-loop stays in the
#              list although this branch's copy moved to its own group
#              (2026-09-14): cron runs the DEFAULT branch's copy, whose group
#              this branch cannot see or change.
#   successor  an ALIVE (waiting or in_progress) forward-capture run of THIS
#              branch that will carry the chain: any such run when
#              CHAIN_RESTARTER=1 (the cron copy only restarts a dead chain),
#              otherwise one NEWER than this run (CHAIN_SELF_RUN_ID). Newest
#              wins, so of two live chains exactly one dispatches.
# Exit 0: found (printed). Exit 1: none. Exit 2: the queue could not be read.
_chain_scan() {
    local runs
    runs=$(gh run list --limit 50 --json databaseId,status,workflowName,headBranch,event 2>/dev/null) || return 2
    CHAIN_MODE="$1" CHAIN_RUNS="$runs" CHAIN_BRANCH="$CHAIN_BRANCH" \
        CHAIN_RESTARTER="${CHAIN_RESTARTER:-}" \
        CHAIN_SELF_RUN_ID="${CHAIN_SELF_RUN_ID:-${GITHUB_RUN_ID:-}}" "$CHAIN_PY" -c '
import json, os, sys
try:
    runs = json.loads(os.environ["CHAIN_RUNS"])
except ValueError:
    sys.exit(2)
if not isinstance(runs, list):
    sys.exit(2)
mode = os.environ["CHAIN_MODE"]
waiting = {"queued", "pending", "waiting", "requested"}
alive = waiting | {"in_progress"}
restarter = os.environ.get("CHAIN_RESTARTER") == "1"
try:
    self_id = int(os.environ.get("CHAIN_SELF_RUN_ID") or 0)
except ValueError:
    self_id = 0
found = False
for run in runs:
    if not isinstance(run, dict):
        continue
    name, status = run.get("workflowName"), run.get("status")
    try:
        run_id = int(run.get("databaseId") or 0)
    except (TypeError, ValueError):
        run_id = 0
    if mode == "blockers":
        hit = name in ("daily-loop", "afternoon-slate") and status in waiting
    else:
        hit = (name == "forward-capture" and status in alive
               and run.get("headBranch") == os.environ["CHAIN_BRANCH"]
               and run_id != self_id
               and (restarter or not self_id or run_id > self_id))
    if hit:
        print("  %s: %s run %s is %s (%s)" % (
            "waiting" if mode == "blockers" else "carries the chain",
            name, run_id, status, run.get("event")))
        found = True
sys.exit(0 if found else 1)
'
}

# Minutes the NEXT slot should wait after this one started. Quiet hours
# (owner/orchestrator, 2026-09-14): no game on any registered sport's schedule
# starts within the next 26 hours -> hourly. Yesterday, today and tomorrow (UTC
# dates) cover every start inside 26 hours. Any failure to read a schedule keeps
# the 13-minute cadence: a missed slot on a game day costs more than a few extra
# free schedule reads on an off day. CHAIN_FIRST_PITCHES (space-separated ISO
# times) replaces the fetch in tests.
_chain_spacing() {
    local verdict
    verdict=$("$CHAIN_PY" -m src.sports.calendar --horizon "$CHAIN_QUIET_HORIZON_HOURS" 2>/dev/null) || verdict="UNKNOWN"
    case "$verdict" in
        QUIET)
            echo "chain: no first pitch within ${CHAIN_QUIET_HORIZON_HOURS}h -- quiet hours, hourly" >&2
            echo "$CHAIN_QUIET_SPACING_MINUTES" ;;
        ACTIVE*)
            echo "chain: ${verdict#ACTIVE } -- ${CHAIN_MIN_SPACING_MINUTES}-minute cadence" >&2
            echo "$CHAIN_MIN_SPACING_MINUTES" ;;
        *)
            echo "chain: schedule unreadable -- keeping the ${CHAIN_MIN_SPACING_MINUTES}-minute cadence" >&2
            echo "$CHAIN_MIN_SPACING_MINUTES" ;;
    esac
}

# Sleep only. No queue polling: this runs in a job that holds no concurrency
# group, so nothing can be waiting behind it.
chain_space() {
    local now prev spacing wait step
    now=$(date +%s)
    prev="${PREV_SLOT_START:-}"
    spacing="${SPACING_MINUTES:-}"
    case "$prev" in
        ''|*[!0-9]*)
            echo "spacing: not a chained run (no previous slot start) -- starting now"
            _chain_out "slot_start=$now"
            return 0 ;;
    esac
    case "$spacing" in ''|*[!0-9]*) spacing=$CHAIN_MIN_SPACING_MINUTES ;; esac
    # BOUNDED both ways: never closer than 13 minutes, never a wait longer than
    # one quiet-hours interval, even for a previous start in the future.
    if [ "$spacing" -lt "$CHAIN_MIN_SPACING_MINUTES" ]; then spacing=$CHAIN_MIN_SPACING_MINUTES; fi
    if [ "$spacing" -gt "$CHAIN_QUIET_SPACING_MINUTES" ]; then spacing=$CHAIN_QUIET_SPACING_MINUTES; fi
    wait=$((prev + spacing * 60 - now))
    if [ "$wait" -gt $((spacing * 60)) ]; then wait=$((spacing * 60)); fi
    if [ "$wait" -le 0 ]; then
        echo "spacing: previous slot started $((now - prev))s ago -- starting now"
    else
        echo "spacing: previous slot started $((now - prev))s ago; waiting ${wait}s (${spacing}-minute spacing, outside the concurrency group)"
        while [ "$wait" -gt 0 ]; do
            step=60
            if [ "$wait" -lt 60 ]; then step=$wait; fi
            "$CHAIN_SLEEP" "$step"
            wait=$((wait - step))
        done
    fi
    _chain_out "slot_start=$(date +%s)"
}

# The slot may join the shared group only when no daily-loop/afternoon-slate
# is waiting in it: the slot's job would be the NEWER pending entry and GitHub
# would cancel the rival. Waiting here costs nobody anything (no group held).
# Outputs yielded=false (join) or yielded=true (skip this slot). The residual
# race is the few seconds between the last read and the job queuing -- which
# is why this is the LAST step before the slot's job.
chain_gate() {
    local rc waited=0
    _chain_token || true
    _chain_repo
    while :; do
        _chain_scan blockers
        rc=$?
        if [ "$rc" -eq 1 ]; then
            echo "gate: nothing waiting in the forward-capture group -- the slot may join it"
            _chain_out "yielded=false"
            return 0
        fi
        if [ "$waited" -ge "$CHAIN_GATE_MAX_MINUTES" ]; then
            _chain_out "yielded=true"
            if [ "$rc" -eq 0 ]; then
                echo "gate: the run above is still waiting after ${waited} minutes -- skipping this slot rather than cancel it (the chain continues)"
                return 0
            fi
            echo "gate: BROKEN -- could not read the run queue for ${waited} minutes; skipping this slot rather than risk cancelling a waiting daily-loop or afternoon-slate"
            return 1
        fi
        if [ "$rc" -eq 0 ]; then
            echo "gate: the run above is waiting in the group; letting it start first"
        else
            echo "gate: run queue unreadable; retrying"
        fi
        "$CHAIN_SLEEP" 60
        waited=$((waited + 1))
    done
}

chain_dispatch() {
    local rc spacing start
    # Two kill switches. The repository variable reaches only this branch's
    # workflow step; the committed file also reaches the default branch's cron
    # copy, which passes this script no variables.
    if [ "${CAPTURE_CHAIN:-on}" = "off" ] || [ -f .github/CAPTURE_CHAIN_OFF ]; then
        echo "chain: switched off (CAPTURE_CHAIN=off or .github/CAPTURE_CHAIN_OFF) -- the chain stops here; cron still runs"
        return 0
    fi
    if ! command -v gh >/dev/null 2>&1; then
        echo "chain: BROKEN -- gh is not installed, the next slot was not dispatched"
        return 1
    fi
    if ! _chain_token; then
        echo "chain: BROKEN -- no token to dispatch with, the next slot was not dispatched"
        return 1
    fi
    _chain_repo
    spacing=$(_chain_spacing)
    start="${SLOT_START_EPOCH:-}"
    case "$start" in ''|*[!0-9]*) start=$SLOT_STARTED_EPOCH ;; esac
    # No rival check here, deliberately (it was here until review): the run
    # this creates cannot cancel anything, because its slot joins the group
    # only through chain_gate, 13+ minutes from now. The only question is
    # whether another live run already carries the chain.
    _chain_scan successor
    rc=$?
    if [ "$rc" -eq 0 ]; then
        echo "chain: not dispatching -- the run above is newer and dispatches the next slot itself"
        return 0
    elif [ "$rc" -ne 1 ]; then
        # Dispatching blind risks at most a duplicate chain, which the next
        # readable successor check collapses (newest wins); not dispatching
        # risks no slots until the next cron firing (2-5 hours).
        echo "chain: run queue unreadable -- dispatching anyway (a duplicate chain collapses at the next check; a missing one waits hours for cron)"
    fi
    # Three attempts with backoff (orchestrator, 2026-09-14, from the cadence
    # checker): one transient API failure used to end the chain until the
    # next cron firing, 2-5 hours later -- tonight that is every first pitch.
    local attempt
    for attempt in 1 2 3; do
        if gh workflow run forward-capture.yml --ref "$CHAIN_BRANCH" \
                -f capture_now=0 -f prev_slot_start="$start" -f spacing_minutes="$spacing"; then
            echo "chain: dispatched the next slot (${spacing}-minute spacing from $start)"
            return 0
        fi
        [ "$attempt" -lt 3 ] && "$CHAIN_SLEEP" $((attempt * 10))
    done
    echo "chain: BROKEN -- gh workflow run failed 3 times, the next slot was not dispatched"
    return 1
}

case "${1:-}" in
    --space-only) chain_space; exit $? ;;
    --chain-only) chain_dispatch; exit $? ;;
    --gate-only) chain_gate; exit $? ;;
esac

# The slot's own exit (any exit, a failed commit included) chains -- but only
# from a workflow file that has no chain step: GITHUB_WORKFLOW_REF names the
# branch the RUNNING workflow file came from. This branch's forward-capture.yml
# chains in its own `if: always()` step; running both would dispatch twice.
# From here the chain is only RESTARTED (CHAIN_RESTARTER=1): any live run of
# this branch's forward-capture already carries it.
_chain_from_script() {
    [ "${GITHUB_ACTIONS:-}" = "true" ] || return 0
    [ "${CHAIN_BY_WORKFLOW_STEP:-}" = "1" ] && return 0
    case "${GITHUB_WORKFLOW_REF:-}" in
        */forward-capture.yml@refs/heads/"$CHAIN_BRANCH") return 0 ;;
        */forward-capture.yml@*) ;;
        *) return 0 ;;
    esac
    echo "== chain (this workflow file has no chain step) =="
    CHAIN_RESTARTER=1 chain_dispatch 2>&1 | sed 's/^/  /' || true
}
trap _chain_from_script EXIT

export PROP_LISTING_AUDIT="on"

echo "== watch =="
python3 -m src.cli watch 2>&1 | sed 's/^/  /'
echo "== umpires =="
python3 -m src.pipeline.umpirewatch 2>&1 | sed 's/^/  /'

echo "== dense (one slot) =="
F5_STORE=data/processed/f5_close.jsonl
f5_rows() { if [ -f "$F5_STORE" ]; then wc -l < "$F5_STORE" | tr -d ' '; else echo 0; fi; }
F5_BEFORE=$(f5_rows)

# THE FULL-SLATE BOARD, WITH NO SET TIME (2026-09-14). The dense pass only
# fires when a game is inside its 180-minute window, so on a night slate
# nothing priced today's games until 19:40Z: the card published at 15:12Z on
# the previous night's 23:19Z board and the engine slate refused ("no price
# capture observed for 2026-09-14 at all"). The owner: "analysis needs to be
# ran pre emtively before any games". One capture call prices EVERY listed
# game (snapshots.capture), so the first slot of each hour widens the window
# to a full day -- the board is never more than an hour old for any game on
# the slate, day game or night game -- and a hand-dispatched run
# (CAPTURE_NOW=1, forward-capture.yml) does the same immediately. Cost: 3
# credits a call, at most 24 extra calls a day, inside the live envelope and
# still behind dense.run's own floor and budget guard.
CAPTURE_NOW="${CAPTURE_NOW:-}"
export CAPTURE_NOW
DENSE_WINDOW=180
if [ "$CAPTURE_NOW" = "1" ] || [ "$((10#$(date -u +%M)))" -lt 15 ]; then
    DENSE_WINDOW=1440
fi
echo "  window: ${DENSE_WINDOW} minutes (CAPTURE_NOW=${CAPTURE_NOW:-0})"
DENSE_OUT=$(python3 -m src.cli dense --captures 1 --interval 0 --window "$DENSE_WINDOW" 2>&1)
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

# THE CARD, REPUBLISHED EVERY SLOT (2026-09-14). `card publish` ran from one
# place, afternoon_slate.sh at 15:40Z, so the card was built once a day on
# whatever prices and props existed then -- before any post-lineup prop
# capture (T-2h) and, on a night slate, before any same-day price. Publishing
# is safe to repeat: a pick more than LOCK_LEAD_HOURS out is replaced by the
# fresh read, a locked pick is carried forward verbatim, a pick first made
# inside its lock window locks on the spot, and a run that changes nothing
# appends nothing (src/appstate/card_ledger.publish). No odds-API spend -- it
# reads what the passes above just bought. Never fails the slot.
# The SLATE date, not the UTC date: from 00:00Z (5 PM PT) the UTC calendar has
# already moved on while that night's West Coast games are still to come.
SLATE_DATE=$(TZ=America/New_York date +%Y-%m-%d)
# The odds-event -> game_pk map the card joins player props through
# (src/report/card.py). It was built only by daily_loop.sh at 10:00Z, and that
# loop failed 09-12 and 09-13 and was cancelled 09-14: the map held no event
# for 2026-09-14, so every prop contract failed the join and the card could
# carry no prop all day. Free (schedule + stored events), idempotent
# (already-mapped events are skipped), and run before the publish that needs it.
echo "== gamekey map ($SLATE_DATE) =="
python3 -m src.cli gamekey --date "$SLATE_DATE" 2>&1 | tail -n 4 | sed 's/^/  /' || true
echo "== card publish ($SLATE_DATE) =="
CARD_OUT=$(python3 -m src.cli card publish --date "$SLATE_DATE" 2>&1) || true
echo "$CARD_OUT" | tail -n 25 | sed 's/^/  /'

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
