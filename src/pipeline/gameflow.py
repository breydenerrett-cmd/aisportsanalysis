"""Per-game play-by-play + win probability: the substrate a post-mortem needs.

WHY THIS EXISTS
----------------
`boxscores_*.jsonl` stores one line per player per game -- season/game totals
with no inning, no sequence, no leverage. Settlement could therefore record
THAT a bet lost and never anything about WHY: no pivot, no decisive moment,
no "the game turned here". This store fills exactly that gap, from the free,
keyless MLB Stats API (`src.providers.mlb.fetch_play_by_play` /
`fetch_win_probability`).

POST-GAME ONLY -- THIS MUST NEVER REACH THE DECISION PATH
-----------------------------------------------------------
Every row here describes something that happened DURING the game it belongs
to. Reading any of it at decision time would leak the outcome itself, which
is the most complete future leak available. Three structural guards, not a
convention:

  1. The store is written to `data/processed/gameflow_<yyyy>.jsonl` -- a
     filename no `src.core.asof` StoreSpec points at, and deliberately NOT
     matching the `boxscores_*.jsonl` glob that `src.engine.settle_slate`
     already reads.
  2. `src.core.asof._default_stores()` does not register it, so `as_of()`
     cannot surface a single field of it at any T.
  3. tests/test_gameflow_pit.py proves both by injection (tamper the store,
     assert the snapshot does not move by one byte) and by import graph (no
     module on the decision path imports this one).

ZERO ODDS CREDITS
------------------
statsapi.mlb.com is free and keyless. This module never imports
`src.providers.odds` and never touches `src.pipeline.creditlog` -- the credit
floor (docs/COLLECTION_POLICY.md) is untouched by any volume of ingest here.
tests/test_gameflow_pit.py asserts that too.

RESUMABLE, NEVER REWRITTEN
----------------------------
Append-only and idempotent by `game_pk`: a game with ANY row already in the
store is skipped whole on a rerun, matching `src.pipeline.boxscores`. A game
whose fetch fails is left ABSENT (recorded in `errors`), never marked, so a
rerun retries it for free. `observed_utc` records when this process fetched
the game, not when the game happened.

WIN PROBABILITY IS NEVER FABRICATED
-------------------------------------
Each game writes one `type="game"` row carrying `wp_available`. When MLB
serves no win-probability series for a game, every play row has
`home_win_prob=None` / `wp_source=None` and `wp_available` is False -- the
post-mortem reader (`src.review.postmortem`) then falls back to its own
documented run-margin proxy and LABELS it as a proxy. Nothing in this module
interpolates, back-fills, or models a probability.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from src.paths import data_path
from src.providers import mlb

ROW_TYPE_PLAY = "play"
ROW_TYPE_GAME = "game"


class GameFlowError(RuntimeError):
    """Raised when the game-flow store cannot be read."""


def default_store_path(iso_date: str) -> Path:
    """`data/processed/gameflow_<yyyy>.jsonl`, keyed by the GAME's own year.

    Deliberately not `boxscores_*` -- `src.engine.settle_slate.BOXSCORES_GLOB`
    reads that pattern, and this data must never be swept up by a reader that
    was written for box lines.
    """
    return data_path("processed", f"gameflow_{iso_date[:4]}.jsonl")


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
            raise GameFlowError(f"{target}:{number} is not valid JSON") from exc
    return rows


def read(path) -> list:
    """All rows in a store, in file order."""
    return _read_rows(path)


def game_pks_in_store(path) -> set:
    """Every game_pk already present, regardless of row type -- the resume set."""
    return {row.get("game_pk") for row in _read_rows(path) if row.get("game_pk")}


def build_rows(game_date, game_pk, play_by_play: dict, win_probability,
               observed_utc: str, game_meta: dict | None = None) -> list:
    """Turn one game's raw play-by-play (+ WP) into the rows this store writes.

    Pure and network-free -- exercised directly by tests against fixtures, and
    called by `ingest_date` after the two live fetches. The `type="game"` row
    is written LAST so a truncated write can never look complete: a reader
    that finds the game row knows every play row for that game is above it.
    """
    parsed = mlb.parse_play_by_play(game_pk, play_by_play, win_probability)
    plays = parsed["plays"]
    rows = [{"type": ROW_TYPE_PLAY, "date": game_date,
             "observed_utc": observed_utc, **play} for play in plays]

    meta = game_meta or {}
    last = plays[-1] if plays else {}
    rows.append({
        "type": ROW_TYPE_GAME,
        "date": game_date,
        "observed_utc": observed_utc,
        "game_pk": parsed["game_pk"],
        "n_plays": len(plays),
        "wp_available": parsed["wp_available"],
        "home_team": meta.get("home_team"),
        "away_team": meta.get("away_team"),
        "home_score_final": meta.get("home_score", last.get("home_score_after")),
        "away_score_final": meta.get("away_score", last.get("away_score_after")),
        "home_probable_id": meta.get("home_probable_id"),
        "away_probable_id": meta.get("away_probable_id"),
        # The pitcher who actually threw the first pitch of each half-inning
        # the opposing side batted -- the ONLY honest way to detect a late
        # scratch after the fact, since a probable is a pre-game claim and
        # this is the game's own record of who took the ball.
        "home_starter_id": _starter_id(plays, "top"),
        "away_starter_id": _starter_id(plays, "bottom"),
    })
    return rows


def _starter_id(plays, half: str):
    """The pitcher on the mound for the first play of `half` -- the real starter.

    `half="top"` is the HOME team's pitcher (the away side bats the top half).
    Returns None for a game with no plays in that half, never a guess.
    """
    for play in plays:
        if play.get("half") == half:
            return play.get("pitcher_id")
    return None


def ingest_date(game_date, path=None, resume=True, timeout=20,
                fetch_results=mlb.fetch_results,
                fetch_play_by_play=mlb.fetch_play_by_play,
                fetch_win_probability=mlb.fetch_win_probability,
                sleep=time.sleep, clock=None) -> dict:
    """Append play + game rows for every FINAL game on one date.

    Resumable: games already in the store (by game_pk) are skipped. A single
    game's fetch failing is recorded in `errors` and does not block the rest
    of the date's slate -- one bad game must not cost the others.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    iso = mlb._validate_date(game_date)
    target = Path(path) if path else default_store_path(iso)
    target.parent.mkdir(parents=True, exist_ok=True)

    have = game_pks_in_store(target) if resume else set()

    result = fetch_results(iso, timeout=timeout)
    final_games = result["final"]

    report = {"date": iso, "games_seen": len(final_games), "games_written": 0,
              "games_skipped": 0, "play_rows": 0, "games_without_wp": 0,
              "errors": [], "path": str(target)}

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
            pbp = fetch_play_by_play(game_pk, timeout=timeout)
            wp = fetch_win_probability(game_pk, timeout=timeout)
        except mlb.MLBError as exc:
            # Left ABSENT, not marked -- a rerun with resume=True retries it.
            report["errors"].append({"game_pk": game_pk, "error": str(exc)})
            continue

        rows = build_rows(iso, game_pk, pbp, wp,
                          clock().isoformat().replace("+00:00", "Z"),
                          game_meta=game)
        with target.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")

        report["games_written"] += 1
        report["play_rows"] += sum(1 for r in rows if r["type"] == ROW_TYPE_PLAY)
        game_row = rows[-1]
        if not game_row.get("wp_available"):
            report["games_without_wp"] += 1

    return report


