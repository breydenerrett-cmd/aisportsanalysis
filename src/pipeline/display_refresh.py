"""Bring every request-time store current, from free MLB endpoints, bounded.

THE DEFECT THIS CLOSES (2026-10-03)
-----------------------------------
The site's computed pages read files in the container image at request time
(`api/games.py` -> `src/pipeline/enrichment.py`, `api/postseason.py`,
`src/report/postseason_page.py`, ...). The image is built from the repo, and
nothing ever committed the stores those pages read: `mlb_results.csv` ended
2026-09-23, pitcher logs 09-07, the bullpen log 09-06, standings 09-08. The
daily loop refreshes them on its runner, but into an Actions cache the deploy
never restores, and `scripts/daily_loop.sh` deliberately does not `git add`
them (a blind add would have deleted git-only postseason rows -- read that
script's comment). Result on the public pages: "Pitcher numbers on file run
through Sept 27", bullpens left out, "no relief appearances in the last 7
days", "days rest 14", team records a week old.

WHAT THIS DOES
--------------
`refresh()` catches up, from the committed copy, to the current Eastern
baseball date:

  results        every date since the store's last covered one, regular season
                 AND postseason (see "THE GAME-TYPE RULE")
  bullpen_log    missing dates from the log's own newest date (never less than
                 the last 75 days), and yesterday re-fetched whole (a game that
                 was still in progress at the last fetch is otherwise lost)
  pitcher_logs   every starter whose log is behind a start the results show
                 (from HIS OWN coverage end), plus today's and tomorrow's
                 probables; postseason starts included, each tagged
  standings      every missing daily snapshot; yesterday re-taken if it was
                 captured before that day was over
  pitcher_splits today's and tomorrow's probables
  handedness     batters in the last days' posted lineups it has not met
  arsenals       the two Savant leaderboards (skipped if already today's)
  transactions   roster moves since the newest one stored

It runs in two places, neither of which needs a person or a model session:
at IMAGE BUILD (`deploy/Dockerfile`, after the last COPY, so the layer is
rebuilt whenever capture has committed anything, i.e. every hourly deploy) and
as a CONTAINER GUARD (`start_background_guard`, called from api/app.py's
startup) that re-checks `store_freshness.report()` hourly and refreshes in a
memory-capped subprocess only when a core store has gone stale.

On the 1 GB machine the guard stays out of the web server's way twice over. It
SKIPS a cycle (never blocks) while a cache warm-up pass or a page-cache rebuild
is running, and asks again a minute later; and the refresh child raises its own
`oom_score_adj` to 1000 (Linux), so if memory truly runs out the kernel kills
the refresh, not the server.

THE GAME-TYPE RULE (why postseason games are ingested, and why that is safe)
---------------------------------------------------------------------------
`ingest`'s default `--game-types training` stores the regular season only, so
that the SHARED results store never feeds a postseason game to a model as a
training row (best teams, aces starting, a selected population). A postseason
page and the card's grading cannot work without those games, so the display
ingest stores `DECISIVE_GAME_TYPES` -- the daily loop has done so since
2026-09-23. What keeps that from contaminating training is a READER-side
filter, and it was missing: `features.build_training_table` took every stored
game, so 131 postseason games (2023-2025) were already training rows for
`train`, the card calibration fit and the backtests. It now takes
`game_types=TRAINING_GAME_TYPES` by default (fixed with this module), and
postseason pitcher appearances carry a `game_type` that
`pitchers.league_fip_constant` excludes. The store holds the games; training
tables leave them out.

THE WINDOWS ARE ANCHORED ON COVERAGE, NOT ON THE CLOCK
------------------------------------------------------
The committed copy never advances (nothing commits these stores), so the gap
between its last date and today only grows until someone commits one. A window
measured back from TODAY (the first version: 21 days of starters, 75 days of
bullpen) eventually stops reaching the start of that gap, and the oldest part
of it is never fetched while /health, which counts the newest date or marker
anywhere in a file, says the store is current. So each window starts at the
store's OWN coverage end minus a small overlap: the bullpen at the log's newest
date, a starter at his own log's end (his refresh marker, in Eastern time, or
his newest start). The old window survives only as a floor on how far back to
look for a hole.

NEVER A WORSE STORE THAN THE ONE IT STARTED WITH
------------------------------------------------
Every step works on a COPY in `<data>/.refresh_work/`. A copy is promoted over
the original (`os.replace`, atomic) only if it parses and no key has lost a
record; any failure -- network down, deadline hit mid-step, a corrupt write --
leaves the committed copy exactly as it was ("fail soft to the committed
copy"). A deadline hit mid-step promotes the progress made so far if it is
sound: a partial catch-up is better than none, and every step resumes from its
own coverage record next time.

"No key has lost a record" is checked KEY BY KEY, not by total (see "Per-key
promotion" below): an empty answer for one pitcher replaced his whole season
while the store grew overall. A key that would lose a record keeps the union of
the committed and refreshed records, and the run says so.

BOUNDED: a wall-clock budget (default 270 s) divided across the steps by
weight, with unused time rolling forward; a one-call reachability probe up
front so an unreachable API costs seconds, not the budget; fetch timeouts of
10 s; the whole run holds one store in memory at a time (the largest, the
bullpen log, parses to roughly 100 MB). The container guard additionally caps
the child's address space.

ZERO ODDS CREDITS. Every call here is MLB's free keyless Stats API or Baseball
Savant's free leaderboard CSV; nothing imports `src.providers.odds`.
Nothing here touches data/watch, data/processed, evidence, any odds store or any
card file: those paths are never opened.

THE SEALED WINDOW. The 2026-01-01..08-27 outcomes are sealed. No step requests
a date in it (`_unsealed_start` clips every range to start on 2026-08-28),
however old a store's coverage is -- the bullpen window used to reach back to
2026-07-20 -- and rows already stored there are left exactly as they are. A
pitcher's game log is the one answer that is not asked for by date (the feed
returns a whole season), so the committed sealed-window starts are put back over
whatever it now says for them.

CLI:  python -m src.pipeline.display_refresh [--root DIR] [--max-seconds N]
          [--only results,bullpen,...] [--max-memory-mb N] [--oom-score-adj N]
          [--json PATH]
      python -m src.pipeline.display_refresh --check     (freshness only)
Exit code is 0 for every soft outcome, including "refreshed nothing"; the
JSON report and the final `through:` lines say what happened.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from src import paths
from src.pipeline import refresh_fetch, store_freshness
from src.providers import mlb

DEFAULT_MAX_SECONDS = 270.0
FETCH_TIMEOUT_S = 10
PROBE_TIMEOUT_S = 8

RESULTS_LOOKBACK_DAYS = 14        # always re-check this far back (scope + late finals)
RESULTS_CHUNK_DAYS = 5
BULLPEN_WINDOW_DAYS = 75          # fill any missing date this far back. The committed
                                  # copy never advances, so every build re-does the gap
                                  # since it; ~3 s per game day, bounded by the budget
BULLPEN_OVERLAP_DAYS = 2          # ... and never start later than the log's own newest
                                  # date minus this: the window is a floor on how far
                                  # back to look, the log's coverage end is the anchor
BULLPEN_CHUNK_DAYS = 4
PITCHER_ACTIVE_DAYS = 21          # a starter with no record of ever being checked this
                                  # season is refreshed only if he started this recently
PITCHER_OVERLAP_DAYS = 2          # a starter is refreshed when he has a start on or after
                                  # his own log's coverage end minus this
PITCHER_CHUNK = 30
PITCHER_REFRESH_AFTER_HOURS = 12.0
PITCHER_MAX_PER_RUN = 400
UPCOMING_MAX_AGE_HOURS = 30.0     # an upcoming probable with no newer start is re-asked this often
STANDINGS_MAX_BACKFILL_DAYS = 45
TRANSACTIONS_MAX_WINDOW_DAYS = 30
HANDEDNESS_LINEUP_DAYS = 7
SPLITS_DAYS_AHEAD = 1             # today and tomorrow's probables
SPLITS_REFRESH_AFTER_HOURS = 12.0  # a cached split younger than this is not re-asked for

# A pitcher store may shrink by at most this fraction (a corrected appearance)
# before a refresh refuses to promote it. Everything else may not shrink.
PITCHER_SHRINK_TOLERANCE = 0.02

# THE SEALED WINDOW. The 2026-01-01..2026-08-27 outcomes are sealed (CLAUDE.md,
# docs/test_split_seal.json): nothing outside the owner's own research path may
# fetch or rewrite them. The refresh therefore never asks for a date in this
# window, however old a store's coverage is (the bullpen window reached back to
# 2026-07-20 before this floor existed). Rows already stored there are left
# exactly as they are: nothing here purges, rewrites or "cleans" them.
SEALED_FIRST = date(2026, 1, 1)
SEALED_LAST = date(2026, 8, 27)
SEALED_FLOOR = date(2026, 8, 28)

STEP_ORDER = ("results", "bullpen", "pitchers", "standings", "splits",
              "handedness", "arsenals", "transactions")
STEP_WEIGHT = {"results": 30, "bullpen": 20, "pitchers": 25, "standings": 8,
               "splits": 5, "handedness": 4, "arsenals": 3, "transactions": 5}

ENV_GUARD_INTERVAL = "DISPLAY_REFRESH_GUARD_INTERVAL_SECONDS"
ENV_GUARD_DELAY = "DISPLAY_REFRESH_GUARD_INITIAL_DELAY_SECONDS"
DEFAULT_GUARD_DELAY_S = 120.0
GUARD_MIN_GAP_S = 1800.0          # never start two refreshes closer than this
GUARD_BUSY_RETRY_S = 60.0         # a cycle skipped because a cache build or warm-up
                                  # is running is asked again this soon, not an hour on
GUARD_CHILD_MEMORY_MB = 700
GUARD_CHILD_SECONDS = 240.0

# The kernel kills the process with the highest `oom_score_adj` first when
# memory runs out; 1000 is the maximum, "kill me before anything else". The
# refresh child sets it on itself (raising your own score needs no privilege),
# so on the 1 GB machine a real out-of-memory takes the refresh, never the web
# server. Linux only; a no-op elsewhere.
OOM_SCORE_ADJ = 1000
OOM_SCORE_PATH = "/proc/self/oom_score_adj"


class Deadline:
    """A wall-clock budget that can be sliced. `clock` is injectable so a test
    never sleeps."""

    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._end = clock() + max(float(seconds), 0.0)

    def remaining(self) -> float:
        return max(self._end - self._clock(), 0.0)

    def expired(self) -> bool:
        return self.remaining() <= 0.0

    def slice(self, weight: float, total_weight: float) -> "Deadline":
        share = weight / total_weight if total_weight > 0 else 1.0
        return Deadline(self.remaining() * share, self._clock)


# ---------------------------------------------------------------------------
# Small file helpers
# ---------------------------------------------------------------------------

def _sha(path: Path) -> Optional[str]:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return None


def _rows(path: Path) -> Optional[int]:
    """Row count by file kind; None if the file is absent."""
    if not path.exists():
        return None
    try:
        if path.suffix == ".jsonl":
            with path.open(encoding="utf-8") as handle:
                return sum(1 for line in handle if line.strip())
        if path.suffix == ".csv":
            with path.open(encoding="utf-8") as handle:
                return max(sum(1 for _ in handle) - 1, 0)
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("rows"), list):
            return len(data["rows"])
        return len(data) if hasattr(data, "__len__") else 0
    except (OSError, ValueError):
        return None


def _atomic_replace(src: Path, dest: Path) -> None:
    """Copy `src` over `dest` so a reader sees the old file or the new one,
    never half of either: the copy lands in a temp file in dest's own
    directory (same filesystem) and one `os.replace` swaps it in. `src` is
    left in place -- a later step may still read it (the pitcher step reads the
    results this run just ingested)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = dest.with_name(dest.name + ".refresh.tmp")
    try:
        shutil.copyfile(src, staging)
        os.replace(staging, dest)
    finally:
        staging.unlink(missing_ok=True)


