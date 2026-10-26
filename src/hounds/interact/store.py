"""The two small tables this package adds to the app database: dog looks and dog feedback.

SAME FILE, SAME PATTERN as src/hounds/user_store.py and the fan-tip box's module: ``users.db_path()`` (APP_DB_PATH
overrides it), ``CREATE TABLE IF NOT EXISTS``, additive only, a connection per call.

hound_looks     one row per LINEAGE (``root_id``), so a dog keeps its look when the referee or the owner makes
                a new version of it. The look is the validated JSON of ``look.validate_look``.
hound_feedback  APPEND-ONLY (owner request 2026-10-25): every "Good call / Bad call" a signed-in user gave a ticket, an
                answer or the hound itself is its own row, with an optional note, the "what was wrong" chips of a Bad
                call (``chips_json``) and, for a suggestion, the change proposed. A vote is NEVER edited: a trigger
                refuses every UPDATE, and a change of mind (or a Bad call that then gets its chips) APPENDS a row.
                What a person currently thinks is the LATEST row per (user, hound, target): the view
                ``hound_feedback_current``, which every reader below uses, so a person still counts once per target.
                A suggestion is its own row each time (its target is a hash of the change); a repeat is a no-op.
hound_feedback_issues / hound_feedback_issue_votes / hound_feedback_resolutions
                the flagged-issue loop: the digest CLI registers an issue (an id like ``FB-3FA9C2``) and which votes
                back it; ``feedback-resolve`` appends a resolution row (also append-only); the members whose votes
                backed the issue read "Fixed: <note>" on their next visit (``fixed_notices``).

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

#: The "what was wrong" chips a Bad call can carry, in the order the page lists them: {id: label}. Ids are stored; the page
#: (web/js/dog-feedback.js CHIPS) and a test keep the same list. Only a Bad call may carry chips.
CHIPS = {
    "wrong_pick": "Wrong pick",
    "bad_price": "Bad price",
    "ignored_news": "Ignored injury/news",
    "wrong_market": "Wrong sport/market",
    "too_risky": "Too risky",
    "confusing": "Confusing answer",
    "other": "Other",
}
CHIP_PHRASES = {k: v.lower() for k, v in CHIPS.items()}   # "2 bad price" reads better lower-cased inside a sentence

RESOLUTION_MAX = 240
NOTICE_DAYS = 30                  # how long a member keeps seeing "Fixed: ..." for a vote of theirs
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


_FEEDBACK_COLUMNS = ("hound_id, root_id, target_kind, target_id, verdict, note, change_json, user_id, created_at")


def _create_feedback_table(conn: sqlite3.Connection, name: str = "hound_feedback") -> None:
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {name} (
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
            chips_json TEXT
        )
    """)


def _migrate_feedback(conn: sqlite3.Connection) -> None:
    """The first version of this table had ``UNIQUE (user_id, hound_id, target_kind, target_id)`` and replaced a vote in
    place. SQLite cannot drop a table constraint, so a table that still has it is rebuilt without it, rows and ids kept
    (the ids are what the issue table points at). Idempotent: a table with no such constraint is left alone."""
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'hound_feedback'").fetchone()
    if row is None:
        return
    sql = row["sql"] or ""
    if "UNIQUE" not in sql.upper():
        if "chips_json" not in sql:
            conn.execute("ALTER TABLE hound_feedback ADD COLUMN chips_json TEXT")
        return
    conn.execute("BEGIN IMMEDIATE")           # one writer rebuilds it; the rename and the copy land together or not at all
    try:
        row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'hound_feedback'").fetchone()
        if row is not None and "UNIQUE" in (row["sql"] or "").upper():      # another process may have just done it
            conn.execute("DROP TRIGGER IF EXISTS hound_feedback_no_update")
            conn.execute("DROP INDEX IF EXISTS hound_feedback_root")
            conn.execute("DROP VIEW IF EXISTS hound_feedback_current")
            conn.execute("ALTER TABLE hound_feedback RENAME TO hound_feedback_v1")
            _create_feedback_table(conn)
            conn.execute(f"INSERT INTO hound_feedback (id, {_FEEDBACK_COLUMNS}) "
                         f"SELECT id, {_FEEDBACK_COLUMNS} FROM hound_feedback_v1")
            conn.execute("DROP TABLE hound_feedback_v1")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hound_looks (
            root_id TEXT PRIMARY KEY,
            look_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by INTEGER
        )
    """)
    _create_feedback_table(conn)
    _migrate_feedback(conn)
    conn.execute("CREATE INDEX IF NOT EXISTS hound_feedback_root ON hound_feedback(root_id, target_kind)")
    conn.execute("CREATE INDEX IF NOT EXISTS hound_feedback_key ON hound_feedback(user_id, hound_id, target_kind, target_id)")
    # a vote is never edited: the database says so, not just this module
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS hound_feedback_no_update BEFORE UPDATE ON hound_feedback
        BEGIN SELECT RAISE(ABORT, 'votes are append-only: a change of mind appends a new row'); END
    """)
    conn.execute("""
        CREATE VIEW IF NOT EXISTS hound_feedback_current AS
        SELECT * FROM hound_feedback WHERE id IN
            (SELECT MAX(id) FROM hound_feedback GROUP BY user_id, hound_id, target_kind, target_id)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hound_feedback_issues (
            feedback_id TEXT PRIMARY KEY,
            root_id TEXT NOT NULL,
            hound_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            chip TEXT,
            summary TEXT NOT NULL,
            window_date TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hound_feedback_issue_votes (
            feedback_id TEXT NOT NULL,
            vote_id INTEGER NOT NULL,
            PRIMARY KEY (feedback_id, vote_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hound_feedback_resolutions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feedback_id TEXT NOT NULL,
            note TEXT NOT NULL,
            resolved_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS hound_feedback_resolutions_no_update BEFORE UPDATE ON hound_feedback_resolutions
        BEGIN SELECT RAISE(ABORT, 'resolutions are append-only'); END
    """)


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


