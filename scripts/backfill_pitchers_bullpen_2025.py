"""T0a: backfill 2025 starter logs and bullpen log into SEPARATE files.

Free MLB Stats API only. Writes:
  data/historical/pitcher_logs_2025.jsonl
  data/historical/bullpen_log_2025.jsonl

Deliberately NOT the live stores (pitcher_logs.jsonl, bullpen_log.jsonl),
because those are read with no season filter by pitchers.league_fip_constant
/ used to build V1's live 2026 features -- mixing 2025 rows in would change
V1's live numbers. Refuses any date outside 2025-01-01..2025-12-31.
"""
from __future__ import annotations
import sys, os
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from src.pipeline import history, pitchers as pitcher_store, bullpen

SEASON = "2025"
START = "2025-01-01"
END = "2025-12-31"

PITCHER_LOG_2025 = os.path.join(REPO, "data", "historical", "pitcher_logs_2025.jsonl")
BULLPEN_LOG_2025 = os.path.join(REPO, "data", "historical", "bullpen_log_2025.jsonl")


def _sealed_guard(d):
    if d >= "2026-01-01":
        raise SystemExit(f"REFUSED: {d} is inside the sealed window")


def main():
    store = history.read_results()
    season_rows = [r for r in store.values() if str(r.get("date") or "")[:4] == SEASON]
    print(f"2025 results rows in history store: {len(season_rows)}")
    for r in season_rows:
        _sealed_guard(str(r.get("date")))

    ids = pitcher_store.probable_pitcher_ids({k: v for k, v in store.items()
                                              if str(v.get("date") or "")[:4] == SEASON})
    print(f"2025 probable pitcher ids: {len(ids)}")

    def on_pitcher(info):
        pass

    report = pitcher_store.build_log_store(
        ids, SEASON, path=PITCHER_LOG_2025, resume=True, on_pitcher=on_pitcher)
    print("PITCHER LOG REPORT:", report)

    bp_report = bullpen.build_log(START, END, path=BULLPEN_LOG_2025, resume=True)
    print("BULLPEN LOG REPORT:", bp_report)


if __name__ == "__main__":
    main()
