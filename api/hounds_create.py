"""api/hounds_create.py: build-your-own hound. Create, list mine, retire, copy, scorecard, coach.

WHO CAN DO WHAT
---------------
  GET  /hounds/menu                 public    the fixed menu, so the web form is generated from it
  GET  /hounds/{id}/spec            public    a spec any signed-in user can POST back as their own
  GET  /hounds/{id}/scorecard       public    data for a reader or a coach (JSON, or ?format=text)
  GET  /hounds/{id}/coach/diary     public    the Houndmaster's rounds and the coach metrics
  POST /hounds                      signed in (free members too): create or copy. A free account keeps ONE dog
                                    (402 upgrade_required for a second); paid accounts run up to five
  GET  /hounds/mine                 signed in: the caller's hounds
  GET  /hounds/builder/menu         public    everything a custom-rules spec may contain, with bounds
  POST /hounds/english              public    plain English -> spec draft (the free parser); a signed-in caller
                                              also gets a Zapier translation job for what it could not read
  POST /hounds/english/callback     the Zap    X-Zap-Secret header; 404 when no secret is configured
  GET  /hounds/english/{job_id}     signed in: poll a translation job (its owner only)
  POST /hounds/builder/preview      public    what a spec would bet on today's board (read-only)
  POST /hounds/{id}/diff            the owner  plain-English difference before saving an edit
  POST /hounds/{id}/version         the owner  save an edit as the next version (the old record stays)
  POST /hounds/{id}/retire          the owner, or an admin (X-Admin-Token) for moderation
  POST /hounds/{id}/coach/opt-in    the owner
  POST /hounds/{id}/coach/undo      the owner
  POST /hounds/{id}/coach/round     an admin: opens a signed round (secret returned once)
  POST /hounds/{id}/coach           the Houndmaster: signed proposal, no bearer token. A proposal creates a
                                    CHALLENGER (shadow run, judged by the referee); it never changes the hound
                                    (docs/PREREG_LEARNING_LOOP.md)

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
split as every other pairing here. A hound's summary IS the shared HoundSummary of src/hounds/contract.py
(kind "user"), built by the public stats and the pre-registered referee (src/hounds/user_view.py), plus a
few owner-only extras; this module computes no record, CLV or verdict of its own.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from src.appstate import freshness, ratelimit
from src.appstate import users as users_store
from src.hounds import user_coach, user_defs, user_engine, user_engine_v2, user_spec, user_store, user_view
from src.hounds.english import jobs as english_jobs
from src.hounds.english import parser as english_parser
from src.hounds.english import render as english_render
from src.hounds.english import translate as english_translate

from api import auth as auth_mod
from api.auth import get_current_user, require_member_access

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

# The free parser is cheap but is still an open door; the preview reads the day's boards. By client
# address, since a signed-out visitor drafts too.
ENGLISH_RATE_LIMIT_PER_MIN = 30
_english_limiter = ratelimit.FixedWindowLimiter(limit=ENGLISH_RATE_LIMIT_PER_MIN, window_s=60.0)
_rate_limit_english = ratelimit.limiter_dependency(_english_limiter)
PREVIEW_RATE_LIMIT_PER_MIN = 20
_preview_limiter = ratelimit.FixedWindowLimiter(limit=PREVIEW_RATE_LIMIT_PER_MIN, window_s=60.0)
_rate_limit_preview = ratelimit.limiter_dependency(_preview_limiter)
# Each translation is a Zapier task on the owner's plan: a person gets a handful an hour.
TRANSLATE_PER_USER_PER_HOUR = 8
_translate_limiter = ratelimit.FixedWindowLimiter(limit=TRANSLATE_PER_USER_PER_HOUR, window_s=3600.0)
MAX_CALLBACK_BYTES = 64 * 1024

# One slate (the day's boards, facts and game keys) shared by every preview of that date. Building it
# holds the process-wide build gate (SingleFlightTTLCache does), so a preview is never the second heavy
# thing running on the 1 GB machine.
_slate_cache = freshness.SingleFlightTTLCache(ttl_s=120.0, stale_while_revalidate_s=300.0)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _wrap(payload: dict) -> dict:
    out = dict(payload)
    out.update(PAPER)
    return out


def _owner_display(owner_user_id: int) -> str:
    return user_defs.owner_display(owner_user_id)


def hound_summary(hound: dict, *, verified: Optional[bool] = None) -> dict:
    """The shared hound summary (src/hounds/contract.py ``HoundSummary``) for a user hound, plus the
    fields only the owner's surfaces need.

    EVERYTHING PUBLIC COMES FROM THE ONE REFEREE. record, clv, verdict, verified, replay, first/last
    bet, status and retired are ``src.hounds.stats`` (CLV by ``src.report.clv``, label by
    ``src.hounds.verdict``); this module computes none of them. ``verified`` in the summary is the referee's (was the recorded price on
    the board at lock); ``ledger_chain_ok`` is this ledger's hash chain, a different question."""
    out = user_view.summary(hound)
    spec = hound["spec"]
    out.update({
        "ledger_chain_ok": user_engine.ledger_verified() if verified is None else verified,
        "version_no": hound["version_no"], "version_of": hound["version_of"],
        "copied_from": hound["copied_from"], "coach_opt_in": hound["coach_opt_in"],
        "retire_reason": hound["retire_reason"], "created_at": hound["created_at"],
        "removed_by_owner": user_store.removed_by_owner(hound),
        # Send to training / Take them out back (owner ruling 2026-10-20): the "Trained xN" badge and the burial flag.
        "buried": hound["status"] == user_store.STATUS_BURIED, "coached_from": hound.get("coached_from"),
        "trained_times": user_store.trained_count(hound["root_id"]),
        "paper_only": True, "not_advice": user_spec.NOT_ADVICE,
        # How the dog looks, and its rules in sentences, wherever a dog is listed.
        "color": spec.get("color", "ember"), "badge": spec.get("badge", "bone"),
        "custom_rules": user_spec.is_v2(spec), "root_id": hound["root_id"],
    })
    return out


