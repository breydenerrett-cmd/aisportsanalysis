"""The alert channels, behind one small interface so a new one slots in beside the others.

A CHANNEL answers four questions: is it available on this server (``availability``), does THIS member have a
place to send to (``has_target``), deliver a batch of events (``deliver``), and deliver a test (``deliver_test``).
The dispatcher (alert_dispatch.py) knows nothing else about a channel, so adding "native push" for the
Capacitor apps is: fill in ``NativePushChannel.deliver`` (APNs/FCM) and ship the app that calls
``alerts.register_device``. Nothing in the dispatcher, the preferences or the UI changes.

  email   Resend, through the existing sender (src/notify/email.py). Off while RESEND_API_KEY is unset.
  push    Web Push + VAPID (src/notify/webpush.py). Off while VAPID_PRIVATE_KEY is unset.
  sms     Twilio. WRITTEN BUT OFF unless TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_FROM are all set.
          A PAID-MEMBER feature (owner decision 2026-10-21). A number is stored only after an explicit opt-in and a
          STOP reply (or Twilio's own 21610 refusal) switches the member off for good until they opt in again.
  native  STUB. Reads the device-token table (alerts.alert_devices) and sends nothing yet.

RESULTS. ``sent`` (delivered to at least one target), ``retry`` (a transient failure: try again with backoff),
``skipped`` (nothing to send to, or the member may not use it: final, not counted against the rate cap) and
``dead`` (the provider refused for good). A channel never raises; the dispatcher also guards it.
"""

from __future__ import annotations

import base64
import os
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from src.notify import alert_render as render
from src.notify import alerts
from src.notify import email as mail
from src.notify import webpush

S_SENT, S_RETRY, S_SKIPPED, S_DEAD = "sent", "retry", "skipped", "dead"

ENV_SID, ENV_TOKEN, ENV_FROM = "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM"
TWILIO_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
TWILIO_STOPPED_CODE = 21610            # "this number replied STOP to your sender"


@dataclass
class Result:
    status: str
    detail: str = ""


@dataclass
class Ctx:
    """Everything a channel needs for one send. ``http`` is the injected transport (tests never touch the network)."""
    user: Any                                     # users_store.User
    prefs: Mapping
    events: Sequence[Mapping]
    sizing: Any                                   # unit_size.Sizing
    batch_key: str
    http: Callable
    env: Optional[Mapping] = None
    now: Optional[datetime] = None
    paid: bool = False
    off_url: str = ""
    settings_url: str = ""
    sleep: Callable[[float], None] = lambda _s: None
    extra: Dict[str, Any] = field(default_factory=dict)


class Channel:
    name = ""
    label = ""

    def availability(self, env: Optional[Mapping] = None) -> dict:
        return {"available": True, "reason": ""}

    def has_target(self, ctx: Ctx) -> bool:
        return True

    def deliver(self, ctx: Ctx) -> Result:
        raise NotImplementedError

    def deliver_test(self, ctx: Ctx) -> Result:
        raise NotImplementedError


class EmailChannel(Channel):
    name, label = "email", "Email"

    def availability(self, env=None) -> dict:
        if not mail.enabled(env):
            return {"available": False, "reason": "Email is not set up on this server yet."}
        return {"available": True, "reason": ""}

    def has_target(self, ctx: Ctx) -> bool:
        from src.notify import email_jobs
        return email_jobs.deliverable(getattr(ctx.user, "email", None))

    def _send(self, ctx: Ctx, message: dict, kind: str) -> Result:
        answer = mail.send(message, user_id=ctx.user.id, kind=kind, date=ctx.batch_key, http=ctx.http, env=ctx.env,
                           sleep=ctx.sleep, now=ctx.now)
        status = answer["status"]
        if status in (mail.R_SENT, mail.R_DUPLICATE):
            return Result(S_SENT)
        if status == mail.R_GAVE_UP:
            return Result(S_DEAD, "gave up")
        if status == mail.R_DISABLED:
            return Result(S_SKIPPED, "email disabled")
        http_status = answer.get("http")
        if isinstance(http_status, int) and 400 <= http_status < 500 and http_status != 429:
            return Result(S_DEAD, f"refused {http_status}")
        return Result(S_RETRY, f"http {http_status}")

    def deliver(self, ctx: Ctx) -> Result:
        message = render.email_message(to=ctx.user.email, events=ctx.events, sizing=ctx.sizing, tz=ctx.prefs["tz"],
                                       off_url=ctx.off_url, settings_url=ctx.settings_url, env=ctx.env)
        return self._send(ctx, message, "alert")

    def deliver_test(self, ctx: Ctx) -> Result:
        return self._send(ctx, render.sample_message(to=ctx.user.email, off_url=ctx.off_url,
                                                     settings_url=ctx.settings_url), "alert-test")


