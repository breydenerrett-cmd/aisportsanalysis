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

from fastapi import APIRouter, HTTPException, Request

from api.games import _build_entries, _record_page_view
from src.analysis import best_bets_card, daily_card, grade
from src.analysis import opportunities as opportunities_mod
from src.analysis import strength
from src.report import card as card_mod

router = APIRouter()

# GET /card/history's page size. Capped, not unlimited -- the record page
# is the public sales pitch, not a data export; a reader who wants the
# whole ledger can read evidence/cards_v1.jsonl directly, which is the
# actual receipt.
DEFAULT_HISTORY_LIMIT = 60
MAX_HISTORY_LIMIT = 200


def _validate_sport(sport: str) -> None:
    """Validate sport parameter against src.sports.keys()."""
    from src import sports
    valid_sports = sports.keys()
    if sport not in valid_sports:
        raise HTTPException(
            status_code=400,
            detail=f"sport must be one of {valid_sports}, got {sport!r}")


# T5 (docs/CARD_V2_BUILD_PLAN.md). The only two rule ids any card route
# accepts -- there is no third value, and neither string is guessed from
# elsewhere: "v1" is `daily_card.CARD_RULE`'s family, "v2" is
# `best_bets_card.V2.rule_id`'s. `?rule=` defaults to `card_mod.
# ACTIVE_CARD_RULE`, so every existing caller (no `rule` param at all) keeps
# getting exactly what it always has -- V1 -- until `ACTIVE_CARD_RULE`
# itself flips at T13's registration commit.
_VALID_RULES = ("v1", "v2")


def _resolve_rule(rule: Optional[str]) -> str:
    resolved = rule or card_mod.ACTIVE_CARD_RULE
    if resolved not in _VALID_RULES:
        raise HTTPException(
            status_code=400,
            detail=f"rule must be one of {_VALID_RULES}, got {resolved!r}")
    return resolved


def _resolve_nfl_rule(rule: Optional[str]) -> str:
    """`?rule=` for sport=nfl: one of src/report/nfl_card.RULES, default the
    live rule. ADDED 2026-09-20: the NFL ledger holds NFL_CARD_V1 (retired)
    and NFL_CARD_V2 (live) and the record shows one at a time, never the two
    pooled -- so the retired record needs its own address to stay public.
    MLB's "v1"/"v2" are not NFL rule ids and are refused here, not guessed."""
    from src.report import nfl_card as nfl_report
    resolved = (rule or nfl_report.LIVE_RULE).upper()
    if resolved not in nfl_report.RULES:
        raise HTTPException(
            status_code=400,
            detail=f"rule must be one of {nfl_report.RULES} for sport=nfl, got {rule!r}")
    return resolved


def _build_payload(date: str, request: Optional[Request], route: str,
                   sport: str = "mlb", rule: Optional[str] = None) -> dict:
    """The card for one date.

    THE FROZEN CHECK COMES FIRST, AND IT IS WORTH 15 SECONDS A REQUEST.
    ------------------------------------------------------------------
    This function used to run `_build_entries` (a live schedule fetch plus a
    full slate build) and then `build_opportunities` over the result, before
    handing both to `card_mod.card_for_date`.

    But `card_for_date` serves the FROZEN row whenever one exists, and in that
    branch it reads neither argument. `frozen_card` needs one ledger row and
    nothing else. So on every request for a date whose card is published --
    which is every request for today's card, all day, from every visitor --
    the endpoint built a slate and a price board and threw both away.

    Measured on the 512 MB staging container from its own log:

        GET /card/{date}  status=200  latency_ms=15260.3

    Fifteen seconds of a one-CPU machine, per request, for a result already
    sitting on disk. It starved /health past Fly's timeout, Fly pulled the
    machine out of rotation, and visitors got 503s from an app that was alive
    -- see docs/INCIDENT_2026-09-10_SPINNING_SLATE.md.

    Checking first costs one ledger read. The live branch below is unchanged
    and still pays full price, which is correct: a date with no published
    card genuinely has to be built.
    """
    _validate_sport(sport)

    # Tennis: return research-only notice
    if sport == "tennis":
        _record_page_view(request, route, date)
        return {
            "sport": "tennis",
            "reason": "Research only. No tennis picks until results grading is connected."
        }

    # NFL: use nfl_card
    if sport == "nfl":
        from src.report import nfl_card
        now = datetime.now(timezone.utc)
        payload = nfl_card.card_for_date(date, now=now)
        _record_page_view(request, route, date)
        return payload

    resolved_rule = _resolve_rule(rule)

    # MLB, rule v2: the PREVIEW path (T5). Kept entirely separate from the
    # branch below so `rule=None`/`rule="v1"` -- every existing caller --
    # reaches the untouched v1 code and gets the untouched v1 byte shape.
    if resolved_rule == "v2":
        return _build_payload_v2(date, request, route)

    # MLB: existing code path (default)
    now = datetime.now(timezone.utc)

    frozen = card_mod.frozen_card(date)
    if frozen is not None:
        frozen["date"] = date
        frozen["generated_at"] = now.isoformat()
        frozen["model_basis"] = strength.MODEL_BASIS
        # The grade legend rides every card, frozen or live. This branch
        # returns before src/report/card.py's card_for_date (which is where
        # the live path attaches it), so it is attached here too -- a
        # frozen card's picks carry the grade they were frozen with, and the
        # page needs the legend to read it.
        frozen["knowledge_legend"] = list(grade.legend())
        # An honest freshness block for a row that is frozen ON PURPOSE. It
        # describes when this payload was BUILT, which for a frozen card is
        # when it was published -- not how old the prices on it are. The page
        # warns about price age separately (web/js/card.js's
        # `card-stale-prices`), and conflating the two would either cry stale
        # about a card doing exactly what it promised, or hide a genuinely
        # old quote behind a fresh-looking build time.
        published = frozen.get("frozen_at")
        age_s = None
        if published:
            try:
                age_s = (now - datetime.fromisoformat(published)).total_seconds()
            except (TypeError, ValueError):
                age_s = None
        frozen["freshness"] = {
            "served_at": now.isoformat(),
            "built_at": published,
            "age_s": age_s,
            "stale": False,
            "stale_reason": None,
        }
        _record_page_view(request, route, date)
        return frozen

    entries, _notes, meta = _build_entries(date)
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


