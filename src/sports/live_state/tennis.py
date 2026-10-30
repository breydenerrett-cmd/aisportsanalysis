"""Tennis live game state from ESPN's free ATP and WTA scoreboards, and the net-breaks math.

WHAT ESPN GIVES, AND WHAT IT DOES NOT (checked 2026-10-29 against live scoreboards)
-----------------------------------------------------------------------------------
Per singles match: a status (STATUS_IN_PROGRESS ...), the games of every set listed so far INCLUDING the one in progress
(``linescores``), a ``possession`` flag on the competitor who is serving, and ``format.regulation.periods`` (3 = best of 3,
5 = best of 5). Every competitor also carries a ``statistics`` list; on all 384 matches read that day, live ones included,
it was EMPTY, so there are no aces, double faults or break-point counts on this feed. ``stats_available`` below says whether
a read carried any, and the numbers are kept per player when it does (ESPN's own stat names). The ESPN summary endpoint for
tennis answers HTTP 400, so there is no second free source for them; if they matter, they are a paid-data question.

This module reuses ``src/providers/espn_tennis_results.py`` (the scoreboard parser the settle path and the live tennis
test already trust) and ``src/research/live_tennis/state.py`` (completed sets, sets won, the set in progress, and the
contradiction checks). The scoreboards are read once per tour per pass (today's UTC date, plus yesterday's early in the UTC
day when a tournament may have just rolled off); ``src/sports/live_feed.py`` does not poll tennis, so there is nothing to share.

THE NET-BREAKS MATH (``net_breaks``, a pure function)
-----------------------------------------------------
Games alternate server, so the number of games already played in a set and WHO IS SERVING NOW say who served first, and
from that how many service games each player has had. A player's games = holds + breaks won (on the other's serve); a
player's service games = holds + breaks lost. So

        net_breaks_A = games_A - service_games_A = breaks A has won - breaks A has lost       (positive = A is up a break)

with service_games_A = ceil(g / 2) if A served first else floor(g / 2), g = games played in the set so far. Two states
have no answer and return None: a set already decided (the next one is not listed yet) and 6-6 (a tiebreak: the server
changes every two points and ESPN's flag cannot be trusted to follow it). Every one of the 2^n game sequences to 12 games
is checked against this formula by the unit tests.

THE SERVER FLAG CAN LAG. ESPN may still flag the player who served the previous game for a few seconds after the games
changed. A one-game lag flips the inferred first server and with it the SIGN of every break count. So the first server
of a set is inferred on each read and ``ServerMemory`` shows net breaks only once two reads in a row agree on it; a read
that disagrees with the one before shows None and restarts the count. Net breaks are therefore one read (about 30 s)
late at the start of a set and never flip silently.

THE STATE DICT (plain, JSON-safe)
---------------------------------
  sport "TENNIS", source "espn", game_id (ESPN's match id), tour "atp"|"wta", tournament, round, state "live", status,
  start_utc, best_of 3|5|None, set_number (the set in progress), sets (every listed set [a_games, b_games] in ESPN's
  order), current_set [a, b]|None, sets_won [a, b], server "a"|"b"|None, first_server, server_confirmed, tiebreak
  (True at 6-6 in the current set, else False; None when the set is not listed), net_breaks {"a": n, "b": -n}|None,
  stats_available, players [{side "a"|"b", name, sets_won, games, serving, net_breaks, stats}], as_of.
  ``state_for`` adds ``home`` / ``away`` (the same player blocks, in the CALLER's order) and ``orientation``.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable, Mapping, Optional

from src.hounds import live_scores as ls
from src.providers import espn_tennis_results as espn
from src.research.live_tennis import state as lt_state
from src.sports.live_state import names, store

SPORT = "TENNIS"
TOURS = espn.TOURS
MAX_REQUESTS_PER_PASS = 6
LEAD_MINUTES = 20                        # a tennis match is read this long before its listed start
LOOKBACK_HOURS = 8                       # and this long after it: a match "followed by" others starts hours late and runs for hours
YESTERDAY_UNTIL_UTC_HOUR = 6             # before this UTC hour the previous day's scoreboards are read too
TIEBREAK_GAMES = 6


# ---------------------------------------------------------------------------
# the math (pure)
# ---------------------------------------------------------------------------

def set_in_progress_games(games_a, games_b) -> bool:
    """True for a non-negative, non-decided score that is not the tiebreak (6-6): the only scores net breaks are defined for."""
    if not all(isinstance(g, int) and not isinstance(g, bool) and g >= 0 for g in (games_a, games_b)):
        return False
    if espn.set_completed(games_a, games_b):
        return False
    return not (games_a == games_b == TIEBREAK_GAMES)


def first_server(games_a: int, games_b: int, server_now: Optional[str]) -> Optional[str]:
    """Who served the FIRST game of the set ("a" or "b"), from the games played and who is serving the next one, or None."""
    if server_now not in ("a", "b") or not set_in_progress_games(games_a, games_b):
        return None
    played = games_a + games_b
    if played % 2 == 0:
        return server_now                        # an even number of games played: the next game is served by the first server
    return "b" if server_now == "a" else "a"


def service_games(games_a: int, games_b: int, first: str) -> tuple:
    """(a's service games, b's service games) among the games already played, given who served first."""
    played = games_a + games_b
    first_count, second_count = (played + 1) // 2, played // 2
    return (first_count, second_count) if first == "a" else (second_count, first_count)


def net_breaks(games_a: int, games_b: int, server_now: Optional[str]) -> Optional[int]:
    """Player A's net breaks in the set in progress: breaks A won minus breaks A lost (positive = A is up a break);
    player B's is the negative. None when the server is unknown, the set is decided, or it is 6-6."""
    first = first_server(games_a, games_b, server_now)
    if first is None:
        return None
    served_a, _served_b = service_games(games_a, games_b, first)
    return games_a - served_a


