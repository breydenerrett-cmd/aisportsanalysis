"""What is in season, and how many games are on in the next seven days: the body of GET /sports/season.

READ ONLY, FROM STORED ROWS. The rules editor's sport chips ("NBA · 58 games this week", "MLB · postseason · 3 games") read
this. Nothing here calls an API. Three stored sources, each optional (a missing one only lowers a count, it never raises):

  * the ESPN stores (data/datasvc/espn/<league>/games_<season>.jsonl): the newest version of every game, counted when its
    state is still "pre" and it starts inside the window; the store's own `season_slug` says preseason / postseason;
  * the all-sports multibook store, through src/sports/allsports_view.py: the events the odds capture has seen, which is
    what MLB, NFL, tennis, MMA and the rest are counted from;
  * the all-sports sport list (data/processed/allsports_sports.jsonl): the sport keys the odds feed marks active, which is
    how a sport with no game this week is told apart from a sport out of season.

A family's count is the LARGER of its ESPN count and its board count (the two overlap, so they are never added). The
counts are the games the program has stored, not a complete league schedule; the payload says when each source was last
read so the page does not present a stale store as today's schedule.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping, Optional

from src.sports import catalog

WINDOW_DAYS = 7
TTL_SECONDS = 600.0

#: ESPN league code -> the catalog family its games count toward.
LEAGUE_FAMILY = {"nba": "NBA", "wnba": "WNBA", "nhl": "NHL", "ncaaf": "NCAAF", "ncaab": "NCAAB", "ncaaw": "NCAAB",
                 "epl": "SOCCER", "laliga": "SOCCER", "bundesliga": "SOCCER", "seriea": "SOCCER", "ligue1": "SOCCER",
                 "mls": "SOCCER", "ucl": "SOCCER", "uel": "SOCCER", "uecl": "SOCCER"}

_cache: dict = {}
_lock = threading.Lock()


def _parse(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slug_phase(slug) -> Optional[str]:
    text = str(slug or "").lower().replace("-", "")
    if "postseason" in text or "playoff" in text:
        return "postseason"
    if "preseason" in text:
        return "preseason"
    return None


def espn_counts(now: datetime, *, store=None, leagues: Optional[Iterable[str]] = None) -> dict:
    """{family: {"games": n, "phase": str|None, "as_of": iso|None}} from the ESPN stores' newest game versions."""
    out: dict = {}
    try:
        if store is None:
            from src.datasvc.espn.store import EspnStore
            store = EspnStore()
        horizon = now + timedelta(days=WINDOW_DAYS)
        for league in (leagues if leagues is not None else LEAGUE_FAMILY):
            family = LEAGUE_FAMILY.get(league)
            if family is None:
                continue
            try:
                seasons = store.seasons(league, "games")
                games = {}
                for season in seasons[-2:]:                      # the current season is the newest file or the one before it
                    games.update(store.latest(league, "games", season))
            except Exception:  # noqa: BLE001 -- one unreadable league never blanks the rest
                continue
            slugs: dict = {}
            n = 0
            newest = None
            for row in games.values():
                seen = _parse(row.get("observed_utc"))
                if seen and (newest is None or seen > newest):
                    newest = seen
                start = _parse(row.get("date_utc"))
                if row.get("state") != "pre" or start is None or not (now <= start <= horizon):
                    continue
                n += 1
                phase = _slug_phase(row.get("season_slug")) or "regular"
                slugs[phase] = slugs.get(phase, 0) + 1
            slot = out.setdefault(family, {"games": 0, "phase": None, "as_of": None, "_phases": {}})
            slot["games"] += n
            for k, v in slugs.items():
                slot["_phases"][k] = slot["_phases"].get(k, 0) + v
            if newest and (slot["as_of"] is None or _iso(newest) > slot["as_of"]):
                slot["as_of"] = _iso(newest)
    except Exception:  # noqa: BLE001 -- the stores are optional
        return {}
    for slot in out.values():
        phases = slot.pop("_phases")
        top = max(phases, key=phases.get) if phases else None
        slot["phase"] = top if top in ("preseason", "postseason") else None
    return out


