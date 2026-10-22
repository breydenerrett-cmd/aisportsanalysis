"""When a ticket is about to start and what is happening in its game: the "starting soon" and "live update" alerts.

WHY THIS EXISTS (owner, 2026-10-22): members want to see their hounds' bets "live or upcoming". ``alerts.py`` already
raises "bet placed" and "bet settled" from the ledger writers; this module raises the two kinds in between.

IT COSTS NO REQUEST. The grading loop (``src/hounds/live_settle.py``) already asks the free feeds about every game behind
an open ticket every five minutes and keeps each answer in its ``live_games`` cache table. ``scan`` runs at the end of the
fetch step of that same pass and only READS the cache (plus the open tickets the pass already parsed). It writes rows into
the alert outbox, which is a local sqlite insert; the dispatcher thread sends them. It never fetches, never waits on a
channel, and ``live_settle.alerts_scan`` swallows anything it raises, so an alert can never slow or break a grade.

THE FOUR MOMENTS (all opt-in under the "Live updates" toggle, which is OFF by default; "starting soon" is its own toggle):
  * ``start``  the game went live (only if the pass sees it within ``WENT_LIVE_GRACE`` of the tip: a game first seen an hour
               in, after a restart or for a ticket placed in play, is not "going live");
  * ``half``   halftime, or the period-end that stands in for it (NHL: the end of the 2nd; baseball: the middle of the game,
               from the 5th inning on, named with the inning it is actually seen in);
  * ``flip``   a LATE lead change that turns the ticket from winning to losing or back (``late``: the last period of
               regulation or later; baseball from the 7th; soccer from the 70th minute; college basketball the last 10
               minutes). A push or a tie is not a position: winning, tied, winning is NOT a flip, winning, tied, losing is;
  * ``final``  the game is final, just before the grading step of the same pass.
Each ticket gets at most ``alerts.LIVE_CAP_PER_TICKET`` (3) live updates per game. The earlier moments may spend only the
first two, so ``final`` always has a slot.

POSITION. ``ticket_status`` reads a moneyline, spread or total off the live score the way the settlers do (a spread or total
exactly on the number is a push; a draw in a three-way sport is a loss for a team moneyline). A prop or anything it cannot
read has NO position: it still gets went-live / halftime / final lines, never a flip.

PAPER ONLY. Nothing here recommends a bet or says a position will win; "winning" and "losing" describe the score right now.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Mapping, Optional, Sequence

from src.hounds import live_scores as ls
from src.notify import alerts

logger = logging.getLogger("linehound.notify.alert_live")

#: "About 15 minutes before": the first pass that finds the tip inside this window raises the alert. The grading loop
#: passes every five minutes, so the real lead is 10 to 15 minutes, and the message says the minutes it measured.
STARTING_WINDOW = timedelta(minutes=15)
WENT_LIVE_GRACE = timedelta(minutes=20)
#: a "final" more than this long after the feed first said final is not "just before grading": the settled alert covers it
FINAL_FRESH = timedelta(minutes=45)
#: a live answer older than this is the feed gone quiet, not the score now (live_settle.STALE_LIVE_MINUTES is 90; an
#: alert wants a much fresher score than a page does)
LIVE_FRESH = timedelta(minutes=20)
#: The scan shares the grading pass's thread, so it is bounded: it stops after this many seconds (the next pass, five minutes on,
#: picks up what is left: every emit is idempotent), and its database waits are short (a locked alert store costs a pass
#: this many milliseconds per wait, never the store's five seconds).
SCAN_BUDGET_S = 3.0
SCAN_BUSY_MS = 250
#: the scoreboard's scheduled start replaces the ticket's (odds-feed) start only when it is this close: a wildly different
#: time is a wrong match, not a reschedule
SCHED_TRUST = timedelta(hours=12)

WINNING, LOSING, PUSH = "winning", "losing", "push"

M_START, M_HALF, M_FLIP, M_FINAL = "start", "half", "flip", "final"

#: last regulation period by family: a lead change in it (or in overtime) is "late"
_LAST_PERIOD = {"NBA": 4, "WNBA": 4, "NFL": 4, "NCAAF": 4, "NHL": 3}
MLB_LATE_INNING = 7
MLB_MID_INNING = 5
SOCCER_LATE_MINUTE = 70
NCAAB_LATE_MINUTES_LEFT = 10


def _num(value) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _three_way(sport: str) -> bool:
    try:
        from src.sports import catalog
        return bool(catalog.draw_possible(sport))
    except Exception:  # noqa: BLE001 -- a catalog that cannot be read: treat a draw as a push, the safe wording
        return False


def ticket_status(ticket: Mapping, home, away) -> Optional[str]:
    """winning / losing / push for a moneyline, spread or total at this score; None when it cannot be read (a prop, a
    missing side or line, no score). The arithmetic is the settlers' own (allsports_scores.grade_bet)."""
    h, a = _num(home), _num(away)
    if h is None or a is None:
        return None
    market, side, line = ticket.get("market"), ticket.get("side"), _num(ticket.get("line"))
    if market == "moneyline" and side in ("home", "away"):
        if h == a:
            return LOSING if _three_way(str(ticket.get("sport") or "")) else PUSH
        return WINNING if (h > a) == (side == "home") else LOSING
    if market == "spread" and side in ("home", "away") and line is not None:
        adjusted = ((h - a) if side == "home" else (a - h)) + line
        return PUSH if abs(adjusted) < 1e-9 else WINNING if adjusted > 0 else LOSING
    if market == "total" and side in ("over", "under") and line is not None:
        total = h + a
        if abs(total - line) < 1e-9:
            return PUSH
        return WINNING if (total > line) == (side == "over") else LOSING
    return None