def _rewrite_jsonl_without(path: Path, drop: Callable[[dict], bool]) -> int:
    """Stream `path` into a sibling temp file minus the rows `drop` selects,
    then replace it. Returns how many rows were dropped. Unparseable lines are
    kept byte for byte -- this never discards what it does not understand."""
    if not path.exists():
        return 0
    tmp = path.with_name(path.name + ".rewrite.tmp")
    dropped = 0
    try:
        with path.open(encoding="utf-8") as src, tmp.open("w", encoding="utf-8", newline="\n") as out:
            for line in src:
                text = line.strip()
                if text:
                    try:
                        row = json.loads(text)
                    except json.JSONDecodeError:
                        row = None
                    if isinstance(row, dict) and drop(row):
                        dropped += 1
                        continue
                out.write(line if line.endswith("\n") else line + "\n")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return dropped


def _jsonl_dates(path: Path) -> set:
    out = set()
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            day = store_freshness._day(row.get("date")) if isinstance(row, dict) else None
            if day:
                out.add(day)
    return out


def _chunks(start: date, end: date, size: int):
    day = start
    while day <= end:
        stop = min(day + timedelta(days=size - 1), end)
        yield day.isoformat(), stop.isoformat()
        day = stop + timedelta(days=1)


def _d(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _unsealed_start(start: date, end: date) -> Optional[date]:
    """`start`, moved up to the sealed floor when [start, end] would reach into
    the sealed window (the part of a range before 2026-08-28 is dropped, 2025
    included: nothing here needs it); None when nothing is left to ask for.
    EVERY date range a step requests goes through this."""
    if start < SEALED_FLOOR and end >= SEALED_FIRST:
        start = SEALED_FLOOR
    return start if start <= end else None


def _in_sealed_window(value) -> bool:
    day = store_freshness._day(value)
    return bool(day) and SEALED_FIRST <= date.fromisoformat(day) <= SEALED_LAST


# ---------------------------------------------------------------------------
# Steps. Each takes a context and returns a small report dict. They raise
# nothing the caller must handle: `refresh` wraps every step in its own
# try/except, so a failure here is one `failed` line, never a lost run.
# ---------------------------------------------------------------------------

class _Ctx:
    def __init__(self, work: Path, base: Path, now: datetime, today: str,
                 deadline: Deadline, timeout: int):
        self.work, self.base, self.now, self.today = work, base, now, today
        self.deadline, self.timeout = deadline, timeout
        self.season = today[:4]
        self.yesterday = (_d(today) - timedelta(days=1)).isoformat()

    def w(self, *parts) -> Path:
        return self.work.joinpath(*parts)


def _step_results(ctx: _Ctx) -> dict:
    from src.pipeline import history
    store, manifest = ctx.w("mlb_results.csv"), ctx.w("mlb_results.manifest.json")
    covered = history.read_manifest(manifest)
    lookback = _d(ctx.today) - timedelta(days=RESULTS_LOOKBACK_DAYS)
    if covered:
        newest = max(_d(k) for k in covered)
        start = min(lookback, newest + timedelta(days=1))
    else:
        # No coverage record at all: a cold store is a full-season backfill,
        # which is `daily_bootstrap.sh`'s job. Never start one from here.
        start = lookback
    # The coverage record is the anchor (the newest date it names, never the
    # clock); the sealed window is never asked for, however old it is.
    start = _unsealed_start(start, _d(ctx.today))
    attempted = processed = failed = 0
    errors = []
    for first, last in (_chunks(start, _d(ctx.today), RESULTS_CHUNK_DAYS) if start else ()):
        if ctx.deadline.expired():
            errors.append({"error": "deadline reached", "next": first})
            break
        # DECISIVE: the postseason is stored too (see the module docstring's
        # game-type rule). Resume is scope-aware, so a date held under the
        # regular-season-only scope is re-fetched once and then left alone.
        report = history.ingest_range(
            first, last, store_path=store, manifest_path=manifest,
            timeout=ctx.timeout, resume=True,
            game_types=mlb.DECISIVE_GAME_TYPES)
        attempted += report["attempted"]
        processed += report["processed"]
        failed += report["failed"]
        errors.extend(report["errors"][:3])
    return {"from": start.isoformat() if start else None, "to": ctx.today, "attempted": attempted,
            "processed": processed, "failed": failed, "errors": errors[:5]}


def _bullpen_yesterday_incomplete(log: Path, ctx: _Ctx) -> bool:
    """True when yesterday's schedule shows a final game the log holds no rows
    for (or the log holds nothing for yesterday at all). When the schedule
    cannot be read the answer is False: the rows are left as they are (the
    old code dropped them first and let the per-key promotion put them back)."""
    if not log.exists():
        return True
    try:
        final_pks = {str(g["gamePk"]) for g in mlb.fetch_schedule(ctx.yesterday, timeout=ctx.timeout)
                     if g.get("gamePk") and (g.get("status") or {}).get("codedGameState") == "F"}
    except mlb.MLBError:
        return False
    held = set()
    with log.open(encoding="utf-8") as handle:
        for line in handle:
            if f'"{ctx.yesterday}"' not in line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("date") == ctx.yesterday and row.get("game_pk") is not None:
                held.add(str(row["game_pk"]))
    return bool(final_pks - held)


def _step_bullpen(ctx: _Ctx) -> dict:
    from src.pipeline import bullpen
    log = ctx.w("bullpen_log.jsonl")
    yesterday = _d(ctx.yesterday)
    # Yesterday is re-fetched WHOLE: a refresh near midnight Eastern sees
    # games still in progress, and `build_log` skips a date once any row for it
    # exists, so without this a late game would be missing for good.
    #
    # ... but only when something is actually missing (2026-10-04). The log
    # holds a game only once it was final (`build_log` reads `codedGameState ==
    # "F"`), so a game that was still on at the last fetch is simply ABSENT.
    # One schedule request (the one `build_log` is about to make anyway) names
    # yesterday's final games; if the log already holds every one of them
    # there is nothing a refetch could add, and the boxscores (one request a
    # game: 288 of the 632 requests of a cold refresh, and the 4 of 19 on a
    # steady one) are not asked for again.
    refetch = _bullpen_yesterday_incomplete(log, ctx)
    replaced = (_rewrite_jsonl_without(log, lambda r: r.get("date") == ctx.yesterday)
                if refetch else 0)
    start = yesterday - timedelta(days=BULLPEN_WINDOW_DAYS - 1)
    have = _jsonl_dates(log)
    if have:
        # ANCHORED ON THE LOG'S OWN COVERAGE END. The window is only how far
        # back to look for a hole; it was relative to today, so once the gap
        # since the committed copy's last date grew past it (a copy ending in
        # September, a build in late November) the oldest part of the gap
        # stopped being fetched while /health, which counts the newest date,
        # reported the log current. Start no later than the newest date the log
        # holds minus a small overlap (dates it already holds are skipped by
        # `build_log` without a request), and never before its first date.
        start = min(start, _d(max(have)) - timedelta(days=BULLPEN_OVERLAP_DAYS))
        start = max(start, _d(min(have)))
    # The sealed window is never asked for, however old the gap is.
    start = _unsealed_start(start, yesterday)
    appearances = dates = failed = 0
    for first, last in (_chunks(start, yesterday, BULLPEN_CHUNK_DAYS) if start else ()):
        if ctx.deadline.expired():
            break
        report = bullpen.build_log(first, last, path=log, resume=True,
                                   timeout=ctx.timeout)
        appearances += report["appearances"]
        dates += report["dates"]
        failed += report["failed"]
    return {"from": start.isoformat() if start else None, "to": ctx.yesterday,
            "refetched_yesterday_rows": replaced, "dates": dates,
            "appearances": appearances, "failed": failed}


def _probable_ids_for(days, timeout) -> set:
    ids = set()
    for day in days:
        try:
            for game in mlb.fetch_games(day, timeout=timeout):
                for key in ("away_probable_id", "home_probable_id"):
                    if game.get(key):
                        ids.add(str(game[key]))
        except mlb.MLBError:
            continue
    return ids


def _eastern_day(stamp) -> Optional[str]:
    """The US Eastern calendar day of an ISO timestamp (a refresh marker's
    `checked_utc`), or None. Games are filed under the Eastern day."""
    text = str(stamp or "")
    if not text:
        return None
    try:
        moment = store_freshness._utc(text)
    except ValueError:
        return None
    return (moment + store_freshness.eastern_offset(moment)).date().isoformat()


def _pitcher_covered_through(appearances, season) -> Optional[str]:
    """The newest day one pitcher's stored log is known to cover for `season`:
    the Eastern day his refresh marker says the feed was asked, or his newest
    stored start, whichever is later. None when the log holds neither (never
    checked)."""
    best = None
    for row in appearances:
        if str(row.get("season") or str(row.get("date") or "")[:4]) != season:
            continue
        for day in (store_freshness._day(row.get("date")), _eastern_day(row.get("checked_utc"))):
            if day and (best is None or day > best):
                best = day
    return best


def _starters_to_refresh(results, existing, season, today: str) -> set:
    """The pitchers whose stored log is behind a start the results show.

    ANCHORED ON EACH PITCHER'S OWN COVERAGE, not on the clock. The first
    version refreshed every starter of the last 21 days, so a start that fell
    outside that window before the log was caught up (a copy ending in early
    September, a build in October) was never fetched while /health, which
    counts the newest marker anywhere in the file, reported the log current.
    A starter is a candidate when the results show a start of his on or after
    his log's coverage end minus `PITCHER_OVERLAP_DAYS`; one never checked this
    season only when he started within `PITCHER_ACTIVE_DAYS` (a full-season
    backfill is `daily_bootstrap.sh`'s job, not this refresh's)."""
    newest_start: dict = {}
    for row in results.values():
        day = str(row.get("date") or "")
        if not day.startswith(season):
            continue
        for key in ("away_probable_id", "home_probable_id"):
            pid = row.get(key)
            if pid not in (None, ""):
                pid = str(pid)
                if day > newest_start.get(pid, ""):
                    newest_start[pid] = day
    recent_cutoff = (_d(today) - timedelta(days=PITCHER_ACTIVE_DAYS)).isoformat()
    out = set()
    for pid, newest in newest_start.items():
        covered = _pitcher_covered_through(existing.get(pid, []), season)
        if covered is None:
            if newest >= recent_cutoff:
                out.add(pid)
        elif newest >= (_d(covered) - timedelta(days=PITCHER_OVERLAP_DAYS)).isoformat():
            out.add(pid)
    return out


def _keep_sealed_pitcher_rows(committed_path: Path, work_path: Path) -> int:
    """Put back the rows the committed copy already holds for a date in the
    sealed window. The game-log endpoint answers with a pitcher's WHOLE
    season, so a refresh would otherwise replace his stored sealed-window
    starts with the feed's current values (a stat correction included); no date
    is requested, but the rows are rewritten. An appearance the committed copy
    does not hold is left as the feed gave it. Returns how many rows were put
    back."""
    from src.pipeline import pitchers
    if not committed_path.exists() or not work_path.exists():
        return 0
    kept = pitchers.read_logs(committed_path)
    logs = pitchers.read_logs(work_path)
    restored = 0
    for person, rows in kept.items():
        # Two outings on one date share an identity: keep them as a LIST and
        # pair the feed's rows with the committed ones in order, so a pair of
        # relief outings is not turned into one outing written twice.
        sealed: dict = {}
        for r in rows:
            if r.get("date") and not r.get("empty") and _in_sealed_window(r["date"]):
                sealed.setdefault(_pitcher_ident(r), []).append(r)
        if not sealed or person not in logs:
            continue
        used: dict = {}
        merged = []
        for row in logs[person]:
            ident = _pitcher_ident(row)
            held = sealed.get(ident)
            n = used.get(ident, 0)
            if row.get("date") and _in_sealed_window(row["date"]) and held and n < len(held):
                used[ident] = n + 1
                if row != held[n]:
                    restored += 1
                merged.append(held[n])
            else:
                merged.append(row)
        logs[person] = merged
    if restored:
        pitchers.write_logs(logs, work_path)
    return restored


def _marker_age_hours(appearances, ctx: _Ctx) -> Optional[float]:
    """Hours since this pitcher's log was last checked (his refresh marker), or
    None when it has no marker. A marker stamped in the future counts as just
    now: a clock that disagrees never makes a log look old."""
    from src.pipeline import pitchers
    marker = pitchers.coverage_marker(appearances, ctx.season)
    stamp = marker.get("checked_utc") if marker else None
    if not stamp:
        return None
    try:
        return max((ctx.now - store_freshness._utc(stamp)).total_seconds() / 3600.0, 0.0)
    except (ValueError, TypeError):
        return None


def _step_pitchers(ctx: _Ctx) -> dict:
    from src.pipeline import history, pitchers
    path = ctx.w("pitcher_logs.jsonl")
    results = history.read_results(ctx.w("mlb_results.csv"))
    existing = pitchers.read_logs(path)
    recent_ids = _starters_to_refresh(results, existing, ctx.season, ctx.today)
    upcoming = _probable_ids_for(
        [(_d(ctx.today) + timedelta(days=i)).isoformat() for i in range(0, 3)], ctx.timeout)
    # An upcoming probable whose log was checked recently and who has no start
    # newer than that check is not asked for again: his season log cannot have
    # changed (he has not pitched). Every build starts from the committed copy,
    # whose markers are up to a day old, so the 12-hour rule alone made each
    # build after the evening re-ask for every probable (about 30 requests a
    # build, many builds a day). He is re-asked after UPCOMING_MAX_AGE_HOURS, or
    # at once if the results show a start of his since the check.
    upcoming_all = len(upcoming)
    upcoming = {pid for pid in upcoming
                if pid in recent_ids or _marker_age_hours(existing.get(pid, []), ctx) is None
                or _marker_age_hours(existing.get(pid, []), ctx) >= UPCOMING_MAX_AGE_HOURS}
    # Upcoming starters first (they decide tonight's pages), then anyone whose
    # log is behind a start. Within each group, never-checked before stale.

    def staleness(pid):
        marker = pitchers.coverage_marker(existing.get(pid, []), ctx.season)
        checked = marker.get("checked_utc") if marker else None
        return (checked is not None, checked or "")

    ordered = sorted(upcoming, key=staleness) + sorted(recent_ids - upcoming, key=staleness)
    processed = failed = 0
    deferred = 0
    for index in range(0, len(ordered), PITCHER_CHUNK):
        if ctx.deadline.expired():
            deferred = len(ordered) - index
            break
        report = pitchers.build_log_store(
            ordered[index:index + PITCHER_CHUNK], ctx.season, path=path,
            resume=True, refresh=True, refresh_after_hours=PITCHER_REFRESH_AFTER_HOURS,
            max_refetch_per_run=PITCHER_MAX_PER_RUN, now=ctx.now,
            timeout=ctx.timeout, game_types=mlb.DECISIVE_GAME_TYPES)
        processed += report["processed"]
        failed += report["failed"]
    # The sealed window's rows stay exactly as committed (see SEALED_FIRST).
    sealed_kept = _keep_sealed_pitcher_rows(ctx.base / "pitcher_logs.jsonl", path) if processed else 0
    return {"candidates": len(ordered), "upcoming_probables": len(upcoming),
            "upcoming_skipped_checked_recently": upcoming_all - len(upcoming),
            "fetched": processed, "failed": failed, "deferred_by_deadline": deferred,
            "sealed_rows_kept": sealed_kept}


def _step_standings(ctx: _Ctx) -> dict:
    from src.pipeline import standings
    path = ctx.w("standings.jsonl")
    # Build only dates a snapshot can exist for: through today while the
    # regular season is on, else through its last game (the Stats API returns
    # an empty table for a postseason date, and asking again every hour for
    # every such date would be a wasted call apiece).
    from src.pipeline import history
    newest_regular = None
    for row in history.read_results(ctx.w("mlb_results.csv")).values():
        if (row.get("game_type") or "R") == "R":
            day_text = str(row.get("date") or "")
            if day_text and (newest_regular is None or day_text > newest_regular):
                newest_regular = day_text
    today = _d(store_freshness.standings_horizon(newest_regular, ctx.today))
    stored = standings._stored_dates(path) if path.exists() else set()
    latest = max((_d(s) for s in stored), default=None)
    start = (latest + timedelta(days=1)) if latest else today
    start = max(start, today - timedelta(days=STANDINGS_MAX_BACKFILL_DAYS))

    # Yesterday's table is only final once yesterday is over. A snapshot taken
    # DURING it holds a part-played day; re-take it if so.
    retaken = 0
    day_start_utc = datetime.combine(_d(ctx.today), datetime.min.time(), tzinfo=timezone.utc) \
        - store_freshness.eastern_offset(ctx.now)
    if ctx.yesterday in stored and path.exists():
        captured = []
        for row in standings._iter_rows(path):
            if row.get("date") == ctx.yesterday and row.get("captured_at"):
                captured.append(str(row["captured_at"]))
        if captured and max(captured) < day_start_utc.isoformat():
            retaken = _drop_standings_day(path, ctx.yesterday)
            start = min(start, _d(ctx.yesterday))

    # The sealed window is never asked for (a snapshot there is an outcome-era
    # record; see SEALED_FIRST).
    first_day = _unsealed_start(start, today)
    built = skipped = failed = 0
    day = first_day
    while day is not None and day <= today:
        if ctx.deadline.expired():
            break
        result = standings.build(day.year, day, path=path, timeout=ctx.timeout)
        if result["error"]:
            failed += 1
        elif result["skipped"]:
            skipped += 1
        else:
            built += 1
        day += timedelta(days=1)
    return {"from": first_day.isoformat() if first_day else None, "to": ctx.today,
            "built": built, "skipped": skipped, "failed": failed,
            "retaken_yesterday_rows": retaken}


def _drop_standings_day(path: Path, day: str) -> int:
    return _rewrite_jsonl_without(path, lambda r: r.get("date") == day)


def _step_splits(ctx: _Ctx) -> dict:
    from src.pipeline import lineups
    ids = _probable_ids_for(
        [(_d(ctx.today) + timedelta(days=i)).isoformat()
         for i in range(0, SPLITS_DAYS_AHEAD + 1)], ctx.timeout)
    fetched = failed = 0
    # A season-to-date split moves only when its pitcher pitches, so a probable
    # whose cached split is under SPLITS_REFRESH_AFTER_HOURS old is not asked
    # for again (every build did, 6 requests of the 19 a steady refresh made).
    cache = lineups.read_splits(ctx.w("pitcher_splits.json"))
    fresh = {pid for pid in ids if _splits_fresh(cache.get(f"{pid}:{ctx.season}"), ctx.now)}
    ordered = sorted(ids - fresh)
    for index in range(0, len(ordered), 10):
        if ctx.deadline.expired():
            break
        report = lineups.refresh_splits(ordered[index:index + 10], ctx.season,
                                        cache_path=ctx.w("pitcher_splits.json"),
                                        timeout=ctx.timeout)
        fetched += report["fetched"]
        failed += report["failed"]
    return {"requested": len(ids), "skipped_fresh": len(fresh), "fetched": fetched,
            "failed": failed}


def _splits_fresh(record, now: datetime) -> bool:
    """True when this cached split was taken within SPLITS_REFRESH_AFTER_HOURS
    of `now`. A missing or unreadable stamp is not fresh."""
    stamp = (record or {}).get("as_of") if isinstance(record, dict) else None
    if not stamp:
        return False
    try:
        age = (now - store_freshness._utc(stamp)).total_seconds()
    except (ValueError, TypeError):
        return False
    return 0 <= age < SPLITS_REFRESH_AFTER_HOURS * 3600.0


def _step_handedness(ctx: _Ctx) -> dict:
    from src.pipeline import lineups
    # Read-only on the lineup store: it is committed hourly by capture and is
    # not this module's to touch.
    cutoff = (_d(ctx.today) - timedelta(days=HANDEDNESS_LINEUP_DAYS)).isoformat()
    path = ctx.base / "lineups.jsonl"
    ids = set()
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict) or str(row.get("date") or "") < cutoff:
                    continue
                for side in ("away", "home"):
                    for slot in row.get(side) or []:
                        if isinstance(slot, dict) and slot.get("person_id"):
                            ids.add(str(slot["person_id"]))
    cache_path = ctx.w("handedness.json")
    have = lineups.read_handedness(cache_path) if cache_path.exists() else {}
    missing = sorted(i for i in ids if i not in have)
    if missing and not ctx.deadline.expired():
        lineups.fetch_handedness(missing, cache_path=cache_path, timeout=ctx.timeout)
    return {"batters_in_recent_lineups": len(ids), "missing_before": len(missing)}


