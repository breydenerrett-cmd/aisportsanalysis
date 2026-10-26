"""One-time member announcements: a note the owner wants a member to see once, as a full-screen card on their next page load.

TWO APPEND-ONLY TABLES in the app database, no update and no delete in this module (the same promise as the lessons
ledger, and enforced the same way: BEFORE UPDATE / BEFORE DELETE triggers abort).
  member_announcements       id, user_id, kind, title, body_json (the steps), created_utc. Written by the CLI
                             (``python -m src.cli announce``); there is no member route that creates one.
  member_announcement_seen   one row per (announcement, user), written when the member dismisses the card.
"Unseen" is therefore a join, never a flag flipped on the announcement, so the record of what was shown, and when, stays.

A seen row is idempotent (marking twice is not an error) and a member can only mark their OWN announcement: an id that
belongs to someone else reads as not found, the same answer as an id that does not exist.

Standard library only (no FastAPI): the CLI and the tests use it where there is none.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, List, Optional

from src.appstate import users as users_store

KINDS = ("kennel_fire",)
MAX_STEPS = 12
MAX_STEP_CHARS = 200

SCHEMA = """
CREATE TABLE IF NOT EXISTS member_announcements (
    id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL,
    body_json TEXT NOT NULL, created_utc TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS member_announcements_user ON member_announcements (user_id, created_utc);
CREATE TABLE IF NOT EXISTS member_announcement_seen (
    announcement_id TEXT NOT NULL, user_id INTEGER NOT NULL, seen_utc TEXT NOT NULL,
    PRIMARY KEY (announcement_id, user_id));
"""
TABLES = ("member_announcements", "member_announcement_seen")


class AnnouncementError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.status = code, status


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table in TABLES:
        for verb in ("UPDATE", "DELETE"):
            conn.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{verb.lower()} BEFORE {verb} ON {table} "
                         f"BEGIN SELECT RAISE(ABORT, 'announcements are append-only'); END")


@contextmanager
def connect(db: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    with users_store._connect(db) as conn:
        ensure_schema(conn)
        yield conn


def _stamp(now: Optional[datetime]) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_steps(steps: Any) -> List[str]:
    """A list of short non-empty strings, or ``AnnouncementError``. Nothing else is stored."""
    if not isinstance(steps, list) or not steps or len(steps) > MAX_STEPS:
        raise AnnouncementError("bad_steps", f"steps must be a list of 1 to {MAX_STEPS} lines")
    out = []
    for item in steps:
        if not isinstance(item, str) or not item.strip() or len(item.strip()) > MAX_STEP_CHARS:
            raise AnnouncementError("bad_steps", f"each step is text of 1 to {MAX_STEP_CHARS} characters")
        out.append(" ".join(item.split()))
    return out


def add(user_id: int, kind: str, steps: Any, *, title: str = "", now: Optional[datetime] = None,
        db: Optional[Path] = None) -> dict:
    if kind not in KINDS:
        raise AnnouncementError("bad_kind", f"kind must be one of {', '.join(KINDS)}")
    steps = clean_steps(steps)
    if users_store.get_user(int(user_id), db=db) is None:
        raise AnnouncementError("no_user", f"no member with id {user_id}", 404)
    row = {"id": "an-" + secrets.token_hex(5), "user_id": int(user_id), "kind": kind,
           "title": (title or "").strip()[:120] or kind, "steps": steps, "created_utc": _stamp(now)}
    with connect(db) as conn:
        conn.execute("INSERT INTO member_announcements (id, user_id, kind, title, body_json, created_utc) VALUES (?,?,?,?,?,?)",
                     (row["id"], row["user_id"], kind, row["title"], json.dumps({"steps": steps}), row["created_utc"]))
    return row


def _row(r: sqlite3.Row, seen: Optional[str] = None) -> dict:
    body = json.loads(r["body_json"])
    return {"id": r["id"], "user_id": r["user_id"], "kind": r["kind"], "title": r["title"],
            "steps": list(body.get("steps") or []), "created_utc": r["created_utc"], "seen_utc": seen}


def unseen(user_id: int, *, db: Optional[Path] = None) -> List[dict]:
    """The member's announcements they have not dismissed, oldest first."""
    with connect(db) as conn:
        rows = conn.execute(
            "SELECT a.* FROM member_announcements a LEFT JOIN member_announcement_seen s "
            "ON s.announcement_id = a.id AND s.user_id = a.user_id "
            "WHERE a.user_id = ? AND s.announcement_id IS NULL ORDER BY a.created_utc, a.id", (int(user_id),)).fetchall()
    return [_row(r) for r in rows]


def mark_seen(user_id: int, announcement_id: str, *, now: Optional[datetime] = None, db: Optional[Path] = None) -> dict:
    with connect(db) as conn:
        r = conn.execute("SELECT * FROM member_announcements WHERE id = ? AND user_id = ?",
                         (str(announcement_id), int(user_id))).fetchone()
        if r is None:
            raise AnnouncementError("not_found", "no such announcement", 404)
        conn.execute("INSERT OR IGNORE INTO member_announcement_seen (announcement_id, user_id, seen_utc) VALUES (?,?,?)",
                     (r["id"], int(user_id), _stamp(now)))
        s = conn.execute("SELECT seen_utc FROM member_announcement_seen WHERE announcement_id = ? AND user_id = ?",
                         (r["id"], int(user_id))).fetchone()
    return _row(r, s["seen_utc"])


def list_all(*, user_id: Optional[int] = None, db: Optional[Path] = None) -> List[dict]:
    """Every announcement with when it was seen (the CLI's ``--list``)."""
    sql = ("SELECT a.*, s.seen_utc AS seen FROM member_announcements a LEFT JOIN member_announcement_seen s "
           "ON s.announcement_id = a.id AND s.user_id = a.user_id")
    args: tuple = ()
    if user_id is not None:
        sql, args = sql + " WHERE a.user_id = ?", (int(user_id),)
    with connect(db) as conn:
        rows = conn.execute(sql + " ORDER BY a.created_utc, a.id", args).fetchall()
    return [_row(r, r["seen"]) for r in rows]
