"""api/email_routes.py: the unsubscribe link and the owner's two email admin routes.

    GET  /email/unsubscribe?t=<signed token>   PUBLIC. One click turns this user's nightly result and Sunday pack off.
    POST /email/unsubscribe?t=<signed token>   PUBLIC. The same, for a mail client's own Unsubscribe button
                                               (RFC 8058 one-click: the message carries List-Unsubscribe-Post).
    GET  /admin/email/status                   X-Admin-Token. Enabled or not, the loop, the last runs, send counts.
    POST /admin/email/test   {"to": address}   X-Admin-Token. Sends the admin a test message.

THE UNSUBSCRIBE LINK is a GET that changes state on purpose: the compliance ask is one click from an email, and
a mail client's link-preview can follow it. That is the accepted trade for one-click, and the flag it flips is
only "stop emailing this person". The token (src/notify/email_prefs.py) is signed, can only do that one thing,
and never signs anyone in. A token that does not verify gets a plain 400 page; a token that verifies for an
account that does not exist gets the same page as one that does (nothing to learn about which ids are real).

The admin routes reuse ``api.auth._require_admin`` like api/admin.py: no ``APP_ADMIN_TOKEN`` set means 404.
Neither admin response contains the key, a full address or a message body.
"""

from __future__ import annotations

from html import escape
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from api.auth import _require_admin
from src.appstate import users as users_store
from src.notify import email as mail
from src.notify import email_jobs
from src.notify import email_prefs as prefs

router = APIRouter()

_PAGE = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
         "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
         "<meta name=\"robots\" content=\"noindex\"><title>LINEHOUND emails</title></head>"
         "<body style=\"margin:0;background:#0B0C0E;color:#F2F4F8;font:16px/1.55 -apple-system,Segoe UI,Arial,sans-serif\">"
         "<main style=\"max-width:520px;margin:12vh auto;padding:0 20px\">"
         "<p style=\"letter-spacing:.14em;font-weight:700\">LINE<span style=\"color:#00E0FF\">HOUND</span></p>"
         "<h1 style=\"font-size:22px\">{title}</h1><p>{body}</p>"
         "<p><a style=\"color:#00E0FF\" href=\"{home}\">Back to LINEHOUND</a></p>"
         "<p style=\"color:#8A919E;font-size:13px\">21+ · Paper bets only, not advice · "
         "<a style=\"color:#8A919E\" href=\"tel:+18004262537\">1-800-GAMBLER</a></p></main></body></html>")


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(_PAGE.format(title=escape(title), body=escape(body), home=escape(prefs.base_url())),
                        status_code=status, headers={"Cache-Control": "no-store"})


def _pause(token: str) -> bool:
    """True when ``token`` verifies (whether or not it matched a real account)."""
    user_id = prefs.verify(token)
    if user_id is None:
        return False
    if user_id and users_store.get_user(user_id) is not None:
        prefs.set_unsubscribed(user_id, True)
    return True


@router.get("/email/unsubscribe")
def unsubscribe(t: str = Query("", max_length=100)) -> HTMLResponse:
    if not _pause(t):
        return _page("This link is not valid",
                     "It may have been cut off when it was copied. Open the latest email and use its link.", 400)
    return _page("Emails paused",
                 "You will not get the nightly result or the Sunday summary any more. Your hounds keep playing "
                 "and their record stays public. If you want the emails back, use Get help on the support page.")


@router.post("/email/unsubscribe")
def unsubscribe_one_click(t: str = Query("", max_length=100)) -> PlainTextResponse:
    if not _pause(t):
        return PlainTextResponse("invalid token", status_code=400)
    return PlainTextResponse("ok")


@router.get("/admin/email/status")
def email_status(_admin: None = Depends(_require_admin)) -> dict:
    return email_jobs.status_report()


class TestEmailRequest(BaseModel):
    to: Optional[Any] = None


@router.post("/admin/email/test")
def email_test(body: TestEmailRequest, _admin: None = Depends(_require_admin)) -> dict:
    """Send the admin a test message. The address is whatever the admin typed; it is masked in the answer."""
    to = body.to.strip() if isinstance(body.to, str) else ""
    if not mail.enabled():
        mail.note_disabled()
        return {"sent": False, "status": "disabled",
                "detail": f"{mail.ENV_KEY} is not set on this app, so nothing was sent."}
    result = email_jobs.send_admin_test(to)
    if result.get("status") == "invalid_address":
        raise HTTPException(status_code=400, detail="Enter a valid email address in \"to\".")
    return {"sent": result["status"] == mail.R_SENT, "status": result["status"], "http": result.get("http"),
            "to": result.get("to"), "id": result.get("id")}
