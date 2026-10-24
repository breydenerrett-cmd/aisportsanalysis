"""Grade a ticket within minutes of its game going final: an in-app loop beside the engine's, fed by free live scores.

WHY (owner, 2026-10-22). Member tickets on the Oct 21 NBA games were still PENDING five hours after the games ended.
Bankroll, record and every lesson the coach learns change with each graded ticket, so a late grade is a wrong number.

THE TIMELINE THIS FIXES (Hornets @ Nets, tip 23:30Z, final about 02:00Z; ``docs/audit/2026-10-22/GRADING_DELAY.md``)
  23:30Z  tip. The member's ticket is OPEN in the ledger on the Fly volume.
  00:10Z  the ONLY NBA ``/scores`` poll of the night (it needs a game an hour old and the key unpolled for 8 h). It
          stores 21-15, ``completed: false``, and locks the key out until 08:10Z.
  ~02:00Z the game ends. Nothing is watching.
  every 15 min  the engine's settle pass asks the score store BAKED INTO THE IMAGE; the row still says in progress.
  06:00Z  the owner's screenshots: five open tickets on finished games.
  08:10Z+ the earliest the next poll could run, then a commit, then the next hourly redeploy.
So a final could not reach production before about 09:00Z, seven hours after the game.

WHAT THIS DOES. Every ``INTERVAL_SECONDS`` (5 minutes) one pass:
  1. gathers the distinct games behind OPEN tickets (the member and manual ledgers, and the AI hounds' ledger, all on
     the volume) whose scheduled start has passed;
  2. asks the free feeds for ONLY those games (``live_scores``: one ESPN scoreboard request per league-day, one MLB
     Stats API call per gamePk), caches each answer in a small table beside the app database, and backs off a game
     whose fetch failed;
  3. hands FINAL games to the EXISTING settle functions (``user_settle.settle`` for the member and manual ledgers,
     ``pack_settle.settle`` for the AI ledger) with the live finals laid over the stores they already read. No grading
     rule lives here: pushes, voids, postponed and cancelled handling, the average-price basis and the CLV all come
     from those functions, unchanged;
  4. if anything graded, rebuilds the public stats book at once, so the record and bankroll follow the grade.

GRADING A TICKET WITH NO LIVE ANSWER. A family or league this module cannot read (cricket, rugby, tennis, MMA) is not
touched: it stays on the old path. A game it cannot match unambiguously is not touched either.

THE HOUSE PACK IS READ, NOT WRITTEN. ``evidence/hounds_house_v1.jsonl`` is git-tracked and baked into the image, so the
app cannot append to it; those tickets are graded by the capture slot (``pack_settle`` in ``scripts/capture_slot.sh``).
The loop still shows their games' live state on the pages, but never settles them and the watchdog does not count them.

SAFE TO REPEAT AND TO RACE. A re-run adds nothing (each settle function writes one graded row per bet, ever). Two passes
at once (two machines on one volume, or a retry) are kept apart by a lock row with an expiry in the same sqlite file. The
settle step also takes the process-wide build gate (``src.appstate.freshness``) like every other writer, so it is never the
second heavy thing running on the 1 GB machine.

MEMORY. Nothing here reads a whole store: the ledgers are read the way settlement already reads them (and the parsed open
tickets are remembered until a ledger changes), the cache table holds one small row per open game, and the answers kept
are the wanted games only.

Paper only. Nothing here can place a bet anywhere. ``LIVE_SETTLE=off`` stops the loop; it is ON by default in code.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from src.hounds import live_scores as ls

logger = logging.getLogger("linehound.hounds.live_settle")

ENV_FLAG = "LIVE_SETTLE"
ENV_INTERVAL = "LIVE_SETTLE_INTERVAL_SECONDS"
ENV_DB = "LIVE_SETTLE_DB"
OFF_VALUES = ("off", "0", "false", "no")

INTERVAL_SECONDS = 300.0                 # the owner's "about 15 minutes" needs a pass well inside it: 5 minutes
MIN_INTERVAL_SECONDS = 30.0
WAIT_FOR_WARMUP_SECONDS = 600.0
LOCK_NAME = "live_settle_pass"
LOCK_TTL_SECONDS = 240.0                 # shorter than a pass interval: a crashed holder frees itself before the next try
# A game whose start passed more than this long ago and that is still not final is asked only hourly: it is postponed,
# very late, or one this feed cannot answer, and a five-minute poll of it would be noise.
SLOW_LANE_AFTER = timedelta(hours=8)
SLOW_LANE_EVERY = timedelta(minutes=60)
WATCH_UNTIL = timedelta(days=5)          # past this the old path's own rules (the 72 hour and 4 day voids) decide
BACKOFF_BASE_SECONDS = 60.0
BACKOFF_MAX_SECONDS = 30 * 60.0
SETTLE_BACKOFF_BASE = timedelta(minutes=5)
SETTLE_BACKOFF_MAX = timedelta(hours=2)
MAX_REQUESTS_PER_PASS = 40               # a bug must not turn into a hundred scoreboard requests
KEEP_FINAL_DAYS = 14                     # cache rows of finished games are pruned after this
#: The owner's line: an open ticket this long after its game's scheduled start raises an alert (watchdog).
OVERDUE_HOURS = 4.0
#: Tennis and MMA get this much longer before the alert counts: a match is played in order of play, "followed by" the one
#: before it, and a bout fights by its place on the card, so the listed start can be many hours before the first ball or bell.
FREE_OVERDUE_EXTRA_HOURS = 4.0
#: A "live" answer older than this is treated as not seen: the feed stopped answering, so the ticket is not "in play".
STALE_LIVE_MINUTES = 90.0

SETTLED_HERE = frozenset({"user", "manual", "ai"})

STATUS: dict = {"enabled": False, "passes": 0, "running": False, "last_pass_utc": None, "last_report": None,
                "last_error": None}
_STATE_LOCK = threading.Lock()


def enabled(env: Optional[Mapping] = None) -> bool:
    """ON unless ``LIVE_SETTLE`` says off. Default on in code (owner, 2026-10-22): a ticket must grade without anyone
    having to remember to switch a thing on."""
    source = env if env is not None else os.environ
    return str(source.get(ENV_FLAG) or "on").strip().lower() not in OFF_VALUES


def interval_seconds(env: Optional[Mapping] = None) -> float:
    source = env if env is not None else os.environ
    raw = str(source.get(ENV_INTERVAL) or "").strip()
    if not raw:
        return INTERVAL_SECONDS
    try:
        return max(MIN_INTERVAL_SECONDS, float(raw))
    except ValueError:
        logger.warning("%s=%r is not a number; using %ss", ENV_INTERVAL, raw, INTERVAL_SECONDS)
        return INTERVAL_SECONDS


# ---------------------------------------------------------------------------
# the cache table, on the volume
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS live_games (
  game_key TEXT PRIMARY KEY,            -- the ticket's event id: one row per game, so a re-run cannot add a second
  sport TEXT NOT NULL, league TEXT, home_team TEXT, away_team TEXT, start_utc TEXT, slate_date TEXT, game_pk TEXT,
  supported INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL, home_score REAL, away_score REAL, detail TEXT, source TEXT, source_id TEXT,
  first_seen_utc TEXT, updated_utc TEXT, final_utc TEXT, applied_utc TEXT,
  fails INTEGER NOT NULL DEFAULT 0, next_try_utc TEXT, last_error TEXT,
  settle_tries INTEGER NOT NULL DEFAULT 0, settle_next_utc TEXT,
  payload TEXT,                         -- tennis / MMA: the free reader's whole result row (a winner or a named void), as JSON
  progress TEXT,                        -- a live game's {period, clock, name, label} as JSON: the bet alerts' "halftime" and "late in the game"
  sched_utc TEXT                        -- the start time the scoreboard itself last gave (the odds feed's start can be hours off): "starting soon" prefers it
);
CREATE TABLE IF NOT EXISTS live_lock (name TEXT PRIMARY KEY, holder TEXT NOT NULL, expires_utc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS live_meta (key TEXT PRIMARY KEY, value TEXT);
"""


