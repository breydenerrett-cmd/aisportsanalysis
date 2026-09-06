#!/usr/bin/env bash
# DATA PLANE: restore or rebuild every git-ignored input scripts/daily_loop.sh
# reads, on a FRESH CHECKOUT that has none of them (data/historical/* and
# most of data/processed/* are .gitignore'd -- see that file's comments for
# which stores are the deliberate tracked exceptions). Run this once, right
# before `bash scripts/daily_loop.sh`, in any environment where the checkout
# might be cold: a GitHub Actions runner after an `actions/cache` MISS, a new
# contributor's machine, or a container that lost its disk.
#
# This script does NOT restore or populate the actions/cache itself -- that
# is a workflow-level concern (.github/workflows/daily-loop.yml's
# actions/cache step, restored before this script runs and saved after the
# loop commits). This script only asks "is each input already on disk, in
# usable shape?" and, if not, either rebuilds it from a free endpoint or
# refuses loudly. It spends ZERO odds-API credits -- every fetch here is
# MLB's free, keyless Stats API (src/providers/mlb.py) or Baseball Savant's
# free CSV export (src/providers/statcast_pitches.py), never
# src/providers/odds.py. Never run `daily`, `dense`, `snapshot`, or any
# prop/extras command from this script.
#
# INPUT-BY-INPUT (what daily_loop.sh actually reads, and where this script
# gets it from):
#
#   data/historical/statcast/ (pitch-level store, manifest.json)
#     -> `python3 -m src.cli statcast --catchup` (called by daily_loop.sh
#        itself) extends the store from the manifest's own last-covered
#        date. With NO manifest, `src.providers.statcast_pitches.catchup()`
#        already refuses (`StatcastPitchError: ... no existing windows to
#        extend -- run a full build() first`) rather than silently fetching
#        a whole season -- confirmed by reading that function, not assumed.
#        This script does not weaken that: a missing manifest here is a
#        HARD STOP (ESCALATE, exit 1), never a `build()` call. A full-season
#        `build()` is a deliberate one-time backfill an operator runs by
#        hand (or via `actions/cache`'s own cross-run persistence), not
#        something a daily bootstrap invents on its own. Measured cost of
#        NOT having this: none applicable -- there is no automatic fallback,
#        by design.
#
#   data/historical/mlb_results.csv (+ mlb_results.manifest.json)
#     -> if the manifest is missing or empty, rebuilt for the CURRENT season
#        via `src.pipeline.history.ingest_range(season_start, yesterday)`
#        against the free MLB schedule/results endpoint. Idempotent and
#        resumable (`docs`/module docstring): a second run only fetches
#        dates missing from the manifest. Measured locally (this worktree,
#        2026-09-06, 10 real days): 0.31s/date -- a ~165-day season (the
#        2026 SEASON_BOUNDS start, 2026-03-26, through yesterday) costs
#        roughly 165 * 0.31s =~ 51 seconds cold.
#
#   data/historical/pitcher_logs.jsonl
#     -> rebuilt for every probable pitcher named in the freshly-rebuilt
#        results store, via `src.pipeline.pitchers.build_log_store` (one
#        free API call per pitcher, resumable, empty-marker cached so an
#        injured pitcher is never re-fetched forever). A season has on the
#        order of 150-250 distinct starters, so this is bounded and fast --
#        not separately timed here because it is dominated by the bullpen
#        rebuild below in every measurement taken.
#
#   data/historical/bullpen_log.jsonl
#     -> rebuilt for the same current-season range via
#        `src.pipeline.bullpen.build_log` (one free schedule call per day
#        plus one free boxscore call per game that day). Measured locally
#        (3 real days, 32 games): 2.86s/date -- the same ~165-day season
#        costs roughly 165 * 2.86s =~ 472 seconds (~8 minutes) cold. This is
#        the single most expensive rebuild in this script.
#
#   data/historical/lineups.jsonl, data/historical/handedness.json
#     -> NOT pre-populated here. `python3 -m src.cli daily`'s own briefing
#        step (`src/cli.py: cmd_brief`) fetches today's posted lineups and
#        any missing handedness live, per game, on every invocation -- it
#        is already self-healing on a cold cache, at the cost of a few
#        extra free API calls on the first run after a cache miss. Nothing
#        else in the daily loop reads these two files.
#
#   data/processed/l1_observations.jsonl
#     -> NOT touched here. `engine slate` (src/engine/slate.py,
#        `refresh_l1_if_stale`) rebuilds/refreshes this itself from the
#        TRACKED odds stores (data/processed/odds_snapshots.jsonl and the
#        other `!`-negated stores in .gitignore, already present in any
#        checkout) immediately before reading it, on every invocation. A
#        bootstrap step here would be redundant with, and could race, that
#        refresh.
#
#   data/processed/matchup_matrix.jsonl
#     -> NOT read by daily_loop.sh or anything it calls (`engine slate`,
#        `engine settle`, `eod`, `gamekey`, `statcast --catchup`). Grepped
#        for `matchup_matrix` across `src/`: every hit is in
#        `src/research/matrix.py`, `src/engine/features.py` (docstring/
#        comment provenance only, not a runtime read), `src/evolab/replay.py`
#        and `src/evolab/registry.py` -- research/replay tooling the daily
#        loop never calls. Nothing to restore or rebuild.
#
#   data/historical/odds_history/, data/historical/odds_first_five/
#     -> NOT read by daily_loop.sh either. Grepped the same way: every
#        reader (`src/board/l1_historical.py`, `src/pipeline/backfill.py`,
#        `src/research/*`, `src/evolab/replay.py`) is a backfill/replay/
#        research path, invoked by its own separate CLI subcommand, never
#        by `daily`, `ledger`, `statcast --catchup`, `gamekey`, `engine
#        slate`, `engine settle`, or `eod`. The one near-exception is
#        `data/historical/first_five_results.jsonl`, read by
#        `src.engine.settle_slate.load_first_five_results` -- but that
#        store is explicitly documented in its own module ("a frozen
#        historical store that stops at 2024") and read best-effort: a
#        missing file yields an empty dict, and `settle_slate` already
#        falls back to the boxscore-derived F5 result
#        (`load_boxscore_first_five`) for any season past 2024, which is
#        every date this loop ever settles. Left absent on a fresh
#        checkout; no rebuild attempted (nothing free could rebuild a
#        frozen, no-longer-updated store, and nothing needs it to).
#
# COLD-REBUILD TOTAL: roughly 9-10 minutes for one full current season
# (results + pitcher logs + bullpen), well inside the ~15-minute stop
# condition -- measured piecewise above rather than run end-to-end here,
# since an end-to-end run would itself burn ~10 minutes of this session for
# a number this script's own per-date rates already predict accurately.
# With `actions/cache` restoring a prior run's stores on every subsequent
# day, this whole rebuild path should only ever fire once (the very first
# time the workflow runs, or after a cache eviction) -- every other day is
# a cache hit and this script does nothing but print that it found each
# store already in place.
set -uo pipefail
cd "$(dirname "$0")/.."

