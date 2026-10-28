"""Live score, status, period and clock for the Live board, from the FREE ESPN scoreboard, refreshed in-process.

WHY THIS EXISTS (owner complaint, 2026-10-27, 5:22 PM PT)
---------------------------------------------------------
The Live board showed Columbus 3, Philadelphia 0 "LIVE" while ESPN had it 3-1 in the 2nd, and the page said "Board as of
5:22 PM PT, refreshes every minute". The chain behind that line:
  * the score came from The Odds API /scores store (src/pipeline/allsports_scores.py), polled by a CI job every 2 hours
    at most per key, committed to git and only reaching production with the next image redeploy;
  * "refreshes every minute" was the browser re-asking an API that answered from that stored file;
  * "Board as of" was the server's clock (`generated_utc`), not the age of any data;
  * the card carried no period, no clock and no per-game age.
So a visitor read a stale number under a fresh-looking timestamp. This module is the fix: one daemon thread in the API
process reads ESPN's public scoreboard JSON (free; no Odds API credit is spent) for ONLY the leagues that have a game in
play or about to start, every `INTERVAL_SECONDS`, and `src.sports.allsports_view` lays the answer over each event.

STALENESS GUARD
---------------
An answer older than `STALE_AFTER_SECONDS` is never shown as a score. A covered game with no fresh answer says "Score
delayed" and carries no numbers, and the payload says when the feed last answered. A wrong score is worse than none.

COVERAGE
--------
MLB, NFL, NBA, WNBA, NHL, NCAAF, NCAAB and the soccer leagues ESPN keys in `src/hounds/live_scores.py`. Families ESPN does
not cover here (tennis, cricket, rugby, MMA) keep the old stored-score path. Matching a game is the grader's own
`live_scores.espn_answers` (same team-name folding, 12 hour start window, no match = no answer), so the board and the
settle loop can never disagree about which game is which.

Read only; nothing here places or implies a bet. Disable with LIVE_FEED=off. Never starts under pytest.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Mapping, Optional

from src.hounds import live_scores as ls

logger = logging.getLogger("linehound.sports.live_feed")

ENV_FLAG = "LIVE_FEED"
INTERVAL_SECONDS = 45.0                  # inside the owner's "at least every 60 s while a game is live", with room for a slow pass
STALE_AFTER_SECONDS = 180.0              # three missed passes: past this a score is not shown
LEAD_MINUTES = 20                        # a league is read this long before its first game starts, so the flip to live is seen
WAIT_FOR_WARMUP_SECONDS = 600.0
FETCH_TIMEOUT_SECONDS = 15.0
MAX_REQUESTS_PER_PASS = 40
USER_AGENT = "Mozilla/5.0 (compatible; linehound-live/1.0)"
MLB_CODE = "mlb"
_MLB_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard?dates={d}&limit=100"

_lock = threading.Lock()
_FEED: dict = {}                         # league -> {"fetched": datetime, "payloads": [dict, ...]}
STATUS: dict = {"enabled": False, "passes": 0, "last_pass_utc": None, "last_error": None, "last_leagues": []}


def enabled(env: Optional[Mapping] = None) -> bool:
    source = env if env is not None else os.environ
    return str(source.get(ENV_FLAG) or "on").strip().lower() not in ("off", "0", "false", "no")


def league_for(family: str, league_key: Optional[str] = None) -> Optional[str]:
    """The ESPN league code this event's scoreboard is read from, or None when the feed does not cover it."""
    if str(family or "").upper() == "MLB":
        return MLB_CODE
    return ls.espn_league_for(family, league_key)


def _url(league: str, day) -> str:
    if league == MLB_CODE:
        return _MLB_URL.format(d=day.strftime("%Y%m%d"))
    return ls.scoreboard_url(league, day)


def default_fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:  # noqa: S310 -- fixed https ESPN host
        return json.loads(response.read().decode("utf-8"))


def scoreboard_days(now: datetime) -> list:
    """The scoreboard days to read: ESPN lists a game under its US-evening date, which for a late game is the UTC day
    before, so both the UTC day and the one before it are read."""
    today = now.astimezone(timezone.utc).date()
    return [today, today - timedelta(days=1)]


# ---------------------------------------------------------------------------
# the cache
# ---------------------------------------------------------------------------

def clear() -> None:
    with _lock:
        _FEED.clear()


def store(league: str, payloads: list, fetched: datetime) -> None:
    with _lock:
        _FEED[league] = {"fetched": fetched, "payloads": payloads}


def fresh_entry(league: str, now: datetime) -> Optional[dict]:
    with _lock:
        entry = _FEED.get(league)
    if not entry:
        return None
    if (now - entry["fetched"]).total_seconds() > STALE_AFTER_SECONDS or entry["fetched"] > now + timedelta(seconds=5):
        return None
    return entry


def last_fetched(now: datetime) -> Optional[datetime]:
    """The newest successful read still inside the staleness guard, or None."""
    with _lock:
        stamps = [e["fetched"] for e in _FEED.values()]
    live = [s for s in stamps if 0 <= (now - s).total_seconds() <= STALE_AFTER_SECONDS]
    return max(live) if live else None


# ---------------------------------------------------------------------------
# refresh
# ---------------------------------------------------------------------------