def db_path(env: Optional[Mapping] = None) -> Path:
    """Beside the app database (the persistent volume in production), never inside the repo: a redeploy replaces the
    repo and the image, not the volume."""
    source = env if env is not None else os.environ
    override = str(source.get(ENV_DB) or "").strip()
    if override:
        return Path(override)
    from src.appstate import users
    return users.db_path().parent / "live_settle.db"


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    target = Path(path) if path is not None else db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=15.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(live_games)")}
    if "payload" not in columns:
        conn.execute("ALTER TABLE live_games ADD COLUMN payload TEXT")       # a cache file made before tennis and MMA
    if "progress" not in columns:
        conn.execute("ALTER TABLE live_games ADD COLUMN progress TEXT")      # a cache file made before the bet alerts
    if "sched_utc" not in columns:
        conn.execute("ALTER TABLE live_games ADD COLUMN sched_utc TEXT")     # a cache file made before the scheduled-time fix
    return conn


def acquire_lock(conn: sqlite3.Connection, holder: str, now: datetime, ttl: float = LOCK_TTL_SECONDS) -> bool:
    """Take the pass lock unless someone else holds an unexpired one. One writer at a time, across threads and machines."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT holder, expires_utc FROM live_lock WHERE name=?", (LOCK_NAME,)).fetchone()
        if row is not None and row["holder"] != holder and (ls.parse_utc(row["expires_utc"]) or now) > now:
            conn.execute("ROLLBACK")
            return False
        conn.execute("INSERT OR REPLACE INTO live_lock(name, holder, expires_utc) VALUES (?,?,?)",
                     (LOCK_NAME, holder, ls.iso(now + timedelta(seconds=ttl))))
        conn.execute("COMMIT")
        return True
    except Exception:
        conn.execute("ROLLBACK")
        raise


def release_lock(conn: sqlite3.Connection, holder: str) -> None:
    conn.execute("DELETE FROM live_lock WHERE name=? AND holder=?", (LOCK_NAME, holder))


def _meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO live_meta(key, value) VALUES (?,?)", (key, value))


def _meta_get(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM live_meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


# ---------------------------------------------------------------------------
# open tickets, grouped into games
# ---------------------------------------------------------------------------

@dataclass
class Game:
    key: str                         # the ticket's event id
    sport: str                       # upper-case family code
    home_team: str
    away_team: str
    start: Optional[datetime]
    slate_date: Optional[str]
    game_pk: Optional[str] = None
    league: Optional[str] = None
    sources: set = field(default_factory=set)       # "user" | "manual" | "ai" settle here; "house" is read-only

    def settles_here(self) -> bool:
        """Some open ticket on this game is in a ledger this loop writes (the house pack's is not)."""
        return bool(self.sources & SETTLED_HERE)
    tickets: int = 0

    def espn_league(self) -> Optional[str]:
        if self.sport == ls.MLB_FAMILY or self.sport in ls.FREE_FAMILIES:
            return None
        return ls.espn_league_for(self.sport, self.league)

    def free_family(self) -> Optional[str]:
        """"TENNIS" or "MMA": settled by the free readers in src/pipeline/allsports_free_results.py, not a scoreboard."""
        return self.sport if self.sport in ls.FREE_FAMILIES else None

    def supported(self) -> bool:
        return ls.supported(self.sport, self.league, self.game_pk)


def ledger_paths(env: Optional[Mapping] = None) -> dict:
    """{label: path} of the ledgers this loop reads: the three on the volume that it also settles, and the house pack's
    (git-tracked, in the image) READ-ONLY, so its tickets show a live state on the pages."""
    from src.hounds import ai_defs, pack_run, user_engine
    return {"user": user_engine.ledger_path(), "manual": user_engine.manual_ledger_path(),
            "ai": ai_defs.ledger_path(), "house": pack_run.ledger_path()}


# (path) -> (mtime_ns, size, parsed open tickets); a ledger that has not changed is not parsed again
_OPEN_CACHE: dict = {}


def _slim_user(row: Mapping, label: str) -> dict:
    return {"source": label, "event_id": row.get("event_id"), "sport": str(row.get("sport") or "").upper(),
            "home_team": row.get("home_team"), "away_team": row.get("away_team"),
            "start": row.get("commence_time") or row.get("start_utc"), "slate_date": row.get("slate_date"),
            "game_pk": row.get("game_pk"), "league": row.get("league"), "bet_id": row.get("bet_id"),
            "hound_id": row.get("hound_id"), "segment": row.get("segment") or "forward",
            # what the bet alerts need to word a ticket and to tell whether it is winning (alert_live.py)
            "provenance": row.get("provenance"), "role": row.get("role"), "market": row.get("market"),
            "side": row.get("side"), "line": row.get("line"), "selection": row.get("selection"),
            "price": row.get("price"), "units": row.get("units"), "stake_units": row.get("stake_units"),
            "player": row.get("player")}


def _slim_pack(row: Mapping, label: str = "ai") -> dict:
    return {"source": label, "event_id": row.get("event_id"), "sport": str(row.get("sport") or "").upper(),
            "home_team": row.get("home"), "away_team": row.get("away"), "start": row.get("start_utc"),
            "slate_date": row.get("date"), "game_pk": row.get("game_pk"), "league": row.get("league"),
            "bet_id": row.get("row_hash") or "|".join(str(row.get(k)) for k in
                                                      ("hound_id", "event_id", "market", "selection")),
            "hound_id": row.get("hound_id"), "segment": row.get("segment") or "forward"}


def open_tickets_in(path: str, label: str) -> list:
    """The OPEN tickets of one ledger as slim dicts: bets with no graded row. Cached until the file changes."""
    from src.ledger.chain import HashChainLedger
    target = Path(path)
    try:
        stat = target.stat()
    except OSError:
        return []
    sig = (stat.st_mtime_ns, stat.st_size)
    hit = _OPEN_CACHE.get(str(target))
    if hit is not None and hit[0] == sig:
        return hit[1]
    rows = HashChainLedger(str(target)).read()
    out: list = []
    if label in ("ai", "house"):
        from src.hounds import pack_run, pack_settle
        graded = {pack_settle._key(r) for r in rows
                  if r.get("kind") == pack_run.KIND_GRADED and r.get("result") in pack_settle.FINAL}
        for r in rows:
            if r.get("kind") == pack_run.KIND_BET and r.get("segment") != "replay" \
                    and pack_settle._key(r) not in graded:
                out.append(_slim_pack(r, label))
    else:
        from src.hounds import user_settle
        from src.hounds import user_engine
        graded = {r["bet_id"] for r in rows if r.get("kind") == user_settle.KIND_GRADED}
        for r in rows:
            if r.get("kind") == user_engine.KIND_BET and r.get("bet_id") not in graded:
                out.append(_slim_user(r, label))
    _OPEN_CACHE[str(target)] = (sig, out)
    return out


def open_games(now: datetime, paths: Optional[Mapping] = None) -> list:
    """The distinct games behind open tickets. A ticket with no event id or no start is skipped (nothing to look up)."""
    games: dict = {}
    for label, path in (paths if paths is not None else ledger_paths()).items():
        for t in open_tickets_in(path, label):
            if not t.get("event_id") or not t.get("sport"):
                continue
            start = ls.parse_utc(t.get("start"))
            game = games.get(t["event_id"])
            if game is None:
                game = games[t["event_id"]] = Game(
                    key=str(t["event_id"]), sport=t["sport"], home_team=t.get("home_team") or "",
                    away_team=t.get("away_team") or "", start=start, slate_date=t.get("slate_date"),
                    game_pk=None if t.get("game_pk") in (None, "", "None") else str(t["game_pk"]),
                    league=t.get("league"))
            game.sources.add(t["source"])
            game.tickets += 1
    return list(games.values())


# ---------------------------------------------------------------------------
# the cache: placeholders, due games, answers
# ---------------------------------------------------------------------------

def _row(conn: sqlite3.Connection, key: str):
    return conn.execute("SELECT * FROM live_games WHERE game_key=?", (key,)).fetchone()


def ensure_rows(conn: sqlite3.Connection, games: Sequence[Game], now: datetime) -> None:
    """One placeholder row per open game, so the pages can say "starts in 3h" before the first fetch."""
    for g in games:
        if _row(conn, g.key) is not None:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO live_games(game_key, sport, league, home_team, away_team, start_utc, slate_date,"
            " game_pk, supported, state, first_seen_utc, updated_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (g.key, g.sport, g.league, g.home_team, g.away_team, ls.iso(g.start) if g.start else None, g.slate_date,
             g.game_pk, 1 if g.supported() else 0, ls.UPCOMING, ls.iso(now), ls.iso(now)))


