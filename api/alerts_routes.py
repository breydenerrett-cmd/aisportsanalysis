"""api/alerts_routes.py: bet-alert settings, the test button, push/SMS enrolment, the secret RSS feed and the one-click off link.

    GET  /me/alerts                     signed in. Status of every channel, the member's switches, quiet hours, feed URL.
    PUT  /me/alerts                     signed in. {channels:{email,push,sms,native}, event_toggles:{placed,starting,live,
                                        settled}, events (legacy), quiet_start, quiet_end, tz}.
    POST /me/alerts/test                signed in. {channel}: one sample alert, now.
    POST /me/alerts/push                signed in. {endpoint, keys:{p256dh, auth}}: save this browser's push subscription.
    POST /me/alerts/push/remove         signed in. {endpoint}.
    POST /me/alerts/sms                 signed in, PAID members only. {phone, consent:true}: the explicit opt-in. Texts a
                                        6-digit code to the number; nothing is stored on the account yet.
    POST /me/alerts/sms/verify          signed in, PAID members only. {code}: the number is stored only when the code
                                        texted to it is typed back (a member cannot make LINEHOUND text a stranger).
    POST /me/alerts/sms/remove          signed in. Forget the number.
    POST /me/alerts/feed/rotate         signed in. A new secret RSS address (the old one stops working).
    POST /me/alerts/device              signed in. {platform, token, app_version}: the native apps register here (stub channel).
    GET  /alerts/feed/{token}.xml       PUBLIC by secret token. The member's bet events as RSS (for Zapier "SMS by Zapier").
    GET|POST /alerts/off?t=             PUBLIC signed link from every alert email: turns EMAIL alerts off in one click.
    POST /alerts/sms/inbound            PUBLIC, Twilio-signed. STOP (and friends) switches the number off for good.

Nothing here returns a secret other than the member's OWN feed URL to that member. Text is escaped by the page, the RSS
writer and the email renderer; this module only moves data.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
import urllib.parse
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from api import auth as auth_mod
from api.auth import get_current_user
from api.email_routes import _page
from src.appstate import ratelimit
from src.appstate import users as users_store
from src.hounds import rss, unit_size
from src.hounds.contract import envelope
from src.notify import alert_channels as ch
from src.notify import alert_dispatch as dispatch
from src.notify import alert_render as render
from src.notify import alerts
from src.notify import email as mail
from src.notify import email_prefs as prefs_mod
from src.notify import webpush

router = APIRouter()

_read_limiter = ratelimit.FixedWindowLimiter(limit=120, window_s=60.0)
_rl_read = ratelimit.limiter_dependency(_read_limiter)
_write_limiter = ratelimit.FixedWindowLimiter(limit=60, window_s=3600.0)
_rl_write = ratelimit.limiter_dependency(_write_limiter, user_dependency=get_current_user)
_test_limiter = ratelimit.FixedWindowLimiter(limit=10, window_s=3600.0)
_rl_test = ratelimit.limiter_dependency(_test_limiter, user_dependency=get_current_user)
_sms_code_limiter = ratelimit.FixedWindowLimiter(limit=10, window_s=3600.0)
_rl_sms_code = ratelimit.limiter_dependency(_sms_code_limiter, user_dependency=get_current_user)
_public_limiter = ratelimit.FixedWindowLimiter(limit=60, window_s=60.0)
_rl_public = ratelimit.limiter_dependency(_public_limiter)

STOP_WORDS = ("STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT")
START_WORDS = ("START", "YES", "UNSTOP")
HELP_WORDS = ("HELP", "INFO")
HELP_TEXT = ("LINEHOUND bet alerts (paper bets only, 21+). Change them in Account, Alerts at linehound.app. "
             "Reply STOP to end, START to resume.")


class _HideFeedToken(logging.Filter):
    """uvicorn's access log prints the request path, and the secret feed address IS a path. Blank the token there."""
    _pattern = re.compile(r"/alerts/feed/[^/\s?\"]+")

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.args, tuple):
                record.args = tuple(self._pattern.sub("/alerts/feed/REDACTED.xml", a) if isinstance(a, str) else a
                                    for a in record.args)
            if isinstance(record.msg, str):
                record.msg = self._pattern.sub("/alerts/feed/REDACTED.xml", record.msg)
        except Exception:  # noqa: BLE001 -- a log filter must never break a request
            pass
        return True


logging.getLogger("uvicorn.access").addFilter(_HideFeedToken())