def leagues_needed(events: Iterable[Mapping], now: datetime) -> list:
    """Leagues with a game live now (or flagged live by the board) or starting within `LEAD_MINUTES`.
    `events` are the board's internal event dicts: family, league, _start, in_play."""
    horizon = now + timedelta(minutes=LEAD_MINUTES)
    out = []
    for ev in events:
        league = league_for(ev.get("family"), ev.get("league"))
        if league is None or league in out:
            continue
        start = ev.get("_start")
        if ev.get("in_play") or (start is not None and now - timedelta(hours=1) <= start <= horizon):
            out.append(league)
    return sorted(out)


def refresh(leagues: Iterable[str], now: datetime, *, fetch_json: Callable[[str], dict] = default_fetch_json,
            max_requests: int = MAX_REQUESTS_PER_PASS) -> dict:
    """Read each league's scoreboard days and replace its cache entry. A league whose every request failed keeps its
    OLD entry (which then ages past the staleness guard on its own); it is never overwritten with nothing."""
    report = {"requests": 0, "ok": [], "failed": []}
    for league in leagues:
        payloads = []
        for day in scoreboard_days(now):
            if report["requests"] >= max_requests:
                break
            report["requests"] += 1
            try:
                payload = fetch_json(_url(league, day))
            except Exception as exc:  # noqa: BLE001 -- one bad day must not stop the other leagues
                logger.warning("live feed %s %s: %s", league, day, str(exc)[:120])
                STATUS["last_error"] = f"{league}: {type(exc).__name__}"
                continue
            if isinstance(payload, Mapping):
                payloads.append(payload)
        if payloads:
            store(league, payloads, now)
            report["ok"].append(league)
        else:
            report["failed"].append(league)
    STATUS["passes"] += 1
    STATUS["last_pass_utc"] = ls.iso(now)
    STATUS["last_leagues"] = list(leagues) if not isinstance(leagues, list) else leagues
    return report


# ---------------------------------------------------------------------------
# the overlay
# ---------------------------------------------------------------------------

def _score_from(answer: Mapping, fetched: datetime) -> dict:
    progress = answer.get("progress") or {}
    done = answer["state"] == ls.FINAL
    detail = answer.get("detail") or progress.get("label")
    if done and not detail:
        detail = "Final"
    return {"home": answer.get("home_score"), "away": answer.get("away_score"), "detail": detail,
            "period": progress.get("period"), "clock": progress.get("clock"), "completed": done,
            "as_of": ls.iso(fetched), "source": "espn"}


def answers_for(events: Iterable[Mapping], now: datetime) -> dict:
    """{event_id: answer} for the events the feed COVERS. An answer is one of
         {"covered": True, "state": live|final|upcoming|postponed|cancelled, "score": {...}}   a fresh, matched game
         {"covered": True, "state": None, "delayed": True}                                      league read too old / never read
         {"covered": True, "state": None, "unmatched": True}                                    fresh read, no unambiguous game
    An event the feed does not cover is simply absent, so its old path is untouched."""
    by_league: dict = {}
    for ev in events:
        league = league_for(ev.get("family"), ev.get("league"))
        if league is not None and ev.get("event_id"):
            by_league.setdefault(league, []).append(ev)
    out: dict = {}
    for league, evs in by_league.items():
        entry = fresh_entry(league, now)
        if entry is None:
            for ev in evs:
                out[ev["event_id"]] = {"covered": True, "state": None, "delayed": True}
            continue
        wanted = [{"key": ev["event_id"], "home_team": ev.get("home"), "away_team": ev.get("away"), "start": ev.get("_start")}
                  for ev in evs]
        found: dict = {}
        for payload in entry["payloads"]:
            found.update(ls.espn_answers(payload, league, wanted, ls.iso(entry["fetched"])))
        for ev in evs:
            ans = found.get(ev["event_id"])
            if ans is None:
                out[ev["event_id"]] = {"covered": True, "state": None, "unmatched": True}
            else:
                out[ev["event_id"]] = {"covered": True, "state": ans["state"], "score": _score_from(ans, entry["fetched"])}
    return out


# ---------------------------------------------------------------------------
# the loop
# ---------------------------------------------------------------------------

def run_pass(events_provider: Callable[[], Iterable[Mapping]], *, now: Optional[datetime] = None,
             fetch_json: Callable[[str], dict] = default_fetch_json) -> dict:
    moment = now or datetime.now(timezone.utc)
    return refresh(leagues_needed(events_provider(), moment), moment, fetch_json=fetch_json)


def start_loop(events_provider: Callable[[], Iterable[Mapping]], *, interval_s: float = INTERVAL_SECONDS,
               ready: Optional[Callable[[], bool]] = None, stop_event: Optional[threading.Event] = None,
               env: Optional[Mapping] = None) -> Optional[threading.Thread]:
    """ONE daemon thread, or None when LIVE_FEED=off or under pytest. A pass never raises out of the loop."""
    if not enabled(env) or (env is None and os.environ.get("PYTEST_CURRENT_TEST")):
        return None
    event = stop_event if stop_event is not None else threading.Event()
    STATUS["enabled"] = True

    def loop():
        waited = 0.0
        while ready is not None and not ready() and waited < WAIT_FOR_WARMUP_SECONDS:
            if event.wait(5.0):
                return
            waited += 5.0
        while not event.is_set():
            try:
                run_pass(events_provider)
            except Exception as exc:  # noqa: BLE001 -- the loop must outlive any one bad pass
                STATUS["last_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
                logger.exception("live feed pass failed")
            if event.wait(interval_s):
                return

    thread = threading.Thread(target=loop, daemon=True, name="live-feed")
    thread.start()
    return thread