def _step_arsenals(ctx: _Ctx) -> dict:
    from src.providers import statcast
    existing = ctx.w("arsenals", f"pitcher_{ctx.season}.json")
    if existing.exists():
        try:
            as_of = store_freshness._day(json.loads(existing.read_text(encoding="utf-8")).get("as_of"))
        except (OSError, ValueError):
            as_of = None
        if as_of == ctx.today:
            return {"skipped": "already built today"}
    report = statcast.build(ctx.season, store=ctx.w("arsenals"), timeout=ctx.timeout)
    return {"pitcher_rows": report.get("pitcher_rows"), "batter_rows": report.get("batter_rows")}


def _step_transactions(ctx: _Ctx) -> dict:
    from src.pipeline import news
    store = ctx.w("transactions.jsonl")
    newest = None
    if store.exists():
        rows = news.read(store)
        stamps = [str(r.get("filed_date") or r.get("date") or "")[:10] for r in rows]
        stamps = [s for s in stamps if s]
        newest = max(stamps) if stamps else None
    floor = _d(ctx.today) - timedelta(days=TRANSACTIONS_MAX_WINDOW_DAYS)
    start = max(_d(newest) - timedelta(days=2), floor) if newest else _d(ctx.today) - timedelta(days=7)
    start = _unsealed_start(start, _d(ctx.today))
    if start is None:
        return {"from": None, "fetched": 0, "written": 0}
    report = news.ingest(start.isoformat(), ctx.today, store=store)
    return {"from": start.isoformat(), "fetched": report["fetched"], "written": report["written"]}


