"""Historical posted-lineup store: resumable, per-date cached, honest about off-days.

WHY POSTED LINEUPS NEED THEIR OWN STORE
---------------------------------------
The rebuilt detectors reason about the nine hitters actually sent out, not the
club in aggregate, and they need that for PAST games. `lineups.fetch_lineups`
returns the posted lineup for any historical date -- the schedule hydrate keeps
it -- but two full seasons is ~370 dates of network calls, and a run that long
WILL be interrupted. So lineups are fetched once per date and appended to a
JSONL store, exactly the shape `bullpen.build_log` already proved out.

WHY THE EMPTY MARKER IS NOT OPTIONAL
------------------------------------
A date with no rows is ambiguous: an off-day, or a date the build never reached.
Those are different facts, and confusing them puts silent holes in the backtest
while looking like complete coverage. Every attempted date therefore writes
something -- lineup rows, or an explicit {"date", "empty": true} marker -- so
absence from the file always means "never fetched" and nothing else.

WHY HANDEDNESS IS EXTENDED HERE
-------------------------------
The detectors read lineups next to bat sides. Handedness is biographical and
stable, so the cheap move is to collect every person_id the build saw and top up
the shared handedness cache once at the end, rather than per date or -- worse --
at detector time, when a network call would be a surprise.
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

from src.paths import historical_path
from src.pipeline import lineups
from src.providers import mlb

DEFAULT_STORE = historical_path("lineups.jsonl")

# Light throttle between dates. The schedule endpoint is cheap, but ~370 dates
# back to back is exactly the shape of traffic that gets a client rate-limited.
THROTTLE_SECONDS = 0.3


class LineupStoreError(RuntimeError):
    """Raised when the lineup store cannot be built or read."""


def build(dates, path=DEFAULT_STORE, resume=True, on_date=None,
          fetch=lineups.fetch_lineups, fetch_handedness=lineups.fetch_handedness,
          sleep=time.sleep, timeout=20) -> dict:
    """Fetch posted lineups for each date and append them to the store.

    Resumable by date: a date already present in the store (as rows or as an
    empty marker) is skipped, so an interrupted build continues rather than
    refetching. `fetch`, `fetch_handedness` and `sleep` are injected so tests
    run without the network or the wait.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    have = {row.get("date") for row in _read_rows(path)} if resume else set()

    report = {"dates": 0, "skipped": 0, "games": 0, "failed": 0}
    person_ids = set()
    throttled = False
    for value in dates:
        iso = value.isoformat() if isinstance(value, date) else str(value).strip()
        if iso in have:
            report["skipped"] += 1
            continue
        if throttled:
            sleep(THROTTLE_SECONDS)
        throttled = True
        try:
            day = fetch(iso, timeout=timeout)
        except mlb.MLBError:
            # A failed date is left ABSENT, not marked empty -- absent means
            # "never fetched", and a rerun with resume=True will retry it.
            report["failed"] += 1
            continue

        rows = []
        for game_pk in sorted(day):
            record = day[game_pk]
            rows.append({"date": iso, "game_pk": game_pk,
                         "away": record.get("away") or [],
                         "home": record.get("home") or []})
        with target.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
            if not rows:
                handle.write(json.dumps({"date": iso, "empty": True}) + "\n")

        for row in rows:
            for side in ("away", "home"):
                for slot in row[side]:
                    if slot.get("person_id"):
                        person_ids.add(slot["person_id"])
        report["dates"] += 1
        report["games"] += len(rows)
        if on_date:
            on_date({"date": iso, "games": len(rows)})

    # One top-up at the end rather than per date: fetch_handedness skips ids
    # already cached and batches the rest in chunks itself.
    if person_ids:
        fetch_handedness(sorted(person_ids), timeout=timeout)
    report["person_ids"] = len(person_ids)
    report["path"] = str(target)
    return report


def read(path=DEFAULT_STORE) -> dict:
    """Stored lineups keyed by game_pk. Empty markers are coverage, not games.

    Keys are str, not the int JSON preserved from the schedule: the results
    store round-trips game_pk through CSV, so its keys come back as str, and a
    join between the two stores must agree on type or it silently matches
    nothing (this exact str/int mismatch once silently broke a since-deleted
    bullpen-grading module -- it always found zero matches and nobody noticed).
    """
    return {str(row["game_pk"]): row for row in _read_rows(path)
            if not row.get("empty") and row.get("game_pk")}


def covered_dates(path=DEFAULT_STORE) -> set:
    """Every date the build actually attempted, off-days included."""
    return {row.get("date") for row in _read_rows(path) if row.get("date")}


def _read_rows(path) -> list:
    target = Path(path)
    if not target.exists():
        return []
    rows = []
    for number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise LineupStoreError(f"{target}:{number} is not valid JSON") from exc
    return rows
