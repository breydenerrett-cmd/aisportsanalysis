"""Umpire watch: bracket the umpire-crew reveal between two of our own polls.

WHY THIS EXISTS
---------------
`docs/RESEARCH_V3_UMPIRE_CLASS.md` pre-registers a 5th V3 timing class,
`umpire_crew_revealed`: does the market react measurably when the MLB Stats
API reveals a game's 4-person umpire crew? Verified live 2026-09-02 against
`src.providers.mlb.fetch_officials` (the same host `fetch_schedule` already
calls): the `officials` hydrate is EMPTY while a game is `Scheduled`, and
becomes a populated crew by `Pre-Game`/`Warmup`, observed 3.6-4.6 hours
before first pitch. That reveal TIME is unrecoverable if not captured
forward -- MLB does not publish when a crew was assigned, only that it now
shows one -- so this module exists to observe the transition itself, the
same "capture now" principle behind `rosterwatch`.

MODELED ON `src.pipeline.rosterwatch`
--------------------------------------
Same bracketed-observation convention: a marker row per successful poll of a
date records that we looked and what we saw (or didn't), so a later reveal
can be bracketed between the LAST poll that still saw no crew and the FIRST
poll that saw one -- grade B, admissible. A reveal with no prior poll to
bracket against (the game's very first sighting, e.g. a doubleheader added
late) is grade C and stored with `prev_poll_utc: null`, never guessed at.

Unlike rosterwatch, the bracket is computed and embedded directly into the
data row at write time (`prev_poll_utc`) rather than reconstructed later by
a separate `events()` pass over markers -- there is exactly one state change
per game worth recording (unrevealed -> revealed), so there is no need for
rosterwatch's fuller change-log-plus-derivation machinery. `events()` still
exists, as a thin adapter into the same `{class, interval, inadmissible,
detail}` shape rosterwatch produces, so `src.research.timingreport` can fold
this store's rows into its per-class accounting without special-casing it.

WHAT COUNTS AS A STATE CHANGE, AND WHY ONLY ONE PER GAME
---------------------------------------------------------
`docs/RESEARCH_V3_UMPIRE_CLASS.md` defines the event as "the first poll
where officials become non-empty". Once a game's reveal has been recorded,
later polls of that same game_pk are treated as unchanged regardless of
whether the crew composition is re-served identically or (rarely) corrected
-- exactly one row per game, matching the pre-registered event definition
rather than inventing an undefined second event type. A game that reverts to
an empty crew after being revealed (a postponement resetting the game's
status) is likewise not un-recorded: the store is append-only and the first
reveal stands as history.

TWO DATES EVERY RUN
--------------------
Each poll fetches TODAY's and TOMORROW's slate (MLB's Eastern day, the same
rollover rosterwatch's docstring explains). Tomorrow's games are essentially
always unrevealed (the crew posts hours, not a day, before first pitch), so
polling tomorrow mainly plants the marker that makes tomorrow's eventual
reveal admissible once it becomes today -- without it, a game seen for the
first time on the morning of its own game day, already in `Pre-Game`, would
be a first sighting with no bracket at all.

FAILURE SEMANTICS
------------------
Each date is fetched independently; a failure on one date is recorded in the
report's `errors`, writes no marker for that date, and never blocks the
other date. A poll never raises for a network failure.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.paths import data_path
from src.providers import mlb

LOG = logging.getLogger(__name__)

DEFAULT_WATCH_DIR = data_path("watch")

UMPIRES_FILE = "umpires_watch.jsonl"

# Named exactly as docs/RESEARCH_V3_UMPIRE_CLASS.md names it.
UMPIRE_CREW_REVEALED = "umpire_crew_revealed"


class UmpireWatchError(RuntimeError):
    """Raised when the watch store cannot be read or a clock is unusable."""


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------

def poll(game_date=None, watch_dir=DEFAULT_WATCH_DIR,
         fetch_officials=mlb.fetch_officials, clock=None, timeout=20) -> dict:
    """One capture pass over today's and tomorrow's umpire crews.

    `game_date` fixes "today" (for tests); by default it comes from the same
    clock that stamps the rows, converted to MLB's Eastern day. `clock` is an
    injectable callable returning an aware UTC datetime, so tests control
    every recorded timestamp exactly. Each date is independent: a failure
    fetching one date is recorded in `errors` and never blocks the other.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    today = _to_iso_date(game_date, clock)
    tomorrow = (date.fromisoformat(today) + timedelta(days=1)).isoformat()

    directory = Path(watch_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / UMPIRES_FILE

    report = {"dates": [today, tomorrow], "dir": str(directory),
              "errors": [], "per_date": {}}

    already_revealed = _already_revealed(path)

    for game_date_str in (today, tomorrow):
        try:
            records = fetch_officials(game_date_str, timeout=timeout)
        except UmpireWatchError:
            raise  # our own store/clock problems are bugs, not weather
        except Exception as exc:  # network failure must not kill the poll
            LOG.warning("umpirewatch: %s fetch failed and was skipped: %s",
                       game_date_str, exc)
            report["errors"].append({"date": game_date_str, "error": str(exc)})
            continue

        observed_utc = _utc_iso(clock())
        markers = _markers_for_date(path, game_date_str)
        written = 0
        out_rows = [_marker(observed_utc, game_date_str)]

        for record in records:
            game_pk = record.get("game_pk")
            if game_pk is None:
                continue
            crew = record.get("officials") or []
            if not crew or game_pk in already_revealed:
                continue  # not yet revealed, or already recorded -- no change
            already_revealed.add(game_pk)
            prev_poll_utc = _last_marker_before(markers, observed_utc)
            out_rows.append({
                "observed_utc": observed_utc,
                "game_pk": game_pk,
                "game_date": game_date_str,
                "commence_time": record.get("first_pitch_utc"),
                "game_state": record.get("game_state"),
                "prev_poll_utc": prev_poll_utc,
                "crew": crew,
                "home_plate_umpire": mlb.home_plate_umpire(crew),
                "revealed": True,
            })
            written += 1

        _append(path, out_rows)
        report["per_date"][game_date_str] = {"games": len(records),
                                             "written": written}

    return report


def _already_revealed(path) -> set:
    """Every game_pk this store has already recorded a reveal for.

    One pass over the store; a game already revealed is never re-written,
    which is both the idempotency guarantee and the "exactly one event per
    game" rule `docs/RESEARCH_V3_UMPIRE_CLASS.md` defines.
    """
    return {row["game_pk"] for row in _read_rows(path)
            if not row.get("poll") and row.get("revealed")}


def _markers_for_date(path, game_date_str) -> list:
    """Ascending observed_utc for every marker that polled this exact date."""
    out = [row["observed_utc"] for row in _read_rows(path)
           if row.get("poll") and row.get("game_date") == game_date_str]
    out.sort()
    return out


def _last_marker_before(markers, end):
    """The last marker strictly before `end`, or None (first sighting).

    `markers` already holds only this exact game_date's markers (see
    `_markers_for_date`), so no cross-date grandfathering is needed here --
    every umpirewatch marker has carried its date since the store's first
    row.
    """
    best = None
    for observed_utc in markers:
        if observed_utc >= end:
            break
        best = observed_utc
    return best


# ---------------------------------------------------------------------------
# Event derivation (the grade-A/B/C output V3 consumes)
# ---------------------------------------------------------------------------

def events(store_dir=DEFAULT_WATCH_DIR) -> list:
    """Derive graded timing events from the umpire watch store.

    Thin adapter: the store's data rows already carry their own bracket
    (`prev_poll_utc`), computed at write time, so this just reshapes them
    into the `{class, interval, inadmissible, detail}` shape
    `src.pipeline.rosterwatch.events` produces, so
    `src.research.timingreport` can fold both stores' events into one
    per-class accounting without special-casing either.
    """
    path = Path(store_dir) / UMPIRES_FILE
    out = []
    for row in _read_rows(path):
        if row.get("poll") or not row.get("revealed"):
            continue
        out.append({
            "class": UMPIRE_CREW_REVEALED,
            "game_pk": row.get("game_pk"),
            "interval": (row.get("prev_poll_utc"), row["observed_utc"]),
            "inadmissible": row.get("prev_poll_utc") is None,
            "detail": {"home_plate_umpire": row.get("home_plate_umpire"),
                       "crew_size": len(row.get("crew") or []),
                       "game_state": row.get("game_state")},
        })
    out.sort(key=lambda e: (e["interval"][1], e["class"]))
    return out


# ---------------------------------------------------------------------------
# Plumbing (mirrors src.pipeline.rosterwatch's, kept independent on purpose --
# this module must work even if rosterwatch's storage format ever changes)
# ---------------------------------------------------------------------------

def _marker(observed_utc, game_date_str) -> dict:
    return {"observed_utc": observed_utc, "poll": True, "game_date": game_date_str}


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

    A corrupt line is logged and SKIPPED, never raised: the realistic cause
    is an append interrupted mid-write, and a poller meant to run unattended
    for months must not be permanently poisoned by one power cut.
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
            LOG.warning("umpirewatch: %s:%s is not valid JSON (likely an "
                       "interrupted append); skipped", target, number)
    return rows


def _utc_iso(moment) -> str:
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise UmpireWatchError(
            "the clock must return a timezone-aware datetime; a naive fetch "
            "time cannot honestly bracket anything")
    return moment.astimezone(timezone.utc).isoformat()


def _eastern():
    """MLB's official timezone; a fixed -04:00 when no zone database is installed.

    Copied from `src.pipeline.rosterwatch._eastern` rather than imported: the
    two modules' storage formats are kept independent on purpose (see the
    module docstring), and this helper is small enough that duplicating it
    costs far less than coupling two forward-capture modules' internals.
    """
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("America/New_York")
    except Exception:  # noqa: BLE001 -- no tzdata is a deployment fact
        return timezone(timedelta(hours=-4))


_EASTERN = _eastern()


def _to_iso_date(value, clock=None) -> str:
    """MLB's date for "today", from the injected clock -- not the UTC date.

    Same rollover rosterwatch's docstring explains: defaulting to the UTC
    date rolls "today" over at 8pm Eastern, hours before the last games of
    the night have even started.
    """
    if value is None:
        moment = clock() if clock is not None else datetime.now(timezone.utc)
        if not isinstance(moment, datetime) or moment.tzinfo is None:
            raise UmpireWatchError(
                "the clock must return a timezone-aware datetime; a naive "
                "one cannot say which slate is today")
        return moment.astimezone(_EASTERN).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(str(value).strip()).isoformat()


# ---------------------------------------------------------------------------
# Standalone entry point: python3 -m src.pipeline.umpirewatch
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="python3 -m src.pipeline.umpirewatch",
        description="Poll today's and tomorrow's umpire crews (free MLB "
                    "endpoint, zero odds credits).")
    parser.add_argument("--date", default=None,
                        help="Override 'today' (YYYY-MM-DD); default is "
                             "MLB's current Eastern date.")
    parser.add_argument("--events", action="store_true",
                        help="Print derived events instead of polling.")
    args = parser.parse_args(argv)

    if args.events:
        for event in events():
            print(json.dumps(event, sort_keys=True))
        return 0

    report = poll(game_date=args.date)
    for game_date_str in report["dates"]:
        detail = report["per_date"].get(game_date_str)
        print(f"  {game_date_str}: " + (
            "FAILED (skipped)" if detail is None
            else f"games={detail['games']} reveals_written={detail['written']}"))
    for error in report["errors"]:
        print(f"  ERROR {error['date']}: {error['error']}", file=sys.stderr)
    print(f"  -> {report['dir']}")
    return 1 if len(report["errors"]) == len(report["dates"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
