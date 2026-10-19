"""The two small tables this package adds to the app database: dog looks and dog feedback.

SAME FILE, SAME PATTERN as src/hounds/user_store.py and fan_tips.py: ``users.db_path()`` (APP_DB_PATH
overrides it), ``CREATE TABLE IF NOT EXISTS``, additive only, a connection per call.

hound_looks     one row per LINEAGE (``root_id``), so a dog keeps its look when the referee or the owner makes
                a new version of it. The look is the validated JSON of ``look.validate_look``.
hound_feedback  one row per (user, dog, target): the "Good call / Bad call" a signed-in user gave a ticket, an
                answer or the dog itself, an optional note, and, for a suggestion, the change proposed.
                A second vote on the same target REPLACES the first (a person changes their mind; they do not
                vote twice). A suggestion is its own row each time (its target is a hash of the change).

NOTHING HERE CHANGES A DOG. Feedback and suggestions are rows in a table: they never reach a spec, a
challenger or a bet. Only the owner (through the builder) or the referee changes a dog.

Privacy: a user's id is stored for the one-vote rule and for the owner's own list; it is never in a public
payload. Notes go through the same text filter a dog's name does, and the public sees counts only.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Mapping, Optional

from src.appstate import users as users_store
from src.hounds import user_spec

VERDICT_GOOD = "good"
VERDICT_BAD = "bad"
VERDICT_SUGGEST = "suggest"
VERDICTS = (VERDICT_GOOD, VERDICT_BAD)

KIND_TICKET = "ticket"
KIND_MANUAL = "manual"
KIND_ANSWER = "answer"
KIND_DOG = "dog"
KIND_SUGGESTION = "suggestion"
TARGET_KINDS = (KIND_TICKET, KIND_MANUAL, KIND_ANSWER, KIND_DOG)

NOTE_MAX = 200
TARGET_MAX = 120
SUGGESTIONS_PER_DAY = 10          # per person per dog
FEEDBACK_PER_HOUR = 60            # per person, across every dog


class FeedbackError(ValueError):
    """A refusal the caller can show; ``code`` is stable and ``status`` is the HTTP status."""

    def __init__(self, code: str, message: str, status: int = 400):
        self.code = code
        self.status = status
        super().__init__(message)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hound_looks (
            root_id TEXT PRIMARY KEY,
            look_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hound_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hound_id TEXT NOT NULL,
            root_id TEXT NOT NULL,
            target_kind TEXT NOT NULL,
            target_id TEXT NOT NULL,
            verdict TEXT NOT NULL,
            note TEXT,
            change_json TEXT,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (user_id, hound_id, target_kind, target_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS hound_feedback_root ON hound_feedback(root_id, target_kind)")


@contextmanager
def connect(db: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    with users_store._connect(db) as conn:
        _ensure_schema(conn)
        yield conn


# ---------------------------------------------------------------------------
# looks
# ---------------------------------------------------------------------------

def get_look(root_id: str, *, db: Optional[Path] = None) -> Optional[dict]:
    with connect(db) as conn:
        row = conn.execute("SELECT look_json FROM hound_looks WHERE root_id = ?", (root_id,)).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["look_json"])
    except ValueError:
        return None


def get_looks(root_ids, *, db: Optional[Path] = None) -> dict:
    ids = [r for r in root_ids if r]
    if not ids:
        return {}
    with connect(db) as conn:
        marks = ",".join("?" for _ in ids)
        rows = conn.execute(f"SELECT root_id, look_json FROM hound_looks WHERE root_id IN ({marks})",
                            ids).fetchall()
    out = {}
    for row in rows:
        try:
            out[row["root_id"]] = json.loads(row["look_json"])
        except ValueError:
            continue
    return out


def set_look(root_id: str, look: Mapping, user_id: int, *, now: Optional[datetime] = None,
             db: Optional[Path] = None) -> dict:
    """Store an ALREADY VALIDATED look (``look.validate_look``)."""
    stamp = _iso(now or datetime.now(timezone.utc))
    with connect(db) as conn:
        conn.execute(
            "INSERT INTO hound_looks (root_id, look_json, updated_at, updated_by) VALUES (?,?,?,?) "
            "ON CONFLICT(root_id) DO UPDATE SET look_json = excluded.look_json, "
            "updated_at = excluded.updated_at, updated_by = excluded.updated_by",
            (root_id, json.dumps(dict(look), sort_keys=True), stamp, user_id))
        conn.commit()
    return dict(look)


# ---------------------------------------------------------------------------
# feedback
# ---------------------------------------------------------------------------

def clean_note(note) -> Optional[str]:
    """The note as stored (trimmed, one line), None for no note; raises ``FeedbackError`` for a bad one."""
    if note is None:
        return None
    if not isinstance(note, str):
        raise FeedbackError("note_invalid", "the note must be text", 422)
    text = " ".join(note.split())
    if not text:
        return None
    if len(text) > NOTE_MAX:
        raise FeedbackError("note_too_long", f"keep the note under {NOTE_MAX} characters", 422)
    problem = user_spec.text_problem(text)
    if problem:
        raise FeedbackError("note_not_allowed", f"the note {problem}", 422)
    return text


def clean_target(kind: str, target_id) -> str:
    if kind not in TARGET_KINDS:
        raise FeedbackError("target_invalid", "feedback goes on a ticket, a manual pick, an answer or the dog", 422)
    if kind == KIND_DOG:
        return ""
    text = " ".join(str(target_id or "").split())
    if not text or len(text) > TARGET_MAX:
        raise FeedbackError("target_invalid", "say which ticket or answer this is about", 422)
    return text


def record_vote(*, hound_id: str, root_id: str, kind: str, target_id: str, verdict: str, note: Optional[str],
                user_id: int, now: Optional[datetime] = None, db: Optional[Path] = None) -> dict:
    """One person's Good call / Bad call on one target. A repeat on the same target replaces the earlier
    vote. Rate limited per person per hour from the rows themselves."""
    if verdict not in VERDICTS:
        raise FeedbackError("verdict_invalid", "the verdict is good or bad", 422)
    moment = now or datetime.now(timezone.utc)
    with connect(db) as conn:
        recent = conn.execute("SELECT COUNT(*) FROM hound_feedback WHERE user_id = ? AND created_at >= ?",
                              (user_id, _iso(moment - timedelta(hours=1)))).fetchone()[0]
        if recent >= FEEDBACK_PER_HOUR:
            raise FeedbackError("rate_limited", "that is a lot of feedback in an hour; try again later", 429)
        conn.execute(
            "INSERT INTO hound_feedback (hound_id, root_id, target_kind, target_id, verdict, note, change_json, "
            "user_id, created_at) VALUES (?,?,?,?,?,?,NULL,?,?) "
            "ON CONFLICT(user_id, hound_id, target_kind, target_id) DO UPDATE SET verdict = excluded.verdict, "
            "note = excluded.note, created_at = excluded.created_at",
            (hound_id, root_id, kind, target_id, verdict, note, user_id, _iso(moment)))
        conn.commit()
    return {"hound_id": hound_id, "target_kind": kind, "target_id": target_id, "verdict": verdict,
            "note": note}


def record_suggestion(*, hound_id: str, root_id: str, change: Mapping, note: Optional[str], user_id: int,
                      now: Optional[datetime] = None, db: Optional[Path] = None) -> dict:
    """A suggested change to a user dog's rule, kept for the owner to read. It changes nothing by itself."""
    moment = now or datetime.now(timezone.utc)
    blob = json.dumps(dict(change), sort_keys=True)
    target = hashlib.sha256((blob + "|" + (note or "")).encode("utf-8")).hexdigest()[:16]
    with connect(db) as conn:
        today = conn.execute(
            "SELECT COUNT(*) FROM hound_feedback WHERE user_id = ? AND hound_id = ? AND target_kind = ? "
            "AND created_at >= ?", (user_id, hound_id, KIND_SUGGESTION, _iso(moment - timedelta(days=1)))
        ).fetchone()[0]
        if today >= SUGGESTIONS_PER_DAY:
            raise FeedbackError("rate_limited", "that is enough suggestions for one dog today", 429)
        conn.execute(
            "INSERT INTO hound_feedback (hound_id, root_id, target_kind, target_id, verdict, note, change_json, "
            "user_id, created_at) VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(user_id, hound_id, target_kind, target_id) DO UPDATE SET created_at = excluded.created_at",
            (hound_id, root_id, KIND_SUGGESTION, target, VERDICT_SUGGEST, note, blob, user_id, _iso(moment)))
        conn.commit()
    return {"hound_id": hound_id, "target_id": target, "change": dict(change), "note": note}