def owner_summary(hound: dict, *, verified: Optional[bool] = None) -> dict:
    """The summary plus what the builder needs to open this dog for editing: its spec as a version-2
    draft (a classic dog is upgraded to the equivalent) and the rules in sentences."""
    out = hound_summary(hound, verified=verified)
    draft = hound["spec"] if user_spec.is_v2(hound["spec"]) else user_spec.upgrade_v1(hound["spec"])
    out["spec"] = draft
    try:
        out["rule_sentences"] = (english_render.rule_sentences(draft) + english_render.global_sentences(draft)
                                 if draft.get("rules") else [])
    except (KeyError, TypeError):
        out["rule_sentences"] = []
    return out


def bare_owner_summary(hound: dict) -> dict:
    """The least a dog's owner needs to see and edit it, built from the store row alone. Used when the full summary
    (record, verdict, ledger) cannot be built for one dog: one dog whose numbers fail must never take the whole
    list down, because the list is what the builder's Edit and Remove buttons are made from."""
    try:
        spec = hound["spec"] if user_spec.is_v2(hound["spec"]) else user_spec.upgrade_v1(hound["spec"])
    except (KeyError, TypeError, ValueError):
        spec = None
    try:
        sentences = (english_render.rule_sentences(spec) + english_render.global_sentences(spec)) if spec and spec.get("rules") else []
    except (KeyError, TypeError):
        sentences = []
    base = hound["spec"] if isinstance(hound.get("spec"), dict) else {}
    return {"id": hound["id"], "name": hound["name"], "tagline": hound.get("tagline") or "", "status": hound["status"],
            "version_no": hound["version_no"], "version_of": hound["version_of"], "root_id": hound["root_id"],
            "retire_reason": hound["retire_reason"], "removed_by_owner": user_store.removed_by_owner(hound),
            "buried": hound["status"] == user_store.STATUS_BURIED, "coached_from": hound.get("coached_from"),
            "created_at": hound["created_at"], "color": base.get("color", "ember"), "badge": base.get("badge", "bone"),
            "custom_rules": user_spec.is_v2(base), "record": {}, "spec": spec, "rule_sentences": sentences,
            "summary_unavailable": True, "paper_only": True, "not_advice": user_spec.NOT_ADVICE}