def _build_payload_v2(date: str, request: Optional[Request], route: str) -> dict:
    """The V2 preview payload for one date (T5, `?rule=v2`).

    Serves the FROZEN row when V2 has published one for this date (same
    "check the ledger first" shape `_build_payload`'s v1 branch uses, for
    the identical reason -- see that function's docstring), and builds live
    otherwise. Nothing publishes V2 before T0's registration commit, so in
    practice every request through this path today builds live; the frozen
    branch exists so this route does not need to change again the day T6
    starts writing rows.

    `CardV2Error` (the frozen-parameter file missing or unreadable) is a 503,
    not a 500 and not a quietly empty card: V2 cannot be built at all
    without its own fitted numbers, and that is an operational fact about
    this deployment, not a fact about tonight's board.
    """
    from src.report import card_v2

    now = datetime.now(timezone.utc)

    frozen = card_v2.frozen_card_v2(date)
    if frozen is not None:
        frozen["generated_at"] = now.isoformat()
        _record_page_view(request, route, date)
        return frozen

    entries, _notes, meta = _build_entries(date)
    opportunities = opportunities_mod.build_opportunities(
        entries, date=date, now=now)
    try:
        payload = card_v2.card_v2_for_date(
            entries, opportunities.get("rows") or [], date=date, now=now)
    except card_v2.CardV2Error as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    payload["freshness"] = meta
    _record_page_view(request, route, date)
    return payload


