"""The operations the Apprentice routes call, with every dependency injectable (no web framework in here).

Each function takes the hound row (``user_store`` shape) and the signed-in owner's id, and refuses anything that is not that
owner's own Apprentice hound. Nothing here edits or deletes a row: the only writes are ``store.add_lesson`` and
``store.append_event``.
"""

from __future__ import annotations

import base64
import binascii
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Mapping, Optional

from src.hounds import user_spec
from src.hounds.apprentice import analytics, board, extract, grading, learning, model, store

SETTLE_EVERY_S = 600.0
_settle_state: dict = {}
_lock = threading.Lock()


class ServiceError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.code, self.status, self.extra = code, status, extra


def check_owner(hound: Optional[Mapping], owner_id: int) -> Mapping:
    """404 for not-yours and not-there alike, and for a hound that is not an Apprentice."""
    if hound is None or hound.get("owner_user_id") != owner_id or not user_spec.is_apprentice(hound.get("spec") or {}):
        raise ServiceError("not_found", "no such hound", 404)
    return hound


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def lesson_view(lesson: Mapping, events: list, rec: Optional[Mapping] = None) -> dict:
    view = model.derive(lesson, events)
    grade, why = model.evidence_grade(lesson, rec)
    legs = [{k: leg.get(k) for k in ("sport", "game", "market", "selection", "side", "line", "price", "player", "event_id")}
            for leg in lesson["legs"]]
    return {"id": lesson["id"], "bet_type": lesson["bet_type"], "legs": legs, "stake": lesson["stake"], "book": lesson["book"],
            "placed_utc": lesson["placed_utc"], "ticket_id": lesson["ticket_id"], "total_price": lesson["total_price"],
            "payout_quoted": lesson["payout_quoted"], "source": lesson["source"], "state": view["state"],
            "result": view["result"], "basis": view["basis"], "disputed": view["disputed"], "flags": view["flags"],
            "payout": view["payout"], "profit": view["profit"], "cash_out_amount": view["cash_out_amount"],
            "leg_results": view["leg_results"], "history": view["history"],
            # the audit's columns: whose money, the recommendation it came from, when each thing happened, how it closed
            "owner": lesson.get("bettor") or "unknown", "recommendation_id": lesson.get("recommendation_id"),
            "recommended_at": lesson.get("recommended_utc"), "placed_at": lesson["placed_utc"],
            "settlement_time": view["settlement_time"], "game_id": next((l.get("event_id") for l in lesson["legs"] if l.get("event_id")), None),
            "closing_line": view["closing_line"], "evidence_grade": grade, "evidence_reason": why}


def _view_of(pair: tuple, db=None) -> dict:
    """The view of one (lesson, events) pair, graded against the recommendation it links (if any)."""
    rid = pair[0].get("recommendation_id")
    return lesson_view(pair[0], pair[1], store.get_recommendation(rid, db=db) if rid else None)


def maybe_settle(hound: Mapping, owner_id: int, *, now: Optional[datetime] = None, force: bool = False, db=None,
                 path: Optional[str] = None, settle_kwargs: Optional[dict] = None) -> dict:
    """Publish the legs, run the slow settle path at most every ten minutes, and record what the grader decided."""
    key = hound["root_id"]
    with _lock:
        due = force or time.monotonic() - _settle_state.get(key, -1e9) >= SETTLE_EVERY_S
        if due:
            _settle_state[key] = time.monotonic()
    return grading.sync(hound["root_id"], owner_id, path=path, now=_now(now), run_settle=due, settle_kwargs=settle_kwargs, db=db)


def overview(hound: Mapping, owner_id: int, *, now: Optional[datetime] = None, db=None, grade: bool = True,
             path: Optional[str] = None, settle_kwargs: Optional[dict] = None) -> dict:
    check_owner(hound, owner_id)
    if grade and hound["status"] not in ("buried",):
        try:
            maybe_settle(hound, owner_id, now=now, db=db, path=path, settle_kwargs=settle_kwargs)
        except Exception:  # noqa: BLE001 -- an unreadable results store leaves lessons open, never breaks the page
            pass
    pairs = store.lessons_for(hound["root_id"], db=db)
    recs = store.recommendations(db=db)
    by_id = {r["id"]: r for r in recs}
    views = [lesson_view(lsn, ev, by_id.get(lsn.get("recommendation_id"))) for lsn, ev in pairs]
    views.sort(key=lambda v: (v["placed_utc"], v["id"]), reverse=True)
    return {"hound_id": hound["id"], "status": hound["status"], "lessons": views, "analytics": analytics.summarize(pairs, recs),
            "can_add": hound["status"] not in ("retired", "buried"),
            "note": "Lessons are your real bets, kept as logged. They are never edited or deleted, and they are not the "
                    "hound's own paper tickets.", "paper_only": True}