def _spec_error(exc: user_spec.SpecError) -> HTTPException:
    return HTTPException(status_code=422, detail={"error": "spec_invalid", "fields": exc.errors})


def _store_error(exc: user_store.StoreError) -> HTTPException:
    status = {"limit": 409, "no_account": 403, "account_suspended": 403, "not_found": 404,
              "unknown_source": 404, "reason_required": 422, "retired": 409,
              "coach_unsupported": 409,
              # a free account adding a second dog: payment, not permission (api/entitlements.py)
              "upgrade_required": 402}.get(exc.code, 400)
    detail = {"error": exc.code, "message": str(exc)}
    if exc.code == "upgrade_required":
        detail["feature"] = "more_dogs"
    return HTTPException(status_code=status, detail=detail)


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


def _send_keep_email(user: users_store.User, hound: dict) -> None:
    """THE KEEP CONFIRMATION HOOK (docs/owner/RESEND_ATTACH.md). The keep flow on the quiz and the builder makes the account
    first (POST /auth/signup) and saves the dog second, so at signup time there is no dog to name: the dog is saved HERE, and
    this is the one place that knows both the account and the dog. It sends the Keep email only for the account's FIRST dog
    ever (a second, or a copy, is not a "keep"), on a background thread so the save never waits for Resend, and it never
    changes the save's answer: any failure is logged and dropped. A no-op while RESEND_API_KEY is unset; the mail layer
    also refuses to send a second Keep email to the same user."""
    try:
        if len(user_store.list_for_owner(user.id)) != 1:
            return
        from src.notify import email_jobs
        email_jobs.send_keep_confirmation_async(user, hound)
    except Exception as exc:  # noqa: BLE001 -- an email problem must never fail a save
        print(f"hounds: keep email hook failed: {exc!r}", file=sys.stderr, flush=True)


class CreateHoundRequest(BaseModel):
    spec: Dict[str, Any]
    copied_from: Optional[str] = None
    coach_opt_in: bool = False


@router.post("/hounds")
def create_hound(body: CreateHoundRequest,
                 current_user: users_store.User = Depends(require_member_access),
                 _rl: None = Depends(_rate_limit_create)) -> dict:
    # A FREE account keeps one dog (owner decision 2026-10-20). The store applies the limit inside its creating
    # transaction; this only says which kind of account is asking. Comps, subscribers inside their period,
    # testers and invited beta users are "paid" (src/appstate/access.py), so they are never held to it.
    free = auth_mod.is_free_member(current_user)
    try:
        hound = user_store.create_hound(current_user.id, body.spec, copied_from=body.copied_from,
                                        coach_opt_in=body.coach_opt_in, free_tier=free)
    except user_spec.SpecError as exc:
        raise _spec_error(exc)
    except user_store.StoreError as exc:
        raise _store_error(exc)
    _send_keep_email(current_user, hound)
    return _wrap({"hound": hound_summary(hound)})


@router.get("/hounds/mine")
def my_hounds(current_user: users_store.User = Depends(get_current_user),
              _rl: None = Depends(_rate_limit_read)) -> dict:
    verified = user_engine.ledger_verified()
    out = []
    for h in user_store.list_for_owner(current_user.id):
        try:
            out.append(owner_summary(h, verified=verified))
        except Exception:  # noqa: BLE001 -- one dog's broken summary must not hide the rest (or their Edit / Remove)
            out.append(bare_owner_summary(h))
    # `limit_running` is THIS account's limit (1 for a free account, 5 for a paid one) so the builder
    # never shows a free member "0 of 5"; `plan` says which it is.
    free = auth_mod.is_free_member(current_user)
    return _wrap({"hounds": out, "plan": "free" if free else "paid",
                  "limit_running": (user_spec.FREE_MAX_ACTIVE_PER_ACCOUNT if free
                                    else user_spec.MAX_RUNNING_PER_ACCOUNT)})


