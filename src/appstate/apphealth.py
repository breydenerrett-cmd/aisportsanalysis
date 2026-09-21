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
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src import paths
from src.appstate import users as users_store
from src.pipeline import store_archive

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
    status: str  # "ok" | "empty" | "missing" | "unreadable" | "archived_only"
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


# SCAN RESULTS, KEYED ON THE FILE'S OWN FINGERPRINT.
#
# THIS MODULE'S DOCSTRING SAYS /health "must answer with near-zero latency,
# because it is the thing a host's load balancer or uptime checker polls every
# few seconds." It did not. Measured on the live container 2026-09-11:
# 1,087-1,212ms, warm, with nothing else in flight.
#
# The cause is `_newest_timestamp` below, which reads and JSON-parses EVERY
# LINE of every store to find the newest one -- 123,182 rows and about 40 MB
# per call. Fly polls /health every 30 seconds, so that was roughly a second
# of CPU burned every thirty, continuously, on a shared vCPU with a quota.
# That background burn is a large part of why everything else on the box was
# being throttled.
#
# The stores are append-only and only change when a capture runs (~every 30
# minutes). So the scan is memoised on (size, mtime_ns): unchanged file,
# cached answer, no read at all. A changed file costs exactly one scan. Fly's
# 120 polls an hour go from 120 scans to about 2.
#
# KEYED ON THE FINGERPRINT RATHER THAN A TTL ON PURPOSE. A TTL would still
# rescan on a timer whether or not anything moved, and -- worse -- could serve
# a stale "newest row" for its whole window, which is the one number this
# check exists to report. Size-and-mtime changes the instant an append lands.
_SCAN_CACHE: dict = {}


def _newest_timestamp(path: Path, field_name: str) -> tuple:
    """Scan a JSONL store for its newest parseable timestamp.

    Returns (rows_counted, newest_datetime_or_None). A corrupt line, like
    src/pipeline/health.py's _read_jsonl, costs that one row rather than the
    whole store -- an interrupted append is the normal signature of a killed
    collector, not proof the rest of the file is unusable.

    Memoised on the file's size and mtime -- see `_SCAN_CACHE` above.

    DELIBERATELY SCANS THE HOT FILE ONLY, NOT THE LOGICAL STORE
    --------------------------------------------------------------
    src.pipeline.store_archive (2026-09-21, the 100MB-push incident) moves
    only the PREFIX of a store older than its keep-window into cold gzip
    segments -- the newest row is, by construction, always still in the hot
    file, UNLESS every row in the store has been rotated (a hot file over
    threshold with nothing captured for `keep_days`, which `check_store`
    below handles as its own "archived_only" case rather than assuming this
    function's `rows == 0` always means genuinely empty; see the 2026-09-21
    review note on that branch). Short of that edge case, this function
    answers "how old is the newest row", which the hot file alone always
    answers correctly, and this exact module's docstring records the
    incident that makes reading more than that a regression: a
    full-store rescan on every /health poll (Fly, every 30s) measured
    1,087-1,212ms and starved everything else on a shared vCPU (see the
    `_SCAN_CACHE` block above) BEFORE this file's mtime-fingerprint cache was
    added. Rescanning every gzip segment on every cache miss would put that
    same cost back for a number the archive can never change the answer to.
    `check_store`'s presence check below still calls `store_archive.exists`,
    so a store that has been rotated hard enough to leave an EMPTY hot file
    is still reported present, not "missing" -- only the age/count scan
    itself stays on the hot file.
    """
    try:
        stat = path.stat()
        fingerprint = (str(path), stat.st_size, stat.st_mtime_ns, field_name)
    except OSError:
        # Cannot stat it: fall through and let the open() below raise the
        # error the caller already knows how to report.
        fingerprint = None

    if fingerprint is not None:
        cached = _SCAN_CACHE.get(fingerprint)
        if cached is not None:
            return cached

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

    if fingerprint is not None:
        # ONE ENTRY PER STORE, not one per scan. The key carries the size and
        # mtime, so a growing file would otherwise leave a copy of every
        # version it ever had in memory -- a slow leak on a long-lived
        # process, in the module whose job is to notice that sort of thing.
        for stale in [k for k in _SCAN_CACHE
                      if k[0] == str(path) and k[3] == field_name]:
            del _SCAN_CACHE[stale]
        _SCAN_CACHE[fingerprint] = (rows, newest)
    return rows, newest


