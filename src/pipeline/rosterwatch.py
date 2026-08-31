"""Roster watch: bracket lineup/probable/transaction events between our own fetches.

WHY THIS EXISTS
---------------
The V3 information-timing study (docs/RESEARCH_V3_TIMING.md) needs grade-B
event timestamps: an event bounded between two of OUR OWN fetches, with both
fetch times recorded. No existing store records fetch times -- lineups are
date-only, probables are one reading per day, transactions carry day-only
dates. This module is the capture side that fixes that, using only the free
MLB endpoints already wrapped by `mlb.fetch_games`, `lineups.fetch_lineups`
and `mlb_news.fetch`. Zero odds-API credits are involved.

`poll()` is meant to run every 10-15 minutes. Each run:

  * fetches today's schedule (probables), today's posted lineups, and today's
    transactions;
  * appends a change row to the matching store ONLY when content changed since
    the last stored row (first sighting always writes);
  * appends one compact poll-marker row
    `{"fetched_utc": ..., "poll": true, "game_date": "YYYY-MM-DD"}` per source
    that was successfully fetched.

WHY THE MARKERS CARRY THE POLLED DATE
-------------------------------------
A marker used to say only "we looked at 23:58Z", not WHAT we looked at. The
poller's slate date rolls over at midnight Eastern, so the first poll after a
flip would be bracketed by the last poll of the PREVIOUS slate -- a look at a
different day's games, which never saw the new day's lineup at all. The
bracket claimed a window whose opening end proved nothing. Stamping the polled
date lets `events()` refuse such a marker instead of trusting it.

WHY THE POLL MARKERS ARE NOT OPTIONAL
-------------------------------------
Change rows alone cannot produce a tight grade-B bracket. If a probable is
listed at 09:00 and scratched at 17:03, the change rows are 09:00 and 17:03
-- an eight-hour interval -- even though a 16:50 poll saw the old value and
proves the change happened inside a 13-minute window. The marker rows record
every successful look at the world, so the interval start is the LAST poll
that still saw the old state, not the poll that first saw it. They also answer
"which prior poll saw this game without a lineup", which is what separates an
admissible lineup_posted bracket from an inadmissible first sighting.

STORAGE COST, STATED
--------------------
Three append-only JSONL stores under data/watch/. Marker rows are ~55 bytes
and arrive at most once per poll per source: at a 10-minute cadence that is
144/day/store, ~2.9 MB per store per year. Data rows are written only on
content change (a handful per game per day). Every `poll()` and `events()`
call reads each store fully ONCE to build an in-memory index -- a few MB read
per poll, milliseconds, and the accepted cost; nothing rereads inside loops.
If a multi-season file ever makes that read matter, rotate the files by
season -- the format needs no change.

FAILURE SEMANTICS
-----------------
A fetch failure for one source is logged, recorded in the report, and skips
that source only: no marker, no rows, and the other sources proceed. A poll
never raises for a network failure. A source that failed writes no marker, so
its brackets simply widen honestly instead of lying about a look that never
happened.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.paths import data_path
from src.pipeline import lineups as lineups_mod
from src.providers import mlb, mlb_news

LOG = logging.getLogger(__name__)

DEFAULT_WATCH_DIR = data_path("watch")

PROBABLES_FILE = "probables_watch.jsonl"
LINEUPS_FILE = "lineups_watch.jsonl"
TRANSACTIONS_FILE = "transactions_watch.jsonl"

# Event classes, named exactly as docs/RESEARCH_V3_TIMING.md names them.
STARTER_SCRATCH = "starter_scratch"
LINEUP_POSTED = "lineup_posted"
HITTER_SCRATCH = "hitter_scratch"
TRANSACTION_SEEN = "transaction_first_seen"


class RosterWatchError(RuntimeError):
    """Raised when a watch store cannot be read or a clock is unusable."""


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------

def poll(game_date=None, watch_dir=DEFAULT_WATCH_DIR,
         fetch_probables=mlb.fetch_games,
         fetch_lineups=lineups_mod.fetch_lineups,
         fetch_transactions=mlb_news.fetch,
         clock=None, timeout=20) -> dict:
    """One capture pass over today's probables, lineups, and transactions.

    All three fetchers are injectable so tests run without the network, and
    `clock` (a callable returning an aware UTC datetime) is injectable so
    tests control the recorded fetch times. Each source is independent: a
    failure logs, lands in the report's `errors`, and never blocks the rest.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    # The default date comes from the SAME clock that stamps the rows. A poll
    # that brackets events with an injected clock but asks MLB about whatever
    # day the wall clock happens to be on is bracketing one world and looking
    # at another.
    iso_date = _to_iso_date(game_date, clock)
    directory = Path(watch_dir)
    directory.mkdir(parents=True, exist_ok=True)

    report = {"date": iso_date, "dir": str(directory), "errors": [],
              "probables": None, "lineups": None, "transactions": None}

    # --- probables -------------------------------------------------------
    try:
        games = fetch_probables(iso_date, timeout=timeout)
        fetched = _utc_iso(clock())
        report["probables"] = _record_probables(
            directory / PROBABLES_FILE, games, fetched, iso_date)
    except RosterWatchError:
        raise  # our own store/clock problems are bugs, not weather
    except Exception as exc:  # network failure must not kill the poll
        _fail(report, "probables", exc)

    # --- lineups ---------------------------------------------------------
    try:
        posted = fetch_lineups(iso_date, timeout=timeout)
        fetched = _utc_iso(clock())
        report["lineups"] = _record_lineups(
            directory / LINEUPS_FILE, posted, fetched, iso_date)
    except RosterWatchError:
        raise
    except Exception as exc:
        _fail(report, "lineups", exc)

    # --- transactions ----------------------------------------------------
    try:
        rows = fetch_transactions(iso_date, timeout=timeout)
        fetched = _utc_iso(clock())
        report["transactions"] = _record_transactions(
            directory / TRANSACTIONS_FILE, rows, fetched, iso_date)
    except RosterWatchError:
        raise
    except Exception as exc:
        _fail(report, "transactions", exc)

    return report


