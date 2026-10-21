"""Interacting with a dog: unleash it, ask it, rate it, dress it, drill it, send it to training or take it out back,
and the Training camp's own data.

    GET  /hounds/{id}/kit             what this visitor can do on this dog's page (token optional)
    POST /hounds/{id}/fire            "What would you bet right now?" (the pages call it UNLEASH; the route keeps its
                                      name): the rule over the latest stored boards, READ ONLY; public, rate limited
                                      per address
    POST /hounds/{id}/unleash         the owner of a member dog: START it betting today (paper, forward) and show the day, with
                                      what it would have taken before it started (not on its record); free accounts included
                                      (src/hounds/interact/unleash.py)
    POST /hounds/{id}/out-back        the owner of a member dog, {"confirm": true}: the dog is BURIED, its record frozen
                                      and public, a headstone in the graveyard (src/hounds/interact/outback.py)
    POST /hounds/{id}/train           the owner of a member dog, {"confirm": true}: SEND TO TRAINING, the dog comes back
                                      as a new version (src/hounds/interact/training.py)
    GET  /hounds/{id}/headstone       a buried dog's headstone (public)
    GET  /hounds/{id}/ask             the dog's greeting and the questions worth asking it
    POST /hounds/{id}/ask             {"question": "..."}: an answer BUILT FROM THE DOG'S DATA (no model is called)
    GET  /hounds/{id}/manual          the owner's manual tickets, kept apart from the rule's record
    POST /hounds/{id}/manual          the owner records a manual pick: {"event_id", "market"} (paper only)
    POST /hounds/{id}/manual/batch    the owner records many at once: {"picks": [{"event_id", "market"}, ...]} (at most 40),
                                      each through the same refusals as the single pick; answers added / skipped with reasons
    GET  /hounds/{id}/feedback        Good call / Bad call counts (and, for a signed-in caller, their own votes)
    POST /hounds/{id}/feedback        signed in: {"target_kind", "target_id", "verdict": good|bad, "note"?}
    POST /hounds/{id}/suggest         signed in, not the owner, builder dogs: a suggested change for the owner
    GET  /hounds/{id}/look            a builder dog's look (public)
    PUT  /hounds/{id}/look            the owner: {"look": {...}} validated against the locker-room whitelist
    GET  /hounds/looks?ids=a,b        looks for several dogs at once (the lists draw their badges from this)
    GET  /hounds/camp/mine            signed in: the caller's dogs for the Training camp
    POST /hounds/drill                signed in: {"dog_id" | "spec", "days": 7|14|30 | "season": "s2"}: a hindsight drill
                                      (the Backtest tab calls it), never counted

PAID TOOLS ON MEMBER DOGS (owner decision 2026-10-20, api/entitlements.py). A free account keeps one dog, and
three tools on a member (builder) dog are for paid accounts only: a LIVE SEND (``POST /hounds/{id}/fire`` with an
``event_id``), BACKTEST (``POST /hounds/drill``, except a drill of a house dog) and ASK (``POST /hounds/{id}/ask``).
A free account gets a 402 ``upgrade_required`` naming the tool; a signed-out caller gets a 401. The house pack's
public pages keep everything they had, and so does the plain "Unleash" preview (``fire`` with no
``event_id``) on any dog, and the Ask greeting (``GET /hounds/{id}/ask``).

THE TWO RITES (owner ruling 2026-10-20). ``out-back`` and ``train`` are for the OWNER of a MEMBER dog, free accounts
included (a free account's one dog can be buried or trained). A house dog is refused (422 ``not_a_member_dog``), a
member dog that is someone else's reads as not found, and both refuse while the dog has a ticket that has not settled
(409 ``open_tickets``). ``out-back`` also refuses a dog already buried (409), and ``train`` refuses a dog that trained
and has not yet settled 5 new bets on its current version (409 ``training_too_soon``). Both need ``{"confirm": true}``
in the body, so a stray POST changes nothing.

NOTHING HERE WRITES TO A DOG'S RULE RECORD. The fire route writes nothing. The manual pick goes to its own
ledger (src/hounds/interact/manual.py). Feedback and looks are rows in two small tables. A drill replays in a
temporary ledger. Every payload carries ``paper_only: true`` and the not-advice line.

MOUNT ORDER. ``/hounds/looks``, ``/hounds/camp/mine`` and ``POST /hounds/drill`` are literal paths next to
``/hounds/{id}``; this router is mounted BEFORE api.hounds (api/app.py does, and a test pins it).
"""