def _minutes(clock: Optional[str]) -> Optional[float]:
    """Minutes shown on a game clock: '7:32' -> 7.5, "78'" -> 78, "45'+2'" -> 45."""
    match = re.match(r"\s*(\d+)(?::(\d+))?", str(clock or ""))
    if not match:
        return None
    return int(match.group(1)) + (int(match.group(2)) / 60.0 if match.group(2) else 0.0)


def late(sport: str, progress: Optional[Mapping], league: Optional[str] = None) -> bool:
    """Is the game in its closing stretch, where a lead change is worth a message? False when it cannot tell."""
    if not progress:
        return False
    period = progress.get("period")
    if not isinstance(period, int):
        return False
    family = str(sport or "").upper()
    if family == "MLB":
        return period >= MLB_LATE_INNING
    if family in _LAST_PERIOD:
        return period >= _LAST_PERIOD[family]
    if family == "NCAAB":
        if "wncaab" in str(league or "").lower():
            return period >= 4
        left = _minutes(progress.get("clock"))
        return period > 2 or (period == 2 and left is not None and left <= NCAAB_LATE_MINUTES_LEFT)
    if family == "SOCCER":
        minute = _minutes(progress.get("clock"))
        return period >= 2 and minute is not None and minute >= SOCCER_LATE_MINUTE
    return False


def at_break(sport: str, progress: Optional[Mapping]) -> bool:
    """Is the game at (or, for baseball, past) its halfway break? Baseball has no halftime: the middle of the 5th is
    two minutes long and a five-minute poll can miss it, so any look at the 6th inning or later also counts, once."""
    if not progress:
        return False
    family = str(sport or "").upper()
    period, name = progress.get("period"), str(progress.get("name") or "")
    if family == "MLB":
        return isinstance(period, int) and (period >= MLB_MID_INNING + 1 or (
            period == MLB_MID_INNING and name in ("MIDDLE", "END")))
    if family == "NHL":
        return name == "STATUS_END_PERIOD" and period == 2
    return name == "STATUS_HALFTIME"


def _ticket_row(t: Mapping) -> dict:
    """The slim open ticket (live_settle._slim_user) as the row shape the alert emitters read."""
    return {"kind": "hound_user_bet", "bet_id": t.get("bet_id"), "hound_id": t.get("hound_id"), "sport": t.get("sport"),
            "market": t.get("market"), "side": t.get("side"), "line": t.get("line"), "selection": t.get("selection"),
            "price": t.get("price"), "units": t.get("units"), "stake_units": t.get("stake_units"),
            "away_team": t.get("away_team"), "home_team": t.get("home_team"), "commence_time": t.get("start"),
            "segment": t.get("segment"), "provenance": t.get("provenance"), "role": t.get("role"),
            "event_id": t.get("event_id"), "league": t.get("league")}


