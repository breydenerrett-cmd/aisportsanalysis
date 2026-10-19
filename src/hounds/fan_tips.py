"""Fan tips: what a fan would turn a dog's dials to, kept so the coach's report card can grade them later.

THE RULE THIS FILE EXISTS TO KEEP: A TIP NEVER CHANGES A DOG. Only the referee changes a dog
(src/hounds/learning/referee.py). A tip is a row in a table. Nothing reads it back into a hound, a
challenger or a bet; the only readers are the page ("Fan tips: 7") and the export a later grading job
pulls, which grades tips the way the AI coach's proposals are graded. Keeping that separation total is
the whole safety story, so there is no function here that can write anywhere but this table.

VALIDATION IS THE COACH'S (``tunables.validate``): names the dog declares, numbers, inside the bounds, on
the step grid, at least one knob different from the dog's current values and at most
``rules.MAX_KNOBS_CHANGED`` (2) of them. A page that sends all the dials is fine: knobs equal to the
current value are not "changed". A dog with no ``tunable`` block cannot be tipped.

RATE LIMITS LIVE IN THE DATABASE, NOT IN MEMORY. The app redeploys hourly (a working-branch push reaches
production within the hour), and a per-process counter would forget every deploy. The limits are counted
from the rows themselves: 3 tips a day per caller, 60 a day for the whole site. The caller is a salted
hash of the address (the salt is made once and kept in this database), kept only 2 days and then blanked,
and never exported. The clock and the address are arguments so the limits are tested without sleeping.

NICKNAME: optional, at most 20 characters, letters, numbers and spaces only, and it goes through
``user_spec.text_problem`` (the same blocklist a dog's name does). It appears on the public page, so it is
treated like any other text a stranger wrote.

SAME FILE, SAME PATTERN as src/hounds/user_store.py: the app database (``users.db_path()``, APP_DB_PATH
overrides it), ``CREATE TABLE IF NOT EXISTS``, additive only.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Mapping, Optional

from src.appstate import users as users_store
from src.hounds import user_spec
from src.hounds.learning import rules, tunables

NICKNAME_MAX = 20
NICKNAME_RE = re.compile(r"^[A-Za-z0-9 ]+$")
PER_CALLER_PER_DAY = 3
SITE_PER_DAY = 60
WINDOW = timedelta(days=1)
CALLER_HASH_KEPT = timedelta(days=2)
LATEST_LIMIT = 20
EXPORT_LIMIT = 5000       # a hard ceiling on one export; the grading job pages with ``since``

COPY_NEVER_CHANGES = "Tips are graded like the AI coach's. Only the referee can change a dog."


class TipError(ValueError):
    """A refusal the caller can show. ``code`` is stable, ``status`` the HTTP status, ``errors`` per field."""

    def __init__(self, code: str, message: str, status: int = 400, errors: Optional[Mapping] = None,
                 retry_after: Optional[int] = None):
        self.code = code
        self.status = status
        self.errors = dict(errors or {})
        self.retry_after = retry_after
        super().__init__(message)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hound_tips (
            id TEXT PRIMARY KEY,
            hound_id TEXT NOT NULL,
            values_json TEXT NOT NULL,
            champion_json TEXT NOT NULL,
            champion_version INTEGER NOT NULL,
            nickname TEXT,
            created_utc TEXT NOT NULL,
            caller_hash TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS hound_tips_hound ON hound_tips(hound_id, created_utc)")
    conn.execute("CREATE INDEX IF NOT EXISTS hound_tips_created ON hound_tips(created_utc)")
    conn.execute("CREATE TABLE IF NOT EXISTS hound_tips_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")


@contextmanager
def _connect(db: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    with users_store._connect(db) as conn:
        _ensure_schema(conn)
        yield conn


def db_file(db: Optional[Path] = None) -> Path:
    return Path(db) if db is not None else users_store.db_path()


def _salt(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value FROM hound_tips_meta WHERE key = 'caller_salt'").fetchone()
    if row:
        return row["value"]
    salt = secrets.token_hex(16)
    conn.execute("INSERT INTO hound_tips_meta(key, value) VALUES ('caller_salt', ?)", (salt,))
    return salt


def _caller_hash(salt: str, caller: str) -> str:
    return hashlib.sha256(f"{salt}|{caller}".encode("utf-8")).hexdigest()


# ---- validation ------------------------------------------------------------------------------------------

def clean_nickname(raw) -> Optional[str]:
    """The nickname to store, None for none, or TipError. Whitespace is squashed before the checks."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise TipError("bad_nickname", "the nickname must be text", errors={"nickname": "must be text"})
    text = " ".join(raw.split())
    if not text:
        return None
    if len(text) > NICKNAME_MAX:
        raise TipError("bad_nickname", f"keep the nickname to {NICKNAME_MAX} characters",
                       errors={"nickname": f"at most {NICKNAME_MAX} characters"})
    if not NICKNAME_RE.match(text):
        raise TipError("bad_nickname", "a nickname is letters, numbers and spaces only",
                       errors={"nickname": "letters, numbers and spaces only"})
    problem = user_spec.text_problem(text)
    if problem:
        raise TipError("bad_nickname", f"that nickname {problem}", errors={"nickname": problem})
    return text