STEPS: dict = {
    "results": _step_results, "bullpen": _step_bullpen, "pitchers": _step_pitchers,
    "standings": _step_standings, "splits": _step_splits,
    "handedness": _step_handedness, "arsenals": _step_arsenals,
    "transactions": _step_transactions,
}

# step -> [(work-relative file, destination-relative-to-historical, kind)]
# kind: "strict" may not shrink; "pitcher" may shrink by PITCHER_SHRINK_TOLERANCE.
STEP_FILES = {
    "results": [("mlb_results.csv", "mlb_results.csv", "strict"),
                ("mlb_results.manifest.json", "mlb_results.manifest.json", "manifest")],
    "bullpen": [("bullpen_log.jsonl", "bullpen_log.jsonl", "strict")],
    "pitchers": [("pitcher_logs.jsonl", "pitcher_logs.jsonl", "pitcher")],
    "standings": [("standings.jsonl", "standings.jsonl", "strict")],
    "splits": [("pitcher_splits.json", "pitcher_splits.json", "strict")],
    "handedness": [("handedness.json", "handedness.json", "strict")],
    "arsenals": [("arsenals/pitcher_{season}.json", "arsenals/pitcher_{season}.json", "arsenal"),
                 ("arsenals/batter_{season}.json", "arsenals/batter_{season}.json", "arsenal")],
    "transactions": [("transactions.jsonl", "transactions.jsonl", "strict")],
}
# The step inputs each step reads from earlier steps' output, so a step that
# needs the freshly-ingested results sees them even before promotion.
SEED_FILES = [rel for files in STEP_FILES.values() for rel, _, _ in files]