def _progress(row) -> Optional[dict]:
    try:
        value = json.loads(row["progress"]) if row["progress"] else None
    except (ValueError, KeyError, IndexError):
        return None
    return value if isinstance(value, dict) else None


def _snapshot(ticket: Mapping, game, progress: Optional[Mapping]) -> dict:
    return {"home_score": game["home_score"], "away_score": game["away_score"],
            "status": ticket_status(ticket, game["home_score"], game["away_score"]),
            "label": (progress or {}).get("label") or game["detail"]}


def effective_start(ticket_start: Optional[datetime], game) -> Optional[datetime]:
    """When the game really starts: the scoreboard's own scheduled time once the cache holds one (the odds feed's start
    can be wrong by more than an hour: a tennis match on 2026-10-22 was 85 minutes off), else the ticket's. A scoreboard
    time more than ``SCHED_TRUST`` away is not trusted over the ticket (a reschedule to another day, or a bad match)."""
    try:
        sched = ls.parse_utc(game["sched_utc"]) if "sched_utc" in game.keys() else None
    except (KeyError, IndexError, AttributeError):
        sched = None
    if sched is None:
        return ticket_start
    if ticket_start is None or abs(sched - ticket_start) <= SCHED_TRUST:
        return sched
    return ticket_start


class _Book:
    """What one member already has on file, read once per scan: starting-soon bet ids, live event keys, live counts per
    ticket and the last decided side per ticket. Kept current as the scan writes, so a pass over many tickets costs two
    reads per member, not several connections per ticket."""

    def __init__(self, owner: int):
        self.starting = alerts.starting_sent(owner)
        self.counts, self.sides, self.raised = alerts.live_book(owner)


def _emit_live(row: dict, found: tuple, moment: str, snap: dict, now: datetime, book: _Book, report: dict) -> bool:
    bet_id = str(row["bet_id"])
    key = alerts.live_key(bet_id, moment)
    if key in book.raised:
        return False
    wrote = alerts.emit_live(row, moment, snap, now=now, _owner=found)
    book.raised.add(key)                                  # written, or refused by the key / the cap: either way, done
    if wrote:
        book.counts[bet_id] = book.counts.get(bet_id, 0) + 1
        report["live"] += 1
    return wrote


def _live_moments(row: dict, found: tuple, game, now: datetime, start: Optional[datetime], report: dict,
                  book: _Book) -> None:
    """Raise the live moments this ticket has reached in the cached game state (at most the ticket's cap)."""
    bet_id = str(row["bet_id"])
    owner = found[1]
    progress = _progress(game)
    snap = _snapshot(row, game, progress)
    state = game["state"]
    updated = ls.parse_utc(game["updated_utc"])
    if state == ls.FINAL:
        final_at = ls.parse_utc(game["final_utc"]) or updated
        if final_at is None or now - final_at > FINAL_FRESH:
            return
        if game["home_score"] is None or game["away_score"] is None:
            return                                         # a final with no score is not a line worth a message
        if book.counts.get(bet_id, 0) < alerts.LIVE_CAP_PER_TICKET:
            _emit_live(row, found, M_FINAL, snap, now, book, report)
        return
    if state != ls.LIVE or updated is None or now - updated > LIVE_FRESH:
        return
    prior, status = book.sides.get(bet_id), snap["status"]
    flipped = (late(row["sport"], progress, row.get("league")) and status in (WINNING, LOSING)
               and prior in (WINNING, LOSING) and prior != status)
    if status in (WINNING, LOSING) and status != prior:
        alerts.set_live_side(owner, bet_id, status, now=now)      # BEFORE emitting: at most once beats twice for a message
        book.sides[bet_id] = status

    def room() -> bool:
        return book.counts.get(bet_id, 0) < alerts.LIVE_CAP_PER_TICKET - 1     # the last slot belongs to the final

    if room() and start is not None and now - start <= WENT_LIVE_GRACE:
        _emit_live(row, found, M_START, snap, now, book, report)
    if room() and at_break(row["sport"], progress):
        _emit_live(row, found, M_HALF, snap, now, book, report)
    if room() and flipped:
        _emit_live(row, found, f"{M_FLIP}{book.counts.get(bet_id, 0)}", snap, now, book, report)


def _is_busy(exc: BaseException) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and ("locked" in str(exc) or "busy" in str(exc))