@router.get("/hounds/{hound_id}/spec")
def hound_spec(hound_id: str, _rl: None = Depends(_rate_limit_read)) -> dict:
    """The spec to POST back as your own: a copy is a new hound carrying `copied_from`. The name
    is suggested fresh, because names are unique."""
    hound = _public_hound(hound_id)
    spec = dict(hound["spec"])
    if not user_spec.is_v2(spec):
        spec.pop("version", None)
    spec["name"] = user_store.suggest_copy_name(hound["name"])
    draft = hound["spec"] if user_spec.is_v2(hound["spec"]) else user_spec.upgrade_v1(hound["spec"])
    draft = dict(draft, name=spec["name"])
    sentences = (english_render.rule_sentences(draft) + english_render.global_sentences(draft)) if draft.get("rules") else []
    return _wrap({"spec": spec, "draft": draft, "rule_sentences": sentences, "copied_from": hound["id"],
                  "rule_text": user_spec.rule_text(hound["spec"]),
                  "how": "POST /hounds with {\"spec\": <this spec>, \"copied_from\": <copied_from>}"})


class RetireRequest(BaseModel):
    # An owner's removal needs no words (the button says what it does); an admin's moderation retirement must
    # carry one, and the store refuses an empty reason.
    reason: Optional[str] = None


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
    reason = body.reason if (body.reason or "").strip() else (user_store.OWNER_REMOVED_REASON if actor.startswith("owner:") else "")
    try:
        retired = user_store.retire_hound(hound["id"], by=actor, reason=reason)
    except user_store.StoreError as exc:
        raise _store_error(exc)
    return _wrap({"hound": hound_summary(retired)})


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
    try:
        hound = user_store.set_coach_opt_in(hound_id, body.enabled)
    except user_store.StoreError as exc:
        raise _store_error(exc)
    return _wrap({"hound": hound_summary(hound)})


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
    return _wrap({"retired": hound_summary(out["retired"]),
                  "resumed": hound_summary(out["resumed"])})


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
    return _wrap({
        "decision": out["decision"], "reason": out["reason"], "quip": out["quip"],
        "hound": hound_summary(out["hound"]),
        "new_hound": hound_summary(out["new_hound"]) if out["new_hound"] else None,
        "challenger": out.get("challenger"),
    })


# ---------------------------------------------------------------------------
# the builder: menu, English, preview, edit
# ---------------------------------------------------------------------------

@router.get("/hounds/builder/menu")
def builder_menu(_rl: None = Depends(_rate_limit_read)) -> dict:
    """Everything a version-2 spec may contain, with bounds: the builder page, the English parser and
    the AI translator's output check are all generated from, and validated against, this."""
    return _wrap(user_spec.builder_menu())


def _optional_user_id(authorization: Optional[str]) -> Optional[int]:
    return auth_mod.optional_user_id(authorization)


class EnglishRequest(BaseModel):
    text: str


