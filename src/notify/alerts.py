"""Bet alerts, the store and the event emitters: "your hound just bet", "your hound's bet settled".

WHY THIS EXISTS (owner, 2026-10-21): "when our hounds are making bets, send them to us ASAP so we can see them
live." The owner said SMS; Resend is email-only and real SMS needs a paid carrier registration (docs/owner/ALERTS.md),
so the plumbing is CHANNEL-AGNOSTIC: one event stream, one preference row per member, and channels that plug in
(email, web push, SMS, and a native APNs/FCM channel later; see ``alert_channels.py``). This module owns the data
and the two emitters. ``alert_render.py`` words the messages, ``alert_dispatch.py`` drains the outbox.

THE EMITTERS NEVER BLOCK A BET. ``emit_placed_safe`` / ``emit_settled_safe`` are called right AFTER the ledger write
in user_engine.run, interact/manual.record and user_settle.settle. They catch everything: a failing alert table
(locked database, full disk, a bug here) is logged and swallowed, and the bet stays written. The ledger is the
record; an alert is a courtesy about it. tests/test_bet_alerts.py injects a failure to pin that.

WHO GETS AN EVENT. Only a MEMBER hound (a row in ``hounds``; the house pack and shadow challengers are not) whose
owner has an alert-preferences row, which exists once they open Account -> Alerts. A hound nobody asked alerts
about writes nothing, which also keeps a test that runs the engine against a scratch ledger from filling the real
app database. A replay (a back-fill of a past date) never alerts.

TABLES (all additive, in the one app database, like src/hounds/unit_size.py)
  alert_prefs         one row per member: channels on/off (``channels_json``), which events, quiet hours, the secret
                      RSS token, the opted-in phone number (SMS only) and the STOP flag.
  alert_events        the outbox: one row per (member, kind, bet), UNIQUE so the same bet cannot be emitted twice.
                      Also the source of the per-member RSS feed.
  alert_deliveries    per (event, channel): pending/retry/sent/skipped/dead, attempts, next try. This is the
                      idempotency record: a (event, channel) that is ``sent`` is never sent again.
  alert_sends         one row per message actually handed to a channel: the rate cap counts these.
  push_subscriptions  Web Push endpoints (one per browser the member subscribed).
  alert_devices       DEVICE-TOKEN TABLE for the native apps (Capacitor wrapper, APNs/FCM). Nothing writes it yet but
                      ``register_device``; the native channel is a stub that reads it (alert_channels.NativePushChannel).

NO SECRETS IN LOGS: nothing here logs a phone number, an endpoint, a token or a message body.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, List, Mapping, Optional

from src.appstate import users as users_store

logger = logging.getLogger("linehound.notify.alerts")

KIND_PLACED = "placed"
KIND_SETTLED = "settled"
KINDS = (KIND_PLACED, KIND_SETTLED)

#: which events a member wants: placed only, settled only, or both
EVENTS_CHOICES = ("placed", "settled", "both")
DEFAULT_EVENTS = "both"
DEFAULT_TZ = "America/New_York"
#: the channels a member can switch on (alert_channels.py registers one object per name). Native is listed so the
#: preference exists the day the app ships; with no device registered it simply has nothing to send to.
CHANNEL_NAMES = ("email", "push", "sms", "native")

SETTLED_RESULTS = ("win", "loss", "push")

_lock = threading.Lock()


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# schema, connection
# ---------------------------------------------------------------------------

def _ensure_schema(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS alert_prefs (
        user_id INTEGER PRIMARY KEY, channels_json TEXT NOT NULL DEFAULT '{}',
        events TEXT NOT NULL DEFAULT 'both', quiet_start INTEGER, quiet_end INTEGER,
        tz TEXT NOT NULL DEFAULT 'America/New_York', feed_token TEXT,
        phone TEXT, sms_consent_utc TEXT, sms_stopped INTEGER NOT NULL DEFAULT 0,
        created_utc TEXT, updated_utc TEXT)""")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS alert_prefs_feed ON alert_prefs(feed_token)")
    conn.execute("""CREATE TABLE IF NOT EXISTS alert_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, kind TEXT NOT NULL,
        hound_id TEXT NOT NULL, bet_id TEXT NOT NULL, payload_json TEXT NOT NULL, created_utc TEXT NOT NULL,
        UNIQUE(user_id, kind, bet_id))""")
    conn.execute("CREATE INDEX IF NOT EXISTS alert_events_user ON alert_events(user_id, id)")
    conn.execute("""CREATE TABLE IF NOT EXISTS alert_deliveries (
        event_id INTEGER NOT NULL, channel TEXT NOT NULL, status TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0, next_try_utc TEXT, detail TEXT, updated_utc TEXT,
        PRIMARY KEY(event_id, channel))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS alert_sends (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, channel TEXT NOT NULL,
        batch_key TEXT NOT NULL, n_events INTEGER NOT NULL, sent_utc TEXT NOT NULL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS alert_sends_user ON alert_sends(user_id, channel, sent_utc)")
    conn.execute("""CREATE TABLE IF NOT EXISTS push_subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, endpoint TEXT NOT NULL UNIQUE,
        p256dh TEXT NOT NULL, auth TEXT NOT NULL, created_utc TEXT NOT NULL, last_ok_utc TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS alert_devices (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, platform TEXT NOT NULL,
        token TEXT NOT NULL UNIQUE, app_version TEXT, created_utc TEXT NOT NULL, last_seen_utc TEXT,
        revoked_utc TEXT)""")


@contextmanager
def connect() -> Iterator:
    with users_store._connect() as conn:
        _ensure_schema(conn)
        yield conn


# ---------------------------------------------------------------------------
# preferences
# ---------------------------------------------------------------------------

def _row_prefs(row) -> dict:
    try:
        channels = json.loads(row["channels_json"] or "{}")
    except ValueError:
        channels = {}
    return {"user_id": row["user_id"], "channels": {n: bool(channels.get(n)) for n in CHANNEL_NAMES},
            "events": row["events"], "quiet_start": row["quiet_start"], "quiet_end": row["quiet_end"],
            "tz": row["tz"], "feed_token": row["feed_token"], "phone": row["phone"],
            "sms_consent_utc": row["sms_consent_utc"], "sms_stopped": bool(row["sms_stopped"])}


def get_prefs(user_id: int) -> Optional[dict]:
    """The member's preferences, or None when they have never opened Alerts (no row, so no events for them)."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM alert_prefs WHERE user_id = ?", (int(user_id),)).fetchone()
    return _row_prefs(row) if row else None


def ensure_prefs(user_id: int, *, now: Optional[datetime] = None) -> dict:
    """Create the all-off row (with its secret RSS token) the first time, then return it."""
    stamp = iso(now or utcnow())
    with _lock, connect() as conn:
        conn.execute("INSERT OR IGNORE INTO alert_prefs (user_id, feed_token, created_utc, updated_utc) "
                     "VALUES (?, ?, ?, ?)", (int(user_id), secrets.token_urlsafe(24), stamp, stamp))
        row = conn.execute("SELECT * FROM alert_prefs WHERE user_id = ?", (int(user_id),)).fetchone()
    return _row_prefs(row)


class AlertError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422):
        self.code, self.status = code, status
        super().__init__(message)