class ServerMemory:
    """Per (match, set): the first server inferred on the last read and how many reads in a row agreed (see the module docstring)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: dict = {}

    def observe(self, match_id: str, set_number: int, inferred_first: Optional[str]) -> bool:
        """Record this read's inference; True when it is the second (or later) consecutive read to agree."""
        if inferred_first is None:
            return False
        key = (str(match_id), int(set_number))
        with self._lock:
            held = self._seen.get(key)
            if held is not None and held[0] == inferred_first:
                self._seen[key] = (inferred_first, held[1] + 1)
            else:
                self._seen[key] = (inferred_first, 1)
            return self._seen[key][1] >= 2

    def forget_except(self, live_ids) -> None:
        keep = {str(i) for i in live_ids}
        with self._lock:
            for key in [k for k in self._seen if k[0] not in keep]:
                self._seen.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._seen.clear()


MEMORY = ServerMemory()


# ---------------------------------------------------------------------------
# the scoreboard (pure)
# ---------------------------------------------------------------------------

def raw_index(doc) -> dict:
    """{match id: {"periods": int|None, "stats": {1: {...}|None, 2: {...}|None}}} for every singles competition of a scoreboard,
    read straight from the document for the two things the shared parser drops: the format and the competitors' statistics."""
    out: dict = {}
    if not isinstance(doc, Mapping):
        return out
    for event in doc.get("events") or []:
        for group in (event or {}).get("groupings") or []:
            label = str(((group or {}).get("grouping") or {}).get("displayName") or "").lower()
            if "singles" not in label:
                continue
            for comp in (group or {}).get("competitions") or []:
                if not isinstance(comp, Mapping) or not str(comp.get("id") or ""):
                    continue
                periods = ((comp.get("format") or {}).get("regulation") or {}).get("periods")
                stats = {}
                for c in comp.get("competitors") or []:
                    if isinstance(c, Mapping) and c.get("order") in (1, 2):
                        stats[c["order"]] = _stats_of(c.get("statistics"))
                out[str(comp["id"])] = {"periods": periods if isinstance(periods, int) and not isinstance(periods, bool) else None,
                                        "stats": stats}
    return out


