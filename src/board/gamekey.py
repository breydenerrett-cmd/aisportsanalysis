"""The event_id <-> game_pk resolver: S1 of the vertical-slice plan.

WHY THIS EXISTS
----------------
`src.board.l1`'s three source stores key every row on the odds provider's
own `event_id` -- an opaque hash. The forward stores `src.core.asof.as_of`
reads (umpire/lineup/probable watches, weather, boxscores) key on the MLB
numeric `game_pk` instead. Nothing joined the two id spaces for a game that
has not yet had a final boxscore written -- see `src.engine.glue`'s module
docstring for the gap this module closes (docs/CHECKPOINT_PHASE0_2026-09-03.md
S1).

The join is: normalize both sides' team names to one canonical abbreviation
(reusing the SAME resolvers `src.pipeline.snapshots._canonical_club` already
composes for the identical odds-feed-name vs project-abbreviation problem,
rather than inventing a second mapping -- see `_team_key` below), then match
an odds event's (away, home, commence_time) against the MLB schedule for
that date. A doubleheader means two schedule games share the same team pair
on the same date; the nearest `commence_time` wins, and the row is stamped
`ambiguous: True` with every candidate recorded -- never a silent guess.

THE STORE
---------
`data/processed/event_game_map.jsonl` is append-only, one row per
`event_id`, holding the evidence used to resolve it (or why it could not
be): teams, both sides' commence_time, source, resolved_utc, and the
ambiguity/candidate detail. Re-running `build_map_for_date` over an
unchanged slate skips every `event_id` already in the store (idempotent,
same discipline as `src.board.l1.run`); pass `force=True` to re-resolve
everything for a date, e.g. after a schedule correction.

NO NETWORK IN THIS MODULE'S OWN CODE PATH BY DEFAULT DURING TESTS
-------------------------------------------------------------------
`schedule_fn` defaults to `src.providers.mlb.fetch_games` (the real, free,
keyless MLB Stats API) but is always a parameter -- every function here
takes it explicitly so tests inject a fixture callable and never touch the
network.
"""

from __future__ import annotations

import json
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping

from src.core.asof import game_pk_key
from src.data import parks
from src.paths import processed_path
from src.pipeline import slate as slate_mod
from src.pipeline.snapshots import official_date
from src.providers import mlb

DEFAULT_MAP_PATH = processed_path("event_game_map.jsonl")

# Every store this module reads odds events out of, to discover what needs
# resolving for a date. Same three stores src.board.l1 backfills from, plus
# f5_close.jsonl for completeness (an event that only ever appears in the
# first-five close store would otherwise never be offered for resolution).
DEFAULT_EVENT_SOURCES = (
    processed_path("odds_multibook.jsonl"),
    processed_path("odds_snapshots.jsonl"),
    processed_path("f5_close.jsonl"),
)


class GameKeyError(ValueError):
    """Raised for a malformed request -- never for an honest non-match,
    which is a resolved-False row, not an exception."""


# ---------------------------------------------------------------------------
# Team-name normalization -- reuses the existing resolvers, does not add one
# ---------------------------------------------------------------------------

def _team_key(name: str | None) -> str | None:
    """One team field -> this project's canonical abbreviation, or None.

    Two-step, same composition `src.pipeline.snapshots._canonical_club`
    already uses for the identical odds-feed-name vs schedule-abbreviation
    join (that function's docstring: "reuses the same pair of resolvers
    ... rather than adding a second team-name mapping"):

      1. `slate.team_abbrev_from_name` -- resolves a full club name
         ('Boston Red Sox') to an abbreviation. Returns None for anything
         that is not a recognized full name (already an abbreviation, or
         unrecognized).
      2. `parks.canonical_team` -- folds abbreviation spelling variants
         (AZ/ARI, ATH/OAK, ...) onto one key. Applied to step 1's result
         when it matched, otherwise to the input as given.

    Unlike `_canonical_club`, an unrecognized input returns None here
    rather than an uppercased pass-through: this module's matching is a
    strict equality join, and two different unrecognized inputs must never
    accidentally compare equal to each other (a shared uppercase fallback
    would silently fold two unrelated unmatched teams together) or to a
    real abbreviation that happens to share the same spelling.
    """
    if not isinstance(name, str) or not name.strip():
        return None
    abbrev = slate_mod.team_abbrev_from_name(name)
    candidate = abbrev if abbrev else name.strip().upper()
    canonical = parks.canonical_team(candidate)
    # Only trust a normalization that actually names a real park -- every
    # genuine MLB abbreviation has one. This is what keeps an unrecognized
    # input from silently comparing equal to another unrecognized input.
    if canonical not in parks.PARKS:
        return None
    return canonical


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

