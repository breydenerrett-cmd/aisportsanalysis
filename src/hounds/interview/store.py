"""The interview's three tables, in the existing app database. Additive only: `CREATE TABLE IF NOT EXISTS`.

Same pattern as src/hounds/user_store.py and src/hounds/english/jobs.py: the db path is resolved through
`users_store.db_path()` at call time, so a test that points APP_DB_PATH at a temp file redirects this module too.

  interview_sessions   one row per interview: the JSON state, a revision counter and a status. Private to its owner.
  strategy_records     the confirmed record (JSON), its freeze_hash and the hound it created. Private to its owner.
  claimed_history      dated history a person said they kept. The column `verification` can only ever hold
                       'claimed_unverified' (a CHECK, so no later code path can quietly store it as anything else), and
                       nothing in this program joins the table to a hound's ledger, stats or leaderboard row.

`save_session` is optimistic: it writes only if the revision it read is still the stored one, so two quick taps on
the same button cannot both apply to the same state.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List, Mapping, Optional

from src.appstate import users as users_store
from src.hounds.interview import history as H

STATUS_OPEN = "open"
STATUS_CONFIRMED = "confirmed"
STATUS_ABANDONED = "abandoned"
MAX_OPEN_PER_USER = 10


class Conflict(Exception):
    """The session changed since it was read."""


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS interview_sessions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            rev INTEGER NOT NULL,
            state_json TEXT NOT NULL,
            created TEXT NOT NULL,
            updated TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS interview_sessions_user ON interview_sessions(user_id, status, updated)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS strategy_records (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            session_id TEXT NOT NULL,
            hound_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            status TEXT NOT NULL,
            freeze_hash TEXT NOT NULL,
            effective_date TEXT NOT NULL,
            record_json TEXT NOT NULL,
            created TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS strategy_records_user ON strategy_records(user_id, created)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS strategy_records_session ON strategy_records(session_id)")
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS claimed_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            verification TEXT NOT NULL CHECK (verification = '{H.LABEL_CODE}'),
            rows_json TEXT NOT NULL,
            rejected_json TEXT NOT NULL,
            created TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS claimed_history_record ON claimed_history(record_id)")


@contextmanager
def _connect(db: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    with users_store._connect(db) as conn:
        _ensure_schema(conn)
        yield conn


def new_session_id() -> str:
    return "iv-" + secrets.token_hex(6)


def new_record_id() -> str:
    return "sr-" + secrets.token_hex(6)


def _session(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "user_id": row["user_id"], "status": row["status"], "rev": row["rev"],
            "state": json.loads(row["state_json"]), "created": row["created"], "updated": row["updated"]}


def create_session(user_id: int, state: Mapping, now: datetime, *, db: Optional[Path] = None) -> dict:
    sid = new_session_id()
    stamp = _iso(now)
    with _connect(db) as conn:
        conn.execute("BEGIN IMMEDIATE")
        old = conn.execute("SELECT id FROM interview_sessions WHERE user_id = ? AND status = ? ORDER BY updated DESC",
                           (user_id, STATUS_OPEN)).fetchall()
        for row in old[MAX_OPEN_PER_USER - 1:]:
            conn.execute("UPDATE interview_sessions SET status = ? WHERE id = ?", (STATUS_ABANDONED, row["id"]))
        conn.execute("INSERT INTO interview_sessions (id, user_id, status, rev, state_json, created, updated) VALUES (?,?,?,?,?,?,?)",
                     (sid, user_id, STATUS_OPEN, 1, json.dumps(state, sort_keys=True), stamp, stamp))
    return get_session(sid, db=db)


def get_session(sid: str, *, db: Optional[Path] = None) -> Optional[dict]:
    with _connect(db) as conn:
        row = conn.execute("SELECT * FROM interview_sessions WHERE id = ?", (sid,)).fetchone()
    return _session(row) if row else None


def save_session(sid: str, state: Mapping, rev: int, now: datetime, *, status: str = STATUS_OPEN,
                 db: Optional[Path] = None) -> int:
    with _connect(db) as conn:
        cur = conn.execute("UPDATE interview_sessions SET state_json = ?, rev = rev + 1, updated = ?, status = ? "
                           "WHERE id = ? AND rev = ?",
                           (json.dumps(state, sort_keys=True), _iso(now), status, sid, rev))
        if cur.rowcount != 1:
            raise Conflict(sid)
    return rev + 1


def confirm_session(sid: str, rev: int, state: Mapping, *, record: Mapping, hound_id: str, user_id: int, now: datetime,
                    history_rows: Optional[List[dict]] = None, history_rejected: Optional[List[dict]] = None,
                    db: Optional[Path] = None) -> None:
    """In one transaction: the record, any claimed history, and the session closed as confirmed."""
    stamp = _iso(now)
    with _connect(db) as conn:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute("UPDATE interview_sessions SET state_json = ?, rev = rev + 1, updated = ?, status = ? "
                           "WHERE id = ? AND rev = ? AND status = ?",
                           (json.dumps(state, sort_keys=True), stamp, STATUS_CONFIRMED, sid, rev, STATUS_OPEN))
        if cur.rowcount != 1:
            raise Conflict(sid)
        conn.execute("INSERT INTO strategy_records (id, user_id, session_id, hound_id, version, status, freeze_hash, "
                     "effective_date, record_json, created) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (record["id"], user_id, sid, hound_id, record["version"], record["status"], record["freeze_hash"],
                      record["effective_date"], json.dumps(record, sort_keys=True), stamp))
        if history_rows:
            conn.execute("INSERT INTO claimed_history (record_id, user_id, verification, rows_json, rejected_json, created) "
                         "VALUES (?,?,?,?,?,?)",
                         (record["id"], user_id, H.LABEL_CODE, json.dumps(history_rows, sort_keys=True),
                          json.dumps(history_rejected or [], sort_keys=True), stamp))


def get_record(record_id: str, *, db: Optional[Path] = None) -> Optional[dict]:
    with _connect(db) as conn:
        row = conn.execute("SELECT * FROM strategy_records WHERE id = ?", (record_id,)).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "user_id": row["user_id"], "session_id": row["session_id"], "hound_id": row["hound_id"],
            "record": json.loads(row["record_json"]), "created": row["created"]}


def record_for_session(sid: str, *, db: Optional[Path] = None) -> Optional[dict]:
    with _connect(db) as conn:
        row = conn.execute("SELECT id FROM strategy_records WHERE session_id = ?", (sid,)).fetchone()
    return get_record(row["id"], db=db) if row else None


def list_records(user_id: int, *, db: Optional[Path] = None) -> List[dict]:
    with _connect(db) as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM strategy_records WHERE user_id = ? ORDER BY created DESC", (user_id,))]
    return [get_record(i, db=db) for i in ids]


def claimed_history(record_id: str, *, db: Optional[Path] = None) -> Optional[dict]:
    with _connect(db) as conn:
        row = conn.execute("SELECT * FROM claimed_history WHERE record_id = ? ORDER BY id DESC LIMIT 1", (record_id,)).fetchone()
    if row is None:
        return None
    rows = json.loads(row["rows_json"])
    rejected = json.loads(row["rejected_json"])
    return {"label": H.LABEL, "verification": row["verification"], "rows": rows, "rejected": rejected,
            "summary": H.summary(rows, rejected), "created": row["created"]}
