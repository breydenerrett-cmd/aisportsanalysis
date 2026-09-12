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

[ -f "$(dirname "$0")/foundry_beat.sh" ] && . "$(dirname "$0")/foundry_beat.sh" || true
type foundry_beat >/dev/null 2>&1 && foundry_beat forward_capture start ok || true

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
EXTRAS_OUT=$(PROP_PRICES=1 BATTER_PROPS=1 DERIVATIVES=1 bash scripts/capture_extras.sh 2>&1)
echo "$EXTRAS_OUT" | grep -v "^ESCALATE:" | sed 's/^/  /'

# ---------------------------------------------------------------------------
# LINEUP CADENCE (P0, 2026-09-08). Everything from here to the git section is
# ENRICHMENT, never a blocker: each block owns its try/except, prints a reason
# on a fault, never raises out of this script and never emits an ESCALATE --
# the same contract standings/weather already hold in daily_loop.sh and
# src/cli.py. A stalled MLB call must not cost the capture pass its commit.
#
# WHY IT LIVES HERE. `lineup_store.build` used to be called from exactly one
# place, the once-daily 10:00Z loop -- hours before lineups post. Measured over
# the 1,055 played decisions in the ledger on 2026-09-08: FORWARD_TEST systems
# (the ones that ARE the product, and the only ones that require a posted
# lineup) froze a median 8.9 minutes before first pitch with 72% inside 30
# minutes, while the null baselines, which need no lineup, decided with a
# median lead of 7-9 HOURS. The lineups themselves were not late: the first
# capture that saw a complete card sat a median 160 minutes before first pitch,
# so the median decision was frozen 137 minutes after its own inputs existed.
# Nothing was waiting on data. Nothing was RUNNING.
#
# So this pass does the two things that turn a posted lineup into a decision on
# the cadence lineups actually post at: it tops the posted-lineup store (and
# the matchup history built from it) up for the dates still moving, and then --
# only when a lineup has landed since the last frozen decision set -- runs one
# more slate pass.
# ---------------------------------------------------------------------------
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

# TODAY ONLY, deliberately, and this cadence does not change that: the
# vsPlayer endpoint matchup_history reads returns CAREER totals with no as-of
# parameter (src/model/pointintime.py marks it LEAKY), so asking it about a
# game that has already been played would bake that game into its own history.
# Refreshing a POSTED LINEUP more often is not a leak -- it is a fixed fact
# once posted -- and the two must not be conflated.
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
" 2>&1)
echo "$LINEUP_OUT" | sed 's/^/  /'

