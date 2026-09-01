"""Support-message store, stdlib sqlite3, shared app.db.

WHY A MESSAGE HAS A NULLABLE user_id AND A NULLABLE email
-----------------------------------------------------------
The private alpha's support surface has to work for two different
callers: an authenticated user (POST /support with a bearer token -- see
api/support.py) and someone who has not redeemed an invite yet but still
hit a wall (a broken invite link, a billing question before they ever got
a token). The first has a `user_id` and no need to also type an email --
Brey can already look them up. The second has no `user_id` at all -- an
email is the only way to reply. Exactly one of the two is required by
`create_message`; storing both as nullable columns (rather than two
separate tables) keeps GET /admin/support one query instead of a union.

WHY STATUS IS open | answered | closed, NOT A FREE-TEXT FIELD
-----------------------------------------------------------------
Same reasoning src/appstate/users.py gives for VALID_STATUSES and
src/appstate/events.py gives for EVENT_KINDS: a typo'd status would
silently fragment "how many open tickets do I have" into two buckets that
never sum right. Three states are what a one-person support desk actually
uses (docs/ONBOARDING_SUPPORT_PLAYBOOK.md): open (unread/untouched),
answered (Brey replied, waiting to see if it sticks), closed (done).
There is no "in_progress" -- for a single operator that distinction never
outlives the one sitting between reading a message and typing a reply.

WHY A PER-USER OPEN-MESSAGE CAP, NOT A RATE LIMIT HERE
-----------------------------------------------------------
api/support.py already rate-limits the POST route (requests per hour, via
src.appstate.ratelimit) -- that guards against a script hammering the
endpoint. This module's own cap guards a different failure: a real,
slow human who is stuck and re-submits the same complaint five times over
a week, each one a fresh open row Brey has to triage separately. Ten open
messages is generous for one honestly-confused user and small enough that
a genuinely abusive submitter (scripted or not) cannot flood the admin
queue with permanently-open rows -- capping OPEN messages, not total
messages ever, so a user who gets their answers and moves on is never
penalized for their own history.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List, Optional

from src import paths

ENV_DB_PATH = "APP_DB_PATH"  # shared with users/events/savedbets -- one app db

MAX_SUBJECT_LENGTH = 200
MAX_BODY_LENGTH = 5000

VALID_STATUSES = ("open", "answered", "closed")

# See module docstring's "PER-USER OPEN-MESSAGE CAP" section for why this
# number and why it counts only open messages, not lifetime messages.
MAX_OPEN_MESSAGES_PER_USER = 10


class TooManyOpenMessagesError(ValueError):
    """Raised by create_message when a user already has
    MAX_OPEN_MESSAGES_PER_USER open messages. A ValueError subclass (not a
    bare ValueError) so api/support.py can tell this apart from an
    ordinary validation failure and answer it with a distinct message/
    status if it ever wants to, without string-matching an exception's
    text."""


def db_path() -> Path:
    override = (os.environ.get(ENV_DB_PATH) or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return paths.repo_root() / "data" / "app" / "app.db"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connect(path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    resolved = path or db_path()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(resolved))
    conn.row_factory = sqlite3.Row
    try:
        _ensure_schema(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS support_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            email TEXT,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL,
            answered_at TEXT
        )
    """)


@dataclass(frozen=True)
class SupportMessage:
    id: int
    user_id: Optional[int]
    email: Optional[str]
    subject: str
    body: str
    created_at: str
    status: str
    answered_at: Optional[str]


def _row_to_message(row: sqlite3.Row) -> SupportMessage:
    return SupportMessage(
        id=row["id"], user_id=row["user_id"], email=row["email"],
        subject=row["subject"], body=row["body"], created_at=row["created_at"],
        status=row["status"], answered_at=row["answered_at"])


def _count_open_for_user(conn: sqlite3.Connection, user_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM support_messages "
        "WHERE user_id = ? AND status = 'open'", (user_id,)).fetchone()
    return row["n"]


