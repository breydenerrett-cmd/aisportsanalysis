"""GET /props/{date} and GET /props: tonight's player props, priced.

Same division of labour as api/card.py: this file validates input and hands
off. `src.report.props.board_for_date` reads the stores,
`src.analysis.propboard` owns the rule and the ordering, and nothing here
decides anything a reader sees.

WHY THIS ENDPOINT EXISTS
------------------------
The card can only emit `moneyline` and `run_line`, so the product showed the
same shape of bet every night -- the market's biggest favourites -- while
17,149 prop quotes sat unread in the store. The owner, 2026-09-11:

    "where are all the player props including player hits player total
     bases player stolen base player home run"

THE ORDER, AND IT IS NOT NEGOTIABLE HERE
----------------------------------------
Contracts come back ranked by OUR PROBABILITY -- how likely the thing is --
and never by the gap against the price. That ordering is set in
`src.analysis.propboard` and the reason is measured: selecting on our own
disagreement with the price returned -13.4% against a -9.1% control
(`scripts/probe_prop_value.py`). This endpoint must not re-sort.

It is a BOARD, not a card. It carries no pick, no label, no recommendation,
and the client is expected to present it as what it is.
"""

from __future__ import annotations

from datetime import date as date_cls, datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from src.pipeline import prop_listing
from src.report import props as props_mod

router = APIRouter()


def _validate(date: str) -> str:
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"date must be ISO format YYYY-MM-DD, got {date!r}") from exc
    return date


def _today() -> str:
    """Tonight's slate date -- EASTERN, not UTC.

    A baseball slate is an Eastern-date concept and the prop store keys its
    rows by exactly that (`game_date`). UTC-today is a different day for the
    four hours between 00:00 UTC and 04:00 UTC, which is 8pm to midnight
    Eastern -- the window in which people are actually looking at tonight's
    board while the games are being played.

    Measured 2026-09-12T01:00Z: `/props` resolved to 2026-09-12 and returned
    an empty board with "no prop prices posted for this slate yet", while
    `/props/2026-09-11` returned forty contracts. The page went blank every
    night at 8pm Eastern and said the slate was unpriced.
    """
    return prop_listing._slate_date(datetime.now(timezone.utc))


def _board(date: str, limit: Optional[int]) -> dict:
    """Build, turning an unreadable store into a 502 rather than a blank page.

    An empty board with a `reason` is a real answer -- prices may not be
    posted yet. A board that could not be built at all is not, and a client
    must be able to tell those apart.
    """
    try:
        return props_mod.board_for_date(date, limit=limit)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 -- surfaced, never swallowed
        raise HTTPException(
            status_code=502,
            detail=f"prop board unavailable: {exc}") from exc


@router.get("/props")
def get_props(request: Request,
              limit: int = Query(props_mod.DEFAULT_LIMIT, ge=1,
                                 le=props_mod.MAX_LIMIT)) -> dict:
    return _board(_today(), limit)


@router.get("/props/{date}")
def get_props_for_date(date: str, request: Request,
                       limit: int = Query(props_mod.DEFAULT_LIMIT, ge=1,
                                          le=props_mod.MAX_LIMIT)) -> dict:
    return _board(_validate(date), limit)
