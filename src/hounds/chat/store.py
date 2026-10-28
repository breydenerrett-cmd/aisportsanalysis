"""The chat's two tables, in the existing app database (``users_store.db_path()``, created with ``IF NOT EXISTS`` like ``user_store``).

hound_chat_messages   what is SAID, for display and for the next turn's context. One row per line, ``role`` member | hound | notice,
                      keyed by the member and the hound's LINEAGE (``root_id``), never by a version's id: a hound that is applied a new
                      version keeps its conversation. A hound line may carry a ``proposal_json`` (the diff card and its state).
                      "Clear chat" DELETES these rows and nothing else, so it is the member's own to wipe.
hound_chat_usage      what a turn COST and that it happened: one row per member message that reached a model (pending while it runs,
                      then ok or failed), with its day, month, tokens and cost and NO text. The daily message cap, the month's
                      spend and the global call ceiling are all read from here, so clearing the chat can never reset a limit and a
                      failed turn (the member got nothing) is not counted against them.

THE CAP IS TAKEN INSIDE A TRANSACTION. ``begin_turn`` counts today's rows and inserts the pending one under ``BEGIN IMMEDIATE``, so two
taps at once cannot both take the last message.

A day and a month are UTC, the same as every other cap in the app (``rebuild_budget``, the router's usage store).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, List, Mapping, Optional

from src.appstate import users as users_store

ROLE_MEMBER = "member"
ROLE_HOUND = "hound"
ROLE_NOTICE = "notice"                 # a line the PAGE wrote ("Applied. I'm version 3 now."), shown but never sent to the model
ROLES = (ROLE_MEMBER, ROLE_HOUND, ROLE_NOTICE)

STATE_PENDING, STATE_OK, STATE_FAILED = "pending", "ok", "failed"

KEEP_PER_LINEAGE = 400                 # older lines are dropped past this, so a chatty member cannot grow the database without end


class CapReached(Exception):
    """``begin_turn`` refused: the member has used their day. ``used`` and ``limit`` are for the sentence."""

    def __init__(self, used: int, limit: int):
        self.used, self.limit = used, limit
        super().__init__(f"{used} of {limit}")


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hound_chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            root_id TEXT NOT NULL,
            hound_id TEXT NOT NULL,
            version_no INTEGER NOT NULL,
            role TEXT NOT NULL,
            text TEXT NOT NULL,
            proposal_json TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS hound_chat_lineage ON hound_chat_messages(user_id, root_id, id)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hound_chat_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            root_id TEXT NOT NULL,
            hound_id TEXT NOT NULL,
            day TEXT NOT NULL,
            month TEXT NOT NULL,
            created_at TEXT NOT NULL,
            state TEXT NOT NULL,
            model_calls INTEGER NOT NULL DEFAULT 0,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd REAL NOT NULL DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS hound_chat_usage_user_day ON hound_chat_usage(user_id, day)")
    conn.execute("CREATE INDEX IF NOT EXISTS hound_chat_usage_month ON hound_chat_usage(month)")


@contextmanager
def _connect(db: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    with users_store._connect(db) as conn:          # noqa: SLF001 -- the one connection helper every app table uses
        _ensure_schema(conn)
        yield conn


def ensure(db: Optional[Path] = None) -> None:
    """Create the tables if they are not there (idempotent). Every other function does this itself; this is for a boot hook and a test."""
    with _connect(db):
        pass


# ---------------------------------------------------------------------------
# messages
# ---------------------------------------------------------------------------

def _message(row: sqlite3.Row) -> dict:
    proposal = None
    if row["proposal_json"]:
        try:
            proposal = json.loads(row["proposal_json"])
        except ValueError:
            proposal = None
    return {"id": row["id"], "role": row["role"], "text": row["text"], "hound_id": row["hound_id"], "version_no": row["version_no"],
            "created_at": row["created_at"], "proposal": proposal}


def add_message(user_id: int, root_id: str, hound_id: str, version_no: int, role: str, text: str, *,
                proposal: Optional[Mapping] = None, now: Optional[datetime] = None, db: Optional[Path] = None) -> dict:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    with _connect(db) as conn:
        cur = conn.execute(
            "INSERT INTO hound_chat_messages (user_id, root_id, hound_id, version_no, role, text, proposal_json, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (user_id, root_id, hound_id, int(version_no), role, text,
             json.dumps(proposal, sort_keys=True) if proposal is not None else None, _iso(_now(now))))
        new_id = cur.lastrowid
        conn.execute(
            "DELETE FROM hound_chat_messages WHERE user_id = ? AND root_id = ? AND id NOT IN "
            "(SELECT id FROM hound_chat_messages WHERE user_id = ? AND root_id = ? ORDER BY id DESC LIMIT ?)",
            (user_id, root_id, user_id, root_id, KEEP_PER_LINEAGE))
        row = conn.execute("SELECT * FROM hound_chat_messages WHERE id = ?", (new_id,)).fetchone()
    return _message(row)


def history(user_id: int, root_id: str, *, limit: int = 200, db: Optional[Path] = None) -> List[dict]:
    """The newest ``limit`` lines of the conversation, oldest first."""
    with _connect(db) as conn:
        rows = conn.execute("SELECT * FROM hound_chat_messages WHERE user_id = ? AND root_id = ? ORDER BY id DESC LIMIT ?",
                            (user_id, root_id, int(limit))).fetchall()
    return [_message(r) for r in reversed(rows)]


def get_message(message_id: int, user_id: int, root_id: str, *, db: Optional[Path] = None) -> Optional[dict]:
    with _connect(db) as conn:
        row = conn.execute("SELECT * FROM hound_chat_messages WHERE id = ? AND user_id = ? AND root_id = ?",
                           (int(message_id), user_id, root_id)).fetchone()
    return _message(row) if row else None


def set_proposal(message_id: int, proposal: Mapping, *, db: Optional[Path] = None) -> None:
    with _connect(db) as conn:
        conn.execute("UPDATE hound_chat_messages SET proposal_json = ? WHERE id = ?",
                     (json.dumps(proposal, sort_keys=True), int(message_id)))


def claim_proposal(message_id: int, user_id: int, root_id: str, status: str, *, expect: str = "pending",
                   db: Optional[Path] = None) -> Optional[dict]:
    """Move a proposal from ``expect`` to ``status`` in one statement and return it, or None when it was not in ``expect`` (already
    applied, cancelled or replaced). Two taps on Apply cannot both win: only the first finds it pending."""
    with _connect(db) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM hound_chat_messages WHERE id = ? AND user_id = ? AND root_id = ?",
                           (int(message_id), user_id, root_id)).fetchone()
        if row is None or not row["proposal_json"]:
            return None
        proposal = json.loads(row["proposal_json"])
        if proposal.get("status") != expect:
            return None
        proposal["status"] = status
        conn.execute("UPDATE hound_chat_messages SET proposal_json = ? WHERE id = ?", (json.dumps(proposal, sort_keys=True), row["id"]))
        out = _message(row)
        out["proposal"] = proposal
    return out


def replace_pending(user_id: int, root_id: str, *, db: Optional[Path] = None) -> int:
    """A new proposal replaces any still waiting on a tap: only one card can be live at a time. Returns how many were replaced."""
    changed = 0
    with _connect(db) as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute("SELECT id, proposal_json FROM hound_chat_messages WHERE user_id = ? AND root_id = ? AND proposal_json IS NOT NULL",
                            (user_id, root_id)).fetchall()
        for row in rows:
            proposal = json.loads(row["proposal_json"])
            if proposal.get("status") == "pending":
                proposal["status"] = "replaced"
                conn.execute("UPDATE hound_chat_messages SET proposal_json = ? WHERE id = ?", (json.dumps(proposal, sort_keys=True), row["id"]))
                changed += 1
    return changed


def clear(user_id: int, root_id: str, *, db: Optional[Path] = None) -> int:
    """Delete this member's conversation with this lineage. The usage rows stay: a limit is not a thing a member can wipe."""
    with _connect(db) as conn:
        cur = conn.execute("DELETE FROM hound_chat_messages WHERE user_id = ? AND root_id = ?", (user_id, root_id))
    return cur.rowcount