def _initial_state(lesson_id: str, owner_id: int, state: Optional[Mapping], *, now, db, image=None) -> None:
    if not state or state.get("state") in (None, model.PENDING):
        return
    data = {k: state[k] for k in ("result", "cash_out_amount", "payout") if state.get(k) is not None}
    store.append_event(lesson_id, owner_id, "owner", state["state"], data, now=now, db=db)


def _attach_recommendation(clean: dict, db) -> None:
    """Copy the linked recommendation's publish time onto the (immutable) lesson, or refuse an id nobody published."""
    rid = clean.get("recommendation_id")
    if not rid:
        clean["recommended_utc"] = None
        return
    rec = store.get_recommendation(rid, db=db)
    if rec is None:
        raise ServiceError("unknown_recommendation", "No published recommendation has that ID.", 422,
                           fields={"recommendation_id": "no published recommendation has that ID"})
    clean["recommended_utc"] = rec["recommended_utc"]


def add_manual(hound: Mapping, owner_id: int, raw: Mapping, *, now: Optional[datetime] = None, games: Optional[list] = None,
               db=None, path: Optional[str] = None) -> dict:
    """File a hand-typed lesson. ``games`` is the board (default: read it) used to pin any leg that names an event id."""
    check_owner(hound, owner_id)
    now = _now(now)
    raw = dict(raw)
    legs = raw.get("legs")
    if isinstance(legs, list) and any(isinstance(g, Mapping) and g.get("event_id") for g in legs):
        raw["legs"] = board.pin_legs([dict(g) if isinstance(g, Mapping) else g for g in legs],
                                     games if games is not None else board.board_games(now))
    elif isinstance(legs, list):
        raw["legs"] = board.pin_legs([dict(g) if isinstance(g, Mapping) else g for g in legs], [])
    try:
        clean = model.normalize_lesson(raw, now=now)
    except model.LessonError as exc:
        raise ServiceError(exc.code, str(exc), 422, fields=exc.fields)
    _attach_recommendation(clean, db)
    try:
        lesson = store.add_lesson(hound, owner_id, clean, source="owner", now=now, db=db)
        _initial_state(lesson["id"], owner_id, raw.get("state"), now=now, db=db)
    except store.StoreError as exc:
        raise ServiceError(exc.code, str(exc), exc.status, **exc.extra)
    grading.publish([(lesson, [])], path=path, now=now)
    pairs = [p for p in store.lessons_for(hound["root_id"], db=db) if p[0]["id"] == lesson["id"]]
    return _view_of(pairs[0], db)


def set_state(hound: Mapping, owner_id: int, lesson_id: str, state: str, data: Optional[Mapping] = None, *,
              now: Optional[datetime] = None, db=None) -> dict:
    """Append the owner's word on a lesson's state (including a cash-out and a dispute resolution). Never edits."""
    check_owner(hound, owner_id)
    lesson = store.get_lesson(lesson_id, db=db)
    if lesson is None or lesson["hound_root"] != hound["root_id"]:
        raise ServiceError("not_found", "no such lesson", 404)
    data = {k: v for k, v in (data or {}).items() if k in ("result", "cash_out_amount", "payout", "resolution", "settlement_time")}
    try:
        ev = store.append_event(lesson_id, owner_id, "owner", state, data, now=_now(now), db=db)
    except store.StoreError as exc:
        raise ServiceError(exc.code, str(exc), exc.status, **exc.extra)
    pair = [p for p in store.lessons_for(hound["root_id"], db=db) if p[0]["id"] == lesson_id][0]
    return {"changed": ev is not None, "lesson": _view_of(pair, db)}


def decode_image(b64: str) -> bytes:
    try:
        data = base64.b64decode(b64 or "", validate=True)
    except (binascii.Error, ValueError, TypeError):
        raise ServiceError("bad_image", "that is not a valid image upload", 422)
    try:
        store.sniff_image(data)
    except store.StoreError as exc:
        raise ServiceError(exc.code, str(exc), exc.status)
    return data


def import_screenshot(hound: Mapping, owner_id: int, data: bytes, router, *, utc_offset_minutes: Optional[int] = None,
                      now: Optional[datetime] = None, games: Optional[list] = None, players_known: Optional[Callable] = None,
                      db=None) -> dict:
    """Upload -> draft (nothing filed). See ``extract.import_image``."""
    check_owner(hound, owner_id)
    if hound["status"] in ("retired", "buried"):
        raise ServiceError("not_active", f"this hound is {hound['status']}; its lessons stay, but it takes no new ones", 409)
    now = _now(now)
    try:
        return extract.import_image(owner_id, data, router, utc_offset_minutes=utc_offset_minutes,
                                    board_games=games if games is not None else board.board_games(now),
                                    players_known=players_known, now=now, db=db)
    except store.StoreError as exc:
        raise ServiceError(exc.code, str(exc), exc.status, **exc.extra)