from __future__ import annotations

import types
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel

from src.appstate import ratelimit
from src.appstate import users as users_store
from src.hounds import user_spec
from src.hounds.contract import envelope
from src.hounds.interact import ask, ask_eval, camp, common, drill, fire, fire_event, look, manual, outback, rites, store, training, unleash

from api import auth as auth_mod
from api import entitlements
from api.auth import get_current_user

router = APIRouter()

_NO_STORE = "no-store"

_fire_limiter = ratelimit.FixedWindowLimiter(limit=20, window_s=60.0)
_rl_fire = ratelimit.limiter_dependency(_fire_limiter)
# A person who is not signed in can still tap "Fire now", and each tap that misses the cache costs a store read.
# The cache is shared (fire.py double-checks it under the build gate), but an unsigned caller also gets a tighter
# per-address allowance than the 20 a minute the signed-in get (red team 2026-10-19).
FIRE_UNSIGNED_PER_MIN = 8
_fire_unsigned_limiter = ratelimit.FixedWindowLimiter(limit=FIRE_UNSIGNED_PER_MIN, window_s=60.0)
_rl_fire_unsigned = ratelimit.limiter_dependency(_fire_unsigned_limiter)


def _rl_fire_route(request: Request, authorization: Optional[str] = Header(default=None)) -> None:
    _rl_fire(request)
    if auth_mod.optional_user_id(authorization) is None:
        _rl_fire_unsigned(request)