class WebPushChannel(Channel):
    name, label = "push", "Browser and phone notifications"

    def availability(self, env=None) -> dict:
        return webpush.status(env)

    def has_target(self, ctx: Ctx) -> bool:
        return bool(alerts.push_subscriptions(ctx.user.id))

    def _fan_out(self, ctx: Ctx, payload: dict) -> Result:
        subs = alerts.push_subscriptions(ctx.user.id)
        if not subs:
            return Result(S_SKIPPED, "no subscription")
        sent = failed = 0
        for sub in subs:
            outcome = webpush.send(sub, payload, http=ctx.http, env=ctx.env)
            if outcome == webpush.R_SENT:
                sent += 1
                alerts.mark_push_ok(sub["endpoint"], now=ctx.now)
            elif outcome == webpush.R_GONE:
                alerts.remove_push_subscription(sub["endpoint"], ctx.user.id)
            elif outcome == webpush.R_DISABLED:
                return Result(S_SKIPPED, "push disabled")
            else:
                failed += 1
        if sent:
            return Result(S_SENT)
        return Result(S_RETRY, "push failed") if failed else Result(S_SKIPPED, "subscription gone")

    def deliver(self, ctx: Ctx) -> Result:
        return self._fan_out(ctx, render.push_payload(ctx.events, ctx.sizing, ctx.prefs["tz"], ctx.env))

    def deliver_test(self, ctx: Ctx) -> Result:
        from src.notify import email_prefs
        return self._fan_out(ctx, {"title": "Test alert from LINEHOUND", "body": "This is a test. No bet was made.",
                                   "url": email_prefs.base_url(ctx.env) + "/web/", "tag": "bet-alert-test",
                                   "paper": True})


class SmsChannel(Channel):
    name, label = "sms", "Text messages"

    def availability(self, env=None) -> dict:
        source = env if env is not None else os.environ
        missing = [k for k in (ENV_SID, ENV_TOKEN, ENV_FROM) if not str(source.get(k) or "").strip()]
        if missing:
            return {"available": False, "reason": "Text alerts are not switched on yet."}
        return {"available": True, "reason": ""}

    def has_target(self, ctx: Ctx) -> bool:
        p = ctx.prefs
        return bool(p.get("phone") and p.get("sms_consent_utc") and not p.get("sms_stopped"))

    def _post(self, ctx: Ctx, text: str) -> Result:
        if not ctx.paid:
            return Result(S_SKIPPED, "text alerts are for paid members")
        if not self.has_target(ctx):
            return Result(S_SKIPPED, "no opted-in number")
        source = ctx.env if ctx.env is not None else os.environ
        sid, token, sender = (str(source.get(k) or "").strip() for k in (ENV_SID, ENV_TOKEN, ENV_FROM))
        body = urllib.parse.urlencode({"To": ctx.prefs["phone"], "From": sender, "Body": text}).encode()
        basic = base64.b64encode(f"{sid}:{token}".encode()).decode()
        headers = {"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded",
                   "User-Agent": mail.USER_AGENT}
        code, answer = ctx.http(TWILIO_URL.format(sid=sid), headers, body, mail.TIMEOUT_S)
        if 200 <= code < 300:
            return Result(S_SENT)
        if code == 400 and str(TWILIO_STOPPED_CODE).encode() in (answer or b""):
            alerts.sms_stop(ctx.prefs["phone"], now=ctx.now)
            return Result(S_SKIPPED, "member replied STOP")
        if code == 0 or code == 429 or code >= 500:
            return Result(S_RETRY, f"http {code}")
        return Result(S_DEAD, f"refused {code}")

    def deliver(self, ctx: Ctx) -> Result:
        return self._post(ctx, render.sms_text(ctx.events, ctx.sizing, ctx.prefs["tz"], ctx.env))

    def deliver_test(self, ctx: Ctx) -> Result:
        return self._post(ctx, "LINEHOUND test alert. No bet was made. Reply STOP to end.")


class NativePushChannel(Channel):
    """STUB for the Capacitor apps (APNs on iOS, FCM on Android). It reads the device tokens the app registered and
    reports 'not released' until a sender is written; to finish it, replace ``deliver`` and flip ``availability``."""
    name, label = "native", "Mobile app notifications"

    def availability(self, env=None) -> dict:
        return {"available": False, "reason": "The mobile app is not released yet."}

    def has_target(self, ctx: Ctx) -> bool:
        return bool(alerts.active_devices(ctx.user.id))

    def deliver(self, ctx: Ctx) -> Result:
        return Result(S_SKIPPED, "native push not implemented")

    def deliver_test(self, ctx: Ctx) -> Result:
        return Result(S_SKIPPED, "native push not implemented")


CHANNELS: Dict[str, Channel] = {c.name: c for c in (EmailChannel(), WebPushChannel(), SmsChannel(), NativePushChannel())}
assert tuple(CHANNELS) == alerts.CHANNEL_NAMES