def is_due(game: Game, row, now: datetime) -> bool:
    """Should this game be asked about now? Started, not already final, outside any backoff, inside the watch window,
    and (long after the start) only on the slow lane."""
    if game.start is None or game.start > now or not game.supported():
        return False
    if row is not None and row["state"] == ls.FINAL:
        return False
    age = now - game.start
    if age > WATCH_UNTIL:
        return False
    if row is not None:
        nxt = ls.parse_utc(row["next_try_utc"])
        if nxt is not None and nxt > now:
            return False
        seen = ls.parse_utc(row["updated_utc"])
        if age > SLOW_LANE_AFTER and row["state"] != ls.UPCOMING and seen is not None \
                and now - seen < SLOW_LANE_EVERY and not row["fails"]:
            return False
    return True


def _store_answer(conn: sqlite3.Connection, game: Game, answer: Mapping, now: datetime) -> None:
    prior = _row(conn, game.key)
    final_utc = (prior["final_utc"] if prior is not None and prior["final_utc"] else
                 (ls.iso(now) if answer["state"] == ls.FINAL else None))
    conn.execute(
        "UPDATE live_games SET state=?, home_score=?, away_score=?, detail=?, source=?, source_id=?, updated_utc=?,"
        " final_utc=?, fails=0, next_try_utc=NULL, last_error=NULL, payload=COALESCE(?, payload), progress=?,"
        " sched_utc=COALESCE(?, sched_utc) WHERE game_key=?",
        (answer["state"], answer.get("home_score"), answer.get("away_score"), answer.get("detail"),
         answer.get("source"), answer.get("source_id"), ls.iso(now), final_utc,
         json.dumps(answer["payload"], sort_keys=True) if answer.get("payload") else None,
         json.dumps(answer["progress"], sort_keys=True) if answer.get("progress") else None,
         _sched_of(answer), game.key))