@router.post("/hounds/english")
def english_to_spec(body: EnglishRequest, authorization: Optional[str] = Header(default=None),
                    _rl: None = Depends(_rate_limit_english)) -> dict:
    """Plain English into a version-2 spec draft.

    The free deterministic parser runs first, on every call, and answers instantly. If it could not
    read everything and the owner has switched the Zapier translator on, a signed-in caller also gets a
    translation job (poll GET /hounds/english/{job_id}); a signed-out caller is told to sign in for it.
    With the translator off, the answer says plainly which words were not understood. The result is
    always a DRAFT: the page shows it as sentences and rule cards to confirm and edit.

    THE DRAFT NEVER DEPENDS ON THE TRANSLATOR (2026-10-19, a member's long strategy left the builder looking
    dead). Every outcome of the translation side (no hook, signed out, rate limited, job started) is a 200
    that still carries the parser's draft, what it understood and did not, what it assumed and its
    suggestions, with `translation.status` saying what the second reader is doing. The only refusals are an
    empty text and a text over the limit, and each says so in words."""
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail={"error": "text_required", "message": "Type a strategy first."})
    if len(text) > english_parser.MAX_TEXT:
        raise HTTPException(status_code=422, detail={
            "error": "text_too_long", "max": english_parser.MAX_TEXT, "length": len(text),
            "message": (f"That is {len(text)} characters and the limit is {english_parser.MAX_TEXT}. Shorten it, or "
                        "send it as a few shorter sentences.")})
    parsed = english_parser.parse(text)
    out = {"status": "parsed" if parsed["complete"] else "partial", "text": text, **parsed}
    out["unread"] = [c["text"] for c in parsed["not_understood"] if c.get("text")]
    if parsed["complete"]:
        return _wrap(out)
    out["translation"] = {"status": "unavailable"}
    if english_translate.hook_url() is None:
        out["message"] = ("I could not read " + (", ".join(f"\"{t}\"" for t in out["unread"]) or "any of that") +
                          ". The rule cards below let you finish it by hand.")
        return _wrap(out)
    user_id = _optional_user_id(authorization)
    if user_id is None:
        out["translation"] = {"status": "sign_in_required"}
        out["message"] = ("Sign in and I can have the translator take a second look at what I could not read; "
                          "meanwhile the rule cards below let you finish it by hand.")
        return _wrap(out)
    check = _translate_limiter.check(ratelimit.key_for(f"user:{user_id}"))
    if not check.allowed:
        wait = max(1, int(round((check.retry_after or 0) / 60.0)))
        out["translation"] = {"status": "rate_limited", "retry_after": check.retry_after, "per_hour": TRANSLATE_PER_USER_PER_HOUR}
        out["message"] = (f"You have used all {TRANSLATE_PER_USER_PER_HOUR} second-reader tries for this hour (more in about "
                          f"{wait} minute{'' if wait == 1 else 's'}). Here is what I could read; finish the rest with the "
                          "rule cards or rephrase.")
        return _wrap(out)
    job = english_jobs.create_job(user_id, text, partial={
        "understood": parsed["understood"], "not_understood": parsed["not_understood"]})
    english_translate.start(job["id"], text)
    out.update({"job_id": job["id"], "status": english_jobs.STATUS_TRANSLATING,
                "translation": {"status": english_jobs.STATUS_TRANSLATING, "job_id": job["id"]},
                "message": "Part of that needs a second look; the translator is on it. The rest is below."})
    return _wrap(out)


class CallbackRequest(BaseModel):
    job_id: str
    spec_json: Any = None


@router.post("/hounds/english/callback")
async def english_callback(request: Request, x_zap_secret: Optional[str] = Header(default=None),
                           _rl: None = Depends(_rate_limit_read)) -> dict:
    """The owner's Zap posts the translation here. 404 when no secret is configured (the door does not
    exist), 401 for a wrong or missing secret (compared in constant time), then the answer is treated as
    untrusted text: cut to the menu's fields and validated like a form post."""
    expected = english_translate.callback_secret()
    if expected is None:
        raise HTTPException(status_code=404, detail="not found")
    if not x_zap_secret or not secrets.compare_digest(x_zap_secret.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=401, detail={"error": "bad_secret"})
    raw = await request.body()
    if len(raw) > MAX_CALLBACK_BYTES:
        raise HTTPException(status_code=413, detail={"error": "too_large"})
    try:
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("job_id"), str):
            raise ValueError("job_id required")
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=422, detail={"error": "bad_body"})
    status, body = english_translate.complete(data["job_id"], data.get("spec_json"))
    if status != 200:
        raise HTTPException(status_code=status, detail=body)
    return body


@router.get("/hounds/english/{job_id}")
def english_job(job_id: str, current_user: users_store.User = Depends(get_current_user),
                _rl: None = Depends(_rate_limit_read)) -> dict:
    """Poll a translation job. Only the person who started it can read it; anyone else sees not found."""
    job = english_jobs.get_job(job_id)
    if job is None or job["user_id"] != current_user.id:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    if job["status"] == english_jobs.STATUS_TRANSLATING and english_jobs.is_expired(job):
        english_jobs.finish(job_id, english_jobs.STATUS_FAILED, error="the translation took too long")
        job = english_jobs.get_job(job_id)
    return _wrap(english_translate.poll_payload(job))


class PreviewRequest(BaseModel):
    spec: Dict[str, Any]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _eastern_today(now: datetime) -> str:
    from src.pipeline import snapshots
    return snapshots.official_date(now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))


