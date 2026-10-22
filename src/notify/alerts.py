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

import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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
    _migrate_feed_hash(conn)
    conn.execute("""CREATE TABLE IF NOT EXISTS sms_verifications (
        user_id INTEGER PRIMARY KEY, phone TEXT NOT NULL, code_hash TEXT NOT NULL, consent_utc TEXT NOT NULL,
        expires_utc TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, sent_utc TEXT NOT NULL,
        window_start_utc TEXT NOT NULL, window_count INTEGER NOT NULL DEFAULT 1)""")
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


def _hash_token(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def _migrate_feed_hash(conn) -> None:
    """The RSS feed is looked up by the SHA-256 of its token (an index probe on a hash tells a guesser nothing about
    the token itself), then confirmed with a constant-time compare. Adds the column to a table made before it."""
    columns = {r[1] for r in conn.execute("PRAGMA table_info(alert_prefs)").fetchall()}
    if "feed_hash" not in columns:
        try:
            conn.execute("ALTER TABLE alert_prefs ADD COLUMN feed_hash TEXT")
        except Exception:  # noqa: BLE001 -- another process added it first
            pass
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS alert_prefs_feed_hash ON alert_prefs(feed_hash)")
    for row in conn.execute("SELECT user_id, feed_token FROM alert_prefs WHERE feed_hash IS NULL "
                            "AND feed_token IS NOT NULL").fetchall():
        conn.execute("UPDATE alert_prefs SET feed_hash = ? WHERE user_id = ? AND feed_hash IS NULL",
                     (_hash_token(row[1]), row[0]))


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
        fresh = secrets.token_urlsafe(24)
        conn.execute("INSERT OR IGNORE INTO alert_prefs (user_id, feed_token, feed_hash, created_utc, updated_utc) "
                     "VALUES (?, ?, ?, ?, ?)", (int(user_id), fresh, _hash_token(fresh), stamp, stamp))
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


def zone(name: str):
    """A tzinfo for ``name``, or None when it is unknown. A machine with no tz database (a Windows laptop, the test
    image) still knows Eastern, through the written-out US daylight rules in src/data/eastern.py."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 -- an unknown zone, or no tz database on the machine
        if name == DEFAULT_TZ:
            from src.data.eastern import EASTERN_FALLBACK
            return EASTERN_FALLBACK
        return None


def _zone_ok(name: str) -> bool:
    return zone(name) is not None


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


def sms_opt_in(user_id: int, phone: str, *, now: Optional[datetime] = None,
               consent_utc: Optional[str] = None) -> dict:
    """Store a number that has ALREADY been verified (``sms_confirm`` is the route's only caller: a text with a code
    reached the number first). Clears an old STOP. ``consent_utc`` is when the member ticked the agree box."""
    number = normalize_phone(phone)
    if number is None:
        raise AlertError("phone_invalid", "enter a US mobile number")
    ensure_prefs(user_id, now=now)
    stamp = iso(now or utcnow())
    with _lock, connect() as conn:
        conn.execute("UPDATE alert_prefs SET phone = ?, sms_consent_utc = ?, sms_stopped = 0, updated_utc = ? "
                     "WHERE user_id = ?", (number, consent_utc or stamp, stamp, int(user_id)))
    return get_prefs(user_id)


# -- phone verification: a number is stored only after the member types back a code texted to it ----------------------
# Without this a paid member could type ANY number and have LINEHOUND text a stranger. The code is 6 digits, valid 10
# minutes, 5 tries; a member may ask for at most 5 codes an hour and one per minute; a number gets at most one code
# per 10 minutes across all members. Only a hash of the code is stored and the code is never logged.

SMS_CODE_TTL_S = 600
SMS_CODE_TRIES = 5
SMS_CODE_GAP_S = 60
SMS_CODE_PER_HOUR = 5
SMS_NUMBER_GAP_S = 600


def _code_hash(user_id: int, phone: str, code: str) -> str:
    return hashlib.sha256(f"{int(user_id)}|{phone}|{code}".encode()).hexdigest()


def sms_begin(user_id: int, phone: str, *, now: Optional[datetime] = None) -> tuple:
    """Start verification: returns (number, code) for the caller to TEXT to that number. Nothing is stored on the
    member's preferences yet. Raises AlertError(429) when asked too often."""
    number = normalize_phone(phone)
    if number is None:
        raise AlertError("phone_invalid", "enter a US mobile number")
    at = now or utcnow()
    stamp = iso(at)
    ensure_prefs(user_id, now=now)
    with _lock, connect() as conn:
        mine = conn.execute("SELECT * FROM sms_verifications WHERE user_id = ?", (int(user_id),)).fetchone()
        window_start, count = stamp, 1
        if mine is not None:
            last = parse_iso(mine["sent_utc"])
            if last is not None and (at - last).total_seconds() < SMS_CODE_GAP_S:
                raise AlertError("sms_code_too_soon", "wait a minute before asking for another code", 429)
            started = parse_iso(mine["window_start_utc"])
            if started is not None and (at - started).total_seconds() < 3600:
                window_start, count = mine["window_start_utc"], int(mine["window_count"]) + 1
                if count > SMS_CODE_PER_HOUR:
                    raise AlertError("sms_code_limit", "too many codes this hour; try again later", 429)
        for r in conn.execute("SELECT sent_utc FROM sms_verifications WHERE phone = ? AND user_id != ?",
                              (number, int(user_id))).fetchall():
            sent = parse_iso(r["sent_utc"])
            if sent is not None and (at - sent).total_seconds() < SMS_NUMBER_GAP_S:
                raise AlertError("sms_number_busy", "a code was just sent to that number; try again later", 429)
        code = f"{secrets.randbelow(10 ** 6):06d}"
        conn.execute(
            "INSERT INTO sms_verifications (user_id, phone, code_hash, consent_utc, expires_utc, attempts, sent_utc, "
            "window_start_utc, window_count) VALUES (?,?,?,?,?,0,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
            "phone = excluded.phone, code_hash = excluded.code_hash, consent_utc = excluded.consent_utc, "
            "expires_utc = excluded.expires_utc, attempts = 0, sent_utc = excluded.sent_utc, "
            "window_start_utc = excluded.window_start_utc, window_count = excluded.window_count",
            (int(user_id), number, _code_hash(user_id, number, code), stamp,
             iso(at + timedelta(seconds=SMS_CODE_TTL_S)), stamp, window_start, count))
    return number, code


def sms_cancel_pending(user_id: int) -> None:
    with _lock, connect() as conn:
        conn.execute("DELETE FROM sms_verifications WHERE user_id = ?", (int(user_id),))


def sms_pending_phone(user_id: int, *, now: Optional[datetime] = None) -> Optional[str]:
    """The number a code was sent to that is still waiting for it, else None."""
    with connect() as conn:
        row = conn.execute("SELECT phone, expires_utc FROM sms_verifications WHERE user_id = ?",
                           (int(user_id),)).fetchone()
    if row is None:
        return None
    expires = parse_iso(row["expires_utc"])
    return row["phone"] if expires is not None and (now or utcnow()) < expires else None


def sms_confirm(user_id: int, code: Any, *, now: Optional[datetime] = None) -> dict:
    """Check the typed code. On success the number is stored with the member's consent time and the pending row is
    removed; a wrong code costs one of five tries; an expired or exhausted one is deleted."""
    at = now or utcnow()
    typed = re.sub(r"\D", "", str(code or ""))
    failure: Optional[AlertError] = None
    phone = consent = ""
    with _lock, connect() as conn:                # the failure is raised AFTER the block: leaving it by an exception would roll back the tries counter
        row = conn.execute("SELECT * FROM sms_verifications WHERE user_id = ?", (int(user_id),)).fetchone()
        expires = parse_iso(row["expires_utc"]) if row else None
        if row is None or expires is None or at >= expires or int(row["attempts"]) >= SMS_CODE_TRIES:
            if row is not None:
                conn.execute("DELETE FROM sms_verifications WHERE user_id = ?", (int(user_id),))
            failure = AlertError("sms_code_expired", "that code has expired; ask for a new one", 410)
        elif len(typed) != 6 or not hmac.compare_digest(_code_hash(user_id, row["phone"], typed).encode(),
                                                        row["code_hash"].encode()):
            conn.execute("UPDATE sms_verifications SET attempts = attempts + 1 WHERE user_id = ?", (int(user_id),))
            failure = AlertError("sms_code_wrong", "that code is not right", 422)
        else:
            phone, consent = row["phone"], row["consent_utc"]
            conn.execute("DELETE FROM sms_verifications WHERE user_id = ?", (int(user_id),))
    if failure is not None:
        raise failure
    return sms_opt_in(user_id, phone, now=at, consent_utc=consent)


def sms_start(phone: str, *, now: Optional[datetime] = None) -> int:
    """START (or YES / UNSTOP) from a number that was verified and opted in: lift the STOP flag and switch texts back
    on. A number nobody verified is untouched. Returns how many members were switched back on."""
    number = normalize_phone(phone)
    if number is None:
        return 0
    n = 0
    with _lock, connect() as conn:
        for row in conn.execute("SELECT * FROM alert_prefs WHERE phone = ? AND sms_consent_utc IS NOT NULL "
                                "AND sms_stopped = 1", (number,)).fetchall():
            channels = _row_prefs(row)["channels"]
            channels["sms"] = True
            conn.execute("UPDATE alert_prefs SET channels_json = ?, sms_stopped = 0, updated_utc = ? "
                         "WHERE user_id = ?", (json.dumps(channels, sort_keys=True), iso(now or utcnow()),
                                               row["user_id"]))
            n += 1
    return n


def sms_remove(user_id: int, *, now: Optional[datetime] = None) -> None:
    """Forget the number and the consent and turn SMS off (and drop a code still waiting to be typed)."""
    sms_cancel_pending(user_id)
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
        conn.execute("UPDATE alert_prefs SET feed_token = ?, feed_hash = ?, updated_utc = ? WHERE user_id = ?",
                     (token, _hash_token(token), iso(now or utcnow()), int(user_id)))
    return token


def user_for_feed_token(token: Any) -> Optional[int]:
    """The member a secret RSS token belongs to, or None. The token is 192 random bits; an unknown one reveals nothing."""
    text = str(token or "")
    if len(text) < 20 or len(text) > 80:
        return None
    with connect() as conn:
        row = conn.execute("SELECT user_id, feed_token FROM alert_prefs WHERE feed_hash = ?",
                           (_hash_token(text),)).fetchone()
    if row is None or not hmac.compare_digest(str(row["feed_token"] or "").encode(), text.encode()):
        return None
    return int(row["user_id"])


# ---------------------------------------------------------------------------
# push subscriptions and native device tokens
# ---------------------------------------------------------------------------

#: the push services the browsers use. The server POSTs to whatever endpoint a member saves, so an endpoint outside
#: these hosts is refused (otherwise a member could aim the server at any https address it can reach).
PUSH_HOST_SUFFIXES = ("fcm.googleapis.com", "android.googleapis.com", "push.services.mozilla.com", "push.apple.com",
                      "notify.windows.com")
MAX_PUSH_SUBSCRIPTIONS = 10


def push_endpoint_ok(endpoint: Any) -> bool:
    from urllib.parse import urlparse
    try:
        parsed = urlparse(str(endpoint))
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.username or parsed.password or port not in (None, 443):
        return False
    return any(host == suffix or host.endswith("." + suffix) for suffix in PUSH_HOST_SUFFIXES)


def _b64u_len(text: Any) -> int:
    import base64
    raw = str(text)
    try:
        return len(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except Exception:  # noqa: BLE001
        return -1


def add_push_subscription(user_id: int, endpoint: str, p256dh: str, auth: str, *, now: Optional[datetime] = None) -> None:
    if not push_endpoint_ok(endpoint) or len(endpoint) > 1000 or _b64u_len(p256dh) != 65 or _b64u_len(auth) != 16:
        raise AlertError("subscription_invalid", "that is not a push subscription")
    with _lock, connect() as conn:
        known = conn.execute("SELECT 1 FROM push_subscriptions WHERE endpoint = ?", (endpoint,)).fetchone()
        mine = conn.execute("SELECT COUNT(*) FROM push_subscriptions WHERE user_id = ?", (int(user_id),)).fetchone()[0]
        if known is None and mine >= MAX_PUSH_SUBSCRIPTIONS:
            raise AlertError("subscription_limit", "too many browsers; remove one first", 409)
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


def _is_replay(row: Mapping) -> bool:
    return row.get("provenance") == "replay" or row.get("segment") == "replay"


def emit_placed(row: Mapping, *, now: Optional[datetime] = None) -> bool:
    """One 'bet placed' event for a freshly written bet row. True when an event was written."""
    if row.get("kind") not in (None, "hound_user_bet") or _is_replay(row) or row.get("role"):
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
    result = str(graded.get("result") or "").lower()          # the grader writes WIN / LOSS / PUSH / VOID
    # A replay bet (the "before you unleashed" list, a backtest, a rehearsal) is graded in a scratch ledger by the same
    # settler; it is not the member's record, so it never alerts.
    if result not in SETTLED_RESULTS or bet.get("role") or _is_replay(bet):
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
