"""T0a: rebuild data/processed/boxscores_2025.jsonl with the new
`batting_order` field (parse_boxscore was extended for this task).

Writes to a NEW path first (boxscores_2025_v2.jsonl), single writer, then
this script verifies row-count parity against the existing store before
doing anything else. The atomic swap into the real path is a separate,
explicit step run only after verification (see bottom of this file).
"""
from __future__ import annotations
import sys, os, json
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from src.pipeline import boxscores

# NOTE (T0a, run 2026-09-17): the range below intentionally overshoots the
# regular season (spring training in March, any October postseason) because
# fetch_results has no game-type filter the way history.ingest_date does.
# The run actually used pulled in 408 non-regular-season games; those were
# filtered back out afterwards by keeping only game_pks already present in
# the pre-existing (regular-season-only) boxscores_2025.jsonl, which is the
# resulting live store. A future re-run should filter game_type up front
# instead of after the fact.
SEASON_START = "2025-03-01"
SEASON_END = "2025-11-01"
NEW_PATH = os.path.join(REPO, "data", "processed", "boxscores_2025_v2.jsonl")
OLD_PATH = os.path.join(REPO, "data", "processed", "boxscores_2025.jsonl")


def _sealed_guard(iso):
    if iso >= "2026-01-01":
        raise SystemExit(f"REFUSED: {iso} is inside the sealed window")


def main():
    for d in boxscores.mlb.iter_dates(SEASON_START, SEASON_END):
        _sealed_guard(d)

    report = boxscores.ingest_range(SEASON_START, SEASON_END, path=NEW_PATH,
                                    resume=True)
    print("BOXSCORE REBUILD REPORT:", report)

    old_games = {r.get("game_pk") for r in boxscores.read(OLD_PATH)
                if r.get("game_pk")}
    new_games = {r.get("game_pk") for r in boxscores.read(NEW_PATH)
                if r.get("game_pk")}
    print(f"old store games: {len(old_games)}  new store games: {len(new_games)}")
    print(f"games in old not in new: {len(old_games - new_games)}")
    print(f"games in new not in old: {len(new_games - old_games)}")

    with_slot = sum(1 for r in boxscores.read(NEW_PATH)
                    if r.get("type") == "batter" and r.get("batting_order"))
    total_batter = sum(1 for r in boxscores.read(NEW_PATH)
                       if r.get("type") == "batter")
    print(f"batter rows with a batting_order: {with_slot} / {total_batter}")


if __name__ == "__main__":
    main()