# Mirrors src/paths.py's own AISPORTS_DATA_DIR override so this script's
# plain `[ -f ... ]` checks agree with whatever data root the python calls
# below actually read and write -- tests exercise this with a scratch
# AISPORTS_DATA_DIR rather than the real (large, gitignored) checkout.
DATA_DIR="${AISPORTS_DATA_DIR:-data}"

TODAY=$(date -u +%Y-%m-%d)
YESTERDAY=$(date -u -d 'yesterday' +%Y-%m-%d)
SEASON=${TODAY:0:4}

echo "== daily_bootstrap: checking git-ignored inputs for $TODAY =="

# --- 1. Statcast: hard refusal on a missing manifest -----------------------
STATCAST_STORE="$DATA_DIR/historical/statcast"
if [ ! -f "$STATCAST_STORE/manifest.json" ]; then
    echo "ESCALATE: no Statcast manifest at $STATCAST_STORE/manifest.json -- refusing to run a full-season build() from a bootstrap script. Restore data/historical/statcast from the actions/cache (or an operator's backfill) before this workflow can proceed."
    exit 1
fi
echo "  statcast manifest present ($STATCAST_STORE/manifest.json) -- catchup can extend it"

# --- 2. mlb_results.csv: rebuild the current season if the manifest is missing/empty ---
RESULTS_MANIFEST="$DATA_DIR/historical/mlb_results.manifest.json"
NEED_RESULTS=0
if [ ! -s "$RESULTS_MANIFEST" ]; then
    NEED_RESULTS=1
