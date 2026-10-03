"""GET /data/v1/...: the data service's HTTP surface (UFC first).

This file only serves what the files hold. Every number a route returns is either a
stored record or comes from `src.datasvc.ufc.features` / `matchup`, which own the
leakage rule; nothing here derives a figure. Same division of labour as api/props.py.

THREE THINGS THAT MUST STAY TRUE
--------------------------------
1. The files are never read per request. Production has run out of memory from
   whole-store reads per request before (the same pattern behind the /odds, /games and
   /props fixes). One `UfcStore` is loaded per process by `StoreHolder`; each request
   costs a `stat()` of the six dataset files, and only a changed modification time (or
   size) swaps in a fresh store, which then loads each dataset lazily, once, under a
   lock. A request that began before a swap finishes on the store it started with, so a
   response is always one consistent version of the files. /status reads the
   MANIFEST.json (cached by its own modification time) and falls back to one streaming
   pass per changed file, never one per request.

2. One error shape under /data/v1, whoever raised it: {"error": {"code", "message"}}
   (plus an optional "details" object). That includes the 401/402 raised by the shared
   auth dependency, a validation failure, an unknown path (404), a wrong method (405) and
   an unhandled bug (500, logged with an error id and never a traceback). FastAPI's
   exception handlers are app-wide and api/app.py is not ours to edit, so the router
   uses a route class (`DataRoute`) that converts exceptions raised anywhere inside
   its routes, dependencies included.

3. The same sign-in as the product's other signed-in content routes, ALWAYS. The router
   depends on `require_paid_access` (a valid bearer token, and a 402 for a subscription
   customer whose paid period ended). Unlike /games, /today and /odds it is NOT dropped
   by APP_PUBLIC_DEMO: those are the demo's read-only product surface, and this is the
   bulk data surface the red-team finding 2 gate (2026-09-01) exists to keep behind a
   login. Mounted in api/app.py with one `include_router`.

THE SEAM FOR KEYS AND TIERS (not built yet, on purpose)
-------------------------------------------------------
`data_access` is the only place that decides who may use the data API and with what
limits. It returns a `DataCaller` (who, which tier, how they authenticated) and stores
it on `request.state.data_caller`. The routes read exactly one thing from it today: the
tier's `max_limit`, the page size cap. When API keys and paid tiers arrive, change
`data_access` alone: accept an `X-Api-Key` header ahead of the bearer token, look the
key up, return a `DataCaller` with that key's tier (more datasets, bigger pages, a
quota), and raise the same error shape for a bad key or an exhausted quota. No route
changes. Rate limiting belongs in the same function.
"""

from __future__ import annotations

import base64
import bisect
import hashlib
import json
import sys
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from fastapi import APIRouter, Depends, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.auth import require_paid_access
from src.datasvc import names
from src.datasvc.ufc import features as features_mod
from src.datasvc.ufc import matchup as matchup_mod
from src.datasvc.ufc import store as ufc_store
from src.datasvc.ufc.store import UfcStore

API_VERSION = "v1"
DEFAULT_LIMIT = 50
EVENT_STATUSES = ("scheduled", "in_progress", "final", "canceled", "postponed", "unknown")

# /upcoming lists events that have not finished. One that started up to this long ago is
# still "tonight's card" (a card runs for hours and the status flips late); a "scheduled"
# event older than that is a stale row, not an upcoming one, and is left out.
UPCOMING_GRACE = timedelta(hours=36)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# -- errors -------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


class DataUnavailable(Exception):
    """A dataset file exists but cannot be read (a corrupt line, a permission error)."""

    def __init__(self, dataset: str):
        super().__init__(dataset)
        self.dataset = dataset


_DEFAULT_CODES = {400: "bad_request", 401: "unauthorized", 402: "payment_required", 403: "forbidden",
                  404: "not_found", 405: "method_not_allowed", 409: "conflict", 422: "invalid_parameter",
                  429: "rate_limited", 500: "internal_error", 503: "unavailable"}


