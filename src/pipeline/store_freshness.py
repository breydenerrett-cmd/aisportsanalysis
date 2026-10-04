"""How current is every store a page reads at request time? One function.

WHY THIS EXISTS (2026-10-03)
----------------------------
The site's computed pages read FILES in the container image at request time --
results, pitcher logs, bullpen log, standings, platoon splits, arsenals,
transactions, posted lineups. Capture commits odds and cards every hour, but
nothing committed these, so the image carried copies that had stopped between
Sept 6 and Sept 23 while the page happily rendered "no relief appearances in
the last 7 days" and "days rest 14" from them. Nothing anywhere said so, and
the one health surface (`/health`) only timed the odds stores.

`report()` answers the question from outside the pages: per store, the newest
date it covers, how many days behind "yesterday, Eastern" that is, and whether
that is past the store's own tolerance. `src.appstate.apphealth.report` embeds
it as `data_freshness` on `/health`; `src.pipeline.display_refresh` uses it to
decide whether a refresh is needed and to prove afterwards that one worked.

"THROUGH" IS COVERAGE, NOT THE NEWEST GAME
------------------------------------------
A store that was refreshed on an off day has no row for that day, so the
newest ROW understates how current it is -- in the winter every store would
look months stale while being exactly as current as it can be. So `through` is
the newest date the store has COVERED:

  results        newest date in the manifest with no game still pending
                 (the manifest records every attempted date, off days too)
  pitcher_logs   the later of the newest appearance and the newest
                 `checked_utc` marker (a refresh that found nothing new)
  bullpen_log    newest date, counting the explicit empty-day markers
  standings      newest daily snapshot
  everything else the newest date or `as_of` stamp it carries

`newest_row` is reported alongside wherever it differs, so nothing is hidden.

THE HONESTY RULE (same as src/appstate/apphealth.py): an absent store says
absent, an unreadable one says why, and nothing is ever reported fresh because
it could not be timed -- `through` is None and `stale` is True.

NO NETWORK, STDLIB ONLY, CHEAP. Files are streamed once and the answer cached
against (size, mtime), so a /health poll every thirty seconds re-reads nothing
unless a store actually changed. Memory is flat: no store is held in memory.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from src import paths


# ---------------------------------------------------------------------------
# The baseball date
# ---------------------------------------------------------------------------

def _nth_sunday(year: int, month: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def eastern_offset(moment: datetime) -> timedelta:
    """-4h while US daylight time is in force, -5h otherwise. A fixed rule
    (second Sunday of March 07:00Z to first Sunday of November 06:00Z), because
    `zoneinfo` needs a tz database the slim image does not ship. Same rule as
    `src.report.postseason_page.eastern_utc_offset`; a test pins them equal."""
    begins = datetime.combine(_nth_sunday(moment.year, 3, 2), datetime.min.time(),
                              tzinfo=timezone.utc) + timedelta(hours=7)
    ends = datetime.combine(_nth_sunday(moment.year, 11, 1), datetime.min.time(),
                            tzinfo=timezone.utc) + timedelta(hours=6)
    return timedelta(hours=-4 if begins <= moment < ends else -5)


def _utc(now) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, str):
        now = datetime.fromisoformat(now.replace("Z", "+00:00"))
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def baseball_date(now=None) -> str:
    """The US Eastern calendar date of `now`: the date the schedule files a
    game under. From 8 pm Eastern the UTC date is already tomorrow."""
    moment = _utc(now)
    return (moment + eastern_offset(moment)).date().isoformat()


# ---------------------------------------------------------------------------
# What is read, and how old is too old
# ---------------------------------------------------------------------------

# A store is STALE when its `through` is more than this many days behind
# yesterday (Eastern). Yesterday, because a day's games are final only after
# midnight Eastern; the tolerance is on top of that, so a refresh that runs at
# the top of the hour around midnight never reads as an outage.
RESULTS_TOLERANCE_DAYS = 1
DAILY_TOLERANCE_DAYS = 1
PITCHER_TOLERANCE_DAYS = 2
SEASON_AGGREGATE_TOLERANCE_DAYS = 3

# A standings snapshot exists only while regular-season games are being
# played: the Stats API answers a postseason (or off-season) date with an empty
# table. Once the newest regular-season game in the results store is more than
# this many days old, the season is over and the newest snapshot is the last
# one there will ever be -- not a stale one.
STANDINGS_SEASON_ACTIVE_DAYS = 4


def standings_horizon(newest_regular: Optional[str], today: str) -> str:
    """The last date a standings snapshot can exist: `today` while the regular
    season is being played, else the day of its last game."""
    if newest_regular is None:
        return today
    cutoff = (date.fromisoformat(today) - timedelta(days=STANDINGS_SEASON_ACTIVE_DAYS)).isoformat()
    return newest_regular if newest_regular < cutoff else today


# The stores whose staleness makes a refresh worth running. The rest are
# reported (and refreshed best-effort) but never the reason to start one.
CORE_STORES = ("mlb_results", "pitcher_logs", "bullpen_log", "standings")


@dataclass(frozen=True)
class StoreSpec:
    name: str
    rel: str                       # under <data root>/historical/
    tolerance_days: int
    reads: str                     # which pages/routes read it (documentation, shown in the report)
    scan: Callable[[Path], dict]   # path -> {"through", "newest_row", "rows"}


def _day(value) -> Optional[str]:
    """The calendar day of a stored date or timestamp, or None. Accepts
    'YYYY-MM-DD', a longer ISO timestamp, and basic-format 'YYYYMMDD'."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        try:
            return date.fromisoformat(text[:10]).isoformat()
        except ValueError:
            return None
    if len(text) >= 8 and text[:8].isdigit():
        try:
            return date(int(text[:4]), int(text[4:6]), int(text[6:8])).isoformat()
        except ValueError:
            return None
    return None