def _parse_utc(value: str) -> datetime:
    text = value.replace("Z", "+00:00") if value.endswith("Z") else value
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _now_iso(now: datetime | None = None) -> str:
    return _iso(now or datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Reading source stores for events needing resolution
# ---------------------------------------------------------------------------

def _read_jsonl(path: Path) -> Iterable[dict]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def events_for_date(date_str: str, *,
                     sources: Iterable[Path | str] | None = None,
                     sport: str = "mlb"
                     ) -> dict[str, dict]:
    """`{event_id: {home_team, away_team, commence_time}}` for every event
    whose `commence_time` falls on `date_str` (official ET date, via
    `official_date` -- the same conversion every other store in this
    project uses, so a 20:10 ET Saturday night game is filed under Saturday
    here too). Filters to rows for the given sport: a row's sport field
    (row.get("sport")) defaults to "mlb" when absent. Pass sport=None to
    include all rows regardless of sport. The first row seen for an
    `event_id` wins; every row for the same event carries the same identity
    fields by construction (they are facts about the event, not the
    observation)."""
    paths = list(sources) if sources is not None else list(DEFAULT_EVENT_SOURCES)
    out: dict[str, dict] = {}
    for path in paths:
        for row in _read_jsonl(Path(path)):
            event_id = row.get("event_id")
            commence_time = row.get("commence_time")
            home_team = row.get("home_team")
            away_team = row.get("away_team")
            if not event_id or not commence_time or not home_team or not away_team:
                continue
            if sport is not None:
                row_sport = row.get("sport") or "mlb"
                if row_sport != sport:
                    continue
            if official_date(commence_time) != date_str:
                continue
            out.setdefault(str(event_id), {
                "home_team": home_team, "away_team": away_team,
                "commence_time": commence_time,
            })
    return out


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

ScheduleFn = Callable[[str], list]


def resolve_event(event_id: str, home_team: str, away_team: str,
                   commence_time: str, *,
                   schedule_fn: ScheduleFn = mlb.fetch_games,
                   source: str = "mlb_schedule",
                   now: datetime | None = None,
                   sport: str = "mlb",
                   team_key_fn: Callable[[str], str | None] | None = None) -> dict:
    """Resolve one odds event to an MLB `game_pk` or non-MLB `game_id`, or explain why not.

    Checks the event's own official date AND the calendar days either side
    of it (a commence_time near midnight ET can round to the "wrong"
    official date under a naive UTC read) so a genuine schedule game is
    never missed only because the boundary date picked was one day off.

    A doubleheader (same two teams, same official date) is every schedule
    game whose (away, home) matches; the CLOSEST to the odds event's own
    `commence_time` wins, and `ambiguous=True` is stamped with every
    candidate recorded -- this function never silently picks one and hides
    the others.

    For sport "mlb", schedule_fn is ignored and defaults to mlb.fetch_games;
    team_key_fn is ignored and uses the built-in _team_key. For other sports,
    schedule_fn must be provided (or sourced from the registry) and must return
    SportSpec-shaped rows [{"game_id", "away", "home", "start_utc"}]; team_key_fn
    defaults to src.sports.spec(sport).team_abbrev_fn when that is not None, else
    a normalized full-name comparison like _team_key.
    """
    resolved_utc = _now_iso(now)
    base = {
        "event_id": event_id, "home_team": home_team, "away_team": away_team,
        "commence_time": commence_time, "source": source,
        "resolved_utc": resolved_utc,
    }

    # For non-MLB sports, lazy-import the registry and extract team_key_fn if needed.
    if sport != "mlb" and team_key_fn is None:
        from src import sports as sports_mod
        try:
            spec_obj = sports_mod.spec(sport)
            team_key_fn = spec_obj.team_abbrev_fn
        except sports_mod.UnknownSport:
            team_key_fn = None

    # Normalize team names for matching. For MLB use _team_key; for non-MLB
    # use team_key_fn if provided, else fall back to _team_key.
    if team_key_fn:
        away_key = team_key_fn(away_team)
        home_key = team_key_fn(home_team)
    else:
        away_key = _team_key(away_team)
        home_key = _team_key(home_team)

    try:
        commence_dt = _parse_utc(commence_time) if commence_time else None
    except ValueError:
        commence_dt = None

    if not away_key or not home_key or commence_dt is None:
        # For non-MLB sports, add sport and game_id=None instead of game_pk.
        result = {
            **base, "resolved": False, "ambiguous": False,
            "candidates": [], "schedule_commence_time": None,
            "reason": (
                f"could not normalize team names or commence_time "
                f"(away={away_team!r} home={home_team!r} "
                f"commence_time={commence_time!r})"),
        }
        if sport != "mlb":
            result["sport"] = sport
            result["game_id"] = None
            result["game_pk"] = None
        else:
            result["game_pk"] = None
        return result

    # Helper to extract the correct field names based on sport.
    def _get_schedule_fields(game: dict) -> tuple:
        """Extract (away_team_val, home_team_val, start_time_val, game_id_val) from schedule row."""
        if sport == "mlb":
            return (game.get("away_team"), game.get("home_team"),
                    game.get("start_time_utc"), game.get("game_pk"))
        else:
            # Non-MLB sports use SportSpec shape: away, home, start_utc, game_id
            return (game.get("away"), game.get("home"),
                    game.get("start_utc"), game.get("game_id"))

    def _matching_games(day: str) -> list[dict]:
        out = []
        for game in schedule_fn(day):
            g_away_val, g_home_val, _, game_id_val = _get_schedule_fields(game)
            # Normalize the schedule row's team names using team_key_fn
            if team_key_fn:
                g_away = team_key_fn(g_away_val)
                g_home = team_key_fn(g_home_val)
            else:
                g_away = _team_key(g_away_val)
                g_home = _team_key(g_home_val)
            if g_away != away_key or g_home != home_key:
                continue
            if game_id_val is None:
                continue
            out.append(game)
        return out

    center_date = official_date(commence_time)
    center_dt = _date.fromisoformat(center_date)

    # The exact official date is checked ALONE first: two different games
    # against the SAME opponent on consecutive nights (an ordinary 3-game
    # series) must never be pooled into one candidate set, or every game of
    # a normal series would be mis-flagged `ambiguous` against the others.
    # A genuine doubleheader is two schedule games matching on THIS SAME
    # date, which is exactly what this single-date query captures.
    candidates = _matching_games(center_date)

    # For MLB, keep track of game_pks using canonical form.
    if sport == "mlb":
        seen_pks = {game_pk_key(g["game_pk"]) for g in candidates}
    else:
        # For non-MLB, track game_ids (which are already strings).
        seen_ids = {g.get("game_id") for g in candidates}

    # Only widen to the calendar day either side when the exact date found
    # NOTHING -- a commence_time within a few hours of midnight ET can round
    # to the "wrong" official date under a naive UTC read, and this is the
    # narrow fallback that catches a genuine schedule game without ever
    # pulling in an unrelated night of the same series.
    if not candidates:
        for day in ((center_dt - timedelta(days=1)).isoformat(),
                    (center_dt + timedelta(days=1)).isoformat()):
            for game in _matching_games(day):
                if sport == "mlb":
                    pk = game_pk_key(game["game_pk"])
                    if pk in seen_pks:
                        continue
                    seen_pks.add(pk)
                else:
                    game_id = game.get("game_id")
                    if game_id in seen_ids:
                        continue
                    seen_ids.add(game_id)
                candidates.append(game)

    if not candidates:
        result = {
            **base, "resolved": False, "ambiguous": False,
            "candidates": [], "schedule_commence_time": None,
            "reason": (
                f"no schedule game matched {away_key}@{home_key} within a "
                f"day of {commence_time}"),
        }
        if sport != "mlb":
            result["sport"] = sport
            result["game_id"] = None
            result["game_pk"] = None
        else:
            result["game_pk"] = None
        return result

    def _delta(game: dict) -> float:
        _, _, start, _ = _get_schedule_fields(game)
        if not start:
            return float("inf")
        try:
            return abs((_parse_utc(start) - commence_dt).total_seconds())
        except ValueError:
            return float("inf")

    candidates.sort(key=_delta)
    best = candidates[0]
    ambiguous = len(candidates) > 1
    reason = None
    if ambiguous:
        if sport == "mlb":
            reason = (
                f"{len(candidates)} schedule games matched {away_key}@{home_key} "
                f"(doubleheader or scheduling anomaly) -- picked game_pk "
                f"{best.get('game_pk')} by nearest commence_time")
        else:
            reason = (
                f"{len(candidates)} schedule games matched {away_key}@{home_key} "
                f"(doubleheader or scheduling anomaly) -- picked game_id "
                f"{best.get('game_id')} by nearest commence_time")

    # Build the result based on sport.
    if sport == "mlb":
        return {
            **base,
            # Canonical string form (see `src.core.asof.game_pk_key`) -- the
            # ONE point this store's `game_pk` column is ever produced, so
            # every downstream reader (`game_pk_for_event`, `src.board.l1`,
            # `src.engine.glue`) receives the same type without having to
            # coerce a second time.
            "game_pk": game_pk_key(best.get("game_pk")),
            "resolved": True,
            "ambiguous": ambiguous,
            "candidates": (
                [{"game_pk": game_pk_key(c.get("game_pk")),
                  "start_time_utc": c.get("start_time_utc")} for c in candidates]
                if ambiguous else []),
            "schedule_commence_time": best.get("start_time_utc"),
            "reason": reason,
        }
    else:
        # Non-MLB sport: return game_id and sport fields.
        _, _, start_time, game_id = _get_schedule_fields(best)
        return {
            **base,
            "sport": sport,
            "game_id": game_id,
            "game_pk": None,
            "resolved": True,
            "ambiguous": ambiguous,
            "candidates": (
                [{"game_id": c.get("game_id"),
                  "start_utc": _get_schedule_fields(c)[2]} for c in candidates]
                if ambiguous else []),
            "schedule_commence_time": start_time,
            "reason": reason,
        }


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def load_map(path: Path | str = DEFAULT_MAP_PATH) -> dict[str, dict]:
    """Every `event_id -> resolution row` in the store, last write wins per
    `event_id` (a `force` re-resolve appends a corrected row rather than
    editing the old one -- append-only, same discipline as ledger.py's
    settlements). Missing file is an empty map, not an error."""
    out: dict[str, dict] = {}
    for row in _read_jsonl(Path(path)):
        event_id = row.get("event_id")
        if event_id is not None:
            out[str(event_id)] = row
    return out


def game_pk_for_event(event_id: str | int | None,
                       index: Mapping[str, dict] | None) -> str | None:
    """The best-known `game_pk` for `event_id`, in the canonical string form
    (`src.core.asof.game_pk_key`), from an already-loaded map `index` (see
    `load_map`), or None when the event is absent from the map or was
    resolved as unresolvable. An ambiguous row still returns its
    nearest-commence_time best guess -- ambiguity is recorded on the row for
    a caller that cares, not withheld from the one that just wants a pk.

    Coerces on READ, not just on write: `resolve_event` has written the
    canonical string since S1's game-key normalization, but this store is
    append-only (module docstring), so a row written before that change
    still holds a native JSON int on disk. Normalizing here means every
    caller gets the same type regardless of which of the two eras wrote the
    row it happens to read.
    """
    if not index or event_id is None:
        return None
    entry = index.get(str(event_id))
    if not entry:
        return None
    return game_pk_key(entry.get("game_pk"))


def game_id_for_event(event_id: str | int | None,
                       mapping: Mapping[str, dict] | None = None,
                       *, map_path: Path | str = DEFAULT_MAP_PATH) -> str | None:
    """The best-known `game_id` for `event_id` (for non-MLB sports), or `game_pk`
    for MLB, from an already-loaded map `mapping` or by loading from `map_path`.
    Returns None when the event is absent from the map or was resolved as
    unresolvable. An ambiguous row still returns its nearest-commence_time best
    guess -- ambiguity is recorded on the row for a caller that cares.

    For non-MLB sports, returns the "game_id" field. For MLB or when "game_id"
    is not present, returns the "game_pk" field (in canonical string form).
    """
    if event_id is None:
        return None

    # Use provided mapping, or load from map_path
    index = mapping
    if index is None:
        index = load_map(map_path)

    if not index:
        return None

    entry = index.get(str(event_id))
    if not entry:
        return None

    # Return game_id if present and not None, otherwise return game_pk
    game_id = entry.get("game_id")
    if game_id is not None:
        return game_id
    return game_pk_key(entry.get("game_pk"))


def _append_rows(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def build_map_for_date(date_str: str, *,
                        map_path: Path | str = DEFAULT_MAP_PATH,
                        event_sources: Iterable[Path | str] | None = None,
                        schedule_fn: ScheduleFn | None = None,
                        now: datetime | None = None,
                        force: bool = False,
                        sport: str = "mlb") -> dict:
    """Resolve every odds event captured for `date_str` and append new rows
    to `map_path`. Idempotent: an `event_id` already in the map is skipped
    unless `force=True`. Returns resolved/ambiguous/unresolved counts.

    For sport "mlb", schedule_fn defaults to mlb.fetch_games if not provided.
    For other sports, schedule_fn must be provided explicitly, or None is used
    (which will raise a GameKeyError when resolve_event tries to call it).
    When schedule_fn is None for a non-MLB sport, it can be sourced from the
    registry via src.sports.spec(sport).schedule_fn, but that must be done
    by the caller before calling this function, or the caller must provide
    an explicit schedule_fn argument.
    """
    # Default schedule_fn for MLB
    if schedule_fn is None and sport == "mlb":
        schedule_fn = mlb.fetch_games
    elif schedule_fn is None and sport != "mlb":
        # Try to get it from the registry
        from src import sports as sports_mod
        try:
            spec_obj = sports_mod.spec(sport)
            schedule_fn = spec_obj.schedule_fn
        except sports_mod.UnknownSport as e:
            raise GameKeyError(str(e))
        if schedule_fn is None:
            raise GameKeyError(
                f"schedule_fn is None for sport {sport!r}; "
                f"the sport registry does not have a schedule function yet")

    events = events_for_date(date_str, sources=event_sources, sport=sport)
    existing = load_map(map_path)
    report = {
        "date": date_str, "candidates": len(events),
        "resolved": 0, "ambiguous": 0, "unresolved": 0,
        "skipped_already_mapped": 0, "rows_written": 0,
        "map_path": str(map_path),
    }
    new_rows = []
    for event_id in sorted(events):
        if event_id in existing and not force:
            report["skipped_already_mapped"] += 1
            continue
        meta = events[event_id]
        entry = resolve_event(
            event_id, meta["home_team"], meta["away_team"],
            meta["commence_time"], schedule_fn=schedule_fn, now=now, sport=sport)
        if not entry["resolved"]:
            report["unresolved"] += 1
        elif entry["ambiguous"]:
            report["ambiguous"] += 1
        else:
            report["resolved"] += 1
        new_rows.append(entry)
    _append_rows(Path(map_path), new_rows)
    report["rows_written"] = len(new_rows)
    return report


def build_map_for_range(start_date: str, end_date: str, *,
                         map_path: Path | str = DEFAULT_MAP_PATH,
                         event_sources: Iterable[Path | str] | None = None,
                         schedule_fn: ScheduleFn | None = None,
                         now: datetime | None = None,
                         force: bool = False,
                         sport: str = "mlb") -> dict:
    """`build_map_for_date` over every calendar date from `start_date` to
    `end_date` inclusive, merging the per-date reports into one totals dict
    plus a `by_date` breakdown."""
    if end_date < start_date:
        raise GameKeyError(
            f"end_date {end_date!r} is before start_date {start_date!r}")

    start = _date.fromisoformat(start_date)
    end = _date.fromisoformat(end_date)
    totals = {
        "start_date": start_date, "end_date": end_date,
        "candidates": 0, "resolved": 0, "ambiguous": 0, "unresolved": 0,
        "skipped_already_mapped": 0, "rows_written": 0,
        "map_path": str(map_path), "by_date": {},
    }
    day = start
    while day <= end:
        day_str = day.isoformat()
        report = build_map_for_date(
            day_str, map_path=map_path, event_sources=event_sources,
            schedule_fn=schedule_fn, now=now, force=force, sport=sport)
        totals["by_date"][day_str] = report
        for key in ("candidates", "resolved", "ambiguous", "unresolved",
                    "skipped_already_mapped", "rows_written"):
            totals[key] += report[key]
        day += timedelta(days=1)
    return totals
