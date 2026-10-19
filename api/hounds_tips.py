"""A dog's rulebook and the fan-tip box.

    GET  /hounds/{id}/rulebook      the rule, the plain trigger, and a tunable dog's dials with their current
                                    values and when the referee last changed them (src/hounds/dials.py)
    GET  /hounds/{id}/tips          the newest 20 fan tips and how many there are; a tip the coach report card has
                                    graded carries ``grade`` {label, units_diff, n_paired, hindsight_units_diff}
    POST /hounds/{id}/tips          send a tip: {"values": {knob: value}, "nickname": "optional"}
    GET  /hounds/tips/export?since= every tip, oldest first, for the grading job (no addresses, no hashes)

A TIP NEVER CHANGES A DOG. It is a row in a table (src/hounds/fan_tips.py); only the referee changes a
dog. Public, no sign-in, paper only: the tip box is rate limited in the database (3 a day per caller, 60 a
day for the site), because it is the only public WRITE on the kennel pages.

MOUNT ORDER. ``/hounds/tips/export`` is a literal path next to ``/hounds/{id}``-shaped routes. It cannot
collide with ``/hounds/{id}/tips`` (a different second segment) but the router is mounted BEFORE
api.hounds anyway, and tests/test_hounds_tips_api.py pins the order, so a later ``/hounds/{id}/{x}``
cannot swallow it.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request, Response

from src.appstate import ratelimit
from src.hounds import dials, fan_tips, stats
from src.hounds.contract import envelope

router = APIRouter()

_NO_STORE = "no-store"
_SHORT = "public, max-age=30"


def _tip_error(exc: fan_tips.TipError) -> HTTPException:
    detail = {"error": exc.code, "message": str(exc), "fields": exc.errors}
    headers = None
    if exc.retry_after:
        detail["retry_after"] = exc.retry_after
        headers = {"Retry-After": str(exc.retry_after)}
    return HTTPException(status_code=exc.status, detail=detail, headers=headers)


def _rule_of(hound_id: str) -> tuple:
    """``(rule_text, tagline)`` from the cached book when there is one; never builds."""
    book = stats.peek_book()
    data = book.hounds.get(hound_id) if book is not None else None
    if data is None:
        return "", ""
    return data.summary.rule_text or "", data.summary.tagline or ""


def _grades_by_tip() -> dict:
    """The coach report card's grade for each fan tip it has recorded ({} when it has none or cannot be read:
    the tip list is the fans' page and must not fail because the report card did)."""
    try:
        from src.hounds import coach_report
        return coach_report.fan_grades_now()
    except Exception:  # noqa: BLE001
        return {}


@router.get("/hounds/tips/export")
def tips_export(response: Response, since: Optional[str] = Query(None, max_length=64)):
    try:
        cutoff = fan_tips.parse_since(since)
    except fan_tips.TipError as exc:
        raise _tip_error(exc)
    response.headers["Cache-Control"] = _NO_STORE
    tips = fan_tips.export(cutoff)
    return envelope({"since": cutoff, "count": len(tips), "tips": tips})


@router.get("/hounds/{hound_id}/rulebook")
def rulebook(hound_id: str, response: Response):
    rule_text, tagline = _rule_of(hound_id)
    payload = dials.rulebook(hound_id, rule_text=rule_text, tagline=tagline)
    response.headers["Cache-Control"] = _SHORT
    return envelope(payload)


@router.get("/hounds/{hound_id}/tips")
def tips_for(hound_id: str, response: Response):
    response.headers["Cache-Control"] = _NO_STORE
    tips = fan_tips.latest(hound_id)
    grades = _grades_by_tip()
    for tip in tips:
        if tip["id"] in grades:
            tip["grade"] = grades[tip["id"]]     # only a graded tip carries the key; the rest read as before
    return envelope({"hound_id": hound_id, "count": fan_tips.count_for(hound_id),
                     "tips": tips, "note": fan_tips.COPY_NEVER_CHANGES})


@router.post("/hounds/{hound_id}/tips")
def send_tip(hound_id: str, request: Request, response: Response, payload: dict = Body(...)):
    response.headers["Cache-Control"] = _NO_STORE
    try:
        tip = fan_tips.submit(hound_id, payload.get("values"), payload.get("nickname"),
                              ratelimit.client_ip(request))
    except fan_tips.TipError as exc:
        raise _tip_error(exc)
    return envelope({"tip": tip, "note": fan_tips.COPY_NEVER_CHANGES})
