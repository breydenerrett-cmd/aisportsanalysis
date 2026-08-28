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
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
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
        "inning", "home_team", "away_team")

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
    except (urllib.error.URLError, OSError) as exc:
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


def build(season, store=DEFAULT_STORE, on_window=None, timeout=DEFAULT_TIMEOUT) -> dict:
    """Fetch one season, resumably. A crash costs at most one window."""
    if season not in SEASON_BOUNDS:
        raise StatcastPitchError(f"no season bounds for {season}")
    target = Path(store)
    target.mkdir(parents=True, exist_ok=True)
    manifest = read_manifest(store)

    report = {"season": season, "windows": 0, "skipped": 0, "rows": 0, "failed": 0}
    for start, end in _windows(*SEASON_BOUNDS[season]):
        key = f"{start}..{end}"
        if key in manifest["windows"]:
            report["skipped"] += 1
            continue
        rows = None
        for attempt in range(RETRIES):
            try:
                rows = fetch_window(start, end, timeout=timeout)
                break
            except StatcastPitchError as exc:
                last = exc
                if attempt + 1 < RETRIES:
                    time.sleep(RETRY_BACKOFF[min(attempt,
                                                 len(RETRY_BACKOFF) - 1)])
        if rows is None:
            report["failed"] += 1
            if on_window:
                on_window({"window": key, "error": str(last)})
            continue
        path = target / f"pitches_{key}.jsonl.gz"
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        manifest["windows"][key] = {"rows": len(rows), "file": path.name}
        _manifest_path(store).write_text(json.dumps(manifest, indent=1,
                                                    sort_keys=True),
                                         encoding="utf-8")
        report["windows"] += 1
        report["rows"] += len(rows)
        if on_window:
            on_window({"window": key, "rows": len(rows)})
        time.sleep(INTER_REQUEST_SECONDS)
    return report


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