def ingest_games(game_date, game_pks, path=None, resume=True, timeout=20,
                 fetch_results=mlb.fetch_results, **kwargs) -> dict:
    """`ingest_date` narrowed to an explicit set of game_pks on that date.

    The post-mortem only ever needs the games it actually has decisions for;
    fetching a whole slate to explain three bets is wasted requests against a
    free API that is still someone else's to be polite to.
    """
    wanted = {str(pk) for pk in game_pks}

    def _filtered(iso, timeout=timeout):
        result = fetch_results(iso, timeout=timeout)
        return {**result, "final": [g for g in result["final"]
                                    if str(g.get("game_pk")) in wanted]}

    return ingest_date(game_date, path=path, resume=resume, timeout=timeout,
                       fetch_results=_filtered, **kwargs)


def ingest_range(start, end, path=None, resume=True, timeout=20,
                 on_date=None, **kwargs) -> dict:
    """Drive `ingest_date` across a date range. Resumable; one bad date does
    not abort the rest -- same shape as `src.pipeline.boxscores.ingest_range`."""
    totals = {"dates": 0, "games_written": 0, "games_skipped": 0,
              "play_rows": 0, "games_without_wp": 0, "errors": []}
    for iso in mlb.iter_dates(start, end):
        report = ingest_date(iso, path=path, resume=resume, timeout=timeout,
                             **kwargs)
        totals["dates"] += 1
        for key in ("games_written", "games_skipped", "play_rows",
                    "games_without_wp"):
            totals[key] += report[key]
        totals["errors"].extend({"date": iso, **e} for e in report["errors"])
        if on_date:
            on_date(report)
    return totals


def load_game(rows_or_path, game_pk) -> dict | None:
    """`{"game": <game row>, "plays": [...]}` for one game_pk, or None.

    Returns None -- never a partial or invented flow -- when the store has no
    `type="game"` row for that game_pk, which is the only signal that the
    game was fully written (see `build_rows`: the game row is written last).
    """
    if game_pk is None:
        return None
    rows = rows_or_path if isinstance(rows_or_path, list) else read(rows_or_path)
    try:
        target = int(game_pk)
    except (TypeError, ValueError):
        return None
    game_row = None
    plays = []
    for row in rows:
        if row.get("game_pk") != target:
            continue
        if row.get("type") == ROW_TYPE_GAME:
            game_row = row
        elif row.get("type") == ROW_TYPE_PLAY:
            plays.append(row)
    if game_row is None:
        return None
    plays.sort(key=lambda p: (p.get("at_bat_index") if p.get("at_bat_index")
                              is not None else -1))
    return {"game": game_row, "plays": plays}


def load_store(pattern_dir=None) -> list:
    """Every gameflow row across every season store, in file order per file."""
    directory = Path(pattern_dir) if pattern_dir else data_path("processed")
    rows = []
    for path in sorted(directory.glob("gameflow_*.jsonl")):
        rows.extend(_read_rows(path))
    return rows
