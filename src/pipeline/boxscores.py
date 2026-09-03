"""Per-game, per-player box lines: the settlement substrate for props.

WHY THIS EXISTS
----------------
A moneyline or a total settles off the final score alone -- `history.py`
already carries that. No batter prop ("2+ hits", "total bases") and no
pitcher prop beyond strikeouts ("outs recorded", "earned runs allowed") can
ever be graded, backtested, or self-reviewed without the box line each
player actually produced that night. The MLB Stats API serves that for free,
keyless, back to 2023 (`src.providers.mlb.fetch_boxscore` /
`fetch_linescore`); nothing in this repo stored it before this module.

WHAT GETS WRITTEN
-------------------
For every FINAL game on a date: one row per pitcher who recorded a
pitching stat, one row per batter who recorded a batting stat, and one
linescore row for the game (runs by inning, first-inning scoring, first
team to score). Rows land in `data/processed/boxscores_<yyyy>.jsonl`,
keyed by the game's own date (not the day this pipeline happens to run),
so a late backfill still files into the correct season's store.

RESUMABLE, NEVER REWRITTEN
----------------------------
Idempotent by `(game_pk, player_id, type)` for player rows and
`(game_pk, "linescore")` for the linescore row. A game already present in
the store (any row carrying its game_pk) is skipped entirely on a rerun --
this pipeline never edits or removes a line already written, matching the
append-only convention of every other forward/historical store in this
project (`lineup_store.py`, `bullpen.py`). `observed_utc` records when this
process fetched the line, not when the game happened -- box lines do not
change after a game goes final, so the two are expected to diverge only by
how long after the game this ran.

A date with zero FINAL games (off-day, or fetched before any game ended)
writes nothing at all -- unlike `lineup_store`'s empty marker, this store is
keyed by game_pk, and "no games yet" is retried for free at zero cost the
next time `ingest_date` runs for that date, no marker needed to distinguish
it from "never tried".
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from src.paths import data_path
from src.providers import mlb


def _default_store_path(iso_date: str) -> Path:
    year = iso_date[:4]
    return data_path("processed", f"boxscores_{year}.jsonl")


class BoxscoresError(RuntimeError):
    """Raised when the boxscore store cannot be read."""


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
            raise BoxscoresError(f"{target}:{number} is not valid JSON") from exc
    return rows


def _game_pks_in_store(path) -> set:
    """Every game_pk already present in the store, regardless of row type.

    A game is fetched atomically (all its rows written in one pass below),
    so the presence of ANY row for a game_pk is treated as "already done" --
    this is what makes a rerun skip whole games instead of refetching them.
    """
    return {row.get("game_pk") for row in _read_rows(path) if row.get("game_pk")}


def build_rows(game_date, game_pk, box: dict, linescore: dict, observed_utc: str) -> list:
    """Turn one game's raw boxscore + linescore into the rows this store writes.

    Pure and network-free -- exercised directly by tests against fixtures, and
    called by `ingest_date` after the two live fetches.
    """
    parsed_box = mlb.parse_boxscore(game_pk, box)
    parsed_line = mlb.parse_linescore(game_pk, linescore)
    rows = []
    for pitcher in parsed_box["pitchers"]:
        rows.append({
            "type": "pitcher",
            "date": game_date,
            "observed_utc": observed_utc,
            **pitcher,
        })
    for batter in parsed_box["batters"]:
        rows.append({
            "type": "batter",
            "date": game_date,
            "observed_utc": observed_utc,
            **batter,
        })
    rows.append({
        "type": "linescore",
        "date": game_date,
        "observed_utc": observed_utc,
        **parsed_line,
    })
    return rows


def ingest_date(game_date, path=None, resume=True, timeout=20,
                 fetch_results=mlb.fetch_results,
                 fetch_boxscore=mlb.fetch_boxscore,
                 fetch_linescore=mlb.fetch_linescore,
                 sleep=time.sleep, clock=None) -> dict:
    """Append box + linescore rows for every FINAL game on one date.

    Resumable: games already in the store (by game_pk) are skipped. A single
    game's fetch failing is recorded in `errors` and does not block the rest
    of the date's slate -- one bad game must not cost the others.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    iso = mlb._validate_date(game_date)
    target = Path(path) if path else _default_store_path(iso)
    target.parent.mkdir(parents=True, exist_ok=True)

    have = _game_pks_in_store(target) if resume else set()

    result = fetch_results(iso, timeout=timeout)
    final_games = result["final"]

    report = {"date": iso, "games_seen": len(final_games), "games_written": 0,
              "games_skipped": 0, "pitcher_rows": 0, "batter_rows": 0,
              "linescore_rows": 0, "errors": [], "path": str(target)}

    throttled = False
    for game in final_games:
        game_pk = game.get("game_pk")
        if game_pk in have:
            report["games_skipped"] += 1
            continue
        if throttled:
            sleep(0.3)
        throttled = True
        try:
            box = fetch_boxscore(game_pk, timeout=timeout)
            linescore = fetch_linescore(game_pk, timeout=timeout)
        except mlb.MLBError as exc:
            # Left ABSENT, not marked -- a rerun with resume=True retries it.
            report["errors"].append({"game_pk": game_pk, "error": str(exc)})
            continue

        rows = build_rows(iso, game_pk, box, linescore,
                           clock().isoformat().replace("+00:00", "Z"))
        with target.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")

        report["games_written"] += 1
        report["pitcher_rows"] += sum(1 for r in rows if r["type"] == "pitcher")
        report["batter_rows"] += sum(1 for r in rows if r["type"] == "batter")
        report["linescore_rows"] += sum(1 for r in rows if r["type"] == "linescore")

    return report


def ingest_range(start, end, path=None, resume=True, timeout=20,
                  on_date=None, **kwargs) -> dict:
    """Drive `ingest_date` across a range of dates. Resumable, one bad date
    does not abort the rest -- same shape as `mlb.backfill_results`."""
    totals = {"dates": 0, "games_written": 0, "games_skipped": 0,
              "pitcher_rows": 0, "batter_rows": 0, "linescore_rows": 0,
              "errors": []}
    for iso in mlb.iter_dates(start, end):
        report = ingest_date(iso, path=path, resume=resume, timeout=timeout,
                              **kwargs)
        totals["dates"] += 1
        totals["games_written"] += report["games_written"]
        totals["games_skipped"] += report["games_skipped"]
        totals["pitcher_rows"] += report["pitcher_rows"]
        totals["batter_rows"] += report["batter_rows"]
        totals["linescore_rows"] += report["linescore_rows"]
        totals["errors"].extend(
            {"date": iso, **e} for e in report["errors"])
        if on_date:
            on_date(report)
    return totals


def read(path) -> list:
    """All rows in a store, in file order."""
    return _read_rows(path)