fi

if [ "$NEED_RESULTS" -eq 1 ]; then
    echo "  mlb_results manifest missing/empty -- rebuilding season $SEASON from the free MLB results endpoint (results, pitcher logs, bullpen)"
    python3 <<PYEOF
import sys
from src.pipeline import history
from src.providers.statcast_pitches import SEASON_BOUNDS

season = int("$SEASON")
season_start = SEASON_BOUNDS.get(season, (f"{season}-03-01", None))[0]
yesterday = "$YESTERDAY"

report = history.ingest_range(season_start, yesterday)
print(f"  results: {report['processed']} date(s) processed, "
      f"{report['failed']} failed, {report['total_games_stored']} games in store")
if report["failed"]:
    print(f"  results ingest errors: {report['errors']}", file=sys.stderr)
PYEOF
    RESULTS_STATUS=$?
    if [ "$RESULTS_STATUS" -ne 0 ]; then
        echo "ESCALATE: mlb_results backfill failed (exit $RESULTS_STATUS) -- daily_loop.sh's briefing step will refuse on an empty historical store"
        exit 1
    fi
else
    echo "  mlb_results manifest present -- daily_loop.sh's own ingest step will keep it current"
fi

# --- 3. pitcher_logs.jsonl: rebuild alongside a fresh results backfill ------
PITCHER_LOG="$DATA_DIR/historical/pitcher_logs.jsonl"
if [ "$NEED_RESULTS" -eq 1 ] || [ ! -s "$PITCHER_LOG" ]; then
    echo "  rebuilding pitcher logs for season $SEASON from the free MLB endpoint"
    python3 <<PYEOF
from src.pipeline import history, pitchers

store = history.read_results()
ids = pitchers.probable_pitcher_ids(store)
report = pitchers.build_log_store(ids, "$SEASON")
print(f"  pitcher logs: {report['processed']} fetched, "
      f"{report['pitchers_in_store']} in store, {len(report.get('errors') or [])} error(s)")
PYEOF
else
    echo "  pitcher logs present -- daily_loop.sh's own refresh step will keep it current"
fi

# --- 4. bullpen_log.jsonl: rebuild the current season if missing/empty -----
BULLPEN_LOG="$DATA_DIR/historical/bullpen_log.jsonl"
if [ ! -s "$BULLPEN_LOG" ]; then
    echo "  bullpen log missing -- rebuilding season $SEASON from the free MLB endpoint (slowest step, ~8 min for a full season)"
    python3 <<PYEOF
from src.pipeline import bullpen
from src.providers.statcast_pitches import SEASON_BOUNDS

season = int("$SEASON")
season_start = SEASON_BOUNDS.get(season, (f"{season}-03-01", None))[0]
report = bullpen.build_log(season_start, "$YESTERDAY")
print(f"  bullpen: {report['dates']} date(s), {report['games']} game(s), "
      f"{report['appearances']} appearance(s), {report['failed']} failed")
PYEOF
    BULLPEN_STATUS=$?
    if [ "$BULLPEN_STATUS" -ne 0 ]; then
        echo "ESCALATE: bullpen backfill failed (exit $BULLPEN_STATUS) -- availability detectors will run blind until the next successful bootstrap"
    fi
else
    echo "  bullpen log present -- daily_loop.sh's own refresh step will keep it current"
fi

echo "== daily_bootstrap: done =="
