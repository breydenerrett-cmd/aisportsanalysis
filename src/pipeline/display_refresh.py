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
  bullpen_log    missing dates, and yesterday re-fetched whole (a game that was
                 still in progress at the last fetch is otherwise lost)
  pitcher_logs   starters in the last 21 days of results plus today's and
                 tomorrow's probables, postseason starts included
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

NEVER A WORSE STORE THAN THE ONE IT STARTED WITH
------------------------------------------------
Every step works on a COPY in `<data>/.refresh_work/`. A copy is promoted over
the original (`os.replace`, atomic) only if it parses and has not shrunk; any
failure -- network down, deadline hit mid-step, a corrupt write -- leaves the
committed copy exactly as it was ("fail soft to the committed copy"). A
deadline hit mid-step promotes the progress made so far if it is sound: a
partial catch-up is better than none, and every step resumes from its own
coverage record next time.

BOUNDED: a wall-clock budget (default 270 s) divided across the steps by
weight, with unused time rolling forward; a one-call reachability probe up
front so an unreachable API costs seconds, not the budget; fetch timeouts of
10 s; the whole run holds one store in memory at a time (the largest, the
bullpen log, parses to roughly 100 MB). The container guard additionally caps
the child's address space.

ZERO ODDS CREDITS. Every call here is MLB's free keyless Stats API or Baseball
Savant's free leaderboard CSV; nothing imports `src.providers.odds`.
Nothing here touches data/watch, data/processed, evidence, any odds store, any
card file, or any outcome of the sealed 2026-01-01..08-27 window: those
paths are never opened.

CLI:  python -m src.pipeline.display_refresh [--root DIR] [--max-seconds N]
          [--only results,bullpen,...] [--max-memory-mb N] [--json PATH]
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
from src.pipeline import store_freshness
from src.providers import mlb

DEFAULT_MAX_SECONDS = 270.0
FETCH_TIMEOUT_S = 10
PROBE_TIMEOUT_S = 8

RESULTS_LOOKBACK_DAYS = 14        # always re-check this far back (scope + late finals)
RESULTS_CHUNK_DAYS = 5
BULLPEN_WINDOW_DAYS = 75          # fill any missing date this far back. The committed
                                  # copy never advances, so every build re-does the gap
                                  # since it; ~3 s per game day, bounded by the budget
BULLPEN_CHUNK_DAYS = 4
PITCHER_ACTIVE_DAYS = 21          # a starter who started within this window is refreshed
PITCHER_CHUNK = 30
PITCHER_REFRESH_AFTER_HOURS = 12.0
PITCHER_MAX_PER_RUN = 400
STANDINGS_MAX_BACKFILL_DAYS = 45
TRANSACTIONS_MAX_WINDOW_DAYS = 30
HANDEDNESS_LINEUP_DAYS = 7
SPLITS_DAYS_AHEAD = 1             # today and tomorrow's probables

# A pitcher store may shrink by at most this fraction (a corrected appearance)
# before a refresh refuses to promote it. Everything else may not shrink.
PITCHER_SHRINK_TOLERANCE = 0.02

STEP_ORDER = ("results", "bullpen", "pitchers", "standings", "splits",
              "handedness", "arsenals", "transactions")
STEP_WEIGHT = {"results": 30, "bullpen": 20, "pitchers": 25, "standings": 8,
               "splits": 5, "handedness": 4, "arsenals": 3, "transactions": 5}

ENV_GUARD_INTERVAL = "DISPLAY_REFRESH_GUARD_INTERVAL_SECONDS"
ENV_GUARD_DELAY = "DISPLAY_REFRESH_GUARD_INITIAL_DELAY_SECONDS"
DEFAULT_GUARD_DELAY_S = 120.0
GUARD_MIN_GAP_S = 1800.0          # never start two refreshes closer than this
GUARD_CHILD_MEMORY_MB = 700
GUARD_CHILD_SECONDS = 240.0


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
    attempted = processed = failed = 0
    errors = []
    for first, last in _chunks(start, _d(ctx.today), RESULTS_CHUNK_DAYS):
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
    return {"from": start.isoformat(), "to": ctx.today, "attempted": attempted,
            "processed": processed, "failed": failed, "errors": errors[:5]}