def _fail(report, source, exc) -> None:
    LOG.warning("rosterwatch: %s fetch failed and was skipped: %s", source, exc)
    report["errors"].append({"source": source, "error": str(exc)})


def _record_probables(path, games, fetched_utc, game_date=None) -> dict:
    """Diff-append today's probable pair per game; always append a marker."""
    last = {}  # game_pk -> (away_probable_id, home_probable_id), one pass
    for row in _read_rows(path):
        if row.get("poll"):
            continue
        last[row["game_pk"]] = (row.get("away_probable_id"),
                                row.get("home_probable_id"))

    written = 0
    out = [_marker(fetched_utc, game_date)]
    for game in games or []:
        game_pk = game.get("game_pk")
        if game_pk is None:
            continue
        pair = (game.get("away_probable_id"), game.get("home_probable_id"))
        if last.get(game_pk, _ABSENT) == pair:
            continue  # unchanged: the marker alone proves we looked
        last[game_pk] = pair
        out.append({"fetched_utc": fetched_utc, "game_pk": game_pk,
                    "away_probable_id": pair[0], "home_probable_id": pair[1]})
        written += 1
    _append(path, out)
    return {"games": len(games or []), "written": written}


def _record_lineups(path, posted, fetched_utc, game_date=None) -> dict:
    """Diff-append ordered player-id lineups per game; always append a marker.

    A game with no posted lineup writes NOTHING for that game -- absence over
    guess. The marker still records that this poll looked and saw it absent,
    which is exactly what makes the eventual lineup_posted bracket admissible.
    """
    last = {}  # game_pk -> (away_ids tuple, home_ids tuple)
    for row in _read_rows(path):
        if row.get("poll"):
            continue
        last[row["game_pk"]] = (tuple(row.get("away_lineup") or []),
                                tuple(row.get("home_lineup") or []))

    written = 0
    out = [_marker(fetched_utc, game_date)]
    for game_pk in sorted(posted or {}):
        record = (posted or {})[game_pk]
        away = tuple(_player_ids(record.get("away")))
        home = tuple(_player_ids(record.get("home")))
        if not away and not home:
            continue
        if last.get(game_pk, _ABSENT) == (away, home):
            continue
        last[game_pk] = (away, home)
        out.append({"fetched_utc": fetched_utc, "game_pk": game_pk,
                    "away_lineup": list(away), "home_lineup": list(home)})
        written += 1
    _append(path, out)
    return {"games": len(posted or {}), "written": written}