def _sched_of(answer: Mapping) -> Optional[str]:
    """The scoreboard's own scheduled start from an answer, normalised, or None (kept apart from ``start_utc``, which is the
    ticket's odds-feed start and drives when the loop asks)."""
    parsed = ls.parse_utc(answer.get("start_utc"))
    return ls.iso(parsed) if parsed is not None else None


def _store_failure(conn: sqlite3.Connection, game: Game, error: str, now: datetime) -> None:
    prior = _row(conn, game.key)
    fails = (prior["fails"] if prior is not None else 0) + 1
    wait = min(BACKOFF_BASE_SECONDS * (2 ** (fails - 1)), BACKOFF_MAX_SECONDS)
    conn.execute("UPDATE live_games SET fails=?, next_try_utc=?, last_error=?, updated_utc=updated_utc WHERE game_key=?",
                 (fails, ls.iso(now + timedelta(seconds=wait)), error[:300], game.key))
    logger.warning("live settle: could not read %s (%s); retry in %ds", game.key, error[:120], wait)


def fetch_due(conn: sqlite3.Connection, due: Sequence[Game], now: datetime, *,
              fetch_json: Callable[[str], dict], fetch_instances: Optional[Callable] = None,
              max_requests: int = MAX_REQUESTS_PER_PASS, mma_provider=None) -> dict:
    """Ask the feeds about the due games and store each answer. Returns {"requests", "answered", "failed"}.

    ESPN games are grouped by (league, day) so ONE scoreboard request serves every open game of that league that day;
    the neighbouring days are tried only for a game the first day did not list. MLB games are one call each."""
    report = {"requests": 0, "answered": 0, "failed": 0}
    observed = ls.iso(now)
    espn = [g for g in due if g.espn_league()]
    mlb = [g for g in due if g.sport == ls.MLB_FAMILY]
    for g in mlb:
        if report["requests"] >= max_requests:
            break
        report["requests"] += 1
        try:
            answer = ls.mlb_answer(g.game_pk, fetch_instances)
        except Exception as exc:  # noqa: BLE001 -- one bad call must not stop the others
            report["failed"] += 1
            _store_failure(conn, g, repr(exc), now)
            continue
        if answer is None:
            continue
        _store_answer(conn, g, answer, now)
        report["answered"] += 1
    pending = {g.key: g for g in espn}
    cache: dict = {}
    for attempt in range(3):                     # the slate day, then the day before, then the day after
        groups: dict = {}
        for g in pending.values():
            days = ls.days_to_ask(g.slate_date, g.start)
            if attempt < len(days):
                groups.setdefault((g.espn_league(), days[attempt]), []).append(g)
        if not groups:
            break
        for (league, day), members in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            if (league, day) not in cache:
                if report["requests"] >= max_requests:
                    break
                report["requests"] += 1
                try:
                    cache[(league, day)] = fetch_json(ls.scoreboard_url(league, day))
                except Exception as exc:  # noqa: BLE001 -- recorded per game, retried with backoff
                    cache[(league, day)] = None
                    report["failed"] += len(members)
                    for g in members:
                        _store_failure(conn, g, repr(exc), now)
                    for g in members:
                        pending.pop(g.key, None)
                    continue
            payload = cache[(league, day)]
            if payload is None:
                continue
            wanted = [{"key": g.key, "home_team": g.home_team, "away_team": g.away_team, "start": g.start}
                      for g in members if g.key in pending]
            for key, answer in ls.espn_answers(payload, league, wanted, observed).items():
                _store_answer(conn, pending.pop(key), answer, now)
                report["answered"] += 1
    free = [g for g in due if g.free_family()]
    if free:
        fetch_free(conn, free, now, fetch_json=fetch_json, report=report, max_requests=max_requests,
                   mma_provider=mma_provider)
    return report


# ---------------------------------------------------------------------------
# tennis and MMA: the free readers the capture slot already uses, asked for only the open tickets' matches
# ---------------------------------------------------------------------------

#: A tennis match or a bout that the free reader could not answer yet (not finished, or not listed) is asked again after
#: this, not every five minutes: a tennis scoreboard holds a whole draw and an MMA card is ~16 requests.
FREE_RECHECK = timedelta(minutes=10)


def _free_event(g: Game) -> dict:
    """The event dict ``allsports_free_results`` reads (its ``unresolved_events`` builds the same from the odds store)."""
    return {"event_id": g.key, "family": g.sport, "commence_time": ls.iso(g.start), "_start": g.start,
            "home_team": g.home_team, "away_team": g.away_team, "league": g.league or g.sport.lower()}


def _defer(conn: sqlite3.Connection, game: Game, now: datetime, wait: timedelta = FREE_RECHECK) -> None:
    conn.execute("UPDATE live_games SET next_try_utc=? WHERE game_key=?", (ls.iso(now + wait), game.key))


def _apply_free(conn: sqlite3.Connection, games: Sequence[Game], rows: Mapping, now: datetime, report: dict) -> None:
    """A game the reader returned a settled row for is FINAL (the row is kept whole: a winner, or a named void); one it did
    not is asked again later. Scores stay empty: a 1-0 match indicator is not a score and the page must not print it."""
    for g in games:
        row = rows.get(g.key)
        if row is None:
            _defer(conn, g, now)
            continue
        void = row.get("void_reason")
        evidence = row.get("evidence") or {}
        answer = {"state": ls.FINAL, "home_score": None, "away_score": None,
                  "detail": f"Void: {void}"[:200] if void else "Final", "source": row.get("source"),
                  "source_id": str(evidence.get("espn_match_id") or evidence.get("espn_bout_id") or ""),
                  "payload": row}
        _store_answer(conn, g, answer, now)
        report["answered"] += 1