def confirm_import(hound: Mapping, owner_id: int, image_hash: str, submitted: Mapping, *, acknowledged=(),
                   lesson_id: Optional[str] = None, now: Optional[datetime] = None, games: Optional[list] = None,
                   db=None, path: Optional[str] = None) -> dict:
    """The owner confirms (or edits) a staged draft. Only now does anything reach the ledger.

    New bet: the lesson is filed with its screenshot and extraction as evidence. A bet already filed (``lesson_id``, found by
    bet ID at import): the screenshot is appended as evidence and, when the ticket's status differs from what the ledger
    holds, a state-change event (source ticket) is appended; the lesson row itself is never touched. Refused while an
    ambiguous field is still the model's raw reading and has not been edited or acknowledged."""
    check_owner(hound, owner_id)
    now = _now(now)
    st = store.staged(owner_id, image_hash, db=db)
    if st is None:
        raise ServiceError("image_not_staged", "that screenshot is not waiting for confirmation; upload it again", 409)
    staged_json = st["json"] or {}
    drafted = staged_json.get("drafted") or {}
    ambiguous = staged_json.get("ambiguous") or []
    left = extract.unresolved(ambiguous, drafted, submitted, acknowledged)
    if left:
        raise ServiceError("unconfirmed_fields", "Confirm or fix the highlighted fields first.", 422, fields=left)
    ticket_state = staged_json.get("ticket_state") or {"state": model.PENDING, "data": {}}
    if lesson_id:
        lesson = store.get_lesson(lesson_id, db=db)
        if lesson is None or lesson["hound_root"] != hound["root_id"] or lesson["owner_id"] != owner_id:
            raise ServiceError("not_found", "no such lesson", 404)
        try:
            ev = store.append_event(lesson_id, owner_id, "ticket", ticket_state["state"], ticket_state.get("data") or {},
                                    image=image_hash, now=now, db=db)
        except store.StoreError as exc:
            raise ServiceError(exc.code, str(exc), exc.status, **exc.extra)
        pair = [p for p in store.lessons_for(hound["root_id"], db=db) if p[0]["id"] == lesson_id][0]
        return {"filed": False, "state_changed": ev is not None, "lesson": _view_of(pair, db)}
    staged_games = [{"event_id": g["event_id"], "sport": g["sport"], "away_team": g["away_team"], "home_team": g["home_team"],
                     "commence_utc": g.get("commence_time"), "slate_date": g.get("slate_date")}
                    for g in drafted.get("legs") or [] if g.get("event_id")]
    raw = dict(submitted)
    raw["legs"] = board.pin_legs([dict(g) for g in (raw.get("legs") or []) if isinstance(g, Mapping)],
                                 (games if games is not None else board.board_games(now)) + staged_games)
    try:
        clean = model.normalize_lesson(raw, now=now)
    except model.LessonError as exc:
        raise ServiceError(exc.code, str(exc), 422, fields=exc.fields)
    _attach_recommendation(clean, db)
    try:
        lesson = store.add_lesson(hound, owner_id, clean, source="dk_import", image=image_hash, now=now, db=db)
        if ticket_state["state"] != model.PENDING:
            store.append_event(lesson["id"], owner_id, "ticket", ticket_state["state"], ticket_state.get("data") or {},
                               now=now, db=db)
    except store.StoreError as exc:
        raise ServiceError(exc.code, str(exc), exc.status, **exc.extra)
    grading.publish([(lesson, [])], path=path, now=now)
    pair = [p for p in store.lessons_for(hound["root_id"], db=db) if p[0]["id"] == lesson["id"]][0]
    return {"filed": True, "state_changed": ticket_state["state"] != model.PENDING, "lesson": _view_of(pair, db)}


def proposal(hound: Mapping, owner_id: int, *, now: Optional[datetime] = None, db=None) -> dict:
    check_owner(hound, owner_id)
    return learning.propose(hound, store.lessons_for(hound["root_id"], db=db), _now(now))


def apply_proposal(hound: Mapping, owner_id: int, basis: str, as_of: str, *, now: Optional[datetime] = None, db=None) -> dict:
    check_owner(hound, owner_id)
    try:
        return learning.apply(hound, owner_id, store.lessons_for(hound["root_id"], db=db), basis, as_of=as_of, now=now, db=db)
    except learning.ApplyError as exc:
        raise ServiceError(exc.code, str(exc), exc.status)
