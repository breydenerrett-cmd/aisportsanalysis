"""Append today's postseason forecasts to the public forecast ledger.

    python3 scripts/postseason_snapshot.py [--date YYYY-MM-DD] [--ledger PATH]

One row per day per live or upcoming series (both teams known, not yet
complete) in `evidence/postseason_forecasts.jsonl`, an append-only
`HashChainLedger`. A series that already has a row for the day is skipped, so
running this twice a day, or after a retry, writes nothing new.

WHY THIS FILE EXISTS. The postseason page (`src/report/postseason_page.py`)
has no series-level track record. The only honest way to earn one is to write
each forecast down BEFORE the games it covers and grade it afterwards, in the
open. This script is the writing-down; once a series ends the page shows what
it said before game 1 next to what happened.

An unavailable page (no final standings, results that stopped advancing, a
game that fits no series) writes nothing and says why: a forecast row is a
claim, and a claim should not be made from a bracket that could not be set.

Exit status: 0 on success, including "nothing to write"; non-zero only when
the builder or the ledger itself failed, which daily_loop.sh turns into an
ESCALATE line.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ledger.chain import HashChainLedger  # noqa: E402
from src.paths import evidence_path  # noqa: E402
from src.providers import mlb  # noqa: E402
from src.report import postseason_page  # noqa: E402

LEDGER_PATH = evidence_path("postseason_forecasts.jsonl")
# At most this many new pitcher game-log requests per run (the route's cap).
MAX_FRESH_PITCHER_FETCHES = 24


def snapshot(payload: dict, day: str, ledger_path=LEDGER_PATH) -> dict:
    """Append one row per series in `payload` that has none for `day` yet.
    Returns {"appended", "already_written", "candidates", "available"}."""
    rows = postseason_page.snapshot_rows(payload, day)
    report = {"available": bool(payload.get("available")), "candidates": len(rows),
              "appended": 0, "already_written": 0}
    if not rows:
        return report
    ledger = HashChainLedger(ledger_path)
    existing = {(r.get("series_id"), r.get("date")) for r in ledger.iter_rows()
                if r.get("kind") == "postseason_series_forecast"}
    for row in rows:
        if (row["series_id"], row["date"]) in existing:
            report["already_written"] += 1
            continue
        ledger.append(row)
        report["appended"] += 1
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", help="baseball (US Eastern) date to write rows for "
                                       "(default: today)")
    parser.add_argument("--ledger", default=str(LEDGER_PATH))
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    day = args.date or postseason_page.baseball_date(now)
    # Announced starters live in the schedule feed; without them the rows
    # would label every starter a projection even on the day one is named.
    # The standings store never holds a final table on its own (see
    # with_final_standings), so the seeding is completed from the feed here.
    from src.pipeline import standings as standings_store
    # A starter counts in a recorded estimate only when his numbers are
    # current, so the same lookup the route uses (one game-log request per
    # identified pitcher whose stored numbers are not current, capped, no memo
    # needed for a once-a-day run) is passed to the builder. A failed lookup
    # leaves that pitcher out of the estimate; each row records what it used.
    season = postseason_page.baseball_date(now)[:4]
    fetcher = postseason_page.capped_pitcher_fetcher(
        lambda pid: mlb.fetch_pitcher_game_log(pid, season),
        cap=MAX_FRESH_PITCHER_FETCHES)
    payload = postseason_page.build(
        now,
        standings=postseason_page.with_final_standings(
            standings_store.read(), now, mlb.fetch_standings, mlb.parse_standings),
        probables=postseason_page.upcoming_games(now, mlb.fetch_games),
        fresh_pitcher_logs=fetcher)
    fetcher.report()
    report = snapshot(payload, day, args.ledger)
    if not payload.get("available"):
        print(f"postseason snapshot: nothing written -- "
              f"{payload.get('detail') or payload.get('reason')}")
    else:
        print(f"postseason snapshot {day}: appended {report['appended']}, "
              f"already written {report['already_written']}, "
              f"series considered {report['candidates']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
