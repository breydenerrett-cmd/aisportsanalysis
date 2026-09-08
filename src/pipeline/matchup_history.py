"""Batter-vs-pitcher matchup history: fetched once per pair, stored per game.

WHY THIS STORE EXISTS
----------------------
`src/pipeline/lineups.py` already has `lineup_vs_pitcher`, which answers the
question a game card needs -- "how has tonight's lineup done against tonight's
starter" -- but it is a LIVE fetcher: one MLB call per hitter, roughly 200 calls
across a full slate. `api/games.py::_enrichment_inputs` cannot call it, because
nothing on the API request path is allowed to touch the network (see that
module's docstring). So the daily loop fetches it once, here, and the API reads
the result off disk.

WHY CACHED BY (batter, pitcher) AND NOT JUST BY GAME
-----------------------------------------------------
A division race replays the same starters against the same lineups constantly.
Caching only per game_pk would refetch every pair from scratch each time two
clubs that faced each other last week meet again. Caching by the pair itself
means a pair looked up once, ever, is never looked up again -- the store only
grows the calls a genuinely new matchup requires.

THE SAME LEAKAGE WARNING AS `lineups.py`, NARROWED
----------------------------------------------------
`src/model/pointintime.py` marks the live vsPlayer endpoint LEAKY for
historical evaluation: it returns career totals to TODAY with no as-of
parameter, so a line fetched now and attached to a game from three years ago
would silently include plate appearances that hadn't happened yet at the time.

This store does not remove that property of the endpoint -- it cannot, the
data itself has no as-of parameter. What keeps this store safe is narrower and
procedural: it is built only for the CURRENT slate, once, on (or after) the day
the lineup posts, and a game_pk already written is never refetched with a later
pair value. A row here is therefore exactly as point-in-time-correct as the
posted lineup it was built from -- fine for the forward loop this store is for,
and still off-limits to a historical backfill, which must reconstruct matchups
from pitch-level data the way `src/model/rebuilt_sections.py` already does.

STORAGE SHAPE
--------------
Two files, not one:

  - `matchup_pairs.json` -- the (batter_id, pitcher_id) cache. Permanent: once
    a pair is fetched it is never refetched, matching the brief exactly. Keyed
    `"{batter_id}:{pitcher_id}"`.
  - `matchup_history.jsonl` -- one row per game_pk, `{"home": ..., "away":
    ...}` where the key is the BATTING side (mirrors the shape
    `src/cli.py::cmd_brief` already builds in memory for `matchups_by_pk`, so
    `read()` is a drop-in for that parameter). `home` is the home lineup
    against the away probable starter, and vice versa.
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

from src.paths import historical_path
from src.pipeline import lineup_store, lineups
from src.providers import mlb

DEFAULT_STORE = historical_path("matchup_history.jsonl")
DEFAULT_PAIR_CACHE = historical_path("matchup_pairs.json")

# Light throttle between actual network fetches (cache hits are free and skip
# this entirely). ~200 new pairs at this rate is ~30 seconds, well inside
# budget for a nightly loop step.
THROTTLE_SECONDS = 0.15

# Same bar `lineups.lineup_vs_pitcher` uses -- restated here rather than
# imported as a private constant so this module's storage contract does not
# silently change if that one is retuned.
MIN_LINEUP_AT_BATS = lineups.MIN_LINEUP_AT_BATS


class MatchupHistoryError(RuntimeError):
    """Raised when the matchup history store cannot be built or read."""


def build(game_date, lineup_path=lineup_store.DEFAULT_STORE, path=DEFAULT_STORE,
          pair_cache_path=DEFAULT_PAIR_CACHE, resume=True,
          fetch_games=mlb.fetch_games,
          fetch_batter_vs_pitcher=lineups.batter_vs_pitcher,
          sleep=time.sleep, throttle=THROTTLE_SECONDS, timeout=20) -> dict:
    """Fetch batter-vs-pitcher history for every posted-lineup game on a date.

    Resumable by game_pk: a game already written to `path` is skipped, so a
    build interrupted mid-slate picks up where it left off on rerun. A game
    with no posted lineup yet is skipped without being marked failed -- an
    unposted lineup is a normal, temporary state (see `lineups.fetch_lineups`),
    and the next run's cheap schedule call will find it once it posts.
    """
    iso = game_date.isoformat() if isinstance(game_date, date) else str(game_date)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    have = {row.get("game_pk") for row in _read_rows(path)} if resume else set()

    report = {"date": iso, "games": 0, "written": 0, "skipped_stored": 0,
              "skipped_no_lineup": 0, "failed": 0,
              "pairs_fetched": 0, "pairs_cached": 0}

    try:
        games = fetch_games(iso, timeout=timeout)
    except mlb.MLBError as exc:
        report["error"] = str(exc)
        return report

    posted = lineup_store.read(lineup_path)
    pair_cache = _read_json(pair_cache_path, {})
    dirty = False

    for game in games:
        pk = game.get("game_pk")
        if not pk:
            continue
        report["games"] += 1
        if pk in have:
            report["skipped_stored"] += 1
            continue

        record = posted.get(str(pk))
        if not record:
            report["skipped_no_lineup"] += 1
            continue

        row = {"date": iso, "game_pk": pk,
               "away_probable_id": game.get("away_probable_id"),
               "home_probable_id": game.get("home_probable_id")}
        wrote_any_side = False
        for lineup_side, pitcher_key in (("away", "home_probable_id"),
                                         ("home", "away_probable_id")):
            lineup = record.get(lineup_side) or []
            pitcher_id = game.get(pitcher_key)
            if not lineup or not pitcher_id:
                row[lineup_side] = None
                continue
            result, calls = _lineup_vs_pitcher_cached(
                lineup, pitcher_id, pair_cache, fetch_batter_vs_pitcher,
                sleep, throttle, timeout)
            row[lineup_side] = result
            report["pairs_fetched"] += calls["fetched"]
            report["pairs_cached"] += calls["cached"]
            if calls["fetched"]:
                dirty = True
            wrote_any_side = True

        if not wrote_any_side:
            report["skipped_no_lineup"] += 1
            continue

        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        report["written"] += 1

    if dirty:
        _write_json(pair_cache_path, pair_cache)
    report["path"] = str(target)
    return report


def _lineup_vs_pitcher_cached(lineup, pitcher_id, pair_cache,
                              fetch_batter_vs_pitcher, sleep, throttle,
                              timeout) -> tuple:
    """Same aggregate shape as `lineups.lineup_vs_pitcher`, but every batter
    is looked up in `pair_cache` first and only fetched on a miss.
    """
    entries, total_ab, total_hits, total_hr, total_k = [], 0, 0, 0, 0
    fetched, cached = 0, 0
    throttled = False

    for slot in lineup:
        person_id = slot.get("person_id")
        if not person_id:
            continue
        key = f"{person_id}:{pitcher_id}"
        if key in pair_cache:
            line = pair_cache[key]
            cached += 1
        else:
            if throttled:
                sleep(throttle)
            throttled = True
            try:
                line = fetch_batter_vs_pitcher(person_id, pitcher_id, timeout=timeout)
            except mlb.MLBError:
                continue
            pair_cache[key] = line
            fetched += 1

        entry = dict(line, name=slot.get("name"), order=slot.get("order"),
                     person_id=person_id)
        entries.append(entry)
        total_ab += line.get("at_bats") or 0
        total_hits += line.get("hits") or 0
        total_hr += line.get("home_runs") or 0
        total_k += line.get("strikeouts") or 0

    result = {
        "batters": entries,
        "total_at_bats": total_ab,
        "total_hits": total_hits,
        "total_home_runs": total_hr,
        "total_strikeouts": total_k,
        "aggregate_avg": round(total_hits / total_ab, 3) if total_ab else None,
        "usable": total_ab >= MIN_LINEUP_AT_BATS,
        "reason": None if total_ab >= MIN_LINEUP_AT_BATS else (
            f"the whole lineup has only {total_ab} career at-bats against him; "
            f"a read needs at least {MIN_LINEUP_AT_BATS}"),
    }
    return result, {"fetched": fetched, "cached": cached}


def read(path=DEFAULT_STORE) -> dict:
    """Stored matchup history keyed by str(game_pk) -> {"home": ..., "away": ...}.

    Drop-in shape for `briefing.build_slate(matchups_by_pk=...)`: the same
    dict `src/cli.py::cmd_brief` builds live, in memory, every run. Missing
    file is {}, not an error -- the same absent-is-safe contract every other
    store in this project follows.
    """
    return {str(row["game_pk"]): {"home": row.get("home"), "away": row.get("away")}
            for row in _read_rows(path) if row.get("game_pk")}


def read_pairs(path=DEFAULT_PAIR_CACHE) -> dict:
    """The raw (batter_id, pitcher_id) pair cache, keyed "batter_id:pitcher_id"."""
    return _read_json(path, {})


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
            raise MatchupHistoryError(f"{target}:{number} is not valid JSON") from exc
    return rows


def _read_json(path, default):
    target = Path(path)
    if not target.exists():
        return default
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MatchupHistoryError(f"{target} is not valid JSON") from exc


def _write_json(path, data):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
