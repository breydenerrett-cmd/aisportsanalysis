"""The data service's in-process door: `DataClient`, and the fastapi-free core under /data/v1.

WHY THIS FILE EXISTS (2026-10-04)
---------------------------------
`/data/v1` was built as an HTTP surface and LineHound's own code is its first customer. A
consumer inside the same process that had to call it over HTTP would be calling itself, so the
routes' domain logic lives HERE, in functions of a store and some filters, and both callers use
it: `api/datasvc.py` is parameter parsing, sign-in, pagination and the error shape on top of
these functions, and `DataClient` is the same functions with no HTTP in between. `src/` may not
import `api/` (tests/test_api_boundary.py) and the Linux CI has no FastAPI, so nothing here
imports it.

What is in this file, top to bottom:

  1. errors, the locked stores and the store holders. `holder` and `nfl_holder` are THE
     process's one UFC and one NFL store (api/datasvc.py re-exports them): the data API, the UFC
     fight-night page and this client share them, so a process never holds two copies of a
     store. Production has run out of memory on whole-store reads before.
  2. pagination, the shared lookups, projections and filters the routes use.
  3. `DataClient`, per sport: schedule and results, the one game, participants, a participant's
     history, availability, quotes, features as of a moment, and the matchup evidence packet.

THE SHAPE OF AN ANSWER
----------------------
A capability returns one of two things and never anything in between:

    {"available": True,  "sport", "kind", "data" (sport-specific, never forced into a common
                         shape), "page" (a list), "meta"}
    {"available": False, "missing": [{"item", "reason"}, ...]}

A capability whose data is absent, unreadable, unknown (an id the store has never seen) or
ambiguous (a name that fits two people equally) is the second form, with the reason. Never a
zero where there is no number, never a made-up name, never a fresh timestamp on old data: the
only clocks in an answer are `built_utc` (when this answer was assembled) and a record's own
`fetched_utc` / the manifest's `generated_utc` (when WE observed it). A caller that passes a
bad parameter (a bad date, an unknown status) gets `DataError` with status 422, as over HTTP.

`meta` (docs/datasvc/CLIENT.md) carries, for every packet: stable ids and the provider id
mapping, units, each source's identity and our observation time, coverage and freshness,
explicit missing reasons, a `data_version`, and for every dataset whether its historical values
were OBSERVED at the time or RECONSTRUCTED later, said truthfully per dataset
(`BASIS`): for example NFL closing lines are one value per game, not a point-in-time
observation.

`data_version` is a stable hash of the version of every file the packet was built from. A file
that the store's MANIFEST.json describes (same byte size) is identified by its sha256, so the
version is the same on every machine holding the same bytes; a file with no usable manifest entry
is identified by (size, modification time), which is stable only on one machine, and `meta` says
which kind each file was. A packet is built from ONE snapshot and the files are stat()ed again
afterwards: if any changed during the build the packet is built again, and if they keep changing
the answer is "unavailable", never a mix of two versions.
"""

from __future__ import annotations

import base64
import bisect
import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from src.datasvc import names
from src.datasvc.nfl import features as nfl_features
from src.datasvc.nfl import matchup as nfl_matchup
from src.datasvc.nfl import store as nfl_store
from src.datasvc.nfl.store import NflStore
from src.datasvc.ufc import features as features_mod
from src.datasvc.ufc import matchup as matchup_mod
from src.datasvc.ufc import store as ufc_store
from src.datasvc.ufc.store import UfcStore
from src.sports import nfl_teams

EVENT_STATUSES = ("scheduled", "in_progress", "final", "canceled", "postponed", "unknown")
GAME_STATUSES = ("scheduled", "in_progress", "final", "no_result", "removed")
GAME_TYPES = ("REG", "WC", "DIV", "CON", "SB")
DEFAULT_LIMIT = 50

# /upcoming lists events that have not finished. One that started up to this long ago is
# still "tonight's card" (a card runs for hours and the status flips late); a "scheduled"
# event older than that is a stale row, not an upcoming one, and is left out.
UPCOMING_GRACE = timedelta(hours=36)

# The largest page the in-process client serves. Over HTTP the caller's tier decides this
# (api/datasvc.py); in process there is no tier, and a bound still keeps one call's answer finite.
CLIENT_MAX_LIMIT = 1000


def _now() -> datetime:
    return datetime.now(timezone.utc)


# -- errors ---------------------------------------------------------------------------------

