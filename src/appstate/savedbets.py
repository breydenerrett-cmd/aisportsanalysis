""""My Bets" -- append-only saved-bet records per user, stdlib sqlite3.

APPEND-ONLY, SOFT-DELETE
-------------------------
A saved bet is a record of what a user saw and chose to keep, at the
moment they saved it. Rewriting a saved row in place would let a later
price update silently change what the user is shown as "the bet I saved" --
the same falsified-history problem src/paths.py's evidence_path guards
against for forward evidence. So there is no update_bet(): only save_bet()
(insert) and delete_bet() (soft: sets deleted_at, never removes the row).
list_bets() hides soft-deleted rows by default so "My Bets" reads clean,
but the row -- and the price/side/snapshot it was saved with -- survives.

THE SNAPSHOT DIGEST
--------------------
`snapshot_digest` is a caller-supplied fingerprint of whatever bet-check
evidence backed this save (e.g. a hash of the Dossier/findings payload at
save time). This module does not compute it -- it has no view into
src/detect's evidence shapes and must not guess one -- it only stores
whatever the caller passes, so "what evidence did the user actually see"
stays reconstructable without this module needing to know the evidence
schema.
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

ENV_DB_PATH = "APP_DB_PATH"  # shared with src.appstate.users -- one app db


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
        CREATE TABLE IF NOT EXISTS saved_bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            game TEXT NOT NULL,
            side TEXT NOT NULL,
            price REAL,
            saved_at TEXT NOT NULL,
            snapshot_digest TEXT,
            deleted_at TEXT
        )
    """)


@dataclass(frozen=True)
class SavedBet:
    id: int
    user_id: int
    game: str
    side: str
    price: Optional[float]
    saved_at: str
    snapshot_digest: Optional[str]
    deleted_at: Optional[str]

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


def _row_to_bet(row: sqlite3.Row) -> SavedBet:
    return SavedBet(id=row["id"], user_id=row["user_id"], game=row["game"],
                     side=row["side"], price=row["price"], saved_at=row["saved_at"],
                     snapshot_digest=row["snapshot_digest"], deleted_at=row["deleted_at"])


def save_bet(user_id: int, game: str, side: str, *, price: Optional[float] = None,
             snapshot_digest: Optional[str] = None,
             db: Optional[Path] = None) -> SavedBet:
    """Append a new saved-bet row. Never updates an existing one -- see
    module docstring."""
    if not game or not side:
        raise ValueError("game and side are required")
    saved_at = _now_iso()
    with _connect(db) as conn:
        cur = conn.execute(
            "INSERT INTO saved_bets (user_id, game, side, price, saved_at, "
            "snapshot_digest, deleted_at) VALUES (?, ?, ?, ?, ?, ?, NULL)",
            (user_id, game, side, price, saved_at, snapshot_digest))
        return SavedBet(id=cur.lastrowid, user_id=user_id, game=game, side=side,
                         price=price, saved_at=saved_at,
                         snapshot_digest=snapshot_digest, deleted_at=None)


def list_bets(user_id: int, *, include_deleted: bool = False,
              db: Optional[Path] = None) -> List[SavedBet]:
    query = "SELECT * FROM saved_bets WHERE user_id = ?"
    if not include_deleted:
        query += " AND deleted_at IS NULL"
    query += " ORDER BY saved_at DESC"
    with _connect(db) as conn:
        rows = conn.execute(query, (user_id,)).fetchall()
        return [_row_to_bet(r) for r in rows]


def delete_bet(bet_id: int, user_id: int, *, db: Optional[Path] = None) -> bool:
    """Soft-delete: sets deleted_at, scoped to user_id so one user can never
    delete another's row by guessing an id. Returns True if a live row was
    found and marked deleted."""
    with _connect(db) as conn:
        cur = conn.execute(
            "UPDATE saved_bets SET deleted_at = ? "
            "WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
            (_now_iso(), bet_id, user_id))
        return cur.rowcount > 0