def check_store(path: Path, timestamp_field: str, *,
                 now: Optional[datetime] = None) -> StoreCheck:
    """Presence, row count, and newest-row age for one JSONL store.

    `now` is injectable so tests can assert an exact age instead of racing
    the wall clock (the pattern api/today.py's odds_meta ageing already
    uses).

    Presence is `store_archive.exists` (hot file OR archive segments), not a
    bare `path.exists()` -- a store rotated hard enough to leave its hot file
    empty or absent (src.pipeline.store_archive, 2026-09-21 incident) still
    holds real history and must not be reported "missing". `_newest_timestamp`
    itself stays hot-file-only on purpose (see its own docstring); the
    genuinely rare case of a rotation leaving NO hot file at all (every row
    archived, none captured since) is reported honestly below rather than
    either fabricated as "empty" (0 rows -- false; the store has history) or
    crashed into "unreadable" (the hot file legitimately does not exist,
    that is not an I/O error).
    """
    now = now or datetime.now(timezone.utc)
    if not store_archive.exists(path):
        return StoreCheck(present=False, rows=None, newest_row_age_seconds=None,
                          newest_row_utc=None, status="missing",
                          reason=f"{path.name} is absent -- nothing has been "
                                 "captured yet, or the volume is not mounted")
    if not path.exists():
        return StoreCheck(present=True, rows=None, newest_row_age_seconds=None,
                          newest_row_utc=None, status="archived_only",
                          reason=f"{path.name} has no hot file (fully rotated "
                                 "to cold storage); its history is in "
                                 f"{store_archive.segment_dir(path)}, but "
                                 "nothing has been captured since the last "
                                 "rotation")
    try:
        rows, newest = _newest_timestamp(path, timestamp_field)
    except OSError as exc:
        return StoreCheck(present=True, rows=None, newest_row_age_seconds=None,
                          newest_row_utc=None, status="unreadable",
                          reason=f"{path.name} could not be read: {exc}")
    if rows == 0:
        # ARCHIVED_ONLY, not "empty" (2026-09-21 review): `rotate` never
        # deletes the hot file, even when it archives every row in it -- it
        # writes the (possibly zero-byte) remaining suffix back with
        # `os.replace` (src/pipeline/store_archive.py). So the ONE real way
        # "every row rotated out" shows up here is a hot file that EXISTS,
        # is readable, and has 0 rows -- exactly the state this branch used
        # to report as "empty" (0 rows -- false; the store has history in
        # its archive segments) rather than the store's own THE HONESTY
        # RULE this module's docstring states: "a present-but-empty store
        # is not the same as an absent one". The `not path.exists()` branch
        # above is the defensive case (a hot file literally missing, e.g.
        # never created); this is the one rotation actually produces.
        if store_archive.segments(path):
            return StoreCheck(present=True, rows=0, newest_row_age_seconds=None,
                              newest_row_utc=None, status="archived_only",
                              reason=f"{path.name}'s hot file has 0 rows -- "
                                     "fully rotated to cold storage, nothing "
                                     "captured since; history is in "
                                     f"{store_archive.segment_dir(path)}")
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

    def check_checkout() -> dict:
        """Can a completed payment actually deliver access?

        `broken` means billing is switched ON and a customer who pays would
        land nowhere -- the production deploy had no PUBLIC_BASE_URL, so
        Stripe's success_url resolved to example.invalid and the only bridge
        from a payment to its access token led to a domain that does not
        exist. src.appstate.billing.create_checkout already refuses in that
        state, so nobody is charged; this exists so an operator learns about
        it from a health check rather than from a customer who tried to buy.

        Reported for the null provider too, as `off` -- a deploy with billing
        deliberately disabled is a different fact from one that is broken,
        and flattening the two would make this line useless on staging.

        Never names a secret or its value: the reason strings name the
        VARIABLE, never its contents (see module docstring).
        """
        try:
            from src.appstate import billing as _billing
            provider = (os.environ.get(_billing.ENV_BILLING_PROVIDER)
                        or _billing.DEFAULT_BILLING_PROVIDER).strip()
            if provider == _billing.DEFAULT_BILLING_PROVIDER:
                return {"status": "off", "provider": provider,
                        "reason": "billing provider is the null provider; "
                                  "no payment can be taken"}
            reason = _billing.checkout_delivery_ready()
            if reason:
                return {"status": "broken", "provider": provider,
                        "reason": reason}
            return {"status": "ok", "provider": provider, "reason": None}
        except Exception as exc:  # noqa: BLE001
            # A health check must never be the thing that 500s.
            return {"status": "unknown", "provider": None,
                    "reason": f"could not evaluate checkout readiness: {exc}"}

    db = check_app_db(db_path)
    odds = check_store(root / "processed" / "odds_multibook.jsonl",
                       ODDS_STORE_TIMESTAMP_FIELD, now=now)
    forward = {name: check_store(root / subdir / filename, field_name, now=now).to_dict()
               for name, (subdir, filename, field_name) in FORWARD_STORES.items()}

    unreadable = [name for name, data in
                  {ODDS_STORE_NAME: odds.to_dict(), **forward}.items()
                  if data["status"] == "unreadable"]
    checkout = check_checkout()
    healthy = db.reachable and not unreadable and checkout["status"] != "broken"

    reasons = []
    if not db.reachable:
        reasons.append(f"app db unreachable: {db.reason}")
    for name, data in {ODDS_STORE_NAME: odds.to_dict(), **forward}.items():
        if data["status"] == "unreadable":
            reasons.append(f"{name}: {data['reason']}")
    if checkout["status"] == "broken":
        reasons.append(f"checkout: {checkout['reason']}")

    return {
        "status": "ok" if healthy else "degraded",
        "generated_at": now.isoformat(),
        "process": {"status": "ok"},
        "app_db": db.to_dict(),
        "odds": {ODDS_STORE_NAME: odds.to_dict()},
        "forward_captures": forward,
        "checkout": checkout,
        "reasons": reasons,
    }