SMS_PAID_MESSAGE = "Text alerts are part of the member plan. Email and browser notifications are free."
FEED_ITEMS = 50


def _http():
    """The transport for the one text this module sends (the verification code). A test replaces this."""
    return mail.urllib_sender


def _mask_phone(phone: Optional[str]) -> Optional[str]:
    return f"***-***-{phone[-4:]}" if phone and len(phone) >= 4 else None


def _is_paid(user) -> bool:
    return not auth_mod.is_free_member(user)


def _feed_url(token: str) -> str:
    return f"{prefs_mod.base_url()}/alerts/feed/{token}.xml"


def _kind_channels() -> dict:
    """{event: channels that may carry it}, so the page can say "email: placed and settled only" without a copy of the rule."""
    return {kind: tuple(c for c in alerts.CHANNEL_NAMES if kind in alerts.CHANNEL_KINDS[c] and c != "native")
            for kind in alerts.KINDS}


def _payload(user) -> dict:
    prefs = alerts.ensure_prefs(user.id)
    paid = _is_paid(user)
    channels = []
    for name in alerts.CHANNEL_NAMES:
        channel = ch.CHANNELS[name]
        avail = channel.availability()
        ctx = ch.Ctx(user=user, prefs=prefs, events=[], sizing=None, batch_key="", http=None, paid=paid)
        entry = {"name": name, "label": channel.label, "available": avail["available"], "reason": avail["reason"],
                 "on": bool(prefs["channels"].get(name)), "has_target": bool(channel.has_target(ctx))}
        if name == "sms":
            entry["paid_only"] = True
            entry["allowed"] = paid
            entry["phone"] = _mask_phone(prefs["phone"])
            entry["opted_in"] = bool(prefs["phone"] and prefs["sms_consent_utc"])
            entry["stopped"] = prefs["sms_stopped"]
            entry["pending_phone"] = _mask_phone(alerts.sms_pending_phone(user.id))
        if name == "push":
            entry["public_key"] = webpush.public_key()
        channels.append(entry)
    return {"channels": channels, "events": prefs["events"], "event_toggles": prefs["event_toggles"],
            "event_channels": {k: list(v) for k, v in _kind_channels().items()}, "quiet_start": prefs["quiet_start"],
            "quiet_end": prefs["quiet_end"], "tz": prefs["tz"], "feed_url": _feed_url(prefs["feed_token"]),
            "sizing": unit_size.get(user.id).as_dict(), "paper_only": True,
            "ios_note": "On iPhone, add LINEHOUND to your Home Screen first (Share, then Add to Home Screen), "
                        "then turn notifications on from the app icon."}


def _error(exc: alerts.AlertError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"error": exc.code, "message": str(exc)})