def _step_bullpen(ctx: _Ctx) -> dict:
    from src.pipeline import bullpen
    log = ctx.w("bullpen_log.jsonl")
    yesterday = _d(ctx.yesterday)
    # Yesterday is re-fetched WHOLE: a refresh near midnight Eastern sees
    # games still in progress, and `build_log` skips a date once any row for it
    # exists, so without this a late game would be missing for good.
    replaced = _rewrite_jsonl_without(log, lambda r: r.get("date") == ctx.yesterday)
    start = yesterday - timedelta(days=BULLPEN_WINDOW_DAYS - 1)
    have = _jsonl_dates(log)
    if have:
        start = max(start, _d(min(have)))
    appearances = dates = failed = 0
    for first, last in _chunks(start, yesterday, BULLPEN_CHUNK_DAYS):
        if ctx.deadline.expired():
            break
        report = bullpen.build_log(first, last, path=log, resume=True,
                                   timeout=ctx.timeout)
        appearances += report["appearances"]
        dates += report["dates"]
        failed += report["failed"]
    return {"from": start.isoformat(), "to": ctx.yesterday,
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


def _step_pitchers(ctx: _Ctx) -> dict:
    from src.pipeline import history, pitchers
    path = ctx.w("pitcher_logs.jsonl")
    results = history.read_results(ctx.w("mlb_results.csv"))
    cutoff = (_d(ctx.today) - timedelta(days=PITCHER_ACTIVE_DAYS)).isoformat()
    recent_ids = pitchers.probable_pitcher_ids(
        {k: v for k, v in results.items() if str(v.get("date") or "") >= cutoff})
    upcoming = _probable_ids_for(
        [(_d(ctx.today) + timedelta(days=i)).isoformat() for i in range(0, 3)], ctx.timeout)
    # Upcoming starters first (they decide tonight's pages), then anyone who
    # started lately. Within each group, never-checked before stale.
    existing = pitchers.read_logs(path)

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
    return {"candidates": len(ordered), "upcoming_probables": len(upcoming),
            "fetched": processed, "failed": failed, "deferred_by_deadline": deferred}


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

    built = skipped = failed = 0
    day = start
    while day <= today:
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
    return {"from": start.isoformat(), "to": ctx.today, "built": built,
            "skipped": skipped, "failed": failed, "retaken_yesterday_rows": retaken}


def _drop_standings_day(path: Path, day: str) -> int:
    return _rewrite_jsonl_without(path, lambda r: r.get("date") == day)


def _step_splits(ctx: _Ctx) -> dict:
    from src.pipeline import lineups
    ids = _probable_ids_for(
        [(_d(ctx.today) + timedelta(days=i)).isoformat()
         for i in range(0, SPLITS_DAYS_AHEAD + 1)], ctx.timeout)
    fetched = failed = 0
    ordered = sorted(ids)
    for index in range(0, len(ordered), 10):
        if ctx.deadline.expired():
            break
        report = lineups.refresh_splits(ordered[index:index + 10], ctx.season,
                                        cache_path=ctx.w("pitcher_splits.json"),
                                        timeout=ctx.timeout)
        fetched += report["fetched"]
        failed += report["failed"]
    return {"requested": len(ids), "fetched": fetched, "failed": failed}


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


def _promote(work_file: Path, dest: Path, kind: str) -> dict:
    """Move one finished copy over its original if it is sound and not worse."""
    if not work_file.exists():
        return {"file": dest.name, "promoted": False, "reason": "step produced no file"}
    problem = _validate(work_file)
    if problem:
        return {"file": dest.name, "promoted": False, "reason": f"copy does not parse: {problem}"}
    if _sha(work_file) == _sha(dest):
        return {"file": dest.name, "promoted": False, "reason": "unchanged"}
    before, after = _rows(dest), _rows(work_file)
    if before is not None and after is not None and kind != "manifest":
        floor = before * (1.0 - PITCHER_SHRINK_TOLERANCE) if kind == "pitcher" else before
        if after < floor:
            return {"file": dest.name, "promoted": False, "rows_before": before, "rows_after": after,
                    "reason": "copy has fewer rows than the committed one; kept the committed copy"}
    _atomic_replace(work_file, dest)
    return {"file": dest.name, "promoted": True, "rows_before": before, "rows_after": after}


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

def refresh(root=None, *, now=None, max_seconds: float = DEFAULT_MAX_SECONDS,
            only=None, timeout: int = FETCH_TIMEOUT_S,
            clock: Callable[[], float] = time.monotonic,
            log: Optional[Callable[[str], None]] = None) -> dict:
    """Catch the stores up. `root` is a data root (default: the project's).
    Returns a report; never raises for a network or data problem."""
    log = log or (lambda text: print(text, flush=True))
    moment = store_freshness._utc(now)
    today = store_freshness.baseball_date(moment)
    data_root = Path(root) if root is not None else paths.data_root()
    base = data_root / "historical"
    wanted = [s for s in STEP_ORDER if only is None or s in set(only)]
    started = clock()
    report: dict = {"started_utc": moment.isoformat(), "baseball_date": today,
                    "steps": {}, "promoted": [], "kept": [], "skipped_reason": None}

    before = store_freshness.report(data_root, moment)
    report["before"] = _summary(before)
    log(f"display refresh: baseball date {today}; core stores through "
        + ", ".join(f"{n}={before['stores'][n]['through']}" for n in store_freshness.CORE_STORES))

    # One cheap call first. An unreachable API must cost seconds, not the budget.
    try:
        mlb.fetch_schedule(today, timeout=PROBE_TIMEOUT_S)
    except mlb.MLBError as exc:
        report["skipped_reason"] = f"MLB Stats API unreachable: {exc}"
        report["after"] = report["before"]
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
            entry: dict = {}
            try:
                if deadline.expired():
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
            for p in promotions:
                (report["promoted"] if p["promoted"] else report["kept"]).append(
                    {"step": name, **p})
            report["steps"][name] = entry
            log(f"  {name:<12} {entry['status']:<7} {entry['seconds']:>6.1f}s  "
                + ", ".join(f"{p['file']}:{'PROMOTED' if p['promoted'] else p['reason']}" for p in promotions))
    finally:
        shutil.rmtree(work, ignore_errors=True)

    after = store_freshness.report(data_root, moment)
    report["after"] = _summary(after)
    report["elapsed_s"] = round(clock() - started, 2)
    log("display refresh: through " + ", ".join(
        f"{n}={after['stores'][n]['through']}" for n in store_freshness.CORE_STORES)
        + (f"; still stale: {', '.join(after['core_stale'])}" if after["core_stale"] else "; core stores current"))
    return report


def _summary(freshness: dict) -> dict:
    return {"expected_through": freshness["expected_through"],
            "core_stale": freshness["core_stale"], "stale": freshness["stale"],
            "through": {n: e["through"] for n, e in freshness["stores"].items()}}


# ---------------------------------------------------------------------------
# The container guard
# ---------------------------------------------------------------------------

_GUARD_STATUS: dict = {"enabled": False, "interval_s": None, "runs": 0,
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
           "--max-seconds", str(int(seconds)), "--max-memory-mb", str(int(memory_mb))]
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
               child: Callable[..., dict] = _run_child) -> dict:
    """One check: refresh in a child only if a core store is stale and the last
    run is not too recent. Returns what it decided (also kept in guard_status)."""
    freshness = store_freshness.report(root, now)
    stale = freshness["core_stale"]
    if not stale:
        decision = {"ran": False, "reason": "core stores current", "core_stale": []}
    elif last_run_at is not None and clock() - last_run_at < GUARD_MIN_GAP_S:
        decision = {"ran": False, "reason": "refreshed recently; waiting", "core_stale": stale}
    else:
        outcome = child(root)
        decision = {"ran": True, "core_stale": stale, **outcome}
    return decision


