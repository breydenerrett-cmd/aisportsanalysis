"""The UFC backfill and the daily update: the ingestion modules run in order.

    backfill   every event of the given years (newest first): bouts and results,
               then each finished bout's statistics and odds, then every fighter
               who appears, then their UFC.com career profiles.
    update     the last few days (so a card that just finished gets its results,
               statistics and closing odds) and the next three weeks (cards,
               replacements and cancellations, current odds), then any new fighters.

Progress is saved after every event, so a run that stops (a request cap, a network
failure, a browser check) keeps everything it finished; the fetcher's cache makes the
next run skip what is already on disk. A browser check stops the whole run at once:
it means the source no longer serves a plain client, and nothing here works around it.

The ingestion modules are looked up at call time (`sources`), so this file imports
cleanly on its own and tests can hand it fakes.
"""

from __future__ import annotations

import types
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterable, List, Optional

from src.datasvc.http import FetchError, PoliteFetcher, RequestCapReached, SourceBlocked
from src.datasvc.ufc.store import UfcStore


def default_sources() -> types.SimpleNamespace:
    from src.datasvc.ufc import fighters, fightstats, odds, schedule, ufccom
    return types.SimpleNamespace(schedule=schedule, fighters=fighters, fightstats=fightstats,
                                 odds=odds, ufccom=ufccom)


def _new_summary(kind: str) -> dict:
    return {"kind": kind, "started_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "events": 0, "bouts": 0, "fight_stats": 0, "odds": 0, "fighters": 0, "profiles": 0,
            "errors": [], "stopped": None}


def _record_error(summary: dict, where: str, exc: Exception) -> None:
    if len(summary["errors"]) < 200:
        summary["errors"].append(f"{where}: {exc}")


def _ingest_bout_details(fetcher, store, src, bouts, summary, *, stats, odds_on, log) -> None:
    for bout in bouts:
        final = bout.get("status") == "final"
        if stats and final:
            try:
                rows = src.fightstats.fetch_bout_stats(fetcher, bout)
                if rows:
                    store.upsert("fight_stats", rows)
                    summary["fight_stats"] += len(rows)
            except (SourceBlocked, RequestCapReached):
                raise
            except FetchError as exc:
                _record_error(summary, f"stats {bout.get('bout_id')}", exc)
        if odds_on and bout.get("status") in ("final", "scheduled"):
            try:
                rows = src.odds.fetch_bout_odds(fetcher, bout)
                if rows:
                    store.upsert("odds", rows)
                    summary["odds"] += len(rows)
            except (SourceBlocked, RequestCapReached):
                raise
            except FetchError as exc:
                _record_error(summary, f"odds {bout.get('bout_id')}", exc)


def _fighter_ids(bouts: Iterable[dict]) -> List[str]:
    ids = set()
    for bout in bouts:
        for side in ("fighter_a_id", "fighter_b_id"):
            if bout.get(side):
                ids.add(str(bout[side]))
    return sorted(ids)


def _batch_parts(result):
    """(fighters, failed) from whatever fetch_fighters returned: its FighterBatch
    (`.fighters`, `.failed`), a dict with those keys, or a plain list."""
    if isinstance(result, dict):
        return list(result.get("fighters", []) or []), list(result.get("failed", result.get("not_found", [])) or [])
    if hasattr(result, "fighters"):
        return list(result.fighters or []), list(getattr(result, "failed", []) or [])
    return list(result or []), []


def _profile_fetcher(fetcher):
    """UFC.com gets its own, slower pace (at least one second between requests) and
    shares the cache. A fake fetcher in a test is used as it is."""
    if isinstance(fetcher, PoliteFetcher):
        return PoliteFetcher(cache_dir=fetcher.cache_dir, delay_s=max(1.0, fetcher.delay_s),
                             max_requests=fetcher.max_requests, user_agent=fetcher.user_agent)
    return fetcher


def _ingest_fighters(fetcher, store, src, ids, summary, *, refresh, profiles, log) -> None:
    known = store.fighter_by_id()
    wanted = ids if refresh else [i for i in ids if i not in known]
    if wanted:
        records, failed = _batch_parts(src.fighters.fetch_fighters(fetcher, wanted))
        for item in failed:
            fid = item.get("fighter_id") if isinstance(item, dict) else item
            status = item.get("status") if isinstance(item, dict) else 404
            kind = item.get("kind") if isinstance(item, dict) else "not_found"
            _record_error(summary, f"fighter {fid}", FetchError(str(fid), status, kind or "failed"))
        if records:
            store.upsert("fighters", records)
            summary["fighters"] += len(records)
        log(f"fighters: {len(records)} saved of {len(wanted)} requested")
    if not profiles:
        return
    have = store.profile_for()
    fighters_by_id = store.fighter_by_id()
    todo = [fighters_by_id[i] for i in ids if i in fighters_by_id and (refresh or i not in have)]
    saved = []
    slow = _profile_fetcher(fetcher)
    for fighter in todo:
        try:
            record = src.ufccom.fetch_profile(slow, fighter)
        except (SourceBlocked, RequestCapReached):
            if saved:
                store.upsert("ufccom_profiles", saved)
                summary["profiles"] += len(saved)
            raise
        except FetchError as exc:
            _record_error(summary, f"profile {fighter.get('fighter_id')}", exc)
            continue
        if record:
            saved.append(record)
        if len(saved) >= 50:
            store.upsert("ufccom_profiles", saved)
            summary["profiles"] += len(saved)
            saved = []
    if saved:
        store.upsert("ufccom_profiles", saved)
        summary["profiles"] += len(saved)


