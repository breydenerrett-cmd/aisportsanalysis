"""Pitch-level Statcast: the raw material for point-in-time splits and arsenals.

WHY PITCH LEVEL, WHEN THE LEADERBOARDS EXIST
--------------------------------------------
Every aggregate source audited so far -- MLB statSplits, Savant arsenal
leaderboards, the vsPlayer endpoint -- is season-or-career-to-date with no as-of
parameter. Verified, not assumed: statSplits returns byte-identical numbers for
any date range requested. None of them can answer what was known before a game
in June.

Pitch-level rows can, because each carries its own date. Platoon splits, pitch
mix, and batter-vs-pitcher history all become forward accumulations over rows
that already existed at the cutoff -- the same shape as every CLEAN input in the
point-in-time audit, which is what lets those inputs flip from LEAKY.

THE EXPORT CAP, MEASURED
------------------------
Savant truncates CSV exports at exactly 25,000 rows and a full week of MLB is
~27,000 pitches. A silent truncation is worse than a failure -- a week missing
its last day looks complete -- so windows are 4 days, the cap is treated as an
error, and every stored window records its row count.

WHAT IS KEPT
------------
Only the columns the rebuilt features need. The full feed is 119 columns and an
unused column is a column nobody validates. Rows are stored gzipped by window,
with a manifest, so the ingest is resumable and a crash costs one window.

`catchup()`: THE FORWARD CADENCE
---------------------------------
`build()` is the one-time-per-season backfill; `catchup(through=...)` is what
keeps the store from going stale afterward. It reads the manifest's own high
-water mark (`latest_covered_date`) and fetches only the `WINDOW_DAYS`-wide
windows between there and `through` (default: yesterday, UTC) -- same window
shape, same file naming, same manifest record `build()` writes, so a reader
of the store (`iter_rows`, `iter_rows_dated`, every `rebuilt` accumulation)
cannot tell a caught-up window from a backfilled one. It is append-only:
windows already in the manifest are never re-fetched or rewritten, a failed
fetch (retries exhausted) writes no file and touches no manifest key at all,
and the manifest itself is replaced atomically (write-temp-then-`os.replace`)
so a crash mid-write can never leave a half-updated manifest behind. Run it
daily (`python3 -m src.cli statcast --catchup`) and the six pitch-accumulator
matchup features in `src.engine.features` grade A instead of D: run daily,
each call covers only the one new day since the last run (`_windows` caps a
window at `through`, so a 1-day gap makes a 1-day window, not a padded
4-day one), so the ongoing cost is ONE HTTP request per day (~7,000 pitches,
well under the 25,000-row export cap) against Baseball Savant's free,
uncredited pitch feed -- zero ODDS-API credits, ever. A missed day or two is
not a problem: the next run's window simply widens to cover the gap, up to
`WINDOW_DAYS` (4) days before the export cap becomes a real risk again.
"""

from __future__ import annotations

import http.client
import csv
import gzip
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.paths import historical_path

HOST = "https://baseballsavant.mlb.com"
USER_AGENT = "Mozilla/5.0 (compatible; aisportsanalysis/0.1)"
DEFAULT_TIMEOUT = 180
DEFAULT_STORE = historical_path("statcast")

# Savant truncates at exactly this many rows. Hitting it means data loss.
EXPORT_CAP = 25000
WINDOW_DAYS = 4

# Savant drops connections under back-to-back heavy exports. A pause between
# windows plus bounded retries turns an hour of failures into a slower success;
# a season is ~45 windows, so ten seconds of politeness costs eight minutes.
INTER_REQUEST_SECONDS = 10
RETRIES = 4
RETRY_BACKOFF = (15, 45, 120)

KEEP = ("game_date", "game_pk", "pitcher", "batter", "stand", "p_throws",
        "pitch_type", "release_speed", "events", "description",
        "woba_value", "woba_denom", "at_bat_number", "pitch_number",
        "inning", "home_team", "away_team",
        # Batted-ball type (ground_ball/fly_ball/line_drive/popup), added
        # 2026-08-31 for the batted-ball profile features. Windows fetched
        # before then lack the column and read as None -- the V5 coverage
        # audit found 0 of 2.74M stored rows carried it, which is why the
        # store is being re-ingested rather than the feature faked.
        "bb_type")

