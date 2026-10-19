"""The translation-job table: one row per phrasing handed to the owner's Zapier translator.

Same file, same pattern as `user_store`: the existing app database, `CREATE TABLE IF NOT EXISTS`, db
path resolved through `users_store.db_path()` at call time (so a test pointing APP_DB_PATH at a temp
file redirects this module too), additive only.

A job is created `translating` and finishes exactly once (`done` with a validated spec, `refused`
with the reasons the menu gave, or `failed` with a short error): `finish` only updates a row that is
still `translating`, so a replayed or duplicated Zap callback cannot overwrite the first answer.
`user_id` is the owner; nothing here is ever readable by anyone else.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional

from src.appstate import users as users_store

STATUS_TRANSLATING = "translating"
STATUS_DONE = "done"
STATUS_REFUSED = "refused"
STATUS_FAILED = "failed"
STATUSES = (STATUS_TRANSLATING, STATUS_DONE, STATUS_REFUSED, STATUS_FAILED)

JOB_TTL = timedelta(hours=1)          # a callback after this is ignored: the person has long moved on
MAX_TEXT = 600


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS english_jobs (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            status TEXT NOT NULL,
            created TEXT NOT NULL,
            result_spec TEXT,
            error TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS english_jobs_user ON english_jobs(user_id, created)")


@contextmanager
def _connect(db: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    with users_store._connect(db) as conn:
        _ensure_schema(conn)
        yield conn


def new_job_id() -> str:
    return "j-" + secrets.token_hex(8)


def _row(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "user_id": row["user_id"], "text": row["text"], "status": row["status"],
            "created": row["created"], "result": json.loads(row["result_spec"]) if row["result_spec"] else None,
            "error": row["error"]}


def create_job(user_id: int, text: str, *, partial: Optional[Mapping] = None,
               now: Optional[datetime] = None, db: Optional[Path] = None) -> dict:
    """A new `translating` job. `partial` is what the deterministic parser already understood, kept
    so the poll can show it beside the translator's answer."""
    job_id = new_job_id()
    stamp = _iso(now or datetime.now(timezone.utc))
    with _connect(db) as conn:
        conn.execute("INSERT INTO english_jobs (id, user_id, text, status, created, result_spec, error) "
                     "VALUES (?,?,?,?,?,?,NULL)",
                     (job_id, user_id, text[:MAX_TEXT], STATUS_TRANSLATING, stamp,
                      json.dumps({"partial": partial}, sort_keys=True) if partial else None))
    return get_job(job_id, db=db)


def get_job(job_id: str, *, db: Optional[Path] = None) -> Optional[dict]:
    with _connect(db) as conn:
        row = conn.execute("SELECT * FROM english_jobs WHERE id = ?", (job_id,)).fetchone()
    return _row(row) if row else None


def finish(job_id: str, status: str, *, result: Optional[Mapping] = None, error: Optional[str] = None,
           db: Optional[Path] = None) -> bool:
    """Close a job that is still `translating`. True for the call that did; a second one is a no-op."""
    if status not in (STATUS_DONE, STATUS_REFUSED, STATUS_FAILED):
        raise ValueError("a job finishes as done, refused or failed")
    with _connect(db) as conn:
        current = conn.execute("SELECT result_spec FROM english_jobs WHERE id = ?", (job_id,)).fetchone()
        merged = json.loads(current["result_spec"]) if current and current["result_spec"] else {}
        merged.update(result or {})
        cur = conn.execute("UPDATE english_jobs SET status = ?, result_spec = ?, error = ? "
                           "WHERE id = ? AND status = ?",
                           (status, json.dumps(merged, sort_keys=True) if merged else None,
                            (error or "")[:300] or None, job_id, STATUS_TRANSLATING))
        return cur.rowcount == 1


def recent_count(user_id: int, since: datetime, *, db: Optional[Path] = None) -> int:
    with _connect(db) as conn:
        return conn.execute("SELECT COUNT(*) FROM english_jobs WHERE user_id = ? AND created >= ?",
                            (user_id, _iso(since))).fetchone()[0]


def is_expired(job: Mapping, now: Optional[datetime] = None) -> bool:
    created = datetime.fromisoformat(job["created"].replace("Z", "+00:00"))
    return (now or datetime.now(timezone.utc)) - created > JOB_TTL
