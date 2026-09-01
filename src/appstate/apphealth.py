"""Process + store health for the paid-beta API's GET /health, stdlib-only.

WHY THIS IS ITS OWN MODULE, NOT INLINE IN api/health.py
---------------------------------------------------------
Same split as every other api/<->src/ boundary in this repo (api/today.py,
api/betcheck.py): the checks themselves -- is the app db reachable, how old
is the newest odds row, how old is the newest capture in each forward
store -- are plain stdlib logic (sqlite3, json, pathlib) with no FastAPI
dependency, so they stay importable and unit-testable without the web
framework installed, and tests/test_api_boundary.py's stdlib-only rule for
all of src/ stays true. api/health.py's job is only to call this and shape
the HTTP response.

WHY THIS IS DELIBERATELY NOT src/pipeline/health.py
-----------------------------------------------------
src/pipeline/health.py answers "is today's SLATE collection working" --
it fetches MLB's schedule, matches quotes to games by identity, and reports
coverage ratios. That is a data-quality question about one day's baseball,
and answering it costs a network call. This module answers a narrower,
ops-facing question -- "is the API process and its stores alive at all" --
and must answer it with zero network access and near-zero latency, because
it is the thing a host's load balancer or uptime checker polls every few
seconds. Reusing the slate monitor here would make /health slow, make it
fail on a network hiccup that has nothing to do with API health, and couple
an ops liveness check to MLB's schedule endpoint being up.

THE HONESTY RULE (same one src/pipeline/health.py states and this module
inherits without re-deriving): an absent store is not a healthy store, and
a present-but-empty store is not the same as an absent one. Every store
check below reports `present` and `newest_row_age_seconds` separately, and
`age_seconds` is None whenever there is nothing to time -- never 0, which
would read as "fresh" rather than "unknown". Nothing here fabricates a
green status; a check that could not run reports why, not "ok".
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src import paths
from src.appstate import users as users_store

# The odds store api/today.py and api/betcheck.py both price games from --
# its newest row's age is the single most useful "is the pipeline still
# feeding this API" number, so /health reports it by name rather than
# burying it in a generic list.
ODDS_STORE_NAME = "odds_multibook"
ODDS_STORE_TIMESTAMP_FIELD = "observed_utc"

# The rest of the forward-evidence stores (see src/paths.py's evidence_path
# docstring and .gitignore's "FORWARD ODDS CAPTURES ARE EVIDENCE" note for
# why these specific files are tracked rather than gitignored): each is
# unbackfillable, so a silently stalled capture here is exactly the failure
# class this endpoint exists to surface before it costs a study.
FORWARD_STORES = {
    "odds_snapshots": ("processed", "odds_snapshots.jsonl", "observed_utc"),
    "f5_close": ("processed", "f5_close.jsonl", "observed_utc"),
    "prop_listing": ("processed", "prop_listing.jsonl", "observed_utc"),
    "probables_watch": ("watch", "probables_watch.jsonl", "fetched_utc"),
    "transactions_watch": ("watch", "transactions_watch.jsonl", "fetched_utc"),
    "lineups_watch": ("watch", "lineups_watch.jsonl", "fetched_utc"),
}


@dataclass(frozen=True)
class StoreCheck:
    """One store's honest state: never a fabricated age for a store that
    cannot supply one."""
    present: bool
    rows: Optional[int]
    newest_row_age_seconds: Optional[float]
    newest_row_utc: Optional[str]
    status: str  # "ok" | "empty" | "missing" | "unreadable"
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "present": self.present,
            "rows": self.rows,
            "newest_row_age_seconds": self.newest_row_age_seconds,
            "newest_row_utc": self.newest_row_utc,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DbCheck:
    reachable: bool
    path: str
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {"reachable": self.reachable, "path": self.path,
                "reason": self.reason}


def _parse_timestamp(value) -> Optional[datetime]:
    """Best-effort ISO-8601 parse. None on anything unparseable -- a
    malformed timestamp must cost that one row, not the whole check."""
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _newest_timestamp(path: Path, field_name: str) -> tuple:
    """Scan a JSONL store for its newest parseable timestamp.

    Returns (rows_counted, newest_datetime_or_None). A corrupt line, like
    src/pipeline/health.py's _read_jsonl, costs that one row rather than the
    whole store -- an interrupted append is the normal signature of a killed
    collector, not proof the rest of the file is unusable.
    """
    rows = 0
    newest = None
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            stamp = _parse_timestamp(row.get(field_name))
            if stamp is not None and (newest is None or stamp > newest):
                newest = stamp
    return rows, newest


def check_store(path: Path, timestamp_field: str, *,
                 now: Optional[datetime] = None) -> StoreCheck:
    """Presence, row count, and newest-row age for one JSONL store.

    `now` is injectable so tests can assert an exact age instead of racing
    the wall clock (the pattern api/today.py's odds_meta ageing already
    uses).
    """
    now = now or datetime.now(timezone.utc)
    if not path.exists():
        return StoreCheck(present=False, rows=None, newest_row_age_seconds=None,
                          newest_row_utc=None, status="missing",
                          reason=f"{path.name} is absent -- nothing has been "
                                 "captured yet, or the volume is not mounted")
    try:
        rows, newest = _newest_timestamp(path, timestamp_field)
    except OSError as exc:
        return StoreCheck(present=True, rows=None, newest_row_age_seconds=None,
                          newest_row_utc=None, status="unreadable",
                          reason=f"{path.name} could not be read: {exc}")
    if rows == 0:
        return StoreCheck(present=True, rows=0, newest_row_age_seconds=None,
                          newest_row_utc=None, status="empty",
                          reason=f"{path.name} exists but holds no rows")
    if newest is None:
        return StoreCheck(present=True, rows=rows, newest_row_age_seconds=None,
                          newest_row_utc=None, status="unreadable",
                          reason=f"{path.name} holds {rows} row(s) but none carry "
                                 f"a parseable {timestamp_field}")
    age = (now - newest).total_seconds()
    return StoreCheck(present=True, rows=rows, newest_row_age_seconds=age,
                      newest_row_utc=newest.isoformat(), status="ok")


def check_app_db(db_path: Optional[Path] = None) -> DbCheck:
    """Confirm the app db can actually be opened and queried -- not just
    that a file exists at the path. A zero-byte or half-written sqlite file
    exists on disk and still fails the first real query, which is the
    failure this check exists to catch rather than a bare path.exists().
    """
    resolved = db_path or users_store.db_path()
    try:
        conn = sqlite3.connect(str(resolved))
        try:
            # sqlite3.connect() never touches the file itself -- it opens
            # lazily -- so a literal `SELECT 1` proves nothing about a
            # corrupt or non-sqlite file at this path. Querying
            # sqlite_master forces an actual page read, which is what
            # "reachable" needs to mean here.
            conn.execute("SELECT name FROM sqlite_master LIMIT 1")
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return DbCheck(reachable=False, path=str(resolved), reason=str(exc))
    return DbCheck(reachable=True, path=str(resolved))


def report(*, data_dir: Optional[Path] = None, db_path: Optional[Path] = None,
           now: Optional[datetime] = None) -> dict:
    """The full /health payload: process liveness, db reachability, the
    named odds store, and every forward-evidence store.

    `healthy` is False whenever the db is unreachable or any store that IS
    present could not be read -- a store that is simply absent or empty
    does not by itself flip the top-level flag, because a freshly
    provisioned environment or an off day legitimately has nothing there
    yet (see module docstring). Every reason a check is not "ok" still
    rides along in that check's own `reason`, so a caller who wants a
    stricter bar (e.g. "the odds store must not be missing either") reads
    it straight from the response rather than needing a second endpoint.
    """
    now = now or datetime.now(timezone.utc)
    root = Path(data_dir) if data_dir is not None else paths.data_root()

    db = check_app_db(db_path)
    odds = check_store(root / "processed" / "odds_multibook.jsonl",
                       ODDS_STORE_TIMESTAMP_FIELD, now=now)
    forward = {name: check_store(root / subdir / filename, field_name, now=now).to_dict()
               for name, (subdir, filename, field_name) in FORWARD_STORES.items()}

    unreadable = [name for name, data in
                  {ODDS_STORE_NAME: odds.to_dict(), **forward}.items()
                  if data["status"] == "unreadable"]
    healthy = db.reachable and not unreadable

    reasons = []
    if not db.reachable:
        reasons.append(f"app db unreachable: {db.reason}")
    for name, data in {ODDS_STORE_NAME: odds.to_dict(), **forward}.items():
        if data["status"] == "unreadable":
            reasons.append(f"{name}: {data['reason']}")

    return {
        "status": "ok" if healthy else "degraded",
        "generated_at": now.isoformat(),
        "process": {"status": "ok"},
        "app_db": db.to_dict(),
        "odds": {ODDS_STORE_NAME: odds.to_dict()},
        "forward_captures": forward,
        "reasons": reasons,
    }