class DataError(Exception):
    """A refusal with an HTTP-shaped status, a code and a message.

    api/datasvc.py's `ApiError` IS this class, so a route handler and the client raise one
    thing and the route class turns it into the one error shape.
    """

    def __init__(self, status: int, code: str, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


class DataUnavailable(Exception):
    """A dataset file exists but cannot be read (a corrupt line, a permission error)."""

    def __init__(self, dataset: str):
        super().__init__(dataset)
        self.dataset = dataset


class SnapshotUnstable(Exception):
    """The files kept changing while one answer was being built, so no single version could be named."""


def _bad_param(param: str, message: str) -> DataError:
    return DataError(422, "invalid_parameter", f"invalid parameter '{param}': {message}",
                     {"errors": [{"in": "query", "param": param, "message": message}]})


def _not_found(kind: str, ident: str) -> DataError:
    return DataError(404, "not_found", f"no {kind} with id {ident!r} in the store")


# -- the stores, loaded once ---------------------------------------------------------------------

class _LockedMixin:
    """Makes a dataset store (UFC or NFL) safe to share between request threads.

    The foundation's stores load lazily and are written for one thread: two requests
    arriving together would both read the same file and both build the same index.
    Loading and indexing here take a lock (re-checked inside it), so each dataset is read
    once per store version however many requests ask for it at once. Reads of what is
    already loaded take no lock. Read failures become `DataUnavailable` so a corrupt
    line is a 503 and not a 500 with a server path in it, and a failure is remembered
    for this store version: otherwise every request would re-parse a large corrupt file
    up to its bad line, the whole-store-read-per-request pattern in the one situation
    where it hurts most. The holder swaps in a fresh store when the file changes, which
    is when it is worth trying again.
    """

    def __init__(self, root: Optional[Path] = None):
        super().__init__(root)
        self._lock = threading.RLock()
        self._views: Dict[str, Any] = {}
        self._failed: Dict[str, BaseException] = {}

    def load(self, name: str) -> list:
        if name in self._cache:
            return self._cache[name]
        with self._lock:
            if name in self._failed:
                raise DataUnavailable(name) from self._failed[name]
            try:
                return super().load(name)
            except (OSError, ValueError) as exc:
                self._failed[name] = exc
                raise DataUnavailable(name) from exc

    def _index(self, name: str, build):
        if name in self._indexes:
            return self._indexes[name]
        with self._lock:
            return super()._index(name, build)

    def view(self, name: str, build: Callable[[], Any]) -> Any:
        """A value derived from this store version (a sorted list, a name index), built once."""
        if name in self._views:
            return self._views[name]
        with self._lock:
            if name not in self._views:
                self._views[name] = build()
            return self._views[name]


class _LockedStore(_LockedMixin, UfcStore):
    """A UfcStore safe to share between request threads (see `_LockedMixin`)."""


class _LockedNflStore(_LockedMixin, NflStore):
    """An NflStore safe to share between request threads (see `_LockedMixin`)."""


@dataclass(frozen=True)
class Snapshot:
    """One store and the version of the files it was opened on, taken together."""
    store: Any
    signature: tuple
    version: dict


def _digest(parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


class _BaseHolder:
    """The one store of a process for one sport, replaced only when a dataset file changes on disk.

    A subclass names the sport's files, date fields, store class and default directory.
    """

    files: Dict[str, str] = {}
    date_fields: Dict[str, str] = {}
    store_class: Any = None

    @staticmethod
    def counts_toward_newest(name: str, row: dict) -> bool:
        return True

    @staticmethod
    def default_root() -> Path:
        raise NotImplementedError

    def __init__(self, root: Optional[Path] = None, clock: Optional[Callable[[], datetime]] = None):
        self._lock = threading.Lock()
        # Late-bound so a deployment or a test can move the clock after the holder exists.
        self.clock: Callable[[], datetime] = clock or _now
        self.set_root(root)

    def set_root(self, root: Optional[Path]) -> None:
        with self._lock:
            self._root = Path(root) if root is not None else self.default_root()
            self._current: Optional[Tuple[tuple, Any]] = None
            self._loaded_utc: Optional[str] = None
            self._status: Dict[str, tuple] = {}
            self._manifest: Tuple[Optional[tuple], dict] = (None, {})
            self._version: Optional[Tuple[tuple, dict]] = None
            self.reloads = 0

    @property
    def root(self) -> Path:
        return self._root

    def _file_signature(self) -> tuple:
        """(name, modification time in ns, size) per dataset file; None for a file that is absent.

        Size rides along with the modification time because a filesystem with coarse
        timestamps can show the same mtime for two writes made close together.
        """
        sig = []
        for name, filename in self.files.items():
            try:
                st = (self._root / filename).stat()
                sig.append((name, st.st_mtime_ns, st.st_size))
            except OSError:
                sig.append((name, None, None))
        return tuple(sig)

    def store(self):
        """The current store, replaced first if any dataset file changed since it was made."""
        return self.snapshot().store

    def snapshot(self) -> Snapshot:
        """The current store with the version of the files it was opened on."""
        sig = self._file_signature()
        current = self._current
        if current is None or current[0] != sig:
            with self._lock:
                sig = self._file_signature()
                if self._current is None or self._current[0] != sig:
                    self._current = (sig, self.store_class(self._root))
                    self._loaded_utc = features_mod.iso_utc(self.clock())
                    self.reloads += 1
                current = self._current
        return Snapshot(current[1], current[0], self._version_for(current[0]))

    def signature(self) -> tuple:
        """The files' signature now, for a caller checking that a build did not straddle a change."""
        return self._file_signature()

    def info(self) -> dict:
        return {"store_loaded_utc": self._loaded_utc, "reloads": self.reloads}

    # -- the version of the files -------------------------------------------------------

    def _version_for(self, sig: tuple) -> dict:
        """{"data_version", "files": {dataset: {"token", "kind"}}} for a file signature, cached by it."""
        cached = self._version
        if cached is not None and cached[0] == sig:
            return cached[1]
        manifest, _ = self._manifest_files()
        files, parts = {}, []
        for name, mtime, size in sig:
            entry = manifest.get(self.files[name]) if isinstance(manifest, dict) else None
            if mtime is None:
                token, kind = "absent", "absent"
            elif isinstance(entry, dict) and entry.get("sha256") and entry.get("bytes") == size:
                token, kind = f"sha256:{entry['sha256']}", "content_hash_from_manifest"
            else:
                token, kind = f"sig:{size}:{mtime}", "size_and_mtime_on_this_machine"
            files[name] = {"token": token, "kind": kind}
            parts.append([name, token])
        version = {"data_version": "dv1-" + _digest(parts)[:24], "files": files}
        with self._lock:
            self._version = (sig, version)
        return version

    def consistent(self, build: Callable[[Any], Any], attempts: int = 3) -> Tuple[Any, Snapshot]:
        """`build(store)` over one snapshot, rebuilt if a file changed while it ran.

        The stat() before and after is cheap; the point is the promise in the module docstring:
        an answer never mixes two versions of the files.
        """
        for _ in range(attempts):
            snap = self.snapshot()
            value = build(snap.store)
            if self._file_signature() == snap.signature:
                return value, snap
        raise SnapshotUnstable(f"the {type(self).__name__} files changed on every one of {attempts} attempts")

    # -- /status: counts and newest dates without loading the datasets -------------------

    def _manifest_files(self) -> Tuple[dict, Optional[str]]:
        path = self._root / "MANIFEST.json"
        try:
            st = path.stat()
        except OSError:
            return {}, None
        sig = (st.st_mtime_ns, st.st_size)
        with self._lock:
            if self._manifest[0] != sig:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    data = data if isinstance(data, dict) else {}
                except (OSError, ValueError):
                    data = {}
                self._manifest = (sig, data)
            data = self._manifest[1]
        return (data.get("files") or {}), data.get("generated_utc")

    def _measure(self, name: str, path: Path, size: int) -> dict:
        """Records and newest date: the manifest if it describes this very file, else one scan."""
        files, _ = self._manifest_files()
        entry = files.get(self.files[name])
        if isinstance(entry, dict) and entry.get("bytes") == size and "records" in entry:
            return {"records": entry["records"], "newest": entry.get("newest"), "source": "manifest"}
        field = self.date_fields.get(name)
        records, newest = 0, None
        try:
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    records += 1
                    value = row.get(field) if field and isinstance(row, dict) else None
                    if value and self.counts_toward_newest(name, row) and (newest is None or value > newest):
                        newest = value
        except (OSError, ValueError) as exc:
            raise DataUnavailable(name) from exc
        return {"records": records, "newest": newest, "source": "files"}

    def dataset_status(self, name: str, now: datetime) -> dict:
        filename = self.files[name]
        path = self._root / filename
        base = {"file": filename, "newest_field": self.date_fields.get(name)}
        try:
            st = path.stat()
        except OSError:
            return {**base, "present": False, "records": 0, "newest": None, "bytes": None,
                    "age_seconds": None, "age_days": None, "source": None}
        sig = (st.st_mtime_ns, st.st_size)
        with self._lock:
            cached = self._status.get(name)
        if cached is None or cached[0] != sig:
            info = self._measure(name, path, st.st_size)
            with self._lock:
                self._status[name] = (sig, info)
        else:
            info = cached[1]
        age = None
        newest = features_mod.instant(info["newest"])
        if newest is not None:
            age = int((now - newest).total_seconds())
        return {**base, "present": True, "records": info["records"], "newest": info["newest"],
                "bytes": st.st_size, "age_seconds": age,
                "age_days": None if age is None else round(age / 86400.0, 2), "source": info["source"]}

    def manifest_generated_utc(self) -> Optional[str]:
        return self._manifest_files()[1]

    def manifest_extra(self, key: str) -> Any:
        """A top-level value of MANIFEST.json other than the file table (attribution, coverage), or None."""
        self._manifest_files()
        return self._manifest[1].get(key)


class StoreHolder(_BaseHolder):
    """The UFC store of a process."""

    files = ufc_store.FILES
    date_fields = ufc_store.DATE_FIELDS
    store_class = _LockedStore
    counts_toward_newest = staticmethod(ufc_store.counts_toward_newest)

    @staticmethod
    def default_root() -> Path:
        return ufc_store.DEFAULT_DIR


class NflStoreHolder(_BaseHolder):
    """The NFL store of a process."""

    files = nfl_store.FILES
    date_fields = nfl_store.DATE_FIELDS
    store_class = _LockedNflStore
    counts_toward_newest = staticmethod(nfl_store.counts_toward_newest)

    @staticmethod
    def default_root() -> Path:
        return nfl_store.DEFAULT_DIR


holder = StoreHolder()
nfl_holder = NflStoreHolder()


# -- pagination ------------------------------------------------------------------------------

def _query_sig(**params: Any) -> str:
    """A short fingerprint of a query's filters, so a cursor cannot be replayed against another query."""
    blob = json.dumps(params, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:8]


def encode_cursor(sig: str, key: Sequence[str]) -> str:
    raw = json.dumps({"q": sig, "k": list(key)}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str, sig: str) -> Tuple[str, ...]:
    bad = DataError(422, "invalid_cursor", "the cursor is not one this API issued; start again without one")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        key, query = data["k"], data["q"]
        if not isinstance(key, list) or not key or not all(isinstance(x, str) for x in key):
            raise ValueError("bad key")
    except (ValueError, KeyError, TypeError) as exc:
        raise bad from exc
    if query != sig:
        raise DataError(422, "invalid_cursor",
                        "the cursor belongs to a different query (other filters or order); start again without one")
    return tuple(key)


def paginate(items: Sequence[Any], key_fn: Callable[[Any], Tuple[str, ...]], *, limit: int,
             cursor: Optional[str], sig: str, descending: bool) -> Tuple[list, Optional[str]]:
    """One page of `items` (sorted ascending by `key_fn`) and the cursor for the next, or None.

    Keyset, not offset: the cursor holds the sort key of the last item served, so a page
    never repeats or skips a row when the data changes between requests.
    """
    keys = [key_fn(i) for i in items]
    after = decode_cursor(cursor, sig) if cursor else None
    if descending:
        end = len(items) if after is None else bisect.bisect_left(keys, after)
        start = max(0, end - limit)
        page = list(items[start:end])[::-1]
        more = start > 0
    else:
        start = 0 if after is None else bisect.bisect_right(keys, after)
        page = list(items[start:start + limit])
        more = start + limit < len(items)
    return page, (encode_cursor(sig, key_fn(page[-1])) if page and more else None)


def page_response(items: Sequence[Any], key_fn, max_limit: int, limit: int, cursor: Optional[str],
                  sig: str, *, descending: bool, render: Callable[[Any], dict]) -> dict:
    effective = min(limit, max_limit)
    page, next_cursor = paginate(items, key_fn, limit=effective, cursor=cursor, sig=sig, descending=descending)
    return {"data": [render(i) for i in page],
            "page": {"limit": effective, "count": len(page), "total": len(items), "next_cursor": next_cursor}}


def _date_key(text: Any) -> str:
    """A sortable form of a stored date: UTC ISO to the second when readable, else the raw text."""
    inst = features_mod.instant(text)
    return features_mod.iso_utc(inst) if inst is not None else (text if isinstance(text, str) else "")


def order_is_descending(order: str) -> bool:
    if order not in ("asc", "desc"):
        raise _bad_param("order", "must be asc or desc")
    return order == "desc"


def parse_as_of(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    try:
        return features_mod.parse_instant(value)
    except ValueError:
        raise DataError(422, "invalid_parameter",
                        "invalid parameter 'as_of': must be an ISO date (2026-10-03) or datetime "
                        "(2026-10-03T21:00Z; URL-encode a + offset as %2B)",
                        {"errors": [{"in": "query", "param": "as_of", "message": "not an ISO date or datetime"}]})


def choice(value: Optional[str], param: str, allowed: Sequence[str]) -> Optional[str]:
    if value is not None and value not in allowed:
        raise _bad_param(param, f"must be one of {', '.join(allowed)}")
    return value


# -- UFC: lookups, projections and the lists the routes serve -----------------------------------

def fighter_ref(store, fighter_id: Optional[str]) -> Optional[dict]:
    if not fighter_id:
        return None
    return {"fighter_id": fighter_id, "name": (store.fighter_by_id().get(fighter_id) or {}).get("name")}


def fighter_summary(f: dict) -> dict:
    return {"fighter_id": f.get("fighter_id"), "name": f.get("name"), "nickname": f.get("nickname"),
            "weight_class": f.get("weight_class"), "stance": f.get("stance"), "dob": f.get("dob"),
            "active": f.get("active"), "record": f.get("record")}


def event_summary(e: dict) -> dict:
    return {"event_id": e.get("event_id"), "name": e.get("name"), "short_name": e.get("short_name"),
            "date_utc": e.get("date_utc"), "season": e.get("season"), "status": e.get("status"),
            "venue_id": e.get("venue_id"), "bout_count": len(e.get("bout_ids") or [])}


def bout_with_names(store, bout: dict) -> dict:
    return {**bout, "fighter_a": fighter_ref(store, bout.get("fighter_a_id")),
            "fighter_b": fighter_ref(store, bout.get("fighter_b_id"))}


def result_block(store, bout: dict) -> Optional[dict]:
    winner, method = bout.get("winner_id"), bout.get("result_method")
    if not winner and method not in ("DRAW", "NC"):
        return None
    loser = None
    if winner:
        loser = bout.get("fighter_b_id") if winner == bout.get("fighter_a_id") else bout.get("fighter_a_id")
    return {
        "outcome": "decided" if winner else ("draw" if method == "DRAW" else "no_contest"),
        "winner_id": winner, "winner_name": (fighter_ref(store, winner) or {}).get("name"),
        "loser_id": loser, "loser_name": (fighter_ref(store, loser) or {}).get("name"),
        "method": method, "method_raw": bout.get("result_method_raw"), "detail": bout.get("result_detail"),
        "target": bout.get("result_target"), "end_round": bout.get("end_round"),
        "end_time_s": bout.get("end_time_s"), "fight_time_s": bout.get("fight_time_s"),
    }


def ufc_people(store) -> Dict[str, List[str]]:
    """fighter_id -> every name it may be searched by, for names.match."""
    def build():
        out = {}
        for f in store.fighters:
            label = f.get("name") or " ".join(p for p in (f.get("first_name"), f.get("last_name")) if p)
            variants = [label] + [a for a in (f.get("aliases") or []) if isinstance(a, str)]
            variants = [v for v in variants if v]
            if variants:
                out[f["fighter_id"]] = variants
        return out
    return store.view("people", build)


def _candidate(store, pid: str, matched: str, score: float) -> dict:
    return {"fighter_id": pid, "name": (store.fighter_by_id().get(pid) or {}).get("name") or matched,
            "matched_name": matched, "score": score}


def known_fighter(store, fighter_id: str) -> bool:
    return fighter_id in store.fighter_by_id() or fighter_id in store.bouts_by_fighter()


def resolve_fighter(store, value: str, param: str) -> Tuple[str, str]:
    """A fighter id or a name to (fighter_id, how it was matched). Never guesses between equals."""
    if known_fighter(store, value):
        return value, "id"
    result = names.match(value, ufc_people(store))
    if result.best:
        return result.best, "name"
    if result.ambiguous:
        raise DataError(409, "ambiguous_name", f"{param}={value!r} matches more than one fighter equally well; "
                        "pass a fighter id", {"param": param, "query": value,
                                              "candidates": [_candidate(store, *c) for c in result.candidates]})
    raise DataError(404, "not_found", f"no fighter matches {param}={value!r}")


def ufc_events_asc(store) -> list:
    return store.view("events_asc", lambda: sorted(
        store.events, key=lambda e: (_date_key(e.get("date_utc")), str(e.get("event_id")))))


def event_year(e: dict) -> Optional[int]:
    inst = features_mod.instant(e.get("date_utc"))
    if inst is not None:
        return inst.year
    season = e.get("season")
    return season if isinstance(season, int) else None


def event_sort_key(e: dict) -> Tuple[str, str]:
    return (_date_key(e.get("date_utc")), str(e.get("event_id")))


def ufc_events(store, year: Optional[int] = None, status: Optional[str] = None) -> list:
    """Events oldest first, filtered by calendar year and status (the rows /data/v1/ufc/events pages)."""
    if status is not None and status not in EVENT_STATUSES:
        raise DataError(422, "invalid_parameter",
                        f"invalid parameter 'status': must be one of {', '.join(EVENT_STATUSES)}",
                        {"errors": [{"in": "query", "param": "status", "message": f"one of {list(EVENT_STATUSES)}"}]})
    return [e for e in ufc_events_asc(store)
            if (year is None or event_year(e) == year) and (status is None or e.get("status") == status)]


def ufc_event_detail(store, event_id: str) -> dict:
    event = store.event_by_id().get(event_id)
    if event is None:
        raise _not_found("event", event_id)
    bouts_by_id = store.bout_by_id()
    ids = event.get("bout_ids") or []
    return {"event": event,
            "bouts": [bout_with_names(store, bouts_by_id[b]) for b in ids if b in bouts_by_id],
            "missing_bout_ids": [b for b in ids if b not in bouts_by_id]}


def ufc_bout_detail(store, bout_id: str) -> dict:
    bout = store.bout_by_id().get(bout_id)
    if bout is None:
        raise _not_found("bout", bout_id)
    fighters = store.fighter_by_id()
    stats = store.stats_for()
    a, b = bout.get("fighter_a_id"), bout.get("fighter_b_id")
    event = store.event_by_id().get(bout.get("event_id"))
    return {"bout": bout,
            "event": event_summary(event) if event else None,
            "fighters": {"a": fighters.get(a), "b": fighters.get(b)},
            "result": result_block(store, bout),
            "stats": [stats[(bout_id, f)] for f in (a, b) if (bout_id, f) in stats],
            "odds": list(store.odds_for_bout().get(bout_id, []))}


def ufc_fighter_search(store, search: str) -> dict:
    """The best match for a name (with the candidates), or DataError 409 / 404. Never a guess between equals."""
    result = names.match(search, ufc_people(store))
    if result.best:
        candidates = [_candidate(store, *c) for c in result.candidates]
        best = store.fighter_by_id()[result.best]
        return {"query": search,
                "match": {**fighter_summary(best), "score": candidates[0]["score"],
                          "matched_name": candidates[0]["matched_name"]},
                "candidates": candidates}
    if result.ambiguous:
        raise DataError(409, "ambiguous_name",
                        f"{search!r} matches more than one fighter equally well; pass a fighter id",
                        {"query": search, "candidates": [_candidate(store, *c) for c in result.candidates]})
    raise DataError(404, "not_found", f"no fighter matches {search!r}")


def fighter_sort_key(f: dict) -> Tuple[str, str]:
    return (names.normalise(f.get("name")), str(f.get("fighter_id")))


def ufc_fighters_by_name(store) -> list:
    return store.view("fighters_by_name", lambda: sorted(store.fighters, key=fighter_sort_key))


def ufc_fighter_detail(store, fighter_id: str) -> dict:
    fighter = store.fighter_by_id().get(fighter_id)
    if fighter is None:
        raise _not_found("fighter record", fighter_id)
    return {"fighter": fighter,
            "ufccom_profile": store.profile_for().get(fighter_id),
            "ufc_bouts_in_store": len(store.bouts_by_fighter().get(fighter_id, []))}


def fight_item(store, fighter_id: str, bout: dict) -> dict:
    a, b = bout.get("fighter_a_id"), bout.get("fighter_b_id")
    opponent = b if a == fighter_id else a
    return {
        "bout_id": bout["bout_id"], "event_id": bout.get("event_id"),
        "event_name": (store.event_by_id().get(bout.get("event_id")) or {}).get("name"),
        "date_utc": bout.get("date_utc"), "status": bout.get("status"),
        "opponent_id": opponent, "opponent_name": (fighter_ref(store, opponent) or {}).get("name"),
        "weight_class": bout.get("weight_class"), "card_segment": bout.get("card_segment"),
        "match_number": bout.get("match_number"), "scheduled_rounds": bout.get("scheduled_rounds"),
        "result": features_mod.outcome_for(bout, fighter_id), "method": bout.get("result_method"),
        "method_detail": bout.get("result_detail"), "end_round": bout.get("end_round"),
        "end_time_s": bout.get("end_time_s"), "fight_time_s": bout.get("fight_time_s"),
        "has_stats": (bout["bout_id"], fighter_id) in store.stats_for(),
    }


def bout_sort_key(b: dict) -> Tuple[str, str]:
    return (_date_key(b.get("date_utc")), str(b["bout_id"]))


def ufc_fighter_bouts(store, fighter_id: str) -> list:
    """A fighter's bouts, oldest first, upcoming ones included. DataError 404 for an id nobody has seen."""
    if not known_fighter(store, fighter_id):
        raise _not_found("fighter", fighter_id)
    return sorted(store.bouts_by_fighter().get(fighter_id, []), key=bout_sort_key)


def ufc_fighter_features(store, fighter_id: str, cutoff: datetime) -> dict:
    if not known_fighter(store, fighter_id):
        raise _not_found("fighter", fighter_id)
    return features_mod.features_as_of(store, fighter_id, cutoff)


def ufc_matchup_sheet(store, a: str, b: str, cutoff: Optional[datetime], now: datetime) -> dict:
    a_id, a_how = resolve_fighter(store, a, "a")
    b_id, b_how = resolve_fighter(store, b, "b")
    if a_id == b_id:
        raise DataError(422, "invalid_parameter", "a and b are the same fighter",
                        {"errors": [{"in": "query", "param": "b", "message": "same fighter as a"}]})
    sheet = matchup_mod.matchup(store, a_id, b_id, cutoff, now=now)
    sheet["resolved"] = {"a": {"query": a, "fighter_id": a_id, "matched_by": a_how},
                         "b": {"query": b, "fighter_id": b_id, "matched_by": b_how}}
    return sheet


def upcoming_bout(store, bout: dict) -> dict:
    a, b = bout.get("fighter_a_id"), bout.get("fighter_b_id")
    return {
        "bout_id": bout["bout_id"], "match_number": bout.get("match_number"),
        "card_segment": bout.get("card_segment"), "date_utc": bout.get("date_utc"),
        "weight_class": bout.get("weight_class"), "scheduled_rounds": bout.get("scheduled_rounds"),
        "status": bout.get("status"), "fighter_a": fighter_ref(store, a), "fighter_b": fighter_ref(store, b),
        "odds": matchup_mod.bout_odds(store, bout, a, b, detail="current"),
    }


def upcoming_event(store, e: dict) -> dict:
    bouts = store.bout_by_id()
    return {**event_summary(e), "bouts": [upcoming_bout(store, bouts[i])
                                          for i in (e.get("bout_ids") or []) if i in bouts]}


def ufc_upcoming_events(store, now: datetime, days: Optional[int] = None) -> list:
    """Scheduled or running events, soonest first, none older than the grace window."""
    horizon = None if days is None else now + timedelta(days=days)
    earliest = now - UPCOMING_GRACE
    items = []
    for e in ufc_events_asc(store):
        start = features_mod.instant(e.get("date_utc"))
        if e.get("status") not in ("scheduled", "in_progress") or start is None or start < earliest:
            continue
        if horizon is not None and start > horizon:
            continue
        items.append(e)
    return items


# -- NFL: lookups and filters ---------------------------------------------------------------------

def team_param(value: Optional[str], param: str) -> Optional[str]:
    """A team filter as an nflverse code; 422 for something that is no NFL team."""
    if value is None:
        return None
    code = nfl_teams.abbrev(value)
    if code is None:
        raise _bad_param(param, f"{value!r} is not an NFL team (a code like KC or a name like Chiefs)")
    return code


def nfl_people(store) -> Dict[str, List[str]]:
    """player_id -> the name it may be searched by, for names.match."""
    return store.view("nfl_people", lambda: {pid: [name] for pid, name in store.player_names().items() if name})


def resolve_player(store, value: str, param: str = "player") -> Tuple[str, str]:
    """A player id or a name to (player_id, how it was matched). Never guesses between equals."""
    if value in store.player_games_by_player():
        return value, "id"
    result = names.match(value, nfl_people(store))
    if result.best:
        return result.best, "name"
    if result.ambiguous:
        raise DataError(409, "ambiguous_name", f"{param}={value!r} matches more than one player equally well; "
                        "pass a player id", {"param": param, "query": value,
                                             "candidates": [{"player_id": pid, "name": name, "score": score}
                                                            for pid, name, score in result.candidates]})
    raise DataError(404, "not_found", f"no player matches {param}={value!r}")


def tg_key(row: dict) -> Tuple[str, str, str]:
    return (row.get("kickoff_utc") or "", row["game_id"], row["team"])


def pg_key(row: dict) -> Tuple[str, str, str]:
    return (row.get("kickoff_utc") or "", row["game_id"], row["player_id"])


def inj_key(row: dict) -> Tuple[str, str]:
    return (row["game_id"], row["player_id"])


def nfl_games(store, *, season=None, week=None, team=None, game_type=None, status=None) -> list:
    """Games in chronological order (the rows /data/v1/nfl/games pages). `team` is a code or a name."""
    choice(game_type, "game_type", GAME_TYPES)
    choice(status, "status", GAME_STATUSES)
    code = team_param(team, "team")
    return [g for g in store.games_sorted()
            if (season is None or g["season"] == season) and (week is None or g["week"] == week)
            and (code is None or code in (g["home_team"], g["away_team"]))
            and (game_type is None or g.get("game_type") == game_type) and (status is None or g.get("status") == status)]


def nfl_game_detail(store, game_id: str) -> dict:
    game = store.game_by_id().get(game_id)
    if game is None:
        raise _not_found("game", game_id)
    rows = store.team_game_by_key()
    return {"game": game,
            "team_games": [rows[(game_id, t)] for t in (game["home_team"], game["away_team"])
                           if (game_id, t) in rows]}


def nfl_team_games(store, *, team=None, season=None, week=None, game_type=None, status=None) -> list:
    choice(game_type, "game_type", GAME_TYPES)
    choice(status, "status", GAME_STATUSES)
    code = team_param(team, "team")
    everything = store.view("team_games_sorted", lambda: sorted(store.team_games, key=tg_key))
    return [r for r in everything
            if (code is None or r["team"] == code) and (season is None or r["season"] == season)
            and (week is None or r["week"] == week) and (game_type is None or r.get("game_type") == game_type)
            and (status is None or r.get("status") == status)]


def nfl_player_games(store, *, player=None, team=None, game_id=None, season=None, week=None,
                     position_group=None) -> Tuple[list, Optional[str]]:
    """(rows oldest first, the resolved player id). `player` is an id or a name (an id wins; a tie is a 409)."""
    choice(position_group, "position_group", nfl_store.POSITION_GROUP_ORDER)
    code = team_param(team, "team")
    pid = resolve_player(store, player)[0] if player is not None else None
    everything = store.view("player_games_sorted", lambda: sorted(store.player_games, key=pg_key))
    rows = [r for r in everything
            if (pid is None or r["player_id"] == pid) and (code is None or r["team"] == code)
            and (game_id is None or r["game_id"] == game_id) and (season is None or r["season"] == season)
            and (week is None or r["week"] == week) and (position_group is None or r.get("position_group") == position_group)]
    return rows, pid


def nfl_injuries(store, *, game_id=None, team=None, season=None, week=None, player_id=None,
                 position_group=None, report_status=None) -> list:
    choice(position_group, "position_group", nfl_store.POSITION_GROUP_ORDER)
    code = team_param(team, "team")
    everything = store.view("injuries_sorted", lambda: sorted(store.injuries, key=inj_key))
    return [r for r in everything
            if (game_id is None or r["game_id"] == game_id) and (code is None or r["team"] == code)
            and (season is None or r["season"] == season) and (week is None or r["week"] == week)
            and (player_id is None or r["player_id"] == player_id)
            and (position_group is None or r.get("position_group") == position_group)
            and (report_status is None or r.get("report_status") == report_status.lower())]


def nfl_matchup_sheet(store, *, game_id=None, a=None, b=None, season=None, week=None,
                      cutoff: Optional[datetime] = None, now: Optional[datetime] = None) -> dict:
    """`game_id`, or `a` and `b` (team codes or names, either of them home): the next game between them that
    has not kicked off, else the latest (`season` and `week` pick one). `as_of` defaults to the kickoff and
    may not be later than it."""
    if game_id is None and (a is None or b is None):
        raise _bad_param("game_id", "give game_id, or both a and b (the two teams)")
    resolved: Dict[str, Any] = {}
    now = now or _now()
    try:
        if game_id is None:
            game = nfl_matchup.find_game(store, a, b, season=season, week=week, now=now)
            game_id = game["game_id"]
            resolved = {"a": a, "b": b, "game_id": game_id, "matched_by": "teams"}
        else:
            resolved = {"game_id": game_id, "matched_by": "game_id"}
        sheet = nfl_matchup.matchup(store, game_id, cutoff, now=now)
    except nfl_features.UnknownGame:
        raise _not_found("game", game_id) from None
    except nfl_features.UnknownTeam as exc:
        raise DataError(404, "not_found", str(exc)) from None
    except LookupError as exc:
        raise DataError(404, "not_found", str(exc)) from None
    except ValueError as exc:
        param = "b" if "does not play itself" in str(exc) else "as_of"
        raise _bad_param(param, str(exc)) from None
    sheet["resolved"] = resolved
    return sheet


def nfl_team_features_as_of(store, team: str, cutoff: datetime, season: Optional[int] = None) -> dict:
    try:
        return nfl_features.team_features_as_of(store, team, cutoff, season=season)
    except nfl_features.UnknownTeam:
        raise _not_found("team", team) from None


def nfl_player_features_as_of(store, player: str, cutoff: datetime) -> dict:
    pid, how = resolve_player(store, player, "player")
    try:
        data = nfl_features.player_features_as_of(store, pid, cutoff)
    except nfl_features.UnknownPlayer:
        raise _not_found("player", pid) from None
    data["resolved"] = {"query": player, "player_id": pid, "matched_by": how}
    return data


# -- provenance: where each dataset comes from and how its history was obtained -------------------------
#
# `basis` answers one question per dataset, truthfully: was a historical value OBSERVED by us at the time
# (our own forward capture, stamped with when we saw it), RECONSTRUCTED later (fetched or derived after the
# fact, so an old row says what the source says now, not what was knowable then), or a SINGLE VALUE per
# record that the source overwrites (so there is no point-in-time observation at all). A leakage-free
# FEATURE is built on top of these by filtering on dates; that rule is the feature module's, and a dataset
# marked reconstructed here is still safe to use as-of by its record dates. The basis is about what a value
# MEANS, not whether it may be used.

OBSERVED = "observed_at_the_time"
RECONSTRUCTED = "reconstructed_later"
SINGLE_VALUE = "single_value_per_record"

BASIS: Dict[str, Dict[str, dict]] = {
    "ufc": {
        "events": {"source": "ESPN public JSON (core API)", "basis": RECONSTRUCTED,
                   "note": "cards and their status as ESPN lists them when we fetched; a past card is read after "
                           "it happened, a future card is a schedule that can change"},
        "bouts": {"source": "ESPN public JSON (core API)", "basis": RECONSTRUCTED,
                  "note": "bouts, results and finish times are read after the fight; the booked card order of a "
                          "future bout can change"},
        "fighters": {"source": "ESPN public JSON (core API)", "basis": SINGLE_VALUE,
                     "note": "one record per fighter as of its fetched_utc (record, reach, age, stance): not an "
                             "as-of-bout value, never used by the leakage-free features"},
        "fight_stats": {"source": "ESPN public JSON (core API)", "basis": RECONSTRUCTED,
                        "note": "per-fight statistics are fetched after the bout; control time is recorded from "
                                "about 2018 on (zero before)"},
        "odds": {"source": "ESPN public JSON (core API), DraftKings and other providers ESPN carries",
                 "basis": RECONSTRUCTED,
                 "note": "open, close and current as the provider reports them when we fetched; for a finished "
                         "bout the close was read after the fight (is_closing marks it), so these are NOT our own "
                         "point-in-time captures and never as-of-safe"},
        "ufccom_profiles": {"source": "UFC.com athlete pages", "basis": SINGLE_VALUE,
                            "note": "career figures as the page showed them when fetched; they include every "
                                    "fight up to the fetch and feed nothing where leakage matters"},
    },
    "nfl": {
        "games": {"source": "nflverse schedules/games.csv (CC BY 4.0)", "basis": SINGLE_VALUE,
                  "note": "the schedule file's market (spread, total, moneylines) is ONE value per game that "
                          "nflverse overwrites as the market moves: the closing numbers for a final game, the "
                          "latest at fetched_utc otherwise; never an as-of-date price. The quarterback listed for "
                          "a game not yet played is a projection, replaced by the actual starter once final"},
        "team_games": {"source": "nflverse stats_team (CC BY 4.0)", "basis": RECONSTRUCTED,
                       "note": "weekly team statistics read after the games were played"},
        "player_games": {"source": "nflverse stats_player (CC BY 4.0)", "basis": RECONSTRUCTED,
                         "note": "weekly player statistics read after the games were played; a player who played "
                                 "but had no stat line has no row"},
        "injuries": {"source": "nflverse injuries (CC BY 4.0)", "basis": OBSERVED,
                     "note": "report rows with the time we first fetched each changed row (fetched_utc); the "
                             "source's own report timestamp exists only for 2009 to 2024, so for later seasons "
                             "and for backfilled rows fetched_utc is when WE saw the row, not when it was issued"},
    },
    "mlb": {
        "schedule": {"source": "MLB Stats API schedule (statsapi.mlb.com)", "basis": RECONSTRUCTED,
                     "note": "read live at observed_utc. For a game already played the probable pitcher is the "
                             "starter the schedule lists now (retroactive), not necessarily the one announced "
                             "before the game"},
        "mlb_results": {"source": "MLB Stats API schedule, ingested after each date", "basis": RECONSTRUCTED,
                        "note": "final scores and the starters' ids are written after the games finish; the starter "
                                "ids are retroactive"},
        "pitcher_logs": {"source": "MLB Stats API game logs", "basis": RECONSTRUCTED,
                         "note": "appearances accumulated after they happened; as-of use filters by appearance date"},
        "bullpen_log": {"source": "MLB Stats API box scores", "basis": RECONSTRUCTED,
                        "note": "relief workload derived after the games"},
        "lineups": {"source": "MLB Stats API posted lineups, captured by our own jobs", "basis": OBSERVED,
                    "note": "batting orders as captured when posted"},
        "standings": {"source": "MLB Stats API standings, one snapshot per day", "basis": OBSERVED,
                      "note": "daily snapshots; a date with no snapshot says so and is never filled from another"},
        "matchup_history": {"source": "MLB Stats API vsPlayer career totals", "basis": SINGLE_VALUE,
                            "note": "career totals with no as-of parameter; captured forward only, never built "
                                    "after the fact"},
        "odds_multibook": {"source": "The Odds API, our own capture", "basis": OBSERVED,
                           "note": "every quote carries the time we captured it (observed_utc) and the book's own "
                                   "last_update; the packet drops quotes captured after it was built or at or "
                                   "after first pitch"},
        "derivative_markets": {"source": "The Odds API, our own capture", "basis": OBSERVED,
                               "note": "team totals, same capture rule as the multi-book store"},
        "batter_props": {"source": "The Odds API, our own capture", "basis": OBSERVED,
                         "note": "player props, same capture rule as the multi-book store"},
        "pitcher_props": {"source": "The Odds API, our own capture", "basis": OBSERVED,
                          "note": "pitcher props, same capture rule as the multi-book store"},
        "weather_forecast": {"source": "forecast captured by our own job", "basis": OBSERVED,
                             "note": "the forecast for the game hour as captured at observed_utc"},
    },
}

UNITS = {
    "ufc": {"height": "inches", "reach": "inches", "weight": "pounds", "time": "seconds",
            "prices": "American odds", "rates": "per minute or per 15 minutes as each figure's own unit says"},
    "nfl": {"points": "points", "yards": "yards", "travel": "miles", "rest": "days", "temperature": "degrees F",
            "wind": "miles per hour", "spread": "points, nflverse sign (positive when the home team is favoured)",
            "prices": "American odds"},
    "mlb": {"prices": "American odds", "lines": "runs (run line and totals)", "temperature": "degrees F",
            "wind": "miles per hour", "time": "UTC instants (ISO 8601) unless a field says Eastern"},
}

# How old a dataset's newest record may be before a packet says it is stale. These are the dataset's own
# rhythm, not a promise: NFL's are in-season numbers (a quiet offseason will read stale, and says so with the
# figure), UFC's reflect a card roughly every one to three weeks.
ALLOWED_AGE_DAYS = {
    "ufc": {"events": 21, "bouts": 21, "odds": 21},
    "nfl": {"games": 10, "team_games": 10, "player_games": 10, "injuries": 10},
}


def _ts(moment: datetime) -> str:
    return features_mod.iso_utc(moment)


def _dataset_meta(sport: str, name: str, status: dict, version_file: dict) -> dict:
    info = BASIS[sport][name]
    limit = ALLOWED_AGE_DAYS.get(sport, {}).get(name)
    age = status.get("age_days")
    stale = None if limit is None else (None if not status.get("present") else (age is None or age > limit))
    return {"source": info["source"], "basis": info["basis"], "basis_note": info["note"],
            "present": status.get("present"), "records": status.get("records"),
            "newest": status.get("newest"), "newest_field": status.get("newest_field"),
            "age_days": age, "allowed_age_days": limit, "stale": stale,
            "version": version_file.get("token"), "version_kind": version_file.get("kind")}


def _packet_meta(sport: str, kind: str, snap: Snapshot, hold: _BaseHolder, used: Sequence[str], *,
                 ids: dict, missing: List[dict], now: datetime, extra: Optional[dict] = None) -> dict:
    """The metadata every packet carries (module docstring)."""
    datasets = {}
    for name in used:
        try:
            status = hold.dataset_status(name, now)
        except DataUnavailable:
            status = {"present": True, "records": None, "newest": None, "newest_field": hold.date_fields.get(name),
                      "age_days": None}
        datasets[name] = _dataset_meta(sport, name, status, snap.version["files"][name])
    stale = sorted(n for n, d in datasets.items() if d["stale"])
    meta = {
        "sport": sport, "kind": kind,
        "ids": ids, "units": UNITS[sport],
        "data_version": snap.version["data_version"],
        "built_utc": _ts(now),
        "observed_utc": hold.manifest_generated_utc(),
        "observed_utc_meaning": ("when our own update job last wrote these files (MANIFEST.json generated_utc); "
                                 "each record also carries its own fetched_utc"),
        "source_updated_utc": None,
        "source_updated_utc_reason": ("the source does not publish an update time we store, except injury "
                                      "report timestamps for 2009 to 2024" if sport == "nfl" else
                                      "the source does not publish an update time we store"),
        "datasets": datasets,
        "coverage": {"manifest": hold.manifest_extra("coverage"), "datasets_used": list(used),
                     "stale_datasets": stale},
        "missing": list(missing),
    }
    if hold.manifest_extra("attribution"):
        meta["attribution"] = hold.manifest_extra("attribution")
    if extra:
        meta.update(extra)
    return meta


def unavailable(*missing: Tuple[str, str], extra_items: Optional[Sequence[dict]] = None) -> dict:
    """The explicit refusal: no data, with each reason. The ONLY shape of 'nothing usable'."""
    items = [{"item": item, "reason": reason} for item, reason in missing]
    items.extend(extra_items or ())
    return {"available": False, "missing": items}


def _ok(sport: str, kind: str, data: Any, meta: dict, page: Optional[dict] = None) -> dict:
    out = {"available": True, "sport": sport, "kind": kind, "data": data}
    if page is not None:
        out["page"] = page
    out["meta"] = meta
    return out


# -- the client ---------------------------------------------------------------------------------------------

SPORTS = ("ufc", "nfl", "mlb")

CAPABILITIES: Dict[str, Dict[str, dict]] = {
    "ufc": {
        "schedule": {"available": True, "via": "events (year, status) and upcoming cards with current odds"},
        "game": {"available": True, "via": "one event with its bouts, or one bout with result, statistics and odds"},
        "participants": {"available": True, "via": "fighters, by name search or listed"},
        "history": {"available": True, "via": "a fighter's bouts, newest first"},
        "features": {"available": True, "via": "a fighter's leakage-free features as of a moment"},
        "availability": {"available": False, "reason": "the UFC store has no injury or availability dataset"},
        "quotes": {"available": True, "via": "a bout's odds as ESPN reports them (not as-of-safe)"},
        "matchup": {"available": True, "via": "the fact sheet for two fighters"},
    },
    "nfl": {
        "schedule": {"available": True, "via": "games by season, week, team, type and status"},
        "game": {"available": True, "via": "one game with both teams' rows"},
        "participants": {"available": True, "via": "teams (from the schedule) and players (from player_games)"},
        "history": {"available": True, "via": "a player's rows, or a team's rows, newest first"},
        "features": {"available": True, "via": "team form and player usage as of a moment"},
        "availability": {"available": True, "via": "injury report rows"},
        "quotes": {"available": True, "via": "the schedule file's market for a game: one value per game"},
        "matchup": {"available": True, "via": "the fact sheet for one game"},
    },
    "mlb": {
        "schedule": {"available": True, "via": "the schedule for a date, with results for final games"},
        "game": {"available": True, "via": "one game from that date's schedule"},
        "participants": {"available": True, "via": "the clubs and probable starters of a date's games"},
        "history": {"available": True, "via": "a pitcher's appearances from the pitcher log"},
        "features": {"available": False, "reason": "MLB features are built inside the analyst packet "
                                                   "(sections.starters, sections.teams), not served alone"},
        "availability": {"available": False, "reason": "no standalone availability feed: posted lineups and "
                                                       "roster news ride inside the matchup packet "
                                                       "(sections.lineups, sections.news)"},
        "quotes": {"available": True, "via": "the packet's markets, each quote with its capture time"},
        "matchup": {"available": True, "via": "the analyst's frozen evidence packet for one game"},
    },
}


class DataClient:
    """In-process access to the data service, per sport (module docstring).

    `ufc` and `nfl` are store holders or directories (default: the process's own `holder` and
    `nfl_holder`, the ones the HTTP API and the UFC page share); `mlb` is an
    `src.datasvc.mlb.service.MlbService` (default: the process's, created on first use). `clock`
    pins "now" for tests and for as-of defaults.
    """

    def __init__(self, *, ufc=None, nfl=None, mlb=None, clock: Optional[Callable[[], datetime]] = None,
                 strict: bool = False):
        # `strict` is for the HTTP routes, which want their own 404, 409 and 503 and not `available: false`:
        # lookup failures and unreadable files are raised (DataError, DataUnavailable) and the "dataset has no
        # records" pre-check is skipped, so an empty store answers as it always has over HTTP.
        self._strict = strict
        self._holders = {
            "ufc": holder if ufc is None else (ufc if isinstance(ufc, _BaseHolder) else StoreHolder(Path(ufc))),
            "nfl": nfl_holder if nfl is None else (nfl if isinstance(nfl, _BaseHolder) else NflStoreHolder(Path(nfl))),
        }
        self._mlb = mlb
        self._clock = clock or _now

    # -- plumbing -----------------------------------------------------------------------------

    def now(self) -> datetime:
        return self._clock()

    def mlb_service(self):
        if self._mlb is None:
            from src.datasvc.mlb import service as mlb_service
            self._mlb = mlb_service.default_service()
        return self._mlb

    def _sport(self, sport: str) -> str:
        if sport not in SPORTS:
            raise _bad_param("sport", f"must be one of {', '.join(SPORTS)}")
        return sport

    def capabilities(self, sport: str) -> dict:
        """What this sport can answer, and why not where it cannot (the capability map is static)."""
        return {name: dict(entry) for name, entry in CAPABILITIES[self._sport(sport)].items()}

    def _run(self, sport: str, kind: str, used: Sequence[str], build: Callable[[Any], Any], *,
             need: Sequence[str] = (), ids: Optional[Callable[[Any, Any], dict]] = None,
             missing: Optional[Callable[[Any], List[dict]]] = None, page: bool = False) -> dict:
        """Run `build(store)` over ONE snapshot and wrap the result, or explain why not.

        `need` names the datasets that must hold at least one record, else the answer is
        unavailable with that reason. A 404 or a tie (409) from the lookups becomes an unavailable
        answer naming the problem; a 422 is the caller's mistake and is raised.
        """
        hold = self._holders[sport]
        try:
            for name in () if self._strict else need:
                status = hold.dataset_status(name, self.now())
                if not status.get("present"):
                    return unavailable((name, f"the {hold.files[name]} file is absent from the {sport} store"))
                if not status.get("records"):
                    return unavailable((name, f"the {hold.files[name]} file holds no records"))
            result, snap = hold.consistent(build)
        except DataUnavailable as exc:
            if self._strict:
                raise
            return unavailable((exc.dataset, f"the {exc.dataset} dataset could not be read: {exc.__cause__!r}"))
        except SnapshotUnstable as exc:
            if self._strict:
                raise DataError(503, "data_unavailable", f"{exc}; try again") from exc
            return unavailable(("snapshot", f"{exc}; try again"))
        except DataError as exc:
            if self._strict:
                raise
            if exc.status == 404:
                return unavailable(("lookup", exc.message))
            if exc.status == 409:
                return unavailable(("lookup", exc.message),
                                   extra_items=[{"item": "candidates", "reason": "pass an id to choose",
                                                 "candidates": (exc.details or {}).get("candidates")}])
            raise
        pager = None
        if page:
            result, pager = result["data"], result["page"]
        meta = _packet_meta(sport, kind, snap, hold, used, ids=ids(result, snap.store) if ids else {},
                            missing=missing(result) if missing else [], now=self.now())
        return _ok(sport, kind, result, meta, pager)

    # -- schedule and results -------------------------------------------------------------------

    def schedule(self, sport: str, *, limit: int = DEFAULT_LIMIT, cursor: Optional[str] = None,
                 order: str = "desc", **filters) -> dict:
        """UFC: `year`, `status`, or `upcoming=True` (with `days`). NFL: `season`, `week`, `team`, `game_type`,
        `status`. MLB: `date` (required). A page of rows, each as the sport's own store holds it."""
        sport = self._sport(sport)
        if sport == "mlb":
            return self.mlb_service().games(filters.get("date"), now=self.now())
        descending = order_is_descending(order)
        if sport == "ufc":
            upcoming = bool(filters.pop("upcoming", False))
            days = filters.pop("days", None)
            year, status = filters.pop("year", None), filters.pop("status", None)
            _reject_unknown(filters)
            now = self.now()

            def build(store):
                if upcoming:
                    items = ufc_upcoming_events(store, now, days)
                    sig = _query_sig(route="upcoming", days=days)
                    return page_response(items, event_sort_key, CLIENT_MAX_LIMIT, limit, cursor, sig,
                                         descending=False, render=lambda e: upcoming_event(store, e))
                items = ufc_events(store, year, status)
                sig = _query_sig(route="events", year=year, status=status, order=order)
                return page_response(items, event_sort_key, CLIENT_MAX_LIMIT, limit, cursor, sig,
                                     descending=descending, render=event_summary)

            return self._run("ufc", "schedule", ("events", "bouts", "odds") if upcoming else ("events",), build,
                             need=("events",), page=True)
        season, week, team = filters.pop("season", None), filters.pop("week", None), filters.pop("team", None)
        game_type, status = filters.pop("game_type", None), filters.pop("status", None)
        _reject_unknown(filters)

        def build_nfl(store):
            items = nfl_games(store, season=season, week=week, team=team, game_type=game_type, status=status)
            code = team_param(team, "team")
            sig = _query_sig(route="nfl_games", season=season, week=week, team=code, game_type=game_type,
                             status=status, order=order)
            return page_response(items, nfl_store.game_sort_key, CLIENT_MAX_LIMIT, limit, cursor, sig,
                                 descending=descending, render=lambda g: g)

        return self._run("nfl", "schedule", ("games",), build_nfl, need=("games",), page=True)

    def game(self, sport: str, *, event_id: Optional[str] = None, bout_id: Optional[str] = None,
             game_id: Optional[str] = None, date: Optional[str] = None, away: Optional[str] = None,
             home: Optional[str] = None) -> dict:
        """UFC: an event (`event_id`) or a bout (`bout_id`). NFL: `game_id`. MLB: `date`, `away`, `home`."""
        sport = self._sport(sport)
        if sport == "mlb":
            return self.mlb_service().game(date, away, home, now=self.now())
        if sport == "ufc":
            if (event_id is None) == (bout_id is None):
                raise _bad_param("event_id", "give exactly one of event_id and bout_id")
            if event_id is not None:
                return self._run("ufc", "event", ("events", "bouts", "fighters"),
                                 lambda s: ufc_event_detail(s, event_id), need=("events",))
            return self._run("ufc", "bout", ("bouts", "events", "fighters", "fight_stats", "odds"),
                             lambda s: ufc_bout_detail(s, bout_id), need=("bouts",))
        if game_id is None:
            raise _bad_param("game_id", "required for nfl")
        return self._run("nfl", "game", ("games", "team_games"), lambda s: nfl_game_detail(s, game_id),
                         need=("games",))

    # -- participants and their history -----------------------------------------------------------

    def participants(self, sport: str, *, search: Optional[str] = None, date: Optional[str] = None,
                     limit: int = DEFAULT_LIMIT, cursor: Optional[str] = None, team: Optional[str] = None) -> dict:
        """UFC: fighters (`search` a name or a page of all). NFL: with `search`, players matching a name
        (best match plus candidates); with `team`, that team's players (from the player rows); with neither, teams.
        MLB: the clubs and probable starters of `date`'s games."""
        sport = self._sport(sport)
        if sport == "mlb":
            return self.mlb_service().participants(date, now=self.now())
        if sport == "ufc":
            if search is not None:
                return self._run("ufc", "participants", ("fighters",), lambda s: ufc_fighter_search(s, search),
                                 need=("fighters",))

            def build(store):
                return page_response(ufc_fighters_by_name(store), fighter_sort_key, CLIENT_MAX_LIMIT, limit, cursor,
                                     _query_sig(route="fighters"), descending=False, render=fighter_summary)

            return self._run("ufc", "participants", ("fighters",), build, need=("fighters",), page=True)
        if search is not None:
            def find(store):
                pid, how = resolve_player(store, search)
                return {"query": search, "player_id": pid, "name": store.player_names().get(pid), "matched_by": how}
            return self._run("nfl", "participants", ("player_games",), find, need=("player_games",))
        if team is not None:
            def roster(store):
                code = team_param(team, "team")
                seen = {}
                for row in store.player_games:
                    if row["team"] == code:
                        seen[row["player_id"]] = {"player_id": row["player_id"], "name": row.get("name"),
                                                  "position_group": row.get("position_group"),
                                                  "last_game_id": row["game_id"]}
                return {"team": code, "team_name": nfl_features.team_name(code),
                        "players": sorted(seen.values(), key=lambda p: (str(p["name"]), p["player_id"]))}
            return self._run("nfl", "participants", ("player_games",), roster, need=("player_games",))

        def teams(store):
            codes = sorted({g[s] for g in store.games for s in ("home_team", "away_team") if g.get(s)})
            return [{"team": c, "name": nfl_features.team_name(c)} for c in codes]
        return self._run("nfl", "participants", ("games",), teams, need=("games",))

    def history(self, sport: str, participant: str, *, limit: int = DEFAULT_LIMIT, cursor: Optional[str] = None,
                season: Optional[int] = None) -> dict:
        """UFC: a fighter's bouts (id), newest first. NFL: a player's rows (id or name), or with
        `season` those of one season; MLB: a pitcher's appearances (person id)."""
        sport = self._sport(sport)
        if sport == "mlb":
            return self.mlb_service().pitcher_history(participant, now=self.now())
        if sport == "ufc":
            def build(store):
                bouts = ufc_fighter_bouts(store, participant)
                return page_response(bouts, bout_sort_key, CLIENT_MAX_LIMIT, limit, cursor,
                                     _query_sig(route="fights", fighter=participant), descending=True,
                                     render=lambda b: fight_item(store, participant, b))

            return self._run("ufc", "history", ("bouts", "events", "fighters", "fight_stats"), build,
                             need=("bouts",), page=True,
                             ids=lambda r, store: {"fighter_id": participant,
                                                   "provider_ids": {"espn": {"athlete": participant}}})

        def build_nfl(store):
            rows, pid = nfl_player_games(store, player=participant, season=season)
            sig = _query_sig(route="nfl_player_games", player=pid, season=season, order="desc")
            return page_response(rows, pg_key, CLIENT_MAX_LIMIT, limit, cursor, sig, descending=True,
                                 render=lambda r: r)

        return self._run("nfl", "history", ("player_games",), build_nfl, need=("player_games",), page=True)

    def features(self, sport: str, subject: str, *, as_of: Optional[str] = None, kind: str = "player") -> dict:
        """UFC: a fighter's features (id) as of a moment (default now). NFL: `kind` "team" or "player"."""
        sport = self._sport(sport)
        if sport == "mlb":
            return unavailable(("features", CAPABILITIES["mlb"]["features"]["reason"]))
        cutoff = parse_as_of(as_of) or self.now()
        if sport == "ufc":
            return self._run("ufc", "features", ("bouts", "events", "fighters", "fight_stats"),
                             lambda s: ufc_fighter_features(s, subject, cutoff), need=("bouts",))
        if kind == "team":
            return self._run("nfl", "features", ("games", "team_games", "injuries"),
                             lambda s: nfl_team_features_as_of(s, subject, cutoff), need=("games",))
        if kind != "player":
            raise _bad_param("kind", "must be team or player")
        return self._run("nfl", "features", ("games", "player_games"),
                         lambda s: nfl_player_features_as_of(s, subject, cutoff), need=("player_games",))

    def availability(self, sport: str, *, game_id: Optional[str] = None, team: Optional[str] = None,
                     season: Optional[int] = None, week: Optional[int] = None, player_id: Optional[str] = None,
                     limit: int = DEFAULT_LIMIT, cursor: Optional[str] = None) -> dict:
        """NFL: the injury report rows. UFC and MLB: unavailable, with the reason."""
        sport = self._sport(sport)
        if sport != "nfl":
            return unavailable(("availability", CAPABILITIES[sport]["availability"]["reason"]))

        def build(store):
            rows = nfl_injuries(store, game_id=game_id, team=team, season=season, week=week, player_id=player_id)
            sig = _query_sig(route="nfl_injuries", game_id=game_id, team=team_param(team, "team"), season=season,
                             week=week, player_id=player_id, order="desc")
            return page_response(rows, inj_key, CLIENT_MAX_LIMIT, limit, cursor, sig, descending=True,
                                 render=lambda r: r)

        return self._run("nfl", "availability", ("injuries",), build, need=("injuries",), page=True)

    # -- quotes ---------------------------------------------------------------------------------

    def quotes(self, sport: str, *, bout_id: Optional[str] = None, game_id: Optional[str] = None,
               date: Optional[str] = None, away: Optional[str] = None, home: Optional[str] = None) -> dict:
        """UFC: a bout's odds (`bout_id`). NFL: the market on a game (`game_id`), ONE value per game: the close
        for a final game, the latest otherwise. MLB: the packet's markets for `date`, `away`, `home`."""
        sport = self._sport(sport)
        if sport == "mlb":
            return self.mlb_service().quotes(date, away, home, now=self.now())
        if sport == "ufc":
            if bout_id is None:
                raise _bad_param("bout_id", "required for ufc")

            def build(store):
                bout = store.bout_by_id().get(bout_id)
                if bout is None:
                    raise _not_found("bout", bout_id)
                a, b = bout.get("fighter_a_id"), bout.get("fighter_b_id")
                odds = matchup_mod.bout_odds(store, bout, a, b)
                if odds is None:
                    raise DataError(404, "not_found", f"no odds row for bout {bout_id!r}")
                return {"bout": matchup_mod.bout_summary(store, bout), "odds": odds,
                        "basis": BASIS["ufc"]["odds"]["basis"], "basis_note": BASIS["ufc"]["odds"]["note"]}

            return self._run("ufc", "quotes", ("odds", "bouts"), build, need=("odds",))
        if game_id is None:
            raise _bad_param("game_id", "required for nfl")

        def build_nfl(store):
            game = store.game_by_id().get(game_id)
            if game is None:
                raise _not_found("game", game_id)
            market = nfl_matchup.market_block(game)
            if not market["available"]:
                raise DataError(404, "not_found", market["reason"])
            return {"game_id": game_id, "status": game.get("status"), "market": market,
                    "basis": SINGLE_VALUE, "basis_note": BASIS["nfl"]["games"]["note"]}

        return self._run("nfl", "quotes", ("games",), build_nfl, need=("games",))

    # -- the matchup evidence packet -----------------------------------------------------------------

    def matchup(self, sport: str, *, a: Optional[str] = None, b: Optional[str] = None,
                game_id: Optional[str] = None, season: Optional[int] = None, week: Optional[int] = None,
                as_of: Optional[str] = None, date: Optional[str] = None, away: Optional[str] = None,
                home: Optional[str] = None, built_at: Optional[str] = None, cfg: Optional[dict] = None) -> dict:
        """The evidence packet for one fixture.

        UFC: `a` and `b`, ids or names. NFL: `game_id`, or `a` and `b` (teams). MLB: `date`, `away`,
        `home` (the analyst's frozen packet, byte for byte what the analyst builds). The packet is
        under `data`; its `meta` carries ids, units, sources, coverage, missing reasons, the
        `data_version` and the basis of each dataset.
        """
        sport = self._sport(sport)
        if sport == "mlb":
            return self.mlb_service().packet(date, away, home, built_at=built_at, cfg=cfg, now=self.now())
        cutoff = parse_as_of(as_of)
        now = self.now()
        if sport == "ufc":
            if a is None or b is None:
                raise _bad_param("a", "give both a and b (fighter ids or names)")
            return self._run(
                "ufc", "matchup_packet", ("events", "bouts", "fighters", "fight_stats", "odds", "ufccom_profiles"),
                lambda s: ufc_matchup_sheet(s, a, b, cutoff, now), need=("bouts",),
                ids=_ufc_ids_of_sheet, missing=_sheet_missing)
        return self._run(
            "nfl", "matchup_packet", ("games", "team_games", "player_games", "injuries"),
            lambda s: nfl_matchup_sheet(s, game_id=game_id, a=a, b=b, season=season, week=week, cutoff=cutoff,
                                        now=now),
            need=("games",), ids=_nfl_ids_of_sheet,
            missing=_sheet_missing)


def _reject_unknown(filters: dict) -> None:
    if filters:
        raise _bad_param(sorted(filters)[0], "not a filter this sport's schedule takes")


def _sheet_missing(sheet: dict) -> List[dict]:
    """The sheet's own missing list in {item, reason} form, keeping every detail it names."""
    out = []
    for m in sheet.get("missing") or []:
        item = m.get("figure") or m.get("item") or "unknown"
        extra = {k: v for k, v in m.items() if k not in ("figure", "item", "reason")}
        out.append({"item": item, "reason": m.get("reason"), **extra})
    return out


def _ufc_ids_of_sheet(sheet: dict, store) -> dict:
    """The sheet's stable ids. The provider id mapping is ESPN's athlete and competition ids (the ids ARE ESPN's)
    and the UFC.com slug where a profile was matched."""
    feats = sheet.get("features") or {}
    ids = {"fighter_a_id": sheet["a"]["fighter_id"], "fighter_b_id": sheet["b"]["fighter_id"],
           "bout_id": (sheet.get("bout") or {}).get("bout_id"),
           "event_id": (sheet.get("bout") or {}).get("event_id"),
           "provider_ids": {"espn": {"fighter_a": sheet["a"]["fighter_id"], "fighter_b": sheet["b"]["fighter_id"],
                                     "competition": (sheet.get("bout") or {}).get("bout_id"),
                                     "event": (sheet.get("bout") or {}).get("event_id")}}}
    slugs = {}
    for side in ("a", "b"):
        block = (feats.get(side) or {}).get("ufccom") or {}
        slugs[side] = block.get("ufc_slug")
    if any(slugs.values()):
        ids["provider_ids"]["ufc_com_slug"] = slugs
    return ids


def _nfl_ids_of_sheet(sheet: dict, store) -> dict:
    game = sheet["game"]
    record = store.game_by_id().get(game["game_id"]) or {}
    return {"game_id": game["game_id"], "home_team": game["home_team"], "away_team": game["away_team"],
            "stadium_id": game.get("stadium_id"),
            "starting_quarterbacks": {"home": record.get("home_qb_id"), "away": record.get("away_qb_id")},
            "provider_ids": {"nflverse": {"game_id": game["game_id"]},
                             "espn": record.get("espn_id"), "pfr": record.get("pfr_id"), "gsis": record.get("gsis_id")}}


def default_client() -> DataClient:
    """A client over the process's own stores (what the analyst and the pages use)."""
    return DataClient()
