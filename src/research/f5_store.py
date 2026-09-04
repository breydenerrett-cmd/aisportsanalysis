"""First-five-innings outcomes, ingested free from MLB StatsAPI.

WHY A SEPARATE STORE
--------------------
The results CSV records who won the game. M4 asks a question about innings 1-5
against innings 6-9, and the CSV cannot answer it -- the final score says
nothing about who was ahead when the starters left.

MLB's schedule endpoint hydrates a linescore, and src/providers/mlb.first_five
already knows how to settle five innings honestly, including refusing to settle
a rain-shortened game rather than counting missing half-innings as zeros. This
module just walks the dates we need and writes what comes back.

FREE, AND RESUMABLE
-------------------
StatsAPI costs no odds credits. Resumability is keyed by game_pk, not by
date: a date is only as "done" as the individual games already recorded for
it. A date-level skip looked resumable but was not -- a run interrupted
mid-date, or a schedule endpoint that momentarily returned a shorter game
list, left that date "present" with some games missing forever, because the
next run saw the date in the store and never looked at it again. That is
exactly how this store ended up with 14 silently partial dates in its first
backfill. Skipping at game_pk level instead means an interrupted or re-run
ingest always closes the actual gap, and writing a game_pk that is already
COMPLETE never happens, so a re-run is also idempotent by construction
rather than by convention.

ON POSTPONED AND SUSPENDED GAMES
---------------------------------
A schedule date is a calendar day, not a game's fate. A game postponed or
suspended before it starts still shows up under its originally scheduled
date with an empty linescore (`first_five` correctly calls that incomplete
-- 0 of 5 innings played), and the same game_pk resurfaces, completed, under
whatever later date it actually got played or resumed. Locking in the empty
snapshot the moment a game_pk is first seen -- as an earlier version of this
module did -- freezes that non-event permanently and the later date's real,
complete linescore is never recorded, because the game_pk already looks
"done". So only a game the API itself calls final (`mlb.is_final`) is
eligible to be written and locked: a genuinely final-but-short first five
(the honest rain-shortened void) is locked immediately since it will never
change, but a game that has not been decided yet is skipped this date and
picked up whichever later date it actually resolves on.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from src.providers import mlb

DEFAULT_STORE = Path("data/historical/first_five_results.jsonl")

# StatsAPI is free and ungated but it is somebody's server. One request a second
# is polite and finishes a season of dates in a few minutes.
INTER_REQUEST_SECONDS = 1.0


def read(store=DEFAULT_STORE) -> dict:
    """game_pk -> first-five record. Missing file is empty, not an error."""
    target = Path(store)
    if not target.exists():
        return {}
    out = {}
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        out[str(record.get("game_pk"))] = record
    return out


def dates_present(store=DEFAULT_STORE) -> set:
    return {r.get("date") for r in read(store).values() if r.get("date")}


def ingest(dates, store=DEFAULT_STORE, sleep=INTER_REQUEST_SECONDS) -> dict:
    """Fetch and append first-five outcomes for every game_pk not yet stored.

    Every requested date's schedule is fetched (the schedule call is free),
    but a game_pk that already has a COMPLETE record is never re-settled or
    rewritten -- that is what makes a re-run over the same date range, or a
    range that overlaps previously-ingested dates, safe: it costs a little
    repeated network time and writes nothing new for games already settled.
    A game_pk seen but not yet final (postponed/suspended/in progress) is
    left alone and revisited on whatever later date actually resolves it --
    see the module docstring's "ON POSTPONED AND SUSPENDED GAMES".
    """
    target = Path(store)
    target.parent.mkdir(parents=True, exist_ok=True)
    have = {pk for pk, r in read(store).items() if r.get("complete")}
    wanted = sorted(set(dates))

    written = failed = voided = games_skipped = not_yet_final = 0
    with target.open("a", encoding="utf-8") as handle:
        for index, day in enumerate(wanted):
            try:
                games = mlb.fetch_schedule(day)
            except Exception as exc:  # noqa: BLE001 -- one bad day must not end the run
                failed += 1
                continue
            for game in games:
                game_pk = str(game.get("gamePk"))
                if game_pk in have:
                    games_skipped += 1
                    continue
                if not mlb.is_final(game):
                    # Not decided yet as of this date -- do not lock in an
                    # empty or partial snapshot. Whatever date this game_pk
                    # actually finishes on will supply the real record.
                    not_yet_final += 1
                    continue
                settled = mlb.first_five(game)
                if not settled.get("complete"):
                    voided += 1
                record = {
                    "game_pk": game_pk,
                    "date": day,
                    "complete": settled.get("complete"),
                    "away_runs": settled.get("away_runs"),
                    "home_runs": settled.get("home_runs"),
                    "winner": settled.get("winner"),
                    "reason": settled.get("reason"),
                }
                handle.write(json.dumps(record, sort_keys=True) + "\n")
                # A game the API calls final never un-finalizes -- lock it
                # in whether the first five itself resolved to a result or a
                # genuine (rain-shortened) void, so a re-run never rewrites
                # either kind.
                have.add(game_pk)
                written += 1
            handle.flush()
            if sleep and index < len(wanted) - 1:
                time.sleep(sleep)

    return {"dates_requested": len(wanted), "games_already_complete": len(have) - written,
            "records_written": written, "games_skipped": games_skipped,
            "not_yet_final_skipped": not_yet_final,
            "dates_failed": failed, "incomplete": voided}
