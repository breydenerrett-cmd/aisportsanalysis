"""`MlbService`: the schedule, the matchup packet, quotes and pitcher history, over existing stores.

WHAT IS WRAPPED, AND WHAT IS NOT
--------------------------------
Nothing here ingests. The packet is built by the analyst's own code (`src/analyst/source.py` loads the
slate and the price rows exactly as `analyst run` does, `src/analyst/packet.py` freezes them), so the bytes
of a packet served here are the bytes the analyst builds; `tests/test_datasvc_mlb_service.py` pins that and
`src/analyst/pilot.py` can take its packet from here. The packet is read-only: serving it publishes
nothing, writes nothing and places nothing.

THE VERSION OF A SNAPSHOT, AND WHY A READ IS CHEAP
--------------------------------------------------
A packet is built from many files (results, pitcher and bullpen logs, lineups, standings, the odds and
props captures with their archive segments, weather) and from one live read of the schedule. The version
of a snapshot is therefore (the signature of every store file, the fingerprint of the schedule that was
read). A read costs a `stat()` per store file and nothing else while that is unchanged: no upstream request
(the schedule is kept for `schedule_ttl_s`, 120 seconds like api/games.py) and no store re-read (the loaded
items and the built packet are kept against the version). A store that changes invalidates the date's
items and its packets. A packet is built from ONE snapshot: the signature is taken again after the build,
and if a file changed meanwhile the build is repeated, and if the files keep changing the answer is
"unavailable", never a packet that mixes two versions.

A file's version here is (size, modification time), stable on one machine and not across machines (the
stores are far too big to hash per read; the UFC and NFL stores, which carry a sha256 manifest, hash by
content). `meta.sources[*].version_kind` says so.

A CACHED PACKET KEEPS ITS OWN TIMES
-----------------------------------
`meta.built_utc` and the packet's `built_at` are when the packet was built, and a cache hit returns them
unchanged: an old packet is never given a fresh timestamp. A caller that needs a packet cut at a chosen
instant (the pilot, which must freeze one) passes `built_at`; that packet is assembled from the cached
items, so it costs no store read, and is not cached itself.

WHAT IS TRUE OF THE HISTORY (docs/datasvc/CLIENT.md has the table, `client.BASIS` is the source)
-------------------------------------------------------------------------------------------------
The odds, props and weather stores are our own forward capture: each row says when we saw it. The results
store and the pitcher and bullpen logs are written after the games: the starter ids in them are
retroactive. The schedule's probable pitcher for a game already played is the starter listed now, not the
one announced beforehand, and `probable_starter_basis` says so on every game row.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
from dataclasses import dataclass
from datetime import date as _date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from src import paths
from src.datasvc import client as core
from src.datasvc.client import DataError, DEFAULT_LIMIT

DEFAULT_SCHEDULE_TTL_S = 120.0
BUILD_ATTEMPTS = 3

# What a packet is built from, named once so the version, the sources list and the tests agree.
PACKET_STORES = ("mlb_results", "pitcher_logs", "bullpen_log", "lineups", "handedness", "pitcher_splits",
                 "matchup_history", "standings", "transactions", "arsenal_pitcher", "arsenal_batter",
                 "weather_forecast", "odds_multibook", "derivative_markets", "batter_props", "pitcher_props")

# Stores that carry a BASIS entry in client.BASIS["mlb"]; the rest are listed without a claim.
NOT_CLASSIFIED = {"basis": "not_classified",
                  "note": "no claim is made about how this store's history was obtained"}


class ScheduleUnavailable(Exception):
    """The schedule provider could not be reached and no earlier read of it is held."""


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canon_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
                          .encode("utf-8")).hexdigest()


def validate_date(value: Any) -> str:
    text = str(value) if value is not None else ""
    try:
        parsed = _date.fromisoformat(text)
    except ValueError:
        parsed = None
    if parsed is None or parsed.isoformat() != text:
        raise core._bad_param("date", f"must be an ISO date (YYYY-MM-DD), got {value!r}")
    return text


# -- the stores a packet is built from -----------------------------------------------------------------

@dataclass(frozen=True)
class StoreFile:
    name: str
    path: Callable[[str], Path]        # date -> the store's hot file (resolved late, so patched paths apply)
    segments: bool = False             # also its cold archive segments (src/pipeline/store_archive.py)


def default_stores() -> Tuple[StoreFile, ...]:
    """The files `analyst run` reads for a date, by the same module constants it reads them through."""
    from src.pipeline import (batter_props, bullpen, derivative_markets, history, lineup_store, lineups,
                              matchup_history, news, snapshots, standings, weather_capture, pitchers)
    from src.providers import statcast
    from src.analyst import source

    def arsenal(side):
        return lambda d: Path(statcast.DEFAULT_STORE) / f"{side}_{str(d)[:4]}.json"

    return (
        StoreFile("mlb_results", lambda d: Path(history.DEFAULT_STORE)),
        StoreFile("pitcher_logs", lambda d: Path(pitchers.DEFAULT_LOG_STORE)),
        StoreFile("bullpen_log", lambda d: Path(bullpen.DEFAULT_LOG)),
        StoreFile("lineups", lambda d: Path(lineup_store.DEFAULT_STORE)),
        StoreFile("handedness", lambda d: Path(lineups.DEFAULT_HANDEDNESS)),
        StoreFile("pitcher_splits", lambda d: Path(lineups.DEFAULT_SPLITS)),
        StoreFile("matchup_history", lambda d: Path(matchup_history.DEFAULT_STORE)),
        StoreFile("standings", lambda d: Path(standings.DEFAULT_STORE)),
        StoreFile("transactions", lambda d: Path(news.DEFAULT_STORE)),
        StoreFile("arsenal_pitcher", arsenal("pitcher")),
        StoreFile("arsenal_batter", arsenal("batter")),
        StoreFile("weather_forecast", lambda d: Path(weather_capture.DEFAULT_STORE)),
        StoreFile("odds_multibook", lambda d: Path(snapshots.DEFAULT_MULTIBOOK_PATH), segments=True),
        StoreFile("derivative_markets", lambda d: Path(derivative_markets.PROCESSED_STORE), segments=True),
        StoreFile("batter_props", lambda d: Path(batter_props.PROCESSED_STORE), segments=True),
        StoreFile("pitcher_props", lambda d: Path(source.PITCHER_PROP_STORE), segments=True),
    )


def _stat(path: Path) -> Optional[Tuple[int, int]]:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns)


def _segment_tokens(path: Path) -> List[Tuple[str, Optional[Tuple[int, int]]]]:
    from src.pipeline import store_archive
    try:
        return [(p.name, _stat(p)) for p in store_archive.segments(path)]
    except OSError:
        return []


def default_loader(date: str, games: list, now: datetime) -> list:
    """Every game's payload and price rows for `date`, from the stores: `analyst.cli.default_loader` with the
    schedule supplied instead of fetched, so the service's one schedule read is the one the packet uses.

    Same calls in the same order as the analyst's loader (a test compares them item for item); only the
    schedule's source and the clock differ. Returns [{"payload", "multibook_rows", "team_total_rows",
    "batter_prop_rows", "pitcher_prop_rows", "prop_board", "team_names", "section_as_of"}].
    """
    from src.analyst import source

    slate = source.slate_payloads(date, fetch_games=lambda _d: copy.deepcopy(games), now=now)
    slate_games = [s["game"] for s in slate]
    rows = source.price_rows(date, slate_games)
    boards = source.prop_board_for(date, {pk: r["batter_props"] for pk, r in rows.items()})
    through = source.stats_through(date)
    out = []
    for s in slate:
        pk = s["game"].get("game_pk")
        r = rows[pk]
        out.append({
            "payload": s["payload"],
            "multibook_rows": r["multibook"], "team_total_rows": r["team_totals"],
            "batter_prop_rows": r["batter_props"], "pitcher_prop_rows": r["pitcher_props"],
            "prop_board": boards.get(pk, []), "team_names": r["team_names"],
            "section_as_of": {"teams": through, "starters": through} if through else {},
        })
    return out


@dataclass(frozen=True)
class _Schedule:
    date: str
    games: tuple
    observed_utc: str
    observed_at: datetime
    fingerprint: str
    refresh_error: Optional[str] = None


@dataclass(frozen=True)
class _Items:
    key: tuple
    items: list
    schedule: _Schedule
    version: dict
    built_utc: str


class MlbService:
    """See the module docstring. Every collaborator is injectable; production passes none."""

    def __init__(self, *, fetch_games: Optional[Callable[[str], list]] = None,
                 loader: Optional[Callable[[str, list, datetime], list]] = None,
                 stores: Optional[Sequence[StoreFile]] = None,
                 clock: Optional[Callable[[], datetime]] = None,
                 schedule_ttl_s: float = DEFAULT_SCHEDULE_TTL_S,
                 results_reader: Optional[Callable[[], Mapping]] = None,
                 pitcher_reader: Optional[Callable[[], Mapping]] = None,
                 data_root: Optional[Path] = None,
                 config_loader: Optional[Callable[[], dict]] = None):
        self._fetch_games = fetch_games
        self._loader = loader or default_loader
        self._stores = tuple(stores) if stores is not None else None
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._ttl = float(schedule_ttl_s)
        self._results_reader = results_reader
        self._pitcher_reader = pitcher_reader
        self._data_root = Path(data_root) if data_root is not None else None
        self._config_loader = config_loader
        self._lock = threading.RLock()
        self._schedules: Dict[str, _Schedule] = {}
        self._items: Dict[str, _Items] = {}
        self._packets: Dict[tuple, Tuple[tuple, dict]] = {}
        self._results_index: Optional[Tuple[tuple, Dict[str, list]]] = None
        self._pitcher_index: Optional[Tuple[tuple, Dict[str, list]]] = None
        self._config_cache: Optional[Tuple[Any, dict]] = None
        self.counters = {"schedule_requests": 0, "item_builds": 0, "packet_builds": 0, "packet_cache_hits": 0}

    # -- collaborators --------------------------------------------------------------------

    def _stores_list(self) -> Tuple[StoreFile, ...]:
        if self._stores is None:
            self._stores = default_stores()
        return self._stores

    def _fetch(self, date: str) -> list:
        if self._fetch_games is not None:
            return self._fetch_games(date)
        from src.providers import mlb
        return mlb.fetch_games(date)

    def _now(self, now: Optional[datetime]) -> datetime:
        return now if now is not None else self._clock()

    def _config(self) -> dict:
        """The analyst config, read once per config-file version (stat() on a hit, never an open)."""
        if self._config_loader is not None:
            return self._config_loader()
        from src.analyst import config as config_mod
        path = paths.repo_root() / config_mod.CONFIG_PATH
        sig = _stat(path)
        cached = self._config_cache
        if cached is None or cached[0] != sig:
            cached = (sig, config_mod.load())
            self._config_cache = cached
        return cached[1]

    # -- the version of the stores ----------------------------------------------------------------

    def signature(self, date: str, names: Optional[Sequence[str]] = None) -> tuple:
        """((store, (size, mtime_ns) or None, archive segments), ...) now. `stat()` only."""
        out = []
        for spec in self._stores_list():
            if names is not None and spec.name not in names:
                continue
            path = spec.path(date)
            out.append((spec.name, _stat(path), tuple(_segment_tokens(path)) if spec.segments else ()))
        return tuple(out)

    @staticmethod
    def _version(sig: tuple, *extra: Any) -> dict:
        files = {}
        for name, hot, segs in sig:
            token = "absent" if hot is None else f"sig:{hot[0]}:{hot[1]}"
            if segs:
                token += f"+{len(segs)}segments:{_canon_hash(segs)[:8]}"
            files[name] = {"token": token,
                           "kind": "absent" if hot is None else "size_and_mtime_on_this_machine"}
        return {"data_version": "dv1-" + _canon_hash([sig, list(extra)])[:24], "files": files}

    # -- the schedule ----------------------------------------------------------------------------

    def _schedule_for(self, date: str, now: datetime) -> _Schedule:
        """The date's schedule: the held read while it is within the TTL, else one fresh request.

        A failed refresh serves the earlier read, marked with the error and its ORIGINAL observation time;
        with no earlier read it raises `ScheduleUnavailable`.
        """
        with self._lock:
            held = self._schedules.get(date)
            if held is not None and 0 <= (now - held.observed_at).total_seconds() < self._ttl:
                return held
            self.counters["schedule_requests"] += 1
            try:
                games = tuple(self._fetch(date))
            except Exception as exc:  # noqa: BLE001 -- any provider failure is "unavailable", never a 500
                if held is None:
                    raise ScheduleUnavailable(f"{type(exc).__name__}: {exc}") from exc
                # Served from the earlier read with its ORIGINAL observation time; the TTL restarts so a provider
                # outage costs one request per window, not one per call.
                held = _Schedule(held.date, held.games, held.observed_utc, now, held.fingerprint,
                                 refresh_error=f"{type(exc).__name__}: {exc}")
                self._schedules[date] = held
                return held
            fingerprint = _canon_hash(list(games))
            if held is not None and held.fingerprint == fingerprint:
                # the same schedule read again: the TTL restarts, the observation time of the content does not
                held = _Schedule(date, held.games, held.observed_utc, now, fingerprint)
            else:
                held = _Schedule(date, games, _iso(now), now, fingerprint)
            self._schedules[date] = held
            return held

    # -- the items of a date, cached against the version ------------------------------------------------

    def _snapshot(self, date: str, now: datetime) -> _Items:
        schedule = self._schedule_for(date, now)
        for _ in range(BUILD_ATTEMPTS):
            sig = self.signature(date)
            key = (sig, schedule.fingerprint)
            with self._lock:
                held = self._items.get(date)
                if held is not None and held.key == key:
                    return held
                items = self._loader(date, list(schedule.games), now)
                self.counters["item_builds"] += 1
                if self.signature(date) != sig:
                    continue                      # a store changed while it was being read: read again
                built = _Items(key, items, schedule, self._version(sig, "schedule:" + schedule.fingerprint),
                               _iso(now))
                self._items[date] = built
                return built
        raise core.SnapshotUnstable(f"the MLB stores changed on every one of {BUILD_ATTEMPTS} reads")

    # -- the capabilities ---------------------------------------------------------------------------

    def games(self, date: Optional[str], *, now: Optional[datetime] = None) -> dict:
        """The schedule for `date`, results for final games. Cached by the schedule's fingerprint."""
        date = validate_date(date)
        now = self._now(now)
        try:
            schedule = self._schedule_for(date, now)
        except ScheduleUnavailable as exc:
            return self._games_from_results(date, now, str(exc))
        rows = sorted((game_row(g) for g in schedule.games),
                      key=lambda r: (r["start_time_utc"] or "", str(r["game_pk"])))
        missing = []
        if schedule.refresh_error:
            missing.append({"item": "schedule", "kind": "stale",
                            "reason": f"the schedule could not be re-read ({schedule.refresh_error}); these games are "
                                      f"the read of {schedule.observed_utc}"})
        if not rows:
            missing.append({"item": "games", "kind": "none_scheduled",
                            "reason": f"the schedule lists no games on {date} (an off day, or a date the provider "
                                      "does not know)"})
        meta = self._meta("games", date, schedule, ids={"date": date,
                                                        "game_pks": [r["game_pk"] for r in rows],
                                                        "provider_ids": {"mlb_statsapi": "game_pk, team_id, person_id"}},
                          version=self._version((), "schedule:" + schedule.fingerprint), used=("schedule",),
                          missing=missing, now=now, coverage=self._coverage(date))
        return core._ok("mlb", "schedule", rows, meta)

    def _games_from_results(self, date: str, now: datetime, why: str) -> dict:
        """The schedule provider is unreachable and nothing is held: the final games the results store has for
        the date, said to be that, or an explicit refusal."""
        index = self._results_by_date()
        stored = index.get(date, [])
        if not stored:
            return {"available": False, "missing": [
                {"item": "schedule", "reason": f"the schedule provider could not be reached ({why}) and the "
                                               f"results store holds no games for {date}", "code": "unavailable"}]}
        rows = [result_row(r) for r in sorted(stored, key=lambda r: (r.get("start_time_utc") or "",
                                                                        str(r.get("game_pk"))))]
        sig = self.signature(date, ("mlb_results",))
        meta = {"sport": "mlb", "kind": "schedule", "built_utc": _iso(now), "observed_utc": None,
                "observed_utc_meaning": "the results store was read, not the live schedule",
                "data_version": self._version(sig)["data_version"],
                "ids": {"date": date, "game_pks": [r["game_pk"] for r in rows]}, "units": core.UNITS["mlb"],
                "sources": [self._source("mlb_results", self._version(sig)["files"].get("mlb_results"))],
                "coverage": self._coverage(date),
                "missing": [{"item": "schedule", "kind": "unavailable",
                             "reason": f"the schedule provider could not be reached ({why}); these are the games "
                                       "the results store holds for the date (final games only)"}]}
        return core._ok("mlb", "schedule", rows, meta)

    def game(self, date: Optional[str], away: Optional[str], home: Optional[str], *,
             now: Optional[datetime] = None) -> dict:
        listing = self.games(date, now=now)
        if not listing.get("available"):
            return listing
        wanted = _wanted(away, home)
        found = [r for r in listing["data"] if r["away"]["team"] and r["home"]["team"]
                 and (r["away"]["team"].upper(), r["home"]["team"].upper()) == wanted]
        if not found:
            return {"available": False, "missing": [
                {"item": "game", "reason": f"no game {away}@{home} on {date} in the schedule read of "
                                           f"{listing['meta'].get('observed_utc')}", "code": "not_found"}]}
        meta = dict(listing["meta"], ids={**listing["meta"]["ids"], "game_pk": found[0]["game_pk"]})
        if len(found) > 1:
            meta["missing"] = list(meta["missing"]) + [
                {"item": "doubleheader", "kind": "ambiguous",
                 "reason": f"{len(found)} games match {away}@{home} on {date}; data is the earlier-listed"}]
        return core._ok("mlb", "game", found[0], meta)

    def participants(self, date: Optional[str], *, now: Optional[datetime] = None) -> dict:
        listing = self.games(date, now=now)
        if not listing.get("available"):
            return listing
        clubs, starters = {}, []
        for row in listing["data"]:
            for side in ("away", "home"):
                club = row[side]
                if club["team"]:
                    clubs[club["team"]] = {"team": club["team"], "team_id": club["team_id"]}
                probable = club.get("probable_starter")
                if probable:
                    starters.append({**probable, "team": club["team"], "game_pk": row["game_pk"],
                                     "basis": row["probable_starter_basis"]})
        data = {"date": date, "clubs": sorted(clubs.values(), key=lambda c: c["team"]), "probable_starters": starters}
        return core._ok("mlb", "participants", data, dict(listing["meta"], kind="participants"))

    def packet(self, date: Optional[str], away: Optional[str], home: Optional[str], *,
               built_at: Optional[str] = None, cfg: Optional[Mapping] = None,
               now: Optional[datetime] = None) -> dict:
        """The analyst's frozen evidence packet for one game, under `data`, with `meta` beside it.

        `built_at` None: the packet cut when the snapshot was built, cached per version. `built_at` given: the
        packet cut at that instant from the cached items (not cached itself); `cfg` as the analyst's loaded config
        (default: config/analyst.json). Refusals carry `code`: not_found (no such game), ambiguous (a
        doubleheader: the packet is per game and the URL cannot say which half), unavailable.
        """
        date = validate_date(date)
        now = self._now(now)
        wanted = _wanted(away, home)
        try:
            snap = self._snapshot(date, now)
        except ScheduleUnavailable as exc:
            return {"available": False, "missing": [
                {"item": "schedule", "reason": f"the schedule provider could not be reached: {exc}",
                 "code": "unavailable"}]}
        except core.SnapshotUnstable as exc:
            return {"available": False, "missing": [{"item": "snapshot", "reason": f"{exc}; try again",
                                                     "code": "unavailable"}]}
        matches = [i for i in snap.items if _item_matches(i, wanted)]
        if not matches:
            return {"available": False, "missing": [
                {"item": "game", "reason": f"no game {away}@{home} on {date} in the schedule read of "
                                           f"{snap.schedule.observed_utc}", "code": "not_found"}]}
        if len(matches) > 1:
            return {"available": False, "missing": [
                {"item": "game", "reason": f"{len(matches)} games match {away}@{home} on {date} (a doubleheader); "
                                           "a packet is built for one game and cannot say which half", "code": "ambiguous"}]}
        cfg_used = dict(cfg) if cfg is not None else self._config()
        cfg_key = _canon_hash(cfg_used)[:12]
        cache_key = (date, wanted, cfg_key)
        if built_at is None:
            with self._lock:
                held = self._packets.get(cache_key)
                if held is not None and held[0] == snap.key:
                    self.counters["packet_cache_hits"] += 1
                    return held[1]
        cut = built_at or _iso(now)
        from src.analyst import cli as analyst_cli
        from src.analyst import packet as packet_mod
        try:
            packet = analyst_cli._packet(matches[0], cut, cfg_used)
        except ValueError as exc:
            raise core._bad_param("built_at", str(exc)) from None
        self.counters["packet_builds"] += 1
        result = core._ok("mlb", "matchup_packet", packet,
                          self._packet_meta(date, snap, matches[0], packet, packet_mod, now))
        if built_at is None:
            with self._lock:
                self._packets[cache_key] = (snap.key, result)
        return result

    def quotes(self, date: Optional[str], away: Optional[str], home: Optional[str], *,
               now: Optional[datetime] = None) -> dict:
        """The packet's markets (every quote with its capture time), or the reasons there are none."""
        result = self.packet(date, away, home, now=now)
        if not result.get("available"):
            return result
        packet = result["data"]
        if not packet["markets"]:
            return {"available": False, "missing": [
                {"item": m["item"], "reason": m["reason"], "code": "no_data"} for m in packet["missing"]]
                or [{"item": "markets", "reason": "the packet prices no market", "code": "no_data"}]}
        stamps = [m["as_of"] for m in packet["markets"].values() if m.get("as_of")]
        data = {"game_id": packet["game"]["game_id"], "built_at": packet["built_at"],
                "newest_quote_as_of": max(stamps) if stamps else None, "markets": packet["markets"],
                "basis": core.OBSERVED, "basis_note": core.BASIS["mlb"]["odds_multibook"]["note"]}
        return core._ok("mlb", "quotes", data, dict(result["meta"], kind="quotes"))

    def pitcher_history(self, person_id: Any, *, now: Optional[datetime] = None, limit: int = DEFAULT_LIMIT) -> dict:
        """A pitcher's stored appearances, newest first, bookkeeping markers left out."""
        now = self._now(now)
        pid = str(person_id).strip() if person_id is not None else ""
        if not pid.isdigit():
            raise core._bad_param("participant", "an MLB pitcher is named by his person id (digits)")
        sig = self.signature("", ("pitcher_logs",))
        index = self._pitchers(sig)
        rows = [a for a in index.get(pid, []) if a.get("date") and not a.get("empty")]
        if not rows:
            return {"available": False, "missing": [
                {"item": "pitcher", "reason": f"no appearances are stored for person id {pid}", "code": "not_found"}]}
        rows = sorted(rows, key=lambda a: a["date"], reverse=True)
        version = self._version(sig)
        meta = {"sport": "mlb", "kind": "history", "built_utc": _iso(now), "units": core.UNITS["mlb"],
                "data_version": version["data_version"],
                "ids": {"person_id": pid, "provider_ids": {"mlb_statsapi": {"person_id": pid}}},
                "observed_utc": None,
                "observed_utc_meaning": "the log has no single observation time; appearances are added after they happen",
                "sources": [self._source("pitcher_logs", version["files"].get("pitcher_logs"))],
                "coverage": {"through": (self._coverage(rows[0]["date"]) or {}).get("pitcher_logs")},
                "missing": []}
        data = {"person_id": pid, "appearances": rows[:limit]}
        page = {"limit": limit, "count": len(data["appearances"]), "total": len(rows), "next_cursor": None}
        return core._ok("mlb", "history", data, meta, page)

    # -- /status ----------------------------------------------------------------------------------------

    def status(self, now: Optional[datetime] = None) -> dict:
        """The MLB datasets for /status: the existing freshness module's report, each with how its history was
        obtained. Fail-soft: a store that cannot be read is reported in its own entry."""
        from src.pipeline import store_freshness
        now = self._now(now)
        report = store_freshness.report(self._data_root, now)
        datasets = {}
        for name, entry in report["stores"].items():
            claim = core.BASIS["mlb"].get(name) or NOT_CLASSIFIED
            datasets[name] = {**entry, "source": claim.get("source"), "basis": claim["basis"],
                              "basis_note": claim["note"]}
        return {"datasets": datasets, "baseball_date": report["baseball_date"],
                "expected_through": report["expected_through"], "stale": report["stale"],
                "core_stale": report["core_stale"], "oldest_through": report["oldest_through"],
                "service": dict(self.counters),
                "note": ("`through` is the newest date a store COVERS (an off day counts), `lag_days` is how far "
                         "that is behind yesterday Eastern, `stale` is past the store's own tolerance. The odds and "
                         "props captures are not timed here; every quote in a packet carries its own capture time.")}

    # -- the pieces ------------------------------------------------------------------------------------

    def _coverage(self, date: str) -> Optional[dict]:
        from src.pipeline import store_freshness
        try:
            return store_freshness.coverage_for_game(date, self._data_root)
        except Exception:  # noqa: BLE001 -- coverage is additive, never the reason an answer fails
            return None

    @staticmethod
    def _source(name: str, version_file: Optional[dict]) -> dict:
        claim = core.BASIS["mlb"].get(name) or NOT_CLASSIFIED
        return {"dataset": name, "source": claim.get("source"), "basis": claim["basis"],
                "basis_note": claim["note"], "version": (version_file or {}).get("token"),
                "version_kind": (version_file or {}).get("kind")}

    def _meta(self, kind: str, date: str, schedule: _Schedule, *, ids: dict, version: dict, used: Sequence[str],
              missing: List[dict], now: datetime, coverage: Optional[dict]) -> dict:
        source = {"dataset": "schedule", **{k: v for k, v in core.BASIS["mlb"]["schedule"].items()
                                            if k in ("source", "basis")},
                  "basis_note": core.BASIS["mlb"]["schedule"]["note"],
                  "version": "schedule:" + schedule.fingerprint[:16], "version_kind": "content_hash_of_the_read"}
        return {"sport": "mlb", "kind": kind, "ids": ids, "units": core.UNITS["mlb"],
                "data_version": version["data_version"], "built_utc": _iso(now),
                "observed_utc": schedule.observed_utc,
                "observed_utc_meaning": "when we read the schedule provider; a held read keeps this time",
                "source_updated_utc": None,
                "source_updated_utc_reason": "the schedule response carries no update time we store",
                "sources": [source], "coverage": coverage, "missing": missing}

    def _packet_meta(self, date: str, snap: _Items, item: Mapping, packet: Mapping, packet_mod, now: datetime) -> dict:
        game = packet["game"]
        advanced_game = ((item.get("payload") or {}).get("advanced") or {}).get("game") or {}
        event_ids = sorted({r.get("event_id") for r in item.get("multibook_rows") or () if r.get("event_id")})
        cutoff = packet_mod._parse_utc(packet["built_at"])
        updates = []
        for row in item.get("multibook_rows") or ():
            seen, stated = packet_mod._parse_utc(row.get("observed_utc")), packet_mod._parse_utc(row.get("last_update"))
            if stated is not None and seen is not None and cutoff is not None and seen <= cutoff:
                updates.append(stated)
        files = snap.version["files"]
        sources = [{"dataset": "schedule", "source": core.BASIS["mlb"]["schedule"]["source"],
                    "basis": core.BASIS["mlb"]["schedule"]["basis"],
                    "basis_note": core.BASIS["mlb"]["schedule"]["note"],
                    "version": "schedule:" + snap.schedule.fingerprint[:16], "version_kind": "content_hash_of_the_read",
                    "observed_utc": snap.schedule.observed_utc}]
        for name in PACKET_STORES:
            if name in files:
                sources.append(self._source(name, files[name]))
        stamps = [m["as_of"] for m in packet["markets"].values() if m.get("as_of")]
        return {
            "sport": "mlb", "kind": "matchup_packet",
            "packet_version": packet["packet_version"], "packet_hash": packet_mod.packet_hash(packet),
            "ids": {"game_id": game["game_id"], "game_pk": game["game_pk"], "date": game["date"],
                    "away": game["away"], "home": game["home"],
                    "team_ids": {"away": advanced_game.get("away_team_id"), "home": advanced_game.get("home_team_id")},
                    "probable_starter_ids": {"away": advanced_game.get("away_probable_id"),
                                             "home": advanced_game.get("home_probable_id")},
                    "provider_ids": {"mlb_statsapi": {"game_pk": game["game_pk"],
                                                      "away_team_id": advanced_game.get("away_team_id"),
                                                      "home_team_id": advanced_game.get("home_team_id"),
                                                      "away_probable_person_id": advanced_game.get("away_probable_id"),
                                                      "home_probable_person_id": advanced_game.get("home_probable_id")},
                                     "the_odds_api": {"event_ids": event_ids} if event_ids else None}},
            "units": core.UNITS["mlb"],
            "data_version": snap.version["data_version"],
            "built_utc": snap.built_utc, "packet_built_at": packet["built_at"],
            "observed_utc": snap.schedule.observed_utc,
            "observed_utc_meaning": ("when we read the schedule; every quote and section inside the packet carries "
                                     "its own capture or as-of time"),
            "newest_quote_as_of": max(stamps) if stamps else None,
            "source_updated_utc": max(updates).strftime("%Y-%m-%dT%H:%M:%SZ") if updates else None,
            "source_updated_utc_reason": (None if updates else
                                          "the price rows carry no book update time before the cutoff"),
            "sources": sources,
            "coverage": self._coverage(game["date"] or date),
            "missing": [dict(m) for m in packet["missing"]],
            "consistency": ("built from one snapshot: the store files were stat()ed before and after the build "
                            "and did not change"),
            "schedule_refresh_error": snap.schedule.refresh_error,
        }

    def _results_by_date(self) -> Dict[str, list]:
        sig = self.signature("", ("mlb_results",))
        cached = self._results_index
        if cached is None or cached[0] != sig:
            if self._results_reader is not None:
                store = self._results_reader()
            else:
                from src.pipeline import history
                store = history.read_results()
            index: Dict[str, list] = {}
            for row in store.values():
                if row.get("date"):
                    index.setdefault(row["date"], []).append(row)
            cached = (sig, index)
            self._results_index = cached
        return cached[1]

    def _pitchers(self, sig: tuple) -> Dict[str, list]:
        cached = self._pitcher_index
        if cached is None or cached[0] != sig:
            if self._pitcher_reader is not None:
                logs = self._pitcher_reader()
            else:
                from src.pipeline import pitchers
                logs = pitchers.read_logs()
            cached = (sig, dict(logs))
            self._pitcher_index = cached
        return cached[1]