def clean_chips(chips, verdict: str) -> list:
    """The "what was wrong" chip ids as stored: known ids only, once each, in the page's order. Empty for none. Only a Bad call
    carries chips (a Good call with chips is a refusal, not a silent drop, so a page bug cannot hide)."""
    if chips is None or chips == []:
        return []
    if not isinstance(chips, (list, tuple)) or any(not isinstance(c, str) for c in chips):
        raise FeedbackError("chips_invalid", "chips are a list of the choices the page offers", 422)
    if verdict != VERDICT_BAD:
        raise FeedbackError("chips_invalid", "only a Bad call says what was wrong", 422)
    unknown = [c for c in chips if c not in CHIPS]
    if unknown:
        raise FeedbackError("chips_invalid", "that is not one of the choices the page offers", 422)
    return [c for c in CHIPS if c in chips]


def _chips_of(raw) -> list:
    try:
        loaded = json.loads(raw) if raw else []
    except ValueError:
        return []
    return [c for c in CHIPS if isinstance(loaded, list) and c in loaded]


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
                user_id: int, chips=None, now: Optional[datetime] = None, db: Optional[Path] = None) -> dict:
    """One person's Good call / Bad call on one target, APPENDED as a new row. A repeat on the same target does not edit the
    earlier row (the database refuses an UPDATE); the latest row is what the person thinks now (``hound_feedback_current``).
    A Bad call may carry ``chips`` (what was wrong). Rate limited per person per hour from the rows themselves."""
    if verdict not in VERDICTS:
        raise FeedbackError("verdict_invalid", "the verdict is good or bad", 422)
    picked = clean_chips(chips, verdict)
    moment = now or datetime.now(timezone.utc)
    with connect(db) as conn:
        recent = conn.execute("SELECT COUNT(*) FROM hound_feedback WHERE user_id = ? AND created_at >= ?",
                              (user_id, _iso(moment - timedelta(hours=1)))).fetchone()[0]
        if recent >= FEEDBACK_PER_HOUR:
            raise FeedbackError("rate_limited", "that is a lot of feedback in an hour; try again later", 429)
        cur = conn.execute(
            "INSERT INTO hound_feedback (hound_id, root_id, target_kind, target_id, verdict, note, change_json, "
            "user_id, created_at, chips_json) VALUES (?,?,?,?,?,?,NULL,?,?,?)",
            (hound_id, root_id, kind, target_id, verdict, note, user_id, _iso(moment),
             json.dumps(picked) if picked else None))
        conn.commit()
        vote_id = cur.lastrowid
    return {"id": vote_id, "hound_id": hound_id, "target_kind": kind, "target_id": target_id, "verdict": verdict,
            "note": note, "chips": picked}


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
        seen = conn.execute(
            "SELECT 1 FROM hound_feedback WHERE user_id = ? AND hound_id = ? AND target_kind = ? AND target_id = ?",
            (user_id, hound_id, KIND_SUGGESTION, target)).fetchone()
        if seen is None:                     # the same suggestion twice is one suggestion (the rows are append-only)
            conn.execute(
                "INSERT INTO hound_feedback (hound_id, root_id, target_kind, target_id, verdict, note, change_json, "
                "user_id, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (hound_id, root_id, KIND_SUGGESTION, target, VERDICT_SUGGEST, note, blob, user_id, _iso(moment)))
            conn.commit()
    return {"hound_id": hound_id, "target_id": target, "change": dict(change), "note": note}


def counts(root_id: str, *, db: Optional[Path] = None) -> dict:
    """What fans think, as counts only: ``{good, bad, by_kind, by_target, suggestions}``. ``by_target`` is
    {"ticket:<key>": {good, bad}} for the rows the dog page paints under each ticket."""
    out = {"good": 0, "bad": 0, "notes": 0, "by_kind": {}, "by_target": {}, "suggestions": 0, "chips": {}}
    with connect(db) as conn:
        for r in conn.execute("SELECT chips_json FROM hound_feedback_current WHERE root_id = ? AND verdict = ? "
                              "AND chips_json IS NOT NULL", (root_id, VERDICT_BAD)).fetchall():
            for chip in _chips_of(r["chips_json"]):
                out["chips"][chip] = out["chips"].get(chip, 0) + 1
        rows = conn.execute(
            "SELECT target_kind, target_id, verdict, COUNT(*) AS n, SUM(CASE WHEN note IS NOT NULL THEN 1 ELSE 0 END) "
            "AS notes FROM hound_feedback_current WHERE root_id = ? GROUP BY target_kind, target_id, verdict",
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
            "SELECT target_kind, target_id, verdict FROM hound_feedback_current WHERE root_id = ? AND user_id = ? "
            "AND target_kind != ?", (root_id, user_id, KIND_SUGGESTION)).fetchall()
    return {f"{r['target_kind']}:{r['target_id']}": r["verdict"] for r in rows}


def notes_for_owner(root_id: str, *, limit: int = 20, db: Optional[Path] = None) -> list:
    """Notes people left, newest first, WITHOUT who left them (the owner reads the words, not the people)."""
    with connect(db) as conn:
        rows = conn.execute(
            "SELECT target_kind, target_id, verdict, note, chips_json, created_at FROM hound_feedback_current WHERE root_id = ? "
            "AND note IS NOT NULL AND target_kind != ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (root_id, KIND_SUGGESTION, limit)).fetchall()
    return [{"target_kind": r["target_kind"], "target_id": r["target_id"], "verdict": r["verdict"],
             "note": r["note"], "chips": _chips_of(r["chips_json"]), "created_at": r["created_at"]} for r in rows]


def suggestions_for_owner(root_id: str, *, limit: int = 20, db: Optional[Path] = None) -> list:
    with connect(db) as conn:
        rows = conn.execute(
            "SELECT id, hound_id, note, change_json, created_at FROM hound_feedback_current WHERE root_id = ? "
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


# ---------------------------------------------------------------------------
# the owner's own votes, as training evidence
# ---------------------------------------------------------------------------

def votes_text(good: int, bad: int, chips: Mapping) -> str:
    """"3 Bad calls: 2 bad price, 1 wrong pick" (the proposal card's line; hound words only, no verdict on the rule)."""
    parts = []
    if bad:
        why = ", ".join(f"{n} {CHIP_PHRASES[c]}" for c, n in sorted(chips.items(), key=lambda kv: (-kv[1], list(CHIPS).index(kv[0]))))
        parts.append(f"{bad} Bad {'call' if bad == 1 else 'calls'}" + (f": {why}" if why else ""))
    if good:
        parts.append(f"{good} Good {'call' if good == 1 else 'calls'}")
    return "; ".join(parts)


def owner_evidence(root_id: str, owner_id: int, *, notes: int = 3, db: Optional[Path] = None) -> dict:
    """What the OWNER said about this hound's picks and answers, current votes only (a changed mind counts once), across the
    whole lineage: ``{good, bad, chips: {chip: n}, notes: [..], text}``. The training proposal shows it under its own label.
    It is evidence for the owner to weigh at review time: nothing here reaches a rule, and nothing applies without their yes."""
    out = {"good": 0, "bad": 0, "chips": {}, "notes": [], "text": ""}
    with connect(db) as conn:
        rows = conn.execute(
            "SELECT verdict, note, chips_json FROM hound_feedback_current WHERE root_id = ? AND user_id = ? "
            "AND target_kind != ? ORDER BY created_at DESC, id DESC", (root_id, owner_id, KIND_SUGGESTION)).fetchall()
    for r in rows:
        if r["verdict"] not in VERDICTS:
            continue
        out[r["verdict"]] += 1
        if r["verdict"] == VERDICT_BAD:
            for chip in _chips_of(r["chips_json"]):
                out["chips"][chip] = out["chips"].get(chip, 0) + 1
        if r["note"] and len(out["notes"]) < notes:
            out["notes"].append({"verdict": r["verdict"], "note": r["note"]})
    out["text"] = votes_text(out["good"], out["bad"], out["chips"])
    return out


# ---------------------------------------------------------------------------
# flagged issues and their resolutions
# ---------------------------------------------------------------------------

def register_issue(*, feedback_id: str, root_id: str, hound_id: str, kind: str, chip: Optional[str], summary: str,
                   window_date: str, vote_ids, now: Optional[datetime] = None, db: Optional[Path] = None) -> bool:
    """Record a flagged issue and the votes behind it. True when the issue is NEW. Votes that arrive later for an issue
    that already exists are attached to it (so they too hear when it is fixed); the issue row itself never changes."""
    stamp = _iso(now or datetime.now(timezone.utc))
    with connect(db) as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO hound_feedback_issues (feedback_id, root_id, hound_id, kind, chip, summary, window_date, "
            "created_at) VALUES (?,?,?,?,?,?,?,?)", (feedback_id, root_id, hound_id, kind, chip, summary, window_date, stamp))
        fresh = cur.rowcount == 1
        conn.executemany("INSERT OR IGNORE INTO hound_feedback_issue_votes (feedback_id, vote_id) VALUES (?,?)",
                         [(feedback_id, int(v)) for v in vote_ids])
        conn.commit()
    return fresh


def get_issue(feedback_id: str, *, db: Optional[Path] = None) -> Optional[dict]:
    with connect(db) as conn:
        row = conn.execute("SELECT * FROM hound_feedback_issues WHERE feedback_id = ?", (feedback_id,)).fetchone()
        if row is None:
            return None
        voters = conn.execute(
            "SELECT COUNT(DISTINCT f.user_id) FROM hound_feedback_issue_votes iv JOIN hound_feedback f ON f.id = iv.vote_id "
            "WHERE iv.feedback_id = ?", (feedback_id,)).fetchone()[0]
    out = dict(row)
    out["voters"] = voters
    return out


def clean_resolution(note) -> str:
    text = " ".join(str(note or "").split())
    if not text:
        raise FeedbackError("resolution_empty", "say what was fixed", 422)
    if len(text) > RESOLUTION_MAX:
        raise FeedbackError("resolution_too_long", f"keep it under {RESOLUTION_MAX} characters", 422)
    return text


def resolve_issue(feedback_id: str, note: str, *, now: Optional[datetime] = None, db: Optional[Path] = None) -> dict:
    """Append a resolution row for a known issue. Never edits an earlier one: a second resolution is a second line the
    members see (newest first). Raises ``FeedbackError`` 404 for an id the digest never flagged."""
    text = clean_resolution(note)
    issue = get_issue(feedback_id, db=db)
    if issue is None:
        raise FeedbackError("issue_not_found", f"no flagged issue {feedback_id}", 404)
    stamp = _iso(now or datetime.now(timezone.utc))
    with connect(db) as conn:
        cur = conn.execute("INSERT INTO hound_feedback_resolutions (feedback_id, note, resolved_at) VALUES (?,?,?)",
                           (feedback_id, text, stamp))
        conn.commit()
    return {"id": cur.lastrowid, "feedback_id": feedback_id, "note": text, "resolved_at": stamp,
            "voters": issue["voters"], "hound_id": issue["hound_id"]}


def fixed_notices(root_id: str, user_id: int, *, now: Optional[datetime] = None, limit: int = 5,
                  db: Optional[Path] = None) -> list:
    """The "Fixed: <note>" lines this person has not outgrown: resolutions of issues that one of THEIR votes on this lineage
    backed, newest first, for ``NOTICE_DAYS`` days. ``[{feedback_id, note, resolved_at}]``; never anyone else's vote."""
    moment = now or datetime.now(timezone.utc)
    with connect(db) as conn:
        rows = conn.execute(
            "SELECT DISTINCT r.id, r.feedback_id, r.note, r.resolved_at FROM hound_feedback_resolutions r "
            "JOIN hound_feedback_issue_votes iv ON iv.feedback_id = r.feedback_id "
            "JOIN hound_feedback f ON f.id = iv.vote_id "
            "WHERE f.user_id = ? AND f.root_id = ? AND r.resolved_at >= ? ORDER BY r.resolved_at DESC, r.id DESC LIMIT ?",
            (user_id, root_id, _iso(moment - timedelta(days=NOTICE_DAYS)), limit)).fetchall()
    return [{"feedback_id": r["feedback_id"], "note": r["note"], "resolved_at": r["resolved_at"]} for r in rows]


# ---------------------------------------------------------------------------
# the digest's reads (every hound at once; the CLI only)
# ---------------------------------------------------------------------------

def votes_between(start: datetime, end: datetime, *, db: Optional[Path] = None) -> list:
    """Current vote rows (not suggestions) created in ``[start, end)``, oldest first, across every hound."""
    with connect(db) as conn:
        rows = conn.execute(
            "SELECT id, hound_id, root_id, target_kind, target_id, verdict, note, chips_json, user_id, created_at "
            "FROM hound_feedback_current WHERE target_kind != ? AND created_at >= ? AND created_at < ? ORDER BY id",
            (KIND_SUGGESTION, _iso(start), _iso(end))).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        item["chips"] = _chips_of(r["chips_json"])
        out.append(item)
    return out