def validate_tip(hound_id: str, proposed, *, tun_cfg: Optional[Mapping] = None,
                 champion_values: Optional[Mapping] = None) -> tuple:
    """``(hound, champion_values, new_values)`` or TipError. ``champion_values`` is injectable for tests;
    the default is the learning ledger's current champion (dials.champion_state)."""
    cfg = tun_cfg if tun_cfg is not None else tunables.load()
    tun = cfg.get(hound_id)
    if tun is None:
        raise TipError("not_tunable", "this dog has no dials to tip", status=404)
    if champion_values is None:
        from src.hounds import dials
        _version, params, _last = dials.champion_state(hound_id)
        champion_values = tunables.full_values(tun, params)
    try:
        values = tunables.validate(tun, champion_values, proposed)
    except tunables.TunableError as exc:
        raise TipError("bad_values", str(exc), errors=exc.errors) from exc
    return tun, dict(champion_values), values


# ---- writing ---------------------------------------------------------------------------------------------

def submit(hound_id: str, proposed, nickname, caller: str, *, now: Optional[datetime] = None,
           db: Optional[Path] = None, tun_cfg: Optional[Mapping] = None,
           champion_values: Optional[Mapping] = None, champion_version: Optional[int] = None) -> dict:
    """Validate and store one tip; returns ``{id, hound_id, values, created_utc}``.

    Order: shape first (so a bad tip never spends a caller's allowance), then the limits, then the insert,
    the last two inside one BEGIN IMMEDIATE so two requests cannot both take the last slot."""
    when = _now(now)
    nick = clean_nickname(nickname)
    tun, champ, values = validate_tip(hound_id, proposed, tun_cfg=tun_cfg, champion_values=champion_values)
    if champion_version is None:
        from src.hounds import dials
        champion_version = dials.champion_state(hound_id)[0]
    created = _iso(when)
    with _connect(db) as conn:
        conn.execute("BEGIN IMMEDIATE")
        salt = _salt(conn)
        who = _caller_hash(salt, str(caller or "unknown"))
        since = _iso(when - WINDOW)
        site = conn.execute("SELECT COUNT(*) AS n FROM hound_tips WHERE created_utc > ?", (since,)).fetchone()["n"]
        mine = conn.execute("SELECT COUNT(*) AS n FROM hound_tips WHERE created_utc > ? AND caller_hash = ?",
                            (since, who)).fetchone()["n"]
        if mine >= PER_CALLER_PER_DAY:
            raise TipError("rate_limited", f"that's {PER_CALLER_PER_DAY} tips today. Come back tomorrow.",
                           status=429, retry_after=_retry_after(conn, when, who))
        if site >= SITE_PER_DAY:
            raise TipError("site_full", "the tip jar is full for today. Try again tomorrow.", status=429,
                           retry_after=_retry_after(conn, when, None))
        # the caller hash is a rate-limit key, not a record: blank it once it is old enough to be useless
        conn.execute("UPDATE hound_tips SET caller_hash = NULL WHERE caller_hash IS NOT NULL AND created_utc < ?",
                     (_iso(when - CALLER_HASH_KEPT),))
        tip_id = "tip_" + secrets.token_hex(5)
        conn.execute(
            "INSERT INTO hound_tips(id, hound_id, values_json, champion_json, champion_version, nickname,"
            " created_utc, caller_hash) VALUES (?,?,?,?,?,?,?,?)",
            (tip_id, hound_id, json.dumps(values, sort_keys=True), json.dumps(champ, sort_keys=True),
             int(champion_version), nick, created, who))
    return {"id": tip_id, "hound_id": hound_id, "values": values, "nickname": nick, "created_utc": created}