# ---------------------------------------------------------------------------
# usage
# ---------------------------------------------------------------------------

def _day(now: datetime) -> str:
    return now.astimezone(timezone.utc).date().isoformat()


def used_today(user_id: int, *, now: Optional[datetime] = None, db: Optional[Path] = None) -> int:
    """Messages this member has sent today that reached a model (a failed turn, where they got nothing, does not count)."""
    with _connect(db) as conn:
        return conn.execute("SELECT COUNT(*) FROM hound_chat_usage WHERE user_id = ? AND day = ? AND state != ?",
                            (user_id, _day(_now(now)), STATE_FAILED)).fetchone()[0]


def calls_today_all(*, now: Optional[datetime] = None, db: Optional[Path] = None) -> int:
    """Model calls every member's chat has FINISHED today (the global ceiling that keeps chat from using up the router's daily calls).
    A turn still running is not in it, so a turn never counts against itself."""
    with _connect(db) as conn:
        return int(conn.execute("SELECT COALESCE(SUM(model_calls), 0) FROM hound_chat_usage WHERE day = ?", (_day(_now(now)),)).fetchone()[0])


def month_spend(*, now: Optional[datetime] = None, db: Optional[Path] = None) -> float:
    month = _day(_now(now))[:7]
    with _connect(db) as conn:
        return round(float(conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM hound_chat_usage WHERE month = ?", (month,)).fetchone()[0]), 8)


def begin_turn(user_id: int, root_id: str, hound_id: str, limit: int, *, now: Optional[datetime] = None, db: Optional[Path] = None) -> int:
    """Take one of the member's messages for today and return the usage row's id, or raise ``CapReached``."""
    moment = _now(now)
    day = _day(moment)
    with _connect(db) as conn:
        conn.execute("BEGIN IMMEDIATE")
        used = conn.execute("SELECT COUNT(*) FROM hound_chat_usage WHERE user_id = ? AND day = ? AND state != ?",
                            (user_id, day, STATE_FAILED)).fetchone()[0]
        if used >= limit:
            raise CapReached(used, limit)
        cur = conn.execute(
            "INSERT INTO hound_chat_usage (user_id, root_id, hound_id, day, month, created_at, state) VALUES (?,?,?,?,?,?,?)",
            (user_id, root_id, hound_id, day, day[:7], _iso(moment), STATE_PENDING))
        return cur.lastrowid


def finish_turn(usage_id: int, state: str, *, calls: int = 0, input_tokens: int = 0, output_tokens: int = 0, cost_usd: float = 0.0,
                db: Optional[Path] = None) -> None:
    with _connect(db) as conn:
        conn.execute("UPDATE hound_chat_usage SET state = ?, model_calls = ?, input_tokens = ?, output_tokens = ?, cost_usd = ? WHERE id = ?",
                     (state, int(calls), int(input_tokens), int(output_tokens), round(float(cost_usd), 8), int(usage_id)))
