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

from src.report import tennis_board

router = APIRouter()

# Module-level readers, patchable for testing
_board_for_date = tennis_board.board_for_date


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

    return _board_for_date(date)
