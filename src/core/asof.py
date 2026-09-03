"""The stop-at-T reader: what an honest decision-time snapshot looked like.

WHY THIS EXISTS
----------------
Every other point-in-time discipline in this codebase (src/evolab/replay.py's
`iter_instants_through`, src/board/record.py's `known_at`/`known_at_grade`)
answers "what was the price board at T". This module answers the wider
question a replay/backtest also needs: what did the FORWARD stores this
project actually captures -- umpire crews, transactions, lineups, probable
pitchers, weather, boxscores -- look like from the vantage point of T, for one
game. It is the read side of guard F4/F1 (docs/ARCHITECTURE_BETTING_ENGINE.md
section 4): nothing observed after T may ever reach a caller through this
module, and a field with no observation before T is honestly absent rather
than backfilled or interpolated.

`as_of` is pure and deterministic: same stores, same game key, same T, same
snapshot, every time. It does no clock reads, no I/O beyond reading the JSONL
files it is told (or defaults) to read, and never mutates its inputs.

PER-FIELD PROVENANCE, NOT A PER-SNAPSHOT ONE
---------------------------------------------
A single decision-time snapshot mixes fields with very different information
quality: a 2026 umpire crew observed via live polling minutes before the
game carries real `known_at` timing; a 2023 probable pitcher backfilled from
a season-end box score cannot honestly claim any `known_at` before the game
itself, because this project did not capture the timestamp at which that
information became public in 2023-24 (docs/AUDIT_PROBABLE_PITCHER_PIT.md).
Stamping one grade on the whole snapshot would hide that difference; every
field gets its own {source, observed_utc, known_at, known_at_grade}.

DEGRADED-INFORMATION REPLAY (owner decision 7)
-----------------------------------------------
`information_grade()` looks at a snapshot's provenance and returns a
`ReplayLabel` -- FAITHFUL when every field that was requested and present
carries a real, pre-T `known_at` observation; DEGRADED_INFORMATION, with a
reasons list naming exactly which fields could not be reconstructed at
decision time, otherwise. This is the one place that decision gets made, so
every artifact writer that touches a 2023-24 replay result can call it
instead of re-deriving the rule.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from src.paths import data_path, processed_path

# ---------------------------------------------------------------------------
# Grades, mirroring src/board/record.py's known_at_grade alphabet so a
# provenance field written here is never a fifth letter nobody else reads.
# ---------------------------------------------------------------------------

GRADE_A = "A"  # real known_at: an honest capture/poll timestamp before T
GRADE_D = "D"  # no known_at can be reconstructed; value (if any) is the
               # store's own observed_utc used as a stand-in, never a claim
               # of point-in-time knowledge

_GRADES = frozenset("ABCD")

# The forward window this project can honestly instrument at capture time.
# Anything dated before this is 2023-24 backfill: the watch/poll stores did
# not exist yet, so no field sourced from them can carry a real known_at.
_LIVE_CAPTURE_START = datetime(2025, 1, 1, tzinfo=timezone.utc)


class AsOfError(ValueError):
    """Raised for a malformed request (bad game key, non-UTC T, bad store)."""


class ReplayLabel(str, Enum):
    FAITHFUL = "FAITHFUL"
    DEGRADED_INFORMATION = "DEGRADED_INFORMATION"


@dataclass(frozen=True)
class FieldObservation:
    """One field's value plus where it came from and how well T is known.

    `known_at` is when the fact became knowable to a decision-maker -- for a
    live poll this is `observed_utc` itself; for anything reconstructed after
    the fact it is None, and `known_at_grade` is GRADE_D to say so honestly.
    """

    value: Any
    source: str
    observed_utc: str
    known_at: str | None
    known_at_grade: str

    def __post_init__(self) -> None:
        if self.known_at_grade not in _GRADES:
            raise AsOfError(
                f"known_at_grade must be one of {sorted(_GRADES)}, got "
                f"{self.known_at_grade!r}")
        if self.known_at_grade == GRADE_A and self.known_at is None:
            raise AsOfError("grade A requires a known_at timestamp")

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "source": self.source,
            "observed_utc": self.observed_utc,
            "known_at": self.known_at,
            "known_at_grade": self.known_at_grade,
        }


@dataclass(frozen=True)
class Snapshot:
    """The as-of read result for one game at one instant T.

    `fields` holds only fields that had at least one observation at or before
    T; a field absent from `fields` is honestly unknown as of T, never a
    null placeholder.
    """

    game_key: str
    t: str  # ISO-8601 UTC, the instant the snapshot was taken at
    fields: Mapping[str, FieldObservation] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "game_key": self.game_key,
            "t": self.t,
            "fields": {k: v.to_dict() for k, v in sorted(self.fields.items())},
        }

    def get(self, name: str, default: Any = None) -> Any:
        obs = self.fields.get(name)
        return obs.value if obs is not None else default


# ---------------------------------------------------------------------------
# Store definitions: one entry per forward store this reader knows about.
# Each entry is (relative jsonl path, game-key extractor, field extractors).
# A field extractor maps a raw JSONL row -> value, or None if this row does
# not carry that field. Rows failing the game-key extractor (e.g. the
# "poll": true heartbeat rows every watch file interleaves) are skipped.
# ---------------------------------------------------------------------------

FieldExtractor = Callable[[dict], Any]


@dataclass(frozen=True)
class StoreSpec:
    name: str
    path: Path
    game_key_of: Callable[[dict], str | None]
    time_of: Callable[[dict], str | None]
    fields: Mapping[str, FieldExtractor]


def _pk(row: dict) -> str | None:
    v = row.get("game_pk")
    return str(v) if v is not None else None


def _obs_utc(row: dict) -> str | None:
    return row.get("observed_utc") or row.get("fetched_utc")


def _default_stores() -> list[StoreSpec]:
    return [
        StoreSpec(
            name="umpires_watch",
            path=data_path("watch", "umpires_watch.jsonl"),
            game_key_of=_pk,
            time_of=_obs_utc,
            fields={
                "home_plate_umpire": lambda r: r.get("home_plate_umpire"),
                "umpire_crew": lambda r: r.get("crew"),
            },
        ),
        StoreSpec(
            name="lineups_watch",
            path=data_path("watch", "lineups_watch.jsonl"),
            game_key_of=_pk,
            time_of=_obs_utc,
            fields={
                "home_lineup": lambda r: r.get("home_lineup") or None,
                "away_lineup": lambda r: r.get("away_lineup") or None,
            },
        ),
        StoreSpec(
            name="probables_watch",
            path=data_path("watch", "probables_watch.jsonl"),
            game_key_of=_pk,
            time_of=_obs_utc,
            fields={
                "home_probable_id": lambda r: r.get("home_probable_id"),
                "away_probable_id": lambda r: r.get("away_probable_id"),
            },
        ),
        StoreSpec(
            name="transactions_watch",
            path=data_path("watch", "transactions_watch.jsonl"),
            game_key_of=lambda r: None,  # not game-keyed; never matches
            time_of=_obs_utc,
            fields={},
        ),
        StoreSpec(
            name="weather_forecast",
            path=processed_path("weather_forecast.jsonl"),
            game_key_of=_pk,
            time_of=_obs_utc,
            fields={
                "temp_f": lambda r: r.get("temp_f"),
                "wind_mph": lambda r: r.get("wind_mph"),
                "wind_from_deg": lambda r: r.get("wind_from_deg"),
                "precip_probability_pct": lambda r: r.get(
                    "precip_probability_pct"),
                "roof": lambda r: r.get("roof"),
            },
        ),
        StoreSpec(
            name="boxscores",
            path=processed_path("boxscores_2026.jsonl"),
            game_key_of=_pk,
            time_of=_obs_utc,
            fields={
                "boxscore_rows": lambda r: r,
            },
        ),
    ]


def _parse_utc(value: str) -> datetime:
    v = value.replace("Z", "+00:00") if value.endswith("Z") else value
    d = datetime.fromisoformat(v)
    if d.tzinfo is None:
        raise AsOfError(f"timestamp {value!r} is not timezone-aware")
    return d.astimezone(timezone.utc)


def _known_at_for(observed_utc_dt: datetime) -> tuple[str | None, str]:
    """Whether this row's own observed_utc can honestly stand in for
    known_at. Only true for the live-capture era (2025+); 2023-24 backfill
    rows never get to claim a real known_at even when observed_utc exists,
    because observed_utc there is when THIS PROJECT captured/backfilled the
    row, not when the fact was public.
    """
    if observed_utc_dt >= _LIVE_CAPTURE_START:
        return observed_utc_dt.isoformat(), GRADE_A
    return None, GRADE_D


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


def as_of(game_key: str | int, t: str | datetime, *,
          stores: Iterable[StoreSpec] | None = None) -> Snapshot:
    """The honest snapshot for `game_key` as of instant `t` (inclusive).

    Stop-at-T: a row observed strictly after `t` is never read into the
    result, full stop -- there is no downstream filter to trust instead.
    Among rows at or before `t` for a given field, the LATEST one wins (the
    most recent fact known by T), ties broken by store iteration order.
    """
    game_key = str(game_key)
    t_dt = t if isinstance(t, datetime) else _parse_utc(t)
    if t_dt.tzinfo is None:
        raise AsOfError("t must be timezone-aware")
    t_dt = t_dt.astimezone(timezone.utc)

    specs = list(stores) if stores is not None else _default_stores()
    fields: dict[str, FieldObservation] = {}
    # track the observed_utc datetime backing each field's current winner,
    # so a later store/row with an equal-or-earlier time never overwrites it
    winners_time: dict[str, datetime] = {}

    for spec in specs:
        for row in _iter_rows(spec.path):
            key = spec.game_key_of(row)
            if key is None or key != game_key:
                continue
            raw_time = spec.time_of(row)
            if raw_time is None:
                continue
            try:
                row_dt = _parse_utc(raw_time)
            except (ValueError, AsOfError):
                continue
            if row_dt > t_dt:
                continue  # future observation: stop-at-T, never surfaced
            for field_name, extractor in spec.fields.items():
                value = extractor(row)
                if value is None:
                    continue
                current = winners_time.get(field_name)
                if current is not None and row_dt <= current:
                    continue
                known_at, grade = _known_at_for(row_dt)
                fields[field_name] = FieldObservation(
                    value=value,
                    source=spec.name,
                    observed_utc=row_dt.isoformat(),
                    known_at=known_at,
                    known_at_grade=grade,
                )
                winners_time[field_name] = row_dt

    return Snapshot(game_key=game_key, t=t_dt.isoformat(), fields=fields)


# ---------------------------------------------------------------------------
# Information grade / degraded-information labelling (owner decision 7)
# ---------------------------------------------------------------------------

# Fields whose absence, or whose presence without a real known_at, marks a
# snapshot as degraded-information -- named per the task packet: lineup
# posting timestamps, probable-pitcher timestamps, and umpires are the
# fields this project cannot honestly reconstruct pre-2026.
DEGRADED_SENTINEL_FIELDS = (
    "home_lineup",
    "away_lineup",
    "home_probable_id",
    "away_probable_id",
    "home_plate_umpire",
)


def information_grade(
        snapshot: Snapshot,
        *, sentinel_fields: Iterable[str] = DEGRADED_SENTINEL_FIELDS,
) -> tuple[ReplayLabel, list[str]]:
    """Classify a snapshot as FAITHFUL or DEGRADED_INFORMATION.

    A field counts against faithfulness in either of two ways:
      - it is entirely absent from the snapshot (never observed by T), or
      - it is present but graded D (no real known_at could be reconstructed,
        e.g. a 2023-24 backfilled probable pitcher).
    Reasons are returned sorted and deduplicated so two snapshots with the
    same problem produce byte-identical reason lists.
    """
    reasons: list[str] = []
    for name in sentinel_fields:
        obs = snapshot.fields.get(name)
        if obs is None:
            reasons.append(f"{name}: no observation before t")
        elif obs.known_at_grade != GRADE_A:
            reasons.append(
                f"{name}: present but known_at could not be reconstructed "
                f"(grade {obs.known_at_grade})")
    reasons.sort()
    label = ReplayLabel.DEGRADED_INFORMATION if reasons else ReplayLabel.FAITHFUL
    return label, reasons


def replay_label_dict(snapshot: Snapshot, *,
                       sentinel_fields: Iterable[str] = DEGRADED_SENTINEL_FIELDS
                       ) -> dict:
    """The JSON-ready form of `information_grade`, for stamping artifacts."""
    label, reasons = information_grade(snapshot, sentinel_fields=sentinel_fields)
    return {"label": label.value, "reasons": reasons}


def season_replay_label(season: int) -> dict:
    """A season-level degraded-information label, for artifact writers that
    have no per-game snapshot at hand (e.g. a sweep report keyed by a whole
    replay universe) but do know which season(s) they cover.

    Per owner decision 7 and docs/AUDIT_PROBABLE_PITCHER_PIT.md: every
    2023-24 season is DEGRADED_INFORMATION by construction -- the watch/poll
    stores this reader reads from did not exist yet, so lineup posting
    timestamps, probable-pitcher timestamps and umpire assignments cannot be
    reconstructed at decision time for any game in those seasons. 2025+ is
    FAITHFUL as far as this function is concerned (a caller with real
    per-game snapshots should prefer `information_grade`/`replay_label_dict`
    instead of this season-level shortcut).
    """
    if season < 2025:
        return {
            "label": ReplayLabel.DEGRADED_INFORMATION.value,
            "reasons": [
                f"season {season}: lineup posting timestamps absent "
                "pre-2026 watch capture",
                f"season {season}: probable-pitcher timestamps absent "
                "pre-2026 watch capture",
                f"season {season}: umpire assignments absent pre-2026 "
                "watch capture",
            ],
        }
    return {"label": ReplayLabel.FAITHFUL.value, "reasons": []}


def seasons_replay_label(seasons: Iterable[int]) -> dict:
    """`season_replay_label`, merged across every season an artifact covers.

    Any degraded season degrades the whole artifact; reasons from every
    degraded season are concatenated, sorted, and deduplicated.
    """
    seasons = sorted(set(int(s) for s in seasons))
    reasons: list[str] = []
    label = ReplayLabel.FAITHFUL
    for season in seasons:
        one = season_replay_label(season)
        if one["label"] == ReplayLabel.DEGRADED_INFORMATION.value:
            label = ReplayLabel.DEGRADED_INFORMATION
            reasons.extend(one["reasons"])
    return {"label": label.value, "reasons": sorted(set(reasons))}
