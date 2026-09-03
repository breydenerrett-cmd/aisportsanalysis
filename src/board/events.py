"""InformationEvent: free-environment facts keyed by game_pk, append-only.

WHY THIS EXISTS
----------------
docs/planning/design-data-first.md section 2.3 and
docs/ARCHITECTURE_BETTING_ENGINE.md section 6/8 (packet W6, "free
environment") call for one record shape -- an InformationEvent -- for
everything that is not a price: a lineup posting, a probable-pitcher
change, an umpire assignment, a weather-forecast update, a roster
transaction, a final boxscore. Six existing stores already capture these
facts in six different shapes (`data/watch/*.jsonl`,
`data/processed/weather_forecast.jsonl`,
`data/processed/boxscores_2026.jsonl`); this module does not replace any of
them -- it is a pure, deterministic PROJECTION over the rows they already
hold, run as its own pass with no new network calls, into one append-only
store keyed by `game_pk` with an honest `observed_utc`, so `src.core.asof`
can read them like every other forward store.

THE ONE GAP THIS CLOSES
------------------------
`src/core/asof.py`'s `transactions_watch` StoreSpec has `game_key_of=lambda
r: None` with the comment "not game-keyed, never matches" -- transactions
carry a `team` abbreviation and a `date`, not a `game_pk`. This module maps
transaction rows to a `game_pk` via `(team, date)` against
`data/processed/boxscores_2026.jsonl` (the only store on disk that already
pairs a team with both a date and a game_pk), so a roster move becomes
reachable per game for the first time. A transaction whose team+date has no
boxscore row (e.g. an off-day move, or a game not yet finalized) is emitted
with `game_pk: None` and excluded from the store -- absence, never a guess.

IDS AND IDEMPOTENCY
--------------------
Each event's id is a stable hash of its (event_kind, game_pk, subject, a
kind-specific dedup key, observed_utc) tuple, so re-running the emitters over
the same source rows produces byte-identical ids and `write_events` is a
safe upsert-by-id: appending the same event twice never duplicates a line.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.data.labels import team_name as _team_full_name
from src.paths import data_path, processed_path

STORE_PATH = processed_path("information_events.jsonl")

LINEUP_POSTED = "lineup_posted"
LINEUP_CHANGED = "lineup_changed"
PROBABLE_CHANGED = "probable_changed"
UMPIRE_ASSIGNED = "umpire_assigned"
WEATHER_FORECAST_UPDATED = "weather_forecast_updated"
TRANSACTION_RELEVANT = "transaction_relevant"
BOXSCORE_FINAL = "boxscore_final"

EVENT_KINDS = frozenset({
    LINEUP_POSTED, LINEUP_CHANGED, PROBABLE_CHANGED, UMPIRE_ASSIGNED,
    WEATHER_FORECAST_UPDATED, TRANSACTION_RELEVANT, BOXSCORE_FINAL,
})

GRADE_A = "A"  # observed via a live poll/capture -- observed_utc IS known_at
GRADE_D = "D"  # no honest known_at could be reconstructed
_GRADES = frozenset("ABCD")

# Weather is polled repeatedly and mostly repeats itself; only a change past
# this material threshold is worth an event (docs/COLLECTION_POLICY.md's
# "maximize research options per credit" applies equally to disk noise).
_WEATHER_TEMP_THRESHOLD_F = 5.0
_WEATHER_WIND_THRESHOLD_MPH = 5.0
_WEATHER_PRECIP_THRESHOLD_PCT = 15.0


class EventError(ValueError):
    """A malformed InformationEvent was about to be constructed."""


@dataclass(frozen=True)
class InformationEvent:
    event_kind: str
    game_pk: str
    subject: str            # what changed: "home_lineup", "TOR", "home_plate", ...
    payload: Mapping[str, Any]
    observed_utc: str       # when this project captured the underlying row
    source: str             # the store this was projected from
    known_at_grade: str = GRADE_A
    dedup_key: str = ""      # kind-specific extra key folded into the id
    event_id: str = field(default="")

    def __post_init__(self) -> None:
        if self.event_kind not in EVENT_KINDS:
            raise EventError(f"unknown event_kind {self.event_kind!r}")
        if not self.game_pk:
            raise EventError("game_pk is required")
        if self.known_at_grade not in _GRADES:
            raise EventError(f"bad known_at_grade {self.known_at_grade!r}")
        if not self.event_id:
            object.__setattr__(self, "event_id", _make_id(self))

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_kind": self.event_kind,
            "game_pk": self.game_pk,
            "subject": self.subject,
            "payload": dict(self.payload),
            "observed_utc": self.observed_utc,
            "source": self.source,
            "known_at_grade": self.known_at_grade,
        }


def _make_id(ev: "InformationEvent") -> str:
    """A stable id from identity fields only -- never the payload -- so a
    row whose payload is re-derived identically from the same source hashes
    the same, and re-running an emitter is always a no-op append.
    """
    basis = "|".join([
        ev.event_kind, str(ev.game_pk), ev.subject, ev.dedup_key,
        ev.observed_utc,
    ])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


# ---------------------------------------------------------------------------
# Store I/O
# ---------------------------------------------------------------------------

def _iter_rows(path: Path) -> Iterable[dict]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def read_events(path: Path | None = None) -> list[dict]:
    """Every event row currently on disk, in file order."""
    return list(_iter_rows(path or STORE_PATH))


def existing_ids(path: Path | None = None) -> set[str]:
    return {row["event_id"] for row in _iter_rows(path or STORE_PATH)
            if row.get("event_id")}


def write_events(events: Iterable[InformationEvent],
                  path: Path | None = None) -> int:
    """Append new events, skipping any id already on disk. Returns the count
    of rows actually written. Append-only: never rewrites an existing line.
    """
    store_path = path or STORE_PATH
    known = existing_ids(store_path)
    new_rows = []
    seen_this_run: set[str] = set()
    for ev in events:
        if ev.event_id in known or ev.event_id in seen_this_run:
            continue
        seen_this_run.add(ev.event_id)
        new_rows.append(ev.to_dict())
    if not new_rows:
        return 0
    store_path.parent.mkdir(parents=True, exist_ok=True)
    with store_path.open("a", encoding="utf-8") as fh:
        for row in new_rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    return len(new_rows)


# ---------------------------------------------------------------------------
# Watch-store readers (mirrors src/core/asof.py's _pk / _obs_utc helpers)
# ---------------------------------------------------------------------------

def _pk(row: dict) -> str | None:
    v = row.get("game_pk")
    return str(v) if v is not None else None


def _obs(row: dict) -> str | None:
    return row.get("observed_utc") or row.get("fetched_utc")


def _by_game(rows: Iterable[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for row in rows:
        if row.get("poll"):
            continue
        key = _pk(row)
        if key is None:
            continue
        out.setdefault(key, []).append(row)
    for rows_for_game in out.values():
        rows_for_game.sort(key=lambda r: _obs(r) or "")
    return out


# ---------------------------------------------------------------------------
# Emitters -- each a pure diff over one existing store's rows
# ---------------------------------------------------------------------------

def lineup_events(rows: Iterable[dict] | None = None) -> list[InformationEvent]:
    """lineup_posted (first sighting of a side's batting order) and
    lineup_changed (a posted lineup's personnel changed) from
    `data/watch/lineups_watch.jsonl`.
    """
    if rows is None:
        rows = _iter_rows(data_path("watch", "lineups_watch.jsonl"))
    out: list[InformationEvent] = []
    for game_pk, game_rows in _by_game(rows).items():
        prev: dict[str, tuple] = {}
        for row in game_rows:
            observed = _obs(row)
            if observed is None:
                continue
            for side in ("away", "home"):
                new = tuple(row.get(f"{side}_lineup") or [])
                old = prev.get(side)
                if not new:
                    continue
                if old is None:
                    out.append(InformationEvent(
                        event_kind=LINEUP_POSTED,
                        game_pk=game_pk,
                        subject=f"{side}_lineup",
                        payload={"side": side, "lineup": list(new)},
                        observed_utc=observed,
                        source="lineups_watch",
                        dedup_key=f"posted:{side}",
                    ))
                elif new != old:
                    out.append(InformationEvent(
                        event_kind=LINEUP_CHANGED,
                        game_pk=game_pk,
                        subject=f"{side}_lineup",
                        payload={"side": side, "from": list(old),
                                 "to": list(new)},
                        observed_utc=observed,
                        source="lineups_watch",
                        dedup_key=f"changed:{side}:{observed}",
                    ))
                prev[side] = new
    return out


def probable_events(rows: Iterable[dict] | None = None) -> list[InformationEvent]:
    """probable_changed: a listed starting pitcher changed from one poll to
    the next. From `data/watch/probables_watch.jsonl`.
    """
    if rows is None:
        rows = _iter_rows(data_path("watch", "probables_watch.jsonl"))
    out: list[InformationEvent] = []
    for game_pk, game_rows in _by_game(rows).items():
        prev: dict[str, Any] = {}
        for row in game_rows:
            observed = _obs(row)
            if observed is None:
                continue
            for side in ("away", "home"):
                new = row.get(f"{side}_probable_id")
                old = prev.get(side, "__unset__")
                if new is not None and old not in ("__unset__", None, new):
                    out.append(InformationEvent(
                        event_kind=PROBABLE_CHANGED,
                        game_pk=game_pk,
                        subject=f"{side}_probable",
                        payload={"side": side, "from": old, "to": new},
                        observed_utc=observed,
                        source="probables_watch",
                        dedup_key=f"{side}:{observed}",
                    ))
                if new is not None:
                    prev[side] = new
    return out


def umpire_events(rows: Iterable[dict] | None = None) -> list[InformationEvent]:
    """umpire_assigned: the home-plate umpire is revealed for a game. From
    `data/watch/umpires_watch.jsonl`.
    """
    if rows is None:
        rows = _iter_rows(data_path("watch", "umpires_watch.jsonl"))
    out: list[InformationEvent] = []
    seen: set[str] = set()
    for row in rows:
        if row.get("poll"):
            continue
        game_pk = _pk(row)
        observed = _obs(row)
        ump = row.get("home_plate_umpire")
        if game_pk is None or observed is None or not ump:
            continue
        key = f"{game_pk}:{ump}"
        if key in seen:
            continue
        seen.add(key)
        out.append(InformationEvent(
            event_kind=UMPIRE_ASSIGNED,
            game_pk=game_pk,
            subject="home_plate_umpire",
            payload={"home_plate_umpire": ump, "crew": row.get("crew")},
            observed_utc=observed,
            source="umpires_watch",
            dedup_key=ump,
        ))
    return out


def weather_events(rows: Iterable[dict] | None = None) -> list[InformationEvent]:
    """weather_forecast_updated: a forecast field moved past a material
    threshold since the last forecast for that game. From
    `data/processed/weather_forecast.jsonl`.
    """
    if rows is None:
        rows = _iter_rows(processed_path("weather_forecast.jsonl"))
    thresholds = {
        "temp_f": _WEATHER_TEMP_THRESHOLD_F,
        "wind_mph": _WEATHER_WIND_THRESHOLD_MPH,
        "precip_probability_pct": _WEATHER_PRECIP_THRESHOLD_PCT,
    }
    out: list[InformationEvent] = []
    for game_pk, game_rows in _by_game(rows).items():
        prev: dict[str, float] = {}
        for row in game_rows:
            observed = _obs(row)
            if observed is None:
                continue
            moved: dict[str, Any] = {}
            for field_name, threshold in thresholds.items():
                new_v = row.get(field_name)
                if new_v is None:
                    continue
                old_v = prev.get(field_name)
                if old_v is None or abs(new_v - old_v) >= threshold:
                    moved[field_name] = {"from": old_v, "to": new_v}
                prev[field_name] = new_v
            if moved:
                out.append(InformationEvent(
                    event_kind=WEATHER_FORECAST_UPDATED,
                    game_pk=game_pk,
                    subject="forecast",
                    payload=moved,
                    observed_utc=observed,
                    source="weather_forecast",
                    dedup_key=observed,
                ))
    return out


def boxscore_events(rows: Iterable[dict] | None = None) -> list[InformationEvent]:
    """boxscore_final: one event per game the first time a boxscore row for
    it appears. From `data/processed/boxscores_2026.jsonl` (and any other
    season file passed in explicitly).
    """
    if rows is None:
        rows = _iter_rows(processed_path("boxscores_2026.jsonl"))
    out: list[InformationEvent] = []
    seen: set[str] = set()
    for row in rows:
        game_pk = _pk(row)
        observed = _obs(row)
        if game_pk is None or observed is None or game_pk in seen:
            continue
        seen.add(game_pk)
        out.append(InformationEvent(
            event_kind=BOXSCORE_FINAL,
            game_pk=game_pk,
            subject="boxscore",
            payload={"date": row.get("date")},
            observed_utc=observed,
            source="boxscores",
            dedup_key="final",
        ))
    return out


def _boxscore_team_date_index(rows: Iterable[dict]) -> dict[tuple[str, str], str]:
    """(canonical full team name, date) -> game_pk, built once from
    boxscore rows (the only store on disk pairing a team_name with both a
    date and a game_pk). First game_pk wins for a given key; a doubleheader
    sharing (team, date) cannot be disambiguated from this store alone, so
    later rows for an already-mapped key are left alone rather than guessed.
    """
    index: dict[tuple[str, str], str] = {}
    for row in rows:
        game_pk = _pk(row)
        date = row.get("date")
        team = row.get("team_name")
        if not (game_pk and date and team):
            continue
        key = (team, date)
        index.setdefault(key, game_pk)
    return index


def transaction_events(
        rows: Iterable[dict] | None = None,
        boxscore_rows: Iterable[dict] | None = None,
) -> list[InformationEvent]:
    """transaction_relevant: a roster move mapped to the game it affects, via
    (team, date) against the boxscore store -- transactions carry a team
    abbreviation and a date, never a game_pk (src/core/asof.py's
    `transactions_watch` StoreSpec comment: "not game-keyed"). A move whose
    team+date has no matching boxscore row is skipped, never guessed.
    """
    if rows is None:
        rows = _iter_rows(data_path("watch", "transactions_watch.jsonl"))
    if boxscore_rows is None:
        boxscore_rows = _iter_rows(processed_path("boxscores_2026.jsonl"))
    index = _boxscore_team_date_index(boxscore_rows)

    out: list[InformationEvent] = []
    for row in rows:
        if row.get("poll") or "transaction_id" not in row:
            continue
        team = row.get("team")
        date = row.get("date")
        observed = row.get("first_seen_utc")
        if not (team and date and observed):
            continue
        full_name = _team_full_name(team)
        game_pk = index.get((full_name, date))
        if game_pk is None:
            continue  # no game for this team on this date in the store yet
        out.append(InformationEvent(
            event_kind=TRANSACTION_RELEVANT,
            game_pk=game_pk,
            subject=team,
            payload={
                "transaction_id": row.get("transaction_id"),
                "player": row.get("player"),
                "player_id": row.get("player_id"),
                "category": row.get("category"),
                "team": team,
                "date": date,
            },
            observed_utc=observed,
            source="transactions_watch",
            dedup_key=str(row.get("transaction_id")),
        ))
    return out


def all_events() -> list[InformationEvent]:
    """Every emitter run once over the real data/ tree, no network calls."""
    events: list[InformationEvent] = []
    events.extend(lineup_events())
    events.extend(probable_events())
    events.extend(umpire_events())
    events.extend(weather_events())
    events.extend(boxscore_events())
    events.extend(transaction_events())
    return events


def run(since: str | None = None, path: Path | None = None) -> dict:
    """Run every emitter and append new events to the store. `since` (an
    ISO date, e.g. "2026-09-01") filters by `observed_utc` date-prefix so a
    caller can bound how much of a large store gets re-scanned; it never
    excludes an event that was already written, since `write_events` dedupes
    by id regardless.
    """
    events = all_events()
    if since:
        events = [e for e in events if e.observed_utc >= since]
    counts: dict[str, int] = {}
    for ev in events:
        counts[ev.event_kind] = counts.get(ev.event_kind, 0) + 1
    written = write_events(events, path=path)
    return {"seen": len(events), "written": written, "by_kind": counts}
