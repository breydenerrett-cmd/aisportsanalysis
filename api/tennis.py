"""GET /tennis/board: Tennis research board per date.

Same division of labour as api/opportunities.py: this file validates the request
and hands it to the pure builder, `src.report.tennis_board.board_for_date`.
Nothing here decides what a reader sees.

DATE HANDLING: the `date` query parameter is optional; defaults to UTC-today,
the same rule every other date-defaulting route applies.
"""

from __future__ import annotations

from datetime import date as date_cls, datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException

from src.appstate import freshness
from src.report import tennis_board

router = APIRouter()

# Module-level readers, patchable for testing
_board_for_date = tennis_board.board_for_date

# Measured on staging 2026-09-21: 3.9s. `tennis_board.board_for_date` reads
# `snapshots.read_multibook(sport=None)` -- EVERY row in the store,
# regardless of sport, because `captured_any`/`last_captured_utc` (the
# "have we ever captured a tennis price at all" fields) need the full
# history, not one date's window -- windowing the read here the way
# api/odds.py's boards_by_matchup(date=...) fix does would silently change
# THOSE two fields for any date outside the window, which is exactly the
# kind of quiet wrongness this project's incidents keep coming back to.
# A plain per-date TTL cache in front of the whole built payload sidesteps
# that risk entirely: the underlying read/derivation is untouched, so
# every field -- including `captured_any` -- is exactly what it always
# was, just not recomputed on every request for the same date within the
# TTL. Same 120s TTL as every other date-keyed cache in this project.
_tennis_cache = freshness.SingleFlightTTLCache(ttl_s=120.0)


def _validate_date(date_str: str) -> str:
    """Parse and validate a YYYY-MM-DD date string."""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return date_str
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"date must be YYYY-MM-DD format (got {date_str!r})")


@router.get("/tennis/board")
def get_tennis_board(date: Optional[str] = None) -> dict:
    """Tennis research board for a date.

    Args:
        date: Optional YYYY-MM-DD date. Defaults to UTC-today.

    Returns:
        {
            "date": YYYY-MM-DD,
            "tournaments": [
                {
                    "key": tournament key,
                    "title": tournament name,
                    "matches": [match records]
                }
            ],
            "notice": "Research only...",
            "generated_utc": ISO timestamp,
            "captured_any": bool -- any tennis price captured at all, for
                            any date (2026-09-20: lets the page tell "none
                            captured yet" from "none for this date"),
            "last_captured_utc": newest tennis capture time, or None
        }
    """
    if date is None:
        date = date_cls.today().isoformat()
    else:
        date = _validate_date(date)

    value, _meta = _tennis_cache.get(("tennis_board", date), lambda: _board_for_date(date))
    return value
