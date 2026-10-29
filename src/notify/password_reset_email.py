"""The password-reset email: one message, built here, sent through src/notify/email.py.

Transactional, so no unsubscribe link (it is a reply to something the reader just
asked for). The link is the only secret in it; this module never logs it.
"""

from __future__ import annotations

from html import escape

from src.notify import email_render as render

KIND_PASSWORD_RESET = "password_reset"


def build(*, to: str, link: str, minutes: int) -> dict:
    body = (render._headline("Reset your password")
            + render._para(f"Someone asked to reset the password for this LINEHOUND account. The link works "
                           f"once and ends in {minutes} minutes.")
            + render._button("Choose a new password", link)
            + render._para("If that was not you, ignore this email. Nothing changes until the link is used."))
    footer = ('<tr><td style="padding:18px 28px 26px;border-top:1px solid #E5E7EB;font:13px/1.5 sans-serif;'
              'color:#6B7280">You are getting this because a password reset was requested for this address. '
              'If the button does not work, paste this into your browser: '
              f'<span style="word-break:break-all">{escape(link)}</span></td></tr>')
    text = "\n".join([
        "Reset your password", "",
        f"Someone asked to reset the password for this LINEHOUND account. The link works once and ends in {minutes} minutes.",
        "", f"Choose a new password: {link}", "",
        "If that was not you, ignore this email. Nothing changes until the link is used."])
    return {"to": to, "subject": "Reset your LINEHOUND password",
            "html": render._shell("Your reset link works once.", body, footer), "text": text + "\n"}