def _record_transactions(path, rows, fetched_utc, game_date=None) -> dict:
    """First-seen rows for transaction ids not already in the store.

    Deduplicated against the WHOLE store, not just today: the feed's date
    filter is by transaction date, and a row filed late can resurface on a
    later poll of an earlier date range.
    """
    seen = {row.get("transaction_id") for row in _read_rows(path)
            if not row.get("poll")}
    out = [_marker(fetched_utc, game_date)]
    new = 0
    for row in rows or []:
        transaction_id = row.get("transaction_id")
        if transaction_id is None or transaction_id in seen:
            continue
        seen.add(transaction_id)
        out.append({"first_seen_utc": fetched_utc,
                    "transaction_id": transaction_id})
        new += 1
    _append(path, out)
    return {"fetched": len(rows or []), "new": new}


def _player_ids(slots) -> list:
    return [slot.get("person_id") for slot in slots or []]


# ---------------------------------------------------------------------------
# Event derivation (the grade-B output V3 consumes)
# ---------------------------------------------------------------------------

def events(store_dir=DEFAULT_WATCH_DIR) -> list:
    """Derive graded timing events from the three watch stores.

    Every event carries `interval: (prev_fetched_utc, fetched_utc)` -- per
    RESEARCH_V3_TIMING.md grade B, the interval IS the timestamp. The start
    is the LAST successful poll (marker) that saw the prior state, so the
    bracket is as tight as the poll cadence. An event whose prior state was
    never observed by us (first sighting) gets `interval: (None, t)` and
    `inadmissible: True` -- grade C, stored but excluded from every timing
    measurement.

    A marker that polled a DIFFERENT slate date than the event's game cannot
    open that game's bracket -- it looked at another day's games and never saw
    this one. Markers written before the date stamp existed carry no date and
    are grandfathered in (see `_last_marker_before`).

    Reads each store fully once. Sorted by interval end, then class.
    """
    directory = Path(store_dir)
    out = []
    out.extend(_probable_events(directory / PROBABLES_FILE))
    out.extend(_lineup_events(directory / LINEUPS_FILE))
    out.extend(_transaction_events(directory / TRANSACTIONS_FILE))
    out.sort(key=lambda e: (e["interval"][1], e["class"]))
    return out


def _probable_events(path) -> list:
    markers, by_game = _split_rows(path)
    events_out = []
    for game_pk, rows in by_game.items():
        for prev, cur in zip(rows, rows[1:]):
            for side in ("away", "home"):
                old = prev.get(f"{side}_probable_id")
                new = cur.get(f"{side}_probable_id")
                if old is None or new == old:
                    # None -> id is a probable being ANNOUNCED, which is not a
                    # scratch; only a change away from a listed starter counts.
                    continue
                events_out.append({
                    "class": STARTER_SCRATCH,
                    "game_pk": game_pk,
                    "interval": (_bracket_start(markers, cur["fetched_utc"],
                                                prev["fetched_utc"],
                                                _polled_date(markers,
                                                             cur["fetched_utc"])),
                                 cur["fetched_utc"]),
                    "inadmissible": False,
                    "detail": {"side": side, "from": old, "to": new},
                })
    return events_out