def counts(root_id: str, *, db: Optional[Path] = None) -> dict:
    """What fans think, as counts only: ``{good, bad, by_kind, by_target, suggestions}``. ``by_target`` is
    {"ticket:<key>": {good, bad}} for the rows the dog page paints under each ticket."""
    out = {"good": 0, "bad": 0, "notes": 0, "by_kind": {}, "by_target": {}, "suggestions": 0}
    with connect(db) as conn:
        rows = conn.execute(
            "SELECT target_kind, target_id, verdict, COUNT(*) AS n, SUM(CASE WHEN note IS NOT NULL THEN 1 ELSE 0 END) "
            "AS notes FROM hound_feedback WHERE root_id = ? GROUP BY target_kind, target_id, verdict",
            (root_id,)).fetchall()
    for r in rows:
        kind, verdict, n = r["target_kind"], r["verdict"], r["n"]
        if kind == KIND_SUGGESTION:
            out["suggestions"] += n
            continue
        if verdict not in VERDICTS:
            continue
        out[verdict] += n
        out["notes"] += r["notes"] or 0
        bucket = out["by_kind"].setdefault(kind, {"good": 0, "bad": 0})
        bucket[verdict] += n
        if kind != KIND_DOG:
            cell = out["by_target"].setdefault(f"{kind}:{r['target_id']}", {"good": 0, "bad": 0})
            cell[verdict] += n
    return out