# -- rows ---------------------------------------------------------------------------------------------------

def _wanted(away: Optional[str], home: Optional[str]) -> Tuple[str, str]:
    if not away or not home:
        raise core._bad_param("away", "give both away and home (club codes such as NYY and TB)")
    return (str(away).upper(), str(home).upper())


def _item_matches(item: Mapping, wanted: Tuple[str, str]) -> bool:
    game = ((item.get("payload") or {}).get("advanced") or {}).get("game") or {}
    return (str(game.get("away_team") or "").upper(), str(game.get("home_team") or "").upper()) == wanted


def _club(g: Mapping, side: str, basis: str) -> dict:
    name, person = g.get(f"{side}_probable"), g.get(f"{side}_probable_id")
    probable = {"name": name, "person_id": person} if (name or person) else None
    return {"team": g.get(f"{side}_team"), "team_id": g.get(f"{side}_team_id"), "probable_starter": probable}


def game_row(g: Mapping) -> dict:
    """One schedule game in MLB's own shape. A score and a winner appear only for a FINAL game: a game in
    progress has a running score that is not a result, and an unplayed one has none."""
    final = g.get("state") == "final"
    basis = "retroactive" if final else "as_listed_at_observed_utc"
    row = {
        "game_pk": g.get("game_pk"), "date": g.get("date"), "start_time_utc": g.get("start_time_utc"),
        "state": g.get("state"), "detailed_state": g.get("detailed_state"), "game_type": g.get("game_type"),
        "venue": g.get("venue"), "double_header": g.get("double_header"), "game_number": g.get("game_number"),
        "away": _club(g, "away", basis), "home": _club(g, "home", basis),
        "probable_starter_basis": basis,
        "result": None,
    }
    if final:
        row["result"] = {"away_score": g.get("away_score"), "home_score": g.get("home_score"),
                         "winner": g.get("winner"), "home_won": g.get("home_won"),
                         "total_runs": g.get("total_runs"), "run_differential": g.get("run_differential")}
    return row