def _lineup_events(path) -> list:
    markers, by_game = _split_rows(path)
    events_out = []
    for game_pk, rows in by_game.items():
        for index, cur in enumerate(rows):
            prev = rows[index - 1] if index else None
            for side in ("away", "home"):
                old = tuple((prev or {}).get(f"{side}_lineup") or [])
                new = tuple(cur.get(f"{side}_lineup") or [])
                if new and not old:
                    # This side's lineup appeared. Admissible only if an
                    # earlier poll looked at the world and saw it absent.
                    start = _last_marker_before(
                        markers, cur["fetched_utc"],
                        _polled_date(markers, cur["fetched_utc"]))
                    events_out.append({
                        "class": LINEUP_POSTED,
                        "game_pk": game_pk,
                        "interval": (start, cur["fetched_utc"]),
                        "inadmissible": start is None,
                        "detail": ({"side": side} if start is not None else
                                   {"side": side, "note": "first sighting"}),
                    })
                elif old and new != old:
                    removed = [p for p in old if p not in new]
                    if removed:
                        events_out.append({
                            "class": HITTER_SCRATCH,
                            "game_pk": game_pk,
                            "interval": (_bracket_start(
                                markers, cur["fetched_utc"],
                                prev["fetched_utc"],
                                _polled_date(markers, cur["fetched_utc"])),
                                cur["fetched_utc"]),
                            "inadmissible": False,
                            "detail": {"side": side, "removed": removed},
                        })
    return events_out


def _transaction_events(path) -> list:
    markers, _ = _split_rows(path)
    events_out = []
    for row in _read_rows(path):
        if row.get("poll"):
            continue
        seen = row["first_seen_utc"]
        # No slate-date filter here: a transaction belongs to no game, and the
        # store is deduplicated against its whole history rather than per date,
        # so any earlier successful poll is a genuine lower bound on when we
        # first could have seen it.
        start = _last_marker_before(markers, seen)
        events_out.append({
            "class": TRANSACTION_SEEN,
            "transaction_id": row["transaction_id"],
            "interval": (start, seen),
            # The first poll of a run sweeps up every transaction already
            # published, with no lower bound on when -- grade C, same as a
            # first-sighting lineup, and marked the same way.
            "inadmissible": start is None,
            "detail": None if start is not None else {"note": "first sighting"},
        })
    return events_out


def _split_rows(path):
    """One pass: sorted markers as (fetched_utc, game_date), plus data rows per game_pk.

    `game_date` is None for markers written before the field existed.
    """
    markers, by_game = [], {}
    for row in _read_rows(path):
        if row.get("poll"):
            markers.append((row["fetched_utc"], row.get("game_date")))
        elif "game_pk" in row:
            by_game.setdefault(row["game_pk"], []).append(row)
    markers.sort()
    for rows in by_game.values():
        rows.sort(key=lambda r: r["fetched_utc"])
    return markers, by_game


def _polled_date(markers, stamp):
    """Which slate the poll at `stamp` was looking at, or None if unrecorded.

    A change row is written by the same poll that wrote a marker with the SAME
    fetched_utc, so that marker names the date the change was observed on.
    """
    for fetched_utc, game_date in markers:
        if fetched_utc == stamp:
            return game_date
    return None


def _last_marker_before(markers, end, game_date=None):
    """The last successful poll of `game_date` strictly before `end`, or None.

    Strict: the poll that wrote the change row also wrote a marker with the
    SAME timestamp, and that poll saw the NEW state, so it cannot open the
    bracket. ISO-8601 UTC strings from one writer compare lexicographically.

    A marker that polled a DIFFERENT slate date cannot open the bracket at
    all. The poller's date rolls over at midnight Eastern mid-run, so the last
    marker before the first poll of a new slate is a look at yesterday's games
    -- it never saw this game's lineup, and letting it open the interval would
    claim a window whose lower bound proves nothing about this game.

    Markers with no `game_date` are GRANDFATHERED and still accepted: they were
    written before the field existed, the stores are append-only evidence that
    is never rewritten, and refusing them would silently downgrade months of
    already-collected brackets to grade C on no evidence of an actual flip.
    """
    best = None
    for fetched_utc, marker_date in markers:
        if fetched_utc >= end:
            break
        if game_date and marker_date and marker_date != game_date:
            continue
        best = fetched_utc
    return best