SEASON_BOUNDS = {  # regular season, slightly wide
    2023: ("2023-03-30", "2023-10-01"),
    2024: ("2024-03-28", "2024-09-30"),
    2025: ("2025-03-27", "2025-09-28"),
    2026: ("2026-03-26", "2026-08-27"),
}


class StatcastPitchError(RuntimeError):
    """Raised when the pitch feed cannot be fetched or would be truncated."""


def _windows(start, end):
    lo, hi = date.fromisoformat(start), date.fromisoformat(end)
    day = lo
    while day <= hi:
        stop = min(day + timedelta(days=WINDOW_DAYS - 1), hi)
        yield day.isoformat(), stop.isoformat()
        day = stop + timedelta(days=1)


def fetch_window(start, end, timeout=DEFAULT_TIMEOUT) -> list:
    query = urllib.parse.urlencode({
        "all": "true", "type": "details", "player_type": "pitcher",
        "game_date_gt": start, "game_date_lt": end})
    url = f"{HOST}/statcast_search/csv?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8-sig", "replace")
    except urllib.error.HTTPError as exc:
        raise StatcastPitchError(f"Savant returned HTTP {exc.code}") from None
    except (urllib.error.URLError, OSError,
            http.client.IncompleteRead) as exc:
        # IncompleteRead is Savant hanging up mid-transfer -- observed live
        # on 2026-08-31 killing a 180-window re-ingest at window seven. It
        # is exactly as transient as a refused connection and must land in
        # the same retry path, not escape as a raw crash.
        raise StatcastPitchError(f"could not reach Savant: {exc}") from None

    rows = []
    for row in csv.DictReader(io.StringIO(raw)):
        rows.append({key: (row.get(key) or None) for key in KEEP})
    if len(rows) >= EXPORT_CAP:
        # Truncated, not big. A window missing its last day looks complete,
        # which is why this is an error and not a warning.
        raise StatcastPitchError(
            f"window {start}..{end} hit the {EXPORT_CAP}-row export cap and "
            "was truncated; shrink the window")
    return rows


def _manifest_path(store):
    return Path(store) / "manifest.json"


def read_manifest(store=DEFAULT_STORE) -> dict:
    path = _manifest_path(store)
    if not path.exists():
        return {"windows": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_manifest_atomic(store, manifest) -> None:
    """Write the manifest so a crash mid-write can never leave a truncated or
    half-updated file behind -- write the full new content to a sibling temp
    file, then one atomic `os.replace` onto the real path. `os.replace` is
    atomic on both POSIX and Windows, so a reader (including this same
    process, resumed) only ever sees the old manifest or the fully-new one,
    never something in between."""
    path = _manifest_path(store)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(manifest, indent=1, sort_keys=True),
                    encoding="utf-8")
    os.replace(tmp, path)


def _fetch_with_retries(start, end, timeout):
    """`fetch_window`, retried with backoff. Returns rows, or raises the last
    `StatcastPitchError` once retries are exhausted -- there is no partial
    result to return, only success or a clean failure."""
    last = None
    for attempt in range(RETRIES):
        try:
            return fetch_window(start, end, timeout=timeout)
        except StatcastPitchError as exc:
            last = exc
            if attempt + 1 < RETRIES:
                time.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])
    raise last


