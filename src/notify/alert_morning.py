"""The morning lineup: "what your hounds are watching today" (owner, 2026-10-28: "text me in the morning, and again the
moment a hound decides a bet").

HOW IT FITS THE ALERT SYSTEM. This module only DECIDES that a member's lineup is due and writes ONE outbox event
(``alerts.emit_morning``, kind ``morning``). Everything after that is the machinery bet alerts already use: the dispatcher
(alert_dispatch.py) sends the event on each channel the member switched on (push, email, and text for a paid member once
Twilio is live), honours quiet hours and the hourly cap, retries, and never sends the same (event, channel) twice. The
per-member private RSS feed (api/alerts_routes.py) lists the same event, which is the bridge to a phone before Twilio exists.
``alert_dispatch.drain`` calls ``run`` first on every tick, so the lineup rides the loop the alerts already have: no new
thread and no workflow file.

ONCE PER LOCAL DAY. The event key is the member's LOCAL date in their saved zone (Pacific when the zone is missing), and
the outbox row is UNIQUE on (member, kind, key). A tick before 9:00 local makes nothing; from 9:00 until noon a due member
gets the event the first tick that has something to say; after noon that day is let go (a server that was down all
morning does not text "this morning" at 4 PM).

WHAT IT SAYS. For each of the member's RUNNING hounds: the games on today's slate in the sports that hound covers
(``allsports_view.cached_sports_now``, the data behind the Tonight page's "games your hounds are checking"), the markets it
bets, and the earliest moment it can decide (the first game's start minus the hound's lock minutes). A hound with no game on
the slate is left out; a member whose hounds have nothing gets no message at all (a note that says "nothing" is noise).
"Today" is the same window the Tonight page uses: from now until 5 AM local the next morning, so a late West Coast game
counts. Tickets the hound already decided today (``placed`` events since local midnight) are counted, never listed.
This is a report of what a hound is looking at. It never says a game is worth betting.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Mapping, Optional

from src.notify import alerts

logger = logging.getLogger("linehound.notify.alert_morning")

#: "today" ends at 5 AM local the next morning (web/js/tonight-model.js tonightEnd), so a late West Coast game is still tonight
SLATE_END_HOUR = 5
MARKET_WORDS = {"moneyline": "moneyline", "spread": "spread", "total": "total", "h2h": "moneyline"}
ZONE_NAMES = {"EDT": "ET", "EST": "ET", "CDT": "CT", "CST": "CT", "MDT": "MT", "MST": "MT", "PDT": "PT", "PST": "PT"}


def member_zone(prefs: Mapping):
    return (alerts.zone(prefs.get("tz") or "") or alerts.zone(alerts.MORNING_FALLBACK_TZ) or timezone.utc)


def clock_text(moment: datetime, zone) -> str:
    """'4:10 PM PT'."""
    local = moment.astimezone(zone)
    hour = local.strftime("%I").lstrip("0") or "12"
    name = local.tzname() or ""
    return f"{hour}:{local.strftime('%M %p')} {ZONE_NAMES.get(name, name)}".strip()


def _games_by_family(families: list, start: datetime, end: datetime) -> dict:
    """{family code: [start datetimes]} for games not yet started and starting before ``end``."""
    out: dict = {}
    for family in families or []:
        code = str(family.get("code") or "").upper()
        for event in family.get("upcoming_24h") or []:
            moment = alerts.parse_iso(event.get("start_utc"))
            if code and moment is not None and start < moment <= end:
                out.setdefault(code, []).append(moment)
    return out


def _markets_text(spec: Mapping) -> str:
    words = []
    for market in spec.get("markets") or []:
        word = MARKET_WORDS.get(str(market), str(market).replace("_", " "))
        if word not in words:
            words.append(word)
    return "/".join(words)


def hound_line(hound: Mapping, games: Mapping, now: datetime, zone, decided: int = 0) -> Optional[str]:
    """One hound's sentence, or None when none of its sports has a game left on the slate."""
    spec = hound.get("spec") or {}
    sports = [str(s).upper() for s in spec.get("sports") or []]
    mine = [(code, games[code]) for code in sports if games.get(code)]
    if not mine:
        return None
    parts = [f"{len(starts)} {code} game{'s' if len(starts) != 1 else ''}" for code, starts in mine]
    markets = _markets_text(spec)
    line = f"{hound['name']}: watching {', '.join(parts)}" + (f" ({markets})" if markets else "") + "."
    first = min(m for _, starts in mine for m in starts)
    decide = first - timedelta(minutes=int(spec.get("lock_minutes") or 0))
    if decide > now:
        line += f" Decides by {clock_text(decide, zone)}."
    if decided:
        line += f" {decided} already decided today."
    return line


