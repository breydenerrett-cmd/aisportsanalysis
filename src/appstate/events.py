"""Product-analytics event scaffold, stdlib-only (sqlite3, hashlib).

ADDITIVE ONLY -- NOT WIRED IN YET
-----------------------------------
This module is deliberately not called from any endpoint yet. Two other
concurrent agents own src/appstate/{reqlog,freshness}.py and api/odds.py;
threading `record_event()` calls into api/today.py, api/games.py,
api/betcheck.py or api/mybets.py right now would touch files those agents
are actively editing for an unrelated reason and risk a merge collision
neither side asked for. The integration point is a follow-up task: call
`record_event()` from
  - api/today.py / api/games.py     -> kind=PAGE_VIEW, on a successful GET
  - api/betcheck.py                 -> kind=BET_CHECK_RUN, on a successful
                                        POST /betcheck (never on the 400/404
                                        error paths -- those are not a
                                        completed check)
  - api/mybets.py                   -> kind=BET_SAVED, on a successful
                                        POST /my-bets
  - wherever invite redemption ends up living (src/appstate/users.py's
    token-consuming call, once one exists) -> kind=INVITE_REDEEMED
`user_hash` at each call site is `hash_user_id(current_user.id)` -- never
the raw id, and never anything from the request body.

WHY THE USER ID IS HASHED, NEVER STORED RAW
----------------------------------------------
Same rule src/appstate/users.py states for bearer tokens and
src/appstate/reqlog.py states for log lines, applied a third time here: an
analytics table is the piece of this system most likely to end up in a
BI tool, a CSV export, or a dashboard with looser access control than the
users table itself. Storing only sha256(user_id) means none of those
downstream copies can be joined back to an email or a real identity without
also having the raw id -- which this module never receives. `hash_user_id`
takes the raw id so this module is the ONE place that computation happens
consistently; nothing else in the codebase should hand-roll it.

WHAT NEVER GOES IN `properties_json`
----------------------------------------
No emails, no raw auth tokens, no bet amounts or stakes. `properties_json`
exists for event-shape context that is safe to aggregate across users
(e.g. {"date": "2026-08-31"} on a page_view, {"market": "h2h"} on a
bet_check_run) -- never anything that identifies a person or their money.
This module does not and cannot enforce that at the type level (a caller
can pass any JSON-serialisable dict), so the boundary is a documented
contract for every future call site, the same way src/appstate/savedbets.py
documents its append-only contract in prose rather than code.

SCHEMA
------
analytics_events(id, user_hash, kind, properties_json, at)
    kind: page_view | bet_check_run | bet_saved | invite_redeemed
    at:   required ISO-8601 UTC string, the instant the event happened.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from src import paths

ENV_DB_PATH = "APP_DB_PATH"  # shared with src.appstate.users/savedbets -- one app db

# The only kinds this table accepts. Enumerated (not free text) so a typo'd
# kind fails loud at record time instead of silently fragmenting an
# aggregate query later -- the same reasoning src/analysis/contracts.py
# gives for refusing an unknown evidence label rather than storing it.
PAGE_VIEW = "page_view"
BET_CHECK_RUN = "bet_check_run"
BET_SAVED = "bet_saved"
INVITE_REDEEMED = "invite_redeemed"

EVENT_KINDS = frozenset({PAGE_VIEW, BET_CHECK_RUN, BET_SAVED, INVITE_REDEEMED})


def db_path() -> Path:
    override = (os.environ.get(ENV_DB_PATH) or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return paths.repo_root() / "data" / "app" / "app.db"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_user_id(user_id) -> str:
    """The only form of a user identity this module ever stores or accepts.

    Takes whatever raw identifier a caller has on hand (an int user id, a
    string, ...) and returns its full sha256 hex digest -- irreversible in
    practice, same guarantee src/appstate/reqlog.py's `user_ref` relies on
    for log-line correlation. Callers pass the RAW id here and use the
    result everywhere else; this function is the one and only place the raw
    value is allowed to exist as an argument.
    """
    if user_id is None:
        raise ValueError("an event needs a user to hash -- pass the raw id, "
                          "not None (use a fixed sentinel string for "
                          "anonymous events if one is ever needed)")
    return hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()


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
        CREATE TABLE IF NOT EXISTS analytics_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_hash TEXT NOT NULL,
            kind TEXT NOT NULL,
            properties_json TEXT,
            at TEXT NOT NULL
        )
    """)


@dataclass(frozen=True)
class AnalyticsEvent:
    id: int
    user_hash: str
    kind: str
    properties: dict
    at: str


def _row_to_event(row: sqlite3.Row) -> AnalyticsEvent:
    raw = row["properties_json"]
    return AnalyticsEvent(id=row["id"], user_hash=row["user_hash"],
                          kind=row["kind"],
                          properties=json.loads(raw) if raw else {},
                          at=row["at"])


def record_event(user_hash: str, kind: str, properties: Optional[dict] = None,
                 *, at: Optional[str] = None,
                 db: Optional[Path] = None) -> AnalyticsEvent:
    """Append one analytics event. Never updates or deletes -- an event log
    that can be rewritten in place is not a log, same append-only reasoning
    src/appstate/savedbets.py gives for saved bets.

    `user_hash` MUST already be a hash (call `hash_user_id` first) -- this
    function refuses anything that is not a 64-char hex sha256 digest, so a
    raw id passed by mistake fails loud here rather than landing in the
    database once and being unrecoverable without a full-table scrub.
    """
    if kind not in EVENT_KINDS:
        raise ValueError(
            f"unknown event kind {kind!r}; must be one of {sorted(EVENT_KINDS)}")
    if not user_hash or len(user_hash) != 64 or \
            any(ch not in "0123456789abcdef" for ch in user_hash.lower()):
        raise ValueError(
            "user_hash must be a sha256 hex digest (call hash_user_id() on "
            "the raw id first) -- record_event never accepts a raw id")
    at = at or _now_iso()
    properties_json = json.dumps(properties or {}, sort_keys=True)
    with _connect(db) as conn:
        cur = conn.execute(
            "INSERT INTO analytics_events (user_hash, kind, properties_json, at) "
            "VALUES (?, ?, ?, ?)",
            (user_hash, kind, properties_json, at))
        return AnalyticsEvent(id=cur.lastrowid, user_hash=user_hash, kind=kind,
                              properties=properties or {}, at=at)


def list_events(*, db: Optional[Path] = None) -> List[AnalyticsEvent]:
    """Every recorded event, oldest first. Small-table debugging/testing
    helper -- the admin view wants `daily_counts_by_kind`, not this."""
    with _connect(db) as conn:
        rows = conn.execute(
            "SELECT * FROM analytics_events ORDER BY at ASC").fetchall()
        return [_row_to_event(r) for r in rows]


def daily_counts_by_kind(*, db: Optional[Path] = None) -> Dict[str, Dict[str, int]]:
    """Aggregate for a future admin view: {date_iso: {kind: count}}.

    Computed in Python over `list_events()` rather than a SQL GROUP BY on a
    sliced `at` string -- this table is small (a private beta, not a
    high-volume product) and a plain dict is trivial to unit-test and to
    hand to a template without a second SQL dialect to get right. If this
    table ever needs to aggregate millions of rows, move the grouping into
    SQL then; doing it now would be optimising for a scale this product
    does not have yet.
    """
    out: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for event in list_events(db=db):
        day = event.at[:10]  # ISO-8601 date prefix, valid for any at we wrote
        out[day][event.kind] += 1
    return {day: dict(kinds) for day, kinds in out.items()}