def board_counts(now: datetime, *, rows: Optional[Iterable[Mapping]] = None, path=None) -> dict:
    """{family: games} for events in the all-sports / multibook store that start inside the window (or are still live)."""
    try:
        from src.sports import allsports_view
        if rows is None:
            rows = allsports_view.read_recent_rows(now, path=path)
        events = allsports_view.build_events(rows, now)
    except Exception:  # noqa: BLE001
        return {}
    horizon = now + timedelta(days=WINDOW_DAYS)
    out: dict = {}
    for ev in events.values():
        start = ev["_start"]
        if ev["in_play"] or (now < start <= horizon):
            out[ev["family"]] = out.get(ev["family"], 0) + 1
    return out


def active_families(path=None) -> tuple:
    """(families the odds feed marks active, observed_utc) from the newest line of the all-sports sport list."""
    try:
        if path is None:
            from src.pipeline.allsports_capture import DEFAULT_SPORTS_PATH
            path = DEFAULT_SPORTS_PATH
        last = None
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    last = line
        if not last:
            return set(), None
        row = json.loads(last)
        return {k for k, v in (row.get("families") or {}).items() if v}, row.get("observed_utc")
    except Exception:  # noqa: BLE001
        return set(), None


def mlb_phase(now: datetime) -> Optional[str]:
    """"postseason" between the first wild-card day and the last World Series day of the recorded calendar."""
    try:
        from src.analysis import postseason_config as pc
        first = pc.CALENDAR[pc.CALENDAR_ROUNDS_IN_ORDER[0]]["start"]
        last = pc.CALENDAR[pc.CALENDAR_ROUNDS_IN_ORDER[-1]]["end"]
        day = now.date().isoformat()
        return "postseason" if first <= day <= last else None
    except Exception:  # noqa: BLE001
        return None


def chip_text(label: str, games: int, phase: Optional[str]) -> str:
    """The words on the chip: "NBA · 25 games coming up", "MLB · postseason · 3 games", "Tennis · no games this week".

    "Coming up", not "this week": the stored schedules reach only a few days ahead (ESPN's NBA rows stop ~4 days out), so
    the count is what is listed, never a claim about the whole week."""
    if games <= 0:
        return f"{label} · no games this week"
    noun = "game" if games == 1 else "games"
    return f"{label} · {phase} · {games} {noun}" if phase else f"{label} · {games} {noun} coming up"


def season_overview(now: Optional[datetime] = None, *, espn: Optional[Mapping] = None, board: Optional[Mapping] = None,
                    active: Optional[Iterable[str]] = None, active_as_of: Optional[str] = None) -> dict:
    """GET /sports/season. The three keyword inputs are the injection points (tests pass fixtures; production reads the stores)."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    espn = espn_counts(now) if espn is None else espn
    board = board_counts(now) if board is None else board
    if active is None:
        active, active_as_of = active_families()
    active = set(active)
    sports = []
    for code in catalog.family_codes():
        fam = catalog.family(code) or {}
        if not fam.get("dog_menu"):
            continue
        e = espn.get(code) or {}
        games = max(int(e.get("games") or 0), int(board.get(code) or 0))
        phase = e.get("phase")
        if code == "MLB":
            phase = mlb_phase(now) or phase
        feed_active = code in active
        if games > 0:
            in_season, reason = True, ""
        elif feed_active:
            in_season, reason = True, "No games scheduled in the next 7 days."
        else:
            in_season, reason = False, "Out of season."
        label = catalog.label(code)
        sports.append({"code": code, "label": label, "in_season": in_season, "games_7d": games, "phase": phase,
                       "chip": chip_text(label, games, phase), "reason": reason})
    return {"generated_utc": _iso(now), "window_days": WINDOW_DAYS, "sports": sports,
            "sources": {"espn_as_of": max((v.get("as_of") for v in espn.values() if v.get("as_of")), default=None),
                        "sport_list_as_of": active_as_of},
            "note": "Counts are the games the program has stored for the next 7 days, not a full league schedule.",
            "paper_only": True}


def cached_season_overview(now: Optional[datetime] = None) -> dict:
    """`season_overview` remembered for `TTL_SECONDS` (production reads only; tests call `season_overview`)."""
    with _lock:
        hit = _cache.get("season")
        if hit and time.monotonic() - hit[0] < TTL_SECONDS:
            return hit[1]
    payload = season_overview(now)
    with _lock:
        _cache["season"] = (time.monotonic(), payload)
    return payload


def clear_cache() -> None:
    with _lock:
        _cache.clear()