def _iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # a truncated final line costs one row, not the report
            if isinstance(row, dict):
                yield row


def _scan_jsonl(field: str, *, also: tuple = ()) -> Callable[[Path], dict]:
    """Newest date in `field` (and in any `also` fields, folded into
    `through` but not into `newest_row`)."""
    def scan(path: Path) -> dict:
        rows = 0
        newest_row = through = None
        for row in _iter_jsonl(path):
            rows += 1
            day = _day(row.get(field))
            if day and (newest_row is None or day > newest_row):
                newest_row = day
            for extra in (field, *also):
                d = _day(row.get(extra))
                if d and (through is None or d > through):
                    through = d
        return {"through": through, "newest_row": newest_row, "rows": rows}
    return scan


def _scan_results(path: Path) -> dict:
    """The results CSV plus its manifest, which is the coverage record."""
    rows = 0
    newest_row = newest_regular = None
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows += 1
            day = _day(row.get("date"))
            if day and (newest_row is None or day > newest_row):
                newest_row = day
            # A row with no game_type is regular season (every older row).
            is_regular = (row.get("game_type") or "R") == "R"
            if day and is_regular and (newest_regular is None or day > newest_regular):
                newest_regular = day
    through = None
    manifest_path = path.with_name("mlb_results.manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = manifest.get("dates", manifest) if isinstance(manifest, dict) else {}
    except (OSError, json.JSONDecodeError):
        manifest = {}
    # Newest date that was fetched with no game still pending. A date fetched
    # while a game was in progress is not covered until it is fetched again.
    done = [d for d, entry in manifest.items()
            if _day(d) and not (entry or {}).get("pending")]
    if done:
        through = max(_day(d) for d in done)
    elif newest_row:
        # No manifest: all that can honestly be said is the newest game.
        through = newest_row
    return {"through": through, "newest_row": newest_row, "rows": rows,
            "newest_regular": newest_regular}


def _scan_pitcher_logs(path: Path) -> dict:
    rows = 0
    newest_row = checked = None
    for row in _iter_jsonl(path):
        if row.get("person_id") is None:
            continue
        rows += 1
        day = _day(row.get("date"))
        if day and (newest_row is None or day > newest_row):
            newest_row = day
        marker = _day(row.get("checked_utc"))
        if marker and (checked is None or marker > checked):
            checked = marker
    through = max((d for d in (newest_row, checked) if d), default=None)
    return {"through": through, "newest_row": newest_row, "rows": rows,
            "last_checked": checked}


def _scan_splits(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("not an object")
    stamps = [_day(v.get("as_of")) for v in data.values() if isinstance(v, dict)]
    stamps = [s for s in stamps if s]
    newest = max(stamps) if stamps else None
    return {"through": newest, "newest_row": newest, "rows": len(data)}


def _scan_arsenal_file(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    day = _day(data.get("as_of")) if isinstance(data, dict) else None
    rows = len(data.get("rows") or []) if isinstance(data, dict) else 0
    return {"through": day, "newest_row": day, "rows": rows}


def _scan_handedness(path: Path) -> dict:
    # A biographical cache: no dates exist to age. Report the size only; its
    # staleness is "players in recent lineups it has not met", which the
    # refresh closes, not a date.
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"through": None, "newest_row": None, "rows": len(data) if isinstance(data, dict) else 0}


def _build_specs() -> tuple:
    return (
        StoreSpec("mlb_results", "mlb_results.csv", RESULTS_TOLERANCE_DAYS,
                  "team records, schedule form, travel, postseason series, card grading", _scan_results),
        StoreSpec("pitcher_logs", "pitcher_logs.jsonl", PITCHER_TOLERANCE_DAYS,
                  "starter lines and days rest on game pages, postseason starters",
                  _scan_pitcher_logs),
        StoreSpec("bullpen_log", "bullpen_log.jsonl", DAILY_TOLERANCE_DAYS,
                  "bullpen workload on game pages and postseason estimates", _scan_jsonl("date")),
        StoreSpec("standings", "standings.jsonl", DAILY_TOLERANCE_DAYS,
                  "league position on game pages, the postseason field", _scan_jsonl("date")),
        StoreSpec("lineups", "lineups.jsonl", DAILY_TOLERANCE_DAYS,
                  "posted batting orders on game pages", _scan_jsonl("date")),
        StoreSpec("matchup_history", "matchup_history.jsonl", DAILY_TOLERANCE_DAYS,
                  "batter-vs-pitcher history on game pages", _scan_jsonl("date")),
        StoreSpec("pitcher_splits", "pitcher_splits.json", SEASON_AGGREGATE_TOLERANCE_DAYS,
                  "platoon splits on game pages", _scan_splits),
        StoreSpec("transactions", "transactions.jsonl", SEASON_AGGREGATE_TOLERANCE_DAYS,
                  "roster news on game pages", _scan_jsonl("filed_date", also=("date",))),
        StoreSpec("arsenal_pitcher", f"arsenals/pitcher_{{season}}.json", SEASON_AGGREGATE_TOLERANCE_DAYS,
                  "pitch arsenals on game pages", _scan_arsenal_file),
        StoreSpec("arsenal_batter", f"arsenals/batter_{{season}}.json", SEASON_AGGREGATE_TOLERANCE_DAYS,
                  "pitch arsenals on game pages", _scan_arsenal_file),
        StoreSpec("handedness", "handedness.json", 10 ** 6,
                  "lineup handedness on game pages (no date: size only)", _scan_handedness),
    )


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

_cache_lock = threading.Lock()
_scan_cache: dict = {}


def _scan_cached(spec: StoreSpec, path: Path) -> dict:
    """One store's scan, remembered against (size, mtime) so an unchanged file
    is never re-read. Errors are returned, never raised.

    A failure is remembered too, per file version. It used to be recomputed on
    every call ("errors are never cached"), so a corrupt or torn store was
    parsed again by every /health poll and every /data/v1/status request until
    someone fixed it -- the UFC and NFL halves of that route already remember a
    failure per file version for exactly this reason. A file that is repaired or
    rewritten has a new (size, mtime) and is read again at once.

    The caller-facing error is the exception TYPE only: an OSError's text
    carries the absolute server path ("[Errno 13] Permission denied: <full path>"),
    and /status hands this string to any signed-in caller. The detail goes to
    stderr, once per file version, where the operator reads it.
    """
    try:
        stat = path.stat()
    except OSError:
        return {"present": False}
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    with _cache_lock:
        hit = _scan_cache.get(spec.name)
        if hit and hit[0] == key:
            return hit[1]
    try:
        scanned = spec.scan(path)
    except Exception as exc:  # noqa: BLE001 -- a corrupt store is a finding, not a crash
        print(f"store freshness: {spec.name} ({path}) could not be read: {type(exc).__name__}: {exc}",
              file=sys.stderr, flush=True)
        scanned = {"present": True, "error": type(exc).__name__}
    else:
        scanned["present"] = True
    with _cache_lock:
        _scan_cache[spec.name] = (key, scanned)
    return scanned


def reset_cache_for_tests() -> None:
    with _cache_lock:
        _scan_cache.clear()


def report(root=None, now=None) -> dict:
    """Per store: the newest date it covers and whether that is past its
    tolerance. `root` is a DATA root (default: the project's); stores are read
    from `<root>/historical`.

    {
      "generated_at": ISO, "baseball_date": "YYYY-MM-DD" (Eastern),
      "expected_through": "YYYY-MM-DD" (yesterday, Eastern),
      "stale": [names of stores past tolerance],
      "core_stale": [the subset that makes a refresh worth running],
      "oldest_through": earliest `through` among the core stores,
      "stores": {name: {"present", "through", "newest_row", "rows",
                        "lag_days", "tolerance_days", "stale", "reads",
                        "reason"}}
    }
    """
    moment = _utc(now)
    today = baseball_date(moment)
    expected = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    season = today[:4]
    base = (Path(root) if root is not None else paths.data_root()) / "historical"

    stores: dict = {}
    newest_regular = newest_game = None
    for spec in _build_specs():
        rel = spec.rel.replace("{season}", season)
        scanned = _scan_cached(spec, base / rel)
        if spec.name == "mlb_results":
            newest_regular = scanned.get("newest_regular")
            newest_game = scanned.get("newest_row")
        target = expected
        if spec.name == "standings":
            target = min(expected, standings_horizon(newest_regular, today))
        elif spec.name == "pitcher_logs" and not stores.get("mlb_results", {}).get("stale", True):
            # Off-season: the results store is current and its newest game is
            # days old, so no starter is a refresh candidate and no marker is
            # written. The log is then as current as it can be, not stale.
            target = min(expected, standings_horizon(newest_game, today))
        entry = {"path": f"historical/{rel}", "reads": spec.reads,
                 "present": bool(scanned.get("present")),
                 "through": scanned.get("through"),
                 "newest_row": scanned.get("newest_row"),
                 "rows": scanned.get("rows"),
                 "tolerance_days": spec.tolerance_days,
                 "lag_days": None, "stale": False, "reason": None}
        if "last_checked" in scanned:
            entry["last_checked"] = scanned["last_checked"]
        if not entry["present"]:
            entry["stale"], entry["reason"] = True, "store is absent"
        elif scanned.get("error"):
            entry["stale"], entry["reason"] = True, f"unreadable: {scanned['error']}"
        elif spec.name == "handedness":
            entry["reason"] = "no dates to age; size only"
        elif entry["through"] is None:
            entry["stale"], entry["reason"] = True, "no dated row to age"
        else:
            lag = (date.fromisoformat(target) - date.fromisoformat(entry["through"])).days
            entry["lag_days"] = max(lag, 0)
            if target != expected:
                entry["expected_through"] = target
            if lag > spec.tolerance_days:
                entry["stale"] = True
                entry["reason"] = (f"covers through {entry['through']}, "
                                   f"{lag} day(s) behind {target}")
        stores[spec.name] = entry

    core = [n for n in CORE_STORES if n in stores]
    core_dates = [stores[n]["through"] for n in core if stores[n]["through"]]
    return {
        "generated_at": moment.isoformat(),
        "baseball_date": today,
        "expected_through": expected,
        "stale": [n for n, e in stores.items() if e["stale"]],
        "core_stale": [n for n in core if stores[n]["stale"]],
        "oldest_through": min(core_dates) if core_dates and len(core_dates) == len(core) else None,
        "stores": stores,
    }


def through_dates(root=None, now=None) -> dict:
    """{store name: its `through` date or None} -- the plain version of
    `report()` for a caller that only wants to print the dates."""
    return {name: entry["through"] for name, entry in report(root, now)["stores"].items()}


# ---------------------------------------------------------------------------
# What a game page says about the age of a store
# ---------------------------------------------------------------------------

# page key -> store. The three stores whose age changes what a game page means:
# team records and rest days (results), a starter's numbers and days of rest
# (pitcher logs), and the "no relief appearances in the last 7 days" sentence
# (bullpen log).
GAME_PAGE_STORES = (("results", "mlb_results"), ("pitcher_logs", "pitcher_logs"),
                    ("bullpen_log", "bullpen_log"))


def ends_before(through, game_date) -> bool:
    """True when a store whose coverage ends on `through` cannot describe a
    game on `game_date`: it stops more than one day before it (yesterday's
    games are legitimately the newest thing a pre-game page can hold), or its
    end is unknown. A PAST game is never called stale because the store has
    since moved on."""
    if not through:
        return True
    try:
        return (date.fromisoformat(str(game_date)[:10])
                - date.fromisoformat(str(through)[:10])).days > 1
    except ValueError:
        return True


def coverage_for_game(game_date, root=None) -> dict:
    """{"results" | "pitcher_logs" | "bullpen_log": {"through", "stale"}} for
    one game's date: what each store COVERS and whether that is too old for
    this game.

    DISPLAY ONLY, ATTACHED BESIDE THE DOSSIER, NEVER INSIDE IT. `through` is
    COVERAGE (see the module docstring), not the newest game. The first
    version of this label lived in the dossier and read the newest game in the
    results store, so the day after a league-wide off day (the schedule has
    no games on the 3rd, a refresh covered it, the newest game is the 2nd)
    every page said "results end ..." for a store that was as current as it
    can be. And a dossier section is a model and ledger input (the card's
    features, the analyst's frozen packet), which a display label must never
    change. `api/games.py` calls this per `/game` request and attaches the
    answer as `advanced.data_coverage`; each store's scan is cached against
    (size, mtime), so a request costs a few `stat` calls.

    Never fresh by default: an absent or unreadable store has `through: None`
    and `stale: True`.
    """
    base = (Path(root) if root is not None else paths.data_root()) / "historical"
    specs = {spec.name: spec for spec in _build_specs()}
    out = {}
    for key, name in GAME_PAGE_STORES:
        spec = specs[name]
        scanned = _scan_cached(spec, base / spec.rel)
        through = None
        if scanned.get("present") and not scanned.get("error"):
            through = scanned.get("through")
        out[key] = {"through": through, "stale": ends_before(through, game_date)}
    return out