def _slate_for(date: str, with_props: bool) -> "user_engine_v2.Slate":
    slate, _meta = _slate_cache.get(
        ("slate", date, with_props),
        lambda: user_engine_v2.build_slate(date, user_spec.SPORTS, with_props=with_props))
    return slate


@router.post("/hounds/builder/preview")
def builder_preview(body: PreviewRequest, _rl: None = Depends(_rate_limit_preview)) -> dict:
    """What this spec would bet on today's board. READ-ONLY: it validates, evaluates against the boards
    as they stand now (a game that has not reached its lock is read on the newest board and flagged
    `locked: false`) and returns the picks. It writes no bet, no hound and no ledger row."""
    raw = dict(body.spec)
    if not str(raw.get("name") or "").strip():
        raw["name"] = "Draft Dog"
    try:
        spec = user_spec.validate_spec(raw)
    except user_spec.SpecError as exc:
        raise _spec_error(exc)
    if not user_spec.is_v2(spec):
        spec = user_spec.validate_spec({**user_spec.upgrade_v1(spec), "name": "Draft Dog"})
    from src.hounds import user_rules
    with_props = any(user_rules.market_kind(m) == "prop" for r in spec["rules"] for m in r["markets"])
    now = _now()
    date = _eastern_today(now)
    try:
        slate = _slate_for(date, with_props)
    except Exception as exc:  # noqa: BLE001 -- a board that cannot be read is a plain "not available"
        raise HTTPException(status_code=503, detail={"error": "board_unavailable", "message": type(exc).__name__})
    result = user_engine_v2.preview(spec, slate.games, slate.facts, date, now, game_pk_index=slate.game_pk_index)
    result.update({"sentences": english_render.rule_sentences(spec) + english_render.global_sentences(spec),
                   "spec": {k: v for k, v in spec.items() if k != "name" or raw["name"] != "Draft Dog"},
                   "games_on_board": len(slate.games), "board_size": len(slate.games), "board_observed_utc": slate.newest_observed(),
                   "as_of": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "read_only": True,
                   "note": "A preview from the board as it stands now. A game's bet is decided at its own decision time."})
    return _wrap(result)


class VersionRequest(BaseModel):
    spec: Dict[str, Any]
    reason: Optional[str] = None


@router.post("/hounds/{hound_id}/diff")
def hound_diff(hound_id: str, body: PreviewRequest, current_user: users_store.User = Depends(get_current_user),
               _rl: None = Depends(_rate_limit_manage)) -> dict:
    """The plain-English difference between this dog and a spec the owner is about to save as its next
    version. Nothing is saved."""
    hound = _owned(hound_id, current_user)
    try:
        new_spec = user_spec.validate_spec(
            body.spec, taken_names=[n for n in user_store.taken_names()
                                    if user_spec._fold(n) != user_spec._fold(hound["name"])])
    except user_spec.SpecError as exc:
        raise _spec_error(exc)
    return _wrap({"hound_id": hound_id, "changes": english_render.diff_specs(hound["spec"], new_spec),
                  "rule_sentences": (english_render.rule_sentences(new_spec) + english_render.global_sentences(new_spec)
                                     if user_spec.is_v2(new_spec) else [user_spec.rule_text(new_spec)])})


@router.post("/hounds/{hound_id}/version")
def hound_new_version(hound_id: str, body: VersionRequest,
                      current_user: users_store.User = Depends(get_current_user),
                      _rl: None = Depends(_rate_limit_manage)) -> dict:
    """Save an edit as the next version of a dog. The old version is retired with its record intact and
    the new one carries on under the same name (existing versioning, user_store.create_version)."""
    hound = _owned(hound_id, current_user)
    reason = " ".join((body.reason or "edited by its owner").split())[:120] or "edited by its owner"
    try:
        new = user_store.create_version(hound_id, body.spec, actor=f"owner:{current_user.id}", reason=reason)
    except user_spec.SpecError as exc:
        raise _spec_error(exc)
    except user_store.StoreError as exc:
        raise _store_error(exc)
    return _wrap({"hound": owner_summary(new), "previous_id": hound_id,
                  "changes": english_render.diff_specs(hound["spec"], new["spec"])})