def fetch_free(conn: sqlite3.Connection, free: Sequence[Game], now: datetime, *, fetch_json: Callable[[str], dict],
               report: dict, max_requests: int, mma_provider=None) -> None:
    """Settle tennis and MMA through ``allsports_free_results`` (``tennis_rows`` / ``mma_rows``), the SAME matching and
    settlement rules the capture slot applies: both names must agree, exactly one ESPN match may fit, a retirement before a
    set is completed, a walkover, a draw and a no contest are named voids, an inferred fighter replacement is never trusted.
    Nothing here re-decides any of it; this only asks sooner, for the open tickets' matches only."""
    from src.pipeline import allsports_free_results as fr
    from src.providers import espn_tennis_results as tennis_src
    observed = ls.iso(now)
    tennis = [g for g in free if g.sport == ls.TENNIS_FAMILY]
    mma = [g for g in free if g.sport == ls.MMA_FAMILY]
    if tennis:
        def get_json(url: str) -> dict:
            if report["requests"] >= max_requests:
                raise tennis_src.EspnTennisError("this pass's request cap is reached")
            report["requests"] += 1
            try:
                return fetch_json(url)
            except Exception as exc:  # noqa: BLE001 -- the reader stops on its own error type
                raise tennis_src.EspnTennisError(f"{type(exc).__name__}: {str(exc)[:160]}") from None

        events = [_free_event(g) for g in tennis]
        feed = tennis_src.EspnTennisFeed(get_json=get_json, sleep=lambda _s: None, now=lambda: now)
        fetched = fr.fetch_tennis_matches(events, feed)
        if fetched["errors"] and not fetched["matches"]:
            for g in tennis:
                report["failed"] += 1
                _store_failure(conn, g, "; ".join(fetched["errors"]), now)
        else:
            out = fr.tennis_rows(events, fetched["matches"], observed)
            _apply_free(conn, tennis, {r["event_id"]: r for r in out["rows"]}, now, report)
    if mma:
        provider = mma_provider or fr.default_mma_provider()
        events = [_free_event(g) for g in mma]
        out = fr.mma_rows(events, provider, now, observed)
        stats = getattr(getattr(provider, "_fetcher", None), "stats", None)
        if isinstance(stats, dict):
            report["requests"] += int(stats.get("requests") or 0)
        if out["errors"] and not out["rows"]:
            for g in mma:
                report["failed"] += 1
                _store_failure(conn, g, "; ".join(out["errors"]), now)
        else:
            _apply_free(conn, mma, {r["event_id"]: r for r in out["rows"]}, now, report)


# ---------------------------------------------------------------------------
# settlement, through the existing functions
# ---------------------------------------------------------------------------

def final_rows(conn: sqlite3.Connection, games: Sequence[Game], now: datetime) -> dict:
    """{game key: cache row} for the open games the cache says are final and whose settle backoff has run out."""
    now_iso = ls.iso(now)
    out: dict = {}
    for g in games:
        row = _row(conn, g.key)
        if row is not None and row["state"] == ls.FINAL and (
                (row["home_score"] is not None and row["away_score"] is not None) or row["payload"]):
            nxt = row["settle_next_utc"]
            if nxt is None or nxt <= now_iso:
                out[g.key] = row
    return out


def allsports_overlay(finals: Mapping, games: Mapping) -> dict:
    """The live finals as rows in the all-sports score store's shape, for ``allsports_scores.grade_bet``."""
    out = {}
    for key, row in finals.items():
        g = games[key]
        if g.sport == ls.MLB_FAMILY or g.sport == "NFL":
            continue
        if g.free_family():
            # tennis / MMA: the free reader's own row (winner as 1-0, or a named void), exactly as the capture slot stores it
            try:
                kept = json.loads(row["payload"] or "")
            except ValueError:
                continue
            if isinstance(kept, dict) and kept.get("completed") and kept.get("event_id") == key:
                out[key] = dict(kept, source="live_settle:" + str(kept.get("source") or row["source"]))
            continue
        home, away = float(row["home_score"]), float(row["away_score"])
        out[key] = {"kind": "score", "event_id": key, "completed": True, "home_score": home, "away_score": away,
                    "outcome": "home" if home > away else "away" if away > home else "draw",
                    "commence_time": ls.iso(g.start) if g.start else None, "home_team": g.home_team,
                    "away_team": g.away_team, "source": "live_settle:" + str(row["source"]),
                    "observed_utc": row["updated_utc"]}
    return out


def mlb_overlay(finals: Mapping, games: Mapping) -> dict:
    """{game_pk: results-store-shaped row} for the live MLB finals."""
    out = {}
    for key, row in finals.items():
        g = games[key]
        if g.sport != ls.MLB_FAMILY or not g.game_pk:
            continue
        home, away = int(row["home_score"]), int(row["away_score"])
        out[str(g.game_pk)] = {"game_pk": str(g.game_pk), "date": g.slate_date, "away_score": away, "home_score": home,
                               "home_won": 1 if home > away else 0 if away > home else None,
                               "source": "live_settle:" + str(row["source"])}
    return out


def nfl_overlay(finals: Mapping, games: Mapping) -> dict:
    """{slate date: {(away code, home code): {home_score, away_score}}} for the live NFL finals."""
    from src.sports import nfl_teams
    out: dict = {}
    for key, row in finals.items():
        g = games[key]
        if g.sport != "NFL":
            continue
        pair = (nfl_teams.abbrev(g.away_team), nfl_teams.abbrev(g.home_team))
        if None in pair:
            continue
        out.setdefault(g.slate_date, {})[pair] = {"home_score": int(row["home_score"]),
                                                  "away_score": int(row["away_score"])}
    return out


def _merged_allsports(overlay: Mapping, load_index: Optional[Callable[[], Mapping]] = None) -> dict:
    """The vendor score store with the live finals laid under it: a completed vendor row wins (it is the feed that
    supplied the price), a live final fills the games the vendor has not finished."""
    if load_index is None:
        from src.pipeline import allsports_scores
        load_index = allsports_scores.load_index
    merged = dict(load_index())
    for key, row in overlay.items():
        if not (merged.get(key) or {}).get("completed"):
            merged[key] = row
    return merged