def scan(conn, now: datetime, paths: Mapping, *, tickets: Optional[Sequence[Mapping]] = None,
         budget_s: Optional[float] = None, clock=time.monotonic) -> dict:
    """Queue the starting-soon and live-update events the cache implies at ``now``. Returns {"tickets", "starting", "live",
    "errors"} plus "out_of_time" / "busy" when the scan stopped early (the next pass carries on: every emit is idempotent).

    ``conn`` is the live_settle cache connection (already open in the pass). ``tickets`` is for tests; the pass reads the
    open tickets of the member and manual ledgers the way settlement does (parsed once per ledger change).

    BOUNDED: the scan runs on the grading thread, so every app.db connection it opens waits at most ``SCAN_BUSY_MS`` on a
    lock, a locked store ends the scan at the first refusal, one bad ticket is skipped (logged by type, never by content),
    and the whole scan stops after ``SCAN_BUDGET_S``. Finals and tickets about to start are taken first."""
    report = {"tickets": 0, "starting": 0, "live": 0, "errors": 0}
    deadline = clock() + (SCAN_BUDGET_S if budget_s is None else budget_s)
    with alerts.short_waits(SCAN_BUSY_MS), alerts.held_open():
        try:
            _scan(conn, now, paths, tickets, report, deadline, clock)
        except Exception as exc:  # noqa: BLE001 -- reading the ledgers or the cache failed: nothing more to do this pass
            if _is_busy(exc):
                report["busy"] = True
            else:
                report["errors"] += 1
                logger.error("bet alert scan stopped: %s", type(exc).__name__)
    return report


def _scan(conn, now: datetime, paths: Mapping, tickets, report: dict, deadline: float, clock) -> None:
    if tickets is None:
        from src.hounds import live_settle
        tickets = []
        for label in ("user", "manual"):
            if paths.get(label):
                tickets.extend(live_settle.open_tickets_in(paths[label], label))
    games: dict = {}
    members: dict = {}
    work = []
    for t in tickets:
        row = _ticket_row(t)
        if not t.get("event_id") or not row["bet_id"] or not row["hound_id"] or not alerts.eligible_ticket(row):
            continue
        key = str(t["event_id"])
        if key not in games:
            games[key] = conn.execute("SELECT * FROM live_games WHERE game_key=?", (key,)).fetchone()
        game = games[key]
        if game is None:
            continue
        start = effective_start(ls.parse_utc(t.get("start")), game)
        state = game["state"]
        if state == ls.FINAL:
            rank = 0
        elif state == ls.UPCOMING and start is not None and timedelta(0) < start - now <= STARTING_WINDOW:
            rank = 1
        elif state == ls.LIVE:
            rank = 2
        else:
            continue                                       # postponed, cancelled, or not near its start: nothing to say
        work.append((rank, row, game, start))
    work.sort(key=lambda w: w[0])
    books: dict = {}
    for rank, row, game, start in work:
        if clock() > deadline:
            report["out_of_time"] = True
            return
        try:
            hound_id = str(row["hound_id"])
            if hound_id not in members:
                members[hound_id] = alerts.member_of(hound_id)
            member = members[hound_id]
            if member is None:
                continue
            hound, owner, toggles = member
            want_starting, want_live = bool(toggles.get(alerts.KIND_STARTING)), bool(toggles.get(alerts.KIND_LIVE))
            if not (want_starting or want_live):
                continue
            report["tickets"] += 1
            if owner not in books:
                books[owner] = _Book(owner)
            book = books[owner]
            found = (hound, owner)
            if rank == 1:
                bet_id = str(row["bet_id"])
                if want_starting and bet_id not in book.starting:
                    minutes = max(1, round((start - now).total_seconds() / 60.0))
                    if alerts.emit_starting(dict(row, commence_time=ls.iso(start)), minutes_out=minutes, now=now,
                                            _owner=found):
                        report["starting"] += 1
                    book.starting.add(bet_id)
            elif want_live:
                _live_moments(row, found, game, now, start, report, book)
        except Exception as exc:  # noqa: BLE001 -- one ticket must not cost the others their alerts (or the pass its grade)
            if _is_busy(exc):
                report["busy"] = True
                return
            report["errors"] += 1
            logger.error("bet alert scan: a ticket was skipped: %s", type(exc).__name__)
