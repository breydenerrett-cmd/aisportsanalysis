"""The dispatcher: drains the alert outbox into the member's channels. One pass is ``drain``; the app calls it every
``TICK_S`` seconds from ONE daemon thread (``start_loop``), the same single-writer pattern as the email and engine loops.

WHAT ONE PASS DOES, per member and per channel the member switched on (and that the server has available):
  1. quiet hours: inside the member's quiet window nothing is sent; the events wait (and batch together afterwards);
  2. pick the events the member wants (placed / settled / both) that this channel has not finished;
  3. BATCH: events within ``BATCH_WINDOW_S`` (60s) of the first one are ONE message. A group is sent once it has been
     quiet for ``SETTLE_S`` (so a burst from one engine pass collapses into a single message), or once its window is
     a full minute old, so the first alert is never held longer than that;
  4. RATE CAP: at most the channel's ``RATE_CAP_PER_HOUR`` messages per member per hour. Events over the cap are not
     dropped: they stay queued and go out together as one message when the hour has room;
  5. CLAIM then send: each event's delivery row is set to ``sending`` in the database before the channel is called, so
     a second worker or a crash-and-restart can never send the same event on the same channel twice (at most once
     beats at least once for a message nobody can recall);
  6. RETRY with backoff on a transient failure (30s, 2m, 8m, then dead after ``MAX_ATTEMPTS``); a refusal is final.

Events older than ``EXPIRE_S`` are never sent (a "just bet" about last night is noise). Rows are pruned after
``KEEP_DAYS``. Nothing here logs an address, a number, an endpoint or a message body.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable, Mapping, Optional

from src.appstate import users as users_store
from src.notify import alert_channels as ch
from src.notify import alerts
from src.notify import email as mail
from src.notify import email_prefs

logger = logging.getLogger("linehound.notify.alert_dispatch")

TICK_S = 10.0
BATCH_WINDOW_S = 60
SETTLE_S = 10
EXPIRE_S = 12 * 3600
KEEP_DAYS = 14
MAX_ATTEMPTS = 3                       # equals email.MAX_ATTEMPTS: the email send log gives up at the same count
BACKOFF_S = (30, 120, 480)
RATE_CAP_PER_HOUR = {"email": 12, "push": 30, "sms": 6, "native": 30}
ENV_LOOP = "ALERTS_JOBS"
WAIT_FOR_WARMUP_SECONDS = 300.0

STATUS: dict = {"enabled": False, "last_tick_utc": None, "last_counts": {}}


def default_paid_check(user) -> bool:
    """True for a PAID member (comp, subscriber, open tester window, invited beta): NOT a free account. Asks the one
    function the dog tools ask (api/auth.py is_free_member, owner decision 2026-10-21). Where the API layer cannot be
    imported (the no-FastAPI harness) nobody is paid, so SMS stays off."""
    try:
        from api import auth as auth_mod
        return not auth_mod.is_free_member(user)
    except Exception:  # noqa: BLE001
        return False


def in_quiet_hours(prefs: Mapping, now: datetime) -> bool:
    start, end = prefs.get("quiet_start"), prefs.get("quiet_end")
    if start is None or end is None or start == end:
        return False
    try:
        from zoneinfo import ZoneInfo
        hour = now.astimezone(ZoneInfo(prefs.get("tz") or alerts.DEFAULT_TZ)).hour
    except Exception:  # noqa: BLE001
        hour = now.astimezone(timezone.utc).hour
    return (start <= hour < end) if start < end else (hour >= start or hour < end)


def backoff_s(attempts: int) -> int:
    return BACKOFF_S[min(max(attempts, 1), len(BACKOFF_S)) - 1]


def batch_key(user_id: int, channel: str, event_ids) -> str:
    return hashlib.sha256(f"{user_id}|{channel}|{','.join(str(i) for i in sorted(event_ids))}".encode()).hexdigest()[:24]


def _candidates(conn, user_id: int, channel: str, kinds, now: datetime) -> list:
    cutoff = alerts.iso(now - timedelta(seconds=EXPIRE_S))
    rows = conn.execute(
        "SELECT e.id, e.kind, e.created_utc, e.payload_json, d.attempts FROM alert_events e "
        "LEFT JOIN alert_deliveries d ON d.event_id = e.id AND d.channel = ? "
        "WHERE e.user_id = ? AND e.created_utc >= ? AND (d.status IS NULL OR (d.status = 'retry' AND d.next_try_utc <= ?)) "
        "ORDER BY e.id", (channel, user_id, cutoff, alerts.iso(now))).fetchall()
    import json
    out = []
    for r in rows:
        if r["kind"] not in kinds:
            continue
        try:
            payload = json.loads(r["payload_json"])
        except ValueError:
            continue
        out.append({"id": r["id"], "kind": r["kind"], "created_utc": r["created_utc"], "payload": payload,
                    "attempts": r["attempts"] or 0})
    return out


def _groups(events: list):
    """Split into windows: each starts at its first event and takes everything within BATCH_WINDOW_S of it."""
    group: list = []
    for e in events:
        stamp = alerts.parse_iso(e["created_utc"])
        if group and (stamp - alerts.parse_iso(group[0]["created_utc"])).total_seconds() > BATCH_WINDOW_S:
            yield group
            group = []
        group.append(e)
    if group:
        yield group


def _ready(group: list, now: datetime) -> bool:
    first = alerts.parse_iso(group[0]["created_utc"])
    last = alerts.parse_iso(group[-1]["created_utc"])
    return (now - last).total_seconds() >= SETTLE_S or (now - first).total_seconds() >= BATCH_WINDOW_S


def _sent_last_hour(conn, user_id: int, channel: str, now: datetime) -> int:
    since = alerts.iso(now - timedelta(hours=1))
    return conn.execute("SELECT COUNT(*) FROM alert_sends WHERE user_id = ? AND channel = ? AND sent_utc > ?",
                        (user_id, channel, since)).fetchone()[0]


def _claim(conn, channel: str, group: list, now: datetime) -> list:
    """Mark each event 'sending' for this channel; returns the events this call actually won."""
    won = []
    for e in group:
        cur = conn.execute(
            "INSERT INTO alert_deliveries (event_id, channel, status, attempts, updated_utc) VALUES (?, ?, 'sending', 1, ?) "
            "ON CONFLICT(event_id, channel) DO UPDATE SET status = 'sending', attempts = attempts + 1, "
            "updated_utc = excluded.updated_utc WHERE alert_deliveries.status = 'retry'",
            (e["id"], channel, alerts.iso(now)))
        if cur.rowcount:
            won.append(e)
    return won


def _finish(conn, channel: str, events: list, result: ch.Result, now: datetime) -> str:
    attempts = max(e["attempts"] for e in events) + 1
    status, next_try = result.status, None
    if status == ch.S_RETRY:
        if attempts >= MAX_ATTEMPTS:
            status = ch.S_DEAD
        else:
            next_try = alerts.iso(now + timedelta(seconds=backoff_s(attempts)))
    for e in events:
        conn.execute("UPDATE alert_deliveries SET status = ?, next_try_utc = ?, detail = ?, updated_utc = ? "
                     "WHERE event_id = ? AND channel = ?",
                     (status, next_try, result.detail[:120], alerts.iso(now), e["id"], channel))
    return status


def _context(user, prefs, events, channel: str, key: str, *, http, env, now, paid_check, sleep) -> ch.Ctx:
    from src.hounds import unit_size
    base = email_prefs.base_url(env)
    return ch.Ctx(user=user, prefs=prefs, events=events, sizing=unit_size.get(user.id), batch_key=key, http=http,
                  env=env, now=now, paid=bool(paid_check(user)) if channel == "sms" else False,
                  off_url=off_url(user.id, env), settings_url=f"{base}/web/#/signin", sleep=sleep)


def off_url(user_id: int, env=None) -> str:
    """The one-click link in every alert email that turns EMAIL alerts off (api/alerts_routes.py)."""
    from urllib.parse import quote
    return f"{email_prefs.base_url(env)}/alerts/off?t={quote(email_prefs.token(user_id), safe='')}"


def _process(user, prefs, channel: str, *, http, env, now, paid_check, sleep, counts: dict) -> None:
    kinds = alerts.KINDS if prefs["events"] == "both" else (prefs["events"],)
    cap = RATE_CAP_PER_HOUR.get(channel, 12)
    channel_obj = ch.CHANNELS[channel]
    while True:
        with alerts.connect() as conn:
            events = _candidates(conn, user.id, channel, kinds, now)
            if not events:
                return
            group = next(iter(_groups(events)))
            if not _ready(group, now):
                counts["held_settling"] = counts.get("held_settling", 0) + 1
                return
            if _sent_last_hour(conn, user.id, channel, now) >= cap:
                counts["held_rate_cap"] = counts.get("held_rate_cap", 0) + 1
                return
            # over-cap backlog goes out as ONE message once there is room: take every ready event, not just the window
            group = events if len(events) > len(group) and _backlog(events, now) else group
            won = _claim(conn, channel, group, now)
        if not won:
            return
        key = batch_key(user.id, channel, [e["id"] for e in won])
        ctx = _context(user, prefs, won, channel, key, http=http, env=env, now=now, paid_check=paid_check, sleep=sleep)
        try:
            result = channel_obj.deliver(ctx) if channel_obj.has_target(ctx) else ch.Result(ch.S_SKIPPED, "no target")
        except Exception as exc:  # noqa: BLE001 -- one channel's bug must not stall the others
            logger.error("alert channel %s crashed: %s", channel, type(exc).__name__)
            result = ch.Result(ch.S_RETRY, "crashed")
        with alerts.connect() as conn:
            final = _finish(conn, channel, won, result, now)
            if final == ch.S_SENT:
                conn.execute("INSERT INTO alert_sends (user_id, channel, batch_key, n_events, sent_utc) VALUES (?,?,?,?,?)",
                             (user.id, channel, key, len(won), alerts.iso(now)))
        counts[final] = counts.get(final, 0) + len(won)
        if final != ch.S_SENT:
            return


def _backlog(events: list, now: datetime) -> bool:
    """True when the queue is older than one window (it built up behind the cap or quiet hours): send it as one."""
    first = alerts.parse_iso(events[0]["created_utc"])
    return (now - first).total_seconds() > BATCH_WINDOW_S * 2


def prune(now: datetime) -> None:
    cutoff = alerts.iso(now - timedelta(days=KEEP_DAYS))
    with alerts.connect() as conn:
        conn.execute("DELETE FROM alert_deliveries WHERE event_id IN (SELECT id FROM alert_events WHERE created_utc < ?)",
                     (cutoff,))
        conn.execute("DELETE FROM alert_events WHERE created_utc < ?", (cutoff,))
        conn.execute("DELETE FROM alert_sends WHERE sent_utc < ?", (cutoff,))


def drain(*, now: Optional[datetime] = None, http=None, env: Optional[Mapping] = None,
          paid_check: Callable = default_paid_check, sleep: Callable[[float], None] = lambda _s: None) -> dict:
    """One pass over the outbox. Returns counts by outcome. Never raises."""
    now = now or alerts.utcnow()
    http = http or mail.urllib_sender
    counts: dict = {}
    try:
        cutoff = alerts.iso(now - timedelta(seconds=EXPIRE_S))
        with alerts.connect() as conn:
            user_ids = [r[0] for r in conn.execute(
                "SELECT DISTINCT user_id FROM alert_events WHERE created_utc >= ?", (cutoff,)).fetchall()]
        for uid in user_ids:
            prefs = alerts.get_prefs(uid)
            user = users_store.get_user(uid)
            if prefs is None or user is None or getattr(user, "status", "") == "suspended":
                continue
            if in_quiet_hours(prefs, now):
                counts["held_quiet"] = counts.get("held_quiet", 0) + 1
                continue
            for name, on in prefs["channels"].items():
                if not on or not ch.CHANNELS[name].availability(env)["available"]:
                    continue
                try:
                    _process(user, prefs, name, http=http, env=env, now=now, paid_check=paid_check, sleep=sleep,
                             counts=counts)
                except Exception as exc:  # noqa: BLE001
                    logger.error("alert dispatch for a member failed: %s", type(exc).__name__)
                    counts["error"] = counts.get("error", 0) + 1
        prune(now)
    except Exception as exc:  # noqa: BLE001
        logger.error("alert drain failed: %s", type(exc).__name__)
        counts["error"] = counts.get("error", 0) + 1
    STATUS["last_tick_utc"] = alerts.iso(now)
    STATUS["last_counts"] = counts
    return counts


def send_test(user, channel: str, *, http=None, env: Optional[Mapping] = None,
              paid_check: Callable = default_paid_check, now: Optional[datetime] = None) -> dict:
    """The 'Send me a test alert' button: one sample on one channel, now, regardless of the on/off switch (a member
    tests BEFORE switching on). Returns {ok, status, message} in words the page can show."""
    now = now or alerts.utcnow()
    channel_obj = ch.CHANNELS.get(channel)
    if channel_obj is None:
        return {"ok": False, "status": "unknown", "message": "Unknown channel."}
    avail = channel_obj.availability(env)
    if not avail["available"]:
        return {"ok": False, "status": "unavailable", "message": avail["reason"]}
    prefs = alerts.ensure_prefs(user.id, now=now)
    key = hashlib.sha256(f"test|{user.id}|{channel}|{now.timestamp()}".encode()).hexdigest()[:24]
    ctx = _context(user, prefs, [], channel, key, http=http or mail.urllib_sender, env=env, now=now,
                   paid_check=paid_check, sleep=lambda _s: None)
    if channel == "sms" and not ctx.paid:
        return {"ok": False, "status": "paid_only", "message": "Text alerts are part of the member plan."}
    if not channel_obj.has_target(ctx):
        return {"ok": False, "status": "no_target", "message": _NO_TARGET.get(channel, "Nothing to send to yet.")}
    try:
        result = channel_obj.deliver_test(ctx)
    except Exception as exc:  # noqa: BLE001
        logger.error("alert test on %s crashed: %s", channel, type(exc).__name__)
        result = ch.Result(ch.S_RETRY, "crashed")
    ok = result.status == ch.S_SENT
    return {"ok": ok, "status": result.status,
            "message": "Test alert sent." if ok else "The test did not go through. Try again in a minute."}


_NO_TARGET = {"email": "No deliverable email address on this account.",
              "push": "Turn on notifications in this browser first.",
              "sms": "Add your phone number and agree to texts first.",
              "native": "The mobile app is not released yet."}


def loop_enabled(env: Optional[Mapping] = None) -> bool:
    source = env if env is not None else os.environ
    return str(source.get(ENV_LOOP) or "").strip().lower() not in ("off", "0", "false", "no")


def start_loop(*, ready: Optional[Callable[[], bool]] = None, stop_event: Optional[threading.Event] = None,
               env: Optional[Mapping] = None, tick_s: float = TICK_S,
               do_tick: Optional[Callable[[], object]] = None) -> Optional[threading.Thread]:
    """Start the ONE daemon thread (waiting for the first cache warm-up like the other loops), or None when
    ``ALERTS_JOBS`` is ``off``. A channel with no keys is simply skipped each pass."""
    if not loop_enabled(env):
        return None
    event = stop_event if stop_event is not None else threading.Event()
    tick = do_tick or drain
    STATUS["enabled"] = True

    def loop():
        waited = 0.0
        while ready is not None and not ready() and waited < WAIT_FOR_WARMUP_SECONDS:
            if event.wait(5.0):
                return
            waited += 5.0
        while not event.is_set():
            tick()
            if event.wait(tick_s):
                return

    thread = threading.Thread(target=loop, daemon=True, name="alert-dispatch")
    thread.start()
    logger.info("bet alert dispatcher started, tick=%ss", tick_s)
    return thread