def _finish(store: UfcStore, summary: dict, fetcher: PoliteFetcher) -> dict:
    summary["finished_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    summary["requests"] = dict(fetcher.stats)
    store.write_manifest(extra={"last_run": {k: summary[k] for k in (
        "kind", "started_utc", "finished_utc", "events", "bouts", "fight_stats", "odds",
        "fighters", "profiles", "stopped")}, "last_run_errors": len(summary["errors"])})
    return summary


def backfill(years: Iterable[int], *, fetcher: Optional[PoliteFetcher] = None,
             store: Optional[UfcStore] = None, stats: bool = True, odds: bool = True,
             fighters: bool = True, profiles: bool = True, sources=None,
             log: Callable[[str], None] = print) -> dict:
    fetcher = fetcher or PoliteFetcher()
    store = store or UfcStore()
    src = sources or default_sources()
    summary = _new_summary("backfill")
    all_bouts: List[dict] = []
    try:
        for year in sorted({int(y) for y in years}, reverse=True):
            event_ids = src.schedule.list_season_events(fetcher, year)
            log(f"{year}: {len(event_ids)} events")
            for event_id in event_ids:
                try:
                    event, bouts = src.schedule.crawl_event(fetcher, event_id)
                except (SourceBlocked, RequestCapReached):
                    raise
                except FetchError as exc:
                    _record_error(summary, f"event {event_id}", exc)
                    continue
                store.upsert("events", [event])
                if bouts:
                    store.upsert("bouts", bouts)
                summary["events"] += 1
                summary["bouts"] += len(bouts)
                all_bouts.extend(bouts)
                _ingest_bout_details(fetcher, store, src, bouts, summary, stats=stats, odds_on=odds, log=log)
        if fighters:
            _ingest_fighters(fetcher, store, src, _fighter_ids(all_bouts), summary,
                             refresh=False, profiles=profiles, log=log)
    except SourceBlocked as exc:
        summary["stopped"] = f"source blocked: {exc}"
        log(f"STOPPED: {summary['stopped']}")
    except RequestCapReached as exc:
        summary["stopped"] = f"request cap reached ({exc}); run again to continue"
        log(f"STOPPED: {summary['stopped']}")
    return _finish(store, summary, fetcher)


def update(today: Optional[date] = None, *, days_back: int = 10, days_ahead: int = 21,
           fetcher: Optional[PoliteFetcher] = None, store: Optional[UfcStore] = None,
           profiles: bool = True, sources=None, log: Callable[[str], None] = print) -> dict:
    today = today or datetime.now(timezone.utc).date()
    fetcher = fetcher or PoliteFetcher()
    store = store or UfcStore()
    src = sources or default_sources()
    summary = _new_summary("update")
    since = today - timedelta(days=days_back)
    touched: List[dict] = []
    try:
        years = sorted({since.year, today.year})
        for year in years:
            events, bouts = src.schedule.crawl_season(fetcher, year, since=since, until=today)
            if events:
                store.upsert("events", events)
            if bouts:
                store.upsert("bouts", bouts)
            summary["events"] += len(events)
            summary["bouts"] += len(bouts)
            touched.extend(bouts)
            _ingest_bout_details(fetcher, store, src, bouts, summary, stats=True, odds_on=True, log=log)
        # known_bouts: a bout that disappears from an upcoming card must come back as
        # canceled; without the stored bouts that is only detectable while the raw
        # cache still holds the previous event document (schedule.crawl_upcoming).
        events, bouts = src.schedule.crawl_upcoming(fetcher, today, days=days_ahead,
                                                    known_bouts=store.bouts)
        if events:
            store.upsert("events", events)
        if bouts:
            store.upsert("bouts", bouts)
        summary["events"] += len(events)
        summary["bouts"] += len(bouts)
        touched.extend(bouts)
        _ingest_bout_details(fetcher, store, src, bouts, summary, stats=False, odds_on=True, log=log)
        _ingest_fighters(fetcher, store, src, _fighter_ids(touched), summary,
                         refresh=False, profiles=profiles, log=log)
    except SourceBlocked as exc:
        summary["stopped"] = f"source blocked: {exc}"
        log(f"STOPPED: {summary['stopped']}")
    except RequestCapReached as exc:
        summary["stopped"] = f"request cap reached ({exc}); run again to continue"
        log(f"STOPPED: {summary['stopped']}")
    return _finish(store, summary, fetcher)


def status(store: Optional[UfcStore] = None, now: Optional[datetime] = None) -> dict:
    """Each dataset's record count, newest date and age in hours, and for events and bouts
    the soonest booked date after now. A booked card never counts as the newest data
    (`store.counts_toward_newest`), so an age is never negative."""
    store = store or UfcStore()
    now = now or datetime.now(timezone.utc)
    out = {}
    from src.datasvc.ufc.store import FILES
    for name in FILES:
        if not store.path(name).exists():
            out[name] = {"records": 0, "newest": None, "age_hours": None, "next_scheduled": None}
            continue
        newest = store.newest(name)
        age = None
        if newest:
            try:
                stamp = datetime.fromisoformat(newest.replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                age = round((now - stamp).total_seconds() / 3600, 1)
            except ValueError:
                age = None
        out[name] = {"records": len(store.load(name)), "newest": newest, "age_hours": age,
                     "next_scheduled": store.next_scheduled(name, after=now)}
    return out