def _hour(value, what: str) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        hour = int(value)
    except (TypeError, ValueError):
        raise AlertError("quiet_invalid", f"{what} must be an hour from 0 to 23") from None
    if not 0 <= hour <= 23:
        raise AlertError("quiet_invalid", f"{what} must be an hour from 0 to 23")
    return hour


def _zone_ok(name: str) -> bool:
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(name)
        return True
    except Exception:  # noqa: BLE001 -- an unknown zone, or no tz database on the machine
        return False


def update_prefs(user_id: int, patch: Mapping, *, now: Optional[datetime] = None) -> dict:
    """Apply a validated partial update: ``channels`` {name: bool}, ``events``, ``quiet_start``/``quiet_end`` (both
    set or both null), ``tz``. Turning SMS on is refused here unless a phone number was opted in (the opt-in has its
    own route) and the member has not replied STOP."""
    current = ensure_prefs(user_id, now=now)
    channels = dict(current["channels"])
    for name, value in (patch.get("channels") or {}).items():
        if name not in CHANNEL_NAMES:
            raise AlertError("channel_unknown", f"unknown channel {name!r}")
        channels[name] = bool(value)
    if channels.get("sms") and not (current["phone"] and current["sms_consent_utc"]):
        raise AlertError("sms_needs_opt_in", "add your phone number and agree to texts first", 409)
    if channels.get("sms") and current["sms_stopped"]:
        raise AlertError("sms_stopped", "you replied STOP; text START to the number or opt in again", 409)
    events = patch.get("events", current["events"])
    if events not in EVENTS_CHOICES:
        raise AlertError("events_invalid", "events must be placed, settled or both")
    start = _hour(patch["quiet_start"], "quiet start") if "quiet_start" in patch else current["quiet_start"]
    end = _hour(patch["quiet_end"], "quiet end") if "quiet_end" in patch else current["quiet_end"]
    if (start is None) != (end is None):
        raise AlertError("quiet_invalid", "set both quiet hours or neither")
    tz = str(patch.get("tz") or current["tz"] or DEFAULT_TZ)
    if not _zone_ok(tz):
        raise AlertError("tz_invalid", "unknown time zone")
    with _lock, connect() as conn:
        conn.execute("UPDATE alert_prefs SET channels_json = ?, events = ?, quiet_start = ?, quiet_end = ?, tz = ?, "
                     "updated_utc = ? WHERE user_id = ?",
                     (json.dumps(channels, sort_keys=True), events, start, end, tz,
                      iso(now or utcnow()), int(user_id)))
    return get_prefs(user_id) or current