# DECLARED BEFORE /card/{date}, because FastAPI matches routes in
# declaration order and "record" would otherwise be captured as a date and
# rejected by _validate_date as a 400.
@router.get("/card/record")
def get_card_record(request: Request = None, sport: str = "mlb",
                    rule: Optional[str] = None) -> dict:
    """The card's public record: every settled day, pooled.

    Pooling is correct here and is not the pooling mistake this repo warns
    about elsewhere. The card is ONE system with ONE rule, so its picks are
    one population; the warning is about pooling different systems, where a
    control and a forward test average into a number describing neither.
    That is still true within V2's own record (`rule=v2`, `sport=mlb` only)
    -- what changes is that V2 has TWO price classes and a fills population,
    reported apart from each other and never summed into one figure a
    reader could mistake for the rule's own result (registration R5).

    For sport=nfl, `rule` is an NFL rule id instead (src/report/nfl_card.
    RULES, default the live one) -- see `_resolve_nfl_rule`.

    The chain is verified on every request and reported. A published record
    whose hash chain is broken is not a record, and the page showing it has
    to be able to say so rather than keep printing the totals.
    """
    from src.appstate import card_ledger

    _validate_sport(sport)
    # NFL's ledger holds two rules since 2026-09-20; the page shows one at a
    # time (default the live one, src/report/nfl_card.LIVE_RULE; `?rule=`
    # names the retired one), never the two pooled.
    nfl_rule = _resolve_nfl_rule(rule) if sport == "nfl" else None
    resolved_rule = None if sport == "nfl" else _resolve_rule(rule)

    if sport == "mlb" and resolved_rule == "v2":
        payload = card_ledger.record_v2()
        payload["rule"] = "v2"
        payload["basis"] = best_bets_card.BASIS
        payload["disclaimer"] = best_bets_card.DISCLAIMER
        _record_page_view(request, "card_record", None)
        return payload

    if sport == "nfl":
        from src.report import nfl_card as nfl_report
    payload = card_ledger.record(sport=sport, rule=nfl_rule)
    # THE CHAIN OF THE LEDGER THIS RECORD WAS READ FROM (review,
    # 2026-09-20). A bare `verify()` walks MLB's file, so the NFL record
    # page said "338 entries so far ... That chain verifies right now" off
    # MLB's ledger (the NFL file had 9 rows), and a tampered NFL file still
    # read as verified. MLB keeps `verify()` exactly as before.
    chain = card_ledger.verify(sport=None if sport == "mlb" else sport)
    payload["chain_ok"] = bool(getattr(chain, "ok", True))
    payload["chain_detail"] = None if payload["chain_ok"] else str(chain)
    payload["rows_checked"] = getattr(chain, "rows_checked", None)
    # THE SAME WORDS THE CARD ITSELF SHOWS, sourced from the one constant
    # both surfaces read -- never a second hand-written sentence on the
    # record page that could quietly drift from daily_card.CARD_DISCLAIMER
    # and end up contradicting it.
    if sport == "mlb":
        payload["disclaimer"] = daily_card.CARD_DISCLAIMER
        payload["basis"] = daily_card.CARD_BASIS
    elif sport == "nfl":
        payload["sport"] = "nfl"
        payload["rule"] = nfl_rule
        payload["live_rule"] = nfl_report.LIVE_RULE
        payload["notice"] = nfl_report.NOTICE
    _record_page_view(request, "card_record", None)
    return payload


# ALSO DECLARED BEFORE /card/{date}, for the identical reason /card/record
# is above: "history" would otherwise be matched as a date and 400 out of
# _validate_date. See that route's comment and tests/test_api_card.py.
@router.get("/card/history")
def get_card_history(request: Request = None, limit: int = DEFAULT_HISTORY_LIMIT,
                     sport: str = "mlb", rule: Optional[str] = None) -> dict:
    """Every settled day, newest first -- the day-by-day detail behind
    /card/record's pooled totals: each day's picks, results, prices, books
    and profit, plus that day's published row_hash.

    `limit` is validated here rather than left to FastAPI's own coercion --
    same reasoning as api/daily.py's get_daily_index: a direct function
    call (this codebase's own test style) never runs FastAPI's
    request-parsing layer at all, so an out-of-range value has to be
    caught by hand to be caught the same way in both call paths.
    """
    from src.appstate import card_ledger

    _validate_sport(sport)
    nfl_rule = _resolve_nfl_rule(rule) if sport == "nfl" else None
    resolved_rule = None if sport == "nfl" else _resolve_rule(rule)

    if limit < 1 or limit > MAX_HISTORY_LIMIT:
        raise HTTPException(
            status_code=400,
            detail=f"limit must be between 1 and {MAX_HISTORY_LIMIT} (got {limit!r})")

    if sport == "mlb" and resolved_rule == "v2":
        payload = card_ledger.history_v2(limit=limit)
        _record_page_view(request, "card_history", None)
        return payload

    if sport == "nfl":
        from src.report import nfl_card as nfl_report
        # One rule's days only, published AND settled: card_ledger.history
        # leaves another rule's dates out of `pending_days` too, so a V1 date
        # never shows on the V2 calendar as PENDING (review, 2026-09-20).
        payload = card_ledger.history(limit=limit, sport=sport, rule=nfl_rule)
        payload["sport"] = "nfl"
        payload["rule"] = nfl_rule
        payload["live_rule"] = nfl_report.LIVE_RULE
        payload["notice"] = nfl_report.NOTICE
    else:
        payload = card_ledger.history(limit=limit, sport=sport)
    _record_page_view(request, "card_history", None)
    return payload


@router.get("/card/{date}")
def get_card_for_date(date: str, request: Request = None,
                      sport: str = "mlb", rule: Optional[str] = None) -> dict:
    return _build_payload(date, request, "card", sport=sport, rule=rule)


@router.get("/card")
def get_card_today(request: Request = None, sport: str = "mlb",
                   rule: Optional[str] = None) -> dict:
    return _build_payload(date_cls.today().isoformat(), request, "card",
                         sport=sport, rule=rule)