@router.get("/me/alerts")
def get_alerts(response: Response, current_user: users_store.User = Depends(get_current_user),
               _rl: None = Depends(_rl_read)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return envelope(_payload(current_user))


class AlertsRequest(BaseModel):
    channels: Optional[Any] = None
    events: Optional[Any] = None
    event_toggles: Optional[Any] = None
    quiet_start: Optional[Any] = None
    quiet_end: Optional[Any] = None
    tz: Optional[Any] = None


@router.put("/me/alerts")
def put_alerts(body: AlertsRequest, response: Response, current_user: users_store.User = Depends(get_current_user),
               _rl: None = Depends(_rl_write)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    patch: dict = {}
    if isinstance(body.channels, dict):
        patch["channels"] = body.channels
        if body.channels.get("sms") and not _is_paid(current_user):
            raise HTTPException(status_code=402, detail={"error": "upgrade_required", "feature": "sms_alerts",
                                                         "message": SMS_PAID_MESSAGE})
    for key in ("events", "event_toggles", "quiet_start", "quiet_end", "tz"):
        if key in body.model_fields_set:
            patch[key] = getattr(body, key)
    try:
        alerts.update_prefs(current_user.id, patch)
    except alerts.AlertError as exc:
        raise _error(exc)
    return envelope(_payload(current_user))


class TestRequest(BaseModel):
    channel: Optional[Any] = None


@router.post("/me/alerts/test")
def test_alert(body: TestRequest, response: Response, current_user: users_store.User = Depends(get_current_user),
               _rl: None = Depends(_rl_test)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    channel = body.channel if isinstance(body.channel, str) else ""
    return envelope(dispatch.send_test(current_user, channel))


class PushRequest(BaseModel):
    endpoint: Optional[Any] = None
    keys: Optional[Any] = None


@router.post("/me/alerts/push")
def add_push(body: PushRequest, response: Response, current_user: users_store.User = Depends(get_current_user),
             _rl: None = Depends(_rl_write)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    keys = body.keys if isinstance(body.keys, dict) else {}
    try:
        alerts.add_push_subscription(current_user.id, str(body.endpoint or ""), str(keys.get("p256dh") or ""),
                                     str(keys.get("auth") or ""))
    except alerts.AlertError as exc:
        raise _error(exc)
    return envelope(_payload(current_user))


@router.post("/me/alerts/push/remove")
def remove_push(body: PushRequest, response: Response, current_user: users_store.User = Depends(get_current_user),
                _rl: None = Depends(_rl_write)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    alerts.remove_push_subscription(str(body.endpoint or ""), current_user.id)
    return envelope(_payload(current_user))


class SmsRequest(BaseModel):
    phone: Optional[Any] = None
    consent: Optional[Any] = None


@router.post("/me/alerts/sms")
def sms_opt_in(body: SmsRequest, response: Response, current_user: users_store.User = Depends(get_current_user),
               _rl: None = Depends(_rl_sms_code)) -> dict:
    """The explicit opt-in. Paid members only; ``consent`` must be literally true (the page's checkbox). The number is
    NOT stored yet: a 6-digit code is texted to it and ``/me/alerts/sms/verify`` stores it when typed back."""
    response.headers["Cache-Control"] = "no-store"
    if not _is_paid(current_user):
        raise HTTPException(status_code=402, detail={"error": "upgrade_required", "feature": "sms_alerts",
                                                     "message": SMS_PAID_MESSAGE})
    if body.consent is not True:
        raise HTTPException(status_code=422, detail={"error": "consent_required",
                                                     "message": "Tick the box to agree to receive texts."})
    if not ch.CHANNELS["sms"].availability()["available"]:
        raise HTTPException(status_code=503, detail={"error": "sms_unavailable",
                                                     "message": "Text alerts are not switched on yet."})
    try:
        number, code = alerts.sms_begin(current_user.id, str(body.phone or ""))
    except alerts.AlertError as exc:
        raise _error(exc)
    result = ch.CHANNELS["sms"].send_code(number, code, http=_http())
    if result.status != ch.S_SENT:
        alerts.sms_cancel_pending(current_user.id)
        raise HTTPException(status_code=502, detail={"error": "sms_not_sent",
                                                     "message": "We could not text that number. Check it and try again."})
    return envelope(_payload(current_user))


class VerifyRequest(BaseModel):
    code: Optional[Any] = None


@router.post("/me/alerts/sms/verify")
def sms_verify(body: VerifyRequest, response: Response, current_user: users_store.User = Depends(get_current_user),
               _rl: None = Depends(_rl_write)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    if not _is_paid(current_user):
        raise HTTPException(status_code=402, detail={"error": "upgrade_required", "feature": "sms_alerts",
                                                     "message": SMS_PAID_MESSAGE})
    try:
        alerts.sms_confirm(current_user.id, body.code)
    except alerts.AlertError as exc:
        raise _error(exc)
    return envelope(_payload(current_user))


@router.post("/me/alerts/sms/remove")
def sms_remove(response: Response, current_user: users_store.User = Depends(get_current_user),
               _rl: None = Depends(_rl_write)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    alerts.sms_remove(current_user.id)
    return envelope(_payload(current_user))


@router.post("/me/alerts/feed/rotate")
def rotate_feed(response: Response, current_user: users_store.User = Depends(get_current_user),
                _rl: None = Depends(_rl_write)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    alerts.rotate_feed_token(current_user.id)
    return envelope(_payload(current_user))


class DeviceRequest(BaseModel):
    platform: Optional[Any] = None
    token: Optional[Any] = None
    app_version: Optional[Any] = None


@router.post("/me/alerts/device")
def register_device(body: DeviceRequest, response: Response, current_user: users_store.User = Depends(get_current_user),
                    _rl: None = Depends(_rl_write)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        alerts.register_device(current_user.id, str(body.platform or ""), str(body.token or ""),
                               str(body.app_version or ""))
    except alerts.AlertError as exc:
        raise _error(exc)
    return envelope({"registered": True})


# ---------------------------------------------------------------------------
# public: the secret RSS feed
# ---------------------------------------------------------------------------

@router.get("/alerts/feed/{token}.xml")
def feed(token: str, _rl: None = Depends(_rl_public)) -> Response:
    """The member's bet events as RSS. The token in the path IS the credential (192 random bits); an unknown token is
    a plain 404 that says nothing about which tokens exist."""
    user_id = alerts.user_for_feed_token(token)
    if user_id is None:
        raise HTTPException(status_code=404, detail="not found")
    prefs = alerts.get_prefs(user_id)
    sizing = unit_size.get(user_id)
    items = []
    for event in alerts.events_for(user_id, limit=FEED_ITEMS):
        pub = alerts.parse_iso(event["created_utc"])
        p = event["payload"]
        items.append({"title": render.subject([event]), "link": render.hound_link(p["hound_id"]),
                      "guid": "alert-" + hashlib.sha256(f"{user_id}:{event['id']}".encode()).hexdigest()[:20], "pub": pub,
                      "description": render.event_line(event, sizing, prefs["tz"] if prefs else alerts.DEFAULT_TZ)
                      + ". Paper bet. 21+. 1-800-GAMBLER."})
    xml = rss.render(title="LINEHOUND bet alerts", link=prefs_mod.base_url() + "/web/",
                     description="Bets your hounds placed, are about to play, are playing and settled. Paper only.", items=items,
                     self_url=_feed_url(token))
    return Response(content=xml, media_type=rss.CONTENT_TYPE,
                    headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})


# ---------------------------------------------------------------------------
# public: one-click email off
# ---------------------------------------------------------------------------

def _email_off(token: str) -> bool:
    user_id = prefs_mod.verify(token)
    if user_id is None:
        return False
    if user_id and alerts.get_prefs(user_id) is not None:
        alerts.update_prefs(user_id, {"channels": {"email": False}})
    return True


@router.get("/alerts/off")
def alerts_off(t: str = Query("", max_length=100)) -> HTMLResponse:
    if not _email_off(t):
        return _page("This link is not valid", "Open the latest alert email and use its link.", 400)
    return _page("Email alerts off", "You will not get bet alert emails any more. You can turn them back on in "
                                      "Account, under Alerts.")


@router.post("/alerts/off")
def alerts_off_one_click(t: str = Query("", max_length=100)) -> PlainTextResponse:
    if not _email_off(t):
        return PlainTextResponse("invalid token", status_code=400)
    return PlainTextResponse("ok")


# ---------------------------------------------------------------------------
# public: Twilio inbound (STOP)
# ---------------------------------------------------------------------------

def twilio_signature(auth_token: str, url: str, params: dict) -> str:
    """Twilio's request signature: base64(HMAC-SHA1(token, url + each POST key and value sorted by key))."""
    data = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    return base64.b64encode(hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()).decode()


@router.post("/alerts/sms/inbound")
async def sms_inbound(request: Request, _rl: None = Depends(_rl_public)) -> Response:
    """Twilio posts every reply here (set as the number's 'A message comes in' webhook). The signature is checked
    against TWILIO_AUTH_TOKEN; with no token set the route does not exist (404). STOP, STOPALL, UNSUBSCRIBE, CANCEL,
    END and QUIT switch that number off; START (YES, UNSTOP) switches a verified number back on; HELP answers with
    one line; anything else is ignored. The answer is a TwiML document."""
    token = str(os.environ.get(ch.ENV_TOKEN) or "").strip()
    if not token:
        raise HTTPException(status_code=404, detail="not found")
    params = dict(urllib.parse.parse_qsl((await request.body()).decode("utf-8", "replace"), keep_blank_values=True))
    url = prefs_mod.base_url() + request.url.path
    sent = request.headers.get("X-Twilio-Signature", "")
    if not hmac.compare_digest(sent.encode(), twilio_signature(token, url, params).encode()):
        raise HTTPException(status_code=403, detail="bad signature")
    word = str(params.get("Body") or "").strip().upper()
    reply = ""
    if word in STOP_WORDS:
        alerts.sms_stop(str(params.get("From") or ""))
    elif word in START_WORDS:
        alerts.sms_start(str(params.get("From") or ""))
        reply = "LINEHOUND bet alerts are back on. Reply STOP to end."
    elif word in HELP_WORDS:
        reply = HELP_TEXT
    answer = f"<Message>{reply}</Message>" if reply else ""
    return Response(content=f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response>{answer}</Response>",
                    media_type="application/xml")