def _stats_of(entries) -> Optional[dict]:
    """{ESPN stat name: value} from a competitor's ``statistics`` list, or None when the list is empty (as it is on the free scoreboard)."""
    out = {}
    for entry in entries or []:
        if not isinstance(entry, Mapping):
            continue
        key = entry.get("name") or entry.get("abbreviation")
        value = entry.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            value = entry.get("displayValue")
        if key and value is not None:
            out[str(key)] = value
    return out or None


def best_of_from_periods(periods) -> Optional[int]:
    return periods if periods in (3, 5) else None


def derive(match: "espn.TennisMatch", possession: Optional[str], periods, stats: Optional[Mapping],
           memory: ServerMemory) -> Optional[dict]:
    """The live state of ONE in-progress match, or None when ESPN's data cannot be a match of its format (a set listed
    after an unfinished one, more sets than the format allows) or the match is not in progress."""
    best_of = best_of_from_periods(periods)
    to_win = (best_of + 1) // 2 if best_of else 3                 # unknown format: permissive, so no false contradiction
    live = lt_state.live_state(match, to_win)
    if not live.in_progress or live.contradiction or live.decided:
        return None
    current = live.current
    set_number = live.set_number
    server = possession if possession in ("a", "b") else None
    tiebreak = None if current is None else (current[0] == current[1] == TIEBREAK_GAMES)
    first = confirmed = breaks_a = None
    if current is not None:
        first = first_server(current[0], current[1], server)
        confirmed = memory.observe(match.match_id, set_number, first)
        if confirmed:
            breaks_a = net_breaks(current[0], current[1], server)
    stats = stats or {}
    players = []
    for side, name, idx in (("a", match.player_a, 0), ("b", match.player_b, 1)):
        order = idx + 1
        own = None if breaks_a is None else (breaks_a if side == "a" else -breaks_a)
        players.append({"side": side, "name": name, "sets_won": live.sets_won[idx],
                        "games": None if current is None else current[idx], "serving": None if server is None else server == side,
                        "net_breaks": own, "stats": stats.get(order)})
    return {
        "sport": SPORT, "source": "espn", "game_id": match.match_id, "tour": match.tour, "tournament": match.tournament or None,
        "round": match.round_name or None, "state": "live", "status": match.status, "start_utc": match.start_utc,
        "best_of": best_of, "set_number": set_number, "sets": [list(s) for s in live.sets],
        "current_set": None if current is None else list(current), "sets_won": list(live.sets_won),
        "server": server, "first_server": first, "server_confirmed": bool(confirmed) if first is not None else None,
        "tiebreak": tiebreak,
        "net_breaks": None if breaks_a is None else {"a": breaks_a, "b": -breaks_a},
        "stats_available": any(p["stats"] for p in players), "players": players,
    }


def in_progress_matches(doc, tour: str) -> list:
    """[(TennisMatch, server "a"|"b"|None, format periods, stats by order)] for every in-progress singles match on one scoreboard."""
    raw = raw_index(doc)
    possession = lt_state.possession_map(doc)
    out = []
    for match in espn.parse_scoreboard(doc, tour):
        if match.status != lt_state.IN_PROGRESS:
            continue
        info = raw.get(match.match_id) or {}
        out.append((match, possession.get(match.match_id), info.get("periods"), _both_stats(info)))
    return out


def states_from_scoreboards(docs_by_tour, memory: ServerMemory) -> list:
    """The live state of every in-progress singles match across scoreboard documents, ONE state per match.

    The same match appears on every day's board of its tournament (a board lists the whole draw), and ``ServerMemory`` counts
    READS, so a match is derived once however many boards list it. `docs_by_tour` is [(tour, doc), ...]."""
    chosen: dict = {}
    for tour, doc in docs_by_tour:
        for item in in_progress_matches(doc, tour):
            chosen.setdefault((tour, item[0].match_id), item)
    out = []
    for match, server, periods, stats in chosen.values():
        state = derive(match, server, periods, stats, memory)
        if state is not None:
            out.append(state)
    return out


def _both_stats(info: Mapping) -> dict:
    return {1: (info.get("stats") or {}).get(1), 2: (info.get("stats") or {}).get(2)}


# ---------------------------------------------------------------------------
# the read
# ---------------------------------------------------------------------------

