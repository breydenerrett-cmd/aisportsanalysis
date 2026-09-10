"""GET /card/{date} and GET /card: THE CARD -- today's three to five bets.

Same division of labour as api/opportunities.py: this file fetches inputs
and hands them to pure builders. `src.report.card.card_for_date` does the
assembly, `src.analysis.daily_card` owns the rule and the wording, and
nothing here decides anything a reader sees.

DATE HANDLING: `/card/{date}` validates and builds for that date; `/card`
uses UTC-today, the same rule every other date-defaulting route applies.

This endpoint NEVER returns an empty card silently. When there is nothing
to publish it carries a `reason` naming a fact about the world -- no games
scheduled, all of them started, no prices posted yet -- because those are
the only empty states this surface has. It has no evidence bar to clear and
so cannot report failing to clear one.
"""

from __future__ import annotations

from datetime import date as date_cls, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request

from api.games import _build_entries, _record_page_view
from src.analysis import opportunities as opportunities_mod
from src.report import card as card_mod

router = APIRouter()


def _build_payload(date: str, request: Optional[Request], route: str) -> dict:
    entries, _notes, meta = _build_entries(date)
    now = datetime.now(timezone.utc)
    # The moneyline board comes from the SAME builder the price board uses,
    # so the card and the board can never quote different best prices for
    # the same bet on the same page.
    opportunities = opportunities_mod.build_opportunities(
        entries, date=date, now=now)
    payload = card_mod.card_for_date(
        entries, opportunities.get("rows") or [], date=date, now=now)
    payload["freshness"] = meta
    _record_page_view(request, route, date)
    return payload


# DECLARED BEFORE /card/{date}, because FastAPI matches routes in
# declaration order and "record" would otherwise be captured as a date and
# rejected by _validate_date as a 400.
@router.get("/card/record")
def get_card_record(request: Request = None) -> dict:
    """The card's public record: every settled day, pooled.

    Pooling is correct here and is not the pooling mistake this repo warns
    about elsewhere. The card is ONE system with ONE rule, so its picks are
    one population; the warning is about pooling different systems, where a
    control and a forward test average into a number describing neither.

    The chain is verified on every request and reported. A published record
    whose hash chain is broken is not a record, and the page showing it has
    to be able to say so rather than keep printing the totals.
    """
    from src.appstate import card_ledger

    payload = card_ledger.record()
    chain = card_ledger.verify()
    payload["chain_ok"] = bool(getattr(chain, "ok", True))
    payload["chain_detail"] = None if payload["chain_ok"] else str(chain)
    _record_page_view(request, "card_record", None)
    return payload


@router.get("/card/{date}")
def get_card_for_date(date: str, request: Request = None) -> dict:
    return _build_payload(date, request, "card")


@router.get("/card")
def get_card_today(request: Request = None) -> dict:
    return _build_payload(date_cls.today().isoformat(), request, "card")