def error_response(status: int, code: str, message: str, details: Optional[dict] = None,
                   headers: Optional[dict] = None) -> JSONResponse:
    body: Dict[str, Any] = {"code": code, "message": message}
    if details:
        body["details"] = details
    return JSONResponse(status_code=status, content={"error": body}, headers=headers)


def _from_http_exception(exc: StarletteHTTPException) -> JSONResponse:
    """The shared auth dependency raises HTTPException(detail={"error", "message", ...})."""
    detail = exc.detail
    code = _DEFAULT_CODES.get(exc.status_code, "error")
    details = None
    if isinstance(detail, dict):
        code = detail["error"] if isinstance(detail.get("error"), str) else code
        message = detail.get("message") or code.replace("_", " ")
        extra = {k: v for k, v in detail.items() if k not in ("error", "message")}
        details = extra or None
    else:
        message = str(detail) if detail else code.replace("_", " ")
    return error_response(exc.status_code, code, message, details, dict(exc.headers or {}) or None)


def _from_validation_error(exc: RequestValidationError) -> JSONResponse:
    errors = []
    for err in exc.errors():
        loc = [str(p) for p in err.get("loc", ())]
        errors.append({"in": loc[0] if loc else None, "param": loc[-1] if loc else None,
                       "message": str(err.get("msg", "invalid"))})
    first = errors[0] if errors else {"param": "request", "message": "invalid"}
    return error_response(422, "invalid_parameter", f"invalid parameter '{first['param']}': {first['message']}",
                          {"errors": errors})


class DataRoute(APIRoute):
    """Every route of this router answers errors in the one shape (module docstring, point 2)."""

    def get_route_handler(self) -> Callable:
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                return await original(request)
            except ApiError as exc:
                return error_response(exc.status, exc.code, exc.message, exc.details)
            except RequestValidationError as exc:
                return _from_validation_error(exc)
            except StarletteHTTPException as exc:
                return _from_http_exception(exc)
            except DataUnavailable as exc:
                print(f"data api: dataset {exc.dataset!r} could not be read: {exc.__cause__!r}",
                      file=sys.stderr, flush=True)
                return error_response(503, "data_unavailable",
                                      f"the {exc.dataset} dataset is not readable right now; this has been logged")
            except Exception as exc:  # noqa: BLE001 -- surfaced as a safe 500 with an id, never a traceback
                error_id = uuid.uuid4().hex
                print(f"error_id={error_id} data_api_unhandled_exception={exc!r}", file=sys.stderr, flush=True)
                return error_response(500, "internal_error",
                                      f"an unexpected error occurred (error_id={error_id}); this has been logged")

        return handler


# -- who is calling, and the seam for keys and tiers ----------------------------------------

@dataclass(frozen=True)
class Tier:
    name: str
    max_limit: int           # the largest page this tier may ask for


TIERS = {"signed_in": Tier("signed_in", max_limit=100)}
DEFAULT_TIER = "signed_in"


@dataclass(frozen=True)
class DataCaller:
    user_id: Optional[int]
    tier: Tier
    via: str                 # "bearer_token" today; "api_key" when keys exist


def data_access(request: Request, user=Depends(require_paid_access)) -> DataCaller:
    """THE seam: who may use the data API and with what limits (module docstring)."""
    caller = DataCaller(user_id=getattr(user, "id", None), tier=TIERS[DEFAULT_TIER], via="bearer_token")
    request.state.data_caller = caller
    return caller


# -- the store, loaded once ---------------------------------------------------------------------