def _decided_today(user_id: int, day_start_utc: datetime) -> dict:
    """{hound id: tickets it placed since the member's local midnight}."""
    with alerts.connect() as conn:
        rows = conn.execute("SELECT hound_id, COUNT(*) FROM alert_events WHERE user_id = ? AND kind = ? "
                            "AND created_utc >= ? GROUP BY hound_id",
                            (user_id, alerts.KIND_PLACED, alerts.iso(day_start_utc))).fetchall()
    return {r[0]: r[1] for r in rows}


def lines_for(user_id: int, prefs: Mapping, hounds: List[Mapping], families: list, now: datetime) -> List[tuple]:
    """[(hound, sentence)] for the member's hounds that have a game today, oldest hound first, ties by name (so the text never reorders between runs)."""
    zone = member_zone(prefs)
    local = now.astimezone(zone)
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end = (local + timedelta(days=1)).replace(hour=SLATE_END_HOUR, minute=0, second=0, microsecond=0)
    games = _games_by_family(families, now, end.astimezone(timezone.utc))
    decided = _decided_today(user_id, day_start.astimezone(timezone.utc))
    out = []
    for hound in sorted(hounds, key=lambda h: (str(h.get("created_at") or ""), str(h.get("name") or ""))):
        if hound.get("status") != "running":
            continue
        if (hound.get("spec") or {}).get("style") == "apprentice" and not (hound["spec"].get("rules")):
            continue
        line = hound_line(hound, games, now, zone, decided.get(hound["id"], 0))
        if line:
            out.append((hound, line))
    return out


def _due_members(now: datetime) -> list:
    """(prefs) for every member with the lineup on, who has a channel or a feed to read it from, whose local clock is in the
    morning window and who has no lineup for today yet."""
    with alerts.connect() as conn:
        user_ids = [r[0] for r in conn.execute(
            "SELECT user_id FROM alert_prefs WHERE morning_lineup IS NULL OR morning_lineup != 0").fetchall()]
    due = []
    for uid in user_ids:
        prefs = alerts.get_prefs(uid)
        if prefs is None or not prefs["morning_lineup"]:
            continue
        if not (any(prefs["channels"].values()) or prefs["feed_set"]):
            continue
        local = now.astimezone(member_zone(prefs))
        if not alerts.MORNING_HOUR <= local.hour < alerts.MORNING_LATEST_HOUR:
            continue
        if alerts.morning_sent(uid, local.date().isoformat()):
            continue
        due.append(prefs)
    return due


def run(now: Optional[datetime] = None, *, slate: Optional[Callable[[], Mapping]] = None,
        hounds_of: Optional[Callable[[int], list]] = None) -> int:
    """Queue the lineup for every member who is due. Returns how many events were written. ``slate`` (the /sports/now payload)
    and ``hounds_of`` are the injection points; production reads the stored odds rows and the hounds table, and only when
    somebody is due (a tick at 3 PM touches neither)."""
    now = (now or alerts.utcnow()).astimezone(timezone.utc)
    due = _due_members(now)
    if not due:
        return 0
    if slate is None:
        from src.sports import allsports_view
        slate = allsports_view.cached_sports_now
    if hounds_of is None:
        from src.hounds import user_store
        hounds_of = user_store.list_for_owner
    families = (slate() or {}).get("families") or []
    queued = 0
    for prefs in due:
        uid = prefs["user_id"]
        try:
            found = lines_for(uid, prefs, hounds_of(uid), families, now)
            if not found:
                continue
            day = now.astimezone(member_zone(prefs)).date().isoformat()
            first = found[0][0]
            name = first["name"] if len(found) == 1 else "Your hounds"
            if alerts.emit_morning(uid, day, [line for _, line in found], hound_id=first["id"], hound_name=name, now=now):
                queued += 1
        except Exception as exc:  # noqa: BLE001 -- one member's data must not stop the others
            logger.error("morning lineup for a member failed: %s", type(exc).__name__)
    return queued