def _validate(path: Path) -> Optional[str]:
    """None if the file parses as what it claims to be; else why not."""
    try:
        if path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))
        elif path.suffix == ".csv":
            import csv
            with path.open(newline="", encoding="utf-8") as handle:
                for _ in csv.DictReader(handle):
                    pass
        elif path.suffix == ".jsonl":
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        try:
                            json.loads(line)
                        except json.JSONDecodeError:
                            pass  # one torn line is tolerated by every reader
    except (OSError, ValueError) as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


# ---------------------------------------------------------------------------
# Per-key promotion: no key may lose a row
# ---------------------------------------------------------------------------
#
# "The copy has not shrunk" compares TOTALS, and a total hides a loss: an empty
# answer from the API for ONE pitcher replaces his whole season with an empty
# marker (`pitchers.build_log_store` replaces every row a successful fetch
# covers), and the store still grows overall because other pitchers gained
# rows. The same shape exists for the one date the bullpen and standings steps
# re-fetch whole. So a copy is checked KEY BY KEY against the committed one
# before it is promoted: a key is a pitcher-season, a date, a game or a player
# as the store defines it, and a key LOSES a row when the committed copy has a
# record under it that the refreshed copy does not.
#
# For a key that would lose rows the promoted copy holds the UNION of the two:
# every committed record under that key, plus whatever the refresh added there.
# (Not "the committed rows instead": a pitcher whose refreshed answer is missing
# one old start still gets his new starts.) What a record IS, per store, is
# `ident`: bookkeeping markers are not records and are never "lost" -- an
# empty-day marker next to real rows would say the day had no games, and a
# refresh marker on an empty answer would say a pitcher had just been checked.
# An answer that carried records writes its own marker; an answer that carried
# none never replaces the committed one, so the next run asks again.
#
# The repair is made on the WORK copy (which a later step may still read) and
# the committed file is only ever read. What was kept is reported
# (`kept_committed`) and logged. The Savant arsenal leaderboards are the one
# exception to the union: their rows are shares of one whole snapshot, so a
# union of two snapshots would double-count; a player who lost rows keeps the
# committed rows instead.

MAX_KEPT_EXAMPLES = 5


def _write_text_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".repair.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _read_jsonl_pairs(path: Path, key_fn, ident, is_marker):
    """([(line, key)] in file order, {key: [(line, identity, is_marker)]}). A
    line that does not parse, or has no key, is carried with key None. The
    parsed row is dropped at once: only the line and its identity are kept, so
    the bullpen log (60,000 rows) costs its text, not its dicts."""
    sequence, groups = [], {}
    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            text = raw.strip()
            if not text:
                continue
            line = raw if raw.endswith("\n") else raw + "\n"
            try:
                row = json.loads(text)
            except json.JSONDecodeError:
                row = None
            key = key_fn(row) if isinstance(row, dict) else None
            sequence.append((line, key))
            if key is not None:
                groups.setdefault(key, []).append((line, ident(row), is_marker(row)))
    return sequence, groups


def _union_for_key(committed, refreshed):
    """(triples, restored_count): the union for one key, markers per the rules
    in the section comment above. `restored_count` is how many committed
    records the refreshed copy was missing."""
    fresh = [t for t in refreshed if not t[2]]
    fresh_count: dict = {}
    fresh_lines: dict = {}
    for t in fresh:
        fresh_count[t[1]] = fresh_count.get(t[1], 0) + 1
        fresh_lines.setdefault(t[1], []).append(t[0].strip())
    by_ident: dict = {}
    for t in committed:
        if not t[2]:
            by_ident.setdefault(t[1], []).append(t)
    extra = []
    for ident, group in by_ident.items():
        if len(group) <= fresh_count.get(ident, 0):
            continue
        # Identity is a MULTISET (a pitcher's two relief outings on one date
        # share one). Committed lines the refresh holds verbatim are matched
        # away; of the rest, the first `len(pool)` pair off, in file order, with
        # the refresh's remaining lines as one record CORRECTED by the refresh;
        # only the committed records beyond the refreshed count are put back.
        pool = list(fresh_lines.get(ident, ()))
        unmatched = []
        for t in group:
            if t[0].strip() in pool:
                pool.remove(t[0].strip())
            else:
                unmatched.append(t)
        extra.extend(unmatched[len(pool):])
    markers_fresh = [t for t in refreshed if t[2]]
    markers_committed = [t for t in committed if t[2]]
    if fresh:
        markers = markers_fresh
    elif extra:
        markers = markers_committed
    else:
        markers = markers_fresh or markers_committed
    return fresh + extra + markers, len(extra)


def _ident_counts(triples) -> dict:
    """{identity: how many records} over the non-marker triples."""
    out: dict = {}
    for t in triples:
        if not t[2]:
            out[t[1]] = out.get(t[1], 0) + 1
    return out


def _restore_jsonl(work: Path, committed: Path, key_fn, ident, is_marker) -> Optional[dict]:
    work_sequence, work_groups = _read_jsonl_pairs(work, key_fn, ident, is_marker)
    _, committed_groups = _read_jsonl_pairs(committed, key_fn, ident, is_marker)
    lost = []
    for key, triples in committed_groups.items():
        after = _ident_counts(work_groups.get(key, ()))
        if any(n > after.get(i, 0) for i, n in _ident_counts(triples).items()):
            lost.append(key)
    if not lost:
        return None
    lost_set, restored = set(lost), 0
    lines = [line for line, key in work_sequence if key not in lost_set]
    for key in lost:
        triples, count = _union_for_key(committed_groups[key], work_groups.get(key, []))
        lines.extend(t[0] for t in triples)
        restored += count
    _write_text_atomic(work, "".join(lines))
    return {"keys": [str(k) for k in lost], "rows": restored}


def _pitcher_key(row):
    person = row.get("person_id")
    if person is None:
        return None
    return f"{person}:{row.get('season') or str(row.get('date') or '')[:4]}"


def _pitcher_ident(row):
    """One appearance: the date, and whether he started (a start and a relief
    outing on one date are two records). Never raises on a malformed field."""
    try:
        started = int(row.get("games_started") or 0)
    except (TypeError, ValueError):
        started = 0
    return (str(row.get("date")), started)


def _pitcher_marker(row) -> bool:
    return row.get("date") is None


def _restore_pitchers(work: Path, committed: Path) -> Optional[dict]:
    from src.pipeline import pitchers
    report = _restore_jsonl(work, committed, _pitcher_key, _pitcher_ident, _pitcher_marker)
    if report:
        # Back to the canonical layout (grouped by pitcher, by date within):
        # the repair appended the restored keys at the end of the file.
        pitchers.write_logs(pitchers.read_logs(work), work)
    return report


def _bullpen_key(row):
    return str(row["date"]) if row.get("date") else None


def _bullpen_ident(row):
    return (str(row.get("game_pk")), str(row.get("person_id")))


def _bullpen_marker(row) -> bool:
    return bool(row.get("empty")) or row.get("person_id") is None


def _standings_key(row):
    return str(row["date"]) if row.get("date") else None


def _standings_ident(row):
    return str(row.get("team_abbrev") or row.get("team_id"))


def _transactions_key(row):
    day = str(row.get("filed_date") or row.get("date") or "")[:10]
    return day or None


def _never_a_marker(row) -> bool:
    return False


def _restore_results(work: Path, committed: Path) -> Optional[dict]:
    from src.pipeline import history
    held, kept = history.read_results(work), history.read_results(committed)
    lost = [pk for pk in kept if pk not in held]
    if not lost:
        return None
    for pk in lost:
        held[pk] = kept[pk]
    history.write_results(held, work)
    return {"keys": lost, "rows": len(lost)}


def _restore_dict(work: Path, committed: Path, wrap: Optional[str]) -> Optional[dict]:
    """A JSON object keyed by pitcher, player or date. `wrap` names the one
    inner object when the keys live under a field (the results manifest's
    `dates`)."""
    def load(path):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path.name} is not an object")
        inner = data[wrap] if wrap and isinstance(data.get(wrap), dict) else data
        return data, inner

    data, held = load(work)
    _, kept = load(committed)
    lost = [k for k in kept if k not in held]
    if not lost:
        return None
    for key in lost:
        held[key] = kept[key]
    _write_text_atomic(work, json.dumps(data, indent=1, sort_keys=True))
    return {"keys": [str(k) for k in lost], "rows": len(lost)}


def _restore_arsenal(work: Path, committed: Path) -> Optional[dict]:
    def load(path):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
            raise ValueError(f"{path.name} has no rows")
        return data

    def by_player(rows):
        out = {}
        for row in rows:
            out.setdefault(str(row.get("player_id")), []).append(row)
        return out

    data, kept = load(work), load(committed)
    held_by, kept_by = by_player(data["rows"]), by_player(kept["rows"])
    lost = []
    for player, rows in kept_by.items():
        before: dict = {}
        for r in rows:
            before[str(r.get("pitch_type"))] = before.get(str(r.get("pitch_type")), 0) + 1
        after: dict = {}
        for r in held_by.get(player, ()):
            after[str(r.get("pitch_type"))] = after.get(str(r.get("pitch_type")), 0) + 1
        if any(n > after.get(t, 0) for t, n in before.items()):
            lost.append(player)
    if not lost:
        return None
    lost_set = set(lost)
    data["rows"] = ([r for r in data["rows"] if str(r.get("player_id")) not in lost_set]
                    + [r for p in lost for r in kept_by[p]])
    _write_text_atomic(work, json.dumps(data, sort_keys=True))
    return {"keys": lost, "rows": sum(len(kept_by[p]) for p in lost)}