def _ingest(window_pairs, store, on_window, timeout, report,
            stop_on_failure=False) -> dict:
    """Fetch and store every window in `window_pairs` that is not already in
    the manifest, mutating `report` in place and returning it.

    Append-only by construction: a window whose key is already in the
    manifest is skipped outright (never re-fetched, so an existing file is
    never opened for writing again), and every new window's file is written
    completely -- gzip, flush, close -- before the manifest is updated to
    mention it, so a crash between "fetched" and "recorded" costs exactly
    that one window and nothing already on disk changes. A failed fetch
    (retries exhausted) writes no file and touches no manifest key at all --
    refusing a partial window rather than recording one -- so the same
    window is retried, not skipped, on the next run.

    `stop_on_failure` (used by `catchup`, not `build`): a forward-extending
    run must keep the manifest's coverage CONTIGUOUS from the store's
    original start, because `latest_covered_date`/`_pitch_coverage_end`
    trust the single latest window END as the store's whole coverage bound
    -- they do not check for holes earlier in the range. Continuing past a
    failed window to fetch a LATER one would silently create exactly such a
    hole (a later window recorded as covered while an earlier, still-failed
    one is skipped over) and every subsequent freshness check would then
    read the store as covering a date range it does not actually have data
    for. Stopping at the first failure keeps every window that IS recorded
    forming one unbroken run from the start, so the high-water mark stays
    honest and the very next run retries the gap before trying to move
    past it -- one extra day's delay on a real Savant outage, against a
    silent, wrong "fresh" grading otherwise. `build()`'s season-long
    backfill has no such freshness reader depending on a single high-water
    mark, so it keeps its original "get as much of the season as possible"
    behavior (`stop_on_failure=False`, the default).
    """
    target = Path(store)
    manifest = read_manifest(store)
    for start, end in window_pairs:
        key = f"{start}..{end}"
        if key in manifest["windows"]:
            report["skipped"] += 1
            continue
        try:
            rows = _fetch_with_retries(start, end, timeout)
        except StatcastPitchError as exc:
            report["failed"] += 1
            if on_window:
                on_window({"window": key, "error": str(exc)})
            if stop_on_failure:
                break
            continue
        path = target / f"pitches_{key}.jsonl.gz"
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        # The manifest is only ever grown here, never rewritten in place for
        # an existing key (guarded by the skip above) and never reordered on
        # disk in a way that changes any existing window's content --
        # `sort_keys=True` fixes the on-disk key order to lexicographic
        # (== chronological, for these "YYYY-MM-DD..YYYY-MM-DD" keys)
        # regardless of insertion order, but every prior window's value is
        # byte-identical before and after.
        manifest["windows"][key] = {"rows": len(rows), "file": path.name}
        _write_manifest_atomic(store, manifest)
        report["windows"] += 1
        report["rows"] += len(rows)
        if on_window:
            on_window({"window": key, "rows": len(rows)})
        time.sleep(INTER_REQUEST_SECONDS)
    return report


def build(season, store=DEFAULT_STORE, on_window=None, timeout=DEFAULT_TIMEOUT) -> dict:
    """Fetch one season, resumably. A crash costs at most one window."""
    if season not in SEASON_BOUNDS:
        raise StatcastPitchError(f"no season bounds for {season}")
    target = Path(store)
    target.mkdir(parents=True, exist_ok=True)
    report = {"season": season, "windows": 0, "skipped": 0, "rows": 0, "failed": 0}
    return _ingest(_windows(*SEASON_BOUNDS[season]), store, on_window, timeout,
                   report)


def latest_covered_date(store=DEFAULT_STORE) -> str | None:
    """The latest `game_date` (inclusive) any stored window's key claims to
    cover -- the manifest's own high-water mark, and the honest starting
    point for extending the store. `None` when the store has no windows at
    all (missing entirely, or not yet built). Mirrors
    `src.engine.features._pitch_coverage_end` exactly (same computation);
    kept here too, as a public function, since `catchup` and any caller
    outside the engine both need it and neither should reach into the
    other's private helpers."""
    manifest = read_manifest(store)
    windows = manifest.get("windows") or {}
    ends = [key.split("..")[-1] for key in windows if ".." in key]
    return max(ends) if ends else None