PHONE_RE = re.compile(r"^\+1[2-9]\d{9}$")


def normalize_phone(raw: Any) -> Optional[str]:
    """A US number as E.164 (+1XXXXXXXXXX), or None. US only: 10DLC is a US registration."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    candidate = "+1" + digits
    return candidate if len(digits) == 10 and PHONE_RE.match(candidate) else None


def sms_opt_in(user_id: int, phone: str, *, now: Optional[datetime] = None) -> dict:
    """Store the number ONLY on an explicit opt-in (the route requires the consent box). Clears an old STOP."""
    number = normalize_phone(phone)
    if number is None:
        raise AlertError("phone_invalid", "enter a US mobile number")
    ensure_prefs(user_id, now=now)
    stamp = iso(now or utcnow())
    with _lock, connect() as conn:
        conn.execute("UPDATE alert_prefs SET phone = ?, sms_consent_utc = ?, sms_stopped = 0, updated_utc = ? "
                     "WHERE user_id = ?", (number, stamp, stamp, int(user_id)))
    return get_prefs(user_id)


def sms_remove(user_id: int, *, now: Optional[datetime] = None) -> None:
    """Forget the number and the consent and turn SMS off."""
    prefs = get_prefs(user_id)
    if prefs is None:
        return
    channels = dict(prefs["channels"])
    channels["sms"] = False
    with _lock, connect() as conn:
        conn.execute("UPDATE alert_prefs SET phone = NULL, sms_consent_utc = NULL, channels_json = ?, "
                     "updated_utc = ? WHERE user_id = ?",
                     (json.dumps(channels, sort_keys=True), iso(now or utcnow()), int(user_id)))


def sms_stop(phone: str, *, now: Optional[datetime] = None) -> int:
    """STOP: every member holding this number is switched off for SMS and flagged. Returns how many."""
    number = normalize_phone(phone)
    if number is None:
        return 0
    n = 0
    with _lock, connect() as conn:
        for row in conn.execute("SELECT * FROM alert_prefs WHERE phone = ?", (number,)).fetchall():
            channels = _row_prefs(row)["channels"]
            channels["sms"] = False
            conn.execute("UPDATE alert_prefs SET channels_json = ?, sms_stopped = 1, updated_utc = ? "
                         "WHERE user_id = ?", (json.dumps(channels, sort_keys=True), iso(now or utcnow()),
                                               row["user_id"]))
            n += 1
    return n


def rotate_feed_token(user_id: int, *, now: Optional[datetime] = None) -> str:
    ensure_prefs(user_id, now=now)
    token = secrets.token_urlsafe(24)
    with _lock, connect() as conn:
        conn.execute("UPDATE alert_prefs SET feed_token = ?, updated_utc = ? WHERE user_id = ?",
                     (token, iso(now or utcnow()), int(user_id)))
    return token


def user_for_feed_token(token: Any) -> Optional[int]:
    """The member a secret RSS token belongs to, or None. The token is 192 random bits; an unknown one reveals nothing."""
    text = str(token or "")
    if len(text) < 20 or len(text) > 80:
        return None
    with connect() as conn:
        row = conn.execute("SELECT user_id FROM alert_prefs WHERE feed_token = ?", (text,)).fetchone()
    return int(row["user_id"]) if row else None


# ---------------------------------------------------------------------------
# push subscriptions and native device tokens
# ---------------------------------------------------------------------------

def add_push_subscription(user_id: int, endpoint: str, p256dh: str, auth: str, *, now: Optional[datetime] = None) -> None:
    if not str(endpoint).startswith("https://") or len(endpoint) > 1000 or not p256dh or not auth:
        raise AlertError("subscription_invalid", "that is not a push subscription")
    with _lock, connect() as conn:
        conn.execute("INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, created_utc) VALUES (?,?,?,?,?) "
                     "ON CONFLICT(endpoint) DO UPDATE SET user_id = excluded.user_id, p256dh = excluded.p256dh, "
                     "auth = excluded.auth", (int(user_id), endpoint, p256dh, auth, iso(now or utcnow())))


def remove_push_subscription(endpoint: str, user_id: Optional[int] = None) -> int:
    with _lock, connect() as conn:
        if user_id is None:
            cur = conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
        else:
            cur = conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ? AND user_id = ?",
                               (endpoint, int(user_id)))
        return cur.rowcount


def push_subscriptions(user_id: int) -> List[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM push_subscriptions WHERE user_id = ? ORDER BY id", (int(user_id),)).fetchall()]


def mark_push_ok(endpoint: str, *, now: Optional[datetime] = None) -> None:
    with _lock, connect() as conn:
        conn.execute("UPDATE push_subscriptions SET last_ok_utc = ? WHERE endpoint = ?",
                     (iso(now or utcnow()), endpoint))


NATIVE_PLATFORMS = ("ios", "android")


def register_device(user_id: int, platform: str, token: str, app_version: str = "", *,
                    now: Optional[datetime] = None) -> None:
    """Record a native-app device token (APNs on iOS, FCM on Android). The channel that sends to it is a stub today."""
    if platform not in NATIVE_PLATFORMS or not str(token).strip() or len(token) > 400:
        raise AlertError("device_invalid", "platform must be ios or android and the token must be set")
    stamp = iso(now or utcnow())
    with _lock, connect() as conn:
        conn.execute("INSERT INTO alert_devices (user_id, platform, token, app_version, created_utc, last_seen_utc) "
                     "VALUES (?,?,?,?,?,?) ON CONFLICT(token) DO UPDATE SET user_id = excluded.user_id, "
                     "last_seen_utc = excluded.last_seen_utc, revoked_utc = NULL, app_version = excluded.app_version",
                     (int(user_id), platform, token, str(app_version)[:40], stamp, stamp))


def active_devices(user_id: int) -> List[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM alert_devices WHERE user_id = ? AND revoked_utc IS NULL ORDER BY id",
            (int(user_id),)).fetchall()]


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------

def _price_ok(price) -> bool:
    try:
        return float(price) > -200
    except (TypeError, ValueError):
        return False


def _payload_placed(row: Mapping, hound: Mapping) -> dict:
    stake = row.get("stake_units")
    if stake is None:
        stake = row.get("units")
    return {"hound_name": hound.get("name") or "Your hound", "hound_id": row["hound_id"], "sport": row.get("sport") or "",
            "market": row.get("market"), "selection": row.get("selection") or str(row.get("side") or "").title(),
            "line": row.get("line"), "price": row.get("price"), "stake_units": float(stake or 1.0),
            "away_team": row.get("away_team"), "home_team": row.get("home_team"),
            "start_utc": row.get("commence_time") or row.get("start_utc"), "bet_id": row["bet_id"]}


def _insert_event(user_id: int, kind: str, hound_id: str, bet_id: str, payload: Mapping, now: datetime) -> bool:
    """True when a new event row was written (False: already there, the UNIQUE key held)."""
    with _lock, connect() as conn:
        cur = conn.execute("INSERT OR IGNORE INTO alert_events (user_id, kind, hound_id, bet_id, payload_json, created_utc) "
                           "VALUES (?,?,?,?,?,?)", (int(user_id), kind, hound_id, bet_id,
                                                    json.dumps(dict(payload), sort_keys=True), iso(now)))
        return cur.rowcount > 0


def _owner_of(hound_id: str) -> Optional[tuple]:
    """(hound row, owner id) for a MEMBER hound that has alert preferences, else None."""
    from src.hounds import user_store
    hound = user_store.get_hound(str(hound_id))
    if hound is None:
        return None
    owner = int(hound["owner_user_id"])
    return (hound, owner) if get_prefs(owner) is not None else None


def emit_placed(row: Mapping, *, now: Optional[datetime] = None) -> bool:
    """One 'bet placed' event for a freshly written bet row. True when an event was written."""
    if row.get("kind") not in (None, "bet") or row.get("provenance") == "replay" or row.get("role"):
        return False
    if not _price_ok(row.get("price")):
        return False
    found = _owner_of(row["hound_id"])
    if found is None:
        return False
    hound, owner = found
    return _insert_event(owner, KIND_PLACED, str(row["hound_id"]), str(row["bet_id"]),
                         _payload_placed(row, hound), now or utcnow())


def emit_settled(bet: Mapping, graded: Mapping, *, now: Optional[datetime] = None) -> bool:
    """One 'bet settled' event (win, loss or push; a void is not reported)."""
    result = graded.get("result")
    if result not in SETTLED_RESULTS or bet.get("role"):
        return False
    found = _owner_of(bet["hound_id"])
    if found is None:
        return False
    hound, owner = found
    payload = _payload_placed(bet, hound)
    profit = graded.get("profit_stake_units")
    if profit is None:
        profit = graded.get("profit_units")
    payload.update({"result": result, "profit_units": None if profit is None else float(profit)})
    return _insert_event(owner, KIND_SETTLED, str(bet["hound_id"]), str(bet["bet_id"]), payload, now or utcnow())


def emit_placed_safe(row: Mapping) -> None:
    """``emit_placed`` that can never raise: a bet write must not depend on an alert."""
    try:
        emit_placed(row)
    except Exception as exc:  # noqa: BLE001 -- by design: the ledger write already happened
        logger.error("bet alert (placed) not queued: %s", type(exc).__name__)


def emit_settled_safe(bet: Mapping, graded: Mapping) -> None:
    try:
        emit_settled(bet, graded)
    except Exception as exc:  # noqa: BLE001
        logger.error("bet alert (settled) not queued: %s", type(exc).__name__)


def events_for(user_id: int, *, limit: int = 50) -> List[dict]:
    """The member's newest events, newest first, each with its decoded payload (the RSS feed reads this)."""
    with connect() as conn:
        rows = conn.execute("SELECT * FROM alert_events WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                            (int(user_id), int(limit))).fetchall()
    out = []
    for r in rows:
        try:
            payload = json.loads(r["payload_json"])
        except ValueError:
            continue
        out.append({"id": r["id"], "kind": r["kind"], "created_utc": r["created_utc"], "payload": payload})
    return out