# destination file name -> repair(work, committed) -> None | {"keys", "rows"}
KEYED_STORES: dict = {
    "pitcher_logs.jsonl": _restore_pitchers,
    "bullpen_log.jsonl": lambda w, c: _restore_jsonl(
        w, c, _bullpen_key, _bullpen_ident, _bullpen_marker),
    "standings.jsonl": lambda w, c: _restore_jsonl(
        w, c, _standings_key, _standings_ident, _never_a_marker),
    "transactions.jsonl": lambda w, c: _restore_jsonl(
        w, c, _transactions_key, lambda r: str(r.get("transaction_id")), _never_a_marker),
    "mlb_results.csv": _restore_results,
    "mlb_results.manifest.json": lambda w, c: _restore_dict(w, c, "dates"),
    "pitcher_splits.json": lambda w, c: _restore_dict(w, c, None),
    "handedness.json": lambda w, c: _restore_dict(w, c, None),
}


# ---------------------------------------------------------------------------
# What a refresh actually changed: new, corrected, unchanged
# ---------------------------------------------------------------------------
#
# "The file differs" says nothing a reader can act on. A refresh that re-asks
# the provider for rows it already holds meets three different things, and the
# report keeps them apart (2026-10-04):
#
#   new        a record the committed copy does not hold
#   corrected  a record the committed copy holds, with different content (the
#              provider revised it: a scorer's change, a late stat correction)
#   unchanged  a record the committed copy holds, identical
#
# Fields that are the refresh's own bookkeeping (when it looked, when the
# snapshot was taken) are not content: a re-taken standings row that differs
# only in `captured_at` is unchanged, not a correction. Missing source data (the
# provider answered with nothing) and a failed fetch are NOT row facts; they are
# counted per request by `refresh_fetch.FetchLayer`.

VOLATILE_FIELDS = frozenset({"as_of", "checked_utc", "captured_at", "fetched_utc"})

# store file name -> (key_fn, ident, is_marker) for the line-per-record stores
JSONL_SPECS: dict = {
    "pitcher_logs.jsonl": (_pitcher_key, _pitcher_ident, _pitcher_marker),
    "bullpen_log.jsonl": (_bullpen_key, _bullpen_ident, _bullpen_marker),
    "standings.jsonl": (_standings_key, _standings_ident, _never_a_marker),
    "transactions.jsonl": (_transactions_key, lambda r: str(r.get("transaction_id")),
                           _never_a_marker),
}


def _stable_text(value) -> str:
    """Canonical text of a record with the refresh's bookkeeping removed."""
    if isinstance(value, dict):
        value = {k: v for k, v in value.items() if k not in VOLATILE_FIELDS}
    return json.dumps(value, sort_keys=True, default=str)


def _diff_counts(old: dict, new: dict) -> dict:
    """{identity: stable text} against {identity: stable text}."""
    out = {"new": 0, "corrected": 0, "unchanged": 0}
    for ident, text in new.items():
        if ident not in old:
            out["new"] += 1
        elif old[ident] == text:
            out["unchanged"] += 1
        else:
            out["corrected"] += 1
    return out


def _jsonl_records(path: Path, key_fn, ident, is_marker) -> dict:
    out: dict = {}
    seen: dict = {}
    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            text = raw.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict) or is_marker(row):
                continue
            key = key_fn(row)
            if key is not None:
                # the Nth record that shares an identity is its own record
                n = seen.get((key, ident(row)), 0)
                seen[(key, ident(row))] = n + 1
                out[(key, ident(row), n)] = _stable_text(row)
    return out


def _json_records(path: Path, wrap: Optional[str]) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if wrap and isinstance(data, dict) and isinstance(data.get(wrap), dict):
        data = data[wrap]
    if isinstance(data, dict) and isinstance(data.get("rows"), list):    # an arsenal leaderboard
        return {(str(r.get("player_id")), str(r.get("pitch_type"))): _stable_text(r)
                for r in data["rows"] if isinstance(r, dict)}
    if not isinstance(data, dict):
        return {}
    return {str(k): _stable_text(v) for k, v in data.items()}


def row_diff(dest_name: str, work: Path, committed: Path) -> Optional[dict]:
    """new / corrected / unchanged for one store, `work` against `committed`.
    None when the pair cannot be compared (a file kind it does not know); never
    raises."""
    try:
        if dest_name in JSONL_SPECS:
            spec = JSONL_SPECS[dest_name]
            return _diff_counts(_jsonl_records(committed, *spec), _jsonl_records(work, *spec))
        if dest_name == "mlb_results.csv":
            from src.pipeline import history
            old, new = history.read_results(committed), history.read_results(work)
            return _diff_counts({k: _stable_text(v) for k, v in old.items()},
                                {k: _stable_text(v) for k, v in new.items()})
        if dest_name.endswith(".json"):
            wrap = "dates" if dest_name == "mlb_results.manifest.json" else None
            return _diff_counts(_json_records(committed, wrap), _json_records(work, wrap))
    except Exception:  # noqa: BLE001 -- a report line, never a reason to fail a refresh
        return None
    return None


def _keyed_repair(dest: Path):
    """The repair for this destination, or None. The arsenal leaderboards are
    named by season (`arsenals/pitcher_2026.json`), so they match on their
    directory."""
    found = KEYED_STORES.get(dest.name)
    if found is None and dest.parent.name == "arsenals" and dest.suffix == ".json":
        found = _restore_arsenal
    return found


def _promote(work_file: Path, dest: Path, kind: str) -> dict:
    """Move one finished copy over its original if it is sound and not worse.

    "Not worse" is checked per key first (no key may lose a record; see the
    section above) and by total second."""
    if not work_file.exists():
        return {"file": dest.name, "promoted": False, "reason": "step produced no file"}
    problem = _validate(work_file)
    if problem:
        return {"file": dest.name, "promoted": False, "reason": f"copy does not parse: {problem}"}
    if _sha(work_file) == _sha(dest):
        return {"file": dest.name, "promoted": False, "reason": "unchanged"}
    kept_committed = None
    repair = _keyed_repair(dest)
    if repair is not None and dest.exists() and _validate(dest) is None:
        try:
            kept_committed = repair(work_file, dest)
        except Exception as exc:  # noqa: BLE001 -- a copy that cannot be checked is not promoted
            return {"file": dest.name, "promoted": False,
                    "reason": (f"could not check the copy against the committed one "
                               f"({type(exc).__name__}: {exc}); kept the committed copy")}
        if kept_committed is not None and _sha(work_file) == _sha(dest):
            return {"file": dest.name, "promoted": False, "reason": "unchanged",
                    "kept_committed": _kept_summary(kept_committed)}
    before, after = _rows(dest), _rows(work_file)
    if before is not None and after is not None and kind != "manifest":
        floor = before * (1.0 - PITCHER_SHRINK_TOLERANCE) if kind == "pitcher" else before
        if after < floor:
            return {"file": dest.name, "promoted": False, "rows_before": before, "rows_after": after,
                    "reason": "copy has fewer rows than the committed one; kept the committed copy"}
    diff = row_diff(dest.name, work_file, dest) if dest.exists() else None
    _atomic_replace(work_file, dest)
    out = {"file": dest.name, "promoted": True, "rows_before": before, "rows_after": after}
    if diff is not None:
        out["diff"] = diff
    if kept_committed is not None:
        out["kept_committed"] = _kept_summary(kept_committed)
    return out


def _kept_summary(found: dict) -> dict:
    keys = found["keys"]
    return {"keys": len(keys), "rows": found["rows"], "examples": keys[:MAX_KEPT_EXAMPLES]}


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

def refresh(root=None, *, now=None, max_seconds: float = DEFAULT_MAX_SECONDS,
            only=None, timeout: int = FETCH_TIMEOUT_S,
            clock: Callable[[], float] = time.monotonic,
            log: Optional[Callable[[str], None]] = None,
            fetch: Optional[refresh_fetch.FetchLayer] = None) -> dict:
    """Catch the stores up. `root` is a data root (default: the project's).
    Returns a report; never raises for a network or data problem.

    Every upstream request goes through one `refresh_fetch.FetchLayer`
    (counted, reused, boundedly retried, halted on a 401/403); its summary is
    `report["fetch"]` and each step's own is `report["steps"][name]["fetch"]`.
    `fetch` is injectable so a test controls the sleeps and the cache."""
    data_root = Path(root) if root is not None else paths.data_root()
    layer = fetch if fetch is not None else refresh_fetch.FetchLayer(
        cache_dir=data_root / "raw" / "mlb_statsapi_cache")
    # A retry sleep may not run past the run's own budget: the run stops itself
    # before --max-seconds instead of being killed by the loop's `timeout`.
    run_deadline = Deadline(max_seconds, clock)
    layer.bind_remaining(run_deadline.remaining)
    with layer.install():
        return _refresh(data_root, layer, now=now, max_seconds=max_seconds, only=only,
                        timeout=timeout, clock=clock, log=log)


