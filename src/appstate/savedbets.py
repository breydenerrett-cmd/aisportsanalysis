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
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List, Optional

from src import paths

ENV_DB_PATH = "APP_DB_PATH"  # shared with src.appstate.users -- one app db

# Same two constants, same values, same rationale as
# src.appstate.users._WAL_MODE_RETRY_ATTEMPTS/_WAL_MODE_RETRY_DELAY_S.
_WAL_MODE_RETRY_ATTEMPTS = 10
_WAL_MODE_RETRY_DELAY_S = 0.02


def db_path() -> Path:
    override = (os.environ.get(ENV_DB_PATH) or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return paths.repo_root() / "data" / "app" / "app.db"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_wal_mode(conn: sqlite3.Connection) -> None:
    """PRAGMA journal_mode=WAL, with a small manual retry -- same helper,
    same reasoning as src.appstate.users._set_wal_mode: busy_timeout does
    not cover the special exclusive lock a brand-new db file's FIRST-EVER
    transition into WAL mode takes, so two connections racing to be first
    to open this module's own db file need this narrower retry on top of
    it. See that function's docstring for the full explanation."""
    last_exc: Optional[sqlite3.OperationalError] = None
    for _ in range(_WAL_MODE_RETRY_ATTEMPTS):
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as exc:
            if "database is locked" not in str(exc):
                raise
            last_exc = exc
            time.sleep(_WAL_MODE_RETRY_DELAY_S)
    raise last_exc


@contextmanager
def _connect(path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    resolved = path or db_path()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(resolved))
    conn.row_factory = sqlite3.Row
    # busy_timeout BEFORE journal_mode -- same two pragmas, same order,
    # same rationale as src.appstate.users._connect (this module shares
    # that db file and must behave identically under concurrent access).
    # The order is load-bearing, not stylistic -- see that module's
    # comment for why setting journal_mode first can itself raise
    # "database is locked" with no retry.
    conn.execute("PRAGMA busy_timeout=5000")
    _set_wal_mode(conn)
    try:
        _ensure_schema(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


#  outcome of grading a bet's SIDE against a final result. `push` exists for
# the rare tied/suspended final (MLB's own tie games are uncommon but real);
# `void-unmatchable` is a game that finished but whose saved `side` text this
# module could not confidently pin to either club -- distinct from a bet that
# is simply not settled yet (see src/appstate/settlement.py, which never
# writes one of these unless it actually reached a verdict).
SETTLEMENT_STATUSES = ("won", "lost", "push", "void-unmatchable")


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
    # MIGRATION-SAFE ALTER, not a table rebuild: an existing app.db already
    # has rows a customer saved, so the settlement columns are added to the
    # table that is already there rather than this module ever dropping or
    # recreating it. `CREATE TABLE IF NOT EXISTS` above already handles a
    # brand-new db; this handles the upgrade of one that predates settlement.
    # sqlite has no "ADD COLUMN IF NOT EXISTS", so PRAGMA table_info is
    # consulted first -- re-running ALTER on a column that already exists
    # raises OperationalError and would make every future _connect() fail.
    #
    # THE CHECK-THEN-ALTER ITSELF STILL RACES ACROSS CONNECTIONS. PRAGMA
    # table_info is a plain read (no write lock needed), so two threads
    # opening a brand-new db at the same instant (tests/
    # test_appstate_sqlite_pragmas.py's concurrent-writer smoke test) can
    # both read "column absent" before either's ALTER commits; the loser's
    # own ALTER then fails with "duplicate column name" once it finally
    # gets the write lock, because the winner already added it. WAL made
    # this race easy to hit (before it, the old rollback journal's
    # exclusive per-write lock happened to serialize these two connections
    # enough that the window rarely opened) -- but the fix is not to weaken
    # WAL, it is to make the migration itself idempotent under a race, not
    # just under repeat single-threaded runs. A duplicate-column failure
    # here is not a real problem: the column exists either way, which is
    # all this loop ever promised.
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(saved_bets)")}
    for column, ddl in (
        ("settlement_status", "TEXT"),
        ("settlement_reason", "TEXT"),
        ("settled_at", "TEXT"),
        # The closing-price facts (src.appstate.settlement.compute_closing_price):
        # the h2h price the market closed at, when that observation was
        # taken, and how the saved price compares -- or, when none of that
        # could be computed, why not. `closing_computed_at` is a separate
        # marker of ATTEMPT, not of success: a bet with no snapshots ever
        # captured for its game still gets closing_computed_at stamped, so
        # the backfill (src.appstate.settlement.backfill_closing_prices)
        # knows not to retry it forever, and record_closing's own guard
        # (WHERE closing_computed_at IS NULL) can tell "never attempted"
        # apart from "attempted, found nothing" using one column instead of
        # inferring it from which of four nullable fields happen to be set.
        ("closing_price", "REAL"),
        ("closing_observed_utc", "TEXT"),
        ("price_vs_close_cents", "REAL"),
        ("closing_reason", "TEXT"),
        ("closing_computed_at", "TEXT"),
    ):
        if column not in existing:
            try:
                conn.execute(f"ALTER TABLE saved_bets ADD COLUMN {column} {ddl}")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc):
                    raise  # a different failure (disk full, corrupt db, ...) must still surface


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
    # Appended after the original fields, all defaulted, so every existing
    # positional-free call site (save_bet's own return, every test that
    # builds one directly) keeps working unchanged -- see the module's
    # append-only philosophy: adding a fact about a bet must never mean
    # touching how every previous fact about it is constructed.
    settlement_status: Optional[str] = None
    settlement_reason: Optional[str] = None
    settled_at: Optional[str] = None
    # The closing-price facts, same append-after-the-fact rule -- see the
    # schema comment in _ensure_schema for what each field means and why
    # closing_computed_at exists alongside closing_reason.
    closing_price: Optional[float] = None
    closing_observed_utc: Optional[str] = None
    price_vs_close_cents: Optional[float] = None
    closing_reason: Optional[str] = None
    closing_computed_at: Optional[str] = None

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def is_settled(self) -> bool:
        return self.settlement_status is not None

    @property
    def has_closing_price(self) -> bool:
        return self.closing_computed_at is not None


def _row_to_bet(row: sqlite3.Row) -> SavedBet:
    return SavedBet(id=row["id"], user_id=row["user_id"], game=row["game"],
                     side=row["side"], price=row["price"], saved_at=row["saved_at"],
                     snapshot_digest=row["snapshot_digest"], deleted_at=row["deleted_at"],
                     settlement_status=row["settlement_status"],
                     settlement_reason=row["settlement_reason"],
                     settled_at=row["settled_at"],
                     closing_price=row["closing_price"],
                     closing_observed_utc=row["closing_observed_utc"],
                     price_vs_close_cents=row["price_vs_close_cents"],
                     closing_reason=row["closing_reason"],
                     closing_computed_at=row["closing_computed_at"])


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


def list_unsettled_bets(*, db: Optional[Path] = None) -> List[SavedBet]:
    """Every live (not soft-deleted), not-yet-settled bet across ALL users.

    Unlike list_bets, this is not scoped to one user -- it exists for
    src.appstate.settlement's daily sweep, an internal batch job, not an
    API-reachable read. api/mybets.py must keep scoping every route to
    current_user.id; this function is deliberately not exported through it.
    """
    with _connect(db) as conn:
        rows = conn.execute(
            "SELECT * FROM saved_bets WHERE deleted_at IS NULL "
            "AND settlement_status IS NULL ORDER BY saved_at").fetchall()
        return [_row_to_bet(r) for r in rows]


def mark_settled(bet_id: int, status: str, *, reason: Optional[str] = None,
                 settled_at: Optional[str] = None,
                 db: Optional[Path] = None) -> bool:
    """Record a settlement verdict on one bet. Only ever moves a row from
    unsettled to settled -- there is no re-settle, matching this module's
    append-only rule: once a verdict is written it is not the caller's to
    quietly revise (a graded bet that later needs correction is a new
    finding, not an edit to what My Bets already showed the user).

    Raises ValueError for an unknown status rather than writing a value
    src.appstate.settlement or a future caller might have typo'd -- this is
    the one write path into settlement_status, so it is the one place that
    can catch that mistake.
    """
    if status not in SETTLEMENT_STATUSES:
        raise ValueError(f"unknown settlement status: {status!r}")
    with _connect(db) as conn:
        cur = conn.execute(
            "UPDATE saved_bets SET settlement_status = ?, settlement_reason = ?, "
            "settled_at = ? WHERE id = ? AND settlement_status IS NULL",
            (status, reason, settled_at or _now_iso(), bet_id))
        return cur.rowcount > 0


def list_settled_bets_missing_closing(*, db: Optional[Path] = None) -> List[SavedBet]:
    """Every live, settled bet whose closing-price computation has never
    been attempted -- the backfill's input (src.appstate.settlement.
    backfill_closing_prices). Scoped to settlement_status IS NOT NULL: only
    a graded bet was ever a real pick to price a close for, and to
    closing_computed_at IS NULL, which src.appstate.settlement stamps
    whether or not a close was actually found (see record_closing) -- so a
    bet that was already tried and genuinely has no close (no snapshots
    ever captured for its game) is not re-selected here forever.
    """
    with _connect(db) as conn:
        rows = conn.execute(
            "SELECT * FROM saved_bets WHERE deleted_at IS NULL "
            "AND settlement_status IS NOT NULL AND closing_computed_at IS NULL "
            "ORDER BY saved_at").fetchall()
        return [_row_to_bet(r) for r in rows]


def record_closing(bet_id: int, *, closing_price: Optional[float] = None,
                   closing_observed_utc: Optional[str] = None,
                   price_vs_close_cents: Optional[float] = None,
                   closing_reason: Optional[str] = None,
                   computed_at: Optional[str] = None,
                   db: Optional[Path] = None) -> bool:
    """Persist one bet's closing-price computation. Written exactly once
    per bet, whether the computation succeeded (the three value fields
    set, `closing_reason` left None) or could not be completed (the value
    fields left None, `closing_reason` stating why) -- both are a real,
    final answer, so both stamp `computed_at` and both are guarded by the
    same WHERE clause below. This is what makes settle_saved_bets calling
    it at settle time and backfill_closing_prices calling it later on an
    already-settled row safe to run in either order, or more than once:
    whichever call reaches a row first wins, and every later call is a
    no-op (rowcount 0) rather than an overwrite of a fact already on
    record. There is deliberately no re-close: a closing price, once
    written, is not the caller's to quietly revise, the same rule
    mark_settled already keeps for the settlement verdict itself.
    """
    with _connect(db) as conn:
        cur = conn.execute(
            "UPDATE saved_bets SET closing_price = ?, closing_observed_utc = ?, "
            "price_vs_close_cents = ?, closing_reason = ?, closing_computed_at = ? "
            "WHERE id = ? AND closing_computed_at IS NULL",
            (closing_price, closing_observed_utc, price_vs_close_cents,
             closing_reason, computed_at or _now_iso(), bet_id))
        return cur.rowcount > 0