def scoreboard_dates(now: datetime) -> list:
    today = now.astimezone(timezone.utc)
    days = [today.date()]
    if today.hour < YESTERDAY_UNTIL_UTC_HOUR:
        days.append(today.date() - timedelta(days=1))
    return days


def needed(events, now: datetime) -> bool:
    """Is any tennis event on the board in play, or inside the read window around its listed start?"""
    lo, hi = now - timedelta(hours=LOOKBACK_HOURS), now + timedelta(minutes=LEAD_MINUTES)
    for ev in events or []:
        if str(ev.get("family") or "").upper() != SPORT:
            continue
        start = ev.get("_start")
        if ev.get("in_play") or (start is not None and lo <= start <= hi):
            return True
    return False


def fetch_and_store(now: datetime, fetch_json: Callable[[str], dict], *, memory: ServerMemory = MEMORY,
                    max_requests: int = MAX_REQUESTS_PER_PASS) -> dict:
    """One tennis pass over both tours. A tour whose every request failed leaves its matches' old entries (which then age
    out by themselves); a match that stopped being in progress is simply no longer refreshed."""
    report = {"requests": 0, "live": 0, "ok": [], "failed": [], "error": None}
    docs = []
    for tour in TOURS:
        got_any = False
        for day in scoreboard_dates(now):
            if report["requests"] >= max_requests:
                break
            report["requests"] += 1
            try:
                docs.append((tour, fetch_json(espn.scoreboard_url(tour, day.isoformat()))))
            except Exception as exc:  # noqa: BLE001
                report["error"] = f"{tour}: {type(exc).__name__}"
                continue
            got_any = True
        (report["ok"] if got_any else report["failed"]).append(tour)
    states = states_from_scoreboards(docs, memory)
    for state in states:
        store.put_base(SPORT, state["game_id"], state, now)
    if report["ok"]:
        store.STATUS["tennis_last_read_utc"] = ls.iso(now)
    report["live"] = len(states)
    if not report["failed"]:
        memory.forget_except([s["game_id"] for s in states])
    return report


# ---------------------------------------------------------------------------
# lookup and the snapshot row
# ---------------------------------------------------------------------------

def match(home_name: str, away_name: str, commence: Optional[datetime], games) -> Optional[dict]:
    """The ONE live match whose two players are the caller's two names (either order), with ``home`` / ``away`` laid out
    in the caller's order, or None (see names.py)."""
    hits = []
    for game in games:
        if not names.within(commence, ls.parse_utc(game.get("start_utc")), names.TENNIS_WINDOW):
            continue
        a, b = game["players"][0], game["players"][1]
        if names.same_player(home_name, a["name"]) and names.same_player(away_name, b["name"]):
            hits.append((game, "straight"))
        elif names.same_player(home_name, b["name"]) and names.same_player(away_name, a["name"]):
            hits.append((game, "crossed"))
    if len(hits) != 1:
        return None
    game, orientation = hits[0]
    view = dict(game)
    home, away = (game["players"][0], game["players"][1]) if orientation == "straight" else (game["players"][1], game["players"][0])
    view["home"], view["away"], view["orientation"] = dict(home), dict(away), orientation
    return view


def log_row(state: Mapping) -> dict:
    p = state.get("players") or [{}, {}]
    return {"t": state.get("as_of"), "sp": SPORT, "id": state.get("game_id"), "st": state.get("state"), "tr": state.get("tour"),
            "n": [p[0].get("name"), p[1].get("name")], "ss": state.get("sets"), "cs": state.get("current_set"),
            "sv": state.get("server"), "fs": state.get("first_server"), "ok": state.get("server_confirmed"),
            "nb": state.get("net_breaks"), "tb": state.get("tiebreak"),
            "stats": [p[0].get("stats"), p[1].get("stats")] if state.get("stats_available") else None}


def signature(row: Mapping):
    keys = ("sp", "id", "st", "ss", "cs", "sv", "nb", "tb", "stats")
    return json.dumps({k: row.get(k) for k in keys}, sort_keys=True, separators=(",", ":"))


def is_live_row(row: Mapping) -> bool:
    return row.get("st") == "live"