def _lookup_kwargs() -> dict:
    from src.hounds import user_runner
    kwargs = {}
    postponed, cancelled = user_runner._postponed_lookup(), user_runner._cancelled_lookup()
    if postponed is not None:
        kwargs["postponed_lookup"] = postponed
    if cancelled is not None:
        kwargs["cancelled_lookup"] = cancelled
    return kwargs


def settle_user_ledgers(now: datetime, finals: Mapping, games: Mapping, *, paths: Mapping,
                        read_mlb_results: Optional[Callable[[], dict]] = None, settle_kwargs: Optional[dict] = None,
                        load_index: Optional[Callable[[], Mapping]] = None) -> int:
    """Run ``user_settle.settle`` over the member and manual ledgers with the live finals laid over its stores."""
    from src.hounds import user_settle
    overlay_allsports = allsports_overlay(finals, games)
    overlay_mlb = mlb_overlay(finals, games)
    overlay_nfl = nfl_overlay(finals, games)
    results = None
    if overlay_mlb:
        if read_mlb_results is None:
            from src.pipeline import history
            read_mlb_results = history.read_results
        results = dict(read_mlb_results())
        for pk, row in overlay_mlb.items():
            if pk not in results:
                results[pk] = row
    nfl_fn = None
    if overlay_nfl:
        def nfl_fn(date: str) -> dict:
            # the existing source first (nflverse), the live finals over it: a game ESPN cannot match still grades the old way
            out: dict = {}
            try:
                out.update(user_settle.default_nfl_results(date))
            except Exception as exc:  # noqa: BLE001 -- no scores yet is pending, as in user_settle itself
                logger.info("live settle: NFL scores for %s unavailable from the schedule: %r", date, exc)
            out.update(overlay_nfl.get(date) or {})
            return out
    kwargs = dict(settle_kwargs) if settle_kwargs is not None else _lookup_kwargs()
    if results is not None:
        kwargs["mlb_results"] = results
    if nfl_fn is not None:
        kwargs["nfl_results"] = nfl_fn
    graded = 0
    for label in ("user", "manual"):
        path = paths.get(label)
        if not path or not Path(path).exists():
            continue
        report = user_settle.settle(ledger=path, now=now, allsports_results=lambda: _merged_allsports(overlay_allsports, load_index),
                                    **kwargs)
        graded += int(report.get("graded") or 0)
    return graded


def settle_ai_ledger(now: datetime, finals: Mapping, games: Mapping, *, path: str,
                     stores_loader: Optional[Callable] = None,
                     load_index: Optional[Callable[[], Mapping]] = None) -> int:
    """Run ``pack_settle.settle`` over the AI hounds' ledger. The stores are loaded for the bets' dates exactly as the
    AI runner does (the close and the CLV come from the odds store, and a grade written without them would lose its CLV
    for good), with the live finals added to the results it reads."""
    from src.hounds import ai_defs, pack_settle
    from src.hounds.pack import base
    if not path or not Path(path).exists():
        return 0
    dates = sorted({g.slate_date for g in games.values() if g.slate_date and "ai" in g.sources})
    if not dates:
        return 0
    if stores_loader is None:
        def stores_loader():
            from datetime import date as _date
            since = max(base.SEAL_FLOOR, base.day_before(dates[0], 3))
            until = (_date.fromisoformat(dates[-1]) + timedelta(days=2)).isoformat()
            return base.load_stores(since=since, until=until, sports=ai_defs.all_sports() or None)
    stores = stores_loader()
    stores.allsports_results = _merged_allsports(allsports_overlay(finals, games), load_index)
    for pk, row in mlb_overlay(finals, games).items():
        if not any(str(x.get("game_pk")) == pk for x in stores.mlb_games):
            stores.mlb_games.append({"game_pk": pk, "date": row["date"], "start_utc": None,
                                     "away_score": row["away_score"], "home_score": row["home_score"],
                                     "source": row["source"]})
    return int(pack_settle.settle(stores, now=now, path=path).get("graded") or 0)


def run_settle(conn: sqlite3.Connection, games: Sequence[Game], now: datetime, *, paths: Mapping,
               settle_kwargs: Optional[dict] = None, read_mlb_results: Optional[Callable] = None,
               stores_loader: Optional[Callable] = None, load_index: Optional[Callable[[], Mapping]] = None) -> dict:
    """Settle every open game the cache says is final; record the outcome per game. Returns {"graded", "games"}."""
    from src.appstate import freshness
    by_key = {g.key: g for g in games}
    finals = final_rows(conn, games, now)
    if not finals:
        return {"graded": 0, "games": 0}
    graded = 0
    with freshness._gated_build():
        if any(k for k, g in by_key.items() if k in finals and g.sources & {"user", "manual"}):
            graded += settle_user_ledgers(now, finals, by_key, paths=paths, settle_kwargs=settle_kwargs,
                                          read_mlb_results=read_mlb_results, load_index=load_index)
        if any(k for k, g in by_key.items() if k in finals and "ai" in g.sources):
            try:
                graded += settle_ai_ledger(now, finals, by_key, path=paths.get("ai"), stores_loader=stores_loader,
                                        load_index=load_index)
            except Exception:  # noqa: BLE001 -- the AI ledger failing must not undo the member grades
                logger.exception("live settle: the AI ledger could not be settled")
    # Which of these games still have an open ticket? Re-read the (changed) ledgers; those are retried with a backoff.
    still = {g.key for g in open_games(now, paths)}
    for key in finals:
        if not by_key[key].settles_here():
            continue                                     # a house-pack game: graded by the capture slot, not here
        if key in still:
            row = _row(conn, key)
            tries = (row["settle_tries"] if row is not None else 0) + 1
            wait = min(SETTLE_BACKOFF_BASE * (2 ** (tries - 1)), SETTLE_BACKOFF_MAX)
            conn.execute("UPDATE live_games SET settle_tries=?, settle_next_utc=? WHERE game_key=?",
                         (tries, ls.iso(now + wait), key))
        else:
            conn.execute("UPDATE live_games SET applied_utc=? WHERE game_key=?", (ls.iso(now), key))
    if graded:
        _meta_set(conn, "last_graded_utc", ls.iso(now))
    return {"graded": graded, "games": len(finals)}


