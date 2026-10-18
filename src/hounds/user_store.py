"""Where user-built hounds live: three tables in the existing app database.

SAME FILE, SAME PATTERN
-----------------------
`src/appstate/users.py` owns `data/app/app.db` (APP_DB_PATH overrides it). `customers.py` adds its
tables to the same file with `CREATE TABLE IF NOT EXISTS`, and so does this module: one sqlite file,
additive migrations only, db path resolved through `users_store.db_path()` at call time so a test
that points APP_DB_PATH at a temp file redirects this module too. Nothing here alters an existing
table.

TABLES
------
hounds          one row per hound VERSION. The rule lives in `spec_json` and is never updated; the
                columns that DO change are only `status`, `retire_*` and `coach_opt_in`.
                `version_of` links a version to the one it replaced, `root_id` names the first
                version of the lineage, `copied_from` links a copy to the hound it was copied from.
coach_rounds    the one-use keys the server issues for a Houndmaster round (see user_coach.py).
coach_diary     one row per round: when, hound, verdict at the time, decision, old and new spec,
                reason, quip, and who decided.

RECORDS ARE NEVER REWRITTEN
---------------------------
There is no UPDATE that touches `spec_json`. An edit, a coach change and an undo all INSERT a new
hound row (a new id, `version_of` = the old id) and retire the old one, so every bet in the ledger
stays attached to the exact rule that made it.

LIMITS AND WHO MAY CREATE
-------------------------
At most MAX_RUNNING_PER_ACCOUNT running hounds per account; only an existing, non-suspended account
may create (the API additionally requires a paid or tester sign-in). Counting and inserting happen
inside one BEGIN IMMEDIATE transaction so two simultaneous requests cannot both take the last slot.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, List, Mapping, Optional

from src.appstate import users as users_store
from src.hounds import user_spec

STATUS_RUNNING = "running"
STATUS_BENCHED = "benched"
STATUS_RETIRED = "retired"
STATUSES = (STATUS_RUNNING, STATUS_BENCHED, STATUS_RETIRED)

ROUND_TTL = timedelta(minutes=15)
COACH_COOLDOWN = timedelta(days=7)

DECISION_APPLIED = "applied"            # a version was made: by the referee's promotion (or, before the learning loop, the coach)
DECISION_CHALLENGER = "challenger"      # the coach proposed a challenger; it runs in shadow (src/hounds/learning)
DECISION_HELD = "held"
DECISION_REJECTED = "rejected"
DECISION_UNDONE = "undone"


class StoreError(ValueError):
    """A refusal the caller can show: `code` is stable, the message is for people."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hounds (
            id TEXT PRIMARY KEY,
            owner_user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            name_key TEXT NOT NULL,
            tagline TEXT NOT NULL,
            spec_json TEXT NOT NULL,
            spec_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            retire_reason TEXT,
            retired_at TEXT,
            retired_by TEXT,
            created_at TEXT NOT NULL,
            version_of TEXT,
            root_id TEXT NOT NULL,
            version_no INTEGER NOT NULL,
            copied_from TEXT,
            coach_opt_in INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS hounds_owner ON hounds(owner_user_id, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS hounds_root ON hounds(root_id)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS coach_rounds (
            round_id TEXT PRIMARY KEY,
            hound_id TEXT NOT NULL,
            secret TEXT,
            issued_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            issued_by TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS coach_diary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id TEXT NOT NULL,
            hound_id TEXT NOT NULL,
            root_id TEXT NOT NULL,
            decided_at TEXT NOT NULL,
            verdict_json TEXT,
            decision TEXT NOT NULL,
            old_spec_json TEXT,
            new_spec_json TEXT,
            new_hound_id TEXT,
            reason TEXT,
            quip TEXT,
            decided_by TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS coach_diary_root ON coach_diary(root_id, decided_at)")
    # Additive migration (the learning loop): the challenger a diary row created or promoted.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(coach_diary)").fetchall()}
    if "challenger_id" not in cols:
        conn.execute("ALTER TABLE coach_diary ADD COLUMN challenger_id TEXT")


@contextmanager
def _connect(db: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    with users_store._connect(db) as conn:
        _ensure_schema(conn)
        yield conn


def new_hound_id() -> str:
    return "u-" + secrets.token_hex(5)


def _row_to_hound(row: sqlite3.Row) -> dict:
    spec = json.loads(row["spec_json"])
    return {
        "id": row["id"], "owner_user_id": row["owner_user_id"], "name": row["name"],
        "tagline": row["tagline"], "spec": spec, "spec_hash": row["spec_hash"],
        "status": row["status"], "retire_reason": row["retire_reason"],
        "retired_at": row["retired_at"], "retired_by": row["retired_by"],
        "created_at": row["created_at"], "version_of": row["version_of"],
        "root_id": row["root_id"], "version_no": row["version_no"],
        "copied_from": row["copied_from"], "coach_opt_in": bool(row["coach_opt_in"]),
    }


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

def get_hound(hound_id: str, *, db: Optional[Path] = None) -> Optional[dict]:
    with _connect(db) as conn:
        row = conn.execute("SELECT * FROM hounds WHERE id = ?", (hound_id,)).fetchone()
    return _row_to_hound(row) if row else None


def list_for_owner(user_id: int, *, db: Optional[Path] = None) -> List[dict]:
    with _connect(db) as conn:
        rows = conn.execute("SELECT * FROM hounds WHERE owner_user_id = ? ORDER BY created_at, id",
                            (user_id,)).fetchall()
    return [_row_to_hound(r) for r in rows]


def list_by_status(status: str, *, db: Optional[Path] = None) -> List[dict]:
    with _connect(db) as conn:
        rows = conn.execute("SELECT * FROM hounds WHERE status = ? ORDER BY created_at, id",
                            (status,)).fetchall()
    return [_row_to_hound(r) for r in rows]


def list_running(*, db: Optional[Path] = None) -> List[dict]:
    return list_by_status(STATUS_RUNNING, db=db)


def list_all(*, db: Optional[Path] = None) -> List[dict]:
    with _connect(db) as conn:
        rows = conn.execute("SELECT * FROM hounds ORDER BY created_at, id").fetchall()
    return [_row_to_hound(r) for r in rows]


def lineage(hound_id: str, *, db: Optional[Path] = None) -> List[dict]:
    """Every version of the hound's lineage, oldest first."""
    hound = get_hound(hound_id, db=db)
    if hound is None:
        return []
    with _connect(db) as conn:
        rows = conn.execute("SELECT * FROM hounds WHERE root_id = ? ORDER BY version_no, id",
                            (hound["root_id"],)).fetchall()
    return [_row_to_hound(r) for r in rows]


def _taken_names(conn, *, exclude_root: Optional[str] = None) -> list:
    rows = conn.execute("SELECT name, root_id FROM hounds").fetchall()
    return [r["name"] for r in rows if r["root_id"] != exclude_root]


def taken_names(*, db: Optional[Path] = None) -> list:
    with _connect(db) as conn:
        return _taken_names(conn)


def _running_count(conn, user_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM hounds WHERE owner_user_id = ? AND status = ?",
                        (user_id, STATUS_RUNNING)).fetchone()[0]


def suggest_copy_name(source_name: str, *, db: Optional[Path] = None) -> str:
    """A free name for a copy of `source_name`: '<name> II', '<name> III', ... within 24 chars."""
    taken = {user_spec._fold(n) for n in taken_names(db=db)}
    for suffix in (" II", " III", " IV", " V", " VI", " VII", " VIII", " IX", " X"):
        stem = source_name[: user_spec.NAME_MAX - len(suffix)].rstrip(" -")
        candidate = stem + suffix
        if user_spec._fold(candidate) not in taken:
            return candidate
    return source_name[: user_spec.NAME_MAX - 5].rstrip(" -") + " " + secrets.token_hex(2)


# ---------------------------------------------------------------------------
# creating hounds
# ---------------------------------------------------------------------------

def _insert(conn, *, hound_id, owner, spec, status, created_at, version_of, root_id, version_no,
            copied_from, coach_opt_in) -> None:
    conn.execute(
        "INSERT INTO hounds (id, owner_user_id, name, name_key, tagline, spec_json, spec_hash, "
        "status, created_at, version_of, root_id, version_no, copied_from, coach_opt_in) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (hound_id, owner, spec["name"], user_spec._fold(spec["name"]), spec["tagline"],
         json.dumps(spec, sort_keys=True), user_spec.spec_hash(spec), status, created_at,
         version_of, root_id, version_no, copied_from, 1 if coach_opt_in else 0))


def _require_account(conn, user_id: int) -> None:
    row = conn.execute("SELECT status FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise StoreError("no_account", "only a signed-in account can create a hound")
    if row["status"] == "suspended":
        raise StoreError("account_suspended", "this account is suspended")


def create_hound(user_id: int, raw_spec: Mapping, *, copied_from: Optional[str] = None,
                 coach_opt_in: bool = False, now: Optional[datetime] = None,
                 db: Optional[Path] = None,
                 extra_real_names: Optional[Mapping[str, str]] = None) -> dict:
    """Validate `raw_spec` and create version 1 of a new hound, or raise.

    SpecError for a spec the menu refuses; StoreError('limit', ...) for the fourth running hound;
    StoreError('no_account', ...) for a user id with no account. The whole check-and-insert runs in
    one BEGIN IMMEDIATE transaction."""
    created = _iso(_now(now))
    with _connect(db) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _require_account(conn, user_id)
        if _running_count(conn, user_id) >= user_spec.MAX_RUNNING_PER_ACCOUNT:
            raise StoreError("limit", f"an account can run at most "
                             f"{user_spec.MAX_RUNNING_PER_ACCOUNT} hounds; retire one first")
        if copied_from is not None:
            src = conn.execute("SELECT id FROM hounds WHERE id = ?", (copied_from,)).fetchone()
            if src is None:
                raise StoreError("unknown_source", "the hound being copied does not exist")
        spec = user_spec.validate_spec(raw_spec, taken_names=_taken_names(conn),
                                       extra_real_names=extra_real_names)
        hound_id = new_hound_id()
        _insert(conn, hound_id=hound_id, owner=user_id, spec=spec, status=STATUS_RUNNING,
                created_at=created, version_of=None, root_id=hound_id, version_no=1,
                copied_from=copied_from, coach_opt_in=coach_opt_in)
    return get_hound(hound_id, db=db)


def create_version(old_id: str, raw_spec: Mapping, *, actor: str, reason: str,
                   now: Optional[datetime] = None, db: Optional[Path] = None,
                   extra_real_names: Optional[Mapping[str, str]] = None) -> dict:
    """A changed rule is a NEW hound: insert version n+1 (`version_of` = old id) and retire the old
    one. The old row's spec and every bet recorded against it stay exactly as they were. The new
    version inherits the owner and the coach opt-in; it keeps the lineage's name (the name is not
    'taken' by its own earlier versions)."""
    created = _iso(_now(now))
    with _connect(db) as conn:
        conn.execute("BEGIN IMMEDIATE")
        old = conn.execute("SELECT * FROM hounds WHERE id = ?", (old_id,)).fetchone()
        if old is None:
            raise StoreError("not_found", "no such hound")
        if old["status"] == STATUS_RETIRED:
            raise StoreError("retired", "a retired hound cannot be changed")
        owner = old["owner_user_id"]
        _require_account(conn, owner)
        spec = user_spec.validate_spec(
            raw_spec, taken_names=_taken_names(conn, exclude_root=old["root_id"]),
            extra_real_names=extra_real_names)
        newest = conn.execute("SELECT MAX(version_no) FROM hounds WHERE root_id = ?",
                              (old["root_id"],)).fetchone()[0]
        hound_id = new_hound_id()
        was_running = old["status"] == STATUS_RUNNING
        conn.execute("UPDATE hounds SET status = ?, retire_reason = ?, retired_at = ?, "
                     "retired_by = ? WHERE id = ?",
                     (STATUS_RETIRED, f"superseded by {hound_id}: {reason}"[:300], created,
                      actor, old_id))
        _insert(conn, hound_id=hound_id, owner=owner, spec=spec,
                status=STATUS_RUNNING if was_running else STATUS_BENCHED, created_at=created,
                version_of=old_id, root_id=old["root_id"], version_no=(newest or 1) + 1,
                copied_from=None, coach_opt_in=bool(old["coach_opt_in"]))
    return get_hound(hound_id, db=db)


def retire_hound(hound_id: str, *, by: str, reason: str, now: Optional[datetime] = None,
                 db: Optional[Path] = None) -> dict:
    """Retire a hound (owner, or an admin for moderation). Idempotent: a retired hound keeps its
    first retirement. Bets already recorded are untouched; no new bets are made."""
    reason = " ".join((reason or "").split())[:300]
    if not reason:
        raise StoreError("reason_required", "a retirement needs a reason")
    stamp = _iso(_now(now))
    with _connect(db) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT status FROM hounds WHERE id = ?", (hound_id,)).fetchone()
        if row is None:
            raise StoreError("not_found", "no such hound")
        if row["status"] != STATUS_RETIRED:
            conn.execute("UPDATE hounds SET status = ?, retire_reason = ?, retired_at = ?, "
                         "retired_by = ? WHERE id = ?",
                         (STATUS_RETIRED, reason, stamp, by, hound_id))
    return get_hound(hound_id, db=db)


def set_coach_opt_in(hound_id: str, enabled: bool, *, db: Optional[Path] = None) -> dict:
    with _connect(db) as conn:
        cur = conn.execute("UPDATE hounds SET coach_opt_in = ? WHERE id = ?",
                           (1 if enabled else 0, hound_id))
        if cur.rowcount == 0:
            raise StoreError("not_found", "no such hound")
    return get_hound(hound_id, db=db)


# ---------------------------------------------------------------------------
# Houndmaster rounds and the diary (logic lives in user_coach.py)
# ---------------------------------------------------------------------------

def last_coach_decision(root_id: str, *, db: Optional[Path] = None) -> Optional[dict]:
    """The newest diary row for the lineage that used up the 7-day allowance (applied or held)."""
    with _connect(db) as conn:
        row = conn.execute(
            "SELECT * FROM coach_diary WHERE root_id = ? AND decision IN (?, ?, ?) "
            "ORDER BY decided_at DESC, id DESC LIMIT 1",
            (root_id, DECISION_APPLIED, DECISION_HELD, DECISION_CHALLENGER)).fetchone()
    return dict(row) if row else None


def open_round_for(hound_id: str, now: datetime, *, db: Optional[Path] = None) -> Optional[dict]:
    with _connect(db) as conn:
        row = conn.execute(
            "SELECT * FROM coach_rounds WHERE hound_id = ? AND used_at IS NULL AND expires_at > ? "
            "ORDER BY issued_at DESC LIMIT 1", (hound_id, _iso(now))).fetchone()
    return dict(row) if row else None


def insert_round(hound_id: str, issued_by: str, now: datetime, *,
                 db: Optional[Path] = None) -> dict:
    round_id = "r-" + secrets.token_hex(6)
    secret = secrets.token_hex(32)
    with _connect(db) as conn:
        conn.execute(
            "INSERT INTO coach_rounds (round_id, hound_id, secret, issued_at, expires_at, issued_by) "
            "VALUES (?,?,?,?,?,?)",
            (round_id, hound_id, secret, _iso(now), _iso(now + ROUND_TTL), issued_by))
    return {"round_id": round_id, "secret": secret, "issued_at": _iso(now),
            "expires_at": _iso(now + ROUND_TTL)}


def get_round(round_id: str, *, db: Optional[Path] = None) -> Optional[dict]:
    with _connect(db) as conn:
        row = conn.execute("SELECT * FROM coach_rounds WHERE round_id = ?", (round_id,)).fetchone()
    return dict(row) if row else None


def burn_round(round_id: str, now: datetime, *, db: Optional[Path] = None) -> bool:
    """Mark a round used and wipe its secret. True only for the call that wins the race: two
    simultaneous submissions of one round cannot both be accepted."""
    with _connect(db) as conn:
        cur = conn.execute(
            "UPDATE coach_rounds SET used_at = ?, secret = NULL "
            "WHERE round_id = ? AND used_at IS NULL AND expires_at > ?",
            (_iso(now), round_id, _iso(now)))
        return cur.rowcount == 1


def add_diary(*, round_id: str, hound: Mapping, decision: str, decided_by: str,
              verdict: Any = None, old_spec: Any = None, new_spec: Any = None,
              new_hound_id: Optional[str] = None, reason: str = "", quip: str = "",
              challenger_id: Optional[str] = None,
              now: Optional[datetime] = None, db: Optional[Path] = None) -> int:
    with _connect(db) as conn:
        cur = conn.execute(
            "INSERT INTO coach_diary (round_id, hound_id, root_id, decided_at, verdict_json, "
            "decision, old_spec_json, new_spec_json, new_hound_id, reason, quip, decided_by, "
            "challenger_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (round_id, hound["id"], hound["root_id"], _iso(_now(now)),
             json.dumps(verdict, sort_keys=True) if verdict is not None else None, decision,
             json.dumps(old_spec, sort_keys=True) if old_spec is not None else None,
             json.dumps(new_spec, sort_keys=True) if new_spec is not None else None,
             new_hound_id, reason, quip, decided_by, challenger_id))
        return cur.lastrowid


def diary_for(hound_id: str, *, db: Optional[Path] = None) -> List[dict]:
    """The whole lineage's diary, newest first."""
    hound = get_hound(hound_id, db=db)
    if hound is None:
        return []
    with _connect(db) as conn:
        rows = conn.execute("SELECT * FROM coach_diary WHERE root_id = ? ORDER BY decided_at DESC, "
                            "id DESC", (hound["root_id"],)).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        for key in ("verdict_json", "old_spec_json", "new_spec_json"):
            item[key[:-5]] = json.loads(item.pop(key)) if item.get(key) else None
        out.append(item)
    return out