def _retry_after(conn, when: datetime, who: Optional[str]) -> int:
    """Seconds until the oldest tip in the window falls out of it (the caller's own, or the site's)."""
    since = _iso(when - WINDOW)
    if who is None:
        row = conn.execute("SELECT MIN(created_utc) AS t FROM hound_tips WHERE created_utc > ?", (since,)).fetchone()
    else:
        row = conn.execute("SELECT MIN(created_utc) AS t FROM hound_tips WHERE created_utc > ? AND caller_hash = ?",
                           (since, who)).fetchone()
    if not row or not row["t"]:
        return 3600
    oldest = datetime.strptime(row["t"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return max(1, int((oldest + WINDOW - when).total_seconds()))


# ---- reading ---------------------------------------------------------------------------------------------

def _rows(db: Optional[Path], sql: str, args: tuple) -> list:
    if not db_file(db).is_file():
        return []          # no database yet means no tips; a GET must not create the file
    with _connect(db) as conn:
        return conn.execute(sql, args).fetchall()


def count_for(hound_id: str, *, db: Optional[Path] = None) -> int:
    rows = _rows(db, "SELECT COUNT(*) AS n FROM hound_tips WHERE hound_id = ?", (hound_id,))
    return int(rows[0]["n"]) if rows else 0


def latest(hound_id: str, *, limit: int = LATEST_LIMIT, db: Optional[Path] = None) -> list:
    """The newest tips for the page: id, values, nickname, when. Nothing that identifies a caller."""
    rows = _rows(db, "SELECT id, values_json, nickname, created_utc FROM hound_tips WHERE hound_id = ?"
                     " ORDER BY created_utc DESC, id DESC LIMIT ?", (hound_id, int(limit)))
    return [{"id": r["id"], "values": json.loads(r["values_json"]), "nickname": r["nickname"],
             "created_utc": r["created_utc"]} for r in rows]


def export(since: Optional[str] = None, *, db: Optional[Path] = None) -> list:
    """Every tip (oldest first) created strictly after ``since``, for the grading job. No caller hash, no IP:
    the SELECT never names that column, so it cannot leak by a later edit to the row shape."""
    args: tuple = ()
    sql = ("SELECT id, hound_id, values_json, champion_json, champion_version, nickname, created_utc"
           " FROM hound_tips")
    if since:
        sql += " WHERE created_utc > ?"
        args = (since,)
    sql += " ORDER BY created_utc ASC, id ASC LIMIT ?"
    rows = _rows(db, sql, args + (EXPORT_LIMIT,))
    return [{"id": r["id"], "hound_id": r["hound_id"], "values": json.loads(r["values_json"]),
             "champion_values": json.loads(r["champion_json"]), "champion_version": r["champion_version"],
             "nickname": r["nickname"], "created_utc": r["created_utc"]} for r in rows]


def parse_since(text: Optional[str]) -> Optional[str]:
    """An ISO instant (Z or an offset, or a bare date) as the stored UTC form, or None for none. Raises
    TipError for text that is not a time, so a typo does not silently export everything."""
    if text is None or not str(text).strip():
        return None
    raw = str(text).strip()
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TipError("bad_since", "since must be an ISO time like 2026-10-18T00:00:00Z",
                       errors={"since": "not an ISO time"}) from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return _iso(moment)
