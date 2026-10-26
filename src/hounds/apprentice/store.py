"""The lessons ledger: three append-only tables in the app database, and the evidence files beside it.

APPEND-ONLY IS ENFORCED BY THE DATABASE, NOT BY GOOD MANNERS. Every table has BEFORE UPDATE and BEFORE DELETE
triggers that abort, so no code path (a future route, a console session, the owner) can edit or remove a lesson, a
state change or a piece of evidence. There is no update or delete function in this module to forget to call.

TABLES
  apprentice_lessons   one row per real bet the owner logged. Never changes: the price they actually got, the stake,
                       the legs, the book, when it was placed, the book's bet id.
  apprentice_events    the state history of a lesson (pending, live, settled, void, cashed_out), one row per change,
                       tagged with who said so (owner, ticket, grader). ``model.derive`` reads it.
  apprentice_evidence  a screenshot (file on the volume) plus the JSON the model extracted from it, linked to a lesson.
  apprentice_recommendations  what LINEHOUND (a hound pick) or Jarvis PUBLISHED, with the time it was published. Written
                       only by the server-side producers (``add_recommendation``); there is no member route that creates
                       one, so a member can never back-date a pick to earn an evidence grade.

KEYED BY THE HOUND'S ROOT ID, so a lesson stays attached to its hound across versions (a Retune makes a new version id)
and survives the hound being retired: retiring changes the hounds table, never these.

WHERE THE FILES LIVE: ``data/app/apprentice/<owner>/`` beside the database (the Fly volume in production, which
deploy/Dockerfile already treats as runtime state: data/app/ is not baked into the image), so no Dockerfile COPY is
needed. Staged uploads (not yet confirmed, so NOT part of the ledger) sit in ``staged/`` and are purged after a day.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional

from src.appstate import users as users_store
from src.hounds.apprentice import model

MAX_IMAGE_BYTES = 4 * 1024 * 1024          # under the model API's 5 MB image limit
MAX_EVIDENCE_PER_USER = 300
MAX_EVIDENCE_BYTES_PER_USER = 150 * 1024 * 1024
STAGED_TTL_S = 24 * 3600
MAX_LESSONS_PER_HOUND = 5000

_MAGIC = ((b"\x89PNG\r\n\x1a\n", "image/png", "png"), (b"\xff\xd8\xff", "image/jpeg", "jpg"))


class StoreError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.code, self.status, self.extra = code, status, extra


class Duplicate(StoreError):
    def __init__(self, lesson_id: str, by: str):
        super().__init__("duplicate", f"this bet is already in the ledger (same {by})", 409, lesson_id=lesson_id, by=by)
        self.lesson_id = lesson_id


SCHEMA = """
CREATE TABLE IF NOT EXISTS apprentice_lessons (
    id TEXT PRIMARY KEY, hound_root TEXT NOT NULL, hound_id TEXT NOT NULL, owner_id INTEGER NOT NULL,
    created_utc TEXT NOT NULL, bet_type TEXT NOT NULL, legs_json TEXT NOT NULL, stake REAL NOT NULL, book TEXT NOT NULL,
    placed_utc TEXT NOT NULL, ticket_id TEXT, total_price INTEGER NOT NULL, payout_quoted REAL, source TEXT NOT NULL,
    image_hash TEXT, bettor TEXT NOT NULL DEFAULT 'unknown', recommendation_id TEXT, recommended_utc TEXT);
CREATE INDEX IF NOT EXISTS apprentice_lessons_root ON apprentice_lessons (hound_root, placed_utc);
CREATE UNIQUE INDEX IF NOT EXISTS apprentice_lessons_ticket ON apprentice_lessons (owner_id, ticket_id) WHERE ticket_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS apprentice_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, lesson_id TEXT NOT NULL, at_utc TEXT NOT NULL, source TEXT NOT NULL,
    state TEXT NOT NULL, data_json TEXT NOT NULL, evidence_id TEXT);