def _refresh(data_root: Path, layer: refresh_fetch.FetchLayer, *, now, max_seconds: float,
             only, timeout: int, clock: Callable[[], float],
             log: Optional[Callable[[str], None]]) -> dict:
    log = log or (lambda text: print(text, flush=True))
    moment = store_freshness._utc(now)
    today = store_freshness.baseball_date(moment)
    base = data_root / "historical"
    wanted = [s for s in STEP_ORDER if only is None or s in set(only)]
    started = clock()
    report: dict = {"started_utc": moment.isoformat(), "baseball_date": today,
                    "steps": {}, "promoted": [], "kept": [], "restored": [],
                    "skipped_reason": None}

    before = store_freshness.report(data_root, moment)
    report["before"] = _summary(before)
    log(f"display refresh: baseball date {today}; core stores through "
        + ", ".join(f"{n}={before['stores'][n]['through']}" for n in store_freshness.CORE_STORES))

    # One cheap call first. An unreachable API must cost seconds, not the budget.
    try:
        mlb.fetch_schedule(today, timeout=PROBE_TIMEOUT_S)
    except mlb.MLBError as exc:
        report["skipped_reason"] = (f"MLB Stats API refused: {layer.halted}" if layer.halted
                                    else f"MLB Stats API unreachable: {exc}")
        report["after"] = report["before"]
        report["fetch"] = layer.summary()
        report["halted"] = layer.halted
        report["elapsed_s"] = round(clock() - started, 2)
        log(f"display refresh: skipped ({report['skipped_reason']}); stores unchanged")
        return report

    work = data_root / ".refresh_work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    season = today[:4]
    try:
        for rel in SEED_FILES:
            rel = rel.replace("{season}", season)
            source = base / rel
            if source.exists():
                (work / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, work / rel)

        deadline = Deadline(max_seconds, clock)
        remaining_weight = sum(STEP_WEIGHT[s] for s in wanted)
        for name in wanted:
            step_deadline = deadline.slice(STEP_WEIGHT[name], remaining_weight)
            remaining_weight -= STEP_WEIGHT[name]
            ctx = _Ctx(work, base, moment, today, step_deadline, timeout)
            step_start = clock()
            mark = layer.mark()
            entry: dict = {}
            try:
                if layer.halted:
                    # A 401/403 (or a run of hard failures) stopped the run:
                    # no step may start another request.
                    entry = {"status": "skipped", "reason": f"halted: {layer.halted}"}
                elif deadline.expired():
                    entry = {"status": "skipped", "reason": "budget exhausted"}
                else:
                    detail = STEPS[name](ctx)
                    entry = {"status": "ok", **detail}
            except Exception as exc:  # noqa: BLE001 -- fail soft: one step's fault is one line
                entry = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
            entry["seconds"] = round(clock() - step_start, 2)

            promotions = []
            # Only a step that RETURNED is promoted (a deadline hit mid-step
            # returns, with its progress). A step that raised may have left a
            # half-rewritten copy (pitchers.write_logs truncates and rewrites)
            # that still parses and sits inside the shrink tolerance.
            if entry["status"] == "ok":
                for rel, dest_rel, kind in STEP_FILES[name]:
                    rel, dest_rel = rel.replace("{season}", season), dest_rel.replace("{season}", season)
                    if kind == "manifest" and promotions and not promotions[-1]["promoted"] \
                            and promotions[-1]["reason"] != "unchanged":
                        # The manifest is the results store's coverage record.
                        # Promoted without its CSV it claims dates whose games
                        # the store does not hold: /health calls the store
                        # current and resume never fetches those dates again.
                        promotions.append({"file": Path(dest_rel).name, "promoted": False,
                                           "reason": "its results copy was not promoted; "
                                                     "kept the committed copy"})
                        continue
                    promotions.append(_promote(work / rel, base / dest_rel, kind))
            entry["files"] = promotions
            entry["fetch"] = _compact_fetch(layer.summary(mark))
            entry["observation"] = _observation(entry, promotions)
            for p in promotions:
                (report["promoted"] if p["promoted"] else report["kept"]).append(
                    {"step": name, **p})
                if p.get("kept_committed"):
                    # A key that would have lost records kept them. Say so: a
                    # refresh that quietly rewrote a pitcher's season is the
                    # failure this exists to make visible.
                    found = p["kept_committed"]
                    report["restored"].append({"step": name, "file": p["file"], **found})
                    log(f"  {name:<12} kept committed records for {found['keys']} key(s) "
                        f"in {p['file']} ({found['rows']} record(s)): "
                        + ", ".join(found["examples"]))
            report["steps"][name] = entry
            log(f"  {name:<12} {entry['status']:<7} {entry['seconds']:>6.1f}s  "
                + ", ".join(f"{p['file']}:{'PROMOTED' if p['promoted'] else p['reason']}" for p in promotions))
    finally:
        shutil.rmtree(work, ignore_errors=True)

    after = store_freshness.report(data_root, moment)
    report["after"] = _summary(after)
    report["fetch"] = layer.summary()
    report["halted"] = layer.halted
    report["elapsed_s"] = round(clock() - started, 2)
    fetch = report["fetch"]
    log(f"display refresh: {fetch['requests_made']} request(s) made, {fetch['reused']} reused, "
        f"{fetch['failed']} failed, {fetch['missing_source_data']} empty answer(s)"
        + (f"; HALTED: {layer.halted}" if layer.halted else ""))
    log("display refresh: through " + ", ".join(
        f"{n}={after['stores'][n]['through']}" for n in store_freshness.CORE_STORES)
        + (f"; still stale: {', '.join(after['core_stale'])}" if after["core_stale"] else "; core stores current"))
    return report


def _compact_fetch(summary: dict) -> dict:
    """The per-step slice of the fetch summary (the run-level one keeps the
    per-class table)."""
    return {k: summary[k] for k in ("calls", "network_calls", "reused", "failed", "retries",
                                    "requests_made", "missing_source_data", "outcomes")}


def _observation(entry: dict, promotions: list) -> dict:
    """What this step found, in the four kinds a reader must not confuse.

    new / corrected / unchanged are record counts, from the diff against the
    committed copy (only for a promoted file: an unchanged or refused file
    changed nothing). missing_source counts requests the provider answered with
    nothing; failed counts requests that did not get an answer. `verdict` is the
    one word for the step."""
    new = sum((p.get("diff") or {}).get("new", 0) for p in promotions)
    corrected = sum((p.get("diff") or {}).get("corrected", 0) for p in promotions)
    unchanged = sum((p.get("diff") or {}).get("unchanged", 0) for p in promotions)
    fetch = entry.get("fetch") or {}
    failed = fetch.get("failed", 0)
    missing = fetch.get("missing_source_data", 0)
    if entry.get("status") == "skipped":
        verdict = "skipped"
    elif entry.get("status") == "failed":
        verdict = "failed"
    elif failed and not (new or corrected):
        verdict = "failed"
    elif failed:
        verdict = "partial"
    elif corrected:
        verdict = "corrected"
    elif new:
        verdict = "updated"
    elif missing:
        verdict = "missing_source_data"
    else:
        verdict = "unchanged"
    return {"new": new, "corrected": corrected, "unchanged": unchanged,
            "missing_source": missing, "failed": failed, "verdict": verdict}


def _summary(freshness: dict) -> dict:
    return {"expected_through": freshness["expected_through"],
            "core_stale": freshness["core_stale"], "stale": freshness["stale"],
            "through": {n: e["through"] for n, e in freshness["stores"].items()}}


# ---------------------------------------------------------------------------
# The container guard
# ---------------------------------------------------------------------------

_GUARD_STATUS: dict = {"enabled": False, "interval_s": None, "runs": 0, "busy_skips": 0,
                       "last_attempt_utc": None, "last_exit": None,
                       "last_result": None, "next_check_utc": None}
_GUARD_LOCK = threading.Lock()


def guard_status() -> dict:
    with _GUARD_LOCK:
        return dict(_GUARD_STATUS)


def _set_status(**fields) -> None:
    with _GUARD_LOCK:
        _GUARD_STATUS.update(fields)


def guard_interval_seconds(env=None) -> float:
    """0 (the default, so tests and a laptop never start one) disables it."""
    raw = (env if env is not None else os.environ).get(ENV_GUARD_INTERVAL)
    try:
        return max(float(raw), 0.0) if raw not in (None, "") else 0.0
    except ValueError:
        return 0.0