# THE GATE (src.pipeline.lineup_store.slate_due -- see its docstring for the
# full reasoning and for why it is stateless). A slate pass is only worth
# running when a genome's gating input has changed since the last one;
# otherwise every capture slot would append a decision set saying exactly what
# the previous one said. The decision lives in the module, not in this shell,
# so it is unit-tested and so this script and the Actions workflow cannot drift
# apart on what "due" means.
echo "== lineup-cadence slate gate =="
GATE_OUT=$(python3 -c "
from src.pipeline import lineup_store
gate = lineup_store.slate_due()
print('RUN' if gate['due'] else 'SKIP', gate['reason'])
" 2>&1) || GATE_OUT="SKIP the gate could not read its stores"
echo "$GATE_OUT" | sed 's/^/  /'

if [ "${GATE_OUT%% *}" = "RUN" ]; then
    # TWO FROZEN DECISION SETS FOR ONE DATE IS EXPECTED, NOT A BUG -- the same
    # property scripts/afternoon_slate.sh documents at length. `engine slate`
    # dedups on (event_id, system_id, market_key, selection_id, decision_utc),
    # so this pass appends its own decisions beside the morning's rather than
    # overwriting them, and STAKING is idempotent per position
    # (src.engine.slate.position_key_for), so a game already staked this date
    # is not staked again by a later pass. run_slate's own live-mode guard
    # skips any game whose first pitch has already passed. Nothing here
    # touches decision identity.
    echo "== engine slate (lineup cadence, $TODAY) =="
    CADENCE_SLATE_OUT=$(python3 -m src.cli engine slate --date "$TODAY" 2>&1)
    CADENCE_SLATE_STATUS=$?
    echo "$CADENCE_SLATE_OUT" | sed 's/^/  /'
    # Deliberately NOT an ESCALATE. The pre-slate freshness guard refusing on
    # this path means one extra pass did not happen; the 10:00Z loop and the
    # afternoon pass still run, and they escalate on their own. Turning an
    # enrichment refusal into an escalation would page on a working system.
    if [ "$CADENCE_SLATE_STATUS" -ne 0 ]; then
        echo "  (lineup-cadence slate refused or failed, exit $CADENCE_SLATE_STATUS -- see output above; the scheduled passes are unaffected)"
    fi
    echo "- $(date -u +%Y-%m-%dT%H:%MZ) forward_capture: lineup-cadence slate --date $TODAY exit=$CADENCE_SLATE_STATUS" >> docs/OVERNIGHT_RUN.md
fi

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
    type foundry_beat >/dev/null 2>&1 && foundry_beat forward_capture escalate escalate "" "git lock not acquired" || true
    exit 1
fi

# Explicit paths, never bare `data`: data/app (customer/auth state) and
# data/raw (reproducible provider pulls, gitignored) must never be staged by an
# automated pass. `evidence` and `data/paper_accounts` are staged because the
# lineup-cadence slate above writes the decision and paper-wager ledgers -- the
# same two paths daily_loop.sh and afternoon_slate.sh already stage for exactly
# that reason. Leaving them out would let a pass freeze decisions locally and
# then hand the next `pull --rebase --autostash` an uncommitted ledger to carry.
#
# data/historical/lineups.jsonl AND matchup_history, BY NAME, because leaving
# them out silently discarded three days of work.
#
# The lineup-cadence block above has called `lineup_store.build` every fifteen
# minutes since 2026-09-08. It writes to data/historical/, which was not in
# this list -- so every run rebuilt the store on the runner and every run threw
# it away unstaged. Measured 2026-09-11: data/watch/lineups_watch.jsonl was
# current to the hour with 25 games fetched that day, while
# data/historical/lineups.jsonl had not moved since 2026-09-08 and carried
# exactly one commit in its whole history.
#
# That store is not a research artefact. api/games.py and
# src/pipeline/enrichment.py read it for tonight's batting orders, so the
# product had been pricing three-day-old lineups while the block that fixed
# lineup cadence reported success every quarter hour.
#
# Named individually, never `data/historical` wholesale: that directory also
# holds mlb_results.csv and the arsenals tree, and staging it bare would put
# multi-megabyte churn into a commit that runs ninety-six times a day.
git add data/watch data/processed data/raw/oddsapi evidence data/paper_accounts docs/OVERNIGHT_RUN.md 2>/dev/null || true
git add data/historical/lineups.jsonl data/historical/matchup_history.jsonl data/historical/matchup_pairs.json 2>/dev/null || true
if ! git diff --cached --quiet; then
    BRANCH=$(git rev-parse --abbrev-ref HEAD)
    if ! git commit -q -m "Forward capture $(date -u +%H:%MZ)"; then
        echo "ESCALATE: git commit failed"
        type foundry_beat >/dev/null 2>&1 && foundry_beat forward_capture escalate escalate "" "git commit failed" || true
        GIT_FAILED=1
    elif ! git fetch -q origin "$BRANCH"; then
        echo "ESCALATE: git fetch failed -- commit is local only"
        type foundry_beat >/dev/null 2>&1 && foundry_beat forward_capture escalate escalate "" "git fetch failed" || true
        GIT_FAILED=1
    elif ! git pull -q --rebase --autostash origin "$BRANCH"; then
        # Our own just-made commit is what we're rebasing onto origin --
        # abort rather than leave the working tree mid-rebase for the next
        # hourly run to trip over.
        git rebase --abort 2>/dev/null || true
        echo "ESCALATE: rebase onto origin/$BRANCH failed -- commit is local only, needs manual resolution"
        type foundry_beat >/dev/null 2>&1 && foundry_beat forward_capture escalate escalate "" "rebase failed" || true
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
            type foundry_beat >/dev/null 2>&1 && foundry_beat forward_capture escalate escalate "" "push failed after retries" || true
            GIT_FAILED=1
        fi
    fi
else
    echo "== no data changes =="
fi

# Escalation markers: the ONLY lines a model needs to react to.
if echo "$DENSE_OUT" | grep -q "skipped: credit floor"; then
    echo "ESCALATE: credit floor reached -- stop spending, tell Brey"
    type foundry_beat >/dev/null 2>&1 && foundry_beat forward_capture escalate escalate "" "credit floor reached" || true
fi
# The 2026-09-04 outage: a same-day historical/probe purchase tripped the
# live-capture envelope and the skip crashed cmd_dense before this line ever
# ran, so nobody was ever told. src/capture/budget.py now counts only the
# LIVE_CAPTURE band against DAILY_ENVELOPE and src/cli.py's skip path no
# longer crashes on any skip reason -- but a REAL envelope block (capture's
# own spend legitimately over budget) is still a live-capture outage and
# must still say so here, not just print a clean line nobody is watching.
if echo "$DENSE_OUT" | grep -q "skipped: daily envelope"; then
    echo "ESCALATE: live-capture envelope tripped -- stop spending, tell Brey"
    type foundry_beat >/dev/null 2>&1 && foundry_beat forward_capture escalate escalate "" "live-capture envelope tripped" || true
fi
if echo "$DENSE_OUT" | grep -q "MISSED WINDOW"; then
    echo "ESCALATE: missed capture window -- log in docs/OVERNIGHT_RUN.md"
    type foundry_beat >/dev/null 2>&1 && foundry_beat forward_capture escalate escalate "" "missed capture window" || true
fi
if [ "$F5_AFTER" -eq 0 ] && echo "$DENSE_OUT" | grep -qE "^[1-9][0-9]* capture"; then
    echo "ESCALATE: dense captured but no F5 close has ever been written -- the market-depth lane is collecting nothing"
    type foundry_beat >/dev/null 2>&1 && foundry_beat forward_capture escalate escalate "" "F5 close never written" || true
fi
# The audit prints its own ESCALATE lines (budget cap, day cap, per-run ceiling)
# and they are passed through verbatim rather than re-worded, so the shell and a
# human reading the log react to the same text the module wrote.
echo "$PROP_OUT" | grep "^ESCALATE:" || true
echo "$EXTRAS_OUT" | grep "^ESCALATE:" || true
if echo "$PROP_OUT" | grep -q "skipped: credit floor"; then
    echo "ESCALATE: credit floor reached -- stop spending, tell Brey"
    type foundry_beat >/dev/null 2>&1 && foundry_beat forward_capture escalate escalate "" "credit floor reached" || true
fi
if echo "$PROP_OUT" | grep -q "skipped: daily envelope"; then
    echo "ESCALATE: live-capture envelope tripped -- stop spending, tell Brey"
    type foundry_beat >/dev/null 2>&1 && foundry_beat forward_capture escalate escalate "" "live-capture envelope tripped" || true
fi

# Exit non-zero on a git failure, but only after every escalation above has
# had its chance to print -- a lock timeout or failed push must never mask
# a credit-floor or missed-window escalation from the passes that already ran.
if [ "$GIT_FAILED" -eq 1 ]; then
    exit 1
fi

type foundry_beat >/dev/null 2>&1 && foundry_beat forward_capture end ok || true