def create_message(*, user_id: Optional[int] = None, email: Optional[str] = None,
                    subject: str, body: str,
                    db: Optional[Path] = None) -> SupportMessage:
    """Create one support message, open by default.

    Exactly one of `user_id` / `email` identifies the sender -- see module
    docstring. Raises ValueError on: neither given, both given, an
    over-length subject/body, or an empty subject/body. Raises
    TooManyOpenMessagesError if the identified user already has
    MAX_OPEN_MESSAGES_PER_USER open messages (checked only for `user_id`
    senders -- an anonymous `email` sender has no stable identity to key
    the cap on, so v1 accepts every anonymous submission and leans on the
    hourly rate limit in api/support.py instead; see that module's
    docstring for the trade-off).
    """
    if (user_id is None) == (email is None):
        raise ValueError(
            "create_message requires exactly one of user_id or email, "
            f"got user_id={user_id!r} email={email!r}")
    subject = (subject or "").strip()
    body = (body or "").strip()
    if not subject:
        raise ValueError("subject must not be empty")
    if not body:
        raise ValueError("body must not be empty")
    if len(subject) > MAX_SUBJECT_LENGTH:
        raise ValueError(
            f"subject exceeds {MAX_SUBJECT_LENGTH} characters "
            f"({len(subject)})")
    if len(body) > MAX_BODY_LENGTH:
        raise ValueError(
            f"body exceeds {MAX_BODY_LENGTH} characters ({len(body)})")
    if email is not None:
        email = email.strip().lower()
        if not email or "@" not in email:
            raise ValueError(f"not a usable email: {email!r}")
    created_at = _now_iso()
    with _connect(db) as conn:
        if user_id is not None:
            open_count = _count_open_for_user(conn, user_id)
            if open_count >= MAX_OPEN_MESSAGES_PER_USER:
                raise TooManyOpenMessagesError(
                    f"user {user_id} already has {open_count} open support "
                    f"messages (cap is {MAX_OPEN_MESSAGES_PER_USER})")
        cur = conn.execute(
            "INSERT INTO support_messages "
            "(user_id, email, subject, body, created_at, status, answered_at) "
            "VALUES (?, ?, ?, ?, ?, 'open', NULL)",
            (user_id, email, subject, body, created_at))
        return SupportMessage(
            id=cur.lastrowid, user_id=user_id, email=email, subject=subject,
            body=body, created_at=created_at, status="open", answered_at=None)


def get_message(message_id: int, *, db: Optional[Path] = None) -> Optional[SupportMessage]:
    with _connect(db) as conn:
        row = conn.execute(
            "SELECT * FROM support_messages WHERE id = ?", (message_id,)).fetchone()
        return _row_to_message(row) if row else None


def list_messages(*, status: Optional[str] = None, user_id: Optional[int] = None,
                   db: Optional[Path] = None) -> List[SupportMessage]:
    """Every message matching the given filters, newest first -- the shape
    an admin triage view wants (most recent complaint on top), the
    opposite ordering of src.appstate.events.list_events, which is
    oldest-first for a chronological audit trail. Both orderings are
    intentional per their own caller; support triage cares about "what's
    new", not "what happened in what order".

    `status`, when given, must be one of VALID_STATUSES -- a typo'd filter
    fails loud (ValueError) rather than silently returning zero rows and
    looking like an empty queue.
    """
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"unknown status: {status!r}")
    clauses = []
    params: list = []
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if user_id is not None:
        clauses.append("user_id = ?")
        params.append(user_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect(db) as conn:
        rows = conn.execute(
            f"SELECT * FROM support_messages {where} ORDER BY created_at DESC",
            params).fetchall()
        return [_row_to_message(r) for r in rows]


def update_status(message_id: int, status: str, *,
                   db: Optional[Path] = None) -> Optional[SupportMessage]:
    """Set a message's status. Returns the updated message, or None if
    `message_id` doesn't exist -- a caller (the admin route) turns that
    into its own 404 rather than this module raising one, the same split
    src.appstate.savedbets.delete_bet uses (a bool/None return, HTTP shape
    decided by the caller).

    Sets `answered_at` the first time a message transitions to
    'answered' (write-once, like users.mark_token_first_used) and leaves
    it alone on every later status change -- a message that goes
    answered -> closed -> reopened-by-a-follow-up keeps the timestamp of
    when Brey FIRST answered it, not the most recent status write.
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"unknown status: {status!r}")
    with _connect(db) as conn:
        existing = conn.execute(
            "SELECT * FROM support_messages WHERE id = ?", (message_id,)).fetchone()
        if existing is None:
            return None
        if status == "answered" and existing["answered_at"] is None:
            conn.execute(
                "UPDATE support_messages SET status = ?, answered_at = ? "
                "WHERE id = ?", (status, _now_iso(), message_id))
        else:
            conn.execute(
                "UPDATE support_messages SET status = ? WHERE id = ?",
                (status, message_id))
        row = conn.execute(
            "SELECT * FROM support_messages WHERE id = ?", (message_id,)).fetchone()
        return _row_to_message(row)