def _run_child(root=None, *, seconds: float = GUARD_CHILD_SECONDS,
               memory_mb: int = GUARD_CHILD_MEMORY_MB, runner=subprocess.run) -> dict:
    """The refresh in a child process: its memory is its own and capped, and a
    hang is killed at the wall clock. Never raises."""
    cmd = [sys.executable, "-m", "src.pipeline.display_refresh",
           "--max-seconds", str(int(seconds)), "--max-memory-mb", str(int(memory_mb)),
           "--oom-score-adj", str(OOM_SCORE_ADJ)]
    if root is not None:
        cmd += ["--root", str(root)]
    try:
        done = runner(cmd, capture_output=True, text=True, timeout=seconds + 60,
                      cwd=str(paths.repo_root()))
    except subprocess.TimeoutExpired:
        return {"exit": None, "result": "timed out and was killed"}
    except Exception as exc:  # noqa: BLE001
        return {"exit": None, "result": f"could not start: {type(exc).__name__}: {exc}"}
    tail = (done.stdout or "").strip().splitlines()[-1:] or [""]
    return {"exit": done.returncode, "result": tail[0][:300]}


def guard_tick(*, now=None, root=None, last_run_at: Optional[float] = None,
               clock: Callable[[], float] = time.monotonic,
               child: Callable[..., dict] = _run_child,
               busy: Optional[Callable[[], Optional[str]]] = None) -> dict:
    """One check: refresh in a child only if a core store is stale, the last
    run is not too recent and nothing heavy is running. Returns what it decided
    (also kept in guard_status).

    `busy()` answers why the machine is occupied (a string) or None. It is only
    asked when a refresh would otherwise start. A busy tick is SKIPPED, not
    waited out: nothing here blocks on the build, the decision comes back at
    once with `busy: True` and the caller asks again soon (`GUARD_BUSY_RETRY_S`).
    Why: the cache warm-up repeats every 600 s and a page cache rebuilds in the
    background, each one's peak (about 540 MB) on a 1 GB machine; the refresh
    child is another few hundred."""
    freshness = store_freshness.report(root, now)
    stale = freshness["core_stale"]
    if not stale:
        decision = {"ran": False, "reason": "core stores current", "core_stale": []}
    elif last_run_at is not None and clock() - last_run_at < GUARD_MIN_GAP_S:
        decision = {"ran": False, "reason": "refreshed recently; waiting", "core_stale": stale}
    else:
        why = busy() if busy is not None else None
        if why:
            decision = {"ran": False, "busy": True, "core_stale": stale,
                        "reason": f"skipped this cycle: {why}"}
        else:
            outcome = child(root)
            decision = {"ran": True, "core_stale": stale, **outcome}
    return decision


def start_background_guard(*, ready: Optional[Callable[[], bool]] = None,
                           env=None, root=None, stop_event: Optional[threading.Event] = None,
                           child: Callable[..., dict] = _run_child,
                           sleep: Callable[[float], bool] = None,
                           busy: Optional[Callable[[], Optional[str]]] = None
                           ) -> Optional[threading.Thread]:
    """Start the one daemon thread that keeps a long-lived container current.

    Disabled (returns None, starts nothing) unless
    DISPLAY_REFRESH_GUARD_INTERVAL_SECONDS > 0. Waits `ready()` (the app's
    first warm-up pass) so a refresh never competes with the first warm-up for
    the 1 GB machine, then every interval runs `guard_tick`. The refresh itself
    is a child process (see `_run_child`); this thread only decides and waits.

    `busy()` covers every pass after the first: the warm-up repeats every 600 s
    and page caches rebuild in the background, so a tick that finds one running
    is skipped (never blocked on) and asked again in `GUARD_BUSY_RETRY_S`
    instead of an interval later. `api/app.py` passes the warm-up's own status
    and `src.appstate.freshness`'s one-build-at-a-time counter.
    """
    interval = guard_interval_seconds(env)
    if interval <= 0:
        return None
    environ = env if env is not None else os.environ
    try:
        delay = float(environ.get(ENV_GUARD_DELAY) or DEFAULT_GUARD_DELAY_S)
    except ValueError:
        delay = DEFAULT_GUARD_DELAY_S
    event = stop_event if stop_event is not None else threading.Event()
    wait = sleep if sleep is not None else event.wait

    def loop():
        waited = 0.0
        while ready is not None and not ready() and waited < 600.0:
            if wait(5.0):
                return
            waited += 5.0
        if wait(delay):
            return
        last_run_at = None
        while True:
            pause = interval
            try:
                decision = guard_tick(root=root, last_run_at=last_run_at, child=child, busy=busy)
                now_iso = datetime.now(timezone.utc).isoformat()
                if decision["ran"]:
                    last_run_at = time.monotonic()
                    with _GUARD_LOCK:
                        _GUARD_STATUS["runs"] += 1
                    _set_status(last_attempt_utc=now_iso, last_exit=decision.get("exit"),
                                last_result=decision.get("result"))
                else:
                    if decision.get("busy"):
                        # Skipped, not blocked on: ask again soon, not an hour on.
                        pause = min(interval, GUARD_BUSY_RETRY_S)
                        with _GUARD_LOCK:
                            _GUARD_STATUS["busy_skips"] += 1
                    _set_status(last_result=decision["reason"])
            except Exception as exc:  # noqa: BLE001 -- a guard must never take the app down
                _set_status(last_result=f"guard error: {type(exc).__name__}: {exc}")
            _set_status(next_check_utc=(datetime.now(timezone.utc)
                                        + timedelta(seconds=pause)).isoformat())
            if wait(pause):
                return

    _set_status(enabled=True, interval_s=interval)
    thread = threading.Thread(target=loop, daemon=True, name="display-refresh-guard")
    thread.start()
    return thread


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cap_memory(megabytes: int) -> Optional[str]:
    """Cap this process's address space so a runaway read dies as a MemoryError
    (one step fails soft) instead of taking the machine. Linux only; a platform
    without `resource` runs uncapped and says so."""
    try:
        import resource
    except ImportError:
        return "no resource module on this platform; memory uncapped"
    limit = int(megabytes) * 1024 * 1024
    try:
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ValueError, OSError) as exc:
        return f"could not cap memory: {exc}"
    return None


def _write_proc_file(path: str, text: str) -> None:
    with open(path, "w", encoding="ascii") as handle:
        handle.write(text)


def raise_oom_priority(value: int = OOM_SCORE_ADJ, *, platform: Optional[str] = None,
                       writer: Optional[Callable[[str, str], None]] = None,
                       path: str = OOM_SCORE_PATH) -> Optional[str]:
    """Make THIS process the kernel's first choice to kill when memory truly
    runs out, so on the 1 GB machine the refresh child dies and the web server
    does not. Writes `value` (default 1000, the maximum) to
    `/proc/self/oom_score_adj`; raising your own score needs no privilege.

    Linux only. On any other platform it does nothing and returns None. A write
    that fails (a read-only /proc, a sandbox) returns a note and never raises:
    the refresh is a convenience and must never fail to start over this.
    `platform` and `writer` are injectable so the call path is testable on a
    machine with no /proc."""
    if not (platform if platform is not None else sys.platform).startswith("linux"):
        return None
    try:
        (writer or _write_proc_file)(path, str(int(value)))
    except (OSError, ValueError) as exc:
        return f"could not raise oom_score_adj: {exc}"
    return None


def main(argv=None, *, oom: Optional[Callable[..., Optional[str]]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", default=None, help="data root (default: the project's data/)")
    parser.add_argument("--max-seconds", type=float, default=DEFAULT_MAX_SECONDS)
    parser.add_argument("--only", default=None,
                        help="comma-separated steps: " + ",".join(STEP_ORDER))
    parser.add_argument("--max-memory-mb", type=int, default=0,
                        help="cap this process's address space (Linux)")
    parser.add_argument("--oom-score-adj", type=int, default=None,
                        help="raise this process's oom_score_adj so the kernel kills it "
                             "before the web server (Linux)")
    parser.add_argument("--json", default=None, help="also write the report here")
    parser.add_argument("--check", action="store_true",
                        help="print the freshness report and stop; fetch nothing")
    args = parser.parse_args(argv)

    if args.oom_score_adj is not None:
        note = (oom or raise_oom_priority)(args.oom_score_adj)
        if note:
            print(f"display refresh: {note}", flush=True)
    if args.check:
        data = store_freshness.report(args.root)
        print(json.dumps(data, indent=1, sort_keys=True))
        return 0
    if args.max_memory_mb:
        note = _cap_memory(args.max_memory_mb)
        if note:
            print(f"display refresh: {note}", flush=True)
    only = [s.strip() for s in args.only.split(",")] if args.only else None
    if only:
        unknown = [s for s in only if s not in STEPS]
        if unknown:
            print(f"unknown step(s): {', '.join(unknown)}", file=sys.stderr)
            return 2
    try:
        report = refresh(args.root, max_seconds=args.max_seconds, only=only)
    except Exception as exc:  # noqa: BLE001 -- the build and the guard must never fail on this
        print(f"display refresh: failed softly ({type(exc).__name__}: {exc}); stores unchanged", flush=True)
        return 0
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