def catchup(through=None, store=DEFAULT_STORE, on_window=None,
            timeout=DEFAULT_TIMEOUT) -> dict:
    """Extend the store forward from the manifest's own last covered date
    through `through` (default: yesterday, UTC calendar date), in the exact
    same `WINDOW_DAYS`-wide window shape, file naming and manifest record
    `build()` uses -- this is the forward cadence that keeps the store from
    going stale between manual backfills, not a separate mechanism.

    Refuses rather than guessing when there is nothing to extend from (no
    prior windows at all -- run a full `build()` first) or when asked to
    reach into today or the future (today's pitches are not final until the
    day is over, so "through today" would risk a window that looks complete
    but silently grows the next time this runs against the same date; ask
    again tomorrow instead). Idempotent: a window already in the manifest is
    never re-requested, so calling this again with the same `through` (or an
    earlier one) fetches and writes nothing. Resumable: a run that stops
    partway (a failed window, a killed process) leaves every prior window
    exactly as it was and the next run picks up from the same manifest,
    re-attempting only the windows that never made it in.
    """
    target = Path(store)
    target.mkdir(parents=True, exist_ok=True)
    last_end = latest_covered_date(store)
    if last_end is None:
        raise StatcastPitchError(
            f"{store} has no existing windows to extend -- run a full "
            "season build() first")

    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    if through is None:
        through_date = yesterday
    else:
        through_date = date.fromisoformat(through)
        if through_date > yesterday:
            raise StatcastPitchError(
                f"--through {through_date.isoformat()} is not yet over "
                f"(today is {today.isoformat()} UTC) -- catchup only "
                "reaches through yesterday, so an in-progress day is never "
                "recorded as though it were complete")

    start = date.fromisoformat(last_end) + timedelta(days=1)
    report = {"from": start.isoformat() if start <= through_date else None,
              "through": through_date.isoformat(),
              "last_covered_before": last_end,
              "windows": 0, "skipped": 0, "rows": 0, "failed": 0}
    if start > through_date:
        # Already current: the manifest's coverage already reaches at or
        # past the target date, so there is nothing to fetch. Not an error --
        # this is exactly what a same-day re-run of a cron job should see.
        return report
    windows = _windows(start.isoformat(), through_date.isoformat())
    return _ingest(windows, store, on_window, timeout, report,
                   stop_on_failure=True)


def iter_rows_dated(store=DEFAULT_STORE):
    """Every stored pitch in game_date order, in one pass.

    Windows never overlap and their keys sort by start date, so global order
    only needs each window sorted internally -- Savant returns rows in feed
    order, not date order, and a boundary-straddling cutoff taken mid-window
    would otherwise see rows from after its date. A window is at most 4 days
    (bounded by EXPORT_CAP rows), so the per-window buffer stays small.
    """
    manifest = read_manifest(store)
    for key in sorted(manifest["windows"]):
        path = Path(store) / manifest["windows"][key]["file"]
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle]
        # Undated rows sort last, mirroring iter_rows' "9999" sentinel: they
        # are never admitted before any real cutoff.
        rows.sort(key=lambda row: row.get("game_date") or "9999")
        yield from rows


def iter_rows(store=DEFAULT_STORE, before=None):
    """Every stored pitch, optionally strictly before a date. The accumulation
    primitive every rebuilt feature reads through."""
    if before is not None:
        # The gate is a lexicographic compare against 'YYYY-MM-DD' rows, and
        # str(datetime) carries a time suffix that sorts AFTER the bare date --
        # which would silently admit every pitch from the cutoff day itself.
        # Dossier information_times are datetimes, so reduce to the calendar
        # day before stringifying; the day's own pitches must never leak.
        if isinstance(before, datetime):
            before = before.date()
        before = str(before)
    manifest = read_manifest(store)
    for key in sorted(manifest["windows"]):
        start = key.split("..")[0]
        if before is not None and start >= before:
            # Window starts at/after the cutoff; nothing in it is usable and
            # windows are date-sorted, so stop entirely.
            break
        path = Path(store) / manifest["windows"][key]["file"]
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                if before is None or (row.get("game_date") or "9999") < before:
                    yield row