def start_background_guard(*, ready: Optional[Callable[[], bool]] = None,
                           env=None, root=None, stop_event: Optional[threading.Event] = None,
                           child: Callable[..., dict] = _run_child,
                           sleep: Callable[[float], bool] = None) -> Optional[threading.Thread]:
    """Start the one daemon thread that keeps a long-lived container current.

    Disabled (returns None, starts nothing) unless
    DISPLAY_REFRESH_GUARD_INTERVAL_SECONDS > 0. Waits `ready()` (the app's
    first warm-up pass) so a refresh never competes with the warm-up for the
    1 GB machine, then every interval runs `guard_tick`. The refresh itself is
    a child process (see `_run_child`); this thread only decides and waits.
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
            try:
                decision = guard_tick(root=root, last_run_at=last_run_at, child=child)
                now_iso = datetime.now(timezone.utc).isoformat()
                if decision["ran"]:
                    last_run_at = time.monotonic()
                    with _GUARD_LOCK:
                        _GUARD_STATUS["runs"] += 1
                    _set_status(last_attempt_utc=now_iso, last_exit=decision.get("exit"),
                                last_result=decision.get("result"))
                else:
                    _set_status(last_result=decision["reason"])
            except Exception as exc:  # noqa: BLE001 -- a guard must never take the app down
                _set_status(last_result=f"guard error: {type(exc).__name__}: {exc}")
            _set_status(next_check_utc=(datetime.now(timezone.utc)
                                        + timedelta(seconds=interval)).isoformat())
            if wait(interval):
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", default=None, help="data root (default: the project's data/)")
    parser.add_argument("--max-seconds", type=float, default=DEFAULT_MAX_SECONDS)
    parser.add_argument("--only", default=None,
                        help="comma-separated steps: " + ",".join(STEP_ORDER))
    parser.add_argument("--max-memory-mb", type=int, default=0,
                        help="cap this process's address space (Linux)")
    parser.add_argument("--json", default=None, help="also write the report here")
    parser.add_argument("--check", action="store_true",
                        help="print the freshness report and stop; fetch nothing")
    args = parser.parse_args(argv)

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
