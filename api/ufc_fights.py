"""GET /ufc/fight-night and GET /ufc/fight-night/{event_id}: the next UFC card, bout by bout.

Each bout comes back with its two fighters (names, records), the card slot, the weight class
and rounds, the current price, the data layer's fact sheet (`src.datasvc.ufc.matchup`) and the
written read built from that sheet (`src.analysis.ufc_read`). This file only selects the event,
asks the data layer for each sheet and hands each to the read; it derives no figure and writes no
sentence about a fighter.

WHY THIS EXISTS
---------------
The UFC page used to take the betting favourite in every bout. That is paused (config/ufc_public_card.json,
docs/decisions/UFC_FAVOURITES_PAUSED.md) and the page shows fight analysis instead. See
docs/UFC_FIGHT_NIGHT.md for the rules behind the read and the shape of this response.

THREE THINGS THAT MUST STAY TRUE
--------------------------------
1. The same sign-in as the product's other signed-in content routes, ALWAYS. The router depends on
   `require_paid_access` itself and is NOT in app.py's `_authed_paid` group, so APP_PUBLIC_DEMO (which
   empties that group) can never open it: a card's worth of fighter statistics is the bulk data
   surface the red-team finding 2 gate exists to keep behind a login, exactly as /data/v1 is.

2. The files are never read per request. Production has run out of memory from whole-store reads per
   request before. This route reuses the data API's one store holder (`api.datasvc.holder`: one store
   per process, swapped only when a dataset file changes on disk) and builds each event's payload ONCE
   per store version, under the store's lock (`store.view`). A request after that costs a stat() of
   the six dataset files and a copy of the top-level dict. Nothing that varies with the clock is baked
   into the cached payload: the read is built without a "now", and `generated_utc` is stamped per request.

3. Fail soft. A bout whose sheet cannot be built (an unknown fighter, no start time, a bug) is still
   listed, with the reason, and the rest of the card is served. An unreadable dataset is a 503 with a
   plain message, never a traceback. No upcoming event is a 200 with `event: null` and a reason, so the
   page can say when the data was last updated instead of showing an error.

WHICH EVENT IS "THE NEXT ONE"
-----------------------------
The same rule as GET /data/v1/ufc/upcoming: status scheduled or in progress, and started no more than 36
hours ago (a card runs for hours and its status flips late), soonest first. Dana White's Contender Series is
a development show whose fighters have no UFC fights on file, so it is never the default; it is listed in
`other_events` and can be opened by id.

BOUTS THAT ARE NOT UPCOMING ANY MORE
------------------------------------
`matchup()` finds only a bout whose status is `scheduled`, so for a finished or in-progress bout (tonight's
card, once it is under way) the sheet is built as of that bout's own start, and the bout and its prices are
attached with the data layer's own public helpers. The read therefore always describes the fight going in,
never the result; a finished bout's result is shown beside it as a plain fact.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api import datasvc
from api.auth import require_paid_access
from src.analysis import ufc_read
from src.situation import ufc as situation_ufc
from src.datasvc.ufc import features as features_mod
from src.datasvc.ufc import matchup as matchup_mod

router = APIRouter(prefix="/ufc", dependencies=[Depends(require_paid_access)])

DEVELOPMENT_SHOW = "contender series"
NO_EVENT_REASON = "No UFC event is scheduled in our data right now."


def _now() -> datetime:
    """The clock. Tests pin `api.datasvc._now`; this follows it so one patch moves both."""
    return datasvc._now()


# -- picking the event -------------------------------------------------------------------------------

def is_development_show(event: dict) -> bool:
    return DEVELOPMENT_SHOW in str(event.get("name") or "").lower()


def _events_asc(store) -> List[dict]:
    return store.view("ufc_fights_events_asc", lambda: sorted(
        store.events, key=lambda e: (datasvc._date_key(e.get("date_utc")), str(e.get("event_id")))))


def upcoming_events(store, now: datetime) -> List[dict]:
    """Events not yet finished and not stale, soonest first (the rule of /data/v1/ufc/upcoming)."""
    earliest = now - datasvc.UPCOMING_GRACE
    out = []
    for event in _events_asc(store):
        start = features_mod.instant(event.get("date_utc"))
        if event.get("status") in ("scheduled", "in_progress") and start is not None and start >= earliest:
            out.append(event)
    return out


def default_event(events: List[dict]) -> Optional[dict]:
    for event in events:
        if not is_development_show(event):
            return event
    return events[0] if events else None


def _event_summary(event: dict) -> dict:
    return {"event_id": event.get("event_id"), "name": event.get("name"), "short_name": event.get("short_name"),
            "date_utc": event.get("date_utc"), "status": event.get("status"),
            "bout_count": len(event.get("bout_ids") or []), "development_show": is_development_show(event)}


# -- one bout ----------------------------------------------------------------------------------------

def _fighter(store, fighter_id: Optional[str]) -> dict:
    record = store.fighter_by_id().get(fighter_id) if fighter_id else None
    record = record or {}
    return {"fighter_id": fighter_id, "name": record.get("name"), "nickname": record.get("nickname"),
            "record": record.get("record"), "stance": record.get("stance"),
            "weight_class": record.get("weight_class")}


def _result(store, bout: dict) -> Optional[dict]:
    """The outcome of a finished bout, as plain facts; None for a bout with no result yet."""
    winner, method = bout.get("winner_id"), bout.get("result_method")
    if bout.get("status") != "final" or (not winner and method not in ("DRAW", "NC")):
        return None
    name = (store.fighter_by_id().get(winner) or {}).get("name") if winner else None
    return {"outcome": "decided" if winner else ("draw" if method == "DRAW" else "no_contest"),
            "winner_id": winner, "winner_name": name, "method": method,
            "method_words": ufc_read.method_words(method) if method else None,
            "detail": bout.get("result_detail"), "end_round": bout.get("end_round"),
            "end_time_s": bout.get("end_time_s")}


def _sheet_for(store, bout: dict, now: datetime) -> dict:
    """The fact sheet for THIS bout. Raises when it cannot be built; the caller turns that into a reason."""
    a, b = bout.get("fighter_a_id"), bout.get("fighter_b_id")
    if not a or not b:
        raise LookupError("a fighter is not named for this bout yet")
    if bout.get("status") == "scheduled":
        sheet = matchup_mod.matchup(store, a, b, now=now)
        if (sheet.get("bout") or {}).get("bout_id") == bout["bout_id"]:
            return sheet
    start = features_mod.bout_start(bout)
    if start is None:
        raise ValueError("this bout has no start time on file")
    # Not (or no longer) the pair's scheduled bout: measure both fighters as of this bout's own start
    # and attach this bout and its prices with the data layer's own helpers.
    sheet = matchup_mod.matchup(store, a, b, start, now=now)
    sheet["bout"] = dict(matchup_mod.bout_summary(store, bout), other_scheduled_bout_ids=[])
    sheet["odds"] = matchup_mod.bout_odds(store, bout, a, b)
    sheet["missing"] = [m for m in sheet["missing"] if not (m.get("side") is None and m.get("figure") in ("bout", "odds"))]
    if sheet["odds"] is None:
        sheet["missing"].append({"side": None, "figure": "odds", "reason": "no odds row for this bout"})
    elif sheet["odds"].get("note"):
        sheet["missing"].append({"side": None, "figure": "odds", "reason": sheet["odds"]["note"]})
    return sheet


_REASONS = {
    features_mod.UnknownFighter: "a fighter on this bout is not in our data yet",
}


def _reason_for(exc: Exception) -> str:
    for kind, text in _REASONS.items():
        if isinstance(exc, kind):
            return text
    if isinstance(exc, ValueError) and "same fighter" in str(exc):
        return "the bout lists the same fighter on both sides"
    if isinstance(exc, (LookupError, ValueError)) and not isinstance(exc, KeyError):
        return str(exc).replace("_", " ")
    return "the fact sheet for this bout could not be built"


def _bout_payload(store, bout: dict, now: datetime) -> dict:
    a, b = bout.get("fighter_a_id"), bout.get("fighter_b_id")
    out = {
        "bout_id": bout.get("bout_id"), "match_number": bout.get("match_number"),
        "card_segment": bout.get("card_segment"), "date_utc": bout.get("date_utc"),
        "weight_class": bout.get("weight_class"), "scheduled_rounds": bout.get("scheduled_rounds"),
        "status": bout.get("status"), "title_bout": bout.get("title_bout"),
        "fighter_a": _fighter(store, a), "fighter_b": _fighter(store, b),
        "result": _result(store, bout), "odds": None, "sheet": None, "read": None, "unavailable": None,
    }
    try:
        if a and b:
            out["odds"] = matchup_mod.bout_odds(store, bout, a, b, detail="current")
    except datasvc.DataUnavailable:
        raise       # a dataset that cannot be read is the whole card's problem (a 503), not this one bout's
    except Exception as exc:  # noqa: BLE001 -- the price is optional; the rest of the bout still serves
        _log(f"odds for bout {bout.get('bout_id')}", exc)
    if bout.get("status") in ("canceled", "postponed"):
        out["unavailable"] = f"This bout is listed as {'cancelled' if bout['status'] == 'canceled' else 'postponed'}."
        return out
    try:
        out["sheet"] = _sheet_for(store, bout, now)
    except datasvc.DataUnavailable:
        raise       # see above: fourteen bouts all "could not be built" would hide a corrupt file behind a 200
    except Exception as exc:  # noqa: BLE001 -- fail soft: the bout is listed with the reason
        _log(f"sheet for bout {bout.get('bout_id')}", exc)
        out["unavailable"] = _cap(_reason_for(exc)) + "."
        return out
    # The situation around the bout (src/situation/ufc.py), from the sheet's own features so nothing is
    # computed twice. Display only and fail soft: a bout whose situation cannot be built is shown
    # without the block, never without its read.
    try:
        out["situation"] = situation_ufc.situation_for_bout(store, bout["bout_id"], sheet=out["sheet"])
    except datasvc.DataUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        _log(f"situation for bout {bout.get('bout_id')}", exc)
        out["situation"] = None
    try:
        out["read"] = ufc_read.build_read(out["sheet"], situation=out.get("situation"))
    except Exception as exc:  # noqa: BLE001
        _log(f"read for bout {bout.get('bout_id')}", exc)
        out["unavailable"] = "The written read for this bout could not be built, so only the facts are shown."
    return out


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _log(what: str, exc: BaseException) -> None:
    print(f"error_id={uuid.uuid4().hex} ufc_fight_night {what}: {exc!r}", file=sys.stderr, flush=True)


# -- one event ---------------------------------------------------------------------------------------

def _ordered_bouts(store, event: dict) -> tuple:
    by_id = store.bout_by_id()
    ids = list(event.get("bout_ids") or [])
    present = [(i, by_id[bid]) for i, bid in enumerate(ids) if bid in by_id]
    present.sort(key=lambda p: (p[1].get("match_number") if isinstance(p[1].get("match_number"), int) else 10 ** 6, p[0]))
    return [b for _, b in present], [bid for bid in ids if bid not in by_id]


def _newest_fetch(store, event: Optional[dict]) -> Optional[str]:
    """When the data behind this answer was last fetched: the newest `fetched_utc` among the event, its bouts
    and their price rows (or, with no event, among every event)."""
    stamps = []
    if event is None:
        stamps = [e.get("fetched_utc") for e in store.events]
    else:
        stamps.append(event.get("fetched_utc"))
        odds = store.odds_for_bout()
        for bout in _ordered_bouts(store, event)[0]:
            stamps.append(bout.get("fetched_utc"))
            stamps += [r.get("fetched_utc") for r in odds.get(bout["bout_id"], ())]
    parsed = [(features_mod.instant(s), s) for s in stamps if s]
    parsed = [p for p in parsed if p[0] is not None]
    return max(parsed, key=lambda p: p[0])[1] if parsed else None


def _build(store, event: Optional[dict], now: datetime, upcoming: List[dict]) -> dict:
    others = [_event_summary(e) for e in upcoming]
    if event is None:
        return {"event": None, "bouts": [], "missing_bout_ids": [], "reason": NO_EVENT_REASON,
                "data_updated_utc": _newest_fetch(store, None), "other_events": others, "label": ufc_read.LABEL}
    bouts, missing = _ordered_bouts(store, event)
    return {
        "event": _event_summary(event),
        "bouts": [_bout_payload(store, bout, now) for bout in bouts],
        "missing_bout_ids": missing,
        "reason": None if bouts else "This event has no bouts on file yet.",
        "data_updated_utc": _newest_fetch(store, event),
        "other_events": others, "label": ufc_read.LABEL,
    }


def _serve(event_id: Optional[str], sheet: str = "full") -> dict:
    now = _now()
    try:
        store = datasvc._store()
        upcoming = upcoming_events(store, now)
        if event_id is None:
            event = default_event(upcoming)
            key = f"ufc_fight_night:{event['event_id']}" if event else "ufc_fight_night:none"
        else:
            event = store.event_by_id().get(event_id)
            if event is None:
                raise HTTPException(status_code=404, detail="no UFC event with that id is on file")
            key = f"ufc_fight_night:{event_id}"
        # Built once per store version. The upcoming list is part of the key's meaning (it is what the
        # payload's `other_events` says), and it changes only when the files do or when a card ages out of
        # the 36 hour window, so the key carries the ids it was built from.
        key += ":" + ",".join(str(e["event_id"]) for e in upcoming)
        payload = store.view(key, lambda: _build(store, event, now, upcoming))
    except datasvc.DataUnavailable as exc:
        print(f"ufc fight night: dataset {exc.dataset!r} could not be read: {exc.__cause__!r}",
              file=sys.stderr, flush=True)
        raise HTTPException(status_code=503, detail="UFC data is not readable right now") from exc
    out = dict(payload, generated_utc=features_mod.iso_utc(now))
    if sheet == "compact":
        out["bouts"] = [dict(b, sheet=ufc_read.compact_sheet(b.get("sheet"))) for b in payload["bouts"]]
    return out


SHEET_PARAM = Query("full", pattern="^(full|compact)$",
                    description="full: the whole fact sheet per bout; compact: what the page draws from it")


@router.get("/fight-night", summary="The next UFC card, bout by bout, with the facts and the written read")
def get_fight_night(sheet: str = SHEET_PARAM) -> dict:
    return _serve(None, sheet)


@router.get("/fight-night/{event_id}", summary="One UFC card, bout by bout, with the facts and the written read")
def get_fight_night_event(event_id: str, sheet: str = SHEET_PARAM) -> dict:
    return _serve(event_id, sheet)