class _LockedStore(UfcStore):
    """A UfcStore safe to share between request threads.

    The foundation's store loads lazily and is written for one thread: two requests
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


class StoreHolder:
    """The one store of a process, replaced only when a dataset file changes on disk."""

    def __init__(self, root: Optional[Path] = None):
        self._lock = threading.Lock()
        self.set_root(root)

    def set_root(self, root: Optional[Path]) -> None:
        with self._lock:
            self._root = Path(root) if root is not None else ufc_store.DEFAULT_DIR
            self._current: Optional[Tuple[tuple, _LockedStore]] = None
            self._loaded_utc: Optional[str] = None
            self._status: Dict[str, tuple] = {}
            self._manifest: Tuple[Optional[tuple], dict] = (None, {})
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
        for name, filename in ufc_store.FILES.items():
            try:
                st = (self._root / filename).stat()
                sig.append((name, st.st_mtime_ns, st.st_size))
            except OSError:
                sig.append((name, None, None))
        return tuple(sig)

    def store(self) -> _LockedStore:
        """The current store, replaced first if any dataset file changed since it was made."""
        sig = self._file_signature()
        current = self._current
        if current is not None and current[0] == sig:
            return current[1]
        with self._lock:
            sig = self._file_signature()
            if self._current is None or self._current[0] != sig:
                self._current = (sig, _LockedStore(self._root))
                self._loaded_utc = features_mod.iso_utc(_now())
                self.reloads += 1
            return self._current[1]

    def info(self) -> dict:
        return {"store_loaded_utc": self._loaded_utc, "reloads": self.reloads}

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
        entry = files.get(ufc_store.FILES[name])
        if isinstance(entry, dict) and entry.get("bytes") == size and "records" in entry:
            return {"records": entry["records"], "newest": entry.get("newest"), "source": "manifest"}
        field = ufc_store.DATE_FIELDS.get(name)
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
                    if value and ufc_store.counts_toward_newest(name, row) and (newest is None or value > newest):
                        newest = value
        except (OSError, ValueError) as exc:
            raise DataUnavailable(name) from exc
        return {"records": records, "newest": newest, "source": "files"}

    def dataset_status(self, name: str, now: datetime) -> dict:
        filename = ufc_store.FILES[name]
        path = self._root / filename
        base = {"file": filename, "newest_field": ufc_store.DATE_FIELDS.get(name)}
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


holder = StoreHolder()


def use_data_dir(path: Optional[Path]) -> None:
    """Point the API at another directory (tests, or a deployment that keeps the files elsewhere)."""
    holder.set_root(path)


def _store() -> _LockedStore:
    return holder.store()


# -- pagination ------------------------------------------------------------------------------

def _query_sig(**params: Any) -> str:
    """A short fingerprint of a query's filters, so a cursor cannot be replayed against another query."""
    blob = json.dumps(params, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:8]


