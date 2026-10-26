"""What our own stores say about a game as of an instant: starters, lineups, umpire, weather, transactions, models.

NOTHING HERE IS RESEARCHED. Every field is read from a file the capture loops already write, through
``src.core.asof`` (the stop-at-T reader) or a direct read that applies the same cut. A field with no observation
at or before ``as_of`` is absent from the result and listed under ``missing``; the briefing then prints "no data".
Injuries have no dedicated MLB feed in our stores, so the only injury-like facts are the IL moves in the
transactions watch file, shown as transactions and never as a diagnosis.

STORED MODELS, NOT NEW ONES. The one game-level model output we store with a forward timestamp is the postseason
series forecast (``evidence/postseason_forecasts.jsonl``, POSTSEASON_PAGE_V1: the next game's home chance) and the
logged single-game predictions (``evidence/predictions.jsonl``). Both are read as-of; neither is calibrated.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from src import paths
from src.core import asof
from src.jarvis.board import iso, parse_time

TRANSACTION_LOOKBACK = timedelta(hours=72)
CONTEXT_STORES = ("umpires_watch", "lineups_watch", "probables_watch", "weather_forecast")
NO_DATA = "no data"

_EASTERN_FIXED = timedelta(hours=-4)   # only used to date a forecast row; see ``_eastern_date``


def _rows(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def evidence_path(name: str) -> Path:
    """evidence/<name>, or JARVIS_EVIDENCE_DIR/<name> (tests and odd deployments redirect the whole folder)."""
    override = (os.environ.get("JARVIS_EVIDENCE_DIR") or "").strip()
    return (Path(override) if override else paths.repo_root() / "evidence") / name


def _eastern_date(moment: datetime) -> str:
    from src.data.eastern import eastern
    return moment.astimezone(eastern()).date().isoformat()


def event_game_pks(as_of: datetime) -> dict:
    """``{event_id: game_pk}`` from the event-to-game map, using only rows resolved at or before ``as_of``."""
    out: dict = {}
    for row in _rows(paths.processed_path("event_game_map.jsonl")):
        resolved = parse_time(row.get("resolved_utc"))
        if (row.get("resolved") and not row.get("ambiguous") and row.get("game_pk") not in (None, "")
                and resolved is not None and resolved <= as_of):
            out[row.get("event_id")] = str(row["game_pk"])
    return out


def player_names() -> dict:
    """``{player_id: name}`` from the boxscore store (the only id-to-name list we keep); empty when it is missing."""
    names: dict = {}
    for row in _rows(paths.processed_path("boxscores_2026.jsonl")):
        pid, name = row.get("player_id"), row.get("player_name")
        if pid is not None and name:
            names[str(pid)] = name
    return names


def _stores() -> list:
    return [s for s in asof._default_stores() if s.name in CONTEXT_STORES]


def transactions_for(teams: list, as_of: datetime, names: Optional[Mapping] = None) -> list:
    """IL moves and roster moves first seen in the 72 hours up to ``as_of`` for these team abbreviations."""
    lo = as_of - TRANSACTION_LOOKBACK
    seen, out = set(), []
    for row in _rows(paths.data_path("watch", "transactions_watch.jsonl")):
        if row.get("poll") or row.get("team") not in teams:
            continue
        first = parse_time(row.get("first_seen_utc"))
        key = row.get("transaction_id")
        if first is None or first > as_of or first < lo or key in seen:
            continue
        seen.add(key)
        out.append({"team": row.get("team"), "player": row.get("player") or (names or {}).get(str(row.get("player_id"))),
                    "category": row.get("category"), "first_seen_utc": iso(first)})
    out.sort(key=lambda r: r["first_seen_utc"])
    return out


def game_context(event: Mapping, game_pk: Optional[str], as_of: datetime, names: Mapping) -> dict:
    """The stored facts for one game as of ``as_of``. ``event`` carries away_team, home_team, commence_time."""
    from src.pipeline.slate import team_abbrev_from_name
    teams = [team_abbrev_from_name(event.get("home_team")), team_abbrev_from_name(event.get("away_team"))]
    ctx: dict = {"game_pk": game_pk, "teams": {"home": teams[0], "away": teams[1]}, "missing": []}
    snap = asof.as_of(game_pk, as_of, stores=_stores()) if game_pk else None
    if snap is None:
        ctx["missing"].append("game_pk (the odds event is not mapped to an MLB game at this time)")

    def name_of(pid):
        return names.get(str(pid)) or f"player {pid} (name not on file)"

    def get(field):
        return snap.get(field) if snap is not None else None

    probables = {}
    for side in ("home", "away"):
        pid = get(f"{side}_probable_id")
        probables[side] = {"id": pid, "name": name_of(pid)} if pid is not None else None
    ctx["probables"] = probables
    if not all(probables.values()):
        ctx["missing"].append("probable pitchers")
    lineup = {}
    for side in ("home", "away"):
        ids = get(f"{side}_lineup")
        lineup[side] = [{"slot": i + 1, "id": pid, "name": name_of(pid)} for i, pid in enumerate(ids)] if ids else None
    ctx["lineups"] = lineup
    ctx["lineups_posted"] = bool(lineup["home"] and lineup["away"])
    if not ctx["lineups_posted"]:
        ctx["missing"].append("lineups (not posted at this time)")
    ctx["umpire"] = get("home_plate_umpire")
    if not ctx["umpire"]:
        ctx["missing"].append("home-plate umpire")
    weather = {k: get(k) for k in ("temp_f", "wind_mph", "wind_from_deg", "precip_probability_pct", "roof")}
    ctx["weather"] = weather if any(v is not None for v in weather.values()) else None
    if ctx["weather"] is None:
        ctx["missing"].append("weather forecast")
    ctx["transactions"] = transactions_for([t for t in teams if t], as_of, names)
    ctx["injuries"] = NO_DATA
    return ctx


def postseason_home_chance(event: Mapping, as_of: datetime, path: Optional[Path] = None) -> Optional[dict]:
    """The stored POSTSEASON_PAGE_V1 home-win chance for this game, or None.

    A forecast row is dated by the day it covers; it counts as known only once that Eastern day is over at
    ``as_of`` (the row has no publish instant of its own, so the cut is deliberately late, never early)."""
    from src.pipeline.slate import team_abbrev_from_name
    home, away = team_abbrev_from_name(event.get("home_team")), team_abbrev_from_name(event.get("away_team"))
    start = parse_time(event.get("commence_time"))
    if not home or not away or start is None:
        return None
    game_date = _eastern_date(start)
    best = None
    for row in _rows(path or evidence_path("postseason_forecasts.jsonl")):
        nxt = row.get("next_game") or {}
        row_date = row.get("date")
        if not row_date or nxt.get("home") != home or nxt.get("away") != away or nxt.get("date") != game_date:
            continue
        if nxt.get("home_chance") is None:
            continue
        try:
            known = datetime.fromisoformat(row_date).replace(tzinfo=timezone.utc) + timedelta(days=1) - _EASTERN_FIXED
        except ValueError:
            continue
        if known > as_of:
            continue
        if best is None or row_date > best["row_date"]:
            best = {"home_probability": float(nxt["home_chance"]), "model": row.get("model") or "POSTSEASON_PAGE_V1",
                    "row_date": row_date, "starter_input_class": nxt.get("starter_input_class"),
                    "game_number": nxt.get("number"), "round": row.get("round")}
    return best


def logged_prediction(game_pk: Optional[str], as_of: datetime, path: Optional[Path] = None) -> Optional[dict]:
    """The logged single-game prediction for this game_pk made at or before ``as_of`` (latest), or None."""
    if not game_pk:
        return None
    best = None
    for row in _rows(path or evidence_path("predictions.jsonl")):
        when = parse_time(row.get("logged_utc"))
        if str(row.get("game_pk")) != str(game_pk) or when is None or when > as_of or row.get("home_probability") is None:
            continue
        if best is None or when > best["logged"]:
            best = {"home_probability": float(row["home_probability"]), "model": "predictions.jsonl " + str(row.get("model_version")),
                    "logged": when, "row_date": row.get("date")}
    return best


def model_for_game(event: Mapping, game_pk: Optional[str], as_of: datetime) -> Optional[dict]:
    """The stored model output for a game's home win probability, preferring the postseason forecast."""
    return postseason_home_chance(event, as_of) or logged_prediction(game_pk, as_of)