def result_row(r: Mapping) -> dict:
    """A results-store row in the same shape as a schedule game. The store holds final games only."""
    def num(value):
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    def side(name):
        person = r.get(f"{name}_probable_id")
        probable = {"name": r.get(f"{name}_probable"), "person_id": num(person)} \
            if (r.get(f"{name}_probable") or person) else None
        return {"team": r.get(f"{name}_team"), "team_id": num(r.get(f"{name}_team_id")), "probable_starter": probable}

    return {"game_pk": num(r.get("game_pk")), "date": r.get("date"), "start_time_utc": r.get("start_time_utc"),
            "state": "final", "detailed_state": "Final", "game_type": r.get("game_type"), "venue": r.get("venue"),
            "double_header": r.get("double_header"), "game_number": num(r.get("game_number")),
            "away": side("away"), "home": side("home"), "probable_starter_basis": "retroactive",
            "result": {"away_score": num(r.get("away_score")), "home_score": num(r.get("home_score")),
                       "winner": r.get("winner"),
                       "home_won": num(r.get("home_won")), "total_runs": num(r.get("total_runs")),
                       "run_differential": num(r.get("run_differential"))}}


# -- the process's own service ----------------------------------------------------------------------------

_default: Optional[MlbService] = None
_default_lock = threading.Lock()


def default_service() -> MlbService:
    global _default
    with _default_lock:
        if _default is None:
            _default = MlbService()
        return _default


def set_default_service(service: Optional[MlbService]) -> None:
    """Replace the process's service (tests), or drop it with None so the next use creates a fresh one."""
    global _default
    with _default_lock:
        _default = service
