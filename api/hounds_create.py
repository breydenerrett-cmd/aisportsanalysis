"""api/hounds_create.py: build-your-own hound. Create, list mine, retire, copy, scorecard, coach.

WHO CAN DO WHAT
---------------
  GET  /hounds/menu                 public    the fixed menu, so the web form is generated from it
  GET  /hounds/{id}/spec            public    a spec any signed-in user can POST back as their own
  GET  /hounds/{id}/scorecard       public    data for a reader or a coach (JSON, or ?format=text)
  GET  /hounds/{id}/coach/diary     public    the Houndmaster's rounds and the coach metrics
  POST /hounds                      signed in (paid or early-access tester): create or copy
  GET  /hounds/mine                 signed in: the caller's hounds
  POST /hounds/{id}/retire          the owner, or an admin (X-Admin-Token) for moderation
  POST /hounds/{id}/coach/opt-in    the owner
  POST /hounds/{id}/coach/undo      the owner
  POST /hounds/{id}/coach/round     an admin: opens a signed round (secret returned once)
  POST /hounds/{id}/coach           the Houndmaster: signed proposal, no bearer token

ROUTE ORDER MATTERS
-------------------
`/hounds/menu` and `/hounds/mine` are literal paths under `/hounds/{id}`. This router must be
mounted BEFORE any router that declares `GET /hounds/{id}` (api/app.py does), or "menu" would be
read as a hound id.

EVERY PAYLOAD IS PAPER ONLY
---------------------------
Every response carries `paper_only: true` and the not-advice line. Nothing here places, queues or
suggests a real bet; a hound is a rule whose simulated picks are recorded and graded.

Thin wiring: all logic lives in src/hounds (user_spec, user_store, user_coach), same api/ <-> src/
split as every other pairing here. The summary shape matches the shared hound summary
(kind "user"); the house-hound worker's contract module supersedes the local assembly when it lands.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from src.appstate import ratelimit
from src.appstate import users as users_store
from src.hounds import user_coach, user_engine, user_settle, user_spec, user_store

from api import auth as auth_mod
from api.auth import get_current_user, require_paid_access

router = APIRouter()

PAPER = {"paper_only": True, "not_advice": user_spec.NOT_ADVICE}

# 10 creations an hour per signed-in user is far above a person's real use (three running hounds
# is the cap) and low enough to blunt a script churning names.
CREATE_RATE_LIMIT_PER_HOUR = 10
_create_limiter = ratelimit.FixedWindowLimiter(limit=CREATE_RATE_LIMIT_PER_HOUR, window_s=3600.0)
_rate_limit_create = ratelimit.limiter_dependency(_create_limiter, user_dependency=get_current_user)

MANAGE_RATE_LIMIT_PER_HOUR = 30
_manage_limiter = ratelimit.FixedWindowLimiter(limit=MANAGE_RATE_LIMIT_PER_HOUR, window_s=3600.0)
_rate_limit_manage = ratelimit.limiter_dependency(_manage_limiter, user_dependency=get_current_user)

# Public reads and the signed coach door key on the client address.
READ_RATE_LIMIT_PER_MIN = 60
_read_limiter = ratelimit.FixedWindowLimiter(limit=READ_RATE_LIMIT_PER_MIN, window_s=60.0)
_rate_limit_read = ratelimit.limiter_dependency(_read_limiter)

COACH_RATE_LIMIT_PER_MIN = 10
_coach_limiter = ratelimit.FixedWindowLimiter(limit=COACH_RATE_LIMIT_PER_MIN, window_s=60.0)
_rate_limit_coach = ratelimit.limiter_dependency(_coach_limiter)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _wrap(payload: dict) -> dict:
    out = dict(payload)
    out.update(PAPER)
    return out


def _owner_display(owner_user_id: int) -> str:
    digest = hashlib.sha256(f"hound-owner:{owner_user_id}".encode()).hexdigest()[:4].upper()
    return f"Handler {digest}"


def hound_summary(hound: dict, records: Optional[dict] = None, *, verified: Optional[bool] = None) -> dict:
    """The shared hound-summary shape for a user hound."""
    spec = hound["spec"]
    rec = (records or {}).get(hound["id"])
    empty = {"bets": 0, "wins": 0, "losses": 0, "pushes": 0, "voids": 0,
             "units_recorded_price": 0.0, "units_average_price": 0.0}
    return {
        "id": hound["id"], "name": hound["name"], "tagline": hound["tagline"], "kind": "user",
        "owner_display": _owner_display(hound["owner_user_id"]),
        "sport": "/".join(spec["sports"]), "sports": spec["sports"], "markets": spec["markets"],
        "rule_text": user_spec.rule_text(spec), "status": hound["status"],
        "record": (rec or {}).get("record") or empty,
        "clv": (rec or {}).get("clv"),
        "verdict": user_settle.verdict_for(rec),
        "first_bet_utc": (rec or {}).get("first_bet_utc"),
        "last_bet_utc": (rec or {}).get("last_bet_utc"),
        "verified": user_engine.ledger_verified() if verified is None else verified,
        "version_no": hound["version_no"], "version_of": hound["version_of"],
        "copied_from": hound["copied_from"], "coach_opt_in": hound["coach_opt_in"],
        "retire_reason": hound["retire_reason"], "created_at": hound["created_at"],
        "paper_only": True, "not_advice": user_spec.NOT_ADVICE,
    }


def _records() -> dict:
    return user_settle.records_by_hound(user_engine.read_ledger())


def _spec_error(exc: user_spec.SpecError) -> HTTPException:
    return HTTPException(status_code=422, detail={"error": "spec_invalid", "fields": exc.errors})


def _store_error(exc: user_store.StoreError) -> HTTPException:
    status = {"limit": 409, "no_account": 403, "account_suspended": 403, "not_found": 404,
              "unknown_source": 404, "reason_required": 422, "retired": 409}.get(exc.code, 400)
    return HTTPException(status_code=status, detail={"error": exc.code, "message": str(exc)})


def _coach_error(exc: user_coach.CoachError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"error": exc.code, "message": str(exc)})


def _owned(hound_id: str, user: users_store.User) -> dict:
    hound = user_store.get_hound(hound_id)
    if hound is None or hound["owner_user_id"] != user.id:
        # Not-yours reads exactly like not-there: no probing for other people's hound ids.
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return hound


def _public_hound(hound_id: str) -> dict:
    hound = user_store.get_hound(hound_id)
    if hound is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return hound


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------

@router.get("/hounds/menu")
def hounds_menu(_rl: None = Depends(_rate_limit_read)) -> dict:
    return _wrap(user_spec.menu())


class CreateHoundRequest(BaseModel):
    spec: Dict[str, Any]
    copied_from: Optional[str] = None
    coach_opt_in: bool = False


@router.post("/hounds")
def create_hound(body: CreateHoundRequest,
                 current_user: users_store.User = Depends(require_paid_access),
                 _rl: None = Depends(_rate_limit_create)) -> dict:
    try:
        hound = user_store.create_hound(current_user.id, body.spec, copied_from=body.copied_from,
                                        coach_opt_in=body.coach_opt_in)
    except user_spec.SpecError as exc:
        raise _spec_error(exc)
    except user_store.StoreError as exc:
        raise _store_error(exc)
    return _wrap({"hound": hound_summary(hound, {})})


@router.get("/hounds/mine")
def my_hounds(current_user: users_store.User = Depends(get_current_user),
              _rl: None = Depends(_rate_limit_read)) -> dict:
    records = _records()
    verified = user_engine.ledger_verified()
    return _wrap({"hounds": [hound_summary(h, records, verified=verified)
                             for h in user_store.list_for_owner(current_user.id)],
                  "limit_running": user_spec.MAX_RUNNING_PER_ACCOUNT})


@router.get("/hounds/{hound_id}/spec")
def hound_spec(hound_id: str, _rl: None = Depends(_rate_limit_read)) -> dict:
    """The spec to POST back as your own: a copy is a new hound carrying `copied_from`. The name
    is suggested fresh, because names are unique."""
    hound = _public_hound(hound_id)
    spec = dict(hound["spec"])
    spec.pop("version", None)
    spec["name"] = user_store.suggest_copy_name(hound["name"])
    return _wrap({"spec": spec, "copied_from": hound["id"], "rule_text": user_spec.rule_text(hound["spec"]),
                  "how": "POST /hounds with {\"spec\": <this spec>, \"copied_from\": <copied_from>}"})


class RetireRequest(BaseModel):
    reason: str


@router.post("/hounds/{hound_id}/retire")
def retire_hound(hound_id: str, body: RetireRequest,
                 authorization: Optional[str] = Header(default=None),
                 x_admin_token: Optional[str] = Header(default=None),
                 request: Request = None) -> dict:
    """The owner retires their own hound; an admin retires any hound (moderation) with a reason."""
    if x_admin_token:
        auth_mod._require_admin(x_admin_token)
        actor = "admin"
        hound = _public_hound(hound_id)
    else:
        user = get_current_user(authorization, request)
        _manage_check(user)
        hound = _owned(hound_id, user)
        actor = f"owner:{user.id}"
    try:
        retired = user_store.retire_hound(hound["id"], by=actor, reason=body.reason)
    except user_store.StoreError as exc:
        raise _store_error(exc)
    return _wrap({"hound": hound_summary(retired, _records())})


def _manage_check(user: users_store.User) -> None:
    result = _manage_limiter.check(ratelimit.key_for(f"user:{user.id}"))
    if not result.allowed:
        raise HTTPException(status_code=429, detail={"error": "rate_limited",
                                                      "retry_after": result.retry_after})


@router.get("/hounds/{hound_id}/scorecard")
def hound_scorecard(hound_id: str, format: str = "json", _rl: None = Depends(_rate_limit_read)):
    """Data for a reader or a coach. Everything is rebuilt from the ledger; the notice says it is
    data, not instructions."""
    card = user_coach.scorecard(hound_id)
    if card is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    if format == "text":
        return PlainTextResponse(user_coach.scorecard_text(card))
    return _wrap({"scorecard": card})


# ---------------------------------------------------------------------------
# the Houndmaster door
# ---------------------------------------------------------------------------

class OptInRequest(BaseModel):
    enabled: bool


@router.post("/hounds/{hound_id}/coach/opt-in")
def coach_opt_in(hound_id: str, body: OptInRequest,
                 current_user: users_store.User = Depends(get_current_user),
                 _rl: None = Depends(_rate_limit_manage)) -> dict:
    _owned(hound_id, current_user)
    hound = user_store.set_coach_opt_in(hound_id, body.enabled)
    return _wrap({"hound": hound_summary(hound, _records())})


@router.post("/hounds/{hound_id}/coach/undo")
def coach_undo(hound_id: str, current_user: users_store.User = Depends(get_current_user),
               _rl: None = Depends(_rate_limit_manage)) -> dict:
    _owned(hound_id, current_user)
    try:
        out = user_coach.undo(hound_id)
    except user_coach.CoachError as exc:
        raise _coach_error(exc)
    except user_store.StoreError as exc:
        raise _store_error(exc)
    records = _records()
    return _wrap({"retired": hound_summary(out["retired"], records),
                  "resumed": hound_summary(out["resumed"], records)})


@router.get("/hounds/{hound_id}/coach/diary")
def coach_diary(hound_id: str, _rl: None = Depends(_rate_limit_read)) -> dict:
    _public_hound(hound_id)
    return _wrap({"diary": user_coach.diary(hound_id)})


@router.post("/hounds/{hound_id}/coach/round")
def coach_round(hound_id: str, x_admin_token: Optional[str] = Header(default=None)) -> dict:
    auth_mod._require_admin(x_admin_token)
    try:
        return _wrap({"round": user_coach.issue_round(hound_id, issued_by="admin")})
    except user_coach.CoachError as exc:
        raise _coach_error(exc)


@router.post("/hounds/{hound_id}/coach")
async def coach_submit(hound_id: str, request: Request,
                       x_coach_round: Optional[str] = Header(default=None),
                       x_coach_ts: Optional[str] = Header(default=None),
                       x_coach_sig: Optional[str] = Header(default=None),
                       _rl: None = Depends(_rate_limit_coach)) -> dict:
    """The only door a machine may change a hound through. The body is read as raw bytes because
    the signature covers it exactly; it carries only spec, reason and quip."""
    body = (await request.body()).decode("utf-8", errors="replace")
    return _coach_submit_sync(hound_id, x_coach_round, x_coach_ts, x_coach_sig, body)


def _coach_submit_sync(hound_id, round_id, ts, sig, body) -> dict:
    try:
        out = user_coach.submit(hound_id, round_id=round_id, ts=ts, sig=sig, body=body)
    except user_coach.CoachError as exc:
        raise _coach_error(exc)
    records = _records()
    return _wrap({
        "decision": out["decision"], "reason": out["reason"], "quip": out["quip"],
        "hound": hound_summary(out["hound"], records),
        "new_hound": hound_summary(out["new_hound"], records) if out["new_hound"] else None,
    })