def my_votes(root_id: str, user_id: int, *, db: Optional[Path] = None) -> dict:
    """{"ticket:<key>": "good"|"bad"} for this person on this lineage, so the buttons show what they chose."""
    with connect(db) as conn:
        rows = conn.execute(
            "SELECT target_kind, target_id, verdict FROM hound_feedback WHERE root_id = ? AND user_id = ? "
            "AND target_kind != ?", (root_id, user_id, KIND_SUGGESTION)).fetchall()
    return {f"{r['target_kind']}:{r['target_id']}": r["verdict"] for r in rows}


def notes_for_owner(root_id: str, *, limit: int = 20, db: Optional[Path] = None) -> list:
    """Notes people left, newest first, WITHOUT who left them (the owner reads the words, not the people)."""
    with connect(db) as conn:
        rows = conn.execute(
            "SELECT target_kind, target_id, verdict, note, created_at FROM hound_feedback WHERE root_id = ? "
            "AND note IS NOT NULL AND target_kind != ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (root_id, KIND_SUGGESTION, limit)).fetchall()
    return [{"target_kind": r["target_kind"], "target_id": r["target_id"], "verdict": r["verdict"],
             "note": r["note"], "created_at": r["created_at"]} for r in rows]


def suggestions_for_owner(root_id: str, *, limit: int = 20, db: Optional[Path] = None) -> list:
    with connect(db) as conn:
        rows = conn.execute(
            "SELECT id, hound_id, note, change_json, created_at FROM hound_feedback WHERE root_id = ? "
            "AND target_kind = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (root_id, KIND_SUGGESTION, limit)).fetchall()
    out = []
    for r in rows:
        try:
            change = json.loads(r["change_json"]) if r["change_json"] else {}
        except ValueError:
            change = {}
        out.append({"id": r["id"], "hound_id": r["hound_id"], "note": r["note"], "change": change,
                    "created_at": r["created_at"]})
    return out