# ---------------------------------------------------------------------------
# one pass
# ---------------------------------------------------------------------------

def alerts_scan(conn: sqlite3.Connection, now: datetime, paths: Mapping) -> Optional[dict]:
    """Queue the bet alerts this pass's cache implies. Never raises, never fetches; None when it could not run."""
    try:
        from src.notify import alert_live
        return alert_live.scan(conn, now, paths)
    except Exception as exc:  # noqa: BLE001 -- an alert is a courtesy; the grade must not depend on it
        logger.error("live settle: bet alert scan failed: %s", type(exc).__name__)
        return None


def default_fetch_json() -> Callable[[str], dict]:
    """Free ESPN JSON through the data service's polite client: one request at a time, retries with backoff, a hard
    request cap, and NO cache reuse (a live score must be the live score)."""
    from src.datasvc.http import PoliteFetcher
    cache = db_path().parent / "live_settle_http"
    fetcher = PoliteFetcher(cache_dir=cache, delay_s=0.3, max_requests=MAX_REQUESTS_PER_PASS + 10, retries=2,
                            timeout_s=20.0)
    return lambda url: fetcher.get_json(url, use_cache=False)


def run_pass(*, now: Optional[datetime] = None, conn: Optional[sqlite3.Connection] = None,
             paths: Optional[Mapping] = None, fetch_json: Optional[Callable[[str], dict]] = None,
             fetch_instances: Optional[Callable] = None, settle: bool = True,
             settle_kwargs: Optional[dict] = None, read_mlb_results: Optional[Callable] = None,
             stores_loader: Optional[Callable] = None, refresh_stats: Optional[Callable[[], object]] = None,
             holder: Optional[str] = None, load_index: Optional[Callable[[], Mapping]] = None,
             mma_provider=None) -> dict:
    """One pass: gather, fetch, settle. Returns a small report; raises only on a bug (the loop catches it)."""
    moment = now or ls.utcnow()
    own = conn is None
    conn = conn or connect()
    holder = holder or f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    report: dict = {"at": ls.iso(moment), "games": 0, "due": 0, "fetch": None, "settle": None, "graded": 0,
                    "paper_only": True}
    try:
        if not acquire_lock(conn, holder, moment):
            report["skipped"] = "another pass holds the lock"
            return report
        try:
            paths = paths if paths is not None else ledger_paths()
            games = open_games(moment, paths)
            report["games"] = len(games)
            ensure_rows(conn, games, moment)
            due = [g for g in games if is_due(g, _row(conn, g.key), moment)]
            report["due"] = len(due)
            if due:
                if fetch_json is None:
                    fetch_json = default_fetch_json()
                report["fetch"] = fetch_due(conn, due, moment, fetch_json=fetch_json, fetch_instances=fetch_instances,
                                            mma_provider=mma_provider)
            # Bet alerts ("starting soon", "live update") read what this pass just cached, BEFORE the settle below so the
            # "final" update goes out ahead of the grade. They only write rows into the alert outbox (a local sqlite
            # insert; the dispatcher thread sends them) and never raise: no network call and no wait on the grading path.
            report["alerts"] = alerts_scan(conn, moment, paths)
            if settle:
                # The lock was taken before the fetches, and a slow feed with retries can outlast its life. Take it again
                # (a renewal when it is still ours) and settle only if no other pass took it meanwhile: the ledger append
                # itself has no lock, so two writers must never be in settle together (verification, 2026-10-22).
                if not acquire_lock(conn, holder, ls.utcnow() if now is None else moment):
                    report["skipped"] = "another pass took the lock while this one was fetching"
                else:
                    out = run_settle(conn, games, moment, paths=paths, settle_kwargs=settle_kwargs,
                                     read_mlb_results=read_mlb_results, stores_loader=stores_loader,
                                     load_index=load_index)
                    report["settle"], report["graded"] = out, out["graded"]
            _meta_set(conn, "last_pass_utc", ls.iso(moment))
            _prune(conn, moment)
        finally:
            release_lock(conn, holder)
    finally:
        if own:
            conn.close()
    if report["graded"]:
        try:
            if refresh_stats is not None:
                refresh_stats()
            else:
                from src.hounds import stats
                stats.refresh_async()
        except Exception:  # noqa: BLE001 -- the next request after a ledger change rebuilds on its own
            logger.exception("live settle: could not start the stats rebuild")
    return report


def _prune(conn: sqlite3.Connection, now: datetime) -> None:
    cutoff = ls.iso(now - timedelta(days=KEEP_FINAL_DAYS))
    conn.execute("DELETE FROM live_games WHERE updated_utc < ? AND (applied_utc IS NOT NULL OR final_utc IS NULL)",
                 (cutoff,))


def pass_safely(**kwargs) -> dict:
    """``run_pass`` that never raises: a failure is logged and kept for /health and the admin view."""
    with _STATE_LOCK:
        STATUS["running"] = True
    try:
        report = run_pass(**kwargs)
        STATUS["last_report"], STATUS["last_error"] = report, None
        if report.get("graded") or report.get("due"):
            logger.info("live settle pass: %s", report)
        return report
    except Exception as exc:  # noqa: BLE001 -- the loop must outlive any one bad pass
        logger.exception("live settle pass failed")
        STATUS["last_error"] = repr(exc)
        return {"error": repr(exc)}
    finally:
        with _STATE_LOCK:
            STATUS["running"] = False
            STATUS["passes"] += 1
            STATUS["last_pass_utc"] = ls.iso(ls.utcnow())


