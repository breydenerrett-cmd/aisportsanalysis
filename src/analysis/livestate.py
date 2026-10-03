"""Live game state for one slate: status, score, inning, outs, pitcher.

THE GAP THIS CLOSES
-------------------
Nothing on the site said a game had started. A game in the sixth inning read
exactly like one at 1 p.m., and the only price on its page was the pregame one.
This module answers one question for a slate, from a source that is free and
already used by the repo's providers: the MLB Stats API schedule with its
linescore hydrated (src.providers.mlb.fetch_schedule -- the same call the
schedule and the livefeed poller make). One schedule call carries every game's
status, runs, inning, half, outs and the pitcher on the mound.

COST AND LOAD
-------------
Free, and still bounded: ONE upstream call per slate per cache window, never per
visitor. `LiveStateCache` serves everyone from one entry per date, a concurrent
burst shares one fetch (per-date lock, re-checked after acquiring it), a failed
fetch is not retried for FAIL_TTL_S so an outage is not hammered, and at most
MAX_DATES entries are held. `get_slate` refuses dates outside yesterday..tomorrow
(ET) before any network call, so a client walking dates cannot fan the upstream
out.

FAIL SOFT
---------
Upstream down or slow: the last good snapshot is served, flagged `stale`, for up
to STALE_MAX_S; after that the answer is `available: false` with a reason. A
live score older than a few minutes is worse than none, so it is never served
indefinitely, and never as if it were fresh.

WHAT THIS IS NOT
----------------
A feed to bet against. The score and inning are observations with an
`observed_utc`; the page labels any pregame price on a started game as the last
pregame price with its capture time (web/js/livestate.js).
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from src.analysis import gamepayload

TTL_S = 45.0          # one upstream call per slate per this window
FAIL_TTL_S = 15.0     # after a failed fetch, do not try again for this long
STALE_MAX_S = 180.0   # the oldest good snapshot ever served after a failure
MAX_DATES = 8         # entries held at once

PREGAME = "pregame"
IN_PROGRESS = "in_progress"
DELAYED = "delayed"
FINAL = "final"
POSTPONED = "postponed"
STATUSES = (PREGAME, IN_PROGRESS, DELAYED, FINAL, POSTPONED)

SOURCE = "MLB Stats API schedule + linescore (free)"

_FINAL_CODES = frozenset({"F", "O"})
_POSTPONED_CODES = frozenset({"D", "C"})
_SUSPENDED_CODES = frozenset({"T", "U"})


# ---------------------------------------------------------------------------
# Classifying and flattening one game
# ---------------------------------------------------------------------------

def classify(game: dict) -> str:
    """One of STATUSES from a raw schedule game.

    Order matters. Postponed/cancelled first (never mistaken for a final), then
    final (a game that ended after a delay is final), then a delay or suspension,
    then live play. A game in Warmup is pregame: nothing has been played. A game with
    no status at all is pregame -- never invented as live.
    """
    status = game.get("status") or {}
    coded = status.get("codedGameState")
    abstract = (status.get("abstractGameState") or "").lower()
    detailed = (status.get("detailedState") or "").lower()
    # Postponed/cancelled BEFORE final: the feed files some of them under an
    # abstract state of "Final", and a game that was never played has no score.
    if coded in _POSTPONED_CODES or "postpone" in detailed or "cancel" in detailed:
        return POSTPONED
    if coded in _FINAL_CODES or abstract == "final":
        return FINAL
    if coded in _SUSPENDED_CODES or "delay" in detailed or "suspend" in detailed:
        return DELAYED
    if abstract == "live" and "warmup" not in detailed and "warm up" not in detailed:
        return IN_PROGRESS
    return PREGAME


def _int(value) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _abbrev(side: dict) -> Optional[str]:
    abbrev = (side.get("team") or {}).get("abbreviation")
    return abbrev.strip().upper() if isinstance(abbrev, str) and abbrev.strip() else None


def _score(game: dict, linescore: dict, side: str) -> Optional[int]:
    runs = _int(((linescore.get("teams") or {}).get(side) or {}).get("runs"))
    if runs is not None:
        return runs
    return _int(((game.get("teams") or {}).get(side) or {}).get("score"))


_HALF_WORD = {"top": "Top", "bottom": "Bot", "middle": "Mid", "end": "End"}


def parse_game(game: dict, observed_utc: str) -> dict:
    """One game's live state. Fields the feed does not give are None, never
    guessed: a pregame game has no score, a game between innings has no outs."""
    teams = game.get("teams") or {}
    away, home = teams.get("away") or {}, teams.get("home") or {}
    linescore = game.get("linescore") or {}
    status = classify(game)
    started = status in (IN_PROGRESS, FINAL) or (
        status == DELAYED and bool(linescore.get("currentInning")))

    record = {
        "game_pk": game.get("gamePk"),
        "away_team": _abbrev(away),
        "home_team": _abbrev(home),
        "date": game.get("officialDate") or (game.get("gameDate") or "")[:10] or None,
        "start_time_utc": game.get("gameDate"),
        "status": status,
        "detailed_state": (game.get("status") or {}).get("detailedState"),
        "away_score": _score(game, linescore, "away") if started else None,
        "home_score": _score(game, linescore, "home") if started else None,
        "inning": None, "half": None, "inning_text": None, "outs": None, "pitcher": None,
        "observed_utc": observed_utc,
    }
    # The id every other payload uses for this game (gamepayload.game_id), so a
    # page matches a live row to its own game without a second join key.
    record["game_id"] = gamepayload.game_id({
        "away_team": record["away_team"], "home_team": record["home_team"],
        "date": record["date"], "game_number": game.get("gameNumber"),
        "game_pk": game.get("gamePk")})

    if status in (IN_PROGRESS, DELAYED) and started:
        inning = _int(linescore.get("currentInning"))
        half = (linescore.get("inningState") or linescore.get("inningHalf") or "").strip().lower() or None
        record["inning"], record["half"] = inning, half
        if inning is not None and half in _HALF_WORD:
            ordinal = linescore.get("currentInningOrdinal") or str(inning)
            record["inning_text"] = f"{_HALF_WORD[half]} {ordinal}"
        # Outs are meaningful only while a half-inning is being played.
        if half in ("top", "bottom"):
            record["outs"] = _int(linescore.get("outs"))
            name = ((linescore.get("defense") or {}).get("pitcher") or {}).get("fullName")
            record["pitcher"] = name if isinstance(name, str) and name.strip() else None
    return record


# ---------------------------------------------------------------------------
# The cache -- one upstream call per slate per window
# ---------------------------------------------------------------------------

class LiveStateCache:
    """Bounded, thread-safe, single-flight cache of parsed slates by date.

    Holds parsed game records (small), never the raw schedule payload. The clock
    is injectable so tests control time without sleeping.
    """

    def __init__(self, ttl_s: float = TTL_S, fail_ttl_s: float = FAIL_TTL_S,
                 stale_max_s: float = STALE_MAX_S, max_dates: int = MAX_DATES,
                 clock: Callable[[], float] = time.monotonic):
        self.ttl_s, self.fail_ttl_s = ttl_s, fail_ttl_s
        self.stale_max_s, self.max_dates = stale_max_s, max_dates
        self._clock = clock
        self._lock = threading.Lock()
        self._locks: dict = {}
        self._entries: "OrderedDict[str, dict]" = OrderedDict()
        self.upstream_calls = 0

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._locks.clear()
            self.upstream_calls = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def _date_lock(self, date: str) -> threading.Lock:
        with self._lock:
            lock = self._locks.get(date)
            if lock is None:
                lock = self._locks[date] = threading.Lock()
            return lock

    def _peek(self, date: str) -> Optional[dict]:
        with self._lock:
            entry = self._entries.get(date)
            if entry is not None:
                self._entries.move_to_end(date)
            return entry

    def _store(self, date: str, entry: dict) -> None:
        with self._lock:
            self._entries[date] = entry
            self._entries.move_to_end(date)
            while len(self._entries) > self.max_dates:
                evicted, _ = self._entries.popitem(last=False)
                self._locks.pop(evicted, None)

    def get(self, date: str, fetch: Callable[[], list]) -> dict:
        """{"games": list|None, "age_seconds": float|None, "stale": bool,
        "error": str|None}. `fetch` returns the parsed game list; it is called at
        most once per window per date however many callers arrive."""
        entry = self._peek(date)
        if entry is not None and self._clock() < entry["retry_at"]:
            return self._serve(entry)
        with self._date_lock(date):
            entry = self._peek(date)
            if entry is not None and self._clock() < entry["retry_at"]:
                return self._serve(entry)
            previous = entry
            self.upstream_calls += 1
            try:
                games = fetch()
            except Exception as exc:  # noqa: BLE001 -- fail soft, whatever the cause
                now = self._clock()
                entry = {
                    "games": previous["games"] if previous else None,
                    "fetched_at": previous["fetched_at"] if previous else None,
                    "retry_at": now + self.fail_ttl_s,
                    "error": f"{type(exc).__name__}: {exc}"[:200],
                }
            else:
                now = self._clock()
                entry = {"games": games, "fetched_at": now, "retry_at": now + self.ttl_s,
                         "error": None}
            self._store(date, entry)
            return self._serve(entry)

    def _serve(self, entry: dict) -> dict:
        now = self._clock()
        games, fetched_at = entry["games"], entry["fetched_at"]
        if games is None or fetched_at is None:
            return {"games": None, "age_seconds": None, "stale": False, "error": entry["error"]}
        age = now - fetched_at
        if age > self.stale_max_s:
            return {"games": None, "age_seconds": age, "stale": True,
                    "error": entry["error"] or "snapshot too old to serve"}
        return {"games": games, "age_seconds": age, "stale": entry["error"] is not None
                or age >= self.ttl_s, "error": entry["error"]}


CACHE = LiveStateCache()


# ---------------------------------------------------------------------------
# The slate payload
# ---------------------------------------------------------------------------

def _eastern():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/New_York")
    except Exception:  # noqa: BLE001 -- no tz data (Windows): fixed -4 is close enough for a +-1 day window
        return timezone(timedelta(hours=-4))


def et_today(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(_eastern()).strftime("%Y-%m-%d")


def _within_window(date: str, now: datetime) -> bool:
    try:
        day = datetime.strptime(date, "%Y-%m-%d").date()
        today = datetime.strptime(et_today(now), "%Y-%m-%d").date()
    except ValueError:
        return False
    return abs((day - today).days) <= 1


def _empty(date: str, now: datetime, reason: str) -> dict:
    return {"date": date, "generated_at": now.isoformat(), "available": False,
            "reason": reason, "source": SOURCE, "observed_utc": None, "games": [],
            "cache": {"age_seconds": None, "ttl_seconds": TTL_S, "stale": False},
            "summary": {"games": 0, **{s: 0 for s in STATUSES}}}


def _default_fetch_schedule(date: str) -> list:
    from src.providers import mlb
    return mlb.fetch_schedule(date)


def get_slate(date: str, *, fetch_schedule: Optional[Callable[[str], list]] = None,
              now: Optional[datetime] = None, cache: Optional[LiveStateCache] = None) -> dict:
    """GET /live/{date}'s payload. Never raises for an upstream problem: it comes
    back `available: false` with the reason.

    `fetch_schedule(date) -> [raw schedule game, ...]` is injectable; the default
    is src.providers.mlb.fetch_schedule (hydrate=probablePitcher,team,linescore).
    """
    now = now or datetime.now(timezone.utc)
    cache = CACHE if cache is None else cache
    fetch_schedule = fetch_schedule or _default_fetch_schedule
    if not _within_window(date, now):
        return _empty(date, now, "live state is served for today's slate only "
                                 "(yesterday to tomorrow, Eastern)")

    def _fetch() -> list:
        observed = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return [parse_game(g, observed) for g in fetch_schedule(date) or []]

    result = cache.get(date, _fetch)
    games = result["games"]
    if games is None:
        return _empty(date, now, "live state not available right now"
                      + (f" ({result['error']})" if result["error"] else ""))
    counts = {s: 0 for s in STATUSES}
    for g in games:
        counts[g["status"]] += 1
    observed = max((g["observed_utc"] for g in games), default=None)
    return {"date": date, "generated_at": now.isoformat(), "available": True, "reason": None,
            "source": SOURCE, "observed_utc": observed,
            "games": games,
            "cache": {"age_seconds": round(result["age_seconds"], 1),
                      "ttl_seconds": cache.ttl_s, "stale": result["stale"]},
            "summary": {"games": len(games), **counts}}