def _bracket_start(markers, end, floor, game_date=None):
    """Tight interval start: last look that still saw the old state.

    Falls back to the previous change row's own time (`floor`) when no marker
    qualifies -- still a fetch of ours, so still grade B, just wider.
    """
    start = _last_marker_before(markers, end, game_date)
    return start if start is not None and start >= floor else floor


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------

_ABSENT = object()  # sentinel: "no previous row", never equal to any pair


def _marker(fetched_utc, game_date=None) -> dict:
    """One poll marker: when we looked, and which slate we looked at.

    `game_date` is omitted rather than nulled when unknown, so a marker never
    claims to have polled a date it did not; readers treat an absent field as
    "unknown date" and grandfather it (see `_last_marker_before`).
    """
    marker = {"fetched_utc": fetched_utc, "poll": True}
    if game_date:
        marker["game_date"] = game_date
    return marker


def _append(path, rows) -> None:
    """Append rows, first newline-terminating any interrupted previous append.

    Without the guard, a fragment left by a mid-write crash would silently
    merge with the next appended row, corrupting BOTH.
    """
    target = Path(path)
    ragged = False
    if target.exists() and target.stat().st_size:
        with target.open("rb") as handle:
            handle.seek(-1, 2)
            ragged = handle.read(1) != b"\n"
    with target.open("a", encoding="utf-8") as handle:
        if ragged:
            handle.write("\n")
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _read_rows(path) -> list:
    """Every JSON row in the file, read once.

    A corrupt line is logged and SKIPPED, never raised: the realistic cause is
    an append interrupted mid-write, and a poller meant to run unattended for
    months must not be permanently poisoned by one power cut. The design
    tolerates the loss -- a dropped data row is re-written by the next poll's
    diff, and a dropped marker merely widens a bracket, which is honest.
    """
    target = Path(path)
    if not target.exists():
        return []
    rows = []
    for number, line in enumerate(
            target.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            LOG.warning("rosterwatch: %s:%s is not valid JSON (likely an "
                        "interrupted append); skipped", target, number)
    return rows


def _utc_iso(moment) -> str:
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise RosterWatchError(
            "the clock must return a timezone-aware datetime; a naive fetch "
            "time cannot honestly bracket anything")
    return moment.astimezone(timezone.utc).isoformat()


def _eastern():
    """MLB's official timezone; a fixed -04:00 when no zone database is installed.

    Baseball is played entirely inside daylight time, and the fallback only
    disagrees with the real zone for the hour after 04:00 UTC -- midnight
    Eastern, when nothing on the slate has started or is about to.
    """
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("America/New_York")
    except Exception:  # noqa: BLE001 -- no tzdata is a deployment fact
        return timezone(timedelta(hours=-4))


_EASTERN = _eastern()


def _to_iso_date(value, clock=None) -> str:
    if value is None:
        moment = clock() if clock is not None else datetime.now(timezone.utc)
        if not isinstance(moment, datetime) or moment.tzinfo is None:
            raise RosterWatchError(
                "the clock must return a timezone-aware datetime; a naive one "
                "cannot say which slate is today")
        # MLB's date, not the UTC date. Defaulting to UTC rolled the poller
        # over to TOMORROW's slate at 00:00 UTC -- 8pm Eastern -- and the
        # poller then spent the rest of the evening asking about games that
        # had not been scheduled yet while the West Coast slate, an hour from
        # first pitch, posted its lineups and took its scratches unwatched.
        # The dense runner calls this every fifteen minutes precisely during
        # those hours, which is when it was least able to see anything.
        return moment.astimezone(_EASTERN).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(str(value).strip()).isoformat()