_ask_limiter = ratelimit.FixedWindowLimiter(limit=40, window_s=60.0)
_rl_ask = ratelimit.limiter_dependency(_ask_limiter)
_read_limiter = ratelimit.FixedWindowLimiter(limit=120, window_s=60.0)
_rl_read = ratelimit.limiter_dependency(_read_limiter)
_write_limiter = ratelimit.FixedWindowLimiter(limit=60, window_s=3600.0)
_rl_write = ratelimit.limiter_dependency(_write_limiter, user_dependency=get_current_user)
# 5 an hour per person: a 30-day house drill peaks near 700 MB (red team 2026-10-19), so this is a deliberately
# scarce tool; the half-hour result cache in drill.py makes a repeat of the same drill free of the engine.
DRILL_PER_USER_PER_HOUR = 5
_drill_limiter = ratelimit.FixedWindowLimiter(limit=DRILL_PER_USER_PER_HOUR, window_s=3600.0)
_rl_drill = ratelimit.limiter_dependency(_drill_limiter, user_dependency=get_current_user)
_manual_limiter = ratelimit.FixedWindowLimiter(limit=30, window_s=3600.0)
_rl_manual = ratelimit.limiter_dependency(_manual_limiter, user_dependency=get_current_user)
# a batch is up to 40 picks of work in one request, so it gets a smaller hourly allowance than the single pick
_manual_batch_limiter = ratelimit.FixedWindowLimiter(limit=10, window_s=3600.0)
_rl_manual_batch = ratelimit.limiter_dependency(_manual_batch_limiter, user_dependency=get_current_user)
# An unleash reads one slate of boards under the heavy gate and may write a handful of bets; a person taps it a few
# times a day at most, and the bet id makes a repeat free of side effects.
_unleash_limiter = ratelimit.FixedWindowLimiter(limit=30, window_s=3600.0)
_rl_unleash = ratelimit.limiter_dependency(_unleash_limiter, user_dependency=get_current_user)
# A burial and a training each read the whole user ledger once; a person does either a handful of times, ever.
_rites_limiter = ratelimit.FixedWindowLimiter(limit=20, window_s=3600.0)
_rl_rites = ratelimit.limiter_dependency(_rites_limiter, user_dependency=get_current_user)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _err(status: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": code, "message": message, **extra})


def _dog(hound_id: str) -> common.Dog:
    dog = common.resolve(hound_id)
    if dog is None:
        raise _err(404, "not_found", "no such dog")
    return dog


def _owned(hound_id: str, user: users_store.User) -> common.Dog:
    dog = _dog(hound_id)
    if dog.kind != common.KIND_USER or dog.owner_user_id != user.id:
        raise _err(404, "not_found", "no such dog")        # not-yours reads exactly like not-there
    return dog


def _viewer_id(authorization: Optional[str]) -> Optional[int]:
    return auth_mod.optional_user_id(authorization)


class FireRequest(BaseModel):
    """POST /hounds/{id}/fire body, all optional: ``event_id`` asks about ONE game (src/hounds/interact/fire_event.py)."""
    event_id: Optional[str] = None


def _event_payload(dog: common.Dog, event_id: str) -> dict:
    """Would this dog back THIS game: picked (with the pick) or not (with the reason). Read only."""
    event_id = event_id.strip()
    if not event_id or len(event_id) > 120:
        raise _err(422, "bad_event_id", "event_id must be a short non-empty string")
    try:
        out = fire_event.answer(dog, event_id)
    except fire.NotFirable as exc:
        raise _err(422, "not_firable", str(exc))
    for pick in [out.get("pick")] + list(out.get("picks") or []):
        if isinstance(pick, dict):
            pick.pop("row", None)
    return out


def _fire_payload(dog: common.Dog, viewer_id: Optional[int] = None) -> dict:
    """The fire preview as the page gets it (src/hounds/interact/camp.py ``decorate_fire``)."""
    try:
        out = fire.fire(dog)
    except fire.NotFirable as exc:
        raise _err(422, "not_firable", str(exc))
    return camp.decorate_fire(dog, out, viewer_id)


def _graded_tips(dog: common.Dog) -> list:
    """Graded tips (the coach's and the fans') about this dog, from the report card. Best effort."""
    try:
        from src.hounds import coach_report
        report = coach_report.build()
    except Exception:  # noqa: BLE001
        return []
    tips = []
    for item in (report.get("items") or []):
        if item.get("hound") == dog.id:
            tips.append({"kind": "coach", "label": (item.get("forward") or {}).get("label") or "TOO EARLY",
                         "line": item.get("line")})
    for item in ((report.get("fans") or {}).get("items") or []):
        if item.get("hound") == dog.id:
            tips.append({"kind": "fan", "label": (item.get("forward") or {}).get("label") or "TOO EARLY",
                         "line": item.get("line")})
    return tips


def _manual_error(exc: manual.ManualError) -> HTTPException:
    return _err(exc.status, exc.code, str(exc))


# ---------------------------------------------------------------------------
# the kit
# ---------------------------------------------------------------------------

@router.get("/hounds/looks")
def looks(response: Response, ids: str = Query("", max_length=1500), _rl: None = Depends(_rl_read)) -> dict:
    """{dog_id: look} for the builder dogs among ``ids`` that have saved a look (at most 40 ids)."""
    response.headers["Cache-Control"] = "public, max-age=30"
    wanted = [i.strip() for i in ids.split(",") if i.strip()][:40]
    roots: dict = {}
    for hound_id in wanted:
        dog = common.resolve(hound_id)
        if dog is not None and dog.kind == common.KIND_USER:
            roots[hound_id] = dog.root_id
    by_root = store.get_looks(set(roots.values()))
    return envelope({"looks": {hid: by_root[root] for hid, root in roots.items() if root in by_root}})


@router.get("/hounds/camp/mine")
def camp_mine(response: Response, current_user: users_store.User = Depends(get_current_user),
              _rl: None = Depends(_rl_read)) -> dict:
    response.headers["Cache-Control"] = _NO_STORE
    manual.maybe_settle()
    return envelope(camp.mine(current_user.id))


class DrillRequest(BaseModel):
    dog_id: Optional[str] = None
    spec: Optional[Dict[str, Any]] = None
    days: int = 14
    season: Optional[str] = None           # a season id ("s2"): that season's completed days so far (Backtest tab)


@router.post("/hounds/drill")
def run_drill(body: DrillRequest, response: Response,
              current_user: users_store.User = Depends(get_current_user),
              _rl: None = Depends(_rl_drill)) -> dict:
    """A hindsight drill: read only, labelled, never counted (src/hounds/interact/drill.py)."""
    response.headers["Cache-Control"] = _NO_STORE
    target = None
    if body.dog_id:
        target = _dog(body.dog_id)
    if target is None or target.kind == common.KIND_USER:    # a drill of a rule or a member dog: paid only
        entitlements.require_paid_dog_tool(current_user, entitlements.FEATURE_BACKTEST)
    try:
        return envelope(drill.drill(days=body.days, dog=target, spec=body.spec if target is None else None,
                                     season=body.season))
    except drill.DrillError as exc:
        error = _err(exc.status, exc.code, str(exc), fields=exc.fields)
        if exc.retry_after:
            error.headers = {"Retry-After": str(exc.retry_after)}
            error.detail["retry_after"] = exc.retry_after
        raise error


@router.get("/hounds/{hound_id}/kit")
def kit(hound_id: str, response: Response, authorization: Optional[str] = Header(default=None),
        _rl: None = Depends(_rl_read)) -> dict:
    response.headers["Cache-Control"] = _NO_STORE
    dog = _dog(hound_id)
    return envelope(camp.kit(dog, _viewer_id(authorization)))


# ---------------------------------------------------------------------------
# fire now and the manual pick
# ---------------------------------------------------------------------------

@router.post("/hounds/{hound_id}/fire")
def fire_now(hound_id: str, response: Response, body: Optional[FireRequest] = None,
             authorization: Optional[str] = Header(default=None), _rl: None = Depends(_rl_fire_route),
             request: Request = None) -> dict:
    response.headers["Cache-Control"] = _NO_STORE
    dog = _dog(hound_id)
    if body is not None and body.event_id is not None:
        if dog.kind == common.KIND_USER:                     # a live send: paid accounts only
            entitlements.paid_dog_tool_for(authorization, request, entitlements.FEATURE_LIVE_SEND)
        return envelope(_event_payload(dog, body.event_id))
    return envelope(_fire_payload(dog, _viewer_id(authorization)))


@router.post("/hounds/{hound_id}/unleash")
def unleash_today(hound_id: str, response: Response, current_user: users_store.User = Depends(get_current_user),
                  _rl: None = Depends(_rl_unleash)) -> dict:
    """The owner's Unleash: start the dog betting today, once, and show the day (src/hounds/interact/unleash.py).
    Open to a free account on its own dog (one dog is what a free account keeps); somebody else's dog reads as not
    found. The per-game live send (``fire`` with an ``event_id``) stays a paid tool."""
    response.headers["Cache-Control"] = _NO_STORE
    try:
        return envelope(unleash.unleash(_dog(hound_id), current_user.id))
    except unleash.UnleashError as exc:
        raise _err(exc.status, exc.code, str(exc))


# ---------------------------------------------------------------------------
# the two rites: out back (a burial) and training
# ---------------------------------------------------------------------------

class RiteRequest(BaseModel):
    """The second tap's word. A POST without ``confirm: true`` is a 400 and the dog is untouched."""
    confirm: bool = False


def _rite_error(exc: rites.RiteError) -> HTTPException:
    return _err(exc.status, exc.code, str(exc), **exc.extra)


@router.post("/hounds/{hound_id}/out-back")
def take_out_back(hound_id: str, response: Response, body: Optional[RiteRequest] = None,
                  current_user: users_store.User = Depends(get_current_user),
                  _rl: None = Depends(_rl_rites)) -> dict:
    """Take the owner's dog out back: buried, record frozen, headstone in the graveyard. There is no taking it back."""
    response.headers["Cache-Control"] = _NO_STORE
    try:
        out = outback.bury(common.resolve(hound_id), current_user.id, confirmed=bool(body and body.confirm))
    except rites.RiteError as exc:
        raise _rite_error(exc)
    return envelope(out)


@router.post("/hounds/{hound_id}/train")
def send_to_training(hound_id: str, response: Response, body: Optional[RiteRequest] = None,
                     current_user: users_store.User = Depends(get_current_user),
                     _rl: None = Depends(_rl_rites)) -> dict:
    """Send the owner's dog to training: it studies its own settled bets and comes back as the next version, with its
    old record frozen and a new one starting now."""
    response.headers["Cache-Control"] = _NO_STORE
    try:
        out = training.train(common.resolve(hound_id), current_user.id, confirmed=bool(body and body.confirm))
    except rites.RiteError as exc:
        raise _rite_error(exc)
    return envelope(out)


@router.get("/hounds/{hound_id}/headstone")
def headstone(hound_id: str, response: Response, _rl: None = Depends(_rl_read)) -> dict:
    """A buried dog's headstone: its frozen record, its epitaph and where it came from. 404 for a dog that is not buried."""
    response.headers["Cache-Control"] = "public, max-age=60"
    stone = outback.headstone_for(hound_id) if common.valid_id(hound_id) else None
    if stone is None:
        raise _err(404, "not_found", "no headstone for that dog")
    return envelope({"headstone": stone})


@router.get("/hounds/{hound_id}/manual")
def manual_tickets(hound_id: str, response: Response, _rl: None = Depends(_rl_read)) -> dict:
    response.headers["Cache-Control"] = _NO_STORE
    dog = _dog(hound_id)
    if dog.kind != common.KIND_USER:
        return envelope({"tickets": [], "record": manual.record_summary([]), "dog_id": dog.id})
    manual.maybe_settle()
    items = manual.tickets(dog.id)
    return envelope({"dog_id": dog.id, "tickets": items, "record": manual.record_summary(items),
                     "limit_per_day": manual.PER_DAY_LIMIT, "note": manual.NOTE_COUNTED})


class ManualRequest(BaseModel):
    event_id: str
    market: str
    player: Optional[str] = None           # a player prop (a game can carry several): which player's


class ManualBatchRequest(BaseModel):
    picks: List[ManualRequest]


@router.post("/hounds/{hound_id}/manual/batch")
def record_manual_batch(hound_id: str, body: ManualBatchRequest, response: Response,
                        current_user: users_store.User = Depends(get_current_user),
                        _rl: None = Depends(_rl_manual_batch)) -> dict:
    """Record every listed pick ``manual.record`` accepts; the rest are skipped with a reason (src/hounds/interact/manual.py)."""
    response.headers["Cache-Control"] = _NO_STORE
    dog = _owned(hound_id, current_user)
    try:
        out = manual.record_batch(dog, current_user.id, [{"event_id": p.event_id, "market": p.market, "player": p.player}
                                                          for p in body.picks])
    except manual.ManualError as exc:
        raise _manual_error(exc)
    out["record"] = manual.record_summary(manual.tickets(dog.id))
    out["note"] = manual.NOTE_COUNTED
    return envelope(out)


@router.post("/hounds/{hound_id}/manual")
def record_manual(hound_id: str, body: ManualRequest, response: Response,
                  current_user: users_store.User = Depends(get_current_user),
                  _rl: None = Depends(_rl_manual)) -> dict:
    response.headers["Cache-Control"] = _NO_STORE
    dog = _owned(hound_id, current_user)
    try:
        ticket = manual.record(dog, current_user.id, body.event_id, body.market, player=body.player)
    except manual.ManualError as exc:
        raise _manual_error(exc)
    items = manual.tickets(dog.id)
    return envelope({"ticket": ticket, "record": manual.record_summary(items),
                     "remaining_today": manual.remaining_today(dog.id, common.now_utc()),
                     "note": manual.NOTE_COUNTED})


# ---------------------------------------------------------------------------
# ask
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str


def _retry_of(exc: HTTPException) -> Optional[int]:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    value = detail.get("retry_after")
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _context(dog: common.Dog, viewer_id: Optional[int], request: Optional[Request] = None,
             authorization: Optional[str] = None) -> ask.AskContext:
    """The facts and the three evaluations an answer may run. Each evaluation passes through the SAME per-address
    allowance the Fire now route has (20 a minute, 8 for an unsigned address), and a replay through the drill's
    five-an-hour allowance, so asking in chat is never a way around those limits (red team 2026-10-19). A refusal
    is a ``Busy`` the dog says out loud, with the seconds to wait."""
    firable = dog.kind in (common.KIND_USER, common.KIND_HOUSE)

    def gate_fire() -> None:
        if request is None:
            return
        try:
            _rl_fire_route(request, authorization)
        except HTTPException as exc:
            raise ask_eval.Busy("rate", _retry_of(exc))

    def fire_fn() -> dict:
        gate_fire()
        return _fire_payload(dog, viewer_id)

    def earlier_fn() -> dict:
        gate_fire()
        return ask_eval.earlier_today(dog)

    def backtest_fn(days: int) -> dict:
        if drill.peek(dog, days) is None and viewer_id is not None and request is not None:
            try:
                _rl_drill(request, types.SimpleNamespace(id=viewer_id))
            except HTTPException as exc:
                raise ask_eval.Busy("rate", _retry_of(exc))
        return ask_eval.backtest(dog, days, signed_in=viewer_id is not None)

    return camp.ask_context(dog, viewer_id, fire_fn=fire_fn if firable else None, tips=_graded_tips(dog),
                            earlier_fn=earlier_fn if firable else None,
                            backtest_fn=backtest_fn if firable else None)


@router.get("/hounds/{hound_id}/ask")
def ask_open(hound_id: str, response: Response, authorization: Optional[str] = Header(default=None),
             _rl: None = Depends(_rl_read)) -> dict:
    response.headers["Cache-Control"] = _NO_STORE
    dog = _dog(hound_id)
    ctx = camp.ask_context(dog, _viewer_id(authorization))
    hello = ask.answer("who are you", ctx)
    return envelope({"dog_id": dog.id, "dog_name": dog.name, "greeting": hello["lines"],
                     "suggestions": ask.suggestions(ctx), "warming": ctx.warming})


@router.post("/hounds/{hound_id}/ask")
def ask_dog(hound_id: str, body: AskRequest, response: Response,
            authorization: Optional[str] = Header(default=None), _rl: None = Depends(_rl_ask),
            request: Request = None) -> dict:
    response.headers["Cache-Control"] = _NO_STORE
    dog = _dog(hound_id)
    if dog.kind == common.KIND_USER:                         # Ask on a member dog: paid accounts only
        entitlements.paid_dog_tool_for(authorization, request, entitlements.FEATURE_ASK)
    question = (body.question or "").strip()
    if not question:
        raise _err(422, "question_required", "ask something")
    if len(question) > 300:
        raise _err(422, "question_too_long", "keep the question under 300 characters")
    return envelope(ask.answer(question, _context(dog, _viewer_id(authorization), request, authorization)))


# ---------------------------------------------------------------------------
# feedback and suggestions
# ---------------------------------------------------------------------------

class FeedbackRequest(BaseModel):
    target_kind: str
    target_id: Optional[str] = None
    verdict: str
    note: Optional[str] = None


def _feedback_error(exc: store.FeedbackError) -> HTTPException:
    return _err(exc.status, exc.code, str(exc))


def _check_target(dog: common.Dog, kind: str, target_id: str) -> None:
    """A vote lands on a thing that exists: a ticket this dog really has, a manual ticket, or an answer kind."""
    if kind == store.KIND_DOG:
        return
    if kind == store.KIND_ANSWER:
        if target_id not in ask.ANSWER_KINDS:
            raise _err(422, "target_invalid", "that is not one of the dog's answers")
        return
    if kind == store.KIND_MANUAL:
        if dog.kind != common.KIND_USER or target_id not in {t["bet_id"] for t in manual.tickets(dog.id)}:
            raise _err(404, "target_not_found", "no such manual ticket")
        return
    data = common.hound_data(dog)
    if data is None:
        raise _err(503, "warming_up", "the tickets are still loading; try again in a minute")
    keys = {ask.ticket_key(common.to_json(b)) for b in data.bets}
    if target_id not in keys:
        raise _err(404, "target_not_found", "no such ticket on this dog")


@router.get("/hounds/{hound_id}/feedback")
def feedback_read(hound_id: str, response: Response, authorization: Optional[str] = Header(default=None),
                  _rl: None = Depends(_rl_read)) -> dict:
    response.headers["Cache-Control"] = _NO_STORE
    dog = _dog(hound_id)
    viewer = _viewer_id(authorization)
    out = {"dog_id": dog.id, "counts": store.counts(dog.root_id)}
    if viewer is not None:
        out["my_votes"] = store.my_votes(dog.root_id, viewer)
        if dog.kind == common.KIND_USER and dog.owner_user_id == viewer:
            out["notes"] = store.notes_for_owner(dog.root_id)
            out["suggestions"] = store.suggestions_for_owner(dog.root_id)
    return envelope(out)


@router.post("/hounds/{hound_id}/feedback")
def feedback_write(hound_id: str, body: FeedbackRequest, response: Response,
                   current_user: users_store.User = Depends(get_current_user),
                   _rl: None = Depends(_rl_write)) -> dict:
    response.headers["Cache-Control"] = _NO_STORE
    dog = _dog(hound_id)
    try:
        target = store.clean_target(body.target_kind, body.target_id)
        note = store.clean_note(body.note)
        _check_target(dog, body.target_kind, target)
        saved = store.record_vote(hound_id=dog.id, root_id=dog.root_id, kind=body.target_kind, target_id=target,
                                  verdict=body.verdict, note=note, user_id=current_user.id)
    except store.FeedbackError as exc:
        raise _feedback_error(exc)
    return envelope({"saved": saved, "counts": store.counts(dog.root_id),
                     "note": "Feedback never changes a dog. It is counted, and the owner reads it."})


class SuggestRequest(BaseModel):
    change: Dict[str, Any]
    note: Optional[str] = None


@router.post("/hounds/{hound_id}/suggest")
def suggest_change(hound_id: str, body: SuggestRequest, response: Response,
                   current_user: users_store.User = Depends(get_current_user),
                   _rl: None = Depends(_rl_write)) -> dict:
    """A suggested change to a builder dog's rule, for its owner to read. It changes nothing by itself."""
    response.headers["Cache-Control"] = _NO_STORE
    dog = _dog(hound_id)
    if dog.kind != common.KIND_USER:
        raise _err(422, "not_a_builder_dog", "suggest changes to a house dog with the tip box on its page")
    if dog.owner_user_id == current_user.id:
        raise _err(409, "own_dog", "this is your dog: change it in the builder")
    change = dict(body.change or {})
    if not change or len(change) > 2 or any(k not in user_spec.RULE_FIELDS for k in change):
        raise _err(422, "change_invalid", "suggest one or two of the rule's own fields")
    candidate = dict(dog.spec)
    candidate.update(change)
    try:
        user_spec.validate_spec(candidate, taken_names=())
        note = store.clean_note(body.note)
        saved = store.record_suggestion(hound_id=dog.id, root_id=dog.root_id, change=change, note=note,
                                        user_id=current_user.id)
    except user_spec.SpecError as exc:
        raise _err(422, "change_invalid", "that change is not a rule the menu allows", fields=exc.errors)
    except store.FeedbackError as exc:
        raise _feedback_error(exc)
    return envelope({"saved": saved, "note": "Your suggestion goes to the owner. It changes nothing on its own."})


# ---------------------------------------------------------------------------
# the locker room
# ---------------------------------------------------------------------------

class LookRequest(BaseModel):
    look: Dict[str, Any]


@router.get("/hounds/{hound_id}/look")
def look_read(hound_id: str, response: Response, _rl: None = Depends(_rl_read)) -> dict:
    response.headers["Cache-Control"] = "public, max-age=30"
    dog = _dog(hound_id)
    return envelope({"dog_id": dog.id, "look": camp.look_of(dog), "menu": look.menu()})


@router.put("/hounds/{hound_id}/look")
def look_write(hound_id: str, body: LookRequest, response: Response,
               current_user: users_store.User = Depends(get_current_user),
               _rl: None = Depends(_rl_write)) -> dict:
    response.headers["Cache-Control"] = _NO_STORE
    dog = _owned(hound_id, current_user)
    try:
        clean = look.validate_look(body.look)
    except look.LookError as exc:
        raise _err(422, "look_invalid", "that look is not on the menu", fields=exc.errors)
    store.set_look(dog.root_id, clean, current_user.id)
    return envelope({"dog_id": dog.id, "look": clean})