def start_loop(*, interval_s: Optional[float] = None, ready: Optional[Callable[[], bool]] = None,
               stop_event: Optional[threading.Event] = None, env: Optional[Mapping] = None,
               do_pass: Callable[[], object] = pass_safely) -> Optional[threading.Thread]:
    """Start the ONE daemon thread, or return None (starting nothing) when ``LIVE_SETTLE=off`` or under pytest. Waits
    for ``ready()`` (the first cache warm-up pass), then runs a pass every ``interval_s``."""
    if not enabled(env) or (env is None and os.environ.get("PYTEST_CURRENT_TEST")):
        return None
    interval = interval_s if interval_s is not None else interval_seconds(env)
    event = stop_event if stop_event is not None else threading.Event()
    STATUS["enabled"] = True

    def loop():
        waited = 0.0
        while ready is not None and not ready() and waited < WAIT_FOR_WARMUP_SECONDS:
            if event.wait(5.0):
                return
            waited += 5.0
        while not event.is_set():
            do_pass()
            if event.wait(interval):
                return

    thread = threading.Thread(target=loop, daemon=True, name="live-settle")
    thread.start()
    logger.info("live settle loop started, interval=%ss", interval)
    return thread


# ---------------------------------------------------------------------------
# what the pages and the watchdog read
# ---------------------------------------------------------------------------

def _public(row, now: datetime) -> dict:
    state = row["state"]
    seen = ls.parse_utc(row["updated_utc"])
    if state == ls.LIVE and seen is not None and now - seen > timedelta(minutes=STALE_LIVE_MINUTES):
        state = "unknown"                                  # the feed went quiet: say nothing rather than a stale score
    return {"state": state, "start_utc": row["start_utc"], "home_score": row["home_score"],
            "away_score": row["away_score"], "detail": row["detail"], "final_utc": row["final_utc"],
            "updated_utc": row["updated_utc"], "supported": bool(row["supported"])}


def game_states(keys: Sequence[str], *, now: Optional[datetime] = None, conn: Optional[sqlite3.Connection] = None) -> dict:
    """{event id: public state} for the asked games the cache holds. Unknown ids are absent."""
    moment = now or ls.utcnow()
    own = conn is None
    try:
        conn = conn or connect()
    except (sqlite3.Error, OSError):
        return {}
    try:
        out: dict = {}
        for key in list(dict.fromkeys(str(k) for k in keys))[:80]:
            row = _row(conn, key)
            if row is not None:
                out[key] = _public(row, moment)
        return out
    finally:
        if own:
            conn.close()


def status(*, now: Optional[datetime] = None, conn: Optional[sqlite3.Connection] = None,
           env: Optional[Mapping] = None, paths: Optional[Mapping] = None) -> dict:
    """The small public status: is the loop on, when it last ran, when a ticket last graded, how many games are
    waiting on a final (the "Grading" indicator), and ``unsupported``: open tickets whose sport or league the loop has
    no free feed for (tennis and MMA have their own readers and count as supported). Those tickets are on the
    old path, which is slow; the count is shown rather than hidden so a stall is visible. None when the ledgers
    cannot be read, never a guess."""
    moment = now or ls.utcnow()
    out = {"enabled": enabled(env), "last_pass_utc": None, "last_graded_utc": None, "awaiting_final": 0,
           "final_ungraded": 0, "unsupported": None}
    try:
        out["unsupported"] = sum(g.tickets for g in open_games(moment, paths if paths is not None else ledger_paths())
                                 if not g.supported())
    except Exception:  # noqa: BLE001 -- an unreadable ledger is unknown, not zero
        out["unsupported"] = None
    own = conn is None
    try:
        conn = conn or connect()
    except (sqlite3.Error, OSError):
        return out
    try:
        out["last_pass_utc"] = _meta_get(conn, "last_pass_utc")
        out["last_graded_utc"] = _meta_get(conn, "last_graded_utc")
        now_iso = ls.iso(moment)
        out["awaiting_final"] = conn.execute(
            "SELECT COUNT(*) FROM live_games WHERE applied_utc IS NULL AND state IN ('live','upcoming') AND supported=1"
            " AND start_utc IS NOT NULL AND start_utc <= ? AND start_utc >= ?",
            (now_iso, ls.iso(moment - WATCH_UNTIL))).fetchone()[0]
        out["final_ungraded"] = conn.execute(
            "SELECT COUNT(*) FROM live_games WHERE state='final' AND applied_utc IS NULL").fetchone()[0]
        return out
    finally:
        if own:
            conn.close()


def overdue_tickets(now: Optional[datetime] = None, *, paths: Optional[Mapping] = None,
                    conn: Optional[sqlite3.Connection] = None, hours: float = OVERDUE_HOURS) -> list:
    """Open member tickets whose game's scheduled start was more than ``hours`` ago, for the watchdog.

    Counted whether or not the loop has a free feed for the sport: a family it cannot read (EuroLeague, cricket, other
    hockey, European soccer off the mapped leagues) is still an open ticket on a game that has long ended, and the watchdog
    must say so. Left out: a game the feed says is postponed or cancelled (those wait for a makeup by rule), a game still
    genuinely in play on a feed that can see it, and house-pack tickets (graded by the capture slot). Tennis and MMA are
    counted with their own extra grace hours, as before."""
    moment = now or ls.utcnow()
    own = conn is None
    try:
        conn = conn or connect()
    except (sqlite3.Error, OSError):
        return []
    try:
        out = []
        for g in open_games(moment, paths if paths is not None else ledger_paths()):
            grace = hours + (FREE_OVERDUE_EXTRA_HOURS if g.free_family() else 0.0)
            if g.start is None or not g.settles_here() or moment - g.start <= timedelta(hours=grace):
                continue
            row = _row(conn, g.key)
            state = row["state"] if row is not None else ls.UPCOMING
            if state in (ls.POSTPONED, ls.CANCELLED):
                continue
            seen = ls.parse_utc(row["updated_utc"]) if row is not None else None
            if state == ls.LIVE and seen is not None and moment - seen <= timedelta(minutes=STALE_LIVE_MINUTES):
                continue
            out.append({"key": g.key, "game": f"{g.away_team} @ {g.home_team}", "sport": g.sport,
                        "start_utc": ls.iso(g.start), "hours_overdue": round((moment - g.start).total_seconds() / 3600, 1),
                        "tickets": g.tickets, "state": state, "sources": sorted(g.sources)})
        out.sort(key=lambda r: r["start_utc"])
        return out
    finally:
        if own:
            conn.close()
