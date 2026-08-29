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
StatsAPI costs no odds credits. The store is keyed by date and skipped when
already present, so an interrupted run resumes instead of refetching.
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
    """Fetch and append first-five outcomes for each date not already stored."""
    target = Path(store)
    target.parent.mkdir(parents=True, exist_ok=True)
    done = dates_present(store)
    wanted = [d for d in sorted(set(dates)) if d not in done]

    written = failed = voided = 0
    with target.open("a", encoding="utf-8") as handle:
        for index, day in enumerate(wanted):
            try:
                games = mlb.fetch_schedule(day)
            except Exception as exc:  # noqa: BLE001 -- one bad day must not end the run
                failed += 1
                continue
            for game in games:
                settled = mlb.first_five(game)
                if not settled.get("complete"):
                    voided += 1
                record = {
                    "game_pk": str(game.get("gamePk")),
                    "date": day,
                    "complete": settled.get("complete"),
                    "away_runs": settled.get("away_runs"),
                    "home_runs": settled.get("home_runs"),
                    "winner": settled.get("winner"),
                    "reason": settled.get("reason"),
                }
                handle.write(json.dumps(record, sort_keys=True) + "\n")
                written += 1
            handle.flush()
            if sleep and index < len(wanted) - 1:
                time.sleep(sleep)

    return {"dates_requested": len(wanted), "dates_skipped": len(done),
            "records_written": written, "dates_failed": failed,
            "incomplete": voided}