CREATE INDEX IF NOT EXISTS apprentice_events_lesson ON apprentice_events (lesson_id, seq);
CREATE TABLE IF NOT EXISTS apprentice_evidence (
    id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL, hound_root TEXT NOT NULL, lesson_id TEXT NOT NULL,
    image_hash TEXT NOT NULL, media_type TEXT NOT NULL, size INTEGER NOT NULL, path TEXT NOT NULL,
    extracted_json TEXT NOT NULL, created_utc TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS apprentice_evidence_hash ON apprentice_evidence (owner_id, image_hash);
CREATE TABLE IF NOT EXISTS apprentice_recommendations (
    id TEXT PRIMARY KEY, source TEXT NOT NULL, recommended_utc TEXT NOT NULL, legs_json TEXT NOT NULL, created_utc TEXT NOT NULL);
"""
TABLES = ("apprentice_lessons", "apprentice_events", "apprentice_evidence", "apprentice_recommendations")


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table in TABLES:
        for verb in ("UPDATE", "DELETE"):
            conn.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{verb.lower()} BEFORE {verb} ON {table} "
                         f"BEGIN SELECT RAISE(ABORT, 'the lessons ledger is append-only'); END")


@contextmanager
def connect(db: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    with users_store._connect(db) as conn:
        ensure_schema(conn)
        yield conn


def root_dir(db: Optional[Path] = None) -> Path:
    override = (os.environ.get("APPRENTICE_DIR") or "").strip()
    return Path(override) if override else (db or users_store.db_path()).parent / "apprentice"


def _utcnow(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# images
# ---------------------------------------------------------------------------

def sniff_image(data: bytes) -> tuple:
    """(media_type, extension) from the file's own first bytes, or ``StoreError``. The client's claim is never used."""
    if not data:
        raise StoreError("empty_image", "that file is empty", 422)
    if len(data) > MAX_IMAGE_BYTES:
        raise StoreError("image_too_large", f"screenshots can be up to {MAX_IMAGE_BYTES // (1024 * 1024)} MB", 413)
    for magic, media, ext in _MAGIC:
        if data.startswith(magic):
            return media, ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    raise StoreError("not_an_image", "upload a PNG, JPEG or WebP screenshot", 422)


def image_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _user_dir(owner_id: int, db: Optional[Path]) -> Path:
    return root_dir(db) / str(int(owner_id))


def purge_staged(owner_id: int, *, db: Optional[Path] = None, now_s: Optional[float] = None) -> int:
    """Delete unconfirmed uploads older than a day. They are not ledger rows; confirmed evidence is never touched."""
    folder = _user_dir(owner_id, db) / "staged"
    now_s = time.time() if now_s is None else now_s
    gone = 0
    if folder.is_dir():
        for f in folder.iterdir():
            try:
                if now_s - f.stat().st_mtime > STAGED_TTL_S:
                    f.unlink()
                    gone += 1
            except OSError:
                pass
    return gone


def stage_image(owner_id: int, data: bytes, extracted: Optional[Mapping] = None, *, db: Optional[Path] = None) -> dict:
    """Keep an upload (and what the model read from it) until the owner confirms. Returns ``{hash, media_type}``."""
    media, ext = sniff_image(data)
    digest = image_hash(data)
    folder = _user_dir(owner_id, db) / "staged"
    folder.mkdir(parents=True, exist_ok=True)
    purge_staged(owner_id, db=db)
    (folder / f"{digest}.{ext}").write_bytes(data)
    (folder / f"{digest}.json").write_text(json.dumps(extracted if extracted is not None else {}, sort_keys=True),
                                           encoding="utf-8")
    return {"hash": digest, "media_type": media}


def staged(owner_id: int, digest: str, *, db: Optional[Path] = None) -> Optional[dict]:
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        return None
    folder = _user_dir(owner_id, db) / "staged"
    for _m, media, ext in _MAGIC + ((b"", "image/webp", "webp"),):
        f = folder / f"{digest}.{ext}"
        j = folder / f"{digest}.json"
        if f.is_file() and j.is_file():
            return {"hash": digest, "media_type": media, "path": f, "json": json.loads(j.read_text(encoding="utf-8"))}
    return None


def _file_evidence(conn, owner_id: int, hound_root: str, lesson_id: str, digest: str, now: datetime,
                   db: Optional[Path]) -> str:
    st = staged(owner_id, digest, db=db)
    if st is None:
        raise StoreError("image_not_staged", "that screenshot is not waiting for confirmation; upload it again", 409)
    used = conn.execute("SELECT COUNT(*) n, COALESCE(SUM(size), 0) b FROM apprentice_evidence WHERE owner_id = ?",
                        (owner_id,)).fetchone()
    size = st["path"].stat().st_size
    if used["n"] >= MAX_EVIDENCE_PER_USER or used["b"] + size > MAX_EVIDENCE_BYTES_PER_USER:
        raise StoreError("evidence_full", "this account's screenshot storage is full", 413)
    final = _user_dir(owner_id, db) / st["path"].name
    os.replace(st["path"], final)
    evidence_id = "ev-" + secrets.token_hex(6)
    conn.execute("INSERT INTO apprentice_evidence (id, owner_id, hound_root, lesson_id, image_hash, media_type, size, path, "
                 "extracted_json, created_utc) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (evidence_id, owner_id, hound_root, lesson_id, digest, st["media_type"], size, str(final),
                  json.dumps(st["json"], sort_keys=True), model.iso(now)))
    try:
        (_user_dir(owner_id, db) / "staged" / f"{digest}.json").unlink()
    except OSError:
        pass
    return evidence_id


def evidence_hash_known(owner_id: int, digest: str, *, db: Optional[Path] = None) -> Optional[dict]:
    """The lesson a screenshot is already filed against (same image bytes), or None."""
    with connect(db) as conn:
        row = conn.execute("SELECT lesson_id, id FROM apprentice_evidence WHERE owner_id = ? AND image_hash = ?",
                           (owner_id, digest)).fetchone()
    return None if row is None else {"lesson_id": row["lesson_id"], "evidence_id": row["id"]}


# ---------------------------------------------------------------------------
# writes (inserts only)
# ---------------------------------------------------------------------------

def _row_lesson(row: sqlite3.Row) -> dict:
    out = {k: row[k] for k in row.keys() if k != "legs_json"}
    out["legs"] = json.loads(row["legs_json"])
    return out


def _event_row(row: sqlite3.Row) -> dict:
    return {"seq": row["seq"], "lesson_id": row["lesson_id"], "at_utc": row["at_utc"], "source": row["source"],
            "state": row["state"], "data": json.loads(row["data_json"]), "evidence_id": row["evidence_id"]}


def _check_state(state: str, data: Mapping) -> dict:
    data = dict(data or {})
    if state not in model.STATES:
        raise StoreError("bad_state", "unknown state", 422)
    if state == model.SETTLED and data.get("result") not in ("won", "lost", "push"):
        raise StoreError("bad_state", "a settled lesson needs a result: won, lost or push", 422)
    if data.get("settlement_time") is not None:
        when = model.parse_time(data["settlement_time"])
        if when is None:
            raise StoreError("bad_state", "settlement_time must be a date and time", 422)
        data["settlement_time"] = model.iso(when)
    if state == model.CASHED_OUT:
        amount = data.get("cash_out_amount")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount < 0 or amount > 1e7:
            raise StoreError("bad_state", "a cash-out needs the amount you got back", 422)
        data["cash_out_amount"] = round(float(amount), 2)
    return data


def _append(conn, lesson_id: str, source: str, state: str, data: Mapping, now: datetime,
            evidence_id: Optional[str] = None) -> int:
    cur = conn.execute("INSERT INTO apprentice_events (lesson_id, at_utc, source, state, data_json, evidence_id) "
                       "VALUES (?,?,?,?,?,?)",
                       (lesson_id, model.iso(now), source, state, json.dumps(dict(data), sort_keys=True), evidence_id))
    return int(cur.lastrowid)


def add_recommendation(rec_id: str, source: str, recommended_utc: str, legs: list, *, now: Optional[datetime] = None,
                       db: Optional[Path] = None) -> dict:
    """File one published recommendation (a hound pick or a Jarvis item): ``legs`` are leg dicts like a lesson's
    (event_id or game, market, player or selection, side, line). Called by the producers, never by a member."""
    if not rec_id or not legs or model.parse_time(recommended_utc) is None:
        raise StoreError("bad_recommendation", "a recommendation needs an id, legs and the time it was published", 422)
    with connect(db) as conn:
        try:
            conn.execute("INSERT INTO apprentice_recommendations (id, source, recommended_utc, legs_json, created_utc) "
                         "VALUES (?,?,?,?,?)", (str(rec_id)[:64], str(source)[:40], recommended_utc,
                                                json.dumps(legs, sort_keys=True), model.iso(_utcnow(now))))
        except sqlite3.IntegrityError:
            raise StoreError("duplicate", "that recommendation id is already filed", 409)
    return get_recommendation(rec_id, db=db)


def _rec_row(row) -> dict:
    return {"id": row["id"], "source": row["source"], "recommended_utc": row["recommended_utc"],
            "legs": json.loads(row["legs_json"])}


def get_recommendation(rec_id: str, *, db: Optional[Path] = None) -> Optional[dict]:
    with connect(db) as conn:
        row = conn.execute("SELECT * FROM apprentice_recommendations WHERE id = ?", (rec_id,)).fetchone()
    return None if row is None else _rec_row(row)


def recommendations(*, db: Optional[Path] = None) -> list:
    with connect(db) as conn:
        rows = conn.execute("SELECT * FROM apprentice_recommendations ORDER BY recommended_utc, id").fetchall()
    return [_rec_row(r) for r in rows]


def add_lesson(hound: Mapping, owner_id: int, lesson: Mapping, *, source: str = "owner", image: Optional[str] = None,
               now: Optional[datetime] = None, db: Optional[Path] = None) -> dict:
    """File one validated lesson (``model.normalize_lesson``'s output) with its first event (pending), and, when a staged
    screenshot is named, the evidence, all in one transaction. A repeat of the same book bet id, or of the same
    screenshot, is ``Duplicate`` and writes nothing."""
    now = _utcnow(now)
    if hound["status"] in ("retired", "buried"):
        raise StoreError("not_active", f"this hound is {hound['status']}; its lessons stay, but it takes no new ones", 409)
    lesson_id = "ls-" + secrets.token_hex(6)
    with connect(db) as conn:
        conn.execute("BEGIN IMMEDIATE")
        n = conn.execute("SELECT COUNT(*) FROM apprentice_lessons WHERE hound_root = ?", (hound["root_id"],)).fetchone()[0]
        if n >= MAX_LESSONS_PER_HOUND:
            raise StoreError("ledger_full", "this hound's lessons ledger is full", 413)
        if lesson.get("ticket_id"):
            hit = conn.execute("SELECT id FROM apprentice_lessons WHERE owner_id = ? AND ticket_id = ?",
                               (owner_id, lesson["ticket_id"])).fetchone()
            if hit:
                raise Duplicate(hit["id"], "bet ID")
        if image:
            hit = conn.execute("SELECT lesson_id FROM apprentice_evidence WHERE owner_id = ? AND image_hash = ?",
                               (owner_id, image)).fetchone()
            if hit:
                raise Duplicate(hit["lesson_id"], "screenshot")
        conn.execute("INSERT INTO apprentice_lessons (id, hound_root, hound_id, owner_id, created_utc, bet_type, legs_json, "
                     "stake, book, placed_utc, ticket_id, total_price, payout_quoted, source, image_hash, bettor, "
                     "recommendation_id, recommended_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (lesson_id, hound["root_id"], hound["id"], owner_id, model.iso(now), lesson["bet_type"],
                      json.dumps(lesson["legs"], sort_keys=True), lesson["stake"], lesson["book"], lesson["placed_utc"],
                      lesson.get("ticket_id"), lesson["total_price"], lesson.get("payout_quoted"), source, image,
                      lesson.get("bettor") or "unknown", lesson.get("recommendation_id"), lesson.get("recommended_utc")))
        evidence_id = _file_evidence(conn, owner_id, hound["root_id"], lesson_id, image, now, db) if image else None
        _append(conn, lesson_id, "owner", model.PENDING, {"note": "logged"}, now, evidence_id)
    return get_lesson(lesson_id, db=db)


def append_event(lesson_id: str, owner_id: int, source: str, state: str, data: Optional[Mapping] = None, *,
                 image: Optional[str] = None, now: Optional[datetime] = None, db: Optional[Path] = None) -> Optional[dict]:
    """Append one state change. Returns the event, or None when it says nothing new (same state as the newest event of
    that channel). A terminal state cannot go back to pending or live. With ``image`` (a staged re-import screenshot) the
    screenshot is filed as evidence on the same lesson. Never edits an existing row."""
    if source not in model.SOURCES:
        raise StoreError("bad_source", "unknown source", 422)
    data = _check_state(state, data or {})
    now = _utcnow(now)
    with connect(db) as conn:
        conn.execute("BEGIN IMMEDIATE")
        lesson = conn.execute("SELECT * FROM apprentice_lessons WHERE id = ? AND owner_id = ?", (lesson_id, owner_id)).fetchone()
        if lesson is None:
            raise StoreError("not_found", "no such lesson", 404)
        channel = model.BOOK_SOURCES if source in model.BOOK_SOURCES else (source,)
        marks = ",".join("?" * len(channel))
        last = conn.execute(f"SELECT * FROM apprentice_events WHERE lesson_id = ? AND source IN ({marks}) "
                            "ORDER BY seq DESC LIMIT 1", (lesson_id, *channel)).fetchone()
        if last is not None:
            prev = _event_row(last)
            if prev["state"] == state and {k: v for k, v in prev["data"].items() if k in ("result", "cash_out_amount")} == \
                    {k: v for k, v in data.items() if k in ("result", "cash_out_amount")} and not data.get("resolution"):
                return None
            if source != "grader" and prev["state"] in model.TERMINAL and state in (model.PENDING, model.LIVE):
                raise StoreError("terminal", "a settled ticket cannot go back to pending", 409)
        evidence_id = None
        if image:
            if conn.execute("SELECT 1 FROM apprentice_evidence WHERE owner_id = ? AND image_hash = ?",
                            (owner_id, image)).fetchone():
                raise Duplicate(lesson_id, "screenshot")
            evidence_id = _file_evidence(conn, owner_id, lesson["hound_root"], lesson_id, image, now, db)
        seq = _append(conn, lesson_id, source, state, data, now, evidence_id)
    return {"seq": seq, "lesson_id": lesson_id, "source": source, "state": state, "data": data, "evidence_id": evidence_id}


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

def get_lesson(lesson_id: str, *, db: Optional[Path] = None) -> Optional[dict]:
    with connect(db) as conn:
        row = conn.execute("SELECT * FROM apprentice_lessons WHERE id = ?", (lesson_id,)).fetchone()
    return None if row is None else _row_lesson(row)


def find_by_ticket(owner_id: int, ticket_id: str, *, db: Optional[Path] = None) -> Optional[dict]:
    with connect(db) as conn:
        row = conn.execute("SELECT * FROM apprentice_lessons WHERE owner_id = ? AND ticket_id = ?",
                           (owner_id, ticket_id)).fetchone()
    return None if row is None else _row_lesson(row)


def lessons_for(hound_root: str, *, db: Optional[Path] = None) -> list:
    """Every lesson of a hound (oldest first) with its events, as ``(lesson, events)`` pairs."""
    with connect(db) as conn:
        rows = conn.execute("SELECT * FROM apprentice_lessons WHERE hound_root = ? ORDER BY placed_utc, id",
                            (hound_root,)).fetchall()
        out = []
        for row in rows:
            ev = conn.execute("SELECT * FROM apprentice_events WHERE lesson_id = ? ORDER BY seq", (row["id"],)).fetchall()
            out.append((_row_lesson(row), [_event_row(e) for e in ev]))
    return out


def evidence_for(lesson_id: str, owner_id: int, *, db: Optional[Path] = None) -> list:
    with connect(db) as conn:
        rows = conn.execute("SELECT * FROM apprentice_evidence WHERE lesson_id = ? AND owner_id = ? ORDER BY created_utc",
                            (lesson_id, owner_id)).fetchall()
    return [{"id": r["id"], "media_type": r["media_type"], "size": r["size"], "created_utc": r["created_utc"],
             "image_hash": r["image_hash"], "extracted": json.loads(r["extracted_json"])} for r in rows]


def evidence_file(evidence_id: str, owner_id: int, *, db: Optional[Path] = None) -> Optional[tuple]:
    """(path, media_type) of an owner's own evidence image, or None."""
    with connect(db) as conn:
        row = conn.execute("SELECT path, media_type FROM apprentice_evidence WHERE id = ? AND owner_id = ?",
                           (evidence_id, owner_id)).fetchone()
    return None if row is None or not Path(row["path"]).is_file() else (Path(row["path"]), row["media_type"])