def encode_cursor(sig: str, key: Sequence[str]) -> str:
    raw = json.dumps({"q": sig, "k": list(key)}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str, sig: str) -> Tuple[str, ...]:
    bad = ApiError(422, "invalid_cursor", "the cursor is not one this API issued; start again without one")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        key, query = data["k"], data["q"]
        if not isinstance(key, list) or not key or not all(isinstance(x, str) for x in key):
            raise ValueError("bad key")
    except (ValueError, KeyError, TypeError) as exc:
        raise bad from exc
    if query != sig:
        raise ApiError(422, "invalid_cursor",
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


def _page_response(items: Sequence[Any], key_fn, caller: DataCaller, limit: int, cursor: Optional[str],
                   sig: str, *, descending: bool, render: Callable[[Any], dict]) -> dict:
    effective = min(limit, caller.tier.max_limit)
    page, next_cursor = paginate(items, key_fn, limit=effective, cursor=cursor, sig=sig, descending=descending)
    return {"data": [render(i) for i in page],
            "page": {"limit": effective, "count": len(page), "total": len(items), "next_cursor": next_cursor}}


def _date_key(text: Any) -> str:
    """A sortable form of a stored date: UTC ISO to the second when readable, else the raw text."""
    inst = features_mod.instant(text)
    return features_mod.iso_utc(inst) if inst is not None else (text if isinstance(text, str) else "")


def _order(order: str) -> bool:
    if order not in ("asc", "desc"):
        raise ApiError(422, "invalid_parameter", "invalid parameter 'order': must be asc or desc",
                       {"errors": [{"in": "query", "param": "order", "message": "must be asc or desc"}]})
    return order == "desc"


# -- shared lookups and projections -----------------------------------------------------------------

def _not_found(kind: str, ident: str) -> ApiError:
    return ApiError(404, "not_found", f"no {kind} with id {ident!r} in the store")


def _fighter_ref(store, fighter_id: Optional[str]) -> Optional[dict]:
    if not fighter_id:
        return None
    return {"fighter_id": fighter_id, "name": (store.fighter_by_id().get(fighter_id) or {}).get("name")}


def _fighter_summary(f: dict) -> dict:
    return {"fighter_id": f.get("fighter_id"), "name": f.get("name"), "nickname": f.get("nickname"),
            "weight_class": f.get("weight_class"), "stance": f.get("stance"), "dob": f.get("dob"),
            "active": f.get("active"), "record": f.get("record")}


def _event_summary(e: dict) -> dict:
    return {"event_id": e.get("event_id"), "name": e.get("name"), "short_name": e.get("short_name"),
            "date_utc": e.get("date_utc"), "season": e.get("season"), "status": e.get("status"),
            "venue_id": e.get("venue_id"), "bout_count": len(e.get("bout_ids") or [])}


def _bout_with_names(store, bout: dict) -> dict:
    return {**bout, "fighter_a": _fighter_ref(store, bout.get("fighter_a_id")),
            "fighter_b": _fighter_ref(store, bout.get("fighter_b_id"))}


def _result_block(store, bout: dict) -> Optional[dict]:
    winner, method = bout.get("winner_id"), bout.get("result_method")
    if not winner and method not in ("DRAW", "NC"):
        return None
    loser = None
    if winner:
        loser = bout.get("fighter_b_id") if winner == bout.get("fighter_a_id") else bout.get("fighter_a_id")
    return {
        "outcome": "decided" if winner else ("draw" if method == "DRAW" else "no_contest"),
        "winner_id": winner, "winner_name": (_fighter_ref(store, winner) or {}).get("name"),
        "loser_id": loser, "loser_name": (_fighter_ref(store, loser) or {}).get("name"),
        "method": method, "method_raw": bout.get("result_method_raw"), "detail": bout.get("result_detail"),
        "target": bout.get("result_target"), "end_round": bout.get("end_round"),
        "end_time_s": bout.get("end_time_s"), "fight_time_s": bout.get("fight_time_s"),
    }


def _people(store) -> Dict[str, List[str]]:
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


def _known_fighter(store, fighter_id: str) -> bool:
    return fighter_id in store.fighter_by_id() or fighter_id in store.bouts_by_fighter()


def _resolve_fighter(store, value: str, param: str) -> Tuple[str, str]:
    """A fighter id or a name to (fighter_id, how it was matched). Never guesses between equals."""
    if _known_fighter(store, value):
        return value, "id"
    result = names.match(value, _people(store))
    if result.best:
        return result.best, "name"
    if result.ambiguous:
        raise ApiError(409, "ambiguous_name", f"{param}={value!r} matches more than one fighter equally well; "
                       "pass a fighter id", {"param": param, "query": value,
                                              "candidates": [_candidate(store, *c) for c in result.candidates]})
    raise ApiError(404, "not_found", f"no fighter matches {param}={value!r}")


def _parse_as_of(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    try:
        return features_mod.parse_instant(value)
    except ValueError:
        raise ApiError(422, "invalid_parameter",
                       "invalid parameter 'as_of': must be an ISO date (2026-10-03) or datetime "
                       "(2026-10-03T21:00Z; URL-encode a + offset as %2B)",
                       {"errors": [{"in": "query", "param": "as_of", "message": "not an ISO date or datetime"}]})


router = APIRouter(prefix=f"/data/{API_VERSION}", dependencies=[Depends(data_access)], route_class=DataRoute)


# -- /status ---------------------------------------------------------------------------------------

@router.get("/status", summary="Each dataset's record count, newest date and age")
def get_status() -> dict:
    now = _now()
    datasets = {name: holder.dataset_status(name, now) for name in ufc_store.FILES}
    return {"data": {
        "generated_utc": features_mod.iso_utc(now),
        "datasets": datasets,
        "manifest_generated_utc": holder.manifest_generated_utc(),
        "service": holder.info(),
        "note": ("age_seconds is now minus `newest`. For events and bouts `newest` is the newest card or bout "
                 "that took place: booked, postponed and cancelled ones do not count (/data/v1/ufc/upcoming "
                 "lists the booked ones). For odds, fighters and ufccom_profiles `newest` is a fetch time."),
    }}


# -- events ------------------------------------------------------------------------------------------

def _event_year(e: dict) -> Optional[int]:
    inst = features_mod.instant(e.get("date_utc"))
    if inst is not None:
        return inst.year
    season = e.get("season")
    return season if isinstance(season, int) else None


@router.get("/ufc/events", summary="Events, newest first; filter by year and status")
def list_events(year: Optional[int] = Query(None, ge=1990, le=2100), status: Optional[str] = Query(None),
                order: str = Query("desc"), limit: int = Query(DEFAULT_LIMIT, ge=1),
                cursor: Optional[str] = Query(None, max_length=1024),
                caller: DataCaller = Depends(data_access)) -> dict:
    if status is not None and status not in EVENT_STATUSES:
        raise ApiError(422, "invalid_parameter", f"invalid parameter 'status': must be one of {', '.join(EVENT_STATUSES)}",
                       {"errors": [{"in": "query", "param": "status", "message": f"one of {list(EVENT_STATUSES)}"}]})
    descending = _order(order)
    store = _store()
    everything = store.view("events_asc", lambda: sorted(
        store.events, key=lambda e: (_date_key(e.get("date_utc")), str(e.get("event_id")))))
    items = [e for e in everything
             if (year is None or _event_year(e) == year) and (status is None or e.get("status") == status)]
    sig = _query_sig(route="events", year=year, status=status, order=order)
    return _page_response(items, lambda e: (_date_key(e.get("date_utc")), str(e.get("event_id"))), caller,
                          limit, cursor, sig, descending=descending, render=_event_summary)


@router.get("/ufc/events/{event_id}", summary="One event with its bouts")
def get_event(event_id: str) -> dict:
    store = _store()
    event = store.event_by_id().get(event_id)
    if event is None:
        raise _not_found("event", event_id)
    bouts_by_id = store.bout_by_id()
    ids = event.get("bout_ids") or []
    return {"data": {
        "event": event,
        "bouts": [_bout_with_names(store, bouts_by_id[b]) for b in ids if b in bouts_by_id],
        "missing_bout_ids": [b for b in ids if b not in bouts_by_id],
    }}


@router.get("/ufc/bouts/{bout_id}", summary="One bout with its fighters, result, statistics rows and odds")
def get_bout(bout_id: str) -> dict:
    store = _store()
    bout = store.bout_by_id().get(bout_id)
    if bout is None:
        raise _not_found("bout", bout_id)
    fighters = store.fighter_by_id()
    stats = store.stats_for()
    a, b = bout.get("fighter_a_id"), bout.get("fighter_b_id")
    event = store.event_by_id().get(bout.get("event_id"))
    return {"data": {
        "bout": bout,
        "event": _event_summary(event) if event else None,
        "fighters": {"a": fighters.get(a), "b": fighters.get(b)},
        "result": _result_block(store, bout),
        "stats": [stats[(bout_id, f)] for f in (a, b) if (bout_id, f) in stats],
        "odds": list(store.odds_for_bout().get(bout_id, [])),
    }}


# -- fighters ------------------------------------------------------------------------------------------

@router.get("/ufc/fighters", summary="Search fighters by name, or list them")
def list_fighters(search: Optional[str] = Query(None, min_length=1, max_length=100),
                  limit: int = Query(DEFAULT_LIMIT, ge=1), cursor: Optional[str] = Query(None, max_length=1024),
                  caller: DataCaller = Depends(data_access)) -> dict:
    """With `search`: the best match (200), or 409 listing the candidates when two fit equally well,
    or 404. Without it: a page of every fighter by name."""
    store = _store()
    if search is not None:
        result = names.match(search, _people(store))
        if result.best:
            candidates = [_candidate(store, *c) for c in result.candidates]
            best = store.fighter_by_id()[result.best]
            return {"data": {"query": search,
                             "match": {**_fighter_summary(best), "score": candidates[0]["score"],
                                       "matched_name": candidates[0]["matched_name"]},
                             "candidates": candidates}}
        if result.ambiguous:
            raise ApiError(409, "ambiguous_name",
                           f"{search!r} matches more than one fighter equally well; pass a fighter id",
                           {"query": search, "candidates": [_candidate(store, *c) for c in result.candidates]})
        raise ApiError(404, "not_found", f"no fighter matches {search!r}")
    everything = store.view("fighters_by_name", lambda: sorted(
        store.fighters, key=lambda f: (names.normalise(f.get("name")), str(f.get("fighter_id")))))
    return _page_response(everything, lambda f: (names.normalise(f.get("name")), str(f.get("fighter_id"))), caller,
                          limit, cursor, _query_sig(route="fighters"), descending=False, render=_fighter_summary)


@router.get("/ufc/fighters/{fighter_id}", summary="One fighter (and the UFC.com profile when there is one)")
def get_fighter(fighter_id: str) -> dict:
    store = _store()
    fighter = store.fighter_by_id().get(fighter_id)
    if fighter is None:
        raise _not_found("fighter record", fighter_id)
    return {"data": {"fighter": fighter,
                     "ufccom_profile": store.profile_for().get(fighter_id),
                     "ufc_bouts_in_store": len(store.bouts_by_fighter().get(fighter_id, []))}}


def _fight_item(store, fighter_id: str, bout: dict) -> dict:
    a, b = bout.get("fighter_a_id"), bout.get("fighter_b_id")
    opponent = b if a == fighter_id else a
    return {
        "bout_id": bout["bout_id"], "event_id": bout.get("event_id"),
        "event_name": (store.event_by_id().get(bout.get("event_id")) or {}).get("name"),
        "date_utc": bout.get("date_utc"), "status": bout.get("status"),
        "opponent_id": opponent, "opponent_name": (_fighter_ref(store, opponent) or {}).get("name"),
        "weight_class": bout.get("weight_class"), "card_segment": bout.get("card_segment"),
        "match_number": bout.get("match_number"), "scheduled_rounds": bout.get("scheduled_rounds"),
        "result": features_mod.outcome_for(bout, fighter_id), "method": bout.get("result_method"),
        "method_detail": bout.get("result_detail"), "end_round": bout.get("end_round"),
        "end_time_s": bout.get("end_time_s"), "fight_time_s": bout.get("fight_time_s"),
        "has_stats": (bout["bout_id"], fighter_id) in store.stats_for(),
    }


@router.get("/ufc/fighters/{fighter_id}/fights", summary="A fighter's bouts, newest first, upcoming ones included")
def get_fighter_fights(fighter_id: str, limit: int = Query(DEFAULT_LIMIT, ge=1),
                       cursor: Optional[str] = Query(None, max_length=1024),
                       caller: DataCaller = Depends(data_access)) -> dict:
    store = _store()
    if not _known_fighter(store, fighter_id):
        raise _not_found("fighter", fighter_id)
    bouts = sorted(store.bouts_by_fighter().get(fighter_id, []),
                   key=lambda b: (_date_key(b.get("date_utc")), str(b["bout_id"])))
    return _page_response(bouts, lambda b: (_date_key(b.get("date_utc")), str(b["bout_id"])), caller, limit, cursor,
                          _query_sig(route="fights", fighter=fighter_id), descending=True,
                          render=lambda b: _fight_item(store, fighter_id, b))


@router.get("/ufc/fighters/{fighter_id}/features", summary="A fighter's leakage-free features as of a moment")
def get_fighter_features(fighter_id: str, as_of: Optional[str] = Query(None, max_length=64)) -> dict:
    cutoff = _parse_as_of(as_of) or _now()
    store = _store()
    if not _known_fighter(store, fighter_id):
        raise _not_found("fighter", fighter_id)
    return {"data": features_mod.features_as_of(store, fighter_id, cutoff)}


# -- matchup and upcoming -------------------------------------------------------------------------------

@router.get("/ufc/matchup", summary="The fact sheet for two fighters (ids or names)")
def get_matchup(a: str = Query(..., min_length=1, max_length=100), b: str = Query(..., min_length=1, max_length=100),
                as_of: Optional[str] = Query(None, max_length=64)) -> dict:
    cutoff = _parse_as_of(as_of)
    store = _store()
    a_id, a_how = _resolve_fighter(store, a, "a")
    b_id, b_how = _resolve_fighter(store, b, "b")
    if a_id == b_id:
        raise ApiError(422, "invalid_parameter", "a and b are the same fighter",
                       {"errors": [{"in": "query", "param": "b", "message": "same fighter as a"}]})
    sheet = matchup_mod.matchup(store, a_id, b_id, cutoff, now=_now())
    sheet["resolved"] = {"a": {"query": a, "fighter_id": a_id, "matched_by": a_how},
                         "b": {"query": b, "fighter_id": b_id, "matched_by": b_how}}
    return {"data": sheet}


def _upcoming_bout(store, bout: dict) -> dict:
    a, b = bout.get("fighter_a_id"), bout.get("fighter_b_id")
    return {
        "bout_id": bout["bout_id"], "match_number": bout.get("match_number"),
        "card_segment": bout.get("card_segment"), "date_utc": bout.get("date_utc"),
        "weight_class": bout.get("weight_class"), "scheduled_rounds": bout.get("scheduled_rounds"),
        "status": bout.get("status"), "fighter_a": _fighter_ref(store, a), "fighter_b": _fighter_ref(store, b),
        "odds": matchup_mod.bout_odds(store, bout, a, b, detail="current"),
    }


@router.get("/ufc/upcoming", summary="Scheduled events with their bouts and current odds, soonest first")
def get_upcoming(days: Optional[int] = Query(None, ge=1, le=365), limit: int = Query(DEFAULT_LIMIT, ge=1),
                 cursor: Optional[str] = Query(None, max_length=1024),
                 caller: DataCaller = Depends(data_access)) -> dict:
    now = _now()
    store = _store()
    horizon = None if days is None else now + timedelta(days=days)
    earliest = now - UPCOMING_GRACE
    everything = store.view("events_asc", lambda: sorted(
        store.events, key=lambda e: (_date_key(e.get("date_utc")), str(e.get("event_id")))))
    items = []
    for e in everything:
        start = features_mod.instant(e.get("date_utc"))
        if e.get("status") not in ("scheduled", "in_progress") or start is None or start < earliest:
            continue
        if horizon is not None and start > horizon:
            continue
        items.append(e)

    def render(e: dict) -> dict:
        bouts = store.bout_by_id()
        return {**_event_summary(e), "bouts": [_upcoming_bout(store, bouts[i])
                                               for i in (e.get("bout_ids") or []) if i in bouts]}

    return _page_response(items, lambda e: (_date_key(e.get("date_utc")), str(e.get("event_id"))), caller, limit,
                          cursor, _query_sig(route="upcoming", days=days), descending=False, render=render)


# -- anything else under /data/v1 -------------------------------------------------------------------------

@router.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                  include_in_schema=False)
def no_such_route(request: Request, path: str) -> dict:
    """404 for an unknown path, 405 (with Allow) when the path exists under other methods."""
    allowed = set()
    for route in router.routes:
        if isinstance(route, APIRoute) and route.path != f"/data/{API_VERSION}/{{path:path}}" \
                and route.path_regex.match(request.url.path):
            allowed |= set(route.methods or ())
    if allowed:
        raise StarletteHTTPException(status_code=405, detail="method not allowed",
                                     headers={"Allow": ", ".join(sorted(allowed))})
    raise ApiError(404, "not_found", f"no such route: {request.url.path}")
