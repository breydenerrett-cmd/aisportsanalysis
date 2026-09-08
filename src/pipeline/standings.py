"""League standings and playoff context per team, captured point-in-time.

WHY THIS EXISTS
----------------
Every downstream reader that wants "where did this team stand" -- a dossier,
a narrative section -- has had nothing to read; `grep standing|division|
wildcard|playoff src/providers/mlb.py` returned nothing before this module.
The API call itself (`mlb.fetch_standings`) is free, keyless, and genuinely
point-in-time (verified live -- see that function's docstring), but calling
it at request time is still a network round trip on every dossier build.
This store makes it a local, no-network read instead: one JSONL row per
(date, team), appended once a day, so a request-time lookup is a dict get.

APPEND-ONLY, NEVER OVERWRITE
------------------------------
Same discipline as every other forward store in this project
(`src/pipeline/bullpen.py`, `src/pipeline/weather_capture.py`): a date's
snapshot, once written, is never rewritten. `build()` is idempotent per
date -- calling it again for a date already in the store is a no-op unless
`force=True` -- and `catchup()` walks a date range calling `build()` for
whatever is missing, so an interrupted run costs nothing but time.

WHY A SNAPSHOT PER DAY, NOT ONE ROW PER TEAM
----------------------------------------------
Standings change every day of the season. A single "current" row per team
would silently answer every past date's lookup with today's numbers, which
is exactly the future leak the point-in-time discipline exists to prevent.
So the store grows by ~30 rows per calendar day it is run for (one per MLB
team), and a reader always gets the exact date it asked for or an honest
`found: False` -- never a nearby date substituted for the one requested.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.paths import historical_path
from src.providers import mlb

DEFAULT_STORE = historical_path("standings.jsonl")

DEFAULT_TIMEOUT = 20

# Team-abbreviation spellings this store also accepts on lookup, mapped to
# the MLB Stats API's own spelling that `mlb.TEAM_ID_TO_ABBREV` (and this
# store's rows) actually use. Only the two franchises where the two
# conventions in this project genuinely differ (src/data/parks.py normalizes
# onto "OAK"/"ARI"; the raw API says "ATH"/"AZ") -- everything else already
# matches, so a caller does not have to know or care which spelling this
# particular store happens to key its rows by.
_ACCEPTED_ALIASES = {"OAK": "ATH", "ARI": "AZ", "ARZ": "AZ"}


class StandingsError(RuntimeError):
    """Raised when the store cannot be built or read. Never for a provider fault."""


def _to_date(value) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise StandingsError(
            f"date must be ISO format YYYY-MM-DD, got {value!r}") from exc


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_team(team) -> str:
    if not isinstance(team, str) or not team.strip():
        raise StandingsError(f"team abbreviation must be a non-empty string, got {team!r}")
    key = team.strip().upper()
    return _ACCEPTED_ALIASES.get(key, key)


# ---------------------------------------------------------------------------
# Build / catchup
# ---------------------------------------------------------------------------

def build(season, target_date, path=DEFAULT_STORE, timeout=DEFAULT_TIMEOUT,
          force=False) -> dict:
    """Fetch one (season, date) standings snapshot and append one row per team.

    Idempotent: if this exact date already has rows in the store, this is a
    no-op (`skipped: True`) unless `force=True` -- append-only, so a re-run
    never rewrites a prior day's snapshot. A provider fault is recorded and
    returned, never raised, matching the "enrichment must never fail the
    caller's loop" contract this store's daily_loop step relies on.
    """
    iso = _to_date(target_date).isoformat()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    if not force and iso in _stored_dates(target):
        return {"date": iso, "season": str(season), "skipped": True,
                "error": False, "reason": "snapshot already stored for this date",
                "teams": 0, "path": str(target)}

    try:
        records = mlb.fetch_standings(season, date=iso, timeout=timeout)
    except mlb.MLBError as exc:
        return {"date": iso, "season": str(season), "skipped": True,
                "error": True, "reason": f"MLB API error: {exc}",
                "teams": 0, "path": str(target)}

    rows = mlb.parse_standings(records)
    captured_at = _utcnow_iso()
    with target.open("a", encoding="utf-8") as handle:
        for row in rows:
            record = dict(row)
            record["date"] = iso
            record["season"] = str(season)
            record["captured_at"] = captured_at
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    return {"date": iso, "season": str(season), "skipped": False, "error": False,
            "reason": None, "teams": len(rows), "path": str(target)}


def catchup(start=None, end=None, path=DEFAULT_STORE, timeout=DEFAULT_TIMEOUT,
            on_date=None) -> dict:
    """Fill every date in [start, end] not already in the store. Resumable.

    `end` defaults to today (UTC). `start` defaults to the day after the
    store's latest snapshot, or `end` itself if the store is empty or has no
    prior snapshot -- so a bare `catchup()` call, as the daily loop makes,
    always advances the store to today without the caller tracking any
    state, and never silently launches an unbounded historical backfill on
    a fresh store. Pass `start` explicitly for a deliberate historical fill
    (e.g. the 2025 tuning season).

    `season` for each date is inferred from that date's own calendar year,
    which is correct for the regular-season window this store is built for.

    A single bad date (provider fault) is recorded in `errors` and does not
    abort the run, matching `mlb.backfill_results`' shape.
    """
    end_date = _to_date(end) if end is not None else datetime.now(timezone.utc).date()
    if start is not None:
        start_date = _to_date(start)
    else:
        latest = _latest_stored_date(path)
        start_date = (latest + timedelta(days=1)) if latest is not None else end_date

    report = {"dates_requested": 0, "dates_built": 0, "dates_skipped": 0,
              "teams": 0, "errors": [], "path": str(Path(path))}
    if start_date > end_date:
        return report

    day = start_date
    while day <= end_date:
        report["dates_requested"] += 1
        result = build(day.year, day, path=path, timeout=timeout)
        if result["error"]:
            report["errors"].append({"date": result["date"], "reason": result["reason"]})
        elif result["skipped"]:
            report["dates_skipped"] += 1
        else:
            report["dates_built"] += 1
            report["teams"] += result["teams"]
        if on_date is not None:
            on_date(result)
        day += timedelta(days=1)

    return report


def _iter_rows(path):
    target = Path(path)
    if not target.exists():
        return
    for line_no, line in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError as exc:
            raise StandingsError(f"{target}:{line_no} is not valid JSON") from exc


def _stored_dates(path) -> set:
    return {row["date"] for row in _iter_rows(path) if row.get("date")}


def _latest_stored_date(path):
    dates = _stored_dates(path)
    if not dates:
        return None
    return max(_to_date(d) for d in dates)


# ---------------------------------------------------------------------------
# Read / accessor
# ---------------------------------------------------------------------------

def read(path=DEFAULT_STORE) -> dict:
    """`{date_iso: {team_abbrev: row}}`. `{}` if the store does not exist yet.

    A row whose `team_id` was not in `mlb.TEAM_ID_TO_ABBREV` (should not
    happen for an active MLB team, but that table is static) is indexed
    under `id<team_id>` instead of dropped, so a row is never silently lost
    from the index even when its abbreviation could not be resolved.
    """
    index: dict = {}
    for row in _iter_rows(path):
        iso = row.get("date")
        if not iso:
            continue
        key = row.get("team_abbrev")
        if not key:
            team_id = row.get("team_id")
            key = f"id{team_id}" if team_id is not None else None
        if key is None:
            continue
        index.setdefault(iso, {})[key] = row
    return index


_ORDINAL_SUFFIXES = {1: "st", 2: "nd", 3: "rd"}


def _ordinal(n) -> str:
    if n is None:
        return "?"
    n = int(n)
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = _ORDINAL_SUFFIXES.get(n % 10, "th")
    return f"{n}{suffix}"


def playoff_context_line(row: dict) -> str:
    """A plain-language playoff-context sentence for one team-standing row.

    e.g. "3rd in NL Central, 6.5 GB, 2.0 back of the last wild card" or
    "1st in AL East, leads the division". Built only from fields already on
    the row -- nothing here queries the network or guesses at a missing
    field.
    """
    rank = row.get("division_rank")
    division = row.get("division_name") or "its division"
    games_back = row.get("games_back")
    wc_rank = row.get("wildcard_rank")
    wc_gb = row.get("wildcard_games_back")
    wc_leading = row.get("wildcard_leading")

    if rank == 1:
        return f"{_ordinal(rank)} in {division}, leads the division"

    gb_text = f"{games_back:.1f} GB" if games_back is not None else "GB unknown"

    if wc_rank is not None and wc_gb is not None:
        if wc_leading:
            wc_text = f"leads the {_ordinal(wc_rank)} wild card by {wc_gb:.1f}"
        else:
            wc_text = f"{wc_gb:.1f} back of the last wild card"
        return f"{_ordinal(rank)} in {division}, {gb_text}, {wc_text}"

    return f"{_ordinal(rank)} in {division}, {gb_text}"


_STANDING_FIELDS = (
    "team_id", "team_abbrev", "team_name", "league_id", "division_id",
    "division_name", "season", "games_played", "wins", "losses", "win_pct",
    "division_rank", "games_back", "wildcard_rank", "wildcard_games_back",
    "wildcard_leading", "streak_code", "clinched", "division_leader",
)


def _empty_standing(iso, team, reason) -> dict:
    empty = {field: None for field in _STANDING_FIELDS}
    empty.update({"date": iso, "team": team, "found": False, "reason": reason,
                  "playoff_context": None})
    return empty


def team_standing(target_date, team, index=None, path=DEFAULT_STORE) -> dict:
    """Playoff context for one team on one date. The per-team accessor.

    Pass `index` (from a prior `read()` call) to reuse one in-memory index
    across many lookups -- e.g. the API layer reads the store once per
    request batch rather than once per team. Omitting it re-reads the whole
    store from `path` on every call, which is correct but slower.

    Absent-safe by construction: a date this store has no snapshot for, or a
    team not found within that date's snapshot, comes back `found: False`
    with a `reason` and every typed field `None` -- never a fabricated 0 or
    a nearby date's numbers substituted for the one asked for (point-in-time
    correctness is the hard rule this project runs on; see CLAUDE.md).
    """
    iso = _to_date(target_date).isoformat()
    key = _normalize_team(team)
    if index is None:
        index = read(path)

    by_team = index.get(iso)
    if by_team is None:
        return _empty_standing(iso, team, f"no standings snapshot stored for {iso}")

    row = by_team.get(key)
    if row is None:
        return _empty_standing(
            iso, team, f"team {team!r} not found in the {iso} snapshot")

    result = {field: row.get(field) for field in _STANDING_FIELDS}
    result.update({"date": iso, "team": row.get("team_abbrev") or team, "found": True,
                   "reason": None, "playoff_context": playoff_context_line(row)})
    return result
