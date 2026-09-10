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

[ -f "$(dirname "$0")/foundry_beat.sh" ] && . "$(dirname "$0")/foundry_beat.sh" || true
type foundry_beat >/dev/null 2>&1 && foundry_beat daily_loop start ok || true

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

# ENRICHMENT, never a blocker -- same contract as weather in src/cli.py's
# slate/brief steps (wrapped in its own try/except, prints "(weather
# unavailable: ...)" on a fault, never raises out). Standings/playoff
# context (src/pipeline/standings.py) is the same shape: a request-time
# store the API reads with no network call, refreshed here through TODAY.
# Its exit is captured and logged below, but deliberately never turned into
# an ESCALATE line -- a stalled MLB standings call must not block
# slate/settle/eod, which is the entire operational point of this loop.
echo "== standings catchup (through $TODAY) =="
STANDINGS_OUT=$(python3 -c "
from src.pipeline import standings
try:
    report = standings.catchup(end='$TODAY')
    print('dates_built:', report['dates_built'], 'dates_skipped:', report['dates_skipped'],
          'teams:', report['teams'], 'errors:', len(report['errors']))
except Exception as exc:
    print('(standings unavailable:', exc, ')')
" 2>&1)
echo "$STANDINGS_OUT" | sed 's/^/  /'
echo "- $(date -u +%Y-%m-%dT%H:%MZ) daily_loop: standings catchup end=$TODAY" >> "$RUN_NOTE"

# THREE MORE REQUEST-TIME STORES, same ENRICHMENT-NEVER-A-BLOCKER contract as
# standings and weather above: api/games.py::_enrichment_inputs reads these
# off disk with no network call on the request path, so this loop is the only
# place they get written. See src/pipeline/matchup_history.py's own docstring
# for the full reasoning; the short version of each:
#
#   - posted lineups + matchup history: lineup_store.build tops up
#     data/historical/lineups.jsonl for YESTERDAY and TODAY (a posted lineup
#     is a fixed historical fact once a game is final, so backfilling
#     yesterday is safe). matchup_history.build is deliberately TODAY ONLY,
#     never yesterday: the vsPlayer endpoint it reads returns CAREER totals
#     with no as-of parameter (src/model/pointintime.py marks it LEAKY for
#     exactly this reason), so fetching it a day late for a game that has
#     already been played would bake that very game's plate appearances into
#     its own "history" -- a point-in-time leak this loop must not introduce.
#
#     BOTH DATES ARE PASSED AS `refresh` (2026-09-08). This step used to rely
#     on plain `resume`, which skips any date the store has ever attempted --
#     correct for a closed historical date, wrong for one still filling in.
#     The 10:00Z pass stored whatever had posted by 10:00Z, marked the date
#     covered, and every later pass (this script's own, the next morning's
#     pass over YESTERDAY, anything) skipped it: measured on 2026-09-08 the
#     store held 10 of the day's 15 games and the missing 5 were unreachable
#     forever. Naming TODAY makes each run of this script a top-up; naming
#     YESTERDAY makes the morning after the backstop that closes any game
#     the evening cadence missed. `build` decides per GAME what to append, so
#     a refresh costs one schedule request per date and writes only what is
#     genuinely new. The intraday cadence itself lives in the capture path
#     (scripts/forward_capture.sh, .github/workflows/forward-capture.yml) --
#     this script is once a day and cannot be the thing that tracks postings.
#   - pitcher splits: refresh_splits covers every probable starter TODAY's
#     schedule names, refreshed (not just cached) every run since a platoon
#     split is season-to-date and moves every time its pitcher takes the ball.
#   - pitch arsenals: statcast.build rebuilds the Savant leaderboard summary
#     for the current season -- one HTTP request per side, no lineup or
#     per-player looping, so it costs seconds regardless of slate size.
#
# Measured on a real 15-game slate (2026-09-08, 10 games with lineups posted):
# lineups+matchup_history ~70s, splits ~8s for 29 probables, arsenals ~1s.
echo "== posted lineups + matchup history ($YESTERDAY lineups only, $TODAY both) =="
MATCHUP_OUT=$(python3 -c "
from src.pipeline import lineup_store, matchup_history

try:
    lineup_report = lineup_store.build(['$YESTERDAY', '$TODAY'],
                                       refresh=['$YESTERDAY', '$TODAY'])
    print('lineups: %d date(s) processed, %d skipped, %d game(s) written '
          '(%d of them topped up on a date already covered), %d failed'
          % (lineup_report['dates'], lineup_report['skipped'],
             lineup_report['games'], lineup_report['topped_up'],
             lineup_report['failed']))
except Exception as exc:
    print('(lineups unavailable:', exc, ')')

try:
    report = matchup_history.build('$TODAY')
    if report.get('error'):
        print('matchup_history $TODAY: schedule unavailable:', report['error'])
    else:
        print('matchup_history $TODAY: %d game(s) on slate, %d written, '
              '%d already stored, %d no lineup yet, %d pair(s) fetched, '
              '%d cache hit' % (report['games'], report['written'],
                                report['skipped_stored'],
                                report['skipped_no_lineup'],
                                report['pairs_fetched'], report['pairs_cached']))
except Exception as exc:
    print('(matchup_history unavailable:', exc, ')')
" 2>&1)
echo "$MATCHUP_OUT" | sed 's/^/  /'
echo "- $(date -u +%Y-%m-%dT%H:%MZ) daily_loop: lineups+matchup_history date=$TODAY" >> "$RUN_NOTE"

echo "== pitcher platoon splits (today's probables, $TODAY) =="
SPLITS_OUT=$(python3 -c "
from src.providers import mlb
from src.pipeline import lineups

try:
    games = mlb.fetch_games('$TODAY')
    ids = [g[k] for g in games
           for k in ('away_probable_id', 'home_probable_id') if g.get(k)]
    report = lineups.refresh_splits(ids, '$TODAY'[:4])
    print('splits: %d probable(s) requested, %d fetched, %d failed' % (
        report['requested'], report['fetched'], report['failed']))
except Exception as exc:
    print('(splits unavailable:', exc, ')')
" 2>&1)
echo "$SPLITS_OUT" | sed 's/^/  /'
echo "- $(date -u +%Y-%m-%dT%H:%MZ) daily_loop: pitcher splits date=$TODAY" >> "$RUN_NOTE"

echo "== pitch arsenals (season ${TODAY:0:4}) =="
ARSENAL_OUT=$(python3 -c "
from src.providers import statcast

try:
    report = statcast.build('${TODAY:0:4}')
    print('arsenals: %d pitcher row(s), %d batter row(s), store %s' % (
        report['pitcher_rows'], report['batter_rows'], report['store']))
except Exception as exc:
    print('(arsenals unavailable:', exc, ')')
" 2>&1)
echo "$ARSENAL_OUT" | sed 's/^/  /'
echo "- $(date -u +%Y-%m-%dT%H:%MZ) daily_loop: pitch arsenals season=${TODAY:0:4}" >> "$RUN_NOTE"

# No separate "refresh L1" step belongs here: `engine slate` (via
# `src.engine.slate.run_slate`) refreshes `data/processed/
# l1_observations.jsonl` itself, immediately before reading it, on every
# invocation -- CLI, this loop, or a replay demonstration alike -- so a
# capture landing between two runs of this script is never stale by the
# time this step reads it (see `run_slate`'s own "L1 REFRESH" docstring
# section for why that placement, not a step here, is the one that cannot
# be forgotten).
# Two free prerequisites the pre-slate guard and the settle guard depend on,
# neither of which anything else on the daily cadence had been refreshing
# (2026-09-06: the Statcast pitch store had stalled at 09-02 and refused the
# slate on the 3-day coverage lag; the event->game_pk map had no rows for
# 09-05, so every 09-05 wager was written unresolved and settle refused the
# date). `engine slate` now also refreshes the map itself, immediately before
# reading it; this step covers YESTERDAY too, so a map rebuilt here can
# rescue a prior slate at settle time. Both are 0 odds-API credits.
echo "== statcast catchup (pitch store through $YESTERDAY) =="
STATCAST_OUT=$(python3 -m src.cli statcast --catchup 2>&1)
STATCAST_STATUS=$?
echo "$STATCAST_OUT" | sed 's/^/  /'
if [ "$STATCAST_STATUS" -ne 0 ]; then
    echo "ESCALATE: statcast catchup failed (exit $STATCAST_STATUS) -- the pre-slate coverage guard will refuse once the pitch store lags more than 3 days"
fi
echo "- $(date -u +%Y-%m-%dT%H:%MZ) daily_loop: statcast --catchup exit=$STATCAST_STATUS" >> "$RUN_NOTE"

echo "== gamekey map ($YESTERDAY..$TODAY) =="
GAMEKEY_OUT=$(python3 -m src.cli gamekey --date "$YESTERDAY" --end "$TODAY" 2>&1)
GAMEKEY_STATUS=$?
echo "$GAMEKEY_OUT" | sed 's/^/  /'
if [ "$GAMEKEY_STATUS" -ne 0 ]; then
    echo "ESCALATE: gamekey map refresh failed (exit $GAMEKEY_STATUS) -- unresolved events are refused at settle, never settled partially"
fi
echo "- $(date -u +%Y-%m-%dT%H:%MZ) daily_loop: gamekey --date $YESTERDAY --end $TODAY exit=$GAMEKEY_STATUS" >> "$RUN_NOTE"

# A THIRD free prerequisite, and the one whose absence was costliest. The
# post-game mechanism checks (docs/PREREG_MECHANISM_CHECKS.md) read
# play-by-play from data/processed/gameflow_<yyyy>.jsonl, and until
# 2026-09-10 NO script or workflow in this repo ever called `gameflow` --
# so the store did not exist, `mechanism_eval.evaluate` had no plays for any
# game, and every check it ever ran returned UNDETERMINED. That is the whole
# reason 0 of 624 reviews had ever classified CONFIRMED or REFUTED: not a
# classifier bug, a missing ingest. With the store backfilled, 616 of 666
# checks resolve (350 refuted, 266 confirmed).
#
# Runs BEFORE settle, because settle is what writes the reviews the checks
# land on, and a review written against an empty store is frozen wrong
# forever -- the ledger is append-only and reviews are never rewritten.
# Yesterday, not today: today's games have not finished. Zero odds credits.
echo "== gameflow ($YESTERDAY, post-game play-by-play) =="
GAMEFLOW_OUT=$(python3 -m src.cli gameflow --date "$YESTERDAY" 2>&1)
GAMEFLOW_STATUS=$?
echo "$GAMEFLOW_OUT" | sed 's/^/  /'
if [ "$GAMEFLOW_STATUS" -ne 0 ]; then
    echo "ESCALATE: gameflow ingest failed (exit $GAMEFLOW_STATUS) -- tonight's reviews will freeze with every mechanism check UNDETERMINED and cannot be re-scored later"
fi
echo "- $(date -u +%Y-%m-%dT%H:%MZ) daily_loop: gameflow --date $YESTERDAY exit=$GAMEFLOW_STATUS" >> "$RUN_NOTE"

echo "== engine slate (today, $TODAY) =="
SLATE_OUT=$(python3 -m src.cli engine slate --date "$TODAY" 2>&1)
SLATE_STATUS=$?
echo "$SLATE_OUT" | sed 's/^/  /'
if [ "$SLATE_STATUS" -ne 0 ]; then
    echo "ESCALATE: engine slate refused or failed for $TODAY (exit $SLATE_STATUS) -- see output above; the pre-slate freshness guard (src/engine/preflight.py) refuses loudly rather than staking on stale inputs"
    type foundry_beat >/dev/null 2>&1 && foundry_beat daily_loop escalate escalate "" "engine slate refused or failed" || true
fi
echo "- $(date -u +%Y-%m-%dT%H:%MZ) daily_loop: engine slate --date $TODAY exit=$SLATE_STATUS" >> "$RUN_NOTE"

# engine slip RANKS what engine slate just froze (src/engine/slip.py) --
# ENRICHMENT, never a blocker, unlike engine slate above: a ranking failure
# must never escalate over decisions and wagers that are already committed.
# Runs even when SLATE_STATUS != 0 -- a refused/partial slate can still have
# decisions worth ranking from earlier in this run or an earlier pass today.
echo "== engine slip (today, $TODAY) =="
SLIP_OUT=$(python3 -m src.cli engine slip --date "$TODAY" 2>&1)
echo "$SLIP_OUT" | sed 's/^/  /' || echo "  (slip pass failed; frozen decisions are unaffected)"
echo "- $(date -u +%Y-%m-%dT%H:%MZ) daily_loop: engine slip --date $TODAY" >> "$RUN_NOTE"

echo "== engine settle (yesterday, $YESTERDAY) =="
SETTLE_OUT=$(python3 -m src.cli engine settle --date "$YESTERDAY" 2>&1)
SETTLE_STATUS=$?
echo "$SETTLE_OUT" | sed 's/^/  /'
if [ "$SETTLE_STATUS" -ne 0 ]; then
    echo "ESCALATE: engine settle failed for $YESTERDAY (exit $SETTLE_STATUS) -- see output above"
    type foundry_beat >/dev/null 2>&1 && foundry_beat daily_loop escalate escalate "" "engine settle failed" || true
fi
echo "- $(date -u +%Y-%m-%dT%H:%MZ) daily_loop: engine settle --date $YESTERDAY exit=$SETTLE_STATUS" >> "$RUN_NOTE"

echo "== eod (yesterday, $YESTERDAY) =="
EOD_OUT=$(python3 -m src.cli eod --date "$YESTERDAY" 2>&1)
EOD_STATUS=$?
echo "$EOD_OUT" | sed 's/^/  /'
if [ "$EOD_STATUS" -ne 0 ]; then
    echo "ESCALATE: eod self-review failed or refused for $YESTERDAY (exit $EOD_STATUS) -- see output above; eod refuses rather than writing an empty report when a date has no recorded decisions"
    type foundry_beat >/dev/null 2>&1 && foundry_beat daily_loop escalate escalate "" "eod self-review failed or refused" || true
fi
echo "- $(date -u +%Y-%m-%dT%H:%MZ) daily_loop: eod --date $YESTERDAY exit=$EOD_STATUS" >> "$RUN_NOTE"

# The learning loop's reporting half: why the losses lost, with a WON control
# beside them so a pattern claimed about losers has to survive appearing in a
# winner too. It reads the mechanism checks settle just froze, which is why it
# runs here and not earlier -- and why running it before 2026-09-10 would have
# produced nothing but "no falsifiable mechanism" for every row, the gameflow
# store having never been ingested.
#
# DESCRIPTION ONLY. docs/PREREG_MECHANISM_CHECKS.md rule 4: nothing here
# returns a parameter, enters fitness, or selects a strategy. It says what
# happened. Never blocks the loop -- a missing report costs a day's reading,
# and the ledgers it describes are already frozen either way.
echo "== postmortem (yesterday, $YESTERDAY) =="
POSTMORTEM_OUT=$(python3 -m src.cli postmortem --date "$YESTERDAY" \
    --out "docs/postmortem/$YESTERDAY.md" 2>&1)
POSTMORTEM_STATUS=$?
echo "$POSTMORTEM_OUT" | sed 's/^/  /'
if [ "$POSTMORTEM_STATUS" -ne 0 ]; then
    echo "  (postmortem did not produce a report; frozen ledgers are unaffected)"
fi
echo "- $(date -u +%Y-%m-%dT%H:%MZ) daily_loop: postmortem --date $YESTERDAY exit=$POSTMORTEM_STATUS" >> "$RUN_NOTE"

# The probability model, refit nightly against whatever data now exists.
#
# `train` was the last real orphan scripts/reachability_audit.py reported:
# committed, complete, and called by nothing. The assumption was that this
# is why p_model_provenance == model_derived has zero rows across the whole
# ledger, and therefore why every gated feature (win probability, edge %,
# confidence meter, variable staking) never ships.
#
# It is not. Run on 2026-09-10 the model fits fine and has NO SIGNAL:
# 0.0006 nats of log loss better than always guessing the base rate, every
# prediction inside 0.447..0.570, calibration off by three points. Wiring
# it here does not unlock anything and is not meant to -- it makes the
# number a SERIES instead of somebody's one-time impression, so that if it
# ever does gain signal as the season accumulates, the pre-registered gate
# in src/cli.py::cmd_train escalates on the night it happens rather than
# whenever someone next thinks to check.
#
# Evaluates on the VALIDATION split. Never --test: that burns the sealed
# split (src/model/seal.py) and a sealed split spends exactly once.
# Zero odds credits, seconds to run, and never blocks the loop.
echo "== train (probability model, validation split) =="
TRAIN_OUT=$(python3 -m src.cli train 2>&1)
TRAIN_STATUS=$?
echo "$TRAIN_OUT" | sed 's/^/  /'
echo "$TRAIN_OUT" | grep "^ESCALATE:" || true
if [ "$TRAIN_STATUS" -ne 0 ]; then
    echo "  (model refit failed; nothing downstream depends on it today)"
fi
echo "- $(date -u +%Y-%m-%dT%H:%MZ) daily_loop: train exit=$TRAIN_STATUS" >> "$RUN_NOTE"

# Closing-price coverage, read-only, per market.
#
# CLV is this product's only measured leading indicator, and a closing
# price that was never captured is a decision that can never be scored --
# so coverage rotting means the measurement goes blind while every report
# keeps printing numbers. This was the last orphan the reachability audit
# reported: complete, correct, invoked by nothing, which is exactly the
# state in which coverage could degrade for weeks and only surface later
# as a confusing CLV result.
#
# Writes nothing to any ledger (see cmd_closing_audit's docstring) and
# spends no odds credits.
echo "== closing audit (per-market coverage) =="
CLOSING_OUT=$(python3 -m src.cli closing-audit 2>&1)
CLOSING_STATUS=$?
echo "$CLOSING_OUT" | sed 's/^/  /'
echo "$CLOSING_OUT" | grep "^ESCALATE:" || true
if [ "$CLOSING_STATUS" -ne 0 ]; then
    echo "  (closing audit failed; it is read-only, nothing downstream is affected)"
fi
echo "- $(date -u +%Y-%m-%dT%H:%MZ) daily_loop: closing-audit exit=$CLOSING_STATUS" >> "$RUN_NOTE"

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
    type foundry_beat >/dev/null 2>&1 && foundry_beat daily_loop escalate escalate "" "git lock not acquired" || true
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
        type foundry_beat >/dev/null 2>&1 && foundry_beat daily_loop escalate escalate "" "git commit failed" || true
        GIT_FAILED=1
    elif ! git fetch -q origin "$BRANCH"; then
        echo "ESCALATE: git fetch failed -- commit is local only"
        type foundry_beat >/dev/null 2>&1 && foundry_beat daily_loop escalate escalate "" "git fetch failed" || true
        GIT_FAILED=1
    elif ! git pull -q --rebase --autostash origin "$BRANCH"; then
        # Our own just-made commit is what we're rebasing onto origin --
        # abort rather than leave the working tree mid-rebase for the next
        # run to trip over.
        git rebase --abort 2>/dev/null || true
        echo "ESCALATE: rebase onto origin/$BRANCH failed -- commit is local only, needs manual resolution"
        type foundry_beat >/dev/null 2>&1 && foundry_beat daily_loop escalate escalate "" "rebase failed" || true
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
            type foundry_beat >/dev/null 2>&1 && foundry_beat daily_loop escalate escalate "" "push failed after retries" || true
            GIT_FAILED=1
        fi
    fi
else
    echo "== no data changes =="
fi

# Escalation markers: the ONLY lines a model needs to react to.
if echo "$DAILY_OUT" | grep -q "skipped: credit floor"; then
    echo "ESCALATE: credit floor reached -- stop spending, tell Brey"
    type foundry_beat >/dev/null 2>&1 && foundry_beat daily_loop escalate escalate "" "credit floor reached" || true
fi
if echo "$DAILY_OUT" | grep -qi "traceback"; then
    echo "ESCALATE: daily pass raised -- investigate before next run"
    type foundry_beat >/dev/null 2>&1 && foundry_beat daily_loop escalate escalate "" "daily pass raised" || true
fi
if echo "$STATUS_OUT" | grep -q "unsettled_past_dates: \[.\+\]"; then
    echo "ESCALATE: settlement gap -- past dates remain unsettled"
    type foundry_beat >/dev/null 2>&1 && foundry_beat daily_loop escalate escalate "" "settlement gap" || true
fi

# Exit non-zero on a git failure, but only after every escalation above has
# had its chance to print -- a lock timeout or failed push must never mask
# a credit-floor or settlement-gap escalation from the passes that already ran.
if [ "$GIT_FAILED" -eq 1 ]; then
    exit 1
fi

type foundry_beat >/dev/null 2>&1 && foundry_beat daily_loop end ok || true
